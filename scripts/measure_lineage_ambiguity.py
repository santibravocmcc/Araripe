#!/usr/bin/env python3
"""Measure the ambiguous-lineage tangles that block the replay, per date.

    python scripts/measure_lineage_ambiguity.py --out-dir <isolated> --date 2026-04-07

Why this exists
---------------
``update_tracks`` fails closed on a many-to-many split/merge component
(``AmbiguousLineageError``), and when it does the replay discards the **whole
date**.  ``docs/implementation/PHASE_4B_2026-09-09.md`` §15 establishes that no
value of ``min_overlap_frac`` avoids this.  The owner then has to choose a
resolution rule, and that choice needs one number nobody had measured: **how
much of a date is actually inside an ambiguous tangle.**

This reconstructs the exact graph the guard builds — same spatial join, same
``intersection / current_area`` fraction, same threshold, same eligibility
(``active & (established | recent)``) — and reports the connected components
that trip it.

Why the reconstruction can be trusted, and how that was established
-------------------------------------------------------------------
By a **negative control**, because a method that only ever answers "ambiguous"
would be worthless.  Run against the state each date really saw, it agrees with
the live ``update_tracks`` on every date tested, in both directions:

=============  ==============  ==================  ==========================
date           the real run    this reconstruction polygons (real == rebuilt)
=============  ==============  ==================  ==========================
2026-03-13     **passed**      0 ambiguous          6839 == 6839
2026-04-04     **passed**      0 ambiguous          7726 == 7726
2026-04-07     refused         14 ambiguous         8566
2026-04-17     refused         3 ambiguous         10299
2026-05-02     refused         19 ambiguous        15313
2026-06-21     refused         15 ambiguous        19086
2026-08-30     refused         3 ambiguous          7021
=============  ==============  ==================  ==========================

Two traps this script exists to not repeat
------------------------------------------
* **The baseline month must come from the date.**  A first version hardcoded
  month 4 for every date; 2026-08-30 then produced 4397 polygons instead of
  7021 and reported *zero* ambiguous components for a date the real run
  refused.  The month is derived from the date and printed.
* **The state must be the one that date really saw.**  Only dates strictly
  before the target contribute, so a date that succeeded is reconstructed
  against the state it actually had rather than a later one.

Read-only: it reads the replay's own outputs and composites and writes nothing
but its report.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Dates whose alert features the replay saved, in chronological order. Only
#: those strictly before the target are replayed into the state.
CHAINED_DATES = ("2026-02-11", "2026-03-13", "2026-04-04")


def build_state(out: Path, target: str, threshold: float, datatakes):
    import geopandas as gpd
    from config.settings import DETECTION_ALGORITHM_VERSION, MONITORING_EXTENT_ID
    from src.detection.identity import create_acquisition_identity
    from src.detection.persistence import update_tracks
    from src.replay.composition_unit import load_decision

    method = load_decision().composite_method_id
    contributing = [d for d in CHAINED_DATES if d < target]
    print("state built from : %s" % (contributing or "nothing (empty state)"))
    state = None
    for date in contributing:
        frame = gpd.read_file(out / "alerts" / ("alerts_%s.geojson" % date))
        acquisition = create_acquisition_identity(
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            observed_on=date,
            scene_ids=sorted(s for d in datatakes[date] for s in d["scene_ids"]),
            monitoring_extent_id=MONITORING_EXTENT_ID,
            composite_method_id=method,
        )
        _, state = update_tracks(
            frame, state, date, acquisition=acquisition,
            algorithm_version=DETECTION_ALGORITHM_VERSION,
            baseline_version="2.1.0",
            monitoring_extent_id=MONITORING_EXTENT_ID, mode="rebuild",
            min_overlap_frac=threshold)
    return state


def polygons_for(out: Path, target: str, datatakes) -> "object":
    """Re-derive one date's alert polygons from the composite already on disk."""

    from src.detection.alerts import vectorize_alerts
    from src.detection.baseline import load_baseline_pair
    from src.detection.baseline_selection import resolve_baseline
    from src.detection.change_detect import detect_deforestation
    from scripts.run_detection_from_gee import INDICES, _load_composite

    present = [
        d for d in datatakes[target]
        if (out / "composites"
            / ("araripe_detect_%s_%s.tif" % (target, d["datatake_id"]))).exists()
    ]
    if len(present) != 1:
        raise SystemExit(
            "expected exactly one pulled composite for %s, found %d: %s"
            % (target, len(present), [d["datatake_id"] for d in datatakes[target]]))
    datatake = present[0]
    path = out / "composites" / (
        "araripe_detect_%s_%s.tif" % (target, datatake["datatake_id"]))

    indices, _ = _load_composite(path)
    reference = indices[list(indices.data_vars)[0]]
    # THE MONTH COMES FROM THE DATE. A hardcoded month silently produced the
    # wrong polygons and a false "zero ambiguous" for an August date.
    month = int(target[5:7])
    baseline = resolve_baseline("2.1.0")
    means, stds = {}, {}
    for name in INDICES:
        if name not in indices:
            continue
        try:
            mean, std = load_baseline_pair(name, month, generation=baseline)
        except FileNotFoundError:
            continue
        means[name] = mean.reindex_like(reference, method="nearest", tolerance=15)
        stds[name] = std.reindex_like(reference, method="nearest", tolerance=15)
    detection = detect_deforestation(indices, means, stds, spi_3month=None)
    frame = vectorize_alerts(detection["confidence"])
    print("%s        : %d polygon(s) (baseline month %02d, datatake %s)"
          % (target, len(frame), month, datatake["datatake_id"]))
    return frame


def ambiguous_components(state, current, target: str, threshold: float):
    """The guard's own graph, and the components that trip it."""

    import numpy as np
    import geopandas as gpd
    from src.detection.persistence import (
        CONFIRMED_MIN, GRACE_DAYS, _days_between,
    )

    tracks = state.to_crs("EPSG:32724").reset_index(drop=True)
    active = tracks["status"].to_numpy() == "active"
    established = tracks["n_sightings"].to_numpy() >= CONFIRMED_MIN
    recent = np.array([
        0 <= _days_between(target, str(value)) <= GRACE_DAYS
        for value in tracks["last_seen"]
    ])
    eligible = active & (established | recent)
    print("eligible tracks  : %d of %d" % (int(eligible.sum()), len(tracks)))

    metric = current.to_crs("EPSG:32724").reset_index(drop=True)
    area = metric.geometry.area.to_numpy()
    indices = np.where(eligible)[0]
    right = gpd.GeoDataFrame(
        {"__event": indices},
        geometry=[tracks.geometry.values[i] for i in indices], crs=metric.crs)
    left = gpd.GeoDataFrame(
        {"__current": np.arange(len(metric))},
        geometry=list(metric.geometry), crs=metric.crs)
    joined = gpd.sjoin(left, right, predicate="intersects", how="inner")
    overlap = np.array([
        a.intersection(b).area for a, b in zip(
            joined.geometry.values,
            right.geometry.values[joined["index_right"].to_numpy()])
    ])
    current_indices = joined["__current"].to_numpy()
    fraction = np.where(area[current_indices] > 0,
                        overlap / area[current_indices], 0.0)

    parents = defaultdict(set)
    children = defaultdict(set)
    for c, e, f in zip(current_indices, joined["__event"].to_numpy(), fraction):
        if f < threshold:
            continue
        parents[int(c)].add(int(e))
        children[int(e)].add(int(c))

    seen, components = set(), []
    for start in parents:
        if start in seen:
            continue
        cs, ps, stack = set(), set(), [("c", start)]
        while stack:
            kind, node = stack.pop()
            if kind == "c":
                if node in cs:
                    continue
                cs.add(node)
                stack.extend(("p", e) for e in parents[node])
            else:
                if node in ps:
                    continue
                ps.add(node)
                stack.extend(("c", c) for c in children[node])
        seen |= cs
        components.append((cs, ps))

    tangles = [
        (cs, ps) for cs, ps in components
        if any(len(parents[c]) > 1 for c in cs)
        and any(len(children[p]) > 1 for p in ps)
    ]
    return metric, parents, components, tangles


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--min-overlap-frac", type=float, default=None,
                        help="default: the owner's recorded decision")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    threshold = args.min_overlap_frac
    if threshold is None:
        from src.replay.overlap_decision import load_decision
        threshold = load_decision().min_overlap_fraction
    print("overlap threshold: %s" % threshold)

    manifest = json.loads((out / "run_manifest_v3.json").read_text(encoding="utf-8"))
    datatakes = defaultdict(list)
    for item in manifest["datatakes"]:
        datatakes[item["observed_on"]].append(item)

    state = build_state(out, args.date, threshold, datatakes)
    if state is None:
        raise SystemExit(
            "no date precedes %s, so the state is empty and no lineage graph "
            "exists; the guard cannot trip" % args.date)
    current = polygons_for(out, args.date, datatakes)
    metric, parents, components, tangles = ambiguous_components(
        state, current, args.date, threshold)

    inside = sum(len(cs) for cs, _ in tangles)
    events = sum(len(ps) for _, ps in tangles)
    shapes = Counter((len(cs), len(ps)) for cs, ps in tangles)
    print("with >1 parent   : %d" % sum(1 for v in parents.values() if len(v) > 1))
    print("components       : %d total, %d AMBIGUOUS" % (len(components), len(tangles)))
    for (new, old), count in shapes.most_common():
        print("   %d new x %d old : %d component(s)" % (new, old, count))
    print("polygons in them : %d of %d (%.2f%%)"
          % (inside, len(metric), 100 * inside / max(len(metric), 1)))
    print("old events in them: %d" % events)
    print("VERDICT          : %s"
          % ("the guard WOULD trip on this date" if tangles
             else "the guard would NOT trip on this date"))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "observed_on": args.date,
            "min_overlap_fraction": repr(threshold),
            "polygons": len(metric),
            "components": len(components),
            "ambiguous_components": len(tangles),
            "component_shapes": {"%dx%d" % k: v for k, v in sorted(shapes.items())},
            "polygons_inside_ambiguous": inside,
            "old_events_inside_ambiguous": events,
            "guard_would_trip": bool(tangles),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote            : %s" % args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
