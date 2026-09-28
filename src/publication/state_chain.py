"""Chain one green run's persistence state onto the next.

``docs/implementation/PHASE_6G_2026-09-28.md`` §1-§4 is the decision this
module implements, and each rule below cites the section that argues it.

Where the state lives (§1)
--------------------------
``runs/<run_id>/persistence_state.geojson`` — a fixed name, like
``ledger.json``, bound by the digest and length every ``run.json`` already
declares under ``persistence_state``.  It is **not** listed in ``objects``:
those become the release, and the state is never published.

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

What this module never does
---------------------------
Write anything but the one state object of a run whose ``run.json`` already
declares it, and only with ``put_if_absent``; read or write a pointer; import
``config`` (``tests/test_assemble_green_run.py`` guards the scripts that use it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

from src.publication.conditional_store import ConditionalStore, ObjectStoreError, PutOutcome
from src.publication.findings import Finding, Rejected
from src.publication.green_release import sha256_bytes
from src.publication.ledger_gate import check_processing_ledger
from src.publication.run_inputs import (
    LEDGER_PATH,
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

    key = state_key(predecessor.run_id)
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
