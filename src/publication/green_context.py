"""The land-cover context of a green release: labels that live beside it.

Contract: ``docs/contracts/phase2b/GREEN_CONTEXT_CONTRACT_V1.md``.

Why a separate layer
--------------------
A release's prefix is a function of its ledger alone
(``green_release.release_identity``), and the ledger does not seal the
land-cover columns of an alert.  So re-annotating a published release with a
newer MapBiomas would offer the *same* immutable keys with *different* bytes,
which the store refuses (``ImmutableObjectConflict``) by design.  The project
already has the rule for this (``SITE_ARTIFACT_CONTRACT_V1.md`` §3): anything
computed by a rule that may change — and MapBiomas publishes a new collection
every year — does not belong inside the sealed release.

So the context is its own immutable object family, ``contexts/<context-id>/``,
whose identity is a function of the release it describes **and** of the exact
recipe (the cropped rasters by checksum, the class tables, the strong rule).
A new MapBiomas makes a new context for the same release; the release is never
touched.  One mutable key, ``contexts/current.json``, names the context
the site should use, and it is only honoured while it names the live release.

What a context carries, per date with alerts
--------------------------------------------
* ``alerts/run-<date>.lc.json`` — the land-cover labels of **every** feature of
  that date's full run, keyed by ``observation_id``.  Columnar, no geometry:
  the page merges it into the full run it already loads from the release.
* ``alerts/run-<date>.strong.geojson`` — the strong subset recomputed under the
  new labels.  It has to be a new object: the release's own strong object was
  filtered with the old labels, and the page loads the strong object by
  default.

Everything here is pure — no clock, no store, no raster.  The annotation
itself (rasterio) happens in ``scripts/publish_green_context.py``; this module
turns its result into documents and checks them.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .canonical_json import canonical_sha256, identity_sha256
from .findings import Finding, Rejected
from . import site_artifact as sa

CONTEXT_SCHEMA = "araripe.green.context/1"
CONTEXT_POINTER_SCHEMA = "araripe.green.context-pointer/1"
LABELS_SCHEMA = "araripe.green.context-labels/1"
SPEC_SCHEMA = "araripe.green.context-spec/1"

CONTEXT_ID_PREFIX = "ctx-g1-"
CONTEXT_ID = re.compile(r"^ctx-g1-[0-9a-f]{64}$")
CONTEXT_IDENTITY_DOMAIN = "araripe.green.context.identity.v1"
CONTEXTS_ROOT = "contexts/"
#: Where a context's objects are stored: by content, so identical bytes are one
#: object no matter how many contexts declare them.  Consecutive promotions
#: re-declare every unchanged date, so storing per context would copy ~300 MB
#: per promotion (measured 2026-10-06 on the live release); by content, a
#: promotion stores only the dates that are new.
CONTEXT_OBJECTS_ROOT = "contexts/objects/"
#: In the context family, not under ``pointers/green/`` (``context_pointer.py``).
CONTEXT_CURRENT_KEY = "contexts/current.json"
CONTEXT_DOCUMENT_NAME = "context.json"

#: The columns a context replaces, in the order the labels document stores
#: them.  The unsuffixed ``lc_class``/``lc_group``/``lc_natural_frac`` are the
#: default collection's (10 m) — the same backward-compatibility copy
#: ``landcover.annotate_alerts_all_collections`` writes — and are derived on
#: merge rather than stored twice.
LABEL_FIELDS = (
    "lc_class_10m",
    "lc_group_10m",
    "lc_natural_frac_10m",
    "lc_class_30m",
    "lc_group_30m",
    "lc_natural_frac_30m",
)
DEFAULT_SUFFIX = "_10m"
UNSUFFIXED = ("lc_class", "lc_group", "lc_natural_frac")

#: Natural fractions are stored rounded, as ``landcover`` already rounds them.
FRACTION_DECIMALS = 3

LABELS_SUFFIX = ".lc.json"
STRONG_SUFFIX = sa.STRONG_OBJECT_SUFFIX
LABELS_CONTENT_TYPE = "application/json"
STRONG_CONTENT_TYPE = "application/geo+json"


class ContextRejected(Rejected):
    subject = "green context"


def _refuse(code: str, detail: str, where: str = "<context>") -> ContextRejected:
    return ContextRejected([Finding(code, detail, where)])


# ── identity ─────────────────────────────────────────────────────────────────

def build_spec(rasters: Sequence[Mapping[str, Any]], group_tables: Mapping[str, Mapping[int, str]]) -> dict:
    """The recipe a context is a function of, with no float anywhere.

    ``rasters`` is one entry per collection key (``mapbiomas10m``,
    ``mapbiomas30m``) carrying the crop's sha256 and its provenance as the crop
    report states it.  Thresholds are strings because the identity is a
    canonical-JSON digest, and canonical JSON refuses floats.
    """

    keys = sorted(entry["collection_key"] for entry in rasters)
    if keys != ["mapbiomas10m", "mapbiomas30m"]:
        raise _refuse("spec_collections", f"a context needs exactly the 10 m and 30 m collections, got {keys}")
    tables = {
        name: {str(code): group for code, group in sorted(table.items())}
        for name, table in sorted(group_tables.items())
    }
    if sorted(tables) != keys:
        raise _refuse("spec_tables", f"one class table per collection, got {sorted(tables)}")
    return {
        "schema": SPEC_SCHEMA,
        "rasters": sorted(
            (
                {
                    "collection_key": entry["collection_key"],
                    "collection": entry["collection"],
                    "year": int(entry["year"]),
                    "origin_url": entry["origin_url"],
                    "crop_sha256": entry["crop_sha256"],
                    "source_md5": entry["source_md5"],
                }
                for entry in rasters
            ),
            key=lambda item: item["collection_key"],
        ),
        "group_tables": tables,
        "natural_fraction_decimals": str(FRACTION_DECIMALS),
        "strong_rule": {
            "stats_policy_version": sa.STATS_POLICY_VERSION,
            "confidence_label": sa.STRONG_CONFIDENCE_LABEL,
            "candidate_min_sightings": str(sa.CANDIDATE_MIN_SIGHTINGS),
            "min_natural_fraction_10m": str(sa.STRONG_MIN_NATURAL_FRACTION),
        },
    }


def context_identity(release_id: str, spec: Mapping[str, Any]) -> tuple[str, str]:
    """``(context_id, spec_sha256)``; the same release and recipe give the same id."""

    spec_sha256 = canonical_sha256(dict(spec))
    digest = identity_sha256(CONTEXT_IDENTITY_DOMAIN, release_id, spec_sha256)
    return CONTEXT_ID_PREFIX + digest, spec_sha256


def context_prefix(context_id: str) -> str:
    if not CONTEXT_ID.match(context_id):
        raise _refuse("context_id_malformed", f"{context_id!r} is not a context id")
    return f"{CONTEXTS_ROOT}{context_id}/"


def object_key(entry: Mapping[str, Any]) -> str:
    """The stored key of a declared context object: its sha256, nothing else."""

    digest = entry.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise _refuse("object_sha256_malformed", f"{digest!r} is not a sha256", entry.get("path", "<object>"))
    return CONTEXT_OBJECTS_ROOT + digest


def labels_path(full_path: str) -> str:
    """``alerts/run-D.geojson`` → ``alerts/run-D.lc.json``."""
    return full_path[: -len(sa.FULL_OBJECT_SUFFIX)] + LABELS_SUFFIX


def strong_path(full_path: str) -> str:
    return full_path[: -len(sa.FULL_OBJECT_SUFFIX)] + STRONG_SUFFIX


# ── labels ───────────────────────────────────────────────────────────────────

def _value(field: str, raw: Any) -> Any:
    """A JSON value for one label, or ``None`` when the raster had no pixel."""

    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    if field.startswith("lc_natural_frac"):
        return round(float(raw), FRACTION_DECIMALS)
    if field.startswith("lc_class"):
        return int(raw)
    return str(raw)


def labels_document(observed_on: str, rows: Iterable[tuple[str, Mapping[str, Any]]]) -> dict:
    """The labels of one date: ``{observation_id: [values in LABEL_FIELDS order]}``."""

    labels: dict[str, list[Any]] = {}
    for observation_id, values in rows:
        if not isinstance(observation_id, str) or not observation_id:
            raise _refuse("observation_id_missing", "every labelled feature needs its observation_id", observed_on)
        if observation_id in labels:
            raise _refuse("observation_id_repeated", f"{observation_id} labelled twice", observed_on)
        labels[observation_id] = [_value(field, values.get(field)) for field in LABEL_FIELDS]
    return {
        "schema": LABELS_SCHEMA,
        "observed_on": observed_on,
        "fields": list(LABEL_FIELDS),
        "labels": dict(sorted(labels.items())),
    }


def apply_labels(properties: Mapping[str, Any], row: Sequence[Any]) -> dict:
    """One feature's properties with the context's labels in place of its own.

    The unsuffixed columns become the 10 m ones, as the annotator writes them.
    Every other property — confidence, persistence, ids — is untouched.
    """

    merged = dict(properties)
    for field, value in zip(LABEL_FIELDS, row):
        merged[field] = value
    for name in UNSUFFIXED:
        merged[name] = merged[name + DEFAULT_SUFFIX]
    return merged


def relabel(features: Sequence[Mapping[str, Any]], labels: Mapping[str, Sequence[Any]], where: str) -> list[dict]:
    """The full run under the context's labels; the two must cover each other exactly.

    A feature without a label, or a label without a feature, means the labels
    were computed from a different run than the one being relabelled — which
    would silently mix two versions on one date.  Both directions refuse.
    """

    seen: set[str] = set()
    out: list[dict] = []
    for feature in features:
        observation_id = (feature.get("properties") or {}).get("observation_id")
        if observation_id not in labels:
            raise _refuse("feature_without_label", f"{observation_id!r} has no label in this context", where)
        if observation_id in seen:
            raise _refuse("observation_id_repeated", f"{observation_id} appears twice in the run", where)
        seen.add(observation_id)
        out.append({**feature, "properties": apply_labels(feature["properties"], labels[observation_id])})
    extra = set(labels) - seen
    if extra:
        raise _refuse(
            "label_without_feature",
            f"{len(extra)} label(s) name observations this run does not have, e.g. {sorted(extra)[0]}",
            where,
        )
    return out


def serialise(document: Mapping[str, Any]) -> bytes:
    """Deterministic bytes: sorted keys, no whitespace, UTF-8."""

    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def strong_collection(relabelled: Sequence[Mapping[str, Any]]) -> dict:
    """The strong subset under the new labels — the same rule the index counts."""

    return {"type": "FeatureCollection", "features": list(sa.strong_features(relabelled))}


# ── the context document ─────────────────────────────────────────────────────

def object_entry(path: str, body: bytes, content_type: str, observed_on: str) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "content_type": content_type,
        "observed_on": observed_on,
    }


def context_document(
    *,
    release: Mapping[str, Any],
    spec: Mapping[str, Any],
    dates: Sequence[Mapping[str, Any]],
    objects: Sequence[Mapping[str, Any]],
) -> dict:
    context_id, spec_sha256 = context_identity(release["release_id"], spec)
    return {
        "schema": CONTEXT_SCHEMA,
        "context_id": context_id,
        "context_prefix": context_prefix(context_id),
        "release_id": release["release_id"],
        "spec": dict(spec),
        "spec_sha256": spec_sha256,
        "dates": list(dates),
        "objects": sorted(objects, key=lambda item: item["path"]),
    }


def alert_dates(release: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """``(observed_on, full path, sha256 of the full object)`` per date with alerts."""

    by_path = {item["path"]: item for item in release["objects"]}
    out = []
    for date in release["dates"]:
        if date.get("alert_state") != "alerts":
            continue
        full, _strong = sa.classify_run_objects(date["paths"])
        out.append((date["observed_on"], full, by_path[full]["sha256"]))
    return out


def check_context(document: Mapping[str, Any], release: Mapping[str, Any]) -> None:
    """Every relation the context must hold against the release it names."""

    findings: list[Finding] = []

    def bad(code: str, detail: str, where: str = "<context>") -> None:
        findings.append(Finding(code, detail, where))

    if document.get("schema") != CONTEXT_SCHEMA:
        bad("schema", f"expected {CONTEXT_SCHEMA}")
    if document.get("release_id") != release.get("release_id"):
        bad("release_mismatch", f"context describes {document.get('release_id')}, the release is {release.get('release_id')}")
    expected_id, expected_spec = context_identity(release["release_id"], document["spec"])
    if document.get("context_id") != expected_id or document.get("spec_sha256") != expected_spec:
        bad("identity_mismatch", "context_id/spec_sha256 are not a function of this release and spec")
    if document.get("context_prefix") != CONTEXTS_ROOT + str(document.get("context_id")) + "/":
        bad("prefix_mismatch", "context_prefix must be contexts/<context_id>/")

    objects = {item["path"]: item for item in document.get("objects", [])}
    if len(objects) != len(document.get("objects", [])):
        bad("object_repeated", "a path is declared twice")
    wanted = alert_dates(release)
    dated = {entry["observed_on"]: entry for entry in document.get("dates", [])}
    if sorted(dated) != sorted(d for d, _, _ in wanted):
        bad("dates_mismatch", "the context must cover exactly the release's dates with alerts")
    for observed_on, full, full_sha in wanted:
        entry = dated.get(observed_on)
        if entry is None:
            continue
        where = f"dates/{observed_on}"
        if entry.get("source_path") != full or entry.get("source_sha256") != full_sha:
            bad("source_mismatch", "the labels were not computed from the release's full object", where)
        for path in (labels_path(full), strong_path(full)):
            item = objects.get(path)
            if item is None:
                bad("object_missing", f"{path} is not declared", where)
            elif item.get("observed_on") != observed_on:
                bad("object_date", f"{path} names {item.get('observed_on')}", where)
        if not (0 <= entry.get("strong_count", -1) <= entry.get("feature_count", -1)):
            bad("counts", "strong_count must lie within [0, feature_count]", where)
    allowed = {p for _, full, _ in wanted for p in (labels_path(full), strong_path(full))}
    for path in objects:
        if path not in allowed:
            bad("object_unexpected", f"{path} is not a labels or strong object of a dated run", f"objects/{path}")
    if findings:
        raise ContextRejected(findings)


def pointer_document(*, context: Mapping[str, Any], context_document_sha256: str, sequence: int, written_utc: str, written_by: Mapping[str, Any]) -> dict:
    return {
        "schema": CONTEXT_POINTER_SCHEMA,
        "sequence": sequence,
        "context_id": context["context_id"],
        "release_id": context["release_id"],
        "context_path": context["context_prefix"] + CONTEXT_DOCUMENT_NAME,
        "context_document_sha256": context_document_sha256,
        "written_utc": written_utc,
        "written_by": dict(written_by),
    }
