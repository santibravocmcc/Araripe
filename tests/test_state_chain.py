"""Where a run's persistence state lives, and how the next run continues it.

``docs/implementation/PHASE_6G_2026-09-28.md`` §1-§4.  Every refusal here is
asserted by its *effect* as well as its code — nothing written, the state never
read — because a check that raises for the wrong reason still raises
(``teste-pode-passar-pelo-motivo-errado``).
"""

from __future__ import annotations

import importlib.util
import gzip
import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from src.publication import conditional_store as cs
from src.publication import run_assembler as ra
from src.publication import state_chain as sc
from src.publication.green_release import sha256_bytes
from src.publication.run_inputs import ReadOnlyStore, RunRejected
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, REJECTED, ZERO, build_ledger

ROOT = Path(__file__).resolve().parents[1]

PRED = "rep-seed"
STATE = b'{"type":"FeatureCollection","features":[]}\n' * 3
STATE_KEY = f"runs/{PRED}/persistence_state.geojson"


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


def predecessor_layout(*, state=STATE, deposit_state=True, declared=None, schema=1):
    """A predecessor prefix: its ledger covers 2026-04-07 .. 2026-04-10."""

    ledger, _ = build_ledger({"2026-04-07": [ALERTS], "2026-04-10": [ZERO, REJECTED]})
    run = {
        "schema": f"araripe.green.run/{schema}",
        "run_id": PRED,
        "ledger": "ledger.json",
        "persistence_state": declared
        or {"sha256": sha256_bytes(state), "bytes": len(state)},
        "objects": [],
    }
    if schema == 2:
        run["predecessor"] = None
    objects = {
        f"runs/{PRED}/run.json": (json.dumps(run).encode(), "application/json"),
        f"runs/{PRED}/ledger.json": (json.dumps(ledger).encode(), "application/json"),
    }
    if deposit_state:
        objects[STATE_KEY] = (state, "application/geo+json")
    return objects


def reader(objects):
    fake = FakeS3(objects)
    return ReadOnlyStore(fake, cs.STAGING_BUCKET), fake


def writer(objects):
    fake = FakeS3(objects)
    return cs.ConditionalStore(fake, cs.STAGING_BUCKET), fake


# ── §1 the key ───────────────────────────────────────────────────────────────


def test_the_state_key_is_the_producers_own_name():
    assemble = load_script("assemble_green_run")
    assert sc.STATE_PATH == assemble.PERSISTENCE_STATE_NAME
    assert sc.state_key("x") == "runs/x/persistence_state.geojson"


def test_the_single_put_ceiling_is_the_documented_one():
    """R2: 5 GiB single-part, '5 MiB less than 5 GiB'."""

    assert sc.MAX_SINGLE_PUT_BYTES == 5 * 1024**3 - 5 * 1024**2
    sc.check_single_put(sc.MAX_SINGLE_PUT_BYTES, "s")
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.check_single_put(sc.MAX_SINGLE_PUT_BYTES + 1, "s")
    assert excinfo.value.codes == ("state_exceeds_single_put",)


# ── §2 reading the predecessor ───────────────────────────────────────────────


@pytest.mark.parametrize("schema", [1, 2])
def test_the_predecessor_is_read_from_its_run_json_and_ledger(schema):
    """Version 1 matters: rep-2026-08-30-v3 and ci-36432616599 are both /1."""

    store, fake = reader(predecessor_layout(schema=schema))
    predecessor = sc.read_predecessor(store, PRED)
    assert predecessor.persistence_state_sha256 == sha256_bytes(STATE)
    assert predecessor.persistence_state_bytes == len(STATE)
    assert predecessor.last_observed_on == "2026-04-10"
    assert predecessor.next_start == "2026-04-11"
    assert STATE_KEY not in fake.reads, "reading the predecessor must not download the state"


def test_an_absent_predecessor_is_a_refusal():
    store, _ = reader({})
    with pytest.raises(RunRejected) as excinfo:
        sc.read_predecessor(store, PRED)
    assert excinfo.value.codes == ("run_manifest_absent",)


def test_a_declared_state_that_was_never_deposited_is_refused():
    """The shape of runs/ci-36432616599/: run.json declares, no object holds."""

    store, _ = reader(predecessor_layout(deposit_state=False))
    predecessor = sc.read_predecessor(store, PRED)
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, predecessor)
    assert excinfo.value.codes == ("predecessor_state_absent",)


def test_a_state_with_other_bytes_is_refused_by_digest_and_length():
    store, _ = reader(predecessor_layout(state=STATE + b"x",
                                         declared={"sha256": sha256_bytes(STATE),
                                                   "bytes": len(STATE)}))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, sc.read_predecessor(store, PRED))
    assert sorted(excinfo.value.codes) == [
        "predecessor_state_digest_mismatch", "predecessor_state_length_mismatch"]


def test_a_same_length_substitution_is_refused_by_digest_alone():
    other = bytes(reversed(STATE))
    store, _ = reader(predecessor_layout(state=other,
                                         declared={"sha256": sha256_bytes(STATE),
                                                   "bytes": len(STATE)}))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, sc.read_predecessor(store, PRED))
    assert excinfo.value.codes == ("predecessor_state_digest_mismatch",)


def test_the_declared_state_is_returned():
    store, _ = reader(predecessor_layout())
    assert sc.fetch_state(store, sc.read_predecessor(store, PRED)) == STATE


# ── §4 the window ────────────────────────────────────────────────────────────


def _pred(last="2026-08-30"):
    return sc.Predecessor(PRED, "a" * 64, 1, last)


def test_the_window_starts_the_day_after_the_last_covered_date():
    sc.check_window(_pred(), "2026-08-31")


@pytest.mark.parametrize("start", ["2026-08-30", "2026-08-01", "2025-12-31"])
def test_an_overlapping_window_is_refused(start):
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.check_window(_pred(), start)
    assert excinfo.value.codes == ("window_overlaps_predecessor",)
    assert "2026-08-31" in str(excinfo.value.findings[0])


@pytest.mark.parametrize("start", ["2026-09-01", "2026-09-02", "2027-01-01"])
def test_a_window_leaving_a_gap_is_refused(start):
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.check_window(_pred(), start)
    assert excinfo.value.codes == ("window_leaves_a_gap",)


@pytest.mark.parametrize("start", ["", "2026-8-31", "tomorrow", None])
def test_a_malformed_start_is_refused(start):
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.check_window(_pred(), start)
    assert excinfo.value.codes == ("window_start_invalid",)


def test_month_and_year_boundaries():
    sc.check_window(_pred("2026-12-31"), "2027-01-01")
    sc.check_window(_pred("2028-02-28"), "2028-02-29")


# ── the lane's fetch step ────────────────────────────────────────────────────


def test_the_fetch_refuses_a_wrong_window_before_reading_the_state(tmp_path):
    fetch = load_script("fetch_green_state")
    store, fake = reader(predecessor_layout())
    with pytest.raises(sc.ChainRejected):
        fetch.fetch(store, PRED, "2026-04-10", tmp_path / "out")
    assert STATE_KEY not in fake.reads
    assert not (tmp_path / "out").exists()


def test_the_fetch_writes_nothing_locally_when_the_state_is_wrong(tmp_path):
    fetch = load_script("fetch_green_state")
    store, _ = reader(predecessor_layout(state=STATE + b"x",
                                         declared={"sha256": sha256_bytes(STATE),
                                                   "bytes": len(STATE)}))
    with pytest.raises(sc.ChainRejected):
        fetch.fetch(store, PRED, "2026-04-11", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_fetch_writes_the_state_and_the_link_and_nothing_remote(tmp_path):
    fetch = load_script("fetch_green_state")
    store, fake = reader(predecessor_layout())
    fetch.fetch(store, PRED, "2026-04-11", tmp_path)
    assert (tmp_path / "persistence_state.geojson").read_bytes() == STATE
    link = json.loads((tmp_path / "predecessor.json").read_text())
    assert link == {"run_id": PRED, "persistence_state_sha256": sha256_bytes(STATE)}
    assert sc.check_link(link) == link
    assert fake.writes == []
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "persistence_state.geojson", "predecessor.json"]


def test_the_fetch_cli_refuses_to_overwrite_a_state(tmp_path, monkeypatch):
    fetch = load_script("fetch_green_state")
    (tmp_path / "persistence_state.geojson").write_bytes(b"old")
    called = []
    monkeypatch.setattr(fetch, "build_reader", lambda: called.append(1))
    code = fetch.main(["--from-run", PRED, "--start", "2026-04-11", "--out-dir", str(tmp_path)])
    assert code == 1 and called == []
    assert (tmp_path / "persistence_state.geojson").read_bytes() == b"old"


def test_the_fetch_store_cannot_write():
    store, fake = reader({})
    with pytest.raises(cs.ObjectStoreError):
        store.put_if_absent(STATE_KEY, STATE, "application/geo+json")
    assert fake.writes == []


# ── the one-time seed ────────────────────────────────────────────────────────


def test_the_seed_goes_into_the_prefix_whose_run_json_binds_it():
    objects = predecessor_layout(deposit_state=False)
    store, fake = writer(objects)
    outcome = sc.seed_state(store, PRED, STATE)
    assert outcome.result == "created"
    assert [key for key, _ in fake.writes] == [STATE_KEY]
    assert fake.objects[STATE_KEY][0] == STATE
    # repeating it is a no-op, not a second write
    assert sc.seed_state(store, PRED, STATE).result == "unchanged"


@pytest.mark.parametrize("body", [STATE + b"x", bytes(reversed(STATE)), b""])
def test_a_seed_that_is_not_the_declared_state_writes_nothing(body):
    store, fake = writer(predecessor_layout(deposit_state=False))
    with pytest.raises(sc.ChainRejected):
        sc.seed_state(store, PRED, body)
    assert fake.writes == []


def test_a_seed_for_a_run_that_does_not_exist_writes_nothing():
    store, fake = writer({})
    with pytest.raises(RunRejected):
        sc.seed_state(store, PRED, STATE)
    assert fake.writes == []


def test_a_seed_above_the_single_put_ceiling_writes_nothing(monkeypatch):
    monkeypatch.setattr(sc, "MAX_SINGLE_PUT_BYTES", len(STATE) - 1)
    store, fake = writer(predecessor_layout(deposit_state=False))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.seed_state(store, PRED, STATE)
    assert excinfo.value.codes == ("state_exceeds_single_put",)
    assert fake.writes == []


def test_a_seed_never_overwrites_a_different_state():
    objects = predecessor_layout(deposit_state=False)
    objects[STATE_KEY] = (b"something else", "application/geo+json")
    store, _ = writer(objects)
    with pytest.raises(cs.ImmutableObjectConflict):
        sc.seed_state(store, PRED, STATE)
    assert objects[STATE_KEY][0] == b"something else"


# ── §2 the successor names its predecessor ───────────────────────────────────


@pytest.mark.parametrize(
    "link",
    [
        {"run_id": PRED},
        {"run_id": PRED, "persistence_state_sha256": "A" * 64},
        {"run_id": "../x", "persistence_state_sha256": "a" * 64},
        {"run_id": PRED, "persistence_state_sha256": "a" * 64, "extra": 1},
        [PRED, "a" * 64],
        "rep-seed",
    ],
)
def test_a_malformed_link_is_refused(link):
    with pytest.raises((sc.ChainRejected, RunRejected)):
        sc.check_link(link)


def test_confirm_link_compares_with_the_predecessors_own_declaration():
    store, _ = writer(predecessor_layout())
    sc.confirm_link(store, {"run_id": PRED, "persistence_state_sha256": sha256_bytes(STATE)})
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.confirm_link(store, {"run_id": PRED, "persistence_state_sha256": "b" * 64})
    assert excinfo.value.codes == ("predecessor_link_mismatch",)


def _assembled(**kwargs):
    ledger, _ = build_ledger({"2026-04-11": [ZERO]})
    kwargs.setdefault("persistence_state_sha256", sha256_bytes(STATE))
    kwargs.setdefault("persistence_state_bytes", len(STATE))
    return ra.assemble_run("succ-1", ledger, {"2026-04-11": []}, **kwargs)


def test_an_empty_start_is_declared_as_null_not_omitted():
    run = _assembled()
    assert "predecessor" in run.document and run.document["predecessor"] is None


def test_a_chained_run_declares_its_predecessor():
    link = {"run_id": PRED, "persistence_state_sha256": "c" * 64}
    assert _assembled(predecessor=link).document["predecessor"] == link


def test_the_state_is_deposited_before_run_json_and_outside_objects():
    run = _assembled(persistence_state_body=STATE)
    assert gzip.decompress(run.bodies[sc.STATE_GZIP_PATH]) == STATE
    assert sc.STATE_PATH not in run.bodies, "the state is deposited compressed only"
    assert all(o["path"] not in (sc.STATE_PATH, sc.STATE_GZIP_PATH)
               for o in run.document["objects"]), (
        "objects become the release; the state is never published"
    )
    store, fake = writer({})
    ra.upload(store, run)
    keys = [key for key, _ in fake.writes]
    assert keys[-1] == "runs/succ-1/run.json"
    assert keys.index(f"runs/succ-1/{sc.STATE_GZIP_PATH}") < len(keys) - 1
    assert fake.objects[f"runs/succ-1/{sc.STATE_GZIP_PATH}"][1] == "application/gzip"


@pytest.mark.parametrize("body", [STATE + b"x", bytes(reversed(STATE))])
def test_state_bytes_that_the_digest_does_not_name_are_refused(body):
    """Both: a different length, and the same length with other bytes."""

    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        _assembled(persistence_state_body=body)
    assert "persistence_state_body_mismatch" in excinfo.value.codes


def test_the_apply_confirms_the_link_before_writing_anything(tmp_path, monkeypatch):
    assemble = load_script("assemble_green_run")
    ledger, _ = build_ledger({"2026-04-11": [ZERO]})
    (tmp_path / "ledger.json").write_text(json.dumps(ledger))
    (tmp_path / "alerts").mkdir()
    (tmp_path / "persistence_state.geojson").write_bytes(STATE)
    (tmp_path / "predecessor.json").write_text(
        json.dumps({"run_id": PRED, "persistence_state_sha256": "d" * 64}))
    store, fake = writer(predecessor_layout())
    monkeypatch.setattr(assemble, "build_candidate_store", lambda: store)
    code = assemble.main([
        "apply", "--run", "succ-1", "--ledger", str(tmp_path / "ledger.json"),
        "--alerts-dir", str(tmp_path / "alerts"),
        "--state", str(tmp_path / "persistence_state.geojson"),
        "--predecessor", str(tmp_path / "predecessor.json"),
    ])
    assert code == 1
    assert fake.writes == []


def test_the_apply_deposits_a_chained_run_with_its_state(tmp_path, monkeypatch):
    assemble = load_script("assemble_green_run")
    ledger, _ = build_ledger({"2026-04-11": [ZERO]})
    (tmp_path / "ledger.json").write_text(json.dumps(ledger))
    (tmp_path / "alerts").mkdir()
    (tmp_path / "persistence_state.geojson").write_bytes(b"new state\n")
    (tmp_path / "predecessor.json").write_text(
        json.dumps({"run_id": PRED, "persistence_state_sha256": sha256_bytes(STATE)}))
    store, fake = writer(predecessor_layout())
    monkeypatch.setattr(assemble, "build_candidate_store", lambda: store)
    code = assemble.main([
        "apply", "--run", "succ-1", "--ledger", str(tmp_path / "ledger.json"),
        "--alerts-dir", str(tmp_path / "alerts"),
        "--state", str(tmp_path / "persistence_state.geojson"),
        "--predecessor", str(tmp_path / "predecessor.json"),
    ])
    assert code == 0
    run = json.loads(fake.objects["runs/succ-1/run.json"][0])
    assert run["schema"] == "araripe.green.run/3"
    assert run["predecessor"] == {"run_id": PRED, "persistence_state_sha256": sha256_bytes(STATE)}
    stored = fake.objects[f"runs/succ-1/{sc.STATE_GZIP_PATH}"][0]
    assert gzip.decompress(stored) == b"new state\n"
    assert "runs/succ-1/persistence_state.geojson" not in fake.objects
    assert run["persistence_state"] == {
        "sha256": sha256_bytes(b"new state\n"), "bytes": 10,
        "stored": {"path": sc.STATE_GZIP_PATH, "encoding": "gzip",
                   "sha256": sha256_bytes(stored), "bytes": len(stored)}}
    # and the new run is itself a valid predecessor for the one after it
    successor = sc.read_predecessor(store, "succ-1")
    assert successor.next_start == "2026-04-12"
    assert sc.fetch_state(store, successor) == b"new state\n"
    # nothing in the predecessor's prefix was touched
    assert not [key for key, _ in fake.writes if key.startswith(f"runs/{PRED}/")]


def test_seed_state_cli_verifies_against_the_bucket(tmp_path, monkeypatch):
    assemble = load_script("assemble_green_run")
    (tmp_path / "s.geojson").write_bytes(STATE + b"x")
    store, fake = writer(predecessor_layout(deposit_state=False))
    monkeypatch.setattr(assemble, "build_candidate_store", lambda: store)
    assert assemble.main(["seed-state", "--run", PRED, "--state", str(tmp_path / "s.geojson")]) == 1
    assert fake.writes == []
    (tmp_path / "s.geojson").write_bytes(STATE)
    assert assemble.main(["seed-state", "--run", PRED, "--state", str(tmp_path / "s.geojson")]) == 0
    assert [key for key, _ in fake.writes] == [STATE_KEY]


# ── §3 rebuild or live ───────────────────────────────────────────────────────


def _transitions(mode, tmp_path):
    from config.settings import (
        BASELINE_VERSION,
        DETECTION_ALGORITHM_VERSION,
        MONITORING_EXTENT_ID,
        TARGET_CRS,
    )
    from src.detection.identity import create_acquisition_identity
    from src.detection.persistence import save_persistence_state, update_tracks

    x, y = 400000, 9200000
    frames = {
        "2026-08-25": [(x, y, x + 100, y + 100)],
        "2026-08-30": [(x + 10, y, x + 110, y + 100), (x + 5000, y, x + 5100, y + 100)],
        "2026-09-02": [(x + 20, y, x + 120, y + 100)],
    }
    state = None
    for observed_on, boxes in frames.items():
        acquisition = create_acquisition_identity(
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            observed_on=observed_on,
            scene_ids=[f"COPERNICUS/S2_SR_HARMONIZED/{observed_on.replace('-', '')}_a"],
            monitoring_extent_id=MONITORING_EXTENT_ID,
            composite_method_id="daily_mosaic-v1",
        )
        current = gpd.GeoDataFrame(geometry=[box(*b) for b in boxes], crs=TARGET_CRS)
        _, state = update_tracks(
            current, state, observed_on, acquisition=acquisition,
            algorithm_version=DETECTION_ALGORITHM_VERSION,
            baseline_version=BASELINE_VERSION,
            monitoring_extent_id=MONITORING_EXTENT_ID, mode=mode,
        )
    path = tmp_path / f"{mode}.geojson"
    save_persistence_state(state, path)
    return path.read_bytes()


def test_rebuild_and_live_produce_byte_identical_states(tmp_path):
    """PHASE_6G §3, measured: ``mode`` is validated and never read.

    If this falls, ``mode`` has acquired a meaning, and the choice of
    ``rebuild`` for a chained run must be made again with the new behaviour.
    """

    assert _transitions("rebuild", tmp_path) == _transitions("live", tmp_path)


def test_a_chained_state_refuses_a_date_it_already_passed(tmp_path):
    """The producer's guarantee behind §4: a gap cannot be backfilled later."""

    from config.settings import (
        BASELINE_VERSION,
        DETECTION_ALGORITHM_VERSION,
        MONITORING_EXTENT_ID,
        TARGET_CRS,
    )
    from src.detection.identity import create_acquisition_identity
    from src.detection.persistence import (
        OutOfOrderAcquisitionError,
        load_persistence_state,
        update_tracks,
    )

    _transitions("rebuild", tmp_path)
    state = load_persistence_state(tmp_path / "rebuild.geojson")
    skipped = "2026-09-01"  # before the watermark 2026-09-02, never registered
    acquisition = create_acquisition_identity(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        observed_on=skipped,
        scene_ids=["COPERNICUS/S2_SR_HARMONIZED/20260901_a"],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id="daily_mosaic-v1",
    )
    current = gpd.GeoDataFrame(geometry=[box(400000, 9200000, 400100, 9200100)], crs=TARGET_CRS)
    with pytest.raises(OutOfOrderAcquisitionError):
        update_tracks(
            current, state, skipped, acquisition=acquisition,
            algorithm_version=DETECTION_ALGORITHM_VERSION,
            baseline_version=BASELINE_VERSION,
            monitoring_extent_id=MONITORING_EXTENT_ID, mode="rebuild",
        )


# ── PHASE_6J: the state is stored compressed ─────────────────────────────────


def compressed_layout(*, body=None, stored_override=None, run_id="gz-1"):
    """A version-3 run whose state is deposited as gzip."""

    ledger, _ = build_ledger({"2026-04-07": [ALERTS]})
    body = sc.compress_state(STATE) if body is None else body
    stored = {"path": sc.STATE_GZIP_PATH, "encoding": "gzip",
              "sha256": sha256_bytes(body), "bytes": len(body)}
    stored.update(stored_override or {})
    run = {
        "schema": "araripe.green.run/3", "run_id": run_id, "ledger": "ledger.json",
        "persistence_state": {"sha256": sha256_bytes(STATE), "bytes": len(STATE),
                              "stored": stored},
        "predecessor": None, "objects": [],
    }
    return {
        f"runs/{run_id}/run.json": (json.dumps(run).encode(), "application/json"),
        f"runs/{run_id}/ledger.json": (json.dumps(ledger).encode(), "application/json"),
        f"runs/{run_id}/{sc.STATE_GZIP_PATH}": (body, "application/gzip"),
    }


def test_a_compressed_state_is_read_back_as_the_uncompressed_bytes():
    store, fake = reader(compressed_layout())
    predecessor = sc.read_predecessor(store, "gz-1")
    assert predecessor.stored["path"] == sc.STATE_GZIP_PATH
    assert sc.fetch_state(store, predecessor) == STATE
    assert "runs/gz-1/persistence_state.geojson" not in fake.reads, (
        "a version-3 run is read from its stored object, never the legacy name")


def test_compression_is_deterministic_and_carries_no_clock():
    assert sc.compress_state(STATE) == sc.compress_state(STATE)
    assert sc.compress_state(STATE)[4:8] == b"\x00\x00\x00\x00", "gzip MTIME is zero"


def test_the_legacy_uncompressed_state_is_still_read():
    """rep-2026-08-30-v3 and the three chained runs are /1 and /2, uncompressed."""

    store, _ = reader(predecessor_layout(schema=2))
    assert sc.fetch_state(store, sc.read_predecessor(store, PRED)) == STATE


def test_a_stored_object_that_is_not_the_one_written_is_refused_before_inflating():
    written = sc.compress_state(STATE)
    declared = {"sha256": sha256_bytes(written), "bytes": len(written)}
    store, _ = reader(compressed_layout(body=written + b"xx", stored_override=declared))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, sc.read_predecessor(store, "gz-1"))
    assert set(excinfo.value.codes) == {
        "predecessor_stored_state_digest_mismatch", "predecessor_stored_state_length_mismatch"}
    # same length, other bytes: the digest alone
    swapped = bytearray(written); swapped[-9] ^= 1
    store, _ = reader(compressed_layout(body=bytes(swapped), stored_override=declared))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, sc.read_predecessor(store, "gz-1"))
    assert excinfo.value.codes == ("predecessor_stored_state_digest_mismatch",)


def test_a_stored_object_whose_contents_are_another_state_is_refused():
    """The object is exactly what run.json says — and holds other bytes."""

    other = sc.compress_state(bytes(reversed(STATE)))
    store, _ = reader(compressed_layout(body=other))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, sc.read_predecessor(store, "gz-1"))
    assert excinfo.value.codes == ("predecessor_state_digest_mismatch",)


@pytest.mark.parametrize(
    "body",
    [
        b"not gzip at all",
        sc.compress_state(STATE) + b"trailing",
        sc.compress_state(STATE + b"x" * 1000),  # inflates past the declared length
        sc.compress_state(STATE)[:-6],  # truncated stream
    ],
    ids=["garbage", "trailing-bytes", "overlong", "truncated"],
)
def test_a_stored_object_that_does_not_inflate_to_exactly_the_state_is_refused(body):
    store, _ = reader(compressed_layout(body=body))
    with pytest.raises(sc.ChainRejected) as excinfo:
        sc.fetch_state(store, sc.read_predecessor(store, "gz-1"))
    assert excinfo.value.codes == ("predecessor_state_undecodable",)


def test_inflation_is_bounded_by_the_declared_length(monkeypatch):
    """A decompression bomb must not allocate more than run.json promised.

    Measured on the inflater itself: it is asked for at most one byte more
    than declared, so a 50 MiB bomb yields 11 bytes before the refusal.
    """

    import zlib

    produced = []
    real = zlib.decompressobj

    class Spy:
        def __init__(self, *args):
            self.inner = real(*args)

        def decompress(self, data, max_length=0):
            out = self.inner.decompress(data, max_length)
            produced.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(sc.zlib, "decompressobj", Spy)
    bomb = gzip.compress(b"\0" * (50 * 1024 * 1024), compresslevel=9, mtime=0)
    with pytest.raises(sc.ChainRejected):
        sc._decompress(bomb, 10, "k")
    assert produced == [11]


def test_the_single_put_ceiling_applies_to_the_compressed_object(monkeypatch):
    """What is PUT is the gzip; a state bigger than one PUT that compresses
    under it deposits, and one that does not is refused."""

    body = b'{"type":"FeatureCollection","features":[]}\n' * 40
    compressed = sc.compress_state(body)
    assert len(compressed) < len(body)
    monkeypatch.setattr(sc, "MAX_SINGLE_PUT_BYTES", len(compressed))
    run = _assembled(persistence_state_body=body,
                     persistence_state_sha256=sha256_bytes(body),
                     persistence_state_bytes=len(body))
    assert run.bodies[sc.STATE_GZIP_PATH] == compressed
    monkeypatch.setattr(sc, "MAX_SINGLE_PUT_BYTES", len(compressed) - 1)
    with pytest.raises(sc.ChainRejected) as excinfo:
        _assembled(persistence_state_body=body,
                   persistence_state_sha256=sha256_bytes(body),
                   persistence_state_bytes=len(body))
    assert excinfo.value.codes == ("state_exceeds_single_put",)


def test_the_version_three_schema_pins_the_stored_name_and_encoding():
    from src.publication.green_release import schema_validator

    ok = json.loads(compressed_layout()["runs/gz-1/run.json"][0])
    validator = schema_validator("green-run-v3")
    assert list(validator.iter_errors(ok)) == []
    for field, value in (("path", "../x.gz"), ("encoding", "zstd")):
        bad = json.loads(json.dumps(ok))
        bad["persistence_state"]["stored"][field] = value
        assert list(validator.iter_errors(bad)), field


def test_retention_keeps_the_compressed_state_like_the_uncompressed_one():
    from datetime import datetime, timezone

    from src.publication import retention as rt

    item = rt.StoredKey(key=f"runs/gz-1/{sc.STATE_GZIP_PATH}", size=1,
                        last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc))
    decision = rt.classify(item, pointer=None, runs={},
                           as_of=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert (decision.action, decision.reason) == (rt.RETAIN, "persistence_state_is_the_chain")
