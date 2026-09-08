#!/usr/bin/env python3
"""Deeply validate local Phase 2A.5 contextual evidence without network I/O."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a5_evidence import (  # noqa: E402
    Phase2A5EvidenceError,
    validate_phase2a5_evidence_artifact,
)


@click.command()
@click.argument("evidence_dir", type=click.Path(path_type=Path, exists=True, file_okay=False))
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
def main(
    evidence_dir: Path,
    parent_phase2a3: Path,
    parent_phase2a4: Path,
    candidate_registry: Path,
    context_artifact: Path,
) -> None:
    try:
        manifest = validate_phase2a5_evidence_artifact(
            evidence_dir,
            parent_phase2a3_dir=parent_phase2a3,
            parent_phase2a4_dir=parent_phase2a4,
            candidate_registry_path=candidate_registry,
            context_artifact_dir=context_artifact,
            repository_root=REPOSITORY_ROOT,
        )
    except Phase2A5EvidenceError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "valid",
                "evidence_id": manifest["evidence_id"],
                "case_counts": manifest["counts"],
                "artifact_count": len(manifest["artifact_inventory"]) + 2,
                "qualified_human_label_present": False,
                "selected_or_activated": False,
                "scientific_accuracy_claim": False,
                "phase2a_exit_gate_closed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
