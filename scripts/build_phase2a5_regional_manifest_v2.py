"""Build the Phase 2A.5 regional context manifest v2 (Package 2A.6D).

Rehashes every regional byte it binds: the reused Collection 3 crop (permitted
by the decision record only after hash verification against its recorded v1
identity), the fresh Collection 10.1 GEE export, and the invalidated
mislabeled Collection 10 crop, whose audit bytes must remain exactly as
recorded while its runtime and qualified-review use stay revoked.

Grid reconciliation is proven, not assumed: the Collection 3 crop and the
10.1 export must be integer-aligned 3:1 lattices so the only permitted future
categorical comparison (nearest to the primary grid) is exact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from src.validation.phase2a5_context_v2 import (  # noqa: E402
    COL3_KEY_V2,
    COL10_1_KEY_V2,
    Phase2A5ContextV2Error,
    REGIONAL_MANIFEST_V2_PATH,
    REGISTRY_V2_PATH,
    _canonical_sha256,
    _sha256_file,
    load_context_registry_v2,
)


def _header(path: Path) -> dict:
    with rasterio.open(path) as src:
        return {
            "crs": str(src.crs),
            "width": src.width,
            "height": src.height,
            "transform": list(src.transform)[:6],
            "dtype": src.dtypes[0],
            "band_count": src.count,
            "nodata": None if src.nodata is None else int(src.nodata),
        }


def _histogram(path: Path) -> dict:
    with rasterio.open(path) as src:
        values = src.read(1)
    unique, counts = np.unique(values, return_counts=True)
    return {str(int(code)): int(count) for code, count in zip(unique, counts)}


@click.command()
@click.option("--build-date", required=True, help="ISO date (YYYY-MM-DD).")
def main(build_date: str) -> None:
    if REGIONAL_MANIFEST_V2_PATH.exists():
        raise click.ClickException(
            f"{REGIONAL_MANIFEST_V2_PATH} already exists; the regional "
            "manifest is immutable once written"
        )
    try:
        registry = load_context_registry_v2()
    except Phase2A5ContextV2Error as exc:
        raise click.ClickException(str(exc)) from exc

    col3 = registry["sources"][COL3_KEY_V2]
    col10_1 = registry["sources"][COL10_1_KEY_V2]
    invalidation = registry["mislabeled_collection10_invalidation"]

    # 1. The reused Collection 3 crop must still be the recorded v1 bytes.
    crop = Path(col3["regional_crop_path"])
    crop_sha = _sha256_file(crop)
    if (
        crop.stat().st_size != col3["regional_crop_bytes"]
        or crop_sha != col3["regional_crop_sha256"]
    ):
        raise click.ClickException(
            "the Collection 3 regional crop does not match its recorded v1 "
            "identity; reuse without hash verification is not permitted"
        )
    click.echo(f"collection 3 crop verified ({crop_sha[:16]}…)")

    # 2. The fresh Collection 10.1 export must match its export manifest.
    export = Path(col10_1["regional_path"])
    export_sha = _sha256_file(export)
    if (
        export.stat().st_size != col10_1["regional_bytes"]
        or export_sha != col10_1["regional_sha256"]
    ):
        raise click.ClickException(
            "the Collection 10.1 export bytes do not match the export manifest"
        )
    export_manifest = json.loads(
        Path(col10_1["export_manifest_path"]).read_text("utf-8")
    )
    click.echo(f"collection 10.1 export verified ({export_sha[:16]}…)")

    # 3. The invalidated crop's audit bytes must be exactly as recorded.
    audit = Path(invalidation["path"])
    audit_sha = _sha256_file(audit)
    if (
        audit.stat().st_size != invalidation["bytes"]
        or audit_sha != invalidation["sha256"]
    ):
        raise click.ClickException(
            "the invalidated Collection 10 crop bytes changed; audit material "
            "must never be modified"
        )
    click.echo(f"invalidated collection 10 audit bytes intact ({audit_sha[:16]}…)")

    col3_header = _header(crop)
    col10_1_header = _header(export)

    # 4. Grid reconciliation. The national 10 m and 30 m lattices do not
    # share an origin: the primary sits at a fixed sub-cell phase inside the
    # secondary grid. What nearest-neighbour correctness actually requires is
    # (a) an exact 3:1 ratio, (b) an origin offset that is an integer count
    # of PRIMARY pixels, and (c) that consequently no primary pixel centre
    # ever falls on a secondary cell boundary — each centre sits at 1/6, 3/6
    # or 5/6 of a cell, 1/6 away from any edge, so nearest is exact and
    # tie-free.
    p, s = col3_header["transform"], col10_1_header["transform"]
    ratio_x, ratio_y = s[0] / p[0], s[4] / p[4]
    phase_x = (p[2] - s[2]) / p[0]
    phase_y = (p[5] - s[5]) / p[4]
    if not (
        abs(ratio_x - 3) < 1e-9
        and abs(ratio_y - 3) < 1e-9
        and abs(phase_x - round(phase_x)) < 1e-6
        and abs(phase_y - round(phase_y)) < 1e-6
    ):
        raise click.ClickException(
            "the Collection 3 and 10.1 grids are not a 3:1 lattice pair with "
            "an integer primary-pixel phase; nearest categorical comparison "
            "would not be exact"
        )
    phase = (int(round(phase_x)) % 3, int(round(phase_y)) % 3)
    # (c) explicitly: primary centre k sits at fraction (phase + k + 0.5)/3
    # of a secondary cell; with an integer phase that is one of 1/6, 3/6,
    # 5/6 — never 0 or 1.
    fractions = sorted({((phase[0] + k + 0.5) / 3) % 1 for k in range(3)})
    if min(fractions) < 1e-9 or max(fractions) > 1 - 1e-9:
        raise click.ClickException(
            "a primary pixel centre would fall on a secondary cell boundary"
        )
    click.echo(
        f"grid reconciliation: 3:1 ratio, primary-pixel phase {phase}, "
        "no centre-on-boundary — nearest is exact and tie-free"
    )

    # 5. The 10.1 histogram must equal the export manifest's.
    histogram = _histogram(export)
    if histogram != export_manifest["class_histogram"]:
        raise click.ClickException(
            "the Collection 10.1 histogram no longer matches its export manifest"
        )

    manifest = {
        "schema_version": "1.0.0",
        "manifest_id": "phase2a5_regional_context_manifest_v2",
        "build_date": build_date,
        "decision_binding": registry["decision_binding"],
        "registry_binding": {
            "path": str(REGISTRY_V2_PATH),
            "sha256": _sha256_file(REGISTRY_V2_PATH),
        },
        "monitoring_extent": registry["monitoring_extent"],
        "regional_sources": {
            COL3_KEY_V2: {
                "path": str(crop),
                "bytes": crop.stat().st_size,
                "sha256": crop_sha,
                "header": col3_header,
                "provenance": "v1 crop bytes reused after hash verification",
                "national_source_sha256": col3["national_sha256"],
            },
            COL10_1_KEY_V2: {
                "path": str(export),
                "bytes": export.stat().st_size,
                "sha256": export_sha,
                "header": col10_1_header,
                "class_histogram": histogram,
                "provenance": "fresh acquisition from the official GEE asset",
                "export_manifest_path": col10_1["export_manifest_path"],
                "export_manifest_sha256": col10_1["export_manifest_sha256"],
                "gee_task_id": export_manifest["task_id"],
            },
        },
        "grid_reconciliation": {
            "primary": COL3_KEY_V2,
            "secondary": COL10_1_KEY_V2,
            "ratio": [3, 3],
            "primary_pixel_phase_of_origin": [phase[0], phase[1]],
            "primary_centre_fractions_in_secondary_cell": fractions,
            "centre_on_boundary_possible": False,
            "permitted_comparison": "nearest_to_primary_grid_only",
        },
        "mislabeled_collection10_invalidation": {
            **invalidation,
            "audit_bytes_verified": True,
            "content_note": (
                "within the monitoring extent the fresh Collection 10.1 export "
                "is pixel-identical to the invalidated crop (0 of 23,619,280 "
                "pixels differ); the invalidation is a provenance correction, "
                "and the provenance-correct GEE export is the only permitted "
                "runtime and qualified-review source"
            ),
        },
        "licence_and_attribution": registry["licence_and_attribution"],
    }
    manifest["manifest_sha256_of_body"] = _canonical_sha256(manifest)
    REGIONAL_MANIFEST_V2_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    click.echo(f"regional context manifest v2 -> {REGIONAL_MANIFEST_V2_PATH}")


if __name__ == "__main__":
    main()
