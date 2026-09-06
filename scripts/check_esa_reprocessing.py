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

It is deliberately **standalone**: it imports nothing from the repository, so
it can run from the default branch, where the Phase 2A rebuild machinery does
not exist. Its query parameters come from
``config/esa_reprocessing_watch_query_v1.json``, which is generated from the
accepted regime contract and verified against it by
``tests/test_esa_watch_query_config.py`` on the science branch -- so the two
cannot drift apart silently.

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

WATCH_QUERY_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "esa_reprocessing_watch_query_v1.json"
)


def _load_query(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"cannot read watch query {path}: {exc}")


@click.command()
@click.option("--project", default="ee-araripe-baseline-v2", show_default=True)
@click.option(
    "--query-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=str(WATCH_QUERY_PATH),
    show_default=True,
)
@click.option(
    "--ready-fraction",
    default=None,
    type=float,
    help=(
        "Per-month share of wet-season scenes that must be on the Collection-1 "
        "lineage before the rebuild is worth attempting "
        "(default: from the query config)."
    ),
)
@click.option(
    "--json-out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write the machine-readable progress report here.",
)
def main(
    project: str,
    query_config: Path,
    ready_fraction: float | None,
    json_out: Path | None,
) -> None:
    import ee

    config = _load_query(query_config)
    query = config["query"]
    floor = config["collection1_processing_baseline_floor"]
    if ready_fraction is None:
        ready_fraction = config["default_ready_fraction"]
    months = list(query["months"])
    cloud = query["scene_cloud_filter_percent"]
    years = list(query["source_years"])
    collection_id = query["collection_id"]

    def is_collection1(baseline: str) -> bool:
        return str(baseline) >= floor

    ee.Initialize(project=project)
    aoi = ee.Geometry.Rectangle(
        list(query["monitoring_extent_bounds"]), None, False
    )
    click.echo(
        f"regime {config['derived_from']['regime_id']}: months {months}, "
        f"cloud <{cloud}"
    )
    click.echo(f"readiness threshold: {ready_fraction:.0%} of scenes per month\n")

    per_month: dict[int, dict] = {}
    for month in months:
        total = 0
        modern = 0
        modern_datatakes: set[str] = set()
        all_datatakes: set[str] = set()
        for year in years:
            start = ee.Date.fromYMD(year, month, 1)
            collection = (
                ee.ImageCollection(collection_id)
                .filterBounds(aoi)
                .filterDate(start, start.advance(1, "month"))
                .filter(
                    ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud)
                )
            )
            rows = collection.reduceColumns(
                ee.Reducer.toList(2, 1),
                ["PROCESSING_BASELINE", "DATATAKE_IDENTIFIER"],
            ).getInfo().get("list", [])
            for baseline, datatake in rows:
                total += 1
                all_datatakes.add(datatake)
                if is_collection1(baseline):
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
        "regime_id": config["derived_from"]["regime_id"],
        "regime_months": months,
        "scene_cloud_filter_percent": cloud,
        "query_config": config["derived_from"],
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
