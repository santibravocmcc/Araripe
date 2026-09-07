"""Build valid v3 ledgers with chosen per-date statuses, plus their artifacts.

Package 2B.2B has to tell four kinds of UTC date apart — alerts, an observed
quiet day, a partly observed quiet day, and a day nobody could observe — so
its tests need ledgers that actually contain those shapes.  The producer's
committed fixture holds one date of two ``complete_with_alerts``
acquisitions, so the rest are assembled here.

Assembled from the producer's own fixture and resealed with the Package 2B.2A
helper, which ``test_resealing_an_unchanged_ledger_reproduces_it_byte_for_byte``
proves is the producer's arithmetic rather than an approximation.  Nothing
here re-implements a contract rule: identities come from
``rebuild_acquisition`` and every digest from ``reseal``.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime

from src.publication import ledger_binding
from tests.test_ledger_completeness_gate import rebuild_acquisition, reseal

STATUSES = ledger_binding.pinned_terminal_statuses()
ALERTS = "complete_with_alerts"
ZERO = "complete_zero_alerts"
REJECTED = "rejected_low_coverage"
FAILED = "failed_download"


def _instant(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp[:-1] + "+00:00")


def producer_fixture() -> dict:
    return json.loads(
        ledger_binding.acceptance_fixture_path().read_text(encoding="utf-8")
    )


def artifact_body(date: str, index: int) -> bytes:
    """Deterministic stand-in for a per-acquisition alert artifact."""

    return (
        '{"type":"FeatureCollection","observed_on":"%s","slot":%d,"features":[]}'
        % (date, index)
    ).encode("utf-8")


def _observation_id(seed: str) -> str:
    return "obs-v3-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_ledger(spec: dict[str, list[str]]) -> tuple[dict, dict[str, bytes]]:
    """A valid ledger for ``{observed_on: [status, ...]}``.

    Returns the ledger and ``{acquisition_id: artifact bytes}`` for every
    acquisition whose status seals an artifact checksum.  The checksums in the
    ledger are the real digests of those bytes, so a release built from them
    passes the artifact cross-check without any test having to fake one.
    """

    base = producer_fixture()
    template = base["expected_acquisitions"][0]
    sealing = ledger_binding.pinned_status_semantics()["artifact_sealing"]
    bearing = ledger_binding.pinned_status_semantics()["alert_bearing"]

    expected: list[dict] = []
    rows: list[dict] = []
    bodies: dict[str, bytes] = {}

    for date in sorted(spec):
        for index, status in enumerate(spec[date]):
            stamp = f"{date}T13:{12 + index:02d}:41Z"
            item = rebuild_acquisition(
                template,
                datatake_id=f"GS2A_{date.replace('-', '')}T131241_{index:06d}_N05.11",
                acquisition_timestamp_utc=stamp,
            )
            expected.append(item)

            output = {"observation_count": 0, "observation_ids": [], "artifact_sha256": None}
            reason = None
            if status in sealing:
                body = artifact_body(date, index)
                bodies[item["acquisition_id"]] = body
                output["artifact_sha256"] = hashlib.sha256(body).hexdigest()
            if status in bearing:
                ids = sorted(
                    (
                        _observation_id(f"{item['acquisition_id']}/{n}")
                        for n in range(index + 1)
                    ),
                    key=lambda value: value.encode("utf-8"),
                )
                output["observation_count"] = len(ids)
                output["observation_ids"] = ids
            if status not in sealing:
                reason = {"code": status.replace("_", "-"), "message": f"{status} on {date}"}

            rows.append(
                {
                    "acquisition_id": item["acquisition_id"],
                    "acquisition_timestamp_utc": stamp,
                    "observed_on": date,
                    "status": status,
                    "terminal_at": f"{date}T18:00:00Z",
                    "output": output,
                    "reason": reason,
                    "terminal_record_sha256": "0" * 64,
                }
            )

    order = lambda entry: (_instant(entry["acquisition_timestamp_utc"]), entry["acquisition_id"])
    document = deepcopy(base)
    document["expected_acquisitions"] = sorted(expected, key=order)
    document["terminal_rows"] = sorted(rows, key=order)
    document["daily_summaries"] = []
    return reseal(document, rederive_summaries=True), bodies


def alerting_release_inputs():
    """The producer's own fixture, with real artifact checksums.

    Kept separate from ``build_ledger`` so at least one release in the suite
    is built on the pinned acceptance fixture itself — including its
    Sentinel-2C acquisition, which is why the v3 family was chosen
    (``LEDGER_CONTRACT_BINDING_V1.md`` §1).
    """

    document = producer_fixture()
    bodies: dict[str, bytes] = {}
    for index, row in enumerate(document["terminal_rows"]):
        body = artifact_body(row["observed_on"], index)
        bodies[row["acquisition_id"]] = body
        row["output"]["artifact_sha256"] = hashlib.sha256(body).hexdigest()
    return reseal(document, rederive_summaries=True), bodies
