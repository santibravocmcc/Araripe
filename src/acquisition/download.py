"""Stream and download satellite bands from COG assets via STAC items."""

from __future__ import annotations

from typing import Optional

import numpy as np
import rioxarray  # noqa: F401 — registers the rio accessor
import xarray as xr
from loguru import logger
from pystac import Item
from rasterio.crs import CRS

from config.bands import LANDSAT_BANDS, SENTINEL2_BANDS, get_asset_key
from config.settings import CHUNK_SIZE, TARGET_CRS


def _reflectance_scale_offset(item: Item, asset_key: str, sensor: str) -> tuple[float, float]:
    """Return (scale, offset) to convert a DN band to surface reflectance [0,1].

    Prefers the STAC raster-extension ``raster:bands`` scale/offset (authoritative
    and per-asset; present for Element84 S2, Planetary Computer Landsat, and HLS
    when available). Falls back per sensor:
      * sentinel2 : scale 1e-4, offset -0.1 for processing baseline >= 04.00
                    (2022-01-25+), else 0.
      * landsat   : Collection 2 Level 2 surface reflectance → scale 2.75e-5,
                    offset -0.2.
      * hls       : reflectance * 10000 → scale 1e-4, offset 0.
    """
    try:
        rb = item.assets[asset_key].extra_fields.get("raster:bands")
        if rb and isinstance(rb, list) and rb[0].get("scale") is not None:
            scale = float(rb[0]["scale"])
            offset = float(rb[0].get("offset") or 0.0)
            return scale, offset
    except Exception:
        pass

    if sensor == "landsat":
        return 2.75e-5, -0.2
    if sensor == "hls":
        return 1e-4, 0.0

    # sentinel2 fallback
    scale, offset = 1e-4, 0.0
    try:
        pb = item.properties.get("s2:processing_baseline")
        if pb is not None:
            if float(pb) >= 4.0:
                offset = -0.1
        elif item.datetime is not None:
            from datetime import datetime, timezone

            cutoff = datetime(2022, 1, 25, tzinfo=item.datetime.tzinfo or timezone.utc)
            if item.datetime >= cutoff:
                offset = -0.1
    except Exception:
        pass
    return scale, offset


def load_band(
    item: Item,
    logical_band: str,
    sensor: str = "sentinel2",
    target_crs: str = TARGET_CRS,
    target_resolution: Optional[float] = None,
) -> xr.DataArray:
    """Load a single band from a STAC item as an xarray DataArray.

    Uses HTTP range requests to stream only the required data from COGs.

    Parameters
    ----------
    item : pystac.Item
        A STAC item with asset hrefs pointing to COG files.
    logical_band : str
        Logical band name (e.g., "nir", "swir16", "red").
    sensor : str
        One of "sentinel2", "landsat", or "hls".
    target_crs : str
        Target CRS for reprojection (default: UTM 24S).
    target_resolution : float, optional
        Target resolution in meters. If None, uses native resolution.

    Returns
    -------
    xr.DataArray
        Band data with spatial coordinates and CRS metadata.
    """
    asset_key = get_asset_key(sensor, logical_band)
    href = item.assets[asset_key].href

    logger.debug("Loading band {} from {}", logical_band, href)

    da = rioxarray.open_rasterio(
        href,
        chunks={"x": CHUNK_SIZE, "y": CHUNK_SIZE},
    )

    # Squeeze the band dimension if present (COGs are typically single-band)
    if "band" in da.dims and da.sizes["band"] == 1:
        da = da.squeeze("band", drop=True)

    # Convert to float32 to avoid unsigned integer underflow in index
    # computations (e.g., NDMI = (NIR - SWIR) / (NIR + SWIR) where the
    # subtraction wraps around in uint16).
    if da.dtype != np.float32:
        da = da.astype(np.float32)

    # ─── Surface-reflectance scaling (COUPLED with the baseline scale) ────
    # When config.settings.REFLECTANCE_SCALING is True, convert raw DN to
    # surface reflectance in [0,1] via the STAC raster:bands scale/offset:
    #     reflectance = DN * scale + offset
    # applied per-scene and per-sensor (S2/Landsat/HLS). This is physically
    # correct and fixes the inflated/mis-scaled EVI2 (whose "+1" soil term
    # assumes reflectance in [0,1] — the "45.7% of EVI2 outside [-1,1]"
    # contamination). NDMI/NBR are ratios and are far less sensitive.
    #
    # CRITICAL COUPLING: this must match the scale of the on-disk baselines.
    # The current baselines are DN-scale, so REFLECTANCE_SCALING defaults to
    # False and this path preserves the legacy DN behaviour (Sentinel-2 +1000
    # offset heuristic). build_baseline.py forces the flag True for its own run
    # so rebuilt baselines are in reflectance; flip the setting True only after
    # rebuilding. See AUDITORIA_TECNICA.md Task 1 and config/settings.py.
    #
    # Classification bands (SCL for S2, QA for Landsat/HLS) are never scaled.
    import config.settings as _settings

    is_class_band = logical_band in ("scl", "qa")
    if getattr(_settings, "REFLECTANCE_SCALING", False) and not is_class_band:
        da = da.where(da != 0)  # 0 = fill → NaN
        scale, offset = _reflectance_scale_offset(item, asset_key, sensor)
        da = da * scale + offset
        # Floor at 0: negative surface reflectance is physically invalid (it
        # arises from the BOA offset on near-zero/dark pixels). Crucially, this
        # keeps the normalized-difference denominator (e.g. NIR+SWIR) from
        # crossing zero, which otherwise makes NDMI/NBR explode to ±1e5 at
        # dark/shadow pixels. With both bands >= 0, NDMI/NBR are bounded to
        # [-1, 1] by construction (NaN is preserved by clip).
        da = da.clip(min=0.0)
    elif sensor == "sentinel2" and not is_class_band:
        # Legacy DN path (matches the current DN-scale baselines). S2 L2A
        # processing baseline 04.00+ stores reflectance*10000 + 1000; the
        # historical code added +1000 to already-DN bands. Preserved here for
        # scale-consistency with the un-rebuilt baselines.
        try:
            sample = da.isel(x=slice(0, min(512, da.sizes["x"])),
                             y=slice(0, min(512, da.sizes["y"]))).values
            sample = sample[~np.isnan(sample)]
            if len(sample) > 0 and float(np.median(sample)) > 200.0:
                da = da + 1000.0
        except Exception:
            pass

    # Declare nodata=NaN for spectral bands BEFORE any fill-producing op. This
    # is the single most important correctness step: without it, rioxarray's
    # reproject / reproject_match / clip fill out-of-footprint (and clipped-out)
    # pixels with 0 — which the compositor then treats as valid data (e.g.
    # EVI2 = 2.5*(0-0)/(0+0+1) = 0), collapsing coverage. It must be set even
    # when reprojection is skipped (scene CRS already == target), because
    # clip_dataset_to_aoi downstream also fills. 0-valued reflectance stays
    # valid data (nodata is NaN, not 0).
    if not is_class_band:
        try:
            da.rio.write_nodata(np.nan, inplace=True)
        except Exception:
            pass

    # Reproject if needed
    if da.rio.crs and str(da.rio.crs) != target_crs:
        if is_class_band:
            da = da.rio.reproject(
                target_crs, resolution=target_resolution, resampling=1,
            )
        else:
            da = da.rio.reproject(
                target_crs,
                resolution=target_resolution,
                resampling=1,  # bilinear
                nodata=np.nan,
            )

    da.attrs["logical_band"] = logical_band
    da.attrs["sensor"] = sensor
    da.attrs["source_item"] = item.id
    return da


def load_bands(
    item: Item,
    band_names: list[str],
    sensor: str = "sentinel2",
    target_crs: str = TARGET_CRS,
    target_resolution: Optional[float] = None,
) -> xr.Dataset:
    """Load multiple bands from a STAC item into an xarray Dataset.

    All bands are reprojected to the same CRS and optionally resampled
    to a common resolution for consistent pixel alignment.

    Parameters
    ----------
    item : pystac.Item
        A STAC item.
    band_names : list[str]
        List of logical band names to load.
    sensor : str
        Sensor identifier.
    target_crs : str
        Target CRS.
    target_resolution : float, optional
        Common resolution for all bands. Required when mixing 10m and 20m bands.

    Returns
    -------
    xr.Dataset
        Dataset with each band as a data variable.
    """
    arrays = {}
    for name in band_names:
        arrays[name] = load_band(
            item,
            name,
            sensor=sensor,
            target_crs=target_crs,
            target_resolution=target_resolution,
        )

    # ─── Align all bands to a common pixel grid ──────────────────────
    # Bands from different native resolutions (e.g., S2 B8=10m vs
    # B8A/B11/B12/SCL=20m) produce slightly different x/y coordinates
    # after reprojection, even at the same target resolution.  This
    # causes xarray .where() to broadcast NaN into mismatched pixels.
    # Fix: snap all bands to one reference grid using nearest-neighbor
    # reindexing with a tolerance of one pixel width.
    if arrays:
        ref_name = "scl" if "scl" in arrays else next(iter(arrays))
        ref = arrays[ref_name]
        tolerance = target_resolution if target_resolution else 30.0
        for name in list(arrays.keys()):
            if name != ref_name:
                arrays[name] = arrays[name].reindex_like(
                    ref, method="nearest", tolerance=tolerance,
                )
        logger.debug(
            "Aligned {} bands to '{}' grid ({}x{} pixels)",
            len(arrays), ref_name,
            ref.sizes.get("y", "?"), ref.sizes.get("x", "?"),
        )

    ds = xr.Dataset(arrays)
    ds.attrs["item_id"] = item.id
    ds.attrs["datetime"] = str(item.datetime)
    ds.attrs["sensor"] = sensor
    return ds


def load_sentinel2_for_indices(
    item: Item,
    indices: list[str],
    resolution: float = 20.0,
) -> xr.Dataset:
    """Load Sentinel-2 bands required for specified vegetation indices.

    Automatically determines which bands are needed and loads them at a
    common resolution. Since moisture indices (NDMI, NBR) use 20m bands
    (B8A, B11, B12), the default resolution is 20m.

    Parameters
    ----------
    item : pystac.Item
        A Sentinel-2 STAC item.
    indices : list[str]
        Index names (e.g., ["ndmi", "nbr", "evi2"]).
    resolution : float
        Target resolution in meters (default 20m for moisture indices).

    Returns
    -------
    xr.Dataset
        Dataset with all required bands.
    """
    from config.bands import INDEX_BANDS

    required_bands = set()
    for idx in indices:
        required_bands.update(INDEX_BANDS[idx])

    # Always include SCL for cloud masking
    required_bands.add("scl")

    logger.info(
        "Loading {} bands for indices {} at {}m: {}",
        len(required_bands),
        indices,
        resolution,
        sorted(required_bands),
    )

    return load_bands(
        item,
        list(required_bands),
        sensor="sentinel2",
        target_resolution=resolution,
    )


def load_landsat_for_indices(
    item: Item,
    indices: list[str],
) -> xr.Dataset:
    """Load Landsat bands required for specified vegetation indices.

    Parameters
    ----------
    item : pystac.Item
        A Landsat STAC item.
    indices : list[str]
        Index names (e.g., ["ndmi", "nbr", "evi2"]).

    Returns
    -------
    xr.Dataset
        Dataset with all required bands at 30m resolution.
    """
    from config.bands import LANDSAT_INDEX_BANDS

    required_bands = set()
    for idx in indices:
        required_bands.update(LANDSAT_INDEX_BANDS[idx])

    # Always include QA for cloud masking
    required_bands.add("qa")

    logger.info(
        "Loading {} Landsat bands for indices {}: {}",
        len(required_bands),
        indices,
        sorted(required_bands),
    )

    return load_bands(
        item,
        list(required_bands),
        sensor="landsat",
    )


def load_hls_for_indices(
    item: Item,
    indices: list[str],
) -> xr.Dataset:
    """Load NASA HLS bands required for specified vegetation indices.

    HLS is on a common 30 m grid. Uses the Landsat-style band set (nir08 for
    NDMI/NBR/EVI2). Note: HLS assets are served from NASA Earthdata and require
    Earthdata authentication (earthaccess) for GDAL /vsicurl streaming.
    """
    from config.bands import LANDSAT_INDEX_BANDS

    required_bands = set()
    for idx in indices:
        required_bands.update(LANDSAT_INDEX_BANDS[idx])
    required_bands.add("qa")

    logger.info(
        "Loading {} HLS bands for indices {}: {}",
        len(required_bands), indices, sorted(required_bands),
    )
    return load_bands(item, list(required_bands), sensor="hls", target_resolution=30.0)
