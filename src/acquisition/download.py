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

    # Reproject if needed
    if da.rio.crs and str(da.rio.crs) != target_crs:
        da = da.rio.reproject(
            target_crs,
            resolution=target_resolution,
            resampling=1,  # bilinear
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
