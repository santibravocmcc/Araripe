"""Offline tests for the pure helpers in src/acquisition/gee_download.py.

The EE-touching download itself needs live credentials and is validated by the
user's service account; here we cover the geometry (tile grid), the raster
mosaic, and the download-payload parsing — the parts that can silently corrupt
output if wrong.
"""

import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.acquisition.gee_download import (  # noqa: E402
    _bytes_to_tif,
    compute_tile_grid,
    mosaic_tiles,
)

AOI = [-40.90, -7.85, -38.95, -6.95]


def test_tile_grid_covers_bbox():
    tiles = compute_tile_grid(AOI, scale=20, tile_px=1024)
    assert len(tiles) == 55  # ~11 x 5 for this AOI at 1024px/20m
    # Every tile lies within the bbox, and the corners touch the bbox extremes.
    for w, s, e, n in tiles:
        assert AOI[0] - 1e-9 <= w < e <= AOI[2] + 1e-9
        assert AOI[1] - 1e-9 <= s < n <= AOI[3] + 1e-9
    xs = [t[0] for t in tiles]; ys = [t[1] for t in tiles]
    assert min(xs) == pytest.approx(AOI[0])
    assert min(ys) == pytest.approx(AOI[1])
    assert max(t[2] for t in tiles) == pytest.approx(AOI[2])
    assert max(t[3] for t in tiles) == pytest.approx(AOI[3])


def test_tile_grid_smaller_tiles_more_pieces():
    coarse = compute_tile_grid(AOI, scale=20, tile_px=4096)
    fine = compute_tile_grid(AOI, scale=20, tile_px=512)
    assert len(fine) > len(coarse)


def test_tile_grid_rejects_bad_bounds():
    with pytest.raises(ValueError):
        compute_tile_grid([0, 0, -1, 1])


def _write_tif(path, origin_x, origin_y, bands=4, size=8, fill=1.0):
    transform = from_origin(origin_x, origin_y, 20, 20)  # 20 m pixels
    with rasterio.open(
        str(path), "w", driver="GTiff", height=size, width=size, count=bands,
        dtype="float32", crs="EPSG:32724", transform=transform, nodata=-9999.0,
    ) as dst:
        for b in range(1, bands + 1):
            dst.write(np.full((size, size), fill * b, dtype="float32"), b)


def test_mosaic_preserves_bands_and_grows_extent(tmp_path):
    a = tmp_path / "a.tif"; b = tmp_path / "b.tif"
    _write_tif(a, 500000, 9100000)           # left tile
    _write_tif(b, 500000 + 8 * 20, 9100000)  # right tile, adjacent
    out = mosaic_tiles([a, b], tmp_path / "mosaic.tif", nodata=-9999.0)
    with rasterio.open(str(out)) as src:
        assert src.count == 4                 # multiband preserved
        assert src.width == 16                # two 8-px tiles side by side
        assert src.height == 8
        assert src.nodata == -9999.0
        assert src.dtypes[0] == "float32"


def test_bytes_to_tif_passthrough_geotiff(tmp_path):
    src_tif = tmp_path / "src.tif"
    _write_tif(src_tif, 500000, 9100000, bands=2, size=4)
    raw = src_tif.read_bytes()
    dest = tmp_path / "out.tif"
    _bytes_to_tif(raw, dest)
    with rasterio.open(str(dest)) as src:
        assert src.count == 2


def test_bytes_to_tif_unwraps_single_tif_zip(tmp_path):
    src_tif = tmp_path / "src.tif"
    _write_tif(src_tif, 500000, 9100000, bands=3, size=4)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("download.tif", src_tif.read_bytes())
    dest = tmp_path / "out.tif"
    _bytes_to_tif(buf.getvalue(), dest)
    with rasterio.open(str(dest)) as src:
        assert src.count == 3


def test_bytes_to_tif_rejects_garbage(tmp_path):
    with pytest.raises(RuntimeError):
        _bytes_to_tif(b"not-a-tiff-or-zip", tmp_path / "x.tif")
