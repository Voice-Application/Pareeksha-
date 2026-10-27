"""T-FR-EV-8: Cohen's kappa and Spearman equal hand-computed values."""

from __future__ import annotations

import pytest
from scipy import stats

from pareeksha.evaluation.calibration import (
    LabelPair,
    cohen_kappa,
    compute_calibration,
    spearman,
)


def test_kappa_hand_computed_2x2() -> None:
    # judge/human pass-fail counts: both pass 20, both fail 15, judge pass & human fail 5,
    # judge fail & human pass 10  ->  n=50, observed = 35/50 = 0.7
    # chance = (25/50)*(30/50) + (25/50)*(20/50) = 0.30 + 0.20 = 0.50  ->  kappa = 0.2 / 0.5 = 0.4
    judge = [True] * 20 + [False] * 15 + [True] * 5 + [False] * 10
    human = [True] * 20 + [False] * 15 + [False] * 5 + [True] * 10
    assert cohen_kappa(judge, human) == pytest.approx(0.4)


def test_kappa_perfect_none_and_chance_level() -> None:
    labels = [True, False, True, True, False]
    assert cohen_kappa(labels, labels) == 1.0
    assert cohen_kappa([True, False, True, False], [False, True, True, False]) == pytest.approx(0.0)
    assert cohen_kappa([True, False], [False, True]) == pytest.approx(-1.0)


def test_kappa_undefined_when_a_rater_never_varies_or_there_is_no_data() -> None:
    assert cohen_kappa([True, True, True], [True, True, True]) is None
    assert cohen_kappa([], []) is None


def test_spearman_hand_computed_with_ties() -> None:
    # x = 10 20 20 40, y = 1 3 2 4. ranks x = 1 2.5 2.5 4, ranks y = 1 3 2 4
    # means 2.5; cov = (-1.5)(-1.5) + 0*0.5 + 0*(-0.5) + 1.5*1.5 = 4.5
    # var x = 2.25 + 0 + 0 + 2.25 = 4.5; var y = 2.25 + 0.25 + 0.25 + 2.25 = 5
    # rho = 4.5 / sqrt(4.5 * 5) = 0.94868...
    assert spearman([10, 20, 20, 40], [1, 3, 2, 4]) == pytest.approx(0.9486833, abs=1e-6)


def test_spearman_matches_scipy_on_random_data() -> None:
    x = [91, 72, 64, 88, 55, 79, 79, 40, 97, 63, 70, 85]
    y = [88, 70, 70, 90, 60, 75, 82, 35, 99, 50, 72, 80]
    assert spearman(x, y) == pytest.approx(stats.spearmanr(x, y).statistic)


def test_spearman_extremes_and_undefined() -> None:
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1], [1]) is None
    assert spearman([5, 5, 5], [1, 2, 3]) is None


def test_compute_calibration_combines_all_three_metrics() -> None:
    pairs = [
        LabelPair(
            True, True, 90, 88, {"task_completion": 4, "empathy_tone": 3}, {"task_completion": 4}
        ),
        LabelPair(
            False, False, 55, 60, {"task_completion": 2, "empathy_tone": 2}, {"task_completion": 3}
        ),
        LabelPair(True, False, 82, 40, {"task_completion": 3}, {"task_completion": 1}),
        LabelPair(False, False, 30, None, {}, {}),  # no human overall: only kappa and MAE use it
    ]
    out = compute_calibration(pairs)
    assert out.n == 4
    # observed 3/4; judge pass 2/4, human pass 1/4 -> chance 0.5*0.25 + 0.5*0.75 = 0.5; kappa 0.5
    assert out.kappa_pass_fail == pytest.approx(0.5)
    # scored pairs: (90,88) (55,60) (82,40): ranks judge 3 1 2, human 3 2 1 -> rho 0.5
    assert out.spearman_overall == pytest.approx(0.5)
    # task_completion |4-4| |2-3| |3-1| = 0,1,2 -> mean 1.0; empathy_tone has no human score
    assert out.dimension_mae == {"task_completion": 1.0}


def test_empty_calibration() -> None:
    out = compute_calibration([])
    assert (out.n, out.kappa_pass_fail, out.spearman_overall, out.dimension_mae) == (
        0,
        None,
        None,
        {},
    )
