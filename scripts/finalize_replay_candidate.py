#!/usr/bin/env python3
"""Turn a finished replay out-dir into a candidate, and record what it is.

    python scripts/finalize_replay_candidate.py \
        --out-dir <isolated> --run <run-id>

What this closes, in the order the steps depend on each other
-------------------------------------------------------------
``scripts/replay_2026.py`` produces the ledger; this produces everything that
can only be computed *after* it exists:

1. **The cutoff, resolved and fixed as a literal.**  ``resolve_recorded_cutoff``
   takes the dates a ledger declares fully terminal.  Before the replay those
   dates do not exist, and the blue time-series database is not a substitute:
   it is the blue product and knows only the dates blue processed.  So the
   cutoff is resolved here, against this replay's own ledger, and written as a
   literal date into the execution record.
2. **Roadmap bullet 8** — persistence tiers, strong subsets, statistics and
   clean 2026 time-series rows, regenerated from the alert features the replay
   wrote.  Every number comes from ``src.publication.site_artifact``, which is
   the authority that decides what a strong feature is and what a run's
   statistics are; nothing here re-decides either.
3. **The post-cutoff queue**, built with the cutoff resolved in step 1.
4. **The assembly**, through ``src.publication.run_assembler.assemble_run`` —
   the same library ``scripts/assemble_green_run.py`` calls, so a run that
   assembles here is the run that lane would deposit.

What it never touches
---------------------
Production.  It writes only under ``--out-dir``.  The regenerated time-series
rows go to a SQLite file *inside* ``--out-dir`` and the script refuses a
database path outside it — the blue database at ``data/timeseries/timeseries.db``
is the blue product, and a replay writing into it would rewrite history the
site serves.  The isolation is checked against ``--out-dir`` rather than
against the blue path so it needs no ``config.settings``, and therefore never
loads the production ``.env`` to prove it.

It contacts no object store and needs no credential: assembly runs in the
library, and depositing the result is a separate authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Where the regenerated 2026 time-series rows go.  Inside the out-dir, always.
REPLAY_DB_NAME = "timeseries_replay.db"

#: The strong subset of each date, written beside the full alerts.
STRONG_SUFFIX = ".strong.geojson"


class FinalizeError(RuntimeError):
    """The replay's outputs cannot support the step being asked for."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def require_inside(path: Path, root: Path, *, label: str) -> Path:
    """Refuse a path that is not under ``root``.

    The one write this script performs that could reach a production product is
    the time-series database, so the containment is checked rather than
    documented.  ``resolve`` first: ``out/../data/timeseries/timeseries.db`` is
    outside, and a string prefix test would call it inside.
    """

    resolved = Path(path).resolve()
    base = Path(root).resolve()
    if resolved != base and base not in resolved.parents:
        raise FinalizeError(
            f"{label} {resolved} is not under the isolated out-dir {base}; a "
            "replay writes only where it was told to"
        )
    return resolved


def load_assembler_cli():
    """The lane-2 entry point, loaded as a module.

    Its ``collect_features`` is reused rather than reimplemented, and that is
    a correctness decision and not tidiness: it distinguishes an ``alerts``
    date with no file (left absent, so the assembler refuses) from a
    ``zero_alerts`` date with no file (``[]``, a positive observation of
    absence). A loop that mapped every missing file to ``[]`` would turn a
    detection that failed to write into a published claim that the day was
    quiet — which is the defect that function's own docstring records.

    It is a script rather than a package module, so it loads the way
    ``replay_2026.py`` loads the export: by path. It deliberately does not
    import ``config.settings``, so loading it does not read the production
    ``.env``.
    """

    import importlib.util
    path = Path(__file__).resolve().parent / "assemble_green_run.py"
    spec = importlib.util.spec_from_file_location("assemble_green_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(args) -> int:
    from src.publication import site_artifact
    from src.publication import run_assembler as ra
    from src.publication.ledger_gate import check_processing_ledger
    from src.replay.cutoff import build_queue, resolve_recorded_cutoff

    out = Path(args.out_dir).resolve()
    ledger_path = out / "ledger.json"
    if not ledger_path.exists():
        raise FinalizeError(
            f"{ledger_path} does not exist. The ledger is written only by the "
            "batch that makes every expected acquisition terminal, so the "
            "replay is not finished and the cutoff cannot be resolved yet."
        )
    ledger_document = json.loads(ledger_path.read_text(encoding="utf-8"))

    # ── 1. the gate, then the cutoff it makes resolvable ────────────────────
    acceptance = check_processing_ledger(ledger_document)
    reconciled = list(acceptance.observed_dates)
    cutoff = resolve_recorded_cutoff(
        terminal_dates=reconciled, asked_at_utc=_utc_now()
    )
    print("ledger        : %s" % acceptance.ledger_id)
    print("expected      : %d acquisition(s)" % acceptance.expected_acquisition_count)
    print("reconciled    : %d date(s)" % len(reconciled))
    print("CUTOFF LITERAL: %s  (rule %s, inclusive on the batch side)"
          % (cutoff["date"], cutoff["rule_id"]))

    states = ra.dates_by_state(acceptance)

    # ── 2. bullet 8, from the features the replay wrote ─────────────────────
    alerts_dir = out / "alerts"
    db_path = require_inside(out / REPLAY_DB_NAME, out, label="time-series database")

    assembler_cli = load_assembler_cli()
    features_by_date = assembler_cli.collect_features(alerts_dir, states)

    per_date_statistics: dict[str, dict] = {}
    strong_written: dict[str, int] = {}
    for observed_on in sorted(features_by_date):
        features = features_by_date[observed_on]
        if not features:
            # A positive observation of absence still gets a statistics row of
            # zeros further down; it has no strong subset to write.
            continue
        per_date_statistics[observed_on] = site_artifact.run_statistics(features)
        strong = site_artifact.strong_features(features)
        strong_written[observed_on] = len(strong)
        (alerts_dir / ("alerts_%s%s" % (observed_on, STRONG_SUFFIX))).write_text(
            json.dumps({"type": "FeatureCollection", "features": strong},
                       sort_keys=True) + "\n", encoding="utf-8")

    # the clean 2026 time-series rows, into the ISOLATED database
    from src.detection.alerts import summarize_alerts  # noqa: E402
    from src.timeseries.builder import store_alert_stats  # noqa: E402
    import geopandas as gpd  # noqa: E402

    rows = 0
    for observed_on in sorted(per_date_statistics):
        source = alerts_dir / ("alerts_%s.geojson" % observed_on)
        frame = gpd.read_file(source)
        store_alert_stats(observed_on, summarize_alerts(frame), db_path=db_path)
        rows += 1
    print("bullet 8      : %d date(s) with features, %d time-series row(s) -> %s"
          % (len(per_date_statistics), rows, db_path.name))
    print("strong subsets: %d date(s) written"
          % len([k for k, v in strong_written.items()]))

    # ── 3. the post-cutoff queue, with the cutoff just resolved ─────────────
    manifest = json.loads((out / "run_manifest_v3.json").read_text(encoding="utf-8"))
    enumerated = sorted(manifest["exported_dates"])
    source = (
        "the Phase 4 replay's own Earth Engine enumeration of every physical "
        "datatake in %s..%s exclusive, run manifest %s"
        % (manifest["query"]["start"], manifest["query"]["end_exclusive"],
           manifest["run_manifest_id"])
    )
    # The replay's own window stops at the cutoff, so on its own it can only
    # produce an EMPTY queue — not because nothing is queued, but because it
    # never looked past the cutoff. Phase 3 recorded the same shape for the
    # blue database and marked its batch side non-authoritative. A second
    # enumeration of the post-cutoff window, produced by `replay_2026.py plan`
    # into a separate directory, is what makes the queued side measured.
    post = None
    if args.post_cutoff_dates:
        post = json.loads(Path(args.post_cutoff_dates).read_text(encoding="utf-8"))
        extra = sorted(set(post["dates"]) - set(enumerated))
        enumerated = sorted(set(enumerated) | set(post["dates"]))
        source = source + "; extended past the cutoff by %s (%d date(s) beyond the replay window)" % (post["source"], len(extra))
    queue = build_queue(
        cutoff=cutoff["date"],
        observed_dates=enumerated,
        observation_source=source,
        cutoff_is_provisional=False,
        cutoff_evidence={
            "resolved_from": "the ledger this replay produced",
            "ledger_id": acceptance.ledger_id,
            "terminal_date_count": cutoff["terminal_date_count"],
            "earliest_terminal_date": cutoff["earliest_terminal_date"],
            "resolved_at_utc": cutoff["resolved_at_utc"],
        },
    )
    print("queue         : %d in batch, %d queued after the cutoff%s"
          % (queue["in_batch"]["count"], queue["queued"]["count"],
             "" if post else "  (post-cutoff window NOT enumerated)"))

    # ── 4. the assembly, in the library the deposit lane calls ──────────────
    state_path = Path(args.state_path) if args.state_path else out / "persistence_state.geojson"
    import hashlib
    state_bytes = state_path.read_bytes()
    state_sha = hashlib.sha256(state_bytes).hexdigest()
    run = ra.assemble_run(
        args.run, ledger_document, features_by_date,
        persistence_state_sha256=state_sha,
        persistence_state_bytes=len(state_bytes),
    )
    print()
    print(ra.describe(run))
    print()

    # ── the execution record ────────────────────────────────────────────────
    regimes_path = out / "composition_regimes.json"
    record = {
        "schema": "araripe-phase4-execution-record-v1",
        "written_at_utc": _utc_now(),
        "out_dir_is_not_recorded_here": (
            "the isolated working directory is deliberately not written into "
            "any committed document; AGENTS.md forbids machine-specific "
            "absolute paths in the repository"
        ),
        "run_id": args.run,
        "ledger": {
            "ledger_id": acceptance.ledger_id,
            "run_manifest_id": acceptance.run_manifest_id,
            "run_manifest_sha256": acceptance.run_manifest_sha256,
            "document_sha256": acceptance.document_sha256,
            "contract_version": acceptance.contract_version,
            "algorithm_version": acceptance.algorithm_version,
            "monitoring_extent_id": acceptance.monitoring_extent_id,
            "expected_acquisition_count": acceptance.expected_acquisition_count,
        },
        "cutoff": cutoff,
        "seasonal_composition_regimes": (
            json.loads(regimes_path.read_text(encoding="utf-8"))
            if regimes_path.exists() else None
        ),
        "reconciliation": {
            "reconciled_date_count": len(reconciled),
            "dates_by_alert_state": states,
        },
        "bullet_8": {
            "dates_with_features": sorted(per_date_statistics),
            "per_date_statistics": per_date_statistics,
            "strong_feature_counts": strong_written,
            "timeseries_rows_written": rows,
            "timeseries_database": REPLAY_DB_NAME,
            "database_is_isolated_from_blue": True,
        },
        "post_cutoff_queue": queue,
        "post_cutoff_window_enumerated": bool(post),
        "assembly": {
            "run_schema": run.document["schema"],
            "object_count": len(run.document["objects"]),
            "persistence_state_sha256": state_sha,
            "persistence_state_bytes": len(state_bytes),
        },
    }
    (out / "execution_record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "run_document.json").write_text(
        json.dumps(run.document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote         : execution_record.json, run_document.json")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", required=True,
                        help="the replay's isolated output directory")
    parser.add_argument("--run", required=True,
                        help="the run id; one path segment")
    parser.add_argument("--state-path", default=None,
                        help="the persistence state (default: <out-dir>/persistence_state.geojson)")
    parser.add_argument("--post-cutoff-dates", default=None,
                        help='JSON {"dates": [...], "source": "..."} measuring the '
                             "window after the cutoff; without it the queued side is "
                             "unmeasured rather than empty")
    args = parser.parse_args(argv)
    try:
        return command(args)
    except FinalizeError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
