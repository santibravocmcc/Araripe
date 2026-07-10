#!/usr/bin/env python3
"""Select the climatologically most "normal" years for the detection baseline.

Two expert reviewers recommended (a) widening the spectral baseline from 3 to at
least 5 years, and (b) choosing those years to *minimise* climate anomalies —
in particular avoiding strong El Niño / La Niña years, which depress or inflate
vegetation-moisture signals across the Caatinga/Cerrado and would bias a
z-score baseline.

This script makes that choice reproducible. For each candidate year it computes:

  1. ENSO severity  — the peak absolute Oceanic Niño Index (ONI) reached during
                       the year, from the official NOAA CPC ONI table (embedded
                       below; refresh with --refresh-oni). This is the dominant
                       driver of inter-annual rainfall anomalies in NE Brazil.
  2. Rainfall anomaly — the standardised anomaly of annual AOI-mean CHIRPS
                       precipitation vs. the available reference record.

It combines them into a single anomaly score, ranks the candidate years, and
recommends the N most recent years whose ENSO severity stays below a threshold
(i.e. the most recent *quiet* years). Sentinel-2 only provides dense coverage
from ~2017 (S2A 2015-06, S2B 2017-03), so the default candidate floor is 2017.

Usage:
    python scripts/select_baseline_years.py                 # default: 5 yrs, S2 era
    python scripts/select_baseline_years.py --n 5 --max-severity 1.5
    python scripts/select_baseline_years.py --refresh-oni   # pull latest ONI table
    python scripts/select_baseline_years.py --json out.json

Data sources & definitions:
  - ONI (3-month running mean of ERSSTv5 SST anomalies in the Niño-3.4 region):
    https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
    Event convention: |ONI| >= 0.5 for 5+ overlapping seasons = El Niño / La Niña.
    Severity bands used here: <0.5 neutral, 0.5-1.0 weak, 1.0-1.5 moderate,
    1.5-2.0 strong, >=2.0 very strong.
  - CHIRPS v2.0 monthly precipitation (0.05°), cropped to the AOI bbox. Files are
    expected in data/chirps/ as chirps-v2.0.YYYY.MM.tif (see scripts download_baseline_data.py).
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import click
import numpy as np

# ── Embedded NOAA CPC ONI table (SEAS, YEAR, ANOM) ────────────────────────────
# Snapshot fetched 2026-07 from cpc.ncep.noaa.gov/data/indices/oni.ascii.txt.
# Each YEAR groups the 12 overlapping 3-month seasons centred in that year.
# Refresh with --refresh-oni (falls back to this snapshot if offline).
_ONI_SNAPSHOT = """
DJF 2015 0.69 | JFM 2015 0.61 | FMA 2015 0.65 | MAM 2015 0.81 | AMJ 2015 1.02 | MJJ 2015 1.25 | JJA 2015 1.57 | JAS 2015 1.91 | ASO 2015 2.21 | SON 2015 2.47 | OND 2015 2.64 | NDJ 2015 2.75
DJF 2016 2.63 | JFM 2016 2.28 | FMA 2016 1.71 | MAM 2016 1.05 | AMJ 2016 0.49 | MJJ 2016 0.00 | JJA 2016 -0.31 | JAS 2016 -0.50 | ASO 2016 -0.58 | SON 2016 -0.64 | OND 2016 -0.60 | NDJ 2016 -0.45
DJF 2017 -0.19 | JFM 2017 -0.02 | FMA 2017 0.18 | MAM 2017 0.31 | AMJ 2017 0.40 | MJJ 2017 0.39 | JJA 2017 0.19 | JAS 2017 -0.07 | ASO 2017 -0.34 | SON 2017 -0.60 | OND 2017 -0.77 | NDJ 2017 -0.86
DJF 2018 -0.77 | JFM 2018 -0.71 | FMA 2018 -0.57 | MAM 2018 -0.39 | AMJ 2018 -0.13 | MJJ 2018 0.06 | JJA 2018 0.14 | JAS 2018 0.27 | ASO 2018 0.53 | SON 2018 0.81 | OND 2018 0.97 | NDJ 2018 0.92
DJF 2019 0.89 | JFM 2019 0.86 | FMA 2019 0.84 | MAM 2019 0.77 | AMJ 2019 0.64 | MJJ 2019 0.52 | JJA 2019 0.33 | JAS 2019 0.19 | ASO 2019 0.23 | SON 2019 0.39 | OND 2019 0.58 | NDJ 2019 0.66
DJF 2020 0.64 | JFM 2020 0.63 | FMA 2020 0.53 | MAM 2020 0.30 | AMJ 2020 0.01 | MJJ 2020 -0.23 | JJA 2020 -0.36 | JAS 2020 -0.53 | ASO 2020 -0.85 | SON 2020 -1.12 | OND 2020 -1.20 | NDJ 2020 -1.08
DJF 2021 -0.91 | JFM 2021 -0.79 | FMA 2021 -0.71 | MAM 2021 -0.55 | AMJ 2021 -0.39 | MJJ 2021 -0.30 | JJA 2021 -0.35 | JAS 2021 -0.45 | ASO 2021 -0.63 | SON 2021 -0.76 | OND 2021 -0.91 | NDJ 2021 -0.87
DJF 2022 -0.82 | JFM 2022 -0.79 | FMA 2022 -0.86 | MAM 2022 -0.95 | AMJ 2022 -0.90 | MJJ 2022 -0.78 | JJA 2022 -0.76 | JAS 2022 -0.87 | ASO 2022 -0.97 | SON 2022 -0.94 | OND 2022 -0.85 | NDJ 2022 -0.71
DJF 2023 -0.54 | JFM 2023 -0.29 | FMA 2023 -0.02 | MAM 2023 0.27 | AMJ 2023 0.57 | MJJ 2023 0.84 | JJA 2023 1.12 | JAS 2023 1.37 | ASO 2023 1.60 | SON 2023 1.83 | OND 2023 1.99 | NDJ 2023 2.06
DJF 2024 1.92 | JFM 2024 1.62 | FMA 2024 1.26 | MAM 2024 0.82 | AMJ 2024 0.49 | MJJ 2024 0.22 | JJA 2024 0.08 | JAS 2024 -0.07 | ASO 2024 -0.17 | SON 2024 -0.21 | OND 2024 -0.30 | NDJ 2024 -0.42
DJF 2025 -0.45 | JFM 2025 -0.24 | FMA 2025 -0.06 | MAM 2025 0.02 | AMJ 2025 -0.02 | MJJ 2025 -0.04 | JJA 2025 -0.14 | JAS 2025 -0.28 | ASO 2025 -0.40 | SON 2025 -0.51 | OND 2025 -0.55 | NDJ 2025 -0.54
DJF 2026 -0.37 | JFM 2026 -0.14 | FMA 2026 0.13 | MAM 2026 0.51 | AMJ 2026 0.98
"""

AOI_BBOX = [-40.0, -8.0, -39.0, -7.0]  # matches config.settings.AOI_BBOX
CHIRPS_DIR = Path("data/chirps")
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"


def parse_oni(text: str) -> dict[int, list[float]]:
    """Parse an ONI table into {year: [anomalies...]} (all seasons of that year)."""
    by_year: dict[int, list[float]] = {}
    # Accept both the snapshot ("SEAS YR ANOM | ...") and the NOAA ascii layout.
    tokens = re.findall(r"[A-Z]{3}\s+(\d{4})\s+(-?\d+\.\d+)", text)
    for yr, anom in tokens:
        by_year.setdefault(int(yr), []).append(float(anom))
    return by_year


def fetch_oni() -> dict[int, list[float]]:
    """Try to fetch the live ONI table; fall back to the embedded snapshot."""
    try:
        import urllib.request
        with urllib.request.urlopen(ONI_URL, timeout=20) as r:
            text = r.read().decode()
        parsed = parse_oni(text)
        if parsed:
            print(f"  ONI: fetched live table ({min(parsed)}–{max(parsed)}).")
            return parsed
    except Exception as e:  # offline / blocked → snapshot
        print(f"  ONI: live fetch failed ({e}); using embedded snapshot.")
    return parse_oni(_ONI_SNAPSHOT)


def enso_state(peak_signed: float) -> str:
    """Classify a year by its peak signed ONI."""
    if peak_signed >= 0.5:
        return "El Nino"
    if peak_signed <= -0.5:
        return "La Nina"
    return "Neutral"


def severity_band(sev: float) -> str:
    if sev < 0.5:
        return "neutral"
    if sev < 1.0:
        return "weak"
    if sev < 1.5:
        return "moderate"
    if sev < 2.0:
        return "strong"
    return "very strong"


def chirps_annual_precip(year: int, bbox=AOI_BBOX, chirps_dir=CHIRPS_DIR):
    """AOI-mean annual precipitation (mm) for `year`, or None if <12 months."""
    import rasterio
    from rasterio.windows import from_bounds
    months = {}
    for f in sorted(glob.glob(str(chirps_dir / f"chirps-v2.0.{year}.*.tif"))):
        m = re.search(rf"{year}\.(\d{{2}})\.tif$", f)
        if not m:
            continue
        with rasterio.open(f) as src:
            w = from_bounds(*bbox, src.transform)
            a = src.read(1, window=w).astype("float64")
        a = np.where(a < 0, np.nan, a)
        months[int(m.group(1))] = float(np.nanmean(a))
    if len(months) < 12:
        return None if months else None
    return sum(months.values())


@click.command()
@click.option("--n", default=5, help="Number of baseline years to recommend.")
@click.option("--min-year", default=2017, help="Earliest candidate year (Sentinel-2 era).")
@click.option("--max-year", default=None, type=int, help="Latest candidate year (default: latest complete).")
@click.option("--max-severity", default=1.5, type=float,
              help="Exclude years whose peak |ONI| >= this (default 1.5 = drop strong events).")
@click.option("--w-enso", default=1.0, type=float, help="Weight on ENSO severity in the score.")
@click.option("--w-precip", default=0.5, type=float, help="Weight on rainfall anomaly in the score.")
@click.option("--refresh-oni", is_flag=True, help="Fetch the latest ONI table (else use snapshot).")
@click.option("--json", "json_out", default=None, type=click.Path(), help="Write the ranking as JSON.")
def main(n, min_year, max_year, max_severity, w_enso, w_precip, refresh_oni, json_out):
    """Rank candidate years by climate anomaly and recommend a baseline set."""
    print("Loading ONI table...")
    oni = fetch_oni() if refresh_oni else parse_oni(_ONI_SNAPSHOT)

    now_year = 2026
    hi = max_year or (now_year - 1)
    candidates = [y for y in range(min_year, hi + 1) if y in oni]

    # Rainfall reference: complete CHIRPS years in the local cache.
    precip = {y: chirps_annual_precip(y) for y in range(min_year, hi + 2)}
    complete = {y: v for y, v in precip.items() if v is not None}
    if len(complete) >= 2:
        pmean = float(np.mean(list(complete.values())))
        pstd = float(np.std(list(complete.values())))
    else:
        pmean, pstd = None, None
    print(f"  CHIRPS complete years for rainfall normal: {sorted(complete)} "
          f"(mean={pmean:.0f} mm)" if pmean else "  CHIRPS: insufficient local data for rainfall anomaly")

    rows = []
    for y in candidates:
        seasons = oni[y]
        peak_signed = max(seasons, key=abs)
        severity = abs(peak_signed)
        p = precip.get(y)
        if pmean and pstd and p is not None:
            precip_z = (p - pmean) / pstd if pstd > 0 else 0.0
        else:
            precip_z = None
        score = w_enso * severity + (w_precip * abs(precip_z) if precip_z is not None else 0.0)
        rows.append({
            "year": y,
            "enso_state": enso_state(peak_signed),
            "oni_peak": round(peak_signed, 2),
            "severity": round(severity, 2),
            "band": severity_band(severity),
            "annual_precip_mm": round(p, 1) if p is not None else None,
            "precip_z": round(precip_z, 2) if precip_z is not None else None,
            "score": round(score, 3),
            "eligible": severity < max_severity,
        })

    # Recommendation: most recent `n` eligible years (quiet years, recent-first).
    eligible_recent = sorted([r for r in rows if r["eligible"]],
                             key=lambda r: -r["year"])[:n]
    recommended = sorted(r["year"] for r in eligible_recent)
    # Also compute the strictly least-anomalous n (by score) for comparison.
    least_anom = sorted(sorted(rows, key=lambda r: r["score"])[:n], key=lambda r: r["year"])

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n── Candidate years (Sentinel-2 era) ─────────────────────────────────")
    print(f"{'year':>4} {'ENSO':<9} {'ONIpk':>6} {'severity':>9} {'precip_mm':>9} "
          f"{'precip_z':>8} {'score':>6} {'elig':>5}")
    for r in sorted(rows, key=lambda r: r["year"]):
        print(f"{r['year']:>4} {r['enso_state']:<9} {r['oni_peak']:>6.2f} "
              f"{r['severity']:>6.2f} ({r['band'][:4]}) "
              f"{(r['annual_precip_mm'] or float('nan')):>9.1f} "
              f"{('' if r['precip_z'] is None else f'{r['precip_z']:>8.2f}'):>8} "
              f"{r['score']:>6.2f} {'yes' if r['eligible'] else 'NO':>5}")

    print(f"\nRECOMMENDED baseline ({n} most-recent quiet years, |ONI|<{max_severity}): "
          f"{recommended}")
    print(f"Least-anomalous {n} by score (any recency):            {least_anom and [r['year'] for r in least_anom]}")
    excluded = [r["year"] for r in rows if not r["eligible"]]
    print(f"Excluded (strong ENSO, |ONI|>={max_severity}):          {excluded}")

    result = {
        "params": {"n": n, "min_year": min_year, "max_year": hi,
                   "max_severity": max_severity, "w_enso": w_enso, "w_precip": w_precip},
        "candidates": rows,
        "recommended_recent_quiet": recommended,
        "least_anomalous_by_score": [r["year"] for r in least_anom],
        "excluded_strong_enso": excluded,
    }
    if json_out:
        Path(json_out).write_text(json.dumps(result, indent=2))
        print(f"\nWrote {json_out}")
    return result


if __name__ == "__main__":
    main()
