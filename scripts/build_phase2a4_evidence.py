#!/usr/bin/env python3
"""Build local/private Phase 2A.4 candidate evidence for the frozen pilot."""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.phase2a4_evidence import (  # noqa: E402
    Phase2A4EvidenceConfig,
    Phase2A4EvidenceError,
    build_phase2a4_evidence,
)


@click.command()
@click.option(
    "--parent-package",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a3-pilot-v1"),
    show_default=True,
)
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("config/phase2a4_candidates_v1.json"),
    show_default=True,
)
@click.option(
    "--rainfall-artifact",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a4-rainfall-reference-v1"),
    show_default=True,
)
@click.option(
    "--baseline-manifest",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("config/baseline_manifest_v1.json"),
    show_default=True,
)
@click.option(
    "--baseline-public-base-url",
    required=True,
    help="Explicit read-only HTTPS base containing manifest-bound baseline keys.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a4-candidate-evidence-v1"),
    show_default=True,
)
@click.option("--generated-at", required=True, help="Fixed timezone-aware RFC3339 time.")
@click.option(
    "--catalog-accessed-at",
    required=True,
    help="Fixed timezone-aware RFC3339 Earth Search access time.",
)
@click.option("--workers", type=click.IntRange(min=1, max=12), default=4, show_default=True)
def main(
    parent_package: Path,
    candidate_registry: Path,
    rainfall_artifact: Path,
    baseline_manifest: Path,
    baseline_public_base_url: str,
    output_dir: Path,
    generated_at: str,
    catalog_accessed_at: str,
    workers: int,
) -> None:
    """Generate evidence only; do not select, activate, replay, or publish."""
    try:
        manifest = build_phase2a4_evidence(
            Phase2A4EvidenceConfig(
                output_dir=output_dir,
                parent_package_dir=parent_package,
                candidate_registry_path=candidate_registry,
                rainfall_artifact_dir=rainfall_artifact,
                baseline_manifest_path=baseline_manifest,
                baseline_public_base_url=baseline_public_base_url,
                generated_at=generated_at,
                catalog_accessed_at=catalog_accessed_at,
                workers=workers,
            )
        )
    except Phase2A4EvidenceError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Built {manifest['evidence_id']} with {manifest['counts']['case_count']} "
        f"unchanged provisional cases at {output_dir}"
    )
    click.echo("No label, method selection, drought activation, replay, or publication was produced.")


if __name__ == "__main__":
    main()
