"""Tests for crashmetrics.doe.

The Halton points were compared with scipy.stats.qmc.Halton (unscrambled)
during development: identical. Here they are checked against values
worked by hand.
"""

import numpy as np
import pytest

from crashmetrics.doe import (
    full_factorial,
    halton,
    latin_hypercube,
    lsdyna_parameters,
    morris_design,
)

B = {"vent": (25.0, 45.0), "limiter": (3.0, 5.5), "knee_k": (80.0, 200.0)}


def test_latin_hypercube_strata_and_bounds():
    d = latin_hypercube(B, n=17, seed=3)
    assert d.values.shape == (17, 3) and d.method == "latin_hypercube"
    for j in range(3):                                  # each stratum used once
        assert sorted(np.floor(d.unit[:, j] * 17).astype(int)) == list(range(17))
    assert d.column("vent").min() >= 25.0 and d.column("vent").max() <= 45.0
    again = latin_hypercube(B, n=17, seed=3)
    np.testing.assert_array_equal(d.values, again.values)
    centred = latin_hypercube(B, n=4, seed=1, centered=True)
    assert sorted(centred.unit[:, 0]) == [0.125, 0.375, 0.625, 0.875]


def test_halton_first_points():
    d = halton({"a": (0.0, 1.0), "b": (0.0, 1.0)}, 4)
    np.testing.assert_allclose(d.unit, [[0.5, 1 / 3], [0.25, 2 / 3],
                                        [0.75, 1 / 9], [0.125, 4 / 9]])
    with pytest.raises(ValueError, match="At most"):
        halton({f"x{i}": (0, 1) for i in range(30)}, 2)


def test_full_factorial():
    d = full_factorial({"a": [1, 2], "b": [10, 20, 30]})
    assert d.values.tolist() == [[1, 10], [1, 20], [1, 30], [2, 10], [2, 20], [2, 30]]
    assert d.unit[:, 1].tolist() == [0.0, 0.5, 1.0] * 2
    rows = d.rows(prefix="doe", digits=2)
    assert rows[0] == {"run": "doe01", "a": 1.0, "b": 10.0}


def test_morris_design_trajectories():
    d = morris_design(B, trajectories=5, levels=4, seed=2)
    assert len(d) == 5 * 4
    delta = 4 / 6
    for start in range(0, len(d), 4):
        steps = np.diff(d.unit[start:start + 4], axis=0)
        moved = np.abs(steps) > 1e-12
        assert moved.sum(axis=1).tolist() == [1, 1, 1]          # one variable a step
        assert sorted(np.flatnonzero(moved.any(axis=0))) == [0, 1, 2]
        np.testing.assert_allclose(np.abs(steps[moved]), delta)
    assert d.unit.min() >= 0 and d.unit.max() <= 1
    with pytest.raises(ValueError, match="even"):
        morris_design(B, levels=3)


def test_bounds_errors():
    with pytest.raises(ValueError, match="low < high"):
        latin_hypercube({"a": (1.0, 1.0)}, 3)
    with pytest.raises(ValueError, match="at least one"):
        latin_hypercube({}, 3)
    with pytest.raises(ValueError, match="n must"):
        halton({"a": (0, 1)}, 0)


def test_lsdyna_parameters():
    text = lsdyna_parameters({"vent": 34.75, "limit": 4, "tiny": 1.2345678e-7},
                             title="run001")
    lines = text.splitlines()
    assert lines[:4] == ["*KEYWORD", "$ run001", "*PARAMETER", "$#   prmr1      val1"]
    assert lines[4] == "R vent         34.75"
    assert lines[5] == "R limit          4.0"
    assert lines[6] == "R tiny    1.2346e-07"
    assert all(len(line) == 20 for line in lines[4:7])
    assert lines[-1] == "*END"
    with pytest.raises(ValueError, match="1-7 ASCII"):
        lsdyna_parameters({"toolongname": 1.0})
    with pytest.raises(ValueError, match="finite"):
        lsdyna_parameters({"a": float("nan")})
