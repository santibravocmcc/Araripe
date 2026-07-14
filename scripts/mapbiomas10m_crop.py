#!/usr/bin/env python3
"""Inspect, crop and validate the MapBiomas 10 m (Sentinel-2) national GeoTIFF.

The MapBiomas 10 m beta collection ships as a single national land-cover
classification raster (~5 GB, EPSG:4326, ~10 m, uint8 class codes). This
script evaluates whether the product is usable for the Chapada do Araripe
project by:

  1. INSPECT   — print the raster header (grid, CRS, resolution, compression,
                 nodata, overviews) without loading the whole array.
  2. CROP      — windowed read of only the Araripe bounding box and write a
                 compressed, tiled GeoTIFF (safe on machines with little RAM).
  3. VALIDATE  — check the crop's spatial extent, dtype, class histogram and
                 valid-data fraction against expectations.
  4. (opt) DELETE the multi-gigabyte national source after a successful,
                 validated crop, to free disk space.

Usage:
    python scripts/mapbiomas10m_crop.py \
        --src ~/Downloads/mapbiomas_10m_collection2_integration_v1-classification_2023.tif \
        --out data/landcover/mapbiomas10m_araripe_2023.tif

    # Also delete the national source once the crop validates:
    python scripts/mapbiomas10m_crop.py --src ... --out ... --delete-source

The default crop window matches the partner's territorio display window
(-41.0, -8.0, -38.8, -6.8) so the 10 m product is directly comparable with
the existing 30 m territorio maps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window

# Territorio display window (west, south, east, north) in EPSG:4326.
# Matches site/scripts/prepare_territorio.py::BBOX and comfortably covers the
# APA (-40.89..-38.95, -7.84..-6.96) and the detection AOI (-40..-39, -8..-7).
DEFAULT_BBOX = (-41.0, -8.0, -38.8, -6.8)

# MapBiomas class legend (subset relevant to the region). Codes follow the
# MapBiomas Collection legend; unlisted codes are printed as "class N".
MAPBIOMAS_LEGEND = {
    0: "No data / not observed",
    3: "Forest formation",
    4: "Savanna formation",
    5: "Mangrove",
    6: "Flooded forest",
    9: "Forest plantation",
    11: "Wetland",
    12: "Grassland formation",
    15: "Pasture",
    18: "Agriculture",
    19: "Temporary crop",
    20: "Sugar cane",
    21: "Mosaic of uses (ag/pasture)",
    23: "Beach, dune and sand spot",
    24: "Urban area",
    25: "Other non-vegetated area",
    29: "Rocky outcrop",
    30: "Mining",
    31: "Aquaculture",
    32: "Hypersaline tidal flat",
    33: "River, lake and ocean",
    35: "Palm oil",
    39: "Soybean",
    40: "Rice",
    41: "Other temporary crops",
    46: "Coffee",
    47: "Citrus",
    48: "Other perennial crops",
    49: "Wooded sandbank vegetation",
    50: "Herbaceous sandbank vegetation",
}


def label(code: int) -> str:
    return MAPBIOMAS_LEGEND.get(int(code), f"class {int(code)}")


def inspect(src_path: Path) -> dict:
    """Print and return header-level metadata for the source raster."""
    with rasterio.open(src_path) as ds:
        info = {
            "path": str(src_path),
            "size_bytes": src_path.stat().st_size,
            "width": ds.width,
            "height": ds.height,
            "gigapixels": round(ds.width * ds.height / 1e9, 2),
            "count": ds.count,
            "dtype": ds.dtypes[0],
            "crs": str(ds.crs),
            "bounds": [round(b, 5) for b in ds.bounds],
            "res_deg": [ds.res[0], ds.res[1]],
            "res_m_approx": round(ds.res[0] * 111_320, 2),
            "nodata": ds.nodata,
            "tiled": ds.is_tiled,
            "block_shape": ds.block_shapes[0],
            "compression": str(ds.compression),
            "overviews_b1": ds.overviews(1),
            "band1_tags": ds.tags(1),
        }
    print("── INSPECT ──────────────────────────────────────────────")
    print(f"  file            : {info['path']}")
    print(f"  size            : {info['size_bytes'] / 1e9:.2f} GB")
    print(f"  grid            : {info['width']} x {info['height']} px "
          f"({info['gigapixels']} Gpx), {info['count']} band(s) {info['dtype']}")
    print(f"  crs             : {info['crs']}")
    print(f"  resolution      : {info['res_deg'][0]:.3e}° (~{info['res_m_approx']} m)")
    print(f"  bounds (WSEN)   : {info['bounds']}")
    print(f"  nodata          : {info['nodata']}")
    print(f"  tiled/block     : {info['tiled']} / {info['block_shape']}")
    print(f"  compression     : {info['compression']}")
    print(f"  overviews (b1)  : {info['overviews_b1'] or 'NONE'}")
    print(f"  band-1 tags     : {info['band1_tags']}")
    return info


def crop(src_path: Path, out_path: Path, bbox: tuple) -> dict:
    """Windowed crop of `bbox` (WSEN, EPSG:4326) into a tiled DEFLATE GeoTIFF."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    west, south, east, north = bbox
    with rasterio.open(src_path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            print(f"  WARNING: source CRS is {ds.crs}, bbox is EPSG:4326 — "
                  "reproject the bbox first if this is not lon/lat.", file=sys.stderr)
        # Intersect requested bbox with the raster footprint.
        b = ds.bounds
        iw, ie = max(west, b.left), min(east, b.right)
        isouth, inorth = max(south, b.bottom), min(north, b.top)
        if iw >= ie or isouth >= inorth:
            raise SystemExit("Requested bbox does not intersect the raster.")
        window = from_bounds(iw, isouth, ie, inorth, ds.transform)
        window = window.round_offsets().round_lengths()
        # Clamp to the raster extent.
        window = window.intersection(Window(0, 0, ds.width, ds.height))
        transform = ds.window_transform(window)
        print("── CROP ─────────────────────────────────────────────────")
        print(f"  bbox (WSEN)     : {[round(x, 4) for x in bbox]}")
        print(f"  window          : col_off={int(window.col_off)}, row_off={int(window.row_off)}, "
              f"{int(window.width)} x {int(window.height)} px")
        data = ds.read(1, window=window)  # only the window is read into RAM
        profile = ds.profile.copy()
        profile.update(
            width=int(window.width),
            height=int(window.height),
            transform=transform,
            compress="deflate",
            predictor=2,
            tiled=True,
            blockxsize=256,
            blockysize=256,
            BIGTIFF="IF_SAFER",
        )
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
            # Copy the colormap if the source carries one (nice for QGIS).
            try:
                dst.write_colormap(1, ds.colormap(1))
            except (ValueError, IndexError):
                pass
    size_mb = out_path.stat().st_size / 1e6
    print(f"  wrote           : {out_path} ({size_mb:.1f} MB)")
    return {"out_path": str(out_path), "size_mb": round(size_mb, 1),
            "width": int(window.width), "height": int(window.height)}


def validate(out_path: Path, bbox: tuple) -> dict:
    """Validate the crop: extent, dtype, class histogram, valid fraction."""
    west, south, east, north = bbox
    with rasterio.open(out_path) as ds:
        arr = ds.read(1)
        b = ds.bounds
        # Extent within one pixel of the requested bbox (after clamping).
        tol = 2 * ds.res[0]
        extent_ok = (abs(b.left - max(west, b.left)) <= tol
                     and abs(b.top - min(north, b.top)) <= tol)
        codes, counts = np.unique(arr, return_counts=True)
        total = int(arr.size)
        nodata = ds.nodata
        # Treat 0 as "no data / not observed" for the valid fraction.
        invalid = int(counts[codes == 0].sum()) if 0 in codes else 0
        if nodata is not None and nodata != 0:
            invalid += int(counts[codes == nodata].sum())
        valid_frac = 1.0 - invalid / total if total else 0.0
        hist = {int(c): int(n) for c, n in zip(codes, counts)}
    print("── VALIDATE ─────────────────────────────────────────────")
    print(f"  crop bounds     : {[round(x, 5) for x in b]}")
    print(f"  grid            : {ds.width} x {ds.height} px, dtype {arr.dtype}")
    print(f"  valid fraction  : {valid_frac:.1%}  (class 0 / nodata excluded)")
    print(f"  distinct classes: {len(hist)}")
    print("  class histogram (by area):")
    for code in sorted(hist, key=lambda c: -hist[c]):
        pct = 100 * hist[code] / total
        if pct >= 0.01:
            print(f"    {code:>3}  {label(code):<32} {pct:6.2f}%  ({hist[code]:,} px)")
    checks = {
        "dtype_uint8": str(arr.dtype) == "uint8",
        "extent_within_tol": bool(extent_ok),
        "has_valid_data": valid_frac > 0.5,
        "plausible_classes": all(0 <= c <= 62 for c in hist),
        "vegetation_present": any(c in hist for c in (3, 4, 12)),
    }
    print("  checks:")
    for k, v in checks.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")
    passed = all(checks.values())
    print(f"  RESULT          : {'ALL CHECKS PASSED' if passed else 'VALIDATION FAILED'}")
    return {"passed": passed, "valid_frac": round(valid_frac, 4),
            "histogram": hist, "checks": checks,
            "bounds": [round(x, 5) for x in b]}


@click.command()
@click.option("--src", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to the national MapBiomas 10 m GeoTIFF.")
@click.option("--out", default=Path("data/landcover/mapbiomas10m_araripe_2023.tif"),
              type=click.Path(path_type=Path), help="Output cropped GeoTIFF.")
@click.option("--bbox", default=None,
              help="Override crop bbox as 'W,S,E,N' (EPSG:4326). Default = territorio window.")
@click.option("--delete-source", is_flag=True, default=False,
              help="Delete the national source AFTER a successful validation.")
def main(src: Path, out: Path, bbox: str | None, delete_source: bool) -> None:
    """Inspect → crop → validate the MapBiomas 10 m national raster."""
    crop_bbox = DEFAULT_BBOX
    if bbox:
        crop_bbox = tuple(float(x) for x in bbox.split(","))
        if len(crop_bbox) != 4:
            raise SystemExit("--bbox must be 'W,S,E,N'")

    inspect_info = inspect(src)
    crop_info = crop(src, out, crop_bbox)
    val = validate(out, crop_bbox)

    report = {"source": inspect_info, "crop": crop_info, "validation": val}
    report_path = out.with_suffix(".report.json")
    with open(report_path, "w") as fp:
        json.dump(report, fp, indent=2, default=str)
    print(f"\nReport written to {report_path}")

    if delete_source:
        if val["passed"]:
            freed = src.stat().st_size / 1e9
            src.unlink()
            print(f"Deleted source {src} — freed {freed:.2f} GB.")
        else:
            print("Validation FAILED — source NOT deleted.", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
