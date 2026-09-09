"""The checksummed photograph of what exists before the replay.

Phase 3, scope item 3 — the roadmap bullet *"Snapshot and checksum the current
R2 alerts, baseline objects, persistence state, SQLite database, site manifest,
public products, and both repository commits"*.

What is measured and what is declared unmeasured
------------------------------------------------
Every entry carries a ``measured`` flag and, when it is false, a ``reason``.
That is not bookkeeping politeness — it is the same discipline the post-cutoff
queue exists for.  A photograph that silently omits the R2 alert inventory
because no credential was present is indistinguishable from a photograph taken
of an empty bucket, and Phase 4 would reconcile against the difference.

Concretely, on the machine this was first run on: the v1 baseline rasters are
**not** local (``data/baselines/`` holds only ``plots/``), because production
fetches them from R2 at run time.  So the baseline entry records each
generation's *manifest identity* — manifest SHA-256, inventory SHA-256, object
count, total bytes — which is a complete checksum of the inventory without
downloading 13 GB, and separately records whether the rasters happened to be
local and were verified byte for byte.

No credential, by construction
------------------------------
This module imports nothing from ``config`` and reads nothing from the
environment, so it cannot load the repository's ``.env``.  Paths are handed in
relative to a repository root.  The optional read-only R2 inventory lives in
the CLI, takes its endpoint and keys from explicit arguments, and is absent
from the document — as unmeasured, with its reason — when it was not run.

Nothing here writes to R2, to git, or to the site.  Read-only throughout.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.detection.identity import canonical_sha256

#: Version token of the snapshot document.
REPLAY_SNAPSHOT_VERSION = "phase3-replay-snapshot-v1"

#: The subjects the roadmap bullet names, in its order.  A subject missing from
#: the document is an error, not an omission.
SNAPSHOT_SUBJECTS = (
    "r2_alerts",
    "baseline_objects",
    "persistence_state",
    "timeseries_database",
    "site_manifest",
    "public_products",
    "repository_commits",
)


class SnapshotError(ValueError):
    """The snapshot cannot be produced or does not account for itself."""


def sha256_of_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path, root: Path | None) -> str:
    """A path as it should appear in a committed document.

    Relative to the repository it belongs to whenever it is inside one. An
    absolute path here would pin the document to one laptop, which
    ``AGENTS.md`` forbids and which would also make two snapshots of the same
    tree differ by whose machine took them.
    """

    path = Path(path)
    if root is not None:
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _unmeasured(reason: str, **extra: Any) -> dict[str, Any]:
    return {"measured": False, "reason": reason, **extra}


def _measured(**fields: Any) -> dict[str, Any]:
    return {"measured": True, **fields}


def file_entry(path: Path, *, label: str, root: Path | None = None) -> dict[str, Any]:
    """One file's identity, or the reason there is none."""

    path = Path(path)
    shown = display_path(path, root)
    if not path.exists():
        return _unmeasured(f"{label} is not present at {shown}", path=shown)
    if not path.is_file():
        return _unmeasured(f"{label} at {shown} is not a file", path=shown)
    return _measured(
        path=shown,
        bytes=path.stat().st_size,
        sha256=sha256_of_file(path),
    )


def directory_entry(
    directory: Path,
    *,
    label: str,
    patterns: Iterable[str] = ("*",),
    root: Path | None = None,
) -> dict[str, Any]:
    """Every matching file in a directory, checksummed, sorted by name."""

    directory = Path(directory)
    shown = display_path(directory, root)
    if not directory.is_dir():
        return _unmeasured(f"{label} directory {shown} is absent", path=shown)
    seen: dict[str, Path] = {}
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                seen[path.name] = path
    files = [
        {
            "name": name,
            "bytes": seen[name].stat().st_size,
            "sha256": sha256_of_file(seen[name]),
        }
        for name in sorted(seen)
    ]
    return _measured(
        path=shown,
        file_count=len(files),
        total_bytes=sum(item["bytes"] for item in files),
        inventory_sha256=canonical_sha256(files),
        files=files,
    )


def baseline_generation_entry(
    *,
    version: str,
    manifest_path: Path,
    directory: Path,
    key_prefix: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """One baseline generation's identity, plus whether its rasters are local.

    The manifest identity is the checksum of the inventory and is available
    without the rasters; ``rasters_local`` says whether the 72 objects were
    also present and verified here.  Keeping the two apart is what stops "the
    inventory is sealed" from being read as "the bytes were checked".
    """

    manifest_path = Path(manifest_path)
    shown_manifest = display_path(manifest_path, root)
    if not manifest_path.is_file():
        return _unmeasured(
            f"baseline {version} manifest is absent at {shown_manifest}",
            version=version,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    aggregate = manifest.get("aggregate") or {}
    expected = {obj["filename"]: obj for obj in manifest.get("objects") or []}

    directory = Path(directory)
    present = (
        sorted(
            name
            for name in expected
            if (directory / name).is_file()
        )
        if directory.is_dir()
        else []
    )
    verified: list[str] = []
    mismatched: list[str] = []
    for name in present:
        path = directory / name
        record = expected[name]
        if path.stat().st_size == record["bytes"] and sha256_of_file(path) == (
            record["sha256"]
        ):
            verified.append(name)
        else:
            mismatched.append(name)

    return _measured(
        version=version,
        key_prefix=key_prefix,
        manifest_path=shown_manifest,
        manifest_sha256=sha256_of_file(manifest_path),
        object_count=aggregate.get("object_count"),
        total_bytes=aggregate.get("total_bytes"),
        inventory_sha256=aggregate.get("inventory_sha256"),
        status=manifest.get("status"),
        rasters_local={
            "directory": display_path(directory, root),
            "expected": len(expected),
            "present": len(present),
            "verified": len(verified),
            "mismatched": sorted(mismatched),
        },
    )


def timeseries_entry(db_path: Path, *, root: Path | None = None) -> dict[str, Any]:
    """The tracked SQLite database: its bytes, and the read-only audit."""

    db_path = Path(db_path)
    shown = display_path(db_path, root)
    if not db_path.is_file():
        return _unmeasured(f"time-series database is absent at {shown}", path=shown)
    from src.timeseries.audit import audit_legacy_database

    entry = _measured(
        path=shown,
        bytes=db_path.stat().st_size,
        sha256=sha256_of_file(db_path),
    )
    try:
        report = audit_legacy_database(db_path)
    except Exception as exc:  # the auditor owns its own failure vocabulary
        entry["audit"] = _unmeasured(f"{type(exc).__name__}: {exc}")
        return entry
    inventory = report.get("inventory") or {}
    entry["audit"] = _measured(
        audit_schema_version=report.get("audit_schema_version"),
        regional_rows=inventory.get("regional_rows"),
        regional_dates=inventory.get("regional_dates"),
        regional_date_range=[
            inventory.get("regional_min_date"),
            inventory.get("regional_max_date"),
        ],
        alert_rows=inventory.get("alert_rows"),
        indices=inventory.get("indices"),
        disposition=(report.get("disposition") or {}).get("classification"),
        publishable=(report.get("disposition") or {}).get("publishable"),
        issue_count=len(report.get("issues") or []),
        report_sha256=canonical_sha256(report),
    )
    return entry


def observed_dates_from_timeseries(db_path: Path) -> tuple[str, ...]:
    """Every UTC date the tracked time-series database has a row for.

    The measured observation set the post-cutoff queue needs. Read read-only
    from both tables and unioned: ``alert_stats`` holds only dates that
    produced alerts, so a quiet observed day exists in ``regional_stats``
    alone — taking either table by itself would drop a whole class of date.
    Measured on the tracked database: 55 regional dates, 45 alert dates, 55
    in the union.
    """

    import sqlite3

    db_path = Path(db_path)
    if not db_path.is_file():
        raise SnapshotError(f"time-series database not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        dates = {
            str(row[0])
            for table in ("regional_stats", "alert_stats")
            for row in connection.execute(f"SELECT DISTINCT date FROM {table}")
            if row[0]
        }
    finally:
        connection.close()
    return tuple(sorted(dates))


def git_commit_entry(
    repository: Path, *, label: str, root: Path | None = None
) -> dict[str, Any]:
    """One repository's HEAD, its upstream, and whether the tree is clean.

    Read through ``git`` itself so the SHA is copied from the tool that
    produces it.  A dirty tree is recorded rather than refused: the
    photograph's job is to say what was there, and "there were uncommitted
    changes" is part of what was there.
    """

    repository = Path(repository)
    shown = display_path(repository, root)
    if not (repository / ".git").exists():
        return _unmeasured(f"{label} is not a git repository at {shown}")

    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repository), *args],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip()

    head = run("rev-parse", "HEAD")
    if head is None:
        return _unmeasured(f"git could not read {label}'s HEAD")
    porcelain = run("status", "--porcelain") or ""
    return _measured(
        label=label,
        path=shown,
        head=head,
        head_subject=run("log", "-1", "--format=%s"),
        branch=run("rev-parse", "--abbrev-ref", "HEAD"),
        origin_main=run("rev-parse", "origin/main"),
        tree_clean=porcelain == "",
        dirty_paths=sorted(
            line[3:] for line in porcelain.splitlines() if len(line) > 3
        ),
    )


_RUN_FILE = re.compile(r"^run-(\d{4}-\d{2}-\d{2})\.")


def site_published_run_dates(
    alerts_dir: Path, *, root: Path | None = None
) -> dict[str, Any]:
    """The dates the published site actually carries a run file for.

    A second, independent view of which dates exist. It is not the same set as
    the tracked time-series database's: the site publishes a file only for a
    date that produced alerts, while the database also holds quiet observed
    days. Recording both is what makes a divergence visible instead of
    arguable — and the replay has to know which side it is reconciling.
    """

    alerts_dir = Path(alerts_dir)
    if not alerts_dir.is_dir():
        return _unmeasured(
            f"site alerts directory {display_path(alerts_dir, root)} is absent"
        )
    dates = sorted(
        {
            match.group(1)
            for path in alerts_dir.iterdir()
            if path.is_file() and (match := _RUN_FILE.match(path.name))
        }
    )
    return _measured(
        count=len(dates),
        earliest=dates[0] if dates else None,
        latest=dates[-1] if dates else None,
        dates=dates,
    )


def build_snapshot(
    *,
    backend_root: Path,
    site_root: Path | None,
    baseline_generations: Iterable[Mapping[str, Any]],
    r2_alerts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the photograph.

    ``r2_alerts`` is the read-only inventory when one was taken; ``None``
    records it as unmeasured with the reason, which is the honest state on a
    machine that holds no R2 credential — and holding none is the point of the
    production freeze.
    """

    backend_root = Path(backend_root)
    body: dict[str, Any] = {
        "replay_snapshot_version": REPLAY_SNAPSHOT_VERSION,
        "r2_alerts": (
            _measured(**dict(r2_alerts))
            if r2_alerts is not None
            else _unmeasured(
                "no R2 credential is present and production is read-only "
                "through Phases 2B-5; run this tool with --r2-read from an "
                "environment that holds a read-only key to fill it in"
            )
        ),
        "baseline_objects": {
            "measured": True,
            "generations": [
                baseline_generation_entry(root=backend_root, **dict(generation))
                for generation in baseline_generations
            ],
        },
        "persistence_state": file_entry(
            backend_root / "data" / "persistence_state.geojson",
            label="persistence state",
            root=backend_root,
        ),
        "timeseries_database": timeseries_entry(
            backend_root / "data" / "timeseries" / "timeseries.db",
            root=backend_root,
        ),
        "repository_commits": {
            "measured": True,
            "backend": git_commit_entry(
                backend_root, label="backend", root=backend_root
            ),
            "site": (
                git_commit_entry(
                    Path(site_root), label="site", root=Path(site_root)
                )
                if site_root is not None
                else _unmeasured("no site checkout path was supplied")
            ),
        },
    }

    if site_root is None:
        body["site_manifest"] = _unmeasured("no site checkout path was supplied")
        body["public_products"] = _unmeasured(
            "no site checkout path was supplied"
        )
    else:
        site_root = Path(site_root)
        body["site_manifest"] = file_entry(
            site_root / "public" / "data" / "alerts" / "manifest.json",
            label="site alert manifest",
            root=site_root,
        )
        alerts_dir = site_root / "public" / "data" / "alerts"
        body["public_products"] = {
            "measured": True,
            "repository": "site",
            "alerts": directory_entry(
                alerts_dir,
                label="site published alerts",
                patterns=("*.json", "*.geojson"),
                root=site_root,
            ),
            "timeseries": directory_entry(
                site_root / "public" / "data",
                label="site published data root",
                patterns=("*.json",),
                root=site_root,
            ),
            "published_run_dates": site_published_run_dates(
                alerts_dir, root=site_root
            ),
        }

    missing = [subject for subject in SNAPSHOT_SUBJECTS if subject not in body]
    if missing:
        raise SnapshotError(
            "the snapshot omits the roadmap subject(s): " + ", ".join(missing)
        )
    document = dict(body)
    document["snapshot_sha256"] = canonical_sha256(body)
    return document


def validate_snapshot(document: Mapping[str, Any]) -> None:
    """Fail closed on a snapshot that does not account for itself."""

    if not isinstance(document, Mapping):
        raise SnapshotError("the snapshot document must be a mapping")
    if document.get("replay_snapshot_version") != REPLAY_SNAPSHOT_VERSION:
        raise SnapshotError(
            f"snapshot version is {document.get('replay_snapshot_version')!r}, "
            f"expected {REPLAY_SNAPSHOT_VERSION!r}"
        )
    body = {
        key: value for key, value in document.items() if key != "snapshot_sha256"
    }
    if canonical_sha256(body) != document.get("snapshot_sha256"):
        raise SnapshotError("snapshot_sha256 does not match the document body")
    missing = [subject for subject in SNAPSHOT_SUBJECTS if subject not in body]
    if missing:
        raise SnapshotError(
            "the snapshot omits the roadmap subject(s): " + ", ".join(missing)
        )
    for subject in SNAPSHOT_SUBJECTS:
        entry = body[subject]
        if not isinstance(entry, Mapping) or "measured" not in entry:
            raise SnapshotError(
                f"{subject} carries no `measured` flag; an entry that does "
                "not say whether it was measured is not evidence"
            )
        if entry["measured"] is False and not entry.get("reason"):
            raise SnapshotError(f"{subject} is unmeasured and gives no reason")


def unmeasured_subjects(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Which roadmap subjects this photograph does not cover."""

    return tuple(
        subject
        for subject in SNAPSHOT_SUBJECTS
        if document.get(subject, {}).get("measured") is not True
    )


def release_drift(
    document: Mapping[str, Any], *, frozen_release: Mapping[str, Any]
) -> dict[str, Any]:
    """Whether the live blue release has advanced past the freeze.

    Reported, never asserted.  The blue lane keeps publishing through Phases
    2B-5 by design, so this drift is expected and a test that failed on it
    would break on every successful production run.
    """

    entry = document.get("timeseries_database", {})
    return {
        "frozen_db_sha256": frozen_release.get("timeseries_db_sha256"),
        "snapshot_db_sha256": entry.get("sha256"),
        "frozen_latest_observation": frozen_release.get("latest_observation"),
        "drifted": entry.get("sha256") != frozen_release.get("timeseries_db_sha256"),
        "expected": (
            "the blue lane publishes on Monday and Thursday; drift here means "
            "production ran, not that the freeze broke"
        ),
    }
