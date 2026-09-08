"""Atomic per-UTC-date persistence transitions for the v3 family (2A.6B.1).

All physical datatakes remain independent acquisitions and observations.  A
date is applied only after its manifest-bound ledger summary is terminal, and
only one contribution is materialized for each event/date pair.  A changed
input for an already finalized date is never patched in place: it requires a
new chronological generation from empty state.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date as Date, datetime
from functools import lru_cache
from typing import Any, Iterable

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as transform_geometry

from config.settings import TARGET_CRS
from src.detection.contracts_v3 import (
    ContractV3ValidationError,
    load_v3_document,
    serialize_v3_document,
    validate_v3_schema,
)
from src.detection.identity import (
    canonical_geometry_sha256,
    canonical_sha256,
    identity_sha256,
)
from src.detection.identity_v3 import (
    SCHEMA_VERSION,
    AcquisitionV3,
    IdentityMajorError,
    ObservationV3,
    acquisition_order_key,
    child_event_id_v3,
    contribution_key_v3,
    lineage_id_v3,
    normalize_utc_timestamp,
    observation_id_v3,
    origin_event_id_v3,
    require_semver,
    require_sha256,
    require_utc_date,
    require_v3_id,
    validate_run_manifest_binding,
)
from src.detection.ledger_v3 import ProcessingLedgerV3


DEFAULT_MIN_OVERLAP_FRAC = 0.05
DEFAULT_GRACE_DAYS = 180
DEFAULT_CONFIRMED_MIN = 15


class PersistenceV3Error(RuntimeError):
    """Base class for a rejected v3 state transition."""


class StateGenerationMismatchError(PersistenceV3Error):
    """The state and runtime generation bindings differ."""


class OutOfOrderRequiresRebuild(PersistenceV3Error):
    """An older unfinalized date cannot mutate the current generation."""


class LateArrivalRequiresRebuild(PersistenceV3Error):
    """A finalized date has a different manifest or input digest."""


class ObservationLedgerMismatch(PersistenceV3Error):
    """Raw observations do not reconcile with terminal ledger rows."""


class AmbiguousLineageError(PersistenceV3Error):
    """One acquisition creates an unsupported many-to-many component."""


@dataclass(frozen=True)
class PersistenceTransitionV3:
    state: dict[str, Any]
    outcome: str
    state_changed: bool
    observation_assignments: dict[str, dict[str, Any]]


def persistence_tier_v3(
    distinct_dates: int, *, confirmed_min: int = DEFAULT_CONFIRMED_MIN
) -> str:
    if confirmed_min != DEFAULT_CONFIRMED_MIN:
        raise ValueError("persistence-state-v3 fixes confirmation at 15 dates")
    if distinct_dates >= confirmed_min:
        return "confirmed"
    if distinct_dates >= 2:
        return "candidate"
    return "first_observation"


def _require_generation_id(value: str) -> str:
    return require_v3_id(value, prefix="gen-v3-", label="generation_id")


def _sorted(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda item: item.encode("utf-8"))


def _days_between(current: str, previous: str) -> int:
    return (Date.fromisoformat(current) - Date.fromisoformat(previous)).days


def _utc_instant(value: str) -> datetime:
    """Parse an already-normalized UTC contract timestamp."""

    return datetime.fromisoformat(value[:-1] + "+00:00")


@lru_cache(maxsize=1)
def _metric_transformer() -> Transformer:
    return Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)


def _metric_geometry(geometry: dict[str, Any]):
    transformer = _metric_transformer()
    return transform_geometry(transformer.transform, shape(geometry))


def _overlap_fraction(
    observation_geometry: dict[str, Any], event_geometry: dict[str, Any]
) -> float:
    observation = _metric_geometry(observation_geometry)
    if observation.is_empty or observation.area <= 0:
        return 0.0
    event = _metric_geometry(event_geometry)
    return float(observation.intersection(event).area / observation.area)


def _event_identity_basis_digest(event_id: str) -> str:
    require_v3_id(event_id, prefix="evt-v3-", label="event_id")
    return event_id.removeprefix("evt-v3-")


def _lineage_record(
    *,
    relation: str,
    parent_event_ids: list[str],
    child_event_ids: list[str],
    acquisition: AcquisitionV3,
    trigger_observation_ids: list[str],
    algorithm_version: str,
    created_at: str,
) -> dict[str, Any]:
    lineage_id = lineage_id_v3(
        relation=relation,
        parent_event_ids=parent_event_ids,
        child_event_ids=child_event_ids,
        acquisition_id=acquisition.acquisition_id,
        acquisition_timestamp_utc=acquisition.acquisition_timestamp_utc,
        trigger_observation_ids=trigger_observation_ids,
        algorithm_version=algorithm_version,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "lineage_id": lineage_id,
        "identity_inputs_sha256": lineage_id.removeprefix("lin-v3-"),
        "run_manifest_id": acquisition.run_manifest_id,
        "run_manifest_sha256": acquisition.run_manifest_sha256,
        "relation": relation,
        "parent_event_ids": _sorted(parent_event_ids),
        "child_event_ids": _sorted(child_event_ids),
        "trigger_observation_ids": _sorted(trigger_observation_ids),
        "effective_acquisition_id": acquisition.acquisition_id,
        "effective_timestamp_utc": acquisition.acquisition_timestamp_utc,
        "observed_on": acquisition.observed_on,
        "algorithm_version": algorithm_version,
        "raw_observations_preserved": True,
        "created_at": created_at,
    }


def _new_event(
    *,
    event_id: str,
    kind: str,
    first_observation_id: str | None,
    parent_event_ids: list[str],
    trigger_observation_ids: list[str],
    observation: dict[str, Any],
    incoming_lineage_ids: list[str],
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "identity_inputs_sha256": _event_identity_basis_digest(event_id),
        "run_manifest_id": observation["run_manifest_id"],
        "run_manifest_sha256": observation["run_manifest_sha256"],
        "identity_basis": {
            "kind": kind,
            "first_observation_id": first_observation_id,
            "parent_event_ids": _sorted(parent_event_ids),
            "trigger_observation_ids": _sorted(trigger_observation_ids),
        },
        "monitoring_extent_id": observation["monitoring_extent_id"],
        "status": "active",
        "first_observed_on": observation["observed_on"],
        "last_observed_on": observation["observed_on"],
        "observation_dates": [],
        "n_distinct_observation_dates": 0,
        "observation_ids": [observation["observation_id"]],
        "acquisition_ids": [observation["acquisition_id"]],
        "contribution_keys": [],
        "incoming_lineage_ids": _sorted(incoming_lineage_ids),
        "outgoing_lineage_ids": [],
        "representative_geometry_crs": "EPSG:4326",
        "representative_geometry": deepcopy(observation["geometry"]),
        "representative_geometry_sha256": observation[
            "canonical_geometry_sha256"
        ],
        "raw_observations_preserved": True,
        "persistence_tier": "first_observation",
        "created_at": created_at,
        "updated_at": created_at,
    }


def _state_identity_inputs(state: dict[str, Any]) -> tuple[str, ...]:
    return (
        "persistence-state-v3",
        state["generation_id"],
        state["run_manifest_id"],
        state["run_manifest_sha256"],
        state["monitoring_extent_id"],
        state["algorithm_version"],
        state["baseline_version"],
        canonical_sha256(state["transition_policy"]),
        canonical_sha256(state["finalized_dates"]),
        canonical_sha256(state["events"]),
        canonical_sha256(state["lineage"]),
        canonical_sha256(state["contributions"]),
        canonical_sha256(state["watermark"]),
    )


def _state_digest(*components: str) -> str:
    return identity_sha256(*components)


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(state)
    sealed["events"] = sorted(
        sealed["events"], key=lambda item: item["event_id"].encode("utf-8")
    )
    sealed["lineage"] = sorted(
        sealed["lineage"], key=lambda item: item["lineage_id"].encode("utf-8")
    )
    sealed["contributions"] = sorted(
        sealed["contributions"],
        key=lambda item: item["contribution_key"].encode("utf-8"),
    )
    sealed["finalized_dates"] = sorted(
        sealed["finalized_dates"], key=lambda item: item["observed_on"]
    )
    digest = _state_digest(*_state_identity_inputs(sealed))
    sealed["state_id"] = "state-v3-" + digest
    sealed["identity_inputs_sha256"] = digest
    integrity_without_document = {
        "finalized_dates_sha256": canonical_sha256(sealed["finalized_dates"]),
        "events_sha256": canonical_sha256(sealed["events"]),
        "lineage_sha256": canonical_sha256(sealed["lineage"]),
        "contributions_sha256": canonical_sha256(sealed["contributions"]),
        "watermark_sha256": canonical_sha256(sealed["watermark"]),
        "schema_validated": True,
        "distinct_dates_reconciled": True,
        "unique_contribution_per_event_date": True,
        "raw_observations_preserved": True,
    }
    sealed["integrity"] = integrity_without_document
    document_without_checksum = deepcopy(sealed)
    sealed["integrity"] = {
        **integrity_without_document,
        "document_sha256": canonical_sha256(document_without_checksum),
    }
    return sealed


def empty_persistence_state_v3(
    *,
    generation_id: str,
    ledger: ProcessingLedgerV3,
    baseline_version: str,
    generated_at: str,
) -> dict[str, Any]:
    _require_generation_id(generation_id)
    generated_at = normalize_utc_timestamp(generated_at, label="generated_at")
    body = {
        "schema_version": SCHEMA_VERSION,
        "state_id": "",
        "identity_inputs_sha256": "",
        "generation_id": generation_id,
        "run_manifest_id": ledger.run_manifest_id,
        "run_manifest_sha256": ledger.run_manifest_sha256,
        "monitoring_extent_id": ledger.monitoring_extent_id,
        "algorithm_version": ledger.algorithm_version,
        "baseline_version": require_semver(
            baseline_version, label="baseline_version"
        ),
        "generated_at": generated_at,
        "transition_policy": {
            "contribution_uniqueness": "event_id+observed_on",
            "duplicate_contribution": "no_op",
            "chronological_order": "acquisition_timestamp_utc+acquisition_id",
            "late_same_day_acquisition": (
                "requires_new_chronological_generation"
            ),
            "legacy_serialization": "v1_v2_forbidden_audit_only",
            "confirmed_min_distinct_dates": DEFAULT_CONFIRMED_MIN,
            "event_reconnect_grace_days": DEFAULT_GRACE_DAYS,
            "minimum_overlap_fraction": DEFAULT_MIN_OVERLAP_FRAC,
        },
        "last_transition": {
            "outcome": "initialized",
            "observed_on": None,
            "date_input_digest": None,
            "new_contribution_count": 0,
            "duplicate_contribution_count": 0,
            "state_changed": False,
        },
        "finalized_dates": [],
        "events": [],
        "lineage": [],
        "contributions": [],
        "watermark": None,
        "integrity": {},
    }
    return _seal_state(body)


def _validate_state_binding(
    state: dict[str, Any], ledger: ProcessingLedgerV3, observed_on: str
) -> None:
    validate_persistence_state_v3(state)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise IdentityMajorError("persistence state must use schema_version 3.0.0")
    require_v3_id(state.get("state_id"), prefix="state-v3-", label="state_id")
    _require_generation_id(state.get("generation_id"))
    if state.get("monitoring_extent_id") != ledger.monitoring_extent_id:
        raise StateGenerationMismatchError("monitoring extent differs")
    if state.get("algorithm_version") != ledger.algorithm_version:
        raise StateGenerationMismatchError("algorithm version differs")


def _normalize_observations(
    observations: Iterable[ObservationV3 | dict[str, Any]],
    *,
    ledger: ProcessingLedgerV3,
    observed_on: str,
    baseline_version: str,
) -> tuple[list[dict[str, Any]], dict[str, AcquisitionV3]]:
    expected = {
        item.acquisition_id: item
        for item in ledger.expected_for_date(observed_on)
    }
    normalized: list[dict[str, Any]] = []
    for item in observations:
        raw = item.to_dict() if isinstance(item, ObservationV3) else deepcopy(item)
        acquisition_id = raw.get("acquisition_id")
        acquisition = expected.get(acquisition_id)
        if acquisition is None:
            raise ObservationLedgerMismatch(
                "observation acquisition is not expected for the UTC date"
            )
        validated = ObservationV3.from_dict(raw, acquisition=acquisition).to_dict()
        if validated["observed_on"] != observed_on:
            raise ObservationLedgerMismatch("observation has the wrong UTC date")
        if validated["algorithm_version"] != ledger.algorithm_version:
            raise ObservationLedgerMismatch("observation algorithm version differs")
        if validated["baseline_version"] != baseline_version:
            raise ObservationLedgerMismatch("observation baseline version differs")
        normalized.append(validated)
    ids = [item["observation_id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ObservationLedgerMismatch("observation list contains duplicate IDs")
    normalized.sort(key=lambda item: item["observation_id"].encode("utf-8"))
    return normalized, expected


def _reconcile_observations_with_ledger(
    *,
    observations: list[dict[str, Any]],
    expected: dict[str, AcquisitionV3],
    ledger: ProcessingLedgerV3,
    observed_on: str,
) -> None:
    by_acquisition: dict[str, list[str]] = defaultdict(list)
    for item in observations:
        by_acquisition[item["acquisition_id"]].append(item["observation_id"])
    rows = {
        row["acquisition_id"]: row
        for row in ledger.terminal_rows
        if row["observed_on"] == observed_on
    }
    if set(rows) != set(expected):
        raise ObservationLedgerMismatch(
            "terminal ledger rows do not equal the expected acquisition set"
        )
    for acquisition_id, row in rows.items():
        actual = _sorted(by_acquisition.get(acquisition_id, []))
        if actual != row["output"]["observation_ids"]:
            raise ObservationLedgerMismatch(
                f"observations do not reconcile with terminal row {acquisition_id}"
            )
    summary = ledger.daily_summary(observed_on)
    if summary["observation_ids"] != _sorted(
        item["observation_id"] for item in observations
    ):
        raise ObservationLedgerMismatch(
            "observations do not reconcile with the daily summary"
        )


def _eligible_event(
    event: dict[str, Any], *, observed_on: str, grace_days: int, confirmed_min: int
) -> bool:
    if event["status"] != "active":
        return False
    if int(event["n_distinct_observation_dates"]) >= confirmed_min:
        return True
    gap = _days_between(observed_on, event["last_observed_on"])
    return 0 <= gap <= grace_days


def _append_unique(record: dict[str, Any], field: str, values: Iterable[str]) -> None:
    record[field] = _sorted([*record[field], *values])


def _process_acquisition(
    *,
    events: dict[str, dict[str, Any]],
    lineage: dict[str, dict[str, Any]],
    acquisition: AcquisitionV3,
    observations: list[dict[str, Any]],
    algorithm_version: str,
    transitioned_at: str,
    event_sources: dict[str, dict[str, set[str]]],
    assignments: dict[str, str],
    grace_days: int,
    confirmed_min: int,
    min_overlap_frac: float,
) -> None:
    observations = sorted(
        observations, key=lambda item: item["observation_id"].encode("utf-8")
    )
    active_ids = sorted(
        (
            event_id
            for event_id, event in events.items()
            if _eligible_event(
                event,
                observed_on=acquisition.observed_on,
                grace_days=grace_days,
                confirmed_min=confirmed_min,
            )
        ),
        key=lambda item: item.encode("utf-8"),
    )
    parents_by_observation: dict[int, set[str]] = {
        index: set() for index in range(len(observations))
    }
    observations_by_parent: dict[str, set[int]] = defaultdict(set)
    for index, observation in enumerate(observations):
        for event_id in active_ids:
            fraction = _overlap_fraction(
                observation["geometry"], events[event_id]["representative_geometry"]
            )
            if fraction >= min_overlap_frac:
                parents_by_observation[index].add(event_id)
                observations_by_parent[event_id].add(index)

    for index, parents in parents_by_observation.items():
        if len(parents) > 1 and any(
            len(observations_by_parent[parent]) > 1 for parent in parents
        ):
            raise AmbiguousLineageError(
                "many-to-many lineage requires reviewed correction"
            )
        if len(parents) == 1:
            parent = next(iter(parents))
            siblings = observations_by_parent[parent]
            if len(siblings) > 1 and any(
                len(parents_by_observation[sibling]) > 1 for sibling in siblings
            ):
                raise AmbiguousLineageError(
                    "many-to-many lineage requires reviewed correction"
                )

    processed: set[int] = set()
    for parent_id in sorted(
        observations_by_parent, key=lambda item: item.encode("utf-8")
    ):
        child_indices = sorted(observations_by_parent[parent_id])
        if len(child_indices) < 2:
            continue
        trigger_ids = [observations[index]["observation_id"] for index in child_indices]
        child_ids = [
            child_event_id_v3("split", [parent_id], [trigger_id])
            for trigger_id in trigger_ids
        ]
        edge = _lineage_record(
            relation="split",
            parent_event_ids=[parent_id],
            child_event_ids=child_ids,
            acquisition=acquisition,
            trigger_observation_ids=trigger_ids,
            algorithm_version=algorithm_version,
            created_at=transitioned_at,
        )
        lineage[edge["lineage_id"]] = edge
        parent = events[parent_id]
        parent["status"] = "superseded"
        _append_unique(parent, "outgoing_lineage_ids", [edge["lineage_id"]])
        parent["updated_at"] = transitioned_at
        for index, child_id in zip(child_indices, child_ids):
            observation = observations[index]
            events[child_id] = _new_event(
                event_id=child_id,
                kind="split",
                first_observation_id=None,
                parent_event_ids=[parent_id],
                trigger_observation_ids=[observation["observation_id"]],
                observation=observation,
                incoming_lineage_ids=[edge["lineage_id"]],
                created_at=transitioned_at,
            )
            event_sources[child_id]["acquisition_ids"].add(acquisition.acquisition_id)
            event_sources[child_id]["observation_ids"].add(
                observation["observation_id"]
            )
            assignments[observation["observation_id"]] = child_id
            processed.add(index)

    for index, observation in enumerate(observations):
        if index in processed:
            continue
        parents = sorted(
            parents_by_observation[index], key=lambda item: item.encode("utf-8")
        )
        if not parents:
            event_id = origin_event_id_v3(observation["observation_id"])
            events[event_id] = _new_event(
                event_id=event_id,
                kind="origin",
                first_observation_id=observation["observation_id"],
                parent_event_ids=[],
                trigger_observation_ids=[observation["observation_id"]],
                observation=observation,
                incoming_lineage_ids=[],
                created_at=transitioned_at,
            )
        elif len(parents) > 1:
            event_id = child_event_id_v3(
                "merge", parents, [observation["observation_id"]]
            )
            edge = _lineage_record(
                relation="merge",
                parent_event_ids=parents,
                child_event_ids=[event_id],
                acquisition=acquisition,
                trigger_observation_ids=[observation["observation_id"]],
                algorithm_version=algorithm_version,
                created_at=transitioned_at,
            )
            lineage[edge["lineage_id"]] = edge
            for parent_id in parents:
                parent = events[parent_id]
                parent["status"] = "superseded"
                _append_unique(
                    parent, "outgoing_lineage_ids", [edge["lineage_id"]]
                )
                parent["updated_at"] = transitioned_at
            events[event_id] = _new_event(
                event_id=event_id,
                kind="merge",
                first_observation_id=None,
                parent_event_ids=parents,
                trigger_observation_ids=[observation["observation_id"]],
                observation=observation,
                incoming_lineage_ids=[edge["lineage_id"]],
                created_at=transitioned_at,
            )
        else:
            event_id = parents[0]
            edge = _lineage_record(
                relation="continuation",
                parent_event_ids=[event_id],
                child_event_ids=[event_id],
                acquisition=acquisition,
                trigger_observation_ids=[observation["observation_id"]],
                algorithm_version=algorithm_version,
                created_at=transitioned_at,
            )
            lineage[edge["lineage_id"]] = edge
            event = events[event_id]
            _append_unique(event, "observation_ids", [observation["observation_id"]])
            _append_unique(event, "acquisition_ids", [acquisition.acquisition_id])
            _append_unique(event, "incoming_lineage_ids", [edge["lineage_id"]])
            _append_unique(event, "outgoing_lineage_ids", [edge["lineage_id"]])
            event["last_observed_on"] = acquisition.observed_on
            event["representative_geometry"] = deepcopy(observation["geometry"])
            event["representative_geometry_sha256"] = observation[
                "canonical_geometry_sha256"
            ]
            event["updated_at"] = transitioned_at

        event_sources[event_id]["acquisition_ids"].add(acquisition.acquisition_id)
        event_sources[event_id]["observation_ids"].add(observation["observation_id"])
        assignments[observation["observation_id"]] = event_id


def _contribution_record(
    *,
    event_id: str,
    observed_on: str,
    source_acquisition_ids: Iterable[str],
    source_observation_ids: Iterable[str],
    ledger: ProcessingLedgerV3,
    daily_summary_sha256: str,
    finalized_at: str,
) -> dict[str, Any]:
    key = contribution_key_v3(event_id, observed_on)
    return {
        "schema_version": SCHEMA_VERSION,
        "contribution_key": key,
        "identity_inputs_sha256": key.removeprefix("pc-v3-"),
        "run_manifest_id": ledger.run_manifest_id,
        "run_manifest_sha256": ledger.run_manifest_sha256,
        "event_id": event_id,
        "observed_on": observed_on,
        "source_acquisition_ids": _sorted(source_acquisition_ids),
        "source_observation_ids": _sorted(source_observation_ids),
        "daily_summary_sha256": daily_summary_sha256,
        "finalization_status": "finalized",
        "finalization_condition": (
            "all_manifest_expected_acquisitions_for_utc_date_terminal"
        ),
        "duplicate_policy": "no_op",
        "finalized_at": finalized_at,
    }


def apply_terminal_date_v3(
    *,
    state: dict[str, Any],
    ledger: ProcessingLedgerV3,
    observed_on: str,
    observations: Iterable[ObservationV3 | dict[str, Any]],
    transitioned_at: str,
    grace_days: int = DEFAULT_GRACE_DAYS,
    confirmed_min: int = DEFAULT_CONFIRMED_MIN,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
) -> PersistenceTransitionV3:
    """Apply one terminal manifest date atomically and chronologically."""

    observed_on = require_utc_date(observed_on)
    transitioned_at = normalize_utc_timestamp(
        transitioned_at, label="transitioned_at"
    )
    if (
        grace_days != DEFAULT_GRACE_DAYS
        or confirmed_min != DEFAULT_CONFIRMED_MIN
        or min_overlap_frac != DEFAULT_MIN_OVERLAP_FRAC
    ):
        raise ValueError("invalid persistence thresholds")
    _validate_state_binding(state, ledger, observed_on)
    summary = ledger.daily_summary(observed_on)
    baseline_version = state["baseline_version"]
    normalized, expected = _normalize_observations(
        observations,
        ledger=ledger,
        observed_on=observed_on,
        baseline_version=baseline_version,
    )
    _reconcile_observations_with_ledger(
        observations=normalized,
        expected=expected,
        ledger=ledger,
        observed_on=observed_on,
    )
    input_digest = ledger.date_input_digest(observed_on, normalized)
    finalized_by_date = {
        item["observed_on"]: item for item in state["finalized_dates"]
    }
    existing = finalized_by_date.get(observed_on)
    if existing is not None:
        if existing["date_input_digest"] != input_digest:
            raise LateArrivalRequiresRebuild(
                "finalized date inputs changed; rebuild a new generation from empty"
            )
        assignments: dict[str, dict[str, Any]] = {}
        for contribution in state["contributions"]:
            if contribution["observed_on"] != observed_on:
                continue
            historical_count = sum(
                1
                for item in state["contributions"]
                if item["event_id"] == contribution["event_id"]
                and item["observed_on"] <= observed_on
            )
            for observation_id in contribution["source_observation_ids"]:
                assignments[observation_id] = {
                    "event_id": contribution["event_id"],
                    "contribution_key": contribution["contribution_key"],
                    "persistence_count": historical_count,
                    "persistence_tier": persistence_tier_v3(historical_count),
                }
        return PersistenceTransitionV3(
            state=state,
            outcome="no_op_replay",
            state_changed=False,
            observation_assignments=assignments,
        )

    watermark = state.get("watermark")
    if watermark is not None and observed_on <= watermark["observed_on"]:
        raise OutOfOrderRequiresRebuild(
            "an older UTC date cannot mutate this generation"
        )
    terminal_rows = [
        row for row in ledger.terminal_rows if row["observed_on"] == observed_on
    ]
    latest_terminal_at = max(
        (row["terminal_at"] for row in terminal_rows), key=_utc_instant
    )
    if _utc_instant(transitioned_at) < _utc_instant(latest_terminal_at):
        raise PersistenceV3Error(
            "transitioned_at cannot precede the last expected terminal row "
            f"({latest_terminal_at})"
        )

    working = deepcopy(state)
    working["run_manifest_id"] = ledger.run_manifest_id
    working["run_manifest_sha256"] = ledger.run_manifest_sha256
    for event in working["events"]:
        # Events are the mutable current snapshot.  Historical per-date
        # provenance remains on contributions and lineage records.
        event["run_manifest_id"] = ledger.run_manifest_id
        event["run_manifest_sha256"] = ledger.run_manifest_sha256
    events = {item["event_id"]: item for item in working["events"]}
    lineage = {item["lineage_id"]: item for item in working["lineage"]}
    contributions = {
        item["contribution_key"]: item for item in working["contributions"]
    }
    observations_by_acquisition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in normalized:
        observations_by_acquisition[observation["acquisition_id"]].append(observation)
    event_sources: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"acquisition_ids": set(), "observation_ids": set()}
    )
    assignments_by_observation: dict[str, str] = {}
    for acquisition in ledger.expected_for_date(observed_on):
        _process_acquisition(
            events=events,
            lineage=lineage,
            acquisition=acquisition,
            observations=observations_by_acquisition.get(
                acquisition.acquisition_id, []
            ),
            algorithm_version=ledger.algorithm_version,
            transitioned_at=transitioned_at,
            event_sources=event_sources,
            assignments=assignments_by_observation,
            grace_days=grace_days,
            confirmed_min=confirmed_min,
            min_overlap_frac=min_overlap_frac,
        )

    date_contribution_keys: list[str] = []
    assignments: dict[str, dict[str, Any]] = {}
    for event_id in sorted(event_sources, key=lambda item: item.encode("utf-8")):
        sources = event_sources[event_id]
        contribution = _contribution_record(
            event_id=event_id,
            observed_on=observed_on,
            source_acquisition_ids=sources["acquisition_ids"],
            source_observation_ids=sources["observation_ids"],
            ledger=ledger,
            daily_summary_sha256=summary["daily_summary_sha256"],
            finalized_at=transitioned_at,
        )
        key = contribution["contribution_key"]
        if key in contributions:
            raise PersistenceV3Error(
                "duplicate contribution exists before date finalization"
            )
        contributions[key] = contribution
        date_contribution_keys.append(key)
        event = events[event_id]
        _append_unique(event, "observation_dates", [observed_on])
        _append_unique(event, "contribution_keys", [key])
        event["n_distinct_observation_dates"] = len(event["observation_dates"])
        event["persistence_tier"] = persistence_tier_v3(
            event["n_distinct_observation_dates"], confirmed_min=confirmed_min
        )
        event["last_observed_on"] = max(
            event["last_observed_on"], observed_on
        )
        event["updated_at"] = transitioned_at
        for observation_id in sources["observation_ids"]:
            assignments[observation_id] = {
                "event_id": event_id,
                "contribution_key": key,
                "persistence_count": event["n_distinct_observation_dates"],
                "persistence_tier": event["persistence_tier"],
            }

    latest = max(
        ledger.expected_for_date(observed_on),
        key=acquisition_order_key,
    )
    working["events"] = list(events.values())
    working["lineage"] = list(lineage.values())
    working["contributions"] = list(contributions.values())
    working["finalized_dates"] = [
        *working["finalized_dates"],
        {
            "observed_on": observed_on,
            "run_manifest_id": ledger.run_manifest_id,
            "run_manifest_sha256": ledger.run_manifest_sha256,
            "date_input_digest": input_digest,
            "daily_summary_sha256": summary["daily_summary_sha256"],
            "contribution_keys": _sorted(date_contribution_keys),
        },
    ]
    working["watermark"] = {
        "observed_on": observed_on,
        "acquisition_timestamp_utc": latest.acquisition_timestamp_utc,
        "acquisition_id": latest.acquisition_id,
    }
    working["generated_at"] = transitioned_at
    working["last_transition"] = {
        "outcome": "applied",
        "observed_on": observed_on,
        "date_input_digest": input_digest,
        "new_contribution_count": len(date_contribution_keys),
        "duplicate_contribution_count": 0,
        "state_changed": True,
    }
    sealed = _seal_state(working)
    return PersistenceTransitionV3(
        state=sealed,
        outcome="applied",
        state_changed=True,
        observation_assignments=assignments,
    )


def rebuild_persistence_state_v3(
    *,
    generation_id: str,
    ledger: ProcessingLedgerV3,
    observations: Iterable[ObservationV3 | dict[str, Any]],
    baseline_version: str,
    generated_at: str,
    grace_days: int = DEFAULT_GRACE_DAYS,
    confirmed_min: int = DEFAULT_CONFIRMED_MIN,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
) -> dict[str, Any]:
    """Build a fresh generation from empty state in canonical date order."""

    records = [
        item.to_dict() if isinstance(item, ObservationV3) else deepcopy(item)
        for item in observations
    ]
    dates = sorted({item.observed_on for item in ledger.acquisitions})
    expected_dates = set(dates)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        if item.get("observed_on") not in expected_dates:
            raise ObservationLedgerMismatch(
                "rebuild observation date is absent from the bound ledger"
            )
        by_date[item["observed_on"]].append(item)
    state = empty_persistence_state_v3(
        generation_id=generation_id,
        ledger=ledger,
        baseline_version=baseline_version,
        generated_at=generated_at,
    )
    for observed_on in dates:
        if not ledger.is_date_terminal(observed_on):
            raise PersistenceV3Error(
                "rebuild requires every expected acquisition to be terminal"
            )
        state = apply_terminal_date_v3(
            state=state,
            ledger=ledger,
            observed_on=observed_on,
            observations=by_date.get(observed_on, []),
            transitioned_at=generated_at,
            grace_days=grace_days,
            confirmed_min=confirmed_min,
            min_overlap_frac=min_overlap_frac,
        ).state
    return state


def persistence_state_bytes_v3(state: dict[str, Any]) -> bytes:
    validate_persistence_state_v3(state)
    return serialize_v3_document("persistence-state-v3", state)


def _require_canonical_values(values: list[str], *, label: str) -> None:
    if values != sorted(set(values), key=lambda item: item.encode("utf-8")):
        raise ContractV3ValidationError(f"{label} must be unique and UTF-8 sorted")


def _validate_event_identity_v3(event: dict[str, Any]) -> None:
    validate_run_manifest_binding(
        event["run_manifest_id"], event["run_manifest_sha256"]
    )
    event_id = require_v3_id(event["event_id"], prefix="evt-v3-", label="event_id")
    basis = event["identity_basis"]
    kind = basis["kind"]
    parents = basis["parent_event_ids"]
    triggers = basis["trigger_observation_ids"]
    _require_canonical_values(parents, label="event parent IDs")
    _require_canonical_values(triggers, label="event trigger observation IDs")
    if kind == "origin":
        first = basis["first_observation_id"]
        if parents or triggers != [first]:
            raise ContractV3ValidationError(
                "origin event identity basis is inconsistent"
            )
        expected_id = origin_event_id_v3(first)
    elif kind in {"split", "merge"}:
        if basis["first_observation_id"] is not None:
            raise ContractV3ValidationError(
                "derived event cannot have a first observation"
            )
        expected_id = child_event_id_v3(kind, parents, triggers)
    else:
        raise ContractV3ValidationError("unknown event identity kind")
    if event_id != expected_id:
        raise ContractV3ValidationError("event identity mismatch")
    if event["identity_inputs_sha256"] != event_id.removeprefix("evt-v3-"):
        raise ContractV3ValidationError("event identity-input checksum mismatch")

    for field, prefix in (
        ("observation_ids", "obs-v3-"),
        ("acquisition_ids", "acq-v3-"),
        ("contribution_keys", "pc-v3-"),
        ("incoming_lineage_ids", "lin-v3-"),
        ("outgoing_lineage_ids", "lin-v3-"),
    ):
        values = event[field]
        _require_canonical_values(values, label=f"event {field}")
        for value in values:
            require_v3_id(value, prefix=prefix, label=f"event {field} item")
    dates = event["observation_dates"]
    _require_canonical_values(dates, label="event observation dates")
    for observed_on in dates:
        require_utc_date(observed_on)
    if event["n_distinct_observation_dates"] != len(dates):
        raise ContractV3ValidationError("event distinct-date count mismatch")
    if dates and (
        event["first_observed_on"] != dates[0]
        or event["last_observed_on"] != dates[-1]
    ):
        raise ContractV3ValidationError("event first/last dates are not reconciled")
    canonical_geometry, geometry_digest = canonical_geometry_sha256(
        event["representative_geometry"]
    )
    if event["representative_geometry"] != canonical_geometry:
        raise ContractV3ValidationError("event geometry is not canonical")
    if event["representative_geometry_sha256"] != geometry_digest:
        raise ContractV3ValidationError("event geometry checksum mismatch")
    if event["raw_observations_preserved"] is not True:
        raise ContractV3ValidationError("event does not preserve raw observations")
    for field in ("created_at", "updated_at"):
        if event[field] != normalize_utc_timestamp(event[field], label=field):
            raise ContractV3ValidationError(f"event {field} is non-canonical")


def validate_event_v3(event: dict[str, Any]) -> None:
    validate_v3_schema("event-v3", event)
    _validate_event_identity_v3(event)
    if "persistence_tier" in event:
        expected_tier = persistence_tier_v3(
            event["n_distinct_observation_dates"]
        )
        if event["persistence_tier"] != expected_tier:
            raise ContractV3ValidationError("event persistence tier mismatch")


def validate_lineage_v3(edge: dict[str, Any]) -> None:
    validate_v3_schema("lineage-v3", edge)
    validate_run_manifest_binding(edge["run_manifest_id"], edge["run_manifest_sha256"])
    for field, prefix in (
        ("parent_event_ids", "evt-v3-"),
        ("child_event_ids", "evt-v3-"),
        ("trigger_observation_ids", "obs-v3-"),
    ):
        _require_canonical_values(edge[field], label=f"lineage {field}")
        for value in edge[field]:
            require_v3_id(value, prefix=prefix, label=f"lineage {field} item")
    expected_id = lineage_id_v3(
        relation=edge["relation"],
        parent_event_ids=edge["parent_event_ids"],
        child_event_ids=edge["child_event_ids"],
        acquisition_id=edge["effective_acquisition_id"],
        acquisition_timestamp_utc=edge["effective_timestamp_utc"],
        trigger_observation_ids=edge["trigger_observation_ids"],
        algorithm_version=edge["algorithm_version"],
    )
    if edge["lineage_id"] != expected_id:
        raise ContractV3ValidationError("lineage identity mismatch")
    if edge["identity_inputs_sha256"] != expected_id.removeprefix("lin-v3-"):
        raise ContractV3ValidationError("lineage identity-input checksum mismatch")
    if edge["effective_timestamp_utc"] != normalize_utc_timestamp(
        edge["effective_timestamp_utc"], label="effective_timestamp_utc"
    ):
        raise ContractV3ValidationError(
            "lineage effective timestamp is non-canonical"
        )
    if edge["observed_on"] != edge["effective_timestamp_utc"][:10]:
        raise ContractV3ValidationError("lineage UTC date differs from its timestamp")
    if edge["created_at"] != normalize_utc_timestamp(
        edge["created_at"], label="created_at"
    ):
        raise ContractV3ValidationError("lineage created_at is non-canonical")


def validate_persistence_contribution_v3(contribution: dict[str, Any]) -> None:
    validate_v3_schema("persistence-contribution-v3", contribution)
    validate_run_manifest_binding(
        contribution["run_manifest_id"], contribution["run_manifest_sha256"]
    )
    for field, prefix in (
        ("source_acquisition_ids", "acq-v3-"),
        ("source_observation_ids", "obs-v3-"),
    ):
        _require_canonical_values(contribution[field], label=f"contribution {field}")
        for value in contribution[field]:
            require_v3_id(value, prefix=prefix, label=f"contribution {field} item")
    expected_key = contribution_key_v3(
        contribution["event_id"], contribution["observed_on"]
    )
    if contribution["contribution_key"] != expected_key:
        raise ContractV3ValidationError("contribution identity mismatch")
    if contribution["identity_inputs_sha256"] != expected_key.removeprefix("pc-v3-"):
        raise ContractV3ValidationError(
            "contribution identity-input checksum mismatch"
        )
    require_sha256(
        contribution["daily_summary_sha256"], label="daily_summary_sha256"
    )
    if contribution["finalized_at"] != normalize_utc_timestamp(
        contribution["finalized_at"], label="finalized_at"
    ):
        raise ContractV3ValidationError("contribution finalized_at is non-canonical")


def validate_persistence_state_v3(state: dict[str, Any]) -> None:
    """Validate schema, hashes, ordering, references, and date uniqueness."""

    validate_v3_schema("persistence-state-v3", state)
    if state["generated_at"] != normalize_utc_timestamp(
        state["generated_at"], label="generated_at"
    ):
        raise ContractV3ValidationError("state generated_at is non-canonical")
    expected_digest = _state_digest(*_state_identity_inputs(state))
    if state["state_id"] != "state-v3-" + expected_digest:
        raise ContractV3ValidationError("persistence state_id checksum mismatch")
    if state["identity_inputs_sha256"] != expected_digest:
        raise ContractV3ValidationError(
            "persistence identity-input checksum mismatch"
        )
    integrity = state["integrity"]
    components = {
        "finalized_dates_sha256": state["finalized_dates"],
        "events_sha256": state["events"],
        "lineage_sha256": state["lineage"],
        "contributions_sha256": state["contributions"],
        "watermark_sha256": state["watermark"],
    }
    for field, value in components.items():
        if integrity[field] != canonical_sha256(value):
            raise ContractV3ValidationError(f"persistence {field} mismatch")
    without_document_checksum = deepcopy(state)
    del without_document_checksum["integrity"]["document_sha256"]
    if integrity["document_sha256"] != canonical_sha256(
        without_document_checksum
    ):
        raise ContractV3ValidationError("persistence document checksum mismatch")

    finalized_dates = state["finalized_dates"]
    if finalized_dates != sorted(
        finalized_dates, key=lambda item: item["observed_on"]
    ):
        raise ContractV3ValidationError("finalized dates are not ordered")
    if len({item["observed_on"] for item in finalized_dates}) != len(
        finalized_dates
    ):
        raise ContractV3ValidationError("duplicate finalized UTC date")
    events = state["events"]
    lineage = state["lineage"]
    contributions = state["contributions"]
    if events != sorted(events, key=lambda item: item["event_id"].encode("utf-8")):
        raise ContractV3ValidationError("events are not event-ID ordered")
    if lineage != sorted(
        lineage, key=lambda item: item["lineage_id"].encode("utf-8")
    ):
        raise ContractV3ValidationError("lineage is not lineage-ID ordered")
    if contributions != sorted(
        contributions,
        key=lambda item: item["contribution_key"].encode("utf-8"),
    ):
        raise ContractV3ValidationError("contributions are not key ordered")
    pairs = [(item["event_id"], item["observed_on"]) for item in contributions]
    if len(pairs) != len(set(pairs)):
        raise ContractV3ValidationError(
            "more than one contribution exists for an event/UTC date"
        )
    event_ids = {item["event_id"] for item in events}
    events_by_id = {item["event_id"]: item for item in events}
    lineage_ids = {item["lineage_id"] for item in lineage}
    contribution_keys = {item["contribution_key"] for item in contributions}
    if len(event_ids) != len(events):
        raise ContractV3ValidationError("duplicate event ID in persistence state")
    if len(lineage_ids) != len(lineage):
        raise ContractV3ValidationError("duplicate lineage ID in persistence state")
    if len(contribution_keys) != len(contributions):
        raise ContractV3ValidationError(
            "duplicate contribution key in persistence state"
        )
    finalized_by_date = {item["observed_on"]: item for item in finalized_dates}
    if state["transition_policy"] != {
        "contribution_uniqueness": "event_id+observed_on",
        "duplicate_contribution": "no_op",
        "chronological_order": "acquisition_timestamp_utc+acquisition_id",
        "late_same_day_acquisition": "requires_new_chronological_generation",
        "legacy_serialization": "v1_v2_forbidden_audit_only",
        "confirmed_min_distinct_dates": DEFAULT_CONFIRMED_MIN,
        "event_reconnect_grace_days": DEFAULT_GRACE_DAYS,
        "minimum_overlap_fraction": DEFAULT_MIN_OVERLAP_FRAC,
    }:
        raise ContractV3ValidationError("persistence transition policy mismatch")
    if finalized_dates:
        latest = finalized_dates[-1]
        if (
            state["run_manifest_id"] != latest["run_manifest_id"]
            or state["run_manifest_sha256"] != latest["run_manifest_sha256"]
        ):
            raise ContractV3ValidationError(
                "state manifest must equal the latest finalized-date manifest"
            )
        watermark = state["watermark"]
        if watermark is None or watermark["observed_on"] != latest["observed_on"]:
            raise ContractV3ValidationError(
                "state watermark/date reconciliation failed"
            )
        watermark_timestamp = normalize_utc_timestamp(
            watermark["acquisition_timestamp_utc"],
            label="watermark.acquisition_timestamp_utc",
        )
        if watermark["acquisition_timestamp_utc"] != watermark_timestamp:
            raise ContractV3ValidationError(
                "state watermark acquisition timestamp is non-canonical"
            )
        if watermark["observed_on"] != watermark_timestamp[:10]:
            raise ContractV3ValidationError(
                "state watermark date differs from its acquisition timestamp"
            )
        require_v3_id(
            watermark["acquisition_id"],
            prefix="acq-v3-",
            label="watermark.acquisition_id",
        )
        expected_last_transition = {
            "outcome": "applied",
            "observed_on": latest["observed_on"],
            "date_input_digest": latest["date_input_digest"],
            "new_contribution_count": len(latest["contribution_keys"]),
            "duplicate_contribution_count": 0,
            "state_changed": True,
        }
    elif state["watermark"] is not None:
        raise ContractV3ValidationError("empty state cannot have a watermark")
    else:
        expected_last_transition = {
            "outcome": "initialized",
            "observed_on": None,
            "date_input_digest": None,
            "new_contribution_count": 0,
            "duplicate_contribution_count": 0,
            "state_changed": False,
        }
    if state["last_transition"] != expected_last_transition:
        raise ContractV3ValidationError(
            "last transition does not reconcile with finalized state"
        )

    for contribution in contributions:
        validate_persistence_contribution_v3(contribution)
        expected_key = contribution["contribution_key"]
        if contribution["event_id"] not in event_ids:
            raise ContractV3ValidationError("contribution references unknown event")
        finalized = finalized_by_date.get(contribution["observed_on"])
        if finalized is None or expected_key not in finalized["contribution_keys"]:
            raise ContractV3ValidationError(
                "contribution is absent from its finalized-date record"
            )
        if (
            contribution["run_manifest_id"] != finalized["run_manifest_id"]
            or contribution["run_manifest_sha256"]
            != finalized["run_manifest_sha256"]
            or contribution["daily_summary_sha256"]
            != finalized["daily_summary_sha256"]
        ):
            raise ContractV3ValidationError(
                "contribution provenance differs from its finalized date"
            )
    for event in events:
        validate_event_v3(event)
        if (
            event["run_manifest_id"] != state["run_manifest_id"]
            or event["run_manifest_sha256"] != state["run_manifest_sha256"]
            or event["monitoring_extent_id"] != state["monitoring_extent_id"]
        ):
            raise ContractV3ValidationError(
                "event snapshot differs from current state bindings"
            )
        dates = event["observation_dates"]
        if dates != sorted(set(dates)):
            raise ContractV3ValidationError(
                "event observation dates are not unique/order"
            )
        if event["n_distinct_observation_dates"] != len(dates):
            raise ContractV3ValidationError("event distinct-date count mismatch")
        event_contributions = sorted(
            (
                item
                for item in contributions
                if item["event_id"] == event["event_id"]
            ),
            key=lambda item: item["contribution_key"].encode("utf-8"),
        )
        expected_event_keys = [
            item["contribution_key"] for item in event_contributions
        ]
        expected_event_dates = sorted(
            {item["observed_on"] for item in event_contributions}
        )
        if event["contribution_keys"] != expected_event_keys:
            raise ContractV3ValidationError(
                "event contribution references are not exact/reciprocal"
            )
        if dates != expected_event_dates:
            raise ContractV3ValidationError(
                "event observation dates do not equal contributed dates"
            )
        if event["identity_basis"]["kind"] == "origin":
            first_date_contributions = [
                item
                for item in event_contributions
                if item["observed_on"] == event["first_observed_on"]
            ]
            first_observation_id = event["identity_basis"][
                "first_observation_id"
            ]
            if (
                len(first_date_contributions) != 1
                or first_observation_id
                not in first_date_contributions[0]["source_observation_ids"]
            ):
                raise ContractV3ValidationError(
                    "origin event first observation is absent from its first-date "
                    "contribution"
                )
        expected_tier = persistence_tier_v3(len(expected_event_dates))
        if event["persistence_tier"] != expected_tier:
            raise ContractV3ValidationError("event persistence tier mismatch")
        contributed_acquisitions = {
            value
            for contribution in event_contributions
            for value in contribution["source_acquisition_ids"]
        }
        contributed_observations = {
            value
            for contribution in event_contributions
            for value in contribution["source_observation_ids"]
        }
        if set(event["acquisition_ids"]) != contributed_acquisitions:
            raise ContractV3ValidationError(
                "event acquisitions differ from contribution sources"
            )
        if set(event["observation_ids"]) != contributed_observations:
            raise ContractV3ValidationError(
                "event observations differ from contribution sources"
            )
        representative_observation_ids = {
            observation_id_v3(
                acquisition_id,
                event["representative_geometry_sha256"],
                state["algorithm_version"],
                state["baseline_version"],
            )
            for acquisition_id in event["acquisition_ids"]
        }
        if not representative_observation_ids & set(event["observation_ids"]):
            raise ContractV3ValidationError(
                "event representative geometry is not bound to a raw observation"
            )
        if not set(event["incoming_lineage_ids"]) <= lineage_ids:
            raise ContractV3ValidationError("event references unknown incoming lineage")
        if not set(event["outgoing_lineage_ids"]) <= lineage_ids:
            raise ContractV3ValidationError("event references unknown outgoing lineage")
        expected_incoming = sorted(
            (
                edge["lineage_id"]
                for edge in lineage
                if event["event_id"] in edge["child_event_ids"]
            ),
            key=lambda item: item.encode("utf-8"),
        )
        expected_outgoing = sorted(
            (
                edge["lineage_id"]
                for edge in lineage
                if event["event_id"] in edge["parent_event_ids"]
            ),
            key=lambda item: item.encode("utf-8"),
        )
        if event["incoming_lineage_ids"] != expected_incoming:
            raise ContractV3ValidationError(
                "event incoming lineage list is not exact/reciprocal"
            )
        if event["outgoing_lineage_ids"] != expected_outgoing:
            raise ContractV3ValidationError(
                "event outgoing lineage list is not exact/reciprocal"
            )
        has_replacing_lineage = any(
            edge["relation"] in {"split", "merge"}
            and event["event_id"] in edge["parent_event_ids"]
            for edge in lineage
        )
        expected_status = "superseded" if has_replacing_lineage else "active"
        if event["status"] != expected_status:
            raise ContractV3ValidationError(
                "event status does not reconcile with split/merge lineage"
            )
        if not set(event["identity_basis"]["trigger_observation_ids"]) <= set(
            event["observation_ids"]
        ):
            raise ContractV3ValidationError(
                "event identity triggers are absent from its observations"
            )
    for edge in lineage:
        validate_lineage_v3(edge)
        if edge["algorithm_version"] != state["algorithm_version"]:
            raise ContractV3ValidationError(
                "lineage algorithm version differs from state"
            )
        if not set(edge["parent_event_ids"]) <= event_ids:
            raise ContractV3ValidationError("lineage references unknown parent event")
        if not set(edge["child_event_ids"]) <= event_ids:
            raise ContractV3ValidationError("lineage references unknown child event")
        finalized = finalized_by_date.get(edge["observed_on"])
        if finalized is None:
            raise ContractV3ValidationError(
                "lineage is absent from a finalized UTC date"
            )
        if (
            edge["run_manifest_id"] != finalized["run_manifest_id"]
            or edge["run_manifest_sha256"] != finalized["run_manifest_sha256"]
        ):
            raise ContractV3ValidationError(
                "lineage provenance differs from its finalized UTC date"
            )
        date_contributions = [
            item
            for item in contributions
            if item["observed_on"] == edge["observed_on"]
        ]
        if edge["effective_acquisition_id"] not in {
            value
            for item in date_contributions
            for value in item["source_acquisition_ids"]
        }:
            raise ContractV3ValidationError(
                "lineage acquisition is absent from daily contributions"
            )
        if not set(edge["trigger_observation_ids"]) <= {
            value
            for item in date_contributions
            for value in item["source_observation_ids"]
        }:
            raise ContractV3ValidationError(
                "lineage triggers are absent from daily contributions"
            )
        if edge["relation"] == "continuation":
            if edge["parent_event_ids"] != edge["child_event_ids"]:
                raise ContractV3ValidationError(
                    "continuation lineage must preserve a single event"
                )
            child = events_by_id[edge["child_event_ids"][0]]
            child_triggers = set(edge["trigger_observation_ids"])
            if not child_triggers <= set(child["observation_ids"]):
                raise ContractV3ValidationError(
                    "continuation triggers are absent from the continued event"
                )
            expected_child_triggers = {
                child["event_id"]: child_triggers,
            }
        else:
            expected_child_triggers: dict[str, set[str]] = {}
            for child_id in edge["child_event_ids"]:
                child = events_by_id[child_id]
                basis = child["identity_basis"]
                if (
                    basis["kind"] != edge["relation"]
                    or basis["parent_event_ids"] != edge["parent_event_ids"]
                ):
                    raise ContractV3ValidationError(
                        "derived child identity basis differs from its lineage"
                    )
                child_triggers = set(basis["trigger_observation_ids"])
                if not child_triggers <= set(child["observation_ids"]):
                    raise ContractV3ValidationError(
                        "lineage child triggers are absent from the child event"
                    )
                expected_child_triggers[child_id] = child_triggers
            if set().union(*expected_child_triggers.values()) != set(
                edge["trigger_observation_ids"]
            ):
                raise ContractV3ValidationError(
                    "lineage triggers differ from its derived child identities"
                )
        for child_id, child_triggers in expected_child_triggers.items():
            matching = [
                item
                for item in date_contributions
                if item["event_id"] == child_id
            ]
            if len(matching) != 1:
                raise ContractV3ValidationError(
                    "lineage child must have one contribution on its effective date"
                )
            contribution = matching[0]
            if (
                not child_triggers
                or not child_triggers
                <= set(contribution["source_observation_ids"])
                or edge["effective_acquisition_id"]
                not in contribution["source_acquisition_ids"]
            ):
                raise ContractV3ValidationError(
                    "lineage child provenance differs from its effective inputs"
                )
        for event_id in edge["parent_event_ids"]:
            event = events_by_id[event_id]
            if edge["lineage_id"] not in event["outgoing_lineage_ids"]:
                raise ContractV3ValidationError(
                    "parent event omits reciprocal outgoing lineage"
                )
        for event_id in edge["child_event_ids"]:
            event = events_by_id[event_id]
            if edge["lineage_id"] not in event["incoming_lineage_ids"]:
                raise ContractV3ValidationError(
                    "child event omits reciprocal incoming lineage"
                )
    finalized_key_union: set[str] = set()
    for finalized in finalized_dates:
        _require_canonical_values(
            finalized["contribution_keys"],
            label="finalized-date contribution keys",
        )
        expected_date_keys = {
            item["contribution_key"]
            for item in contributions
            if item["observed_on"] == finalized["observed_on"]
        }
        if set(finalized["contribution_keys"]) != expected_date_keys:
            raise ContractV3ValidationError(
                "finalized-date contribution list is not exact"
            )
        finalized_key_union.update(finalized["contribution_keys"])
    if finalized_key_union != contribution_keys:
        raise ContractV3ValidationError(
            "state contributions are not all bound to finalized dates"
        )
    all_source_observations = [
        value
        for contribution in contributions
        for value in contribution["source_observation_ids"]
    ]
    if len(all_source_observations) != len(set(all_source_observations)):
        raise ContractV3ValidationError(
            "one observation is assigned to more than one event contribution"
        )


def load_persistence_state_v3(path) -> dict[str, Any]:
    state = load_v3_document(path, "persistence-state-v3")
    validate_persistence_state_v3(state)
    return state
