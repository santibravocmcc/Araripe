#!/usr/bin/env python3
"""Crop a national MapBiomas coverage GeoTIFF to the Araripe display window.

The national files are multi-gigabyte single-band ``uint8`` rasters whose pixel
values are MapBiomas legend class IDs. This script reads only the window that
covers the Araripe display rectangle — on the source's own grid, so no pixel is
resampled — and writes a small tiled, compressed crop plus a JSON report that
binds the crop to the exact national bytes it came from (size, SHA-256, MD5,
origin URL). The report is what survives once the national file is deleted.

The window is the territory/display rectangle ``(-41.0, -8.0, -38.8, -6.8)``,
the same one the 2023 crops used. It contains the registered monitoring extent
``araripe-implementation-rectangle-v1`` (W -40.892, S -7.841, E -38.952,
N -6.957), checked below; it is a presentation window, not a new AOI.

Class ``0`` is written as the declared NoData: the national headers leave
NoData unset, and the official legends (Collection 11 and 10 m Collection 4,
published 2026-08) assign no class to ``0``.

Usage:

    python scripts/crop_mapbiomas_national.py \
        --src ~/Downloads/brazil_coverage-col11_2025.tif \
        --out data/landcover/mapbiomas_col11_30m_2025_araripe.tif \
        --origin-url https://storage.googleapis.com/.../brazil_coverage-col11_2025.tif \
        --collection "Coleção 11" --year 2025
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import click
import numpy as np
import rasterio
from rasterio.windows import from_bounds

DISPLAY_WINDOW = (-41.0, -8.0, -38.8, -6.8)
MONITORING_EXTENT = (
    -40.89236812577142,
    -7.840780758480428,
    -38.95208146319247,
    -6.957104781339829,
)


def _digests(path: Path) -> dict[str, str]:
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return {"sha256": sha.hexdigest(), "md5": md5.hexdigest()}


@click.command()
@click.option("--src", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--origin-url", required=True)
@click.option("--collection", required=True, help='e.g. "Coleção 11" or "Coleção 4 (10 m)"')
@click.option("--year", type=int, required=True)
def main(src: Path, out: Path, origin_url: str, collection: str, year: int) -> None:
    source_digests = _digests(src)
    with rasterio.open(src) as ds:
        if ds.count != 1 or ds.dtypes[0] != "uint8":
            raise click.ClickException(f"expected one uint8 band, got {ds.count} × {ds.dtypes}")
        if ds.crs.to_epsg() != 4326:
            raise click.ClickException(f"expected EPSG:4326, got {ds.crs}")
        window = from_bounds(*DISPLAY_WINDOW, transform=ds.transform)
        window = window.round_offsets().round_lengths()
        data = ds.read(1, window=window)
        transform = ds.window_transform(window)
        source_header = {
            "width": ds.width,
            "height": ds.height,
            "res_deg": list(ds.res),
            "bounds": list(ds.bounds),
            "nodata": ds.nodata,
            "compression": str(ds.compression),
        }
        profile = ds.profile.copy()

    height, width = data.shape
    west, north = transform.c, transform.f
    east = west + transform.a * width
    south = north + transform.e * height
    mw, ms, me, mn = MONITORING_EXTENT
    if not (west <= mw and south <= ms and east >= me and north >= mn):
        raise click.ClickException("crop does not contain the monitoring extent")

    profile.update(
        width=width, height=height, transform=transform, nodata=0,
        compress="lzw", tiled=True, blockxsize=256, blockysize=256,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(data, 1)

    codes, counts = np.unique(data, return_counts=True)
    report = {
        "collection": collection,
        "year": year,
        "origin_url": origin_url,
        "source": {"path_at_crop_time": str(src), "bytes": src.stat().st_size,
                   **source_digests, **source_header},
        "window_requested": list(DISPLAY_WINDOW),
        "window_contains_extent": "araripe-implementation-rectangle-v1",
        "resampling": "none (native grid window read)",
        "crop": {
            "path": out.as_posix(),
            "bytes": out.stat().st_size,
            "sha256": _digests(out)["sha256"],
            "width": width,
            "height": height,
            "bounds": [west, south, east, north],
            "transform": list(transform)[:6],
            "nodata": 0,
            "histogram": {str(int(c)): int(n) for c, n in zip(codes, counts)},
        },
        "cropped_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "software": {"rasterio": rasterio.__version__, "numpy": np.__version__},
    }
    report_path = out.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    click.echo(json.dumps({k: report["crop"][k] for k in ("width", "height", "sha256", "histogram")}))


if __name__ == "__main__":
    main()
