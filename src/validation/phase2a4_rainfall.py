"""Deterministic local CHIRPS rainfall-reference artifacts for Phase 2A.4.

This module deliberately stops at a provenance-bound monthly rainfall input.
It does not calculate SPI, activate drought adjustment, replay detections, or
write to any remote service.  Every 1981--2025 reference month and every
explicitly requested target month remains present as either a checksummed local
window or an error record; a failed month is never substituted.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import io
import json
import math
import os
import platform
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import numpy as np
import rasterio
from rasterio.windows import Window

from src.detection.baseline_manifest import (
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_BOUNDS_SHA256,
    MONITORING_EXTENT_GEOMETRY_SHA256,
    MONITORING_EXTENT_ID,
    sha256_file,
)
from src.detection.identity import (
    canonical_json_bytes,
    canonical_sha256,
    identity_sha256,
)


RAINFALL_SCHEMA_VERSION = "1.0.0"
RAINFALL_ARTIFACT_TYPE = "phase2a4_chirps_monthly_reference"
RAINFALL_PIPELINE_VERSION = "phase2a4-rainfall-reference-v1"
CHIRPS_PROVIDER = "Climate Hazards Center, UC Santa Barbara"
CHIRPS_DATASET = "CHIRPS 2.0 monthly precipitation"
CHIRPS_COG_BASE_URL = (
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/cogs"
)
CHIRPS_COG_PATTERN = "chirps-v2.0.YYYY.MM.cog"
REFERENCE_START_MONTH = "1981-01"
REFERENCE_END_MONTH = "2025-12"
REFERENCE_START_YEAR = 1981
REFERENCE_END_YEAR = 2025
REFERENCE_MONTH_COUNT = (REFERENCE_END_YEAR - REFERENCE_START_YEAR + 1) * 12

_MONTH_RE = re.compile(r"^(?P<year>[1-9][0-9]{3})-(?P<month>0[1-9]|1[0-2])$")
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_URL_WITH_QUERY = re.compile(r"(https?://[^?\s'\"<>]+)\?[^\s'\"<>]+")
_URL_WITH_USERINFO = re.compile(r"(https?://)[^/@\s]+@")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[-_]?key|credential|password|secret|signature|token)"
    r"\s*[:=]\s*[^\s,;]+"
)
_CHECKSUM_LINE = re.compile(r"^(?P<sha>[0-9a-f]{64})  (?P<path>[^\n]+)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HTTP_FIELDS = (
    "status_code",
    "content_length",
    "etag",
    "last_modified",
    "content_type",
    "accept_ranges",
)
_RAINFALL_GENERATOR_SOURCE_PATHS = (
    "src/detection/baseline_manifest.py",
    "src/detection/identity.py",
    "src/validation/phase2a4_rainfall.py",
    "scripts/build_phase2a4_rainfall_reference.py",
)


class RainfallArtifactError(ValueError):
    """Raised when a rainfall artifact or build plan is invalid."""


class RainfallFetchError(RuntimeError):
    """One retained source-month failure, optionally with HTTP metadata."""

    def __init__(self, message: str, *, http_metadata: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.http_metadata = sanitize_http_metadata(http_metadata or {})


@dataclass(frozen=True)
class FetchedRainfallWindow:
    """One source window selected by cell center from a monthly CHIRPS raster."""

    values: np.ndarray
    latitude_centers: np.ndarray
    longitude_centers: np.ndarray
    source_grid: Mapping[str, Any]
    http_metadata: Mapping[str, Any]


FetchMonth = Callable[
    [str, str, tuple[float, float, float, float], str],
    FetchedRainfallWindow,
]


def parse_month(value: str) -> tuple[int, int]:
    """Parse an explicit ``YYYY-MM`` without consulting the wall clock."""
    match = _MONTH_RE.fullmatch(str(value))
    if match is None:
        raise RainfallArtifactError(f"invalid month {value!r}; expected YYYY-MM")
    return int(match.group("year")), int(match.group("month"))


def validate_fixed_timestamp(value: str, *, label: str) -> str:
    """Require an explicit timezone-aware RFC3339 timestamp and preserve it."""
    if not isinstance(value, str) or _RFC3339_RE.fullmatch(value) is None:
        raise RainfallArtifactError(f"{label} must be a fixed RFC3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RainfallArtifactError(
            f"{label} must be a fixed RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RainfallArtifactError(f"{label} must include an explicit UTC offset")
    return value


def iter_reference_months() -> tuple[str, ...]:
    """Return the immutable 540-month 1981-01 through 2025-12 reference."""
    return tuple(
        f"{year:04d}-{month:02d}"
        for year in range(REFERENCE_START_YEAR, REFERENCE_END_YEAR + 1)
        for month in range(1, 13)
    )


def chirps_cog_url(month: str) -> str:
    """Return the official public monthly CHIRPS 2.0 COG URL."""
    year, number = parse_month(month)
    return f"{CHIRPS_COG_BASE_URL}/chirps-v2.0.{year:04d}.{number:02d}.cog"


def build_month_plan(target_months: Iterable[str]) -> list[dict[str, Any]]:
    """Combine the fixed reference with exact, explicit target months."""
    targets = sorted({str(value) for value in target_months})
    if not targets:
        raise RainfallArtifactError("at least one explicit target month is required")
    for month in targets:
        parse_month(month)
    reference = set(iter_reference_months())
    target_set = set(targets)
    return [
        {
            "month": month,
            "roles": [
                role
                for role, members in (
                    ("reference", reference),
                    ("target", target_set),
                )
                if month in members
            ],
            "source_url": chirps_cog_url(month),
        }
        for month in sorted(reference | target_set)
    ]


def _safe_error_message(error: BaseException | str, limit: int = 600) -> str:
    value = str(error).replace("\r", " ").replace("\n", " ")
    value = _URL_WITH_QUERY.sub(r"\1?[query-redacted]", value)
    value = _URL_WITH_USERINFO.sub(r"\1[userinfo-redacted]@", value)
    value = _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", value)
    return value[:limit]


def _clean_header(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = _safe_error_message(value, limit=500).strip()
    return cleaned[:500] or None


def sanitize_http_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a small non-secret allowlist of reproducibility-relevant headers."""
    if not isinstance(value, Mapping):
        value = {}
    status = value.get("status_code")
    length = value.get("content_length")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    try:
        length = int(length) if length is not None else None
    except (TypeError, ValueError):
        length = None
    if status is not None and not 100 <= status <= 599:
        status = None
    if length is not None and length < 0:
        length = None
    return {
        "status_code": status,
        "content_length": length,
        "etag": _clean_header(value.get("etag")),
        "last_modified": _clean_header(value.get("last_modified")),
        "content_type": _clean_header(value.get("content_type")),
        "accept_ranges": _clean_header(value.get("accept_ranges")),
    }


def _validate_public_source_url(url: str) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != "data.chc.ucsb.edu"
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise RainfallArtifactError("CHIRPS source URL is not the fixed public endpoint")
    if not parts.path.startswith(
        "/products/CHIRPS-2.0/global_monthly/cogs/chirps-v2.0."
    ) or not parts.path.endswith(".cog"):
        raise RainfallArtifactError("CHIRPS source URL does not match the official COG pattern")


def _http_metadata(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    _validate_public_source_url(url)
    request = Request(
        url,
        method="HEAD",
        headers={"User-Agent": "araripe-phase2a4-rainfall-reference/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            headers = response.headers
            return sanitize_http_metadata(
                {
                    "status_code": response.status,
                    "content_length": headers.get("Content-Length"),
                    "etag": headers.get("ETag"),
                    "last_modified": headers.get("Last-Modified"),
                    "content_type": headers.get("Content-Type"),
                    "accept_ranges": headers.get("Accept-Ranges"),
                }
            )
    except HTTPError as exc:
        metadata = sanitize_http_metadata(
            {
                "status_code": exc.code,
                "content_length": exc.headers.get("Content-Length"),
                "etag": exc.headers.get("ETag"),
                "last_modified": exc.headers.get("Last-Modified"),
                "content_type": exc.headers.get("Content-Type"),
                "accept_ranges": exc.headers.get("Accept-Ranges"),
            }
        )
        raise RainfallFetchError(
            f"HTTP {exc.code} for official CHIRPS month", http_metadata=metadata
        ) from exc
    except (URLError, OSError) as exc:
        raise RainfallFetchError(
            f"CHIRPS HTTP metadata request failed: {_safe_error_message(exc)}"
        ) from exc


def read_cell_center_window(
    source: str | Path,
    bounds: tuple[float, float, float, float] = MONITORING_EXTENT_BOUNDS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Read cells whose centers fall inside the exact closed rectangle.

    The raster must be an unrotated EPSG:4326 north-up grid.  Dataset-invalid,
    non-finite, and negative values are represented by a canonical float32 NaN.
    No resampling or boundary-area approximation is performed.
    """
    west, south, east, north = (float(value) for value in bounds)
    if not west < east or not south < north:
        raise RainfallArtifactError("monitoring rectangle bounds are invalid")
    source_label = str(source)
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MAX_RETRY="3",
        GDAL_HTTP_RETRY_DELAY="1",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".cog",
    ):
        with rasterio.open(source_label) as dataset:
            if dataset.count < 1:
                raise RainfallFetchError("CHIRPS source has no raster band")
            if dataset.crs is None or dataset.crs.to_epsg() != 4326:
                raise RainfallFetchError("CHIRPS source is not EPSG:4326")
            transform = dataset.transform
            if (
                abs(transform.b) > 1e-12
                or abs(transform.d) > 1e-12
                or transform.a <= 0
                or transform.e >= 0
            ):
                raise RainfallFetchError(
                    "CHIRPS source grid must be unrotated, north-up, and east-positive"
                )

            longitude_centers = transform.c + (
                np.arange(dataset.width, dtype=np.float64) + 0.5
            ) * transform.a
            latitude_centers = transform.f + (
                np.arange(dataset.height, dtype=np.float64) + 0.5
            ) * transform.e
            columns = np.flatnonzero(
                (longitude_centers >= west) & (longitude_centers <= east)
            )
            rows = np.flatnonzero(
                (latitude_centers >= south) & (latitude_centers <= north)
            )
            if rows.size == 0 or columns.size == 0:
                raise RainfallFetchError(
                    "no raster cell centers fall inside the accepted monitoring rectangle"
                )
            if not np.all(np.diff(rows) == 1) or not np.all(np.diff(columns) == 1):
                raise RainfallFetchError("selected CHIRPS window is not contiguous")

            window = Window(
                col_off=int(columns[0]),
                row_off=int(rows[0]),
                width=int(columns.size),
                height=int(rows.size),
            )
            band = dataset.read(1, window=window, masked=True)
            raw = np.asarray(band.astype(np.float64).filled(np.nan), dtype=np.float64)
            valid = (
                ~np.ma.getmaskarray(band)
                & np.isfinite(raw)
                & (raw >= 0.0)
            )
            values = np.full(raw.shape, np.float32(np.nan), dtype="<f4")
            values[valid] = raw[valid].astype("<f4")
            selected_latitudes = np.asarray(latitude_centers[rows], dtype="<f8")
            selected_longitudes = np.asarray(longitude_centers[columns], dtype="<f8")
            nodata = dataset.nodata
            if nodata is not None and not math.isfinite(float(nodata)):
                nodata = None
            grid = {
                "crs": "EPSG:4326",
                "source_width": dataset.width,
                "source_height": dataset.height,
                "source_transform": [
                    float(transform.a),
                    float(transform.b),
                    float(transform.c),
                    float(transform.d),
                    float(transform.e),
                    float(transform.f),
                ],
                "source_dtype": dataset.dtypes[0],
                "source_nodata": None if nodata is None else float(nodata),
                "selected_window": {
                    "column_offset": int(columns[0]),
                    "row_offset": int(rows[0]),
                    "width": int(columns.size),
                    "height": int(rows.size),
                },
            }
    return values, selected_latitudes, selected_longitudes, grid


def fetch_official_chirps_month(
    month: str,
    source_url: str,
    bounds: tuple[float, float, float, float],
    accessed_at: str,
    *,
    timeout_seconds: float = 60.0,
) -> FetchedRainfallWindow:
    """Read one official monthly COG window without persisting global bytes."""
    del accessed_at  # fixed access time is recorded by the caller, never inferred here
    if source_url != chirps_cog_url(month):
        raise RainfallArtifactError("source URL does not match the requested month")
    http = _http_metadata(source_url, timeout_seconds=timeout_seconds)
    if http["status_code"] is None or not 200 <= http["status_code"] < 300:
        raise RainfallFetchError("official CHIRPS COG did not return HTTP success", http_metadata=http)
    try:
        values, latitudes, longitudes, grid = read_cell_center_window(
            source_url, bounds
        )
    except Exception as exc:
        if isinstance(exc, RainfallFetchError):
            raise RainfallFetchError(str(exc), http_metadata=http) from exc
        raise RainfallFetchError(
            f"CHIRPS COG window read failed: {_safe_error_message(exc)}",
            http_metadata=http,
        ) from exc
    return FetchedRainfallWindow(
        values=values,
        latitude_centers=latitudes,
        longitude_centers=longitudes,
        source_grid=grid,
        http_metadata=http,
    )


def _regular_axis(values: np.ndarray, *, label: str) -> dict[str, Any]:
    axis = np.asarray(values, dtype=np.float64)
    if axis.ndim != 1 or axis.size == 0 or not np.all(np.isfinite(axis)):
        raise RainfallArtifactError(f"{label} centers must be a nonempty finite axis")
    step = 0.0 if axis.size == 1 else float(axis[1] - axis[0])
    if axis.size > 1 and not np.allclose(
        np.diff(axis), step, rtol=0.0, atol=1e-12
    ):
        raise RainfallArtifactError(f"{label} centers are not regularly spaced")
    return {
        "count": int(axis.size),
        "first": float(axis[0]),
        "last": float(axis[-1]),
        "step": step,
    }


def _axis_values(record: Mapping[str, Any]) -> np.ndarray:
    count = int(record["count"])
    return np.asarray(
        [float(record["first"]) + index * float(record["step"]) for index in range(count)],
        dtype=np.float64,
    )


def summarize_weighted_window(
    values: np.ndarray,
    latitude_centers: np.ndarray,
    longitude_centers: np.ndarray,
) -> dict[str, Any]:
    """Return deterministic finite-cell, cosine-latitude weighted statistics."""
    array = np.asarray(values, dtype=np.float64)
    latitudes = np.asarray(latitude_centers, dtype=np.float64)
    longitudes = np.asarray(longitude_centers, dtype=np.float64)
    if array.ndim != 2 or array.shape != (latitudes.size, longitudes.size):
        raise RainfallArtifactError("rainfall values do not match center-coordinate axes")
    if array.size == 0:
        raise RainfallArtifactError("rainfall window is empty")
    weights_by_row = np.cos(np.deg2rad(latitudes))
    if not np.all(np.isfinite(weights_by_row)) or np.any(weights_by_row <= 0):
        raise RainfallArtifactError("cosine-latitude weights must be finite and positive")
    weights = np.broadcast_to(weights_by_row[:, None], array.shape)
    valid = np.isfinite(array) & (array >= 0.0)
    total_weight = float(np.sum(weights, dtype=np.float64))
    finite_weight = float(np.sum(weights[valid], dtype=np.float64))
    finite_cells = int(np.count_nonzero(valid))
    mean = (
        float(np.sum(array[valid] * weights[valid], dtype=np.float64) / finite_weight)
        if finite_cells
        else None
    )
    return {
        "mean_mm": mean,
        "coverage_fraction": finite_weight / total_weight,
        "finite_cells": finite_cells,
        "total_cells": int(array.size),
        "finite_weight": finite_weight,
        "total_weight": total_weight,
    }


def _canonical_npy_bytes(values: np.ndarray) -> bytes:
    array = np.asarray(values, dtype="<f4", order="C").copy()
    invalid = ~np.isfinite(array) | (array < 0.0)
    array[invalid] = np.float32(np.nan)
    output = io.BytesIO()
    np.lib.format.write_array(
        output,
        array,
        version=(1, 0),
        allow_pickle=False,
    )
    return output.getvalue()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{id(content)}")
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, canonical_json_bytes(value) + b"\n")


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RainfallArtifactError(f"unsafe artifact path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RainfallArtifactError(f"artifact path escapes root: {relative}") from exc
    return resolved


def _window_relative_path(month: str) -> str:
    year, number = parse_month(month)
    return f"windows/chirps-v2.0.{year:04d}.{number:02d}.araripe.npy"


def _record_relative_path(month: str) -> str:
    return f"records/{month}.json"


def _monthly_value(
    record: Mapping[str, Any], *, output_dir: Path
) -> dict[str, Any]:
    """Create the compact, ordered month interface consumed downstream."""
    record_relative = _record_relative_path(str(record["month"]))
    record_path = output_dir / record_relative
    raw = record.get("raw_local_window")
    aggregation = record.get("aggregation", {})
    return {
        "month": record["month"],
        "status": record["status"],
        "precipitation_mm": aggregation.get("mean_mm"),
        "valid_coverage_fraction": aggregation.get("coverage_fraction"),
        "source_record": {
            "path": record_relative,
            "sha256": sha256_file(record_path),
        },
        "source_window": (
            {
                "path": raw["path"],
                "sha256": raw["sha256"],
            }
            if isinstance(raw, Mapping)
            else None
        ),
    }


def _expected_immutable_paths(plan: Mapping[str, Any]) -> set[str]:
    expected = {"plan.json", "build-environment.json"}
    for entry in plan["months"]:
        expected.add(_record_relative_path(entry["month"]))
    return expected


def _record_base(
    entry: Mapping[str, Any], *, plan_sha256: str, accessed_at: str
) -> dict[str, Any]:
    return {
        "schema_version": RAINFALL_SCHEMA_VERSION,
        "pipeline_version": RAINFALL_PIPELINE_VERSION,
        "plan_sha256": plan_sha256,
        "month": entry["month"],
        "roles": list(entry["roles"]),
        "source_url": entry["source_url"],
        "catalog_accessed_at": accessed_at,
    }


def _success_record(
    entry: Mapping[str, Any],
    *,
    plan_sha256: str,
    accessed_at: str,
    output_dir: Path,
    fetched: FetchedRainfallWindow,
) -> dict[str, Any]:
    values = np.asarray(fetched.values, dtype="<f4")
    latitudes = np.asarray(fetched.latitude_centers, dtype=np.float64)
    longitudes = np.asarray(fetched.longitude_centers, dtype=np.float64)
    aggregation = summarize_weighted_window(values, latitudes, longitudes)
    relative = _window_relative_path(entry["month"])
    path = output_dir / relative
    _atomic_write(path, _canonical_npy_bytes(values))
    status = "available" if aggregation["finite_cells"] > 0 else "insufficient"
    return {
        **_record_base(entry, plan_sha256=plan_sha256, accessed_at=accessed_at),
        "status": status,
        "reason": (
            None
            if status == "available"
            else "No finite non-negative rainfall cell is available in the exact rectangle."
        ),
        "http": sanitize_http_metadata(fetched.http_metadata),
        "retrieval": {
            "access_mode": "remote_cog_range_read",
            "source_url_unsigned": True,
            "upstream_full_asset_sha256": None,
            "local_window_sha256": sha256_file(path),
        },
        "source_grid": dict(fetched.source_grid),
        "center_grid": {
            "latitude": _regular_axis(latitudes, label="latitude"),
            "longitude": _regular_axis(longitudes, label="longitude"),
            "selection_rule": (
                "west <= longitude_cell_center <= east and south <= "
                "latitude_cell_center <= north"
            ),
        },
        "raw_local_window": {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "format": "NumPy NPY v1.0",
            "dtype": "<f4",
            "shape": list(values.shape),
            "invalid_value": "canonical_float32_nan",
        },
        "aggregation": aggregation,
    }


def _error_record(
    entry: Mapping[str, Any],
    *,
    plan_sha256: str,
    accessed_at: str,
    error: BaseException,
) -> dict[str, Any]:
    http = (
        error.http_metadata if isinstance(error, RainfallFetchError) else {}
    )
    return {
        **_record_base(entry, plan_sha256=plan_sha256, accessed_at=accessed_at),
        "status": "error",
        "reason": _safe_error_message(error),
        "http": sanitize_http_metadata(http),
        "retrieval": {
            "access_mode": "remote_cog_range_read_attempt",
            "source_url_unsigned": True,
            "upstream_full_asset_sha256": None,
            "local_window_sha256": None,
        },
        "source_grid": None,
        "center_grid": None,
        "raw_local_window": None,
        "aggregation": {
            "mean_mm": None,
            "coverage_fraction": None,
            "finite_cells": None,
            "total_cells": None,
            "finite_weight": None,
            "total_weight": None,
        },
    }


def _record_is_resumable(
    record: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    plan_sha256: str,
    accessed_at: str,
    output_dir: Path,
    retry_errors: bool,
) -> bool:
    base = _record_base(entry, plan_sha256=plan_sha256, accessed_at=accessed_at)
    if any(record.get(key) != value for key, value in base.items()):
        return False
    status = record.get("status")
    if status == "error":
        return (
            not retry_errors
            and bool(record.get("reason"))
            and record.get("reason") == _safe_error_message(record.get("reason"))
            and record.get("http")
            == sanitize_http_metadata(record.get("http", {}))
            and record.get("retrieval")
            == {
                "access_mode": "remote_cog_range_read_attempt",
                "source_url_unsigned": True,
                "upstream_full_asset_sha256": None,
                "local_window_sha256": None,
            }
            and record.get("source_grid") is None
            and record.get("center_grid") is None
            and record.get("raw_local_window") is None
            and record.get("aggregation")
            == {
                "mean_mm": None,
                "coverage_fraction": None,
                "finite_cells": None,
                "total_cells": None,
                "finite_weight": None,
                "total_weight": None,
            }
        )
    if status not in {"available", "insufficient"}:
        return False
    raw = record.get("raw_local_window")
    center = record.get("center_grid")
    if not isinstance(raw, Mapping) or not isinstance(center, Mapping):
        return False
    if raw.get("path") != _window_relative_path(entry["month"]):
        return False
    try:
        path = _safe_path(output_dir, str(raw["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != raw["bytes"]
            or sha256_file(path) != raw["sha256"]
        ):
            return False
        values = np.load(path, allow_pickle=False)
        if (
            values.dtype.str != "<f4"
            or list(values.shape) != raw["shape"]
            or path.read_bytes() != _canonical_npy_bytes(values)
            or raw
            != {
                "path": _window_relative_path(entry["month"]),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "format": "NumPy NPY v1.0",
                "dtype": "<f4",
                "shape": list(values.shape),
                "invalid_value": "canonical_float32_nan",
            }
        ):
            return False
        latitudes = _axis_values(center["latitude"])
        longitudes = _axis_values(center["longitude"])
        aggregation = summarize_weighted_window(values, latitudes, longitudes)
    except (KeyError, OSError, ValueError, TypeError, RainfallArtifactError):
        return False
    expected_status = "available" if aggregation["finite_cells"] > 0 else "insufficient"
    expected_reason = (
        None
        if expected_status == "available"
        else "No finite non-negative rainfall cell is available in the exact rectangle."
    )
    return (
        status == expected_status
        and record.get("reason") == expected_reason
        and record.get("http")
        == sanitize_http_metadata(record.get("http", {}))
        and record.get("retrieval")
        == {
            "access_mode": "remote_cog_range_read",
            "source_url_unsigned": True,
            "upstream_full_asset_sha256": None,
            "local_window_sha256": raw["sha256"],
        }
        and isinstance(record.get("source_grid"), Mapping)
        and center.get("selection_rule")
        == (
            "west <= longitude_cell_center <= east and south <= "
            "latitude_cell_center <= north"
        )
        and aggregation == record.get("aggregation")
    )


def _process_entry(
    entry: Mapping[str, Any],
    *,
    plan_sha256: str,
    accessed_at: str,
    output_dir: Path,
    fetch_month: FetchMonth,
) -> dict[str, Any]:
    expected_window = output_dir / _window_relative_path(entry["month"])
    try:
        fetched = fetch_month(
            entry["month"],
            entry["source_url"],
            MONITORING_EXTENT_BOUNDS,
            accessed_at,
        )
        record = _success_record(
            entry,
            plan_sha256=plan_sha256,
            accessed_at=accessed_at,
            output_dir=output_dir,
            fetched=fetched,
        )
    except Exception as exc:  # one failed month is retained, never substituted
        expected_window.unlink(missing_ok=True)
        record = _error_record(
            entry,
            plan_sha256=plan_sha256,
            accessed_at=accessed_at,
            error=exc,
        )
    _write_json(output_dir / _record_relative_path(entry["month"]), record)
    return record


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
    }


def _generator_source_inventory(repository_root: Path) -> list[dict[str, Any]]:
    paths = tuple(repository_root / relative for relative in _RAINFALL_GENERATOR_SOURCE_PATHS)
    if any(not path.is_file() for path in paths):
        raise RainfallArtifactError("rainfall generator source is missing")
    return [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def _validate_generator_source_inventory(value: Any) -> None:
    if (
        not isinstance(value, list)
        or [item.get("path") for item in value if isinstance(item, Mapping)]
        != list(_RAINFALL_GENERATOR_SOURCE_PATHS)
        or len(value) != len(_RAINFALL_GENERATOR_SOURCE_PATHS)
    ):
        raise RainfallArtifactError(
            "rainfall generator source inventory paths are incomplete or reordered"
        )
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"path", "bytes", "sha256"}
            or isinstance(item["bytes"], bool)
            or not isinstance(item["bytes"], int)
            or item["bytes"] < 1
            or not isinstance(item["sha256"], str)
            or _SHA256_RE.fullmatch(item["sha256"]) is None
        ):
            raise RainfallArtifactError(
                "rainfall generator source inventory record is invalid"
            )


def _build_environment_record(
    generator_inventory: Sequence[Mapping[str, Any]],
    runtime_versions: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": RAINFALL_SCHEMA_VERSION,
        "generator_source_inventory": [dict(item) for item in generator_inventory],
        "runtime_versions": dict(runtime_versions),
    }


def _build_plan(
    *, target_months: Sequence[str], generated_at: str, accessed_at: str
) -> dict[str, Any]:
    months = build_month_plan(target_months)
    return {
        "schema_version": RAINFALL_SCHEMA_VERSION,
        "pipeline_version": RAINFALL_PIPELINE_VERSION,
        "generated_at": validate_fixed_timestamp(generated_at, label="generated_at"),
        "catalog_accessed_at": validate_fixed_timestamp(
            accessed_at, label="catalog_accessed_at"
        ),
        "source": {
            "provider": CHIRPS_PROVIDER,
            "dataset": CHIRPS_DATASET,
            "dataset_version": "2.0",
            "source_kind": "official_direct_monthly_cog_not_stac",
            "official_cog_base_url": CHIRPS_COG_BASE_URL,
            "official_cog_pattern": CHIRPS_COG_PATTERN,
        },
        "reference_period": {
            "start_month": REFERENCE_START_MONTH,
            "end_month": REFERENCE_END_MONTH,
            "expected_month_count": REFERENCE_MONTH_COUNT,
        },
        "target_months": sorted({str(value) for value in target_months}),
        "monitoring_extent": {
            "extent_id": MONITORING_EXTENT_ID,
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
            "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
            "scope": "APA and surroundings",
        },
        "aggregation": {
            "version": "cell-center-cos-lat-v1",
            "cell_selection": (
                "closed accepted rectangle; select a source cell iff its EPSG:4326 "
                "center satisfies west <= x <= east and south <= y <= north"
            ),
            "validity": (
                "dataset-valid and finite monthly precipitation greater than or equal to zero"
            ),
            "weight": "cos(latitude_cell_center_radians)",
            "mean": "sum(value * weight over valid cells) / sum(weight over valid cells)",
            "coverage": "sum(weight over valid cells) / sum(weight over all selected cells)",
            "resampling": "none",
            "raw_window": (
                "NumPy NPY v1.0 little-endian float32; invalid cells use canonical NaN"
            ),
        },
        "months": months,
        "local_only": True,
        "raw_redistribution_allowed": False,
    }


@contextlib.contextmanager
def _exclusive_build_lock(output_dir: Path):
    lock_path = output_dir / ".phase2a4-rainfall.lock"
    output_dir.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RainfallArtifactError(
                f"another rainfall-reference build holds {lock_path}"
            ) from exc
        acquired = True
        handle.seek(0)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
        yield
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        # Never unlink a lock inode: unlink-after-unlock permits a new process
        # to lock the old inode while a third process creates and locks a new
        # path.  This empty operational file is excluded from artifact hashes.


def _clean_interrupted_temporaries(output_dir: Path) -> None:
    for directory in (output_dir, output_dir / "records", output_dir / "windows"):
        if not directory.is_dir():
            continue
        for path in directory.glob(".*.tmp-*"):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)


def build_rainfall_reference_artifact(
    *,
    output_dir: Path,
    target_months: Sequence[str],
    generated_at: str,
    accessed_at: str,
    workers: int = 4,
    fetch_month: FetchMonth = fetch_official_chirps_month,
    retry_errors: bool = False,
    generation_command: Sequence[str] | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Build or safely resume the complete local/private monthly artifact."""
    output_dir = Path(output_dir).resolve()
    if workers < 1 or workers > 32:
        raise RainfallArtifactError("workers must be between 1 and 32")
    repository_root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    plan = _build_plan(
        target_months=target_months,
        generated_at=generated_at,
        accessed_at=accessed_at,
    )
    plan_sha256 = canonical_sha256(plan)
    generator_inventory = _generator_source_inventory(repository_root)
    runtime_versions = _runtime_versions()

    with _exclusive_build_lock(output_dir):
        _clean_interrupted_temporaries(output_dir)
        plan_path = output_dir / "plan.json"
        if plan_path.is_file():
            try:
                recorded_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RainfallArtifactError(f"cannot resume invalid plan.json: {exc}") from exc
            if recorded_plan != plan:
                raise RainfallArtifactError(
                    "existing output plan differs; use a new output directory"
                )
        else:
            _write_json(plan_path, plan)

        manifest_path = output_dir / "manifest.json"
        checksums_path = output_dir / "CHECKSUMS.sha256"
        if manifest_path.is_file() and checksums_path.is_file():
            try:
                recorded_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise RainfallArtifactError(
                    f"cannot resume invalid manifest.json: {exc}"
                ) from exc
            if recorded_manifest.get("plan_sha256") != plan_sha256:
                raise RainfallArtifactError("completed artifact has a different build plan")
            generation_environment_unchanged = (
                recorded_manifest.get("generator_source_inventory")
                == generator_inventory
                and recorded_manifest.get("runtime_versions") == runtime_versions
            )
            if not generation_environment_unchanged:
                raise RainfallArtifactError(
                    "completed artifact source/runtime provenance differs; "
                    "build in a new output directory and re-fetch every month"
                )
            manifest = validate_rainfall_reference_artifact(output_dir)
            retained_errors = manifest.get("status_counts", {}).get("error", 0)
            if not retry_errors or retained_errors == 0:
                return manifest
            # An explicit error retry under the exact same source/runtime
            # inventory invalidates only the two derived index files. All
            # retained successful records remain bound to that same generator.
            manifest_path.unlink()
            checksums_path.unlink()

        environment_path = output_dir / "build-environment.json"
        environment_record = _build_environment_record(
            generator_inventory, runtime_versions
        )
        if environment_path.is_file():
            try:
                recorded_environment = json.loads(
                    environment_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise RainfallArtifactError(
                    f"cannot resume invalid build-environment.json: {exc}"
                ) from exc
            if recorded_environment != environment_record:
                raise RainfallArtifactError(
                    "rainfall build source/runtime changed after retrieval began; "
                    "use a new output directory and re-fetch every month"
                )
        else:
            prior_month_material = any(
                path.is_file()
                for directory in (output_dir / "records", output_dir / "windows")
                if directory.is_dir()
                for path in directory.rglob("*")
            )
            if prior_month_material:
                raise RainfallArtifactError(
                    "rainfall build environment provenance is missing for retained "
                    "month material; use a new output directory"
                )
            _write_json(environment_path, environment_record)

        records: dict[str, dict[str, Any]] = {}
        pending: list[dict[str, Any]] = []
        for entry in plan["months"]:
            path = output_dir / _record_relative_path(entry["month"])
            record: dict[str, Any] | None = None
            if path.is_file():
                try:
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    candidate = None
                if candidate is not None and _record_is_resumable(
                    candidate,
                    entry,
                    plan_sha256=plan_sha256,
                    accessed_at=accessed_at,
                    output_dir=output_dir,
                    retry_errors=retry_errors,
                ):
                    record = candidate
            if record is None:
                pending.append(entry)
            else:
                records[entry["month"]] = record

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_entry,
                    entry,
                    plan_sha256=plan_sha256,
                    accessed_at=accessed_at,
                    output_dir=output_dir,
                    fetch_month=fetch_month,
                ): entry["month"]
                for entry in pending
            }
            for future in as_completed(futures):
                month = futures[future]
                records[month] = future.result()

        ordered_records = [records[entry["month"]] for entry in plan["months"]]
        status_counts = dict(
            sorted(Counter(record["status"] for record in ordered_records).items())
        )
        reference_records = [
            record for record in ordered_records if "reference" in record["roles"]
        ]
        target_records = [
            record for record in ordered_records if "target" in record["roles"]
        ]
        all_available = all(record["status"] == "available" for record in ordered_records)

        expected_immutable_paths = _expected_immutable_paths(plan)
        expected_immutable_paths.update(
            record["raw_local_window"]["path"]
            for record in ordered_records
            if isinstance(record.get("raw_local_window"), Mapping)
        )
        actual_immutable_paths = {
            path.relative_to(output_dir).as_posix()
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.name
            not in {"manifest.json", "CHECKSUMS.sha256", ".phase2a4-rainfall.lock"}
            and ".tmp-" not in path.name
        }
        if actual_immutable_paths != expected_immutable_paths:
            extras = sorted(actual_immutable_paths - expected_immutable_paths)
            missing = sorted(expected_immutable_paths - actual_immutable_paths)
            raise RainfallArtifactError(
                "rainfall artifact contains unexpected or missing immutable files: "
                f"extras={extras}, missing={missing}"
            )

        inventory_paths = sorted(
            path
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.name
            not in {"manifest.json", "CHECKSUMS.sha256", ".phase2a4-rainfall.lock"}
            and ".tmp-" not in path.name
        )
        inventory = [_artifact(path, output_dir) for path in inventory_paths]
        monthly_values = [
            _monthly_value(record, output_dir=output_dir)
            for record in ordered_records
        ]
        if (
            _generator_source_inventory(repository_root) != generator_inventory
            or _runtime_versions() != runtime_versions
        ):
            raise RainfallArtifactError(
                "rainfall generator source or runtime changed during construction"
            )
        command = list(generation_command or [])
        artifact_id = "p2a4-rainfall-reference-v1-" + identity_sha256(
            RAINFALL_PIPELINE_VERSION,
            plan_sha256,
            canonical_sha256(ordered_records),
            canonical_sha256(inventory),
            canonical_sha256(generator_inventory),
            canonical_sha256(runtime_versions),
            canonical_sha256(command),
        )
        manifest = {
            "schema_version": RAINFALL_SCHEMA_VERSION,
            "artifact_id": artifact_id,
            "artifact_type": RAINFALL_ARTIFACT_TYPE,
            "scientific_status": "provisional_candidate_input_only",
            "overall_status": (
                "complete" if all_available else "incomplete_retained_source_evidence"
            ),
            "generated_at": generated_at,
            "catalog_accessed_at": accessed_at,
            "plan_sha256": plan_sha256,
            "generation_command": command,
            "runtime_versions": runtime_versions,
            "generator_source_inventory": generator_inventory,
            "source": {
                **plan["source"],
                "source_url_policy": "one fixed official public COG URL per month",
                "credentials_used": False,
                "signed_urls_persisted": False,
                "full_upstream_cog_checksum_available": False,
            },
            "monitoring_extent": plan["monitoring_extent"],
            "aggregation": plan["aggregation"],
            "reference_period": {
                **plan["reference_period"],
                "available_month_count": sum(
                    record["status"] == "available" for record in reference_records
                ),
                "status": (
                    "complete"
                    if all(record["status"] == "available" for record in reference_records)
                    else "incomplete"
                ),
            },
            "target_months": plan["target_months"],
            "target_status": (
                "complete"
                if all(record["status"] == "available" for record in target_records)
                else "incomplete"
            ),
            "month_count": len(ordered_records),
            "status_counts": status_counts,
            "monthly_values": monthly_values,
            "months": ordered_records,
            "claims": {
                "rainfall_reference_only": True,
                "drought_status_computed": False,
                "drought_adjustment_activated": False,
                "method_selected": False,
                "scientific_accuracy_claim": False,
                "qualified_human_labels_present": False,
                "raw_detection_modified": False,
            },
            "local_only": True,
            "raw_redistribution_allowed": False,
            "generation_limitations": [
                "A local window checksum binds retained NumPy bytes, not the complete upstream COG object.",
                "HTTP ETag and Last-Modified values are transport metadata, not scientific content checksums.",
                "Any source failure remains an error for its requested month; no neighboring or climatological month is substituted.",
                "This artifact does not calculate SPI or authorize drought adjustment.",
                "Raw redistribution remains disabled pending source-specific licensing review.",
            ],
            "artifact_inventory_rule": (
                "artifact_inventory contains every immutable artifact file except "
                "manifest.json and CHECKSUMS.sha256; CHECKSUMS.sha256 includes the "
                "manifest and every inventoried file and excludes itself; the empty "
                "operational build-lock file is not an artifact and is excluded from both"
            ),
            "artifact_inventory": inventory,
            "checksum_file": "CHECKSUMS.sha256",
        }
        _write_json(manifest_path, manifest)
        checksum_paths = sorted(
            path
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.name not in {"CHECKSUMS.sha256", ".phase2a4-rainfall.lock"}
            and ".tmp-" not in path.name
        )
        checksum_lines = [
            f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}"
            for path in checksum_paths
        ]
        _atomic_write(
            checksums_path,
            ("\n".join(checksum_lines) + "\n").encode("utf-8"),
        )
        return validate_rainfall_reference_artifact(output_dir)


def validate_rainfall_reference_artifact(output_dir: Path) -> dict[str, Any]:
    """Deeply validate checksums, monthly records, claims, and artifact ID."""
    root = Path(output_dir).resolve()
    if not root.is_dir():
        raise RainfallArtifactError(f"artifact directory does not exist: {root}")
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RainfallArtifactError(f"cannot parse manifest.json: {exc}") from exc
    if manifest.get("schema_version") != RAINFALL_SCHEMA_VERSION:
        raise RainfallArtifactError("rainfall artifact schema version mismatch")
    if manifest.get("artifact_type") != RAINFALL_ARTIFACT_TYPE:
        raise RainfallArtifactError("rainfall artifact type mismatch")
    _validate_generator_source_inventory(manifest.get("generator_source_inventory"))
    try:
        environment_record = json.loads(
            (root / "build-environment.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RainfallArtifactError(
            f"cannot parse build-environment.json: {exc}"
        ) from exc
    if environment_record != _build_environment_record(
        manifest.get("generator_source_inventory", []),
        manifest.get("runtime_versions", {}),
    ):
        raise RainfallArtifactError(
            "rainfall build environment does not bind manifest source/runtime"
        )

    inventory = manifest.get("artifact_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise RainfallArtifactError("artifact inventory is missing")
    inventory_paths = [item["path"] for item in inventory]
    if len(inventory_paths) != len(set(inventory_paths)):
        raise RainfallArtifactError("artifact inventory contains duplicate paths")
    actual_files = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.name != ".phase2a4-rainfall.lock"
    }
    expected_files = set(inventory_paths) | {"manifest.json", "CHECKSUMS.sha256"}
    if set(actual_files) != expected_files:
        raise RainfallArtifactError("artifact file inventory does not reconcile")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RainfallArtifactError(f"symlink is forbidden: {path}")
    for item in inventory:
        path = _safe_path(root, item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or sha256_file(path) != item["sha256"]
        ):
            raise RainfallArtifactError(f"artifact checksum mismatch: {item['path']}")

    recorded: dict[str, str] = {}
    try:
        checksum_lines = (root / "CHECKSUMS.sha256").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError as exc:
        raise RainfallArtifactError(f"cannot read CHECKSUMS.sha256: {exc}") from exc
    for number, line in enumerate(checksum_lines, start=1):
        match = _CHECKSUM_LINE.fullmatch(line)
        if match is None or match.group("path") in recorded:
            raise RainfallArtifactError(f"invalid checksum line {number}")
        recorded[match.group("path")] = match.group("sha")
    checksum_expected = expected_files - {"CHECKSUMS.sha256"}
    if set(recorded) != checksum_expected:
        raise RainfallArtifactError("checksum-file inventory does not reconcile")
    for relative, digest in recorded.items():
        if sha256_file(_safe_path(root, relative)) != digest:
            raise RainfallArtifactError(f"checksum-file mismatch: {relative}")

    try:
        plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RainfallArtifactError(f"cannot parse plan.json: {exc}") from exc
    try:
        expected_plan = _build_plan(
            target_months=plan["target_months"],
            generated_at=plan["generated_at"],
            accessed_at=plan["catalog_accessed_at"],
        )
    except (KeyError, TypeError, RainfallArtifactError) as exc:
        raise RainfallArtifactError(f"invalid rainfall build plan: {exc}") from exc
    if plan != expected_plan:
        raise RainfallArtifactError(
            "plan does not preserve the fixed source, reference, extent, or aggregation"
        )
    if canonical_sha256(plan) != manifest.get("plan_sha256"):
        raise RainfallArtifactError("plan SHA-256 mismatch")
    expected_source = {
        **plan["source"],
        "source_url_policy": "one fixed official public COG URL per month",
        "credentials_used": False,
        "signed_urls_persisted": False,
        "full_upstream_cog_checksum_available": False,
    }
    if (
        manifest.get("generated_at") != plan["generated_at"]
        or manifest.get("catalog_accessed_at") != plan["catalog_accessed_at"]
        or manifest.get("source") != expected_source
        or manifest.get("monitoring_extent") != plan["monitoring_extent"]
        or manifest.get("aggregation") != plan["aggregation"]
        or manifest.get("target_months") != plan["target_months"]
    ):
        raise RainfallArtifactError("manifest does not reconcile with the fixed plan")
    expected_months = [entry["month"] for entry in plan["months"]]
    months = manifest.get("months")
    if (
        not isinstance(months, list)
        or [record.get("month") for record in months] != expected_months
        or len(months) != manifest.get("month_count")
    ):
        raise RainfallArtifactError("manifest month records do not match the plan")
    for entry, manifest_record in zip(plan["months"], months):
        record_path = root / _record_relative_path(entry["month"])
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RainfallArtifactError(
                f"cannot parse month record {entry['month']}: {exc}"
            ) from exc
        if record != manifest_record or not _record_is_resumable(
            record,
            entry,
            plan_sha256=manifest["plan_sha256"],
            accessed_at=manifest["catalog_accessed_at"],
            output_dir=root,
            retry_errors=False,
        ):
            raise RainfallArtifactError(
                f"month record does not reconcile: {entry['month']}"
            )

    expected_monthly_values = [
        _monthly_value(record, output_dir=root) for record in months
    ]
    if manifest.get("monthly_values") != expected_monthly_values:
        raise RainfallArtifactError(
            "top-level monthly rainfall values do not reconcile with source records"
        )

    status_counts = dict(sorted(Counter(record["status"] for record in months).items()))
    reference_records = [record for record in months if "reference" in record["roles"]]
    target_records = [record for record in months if "target" in record["roles"]]
    expected_reference = {
        **plan["reference_period"],
        "available_month_count": sum(
            record["status"] == "available" for record in reference_records
        ),
        "status": (
            "complete"
            if all(record["status"] == "available" for record in reference_records)
            else "incomplete"
        ),
    }
    expected_target_status = (
        "complete"
        if all(record["status"] == "available" for record in target_records)
        else "incomplete"
    )
    all_available = all(record["status"] == "available" for record in months)
    if (
        manifest.get("status_counts") != status_counts
        or manifest.get("reference_period") != expected_reference
        or manifest.get("target_status") != expected_target_status
        or manifest.get("overall_status")
        != (
            "complete" if all_available else "incomplete_retained_source_evidence"
        )
        or manifest.get("scientific_status") != "provisional_candidate_input_only"
    ):
        raise RainfallArtifactError("manifest status summary does not reconcile")

    claims = manifest.get("claims", {})
    if (
        claims.get("rainfall_reference_only") is not True
        or any(
            claims.get(name) is not False
            for name in (
                "drought_status_computed",
                "drought_adjustment_activated",
                "method_selected",
                "scientific_accuracy_claim",
                "qualified_human_labels_present",
                "raw_detection_modified",
            )
        )
    ):
        raise RainfallArtifactError("rainfall artifact exceeds its claim boundary")
    if manifest.get("local_only") is not True or manifest.get(
        "raw_redistribution_allowed"
    ) is not False:
        raise RainfallArtifactError("rainfall artifact violates local-only policy")

    expected_id = "p2a4-rainfall-reference-v1-" + identity_sha256(
        RAINFALL_PIPELINE_VERSION,
        manifest["plan_sha256"],
        canonical_sha256(months),
        canonical_sha256(inventory),
        canonical_sha256(manifest["generator_source_inventory"]),
        canonical_sha256(manifest["runtime_versions"]),
        canonical_sha256(manifest["generation_command"]),
    )
    if manifest.get("artifact_id") != expected_id:
        raise RainfallArtifactError("artifact ID does not bind generation inputs")
    return manifest


def load_rainfall_monthly_values(output_dir: Path) -> dict[str, Any]:
    """Load the validated month-to-rainfall interface for method evidence.

    ``manifest_sha256`` is the checksum recorded for ``manifest.json`` in the
    artifact's checksum file.  Downstream evidence should bind that digest and
    the artifact ID; it must retain non-available month entries rather than
    silently dropping or replacing them.
    """
    root = Path(output_dir).resolve()
    manifest = validate_rainfall_reference_artifact(root)
    values = manifest["monthly_values"]
    return {
        "artifact_id": manifest["artifact_id"],
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "plan_sha256": manifest["plan_sha256"],
        "monthly_values": {entry["month"]: entry for entry in values},
        "precipitation_mm_by_month": {
            entry["month"]: entry["precipitation_mm"] for entry in values
        },
    }


__all__ = [
    "CHIRPS_COG_BASE_URL",
    "FetchedRainfallWindow",
    "RainfallArtifactError",
    "RainfallFetchError",
    "build_month_plan",
    "build_rainfall_reference_artifact",
    "chirps_cog_url",
    "fetch_official_chirps_month",
    "iter_reference_months",
    "load_rainfall_monthly_values",
    "read_cell_center_window",
    "summarize_weighted_window",
    "validate_rainfall_reference_artifact",
]
