"""Report how far ESA has reprocessed the baseline wet season onto Collection-1.

Package 2A.6C.1 admitted pre-Collection-1 products for calendar months 1-4
because the Collection-1 lineage barely covers the wet season of the accepted
source years. That admission carries the provenance state
``mixed_lineage_pending_esa_reprocessing`` and a retirement condition: when the
reprocessing reaches those months, the wet season should be rebuilt on the
Collection-1 lineage alone and the regime retired.

This script measures that progress. It is a **metadata-only** query -- it reads
scene properties and touches no pixels -- so it is cheap enough to run monthly
without meaningfully consuming the project's Earth Engine compute quota.

Exit status:
    0  progress reported, not yet ready
    9  every wet-season month has crossed the readiness threshold
    1  error

Usage:
    python scripts/check_esa_reprocessing.py --project ee-araripe-baseline-v2
    python scripts/check_esa_reprocessing.py --json-out progress.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import BASELINE_SOURCE_YEARS, GEE_COLLECTION_ID  # noqa: E402
from src.detection.baseline_manifest import (  # noqa: E402
    MONITORING_EXTENT_BOUNDS,
)
from src.processing.baseline_rebuild_v2 import (  # noqa: E402
    load_source_regimes,
)

# A product is on the Collection-1 lineage when its processing baseline is
# 05.00 or later; this is the same criterion the owner's 2026-09-05 review used.
COLLECTION1_FLOOR = "05."


def _is_collection1(baseline: str) -> bool:
    return str(baseline) >= COLLECTION1_FLOOR


@click.command()
@click.option("--project", default="ee-araripe-baseline-v2", show_default=True)
@click.option(
    "--ready-fraction",
    default=0.90,
    show_default=True,
    help=(
        "Per-month share of wet-season scenes that must be on the Collection-1 "
        "lineage before the rebuild is worth attempting."
    ),
)
@click.option(
    "--json-out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the machine-readable progress report here.",
)
def main(project: str, ready_fraction: float, json_out: Path | None) -> None:
    import ee

    ee.Initialize(project=project)
    aoi = ee.Geometry.Rectangle(list(MONITORING_EXTENT_BOUNDS), None, False)

    wet = next(
        regime
        for regime in load_source_regimes()
        if regime.provenance_state == "mixed_lineage_pending_esa_reprocessing"
    )
    click.echo(
        f"regime {wet.regime_id}: months {list(wet.months)}, "
        f"cloud <{wet.scene_cloud_filter_percent}"
    )
    click.echo(f"readiness threshold: {ready_fraction:.0%} of scenes per month\n")

    per_month: dict[int, dict] = {}
    for month in wet.months:
        total = 0
        modern = 0
        modern_datatakes: set[str] = set()
        all_datatakes: set[str] = set()
        for year in BASELINE_SOURCE_YEARS:
            start = ee.Date.fromYMD(year, month, 1)
            collection = (
                ee.ImageCollection(GEE_COLLECTION_ID)
                .filterBounds(aoi)
                .filterDate(start, start.advance(1, "month"))
                .filter(
                    ee.Filter.lt(
                        "CLOUDY_PIXEL_PERCENTAGE",
                        wet.scene_cloud_filter_percent,
                    )
                )
            )
            rows = collection.reduceColumns(
                ee.Reducer.toList(2, 1),
                ["PROCESSING_BASELINE", "DATATAKE_IDENTIFIER"],
            ).getInfo().get("list", [])
            for baseline, datatake in rows:
                total += 1
                all_datatakes.add(datatake)
                if _is_collection1(baseline):
                    modern += 1
                    modern_datatakes.add(datatake)
        share = (modern / total) if total else 0.0
        per_month[month] = {
            "scenes_total": total,
            "scenes_on_collection1": modern,
            "collection1_share": round(share, 4),
            "datatakes_total": len(all_datatakes),
            "datatakes_on_collection1": len(modern_datatakes),
            "ready": share >= ready_fraction,
        }
        flag = "PRONTO" if share >= ready_fraction else "aguardando"
        click.echo(
            f"  month {month:02d}: {modern:>4}/{total:<4} scenes on "
            f"Collection-1 ({share:6.1%})  "
            f"{len(modern_datatakes):>3}/{len(all_datatakes):<3} datatakes  "
            f"[{flag}]"
        )

    ready = all(entry["ready"] for entry in per_month.values())
    report = {
        "report_version": "phase2a6c1-esa-reprocessing-watch-v1",
        "checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "earth_engine_project": project,
        "regime_id": wet.regime_id,
        "regime_months": list(wet.months),
        "scene_cloud_filter_percent": wet.scene_cloud_filter_percent,
        "ready_fraction": ready_fraction,
        "months": {str(k): v for k, v in per_month.items()},
        "ready_to_rebuild": ready,
    }
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        click.echo(f"\nreport -> {json_out}")

    if ready:
        click.echo(
            "\nREADY_TO_REBUILD: every wet-season month has crossed the "
            "threshold.\nRun the procedure in "
            "docs/operations/WET_SEASON_REBUILD_PROMPT.md"
        )
        sys.exit(9)
    click.echo("\nnot ready yet; nothing to do.")


if __name__ == "__main__":
    main()
