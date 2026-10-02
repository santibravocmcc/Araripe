"""The first policy in this project that could ever remove anything.

Package 2B.3: *define conservative lifecycle and rollback retention; run
deletion policies in reviewed dry-run form first.*

Until now nothing could be deleted by construction — ``ConditionalStore`` has
no delete and no unconditional put — so the tests that matter most here are
about what the policy **refuses to decide**, and about the fact that nothing in
this repository can act on a plan at all.

The finding the whole policy is built on is measured, not argued:
``pointers/green/current.json`` is one mutable object and keeps a single step of
context, so "was this release ever live?" stops being answerable one pointer
write after it was.  ``test_a_release_that_was_live_becomes_undecidable_after_one_more_move``
is that fact as a test.

No network, no clock (``as_of`` is injected), no credential, no object store.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from src.publication import delivery_boundary as db
from src.publication import promotion_history as ph
from src.publication import retention as rt
from src.publication.conditional_store import ConditionalStore
from src.publication.green_release import LEDGER_PATH, MANIFEST_PATH, object_key
from src.publication.run_inputs import ReadOnlyStore
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, ZERO
from tests.test_atomic_publish import make_release

NOW = datetime(2026, 9, 7, 23, 0, 0, tzinfo=timezone.utc)

LIVE = "rel-g1-" + "ae" * 32
ROLLED_BACK_FROM = "rel-g1-" + "5f" * 32
NEVER_PROMOTED = "rel-g1-" + "9f" * 32

#: The live pointer as measured in ``araripe-v2-staging`` on 2026-09-07: a
#: rollback at sequence 3, naming the release it came back from and saying
#: nothing at all about the release whose promotion was refused.
POINTER = {
    "schema": "araripe.green.pointer/1",
    "sequence": 3,
    "action": "rollback",
    "release_id": LIVE,
    "supersedes": {"release_id": ROLLED_BACK_FROM, "sequence": 2,
                   "last_observed_on": "2026-04-13"},
    "rolled_back_from": {"release_id": ROLLED_BACK_FROM, "sequence": 2},
}


def key(name, *, age_days=0, size=100):
    return rt.StoredKey(name, size, NOW - timedelta(days=age_days))


def decide(name, *, age_days=0, pointer=POINTER, runs=None, **options):
    return rt.classify(
        key(name, age_days=age_days),
        pointer=pointer,
        runs=runs or {},
        as_of=NOW,
        **options,
    )


# ── the two release cases the 2026-09-07 proofs left in the bucket ───────────


def test_the_live_release_is_retained_because_the_pointer_names_it():
    entry = decide(f"releases/{LIVE}/alerts/2026-04-07/a.geojson")
    assert (entry.action, entry.reason) == (rt.RETAIN, "release_is_live")


def test_a_release_that_was_live_and_was_rolled_back_from_is_retained():
    """``rel-g1-5ffad23a…``: promoted at sequence 2, then rolled back away from.

    It is the natural target of a future rollback, so a policy that deleted
    "releases the pointer does not point at" would delete exactly the one an
    operator would ask for back.
    """

    entry = decide(f"releases/{ROLLED_BACK_FROM}/release.json")
    assert (entry.action, entry.reason) == (rt.RETAIN, "release_is_referenced")


def test_a_release_that_was_never_promoted_is_kept_for_review_not_deleted():
    """``rel-g1-9f1ed344…``: published, then refused for coverage regression.

    Its objects are in the bucket and the pointer never mentioned it.  It is
    still not deleted — but it is reported separately from the two above,
    because the *reason* it is kept is that the store cannot tell.
    """

    entry = decide(f"releases/{NEVER_PROMOTED}/release.json")
    assert (entry.action, entry.reason) == (rt.REVIEW, "promotion_history_not_recorded")


def test_a_release_that_was_live_becomes_undecidable_after_one_more_move():
    """The measurement that shapes the policy, as an executable fact.

    Today ``rel-g1-5ffad23a…`` is distinguishable from ``rel-g1-9f1ed344…``
    only because the last pointer write happened to be a rollback *from* it.
    Promote anything else and the pointer is overwritten: it drops out, and the
    two become the same case.  A promotion history is the prerequisite for ever
    deciding this, and it does not exist.
    """

    before = decide(f"releases/{ROLLED_BACK_FROM}/release.json")
    assert before.action == rt.RETAIN

    next_pointer = {
        "schema": "araripe.green.pointer/1",
        "sequence": 4,
        "action": "promote",
        "release_id": LIVE,
        "supersedes": {"release_id": LIVE, "sequence": 3,
                       "last_observed_on": "2026-04-10"},
    }
    after = decide(f"releases/{ROLLED_BACK_FROM}/release.json", pointer=next_pointer)
    assert (after.action, after.reason) == (rt.REVIEW, "promotion_history_not_recorded")
    assert after.reason == decide(
        f"releases/{NEVER_PROMOTED}/release.json", pointer=next_pointer
    ).reason


@pytest.mark.parametrize("age_days", [0, 31, 400, 10_000])
@pytest.mark.parametrize("release_id", [LIVE, ROLLED_BACK_FROM, NEVER_PROMOTED])
def test_no_release_is_ever_eligible_at_any_age(age_days, release_id):
    """Age does not make a release deletable, and no option does either.

    Every knob the planner has is turned on at once here.  A release becoming
    eligible would mean this package shipped the capability to lose a rollback
    target, which is the one outcome the roadmap bullet forbids.
    """

    entry = decide(
        f"releases/{release_id}/release.json",
        age_days=age_days,
        phase_open=False,
        accept_run_manifest_loss=True,
        run_horizon_days=0,
        verification_horizon_days=0,
    )
    assert entry.action != rt.ELIGIBLE


def test_the_pointer_itself_is_never_a_candidate():
    entry = decide(db.POINTER_KEY, age_days=10_000, phase_open=False)
    assert (entry.action, entry.reason) == (rt.RETAIN, "pointer_is_the_layout")


def test_the_heartbeat_is_never_a_candidate_and_its_root_is_not_blessed():
    entry = decide(db.HEARTBEAT_KEY, age_days=10_000, phase_open=False)
    assert (entry.category, entry.action, entry.reason) == (
        "heartbeat", rt.RETAIN, "heartbeat_is_the_status")
    other = decide("status/green/other.json", age_days=10_000, phase_open=False)
    assert (other.action, other.reason) == (rt.REVIEW, "unclassified_prefix")


def test_referenced_release_ids_is_the_whole_of_what_the_store_remembers():
    assert rt.referenced_release_ids(POINTER) == (LIVE, ROLLED_BACK_FROM)
    assert rt.referenced_release_ids(None) == ()
    assert rt.referenced_release_ids({"release_id": LIVE}) == (LIVE,)
    assert rt.referenced_release_ids(
        {"release_id": LIVE, "supersedes": None, "rolled_back_from": None}
    ) == (LIVE,)


# ── run prefixes: the input, once the product exists ─────────────────────────


LINKED = {"proof-a": rt.RunLink("proof-a", LIVE, True)}


def test_a_run_whose_release_cannot_be_resolved_is_kept_for_review():
    entry = decide("runs/unknown/run.json", age_days=999, runs={})
    assert (entry.action, entry.reason) == (rt.REVIEW, "run_release_link_unresolved")


def test_a_run_whose_release_is_not_complete_is_the_only_copy():
    runs = {"proof-a": rt.RunLink("proof-a", LIVE, False)}
    entry = decide("runs/proof-a/run.json", age_days=999, runs=runs)
    assert (entry.action, entry.reason) == (rt.RETAIN, "run_is_the_only_copy")


def test_a_recent_run_is_retained_by_its_horizon():
    entry = decide("runs/proof-a/run.json", age_days=3, runs=LINKED)
    assert (entry.action, entry.reason) == (rt.RETAIN, "within_run_horizon")
    assert "3 day(s) old" in entry.detail


def test_a_ripe_run_still_waits_for_a_named_decision_about_run_json():
    """A published release holds the ledger and the objects — never ``run.json``.

    And ``GREEN_RELEASE_CONTRACT_V1.md`` §4 non-requirement 2 says a release is
    not obliged to publish every sealed artifact, so "the release exists" does
    not mean "everything here survives elsewhere".  What is lost is stated, and
    accepting it is a flag rather than a default.
    """

    entry = decide("runs/proof-a/run.json", age_days=45, runs=LINKED)
    assert (entry.action, entry.reason) == (rt.REVIEW, "run_manifest_not_recoverable")


def test_a_ripe_run_becomes_eligible_only_once_that_loss_is_accepted():
    entry = decide(
        "runs/proof-a/run.json", age_days=45, runs=LINKED, accept_run_manifest_loss=True
    )
    assert (entry.action, entry.reason) == (rt.ELIGIBLE, "run_superseded_by_release")


def test_the_run_horizon_boundary_is_inclusive_and_measured_in_days():
    ripe = dict(runs=LINKED, accept_run_manifest_loss=True, run_horizon_days=30)
    assert decide("runs/proof-a/x", age_days=29, **ripe).action == rt.RETAIN
    assert decide("runs/proof-a/x", age_days=30, **ripe).action == rt.ELIGIBLE


# ── verification artifacts ───────────────────────────────────────────────────


@pytest.mark.parametrize("root", db.VERIFICATION_ROOTS)
def test_probe_objects_are_evidence_while_the_phase_is_open(root):
    entry = decide(f"{root}run-1/probe.json", age_days=10_000)
    assert (entry.action, entry.reason) == (rt.RETAIN, "phase_evidence_retained")


def test_probe_objects_expire_only_after_the_phase_closes_and_the_horizon_passes():
    fresh = decide("promotion-identity-probe/run-1/p.json", age_days=10, phase_open=False)
    assert (fresh.action, fresh.reason) == (rt.RETAIN, "within_verification_horizon")
    old = decide("promotion-identity-probe/run-1/p.json", age_days=200, phase_open=False)
    assert (old.action, old.reason) == (rt.ELIGIBLE, "verification_artifact_expired")


# ── failing closed ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["scratch/x.json", "site-full/run.geojson", "x", "releases", "runs"]
)
def test_an_unclassified_key_is_kept_and_reported(name):
    entry = decide(name, age_days=10_000, phase_open=False, accept_run_manifest_loss=True)
    assert (entry.action, entry.reason) == (rt.REVIEW, "unclassified_prefix")


@pytest.mark.parametrize("age_days", [0, 400, 10_000])
def test_a_history_record_is_retained_as_the_record_now_that_the_policy_knows_it(age_days):
    """Phase 6, D5: this is the test that marks the extension.

    Until the history was re-proven against real R2 from ``main``
    (``docs/implementation/PHASE_6D_2026-09-27.md``), a record fell to the
    fail-closed rule — ``review``, ``unclassified_prefix``.  It is now named:
    the one evidence the store keeps that a release was live, retained at any
    age with every knob turned on.
    """

    entry = decide(
        ph.history_key(10),
        age_days=age_days,
        phase_open=False,
        accept_run_manifest_loss=True,
        run_horizon_days=0,
        verification_horizon_days=0,
    )
    assert (entry.category, entry.action, entry.reason) == (
        "promotion_history", rt.RETAIN, "promotion_history_is_the_record",
    )


@pytest.mark.parametrize(
    "name",
    [
        "pointers/green/history/10.json",
        "pointers/green/history/0000000000.json",
        "pointers/green/history/notes.txt",
        "pointers/green/history/0000000010.json.bak",
    ],
)
def test_a_stray_key_under_the_history_is_reviewed_not_taken_for_a_record(name):
    entry = decide(name, age_days=10_000, phase_open=False)
    assert (entry.action, entry.reason) == (rt.REVIEW, "history_key_malformed")


def test_another_pointer_key_is_still_unclassified():
    """Only the history prefix was learnt; the rest of ``pointers/`` was not."""

    entry = decide("pointers/green/current.json.bak", age_days=10_000)
    assert (entry.action, entry.reason) == (rt.REVIEW, "unclassified_prefix")


def test_a_key_directly_under_releases_is_reviewed_not_classified_as_a_release():
    entry = decide("releases/stray.json")
    assert (entry.action, entry.reason) == (rt.REVIEW, "release_prefix_malformed")


def test_with_no_pointer_every_release_is_undecidable_and_none_is_eligible():
    plan = rt.build_plan(
        [key(f"releases/{LIVE}/release.json"), key(db.POINTER_KEY)],
        pointer=None,
        as_of=NOW,
    )
    assert plan.live_release_id is None
    assert plan.eligible == ()
    assert plan.review[0].reason == "promotion_history_not_recorded"


# ── the plan document ────────────────────────────────────────────────────────


def test_a_plan_reports_the_scale_before_the_enumeration():
    inventory = [
        key(db.POINTER_KEY),
        key(f"releases/{LIVE}/release.json"),
        key(f"releases/{NEVER_PROMOTED}/release.json"),
        key("runs/proof-a/run.json", age_days=45, size=917),
        key("scratch/x", age_days=1),
    ]
    plan = rt.build_plan(inventory, pointer=POINTER, runs=LINKED, as_of=NOW)
    assert plan.counts() == {rt.RETAIN: 2, rt.REVIEW: 3}
    assert plan.eligible_bytes == 0
    document = rt.plan_document(plan)
    assert document["schema"] == rt.PLAN_SCHEMA
    assert document["live_release_id"] == LIVE
    assert document["referenced_release_ids"] == [LIVE, ROLLED_BACK_FROM]
    assert [entry["key"] for entry in document["objects"]] == sorted(
        item.key for item in inventory
    )
    assert json.dumps(document)  # the plan is serialisable as it stands


def test_the_dry_run_says_in_words_that_nothing_was_deleted():
    text = rt.describe(rt.build_plan([key(db.POINTER_KEY)], pointer=POINTER, as_of=NOW))
    assert "NOTHING WAS DELETED" in text
    assert "ConditionalStore has no delete operation" in text


# ── the capability that does not exist ───────────────────────────────────────


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


@pytest.mark.parametrize(
    "path",
    [
        "src/publication/retention.py",
        "src/publication/delivery_boundary.py",
        "scripts/plan_retention.py",
        "scripts/check_delivery_boundary.py",
    ],
)
def test_no_deletion_is_expressible_from_the_retention_path(path):
    """The plan is a document; nothing here can carry one out.

    Read from the file rather than promised in prose, because "we decided not
    to" is the kind of decision a later edit undoes without noticing.  The one
    place in this repository that may issue a delete is
    ``scripts/probe_readonly_identity.py``, which does it to a key that does
    not exist in order to measure whether the credential holds the permission.
    """

    forbidden = {
        "delete_object",
        "delete_objects",
        "delete_bucket",
        "abort_multipart_upload",
        "put_object",
        "copy_object",
    }
    assert not (_calls(Path(path)) & forbidden)


def test_the_planner_never_names_the_promotion_identity():
    """Planning is a read, so it uses the smaller of the two keys.

    Mirrors ``test_the_candidate_identity_is_not_read_by_the_cli``: the
    separation is only real if each side cannot even name the other's
    credential.
    """

    source = Path("scripts/plan_retention.py").read_text(encoding="utf-8")
    assert "R2_PROMOTION" not in source
    assert "R2_STAGING_ACCESS_KEY_ID" in source


def test_the_planner_is_handed_a_store_that_refuses_every_write():
    store = ReadOnlyStore(FakeS3(), cs.STAGING_BUCKET)
    for call in (
        lambda: store.put_if_absent("k", b"{}", "application/json"),
        lambda: store.put_if_match("k", b"{}", "application/json", "e"),
        lambda: store.put_if_pointer_absent("k", b"{}", "application/json"),
    ):
        with pytest.raises(cs.ObjectStoreError, match="refusing to write"):
            call()


# ── reading an inventory ─────────────────────────────────────────────────────


def test_a_listing_follows_its_continuation_token_to_the_end():
    fake = FakeS3({f"k{index:03d}": (b"x", None) for index in range(250)})
    fake.page_size = 40
    inventory = rt.list_inventory(fake, cs.STAGING_BUCKET)
    assert len(inventory) == 250
    assert {item.key for item in inventory} == set(fake.objects)


def test_a_truncated_listing_with_no_cursor_refuses_to_plan_over_half_a_bucket():
    """An incomplete inventory would classify absent objects as absent.

    The planner's answers are all of the form "this key is/is not referenced",
    so half a listing is not a smaller plan — it is a wrong one.
    """

    fake = FakeS3({f"k{index}": (b"x", None) for index in range(10)})
    fake.page_size = 3
    fake.drop_continuation_token = True
    with pytest.raises(RuntimeError, match="partial inventory"):
        rt.list_inventory(fake, cs.STAGING_BUCKET)


def test_a_run_link_is_recomputed_from_the_ledger_and_not_read_from_anywhere():
    """Nothing in the store records which release a run prefix produced.

    A release manifest carries the *ledger's* ``run_manifest_id``, not the
    ``runs/<run-id>/`` prefix.  The edge is derivable because the release
    identity is a pure function of the ledger, and running the Package 2B.2A
    gate to derive it means a ledger that would be rejected yields no link.
    """

    release, ledger, bodies = make_release({"2026-04-07": [ALERTS], "2026-04-10": [ZERO]})
    release_id = release["release_id"]
    prefix = release["release_prefix"]
    ledger_bytes = json.dumps(ledger).encode()

    objects = {
        f"runs/proof-a/{LEDGER_PATH}": (ledger_bytes, "application/json"),
        f"runs/proof-a/{MANIFEST_PATH}": (b"{}", "application/json"),
        prefix + MANIFEST_PATH: (json.dumps(release).encode(), "application/json"),
        prefix + LEDGER_PATH: (ledger_bytes, "application/json"),
    }
    for item in release["objects"]:
        objects[prefix + item["path"]] = (bodies[item["path"]], item["content_type"])

    fake = FakeS3(objects)
    store = ReadOnlyStore(fake, cs.STAGING_BUCKET)
    inventory = rt.list_inventory(fake, cs.STAGING_BUCKET)
    links = rt.resolve_run_links(store, inventory)
    assert links["proof-a"] == rt.RunLink("proof-a", release_id, True)

    # Remove one declared object and the release stops being complete, so the
    # run prefix becomes the only copy of its inputs again.
    del fake.objects[prefix + release["objects"][0]["path"]]
    incomplete = rt.resolve_run_links(store, rt.list_inventory(fake, cs.STAGING_BUCKET))
    assert incomplete["proof-a"] == rt.RunLink("proof-a", release_id, False)


def test_an_unusable_ledger_resolves_to_no_link_at_all():
    fake = FakeS3(
        {
            f"runs/broken/{LEDGER_PATH}": (b"not json", "application/json"),
            f"runs/absent/{MANIFEST_PATH}": (b"{}", "application/json"),
        }
    )
    store = ReadOnlyStore(fake, cs.STAGING_BUCKET)
    links = rt.resolve_run_links(store, rt.list_inventory(fake, cs.STAGING_BUCKET))
    assert links["broken"] == rt.RunLink("broken", None, False)
    assert links["absent"] == rt.RunLink("absent", None, False)


def test_resolving_run_links_writes_nothing():
    release, ledger, bodies = make_release({"2026-04-07": [ALERTS]})
    fake = FakeS3({f"runs/proof-a/{LEDGER_PATH}": (json.dumps(ledger).encode(), None)})
    store = ReadOnlyStore(fake, cs.STAGING_BUCKET)
    rt.resolve_run_links(store, rt.list_inventory(fake, cs.STAGING_BUCKET))
    assert fake.writes == []


def test_a_plan_over_the_shape_the_real_bucket_had_on_2026_09_07():
    """The reviewed dry-run, reproduced from the measured inventory.

    The real run is recorded in ``docs/operations/GREEN_RETENTION_AND_MIGRATION.md``;
    this pins the *shape* of its answer so a policy change that would have
    proposed deleting one of those 29 objects fails here.
    """

    inventory = [
        key("green-isolation-proof/run-31720230963-1/probe.json", age_days=25),
        key("green-isolation-proof/run-34165026961-1/probe.json"),
        key(db.POINTER_KEY),
        key("promotion-identity-probe/run-34164992026-1/immutable.json"),
        key("promotion-identity-probe/run-34166180531-1/pointer.json"),
        *[key(f"releases/{LIVE}/{name}") for name in
          ("release.json", "ledger.json", "alerts/2026-04-07/a.geojson",
           "alerts/2026-04-10/b.geojson")],
        *[key(f"releases/{ROLLED_BACK_FROM}/{name}") for name in
          ("release.json", "ledger.json", "alerts/2026-04-07/a.geojson",
           "alerts/2026-04-13/c.geojson")],
        *[key(f"releases/{NEVER_PROMOTED}/{name}") for name in
          ("release.json", "ledger.json", "alerts/2026-04-01/d.geojson")],
        *[key(f"runs/proof-{tag}/{name}")
          for tag in "abc" for name in ("run.json", "ledger.json")],
    ]
    runs = {f"proof-{tag}": rt.RunLink(f"proof-{tag}", LIVE, True) for tag in "abc"}
    plan = rt.build_plan(inventory, pointer=POINTER, runs=runs, as_of=NOW)

    assert plan.eligible == ()
    assert plan.by_reason() == {
        "phase_evidence_retained": 4,
        "pointer_is_the_layout": 1,
        "release_is_live": 4,
        "release_is_referenced": 4,
        "promotion_history_not_recorded": 3,
        "within_run_horizon": 6,
    }


# ── Phase 6, D5: the policy reads the promotion history ──────────────────────
#
# ``docs/implementation/PHASE_6C_2026-09-27.md`` §7 is the design, and the order
# was the briefing's: build the history, re-prove it against real R2 from
# ``main``, and only then teach the policy.  The re-proof ran on 2026-09-27
# (``docs/implementation/PHASE_6D_2026-09-27.md``).  What the history makes
# decidable is *why* a release is kept — was it ever live? — never whether it
# may go.


def _entry(sequence, release_id, action="promote", recorded=True):
    return ph.Entry(sequence, action, release_id, "2026-09-27T00:00:00Z", recorded)


def _history(entries, *, predecessor=None, findings=()):
    entries = tuple(entries)
    recorded = [e.sequence for e in entries if e.recorded]
    return ph.History(
        live_sequence=entries[-1].sequence if entries else None,
        first_recorded=min(recorded) if recorded else None,
        entries=entries,
        predecessor=predecessor,
        findings=tuple(findings),
    )


def _rebuilt(*release_ids, actions=None, last_observed_on="2026-04-10"):
    actions = actions or ["promote"] * len(release_ids)
    return tuple(
        rt.ReconstructedEntry(n, action, release_id, last_observed_on, ("doc §1",))
        for n, (release_id, action) in enumerate(zip(release_ids, actions), start=1)
    )


A = "rel-g1-" + "aa" * 32
B = "rel-g1-" + "bb" * 32
C = "rel-g1-" + "cc" * 32
D = "rel-g1-" + "dd" * 32
NEVER = "rel-g1-" + "ee" * 32

#: Pre-history 1-2 (A then B), records 3-4 (C, then back to A): the shape of
#: the real bucket in miniature, where the history begins above sequence 1.
PRE = _rebuilt(A, B)
JOIN = {"release_id": B, "sequence": 2, "last_observed_on": "2026-04-10"}
RECORDED = _history([_entry(3, C), _entry(4, A, "rollback")], predecessor=JOIN)
LIVE_AT_4 = {
    "schema": "araripe.green.pointer/1", "sequence": 4, "action": "rollback",
    "release_id": A,
    "supersedes": {"release_id": C, "sequence": 3, "last_observed_on": "2026-04-13"},
    "rolled_back_from": {"release_id": C, "sequence": 3},
}


def classify_with(release_id, lineage, pointer=LIVE_AT_4, **options):
    return rt.classify(
        key(f"releases/{release_id}/release.json", age_days=options.pop("age_days", 0)),
        pointer=pointer, runs={}, as_of=NOW, lineage=lineage, **options,
    )


def test_a_continuous_account_decides_every_release():
    lineage = rt.build_lineage(RECORDED, PRE)
    assert lineage.continuous, lineage.detail
    assert lineage.history_begins == 3
    got = {r: classify_with(r, lineage).reason for r in (A, B, C, D, NEVER)}
    assert got == {
        A: "release_is_live",
        C: "release_is_referenced",
        B: "release_was_live_per_reconstruction",
        D: "release_never_live",
        NEVER: "release_never_live",
    }
    assert all(classify_with(r, lineage).action == rt.RETAIN for r in got)


def test_a_record_outranks_the_reconstruction_and_names_every_sequence():
    """A release both reconstructed and recorded is reported by the record —
    the store's byte-exact copy — with every sequence it was live at."""

    found = _history(
        [_entry(3, B), _entry(4, C), _entry(5, B, "rollback")], predecessor=JOIN
    )
    lineage = rt.build_lineage(found, PRE)
    pointer = dict(LIVE_AT_4, sequence=5, release_id=D)
    entry = classify_with(B, lineage, pointer=pointer)
    assert (entry.action, entry.reason) == (rt.RETAIN, "release_was_live")
    assert "sequence(s) 3, 5" in entry.detail


def test_a_reconstructed_release_cites_its_sources():
    lineage = rt.build_lineage(RECORDED, PRE)
    entry = classify_with(B, lineage)
    assert "sequence 2 (promote, per doc §1)" in entry.detail
    assert rt.RECONSTRUCTION_PATH in entry.detail


def test_the_releases_that_were_live_stay_decidable_after_any_number_of_moves():
    """The counterpart of ``test_a_release_that_was_live_becomes_undecidable_after_one_more_move``.

    That test is still true of the pointer alone.  With the history, a release
    that drops out of the pointer keeps its reason, however far it drops.
    """

    moves = [_entry(3, C), _entry(4, A, "rollback")]
    for sequence in range(5, 40):
        moves.append(_entry(sequence, D if sequence % 2 else C))
    lineage = rt.build_lineage(_history(moves, predecessor=JOIN), PRE)
    pointer = dict(LIVE_AT_4, sequence=39, release_id=D)
    assert classify_with(A, lineage, pointer=pointer).reason == "release_was_live"
    assert classify_with(B, lineage, pointer=pointer).reason == (
        "release_was_live_per_reconstruction"
    )
    assert classify_with(NEVER, lineage, pointer=pointer).reason == "release_never_live"


# ── the join fails closed ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "found, reconstruction, reason",
    [
        pytest.param(None, PRE, rt.NOT_RECORDED, id="no-history-read"),
        pytest.param(_history([]), PRE, rt.NOT_RECORDED, id="no-pointer-no-record"),
        pytest.param(
            _history(RECORDED.entries, predecessor=JOIN,
                     findings=[ph.Finding("history_gap", "x", "k")]),
            PRE, rt.INCONSISTENT, id="inconsistent-history",
        ),
        pytest.param(RECORDED, None, rt.NOT_CONTINUOUS, id="no-reconstruction"),
        pytest.param(RECORDED, PRE[:1], rt.NOT_CONTINUOUS, id="reconstruction-too-short"),
        pytest.param(RECORDED, _rebuilt(A, B, C), rt.NOT_CONTINUOUS,
                     id="reconstruction-overlaps-the-records"),
        pytest.param(RECORDED, _rebuilt(A, D), rt.NOT_CONTINUOUS,
                     id="reconstruction-ends-at-another-release"),
        pytest.param(RECORDED, _rebuilt(A, B, last_observed_on="2026-04-13"),
                     rt.NOT_CONTINUOUS, id="reconstruction-ends-at-another-coverage"),
        pytest.param(_history(RECORDED.entries, predecessor=dict(JOIN, sequence=1)),
                     PRE, rt.NOT_CONTINUOUS, id="first-record-names-another-sequence"),
        pytest.param(_history(RECORDED.entries, predecessor=None), PRE,
                     rt.NOT_CONTINUOUS, id="first-record-names-nothing"),
        pytest.param(_history([_entry(1, A)]), PRE, rt.NOT_CONTINUOUS,
                     id="history-from-1-yet-a-reconstruction"),
    ],
)
def test_a_release_nothing_names_is_never_called_never_live_on_a_broken_account(
    found, reconstruction, reason
):
    lineage = rt.build_lineage(found, reconstruction)
    assert not lineage.continuous
    assert lineage.reason == reason
    entry = classify_with(NEVER, lineage)
    assert (entry.action, entry.reason) == (rt.REVIEW, reason)
    assert lineage.detail and lineage.detail in entry.detail


def test_an_unjoined_reconstruction_is_not_evidence_even_for_what_it_names():
    """A reconstruction the store contradicts vouches for nothing — B stays in
    review rather than being retained on the reconstruction's word."""

    lineage = rt.build_lineage(RECORDED, _rebuilt(A, D))
    entry = classify_with(B, lineage)
    assert (entry.action, entry.reason) == (rt.REVIEW, rt.NOT_CONTINUOUS)
    assert lineage.reconstructed == {}


def test_a_record_still_retains_its_release_on_an_inconsistent_account():
    """Retaining is the safe direction, and a record is a byte-exact copy the
    reader accepted; what an inconsistent account loses is only the right to
    say *never*."""

    found = _history(
        RECORDED.entries, predecessor=JOIN,
        findings=[ph.Finding("history_gap", "x", "k")],
    )
    lineage = rt.build_lineage(found, PRE)
    assert classify_with(C, lineage, pointer=dict(LIVE_AT_4, supersedes=None,
                                                  rolled_back_from=None)).reason == (
        "release_was_live"
    )
    assert classify_with(B, lineage).action == rt.REVIEW


def test_a_history_that_begins_at_1_needs_no_reconstruction():
    lineage = rt.build_lineage(_history([_entry(1, A), _entry(2, C)]), None)
    assert lineage.continuous
    pointer = dict(LIVE_AT_4, sequence=2, release_id=C, action="promote",
                   supersedes={"release_id": A, "sequence": 1,
                               "last_observed_on": "2026-04-10"},
                   rolled_back_from=None)
    assert classify_with(NEVER, lineage, pointer=pointer).reason == "release_never_live"


def test_a_pending_live_record_still_starts_a_continuous_account():
    """The one record the protocol allows to be missing is the live one; its
    bytes are the live pointer, and the reader returns it as an entry."""

    found = _history([_entry(3, C, recorded=False)], predecessor=JOIN)
    assert found.first_recorded is None
    lineage = rt.build_lineage(found, PRE)
    assert lineage.continuous and lineage.history_begins == 3
    assert classify_with(NEVER, lineage).reason == "release_never_live"
    assert "reconstruction 1-2, records 3-" in classify_with(NEVER, lineage).detail


# ── nothing is eligible, with any lineage ────────────────────────────────────


LINEAGES = {
    "none": None,
    "continuous": rt.build_lineage(RECORDED, PRE),
    "inconsistent": rt.build_lineage(
        _history(RECORDED.entries, predecessor=JOIN,
                 findings=[ph.Finding("history_gap", "x", "k")]), PRE),
    "not-continuous": rt.build_lineage(RECORDED, None),
}


@pytest.mark.parametrize("lineage", LINEAGES.values(), ids=LINEAGES.keys())
@pytest.mark.parametrize("age_days", [0, 400, 10_000])
@pytest.mark.parametrize("release_id", [A, B, C, D, NEVER])
def test_no_release_is_ever_eligible_with_any_lineage(lineage, age_days, release_id):
    """Classifying is not deleting.  The property of 2B.3, extended to every
    state the account can be in, every knob on at once."""

    entry = classify_with(
        release_id, lineage, age_days=age_days, phase_open=False,
        accept_run_manifest_loss=True, run_horizon_days=0, verification_horizon_days=0,
    )
    assert entry.action != rt.ELIGIBLE


# ── the reconstruction document ──────────────────────────────────────────────


def _reconstruction_document(**changes):
    document = {
        "schema": rt.RECONSTRUCTION_SCHEMA,
        "reconstructed": True,
        "entries": [
            {"sequence": 1, "action": "promote", "release_id": A,
             "last_observed_on": "2026-04-10",
             "sources": [{"document": "d.md", "section": "1"}]},
            {"sequence": 2, "action": "rollback", "release_id": B,
             "last_observed_on": "2026-04-10",
             "sources": [{"document": "d.md", "section": "2"}]},
        ],
    }
    for path, value in changes.items():
        if "__" in path:
            index, leaf = path.split("__")
            document["entries"][int(index)][leaf] = value
        else:
            document[path] = value
    return document


def test_a_well_formed_reconstruction_loads():
    entries = rt.load_reconstruction(_reconstruction_document())
    assert [(e.sequence, e.action, e.release_id) for e in entries] == [
        (1, "promote", A), (2, "rollback", B),
    ]
    assert entries[1].sources == ("d.md §2",)


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"schema": "araripe.green.pointer/1"}, id="other-schema"),
        pytest.param({"reconstructed": False}, id="not-declared-reconstructed"),
        pytest.param({"reconstructed": "yes"}, id="declared-loosely"),
        pytest.param({"entries": []}, id="no-entries"),
        pytest.param({"1__sequence": 3}, id="gap"),
        pytest.param({"0__sequence": True}, id="boolean-sequence"),
        pytest.param({"0__action": "rollback"}, id="first-write-a-rollback"),
        pytest.param({"1__action": "delete"}, id="unknown-action"),
        pytest.param({"1__release_id": "rel-g1-24db9555…"}, id="abbreviated-id"),
        pytest.param({"1__last_observed_on": "08-25"}, id="partial-date"),
        pytest.param({"1__sources": []}, id="no-source"),
        pytest.param({"1__sources": [{"document": "d.md"}]}, id="source-without-section"),
    ],
)
def test_a_malformed_reconstruction_is_refused(changes):
    with pytest.raises(ValueError):
        rt.load_reconstruction(_reconstruction_document(**changes))


# ── the real reconstruction, against the documents it cites ─────────────────

REAL_RECONSTRUCTION = Path(rt.RECONSTRUCTION_PATH)

#: Read from ``pointers/green/history/0000000010.json`` in ``araripe-v2-staging``
#: on 2026-09-27, after the re-proof wrote it (sha256 ``5c016cd4…``, byte-identical
#: to the pointer measured before it; ``PHASE_6D_2026-09-27.md`` §3).
MEASURED_RECORD_10_SUPERSEDES = {
    "release_id": "rel-g1-24db9555c8b2c3569418d953194622e02ebff2eae51b97d294014b3f777a6e36",
    "sequence": 9,
    "last_observed_on": "2026-08-25",
}

#: Refused for ``coverage_regression`` and never live — ``PHASE_2B3_2026-09-07.md`` §1.
REFUSED_RELEASE = "rel-g1-9f1ed3441310bd632caba3e5354cb20707669b433bf3a75e42db4a1bc245f54e"


def _real_entries():
    return rt.load_reconstruction(json.loads(REAL_RECONSTRUCTION.read_text(encoding="utf-8")))


def _section(document: Path, section: str) -> str:
    import re

    lines = document.read_text(encoding="utf-8").splitlines()
    heading = re.compile(r"^(#+)\s+" + re.escape(section) + r"\.?\s")
    for start, line in enumerate(lines):
        match = heading.match(line)
        if match:
            level = len(match.group(1))
            body = []
            for later in lines[start + 1:]:
                if re.match(r"^#{1,%d}\s" % level, later):
                    break
                body.append(later)
            return "\n".join(body)
    raise AssertionError(f"{document} has no section {section}")


def test_the_real_reconstruction_covers_sequences_1_to_9():
    entries = _real_entries()
    assert [e.sequence for e in entries] == list(range(1, 10))


def test_the_real_reconstruction_joins_the_store_at_record_10():
    last = _real_entries()[-1]
    assert {
        "release_id": last.release_id,
        "sequence": last.sequence,
        "last_observed_on": last.last_observed_on,
    } == MEASURED_RECORD_10_SUPERSEDES


def test_every_entry_is_in_the_sections_it_cites():
    """Each entry's full release id and its sequence must appear in the text of
    the sections it cites — read here, not trusted.  A mistyped id, a wrong
    section or a document that moved its numbering fails this test."""

    import re

    document = json.loads(REAL_RECONSTRUCTION.read_text(encoding="utf-8"))
    for item in document["entries"]:
        text = "\n".join(
            _section(Path(source["document"]), source["section"])
            for source in item["sources"]
        )
        assert item["release_id"] in text, (item["sequence"], item["sources"])
        n = item["sequence"]
        assert re.search(rf"(sequence\W{{0,4}}{n}\b|\|\s*{n}\s*\|)", text), (
            n, item["sources"],
        )


def test_the_refused_release_is_not_in_the_reconstruction():
    assert REFUSED_RELEASE not in {e.release_id for e in _real_entries()}


def test_the_reconstruction_declares_itself_and_is_never_a_store_key():
    """It lives in the repository, never under ``pointers/green/history/`` —
    ``PHASE_6C_2026-09-27.md`` §2.4: no backfill in the store."""

    document = json.loads(REAL_RECONSTRUCTION.read_text(encoding="utf-8"))
    assert document["reconstructed"] is True
    assert not rt.RECONSTRUCTION_PATH.startswith(ph.HISTORY_ROOT)
    source = Path("src/publication/retention.py").read_text(encoding="utf-8")
    assert "put_if_absent" not in source


# ── the bucket as it stands after the re-proof ───────────────────────────────

#: The seven releases in ``araripe-v2-staging`` on 2026-09-27 and the history
#: the promotion lane's ``history`` mode read back (run ``36365859406``).
AE3F = "rel-g1-ae3f6e1db152ac608f5e63d2fe2d6f4357f0f311ad5582070dfabf9e91828827"
FFAD = "rel-g1-5ffad23ad2b4072fa63f01b86fdab4f3f34627fddd0f877f910e7a4544d77d37"
FB34 = "rel-g1-1fb345489260784289532351887aef039345964518c981556b4a02048d16e14d"
DB95 = MEASURED_RECORD_10_SUPERSEDES["release_id"]
DDB1 = "rel-g1-2ddb10c795deb75f0b2f61a4ae349fda192baf31a2cbd310723b0c362a6670d3"
FB72 = "rel-g1-fb722b2d1786075b1a6b4d10b1d49db31bb1b3f4e4be74f9621f21b9358ea8bb"

AFTER_REPROOF = _history(
    [
        _entry(10, FB72), _entry(11, DDB1), _entry(12, DB95, "rollback"),
        _entry(13, DDB1), _entry(14, FB72),
    ],
    predecessor=MEASURED_RECORD_10_SUPERSEDES,
)
POINTER_14 = {
    "schema": "araripe.green.pointer/1", "sequence": 14, "action": "promote",
    "release_id": FB72,
    "supersedes": {"release_id": DDB1, "sequence": 13, "last_observed_on": "2026-08-30"},
}


def test_a_plan_over_the_bucket_after_the_re_proof():
    """Every one of the seven releases gets its own, true reason — and the one
    that was never live is told apart from the six that were."""

    inventory = [
        key(db.POINTER_KEY),
        *[key(ph.history_key(n)) for n in range(10, 15)],
        *[key(f"releases/{r}/release.json") for r in
          (AE3F, FFAD, FB34, DB95, DDB1, FB72, REFUSED_RELEASE)],
    ]
    lineage = rt.build_lineage(AFTER_REPROOF, _real_entries())
    assert lineage.continuous, lineage.detail
    plan = rt.build_plan(inventory, pointer=POINTER_14, as_of=NOW, lineage=lineage)
    reasons = {d.key.split("/")[1]: d.reason for d in plan.dispositions
               if d.category == "release"}
    assert reasons == {
        FB72: "release_is_live",
        DDB1: "release_is_referenced",
        DB95: "release_was_live",
        AE3F: "release_was_live_per_reconstruction",
        FFAD: "release_was_live_per_reconstruction",
        FB34: "release_was_live_per_reconstruction",
        REFUSED_RELEASE: "release_never_live",
    }
    assert plan.eligible == ()
    assert plan.counts() == {rt.RETAIN: 13}
    document = rt.plan_document(plan)
    assert document["lineage"]["continuous"] is True
    assert document["lineage"]["history_begins"] == 10
    assert document["lineage"]["recorded"][DB95] == [12]
    text = rt.describe(plan)
    assert "continuous from sequence 1 (reconstruction 1-9 + records 10-14)" in text
    assert "NOTHING WAS DELETED" in text


# ── end to end: the real protocol writes the history the planner reads ───────


def test_the_planner_reads_the_history_the_protocol_wrote():
    """No hand-built ``History`` here: the re-proof sequence runs through the
    real ``promote``/``rollback`` on the fake store, from a sequence-10 pointer
    with no history, and the planner reads what they wrote with the same reader
    the lane uses."""

    from src.publication.atomic_publish import (
        PromotionRefused, promote, read_live_pointer, rollback,
    )
    from tests.test_atomic_publish import LATER
    from tests.test_atomic_publish import NOW as T0
    from tests.test_promotion_history import _publish, _seed_prehistory_pointer, _store

    store, fake = _store()
    (before, _), (candidate, doc_candidate), _ = _seed_prehistory_pointer(store, fake)
    # The candidate's dates with other content (PHASE_6I §3: a promotion may
    # not retire a published date), as in the rehearsal it mirrors.
    gate_c, doc_c = _publish(store, {"2026-04-07": [ALERTS], "2026-04-10": [ALERTS]})
    gate_a, doc_a = _publish(store, {"2026-04-01": [ALERTS]})
    promote(store, gate_c, doc_c, now=T0)
    rollback(store, before["release_id"], now=T0)
    promote(store, gate_c, doc_c, now=LATER)
    with pytest.raises(PromotionRefused):
        promote(store, gate_a, doc_a, now=LATER)
    promote(store, candidate, doc_candidate, now=LATER)

    live, stored = read_live_pointer(store)
    inventory = rt.list_inventory(fake, cs.STAGING_BUCKET)
    found = ph.read_history(
        ReadOnlyStore(fake, cs.STAGING_BUCKET), live, stored.body,
        keys=[i.key for i in inventory if i.key.startswith(ph.HISTORY_ROOT)],
    )
    # Sequences 1-9 as a reconstruction would state them, ending at the release
    # the seeded pointer superseded.
    pre = _rebuilt(
        *([before["release_id"]] * 9),
        last_observed_on=found.predecessor["last_observed_on"],
    )
    lineage = rt.build_lineage(found, pre)
    assert lineage.continuous, lineage.detail
    plan = rt.build_plan(inventory, pointer=live, as_of=NOW, lineage=lineage)

    by_release = {}
    for d in plan.dispositions:
        if d.category == "release":
            by_release.setdefault(d.key.split("/")[1], set()).add(d.reason)
    assert by_release == {
        candidate["release_id"]: {"release_is_live"},
        gate_c["release_id"]: {"release_is_referenced"},
        before["release_id"]: {"release_was_live"},
        gate_a["release_id"]: {"release_never_live"},
    }
    assert {d.reason for d in plan.dispositions if d.category == "promotion_history"} == {
        "promotion_history_is_the_record"
    }
    assert plan.eligible == ()


def test_the_planner_script_reads_the_history_and_the_real_reconstruction(
    monkeypatch, capsys
):
    """The wiring, not just the policy: ``scripts/plan_retention.py`` lists the
    bucket, reads the history with the lane's reader, loads the reconstruction
    from the repository and passes the lineage on.  Run over a fake bucket
    shaped like the real one — history from sequence 10, joined at the release
    the real reconstruction ends at."""

    import importlib.util

    from src.publication.atomic_publish import promote
    from tests.test_atomic_publish import NOW as T0
    from tests.test_promotion_history import _publish, _seed_prehistory_pointer, _store

    store, fake = _store()
    (before, _), _live_release, _ = _seed_prehistory_pointer(store, fake)
    newer, doc_newer = _publish(
        store, {"2026-04-07": [ALERTS], "2026-04-10": [ZERO], "2026-04-13": [ALERTS]}
    )
    refused_like, _ = _publish(store, {"2026-04-01": [ALERTS]})
    promote(store, newer, doc_newer, now=T0)
    # Make the seeded pre-history name the release the real reconstruction ends
    # at, so the script's own reconstruction file joins it.
    record_10 = json.loads(fake.body(ph.history_key(10)))
    record_10["supersedes"] = dict(MEASURED_RECORD_10_SUPERSEDES)
    from src.publication.green_release import release_bytes

    fake.objects[ph.history_key(10)] = (release_bytes(record_10), "application/json")

    spec = importlib.util.spec_from_file_location("plan_retention_cli", "scripts/plan_retention.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(
        cli, "build_read_only_store",
        lambda: (fake, ReadOnlyStore(fake, cs.STAGING_BUCKET)),
    )
    assert cli.main(["--json", "--as-of", "2026-09-27T23:00:00Z"]) == 0
    document = json.loads(capsys.readouterr().out)
    lineage = document["lineage"]
    assert lineage == {
        "continuous": True, "reason": None, "detail": "", "findings": [],
        "live_sequence": 11, "history_begins": 10,
        "recorded": {_live_release[0]["release_id"]: [10], newer["release_id"]: [11]},
        "reconstructed": {
            e.release_id: [x.sequence for x in _real_entries() if x.release_id == e.release_id]
            for e in _real_entries()
        },
    }
    reasons = {o["key"]: o["reason"] for o in document["objects"]}
    assert reasons[f"releases/{refused_like['release_id']}/release.json"] == (
        "release_never_live"
    )
    assert reasons[f"releases/{newer['release_id']}/release.json"] == "release_is_live"
    assert {reasons[ph.history_key(n)] for n in (10, 11)} == {
        "promotion_history_is_the_record"
    }
    assert document["eligible_bytes"] == 0


@pytest.mark.parametrize("accept", [False, True])
def test_a_runs_persistence_state_is_retained_even_once_its_release_is_published(accept):
    """PHASE_6G §1: the state lives only in its run prefix.

    A release carries the state's digest and never its bytes, so the rule that
    makes a ripe run ``ELIGIBLE`` once its release is published would lose the
    one object a chained run continues from.
    """

    key = "runs/proof-a/persistence_state.geojson"
    entry = decide(key, age_days=999, runs=LINKED, accept_run_manifest_loss=accept)
    assert (entry.action, entry.reason) == (rt.RETAIN, "persistence_state_is_the_chain")
    # the rest of the same prefix is still decided by the run rule
    other = decide("runs/proof-a/run.json", age_days=999, runs=LINKED,
                   accept_run_manifest_loss=True)
    assert other.action == rt.ELIGIBLE
    # and a lookalike deeper in the prefix is not the state
    deeper = decide("runs/proof-a/alerts/persistence_state.geojson", age_days=999,
                    runs=LINKED, accept_run_manifest_loss=True)
    assert deeper.action == rt.ELIGIBLE


# ── PHASE_6J §2: a version-3 release keeps its members ──────────────────────


def test_every_member_of_a_chain_release_is_retained_and_the_live_ones_say_so():
    from src.publication import retention as rt

    live_chain = "rel-g3-" + "a" * 64
    old_chain = "rel-g3-" + "b" * 64
    served, kept, loose = ("rel-g1-" + c * 64 for c in "cde")
    members = {live_chain: (served,), old_chain: (kept,)}
    pointer = {"release_id": live_chain}
    moment = datetime(2027, 1, 1, tzinfo=timezone.utc)

    def decide(release):
        item = rt.StoredKey(f"releases/{release}/alerts/x.geojson", 1,
                            datetime(2026, 1, 1, tzinfo=timezone.utc))
        return rt.classify(item, pointer=pointer, runs={}, as_of=moment,
                           chain_members=members, lineage=None)

    assert (decide(served).action, decide(served).reason) == (
        rt.RETAIN, "release_is_served_by_the_live_release")
    assert (decide(kept).action, decide(kept).reason) == (
        rt.RETAIN, "release_is_a_member_of_a_chain_release")
    assert decide(loose).reason != "release_is_a_member_of_a_chain_release"


def test_the_planner_reads_each_chain_releases_members_from_the_store():
    from src.publication import conditional_store as cs
    from src.publication import retention as rt
    from tests.fake_object_store import FakeS3

    chain = "rel-g3-" + "a" * 64
    member = "rel-g1-" + "c" * 64
    manifest = json.dumps({"members": [{"release_id": member}]}).encode()
    fake = FakeS3({f"releases/{chain}/release.json": (manifest, "application/json"),
                   f"releases/{chain}/ledger.json": (b"{}", "application/json")})
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    inventory = rt.list_inventory(fake, cs.STAGING_BUCKET)
    assert rt.resolve_chain_members(store, inventory) == {chain: (member,)}
