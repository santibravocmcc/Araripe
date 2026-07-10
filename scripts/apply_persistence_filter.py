"""Re-evaluate the existing alert archive under the temporal-persistence rule.

Walks ``data/alerts/alerts_YYYY-MM-DD.geojson`` in chronological order and,
for each observation, keeps only the alerts confirmed by the preceding
observation(s) (``>=2 consecutive independent observations``; see
src/detection/persistence.py). Prints a before/after count table so the effect
of persistence on the historical archive is explicit, and — with ``--write`` —
saves the confirmed subsets to ``data/alerts/persistent/``.

This operates purely on the saved GeoJSONs (no imagery re-streaming), which is
what makes the historical before/after comparison reproducible offline.

Usage:
    python scripts/apply_persistence_filter.py
    python scripts/apply_persistence_filter.py --min-consecutive 2 --write
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import geopandas as gpd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ALERTS_DIR
from src.detection.persistence import (
    DEFAULT_MIN_OVERLAP_FRAC,
    apply_persistence_to_history,
)


def _date_from_name(path: Path) -> str:
    # alerts_2025-11-28.geojson -> 2025-11-28
    return path.stem.replace("alerts_", "")


@click.command()
@click.option("--alerts-dir", default=str(ALERTS_DIR), help="Directory of alerts_*.geojson.")
@click.option("--min-consecutive", default=2, help="Consecutive observations required (>=2).")
@click.option("--min-overlap-frac", default=DEFAULT_MIN_OVERLAP_FRAC,
              help="Min overlap (fraction of current alert area) with a previous observation.")
@click.option("--write/--no-write", default=False,
              help="Write confirmed subsets to <alerts-dir>/persistent/.")
def main(alerts_dir: str, min_consecutive: int, min_overlap_frac: float, write: bool) -> None:
    adir = Path(alerts_dir)
    files = sorted(adir.glob("alerts_*.geojson"), key=_date_from_name)
    if not files:
        logger.error("No alerts_*.geojson found in {}", adir)
        raise SystemExit(1)

    logger.info("Loading {} alert files from {}", len(files), adir)
    dated = []
    for f in files:
        try:
            gdf = gpd.read_file(str(f))
        except Exception as e:
            logger.warning("Could not read {}: {}", f.name, e)
            gdf = gpd.GeoDataFrame(geometry=[])
        dated.append((_date_from_name(f), gdf))

    confirmed_by_date, summary = apply_persistence_to_history(
        dated, min_consecutive=min_consecutive, min_overlap_frac=min_overlap_frac,
    )

    # Report
    print("\n=== Persistence filter — before/after (>= {} consecutive obs, "
          "min overlap {:.0%}) ===".format(min_consecutive, min_overlap_frac))
    print(summary.to_string(index=False))
    total_raw = int(summary["raw"].sum())
    total_conf = int(summary["confirmed"].sum())
    print(f"\nTOTAL raw={total_raw}  confirmed={total_conf}  "
          f"dropped={total_raw - total_conf} "
          f"({100 * (1 - total_conf / total_raw):.1f}% removed)" if total_raw else "\nNo alerts.")

    if write:
        outdir = adir / "persistent"
        outdir.mkdir(parents=True, exist_ok=True)
        for date, gdf in confirmed_by_date.items():
            if gdf is None or gdf.empty:
                continue
            outpath = outdir / f"alerts_{date}.geojson"
            gdf.to_file(str(outpath), driver="GeoJSON")
        logger.info("Wrote confirmed subsets to {}", outdir)


if __name__ == "__main__":
    main()
