"""Package 2A.6B candidate cloud mask: ``scl-explicit-allowlist-v2``.

Implements the mask selected by
``config/phase2a_candidate_generation_decisions_v2.json`` and the 2026-08-11
decision record.  The policy is an explicit SCL allowlist only:

- accept SCL 4, 5, 6, and 7;
- reject SCL 0, 1, 2, 3, 8, 9, 10, and 11;
- fail closed on missing, unexpected, or unreviewed SCL or
  processing-baseline metadata;
- keep class 2 rejected under both pre- and post-PB04 semantics;
- no dark-NIR proximity mask and no cloud-shadow dilation; and
- record the SCL 7 fraction as QA without any scientific-validation claim.

This module is candidate-generation code.  The legacy v1 policy in
``src/processing/cloud_mask.py`` (which accepts SCL 2 and 11) remains
audit-only and is intentionally not modified here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np

from src.detection.identity import canonical_sha256


SCL_MASK_METHOD_ID = "scl-explicit-allowlist-v2"
SCL_ACCEPTED_CLASSES = (4, 5, 6, 7)
SCL_REJECTED_CLASSES = (0, 1, 2, 3, 8, 9, 10, 11)
SCL_KNOWN_CLASSES = tuple(range(12))
SCL_CLASS_LABELS = MappingProxyType(
    {
        0: "no-data",
        1: "saturated-or-defective",
        2: "cast-shadows",
        3: "cloud-shadows",
        4: "vegetation",
        5: "not-vegetated",
        6: "water",
        7: "unclassified",
        8: "cloud-medium-probability",
        9: "cloud-high-probability",
        10: "thin-cirrus",
        11: "snow-or-ice",
    }
)

# Fixed policy tokens from the accepted decision record.
DARK_NIR_PROXIMITY_MASK = False
CLOUD_SHADOW_DILATION_M = 0
PROCESSING_BASELINE_FIELD_PRIORITY = (
    "s2:processing_baseline",
    "PROCESSING_BASELINE",
)
PROCESSING_BASELINE_NORMALIZATION_RULE = (
    "parse_provider_decimal_string_without_rounding"
)
PB04_BOUNDARY = "04.00"
SCL_CLASS2_SEMANTICS_PRE_PB04 = "dark-area-pixels"
SCL_CLASS2_SEMANTICS_POST_PB04 = "cast-shadows"

# Reviewed processing baselines.  This registry is the complete enumeration
# observed across the 70 retained Phase 2A.4 pilot source scenes bound by the
# 2026-08-11 decision record.  Any value outside the registry fails closed
# until a recorded review extends it.
REVIEWED_PROCESSING_BASELINE_REGISTRY_ID = (
    "araripe-reviewed-processing-baselines-v1"
)
REVIEWED_PROCESSING_BASELINES = ("05.11", "05.12")

SCL7_QA_POLICY = MappingProxyType(
    {
        "candidate_generation_treatment": "provisionally_clear",
        "scientifically_validated": False,
        "public_quality_claim_permitted": False,
        "phase5_validation_required": True,
    }
)

_BASELINE_RE = re.compile(r"^([0-9]{1,2})\.([0-9]{2})$")
_DATATAKE_RE = re.compile(
    r"^GS2([A-D])_([0-9]{8}T[0-9]{6})_([0-9]{6})_N([0-9]{2}\.[0-9]{2})$"
)


class SclMaskUnavailableError(ValueError):
    """The scene is unavailable under the fail-closed v2 mask policy.

    ``reason_code`` is a stable lowercase token accepted by the
    processing-ledger-v2 ``reason.code`` charset.
    """

    reason_code = "scl-mask-unavailable"

    def __init__(
        self,
        message: str,
        *,
        scene_id: str | None = None,
        observed_baseline: str | None = None,
    ) -> None:
        if scene_id:
            message = f"{message} (scene {scene_id})"
        super().__init__(message)
        self.scene_id = scene_id
        self.observed_baseline = observed_baseline
        # Every readable normalized baseline across the failing datatake's
        # scenes; the composition gate fills this so run evidence can
        # enumerate observed baselines even for multi-scene failures.
        self.observed_baselines: tuple[str, ...] = (
            (observed_baseline,) if observed_baseline is not None else ()
        )


class MissingSclError(SclMaskUnavailableError):
    reason_code = "scl-missing"


class UnexpectedSclValueError(SclMaskUnavailableError):
    reason_code = "scl-unexpected-value"


class MissingProcessingBaselineError(SclMaskUnavailableError):
    reason_code = "processing-baseline-missing"


class UnexpectedProcessingBaselineError(SclMaskUnavailableError):
    reason_code = "processing-baseline-unexpected"


class UnreviewedProcessingBaselineError(SclMaskUnavailableError):
    reason_code = "processing-baseline-unreviewed"


@dataclass(frozen=True)
class ProcessingBaselineV2:
    """One provider processing-baseline reading, normalized without rounding."""

    source_field: str
    raw_value: str
    normalized_value: str

    @property
    def numeric_key(self) -> tuple[int, int]:
        major, fractional = self.normalized_value.split(".")
        return int(major), int(fractional)

    @property
    def class2_semantics(self) -> str:
        pb04_major, pb04_fractional = PB04_BOUNDARY.split(".")
        if self.numeric_key < (int(pb04_major), int(pb04_fractional)):
            return SCL_CLASS2_SEMANTICS_PRE_PB04
        return SCL_CLASS2_SEMANTICS_POST_PB04

    def qa_dict(self) -> dict[str, Any]:
        return {
            "source_field": self.source_field,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "normalization_rule": PROCESSING_BASELINE_NORMALIZATION_RULE,
            "pb04_boundary": PB04_BOUNDARY,
            "scl_class2_semantics": self.class2_semantics,
            "scl_class2_accepted": False,
        }


def normalize_processing_baseline_value(
    value: Any, *, source_field: str, scene_id: str | None = None
) -> str:
    """Normalize a provider decimal baseline string without rounding.

    Only the provider's exact decimal string form is accepted; a numeric type
    has already passed through a parser that may round, so it fails closed.
    Normalization zero-pads the major component and preserves every fractional
    digit verbatim.
    """

    if not isinstance(value, str):
        raise UnexpectedProcessingBaselineError(
            f"{source_field} must be the provider decimal string, "
            f"got {type(value).__name__}",
            scene_id=scene_id,
        )
    match = _BASELINE_RE.fullmatch(value)
    if match is None:
        raise UnexpectedProcessingBaselineError(
            f"{source_field} value {value!r} is not a provider "
            "NN.NN decimal baseline",
            scene_id=scene_id,
        )
    return f"{int(match.group(1)):02d}.{match.group(2)}"


def read_processing_baseline(
    properties: Mapping[str, Any], *, scene_id: str | None = None
) -> ProcessingBaselineV2:
    """Read the baseline using the fixed metadata-field priority.

    ``s2:processing_baseline`` (STAC) is read before ``PROCESSING_BASELINE``
    (GEE).  A present-but-invalid higher-priority field fails closed instead
    of falling through to the next field.
    """

    if not isinstance(properties, Mapping):
        raise MissingProcessingBaselineError(
            "scene metadata properties are missing", scene_id=scene_id
        )
    for source_field in PROCESSING_BASELINE_FIELD_PRIORITY:
        if source_field not in properties:
            continue
        value = properties[source_field]
        if value is None:
            raise MissingProcessingBaselineError(
                f"{source_field} is present but null", scene_id=scene_id
            )
        normalized = normalize_processing_baseline_value(
            value, source_field=source_field, scene_id=scene_id
        )
        return ProcessingBaselineV2(
            source_field=source_field,
            raw_value=value,
            normalized_value=normalized,
        )
    raise MissingProcessingBaselineError(
        "scene metadata has none of the processing-baseline fields "
        + "/".join(PROCESSING_BASELINE_FIELD_PRIORITY),
        scene_id=scene_id,
    )


def require_datatake_baseline_consistency(
    datatake_id: str,
    baseline: ProcessingBaselineV2,
    *,
    scene_id: str | None = None,
) -> None:
    """Cross-check a provider ``GS2X_...NNN.NN`` datatake baseline suffix.

    All 70 retained Phase 2A.4 pilot scenes carry a datatake suffix equal to
    ``s2:processing_baseline``; a mismatch is a metadata inconsistency and
    fails closed.  Identifiers that do not start with ``GS2`` carry no suffix
    and are not cross-checked here.
    """

    if not isinstance(datatake_id, str) or not datatake_id.startswith("GS2"):
        return
    match = _DATATAKE_RE.fullmatch(datatake_id)
    if match is None:
        raise UnexpectedProcessingBaselineError(
            f"datatake_id {datatake_id!r} is not a canonical provider "
            "GS2X_YYYYMMDDTHHMMSS_OOOOOO_NNN.NN identifier",
            scene_id=scene_id,
        )
    suffix = match.group(4)
    if suffix != baseline.normalized_value:
        raise UnexpectedProcessingBaselineError(
            f"datatake_id baseline suffix N{suffix} disagrees with "
            f"{baseline.source_field} {baseline.normalized_value}",
            scene_id=scene_id,
            observed_baseline=baseline.normalized_value,
        )


def require_reviewed_processing_baseline(
    baseline: ProcessingBaselineV2,
    reviewed_baselines: Iterable[str] = REVIEWED_PROCESSING_BASELINES,
    *,
    scene_id: str | None = None,
) -> None:
    reviewed = frozenset(reviewed_baselines)
    if baseline.normalized_value not in reviewed:
        raise UnreviewedProcessingBaselineError(
            f"processing baseline {baseline.normalized_value} is not in the "
            f"reviewed registry {REVIEWED_PROCESSING_BASELINE_REGISTRY_ID}",
            scene_id=scene_id,
            observed_baseline=baseline.normalized_value,
        )


def reviewed_baseline_registry_dict(
    reviewed_baselines: Iterable[str] = REVIEWED_PROCESSING_BASELINES,
) -> dict[str, Any]:
    values = sorted(set(reviewed_baselines))
    for value in values:
        if _BASELINE_RE.fullmatch(value) is None or value != (
            f"{int(value.split('.')[0]):02d}.{value.split('.')[1]}"
        ):
            raise ValueError(
                f"reviewed baseline {value!r} is not in normalized NN.NN form"
            )
    return {
        "registry_id": REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
        "reviewed_values": values,
        "unreviewed_value_policy": "unavailable_fail_closed",
    }


@dataclass(frozen=True)
class SceneSclMaskV2:
    """One scene's fail-closed SCL allowlist evaluation."""

    scene_id: str | None
    method_id: str
    processing_baseline: ProcessingBaselineV2
    accepted_mask: np.ndarray
    class_pixel_counts: Mapping[int, int]
    total_pixel_count: int
    accepted_pixel_count: int
    scl7_pixel_count: int
    scl7_fraction_of_accepted: float | None

    def qa_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "scene_id": self.scene_id,
            "processing_baseline": self.processing_baseline.qa_dict(),
            "accepted_scl_classes": list(SCL_ACCEPTED_CLASSES),
            "rejected_scl_classes": list(SCL_REJECTED_CLASSES),
            "dark_nir_proximity_mask": DARK_NIR_PROXIMITY_MASK,
            "cloud_shadow_dilation_m": CLOUD_SHADOW_DILATION_M,
            "class_pixel_counts": [
                {
                    "scl_class": scl_class,
                    # Class 2 semantics changed at PB04; label it by the
                    # scene's actual baseline regime instead of one epoch.
                    "label": (
                        self.processing_baseline.class2_semantics
                        if scl_class == 2
                        else SCL_CLASS_LABELS[scl_class]
                    ),
                    "accepted": scl_class in SCL_ACCEPTED_CLASSES,
                    "pixel_count": self.class_pixel_counts[scl_class],
                }
                for scl_class in SCL_KNOWN_CLASSES
            ],
            "total_pixel_count": self.total_pixel_count,
            "accepted_pixel_count": self.accepted_pixel_count,
            "scl7": {
                "pixel_count": self.scl7_pixel_count,
                "fraction_of_accepted": self.scl7_fraction_of_accepted,
                **dict(SCL7_QA_POLICY),
            },
        }

    def qa_sha256(self) -> str:
        return canonical_sha256(self.qa_dict())


def compute_scene_scl_mask(
    scl: Any,
    *,
    properties: Mapping[str, Any],
    scene_id: str | None = None,
    datatake_id: str | None = None,
    reviewed_baselines: Iterable[str] = REVIEWED_PROCESSING_BASELINES,
) -> SceneSclMaskV2:
    """Evaluate ``scl-explicit-allowlist-v2`` for one scene, failing closed.

    Metadata gates run before pixels are touched: the processing baseline must
    be readable through the fixed field priority, consistent with a provider
    datatake suffix when one is present, and a member of the reviewed
    registry.  The SCL array must be a non-empty 2-D integer grid containing
    only the twelve known classes.
    """

    baseline = read_processing_baseline(properties, scene_id=scene_id)
    if datatake_id is not None:
        require_datatake_baseline_consistency(
            datatake_id, baseline, scene_id=scene_id
        )
    require_reviewed_processing_baseline(
        baseline, reviewed_baselines, scene_id=scene_id
    )

    if scl is None:
        raise MissingSclError("scene has no SCL band", scene_id=scene_id)
    if isinstance(scl, np.ma.MaskedArray):
        # np.asarray would silently drop the nodata mask and accept the
        # stored fill values as real SCL classes.
        raise UnexpectedSclValueError(
            "SCL must not be a masked array; resolve nodata explicitly "
            "before the fail-closed allowlist",
            scene_id=scene_id,
        )
    array = np.asarray(scl)
    if array.dtype.kind not in "iu":
        raise UnexpectedSclValueError(
            f"SCL must be integer-typed, got dtype {array.dtype}",
            scene_id=scene_id,
        )
    if array.ndim != 2:
        raise UnexpectedSclValueError(
            f"SCL must be a 2-D grid, got {array.ndim} dimension(s)",
            scene_id=scene_id,
        )
    if array.size == 0:
        raise UnexpectedSclValueError("SCL grid is empty", scene_id=scene_id)
    minimum = int(array.min())
    maximum = int(array.max())
    if minimum < 0 or maximum > max(SCL_KNOWN_CLASSES):
        unexpected = sorted(
            int(value)
            for value in np.unique(array)
            if int(value) < 0 or int(value) > max(SCL_KNOWN_CLASSES)
        )
        raise UnexpectedSclValueError(
            f"SCL contains unexpected value(s) {unexpected}", scene_id=scene_id
        )

    counts = np.bincount(array.ravel(), minlength=len(SCL_KNOWN_CLASSES))
    class_pixel_counts = {
        scl_class: int(counts[scl_class]) for scl_class in SCL_KNOWN_CLASSES
    }
    accepted_mask = np.isin(array, np.asarray(SCL_ACCEPTED_CLASSES))
    accepted_mask.setflags(write=False)
    accepted_pixel_count = int(accepted_mask.sum())
    scl7_pixel_count = class_pixel_counts[7]
    scl7_fraction = (
        scl7_pixel_count / accepted_pixel_count if accepted_pixel_count else None
    )
    return SceneSclMaskV2(
        scene_id=scene_id,
        method_id=SCL_MASK_METHOD_ID,
        processing_baseline=baseline,
        accepted_mask=accepted_mask,
        class_pixel_counts=MappingProxyType(class_pixel_counts),
        total_pixel_count=int(array.size),
        accepted_pixel_count=accepted_pixel_count,
        scl7_pixel_count=scl7_pixel_count,
        scl7_fraction_of_accepted=scl7_fraction,
    )


def enumerate_observed_baselines(
    masks: Iterable[SceneSclMaskV2],
) -> tuple[str, ...]:
    """Enumerate every distinct normalized baseline observed across scenes."""

    return tuple(
        sorted({mask.processing_baseline.normalized_value for mask in masks})
    )
