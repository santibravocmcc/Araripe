#!/usr/bin/env python3
"""Build the local/private, provenance-bound Phase 2A.5 MapBiomas context."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a5_context import (  # noqa: E402
    Phase2A5ContextError,
    build_phase2a5_context_artifact,
)


@click.command()
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("config/phase2a5_context_candidates_v1.json"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a5-context-v1"),
    show_default=True,
)
@click.option(
    "--generated-at",
    required=True,
    help="Fixed timezone-aware RFC3339 generation time; never inferred from the clock.",
)
def main(candidate_registry: Path, output_dir: Path, generated_at: str) -> None:
    """Create both native-grid crops; do not select a policy or publish anything."""
    command = [
        "python",
        "scripts/build_phase2a5_context.py",
        "--candidate-registry",
        candidate_registry.as_posix(),
        "--output-dir",
        output_dir.as_posix(),
        "--generated-at",
        generated_at,
    ]
    try:
        manifest = build_phase2a5_context_artifact(
            repository_root=REPOSITORY_ROOT,
            registry_path=(REPOSITORY_ROOT / candidate_registry).resolve(),
            # Preserve a broken final symlink so the builder's no-clobber
            # checks can reject it rather than resolving it away.
            output_root=(REPOSITORY_ROOT / output_dir).absolute(),
            generated_at=generated_at,
            generation_command=command,
        )
    except Phase2A5ContextError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "built_and_deep_valid",
                "context_id": manifest["context_id"],
                "output_dir": output_dir.as_posix(),
                "crop_outputs": {
                    key: value["output"]
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
