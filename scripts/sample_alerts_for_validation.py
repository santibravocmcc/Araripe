"""Build a stratified sample of alerts for independent accuracy validation.

Accuracy of the deforestation alerts cannot be established by code alone: it
requires human visual interpretation of independent reference imagery. This
script builds the *infrastructure* for that assessment — it does NOT invent
accuracy numbers.

What it does:
  1. Loads the alert archive (data/alerts/*.geojson).
  2. Draws a stratified random sample, stratified by confidence level
     (high/medium/low) and, when present, by dominant land-cover group
     (lc_group). Stratification ensures each confidence tier is represented so
     per-tier commission rates can be estimated.
  3. Optionally renders a Sentinel-2 RGB reference chip per sampled alert
     (least-cloudy scene near the detection date) with the alert polygon
     overlaid, for side-by-side visual judgement (--chips).
  4. Writes a CSV with one row per sampled alert and an empty ``verdict`` column
     for the human interpreter to fill: TP (true positive), FP (false positive),
     or UNC (uncertain).

Computing accuracy from the filled sheet (documented, not automated here):
  * Commission error (false-positive rate) per confidence tier =
        FP_tier / (TP_tier + FP_tier)      # UNC excluded or reported separately
  * User's accuracy per tier = 1 − commission = TP_tier / (TP_tier + FP_tier).
  * Omission error requires an INDEPENDENT reference set of *known* clearings
    (e.g. PRODES/DETER polygons or manually digitized clearings) that is NOT
    derived from these alerts; then
        omission = missed_reference / total_reference,
        producer's accuracy = 1 − omission.
    This script samples *alerts* (the detected set) so it supports commission
    directly; omission needs that separate reference layer (a documented,
    human-driven follow-up — see AUDITORIA_TECNICA.md Task 4).

Usage:
    python scripts/sample_alerts_for_validation.py --per-stratum 15
    python scripts/sample_alerts_for_validation.py --date 2026-02-01 --chips
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import geopandas as gpd
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ALERTS_DIR

# Deterministic sampling: seed is fixed and printed so the sample is reproducible
# (Math.random-style nondeterminism would make the audit trail irreproducible).
DEFAULT_SEED = 42


def _confidence_label(row) -> str:
    if "confidence_label" in row and isinstance(row["confidence_label"], str):
        return row["confidence_label"]
    conf = row.get("confidence")
    return {3: "high", 2: "medium", 1: "low"}.get(int(conf) if conf == conf else 0, "unknown")


def _load_alerts(alerts_dir: Path, date: str | None) -> gpd.GeoDataFrame:
    if date:
        f = alerts_dir / f"alerts_{date}.geojson"
        if not f.exists():
            raise SystemExit(f"No alert file for {date}")
        gdf = gpd.read_file(str(f))
        gdf["source_file"] = f.name
        return gdf
    frames = []
    for f in sorted(alerts_dir.glob("alerts_*.geojson")):
        g = gpd.read_file(str(f))
        g["source_file"] = f.name
        frames.append(g)
    if not frames:
        raise SystemExit(f"No alerts_*.geojson in {alerts_dir}")
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)


def _render_chip(row, out_png: Path, buffer_m: float = 300.0) -> bool:
    """Render an S2 RGB reference chip with the alert polygon overlaid.

    Returns True on success. Requires network (STAC). Best-effort: any failure
    returns False and is logged, so the CSV is still produced without chips.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import rioxarray  # noqa: F401
        from pystac_client import Client
        from shapely.geometry import shape

        geom = row.geometry
        c = geom.centroid
        # small bbox around the alert (WGS84 degrees ~ buffer_m)
        d = buffer_m / 111_000.0
        bbox = [c.x - d, c.y - d, c.x + d, c.y + d]
        date = str(row.get("detection_date") or "")[:10]
        if not date:
            return False
        # search a +-20 day window, least cloud
        from datetime import date as _date, timedelta
        y, m, dd = (int(x) for x in date.split("-"))
        lo = (_date(y, m, dd) - timedelta(days=20)).isoformat()
        hi = (_date(y, m, dd) + timedelta(days=20)).isoformat()
        cl = Client.open("https://earth-search.aws.element84.com/v1")
        items = list(cl.search(collections=["sentinel-2-l2a"], bbox=bbox,
                               datetime=f"{lo}/{hi}",
                               query={"eo:cloud_cover": {"lt": 30}},
                               sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
                               limit=1).items())
        if not items:
            return False
        href = items[0].assets["visual"].href
        import rioxarray
        da = rioxarray.open_rasterio(href)
        da = da.rio.clip_box(*bbox, crs="EPSG:4326")
        rgb = np.moveaxis(da.values[:3], 0, -1).astype("float32")
        rgb = np.clip(rgb / max(1.0, float(np.nanpercentile(rgb, 98))), 0, 1)
        fig, ax = plt.subplots(figsize=(4, 4))
        ext = [float(da.x.min()), float(da.x.max()), float(da.y.min()), float(da.y.max())]
        ax.imshow(rgb, extent=[da.x.min(), da.x.max(), da.y.min(), da.y.max()])
        gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(da.rio.crs).boundary.plot(
            ax=ax, color="red", linewidth=1.5)
        ax.set_title(f"{date}  conf={_confidence_label(row)}", fontsize=8)
        ax.axis("off")
        fig.savefig(str(out_png), dpi=120, bbox_inches="tight")
        plt.close(fig)
        return True
    except Exception as e:
        logger.warning("Chip render failed for alert: {}", e)
        return False


@click.command()
@click.option("--alerts-dir", default=str(ALERTS_DIR))
@click.option("--date", default=None, help="Single date (YYYY-MM-DD). Default: all.")
@click.option("--per-stratum", default=15, help="Samples per (confidence[,lc_group]) stratum.")
@click.option("--seed", default=DEFAULT_SEED, help="Random seed (printed for reproducibility).")
@click.option("--chips/--no-chips", default=False, help="Render S2 RGB reference chips (needs network).")
@click.option("--out-dir", default="data/validation", help="Output directory.")
def main(alerts_dir, date, per_stratum, seed, chips, out_dir):
    adir = Path(alerts_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chips_dir = out / "chips"
    if chips:
        chips_dir.mkdir(parents=True, exist_ok=True)

    gdf = _load_alerts(adir, date)
    gdf = gdf.reset_index(drop=True)
    gdf["conf_tier"] = gdf.apply(_confidence_label, axis=1)
    strat_cols = ["conf_tier"]
    if "lc_group" in gdf.columns:
        strat_cols.append("lc_group")
    logger.info("Loaded {} alerts; stratifying by {}", len(gdf), strat_cols)

    # Stratified sample (deterministic)
    sampled = (
        gdf.groupby(strat_cols, dropna=False, group_keys=False)
        .apply(lambda g: g.sample(min(len(g), per_stratum), random_state=seed))
        .reset_index(drop=True)
    )
    logger.info("Sampled {} alerts across {} strata (seed={})",
                len(sampled), sampled.groupby(strat_cols).ngroups, seed)

    # Build the CSV for human judgement. Compute centroids in a metric CRS
    # (avoids the geographic-CRS centroid warning), then report as lon/lat.
    cent = sampled.geometry.to_crs("EPSG:32724").centroid.to_crs("EPSG:4326")
    rows = []
    for i, (_, r) in enumerate(sampled.iterrows()):
        chip_name = f"chip_{i:04d}.png"
        chip_ok = False
        if chips:
            # _render_chip expects a WGS84 geometry (it works in lon/lat degrees).
            r_wgs = r.copy()
            r_wgs["geometry"] = gpd.GeoSeries([r.geometry], crs=sampled.crs).to_crs("EPSG:4326").iloc[0]
            chip_ok = _render_chip(r_wgs, chips_dir / chip_name)
        rows.append({
            "sample_id": i,
            "source_file": r.get("source_file", ""),
            "detection_date": r.get("detection_date", ""),
            "confidence": _confidence_label(r),
            "lc_group": r.get("lc_group", ""),
            "lc_natural_frac": r.get("lc_natural_frac", ""),
            "clearing_type": r.get("clearing_type", ""),
            "persistence_status": r.get("persistence_status", ""),
            "area_ha": r.get("area_ha", ""),
            "centroid_lat": round(float(cent.iloc[i].y), 6),
            "centroid_lon": round(float(cent.iloc[i].x), 6),
            "chip": (f"chips/{chip_name}" if chip_ok else ""),
            "verdict": "",       # human fills: TP | FP | UNC
            "notes": "",         # human free text
        })

    csv_path = out / "validation_sample.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    sampled.to_file(str(out / "validation_sample.geojson"), driver="GeoJSON")

    print(f"\nWrote {len(rows)} rows -> {csv_path}")
    print(f"Sample geometries -> {out / 'validation_sample.geojson'}")
    if chips:
        print(f"Reference chips -> {chips_dir}")
    print("\nNEXT (human step, NOT automated): open validation_sample.csv, inspect each")
    print("alert against its chip (or in QGIS with high-res imagery), and set verdict to")
    print("TP / FP / UNC. Then per-confidence commission = FP/(TP+FP). Omission needs an")
    print("independent reference clearing layer (see the module docstring).")


if __name__ == "__main__":
    main()
