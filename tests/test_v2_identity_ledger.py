"""Focused Package 2A.6A acquisition identities and processing-ledger rules."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import pytest
from shapely.geometry import Polygon

from src.detection.identity import canonical_geometry_sha256, canonical_sha256
from src.detection.identity_v2 import (
    AcquisitionV2,
    IdentityMajorError,
    ObservationV2,
    acquisition_order_key,
    create_acquisition_v2,
    create_observation_v2,
    normalize_utc_timestamp,
    observation_id_v2,
)
from src.detection.ledger_v2 import (
    TERMINAL_STATUSES,
    ConflictingTerminalRowError,
    IncompleteDateError,
    ProcessingLedgerV2,
    UnexpectedAcquisitionError,
)


ROOT = Path(__file__).resolve().parent.parent
LEDGER_SCHEMA = (
    ROOT / "docs" / "contracts" / "phase2a" / "schemas"
    / "processing-ledger-v2.schema.json"
)
MANIFEST_ID = "run-v2-" + "a" * 64
MANIFEST_SHA256 = "b" * 64
ARTIFACT_A = "c" * 64
ARTIFACT_B = "d" * 64
EXTENT_ID = "araripe-implementation-rectangle-v1"
ALGORITHM_VERSION = "2.0.0"
BASELINE_VERSION = "2.0.0"


def _acquisition(
    *,
    datatake_id: str,
    timestamp: str = "2026-04-07T13:12:41Z",
    platform: str = "S2A",
    scene_ids: tuple[str, ...] = ("scene-b", "scene-a"),
):
    return create_acquisition_v2(
        run_manifest_id=MANIFEST_ID,
        run_manifest_sha256=MANIFEST_SHA256,
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=timestamp,
        scene_ids=scene_ids,
        monitoring_extent_id=EXTENT_ID,
        composite_method_id="coverage-ranked-first-valid-v1",
        grid_id="araripe-sentinel2-20m-grid-v1",
    )


def _two_same_day_acquisitions():
    later = _acquisition(
        datatake_id="GS2B_20260407T132251_041247_N05.11",
        timestamp="2026-04-07T13:22:51Z",
        platform="S2B",
        scene_ids=("scene-d", "scene-c"),
    )
    earlier = _acquisition(
        datatake_id="GS2A_20260407T131241_055725_N05.11",
        timestamp="2026-04-07T13:12:41Z",
    )
    return earlier, later


def _ledger(acquisitions):
    return ProcessingLedgerV2(
        run_manifest_id=MANIFEST_ID,
        run_manifest_sha256=MANIFEST_SHA256,
        acquisitions=acquisitions,
        monitoring_extent_id=EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at="2026-04-08T00:00:00Z",
    )


def _observation(acquisition, *, x_offset: float = 0.0):
    geometry = Polygon(
        [
            (-40.0 + x_offset, -7.0),
            (-39.9 + x_offset, -7.0),
            (-39.9 + x_offset, -7.1),
            (-40.0 + x_offset, -7.1),
        ]
    )
    return create_observation_v2(
        acquisition=acquisition,
        geometry=geometry,
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=123.5,
        created_at="2026-04-07T14:00:00Z",
    )


def _complete_with_alerts(ledger, acquisition, observation, *, at, artifact):
    return ledger.record_terminal(
        acquisition_id=acquisition.acquisition_id,
        status="complete_with_alerts",
        observation_ids=[observation.observation_id],
        terminal_at=at,
        artifact_sha256=artifact,
    )


def _complete_zero_alerts(ledger, acquisition, *, at, artifact):
    return ledger.record_terminal(
        acquisition_id=acquisition.acquisition_id,
        status="complete_zero_alerts",
        terminal_at=at,
        artifact_sha256=artifact,
    )


def test_same_day_distinct_datatakes_are_distinct_acquisitions_and_observations():
    first, second = _two_same_day_acquisitions()

    assert first.observed_on == second.observed_on == "2026-04-07"
    assert first.datatake_id != second.datatake_id
    assert first.acquisition_id != second.acquisition_id

    first_observation = _observation(first)
    second_observation = _observation(second)
    assert first_observation.observation_id != second_observation.observation_id
    assert first_observation.acquisition_id == first.acquisition_id
    assert second_observation.acquisition_id == second.acquisition_id


def test_acquisition_scene_order_is_invariant_but_duplicates_fail_closed():
    expected = _acquisition(
        datatake_id="GS2A_20260407T131241_055725_N05.11",
        scene_ids=("scene-b", "scene-a"),
    )
    reordered = _acquisition(
        datatake_id="GS2A_20260407T131241_055725_N05.11",
        scene_ids=("scene-a", "scene-b"),
    )

    assert reordered == expected
    assert expected.scene_ids == ("scene-a", "scene-b")
    with pytest.raises(ValueError, match="duplicates"):
        _acquisition(
            datatake_id="GS2A_20260407T131241_055725_N05.11",
            scene_ids=("scene-a", "scene-a"),
        )


def test_timestamp_is_canonical_utc_and_acquisitions_order_by_timestamp_then_id():
    shifted = datetime(
        2026,
        4,
        7,
        10,
        12,
        41,
        120000,
        tzinfo=timezone(timedelta(hours=-3)),
    )
    assert normalize_utc_timestamp(shifted, label="timestamp") == (
        "2026-04-07T13:12:41.12Z"
    )
    with pytest.raises(ValueError, match="explicit RFC 3339 UTC"):
        normalize_utc_timestamp("2026-04-07T10:12:41-03:00", label="timestamp")
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_utc_timestamp(datetime(2026, 4, 7, 13, 12, 41), label="timestamp")

    early = _acquisition(datatake_id="early", timestamp="2026-04-07T12:00:00Z")
    tied_a = _acquisition(datatake_id="tie-a", timestamp="2026-04-07T13:00:00Z")
    tied_b = _acquisition(datatake_id="tie-b", timestamp="2026-04-07T13:00:00Z")
    ordered = sorted([tied_b, early, tied_a], key=acquisition_order_key)

    assert ordered[0] == early
    assert [item.acquisition_id for item in ordered[1:]] == sorted(
        [tied_a.acquisition_id, tied_b.acquisition_id]
    )
    ledger_order = [
        item.acquisition_id for item in _ledger(reversed(ordered)).acquisitions
    ]
    assert ledger_order == [
        item.acquisition_id for item in ordered
    ]


def test_observation_identity_binds_acquisition_geometry_algorithm_and_baseline():
    acquisition, second_acquisition = _two_same_day_acquisitions()
    observation = _observation(acquisition)
    canonical_geometry, geometry_sha256 = canonical_geometry_sha256(
        observation.to_dict()["geometry"]
    )

    assert observation.to_dict()["geometry"] == canonical_geometry
    assert observation.observation_id == observation_id_v2(
        acquisition.acquisition_id,
        geometry_sha256,
        ALGORITHM_VERSION,
        BASELINE_VERSION,
    )
    assert _observation(second_acquisition).observation_id != observation.observation_id
    assert _observation(acquisition, x_offset=0.2).observation_id != (
        observation.observation_id
    )
    assert observation_id_v2(
        acquisition.acquisition_id,
        geometry_sha256,
        "2.0.1",
        BASELINE_VERSION,
    ) != observation.observation_id
    assert observation_id_v2(
        acquisition.acquisition_id,
        geometry_sha256,
        ALGORITHM_VERSION,
        "2.0.1",
    ) != observation.observation_id


@pytest.mark.parametrize("schema_version", ["1.0.0", "3.0.0", None])
def test_v2_deserializers_refuse_non_v2_schema_versions(schema_version):
    acquisition = _two_same_day_acquisitions()[0]
    acquisition_record = acquisition.to_dict()
    acquisition_record["schema_version"] = schema_version
    with pytest.raises(IdentityMajorError):
        AcquisitionV2.from_dict(acquisition_record)

    observation_record = _observation(acquisition).to_dict()
    observation_record["schema_version"] = schema_version
    with pytest.raises(IdentityMajorError):
        ObservationV2.from_dict(observation_record, acquisition=acquisition)


def test_v2_runtime_helpers_refuse_v1_identity_references():
    v1_acquisition_id = "acq-v1-" + "e" * 64

    with pytest.raises(IdentityMajorError):
        observation_id_v2(
            v1_acquisition_id,
            "f" * 64,
            ALGORITHM_VERSION,
            BASELINE_VERSION,
        )

    acquisition = _acquisition(datatake_id="v2-only")
    with pytest.raises(IdentityMajorError):
        _ledger([acquisition]).record_terminal(
            acquisition_id=v1_acquisition_id,
            status="complete_zero_alerts",
            terminal_at="2026-04-07T14:00:00Z",
            artifact_sha256=ARTIFACT_A,
        )


def test_ledger_keeps_two_same_day_terminal_rows_and_blocks_incomplete_date():
    first, second = _two_same_day_acquisitions()
    ledger = _ledger([second, first])

    _complete_zero_alerts(
        ledger,
        first,
        at="2026-04-07T14:00:00Z",
        artifact=ARTIFACT_A,
    )
    assert not ledger.is_date_terminal("2026-04-07")
    assert ledger.daily_summaries() == ()
    with pytest.raises(IncompleteDateError):
        ledger.daily_summary("2026-04-07")
    with pytest.raises(IncompleteDateError):
        ledger.to_dict()

    _complete_zero_alerts(
        ledger,
        second,
        at="2026-04-07T14:10:00Z",
        artifact=ARTIFACT_B,
    )
    assert ledger.is_date_terminal("2026-04-07")
    assert [row["acquisition_id"] for row in ledger.terminal_rows] == [
        first.acquisition_id,
        second.acquisition_id,
    ]
    assert ledger.daily_summary("2026-04-07")["persistence_finalization_allowed"]


def test_exact_terminal_retry_is_no_op_and_keeps_ledger_bytes_identical():
    acquisition = _acquisition(datatake_id="retry")
    observation = _observation(acquisition)
    ledger = _ledger([acquisition])
    arguments = {
        "acquisition_id": acquisition.acquisition_id,
        "status": "complete_with_alerts",
        "observation_ids": [observation.observation_id],
        "terminal_at": "2026-04-07T14:00:00Z",
        "artifact_sha256": ARTIFACT_A,
    }

    first = ledger.record_terminal(**arguments)
    before = ledger.to_bytes()
    retry = ledger.record_terminal(**arguments)

    assert not first.no_op
    assert retry.no_op
    assert retry.row == first.row
    assert ledger.to_bytes() == before


def test_conflicting_retry_fails_closed_and_keeps_ledger_bytes_identical():
    acquisition = _acquisition(datatake_id="conflict")
    ledger = _ledger([acquisition])
    _complete_zero_alerts(
        ledger,
        acquisition,
        at="2026-04-07T14:00:00Z",
        artifact=ARTIFACT_A,
    )
    before = ledger.to_bytes()

    with pytest.raises(ConflictingTerminalRowError):
        _complete_zero_alerts(
            ledger,
            acquisition,
            at="2026-04-07T14:01:00Z",
            artifact=ARTIFACT_A,
        )

    assert ledger.to_bytes() == before


def test_unexpected_or_late_acquisition_requires_a_new_manifest_bound_ledger():
    expected = _acquisition(datatake_id="expected", timestamp="2026-04-07T12:00:00Z")
    late = _acquisition(datatake_id="late", timestamp="2026-04-07T18:00:00Z")
    ledger = _ledger([expected])
    _complete_zero_alerts(
        ledger,
        expected,
        at="2026-04-07T14:00:00Z",
        artifact=ARTIFACT_A,
    )
    before = ledger.to_bytes()

    with pytest.raises(UnexpectedAcquisitionError, match="rebuild required"):
        _complete_zero_alerts(
            ledger,
            late,
            at="2026-04-07T19:00:00Z",
            artifact=ARTIFACT_B,
        )

    assert ledger.to_bytes() == before
    rebuilt = _ledger([late, expected])
    assert [item.acquisition_id for item in rebuilt.acquisitions] == [
        expected.acquisition_id,
        late.acquisition_id,
    ]
    assert rebuilt.ledger_id != ledger.ledger_id
    with pytest.raises(IncompleteDateError):
        rebuilt.daily_summary("2026-04-07")

    _complete_zero_alerts(
        rebuilt,
        expected,
        at="2026-04-07T14:00:00Z",
        artifact=ARTIFACT_A,
    )
    assert not rebuilt.is_date_terminal("2026-04-07")
    _complete_zero_alerts(
        rebuilt,
        late,
        at="2026-04-07T19:00:00Z",
        artifact=ARTIFACT_B,
    )
    assert rebuilt.daily_summary("2026-04-07")["terminal_acquisition_ids"] == (
        sorted([expected.acquisition_id, late.acquisition_id])
    )


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_all_seven_terminal_statuses_have_explicit_semantics(status):
    acquisition = _acquisition(datatake_id=status)
    ledger = _ledger([acquisition])
    observation = _observation(acquisition)
    is_success = status in {"complete_with_alerts", "complete_zero_alerts"}
    arguments = {
        "acquisition_id": acquisition.acquisition_id,
        "status": status,
        "observation_ids": (
            [observation.observation_id] if status == "complete_with_alerts" else []
        ),
        "reason": None if is_success else {"code": status, "message": "explicit"},
        "terminal_at": "2026-04-07T14:00:00Z",
        "artifact_sha256": ARTIFACT_A if is_success else None,
    }

    result = ledger.record_terminal(**arguments)
    row = result.row
    assert row["reason"] == arguments["reason"]
    assert row["output"]["observation_count"] == len(arguments["observation_ids"])
    assert row["output"]["observation_ids"] == arguments["observation_ids"]
    assert row["output"]["artifact_sha256"] == arguments["artifact_sha256"]
    summary = ledger.daily_summary(acquisition.observed_on)
    assert summary["status_counts"] == {
        candidate: int(candidate == status) for candidate in TERMINAL_STATUSES
    }


def test_terminal_status_output_and_reason_combinations_fail_closed():
    acquisition = _acquisition(datatake_id="invalid-terminal-semantics")
    observation = _observation(acquisition)

    with pytest.raises(ValueError, match="requires at least one observation"):
        _ledger([acquisition]).record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status="complete_with_alerts",
            terminal_at="2026-04-07T14:00:00Z",
            artifact_sha256=ARTIFACT_A,
        )
    with pytest.raises(ValueError, match="cannot carry observation IDs"):
        _ledger([acquisition]).record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status="rejected_quality",
            observation_ids=[observation.observation_id],
            reason={"code": "quality", "message": "explicit"},
            terminal_at="2026-04-07T14:00:00Z",
        )
    with pytest.raises(ValueError, match="requires reason"):
        _ledger([acquisition]).record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status="failed_processing",
            terminal_at="2026-04-07T14:00:00Z",
        )
    with pytest.raises(ValueError, match="cannot carry"):
        _ledger([acquisition]).record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status="complete_zero_alerts",
            reason={"code": "not_allowed", "message": "not allowed"},
            terminal_at="2026-04-07T14:00:00Z",
            artifact_sha256=ARTIFACT_A,
        )


def test_zero_alerts_are_explicit_and_not_confused_with_rejection_or_missing_output():
    acquisition = _acquisition(datatake_id="zero")
    ledger = _ledger([acquisition])
    result = _complete_zero_alerts(
        ledger,
        acquisition,
        at="2026-04-07T14:00:00Z",
        artifact=ARTIFACT_A,
    )

    assert result.row["status"] == "complete_zero_alerts"
    assert result.row["reason"] is None
    assert result.row["output"] == {
        "observation_count": 0,
        "observation_ids": [],
        "artifact_sha256": ARTIFACT_A,
    }
    with pytest.raises(ValueError, match="explicit artifact checksum"):
        _ledger([acquisition]).record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status="complete_zero_alerts",
            terminal_at="2026-04-07T14:00:00Z",
        )


def test_daily_summary_reconciles_same_day_rows_and_complete_ledger_validates_schema():
    first, second = _two_same_day_acquisitions()
    first_observation = _observation(first)
    ledger = _ledger([second, first])
    _complete_with_alerts(
        ledger,
        first,
        first_observation,
        at="2026-04-07T14:00:00Z",
        artifact=ARTIFACT_A,
    )
    _complete_zero_alerts(
        ledger,
        second,
        at="2026-04-07T14:10:00Z",
        artifact=ARTIFACT_B,
    )

    summary = ledger.daily_summary("2026-04-07")
    rows = list(ledger.terminal_rows)
    assert summary["expected_acquisition_ids"] == sorted(
        [first.acquisition_id, second.acquisition_id]
    )
    assert summary["terminal_acquisition_ids"] == summary[
        "expected_acquisition_ids"
    ]
    assert summary["terminal_rows_sha256"] == canonical_sha256(rows)
    assert summary["observation_ids"] == [first_observation.observation_id]
    assert summary["status_counts"] == {
        "complete_with_alerts": 1,
        "complete_zero_alerts": 1,
        "rejected_low_coverage": 0,
        "rejected_quality": 0,
        "failed_download": 0,
        "failed_missing_input": 0,
        "failed_processing": 0,
    }
    summary_without_digest = deepcopy(summary)
    del summary_without_digest["daily_summary_sha256"]
    assert summary["daily_summary_sha256"] == canonical_sha256(
        summary_without_digest
    )

    payload = ledger.to_dict()
    assert payload["ledger_id"].startswith("pl-v2-")
    assert payload["terminal_rows"] == rows
    assert payload["daily_summaries"] == [summary]
    assert payload["summary"]["expected_acquisition_count"] == 2
    assert payload["summary"]["terminal_acquisition_count"] == 2
    assert payload["summary"]["utc_date_count"] == 1
    assert payload["summary"]["terminal_utc_date_count"] == 1

    schema = json.loads(LEDGER_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
