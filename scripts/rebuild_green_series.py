#!/usr/bin/env python3
"""Re-measure the series rows of chain runs deposited before D4B (the reconstruction).

    python scripts/rebuild_green_series.py --plan-dir <dir> --out-dir <dir> \
        --service-account

The owner chose, on 2026-11-05, a series **from January** (option a of
``PHASE_D4_2026-11-03.md`` §7).  The runs deposited before the detect job
measured rows kept no composite, so this pulls again, as the green account and
exactly as the detection did (``replay_2026.pull_composite``), each composite
the series needs — every acquisition the run's ledger calls ``complete_*`` or
``rejected_quality`` — and measures it with the detect job's own code
(``green_rows.run_rows``).

What binds the result to the run: ``run_rows`` refuses an accepted composite
whose bytes do not hash to the ``artifact_sha256`` the ledger sealed.  So a
reconstruction either reproduces the pixels the detection used, byte for byte,
or stops.  Measured before this was written (``PHASE_D4B_2026-11-17.md`` §2):
Earth Engine returned the same bytes for one composite ten weeks apart, and a
local pull matched the hash a CI run had sealed.  If a pull ever stops
matching, this script fails and the decision returns to the owner — it never
re-seals, re-detects or writes a row it cannot bind.

One run at a time: its composites are pulled, measured and deleted before the
next run's, so the runner's disk holds one window.  It writes only under
``--out-dir``, holds no bucket identity (the workflow step has none), and
imports ``config`` through the detection's modules — which is why it is not in
``GREEN_SCRIPTS`` and why no step holding ``R2_STAGING_*`` runs it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.timeseries import green_rows as gr  # noqa: E402

#: The deposit lane's own defaults (``replay_2026.py``: ``--max-cloud 60``,
#: ``--baseline-version 2.1.0``); the generation id depends on the second.
MAX_CLOUD = 60
BASELINE_VERSION = "2.1.0"


def load_replay():
    spec = importlib.util.spec_from_file_location("replay_2026", ROOT / "scripts" / "replay_2026.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def to_pull(ledger: dict) -> list[dict]:
    """The acquisitions whose composite a series row needs, from the ledger."""

    expected = {item["acquisition_id"]: item for item in ledger["expected_acquisitions"]}
    return [
        {"observed_on": row["observed_on"], **expected[row["acquisition_id"]]}
        for row in ledger["terminal_rows"]
        if row["status"] in gr.IN_SERIES
    ]


def rebuild_run(replay, ee, export, ledger: dict, work: Path, *, baseline_version: str,
                workers: int) -> dict:
    composites = work / "composites"
    composites.mkdir(parents=True, exist_ok=True)
    try:
        for item in to_pull(ledger):
            day = date.fromisoformat(item["observed_on"])
            target = composites / gr.COMPOSITE_NAME.format(
                observed_on=item["observed_on"], datatake_id=item["datatake_id"])
            started = time.time()
            replay.pull_composite(ee, export, {"datatake_id": item["datatake_id"]}, target,
                                  start=day.isoformat(),
                                  end=(day + timedelta(days=1)).isoformat(),
                                  max_cloud=MAX_CLOUD, workers=workers)
            print("  pulled    %s %s  (%.0fs, %.0f MB)" % (
                item["observed_on"], item["datatake_id"], time.time() - started,
                target.stat().st_size / 1e6))
        return gr.run_rows(ledger, composites, baseline_version=baseline_version,
                           algorithm_version=ledger["algorithm_version"])
    finally:
        shutil.rmtree(composites, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--project", default="ee-araripe")
    parser.add_argument("--service-account", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    plan_dir, out_dir = Path(args.plan_dir), Path(args.out_dir)
    plan = json.loads((plan_dir / "plan.json").read_text(encoding="utf-8"))
    if not plan["this_dispatch"]:
        print("nothing to rebuild: every chain run has its rows")
        return 0

    from src.detection.baseline_selection import resolve_baseline
    baseline_version = resolve_baseline(BASELINE_VERSION).version
    replay = load_replay()
    import ee
    replay.initialize_earth_engine(ee, project=args.project,
                                   service_account=args.service_account)
    export = replay._load_export()  # noqa: SLF001 - the detection's own export module

    for run_id in plan["this_dispatch"]:
        ledger = json.loads((plan_dir / run_id / "ledger.json").read_text(encoding="utf-8"))
        print(f"{run_id}: {ledger['ledger_id']}, {len(to_pull(ledger))} composite(s)")
        try:
            document = rebuild_run(replay, ee, export, ledger, out_dir / run_id / "work",
                                   baseline_version=baseline_version, workers=args.workers)
        except gr.RowsRejected as exc:
            print(f"::error::{run_id}: {exc}. The pull does not reproduce what the "
                  "detection sealed; stop and take it to the owner.", file=sys.stderr)
            return 1
        target = out_dir / run_id / "timeseries_rows.json"
        target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        shutil.copyfile(plan_dir / run_id / "ledger.json", out_dir / run_id / "ledger.json")
        shutil.rmtree(out_dir / run_id / "work", ignore_errors=True)
        kept = document["acquisitions"]
        print(f"  rows      {len(kept)} date(s), "
              f"{sum(a['qa_status'] == 'accepted' for a in kept)} accepted; hashes bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
