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
