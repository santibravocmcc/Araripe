#!/usr/bin/env python3
"""Validate a generated Phase 2A.3 desktop package and its source snapshot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.validator import validate_validation_package


@click.command()
@click.argument(
    "package_dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
@click.option(
    "--source-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=None,
    help="Optional local alert snapshot; when supplied, rechecks every source byte/SHA.",
)
def main(package_dir: Path, source_dir: Path | None) -> None:
    result = validate_validation_package(package_dir, source_dir=source_dir)
    click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
