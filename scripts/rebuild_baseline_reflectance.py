"""Resilient orchestrator: rebuild the full 12-month baseline in reflectance.

Runs build_baseline.py once PER MONTH as an isolated subprocess (so memory is
freed between months and a hung month can be killed and retried), for the
year set {2017,2019,2021,2022,2025}. Each month is retried several times; each
build_baseline run already has per-scene timeouts/retries and GDAL HTTP
timeouts, so a throttled S3 read is skipped rather than blocking forever.

Idempotent/resumable: a month is "done" when all 3 indices have mean+std COGs in
the output dir, and done months are skipped — so re-running continues where it
left off. Builds into a SEPARATE dir (data/baselines_reflectance/) so the live
DN baselines keep working until an explicit swap.

After all 72 files exist: back up the DN baselines, move the reflectance ones
into data/baselines/, and set REFLECTANCE_SCALING=True (the coupling — done
manually/after verification, NOT by this script).

Usage:
    python scripts/rebuild_baseline_reflectance.py
    python scripts/rebuild_baseline_reflectance.py --out data/baselines_reflectance \
        --year-set 2017,2019,2021,2022,2025 --attempts 4 --month-timeout 7200
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDICES = ["ndmi", "nbr", "evi2"]


def month_files(out: Path, m: int) -> list[Path]:
    return [out / f"{ix}_month{m:02d}_{k}.tif" for ix in INDICES for k in ("mean", "std")]


def month_done(out: Path, m: int) -> bool:
    return all(p.exists() for p in month_files(out, m))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines_reflectance"))
    ap.add_argument("--year-set", default="2017,2019,2021,2022,2025")
    ap.add_argument("--months", default="1,2,3,4,5,6,7,8,9,10,11,12")
    ap.add_argument("--indices", default="ndmi,nbr,evi2")
    ap.add_argument("--attempts", type=int, default=4, help="Attempts per month.")
    ap.add_argument("--month-timeout", type=float, default=7200.0,
                    help="Wall-clock backstop per month attempt (s).")
    ap.add_argument("--scene-timeout", type=float, default=240.0)
    ap.add_argument("--min-clear", type=float, default=20.0)
    ap.add_argument("--max-cloud", type=int, default=30)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    months = [int(x) for x in args.months.split(",") if x.strip()]

    # Aggressive GDAL timeouts inherited by the subprocesses.
    env = dict(os.environ)
    env.setdefault("GDAL_HTTP_TIMEOUT", "60")
    env.setdefault("GDAL_HTTP_MAX_RETRY", "5")
    env.setdefault("GDAL_HTTP_RETRY_DELAY", "3")

    t_start = time.time()
    print(f"[orchestrator] out={out} year_set={args.year_set} months={months}", flush=True)

    for m in months:
        if month_done(out, m):
            print(f"[month {m:02d}] already complete — skipping", flush=True)
            continue
        for attempt in range(1, args.attempts + 1):
            elapsed_h = (time.time() - t_start) / 3600
            print(f"[month {m:02d}] attempt {attempt}/{args.attempts} "
                  f"(elapsed {elapsed_h:.2f}h)", flush=True)
            cmd = [
                sys.executable, str(ROOT / "scripts" / "build_baseline.py"),
                "--year-set", args.year_set,
                "--months", str(m),
                "--indices", args.indices,
                "--min-clear", str(args.min_clear),
                "--max-cloud", str(args.max_cloud),
                "--min-free-gb", "3",
                "--reflectance",
                "--scene-timeout", str(args.scene_timeout),
                "--scene-retries", "2",
                "--output-dir", str(out),
            ]
            try:
                subprocess.run(cmd, cwd=str(ROOT), env=env,
                               timeout=args.month_timeout, check=False)
            except subprocess.TimeoutExpired:
                print(f"[month {m:02d}] attempt {attempt} hit "
                      f"{args.month_timeout:.0f}s wall backstop; killed", flush=True)
            if month_done(out, m):
                print(f"[month {m:02d}] DONE", flush=True)
                break
            print(f"[month {m:02d}] incomplete after attempt {attempt}; "
                  f"pausing before retry", flush=True)
            time.sleep(20)
        if not month_done(out, m):
            print(f"[month {m:02d}] STILL INCOMPLETE after {args.attempts} attempts",
                  flush=True)

    done = sum(month_done(out, m) for m in months)
    n_files = len(glob.glob(str(out / "*.tif")))
    total_h = (time.time() - t_start) / 3600
    print(f"[orchestrator] COMPLETE: {done}/{len(months)} months, {n_files} .tif files, "
          f"{total_h:.2f}h total", flush=True)
    print("[orchestrator] Next (manual, after verifying reflectance scale): "
          "back up data/baselines, move reflectance COGs in, set "
          "REFLECTANCE_SCALING=True.", flush=True)
    return 0 if done == len(months) else 3


if __name__ == "__main__":
    sys.exit(main())
