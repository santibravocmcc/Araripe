#!/usr/bin/env python3
"""Compare the replay candidate's per-date outcome with the blue product's.

    python scripts/compare_replay_to_blue.py --out-dir <isolated>

Why this exists
---------------
The replay is the first time 2026 has been processed against baseline
``2.1.0``, the generation the owner chose.  Blue processed the same year
against ``1.0.0``.  Where the two disagree about a date, the disagreement is
evidence about the generation — and it is exactly the input roadmap Phase 5
needs, because changing a rule is Phase 5's decision and not Phase 4's.

This is a **reproduction**, not a conclusion: it prints what each side says
about each date and leaves the reading to the document that cites it.

What it is careful about
------------------------
*The blue database is opened read-only*, through a SQLite URI with
``mode=ro``, so no code path here can write the product the site serves.  A
plain ``connect`` would create or modify it; this cannot.

*The two sides count different things, and that is stated rather than
hidden.*  Blue's ``alert_stats`` rows carry polygon counts and hectares for a
whole UTC date composed as one daily mosaic.  The replay accounts per physical
datatake and composes per datatake.  On a date with one datatake the two
populations are the same scenes; on a dual date they are not, and the report
says which is which so a reader never compares the incomparable by accident.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: The blue time-series product. Opened read-only, always.
BLUE_DB = "data/timeseries/timeseries.db"


def blue_rows(db_path: Path) -> dict[str, dict]:
    """Blue's per-date alert statistics, read-only."""

    uri = "file:%s?mode=ro" % db_path
    connection = sqlite3.connect(uri, uri=True)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "select date, total_alerts, total_area_ha from alert_stats "
            "where date like '2026-%' order by date"
        )
        return {
            row[0]: {"total_alerts": row[1], "total_area_ha": row[2]}
            for row in cursor.fetchall()
        }
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--blue-db", default=BLUE_DB)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    rows = json.loads((out / "terminal_rows.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "run_manifest_v3.json").read_text(encoding="utf-8"))
    by_datatake = {item["datatake_id"]: item for item in manifest["datatakes"]}
    datatakes_per_date = Counter(item["observed_on"] for item in manifest["datatakes"])

    # the replay's own view, per acquisition
    per_acq = []
    for row in rows:
        # the acquisition id does not carry the datatake, so recover it from
        # the manifest by timestamp: one datatake per (timestamp, date).
        matches = [
            item for item in manifest["datatakes"]
            if item["acquisition_timestamp_utc"] == row["acquisition_timestamp_utc"]
        ]
        datatake = matches[0] if len(matches) == 1 else None
        per_acq.append({
            "observed_on": row["observed_on"],
            "status": row["status"],
            "reason": (row.get("reason") or {}).get("message"),
            "observations": len((row["output"] or {}).get("observation_ids") or []),
            "datatake_id": datatake["datatake_id"] if datatake else None,
            "platform": datatake["platform"] if datatake else None,
            "processing_baselines": (
                datatake["observed_processing_baselines"] if datatake else None),
            "datatakes_on_this_date": datatakes_per_date[row["observed_on"]],
        })

    blue = blue_rows(Path(args.blue_db))

    # per-date comparison
    comparison = []
    for date in sorted({item["observed_on"] for item in per_acq}):
        mine = [item for item in per_acq if item["observed_on"] == date]
        accepted = [i for i in mine if i["status"].startswith("complete")]
        blue_row = blue.get(date)
        if accepted and blue_row:
            verdict = "both_accepted"
        elif accepted and not blue_row:
            verdict = "replay_only"
        elif not accepted and blue_row:
            verdict = "blue_only"
        else:
            verdict = "neither"
        comparison.append({
            "observed_on": date,
            "verdict": verdict,
            "datatakes_on_this_date": mine[0]["datatakes_on_this_date"],
            "replay_statuses": sorted(i["status"] for i in mine),
            "replay_observations": sum(i["observations"] for i in accepted),
            "replay_reasons": [i["reason"] for i in mine if i["reason"]],
            "blue_total_alerts": blue_row["total_alerts"] if blue_row else None,
            "blue_total_area_ha": blue_row["total_area_ha"] if blue_row else None,
            "processing_baselines": sorted({
                b for i in mine for b in (i["processing_baselines"] or [])
            }),
        })

    verdicts = Counter(item["verdict"] for item in comparison)
    print("dates compared : %d" % len(comparison))
    for key in ("both_accepted", "blue_only", "replay_only", "neither"):
        print("  %-14s : %d" % (key, verdicts.get(key, 0)))

    # the lineage question, on every acquisition the replay pulled and judged
    judged = [i for i in per_acq
              if i["status"] in ("complete_with_alerts", "complete_zero_alerts",
                                 "rejected_quality")]
    print()
    print("processing baseline against the gate outcome (pulled acquisitions only):")
    table: dict[tuple, Counter] = {}
    for item in judged:
        key = tuple(item["processing_baselines"] or ["unknown"])
        table.setdefault(key, Counter())[item["status"]] += 1
    for key in sorted(table):
        print("  %-12s %s" % ("/".join(key), dict(table[key])))

    # The confound, printed here rather than left to prose. If a processing
    # baseline occupies only one part of the year, then "lineage" and "season"
    # name the same set of acquisitions and this data cannot tell them apart.
    # Saying so in the output stops the table above from being read as a
    # lineage effect it does not establish.
    months_by_baseline: dict[str, Counter] = {}
    for item in per_acq:
        for label in (item["processing_baselines"] or ["unknown"]):
            months_by_baseline.setdefault(label, Counter())[item["observed_on"][:7]] += 1
    print()
    print("the confound — which months each processing baseline occupies:")
    for label in sorted(months_by_baseline):
        spread = dict(sorted(months_by_baseline[label].items()))
        print("  %-12s %s" % (label, spread))
    # State the overlap as a measurement rather than as a verdict. The first
    # version of this block asserted "the baselines do not share months" while
    # 05.11 and 05.12 both carried February — it tested for a shared month
    # count above one instead of above zero, and printed a false conclusion
    # from true data. Print the shared months and let the reader judge.
    labels = sorted(months_by_baseline)
    shared_pairs = []
    for i, left in enumerate(labels):
        for right in labels[i + 1:]:
            shared = sorted(
                set(months_by_baseline[left]) & set(months_by_baseline[right])
            )
            shared_pairs.append((left, right, shared))
    for left, right, shared in shared_pairs:
        if shared:
            print("  %s and %s share %s" % (left, right, ", ".join(shared)))
        else:
            print("  %s and %s share no month" % (left, right))
    if shared_pairs and all(len(shared) <= 1 for _, _, shared in shared_pairs):
        print("  -> the baselines are near-collinear with the calendar, so the")
        print("     table above CANNOT be read as a lineage effect.")

    print()
    print("dates blue accepted and the replay rejected:")
    for item in comparison:
        if item["verdict"] == "blue_only":
            print("  %s  blue %6d alerts / %10.1f ha | replay %s | baseline %s"
                  % (item["observed_on"], item["blue_total_alerts"],
                     item["blue_total_area_ha"], ",".join(item["replay_statuses"]),
                     "/".join(item["processing_baselines"])))

    print()
    print("dates both accepted — replay observations against blue polygons:")
    for item in comparison:
        if item["verdict"] == "both_accepted":
            print("  %s  replay %6d | blue %6d | %d datatake(s) | baseline %s"
                  % (item["observed_on"], item["replay_observations"],
                     item["blue_total_alerts"], item["datatakes_on_this_date"],
                     "/".join(item["processing_baselines"])))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({
                "comparison": comparison,
                "verdict_counts": dict(verdicts),
                "baseline_against_outcome": {
                    "/".join(k): dict(v) for k, v in sorted(table.items())
                },
                "months_by_processing_baseline": {
                    k: dict(sorted(v.items()))
                    for k, v in sorted(months_by_baseline.items())
                },
                "shared_months_between_processing_baselines": {
                    "%s|%s" % (left, right): shared
                    for left, right, shared in shared_pairs
                },
                "confound": (
                    "a processing baseline that occupies only part of the year "
                    "is not separable from the season it occupies; check "
                    "shared_months_between_processing_baselines before reading "
                    "baseline_against_outcome as a lineage effect"
                ),
                "caveat": (
                    "blue counts polygons for a whole UTC date composed as one "
                    "daily mosaic against baseline 1.0.0; the replay counts "
                    "observations per physical datatake composed per datatake "
                    "against 2.1.0. On a single-datatake date the scene "
                    "population is the same and the generation is the variable; "
                    "on a dual date it is not."
                ),
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("\nwrote %s" % args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
