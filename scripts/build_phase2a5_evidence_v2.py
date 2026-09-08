#!/usr/bin/env python3
"""Build the Phase 2A.5 v2 per-case evidence (Package 2A.6D)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a5_evidence_v2 import (  # noqa: E402
    EvidenceV2Config,
    Phase2A5EvidenceV2Error,
    build_phase2a5_evidence_v2,
)


@click.command()
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a5-context-evidence-v2"),
    show_default=True,
)
@click.option(
    "--phase2a3-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a3-pilot-v1"),
    show_default=True,
)
@click.option(
    "--phase2a4-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a4-candidate-evidence-v1"),
    show_default=True,
)
@click.option("--generated-at", required=True)
def main(output_dir: Path, phase2a3_dir: Path, phase2a4_dir: Path, generated_at: str) -> None:
    try:
        manifest = build_phase2a5_evidence_v2(
            EvidenceV2Config(
                output_dir=(REPOSITORY_ROOT / output_dir).absolute(),
                phase2a3_dir=(REPOSITORY_ROOT / phase2a3_dir).resolve(),
                phase2a4_dir=(REPOSITORY_ROOT / phase2a4_dir).resolve(),
                generated_at=generated_at,
                repository_root=REPOSITORY_ROOT,
            )
        )
    except Phase2A5EvidenceV2Error as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "built_and_validated",
                "evidence_id": manifest["evidence_id"],
                "case_count": manifest["case_count"],
                "strong_subset_v2_totals": manifest["strong_subset_v2_totals"],
                "cross_collection_v2_states": manifest["cross_collection_v2_states"],
                "signature_v2_aggregate_labels": manifest["signature_v2_aggregate_labels"],
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
