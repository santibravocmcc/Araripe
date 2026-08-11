#!/usr/bin/env python3
"""Build the local/private blinded Phase 2A.5 reviewer derivative."""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.phase2a5_package import (  # noqa: E402
    Phase2A5PackageError,
    build_phase2a5_derivative_package,
)


@click.command()
@click.option(
    "--phase2a3-parent",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a3-pilot-v1"),
    show_default=True,
)
@click.option(
    "--phase2a4-derivative",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a4-method-comparison-v1"),
    show_default=True,
)
@click.option(
    "--candidate-registry",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("config/phase2a5_context_candidates_v1.json"),
    show_default=True,
)
@click.option(
    "--context-manifest",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("data/validation/phase2a5-context-v1/manifest.json"),
    show_default=True,
)
@click.option(
    "--context-evidence",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a5-context-evidence-v1"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a5-method-comparison-v1"),
    show_default=True,
)
@click.option("--generated-at", required=True, help="Fixed timezone-aware RFC3339 time.")
def main(
    phase2a3_parent: Path,
    phase2a4_derivative: Path,
    candidate_registry: Path,
    context_manifest: Path,
    context_evidence: Path,
    output_dir: Path,
    generated_at: str,
) -> None:
    repository_root = Path(__file__).resolve().parent.parent
    command = [
        "scripts/build_phase2a5_method_package.py",
        "--phase2a3-parent",
        str(phase2a3_parent.resolve()),
        "--phase2a4-derivative",
        str(phase2a4_derivative.resolve()),
        "--candidate-registry",
        str(candidate_registry.resolve()),
        "--context-manifest",
        str(context_manifest.resolve()),
        "--context-evidence",
        str(context_evidence.resolve()),
        "--output-dir",
        str(output_dir.resolve()),
        "--generated-at",
        generated_at,
    ]
    try:
        manifest = build_phase2a5_derivative_package(
            phase2a3_parent_root=phase2a3_parent,
            phase2a4_derivative_root=phase2a4_derivative,
            registry_path=candidate_registry,
            context_manifest_path=context_manifest,
            evidence_root=context_evidence,
            output_root=output_dir,
            repository_root=repository_root,
            generated_at=generated_at,
            generation_command=command,
        )
    except Phase2A5PackageError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Built {manifest['package_id']} with "
        f"{manifest['case_population']['primary_case_count']} unchanged cases at {output_dir}"
    )
    click.echo(
        "No qualified label, threshold choice, contextual policy, activation, "
        "replay, release, or publication was produced."
    )


if __name__ == "__main__":
    main()
