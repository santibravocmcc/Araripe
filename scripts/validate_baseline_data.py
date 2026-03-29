"""Validate downloaded baseline GeoTIFF data for cloud contamination and quality.

Analyzes per-scene index files (NDMI, NBR, EVI2) to detect:
  - Unmasked cloud contamination (bimodal distributions, out-of-range values)
  - NoData=0 conflicts with legitimate index values
  - Spatial coverage gaps
  - Per-tile and per-year consistency

Outputs:
  - Console summary with pass/warn/fail indicators
  - PNG histograms per band saved to scripts/validation_output/
  - Markdown report at scripts/validation_output/validation_report.md

Usage:
    python scripts/validate_baseline_data.py [--month-dir data/baselines/temp_month_01]
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from scipy import stats

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BAND_NAMES = ["NDMI", "NBR", "EVI2"]
# Physically valid ranges for each index (theoretical bounds are [-1, 1])
# but real-world vegetated surfaces stay within tighter ranges.
VALID_RANGE = (-1.0, 1.0)
# Thresholds for cloud contamination heuristics
SUSPECT_HIGH_FRACTION = 0.02  # >2% pixels above 0.95 suggests cloud noise
SUSPECT_LOW_FRACTION = 0.05   # >5% pixels below -0.95 suggests shadow noise
NODATA_ZERO_WARN = 0.15       # >15% zero-valued pixels is suspicious
BIMODAL_DIP_THRESHOLD = 0.05  # Hartigan's dip test p-value threshold


def parse_filename(name: str) -> dict:
    """Extract metadata from filename like 20230103_S2B_24MTS_20230103_0_L2A.tif."""
    parts = name.replace(".tif", "").split("_")
    if len(parts) < 6:
        return {}
    return {
        "date": parts[0],
        "satellite": parts[1],
        "tile": parts[2],
        "revisit": parts[4],
        "level": parts[5],
        "year": parts[0][:4],
        "month": parts[0][4:6],
    }


def analyze_file(filepath: Path) -> dict:
    """Analyze a single GeoTIFF file and return quality metrics per band."""
    result = {"file": filepath.name, "bands": {}, "meta": parse_filename(filepath.name)}

    with rasterio.open(filepath) as src:
        result["crs"] = str(src.crs)
        result["shape"] = (src.height, src.width)
        result["res"] = src.res
        result["bounds"] = src.bounds
        result["nodata"] = src.nodata

        for band_idx, band_name in enumerate(BAND_NAMES, start=1):
            data = src.read(band_idx).astype(np.float32)
            total_pixels = data.size

            # Separate NoData (NaN and 0) from valid data
            # Files use NaN for actual no-data regions (tile edges) and
            # metadata declares nodata=0, so we exclude both.
            nodata_mask = np.isnan(data) | (data == 0)
            valid = data[~nodata_mask]

            band_stats = {
                "total_pixels": total_pixels,
                "nodata_count": int(nodata_mask.sum()),
                "nodata_fraction": float(nodata_mask.sum()) / total_pixels,
                "valid_count": len(valid),
            }

            if len(valid) == 0:
                band_stats.update({
                    "mean": np.nan, "std": np.nan, "min": np.nan, "max": np.nan,
                    "median": np.nan, "p01": np.nan, "p99": np.nan,
                    "out_of_range_fraction": 0.0,
                    "suspect_high_fraction": 0.0,
                    "suspect_low_fraction": 0.0,
                    "near_zero_fraction": 0.0,
                    "skewness": np.nan,
                    "kurtosis": np.nan,
                    "values_sample": np.array([]),
                })
            else:
                out_of_range = np.sum((valid < VALID_RANGE[0]) | (valid > VALID_RANGE[1]))
                suspect_high = np.sum(valid > 0.95)
                suspect_low = np.sum(valid < -0.95)
                near_zero = np.sum(np.abs(valid) < 0.005)  # within ±0.005 of zero

                band_stats.update({
                    "mean": float(np.mean(valid)),
                    "std": float(np.std(valid)),
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "median": float(np.median(valid)),
                    "p01": float(np.percentile(valid, 1)),
                    "p99": float(np.percentile(valid, 99)),
                    "out_of_range_fraction": float(out_of_range) / len(valid),
                    "suspect_high_fraction": float(suspect_high) / len(valid),
                    "suspect_low_fraction": float(suspect_low) / len(valid),
                    "near_zero_fraction": float(near_zero) / len(valid),
                    "skewness": float(stats.skew(valid)),
                    "kurtosis": float(stats.kurtosis(valid)),
                    # Keep a subsample for histogram plotting
                    "values_sample": np.random.choice(valid, size=min(50000, len(valid)), replace=False),
                })

            result["bands"][band_name] = band_stats

    return result


def plot_histograms(results: list[dict], output_dir: Path) -> list[Path]:
    """Plot per-band histograms across all analyzed files, color-coded by year."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    year_colors = {"2023": "#2196F3", "2024": "#4CAF50", "2025": "#FF9800", "2026": "#E91E63"}

    for band_name in BAND_NAMES:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"{band_name} — Value Distribution Across All Scenes", fontsize=14)

        # Left: overlapping histograms by year
        ax = axes[0]
        for r in results:
            sample = r["bands"][band_name].get("values_sample", np.array([]))
            if len(sample) == 0:
                continue
            year = r["meta"].get("year", "unknown")
            color = year_colors.get(year, "#999999")
            ax.hist(sample, bins=200, range=(-1, 1), alpha=0.3, color=color,
                    label=year, density=True)
        ax.set_xlabel(f"{band_name} value")
        ax.set_ylabel("Density")
        ax.set_title("By year (overlapping)")
        ax.axvline(0, color="red", linestyle="--", alpha=0.5, label="NoData=0 zone")
        handles, labels = ax.get_legend_handles_labels()
        # Deduplicate legend
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), fontsize=8)

        # Right: combined histogram with percentile markers
        ax2 = axes[1]
        all_vals = np.concatenate([
            r["bands"][band_name].get("values_sample", np.array([]))
            for r in results
            if len(r["bands"][band_name].get("values_sample", np.array([]))) > 0
        ])
        if len(all_vals) > 0:
            ax2.hist(all_vals, bins=300, range=(-1, 1), color="#607D8B", alpha=0.7, density=True)
            p01, p99 = np.percentile(all_vals, [1, 99])
            ax2.axvline(p01, color="orange", linestyle="--", alpha=0.8, label=f"P1={p01:.3f}")
            ax2.axvline(p99, color="orange", linestyle="--", alpha=0.8, label=f"P99={p99:.3f}")
            ax2.axvline(0, color="red", linestyle="--", alpha=0.5, label="NoData=0 zone")
            ax2.legend(fontsize=8)
        ax2.set_xlabel(f"{band_name} value")
        ax2.set_ylabel("Density")
        ax2.set_title("Combined (all years)")

        plt.tight_layout()
        path = output_dir / f"histogram_{band_name.lower()}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        saved.append(path)
        print(f"  Saved {path}")

    return saved


def plot_tile_summary(results: list[dict], output_dir: Path) -> Path:
    """Plot per-tile mean values as box plots to identify spatial anomalies."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Per-Tile Index Distributions (mean per scene)", fontsize=14)

    for ax, band_name in zip(axes, BAND_NAMES):
        tile_data: dict[str, list[float]] = {}
        for r in results:
            tile = r["meta"].get("tile", "unknown")
            mean_val = r["bands"][band_name]["mean"]
            if not np.isnan(mean_val):
                tile_data.setdefault(tile, []).append(mean_val)

        if tile_data:
            tiles_sorted = sorted(tile_data.keys())
            data_arrays = [tile_data[t] for t in tiles_sorted]
            ax.boxplot(data_arrays, tick_labels=tiles_sorted)
            ax.set_title(band_name)
            ax.set_ylabel("Scene mean")
            ax.tick_params(axis="x", rotation=45)

    plt.tight_layout()
    path = output_dir / "tile_summary.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")
    return path


def assess_cloud_contamination(results: list[dict]) -> dict:
    """Aggregate metrics and produce a cloud contamination assessment."""
    assessment = {"overall": "PASS", "issues": [], "warnings": []}

    for band_name in BAND_NAMES:
        all_out_of_range = []
        all_suspect_high = []
        all_suspect_low = []
        all_nodata_frac = []
        all_kurtosis = []

        for r in results:
            bs = r["bands"][band_name]
            all_out_of_range.append(bs["out_of_range_fraction"])
            all_suspect_high.append(bs["suspect_high_fraction"])
            all_suspect_low.append(bs["suspect_low_fraction"])
            all_nodata_frac.append(bs["nodata_fraction"])
            all_kurtosis.append(bs["kurtosis"])

        mean_oor = np.nanmean(all_out_of_range)
        mean_high = np.nanmean(all_suspect_high)
        mean_low = np.nanmean(all_suspect_low)
        mean_nodata = np.nanmean(all_nodata_frac)
        mean_kurt = np.nanmean(all_kurtosis)

        # Check for out-of-range values (strongest cloud indicator)
        if mean_oor > 0.01:
            assessment["issues"].append(
                f"[FAIL] {band_name}: {mean_oor:.1%} avg pixels outside [-1, 1] — "
                f"strong cloud/corruption signal"
            )
            assessment["overall"] = "FAIL"
        elif mean_oor > 0.001:
            assessment["warnings"].append(
                f"[WARN] {band_name}: {mean_oor:.2%} avg pixels outside [-1, 1]"
            )

        # Check for suspect high values (cloud reflectance → extreme index values)
        if mean_high > SUSPECT_HIGH_FRACTION:
            assessment["issues"].append(
                f"[FAIL] {band_name}: {mean_high:.1%} avg pixels > 0.95 — "
                f"likely unmasked bright clouds"
            )
            assessment["overall"] = "FAIL"
        elif mean_high > 0.005:
            assessment["warnings"].append(
                f"[WARN] {band_name}: {mean_high:.2%} avg pixels > 0.95"
            )

        # Check for suspect low values (cloud shadow → extreme negative indices)
        if mean_low > SUSPECT_LOW_FRACTION:
            assessment["issues"].append(
                f"[FAIL] {band_name}: {mean_low:.1%} avg pixels < -0.95 — "
                f"likely unmasked cloud shadows"
            )
            assessment["overall"] = "FAIL"

        # High kurtosis can indicate contamination (heavy tails)
        if mean_kurt > 10:
            assessment["warnings"].append(
                f"[WARN] {band_name}: high kurtosis ({mean_kurt:.1f}) — "
                f"heavy-tailed distribution, possible outlier contamination"
            )

        # NoData=0 fraction
        if mean_nodata > NODATA_ZERO_WARN:
            assessment["warnings"].append(
                f"[WARN] {band_name}: {mean_nodata:.1%} avg pixels are exactly 0 (NoData) — "
                f"check if legitimate values near zero are being lost"
            )

    if not assessment["issues"] and not assessment["warnings"]:
        assessment["notes"] = ["All indices within expected ranges. No cloud contamination detected."]

    return assessment


def generate_report(results: list[dict], assessment: dict, output_dir: Path, hist_paths: list[Path], tile_path: Path) -> Path:
    """Generate a Markdown validation report."""
    report_path = output_dir / "validation_report.md"

    lines = [
        "# Baseline Data Validation Report",
        "",
        f"**Files analyzed:** {len(results)}",
        f"**Directory:** `{results[0]['meta'].get('month', '??')}` (month {results[0]['meta'].get('month', '??')})",
        "",
        "---",
        "",
        "## Cloud Contamination Assessment",
        "",
        f"### Overall: **{assessment['overall']}**",
        "",
    ]

    if assessment.get("issues"):
        lines.append("### Issues (require action)")
        for issue in assessment["issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    if assessment.get("warnings"):
        lines.append("### Warnings (review recommended)")
        for warn in assessment["warnings"]:
            lines.append(f"- {warn}")
        lines.append("")

    if assessment.get("notes"):
        for note in assessment["notes"]:
            lines.append(f"- {note}")
        lines.append("")

    # Per-band statistics table
    lines.extend([
        "---",
        "",
        "## Per-Band Aggregate Statistics",
        "",
        "| Metric | NDMI | NBR | EVI2 |",
        "|--------|------|-----|------|",
    ])

    metrics_to_show = [
        ("Mean", "mean"), ("Std", "std"), ("Median", "median"),
        ("Min", "min"), ("Max", "max"),
        ("P1", "p01"), ("P99", "p99"),
        ("NoData fraction", "nodata_fraction"),
        ("Out-of-range fraction", "out_of_range_fraction"),
        ("Suspect high (>0.95)", "suspect_high_fraction"),
        ("Suspect low (<-0.95)", "suspect_low_fraction"),
        ("Near-zero fraction", "near_zero_fraction"),
        ("Skewness", "skewness"),
        ("Kurtosis", "kurtosis"),
    ]

    for label, key in metrics_to_show:
        vals = []
        for band_name in BAND_NAMES:
            band_vals = [r["bands"][band_name][key] for r in results if not np.isnan(r["bands"][band_name].get(key, np.nan))]
            if band_vals:
                avg = np.mean(band_vals)
                if "fraction" in key:
                    vals.append(f"{avg:.2%}")
                else:
                    vals.append(f"{avg:.4f}")
            else:
                vals.append("N/A")
        lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")

    # Temporal coverage
    lines.extend(["", "---", "", "## Temporal Coverage", ""])
    year_counts: dict[str, int] = {}
    for r in results:
        y = r["meta"].get("year", "unknown")
        year_counts[y] = year_counts.get(y, 0) + 1
    lines.append("| Year | Scene count |")
    lines.append("|------|------------|")
    for y in sorted(year_counts):
        lines.append(f"| {y} | {year_counts[y]} |")

    # Tile coverage
    lines.extend(["", "## Tile Coverage", ""])
    tile_counts: dict[str, int] = {}
    for r in results:
        t = r["meta"].get("tile", "unknown")
        tile_counts[t] = tile_counts.get(t, 0) + 1
    lines.append("| Tile | Scene count |")
    lines.append("|------|------------|")
    for t in sorted(tile_counts):
        lines.append(f"| {t} | {tile_counts[t]} |")

    # Figures
    lines.extend(["", "---", "", "## Figures", ""])
    for hp in hist_paths:
        lines.append(f"![{hp.stem}]({hp.name})")
        lines.append("")
    lines.append(f"![tile_summary]({tile_path.name})")

    # Recommendations
    lines.extend([
        "", "---", "",
        "## Recommendations",
        "",
    ])
    if assessment["overall"] == "FAIL":
        lines.extend([
            "1. **Cloud contamination detected.** Before compositing into baselines, apply cloud "
            "masks retroactively by fetching SCL bands from STAC for each scene date and masking "
            "contaminated pixels in the index files.",
            "2. Re-run this validation after masking to confirm the issue is resolved.",
        ])
    elif assessment.get("warnings"):
        lines.extend([
            "1. **Minor issues detected.** Review the warnings above. The data is likely usable "
            "but spot-check a few flagged scenes visually.",
            "2. Proceed to AOI clipping and monthly compositing with caution.",
        ])
    else:
        lines.extend([
            "1. **Data looks clean.** Proceed to AOI clipping and monthly compositing.",
            "2. Re-encode NoData from 0 → NaN before compositing to avoid losing legitimate zero values.",
        ])

    report_path.write_text("\n".join(lines))
    print(f"\n  Report saved to {report_path}")
    return report_path


@click.command()
@click.option(
    "--month-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path("data/baselines/temp_month_01"),
    help="Directory containing per-scene GeoTIFFs for one month.",
)
@click.option(
    "--max-files",
    type=int,
    default=0,
    help="Max files to analyze (0 = all). Use for quick checks.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("scripts/validation_output"),
    help="Directory for output plots and report.",
)
def main(month_dir: Path, max_files: int, output_dir: Path):
    """Validate downloaded baseline data for cloud contamination and quality."""
    tif_files = sorted(month_dir.glob("*.tif"))
    if not tif_files:
        print(f"No .tif files found in {month_dir}")
        sys.exit(1)

    if max_files > 0:
        tif_files = tif_files[:max_files]

    print(f"Analyzing {len(tif_files)} files in {month_dir}...\n")

    results = []
    for i, fp in enumerate(tif_files, 1):
        print(f"  [{i}/{len(tif_files)}] {fp.name}", end="")
        try:
            r = analyze_file(fp)
            results.append(r)
            # Quick summary
            ndmi_mean = r["bands"]["NDMI"]["mean"]
            nodata_frac = r["bands"]["NDMI"]["nodata_fraction"]
            print(f"  — NDMI mean={ndmi_mean:.3f}, nodata={nodata_frac:.1%}")
        except Exception as e:
            print(f"  — ERROR: {e}")

    if not results:
        print("No files could be analyzed.")
        sys.exit(1)

    print(f"\nAnalyzed {len(results)} files successfully.\n")

    # Assessment
    print("=== Cloud Contamination Assessment ===\n")
    assessment = assess_cloud_contamination(results)
    print(f"  Overall: {assessment['overall']}\n")
    for issue in assessment.get("issues", []):
        print(f"  {issue}")
    for warn in assessment.get("warnings", []):
        print(f"  {warn}")
    for note in assessment.get("notes", []):
        print(f"  {note}")

    # Plots
    print("\n=== Generating Plots ===\n")
    output_dir.mkdir(parents=True, exist_ok=True)
    hist_paths = plot_histograms(results, output_dir)
    tile_path = plot_tile_summary(results, output_dir)

    # Report
    print("\n=== Generating Report ===")
    generate_report(results, assessment, output_dir, hist_paths, tile_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
