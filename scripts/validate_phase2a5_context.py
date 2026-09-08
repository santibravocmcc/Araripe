#!/usr/bin/env python3
"""Deeply validate a local Phase 2A.5 MapBiomas context without network I/O."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a5_context import (  # noqa: E402
    Phase2A5ContextError,
    validate_phase2a5_context_artifact,
)


@click.command()
@click.argument(
    "context_dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("config/phase2a5_context_candidates_v1.json"),
    show_default=True,
)
@click.option(
    "--verify-sources/--skip-source-verification",
    default=True,
    show_default=True,
    help="Rehash both immutable national sources and ATBDs and reread native windows.",
)
def main(
    context_dir: Path,
    candidate_registry: Path,
    verify_sources: bool,
) -> None:
    try:
        manifest = validate_phase2a5_context_artifact(
            (REPOSITORY_ROOT / context_dir).resolve(),
            registry_path=(REPOSITORY_ROOT / candidate_registry).resolve(),
            repository_root=REPOSITORY_ROOT,
            verify_sources=verify_sources,
        )
    except Phase2A5ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "deep_valid" if verify_sources else "artifact_valid_sources_not_rehashed",
                "context_id": manifest["context_id"],
                "generated_at": manifest["generated_at"],
                "candidate_registry_sha256": manifest["candidate_registry"]["sha256"],
                "crop_outputs": {
                    key: {
                        "path": value["output"]["path"],
                        "bytes": value["output"]["bytes"],
                        "sha256": value["output"]["sha256"],
                        "class_histogram": value["output"]["class_histogram"],
                        "valid_coverage_fraction": value["output"]["valid_coverage_fraction"],
                    }
                    for key, value in manifest["crops"].items()
                },
                "method_selected_or_activated": False,
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
