"""Build monthly baseline COGs from downloaded per-scene GeoTIFF files.

Takes the per-scene, per-tile files downloaded by a colleague (3-band GeoTIFFs
containing NDMI, NBR, EVI2) and produces the baseline COGs expected by the
detection pipeline: {index}_month{MM}_mean.tif and {index}_month{MM}_std.tif.

Steps per month:
  1. Group files by acquisition date
  2. Merge tiles for each date into a single AOI-extent raster
  3. Clip to AOI polygon
  4. Cap EVI2 values at 1.0 (residual cloud contamination filter)
  5. Compute pixel-wise median and std across all dates
  6. Save as Cloud Optimized GeoTIFFs

Usage:
    python scripts/build_baseline_from_downloads.py
    python scripts/build_baseline_from_downloads.py --months 1,2,3
    python scripts/build_baseline_from_downloads.py --input-dir data/baselines --dry-run
"""

from __future__ import annotations

import gc
import sys
from collections import defaultdict
from pathlib import Path

import click
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform

BAND_NAMES = ["ndmi", "nbr", "evi2"]
BAND_INDEX = {"ndmi": 1, "nbr": 2, "evi2": 3}  # 1-based rasterio band index
EVI2_CAP = 1.0
TARGET_CRS = "EPSG:32724"
RESOLUTION = 20.0  # meters


def load_aoi(aoi_dir: Path) -> gpd.GeoDataFrame:
    """Load AOI polygon, preferring GeoPackage over GeoJSON."""
    for name in ["APA_chapada_araripe.gpkg", "chapada_araripe.gpkg", "chapada_araripe.geojson"]:
        path = aoi_dir / name
        if path.exists():
            gdf = gpd.read_file(str(path))
            if gdf.crs is not None and str(gdf.crs) != TARGET_CRS:
                gdf = gdf.to_crs(TARGET_CRS)
            print(f"  AOI loaded from {path.name} ({len(gdf)} feature(s))")
            return gdf
    raise FileNotFoundError(f"No AOI file found in {aoi_dir}")


def compute_target_grid(aoi_gdf: gpd.GeoDataFrame) -> tuple:
    """Compute the target raster grid (transform, width, height) from AOI bounds."""
    bounds = aoi_gdf.total_bounds  # [minx, miny, maxx, maxy]
    # Snap bounds to resolution grid
    minx = np.floor(bounds[0] / RESOLUTION) * RESOLUTION
    miny = np.floor(bounds[1] / RESOLUTION) * RESOLUTION
    maxx = np.ceil(bounds[2] / RESOLUTION) * RESOLUTION
    maxy = np.ceil(bounds[3] / RESOLUTION) * RESOLUTION

    width = int((maxx - minx) / RESOLUTION)
    height = int((maxy - miny) / RESOLUTION)
    transform = rasterio.transform.from_bounds(minx, miny, maxx, maxy, width, height)

    print(f"  Target grid: {width}x{height} pixels ({width*RESOLUTION/1000:.1f}x{height*RESOLUTION/1000:.1f} km)")
    return transform, width, height, (minx, miny, maxx, maxy)


def group_files_by_date(
    month_dir: Path,
    min_year: int | None = None,
    max_year: int | None = None,
) -> dict[str, list[Path]]:
    """Group .tif files by acquisition date (first 8 chars of filename).

    Skips macOS resource fork files (._*) and any file whose name doesn't
    start with a valid 8-digit date. Optionally filters by year so the
    baseline is built only from the requested calendar window.
    """
    groups = defaultdict(list)
    for f in sorted(month_dir.glob("*.tif")):
        if f.name.startswith("._") or f.name.startswith("."):
            continue
        date_str = f.name[:8]
        if not date_str.isdigit():
            continue
        year = int(date_str[:4])
        if min_year is not None and year < min_year:
            continue
        if max_year is not None and year > max_year:
            continue
        groups[date_str].append(f)
    return dict(groups)


def merge_tiles_to_grid(
    tile_paths: list[Path],
    target_bounds: tuple,
    target_transform: rasterio.Affine,
    width: int,
    height: int,
    band_idx: int,
) -> np.ndarray:
    """Merge multiple tiles for one date into the target grid for a single band.

    Returns a 2D float32 array (height, width) with NaN for no-data.
    """
    datasets = []
    try:
        for p in tile_paths:
            ds = rasterio.open(p)
            datasets.append(ds)

        merged, merged_transform = merge(
            datasets,
            bounds=target_bounds,
            res=RESOLUTION,
            indexes=[band_idx],
            nodata=np.nan,
            method="first",
        )
        # merged shape: (1, height, width)
        result = merged[0].astype(np.float32)
        return result
    finally:
        for ds in datasets:
            ds.close()


def apply_aoi_mask(data: np.ndarray, aoi_gdf: gpd.GeoDataFrame,
                   transform: rasterio.Affine, shape: tuple) -> np.ndarray:
    """Mask pixels outside the AOI polygon to NaN."""
    mask = geometry_mask(
        aoi_gdf.geometry,
        out_shape=shape,
        transform=transform,
        invert=False,  # True = inside polygon; False = outside polygon is True
    )
    # mask is True where pixels are OUTSIDE the geometry
    data[mask] = np.nan
    return data


def save_cog(data: np.ndarray, path: Path, transform: rasterio.Affine,
             crs: str, nodata: float = np.nan) -> None:
    """Save a 2D array as a Cloud Optimized GeoTIFF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = data.shape

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
    }

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype(np.float32), 1)

    # Convert to COG using GDAL (adds overviews)
    try:
        import subprocess
        tmp_path = path.with_suffix(".tmp.tif")
        subprocess.run(
            ["gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE",
             str(path), str(tmp_path)],
            check=True, capture_output=True,
        )
        tmp_path.replace(path)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # gdal_translate not available or failed — keep the tiled GeoTIFF
        pass


@click.command()
@click.option(
    "--input-dir", type=click.Path(exists=True, path_type=Path),
    default=Path("data/baselines"),
    help="Parent directory containing temp_month_XX subdirectories. "
         "Can point to an external drive (e.g., /Volumes/Expansion/...).",
)
@click.option(
    "--output-dir", type=click.Path(path_type=Path),
    default=Path("data/baselines"),
    help="Directory for output baseline COGs.",
)
@click.option(
    "--aoi-dir", type=click.Path(exists=True, path_type=Path),
    default=Path("data/aoi"),
    help="Directory containing the AOI polygon file.",
)
@click.option(
    "--months", type=str, default="",
    help="Comma-separated months to process (e.g., '1,2,3'). Empty = all available.",
)
@click.option(
    "--min-year", type=int, default=None,
    help="Only include scenes from this year onwards (inclusive).",
)
@click.option(
    "--max-year", type=int, default=None,
    help="Only include scenes up to this year (inclusive). Useful to lock the "
         "baseline to a fixed window (e.g. 2025) before a new monitoring year.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done without processing.")
def main(
    input_dir: Path,
    output_dir: Path,
    aoi_dir: Path,
    months: str,
    min_year: int | None,
    max_year: int | None,
    dry_run: bool,
):
    """Build monthly baseline COGs from downloaded per-scene data."""

    # Discover available month directories
    month_dirs = sorted(input_dir.glob("temp_month_*"))
    if not month_dirs:
        print(f"No temp_month_* directories found in {input_dir}")
        sys.exit(1)

    # Filter to requested months
    if months:
        requested = {int(m) for m in months.split(",")}
        month_dirs = [d for d in month_dirs if int(d.name.split("_")[-1]) in requested]

    print(f"Found {len(month_dirs)} month(s) to process: {[d.name for d in month_dirs]}\n")

    # Load AOI
    print("Loading AOI...")
    aoi_gdf = load_aoi(aoi_dir)
    transform, width, height, target_bounds = compute_target_grid(aoi_gdf)

    if min_year is not None or max_year is not None:
        print(f"Year filter: min={min_year}, max={max_year}")

    if dry_run:
        for md in month_dirs:
            groups = group_files_by_date(md, min_year=min_year, max_year=max_year)
            print(f"\n{md.name}: {len(groups)} dates, {sum(len(v) for v in groups.values())} files")
            for date, files in sorted(groups.items()):
                print(f"  {date}: {len(files)} tiles")
        print("\n[dry-run] No processing performed.")
        return

    # Process each month
    for md in month_dirs:
        month_num = int(md.name.split("_")[-1])
        print(f"\n{'='*60}")
        print(f"Processing month {month_num:02d} ({md.name})")
        print(f"{'='*60}")

        date_groups = group_files_by_date(md, min_year=min_year, max_year=max_year)
        n_dates = len(date_groups)
        print(f"  {n_dates} acquisition dates, {sum(len(v) for v in date_groups.values())} total files")

        # Process one band at a time to manage memory
        for band_name in BAND_NAMES:
            band_idx = BAND_INDEX[band_name]
            print(f"\n  --- {band_name.upper()} (band {band_idx}) ---")

            # Check if output already exists
            mean_path = output_dir / f"{band_name}_month{month_num:02d}_mean.tif"
            std_path = output_dir / f"{band_name}_month{month_num:02d}_std.tif"
            if mean_path.exists() and std_path.exists():
                print(f"  Skipping — {mean_path.name} and {std_path.name} already exist")
                continue

            # Collect all dates into a stack
            stack = []
            for i, (date_str, tile_paths) in enumerate(sorted(date_groups.items()), 1):
                print(f"    [{i}/{n_dates}] {date_str} ({len(tile_paths)} tiles)", end="", flush=True)

                try:
                    merged = merge_tiles_to_grid(
                        tile_paths, target_bounds, transform, width, height, band_idx
                    )

                    # Apply AOI mask
                    merged = apply_aoi_mask(merged, aoi_gdf, transform, (height, width))

                    # Cap EVI2 values
                    if band_name == "evi2":
                        over_cap = np.nansum(merged > EVI2_CAP)
                        if over_cap > 0:
                            merged = np.where(
                                np.isnan(merged), np.nan,
                                np.clip(merged, -EVI2_CAP, EVI2_CAP)
                            )
                            total_valid = np.nansum(~np.isnan(merged))
                            pct = over_cap / total_valid * 100 if total_valid > 0 else 0
                            print(f" — capped {over_cap} EVI2 pixels ({pct:.1f}%)", end="")

                    valid_pct = np.sum(~np.isnan(merged)) / merged.size * 100
                    print(f" — {valid_pct:.1f}% valid")

                    stack.append(merged)

                except Exception as e:
                    print(f" — ERROR: {e}")
                    continue

            if len(stack) < 2:
                print(f"  WARNING: Only {len(stack)} valid date(s) for {band_name} — "
                      f"need at least 2 for meaningful std. Skipping.")
                continue

            # Stack and compute statistics
            print(f"  Computing median and std from {len(stack)} dates...")
            cube = np.stack(stack, axis=0)  # shape: (n_dates, height, width)
            del stack
            gc.collect()

            with np.errstate(all="ignore"):
                median_arr = np.nanmedian(cube, axis=0)
                std_arr = np.nanstd(cube, axis=0)

            # Where we have fewer than 2 valid observations, set std to NaN
            valid_count = np.sum(~np.isnan(cube), axis=0)
            std_arr[valid_count < 2] = np.nan

            del cube
            gc.collect()

            # Save COGs
            print(f"  Saving {mean_path.name}...")
            save_cog(median_arr, mean_path, transform, TARGET_CRS)

            print(f"  Saving {std_path.name}...")
            save_cog(std_arr, std_path, transform, TARGET_CRS)

            # Summary stats
            print(f"  {band_name.upper()} baseline summary:")
            print(f"    Median — min={np.nanmin(median_arr):.4f}, "
                  f"max={np.nanmax(median_arr):.4f}, "
                  f"mean={np.nanmean(median_arr):.4f}")
            print(f"    Std    — min={np.nanmin(std_arr):.4f}, "
                  f"max={np.nanmax(std_arr):.4f}, "
                  f"mean={np.nanmean(std_arr):.4f}")
            print(f"    Valid pixel coverage: {np.sum(~np.isnan(median_arr)) / median_arr.size:.1%}")

            del median_arr, std_arr
            gc.collect()

        print(f"\n  Month {month_num:02d} complete.")

    # Final summary
    print(f"\n{'='*60}")
    print("All months processed. Baseline COGs saved to:")
    print(f"  {output_dir}/")
    cogs = sorted(output_dir.glob("*_month*_*.tif"))
    for c in cogs:
        size_mb = c.stat().st_size / (1024 * 1024)
        print(f"    {c.name} ({size_mb:.1f} MB)")
    print(f"\nTotal: {len(cogs)} baseline COGs")


if __name__ == "__main__":
    main()
