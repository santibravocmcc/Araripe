"""Change detection using z-score anomaly detection and multi-index confirmation."""

from __future__ import annotations

import numpy as np
import xarray as xr
from loguru import logger

from config.settings import (
    DELTA_THRESHOLD_HIGH,
    DELTA_THRESHOLD_LOW,
    DELTA_THRESHOLD_MEDIUM,
    DNBR_HIGH_SEVERITY,
    DNBR_LOW_SEVERITY,
    DROUGHT_Z_ADJUSTMENT,
    NBR_POST_FIRE_THRESHOLD,
    SPI_DROUGHT_THRESHOLD,
    Z_THRESHOLD_HIGH,
    Z_THRESHOLD_LOW,
    Z_THRESHOLD_MEDIUM,
)
from src.detection.baseline import compute_delta, compute_zscore


def detect_deforestation(
    current_indices: xr.Dataset,
    baseline_means: dict[str, xr.DataArray],
    baseline_stds: dict[str, xr.DataArray],
    spi_3month: float | None = None,
) -> xr.Dataset:
    """Run the full deforestation detection pipeline.

    Computes z-scores and deltas for each index, then classifies pixels
    into confidence levels based on multi-index agreement.

    Parameters
    ----------
    current_indices : xr.Dataset
        Current observation indices (e.g., ndmi, nbr, evi2).
    baseline_means : dict[str, xr.DataArray]
        Monthly baseline means keyed by index name.
    baseline_stds : dict[str, xr.DataArray]
        Monthly baseline stds keyed by index name.
    spi_3month : float, optional
        3-month Standardized Precipitation Index. When < -1.0, thresholds
        are widened to reduce false positives during drought.

    Returns
    -------
    xr.Dataset
        Dataset containing:
        - z_{index}: z-scores for each index
        - delta_{index}: deltas for each index
        - confidence: 0 (none), 1 (low), 2 (medium), 3 (high)
        - is_alert: boolean mask of any detection
    """
    # Adjust thresholds during drought
    z_adj = 0.0
    if spi_3month is not None and spi_3month < SPI_DROUGHT_THRESHOLD:
        z_adj = DROUGHT_Z_ADJUSTMENT
        logger.warning(
            "Drought detected (SPI={:.2f}), widening z-thresholds by {:.1f}σ",
            spi_3month,
            z_adj,
        )

    z_high = Z_THRESHOLD_HIGH - z_adj
    z_med = Z_THRESHOLD_MEDIUM - z_adj
    z_low = Z_THRESHOLD_LOW - z_adj

    results = {}
    z_flags = {}
    delta_flags = {}

    available_indices = [
        name for name in current_indices.data_vars
        if name in baseline_means
    ]

    for idx_name in available_indices:
        current = current_indices[idx_name]
        mean = baseline_means[idx_name]
        std = baseline_stds[idx_name]

        z = compute_zscore(current, mean, std)
        d = compute_delta(current, mean)

        results[f"z_{idx_name}"] = z
        results[f"delta_{idx_name}"] = d

        # Flag pixels exceeding thresholds
        z_flags[idx_name] = z < z_low
        delta_flags[idx_name] = d < DELTA_THRESHOLD_LOW

    # ─── Confidence classification ────────────────────────────────────────
    # Start with zeros (no alert)
    reference = list(results.values())[0]
    confidence = xr.zeros_like(reference, dtype=np.int8)

    # Moisture indices for multi-index confirmation
    moisture_indices = [n for n in available_indices if n in ("ndmi", "nbr")]
    all_indices = available_indices

    # High confidence: z < -3.0 AND delta < -0.20 in BOTH NDMI and NBR
    if len(moisture_indices) >= 2:
        high_z = True
        high_d = True
        for idx_name in moisture_indices:
            high_z = high_z & (results[f"z_{idx_name}"] < z_high)
            high_d = high_d & (results[f"delta_{idx_name}"] < DELTA_THRESHOLD_HIGH)
        confidence = confidence.where(~(high_z & high_d), other=3)

    # Medium confidence: z < -2.5 OR delta < -0.15 in at least one moisture index
    for idx_name in moisture_indices:
        z_med_flag = results[f"z_{idx_name}"] < z_med
        d_med_flag = results[f"delta_{idx_name}"] < DELTA_THRESHOLD_MEDIUM
        med_flag = z_med_flag | d_med_flag
        confidence = confidence.where(~((confidence < 2) & med_flag), other=2)

    # Low confidence: z < -2.0 in any single index
    for idx_name in all_indices:
        low_flag = results[f"z_{idx_name}"] < z_low
        confidence = confidence.where(~((confidence < 1) & low_flag), other=1)

    confidence.name = "confidence"
    results["confidence"] = confidence
    results["is_alert"] = confidence > 0

    n_alerts = int(results["is_alert"].sum().values)
    n_high = int((confidence == 3).sum().values)
    n_med = int((confidence == 2).sum().values)
    n_low = int((confidence == 1).sum().values)
    logger.info(
        "Detection complete: {} alerts (high={}, medium={}, low={})",
        n_alerts, n_high, n_med, n_low,
    )

    return xr.Dataset(results)


def classify_fire_vs_mechanical(
    nbr_pre: xr.DataArray,
    nbr_post: xr.DataArray,
    bsi_post: xr.DataArray,
) -> xr.DataArray:
    """Distinguish fire-related clearing from mechanical clearing.

    Fire signature: dNBR > 0.27 with NBR post-event < 0.1
    Mechanical clearing: high BSI without charcoal signature

    Parameters
    ----------
    nbr_pre : xr.DataArray
        NBR before the detected change.
    nbr_post : xr.DataArray
        NBR after the detected change.
    bsi_post : xr.DataArray
        BSI after the detected change.

    Returns
    -------
    xr.DataArray
        Classification: 0=no clearing, 1=fire, 2=mechanical, 3=uncertain
    """
    from src.processing.indices import dnbr

    d_nbr = dnbr(nbr_pre, nbr_post)

    classification = xr.zeros_like(d_nbr, dtype=np.int8)

    # Fire: high dNBR + low post-fire NBR
    fire_mask = (d_nbr > DNBR_LOW_SEVERITY) & (nbr_post < NBR_POST_FIRE_THRESHOLD)
    classification = classification.where(~fire_mask, other=1)

    # Mechanical: high BSI without fire signature
    mechanical_mask = (bsi_post > 0.1) & (~fire_mask) & (d_nbr > 0.05)
    classification = classification.where(~mechanical_mask, other=2)

    # Uncertain: some change detected but doesn't clearly match either pattern
    uncertain_mask = (d_nbr > 0.1) & (classification == 0)
    classification = classification.where(~uncertain_mask, other=3)

    classification.name = "clearing_type"
    return classification
