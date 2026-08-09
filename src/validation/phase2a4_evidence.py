"""Build local, provenance-bound Phase 2A.4 candidate evidence.

The collector evaluates the fixed drought, cloud-mask, and same-day
composition registry on the unchanged Phase 2A.3 cases.  It reads public
Sentinel-2, CHIRPS, and accepted-baseline objects only.  It does not create
canonical acquisition/observation/event identities, update operational state,
select a method, or mutate the frozen parent package.

Every queried scene stays in the source set.  Missing assets, read failures,
low coverage, and unavailable rainfall are retained in the eight-cell record;
the collector never substitutes a case or silently drops a scene.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import json
import math
import platform
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

import numpy as np
import PIL
import pyproj
import pystac
import pystac_client
import rasterio
import scipy
from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image, ImageDraw
from pyproj import Transformer
from rasterio.enums import Resampling as RioResampling
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as transform_geometry

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import (
    canonical_geometry_sha256,
    canonical_json_bytes,
    canonical_sha256,
    identity_sha256,
)
from src.validation.package import write_canonical_json
from src.validation.phase2a4 import (
    CompositionCandidateConfig,
    CompositionScene,
    DroughtCandidateConfig,
    MaskCandidateConfig,
    apply_mask_policy,
    canonical_array_record,
    compose_coverage_ranked_first_valid,
    compose_min_cloudprob_sclrank_sceneid,
    compute_season_matched_spi3,
)
from src.validation.phase2a4_rainfall import load_rainfall_monthly_values
from src.validation.validator import validate_validation_package


SCHEMA_VERSION = "1.0.0"
EVIDENCE_ARTIFACT_TYPE = "phase2a4_candidate_evidence"
EVIDENCE_PIPELINE_VERSION = "phase2a4-candidate-evidence-v1"
EVIDENCE_MANIFEST_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a4-candidate-evidence-manifest-v1.schema.json"
)
EVIDENCE_CASE_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a4-candidate-evidence-case-v1.schema.json"
)
EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
SENTINEL_COLLECTION = "sentinel-2-l2a"
REQUIRED_ASSETS = (
    "blue",
    "red",
    "nir",
    "nir08",
    "swir16",
    "swir22",
    "scl",
    "cloud",
)
REFLECTANCE_ASSETS = REQUIRED_ASSETS[:6]
INDEX_NAMES = ("evi2", "nbr", "ndmi")
COMPARISON_PADDING_M = 500.0
SHADOW_CONTEXT_HALO_M = 1060.0
MINIMUM_VALID_COVERAGE = 0.20
GRID_CRS = "EPSG:32724"
GRID_WIDTH = 10773
GRID_HEIGHT = 4999
GRID_TRANSFORM = Affine(20.0, 0.0, 290080.0, 0.0, -20.0, 9231780.0)
GRID_BOUNDS = (290080.0, 9131800.0, 505540.0, 9231780.0)
BASELINE_MANIFEST_SHA256 = "15a1ed3cea7c804d18d2c82c86a7b9a030687fedb01b315d543965b1f26f0a82"
PHASE2A3_MANIFEST_SHA256 = "4b78167930fcb7a928b40d50ae1d54675e4cca47a10857bcbf28db803c18946b"
_URL_QUERY = re.compile(r"(https?://[^?\s'\"<>]+)\?[^\s'\"<>]+")
_URL_USERINFO = re.compile(r"(https?://)[^/@\s]+@")
_CHECKSUM_LINE = re.compile(r"^(?P<sha>[0-9a-f]{64})  (?P<path>[^\n]+)$")
_HTTP_FIELDS = (
    "status_code",
    "content_length",
    "etag",
    "last_modified",
    "content_type",
    "accept_ranges",
)
_SOURCE_READ_MODE = "remote_raster_range_read_to_aligned_context_window"
_SOURCE_CHECKSUM_LIMITATION = (
    "local_window_data_sha256_does_not_verify_full_remote_asset"
)
_ASSET_HREF_RESOLUTION_POLICY = (
    "earth-search-provider-https-or-fixed-public-s3-bucket-to-https-v1"
)
_PUBLIC_S3_HTTPS_BASES = {
    "sentinel-cogs": "https://sentinel-cogs.s3.us-west-2.amazonaws.com",
    "sentinel-s2-l2a": "https://sentinel-s2-l2a.s3.amazonaws.com",
}
_BASELINE_READ_MODE = "remote_cog_range_read_to_aligned_context_window"
_REFLECTANCE_NORMALIZATION_POLICY = {
    "policy_version": "sentinel2-l2a-stac-scale-offset-zero-fill-nonnegative-v1",
    "scale_offset_source": "raster:bands[0].scale_and_offset_required",
    "raw_zero_fill": "invalid_before_resampling_and_scaling",
    "negative_scaled_reflectance": "clip_to_zero",
    "output_dtype": "float32",
}
_LOCAL_WINDOW_CANONICALIZATION = (
    "normalized_decoded_values_plus_validity_and_normalization_"
    "RFC8785_SHA256_on_fixed_grid_aligned_context_window_v1"
)


class Phase2A4EvidenceError(ValueError):
    """Raised when evidence inputs violate the fixed Package 2A.4 contract."""


@dataclass(frozen=True)
class Phase2A4EvidenceConfig:
    """All external inputs and fixed generation metadata for one evidence run."""

    output_dir: Path
    parent_package_dir: Path
    candidate_registry_path: Path
    rainfall_artifact_dir: Path
    baseline_manifest_path: Path
    baseline_public_base_url: str
    generated_at: str
    catalog_accessed_at: str
    workers: int = 4
    comparison_padding_m: float = COMPARISON_PADDING_M
    shadow_context_halo_m: float = SHADOW_CONTEXT_HALO_M

    def __post_init__(self) -> None:
        for label in ("generated_at", "catalog_accessed_at"):
            value = getattr(self, label)
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise Phase2A4EvidenceError(
                    f"{label} must be an explicit timezone-aware RFC3339 value"
                ) from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise Phase2A4EvidenceError(f"{label} must include a UTC offset")
        if not 1 <= self.workers <= 12:
            raise Phase2A4EvidenceError("workers must be in [1, 12]")
        if self.comparison_padding_m != COMPARISON_PADDING_M:
            raise Phase2A4EvidenceError("comparison padding is fixed at 500 m")
        if self.shadow_context_halo_m != SHADOW_CONTEXT_HALO_M:
            raise Phase2A4EvidenceError("shadow context halo is fixed at 1060 m")
        base = _unsigned_url(self.baseline_public_base_url.rstrip("/"))
        if not base.startswith("https://"):
            raise Phase2A4EvidenceError("baseline public base URL must use HTTPS")
        object.__setattr__(self, "baseline_public_base_url", base)


def _safe_error(value: BaseException | str, limit: int = 500) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = _URL_QUERY.sub(r"\1?[query-redacted]", text)
    text = _URL_USERINFO.sub(r"\1[userinfo-redacted]@", text)
    return text[:limit]


def _unsigned_url(value: str) -> str:
    parts = urlsplit(str(value))
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _artifact(path: Path, root: Path, **extra: Any) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        **extra,
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2A4EvidenceError(f"cannot parse {path}: {exc}") from exc


def _validate_schema(value: Any, schema: Mapping[str, Any], label: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise Phase2A4EvidenceError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _safe_artifact_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise Phase2A4EvidenceError(f"unsafe artifact path: {relative}")
    path = (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise Phase2A4EvidenceError(f"artifact path escapes root: {relative}") from exc
    return path


def _verify_artifact(path: Path, root: Path, record: Mapping[str, Any]) -> None:
    if (
        path != _safe_artifact_path(root, str(record["path"]))
        or not path.is_file()
        or path.stat().st_size != record["bytes"]
        or sha256_file(path) != record["sha256"]
    ):
        raise Phase2A4EvidenceError(f"artifact mismatch: {record.get('path')}")


def _generator_source_inventory(repository_root: Path) -> list[dict[str, Any]]:
    paths = (
        repository_root / "config" / "settings.py",
        repository_root / "src" / "detection" / "baseline.py",
        repository_root / "src" / "detection" / "baseline_manifest.py",
        repository_root / "src" / "detection" / "change_detect.py",
        repository_root / "src" / "detection" / "identity.py",
        repository_root / "src" / "detection" / "scene_quality.py",
        repository_root / "src" / "processing" / "indices.py",
        repository_root / "src" / "validation" / "phase2a4_evidence.py",
        repository_root / "src" / "validation" / "phase2a4.py",
        repository_root / "src" / "validation" / "phase2a4_rainfall.py",
        repository_root / "src" / "validation" / "package.py",
        repository_root / "src" / "validation" / "validator.py",
        repository_root / "scripts" / "build_phase2a4_evidence.py",
        repository_root / "scripts" / "validate_phase2a4_evidence.py",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-candidate-evidence-manifest-v1.schema.json",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-candidate-evidence-case-v1.schema.json",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-candidate-registry-v1.schema.json",
    )
    if any(not path.is_file() for path in paths):
        raise Phase2A4EvidenceError("candidate evidence generator source is missing")
    return [_artifact(path, repository_root) for path in paths]


def _npy_storage_array(array: np.ndarray) -> np.ndarray:
    """Return the exact canonical array representation persisted in NPY files."""
    value = np.asarray(array)
    if value.dtype.kind == "f":
        value = np.array(value, dtype="<f4", order="C", copy=True)
        value[value == 0.0] = 0.0
        value[np.isnan(value)] = np.nan
    elif value.dtype.kind == "b":
        value = np.ascontiguousarray(value.astype(np.bool_, copy=False))
    elif value.dtype.kind in "iu":
        if value.dtype.itemsize == 1:
            value = np.ascontiguousarray(value)
        else:
            value = np.ascontiguousarray(value.astype("<i4", copy=False))
    else:
        raise TypeError("NPY evidence arrays must be numeric or boolean")
    return value


def _write_npy(path: Path, array: np.ndarray) -> None:
    """Write deterministic, pickle-free NPY bytes."""
    value = _npy_storage_array(array)
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stream.getvalue())


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "pyproj": pyproj.__version__,
        "pystac": pystac.__version__,
        "pystac-client": pystac_client.__version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "scipy": scipy.__version__,
        "shapely": distribution_version("shapely"),
        "jsonschema": distribution_version("jsonschema"),
    }


def _reference_grid_record() -> dict[str, Any]:
    return {
        "crs": GRID_CRS,
        "width": GRID_WIDTH,
        "height": GRID_HEIGHT,
        "transform": [20.0, 0.0, 290080.0, 0.0, -20.0, 9231780.0],
        "bounds": list(GRID_BOUNDS),
        "pixel_size_m": 20,
    }


def _window_from_geometry(geometry_wgs84: Mapping[str, Any]) -> dict[str, Any]:
    transformer = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
    projected = transform_geometry(transformer.transform, shape(geometry_wgs84))
    if projected.is_empty or not projected.is_valid:
        raise Phase2A4EvidenceError("target geometry is empty or invalid")
    minx, miny, maxx, maxy = projected.bounds

    def grid_window(padding: float) -> tuple[int, int, int, int]:
        col0 = math.floor((minx - padding - GRID_TRANSFORM.c) / GRID_TRANSFORM.a)
        col1 = math.ceil((maxx + padding - GRID_TRANSFORM.c) / GRID_TRANSFORM.a)
        row0 = math.floor((GRID_TRANSFORM.f - (maxy + padding)) / -GRID_TRANSFORM.e)
        row1 = math.ceil((GRID_TRANSFORM.f - (miny - padding)) / -GRID_TRANSFORM.e)
        col0 = max(0, min(GRID_WIDTH - 1, col0))
        row0 = max(0, min(GRID_HEIGHT - 1, row0))
        col1 = max(col0 + 1, min(GRID_WIDTH, col1))
        row1 = max(row0 + 1, min(GRID_HEIGHT, row1))
        return col0, row0, col1 - col0, row1 - row0

    comp_col, comp_row, comp_width, comp_height = grid_window(COMPARISON_PADDING_M)
    context_extra = COMPARISON_PADDING_M + SHADOW_CONTEXT_HALO_M
    ctx_col, ctx_row, ctx_width, ctx_height = grid_window(context_extra)

    comparison_transform = GRID_TRANSFORM * Affine.translation(comp_col, comp_row)
    comparison_bounds = rasterio.transform.array_bounds(
        comp_height, comp_width, comparison_transform
    )
    core = {
        "column_offset": comp_col,
        "row_offset": comp_row,
        "width": comp_width,
        "height": comp_height,
        "transform": list(comparison_transform)[:6],
        "bounds": list(comparison_bounds),
        "pixel_size_m": 20,
        "aligned_to_reference_grid": True,
        "same_window_for_all_factorial_cells": True,
        "fixed_before_candidate_evaluation": True,
    }
    core["window_definition_sha256"] = canonical_sha256(core)

    context_transform = GRID_TRANSFORM * Affine.translation(ctx_col, ctx_row)
    context_bounds = rasterio.transform.array_bounds(ctx_height, ctx_width, context_transform)
    comparison_mask = np.zeros((ctx_height, ctx_width), dtype=bool)
    relative_col = comp_col - ctx_col
    relative_row = comp_row - ctx_row
    comparison_mask[
        relative_row : relative_row + comp_height,
        relative_col : relative_col + comp_width,
    ] = True
    return {
        "reference_grid": _reference_grid_record(),
        "case_window": core,
        "context_window": {
            "column_offset": ctx_col,
            "row_offset": ctx_row,
            "width": ctx_width,
            "height": ctx_height,
            "transform": list(context_transform)[:6],
            "bounds": list(context_bounds),
            "auxiliary_halo_m": SHADOW_CONTEXT_HALO_M,
            "comparison_offset_in_context": [relative_col, relative_row],
        },
        "comparison_mask": comparison_mask,
        "coverage_contract": {
            "denominator_pixel_rule": "all_pixels_in_fixed_grid_aligned_case_window",
            "valid_pixel_rule": (
                "finite_required_reflectance_after_candidate_mask_and_composition_"
                "and_at_least_one_configured_index_with_finite_current_baseline_"
                "mean_and_std"
            ),
            "valid_coverage_formula": "valid_pixel_count/case_window_pixel_count",
            "minimum_valid_coverage_fraction": MINIMUM_VALID_COVERAGE,
        },
    }


def _query_geometry(window: Mapping[str, Any]) -> dict[str, Any]:
    inverse = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)
    projected = box(*window["case_window"]["bounds"])
    # Normalize Shapely coordinate tuples to JSON arrays before hashing and
    # passing the same payload to the STAC client.
    return json.loads(
        json.dumps(
            mapping(transform_geometry(inverse.transform, projected)),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _query_record(target_date: str, query_geometry: Mapping[str, Any]) -> dict[str, Any]:
    day = dt.date.fromisoformat(target_date)
    next_day = day + dt.timedelta(days=1)
    interval = f"{day.isoformat()}T00:00:00Z/{next_day.isoformat()}T00:00:00Z"
    request_payload = {
        "stac_endpoint": EARTH_SEARCH,
        "collection": SENTINEL_COLLECTION,
        "intersects": query_geometry,
        "datetime": interval,
        "query": {"eo:cloud_cover": {"lt": 60}},
        "max_items": None,
        "pagination_policy": "all_pages_until_exhausted",
    }
    query = {
        "target_date": target_date,
        "spatial_filter": "intersects_fixed_grid_aligned_case_window",
        "temporal_filter": "target_date_inclusive_to_next_date_exclusive",
        "eo_cloud_cover_lt": 60,
        "intersects": copy.deepcopy(query_geometry),
        "datetime": interval,
        "result_limit": None,
        "pagination_policy": "all_pages_until_exhausted",
        "intersects_geometry_sha256": canonical_geometry_sha256(query_geometry)[1],
        "canonical_payload_sha256": canonical_sha256(request_payload),
    }
    return query


def _query_items(
    target_date: str, query_geometry: Mapping[str, Any]
) -> tuple[list[pystac.Item], dict[str, Any], str | None, dict[str, Any]]:
    query = _query_record(target_date, query_geometry)
    observed_items: list[pystac.Item] = []
    page_trace: list[dict[str, Any]] = []
    query_error: str | None = None
    observed_exhaustion = False
    try:
        client = pystac_client.Client.open(EARTH_SEARCH)
        search = client.search(
            collections=[SENTINEL_COLLECTION],
            intersects=query_geometry,
            datetime=query["datetime"],
            query={"eo:cloud_cover": {"lt": 60}},
            max_items=None,
        )
        page_iterator = iter(search.pages())
        while True:
            try:
                page = next(page_iterator)
            except StopIteration:
                observed_exhaustion = True
                break
            page_items = list(page)
            item_ids = [item.id for item in page_items]
            item_hashes = [canonical_sha256(item.to_dict()) for item in page_items]
            links = page.extra_fields.get("links", [])
            advertised_next = any(
                isinstance(link, Mapping) and link.get("rel") == "next"
                for link in links
            )
            page_trace.append(
                {
                    "page_index": len(page_trace) + 1,
                    "item_count": len(page_items),
                    "ordered_item_ids": item_ids,
                    "ordered_item_json_sha256": item_hashes,
                    "advertised_next_page": advertised_next,
                }
            )
            observed_items.extend(page_items)
    except Exception as exc:
        query_error = _safe_error(exc)

    if observed_exhaustion and page_trace:
        # pystac-client yields nonempty ItemCollections only. It follows a
        # final advertised ``next`` link, but suppresses an empty terminal
        # FeatureCollection before exhausting the iterator. Therefore every
        # yielded page before the last must advertise continuation, while the
        # last yielded page may either omit ``next`` or lead to that observed,
        # suppressed empty terminal response.
        inconsistent = any(
            not page["advertised_next_page"] for page in page_trace[:-1]
        )
        if inconsistent:
            query_error = (
                "STAC pagination links did not reconcile with collector exhaustion"
            )

    ids = [item.id for item in observed_items]
    duplicate_ids = sorted(
        item_id for item_id, count in Counter(ids).items() if count > 1
    )
    if duplicate_ids:
        duplicate_error = (
            "STAC query returned duplicate provider item IDs: "
            + ", ".join(duplicate_ids)
        )
        query_error = (
            duplicate_error
            if query_error is None
            else f"{query_error} | {duplicate_error}"
        )
    unique_items: dict[str, pystac.Item] = {}
    for item in observed_items:
        unique_items.setdefault(item.id, item)
    retained_items = sorted(
        unique_items.values(), key=lambda item: item.id.encode("utf-8")
    )
    execution = {
        "status": (
            "complete"
            if query_error is None and observed_exhaustion
            else "partial"
            if page_trace
            else "error"
        ),
        "completed_page_count": len(page_trace),
        "observed_item_count": len(observed_items),
        "retained_unique_item_count": len(retained_items),
        "collector_observed_exhaustion": observed_exhaustion,
        "duplicate_item_ids": duplicate_ids,
        "page_trace": page_trace,
        "page_trace_sha256": canonical_sha256(page_trace),
    }
    return retained_items, query, query_error, execution


@lru_cache(maxsize=2048)
def _http_metadata(url: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "status_code": None,
        "content_length": None,
        "etag": None,
        "last_modified": None,
        "content_type": None,
        "accept_ranges": None,
    }
    request = Request(
        _unsigned_url(url),
        method="HEAD",
        headers={"User-Agent": "araripe-phase2a4-candidate-evidence/1.0"},
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public URLs
            headers = response.headers
            fields.update(
                {
                    "status_code": int(response.status),
                    "content_length": _optional_int(headers.get("Content-Length")),
                    "etag": headers.get("ETag"),
                    "last_modified": headers.get("Last-Modified"),
                    "content_type": headers.get("Content-Type"),
                    "accept_ranges": headers.get("Accept-Ranges"),
                }
            )
    except HTTPError as exc:
        fields["status_code"] = int(exc.code)
    except (URLError, OSError, TimeoutError):
        pass
    return fields


def _optional_int(value: Any) -> int | None:
    try:
        output = int(value)
    except (TypeError, ValueError):
        return None
    return output if output >= 0 else None


def _validate_http_metadata_record(value: Any, *, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(_HTTP_FIELDS):
        raise Phase2A4EvidenceError(f"{label} HTTP metadata fields are invalid")
    status = value["status_code"]
    length = value["content_length"]
    if status is not None and (
        isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599
    ):
        raise Phase2A4EvidenceError(f"{label} HTTP status is invalid")
    if length is not None and (
        isinstance(length, bool) or not isinstance(length, int) or length < 0
    ):
        raise Phase2A4EvidenceError(f"{label} HTTP content length is invalid")
    for name in ("etag", "last_modified", "content_type", "accept_ranges"):
        item = value[name]
        if item is not None and (not isinstance(item, str) or not item or len(item) > 500):
            raise Phase2A4EvidenceError(f"{label} HTTP {name} is invalid")


def _validate_retained_https_url(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise Phase2A4EvidenceError(f"{label} URL is missing")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or value != _unsigned_url(value)
    ):
        raise Phase2A4EvidenceError(f"{label} URL is not unsigned public HTTPS")
    return value


def _validate_unsigned_provider_href(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise Phase2A4EvidenceError(f"{label} provider href is missing or invalid")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"https", "s3"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not parts.path
        or ".." in parts.path.split("/")
    ):
        raise Phase2A4EvidenceError(f"{label} provider href is not unsigned")
    return value


def _resolve_provider_asset_hrefs(value: Any, *, label: str) -> tuple[str, str]:
    """Return the raw provider href and fixed anonymous HTTPS read href."""
    value = _validate_unsigned_provider_href(value, label=label)
    parts = urlsplit(value)
    if parts.scheme == "https":
        return value, _validate_retained_https_url(value, label=label)
    if parts.scheme != "s3" or parts.hostname not in _PUBLIC_S3_HTTPS_BASES:
        raise Phase2A4EvidenceError(
            f"{label} provider href is not an allowed public Earth Search asset"
        )
    key = parts.path.lstrip("/")
    if not key:
        raise Phase2A4EvidenceError(f"{label} public S3 object key is missing")
    resolved = f"{_PUBLIC_S3_HTTPS_BASES[parts.hostname]}/{key}"
    return value, _validate_retained_https_url(resolved, label=label)


def _validate_categorical_source_values(
    asset_key: str, values: np.ndarray
) -> None:
    maximum = {"scl": 11, "cloud": 100}.get(asset_key)
    if maximum is None:
        raise Phase2A4EvidenceError(
            f"unsupported categorical source asset: {asset_key}"
        )
    if values.dtype != np.uint8 or np.any(values > maximum):
        raise Phase2A4EvidenceError(
            f"categorical source range mismatch: {asset_key}"
        )


def _item_observed_at(item_json: Mapping[str, Any]) -> str:
    try:
        item = pystac.Item.from_dict(copy.deepcopy(dict(item_json)))
    except Exception as exc:
        raise Phase2A4EvidenceError(f"invalid retained STAC item: {_safe_error(exc)}") from exc
    observed = item.datetime or item.common_metadata.start_datetime
    if observed is None:
        raise Phase2A4EvidenceError("retained STAC item has no observation time")
    return observed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _item_self_href(item_json: Mapping[str, Any], item_id: str) -> str:
    links = item_json.get("links", [])
    href = next(
        (
            link.get("href")
            for link in links
            if isinstance(link, Mapping) and link.get("rel") == "self"
        ),
        f"{EARTH_SEARCH}/collections/{SENTINEL_COLLECTION}/items/{item_id}",
    )
    return _validate_retained_https_url(href, label=f"STAC item {item_id} self")


def _reflectance_normalization_record(
    asset_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the exact, fail-closed Sentinel-2 reflectance conversion."""
    bands = asset_metadata.get("raster:bands")
    if not isinstance(bands, list) or not bands or not isinstance(bands[0], Mapping):
        raise Phase2A4EvidenceError(
            "reflectance raster:bands[0] metadata is required"
        )
    band = bands[0]
    converted: dict[str, float] = {}
    for field in ("scale", "offset"):
        if field not in band:
            raise Phase2A4EvidenceError(
                f"reflectance raster:bands[0].{field} metadata is required"
            )
        raw = band[field]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise Phase2A4EvidenceError(
                f"reflectance raster:bands[0].{field} must be numeric"
            )
        value = float(raw)
        if not math.isfinite(value) or not np.isfinite(np.float32(value)):
            raise Phase2A4EvidenceError(
                f"reflectance raster:bands[0].{field} must be finite in float32"
            )
        converted[field] = value
    if converted["scale"] <= 0 or np.float32(converted["scale"]) <= 0:
        raise Phase2A4EvidenceError(
            "reflectance raster:bands[0].scale must be positive"
        )
    return {
        **_REFLECTANCE_NORMALIZATION_POLICY,
        "status": "available",
        "reason": None,
        "scale": converted["scale"],
        "offset": converted["offset"],
    }


def _reflectance_normalization_error_record(
    error: BaseException | str,
) -> dict[str, Any]:
    return {
        **_REFLECTANCE_NORMALIZATION_POLICY,
        "status": "error",
        "reason": _safe_error(error),
        "scale": None,
        "offset": None,
    }


def _reflectance_warp_nodata_options(
    asset_key: str, source_nodata: float | int | None
) -> dict[str, Any]:
    if asset_key in REFLECTANCE_ASSETS:
        # Sentinel-2 L2A raw DN zero is fill.  Supplying it as src_nodata makes
        # GDAL exclude it before bilinear resampling instead of blending fill
        # into otherwise valid reflectance.
        return {"src_nodata": 0.0, "nodata": np.nan, "dtype": "float32"}
    return {"nodata": source_nodata}


def _apply_reflectance_normalization(
    raw_values: np.ndarray,
    validity: np.ndarray,
    normalization: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    if normalization.get("status") != "available":
        raise Phase2A4EvidenceError(
            "reflectance normalization metadata is unavailable"
        )
    raw = np.asarray(raw_values, dtype=np.float32)
    valid = np.asarray(validity, dtype=bool).copy()
    if raw.shape != valid.shape:
        raise Phase2A4EvidenceError(
            "reflectance values and validity must have the same shape"
        )
    valid &= np.isfinite(raw) & (raw != np.float32(0.0))
    values = raw * np.float32(normalization["scale"]) + np.float32(
        normalization["offset"]
    )
    np.maximum(values, np.float32(0.0), out=values)
    valid &= np.isfinite(values)
    values[~valid] = np.nan
    return np.asarray(values, dtype=np.float32), valid


def _validate_reflectance_normalization_binding(
    asset_key: str,
    asset_record: Mapping[str, Any],
    item_asset: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any] | None:
    expected: dict[str, Any] | None = None
    if asset_key in REFLECTANCE_ASSETS:
        try:
            expected = _reflectance_normalization_record(item_asset)
        except Phase2A4EvidenceError as exc:
            expected = _reflectance_normalization_error_record(exc)
    if asset_record.get("reflectance_normalization") != expected:
        raise Phase2A4EvidenceError(
            f"reflectance normalization mismatch: {label}"
        )
    if (
        expected is not None
        and expected["status"] == "error"
        and (
            asset_record.get("status") != "error"
            or asset_record.get("reason") != expected["reason"]
            or not isinstance(asset_record.get("http_metadata"), Mapping)
            or any(
                asset_record["http_metadata"].get(field) is not None
                for field in _HTTP_FIELDS
            )
        )
    ):
        raise Phase2A4EvidenceError(
            f"invalid reflectance metadata did not fail closed: {label}"
        )
    return expected


def _validate_reflectance_window_values(
    values: np.ndarray, validity: np.ndarray, *, label: str
) -> None:
    if (
        values.dtype != np.float32
        or validity.dtype != np.bool_
        or values.shape != validity.shape
        or np.any(~np.isfinite(values[validity]))
        or np.any(values[validity] < np.float32(0.0))
        or np.any(~np.isnan(values[~validity]))
    ):
        raise Phase2A4EvidenceError(
            f"reflectance value/validity semantics mismatch: {label}"
        )


def _stac_sha256(extra_fields: Mapping[str, Any]) -> str | None:
    value = extra_fields.get("file:checksum")
    if isinstance(value, str) and len(value) == 68 and value.startswith("1220"):
        digest = value[4:].lower()
        if re.fullmatch(r"[0-9a-f]{64}", digest):
            return digest
    return None


def _empty_http_metadata() -> dict[str, Any]:
    return {name: None for name in _HTTP_FIELDS}


def _missing_source_asset_record(asset_key: str) -> dict[str, Any]:
    return {
        "asset_key": asset_key,
        "status": "missing",
        "reason": "required STAC asset is absent",
        "provider_href": None,
        "unsigned_href": None,
        "href_resolution_policy": _ASSET_HREF_RESOLUTION_POLICY,
        "stac_asset_metadata_sha256": None,
        "media_type": None,
        "read_mode": _SOURCE_READ_MODE,
        "http_metadata": _empty_http_metadata(),
        "upstream_full_asset_sha256": None,
        "reflectance_normalization": None,
        "local_window_data": None,
        "checksum_scope_limitation": _SOURCE_CHECKSUM_LIMITATION,
    }


def _read_asset_window(
    item: pystac.Item,
    asset_key: str,
    *,
    context_window: Mapping[str, Any],
    case_root: Path,
    output_root: Path,
) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, Any], list[dict[str, Any]]]:
    if asset_key not in item.assets:
        return None, None, _missing_source_asset_record(asset_key), []

    asset = item.assets[asset_key]
    provider_href, href = _resolve_provider_asset_hrefs(
        asset.href, label=f"STAC item {item.id} asset {asset_key}"
    )
    asset_metadata = asset.to_dict()
    metadata_sha = canonical_sha256(asset_metadata)
    artifacts: list[dict[str, Any]] = []
    normalization: dict[str, Any] | None = None
    if asset_key in REFLECTANCE_ASSETS:
        try:
            normalization = _reflectance_normalization_record(asset_metadata)
        except Phase2A4EvidenceError as exc:
            normalization = _reflectance_normalization_error_record(exc)
            return None, None, {
                "asset_key": asset_key,
                "status": "error",
                "reason": normalization["reason"],
                "provider_href": provider_href,
                "unsigned_href": href,
                "href_resolution_policy": _ASSET_HREF_RESOLUTION_POLICY,
                "stac_asset_metadata_sha256": metadata_sha,
                "media_type": asset.media_type,
                "read_mode": _SOURCE_READ_MODE,
                "http_metadata": _empty_http_metadata(),
                "upstream_full_asset_sha256": _stac_sha256(asset.extra_fields),
                "reflectance_normalization": normalization,
                "local_window_data": None,
                "checksum_scope_limitation": _SOURCE_CHECKSUM_LIMITATION,
            }, []
    try:
        transform = Affine(*context_window["transform"])
        resampling = (
            RioResampling.bilinear
            if asset_key in REFLECTANCE_ASSETS
            else RioResampling.nearest
        )
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_HTTP_MAX_RETRY="3",
            GDAL_HTTP_RETRY_DELAY="1",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.jp2",
        ):
            with rasterio.open(href) as source:
                with WarpedVRT(
                    source,
                    crs=GRID_CRS,
                    transform=transform,
                    width=int(context_window["width"]),
                    height=int(context_window["height"]),
                    resampling=resampling,
                    **_reflectance_warp_nodata_options(asset_key, source.nodata),
                ) as aligned:
                    band = aligned.read(1, masked=True)
        valid = ~np.ma.getmaskarray(band)
        if asset_key in REFLECTANCE_ASSETS:
            raw = np.asarray(
                band.astype(np.float32).filled(np.nan), dtype=np.float32
            )
            values, valid = _apply_reflectance_normalization(
                raw, valid, normalization
            )
        elif asset_key == "cloud":
            raw = np.asarray(band.filled(100), dtype=np.float64)
            valid &= np.isfinite(raw) & (raw >= 0) & (raw <= 100)
            values = np.clip(np.rint(np.nan_to_num(raw, nan=100.0)), 0, 100).astype(np.uint8)
        else:
            raw = np.asarray(band.filled(0), dtype=np.float64)
            valid &= np.isfinite(raw) & (raw >= 0) & (raw <= 11)
            values = np.clip(np.rint(np.nan_to_num(raw, nan=0.0)), 0, 11).astype(np.uint8)

        safe_scene = hashlib.sha256(item.id.encode("utf-8")).hexdigest()[:24]
        value_path = case_root / "source-windows" / safe_scene / f"{asset_key}.npy"
        valid_path = case_root / "source-windows" / safe_scene / f"{asset_key}-valid.npy"
        _write_npy(value_path, values)
        _write_npy(valid_path, valid)
        artifacts.extend(
            [
                _artifact(value_path, output_root, media_type="application/x-npy", role="source_window_values"),
                _artifact(valid_path, output_root, media_type="application/x-npy", role="source_window_validity"),
            ]
        )
        local_digest = canonical_sha256(
            {
                "values": canonical_array_record(values),
                "validity": canonical_array_record(valid),
                "asset_metadata_sha256": metadata_sha,
                "reflectance_normalization": normalization,
                "aligned_context_window": context_window,
            }
        )
        record = {
            "asset_key": asset_key,
            "status": "available",
            "reason": None,
            "provider_href": provider_href,
            "unsigned_href": href,
            "href_resolution_policy": _ASSET_HREF_RESOLUTION_POLICY,
            "stac_asset_metadata_sha256": metadata_sha,
            "media_type": asset.media_type,
            "read_mode": _SOURCE_READ_MODE,
            "http_metadata": _http_metadata(href),
            "upstream_full_asset_sha256": _stac_sha256(asset.extra_fields),
            "reflectance_normalization": normalization,
            "local_window_data": {
                "sha256": local_digest,
                "dtype": str(values.dtype),
                "shape": list(values.shape),
                "canonicalization": _LOCAL_WINDOW_CANONICALIZATION,
            },
            "checksum_scope_limitation": _SOURCE_CHECKSUM_LIMITATION,
        }
        return values, valid, record, artifacts
    except Exception as exc:
        return None, None, {
            "asset_key": asset_key,
            "status": "error",
            "reason": _safe_error(exc),
            "provider_href": provider_href,
            "unsigned_href": href,
            "href_resolution_policy": _ASSET_HREF_RESOLUTION_POLICY,
            "stac_asset_metadata_sha256": metadata_sha,
            "media_type": asset.media_type,
            "read_mode": _SOURCE_READ_MODE,
            "http_metadata": _http_metadata(href),
            "upstream_full_asset_sha256": _stac_sha256(asset.extra_fields),
            "reflectance_normalization": normalization,
            "local_window_data": None,
            "checksum_scope_limitation": _SOURCE_CHECKSUM_LIMITATION,
        }, artifacts


def _load_scene(
    item: pystac.Item,
    *,
    context_window: Mapping[str, Any],
    case_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    item_json = item.to_dict()
    self_href = _item_self_href(item_json, item.id)
    for key, asset_json in item_json.get("assets", {}).items():
        if isinstance(asset_json, Mapping) and "href" in asset_json:
            _validate_unsigned_provider_href(
                asset_json["href"], label=f"STAC item {item.id} asset {key}"
            )
    for index, link in enumerate(item_json.get("links", [])):
        if isinstance(link, Mapping) and "href" in link:
            _validate_unsigned_provider_href(
                link["href"], label=f"STAC item {item.id} link {index}"
            )
    item_sha = canonical_sha256(item_json)
    safe_scene = hashlib.sha256(item.id.encode("utf-8")).hexdigest()[:24]
    item_path = case_root / "source-scenes" / f"{safe_scene}.json"
    write_canonical_json(item_path, item_json)
    artifacts = [_artifact(item_path, output_root, media_type="application/json", role="stac_item_json")]
    arrays: dict[str, np.ndarray | None] = {}
    validities: dict[str, np.ndarray | None] = {}
    asset_records: list[dict[str, Any]] = []
    for key in REQUIRED_ASSETS:
        values, valid, record, asset_artifacts = _read_asset_window(
            item,
            key,
            context_window=context_window,
            case_root=case_root,
            output_root=output_root,
        )
        arrays[key] = values
        validities[key] = valid
        asset_records.append(record)
        artifacts.extend(asset_artifacts)
    observed_at = _item_observed_at(item_json)
    source_record = {
        "catalog": "Element84 Earth Search",
        "stac_endpoint": EARTH_SEARCH,
        "collection_id": SENTINEL_COLLECTION,
        "item_id": item.id,
        "observed_at": observed_at,
        "self_href": self_href,
        "stac_item_json_sha256": item_sha,
        "assets": asset_records,
    }
    return {
        # The collection is recorded alongside every item.  The deterministic
        # scene sort/tie-break itself uses the provider-native STAC item ID.
        "scene_id": item.id,
        "item_id": item.id,
        "metadata_sha256": item_sha,
        "source_record": source_record,
        "arrays": arrays,
        "validities": validities,
        "artifacts": artifacts,
    }


def _verify_baseline_manifest(path: Path) -> dict[str, Any]:
    if sha256_file(path) != BASELINE_MANIFEST_SHA256:
        raise Phase2A4EvidenceError("accepted baseline manifest checksum changed")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("baseline_version") != "1.0.0"
        or value.get("status") != "accepted_audit_generation"
    ):
        raise Phase2A4EvidenceError("baseline manifest is not accepted version 1.0.0")
    return value


def _read_baselines(
    month: int,
    *,
    manifest: Mapping[str, Any],
    base_url: str,
    context_window: Mapping[str, Any],
    case_root: Path,
    output_root: Path,
) -> tuple[dict[str, dict[str, np.ndarray]] | None, list[dict[str, Any]], dict[str, Any]]:
    by_key = {entry["key"]: entry for entry in manifest["objects"]}
    arrays: dict[str, dict[str, np.ndarray]] = {}
    artifacts: list[dict[str, Any]] = []
    provenance_objects: list[dict[str, Any]] = []
    failures: list[str] = []
    raster_window = Window(
        col_off=int(context_window["column_offset"]),
        row_off=int(context_window["row_offset"]),
        width=int(context_window["width"]),
        height=int(context_window["height"]),
    )
    for index_name in INDEX_NAMES:
        arrays[index_name] = {}
        for statistic in ("mean", "std"):
            key = f"baselines/{index_name}_month{month:02d}_{statistic}.tif"
            expected = by_key.get(key)
            if expected is None:
                failures.append(f"baseline object missing from manifest: {key}")
                provenance_objects.append(
                    {
                        "key": key,
                        "status": "error",
                        "reason": failures[-1],
                        "manifest_bytes": None,
                        "manifest_sha256": None,
                        "manifest_r2_etag": None,
                        "unsigned_href": None,
                        "http_metadata": None,
                        "read_mode": "remote_cog_range_read_to_aligned_context_window",
                        "local_window": None,
                        "checksum_scope_limitation": (
                            "accepted_manifest_sha256_binds_full_object; no local window was available"
                        ),
                    }
                )
                continue
            url = f"{base_url}/{key}"
            http = _http_metadata(url)
            try:
                if http["content_length"] != expected["bytes"]:
                    raise Phase2A4EvidenceError(f"baseline content length mismatch: {key}")
                if str(http["etag"] or "").strip('"') != expected["r2_etag"]:
                    raise Phase2A4EvidenceError(f"baseline ETag mismatch: {key}")
                with rasterio.Env(
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    GDAL_HTTP_MAX_RETRY="3",
                    GDAL_HTTP_RETRY_DELAY="1",
                    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                ):
                    with rasterio.open(url) as dataset:
                        if (
                            str(dataset.crs) != GRID_CRS
                            or dataset.width != GRID_WIDTH
                            or dataset.height != GRID_HEIGHT
                            or tuple(dataset.transform)[:6] != tuple(GRID_TRANSFORM)[:6]
                        ):
                            raise Phase2A4EvidenceError(f"baseline grid mismatch: {key}")
                        band = dataset.read(1, window=raster_window, masked=True)
                value = np.asarray(band.astype(np.float32).filled(np.nan), dtype=np.float32)
                value[~np.isfinite(value)] = np.nan
                arrays[index_name][statistic] = value
                path = case_root / "baseline-windows" / f"{index_name}-{statistic}.npy"
                _write_npy(path, value)
                artifact = _artifact(
                    path,
                    output_root,
                    media_type="application/x-npy",
                    role="accepted_baseline_window",
                )
                artifacts.append(artifact)
                provenance_objects.append(
                    {
                        "key": key,
                        "status": "available",
                        "reason": None,
                        "manifest_bytes": expected["bytes"],
                        "manifest_sha256": expected["sha256"],
                        "manifest_r2_etag": expected["r2_etag"],
                        "unsigned_href": url,
                        "http_metadata": http,
                        "read_mode": "remote_cog_range_read_to_aligned_context_window",
                        "local_window": artifact,
                        "checksum_scope_limitation": (
                            "accepted_manifest_sha256_binds_full_object; local_window_sha256_binds_only_aligned_context_derivative"
                        ),
                    }
                )
            except Exception as exc:
                reason = _safe_error(exc)
                failures.append(reason)
                provenance_objects.append(
                    {
                        "key": key,
                        "status": "error",
                        "reason": reason,
                        "manifest_bytes": expected["bytes"],
                        "manifest_sha256": expected["sha256"],
                        "manifest_r2_etag": expected["r2_etag"],
                        "unsigned_href": url,
                        "http_metadata": http,
                        "read_mode": "remote_cog_range_read_to_aligned_context_window",
                        "local_window": None,
                        "checksum_scope_limitation": (
                            "accepted_manifest_sha256_binds_full_object; no local window was available"
                        ),
                    }
                )
    status = "available" if not failures else "error"
    reason = None if not failures else " | ".join(failures)
    return (
        arrays if not failures else None,
        artifacts,
        {"month": month, "status": status, "reason": reason, "objects": provenance_objects},
    )


def _mask_configs(registry: Mapping[str, Any]) -> dict[str, MaskCandidateConfig]:
    output: dict[str, MaskCandidateConfig] = {}
    for candidate in registry["families"]["cloud_mask"]["candidates"]:
        probability = candidate.get("cloud_probability")
        shadow = candidate["shadow_policy"]
        output[candidate["candidate_id"]] = MaskCandidateConfig(
            candidate_id=candidate["candidate_id"],
            scl_clear_classes=tuple(candidate["scl_clear_classes"]),
            scl_shadow_classes=tuple(candidate["scl_shadow_classes"]),
            scl_invalid_classes=tuple(candidate["scl_invalid_classes"]),
            scl_cloud_classes=tuple(candidate["scl_cloud_classes"]),
            cloud_probability_max_percent=(
                None if probability is None else probability["clear_when_lte"]
            ),
            cloud_probability_uint8_required=probability is not None,
            shadow_mode=shadow["mode"],
            dark_nir_reflectance_max=shadow.get("dark_nir_reflectance_lte"),
            within_cloud_distance_m=shadow.get("within_cloud_distance_m", 0),
            pixel_size_m=20,
            dilation_m=candidate["dilation_m"],
        )
    return output


def _composition_configs(registry: Mapping[str, Any]) -> dict[str, CompositionCandidateConfig]:
    output: dict[str, CompositionCandidateConfig] = {}
    for candidate in registry["families"]["daily_composition"]["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id == "coverage-ranked-first-valid-v1":
            method = "coverage_ranked_first_valid"
            ranks = None
        else:
            method = "min_cloudprob_sclrank_sceneid"
            ranks = tuple(candidate["scl_rank_order"])
        output[candidate_id] = CompositionCandidateConfig(
            candidate_id=candidate_id,
            method=method,
            scl_rank_order=ranks,
        )
    return output


def _evaluate_mask_candidates(
    loaded_scenes: Sequence[Mapping[str, Any]],
    mask_configs: Mapping[str, MaskCandidateConfig],
    *,
    comparison_mask: np.ndarray,
    scene_fatal: str | None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if scene_fatal is not None:
        return results
    for mask_id, config in mask_configs.items():
        per_scene: list[tuple[Mapping[str, Any], Any]] = []
        reason = None
        for scene in loaded_scenes:
            arrays = scene["arrays"]
            validities = scene["validities"]
            reflectance_valid = np.logical_and.reduce(
                [validities[key] for key in REFLECTANCE_ASSETS]
            )
            source_valid = reflectance_valid & validities["scl"]
            if config.cloud_probability_max_percent is not None:
                if arrays["cloud"] is None:
                    reason = f"{scene['scene_id']} lacks usable cloud probability"
                    break
                source_valid &= validities["cloud"]
            try:
                result = apply_mask_policy(
                    arrays["scl"],
                    config=config,
                    cloud_probability=arrays["cloud"],
                    dark_nir_reflectance=arrays["nir"],
                    source_valid_mask=source_valid,
                    comparison_mask=comparison_mask,
                )
            except Exception as exc:
                reason = f"{scene['scene_id']} mask input error: {_safe_error(exc)}"
                break
            if result.record["status"] != "available":
                reason = result.record.get("unavailable_reason")
                break
            per_scene.append((scene, result))
        results[mask_id] = {
            "status": "available" if reason is None else "unavailable",
            "reason": reason,
            "per_scene": per_scene,
        }
    return results


def _drought_result(
    observed_on: str,
    *,
    registry: Mapping[str, Any],
    rainfall: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = registry["families"]["drought_adjustment"]["candidates"][1]
    distribution = candidate["reference_distribution"]
    decision = candidate["decision_rule"]
    config = DroughtCandidateConfig(
        candidate_id=candidate["candidate_id"],
        reference_start_year=1981,
        reference_end_year=2025,
        accumulation_months=candidate["target_period"]["accumulation_months"],
        minimum_complete_reference_windows=distribution["minimum_complete_windows"],
        minimum_positive_reference_windows=distribution[
            "minimum_positive_windows"
        ],
        normal_probability_clip=tuple(distribution["normal_probability_clip"]),
        drought_threshold=decision["drought_when_spi3_lt"],
        z_threshold_adjustment=decision["z_threshold_adjustment"],
    )
    return compute_season_matched_spi3(
        observed_on,
        rainfall["precipitation_mm_by_month"],
        config=config,
    )


def _rainfall_reference_record(
    result: Mapping[str, Any], rainfall: Mapping[str, Any], rainfall_dir: Path, output_root: Path
) -> dict[str, Any]:
    del rainfall_dir, output_root
    status = "available" if result["status"] == "available" else "invalid"
    return {
        "status": status,
        "reason": None if status == "available" else result.get("unavailable_reason", "rainfall evidence unavailable"),
        "dataset_id": "CHIRPS-2.0-monthly",
        "source_kind": "official_direct_monthly_cog_not_stac",
        "official_cog_base_url": "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/cogs/",
        "official_cog_pattern": "chirps-v2.0.YYYY.MM.cog",
        "aggregation_version": "cell-center-cos-lat-v1",
        "coverage_denominator": "sum_cosine_latitude_weight_over_all_selected_cell_centers",
        "reference_start_month": "1981-01",
        "reference_end_month": "2025-12",
        "target_ending_month": result.get("target_ending_month"),
        "complete_reference_window_count": int(result.get("reference_complete_count", 0)),
        "artifact_id": rainfall.get("artifact_id"),
        "manifest_sha256": rainfall.get("manifest_sha256"),
        "plan_sha256": rainfall.get("plan_sha256"),
        "full_upstream_cog_checksum_available": False,
        "checksum_scope_limitation": "local_window_sha256_does_not_verify_full_upstream_cog",
        "artifact": None,
    }


def _compute_indices(values: np.ndarray) -> dict[str, np.ndarray]:
    blue, red, nir, nir08, swir16, swir22 = np.asarray(
        values, dtype=np.float32
    )

    def ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        denominator = a + b
        return np.divide(
            a - b,
            denominator,
            out=np.full(a.shape, np.nan, dtype=np.float32),
            where=np.isfinite(a) & np.isfinite(b) & (denominator != 0),
        )

    evi_denominator = (
        nir + np.float32(2.4) * red + np.float32(1.0)
    )
    evi2 = np.divide(
        np.float32(2.5) * (nir - red),
        evi_denominator,
        out=np.full(red.shape, np.nan, dtype=np.float32),
        where=np.isfinite(nir) & np.isfinite(red) & (evi_denominator != 0),
    )
    return {"evi2": evi2, "nbr": ratio(nir08, swir22), "ndmi": ratio(nir08, swir16)}


def _detect(
    composite_values: np.ndarray,
    composite_valid: np.ndarray,
    baseline: Mapping[str, Mapping[str, np.ndarray]],
    *,
    comparison_mask: np.ndarray,
    z_adjustment: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    indices = _compute_indices(composite_values)
    source_valid = comparison_mask & composite_valid
    index_valid: dict[str, np.ndarray] = {}
    zscores: dict[str, np.ndarray] = {}
    deltas: dict[str, np.ndarray] = {}
    for name in INDEX_NAMES:
        current = indices[name]
        mean = baseline[name]["mean"]
        std = baseline[name]["std"]
        eligible = source_valid & (
            np.isfinite(current)
            & np.isfinite(mean)
            & np.isfinite(std)
        )
        safe_std = np.where(
            std > np.float32(0.01), std, np.float32(0.01)
        )
        delta = current - mean
        with np.errstate(divide="ignore", invalid="ignore"):
            zscore = np.divide(
                delta,
                safe_std,
                out=np.full(delta.shape, np.nan, dtype=np.float32),
                where=np.isfinite(delta),
            )
        index_valid[name] = eligible
        deltas[name] = delta
        zscores[name] = zscore
    valid = np.logical_or.reduce([index_valid[name] for name in INDEX_NAMES])
    confidence = np.full(valid.shape, -1, dtype=np.int8)
    confidence[valid] = 0
    z_high, z_medium, z_low = -3.0 - z_adjustment, -2.5 - z_adjustment, -2.0 - z_adjustment
    high = (
        valid
        & (zscores["ndmi"] < z_high)
        & (deltas["ndmi"] < -0.20)
        & (zscores["nbr"] < z_high)
        & (deltas["nbr"] < -0.20)
    )
    confidence[high] = 3
    for name in ("ndmi", "nbr"):
        medium = valid & (confidence < 2) & (zscores[name] < z_medium) & (deltas[name] < -0.15)
        confidence[medium] = 2
    for name in INDEX_NAMES:
        low = valid & (confidence < 1) & (zscores[name] < z_low) & (deltas[name] < -0.15)
        confidence[low] = 1
    total = int(np.count_nonzero(comparison_mask))
    valid_count = int(np.count_nonzero(valid))
    counts = {str(level): int(np.count_nonzero(confidence == level)) for level in (0, 1, 2, 3)}
    record = {
        "algorithm": "accepted_phase2a1_detector_semantics_factorial_replay_v1",
        "valid_pixel_rule": (
            "union_of_per_index_finite_current_baseline_mean_and_std_within_"
            "candidate_composite_validity"
        ),
        "standard_deviation_floor": 0.01,
        "z_thresholds": {"high": z_high, "medium": z_medium, "low": z_low},
        "delta_thresholds": {"high": -0.20, "medium": -0.15, "low": -0.15},
        "z_threshold_adjustment": z_adjustment,
        "case_window_pixel_count": total,
        "valid_pixel_count": valid_count,
        "valid_coverage_fraction": valid_count / total,
        "confidence_counts": counts,
        "alert_pixel_count": sum(counts[str(level)] for level in (1, 2, 3)),
        "valid_mask_sha256": canonical_array_record(valid)["sha256"],
        "confidence_sha256": canonical_array_record(confidence)["sha256"],
        "candidate_only": True,
        "selected_or_activated": False,
    }
    return valid, confidence, record


def _contributing_scene_records(
    result: Any,
    detector_valid: np.ndarray,
    comparison_mask: np.ndarray,
) -> list[dict[str, Any]]:
    """Keep composition contribution distinct from detector eligibility."""
    total = int(np.count_nonzero(comparison_mask))
    records: list[dict[str, Any]] = []
    selected_total = 0
    detector_total = 0
    for scene_index, scene_id in enumerate(result.source_scene_ids):
        selected_count = int(result.per_scene_pixel_counts[scene_id])
        if selected_count == 0:
            continue
        detector_count = int(
            np.count_nonzero(
                detector_valid & (result.contributor_map == scene_index)
            )
        )
        scene_valid_count = int(
            result.record["per_scene_valid_pixel_counts"][scene_id]
        )
        records.append(
            {
                "scene_id": scene_id,
                "selected_pixel_count": selected_count,
                "detector_valid_pixel_count": detector_count,
                "scene_valid_pixel_count": scene_valid_count,
                "scene_valid_coverage_fraction": scene_valid_count / total,
            }
        )
        selected_total += selected_count
        detector_total += detector_count
    if selected_total != int(result.record["valid_pixel_count"]):
        raise Phase2A4EvidenceError(
            "composition contributor counts do not reconcile"
        )
    if detector_total != int(np.count_nonzero(detector_valid)):
        raise Phase2A4EvidenceError(
            "detector-eligible contributor counts do not reconcile"
        )
    return records


def _crop_comparison(array: np.ndarray, comparison_mask: np.ndarray) -> np.ndarray:
    rows, columns = np.nonzero(comparison_mask)
    row0, row1 = int(rows.min()), int(rows.max()) + 1
    col0, col1 = int(columns.min()), int(columns.max()) + 1
    if array.ndim == 3:
        return array[:, row0:row1, col0:col1]
    return array[row0:row1, col0:col1]


def _render_cell_tile(
    composite_values: np.ndarray | None,
    valid: np.ndarray | None,
    confidence: np.ndarray | None,
    comparison_mask: np.ndarray,
    *,
    label: str,
    missing_reason: str | None,
) -> Image.Image:
    width, panel_height, header = 720, 300, 34
    image = Image.new("RGB", (width, panel_height + header), "white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), label, fill=(0, 0, 0))
    if composite_values is None or valid is None or confidence is None:
        draw.rectangle((0, header, width, panel_height + header), fill=(232, 232, 232))
        draw.text((18, header + 20), f"Unavailable: {missing_reason or 'missing evidence'}"[:100], fill=(80, 40, 40))
        return image
    cropped = _crop_comparison(composite_values, comparison_mask)
    cropped_valid = _crop_comparison(valid, comparison_mask)
    cropped_confidence = _crop_comparison(confidence, comparison_mask)
    # Fixed SWIR1/NIR08/RED physical stretch for every option and stratum.
    rgb = np.stack((cropped[4], cropped[3], cropped[1]), axis=-1)
    rgb = np.clip(rgb / 0.40, 0.0, 1.0)
    rgb = np.rint(np.nan_to_num(rgb, nan=0.0) * 255).astype(np.uint8)
    rgb[~cropped_valid] = (55, 45, 60)
    status = np.zeros_like(rgb)
    status[:] = (38, 67, 48)
    status[~cropped_valid] = (65, 58, 70)
    colors = {1: (245, 214, 70), 2: (244, 139, 45), 3: (202, 38, 40)}
    for level, color in colors.items():
        status[cropped_confidence == level] = color
    left = Image.fromarray(rgb, mode="RGB").resize(
        (360, panel_height), Image.Resampling.NEAREST
    )
    right = Image.fromarray(status, mode="RGB").resize(
        (360, panel_height), Image.Resampling.NEAREST
    )
    image.paste(left, (0, header))
    image.paste(right, (360, header))
    draw.line((360, header, 360, header + panel_height), fill=(255, 255, 255), width=2)
    draw.text((10, header + 8), "fixed SWIR/NIR/red", fill=(255, 255, 255))
    draw.text((370, header + 8), "validity and change response", fill=(255, 255, 255))
    return image


def _candidate_panel_bytes(
    *,
    cells: Sequence[dict[str, Any]],
    render_by_cell: Mapping[str, tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, str | None]],
    comparison_mask: np.ndarray,
) -> bytes:
    tiles = []
    for index, cell in enumerate(cells, start=1):
        composite, valid, confidence, reason = render_by_cell[cell["cell_id"]]
        tiles.append(
            _render_cell_tile(
                composite,
                valid,
                confidence,
                comparison_mask,
                label=f"Paired stratum {index}",
                missing_reason=reason,
            )
        )
    panel = Image.new("RGB", (720, sum(tile.height for tile in tiles)), "white")
    y = 0
    for tile in tiles:
        panel.paste(tile, (0, y))
        y += tile.height
    stream = io.BytesIO()
    panel.save(stream, format="PNG", compress_level=9, optimize=False)
    return stream.getvalue()


def _render_candidate_panel(
    path: Path,
    *,
    cells: Sequence[dict[str, Any]],
    render_by_cell: Mapping[str, tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, str | None]],
    comparison_mask: np.ndarray,
) -> None:
    payload = _candidate_panel_bytes(
        cells=cells,
        render_by_cell=render_by_cell,
        comparison_mask=comparison_mask,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _paired_stratum_key(
    blind_case_id: str,
    family: str,
    cell: Mapping[str, Any],
) -> str:
    """Order paired panels by the two factors that are held constant.

    The candidate under comparison is deliberately excluded so row N in both
    blinded alternatives represents the same other-factor stratum.
    """
    candidates = cell["candidates"]
    other_factors = {
        name: candidates[name]
        for name in ("cloud_mask", "daily_composition", "drought_adjustment")
        if name != family
    }
    return identity_sha256(
        "phase2a4-paired-stratum-v1",
        blind_case_id,
        family,
        canonical_sha256(other_factors),
    )


def _disabled_drought_status() -> dict[str, Any]:
    return {
        "status": "disabled",
        "spi3": None,
        "reference_window_count": None,
        "z_threshold_adjustment": 0.0,
        "reason": None,
    }


def _candidate_drought_status(result: Mapping[str, Any]) -> dict[str, Any]:
    if result["status"] != "available":
        return {
            "status": "unavailable",
            "spi3": None,
            "reference_window_count": int(result.get("reference_complete_count", 0)),
            "z_threshold_adjustment": None,
            "reason": result.get("unavailable_reason", "drought evidence unavailable"),
        }
    is_drought = bool(result["is_drought"])
    return {
        "status": "drought" if is_drought else "not_drought",
        "spi3": float(result["spi_3month"]),
        "reference_window_count": int(result["reference_complete_count"]),
        "z_threshold_adjustment": 0.5 if is_drought else 0.0,
        "reason": None,
    }


def _build_case(
    mapping_record: Mapping[str, Any],
    *,
    parent_package: Path,
    output_root: Path,
    registry: Mapping[str, Any],
    rainfall: Mapping[str, Any],
    rainfall_dir: Path,
    baseline_manifest: Mapping[str, Any],
    baseline_base_url: str,
    catalog_accessed_at: str,
) -> dict[str, Any]:
    sample_id = mapping_record["sample_id"]
    blind_case_id = mapping_record["blind_case_id"]
    source_case_path = parent_package / "coordinator" / "cases" / f"{sample_id}.json"
    source_case = json.loads(source_case_path.read_text(encoding="utf-8"))
    reviewer_case = source_case["reviewer_case"]
    target_date = reviewer_case["target_date"]
    case_root = output_root / "cases" / sample_id
    case_root.mkdir(parents=True, exist_ok=False)
    grid = _window_from_geometry(reviewer_case["target_geometry"])
    query_geometry = _query_geometry(grid)
    items: list[pystac.Item] = []
    query = _query_record(target_date, query_geometry)
    query_error = None
    query_execution = {
        "status": "error",
        "completed_page_count": 0,
        "observed_item_count": 0,
        "retained_unique_item_count": 0,
        "collector_observed_exhaustion": False,
        "duplicate_item_ids": [],
        "page_trace": [],
        "page_trace_sha256": canonical_sha256([]),
    }
    try:
        items, query, query_error, query_execution = _query_items(
            target_date, query_geometry
        )
    except Exception as exc:
        query_error = _safe_error(exc)

    loaded_scenes: list[dict[str, Any]] = []
    for item in items:
        loaded_scenes.append(
            _load_scene(
                item,
                context_window=grid["context_window"],
                case_root=case_root,
                output_root=output_root,
            )
        )
    source_scene_ids = [scene["scene_id"] for scene in loaded_scenes]
    source_scene_ids_sha = canonical_sha256(source_scene_ids)
    source_artifacts = [artifact for scene in loaded_scenes for artifact in scene["artifacts"]]

    baseline: dict[str, dict[str, np.ndarray]] | None = None
    baseline_artifacts: list[dict[str, Any]] = []
    baseline_record: dict[str, Any] | None = None
    baseline_error = None
    baseline, baseline_artifacts, baseline_record = _read_baselines(
        dt.date.fromisoformat(target_date).month,
        manifest=baseline_manifest,
        base_url=baseline_base_url,
        context_window=grid["context_window"],
        case_root=case_root,
        output_root=output_root,
    )
    if baseline is None:
        baseline_error = baseline_record.get("reason")

    drought_result = _drought_result(target_date, registry=registry, rainfall=rainfall)
    rainfall_reference = _rainfall_reference_record(drought_result, rainfall, rainfall_dir, output_root)
    comparison_mask = grid.pop("comparison_mask")
    mask_configs = _mask_configs(registry)
    composition_configs = _composition_configs(registry)
    mask_results: dict[str, dict[str, Any]] = {}
    compositions: dict[tuple[str, str], dict[str, Any]] = {}

    scene_fatal = query_error
    if query_execution["status"] != "complete" and scene_fatal is None:
        scene_fatal = "STAC query execution did not yield a complete scene set"
    if not loaded_scenes and scene_fatal is None:
        scene_fatal = "source query returned no same-day scenes"
    if loaded_scenes:
        reflectance_failures = [
            f"{scene['scene_id']}:{key}"
            for scene in loaded_scenes
            for key in (*REFLECTANCE_ASSETS, "scl")
            if scene["arrays"][key] is None
        ]
        if reflectance_failures:
            scene_fatal = "required source assets unavailable: " + ", ".join(reflectance_failures)

    mask_results = _evaluate_mask_candidates(
        loaded_scenes,
        mask_configs,
        comparison_mask=comparison_mask,
        scene_fatal=scene_fatal,
    )
    if scene_fatal is None:
        for mask_id, mask_entry in mask_results.items():
            for composition_id, composition_config in composition_configs.items():
                key = (mask_id, composition_id)
                if mask_entry["status"] != "available":
                    compositions[key] = {
                        "status": "unavailable",
                        "reason": mask_entry["reason"],
                        "result": None,
                    }
                    continue
                scenes_for_composition = []
                for scene, mask_result in mask_entry["per_scene"]:
                    arrays = scene["arrays"]
                    valid_mask = mask_result.valid_mask
                    if composition_config.method == "min_cloudprob_sclrank_sceneid":
                        if arrays["cloud"] is None:
                            scenes_for_composition = []
                            break
                        # Pixel ranking requires an actual cloud-probability
                        # sample; an invalid probability is never replaced by
                        # an apparently clear or cloudy numeric surrogate.
                        valid_mask = valid_mask & scene["validities"]["cloud"]
                    scenes_for_composition.append(
                        CompositionScene(
                            scene_id=scene["scene_id"],
                            values=np.stack([arrays[name] for name in REFLECTANCE_ASSETS]),
                            valid_mask=valid_mask,
                            source_metadata_sha256=scene["metadata_sha256"],
                            scl=arrays["scl"],
                            cloud_probability=arrays["cloud"],
                        )
                    )
                if not scenes_for_composition:
                    compositions[key] = {
                        "status": "unavailable",
                        "reason": "cloud probability required for every source scene",
                        "result": None,
                    }
                    continue
                try:
                    if composition_config.method == "coverage_ranked_first_valid":
                        result = compose_coverage_ranked_first_valid(
                            scenes_for_composition,
                            config=composition_config,
                            comparison_mask=comparison_mask,
                        )
                    else:
                        result = compose_min_cloudprob_sclrank_sceneid(
                            scenes_for_composition,
                            config=composition_config,
                            comparison_mask=comparison_mask,
                        )
                    compositions[key] = {"status": "available", "reason": None, "result": result}
                except Exception as exc:
                    compositions[key] = {
                        "status": "unavailable",
                        "reason": _safe_error(exc),
                        "result": None,
                    }

    processing_artifacts: list[dict[str, Any]] = []
    mask_audit: dict[str, Any] = {}
    for mask_id in sorted(mask_configs):
        entry = mask_results.get(
            mask_id,
            {"status": "unavailable", "reason": scene_fatal or "mask unavailable", "per_scene": []},
        )
        scenes_audit: list[dict[str, Any]] = []
        for scene, result in entry["per_scene"]:
            safe_scene = hashlib.sha256(scene["scene_id"].encode("utf-8")).hexdigest()[:24]
            audit_root = case_root / "processing" / "masks" / mask_id / safe_scene
            valid_path = audit_root / "valid-mask.npy"
            record_path = audit_root / "mask-record.json"
            _write_npy(valid_path, result.valid_mask)
            write_canonical_json(record_path, result.record)
            valid_artifact = _artifact(
                valid_path,
                output_root,
                media_type="application/x-npy",
                role="candidate_mask_validity",
            )
            record_artifact = _artifact(
                record_path,
                output_root,
                media_type="application/json",
                role="candidate_mask_record",
            )
            processing_artifacts.extend((valid_artifact, record_artifact))
            scenes_audit.append(
                {
                    "scene_id": scene["scene_id"],
                    "valid_mask": valid_artifact,
                    "record": record_artifact,
                }
            )
        mask_audit[mask_id] = {
            "status": entry["status"],
            "reason": entry["reason"],
            "scenes": scenes_audit,
        }

    composition_audit: dict[str, Any] = {}
    for mask_id in sorted(mask_configs):
        composition_audit[mask_id] = {}
        for composition_id in sorted(composition_configs):
            entry = compositions.get(
                (mask_id, composition_id),
                {
                    "status": "unavailable",
                    "reason": scene_fatal or "composition unavailable",
                    "result": None,
                },
            )
            result = entry["result"]
            artifacts: dict[str, Any] | None = None
            if result is not None:
                audit_root = (
                    case_root / "processing" / "compositions" / mask_id / composition_id
                )
                values_path = audit_root / "values.npy"
                valid_path = audit_root / "valid-mask.npy"
                contributor_path = audit_root / "contributor-map.npy"
                record_path = audit_root / "composition-record.json"
                _write_npy(values_path, result.values)
                _write_npy(valid_path, result.valid_mask)
                _write_npy(contributor_path, result.contributor_map)
                write_canonical_json(record_path, result.record)
                artifacts = {
                    "values": _artifact(
                        values_path,
                        output_root,
                        media_type="application/x-npy",
                        role="candidate_composite_values",
                    ),
                    "valid_mask": _artifact(
                        valid_path,
                        output_root,
                        media_type="application/x-npy",
                        role="candidate_composite_validity",
                    ),
                    "contributor_map": _artifact(
                        contributor_path,
                        output_root,
                        media_type="application/x-npy",
                        role="candidate_composite_contributor_map",
                    ),
                    "record": _artifact(
                        record_path,
                        output_root,
                        media_type="application/json",
                        role="candidate_composition_record",
                    ),
                }
                processing_artifacts.extend(artifacts.values())
            composition_audit[mask_id][composition_id] = {
                "status": entry["status"],
                "reason": entry["reason"],
                "artifacts": artifacts,
            }

    cells: list[dict[str, Any]] = []
    render_by_cell: dict[
        str, tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, str | None]
    ] = {}
    for cell_spec in registry["factorial_design"]["treatment_cells"]:
        cell_id = cell_spec["cell_id"]
        composition_entry = compositions.get(
            (cell_spec["cloud_mask"], cell_spec["daily_composition"]),
            {"status": "unavailable", "reason": scene_fatal or "composition unavailable", "result": None},
        )
        drought_status = (
            _disabled_drought_status()
            if cell_spec["drought_adjustment"] == "drought-disabled-v1"
            else _candidate_drought_status(drought_result)
        )
        raw_artifacts: list[dict[str, Any]] = []
        result = composition_entry["result"]
        unavailable_reason = None
        availability = "available"
        valid = confidence = None
        composite_values = result.values if result is not None else None
        if composition_entry["status"] != "available":
            availability = "unavailable"
            unavailable_reason = composition_entry["reason"]
        elif baseline is None:
            availability = "unavailable"
            unavailable_reason = baseline_error or "accepted baseline range read unavailable"
        elif drought_status["status"] == "unavailable":
            availability = "unavailable"
            unavailable_reason = drought_status["reason"]
        else:
            z_adjustment = float(drought_status["z_threshold_adjustment"])
            valid, confidence, detection_record = _detect(
                result.values,
                result.valid_mask,
                baseline,
                comparison_mask=comparison_mask,
                z_adjustment=z_adjustment,
            )
            cell_dir = case_root / "factorial" / cell_id
            valid_path = cell_dir / "valid-mask.npy"
            confidence_path = cell_dir / "confidence.npy"
            contributor_path = cell_dir / "contributor-map.npy"
            _write_npy(valid_path, valid)
            _write_npy(confidence_path, confidence)
            _write_npy(contributor_path, result.contributor_map)
            raw_artifacts = [
                _artifact(valid_path, output_root, media_type="application/x-npy", role="raw_valid_detection_mask"),
                _artifact(confidence_path, output_root, media_type="application/x-npy", role="raw_detection_confidence"),
                _artifact(contributor_path, output_root, media_type="application/x-npy", role="composition_contributor_map"),
            ]
            detection_path = cell_dir / "detection-record.json"
            write_canonical_json(detection_path, detection_record)
            raw_artifacts.append(
                _artifact(detection_path, output_root, media_type="application/json", role="raw_detection_record")
            )
            if detection_record["valid_coverage_fraction"] < MINIMUM_VALID_COVERAGE:
                availability = "rejected_low_coverage"
                unavailable_reason = "valid_coverage_below_threshold"

        if result is None or valid is None:
            coverage = None
            contributing = []
            ordered_scene_ids = source_scene_ids
        else:
            valid_count = int(np.count_nonzero(valid))
            total_count = int(np.count_nonzero(comparison_mask))
            coverage_fraction = valid_count / total_count
            coverage = {
                "case_window_pixel_count": total_count,
                "valid_pixel_count": valid_count,
                "valid_coverage_fraction": coverage_fraction,
                "minimum_required_fraction": MINIMUM_VALID_COVERAGE,
                "accepted": coverage_fraction >= MINIMUM_VALID_COVERAGE,
                "rejection_reason": (
                    None if coverage_fraction >= MINIMUM_VALID_COVERAGE else "valid_coverage_below_threshold"
                ),
            }
            ordered_scene_ids = list(result.source_scene_ids)
            contributing = _contributing_scene_records(
                result, valid, comparison_mask
            )
        cell = {
            "cell_id": cell_id,
            "candidates": {family: cell_spec[family] for family in ("drought_adjustment", "cloud_mask", "daily_composition")},
            "availability": availability,
            "unavailable_reason": unavailable_reason,
            "ordered_source_scene_ids": ordered_scene_ids,
            "contributing_scenes": contributing,
            "coverage": coverage,
            "drought_status": drought_status,
            "artifacts": raw_artifacts,
        }
        cells.append(cell)
        render_by_cell[cell_id] = (composite_values, valid, confidence, unavailable_reason)

    candidate_panels: dict[str, dict[str, Any]] = {}
    factor_order = ("cloud_mask", "daily_composition", "drought_adjustment")
    for family in factor_order:
        candidate_panels[family] = {}
        for candidate_id in registry["families"][family]["candidate_ids"]:
            paired = [cell for cell in cells if cell["candidates"][family] == candidate_id]
            paired.sort(key=lambda cell: _paired_stratum_key(blind_case_id, family, cell))
            counts = {
                "available": sum(cell["availability"] == "available" for cell in paired),
                "rejected_low_coverage": sum(
                    cell["availability"] == "rejected_low_coverage" for cell in paired
                ),
                "unavailable": sum(cell["availability"] in {"unavailable", "error"} for cell in paired),
            }
            renderable = counts["available"] + counts["rejected_low_coverage"]
            status = "available" if counts["available"] == 4 else "partial" if renderable else "unreviewable"
            panel_path = None
            panel_artifact = None
            if renderable:
                panel_path = case_root / "candidate-panels" / family / f"{candidate_id}.png"
                _render_candidate_panel(
                    panel_path,
                    cells=paired,
                    render_by_cell=render_by_cell,
                    comparison_mask=comparison_mask,
                )
                panel_artifact = _artifact(panel_path, output_root, media_type="image/png", role="candidate_comparison_panel")
            coverages = [
                cell["coverage"]["valid_coverage_fraction"]
                for cell in paired
                if cell["coverage"] is not None
            ]
            contributor_ids = {
                item["scene_id"] for cell in paired for item in cell["contributing_scenes"]
            }
            candidate_panels[family][candidate_id] = {
                "status": status,
                "reason": None if status == "available" else (
                    f"{counts['available']} available, "
                    f"{counts['rejected_low_coverage']} rejected low coverage, "
                    f"{counts['unavailable']} unavailable paired cells"
                ),
                "path": None if panel_artifact is None else panel_artifact["path"],
                "bytes": None if panel_artifact is None else panel_artifact["bytes"],
                "sha256": None if panel_artifact is None else panel_artifact["sha256"],
                "media_type": None if panel_artifact is None else "image/png",
                "valid_coverage_fraction": None if not coverages else float(sum(coverages) / len(coverages)),
                "contributing_scene_count": len(contributor_ids),
                "source_scene_count": len(source_scene_ids),
                "source_scene_set_sha256": source_scene_ids_sha,
                "paired_cell_ids": [cell["cell_id"] for cell in paired],
                "coverage_summary": {
                    "available_cell_count": counts["available"],
                    "rejected_low_coverage_cell_count": counts[
                        "rejected_low_coverage"
                    ],
                    "unavailable_cell_count": counts["unavailable"],
                },
            }

    all_statuses = [cell["availability"] for cell in cells]
    case_status = (
        "available"
        if all(status == "available" for status in all_statuses)
        else "unavailable"
        if all(status in {"unavailable", "error"} for status in all_statuses)
        else "partial"
    )
    case_record = {
        "$schema": EVIDENCE_CASE_SCHEMA_URL,
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "blind_case_id": blind_case_id,
        "target_date": target_date,
        "target_geometry_sha256": canonical_geometry_sha256(
            reviewer_case["target_geometry"]
        )[1],
        "canonical_observation_id": None,
        "canonical_event_id": None,
        "status": case_status,
        "case_replaced": False,
        "source_query": {
            "catalog": "Element84 Earth Search",
            "stac_endpoint": EARTH_SEARCH,
            "collection_id": SENTINEL_COLLECTION,
            "catalog_accessed_at": catalog_accessed_at,
            "query": query,
            "query_error": query_error,
            "query_execution": query_execution,
            "source_scene_ids_sha256": source_scene_ids_sha,
        },
        "source_scenes": [scene["source_record"] for scene in loaded_scenes],
        "source_window_artifacts": source_artifacts,
        "processing_audit": {
            "mask_candidates": mask_audit,
            "compositions": composition_audit,
            "artifacts": processing_artifacts,
        },
        "grid": grid,
        "baseline": {
            "status": "available" if baseline is not None else "error",
            "reason": baseline_error,
            "baseline_id": baseline_manifest["baseline_id"],
            "baseline_version": baseline_manifest["baseline_version"],
            "manifest_sha256": BASELINE_MANIFEST_SHA256,
            "range_read": baseline_record,
            "artifacts": baseline_artifacts,
        },
        "drought": {
            "candidate_result": drought_result,
            "rainfall_reference": rainfall_reference,
        },
        "factorial_cells": cells,
        "candidate_panels": candidate_panels,
        "claims": {
            "qualified_human_label_present": False,
            "scientific_accuracy_claim": False,
            "method_selected_or_activated": False,
            "canonical_identity_inferred": False,
            "case_replaced": False,
            "desired_total_tuning_performed": False,
        },
    }
    record_path = case_root / "case-evidence.json"
    write_canonical_json(record_path, case_record)
    return {
        "sample_id": sample_id,
        "blind_case_id": blind_case_id,
        "target_date": target_date,
        "status": case_status,
        "record": _artifact(record_path, output_root),
    }


def build_phase2a4_evidence(config: Phase2A4EvidenceConfig) -> dict[str, Any]:
    """Build all 60 fixed-case evidence records and their eight candidate cells."""
    if config.output_dir.exists() and any(config.output_dir.iterdir()):
        raise Phase2A4EvidenceError(f"output directory is not empty: {config.output_dir}")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    repository_root = Path(__file__).resolve().parents[2]
    generator_inventory = _generator_source_inventory(repository_root)
    runtime_versions = _runtime_versions()
    schema_sources = {
        "phase2a4-candidate-evidence-manifest-v1.schema.json": (
            repository_root
            / "docs/contracts/phase2a/schemas/phase2a4-candidate-evidence-manifest-v1.schema.json"
        ),
        "phase2a4-candidate-evidence-case-v1.schema.json": (
            repository_root
            / "docs/contracts/phase2a/schemas/phase2a4-candidate-evidence-case-v1.schema.json"
        ),
    }
    for name, source in schema_sources.items():
        if not source.is_file():
            raise Phase2A4EvidenceError(f"candidate evidence schema is missing: {source}")
        destination = config.output_dir / "schemas" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    parent_result = validate_validation_package(config.parent_package_dir)
    parent_manifest_path = config.parent_package_dir / "manifest.json"
    if sha256_file(parent_manifest_path) != PHASE2A3_MANIFEST_SHA256:
        raise Phase2A4EvidenceError("frozen Phase 2A.3 manifest checksum changed")
    parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    crosswalk_path = config.parent_package_dir / "coordinator" / "crosswalk.json"
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    mappings = sorted(crosswalk["mappings"], key=lambda item: item["sample_id"])
    if len(mappings) != 60:
        raise Phase2A4EvidenceError("Phase 2A.3 source must contain exactly 60 cases")

    registry = json.loads(config.candidate_registry_path.read_text(encoding="utf-8"))
    registry_schema = _load_json(
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a4-candidate-registry-v1.schema.json"
    )
    Draft202012Validator.check_schema(registry_schema)
    _validate_schema(registry, registry_schema, "candidate registry")
    registry_sha = sha256_file(config.candidate_registry_path)
    rainfall = load_rainfall_monthly_values(config.rainfall_artifact_dir)
    baseline_manifest = _verify_baseline_manifest(config.baseline_manifest_path)
    embedded_baseline_path = config.output_dir / "inputs/baseline_manifest_v1.json"
    embedded_baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config.baseline_manifest_path, embedded_baseline_path)

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=config.workers) as executor:
        futures = {
            executor.submit(
                _build_case,
                mapping_record,
                parent_package=config.parent_package_dir,
                output_root=config.output_dir,
                registry=registry,
                rainfall=rainfall,
                rainfall_dir=config.rainfall_artifact_dir,
                baseline_manifest=baseline_manifest,
                baseline_base_url=config.baseline_public_base_url,
                catalog_accessed_at=config.catalog_accessed_at,
            ): mapping_record
            for mapping_record in mappings
        }
        for future in as_completed(futures):
            mapping_record = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(f"{mapping_record['sample_id']}: {_safe_error(exc)}")
    if errors:
        raise Phase2A4EvidenceError(
            "case evidence construction failed without substitution: " + " | ".join(sorted(errors))
        )
    results.sort(key=lambda item: item["sample_id"])
    manifest_schema = _load_json(
        config.output_dir
        / "schemas/phase2a4-candidate-evidence-manifest-v1.schema.json"
    )
    case_schema = _load_json(
        config.output_dir / "schemas/phase2a4-candidate-evidence-case-v1.schema.json"
    )
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator.check_schema(case_schema)
    for summary in results:
        _validate_schema(
            _load_json(config.output_dir / summary["record"]["path"]),
            case_schema,
            summary["record"]["path"],
        )

    inventory_paths = sorted(
        path
        for path in config.output_dir.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "CHECKSUMS.sha256"}
    )
    inventory = [_artifact(path, config.output_dir) for path in inventory_paths]
    if (
        _generator_source_inventory(repository_root) != generator_inventory
        or _runtime_versions() != runtime_versions
    ):
        raise Phase2A4EvidenceError(
            "candidate evidence generator source or runtime changed during construction"
        )
    baseline_access = {
        "public_base_url": config.baseline_public_base_url,
        "read_mode": "public_read_only_remote_cog_range_reads",
    }
    evidence_identity = {
        "phase2a3_package_id": parent_manifest["package_id"],
        "phase2a3_manifest_sha256": PHASE2A3_MANIFEST_SHA256,
        "candidate_registry_sha256": registry_sha,
        "rainfall_artifact_id": rainfall["artifact_id"],
        "rainfall_manifest_sha256": rainfall["manifest_sha256"],
        "baseline_manifest_sha256": BASELINE_MANIFEST_SHA256,
        "cases_sha256": canonical_sha256(results),
        "artifact_inventory_sha256": canonical_sha256(inventory),
        "generator_inventory_sha256": canonical_sha256(generator_inventory),
        "runtime_versions_sha256": canonical_sha256(runtime_versions),
        "baseline_access": baseline_access,
        "generated_at": config.generated_at,
        "catalog_accessed_at": config.catalog_accessed_at,
    }
    evidence_id = "p2a4-candidate-evidence-v1-" + identity_sha256(
        EVIDENCE_PIPELINE_VERSION, canonical_sha256(evidence_identity)
    )
    manifest = {
        "$schema": EVIDENCE_MANIFEST_SCHEMA_URL,
        "schema_version": SCHEMA_VERSION,
        "artifact_type": EVIDENCE_ARTIFACT_TYPE,
        "evidence_id": evidence_id,
        "pipeline_version": EVIDENCE_PIPELINE_VERSION,
        "generated_at": config.generated_at,
        "catalog_accessed_at": config.catalog_accessed_at,
        "runtime_versions": runtime_versions,
        "generator_source_inventory": generator_inventory,
        "schema_bindings": {
            "manifest": _artifact(
                config.output_dir
                / "schemas/phase2a4-candidate-evidence-manifest-v1.schema.json",
                config.output_dir,
            ),
            "case": _artifact(
                config.output_dir
                / "schemas/phase2a4-candidate-evidence-case-v1.schema.json",
                config.output_dir,
            ),
        },
        "phase2a3": {
            "package_id": parent_manifest["package_id"],
            "population_snapshot_id": parent_manifest["population_snapshot_id"],
            "manifest_sha256": PHASE2A3_MANIFEST_SHA256,
            "checksums_sha256": sha256_file(config.parent_package_dir / "CHECKSUMS.sha256"),
            "validated_file_count": parent_result["artifact_count"],
        },
        "candidate_registry": {
            "registry_id": registry["registry_id"],
            "path": "config/phase2a4_candidates_v1.json",
            "sha256": registry_sha,
        },
        "rainfall_reference": {
            "artifact_id": rainfall["artifact_id"],
            "manifest_sha256": rainfall["manifest_sha256"],
            "plan_sha256": rainfall["plan_sha256"],
        },
        "baseline": {
            "baseline_id": baseline_manifest["baseline_id"],
            "baseline_version": baseline_manifest["baseline_version"],
            "manifest_sha256": BASELINE_MANIFEST_SHA256,
            "manifest_artifact": _artifact(
                embedded_baseline_path, config.output_dir
            ),
            **baseline_access,
            "rebuild_performed": False,
        },
        "cases": results,
        "counts": {
            "case_count": len(results),
            "available": sum(item["status"] == "available" for item in results),
            "partial": sum(item["status"] == "partial" for item in results),
            "unavailable": sum(item["status"] == "unavailable" for item in results),
        },
        "claims": {
            "local_only": True,
            "qualified_human_labels_present": False,
            "scientific_accuracy_claim": False,
            "method_selected_or_activated": False,
            "baseline_rebuilt": False,
            "legacy_timeseries_used_or_mutated": False,
            "case_replacement_performed": False,
            "canonical_identity_inferred": False,
            "phase2a5_policy_modified": False,
        },
        "artifact_inventory_rule": "all files except manifest.json and CHECKSUMS.sha256",
        "artifact_inventory": inventory,
        "checksum_file": "CHECKSUMS.sha256",
    }
    _validate_schema(manifest, manifest_schema, "candidate evidence manifest")
    write_canonical_json(config.output_dir / "manifest.json", manifest)
    checksum_paths = [config.output_dir / "manifest.json", *inventory_paths]
    checksum_lines = [
        f"{sha256_file(path)}  {path.relative_to(config.output_dir).as_posix()}"
        for path in sorted(checksum_paths)
    ]
    (config.output_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n"
    )
    return validate_phase2a4_evidence_artifact(
        config.output_dir,
        parent_package_dir=config.parent_package_dir,
        candidate_registry_path=config.candidate_registry_path,
        rainfall_artifact_dir=config.rainfall_artifact_dir,
        baseline_manifest_path=config.baseline_manifest_path,
        repository_root=repository_root,
    )


def _verify_inventory(root: Path, manifest: Mapping[str, Any]) -> None:
    inventory = manifest.get("artifact_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise Phase2A4EvidenceError("candidate evidence inventory is missing")
    paths = [item.get("path") for item in inventory]
    if any(not isinstance(path, str) for path in paths) or len(paths) != len(set(paths)):
        raise Phase2A4EvidenceError("candidate evidence inventory paths are invalid")
    actual: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Phase2A4EvidenceError(f"symlink is forbidden: {path}")
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = path
    expected = set(paths) | {"manifest.json", "CHECKSUMS.sha256"}
    if set(actual) != expected:
        raise Phase2A4EvidenceError(
            "candidate evidence inventory mismatch; "
            f"missing={sorted(expected - set(actual))}, "
            f"unlisted={sorted(set(actual) - expected)}"
        )
    canonical_inventory = [
        _artifact(actual[path], root) for path in sorted(paths)
    ]
    if inventory != canonical_inventory:
        raise Phase2A4EvidenceError("candidate evidence inventory is not canonical")
    for item in inventory:
        _verify_artifact(actual[item["path"]], root, item)
    recorded: dict[str, str] = {}
    for number, line in enumerate(
        (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        match = _CHECKSUM_LINE.fullmatch(line)
        if match is None or match.group("path") in recorded:
            raise Phase2A4EvidenceError(f"invalid or duplicate checksum line {number}")
        recorded[match.group("path")] = match.group("sha")
    expected_checksum_paths = expected - {"CHECKSUMS.sha256"}
    if set(recorded) != expected_checksum_paths:
        raise Phase2A4EvidenceError("candidate evidence checksum inventory mismatch")
    for relative, digest in recorded.items():
        if sha256_file(actual[relative]) != digest:
            raise Phase2A4EvidenceError(f"candidate evidence checksum mismatch: {relative}")


def _artifact_records(value: Any) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if (
                isinstance(item.get("path"), str)
                and isinstance(item.get("bytes"), int)
                and isinstance(item.get("sha256"), str)
            ):
                candidate = dict(item)
                existing = records.get(candidate["path"])
                if existing is not None and existing != candidate:
                    raise Phase2A4EvidenceError(
                        f"conflicting artifact records: {candidate['path']}"
                    )
                records[candidate["path"]] = candidate
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return [records[path] for path in sorted(records)]


def _load_npy(path: Path) -> np.ndarray:
    try:
        value = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise Phase2A4EvidenceError(f"cannot load NPY artifact {path}: {exc}") from exc
    if value.dtype.kind not in "biuf":
        raise Phase2A4EvidenceError(f"unsupported NPY dtype: {path}")
    return value


def _arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    if left.shape != right.shape or left.dtype != right.dtype:
        return False
    if left.dtype.kind in "fc":
        return np.array_equal(left, right, equal_nan=True)
    return np.array_equal(left, right)


def _validate_output_record(record: Mapping[str, Any], label: str) -> None:
    payload = copy.deepcopy(dict(record))
    digest = payload.pop("output_sha256", None)
    if digest != canonical_sha256(payload):
        raise Phase2A4EvidenceError(f"{label} output hash mismatch")


def _comparison_mask_from_grid(grid: Mapping[str, Any]) -> np.ndarray:
    case_window = grid["case_window"]
    context = grid["context_window"]
    mask = np.zeros((context["height"], context["width"]), dtype=bool)
    col, row = context["comparison_offset_in_context"]
    mask[
        row : row + case_window["height"],
        col : col + case_window["width"],
    ] = True
    return mask


def _registry_cells(registry: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    families = ("drought_adjustment", "cloud_mask", "daily_composition")
    candidates = {
        family: set(registry["families"][family]["candidate_ids"])
        for family in families
    }
    cells: dict[str, dict[str, str]] = {}
    signatures: set[tuple[str, str, str]] = set()
    for item in registry["factorial_design"]["treatment_cells"]:
        cell_id = item["cell_id"]
        factors = {family: item[family] for family in families}
        if (
            cell_id in cells
            or any(factors[family] not in candidates[family] for family in families)
        ):
            raise Phase2A4EvidenceError("candidate registry factorial cell is invalid")
        signature = tuple(factors[family] for family in families)
        if signature in signatures:
            raise Phase2A4EvidenceError("candidate registry factorial cell is duplicated")
        signatures.add(signature)
        cells[cell_id] = factors
    if len(cells) != 8 or len(signatures) != 8:
        raise Phase2A4EvidenceError("candidate registry is not a complete 2x2x2 design")
    return cells


def _validate_query_execution(
    source_query: Mapping[str, Any],
    source_scenes: Sequence[Mapping[str, Any]],
    *,
    sample_id: str,
) -> None:
    execution = source_query.get("query_execution")
    if not isinstance(execution, Mapping) or set(execution) != {
        "status",
        "completed_page_count",
        "observed_item_count",
        "retained_unique_item_count",
        "collector_observed_exhaustion",
        "duplicate_item_ids",
        "page_trace",
        "page_trace_sha256",
    }:
        raise Phase2A4EvidenceError(
            f"STAC query execution trace is invalid: {sample_id}"
        )
    trace = execution["page_trace"]
    if not isinstance(trace, list) or execution["page_trace_sha256"] != canonical_sha256(
        trace
    ):
        raise Phase2A4EvidenceError(f"STAC page trace hash mismatch: {sample_id}")
    flattened_ids: list[str] = []
    flattened_hashes: list[str] = []
    for index, page in enumerate(trace, start=1):
        if not isinstance(page, Mapping) or set(page) != {
            "page_index",
            "item_count",
            "ordered_item_ids",
            "ordered_item_json_sha256",
            "advertised_next_page",
        }:
            raise Phase2A4EvidenceError(f"STAC page trace is invalid: {sample_id}")
        ids = page["ordered_item_ids"]
        hashes = page["ordered_item_json_sha256"]
        if (
            page["page_index"] != index
            or not isinstance(ids, list)
            or not isinstance(hashes, list)
            or page["item_count"] != len(ids)
            or len(ids) != len(hashes)
            or not isinstance(page["advertised_next_page"], bool)
        ):
            raise Phase2A4EvidenceError(
                f"STAC page trace counts/order are invalid: {sample_id}"
            )
        flattened_ids.extend(ids)
        flattened_hashes.extend(hashes)
    duplicate_ids = sorted(
        item_id
        for item_id, count in Counter(flattened_ids).items()
        if count > 1
    )
    scene_hashes = {
        scene["item_id"]: scene["stac_item_json_sha256"] for scene in source_scenes
    }
    if (
        execution["completed_page_count"] != len(trace)
        or execution["observed_item_count"] != len(flattened_ids)
        or execution["retained_unique_item_count"] != len(scene_hashes)
        or execution["duplicate_item_ids"] != duplicate_ids
        or sorted(set(flattened_ids), key=lambda value: value.encode("utf-8"))
        != list(scene_hashes)
        or any(
            scene_hashes.get(item_id) != digest
            for item_id, digest in zip(flattened_ids, flattened_hashes, strict=True)
        )
    ):
        raise Phase2A4EvidenceError(
            f"STAC page trace does not reconcile with retained scenes: {sample_id}"
        )
    exhausted = execution["collector_observed_exhaustion"]
    query_error = source_query.get("query_error")
    expected_status = (
        "complete"
        if query_error is None and exhausted
        else "partial"
        if trace
        else "error"
    )
    if execution["status"] != expected_status or not isinstance(exhausted, bool):
        raise Phase2A4EvidenceError(
            f"STAC query completeness status mismatch: {sample_id}"
        )
    if expected_status != "complete" and query_error is None:
        raise Phase2A4EvidenceError(
            f"incomplete STAC query has no retained failure: {sample_id}"
        )
    if exhausted and trace:
        # The trace contains the nonempty pages yielded by pystac-client.
        # Iterator exhaustion may occur after the client follows the last
        # yielded page's ``next`` link and suppresses an empty terminal page.
        inconsistent = any(
            not page["advertised_next_page"] for page in trace[:-1]
        )
        if inconsistent:
            raise Phase2A4EvidenceError(
                f"STAC pagination exhaustion contradicts retained links: {sample_id}"
            )


def _validate_stac_item_binding(
    item_json: Mapping[str, Any],
    scene: Mapping[str, Any],
    source_query: Mapping[str, Any],
    *,
    target_date: str,
    sample_id: str,
) -> None:
    scene_id = scene["item_id"]
    observed_at = _item_observed_at(item_json)
    self_href = _item_self_href(item_json, scene_id)
    properties = item_json.get("properties", {})
    cloud_cover = properties.get("eo:cloud_cover")
    try:
        intersects_query = shape(item_json["geometry"]).intersects(
            shape(source_query["query"]["intersects"])
        )
    except Exception as exc:
        raise Phase2A4EvidenceError(
            f"STAC item geometry is invalid: {sample_id}/{scene_id}"
        ) from exc
    if (
        set(scene)
        != {
            "catalog",
            "stac_endpoint",
            "collection_id",
            "item_id",
            "observed_at",
            "self_href",
            "stac_item_json_sha256",
            "assets",
        }
        or scene["catalog"] != "Element84 Earth Search"
        or scene["stac_endpoint"] != EARTH_SEARCH
        or item_json.get("id") != scene_id
        or canonical_sha256(item_json) != scene["stac_item_json_sha256"]
        or item_json.get("collection") != SENTINEL_COLLECTION
        or scene["collection_id"] != SENTINEL_COLLECTION
        or scene["observed_at"] != observed_at
        or observed_at[:10] != target_date
        or scene["self_href"] != self_href
        or isinstance(cloud_cover, bool)
        or not isinstance(cloud_cover, (int, float))
        or not math.isfinite(float(cloud_cover))
        or not float(cloud_cover) < 60.0
        or not intersects_query
    ):
        raise Phase2A4EvidenceError(
            f"STAC item provenance mismatch: {sample_id}/{scene_id}"
        )


def _validate_baseline_provenance(
    root: Path,
    case_root: Path,
    baseline_record: Mapping[str, Any],
    *,
    baseline_manifest: Mapping[str, Any],
    baseline_public_base_url: str,
    context_shape: tuple[int, int],
    month: int,
    sample_id: str,
) -> tuple[
    dict[str, dict[str, np.ndarray]] | None,
    list[dict[str, Any]],
]:
    _validate_retained_https_url(
        baseline_public_base_url, label="accepted baseline public base"
    )
    if set(baseline_record) != {
        "status",
        "reason",
        "baseline_id",
        "baseline_version",
        "manifest_sha256",
        "range_read",
        "artifacts",
    } or (
        baseline_record["baseline_id"] != baseline_manifest["baseline_id"]
        or baseline_record["baseline_version"]
        != baseline_manifest["baseline_version"]
        or baseline_record["manifest_sha256"] != BASELINE_MANIFEST_SHA256
    ):
        raise Phase2A4EvidenceError(
            f"accepted baseline identity mismatch: {sample_id}"
        )
    range_read = baseline_record["range_read"]
    if not isinstance(range_read, Mapping) or set(range_read) != {
        "month",
        "status",
        "reason",
        "objects",
    } or range_read["month"] != month:
        raise Phase2A4EvidenceError(
            f"accepted baseline range-read record is invalid: {sample_id}"
        )
    by_key = {item["key"]: item for item in baseline_manifest["objects"]}
    expected_keys = [
        f"baselines/{index_name}_month{month:02d}_{statistic}.tif"
        for index_name in INDEX_NAMES
        for statistic in ("mean", "std")
    ]
    objects = range_read["objects"]
    if not isinstance(objects, list) or [item.get("key") for item in objects] != expected_keys:
        raise Phase2A4EvidenceError(
            f"accepted baseline object order mismatch: {sample_id}"
        )
    arrays: dict[str, dict[str, np.ndarray]] = {
        index_name: {} for index_name in INDEX_NAMES
    }
    artifacts: list[dict[str, Any]] = []
    failures: list[str] = []
    for item in objects:
        key = item["key"]
        expected = by_key.get(key)
        if expected is None:
            raise Phase2A4EvidenceError(
                f"baseline range read references an unaccepted object: {sample_id}/{key}"
            )
        if set(item) != {
            "key",
            "status",
            "reason",
            "manifest_bytes",
            "manifest_sha256",
            "manifest_r2_etag",
            "unsigned_href",
            "http_metadata",
            "read_mode",
            "local_window",
            "checksum_scope_limitation",
        }:
            raise Phase2A4EvidenceError(
                f"baseline object provenance fields are invalid: {sample_id}/{key}"
            )
        href = f"{baseline_public_base_url.rstrip('/')}/{key}"
        _validate_retained_https_url(href, label=f"accepted baseline {key}")
        if (
            item["manifest_bytes"] != expected["bytes"]
            or item["manifest_sha256"] != expected["sha256"]
            or item["manifest_r2_etag"] != expected["r2_etag"]
            or item["unsigned_href"] != href
            or item["read_mode"] != _BASELINE_READ_MODE
        ):
            raise Phase2A4EvidenceError(
                f"baseline accepted-manifest binding mismatch: {sample_id}/{key}"
            )
        _validate_http_metadata_record(
            item["http_metadata"], label=f"accepted baseline {sample_id}/{key}"
        )
        if item["status"] == "available":
            if (
                item["reason"] is not None
                or item["http_metadata"]["content_length"] != expected["bytes"]
                or str(item["http_metadata"]["etag"] or "").strip('"')
                != expected["r2_etag"]
                or item["checksum_scope_limitation"]
                != "accepted_manifest_sha256_binds_full_object; local_window_sha256_binds_only_aligned_context_derivative"
            ):
                raise Phase2A4EvidenceError(
                    f"available baseline transport binding mismatch: {sample_id}/{key}"
                )
            filename = key.rsplit("/", 1)[-1]
            match = re.fullmatch(
                r"(?P<index>evi2|nbr|ndmi)_month[0-9]{2}_(?P<stat>mean|std)\.tif",
                filename,
            )
            if match is None:
                raise Phase2A4EvidenceError(
                    f"baseline object key is invalid: {sample_id}/{key}"
                )
            path = (
                case_root
                / "baseline-windows"
                / f"{match.group('index')}-{match.group('stat')}.npy"
            )
            value = _load_npy(path)
            artifact = _artifact(
                path,
                root,
                media_type="application/x-npy",
                role="accepted_baseline_window",
            )
            if (
                value.shape != context_shape
                or value.dtype != np.float32
                or item["local_window"] != artifact
            ):
                raise Phase2A4EvidenceError(
                    f"baseline local window mismatch: {sample_id}/{key}"
                )
            arrays[match.group("index")][match.group("stat")] = value
            artifacts.append(artifact)
        elif item["status"] == "error":
            if (
                not isinstance(item["reason"], str)
                or not item["reason"]
                or item["local_window"] is not None
                or item["checksum_scope_limitation"]
                != "accepted_manifest_sha256_binds_full_object; no local window was available"
            ):
                raise Phase2A4EvidenceError(
                    f"failed baseline provenance mismatch: {sample_id}/{key}"
                )
            failures.append(item["reason"])
        else:
            raise Phase2A4EvidenceError(
                f"baseline object status is invalid: {sample_id}/{key}"
            )
    expected_status = "available" if not failures else "error"
    expected_reason = None if not failures else " | ".join(failures)
    if (
        range_read["status"] != expected_status
        or range_read["reason"] != expected_reason
        or baseline_record["status"] != expected_status
        or baseline_record["reason"] != expected_reason
        or baseline_record["artifacts"] != artifacts
    ):
        raise Phase2A4EvidenceError(
            f"baseline availability summary mismatch: {sample_id}"
        )
    return (arrays if not failures else None), artifacts


def _validate_case_semantics(
    root: Path,
    record: Mapping[str, Any],
    *,
    registry: Mapping[str, Any],
    rainfall: Mapping[str, Any],
    baseline_manifest: Mapping[str, Any],
    baseline_public_base_url: str,
    parent_case: Mapping[str, Any] | None,
) -> None:
    sample_id = record["sample_id"]
    blind_id = record["blind_case_id"]
    case_root = root / "cases" / sample_id
    if parent_case is not None:
        reviewer_case = parent_case["reviewer_case"]
        expected_geometry_sha = canonical_geometry_sha256(
            reviewer_case["target_geometry"]
        )[1]
        expected_grid = _window_from_geometry(reviewer_case["target_geometry"])
        expected_grid.pop("comparison_mask")
        if (
            record["target_geometry_sha256"] != expected_geometry_sha
            or record["grid"] != expected_grid
            or record["target_date"] != reviewer_case["target_date"]
            or blind_id != parent_case["blind_case_id"]
        ):
            raise Phase2A4EvidenceError(
                f"candidate evidence parent geometry/window mismatch: {sample_id}"
            )
    grid = record["grid"]
    comparison_mask = _comparison_mask_from_grid(grid)
    expected_query = _query_record(
        record["target_date"], _query_geometry({"case_window": grid["case_window"]})
    )
    source_query = record["source_query"]
    try:
        accessed_at = dt.datetime.fromisoformat(
            source_query["catalog_accessed_at"].replace("Z", "+00:00")
        )
    except (AttributeError, KeyError, ValueError) as exc:
        raise Phase2A4EvidenceError(
            f"candidate evidence catalog access time is invalid: {sample_id}"
        ) from exc
    if (
        set(source_query)
        != {
            "catalog",
            "stac_endpoint",
            "collection_id",
            "catalog_accessed_at",
            "query",
            "query_error",
            "query_execution",
            "source_scene_ids_sha256",
        }
        or accessed_at.tzinfo is None
        or accessed_at.utcoffset() is None
        or source_query["catalog"] != "Element84 Earth Search"
        or source_query["stac_endpoint"] != EARTH_SEARCH
        or source_query["collection_id"] != SENTINEL_COLLECTION
        or source_query["query"] != expected_query
        or (
            source_query["query_error"] is not None
            and (
                not isinstance(source_query["query_error"], str)
                or not source_query["query_error"]
            )
        )
    ):
        raise Phase2A4EvidenceError(f"candidate evidence STAC query mismatch: {sample_id}")

    context_shape = (grid["context_window"]["height"], grid["context_window"]["width"])
    loaded_scenes: list[dict[str, Any]] = []
    source_artifacts: list[dict[str, Any]] = []
    scene_ids = [scene["item_id"] for scene in record["source_scenes"]]
    if scene_ids != sorted(scene_ids, key=lambda value: value.encode("utf-8")) or len(
        scene_ids
    ) != len(set(scene_ids)):
        raise Phase2A4EvidenceError(f"source scene order/identity mismatch: {sample_id}")
    if canonical_sha256(scene_ids) != source_query["source_scene_ids_sha256"]:
        raise Phase2A4EvidenceError(f"source scene digest mismatch: {sample_id}")
    _validate_query_execution(
        source_query, record["source_scenes"], sample_id=sample_id
    )
    for scene in record["source_scenes"]:
        scene_id = scene["item_id"]
        safe_scene = hashlib.sha256(scene_id.encode("utf-8")).hexdigest()[:24]
        item_path = case_root / "source-scenes" / f"{safe_scene}.json"
        item_json = _load_json(item_path)
        _validate_stac_item_binding(
            item_json,
            scene,
            source_query,
            target_date=record["target_date"],
            sample_id=sample_id,
        )
        source_artifacts.append(
            _artifact(item_path, root, media_type="application/json", role="stac_item_json")
        )
        arrays: dict[str, np.ndarray | None] = {}
        validities: dict[str, np.ndarray | None] = {}
        asset_records = scene["assets"]
        if [item["asset_key"] for item in asset_records] != list(REQUIRED_ASSETS):
            raise Phase2A4EvidenceError(f"source asset order mismatch: {sample_id}/{scene_id}")
        for asset in asset_records:
            key = asset["asset_key"]
            item_asset = item_json.get("assets", {}).get(key)
            if item_asset is None:
                if asset != _missing_source_asset_record(key):
                    raise Phase2A4EvidenceError(
                        f"missing STAC asset provenance mismatch: {sample_id}/{scene_id}/{key}"
                    )
                arrays[key] = None
                validities[key] = None
                continue
            if not isinstance(item_asset, Mapping):
                raise Phase2A4EvidenceError(
                    f"STAC asset metadata is invalid: {sample_id}/{scene_id}/{key}"
                )
            provider_href, href = _resolve_provider_asset_hrefs(
                item_asset.get("href"),
                label=f"STAC item {scene_id} asset {key}",
            )
            expected_shared = {
                "asset_key": key,
                "provider_href": provider_href,
                "unsigned_href": href,
                "href_resolution_policy": _ASSET_HREF_RESOLUTION_POLICY,
                "stac_asset_metadata_sha256": canonical_sha256(item_asset),
                "media_type": item_asset.get("type"),
                "read_mode": _SOURCE_READ_MODE,
                "upstream_full_asset_sha256": _stac_sha256(item_asset),
                "checksum_scope_limitation": _SOURCE_CHECKSUM_LIMITATION,
            }
            if any(asset.get(name) != value for name, value in expected_shared.items()):
                raise Phase2A4EvidenceError(
                    f"STAC asset metadata mismatch: {sample_id}/{scene_id}/{key}"
                )
            expected_normalization = _validate_reflectance_normalization_binding(
                key,
                asset,
                item_asset,
                label=f"{sample_id}/{scene_id}/{key}",
            )
            _validate_http_metadata_record(
                asset.get("http_metadata"),
                label=f"STAC asset {sample_id}/{scene_id}/{key}",
            )
            source_size = item_asset.get("file:size")
            if (
                isinstance(source_size, int)
                and not isinstance(source_size, bool)
                and asset["http_metadata"]["content_length"] is not None
                and asset["http_metadata"]["content_length"] != source_size
            ):
                raise Phase2A4EvidenceError(
                    f"STAC asset content length mismatch: {sample_id}/{scene_id}/{key}"
                )
            if asset.get("status") not in {"available", "error"}:
                raise Phase2A4EvidenceError(
                    f"present STAC asset has invalid status: {sample_id}/{scene_id}/{key}"
                )
            if asset["status"] == "available":
                if asset.get("reason") is not None:
                    raise Phase2A4EvidenceError(
                        f"available STAC asset has a failure reason: {sample_id}/{scene_id}/{key}"
                    )
                value_path = case_root / "source-windows" / safe_scene / f"{key}.npy"
                valid_path = case_root / "source-windows" / safe_scene / f"{key}-valid.npy"
                values = _load_npy(value_path)
                valid = _load_npy(valid_path)
                if values.shape != context_shape or valid.shape != context_shape or valid.dtype != np.bool_:
                    raise Phase2A4EvidenceError(
                        f"source window shape/dtype mismatch: {sample_id}/{scene_id}/{key}"
                    )
                expected_local = canonical_sha256(
                    {
                        "values": canonical_array_record(values),
                        "validity": canonical_array_record(valid),
                        "asset_metadata_sha256": asset["stac_asset_metadata_sha256"],
                        "reflectance_normalization": expected_normalization,
                        "aligned_context_window": grid["context_window"],
                    }
                )
                local = asset["local_window_data"]
                if (
                    not isinstance(local, Mapping)
                    or set(local)
                    != {"sha256", "dtype", "shape", "canonicalization"}
                    or local["sha256"] != expected_local
                    or local["shape"] != list(values.shape)
                    or local["dtype"] != str(values.dtype)
                    or local["canonicalization"]
                    != _LOCAL_WINDOW_CANONICALIZATION
                ):
                    raise Phase2A4EvidenceError(
                        f"source local-window digest mismatch: {sample_id}/{scene_id}/{key}"
                    )
                arrays[key] = values
                validities[key] = valid
                if key in REFLECTANCE_ASSETS:
                    _validate_reflectance_window_values(
                        values,
                        valid,
                        label=f"{sample_id}/{scene_id}/{key}",
                    )
                else:
                    _validate_categorical_source_values(key, values)
                source_artifacts.extend(
                    (
                        _artifact(value_path, root, media_type="application/x-npy", role="source_window_values"),
                        _artifact(valid_path, root, media_type="application/x-npy", role="source_window_validity"),
                    )
                )
            else:
                if (
                    not isinstance(asset.get("reason"), str)
                    or not asset["reason"]
                    or asset["local_window_data"] is not None
                ):
                    raise Phase2A4EvidenceError(
                        f"failed asset provenance mismatch: {sample_id}/{scene_id}/{key}"
                    )
                arrays[key] = None
                validities[key] = None
        loaded_scenes.append(
            {
                "scene_id": scene_id,
                "metadata_sha256": scene["stac_item_json_sha256"],
                "arrays": arrays,
                "validities": validities,
            }
        )
    if record["source_window_artifacts"] != source_artifacts:
        raise Phase2A4EvidenceError(f"source artifact list mismatch: {sample_id}")

    baseline_arrays, _baseline_artifacts = _validate_baseline_provenance(
        root,
        case_root,
        record["baseline"],
        baseline_manifest=baseline_manifest,
        baseline_public_base_url=baseline_public_base_url,
        context_shape=context_shape,
        month=dt.date.fromisoformat(record["target_date"]).month,
        sample_id=sample_id,
    )

    expected_drought = _drought_result(record["target_date"], registry=registry, rainfall=rainfall)
    _validate_output_record(expected_drought, f"drought {sample_id}")
    if record["drought"]["candidate_result"] != expected_drought:
        raise Phase2A4EvidenceError(f"drought result mismatch: {sample_id}")
    expected_rainfall_reference = _rainfall_reference_record(
        expected_drought, rainfall, Path("."), root
    )
    if record["drought"]["rainfall_reference"] != expected_rainfall_reference:
        raise Phase2A4EvidenceError(
            f"rainfall provenance mismatch: {sample_id}"
        )

    mask_configs = _mask_configs(registry)
    composition_configs = _composition_configs(registry)
    scene_fatal = source_query["query_error"]
    if source_query["query_execution"]["status"] != "complete" and scene_fatal is None:
        scene_fatal = "STAC query execution did not yield a complete scene set"
    if not loaded_scenes and scene_fatal is None:
        scene_fatal = "source query returned no same-day scenes"
    if loaded_scenes:
        failures = [
            f"{scene['scene_id']}:{key}"
            for scene in loaded_scenes
            for key in (*REFLECTANCE_ASSETS, "scl")
            if scene["arrays"][key] is None
        ]
        if failures:
            scene_fatal = "required source assets unavailable: " + ", ".join(failures)

    mask_results = _evaluate_mask_candidates(
        loaded_scenes,
        mask_configs,
        comparison_mask=comparison_mask,
        scene_fatal=scene_fatal,
    )
    processing = record["processing_audit"]
    expected_processing_artifacts: list[dict[str, Any]] = []
    for mask_id in sorted(mask_configs):
        expected_entry = mask_results.get(
            mask_id,
            {"status": "unavailable", "reason": scene_fatal or "mask unavailable", "per_scene": []},
        )
        stored = processing["mask_candidates"][mask_id]
        if stored["status"] != expected_entry["status"] or stored["reason"] != expected_entry["reason"]:
            raise Phase2A4EvidenceError(f"mask availability mismatch: {sample_id}/{mask_id}")
        expected_scenes = []
        for scene, result in expected_entry["per_scene"]:
            _validate_output_record(result.record, f"mask {sample_id}/{mask_id}/{scene['scene_id']}")
            safe_scene = hashlib.sha256(scene["scene_id"].encode("utf-8")).hexdigest()[:24]
            audit_root = case_root / "processing" / "masks" / mask_id / safe_scene
            valid_path = audit_root / "valid-mask.npy"
            record_path = audit_root / "mask-record.json"
            stored_valid = _load_npy(valid_path)
            stored_record = _load_json(record_path)
            if not _arrays_equal(stored_valid, result.valid_mask) or stored_record != result.record:
                raise Phase2A4EvidenceError(f"mask replay mismatch: {sample_id}/{mask_id}")
            valid_artifact = _artifact(valid_path, root, media_type="application/x-npy", role="candidate_mask_validity")
            record_artifact = _artifact(record_path, root, media_type="application/json", role="candidate_mask_record")
            expected_processing_artifacts.extend((valid_artifact, record_artifact))
            expected_scenes.append(
                {"scene_id": scene["scene_id"], "valid_mask": valid_artifact, "record": record_artifact}
            )
        if stored["scenes"] != expected_scenes:
            raise Phase2A4EvidenceError(f"mask audit inventory mismatch: {sample_id}/{mask_id}")

    compositions: dict[tuple[str, str], dict[str, Any]] = {}
    for mask_id, mask_entry in mask_results.items():
        for composition_id, config in composition_configs.items():
            key = (mask_id, composition_id)
            if mask_entry["status"] != "available":
                compositions[key] = {"status": "unavailable", "reason": mask_entry["reason"], "result": None}
                continue
            scenes_for_composition = []
            for scene, mask_result in mask_entry["per_scene"]:
                arrays = scene["arrays"]
                valid_mask = mask_result.valid_mask
                if config.method == "min_cloudprob_sclrank_sceneid":
                    if arrays["cloud"] is None:
                        scenes_for_composition = []
                        break
                    valid_mask = valid_mask & scene["validities"]["cloud"]
                scenes_for_composition.append(
                    CompositionScene(
                        scene_id=scene["scene_id"],
                        values=np.stack([arrays[name] for name in REFLECTANCE_ASSETS]),
                        valid_mask=valid_mask,
                        source_metadata_sha256=scene["metadata_sha256"],
                        scl=arrays["scl"],
                        cloud_probability=arrays["cloud"],
                    )
                )
            if not scenes_for_composition:
                compositions[key] = {
                    "status": "unavailable",
                    "reason": "cloud probability required for every source scene",
                    "result": None,
                }
                continue
            try:
                result = (
                    compose_coverage_ranked_first_valid(
                        scenes_for_composition, config=config, comparison_mask=comparison_mask
                    )
                    if config.method == "coverage_ranked_first_valid"
                    else compose_min_cloudprob_sclrank_sceneid(
                        scenes_for_composition, config=config, comparison_mask=comparison_mask
                    )
                )
                compositions[key] = {"status": "available", "reason": None, "result": result}
            except Exception as exc:
                compositions[key] = {"status": "unavailable", "reason": _safe_error(exc), "result": None}

    for mask_id in sorted(mask_configs):
        for composition_id in sorted(composition_configs):
            expected_entry = compositions.get(
                (mask_id, composition_id),
                {"status": "unavailable", "reason": scene_fatal or "composition unavailable", "result": None},
            )
            stored = processing["compositions"][mask_id][composition_id]
            if stored["status"] != expected_entry["status"] or stored["reason"] != expected_entry["reason"]:
                raise Phase2A4EvidenceError(
                    f"composition availability mismatch: {sample_id}/{mask_id}/{composition_id}"
                )
            result = expected_entry["result"]
            expected_artifacts = None
            if result is not None:
                _validate_output_record(result.record, f"composition {sample_id}/{mask_id}/{composition_id}")
                audit_root = case_root / "processing" / "compositions" / mask_id / composition_id
                paths = {
                    "values": audit_root / "values.npy",
                    "valid_mask": audit_root / "valid-mask.npy",
                    "contributor_map": audit_root / "contributor-map.npy",
                    "record": audit_root / "composition-record.json",
                }
                stored_values = _load_npy(paths["values"])
                expected_stored_values = _npy_storage_array(result.values)
                if (
                    not _arrays_equal(stored_values, expected_stored_values)
                    or canonical_array_record(stored_values)
                    != result.record["values"]
                    or not _arrays_equal(_load_npy(paths["valid_mask"]), result.valid_mask)
                    or not _arrays_equal(_load_npy(paths["contributor_map"]), result.contributor_map)
                    or _load_json(paths["record"]) != result.record
                ):
                    raise Phase2A4EvidenceError(
                        f"composition replay mismatch: {sample_id}/{mask_id}/{composition_id}"
                    )
                expected_artifacts = {
                    "values": _artifact(paths["values"], root, media_type="application/x-npy", role="candidate_composite_values"),
                    "valid_mask": _artifact(paths["valid_mask"], root, media_type="application/x-npy", role="candidate_composite_validity"),
                    "contributor_map": _artifact(paths["contributor_map"], root, media_type="application/x-npy", role="candidate_composite_contributor_map"),
                    "record": _artifact(paths["record"], root, media_type="application/json", role="candidate_composition_record"),
                }
                expected_processing_artifacts.extend(expected_artifacts.values())
            if stored["artifacts"] != expected_artifacts:
                raise Phase2A4EvidenceError(
                    f"composition audit inventory mismatch: {sample_id}/{mask_id}/{composition_id}"
                )
    if processing["artifacts"] != expected_processing_artifacts:
        raise Phase2A4EvidenceError(f"processing artifact list mismatch: {sample_id}")

    registry_cells = _registry_cells(registry)
    actual_cells = {cell["cell_id"]: cell for cell in record["factorial_cells"]}
    if len(actual_cells) != 8 or set(actual_cells) != set(registry_cells):
        raise Phase2A4EvidenceError(f"factorial cell population mismatch: {sample_id}")
    render_by_cell: dict[str, tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None, str | None]] = {}
    for cell_spec in registry["factorial_design"]["treatment_cells"]:
        cell_id = cell_spec["cell_id"]
        cell = actual_cells[cell_id]
        expected_factors = {
            family: cell_spec[family]
            for family in ("drought_adjustment", "cloud_mask", "daily_composition")
        }
        if cell["candidates"] != expected_factors:
            raise Phase2A4EvidenceError(f"factorial candidate mapping mismatch: {sample_id}/{cell_id}")
        composition = compositions.get(
            (cell_spec["cloud_mask"], cell_spec["daily_composition"]),
            {"status": "unavailable", "reason": scene_fatal or "composition unavailable", "result": None},
        )
        drought_status = (
            _disabled_drought_status()
            if cell_spec["drought_adjustment"] == "drought-disabled-v1"
            else _candidate_drought_status(expected_drought)
        )
        result = composition["result"]
        availability = "available"
        reason = None
        valid = confidence = None
        expected_artifacts: list[dict[str, Any]] = []
        if composition["status"] != "available":
            availability, reason = "unavailable", composition["reason"]
        elif baseline_arrays is None:
            availability, reason = "unavailable", record["baseline"]["reason"] or "accepted baseline range read unavailable"
        elif drought_status["status"] == "unavailable":
            availability, reason = "unavailable", drought_status["reason"]
        else:
            valid, confidence, detection = _detect(
                result.values,
                result.valid_mask,
                baseline_arrays,
                comparison_mask=comparison_mask,
                z_adjustment=float(drought_status["z_threshold_adjustment"]),
            )
            cell_root = case_root / "factorial" / cell_id
            paths = {
                "valid": cell_root / "valid-mask.npy",
                "confidence": cell_root / "confidence.npy",
                "contributor": cell_root / "contributor-map.npy",
                "record": cell_root / "detection-record.json",
            }
            if (
                not _arrays_equal(_load_npy(paths["valid"]), valid)
                or not _arrays_equal(_load_npy(paths["confidence"]), confidence)
                or not _arrays_equal(_load_npy(paths["contributor"]), result.contributor_map)
                or _load_json(paths["record"]) != detection
            ):
                raise Phase2A4EvidenceError(f"factorial detection replay mismatch: {sample_id}/{cell_id}")
            expected_artifacts = [
                _artifact(paths["valid"], root, media_type="application/x-npy", role="raw_valid_detection_mask"),
                _artifact(paths["confidence"], root, media_type="application/x-npy", role="raw_detection_confidence"),
                _artifact(paths["contributor"], root, media_type="application/x-npy", role="composition_contributor_map"),
                _artifact(paths["record"], root, media_type="application/json", role="raw_detection_record"),
            ]
            if detection["valid_coverage_fraction"] < MINIMUM_VALID_COVERAGE:
                availability, reason = (
                    "rejected_low_coverage",
                    "valid_coverage_below_threshold",
                )
        if result is None or valid is None:
            coverage = None
            contributing = []
            ordered_scene_ids = scene_ids
        else:
            total = int(np.count_nonzero(comparison_mask))
            valid_count = int(np.count_nonzero(valid))
            fraction = valid_count / total
            coverage = {
                "case_window_pixel_count": total,
                "valid_pixel_count": valid_count,
                "valid_coverage_fraction": fraction,
                "minimum_required_fraction": MINIMUM_VALID_COVERAGE,
                "accepted": fraction >= MINIMUM_VALID_COVERAGE,
                "rejection_reason": None if fraction >= MINIMUM_VALID_COVERAGE else "valid_coverage_below_threshold",
            }
            ordered_scene_ids = list(result.source_scene_ids)
            contributing = _contributing_scene_records(
                result, valid, comparison_mask
            )
        expected_cell = {
            "cell_id": cell_id,
            "candidates": expected_factors,
            "availability": availability,
            "unavailable_reason": reason,
            "ordered_source_scene_ids": ordered_scene_ids,
            "contributing_scenes": contributing,
            "coverage": coverage,
            "drought_status": drought_status,
            "artifacts": expected_artifacts,
        }
        if cell != expected_cell:
            raise Phase2A4EvidenceError(f"factorial cell semantics mismatch: {sample_id}/{cell_id}")
        render_by_cell[cell_id] = (
            None if result is None else result.values,
            valid,
            confidence,
            reason,
        )

    expected_case_status = (
        "available"
        if all(cell["availability"] == "available" for cell in actual_cells.values())
        else "unavailable"
        if all(cell["availability"] in {"unavailable", "error"} for cell in actual_cells.values())
        else "partial"
    )
    if record["status"] != expected_case_status:
        raise Phase2A4EvidenceError(f"case availability mismatch: {sample_id}")

    for family in ("cloud_mask", "daily_composition", "drought_adjustment"):
        family_panels = record["candidate_panels"][family]
        if set(family_panels) != set(registry["families"][family]["candidate_ids"]):
            raise Phase2A4EvidenceError(f"panel candidate population mismatch: {sample_id}/{family}")
        for candidate_id in registry["families"][family]["candidate_ids"]:
            paired = [
                cell for cell in actual_cells.values() if cell["candidates"][family] == candidate_id
            ]
            paired.sort(key=lambda cell: _paired_stratum_key(blind_id, family, cell))
            counts = {
                "available": sum(cell["availability"] == "available" for cell in paired),
                "rejected_low_coverage": sum(
                    cell["availability"] == "rejected_low_coverage" for cell in paired
                ),
                "unavailable": sum(cell["availability"] in {"unavailable", "error"} for cell in paired),
            }
            renderable = counts["available"] + counts["rejected_low_coverage"]
            status = "available" if counts["available"] == 4 else "partial" if renderable else "unreviewable"
            coverages = [
                cell["coverage"]["valid_coverage_fraction"]
                for cell in paired
                if cell["coverage"] is not None
            ]
            contributors = {
                item["scene_id"] for cell in paired for item in cell["contributing_scenes"]
            }
            panel = family_panels[candidate_id]
            expected_common = {
                "status": status,
                "reason": None if status == "available" else (
                    f"{counts['available']} available, "
                    f"{counts['rejected_low_coverage']} rejected low coverage, "
                    f"{counts['unavailable']} unavailable paired cells"
                ),
                "valid_coverage_fraction": None if not coverages else float(sum(coverages) / len(coverages)),
                "contributing_scene_count": len(contributors),
                "source_scene_count": len(scene_ids),
                "source_scene_set_sha256": canonical_sha256(scene_ids),
                "paired_cell_ids": [cell["cell_id"] for cell in paired],
                "coverage_summary": {
                    "available_cell_count": counts["available"],
                    "rejected_low_coverage_cell_count": counts[
                        "rejected_low_coverage"
                    ],
                    "unavailable_cell_count": counts["unavailable"],
                },
            }
            for key, value in expected_common.items():
                if panel[key] != value:
                    raise Phase2A4EvidenceError(f"panel metadata mismatch: {sample_id}/{family}/{candidate_id}")
            if renderable:
                panel_path = _safe_artifact_path(root, panel["path"])
                payload = _candidate_panel_bytes(
                    cells=paired,
                    render_by_cell=render_by_cell,
                    comparison_mask=comparison_mask,
                )
                if panel_path.read_bytes() != payload or panel["sha256"] != hashlib.sha256(payload).hexdigest():
                    raise Phase2A4EvidenceError(f"panel replay mismatch: {sample_id}/{family}/{candidate_id}")
            elif any(panel[key] is not None for key in ("path", "bytes", "sha256", "media_type")):
                raise Phase2A4EvidenceError(f"unreviewable panel exposes an artifact: {sample_id}/{family}/{candidate_id}")


def validate_phase2a4_evidence_artifact(
    evidence_root: Path,
    *,
    parent_package_dir: Path | None = None,
    candidate_registry_path: Path | None = None,
    rainfall_artifact_dir: Path | None = None,
    baseline_manifest_path: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Deeply validate provenance, replay outputs, checksums, and fixed cases."""
    root = Path(evidence_root).resolve()
    if not root.is_dir():
        raise Phase2A4EvidenceError(f"candidate evidence directory does not exist: {root}")
    manifest = _load_json(root / "manifest.json")
    manifest_schema_path = root / "schemas/phase2a4-candidate-evidence-manifest-v1.schema.json"
    case_schema_path = root / "schemas/phase2a4-candidate-evidence-case-v1.schema.json"
    manifest_schema = _load_json(manifest_schema_path)
    case_schema = _load_json(case_schema_path)
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator.check_schema(case_schema)
    _validate_schema(manifest, manifest_schema, "candidate evidence manifest")
    _verify_inventory(root, manifest)
    expected_bindings = {
        "manifest": _artifact(manifest_schema_path, root),
        "case": _artifact(case_schema_path, root),
    }
    if manifest["schema_bindings"] != expected_bindings:
        raise Phase2A4EvidenceError("candidate evidence schema bindings mismatch")

    parent_by_sample: dict[str, dict[str, Any]] = {}
    if parent_package_dir is not None:
        parent_root = Path(parent_package_dir).resolve()
        parent_result = validate_validation_package(parent_root)
        if sha256_file(parent_root / "manifest.json") != PHASE2A3_MANIFEST_SHA256:
            raise Phase2A4EvidenceError("frozen Phase 2A.3 manifest checksum changed")
        crosswalk = _load_json(parent_root / "coordinator/crosswalk.json")
        for mapping_record in crosswalk["mappings"]:
            source_case = _load_json(
                parent_root
                / "coordinator/cases"
                / f"{mapping_record['sample_id']}.json"
            )
            parent_by_sample[mapping_record["sample_id"]] = {
                **mapping_record,
                "reviewer_case": source_case["reviewer_case"],
            }
        if manifest["phase2a3"] != {
            "package_id": _load_json(parent_root / "manifest.json")["package_id"],
            "population_snapshot_id": _load_json(parent_root / "manifest.json")["population_snapshot_id"],
            "manifest_sha256": PHASE2A3_MANIFEST_SHA256,
            "checksums_sha256": sha256_file(parent_root / "CHECKSUMS.sha256"),
            "validated_file_count": parent_result["artifact_count"],
        }:
            raise Phase2A4EvidenceError("candidate evidence Phase 2A.3 binding mismatch")

    if candidate_registry_path is None:
        raise Phase2A4EvidenceError("deep validation requires the fixed candidate registry")
    registry_path = Path(candidate_registry_path).resolve()
    registry = _load_json(registry_path)
    _registry_cells(registry)
    if manifest["candidate_registry"] != {
        "registry_id": registry["registry_id"],
        "path": "config/phase2a4_candidates_v1.json",
        "sha256": sha256_file(registry_path),
    }:
        raise Phase2A4EvidenceError("candidate evidence registry binding mismatch")

    if rainfall_artifact_dir is None:
        raise Phase2A4EvidenceError("deep validation requires the rainfall artifact")
    rainfall_root = Path(rainfall_artifact_dir).resolve()
    rainfall = load_rainfall_monthly_values(rainfall_root)
    if manifest["rainfall_reference"] != {
        "artifact_id": rainfall["artifact_id"],
        "manifest_sha256": rainfall["manifest_sha256"],
        "plan_sha256": rainfall["plan_sha256"],
    }:
        raise Phase2A4EvidenceError("candidate evidence rainfall binding mismatch")
    embedded_baseline_path = root / "inputs/baseline_manifest_v1.json"
    baseline = _verify_baseline_manifest(embedded_baseline_path)
    if baseline_manifest_path is not None and embedded_baseline_path.read_bytes() != Path(
        baseline_manifest_path
    ).resolve().read_bytes():
        raise Phase2A4EvidenceError(
            "embedded accepted baseline manifest differs from external source"
        )
    expected_baseline_artifact = _artifact(embedded_baseline_path, root)
    _validate_retained_https_url(
        manifest["baseline"]["public_base_url"],
        label="candidate evidence baseline public base",
    )
    if (
        manifest["baseline"]["baseline_id"] != baseline["baseline_id"]
        or manifest["baseline"]["baseline_version"] != baseline["baseline_version"]
        or manifest["baseline"]["manifest_sha256"] != BASELINE_MANIFEST_SHA256
        or manifest["baseline"]["manifest_artifact"]
        != expected_baseline_artifact
        or manifest["baseline"]["read_mode"]
        != "public_read_only_remote_cog_range_reads"
        or manifest["baseline"]["rebuild_performed"] is not False
    ):
        raise Phase2A4EvidenceError("candidate evidence baseline binding mismatch")
    if repository_root is not None:
        expected_sources = _generator_source_inventory(Path(repository_root).resolve())
        if manifest["generator_source_inventory"] != expected_sources:
            raise Phase2A4EvidenceError("candidate evidence generator inventory mismatch")

    summaries = manifest["cases"]
    if [item["sample_id"] for item in summaries] != sorted(
        item["sample_id"] for item in summaries
    ) or len({item["sample_id"] for item in summaries}) != 60:
        raise Phase2A4EvidenceError("candidate evidence case order/population mismatch")
    referenced_paths = {
        "schemas/phase2a4-candidate-evidence-manifest-v1.schema.json",
        "schemas/phase2a4-candidate-evidence-case-v1.schema.json",
        expected_baseline_artifact["path"],
    }
    status_counts: Counter[str] = Counter()
    for summary in summaries:
        record_path = _safe_artifact_path(root, summary["record"]["path"])
        _verify_artifact(record_path, root, summary["record"])
        record = _load_json(record_path)
        _validate_schema(record, case_schema, summary["record"]["path"])
        if any(
            summary[field] != record[field]
            for field in ("sample_id", "blind_case_id", "target_date", "status")
        ):
            raise Phase2A4EvidenceError("candidate evidence case summary mismatch")
        if (
            record["source_query"]["catalog_accessed_at"]
            != manifest["catalog_accessed_at"]
        ):
            raise Phase2A4EvidenceError(
                "candidate evidence case catalog-access binding mismatch"
            )
        if record["canonical_observation_id"] is not None or record["canonical_event_id"] is not None:
            raise Phase2A4EvidenceError("candidate evidence inferred a canonical identity")
        parent_case = parent_by_sample.get(record["sample_id"])
        if parent_package_dir is not None and parent_case is None:
            raise Phase2A4EvidenceError("candidate evidence case is absent from frozen parent")
        _validate_case_semantics(
            root,
            record,
            registry=registry,
            rainfall=rainfall,
            baseline_manifest=baseline,
            baseline_public_base_url=manifest["baseline"]["public_base_url"],
            parent_case=parent_case,
        )
        for artifact in _artifact_records(record):
            path = _safe_artifact_path(root, artifact["path"])
            _verify_artifact(path, root, artifact)
            referenced_paths.add(artifact["path"])
        referenced_paths.add(summary["record"]["path"])
        status_counts[record["status"]] += 1
    expected_counts = {
        "case_count": 60,
        "available": status_counts["available"],
        "partial": status_counts["partial"],
        "unavailable": status_counts["unavailable"],
    }
    if manifest["counts"] != expected_counts:
        raise Phase2A4EvidenceError("candidate evidence status counts mismatch")
    inventory_paths = {item["path"] for item in manifest["artifact_inventory"]}
    if referenced_paths != inventory_paths:
        raise Phase2A4EvidenceError(
            "candidate evidence contains unreferenced or missing artifacts; "
            f"unreferenced={sorted(inventory_paths - referenced_paths)}, "
            f"missing={sorted(referenced_paths - inventory_paths)}"
        )
    identity = {
        "phase2a3_package_id": manifest["phase2a3"]["package_id"],
        "phase2a3_manifest_sha256": PHASE2A3_MANIFEST_SHA256,
        "candidate_registry_sha256": manifest["candidate_registry"]["sha256"],
        "rainfall_artifact_id": manifest["rainfall_reference"]["artifact_id"],
        "rainfall_manifest_sha256": manifest["rainfall_reference"]["manifest_sha256"],
        "baseline_manifest_sha256": BASELINE_MANIFEST_SHA256,
        "cases_sha256": canonical_sha256(summaries),
        "artifact_inventory_sha256": canonical_sha256(manifest["artifact_inventory"]),
        "generator_inventory_sha256": canonical_sha256(manifest["generator_source_inventory"]),
        "runtime_versions_sha256": canonical_sha256(manifest["runtime_versions"]),
        "baseline_access": {
            "public_base_url": manifest["baseline"]["public_base_url"],
            "read_mode": manifest["baseline"]["read_mode"],
        },
        "generated_at": manifest["generated_at"],
        "catalog_accessed_at": manifest["catalog_accessed_at"],
    }
    expected_id = "p2a4-candidate-evidence-v1-" + identity_sha256(
        EVIDENCE_PIPELINE_VERSION, canonical_sha256(identity)
    )
    if manifest["evidence_id"] != expected_id:
        raise Phase2A4EvidenceError("candidate evidence ID does not bind its inputs")
    return manifest


__all__ = [
    "Phase2A4EvidenceConfig",
    "Phase2A4EvidenceError",
    "build_phase2a4_evidence",
    "validate_phase2a4_evidence_artifact",
]
