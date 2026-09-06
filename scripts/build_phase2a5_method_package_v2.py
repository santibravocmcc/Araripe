#!/usr/bin/env python3
"""Build the Phase 2A.5 v2 blinded method-comparison derivative (2A.6D)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.validation.phase2a5_package_v2 import (  # noqa: E402
    PackageV2Config,
    Phase2A5PackageV2Error,
    build_phase2a5_package_v2,
)


@click.command()
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("data/validation/phase2a5-method-comparison-v2"),
    show_default=True,
)
@click.option(
    "--v1-package-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a5-method-comparison-v1"),
    show_default=True,
)
@click.option(
    "--evidence-v2-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path("data/validation/phase2a5-context-evidence-v2"),
    show_default=True,
)
@click.option("--generated-at", required=True)
def main(output_dir: Path, v1_package_dir: Path, evidence_v2_dir: Path, generated_at: str) -> None:
    try:
        manifest = build_phase2a5_package_v2(
            PackageV2Config(
                output_dir=(REPOSITORY_ROOT / output_dir).absolute(),
                v1_package_dir=(REPOSITORY_ROOT / v1_package_dir).resolve(),
                evidence_v2_dir=(REPOSITORY_ROOT / evidence_v2_dir).resolve(),
                repository_root=REPOSITORY_ROOT,
                generated_at=generated_at,
            )
        )
    except Phase2A5PackageV2Error as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "status": "built_and_validated",
                "package_id": manifest["package_id"],
                "preserved_v1_files": manifest["derived_from_v1_package"]["preserved_file_count"],
                "file_count": manifest["file_count"],
                "exact_balance_per_family": manifest["exact_balance_per_family"],
            },
            ensure_ascii=False, indent=2, sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
