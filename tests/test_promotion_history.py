"""The durable promotion history (Phase 6, D5): every accepted write leaves a copy.

``docs/implementation/PHASE_6C_2026-09-27.md`` §2 answers four questions in
writing, before any code; these tests are those answers made executable.

* **The order.**  Pointer first, and the version about to be replaced is
  recorded *before* the swap — so a record is never of a write that did not
  happen (H1), and a version is never replaced without its record (H2).  The
  only record that may be missing is the live version's own, and its bytes are
  the live pointer.
* **The key.**  The sequence, and only the sequence: two bodies can never
  share one, so a write made outside the protocol becomes a refusal.
* **The race.**  Enumerated, not argued: every interleaving of the pointer and
  history operations of two real ``promote`` calls, from three starting states.
* **The past.**  The version live before the history existed is recorded,
  byte for byte, by the first move — and the reader calls everything below it
  pre-history, never a gap.

Plus the failure in the middle — the pointer moved and its record could not be
written — which must say the pointer MOVED, and which the natural retry heals.

No network, no clock (``now`` is injected), no credential, no object store.
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from contextlib import contextmanager

import pytest

from src.publication import atomic_publish as ap
from src.publication import conditional_store as cs
from src.publication import promotion_history as history
from src.publication.atomic_publish import (
    HistoryNotRecorded,
    PromotionRefused,
    promote,
    publish_release,
    rollback,
)
from src.publication.conditional_store import (
    ConditionalStore,
    ImmutableObjectConflict,
    ObjectStoreError,
    PreconditionFailed,
)
from src.publication.green_release import POINTER_KEY, release_bytes
from src.publication.run_inputs import ReadOnlyStore
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, ZERO
from tests.test_atomic_publish import CI, LATER, NOW, make_release, pointer_of

#: Three releases with rising coverage, and a fourth covering the same dates
#: as the third — so a promotion between those two is allowed in either order.
#: Each covers every date of the one before: a promotion that retires a
#: published date is refused (``coverage_dates_dropped``, PHASE_6I §3).
OLD = {"2026-04-07": [ALERTS]}
MID = {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]}
NEW = {"2026-04-07": [ALERTS], "2026-04-10": [ZERO], "2026-04-13": [ALERTS]}
NEW_TOO = {"2026-04-07": [ALERTS], "2026-04-10": [ZERO], "2026-04-13": [ALERTS, ALERTS]}


def _store(**kwargs):
    fake = FakeS3(**kwargs)
    return ConditionalStore(fake, cs.STAGING_BUCKET), fake


def _publish(store, spec):
    release, document, bodies = make_release(spec)
    publish_release(store, release, document, bodies)
    return release, document


def _keys(fake):
    return [key for key in fake.keys() if key.startswith(history.HISTORY_ROOT)]


def _record(fake, sequence):
    return fake.body(history.history_key(sequence))


def _read(store, *, keys=None):
    live, stored = ap.read_live_pointer(store)
    return history.read_history(
        store, live, stored.body if stored is not None else None, keys=keys
    )


def _seed_prehistory_pointer(store, fake, *, at=10):
    """The state of ``araripe-v2-staging`` today: a live pointer at sequence 10
    that old code wrote, and no history at all.

    Built with the real code and then renumbered, so the seeded pointer is a
    schema-valid version whose ``supersedes`` names the release really live
    one sequence below it — as the live pointer does (``rel-g1-24db9555…`` at
    sequence 9).  Returns ``(before, live)`` releases and the seeded bytes.
    """

    before, doc_before = _publish(store, OLD)
    live, doc_live = _publish(store, MID)
    promote(store, before, doc_before, now=NOW)
    promote(store, live, doc_live, now=NOW)
    pointer = pointer_of(fake)
    pointer["sequence"] = at
    pointer["supersedes"]["sequence"] = at - 1
    seeded = release_bytes(pointer)
    fake.objects[POINTER_KEY] = (seeded, "application/json")
    for key in _keys(fake):
        del fake.objects[key]
    return (before, doc_before), (live, doc_live), seeded


# ── the key: the sequence, and nothing else ──────────────────────────────────


def test_the_key_is_the_sequence_zero_padded_and_nothing_else():
    assert history.history_key(1) == "pointers/green/history/0000000001.json"
    assert history.history_key(11) == "pointers/green/history/0000000011.json"
    numbers = [1, 2, 9, 10, 11, 99, 100, 12345]
    assert sorted(history.history_key(n) for n in numbers) == [
        history.history_key(n) for n in sorted(numbers)
    ], "a lexicographic listing must be the numeric order"


@pytest.mark.parametrize("bad", [0, -1, True, 10**10, "3", 2.0, None])
def test_a_sequence_outside_the_key_space_has_no_key(bad):
    with pytest.raises(ValueError):
        history.history_key(bad)


@pytest.mark.parametrize(
    "key,expected",
    [
        ("pointers/green/history/0000000011.json", 11),
        ("pointers/green/history/0000000001.json", 1),
        ("pointers/green/history/0000000000.json", None),
        ("pointers/green/history/11.json", None),
        ("pointers/green/history/00000000011.json", None),
        ("pointers/green/history/0000000011.json.bak", None),
        ("pointers/green/current.json", None),
        ("releases/rel-g1-x/0000000011.json", None),
    ],
)
def test_only_a_well_formed_key_names_a_sequence(key, expected):
    assert history.sequence_of(key) == expected


def test_two_different_bodies_can_never_share_a_sequence():
    """The tripwire: the key depends on the sequence only, so a second body for
    one sequence collides — and the same body again is a no-op.
    """

    store, _ = _store()
    assert history.record(store, 5, b'{"a":1}\n').result == "created"
    assert history.record(store, 5, b'{"a":1}\n').result == "unchanged"
    with pytest.raises(ImmutableObjectConflict):
        history.record(store, 5, b'{"a":2}\n')


# ── every accepted write leaves its exact bytes ──────────────────────────────


def test_every_accepted_write_leaves_its_exact_bytes():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)

    first = promote(store, old, doc_old, now=NOW, promoted_by=CI)
    assert _record(fake, 1) == fake.body(POINTER_KEY)
    assert first.new_record.result == "created"
    assert first.live_record is None, "an empty pointer has no version to record"

    second = promote(store, new, doc_new, now=LATER, promoted_by=CI)
    assert _record(fake, 2) == fake.body(POINTER_KEY)
    assert second.live_record.result == "unchanged", "sequence 1 recorded itself"

    back = rollback(store, old["release_id"], now=LATER, promoted_by=CI)
    assert back.action == "rollback"
    assert _record(fake, 3) == fake.body(POINTER_KEY)
    assert _keys(fake) == [history.history_key(n) for n in (1, 2, 3)]


def test_the_record_is_the_pointer_itself_not_an_envelope():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    promote(store, old, doc_old, now=NOW)
    document = json.loads(_record(fake, 1))
    assert document == pointer_of(fake)
    assert document["schema"] == "araripe.green.pointer/2"


# ── step 1: no version is replaced before its record exists ──────────────────


def test_no_version_is_replaced_before_its_record_exists():
    """H2, observed at the instant of the swap rather than after the fact.

    The live version's record is removed first — the state a failed step 3
    leaves, and the state of the real bucket before this package — so the
    only way the record can exist when the swap happens is step 1.
    """

    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    live_bytes = fake.body(POINTER_KEY)
    del fake.objects[history.history_key(1)]

    seen = []
    real_put = fake.put_object

    def watching_put(Bucket, Key, Body, ContentType=None, IfNoneMatch=None, IfMatch=None):
        if Key == POINTER_KEY and IfMatch is not None:
            key = history.history_key(1)
            seen.append(fake.objects.get(key, (None,))[0])
        return real_put(
            Bucket=Bucket, Key=Key, Body=Body, ContentType=ContentType,
            IfNoneMatch=IfNoneMatch, IfMatch=IfMatch,
        )

    fake.put_object = watching_put
    result = promote(store, new, doc_new, now=LATER)
    assert seen == [live_bytes], "the swap ran before the replaced version was recorded"
    assert result.live_record.result == "created"


def test_the_version_live_before_the_history_existed_is_recorded_by_the_first_move():
    """The real bucket's state: sequence 10, written by old code, no record.

    The first move under the new code copies it — byte for byte, from the
    store — so the history begins at sequence 10 with the original bytes, not
    with a reconstruction.
    """

    store, fake = _store()
    _, (live, _doc), seeded = _seed_prehistory_pointer(store, fake)
    assert _keys(fake) == []

    new, doc_new = _publish(store, NEW)
    result = promote(store, new, doc_new, now=LATER)
    assert (result.action, result.sequence) == ("promote", 11)
    assert result.live_record.result == "created"
    assert _record(fake, 10) == seeded
    assert _record(fake, 11) == fake.body(POINTER_KEY)
    assert _keys(fake) == [history.history_key(10), history.history_key(11)]


def test_the_record_copies_the_bytes_read_never_a_re_encoding():
    """A copy must not depend on this code's serializer agreeing with the writer.

    The live pointer here is stored pretty-printed — schema-valid, and not the
    canonical encoding this code would produce.  Its record is still those
    exact bytes.
    """

    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    pretty = (json.dumps(pointer_of(fake), indent=2) + "\n").encode()
    assert pretty != release_bytes(pointer_of(fake))
    fake.objects[POINTER_KEY] = (pretty, "application/json")
    del fake.objects[history.history_key(1)]

    promote(store, new, doc_new, now=LATER)
    assert _record(fake, 1) == pretty


# ── a refusal writes nothing, even where step 1 would have had work to do ────


def test_a_refused_promotion_writes_nothing_even_when_the_live_record_is_pending():
    """Every refusal happens before step 1.

    The live record is removed, so step 1 *would* create it — which makes a
    refusal that ran after step 1 visible as one written object.
    """

    store, fake = _store()
    new, doc_new = _publish(store, NEW)
    old, doc_old = _publish(store, OLD)
    promote(store, new, doc_new, now=NOW)
    del fake.objects[history.history_key(1)]
    writes = list(fake.writes)

    with pytest.raises(PromotionRefused) as raised:
        promote(store, old, doc_old, now=LATER)
    assert raised.value.codes == ("coverage_regression",)
    assert fake.writes == writes
    assert _keys(fake) == []


def test_an_invalid_pointer_is_refused_before_anything_is_written():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    del fake.objects[history.history_key(1)]
    writes = list(fake.writes)

    with pytest.raises(PromotionRefused) as raised:
        promote(store, new, doc_new, now=LATER, promoted_by={"workflow": 5})
    assert raised.value.codes == ("pointer_schema_invalid",)
    assert fake.writes == writes


def test_a_rollback_with_nothing_live_writes_nothing():
    store, fake = _store()
    old, _ = _publish(store, OLD)
    writes = list(fake.writes)
    with pytest.raises(PromotionRefused):
        rollback(store, old["release_id"], now=NOW)
    assert fake.writes == writes


# ── the swap failed: no record of its own sequence ───────────────────────────


def test_a_swap_that_fails_leaves_no_record_of_its_sequence():
    """H1 at the one moment it could break: a record written before the swap
    would survive the swap's failure as a record of a write that never
    happened — and hold that sequence's key for good.
    """

    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)

    fake.fail_on = {POINTER_KEY}
    with pytest.raises(ObjectStoreError):
        promote(store, new, doc_new, now=LATER)
    fake.fail_on = set()

    assert _keys(fake) == [history.history_key(1)]
    assert pointer_of(fake)["sequence"] == 1


def test_the_loser_of_a_race_leaves_no_object_of_its_own():
    """The racing writer of ``test_a_pointer_write_that_loses_the_race_does_not_clobber``,
    now asked what it left behind: nothing but a correct record of the version
    both read.
    """

    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    loser, doc_loser = _publish(store, NEW)
    winner, doc_winner = _publish(store, NEW_TOO)
    promote(store, old, doc_old, now=NOW)

    real_get = fake.get_object

    def racing_get(Bucket, Key):
        response = real_get(Bucket=Bucket, Key=Key)
        if Key == POINTER_KEY and not getattr(racing_get, "fired", False):
            racing_get.fired = True
            promote(store, winner, doc_winner, now=LATER)
        return response

    fake.get_object = racing_get
    with pytest.raises(PreconditionFailed):
        promote(store, loser, doc_loser, now=LATER)
    fake.get_object = real_get

    assert _keys(fake) == [history.history_key(1), history.history_key(2)]
    assert json.loads(_record(fake, 2))["release_id"] == winner["release_id"]
    assert _record(fake, 2) == fake.body(POINTER_KEY)


# ── step 3 failed: the pointer MOVED, and it says so ─────────────────────────


def _moved_without_record():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    fake.fail_on = {history.history_key(2)}
    with pytest.raises(HistoryNotRecorded) as raised:
        promote(store, new, doc_new, now=LATER, promoted_by=CI)
    fake.fail_on = set()
    return store, fake, (old, doc_old), (new, doc_new), raised.value


def test_a_record_that_cannot_be_written_after_the_swap_says_the_pointer_moved():
    store, fake, _old, (new, _), error = _moved_without_record()
    assert pointer_of(fake)["release_id"] == new["release_id"]
    assert pointer_of(fake)["sequence"] == 2
    assert (error.promotion.action, error.promotion.sequence) == ("promote", 2)
    assert error.promotion.release_id == new["release_id"]
    assert "MOVED" in str(error)
    assert "no reason to roll it back" in str(error)
    assert isinstance(error, ObjectStoreError), "the CLI's failure path catches it"
    assert _keys(fake) == [history.history_key(1)]


def test_re_running_that_promotion_completes_the_record():
    """The natural retry is the repair: ``unchanged`` records the live version."""

    store, fake, _old, (new, doc_new), _ = _moved_without_record()
    writes = len(fake.writes)
    again = promote(store, new, doc_new, now=LATER)
    assert again.action == "unchanged"
    assert again.live_record.result == "created"
    assert _record(fake, 2) == fake.body(POINTER_KEY)
    assert len(fake.writes) == writes + 1, "exactly the missing record, nothing else"


def test_rolling_back_to_the_live_release_also_completes_a_pending_record():
    """``rollback`` has its own ``unchanged`` path, and it repairs the same way."""

    store, fake, _old, (new, _), _ = _moved_without_record()
    again = rollback(store, new["release_id"], now=LATER)
    assert again.action == "unchanged"
    assert again.live_record.result == "created"
    assert _record(fake, 2) == fake.body(POINTER_KEY)


def test_the_next_move_records_a_pending_version_before_replacing_it():
    store, fake, (old, _), _new, _ = _moved_without_record()
    moved_bytes = fake.body(POINTER_KEY)
    back = rollback(store, old["release_id"], now=LATER)
    assert back.live_record.result == "created"
    assert _record(fake, 2) == moved_bytes
    assert _keys(fake) == [history.history_key(n) for n in (1, 2, 3)]


def test_a_rollback_whose_record_fails_says_the_pointer_moved_too():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    promote(store, new, doc_new, now=LATER)
    fake.fail_on = {history.history_key(3)}
    with pytest.raises(HistoryNotRecorded) as raised:
        rollback(store, old["release_id"], now=LATER)
    assert raised.value.promotion.action == "rollback"
    assert pointer_of(fake)["sequence"] == 3


# ── a history that contradicts the pointer stops everything ──────────────────


def test_a_history_that_contradicts_the_live_pointer_stops_the_move():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    before = fake.body(POINTER_KEY)
    fake.objects[history.history_key(1)] = (b'{"not":"the pointer"}\n', "application/json")

    with pytest.raises(PromotionRefused) as raised:
        promote(store, new, doc_new, now=LATER)
    assert raised.value.codes == ("history_contradicts_the_pointer",)
    assert fake.body(POINTER_KEY) == before
    assert _keys(fake) == [history.history_key(1)]


def test_a_repeated_promotion_on_a_contradicted_history_is_refused_not_silent():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    promote(store, old, doc_old, now=NOW)
    fake.objects[history.history_key(1)] = (b'{"not":"the pointer"}\n', "application/json")
    with pytest.raises(PromotionRefused) as raised:
        promote(store, old, doc_old, now=LATER)
    assert raised.value.codes == ("history_contradicts_the_pointer",)


def test_repeating_a_promotion_creates_nothing_when_its_record_exists():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    promote(store, old, doc_old, now=NOW)
    writes = list(fake.writes)
    again = promote(store, old, doc_old, now=LATER)
    assert again.action == "unchanged"
    assert again.live_record.result == "unchanged"
    assert again.new_record is None
    assert fake.writes == writes


# ── one writer of the pointer, or H2 means nothing ───────────────────────────


def _mutating_pointer_calls():
    """Every call to a pointer-moving store method in src/ and scripts/, by
    (file, enclosing function).  Read with ``ast``, so a docstring or a
    comment naming the methods is not mistaken for a call.
    """

    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    found = set()
    for path in sorted([*root.glob("src/**/*.py"), *root.glob("scripts/*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"put_if_match", "put_if_pointer_absent"}
                ):
                    found.add((path.relative_to(root).as_posix(), function.name))
    return found


def test_the_pointer_has_exactly_one_writer_and_it_keeps_the_history():
    """H2 holds only if every pointer write goes through the protocol.

    A second function that swapped ``pointers/green/current.json`` on its own
    would replace versions without recording them, and nothing else in this
    file would notice.  The one other caller is the identity probe, which swaps
    a key of its own under ``promotion-identity-probe/`` — and never names the
    pointer.
    """

    assert _mutating_pointer_calls() == {
        ("src/publication/atomic_publish.py", "_move_pointer"),
        ("scripts/probe_promotion_identity.py", "main"),
    }
    from pathlib import Path

    probe = Path(__file__).resolve().parents[1] / "scripts" / "probe_promotion_identity.py"
    source = probe.read_text(encoding="utf-8")
    assert "POINTER_KEY" not in source and "pointers/green" not in source


# ── the race, enumerated ─────────────────────────────────────────────────────


class Turns:
    """Run the pointer and history operations of two threads in a given order.

    Every ``get`` of the pointer and every ``put`` of the pointer or of a
    history record takes one turn, and holds it until the operation returns,
    so each schedule is one exact interleaving of those operations.  Reads of
    immutable release objects run freely: nothing can change them.
    """

    def __init__(self, order):
        self.order = list(order)
        self.cond = threading.Condition()
        self.finished = set()

    def _head(self):
        while self.order and self.order[0] in self.finished:
            self.order.pop(0)
        return self.order[0] if self.order else None

    @contextmanager
    def turn(self, name):
        deadline = time.monotonic() + 10
        with self.cond:
            while self._head() not in (None, name):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"schedule stalled waiting for {name}")
                self.cond.wait(remaining)
        try:
            yield
        finally:
            with self.cond:
                if self.order and self.order[0] == name:
                    self.order.pop(0)
                self.cond.notify_all()

    def finish(self, name):
        with self.cond:
            self.finished.add(name)
            self.cond.notify_all()


STARTS = ("empty", "recorded", "pending")


def _race(start, schedule):
    store, fake = _store()
    initial = None
    if start != "empty":
        base, doc_base = _publish(store, OLD)
        promote(store, base, doc_base, now=NOW)
        if start == "pending":
            del fake.objects[history.history_key(1)]
        initial = (1, fake.body(POINTER_KEY))
    racers = {"A": _publish(store, NEW), "B": _publish(store, NEW_TOO)}
    now = {"A": NOW, "B": LATER}

    turns = Turns(schedule)
    accepted = []
    names = threading.local()
    real_get, real_put = fake.get_object, fake.put_object

    def get(Bucket, Key):
        if Key != POINTER_KEY:
            return real_get(Bucket=Bucket, Key=Key)
        with turns.turn(names.name):
            return real_get(Bucket=Bucket, Key=Key)

    def put(Bucket, Key, Body, ContentType=None, IfNoneMatch=None, IfMatch=None):
        with turns.turn(names.name):
            response = real_put(
                Bucket=Bucket, Key=Key, Body=Body, ContentType=ContentType,
                IfNoneMatch=IfNoneMatch, IfMatch=IfMatch,
            )
            if Key == POINTER_KEY:
                accepted.append((json.loads(Body)["sequence"], Body))
            return response

    fake.get_object, fake.put_object = get, put
    outcomes = {}

    def run(name):
        names.name = name
        release, document = racers[name]
        try:
            outcomes[name] = promote(store, release, document, now=now[name])
        except Exception as exc:  # noqa: BLE001 - the assertion names it
            outcomes[name] = exc
        finally:
            turns.finish(name)

    threads = [threading.Thread(target=run, args=(name,)) for name in racers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), f"schedule {schedule} hung"
    fake.get_object, fake.put_object = real_get, real_put
    return fake, initial, accepted, outcomes


def _schedules(turns_each=4):
    seen = set()
    for positions in itertools.combinations(range(2 * turns_each), turns_each):
        order = "".join("A" if i in positions else "B" for i in range(2 * turns_each))
        if order not in seen:
            seen.add(order)
            yield order


@pytest.mark.parametrize("start", STARTS)
def test_every_interleaving_of_two_promoters_keeps_both_invariants(start):
    """§2.3 of the design, checked in all 70 schedules from each start.

    Four operations per promoter at most — read the pointer, record the live
    version, swap, record the new one — so eight slots, four each, cover every
    interleaving.  In every schedule:

    * each promoter either promotes or loses the swap, and nothing else;
    * H1 — every record is the exact bytes of an accepted write at its
      sequence (so the loser left no record of its own);
    * H2 — every version that was replaced has its record;
    * and with nothing failing, every version has one, the live one included.
    """

    for schedule in _schedules():
        fake, initial, accepted, outcomes = _race(start, schedule)
        for name, outcome in outcomes.items():
            assert isinstance(outcome, (ap.Promotion, PreconditionFailed)), (
                f"{start}/{schedule}: {name} raised {outcome!r}"
            )
        winners = [o for o in outcomes.values() if isinstance(o, ap.Promotion)]
        assert winners, f"{start}/{schedule}: nobody promoted"

        versions = dict(accepted)
        assert len(versions) == len(accepted), "one body per sequence"
        if initial is not None:
            versions.setdefault(initial[0], initial[1])
        for key in _keys(fake):
            sequence = history.sequence_of(key)
            assert fake.body(key) == versions.get(sequence), (
                f"{start}/{schedule}: {key} is not the bytes accepted at "
                f"sequence {sequence}"
            )
        assert sorted(history.sequence_of(k) for k in _keys(fake)) == sorted(versions)
        live = json.loads(fake.body(POINTER_KEY))["sequence"]
        assert live == max(versions)


def test_the_race_really_produces_both_outcomes():
    """A schedule enumeration whose every run ended the same way would prove
    nothing about losing.  Among the 70 schedules from a recorded pointer, some
    serialize the two promoters and some make one of them lose the swap.
    """

    results = set()
    for schedule in _schedules():
        _fake, _initial, _accepted, outcomes = _race("recorded", schedule)
        results.add(tuple(sorted(type(o).__name__ for o in outcomes.values())))
    assert ("PreconditionFailed", "Promotion") in results
    assert ("Promotion", "Promotion") in results


# ── the reader ───────────────────────────────────────────────────────────────


def _three_writes():
    store, fake = _store()
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    promote(store, new, doc_new, now=LATER)
    rollback(store, old["release_id"], now=LATER)
    return store, fake, old, new


def _tamper(fake, sequence, **changes):
    document = json.loads(_record(fake, sequence))
    for path, value in changes.items():
        target = document
        *parents, leaf = path.split("__")
        for parent in parents:
            target = target[parent]
        target[leaf] = value
    fake.objects[history.history_key(sequence)] = (release_bytes(document), "application/json")


def test_the_reader_sees_every_version_in_order():
    store, fake, old, new = _three_writes()
    found = _read(store)
    assert found.consistent, found.findings
    assert [(e.sequence, e.action, e.release_id) for e in found.entries] == [
        (1, "promote", old["release_id"]),
        (2, "promote", new["release_id"]),
        (3, "rollback", old["release_id"]),
    ]
    assert found.first_recorded == 1
    assert found.predecessor is None
    assert not found.live_record_pending
    assert found.sequences_of(old["release_id"]) == (1, 3)
    assert found.release_ids() == {old["release_id"], new["release_id"]}


def test_the_reader_writes_nothing():
    store, fake, *_ = _three_writes()
    writes = list(fake.writes)
    history.read_history(ReadOnlyStore(fake, cs.STAGING_BUCKET), *_live(store))
    assert fake.writes == writes


def _live(store):
    live, stored = ap.read_live_pointer(store)
    return live, stored.body


def test_a_pending_live_record_is_reported_and_is_not_a_finding():
    store, fake, _old, (new, _), _ = _moved_without_record()
    found = _read(store)
    assert found.consistent, found.findings
    assert found.live_record_pending
    assert found.entries[-1].sequence == 2
    assert found.entries[-1].recorded is False
    assert found.entries[-1].release_id == new["release_id"]


def test_before_any_record_the_live_pointer_is_the_whole_history():
    """Today's bucket, read: one pending entry, and the one pre-history fact
    the store keeps — which release was live at sequence 9.
    """

    store, fake = _store()
    (before, _), (live, _), _seeded = _seed_prehistory_pointer(store, fake)
    found = _read(store)
    assert found.consistent, found.findings
    assert found.first_recorded is None
    assert [(e.sequence, e.recorded) for e in found.entries] == [(10, False)]
    assert found.predecessor["release_id"] == before["release_id"]
    assert found.predecessor["sequence"] == 9


def test_sequences_below_the_first_record_are_prehistory_not_gaps():
    store, fake = _store()
    (before, _), (live, _), _seeded = _seed_prehistory_pointer(store, fake)
    new, doc_new = _publish(store, NEW)
    promote(store, new, doc_new, now=LATER)
    found = _read(store)
    assert found.consistent, found.findings
    assert found.first_recorded == 10
    assert [e.sequence for e in found.entries] == [10, 11]
    assert found.predecessor["release_id"] == before["release_id"]


def test_a_missing_record_between_the_first_and_the_live_is_a_gap():
    store, fake, *_ = _three_writes()
    del fake.objects[history.history_key(2)]
    found = _read(store)
    assert [f.code for f in found.findings] == ["history_gap"]
    assert found.findings[0].path == history.history_key(2)


def test_a_record_that_differs_from_the_live_pointer_is_a_finding():
    store, fake, *_ = _three_writes()
    _tamper(fake, 3, promoted_utc="2020-01-01T00:00:00Z")
    found = _read(store)
    assert "history_record_differs_from_the_live_pointer" in [f.code for f in found.findings]


def test_a_record_naming_the_wrong_predecessor_breaks_the_chain():
    store, fake, old, new = _three_writes()
    _tamper(fake, 2, supersedes__release_id=new["release_id"])
    found = _read(store)
    assert [f.code for f in found.findings] == ["history_chain_broken"]
    assert found.findings[0].path == history.history_key(2)


def test_a_record_naming_the_wrong_predecessor_coverage_breaks_the_chain():
    store, fake, *_ = _three_writes()
    _tamper(fake, 2, supersedes__last_observed_on="2026-01-01")
    assert [f.code for f in _read(store).findings] == ["history_chain_broken"]


def test_a_record_skipping_a_sequence_breaks_the_chain_on_its_own():
    """Checked on the record alone, so it holds for the first record too,
    whose predecessor is not in the store.
    """

    store, fake, *_ = _three_writes()
    _tamper(fake, 2, supersedes__sequence=7)
    assert [f.code for f in _read(store).findings] == ["history_chain_broken"]


def test_a_rollback_that_does_not_name_what_it_left_breaks_the_chain():
    store, fake, old, new = _three_writes()
    _tamper(fake, 3, rolled_back_from__release_id=old["release_id"])
    # the live pointer carries the same defect, so the one finding is the chain
    fake.objects[POINTER_KEY] = (_record(fake, 3), "application/json")
    assert [f.code for f in _read(store).findings] == ["history_chain_broken"]


def test_the_first_write_must_have_replaced_nothing():
    store, fake, old, new = _three_writes()
    _tamper(
        fake, 1,
        supersedes={"release_id": new["release_id"], "sequence": 1,
                    "last_observed_on": "2026-04-13"},
    )
    found = _read(store)
    assert [f.code for f in found.findings] == ["history_chain_broken"]
    assert found.findings[0].path == history.history_key(1)


def test_a_record_above_the_live_pointer_is_an_orphan_and_only_a_listing_sees_it():
    store, fake, *_ = _three_writes()
    orphan = json.loads(_record(fake, 3))
    orphan["sequence"] = 5
    orphan["supersedes"]["sequence"] = 4
    fake.objects[history.history_key(5)] = (release_bytes(orphan), "application/json")

    listed = _read(store, keys=_keys(fake))
    assert [f.code for f in listed.findings] == ["history_record_above_the_live_pointer"]
    walked = _read(store)
    assert walked.consistent, "a walk to the live sequence cannot see above it"


def test_a_record_that_is_not_a_pointer_is_a_finding():
    store, fake, *_ = _three_writes()
    fake.objects[history.history_key(2)] = (b"not json", "application/json")
    codes = [f.code for f in _read(store).findings]
    assert codes == ["history_record_not_a_pointer", "history_gap"]


@pytest.mark.parametrize(
    "change",
    [
        {"note": "a field the pointer schema does not allow"},
        {"schema": "araripe.green.pointer/3"},
        {"release_id": "rel-g1-not-a-digest"},
    ],
    ids=["extra-field", "other-contract", "malformed-release-id"],
)
def test_a_record_that_parses_but_is_not_a_valid_pointer_is_a_finding(change):
    """Found by mutation: the only "not a pointer" case used to be bytes that
    are not JSON at all, so skipping the schema check for anything that looked
    like a pointer — a dict with a ``sequence`` — survived.  A record that
    parses, carries its sequence, and still breaks the contract is the case the
    check exists for.
    """

    store, fake, *_ = _three_writes()
    document = json.loads(_record(fake, 2))
    document.update(change)
    fake.objects[history.history_key(2)] = (release_bytes(document), "application/json")
    codes = [f.code for f in _read(store).findings]
    assert codes == ["history_record_not_a_pointer", "history_gap"]


def test_a_record_stored_under_another_sequence_is_a_finding():
    store, fake, *_ = _three_writes()
    fake.objects[history.history_key(2)] = (_record(fake, 1), "application/json")
    codes = [f.code for f in _read(store).findings]
    assert codes == ["history_record_sequence_mismatch", "history_gap"]


def test_a_malformed_key_under_the_root_is_a_finding():
    store, fake, *_ = _three_writes()
    keys = _keys(fake) + [history.HISTORY_ROOT + "notes.json"]
    codes = [f.code for f in _read(store, keys=keys).findings]
    assert codes == ["history_key_malformed"]


def test_a_history_with_no_pointer_at_all_is_all_orphans():
    store, fake, *_ = _three_writes()
    del fake.objects[POINTER_KEY]
    found = _read(store, keys=_keys(fake))
    assert [f.code for f in found.findings] == [
        "history_record_above_the_live_pointer"
    ] * 3
    assert found.entries == ()


def test_describe_leads_with_the_verdict_a_reader_needs():
    store, fake, *_ = _three_writes()
    assert "verdict          : consistent" in history.describe(_read(store))
    del fake.objects[history.history_key(2)]
    text = history.describe(_read(store))
    assert "INCONSISTENT — 1 finding(s)" in text
    assert "history_gap" in text


# ── the re-proof plan, rehearsed ─────────────────────────────────────────────


def test_the_re_proof_plan_rehearsed_against_the_fake_store():
    """The CI re-proof of ``PHASE_6C_2026-09-27.md`` §6, step for step, from
    the bucket's real starting state — a sequence-10 pointer with no history.

    Promote, roll back, promote again, repeat (a no-op), be refused, and
    promote the original back: five pointer versions, five records, nothing
    written by the no-op or by the refusal, and the history naming every
    release that was live, in order.
    """

    store, fake = _store()
    (gate_b, _), (candidate, doc_candidate), seeded = _seed_prehistory_pointer(store, fake)
    # Gate C covers exactly the candidate's dates (2026-04-07 and 2026-04-10)
    # with other content, as rel-g1-2ddb10c7… and rel-g1-fb722b2d… both cover
    # through 2026-08-30 — which is what lets each be promoted over the other
    # without a rollback. Covering only the candidate's LAST date is no longer
    # enough: that would retire 2026-04-07 (coverage_dates_dropped, PHASE_6I §3).
    gate_c, doc_gate_c = _publish(store, {"2026-04-07": [ALERTS], "2026-04-10": [ALERTS]})
    gate_a, doc_gate_a = _publish(store, {"2026-04-01": [ALERTS]})
    plan = []

    plan.append(promote(store, gate_c, doc_gate_c, now=NOW))
    plan.append(rollback(store, gate_b["release_id"], now=NOW))
    plan.append(promote(store, gate_c, doc_gate_c, now=LATER))
    writes = list(fake.writes)
    plan.append(promote(store, gate_c, doc_gate_c, now=LATER))
    assert fake.writes == writes, "the repeated promotion wrote something"
    with pytest.raises(PromotionRefused) as refused:
        promote(store, gate_a, doc_gate_a, now=LATER)
    assert refused.value.codes == ("coverage_regression",)
    assert fake.writes == writes, "the refused promotion wrote something"
    plan.append(promote(store, candidate, doc_candidate, now=LATER))

    assert [(p.action, p.sequence) for p in plan] == [
        ("promote", 11), ("rollback", 12), ("promote", 13),
        ("unchanged", 13), ("promote", 14),
    ]
    assert _record(fake, 10) == seeded
    found = _read(store, keys=_keys(fake))
    assert found.consistent, found.findings
    assert [(e.sequence, e.release_id) for e in found.entries] == [
        (10, candidate["release_id"]),
        (11, gate_c["release_id"]),
        (12, gate_b["release_id"]),
        (13, gate_c["release_id"]),
        (14, candidate["release_id"]),
    ]
    assert all(e.recorded for e in found.entries)


# ── the CLI ──────────────────────────────────────────────────────────────────


@pytest.fixture
def cli(monkeypatch):
    from tests.test_promotion_lane import publish_cli

    store, fake = _store()
    monkeypatch.setattr(publish_cli, "build_store", lambda: store)
    return publish_cli, store, fake


def test_the_cli_reports_both_records_of_a_move(cli, capsys):
    publish_cli, store, fake = cli
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    promote(store, new, doc_new, now=LATER)
    assert publish_cli.main(["rollback", "--to", old["release_id"]]) == 0
    out = capsys.readouterr().out
    assert f"pointer  : rollback -> {old['release_id']} at sequence 3" in out
    assert (
        f"history  : sequence 2 (replaced) already recorded at "
        f"{history.history_key(2)}" in out
    )
    assert f"history  : sequence 3 (new) recorded now at {history.history_key(3)}" in out


def test_the_cli_says_the_pointer_moved_when_its_record_fails(cli, capsys):
    publish_cli, store, fake = cli
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    promote(store, new, doc_new, now=LATER)
    fake.fail_on = {history.history_key(3)}
    assert publish_cli.main(["rollback", "--to", old["release_id"]]) == 1
    captured = capsys.readouterr()
    assert f"pointer  : rollback -> {old['release_id']} at sequence 3" in captured.out
    assert "HistoryNotRecorded" in captured.err
    assert "the pointer MOVED" in captured.err


def test_the_history_mode_prints_the_chain_and_writes_nothing(cli, capsys):
    publish_cli, store, fake = cli
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    promote(store, new, doc_new, now=LATER)
    writes = list(fake.writes)
    assert publish_cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "live sequence    : 2" in out
    assert "verdict          : consistent" in out
    assert fake.writes == writes


def test_the_history_mode_fails_on_an_inconsistent_history(cli, capsys):
    publish_cli, store, fake = cli
    old, doc_old = _publish(store, OLD)
    new, doc_new = _publish(store, NEW)
    promote(store, old, doc_old, now=NOW)
    promote(store, new, doc_new, now=LATER)
    fake.objects[history.history_key(2)] = (b"{}", "application/json")
    assert publish_cli.main(["history"]) == 1
    assert "INCONSISTENT" in capsys.readouterr().out
