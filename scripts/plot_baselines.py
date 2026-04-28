"""Render the monthly baseline rasters as PNG figures for visual inspection.

For each vegetation index (NDMI, NBR, EVI2) this script produces:

1. A 4x3 grid figure showing the *mean* baseline for every calendar month —
   useful to verify spatial coverage and seasonal dynamics across the AOI.
2. A second 4x3 grid figure showing the *standard deviation* per month —
   helps spot months with poor scene coverage or high inter-annual noise.

The APA Chapada do Araripe and FLONA Araripe-Apodi contours are overlaid on
every panel so the geography is easy to locate.

Output is written to ``data/baselines/plots/``.

Usage::

    python scripts/plot_baselines.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.gridspec import GridSpec
from rasterio.warp import transform_bounds

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import AOI_DIR, BASELINES_DIR  # noqa: E402

PLOTS_DIR = BASELINES_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

INDEX_INFO = {
    "ndmi": {"label": "NDMI",  "vrange": (-0.5, 0.6),  "cmap": "RdYlGn"},
    "nbr":  {"label": "NBR",   "vrange": (-0.4, 0.8),  "cmap": "RdYlGn"},
    "evi2": {"label": "EVI2",  "vrange": (0.0,  0.7),  "cmap": "YlGn"},
}

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

CONTOURS = [
    ("APA_chapada_araripe.gpkg", "#FFD600", "APA Chapada do Araripe"),
    ("FLONA_araripe.gpkg",       "#00E676", "FLONA Araripe-Apodi"),
]


def _load_contours_in_crs(target_crs) -> list[tuple[gpd.GeoDataFrame, str, str]]:
    out = []
    for fname, color, label in CONTOURS:
        path = AOI_DIR / fname
        if not path.exists():
            continue
        gdf = gpd.read_file(str(path))
        if gdf.crs is not None and str(gdf.crs) != str(target_crs):
            gdf = gdf.to_crs(target_crs)
        out.append((gdf, color, label))
    return out


def _plot_panel(ax, data, transform, vrange, cmap, contours):
    """Render a single month panel with raster + contours."""
    # Build extent in raster CRS units
    height, width = data.shape
    left = transform.c
    top = transform.f
    right = left + transform.a * width
    bottom = top + transform.e * height
    extent = (left, right, bottom, top)

    # Mask NaN (no-data) pixels so they render as the colormap's "bad" colour
    # rather than as the midpoint, making "negative = real value" vs
    # "missing = no data" visually unambiguous.
    masked = np.ma.masked_invalid(data)
    cmap_obj = plt.get_cmap(cmap).copy()
    cmap_obj.set_bad(color="#d0d0d0", alpha=1.0)

    im = ax.imshow(
        masked,
        cmap=cmap_obj,
        vmin=vrange[0],
        vmax=vrange[1],
        extent=extent,
        origin="upper",
        interpolation="nearest",
    )

    for gdf, color, _label in contours:
        gdf.boundary.plot(ax=ax, color=color, linewidth=1.0)

    ax.set_xticks([])
    ax.set_yticks([])
    return im


def _make_grid(index: str, kind: str) -> Path | None:
    """Build a 4x3 grid of monthly baselines for one index/kind (mean|std)."""
    info = INDEX_INFO[index]
    label = info["label"]

    # Compute global vrange for std automatically; mean uses the index range.
    if kind == "mean":
        vrange = info["vrange"]
        cmap = info["cmap"]
        title_kind = "Mean"
    else:
        vrange = (0.0, 0.2)  # reasonable upper bound for normalized index std
        cmap = "magma"
        title_kind = "Std. Dev."

    # Load each month into memory to know which exist
    rasters = {}
    target_crs = None
    target_transform = None
    contours_in_raster_crs = None

    for month in range(1, 13):
        path = BASELINES_DIR / f"{index}_month{month:02d}_{kind}.tif"
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            arr = src.read(1, masked=False).astype(np.float32)
            # Convert any sentinel nodata (e.g. -3.4e+38, 0 in older COGs) to
            # NaN so the masked_invalid plotting path treats them uniformly.
            if src.nodata is not None and not np.isnan(src.nodata):
                arr = np.where(arr == np.float32(src.nodata), np.nan, arr)
            rasters[month] = (arr, src.transform, src.crs)
            if target_crs is None:
                target_crs = src.crs
                target_transform = src.transform

    if not rasters:
        print(f"  No {kind} rasters found for {index}")
        return None

    contours_in_raster_crs = _load_contours_in_crs(target_crs)

    fig = plt.figure(figsize=(16, 11))
    gs = GridSpec(4, 3, figure=fig, hspace=0.18, wspace=0.05)
    fig.suptitle(
        f"{label} monthly baseline — {title_kind}\n"
        f"AOI: Chapada do Araripe (yellow = APA, green = FLONA)",
        fontsize=14, fontweight="bold", y=0.995,
    )

    last_im = None
    for i, month in enumerate(range(1, 13)):
        ax = fig.add_subplot(gs[i // 3, i % 3])
        if month in rasters:
            arr, tr, _ = rasters[month]
            valid_pct = float(np.sum(~np.isnan(arr))) / arr.size * 100.0
            last_im = _plot_panel(ax, arr, tr, vrange, cmap, contours_in_raster_crs)
            ax.set_title(
                f"{MONTH_NAMES[month-1]} ({month:02d})  •  "
                f"{valid_pct:.1f}% valid",
                fontsize=10,
            )
        else:
            ax.text(0.5, 0.5, "no data", ha="center", va="center",
                    transform=ax.transAxes, color="gray")
            ax.set_title(f"{MONTH_NAMES[month-1]} ({month:02d})", fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])

    # Shared colorbar
    if last_im is not None:
        cbar_ax = fig.add_axes([0.25, 0.04, 0.5, 0.015])
        cb = fig.colorbar(last_im, cax=cbar_ax, orientation="horizontal")
        cb.set_label(f"{label} {title_kind}", fontsize=10)

    out_path = PLOTS_DIR / f"{index}_monthly_{kind}.png"
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.relative_to(ROOT)}")
    return out_path


def main() -> None:
    print(f"Rendering baseline plots into {PLOTS_DIR.relative_to(ROOT)}/")
    for index in INDEX_INFO:
        print(f"\n[{index.upper()}]")
        for kind in ("mean", "std"):
            _make_grid(index, kind)


if __name__ == "__main__":
    main()
