"""Reading one green run's inputs from its immutable prefix (Package 2B.2C).

The Package 2B.2 bullet this closes is *keep operational data publication
automatic without PRs or manual merges*.  Package 2B.2B built publish → verify
→ promote and left one question open: where the ledger and the artifacts come
from when nobody is typing a command line.  They come from ``runs/<run_id>/``
in the staging bucket, and this file pins what that document may and may not
do.

Two properties carry most of the weight:

* the run document is **not** a second ledger — the release identity, the
  watermark and every checksum still come from the processing ledger, so two
  different runs offering the same ledger and bytes produce the *same*
  release;
* intent is declared and a declaration the bytes contradict is refused, rather
  than quietly relabelled — the defect a first draft of the 2B.2B CLI had
  (``docs/implementation/PHASE_2B2B_2026-09-07.md`` §7).

Everything here runs against ``tests/fake_object_store.py``: no network, no
clock, no credential, no object store.
"""

from __future__ import annotations

import json

import pytest

from src.publication import conditional_store as cs
from src.publication import run_inputs as ri
from src.publication.green_release import (
    ReleaseRejected,
    release_identity,
    sha256_bytes,
)
from src.publication.ledger_gate import check_processing_ledger, LedgerRejected
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, REJECTED, ZERO, build_ledger

RUN_ID = "run-31720230963-1"
STATE_SHA = "a" * 64
STATE_BYTES = 126469137
SPEC = {"2026-04-07": [ALERTS, REJECTED], "2026-04-10": [ZERO]}


def short(acquisition_id: str) -> str:
    """The readable slice of an acquisition id, as the 2B.2B tests use."""

    return acquisition_id[7:19]


def run_layout(document, bodies, *, run_id=RUN_ID, state_sha256=STATE_SHA):
    """A complete, publishable run prefix: the document and the stored objects."""

    objects = []
    stored = {}
    for row in document["terminal_rows"]:
        body = bodies.get(row["acquisition_id"])
        if body is None:
            continue
        name = f"{short(row['acquisition_id'])}.geojson"
        source = f"objects/{name}"
        objects.append(
            {
                "path": f"alerts/{row['observed_on']}/{name}",
                "source": source,
                "kind": "acquisition_artifact",
                "observed_on": row["observed_on"],
                "content_type": "application/geo+json",
                "acquisition_id": row["acquisition_id"],
            }
        )
        stored[f"runs/{run_id}/{source}"] = (body, "application/geo+json")

    run_document = {
        "schema": ri.RUN_SCHEMA,
        "run_id": run_id,
        "ledger": "ledger.json",
        "persistence_state": {"sha256": state_sha256, "bytes": STATE_BYTES},
        "objects": objects,
    }
    # Deliberately pretty-printed, not canonical: the contract inherits
    # "a ledger file need not be canonical on arrival" and the run document
    # makes no byte claim about itself either.
    stored[f"runs/{run_id}/run.json"] = (
        json.dumps(run_document, indent=2).encode("utf-8"),
        "application/json",
    )
    stored[f"runs/{run_id}/ledger.json"] = (
        json.dumps(document, indent=2).encode("utf-8"),
        "application/json",
    )
    return run_document, stored


def store_of(stored, **kwargs):
    fake = FakeS3(stored, **kwargs)
    return cs.ConditionalStore(fake, cs.STAGING_BUCKET), fake


@pytest.fixture
def run():
    document, bodies = build_ledger(SPEC)
    run_document, stored = run_layout(document, bodies)
    return document, bodies, run_document, stored


# ── the happy path, and what it proves about identity ────────────────────────

def test_a_complete_run_prefix_produces_a_validated_release(run):
    document, _, _, stored = run
    store, _ = store_of(stored)
    staged = ri.load_run(store, RUN_ID)

    assert staged.release_id.startswith("rel-g1-")
    assert staged.release["schema"] == "araripe.green.release/1"
    assert [entry["observed_on"] for entry in staged.release["dates"]] == [
        "2026-04-07",
        "2026-04-10",
    ]
    assert len(staged.bodies) == 2  # one alerting artifact, one quiet-day one


def test_the_release_identity_comes_from_the_ledger_not_from_the_run(run):
    """The run document is not a second ledger, and this is how that is felt.

    Two different runs offering the same ledger and the same bytes publish the
    *same* release, to the same immutable prefix, so republishing is a
    byte-exact no-op rather than a conflict.
    """

    document, bodies, _, stored = run
    other_document, other_stored = run_layout(document, bodies, run_id="run-999-2")

    first, _ = store_of(stored)
    second, _ = store_of(other_stored)
    a = ri.load_run(first, RUN_ID)
    b = ri.load_run(second, "run-999-2")

    assert a.run_id != b.run_id
    assert a.release_id == b.release_id
    assert a.release == b.release
    expected, _ = release_identity(check_processing_ledger(document))
    assert a.release_id == expected


def test_the_watermark_is_derived_from_the_ledger_not_supplied_by_the_run(run):
    """`finalized_through` has no field in the run document at all."""

    document, _, run_document, stored = run
    assert "state_watermark" not in run_document
    assert "finalized_through" not in json.dumps(run_document)

    store, _ = store_of(stored)
    staged = ri.load_run(store, RUN_ID)
    assert staged.release["state_watermark"]["finalized_through"] == "2026-04-10"


def test_the_run_makes_no_claim_about_the_persistence_state_contents(run):
    """Provenance only — `max(last_seen)` is not a watermark (contract §4.1)."""

    document, bodies, _, _ = run
    _, first = run_layout(document, bodies, state_sha256="a" * 64)
    _, second = run_layout(document, bodies, state_sha256="b" * 64)

    a = ri.load_run(store_of(first)[0], RUN_ID)
    b = ri.load_run(store_of(second)[0], RUN_ID)
    assert a.release_id == b.release_id  # the state is not part of identity
    assert a.release["state_watermark"]["persistence_state_sha256"] == "a" * 64
    assert b.release["state_watermark"]["persistence_state_sha256"] == "b" * 64


def test_a_non_canonical_ledger_file_is_accepted(run):
    """Inherited non-requirement: the producer's generator pretty-prints."""

    _, _, _, stored = run
    body = stored[f"runs/{RUN_ID}/ledger.json"][0]
    assert b"\n  " in body, "the fixture should be pretty-printed"
    assert ri.load_run(store_of(stored)[0], RUN_ID).release_id.startswith("rel-g1-")


# ── reading a run never writes ───────────────────────────────────────────────

def test_loading_a_run_writes_nothing(run):
    _, _, _, stored = run
    store, fake = store_of(stored)
    ri.load_run(store, RUN_ID)
    assert fake.writes == []


def test_the_read_only_store_refuses_every_write(run):
    """The lane-2 identity is handed an object with no expressible write."""

    _, _, _, stored = run
    fake = FakeS3(stored)
    store = ri.ReadOnlyStore(fake, cs.STAGING_BUCKET)
    ri.load_run(store, RUN_ID)  # reading still works

    for call in (
        lambda: store.put_if_absent("k", b"x", "application/json"),
        lambda: store.put_if_match("k", b"x", "application/json", '"e"'),
        lambda: store.put_if_pointer_absent("k", b"x", "application/json"),
    ):
        with pytest.raises(cs.ObjectStoreError, match="refusing to write"):
            call()
    assert fake.writes == []


def test_the_read_only_store_overrides_every_write_the_base_class_has():
    """A write added to ConditionalStore later must not silently be allowed."""

    writes = {
        name
        for name in vars(cs.ConditionalStore)
        if name.startswith("put") or name.startswith("delete")
    }
    assert writes, "the base store should expose at least one write"
    assert writes <= set(vars(ri.ReadOnlyStore))


# ── intent is declared, and a declaration the bytes contradict is refused ────

def test_a_date_product_whose_bytes_are_a_sealed_artifact_is_refused(run):
    """The reachable direction of the 2B.2B CLI defect.

    Omitting `acquisition_id` on a real artifact would publish it as an object
    the ledger makes no claim about, silently dropping the checksum
    cross-check.  Either the id was forgotten or the file is wrong; neither is
    resolved by relabelling.
    """

    document, bodies, run_document, stored = run
    victim = run_document["objects"][0]
    victim.pop("acquisition_id")
    victim["kind"] = "date_product"
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )

    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("product_is_a_sealed_artifact",)
    assert "acquisition_id was omitted" in str(raised.value)


def test_a_genuine_date_product_is_accepted(run):
    """A derived product the ledger makes no claim about is a permitted shape."""

    document, bodies, run_document, stored = run
    body = b'{"alerts":1,"observed_on":"2026-04-07"}'
    assert sha256_bytes(body) not in json.dumps(document)
    run_document["objects"].append(
        {
            "path": "summary/2026-04-07.json",
            "source": "objects/summary.json",
            "kind": "date_product",
            "observed_on": "2026-04-07",
            "content_type": "application/json",
        }
    )
    stored[f"runs/{RUN_ID}/objects/summary.json"] = (body, "application/json")
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )

    staged = ri.load_run(store_of(stored)[0], RUN_ID)
    kinds = {
        item["path"]: item["provenance"]["kind"] for item in staged.release["objects"]
    }
    assert kinds["summary/2026-04-07.json"] == "date_product"


def test_an_artifact_whose_bytes_do_not_match_its_acquisition_is_refused(run):
    """The checksum cross-check still fires when the id IS declared."""

    document, bodies, run_document, stored = run
    source = run_document["objects"][0]["source"]
    stored[f"runs/{RUN_ID}/{source}"] = (b'{"tampered":true}', "application/geo+json")

    with pytest.raises(ReleaseRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("artifact_checksum_mismatch",)


# ── a half-uploaded prefix reports everything, not the first thing ───────────

def test_every_absent_object_is_reported_in_one_read(run):
    document, bodies, run_document, stored = run
    for item in run_document["objects"]:
        stored.pop(f"runs/{RUN_ID}/{item['source']}")

    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert set(raised.value.codes) == {"run_object_absent"}
    assert len(raised.value.findings) == 2
    assert "2 finding(s)" in str(raised.value)


def test_an_unreadable_object_is_not_read_as_an_absent_one(run):
    """A credential or network failure must never look like "not there"."""

    _, _, run_document, stored = run
    key = f"runs/{RUN_ID}/{run_document['objects'][0]['source']}"
    fake = FakeS3(stored)
    original = fake.get_object

    def flaky(Bucket, Key):
        if Key == key:
            from tests.fake_object_store import client_error

            raise client_error("AccessDenied", "GetObject", 403)
        return original(Bucket=Bucket, Key=Key)

    fake.get_object = flaky
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(cs.ConditionalStore(fake, cs.STAGING_BUCKET), RUN_ID)
    assert raised.value.codes == ("run_object_unreadable",)


def test_a_duplicate_logical_path_is_refused(run):
    document, bodies, run_document, stored = run
    run_document["objects"].append(dict(run_document["objects"][0]))
    run_document["objects"][-1]["source"] = "objects/copy.geojson"
    stored[f"runs/{RUN_ID}/objects/copy.geojson"] = (b"{}", "application/geo+json")
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )

    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("run_object_duplicated",)


# ── the prefix itself ────────────────────────────────────────────────────────

def test_an_absent_run_manifest_names_the_key(run):
    _, _, _, stored = run
    stored.pop(f"runs/{RUN_ID}/run.json")
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("run_manifest_absent",)
    assert f"runs/{RUN_ID}/run.json" in str(raised.value)


def test_an_absent_ledger_names_the_key(run):
    _, _, _, stored = run
    stored.pop(f"runs/{RUN_ID}/ledger.json")
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("run_ledger_absent",)


def test_an_unparseable_run_manifest_is_not_treated_as_absent(run):
    _, _, _, stored = run
    stored[f"runs/{RUN_ID}/run.json"] = (b"{not json", "application/json")
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("run_manifest_unparseable",)


def test_a_run_document_may_not_claim_another_runs_inputs(run):
    _, _, run_document, stored = run
    run_document["run_id"] = "run-somebody-else"
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("run_id_mismatch",)


@pytest.mark.parametrize(
    "run_id", ["", ".", "..", "../other", "a/b", "a\\b", "with space"]
)
def test_a_run_id_that_could_address_another_prefix_is_refused(run_id):
    _, stored = run_layout(*build_ledger(SPEC))
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], run_id)
    assert raised.value.codes == ("run_id_invalid",)


@pytest.mark.parametrize(
    "source", ["../../etc/passwd", "/absolute", "objects/../../out", "objects/"]
)
def test_a_source_cannot_escape_the_run_prefix(run, source):
    _, _, run_document, stored = run
    run_document["objects"][0]["source"] = source
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert raised.value.codes == ("run_manifest_invalid",)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda d: d.__setitem__("schema", "araripe.green.run/2"), "run_manifest_invalid"),
        (lambda d: d.pop("persistence_state"), "run_manifest_invalid"),
        (lambda d: d.__setitem__("ledger", "other.json"), "run_manifest_invalid"),
        (lambda d: d.__setitem__("extra", 1), "run_manifest_invalid"),
    ],
)
def test_the_schema_owns_the_shape(run, mutate, expected):
    _, _, run_document, stored = run
    mutate(run_document)
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert expected in raised.value.codes


def test_an_artifact_must_declare_its_acquisition_and_a_product_must_not(run):
    """The two halves of the declaration cannot disagree with each other."""

    _, _, run_document, stored = run

    orphan = dict(run_document["objects"][0])
    orphan.pop("acquisition_id")  # kind stays acquisition_artifact
    run_document["objects"] = [orphan]
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert "run_manifest_invalid" in raised.value.codes

    document, bodies = build_ledger(SPEC)
    run_document, stored = run_layout(document, bodies)
    claimed = dict(run_document["objects"][0])
    claimed["kind"] = "date_product"  # keeps acquisition_id
    run_document["objects"] = [claimed]
    stored[f"runs/{RUN_ID}/run.json"] = (
        json.dumps(run_document).encode("utf-8"),
        "application/json",
    )
    with pytest.raises(ri.RunRejected) as raised:
        ri.load_run(store_of(stored)[0], RUN_ID)
    assert "run_manifest_invalid" in raised.value.codes


# ── the ledger gate runs first, and keeps its own findings ───────────────────

def test_the_ledger_gate_runs_before_any_object_body_is_read(run):
    """A rejected ledger is a different failure from a broken run prefix."""

    document, bodies, run_document, stored = run
    broken = json.loads(stored[f"runs/{RUN_ID}/ledger.json"][0])
    broken["terminal_rows"] = broken["terminal_rows"][:-1]
    stored[f"runs/{RUN_ID}/ledger.json"] = (
        json.dumps(broken).encode("utf-8"),
        "application/json",
    )

    store, fake = store_of(stored)
    with pytest.raises(LedgerRejected):
        ri.load_run(store, RUN_ID)
    sources = {f"runs/{RUN_ID}/{o['source']}" for o in run_document["objects"]}
    assert not sources & set(fake.reads)
