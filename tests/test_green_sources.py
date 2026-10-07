"""The sources and attributions of a green publication (GREEN_SOURCES_CONTRACT_V1.md).

The first block measures why the sources cannot live inside ``release.json``
(PHASE_6V §2) — so that the decision stays argued by a test, not by prose.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.publication import conditional_store as cs
from src.publication import green_context as gc
from src.publication import green_sources as gs
from src.publication.canonical_json import identity_sha256
from src.publication.green_release import release_bytes, schema_validator
from tests.fake_object_store import FakeS3
from tests.test_green_release import release_for

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "config/green_sources_v1.json").read_text(encoding="utf-8"))
VECTORS = json.loads((ROOT / "docs/contracts/phase2b/sources_conformance_vectors.json").read_text(encoding="utf-8"))
FIXTURE = VECTORS["fixture"]


def _context_for(release: dict, spec: dict = SPEC, tables: dict = FIXTURE["group_tables"]) -> dict:
    rasters = [
        {"collection_key": r["collection_key"], "collection": r["collection"], "year": r["year"],
         "origin_url": r["origin_url"], "crop_sha256": r["crop"]["sha256"],
         "source_md5": r["source_checksum"]["md5"]}
        for r in spec["sources"] if r["role"] == gs.ROLE_CONTEXT
    ]
    group_tables = {key: {int(code): group for code, group in table.items()} for key, table in tables.items()}
    return gc.context_document(release=release, spec=gc.build_spec(rasters, group_tables), dates=[], objects=[])


@pytest.fixture(scope="module")
def published():
    release, ledger, _bodies, _acceptance = release_for(FIXTURE["ledger_spec"])
    return release, ledger, _context_for(release)


def codes(raised) -> set[str]:
    return set(raised.value.codes)


# ── why not inside the release (PHASE_6V §2) ─────────────────────────────────

@pytest.mark.parametrize("version", ["green-release-v1", "green-release-v3"])
def test_every_release_schema_refuses_a_sources_field(published, version):
    schema = json.loads((ROOT / f"docs/contracts/phase2b/schemas/{version}.schema.json").read_text())
    assert schema["additionalProperties"] is False
    release, _, _ = published
    if version == "green-release-v1":
        errors = list(schema_validator(version).iter_errors({**release, "sources": []}))
        assert any("sources" in error.message for error in errors)


def test_a_release_json_with_sources_under_the_same_id_is_refused_by_the_store(published):
    """The trap the briefing names: same key, different bytes.

    ``release_identity`` does not read the manifest, so adding a field leaves
    the id — and therefore the key — unchanged.
    """

    release, _, _ = published
    store = cs.ConditionalStore(FakeS3(), cs.STAGING_BUCKET)
    key = release["release_prefix"] + "release.json"
    assert store.put_if_absent(key, release_bytes(release), "application/json").result == "created"
    assert store.put_if_absent(key, release_bytes(release), "application/json").result == "unchanged"
    with pytest.raises(cs.ImmutableObjectConflict):
        store.put_if_absent(key, release_bytes({**release, "sources": ["x"]}), "application/json")


# ── conformance vectors ──────────────────────────────────────────────────────

@pytest.mark.parametrize("case", VECTORS["identity"], ids=lambda c: c["sources_id"][:14])
def test_identity_vectors(case):
    digest = identity_sha256(gs.SOURCES_IDENTITY_DOMAIN, case["release_id"], case["context_id"] or "", case["spec_sha256"])
    assert gs.SOURCES_ID_PREFIX + digest == case["sources_id"]


@pytest.mark.parametrize("case", VECTORS["notice_years"], ids=lambda c: c["text"])
def test_notice_year_vectors(case):
    assert gs.years_text(case["years"]) == case["text"]


@pytest.mark.parametrize("name", ["with_context", "without_context"])
def test_the_fixture_documents_are_byte_for_byte_the_vectors(name):
    """Pins the rendering rule: same inputs, same bytes.

    If this fails after a code change, the change altered what a document
    looks like for inputs that already have an id — bump ``DERIVATION`` (a new
    id) and regenerate, never edit the digest alone.
    """

    release, ledger, _, _ = release_for(FIXTURE["ledger_spec"])
    context = _context_for(release, FIXTURE["spec"]) if name == "with_context" else None
    document = gs.build_sources(release, context, FIXTURE["spec"], [ledger])
    body = gs.serialise(document)
    want = FIXTURE[name]
    assert (document["release_id"], document["context_id"]) == (want["release_id"], want["context_id"])
    assert (document["sources_id"], document["spec_sha256"]) == (want["sources_id"], want["spec_sha256"])
    assert (hashlib.sha256(body).hexdigest(), len(body)) == (want["document_sha256"], want["bytes"])
    assert FIXTURE["spec"]["derivation"] == VECTORS["derivation"] == gs.DERIVATION


# ── identity ─────────────────────────────────────────────────────────────────

def test_the_identity_is_a_function_of_release_context_and_spec():
    rid, cid = "rel-g3-" + "ab" * 32, "ctx-g1-" + "cd" * 32
    base = gs.sources_identity(rid, cid, SPEC)[0]
    assert gs.SOURCES_ID.match(base)
    assert gs.sources_identity(rid, cid, deepcopy(SPEC))[0] == base
    assert gs.sources_identity("rel-g3-" + "ef" * 32, cid, SPEC)[0] != base
    assert gs.sources_identity(rid, "ctx-g1-" + "ef" * 32, SPEC)[0] != base
    assert gs.sources_identity(rid, None, SPEC)[0] != base
    edited = deepcopy(SPEC)
    edited["sources"][0]["modification"] += " "
    assert gs.sources_identity(rid, cid, edited)[0] != base


def test_without_a_context_the_2025_records_are_not_sealed(published):
    release, ledger, context = published
    bare = gs.build_sources(release, None, SPEC, [ledger])
    assert bare["context_id"] is None
    assert {r["role"] for r in bare["spec"]["sources"]} == {gs.ROLE_DETECTION, gs.ROLE_RELEASE}
    assert {line["applies_to"] for line in bare["attribution"]} == {"release"}
    full = gs.build_sources(release, context, SPEC, [ledger])
    assert [line["applies_to"] for line in full["attribution"]].count("context") == 2


# ── the shipped records ──────────────────────────────────────────────────────

@pytest.mark.parametrize("with_context", [True, False])
def test_the_shipped_spec_is_valid(with_context):
    sealed = gs.select_spec(SPEC, with_context=with_context)
    assert gs.spec_findings(sealed, with_context=with_context) == []


def _script():
    spec = importlib.util.spec_from_file_location("plan_green_sources", ROOT / "scripts/plan_green_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_records_match_the_freeze_and_the_tracked_crops():
    assert _script().repository_findings(SPEC) == []


def test_a_record_that_disagrees_with_its_crop_is_caught():
    edited = deepcopy(SPEC)
    edited["sources"][1]["crop"]["sha256"] = "0" * 64
    edited["sources"][3]["origin_url"] = "https://example.org/other.tif"
    problems = _script().repository_findings(edited)
    assert any("mapbiomas-10m-col2-beta-2023" in p for p in problems)
    assert any("origin_url" in p for p in problems)


# ── spec rules ───────────────────────────────────────────────────────────────

def _spec_codes(mutate, with_context=True) -> set[str]:
    edited = deepcopy(SPEC)
    mutate(edited)
    return {f.code for f in gs.spec_findings(gs.select_spec(edited, with_context=with_context), with_context=with_context)}


@pytest.mark.parametrize("mutate, code", [
    (lambda s: s["sources"][3].update(accessed_on=None), "silent_gap"),
    (lambda s: s["sources"][1].update(open_gaps=s["sources"][1]["open_gaps"] + ["year: unknown"]), "gap_stale"),
    (lambda s: s["sources"][1].update(open_gaps=["colour: x"] + s["sources"][1]["open_gaps"]), "gap_unknown_field"),
    (lambda s: s["sources"][1].update(citation=None, open_gaps=s["sources"][1]["open_gaps"] + ["citation: x"]), "gap_not_allowed"),
    (lambda s: s["sources"][1].pop("applies_to_fields"), "field_missing"),
    (lambda s: s["sources"][0].update(baseline_years=[2017.0]), "spec_float"),
    (lambda s: s.update(derivation="araripe.green.sources-derivation/2"), "spec_derivation"),
    (lambda s: s["sources"][0].update(notice_template="Contains modified Copernicus Sentinel data"), "notice_template"),
    (lambda s: s["sources"][0]["licence"].update(url=""), "licence_incomplete"),
    (lambda s: s["sources"].append(deepcopy(s["sources"][0])), "source_repeated"),
    (lambda s: s["sources"].pop(2), "collection_keys"),
])
def test_a_spec_that_hides_or_misstates_provenance_is_refused(mutate, code):
    assert code in _spec_codes(mutate)


def test_context_records_are_refused_in_a_document_without_a_context():
    sealed = gs.select_spec(SPEC, with_context=True)
    assert "collection_keys" in {f.code for f in gs.spec_findings(sealed, with_context=False)}


# ── check_sources ────────────────────────────────────────────────────────────

def test_a_built_document_checks_after_a_round_trip(published):
    release, ledger, context = published
    for ctx in (context, None):
        document = gs.build_sources(release, ctx, SPEC, [ledger])
        assert gs.check_sources(json.loads(gs.serialise(document)), release, ctx, [ledger]) == document


@pytest.mark.parametrize("edit, code", [
    (lambda d: d["attribution"][0].update(text="Contains Copernicus data"), "does_not_derive"),
    (lambda d: d["derived"]["detection"].update(observation_years=[2026]), "does_not_derive"),
    (lambda d: d.update(sources_id="src-g1-" + "0" * 64), "does_not_derive"),
    (lambda d: d["spec"]["sources"][0].update(provider="someone else"), "does_not_derive"),
    (lambda d: d.update(release_id="rel-g1-" + "0" * 64), "release_mismatch"),
    (lambda d: d.update(extra=1), "schema_invalid"),
])
def test_an_edited_document_is_refused(published, edit, code):
    release, ledger, context = published
    document = json.loads(gs.serialise(gs.build_sources(release, context, SPEC, [ledger])))
    edit(document)
    with pytest.raises(gs.SourcesRejected) as raised:
        gs.check_sources(document, release, context, [ledger])
    assert code in codes(raised)


def test_a_document_is_checked_against_the_context_it_names(published):
    release, ledger, context = published
    document = json.loads(gs.serialise(gs.build_sources(release, context, SPEC, [ledger])))
    with pytest.raises(gs.SourcesRejected) as raised:
        gs.check_sources(document, release, None, [ledger])
    assert "context_mismatch" in codes(raised)


def test_the_2025_records_must_be_what_the_context_recipe_used(published):
    release, ledger, context = published
    other = deepcopy(context)
    other["spec"]["rasters"][0]["crop_sha256"] = "9" * 64
    with pytest.raises(gs.SourcesRejected) as raised:
        gs.build_sources(release, other, SPEC, [ledger])
    assert "context_binding" in codes(raised)


def test_the_ledgers_must_be_the_releases_own(published):
    release, _, context = published
    _, other_ledger, _, _ = release_for({"2026-03-01": ["complete_zero_alerts"]})
    with pytest.raises(gs.SourcesRejected) as raised:
        gs.build_sources(release, context, SPEC, [other_ledger])
    assert "ledgers_mismatch" in codes(raised)


def test_the_detection_source_is_the_collection_the_ledgers_read(published):
    release, ledger, _ = published
    sealed = gs.select_spec(SPEC, with_context=False)
    acceptance = SimpleNamespace(ledger_id=release["ledger"]["ledger_id"],
                                 document_sha256=release["ledger"]["document_sha256"])
    assert gs.ledger_findings(release, [ledger], [acceptance], sealed) == []
    landsat = deepcopy(ledger)
    landsat["expected_acquisitions"][0]["collection_id"] = "LANDSAT/LC09/C02/T1_L2"
    found = gs.ledger_findings(release, [landsat], [acceptance], sealed)
    assert [f.code for f in found] == ["detection_collection"]


def test_a_date_without_usable_data_adds_no_year(published):
    release, _, _ = published
    assert [d["usable_acquisition_count"] for d in release["dates"]] == [1, 0]
    assert gs.observation_years(release) == [2025]


def test_the_ledgers_of_each_release_version_are_found():
    v3 = {"schema": "araripe.green.release/3",
          "members": [{"ledger_id": "a", "document_sha256": "1"}, {"ledger_id": "b", "document_sha256": "2"}]}
    v2 = {"schema": "araripe.green.release/2", "ledgers": {"chain": v3["members"]}}
    assert gs.release_ledgers(v3) == gs.release_ledgers(v2) == [("a", "1"), ("b", "2")]
    with pytest.raises(gs.SourcesRejected):
        gs.release_ledgers({"schema": "araripe.green.release/9"})


# ── exposure and retention: a new family is private and kept until classified ─

@pytest.mark.parametrize("key", ["sources/current.json", "sources/src-g1-" + "a" * 64 + "/sources.json"])
def test_the_sources_family_is_private_and_never_eligible_today(key):
    from src.publication import delivery_boundary as db
    from src.publication import retention as rt

    assert db.classify_key(key, live_release_id="rel-g3-" + "b" * 64).exposure == db.PRIVATE
    entry = rt.classify(rt.StoredKey(key, 1, datetime(2026, 1, 1, tzinfo=timezone.utc)),
                        pointer=None, runs={}, as_of=datetime(2026, 10, 7, tzinfo=timezone.utc))
    assert (entry.action, entry.reason) == (rt.REVIEW, "unclassified_prefix")


# ── the pointer ──────────────────────────────────────────────────────────────

class _Store:
    def __init__(self, current: bytes | None = None):
        from src.publication.conditional_store import StoredObject
        self.calls = []
        self._current = None if current is None else StoredObject(gs.SOURCES_CURRENT_KEY, current, '"e1"')

    def get(self, key):
        assert key == gs.SOURCES_CURRENT_KEY
        return self._current

    def put_if_pointer_absent(self, key, body, content_type):
        self.calls.append(("absent", key, json.loads(body)))

    def put_if_match(self, key, body, content_type, etag):
        self.calls.append(("match", key, json.loads(body), etag))


def test_the_sources_pointer_is_created_then_swapped_never_rewritten_in_place(published):
    from src.publication import sources_pointer

    release, ledger, context = published
    document = gs.build_sources(release, context, SPEC, [ledger])
    body = gs.serialise(document)
    store = _Store()
    assert sources_pointer.move(store, document, body, {"workflow": "t"}) == "moved"
    (kind, key, written), = store.calls
    assert (kind, key, written["sequence"]) == ("absent", "sources/current.json", 1)
    assert written["sources_document_sha256"] == hashlib.sha256(body).hexdigest()
    assert written["sources_path"] == document["sources_prefix"] + "sources.json"
    assert (written["release_id"], written["context_id"]) == (release["release_id"], context["context_id"])

    same = _Store(gs.serialise(written))
    assert sources_pointer.move(same, document, body, {}) == "unchanged" and same.calls == []

    other = _Store(gs.serialise({**written, "sources_id": "src-g1-" + "0" * 64}))
    assert sources_pointer.move(other, document, body, {}) == "moved"
    (kind, _key, swapped, etag), = other.calls
    assert (kind, etag, swapped["sequence"]) == ("match", '"e1"', 2)


def test_the_sources_pointer_never_names_the_release_pointer():
    """H2: one writer under ``pointers/green/``.  Read the code, not the prose."""

    assert not gs.SOURCES_CURRENT_KEY.startswith("pointers/")
    tree = ast.parse((ROOT / "src/publication/sources_pointer.py").read_text())
    docstrings = {
        id(node.body[0].value) for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body
        and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    strings = [node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]
    assert not any("pointers/" in value for value in strings)


# ── the plan script ──────────────────────────────────────────────────────────

def test_plan_writes_a_document_that_checks_and_touches_no_store(tmp_path, published, capsys):
    release, ledger, context = published
    paths = {}
    for name, doc in (("release", release), ("context", context), ("ledger", ledger)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(doc))
    out = tmp_path / "out"
    code = _script().main(["--release", str(paths["release"]), "--context", str(paths["context"]),
                           "--ledger", str(paths["ledger"]), "--out", str(out)])
    assert code == 0
    written = json.loads((out / "sources.json").read_bytes())
    assert gs.check_sources(written, release, context, [ledger]) == written
    assert "Contains modified Copernicus Sentinel data 2017–2025" in capsys.readouterr().out
    imported = set()
    for node in ast.walk(ast.parse((ROOT / "scripts/plan_green_sources.py").read_text())):
        if isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module}.{alias.name}" for alias in node.names} | {node.module}
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert not any("conditional_store" in name or name.startswith("config") for name in imported)
