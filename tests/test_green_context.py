"""The land-cover context of a green release (GREEN_CONTEXT_CONTRACT_V1.md)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.publication import green_context as gc
from src.publication import site_artifact as sa

ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "rel-g3-" + "ab" * 32
TABLES = {"mapbiomas10m": {3: "natural", 15: "farming"}, "mapbiomas30m": {3: "natural", 15: "farming"}}


def _raster(key: str, sha: str) -> dict:
    return {"collection_key": key, "collection": "Coleção X", "year": 2025,
            "origin_url": f"https://example.org/{key}.tif", "crop_sha256": sha, "source_md5": "0" * 32}


def _spec(sha10: str = "1" * 64) -> dict:
    return gc.build_spec([_raster("mapbiomas10m", sha10), _raster("mapbiomas30m", "2" * 64)], TABLES)


def _feature(oid: str, *, label: str = "high", count: int = 3, frac: float = 0.9, geometry: str = "Polygon") -> dict:
    coords = [[[-39.5, -7.3], [-39.49, -7.3], [-39.49, -7.29], [-39.5, -7.3]]]
    geom = {"type": "Polygon", "coordinates": coords} if geometry == "Polygon" else {"type": "Point", "coordinates": [-39.5, -7.3]}
    return {"type": "Feature", "geometry": geom, "properties": {
        "observation_id": oid, "confidence_label": label, "persistence_count": count,
        "lc_natural_frac_10m": frac, "lc_natural_frac": frac, "lc_group_10m": "natural"}}


# ── identity ─────────────────────────────────────────────────────────────────

def test_the_identity_is_a_function_of_the_release_and_the_recipe():
    a, _ = gc.context_identity(RELEASE_ID, _spec())
    assert a == gc.context_identity(RELEASE_ID, _spec())[0]
    assert gc.CONTEXT_ID.match(a)
    # a new crop is a new context for the same release …
    assert gc.context_identity(RELEASE_ID, _spec(sha10="3" * 64))[0] != a
    # … and the same recipe on another release is another context
    assert gc.context_identity("rel-g3-" + "cd" * 32, _spec())[0] != a


def test_the_spec_carries_no_float_so_it_can_be_canonically_hashed():
    def walk(value):
        assert not isinstance(value, float), value
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(_spec())


def test_the_spec_needs_both_collections():
    with pytest.raises(gc.ContextRejected):
        gc.build_spec([_raster("mapbiomas10m", "1" * 64)], {"mapbiomas10m": {}})


# ── labels and relabelling ───────────────────────────────────────────────────

def test_labels_are_rounded_typed_and_null_when_there_was_no_pixel():
    doc = gc.labels_document("2026-09-24", [
        ("obs-b", {"lc_class_10m": 4.0, "lc_group_10m": "natural", "lc_natural_frac_10m": 0.93456,
                   "lc_class_30m": 15, "lc_group_30m": "farming", "lc_natural_frac_30m": float("nan")}),
        ("obs-a", {}),
    ])
    assert list(doc["labels"]) == ["obs-a", "obs-b"]
    assert doc["labels"]["obs-b"] == [4, "natural", 0.935, 15, "farming", None]
    assert doc["labels"]["obs-a"] == [None] * 6
    assert doc["fields"] == list(gc.LABEL_FIELDS)


def test_relabel_replaces_only_land_cover_and_derives_the_unsuffixed_columns():
    feature = _feature("obs-1", frac=0.9)
    row = [3, "natural", 0.2, 15, "farming", 0.0]
    (out,) = gc.relabel([feature], {"obs-1": row}, "d")
    p = out["properties"]
    assert p["lc_natural_frac_10m"] == 0.2 and p["lc_natural_frac"] == 0.2
    assert p["lc_group"] == "natural" and p["lc_class"] == 3
    assert p["confidence_label"] == "high" and p["persistence_count"] == 3
    assert feature["properties"]["lc_natural_frac_10m"] == 0.9   # input untouched


@pytest.mark.parametrize("labels, code", [
    ({}, "feature_without_label"),
    ({"obs-1": [None] * 6, "obs-ghost": [None] * 6}, "label_without_feature"),
])
def test_labels_and_features_must_cover_each_other_exactly(labels, code):
    with pytest.raises(gc.ContextRejected) as caught:
        gc.relabel([_feature("obs-1")], labels, "d")
    assert caught.value.codes[0] == code


def test_the_strong_subset_is_the_index_rule_under_the_new_labels():
    features = [
        _feature("keeps"),
        _feature("loses-natural"),
        _feature("low", label="medium"),
        _feature("single", count=1),
        _feature("point", geometry="Point"),
    ]
    labels = {f["properties"]["observation_id"]: [3, "natural", 0.9, 3, "natural", 0.9] for f in features}
    labels["loses-natural"] = [15, "farming", 0.1, 15, "farming", 0.1]
    relabelled = gc.relabel(features, labels, "d")
    strong = gc.strong_collection(relabelled)["features"]
    assert [f["properties"]["observation_id"] for f in strong] == ["keeps"]
    assert strong == list(sa.strong_features(relabelled))


# ── the context document against its release ─────────────────────────────────

def _release() -> dict:
    return {
        "release_id": RELEASE_ID,
        "objects": [
            {"path": "alerts/run-2026-09-24.geojson", "sha256": "f" * 64},
            {"path": "alerts/run-2026-09-24.strong.geojson", "sha256": "e" * 64},
        ],
        "dates": [
            {"observed_on": "2026-09-24", "alert_state": "alerts",
             "paths": ["alerts/run-2026-09-24.geojson", "alerts/run-2026-09-24.strong.geojson"]},
            {"observed_on": "2026-09-27", "alert_state": "no_valid_coverage", "paths": []},
        ],
    }


def _document(**overrides) -> dict:
    objects = [gc.object_entry(p, b"x", "application/json", "2026-09-24")
               for p in ("alerts/run-2026-09-24.lc.json", "alerts/run-2026-09-24.strong.geojson")]
    dates = [{"observed_on": "2026-09-24", "source_path": "alerts/run-2026-09-24.geojson",
              "source_sha256": "f" * 64, "feature_count": 10, "strong_count": 2}]
    doc = gc.context_document(release=_release(), spec=_spec(), dates=dates, objects=objects)
    doc.update(overrides)
    return doc


def test_a_well_formed_context_passes():
    gc.check_context(_document(), _release())


@pytest.mark.parametrize("patch, code", [
    ({"release_id": "rel-g3-" + "00" * 32}, "release_mismatch"),
    ({"context_id": "ctx-g1-" + "00" * 32}, "identity_mismatch"),
    ({"dates": []}, "dates_mismatch"),
    ({"objects": []}, "object_missing"),
])
def test_a_context_that_does_not_fit_its_release_is_refused(patch, code):
    with pytest.raises(gc.ContextRejected) as caught:
        gc.check_context(_document(**patch), _release())
    assert code in caught.value.codes


def test_a_context_computed_from_another_full_object_is_refused():
    doc = _document()
    doc["dates"][0]["source_sha256"] = "0" * 64
    with pytest.raises(gc.ContextRejected) as caught:
        gc.check_context(doc, _release())
    assert "source_mismatch" in caught.value.codes


def test_an_object_outside_the_dated_runs_is_refused():
    doc = _document()
    doc["objects"].append(gc.object_entry("alerts/run-2026-09-27.lc.json", b"x", "application/json", "2026-09-27"))
    with pytest.raises(gc.ContextRejected) as caught:
        gc.check_context(doc, _release())
    assert "object_unexpected" in caught.value.codes


# ── the script, end to end on the committed 2025 crops ───────────────────────

def _load_script():
    spec = importlib.util.spec_from_file_location("publish_green_context", ROOT / "scripts/publish_green_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_writes_a_context_that_checks_against_its_release(tmp_path):
    script = _load_script()
    features = [_feature(f"obs-{i}", frac=0.0) for i in range(3)]
    features[0]["geometry"]["coordinates"] = [[[-39.40, -7.40], [-39.39, -7.40], [-39.39, -7.39], [-39.40, -7.40]]]
    body = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    release = _release()
    release["objects"][0]["sha256"] = hashlib.sha256(body).hexdigest()
    source = tmp_path / "in"
    (source / "objects/alerts").mkdir(parents=True)
    (source / "objects/alerts/run-2026-09-24.geojson").write_bytes(body)
    (source / "release.json").write_text(json.dumps(release))

    assert script.main(["plan", "--input", str(source), "--out", str(tmp_path / "out")]) == 0
    (document_path,) = (tmp_path / "out").glob("contexts/*/context.json")
    document = json.loads(document_path.read_bytes())
    gc.check_context(document, release)
    labels = json.loads((document_path.parent / "alerts/run-2026-09-24.lc.json").read_bytes())
    assert sorted(labels["labels"]) == ["obs-0", "obs-1", "obs-2"]
    # every label came from the 2025 crops, so the 10 m class is a 2025 legend code
    assert all(isinstance(row[0], int) for row in labels["labels"].values())
    # and the recipe in the document names those crops by checksum
    shas = {r["collection_key"]: r["crop_sha256"] for r in document["spec"]["rasters"]}
    for key, stem in script.CROPS.items():
        report = json.loads((ROOT / f"data/landcover/{stem}.report.json").read_text())
        assert shas[key] == report["crop"]["sha256"]
    # a second plan of the same input is byte-identical (same id, same bytes)
    assert script.main(["plan", "--input", str(source), "--out", str(tmp_path / "again")]) == 0
    (again,) = (tmp_path / "again").glob("contexts/*/context.json")
    assert again.read_bytes() == document_path.read_bytes()


def test_plan_refuses_an_object_that_does_not_match_the_release(tmp_path):
    script = _load_script()
    source = tmp_path / "in"
    (source / "objects/alerts").mkdir(parents=True)
    (source / "objects/alerts/run-2026-09-24.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (source / "release.json").write_text(json.dumps(_release()))
    with pytest.raises(SystemExit):
        script.main(["plan", "--input", str(source), "--out", str(tmp_path / "out")])


# ── the context pointer's single writer ──────────────────────────────────────

class _Store:
    """The three ConditionalStore methods ``context_pointer.move`` uses."""

    def __init__(self, current: bytes | None = None):
        from src.publication.conditional_store import StoredObject
        self.calls = []
        self._current = None if current is None else StoredObject(gc.CONTEXT_CURRENT_KEY, current, '"e1"')

    def get(self, key):
        assert key == gc.CONTEXT_CURRENT_KEY
        return self._current

    def put_if_pointer_absent(self, key, body, content_type):
        self.calls.append(("absent", key, json.loads(body)))

    def put_if_match(self, key, body, content_type, etag):
        self.calls.append(("match", key, json.loads(body), etag))


def test_the_context_pointer_is_created_then_swapped_and_never_rewritten_in_place():
    from src.publication import context_pointer

    document = _document()
    body = gc.serialise(document)
    store = _Store()
    assert context_pointer.move(store, document, body, {"workflow": "t"}) == "moved"
    (kind, key, written), = store.calls
    assert (kind, key) == ("absent", "contexts/current.json")
    assert written["sequence"] == 1 and written["context_id"] == document["context_id"]
    assert written["context_document_sha256"] == hashlib.sha256(body).hexdigest()

    # the same context again: nothing is written
    same = _Store(gc.serialise(written))
    assert context_pointer.move(same, document, body, {}) == "unchanged"
    assert same.calls == []

    # another context: a compare-and-swap against the version read
    other = _Store(gc.serialise({**written, "context_id": "ctx-g1-" + "0" * 64}))
    assert context_pointer.move(other, document, body, {}) == "moved"
    (kind, key, swapped, etag), = other.calls
    assert (kind, etag, swapped["sequence"]) == ("match", '"e1"', 2)


def test_the_context_pointer_is_not_the_release_pointer():
    from src.publication import delivery_boundary as db

    assert gc.CONTEXT_CURRENT_KEY == db.CONTEXT_CURRENT_KEY == "contexts/current.json"
    assert not gc.CONTEXT_CURRENT_KEY.startswith("pointers/")


# ── the lane ─────────────────────────────────────────────────────────────────

def test_the_lane_is_serialized_and_runs_only_from_main():
    import yaml

    lane = yaml.safe_load((ROOT / ".github/workflows/v2_green_context.yml").read_text())
    assert lane["concurrency"] == {"group": "araripe-green-context", "cancel-in-progress": False}
    job = lane["jobs"]["context"]
    assert job["environment"] == "v2-promotion"
    assert "github.ref == 'refs/heads/main'" in job["if"]
    names = [step["name"] for step in job["steps"]]
    # the bucket check comes before any step that holds the key
    first_secret = next(i for i, s in enumerate(job["steps"]) if "secrets." in json.dumps(s))
    assert names.index("Fail closed unless the target is exactly the approved staging bucket") < first_secret
    # only `publish` writes
    publish = next(s for s in job["steps"] if "apply" in s.get("run", ""))
    assert publish["if"] == "inputs.mode == 'publish'"


def test_the_lane_is_dispatched_only_and_reads_its_own_mode():
    """PHASE_6W §8: the lane is no longer called by v2_operational_publish.yml
    (its Environment secrets arrived empty in the call); that lane runs the
    same steps in a job of its own. This one stays for a manual re-publish."""

    import yaml

    lane = yaml.safe_load((ROOT / ".github/workflows/v2_green_context.yml").read_text())
    on = lane[True]
    assert set(on) == {"workflow_dispatch"}
    assert on["workflow_dispatch"]["inputs"]["mode"]["default"] == "plan"
    mode = next(s for s in lane["jobs"]["context"]["steps"] if s["name"] == "Refuse an unknown mode")
    assert mode["env"]["MODE"] == "${{ inputs.mode }}"
