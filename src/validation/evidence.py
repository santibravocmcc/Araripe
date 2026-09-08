"""Read-only, provenance-recorded evidence retrieval for Phase 2A.3 cases.

This module builds validation derivatives only.  It does not reproduce the
operational detector, activate a cloud/composition method, or create canonical
acquisition/observation identities.
"""

from __future__ import annotations

import copy
import datetime as dt
import html
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import planetary_computer
import rasterio
from PIL import Image, ImageDraw
from pyproj import Transformer
from pystac import Item
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from shapely.geometry import shape
from shapely.ops import transform as transform_geometry

from src.detection.identity import canonical_sha256
from src.detection.baseline_manifest import sha256_file
from src.validation.package import write_canonical_json


ELEMENT84_STAC = "https://earth-search.aws.element84.com/v1"
PLANETARY_COMPUTER_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SENTINEL_COLLECTION = "sentinel-2-l2a"
LANDSAT_COLLECTION = "landsat-c2-l2"
SENTINEL_CLEAR_SCL = {2, 4, 5, 6, 7, 11}
MAPBIOMAS_10M_SHA256 = "2ba20d400976020b4e7472a37de04fe1755c6f23631008b39da388001a034f59"
MAPBIOMAS_30M_SHA256 = "1be96442929c98cdbe0126d5c83d65a8142b61642ec14fb0ad1dfdfa3bf68d6c"
EVIDENCE_PIPELINE_VERSION = "phase2a3-evidence-pipeline-v1"
_URL_WITH_QUERY = re.compile(r"(https?://[^?\s'\"<>]+)\?[^\s'\"<>]+")
_URL_WITH_USERINFO = re.compile(r"(https?://)[^/@\s]+@")


@dataclass(frozen=True)
class EvidenceConfig:
    cache_dir: Path
    catalog_accessed_at: str
    evidence_cutoff_date: dt.date
    before_days: int = 60
    after_days: int = 45
    max_scene_cloud_percent: float = 80.0
    minimum_local_clear_fraction: float = 0.70
    minimum_local_coverage_fraction: float = 0.95
    local_padding_m: float = 350.0
    context_half_width_m: float = 5000.0
    chip_pixels: int = 640
    context_pixels: int = 768
    candidate_limit: int = 8
    mapbiomas_10m_path: Path | None = None
    mapbiomas_30m_path: Path | None = None


class EvidenceRetrievalError(RuntimeError):
    """Raised for one evidence retrieval operation; callers record it in-case."""


def evidence_config_record(config: EvidenceConfig) -> dict[str, Any]:
    """Return the non-secret settings that determine evidence/cache bytes."""
    def package_version(name: str) -> str:
        try:
            return version(name)
        except PackageNotFoundError:
            return "not-installed"

    return {
        "pipeline_version": EVIDENCE_PIPELINE_VERSION,
        "implementation_sha256": sha256_file(Path(__file__)),
        "runtime_versions": {
            "numpy": np.__version__,
            "pillow": package_version("pillow"),
            "planetary-computer": package_version("planetary-computer"),
            "pyproj": package_version("pyproj"),
            "pystac": package_version("pystac"),
            "pystac-client": package_version("pystac-client"),
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
        },
        "catalogs": {
            "sentinel2": ELEMENT84_STAC,
            "landsat": PLANETARY_COMPUTER_STAC,
        },
        "collections": {
            "sentinel2": SENTINEL_COLLECTION,
            "landsat": LANDSAT_COLLECTION,
        },
        "catalog_accessed_at": config.catalog_accessed_at,
        "evidence_cutoff_date": config.evidence_cutoff_date.isoformat(),
        "before_days": config.before_days,
        "after_days": config.after_days,
        "max_scene_cloud_percent": config.max_scene_cloud_percent,
        "minimum_local_clear_fraction": config.minimum_local_clear_fraction,
        "minimum_local_coverage_fraction": config.minimum_local_coverage_fraction,
        "local_padding_m": config.local_padding_m,
        "context_half_width_m": config.context_half_width_m,
        "chip_pixels": config.chip_pixels,
        "context_pixels": config.context_pixels,
        "candidate_limit": config.candidate_limit,
        "mapbiomas_10m": {
            "supplied": config.mapbiomas_10m_path is not None,
            "expected_sha256": MAPBIOMAS_10M_SHA256 if config.mapbiomas_10m_path else None,
        },
        "mapbiomas_30m": {
            "supplied": config.mapbiomas_30m_path is not None,
            "expected_sha256": MAPBIOMAS_30M_SHA256 if config.mapbiomas_30m_path else None,
        },
        "signed_urls_persisted": False,
        "legacy_sqlite_used": False,
    }


def _safe_error_message(error: BaseException | str, limit: int = 600) -> str:
    """Remove query tokens/userinfo before an upstream error enters artifacts."""
    value = str(error).replace("\r", " ").replace("\n", " ")
    value = _URL_WITH_QUERY.sub(r"\1?[query-redacted]", value)
    value = _URL_WITH_USERINFO.sub(r"\1[userinfo-redacted]@", value)
    return value[:limit]


def _unsigned_url(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _item_datetime(item: Item) -> dt.datetime:
    value = item.datetime or item.common_metadata.start_datetime
    if value is None:
        raise EvidenceRetrievalError(f"STAC item {item.id} has no datetime")
    return value.astimezone(dt.timezone.utc)


def _item_record(item: Item, *, sensor: str) -> dict[str, Any]:
    item_json = item.to_dict()
    return {
        "catalog": "Element84 Earth Search" if sensor == "sentinel2" else "Microsoft Planetary Computer",
        "collection": item.collection_id,
        "item_id": item.id,
        "observed_at": _item_datetime(item).isoformat().replace("+00:00", "Z"),
        "self_link": _unsigned_url(item.get_self_href() or ""),
        "item_metadata_sha256": canonical_sha256(item_json),
        "scene_cloud_percent": item.properties.get("eo:cloud_cover"),
        "platform": item.properties.get("platform"),
        "signing_required": sensor == "landsat",
    }


def _signed_copy(item: Item, sensor: str) -> Item:
    cloned = item.clone()
    if sensor == "landsat":
        return planetary_computer.sign(cloned)
    return cloned


def _search_items(
    *,
    sensor: str,
    longitude: float,
    latitude: float,
    start: dt.datetime,
    end: dt.datetime,
    max_cloud: float,
) -> list[Item]:
    url = ELEMENT84_STAC if sensor == "sentinel2" else PLANETARY_COMPUTER_STAC
    collection = SENTINEL_COLLECTION if sensor == "sentinel2" else LANDSAT_COLLECTION
    client = Client.open(url)
    search = client.search(
        collections=[collection],
        intersects={"type": "Point", "coordinates": [longitude, latitude]},
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        max_items=50,
    )
    return sorted(search.items(), key=lambda item: (_item_datetime(item), item.id))


def _point_window(
    dataset: rasterio.io.DatasetReader,
    longitude: float,
    latitude: float,
    half_width_m: float,
):
    transformer = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)
    x, y = transformer.transform(longitude, latitude)
    return from_bounds(
        x - half_width_m,
        y - half_width_m,
        x + half_width_m,
        y + half_width_m,
        dataset.transform,
    )


def _local_qa_metrics(
    item: Item,
    *,
    sensor: str,
    longitude: float,
    latitude: float,
    half_width_m: float = 500.0,
) -> tuple[float, float]:
    signed = _signed_copy(item, sensor)
    asset_key = "scl" if sensor == "sentinel2" else "qa_pixel"
    if asset_key not in signed.assets:
        return 0.0, 0.0
    href = signed.assets[asset_key].href
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MAX_RETRY="3",
        GDAL_HTTP_RETRY_DELAY="1",
    ):
        with rasterio.open(href) as dataset:
            window = _point_window(
                dataset, longitude, latitude, half_width_m
            )
            values = dataset.read(
                1,
                window=window,
                out_shape=(96, 96),
                boundless=True,
                masked=True,
                resampling=Resampling.nearest,
            )
    valid = ~np.ma.getmaskarray(values)
    if not np.any(valid):
        return 0.0, 0.0
    coverage_fraction = float(np.count_nonzero(valid) / valid.size)
    raw = np.asarray(values.filled(0), dtype=np.uint32)
    if sensor == "sentinel2":
        clear = np.isin(raw, list(SENTINEL_CLEAR_SCL))
    else:
        # Landsat QA_PIXEL: reject dilated cloud, cirrus, cloud, shadow, snow.
        rejected = (
            (raw & (1 << 1))
            | (raw & (1 << 2))
            | (raw & (1 << 3))
            | (raw & (1 << 4))
            | (raw & (1 << 5))
        )
        clear = rejected == 0
    clear_fraction = float(
        np.count_nonzero(clear & valid) / np.count_nonzero(valid)
    )
    return clear_fraction, coverage_fraction


def _select_item(
    items: Iterable[Item],
    *,
    sensor: str,
    target: dt.datetime,
    direction: str,
    longitude: float,
    latitude: float,
    config: EvidenceConfig,
) -> tuple[Item, float, float, list[dict[str, Any]]]:
    materialized = list(items)
    if direction == "before":
        materialized = [item for item in materialized if _item_datetime(item) < target]
        materialized.sort(
            key=lambda item: (target - _item_datetime(item), item.id)
        )
    else:
        materialized = [item for item in materialized if _item_datetime(item) >= target]
        materialized.sort(
            key=lambda item: (_item_datetime(item) - target, item.id)
        )
    if not materialized:
        raise EvidenceRetrievalError(f"no {sensor} {direction} candidate")

    inspected: list[tuple[Item, float, float]] = []
    audit: list[dict[str, Any]] = []
    for item in materialized[: config.candidate_limit]:
        try:
            clear_fraction, coverage_fraction = _local_qa_metrics(
                item,
                sensor=sensor,
                longitude=longitude,
                latitude=latitude,
            )
        except Exception as exc:
            audit.append(
                {
                    "item_id": item.id,
                    "local_qa_status": "error",
                    "reason": _safe_error_message(exc, limit=300),
                }
            )
            continue
        inspected.append((item, clear_fraction, coverage_fraction))
        usable = (
            clear_fraction >= config.minimum_local_clear_fraction
            and coverage_fraction >= config.minimum_local_coverage_fraction
        )
        audit.append(
            {
                "item_id": item.id,
                "observed_at": _item_datetime(item).isoformat(),
                "scene_cloud_percent": item.properties.get("eo:cloud_cover"),
                "local_clear_fraction": clear_fraction,
                "local_coverage_fraction": coverage_fraction,
                "local_qa_status": "usable" if usable else "below_threshold",
            }
        )
        if usable:
            return item, clear_fraction, coverage_fraction, audit
    if not inspected:
        raise EvidenceRetrievalError(
            f"all {sensor} {direction} candidates failed local QA reads"
        )
    # Keep the sample and expose an insufficient best-available panel rather
    # than silently replacing the case or hiding the evidence gap.
    item, clear_fraction, coverage_fraction = max(
        inspected,
        key=lambda pair: (
            min(
                pair[1] / config.minimum_local_clear_fraction,
                pair[2] / config.minimum_local_coverage_fraction,
            ),
            pair[1],
            pair[2],
            -abs((_item_datetime(pair[0]) - target).total_seconds()),
            pair[0].id,
        ),
    )
    return item, clear_fraction, coverage_fraction, audit


def _bounds_for_geometry(
    dataset: rasterio.io.DatasetReader,
    geometry_wgs84,
    *,
    padding_m: float,
    context_half_width_m: float | None = None,
) -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)
    projected = transform_geometry(transformer.transform, geometry_wgs84)
    if context_half_width_m is not None:
        point = projected.representative_point()
        return (
            point.x - context_half_width_m,
            point.y - context_half_width_m,
            point.x + context_half_width_m,
            point.y + context_half_width_m,
        )
    west, south, east, north = projected.bounds
    return (
        west - padding_m,
        south - padding_m,
        east + padding_m,
        north + padding_m,
    )


def _draw_geometry(
    image: Image.Image,
    geometry_wgs84,
    *,
    dataset_crs,
    bounds: tuple[float, float, float, float],
) -> None:
    transformer = Transformer.from_crs("EPSG:4326", dataset_crs, always_xy=True)
    projected = transform_geometry(transformer.transform, geometry_wgs84)
    west, south, east, north = bounds

    def pixel(position):
        x, y = position[:2]
        return (
            int(round((x - west) / (east - west) * (image.width - 1))),
            int(round((north - y) / (north - south) * (image.height - 1))),
        )

    polygons = [projected] if projected.geom_type == "Polygon" else list(projected.geoms)
    draw = ImageDraw.Draw(image)
    for polygon in polygons:
        draw.line([pixel(value) for value in polygon.exterior.coords], fill=(255, 238, 0), width=4, joint="curve")
        for ring in polygon.interiors:
            draw.line([pixel(value) for value in ring.coords], fill=(255, 238, 0), width=2)


def _save_png(array: np.ndarray, path: Path, geometry_wgs84, dataset_crs, bounds) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(array.astype(np.uint8), mode="RGB")
    _draw_geometry(
        image,
        geometry_wgs84,
        dataset_crs=dataset_crs,
        bounds=bounds,
    )
    image.save(path, format="PNG", compress_level=9, optimize=False)


def _render_sentinel(
    item: Item,
    *,
    geometry_wgs84,
    output_path: Path,
    pixels: int,
    padding_m: float,
    context_half_width_m: float | None = None,
) -> dict[str, Any]:
    signed = _signed_copy(item, "sentinel2")
    asset = signed.assets.get("visual")
    if asset is None:
        raise EvidenceRetrievalError(f"Sentinel item {item.id} lacks visual asset")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
        with rasterio.open(asset.href) as dataset:
            bounds = _bounds_for_geometry(
                dataset,
                geometry_wgs84,
                padding_m=padding_m,
                context_half_width_m=context_half_width_m,
            )
            window = from_bounds(*bounds, transform=dataset.transform)
            values = dataset.read(
                [1, 2, 3],
                window=window,
                out_shape=(3, pixels, pixels),
                boundless=True,
                masked=True,
                resampling=Resampling.bilinear,
            )
            crs = dataset.crs
    mask = np.ma.getmaskarray(values)
    valid = ~np.any(mask, axis=0)
    coverage_fraction = float(np.count_nonzero(valid) / valid.size)
    rgb = np.moveaxis(values.filled(0), 0, -1)
    _save_png(rgb, output_path, geometry_wgs84, crs, bounds)
    return {
        "asset_key": "visual",
        "asset_href": _unsigned_url(item.assets["visual"].href),
        "render": "provider_TCI_uint8_no_dynamic_stretch",
        "output_pixels": [pixels, pixels],
        "footprint_bounds_source_crs": list(bounds),
        "source_crs": str(crs),
        "coverage_fraction": coverage_fraction,
    }


def _band_scale_offset(item: Item, asset_key: str) -> tuple[float, float]:
    bands = item.assets[asset_key].extra_fields.get("raster:bands") or []
    record = bands[0] if bands else {}
    return float(record.get("scale", 1.0)), float(record.get("offset", 0.0))


def _read_landsat_rgb(
    item: Item,
    *,
    geometry_wgs84,
    pixels: int,
    padding_m: float,
) -> tuple[np.ndarray, Any, tuple[float, float, float, float], dict[str, Any]]:
    signed = _signed_copy(item, "landsat")
    band_keys = ("red", "green", "blue")
    values = []
    valid_masks = []
    common_bounds = None
    common_crs = None
    hrefs = {}
    for band_key in band_keys:
        if band_key not in signed.assets:
            raise EvidenceRetrievalError(f"Landsat item {item.id} lacks {band_key}")
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
            with rasterio.open(signed.assets[band_key].href) as dataset:
                bounds = _bounds_for_geometry(
                    dataset, geometry_wgs84, padding_m=padding_m
                )
                window = from_bounds(*bounds, transform=dataset.transform)
                band = dataset.read(
                    1,
                    window=window,
                    out_shape=(pixels, pixels),
                    boundless=True,
                    masked=True,
                    resampling=Resampling.bilinear,
                )
                valid_masks.append(~np.ma.getmaskarray(band))
                scale, offset = _band_scale_offset(item, band_key)
                values.append(band.astype("float32").filled(np.nan) * scale + offset)
                common_bounds = bounds
                common_crs = dataset.crs
        hrefs[band_key] = _unsigned_url(item.assets[band_key].href)
    reflectance = np.stack(values, axis=-1)
    coverage_fraction = float(
        np.count_nonzero(np.logical_and.reduce(valid_masks)) / valid_masks[0].size
    )
    # One fixed physical stretch for every Landsat panel; never per-image
    # percentile stretching, which would weaken visual comparison.
    rgb = np.clip((reflectance - 0.0) / 0.30, 0, 1)
    rgb = np.nan_to_num(rgb, nan=0.0)
    return (
        np.rint(rgb * 255).astype(np.uint8),
        common_crs,
        common_bounds,
        {
            "asset_keys": list(band_keys),
            "asset_hrefs": hrefs,
            "render": "surface_reflectance_fixed_0_to_0.30",
            "output_pixels_each": [pixels, pixels],
            "footprint_bounds_source_crs": list(common_bounds),
            "source_crs": str(common_crs),
            "coverage_fraction": coverage_fraction,
        },
    )


def _render_landsat_pair(
    before: Item,
    after: Item,
    *,
    geometry_wgs84,
    output_path: Path,
    pixels: int,
    padding_m: float,
) -> dict[str, Any]:
    arrays = []
    details = []
    for item in (before, after):
        array, crs, bounds, detail = _read_landsat_rgb(
            item,
            geometry_wgs84=geometry_wgs84,
            pixels=pixels,
            padding_m=padding_m,
        )
        image = Image.fromarray(array, mode="RGB")
        _draw_geometry(image, geometry_wgs84, dataset_crs=crs, bounds=bounds)
        arrays.append(np.asarray(image))
        details.append(detail)
    panels = Image.fromarray(np.concatenate(arrays, axis=1), mode="RGB")
    combined = Image.new("RGB", (pixels * 2, pixels + 30), color=(255, 255, 255))
    combined.paste(panels, (0, 30))
    draw = ImageDraw.Draw(combined)
    before_label = f"BEFORE  {_item_datetime(before).date().isoformat()}  {before.id}"
    after_label = f"AFTER  {_item_datetime(after).date().isoformat()}  {after.id}"
    draw.text((8, 8), before_label, fill=(0, 0, 0))
    draw.text((pixels + 8, 8), after_label, fill=(0, 0, 0))
    draw.line([(pixels, 0), (pixels, pixels + 30)], fill=(255, 255, 255), width=3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output_path, format="PNG", compress_level=9, optimize=False)
    return {"panels": ["before", "after"], "panel_details": details}


def _spectral_point(
    item: Item, *, longitude: float, latitude: float
) -> dict[str, Any] | None:
    signed = _signed_copy(item, "sentinel2")
    band_keys = ("red", "nir", "nir08", "swir16", "swir22")
    if "scl" not in signed.assets or any(
        key not in signed.assets for key in band_keys
    ):
        return None
    output_shape = (12, 12)
    half_width_m = 60.0
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MAX_RETRY="3",
    ):
        with rasterio.open(signed.assets["scl"].href) as scl_dataset:
            scl = scl_dataset.read(
                1,
                window=_point_window(
                    scl_dataset, longitude, latitude, half_width_m
                ),
                out_shape=output_shape,
                boundless=True,
                masked=True,
                resampling=Resampling.nearest,
            )
        scl_valid = ~np.ma.getmaskarray(scl)
        scl_values = np.asarray(scl.filled(0), dtype=np.uint8)
        clear = scl_valid & np.isin(scl_values, list(SENTINEL_CLEAR_SCL))
        if np.count_nonzero(clear) < 4:
            return None

        values: dict[str, float] = {}
        valid_counts: dict[str, int] = {}
        for key in band_keys:
            with rasterio.open(signed.assets[key].href) as dataset:
                band = dataset.read(
                    1,
                    window=_point_window(
                        dataset, longitude, latitude, half_width_m
                    ),
                    out_shape=output_shape,
                    boundless=True,
                    masked=True,
                    resampling=Resampling.bilinear,
                )
            band_valid = ~np.ma.getmaskarray(band)
            support = clear & band_valid
            valid_count = int(np.count_nonzero(support))
            if valid_count < 4:
                return None
            scale, offset = _band_scale_offset(item, key)
            raw = np.asarray(band.astype("float32").filled(np.nan), dtype=float)[support]
            values[key] = float(np.median(raw) * scale + offset)
            valid_counts[key] = valid_count
    red = values["red"]
    nir = values["nir"]
    nir08 = values["nir08"]
    swir16 = values["swir16"]
    swir22 = values["swir22"]

    def ratio(a: float, b: float) -> float | None:
        return None if abs(a + b) < 1e-12 else (a - b) / (a + b)

    denominator = nir + 2.4 * red + 1.0
    evi2 = None if abs(denominator) < 1e-12 else 2.5 * (nir - red) / denominator
    return {
        "item_id": item.id,
        "observed_at": _item_datetime(item).isoformat().replace("+00:00", "Z"),
        "item_metadata_sha256": canonical_sha256(item.to_dict()),
        "sampling_support": "median_surface_reflectance_in_120m_square_at_representative_point",
        "qa_mask": "Sentinel-2 SCL clear classes 2,4,5,6,7,11; minimum four aligned clear pixels",
        "qa_coverage_fraction": float(np.count_nonzero(scl_valid) / scl_valid.size),
        "qa_clear_fraction": float(
            np.count_nonzero(clear) / max(1, np.count_nonzero(scl_valid))
        ),
        "valid_pixel_counts": valid_counts,
        "ndmi": ratio(nir08, swir16),
        "nbr": ratio(nir08, swir22),
        "evi2": evi2,
    }


def _write_series_svg(points: list[dict[str, Any]], output_path: Path) -> None:
    width, height = 720, 360
    left, right, top, bottom = 70, 690, 30, 300
    dates = [dt.datetime.fromisoformat(point["observed_at"].replace("Z", "+00:00")) for point in points]
    minimum, maximum = min(dates), max(dates)
    span = max(1.0, (maximum - minimum).total_seconds())

    def x(value: dt.datetime) -> float:
        return left + (value - minimum).total_seconds() / span * (right - left)

    def y(value: float) -> float:
        return bottom - (value + 1.0) / 2.0 * (bottom - top)

    colors = {"ndmi": "#177245", "nbr": "#8b3a3a", "evi2": "#315fa8"}
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#555"/>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#555"/>',
    ]
    for tick in (-1.0, -0.5, 0.0, 0.5, 1.0):
        position = y(tick)
        lines.append(f'<line x1="{left}" y1="{position:.2f}" x2="{right}" y2="{position:.2f}" stroke="#ddd"/>')
        lines.append(f'<text x="12" y="{position + 4:.2f}" font-family="sans-serif" font-size="12">{tick:.1f}</text>')
    for index, name in enumerate(("ndmi", "nbr", "evi2")):
        usable = [(date, point[name]) for date, point in zip(dates, points) if point[name] is not None]
        coordinates = " ".join(f"{x(date):.2f},{y(float(value)):.2f}" for date, value in usable)
        if len(usable) >= 2:
            lines.append(f'<polyline points="{coordinates}" fill="none" stroke="{colors[name]}" stroke-width="3"/>')
        for date, value in usable:
            lines.append(f'<circle cx="{x(date):.2f}" cy="{y(float(value)):.2f}" r="5" fill="{colors[name]}"/>')
        lines.append(f'<text x="{left + index * 110}" y="340" font-family="sans-serif" font-size="14" fill="{colors[name]}">{name.upper()}</text>')
    for date in dates:
        lines.append(f'<text x="{x(date) - 36:.2f}" y="320" font-family="sans-serif" font-size="11">{html.escape(date.date().isoformat())}</text>')
    lines.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8", newline="\n")


def _mapbiomas_array(
    path: Path, *, longitude: float, latitude: float, pixels: int = 320
) -> tuple[np.ndarray, dict[str, Any]]:
    # Approximately 1.5 km around the target; this is a direct read-only window,
    # not the wider-extent crop owned by Phase 2A.5.
    degree = 1500.0 / 111_000.0
    with rasterio.open(path) as dataset:
        transformer = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)
        x0, y0 = transformer.transform(longitude - degree, latitude - degree)
        x1, y1 = transformer.transform(longitude + degree, latitude + degree)
        bounds = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        window = from_bounds(*bounds, transform=dataset.transform)
        values = dataset.read(
            1,
            window=window,
            out_shape=(pixels, pixels),
            boundless=True,
            fill_value=0,
            resampling=Resampling.nearest,
        ).astype(np.uint16)
        crs = str(dataset.crs)
    unique, counts = np.unique(values, return_counts=True)
    histogram = {
        str(int(value)): int(count)
        for value, count in zip(unique, counts)
    }
    rgb = np.zeros((pixels, pixels, 3), dtype=np.uint8)
    for value in unique:
        integer = int(value)
        color = (205, 205, 205) if integer == 0 else (
            (integer * 53 + 41) % 220 + 20,
            (integer * 97 + 17) % 220 + 20,
            (integer * 149 + 73) % 220 + 20,
        )
        rgb[values == value] = color
    return rgb, {"class_histogram": histogram, "source_crs": crs, "resampling": "nearest"}


def _render_mapbiomas_pair(
    *,
    path_10m: Path,
    path_30m: Path,
    longitude: float,
    latitude: float,
    output_path: Path,
) -> dict[str, Any]:
    array_10, detail_10 = _mapbiomas_array(
        path_10m, longitude=longitude, latitude=latitude
    )
    array_30, detail_30 = _mapbiomas_array(
        path_30m, longitude=longitude, latitude=latitude
    )
    panels = Image.fromarray(np.concatenate([array_10, array_30], axis=1), mode="RGB")
    combined = Image.new("RGB", (640, 350), color=(255, 255, 255))
    combined.paste(panels, (0, 30))
    draw = ImageDraw.Draw(combined)
    draw.text((8, 8), "MapBiomas 2024 candidate — Collection 3 beta 10 m", fill=(0, 0, 0))
    draw.text((328, 8), "MapBiomas 2024 — Collection 10.1 30 m", fill=(0, 0, 0))
    draw.line([(320, 0), (320, 350)], fill=(255, 255, 255), width=3)
    for offset in (0, 320):
        draw.ellipse((offset + 154, 184, offset + 166, 196), outline=(255, 255, 0), width=3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output_path, format="PNG", compress_level=9, optimize=False)
    return {
        "panels": ["collection3_beta_10m_2024", "collection10_1_30m_2024"],
        "interpretation": "numeric_class_context_only_no_phase2a5_mapping",
        "collection3_beta_10m": detail_10,
        "collection10_1_30m": detail_30,
    }


def _asset_evidence(
    *,
    role: str,
    path: Path,
    independence_class: str,
    source: dict[str, Any],
    status: str = "available",
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "role": role,
        "status": status,
        "reason": reason,
        "independence_class": independence_class,
        "local_path": None,
        "local_bytes": None,
        "local_sha256": None,
        "source": source,
        "_source_path": str(path),
    }


def _error_evidence(role: str, reason: BaseException | str, independence_class: str) -> dict[str, Any]:
    return {
        "role": role,
        "status": "error",
        "reason": _safe_error_message(reason),
        "independence_class": independence_class,
        "local_path": None,
        "local_bytes": None,
        "local_sha256": None,
        "source": None,
    }


def _cache_key(unit: Mapping[str, Any], config: EvidenceConfig) -> str:
    return canonical_sha256(
        {
            "sample_id": unit["sample_id"],
            "observed_on": unit["observed_on"],
            "canonical_geometry": unit["canonical_geometry"],
            "config": evidence_config_record(config),
        }
    )


def _cache_write(
    case_dir: Path,
    sample_id: str,
    cache_key: str,
    evidence: dict[str, Any],
) -> None:
    stored = copy.deepcopy(evidence)
    for value in stored.values():
        source_path = value.pop("_source_path", None)
        if source_path:
            asset_path = Path(source_path)
            value["_cache_asset"] = asset_path.relative_to(case_dir).as_posix()
            value["_cache_asset_bytes"] = asset_path.stat().st_size
            value["_cache_asset_sha256"] = sha256_file(asset_path)
    write_canonical_json(
        case_dir / "evidence.json",
        {"sample_id": sample_id, "cache_key": cache_key, "evidence": stored},
    )


def _cache_read(
    case_dir: Path, sample_id: str, cache_key: str
) -> dict[str, Any] | None:
    path = case_dir / "evidence.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("sample_id") != sample_id or value.get("cache_key") != cache_key:
        return None
    evidence = value["evidence"]
    for record in evidence.values():
        asset = record.pop("_cache_asset", None)
        expected_bytes = record.pop("_cache_asset_bytes", None)
        expected_sha256 = record.pop("_cache_asset_sha256", None)
        if asset:
            relative = Path(asset)
            if relative.is_absolute() or ".." in relative.parts:
                return None
            candidate = case_dir / relative
            if (
                not candidate.is_file()
                or candidate.stat().st_size != expected_bytes
                or sha256_file(candidate) != expected_sha256
            ):
                return None
            record["_source_path"] = str(candidate)
    return evidence


def collect_case_evidence(
    unit: Mapping[str, Any],
    *,
    config: EvidenceConfig,
) -> dict[str, Any]:
    """Collect all possible evidence for one frozen sampled case."""
    sample_id = unit["sample_id"]
    case_dir = config.cache_dir / sample_id
    cache_key = _cache_key(unit, config)
    cached = _cache_read(case_dir, sample_id, cache_key)
    if cached is not None:
        return cached
    case_dir.mkdir(parents=True, exist_ok=True)
    geometry = shape(unit["canonical_geometry"])
    point = geometry.representative_point()
    longitude, latitude = point.x, point.y
    target_date = dt.date.fromisoformat(unit["observed_on"])
    target = dt.datetime.combine(target_date, dt.time.min, tzinfo=dt.timezone.utc)
    before_start = target - dt.timedelta(days=config.before_days)
    before_end = target - dt.timedelta(microseconds=1)
    after_start = target
    after_end_date = min(
        config.evidence_cutoff_date,
        target_date + dt.timedelta(days=config.after_days),
    )
    after_end = dt.datetime.combine(
        after_end_date, dt.time.max, tzinfo=dt.timezone.utc
    )
    evidence: dict[str, Any] = {}

    sentinel_before = sentinel_after = None
    before_clear = after_clear = None
    before_coverage = after_coverage = None
    before_audit: list[dict[str, Any]] = []
    after_audit: list[dict[str, Any]] = []
    try:
        candidates = _search_items(
            sensor="sentinel2",
            longitude=longitude,
            latitude=latitude,
            start=before_start,
            end=before_end,
            max_cloud=config.max_scene_cloud_percent,
        )
        sentinel_before, before_clear, before_coverage, before_audit = _select_item(
            candidates,
            sensor="sentinel2",
            target=target,
            direction="before",
            longitude=longitude,
            latitude=latitude,
            config=config,
        )
        render = _render_sentinel(
            sentinel_before,
            geometry_wgs84=geometry,
            output_path=case_dir / "before.png",
            pixels=config.chip_pixels,
            padding_m=config.local_padding_m,
        )
        status = (
            "available"
            if before_clear >= config.minimum_local_clear_fraction
            and before_coverage >= config.minimum_local_coverage_fraction
            and render["coverage_fraction"] >= config.minimum_local_coverage_fraction
            else "insufficient"
        )
        evidence["before_imagery"] = _asset_evidence(
            role="before_imagery",
            path=case_dir / "before.png",
            independence_class="operational_source_same_sensor",
            status=status,
            reason=None if status == "available" else "Best candidate is below the fixed local-clear evidence threshold.",
            source={
                **_item_record(sentinel_before, sensor="sentinel2"),
                "local_clear_fraction": before_clear,
                "local_coverage_fraction": before_coverage,
                "temporal_gap_days": round(
                    (_item_datetime(sentinel_before) - target).total_seconds() / 86400,
                    6,
                ),
                "selection_candidates": before_audit,
                "search_window": [before_start.isoformat(), before_end.isoformat()],
                "catalog_accessed_at": config.catalog_accessed_at,
                "attribution": f"Contains modified Copernicus Sentinel data {_item_datetime(sentinel_before).year}",
                **render,
            },
        )
    except Exception as exc:
        evidence["before_imagery"] = _error_evidence(
            "before_imagery", str(exc), "operational_source_same_sensor"
        )

    try:
        if after_end < after_start:
            raise EvidenceRetrievalError("evidence cutoff precedes target date")
        candidates = _search_items(
            sensor="sentinel2",
            longitude=longitude,
            latitude=latitude,
            start=after_start,
            end=after_end,
            max_cloud=config.max_scene_cloud_percent,
        )
        sentinel_after, after_clear, after_coverage, after_audit = _select_item(
            candidates,
            sensor="sentinel2",
            target=target,
            direction="after",
            longitude=longitude,
            latitude=latitude,
            config=config,
        )
        render = _render_sentinel(
            sentinel_after,
            geometry_wgs84=geometry,
            output_path=case_dir / "after.png",
            pixels=config.chip_pixels,
            padding_m=config.local_padding_m,
        )
        status = (
            "available"
            if after_clear >= config.minimum_local_clear_fraction
            and after_coverage >= config.minimum_local_coverage_fraction
            and render["coverage_fraction"] >= config.minimum_local_coverage_fraction
            else "insufficient"
        )
        evidence["after_imagery"] = _asset_evidence(
            role="after_imagery",
            path=case_dir / "after.png",
            independence_class="operational_source_same_sensor",
            status=status,
            reason=None if status == "available" else "Best candidate is below the fixed local-clear evidence threshold.",
            source={
                **_item_record(sentinel_after, sensor="sentinel2"),
                "local_clear_fraction": after_clear,
                "local_coverage_fraction": after_coverage,
                "temporal_gap_days": round(
                    (_item_datetime(sentinel_after) - target).total_seconds() / 86400,
                    6,
                ),
                "selection_candidates": after_audit,
                "search_window": [after_start.isoformat(), after_end.isoformat()],
                "catalog_accessed_at": config.catalog_accessed_at,
                "attribution": f"Contains modified Copernicus Sentinel data {_item_datetime(sentinel_after).year}",
                **render,
            },
        )
        context_render = _render_sentinel(
            sentinel_after,
            geometry_wgs84=geometry,
            output_path=case_dir / "context.png",
            pixels=config.context_pixels,
            padding_m=config.local_padding_m,
            context_half_width_m=config.context_half_width_m,
        )
        context_status = (
            status
            if context_render["coverage_fraction"]
            >= config.minimum_local_coverage_fraction
            else "insufficient"
        )
        evidence["wider_spatial_context"] = _asset_evidence(
            role="wider_spatial_context",
            path=case_dir / "context.png",
            independence_class="operational_source_same_sensor",
            status=context_status,
            reason=None if context_status == "available" else "Context is below a fixed local-clear or spatial-coverage threshold.",
            source={
                **_item_record(sentinel_after, sensor="sentinel2"),
                "local_clear_fraction": after_clear,
                "local_coverage_fraction": after_coverage,
                "temporal_gap_days": round(
                    (_item_datetime(sentinel_after) - target).total_seconds() / 86400,
                    6,
                ),
                "half_width_m": config.context_half_width_m,
                "catalog_accessed_at": config.catalog_accessed_at,
                "attribution": f"Contains modified Copernicus Sentinel data {_item_datetime(sentinel_after).year}",
                **context_render,
            },
        )
    except Exception as exc:
        evidence["after_imagery"] = _error_evidence(
            "after_imagery", str(exc), "operational_source_same_sensor"
        )
        evidence["wider_spatial_context"] = _error_evidence(
            "wider_spatial_context", str(exc), "operational_source_same_sensor"
        )

    if sentinel_before is not None and sentinel_after is not None:
        try:
            points = [
                point_record
                for point_record in (
                    _spectral_point(
                        sentinel_before, longitude=longitude, latitude=latitude
                    ),
                    _spectral_point(
                        sentinel_after, longitude=longitude, latitude=latitude
                    ),
                )
                if point_record is not None
            ]
            if len(points) < 2:
                raise EvidenceRetrievalError(
                    "fewer than two complete item-provenanced spectral observations"
                )
            _write_series_svg(points, case_dir / "timeseries.svg")
            evidence["provenance_valid_time_series"] = _asset_evidence(
                role="provenance_valid_time_series",
                path=case_dir / "timeseries.svg",
                independence_class="operational_source_same_sensor",
                source={
                    "dataset": "Element84 Sentinel-2 L2A validation-only sparse series",
                    "points": points,
                    "indices": ["ndmi", "nbr", "evi2"],
                    "gap_filling": "none",
                    "legacy_sqlite_used": False,
                    "limitations": [
                        "Two-point sparse validation series; not the canonical monitoring chronology.",
                        "Representative-point window, not a full-polygon or regional statistic.",
                        "Accepted baseline 1.0.0 is referenced by the package but not subtracted from these validation points.",
                    ],
                },
            )
        except Exception as exc:
            evidence["provenance_valid_time_series"] = _error_evidence(
                "provenance_valid_time_series",
                str(exc),
                "operational_source_same_sensor",
            )
    else:
        evidence["provenance_valid_time_series"] = _error_evidence(
            "provenance_valid_time_series",
            "Before and after Sentinel items are both required for the sparse provenance-valid series.",
            "operational_source_same_sensor",
        )

    try:
        landsat_before_candidates = _search_items(
            sensor="landsat",
            longitude=longitude,
            latitude=latitude,
            start=before_start,
            end=before_end,
            max_cloud=config.max_scene_cloud_percent,
        )
        landsat_after_candidates = _search_items(
            sensor="landsat",
            longitude=longitude,
            latitude=latitude,
            start=after_start,
            end=after_end,
            max_cloud=config.max_scene_cloud_percent,
        )
        landsat_before, lb_clear, lb_coverage, lb_audit = _select_item(
            landsat_before_candidates,
            sensor="landsat",
            target=target,
            direction="before",
            longitude=longitude,
            latitude=latitude,
            config=config,
        )
        landsat_after, la_clear, la_coverage, la_audit = _select_item(
            landsat_after_candidates,
            sensor="landsat",
            target=target,
            direction="after",
            longitude=longitude,
            latitude=latitude,
            config=config,
        )
        render = _render_landsat_pair(
            landsat_before,
            landsat_after,
            geometry_wgs84=geometry,
            output_path=case_dir / "landsat-comparison.png",
            pixels=config.chip_pixels,
            padding_m=config.local_padding_m,
        )
        panel_coverages = [
            panel["coverage_fraction"] for panel in render["panel_details"]
        ]
        status = (
            "available"
            if min(lb_clear, la_clear) >= config.minimum_local_clear_fraction
            and min(lb_coverage, la_coverage, *panel_coverages)
            >= config.minimum_local_coverage_fraction
            else "insufficient"
        )
        evidence["independent_source_comparison"] = _asset_evidence(
            role="independent_source_comparison",
            path=case_dir / "landsat-comparison.png",
            independence_class="independent_sensor",
            status=status,
            reason=None if status == "available" else "At least one Landsat panel is below the fixed local-clear threshold.",
            source={
                "dataset": "Landsat Collection 2 Level-2",
                "before": {**_item_record(landsat_before, sensor="landsat"), "local_clear_fraction": lb_clear, "local_coverage_fraction": lb_coverage, "temporal_gap_days": round((_item_datetime(landsat_before) - target).total_seconds() / 86400, 6), "selection_candidates": lb_audit},
                "after": {**_item_record(landsat_after, sensor="landsat"), "local_clear_fraction": la_clear, "local_coverage_fraction": la_coverage, "temporal_gap_days": round((_item_datetime(landsat_after) - target).total_seconds() / 86400, 6), "selection_candidates": la_audit},
                "search_windows": {
                    "before": [before_start.isoformat(), before_end.isoformat()],
                    "after": [after_start.isoformat(), after_end.isoformat()],
                },
                "catalog_accessed_at": config.catalog_accessed_at,
                "attribution": "Landsat Collection 2 Level-2, U.S. Geological Survey; hosted by Microsoft Planetary Computer.",
                "independence_limit": "Independent optical sensor corroboration, not ground truth and not a production baseline.",
                **render,
            },
        )
    except Exception as exc:
        evidence["independent_source_comparison"] = _error_evidence(
            "independent_source_comparison", str(exc), "independent_sensor"
        )

    if config.mapbiomas_10m_path and config.mapbiomas_30m_path:
        try:
            render = _render_mapbiomas_pair(
                path_10m=config.mapbiomas_10m_path,
                path_30m=config.mapbiomas_30m_path,
                longitude=longitude,
                latitude=latitude,
                output_path=case_dir / "mapbiomas-comparison.png",
            )
            evidence["mapbiomas_context_comparison"] = _asset_evidence(
                role="mapbiomas_context_comparison",
                path=case_dir / "mapbiomas-comparison.png",
                independence_class="contextual_classification",
                source={
                    "dataset": "MapBiomas 2024 candidate contextual comparison",
                    "collection3_beta_10m_sha256": MAPBIOMAS_10M_SHA256,
                    "collection10_1_30m_sha256": MAPBIOMAS_30M_SHA256,
                    "read_mode": "direct_read_only_source_windows_no_regional_crop",
                    "method_decision_status": "none",
                    "attribution": "MapBiomas Collection 3 beta 10 m and Collection 10.1 30 m, 2024; context only under CC-BY attribution requirements.",
                    **render,
                },
            )
        except Exception as exc:
            evidence["mapbiomas_context_comparison"] = _error_evidence(
                "mapbiomas_context_comparison",
                str(exc),
                "contextual_classification",
            )
    else:
        evidence["mapbiomas_context_comparison"] = _error_evidence(
            "mapbiomas_context_comparison",
            "MapBiomas 2024 source paths were not supplied.",
            "contextual_classification",
        )

    _cache_write(case_dir, sample_id, cache_key, evidence)
    return evidence


def collect_evidence(
    selected_units: Iterable[Mapping[str, Any]],
    *,
    config: EvidenceConfig,
    workers: int = 4,
) -> dict[str, dict[str, Any]]:
    """Collect/resume read-only evidence for a frozen selected sample."""
    units = list(selected_units)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    if workers <= 0:
        raise ValueError("workers must be positive")
    if config.mapbiomas_10m_path:
        if sha256_file(config.mapbiomas_10m_path) != MAPBIOMAS_10M_SHA256:
            raise EvidenceRetrievalError("MapBiomas Collection 3 beta 10 m source checksum mismatch")
    if config.mapbiomas_30m_path:
        if sha256_file(config.mapbiomas_30m_path) != MAPBIOMAS_30M_SHA256:
            raise EvidenceRetrievalError("MapBiomas Collection 10.1 30 m source checksum mismatch")
    output: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(collect_case_evidence, unit, config=config): unit[
                "sample_id"
            ]
            for unit in units
        }
        for future in as_completed(futures):
            sample_id = futures[future]
            try:
                output[sample_id] = future.result()
            except Exception as exc:  # fail per case, never silently replace it
                output[sample_id] = {
                    "before_imagery": _error_evidence("before_imagery", str(exc), "operational_source_same_sensor"),
                    "after_imagery": _error_evidence("after_imagery", str(exc), "operational_source_same_sensor"),
                    "wider_spatial_context": _error_evidence("wider_spatial_context", str(exc), "operational_source_same_sensor"),
                    "provenance_valid_time_series": _error_evidence("provenance_valid_time_series", str(exc), "operational_source_same_sensor"),
                    "independent_source_comparison": _error_evidence("independent_source_comparison", str(exc), "independent_sensor"),
                    "mapbiomas_context_comparison": _error_evidence("mapbiomas_context_comparison", str(exc), "contextual_classification"),
                }
    return output
