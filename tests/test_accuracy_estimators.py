"""The Phase 5 arithmetic, anchored on the published worked example.

A weighted estimator is exactly the kind of code that looks right with
plausible numbers, so the primary tests here do not assert a property this
repository invented — they reproduce values that **Olofsson et al. (2014)**
printed:

* Table 5: ``W_i``, ``U_i``, ``S_i`` for four strata, and a total sample size
  of **641** from Eq. (13) at a target ``S(O) = 0.01``;
* §5.1.2: the allocation the example chooses, 75 units in each change stratum
  with the remainder proportional to the stable strata ("Alloc2");
* Table 6/7: the hypothetical error matrix and the standard errors it yields.

Each test names the mutation it kills.  The band of tests at the end exists
because the interesting failures of this module are not wrong formulas — they
are a right formula fed an unweighted matrix, or a stratum quietly missing from
the weights.

Source: Remote Sensing of Environment 148:42-57,
https://doi.org/10.1016/j.rse.2014.02.015
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.validation.accuracy import (  # noqa: E402
    CHANGE_STRATUM_MAX,
    CHANGE_STRATUM_MIN,
    StratifiedError,
    allocate_sample,
    area_proportion,
    cell_proportions,
    overall_accuracy,
    producers_accuracy,
    sample_size_simple,
    sample_size_stratified,
    stratum_std_dev,
    users_accuracy,
)

# ── Table 5 of the paper, transcribed ────────────────────────────────────────
# Strata (i)          Wi      Ui     Si
# 1 Deforestation     0.020   0.700  0.458
# 2 Forest gain       0.015   0.600  0.490
# 3 Stable forest     0.320   0.900  0.300
# 4 Stable non-forest 0.645   0.950  0.218   (Wi completes the unit sum)
TABLE5_W = {
    "deforestation": 0.020,
    "forest_gain": 0.015,
    "stable_forest": 0.320,
    "stable_nonforest": 0.645,
}
TABLE5_U = {
    "deforestation": 0.700,
    "forest_gain": 0.600,
    "stable_forest": 0.900,
    "stable_nonforest": 0.950,
}
TABLE5_S = {
    "deforestation": 0.458,
    "forest_gain": 0.490,
    "stable_forest": 0.300,
    "stable_nonforest": 0.218,
}
PAPER_TARGET_SE = 0.01
PAPER_SAMPLE_SIZE = 641
CHANGE_STRATA = ("deforestation", "forest_gain")


# ── the published anchors ────────────────────────────────────────────────────

def test_table5_weights_close_to_one():
    """Mutation killed: mistyping a weight from Table 5.

    The fourth weight is the one the paper leaves implicit, and a transcription
    error there would shift every number below without any test noticing.
    """

    assert math.fsum(TABLE5_W.values()) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("stratum", sorted(TABLE5_U))
def test_stratum_std_dev_reproduces_table5(stratum):
    """Mutation killed: ``sqrt(U)`` or ``U(1-U)`` instead of ``sqrt(U(1-U))``.

    Table 5 prints S_i to three decimals, so that is the tolerance.
    """

    assert stratum_std_dev(TABLE5_U[stratum]) == pytest.approx(
        TABLE5_S[stratum], abs=5e-4
    )


def test_eq13_reproduces_the_published_sample_size_of_641():
    """THE anchor: the paper says n = 641 for these inputs. Mutation killed: any
    algebraic slip in Eq. (13) — a missing square, a sum of squares instead of a
    square of sums, or the weights dropped."""

    n = sample_size_stratified(TABLE5_W, TABLE5_U, PAPER_TARGET_SE)
    assert n == PAPER_SAMPLE_SIZE


def test_the_second_denominator_term_is_negligible_at_the_papers_N():
    """The paper drops ``(1/N) sum W_i S_i^2`` because N is over ten million.

    Asserted rather than trusted: with N = 1e7 the exact form must still give
    641, and with an absurdly small N it must differ — otherwise the parameter
    is decorative.
    """

    assert sample_size_stratified(
        TABLE5_W, TABLE5_U, PAPER_TARGET_SE, population_units=1e7
    ) == PAPER_SAMPLE_SIZE
    assert sample_size_stratified(
        TABLE5_W, TABLE5_U, PAPER_TARGET_SE, population_units=500
    ) < PAPER_SAMPLE_SIZE


def test_eq12_is_cochrans_simple_random_formula():
    """Mutation killed: dropping z^2, or using d instead of d^2.

    At O = 0.7 and d = 0.05, z^2 O(1-O)/d^2 = 1.96^2 * 0.21 / 0.0025 = 322.7.
    """

    assert sample_size_simple(0.70, 0.05) == 323


#: Table 5's published "Alloc2" column, transcribed. It sums to 640, not 641 —
#: and so do "Equal" (640) and "Alloc3" (640), while "Alloc1" and "Prop" sum to
#: 641. The table carries its own rounding, which is why the test below checks
#: the STATED RULE and bounds the gap, rather than claiming to reproduce the
#: column exactly.
TABLE5_ALLOC2 = {
    "deforestation": 75,
    "forest_gain": 75,
    "stable_forest": 165,
    "stable_nonforest": 325,
}


def test_the_allocation_follows_the_papers_STATED_RULE():
    """Mutation killed: allocating the remainder equally instead of proportionally.

    §5.1.2: *"Allocate a sample size of 50-100 for each change strata … The
    sample size of n-r is then allocated proportionally to the area of each
    remaining stratum."*  With the change strata taking 150 of 641, the
    remainder 491 splits over stable weights 0.320 and 0.645 (share 0.965) as
    163 / 328.

    An equal split of the remainder would give 245/246, so the test tells the
    two rules apart.
    """

    allocation = allocate_sample(
        TABLE5_W, PAPER_SAMPLE_SIZE, CHANGE_STRATA, per_change_stratum=75
    )
    assert allocation["deforestation"] == 75
    assert allocation["forest_gain"] == 75
    assert allocation["stable_forest"] == 163
    assert allocation["stable_nonforest"] == 328
    assert allocation["stable_forest"] != allocation["stable_nonforest"]
    assert sum(allocation.values()) == PAPER_SAMPLE_SIZE


def test_the_stated_rule_lands_within_three_units_of_the_published_column():
    """A MEASURED DISCREPANCY, asserted so it cannot drift unnoticed.

    The stated rule gives 163/328; the published "Alloc2" column prints
    165/325.  The rule, applied to the weights the same table prints, does not
    reproduce the column — the paper's own columns disagree with each other on
    the total (640 vs 641), so the difference is rounding inside the example
    and not a different rule.

    The first version of this test asserted 163/328 while its docstring
    claimed to reproduce "Alloc2". That is a test passing for the wrong
    reason: it asserted this module's own output under someone else's
    authority. Bounding the gap is the honest form — and if a future edit
    changes the rule, the bound breaks.
    """

    allocation = allocate_sample(
        TABLE5_W, PAPER_SAMPLE_SIZE, CHANGE_STRATA, per_change_stratum=75
    )
    for stratum, published in TABLE5_ALLOC2.items():
        assert abs(allocation[stratum] - published) <= 3, (
            f"{stratum}: rule gives {allocation[stratum]}, paper prints {published}"
        )
    assert sum(TABLE5_ALLOC2.values()) == 640
    assert sum(allocation.values()) == 641


@pytest.mark.parametrize("bad", [0, 49, 101, 1000])
def test_an_allocation_outside_the_recommended_band_is_refused(bad):
    """Mutation killed: accepting any per-stratum size silently.

    §5.1.2 recommends 50-100 for a change stratum.  Stepping outside is a
    decision that belongs in a record; the refusal is what forces it there.
    """

    with pytest.raises(StratifiedError, match="50-100|outside the recommended"):
        allocate_sample(TABLE5_W, 641, CHANGE_STRATA, per_change_stratum=bad)


def test_the_recommended_band_is_the_papers_band():
    assert (CHANGE_STRATUM_MIN, CHANGE_STRATUM_MAX) == (50, 100)


# ── the estimators, on a matrix whose answers are computable by hand ─────────
# Two strata, deliberately tiny, so every expected value below is arithmetic a
# reviewer can redo on paper.
W2 = {"change": 0.10, "nochange": 0.90}
M2 = {
    # map class -> reference class -> count
    "change": {"change": 60, "nochange": 40},      # U = 0.60
    "nochange": {"change": 10, "nochange": 90},    # U = 0.90
}


def test_eq4_weights_the_cells_and_they_sum_to_one():
    """Mutation killed: returning raw sample fractions instead of W_i * n_ij/n_i.

    This is the step that makes the estimate area-weighted; without it the
    rare stratum's oversampling inflates it.
    """

    p = cell_proportions(W2, M2)
    assert p["change"]["change"] == pytest.approx(0.10 * 0.60)
    assert p["nochange"]["change"] == pytest.approx(0.90 * 0.10)
    total = math.fsum(v for row in p.values() for v in row.values())
    assert total == pytest.approx(1.0, abs=1e-12)


def test_users_accuracy_is_the_within_stratum_proportion():
    """Mutation killed: weighting U_i, which would make it not a user's accuracy.

    Eq. (2) with the map classes as strata reduces to n_ii/n_i — 0.60 here —
    and its SE from Eq. (6) is sqrt(0.6*0.4/99).
    """

    u = users_accuracy(W2, M2, "change")
    assert u.value == pytest.approx(0.60)
    assert u.standard_error == pytest.approx(math.sqrt(0.6 * 0.4 / 99))
    assert u.sample_size == 100


def test_overall_accuracy_is_area_weighted_not_sample_weighted():
    """Mutation killed: averaging the strata instead of weighting them.

    O = 0.10*0.60 + 0.90*0.90 = 0.87.  The unweighted mean of 0.60 and 0.90 is
    0.75, so the two are far apart and the test can tell them apart.
    """

    o = overall_accuracy(W2, M2)
    assert o.value == pytest.approx(0.87)
    assert o.value != pytest.approx(0.75)
    expected_var = 0.10**2 * 0.6 * 0.4 / 99 + 0.90**2 * 0.9 * 0.1 / 99
    assert o.standard_error == pytest.approx(math.sqrt(expected_var))


def test_area_proportion_estimates_the_REFERENCE_area_not_the_mapped_area():
    """Mutation killed: returning W_change, i.e. the map's own census.

    Eq. (9): p_change = 0.10*0.60 + 0.90*0.10 = 0.15.  The map says 0.10.  The
    gap is the whole point of the assessment, and a mutation that returns the
    mapped area would look plausible on any well-behaved map.
    """

    est = area_proportion(W2, M2, "change", total_area=2_093_558.0)
    assert est.proportion == pytest.approx(0.15)
    assert est.proportion != pytest.approx(W2["change"])
    assert est.area == pytest.approx(0.15 * 2_093_558.0)
    assert est.area_standard_error == pytest.approx(
        est.proportion_standard_error * 2_093_558.0
    )


def test_producers_accuracy_uses_the_reference_total_as_denominator():
    """Mutation killed: computing omission from the mapped total (= user's accuracy).

    P_change = p_cc / p_.c = 0.06 / 0.15 = 0.40, against U_change = 0.60.  The
    two differ precisely because the reference total includes change the map
    put in the *no-change* stratum — the omissions.
    """

    p = producers_accuracy(W2, M2, "change")
    assert p.value == pytest.approx(0.06 / 0.15)
    assert p.value != pytest.approx(users_accuracy(W2, M2, "change").value)
    assert p.standard_error > 0


def test_omission_is_unestimable_when_only_the_change_stratum_is_sampled():
    """The roadmap bullet, as an executable fact.

    *"reviewing only detected polygons can estimate commission but not
    omissions"*.  With the no-change stratum contributing no reference-change
    unit, the producer's accuracy comes out 1.0 — a **false** 100% recall — so
    the design, not the arithmetic, is what has to prevent this.
    """

    blind = {
        "change": {"change": 60, "nochange": 40},
        "nochange": {"change": 0, "nochange": 100},
    }
    p = producers_accuracy(W2, blind, "change")
    assert p.value == pytest.approx(1.0)
    # and the honest matrix disagrees sharply
    assert producers_accuracy(W2, M2, "change").value < 0.5


def test_a_perfect_matrix_gives_unit_accuracy_and_zero_variance():
    perfect = {
        "change": {"change": 100, "nochange": 0},
        "nochange": {"change": 0, "nochange": 100},
    }
    o = overall_accuracy(W2, perfect)
    assert o.value == pytest.approx(1.0)
    assert o.standard_error == pytest.approx(0.0)
    assert area_proportion(W2, perfect, "change").proportion == pytest.approx(0.10)


# ── the refusals, which are where a real design goes wrong ───────────────────

def test_weights_that_do_not_close_are_refused():
    """Mutation killed: normalising the weights instead of refusing.

    A short sum means a stratum of the region was left out of the frame.
    Normalising would redistribute its area over the others and every estimate
    would come out confidently wrong, with no symptom.
    """

    with pytest.raises(StratifiedError, match="sum to"):
        overall_accuracy({"change": 0.10, "nochange": 0.80}, M2)


def test_a_stratum_with_one_unit_is_refused_because_the_variance_divides_by_n_minus_1():
    with pytest.raises(StratifiedError, match=r"n=1|at least 2"):
        overall_accuracy(W2, {"change": {"change": 1}, "nochange": M2["nochange"]})


def test_a_missing_conjectured_accuracy_is_refused_not_defaulted():
    """Mutation killed: defaulting the unknown stratum to 0.5.

    S_i is maximised at U = 0.5, so a silent default inflates n — which looks
    conservative and is actually an unrecorded assumption about the stratum a
    planner knows least about.
    """

    with pytest.raises(StratifiedError, match="conjectured user's accuracy"):
        sample_size_stratified(
            TABLE5_W, {k: v for k, v in TABLE5_U.items() if k != "forest_gain"}, 0.01
        )


def test_a_stratum_absent_from_the_sample_is_refused():
    with pytest.raises(StratifiedError, match="without a sample row"):
        overall_accuracy(W2, {"change": M2["change"]})


def test_producers_accuracy_of_a_class_nobody_observed_is_refused():
    """Mutation killed: returning 0.0, which reads as 'total omission' rather
    than 'not estimable from this sample'."""

    none_seen = {
        "change": {"nochange": 100},
        "nochange": {"nochange": 100},
    }
    with pytest.raises(StratifiedError, match="not estimable"):
        producers_accuracy(W2, none_seen, "change")
