#!/usr/bin/env python3
"""Validate the Phase 1 schemas, fixtures, and cross-contract invariants.

Run from the backend repository with its documented environment:

    /opt/anaconda3/envs/araripe/bin/python \
        docs/contracts/phase1/validate_contracts.py

This validator has no network or cloud dependency. The fixture canonical JSON
values contain only number forms for which Python's compact sorted encoding is
byte-identical to RFC 8785. Production identity code must use a complete,
tested RFC 8785 implementation rather than reusing this fixture helper.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent
SCHEMAS = ROOT / "schemas"
EXAMPLES = ROOT / "examples"
CONTRACT_NAMES = (
    "monitoring-extent-v1",
    "observation-v1",
    "event-v1",
    "persistence-state-v1",
    "processing-ledger-v1",
    "release-manifest-v1",
)
UNIT_SEPARATOR = "\x1f"
LINE_FEED = "\n"
PUBLIC_DATA_ORIGIN = "https://observatoriodachapadadoararipe.com/data/"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def canonical_fixture_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_fixture_bytes(value))


def identity_sha256(*components: str) -> str:
    return sha256_bytes(UNIT_SEPARATOR.join(components).encode("utf-8"))


def sorted_lines(values: list[str]) -> str:
    require(len(values) == len(set(values)), "identity list contains duplicates")
    require(values == sorted(values), "identity list is not UTF-8 sorted")
    return LINE_FEED.join(values)


def validate_schema_examples() -> dict[str, Any]:
    actual_schemas = {path.name for path in SCHEMAS.glob("*.schema.json")}
    actual_examples = {path.name for path in EXAMPLES.glob("*.example.json")}
    expected_schemas = {f"{name}.schema.json" for name in CONTRACT_NAMES}
    expected_examples = {f"{name}.example.json" for name in CONTRACT_NAMES}
    require(actual_schemas == expected_schemas, "schema file set is incomplete or unexpected")
    require(actual_examples == expected_examples, "example file set is incomplete or unexpected")

    documents: dict[str, Any] = {}
    checker = FormatChecker()
    for name in CONTRACT_NAMES:
        schema = load_json(SCHEMAS / f"{name}.schema.json")
        example = load_json(EXAMPLES / f"{name}.example.json")
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
        documents[name] = example
    return documents


def validate_extent(extent: dict[str, Any]) -> None:
    require(extent["scope"]["includes_apa_and_surroundings"], "extent omits surroundings")
    require(not extent["scope"]["narrowed_to_apa"], "extent is silently narrowed to APA")
    require(
        canonical_sha256(extent["geometry"]) == extent["canonical_geometry_sha256"],
        "extent geometry checksum mismatch",
    )
    require(
        canonical_sha256(extent["bounds_wgs84"]) == extent["canonical_bounds_sha256"],
        "extent bounds checksum mismatch",
    )


def validate_observation(observation: dict[str, Any]) -> None:
    acquisition = observation["acquisition"]
    acquisition_hash = identity_sha256(
        "acquisition-v1",
        acquisition["collection_id"],
        acquisition["observed_on"],
        sorted_lines(acquisition["scene_ids"]),
        observation["monitoring_extent_id"],
        acquisition["composite_method_id"],
    )
    require(
        acquisition["acquisition_id"] == f"acq-v1-{acquisition_hash}",
        "acquisition ID mismatch",
    )
    require(
        acquisition["identity_inputs_sha256"] == acquisition_hash,
        "acquisition identity-input checksum mismatch",
    )
    require(
        canonical_sha256(observation["geometry"])
        == observation["canonical_geometry_sha256"],
        "observation geometry checksum mismatch",
    )
    observation_hash = identity_sha256(
        "observation-v1",
        acquisition["acquisition_id"],
        observation["canonical_geometry_sha256"],
        observation["algorithm_version"],
        observation["baseline_version"],
    )
    require(
        observation["observation_id"] == f"obs-v1-{observation_hash}",
        "observation ID mismatch",
    )
    require(
        observation["observation_identity_inputs_sha256"] == observation_hash,
        "observation identity-input checksum mismatch",
    )
    contribution_hash = identity_sha256(
        "persistence-contribution-v1",
        observation["event_id"],
        acquisition["acquisition_id"],
    )
    require(
        observation["persistence_contribution_key"] == f"pc-v1-{contribution_hash}",
        "persistence contribution key mismatch",
    )
    policy = observation["raw_detection_policy"]
    require(
        policy
        == {
            "retained": True,
            "immutable": True,
            "mapbiomas_can_remove": False,
            "persistence_can_remove": False,
        },
        "raw-observation preservation policy changed",
    )
    for annotation in observation["context"]["mapbiomas"]["annotations"]:
        require(
            annotation["crop_extent_id"] == observation["monitoring_extent_id"],
            "MapBiomas crop extent differs from observation extent",
        )


def validate_event(event: dict[str, Any], observation: dict[str, Any]) -> None:
    basis = event["identity_basis"]
    if basis["kind"] == "origin":
        require(
            basis["first_observation_id"] == basis["trigger_observation_ids"][0],
            "origin event first observation differs from its trigger",
        )
        event_hash = identity_sha256(
            "event-v1",
            "origin",
            basis["first_observation_id"],
        )
    else:
        event_hash = identity_sha256(
            "event-v1",
            basis["kind"],
            sorted_lines(basis["parent_event_ids"]),
            sorted_lines(basis["trigger_observation_ids"]),
        )
    require(event["event_id"] == f"evt-v1-{event_hash}", "event ID mismatch")
    require(
        event["event_identity_inputs_sha256"] == event_hash,
        "event identity-input checksum mismatch",
    )
    require(event["event_id"] == observation["event_id"], "observation/event mismatch")
    require(
        observation["observation_id"] in event["observation_ids"],
        "event omits the observation fixture",
    )
    require(
        observation["acquisition"]["acquisition_id"]
        in event["contributing_acquisition_ids"],
        "event omits the acquisition fixture",
    )
    require(
        observation["persistence_contribution_key"] in event["contribution_keys"],
        "event omits the contribution fixture",
    )
    require(
        canonical_sha256(event["representative_geometry"])
        == event["representative_geometry_sha256"],
        "event representative-geometry checksum mismatch",
    )
    for direction in ("incoming", "outgoing"):
        for edge in event["lineage"][direction]:
            lineage_hash = identity_sha256(
                "lineage-v1",
                edge["relation"],
                sorted_lines(edge["parent_event_ids"]),
                sorted_lines(edge["child_event_ids"]),
                edge["effective_acquisition_id"],
                edge["effective_on"],
                sorted_lines(edge["trigger_observation_ids"]),
                edge["algorithm_version"],
            )
            require(
                edge["lineage_id"] == f"lin-v1-{lineage_hash}",
                "lineage ID mismatch",
            )
            if direction == "incoming":
                require(
                    event["event_id"] in edge["child_event_ids"],
                    "incoming lineage edge omits current event",
                )
            else:
                require(
                    event["event_id"] in edge["parent_event_ids"],
                    "outgoing lineage edge omits current event",
                )
    require(event["first_observed_on"] <= event["last_observed_on"], "event dates reversed")
    require(event["raw_observations_preserved"], "event does not preserve observations")


def validate_state(
    state: dict[str, Any],
    event: dict[str, Any],
    observation: dict[str, Any],
) -> None:
    require(state["release_id"] == observation["release_id"], "state release mismatch")
    require(
        state["monitoring_extent_id"] == observation["monitoring_extent_id"],
        "state extent mismatch",
    )
    require(
        state["watermark"]["acquisition_id"]
        == observation["acquisition"]["acquisition_id"],
        "state watermark acquisition mismatch",
    )
    all_keys: list[str] = []
    fixture_state_event = None
    for state_event in state["events"]:
        contributions = state_event["contributions"]
        acquisition_ids = {item["acquisition_id"] for item in contributions}
        observed_dates = {item["observed_on"] for item in contributions}
        require(
            state_event["n_distinct_acquisitions"] == len(acquisition_ids),
            "persistence distinct-acquisition count mismatch",
        )
        require(
            len(observed_dates) == len(contributions),
            "event has more than one persistence contribution for a date",
        )
        require(
            state_event["first_seen"] <= state_event["last_seen"],
            "persistence event dates reversed",
        )
        for contribution in contributions:
            all_keys.append(contribution["contribution_key"])
        if state_event["event_id"] == event["event_id"]:
            fixture_state_event = state_event
    require(len(all_keys) == len(set(all_keys)), "duplicate contribution key in state")
    require(fixture_state_event is not None, "state omits the event fixture")
    require(
        observation["persistence_contribution_key"] in all_keys,
        "state omits the observation contribution key",
    )


def validate_ledger(
    ledger: dict[str, Any],
    observation: dict[str, Any],
) -> None:
    dates = ledger["expected_dates"]
    entry_dates = [entry["expected_date"] for entry in ledger["entries"]]
    require(dates == sorted(set(dates)), "expected dates are not sorted and unique")
    require(entry_dates == dates, "ledger entries do not exactly match expected dates")
    statuses = Counter(entry["status"] for entry in ledger["entries"])
    summary = ledger["summary"]
    require(summary["expected_date_count"] == len(dates), "expected-date count mismatch")
    require(summary["terminal_count"] == len(ledger["entries"]), "terminal count mismatch")
    for status in (
        "complete_with_alerts",
        "complete_zero_alerts",
        "rejected_low_coverage",
        "rejected_quality",
        "failed_download",
        "failed_missing_input",
        "failed_processing",
    ):
        require(summary[status] == statuses[status], f"summary mismatch for {status}")
    for entry in ledger["entries"]:
        require(
            entry["source_input"]["source_count"]
            == len(entry["source_input"]["scene_ids"]),
            f"source-count mismatch for {entry['expected_date']}",
        )
        require(
            entry["output"]["observation_count"]
            == len(entry["output"]["observation_ids"]),
            f"observation-count mismatch for {entry['expected_date']}",
        )
    failed_dates = [
        entry["expected_date"]
        for entry in ledger["entries"]
        if entry["status"].startswith("failed_")
    ]
    eligibility = ledger["release_eligibility"]
    require(
        eligibility["one_canonical_acquisition_per_expected_date"],
        "ledger does not enforce one canonical acquisition per date",
    )
    require(
        eligibility["corrected_same_date_requires_new_generation"],
        "ledger allows corrected same-date acquisition in the current generation",
    )
    require(
        eligibility["blocking_entry_dates"] == failed_dates,
        "ledger blocking-date list mismatch",
    )
    require(eligibility["eligible"] == (not failed_dates), "ledger eligibility mismatch")
    require(
        canonical_sha256(ledger["entries"]) == ledger["integrity"]["entries_sha256"],
        "ledger entry checksum mismatch",
    )
    observation_entries = [
        entry
        for entry in ledger["entries"]
        if observation["observation_id"] in entry["output"]["observation_ids"]
    ]
    require(len(observation_entries) == 1, "observation not represented exactly once in ledger")


def validate_manifest(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    state: dict[str, Any],
    extent: dict[str, Any],
    observation: dict[str, Any],
) -> None:
    release_id = manifest["release_id"]
    require(release_id == ledger["release_id"] == state["release_id"], "release IDs diverge")
    require(
        manifest["versions"]["monitoring_extent"]["id"] == extent["extent_id"],
        "manifest extent ID mismatch",
    )
    require(
        all(version == "1.0.0" for version in manifest["versions"]["schemas"].values()),
        "fixture contains an unexpected schema version",
    )
    mapbiomas_versions = {
        item["id"]: item for item in manifest["versions"]["mapbiomas"]
    }
    for annotation in observation["context"]["mapbiomas"]["annotations"]:
        registered = mapbiomas_versions.get(annotation["collection_id"])
        require(registered is not None, "observation uses unregistered MapBiomas collection")
        require(
            registered["version"] == annotation["collection_version"],
            "MapBiomas collection version mismatch",
        )
        require(
            registered["source_sha256"] == annotation["source_national_sha256"],
            "MapBiomas national-source checksum mismatch",
        )
    artifacts = manifest["artifacts"]
    require(
        canonical_sha256(artifacts) == manifest["integrity"]["artifact_inventory_sha256"],
        "artifact inventory checksum mismatch",
    )
    require(
        len({item["artifact_id"] for item in artifacts}) == len(artifacts),
        "duplicate artifact ID",
    )
    require(
        len({item["immutable_path"] for item in artifacts}) == len(artifacts),
        "duplicate artifact path",
    )
    release_prefix = f"releases/{release_id}/"
    by_path = {item["immutable_path"]: item for item in artifacts}
    for artifact in artifacts:
        path = artifact["immutable_path"]
        require(path.startswith(release_prefix), f"artifact escapes release prefix: {path}")
        if artifact["visibility"] == "public":
            require(
                artifact["public_url"] == f"{PUBLIC_DATA_ORIGIN}{path}",
                f"public URL/path mismatch for {artifact['artifact_id']}",
            )
        else:
            require(
                artifact["public_url"] is None,
                f"private artifact has public URL: {artifact['artifact_id']}",
            )
    for name, reference in manifest["authoritative_records"].items():
        artifact = by_path.get(reference["immutable_path"])
        require(artifact is not None, f"authoritative {name} is absent from inventory")
        require(
            artifact["sha256"] == reference["sha256"],
            f"authoritative {name} checksum differs from inventory",
        )
    completeness = manifest["completeness"]
    require(
        completeness["expected_date_count"] == ledger["summary"]["expected_date_count"],
        "manifest/ledger expected-date count mismatch",
    )
    require(
        completeness["terminal_date_count"] == ledger["summary"]["terminal_count"],
        "manifest/ledger terminal-date count mismatch",
    )
    failed_count = sum(
        ledger["summary"][status]
        for status in ("failed_download", "failed_missing_input", "failed_processing")
    )
    require(completeness["failed_date_count"] == failed_count, "failed-date count mismatch")
    require(
        manifest["promotion"]["expected_previous_release_id"]
        == manifest["rollback"]["previous_release_id"],
        "promotion and rollback disagree on previous release",
    )
    require(manifest["promotion"]["eligible"] == ledger["release_eligibility"]["eligible"],
            "manifest and ledger eligibility mismatch")


def main() -> None:
    documents = validate_schema_examples()
    extent = documents["monitoring-extent-v1"]
    observation = documents["observation-v1"]
    event = documents["event-v1"]
    state = documents["persistence-state-v1"]
    ledger = documents["processing-ledger-v1"]
    manifest = documents["release-manifest-v1"]

    validate_extent(extent)
    validate_observation(observation)
    validate_event(event, observation)
    validate_state(state, event, observation)
    validate_ledger(ledger, observation)
    validate_manifest(manifest, ledger, state, extent, observation)
    print("Phase 1 contracts: 6 schemas and 6 examples valid; semantic checks passed.")


if __name__ == "__main__":
    main()
