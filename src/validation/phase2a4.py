"""Pure Phase 2A.4 scientific-candidate algorithms.

This module is deliberately isolated from the operational detector.  It creates
candidate drought, mask, and same-day-composition evidence; it does not select
or activate a method and it does not create canonical acquisition,
observation, or event identities.

Every public result carries stable SHA-256 records for its candidate
configuration, normalized inputs, and output.  Numpy arrays are normalized for
endianness, memory order, NaN representation, and negative zero before hashing.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import ndimage, stats

from src.detection.identity import canonical_json_bytes, canonical_sha256


_CANDIDATE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*-v[1-9][0-9]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

MASK_REASON_CODES = {
    "valid": 0,
    "source_invalid": 1,
    "scl_rejected": 2,
    "cloud_rejected": 3,
    "dark_shadow_rejected": 4,
}
MASK_OUTSIDE_COMPARISON_CODE = 255


def _candidate_id(value: str) -> str:
    if not isinstance(value, str) or not _CANDIDATE_ID.fullmatch(value):
        raise ValueError(
            "candidate_id must be a lowercase versioned identifier ending in -vN"
        )
    return value


def _output_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy ``record`` and bind every field with ``output_sha256``."""
    output = copy.deepcopy(dict(record))
    if "output_sha256" in output:
        raise ValueError("output record already contains output_sha256")
    output["output_sha256"] = canonical_sha256(output)
    return output


def canonical_array_record(array: np.ndarray) -> dict[str, Any]:
    """Return a stable, content-addressed record for a numeric/bool array.

    The digest is independent of input byte order, C/F memory layout, NaN
    payload, and the sign bit on zero.  Floats are represented as little-endian
    float64, integers as little-endian int64, and booleans as uint8.
    """
    value = np.asarray(array)
    if value.dtype.kind == "b":
        normalized = np.ascontiguousarray(value.astype(np.uint8, copy=False))
        encoding = "uint8_boolean"
    elif value.dtype.kind in "iu":
        normalized = np.ascontiguousarray(value.astype("<i8", copy=False))
        encoding = "little_endian_int64"
    elif value.dtype.kind == "f":
        normalized = np.array(value, dtype="<f8", order="C", copy=True)
        normalized[normalized == 0.0] = 0.0
        normalized[np.isnan(normalized)] = np.nan
        encoding = "little_endian_float64_canonical_nan_and_zero"
    else:
        raise TypeError("array must have a boolean, integer, or floating dtype")

    header = {
        "schema": "phase2a4-canonical-array-v1",
        "shape": list(normalized.shape),
        "encoding": encoding,
    }
    digest = hashlib.sha256(
        canonical_json_bytes(header) + b"\x00" + normalized.tobytes(order="C")
    ).hexdigest()
    return {**header, "sha256": digest}


def _parse_observed_on(value: dt.date | str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise TypeError("observed_on must be a date, not a datetime")
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        raise TypeError("observed_on must be an ISO date string or date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("observed_on must be a valid ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError("observed_on must use canonical YYYY-MM-DD form")
    return parsed


def _month_shift(year: int, month: int, offset: int) -> tuple[int, int]:
    ordinal = year * 12 + (month - 1) + offset
    shifted_year, shifted_zero_month = divmod(ordinal, 12)
    return shifted_year, shifted_zero_month + 1


def _window_months(
    ending_year: int, ending_month: int, accumulation_months: int
) -> tuple[tuple[int, int], ...]:
    return tuple(
        _month_shift(ending_year, ending_month, offset)
        for offset in range(-(accumulation_months - 1), 1)
    )


def _month_key(value: object) -> tuple[int, int]:
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            raise ValueError(f"invalid monthly precipitation key: {value!r}")
        year, month = (int(part) for part in value.split("-"))
    elif (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(part, int) and not isinstance(part, bool) for part in value)
    ):
        year, month = value
    elif isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        year, month = value.year, value.month
    else:
        raise TypeError(
            "monthly precipitation keys must be YYYY-MM strings, "
            "(year, month) tuples, or dates"
        )
    if year < 1 or not 1 <= month <= 12:
        raise ValueError(f"invalid monthly precipitation key: {value!r}")
    return year, month


def _monthly_values(
    values: Mapping[object, float | int | None],
) -> tuple[dict[tuple[int, int], float | None], list[dict[str, Any]]]:
    if not isinstance(values, Mapping):
        raise TypeError("monthly_precipitation must be a mapping")
    normalized: dict[tuple[int, int], float | None] = {}
    for raw_key, raw_value in values.items():
        key = _month_key(raw_key)
        if key in normalized:
            raise ValueError(f"duplicate normalized month {key[0]:04d}-{key[1]:02d}")
        if raw_value is None:
            value = None
        elif isinstance(raw_value, bool) or not isinstance(
            raw_value, (int, float, np.integer, np.floating)
        ):
            raise TypeError(
                f"precipitation for {key[0]:04d}-{key[1]:02d} must be numeric or null"
            )
        else:
            converted = float(raw_value)
            value = converted if math.isfinite(converted) else None
        normalized[key] = value
    record = [
        {
            "month": f"{year:04d}-{month:02d}",
            "precipitation_mm": normalized[(year, month)],
        }
        for year, month in sorted(normalized)
    ]
    return normalized, record


@dataclass(frozen=True)
class DroughtCandidateConfig:
    """Fixed inputs for one season-matched SPI-3 candidate."""

    candidate_id: str
    reference_start_year: int
    reference_end_year: int
    accumulation_months: int = 3
    minimum_complete_reference_windows: int = 40
    minimum_positive_reference_windows: int = 2
    normal_probability_clip: tuple[float, float] = (0.001, 0.999)
    drought_threshold: float = -1.0
    z_threshold_adjustment: float = 0.5

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        if isinstance(self.reference_start_year, bool) or not isinstance(
            self.reference_start_year, int
        ):
            raise TypeError("reference_start_year must be an integer")
        if isinstance(self.reference_end_year, bool) or not isinstance(
            self.reference_end_year, int
        ):
            raise TypeError("reference_end_year must be an integer")
        if (
            self.reference_start_year < 1
            or self.reference_end_year < self.reference_start_year
        ):
            raise ValueError("reference year bounds are invalid")
        if self.accumulation_months != 3:
            raise ValueError("Phase 2A.4 drought candidates require SPI-3")
        if isinstance(self.minimum_complete_reference_windows, bool) or not isinstance(
            self.minimum_complete_reference_windows, int
        ):
            raise TypeError("minimum_complete_reference_windows must be an integer")
        if self.minimum_complete_reference_windows < 1:
            raise ValueError("minimum_complete_reference_windows must be positive")
        if isinstance(self.minimum_positive_reference_windows, bool) or not isinstance(
            self.minimum_positive_reference_windows, int
        ):
            raise TypeError("minimum_positive_reference_windows must be an integer")
        if self.minimum_positive_reference_windows < 2:
            raise ValueError("minimum_positive_reference_windows must be at least 2")
        clip = tuple(self.normal_probability_clip)
        if (
            len(clip) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in clip
            )
            or not 0 < float(clip[0]) < float(clip[1]) < 1
        ):
            raise ValueError(
                "normal_probability_clip must contain increasing bounds in (0, 1)"
            )
        object.__setattr__(
            self, "normal_probability_clip", (float(clip[0]), float(clip[1]))
        )
        if not math.isfinite(self.drought_threshold):
            raise ValueError("drought_threshold must be finite")
        if (
            not math.isfinite(self.z_threshold_adjustment)
            or self.z_threshold_adjustment < 0
        ):
            raise ValueError("z_threshold_adjustment must be finite and non-negative")

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "candidate_id": self.candidate_id,
            "status": "candidate_only_not_selected_or_activated",
            "dataset": "CHIRPS 2.0 monthly precipitation",
            "reference_ending_years": [
                self.reference_start_year,
                self.reference_end_year,
            ],
            "accumulation_months": self.accumulation_months,
            "target_month_rule": "calendar_month_immediately_before_acquisition",
            "season_matching_rule": (
                "same_accumulation_ending_month_across_reference_years"
            ),
            "target_window_excluded_from_reference": True,
            "minimum_complete_reference_windows": (
                self.minimum_complete_reference_windows
            ),
            "minimum_positive_reference_windows": (
                self.minimum_positive_reference_windows
            ),
            "distribution": "mixed_zero_probability_plus_gamma_mle_floc_0",
            "normal_probability_clip": list(self.normal_probability_clip),
            "drought_threshold": self.drought_threshold,
            "z_threshold_adjustment": self.z_threshold_adjustment,
            "adjustment_applied": False,
            "missing_evidence_policy": (
                "target_unavailable_reference_incomplete_excluded_"
                "without_substitution"
            ),
        }

    @property
    def config_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def compute_season_matched_spi3(
    observed_on: dt.date | str,
    monthly_precipitation: Mapping[object, float | int | None],
    *,
    config: DroughtCandidateConfig,
) -> dict[str, Any]:
    """Compute candidate SPI-3 for one acquisition date.

    The target ends in the immediately preceding calendar month.  Reference
    windows end in that same calendar month for every fixed reference year.  A
    missing target window, inadequate reference completeness, or unusable gamma
    fit returns an explicit ``unavailable`` record; it never returns a neutral
    numeric surrogate or a z-score fallback.
    """
    if not isinstance(config, DroughtCandidateConfig):
        raise TypeError("config must be DroughtCandidateConfig")
    acquisition_date = _parse_observed_on(observed_on)
    values, monthly_record = _monthly_values(monthly_precipitation)
    target_end_year, target_end_month = _month_shift(
        acquisition_date.year, acquisition_date.month, -1
    )
    target_months = _window_months(
        target_end_year, target_end_month, config.accumulation_months
    )
    reference_years = list(
        range(config.reference_start_year, config.reference_end_year + 1)
    )
    considered_years = [year for year in reference_years if year != target_end_year]
    input_record = {
        "schema": "phase2a4-drought-input-v1",
        "observed_on": acquisition_date.isoformat(),
        "config_sha256": config.config_sha256,
        "monthly_precipitation": monthly_record,
    }
    input_sha256 = canonical_sha256(input_record)

    target_missing = [
        f"{year:04d}-{month:02d}"
        for year, month in target_months
        if values.get((year, month)) is None
    ]
    target_invalid = [
        f"{year:04d}-{month:02d}"
        for year, month in target_months
        if values.get((year, month)) is not None
        and values[(year, month)] < 0
    ]

    complete_reference: list[dict[str, Any]] = []
    incomplete_reference: list[dict[str, Any]] = []
    for ending_year in considered_years:
        months = _window_months(
            ending_year, target_end_month, config.accumulation_months
        )
        missing = [
            f"{year:04d}-{month:02d}"
            for year, month in months
            if (year, month) < (config.reference_start_year, 1)
            or (year, month) > (config.reference_end_year, 12)
            or values.get((year, month)) is None
        ]
        invalid = [
            f"{year:04d}-{month:02d}"
            for year, month in months
            if (config.reference_start_year, 1)
            <= (year, month)
            <= (config.reference_end_year, 12)
            and values.get((year, month)) is not None
            and values[(year, month)] < 0
        ]
        if missing or invalid:
            incomplete_reference.append(
                {
                    "ending_year": ending_year,
                    "missing_months": missing,
                    "invalid_months": invalid,
                }
            )
            continue
        total = float(sum(values[month] for month in months))  # type: ignore[arg-type]
        complete_reference.append(
            {"ending_year": ending_year, "precipitation_3month_mm": total}
        )

    possible_count = len(considered_years)
    complete_count = len(complete_reference)
    completeness = complete_count / possible_count if possible_count else 0.0
    required_count = config.minimum_complete_reference_windows
    common = {
        "schema_version": "1.0.0",
        "candidate_id": config.candidate_id,
        "candidate_only": True,
        "selected_or_activated": False,
        "observed_on": acquisition_date.isoformat(),
        "target_ending_month": f"{target_end_year:04d}-{target_end_month:02d}",
        "target_window_months": [
            f"{year:04d}-{month:02d}" for year, month in target_months
        ],
        "reference_ending_month": target_end_month,
        "reference_years_considered": considered_years,
        "reference_years_complete": [
            item["ending_year"] for item in complete_reference
        ],
        "reference_years_incomplete": incomplete_reference,
        "reference_complete_count": complete_count,
        "reference_possible_count": possible_count,
        "reference_completeness_fraction": completeness,
        "required_complete_reference_count": required_count,
        "config_sha256": config.config_sha256,
        "input_sha256": input_sha256,
    }

    def unavailable(reason: str, **details: Any) -> dict[str, Any]:
        return _output_record(
            {
                **common,
                "status": "unavailable",
                "unavailable_reason": reason,
                "spi_3month": None,
                "drought_status": "unavailable",
                "is_drought": None,
                **details,
            }
        )

    if target_invalid:
        return unavailable(
            "invalid_target_precipitation",
            target_missing_months=target_missing,
            target_invalid_months=target_invalid,
        )
    if target_missing:
        return unavailable(
            "missing_target_precipitation",
            target_missing_months=target_missing,
            target_invalid_months=[],
        )
    if possible_count == 0 or complete_count < required_count:
        return unavailable("insufficient_complete_reference_windows")

    target_total = float(
        sum(values[month] for month in target_months)  # type: ignore[arg-type]
    )
    reference = np.asarray(
        [item["precipitation_3month_mm"] for item in complete_reference],
        dtype=np.float64,
    )
    positive = reference[reference > 0]
    if positive.size < config.minimum_positive_reference_windows:
        return unavailable(
            "insufficient_positive_reference_windows",
            target_precipitation_3month_mm=target_total,
            positive_reference_count=int(positive.size),
        )
    if float(np.std(positive)) <= 1e-12:
        return unavailable(
            "degenerate_positive_reference_distribution",
            target_precipitation_3month_mm=target_total,
            positive_reference_count=int(positive.size),
        )

    try:
        shape, location, scale = stats.gamma.fit(positive, floc=0)
    except Exception as exc:
        return unavailable(
            "gamma_fit_failed",
            target_precipitation_3month_mm=target_total,
            fit_error_type=type(exc).__name__,
        )
    if not all(math.isfinite(float(item)) for item in (shape, location, scale)) or (
        shape <= 0 or scale <= 0 or location != 0
    ):
        return unavailable(
            "gamma_fit_invalid",
            target_precipitation_3month_mm=target_total,
        )

    zero_probability = float(np.count_nonzero(reference == 0) / reference.size)
    if target_total == 0:
        mixed_cdf = zero_probability
    else:
        gamma_cdf = float(stats.gamma.cdf(target_total, shape, loc=0, scale=scale))
        mixed_cdf = zero_probability + (1.0 - zero_probability) * gamma_cdf
    if not math.isfinite(mixed_cdf):
        return unavailable(
            "gamma_cdf_invalid",
            target_precipitation_3month_mm=target_total,
        )
    clipped_cdf = float(
        np.clip(
            mixed_cdf,
            config.normal_probability_clip[0],
            config.normal_probability_clip[1],
        )
    )
    spi = float(stats.norm.ppf(clipped_cdf))
    if not math.isfinite(spi):
        return unavailable(
            "spi_transform_invalid",
            target_precipitation_3month_mm=target_total,
        )

    return _output_record(
        {
            **common,
            "status": "available",
            "unavailable_reason": None,
            "target_precipitation_3month_mm": target_total,
            "reference_3month_totals": complete_reference,
            "positive_reference_count": int(positive.size),
            "zero_probability": zero_probability,
            "gamma_shape": float(shape),
            "gamma_location": float(location),
            "gamma_scale": float(scale),
            "mixed_cdf": mixed_cdf,
            "clipped_cdf": clipped_cdf,
            "spi_3month": spi,
            "drought_status": (
                "drought" if spi < config.drought_threshold else "not_drought"
            ),
            "is_drought": bool(spi < config.drought_threshold),
        }
    )


@dataclass(frozen=True)
class MaskCandidateConfig:
    """Fixed SCL/cloud-probability/dark-shadow candidate policy."""

    candidate_id: str
    scl_clear_classes: tuple[int, ...]
    scl_shadow_classes: tuple[int, ...] = (3,)
    scl_invalid_classes: tuple[int, ...] = (0, 1)
    scl_cloud_classes: tuple[int, ...] = (8, 9, 10)
    cloud_probability_max_percent: float | None = None
    cloud_probability_uint8_required: bool = False
    shadow_mode: str = "scl_class_only"
    dark_nir_reflectance_max: float | None = None
    within_cloud_distance_m: float = 0.0
    pixel_size_m: float = 20.0
    dilation_m: float = 0.0

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        class_fields = (
            "scl_clear_classes",
            "scl_shadow_classes",
            "scl_invalid_classes",
            "scl_cloud_classes",
        )
        normalized_classes: dict[str, tuple[int, ...]] = {}
        for field_name in class_fields:
            classes = tuple(getattr(self, field_name))
            if field_name == "scl_clear_classes" and not classes:
                raise ValueError("scl_clear_classes must be non-empty")
            if len(set(classes)) != len(classes):
                raise ValueError(f"{field_name} must contain unique values")
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 11
                for value in classes
            ):
                raise ValueError(f"{field_name} must contain SCL integers in [0, 11]")
            normalized_classes[field_name] = tuple(sorted(classes))
            object.__setattr__(self, field_name, tuple(sorted(classes)))
        claimed: dict[int, str] = {}
        for field_name, classes in normalized_classes.items():
            for value in classes:
                if value in claimed:
                    raise ValueError(
                        f"SCL class {value} overlaps {claimed[value]} and {field_name}"
                    )
                claimed[value] = field_name

        threshold = self.cloud_probability_max_percent
        if threshold is not None:
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                raise TypeError("cloud_probability_max_percent must be numeric or null")
            threshold = float(threshold)
            if not math.isfinite(threshold) or not 0 <= threshold <= 100:
                raise ValueError("cloud_probability_max_percent must be in [0, 100]")
            object.__setattr__(self, "cloud_probability_max_percent", threshold)
        if not isinstance(self.cloud_probability_uint8_required, bool):
            raise TypeError("cloud_probability_uint8_required must be boolean")
        if self.shadow_mode not in {"scl_class_only", "scl_or_projected_dark_nir"}:
            raise ValueError("unsupported shadow_mode")
        for field_name in ("within_cloud_distance_m", "pixel_size_m", "dilation_m"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise TypeError(f"{field_name} must be finite numeric")
            object.__setattr__(self, field_name, float(value))
        if self.pixel_size_m <= 0:
            raise ValueError("pixel_size_m must be positive")
        if self.dilation_m < 0:
            raise ValueError("dilation_m must be non-negative")
        if self.shadow_mode == "scl_or_projected_dark_nir":
            if threshold is None:
                raise ValueError(
                    "projected dark-NIR shadow policy requires cloud probability"
                )
            dark_threshold = self.dark_nir_reflectance_max
            if (
                isinstance(dark_threshold, bool)
                or not isinstance(dark_threshold, (int, float))
                or not math.isfinite(float(dark_threshold))
            ):
                raise ValueError(
                    "projected dark-NIR shadow policy requires a finite threshold"
                )
            object.__setattr__(
                self, "dark_nir_reflectance_max", float(dark_threshold)
            )
            if self.within_cloud_distance_m <= 0:
                raise ValueError("within_cloud_distance_m must be positive")
        elif (
            self.dark_nir_reflectance_max is not None
            or self.within_cloud_distance_m != 0
        ):
            raise ValueError(
                "dark-NIR parameters are only valid for scl_or_projected_dark_nir"
            )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "candidate_id": self.candidate_id,
            "status": "candidate_only_not_selected_or_activated",
            "scl_clear_classes": list(self.scl_clear_classes),
            "scl_shadow_classes": list(self.scl_shadow_classes),
            "scl_invalid_classes": list(self.scl_invalid_classes),
            "scl_cloud_classes": list(self.scl_cloud_classes),
            "cloud_probability_max_percent": self.cloud_probability_max_percent,
            "cloud_probability_uint8_required": self.cloud_probability_uint8_required,
            "cloud_probability_comparison": (
                "less_than_or_equal"
                if self.cloud_probability_max_percent is not None
                else "not_applied"
            ),
            "shadow_mode": self.shadow_mode,
            "dark_nir_reflectance_max": self.dark_nir_reflectance_max,
            "within_cloud_distance_m": self.within_cloud_distance_m,
            "distance_metric": "euclidean_on_projected_processing_grid",
            "pixel_size_m": self.pixel_size_m,
            "dilation_m": self.dilation_m,
            "dilation_target": "union_of_cloud_and_shadow_mask",
            "missing_input_policy": "unavailable_no_fallback",
            "exclusive_reason_precedence": [
                "source_invalid",
                "scl_rejected",
                "cloud_rejected",
                "dark_shadow_rejected",
                "valid",
            ],
        }

    @property
    def config_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def _strict_2d_numeric(name: str, value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2 or array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must be a two-dimensional numeric array")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _strict_bool_mask(
    name: str, value: np.ndarray, shape: tuple[int, int]
) -> np.ndarray:
    array = np.asarray(value)
    if array.shape != shape:
        raise ValueError(f"{name} shape {array.shape} does not match {shape}")
    if array.dtype.kind != "b":
        raise TypeError(f"{name} must have boolean dtype")
    return np.asarray(array, dtype=bool)


def _comparison_mask(
    value: np.ndarray | None, shape: tuple[int, int]
) -> np.ndarray:
    comparison = (
        np.ones(shape, dtype=bool)
        if value is None
        else _strict_bool_mask("comparison_mask", value, shape)
    )
    if not np.any(comparison):
        raise ValueError("comparison_mask must contain at least one true pixel")
    return comparison


@dataclass(frozen=True)
class MaskResult:
    valid_mask: np.ndarray | None
    reason_map: np.ndarray | None
    cloud_mask: np.ndarray | None
    dark_shadow_mask: np.ndarray | None
    rejection_mask: np.ndarray | None
    record: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return copy.deepcopy(self.record)


def apply_mask_policy(
    scl: np.ndarray,
    *,
    config: MaskCandidateConfig,
    cloud_probability: np.ndarray | None = None,
    dark_nir_reflectance: np.ndarray | None = None,
    source_valid_mask: np.ndarray | None = None,
    comparison_mask: np.ndarray | None = None,
) -> MaskResult:
    """Apply one candidate mask and construct its dark-shadow evidence.

    For ``scl_or_projected_dark_nir``, a dark pixel is a shadow candidate when
    its NIR reflectance is at or below the fixed threshold and its Euclidean
    distance to a cloud pixel is at or below the configured distance.  SCL
    class shadows are unioned with those candidates.  Cloud and shadow masks
    are then dilated in projected-grid metres before the final clear mask is
    evaluated.  Missing required auxiliary arrays produce an explicit
    unavailable result, never an SCL-only fallback.
    """
    if not isinstance(config, MaskCandidateConfig):
        raise TypeError("config must be MaskCandidateConfig")
    scl_array = _strict_2d_numeric("scl", scl)
    if not np.all(scl_array == np.floor(scl_array)) or not np.all(
        (scl_array >= 0) & (scl_array <= 11)
    ):
        raise ValueError("scl must contain integer class values in [0, 11]")
    scl_array = scl_array.astype(np.int16, copy=False)
    shape = tuple(scl_array.shape)

    source_valid = (
        np.ones(shape, dtype=bool)
        if source_valid_mask is None
        else _strict_bool_mask("source_valid_mask", source_valid_mask, shape)
    )
    comparison = _comparison_mask(comparison_mask, shape)

    cloud_array = None
    if cloud_probability is not None:
        raw_cloud = np.asarray(cloud_probability)
        if config.cloud_probability_uint8_required and raw_cloud.dtype != np.uint8:
            raise TypeError("cloud_probability must have uint8 dtype")
        cloud_array = _strict_2d_numeric("cloud_probability", raw_cloud)
        if cloud_array.shape != shape:
            raise ValueError(
                f"cloud_probability shape {cloud_array.shape} does not match {shape}"
            )
        if not np.all((cloud_array >= 0) & (cloud_array <= 100)):
            raise ValueError("cloud_probability must be in [0, 100]")
        cloud_array = cloud_array.astype(np.float64, copy=False)

    dark_nir_array = None
    if dark_nir_reflectance is not None:
        dark_nir_array = np.asarray(dark_nir_reflectance)
        if dark_nir_array.ndim != 2 or dark_nir_array.dtype.kind not in "iuf":
            raise ValueError(
                "dark_nir_reflectance must be a two-dimensional numeric array"
            )
        if dark_nir_array.shape != shape:
            raise ValueError(
                f"dark_nir_reflectance shape {dark_nir_array.shape} "
                f"does not match {shape}"
            )
        dark_nir_array = dark_nir_array.astype(np.float64, copy=False)
        if np.any(np.isinf(dark_nir_array)) or np.any(
            source_valid & ~np.isfinite(dark_nir_array)
        ):
            raise ValueError(
                "dark_nir_reflectance must be finite wherever source_valid_mask is true"
            )

    input_record = {
        "schema": "phase2a4-mask-input-v1",
        "config_sha256": config.config_sha256,
        "scl": canonical_array_record(scl_array),
        "cloud_probability": (
            canonical_array_record(cloud_array) if cloud_array is not None else None
        ),
        "dark_nir_reflectance": (
            canonical_array_record(dark_nir_array)
            if dark_nir_array is not None
            else None
        ),
        "source_valid_mask": canonical_array_record(source_valid),
        "comparison_mask": canonical_array_record(comparison),
    }
    input_sha256 = canonical_sha256(input_record)
    missing_inputs: list[str] = []
    if config.cloud_probability_max_percent is not None and cloud_array is None:
        missing_inputs.append("cloud_probability")
    if config.shadow_mode == "scl_or_projected_dark_nir" and dark_nir_array is None:
        missing_inputs.append("dark_nir_reflectance")
    if missing_inputs:
        record = _output_record(
            {
                "schema_version": "1.0.0",
                "candidate_id": config.candidate_id,
                "candidate_only": True,
                "selected_or_activated": False,
                "status": "unavailable",
                "unavailable_reason": "missing_required_auxiliary_input",
                "missing_inputs": missing_inputs,
                "config_sha256": config.config_sha256,
                "input_sha256": input_sha256,
                "shape": list(shape),
                "array_pixel_count": int(comparison.size),
                "total_pixel_count": int(np.count_nonzero(comparison)),
                "outside_comparison_pixel_count": int(
                    np.count_nonzero(~comparison)
                ),
                "valid_pixel_count": None,
                "valid_coverage_fraction": None,
            }
        )
        return MaskResult(None, None, None, None, None, record)

    raw_cloud_mask = np.isin(scl_array, config.scl_cloud_classes) & source_valid
    if config.cloud_probability_max_percent is not None:
        raw_cloud_mask |= (
            cloud_array > config.cloud_probability_max_percent  # type: ignore[operator]
        ) & source_valid

    scl_shadow_mask = np.isin(scl_array, config.scl_shadow_classes) & source_valid
    projected_dark_shadow = np.zeros(shape, dtype=bool)
    if config.shadow_mode == "scl_or_projected_dark_nir" and np.any(raw_cloud_mask):
        distance_to_cloud = ndimage.distance_transform_edt(
            ~raw_cloud_mask,
            sampling=(config.pixel_size_m, config.pixel_size_m),
        )
        projected_dark_shadow = (
            source_valid
            & (
                dark_nir_array
                <= config.dark_nir_reflectance_max  # type: ignore[operator]
            )
            & (distance_to_cloud <= config.within_cloud_distance_m)
        )
    raw_shadow_mask = scl_shadow_mask | projected_dark_shadow

    def dilate(mask: np.ndarray) -> np.ndarray:
        if config.dilation_m == 0 or not np.any(mask):
            return mask.copy()
        distance = ndimage.distance_transform_edt(
            ~mask,
            sampling=(config.pixel_size_m, config.pixel_size_m),
        )
        return (distance <= config.dilation_m) & source_valid

    cloud_mask = dilate(raw_cloud_mask) & comparison
    shadow_mask = dilate(raw_shadow_mask) & comparison
    rejection_mask = cloud_mask | shadow_mask

    reason = np.full(shape, MASK_OUTSIDE_COMPARISON_CODE, dtype=np.uint8)
    remaining = comparison & source_valid
    reason[comparison & ~source_valid] = MASK_REASON_CODES["source_invalid"]
    reason[remaining] = MASK_REASON_CODES["valid"]

    categorized_cloud_or_shadow = np.isin(
        scl_array,
        config.scl_cloud_classes + config.scl_shadow_classes,
    )
    scl_criterion = (
        ~np.isin(scl_array, config.scl_clear_classes)
        & ~categorized_cloud_or_shadow
    )
    rejected = remaining & scl_criterion
    reason[rejected] = MASK_REASON_CODES["scl_rejected"]
    remaining &= ~scl_criterion

    rejected = remaining & cloud_mask
    reason[rejected] = MASK_REASON_CODES["cloud_rejected"]
    remaining &= ~cloud_mask

    rejected = remaining & shadow_mask
    reason[rejected] = MASK_REASON_CODES["dark_shadow_rejected"]
    remaining &= ~shadow_mask

    # The remaining SCL classes must be explicitly declared clear.
    undeclared = remaining & ~np.isin(scl_array, config.scl_clear_classes)
    reason[undeclared] = MASK_REASON_CODES["scl_rejected"]
    remaining &= ~undeclared

    valid = remaining
    total = int(np.count_nonzero(comparison))
    valid_count = int(np.count_nonzero(valid))
    exclusive_counts = {
        name: int(np.count_nonzero(comparison & (reason == code)))
        for name, code in MASK_REASON_CODES.items()
    }
    if sum(exclusive_counts.values()) != total:
        raise RuntimeError("internal mask accounting did not reconcile")
    record = _output_record(
        {
            "schema_version": "1.0.0",
            "candidate_id": config.candidate_id,
            "candidate_only": True,
            "selected_or_activated": False,
            "status": "available",
            "unavailable_reason": None,
            "config_sha256": config.config_sha256,
            "input_sha256": input_sha256,
            "shape": list(shape),
            "array_pixel_count": int(comparison.size),
            "total_pixel_count": total,
            "outside_comparison_pixel_count": int(np.count_nonzero(~comparison)),
            "source_valid_pixel_count": int(
                np.count_nonzero(comparison & source_valid)
            ),
            "valid_pixel_count": valid_count,
            "valid_coverage_fraction": valid_count / total if total else 0.0,
            "exclusive_reason_counts": exclusive_counts,
            "criterion_counts_with_overlap": {
                "source_invalid": int(
                    np.count_nonzero(comparison & ~source_valid)
                ),
                "scl_rejected": int(
                    np.count_nonzero(
                        comparison
                        & source_valid
                        & ~np.isin(scl_array, config.scl_clear_classes)
                    )
                ),
                "raw_cloud": int(
                    np.count_nonzero(comparison & raw_cloud_mask)
                ),
                "dilated_cloud": int(np.count_nonzero(cloud_mask)),
                "scl_shadow": int(
                    np.count_nonzero(comparison & scl_shadow_mask)
                ),
                "projected_dark_nir_shadow": int(
                    np.count_nonzero(comparison & projected_dark_shadow)
                ),
                "dark_shadow_rejected": int(
                    np.count_nonzero(shadow_mask)
                ),
                "dilated_cloud_shadow_union": int(np.count_nonzero(rejection_mask)),
            },
            "reason_codes": MASK_REASON_CODES,
            "outside_comparison_reason_code": MASK_OUTSIDE_COMPARISON_CODE,
            "comparison_mask": canonical_array_record(comparison),
            "raw_cloud_mask": canonical_array_record(raw_cloud_mask),
            "scl_shadow_mask": canonical_array_record(scl_shadow_mask),
            "projected_dark_shadow_mask": canonical_array_record(
                projected_dark_shadow
            ),
            "cloud_mask_after_dilation": canonical_array_record(cloud_mask),
            "dark_shadow_mask_after_dilation": canonical_array_record(shadow_mask),
            "cloud_shadow_rejection_mask": canonical_array_record(rejection_mask),
            "valid_mask": canonical_array_record(valid),
            "reason_map": canonical_array_record(reason),
        }
    )
    for array in (valid, reason, cloud_mask, shadow_mask, rejection_mask):
        array.setflags(write=False)
    return MaskResult(
        valid_mask=valid,
        reason_map=reason,
        cloud_mask=cloud_mask,
        dark_shadow_mask=shadow_mask,
        rejection_mask=rejection_mask,
        record=record,
    )


@dataclass(frozen=True)
class CompositionScene:
    """One fixed source scene presented to every composition candidate."""

    scene_id: str
    values: np.ndarray
    valid_mask: np.ndarray
    source_metadata_sha256: str
    scl: np.ndarray | None = None
    cloud_probability: np.ndarray | None = None


@dataclass(frozen=True)
class CompositionCandidateConfig:
    candidate_id: str
    method: str
    scl_rank_order: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        _candidate_id(self.candidate_id)
        if self.method not in {
            "coverage_ranked_first_valid",
            "min_cloudprob_sclrank_sceneid",
        }:
            raise ValueError("unsupported composition candidate method")
        if self.method == "coverage_ranked_first_valid":
            if self.scl_rank_order is not None:
                raise ValueError(
                    "scl_rank_order is not used by coverage-ranked composition"
                )
            return
        rank_order = (
            (2, 4, 5, 6, 7, 11)
            if self.scl_rank_order is None
            else tuple(self.scl_rank_order)
        )
        if not rank_order or len(rank_order) != len(set(rank_order)):
            raise ValueError("scl_rank_order must be non-empty and unique")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 11
            for value in rank_order
        ):
            raise ValueError("scl_rank_order must contain SCL integers in [0, 11]")
        object.__setattr__(self, "scl_rank_order", rank_order)

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "candidate_id": self.candidate_id,
            "status": "candidate_only_not_selected_or_activated",
            "method": self.method,
            "source_scene_identity": "caller_supplied_provider_native_scene_id",
            "source_scene_set_rule": "fixed_identical_set_for_all_candidates",
            "valid_pixel_rule": "scene_valid_mask_and_all_output_bands_finite",
            "tie_breaker": "scene_id_utf8_ascending",
            "scl_rank_order": (
                list(self.scl_rank_order)
                if self.scl_rank_order is not None
                else None
            ),
            "scl_rank_is_quality_claim": False,
            "uncovered_output": "nan_with_contributor_minus_one",
            "coverage_denominator": "all_pixels_in_fixed_comparison_grid",
            "score_rule": (
                "cloud_probability_uint8_then_scl_rank_then_scene_id"
                if self.method == "min_cloudprob_sclrank_sceneid"
                else "higher_scene_valid_coverage_then_scene_id"
            ),
        }

    @property
    def config_sha256(self) -> str:
        return canonical_sha256(self.to_record())


@dataclass(frozen=True)
class CompositionResult:
    values: np.ndarray
    valid_mask: np.ndarray
    contributor_map: np.ndarray
    source_scene_ids: tuple[str, ...]
    contributing_scene_ids: tuple[str, ...]
    per_scene_pixel_counts: dict[str, int]
    record: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return copy.deepcopy(self.record)


@dataclass(frozen=True)
class _NormalizedScene:
    scene_id: str
    values: np.ndarray
    valid_mask: np.ndarray
    scl: np.ndarray | None
    cloud_probability: np.ndarray | None
    source_metadata_sha256: str
    original_ndim: int


def _normalize_scenes(
    scenes: Sequence[CompositionScene], *, require_pixel_scores: bool
) -> tuple[list[_NormalizedScene], int]:
    if not isinstance(scenes, Sequence) or isinstance(scenes, (str, bytes)):
        raise TypeError("scenes must be a sequence of CompositionScene")
    if not scenes:
        raise ValueError("at least one source scene is required")
    normalized: list[_NormalizedScene] = []
    ids: set[str] = set()
    expected_shape: tuple[int, int, int] | None = None
    expected_ndim: int | None = None
    for scene in scenes:
        if not isinstance(scene, CompositionScene):
            raise TypeError("every scene must be CompositionScene")
        if not isinstance(scene.scene_id, str) or not scene.scene_id:
            raise ValueError("scene_id must be a non-empty provider-native identifier")
        if scene.scene_id in ids:
            raise ValueError(f"duplicate scene_id: {scene.scene_id}")
        ids.add(scene.scene_id)
        if not isinstance(scene.source_metadata_sha256, str) or not _SHA256.fullmatch(
            scene.source_metadata_sha256
        ):
            raise ValueError(
                "source_metadata_sha256 is required and must be 64 "
                "lowercase hex characters"
            )

        raw_values = np.asarray(scene.values)
        if raw_values.ndim not in {2, 3} or raw_values.dtype.kind not in "iuf":
            raise ValueError(
                "scene values must be a 2D or bands-first 3D numeric array"
            )
        original_ndim = raw_values.ndim
        values = (
            raw_values[np.newaxis, ...]
            if original_ndim == 2
            else raw_values
        ).astype(np.float64, copy=True)
        if expected_ndim is None:
            expected_ndim = original_ndim
        elif original_ndim != expected_ndim:
            raise ValueError("all scene values must use the same dimensionality")
        if expected_shape is None:
            expected_shape = tuple(values.shape)
        elif tuple(values.shape) != expected_shape:
            raise ValueError(
                f"scene value shape {values.shape} does not match {expected_shape}"
            )
        spatial_shape = tuple(values.shape[-2:])
        valid = _strict_bool_mask("scene.valid_mask", scene.valid_mask, spatial_shape)
        if not np.all(np.isfinite(values[:, valid])):
            raise ValueError(
                f"scene {scene.scene_id} has non-finite values at pixels marked valid"
            )

        scl = None
        if scene.scl is not None:
            raw_scl = _strict_2d_numeric("scene.scl", scene.scl)
            if raw_scl.shape != spatial_shape:
                raise ValueError(
                    f"scene.scl shape {raw_scl.shape} does not match {spatial_shape}"
                )
            if not np.all(raw_scl == np.floor(raw_scl)) or not np.all(
                (raw_scl >= 0) & (raw_scl <= 11)
            ):
                raise ValueError("scene.scl must contain integer classes in [0, 11]")
            scl = raw_scl.astype(np.int16, copy=True)

        cloud = None
        if scene.cloud_probability is not None:
            raw_cloud = np.asarray(scene.cloud_probability)
            if raw_cloud.shape != spatial_shape or raw_cloud.dtype != np.uint8:
                raise ValueError(
                    "scene.cloud_probability must be a matching 2D uint8 array"
                )
            cloud = raw_cloud.copy()
            if not np.all(cloud <= 100):
                raise ValueError(
                    f"scene {scene.scene_id} cloud probability must be in [0, 100]"
                )
        if require_pixel_scores and cloud is None:
            raise ValueError(
                f"scene {scene.scene_id} lacks cloud_probability required by "
                "pixel ranking"
            )
        if require_pixel_scores and scl is None:
            raise ValueError(
                f"scene {scene.scene_id} lacks SCL required by pixel ranking"
            )
        normalized.append(
            _NormalizedScene(
                scene_id=scene.scene_id,
                values=values,
                valid_mask=valid.copy(),
                scl=scl,
                cloud_probability=cloud,
                source_metadata_sha256=scene.source_metadata_sha256,
                original_ndim=original_ndim,
            )
        )
    normalized.sort(key=lambda item: item.scene_id.encode("utf-8"))
    return normalized, int(expected_ndim)


def _composition_input_record(
    scenes: Sequence[_NormalizedScene],
    config: CompositionCandidateConfig,
    comparison_mask: np.ndarray,
) -> dict[str, Any]:
    return {
        "schema": "phase2a4-composition-input-v1",
        "config_sha256": config.config_sha256,
        "comparison_mask": canonical_array_record(comparison_mask),
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "source_metadata_sha256": scene.source_metadata_sha256,
                "values": canonical_array_record(scene.values),
                "valid_mask": canonical_array_record(scene.valid_mask),
                "scl": (
                    canonical_array_record(scene.scl)
                    if scene.scl is not None
                    else None
                ),
                "cloud_probability": (
                    canonical_array_record(scene.cloud_probability)
                    if scene.cloud_probability is not None
                    else None
                ),
            }
            for scene in scenes
        ],
    }


def _composition_result(
    *,
    scenes: Sequence[_NormalizedScene],
    config: CompositionCandidateConfig,
    values: np.ndarray,
    valid: np.ndarray,
    contributor: np.ndarray,
    composition_order: Sequence[str],
    original_ndim: int,
    comparison_mask: np.ndarray,
) -> CompositionResult:
    source_ids = tuple(scene.scene_id for scene in scenes)
    counts = {
        scene_id: int(np.count_nonzero(contributor == index))
        for index, scene_id in enumerate(source_ids)
    }
    contributing = tuple(scene_id for scene_id in source_ids if counts[scene_id] > 0)
    valid_count = int(np.count_nonzero(valid))
    total = int(np.count_nonzero(comparison_mask))
    scene_valid_counts = {
        scene.scene_id: int(
            np.count_nonzero(comparison_mask & scene.valid_mask)
        )
        for scene in scenes
    }
    if sum(counts.values()) != valid_count:
        raise RuntimeError("internal contributor accounting did not reconcile")
    public_values = values[0] if original_ndim == 2 else values
    input_record = _composition_input_record(scenes, config, comparison_mask)
    record = _output_record(
        {
            "schema_version": "1.0.0",
            "candidate_id": config.candidate_id,
            "candidate_only": True,
            "selected_or_activated": False,
            "status": "available",
            "method": config.method,
            "config_sha256": config.config_sha256,
            "input_sha256": canonical_sha256(input_record),
            "source_scene_ids": list(source_ids),
            "composition_order_scene_ids": list(composition_order),
            "contributing_scene_ids": list(contributing),
            "per_scene_pixel_counts": counts,
            "per_scene_valid_pixel_counts": scene_valid_counts,
            "per_scene_valid_coverage_fractions": {
                scene_id: count / total if total else 0.0
                for scene_id, count in scene_valid_counts.items()
            },
            "contributor_index_to_scene_id": {
                str(index): scene_id for index, scene_id in enumerate(source_ids)
            },
            "array_pixel_count": int(comparison_mask.size),
            "total_pixel_count": total,
            "outside_comparison_pixel_count": int(
                np.count_nonzero(~comparison_mask)
            ),
            "valid_pixel_count": valid_count,
            "valid_coverage_fraction": valid_count / total if total else 0.0,
            "comparison_mask": canonical_array_record(comparison_mask),
            "values": canonical_array_record(public_values),
            "valid_mask": canonical_array_record(valid),
            "contributor_map": canonical_array_record(contributor),
        }
    )
    public_values.setflags(write=False)
    valid.setflags(write=False)
    contributor.setflags(write=False)
    return CompositionResult(
        values=public_values,
        valid_mask=valid,
        contributor_map=contributor,
        source_scene_ids=source_ids,
        contributing_scene_ids=contributing,
        per_scene_pixel_counts=counts,
        record=record,
    )


def compose_coverage_ranked_first_valid(
    scenes: Sequence[CompositionScene],
    *,
    config: CompositionCandidateConfig,
    comparison_mask: np.ndarray | None = None,
) -> CompositionResult:
    """Fill each pixel from the highest-coverage valid scene.

    Scene coverage is ranked descending; provider-native scene ID ascending is
    the deterministic tie-break.  The output is invariant to caller input order.
    """
    if not isinstance(config, CompositionCandidateConfig):
        raise TypeError("config must be CompositionCandidateConfig")
    if config.method != "coverage_ranked_first_valid":
        raise ValueError("config method must be coverage_ranked_first_valid")
    normalized, original_ndim = _normalize_scenes(
        scenes, require_pixel_scores=False
    )
    comparison = _comparison_mask(
        comparison_mask, tuple(normalized[0].valid_mask.shape)
    )
    ranked = sorted(
        normalized,
        key=lambda scene: (
            -int(np.count_nonzero(comparison & scene.valid_mask)),
            scene.scene_id.encode("utf-8"),
        ),
    )
    spatial_shape = tuple(normalized[0].valid_mask.shape)
    values = np.full(normalized[0].values.shape, np.nan, dtype=np.float64)
    valid = np.zeros(spatial_shape, dtype=bool)
    contributor = np.full(spatial_shape, -1, dtype=np.int32)
    source_index = {scene.scene_id: index for index, scene in enumerate(normalized)}
    for scene in ranked:
        take = comparison & scene.valid_mask & ~valid
        values[:, take] = scene.values[:, take]
        valid[take] = True
        contributor[take] = source_index[scene.scene_id]
    return _composition_result(
        scenes=normalized,
        config=config,
        values=values,
        valid=valid,
        contributor=contributor,
        composition_order=[scene.scene_id for scene in ranked],
        original_ndim=original_ndim,
        comparison_mask=comparison,
    )


def compose_min_cloudprob_sclrank_sceneid(
    scenes: Sequence[CompositionScene],
    *,
    config: CompositionCandidateConfig,
    comparison_mask: np.ndarray | None = None,
) -> CompositionResult:
    """Choose a source by cloud probability, SCL rank, then scene ID.

    Cloud probability is an integer percent.  Lower values win.  Exact cloud
    ties use the fixed SCL rank, and exact score ties use the provider-native
    scene ID in UTF-8 ascending order.  The SCL order is a fixed candidate
    parameter, not an accepted quality claim.
    """
    if not isinstance(config, CompositionCandidateConfig):
        raise TypeError("config must be CompositionCandidateConfig")
    if config.method != "min_cloudprob_sclrank_sceneid":
        raise ValueError("config method must be min_cloudprob_sclrank_sceneid")
    normalized, original_ndim = _normalize_scenes(
        scenes, require_pixel_scores=True
    )
    comparison = _comparison_mask(
        comparison_mask, tuple(normalized[0].valid_mask.shape)
    )
    rank_lookup = np.full(12, -1, dtype=np.int16)
    for rank, scl_class in enumerate(config.scl_rank_order or ()):
        rank_lookup[scl_class] = rank
    for scene in normalized:
        scene_ranks = rank_lookup[scene.scl]  # type: ignore[index]
        if np.any(comparison & scene.valid_mask & (scene_ranks < 0)):
            invalid = sorted(
                int(value)
                for value in np.unique(
                    scene.scl[comparison & scene.valid_mask]  # type: ignore[index]
                )
                if rank_lookup[int(value)] < 0
            )
            raise ValueError(
                f"scene {scene.scene_id} has valid SCL classes absent from "
                f"rank order: {invalid}"
            )
    spatial_shape = tuple(normalized[0].valid_mask.shape)
    values = np.full(normalized[0].values.shape, np.nan, dtype=np.float64)
    valid = np.zeros(spatial_shape, dtype=bool)
    contributor = np.full(spatial_shape, -1, dtype=np.int32)
    best_cloud = np.full(spatial_shape, 101, dtype=np.int16)
    best_scl_rank = np.full(spatial_shape, 32767, dtype=np.int16)
    for index, scene in enumerate(normalized):
        cloud_score = scene.cloud_probability.astype(  # type: ignore[union-attr]
            np.int16
        )
        scl_score = rank_lookup[scene.scl]  # type: ignore[index]
        take = comparison & scene.valid_mask & (
            (cloud_score < best_cloud)
            | ((cloud_score == best_cloud) & (scl_score < best_scl_rank))
        )
        values[:, take] = scene.values[:, take]
        valid[take] = True
        best_cloud[take] = cloud_score[take]
        best_scl_rank[take] = scl_score[take]
        contributor[take] = index
    return _composition_result(
        scenes=normalized,
        config=config,
        values=values,
        valid=valid,
        contributor=contributor,
        composition_order=[scene.scene_id for scene in normalized],
        original_ndim=original_ndim,
        comparison_mask=comparison,
    )


def compose_clearest_pixel(
    scenes: Sequence[CompositionScene],
    *,
    config: CompositionCandidateConfig,
    comparison_mask: np.ndarray | None = None,
) -> CompositionResult:
    """Compatibility name for the fixed cloud/SCL/scene-ID candidate."""
    return compose_min_cloudprob_sclrank_sceneid(
        scenes, config=config, comparison_mask=comparison_mask
    )


__all__ = [
    "CompositionCandidateConfig",
    "CompositionResult",
    "CompositionScene",
    "DroughtCandidateConfig",
    "MASK_OUTSIDE_COMPARISON_CODE",
    "MASK_REASON_CODES",
    "MaskCandidateConfig",
    "MaskResult",
    "apply_mask_policy",
    "canonical_array_record",
    "compose_clearest_pixel",
    "compose_coverage_ranked_first_valid",
    "compose_min_cloudprob_sclrank_sceneid",
    "compute_season_matched_spi3",
]
