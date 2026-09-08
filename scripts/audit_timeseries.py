#!/usr/bin/env python3
"""Read-only audit of the tracked legacy time-series SQLite database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.timeseries.audit import audit_legacy_database


@click.command()
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=Path("data/timeseries/timeseries.db"),
    show_default=True,
)
@click.option(
    "--json-out",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Optional local JSON report path.",
)
def main(db_path: Path, json_out: Path | None) -> None:
    """Inspect legacy rows and report their quarantine disposition."""
    report = audit_legacy_database(db_path)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(rendered, encoding="utf-8")
        click.echo(f"Wrote time-series audit: {json_out}")
    else:
        click.echo(rendered, nl=False)


if __name__ == "__main__":
    main()
