"""The public release of a state chain (``docs/implementation/PHASE_6I_2026-09-28.md``).

§2 is the decision: one immutable release, composed of the version-1 releases
of every run from the root to the head, under an identity that is a function of
their ledgers in order.  §3 is the guard: a promotion that retires a published
date is refused, for either version.  §4 is the pointer that can name it.

The case this package exists for is here verbatim, at fixture scale:
``test_the_heads_own_release_is_refused_because_it_drops_the_history`` — the
release of one chained run advances the last covered date while retiring every
earlier one, and ``coverage_regression`` alone waved that through.

Every refusal is asserted by its effect as well as its code: nothing written,
the pointer's bytes unchanged.  No network, no clock, no credential.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.publication import atomic_publish as ap
from src.publication import chain_release as cr
from src.publication import conditional_store as cs
from src.publication import promotion_history as history
from src.publication import run_inputs as ri
from src.publication.state_chain import CHAIN_ROOT
from src.publication.atomic_publish import PromotionRefused, promote, publish_release, rollback
from src.publication.green_release import (
    LEDGER_PATH,
    MANIFEST_PATH,
    POINTER_KEY,
    POINTER_SCHEMA,
    RELEASE_SCHEMA,
    ReleaseBuildError,
    ReleaseRejected,
    build_release,
    ledger_bytes,
    object_key,
    release_bytes,
    schema_validator,
    sha256_bytes,
)
from src.publication.ledger_gate import check_processing_ledger
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, REJECTED, ZERO, build_ledger
from tests.test_green_release import objects_for
from tests.test_ledger_completeness_gate import reseal

NOW = datetime(2026, 9, 28, 20, 0, 0, tzinfo=timezone.utc)

#: A chain at fixture scale: the root covers two dates, a middle run observes
#: nothing usable (like ci-36456671793, whose three dates had no valid
#: coverage), and the head covers one later date.
ROOT = {"2026-04-07": [ALERTS], "2026-04-10": [ZERO, REJECTED]}
MIDDLE = {"2026-04-12": [REJECTED]}
HEAD = {"2026-04-15": [ALERTS, ALERTS]}

STATES = {
    "root": ("1" * 64, 1000),
    "middle": ("1" * 64, 1000),
    "head": ("3" * 64, 1013),
}


def member(spec, state=("a" * 64, 100), *, ledger=None, bodies=None):
    """One run's version-1 release, its ledger and its object bodies."""

    if ledger is None:
        ledger, bodies = build_ledger(spec)
    objects = objects_for(ledger, bodies)
    release = build_release(
        check_processing_ledger(ledger),
        ledger,
        objects,
        persistence_state_sha256=state[0],
        persistence_state_bytes=state[1],
    )
    return cr.ChainMember(release, ledger), {item.path: item.body for item in objects}


def chain(*specs):
    names = ("root", "middle", "head")
    members, bodies = [], {}
    for name, spec in zip(names, specs):
        built, own = member(spec, STATES[name])
        members.append(built)
        bodies.update(own)
    return members, bodies


def chain_doc(members):
    return cr.ledger_chain_document([m.ledger_document for m in members])


def built():
    members, bodies = chain(ROOT, MIDDLE, HEAD)
    release = cr.build_chain_release(members)
    return release, chain_doc(members), bodies, members


def codes_of(document, ledger_chain):
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_chain_release(document, ledger_chain)
    return raised.value.codes


# ── §2 what a chain release is ───────────────────────────────────────────────


def test_the_chain_release_covers_every_members_dates_in_chain_order():
    release, ledger_chain, _, members = built()
    assert release["schema"] == "araripe.green.release/2"
    assert release["release_id"].startswith("rel-g2-")
    assert release["release_prefix"] == f"releases/{release['release_id']}/"
    assert release["coverage"]["observed_dates"] == [
        "2026-04-07", "2026-04-10", "2026-04-12", "2026-04-15"]
    assert [e["ledger_id"] for e in release["dates"]] == [
        members[0].release["ledger"]["ledger_id"]] * 2 + [
        members[1].release["ledger"]["ledger_id"],
        members[2].release["ledger"]["ledger_id"]]
    assert release["state_watermark"]["finalized_through"] == "2026-04-15"
    # the head's state: the one the next run continues from
    assert release["state_watermark"]["persistence_state_sha256"] == "3" * 64
    assert release["state_watermark"]["persistence_state_bytes"] == 1013
    checked, acceptances = cr.check_chain_release(release, ledger_chain)
    assert checked is release and len(acceptances) == 3


def test_every_member_is_exactly_what_its_run_would_publish_alone():
    """Composed, not re-derived: each member stays checkable on its own."""

    release, _, _, members = built()
    for block, m in zip(release["ledgers"]["chain"], members):
        assert block["file_sha256"] == m.release["ledger"]["file_sha256"]
        assert block["bytes"] == m.release["ledger"]["bytes"]
        own = [dict(e, ledger_id=block["ledger_id"]) for e in m.release["dates"]]
        assert [e for e in release["dates"] if e["ledger_id"] == block["ledger_id"]] == own
    everything = sorted((o["path"], o["sha256"]) for m in members for o in m.release["objects"])
    assert sorted((o["path"], o["sha256"]) for o in release["objects"]) == everything


def test_the_ledger_file_is_every_member_ledger_root_first():
    release, ledger_chain, _, members = built()
    stored = ledger_bytes(ledger_chain)
    assert release["ledgers"]["path"] == LEDGER_PATH == "ledger.json"
    assert release["ledgers"]["file_sha256"] == sha256_bytes(stored)
    assert ledger_chain["schema"] == "araripe.green.ledger-chain/1"
    assert [check_processing_ledger(d).ledger_id for d in ledger_chain["ledgers"]] == [
        m.release["ledger"]["ledger_id"] for m in members]


def test_the_identity_is_the_ledgers_in_order_and_nothing_else():
    members, _ = chain(ROOT, MIDDLE, HEAD)
    first = cr.build_chain_release(members)
    again = cr.build_chain_release(members)
    assert release_bytes(first) == release_bytes(again), "no clock, no counter"

    acceptances = [check_processing_ledger(m.ledger_document) for m in members]
    assert cr.chain_release_identity(acceptances)[0] == first["release_id"]
    assert cr.chain_release_identity(acceptances[::-1])[0] != first["release_id"]
    assert cr.chain_release_identity(acceptances[:2])[0] != first["release_id"]

    # One different member ledger — here only the head's content — is another release.
    other, _ = chain(ROOT, MIDDLE, {"2026-04-15": [ALERTS]})
    assert cr.build_chain_release(other)["release_id"] != first["release_id"]


def test_the_identity_does_not_collide_with_the_version_one_release_of_one_ledger():
    """A chain of one member is the same ledger under another contract."""

    root, _ = member(ROOT)
    alone = cr.build_chain_release([root])
    assert alone["release_id"] != root.release["release_id"]
    assert alone["release_id"][len("rel-g2-"):] != root.release["release_id"][len("rel-g1-"):]


def test_a_chain_without_members_cannot_be_built():
    with pytest.raises(ReleaseBuildError, match="at least one member"):
        cr.build_chain_release([])


def test_the_version_one_contract_and_its_constants_are_untouched():
    """PHASE_6I §4: the Phase 3 freeze pins these two values."""

    assert RELEASE_SCHEMA == "araripe.green.release/1"
    assert POINTER_SCHEMA == "araripe.green.pointer/1"
    from src.replay import freeze

    freeze.load_freeze()  # the replay's preflight, which a drift would stop


# ── §2 what must hold across members ─────────────────────────────────────────


def test_members_whose_dates_touch_are_refused_when_building():
    members, _ = chain(ROOT, {"2026-04-10": [ALERTS]})
    with pytest.raises(ReleaseBuildError, match="chain_dates_overlap"):
        cr.build_chain_release(members)


def test_members_out_of_chain_order_are_refused_when_building():
    members, _ = chain(HEAD, ROOT)
    with pytest.raises(ReleaseBuildError, match="chain_dates_overlap"):
        cr.build_chain_release(members)


def test_the_gate_reads_the_order_from_the_ledgers_not_from_the_manifest():
    """A manifest cannot talk a chain into order by misreporting its dates."""

    release, _, _, members = built()
    swapped = chain_doc([members[0], members[2], members[1]])
    assert "chain_dates_overlap" in codes_of(release, swapped)


def test_a_chain_mixing_generations_is_refused():
    ledger, bodies = build_ledger(HEAD)
    other = deepcopy(ledger)
    other["algorithm_version"] = "9.9.9"
    other = reseal(other)
    root, _ = member(ROOT)
    head, _ = member(HEAD, ledger=other, bodies=bodies)
    with pytest.raises(ReleaseBuildError, match="chain_mixes_generations"):
        cr.build_chain_release([root, head])


def test_the_gate_refuses_mixed_generations_too():
    release, _, _, members = built()
    other = deepcopy(members[2].ledger_document)
    other["algorithm_version"] = "9.9.9"
    mixed = chain_doc([members[0], members[1], cr.ChainMember({}, reseal(other))])
    assert "chain_mixes_generations" in codes_of(release, mixed)


def test_one_path_published_by_two_members_is_refused_when_building():
    root, _ = member(ROOT)
    head, _ = member(HEAD)
    ledger, bodies = build_ledger(HEAD)
    objects = objects_for(ledger, bodies)
    taken = root.release["objects"][0]["path"]
    objects[0] = type(objects[0])(taken, objects[0].body, objects[0].content_type,
                                  objects[0].observed_on, objects[0].acquisition_id)
    clash = build_release(check_processing_ledger(ledger), ledger, objects,
                          persistence_state_sha256="3" * 64, persistence_state_bytes=1)
    with pytest.raises(ReleaseBuildError, match="published by two members"):
        cr.build_chain_release([root, cr.ChainMember(clash, ledger)])


def test_a_member_whose_own_release_does_not_check_is_refused_when_building():
    """Composed from checked parts: every member passes the version-1 gate first."""

    root, _ = member(ROOT)
    head, _ = member(HEAD)
    tampered = deepcopy(head.release)
    tampered["dates"][0]["observation_count"] += 1
    with pytest.raises(ReleaseRejected) as raised:
        cr.build_chain_release([root, cr.ChainMember(tampered, head.ledger_document)])
    assert raised.value.codes == ("date_accounting_mismatch",)


# ── the gate, every rule ─────────────────────────────────────────────────────


def test_a_date_whose_accounting_was_edited_is_refused_at_its_own_index():
    """``positions``: the finding names the entry in the WHOLE document."""

    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["dates"][3]["observation_count"] += 1
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_chain_release(tampered, ledger_chain)
    assert raised.value.codes == ("date_accounting_mismatch",)
    assert raised.value.findings[0].path == "dates/3/observation_count"


def test_an_object_whose_bytes_were_edited_is_refused_at_its_own_index():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    last = len(tampered["objects"]) - 1
    tampered["objects"][last]["sha256"] = "f" * 64
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_chain_release(tampered, ledger_chain)
    assert raised.value.codes == ("artifact_checksum_mismatch",)
    assert raised.value.findings[0].path == f"objects/{last}/sha256"


def test_a_date_that_names_another_members_ledger_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["dates"][0]["ledger_id"] = tampered["dates"][3]["ledger_id"]
    assert "date_names_the_wrong_ledger" in codes_of(tampered, ledger_chain)


def test_a_date_missing_from_the_manifest_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    del tampered["dates"][2]
    assert "release_dates_do_not_cover_the_chain" in codes_of(tampered, ledger_chain)


def test_an_object_on_a_date_no_member_reconciles_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["objects"][0]["provenance"]["observed_on"] = "2026-04-30"
    assert "object_on_an_unreconciled_date" in codes_of(tampered, ledger_chain)


def test_a_declared_path_twice_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["objects"].append(deepcopy(tampered["objects"][0]))
    assert "duplicate_object_path" in codes_of(tampered, ledger_chain)


def test_a_member_block_that_misreports_its_ledger_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["ledgers"]["chain"][1]["expected_acquisition_count"] += 1
    assert codes_of(tampered, ledger_chain) == ("ledger_block_mismatch",)


def test_a_member_block_that_misreports_its_dates_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["ledgers"]["chain"][2]["first_observed_on"] = "2026-04-14"
    assert codes_of(tampered, ledger_chain) == ("ledger_block_mismatch",)


def test_a_member_digest_that_is_not_its_own_ledger_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["ledgers"]["chain"][0]["file_sha256"] = "0" * 64
    assert codes_of(tampered, ledger_chain) == ("ledger_object_mismatch",)


def test_a_ledger_file_that_is_not_the_one_declared_is_refused():
    release, ledger_chain, _, members = built()
    other, _ = member({"2026-04-15": [ALERTS]}, STATES["head"])
    swapped = chain_doc([members[0], members[1], other])
    codes = set(codes_of(release, swapped))
    assert {"ledger_object_mismatch", "release_identity_mismatch", "ledger_block_mismatch"} <= codes
    shorter = chain_doc(members[:2])
    assert "ledger_chain_length_mismatch" in codes_of(release, shorter)


def test_a_ledger_file_with_another_envelope_is_refused():
    release, ledger_chain, _, _ = built()
    assert codes_of(release, dict(ledger_chain, schema="araripe.green.ledger-chain/2")) == (
        "ledger_chain_invalid",)
    assert codes_of(release, [ledger_chain]) == ("ledger_chain_invalid",)


def test_a_rejected_member_ledger_stops_the_gate_with_its_own_findings():
    from src.publication.ledger_gate import LedgerRejected

    release, ledger_chain, _, _ = built()
    broken = deepcopy(ledger_chain)
    broken["ledgers"][1]["terminal_rows"] = []
    with pytest.raises(LedgerRejected):
        cr.check_chain_release(release, broken)


def test_a_watermark_or_coverage_that_was_edited_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["state_watermark"]["finalized_through"] = "2026-04-12"
    assert codes_of(tampered, ledger_chain) == ("state_watermark_mismatch",)
    tampered = deepcopy(release)
    tampered["state_watermark"]["finalized_dates"] = tampered["state_watermark"]["finalized_dates"][:-1]
    assert codes_of(tampered, ledger_chain) == ("state_watermark_mismatch",)
    tampered = deepcopy(release)
    tampered["coverage"]["last_observed_on"] = "2026-04-12"
    assert codes_of(tampered, ledger_chain) == ("coverage_mismatch",)


def test_an_edited_identity_or_prefix_is_refused():
    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["release_id"] = "rel-g2-" + "0" * 64
    tampered["release_prefix"] = "releases/rel-g2-" + "0" * 64 + "/"
    assert set(codes_of(tampered, ledger_chain)) == {"release_identity_mismatch"}
    tampered = deepcopy(release)
    tampered["release_prefix"] = "releases/rel-g2-" + "0" * 64 + "/"
    assert codes_of(tampered, ledger_chain) == ("release_prefix_mismatch",)


def test_a_version_one_identity_is_not_a_chain_identity():
    release, ledger_chain, _, _ = built()
    tampered = dict(release, release_id="rel-g1-" + release["release_id"][7:])
    assert "release_schema_invalid" in codes_of(tampered, ledger_chain)


# ── one gate for both versions ───────────────────────────────────────────────


def test_the_gate_dispatches_on_the_declared_version():
    release, ledger_chain, _, members = built()
    assert len(cr.check_release(release, ledger_chain)[1]) == 3
    root = members[0]
    assert len(cr.check_release(root.release, root.ledger_document)[1]) == 1
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_release(dict(release, schema="araripe.green.release/4"), ledger_chain)
    assert raised.value.codes == ("release_schema_mismatch",)
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_release([release], ledger_chain)
    assert raised.value.codes == ("not_a_release_document",)


def test_a_chain_release_is_never_accepted_by_the_version_one_gate():
    from src.publication.green_release import check_green_release

    release, ledger_chain, _, _ = built()
    with pytest.raises(ReleaseRejected) as raised:
        check_green_release(release, ledger_chain)
    assert raised.value.codes == ("release_schema_mismatch",)


# ── publish, verify, promote: the layout is version 1's ──────────────────────


def store_with_live_root():
    """The bucket today: the root's own version-1 release is live, as
    rel-g1-fb722b2d… is at sequence 14."""

    fake = FakeS3()
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    members, bodies = chain(ROOT, MIDDLE, HEAD)
    root = members[0]
    root_bodies = {o["path"]: bodies[o["path"]] for o in root.release["objects"]}
    publish_release(store, root.release, root.ledger_document, root_bodies)
    promote(store, root.release, root.ledger_document, now=NOW)
    return store, fake, members, bodies


def test_a_chain_release_publishes_the_version_one_layout_under_its_own_prefix():
    release, ledger_chain, bodies, _ = built()
    fake = FakeS3()
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    publish_release(store, release, ledger_chain, bodies)
    prefix = release["release_prefix"]
    assert fake.keys() == sorted(
        [prefix + LEDGER_PATH, prefix + MANIFEST_PATH]
        + [prefix + item["path"] for item in release["objects"]])
    assert fake.writes[-1][0] == prefix + MANIFEST_PATH, "the manifest lands last"
    assert fake.body(prefix + LEDGER_PATH) == ledger_bytes(ledger_chain)
    ap.verify_release(store, release)
    loaded, stored_chain = ap.load_published_release(store, release["release_id"])
    assert loaded == release and stored_chain == ledger_chain


def test_a_ledger_file_that_changed_in_the_store_fails_verification():
    release, ledger_chain, bodies, _ = built()
    fake = FakeS3()
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    publish_release(store, release, ledger_chain, bodies)
    key = release["release_prefix"] + LEDGER_PATH
    fake.objects[key] = (fake.body(key) + b" ", "application/json")
    with pytest.raises(ap.ReleaseIncomplete) as raised:
        ap.verify_release(store, release)
    assert raised.value.codes == ("release_object_mismatch",)


def test_the_chain_release_promotes_over_the_live_root_and_names_every_ledger():
    store, fake, members, bodies = store_with_live_root()
    release = cr.build_chain_release(members)
    ledger_chain = chain_doc(members)
    publish_release(store, release, ledger_chain, bodies)
    result = promote(store, release, ledger_chain, now=NOW)

    pointer = json.loads(fake.body(POINTER_KEY))
    assert (result.action, result.sequence) == ("promote", 2)
    assert pointer["schema"] == "araripe.green.pointer/2"
    assert pointer["release_id"] == release["release_id"]
    assert pointer["release_path"] == object_key(release["release_id"], MANIFEST_PATH)
    assert pointer["ledgers"] == [
        {"ledger_id": b["ledger_id"], "run_manifest_id": b["run_manifest_id"]}
        for b in release["ledgers"]["chain"]]
    assert pointer["supersedes"]["release_id"] == members[0].release["release_id"]
    # The root's objects are carried byte for byte: nothing is retired.
    assert pointer["tombstones"] == []
    assert list(schema_validator("green-pointer-v2").iter_errors(pointer)) == []


def test_the_heads_own_release_is_refused_because_it_drops_the_history():
    """The package's reason to exist, at fixture scale.

    The head's version-1 release covers one later date: its last covered date
    ADVANCES, so ``coverage_regression`` passes it, and promoting it would
    retire every date of the root.
    """

    store, fake, members, bodies = store_with_live_root()
    head = members[2]
    head_bodies = {o["path"]: bodies[o["path"]] for o in head.release["objects"]}
    publish_release(store, head.release, head.ledger_document, head_bodies)
    live = fake.body(POINTER_KEY)
    writes = list(fake.writes)

    assert head.release["coverage"]["last_observed_on"] > members[0].release["coverage"]["last_observed_on"]
    with pytest.raises(PromotionRefused) as raised:
        promote(store, head.release, head.ledger_document, now=NOW)
    assert raised.value.codes == ("coverage_dates_dropped",)
    assert "2026-04-07, 2026-04-10" in str(raised.value)
    assert fake.body(POINTER_KEY) == live
    assert fake.writes == writes, "a refused promotion wrote something"


def test_a_chain_release_that_drops_a_date_is_refused_too():
    """The guard is on the pointer's coverage, whatever the release version."""

    store, fake, members, bodies = store_with_live_root()
    full = cr.build_chain_release(members)
    publish_release(store, full, chain_doc(members), bodies)
    promote(store, full, chain_doc(members), now=NOW)

    # A chain that grew from another root and never saw 2026-04-07.
    stray, stray_bodies = member({"2026-04-20": [ALERTS]}, ("4" * 64, 9))
    alone = cr.build_chain_release([stray])
    publish_release(store, alone, chain_doc([stray]), stray_bodies)
    live = fake.body(POINTER_KEY)
    with pytest.raises(PromotionRefused) as raised:
        promote(store, alone, chain_doc([stray]), now=NOW)
    assert raised.value.codes == ("coverage_dates_dropped",)
    assert fake.body(POINTER_KEY) == live


def test_a_receding_last_date_is_still_named_a_regression_first():
    store, fake, members, bodies = store_with_live_root()
    older, older_bodies = member({"2026-04-01": [ALERTS]})
    publish_release(store, older.release, older.ledger_document, older_bodies)
    with pytest.raises(PromotionRefused) as raised:
        promote(store, older.release, older.ledger_document, now=NOW)
    assert raised.value.codes == ("coverage_regression",)


def test_rollback_from_a_chain_release_to_the_root_names_both():
    """Only pointer /2 can say this: rolled_back_from is a rel-g2 id."""

    store, fake, members, bodies = store_with_live_root()
    release = cr.build_chain_release(members)
    publish_release(store, release, chain_doc(members), bodies)
    promote(store, release, chain_doc(members), now=NOW)
    result = rollback(store, members[0].release["release_id"], now=NOW)
    pointer = json.loads(fake.body(POINTER_KEY))
    assert (result.action, result.sequence) == ("rollback", 3)
    assert pointer["release_id"].startswith("rel-g1-")
    assert pointer["rolled_back_from"]["release_id"] == release["release_id"]
    assert len(pointer["ledgers"]) == 1


def test_a_live_version_one_pointer_is_read_recorded_and_replaced():
    """The real bucket: pointer /1 at the live sequence, records /1 below it.

    The first chain promotion records the /1 version byte for byte, writes a
    /2 one, and the history reads the mixed sequence as one consistent chain.
    """

    store, fake, members, bodies = store_with_live_root()
    current = json.loads(fake.body(POINTER_KEY))
    as_v1 = {k: v for k, v in current.items() if k != "ledgers"}
    as_v1["schema"] = POINTER_SCHEMA
    as_v1["ledger_id"] = current["ledgers"][0]["ledger_id"]
    as_v1["run_manifest_id"] = current["ledgers"][0]["run_manifest_id"]
    assert list(schema_validator("green-pointer-v1").iter_errors(as_v1)) == []
    v1_bytes = release_bytes(as_v1)
    fake.objects[POINTER_KEY] = (v1_bytes, "application/json")
    fake.objects[history.history_key(1)] = (v1_bytes, "application/json")

    release = cr.build_chain_release(members)
    publish_release(store, release, chain_doc(members), bodies)
    promote(store, release, chain_doc(members), now=NOW)

    assert fake.body(history.history_key(1)) == v1_bytes
    assert json.loads(fake.body(history.history_key(2)))["schema"] == "araripe.green.pointer/2"
    live, stored = ap.read_live_pointer(store)
    found = history.read_history(store, live, stored.body)
    assert found.consistent, found.findings
    assert [e.release_id for e in found.entries] == [
        members[0].release["release_id"], release["release_id"]]


# ── reading a chain from the bucket ──────────────────────────────────────────


def deposit(fake, run_id, built_member, bodies, predecessor):
    """A run prefix as the deposit lane writes it: bodies, ledger, run.json last."""

    objects = []
    for item in built_member.release["objects"]:
        source = "objects/" + item["path"].replace("/", "_")
        fake.objects[f"runs/{run_id}/{source}"] = (bodies[item["path"]], item["content_type"])
        objects.append({
            "path": item["path"], "source": source, "kind": item["provenance"]["kind"],
            "observed_on": item["provenance"]["observed_on"],
            "content_type": item["content_type"],
            "acquisition_id": item["provenance"]["acquisition_id"],
        })
    watermark = built_member.release["state_watermark"]
    fake.objects[f"runs/{run_id}/ledger.json"] = (
        json.dumps(built_member.ledger_document).encode(), "application/json")
    fake.objects[f"runs/{run_id}/run.json"] = (json.dumps({
        "schema": ri.RUN_SCHEMA, "run_id": run_id, "ledger": "ledger.json",
        "persistence_state": {"sha256": watermark["persistence_state_sha256"],
                              "bytes": watermark["persistence_state_bytes"]},
        "predecessor": predecessor, "objects": objects,
    }).encode(), "application/json")


def bucket_with_a_chain():
    members, bodies = chain(ROOT, MIDDLE, HEAD)
    fake = FakeS3()
    deposit(fake, CHAIN_ROOT, members[0], bodies, None)
    deposit(fake, "ci-1", members[1], bodies,
            {"run_id": CHAIN_ROOT, "persistence_state_sha256": STATES["root"][0]})
    deposit(fake, "ci-2", members[2], bodies,
            {"run_id": "ci-1", "persistence_state_sha256": STATES["middle"][0]})
    return fake, members


def test_the_chain_is_read_from_its_run_prefixes_with_a_store_that_cannot_write():
    fake, members = bucket_with_a_chain()
    store = ri.ReadOnlyStore(fake, cs.STAGING_BUCKET)
    staged = cr.load_chain(store, (CHAIN_ROOT, "ci-1", "ci-2"))
    assert staged.release == cr.build_chain_release(members)
    assert staged.ledger_chain == chain_doc(members)
    assert set(staged.bodies) == {o["path"] for o in staged.release["objects"]}
    assert fake.writes == []
    assert f"{CHAIN_ROOT} -> ci-1 -> ci-2" in cr.describe(staged)


def test_a_member_that_could_not_be_published_alone_stops_the_chain():
    fake, _ = bucket_with_a_chain()
    victim = next(k for k in fake.objects if k.startswith("runs/ci-2/objects/"))
    del fake.objects[victim]
    with pytest.raises(ri.RunRejected) as raised:
        cr.load_chain(ri.ReadOnlyStore(fake, cs.STAGING_BUCKET), (CHAIN_ROOT, "ci-1", "ci-2"))
    assert raised.value.codes == ("run_object_absent",)


# ── the two scripts: stage with the candidate identity, publish with the other ─


def _script(name):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bucket_with_a_chain_and_a_live_root():
    """The bucket as it is: runs/ holds the chain, the root's release is live."""

    fake, members = bucket_with_a_chain()
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    root = members[0]
    staged_root = ri.load_run(store, CHAIN_ROOT)
    publish_release(store, root.release, root.ledger_document, staged_root.bodies)
    promote(store, root.release, root.ledger_document, now=NOW)
    return fake, store, members


def test_the_staging_script_emits_the_chain_release_and_writes_nothing(
    monkeypatch, tmp_path, capsys
):
    fake, _, members = bucket_with_a_chain_and_a_live_root()
    stage = _script("stage_chain_release")
    monkeypatch.setattr(stage, "build_reader", lambda: ri.ReadOnlyStore(fake, cs.STAGING_BUCKET))
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    writes, before = list(fake.writes), len(fake.reads)
    assert stage.main([]) == 0
    expected = cr.build_reference_release(members)[0]["release_id"]
    assert expected.startswith("rel-g3-"), "the lane stages the version-3 release"
    assert output.read_text() == f"release_id={expected}\n"
    printed = capsys.readouterr().out
    assert f"{CHAIN_ROOT} -> ci-1 -> ci-2" in printed and "read-only" in printed
    assert fake.writes == writes
    assert POINTER_KEY not in fake.reads[before:], "staging reads no pointer"


def test_the_staging_script_refuses_a_forked_chain(monkeypatch, capsys):
    fake, members = bucket_with_a_chain()
    body, kind = fake.objects["runs/ci-2/run.json"]
    twin = json.loads(body)
    twin["run_id"] = "ci-3"
    fake.objects["runs/ci-3/run.json"] = (json.dumps(twin).encode(), kind)
    stage = _script("stage_chain_release")
    monkeypatch.setattr(stage, "build_reader", lambda: ri.ReadOnlyStore(fake, cs.STAGING_BUCKET))
    assert stage.main([]) == 1
    assert "chain_forked" in capsys.readouterr().err


def test_publish_chain_promotes_exactly_the_staged_release(monkeypatch, capsys):
    from tests.test_promotion_lane import publish_cli

    fake, store, members = bucket_with_a_chain_and_a_live_root()
    monkeypatch.setattr(publish_cli, "build_store", lambda: store)
    expected = cr.build_reference_release(members)[0]["release_id"]
    assert publish_cli.main(["publish-chain", "--expect", expected]) == 0
    pointer = json.loads(fake.body(POINTER_KEY))
    assert pointer["release_id"] == expected
    assert pointer["coverage"]["observed_dates"] == [
        "2026-04-07", "2026-04-10", "2026-04-12", "2026-04-15"]
    assert pointer["tombstones"] == []
    assert f"pointer  : promote -> {expected} at sequence 2" in capsys.readouterr().out
    # Every member's version-1 release is published, and the index holds no object.
    for m in members:
        ap.verify_release(store, m.release)
    index_keys = [k for k in fake.keys() if k.startswith(f"releases/{expected}/")]
    assert sorted(index_keys) == [f"releases/{expected}/ledger.json",
                                  f"releases/{expected}/release.json"]


def test_publish_chain_refuses_a_chain_that_moved_since_staging(monkeypatch, capsys):
    """A run deposited between the jobs composes another release: refused,
    before a single object is written."""

    from tests.test_promotion_lane import publish_cli

    fake, store, members = bucket_with_a_chain_and_a_live_root()
    monkeypatch.setattr(publish_cli, "build_store", lambda: store)
    staged = cr.build_reference_release(members[:2])[0]["release_id"]
    live = fake.body(POINTER_KEY)
    writes = list(fake.writes)
    assert publish_cli.main(["publish-chain", "--expect", staged]) == 1
    assert "chain_moved_since_staging" in capsys.readouterr().err
    assert fake.writes == writes and fake.body(POINTER_KEY) == live


def test_publish_chain_cannot_run_without_naming_what_was_staged():
    from tests.test_promotion_lane import publish_cli

    with pytest.raises(SystemExit):
        publish_cli.main(["publish-chain"])


# ── found by mutation ────────────────────────────────────────────────────────


def test_two_deposits_of_one_window_are_two_releases():
    """Mutation M6: dropping ``document_sha256`` from the identity.

    Runs A and B of PHASE_6H §7 detected the same window and produced the
    SAME ``ledger_id`` — the identity excludes ``terminal_at``.  Without the
    document digest their chain releases would share one prefix and differ in
    bytes, and the second publication would fail as an immutable conflict.
    """

    root, _ = member(ROOT)
    ledger, bodies = build_ledger(HEAD)
    rerun = deepcopy(ledger)
    for row in rerun["terminal_rows"]:
        row["terminal_at"] = "2026-04-15T19:30:00Z"
    rerun = reseal(rerun, rederive_summaries=True)
    assert check_processing_ledger(rerun).ledger_id == check_processing_ledger(ledger).ledger_id
    first, _ = member(HEAD, ledger=ledger, bodies=bodies)
    second, _ = member(HEAD, ledger=rerun, bodies=bodies)
    assert (cr.build_chain_release([root, first])["release_id"]
            != cr.build_chain_release([root, second])["release_id"])


def test_a_manifest_that_misdeclares_its_ledger_file_is_refused():
    """Mutation M9: the whole file's digest is what ``verify_release`` compares
    the stored ``ledger.json`` against, so the gate must hold it to the chain."""

    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    tampered["ledgers"]["file_sha256"] = "0" * 64
    assert codes_of(tampered, ledger_chain) == ("ledger_object_mismatch",)
    tampered = deepcopy(release)
    tampered["ledgers"]["bytes"] += 1
    assert codes_of(tampered, ledger_chain) == ("ledger_object_mismatch",)


def test_one_path_declared_on_two_members_dates_is_named_a_duplicate():
    """Mutation M14: a duplicate ACROSS members lands in two member slices, so
    no single slice sees two objects — only the whole-document check names it."""

    release, ledger_chain, _, _ = built()
    tampered = deepcopy(release)
    first = tampered["objects"][0]
    head_object = next(o for o in tampered["objects"]
                       if o["provenance"]["observed_on"] == "2026-04-15")
    tampered["objects"].append(dict(deepcopy(head_object), path=first["path"]))
    assert "duplicate_object_path" in codes_of(tampered, ledger_chain)


def test_the_chain_is_gated_after_it_is_composed(monkeypatch):
    """Mutation M33: the staging job relies on ``load_chain`` running the chain
    gate, not only the builder's own checks — it never calls ``promote``."""

    fake, _ = bucket_with_a_chain()
    real = cr.build_chain_release

    def drifting(members):
        document = real(members)
        document["coverage"]["last_observed_on"] = "2026-04-12"
        return document

    monkeypatch.setattr(cr, "build_chain_release", drifting)
    with pytest.raises(ReleaseRejected) as raised:
        cr.load_chain(ri.ReadOnlyStore(fake, cs.STAGING_BUCKET), (CHAIN_ROOT, "ci-1", "ci-2"))
    assert raised.value.codes == ("coverage_mismatch",)


# ═══ version 3: the chain release BY REFERENCE (PHASE_6J §2) ═══════════════


def published_members():
    """A bucket where every member's version-1 release is published, and the
    root's is live — the state publish-chain leaves before the index."""

    fake = FakeS3()
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    members, bodies = chain(ROOT, MIDDLE, HEAD)
    for m in members:
        own = {o["path"]: bodies[o["path"]] for o in m.release["objects"]}
        publish_release(store, m.release, m.ledger_document, own)
    promote(store, members[0].release, members[0].ledger_document, now=NOW)
    return store, fake, members


def reference_codes(document, index, members):
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_reference_release(document, index, members)
    return raised.value.codes


def test_the_reference_release_is_an_index_of_its_members():
    members, _ = chain(ROOT, MIDDLE, HEAD)
    release, index = cr.build_reference_release(members)
    assert release["schema"] == "araripe.green.release/3"
    assert release["release_id"].startswith("rel-g3-")
    assert [m["release_id"] for m in release["members"]] == [
        m.release["release_id"] for m in members]
    assert all(o["release_id"] in {m.release["release_id"] for m in members}
               for o in release["objects"])
    for m in members:
        mine = [dict(o) for o in release["objects"] if o["release_id"] == m.release["release_id"]]
        assert [{k: v for k, v in o.items() if k != "release_id"} for o in mine] == m.release["objects"]
    assert release["coverage"]["observed_dates"] == [
        "2026-04-07", "2026-04-10", "2026-04-12", "2026-04-15"]
    assert release["state_watermark"]["persistence_state_sha256"] == "3" * 64
    assert index["schema"] == "araripe.green.ledger-index/1"
    assert [e["key"] for e in index["ledgers"]] == [
        f"releases/{m.release['release_id']}/ledger.json" for m in members]
    assert list(schema_validator("green-release-v3").iter_errors(release)) == []
    cr.check_reference_release(release, index, members)


def test_the_reference_identity_pins_each_members_manifest_bytes():
    """A date_product is not sealed by the ledger, so the member's manifest
    digest is what makes the reference point at bytes, not at a name."""

    members, _ = chain(ROOT, MIDDLE, HEAD)
    first = cr.build_reference_release(members)[0]["release_id"]
    assert cr.build_reference_release(members)[0]["release_id"] == first
    edited = deepcopy(members[2].release)
    edited["objects"][0]["content_type"] = "application/json"
    other = [members[0], members[1], cr.ChainMember(edited, members[2].ledger_document)]
    assert cr.build_reference_release(other)[0]["release_id"] != first
    assert cr.build_reference_release(members[:2])[0]["release_id"] != first
    assert cr.reference_release_identity([m.release for m in members[::-1]])[0] != first


def test_the_reference_gate_refuses_every_departure_from_its_members():
    members, _ = chain(ROOT, MIDDLE, HEAD)
    release, index = cr.build_reference_release(members)
    for key, edit in (
        ("dates", lambda d: d["dates"][0].__setitem__("observation_count", 9)),
        ("objects", lambda d: d["objects"][0].__setitem__("release_id", d["members"][2]["release_id"])),
        ("coverage", lambda d: d["coverage"].__setitem__("last_observed_on", "2026-04-12")),
        ("state_watermark", lambda d: d["state_watermark"].__setitem__("persistence_state_bytes", 1)),
        ("ledgers", lambda d: d["ledgers"].__setitem__("bytes", 1)),
    ):
        tampered = deepcopy(release)
        edit(tampered)
        assert "reference_release_does_not_derive_from_its_members" in reference_codes(
            tampered, index, members), key
    tampered = deepcopy(release)
    tampered["members"][1]["release_document_sha256"] = "0" * 64
    assert "member_manifest_mismatch" in reference_codes(tampered, index, members)
    wrong_index = deepcopy(index)
    wrong_index["ledgers"][0]["bytes"] += 1
    assert reference_codes(release, wrong_index, members) == ("ledger_object_mismatch",)
    assert reference_codes(release, index, members[:2]) == ("reference_members_mismatch",)


def test_the_reference_gate_reads_order_and_generation_from_the_members():
    members, _ = chain(ROOT, MIDDLE, HEAD)
    release, index = cr.build_reference_release(members)
    swapped = [members[0], members[2], members[1]]
    with pytest.raises(ReleaseRejected) as raised:
        cr.check_reference_release(dict(release, members=[release["members"][i] for i in (0, 2, 1)]),
                                   index, swapped)
    assert "chain_dates_overlap" in raised.value.codes
    touching, _ = chain(ROOT, {"2026-04-10": [ALERTS]})
    with pytest.raises(ReleaseBuildError, match="chain_dates_overlap"):
        cr.build_reference_release(touching)


def test_a_member_whose_own_release_does_not_check_is_refused_by_reference_too():
    members, _ = chain(ROOT, MIDDLE, HEAD)
    tampered = deepcopy(members[2].release)
    tampered["dates"][0]["observation_count"] += 1
    with pytest.raises(ReleaseRejected) as raised:
        cr.build_reference_release([members[0], members[1],
                                    cr.ChainMember(tampered, members[2].ledger_document)])
    assert raised.value.codes == ("date_accounting_mismatch",)


def test_the_gate_needs_the_members_it_references():
    members, _ = chain(ROOT, MIDDLE, HEAD)
    release, index = cr.build_reference_release(members)
    with pytest.raises(ReleaseBuildError, match="member releases as read from the store"):
        cr.check_release(release, index)


def test_publishing_a_reference_release_writes_only_its_index():
    store, fake, members = published_members()
    release, index = cr.build_reference_release(members)
    before = set(fake.keys())
    ap.publish_release(store, release, index, {})
    added = sorted(set(fake.keys()) - before)
    assert added == [release["release_prefix"] + "ledger.json",
                     release["release_prefix"] + "release.json"]
    assert fake.writes[-1][0] == release["release_prefix"] + "release.json"
    with pytest.raises(cs.ObjectStoreError, match="stores none"):
        ap.publish_release(store, release, index, {"alerts/x.geojson": b"{}"})


def test_a_reference_release_verifies_against_its_members_objects():
    store, fake, members = published_members()
    release, index = cr.build_reference_release(members)
    ap.publish_release(store, release, index, {})
    stored = ap.verify_release(store, release)
    assert len(stored) == len(release["objects"]) + len(release["members"]) + 2
    item = release["objects"][-1]
    key = f"releases/{item['release_id']}/{item['path']}"
    del fake.objects[key]
    with pytest.raises(ap.ReleaseIncomplete) as raised:
        ap.verify_release(store, release)
    assert raised.value.codes == ("release_object_absent",)


def test_a_member_manifest_that_changed_in_the_store_fails_verification():
    store, fake, members = published_members()
    release, index = cr.build_reference_release(members)
    ap.publish_release(store, release, index, {})
    key = f"releases/{release['members'][1]['release_id']}/release.json"
    fake.objects[key] = (fake.body(key) + b" ", "application/json")
    with pytest.raises(ap.ReleaseIncomplete) as raised:
        ap.verify_release(store, release)
    assert raised.value.codes == ("release_object_mismatch",)


def test_the_reference_release_promotes_over_the_live_root_with_nothing_retired():
    store, fake, members = published_members()
    release, index = cr.build_reference_release(members)
    ap.publish_release(store, release, index, {})
    result = promote(store, release, index, now=NOW)
    pointer = json.loads(fake.body(POINTER_KEY))
    assert (result.action, result.sequence) == ("promote", 2)
    assert pointer["release_id"] == release["release_id"]
    assert pointer["tombstones"] == [], "the root's objects are the same objects"
    assert [l["ledger_id"] for l in pointer["ledgers"]] == [
        m["ledger_id"] for m in release["members"]]
    assert list(schema_validator("green-pointer-v2").iter_errors(pointer)) == []
    loaded, loaded_index = ap.load_published_release(store, release["release_id"])
    assert loaded == release and loaded_index == index


def test_a_reference_release_whose_member_is_not_published_is_never_promoted():
    fake = FakeS3()
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    members, bodies = chain(ROOT, MIDDLE, HEAD)
    root = members[0]
    publish_release(store, root.release, root.ledger_document,
                    {o["path"]: bodies[o["path"]] for o in root.release["objects"]})
    promote(store, root.release, root.ledger_document, now=NOW)
    release, index = cr.build_reference_release(members)
    ap.publish_release(store, release, index, {})
    live = fake.body(POINTER_KEY)
    with pytest.raises(cs.ObjectStoreError, match="is absent"):
        promote(store, release, index, now=NOW)
    assert fake.body(POINTER_KEY) == live


def test_rolling_back_from_a_reference_release_tombstones_by_the_real_key():
    store, fake, members = published_members()
    release, index = cr.build_reference_release(members)
    ap.publish_release(store, release, index, {})
    promote(store, release, index, now=NOW)
    rollback(store, members[0].release["release_id"], now=NOW)
    pointer = json.loads(fake.body(POINTER_KEY))
    assert pointer["rolled_back_from"]["release_id"] == release["release_id"]
    retired = [t for t in pointer["tombstones"] if t["reason"] == "absent_from_successor"]
    assert retired, "the head's objects are retired by the rollback"
    for stone in retired:
        assert stone["key"] in fake.objects, "a tombstone names a key that exists"
        assert stone["key"].startswith("releases/rel-g1-")


def test_the_reference_chain_is_read_from_the_bucket_and_writes_nothing():
    fake, members = bucket_with_a_chain()
    store = ri.ReadOnlyStore(fake, cs.STAGING_BUCKET)
    staged = cr.load_reference_chain(store, (CHAIN_ROOT, "ci-1", "ci-2"))
    assert staged.release == cr.build_reference_release(members)[0]
    assert [r.run_id for r in staged.runs] == [CHAIN_ROOT, "ci-1", "ci-2"]
    assert fake.writes == []
    assert "none copied" in cr.describe_reference(staged)


def test_one_path_in_two_members_is_refused_by_reference():
    """Mutation R4: the route's allowlist is keyed by path, so two members
    declaring one path would leave which bytes are served to dictionary order."""

    root, _ = member(ROOT)
    ledger, bodies = build_ledger(HEAD)
    objects = objects_for(ledger, bodies)
    taken = root.release["objects"][0]["path"]
    objects[0] = type(objects[0])(taken, objects[0].body, objects[0].content_type,
                                  objects[0].observed_on, objects[0].acquisition_id)
    clash = build_release(check_processing_ledger(ledger), ledger, objects,
                          persistence_state_sha256="3" * 64, persistence_state_bytes=1)
    with pytest.raises(ReleaseBuildError, match="duplicate_object_path"):
        cr.build_reference_release([root, cr.ChainMember(clash, ledger)])
