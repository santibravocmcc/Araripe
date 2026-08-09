#!/usr/bin/env python3
"""Validate a Phase 2A.3 or package-bound Phase 2A.4 reviewer export."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.validator import (
    ValidationPackageIntegrityError,
    validate_review_export,
)


@click.command()
@click.argument(
    "package_root",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
)
@click.argument(
    "review_export",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
def main(package_root: Path, review_export: Path) -> None:
    try:
        result = validate_review_export(package_root, review_export)
    except ValidationPackageIntegrityError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
