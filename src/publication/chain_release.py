"""The public release of a state chain: every run from its root to its head.

``docs/implementation/PHASE_6I_2026-09-28.md`` is the decision this module
implements, and each rule below cites the section that argues it.

Why a chain needs its own release (§0, §2)
------------------------------------------
A version-1 release is a function of **one** processing ledger
(``GREEN_RELEASE_CONTRACT_V1.md`` §2), and a chained run's ledger accounts only
for its own window.  Promoting the head's release would publish one day and
retire eight months.  A **version-2** release is composed of the version-1
releases its runs would mint — root first — so it covers every date the chain
covers, under one identity, one pointer and one citation.

Composed, not re-derived
------------------------
``build_chain_release`` takes each member's version-1 release and ledger, runs
``check_green_release`` on every one of them, and only then concatenates.  So a
member of a version-2 release is exactly what that run would publish alone,
and each member stays checkable on its own: ``ledgers.chain`` carries the
digest of each ledger's own canonical encoding, the ``ledger.json`` its
version-1 release would store.

The layout is version 1's, on purpose (§2, *Por que copiar*)
-------------------------------------------------------------
``release.json``, ``ledger.json`` and the declared objects, all under the
release's own prefix.  The objects of every member are **copied** there.  That
is what keeps the green route (``site/worker/data_route.js``: key = live
``release_prefix`` + declared path), the site composer, the remote verifier
(which requires ``/data/green/ledger.json``), the exposure policy and the
retention planner working with no change at all.  ``ledger.json`` holds every
member ledger in one ``araripe.green.ledger-chain/1`` document.

What must hold across members (§2)
----------------------------------
* their dates do not touch and are in chain order — promised by
  ``state_chain.check_window``, which refuses any window that does not start
  the day after the predecessor's last date (PHASE_6G §4);
* one generation: the same extent, algorithm and ledger contract — a new
  generation is a new root (PHASE_6H §1).

What this module never does
---------------------------
Read or write a pointer, read the persistence state, or change what
``green_release.RELEASE_SCHEMA`` means.  The Phase 3 freeze pins that constant
and ``replay_2026.py`` refuses to detect when it drifts (§4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.publication.canonical_json import identity_sha256
from src.publication.conditional_store import ConditionalStore
from src.publication.findings import Finding
from src.publication.green_release import (
    LEDGER_PATH,
    RELEASE_SCHEMA,
    RELEASES_ROOT,
    ReleaseBuildError,
    ReleaseRejected,
    ReleaseRejection,
    _check_dates,
    _check_objects,
    check_green_release,
    ledger_bytes,
    schema_validator,
    sha256_bytes,
)
from src.publication.ledger_gate import LedgerAcceptance, check_processing_ledger

CHAIN_RELEASE_SCHEMA = "araripe.green.release/2"
CHAIN_RELEASE_IDENTITY_DOMAIN = "araripe.green.release/2"
CHAIN_RELEASE_ID_PREFIX = "rel-g2-"
LEDGER_CHAIN_SCHEMA = "araripe.green.ledger-chain/1"

#: The sealed fields of a member ledger, exactly the version-1 ``ledger`` block
#: without its ``path`` — the path of a member is not a file of this release.
_SEALED = (
    "ledger_id",
    "run_manifest_id",
    "run_manifest_sha256",
    "monitoring_extent_id",
    "algorithm_version",
    "contract_version",
    "document_sha256",
    "expected_acquisition_count",
)

#: What one generation means for a chain (PHASE_6H §1): these may not vary.
_GENERATION = ("monitoring_extent_id", "algorithm_version", "contract_version")


@dataclass(frozen=True)
class ChainMember:
    """One run of the chain: the version-1 release it would mint, and its ledger."""

    release: dict[str, Any]
    ledger_document: dict[str, Any]


# ── identity and the ledger file ─────────────────────────────────────────────

def chain_release_identity(acceptances: Sequence[LedgerAcceptance]) -> tuple[str, str]:
    """``(release_id, identity_inputs_sha256)`` for the ledgers of a chain, in order.

    The four inputs per member are version 1's, in version 1's order.  The
    unit separator of ``SHA256_US`` already makes the sequence unambiguous —
    every member contributes exactly four components — so the member count is
    not an input.  No run id: two chains whose ledgers are the same are the
    same release (§2).
    """

    components: list[str] = [CHAIN_RELEASE_IDENTITY_DOMAIN]
    for acceptance in acceptances:
        components += [
            acceptance.ledger_id,
            acceptance.run_manifest_id,
            acceptance.run_manifest_sha256,
            acceptance.document_sha256,
        ]
    digest = identity_sha256(*components)
    return CHAIN_RELEASE_ID_PREFIX + digest, digest


def chain_release_prefix(release_id: str) -> str:
    return f"{RELEASES_ROOT}/{release_id}/"


def ledger_chain_document(ledger_documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The ``ledger.json`` of a chain release: every member ledger, root first."""

    return {
        "schema": LEDGER_CHAIN_SCHEMA,
        "ledgers": [dict(document) for document in ledger_documents],
    }


# ── building ─────────────────────────────────────────────────────────────────

def _member_block(
    release: Mapping[str, Any], ledger_document: Mapping[str, Any]
) -> dict[str, Any]:
    block = {key: release["ledger"][key] for key in _SEALED}
    own = ledger_bytes(dict(ledger_document))
    block["bytes"] = len(own)
    block["file_sha256"] = sha256_bytes(own)
    block["first_observed_on"] = release["coverage"]["first_observed_on"]
    block["last_observed_on"] = release["coverage"]["last_observed_on"]
    return block


def _chain_order_findings(blocks: Sequence[Mapping[str, Any]]) -> list[Finding]:
    """The two relations between members: order, and one generation."""

    findings: list[Finding] = []
    for index in range(1, len(blocks)):
        before, after = blocks[index - 1], blocks[index]
        if not before["last_observed_on"] < after["first_observed_on"]:
            findings.append(
                ReleaseRejection(
                    "chain_dates_overlap",
                    f"member {index} ({after['ledger_id']}) starts on "
                    f"{after['first_observed_on']}, which is not after "
                    f"{before['last_observed_on']}, the last date of member "
                    f"{index - 1}. Two ledgers accounting for one date have no "
                    "winner; state_chain.check_window refuses such a window, so a "
                    "chain that holds one was not built by this lane.",
                    f"ledgers/chain/{index}/first_observed_on",
                )
            )
        for key in _GENERATION:
            if after[key] != blocks[0][key]:
                findings.append(
                    ReleaseRejection(
                        "chain_mixes_generations",
                        f"member {index} has {key} {after[key]!r} and the root has "
                        f"{blocks[0][key]!r}. A new generation is a new root "
                        "(PHASE_6H §1); a release mixing two would claim one "
                        "homogeneous series.",
                        f"ledgers/chain/{index}/{key}",
                    )
                )
    return findings


def build_chain_release(members: Sequence[ChainMember]) -> dict[str, Any]:
    """Compose the version-2 release of a chain from its members' version-1 releases.

    Every member is revalidated with ``check_green_release`` before anything is
    composed, and the relations between members are checked with the same
    function the gate uses.  ``check_chain_release`` then re-checks the result
    independently; it is what a promoter runs against the stored object.
    """

    if not members:
        raise ReleaseBuildError("a chain release needs at least one member run")

    acceptances: list[LedgerAcceptance] = []
    blocks: list[dict[str, Any]] = []
    for member in members:
        _, acceptance = check_green_release(member.release, member.ledger_document)
        acceptances.append(acceptance)
        blocks.append(_member_block(member.release, member.ledger_document))

    order = _chain_order_findings(blocks)
    if order:
        raise ReleaseBuildError("; ".join(f"{f.code}: {f.detail}" for f in order))

    dates: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for member, acceptance in zip(members, acceptances):
        for entry in member.release["dates"]:
            dates.append({**entry, "ledger_id": acceptance.ledger_id})
        for item in member.release["objects"]:
            if item["path"] in seen:
                raise ReleaseBuildError(
                    f"{item['path']!r} is published by two members; one logical "
                    "path is one object in a release"
                )
            seen.add(item["path"])
            objects.append(dict(item))
    objects.sort(key=lambda item: item["path"])

    observed = [entry["observed_on"] for entry in dates]
    chain_file = ledger_bytes(
        ledger_chain_document([member.ledger_document for member in members])
    )
    release_id, digest = chain_release_identity(acceptances)
    head = members[-1].release["state_watermark"]
    return {
        "schema": CHAIN_RELEASE_SCHEMA,
        "release_id": release_id,
        "identity_inputs_sha256": digest,
        "release_prefix": chain_release_prefix(release_id),
        "ledgers": {
            "path": LEDGER_PATH,
            "bytes": len(chain_file),
            "file_sha256": sha256_bytes(chain_file),
            "chain": blocks,
        },
        "coverage": {
            "observed_dates": observed,
            "first_observed_on": observed[0],
            "last_observed_on": observed[-1],
        },
        "dates": dates,
        "objects": objects,
        "state_watermark": {
            "finalized_through": observed[-1],
            "finalized_dates": observed,
            # The head's: the state the next run continues from.  Provenance
            # only, exactly as in version 1.
            "persistence_state_sha256": head["persistence_state_sha256"],
            "persistence_state_bytes": head["persistence_state_bytes"],
        },
    }


# ── the gate ─────────────────────────────────────────────────────────────────

def _envelope(chain_document: Any) -> list[dict[str, Any]]:
    if not isinstance(chain_document, dict):
        raise ReleaseRejected(
            [
                ReleaseRejection(
                    "ledger_chain_invalid",
                    "the ledger file of a chain release must be a JSON object, got "
                    f"{type(chain_document).__name__}",
                    "ledger.json",
                )
            ]
        )
    errors = sorted(
        schema_validator("green-ledger-chain-v1").iter_errors(chain_document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ReleaseRejected(
            ReleaseRejection(
                "ledger_chain_invalid",
                error.message,
                "ledger.json/" + "/".join(str(p) for p in error.absolute_path),
            )
            for error in errors
        )
    return list(chain_document["ledgers"])


def check_chain_release(
    document: Any, chain_document: Any
) -> tuple[dict[str, Any], tuple[LedgerAcceptance, ...]]:
    """Accept a version-2 release as a promotion input, or reject it.

    The ledgers are **required**, read from the ``ledger.json`` stored beside
    the release, and every one of them passes the Package 2B.2A gate again.
    Then every rule of the version-1 gate is applied member by member — each
    member's slice of ``dates`` and ``objects`` against that member's ledger —
    and the relations between members on top.  Findings are collected, never
    raised one at a time.
    """

    if not isinstance(document, dict) or document.get("schema") != CHAIN_RELEASE_SCHEMA:
        declared = document.get("schema") if isinstance(document, dict) else None
        raise ReleaseRejected(
            [
                ReleaseRejection(
                    "release_schema_mismatch",
                    f"a chain release declares {CHAIN_RELEASE_SCHEMA!r}; the document "
                    f"declares {declared!r}",
                    "schema",
                )
            ]
        )
    errors = sorted(
        schema_validator("green-release-v2").iter_errors(document),
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

    ledgers = _envelope(chain_document)
    # Every ledger passes the 2B.2A gate first, and its findings stay its own.
    acceptances = tuple(check_processing_ledger(ledger) for ledger in ledgers)

    findings: list[Finding] = []
    findings += _check_identity(document, acceptances)
    findings += _check_ledgers_block(document, acceptances, ledgers, chain_document)
    findings += _check_dates_and_objects(document, acceptances, ledgers)
    findings += _check_watermark(document, acceptances)
    if findings:
        raise ReleaseRejected(findings)
    return document, acceptances


def _check_identity(
    document: Mapping[str, Any], acceptances: Sequence[LedgerAcceptance]
) -> list[Finding]:
    expected_id, expected_digest = chain_release_identity(acceptances)
    findings: list[Finding] = []
    if document["release_id"] != expected_id:
        findings.append(
            ReleaseRejection(
                "release_identity_mismatch",
                "release_id does not recompute from the chain's ledgers in order "
                f"(expected {expected_id})",
                "release_id",
            )
        )
    if document["identity_inputs_sha256"] != expected_digest:
        findings.append(
            ReleaseRejection(
                "release_identity_mismatch",
                "identity_inputs_sha256 does not recompute from the chain's ledgers",
                "identity_inputs_sha256",
            )
        )
    if document["release_prefix"] != chain_release_prefix(document["release_id"]):
        findings.append(
            ReleaseRejection(
                "release_prefix_mismatch",
                "release_prefix does not address release_id, so objects would be "
                "written outside the identity that makes them immutable",
                "release_prefix",
            )
        )
    return findings


def _check_ledgers_block(
    document: Mapping[str, Any],
    acceptances: Sequence[LedgerAcceptance],
    ledgers: Sequence[Mapping[str, Any]],
    chain_document: Mapping[str, Any],
) -> list[Finding]:
    block = document["ledgers"]
    findings: list[Finding] = []
    stored = ledger_bytes(dict(chain_document))
    if block["file_sha256"] != sha256_bytes(stored) or block["bytes"] != len(stored):
        findings.append(
            ReleaseRejection(
                "ledger_object_mismatch",
                "the ledger file this release declares is not the canonical "
                "encoding of the ledger chain it was validated against",
                "ledgers/file_sha256",
            )
        )
    chain = block["chain"]
    if len(chain) != len(acceptances):
        findings.append(
            ReleaseRejection(
                "ledger_chain_length_mismatch",
                f"the manifest lists {len(chain)} member(s) and ledger.json holds "
                f"{len(acceptances)}",
                "ledgers/chain",
            )
        )
        return findings

    for index, (entry, acceptance, ledger) in enumerate(zip(chain, acceptances, ledgers)):
        where = f"ledgers/chain/{index}"
        sealed = {key: getattr(acceptance, key) for key in _SEALED}
        for key, value in sealed.items():
            if entry[key] != value:
                findings.append(
                    ReleaseRejection(
                        "ledger_block_mismatch",
                        f"{key} says {entry[key]!r} but member {index}'s ledger "
                        f"reports {value!r}",
                        f"{where}/{key}",
                    )
                )
        own = ledger_bytes(dict(ledger))
        if entry["file_sha256"] != sha256_bytes(own) or entry["bytes"] != len(own):
            findings.append(
                ReleaseRejection(
                    "ledger_object_mismatch",
                    f"member {index}'s digest is not the canonical encoding of its "
                    "own ledger, so it cannot be checked against its run's release",
                    f"{where}/file_sha256",
                )
            )
        dates = acceptance.observed_dates
        if (entry["first_observed_on"], entry["last_observed_on"]) != (dates[0], dates[-1]):
            findings.append(
                ReleaseRejection(
                    "ledger_block_mismatch",
                    f"member {index} says {entry['first_observed_on']} … "
                    f"{entry['last_observed_on']} and its ledger reconciles "
                    f"{dates[0]} … {dates[-1]}",
                    where,
                )
            )
    # The relations are read from the ledgers, not from the manifest's blocks:
    # a manifest cannot talk a chain into order by misreporting its dates.
    measured = [
        {
            **{key: getattr(acceptance, key) for key in _SEALED},
            "first_observed_on": acceptance.observed_dates[0],
            "last_observed_on": acceptance.observed_dates[-1],
        }
        for acceptance in acceptances
    ]
    findings += _chain_order_findings(measured)
    return findings


def _check_dates_and_objects(
    document: Mapping[str, Any],
    acceptances: Sequence[LedgerAcceptance],
    ledgers: Sequence[Mapping[str, Any]],
) -> list[Finding]:
    findings: list[Finding] = []
    entries = document["dates"]
    listed = [entry["observed_on"] for entry in entries]
    expected = [date for acceptance in acceptances for date in acceptance.observed_dates]
    if listed != expected:
        missing = sorted(set(expected) - set(listed))
        extra = sorted(set(listed) - set(expected))
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if extra:
            detail.append(f"reconciled by no member: {', '.join(extra)}")
        if not detail:
            detail.append("not the members' dates in chain order")
        findings.append(
            ReleaseRejection(
                "release_dates_do_not_cover_the_chain", "; ".join(detail), "dates"
            )
        )

    member_of_ledger = {a.ledger_id: i for i, a in enumerate(acceptances)}
    member_of_date = {
        date: i for i, a in enumerate(acceptances) for date in a.observed_dates
    }
    date_slices: list[list[int]] = [[] for _ in acceptances]
    for index, entry in enumerate(entries):
        member = member_of_ledger.get(entry["ledger_id"])
        if member is None or member_of_date.get(entry["observed_on"]) != member:
            findings.append(
                ReleaseRejection(
                    "date_names_the_wrong_ledger",
                    f"{entry['observed_on']} names {entry['ledger_id']}, which is not "
                    "the member ledger that reconciles it",
                    f"dates/{index}/ledger_id",
                )
            )
            continue
        date_slices[member].append(index)

    object_slices: list[list[int]] = [[] for _ in acceptances]
    paths: dict[str, int] = {}
    for index, item in enumerate(document["objects"]):
        if item["path"] in paths:
            findings.append(
                ReleaseRejection(
                    "duplicate_object_path",
                    f"{item['path']!r} is declared more than once, so one physical "
                    "key would carry two declared checksums",
                    f"objects/{index}/path",
                )
            )
            continue
        paths[item["path"]] = index
        member = member_of_date.get(item["provenance"]["observed_on"])
        if member is None:
            findings.append(
                ReleaseRejection(
                    "object_on_an_unreconciled_date",
                    f"{item['path']!r} claims {item['provenance']['observed_on']}, "
                    "which no member ledger reconciles",
                    f"objects/{index}/provenance/observed_on",
                )
            )
            continue
        object_slices[member].append(index)

    # Every version-1 rule, member by member, on that member's slice.
    for member, (acceptance, ledger) in enumerate(zip(acceptances, ledgers)):
        view = {
            "dates": [entries[i] for i in date_slices[member]],
            "objects": [document["objects"][i] for i in object_slices[member]],
        }
        if [e["observed_on"] for e in view["dates"]] == list(acceptance.observed_dates):
            findings += _check_dates(view, acceptance, date_slices[member])
        findings += _check_objects(view, acceptance, dict(ledger), object_slices[member])
    return findings


def _check_watermark(
    document: Mapping[str, Any], acceptances: Sequence[LedgerAcceptance]
) -> list[Finding]:
    watermark = document["state_watermark"]
    observed = [date for acceptance in acceptances for date in acceptance.observed_dates]
    findings: list[Finding] = []
    if watermark["finalized_dates"] != observed:
        findings.append(
            ReleaseRejection(
                "state_watermark_mismatch",
                "finalized_dates is not the members' reconciled dates in order",
                "state_watermark/finalized_dates",
            )
        )
    if watermark["finalized_through"] != observed[-1]:
        findings.append(
            ReleaseRejection(
                "state_watermark_mismatch",
                f"finalized_through says {watermark['finalized_through']} but the "
                f"chain reconciles through {observed[-1]}",
                "state_watermark/finalized_through",
            )
        )
    coverage = document["coverage"]
    if (
        coverage["observed_dates"] != observed
        or coverage["first_observed_on"] != observed[0]
        or coverage["last_observed_on"] != observed[-1]
    ):
        findings.append(
            ReleaseRejection(
                "coverage_mismatch",
                "coverage is not the members' reconciled dates in order",
                "coverage",
            )
        )
    return findings


# ── one gate for both versions ───────────────────────────────────────────────

def check_release(document: Any, ledger_payload: Any):
    """Dispatch on the declared version: the version-1 gate or the chain gate.

    ``ledger_payload`` is what ``ledger.json`` holds for that version — a
    processing ledger, or a ledger chain.  Returns ``(document, acceptances)``
    with ``acceptances`` always a tuple, one per ledger.
    """

    declared = document.get("schema") if isinstance(document, dict) else None
    if declared == CHAIN_RELEASE_SCHEMA:
        return check_chain_release(document, ledger_payload)
    if declared == RELEASE_SCHEMA or not isinstance(document, dict):
        checked, acceptance = check_green_release(document, ledger_payload)
        return checked, (acceptance,)
    raise ReleaseRejected(
        [
            ReleaseRejection(
                "release_schema_mismatch",
                f"this repository publishes {RELEASE_SCHEMA!r} and "
                f"{CHAIN_RELEASE_SCHEMA!r}; the document declares {declared!r}. A "
                "different version is refused, not coerced.",
                "schema",
            )
        ]
    )


def ledger_file(document: Mapping[str, Any]) -> tuple[int, str]:
    """``(bytes, file_sha256)`` of the ``ledger.json`` a release declares."""

    block = document["ledgers"] if document["schema"] == CHAIN_RELEASE_SCHEMA else document["ledger"]
    return block["bytes"], block["file_sha256"]


def ledger_references(document: Mapping[str, Any]) -> list[dict[str, str]]:
    """The ledgers that account for a release, in chain order — the pointer's ``ledgers``."""

    if document["schema"] == CHAIN_RELEASE_SCHEMA:
        blocks = document["ledgers"]["chain"]
    else:
        blocks = [document["ledger"]]
    return [
        {"ledger_id": block["ledger_id"], "run_manifest_id": block["run_manifest_id"]}
        for block in blocks
    ]


# ── reading a chain from the bucket ──────────────────────────────────────────

@dataclass(frozen=True)
class StagedChain:
    """A chain release in memory: the manifest, the ledger chain, every body."""

    path: tuple[str, ...]
    release: dict[str, Any]
    ledger_chain: dict[str, Any]
    bodies: dict[str, bytes]

    @property
    def release_id(self) -> str:
        return self.release["release_id"]


def load_chain(store: ConditionalStore, path: Sequence[str]) -> StagedChain:
    """Read every run of ``path`` from its prefix and compose the chain release.

    ``run_inputs.load_run`` does for each member exactly what the per-run
    publication does — the ledger gate, every object read and checked against
    ``run.json`` — so a member that could not be published alone is not
    published as part of a chain either.
    """

    from src.publication import run_inputs

    members: list[ChainMember] = []
    bodies: dict[str, bytes] = {}
    for run_id in path:
        staged = run_inputs.load_run(store, run_id)
        members.append(ChainMember(staged.release, staged.ledger_document))
        for logical, body in staged.bodies.items():
            if logical in bodies:
                raise ReleaseBuildError(
                    f"{logical!r} is published by two runs of the chain"
                )
            bodies[logical] = body
    release = build_chain_release(members)
    chain = ledger_chain_document([member.ledger_document for member in members])
    check_chain_release(release, chain)
    return StagedChain(tuple(path), release, chain, bodies)


def describe(chain: StagedChain) -> str:
    """One operator-readable summary of what publishing the chain would do."""

    release = chain.release
    coverage = release["coverage"]
    size = sum(item["bytes"] for item in release["objects"])
    lines = [
        f"chain            : {' -> '.join(chain.path)}",
        f"release          : {chain.release_id}",
        f"prefix           : {release['release_prefix']}",
        "coverage         : "
        f"{coverage['first_observed_on']} … {coverage['last_observed_on']} "
        f"({len(coverage['observed_dates'])} UTC date(s))",
        f"objects          : {len(release['objects'])}, {size} bytes, copied into "
        "the release prefix",
        f"ledger.json      : {release['ledgers']['bytes']} bytes, "
        f"{len(release['ledgers']['chain'])} ledger(s)",
        "",
        "members:",
    ]
    for run_id, block in zip(chain.path, release["ledgers"]["chain"]):
        count = sum(1 for e in release["dates"] if e["ledger_id"] == block["ledger_id"])
        lines.append(
            f"  {run_id:<22} {block['ledger_id'][:18]}…  "
            f"{block['first_observed_on']} … {block['last_observed_on']}  "
            f"{count} date(s)"
        )
    return "\n".join(lines)
