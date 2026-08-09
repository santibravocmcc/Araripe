#!/usr/bin/env python3
"""Build the local/private Phase 2A.4 CHIRPS monthly reference artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a4_rainfall import (  # noqa: E402
    RainfallArtifactError,
    build_rainfall_reference_artifact,
)


@click.command()
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a4-rainfall-reference-v1"),
    show_default=True,
    help="Local/private artifact directory; never uploaded by this command.",
)
@click.option(
    "--target-month",
    "target_months",
    multiple=True,
    required=True,
    help=(
        "Explicit YYYY-MM target month. Repeat for every target; the fixed "
        "1981-01 through 2025-12 reference is always included."
    ),
)
@click.option(
    "--generated-at",
    required=True,
    help="Fixed timezone-aware RFC3339 artifact generation time.",
)
@click.option(
    "--catalog-accessed-at",
    required=True,
    help="Fixed timezone-aware RFC3339 time for the CHIRPS source access.",
)
@click.option(
    "--workers",
    type=click.IntRange(min=1, max=32),
    default=4,
    show_default=True,
    help="Concurrent read count; it does not affect artifact ordering.",
)
@click.option(
    "--retry-errors/--reuse-errors",
    default=False,
    show_default=True,
    help="Retry retained error months when resuming; never substitute another month.",
)
def main(
    out_dir: Path,
    target_months: tuple[str, ...],
    generated_at: str,
    catalog_accessed_at: str,
    workers: int,
    retry_errors: bool,
) -> None:
    """Materialize fixed official CHIRPS COG windows for candidate evaluation."""
    sorted_targets = sorted(set(target_months))
    generation_command = [
        "scripts/build_phase2a4_rainfall_reference.py",
        "--out-dir",
        "<local-private-output>",
    ]
    for month in sorted_targets:
        generation_command.extend(["--target-month", month])
    generation_command.extend(
        [
            "--generated-at",
            generated_at,
            "--catalog-accessed-at",
            catalog_accessed_at,
        ]
    )
    try:
        manifest = build_rainfall_reference_artifact(
            output_dir=out_dir,
            target_months=sorted_targets,
            generated_at=generated_at,
            accessed_at=catalog_accessed_at,
            workers=workers,
            retry_errors=retry_errors,
            generation_command=generation_command,
            repository_root=REPOSITORY_ROOT,
        )
    except RainfallArtifactError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        json.dumps(
            {
                "artifact_id": manifest["artifact_id"],
                "artifact_path": str(out_dir.resolve()),
                "overall_status": manifest["overall_status"],
                "reference_status": manifest["reference_period"]["status"],
                "target_status": manifest["target_status"],
                "status_counts": manifest["status_counts"],
                "drought_status_computed": False,
                "drought_adjustment_activated": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
