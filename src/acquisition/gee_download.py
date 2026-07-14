"""Headless Google Earth Engine auth + synchronous tiled image download.

This is the transport layer for the *CI* detection path
(``scripts/run_detection_gee.py``). It lets a GitHub Actions job compute a
composite on Google's servers and pull it down over a region **synchronously**
— no Export tasks, no Google Drive, no GCS bucket — so the runner never touches
the throttled AWS S3 stream and never waits on async batch tasks.

Two concerns, deliberately separated so the non-EE logic is unit-testable:

* ``ee_initialize`` — authenticate non-interactively with a **service account**
  (JSON key from an env var / GitHub secret), or fall back to interactive local
  auth. Uses the Earth Engine **high-volume** endpoint (recommended for
  automated jobs).
* ``compute_tile_grid`` / ``mosaic_tiles`` — pure geometry + raster helpers,
  testable without EE. ``download_image_tiled`` glues them to EE.

Limits that drive the design (see docs/DETECTION_GEE.md for sources):
``getDownloadURL`` caps a single request at ~32 MB and 10000 px/side, so an
AOI-wide 20 m 4-band float32 image (~860 MB) must be tiled (~1024 px tiles →
~55 requests). Each tile is a georeferenced GeoTIFF, so ``rasterio.merge``
reassembles them by geotransform (no manual pixel alignment needed).

NOTE: the EE-touching paths require live Earth Engine credentials and have not
been exercised in this repo's offline test env — validate end-to-end with your
service account before relying on the CI job. The pure helpers are tested in
tests/test_gee_download.py.
"""

from __future__ import annotations

import io
import math
import os
import time
import zipfile
from pathlib import Path
from typing import Sequence

from loguru import logger

HIGH_VOLUME_URL = "https://earthengine-highvolume.googleapis.com"


# ─── auth ─────────────────────────────────────────────────────────────────────
def ee_initialize(project: str, *, high_volume: bool = True):
    """Initialize Earth Engine for headless or interactive use.

    Auth precedence:
      1. ``GEE_SA_KEY``  — the full service-account JSON *key string* (ideal for
         a GitHub secret). No file is written to disk.
      2. ``GEE_SA_KEY_FILE`` — path to a service-account JSON key file.
      3. interactive credentials already on the machine (local dev).
    """
    import ee

    opt_url = HIGH_VOLUME_URL if high_volume else None
    key_str = os.environ.get("GEE_SA_KEY")
    key_file = os.environ.get("GEE_SA_KEY_FILE")

    if key_str:
        # key_data takes the JSON *string*; the SA email is read from the JSON,
        # so the email arg is ignored.
        creds = ee.ServiceAccountCredentials(email="", key_data=key_str)
        ee.Initialize(creds, project=project, opt_url=opt_url)
        logger.info("EE initialized via GEE_SA_KEY (service account, high-volume={})", high_volume)
    elif key_file:
        creds = ee.ServiceAccountCredentials(email="", key_file=key_file)
        ee.Initialize(creds, project=project, opt_url=opt_url)
        logger.info("EE initialized via GEE_SA_KEY_FILE={}", key_file)
    else:
        ee.Initialize(project=project, opt_url=opt_url)
        logger.info("EE initialized via interactive/default credentials")


# ─── pure helpers (unit-testable, no EE) ───────────────────────────────────────
def compute_tile_grid(bounds: Sequence[float], scale: float = 20.0,
                      tile_px: int = 1024) -> list[tuple[float, float, float, float]]:
    """Split a lon/lat bbox [w, s, e, n] into sub-rectangles, each small enough
    that a getDownloadURL request stays under the ~32 MB / 10000 px cap.

    ``tile_px`` is the target max pixels per tile side at ``scale`` metres.
    Returns a list of [w, s, e, n] rectangles covering the bbox.
    """
    w, s, e, n = bounds
    if not (e > w and n > s):
        raise ValueError(f"Invalid bounds {bounds!r} (need e>w and n>s)")
    lat_mid = math.radians((s + n) / 2.0)
    m_per_deg_lat = 110_540.0
    m_per_deg_lon = 111_320.0 * max(math.cos(lat_mid), 1e-6)
    tile_m = tile_px * scale
    step_lon = tile_m / m_per_deg_lon
    step_lat = tile_m / m_per_deg_lat
    n_lon = max(1, math.ceil((e - w) / step_lon))
    n_lat = max(1, math.ceil((n - s) / step_lat))

    tiles: list[tuple[float, float, float, float]] = []
    for j in range(n_lat):
        ts = s + j * step_lat
        tn = min(n, s + (j + 1) * step_lat)
        for i in range(n_lon):
            tw = w + i * step_lon
            te = min(e, w + (i + 1) * step_lon)
            tiles.append((tw, ts, te, tn))
    return tiles


def mosaic_tiles(tile_paths: Sequence[Path], out_path: Path,
                nodata: float = -9999.0) -> Path:
    """Merge per-tile GeoTIFFs into one multiband GeoTIFF (by geotransform)."""
    import rasterio
    from rasterio.merge import merge

    srcs = [rasterio.open(str(p)) for p in tile_paths]
    try:
        mosaic, transform = merge(srcs, nodata=nodata)
        meta = srcs[0].meta.copy()
        meta.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2],
                    count=mosaic.shape[0], transform=transform, nodata=nodata,
                    dtype="float32", compress="deflate")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(str(out_path), "w", **meta) as dst:
            dst.write(mosaic.astype("float32"))
        return out_path
    finally:
        for sc in srcs:
            sc.close()


def _bytes_to_tif(content: bytes, dest: Path) -> None:
    """Write a getDownloadURL payload to ``dest`` as a GeoTIFF.

    Handles both a single multiband GEO_TIFF and a zip (older default) — if the
    zip holds per-band tifs it stacks them into one multiband file.
    """
    if content[:2] in (b"II", b"MM"):  # TIFF magic → single multiband tif
        dest.write_bytes(content)
        return
    if content[:4] == b"PK\x03\x04":  # zip
        import rasterio
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = sorted(n for n in zf.namelist() if n.lower().endswith(".tif"))
            if not names:
                raise RuntimeError("Downloaded zip contained no .tif")
            if len(names) == 1:
                dest.write_bytes(zf.read(names[0]))
                return
            # multiple per-band tifs → stack as bands
            arrs, meta = [], None
            for nm in names:
                with rasterio.open(io.BytesIO(zf.read(nm))) as src:
                    arrs.append(src.read(1))
                    if meta is None:
                        meta = src.meta.copy()
            meta.update(count=len(arrs), dtype="float32", driver="GTiff")
            with rasterio.open(str(dest), "w", **meta) as dst:
                for bi, a in enumerate(arrs, start=1):
                    dst.write(a.astype("float32"), bi)
        return
    raise RuntimeError(f"Unrecognized download payload (first bytes {content[:8]!r})")


def download_image_tiled(image, bounds: Sequence[float], out_path: Path, *,
                        bands: Sequence[str], scale: float = 20.0,
                        crs: str = "EPSG:32724", tile_px: int = 1024,
                        max_retries: int = 5, tmp_dir: Path | None = None) -> Path:
    """Download an ``ee.Image`` over ``bounds`` as one multiband GeoTIFF.

    Requests each tile via ``getDownloadURL(format='GEO_TIFF')`` (synchronous),
    with exponential backoff on transient/429 errors, then mosaics with
    ``rasterio.merge``. Returns ``out_path``.
    """
    import ee
    import requests
    from requests import HTTPError

    out_path = Path(out_path)
    tmp_dir = Path(tmp_dir) if tmp_dir else out_path.parent / f".{out_path.stem}_tiles"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    img = image.select(list(bands)).toFloat()
    grid = compute_tile_grid(bounds, scale=scale, tile_px=tile_px)
    logger.info("Downloading {} in {} tiles ({}px @ {}m, crs {})",
                out_path.name, len(grid), tile_px, scale, crs)

    tile_paths: list[Path] = []
    for k, (tw, ts, te, tn) in enumerate(grid):
        region = ee.Geometry.Rectangle([tw, ts, te, tn], proj="EPSG:4326", geodesic=False)
        params = {"region": region, "scale": scale, "crs": crs,
                  "format": "GEO_TIFF", "filePerBand": False}
        last_err = None
        for attempt in range(max_retries):
            try:
                url = img.getDownloadURL(params)
                resp = requests.get(url, timeout=300)
                if resp.status_code == 200:
                    dest = tmp_dir / f"tile_{k:04d}.tif"
                    _bytes_to_tif(resp.content, dest)
                    tile_paths.append(dest)
                    break
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {resp.status_code}")  # transient → retry
                resp.raise_for_status()  # 4xx (bad params/auth/not-found) → abort
            except HTTPError:
                # Deterministic non-retryable HTTP error: fail fast, don't burn
                # the retry budget (~31s) on something that will never succeed.
                raise
            except Exception as ex:  # transient EE/HTTP → backoff
                last_err = ex
                if attempt < max_retries - 1:
                    sleep_s = min(60, 2 ** attempt)
                    logger.warning("tile {} attempt {} failed ({}); retrying in {}s",
                                   k, attempt + 1, ex, sleep_s)
                    time.sleep(sleep_s)
                # On the final attempt, fall through WITHOUT break so the for/else
                # raises below (a break would skip else and drop the tile silently).
        else:
            raise RuntimeError(f"Tile {k} failed after {max_retries} retries: {last_err}")

    return mosaic_tiles(tile_paths, out_path)
