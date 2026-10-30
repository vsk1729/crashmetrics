"""Tests for crashmetrics.margins and crashmetrics.uncertainty."""

import math

import numpy as np
import pytest

from crashmetrics.frontal_scoring import Limit
from crashmetrics.margins import euroncap_margins, margin, margin_features, margins
from crashmetrics.uncertainty import (
    monte_carlo,
    normal,
    relative,
    scale,
    star_probabilities,
    uniform,
)

# --- margins -------------------------------------------------------------------

def test_margin_with_hpl_and_lpl():
    m = margin("hic15", 600.0, Limit(500.0, 700.0, 700.0))
    assert m.position == pytest.approx(0.5)
    assert m.margin_lpl == pytest.approx(100 / 700)
    assert m.margin_hpl == pytest.approx(-0.2)
    assert m.sliding == pytest.approx(0.5)
    assert margin("hic15", 400.0, (500.0, 700.0)).sliding == 1.0
    assert margin("hic15", 800.0, (500.0, 700.0)).position == pytest.approx(1.5)
    assert margin("neck", -3500.0, (2700.0, 3300.0)).value == 3500.0   # magnitude


def test_margin_single_limit():
    m = margin("thcc", 30.0, 42.0)
    assert m.hpl is None and m.position is None
    assert m.margin_lpl == pytest.approx(12 / 42)
    assert m.sliding == 1.0 and margin("thcc", 42.0, 42.0).sliding == 0.0
    with pytest.raises(ValueError, match="positive"):
        margin("x", 1.0, 0.0)
    with pytest.raises(ValueError, match="HPL < LPL"):
        margin("x", 1.0, (5.0, 4.0))
    with pytest.raises(ValueError, match="finite"):
        margin("x", math.nan, 4.0)


def test_euroncap_margins_and_features():
    result = euroncap_margins("hybrid3_50", {"hic15": 600.0, "chest_compression": 31.0,
                                             "tibia_index": 1.0, "unknown": 1.0}, 50)
    assert set(result) == {"hic15", "chest_compression", "tibia_index"}
    assert result["chest_compression"].position == pytest.approx(0.5)  # 20 -> 42 mm
    flat = margin_features(result, prefix="driver.")
    assert flat["driver.hic15.sliding"] == pytest.approx(0.5)
    assert len(flat) == 9
    single = margin_features(margins({"thcc": 30.0}, {"thcc": 42.0}))
    assert math.isnan(single["thcc.position"])


# --- uncertainty ---------------------------------------------------------------

def test_scatter_kinds():
    rng = np.random.default_rng(0)
    x = normal(25.0).sample(500.0, 20000, rng)
    assert x.mean() == pytest.approx(500, abs=1)
    assert x.std() == pytest.approx(25, rel=0.03)
    r = relative(0.1).sample(30.0, 20000, rng)
    assert r.std() == pytest.approx(3.0, rel=0.03)
    u = uniform(2.0).sample(10.0, 20000, rng)
    assert u.min() >= 8.0 and u.max() <= 12.0
    s = scale(0.05).sample(1.0, 20000, rng)
    assert s.mean() == pytest.approx(1.0, abs=0.002)
    assert normal(5.0).sample(1.0, 2000, rng).min() == 0.0      # clipped at zero
    assert normal(5.0, nonnegative=False).sample(1.0, 2000, rng).min() < 0
    with pytest.raises(ValueError):
        relative(-0.1)


def stars(points):
    return 5 if points >= 27 else 4 if points >= 22 else 3


def test_monte_carlo_probability_matches_normal_distribution():
    """points = 30 - a with a ~ N(2, 1): P(points >= 27) = P(a <= 3) = 84.1 %."""
    def func(v):
        return {"points": 30 - v["a"], "stars": stars(30 - v["a"])}

    result = monte_carlo(func, {"a": 2.0, "b": 1.0},
                         {"a": normal(1.0, nonnegative=False)}, n=20000, seed=1)
    assert result.nominal == {"points": 28.0, "stars": 5.0}
    assert result.probability("stars", at_least=5) == pytest.approx(0.8413, abs=0.01)
    probs = star_probabilities(result)
    assert sum(probs.values()) == pytest.approx(1.0) and probs[0] == 0.0
    assert probs[5] == result.probability("stars", equals=5)
    assert np.all(result.inputs["b"] == 1.0)
    pct = result.percentiles("points")
    assert pct[50.0] == pytest.approx(28.0, abs=0.05)
    assert pct[5.0] == pytest.approx(28 - 1.645, abs=0.05)
    assert result.probability("points", below=28.0) == pytest.approx(0.5, abs=0.02)
    rows = result.rows()
    assert len(rows) == 20000 and set(rows[0]) == {"a", "b", "points", "stars"}
    assert "Monte Carlo, 20000 samples" in result.summary()


def test_monte_carlo_single_output_and_errors():
    result = monte_carlo(lambda v: v["x"] * 2, {"x": 1.0}, {"x": relative(0.1)},
                         n=50, seed=3)
    assert set(result.outputs) == {"value"} and len(result) == 50
    assert result.probability(at_least=0.0) == 1.0
    again = monte_carlo(lambda v: v["x"] * 2, {"x": 1.0}, {"x": relative(0.1)},
                        n=50, seed=3)
    np.testing.assert_array_equal(result.outputs["value"], again.outputs["value"])
    with pytest.raises(ValueError, match="exactly one"):
        result.probability(at_least=1.0, below=2.0)
    with pytest.raises(ValueError, match="unknown inputs"):
        monte_carlo(lambda v: 0.0, {"x": 1.0}, {"y": relative(0.1)})
    with pytest.raises(KeyError):
        result.distribution("stars")
    two = monte_carlo(lambda v: {"p": 1.0, "q": 2.0}, {"x": 1.0}, {}, n=5)
    with pytest.raises(ValueError, match="Name the output"):
        two.probability(at_least=1.0)
