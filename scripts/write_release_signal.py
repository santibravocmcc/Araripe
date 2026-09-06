#!/usr/bin/env python3
"""Write the time-series release signal consumed by the site (Package 2B.1).

Why this exists
---------------
The site used to infer "the backend has finished" from a fixed clock offset: it
refreshed 90 minutes after the backend cron and assumed the time-series pull
request had landed. On 2026-08-17 GitHub started the backend cron 67 minutes
late and the site read a `main` whose time-series PR had not merged yet — it
published a stale series while reporting success (ROADMAP.md §6).

A clock offset cannot express "the release is complete", so this replaces it
with a signal the site can *validate*: the backend states what it published and
the checksum of the artifact it published, and the site refuses to publish
unless the artifact it is holding is exactly that one.

The signal is written INTO `data/timeseries/`, so it travels in the same
squash-merged pull request as `timeseries.db` itself and is atomic with it by
construction — the existing publish step already refuses to stage anything
outside that directory, so no guard changes.

Scope: this is a release *signal*, not a manifest. Package 2B.2 owns the
manifest, the ledger and atomic publication, and absorbs this file's role.

Usage:
    python scripts/write_release_signal.py
    python scripts/write_release_signal.py --db data/timeseries/timeseries.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "araripe.timeseries.release/1"
DEFAULT_DB = Path("data/timeseries/timeseries.db")
SIGNAL_NAME = "RELEASE.json"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_observation(db: Path) -> str | None:
    """Most recent date in the published series, or None if it is empty."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute("select max(date) from regional_stats").fetchone()
    finally:
        con.close()
    return row[0] if row else None


def build_signal(db: Path, *, now=None, env=None) -> dict:
    """Describe the release that `db` represents."""
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    if not db.exists():
        raise SystemExit(f"::error::{db} does not exist — nothing to publish")

    run_id = env.get("GITHUB_RUN_ID")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repo = env.get("GITHUB_REPOSITORY")
    return {
        "schema": SCHEMA,
        "published_utc": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run_id": run_id,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else None,
        "latest_observation": latest_observation(db),
        "timeseries": {
            "path": db.as_posix(),
            "bytes": db.stat().st_size,
            "sha256": sha256_of(db),
        },
    }


def write_signal(db: Path, *, now=None, env=None) -> Path:
    signal = build_signal(db, now=now, env=env)
    out = db.parent / SIGNAL_NAME
    # Trailing newline: this file is committed, and a diff without one is noisy.
    out.write_text(json.dumps(signal, indent=2, sort_keys=True) + "\n")
    print(
        f"{out}: {SCHEMA} run={signal['run_id']} "
        f"latest_observation={signal['latest_observation']} "
        f"sha256={signal['timeseries']['sha256'][:12]}…"
    )
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"time-series database (default: {DEFAULT_DB})")
    args = parser.parse_args(argv)
    write_signal(args.db)


if __name__ == "__main__":
    sys.exit(main())
