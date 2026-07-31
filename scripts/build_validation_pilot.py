#!/usr/bin/env python3
"""Build the deterministic local/private Phase 2A.3 validation pilot."""

from __future__ import annotations

import sys
import datetime as dt
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.package import build_validation_package
from src.validation.evidence import (
    EvidenceConfig,
    collect_evidence,
    evidence_config_record,
)
from src.validation.sampling import (
    DEFAULT_RANDOM_SEED,
    DEFAULT_TARGET_SIZE,
    build_sampling_frame,
    sanitize_origin_base_url,
)


@click.command()
@click.option(
    "--alerts-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    required=True,
    help="Local read-only directory containing the frozen alerts_*.geojson snapshot.",
)
@click.option("--pattern", default="alerts_*.geojson", show_default=True)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a3-pilot-v1"),
    show_default=True,
)
@click.option("--target-size", type=click.IntRange(min=1), default=DEFAULT_TARGET_SIZE, show_default=True)
@click.option("--seed", default=DEFAULT_RANDOM_SEED, show_default=True)
@click.option(
    "--origin-base-url",
    default=None,
    help="Optional non-secret source URL prefix recorded for each retrieved artifact.",
)
@click.option(
    "--generated-at",
    required=True,
    help="Fixed RFC3339 generation time; required so regeneration has no wall-clock default.",
)
@click.option(
    "--source-retrieved-at",
    required=True,
    help="Fixed RFC3339 time at which the local read-only source snapshot was retrieved.",
)
@click.option(
    "--fetch-evidence/--no-fetch-evidence",
    default=False,
    help="Read-only STAC/local-source retrieval for case evidence; failures remain explicit.",
)
@click.option(
    "--evidence-cache",
    type=click.Path(path_type=Path),
    default=Path("data/validation/evidence-cache-v1"),
    show_default=True,
)
@click.option(
    "--evidence-cutoff-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Latest permitted evidence date (YYYY-MM-DD); required with --fetch-evidence.",
)
@click.option(
    "--catalog-accessed-at",
    default=None,
    help="Fixed RFC3339 STAC access time; required with --fetch-evidence.",
)
@click.option(
    "--mapbiomas-10m",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
)
@click.option(
    "--mapbiomas-30m",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
)
@click.option("--evidence-workers", type=click.IntRange(min=1, max=16), default=4, show_default=True)
def main(
    alerts_dir: Path,
    pattern: str,
    out_dir: Path,
    target_size: int,
    seed: str,
    origin_base_url: str | None,
    generated_at: str,
    source_retrieved_at: str,
    fetch_evidence: bool,
    evidence_cache: Path,
    evidence_cutoff_date: dt.datetime | None,
    catalog_accessed_at: str | None,
    mapbiomas_10m: Path | None,
    mapbiomas_30m: Path | None,
    evidence_workers: int,
) -> None:
    paths = sorted(alerts_dir.glob(pattern))
    if not paths:
        raise click.ClickException(f"no files match {pattern!r} under {alerts_dir}")
    frame = build_sampling_frame(
        paths,
        target_size=target_size,
        seed=seed,
        origin_base_url=origin_base_url,
    )
    evidence = None
    evidence_config = None
    if fetch_evidence:
        if evidence_cutoff_date is None or catalog_accessed_at is None:
            raise click.ClickException(
                "--evidence-cutoff-date and --catalog-accessed-at are required with --fetch-evidence"
            )
        evidence_config = EvidenceConfig(
            cache_dir=evidence_cache,
            catalog_accessed_at=catalog_accessed_at,
            evidence_cutoff_date=evidence_cutoff_date.date(),
            mapbiomas_10m_path=mapbiomas_10m,
            mapbiomas_30m_path=mapbiomas_30m,
        )
        evidence = collect_evidence(
            frame["selected_units"],
            config=evidence_config,
            workers=evidence_workers,
        )
    command = [
        "scripts/build_validation_pilot.py",
        "--alerts-dir",
        str(alerts_dir.resolve()),
        "--pattern",
        pattern,
        "--out-dir",
        str(out_dir.resolve()),
        "--target-size",
        str(target_size),
        "--seed",
        seed,
        "--generated-at",
        generated_at,
        "--source-retrieved-at",
        source_retrieved_at,
    ]
    if origin_base_url:
        command.extend(
            ["--origin-base-url", sanitize_origin_base_url(origin_base_url)]
        )
    if fetch_evidence:
        command.extend(
            [
                "--fetch-evidence",
                "--evidence-cache",
                str(evidence_cache.resolve()),
                "--evidence-cutoff-date",
                evidence_cutoff_date.date().isoformat(),
                "--catalog-accessed-at",
                catalog_accessed_at,
                "--evidence-workers",
                str(evidence_workers),
            ]
        )
        if mapbiomas_10m:
            command.extend(["--mapbiomas-10m", str(mapbiomas_10m.resolve())])
        if mapbiomas_30m:
            command.extend(["--mapbiomas-30m", str(mapbiomas_30m.resolve())])
    else:
        command.append("--no-fetch-evidence")
    root = Path(__file__).resolve().parent.parent
    manifest = build_validation_package(
        frame,
        output_dir=out_dir,
        repository_root=root,
        generated_at=generated_at,
        source_retrieved_at=source_retrieved_at,
        evidence_by_sample=evidence,
        evidence_generation=(
            {
                "mode": "read_only_live_catalog_and_local_sources",
                **evidence_config_record(evidence_config),
                "catalog_snapshot_limit": (
                    "Catalog results are not replayable from access time alone; mutable "
                    "catalogs can ingest, replace, or remove items. Only selected item "
                    "identifiers, recorded metadata fields and digests, cached evidence "
                    "assets, and rendered derivatives are frozen per case."
                ),
            }
            if evidence_config
            else None
        ),
        generation_command=command,
    )
    click.echo(
        f"Built {manifest['package_id']} with {manifest['sampling']['actual_size']} "
        f"provisional cases at {out_dir}"
    )
    click.echo("No human labels, scientific accuracy estimate, or method decision was generated.")


if __name__ == "__main__":
    main()
