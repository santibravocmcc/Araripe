#!/usr/bin/env python3
"""Validate the Phase 2A.6A v2 schemas, examples, and semantic invariants.

Run locally from the backend repository:

    /opt/anaconda3/envs/araripe/bin/python \
        docs/contracts/phase2a/validate_v2_contracts.py

This validator has no cloud dependency and deliberately reuses the repository's
stable RFC 8785 and geometry canonicalization primitives so fixture identities
cannot drift from runtime identities.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.detection.identity import (
    canonical_geometry_sha256,
    canonical_json_bytes,
    canonical_sha256,
    identity_sha256,
)

SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"
PHASE1_SCHEMAS = REPOSITORY_ROOT / "docs" / "contracts" / "phase1" / "schemas"
DECISION_RECORD = REPOSITORY_ROOT / "config" / "phase2a_candidate_generation_decisions_v2.json"
CONTRACT_NAMES = (
    "acquisition-v2",
    "observation-v2",
    "event-v2",
    "lineage-v2",
    "persistence-contribution-v2",
    "persistence-state-v2",
    "processing-ledger-v2",
)
UNIT_SEPARATOR = "\x1f"
LINE_FEED = "\n"
TERMINAL_STATUSES = (
    "complete_with_alerts",
    "complete_zero_alerts",
    "rejected_low_coverage",
    "rejected_quality",
    "failed_download",
    "failed_missing_input",
    "failed_processing",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value)


def sorted_lines(values: list[str], label: str) -> str:
    require(len(values) == len(set(values)), f"{label} contains duplicates")
    require(values == sorted(values), f"{label} is not UTF-8 sorted")
    return LINE_FEED.join(values)


def document_hash(value: dict[str, Any]) -> str:
    payload = deepcopy(value)
    del payload["integrity"]["document_sha256"]
    return canonical_sha256(payload)


def daily_summary_hash(value: dict[str, Any]) -> str:
    payload = dict(value)
    del payload["daily_summary_sha256"]
    return canonical_sha256(payload)


def utc_instant(value: str) -> datetime:
    require(value.endswith("Z"), f"timestamp is not explicit UTC: {value}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AssertionError(f"invalid UTC timestamp: {value}") from exc
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    if parsed.microsecond:
        canonical += "." + f"{parsed.microsecond:06d}".rstrip("0")
    canonical += "Z"
    require(value == canonical, f"timestamp is not in canonical UTC form: {value}")
    return parsed


def stable_observation_record(record: dict[str, Any]) -> dict[str, Any]:
    """Project an observation to immutable scientific retry inputs."""

    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key not in {"run_manifest_id", "run_manifest_sha256", "created_at"}
    }


def date_input_digest(
    value: dict[str, Any],
    rows: list[dict[str, Any]],
    observation_records: list[dict[str, Any]],
) -> str:
    records = sorted(
        (deepcopy(item) for item in observation_records),
        key=lambda item: item["observation_id"].encode("utf-8"),
    )
    record_ids = [item["observation_id"] for item in records]
    require(len(record_ids) == len(set(record_ids)), "duplicate observation record")
    records_by_acquisition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_acquisition[record["acquisition_id"]].append(record)
    terminal_inputs = []
    for row in rows:
        reason = row["reason"]
        acquisition_records = records_by_acquisition[row["acquisition_id"]]
        require(
            [item["observation_id"] for item in acquisition_records]
            == row["output"]["observation_ids"],
            "complete observation records do not reconcile with terminal row",
        )
        terminal_inputs.append(
            {
                "acquisition_id": row["acquisition_id"],
                "status": row["status"],
                "observation_ids": row["output"]["observation_ids"],
                "observation_records_sha256": canonical_sha256(
                    [
                        stable_observation_record(record)
                        for record in acquisition_records
                    ]
                ),
                "artifact_sha256": row["output"]["artifact_sha256"],
                "reason_code": None if reason is None else reason["code"],
            }
        )
    return canonical_sha256(
        {
            "observed_on": value["observed_on"],
            "expected_acquisition_ids": value["expected_acquisition_ids"],
            "terminal_inputs": terminal_inputs,
        }
    )


def validate_schema_examples() -> dict[str, dict[str, Any]]:
    checker = FormatChecker()
    documents: dict[str, dict[str, Any]] = {}
    for name in CONTRACT_NAMES:
        schema_path = SCHEMAS / f"{name}.schema.json"
        example_path = EXAMPLES / f"{name}.example.json"
        require(schema_path.is_file(), f"missing schema: {schema_path.name}")
        require(example_path.is_file(), f"missing example: {example_path.name}")
        schema = load_json(schema_path)
        example = load_json(example_path)
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=checker).iter_errors(example),
            key=lambda error: list(error.absolute_path),
        )
        require(
            not errors,
            f"{name} schema errors: "
            + "; ".join(
                f"{'/'.join(map(str, error.absolute_path))}: {error.message}"
                for error in errors
            ),
        )
        require(example["schema_version"] == "2.0.0", f"{name} is not v2")
        documents[name] = example
    return documents


def validate_decision_lock() -> None:
    decision = load_json(DECISION_RECORD)
    identity = decision["identity"]
    require(
        identity["contract_family"]["required_contracts"] == list(CONTRACT_NAMES),
        "v2 contract family differs from the accepted decision lock",
    )
    require(identity["contract_family"]["selected_major"] == 2, "decision lock no longer selects v2")
    require(not identity["contract_family"]["v1_runtime_serialization_permitted"], "decision lock permits v1 serialization")
    require(identity["acquisition"]["id_prefix"] == "acq-v2-", "acquisition prefix differs from decision lock")
    require(identity["observation"]["id_prefix"] == "obs-v2-", "observation prefix differs from decision lock")
    require(identity["event"]["id_prefix"] == "evt-v2-", "event prefix differs from decision lock")
    require(identity["lineage"]["id_prefix"] == "lin-v2-", "lineage prefix differs from decision lock")
    persistence = identity["persistence"]
    require(persistence["contribution_key_prefix"] == "pc-v2-", "contribution prefix differs from decision lock")
    require(persistence["maximum_contributions_per_event_per_utc_date"] == 1, "decision lock permits duplicate daily contribution")
    require(persistence["duplicate_contribution_policy"] == "no_op", "decision lock changed retry semantics")
    ledger = identity["processing_ledger"]
    require(ledger["accounting_unit"] == "expected_acquisition", "decision lock changed ledger unit")
    require(ledger["expected_acquisition_set_bound_to_run_manifest"], "decision lock removed manifest binding")
    require(ledger["same_day_multiple_acquisitions_permitted"], "decision lock forbids same-day datatakes")
    require(
        ledger["chronological_order_key"] == ["acquisition_timestamp_utc", "acquisition_id"],
        "decision lock changed chronological order",
    )


def validate_common_manifest_binding(documents: dict[str, dict[str, Any]]) -> tuple[str, str]:
    manifest_ids = {document["run_manifest_id"] for document in documents.values()}
    manifest_hashes = {document["run_manifest_sha256"] for document in documents.values()}
    require(len(manifest_ids) == 1, "v2 fixtures do not share one run manifest ID")
    require(len(manifest_hashes) == 1, "v2 fixtures do not share one run manifest checksum")
    return next(iter(manifest_ids)), next(iter(manifest_hashes))


def validate_acquisition(acquisition: dict[str, Any]) -> None:
    utc_instant(acquisition["acquisition_timestamp_utc"])
    require(
        acquisition["observed_on"] == acquisition["acquisition_timestamp_utc"][:10],
        "acquisition observed_on is not its UTC timestamp date",
    )
    scene_lines = sorted_lines(acquisition["scene_ids"], "acquisition scene_ids")
    digest = identity_sha256(
        "acquisition-v2",
        acquisition["collection_id"],
        acquisition["platform"],
        acquisition["datatake_id"],
        acquisition["acquisition_timestamp_utc"],
        scene_lines,
        acquisition["monitoring_extent_id"],
        acquisition["composite_method_id"],
        acquisition["grid_id"],
    )
    require(acquisition["acquisition_id"] == f"acq-v2-{digest}", "acquisition ID mismatch")
    require(acquisition["identity_inputs_sha256"] == digest, "acquisition identity hash mismatch")


def validate_observation(observation: dict[str, Any], acquisition: dict[str, Any]) -> None:
    require(observation["acquisition_id"] == acquisition["acquisition_id"], "observation/acquisition mismatch")
    require(
        observation["acquisition_timestamp_utc"] == acquisition["acquisition_timestamp_utc"],
        "observation timestamp differs from its acquisition",
    )
    require(observation["observed_on"] == acquisition["observed_on"], "observation date mismatch")
    canonical_geometry, geometry_hash = canonical_geometry_sha256(
        observation["geometry"]
    )
    require(
        observation["geometry"] == canonical_geometry,
        "observation geometry is not in canonical form",
    )
    require(geometry_hash == observation["canonical_geometry_sha256"], "observation geometry hash mismatch")
    digest = identity_sha256(
        "observation-v2",
        acquisition["acquisition_id"],
        geometry_hash,
        observation["algorithm_version"],
        observation["baseline_version"],
    )
    require(observation["observation_id"] == f"obs-v2-{digest}", "observation ID mismatch")
    require(observation["identity_inputs_sha256"] == digest, "observation identity hash mismatch")
    require(
        observation["raw_detection_policy"]
        == {
            "retained": True,
            "immutable": True,
            "context_can_remove": False,
            "persistence_can_remove": False,
        },
        "raw-detection preservation policy changed",
    )
    require("event_id" not in observation, "observation embeds mutable event assignment")
    require("contribution_key" not in observation, "observation embeds persistence assignment")


def build_fixture_observation_records(
    documents: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the complete split fixture input supplied to daily finalization."""

    standalone = documents["observation-v2"]
    state = documents["persistence-state-v2"]
    ledger = documents["processing-ledger-v2"]
    acquisitions = {
        item["acquisition_id"]: item for item in ledger["expected_acquisitions"]
    }
    records = {standalone["observation_id"]: deepcopy(standalone)}
    split_events = [
        item for item in state["events"] if item["identity_basis"]["kind"] == "split"
    ]
    require(split_events, "split fixture no longer contains split children")
    split_area_ha = float(standalone["area_ha"]) / len(split_events)
    observation_schema = load_json(SCHEMAS / "observation-v2.schema.json")
    checker = FormatChecker()
    for event in state["events"]:
        require(
            len(event["observation_ids"]) == 1
            and len(event["acquisition_ids"]) == 1,
            "example event is not a one-observation fixture",
        )
        observation_id = event["observation_ids"][0]
        if observation_id in records:
            continue
        acquisition = acquisitions[event["acquisition_ids"][0]]
        canonical_geometry, geometry_hash = canonical_geometry_sha256(
            event["representative_geometry"]
        )
        record = {
            "schema_version": "2.0.0",
            "observation_id": observation_id,
            "identity_inputs_sha256": observation_id.removeprefix("obs-v2-"),
            "run_manifest_id": event["run_manifest_id"],
            "run_manifest_sha256": event["run_manifest_sha256"],
            "acquisition_id": acquisition["acquisition_id"],
            "acquisition_timestamp_utc": acquisition[
                "acquisition_timestamp_utc"
            ],
            "observed_on": acquisition["observed_on"],
            "monitoring_extent_id": acquisition["monitoring_extent_id"],
            "algorithm_version": state["algorithm_version"],
            "baseline_version": state["baseline_version"],
            "geometry_crs": "EPSG:4326",
            "geometry": canonical_geometry,
            "canonical_geometry_sha256": geometry_hash,
            "area_ha": split_area_ha,
            "raw_detection_policy": deepcopy(standalone["raw_detection_policy"]),
            "created_at": event["created_at"],
        }
        errors = list(
            Draft202012Validator(
                observation_schema, format_checker=checker
            ).iter_errors(record)
        )
        require(not errors, "derived split observation fixture is schema-invalid")
        validate_observation(record, acquisition)
        records[observation_id] = record
    return sorted(
        records.values(), key=lambda item: item["observation_id"].encode("utf-8")
    )


def event_identity_digest(event: dict[str, Any]) -> str:
    basis = event["identity_basis"]
    if basis["kind"] == "origin":
        require(basis["first_observation_id"] == basis["trigger_observation_ids"][0], "origin trigger mismatch")
        return identity_sha256("event-v2", "origin", basis["first_observation_id"])
    return identity_sha256(
        "event-v2",
        basis["kind"],
        sorted_lines(basis["parent_event_ids"], "event parent_event_ids"),
        sorted_lines(basis["trigger_observation_ids"], "event trigger_observation_ids"),
    )


def validate_origin_contribution_binding(
    event: dict[str, Any], contributions: list[dict[str, Any]]
) -> None:
    basis = event["identity_basis"]
    if basis["kind"] != "origin":
        return
    first_observation_id = basis["first_observation_id"]
    matching = [
        item
        for item in contributions
        if item["event_id"] == event["event_id"]
        and item["observed_on"] == event["first_observed_on"]
    ]
    require(
        len(matching) == 1,
        "origin event lacks exactly one own contribution on its first date",
    )
    require(
        first_observation_id in matching[0]["source_observation_ids"],
        "origin first observation is absent from its first-date contribution",
    )


def validate_event(
    event: dict[str, Any],
    observation: dict[str, Any],
    acquisition: dict[str, Any],
    contributions: list[dict[str, Any]],
) -> None:
    digest = event_identity_digest(event)
    require(event["event_id"] == f"evt-v2-{digest}", "event ID mismatch")
    require(event["identity_inputs_sha256"] == digest, "event identity hash mismatch")
    sorted_lines(event["observation_dates"], "event observation_dates")
    sorted_lines(event["observation_ids"], "event observation_ids")
    sorted_lines(event["acquisition_ids"], "event acquisition_ids")
    sorted_lines(event["contribution_keys"], "event contribution_keys")
    sorted_lines(event["incoming_lineage_ids"], "event incoming_lineage_ids")
    sorted_lines(event["outgoing_lineage_ids"], "event outgoing_lineage_ids")
    require(
        event["n_distinct_observation_dates"] == len(event["observation_dates"]),
        "event distinct-date count mismatch",
    )
    require(event["first_observed_on"] == min(event["observation_dates"]), "event first date mismatch")
    require(event["last_observed_on"] == max(event["observation_dates"]), "event last date mismatch")
    require(observation["observation_id"] in event["observation_ids"], "event omits fixture observation")
    require(acquisition["acquisition_id"] in event["acquisition_ids"], "event omits fixture acquisition")
    canonical_geometry, geometry_hash = canonical_geometry_sha256(
        event["representative_geometry"]
    )
    require(
        event["representative_geometry"] == canonical_geometry,
        "event representative geometry is not in canonical form",
    )
    require(
        geometry_hash == event["representative_geometry_sha256"],
        "event representative geometry hash mismatch",
    )
    require(event["raw_observations_preserved"], "event does not preserve raw observations")
    require(event["status"] in {"active", "superseded"}, "invalid event status")
    validate_origin_contribution_binding(event, contributions)


def lineage_identity_digest(lineage: dict[str, Any]) -> str:
    parent_lines = sorted_lines(lineage["parent_event_ids"], "lineage parent_event_ids")
    child_lines = sorted_lines(lineage["child_event_ids"], "lineage child_event_ids")
    trigger_lines = sorted_lines(lineage["trigger_observation_ids"], "lineage trigger_observation_ids")
    return identity_sha256(
        "lineage-v2",
        lineage["relation"],
        parent_lines,
        child_lines,
        lineage["effective_acquisition_id"],
        lineage["effective_timestamp_utc"],
        trigger_lines,
        lineage["algorithm_version"],
    )


def derived_event_id(
    relation: str, parent_event_ids: list[str], trigger_observation_ids: list[str]
) -> str:
    require(relation in {"split", "merge"}, "derived event must split or merge")
    return "evt-v2-" + identity_sha256(
        "event-v2",
        relation,
        sorted_lines(parent_event_ids, "derived event parent IDs"),
        sorted_lines(trigger_observation_ids, "derived event trigger IDs"),
    )


def validate_executable_lineage(
    lineage: dict[str, Any], event_states: dict[str, dict[str, Any]]
) -> None:
    parents = lineage["parent_event_ids"]
    children = lineage["child_event_ids"]
    triggers = lineage["trigger_observation_ids"]
    relation = lineage["relation"]
    require(set(parents) <= set(event_states), "lineage has unknown parent")
    require(set(children) <= set(event_states), "lineage has unknown child")
    if relation == "continuation":
        require(parents == children, "continuation lineage is not a self-edge")
        require(
            set(triggers) <= set(event_states[children[0]]["observation_ids"]),
            "continuation trigger does not belong to its event",
        )
        return
    if relation == "split":
        expected_children = []
        for trigger in triggers:
            child_id = derived_event_id("split", parents, [trigger])
            expected_children.append(child_id)
            require(child_id in event_states, "split-derived child is absent")
            child = event_states[child_id]
            require(
                trigger in child["observation_ids"],
                "split trigger does not belong to its derived child",
            )
            require(
                child["identity_basis"]["kind"] == "split"
                and child["identity_basis"]["parent_event_ids"] == parents
                and child["identity_basis"]["trigger_observation_ids"]
                == [trigger],
                "split child identity basis does not match its trigger",
            )
        require(
            children == sorted(expected_children),
            "split children are not exactly the per-trigger derived IDs",
        )
        return
    require(relation == "merge", "unknown executable lineage relation")
    child_id = derived_event_id("merge", parents, triggers)
    require(children == [child_id], "merge child is not the derived all-trigger ID")
    child = event_states[child_id]
    require(
        set(triggers) <= set(child["observation_ids"]),
        "merge triggers do not all belong to the merged child",
    )
    require(
        child["identity_basis"]["kind"] == "merge"
        and child["identity_basis"]["parent_event_ids"] == parents
        and child["identity_basis"]["trigger_observation_ids"] == triggers,
        "merge child identity basis does not match its parents/triggers",
    )


def validate_lineage(
    lineage: dict[str, Any],
    event: dict[str, Any],
    event_states: dict[str, dict[str, Any]],
) -> None:
    digest = lineage_identity_digest(lineage)
    require(lineage["lineage_id"] == f"lin-v2-{digest}", "lineage ID mismatch")
    require(lineage["identity_inputs_sha256"] == digest, "lineage identity hash mismatch")
    utc_instant(lineage["effective_timestamp_utc"])
    utc_instant(lineage["created_at"])
    require(lineage["observed_on"] == lineage["effective_timestamp_utc"][:10], "lineage date mismatch")
    if event["event_id"] in lineage["parent_event_ids"]:
        require(lineage["lineage_id"] in event["outgoing_lineage_ids"], "event omits outgoing lineage")
    if event["event_id"] in lineage["child_event_ids"]:
        require(lineage["lineage_id"] in event["incoming_lineage_ids"], "event omits incoming lineage")
    validate_executable_lineage(lineage, event_states)


def terminal_cutoffs(ledger: dict[str, Any]) -> dict[str, datetime]:
    by_date: dict[str, list[datetime]] = defaultdict(list)
    for row in ledger["terminal_rows"]:
        by_date[row["observed_on"]].append(utc_instant(row["terminal_at"]))
    return {observed_on: max(values) for observed_on, values in by_date.items()}


def validate_contribution(
    contribution: dict[str, Any],
    event: dict[str, Any],
    observation: dict[str, Any],
    acquisition: dict[str, Any],
    ledger: dict[str, Any],
) -> None:
    digest = identity_sha256("persistence-contribution-v2", contribution["event_id"], contribution["observed_on"])
    require(contribution["contribution_key"] == f"pc-v2-{digest}", "contribution key mismatch")
    require(contribution["identity_inputs_sha256"] == digest, "contribution identity hash mismatch")
    require(contribution["event_id"] == event["event_id"], "contribution/event mismatch")
    sorted_lines(contribution["source_acquisition_ids"], "contribution acquisition IDs")
    sorted_lines(contribution["source_observation_ids"], "contribution observation IDs")
    require(acquisition["acquisition_id"] in contribution["source_acquisition_ids"], "contribution omits acquisition")
    require(observation["observation_id"] in contribution["source_observation_ids"], "contribution omits observation")
    summaries = {summary["observed_on"]: summary for summary in ledger["daily_summaries"]}
    require(contribution["observed_on"] in summaries, "contribution has no daily summary")
    cutoff = terminal_cutoffs(ledger)[contribution["observed_on"]]
    require(
        utc_instant(contribution["finalized_at"]) >= cutoff,
        "contribution was finalized before all expected acquisitions were terminal",
    )
    require(daily_summary_hash(summaries[contribution["observed_on"]]) == contribution["daily_summary_sha256"], "contribution daily-summary hash mismatch")


def validate_terminal_row(row: dict[str, Any]) -> None:
    output = row["output"]
    sorted_lines(output["observation_ids"], "terminal-row observation IDs")
    require(output["observation_count"] == len(output["observation_ids"]), "terminal output count mismatch")
    terminal_payload = dict(row)
    del terminal_payload["terminal_record_sha256"]
    require(canonical_sha256(terminal_payload) == row["terminal_record_sha256"], "terminal row hash mismatch")
    if row["status"] == "complete_with_alerts":
        require(output["observation_count"] > 0 and row["reason"] is None, "alert row semantics mismatch")
    elif row["status"] == "complete_zero_alerts":
        require(output["observation_count"] == 0 and row["reason"] is None, "zero-alert row semantics mismatch")
    else:
        require(output["observation_count"] == 0 and row["reason"] is not None, "rejection/failure row semantics mismatch")


def validate_ledger(ledger: dict[str, Any], acquisition: dict[str, Any], observation: dict[str, Any]) -> None:
    expected = ledger["expected_acquisitions"]
    rows = ledger["terminal_rows"]
    summaries = ledger["daily_summaries"]
    for item in expected:
        validate_acquisition(item)
        require(
            item["monitoring_extent_id"] == ledger["monitoring_extent_id"],
            "expected acquisition differs from ledger monitoring extent",
        )
    require(
        observation["algorithm_version"] == ledger["algorithm_version"],
        "observation differs from ledger algorithm version",
    )
    expected_order = [
        (utc_instant(item["acquisition_timestamp_utc"]), item["acquisition_id"])
        for item in expected
    ]
    require(expected_order == sorted(expected_order), "expected acquisitions are not timestamp/ID ordered")
    expected_ids = [item["acquisition_id"] for item in expected]
    require(len(expected_ids) == len(set(expected_ids)), "duplicate expected acquisition ID")
    row_ids = [row["acquisition_id"] for row in rows]
    require(len(row_ids) == len(set(row_ids)), "duplicate terminal acquisition row")
    require(row_ids == expected_ids, "terminal rows do not exactly reconcile expected acquisitions")
    expected_by_id = {item["acquisition_id"]: item for item in expected}
    rows_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        validate_terminal_row(row)
        item = expected_by_id[row["acquisition_id"]]
        require(row["acquisition_timestamp_utc"] == item["acquisition_timestamp_utc"], "terminal timestamp mismatch")
        require(row["observed_on"] == item["observed_on"], "terminal date mismatch")
        rows_by_date[row["observed_on"]].append(row)
    require([summary["observed_on"] for summary in summaries] == sorted(rows_by_date), "daily summaries are not sorted/complete")
    all_counts = Counter(row["status"] for row in rows)
    all_observations: list[str] = []
    for summary in summaries:
        date_rows = rows_by_date[summary["observed_on"]]
        date_expected_ids = [item["acquisition_id"] for item in expected if item["observed_on"] == summary["observed_on"]]
        date_row_ids = [row["acquisition_id"] for row in date_rows]
        require(summary["expected_acquisition_ids"] == sorted(date_expected_ids), "daily expected IDs mismatch")
        require(summary["terminal_acquisition_ids"] == sorted(date_row_ids), "daily terminal IDs mismatch")
        require(summary["terminal_rows_sha256"] == canonical_sha256(date_rows), "daily row hash mismatch")
        date_observations = sorted(observation_id for row in date_rows for observation_id in row["output"]["observation_ids"])
        require(summary["observation_ids"] == date_observations, "daily observation IDs mismatch")
        all_observations.extend(date_observations)
        counts = Counter(row["status"] for row in date_rows)
        require(summary["status_counts"] == {status: counts[status] for status in TERMINAL_STATUSES}, "daily status counts mismatch")
        require(summary["daily_summary_sha256"] == daily_summary_hash(summary), "daily summary hash mismatch")
    require(acquisition["acquisition_id"] in expected_ids, "ledger omits fixture acquisition")
    require(observation["observation_id"] in all_observations, "ledger omits fixture observation")
    summary = ledger["summary"]
    require(summary["expected_acquisition_count"] == len(expected), "ledger expected count mismatch")
    require(summary["terminal_acquisition_count"] == len(rows), "ledger terminal count mismatch")
    require(summary["utc_date_count"] == len(rows_by_date), "ledger date count mismatch")
    require(summary["terminal_utc_date_count"] == len(summaries), "ledger terminal date count mismatch")
    require(summary["status_counts"] == {status: all_counts[status] for status in TERMINAL_STATUSES}, "ledger status counts mismatch")
    integrity = ledger["integrity"]
    require(integrity["expected_acquisitions_sha256"] == canonical_sha256(expected), "expected acquisition hash mismatch")
    require(integrity["terminal_rows_sha256"] == canonical_sha256(rows), "terminal rows hash mismatch")
    require(integrity["daily_summaries_sha256"] == canonical_sha256(summaries), "daily summaries hash mismatch")
    require(integrity["document_sha256"] == document_hash(ledger), "ledger document hash mismatch")
    digest = identity_sha256(
        "processing-ledger-v2",
        ledger["run_manifest_id"],
        ledger["run_manifest_sha256"],
        ledger["monitoring_extent_id"],
        ledger["algorithm_version"],
        canonical_sha256(expected),
    )
    require(ledger["ledger_id"] == f"pl-v2-{digest}", "ledger ID mismatch")
    require(ledger["identity_inputs_sha256"] == digest, "ledger identity hash mismatch")


def validate_state(
    state: dict[str, Any],
    event: dict[str, Any],
    lineage: dict[str, Any],
    contribution: dict[str, Any],
    ledger: dict[str, Any],
    observation_records: list[dict[str, Any]],
) -> None:
    dates = state["finalized_dates"]
    events = state["events"]
    lineage_items = state["lineage"]
    contributions = state["contributions"]
    utc_instant(state["generated_at"])
    if state["watermark"] is not None:
        utc_instant(state["watermark"]["acquisition_timestamp_utc"])
    require([item["observed_on"] for item in dates] == sorted(item["observed_on"] for item in dates), "state dates not sorted")
    contribution_pairs = [(item["event_id"], item["observed_on"]) for item in contributions]
    require(len(contribution_pairs) == len(set(contribution_pairs)), "more than one contribution for event/date")
    for item in contributions:
        digest = identity_sha256("persistence-contribution-v2", item["event_id"], item["observed_on"])
        require(item["contribution_key"] == f"pc-v2-{digest}", "state contribution key mismatch")
        sorted_lines(item["source_acquisition_ids"], "state contribution acquisition IDs")
        sorted_lines(item["source_observation_ids"], "state contribution observation IDs")
    require(contribution in contributions, "state omits fixture contribution")
    finalized_by_date = {item["observed_on"]: item for item in dates}
    require(len(finalized_by_date) == len(dates), "duplicate finalized date")
    ledger_summaries = {item["observed_on"]: item for item in ledger["daily_summaries"]}
    ledger_rows_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ledger["terminal_rows"]:
        ledger_rows_by_date[row["observed_on"]].append(row)
    cutoffs = terminal_cutoffs(ledger)
    for observed_on, item in finalized_by_date.items():
        require(observed_on in ledger_summaries, "finalized date has no ledger summary")
        summary = ledger_summaries[observed_on]
        date_records = [
            record
            for record in observation_records
            if record["observed_on"] == observed_on
        ]
        computed_input_digest = date_input_digest(
            summary, ledger_rows_by_date[observed_on], date_records
        )
        require(
            item["date_input_digest"] == computed_input_digest,
            "finalized date input digest mismatch",
        )
        provenance_retry = deepcopy(date_records)
        for record in provenance_retry:
            record["run_manifest_id"] = "run-v2-" + "f" * 64
            record["run_manifest_sha256"] = "e" * 64
            record["created_at"] = "2026-04-08T00:00:00Z"
        require(
            date_input_digest(
                summary, ledger_rows_by_date[observed_on], provenance_retry
            )
            == computed_input_digest,
            "operational observation provenance changed the retry digest",
        )
        if date_records:
            scientific_change = deepcopy(date_records)
            scientific_change[0]["area_ha"] += 0.001
            require(
                date_input_digest(
                    summary,
                    ledger_rows_by_date[observed_on],
                    scientific_change,
                )
                != computed_input_digest,
                "scientific observation content did not change the retry digest",
            )
        require(item["daily_summary_sha256"] == summary["daily_summary_sha256"], "finalized daily-summary hash mismatch")
        expected_keys = sorted(candidate["contribution_key"] for candidate in contributions if candidate["observed_on"] == observed_on)
        require(item["contribution_keys"] == expected_keys, "finalized date contribution keys mismatch")
    event_states = {item["event_id"]: item for item in events}
    require(len(event_states) == len(events), "duplicate state event ID")
    require(event["event_id"] in event_states, "state omits fixture event")
    require([item["event_id"] for item in events] == sorted(event_states), "state events are not event-ID sorted")
    for item in events:
        require(item["run_manifest_id"] == state["run_manifest_id"], "state event manifest ID mismatch")
        require(item["run_manifest_sha256"] == state["run_manifest_sha256"], "state event manifest hash mismatch")
        sorted_lines(item["observation_dates"], "state event dates")
        sorted_lines(item["observation_ids"], "state event observation IDs")
        sorted_lines(item["acquisition_ids"], "state event acquisition IDs")
        sorted_lines(item["incoming_lineage_ids"], "state event incoming lineage IDs")
        sorted_lines(item["outgoing_lineage_ids"], "state event outgoing lineage IDs")
        require(item["n_distinct_observation_dates"] == len(item["observation_dates"]), "state event date count mismatch")
        keys = [candidate["contribution_key"] for candidate in contributions if candidate["event_id"] == item["event_id"]]
        require(item["contribution_keys"] == sorted(keys), "state event contribution list mismatch")
        require(item["observation_dates"] == sorted({candidate["observed_on"] for candidate in contributions if candidate["event_id"] == item["event_id"]}), "state event distinct dates mismatch")
        canonical_geometry, geometry_hash = canonical_geometry_sha256(
            item["representative_geometry"]
        )
        require(
            item["representative_geometry"] == canonical_geometry,
            "state event geometry is not in canonical form",
        )
        require(
            geometry_hash == item["representative_geometry_sha256"],
            "state event geometry hash mismatch",
        )
        bindable_observation_ids = {
            "obs-v2-"
            + identity_sha256(
                "observation-v2",
                acquisition_id,
                geometry_hash,
                state["algorithm_version"],
                state["baseline_version"],
            )
            for acquisition_id in item["acquisition_ids"]
        }
        require(
            bool(bindable_observation_ids & set(item["observation_ids"])),
            "state event representative geometry is not bound to any observation",
        )
        digest = event_identity_digest(item)
        require(item["event_id"] == f"evt-v2-{digest}", "state event ID mismatch")
        require(item["identity_inputs_sha256"] == digest, "state event identity hash mismatch")
        expected_tier = (
            "confirmed"
            if item["n_distinct_observation_dates"] >= state["transition_policy"]["confirmed_min_distinct_dates"]
            else "first_observation"
            if item["n_distinct_observation_dates"] == 1
            else "candidate"
        )
        require(item["persistence_tier"] == expected_tier, "state event persistence tier mismatch")
        validate_origin_contribution_binding(item, contributions)
    for item in contributions:
        event_state = event_states.get(item["event_id"])
        require(event_state is not None, "state contribution has unknown event")
        require(item["contribution_key"] in event_state["contribution_keys"], "event omits contribution reference")
        require(set(item["source_acquisition_ids"]) <= set(event_state["acquisition_ids"]), "contribution acquisition not retained by event")
        require(set(item["source_observation_ids"]) <= set(event_state["observation_ids"]), "contribution observation not retained by event")
        finalized = finalized_by_date[item["observed_on"]]
        require(item["run_manifest_id"] == finalized["run_manifest_id"], "contribution/finalized manifest ID mismatch")
        require(item["run_manifest_sha256"] == finalized["run_manifest_sha256"], "contribution/finalized manifest hash mismatch")
        require(item["daily_summary_sha256"] == finalized["daily_summary_sha256"], "contribution/finalized summary mismatch")
        require(
            utc_instant(item["finalized_at"]) >= cutoffs[item["observed_on"]],
            "state contribution predates terminal daily evidence",
        )
    lineage_ids = {item["lineage_id"] for item in lineage_items}
    require(len(lineage_ids) == len(lineage_items), "duplicate state lineage ID")
    require(lineage["lineage_id"] in lineage_ids, "state omits fixture lineage")
    require([item["lineage_id"] for item in lineage_items] == sorted(lineage_ids), "state lineage is not lineage-ID sorted")
    require(
        [item["contribution_key"] for item in contributions]
        == sorted(item["contribution_key"] for item in contributions),
        "state contributions are not contribution-key sorted",
    )
    require(
        len({item["contribution_key"] for item in contributions})
        == len(contributions),
        "duplicate state contribution key",
    )
    for item in lineage_items:
        digest = lineage_identity_digest(item)
        require(item["lineage_id"] == f"lin-v2-{digest}", "state lineage ID mismatch")
        require(item["identity_inputs_sha256"] == digest, "state lineage identity hash mismatch")
        utc_instant(item["effective_timestamp_utc"])
        utc_instant(item["created_at"])
        require(item["observed_on"] == item["effective_timestamp_utc"][:10], "state lineage date mismatch")
        require(set(item["parent_event_ids"]) <= set(event_states), "state lineage has unknown parent")
        require(set(item["child_event_ids"]) <= set(event_states), "state lineage has unknown child")
        validate_executable_lineage(item, event_states)
        for parent_id in item["parent_event_ids"]:
            require(item["lineage_id"] in event_states[parent_id]["outgoing_lineage_ids"], "parent event omits outgoing lineage")
        for child_id in item["child_event_ids"]:
            require(item["lineage_id"] in event_states[child_id]["incoming_lineage_ids"], "child event omits incoming lineage")
    for item in events:
        require(set(item["incoming_lineage_ids"]) <= lineage_ids, "unknown incoming lineage reference")
        require(set(item["outgoing_lineage_ids"]) <= lineage_ids, "unknown outgoing lineage reference")
        has_replacing_lineage = any(
            edge["relation"] in {"split", "merge"}
            and item["event_id"] in edge["parent_event_ids"]
            for edge in lineage_items
        )
        require(
            item["status"]
            == ("superseded" if has_replacing_lineage else "active"),
            "event status does not reconcile with outgoing split/merge",
        )
    integrity = state["integrity"]
    require(
        state["transition_policy"]
        == {
            "contribution_uniqueness": "event_id+observed_on",
            "duplicate_contribution": "no_op",
            "chronological_order": "acquisition_timestamp_utc+acquisition_id",
            "late_same_day_acquisition": "requires_new_chronological_generation",
            "v1_serialization": "forbidden_audit_only",
            "confirmed_min_distinct_dates": 15,
            "event_reconnect_grace_days": 180,
            "minimum_overlap_fraction": 0.05,
        },
        "state transition policy mismatch",
    )
    if dates:
        latest = dates[-1]
        require(
            utc_instant(state["generated_at"]) >= cutoffs[latest["observed_on"]],
            "state transition predates terminal evidence for its latest date",
        )
        require(
            state["last_transition"]
            == {
                "outcome": "applied",
                "observed_on": latest["observed_on"],
                "date_input_digest": latest["date_input_digest"],
                "new_contribution_count": len(latest["contribution_keys"]),
                "duplicate_contribution_count": 0,
                "state_changed": True,
            },
            "non-empty state last_transition is not the latest applied date",
        )
    else:
        require(
            state["last_transition"]
            == {
                "outcome": "initialized",
                "observed_on": None,
                "date_input_digest": None,
                "new_contribution_count": 0,
                "duplicate_contribution_count": 0,
                "state_changed": False,
            },
            "empty state last_transition is not initialized",
        )
    require(integrity["finalized_dates_sha256"] == canonical_sha256(dates), "state dates hash mismatch")
    require(integrity["events_sha256"] == canonical_sha256(events), "state events hash mismatch")
    require(integrity["lineage_sha256"] == canonical_sha256(lineage_items), "state lineage hash mismatch")
    require(integrity["contributions_sha256"] == canonical_sha256(contributions), "state contributions hash mismatch")
    require(integrity["watermark_sha256"] == canonical_sha256(state["watermark"]), "state watermark hash mismatch")
    require(integrity["document_sha256"] == document_hash(state), "state document hash mismatch")
    digest = identity_sha256(
        "persistence-state-v2",
        state["generation_id"],
        state["run_manifest_id"],
        state["run_manifest_sha256"],
        state["monitoring_extent_id"],
        state["algorithm_version"],
        state["baseline_version"],
        canonical_sha256(state["transition_policy"]),
        canonical_sha256(dates),
        canonical_sha256(events),
        canonical_sha256(lineage_items),
        canonical_sha256(contributions),
        canonical_sha256(state["watermark"]),
    )
    require(state["state_id"] == f"state-v2-{digest}", "state ID mismatch")
    require(state["identity_inputs_sha256"] == digest, "state identity hash mismatch")


def validate_v1_incompatibility(documents: dict[str, dict[str, Any]]) -> None:
    corresponding = {
        "observation-v2": "observation-v1.schema.json",
        "event-v2": "event-v1.schema.json",
        "persistence-state-v2": "persistence-state-v1.schema.json",
        "processing-ledger-v2": "processing-ledger-v1.schema.json",
    }
    checker = FormatChecker()
    for name, schema_name in corresponding.items():
        schema = load_json(PHASE1_SCHEMAS / schema_name)
        require(
            not Draft202012Validator(schema, format_checker=checker).is_valid(documents[name]),
            f"{name} was accepted by audit-only {schema_name}",
        )
    for name, document in documents.items():
        require("-v1-" not in canonical_bytes(document).decode("utf-8"), f"{name} contains a v1 identity")


def main() -> None:
    validate_decision_lock()
    documents = validate_schema_examples()
    validate_common_manifest_binding(documents)
    acquisition = documents["acquisition-v2"]
    observation = documents["observation-v2"]
    event = documents["event-v2"]
    lineage = documents["lineage-v2"]
    contribution = documents["persistence-contribution-v2"]
    state = documents["persistence-state-v2"]
    ledger = documents["processing-ledger-v2"]
    validate_acquisition(acquisition)
    validate_observation(observation, acquisition)
    observation_records = build_fixture_observation_records(documents)
    validate_event(event, observation, acquisition, [contribution])
    validate_lineage(
        lineage,
        event,
        {item["event_id"]: item for item in state["events"]},
    )
    validate_ledger(ledger, acquisition, observation)
    validate_contribution(contribution, event, observation, acquisition, ledger)
    validate_state(
        state,
        event,
        lineage,
        contribution,
        ledger,
        observation_records,
    )
    validate_v1_incompatibility(documents)
    print("Phase 2A.6A contracts: 7 schemas and 7 examples valid; semantic and v1 isolation checks passed.")


if __name__ == "__main__":
    main()
