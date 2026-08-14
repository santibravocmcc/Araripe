"""Focused Package 2A.6B tests for the manifest-bound composition run."""

import numpy as np
import pytest
from shapely.geometry import Polygon

from src.detection.composition_run_v2 import (
    CompositionRunV2,
    DatatakeRunInputV2,
    ZERO_VALID_REASON_CODE,
)
from src.detection.identity_v2 import create_observation_v2
from src.detection.ledger_v2 import IncompleteDateError
from src.processing.composition_v2 import create_scene_input_v2


MANIFEST_ID = "run-v2-" + "a" * 64
MANIFEST_SHA256 = "b" * 64
COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
EXTENT_ID = "araripe-implementation-rectangle-v1"
GRID_ID = "araripe-sentinel2-20m-grid-v1"
ALGORITHM_VERSION = "2.0.0"
BASELINE_VERSION = "2.0.0"


def _scene(
    scene_id,
    scl_rows,
    *,
    value_base,
    platform="sentinel-2b",
    datatake_id,
    properties=None,
    scl=True,
):
    scl_array = np.asarray(scl_rows, dtype=np.uint8) if scl else None
    shape = np.asarray(scl_rows, dtype=np.uint8).shape
    bands = {
        name: (
            float(value_base)
            + 1000.0 * offset
            + np.arange(shape[0] * shape[1], dtype=np.float64).reshape(shape)
        )
        for offset, name in enumerate(("B08", "B12"))
    }
    if properties is None:
        properties = {"s2:processing_baseline": "05.12"}
    return create_scene_input_v2(
        scene_id=scene_id,
        platform=platform,
        datatake_id=datatake_id,
        properties=properties,
        scl=scl_array,
        bands=bands,
    )


def _good_datatake(platform="sentinel-2a"):
    datatake_id = "GS2A_20260407T131241_055725_N05.12"
    return DatatakeRunInputV2(
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc="2026-04-07T13:12:41Z",
        scenes=(
            _scene(
                "S2A_GOOD_1",
                [[4, 7], [8, 5]],
                value_base=100.0,
                platform=platform,
                datatake_id=datatake_id,
            ),
            _scene(
                "S2A_GOOD_2",
                [[4, 4], [4, 9]],
                value_base=200.0,
                platform=platform,
                datatake_id=datatake_id,
            ),
        ),
    )


def _unreviewed_datatake():
    datatake_id = "GS2B_20260407T132251_041247_N05.10"
    return DatatakeRunInputV2(
        platform="sentinel-2b",
        datatake_id=datatake_id,
        acquisition_timestamp_utc="2026-04-07T13:22:51Z",
        scenes=(
            _scene(
                "S2B_UNREVIEWED_1",
                [[4]],
                value_base=300.0,
                datatake_id=datatake_id,
                properties={"s2:processing_baseline": "05.10"},
            ),
        ),
    )


def _zero_valid_datatake():
    datatake_id = "GS2B_20260409T130500_048999_N05.12"
    return DatatakeRunInputV2(
        platform="sentinel-2b",
        datatake_id=datatake_id,
        acquisition_timestamp_utc="2026-04-09T13:05:00Z",
        scenes=(
            _scene(
                "S2B_ZERO_1",
                [[8, 9], [10, 3]],
                value_base=400.0,
                datatake_id=datatake_id,
            ),
        ),
    )


def _missing_metadata_datatake():
    datatake_id = "GS2B_20260409T131000_049000_N05.12"
    return DatatakeRunInputV2(
        platform="sentinel-2b",
        datatake_id=datatake_id,
        acquisition_timestamp_utc="2026-04-09T13:10:00Z",
        scenes=(
            _scene(
                "S2B_NOMETA_1",
                [[4]],
                value_base=500.0,
                datatake_id=datatake_id,
                properties={},
            ),
        ),
    )


def _run(datatakes=None):
    return CompositionRunV2(
        run_manifest_id=MANIFEST_ID,
        run_manifest_sha256=MANIFEST_SHA256,
        collection_id=COLLECTION_ID,
        monitoring_extent_id=EXTENT_ID,
        grid_id=GRID_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at="2026-04-10T00:00:00Z",
        datatakes=tuple(
            datatakes
            if datatakes is not None
            else (
                _good_datatake(),
                _unreviewed_datatake(),
                _zero_valid_datatake(),
                _missing_metadata_datatake(),
            )
        ),
    )


def _observation(acquisition, *, x_offset=0.0):
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


def _terminal_run():
    run = _run()
    run.compose_all(terminal_at="2026-04-09T18:00:00Z")
    outcomes = {
        outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
    }
    good = outcomes["GS2A_20260407T131241_055725_N05.12"]
    observation = _observation(good.acquisition)
    run.record_complete(
        good,
        observations=[observation],
        terminal_at="2026-04-07T18:00:00Z",
    )
    run.record_zero_valid(
        outcomes["GS2B_20260409T130500_048999_N05.12"],
        terminal_at="2026-04-09T18:00:00Z",
    )
    return run, outcomes, observation


class TestPhysicalAcquisitions:
    def test_same_day_datatakes_become_distinct_expected_acquisitions(self):
        run = _run()
        by_date = {}
        for acquisition in run.ledger.acquisitions:
            by_date.setdefault(acquisition.observed_on, []).append(acquisition)
        assert len(by_date["2026-04-07"]) == 2
        assert len({item.acquisition_id for item in by_date["2026-04-07"]}) == 2
        assert {item.platform for item in by_date["2026-04-07"]} == {
            "S2A",
            "S2B",
        }
        for acquisition in run.ledger.acquisitions:
            assert acquisition.composite_method_id == (
                "coverage-ranked-first-valid-v1"
            )
            assert acquisition.grid_id == GRID_ID

    def test_declared_timestamp_must_match_datatake_sensing_instant(self):
        bad = DatatakeRunInputV2(
            platform="sentinel-2a",
            datatake_id="GS2A_20260407T131241_055725_N05.12",
            acquisition_timestamp_utc="2026-04-07T13:22:51Z",
            scenes=_good_datatake().scenes,
        )
        with pytest.raises(ValueError, match="disagrees"):
            _run([bad])

    def test_foreign_datatake_scene_is_never_composed(self):
        good = _good_datatake()
        foreign = _zero_valid_datatake().scenes[0]
        mixed = DatatakeRunInputV2(
            platform=good.platform,
            datatake_id=good.datatake_id,
            acquisition_timestamp_utc=good.acquisition_timestamp_utc,
            scenes=good.scenes + (foreign,),
        )
        with pytest.raises(ValueError, match="never composed"):
            _run([mixed])

    def test_duplicate_physical_datatake_fails_closed(self):
        first = _good_datatake()
        second = DatatakeRunInputV2(
            platform=first.platform,
            datatake_id=first.datatake_id,
            acquisition_timestamp_utc=first.acquisition_timestamp_utc,
            scenes=(
                _scene(
                    "S2A_GOOD_3",
                    [[4]],
                    value_base=900.0,
                    platform=first.platform,
                    datatake_id=first.datatake_id,
                ),
            ),
        )
        with pytest.raises(ValueError, match="declared more than once"):
            _run([first, second])

    def test_microsecond_retiming_cannot_duplicate_a_physical_datatake(self):
        # The 2A.6A ledger physical key uses the exact timestamp string; a
        # microsecond-different declaration of the same platform/datatake
        # must fail closed here instead of becoming two expected rows.
        first = _good_datatake()
        retimed = DatatakeRunInputV2(
            platform=first.platform,
            datatake_id=first.datatake_id,
            acquisition_timestamp_utc="2026-04-07T13:12:41.000001Z",
            scenes=(
                _scene(
                    "S2A_GOOD_3",
                    [[4]],
                    value_base=900.0,
                    platform=first.platform,
                    datatake_id=first.datatake_id,
                ),
            ),
        )
        with pytest.raises(ValueError, match="declared more than once"):
            _run([first, retimed])

    def test_sentinel_2c_fails_closed_at_the_consumed_contract(self):
        # 20 of the 70 Phase 2A.4 pilot scenes are Sentinel-2C, but the
        # closed acquisition-v2 contract only represents S2A/S2B.  The
        # producer must fail closed rather than silently relabel; widening
        # the platform enum is an explicit owner decision for a later
        # package, not a composition-time fallback.
        datatake_id = "GS2C_20260512T130251_008788_N05.12"
        s2c = DatatakeRunInputV2(
            platform="sentinel-2c",
            datatake_id=datatake_id,
            acquisition_timestamp_utc="2026-05-12T13:02:51Z",
            scenes=(
                _scene(
                    "S2C_PILOT_1",
                    [[4]],
                    value_base=700.0,
                    platform="sentinel-2c",
                    datatake_id=datatake_id,
                ),
            ),
        )
        with pytest.raises(ValueError, match="S2A or S2B"):
            _run([s2c])


class TestComposeAll:
    def test_failures_get_fail_closed_terminal_rows(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome
            for outcome in run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        }
        unreviewed = outcomes["GS2B_20260407T132251_041247_N05.10"]
        assert unreviewed.terminal_row["status"] == "rejected_quality"
        assert unreviewed.terminal_row["reason"]["code"] == (
            "processing-baseline-unreviewed"
        )
        missing = outcomes["GS2B_20260409T131000_049000_N05.12"]
        assert missing.terminal_row["status"] == "failed_missing_input"
        assert missing.terminal_row["reason"]["code"] == (
            "processing-baseline-missing"
        )

    def test_missing_scl_maps_to_failed_missing_input(self):
        datatake_id = "GS2B_20260409T131500_049001_N05.12"
        no_scl = DatatakeRunInputV2(
            platform="sentinel-2b",
            datatake_id=datatake_id,
            acquisition_timestamp_utc="2026-04-09T13:15:00Z",
            scenes=(
                _scene(
                    "S2B_NOSCL_1",
                    [[4]],
                    value_base=600.0,
                    datatake_id=datatake_id,
                    scl=False,
                ),
            ),
        )
        run = _run([no_scl])
        (outcome,) = run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        assert outcome.terminal_row["status"] == "failed_missing_input"
        assert outcome.terminal_row["reason"]["code"] == "scl-missing"

    def test_successful_composites_prove_local_gee_parity(self):
        run = _run()
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        composed = [
            outcome for outcome in run.outcomes if outcome.composite is not None
        ]
        assert len(composed) == 2
        for outcome in composed:
            assert outcome.parity_evidence["parity"] is True
            assert outcome.gee_plan["mosaic_input_order"] == list(
                reversed(outcome.composite.composition_order_scene_ids)
            )
            assert outcome.terminal_row is None

    def test_compose_all_is_idempotent(self):
        run = _run()
        first = run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        second = run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        assert first is second is run.outcomes


class TestTerminalEvidence:
    def test_full_run_reconciles_with_the_manifest_bound_ledger(self):
        run, outcomes, observation = _terminal_run()
        document = run.ledger.to_dict()
        assert document["summary"]["expected_acquisition_count"] == 4
        assert document["summary"]["terminal_acquisition_count"] == 4
        assert document["summary"]["utc_date_count"] == 2
        assert document["summary"]["status_counts"] == {
            "complete_with_alerts": 1,
            "complete_zero_alerts": 0,
            "rejected_low_coverage": 1,
            "rejected_quality": 1,
            "failed_download": 0,
            "failed_missing_input": 1,
            "failed_processing": 0,
        }
        good = outcomes["GS2A_20260407T131241_055725_N05.12"]
        assert good.terminal_row["output"]["artifact_sha256"] == (
            good.composite.composition_evidence_sha256
        )
        assert good.terminal_row["output"]["observation_ids"] == [
            observation.observation_id
        ]
        zero = outcomes["GS2B_20260409T130500_048999_N05.12"]
        assert zero.terminal_row["status"] == "rejected_low_coverage"
        assert zero.terminal_row["reason"]["code"] == ZERO_VALID_REASON_CODE

    def test_daily_summary_waits_for_every_same_day_datatake(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
        }
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        # 2026-04-07 has the good acquisition still non-terminal.
        with pytest.raises(IncompleteDateError):
            run.ledger.daily_summary("2026-04-07")
        run.record_complete(
            outcomes["GS2A_20260407T131241_055725_N05.12"],
            observations=[],
            terminal_at="2026-04-07T18:00:00Z",
        )
        summary = run.ledger.daily_summary("2026-04-07")
        assert summary["persistence_finalization_allowed"] is True
        assert len(summary["expected_acquisition_ids"]) == 2

    def test_complete_zero_alerts_requires_no_observations(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
        }
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        row = run.record_complete(
            outcomes["GS2A_20260407T131241_055725_N05.12"],
            observations=[],
            terminal_at="2026-04-07T18:00:00Z",
        )
        assert row["status"] == "complete_zero_alerts"
        assert row["output"]["observation_count"] == 0

    def test_foreign_or_mismatched_observations_fail_closed(self):
        run, outcomes, observation = _terminal_run()
        zero = outcomes["GS2B_20260409T130500_048999_N05.12"]
        with pytest.raises(ValueError, match="terminal row"):
            run.record_complete(
                zero,
                observations=[observation],
                terminal_at="2026-04-09T19:00:00Z",
            )

    def test_record_complete_rejects_observations_of_other_acquisitions(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
        }
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        good = outcomes["GS2A_20260407T131241_055725_N05.12"]
        other_acquisition = outcomes[
            "GS2B_20260409T130500_048999_N05.12"
        ].acquisition
        foreign = _observation(other_acquisition)
        with pytest.raises(ValueError, match="different acquisition"):
            run.record_complete(
                good,
                observations=[foreign],
                terminal_at="2026-04-07T18:00:00Z",
            )

    def test_record_complete_rejects_algorithm_version_drift(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
        }
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        good = outcomes["GS2A_20260407T131241_055725_N05.12"]
        drifted = create_observation_v2(
            acquisition=good.acquisition,
            geometry=Polygon(
                [(-40.0, -7.0), (-39.9, -7.0), (-39.9, -7.1), (-40.0, -7.1)]
            ),
            algorithm_version="2.0.1",
            baseline_version=BASELINE_VERSION,
            area_ha=1.0,
            created_at="2026-04-07T14:00:00Z",
        )
        with pytest.raises(ValueError, match="algorithm_version"):
            run.record_complete(
                good,
                observations=[drifted],
                terminal_at="2026-04-07T18:00:00Z",
            )

    def test_swapped_composite_cannot_bypass_the_zero_valid_gate(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
        }
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        good = outcomes["GS2A_20260407T131241_055725_N05.12"]
        zero = outcomes["GS2B_20260409T130500_048999_N05.12"]
        zero.composite = good.composite
        with pytest.raises(ValueError, match="does not belong"):
            run.record_complete(
                zero,
                observations=[],
                terminal_at="2026-04-09T19:00:00Z",
            )
        with pytest.raises(ValueError, match="does not belong"):
            run.record_zero_valid(zero, terminal_at="2026-04-09T19:00:00Z")

    def test_foreign_outcome_objects_are_rejected(self):
        first = _run()
        second = _run()
        first.compose_all(terminal_at="2026-04-09T18:00:00Z")
        second.compose_all(terminal_at="2026-04-09T18:00:00Z")
        foreign = {
            outcome.acquisition.datatake_id: outcome
            for outcome in second.outcomes
        }["GS2A_20260407T131241_055725_N05.12"]
        with pytest.raises(ValueError, match="belong to this run"):
            first.record_complete(
                foreign,
                observations=[],
                terminal_at="2026-04-07T18:00:00Z",
            )

    def test_record_zero_valid_only_fits_empty_composites(self):
        run = _run()
        outcomes = {
            outcome.acquisition.datatake_id: outcome for outcome in run.outcomes
        }
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        good = outcomes["GS2A_20260407T131241_055725_N05.12"]
        with pytest.raises(ValueError, match="valid pixels"):
            run.record_zero_valid(good, terminal_at="2026-04-07T18:00:00Z")
        zero = outcomes["GS2B_20260409T130500_048999_N05.12"]
        with pytest.raises(ValueError, match="zero-valid"):
            run.record_complete(
                zero, observations=[], terminal_at="2026-04-09T18:00:00Z"
            )

    def test_date_input_digest_is_stable_across_identical_runs(self):
        first_run, _, first_observation = _terminal_run()
        second_run, _, second_observation = _terminal_run()
        first_digest = first_run.ledger.date_input_digest(
            "2026-04-07", [first_observation.to_dict()]
        )
        second_digest = second_run.ledger.date_input_digest(
            "2026-04-07", [second_observation.to_dict()]
        )
        assert first_digest == second_digest


class TestRunEvidence:
    def test_run_evidence_enumerates_baselines_and_parity(self):
        run, _, _ = _terminal_run()
        evidence = run.run_evidence()
        assert evidence["observed_processing_baselines"] == ["05.10", "05.12"]
        assert evidence["unreviewed_processing_baselines"] == ["05.10"]
        registry = evidence["reviewed_processing_baseline_registry"]
        assert registry["reviewed_values"] == ["05.11", "05.12"]
        by_datatake = {
            item["datatake_id"]: item for item in evidence["acquisitions"]
        }
        good = by_datatake["GS2A_20260407T131241_055725_N05.12"]
        assert good["status"] == "complete_with_alerts"
        assert good["local_gee_parity"] is True
        assert good["composition_evidence_sha256"] is not None
        failed = by_datatake["GS2B_20260409T131000_049000_N05.12"]
        assert failed["status"] == "failed_missing_input"
        assert failed["local_gee_parity"] is None
        assert evidence["ledger_id"] == run.ledger.ledger_id

    def test_run_evidence_is_deterministic(self):
        first, _, _ = _terminal_run()
        second, _, _ = _terminal_run()
        assert first.run_evidence() == second.run_evidence()

    def test_run_evidence_requires_a_fully_terminal_ledger(self):
        run = _run()
        run.compose_all(terminal_at="2026-04-09T18:00:00Z")
        with pytest.raises(IncompleteDateError):
            run.run_evidence()
