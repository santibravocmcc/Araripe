#!/usr/bin/env python3
"""Build the local/private blinded Phase 2A.4 reviewer derivative."""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.phase2a4_package import (  # noqa: E402
    Phase2A4PackageError,
    build_phase2a4_derivative_package,
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
    "--candidate-evidence",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a4-candidate-evidence-v1"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a4-method-comparison-v1"),
    show_default=True,
)
@click.option("--generated-at", required=True, help="Fixed timezone-aware RFC3339 time.")
def main(
    parent_package: Path,
    candidate_registry: Path,
    rainfall_artifact: Path,
    candidate_evidence: Path,
    output_dir: Path,
    generated_at: str,
) -> None:
    repository_root = Path(__file__).resolve().parent.parent
    command = [
        "scripts/build_phase2a4_method_package.py",
        "--parent-package",
        str(parent_package.resolve()),
        "--candidate-registry",
        str(candidate_registry.resolve()),
        "--rainfall-artifact",
        str(rainfall_artifact.resolve()),
        "--candidate-evidence",
        str(candidate_evidence.resolve()),
        "--output-dir",
        str(output_dir.resolve()),
        "--generated-at",
        generated_at,
    ]
    try:
        manifest = build_phase2a4_derivative_package(
            parent_root=parent_package,
            registry_path=candidate_registry,
            rainfall_root=rainfall_artifact,
            evidence_root=candidate_evidence,
            output_root=output_dir,
            repository_root=repository_root,
            generated_at=generated_at,
            generation_command=command,
        )
    except Phase2A4PackageError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Built {manifest['package_id']} with "
        f"{manifest['case_population']['primary_case_count']} unchanged cases at {output_dir}"
    )
    click.echo("No label, method decision, activation, replay, release, or publication was produced.")


if __name__ == "__main__":
    main()
