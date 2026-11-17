"""The green series of the live release: which rows documents, and the database (D4B).

Where the rows live
-------------------
``green_rows.run_rows`` measures one run's rows in the detect job, from the
composites that die with the runner.  The deposit job stores that document
beside the run, at ``series/<run-id>/timeseries_rows.json`` with
``put_if_absent`` — a sibling prefix, never under ``runs/``: the chain-head
resolution reads every ``runs/<id>/`` it finds, and ``run.json`` is a closed
schema (``green-run-v3``, ``additionalProperties: false``).  The document is the
only copy of the measurement, so retention keeps it
(``src/publication/retention.py``).

Which documents make the series
-------------------------------
The **live release**, not the bucket: the pointer names a version-3 chain
release whose ``members`` are the runs' version-1 releases, each naming its
``ledger_id`` and ``run_manifest_id``.  A rows document names the same two
ids (``green_rows.run_rows``), so a document belongs to a member exactly when
both match.  The run id in the key is a namespace, not the binding.

* A member with no document is a **hole**, and the build refuses
  (``SeriesIncomplete``): a series with a silent gap is the failure Package
  2A.2 quarantined the legacy database for.  Every run deposited before this
  package has none; the reconstruction workflow fills them
  (``v2_green_series_rebuild.yml``), and until it has, the series lane fails
  loudly instead of publishing a partial series.
* Two different documents for one member are refused; byte-identical copies
  are one document.
* Documents of two generations are refused: one series is one generation
  (``green_rows.generation_identity``).

The database
------------
Built **from empty** on every run, members in chain order, so the same
documents give the same bytes — and an unchanged series opens no pull request.

It imports nothing from ``config`` (``tests/test_assemble_green_run.py``).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.timeseries import green_rows as gr

SERIES_ROOT = "series/"
ROWS_NAME = "timeseries_rows.json"

#: The published database and its signal.  New names on purpose: the legacy
#: ``timeseries.db`` is quarantined (Package 2A.2) and ``RELEASE.json`` is the
#: blue signal the site still validates until its consumer moves.
DATABASE_NAME = "green_series.db"
SIGNAL_NAME = "GREEN_SERIES.json"
SIGNAL_SCHEMA = "araripe.green.timeseries.release/1"


class SeriesRejected(ValueError):
    """The documents cannot make the live release's series."""


class SeriesIncomplete(SeriesRejected):
    """At least one member of the live release has no rows document."""

    def __init__(self, missing: Sequence[Mapping[str, Any]]):
        self.missing = list(missing)
        names = ", ".join(
            f"{m['release_id']} ({m['first_observed_on']}..{m['last_observed_on']})"
            for m in self.missing
        )
        super().__init__(
            f"{len(self.missing)} member(s) of the live release have no rows "
            f"document: {names}. Run v2_green_series_rebuild.yml; a series with "
            "a hole is not published."
        )


def series_key(run_id: str) -> str:
    if not run_id or "/" in run_id or run_id in (".", ".."):
        raise SeriesRejected(f"{run_id!r} is not one run id")
    return f"{SERIES_ROOT}{run_id}/{ROWS_NAME}"


def run_id_of(key: str) -> str | None:
    """The run id of a rows-document key, or ``None`` for any other key."""

    if not key.startswith(SERIES_ROOT) or not key.endswith("/" + ROWS_NAME):
        return None
    run_id = key[len(SERIES_ROOT) : -len("/" + ROWS_NAME)]
    return run_id if run_id and "/" not in run_id else None


def check_rows_document(document: Any, *, ledger: Mapping[str, Any] | None = None) -> None:
    """The shape every consumer relies on, and, with ``ledger``, its binding."""

    if not isinstance(document, Mapping) or document.get("schema") != gr.ROWS_SCHEMA:
        raise SeriesRejected(f"not a {gr.ROWS_SCHEMA} document")
    for field in ("ledger_id", "run_manifest_id", "generation", "acquisitions"):
        if field not in document:
            raise SeriesRejected(f"the rows document has no {field}")
    if ledger is not None:
        for field in ("ledger_id", "run_manifest_id"):
            if document[field] != ledger.get(field):
                raise SeriesRejected(
                    f"the rows document names {field} {document[field]}, the "
                    f"run's ledger {ledger.get(field)}"
                )


def live_members(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The live chain release's members, in chain order."""

    members = manifest.get("members")
    if not isinstance(members, list) or not members:
        raise SeriesRejected(
            f"{manifest.get('release_id')} is not a chain release with members; "
            "the series follows the chain release, the only source a routine "
            "promotes"
        )
    return sorted(members, key=lambda m: (m["first_observed_on"], m["release_id"]))


def select_documents(
    manifest: Mapping[str, Any], documents: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One document per member, in chain order — or a refusal."""

    by_member: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        check_rows_document(document)
        identity = (document["ledger_id"], document["run_manifest_id"])
        held = by_member.get(identity)
        if held is not None and gr._canonical(held) != gr._canonical(document):
            raise SeriesRejected(
                f"two different rows documents name ledger {identity[0]}"
            )
        by_member[identity] = dict(document)

    chosen, missing = [], []
    for member in live_members(manifest):
        document = by_member.get((member["ledger_id"], member["run_manifest_id"]))
        if document is None:
            missing.append(member)
        else:
            chosen.append(document)
    if missing:
        raise SeriesIncomplete(missing)
    generations = {d["generation"]["generation_id"] for d in chosen}
    if len(generations) != 1:
        raise SeriesRejected(f"one series is one generation: {sorted(generations)}")
    return chosen


def sha256_file(path: Path) -> str:
    return gr.sha256_file(Path(path))


def build_database(path: Path, documents: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Write ``documents`` into a fresh database at ``path``, refusing to reuse one."""

    path = Path(path)
    if path.exists():
        raise SeriesRejected(f"{path} exists; the series database is built from empty")
    return gr.apply_rows(path, documents)


def summarize(path: Path) -> dict[str, Any]:
    """What the signal states about the database, read back from it."""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        first, last, total = connection.execute(
            "SELECT min(observed_on), max(observed_on), count(*) FROM acquisitions"
        ).fetchone()
        accepted_last, accepted = connection.execute(
            "SELECT max(observed_on), count(*) FROM acquisitions "
            "WHERE qa_status = 'accepted'"
        ).fetchone()
        (generation,) = connection.execute(
            "SELECT generation_id FROM processing_generations"
        ).fetchone()
    finally:
        connection.close()
    return {
        "generation_id": generation,
        "first_observed_on": first,
        "last_observed_on": last,
        "last_accepted_observed_on": accepted_last,
        "acquisitions": total,
        "accepted": accepted,
    }


def build_signal(
    path: Path,
    *,
    release_id: str,
    documents: Sequence[Mapping[str, Any]],
    published_utc: str,
    run_url: str | None,
) -> dict[str, Any]:
    """The release signal the site validates (successor of ``RELEASE.json``)."""

    path = Path(path)
    return {
        "schema": SIGNAL_SCHEMA,
        "release_id": release_id,
        "published_utc": published_utc,
        "run_url": run_url,
        "database": {
            "path": f"data/timeseries/{DATABASE_NAME}",
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        },
        "series": summarize(path),
        "documents": [
            {"ledger_id": d["ledger_id"],
             "sha256": hashlib.sha256(gr._canonical(d)).hexdigest()}
            for d in documents
        ],
    }


def unchanged(previous: Mapping[str, Any] | None, signal: Mapping[str, Any]) -> bool:
    """Whether ``signal`` publishes nothing the published one does not."""

    if not previous or previous.get("schema") != SIGNAL_SCHEMA:
        return False
    return (previous.get("release_id") == signal["release_id"]
            and previous.get("database", {}).get("sha256") == signal["database"]["sha256"])


def dumps(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
