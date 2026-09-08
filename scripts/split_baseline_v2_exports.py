"""Split the baseline 2.0.0 monthly exports into the canonical rebuild rasters.

Package 2A.6C tooling.  Deliberately a separate script from the v1
``scripts/split_gee_baselines.py``, which stays byte-unchanged audit material
for the accepted 1.0.0 generation.  Two v1 behaviours are unsafe for a v2
rebuild and are corrected here:

- the v1 splitter defaults to ``data/baselines`` (the 1.0.0 directory); this
  script refuses to write into the v1 directory at all; and
- the v1 splitter silently masks any ``|value| > 1.5``, which is looser than
  the v2 range contract for NDMI/NBR and would hide a real problem behind a
  manifest that then validates.  This script clamps only within a tiny
  numerical tolerance, counts what it clamped, and fails closed on anything
  beyond it.

Input: the 12 nine-band GeoTIFFs exported by the rebuild executor
(``araripe_baseline_v2_monthNN.tif``), band order
``ndmi_median, nbr_median, evi2_median, ndmi_std, nbr_std, evi2_std,
ndmi_count, nbr_count, evi2_count``.

Output:
  * ``data/baselines_v2/2.0.0/<index>_month<NN>_{mean,std}.tif`` — the 72
    audited single-band COGs (``_mean`` carries the median, exactly as the
    accepted 1.0.0 naming does);
  * ``data/baselines_v2/2.0.0_evidence/counts/<index>_month<NN>_count.tif`` —
    the contribution-depth rasters, outside the audited directory; and
  * ``contribution_counts.json`` in that evidence directory, merged across
    incremental runs, feeding the manifest's contribution-count block.

Usage (month by month, deleting each export after it is split):
    python scripts/split_baseline_v2_exports.py --in-dir data/baselines_v2/exports
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import BASELINES_DIR  # noqa: E402
from src.detection.baseline_manifest import _range_limits  # noqa: E402
from src.detection.baseline_manifest_v2 import (  # noqa: E402
    BASELINE_V2_COUNTS_LOCAL_DIR,
    BASELINE_V2_EXPORTS_LOCAL_DIR,
    BASELINE_V2_LOCAL_DIR,
    BASELINE_V2_SPLIT_EVIDENCE_FILENAME,
    sha256_bytes_of_file,
)
from src.processing.baseline_rebuild_v2 import (  # noqa: E402
    CONTRIBUTION_COUNT_DTYPE,
    REBUILD_EXPORT_BAND_NAMES,
    STATISTIC_EXPORT_SENTINEL,
    contribution_count_filename,
    contribution_count_summary,
    month_export_filename,
)

# Export band name -> (index, canonical filename statistic).  The exported
# band is honestly named ``_median``; the canonical object keeps the accepted
# historical ``_mean`` filename, which the manifest documents as a median.
_BAND_TARGETS = {
    "ndmi_median": ("ndmi", "mean"),
    "nbr_median": ("nbr", "mean"),
    "evi2_median": ("evi2", "mean"),
    "ndmi_std": ("ndmi", "std"),
    "nbr_std": ("nbr", "std"),
    "evi2_std": ("evi2", "std"),
}
_COUNT_BANDS = {
    "ndmi_count": "ndmi",
    "nbr_count": "nbr",
    "evi2_count": "evi2",
}


class SplitError(click.ClickException):
    """A rebuild export violates the baseline 2.0.0 split contract."""


def _write_statistic_cog(array: np.ndarray, src, out_path: Path) -> None:
    profile = src.profile.copy()
    profile.update(
        count=1,
        dtype="float32",
        nodata=float("nan"),
        driver="GTiff",
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(array.astype("float32"), 1)


def _write_count_cog(array: np.ndarray, src, out_path: Path) -> None:
    profile = src.profile.copy()
    # Zero contributions is a real value, not nodata, so the count raster
    # carries no nodata at all.
    profile.update(
        count=1,
        dtype=CONTRIBUTION_COUNT_DTYPE,
        nodata=None,
        driver="GTiff",
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(array.astype(CONTRIBUTION_COUNT_DTYPE), 1)


def _restore_and_guard(
    values: np.ndarray,
    *,
    index: str,
    statistic: str,
    month: int,
    tolerance: float,
) -> tuple[np.ndarray, int]:
    """Restore the export sentinel to NaN and enforce the v2 range contract."""

    array = values.astype("float64", copy=True)
    array[array <= STATISTIC_EXPORT_SENTINEL + 9.0] = np.nan
    array[~np.isfinite(array)] = np.nan
    lower, upper = _range_limits(index, statistic)
    finite = np.isfinite(array)
    below = finite & (array < lower)
    above = finite & (array > upper)
    hard = (finite & (array < lower - tolerance)) | (
        finite & (array > upper + tolerance)
    )
    if hard.any():
        offending = array[hard]
        raise SplitError(
            f"month {month:02d} {index}_{statistic}: {int(hard.sum())} pixel(s) "
            f"fall outside the accepted range [{lower}, {upper}] beyond the "
            f"{tolerance:g} tolerance (min {float(offending.min())!r}, max "
            f"{float(offending.max())!r}). This is a scientific signal, not a "
            "formatting problem: investigate the composite before rebuilding. "
            "Masking it here would produce a manifest that validates while "
            "hiding the cause."
        )
    clamped = int(below.sum() + above.sum())
    array[below] = lower
    array[above] = upper
    return array, clamped


def _load_evidence(path: Path) -> dict:
    if not path.exists():
        return {
            "evidence_version": "phase2a6c-baseline-split-evidence-v1",
            "months": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


@click.command()
@click.option(
    "--in-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=str(BASELINE_V2_EXPORTS_LOCAL_DIR),
    show_default=True,
    help="Directory holding the downloaded araripe_baseline_v2_month*.tif.",
)
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=str(BASELINE_V2_LOCAL_DIR),
    show_default=True,
    help="Directory for the 72 audited baseline 2.0.0 rasters.",
)
@click.option(
    "--counts-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=str(BASELINE_V2_COUNTS_LOCAL_DIR),
    show_default=True,
    help="Directory for the contribution-depth rasters and their evidence.",
)
@click.option(
    "--tolerance",
    type=float,
    default=1e-6,
    show_default=True,
    help="Numerical tolerance clamped at a range bound before failing closed.",
)
def main(in_dir: Path, out_dir: Path, counts_dir: Path, tolerance: float) -> None:
    v1_dir = Path(BASELINES_DIR).resolve()
    for label, target in (("--out-dir", out_dir), ("--counts-dir", counts_dir)):
        resolved = target.resolve()
        if resolved == v1_dir or v1_dir in resolved.parents:
            raise SplitError(
                f"{label} {target} is inside the immutable baseline 1.0.0 "
                f"directory {v1_dir}; the two generations never share storage"
            )
    if tolerance < 0:
        raise SplitError("--tolerance must be non-negative")

    out_dir.mkdir(parents=True, exist_ok=True)
    counts_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = counts_dir / BASELINE_V2_SPLIT_EVIDENCE_FILENAME
    evidence = _load_evidence(evidence_path)

    exports = sorted(Path(in_dir).glob("*.tif"))
    if not exports:
        raise SplitError(f"no *.tif export found in {in_dir}")

    expected_names = {month_export_filename(m): m for m in range(1, 13)}
    written = 0
    for export in exports:
        month = expected_names.get(export.name)
        if month is None:
            raise SplitError(
                f"{export.name} is not a canonical baseline 2.0.0 monthly "
                "export name; a v1 or foreign file must never be split into "
                "the v2 inventory"
            )
        with rasterio.open(export) as src:
            if src.count != len(REBUILD_EXPORT_BAND_NAMES):
                raise SplitError(
                    f"{export.name}: expected "
                    f"{len(REBUILD_EXPORT_BAND_NAMES)} bands, got {src.count}"
                )
            descriptions = [
                (name or "").lower() for name in src.descriptions
            ]
            order = (
                descriptions
                if sorted(descriptions) == sorted(REBUILD_EXPORT_BAND_NAMES)
                else list(REBUILD_EXPORT_BAND_NAMES)
            )
            month_evidence: dict[str, dict] = {}
            for position, band_name in enumerate(order, start=1):
                raw = src.read(position)
                if band_name in _BAND_TARGETS:
                    index, statistic = _BAND_TARGETS[band_name]
                    values, clamped = _restore_and_guard(
                        raw,
                        index=index,
                        statistic=statistic,
                        month=month,
                        tolerance=tolerance,
                    )
                    target = out_dir / f"{index}_month{month:02d}_{statistic}.tif"
                    _write_statistic_cog(values, src, target)
                    written += 1
                    if clamped:
                        click.echo(
                            f"  note: {target.name} clamped {clamped} pixel(s) "
                            f"within {tolerance:g} of a range bound"
                        )
                elif band_name in _COUNT_BANDS:
                    index = _COUNT_BANDS[band_name]
                    counts = np.rint(raw).astype("int64")
                    if counts.min() < 0:
                        raise SplitError(
                            f"month {month:02d} {index}: negative contribution "
                            "count in the export"
                        )
                    target = counts_dir / contribution_count_filename(
                        index, month
                    )
                    _write_count_cog(counts, src, target)
                    month_evidence[index] = {
                        "file": target.name,
                        "bytes": target.stat().st_size,
                        "sha256": sha256_bytes_of_file(target),
                        **contribution_count_summary(counts.astype("int32")),
                    }
                else:
                    raise SplitError(
                        f"{export.name}: unexpected band {band_name!r}"
                    )
        evidence["months"][str(month)] = {
            "export_file": {
                "name": export.name,
                "bytes": export.stat().st_size,
                "sha256": sha256_bytes_of_file(export),
            },
            "contribution_counts": month_evidence,
        }
        shallow = {
            index: block["pixels_below_three_contributions"]
            for index, block in month_evidence.items()
        }
        click.echo(
            f"  {export.name} -> 6 baseline COGs + 3 count rasters "
            f"(month {month:02d}); pixels with <3 contributions: {shallow}"
        )

    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    click.echo(
        f"\nWrote {written} baseline COG(s) to {out_dir} and contribution "
        f"evidence to {evidence_path}."
    )
    click.echo(
        "Baseline 1.0.0 was not read or written. Runtime BASELINE_VERSION "
        "stays 1.0.0 until a later reviewed package activates 2.0.0."
    )


if __name__ == "__main__":
    main()
