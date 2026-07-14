"""Split the Earth Engine monthly exports into the per-index baseline COGs.

Input: the 12 GeoTIFFs produced by scripts/build_baseline_gee.py and downloaded
from Google Drive (araripe_baseline_monthNN.tif), each with 6 bands in this
order: ndmi_mean, nbr_mean, evi2_mean, ndmi_std, nbr_std, evi2_std.

Output: the 72 files the detector reads —
    data/baselines/<index>_month<NN>_{mean,std}.tif
each a single-band COG with nodata=NaN (the -9999 export sentinel is restored to
NaN, and any |value|>1.5 numerical artefact is also masked).

Usage:
    python scripts/split_gee_baselines.py --in-dir ~/Downloads/araripe_baselines --out-dir data/baselines
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click
import numpy as np
import rasterio

BANDS = ["ndmi_mean", "nbr_mean", "evi2_mean", "ndmi_std", "nbr_std", "evi2_std"]
_MONTH_RE = re.compile(r"month(\d{1,2})", re.IGNORECASE)


def _write_cog(arr, src, out_path):
    profile = src.profile.copy()
    profile.update(count=1, dtype="float32", nodata=float("nan"),
                   driver="GTiff", compress="deflate", tiled=True,
                   blockxsize=256, blockysize=256)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr.astype("float32"), 1)


@click.command()
@click.option("--in-dir", required=True, type=click.Path(exists=True), help="Dir with araripe_baseline_month*.tif from Drive.")
@click.option("--out-dir", default="data/baselines", help="Output baselines dir.")
def main(in_dir, out_dir):
    in_dir = Path(in_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(in_dir.glob("*month*.tif"))
    if not files:
        print(f"No *month*.tif found in {in_dir}")
        raise SystemExit(1)

    n_written = 0
    for f in files:
        mm = _MONTH_RE.search(f.stem)
        if not mm:
            print(f"  skip {f.name}: no month in name")
            continue
        month = int(mm.group(1))
        with rasterio.open(f) as src:
            if src.count < 6:
                print(f"  skip {f.name}: expected 6 bands, got {src.count}")
                continue
            # Prefer band descriptions if GEE wrote them; else fall back to the
            # known export order.
            descs = [d.lower() if d else "" for d in src.descriptions]
            order = BANDS
            if all(b in descs for b in BANDS):
                order = descs  # already the band names
            for i in range(6):
                name = order[i] if order[i] in BANDS else BANDS[i]
                idx, stat = name.split("_")
                arr = src.read(i + 1).astype("float32")
                # Restore nodata: the -9999 sentinel and any gross artefact.
                arr[arr <= -9990] = np.nan
                arr[np.abs(arr) > 1.5] = np.nan
                out_path = out_dir / f"{idx}_month{month:02d}_{stat}.tif"
                _write_cog(arr, src, out_path)
                n_written += 1
        print(f"  {f.name} -> 6 baseline COGs (month {month:02d})")

    print(f"\nWrote {n_written} baseline COGs to {out_dir}.")
    print("Next: set REFLECTANCE_SCALING = True in config/settings.py so detection "
          "produces reflectance to match these reflectance baselines (Task 1 coupling), "
          "then run `pytest -q` and a detection sanity check.")


if __name__ == "__main__":
    main()
