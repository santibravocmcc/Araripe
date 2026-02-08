"""Vegetation and spectral index computation.

All formulas follow the specifications in the project methodology:
- NDVI, EVI2 use broad NIR (B8 for S2, B5 for Landsat)
- NDMI, NBR use narrow NIR (B8A for S2, B5 for Landsat) + SWIR bands
- BSI combines blue, red, NIR, and SWIR1
"""

from __future__ import annotations

import numpy as np
import xarray as xr


def _safe_divide(numerator: xr.DataArray, denominator: xr.DataArray) -> xr.DataArray:
    """Divide with protection against division by zero."""
    return numerator / denominator.where(denominator != 0, other=np.nan)


def ndvi(ds: xr.Dataset, nir: str = "nir", red: str = "red") -> xr.DataArray:
    """Normalized Difference Vegetation Index.

    NDVI = (NIR - RED) / (NIR + RED)
    S2: (B8 - B4) / (B8 + B4) at 10m
    Landsat: (B5 - B4) / (B5 + B4) at 30m
    """
    result = _safe_divide(ds[nir] - ds[red], ds[nir] + ds[red])
    result.name = "ndvi"
    return result


def evi2(ds: xr.Dataset, nir: str = "nir", red: str = "red") -> xr.DataArray:
    """Enhanced Vegetation Index 2 (two-band version, no blue needed).

    EVI2 = 2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)
    """
    numerator = 2.5 * (ds[nir] - ds[red])
    denominator = ds[nir] + 2.4 * ds[red] + 1
    result = _safe_divide(numerator, denominator)
    result.name = "evi2"
    return result


def ndmi(ds: xr.Dataset, nir: str = "nir08", swir16: str = "swir16") -> xr.DataArray:
    """Normalized Difference Moisture Index.

    NDMI = (NIR - SWIR1) / (NIR + SWIR1)
    S2: (B8A - B11) / (B8A + B11) at 20m
    Landsat: (B5 - B6) / (B5 + B6) at 30m

    Best single index for deforestation detection in Caatinga/Cerrado transition.
    """
    result = _safe_divide(ds[nir] - ds[swir16], ds[nir] + ds[swir16])
    result.name = "ndmi"
    return result


def nbr(ds: xr.Dataset, nir: str = "nir08", swir22: str = "swir22") -> xr.DataArray:
    """Normalized Burn Ratio.

    NBR = (NIR - SWIR2) / (NIR + SWIR2)
    S2: (B8A - B12) / (B8A + B12) at 20m
    Landsat: (B5 - B7) / (B5 + B7) at 30m

    Excellent for fire-related clearing detection.
    """
    result = _safe_divide(ds[nir] - ds[swir22], ds[nir] + ds[swir22])
    result.name = "nbr"
    return result


def savi(ds: xr.Dataset, nir: str = "nir", red: str = "red", L: float = 0.5) -> xr.DataArray:
    """Soil-Adjusted Vegetation Index.

    SAVI = 1.5 * (NIR - RED) / (NIR + RED + L)
    where L = 0.5 (standard soil brightness correction factor)

    Useful in sparse Caatinga where bare soil contributes to pixel reflectance.
    """
    numerator = 1.5 * (ds[nir] - ds[red])
    denominator = ds[nir] + ds[red] + L
    result = _safe_divide(numerator, denominator)
    result.name = "savi"
    return result


def bsi(
    ds: xr.Dataset,
    blue: str = "blue",
    red: str = "red",
    nir: str = "nir",
    swir16: str = "swir16",
) -> xr.DataArray:
    """Bare Soil Index.

    BSI = ((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))

    High values indicate exposed soil; confirms clearing when combined
    with vegetation index drops.
    """
    numerator = (ds[swir16] + ds[red]) - (ds[nir] + ds[blue])
    denominator = (ds[swir16] + ds[red]) + (ds[nir] + ds[blue])
    result = _safe_divide(numerator, denominator)
    result.name = "bsi"
    return result


def dnbr(nbr_pre: xr.DataArray, nbr_post: xr.DataArray) -> xr.DataArray:
    """Delta Normalized Burn Ratio for fire severity assessment.

    dNBR = NBR_pre - NBR_post
    Severity classes: >0.27 low, >0.44 moderate, >0.66 high
    """
    result = nbr_pre - nbr_post
    result.name = "dnbr"
    return result


# ─── Index dispatch ──────────────────────────────────────────────────────────

INDEX_FUNCTIONS = {
    "ndvi": ndvi,
    "evi2": evi2,
    "ndmi": ndmi,
    "nbr": nbr,
    "savi": savi,
    "bsi": bsi,
}

# Default band name overrides for Landsat (uses nir08 for everything)
LANDSAT_BAND_OVERRIDES = {
    "ndvi": {"nir": "nir08"},
    "evi2": {"nir": "nir08"},
    "savi": {"nir": "nir08"},
    "bsi":  {"nir": "nir08"},
}


def compute_index(
    ds: xr.Dataset,
    index_name: str,
    sensor: str = "sentinel2",
) -> xr.DataArray:
    """Compute a vegetation/spectral index from a dataset.

    Automatically adjusts band names based on sensor type.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset containing the required bands.
    index_name : str
        Name of the index to compute (e.g., "ndmi", "nbr", "evi2").
    sensor : str
        Sensor type: "sentinel2", "landsat", or "hls".

    Returns
    -------
    xr.DataArray
        Computed index values.
    """
    func = INDEX_FUNCTIONS[index_name]

    # Apply band name overrides for Landsat
    kwargs = {}
    if sensor in ("landsat", "hls") and index_name in LANDSAT_BAND_OVERRIDES:
        kwargs = LANDSAT_BAND_OVERRIDES[index_name]

    return func(ds, **kwargs)


def compute_all_indices(
    ds: xr.Dataset,
    indices: list[str],
    sensor: str = "sentinel2",
) -> xr.Dataset:
    """Compute multiple indices and return them as a dataset.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset with reflectance bands.
    indices : list[str]
        List of index names to compute.
    sensor : str
        Sensor type.

    Returns
    -------
    xr.Dataset
        Dataset with each index as a variable.
    """
    results = {}
    for idx_name in indices:
        results[idx_name] = compute_index(ds, idx_name, sensor=sensor)

    result_ds = xr.Dataset(results)
    result_ds.attrs = ds.attrs.copy()
    return result_ds
