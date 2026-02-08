"""Seasonal decomposition and harmonic fitting for vegetation time series."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


def gap_fill_timeseries(
    df: pd.DataFrame,
    value_col: str = "mean",
    date_col: str = "date",
    max_gap_days: int = 30,
) -> pd.DataFrame:
    """Fill gaps in a time series using interpolation and seasonal replacement.

    - Gaps ≤ max_gap_days: linear interpolation
    - Gaps > max_gap_days: same day-of-year seasonal mean replacement

    Parameters
    ----------
    df : pd.DataFrame
        Time series with date and value columns.
    value_col : str
        Column containing the values to gap-fill.
    date_col : str
        Column containing dates.
    max_gap_days : int
        Maximum gap size for linear interpolation.

    Returns
    -------
    pd.DataFrame
        Gap-filled time series with a 'filled' column indicating method used.
    """
    df = df.copy().sort_values(date_col).reset_index(drop=True)
    df[date_col] = pd.to_datetime(df[date_col])

    # Resample to regular interval (e.g., 5-day for HLS revisit)
    df = df.set_index(date_col)
    regular = df[[value_col]].resample("5D").mean()
    regular["filled"] = "observed"
    regular.loc[regular[value_col].isna(), "filled"] = np.nan

    # Identify gap sizes
    is_null = regular[value_col].isna()
    gap_groups = (~is_null).cumsum()

    # Linear interpolation for short gaps
    short_gap_mask = is_null.copy()
    for group_id in gap_groups[is_null].unique():
        group_dates = regular.index[gap_groups == group_id]
        gap_size = (group_dates[-1] - group_dates[0]).days if len(group_dates) > 1 else 0
        if gap_size > max_gap_days:
            short_gap_mask[gap_groups == group_id] = False

    regular.loc[short_gap_mask, value_col] = regular[value_col].interpolate(method="linear")
    regular.loc[short_gap_mask & regular["filled"].isna(), "filled"] = "interpolated"

    # Seasonal mean for remaining gaps
    still_null = regular[value_col].isna()
    if still_null.any():
        doy = regular.index.dayofyear
        seasonal_mean = regular.groupby(doy)[value_col].transform("mean")
        regular.loc[still_null, value_col] = seasonal_mean[still_null]
        regular.loc[still_null & regular["filled"].isna(), "filled"] = "seasonal"

    return regular.reset_index()


def stl_decomposition(
    df: pd.DataFrame,
    value_col: str = "mean",
    period: int = 73,  # ~365 days / 5-day interval
) -> dict[str, pd.Series]:
    """Apply STL (Seasonal-Trend decomposition using LOESS).

    Parameters
    ----------
    df : pd.DataFrame
        Regular time series (gap-filled).
    value_col : str
        Value column.
    period : int
        Seasonal period in number of observations.

    Returns
    -------
    dict
        Keys: "trend", "seasonal", "residual", each as pd.Series.
    """
    from statsmodels.tsa.seasonal import STL

    series = df[value_col].dropna()

    if len(series) < 2 * period:
        logger.warning(
            "Time series too short for STL ({} obs, need {})", len(series), 2 * period
        )
        return {
            "trend": series,
            "seasonal": pd.Series(0, index=series.index),
            "residual": pd.Series(0, index=series.index),
        }

    stl = STL(series, period=period, robust=True)
    result = stl.fit()

    return {
        "trend": result.trend,
        "seasonal": result.seasonal,
        "residual": result.resid,
    }


def harmonic_fit(
    dates: pd.DatetimeIndex,
    values: np.ndarray,
    n_harmonics: int = 2,
) -> dict:
    """Fit a harmonic (Fourier) model to a vegetation time series.

    Model: y(t) = a0 + Σ[a_k * cos(2πk*t/T) + b_k * sin(2πk*t/T)]

    Used for BFAST Monitor-style breakpoint detection: observations
    exceeding 3× RMSE of the fitted model on 3 consecutive dates are flagged.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Observation dates.
    values : np.ndarray
        Observed values.
    n_harmonics : int
        Number of harmonic terms (default 2).

    Returns
    -------
    dict
        Keys: "coefficients", "fitted", "residuals", "rmse"
    """
    # Convert dates to fractional year
    doy = dates.dayofyear.values
    year_fraction = doy / 365.25

    # Build design matrix
    n = len(dates)
    X = np.ones((n, 1 + 2 * n_harmonics))

    for k in range(1, n_harmonics + 1):
        X[:, 2 * k - 1] = np.cos(2 * np.pi * k * year_fraction)
        X[:, 2 * k] = np.sin(2 * np.pi * k * year_fraction)

    # Remove NaN observations
    valid = ~np.isnan(values)
    X_valid = X[valid]
    y_valid = values[valid]

    if len(y_valid) < X.shape[1]:
        logger.warning("Not enough valid observations for harmonic fit")
        return {
            "coefficients": np.zeros(X.shape[1]),
            "fitted": np.full(n, np.nan),
            "residuals": np.full(n, np.nan),
            "rmse": np.nan,
        }

    # Least squares fit
    coeffs, _, _, _ = np.linalg.lstsq(X_valid, y_valid, rcond=None)

    fitted = X @ coeffs
    residuals = values - fitted
    rmse = float(np.sqrt(np.nanmean(residuals**2)))

    return {
        "coefficients": coeffs,
        "fitted": fitted,
        "residuals": residuals,
        "rmse": rmse,
    }


def detect_breaks_harmonic(
    dates: pd.DatetimeIndex,
    values: np.ndarray,
    history_end: str,
    n_harmonics: int = 2,
    threshold_factor: float = 3.0,
    n_consecutive: int = 3,
) -> list[dict]:
    """Simplified BFAST Monitor: detect breakpoints using harmonic model.

    Fits a harmonic model to the historical period, then flags monitoring
    period observations exceeding threshold_factor × RMSE on n_consecutive
    consecutive dates.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Full time series dates.
    values : np.ndarray
        Full time series values.
    history_end : str
        End date of historical (stable) period (YYYY-MM-DD).
    n_harmonics : int
        Number of harmonics for the model.
    threshold_factor : float
        Multiplier for RMSE threshold (default 3.0).
    n_consecutive : int
        Required consecutive anomalies to confirm break (default 3).

    Returns
    -------
    list[dict]
        Detected breaks with keys: "date", "value", "expected", "anomaly".
    """
    history_mask = dates <= pd.Timestamp(history_end)
    monitor_mask = ~history_mask

    # Fit model on history
    fit = harmonic_fit(dates[history_mask], values[history_mask], n_harmonics)

    if np.isnan(fit["rmse"]):
        return []

    threshold = threshold_factor * fit["rmse"]

    # Predict for monitoring period
    monitor_dates = dates[monitor_mask]
    monitor_values = values[monitor_mask]

    doy = monitor_dates.dayofyear.values
    year_fraction = doy / 365.25
    n = len(monitor_dates)
    X = np.ones((n, 1 + 2 * n_harmonics))
    for k in range(1, n_harmonics + 1):
        X[:, 2 * k - 1] = np.cos(2 * np.pi * k * year_fraction)
        X[:, 2 * k] = np.sin(2 * np.pi * k * year_fraction)

    expected = X @ fit["coefficients"]
    anomalies = monitor_values - expected

    # Find consecutive anomalies exceeding threshold
    is_anomaly = np.abs(anomalies) > threshold
    breaks = []

    consecutive_count = 0
    for i in range(len(monitor_dates)):
        if is_anomaly[i] and not np.isnan(monitor_values[i]):
            consecutive_count += 1
            if consecutive_count >= n_consecutive:
                break_idx = i - n_consecutive + 1
                breaks.append(
                    {
                        "date": str(monitor_dates[break_idx].date()),
                        "value": float(monitor_values[break_idx]),
                        "expected": float(expected[break_idx]),
                        "anomaly": float(anomalies[break_idx]),
                    }
                )
                consecutive_count = 0
        else:
            consecutive_count = 0

    logger.info("Detected {} breakpoints in monitoring period", len(breaks))
    return breaks
