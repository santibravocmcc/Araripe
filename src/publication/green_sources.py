"""The sources and attributions of a green publication: a document beside it.

Contract: ``docs/contracts/phase2b/GREEN_SOURCES_CONTRACT_V1.md``.
Decision record: ``docs/implementation/PHASE_6V_2026-10-07.md``.

Why beside, and not inside ``release.json``
-------------------------------------------
The register (§3.3, §6.1) asks the release manifest to carry its sources.  It
cannot, without breaking what makes a release citable:

* a release's id is a function of its ledger (version 1) or of its members'
  ``release.json`` digests (version 3), never of attribution text — so a
  ``sources`` field added to an existing release offers the **same** key with
  **different** bytes, which ``put_if_absent`` refuses
  (``ImmutableObjectConflict``);
* every release schema (``green-release-v{1,2,3}``) is
  ``additionalProperties: false``, so the gate refuses the field anyway;
* attribution is a rule that changes: the MapBiomas terms URL in the register
  answered 404 three months later, the Esri credit changed wording, and the
  2023 crops' lineage may still be recovered.  Sealing it into a release would
  make every correction a new name for the same data
  (``SITE_ARTIFACT_CONTRACT_V1.md`` §3, the rule the context already follows).

So the sources are their own immutable family, ``sources/<sources-id>/``,
exactly as the land-cover context is.  Its identity is a function of the
release it describes, of the context it covers (or of none), and of the
reviewed records in ``config/green_sources_v1.json``.  A correction makes a new
document for the same release; the release and every earlier document stay.

What the document proves and what it only asserts
-------------------------------------------------
* **derived** — checked against the release and its ledgers: the Sentinel-2
  collection every acquisition was read from (the ledgers seal
  ``collection_id``), and the years of the observations (the release's dates
  with a usable acquisition);
* **bound to the context** — the 2025 MapBiomas records must name exactly the
  crops, origins and checksums the context's own recipe names;
* **asserted** — the 2023 crops the release's ``lc_*`` columns came from.  No
  identity input of a release seals them; their basis is the replay freeze,
  which ``replay_2026.py`` refuses to run without, and
  ``scripts/plan_green_sources.py`` checks the records against the freeze and
  the tracked files before it writes anything.

Unknown provenance is never silently omitted (register §6.4): a record may
carry ``null`` in a required field only if its ``open_gaps`` names that field,
and a gap may not be listed for a field that has a value.

Everything here is pure — no clock, no store, no file.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .canonical_json import canonical_sha256, identity_sha256
from .findings import Finding, Rejected
from .green_release import schema_validator
from .ledger_gate import check_processing_ledger

SOURCES_SCHEMA = "araripe.green.sources/1"
SOURCES_POINTER_SCHEMA = "araripe.green.sources-pointer/1"
SPEC_SCHEMA = "araripe.green.sources-spec/1"
#: The rendering rule.  A document is a function of its identity inputs only
#: while this rule is fixed, so the rule is *in* the spec: changing how a
#: document is derived from the same inputs must bump this string, which gives
#: a new id instead of different bytes under an old one.  The conformance
#: vectors pin a full document's digest, so an unbumped change fails a test.
DERIVATION = "araripe.green.sources-derivation/1"

SOURCES_ID_PREFIX = "src-g1-"
SOURCES_ID = re.compile(r"^src-g1-[0-9a-f]{64}$")
SOURCES_IDENTITY_DOMAIN = "araripe.green.sources.identity.v1"
SOURCES_ROOT = "sources/"
#: In the sources family, not under ``pointers/green/`` (one writer there).
SOURCES_CURRENT_KEY = "sources/current.json"
SOURCES_DOCUMENT_NAME = "sources.json"

ROLE_DETECTION = "detection"
ROLE_RELEASE = "release_annotation"
ROLE_CONTEXT = "context_annotation"
ROLES = (ROLE_DETECTION, ROLE_RELEASE, ROLE_CONTEXT)
COLLECTION_KEYS = ("mapbiomas10m", "mapbiomas30m")

_COMMON = ("source_id", "role", "provider", "dataset", "resolution", "official_url",
           "licence", "modification", "open_gaps")
REQUIRED = {
    ROLE_DETECTION: _COMMON + ("edition", "terms_read_on", "notice_template", "baseline_years"),
    ROLE_RELEASE: _COMMON + ("collection_key", "collection", "year", "terms_url", "origin_url",
                             "accessed_on", "source_checksum", "crop", "citation",
                             "applies_to_fields"),
}
REQUIRED[ROLE_CONTEXT] = REQUIRED[ROLE_RELEASE]
#: Fields that may never be a gap: without them a record names nothing.
NEVER_OPEN = frozenset({"source_id", "role", "provider", "dataset", "licence", "open_gaps",
                        "collection_key", "crop", "citation", "notice_template",
                        "applies_to_fields"})
YEARS_PLACEHOLDER = "{years}"

#: Where each release schema keeps the ledgers it was built from.
_V1, _V2, _V3 = "araripe.green.release/1", "araripe.green.release/2", "araripe.green.release/3"


class SourcesRejected(Rejected):
    subject = "green sources"


def _refuse(code: str, detail: str, where: str = "<sources>") -> SourcesRejected:
    return SourcesRejected([Finding(code, detail, where)])


# ── the spec ─────────────────────────────────────────────────────────────────

def _floats(value: Any, where: str) -> list[str]:
    if isinstance(value, float):
        return [where]
    if isinstance(value, Mapping):
        return [w for k, v in value.items() for w in _floats(v, f"{where}/{k}")]
    if isinstance(value, list):
        return [w for i, v in enumerate(value) for w in _floats(v, f"{where}/{i}")]
    return []


def spec_findings(spec: Mapping[str, Any], *, with_context: bool) -> list[Finding]:
    """Everything a **sealed** spec must hold (``select_spec`` already applied).

    Context records are required with a context and refused without one.
    """

    findings: list[Finding] = []

    def bad(code: str, detail: str, where: str = "spec") -> None:
        findings.append(Finding(code, detail, where))

    if spec.get("schema") != SPEC_SCHEMA:
        bad("spec_schema", f"expected {SPEC_SCHEMA}")
    if spec.get("derivation") != DERIVATION:
        bad("spec_derivation", f"this code renders {DERIVATION}, the spec asks for {spec.get('derivation')!r}")
    for where in _floats(spec, "spec"):
        bad("spec_float", "canonical JSON refuses floats; write the value as a string", where)
    sources = spec.get("sources")
    if not isinstance(sources, list) or not sources:
        bad("spec_sources", "a spec lists at least one source")
        return findings

    seen: set[str] = set()
    for index, record in enumerate(sources):
        where = f"spec/sources/{index}"
        role = record.get("role")
        if role not in ROLES:
            bad("source_role", f"role {role!r} is not one of {ROLES}", where)
            continue
        source_id = record.get("source_id")
        if source_id in seen:
            bad("source_repeated", f"{source_id!r} is listed twice", where)
        seen.add(source_id)
        gaps = record.get("open_gaps")
        if not isinstance(gaps, list) or not all(isinstance(g, str) and ": " in g for g in gaps):
            bad("open_gaps_malformed", "open_gaps is a list of '<field>: <reason>' strings", where)
            gaps = []
        gap_fields = {g.split(": ", 1)[0] for g in gaps}
        for name in REQUIRED[role]:
            if name not in record:
                bad("field_missing", f"{name} is required for a {role} source", f"{where}/{name}")
            elif record[name] is None and name not in gap_fields:
                bad("silent_gap", f"{name} is null and open_gaps does not say why (register §6.4)", f"{where}/{name}")
            elif record[name] is None and name in NEVER_OPEN:
                bad("gap_not_allowed", f"{name} cannot be an open gap", f"{where}/{name}")
        for name in sorted(gap_fields):
            if name not in REQUIRED[role]:
                bad("gap_unknown_field", f"open_gaps names {name}, which a {role} source does not have", where)
            elif record.get(name) is not None:
                bad("gap_stale", f"open_gaps names {name}, which now has a value", where)
        licence = record.get("licence")
        if not isinstance(licence, Mapping) or not licence.get("name") or not licence.get("url"):
            bad("licence_incomplete", "a licence names itself and links to its text", f"{where}/licence")
        if role == ROLE_DETECTION:
            template = record.get("notice_template")
            if not isinstance(template, str) or template.count(YEARS_PLACEHOLDER) != 1:
                bad("notice_template", f"the notice carries {YEARS_PLACEHOLDER} exactly once", where)
            years = record.get("baseline_years")
            if not isinstance(years, list) or not all(isinstance(y, int) and not isinstance(y, bool) for y in years):
                bad("baseline_years", "baseline_years is a list of integers", where)

    by_role: dict[str, list[Mapping[str, Any]]] = {role: [] for role in ROLES}
    for record in sources:
        if record.get("role") in by_role:
            by_role[record["role"]].append(record)
    if len(by_role[ROLE_DETECTION]) != 1:
        bad("detection_count", "a spec names exactly one detection source")
    for role in (ROLE_RELEASE, ROLE_CONTEXT):
        keys = sorted(str(r.get("collection_key")) for r in by_role[role])
        want = sorted(COLLECTION_KEYS) if (role == ROLE_RELEASE or with_context) else []
        if keys != want:
            bad("collection_keys", f"{role} sources must be {want}, got {keys}")
    return findings


def select_spec(spec: Mapping[str, Any], *, with_context: bool) -> dict:
    """The spec a document seals: context records only when it covers a context.

    A document for a release without a live context must not carry the 2025
    attribution — it would credit a layer nobody is served.
    """

    out = dict(spec)
    out["sources"] = [
        dict(record) for record in spec["sources"]
        if with_context or record.get("role") != ROLE_CONTEXT
    ]
    return out


# ── identity ─────────────────────────────────────────────────────────────────

def sources_identity(release_id: str, context_id: str | None, spec: Mapping[str, Any]) -> tuple[str, str]:
    """``(sources_id, spec_sha256)``.  No context is the empty component."""

    spec_sha256 = canonical_sha256(dict(spec))
    digest = identity_sha256(SOURCES_IDENTITY_DOMAIN, release_id, context_id or "", spec_sha256)
    return SOURCES_ID_PREFIX + digest, spec_sha256


def sources_prefix(sources_id: str) -> str:
    if not SOURCES_ID.match(sources_id):
        raise _refuse("sources_id_malformed", f"{sources_id!r} is not a sources id")
    return f"{SOURCES_ROOT}{sources_id}/"


# ── what the release and its ledgers determine ───────────────────────────────

def release_ledgers(release: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``(ledger_id, document_sha256)`` of every ledger a release was built from, in order."""

    schema = release.get("schema")
    if schema == _V1:
        blocks = [release["ledger"]]
    elif schema == _V2:
        blocks = release["ledgers"]["chain"]
    elif schema == _V3:
        blocks = release["members"]
    else:
        raise _refuse("release_schema", f"no rule for the ledgers of a {schema!r} release")
    return [(block["ledger_id"], block["document_sha256"]) for block in blocks]


def observation_years(release: Mapping[str, Any]) -> list[int]:
    """The years of the dates whose data entered the release.

    A date with no usable acquisition contributed no Sentinel data, so it does
    not add a year to the notice.
    """

    return sorted({
        int(entry["observed_on"][:4])
        for entry in release["dates"]
        if entry.get("usable_acquisition_count", 0) > 0
    })


def collection_ids(ledgers: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every ``collection_id`` the ledgers' expected acquisitions were read from."""

    return sorted({item["collection_id"] for ledger in ledgers for item in ledger["expected_acquisitions"]})


def years_text(years: Iterable[int]) -> str:
    ordered = sorted(set(years))
    if not ordered:
        raise _refuse("no_years", "a Copernicus notice needs at least one year of data")
    return str(ordered[0]) if ordered[0] == ordered[-1] else f"{ordered[0]}–{ordered[-1]}"


def _context_bindings(context: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {raster["collection_key"]: raster for raster in context["spec"]["rasters"]}


def context_findings(spec: Mapping[str, Any], context: Mapping[str, Any]) -> list[Finding]:
    """The 2025 records must name exactly what the context's recipe used."""

    findings = []
    rasters = _context_bindings(context)
    for index, record in enumerate(spec["sources"]):
        if record.get("role") != ROLE_CONTEXT:
            continue
        raster = rasters.get(record["collection_key"])
        where = f"spec/sources/{index}"
        if raster is None:
            findings.append(Finding("context_collection_missing", f"the context has no {record['collection_key']}", where))
            continue
        checksum = record.get("source_checksum") or {}
        pairs = (
            ("collection", record.get("collection"), raster["collection"]),
            ("year", record.get("year"), raster["year"]),
            ("origin_url", record.get("origin_url"), raster["origin_url"]),
            ("crop.sha256", (record.get("crop") or {}).get("sha256"), raster["crop_sha256"]),
            ("source_checksum.md5", checksum.get("md5"), raster["source_md5"]),
        )
        for name, ours, theirs in pairs:
            if ours != theirs:
                findings.append(Finding(
                    "context_binding",
                    f"{name} is {ours!r} here and {theirs!r} in the context's recipe",
                    f"{where}/{name}",
                ))
    return findings


def ledger_findings(release: Mapping[str, Any], ledgers: Sequence[Mapping[str, Any]],
                    acceptances: Sequence[Any], spec: Mapping[str, Any]) -> list[Finding]:
    """The ledgers are the release's, and they read only the declared collection."""

    findings = []
    offered = [(a.ledger_id, a.document_sha256) for a in acceptances]
    if offered != release_ledgers(release):
        findings.append(Finding(
            "ledgers_mismatch",
            "the ledgers offered are not, in order, the ones the release was built from",
            "ledgers",
        ))
    declared = [r["dataset"] for r in spec["sources"] if r.get("role") == ROLE_DETECTION]
    read = collection_ids(ledgers)
    if read != declared:
        findings.append(Finding(
            "detection_collection",
            f"the ledgers read {read}; the detection source declares {declared}",
            "derived/detection",
        ))
    return findings


# ── the document ─────────────────────────────────────────────────────────────

def _attribution(spec: Mapping[str, Any], years: str) -> list[dict]:
    lines = []
    for record in spec["sources"]:
        if record["role"] == ROLE_DETECTION:
            text = record["notice_template"].replace(YEARS_PLACEHOLDER, years)
            applies_to = "release"
        else:
            text = record["citation"]
            applies_to = "release" if record["role"] == ROLE_RELEASE else "context"
        lines.append({
            "source_id": record["source_id"],
            "applies_to": applies_to,
            "text": text,
            "licence": dict(record["licence"]),
            "modified": True,
        })
    return lines


def derive(release: Mapping[str, Any], context: Mapping[str, Any] | None,
           spec: Mapping[str, Any], ledgers: Sequence[Mapping[str, Any]]) -> dict:
    """The document the inputs determine.  Pure; the builder and the gate share it."""

    sealed = select_spec(spec, with_context=context is not None)
    context_id = None if context is None else context["context_id"]
    sources_id, spec_sha256 = sources_identity(release["release_id"], context_id, sealed)
    detection = next(r for r in sealed["sources"] if r["role"] == ROLE_DETECTION)
    observed = observation_years(release)
    years = years_text(list(detection["baseline_years"]) + observed)
    return {
        "schema": SOURCES_SCHEMA,
        "sources_id": sources_id,
        "sources_prefix": sources_prefix(sources_id),
        "release_id": release["release_id"],
        "context_id": context_id,
        "spec": sealed,
        "spec_sha256": spec_sha256,
        "derived": {
            "detection": {
                "collection_ids": collection_ids(ledgers),
                "observation_years": observed,
                "baseline_years": sorted(detection["baseline_years"]),
                "notice_years": years,
            },
            "release_coverage": {
                "first_observed_on": release["coverage"]["first_observed_on"],
                "last_observed_on": release["coverage"]["last_observed_on"],
            },
        },
        "attribution": _attribution(sealed, years),
    }


def _all_findings(release, context, spec, ledgers) -> list[Finding]:
    sealed = select_spec(spec, with_context=context is not None)
    findings = spec_findings(sealed, with_context=context is not None)
    if findings:
        return findings
    if context is not None:
        if context.get("release_id") != release.get("release_id"):
            findings.append(Finding("context_not_of_release",
                                    f"the context describes {context.get('release_id')}", "context"))
        findings += context_findings(sealed, context)
    acceptances = [check_processing_ledger(ledger) for ledger in ledgers]
    findings += ledger_findings(release, ledgers, acceptances, sealed)
    return findings


def build_sources(release: Mapping[str, Any], context: Mapping[str, Any] | None,
                  spec: Mapping[str, Any], ledgers: Sequence[Mapping[str, Any]]) -> dict:
    """The sources document of ``release`` (and ``context``), or a refusal naming every finding."""

    findings = _all_findings(release, context, spec, ledgers)
    if findings:
        raise SourcesRejected(findings)
    return derive(release, context, spec, ledgers)


def check_sources(document: Any, release: Mapping[str, Any], context: Mapping[str, Any] | None,
                  ledgers: Sequence[Mapping[str, Any]]) -> dict:
    """Accept a stored sources document, or refuse it.

    The document must be **exactly** what its release, its context and its own
    sealed spec determine — the same rule ``check_reference_release`` applies
    to a version-3 manifest — so nothing in it can be edited by hand.
    """

    if not isinstance(document, dict) or document.get("schema") != SOURCES_SCHEMA:
        raise _refuse("schema", f"expected {SOURCES_SCHEMA}")
    errors = sorted(schema_validator("green-sources-v1").iter_errors(document),
                    key=lambda error: list(error.absolute_path))
    if errors:
        raise SourcesRejected(
            Finding("schema_invalid", e.message, "/".join(str(p) for p in e.absolute_path) or "<root>")
            for e in errors
        )
    findings: list[Finding] = []
    if document["release_id"] != release.get("release_id"):
        findings.append(Finding("release_mismatch",
                                f"the document describes {document['release_id']}", "release_id"))
    named = document["context_id"]
    offered = None if context is None else context.get("context_id")
    if named != offered:
        findings.append(Finding("context_mismatch",
                                f"the document covers context {named!r}, the context offered is {offered!r}",
                                "context_id"))
    if findings:
        raise SourcesRejected(findings)
    findings = _all_findings(release, context, document["spec"], ledgers)
    if findings:
        raise SourcesRejected(findings)
    expected = derive(release, context, document["spec"], ledgers)
    for key in sorted(expected):
        if document.get(key) != expected[key]:
            findings.append(Finding("does_not_derive", f"{key} is not what the inputs determine", key))
    if set(document) != set(expected):
        findings.append(Finding("unexpected_keys", f"{sorted(set(document) - set(expected))}", "<root>"))
    if findings:
        raise SourcesRejected(findings)
    return document


def serialise(document: Mapping[str, Any]) -> bytes:
    """Deterministic bytes: sorted keys, no whitespace, UTF-8 — as the context's."""

    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pointer_document(*, document: Mapping[str, Any], document_sha256: str, sequence: int,
                     written_utc: str, written_by: Mapping[str, Any]) -> dict:
    return {
        "schema": SOURCES_POINTER_SCHEMA,
        "sequence": sequence,
        "sources_id": document["sources_id"],
        "release_id": document["release_id"],
        "context_id": document["context_id"],
        "sources_path": document["sources_prefix"] + SOURCES_DOCUMENT_NAME,
        "sources_document_sha256": document_sha256,
        "written_utc": written_utc,
        "written_by": dict(written_by),
    }
