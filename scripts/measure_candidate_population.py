#!/usr/bin/env python3
"""Characterise the Phase 4 candidate as a SAMPLING POPULATION — Phase 5 input.

    python scripts/measure_candidate_population.py \
        --alerts <dir with run-<date>.geojson and run-<date>.strong.geojson> \
        --out <population.json>

What this answers, and why each answer is a stratum weight rather than a count
--------------------------------------------------------------------------------
A design-based accuracy assessment needs ``W_h = area(stratum h) / area(region)``
for every stratum, because the estimators are area-weighted.  Three properties
of this map make the naive computation wrong, and each one is handled here:

1. **Summing per-date area double-counts.**  The same ground is detected on
   several dates as an event persists, so the mapped-change area is the
   **union** of the footprints, not the sum.  Measured: the sum is 2.7x the
   union.
2. **Area must be geodesic.**  The products are in EPSG:4326 and the extent is
   ~1.94 degrees wide; a planar area on degrees is not an area.  ``pyproj.Geod``
   on WGS84 throughout.
3. **The map's own class is not the stratum.**  A detection sitting on land that
   MapBiomas calls farming cannot be deforestation of natural vegetation, so
   land-cover group is carried as a stratifier and its union area reported
   separately.  The features already carry ``lc_group`` — annotated by the
   Package 2A.6 pipeline — so this is read, never recomputed.

It computes nothing scientific beyond areas and cross-tabulations: no accuracy,
no precision, no recall.  ``scientific_status`` in the output says so.

Why it reads the candidate from disk rather than from the store
---------------------------------------------------------------
The deposited prefix and the local assembly are byte-identical, verified in
``docs/implementation/PHASE_4C_2026-09-16.md`` §3 against three independent
sources.  Reading the local copy needs no credential at all, which keeps this
measurement outside the green lane entirely.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pyproj import Geod
from shapely.geometry import box, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.validation.sampling import (  # noqa: E402
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_ID,
)

GEOD = Geod(ellps="WGS84")
M2_PER_HA = 10_000.0

#: The pilot's own size bands, so Phase 5 strata are comparable to Phase 2A.3's.
#: Copied from src/validation/sampling.py::_polygon_size rather than invented.
SIZE_BANDS = (
    ("below_nominal_minimum", 0.0, 1.0),
    ("small_1_2ha", 1.0, 2.0),
    ("medium_2_5ha", 2.0, 5.0),
    ("large_5ha_plus", 5.0, float("inf")),
)


def geodesic_ha(geom) -> float:
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / M2_PER_HA


def size_band(area_ha) -> str:
    try:
        value = float(area_ha)
    except (TypeError, ValueError):
        return "unknown"
    for name, low, high in SIZE_BANDS:
        if low <= value < high:
            return name
    return "unknown"


def season(observed_on: str) -> str:
    """Wet Nov-Apr, dry May-Oct — the pilot's own split."""
    try:
        month = int(observed_on[5:7])
    except (TypeError, ValueError, IndexError):
        return "unknown"
    return "wet_nov_apr" if month in (11, 12, 1, 2, 3, 4) else "dry_may_oct"


def read_features(path: Path):
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a FeatureCollection")
    return doc.get("features") or []


def characterise(files: list[Path], extent_ha: float) -> dict:
    """Counts, cross-tabs and UNION areas, in one pass over the features."""

    counts: Counter = Counter()
    by: dict[str, Counter] = defaultdict(Counter)
    cross: Counter = Counter()
    per_date: dict[str, Counter] = defaultdict(Counter)
    geoms_by_group: dict[str, list] = defaultdict(list)
    all_geoms: list = []
    summed_ha = 0.0

    for path in files:
        for feat in read_features(path):
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            if geom is None:
                counts["without_geometry"] += 1
                continue
            g = shape(geom)
            group = str(props.get("lc_group") or "unknown")
            conf = str(props.get("confidence_label") or "unknown")
            pers = str(props.get("persistence_status") or "unknown")
            date = str(props.get("detection_date") or "unknown")
            ambiguous = bool(props.get("lineage_ambiguity_resolved"))
            band = size_band(props.get("area_ha"))

            counts["features"] += 1
            by["lc_group"][group] += 1
            by["confidence"][conf] += 1
            by["persistence"][pers] += 1
            by["size_band"][band] += 1
            by["season"][season(date)] += 1
            by["lineage_ambiguity_resolved"][str(ambiguous)] += 1
            cross[f"{conf}|{pers}"] += 1
            per_date[date]["features"] += 1
            if ambiguous:
                per_date[date]["lineage_ambiguity_resolved"] += 1

            summed_ha += geodesic_ha(g)
            geoms_by_group[group].append(g)
            all_geoms.append(g)

    union_all = unary_union(all_geoms) if all_geoms else None
    union_ha = geodesic_ha(union_all) if union_all is not None else 0.0

    group_union = {}
    for group, geoms in geoms_by_group.items():
        area = geodesic_ha(unary_union(geoms))
        group_union[group] = {
            "union_ha": round(area, 3),
            "share_of_extent": round(area / extent_ha, 8),
        }

    return {
        "counts": dict(counts),
        "by": {k: dict(v) for k, v in by.items()},
        "confidence_by_persistence": dict(cross),
        "per_date": {d: dict(c) for d, c in sorted(per_date.items())},
        "area": {
            "summed_ha": round(summed_ha, 3),
            "union_ha": round(union_ha, 3),
            "overlap_discarded_ha": round(summed_ha - union_ha, 3),
            "overlap_share_of_sum": (
                round((summed_ha - union_ha) / summed_ha, 6) if summed_ha else None
            ),
            "W_change": round(union_ha / extent_ha, 8),
            "W_nochange": round(1.0 - union_ha / extent_ha, 8),
        },
        "union_ha_by_lc_group": group_union,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alerts", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    extent = box(*MONITORING_EXTENT_BOUNDS)
    extent_ha = geodesic_ha(extent)

    strong = sorted(args.alerts.glob("*.strong.geojson"))
    full = [p for p in sorted(args.alerts.glob("*.geojson"))
            if not p.name.endswith(".strong.geojson")]
    if not strong or not full:
        print(f"erro: {args.alerts} has {len(full)} full and {len(strong)} strong "
              "product(s); expected both", file=sys.stderr)
        return 1

    document = {
        "schema": "araripe-phase5-candidate-population-v1",
        "scientific_status": "population_description_only",
        "claims": {
            "precision_estimate": False,
            "recall_estimate": False,
            "omission_estimate": False,
            "scientific_accuracy_claim": False,
            "area_of_change_estimate": False,
        },
        "monitoring_extent": {
            "id": MONITORING_EXTENT_ID,
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "geodesic_area_ha": round(extent_ha, 3),
            "area_method": "pyproj.Geod(ellps='WGS84').geometry_area_perimeter",
        },
        "products": {},
    }

    for label, files in (("full", full), ("strong", strong)):
        print(f"measuring {label} ({len(files)} file(s))…", file=sys.stderr)
        document["products"][label] = characterise(files, extent_ha)

    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
