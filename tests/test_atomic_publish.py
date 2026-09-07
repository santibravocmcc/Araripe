"""Atomic publication: a partial or racing run can never expose a release.

This is the P2B exit-gate clause under test — *a deliberately failed or racing
green run cannot corrupt blue or expose a partial release; a staged test
release can move and roll back its green pointer without a manual data PR or
any production effect* — proved against an in-memory store that enforces R2's
preconditions and refuses an unconditional write.

No network, no clock (``now`` is injected), no credential, no object store.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.publication import atomic_publish as ap
from src.publication import conditional_store as cs
from src.publication.atomic_publish import (
    PromotionRefused,
    ReleaseIncomplete,
    promote,
    publish_release,
    rollback,
    tombstones,
    verify_release,
)
from src.publication.conditional_store import (
    ConditionalStore,
    ObjectStoreError,
    PreconditionFailed,
)
from src.publication.green_release import (
    LEDGER_PATH,
    MANIFEST_PATH,
    POINTER_KEY,
    ProductObject,
    build_release,
    object_key,
    release_bytes,
    sha256_bytes,
)
from src.publication.ledger_gate import check_processing_ledger
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, FAILED, REJECTED, ZERO, build_ledger
from tests.test_green_release import STATE_BYTES, STATE_SHA, objects_for

NOW = datetime(2026, 9, 8, 6, 42, 11, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 11, 6, 5, 0, tzinfo=timezone.utc)
CI = {
    "workflow": "v2 green promotion lane",
    "run_id": "4242",
    "run_url": "https://github.com/santibravocmcc/Araripe/actions/runs/4242",
    "actor": "santibravocmcc",
}


def make_release(spec, *, prefix="alerts", extra=()):
    document, bodies = build_ledger(spec)
    acceptance = check_processing_ledger(document)
    objects = list(objects_for(document, bodies, prefix=prefix)) + list(extra)
    release = build_release(
        acceptance,
        document,
        objects,
        persistence_state_sha256=STATE_SHA,
        persistence_state_bytes=STATE_BYTES,
    )
    return release, document, {item.path: item.body for item in objects}


def fresh_store(**kwargs):
    fake = FakeS3(**kwargs)
    return ConditionalStore(fake, cs.STAGING_BUCKET), fake


def published(spec, *, store=None, fake=None, **kwargs):
    release, document, bodies = make_release(spec, **kwargs)
    if store is None:
        store, fake = fresh_store()
    publish_release(store, release, document, bodies)
    return store, fake, release, document, bodies


def pointer_of(fake):
    return json.loads(fake.body(POINTER_KEY))


# ── publication is write-once and the manifest lands last ────────────────────

def test_every_declared_object_the_ledger_and_the_manifest_are_written():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS, ALERTS]})
    prefix = release["release_prefix"]
    assert fake.keys() == sorted(
        [prefix + LEDGER_PATH, prefix + MANIFEST_PATH]
        + [prefix + item["path"] for item in release["objects"]]
    )


def test_the_manifest_is_written_last():
    """An interrupted prefix must look unfinished, not complete."""

    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    assert fake.writes[-1][0] == release["release_prefix"] + MANIFEST_PATH


def test_publishing_the_same_release_twice_writes_nothing_new():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    before = list(fake.writes)
    report = publish_release(store, release, document, bodies)
    assert fake.writes == before
    assert report.created == ()
    assert len(report.unchanged) == len(before)


def test_a_body_that_disagrees_with_the_manifest_is_refused_before_any_write():
    release, document, bodies = make_release({"2026-04-07": [ALERTS]})
    store, fake = fresh_store()
    path = release["objects"][0]["path"]
    with pytest.raises(ObjectStoreError, match="does not match what the manifest"):
        publish_release(store, release, document, {**bodies, path: b"different"})
    assert fake.writes == []


def test_an_undeclared_body_is_refused():
    release, document, bodies = make_release({"2026-04-07": [ALERTS]})
    store, _ = fresh_store()
    with pytest.raises(ObjectStoreError, match="offered but not declared"):
        publish_release(store, release, document, {**bodies, "stray.json": b"{}"})


def test_a_declared_object_with_no_body_is_refused():
    release, document, bodies = make_release({"2026-04-07": [ALERTS]})
    store, _ = fresh_store()
    short = {k: v for k, v in list(bodies.items())[1:]}
    with pytest.raises(ObjectStoreError, match="declared but not offered"):
        publish_release(store, release, document, short)


def test_two_releases_of_the_same_date_never_share_a_key():
    """Immutability by construction: different ledgers, different prefixes."""

    first, doc_a, bodies_a = make_release({"2026-04-07": [ALERTS]})
    second, doc_b, bodies_b = make_release({"2026-04-07": [ALERTS, ALERTS]})
    store, fake = fresh_store()
    publish_release(store, first, doc_a, bodies_a)
    publish_release(store, second, doc_b, bodies_b)
    assert first["release_id"] != second["release_id"]
    for key in fake.keys():
        assert key.startswith(first["release_prefix"]) or key.startswith(
            second["release_prefix"]
        )


# ── verification re-reads instead of trusting the write ──────────────────────

def test_a_fully_published_release_verifies():
    store, fake, release, *_ = published({"2026-04-07": [ALERTS, ZERO]})
    stored = verify_release(store, release)
    assert len(stored) == len(release["objects"]) + 2


def test_a_missing_object_is_reported_with_its_path():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS, ALERTS]})
    victim = release["objects"][0]["path"]
    del fake.objects[object_key(release["release_id"], victim)]
    with pytest.raises(ReleaseIncomplete) as raised:
        verify_release(store, release)
    assert raised.value.codes == ("release_object_absent",)
    assert raised.value.findings[0].path == victim


def test_a_tampered_object_is_reported_as_a_mismatch():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    key = object_key(release["release_id"], release["objects"][0]["path"])
    fake.objects[key] = (b"replaced by something else", "application/geo+json")
    with pytest.raises(ReleaseIncomplete) as raised:
        verify_release(store, release)
    assert raised.value.codes == ("release_object_mismatch",)


def test_every_missing_object_is_reported_not_just_the_first():
    """Package 2B.1's validator died on the first bad row; this one counts."""

    store, fake, release, document, bodies = published(
        {"2026-04-07": [ALERTS, ALERTS], "2026-04-10": [ALERTS]}
    )
    for item in release["objects"]:
        del fake.objects[object_key(release["release_id"], item["path"])]
    with pytest.raises(ReleaseIncomplete) as raised:
        verify_release(store, release)
    assert len(raised.value.findings) == 3
    assert str(raised.value).startswith("published release rejected — 3 finding(s)")


def test_an_unreadable_object_is_a_finding_not_a_crash():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    key = object_key(release["release_id"], release["objects"][0]["path"])
    stored = fake.objects[key]
    fake.tamper[key] = stored[0][:2]
    with pytest.raises(ReleaseIncomplete) as raised:
        verify_release(store, release)
    assert raised.value.codes == ("release_object_unreadable",)


# ── the pointer moves once, at the end ───────────────────────────────────────

def test_the_first_promotion_creates_the_pointer_at_sequence_one():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    result = promote(store, release, document, now=NOW, promoted_by=CI)
    pointer = pointer_of(fake)
    assert (result.action, result.sequence) == ("promote", 1)
    assert pointer["release_id"] == release["release_id"]
    assert pointer["release_path"] == object_key(release["release_id"], MANIFEST_PATH)
    assert pointer["release_document_sha256"] == sha256_bytes(release_bytes(release))
    assert pointer["supersedes"] is None
    assert pointer["promoted_utc"] == "2026-09-08T06:42:11Z"
    assert pointer["promoted_by"] == CI


def test_a_local_promotion_records_null_provenance_rather_than_omitting_it():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    promote(store, release, document, now=NOW)
    assert pointer_of(fake)["promoted_by"] == {
        "workflow": None, "run_id": None, "run_url": None, "actor": None
    }


def test_promoting_the_live_release_again_changes_nothing():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    promote(store, release, document, now=NOW)
    writes = list(fake.writes)
    result = promote(store, release, document, now=LATER)
    assert result.action == "unchanged"
    assert fake.writes == writes
    assert pointer_of(fake)["promoted_utc"] == "2026-09-08T06:42:11Z"


def test_an_unpublished_release_is_never_promoted():
    """Validation and verification both precede the pointer write."""

    release, document, bodies = make_release({"2026-04-07": [ALERTS]})
    store, fake = fresh_store()
    with pytest.raises(ReleaseIncomplete):
        promote(store, release, document, now=NOW)
    assert POINTER_KEY not in fake.objects


def test_a_partial_publication_leaves_the_last_complete_release_live():
    """Bullet 4, and the clause the P2B gate turns on.

    The first release is promoted; the second is interrupted halfway through
    its own prefix.  The pointer must still name the first release, and every
    object of the first release must still verify.
    """

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    live_before = fake.body(POINTER_KEY)

    second, doc_b, bodies_b = make_release({"2026-04-07": [ALERTS], "2026-04-10": [ALERTS]})
    fake.interrupt_after = len(fake.writes) + 1
    with pytest.raises(ObjectStoreError):
        publish_release(store, second, doc_b, bodies_b)
    fake.interrupt_after = None

    with pytest.raises(ReleaseIncomplete):
        promote(store, second, doc_b, now=LATER)

    assert fake.body(POINTER_KEY) == live_before
    assert pointer_of(fake)["release_id"] == first["release_id"]
    verify_release(store, first)


def test_a_pointer_write_that_loses_the_race_does_not_clobber():
    """The CAS behind the serialized lane: a stale reader must lose.

    The lane gives at most one promotion per repository, so this covers what
    the lane cannot — a local run, a re-dispatch from another ref, or a second
    promoter.
    """

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)

    second, doc_b, bodies_b = make_release({"2026-04-10": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)

    # A racing writer replaces the pointer between our read and our write.
    real_get = fake.get_object
    third, doc_c, bodies_c = make_release({"2026-04-12": [ALERTS]})
    publish_release(store, third, doc_c, bodies_c)

    def racing_get(Bucket, Key):
        response = real_get(Bucket=Bucket, Key=Key)
        if Key == POINTER_KEY and not getattr(racing_get, "fired", False):
            racing_get.fired = True
            promote(store, third, doc_c, now=LATER)
        return response

    fake.get_object = racing_get
    with pytest.raises(PreconditionFailed, match="not retried"):
        promote(store, second, doc_b, now=LATER)
    fake.get_object = real_get
    assert pointer_of(fake)["release_id"] == third["release_id"]


def test_an_older_run_may_not_replace_a_newer_release():
    """Bullet 3 stated as data recency, not write order.

    A replay of an old window is a LATER write of OLDER data, so any recency
    test based on sequence or clock would wave it through.
    """

    store, fake, newer, doc_new, bodies_new = published({"2026-04-10": [ALERTS]})
    promote(store, newer, doc_new, now=NOW)

    older, doc_old, bodies_old = make_release({"2026-04-07": [ALERTS]})
    publish_release(store, older, doc_old, bodies_old)
    with pytest.raises(PromotionRefused) as raised:
        promote(store, older, doc_old, now=LATER)
    assert raised.value.codes == ("coverage_regression",)
    assert "use rollback" in str(raised.value)
    assert pointer_of(fake)["release_id"] == newer["release_id"]


def test_equal_coverage_is_not_a_regression():
    """A re-run of the same window that produced a better release may promote."""

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-07": [ALERTS, ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    result = promote(store, second, doc_b, now=LATER)
    assert (result.action, result.sequence) == ("promote", 2)
    assert pointer_of(fake)["supersedes"]["release_id"] == first["release_id"]


def test_promote_has_no_regression_override():
    """Going backwards is always a named operation, never a flag."""

    import inspect

    assert "allow_regression" not in inspect.signature(promote).parameters
    assert "force" not in inspect.signature(promote).parameters


# ── the pointer fails closed on anything it cannot read ──────────────────────

def test_an_unparseable_pointer_is_never_treated_as_absent():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    fake.objects[POINTER_KEY] = (b"not json at all", "application/json")
    with pytest.raises(ObjectStoreError, match="refusing to treat an unreadable"):
        promote(store, release, document, now=NOW)


def test_a_pointer_from_a_later_contract_is_not_overwritten():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    fake.objects[POINTER_KEY] = (
        json.dumps({"schema": "araripe.green.pointer/2"}).encode(),
        "application/json",
    )
    with pytest.raises(ObjectStoreError, match="does not understand"):
        promote(store, release, document, now=NOW)


def test_a_pointer_that_fails_its_own_schema_is_refused():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    fake.objects[POINTER_KEY] = (
        json.dumps({"schema": "araripe.green.pointer/1", "sequence": 0}).encode(),
        "application/json",
    )
    with pytest.raises(ObjectStoreError, match="does not satisfy"):
        promote(store, release, document, now=NOW)


def test_a_live_release_whose_manifest_moved_stops_the_promotion():
    """Tombstones cannot be computed honestly against an unverifiable release."""

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-10": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)

    live = pointer_of(fake)
    live["release_document_sha256"] = "0" * 64
    fake.objects[POINTER_KEY] = (release_bytes(live), "application/json")
    with pytest.raises(PromotionRefused) as raised:
        promote(store, second, doc_b, now=LATER)
    assert raised.value.codes == ("live_release_unverifiable",)


def test_a_manifest_not_stored_canonically_is_refused_on_load():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    key = object_key(release["release_id"], MANIFEST_PATH)
    fake.objects[key] = (
        (json.dumps(release, indent=2) + "\n").encode(),
        "application/json",
    )
    with pytest.raises(ObjectStoreError, match="canonical encoding"):
        ap.load_published_release(store, release["release_id"])


# ── tombstones: staleness is a relation between two releases ─────────────────

def test_a_path_the_successor_drops_is_tombstoned():
    _, _, first, doc_a, _ = published({"2026-04-07": [ALERTS, ALERTS]})
    second, doc_b, _ = make_release({"2026-04-07": [ALERTS]})
    stones = tombstones(first, second)
    assert {stone["reason"] for stone in stones} == {"absent_from_successor"}
    assert all(stone["superseded_release_id"] == first["release_id"] for stone in stones)
    assert all(stone["key"].startswith(first["release_prefix"]) for stone in stones)


def test_the_same_path_with_different_bytes_is_tombstoned():
    """The case the conditional write, not the identity function, catches.

    A ``date_product`` is computed by the publisher rather than sealed by the
    ledger, so the same ledger with a different renderer yields the same
    release prefix and different bytes at the same logical path.
    """

    def summary(body):
        return ProductObject(
            path="summary/2026-04-07.json",
            body=body,
            content_type="application/json",
            observed_on="2026-04-07",
        )

    first, doc_a, _ = make_release({"2026-04-07": [ALERTS]}, extra=[summary(b'{"v":1}')])
    second, doc_b, _ = make_release({"2026-04-07": [ALERTS]}, extra=[summary(b'{"v":2}')])
    assert first["release_id"] == second["release_id"], (
        "the same ledger must map to the same prefix for this to be the case"
    )
    stones = tombstones(first, second)
    assert [stone["reason"] for stone in stones] == ["superseded_content"]
    assert "replaced by" in stones[0]["detail"]


def test_a_retracted_date_is_never_retired_silently():
    """The scientifically load-bearing case: a replay that withdraws alerts."""

    first, doc_a, _ = make_release({"2026-04-07": [ALERTS]})
    second, doc_b, _ = make_release({"2026-04-07": [REJECTED]})
    stones = tombstones(first, second)
    assert [stone["reason"] for stone in stones] == ["absent_from_successor"]
    assert stones[0]["observed_on"] == "2026-04-07"


def test_a_quiet_day_that_gains_alerts_retires_its_own_claim():
    """The object survives; what it *means* does not.

    `complete_zero_alerts` seals an artifact checksum of its own, so a quiet
    day publishes a real object.  When a later run finds alerts on that date,
    the old object is byte-identical and still correct as bytes — but a
    consumer holding "2026-04-07: zero alerts" is now wrong, and that has to
    be said out loud.
    """

    first, doc_a, _ = make_release({"2026-04-07": [ZERO]})
    second, doc_b, _ = make_release({"2026-04-07": [ZERO, ALERTS]})
    shared = {item["path"] for item in first["objects"]} & {
        item["path"] for item in second["objects"]
    }
    assert shared, "the fixture must share an acquisition for this to be the case"
    stones = tombstones(first, second)
    assert [stone["reason"] for stone in stones] == ["date_reclassified"]
    assert stones[0]["detail"] == "zero_alerts → alerts"


def test_a_reclassified_date_that_published_nothing_is_still_recorded():
    """An unobservable day publishes no bytes, so its claim is on the manifest."""

    first, doc_a, _ = make_release({"2026-04-07": [REJECTED, FAILED]})
    second, doc_b, _ = make_release({"2026-04-07": [REJECTED, ALERTS]})
    assert first["objects"] == []
    stones = tombstones(first, second)
    assert [stone["reason"] for stone in stones] == ["date_reclassified"]
    assert stones[0]["detail"] == "no_valid_coverage → alerts"
    assert stones[0]["key"].endswith(MANIFEST_PATH)


def test_a_retracted_quiet_day_is_tombstoned_by_its_object():
    """The other direction: the successor drops the artifact entirely."""

    first, doc_a, _ = make_release({"2026-04-07": [ZERO]})
    second, doc_b, _ = make_release({"2026-04-07": [REJECTED]})
    stones = tombstones(first, second)
    assert [stone["reason"] for stone in stones] == ["absent_from_successor"]
    assert stones[0]["observed_on"] == "2026-04-07"


def test_an_unchanged_successor_tombstones_nothing():
    first, doc_a, _ = make_release({"2026-04-07": [ALERTS]})
    assert tombstones(first, first) == []


def test_a_promotion_records_its_tombstones_on_the_pointer():
    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS, ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-07": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    result = promote(store, second, doc_b, now=LATER)
    pointer = pointer_of(fake)
    assert result.tombstone_count == len(pointer["tombstones"])
    assert result.tombstone_count >= 1
    assert all(
        stone["superseded_release_id"] == first["release_id"]
        for stone in pointer["tombstones"]
    )


def test_nothing_is_ever_deleted():
    """Retention and lifecycle are Package 2B.3; a tombstone is a record."""

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS, ALERTS]})
    promote(store, first, doc_a, now=NOW)
    before = set(fake.keys())
    second, doc_b, bodies_b = make_release({"2026-04-07": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    promote(store, second, doc_b, now=LATER)
    assert before <= set(fake.keys())
    assert not hasattr(ConditionalStore, "delete")


# ── rollback ─────────────────────────────────────────────────────────────────

def test_the_pointer_can_roll_back_to_the_previous_release():
    """The second half of the P2B gate: move it, and move it back."""

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-10": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    promote(store, second, doc_b, now=LATER)

    result = rollback(store, first["release_id"], now=LATER, promoted_by=CI)
    pointer = pointer_of(fake)
    assert (result.action, result.sequence) == ("rollback", 3)
    assert pointer["release_id"] == first["release_id"]
    assert pointer["rolled_back_from"] == {
        "release_id": second["release_id"],
        "sequence": 2,
    }
    assert pointer["supersedes"]["release_id"] == second["release_id"]


def test_the_sequence_only_ever_increases_including_on_rollback():
    """Write order and data recency are separate axes, deliberately."""

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-10": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    promote(store, second, doc_b, now=LATER)
    rollback(store, first["release_id"], now=LATER)
    pointer = pointer_of(fake)
    assert pointer["sequence"] == 3
    assert pointer["coverage"]["last_observed_on"] == "2026-04-07"


def test_rollback_refuses_a_release_that_is_no_longer_complete():
    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-10": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    promote(store, second, doc_b, now=LATER)

    del fake.objects[object_key(first["release_id"], first["objects"][0]["path"])]
    with pytest.raises(ReleaseIncomplete):
        rollback(store, first["release_id"], now=LATER)
    assert pointer_of(fake)["release_id"] == second["release_id"]


def test_rollback_to_an_unknown_release_fails_closed():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    promote(store, release, document, now=NOW)
    with pytest.raises(ObjectStoreError, match="is absent"):
        rollback(store, "rel-g1-" + "0" * 64, now=LATER)
    assert pointer_of(fake)["release_id"] == release["release_id"]


def test_rollback_with_no_live_pointer_is_refused():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    with pytest.raises(PromotionRefused) as raised:
        rollback(store, release["release_id"], now=NOW)
    assert raised.value.codes == ("no_live_pointer",)


def test_rollback_to_the_live_release_changes_nothing():
    store, fake, release, document, bodies = published({"2026-04-07": [ALERTS]})
    promote(store, release, document, now=NOW)
    writes = list(fake.writes)
    result = rollback(store, release["release_id"], now=LATER)
    assert result.action == "unchanged"
    assert fake.writes == writes


def test_rollback_revalidates_the_target_against_its_stored_ledger():
    """The target is read from the store, never from the caller's memory."""

    store, fake, first, doc_a, bodies_a = published({"2026-04-07": [ALERTS]})
    promote(store, first, doc_a, now=NOW)
    second, doc_b, bodies_b = make_release({"2026-04-10": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    promote(store, second, doc_b, now=LATER)

    key = object_key(first["release_id"], LEDGER_PATH)
    other, _ = build_ledger({"2026-04-07": [ALERTS, ALERTS]})
    fake.objects[key] = (release_bytes(other), "application/json")
    with pytest.raises(Exception) as raised:
        rollback(store, first["release_id"], now=LATER)
    assert raised.type.__name__ in {"ReleaseRejected", "ReleaseIncomplete"}
    assert pointer_of(fake)["release_id"] == second["release_id"]


# ── the whole gate clause, end to end ────────────────────────────────────────

def test_a_staged_release_moves_and_rolls_back_without_touching_anything_else():
    """The P2B clause in one test, with nothing outside the staging bucket."""

    store, fake, first, doc_a, bodies_a = published(
        {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]}
    )
    promote(store, first, doc_a, now=NOW, promoted_by=CI)
    second, doc_b, bodies_b = make_release({"2026-04-13": [ALERTS]})
    publish_release(store, second, doc_b, bodies_b)
    promote(store, second, doc_b, now=LATER, promoted_by=CI)
    rollback(store, first["release_id"], now=LATER, promoted_by=CI)

    assert pointer_of(fake)["release_id"] == first["release_id"]
    assert pointer_of(fake)["sequence"] == 3
    # Every key written lives under the green layout, and nothing else exists.
    for key in fake.keys():
        assert key.startswith("releases/rel-g1-") or key == POINTER_KEY
    assert store.bucket == cs.STAGING_BUCKET
