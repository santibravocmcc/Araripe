"""Authoritative baseline-manifest validation and local raster auditing.

The current baseline generation is large and intentionally kept outside Git.
This module keeps its identity in a small checked-in manifest and provides the
read-only checks used after downloading the 72 rasters from object storage.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom

EXPECTED_INDICES = ("evi2", "nbr", "ndmi")
EXPECTED_MONTHS = tuple(range(1, 13))
EXPECTED_FILENAME_STATS = ("mean", "std")
EXPECTED_OBJECT_COUNT = 72
BASELINE_SCHEMA_VERSION = "1.0.0"
BASELINE_ID = "araripe-s2-sr-harmonized-monthly"
BASELINE_VERSION = "1.0.0"
MONITORING_EXTENT_ID = "araripe-implementation-rectangle-v1"
MONITORING_EXTENT_BOUNDS = (
    -40.89236812577142,
    -7.840780758480428,
    -38.95208146319247,
    -6.957104781339829,
)
MONITORING_EXTENT_GEOMETRY_SHA256 = (
    "b4986ef80d8a0d6e65bbb41b575dbd952c010415bf3aee93a88412b3b657e8c7"
)
MONITORING_EXTENT_BOUNDS_SHA256 = (
    "93f254373d6b203bca33aa5c356bd03fec3bff7f43c9c15b368cc2bdb7029f28"
)
MIN_EXTENT_COVERAGE = 0.99

_OBJECT_RE = re.compile(
    r"^(?P<index>evi2|nbr|ndmi)_month(?P<month>0[1-9]|1[0-2])_"
    r"(?P<filename_stat>mean|std)\.tif$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ETAG_RE = re.compile(r"^[0-9a-f]{32}(?:-\d+)?$")
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class BaselineAuditError(ValueError):
    """Raised when a manifest or raster set violates the baseline contract."""


def expected_filenames() -> tuple[str, ...]:
    """Return the exact canonical 72-file inventory in stable order."""
    return tuple(
        f"{index}_month{month:02d}_{stat}.tif"
        for index in EXPECTED_INDICES
        for month in EXPECTED_MONTHS
        for stat in EXPECTED_FILENAME_STATS
    )


def parse_baseline_filename(filename: str) -> dict[str, Any]:
    """Parse one canonical baseline filename into scientific components."""
    match = _OBJECT_RE.fullmatch(filename)
    if match is None:
        raise BaselineAuditError(f"unexpected baseline filename: {filename}")
    filename_stat = match.group("filename_stat")
    return {
        "index": match.group("index"),
        "month": int(match.group("month")),
        "filename_statistic": filename_stat,
        # Historical compatibility: *_mean.tif stores a multi-year median.
        "statistic": "median" if filename_stat == "mean" else "standard_deviation",
    }


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Compute a file SHA-256 without loading the raster into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Compute the single-part object ETag candidate for audit comparison."""
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_sha256(objects: Iterable[Mapping[str, Any]]) -> str:
    """Hash the immutable object identity list with deterministic JSON."""
    identity = [
        {
            "key": obj["key"],
            "bytes": obj["bytes"],
            "sha256": obj["sha256"],
        }
        for obj in sorted(objects, key=lambda item: item["key"])
    ]
    payload = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and structurally validate an authoritative baseline manifest."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineAuditError(f"cannot read baseline manifest {path}: {exc}") from exc
    validate_manifest(manifest)
    return manifest


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BaselineAuditError(message)


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate inventory, versions, provenance, QA, and aggregate arithmetic."""
    _require(
        manifest.get("schema_version") == BASELINE_SCHEMA_VERSION,
        f"schema_version must be {BASELINE_SCHEMA_VERSION}",
    )
    _require(manifest.get("baseline_id") == BASELINE_ID, "unexpected baseline_id")
    _require(
        manifest.get("baseline_version") == BASELINE_VERSION,
        "unexpected baseline_version",
    )
    _require(
        bool(_SEMVER_RE.fullmatch(str(manifest.get("baseline_version", "")))),
        "baseline_version must be semantic version x.y.z",
    )

    extent = manifest.get("monitoring_extent", {})
    _require(extent.get("extent_id") == MONITORING_EXTENT_ID, "extent_id mismatch")
    _require(
        tuple(extent.get("bounds", ())) == MONITORING_EXTENT_BOUNDS,
        "monitoring extent bounds mismatch",
    )
    _require(
        extent.get("geometry_sha256") == MONITORING_EXTENT_GEOMETRY_SHA256,
        "monitoring extent geometry checksum mismatch",
    )
    _require(
        extent.get("bounds_sha256") == MONITORING_EXTENT_BOUNDS_SHA256,
        "monitoring extent bounds checksum mismatch",
    )

    source = manifest.get("source", {})
    _require(
        source.get("collection_id") == "COPERNICUS/S2_SR_HARMONIZED",
        "unexpected source collection",
    )
    _require(
        source.get("years") == [2017, 2019, 2021, 2022, 2025],
        "baseline source-year set mismatch",
    )
    _require(
        source.get("reflectance_scale_divisor") == 10000,
        "reflectance scale divisor mismatch",
    )

    raster_contract = manifest.get("raster_contract", {})
    _require(
        raster_contract.get("expected_object_count") == EXPECTED_OBJECT_COUNT,
        "raster contract object count mismatch",
    )
    _require(
        raster_contract.get("indices") == list(EXPECTED_INDICES),
        "raster contract indices mismatch",
    )
    _require(
        raster_contract.get("months") == list(EXPECTED_MONTHS),
        "raster contract months mismatch",
    )

    objects = manifest.get("objects")
    _require(isinstance(objects, list), "objects must be a list")
    _require(len(objects) == EXPECTED_OBJECT_COUNT, "manifest must contain 72 objects")
    filenames = [obj.get("filename") for obj in objects]
    _require(
        sorted(filenames) == sorted(expected_filenames()),
        "manifest does not contain the exact canonical 72-file inventory",
    )

    keys: set[str] = set()
    for obj in objects:
        parsed = parse_baseline_filename(obj["filename"])
        _require(obj.get("key") == f"baselines/{obj['filename']}", "object key mismatch")
        _require(obj["key"] not in keys, f"duplicate object key: {obj['key']}")
        keys.add(obj["key"])
        for field in ("index", "month", "filename_statistic", "statistic"):
            _require(obj.get(field) == parsed[field], f"{obj['key']} {field} mismatch")
        _require(
            isinstance(obj.get("bytes"), int) and obj["bytes"] > 0,
            f"{obj['key']} invalid byte size",
        )
        _require(
            bool(_SHA256_RE.fullmatch(str(obj.get("sha256", "")))),
            f"{obj['key']} invalid SHA-256",
        )
        _require(
            bool(_ETAG_RE.fullmatch(str(obj.get("r2_etag", "")))),
            f"{obj['key']} invalid R2 ETag",
        )
        _require(obj.get("grid_matches_reference") is True, f"{obj['key']} grid drift")
        _require(obj.get("crs") == "EPSG:32724", f"{obj['key']} CRS mismatch")
        _require(obj.get("dtype") == "float32", f"{obj['key']} dtype mismatch")
        _require(obj.get("band_count") == 1, f"{obj['key']} band-count mismatch")
        _require(obj.get("nodata") == "NaN", f"{obj['key']} NoData mismatch")
        _require(
            obj.get("range_violation_pixels") == 0,
            f"{obj['key']} contains out-of-range pixels",
        )
        _require(
            obj.get("extent_coverage_fraction", 0) >= MIN_EXTENT_COVERAGE,
            f"{obj['key']} has insufficient monitoring-extent coverage",
        )
        if obj["filename_statistic"] == "std":
            _require(obj.get("minimum", -1) >= 0, f"{obj['key']} has negative std")

    aggregate = manifest.get("aggregate", {})
    _require(
        aggregate.get("object_count") == len(objects),
        "aggregate object count mismatch",
    )
    _require(
        aggregate.get("total_bytes") == sum(obj["bytes"] for obj in objects),
        "aggregate byte count mismatch",
    )
    _require(
        aggregate.get("inventory_sha256") == inventory_sha256(objects),
        "aggregate inventory checksum mismatch",
    )
    _require(
        math.isclose(
            aggregate.get("minimum_extent_coverage_fraction", -1),
            min(obj["extent_coverage_fraction"] for obj in objects),
            abs_tol=1e-12,
        ),
        "aggregate minimum extent coverage mismatch",
    )
    decision = manifest.get("decision", {})
    _require(
        decision.get("rebuild_required") is False,
        "accepted v1 manifest must record the no-rebuild audit decision",
    )


def _monitoring_geometry() -> dict[str, Any]:
    west, south, east, north = MONITORING_EXTENT_BOUNDS
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }


def _range_limits(index: str, filename_stat: str) -> tuple[float, float]:
    if filename_stat == "std":
        return 0.0, 1.5
    if index in {"ndmi", "nbr"}:
        return -1.0, 1.0
    return -1.5, 1.5


def _remote_by_key(
    remote_inventory: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    if remote_inventory is None:
        return {}
    return {item["key"]: item for item in remote_inventory}


def audit_baseline_directory(
    baselines_dir: Path,
    remote_inventory: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read every expected raster and return per-object manifest evidence."""
    baselines_dir = Path(baselines_dir)
    actual = sorted(path.name for path in baselines_dir.glob("*.tif"))
    _require(
        actual == sorted(expected_filenames()),
        "local directory does not contain the exact canonical 72-file inventory",
    )
    remote = _remote_by_key(remote_inventory)
    if remote:
        _require(
            sorted(remote) == [f"baselines/{name}" for name in sorted(expected_filenames())],
            "R2 inventory does not contain the exact canonical 72-object inventory",
        )

    reference_grid: dict[str, Any] | None = None
    extent_mask: np.ndarray | None = None
    extent_pixel_count = 0
    objects: list[dict[str, Any]] = []

    for filename in expected_filenames():
        path = baselines_dir / filename
        parsed = parse_baseline_filename(filename)
        key = f"baselines/{filename}"
        remote_obj = remote.get(key, {})

        with rasterio.open(path) as src:
            grid = {
                "crs": src.crs.to_string() if src.crs else None,
                "width": src.width,
                "height": src.height,
                "transform": list(src.transform)[:6],
                "bounds": list(src.bounds),
                "pixel_size": [abs(src.transform.a), abs(src.transform.e)],
            }
            if reference_grid is None:
                reference_grid = grid
                projected_extent = transform_geom(
                    "EPSG:4326",
                    src.crs,
                    _monitoring_geometry(),
                    precision=12,
                )
                extent_mask = geometry_mask(
                    [projected_extent],
                    out_shape=(src.height, src.width),
                    transform=src.transform,
                    invert=True,
                    all_touched=False,
                )
                extent_pixel_count = int(np.count_nonzero(extent_mask))
                _require(extent_pixel_count > 0, "monitoring extent misses baseline grid")
            assert extent_mask is not None
            assert reference_grid is not None
            grid_matches_reference = grid == reference_grid

            finite_count = 0
            extent_valid_count = 0
            range_violation_count = 0
            minimum = math.inf
            maximum = -math.inf
            lower, upper = _range_limits(parsed["index"], parsed["filename_statistic"])

            for _, window in src.block_windows(1):
                values = src.read(1, window=window, masked=False)
                finite = np.isfinite(values)
                count = int(np.count_nonzero(finite))
                finite_count += count
                if count:
                    valid_values = values[finite]
                    minimum = min(minimum, float(valid_values.min()))
                    maximum = max(maximum, float(valid_values.max()))
                    range_violation_count += int(
                        np.count_nonzero((valid_values < lower) | (valid_values > upper))
                    )
                rows, cols = window.toslices()
                extent_valid_count += int(
                    np.count_nonzero(finite & extent_mask[rows, cols])
                )

            _require(finite_count > 0, f"{filename} has no finite pixels")
            local_size = path.stat().st_size
            if remote_obj:
                _require(
                    int(remote_obj["size"]) == local_size,
                    f"{key} local/R2 byte-size mismatch",
                )
            local_md5 = md5_file(path)
            etag = str(remote_obj.get("etag") or local_md5).strip('"')
            # Current objects are single-part. A future multipart ETag is retained
            # as metadata but is not treated as a content checksum.
            if "-" not in etag:
                _require(etag == local_md5, f"{key} local/R2 ETag mismatch")

            objects.append(
                {
                    "key": key,
                    "filename": filename,
                    **parsed,
                    "bytes": local_size,
                    "sha256": sha256_file(path),
                    "r2_etag": etag,
                    "r2_last_modified": remote_obj.get("last_modified"),
                    "r2_storage_class": remote_obj.get("storage_class", "Standard"),
                    "r2_content_type": (
                        remote_obj.get("http_metadata", {}).get("contentType")
                        or remote_obj.get("content_type")
                        or "image/tiff"
                    ),
                    "crs": grid["crs"],
                    "width": grid["width"],
                    "height": grid["height"],
                    "transform": grid["transform"],
                    "bounds": grid["bounds"],
                    "pixel_size": grid["pixel_size"],
                    "grid_matches_reference": grid_matches_reference,
                    "dtype": src.dtypes[0],
                    "band_count": src.count,
                    "nodata": "NaN" if src.nodata is not None and math.isnan(src.nodata) else src.nodata,
                    "compression": src.compression.name if src.compression else None,
                    "tiled": src.is_tiled,
                    "block_shape": list(src.block_shapes[0]),
                    "overview_levels": src.overviews(1),
                    "finite_pixels": finite_count,
                    "valid_fraction": finite_count / (src.width * src.height),
                    "monitoring_extent_pixels": extent_pixel_count,
                    "monitoring_extent_valid_pixels": extent_valid_count,
                    "extent_coverage_fraction": extent_valid_count / extent_pixel_count,
                    "minimum": minimum,
                    "maximum": maximum,
                    "accepted_range": [lower, upper],
                    "range_violation_pixels": range_violation_count,
                }
            )

    return objects


def build_manifest(
    objects: list[dict[str, Any]],
    *,
    audit_date: str,
) -> dict[str, Any]:
    """Build the accepted v1 manifest around fully audited object evidence."""
    _require(len(objects) == EXPECTED_OBJECT_COUNT, "cannot build incomplete manifest")
    reference = objects[0]
    manifest = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "baseline_version": BASELINE_VERSION,
        "status": "accepted_audit_generation",
        "audit_date": audit_date,
        "decision": {
            "rebuild_required": False,
            "reason": (
                "All 72 existing objects passed checksum, inventory, grid, scale, "
                "range, and monitoring-extent coverage checks. Rebuilding would not "
                "resolve the documented missing historical scene/task provenance and "
                "is not scientifically required before the method-selection pilot."
            ),
            "limitations": [
                "The source scene IDs, GEE task IDs, and original 12 export checksums were not retained.",
                "The historical *_mean.tif label stores a multi-year median.",
                "The split GeoTIFFs are tiled and range-readable but have no internal overview levels.",
                "The baseline build used the rounded generation rectangle; the audited grid fully covers the approved exact monitoring extent.",
            ],
        },
        "source": {
            "provider": "Google Earth Engine / Copernicus Sentinel-2",
            "collection_id": "COPERNICUS/S2_SR_HARMONIZED",
            "years": [2017, 2019, 2021, 2022, 2025],
            "year_selection": {
                "method": "expert-reviewed historical selection",
                "status": "partially_reconstructed",
                "diagnostic_script": "scripts/select_baseline_years.py",
                "note": (
                    "The diagnostic ranking did not automatically select the adopted "
                    "set. The manifest, not a retrofitted ranking rule, is authoritative."
                ),
            },
            "scene_cloud_filter_percent": 40,
            "scl_clear_classes": [2, 4, 5, 6, 7, 11],
            "reflectance_scale_divisor": 10000,
            "indices": {
                "ndmi": "(B8A-B11)/(B8A+B11)",
                "nbr": "(B8A-B12)/(B8A+B12)",
                "evi2": "2.5*(B8-B4)/(B8+2.4*B4+1)",
            },
            "monthly_central_statistic": "median",
            "monthly_dispersion_statistic": "standard_deviation",
            "generator": {
                "script": "scripts/build_baseline_gee.py",
                "splitter": "scripts/split_gee_baselines.py",
                "repository_commit": "fecbde3e87671c214b0efbcde14615b803c2e51f",
                "target_crs": "EPSG:32724",
                "scale_m": 20,
                "generation_bounds_epsg4326": [-40.9, -7.85, -38.95, -6.95],
                "output_sentinel": -9999,
                "splitter_range_guard": [-1.5, 1.5],
            },
            "provenance_completeness": {
                "status": "partial",
                "retained": [
                    "collection",
                    "years",
                    "query and transform configuration",
                    "generator commit",
                    "72 final object checksums",
                    "R2 object metadata",
                ],
                "missing": [
                    "provider-native scene IDs per month",
                    "source processing-baseline versions per scene",
                    "GEE task IDs",
                    "GEE query fingerprint",
                    "12 original multi-band export checksums",
                ],
            },
        },
        "monitoring_extent": {
            "extent_id": MONITORING_EXTENT_ID,
            "scope": "APA and surroundings",
            "crs": "EPSG:4326",
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
            "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
        },
        "raster_contract": {
            "expected_object_count": EXPECTED_OBJECT_COUNT,
            "indices": list(EXPECTED_INDICES),
            "months": list(EXPECTED_MONTHS),
            "filename_statistics": {
                "mean": "multi-year monthly median",
                "std": "multi-year monthly standard deviation",
            },
            "crs": reference["crs"],
            "width": reference["width"],
            "height": reference["height"],
            "transform": reference["transform"],
            "bounds": reference["bounds"],
            "pixel_size": reference["pixel_size"],
            "dtype": "float32",
            "band_count": 1,
            "nodata": "NaN",
            "minimum_extent_coverage_fraction": MIN_EXTENT_COVERAGE,
        },
        "aggregate": {
            "object_count": len(objects),
            "total_bytes": sum(obj["bytes"] for obj in objects),
            "inventory_sha256": inventory_sha256(objects),
            "minimum_extent_coverage_fraction": min(
                obj["extent_coverage_fraction"] for obj in objects
            ),
            "maximum_extent_coverage_fraction": max(
                obj["extent_coverage_fraction"] for obj in objects
            ),
            "range_violation_pixels": sum(
                obj["range_violation_pixels"] for obj in objects
            ),
        },
        "objects": objects,
    }
    validate_manifest(manifest)
    return manifest


def compare_local_files_to_manifest(
    baselines_dir: Path,
    manifest: Mapping[str, Any],
) -> None:
    """Verify exact local file sizes and SHA-256 values against the manifest."""
    validate_manifest(manifest)
    baselines_dir = Path(baselines_dir)
    actual = sorted(path.name for path in baselines_dir.glob("*.tif"))
    _require(
        actual == sorted(expected_filenames()),
        "local baseline inventory differs from the manifest",
    )
    for obj in manifest["objects"]:
        path = baselines_dir / obj["filename"]
        _require(path.stat().st_size == obj["bytes"], f"{obj['filename']} size mismatch")
        _require(
            sha256_file(path) == obj["sha256"],
            f"{obj['filename']} checksum mismatch",
        )
