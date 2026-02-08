"""Cloud masking for Sentinel-2 (SCL) and Landsat (QA_PIXEL)."""

from __future__ import annotations

import numpy as np
import xarray as xr
from loguru import logger

# ─── Sentinel-2 SCL classes to mask ──────────────────────────────────────────
# 0: No data, 1: Saturated, 3: Cloud shadow, 8: Cloud medium,
# 9: Cloud high, 10: Thin cirrus
S2_MASK_CLASSES = {0, 1, 3, 8, 9, 10}

# SCL classes considered clear
S2_CLEAR_CLASSES = {2, 4, 5, 6, 7, 11}  # Dark, Veg, Bare, Water, Snow


def mask_sentinel2(ds: xr.Dataset, scl_var: str = "scl") -> xr.Dataset:
    """Apply cloud mask to a Sentinel-2 dataset using the SCL band.

    Pixels classified as cloud, cloud shadow, cirrus, saturated, or no-data
    are set to NaN across all data variables.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset containing reflectance bands and the SCL band.
    scl_var : str
        Name of the SCL variable in the dataset.

    Returns
    -------
    xr.Dataset
        Masked dataset with SCL band removed.
    """
    if scl_var not in ds:
        logger.warning("SCL band '{}' not found in dataset, skipping mask", scl_var)
        return ds

    scl = ds[scl_var]

    # Build boolean mask: True where pixel is clear
    clear_mask = xr.zeros_like(scl, dtype=bool)
    for cls in S2_CLEAR_CLASSES:
        clear_mask = clear_mask | (scl == cls)

    # Apply mask to all non-SCL variables
    masked = ds.drop_vars(scl_var)
    masked = masked.where(clear_mask)

    n_total = clear_mask.size
    n_clear = int(clear_mask.sum().values) if hasattr(clear_mask.sum(), "values") else 0
    pct = (n_clear / n_total * 100) if n_total > 0 else 0
    logger.info("Cloud mask applied: {:.1f}% clear pixels", pct)

    return masked


def mask_landsat(ds: xr.Dataset, qa_var: str = "qa") -> xr.Dataset:
    """Apply cloud mask to a Landsat dataset using QA_PIXEL band.

    Uses bitwise operations on QA_PIXEL to mask clouds and cloud shadows.
    Bit 3 = cloud, Bit 4 = cloud shadow (1 = flagged).

    Parameters
    ----------
    ds : xr.Dataset
        Dataset containing reflectance bands and QA_PIXEL.
    qa_var : str
        Name of the QA variable in the dataset.

    Returns
    -------
    xr.Dataset
        Masked dataset with QA band removed.
    """
    if qa_var not in ds:
        logger.warning("QA band '{}' not found in dataset, skipping mask", qa_var)
        return ds

    qa = ds[qa_var].astype(np.uint16)

    # Bit 3: cloud, Bit 4: cloud shadow
    cloud_bit = 1 << 3
    shadow_bit = 1 << 4

    clear_mask = ((qa & cloud_bit) == 0) & ((qa & shadow_bit) == 0)

    masked = ds.drop_vars(qa_var)
    masked = masked.where(clear_mask)

    n_total = clear_mask.size
    n_clear = int(clear_mask.sum().values) if hasattr(clear_mask.sum(), "values") else 0
    pct = (n_clear / n_total * 100) if n_total > 0 else 0
    logger.info("Landsat QA mask applied: {:.1f}% clear pixels", pct)

    return masked


def mask_hls(ds: xr.Dataset, qa_var: str = "qa") -> xr.Dataset:
    """Apply cloud mask to an HLS dataset using the Fmask band.

    HLS Fmask uses the same bit structure as Landsat QA_PIXEL.
    Bit 1 = cloud, Bit 2 = adjacent cloud/shadow, Bit 3 = cloud shadow.

    Parameters
    ----------
    ds : xr.Dataset
        HLS dataset with Fmask band.
    qa_var : str
        Name of the QA/Fmask variable.

    Returns
    -------
    xr.Dataset
        Masked dataset.
    """
    if qa_var not in ds:
        logger.warning("Fmask band '{}' not found in dataset, skipping mask", qa_var)
        return ds

    qa = ds[qa_var].astype(np.uint8)

    # HLS Fmask: bit 1 = cloud, bit 2 = adjacent cloud, bit 3 = cloud shadow
    cloud_bit = 1 << 1
    adjacent_bit = 1 << 2
    shadow_bit = 1 << 3

    clear_mask = (
        ((qa & cloud_bit) == 0)
        & ((qa & adjacent_bit) == 0)
        & ((qa & shadow_bit) == 0)
    )

    masked = ds.drop_vars(qa_var)
    masked = masked.where(clear_mask)

    logger.info("HLS Fmask applied")
    return masked


def compute_clear_percentage(ds: xr.Dataset, reference_var: str | None = None) -> float:
    """Compute the percentage of non-NaN (clear) pixels in a dataset.

    Parameters
    ----------
    ds : xr.Dataset
        A masked dataset.
    reference_var : str, optional
        Variable to use for counting. If None, uses the first variable.

    Returns
    -------
    float
        Percentage of clear pixels (0–100).
    """
    if reference_var is None:
        reference_var = list(ds.data_vars)[0]

    arr = ds[reference_var]
    n_total = arr.size
    n_valid = int(arr.count().values)
    return (n_valid / n_total * 100) if n_total > 0 else 0.0
