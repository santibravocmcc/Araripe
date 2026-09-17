"""Design-based accuracy and area estimation — the Phase 5 arithmetic.

Every estimator here is from **Olofsson, Foody, Herold, Stehman, Woodcock &
Wulder (2014), "Good practices for estimating area and assessing accuracy of
land change", Remote Sensing of Environment 148:42-57,
https://doi.org/10.1016/j.rse.2014.02.015**, and each function names the
equation it implements.  The roadmap's Phase 5 bullet asks for precision,
recall, commission, omission, stratum results *and uncertainty*; a number
without an interval does not survive peer review, so the variance estimators
are not optional companions — they are the deliverable.

Why this module exists rather than a formula in prose
-----------------------------------------------------
A weighted estimator is exactly the kind of code that looks right with
plausible numbers.  ``tests/test_accuracy_estimators.py`` therefore anchors it
on the **published worked example**: Table 5 of the paper, whose inputs yield
*n* = 641, and Table 6/7's hypothetical error matrix.  Reproducing a number
someone else printed is a stronger check than any invariant this file could
assert about itself.

The constraint that decides the sampling unit — quoted, because it is easy to
read past
-----------------------------------------------------------------------------
    "These variance estimators are also based on assumptions that the
    assessment unit for the response design is a pixel and each pixel has a
    hard classification for the map and a hard classification for the
    reference data.  The variance estimators would not apply to a polygon
    assessment unit or to a mixed pixel situation."  — §4.3

The Package 2A.3 pilot sampled **alert polygons**.  Its labels are therefore
not inputs to these estimators, and that is a property of the design, not a
defect of the pilot: the pilot's own manifest declares
``precision_estimate: false``.  Phase 5 needs an **area/pixel** assessment
unit for anything it intends to publish with a confidence interval.

What this module does NOT do
----------------------------
It does not sample, does not label, does not decide strata, and does not know
what the Araripe candidate is.  It is arithmetic over an error matrix and a
set of stratum weights, so it can be tested with no data at all.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

__all__ = [
    "AccuracyEstimate",
    "AreaEstimate",
    "StratifiedError",
    "cell_proportions",
    "overall_accuracy",
    "users_accuracy",
    "producers_accuracy",
    "area_proportion",
    "sample_size_simple",
    "sample_size_stratified",
    "allocate_sample",
    "stratum_std_dev",
]

#: z for a two-sided 95% interval, as the paper uses it (§5.1.1).
Z_95 = 1.96
#: The paper's own guidance for change strata (§5.1.2): "Allocate a sample size
#: of 50-100 for each change strata".
CHANGE_STRATUM_MIN = 50
CHANGE_STRATUM_MAX = 100


class StratifiedError(ValueError):
    """The inputs are not a usable stratified sample."""


@dataclass(frozen=True)
class AccuracyEstimate:
    """A proportion with its standard error, and the interval it implies."""

    value: float
    standard_error: float
    sample_size: int

    def interval(self, z: float = Z_95) -> tuple[float, float]:
        half = z * self.standard_error
        return (self.value - half, self.value + half)

    @property
    def half_width(self) -> float:
        return Z_95 * self.standard_error


@dataclass(frozen=True)
class AreaEstimate:
    """An area with its standard error, in the unit of ``total_area``."""

    proportion: float
    proportion_standard_error: float
    area: float
    area_standard_error: float

    def interval(self, z: float = Z_95) -> tuple[float, float]:
        half = z * self.area_standard_error
        return (self.area - half, self.area + half)


def _check(weights: Mapping[str, float], matrix: Mapping[str, Mapping[str, int]]) -> None:
    if not weights:
        raise StratifiedError("no strata weights given")
    missing = [s for s in weights if s not in matrix]
    if missing:
        raise StratifiedError(
            "strata without a sample row: " + ", ".join(sorted(missing))
        )
    for stratum, weight in weights.items():
        if not (0.0 < weight <= 1.0):
            raise StratifiedError(
                f"weight for {stratum!r} is {weight!r}; a mapped area proportion "
                "must be in (0, 1]"
            )
    total = math.fsum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise StratifiedError(
            f"weights sum to {total!r}, not 1. They are mapped area proportions "
            "of the whole region, so a short sum means a stratum is missing — "
            "and a missing stratum biases every estimate below."
        )
    for stratum in weights:
        n = sum((matrix[stratum] or {}).values())
        if n < 2:
            raise StratifiedError(
                f"stratum {stratum!r} has n={n}; the variance estimators divide "
                "by (n-1), so a stratum needs at least 2 sample units"
            )


def stratum_std_dev(users_accuracy_value: float) -> float:
    """``S_i = sqrt(U_i (1 - U_i))`` — Cochran (1977) Eq. (5.55), cited in Eq. (13)."""

    if not (0.0 <= users_accuracy_value <= 1.0):
        raise StratifiedError(
            f"user's accuracy {users_accuracy_value!r} is not a proportion"
        )
    return math.sqrt(users_accuracy_value * (1.0 - users_accuracy_value))


def cell_proportions(
    weights: Mapping[str, float], matrix: Mapping[str, Mapping[str, int]]
) -> dict[str, dict[str, float]]:
    """``p_ij = W_i * n_ij / n_i`` — **Eq. (4)**.

    This is the step that makes everything downstream area-weighted: the raw
    sample counts are *not* proportions of the region, because the strata were
    sampled at different rates on purpose.
    """

    _check(weights, matrix)
    out: dict[str, dict[str, float]] = {}
    for stratum, weight in weights.items():
        row = matrix[stratum] or {}
        n_i = sum(row.values())
        out[stratum] = {ref: weight * count / n_i for ref, count in row.items()}
    return out


def overall_accuracy(
    weights: Mapping[str, float], matrix: Mapping[str, Mapping[str, int]]
) -> AccuracyEstimate:
    """``O = sum_j p_jj`` — **Eq. (1)**; variance from **Eq. (5)**."""

    p = cell_proportions(weights, matrix)
    value = math.fsum(p[s].get(s, 0.0) for s in weights)
    variance = 0.0
    total_n = 0
    for stratum, weight in weights.items():
        row = matrix[stratum] or {}
        n_i = sum(row.values())
        total_n += n_i
        u_i = row.get(stratum, 0) / n_i
        variance += weight**2 * u_i * (1.0 - u_i) / (n_i - 1)
    return AccuracyEstimate(value, math.sqrt(variance), total_n)


def users_accuracy(
    weights: Mapping[str, float],
    matrix: Mapping[str, Mapping[str, int]],
    stratum: str,
) -> AccuracyEstimate:
    """``U_i = p_ii / p_i.`` — **Eq. (2)**; variance from **Eq. (6)**.

    Commission error is ``1 - U_i``.  With the map classes as strata this
    reduces to the sample proportion within the stratum, which is why it needs
    no weights — but they are still validated, so a caller cannot get a
    user's accuracy out of a frame whose weights do not close.
    """

    _check(weights, matrix)
    if stratum not in weights:
        raise StratifiedError(f"{stratum!r} is not one of the strata")
    row = matrix[stratum] or {}
    n_i = sum(row.values())
    u_i = row.get(stratum, 0) / n_i
    variance = u_i * (1.0 - u_i) / (n_i - 1)
    return AccuracyEstimate(u_i, math.sqrt(variance), n_i)


def producers_accuracy(
    weights: Mapping[str, float],
    matrix: Mapping[str, Mapping[str, int]],
    reference_class: str,
    *,
    population_units: Mapping[str, float] | None = None,
) -> AccuracyEstimate:
    """``P_j = p_jj / p_.j`` — **Eq. (3)**; variance from **Eq. (7)**.

    Omission error is ``1 - P_j``, and **this is the estimate the roadmap's
    "reviewing only detected polygons can estimate commission but not
    omissions" bullet is about**: the denominator is the reference class total,
    which includes area the map put in *other* strata.  A design that samples
    only inside the mapped-change stratum leaves ``n_ij`` empty for every
    ``i != j`` and cannot estimate it at all.

    ``population_units`` is ``N_i`` per stratum; when omitted the weights are
    used, which is equivalent because Eq. (7) is homogeneous in ``N``.
    """

    _check(weights, matrix)
    j = reference_class
    if j not in weights:
        raise StratifiedError(
            f"{j!r} is not one of the strata; Eq. (7) needs the map class of the "
            "same name to form the N_j. marginal"
        )
    N = dict(population_units) if population_units else dict(weights)

    n_of = {s: sum((matrix[s] or {}).values()) for s in weights}
    # N_hat_j = sum_i (N_i / n_i) * n_ij  — the estimated reference-class total.
    n_hat_j = math.fsum(
        N[s] / n_of[s] * (matrix[s] or {}).get(j, 0) for s in weights
    )
    if n_hat_j <= 0:
        raise StratifiedError(
            f"no sample unit anywhere has reference class {j!r}, so its producer's "
            "accuracy is not estimable from this sample"
        )
    p_j = math.fsum(cell_proportions(weights, matrix)[s].get(j, 0.0) for s in weights)
    p_jj = cell_proportions(weights, matrix)[j].get(j, 0.0)
    value = p_jj / p_j if p_j else 0.0

    u_j = (matrix[j] or {}).get(j, 0) / n_of[j]
    first = N[j] ** 2 * (1.0 - value) ** 2 * u_j * (1.0 - u_j) / (n_of[j] - 1)
    second = 0.0
    for s in weights:
        if s == j:
            continue
        row = matrix[s] or {}
        n_i = n_of[s]
        frac = row.get(j, 0) / n_i
        second += N[s] ** 2 * frac * (1.0 - frac) / (n_i - 1)
    variance = (first + value**2 * second) / n_hat_j**2
    return AccuracyEstimate(value, math.sqrt(max(variance, 0.0)), sum(n_of.values()))


def area_proportion(
    weights: Mapping[str, float],
    matrix: Mapping[str, Mapping[str, int]],
    reference_class: str,
    *,
    total_area: float = 1.0,
) -> AreaEstimate:
    """``p_k = sum_i W_i n_ik / n_i`` — **Eq. (9)**; SE from **Eq. (10)**, area from **Eq. (11)**.

    This is the *reference* area of the class, not the mapped area.  The gap
    between the two is what an accuracy assessment buys: the mapped area is a
    census of the map, the estimate is of the ground.
    """

    _check(weights, matrix)
    value = 0.0
    variance = 0.0
    for stratum, weight in weights.items():
        row = matrix[stratum] or {}
        n_i = sum(row.values())
        frac = row.get(reference_class, 0) / n_i
        value += weight * frac
        variance += weight**2 * frac * (1.0 - frac) / (n_i - 1)
    se = math.sqrt(variance)
    return AreaEstimate(value, se, value * total_area, se * total_area)


def sample_size_simple(
    overall_accuracy_target: float, half_width: float, *, z: float = Z_95
) -> int:
    """``n = z^2 O (1-O) / d^2`` — **Eq. (12)**, Cochran (1977) Eq. (4.2).

    A starting point only, and the paper says so: it targets overall accuracy
    under *simple* random sampling, which is not the design a rare change class
    wants.
    """

    if not (0.0 < overall_accuracy_target < 1.0):
        raise StratifiedError("the conjectured overall accuracy must be in (0, 1)")
    if half_width <= 0:
        raise StratifiedError("the target half-width must be positive")
    o = overall_accuracy_target
    return math.ceil(z**2 * o * (1.0 - o) / half_width**2)


def sample_size_stratified(
    weights: Mapping[str, float],
    conjectured_users_accuracy: Mapping[str, float],
    target_overall_se: float,
    *,
    population_units: float | None = None,
) -> int:
    """``n ~= (sum W_i S_i / S(O))^2`` — **Eq. (13)**, Cochran (1977) Eq. (5.25).

    The paper drops the ``(1/N) sum W_i S_i^2`` term in the denominator because
    ``N`` is typically over ten million pixels.  ``population_units`` keeps the
    exact form available rather than hiding the approximation: pass ``N`` and
    the full denominator is used.
    """

    if target_overall_se <= 0:
        raise StratifiedError("the target standard error must be positive")
    missing = [s for s in weights if s not in conjectured_users_accuracy]
    if missing:
        raise StratifiedError(
            "no conjectured user's accuracy for: " + ", ".join(sorted(missing))
            + ". Eq. (13) cannot be evaluated without one per stratum, and "
            "guessing 0.5 for an unknown stratum silently maximises it."
        )
    total = math.fsum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise StratifiedError(f"weights sum to {total!r}, not 1")

    numerator = math.fsum(
        weights[s] * stratum_std_dev(conjectured_users_accuracy[s]) for s in weights
    )
    if population_units is None:
        return math.ceil((numerator / target_overall_se) ** 2)
    tail = math.fsum(
        weights[s] * stratum_std_dev(conjectured_users_accuracy[s]) ** 2
        for s in weights
    )
    denominator = target_overall_se**2 + tail / population_units
    return math.ceil(numerator**2 / denominator)


def allocate_sample(
    weights: Mapping[str, float],
    total: int,
    change_strata: Sequence[str],
    *,
    per_change_stratum: int = 75,
) -> dict[str, int]:
    """The paper's own simplified allocation (§5.1.2), made explicit.

    *"Allocate a sample size of 50-100 for each change strata … The sample size
    of n-r is then allocated proportionally to the area of each remaining
    stratum."*  ``per_change_stratum`` defaults to 75 because that is the
    allocation the worked example chooses ("Alloc2").

    It refuses a value outside 50-100 rather than accepting it quietly: the
    band is the recommendation, and stepping outside it is a decision that
    belongs in a record, not in a keyword argument.
    """

    if not (CHANGE_STRATUM_MIN <= per_change_stratum <= CHANGE_STRATUM_MAX):
        raise StratifiedError(
            f"per_change_stratum={per_change_stratum} is outside the recommended "
            f"{CHANGE_STRATUM_MIN}-{CHANGE_STRATUM_MAX} band of Olofsson et al. "
            "(2014) §5.1.2; record the reason for departing from it"
        )
    unknown = [s for s in change_strata if s not in weights]
    if unknown:
        raise StratifiedError("unknown change strata: " + ", ".join(sorted(unknown)))
    stable = [s for s in weights if s not in change_strata]
    if not stable:
        raise StratifiedError("every stratum is a change stratum; nothing to spread")

    allocation = {s: per_change_stratum for s in change_strata}
    remaining = total - per_change_stratum * len(change_strata)
    if remaining < len(stable):
        raise StratifiedError(
            f"total={total} leaves {remaining} for {len(stable)} stable stratum/a "
            "after the change strata; raise the total or lower per_change_stratum"
        )
    stable_weight = math.fsum(weights[s] for s in stable)
    for s in stable:
        allocation[s] = max(1, round(remaining * weights[s] / stable_weight))
    return allocation
