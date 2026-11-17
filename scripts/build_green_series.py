#!/usr/bin/env python3
"""Build the live release's green series, or list the chain runs that lack rows (D4B).

    # the series job: pointer -> live chain release -> its members' rows
    # documents -> a database built from empty, and its signal
    python scripts/build_green_series.py build --out-dir <dir> \
        --previous data/timeseries/GREEN_SERIES.json

    # the reconstruction's plan: the chain runs with no series/<run-id>/
    # document yet, oldest first, and each one's ledger
    python scripts/build_green_series.py missing --out-dir <dir> --max-runs 8

Both are **read-only**: the store is a ``ReadOnlyStore`` (no write is
expressible), it is the staging bucket or a refusal (``assert_staging_target``),
and nothing here imports ``config`` (``GREEN_SCRIPTS``).  ``build`` writes only
under ``--out-dir``; publishing the database is the next job's, by pull
request, with no bucket identity at all (``v2_green_timeseries.yml``).

``build`` follows the **pointer**, not the bucket's chain head: the page's
series is the promoted release's.  It refuses a member with no rows document
(``SeriesIncomplete``) instead of publishing a series with a hole, and says
``changed=false`` when the release and the database bytes are the ones already
published, so an unchanged series opens no pull request.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import atomic_publish as ap  # noqa: E402
from src.publication import conditional_store as cs  # noqa: E402
from src.publication import run_inputs as ri  # noqa: E402
from src.publication import state_chain as sc  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.ledger_binding import ContractBindingError  # noqa: E402
from src.timeseries import green_series as gs  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def build_reader() -> ri.ReadOnlyStore:
    """The candidate identity, unable to write through this object."""

    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    client = cs.build_client(
        bucket,
        os.environ.get(ENDPOINT_VAR),
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
    )
    return ri.ReadOnlyStore(client, bucket)


def emit(outputs: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for name, value in outputs.items():
                handle.write(f"{name}={value}\n")


def _json(store: cs.ConditionalStore, key: str) -> Any:
    return json.loads(store.require(key).body)


def list_series_run_ids(store: cs.ConditionalStore) -> list[str]:
    """Every ``series/<id>/`` prefix, following the cursor, or a refusal."""

    client = sc._listing_client(store)  # noqa: SLF001 - read-only listing
    ids: list[str] = []
    token = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": store.bucket, "Prefix": gs.SERIES_ROOT,
                                  "Delimiter": "/"}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for entry in page.get("CommonPrefixes") or ():
            segment = entry["Prefix"][len(gs.SERIES_ROOT):].rstrip("/")
            if segment:
                ids.append(segment)
        if not page.get("IsTruncated"):
            return sorted(set(ids))
        token = page.get("NextContinuationToken")
        if not token:
            raise gs.SeriesRejected(
                f"listing {gs.SERIES_ROOT} reported more results and returned no "
                "continuation token; a partial listing could hide a member's rows"
            )


def live_manifest(store: cs.ConditionalStore) -> dict[str, Any]:
    pointer, _ = ap.read_pointer(store)
    if pointer is None:
        raise gs.SeriesRejected("no green release has been promoted; there is no series")
    release_id = pointer["release_id"]
    manifest = _json(store, f"releases/{release_id}/release.json")
    if manifest.get("release_id") != release_id:
        raise gs.SeriesRejected(
            f"releases/{release_id}/release.json names {manifest.get('release_id')}"
        )
    return manifest


def read_documents(store: cs.ConditionalStore) -> list[dict[str, Any]]:
    documents = []
    for run_id in list_series_run_ids(store):
        stored = store.get(gs.series_key(run_id))
        if stored is not None:
            documents.append(json.loads(stored.body))
    return documents


def command_build(store, out_dir: Path, previous: Path | None) -> dict[str, str]:
    manifest = live_manifest(store)
    chosen = gs.select_documents(manifest, read_documents(store))
    out_dir.mkdir(parents=True, exist_ok=True)
    database = out_dir / gs.DATABASE_NAME
    counts = gs.build_database(database, chosen)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    signal = gs.build_signal(
        database,
        release_id=manifest["release_id"],
        documents=chosen,
        published_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_url=f"{server}/{repository}/actions/runs/{run}" if repository and run else None,
    )
    (out_dir / gs.SIGNAL_NAME).write_text(gs.dumps(signal), encoding="utf-8")
    published = None
    if previous is not None and previous.is_file():
        published = json.loads(previous.read_text(encoding="utf-8"))
    changed = not gs.unchanged(published, signal)
    series = signal["series"]
    print(f"release    : {manifest['release_id']} ({len(chosen)} member(s))")
    print(f"generation : {series['generation_id']}")
    print(f"series     : {series['acquisitions']} acquisition(s), {series['accepted']} "
          f"accepted, {series['first_observed_on']} .. {series['last_observed_on']}; "
          f"{counts['regional_stats_v1']} row(s)")
    print(f"database   : {signal['database']['sha256']}")
    print("changed    : %s" % ("yes" if changed else "no — the published series is this one"))
    return {"changed": "true" if changed else "false",
            "release_id": manifest["release_id"]}


def command_missing(store, out_dir: Path, max_runs: int) -> dict[str, str]:
    head = sc.resolve_head(store)
    missing = [run_id for run_id in head.path if store.get(gs.series_key(run_id)) is None]
    chosen = missing[:max_runs]
    out_dir.mkdir(parents=True, exist_ok=True)
    for run_id in chosen:
        target = out_dir / run_id
        target.mkdir()
        (target / "ledger.json").write_bytes(
            store.require(ri.run_key(run_id, "ledger.json")).body)
    (out_dir / "plan.json").write_text(
        gs.dumps({"chain": list(head.path), "missing": missing, "this_dispatch": chosen}),
        encoding="utf-8")
    print(f"chain      : {len(head.path)} run(s), {len(missing)} without rows")
    print(f"this time  : {', '.join(chosen) or 'nothing — every chain run has its rows'}")
    return {"count": str(len(chosen)), "remaining": str(len(missing) - len(chosen))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--out-dir", required=True)
    build.add_argument("--previous")
    missing = sub.add_parser("missing")
    missing.add_argument("--out-dir", required=True)
    missing.add_argument("--max-runs", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        store = build_reader()
        if args.command == "build":
            outputs = command_build(store, Path(args.out_dir),
                                    Path(args.previous) if args.previous else None)
        else:
            if args.max_runs < 1:
                raise gs.SeriesRejected("--max-runs must be at least 1")
            outputs = command_missing(store, Path(args.out_dir), args.max_runs)
    except (Rejected, ContractBindingError, gs.SeriesRejected, cs.ObjectStoreError,
            OSError, ValueError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding}", file=sys.stderr)
        return 1
    emit(outputs)
    print("read-only — nothing was written to the bucket")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
