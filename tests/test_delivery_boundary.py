"""The public/private boundary, and the route that is the only way across it.

Package 2B.3, bullets 1 and 4.  Two properties carry most of the weight, and
both are about what the code *cannot* express rather than what it checks:

* a request never becomes an object key by string manipulation — the path is
  looked up in an allowlist built from the live manifest, so ``runs/``, a probe
  prefix and a non-live release are unreachable by construction rather than
  by filtering;
* only the **live** release is public.  A release whose promotion was refused
  and a release that was rolled back away from both stay in the bucket, and
  serving either would contradict the release the pointer names.

Everything here is a pure function of documents: no network, no clock, no
object store, no credential.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.publication import delivery_boundary as db
from scripts.check_delivery_boundary import CHAIN_FIXTURE, FIXTURE, FIXTURES, VECTORS_PATH, build_vectors

LIVE = "rel-g1-" + "ae" * 32
OTHER = "rel-g1-" + "5f" * 32

POINTER = {"schema": "araripe.green.pointer/1", "sequence": 3, "release_id": LIVE}
MANIFEST = {
    "schema": "araripe.green.release/1",
    "release_id": LIVE,
    "release_prefix": f"releases/{LIVE}/",
    "objects": [
        {
            "path": "alerts/2026-04-07/19741870aa21.geojson",
            "bytes": 78,
            "sha256": "b1" * 32,
            "content_type": "application/geo+json",
        }
    ],
}
DECLARED = MANIFEST["objects"][0]["path"]


def serve(path, method="GET", **kwargs):
    return db.resolve(
        method, path, pointer=POINTER, manifest=MANIFEST, **kwargs
    )


def refusal_code(path, method="GET", **kwargs):
    with pytest.raises(db.DeliveryRefused) as excinfo:
        serve(path, method, **kwargs)
    return excinfo.value.codes[0]


# ── the exposure classification ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "key,exposure,reason",
    [
        (db.POINTER_KEY, db.PUBLIC, "pointer"),
        (f"releases/{LIVE}/release.json", db.PUBLIC, "live_release"),
        (f"releases/{LIVE}/alerts/2026-04-07/a.geojson", db.PUBLIC, "live_release"),
        (f"releases/{OTHER}/release.json", db.PRIVATE, "release_not_live"),
        ("runs/proof-a/run.json", db.PRIVATE, "processing_input"),
        ("green-isolation-proof/run-1/probe.json", db.PRIVATE, "verification_artifact"),
        ("promotion-identity-probe/run-1/pointer.json", db.PRIVATE, "verification_artifact"),
        ("readonly-identity-probe/run-1/write-attempt.json", db.PRIVATE, "verification_artifact"),
        ("pointers/green/history/0000000011.json", db.PRIVATE, "promotion_history"),
        ("status/green/heartbeat.json", db.PUBLIC, "heartbeat"),
        ("status/green/heartbeat.json.bak", db.PRIVATE, "unclassified"),
        ("status/green/other.json", db.PRIVATE, "unclassified"),
    ],
)
def test_every_known_prefix_classifies_to_its_documented_exposure(key, exposure, reason):
    entry = db.classify_key(key, live_release_id=LIVE)
    assert (entry.exposure, entry.reason) == (exposure, reason)


def test_the_history_root_is_the_one_the_history_writes_to():
    """Two constants for one prefix, pinned equal.

    This module deliberately imports nothing from the publication path — it is
    the one place that decides exposure — so the history root is restated here
    rather than imported, exactly as ``POINTER_KEY`` is.  A rename on one side
    only would make every history record "unclassified" again, silently.
    """

    from src.publication import promotion_history as history

    assert db.HISTORY_ROOT == history.HISTORY_ROOT
    assert db.classify_key(history.history_key(1), live_release_id=LIVE).reason == (
        "promotion_history"
    )


def test_the_route_cannot_reach_the_history():
    """The Worker serves only what the LIVE release declares, plus three names.

    So ``/data/green/history/…`` is refused by construction — the same refusal
    as any undeclared path — and nothing in the site needed to change for the
    history to stay private.
    """

    assert refusal_code("/data/green/history/0000000011.json") == (
        "not_declared_by_the_live_release"
    )


def test_an_unclassified_prefix_is_private_rather_than_unknown():
    """The policy fails closed on a prefix nobody has thought about yet.

    A future producer writing to a new root gets "private" without anyone
    editing this module, which is the direction an error should go: a prefix
    that should be public and is not is a visible bug, and the reverse is a
    disclosure.
    """

    entry = db.classify_key("scratch/whatever.json", live_release_id=LIVE)
    assert entry.exposure == db.PRIVATE
    assert entry.reason == "unclassified"


def test_without_a_pointer_no_release_is_public():
    """No pointer means nothing was promoted, so nothing is live.

    A boundary that guessed — "there is only one release, it must be the one" —
    would serve a release an operator never promoted, which is exactly what
    happened to `rel-g1-9f1ed344…`: published, refused, and still in the bucket.
    """

    for key in (f"releases/{LIVE}/release.json", f"releases/{OTHER}/release.json"):
        assert db.classify_key(key, live_release_id=None).exposure == db.PRIVATE
    assert db.classify_key(db.POINTER_KEY, live_release_id=None).is_public


def test_a_key_directly_under_releases_names_no_release():
    entry = db.classify_key("releases/stray.json", live_release_id=LIVE)
    assert entry.reason == "release_prefix_malformed"
    assert entry.exposure == db.PRIVATE


# ── the route: what it serves ────────────────────────────────────────────────


def test_the_pointer_is_served_and_never_cached():
    served = serve("/data/green/current.json")
    assert served.key == db.POINTER_KEY
    assert served.headers["Cache-Control"] == "no-store"


def test_a_declared_product_resolves_under_the_live_release_prefix():
    served = serve(f"/data/green/{DECLARED}")
    assert served.key == f"releases/{LIVE}/{DECLARED}"
    assert served.headers["Content-Type"] == "application/geo+json"
    assert served.sha256 == "b1" * 32
    assert served.bytes == 78


def test_the_etag_is_the_scientific_checksum_not_the_stores_token():
    """The declared sha256, quoted — deliberately not R2's ETag.

    R2's ETag is the MD5 of the body for a single PutObject and the MD5 of the
    part MD5s with a ``-N`` suffix for a multipart one.  Measured against the
    live blue object on 2026-09-07: ``run-2026-08-30.geojson`` answers
    ``ETag: "82d98a0bca9f8a9669fba81d824c79db-2"``.  Passing that through would
    hand consumers a validator they cannot compute, next to a manifest field
    they can.
    """

    served = serve(f"/data/green/{DECLARED}")
    assert served.headers["ETag"] == '"' + "b1" * 32 + '"'
    assert served.headers["X-Araripe-Sha256"] == "b1" * 32
    assert "-" not in served.headers["ETag"].strip('"')


def test_head_resolves_exactly_as_get_does():
    assert serve(f"/data/green/{DECLARED}", "HEAD") == serve(f"/data/green/{DECLARED}")


def test_a_download_filename_comes_from_the_declared_path():
    served = serve(f"/data/green/{DECLARED}", download=True)
    assert served.headers["Content-Disposition"] == (
        'attachment; filename="19741870aa21.geojson"'
    )


def test_no_response_carries_a_cross_origin_permission():
    """Same-origin is the whole point of the ``/data/...`` route.

    The blue path serves 13.8 MiB of alerts from ``pub-…r2.dev`` and needs the
    bucket's CORS policy to name the final domain — measured 2026-09-07: the
    preflight answers ``Access-Control-Allow-Origin:
    https://observatoriodachapadadoararipe.com`` with ``Vary: Origin``.  Adding
    ``*`` here would rebuild that surface wider than it started.
    """

    for path in ("/data/green/current.json", "/data/green/release.json",
                 f"/data/green/{DECLARED}"):
        headers = serve(path).headers
        assert not any(name.lower().startswith("access-control") for name in headers)


def test_every_response_refuses_content_type_sniffing():
    for path in ("/data/green/current.json", f"/data/green/{DECLARED}"):
        assert serve(path).headers["X-Content-Type-Options"] == "nosniff"


# ── the route: what it refuses, and why the refusal has that shape ───────────


@pytest.mark.parametrize(
    "path",
    [
        "/data/green/runs/proof-a-2026-09-07/run.json",
        "/data/green/../pointers/green/current.json",
        "/data/green/../../etc/passwd",
        "/data/green//etc/passwd",
        "/data/green/./alerts/2026-04-07/19741870aa21.geojson",
        "/data/green/alerts/2026-04-07/19741870aa21.geojson/",
        "/data/green/alerts\\2026-04-07\\19741870aa21.geojson",
        f"/data/green/releases/{OTHER}/release.json",
        f"/data/green/releases/{LIVE}/release.json",
        "/data/green/green-isolation-proof/run-1/probe.json",
        "/data/green/",
        "/data/green/alerts",
        "/data/green/ALERTS/2026-04-07/19741870aa21.geojson",
    ],
)
def test_anything_the_live_release_does_not_declare_is_refused(path):
    """One code for all of them, and that is the design.

    None of these is refused for *looking* dangerous.  They are refused because
    the only strings that ever become a key are the ones the live manifest
    declares, so traversal, a private prefix and a simple typo are the same
    kind of miss.  A denylist would have to enumerate the first two and would
    still be a denylist.
    """

    assert refusal_code(path) == "not_declared_by_the_live_release"


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE", "PATCH", "OPTIONS", "get"])
def test_only_get_and_head_are_answered(method):
    assert refusal_code(f"/data/green/{DECLARED}", method) == "method_not_allowed"


@pytest.mark.parametrize(
    "path", ["/data/alerts/manifest.json", "/data/green", "/", "/api/chat", "/datagreen/x"]
)
def test_the_mount_never_claims_a_path_outside_itself(path):
    """The route owns one namespace and does not fall back to another.

    ``/data/alerts/manifest.json`` is a *static asset the site publishes today*.
    A mount that matched it would switch every consumer the moment it deployed,
    which is the opposite of Package 2B.3's third bullet — copy and verify
    before switching consumers, and retain the old paths for rollback.
    """

    assert refusal_code(path) == "outside_mount"


def test_a_manifest_that_is_not_the_live_release_is_refused():
    stale = dict(MANIFEST, release_id=OTHER, release_prefix=f"releases/{OTHER}/")
    with pytest.raises(db.DeliveryRefused) as excinfo:
        db.resolve("GET", "/data/green/release.json", pointer=POINTER, manifest=stale)
    assert excinfo.value.codes[0] == "manifest_is_not_live"


def test_without_a_pointer_the_route_serves_nothing():
    for path in ("/data/green/current.json", f"/data/green/{DECLARED}"):
        with pytest.raises(db.DeliveryRefused) as excinfo:
            db.resolve("GET", path, pointer=None, manifest=None)
        assert excinfo.value.codes[0] == "pointer_absent"


# ── the one manifest field the producer promises nothing about ───────────────


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json\r\nX-Injected: yes",
        "application/json\nSet-Cookie: a=b",
        "application/json\r\n\r\n<script>",
        "",
        "notamediatype",
        "application/json; charset=\x00",
        "application/json\x7f",
    ],
)
def test_a_content_type_the_schema_permits_but_a_header_must_not_carry(content_type):
    """``content_type`` is ``{"type": "string", "minLength": 1}`` and no more.

    The release schema constrains ``path`` with a strict ``logical_path``
    pattern and ``sha256`` with a hex pattern, and leaves this field open.  The
    producer therefore promises nothing about it, so the delivery layer refuses
    rather than trusts — the ``LEDGER_CONTRACT_BINDING_V1.md`` §5 rule read the
    other way round.  A CR or LF here splits the response.
    """

    manifest = json.loads(json.dumps(MANIFEST))
    manifest["objects"][0]["content_type"] = content_type
    with pytest.raises(db.DeliveryRefused) as excinfo:
        db.resolve("GET", f"/data/green/{DECLARED}", pointer=POINTER, manifest=manifest)
    assert excinfo.value.codes[0] == "content_type_unusable"


@pytest.mark.parametrize(
    "content_type",
    [
        "application/geo+json",
        "application/json; charset=utf-8",
        "text/csv",
        "image/tiff; application=geotiff",
        'text/plain; charset="utf-8"',
    ],
)
def test_the_media_types_this_project_actually_publishes_are_accepted(content_type):
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["objects"][0]["content_type"] = content_type
    served = db.resolve(
        "GET", f"/data/green/{DECLARED}", pointer=POINTER, manifest=manifest
    )
    assert served.headers["Content-Type"] == content_type


# ── the layout's own names ───────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["release.json", "ledger.json", "current.json", "heartbeat.json", "sources.json"])
def test_a_product_may_not_be_published_at_a_reserved_layout_name(path):
    """Reachable, and not a re-check of the schema.

    ``logical_path`` permits both strings and ``check_green_release`` has no
    opinion about them, so without this a product could decide what
    ``/data/green/release.json`` means.
    """

    manifest = json.loads(json.dumps(MANIFEST))
    manifest["objects"][0]["path"] = path
    with pytest.raises(db.BoundaryViolation) as excinfo:
        db.check_release_layout(manifest)
    assert excinfo.value.codes[0] == "product_shadows_release_document"


def test_a_normal_release_passes_the_layout_check():
    db.check_release_layout(MANIFEST)


def test_the_public_surface_is_derived_from_the_manifest_not_restated():
    keys = db.public_keys(MANIFEST)
    assert keys == (
        db.POINTER_KEY,
        db.HEARTBEAT_KEY,
        f"releases/{LIVE}/release.json",
        f"releases/{LIVE}/ledger.json",
        f"releases/{LIVE}/{DECLARED}",
    )
    for key in keys:
        assert db.classify_key(key, live_release_id=LIVE).is_public


# ── the structural claim, checked rather than asserted ───────────────────────


def test_no_resolved_key_ever_leaves_the_live_release_or_the_pointer():
    """Whatever a request says, the key is one of a fixed, tiny set.

    This is the property the whole module exists for, so it is exercised over
    every reserved name and every declared path rather than argued for in a
    comment.
    """

    allowed = set(db.public_keys(MANIFEST))
    paths = [
        "/data/green/current.json",
        "/data/green/heartbeat.json",
        "/data/green/release.json",
        "/data/green/ledger.json",
        f"/data/green/{DECLARED}",
    ]
    for path in paths:
        assert serve(path, heartbeat=FIXTURE["heartbeat"]).key in allowed


def test_the_committed_vectors_match_the_authority():
    """The vectors are the reference; two implementations of one policy drift.

    Package 2B.4 writes the Worker that answers these requests, in another
    language.  It must pass this same file, and a policy change that forgets to
    regenerate it fails here first.
    """

    stored = json.loads(Path(VECTORS_PATH).read_text(encoding="utf-8"))
    assert stored == build_vectors()


def test_every_vector_case_is_named_for_a_property_and_none_repeats():
    stored = json.loads(Path(VECTORS_PATH).read_text(encoding="utf-8"))
    names = [case["name"] for case in stored["cases"]]
    assert len(names) == len(set(names))
    assert stored["mount"] == db.MOUNT
    assert stored["fixtures"] == FIXTURES
    assert {case["fixture"] for case in stored["cases"]} == set(FIXTURES)
    outcomes = {case["expect"]["outcome"] for case in stored["cases"]}
    assert outcomes == {"served", "refused"}


# ── PHASE_6J §2.4: a version-3 release serves its members' objects ──────────


def _chain(patch=None):
    manifest = json.loads(json.dumps(CHAIN_FIXTURE["manifest"]))
    if patch:
        manifest["objects"][0].update(patch)
    return CHAIN_FIXTURE["pointer"], manifest


def test_a_referenced_object_resolves_to_its_members_prefix():
    pointer, manifest = _chain()
    for item in manifest["objects"]:
        served = db.resolve("GET", db.MOUNT + item["path"], pointer=pointer, manifest=manifest)
        assert served.key == f"releases/{item['release_id']}/{item['path']}"
        assert served.headers["X-Araripe-Release-Id"] == manifest["release_id"]


@pytest.mark.parametrize(
    "owner",
    ["rel-g1-" + "00" * 32, "../runs/ci-1", "rel-g3-" + "d4" * 32, "", None, 7],
    ids=["unlisted", "traversal", "the-chain-itself", "empty", "null", "not-a-string"],
)
def test_an_object_that_names_no_listed_member_is_refused(owner):
    pointer, manifest = _chain({"release_id": owner})
    with pytest.raises(db.DeliveryRefused) as raised:
        db.resolve("GET", db.MOUNT + manifest["objects"][0]["path"],
                   pointer=pointer, manifest=manifest)
    assert raised.value.codes == ("object_release_unusable",)


def test_a_member_listed_with_a_malformed_id_does_not_become_a_prefix():
    """The member list is itself filtered: listing a bad id authorises nothing."""

    pointer, manifest = _chain({"release_id": "../runs/ci-1"})
    manifest["members"].append({"release_id": "../runs/ci-1"})
    with pytest.raises(db.DeliveryRefused) as raised:
        db.resolve("GET", db.MOUNT + manifest["objects"][0]["path"],
                   pointer=pointer, manifest=manifest)
    assert raised.value.codes == ("object_release_unusable",)


def test_the_public_surface_of_a_chain_release_is_its_index_and_its_members_objects():
    pointer, manifest = _chain()
    keys = set(db.public_keys(manifest))
    assert keys == {
        db.POINTER_KEY,
        db.HEARTBEAT_KEY,
        manifest["release_prefix"] + "release.json",
        manifest["release_prefix"] + "ledger.json",
        *(f"releases/{o['release_id']}/{o['path']}" for o in manifest["objects"]),
    }


def test_a_member_of_the_live_release_is_public_and_another_release_is_not():
    _, manifest = _chain()
    members = db.live_member_ids(manifest)
    member = manifest["members"][0]["release_id"]
    assert db.classify_key(f"releases/{member}/x.geojson", live_release_id=manifest["release_id"],
                           live_members=members).reason == "member_of_the_live_release"
    other = "rel-g1-" + "99" * 32
    assert not db.classify_key(f"releases/{other}/x.geojson", live_release_id=manifest["release_id"],
                               live_members=members).is_public
    assert db.live_member_ids(None) == frozenset()
    assert db.live_member_ids(FIXTURE["manifest"]) == frozenset()


# ── the automation heartbeat (GREEN_HEARTBEAT_CONTRACT_V1.md §5) ────────────


HEARTBEAT = FIXTURE["heartbeat"]


def test_the_heartbeat_is_resolved_without_a_pointer_or_a_manifest():
    served = db.resolve("GET", "/data/green/heartbeat.json", pointer=None,
                        manifest=None, heartbeat=HEARTBEAT)
    assert served.key == db.HEARTBEAT_KEY
    assert served.headers["Cache-Control"] == "no-store"
    assert served.sha256 is None and served.bytes is None
    assert "X-Araripe-Release-Id" not in served.headers


def test_the_heartbeat_is_resolved_before_any_release_name():
    """A manifest declaring ``heartbeat.json`` cannot take the name over."""

    manifest = json.loads(json.dumps(MANIFEST))
    manifest["objects"][0]["path"] = "heartbeat.json"
    served = db.resolve("GET", "/data/green/heartbeat.json", pointer=POINTER,
                        manifest=manifest, heartbeat=HEARTBEAT)
    assert served.key == db.HEARTBEAT_KEY


@pytest.mark.parametrize(
    "heartbeat, code",
    [
        (None, "heartbeat_absent"),
        ({**HEARTBEAT, "schema": "araripe.green.pointer/2"}, "heartbeat_unusable"),
        ({k: v for k, v in HEARTBEAT.items() if k != "schema"}, "heartbeat_unusable"),
        (["araripe.green.heartbeat/1"], "heartbeat_unusable"),
    ],
)
def test_a_missing_or_foreign_heartbeat_is_refused_under_its_own_code(heartbeat, code):
    with pytest.raises(db.DeliveryRefused) as excinfo:
        db.resolve("GET", "/data/green/heartbeat.json", pointer=POINTER,
                   manifest=MANIFEST, heartbeat=heartbeat)
    assert excinfo.value.codes == (code,)


def test_no_other_request_depends_on_the_heartbeat():
    """The release half of the route answers the same with or without one."""

    for path in ("/data/green/current.json", "/data/green/release.json", f"/data/green/{DECLARED}"):
        assert serve(path) == serve(path, heartbeat=HEARTBEAT)


def test_the_vector_heartbeat_is_a_valid_heartbeat():
    from src.publication import heartbeat as hb

    hb.check_heartbeat(HEARTBEAT)


# ── the sources document (delivery/3, GREEN_SOURCES_CONTRACT_V1.md §6) ───────

SOURCES_ID = "src-g1-" + "5a" * 32
SOURCES_KEY = f"sources/{SOURCES_ID}/sources.json"


def _sources(context_id=None, **pointer_overrides):
    pointer = {"schema": "araripe.green.sources-pointer/1", "sequence": 1, "sources_id": SOURCES_ID,
               "release_id": LIVE, "context_id": context_id,
               "sources_document_sha256": "f3" * 32, **pointer_overrides}
    document = {"schema": "araripe.green.sources/1", "sources_id": SOURCES_ID,
                "release_id": LIVE, "context_id": context_id}
    return {"sources_pointer": pointer, "sources": document}


def test_the_live_sources_are_public_and_every_other_sources_key_is_private():
    assert db.classify_key(SOURCES_KEY, live_release_id=LIVE, live_sources_id=SOURCES_ID) == db.Exposure(
        SOURCES_KEY, db.PUBLIC, "live_sources")
    other = "sources/src-g1-" + "6b" * 32 + "/sources.json"
    assert db.classify_key(other, live_release_id=LIVE, live_sources_id=SOURCES_ID).reason == "sources_not_live"
    # the pointer is read by the resolver and never public, live or not
    assert db.classify_key(db.SOURCES_CURRENT_KEY, live_release_id=LIVE,
                           live_sources_id=SOURCES_ID).reason == "sources_pointer"
    # a sibling of the document under the live id is not the document
    sibling = f"sources/{SOURCES_ID}/sources.json.bak"
    assert db.classify_key(sibling, live_release_id=LIVE, live_sources_id=SOURCES_ID).exposure == db.PRIVATE
    # with no live sources named, nothing under sources/ is public
    assert db.classify_key(SOURCES_KEY, live_release_id=LIVE).exposure == db.PRIVATE


def test_the_sources_resolve_to_the_key_their_pointer_names_never_the_request():
    served = serve("/data/green/sources.json", **_sources())
    assert served.key == SOURCES_KEY
    assert served.headers["X-Araripe-Sources-Id"] == SOURCES_ID
    assert served.headers["ETag"] == '"' + "f3" * 32 + '"'
    assert "X-Araripe-Context-Id" not in served.headers
    assert served.headers["Cache-Control"] == db.CACHE_RESOLVED


def test_the_sources_name_the_live_context_when_one_is_live():
    context_id = "ctx-g1-" + "c9" * 32
    context_pointer = {"release_id": LIVE, "context_id": context_id}
    served = serve("/data/green/sources.json", context_pointer=context_pointer, **_sources(context_id))
    assert served.headers["X-Araripe-Context-Id"] == context_id
    # the same document, with that context no longer live, is not served
    assert refusal_code("/data/green/sources.json", **_sources(context_id)) == "sources_not_live"


def test_the_live_context_is_the_pointers_only_for_the_live_release():
    assert db.live_context_id(MANIFEST, None) is None
    assert db.live_context_id(MANIFEST, {"release_id": OTHER, "context_id": "ctx-g1-" + "c9" * 32}) is None
    assert db.live_context_id(MANIFEST, {"release_id": LIVE, "context_id": "x"}) == "x"
