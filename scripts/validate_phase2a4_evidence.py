#!/usr/bin/env python3
"""Deeply validate local Phase 2A.4 candidate evidence without network I/O."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a4_evidence import (  # noqa: E402
    Phase2A4EvidenceError,
    validate_phase2a4_evidence_artifact,
)


@click.command()
@click.argument(
    "evidence_dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
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
def main(
    evidence_dir: Path,
    parent_package: Path,
    candidate_registry: Path,
    rainfall_artifact: Path,
    baseline_manifest: Path,
) -> None:
    try:
        manifest = validate_phase2a4_evidence_artifact(
            evidence_dir,
            parent_package_dir=parent_package,
            candidate_registry_path=candidate_registry,
            rainfall_artifact_dir=rainfall_artifact,
            baseline_manifest_path=baseline_manifest,
            repository_root=REPOSITORY_ROOT,
        )
    except Phase2A4EvidenceError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "valid",
                "evidence_id": manifest["evidence_id"],
                "case_counts": manifest["counts"],
                "artifact_count": len(manifest["artifact_inventory"]) + 2,
                "method_selected_or_activated": False,
                "scientific_accuracy_claim": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
