"""Tests for crashmetrics.sensitivity.

During development the results matched scipy.stats.spearmanr (with ties),
the inverse-correlation-matrix formula for PRCC, a plain least-squares
fit for SRC (all to 1e-15) and SALib's Morris analysis (exactly). Here
they are checked against exact cases.
"""

import math

import numpy as np
import pytest

from crashmetrics.doe import latin_hypercube, morris_design
from crashmetrics.sensitivity import (
    morris_effects,
    partial_rank_correlation,
    rank_correlation,
    rank_sensitivity,
    regression_coefficients,
)


def test_rank_correlation_exact_cases():
    x = np.arange(10.0)
    r = rank_correlation({"up": x, "down": -x ** 3, "flat": np.ones(10)}, np.exp(x))
    assert r == pytest.approx({"up": 1.0, "down": -1.0, "flat": 0.0})
    # ties: average ranks, as scipy.stats.spearmanr
    ties = rank_correlation({"t": [1, 1, 2, 2, 3]}, [1, 2, 3, 4, 5])
    assert ties["t"] == pytest.approx(0.9486832980505138)


def test_missing_values_are_left_out():
    x = [1.0, 2.0, 3.0, 4.0, math.nan, 6.0]
    y = [2.0, 4.0, 6.0, 8.0, 1.0, math.nan]
    assert rank_correlation({"x": x}, y)["x"] == pytest.approx(1.0)
    with pytest.raises(ValueError, match="complete runs"):
        rank_correlation({"x": [1.0, 2.0]}, [1.0, 2.0])
    with pytest.raises(ValueError, match="one value per"):
        rank_correlation({"x": [1.0, 2.0, 3.0]}, [1.0, 2.0])


def test_prcc_finds_a_weak_variable_behind_a_strong_one():
    d = latin_hypercube({"a": (0, 1), "b": (0, 1), "c": (0, 1)}, 40, seed=2)
    a, b, c = d.unit.T
    y = 5 * a + b ** 2
    spearman = rank_correlation({"a": a, "b": b, "c": c}, y)
    prcc = partial_rank_correlation({"a": a, "b": b, "c": c}, y)
    assert abs(spearman["b"]) < 0.3                     # hidden by a
    assert prcc["a"] > 0.99 and prcc["b"] > 0.85 and abs(prcc["c"]) < 0.35


def test_regression_coefficients_linear_model():
    rng = np.random.default_rng(1)
    x1, x2 = rng.random(200), rng.random(200)
    y = 3.0 * x1 - 1.0 * x2
    src, r2 = regression_coefficients({"x1": x1, "x2": x2, "k": np.ones(200)}, y)
    assert r2 == pytest.approx(1.0)
    assert src["k"] == 0.0
    sd_y = y.std()
    assert src["x1"] == pytest.approx(3.0 * x1.std() / sd_y)
    assert src["x2"] == pytest.approx(-1.0 * x2.std() / sd_y)
    flat, r2_flat = regression_coefficients({"x1": x1}, np.ones(200))
    assert flat == {"x1": 0.0} and r2_flat == 0.0


def test_rank_sensitivity_from_rows():
    rows = latin_hypercube({"a": (0, 1), "b": (0, 1)}, 20, seed=4).rows()
    for r in rows:
        r["y"] = 2 * r["a"] - 5 * r["b"]
    rows.append({"run": "failed", "a": 0.5, "b": 0.5, "error": "ValueError"})
    result = rank_sensitivity(rows, ["a", "b"], "y")
    assert result.ranking == ["b", "a"]
    assert result.r2 == pytest.approx(1.0)
    text = result.summary()
    assert text.splitlines()[0] == "Sensitivity of y (linear fit R² 1.00):"
    assert "-0.00" not in text


def test_morris_effects_exact():
    bounds = {"a": (0.0, 2.0), "b": (0.0, 1.0), "c": (0.0, 1.0)}
    d = morris_design(bounds, trajectories=8, levels=4, seed=5)
    a, b, _ = d.values.T
    y = 4.0 * a + 10.0 * b ** 2                      # c has no effect
    effects = {e.name: e for e in morris_effects(d, y)}
    # unit-cube effects: d(4 a)/d(unit a) = 4 * 2 = 8, constant
    assert effects["a"].mu == pytest.approx(8.0)
    assert effects["a"].sigma == pytest.approx(0)
    assert effects["c"].mu_star == 0.0
    assert effects["b"].sigma > 0                     # non-linear
    assert [e.name for e in morris_effects(d, y)][-1] == "c"
    with pytest.raises(ValueError, match="one output value"):
        morris_effects(d, y[:-1])
