"""Deterministic Package 2A.6A identities for physical acquisitions.

This module is deliberately separate from :mod:`src.detection.identity`.
Version 1 models one canonical acquisition per date and is audit-only for new
candidate data.  Version 2 models one physical datatake per acquisition and
refuses every cross-major reference.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable

from shapely.geometry.base import BaseGeometry

from src.detection.identity import (
    LINE_FEED,
    canonical_geometry_sha256,
    identity_sha256,
)


SCHEMA_VERSION = "2.0.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_VERSIONED_METHOD_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*-v[1-9][0-9]*$")


class IdentityMajorError(ValueError):
    """An identity reference belongs to another contract major."""


def require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def require_v2_id(value: str, *, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise IdentityMajorError(f"{label} must use the {prefix} identity major")
    require_sha256(value[len(prefix) :], label=label)
    return value


def require_nonempty(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if any(ord(character) < 0x20 for character in value):
        raise ValueError(f"{label} cannot contain control characters")
    return value


def require_semver(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SEMVER_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must use Semantic Versioning")
    return value


def require_versioned_method(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _VERSIONED_METHOD_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase versioned method ID")
    return value


def normalize_utc_timestamp(value: str | datetime, *, label: str) -> str:
    """Normalize an instant to the contract's canonical ``...Z`` form.

    String inputs are intentionally required to declare UTC explicitly.  A
    timezone-aware ``datetime`` may use another offset and is normalized to
    UTC.  Fractional seconds are retained without trailing zeroes.
    """

    if isinstance(value, str):
        if _UTC_TIMESTAMP_RE.fullmatch(value) is None:
            raise ValueError(f"{label} must be an explicit RFC 3339 UTC timestamp")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError(f"{label} is not a valid UTC timestamp") from exc
    elif isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} datetime must be timezone-aware")
        parsed = value.astimezone(timezone.utc)
    else:
        raise TypeError(f"{label} must be a string or datetime")

    parsed = parsed.astimezone(timezone.utc)
    base = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    if parsed.microsecond:
        base += "." + f"{parsed.microsecond:06d}".rstrip("0")
    return base + "Z"


def require_utc_date(value: str, *, label: str = "observed_on") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use canonical YYYY-MM-DD form")
    return value


def sorted_unique(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    items = tuple(values)
    if not items:
        raise ValueError(f"{label} must contain at least one item")
    for item in items:
        require_nonempty(item, label=f"{label} item")
    if len(items) != len(set(items)):
        raise ValueError(f"{label} contains duplicates")
    return tuple(sorted(items, key=lambda item: item.encode("utf-8")))


def sorted_v2_ids(
    values: Iterable[str], *, prefix: str, label: str, allow_empty: bool = False
) -> tuple[str, ...]:
    items = tuple(values)
    if not items and not allow_empty:
        raise ValueError(f"{label} must contain at least one item")
    for item in items:
        require_v2_id(item, prefix=prefix, label=f"{label} item")
    if len(items) != len(set(items)):
        raise ValueError(f"{label} contains duplicates")
    return tuple(sorted(items, key=lambda item: item.encode("utf-8")))


def validate_run_manifest_binding(
    run_manifest_id: str, run_manifest_sha256: str
) -> tuple[str, str]:
    require_v2_id(run_manifest_id, prefix="run-v2-", label="run_manifest_id")
    require_sha256(run_manifest_sha256, label="run_manifest_sha256")
    return run_manifest_id, run_manifest_sha256


@dataclass(frozen=True)
class AcquisitionV2:
    acquisition_id: str
    identity_inputs_sha256: str
    run_manifest_id: str
    run_manifest_sha256: str
    collection_id: str
    platform: str
    datatake_id: str
    acquisition_timestamp_utc: str
    observed_on: str
    scene_ids: tuple[str, ...]
    monitoring_extent_id: str
    composite_method_id: str
    grid_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "acquisition_id": self.acquisition_id,
            "identity_inputs_sha256": self.identity_inputs_sha256,
            "run_manifest_id": self.run_manifest_id,
            "run_manifest_sha256": self.run_manifest_sha256,
            "collection_id": self.collection_id,
            "platform": self.platform,
            "datatake_id": self.datatake_id,
            "acquisition_timestamp_utc": self.acquisition_timestamp_utc,
            "observed_on": self.observed_on,
            "scene_ids": list(self.scene_ids),
            "monitoring_extent_id": self.monitoring_extent_id,
            "composite_method_id": self.composite_method_id,
            "grid_id": self.grid_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcquisitionV2":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise IdentityMajorError("acquisition must use schema_version 2.0.0")
        created = create_acquisition_v2(
            run_manifest_id=value["run_manifest_id"],
            run_manifest_sha256=value["run_manifest_sha256"],
            collection_id=value["collection_id"],
            platform=value["platform"],
            datatake_id=value["datatake_id"],
            acquisition_timestamp_utc=value["acquisition_timestamp_utc"],
            scene_ids=value["scene_ids"],
            monitoring_extent_id=value["monitoring_extent_id"],
            composite_method_id=value["composite_method_id"],
            grid_id=value["grid_id"],
        )
        if value != created.to_dict():
            raise ValueError(
                "acquisition payload is non-canonical or does not match its v2 inputs"
            )
        return created


def create_acquisition_v2(
    *,
    run_manifest_id: str,
    run_manifest_sha256: str,
    collection_id: str,
    platform: str,
    datatake_id: str,
    acquisition_timestamp_utc: str | datetime,
    scene_ids: Iterable[str],
    monitoring_extent_id: str,
    composite_method_id: str,
    grid_id: str,
) -> AcquisitionV2:
    validate_run_manifest_binding(run_manifest_id, run_manifest_sha256)
    collection_id = require_nonempty(collection_id, label="collection_id")
    if platform not in {"S2A", "S2B"}:
        raise ValueError("platform must be S2A or S2B")
    datatake_id = require_nonempty(datatake_id, label="datatake_id")
    timestamp = normalize_utc_timestamp(
        acquisition_timestamp_utc, label="acquisition_timestamp_utc"
    )
    scenes = sorted_unique(scene_ids, label="scene_ids")
    monitoring_extent_id = require_nonempty(
        monitoring_extent_id, label="monitoring_extent_id"
    )
    composite_method_id = require_versioned_method(
        composite_method_id, label="composite_method_id"
    )
    grid_id = require_versioned_method(grid_id, label="grid_id")
    digest = identity_sha256(
        "acquisition-v2",
        collection_id,
        platform,
        datatake_id,
        timestamp,
        LINE_FEED.join(scenes),
        monitoring_extent_id,
        composite_method_id,
        grid_id,
    )
    return AcquisitionV2(
        acquisition_id="acq-v2-" + digest,
        identity_inputs_sha256=digest,
        run_manifest_id=run_manifest_id,
        run_manifest_sha256=run_manifest_sha256,
        collection_id=collection_id,
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=timestamp,
        observed_on=timestamp[:10],
        scene_ids=scenes,
        monitoring_extent_id=monitoring_extent_id,
        composite_method_id=composite_method_id,
        grid_id=grid_id,
    )


def acquisition_order_key(acquisition: AcquisitionV2) -> tuple[datetime, str]:
    """Return true chronological order, then the deterministic ID tie-break.

    Comparing RFC 3339 strings directly is incorrect when one timestamp has a
    fractional second and another does not (``.`` sorts before ``Z``).  Parse
    the already-normalized UTC instant so timestamp order remains scientific
    rather than lexical.
    """

    instant = datetime.fromisoformat(
        acquisition.acquisition_timestamp_utc[:-1] + "+00:00"
    )
    return instant, acquisition.acquisition_id


def observation_id_v2(
    acquisition_id: str,
    geometry_sha256: str,
    algorithm_version: str,
    baseline_version: str,
) -> str:
    require_v2_id(acquisition_id, prefix="acq-v2-", label="acquisition_id")
    require_sha256(geometry_sha256, label="geometry_sha256")
    algorithm_version = require_semver(
        algorithm_version, label="algorithm_version"
    )
    baseline_version = require_semver(baseline_version, label="baseline_version")
    digest = identity_sha256(
        "observation-v2",
        acquisition_id,
        geometry_sha256,
        algorithm_version,
        baseline_version,
    )
    return "obs-v2-" + digest


@dataclass(frozen=True)
class ObservationV2:
    value: dict[str, Any]

    @property
    def observation_id(self) -> str:
        return self.value["observation_id"]

    @property
    def acquisition_id(self) -> str:
        return self.value["acquisition_id"]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.value)

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], *, acquisition: AcquisitionV2
    ) -> "ObservationV2":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise IdentityMajorError("observation must use schema_version 2.0.0")
        if value.get("acquisition_id") != acquisition.acquisition_id:
            raise ValueError("observation does not reference the supplied acquisition")
        created = create_observation_v2(
            acquisition=acquisition,
            geometry=value["geometry"],
            algorithm_version=value["algorithm_version"],
            baseline_version=value["baseline_version"],
            area_ha=value["area_ha"],
            created_at=value["created_at"],
        )
        required_equal = (
            "observation_id",
            "identity_inputs_sha256",
            "run_manifest_id",
            "run_manifest_sha256",
            "acquisition_timestamp_utc",
            "observed_on",
            "monitoring_extent_id",
            "geometry_crs",
            "canonical_geometry_sha256",
            "raw_detection_policy",
        )
        for field in required_equal:
            if value.get(field) != created.value[field]:
                raise ValueError(f"observation {field} does not match its v2 inputs")
        if value != created.to_dict():
            raise ValueError(
                "observation payload is non-canonical or does not match its v2 inputs"
            )
        return created


def create_observation_v2(
    *,
    acquisition: AcquisitionV2,
    geometry: BaseGeometry | dict[str, Any],
    algorithm_version: str,
    baseline_version: str,
    area_ha: float,
    created_at: str | datetime,
) -> ObservationV2:
    canonical_geometry, geometry_sha256 = canonical_geometry_sha256(geometry)
    if isinstance(area_ha, bool) or not isinstance(area_ha, (int, float)):
        raise TypeError("area_ha must be a number")
    if not math.isfinite(float(area_ha)) or not 0 < float(area_ha):
        raise ValueError("area_ha must be positive")
    algorithm_version = require_semver(
        algorithm_version, label="algorithm_version"
    )
    baseline_version = require_semver(baseline_version, label="baseline_version")
    observation_id_value = observation_id_v2(
        acquisition.acquisition_id,
        geometry_sha256,
        algorithm_version,
        baseline_version,
    )
    return ObservationV2(
        {
            "schema_version": SCHEMA_VERSION,
            "observation_id": observation_id_value,
            "identity_inputs_sha256": observation_id_value.removeprefix("obs-v2-"),
            "run_manifest_id": acquisition.run_manifest_id,
            "run_manifest_sha256": acquisition.run_manifest_sha256,
            "acquisition_id": acquisition.acquisition_id,
            "acquisition_timestamp_utc": acquisition.acquisition_timestamp_utc,
            "observed_on": acquisition.observed_on,
            "monitoring_extent_id": acquisition.monitoring_extent_id,
            "algorithm_version": algorithm_version,
            "baseline_version": baseline_version,
            "geometry_crs": "EPSG:4326",
            "geometry": canonical_geometry,
            "canonical_geometry_sha256": geometry_sha256,
            "area_ha": float(area_ha),
            "raw_detection_policy": {
                "retained": True,
                "immutable": True,
                "context_can_remove": False,
                "persistence_can_remove": False,
            },
            "created_at": normalize_utc_timestamp(created_at, label="created_at"),
        }
    )


def validate_observation_v2(value: dict[str, Any]) -> None:
    """Validate a standalone observation's canonical bytes and identity.

    The acquisition record is intentionally not embedded in observation-v2,
    so this boundary validates every locally available binding.  A caller that
    has the acquisition must additionally use :meth:`ObservationV2.from_dict`
    to reconcile the manifest, timestamp, date, and monitoring extent.
    """

    if not isinstance(value, dict):
        raise TypeError("observation-v2 must be a JSON object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise IdentityMajorError("observation must use schema_version 2.0.0")
    validate_run_manifest_binding(
        value.get("run_manifest_id"), value.get("run_manifest_sha256")
    )
    acquisition_id = require_v2_id(
        value.get("acquisition_id"),
        prefix="acq-v2-",
        label="acquisition_id",
    )
    timestamp = normalize_utc_timestamp(
        value.get("acquisition_timestamp_utc"),
        label="acquisition_timestamp_utc",
    )
    if value.get("acquisition_timestamp_utc") != timestamp:
        raise ValueError("observation acquisition timestamp is non-canonical")
    observed_on = require_utc_date(value.get("observed_on"))
    if observed_on != timestamp[:10]:
        raise ValueError("observation UTC date differs from acquisition timestamp")
    require_nonempty(value.get("monitoring_extent_id"), label="monitoring_extent_id")
    algorithm_version = require_semver(
        value.get("algorithm_version"), label="algorithm_version"
    )
    baseline_version = require_semver(
        value.get("baseline_version"), label="baseline_version"
    )
    canonical_geometry, geometry_digest = canonical_geometry_sha256(
        value.get("geometry")
    )
    if value.get("geometry") != canonical_geometry:
        raise ValueError("observation geometry is not in canonical form")
    if value.get("canonical_geometry_sha256") != geometry_digest:
        raise ValueError("observation geometry checksum mismatch")
    expected_id = observation_id_v2(
        acquisition_id,
        geometry_digest,
        algorithm_version,
        baseline_version,
    )
    if value.get("observation_id") != expected_id:
        raise ValueError("observation identity mismatch")
    if value.get("identity_inputs_sha256") != expected_id.removeprefix("obs-v2-"):
        raise ValueError("observation identity-input checksum mismatch")
    area_ha = value.get("area_ha")
    if isinstance(area_ha, bool) or not isinstance(area_ha, (int, float)):
        raise TypeError("area_ha must be a number")
    if not math.isfinite(float(area_ha)) or float(area_ha) <= 0:
        raise ValueError("area_ha must be positive")
    if value.get("raw_detection_policy") != {
        "retained": True,
        "immutable": True,
        "context_can_remove": False,
        "persistence_can_remove": False,
    }:
        raise ValueError("observation raw-detection policy differs from v2")
    created_at = normalize_utc_timestamp(value.get("created_at"), label="created_at")
    if value.get("created_at") != created_at:
        raise ValueError("observation created_at is non-canonical")


def origin_event_id_v2(first_observation_id: str) -> str:
    require_v2_id(
        first_observation_id, prefix="obs-v2-", label="first_observation_id"
    )
    return "evt-v2-" + identity_sha256(
        "event-v2", "origin", first_observation_id
    )


def child_event_id_v2(
    operation: str,
    parent_event_ids: Iterable[str],
    trigger_observation_ids: Iterable[str],
) -> str:
    if operation not in {"split", "merge"}:
        raise ValueError("child event operation must be split or merge")
    parents = sorted_v2_ids(
        parent_event_ids, prefix="evt-v2-", label="parent_event_ids"
    )
    triggers = sorted_v2_ids(
        trigger_observation_ids,
        prefix="obs-v2-",
        label="trigger_observation_ids",
    )
    if operation == "split" and len(parents) != 1:
        raise ValueError("split requires exactly one parent")
    if operation == "merge" and len(parents) < 2:
        raise ValueError("merge requires at least two parents")
    return "evt-v2-" + identity_sha256(
        "event-v2",
        operation,
        LINE_FEED.join(parents),
        LINE_FEED.join(triggers),
    )


def lineage_id_v2(
    *,
    relation: str,
    parent_event_ids: Iterable[str],
    child_event_ids: Iterable[str],
    acquisition_id: str,
    acquisition_timestamp_utc: str | datetime,
    trigger_observation_ids: Iterable[str],
    algorithm_version: str,
) -> str:
    if relation not in {"continuation", "split", "merge"}:
        raise ValueError("invalid lineage relation")
    parents = sorted_v2_ids(
        parent_event_ids, prefix="evt-v2-", label="parent_event_ids"
    )
    children = sorted_v2_ids(
        child_event_ids, prefix="evt-v2-", label="child_event_ids"
    )
    triggers = sorted_v2_ids(
        trigger_observation_ids,
        prefix="obs-v2-",
        label="trigger_observation_ids",
    )
    require_v2_id(acquisition_id, prefix="acq-v2-", label="acquisition_id")
    timestamp = normalize_utc_timestamp(
        acquisition_timestamp_utc, label="acquisition_timestamp_utc"
    )
    algorithm_version = require_semver(
        algorithm_version, label="algorithm_version"
    )
    if relation == "continuation" and (len(parents) != 1 or len(children) != 1):
        raise ValueError("continuation requires one parent and one child")
    if relation == "continuation" and parents != children:
        raise ValueError("continuation must preserve one event as a self-edge")
    if relation == "split" and (len(parents) != 1 or len(children) < 2):
        raise ValueError("split requires one parent and at least two children")
    if relation == "merge" and (len(parents) < 2 or len(children) != 1):
        raise ValueError("merge requires at least two parents and one child")
    if relation == "split":
        expected_children = sorted_v2_ids(
            (
                child_event_id_v2("split", parents, [trigger])
                for trigger in triggers
            ),
            prefix="evt-v2-",
            label="derived split child_event_ids",
        )
        if children != expected_children:
            raise ValueError(
                "split children must correspond one-to-one with trigger observations"
            )
    if relation == "merge":
        expected_child = child_event_id_v2("merge", parents, triggers)
        if children != (expected_child,):
            raise ValueError(
                "merge child must derive from the complete parent/trigger set"
            )
    digest = identity_sha256(
        "lineage-v2",
        relation,
        LINE_FEED.join(parents),
        LINE_FEED.join(children),
        acquisition_id,
        timestamp,
        LINE_FEED.join(triggers),
        algorithm_version,
    )
    return "lin-v2-" + digest


def contribution_key_v2(event_id: str, observed_on: str) -> str:
    require_v2_id(event_id, prefix="evt-v2-", label="event_id")
    observed_on = require_utc_date(observed_on)
    return "pc-v2-" + identity_sha256(
        "persistence-contribution-v2", event_id, observed_on
    )
