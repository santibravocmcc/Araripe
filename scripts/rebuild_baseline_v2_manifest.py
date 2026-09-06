"""Assemble and validate the baseline 2.0.0 manifest from a rebuilt directory.

Package 2A.6C tooling.  This script performs the LOCAL, deterministic half of
the baseline rebuild: it fully audits the 72 rebuilt rasters (checksums,
grid, scale, range, wider-extent coverage — the Package 2A.2 discipline),
joins them with the executor's execution-evidence document (per-month
datatakes, scene processing baselines, GEE project/task identity, export
checksums, plan/parity checksums), re-derives every acquisition ID and GEE
plan checksum, and writes the immutable `config/baseline_manifest_v2.json`.

It never contacts Earth Engine or R2, never touches the immutable baseline
1.0.0 manifest or objects, and refuses to overwrite any existing manifest.

Usage:
    python scripts/rebuild_baseline_v2_manifest.py \
        --baselines-dir data/baselines_v2/2.0.0 \
        --execution-evidence <rebuild_execution_evidence.json> \
        --build-date 2026-09-15
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection.baseline_manifest_v2 import (  # noqa: E402
    BASELINE_V2_LOCAL_DIR,
    BASELINE_V2_MANIFEST_PATH,
    BaselineManifestV2Error,
    audit_rebuilt_baseline_directory,
    build_manifest_v2,
    require_baseline_v1_untouched,
    write_manifest_v2,
)
from config.settings import BASELINE_MANIFEST_PATH  # noqa: E402


@click.command()
@click.option(
    "--baselines-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=str(BASELINE_V2_LOCAL_DIR),
    show_default=True,
    help="Directory holding the 72 rebuilt baseline rasters.",
)
@click.option(
    "--execution-evidence",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help=(
        "JSON produced by the rebuild executor with the "
        "reviewed_processing_baseline_registry and rebuild_execution blocks."
    ),
)
@click.option(
    "--build-date",
    required=True,
    help="ISO date the rebuilt rasters were produced (YYYY-MM-DD).",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=str(BASELINE_V2_MANIFEST_PATH),
    show_default=True,
    help="Target manifest path; must not already exist.",
)
def main(
    baselines_dir: Path,
    execution_evidence: Path,
    build_date: str,
    output: Path,
) -> None:
    # Fail before any work when the write target is unsafe: the v1 manifest
    # is immutable and a written v2 manifest is immutable too.
    if output.resolve() == Path(BASELINE_MANIFEST_PATH).resolve():
        raise click.ClickException(
            "refusing to target the immutable baseline 1.0.0 manifest"
        )
    if output.exists():
        raise click.ClickException(
            f"refusing to overwrite existing manifest {output}"
        )

    try:
        v1_sha256 = require_baseline_v1_untouched()
        click.echo(f"baseline 1.0.0 manifest verified untouched ({v1_sha256})")

        evidence = json.loads(execution_evidence.read_text(encoding="utf-8"))
        registry_block = evidence["reviewed_processing_baseline_registry"]
        execution_block = evidence["rebuild_execution"]
        # Package 2A.6C.1: the seasonal source regimes, when the rebuild used
        # them. Absent, the manifest falls back to the single-policy form.
        source_regimes = evidence.get("source_regimes")

        click.echo(f"auditing 72 rebuilt rasters in {baselines_dir} ...")
        objects = audit_rebuilt_baseline_directory(baselines_dir)

        manifest = build_manifest_v2(
            objects,
            execution_block,
            registry_block=registry_block,
            build_date=build_date,
            source_regimes=source_regimes,
        )
        target = write_manifest_v2(manifest, output)
    except (BaselineManifestV2Error, KeyError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

    aggregate = manifest["aggregate"]
    click.echo(
        "baseline 2.0.0 manifest written: "
        f"{target} ({aggregate['object_count']} objects, "
        f"{aggregate['total_bytes']} bytes, inventory "
        f"{aggregate['inventory_sha256']})"
    )
    click.echo(
        "observed processing baselines: "
        + ", ".join(manifest["observed_processing_baselines"])
    )
    click.echo(
        "observed platforms: " + ", ".join(manifest["observed_platforms"])
    )
    for regime in manifest["source_regimes"]:
        click.echo(
            f"source regime {regime['regime_id']}: months {regime['months']}, "
            f"cloud <{regime['scene_cloud_filter_percent']}, "
            f"provenance {regime['provenance_state']}"
        )


if __name__ == "__main__":
    main()
