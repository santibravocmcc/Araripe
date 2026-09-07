"""The immutable green release: its identity, its manifest, and its gate.

Roadmap Package 2B.2, the bullets Package 2B.2A left open:

* *publish all artifacts under an immutable release/staging identity*;
* *validate schemas, checksums, expected dates, state watermark and product
  completeness before green staging-pointer promotion*;
* *represent valid zero-alert dates and stale-object tombstones explicitly*
  (the zero-alert half; tombstones are a relation between two releases and
  therefore live on the pointer — see ``atomic_publish``).

Identity is derived, not minted
-------------------------------
``release_id`` is a pure function of what the ledger already seals: its
``ledger_id``, its run manifest and its ``document_sha256``.  No clock, no run
id, no actor, no counter.  Three properties follow, and the whole immutability
argument rests on them:

1. the same ledger always maps to the same release prefix, so republishing a
   release is a byte-exact no-op rather than a conflict;
2. any change to the ledger — one row, one digest — lands on a *different*
   prefix, so a release can never be rewritten in place;
3. an object write that a conditional precondition somehow failed to guard
   could only ever overwrite byte-identical content, because the bytes are a
   function of the same inputs as the prefix.

Property 3 is why the conditional write in ``conditional_store`` is a second
line of defence rather than the only one.  It is not the whole defence,
though: a ``date_product`` object is computed by the publisher, not by the
ledger, so the same ledger with a different renderer yields the same prefix
and different bytes.  That case is exactly what the conditional write catches.

The manifest carries no publication provenance
----------------------------------------------
No ``built_utc``, no run id, no actor.  Those describe a promotion *event*,
which is the pointer's subject, and putting them here would make the manifest
bytes non-reproducible and destroy property 1 above.  The manifest is
serialized as canonical JSON (``canonical_json``) so its bytes are a function
of its content.

Requiring canonical *file* bytes is legitimate here and was refused for the
ledger, and the difference is who promises what.  The ledger's file bytes come
from the producer, whose example generator writes ``json.dumps(indent=2)``
(``LEDGER_CONTRACT_BINDING_V1.md`` §5, non-requirement 1).  These bytes come
from this module.  A validation may require what its own producer promises.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.publication import ledger_binding
from src.publication.canonical_json import canonical_json_bytes, identity_sha256
from src.publication.findings import Finding, Rejected
from src.publication.ledger_gate import (
    DateAcceptance,
    LedgerAcceptance,
    check_processing_ledger,
)

RELEASE_SCHEMA = "araripe.green.release/1"
POINTER_SCHEMA = "araripe.green.pointer/1"

#: Domain separation for the publication-side identity.  The inputs are the
#: ledger's own seals; the domain string only stops a release identity from
#: ever colliding with an acquisition or ledger identity, which share the
#: contract's ``SHA256_US`` framing.
RELEASE_IDENTITY_DOMAIN = "araripe.green.release/1"
RELEASE_ID_PREFIX = "rel-g1-"

#: Object layout.  ``releases/<id>/`` is write-once; ``pointers/green/current.json``
#: is the single mutable object in the layout.
RELEASES_ROOT = "releases"
LEDGER_PATH = "ledger.json"
MANIFEST_PATH = "release.json"
POINTER_KEY = "pointers/green/current.json"

RELEASE_CONTENT_TYPE = "application/json"
LEDGER_CONTENT_TYPE = "application/json"

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "phase2b" / "schemas"


#: One reason a green release manifest may not be promoted from.  Shares the
#: ledger gate's finding vocabulary via ``findings.Finding``.
ReleaseRejection = Finding


class ReleaseRejected(Rejected):
    """The release manifest is not an acceptable promotion input."""

    subject = "green release"


class ReleaseBuildError(ValueError):
    """The inputs offered to ``build_release`` cannot form a release."""


# ── serialization ────────────────────────────────────────────────────────────

def release_bytes(document: dict[str, Any]) -> bytes:
    """Canonical bytes of a release manifest or pointer, with a newline.

    The trailing newline follows the producer's ``serialize_v3_document`` so
    the two documents are stored the same way and a stored object is a
    well-formed text file.
    """

    return canonical_json_bytes(document) + b"\n"


def ledger_bytes(ledger_document: dict[str, Any]) -> bytes:
    """The ledger as it is stored inside a release.

    Re-encoded canonically rather than copied byte-for-byte on purpose.  The
    producer's digests cover the parsed *structure*, and its runtime writer
    ``serialize_v3_document`` emits exactly these bytes; only the example
    generator pretty-prints.  Re-encoding therefore loses nothing verifiable
    and buys the reproducibility property the release identity depends on: two
    differently formatted files holding the same ledger are the same release
    and produce the same stored bytes.
    """

    return release_bytes(ledger_document)


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@lru_cache(maxsize=None)
def _schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / f"{name}.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - packaging accident
        raise ReleaseBuildError(f"missing publication schema {path}") from exc


def schema_validator(name: str):
    """A validator for one of this package's own schemas.

    ``jsonschema`` is imported lazily and its absence is reported as a missing
    capability, exactly as ``ledger_binding.pinned_validator`` does: an
    environment without it must make the gate refuse, never silently skip
    validation.
    """

    try:
        import jsonschema
    except ModuleNotFoundError as exc:
        raise ReleaseBuildError(
            "jsonschema is required to validate a green release and is not "
            "installed; refusing to publish without schema validation"
        ) from exc
    schema = _schema(name)
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


# ── identity ─────────────────────────────────────────────────────────────────

def release_identity(acceptance: LedgerAcceptance) -> tuple[str, str]:
    """``(release_id, identity_inputs_sha256)`` for an accepted ledger.

    ``document_sha256`` alone would determine the release, since it is a
    digest over the whole ledger body.  The manifest identity and ledger
    identity are joined in as well so that the identity inputs read as what
    they are — this release is *that* run of *that* manifest — rather than as
    an opaque digest of a digest.
    """

    digest = identity_sha256(
        RELEASE_IDENTITY_DOMAIN,
        acceptance.ledger_id,
        acceptance.run_manifest_id,
        acceptance.run_manifest_sha256,
        acceptance.document_sha256,
    )
    return RELEASE_ID_PREFIX + digest, digest


def release_prefix(release_id: str) -> str:
    return f"{RELEASES_ROOT}/{release_id}/"


def object_key(release_id: str, path: str) -> str:
    return release_prefix(release_id) + path


# ── the zero-alert distinction ───────────────────────────────────────────────

@dataclass(frozen=True)
class DateClassification:
    """What a UTC date is, as the contract's own status semantics decide."""

    alert_state: str
    coverage: str
    usable_acquisition_count: int
    unusable_acquisition_count: int


def classify_date(status_counts: dict[str, int]) -> DateClassification:
    """Classify one UTC date from its terminal status counts.

    A total function: every multiset of terminal statuses maps to exactly one
    ``alert_state`` and one ``coverage``.  The two axes are independent and
    neither derives from the other in general, which is the point —

    * ``zero_alerts`` is a *positive* observation of absence.  Collapsing it
      into "no data" would make a clear sky and a cloud bank look alike, and
      the ledger represents ``complete_zero_alerts`` as a first-class terminal
      state precisely so the publication layer does not have to guess.
    * ``coverage`` says whether anything was missed.  A date whose only
      complete acquisition saw nothing while a second was rejected is
      ``zero_alerts`` *and* ``partial`` — it is not the same claim as a fully
      observed quiet day, and the manifest must not say it is.
    """

    semantics = ledger_binding.pinned_status_semantics()
    sealing = semantics["artifact_sealing"]
    bearing = semantics["alert_bearing"]

    usable = sum(count for status, count in status_counts.items() if status in sealing)
    unusable = sum(
        count for status, count in status_counts.items() if status not in sealing
    )
    if any(status_counts.get(status, 0) > 0 for status in bearing):
        alert_state = "alerts"
    elif usable > 0:
        alert_state = "zero_alerts"
    else:
        alert_state = "no_valid_coverage"

    if usable == 0:
        coverage = "none"
    elif unusable == 0:
        coverage = "complete"
    else:
        coverage = "partial"

    return DateClassification(alert_state, coverage, usable, unusable)


# ── building a release ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProductObject:
    """One object offered for publication under the release prefix.

    ``path`` is the logical path inside the prefix; the physical key is the
    prefix plus that path, so the same product in two releases is two objects
    and neither can overwrite the other.
    """

    path: str
    body: bytes
    content_type: str
    observed_on: str
    acquisition_id: str | None = None

    @property
    def kind(self) -> str:
        return "acquisition_artifact" if self.acquisition_id else "date_product"


def _rows_by_acquisition(ledger_document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["acquisition_id"]: row for row in ledger_document["terminal_rows"]}


def _date_entry(
    date: DateAcceptance, paths: Sequence[str], expected_count: int
) -> dict[str, Any]:
    classification = classify_date(date.status_counts)
    return {
        "observed_on": date.observed_on,
        "alert_state": classification.alert_state,
        "coverage": classification.coverage,
        "expected_acquisition_count": expected_count,
        "usable_acquisition_count": classification.usable_acquisition_count,
        "unusable_acquisition_count": classification.unusable_acquisition_count,
        "observation_count": len(date.observation_ids),
        "status_counts": dict(date.status_counts),
        "max_terminal_at": date.max_terminal_at,
        "daily_summary_sha256": date.daily_summary_sha256,
        "paths": list(paths),
    }


def build_release(
    acceptance: LedgerAcceptance,
    ledger_document: dict[str, Any],
    objects: Iterable[ProductObject],
    *,
    persistence_state_sha256: str,
    persistence_state_bytes: int,
) -> dict[str, Any]:
    """Assemble the release manifest for an accepted ledger.

    Raises ``ReleaseBuildError`` when the offered objects cannot form a
    release at all — a duplicate path, an object on a date the ledger does not
    reconcile, or an artifact claimed for an acquisition whose status seals no
    artifact.  Everything the *document* must satisfy is then re-checked
    independently by ``check_green_release``, which is what a promoter runs
    against the stored object rather than against this function's output.
    """

    release_id, identity_digest = release_identity(acceptance)
    offered = list(objects)

    seen: set[str] = set()
    for item in offered:
        if item.path in seen:
            raise ReleaseBuildError(f"duplicate object path {item.path!r}")
        seen.add(item.path)

    dates_by_key = {date.observed_on: date for date in acceptance.dates}
    rows = _rows_by_acquisition(ledger_document)
    sealing = ledger_binding.pinned_status_semantics()["artifact_sealing"]

    paths_by_date: dict[str, list[str]] = {key: [] for key in dates_by_key}
    manifest_objects: list[dict[str, Any]] = []
    for item in sorted(offered, key=lambda entry: entry.path):
        date = dates_by_key.get(item.observed_on)
        if date is None:
            raise ReleaseBuildError(
                f"{item.path!r} claims {item.observed_on}, which the ledger does "
                f"not reconcile (reconciled: {', '.join(sorted(dates_by_key))})"
            )
        provenance: dict[str, Any] = {
            "kind": item.kind,
            "observed_on": item.observed_on,
        }
        if item.acquisition_id is not None:
            row = rows.get(item.acquisition_id)
            if row is None or item.acquisition_id not in date.expected_acquisition_ids:
                raise ReleaseBuildError(
                    f"{item.path!r} claims acquisition {item.acquisition_id}, which "
                    f"is not expected on {item.observed_on}"
                )
            if row["status"] not in sealing:
                raise ReleaseBuildError(
                    f"{item.path!r} claims an artifact for {item.acquisition_id}, "
                    f"whose status {row['status']!r} seals no artifact checksum"
                )
            provenance["acquisition_id"] = item.acquisition_id
        manifest_objects.append(
            {
                "path": item.path,
                "bytes": len(item.body),
                "sha256": sha256_bytes(item.body),
                "content_type": item.content_type,
                "provenance": provenance,
            }
        )
        paths_by_date[item.observed_on].append(item.path)

    stored_ledger = ledger_bytes(ledger_document)
    observed_dates = list(acceptance.observed_dates)
    expected_per_date = {
        date.observed_on: len(date.expected_acquisition_ids)
        for date in acceptance.dates
    }

    return {
        "schema": RELEASE_SCHEMA,
        "release_id": release_id,
        "identity_inputs_sha256": identity_digest,
        "release_prefix": release_prefix(release_id),
        "ledger": {
            "ledger_id": acceptance.ledger_id,
            "run_manifest_id": acceptance.run_manifest_id,
            "run_manifest_sha256": acceptance.run_manifest_sha256,
            "monitoring_extent_id": acceptance.monitoring_extent_id,
            "algorithm_version": acceptance.algorithm_version,
            "contract_version": acceptance.contract_version,
            "document_sha256": acceptance.document_sha256,
            "expected_acquisition_count": acceptance.expected_acquisition_count,
            "path": LEDGER_PATH,
            "bytes": len(stored_ledger),
            "file_sha256": sha256_bytes(stored_ledger),
        },
        "coverage": {
            "observed_dates": observed_dates,
            "first_observed_on": observed_dates[0],
            "last_observed_on": observed_dates[-1],
        },
        "dates": [
            _date_entry(
                date,
                sorted(paths_by_date[date.observed_on]),
                expected_per_date[date.observed_on],
            )
            for date in acceptance.dates
        ],
        "objects": manifest_objects,
        "state_watermark": {
            # Derived from the ledger, never supplied: a caller cannot overclaim
            # how far persistence is finalized.
            "finalized_through": observed_dates[-1],
            "finalized_dates": observed_dates,
            # Provenance only.  This contract makes NO claim about the state's
            # contents.  `max(last_seen)` is not a watermark: `update_tracks`
            # overwrites `last_seen` with the date being processed, and a run
            # re-covering the 16-day window can move it BACKWARDS
            # (tests/test_update_tracks.py::test_last_seen_can_move_backwards).
            # Requiring monotonicity there is the 2026-09-07 outage.
            "persistence_state_sha256": persistence_state_sha256,
            "persistence_state_bytes": persistence_state_bytes,
        },
    }


# ── the release gate: validation before promotion ────────────────────────────

def check_green_release(
    document: Any, ledger_document: Any
) -> tuple[dict[str, Any], LedgerAcceptance]:
    """Accept a release manifest as a promotion input, or reject it.

    The ledger is **required**, and re-validated here through
    ``check_processing_ledger``: "validate schemas, checksums, expected dates,
    state watermark and product completeness before green staging-pointer
    promotion" composes the ledger gate rather than duplicating it, so a
    release can never be promoted without its ledger passing again from the
    bytes actually stored beside it.

    Raises ``ReleaseRejected`` carrying every finding, ``LedgerRejected`` when
    the stored ledger itself is unacceptable, or ``ledger_binding``'s
    ``ContractBindingError`` when the consumed contract cannot be established.

    What this gate owns, and what the schema owns: the schema owns shape —
    field presence, types, the two enums, the logical-path grammar and the
    provenance conditionals.  This gate owns only relations the schema cannot
    express: recomputing the identity, recomputing digests, relating the
    manifest to the ledger's accounting, relating objects to dates and to
    ledger rows, and recomputing the classification.  Both layers read the
    same schema file, so re-checking a shape rule here would be an unreachable
    branch that looks like protection
    (``docs/implementation/PHASE_2B2A_2026-09-07.md`` §4).
    """

    if not isinstance(document, dict):
        raise ReleaseRejected(
            [
                ReleaseRejection(
                    "not_a_release_document",
                    "a green release manifest must be a JSON object, got "
                    f"{type(document).__name__}",
                )
            ]
        )

    declared = document.get("schema")
    if declared != RELEASE_SCHEMA:
        raise ReleaseRejected(
            [
                ReleaseRejection(
                    "release_schema_mismatch",
                    f"this repository publishes {RELEASE_SCHEMA!r}; the document "
                    f"declares {declared!r}. A different version is refused, not "
                    "coerced.",
                    "schema",
                )
            ]
        )

    errors = sorted(
        schema_validator("green-release-v1").iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ReleaseRejected(
            ReleaseRejection(
                "release_schema_invalid",
                error.message,
                "/".join(str(part) for part in error.absolute_path) or "<root>",
            )
            for error in errors
        )

    # The ledger gate runs first and its findings are never merged into ours:
    # an unacceptable ledger is a different failure from an inconsistent
    # manifest, and collapsing them would hide which one an operator must fix.
    acceptance = check_processing_ledger(ledger_document)

    findings: list[Finding] = []
    findings += _check_identity(document, acceptance)
    findings += _check_ledger_block(document, acceptance, ledger_document)
    findings += _check_dates(document, acceptance)
    findings += _check_objects(document, acceptance, ledger_document)
    findings += _check_watermark(document, acceptance)

    if findings:
        raise ReleaseRejected(findings)
    return document, acceptance


def _check_identity(
    document: dict[str, Any], acceptance: LedgerAcceptance
) -> list[Finding]:
    expected_id, expected_digest = release_identity(acceptance)
    findings: list[Finding] = []
    if document["release_id"] != expected_id:
        findings.append(
            ReleaseRejection(
                "release_identity_mismatch",
                "release_id does not recompute from the ledger's identity, run "
                f"manifest and document digest (expected {expected_id})",
                "release_id",
            )
        )
    if document["identity_inputs_sha256"] != expected_digest:
        findings.append(
            ReleaseRejection(
                "release_identity_mismatch",
                "identity_inputs_sha256 does not recompute from the ledger seals",
                "identity_inputs_sha256",
            )
        )
    if document["release_prefix"] != release_prefix(document["release_id"]):
        findings.append(
            ReleaseRejection(
                "release_prefix_mismatch",
                "release_prefix does not address release_id, so objects would be "
                "written outside the identity that makes them immutable",
                "release_prefix",
            )
        )
    return findings


def _check_ledger_block(
    document: dict[str, Any],
    acceptance: LedgerAcceptance,
    ledger_document: dict[str, Any],
) -> list[Finding]:
    block = document["ledger"]
    findings: list[Finding] = []
    sealed = {
        "ledger_id": acceptance.ledger_id,
        "run_manifest_id": acceptance.run_manifest_id,
        "run_manifest_sha256": acceptance.run_manifest_sha256,
        "monitoring_extent_id": acceptance.monitoring_extent_id,
        "algorithm_version": acceptance.algorithm_version,
        "contract_version": acceptance.contract_version,
        "document_sha256": acceptance.document_sha256,
        "expected_acquisition_count": acceptance.expected_acquisition_count,
    }
    for key, value in sealed.items():
        if block[key] != value:
            findings.append(
                ReleaseRejection(
                    "ledger_block_mismatch",
                    f"{key} says {block[key]!r} but the accepted ledger reports "
                    f"{value!r}",
                    f"ledger/{key}",
                )
            )
    stored = ledger_bytes(ledger_document)
    if block["file_sha256"] != sha256_bytes(stored) or block["bytes"] != len(stored):
        findings.append(
            ReleaseRejection(
                "ledger_object_mismatch",
                "the ledger object this release declares is not the canonical "
                "encoding of the ledger it was validated against",
                "ledger/file_sha256",
            )
        )
    return findings


def _check_dates(
    document: dict[str, Any], acceptance: LedgerAcceptance
) -> list[Finding]:
    """Every reconciled date appears exactly once, correctly classified.

    This is the "cannot expose a partial release" clause at the date level: a
    date the ledger reconciled may not be silently missing from the manifest,
    and a date the ledger does not reconcile may not appear in it.
    """

    findings: list[Finding] = []
    entries = document["dates"]
    listed = [entry["observed_on"] for entry in entries]
    expected_dates = list(acceptance.observed_dates)

    if listed != expected_dates:
        missing = sorted(set(expected_dates) - set(listed))
        extra = sorted(set(listed) - set(expected_dates))
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if extra:
            detail.append(f"not reconciled by the ledger: {', '.join(extra)}")
        duplicated = sorted({d for d in listed if listed.count(d) > 1})
        if duplicated:
            detail.append(f"listed more than once: {', '.join(duplicated)}")
        if not detail:
            detail.append(
                f"out of chronological order: {', '.join(listed)} against "
                f"{', '.join(expected_dates)}"
            )
        findings.append(
            ReleaseRejection(
                "release_dates_do_not_cover_the_ledger",
                "; ".join(detail),
                "dates",
            )
        )

    by_date = {date.observed_on: date for date in acceptance.dates}
    for index, entry in enumerate(entries):
        where = f"dates/{index}"
        date = by_date.get(entry["observed_on"])
        if date is None:
            continue
        expected_entry = _date_entry(
            date, entry["paths"], len(date.expected_acquisition_ids)
        )
        for key, value in expected_entry.items():
            if key == "paths":
                continue
            if entry[key] != value:
                findings.append(
                    ReleaseRejection(
                        "date_accounting_mismatch",
                        f"{key} says {entry[key]!r} but the ledger's daily summary "
                        f"for {entry['observed_on']} yields {value!r}",
                        f"{where}/{key}",
                    )
                )
        if entry["alert_state"] == "alerts" and not entry["paths"]:
            findings.append(
                ReleaseRejection(
                    "alert_date_publishes_nothing",
                    f"{entry['observed_on']} reports alerts — the contract "
                    "guarantees at least one observation for that status — but the "
                    "release publishes no object for it, which would serve a date "
                    "that claims alerts and holds none",
                    f"{where}/paths",
                )
            )
    return findings


def _check_objects(
    document: dict[str, Any],
    acceptance: LedgerAcceptance,
    ledger_document: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    objects = document["objects"]
    rows = _rows_by_acquisition(ledger_document)
    sealing = ledger_binding.pinned_status_semantics()["artifact_sealing"]
    by_date = {date.observed_on: date for date in acceptance.dates}

    paths_claimed: dict[str, list[str]] = {}
    for entry in document["dates"]:
        for path in entry["paths"]:
            paths_claimed.setdefault(path, []).append(entry["observed_on"])

    by_path: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(objects):
        where = f"objects/{index}"
        path = item["path"]
        if path in by_path:
            findings.append(
                ReleaseRejection(
                    "duplicate_object_path",
                    f"{path!r} is declared more than once, so one physical key "
                    "would carry two declared checksums",
                    f"{where}/path",
                )
            )
            continue
        by_path[path] = item

        observed_on = item["provenance"]["observed_on"]
        claimants = paths_claimed.get(path, [])
        if claimants != [observed_on]:
            findings.append(
                ReleaseRejection(
                    "object_not_claimed_by_its_date",
                    f"{path!r} declares {observed_on} but the date index claims it "
                    f"under {claimants or 'no date'}",
                    f"{where}/path",
                )
            )
        date = by_date.get(observed_on)
        if date is None:
            findings.append(
                ReleaseRejection(
                    "object_on_an_unreconciled_date",
                    f"{path!r} claims {observed_on}, which the ledger does not "
                    "reconcile",
                    f"{where}/provenance/observed_on",
                )
            )
            continue

        acquisition_id = item["provenance"].get("acquisition_id")
        if acquisition_id is None:
            continue
        row = rows.get(acquisition_id)
        if row is None or acquisition_id not in date.expected_acquisition_ids:
            findings.append(
                ReleaseRejection(
                    "object_acquisition_not_expected",
                    f"{path!r} claims acquisition {acquisition_id}, which is not "
                    f"expected on {observed_on}",
                    f"{where}/provenance/acquisition_id",
                )
            )
            continue
        if row["status"] not in sealing:
            findings.append(
                ReleaseRejection(
                    "object_claims_an_unsealed_artifact",
                    f"{path!r} claims an artifact for {acquisition_id}, whose "
                    f"status {row['status']!r} seals no artifact checksum — for "
                    "the rejection and failure statuses artifact_sha256 is "
                    "unconstrained and must not be read",
                    f"{where}/provenance/acquisition_id",
                )
            )
            continue
        sealed_digest = row["output"]["artifact_sha256"]
        if item["sha256"] != sealed_digest:
            findings.append(
                ReleaseRejection(
                    "artifact_checksum_mismatch",
                    f"{path!r} declares sha256 {item['sha256'][:12]}… but the "
                    f"ledger row for {acquisition_id} seals "
                    f"{str(sealed_digest)[:12]}…",
                    f"{where}/sha256",
                )
            )

    for path, claimants in sorted(paths_claimed.items()):
        if path not in by_path:
            findings.append(
                ReleaseRejection(
                    "date_claims_an_undeclared_object",
                    f"{', '.join(claimants)} lists {path!r}, which no object "
                    "declares, so its checksum and size are unknown and it could "
                    "never be verified after upload",
                    "objects",
                )
            )
    return findings


def _check_watermark(
    document: dict[str, Any], acceptance: LedgerAcceptance
) -> list[Finding]:
    """The state watermark is derived, so it cannot be overclaimed.

    Only the two derived fields are checked.  ``persistence_state_sha256`` and
    ``persistence_state_bytes`` are provenance the caller supplies and this
    layer makes no claim about them: reading the production state is out of
    bounds, and the one property a reader might expect to hold —
    ``max(last_seen)`` moving forward — is not an invariant of
    ``update_tracks`` at all.
    """

    watermark = document["state_watermark"]
    findings: list[Finding] = []
    observed = list(acceptance.observed_dates)
    if watermark["finalized_dates"] != observed:
        findings.append(
            ReleaseRejection(
                "state_watermark_mismatch",
                "finalized_dates is not the ledger's reconciled date set",
                "state_watermark/finalized_dates",
            )
        )
    if watermark["finalized_through"] != observed[-1]:
        findings.append(
            ReleaseRejection(
                "state_watermark_mismatch",
                f"finalized_through says {watermark['finalized_through']} but the "
                f"ledger reconciles through {observed[-1]}",
                "state_watermark/finalized_through",
            )
        )
    return findings
