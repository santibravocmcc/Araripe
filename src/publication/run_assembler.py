"""Assemble one green run prefix from a detection run's outputs.

Exit gate P2B.  The gap has been named since Package 2B.2C: *"nenhum produtor
deposita ``runs/<run-id>/``"*.  The publication path knows how to read a run
prefix (``run_inputs``), publish it, verify it and move the pointer — and the
prefix was assembled by hand for the 2026-09-07 proofs, by a scaffold that
deliberately lived outside the repository.  This module is that scaffold's
replacement, inside the repository, with the requirements the contracts impose.

What it does NOT do, and the boundary is load-bearing
-----------------------------------------------------
**It does not write a ledger.**  ``PACKAGE_2B_GATE_PROMPT.md`` §4: *"O montador
da rodada usa o ledger que a detecção produz; ele não escreve um."*  The ledger
is an input here, and every checksum, date and terminal status a publication
trusts still comes from it.  The 2B.2A gate (``check_processing_ledger``) runs
on it before a single object is composed, so a run built on a ledger that would
be rejected never gets assembled at all.

**It does not decide what a strong alert is.**  ``site_artifact.strong_features``
is the authority, and this module calls it.  Reimplementing the predicate is the
defect Package 2B.4B found by fixture: ``is_strong`` reads *properties* while
``run_statistics`` counts only *areal* features, so filtering on properties
alone publishes an object with more features than the number displayed beside
it.  A second implementation would be a second chance to make exactly that
mistake.

Which dates get objects, measured from the consumer
---------------------------------------------------
Not chosen here — read from ``site/scripts/site_artifact.py:444``, which skips
``no_valid_coverage`` and then requires exactly one full and one strong object
for every remaining date:

* ``alerts`` and ``zero_alerts`` → **one full + one strong object**;
* ``no_valid_coverage`` → **no objects at all**.  Nothing was observed; the page
  lists runs, and a date without coverage was not a run.

A ``zero_alerts`` date therefore publishes two *empty* collections, and that is
the honest encoding rather than an omission: the release contract §5 calls it *a
positive observation of absence*, and a date that published nothing would be
indistinguishable from one nobody looked at.

Determinism
-----------
The release prefix is a function of the ledger alone, so two assemblies of the
same ledger land on the same prefix — and ``If-None-Match: *`` then compares
*bytes*.  Assembling the same inputs twice must therefore produce byte-identical
objects, or the second publication of a run fails closed as an
``ImmutableObjectConflict``.  Every document here is serialised canonically, and
``test_assembling_twice_is_byte_identical`` pins it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.publication import site_artifact
from src.publication.findings import Finding, Rejected
from src.publication.green_release import (
    LEDGER_PATH,
    classify_date,
    release_bytes,
    sha256_bytes,
)
from src.publication.ledger_gate import LedgerAcceptance, check_processing_ledger
from src.publication.run_inputs import RUN_MANIFEST_PATH, RUN_SCHEMA, validate_run_id

#: Where per-date alert objects live inside a release.  A prefix and not a full
#: path, because the site contract requires only a *suffix* — it deliberately
#: leaves the prefix to this producer.
ALERTS_PREFIX = "alerts"

#: The two suffixes the site composer classifies by.  Imported rather than
#: retyped: the order of its two tests is load-bearing, and a copy here could
#: drift from the string the consumer actually matches.
FULL_SUFFIX = site_artifact.FULL_OBJECT_SUFFIX
STRONG_SUFFIX = site_artifact.STRONG_OBJECT_SUFFIX

GEOJSON_CONTENT_TYPE = "application/geo+json"

#: The alert states that publish objects, measured from the consumer.
PUBLISHING_STATES = ("alerts", "zero_alerts")
#: The state that publishes none.
UNOBSERVED_STATE = "no_valid_coverage"


class RunAssemblyRejected(Rejected):
    """The inputs are not an assemblable run."""

    subject = "green run assembly"


@dataclass(frozen=True)
class AssembledRun:
    """One run prefix, in memory: the documents and every object body.

    ``bodies`` is keyed by the path *inside the run prefix*, so uploading is a
    loop over it with ``runs/<run_id>/`` prepended and nothing else to decide.
    """

    run_id: str
    document: dict[str, Any]
    bodies: dict[str, bytes]
    acceptance: LedgerAcceptance

    @property
    def prefix(self) -> str:
        return f"runs/{self.run_id}/"

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.prefix + path for path in self.bodies))


def full_object_path(observed_on: str) -> str:
    return f"{ALERTS_PREFIX}/run-{observed_on}{FULL_SUFFIX}"


def strong_object_path(observed_on: str) -> str:
    return f"{ALERTS_PREFIX}/run-{observed_on}{STRONG_SUFFIX}"


def feature_collection(features: Sequence[Mapping[str, Any]]) -> bytes:
    """A GeoJSON FeatureCollection, serialised deterministically.

    **Not** with ``release_bytes``, and the reason is a refusal worth reading:
    ``canonical_json`` rejects floating-point values on purpose —

        *"this canonicalizer refuses floating-point values: RFC 8785 number
        formatting is not reproduced here and the v3 ledger has no
        floating-point field, so a float means the document is not a
        processing-ledger-v3"*

    — and a GeoJSON alert is nothing but floats: coordinates, ``nat10``,
    ``area_ha``.  So the release layout's serialiser is the wrong tool here, and
    it says so rather than producing bytes it cannot promise are reproducible.
    Reaching for it was this module's first draft, and the refusal caught it.

    What an alert object actually needs is **determinism**, not
    cross-implementation canonicality: the same features must give the same
    bytes, so republishing a run is a byte-exact no-op instead of an
    ``ImmutableObjectConflict``.  Sorted keys and fixed separators give that.

    The honest limit: this is deterministic for a given input on CPython, whose
    ``repr`` of a float is the shortest round-tripping form since 3.1.  It is
    **not** a canonical form across languages, and nothing here claims it is —
    no digest in any contract is taken over these bytes except the release
    manifest's own ``sha256``, which is computed from exactly what was written.
    """

    document = {"type": "FeatureCollection", "features": list(features)}
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def dates_by_state(acceptance: LedgerAcceptance) -> dict[str, str]:
    """``{observed_on: alert_state}`` for every reconciled date.

    Read from the acceptance the 2B.2A gate produced, never from the ledger
    document directly: the gate is what establishes that every manifest-bound
    acquisition is terminal and the daily summary reconciles its rows, and a
    date it did not accept is not a date.

    ``classify_date`` is the release layer's own function, so the run assembler
    and the release manifest cannot disagree about what a date *is*.  They are
    built from the same ledger minutes apart, and disagreeing would mean the run
    declares objects for a date the release calls unobserved.
    """

    return {
        entry.observed_on: classify_date(entry.status_counts).alert_state
        for entry in acceptance.dates
    }


def assemble_run(
    run_id: str,
    ledger_document: Mapping[str, Any],
    features_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    persistence_state_sha256: str,
    persistence_state_bytes: int,
) -> AssembledRun:
    """Build one run prefix, or refuse.

    ``features_by_date`` holds the alert features for each UTC date, as the
    backend's detection writes them.  It is the only *scientific* input, and it
    is never trusted to say which dates exist: the ledger says that, and a date
    in one and not the other is a refusal rather than a merge.

    Every finding is collected before anything is raised — an operator whose
    detection output is half-there needs to learn that in one run, not one date
    per attempt (``findings.py``).
    """

    validate_run_id(run_id)

    # The Package 2B.2A gate first, on the producer's own bytes, before a single
    # object is composed. A ledger that would be rejected at publication time
    # must be rejected here, where the run does not exist yet and nothing has
    # been uploaded.
    acceptance = check_processing_ledger(ledger_document)
    states = dates_by_state(acceptance)

    findings: list[Finding] = []

    unknown = sorted(set(features_by_date) - set(states))
    for date in unknown:
        findings.append(
            Finding(
                "features_for_an_unreconciled_date",
                f"features were supplied for {date}, which the ledger does not "
                "reconcile. The ledger decides which dates exist; a date only "
                "the detection output knows about is a mismatch, not a date.",
                f"features_by_date/{date}",
            )
        )

    objects: list[dict[str, Any]] = []
    bodies: dict[str, bytes] = {}

    for observed_on in sorted(states):
        state = states[observed_on]
        supplied = features_by_date.get(observed_on)

        if state == UNOBSERVED_STATE:
            # Nothing was observed. Publishing an empty collection here would
            # claim a run happened, and the consumer skips these dates anyway.
            if supplied:
                findings.append(
                    Finding(
                        "features_for_an_unobserved_date",
                        f"{observed_on} is {UNOBSERVED_STATE} — nothing was "
                        f"observed — and {len(supplied)} feature(s) were "
                        "supplied for it. A date with no coverage cannot have "
                        "alerts; one of the two inputs is wrong.",
                        f"features_by_date/{observed_on}",
                    )
                )
            continue

        if state not in PUBLISHING_STATES:  # pragma: no cover - total function
            findings.append(
                Finding(
                    "unknown_alert_state",
                    f"{observed_on} classifies as {state!r}, which this "
                    "assembler has no rule for",
                    f"dates/{observed_on}",
                )
            )
            continue

        if supplied is None:
            findings.append(
                Finding(
                    "date_without_detection_output",
                    f"the ledger reconciles {observed_on} as {state!r}, so the "
                    "release must publish one full and one strong object for "
                    "it, and no features were supplied. A zero-alert date is "
                    "an empty list, not a missing key — the difference is "
                    "whether anyone looked.",
                    f"features_by_date/{observed_on}",
                )
            )
            continue

        if state == "alerts" and not supplied:
            findings.append(
                Finding(
                    "alerting_date_without_features",
                    f"the ledger reconciles {observed_on} as 'alerts', which "
                    "means at least one acquisition reported observations, and "
                    "no features were supplied. The release contract requires "
                    "such a date to publish at least one object with content.",
                    f"features_by_date/{observed_on}",
                )
            )
            continue

        # The strong subset is the authority's, not ours. Both conditions:
        # property AND areal geometry.
        strong = site_artifact.strong_features(supplied)

        for path, features in (
            (full_object_path(observed_on), supplied),
            (strong_object_path(observed_on), strong),
        ):
            bodies[path] = feature_collection(features)
            objects.append(
                {
                    "path": path,
                    "source": path,
                    "kind": "date_product",
                    "observed_on": observed_on,
                    "content_type": GEOJSON_CONTENT_TYPE,
                }
            )

    if findings:
        raise RunAssemblyRejected(findings)

    document = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "ledger": LEDGER_PATH,
        "persistence_state": {
            "sha256": persistence_state_sha256,
            "bytes": persistence_state_bytes,
        },
        "objects": objects,
    }

    # The ledger travels as the producer wrote it, not canonicalised: the
    # binding's non-requirement 4 says a ledger file need not be canonical on
    # arrival, and re-encoding it here would make this module the author of
    # bytes whose digests the producer sealed. `indent=2` matches the producer's
    # own example generator (LEDGER_CONTRACT_BINDING_V1.md §5).
    bodies[LEDGER_PATH] = (
        json.dumps(ledger_document, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    bodies[RUN_MANIFEST_PATH] = release_bytes(document)

    return AssembledRun(
        run_id=run_id,
        document=document,
        bodies=bodies,
        acceptance=acceptance,
    )


def describe(run: AssembledRun) -> str:
    """One operator-readable summary of what would be uploaded."""

    dates: dict[str, list[str]] = {}
    for item in run.document["objects"]:
        dates.setdefault(item["observed_on"], []).append(item["path"])

    lines = [
        f"run        : {run.run_id}  ({run.prefix})",
        f"ledger     : {run.acceptance.ledger_id}",
        f"dates      : {len(dates)} publishing, "
        f"{len(run.acceptance.dates)} reconciled",
        f"objects    : {len(run.document['objects'])}",
        "",
    ]
    for observed_on in sorted(dates):
        full, strong = site_artifact.classify_run_objects(dates[observed_on])
        lines.append(f"  {observed_on}")
        for path in (full, strong):
            body = run.bodies[path]
            features = len(json.loads(body)["features"])
            lines.append(
                f"    {path}  {len(body)} bytes  {features} feature(s)  "
                f"{sha256_bytes(body)[:12]}…"
            )
    lines += ["", f"total bytes : {sum(len(b) for b in run.bodies.values())}"]
    return "\n".join(lines)


def upload(store: Any, run: AssembledRun) -> list[str]:
    """Write every body under the run prefix, write-once.

    ``put_if_absent`` throughout: a run prefix is immutable, so re-uploading
    the same assembly is an idempotent no-op and re-uploading *different* bytes
    under the same run id fails closed rather than silently replacing the
    inputs a release was built from.

    The manifest goes **last**, mirroring the release layout: a partially
    uploaded run has no ``run.json``, and ``load_run`` refuses a prefix whose
    manifest is absent instead of publishing half a run.
    """

    written: list[str] = []
    ordered = [path for path in sorted(run.bodies) if path != RUN_MANIFEST_PATH]
    ordered.append(RUN_MANIFEST_PATH)
    for path in ordered:
        content_type = (
            "application/json"
            if path in (RUN_MANIFEST_PATH, LEDGER_PATH)
            else GEOJSON_CONTENT_TYPE
        )
        outcome = store.put_if_absent(run.prefix + path, run.bodies[path], content_type)
        written.append(f"{outcome.result} {run.prefix}{path}")
    return written
