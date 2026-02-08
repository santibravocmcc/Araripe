"""Trend analysis: Mann-Kendall test and Sen's slope for vegetation time series."""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats


def mann_kendall_test(values: np.ndarray) -> dict:
    """Perform the Mann-Kendall trend test.

    Tests for monotonic trend in a time series.

    Parameters
    ----------
    values : np.ndarray
        Time series values (NaN allowed, will be removed).

    Returns
    -------
    dict
        Keys: "tau" (Kendall's tau), "p_value", "trend" (str),
        "significant" (bool at α=0.05), "n" (sample size).
    """
    clean = values[~np.isnan(values)]
    n = len(clean)

    if n < 4:
        logger.warning("Too few observations for Mann-Kendall (n={})", n)
        return {
            "tau": 0.0,
            "p_value": 1.0,
            "trend": "insufficient_data",
            "significant": False,
            "n": n,
        }

    # Compute S statistic
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = clean[j] - clean[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    # Kendall's tau
    tau = s / (n * (n - 1) / 2)

    # Variance of S (corrected for ties)
    unique, counts = np.unique(clean, return_counts=True)
    tied_groups = counts[counts > 1]

    var_s = (n * (n - 1) * (2 * n + 5)) / 18
    if len(tied_groups) > 0:
        for t in tied_groups:
            var_s -= t * (t - 1) * (2 * t + 5) / 18

    # Z-score
    if s > 0:
        z = (s - 1) / np.sqrt(var_s) if var_s > 0 else 0
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s) if var_s > 0 else 0
    else:
        z = 0

    p_value = 2 * (1 - stats.norm.cdf(abs(z)))

    # Determine trend direction
    significant = p_value < 0.05
    if significant:
        trend = "increasing" if tau > 0 else "decreasing"
    else:
        trend = "no_trend"

    return {
        "tau": float(tau),
        "p_value": float(p_value),
        "trend": trend,
        "significant": significant,
        "n": n,
    }


def sens_slope(dates: pd.DatetimeIndex, values: np.ndarray) -> dict:
    """Compute Sen's slope estimator (Theil-Sen) for a time series.

    The slope is the median of all pairwise slopes, making it robust
    to outliers.

    Parameters
    ----------
    dates : pd.DatetimeIndex
        Observation dates.
    values : np.ndarray
        Observed values.

    Returns
    -------
    dict
        Keys: "slope" (per year), "intercept", "lower_ci", "upper_ci"
        (95% confidence interval for slope).
    """
    valid = ~np.isnan(values)
    clean_dates = dates[valid]
    clean_values = values[valid]
    n = len(clean_values)

    if n < 3:
        return {
            "slope": 0.0,
            "intercept": 0.0,
            "lower_ci": 0.0,
            "upper_ci": 0.0,
        }

    # Convert dates to fractional years
    t = np.array([
        (d - clean_dates[0]).total_seconds() / (365.25 * 86400)
        for d in clean_dates
    ])

    # Compute all pairwise slopes
    slopes = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            dt = t[j] - t[i]
            if dt > 0:
                slopes.append((clean_values[j] - clean_values[i]) / dt)

    if not slopes:
        return {"slope": 0.0, "intercept": 0.0, "lower_ci": 0.0, "upper_ci": 0.0}

    slopes = np.array(slopes)
    median_slope = float(np.median(slopes))

    # Intercept: median of (y_i - slope * t_i)
    intercepts = clean_values - median_slope * t
    intercept = float(np.median(intercepts))

    # 95% confidence interval for slope
    z_alpha = 1.96
    c_alpha = z_alpha * np.sqrt(n * (n - 1) * (2 * n + 5) / 18)
    m1 = int((len(slopes) - c_alpha) / 2)
    m2 = int((len(slopes) + c_alpha) / 2)

    sorted_slopes = np.sort(slopes)
    lower = float(sorted_slopes[max(0, m1)])
    upper = float(sorted_slopes[min(len(sorted_slopes) - 1, m2)])

    return {
        "slope": median_slope,
        "intercept": intercept,
        "lower_ci": lower,
        "upper_ci": upper,
    }


def analyze_trend(
    df: pd.DataFrame,
    value_col: str = "mean",
    date_col: str = "date",
) -> dict:
    """Run full trend analysis on a time series DataFrame.

    Combines Mann-Kendall test and Sen's slope estimation.

    Parameters
    ----------
    df : pd.DataFrame
        Time series with date and value columns.
    value_col : str
        Value column name.
    date_col : str
        Date column name.

    Returns
    -------
    dict
        Combined results from Mann-Kendall and Sen's slope.
    """
    df = df.sort_values(date_col).reset_index(drop=True)
    dates = pd.DatetimeIndex(df[date_col])
    values = df[value_col].values

    mk = mann_kendall_test(values)
    ss = sens_slope(dates, values)

    result = {
        "mann_kendall": mk,
        "sens_slope": ss,
        "summary": {
            "trend": mk["trend"],
            "significant": mk["significant"],
            "slope_per_year": ss["slope"],
            "n_observations": mk["n"],
        },
    }

    logger.info(
        "Trend analysis: {} (τ={:.3f}, p={:.4f}, slope={:.4f}/yr)",
        mk["trend"],
        mk["tau"],
        mk["p_value"],
        ss["slope"],
    )

    return result
