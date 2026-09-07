"""One terminal row per expected acquisition, and a summary that reconciles.

Roadmap Topic 31 — *record one terminal row per manifest-bound expected
acquisition plus a reconciled daily summary … incomplete runs never replace
the last complete release* — on the publication side (Package 2B.2A).

Every case starts from the producer's own committed ledger and changes exactly
one thing.  ``reseal`` then recomputes each digest the change would otherwise
also invalidate, so a test fails for the reason it is named after rather than
because a checksum moved.  Without that, "missing row" and "bad checksum"
would be indistinguishable and neither would be proven.

There is no network, no clock, no object store and no producer import here.
"""
from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy

import pytest

from src.publication import ledger_binding
from src.publication.canonical_json import canonical_sha256, identity_sha256
from src.publication.ledger_gate import (
    LedgerRejected,
    check_processing_ledger,
)


PRIMITIVES = ledger_binding.identity_primitives()
STATUSES = ledger_binding.pinned_terminal_statuses()


def _utf8_sorted(values):
    return sorted(values, key=lambda value: value.encode("utf-8"))


def _without(mapping, key):
    return {name: value for name, value in mapping.items() if name != key}


def rebuild_acquisition(item: dict, **overrides) -> dict:
    """Apply overrides and recompute the acquisition's own identity."""
    item = {**deepcopy(item), **overrides}
    if "acquisition_timestamp_utc" in overrides:
        item["observed_on"] = item["acquisition_timestamp_utc"][:10]
    item["scene_ids"] = _utf8_sorted(item["scene_ids"])
    digest = identity_sha256(
        PRIMITIVES["acquisition_identity_domain"],
        item["collection_id"],
        item["platform"],
        item["datatake_id"],
        item["acquisition_timestamp_utc"],
        "\n".join(item["scene_ids"]),
        item["monitoring_extent_id"],
        item["composite_method_id"],
        item["grid_id"],
    )
    item["acquisition_id"] = PRIMITIVES["acquisition_id_prefix"] + digest
    item["identity_inputs_sha256"] = digest
    return item


def _derive_summary(document: dict, observed_on: str) -> dict:
    """The producer's ``daily_summary``, for rebuilding a valid fixture."""
    expected = [
        item
        for item in document["expected_acquisitions"]
        if item["observed_on"] == observed_on
    ]
    rows_by_id = {row["acquisition_id"]: row for row in document["terminal_rows"]}
    rows = [
        rows_by_id[item["acquisition_id"]]
        for item in expected
        if item["acquisition_id"] in rows_by_id
    ]
    counter = Counter(row["status"] for row in rows)
    body = {
        "observed_on": observed_on,
        "expected_acquisition_ids": _utf8_sorted(
            item["acquisition_id"] for item in expected
        ),
        "terminal_acquisition_ids": _utf8_sorted(
            row["acquisition_id"] for row in rows
        ),
        "terminal": True,
        "terminal_rows_sha256": canonical_sha256(rows),
        "observation_ids": _utf8_sorted(
            {
                observation_id
                for row in rows
                for observation_id in row["output"]["observation_ids"]
            }
        ),
        "status_counts": {status: counter.get(status, 0) for status in STATUSES},
        "persistence_finalization_allowed": True,
    }
    return {**body, "daily_summary_sha256": canonical_sha256(body)}


def reseal(document: dict, *, rederive_summaries: bool = False) -> dict:
    """Recompute every derived digest, so one mutation shows one failure.

    Summary *content* is deliberately left alone unless asked for: a test that
    corrupts a summary needs its digest resealed but its claim intact, or the
    digest check would mask the reconciliation check.
    """
    document = deepcopy(document)
    for row in document["terminal_rows"]:
        row["terminal_record_sha256"] = canonical_sha256(
            _without(row, "terminal_record_sha256")
        )
    if rederive_summaries:
        document["daily_summaries"] = [
            _derive_summary(document, date)
            for date in sorted(
                {
                    item["observed_on"]
                    for item in document["expected_acquisitions"]
                }
            )
        ]
    else:
        for summary in document["daily_summaries"]:
            summary["daily_summary_sha256"] = canonical_sha256(
                _without(summary, "daily_summary_sha256")
            )

    rows = document["terminal_rows"]
    dates = {item["observed_on"] for item in document["expected_acquisitions"]}
    counter = Counter(row["status"] for row in rows)
    document["summary"] = {
        "expected_acquisition_count": len(document["expected_acquisitions"]),
        "terminal_acquisition_count": len(rows),
        "utc_date_count": len(dates),
        "terminal_utc_date_count": len(document["daily_summaries"]),
        "status_counts": {status: counter.get(status, 0) for status in STATUSES},
    }

    integrity = {
        "expected_acquisitions_sha256": canonical_sha256(
            document["expected_acquisitions"]
        ),
        "terminal_rows_sha256": canonical_sha256(rows),
        "daily_summaries_sha256": canonical_sha256(document["daily_summaries"]),
        "schema_validated": True,
        "manifest_reconciled": True,
        "daily_summaries_reconciled": True,
    }
    digest = identity_sha256(
        PRIMITIVES["ledger_identity_domain"],
        document["run_manifest_id"],
        document["run_manifest_sha256"],
        document["monitoring_extent_id"],
        document["algorithm_version"],
        integrity["expected_acquisitions_sha256"],
    )
    document["ledger_id"] = PRIMITIVES["ledger_id_prefix"] + digest
    document["identity_inputs_sha256"] = digest

    body = _without(document, "integrity")
    body["integrity"] = integrity
    document["integrity"] = {
        **integrity,
        "document_sha256": canonical_sha256(body),
    }
    return document


@pytest.fixture
def ledger() -> dict:
    return json.loads(
        ledger_binding.acceptance_fixture_path().read_text(encoding="utf-8")
    )


def codes_for(document) -> tuple[str, ...]:
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(document)
    return raised.value.codes


# --------------------------------------------------------------------------
# The producer's own output, and the resealing helper itself
# --------------------------------------------------------------------------


def test_the_producers_own_ledger_is_accepted(ledger):
    acceptance = check_processing_ledger(ledger)
    assert acceptance.contract_version == "3.0.0"
    assert acceptance.expected_acquisition_count == 2
    assert acceptance.observed_dates == ("2026-04-07",)
    assert len(acceptance.observation_ids) == 3
    assert acceptance.dates[0].max_terminal_at == "2026-04-07T13:50:00Z"
    assert acceptance.document_sha256 == ledger["integrity"]["document_sha256"]


def test_resealing_an_unchanged_ledger_reproduces_it_byte_for_byte(ledger):
    """Proves the helper is the producer's arithmetic, not an approximation.

    If ``reseal`` were wrong, every mutation test below would pass for the
    wrong reason.
    """
    assert reseal(ledger, rederive_summaries=True) == ledger
    assert reseal(ledger) == ledger


# --------------------------------------------------------------------------
# One terminal row per manifest-bound expected acquisition
# --------------------------------------------------------------------------


def test_a_missing_terminal_row_is_an_incomplete_run(ledger):
    """The gate's whole purpose: an unaccounted acquisition blocks publication."""
    dropped = ledger["terminal_rows"].pop(1)
    codes = codes_for(reseal(ledger))
    assert "missing_terminal_row" in codes
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    detail = str(raised.value)
    assert "1 of 2 manifest-bound expected acquisition(s) have no terminal row" in detail
    assert dropped["acquisition_id"] in detail
    # The date can no longer honestly claim to be terminal either.
    assert "daily_summary_does_not_reconcile" in codes


def test_every_missing_row_is_reported_not_only_the_first(ledger):
    """Package 2B.1's validator died on row one and hid the scale."""
    ledger["terminal_rows"] = []
    ledger["daily_summaries"] = []
    document = reseal(ledger)
    # An empty collection is refused by the pinned schema's minItems, which is
    # the correct layer for it; the message must still name both arrays.
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(document)
    assert set(raised.value.codes) == {"schema_invalid"}
    detail = str(raised.value)
    assert "terminal_rows" in detail and "daily_summaries" in detail


def test_a_duplicated_terminal_row_is_refused(ledger):
    """Replay is a no-op only in the producer; a ledger holds one row each."""
    duplicate = deepcopy(ledger["terminal_rows"][0])
    # Insert in place so chronological order is not the thing that fails.
    ledger["terminal_rows"].insert(1, duplicate)
    codes = codes_for(reseal(ledger))
    assert set(codes) == {"duplicate_terminal_row"}
    assert len(codes) == 2, "both occurrences are reported"


def test_a_conflicting_duplicate_row_is_refused(ledger):
    """Idempotence is not permission to accept conflicting bytes under one ID."""
    conflicting = deepcopy(ledger["terminal_rows"][0])
    conflicting["terminal_at"] = "2026-04-07T18:00:00Z"
    ledger["terminal_rows"].insert(1, conflicting)
    assert "duplicate_terminal_row" in codes_for(reseal(ledger))


def test_a_row_for_an_acquisition_outside_the_manifest_is_refused(ledger):
    """A late datatake needs a new generation, not an extra row."""
    intruder = rebuild_acquisition(
        ledger["expected_acquisitions"][0],
        datatake_id="GS2B_20260407T140000_099999_N05.11",
        acquisition_timestamp_utc="2026-04-07T14:00:00Z",
        platform="S2B",
    )
    row = deepcopy(ledger["terminal_rows"][0])
    row["acquisition_id"] = intruder["acquisition_id"]
    row["acquisition_timestamp_utc"] = intruder["acquisition_timestamp_utc"]
    row["observed_on"] = intruder["observed_on"]
    ledger["terminal_rows"].append(row)

    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert "acquisition_outside_manifest" in raised.value.codes
    assert "requires a new chronological generation" in str(raised.value)


def test_a_non_terminal_status_is_refused_by_the_pinned_contract(ledger):
    """"Terminal" is the pinned schema's seven-value vocabulary, nothing wider.

    The gate does not keep its own copy of that list — it reads it out of the
    pinned schema — so a status outside it is refused at the schema layer and
    the document never reaches the reconciliation rules.
    """
    ledger["terminal_rows"][0]["status"] = "in_progress"
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert set(raised.value.codes) == {"schema_invalid"}
    assert "in_progress" in str(raised.value)
    assert "complete_with_alerts" in str(raised.value)


def test_a_row_that_is_not_terminal_evidence_for_its_acquisition_is_refused(ledger):
    """``terminal_at`` before the acquisition instant is not evidence of it."""
    ledger["terminal_rows"][0]["terminal_at"] = "2026-04-07T10:00:00Z"
    codes = codes_for(reseal(ledger))
    assert "terminal_before_acquisition" in codes


def test_a_row_restating_a_different_acquisition_is_refused(ledger):
    ledger["terminal_rows"][0]["observed_on"] = "2026-04-08"
    assert "terminal_row_acquisition_mismatch" in codes_for(reseal(ledger))


def test_an_observation_count_that_disagrees_with_its_ids_is_refused(ledger):
    """The schema fixes the shape; only the gate can compare the two fields."""
    ledger["terminal_rows"][1]["output"]["observation_count"] = 9
    assert "terminal_row_output_incoherent" in codes_for(reseal(ledger))


def test_unsorted_observation_ids_are_refused(ledger):
    row = ledger["terminal_rows"][1]
    row["output"]["observation_ids"] = list(
        reversed(row["output"]["observation_ids"])
    )
    assert "terminal_row_output_incoherent" in codes_for(reseal(ledger))


def test_rows_out_of_chronological_order_are_refused(ledger):
    ledger["terminal_rows"] = list(reversed(ledger["terminal_rows"]))
    assert "terminal_rows_out_of_order" in codes_for(reseal(ledger))


def test_a_tampered_terminal_record_digest_is_refused(ledger):
    ledger["terminal_rows"][0]["terminal_record_sha256"] = "0" * 64
    assert "terminal_record_digest_mismatch" in codes_for(ledger)


# --------------------------------------------------------------------------
# The derived daily summary must reconcile every same-day row
# --------------------------------------------------------------------------


def test_a_summary_omitting_a_same_day_row_does_not_reconcile(ledger):
    """Two same-day datatakes are two rows; a summary must account for both."""
    summary = ledger["daily_summaries"][0]
    summary["terminal_acquisition_ids"] = summary["terminal_acquisition_ids"][:1]
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert "daily_summary_does_not_reconcile" in raised.value.codes
    assert "terminal_acquisition_ids do not match" in str(raised.value)


def test_a_summary_with_the_wrong_observation_union_does_not_reconcile(ledger):
    summary = ledger["daily_summaries"][0]
    summary["observation_ids"] = summary["observation_ids"][:2]
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert "daily_summary_does_not_reconcile" in raised.value.codes
    assert "3-member union" in str(raised.value)


def test_a_summary_whose_status_counts_do_not_recount_is_refused(ledger):
    summary = ledger["daily_summaries"][0]
    summary["status_counts"]["complete_zero_alerts"] = 1
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert "daily_summary_does_not_reconcile" in raised.value.codes
    assert "status_counts do not recount" in str(raised.value)


def test_a_summary_whose_row_digest_does_not_recompute_is_refused(ledger):
    ledger["daily_summaries"][0]["terminal_rows_sha256"] = "1" * 64
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert "daily_summary_does_not_reconcile" in raised.value.codes
    assert "terminal_rows_sha256 does not recompute" in str(raised.value)


def test_a_summary_claiming_the_wrong_expected_set_is_refused(ledger):
    summary = ledger["daily_summaries"][0]
    summary["expected_acquisition_ids"] = summary["expected_acquisition_ids"][:1]
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    assert "daily_summary_does_not_reconcile" in raised.value.codes
    assert "not the manifest's expected set" in str(raised.value)


def test_a_tampered_summary_digest_is_refused(ledger):
    ledger["daily_summaries"][0]["daily_summary_sha256"] = "2" * 64
    assert "daily_summary_digest_mismatch" in codes_for(ledger)


def test_a_summary_for_a_date_outside_the_manifest_is_refused(ledger):
    stray = deepcopy(ledger["daily_summaries"][0])
    stray["observed_on"] = "2026-04-09"
    ledger["daily_summaries"].append(stray)
    codes = codes_for(reseal(ledger))
    assert "daily_summary_unexpected_date" in codes


def test_a_date_with_no_summary_at_all_is_refused(ledger):
    ledger["daily_summaries"] = []
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    # minItems on the collection is the schema's rule; the point is that an
    # unaccounted date can never pass silently.
    assert set(raised.value.codes) == {"schema_invalid"}


def test_two_summaries_for_one_date_are_refused(ledger):
    ledger["daily_summaries"].append(deepcopy(ledger["daily_summaries"][0]))
    codes = codes_for(reseal(ledger))
    assert "daily_summary_missing" in codes


def test_summaries_out_of_date_order_are_refused(ledger):
    """A second date, correctly built, then deliberately mis-ordered."""
    second = rebuild_acquisition(
        ledger["expected_acquisitions"][0],
        datatake_id="GS2A_20260410T131241_055768_N05.11",
        acquisition_timestamp_utc="2026-04-10T13:12:41Z",
    )
    row = deepcopy(ledger["terminal_rows"][0])
    row.update(
        acquisition_id=second["acquisition_id"],
        acquisition_timestamp_utc=second["acquisition_timestamp_utc"],
        observed_on=second["observed_on"],
        status="complete_zero_alerts",
        terminal_at="2026-04-10T13:50:00Z",
        reason=None,
    )
    row["output"] = {
        "observation_count": 0,
        "observation_ids": [],
        "artifact_sha256": "e" * 64,
    }
    ledger["expected_acquisitions"].append(second)
    ledger["terminal_rows"].append(row)

    document = reseal(ledger, rederive_summaries=True)
    # Built correctly, the two-date ledger is acceptable …
    accepted = check_processing_ledger(document)
    assert accepted.observed_dates == ("2026-04-07", "2026-04-10")
    assert accepted.dates[1].status_counts["complete_zero_alerts"] == 1

    # … and reversing only the summary order is not.
    document["daily_summaries"] = list(reversed(document["daily_summaries"]))
    document = reseal(document)
    assert "daily_summaries_out_of_order" in codes_for(document)


# --------------------------------------------------------------------------
# Manifest binding, identity, order and the ledger's own totals
# --------------------------------------------------------------------------


def test_an_expected_acquisition_bound_to_another_manifest_is_refused(ledger):
    ledger["expected_acquisitions"][1]["run_manifest_sha256"] = "9" * 64
    codes = codes_for(reseal(ledger))
    assert "manifest_binding_mismatch" in codes


def test_an_expected_acquisition_from_another_monitoring_extent_is_refused(ledger):
    ledger["expected_acquisitions"][1]["monitoring_extent_id"] = "other-extent-v1"
    codes = codes_for(reseal(ledger))
    assert "manifest_binding_mismatch" in codes


def test_an_acquisition_whose_id_does_not_recompute_is_refused(ledger):
    """A forged manifest entry: real-looking ID, different inputs."""
    ledger["expected_acquisitions"][1]["collection_id"] = "COPERNICUS/S2_SR"
    codes = codes_for(reseal(ledger))
    assert "acquisition_identity_mismatch" in codes


def test_an_observed_on_that_is_not_the_acquisitions_utc_date_is_refused(ledger):
    ledger["expected_acquisitions"][1]["observed_on"] = "2026-04-06"
    codes = codes_for(reseal(ledger))
    assert "acquisition_identity_mismatch" in codes


def test_expected_acquisitions_out_of_chronological_order_are_refused(ledger):
    ledger["expected_acquisitions"] = list(
        reversed(ledger["expected_acquisitions"])
    )
    assert "expected_acquisitions_out_of_order" in codes_for(reseal(ledger))


def test_chronological_order_is_by_instant_not_by_string(ledger):
    """The producer's documented trap: ``.`` sorts before ``Z``.

    A fractional-second timestamp in the same second as a whole-second one
    sorts *earlier* lexically and *later* chronologically.  A ledger in correct
    chronological order must be accepted, which a string comparison would not
    do.
    """
    first = ledger["expected_acquisitions"][0]
    later = rebuild_acquisition(
        first,
        datatake_id="GS2B_20260407T131241_055726_N05.11",
        platform="S2B",
        acquisition_timestamp_utc="2026-04-07T13:12:41.5Z",
    )
    assert later["acquisition_timestamp_utc"] < first["acquisition_timestamp_utc"], (
        "the fixture must be one where lexical and chronological order differ"
    )
    row = deepcopy(ledger["terminal_rows"][0])
    row.update(
        acquisition_id=later["acquisition_id"],
        acquisition_timestamp_utc=later["acquisition_timestamp_utc"],
        observed_on=later["observed_on"],
        status="rejected_low_coverage",
        terminal_at="2026-04-07T13:55:00Z",
        reason={"code": "low_valid_coverage", "message": "8% valid pixels"},
    )
    row["output"] = {
        "observation_count": 0,
        "observation_ids": [],
        "artifact_sha256": None,
    }
    # Chronological position: after the 13:12:41Z datatake, before 13:22:51Z.
    ledger["expected_acquisitions"].insert(1, later)
    ledger["terminal_rows"].insert(1, row)

    accepted = check_processing_ledger(reseal(ledger, rederive_summaries=True))
    assert accepted.expected_acquisition_count == 3
    assert accepted.dates[0].status_counts["rejected_low_coverage"] == 1


def test_a_duplicate_physical_datatake_key_is_refused(ledger):
    """One physical platform/datatake/timestamp is one acquisition."""
    clone = rebuild_acquisition(
        ledger["expected_acquisitions"][1],
        grid_id="araripe-sentinel2-10m-grid-v1",
    )
    clone["platform"] = ledger["expected_acquisitions"][0]["platform"]
    clone["datatake_id"] = ledger["expected_acquisitions"][0]["datatake_id"]
    clone["acquisition_timestamp_utc"] = ledger["expected_acquisitions"][0][
        "acquisition_timestamp_utc"
    ]
    clone = rebuild_acquisition(clone)
    row = deepcopy(ledger["terminal_rows"][0])
    row.update(
        acquisition_id=clone["acquisition_id"],
        acquisition_timestamp_utc=clone["acquisition_timestamp_utc"],
        observed_on=clone["observed_on"],
    )
    ledger["expected_acquisitions"].insert(1, clone)
    ledger["terminal_rows"].insert(1, row)
    codes = codes_for(reseal(ledger, rederive_summaries=True))
    assert "duplicate_physical_datatake" in codes


def test_a_ledger_id_that_does_not_recompute_is_refused(ledger):
    ledger["ledger_id"] = "pl-v3-" + "3" * 64
    codes = codes_for(ledger)
    assert "ledger_identity_mismatch" in codes


def test_a_ledger_identity_from_another_extent_is_refused(ledger):
    """Identity seals the extent and algorithm, not just the manifest bytes."""
    document = reseal(ledger)
    document["algorithm_version"] = "2.1.0"
    assert "ledger_identity_mismatch" in codes_for(document)


def test_totals_that_do_not_recount_the_collections_are_refused(ledger):
    ledger["summary"]["terminal_acquisition_count"] = 1
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(ledger)
    assert "ledger_summary_does_not_reconcile" in raised.value.codes
    assert "recount is 2" in str(raised.value)


@pytest.mark.parametrize(
    "field",
    [
        "expected_acquisitions_sha256",
        "terminal_rows_sha256",
        "daily_summaries_sha256",
        "document_sha256",
    ],
)
def test_a_tampered_integrity_digest_is_refused(ledger, field):
    ledger["integrity"][field] = "4" * 64
    assert "integrity_digest_mismatch" in codes_for(ledger)


# --------------------------------------------------------------------------
# Reporting behaviour
# --------------------------------------------------------------------------


def test_all_findings_are_reported_together(ledger):
    """Three unrelated defects must produce three findings, not one."""
    ledger["expected_acquisitions"][1]["monitoring_extent_id"] = "other-extent-v1"
    ledger["terminal_rows"][0]["terminal_at"] = "2026-04-07T09:00:00Z"
    document = reseal(ledger)
    # After resealing, so the helper does not recompute this one away.
    document["summary"]["utc_date_count"] = 7
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(document)
    codes = set(raised.value.codes)
    assert {
        "manifest_binding_mismatch",
        "terminal_before_acquisition",
        "ledger_summary_does_not_reconcile",
    } <= codes
    assert len(raised.value.rejections) >= 3
    # Each finding carries the JSON path it applies to.
    assert any(
        rejection.path.startswith("expected_acquisitions/")
        for rejection in raised.value.rejections
    )


def test_a_non_object_payload_is_refused():
    for payload in ([], "ledger", None, 7):
        with pytest.raises(LedgerRejected) as raised:
            check_processing_ledger(payload)
        assert raised.value.codes == ("not_a_ledger_document",)


def test_the_rejection_message_summarizes_before_it_enumerates(ledger):
    """An operator must be able to read scale off the first line."""
    duplicate = deepcopy(ledger["terminal_rows"][0])
    ledger["terminal_rows"].insert(1, duplicate)
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(reseal(ledger))
    first_line = str(raised.value).splitlines()[0]
    assert "2 finding(s)" in first_line
    assert "duplicate_terminal_row×2" in first_line
