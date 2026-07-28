"""Finite-pixel scene QA for the Phase 2A.1 anomaly guard."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import xarray as xr


@dataclass(frozen=True)
class SceneQuality:
    scene_decision: str
    valid_coverage_fraction: float
    minimum_required_fraction: float
    alert_fraction_of_valid: float
    anomaly_reject_fraction: float
    valid_pixel_count: int
    total_pixel_count: int
    alert_pixel_count: int
    qa_flags: tuple[str, ...]
    rejection_reason: str | None

    def to_dict(self) -> dict:
        value = asdict(self)
        value["qa_flags"] = list(self.qa_flags)
        return value


def finite_source_reference_mask(
    current_indices: xr.Dataset,
    baseline_means: dict[str, xr.DataArray],
    baseline_stds: dict[str, xr.DataArray],
) -> xr.DataArray:
    """Pixels eligible for at least one configured index comparison.

    A pixel is valid only when the current value and its matching baseline mean
    and standard deviation are all finite. The union is intentional: low and
    medium detection rules can operate on one available index.
    """
    masks: list[xr.DataArray] = []
    for name in current_indices.data_vars:
        if name not in baseline_means or name not in baseline_stds:
            continue
        masks.append(
            np.isfinite(current_indices[name])
            & np.isfinite(baseline_means[name])
            & np.isfinite(baseline_stds[name])
        )
    if not masks:
        raise ValueError("no current index has matching baseline mean and std")
    valid = masks[0]
    for mask in masks[1:]:
        valid = valid | mask
    valid.name = "valid_pixel_mask"
    return valid.astype(bool)


def assess_scene_quality(
    detection: xr.Dataset,
    *,
    minimum_required_fraction: float,
    anomaly_reject_fraction: float,
) -> SceneQuality:
    """Assess coverage and anomaly fraction using finite eligible pixels only."""
    if "valid_pixel_mask" not in detection:
        raise ValueError("detection output is missing valid_pixel_mask")
    if "confidence" not in detection:
        raise ValueError("detection output is missing confidence")
    if not 0 <= minimum_required_fraction <= 1:
        raise ValueError("minimum_required_fraction must be in [0, 1]")
    if not 0 <= anomaly_reject_fraction <= 1:
        raise ValueError("anomaly_reject_fraction must be in [0, 1]")

    valid = np.asarray(detection["valid_pixel_mask"].values, dtype=bool)
    confidence = np.asarray(detection["confidence"].values)
    total = int(valid.size)
    valid_count = int(valid.sum())
    alert_count = int(((confidence >= 1) & valid).sum())
    coverage = valid_count / total if total else 0.0
    alert_fraction = alert_count / valid_count if valid_count else 0.0

    flags: list[str] = []
    invalid_count = total - valid_count
    if invalid_count:
        flags.append("cloud_nodata_or_invalid_pixels_excluded")

    if valid_count == 0:
        decision = "rejected_low_coverage"
        reason = "no_finite_source_reference_pixels"
    elif coverage < minimum_required_fraction:
        decision = "rejected_low_coverage"
        reason = "valid_coverage_below_threshold"
    elif alert_fraction > anomaly_reject_fraction:
        decision = "rejected_quality"
        reason = "alert_fraction_of_valid_pixels_above_threshold"
    else:
        decision = "accepted"
        reason = None

    return SceneQuality(
        scene_decision=decision,
        valid_coverage_fraction=coverage,
        minimum_required_fraction=minimum_required_fraction,
        alert_fraction_of_valid=alert_fraction,
        anomaly_reject_fraction=anomaly_reject_fraction,
        valid_pixel_count=valid_count,
        total_pixel_count=total,
        alert_pixel_count=alert_count,
        qa_flags=tuple(flags),
        rejection_reason=reason,
    )


def save_scene_quality(
    quality: SceneQuality,
    *,
    output_dir: Path,
    record_id: str,
    acquisition_id: str,
    observed_on: str,
    scene_ids: list[str],
) -> Path:
    """Write a small local QA record for later processing-ledger ingestion."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in record_id
    )
    path = output_dir / f"{safe_id}.json"
    payload = {
        "schema_version": "1.0.0",
        "acquisition_id": acquisition_id,
        "observed_on": observed_on,
        "scene_ids": sorted(set(scene_ids)),
        "quality": quality.to_dict(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
