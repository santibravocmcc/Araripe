#!/usr/bin/env python3
"""Sample size and allocation for the Phase 5 assessment, from measured weights.

    python scripts/plan_phase5_sample.py --population <population.json>

Arithmetic is ``src/validation/accuracy.py``, which reproduces the published
``n = 641`` of Olofsson et al. (2014) Table 5 under test.  This script only
supplies *our* stratum weights and the conjectured user's accuracies, and shows
the trade-off across the designs the owner has to choose between.

The conjectures are not guesses dressed as numbers — each one cites the
measurement that motivates it, and the whole point of printing several targets
is that the choice is the owner's, not this script's.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.validation.accuracy import (  # noqa: E402
    allocate_sample,
    sample_size_stratified,
)

#: Conjectured user's accuracies, with the measurement behind each.  §5.1.1:
#: "we should draw upon any past experience for insight into the accuracy of
#: the map to be produced".
CONJECTURES = {
    "strong_change": (
        0.70,
        "the paper's own conjecture for a deforestation class, and the strong "
        "subset sits 99.6% on MapBiomas-natural land",
    ),
    "weak_change": (
        0.30,
        "34.5% of the full detection set sits on MapBiomas-FARMING land, where "
        "deforestation of natural vegetation cannot occur; these also failed "
        "the strong filter",
    ),
    "nochange": (
        0.99,
        "stable classes are routinely the accurate ones (paper conjectures "
        "0.90-0.95); the no-change stratum here is 94% of the extent",
    ),
}

DOUBLE_REVIEW_FRACTION = 0.20  # inherited from the Package 2A.3 pilot


def designs(pop: dict) -> dict[str, dict[str, float]]:
    """The three candidate frames, with weights read from the measurement."""

    extent = pop["monitoring_extent"]["geodesic_area_ha"]
    strong = pop["products"]["strong"]["area"]["union_ha"]
    full = pop["products"]["full"]["area"]["union_ha"]
    weak = full - strong
    if weak <= 0:
        raise SystemExit("the full union is not larger than the strong union")
    return {
        "A. strong only, 2 strata": {
            "strong_change": strong / extent,
            "nochange": 1.0 - strong / extent,
        },
        "B. strong + weak + no-change, 3 strata": {
            "strong_change": strong / extent,
            "weak_change": weak / extent,
            "nochange": 1.0 - full / extent,
        },
        "C. full set as one change class, 2 strata": {
            "weak_change": full / extent,
            "nochange": 1.0 - full / extent,
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--population", required=True, type=Path)
    parser.add_argument(
        "--targets", type=float, nargs="+", default=[0.01, 0.015, 0.02],
        help="target standard errors of overall accuracy",
    )
    args = parser.parse_args(argv)

    pop = json.loads(args.population.read_text())
    extent = pop["monitoring_extent"]["geodesic_area_ha"]
    print(f"monitored extent : {extent:,.0f} ha")
    print("conjectured user's accuracies (each with its basis):")
    for name, (value, why) in CONJECTURES.items():
        print(f"  {name:<14} U = {value:.2f}   {why}")

    for label, weights in designs(pop).items():
        print(f"\n=== {label} ===")
        for s, w in weights.items():
            print(f"  W[{s:<13}] = {w:.6f}  ({100*w:6.3f}% of the extent)")
        conj = {s: CONJECTURES[s][0] for s in weights}
        change = [s for s in weights if s != "nochange"]
        for target in args.targets:
            n = sample_size_stratified(weights, conj, target)
            line = f"  S(O) <= {target:<5} -> n = {n:>5}"
            try:
                alloc = allocate_sample(weights, n, change, per_change_stratum=75)
                spread = "  ".join(f"{k}={v}" for k, v in sorted(alloc.items()))
                cases = n * (1.0 + DOUBLE_REVIEW_FRACTION)
                line += f"   [{spread}]   reviewer-cases ~{cases:,.0f}"
            except Exception as exc:  # the refusal is informative, not fatal
                line += f"   allocation refused: {exc}"
            print(line)
    print(
        "\nreviewer-cases include the pilot's 20% double review "
        f"({DOUBLE_REVIEW_FRACTION:.0%}), inherited from phase2a3-pilot-v1."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
