#!/usr/bin/env python3
"""Deeply validate a local Phase 2A.5 blinded reviewer derivative."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.phase2a5_package import (  # noqa: E402
    Phase2A5PackageIntegrityError,
    validate_phase2a5_derivative_package,
)


@click.command()
@click.argument(
    "package_dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
@click.option(
    "--phase2a3-parent",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
@click.option(
    "--phase2a4-derivative",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
)
@click.option(
    "--context-manifest",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
)
@click.option(
    "--context-evidence",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
def main(
    package_dir: Path,
    phase2a3_parent: Path | None,
    phase2a4_derivative: Path | None,
    candidate_registry: Path | None,
    context_manifest: Path | None,
    context_evidence: Path | None,
) -> None:
    try:
        manifest = validate_phase2a5_derivative_package(
            package_dir,
            phase2a3_parent_root=phase2a3_parent,
            phase2a4_derivative_root=phase2a4_derivative,
            registry_path=candidate_registry,
            context_manifest_path=context_manifest,
            evidence_root=context_evidence,
            repository_root=(
                Path(__file__).resolve().parent.parent
                if phase2a3_parent is not None
                else None
            ),
        )
    except Phase2A5PackageIntegrityError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "valid",
                "package_id": manifest["package_id"],
                "primary_case_count": manifest["case_population"][
                    "primary_case_count"
                ],
                "double_review_case_count": manifest["case_population"][
                    "double_review_case_count"
                ],
                "artifact_count": len(manifest["artifact_inventory"]) + 2,
                "method_decision_status": manifest["method_decision_status"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
