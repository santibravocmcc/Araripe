"""Chain one green run's persistence state onto the next.

``docs/implementation/PHASE_6G_2026-09-28.md`` §1-§4 is the decision this
module implements, and each rule below cites the section that argues it.

Where the state lives (§1)
--------------------------
``runs/<run_id>/persistence_state.geojson`` — a fixed name, like
``ledger.json``, bound by the digest and length every ``run.json`` already
declares under ``persistence_state``.  It is **not** listed in ``objects``:
those become the release, and the state is never published.

Stored compressed (PHASE_6J)
----------------------------
From ``araripe.green.run/3`` on, the state is deposited gzip-compressed at
``persistence_state.geojson.gz`` and ``run.json`` names that object under
``persistence_state.stored``, with its own digest and length.  The state
compresses 3.9x (1 021 260 480 -> 259 064 005 bytes, measured on
``ci-36465147834``), and one ~1 GB state per run was the largest share of the
bucket's growth (PHASE_6I §5).  ``persistence_state.sha256`` and ``.bytes``
still describe the **uncompressed** state, so every predecessor link and every
release compares the same object it always did; the older runs, uncompressed
at ``STATE_PATH``, stay readable and are never rewritten.

How a run names its predecessor (§2)
------------------------------------
``araripe.green.run/2`` adds one required field, ``predecessor``: the run whose
state this one started from and that state's sha256, or ``null`` for a run
that started empty.  Declared, never deduced — an absent field would mean both
"started empty" and "somebody forgot".

Which window may follow (§4)
----------------------------
Exactly the day after the last date the predecessor's ledger reconciles.  An
overlap makes two ledgers claim one date or trips ``update_tracks``'s
out-of-order guard; a gap can never be backfilled in this chain, because the
next transition moves the watermark past it.  Both are refused before a byte of
state is downloaded.

Which run is the head, and who refuses a second child (PHASE_6H §1-§3)
-----------------------------------------------------------------------
``docs/implementation/PHASE_6H_2026-09-28.md``.  The head is **derived**, never
stored: the one leaf of the tree the ``predecessor`` fields draw from
``CHAIN_ROOT``.  Two children of one run is a fork, and every read of the
chain refuses it; the deposit refuses to *create* one.  The automatic window
runs from the head's ``next_start`` to the day before today, at most
``WINDOW_MAX_DAYS`` long.

What this module never does
---------------------------
Write anything but the one state object of a run whose ``run.json`` already
declares it, and only with ``put_if_absent``; read or write a pointer; import
``config`` (``tests/test_assemble_green_run.py`` guards the scripts that use it).
"""

from __future__ import annotations

import gzip
import re
import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

from src.publication.conditional_store import ConditionalStore, ObjectStoreError, PutOutcome
from src.publication.findings import Finding, Rejected
from src.publication.green_release import sha256_bytes
from src.publication.ledger_gate import check_processing_ledger
from src.publication.run_inputs import (
    LEDGER_PATH,
    RUN_MANIFEST_PATH,
    RUNS_ROOT,
    _read_json,
    load_run_manifest,
    run_key,
    validate_run_id,
)

#: The state's name inside a run prefix — the producer's own
#: (``scripts/assemble_green_run.py::PERSISTENCE_STATE_NAME``, which copies
#: ``scripts/run_detection.py``).  ``tests/test_state_chain.py`` keeps the two
#: from drifting.
STATE_PATH = "persistence_state.geojson"
STATE_CONTENT_TYPE = "application/geo+json"

#: The compressed state of a version-3 run (PHASE_6J).  ``GZIP_LEVEL`` 6 is
#: gzip's default; level 9 bought 8% more on the measured state for several
#: times the time, and brotli 9% more for a codec the standard library lacks.
STATE_GZIP_PATH = "persistence_state.geojson.gz"
STATE_GZIP_CONTENT_TYPE = "application/gzip"
STATE_GZIP_ENCODING = "gzip"
GZIP_LEVEL = 6

#: The largest body one R2 PUT accepts: "5 GiB (single-part)", footnote "5 MiB
#: less than 5 GiB" — developers.cloudflare.com/r2/platform/limits/, read
#: 2026-09-28.  ``put_if_absent`` is a single PUT.  Refusing here names the
#: reason; letting R2 refuse would name an HTTP status.
MAX_SINGLE_PUT_BYTES = 5 * 1024**3 - 5 * 1024**2

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ChainRejected(Rejected):
    """The predecessor's state cannot start this run."""

    subject = "state chain"


@dataclass(frozen=True)
class Predecessor:
    """What a run needs to know about the run it continues.

    Everything here is read from the predecessor's own prefix: the digest and
    length from its ``run.json``, the last covered date from its ledger after
    the Package 2B.2A gate accepted it.
    """

    run_id: str
    persistence_state_sha256: str
    persistence_state_bytes: int
    last_observed_on: str
    #: ``persistence_state.stored`` of a version-3 run, or ``None`` for the
    #: uncompressed object at ``STATE_PATH``.
    stored: Mapping[str, Any] | None = None
    #: The ``algorithm_version`` its ledger seals — its generation (PHASE_6W).
    algorithm_version: str | None = None

    @property
    def next_start(self) -> str:
        return (date.fromisoformat(self.last_observed_on) + timedelta(days=1)).isoformat()

    def link(self) -> dict[str, str]:
        """The ``predecessor`` field of the successor's ``run.json``."""

        return {
            "run_id": self.run_id,
            "persistence_state_sha256": self.persistence_state_sha256,
        }


def state_key(run_id: str) -> str:
    return run_key(run_id, STATE_PATH)


def compress_state(body: bytes) -> bytes:
    """The deposited form of a state: gzip, with no name and no timestamp.

    ``mtime=0`` keeps the header free of the clock, so compressing the same
    state twice on one machine gives the same bytes.  Nothing depends on
    bytes being equal across zlib builds: the state's identity is the digest
    of the uncompressed bytes, and ``stored.sha256`` only proves the object
    read is the object written.
    """

    return gzip.compress(body, compresslevel=GZIP_LEVEL, mtime=0)


def stored_block(compressed: bytes) -> dict[str, Any]:
    """``persistence_state.stored`` for a compressed state."""

    return {
        "path": STATE_GZIP_PATH,
        "encoding": STATE_GZIP_ENCODING,
        "sha256": sha256_bytes(compressed),
        "bytes": len(compressed),
    }


def _decompress(compressed: bytes, declared: int, key: str) -> bytes:
    """Inflate at most one byte more than ``declared``, or refuse.

    Bounded, so a corrupt or hostile object cannot make the runner allocate
    more than the run.json promised: the extra byte is how an overlong stream
    is told apart from an exact one.
    """

    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        body = inflater.decompress(compressed, declared + 1)
    except zlib.error as exc:
        raise ChainRejected(
            [Finding("predecessor_state_undecodable", f"{key}: {exc}", key)]
        ) from exc
    if len(body) > declared or not inflater.eof or inflater.unused_data:
        raise ChainRejected(
            [
                Finding(
                    "predecessor_state_undecodable",
                    f"{key} does not inflate to exactly one gzip stream of at most "
                    f"{declared} bytes",
                    key,
                )
            ]
        )
    return body


def check_single_put(size: int, where: str) -> None:
    if size > MAX_SINGLE_PUT_BYTES:
        raise ChainRejected(
            [
                Finding(
                    "state_exceeds_single_put",
                    f"the persistence state is {size} bytes and one R2 PUT accepts "
                    f"at most {MAX_SINGLE_PUT_BYTES}. The state keeps confirmed "
                    "tracks forever, so it grows; this is the day to move its "
                    "deposit to a multipart upload, not to trim the state.",
                    where,
                )
            ]
        )


def read_predecessor(store: ConditionalStore, run_id: str) -> Predecessor:
    """The predecessor's declared state and last covered date, or a refusal.

    Reads two small documents; never the state itself.
    """

    validate_run_id(run_id)
    document = load_run_manifest(store, run_id)
    ledger = _read_json(store, run_key(run_id, LEDGER_PATH), "run_ledger")
    acceptance = check_processing_ledger(ledger)
    dates = sorted(entry.observed_on for entry in acceptance.dates)
    if not dates:
        raise ChainRejected(
            [
                Finding(
                    "predecessor_covered_nothing",
                    f"the ledger of {run_id} reconciles no date, so there is no "
                    "last covered date for a successor to follow",
                    run_key(run_id, LEDGER_PATH),
                )
            ]
        )
    state = document["persistence_state"]
    return Predecessor(
        run_id=run_id,
        persistence_state_sha256=state["sha256"],
        persistence_state_bytes=state["bytes"],
        last_observed_on=dates[-1],
        stored=state.get("stored"),
        algorithm_version=acceptance.algorithm_version,
    )


def check_generation(predecessor: Predecessor, algorithm_version: str) -> None:
    """Refuse to continue a run of another generation (PHASE_6W).

    ``update_tracks`` stamps the version it is given and never compares it with
    the state's, so nothing downstream would notice a 1.1.0 run continuing a
    1.0.0 state until the chain release refuses to mix them — after the run is
    deposited and the old chain has a second child.  A new generation is a new
    root (PHASE_6H §1): ``chain=empty``, then ``CHAIN_ROOT`` moves in a reviewed
    change.
    """

    if predecessor.algorithm_version != algorithm_version:
        raise ChainRejected(
            [
                Finding(
                    "predecessor_other_generation",
                    f"{predecessor.run_id} was detected under algorithm_version "
                    f"{predecessor.algorithm_version!r} and this run detects under "
                    f"{algorithm_version!r}. A new generation starts from an empty "
                    "state, as a new chain root.",
                    run_key(predecessor.run_id, LEDGER_PATH),
                )
            ]
        )


def check_window(predecessor: Predecessor, start: str) -> None:
    """Refuse any start but the day after the predecessor's last covered date."""

    try:
        requested = date.fromisoformat(start)
    except (TypeError, ValueError):
        raise ChainRejected(
            [Finding("window_start_invalid", f"{start!r} is not YYYY-MM-DD", "start")]
        ) from None
    expected = date.fromisoformat(predecessor.next_start)
    if requested == expected:
        return
    last = predecessor.last_observed_on
    if requested < expected:
        code = "window_overlaps_predecessor"
        detail = (
            f"{start} is not after {last}, the last date {predecessor.run_id} "
            "covers. A date covered twice is either refused by update_tracks as "
            "out of order or claimed by two ledgers."
        )
    else:
        code = "window_leaves_a_gap"
        skipped = (requested - expected).days
        detail = (
            f"{start} skips {skipped} day(s) after {last}, the last date "
            f"{predecessor.run_id} covers. Once this run moves the watermark, "
            "update_tracks refuses every earlier date, so a gap in a chain is "
            "a permanent loss."
        )
    raise ChainRejected(
        [Finding(code, detail + f" The chained window must start on {expected}.", "start")]
    )


def fetch_state(store: ConditionalStore, predecessor: Predecessor) -> bytes:
    """The predecessor's state bytes, verified against its ``run.json``.

    ``runs/ci-36432616599/`` is the case this exists for: its ``run.json``
    declares a state that was never deposited, and "declared" must not be read
    as "present".
    """

    compressed = predecessor.stored
    key = (
        run_key(predecessor.run_id, compressed["path"])
        if compressed
        else state_key(predecessor.run_id)
    )
    try:
        stored = store.get(key)
    except ObjectStoreError as exc:
        raise ChainRejected([Finding("predecessor_state_unreadable", str(exc), key)]) from exc
    if stored is None:
        raise ChainRejected(
            [
                Finding(
                    "predecessor_state_absent",
                    f"{store.bucket}/{key} is absent. The run.json of "
                    f"{predecessor.run_id} declares a persistence state, and no "
                    "object holds it — the run was deposited before states were, "
                    "or the state was never written. A run cannot continue from "
                    "a digest.",
                    key,
                )
            ]
        )
    body = stored.body
    if compressed:
        # The object first — is it the one written? — then the state it holds.
        findings = []
        if len(body) != compressed["bytes"]:
            findings.append(
                Finding(
                    "predecessor_stored_state_length_mismatch",
                    f"{key} holds {len(body)} bytes and the run.json declares "
                    f"{compressed['bytes']}",
                    key,
                )
            )
        if sha256_bytes(body) != compressed["sha256"]:
            findings.append(
                Finding(
                    "predecessor_stored_state_digest_mismatch",
                    f"{key} does not hash to the stored digest the run.json declares",
                    key,
                )
            )
        if findings:
            raise ChainRejected(findings)
        body = _decompress(body, predecessor.persistence_state_bytes, key)
    findings = []
    if len(body) != predecessor.persistence_state_bytes:
        findings.append(
            Finding(
                "predecessor_state_length_mismatch",
                f"{key} holds {len(body)} bytes and the run.json declares "
                f"{predecessor.persistence_state_bytes}",
                key,
            )
        )
    digest = sha256_bytes(body)
    if digest != predecessor.persistence_state_sha256:
        findings.append(
            Finding(
                "predecessor_state_digest_mismatch",
                f"{key} hashes to {digest} and the run.json declares "
                f"{predecessor.persistence_state_sha256}",
                key,
            )
        )
    if findings:
        raise ChainRejected(findings)
    return body


def seed_state(store: ConditionalStore, run_id: str, body: bytes) -> PutOutcome:
    """Put one run's state into its own prefix, once, if its ``run.json`` binds it.

    For a run deposited before states were: the ``run.json`` already declares
    the digest, so the only question is whether these are those bytes — and it
    is answered before anything is written.  A run with no ``run.json`` is
    refused by ``load_run_manifest``: a state with no run to bind it is not a
    chain link.
    """

    document = load_run_manifest(store, run_id)
    declared = document["persistence_state"]
    digest = sha256_bytes(body)
    findings = []
    if len(body) != declared["bytes"]:
        findings.append(
            Finding(
                "seed_length_mismatch",
                f"the local state is {len(body)} bytes and runs/{run_id}/run.json "
                f"declares {declared['bytes']}",
                "state",
            )
        )
    if digest != declared["sha256"]:
        findings.append(
            Finding(
                "seed_digest_mismatch",
                f"the local state hashes to {digest} and runs/{run_id}/run.json "
                f"declares {declared['sha256']}",
                "state",
            )
        )
    if findings:
        raise ChainRejected(findings)
    check_single_put(len(body), "state")
    return store.put_if_absent(state_key(run_id), body, STATE_CONTENT_TYPE)


def check_link(link: Any) -> dict[str, str] | None:
    """A ``predecessor`` field as a successor supplies it, or a refusal."""

    if link is None:
        return None
    if (
        not isinstance(link, Mapping)
        or set(link) != {"run_id", "persistence_state_sha256"}
        or not isinstance(link["persistence_state_sha256"], str)
        or not _SHA256.match(link["persistence_state_sha256"])
        or not isinstance(link["run_id"], str)
    ):
        raise ChainRejected(
            [
                Finding(
                    "predecessor_link_invalid",
                    "a predecessor is {run_id, persistence_state_sha256} and "
                    f"nothing else; got {link!r}",
                    "predecessor",
                )
            ]
        )
    validate_run_id(link["run_id"])
    return {"run_id": link["run_id"], "persistence_state_sha256": link["persistence_state_sha256"]}


def confirm_link(store: ConditionalStore, link: Mapping[str, str]) -> None:
    """The link a successor carries must equal what its predecessor declares.

    Run in the job that writes, with that job's own identity, so the detection
    job's artifact is not the only witness to which state the run started from.
    """

    document = load_run_manifest(store, link["run_id"])
    declared = document["persistence_state"]["sha256"]
    if declared != link["persistence_state_sha256"]:
        raise ChainRejected(
            [
                Finding(
                    "predecessor_link_mismatch",
                    f"this run says it started from {link['persistence_state_sha256']} "
                    f"and runs/{link['run_id']}/run.json declares {declared}",
                    "predecessor",
                )
            ]
        )


# ── the head, the fork, the automatic window (PHASE_6H) ──────────────────────

#: The run the chain grows from: the 2026 replay's candidate, whose state
#: PHASE_6G §7 put into its own prefix and verified.  It is the one fact the
#: derivation cannot deduce — nine run.json in the bucket name no predecessor
#: and eight of them are not this chain's start (PHASE_6H §0) — so it is
#: declared here.  A new generation (a backfill from empty, which
#: ``update_tracks`` requires below the watermark) is a new root, and that is
#: a reviewed code change, not a dispatch input (PHASE_6H §1, §5).
CHAIN_ROOT = "rep-2026-08-30-v3"

#: The lane's window ceiling, the ``(b - a).days <= 16`` of
#: ``v2_green_deposit_lane.yml``; ``tests/test_green_deposit_lane.py`` keeps
#: the two equal.  A queue longer than this is walked in several runs.
WINDOW_MAX_DAYS = 16

#: How many days before today the automatic window stops (exclusive end =
#: today - SETTLE_DAYS), so a run on day T enumerates at most T - 2.  Measured
#: in PHASE_6H §0 from twelve blue runs: every date older than 21.9 h was
#: visible, and the youngest visible was 19.6 h — T - 1 sits in that band at
#: the cron's hour, T - 2 at twice it.  A date not yet ingested before the
#: last enumerated one is lost to the chain for good (§3), so the band is
#: excluded at the price of one day of latency.
SETTLE_DAYS = 1

_RUN_PREFIX = RUNS_ROOT + "/"


def _listing_client(store: ConditionalStore) -> Any:
    """The raw client the store reads with, for the one listing the chain needs.

    ``ConditionalStore`` deliberately has no listing (``retention.list_inventory``
    explains why), and a listing is neither a write nor a widening of it.  It
    goes through the same client, so the list and the reads that follow see
    one bucket through one identity — in the lane and in a test fake alike.
    """

    return store._client  # noqa: SLF001 - read-only listing, see docstring


def list_run_ids(store: ConditionalStore) -> list[str]:
    """Every ``runs/<id>/`` prefix, following the cursor, or a refusal.

    One delimited listing — prefixes, not objects, so a run's 70 alert files
    cost nothing.  R2 lists strongly consistently (PHASE_6H §0): a run whose
    ``run.json`` was written before this call is in the answer.
    """

    client = _listing_client(store)
    ids: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.bucket,
            "Prefix": _RUN_PREFIX,
            "Delimiter": "/",
        }
        if token:
            kwargs["ContinuationToken"] = token
        try:
            page = client.list_objects_v2(**kwargs)
        except Exception as exc:  # botocore ClientError and transport errors
            raise ChainRejected(
                [Finding("run_listing_unreadable", str(exc), _RUN_PREFIX)]
            ) from exc
        for entry in page.get("CommonPrefixes") or ():
            segment = entry["Prefix"][len(_RUN_PREFIX):].rstrip("/")
            if segment:
                ids.append(segment)
        if not page.get("IsTruncated"):
            return sorted(set(ids))
        token = page.get("NextContinuationToken")
        if not token:
            # A partial listing could omit exactly the child that makes the
            # apparent head a continued run. Refuse rather than decide on it.
            raise ChainRejected(
                [
                    Finding(
                        "run_listing_incomplete",
                        f"listing {store.bucket}/{_RUN_PREFIX} reported more "
                        "results and returned no continuation token",
                        _RUN_PREFIX,
                    )
                ]
            )


@dataclass(frozen=True)
class RunLinks:
    """What the bucket says about every run: who continues whom.

    ``manifests`` holds every run that has a ``run.json``; ``incomplete`` the
    prefixes without one — a deposit writes ``run.json`` last, so those are
    deposits that did not finish, and they are not runs.
    """

    manifests: dict[str, dict]
    incomplete: tuple[str, ...]

    def parent_of(self, run_id: str) -> str | None:
        link = self.manifests[run_id].get("predecessor")
        return link["run_id"] if link else None

    def children_of(self, run_id: str) -> list[str]:
        return sorted(rid for rid in self.manifests if self.parent_of(rid) == run_id)


def read_run_links(store: ConditionalStore) -> RunLinks:
    """Every ``run.json`` in the bucket, validated — any invalid one refuses.

    Failing closed on one unreadable ``run.json`` is deliberate: it may be the
    very child that makes the apparent head a continued run (PHASE_6H §1).
    """

    manifests: dict[str, dict] = {}
    incomplete: list[str] = []
    for run_id in list_run_ids(store):
        try:
            validate_run_id(run_id)
        except Rejected:
            incomplete.append(run_id)
            continue
        try:
            manifests[run_id] = load_run_manifest(store, run_id)
        except Rejected as exc:
            if exc.codes != ("run_manifest_absent",):
                raise
            incomplete.append(run_id)
    return RunLinks(manifests, tuple(incomplete))


@dataclass(frozen=True)
class ChainHead:
    """The chain from its root to the one run nothing continues yet."""

    path: tuple[str, ...]
    incomplete: tuple[str, ...]
    outside: tuple[str, ...]

    @property
    def run_id(self) -> str:
        return self.path[-1]


def resolve_head(store: ConditionalStore, root: str = CHAIN_ROOT) -> ChainHead:
    """Walk the ``predecessor`` edges from ``root`` to the single leaf, or refuse.

    Zero children: the head.  One: the next step, after its link is checked
    against its parent's declared state.  Two or more: a fork, refused with
    both names — a fork is never resolved here, because choosing a branch is
    choosing which dates the chain claims (PHASE_6H §2).
    """

    links = read_run_links(store)
    if root not in links.manifests:
        raise ChainRejected(
            [
                Finding(
                    "chain_root_absent",
                    f"runs/{root}/run.json is absent; the chain has nothing to "
                    "grow from",
                    run_key(root, RUN_MANIFEST_PATH),
                )
            ]
        )
    path = [root]
    while True:
        current = path[-1]
        children = links.children_of(current)
        if not children:
            break
        if len(children) > 1:
            raise ChainRejected(
                [
                    Finding(
                        "chain_forked",
                        f"{', '.join(children)} all continue {current}. A chain "
                        "has one head; which branch holds the chain's dates is a "
                        "recorded human decision, and nothing here deletes or "
                        "chooses.",
                        run_key(current, RUN_MANIFEST_PATH),
                    )
                ]
            )
        (child,) = children
        declared = links.manifests[current]["persistence_state"]["sha256"]
        claimed = links.manifests[child]["predecessor"]["persistence_state_sha256"]
        if claimed != declared:
            raise ChainRejected(
                [
                    Finding(
                        "predecessor_link_mismatch",
                        f"{child} says it started from {claimed} and "
                        f"runs/{current}/run.json declares {declared}",
                        run_key(child, RUN_MANIFEST_PATH),
                    )
                ]
            )
        path.append(child)
    on_chain = set(path)
    outside = tuple(sorted(rid for rid in links.manifests if rid not in on_chain))
    return ChainHead(tuple(path), links.incomplete, outside)


def check_not_continued(store: ConditionalStore, predecessor_id: str, run_id: str | None) -> None:
    """Refuse when a run other than ``run_id`` already continues ``predecessor_id``.

    The deposit asks before its first byte and again right before its
    ``run.json`` (PHASE_6H §2).  ``run_id`` itself does not count: re-running
    only the deposit job of the same run finds its own ``run.json`` and must
    go on to the usual ``unchanged``.
    """

    others = [
        rid for rid in read_run_links(store).children_of(predecessor_id) if rid != run_id
    ]
    if others:
        raise ChainRejected(
            [
                Finding(
                    "predecessor_already_continued",
                    f"{', '.join(others)} already continue {predecessor_id}. A "
                    "second continuation would make two runs claim the same "
                    "dates; continue the head instead.",
                    run_key(predecessor_id, RUN_MANIFEST_PATH),
                )
            ]
        )


@dataclass(frozen=True)
class Window:
    start: str
    end: str

    @property
    def days(self) -> int:
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days

    @property
    def full(self) -> bool:
        """At the ceiling: an enumeration that finds nothing here is a failure."""

        return self.days == WINDOW_MAX_DAYS


def automatic_window(predecessor: Predecessor, today: str) -> Window | None:
    """``[next_start, min(today - SETTLE_DAYS, next_start + 16))``, or nothing to do.

    ``None`` when the head already covers everything the settle rule allows —
    not an error: the scheduled run that finds it has simply come early.
    """

    try:
        now = date.fromisoformat(today)
    except (TypeError, ValueError):
        raise ChainRejected(
            [Finding("today_invalid", f"{today!r} is not YYYY-MM-DD", "today")]
        ) from None
    start = date.fromisoformat(predecessor.next_start)
    end = min(now - timedelta(days=SETTLE_DAYS), start + timedelta(days=WINDOW_MAX_DAYS))
    if end <= start:
        return None
    return Window(start.isoformat(), end.isoformat())
