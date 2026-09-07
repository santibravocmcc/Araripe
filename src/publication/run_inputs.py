"""Read one green run's publication inputs from its immutable run prefix.

Roadmap Package 2B.2, last bullet: *keep operational data publication
automatic without PRs or manual merges.*  Package 2B.2B built the publication
path and left one question open — where the ledger and the artifacts come from
when nobody is typing a command line.

They come from ``runs/<run_id>/`` in ``araripe-v2-staging``, the immutable
per-run prefix ``docs/operations/GREEN_CONCURRENCY_LANES.md`` already reserves
for lane 2, and **not** from git.  That is the whole point of the package: the
blue lane publishes its time-series DB by opening and merging a pull request,
and no green data path may do that.

Why this document is not a second ledger
----------------------------------------
``run.json`` is the operator's command line written down.  It carries exactly
what ``scripts/publish_green_release.py`` takes as ``--ledger``, ``--artifact``,
``--product``, ``--date``, ``--state-sha256`` and ``--state-bytes``, and it
defines no scientific fact: every checksum a publication trusts still comes
from the processing ledger this document points at, and every relation is
re-checked by ``check_processing_ledger`` and ``check_green_release``.  The
briefing's rule — *do not invent a second ledger producer* — is honoured
because nothing here produces a ledger; it locates one.

Intent is declared, never deduced
---------------------------------
``kind`` and ``acquisition_id`` are stated by the run.  A first draft of the
Package 2B.2B CLI matched an object's bytes against the ledger's sealed
checksums and, on no match, quietly relabelled it a ``date_product`` — so a
*tampered artifact* passed validation as a different kind of object
(``docs/implementation/PHASE_2B2B_2026-09-07.md`` §7).

This module takes the rule one step further in the reachable direction.  It
never infers a kind from bytes, and it *refuses* a declaration the bytes
contradict: a ``date_product`` whose body is exactly some acquisition's sealed
artifact for that date is rejected, because either the ``acquisition_id`` was
forgotten or the file is the wrong one, and relabelling resolves neither.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.publication import ledger_binding
from src.publication.findings import Finding, Rejected
from src.publication.conditional_store import ConditionalStore, ObjectStoreError
from src.publication.green_release import (
    ProductObject,
    build_release,
    check_green_release,
    schema_validator,
    sha256_bytes,
)
from src.publication.ledger_gate import check_processing_ledger

#: Contract version of the run input document.
RUN_SCHEMA = "araripe.green.run/1"

#: The lane-2 root.  Every run writes under its own immutable prefix here and
#: nothing is ever rewritten, so a publication reads a fixed set of bytes.
RUNS_ROOT = "runs"

#: Fixed names inside a run prefix, mirroring the release layout so an
#: operator reading either sees the same two words.
RUN_MANIFEST_PATH = "run.json"
LEDGER_PATH = "ledger.json"


class RunRejected(Rejected):
    """The run prefix is not a publishable set of inputs."""

    subject = "green run input"


@dataclass(frozen=True)
class StagedRun:
    """Everything a publication needs, read from one run prefix.

    ``release`` has already passed ``check_green_release``, so a caller that
    only wants to know whether a run is publishable is done here — which is
    what the staging job does with the lane-2 identity, before the lane-3
    identity is exercised at all.
    """

    run_id: str
    document: dict[str, Any]
    ledger_document: dict[str, Any]
    release: dict[str, Any]
    bodies: dict[str, bytes]

    @property
    def release_id(self) -> str:
        return self.release["release_id"]


def validate_run_id(run_id: str) -> str:
    """A run id that addresses exactly one prefix, or a refusal.

    One path segment and nothing else.  A run id carrying ``/`` or ``..``
    would let a dispatch input read another run's prefix — or walk out of
    ``runs/`` entirely — which is the one way an operational input could reach
    an object it was not meant to.
    """

    if not run_id or run_id in {".", ".."}:
        raise RunRejected([Finding("run_id_invalid", "the run id is empty", "run_id")])
    forbidden = [part for part in ("/", "\\", "..", " ") if part in run_id]
    if forbidden:
        raise RunRejected(
            [
                Finding(
                    "run_id_invalid",
                    f"{run_id!r} contains {forbidden[0]!r}; a run id is one path "
                    "segment, so it can address only its own prefix",
                    "run_id",
                )
            ]
        )
    return run_id


def run_prefix(run_id: str) -> str:
    return f"{RUNS_ROOT}/{validate_run_id(run_id)}/"


def run_key(run_id: str, path: str) -> str:
    return run_prefix(run_id) + path


def _read_json(store: ConditionalStore, key: str, code: str) -> dict[str, Any]:
    try:
        stored = store.get(key)
    except ObjectStoreError as exc:
        raise RunRejected([Finding(code + "_unreadable", str(exc), key)]) from exc
    if stored is None:
        raise RunRejected(
            [Finding(code + "_absent", f"{store.bucket}/{key} is absent", key)]
        )
    try:
        document = json.loads(stored.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RunRejected(
            [Finding(code + "_unparseable", f"{key} is not valid JSON: {exc}", key)]
        ) from exc
    if not isinstance(document, dict):
        raise RunRejected(
            [
                Finding(
                    code + "_unparseable",
                    f"{key} is a {type(document).__name__}, expected an object",
                    key,
                )
            ]
        )
    return document


def load_run_manifest(store: ConditionalStore, run_id: str) -> dict[str, Any]:
    """The run document, validated against its schema and its own prefix."""

    validate_run_id(run_id)
    key = run_key(run_id, RUN_MANIFEST_PATH)
    document = _read_json(store, key, "run_manifest")

    findings = [
        Finding(
            "run_manifest_invalid",
            error.message,
            "/".join(str(part) for part in error.absolute_path) or "<root>",
        )
        for error in sorted(
            schema_validator("green-run-v1").iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
    ]
    if findings:
        raise RunRejected(findings)
    if document["run_id"] != run_id:
        raise RunRejected(
            [
                Finding(
                    "run_id_mismatch",
                    f"{key} declares run {document['run_id']!r}, which is not the "
                    "run this prefix addresses; a run document may not claim "
                    "another run's inputs",
                    "run_id",
                )
            ]
        )
    return document


def _sealed_by_date(ledger_document: dict[str, Any]) -> dict[str, set[str]]:
    """``{observed_on: {artifact_sha256, …}}`` for the sealing statuses only.

    The five rejection and failure statuses leave ``artifact_sha256``
    unconstrained (``LEDGER_CONTRACT_BINDING_V1.md`` §5, non-requirement 2), so
    their value is never read — not even to compare against.
    """

    sealing = ledger_binding.pinned_status_semantics()["artifact_sealing"]
    by_date: dict[str, set[str]] = {}
    for row in ledger_document["terminal_rows"]:
        if row["status"] in sealing:
            by_date.setdefault(row["observed_on"], set()).add(
                row["output"]["artifact_sha256"]
            )
    return by_date


def load_run(store: ConditionalStore, run_id: str) -> StagedRun:
    """Read, validate and assemble one run's release, contacting no pointer.

    Every finding is collected before anything is raised.  An operator whose
    run prefix is half-uploaded needs to learn that in one read, not one
    object per dispatch — the rule ``findings.py`` exists for.
    """

    document = load_run_manifest(store, run_id)
    ledger_document = _read_json(store, run_key(run_id, LEDGER_PATH), "run_ledger")

    # The Package 2B.2A gate runs here, on the bytes the run deposited, before
    # a single object body is read.  Its findings stay in their own exception:
    # a rejected ledger is a different failure from a broken run prefix.
    acceptance = check_processing_ledger(ledger_document)

    sealed = _sealed_by_date(ledger_document)
    findings: list[Finding] = []
    bodies: dict[str, bytes] = {}
    objects: list[ProductObject] = []
    seen_paths: set[str] = set()

    for index, item in enumerate(document["objects"]):
        where = f"objects/{index}"
        if item["path"] in seen_paths:
            findings.append(
                Finding(
                    "run_object_duplicated",
                    f"{item['path']!r} is offered more than once; one logical path "
                    "is one object in a release",
                    where,
                )
            )
            continue
        seen_paths.add(item["path"])

        key = run_key(run_id, item["source"])
        try:
            stored = store.get(key)
        except ObjectStoreError as exc:
            findings.append(Finding("run_object_unreadable", str(exc), where))
            continue
        if stored is None:
            findings.append(
                Finding(
                    "run_object_absent",
                    f"{store.bucket}/{key} is declared by {RUN_MANIFEST_PATH} and "
                    "is not in the run prefix",
                    where,
                )
            )
            continue

        body = stored.body
        acquisition_id = item.get("acquisition_id")
        if acquisition_id is None:
            digest = sha256_bytes(body)
            if digest in sealed.get(item["observed_on"], set()):
                findings.append(
                    Finding(
                        "product_is_a_sealed_artifact",
                        f"{item['path']!r} is declared a date_product, but its "
                        f"body hashes to {digest[:12]}… which an acquisition on "
                        f"{item['observed_on']} seals as its artifact. Either the "
                        "acquisition_id was omitted or the file is the wrong one; "
                        "relabelling resolves neither.",
                        where,
                    )
                )
                continue

        bodies[item["path"]] = body
        objects.append(
            ProductObject(
                path=item["path"],
                body=body,
                content_type=item["content_type"],
                observed_on=item["observed_on"],
                acquisition_id=acquisition_id,
            )
        )

    if findings:
        raise RunRejected(findings)

    state = document["persistence_state"]
    release = build_release(
        acceptance,
        ledger_document,
        objects,
        persistence_state_sha256=state["sha256"],
        persistence_state_bytes=state["bytes"],
    )
    check_green_release(release, ledger_document)
    return StagedRun(
        run_id=run_id,
        document=document,
        ledger_document=ledger_document,
        release=release,
        bodies=bodies,
    )


class ReadOnlyStore(ConditionalStore):
    """A store that can read a run prefix and cannot write anything.

    ``load_run`` only ever calls ``get``, so this changes nothing about how it
    behaves — which is the point.  The staging job runs with the *candidate*
    identity, whose lane definition is "immutable per-run prefixes only … no
    deletes, no overwrites, no pointers"
    (``docs/operations/GREEN_CONCURRENCY_LANES.md`` lane 2), and this makes
    that a property of the object it is handed rather than a promise about the
    code path it takes.  A future edit that reaches for a write raises here
    instead of discovering the lane boundary in production.
    """

    def _refuse(self, key: str):
        raise ObjectStoreError(
            f"refusing to write {self.bucket}/{key}: this store was opened to "
            "read a run prefix. Publishing a release and moving the green "
            "pointer belong to the promotion identity, not to this one."
        )

    def put_if_absent(self, key: str, body: bytes, content_type: str):
        self._refuse(key)

    def put_if_match(self, key: str, body: bytes, content_type: str, etag: str):
        self._refuse(key)

    def put_if_pointer_absent(self, key: str, body: bytes, content_type: str):
        self._refuse(key)


def describe(run: StagedRun) -> str:
    """One operator-readable summary of what publishing this run would do."""

    coverage = run.release["coverage"]
    lines = [
        f"run              : {run.run_id}  ({run_prefix(run.run_id)})",
        f"release          : {run.release_id}",
        f"prefix           : {run.release['release_prefix']}",
        f"ledger           : {run.release['ledger']['ledger_id']}",
        "coverage         : "
        f"{coverage['first_observed_on']} … {coverage['last_observed_on']} "
        f"({len(coverage['observed_dates'])} UTC date(s))",
        "state watermark  : finalized through "
        f"{run.release['state_watermark']['finalized_through']}",
        "",
        "dates:",
    ]
    for entry in run.release["dates"]:
        lines.append(
            f"  {entry['observed_on']}  {entry['alert_state']:<18} "
            f"coverage={entry['coverage']:<8} objects={len(entry['paths'])}"
        )
    lines += ["", "objects (write-once, If-None-Match: *):"]
    for item in run.release["objects"]:
        lines.append(
            f"  {item['path']}  {item['bytes']} bytes  {item['sha256'][:12]}…  "
            f"{item['provenance']['kind']}"
        )
    return "\n".join(lines)
