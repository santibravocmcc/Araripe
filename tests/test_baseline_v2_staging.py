"""Baseline 2.1.0 reaches the green bucket intact, and comes back intact.

The store is ``tests.fake_object_store.FakeS3``: no network, and it enforces
``If-None-Match`` the way R2 does, so write-once behaviour is exercised rather
than assumed. The manifest is a small synthetic one written per test, except
where the real one is read on purpose.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from src.publication.conditional_store import ConditionalStore, ObjectStoreError
from tests.fake_object_store import FakeS3

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "baseline_v2_staging.py"
SPEC = importlib.util.spec_from_file_location("baseline_v2_staging", SCRIPT)
assert SPEC and SPEC.loader
bv = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bv
SPEC.loader.exec_module(bv)


def raster(month: int, name: str) -> bytes:
    return f"tiff-{month:02d}-{name}".encode() * 50


def objects_for(months=(1, 8)) -> tuple[list[dict], dict[str, bytes]]:
    objects, bodies = [], {}
    for month in months:
        for name in ("ndmi_mean", "ndmi_std"):
            filename = f"{name.split('_')[0]}_month{month:02d}_{name.split('_')[1]}.tif"
            body = raster(month, name)
            bodies[filename] = body
            objects.append({
                "key": bv.KEY_PREFIX + filename,
                "filename": filename,
                "month": month,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            })
    return objects, bodies


def store(objects=None) -> tuple[ConditionalStore, FakeS3]:
    """``objects`` maps key -> body; FakeS3 stores (body, content type)."""

    fake = FakeS3({k: (v, bv.CONTENT_TYPE) for k, v in (objects or {}).items()})
    return ConditionalStore(fake, cs.STAGING_BUCKET), fake


def source_dir(tmp_path, bodies) -> Path:
    src = tmp_path / "source"
    src.mkdir()
    for filename, body in bodies.items():
        (src / filename).write_bytes(body)
    return src


# ─── the real manifest ───────────────────────────────────────────────────────


def test_the_real_manifest_declares_72_objects_under_the_prefix():
    objects = bv.load_objects()
    assert len(objects) == 72
    assert {o["month"] for o in objects} == set(range(1, 13))
    assert all(o["key"].startswith("baselines_v2/2.1.0/") for o in objects)
    # three indices (ndmi, nbr, evi2) x mean/std — PHASE_6E said 8, and was wrong
    assert sum(1 for o in objects if o["month"] == 8) == 6


@pytest.mark.parametrize("mutate,message", [
    (lambda m: m.update(baseline_version="2.0.0"), "not 2.1.0"),
    (lambda m: m["objects"].pop(), "not 72"),
    (lambda m: m["objects"][0].update(key="baselines/other.tif"), "is not"),
    (lambda m: m["objects"][0].update(sha256="nothex"), "no SHA-256"),
    (lambda m: m["objects"][1].update(key=m["objects"][0]["key"],
                                      filename=m["objects"][0]["filename"]), "listed twice"),
])
def test_a_manifest_that_is_not_this_generation_is_refused(tmp_path, mutate, message):
    manifest = json.loads(bv.MANIFEST.read_text())
    mutate(manifest)
    path = tmp_path / "m.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(bv.ManifestError, match=message):
        bv.load_objects(path)


# ─── upload ──────────────────────────────────────────────────────────────────


def test_upload_writes_every_object_once_and_a_rerun_is_unchanged(tmp_path):
    objects, bodies = objects_for()
    src = source_dir(tmp_path, bodies)
    s, fake = store()
    assert bv.upload(s, src, objects) == {"created": 4}
    assert sorted(fake.keys()) == sorted(o["key"] for o in objects)
    assert bv.upload(s, src, objects) == {"unchanged": 4}


def test_one_bad_local_file_stops_the_upload_before_any_write(tmp_path):
    """Kills: verifying each file just before writing it.

    A baseline half-uploaded from a wrong local copy would be immutable and
    undeletable, so the LAST file being wrong must leave the bucket empty.
    """

    objects, bodies = objects_for()
    src = source_dir(tmp_path, bodies)
    (src / objects[-1]["filename"]).write_bytes(b"corrupted" * 10)
    s, fake = store()
    with pytest.raises(ObjectStoreError):
        bv.upload(s, src, objects)
    assert fake.keys() == []


def test_a_missing_local_file_stops_the_upload_before_any_write(tmp_path):
    objects, bodies = objects_for()
    src = source_dir(tmp_path, bodies)
    (src / objects[-1]["filename"]).unlink()
    s, fake = store()
    with pytest.raises(ObjectStoreError, match="missing"):
        bv.upload(s, src, objects)
    assert fake.keys() == []


def test_different_bytes_already_under_a_key_are_a_refusal_not_an_overwrite(tmp_path):
    objects, bodies = objects_for()
    src = source_dir(tmp_path, bodies)
    first = objects[0]
    s, fake = store({first["key"]: b"someone else's raster"})
    with pytest.raises(cs.ImmutableObjectConflict):
        bv.upload(s, src, objects)
    assert fake.body(first["key"]) == b"someone else's raster"


# ─── fetch ───────────────────────────────────────────────────────────────────


def test_fetch_takes_only_the_months_asked_and_verifies_them(tmp_path):
    objects, bodies = objects_for()
    s, _ = store({o["key"]: bodies[o["filename"]] for o in objects})
    out = tmp_path / "out"
    written = bv.fetch(s, out, [8], objects)
    assert sorted(p.name for p in written) == sorted(
        o["filename"] for o in objects if o["month"] == 8
    )
    assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in written)
    for path in written:
        assert path.read_bytes() == bodies[path.name]


def test_a_tampered_object_is_refused_and_leaves_no_file(tmp_path):
    """Kills: skipping the digest check, or writing before checking."""

    objects, bodies = objects_for()
    stored = {o["key"]: bodies[o["filename"]] for o in objects}
    target = next(o for o in objects if o["month"] == 8)
    stored[target["key"]] = b"x" * target["bytes"]  # right length, wrong bytes
    s, _ = store(stored)
    out = tmp_path / "out"
    with pytest.raises(ObjectStoreError, match="SHA-256"):
        bv.fetch(s, out, [8], objects)
    assert not (out / target["filename"]).exists()
    assert not list(out.glob("*.partial"))


def test_a_short_object_is_refused(tmp_path):
    objects, bodies = objects_for()
    stored = {o["key"]: bodies[o["filename"]] for o in objects}
    target = next(o for o in objects if o["month"] == 8)
    stored[target["key"]] = bodies[target["filename"]][:-1]
    s, _ = store(stored)
    with pytest.raises(ObjectStoreError, match="bytes"):
        bv.fetch(s, tmp_path / "out", [8], objects)


def test_an_absent_object_is_a_refusal(tmp_path):
    objects, _ = objects_for()
    s, _ = store({})
    with pytest.raises(ObjectStoreError, match="absent"):
        bv.fetch(s, tmp_path / "out", [8], objects)


def test_a_verified_local_copy_is_not_downloaded_again(tmp_path):
    objects, bodies = objects_for()
    out = tmp_path / "out"
    out.mkdir()
    for o in objects:
        if o["month"] == 8:
            (out / o["filename"]).write_bytes(bodies[o["filename"]])
    s, _ = store({})  # an empty store: any download would be a refusal
    assert len(bv.fetch(s, out, [8], objects)) == 2


def test_a_month_with_no_objects_is_a_refusal(tmp_path):
    objects, bodies = objects_for(months=(1,))
    s, _ = store({o["key"]: bodies[o["filename"]] for o in objects})
    with pytest.raises(ObjectStoreError, match="no manifest object"):
        bv.fetch(s, tmp_path / "out", [8], objects)


def test_nothing_outside_the_prefix_is_addressed(tmp_path):
    objects, bodies = objects_for()
    src = source_dir(tmp_path, bodies)
    s, fake = store()
    bv.upload(s, src, objects)
    bv.fetch(s, tmp_path / "out", [1, 8], objects)
    assert all(key.startswith("baselines_v2/2.1.0/") for key in fake.keys())


def test_a_local_copy_of_the_right_size_but_wrong_bytes_is_replaced(tmp_path):
    """Kills: trusting a local file by its size (mutation M8 survived without this).

    A runner cache or an earlier interrupted run can leave a file of the right
    length; only its digest says whether it is the baseline.
    """

    objects, bodies = objects_for()
    out = tmp_path / "out"
    out.mkdir()
    target = next(o for o in objects if o["month"] == 8)
    (out / target["filename"]).write_bytes(b"z" * target["bytes"])
    s, _ = store({o["key"]: bodies[o["filename"]] for o in objects})
    bv.fetch(s, out, [8], objects)
    assert (out / target["filename"]).read_bytes() == bodies[target["filename"]]
