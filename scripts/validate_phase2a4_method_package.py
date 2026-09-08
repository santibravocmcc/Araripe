#!/usr/bin/env python3
"""Deeply validate a local Phase 2A.4 blinded reviewer derivative."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.phase2a4_package import (  # noqa: E402
    Phase2A4PackageIntegrityError,
    validate_phase2a4_derivative_package,
)


@click.command()
@click.argument("package_dir", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option(
    "--parent-package",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=None,
)
@click.option(
    "--rainfall-artifact",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
@click.option(
    "--candidate-evidence",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
)
def main(
    package_dir: Path,
    parent_package: Path | None,
    candidate_registry: Path | None,
    rainfall_artifact: Path | None,
    candidate_evidence: Path | None,
) -> None:
    try:
        manifest = validate_phase2a4_derivative_package(
            package_dir,
            parent_root=parent_package,
            registry_path=candidate_registry,
            rainfall_root=rainfall_artifact,
            evidence_root=candidate_evidence,
            repository_root=(Path(__file__).resolve().parent.parent if parent_package else None),
        )
    except Phase2A4PackageIntegrityError as exc:
        raise click.ClickException(str(exc)) from exc
    result = {
        "status": "valid",
        "package_id": manifest["package_id"],
        "primary_case_count": manifest["case_population"]["primary_case_count"],
        "double_review_case_count": manifest["case_population"]["double_review_case_count"],
        "artifact_count": len(manifest["artifact_inventory"]) + 2,
        "method_decision_status": manifest["method_decision_status"],
    }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
