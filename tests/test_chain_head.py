"""Which run is the chain's head, who refuses a second child, where the window ends.

``docs/implementation/PHASE_6H_2026-09-28.md`` §1-§3.  As in
``tests/test_state_chain.py``, a refusal is asserted by its *effect* too —
nothing written, the state never read — because a check that raises for the
wrong reason still raises.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from src.publication import state_chain as sc
from src.publication.green_release import sha256_bytes
from src.publication.run_inputs import ReadOnlyStore, RunRejected
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, ZERO, build_ledger

ROOT = Path(__file__).resolve().parents[1]
ROOT_RUN = sc.CHAIN_ROOT


FIXTURE_GENERATION = build_ledger({"2026-04-11": [ZERO]})[0]["algorithm_version"]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "GREEN_ALGORITHM_VERSION"):
        # The fixture ledgers seal another algorithm_version than the green
        # generation's (measured: 2.0.0), and these tests are
        # about the chain, not the generation: the refusal to continue
        # another generation has its own tests in test_green_generation.py.
        module.GREEN_ALGORITHM_VERSION = FIXTURE_GENERATION
    return module


def state_of(run_id: str) -> bytes:
    return f'{{"type":"FeatureCollection","features":[],"run":"{run_id}"}}\n'.encode()


def run_objects(run_id, last_date, *, parent=None, schema=2, parent_sha=None,
                with_run_json=True, with_state=True):
    """One run prefix whose ledger covers ``last_date``."""

    ledger, _ = build_ledger({last_date: [ZERO]})
    state = state_of(run_id)
    document = {
        "schema": f"araripe.green.run/{schema}",
        "run_id": run_id,
        "ledger": "ledger.json",
        "persistence_state": {"sha256": sha256_bytes(state), "bytes": len(state)},
        "objects": [],
    }
    if schema == 2:
        document["predecessor"] = (
            None if parent is None
            else {"run_id": parent,
                  "persistence_state_sha256": parent_sha or sha256_bytes(state_of(parent))}
        )
    objects = {f"runs/{run_id}/ledger.json": (json.dumps(ledger).encode(), "application/json")}
    if with_state:
        objects[f"runs/{run_id}/persistence_state.geojson"] = (state, "application/geo+json")
    if with_run_json:
        objects[f"runs/{run_id}/run.json"] = (json.dumps(document).encode(), "application/json")
    return objects


def bucket(*layouts, page_size=1000):
    objects = {}
    for layout in layouts:
        objects.update(layout)
    fake = FakeS3(objects)
    fake.page_size = page_size
    return ReadOnlyStore(fake, cs.STAGING_BUCKET), fake


def chain(*links):
    """``chain(("a", "2026-09-07"), ("b", "2026-09-22"))`` grows from the root."""

    layouts = [run_objects(ROOT_RUN, "2026-08-30", schema=1)]
    parent = ROOT_RUN
    for run_id, last in links:
        layouts.append(run_objects(run_id, last, parent=parent))
        parent = run_id
    return layouts


# ── the listing ──────────────────────────────────────────────────────────────


def test_the_listing_returns_run_prefixes_across_pages():
    store, _ = bucket(*chain(("ci-1", "2026-09-07"), ("ci-2", "2026-09-22")), page_size=1)
    assert sc.list_run_ids(store) == ["ci-1", "ci-2", ROOT_RUN]


def test_a_truncated_listing_without_a_cursor_is_refused():
    store, fake = bucket(*chain(("ci-1", "2026-09-07")), page_size=1)
    fake.drop_continuation_token = True
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.list_run_ids(store)
    assert excinfo.value.codes == ("run_listing_incomplete",)


def test_the_listing_ignores_everything_outside_runs():
    store, _ = bucket(*chain(), {"releases/x/run.json": (b"{}", "application/json"),
                                 "runsX/y/run.json": (b"{}", "application/json")})
    assert sc.list_run_ids(store) == [ROOT_RUN]


# ── §1 the head ──────────────────────────────────────────────────────────────


def test_the_root_alone_is_the_head():
    store, _ = bucket(*chain())
    assert sc.resolve_head(store).path == (ROOT_RUN,)


def test_the_head_is_the_one_leaf_reached_from_the_root():
    store, fake = bucket(*chain(("ci-1", "2026-09-07"), ("ci-2", "2026-09-22")))
    head = sc.resolve_head(store)
    assert head.path == (ROOT_RUN, "ci-1", "ci-2") and head.run_id == "ci-2"
    assert not [key for key in fake.reads if key.endswith("persistence_state.geojson")], (
        "resolving the head must never download a state"
    )


def test_the_bucket_as_measured_resolves_to_ci_36456671793():
    """PHASE_6H §0: nine run.json, eight roots that are not this chain's."""

    layouts = chain(("ci-36456671793", "2026-09-07"))
    for other in ("ci-36432616599", "gate-p2b-real-a", "gate-p2b-real-b",
                  "gate-p2b-real-c", "proof-a-2026-09-07", "proof-b-older", "proof-c-newer"):
        layouts.append(run_objects(other, "2026-08-30", schema=1))
    layouts.append(run_objects("gate-p2b-real-fail", "2026-08-30", with_run_json=False))
    head = sc.resolve_head(bucket(*layouts)[0])
    assert head.run_id == "ci-36456671793"
    assert len(head.outside) == 7
    assert head.incomplete == ("gate-p2b-real-fail",)


def test_an_empty_start_run_is_a_root_of_its_own_and_not_a_child():
    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("ci-empty", "2026-09-10", parent=None))
    head = sc.resolve_head(bucket(*layouts)[0])
    assert head.run_id == "ci-1" and "ci-empty" in head.outside


def test_a_prefix_without_run_json_is_not_a_run():
    """A deposit writes run.json last: a prefix without it did not finish."""

    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("ci-half", "2026-09-22", parent="ci-1", with_run_json=False))
    head = sc.resolve_head(bucket(*layouts)[0])
    assert head.run_id == "ci-1" and head.incomplete == ("ci-half",)


def test_a_fork_is_refused_naming_both_children():
    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("ci-2", "2026-09-22", parent="ci-1"))
    layouts.append(run_objects("ci-3", "2026-09-22", parent="ci-1"))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.resolve_head(bucket(*layouts)[0])
    assert excinfo.value.codes == ("chain_forked",)
    assert "ci-2" in str(excinfo.value) and "ci-3" in str(excinfo.value)


def test_a_fork_at_the_root_is_refused_too():
    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("ci-2", "2026-09-07", parent=ROOT_RUN))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.resolve_head(bucket(*layouts)[0])
    assert excinfo.value.codes == ("chain_forked",)


def test_a_fork_off_the_chain_does_not_matter():
    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("x-root", "2026-08-30", schema=1))
    layouts.append(run_objects("x-a", "2026-09-07", parent="x-root"))
    layouts.append(run_objects("x-b", "2026-09-07", parent="x-root"))
    assert sc.resolve_head(bucket(*layouts)[0]).run_id == "ci-1"


def test_a_link_that_does_not_match_its_parents_state_is_refused():
    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("ci-2", "2026-09-22", parent="ci-1", parent_sha="e" * 64))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.resolve_head(bucket(*layouts)[0])
    assert excinfo.value.codes == ("predecessor_link_mismatch",)


def test_an_invalid_run_json_anywhere_refuses_the_resolution():
    """It may be exactly the child that makes the apparent head a continued run."""

    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append({"runs/ci-2/run.json": (b'{"schema": "araripe.green.run/2"}', "application/json")})
    with pytest.raises(RunRejected) as excinfo:
        sc.resolve_head(bucket(*layouts)[0])
    assert "run_manifest_invalid" in excinfo.value.codes


def test_an_absent_root_is_refused():
    store, _ = bucket(run_objects("ci-1", "2026-09-07", parent=None))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.resolve_head(store)
    assert excinfo.value.codes == ("chain_root_absent",)


def test_the_root_is_the_seed():
    assert sc.CHAIN_ROOT == "rep-2026-08-30-v3"


# ── §2 the second child ──────────────────────────────────────────────────────


def test_a_continued_predecessor_is_refused_and_its_own_run_is_not_another():
    store, _ = bucket(*chain(("ci-1", "2026-09-07")))
    sc.check_not_continued(store, "ci-1", None)
    sc.check_not_continued(store, ROOT_RUN, "ci-1")  # re-running ci-1's deposit
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.check_not_continued(store, ROOT_RUN, "ci-9")
    assert excinfo.value.codes == ("predecessor_already_continued",)
    assert "ci-1" in str(excinfo.value)
    with pytest.raises(sc.ChainRejected):
        sc.check_not_continued(store, ROOT_RUN, None)


def _detection(tmp_path, pred, last_state_sha):
    ledger, _ = build_ledger({"2026-09-08": [ZERO]})
    (tmp_path / "ledger.json").write_text(json.dumps(ledger))
    (tmp_path / "alerts").mkdir()
    (tmp_path / "persistence_state.geojson").write_bytes(b"new state\n")
    (tmp_path / "predecessor.json").write_text(
        json.dumps({"run_id": pred, "persistence_state_sha256": last_state_sha}))
    return [
        "apply", "--run", "ci-9", "--ledger", str(tmp_path / "ledger.json"),
        "--alerts-dir", str(tmp_path / "alerts"),
        "--state", str(tmp_path / "persistence_state.geojson"),
        "--predecessor", str(tmp_path / "predecessor.json"),
    ]


def test_the_apply_refuses_a_second_child_before_the_first_byte(tmp_path, monkeypatch):
    assemble = load_script("assemble_green_run")
    fake = FakeS3({k: v for layout in chain(("ci-1", "2026-09-07")) for k, v in layout.items()})
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    monkeypatch.setattr(assemble, "build_candidate_store", lambda: store)
    argv = _detection(tmp_path, ROOT_RUN, sha256_bytes(state_of(ROOT_RUN)))
    assert assemble.main(argv) == 1
    assert fake.writes == []


def test_the_apply_asks_again_right_before_run_json(tmp_path, monkeypatch):
    """A sibling that lands mid-deposit — the race the group should prevent.

    The first check passes; the sibling's run.json appears while this run's
    state is being written; the second check must stop this run's run.json.
    """

    assemble = load_script("assemble_green_run")
    fake = FakeS3({k: v for layout in chain(("ci-1", "2026-09-07")) for k, v in layout.items()})
    sibling = run_objects("ci-8", "2026-09-22", parent="ci-1")
    original = fake.put_object

    def racing_put(**kwargs):
        response = original(**kwargs)
        if kwargs["Key"].endswith(sc.STATE_GZIP_PATH):
            fake.objects.update(sibling)
        return response

    fake.put_object = racing_put
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    monkeypatch.setattr(assemble, "build_candidate_store", lambda: store)
    argv = _detection(tmp_path, "ci-1", sha256_bytes(state_of("ci-1")))
    assert assemble.main(argv) == 1
    written = [key for key, _ in fake.writes]
    assert f"runs/ci-9/{sc.STATE_GZIP_PATH}" in written
    assert "runs/ci-9/run.json" not in written, "the commit point must not be written"


def test_the_apply_continues_the_head_and_re_running_it_is_unchanged(tmp_path, monkeypatch):
    assemble = load_script("assemble_green_run")
    fake = FakeS3({k: v for layout in chain(("ci-1", "2026-09-07")) for k, v in layout.items()})
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    monkeypatch.setattr(assemble, "build_candidate_store", lambda: store)
    argv = _detection(tmp_path, "ci-1", sha256_bytes(state_of("ci-1")))
    assert assemble.main(argv) == 0
    assert "runs/ci-9/run.json" in fake.objects
    before = len(fake.writes)
    assert assemble.main(argv) == 0, "re-running the deposit job of the same run"
    assert len(fake.writes) == before
    assert sc.resolve_head(store).run_id == "ci-9"


def test_the_fetch_refuses_a_continued_predecessor_before_the_state(tmp_path):
    fetch = load_script("fetch_green_state")
    store, fake = bucket(*chain(("ci-1", "2026-09-07")))
    with pytest.raises(sc.ChainRejected) as excinfo:
        fetch.fetch(store, ROOT_RUN, "2026-08-31", tmp_path / "out", "ci-9")
    assert excinfo.value.codes == ("predecessor_already_continued",)
    assert f"runs/{ROOT_RUN}/persistence_state.geojson" not in fake.reads
    assert not (tmp_path / "out").exists()
    fetch.fetch(store, "ci-1", "2026-09-08", tmp_path / "ok", "ci-9")
    assert (tmp_path / "ok" / "persistence_state.geojson").read_bytes() == state_of("ci-1")


# ── §3 the automatic window ──────────────────────────────────────────────────


def pred(last):
    return sc.Predecessor("h", "a" * 64, 1, last)


@pytest.mark.parametrize(
    "last, today, window",
    [
        # the queue this package inherits: 20 days, walked as 16 + the rest
        ("2026-09-07", "2026-09-28", ("2026-09-08", "2026-09-24")),
        ("2026-09-22", "2026-09-28", ("2026-09-23", "2026-09-27")),
        # yesterday is never in the window
        ("2026-09-25", "2026-09-28", ("2026-09-26", "2026-09-27")),
        ("2026-09-26", "2026-09-28", None),
        ("2026-09-27", "2026-09-28", None),
        # a head ahead of the settle rule is nothing to do, not an error
        ("2026-09-30", "2026-09-28", None),
        # across a year boundary
        ("2026-12-30", "2027-01-05", ("2026-12-31", "2027-01-04")),
    ],
)
def test_the_automatic_window(last, today, window):
    got = sc.automatic_window(pred(last), today)
    assert (None if got is None else (got.start, got.end)) == window


def test_the_window_is_full_only_at_the_ceiling():
    assert sc.automatic_window(pred("2026-09-07"), "2026-09-28").full
    assert sc.automatic_window(pred("2026-09-07"), "2026-09-28").days == 16
    assert not sc.automatic_window(pred("2026-09-22"), "2026-09-28").full
    fifteen = sc.automatic_window(pred("2026-09-07"), "2026-09-24")
    assert fifteen.days == 15 and not fifteen.full


def test_the_settle_rule_is_the_measured_one():
    """PHASE_6H §0/§3: T - 1 is inside the measured ingestion band, T - 2 is not."""

    assert sc.SETTLE_DAYS == 1


@pytest.mark.parametrize("today", ["", "28/09/2026", None])
def test_a_malformed_today_is_refused(today):
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.automatic_window(pred("2026-09-07"), today)
    assert excinfo.value.codes == ("today_invalid",)


def test_the_automatic_window_always_passes_the_chain_rule():
    """The window a head yields is exactly the one check_window accepts."""

    predecessor = pred("2026-09-07")
    window = sc.automatic_window(predecessor, "2026-09-28")
    sc.check_window(predecessor, window.start)


# ── the lane's resolve step ──────────────────────────────────────────────────


def test_the_resolve_cli_emits_the_head_and_its_window(tmp_path, monkeypatch, capsys):
    resolve = load_script("resolve_chain_head")
    store, fake = bucket(*chain(("ci-36456671793", "2026-09-07")))
    monkeypatch.setattr(resolve, "build_reader", lambda: store)
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert resolve.main(["--today", "2026-09-28"]) == 0
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values == {"nothing_to_do": "false", "from_run": "ci-36456671793",
                      "start": "2026-09-08", "end": "2026-09-24"}
    assert fake.writes == []


def test_the_resolve_cli_says_nothing_to_do_and_succeeds(tmp_path, monkeypatch):
    resolve = load_script("resolve_chain_head")
    store, _ = bucket(*chain(("ci-1", "2026-09-26")))
    monkeypatch.setattr(resolve, "build_reader", lambda: store)
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert resolve.main(["--today", "2026-09-28"]) == 0
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["nothing_to_do"] == "true" and values["from_run"] == "ci-1"
    assert values["start"] == "" and values["end"] == ""


def test_the_resolve_cli_fails_on_a_fork_and_emits_nothing(tmp_path, monkeypatch):
    resolve = load_script("resolve_chain_head")
    layouts = chain(("ci-1", "2026-09-07"))
    layouts.append(run_objects("ci-2", "2026-09-07", parent=ROOT_RUN))
    store, _ = bucket(*layouts)
    monkeypatch.setattr(resolve, "build_reader", lambda: store)
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert resolve.main(["--today", "2026-09-28"]) == 1
    assert not output.exists()
