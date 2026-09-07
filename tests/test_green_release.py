"""Immutable release identity, the zero-alert distinction, and the release gate.

Roadmap Package 2B.2 bullets 1, 2 and 5 on the release document itself:
identity derived from what the ledger seals, validation before promotion, and
valid zero-alert dates represented explicitly rather than collapsed into "no
data".

No network, no clock, no object store, no producer import.  Every ledger comes
from the producer's committed fixture through the Package 2B.2A ``reseal``
helper, so a test fails for the reason it is named after rather than because a
checksum moved.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from src.publication import green_release as gr
from src.publication import ledger_binding
from src.publication.green_release import (
    ProductObject,
    ReleaseBuildError,
    ReleaseRejected,
    build_release,
    check_green_release,
    classify_date,
    release_identity,
)
from src.publication.ledger_gate import LedgerRejected, check_processing_ledger
from tests.green_release_fixtures import (
    ALERTS,
    FAILED,
    REJECTED,
    ZERO,
    alerting_release_inputs,
    build_ledger,
)

STATE_SHA = "a" * 64
STATE_BYTES = 126_469_137


# ── helpers ──────────────────────────────────────────────────────────────────

def objects_for(document, bodies, *, prefix="alerts"):
    """One acquisition artifact per acquisition whose status seals one."""

    out = []
    for row in document["terminal_rows"]:
        body = bodies.get(row["acquisition_id"])
        if body is None:
            continue
        out.append(
            ProductObject(
                path=f"{prefix}/{row['observed_on']}/{row['acquisition_id'][7:19]}.geojson",
                body=body,
                content_type="application/geo+json",
                observed_on=row["observed_on"],
                acquisition_id=row["acquisition_id"],
            )
        )
    return out


def release_for(spec, **kwargs):
    document, bodies = build_ledger(spec)
    acceptance = check_processing_ledger(document)
    objects = kwargs.pop("objects", None)
    if objects is None:
        objects = objects_for(document, bodies)
    release = build_release(
        acceptance,
        document,
        objects,
        persistence_state_sha256=kwargs.pop("state_sha", STATE_SHA),
        persistence_state_bytes=kwargs.pop("state_bytes", STATE_BYTES),
    )
    assert not kwargs, f"unused arguments {sorted(kwargs)}"
    return release, document, bodies, acceptance


def codes(raised) -> set[str]:
    return set(raised.value.codes)


# ── the identity is derived from the ledger, not minted ──────────────────────

def test_the_release_identity_is_a_function_of_the_ledger_alone():
    """Same ledger, same identity — twice, with nothing else held constant."""

    document, bodies = alerting_release_inputs()
    acceptance = check_processing_ledger(document)
    first = release_identity(acceptance)
    second = release_identity(check_processing_ledger(deepcopy(document)))
    assert first == second
    assert first[0] == gr.RELEASE_ID_PREFIX + first[1]


def test_two_identical_builds_are_byte_identical():
    """The property republication rests on: the manifest carries no clock."""

    release, document, bodies, acceptance = release_for({"2026-04-07": [ALERTS]})
    again = build_release(
        acceptance,
        document,
        objects_for(document, bodies),
        persistence_state_sha256=STATE_SHA,
        persistence_state_bytes=STATE_BYTES,
    )
    assert gr.release_bytes(release) == gr.release_bytes(again)


def test_the_manifest_carries_no_publication_provenance():
    """Provenance belongs to the pointer; here it would break reproducibility."""

    release, *_ = release_for({"2026-04-07": [ALERTS]})
    text = json.dumps(release)
    for forbidden in ("built_utc", "run_id", "run_url", "actor", "workflow"):
        assert forbidden not in text


def test_any_change_to_the_ledger_moves_the_release_to_a_new_prefix():
    """Immutability by construction: a changed ledger cannot reuse the prefix."""

    document, _ = alerting_release_inputs()
    first = release_identity(check_processing_ledger(document))[0]

    changed = deepcopy(document)
    changed["terminal_rows"][0]["terminal_at"] = "2026-04-07T19:00:00Z"
    from tests.test_ledger_completeness_gate import reseal

    changed = reseal(changed, rederive_summaries=True)
    second = release_identity(check_processing_ledger(changed))[0]
    assert first != second
    assert gr.release_prefix(first) != gr.release_prefix(second)


def test_the_release_identity_is_domain_separated():
    """A release id can never collide with an acquisition or ledger id."""

    release, *_ = release_for({"2026-04-07": [ALERTS]})
    primitives = ledger_binding.identity_primitives()
    assert release["release_id"].startswith(gr.RELEASE_ID_PREFIX)
    assert not release["release_id"].startswith(primitives["acquisition_id_prefix"])
    assert not release["release_id"].startswith(primitives["ledger_id_prefix"])
    assert release["identity_inputs_sha256"] != release["ledger"]["document_sha256"]


# ── the zero-alert distinction ───────────────────────────────────────────────

def counts(**kwargs):
    return {status: kwargs.get(status, 0) for status in ledger_binding.pinned_terminal_statuses()}


def test_an_observed_quiet_day_is_not_no_data():
    """The distinction Package 2B.2 bullet 5 exists to preserve."""

    quiet = classify_date(counts(complete_zero_alerts=2))
    blind = classify_date(counts(rejected_low_coverage=2))
    assert quiet.alert_state == "zero_alerts"
    assert quiet.coverage == "complete"
    assert blind.alert_state == "no_valid_coverage"
    assert blind.coverage == "none"
    assert quiet.alert_state != blind.alert_state


def test_a_partly_observed_quiet_day_is_neither_of_the_two():
    """A clear sky over half the extent is not a fully observed quiet day."""

    mixed = classify_date(counts(complete_zero_alerts=1, rejected_quality=1))
    assert (mixed.alert_state, mixed.coverage) == ("zero_alerts", "partial")


def test_alerts_win_over_every_other_status_on_the_same_date():
    mixed = classify_date(
        counts(complete_with_alerts=1, complete_zero_alerts=1, failed_download=3)
    )
    assert mixed.alert_state == "alerts"
    assert mixed.coverage == "partial"
    assert (mixed.usable_acquisition_count, mixed.unusable_acquisition_count) == (2, 3)


@pytest.mark.parametrize("status", ledger_binding.pinned_terminal_statuses())
def test_classification_is_total_over_the_contract_vocabulary(status):
    """Every terminal status the contract admits maps to exactly one pair."""

    result = classify_date(counts(**{status: 1}))
    assert result.alert_state in {"alerts", "zero_alerts", "no_valid_coverage"}
    assert result.coverage in {"complete", "partial", "none"}
    assert result.usable_acquisition_count + result.unusable_acquisition_count == 1


def test_no_valid_coverage_and_none_coverage_are_the_same_fact():
    """The two axes overlap in exactly one place, and it must not drift."""

    for spec in (
        counts(complete_with_alerts=1),
        counts(complete_zero_alerts=1),
        counts(rejected_quality=2),
        counts(complete_zero_alerts=1, failed_processing=1),
        counts(complete_with_alerts=1, rejected_low_coverage=1),
    ):
        result = classify_date(spec)
        assert (result.alert_state == "no_valid_coverage") == (result.coverage == "none")


def test_the_status_semantics_come_out_of_the_pinned_schema():
    """Not a second vocabulary: both sets are read back out of the contract."""

    semantics = ledger_binding.pinned_status_semantics()
    assert semantics["artifact_sealing"] == {ALERTS, ZERO}
    assert semantics["alert_bearing"] == {ALERTS}
    assert semantics["zero_alert"] == {ZERO}
    assert semantics["zero_alert"] <= semantics["artifact_sealing"]


def test_a_schema_without_per_status_conditionals_is_refused(monkeypatch):
    """A silently empty derivation would make every acquisition look unusable.

    Unreachable while the pin stands — identical bytes yield an identical
    derivation — so it is exercised by injecting a restructured schema, which
    is what a future re-pin could bring.
    """

    schema = deepcopy(ledger_binding.pinned_schema())
    del schema["$defs"]["terminal_row"]["allOf"]
    monkeypatch.setattr(ledger_binding, "pinned_schema", lambda: schema)
    with pytest.raises(ledger_binding.ContractBindingError, match="per-status"):
        ledger_binding.pinned_status_semantics()


def test_an_optional_checksum_does_not_count_as_a_seal(monkeypatch):
    """`oneOf` with null is how the schema marks a checksum optional."""

    schema = deepcopy(ledger_binding.pinned_schema())
    branch = schema["$defs"]["terminal_row"]["allOf"][1]
    branch["then"]["properties"]["output"]["properties"]["artifact_sha256"] = {
        "oneOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]
    }
    monkeypatch.setattr(ledger_binding, "pinned_schema", lambda: schema)
    semantics = ledger_binding.pinned_status_semantics()
    assert semantics["artifact_sealing"] == {ALERTS}
    assert semantics["zero_alert"] == frozenset()


# ── every date the ledger reconciles appears, classified ─────────────────────

def test_a_zero_alert_date_is_published_as_a_date_and_not_omitted():
    release, document, *_ = release_for(
        {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]}
    )
    states = {entry["observed_on"]: entry["alert_state"] for entry in release["dates"]}
    assert states == {"2026-04-07": "alerts", "2026-04-10": "zero_alerts"}
    quiet = next(e for e in release["dates"] if e["observed_on"] == "2026-04-10")
    assert quiet["observation_count"] == 0
    assert quiet["coverage"] == "complete"
    check_green_release(release, document)


def test_a_date_nobody_could_observe_is_published_too():
    release, document, *_ = release_for(
        {"2026-04-07": [ALERTS], "2026-04-10": [REJECTED, FAILED]}
    )
    entry = next(e for e in release["dates"] if e["observed_on"] == "2026-04-10")
    assert entry["alert_state"] == "no_valid_coverage"
    assert entry["coverage"] == "none"
    assert entry["paths"] == []
    assert entry["status_counts"][REJECTED] == 1
    assert entry["status_counts"][FAILED] == 1
    check_green_release(release, document)


def test_a_release_of_only_unobservable_dates_still_validates():
    """Nothing to serve is a valid release; silently publishing nothing is not."""

    release, document, *_ = release_for({"2026-04-07": [REJECTED]})
    check_green_release(release, document)
    assert release["objects"] == []
    assert release["dates"][0]["alert_state"] == "no_valid_coverage"


def test_dropping_a_reconciled_date_is_rejected():
    """The partial-release clause at the date level."""

    release, document, *_ = release_for(
        {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]}
    )
    release["dates"] = [e for e in release["dates"] if e["observed_on"] != "2026-04-10"]
    release["coverage"]["observed_dates"] = ["2026-04-07"]
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "release_dates_do_not_cover_the_ledger" in codes(raised)


def test_relabelling_a_zero_alert_date_as_unobservable_is_rejected():
    """Collapsing the distinction is caught by recomputing it."""

    release, document, *_ = release_for({"2026-04-07": [ZERO]})
    release["dates"][0]["alert_state"] = "no_valid_coverage"
    release["dates"][0]["coverage"] = "none"
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert codes(raised) == {"date_accounting_mismatch"}


def test_a_date_claiming_alerts_must_publish_something():
    release, document, bodies, _ = release_for({"2026-04-07": [ALERTS]})
    release["dates"][0]["paths"] = []
    release["objects"] = []
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "alert_date_publishes_nothing" in codes(raised)


# ── the release gate ─────────────────────────────────────────────────────────

def test_the_producers_own_fixture_yields_an_acceptable_release():
    document, bodies = alerting_release_inputs()
    acceptance = check_processing_ledger(document)
    release = build_release(
        acceptance,
        document,
        objects_for(document, bodies),
        persistence_state_sha256=STATE_SHA,
        persistence_state_bytes=STATE_BYTES,
    )
    accepted, returned = check_green_release(release, document)
    assert accepted is release
    assert returned.ledger_id == document["ledger_id"]


def test_a_sentinel_2c_release_is_representable():
    """The v3 binding's reason, carried through to publication.

    20 of the 70 retained pilot scenes are Sentinel-2C; a publication layer
    bound to v2 could not account for them at all.
    """

    document, bodies = alerting_release_inputs()
    platforms = {item["platform"] for item in document["expected_acquisitions"]}
    assert "S2C" in platforms
    acceptance = check_processing_ledger(document)
    release = build_release(
        acceptance, document, objects_for(document, bodies),
        persistence_state_sha256=STATE_SHA, persistence_state_bytes=STATE_BYTES,
    )
    check_green_release(release, document)


def test_a_release_is_never_validated_without_its_ledger():
    """Composition, not duplication: the ledger gate runs again at promotion."""

    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    broken = deepcopy(document)
    broken["terminal_rows"] = []
    with pytest.raises(LedgerRejected) as raised:
        check_green_release(release, broken)
    assert "schema_invalid" in codes(raised) or "missing_terminal_row" in codes(raised)


def test_a_ledger_from_a_different_run_is_rejected():
    release, _, _, _ = release_for({"2026-04-07": [ALERTS]})
    other_document, _ = build_ledger({"2026-04-07": [ALERTS, ALERTS]})
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, other_document)
    assert "release_identity_mismatch" in codes(raised)
    assert "ledger_block_mismatch" in codes(raised)


def test_a_forged_release_identity_is_rejected():
    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    release["release_id"] = "rel-g1-" + "b" * 64
    release["release_prefix"] = gr.release_prefix(release["release_id"])
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert codes(raised) == {"release_identity_mismatch"}


def test_a_prefix_that_does_not_address_its_release_is_rejected():
    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    release["release_prefix"] = "releases/rel-g1-" + "c" * 64 + "/"
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "release_prefix_mismatch" in codes(raised)


def test_a_wrong_declared_schema_is_refused_rather_than_coerced():
    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    release["schema"] = "araripe.green.release/2"
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert codes(raised) == {"release_schema_mismatch"}


@pytest.mark.parametrize("payload", [None, [], "release", 7])
def test_a_non_object_payload_is_refused(payload):
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(payload, {})
    assert codes(raised) == {"not_a_release_document"}


def test_the_stored_ledger_must_be_the_ledger_that_was_validated():
    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    release["ledger"]["file_sha256"] = "d" * 64
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "ledger_object_mismatch" in codes(raised)


def test_an_artifact_whose_checksum_the_ledger_does_not_seal_is_rejected():
    release, document, bodies, _ = release_for({"2026-04-07": [ALERTS]})
    release["objects"][0]["sha256"] = hashlib.sha256(b"tampered").hexdigest()
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "artifact_checksum_mismatch" in codes(raised)


def test_an_artifact_claimed_for_a_rejected_acquisition_is_refused():
    """`artifact_sha256` is unconstrained for the five failure statuses.

    Requiring it would be the 2026-09-07 mistake; reading it is just as wrong,
    so an object may never claim provenance from an unsealed acquisition
    (``LEDGER_CONTRACT_BINDING_V1.md`` §5, non-requirement 2).
    """

    document, bodies = build_ledger({"2026-04-07": [ALERTS, REJECTED]})
    acceptance = check_processing_ledger(document)
    rejected_row = next(r for r in document["terminal_rows"] if r["status"] == REJECTED)
    with pytest.raises(ReleaseBuildError, match="seals no artifact"):
        build_release(
            acceptance,
            document,
            [
                ProductObject(
                    path="alerts/2026-04-07/forged.geojson",
                    body=b"{}",
                    content_type="application/geo+json",
                    observed_on="2026-04-07",
                    acquisition_id=rejected_row["acquisition_id"],
                )
            ],
            persistence_state_sha256=STATE_SHA,
            persistence_state_bytes=STATE_BYTES,
        )


def test_the_gate_catches_the_same_forgery_in_a_stored_document():
    """The builder's refusal is not the defence; the gate is."""

    document, bodies = build_ledger({"2026-04-07": [ALERTS, REJECTED]})
    acceptance = check_processing_ledger(document)
    release = build_release(
        acceptance, document, objects_for(document, bodies),
        persistence_state_sha256=STATE_SHA, persistence_state_bytes=STATE_BYTES,
    )
    rejected_row = next(r for r in document["terminal_rows"] if r["status"] == REJECTED)
    release["objects"][0]["provenance"]["acquisition_id"] = rejected_row["acquisition_id"]
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "object_claims_an_unsealed_artifact" in codes(raised)


def test_an_object_on_a_date_the_ledger_does_not_reconcile_is_refused():
    document, bodies = build_ledger({"2026-04-07": [ALERTS]})
    acceptance = check_processing_ledger(document)
    with pytest.raises(ReleaseBuildError, match="does not reconcile"):
        build_release(
            acceptance,
            document,
            [
                ProductObject(
                    path="alerts/2026-04-08/stray.geojson",
                    body=b"{}",
                    content_type="application/geo+json",
                    observed_on="2026-04-08",
                )
            ],
            persistence_state_sha256=STATE_SHA,
            persistence_state_bytes=STATE_BYTES,
        )


def test_an_object_the_date_index_does_not_claim_is_rejected():
    release, document, bodies, _ = release_for({"2026-04-07": [ALERTS]})
    release["dates"][0]["paths"] = []
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "object_not_claimed_by_its_date" in codes(raised)


def test_a_date_claiming_an_object_that_is_not_declared_is_rejected():
    release, document, bodies, _ = release_for({"2026-04-07": [ALERTS]})
    release["dates"][0]["paths"].append("alerts/2026-04-07/ghost.geojson")
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "date_claims_an_undeclared_object" in codes(raised)


def test_a_duplicate_object_path_is_refused_at_build_time():
    document, bodies = build_ledger({"2026-04-07": [ALERTS, ALERTS]})
    acceptance = check_processing_ledger(document)
    rows = document["terminal_rows"]
    with pytest.raises(ReleaseBuildError, match="duplicate object path"):
        build_release(
            acceptance,
            document,
            [
                ProductObject(
                    path="alerts/same.geojson",
                    body=bodies[row["acquisition_id"]],
                    content_type="application/geo+json",
                    observed_on=row["observed_on"],
                    acquisition_id=row["acquisition_id"],
                )
                for row in rows
            ],
            persistence_state_sha256=STATE_SHA,
            persistence_state_bytes=STATE_BYTES,
        )


def test_a_date_product_needs_no_acquisition_and_is_accepted():
    document, bodies = build_ledger({"2026-04-07": [ALERTS]})
    acceptance = check_processing_ledger(document)
    objects = objects_for(document, bodies) + [
        ProductObject(
            path="summary/2026-04-07.json",
            body=b'{"alerts":1}',
            content_type="application/json",
            observed_on="2026-04-07",
        )
    ]
    release = build_release(
        acceptance, document, objects,
        persistence_state_sha256=STATE_SHA, persistence_state_bytes=STATE_BYTES,
    )
    kinds = {item["path"]: item["provenance"]["kind"] for item in release["objects"]}
    assert kinds["summary/2026-04-07.json"] == "date_product"
    check_green_release(release, document)


@pytest.mark.parametrize(
    "path",
    ["/absolute.json", "../escape.json", "a//b.json", "trailing/", "a/./b.json", ""],
)
def test_a_path_that_could_escape_the_release_prefix_is_refused(path):
    """The prefix is what makes an object immutable, so nothing may leave it."""

    release, document, bodies, _ = release_for({"2026-04-07": [ALERTS]})
    release["objects"][0]["path"] = path
    release["dates"][0]["paths"] = [path]
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "release_schema_invalid" in codes(raised)


# ── the state watermark ──────────────────────────────────────────────────────

def test_the_watermark_is_derived_from_the_ledger_not_supplied():
    release, document, *_ = release_for(
        {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]}
    )
    assert release["state_watermark"]["finalized_through"] == "2026-04-10"
    assert release["state_watermark"]["finalized_dates"] == ["2026-04-07", "2026-04-10"]


def test_an_overclaimed_watermark_is_rejected():
    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    release["state_watermark"]["finalized_through"] = "2026-04-30"
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    assert "state_watermark_mismatch" in codes(raised)


def test_the_watermark_makes_no_claim_about_the_state_contents():
    """`last_seen` moves backwards, so no monotonicity is asserted about it.

    On 2026-09-07 a validator required `first_seen <= last_seen`, which
    `update_tracks` never promised, and stopped the production pipeline over
    0.10% of rows.  The state's digest is recorded as provenance and nothing
    is derived from it — proven here by publishing two releases whose only
    difference is that digest and requiring both to be accepted.
    """

    document, bodies = build_ledger({"2026-04-07": [ALERTS]})
    acceptance = check_processing_ledger(document)
    for digest, size in (("a" * 64, 1), ("f" * 64, 999_999_999)):
        release = build_release(
            acceptance, document, objects_for(document, bodies),
            persistence_state_sha256=digest, persistence_state_bytes=size,
        )
        check_green_release(release, document)


# ── all findings, not the first one ──────────────────────────────────────────

def test_every_finding_is_reported_and_the_count_comes_first():
    release, document, bodies, _ = release_for({"2026-04-07": [ALERTS, ALERTS]})
    release["release_id"] = "rel-g1-" + "e" * 64
    release["release_prefix"] = "releases/rel-g1-" + "f" * 64 + "/"
    release["ledger"]["algorithm_version"] = "9.9.9"
    release["state_watermark"]["finalized_through"] = "2026-04-30"
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, document)
    message = str(raised.value)
    assert len(raised.value.findings) >= 4
    assert message.startswith("green release rejected — ")
    assert f"{len(raised.value.findings)} finding(s)" in message
    assert {
        "release_identity_mismatch",
        "release_prefix_mismatch",
        "ledger_block_mismatch",
        "state_watermark_mismatch",
    } <= codes(raised)
    for finding in raised.value.findings:
        assert finding.path and finding.code


def test_the_ledger_gates_findings_are_never_merged_into_the_releases():
    """An unacceptable ledger is a different failure from a bad manifest."""

    release, document, *_ = release_for({"2026-04-07": [ALERTS]})
    broken = deepcopy(document)
    broken["schema_version"] = "2.0.0"
    with pytest.raises(LedgerRejected) as raised:
        check_green_release(release, broken)
    assert codes(raised) == {"contract_binding_mismatch"}


def test_canonical_bytes_are_required_of_our_own_documents():
    """Refused for the ledger, required here, and the difference is authorship.

    The ledger's file bytes come from the producer, whose example generator
    pretty-prints (``LEDGER_CONTRACT_BINDING_V1.md`` §5, non-requirement 1).
    These bytes come from this module, so requiring them is requiring what
    their own producer promises.
    """

    release, *_ = release_for({"2026-04-07": [ALERTS]})
    body = gr.release_bytes(release)
    assert body.endswith(b"\n")
    assert json.loads(body) == release
    assert gr.release_bytes(json.loads(body)) == body
    assert body != (json.dumps(release, indent=2) + "\n").encode()
