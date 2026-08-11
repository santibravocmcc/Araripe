#!/usr/bin/env python3
"""Build local/private Phase 2A.5 evidence for the frozen 60-case pilot."""

from __future__ import annotations

import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a5_evidence import (  # noqa: E402
    Phase2A5EvidenceConfig,
    Phase2A5EvidenceError,
    build_phase2a5_evidence,
)


@click.command()
@click.option(
    "--parent-phase2a3",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a3-pilot-v1"),
    show_default=True,
)
@click.option(
    "--parent-phase2a4",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a4-candidate-evidence-v1"),
    show_default=True,
)
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("config/phase2a5_context_candidates_v1.json"),
    show_default=True,
)
@click.option(
    "--context-artifact",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a5-context-v1"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a5-context-evidence-v1"),
    show_default=True,
)
@click.option("--generated-at", required=True, help="Fixed timezone-aware RFC3339 time.")
def main(
    parent_phase2a3: Path,
    parent_phase2a4: Path,
    candidate_registry: Path,
    context_artifact: Path,
    output_dir: Path,
    generated_at: str,
) -> None:
    """Generate evidence only; do not label, select, activate, replay, or publish."""
    try:
        manifest = build_phase2a5_evidence(
            Phase2A5EvidenceConfig(
                output_dir=output_dir,
                parent_phase2a3_dir=parent_phase2a3,
                parent_phase2a4_dir=parent_phase2a4,
                candidate_registry_path=candidate_registry,
                context_artifact_dir=context_artifact,
                generated_at=generated_at,
                repository_root=REPOSITORY_ROOT,
            )
        )
    except Phase2A5EvidenceError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Built {manifest['evidence_id']} with {manifest['counts']['case_count']} "
        f"unchanged provisional cases at {output_dir}"
    )
    click.echo(
        "No qualified label, accepted identity, threshold/signature selection, cause claim, "
        "Phase 2A.4 change, replay, or publication was produced."
    )


if __name__ == "__main__":
    main()
