#!/usr/bin/env python3
"""Measure one green run's time-series rows, and build the clean database (D4).

    # in the detect job, after replay_2026.py run, on the composites it pulled:
    python scripts/green_timeseries.py rows --out-dir <replay out-dir> \
        --output <replay out-dir>/timeseries_rows.json

    # anywhere, from rows documents only — no raster, no credential:
    python scripts/green_timeseries.py build --db <path>.db rows1.json [rows2.json ...]

``rows`` reads ``ledger.json`` (the run's sealed ledger), the baseline version
from ``composition_regimes.json`` and the algorithm version from the ledger,
and the composites under ``composites/``; it writes one JSON document.
``build`` writes the 2A.2 clean schema (``src/timeseries/schema.py``) and
refuses to write into the quarantined legacy database by name.

Neither contacts a store, a pointer, Git or Earth Engine, and neither imports
``config`` (``tests/test_assemble_green_run.py::GREEN_SCRIPTS``).  Where the
rows go after this — deposited beside the run, then merged and published by
pull request — is the lane's, not this script's (``src/timeseries/green_rows.py``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timeseries import green_rows as gr  # noqa: E402

#: Package 2A.2 quarantined it as a whole; a green build never writes into it.
LEGACY_DB_NAME = "timeseries.db"


def command_rows(args) -> int:
    out = Path(args.out_dir)
    ledger_path = out / "ledger.json"
    if not ledger_path.is_file():
        # replay_2026.py writes ledger.json only when every expected
        # acquisition is terminal; without it there is no sealed set to bind.
        raise SystemExit(f"{ledger_path} is absent: the run's ledger is not sealed")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    regimes = json.loads((out / "composition_regimes.json").read_text(encoding="utf-8"))
    document = gr.run_rows(
        ledger, out / "composites",
        baseline_version=regimes["baseline_version"],
        algorithm_version=ledger["algorithm_version"],
    )
    target = Path(args.output)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    kept = document["acquisitions"]
    print("generation : %s" % document["generation"]["generation_id"])
    print("rows       : %d date(s), %d accepted, %d rejected_quality"
          % (len(kept), sum(a["qa_status"] == "accepted" for a in kept),
             sum(a["qa_status"] == "rejected_quality" for a in kept)))
    print("superseded : %d; absent (failed): %d"
          % (len(document["superseded"]), len(document["absent"])))
    print("wrote      : %s" % target)
    return 0


def command_build(args) -> int:
    db = Path(args.db)
    if db.name == LEGACY_DB_NAME:
        raise SystemExit(f"refusing {db}: {LEGACY_DB_NAME} is the quarantined legacy series")
    documents = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.rows]
    counts = gr.apply_rows(db, documents)
    print("wrote %(acquisitions)d acquisition(s), %(regional_stats_v1)d row(s)" % counts
          + " into %s" % db)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rows = sub.add_parser("rows")
    rows.add_argument("--out-dir", required=True)
    rows.add_argument("--output", required=True)
    build = sub.add_parser("build")
    build.add_argument("--db", required=True)
    build.add_argument("rows", nargs="+")
    args = parser.parse_args(argv)
    return command_rows(args) if args.command == "rows" else command_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
