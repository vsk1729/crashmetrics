"""Tests for Euro NCAP legform scoring.

Worked examples from:
- Euro NCAP Assessment Protocol - VRU v11.4 (2023), Sections 1.3.2.3, 1.3.2.4
- Euro NCAP Crash Protection - VRU Impacts v1.1 (2026), Section 4.4.3
"""

import math

import numpy as np
import pytest

from crashmetrics.pedestrian import (
    LEGFORM_LIMITS,
    LEGFORM_PROTOCOLS,
    ApliPointScore,
    apli_point_score,
    apli_score,
    headform_score,
    leg_colour,
    round_score,
    sliding_scale,
    upper_legform_alpha,
    upper_legform_energy,
    upper_legform_point_score,
    upper_legform_score,
    vru_score,
)

U_GRID = [f"U{i:+d}" if i else "U0" for i in range(4, -5, -1)]  # U+4 .. U-4
L_GRID = [f"L{i:+d}" if i else "L0" for i in range(5, -6, -1)]  # L+5 .. L-5

# 2023 / 2026 upper legform example: sum of forces in N.
UPPER_TESTS = {"U0": 5260.0, "U-2": 6800.0, "U-4": 4890.0}
UPPER_ROW = [1.000, 0.0, 0.0, 0.0, 0.740, 0.0, 0.0, 0.0, 1.000]

# 2023 aPLI example: (femur moment N m, tibia moment N m, MCL mm).
APLI_TESTS = {
    "L+1": (400.0, 257.0, 20.0),
    "L+3": (438.0, 300.0, 29.0),
    "L+5": (385.0, 225.0, 36.0),
}
FEMUR_ROW = [1.000, 0.040, 0.040, 0.040, 0.800, 0.800, 0.800, 0.040, 0.040,
             0.040, 1.000]
KNEE_ROW = [0.000, 0.000, 0.444, 0.444, 1.000, 1.000, 1.000, 0.444, 0.444,
            0.000, 0.000]


# --- sliding scale, rounding and colours ---------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(4000.0, 1.0), (5000.0, 1.0), (5260.0, 0.74), (5500.0, 0.5),
     (6000.0, 0.0), (6800.0, 0.0)],
)
def test_sliding_scale(value, expected):
    assert sliding_scale(value, 5000.0, 6000.0) == pytest.approx(expected)


def test_sliding_scale_validation():
    with pytest.raises(ValueError):
        sliding_scale(1.0, 6000.0, 5000.0)
    with pytest.raises(ValueError):
        sliding_scale(math.nan, 5000.0, 6000.0)


def test_round_score_is_half_up():
    assert round_score(0.4444) == 0.444
    assert round_score(0.0005) == 0.001
    assert round_score(0.0004) == 0.0
    assert round_score(2 / 3) == 0.667


@pytest.mark.parametrize(
    "score, colour",
    [(1.0, "green"), (0.9996, "green"), (0.9994, "yellow"), (0.75, "yellow"),
     (0.7499, "yellow"), (0.7494, "orange"), (0.5, "orange"), (0.4999, "orange"),
     (0.4994, "brown"), (0.001, "brown"),
     (0.0005, "brown"), (0.0004, "red"), (0.0, "red")],
)
def test_leg_colour(score, colour):
    # Scores are rounded to 3 decimals before the colour is assigned.
    assert leg_colour(score) == colour


def test_limits_table():
    assert LEGFORM_LIMITS == {
        "upper_legform_sum_of_forces": (5000.0, 6000.0),
        "apli_femur_moment": (390.0, 440.0),
        "apli_tibia_moment": (275.0, 320.0),
        "apli_mcl_elongation": (27.0, 32.0),
    }
    for key, expected in (("euroncap_2026", (2.5, 2.5, 5.0)),
                          ("euroncap_2023", (4.5, 4.5, 9.0))):
        p = LEGFORM_PROTOCOLS[key]
        assert (p.pelvis_points, p.femur_points, p.knee_tibia_points) == expected


# --- point scores (values from the worked examples) -----------------------


@pytest.mark.parametrize(
    "force, score", [(5260.0, 0.740), (6800.0, 0.000), (4890.0, 1.000)]
)
def test_upper_legform_point_scores(force, score):
    assert upper_legform_point_score(force) == score


def test_upper_legform_point_score_from_time_history():
    t = np.linspace(0, 0.02, 201)
    upper = 3000 * np.sin(np.pi * t / 0.02)
    lower = 2260 * np.sin(np.pi * t / 0.02)
    assert upper_legform_point_score(upper + lower) == 0.740


@pytest.mark.parametrize(
    "measured, expected",
    [
        ((400.0, 257.0, 20.0), (0.800, 1.000, 1.000, 1.000)),
        ((438.0, 300.0, 29.0), (0.040, 0.444, 0.600, 0.444)),
        ((385.0, 225.0, 36.0), (1.000, 1.000, 0.000, 0.000)),
    ],
    ids=["L+1", "L+3", "L+5"],
)
def test_apli_point_scores(measured, expected):
    s = apli_point_score(*measured)
    assert (s.femur, s.tibia, s.mcl, s.knee_tibia) == expected


def test_apli_uses_worst_gauge():
    # Several femur and tibia gauges, signed values: largest magnitude counts.
    s = apli_point_score([380.0, -415.0, 200.0], [100.0, -290.0, 250.0, 10.0], 25.0)
    assert s.femur_moment == 415.0
    assert s.femur == 0.5
    assert s.tibia_moment == 290.0
    assert s.tibia == round_score(30 / 45)
    assert s.knee_tibia == s.tibia


def test_apli_unrounded_option():
    s = apli_point_score(400.0, 300.0, 20.0, round_to=None)
    assert s.tibia == pytest.approx(20 / 45)


# --- 2023 worked examples --------------------------------------------------


def test_2023_upper_legform_example():
    result = upper_legform_score(U_GRID, UPPER_TESTS, protocol="euroncap_2023")

    assert list(result.scores) == U_GRID
    assert list(result.scores.values()) == UPPER_ROW
    assert result.total == pytest.approx(2.740)
    assert result.percentage == pytest.approx(30.444, abs=5e-4)
    assert result.points == pytest.approx(1.370, abs=5e-4)
    assert result.max_points == 4.5
    assert result.sources["U-1"] == "worst adjacent 'U-2'"
    assert result.sources["U+4"] == "symmetry of 'U-4'"


def test_2023_apli_example():
    result = apli_score(L_GRID, APLI_TESTS, protocol="euroncap_2023")

    assert list(result.femur.scores.values()) == FEMUR_ROW
    assert result.femur.total == pytest.approx(4.640)
    assert result.femur.percentage == pytest.approx(42.182, abs=5e-4)
    assert result.femur.points == pytest.approx(1.898, abs=5e-4)

    assert list(result.knee_tibia.scores.values()) == KNEE_ROW
    assert result.knee_tibia.total == pytest.approx(4.776)
    assert result.knee_tibia.percentage == pytest.approx(43.418, abs=5e-4)
    assert result.knee_tibia.points == pytest.approx(3.908, abs=5e-4)


def test_untested_points_are_filled_per_region():
    # L+4 takes femur from L+3 but knee/tibia from L+5 (2023 example).
    result = apli_score(L_GRID, APLI_TESTS)
    assert result.femur.sources["L+4"] == "worst adjacent 'L+3'"
    # L0's neighbours tie (0.800); the tested L+1 is cited, as in the protocol.
    assert result.femur.sources["L0"] == "worst adjacent 'L+1'"
    assert result.knee_tibia.sources["L+4"] == "worst adjacent 'L+5'"


def test_2023_example_total_vru_score():
    head = 10.554  # 2023 headform worked example
    pelvis = upper_legform_score(U_GRID, UPPER_TESTS, protocol="euroncap_2023")
    apli = apli_score(L_GRID, APLI_TESTS, protocol="euroncap_2023")

    total = vru_score(head, pelvis, apli.femur, apli.knee_tibia,
                      protocol="euroncap_2023")

    assert total.max_total == 36.0
    assert total.total == pytest.approx(10.554 + 1.370 + 1.898 + 3.908, abs=2e-3)


# --- 2026 ------------------------------------------------------------------


def test_2026_upper_legform_example():
    result = upper_legform_score(U_GRID, UPPER_TESTS)  # 2026 is the default

    assert list(result.scores.values()) == UPPER_ROW
    assert result.points == pytest.approx(0.761, abs=5e-4)
    assert result.max_points == 2.5


def test_2026_apli_scales_to_2_5_and_5_points():
    result = apli_score(L_GRID, APLI_TESTS)

    assert result.femur.points == pytest.approx(4.640 / 11 * 2.5)
    assert result.knee_tibia.points == pytest.approx(4.776 / 11 * 5.0)


def test_2026_total_vru_score_with_result_objects():
    head = headform_score({(i, 0): "green" for i in range(8)} | {(9, 0): "red",
                          (10, 0): "red"})
    pelvis = upper_legform_score(U_GRID, UPPER_TESTS)
    apli = apli_score(L_GRID, APLI_TESTS)

    total = vru_score(head, pelvis, apli.femur, apli.knee_tibia)

    assert total.max_total == 20.0
    assert total.head == pytest.approx(8.0)
    assert total.total == pytest.approx(
        8.0 + pelvis.points + apli.femur.points + apli.knee_tibia.points
    )
    assert total.percentage == pytest.approx(100 * total.total / 20)


# --- grid rules ------------------------------------------------------------


def test_numeric_grid_points_and_extra_outboard_point():
    grid = [5.5, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -5, -5.5]
    tests = {1: (400.0, 257.0, 20.0), 3: (438.0, 300.0, 29.0),
             5: (385.0, 225.0, 36.0)}

    result = apli_score(grid, tests)

    assert result.femur.scores[5.5] == 1.0          # adjacent only to 5
    assert result.femur.sources[-5.5] == "worst adjacent -5"
    assert result.femur.grid_points == 13


def test_tested_point_overrides_symmetry():
    tests = dict(UPPER_TESTS)
    tests["U+2"] = 5000.0  # tested on the other side too
    result = upper_legform_score(U_GRID, tests)
    assert result.scores["U+2"] == 1.0
    assert result.scores["U-2"] == 0.0


def test_asymmetric_points_do_not_share_results():
    result = upper_legform_score(
        U_GRID, {**UPPER_TESTS, "U+3": 5500.0}, asymmetric_points=["U+4", "U-4"]
    )
    # U+4 cannot take U-4's result; its only neighbour U+3 was tested.
    assert result.scores["U+4"] == 0.5
    assert result.sources["U+4"] == "worst adjacent 'U+3'"


def test_without_symmetry_only_adjacent_results_are_used():
    result = upper_legform_score(
        U_GRID, {"U0": 5260.0, "U-2": 6800.0, "U-4": 4890.0, "U+2": 5000.0,
                 "U+4": 5000.0}, symmetric=False
    )
    assert result.scores["U+1"] == 0.74  # worst of U+2 (1.0) and U0 (0.74)


def test_point_without_any_result_raises():
    with pytest.raises(ValueError, match="needs a test"):
        upper_legform_score(U_GRID, {"U0": 5000.0}, symmetric=False)


# --- upper legform energy --------------------------------------------------


def test_energy_formula():
    e = upper_legform_energy(0.0)
    assert e.nominal_velocity == pytest.approx(11.11)
    assert e.energy == pytest.approx(0.5 * 7.4 * 11.11**2)
    assert e.test_velocity == pytest.approx(math.sqrt(2 * e.energy / 10.5))
    assert e.test_required


def test_energy_160_j_threshold():
    # cos(1.2 alpha) = sqrt(2 * 160 / 7.4) / 11.11 at the threshold.
    alpha_160 = math.degrees(math.acos(math.sqrt(320 / 7.4) / 11.11)) / 1.2
    assert upper_legform_energy(alpha_160).energy == pytest.approx(160.0)
    assert upper_legform_energy(alpha_160 - 0.01).test_required
    assert not upper_legform_energy(alpha_160 + 0.01).test_required
    assert not upper_legform_energy(50.0).test_required  # 114 J


def test_energy_angle_limits():
    assert upper_legform_energy(-5.0).alpha == 0.0
    with pytest.raises(ValueError):
        upper_legform_energy(80.0)


def test_alpha_from_geometry():
    assert upper_legform_alpha((0.0, 500.0), (0.0, 900.0)) == pytest.approx(0.0)
    assert upper_legform_alpha((0.0, 500.0), (300.0, 800.0)) == pytest.approx(45.0)
    assert upper_legform_alpha((0.0, 500.0), (-100.0, 800.0)) < 0
    with pytest.raises(ValueError):
        upper_legform_alpha((0.0, 800.0), (100.0, 500.0))


def test_energies_mark_points_not_required():
    energies = {p: 300.0 for p in U_GRID}
    energies.update({"U+4": 150.0, "U-4": 150.0})

    result = upper_legform_score(U_GRID, {"U0": 5260.0, "U-2": 5500.0},
                                 energies=energies)

    assert result.scores["U-4"] == 1.0
    assert result.sources["U-4"] == "not required (E < 160 J)"
    assert result.scores["U-3"] == 0.5  # worst of U-2 (0.5) and U-4 (1.0)


def test_energy_tolerance_blocks_sharing():
    energies = {p: 300.0 for p in U_GRID}
    energies["U+2"] = 340.0  # 13 % more than U-2: needs its own test
    with pytest.raises(ValueError, match="energy tolerance"):
        upper_legform_score(U_GRID, UPPER_TESTS, energies=energies)

    energies["U+2"] = 325.0  # 8.3 % more: may take U-2's result
    result = upper_legform_score(U_GRID, UPPER_TESTS, energies=energies)
    assert result.sources["U+2"] == "symmetry of 'U-2'"


# --- validation ------------------------------------------------------------


def test_validation():
    with pytest.raises(ValueError, match="Unknown protocol"):
        apli_score(L_GRID, APLI_TESTS, protocol="cncap")
    with pytest.raises(ValueError, match="not a grid point"):
        upper_legform_score(U_GRID, {"U+9": 5000.0})
    with pytest.raises(ValueError, match="Invalid grid point"):
        upper_legform_score(["centre"], {})
    with pytest.raises(ValueError, match="same lateral position"):
        upper_legform_score(["U+1", 1], {1: 5000.0})
    with pytest.raises(ValueError, match="missing"):
        upper_legform_score(U_GRID, UPPER_TESTS, energies={"U0": 300.0})
    with pytest.raises(ValueError, match="between 0 and"):
        vru_score(11.0, 1.0, 1.0, 1.0)
    pelvis_2023 = upper_legform_score(U_GRID, UPPER_TESTS, protocol="euroncap_2023")
    with pytest.raises(ValueError, match="uses 'euroncap_2023'"):
        vru_score(5.0, pelvis_2023, 1.0, 1.0)
    apli = apli_score(L_GRID, APLI_TESTS)
    with pytest.raises(ValueError, match="'femur' score was given for 'pelvis'"):
        vru_score(5.0, apli.femur, 1.0, 1.0)


def test_precomputed_point_scores_are_accepted():
    pre = {p: apli_point_score(*v) for p, v in APLI_TESTS.items()}
    assert isinstance(pre["L+1"], ApliPointScore)
    a = apli_score(L_GRID, pre)
    b = apli_score(L_GRID, APLI_TESTS)
    assert a.femur.points == b.femur.points
