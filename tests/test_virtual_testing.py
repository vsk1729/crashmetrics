"""Tests for crashmetrics.virtual_testing (Euro NCAP frontal VTC).

Thresholds from the Euro NCAP Crash Protection Virtual Testing Protocol
v1.0.2 (Sections 5.2-5.4) and the load case matrix and points from the
Frontal Impact Protocol v1.2 (Section 3.3). The score example is worked
by hand below.
"""

import math

import numpy as np
import pytest

from crashmetrics.energy_check import GlobalEnergies, PartEnergies
from crashmetrics.frontal_scoring import Occupant, _limits_for
from crashmetrics.virtual_testing import (
    FRONTAL_LOAD_CASES,
    FRONTAL_SENSORS,
    QUALITY_LIMITS,
    VIRTUAL_NOT_APPLICABLE,
    SensorScore,
    axis_weights,
    check_model_quality,
    frontal_end_time,
    kpi_check,
    kpi_checks,
    model_quality_inputs,
    score_sled_virtual,
    sensor_score,
    validate_load_case,
)

T = np.arange(0.0, 0.12, 1e-4)


def pulse(peak, start, width):
    phase = (T - start) / width
    return np.where((phase > 0) & (phase < 1), peak * np.sin(np.pi * phase) ** 2, 0.0)


# --- Load cases and thresholds ------------------------------------------------------

def test_load_case_matrix():
    assert len(FRONTAL_LOAD_CASES) == 6
    lc1, lc2, lc6 = FRONTAL_LOAD_CASES[1], FRONTAL_LOAD_CASES[2], FRONTAL_LOAD_CASES[6]
    assert (lc1.speed, lc1.driver, lc1.front_passenger) == (50, "hybrid3_50",
                                                            "hybrid3_95")
    assert (lc2.speed, lc2.driver, lc2.front_passenger) == (56, "hybrid3_95",
                                                            "hybrid3_05")
    assert (lc6.driver, lc6.front_passenger) == ("hbm_50", None)
    speeds = sorted({c.speed for c in FRONTAL_LOAD_CASES.values()})
    assert speeds == [35, 50, 56]
    # every Hybrid III load case has chest limits for its speed
    for case in list(FRONTAL_LOAD_CASES.values())[:5]:
        for dummy in (case.driver, case.front_passenger):
            assert "chest_compression" in _limits_for(dummy, case.speed)


def test_quality_limits_from_protocol():
    assert QUALITY_LIMITS["hourglass_ratio"] == 0.10
    assert QUALITY_LIMITS["added_mass_ratio"] == 0.05
    assert QUALITY_LIMITS["added_mass_ratio_separate"] == 0.025
    assert QUALITY_LIMITS["hpoint_dz_mm"] == 10.0
    assert QUALITY_LIMITS["sled_x_score"] == 0.95
    assert set(FRONTAL_SENSORS) == {"head", "chest_acceleration", "chest_deflection",
                                    "pelvis", "sled", "shoulder_belt"}
    assert VIRTUAL_NOT_APPLICABLE == ("knee_displacement", "tibia_index", "tibia_force")


# --- Model quality --------------------------------------------------------------------

def test_model_quality_limits_are_strict():
    ok = check_model_quality(0.0999, 0.0499, 9.9)
    assert ok.passed and ok.complete
    at_limit = check_model_quality(0.10, 0.05, 10.0)
    assert at_limit.failures == ["hourglass_ratio", "added_mass_ratio", "hpoint_dz_mm"]
    separate = check_model_quality(0.05, 0.03, 2.0, separate_models=True,
                                   sled_x_score=0.95)
    assert separate.failures == ["added_mass_ratio", "sled_x_score"]
    partial = check_model_quality(0.05, None, None, {"driver": 0.12})
    assert partial.failures == ["hourglass_ratio[driver]"]
    assert partial.not_assessed == ["added_mass_ratio", "hpoint_dz_mm"]
    with pytest.raises(ValueError, match="finite"):
        check_model_quality(math.nan, 0.01, 1.0)


def test_model_quality_inputs_from_energies():
    t = np.linspace(0.0, 0.1, 11)
    glstat = GlobalEnergies(time=t, kinetic=100 - 50 * t, internal=500 * t,
                            hourglass=20 * t, added_mass_percent=np.full(11, 1.2))
    matsum = PartEnergies(
        time=t, part_ids=np.array([1, 2, 3]),
        internal=np.column_stack([100 * t, 300 * t, 100 * t]),
        hourglass=np.column_stack([3 * t, 9 * t, 8 * t]))
    out = model_quality_inputs(glstat, matsum, {"driver": [1, 2], "passenger": [3]})
    assert out["hourglass_ratio"] == pytest.approx(0.04)
    assert out["added_mass_ratio"] == pytest.approx(0.012)
    assert out["dummy_hourglass_ratios"] == pytest.approx({"driver": 0.03,
                                                           "passenger": 0.08})
    result = check_model_quality(hpoint_dz_mm=1.0, **out)
    assert result.passed
    with pytest.raises(ValueError, match="not in matsum"):
        model_quality_inputs(glstat, matsum, {"driver": [9]})


def test_frontal_end_time():
    head_x = pulse(400.0, 0.0, 0.16)                # maximum at 80 ms
    assert frontal_end_time(T, head_x) == pytest.approx(0.112)
    assert frontal_end_time(T, -head_x, t0=0.01) == pytest.approx(0.01 + 1.4 * 0.07)


# --- Sensor score and KPI -----------------------------------------------------------

def test_axis_weights():
    w = axis_weights({"x": -60.0 * np.ones(3), "y": [0.0, 10.0, -5.0], "z": [30.0]})
    assert w == pytest.approx({"x": 0.6, "y": 0.1, "z": 0.3})
    assert axis_weights({"force": [1.0, 2.0]}) == {"force": 1.0}
    assert axis_weights({"x": [0.0], "y": [0.0]}) == {"x": 0.5, "y": 0.5}
    with pytest.raises(ValueError):
        axis_weights({})


def test_sensor_score_weights_axes_by_test_peaks():
    test = {"x": pulse(-45.0, 0.02, 0.06), "y": pulse(5.0, 0.03, 0.05),
            "z": pulse(10.0, 0.03, 0.05)}
    same = sensor_score("head", T, test, test)
    assert same.score == pytest.approx(1.0)
    sim = dict(test, y=-test["y"])                          # y has the wrong sign
    s = sensor_score("head", T, test, sim)
    assert s.weights == pytest.approx({"x": 0.75, "y": 1 / 12, "z": 1 / 6})
    assert s.axis_scores["x"] == pytest.approx(1.0)
    assert s.axis_scores["y"] < 0.5
    assert s.score == pytest.approx(sum(s.weights[a] * s.axis_scores[a] for a in test))
    with pytest.raises(ValueError, match="differ"):
        sensor_score("head", T, test, {"x": test["x"]})


def test_kpi_check_rules():
    k = kpi_check("hic15", 420.0, 600.0, 700.0)              # rAC 0.60 vs 0.857
    assert k.r_test == pytest.approx(0.6) and k.deviation == pytest.approx(0.2571, 1e-3)
    assert k.passed is True
    assert kpi_check("hic15", 420.0, 630.0, 700.0).passed is False   # dAC 0.30
    low = kpi_check("neck_tension", 1600.0, 3200.0, 3300.0)  # rAC test 0.485
    assert low.deviation is None and low.passed is None
    edge = kpi_check("femur_force", 4550.0, 4550.0, 9100.0)  # exactly 50 %
    assert edge.deviation == 0.0 and edge.passed
    with pytest.raises(ValueError):
        kpi_check("hic15", 1.0, 1.0, 0.0)


def test_kpi_checks_use_lpl_and_skip_virtual_na():
    results = kpi_checks("hybrid3_05", {"hic15": 500, "chest_compression": 30,
                                        "knee_displacement": 12, "femur_force": 100},
                         {"hic15": 520, "chest_compression": 33,
                          "knee_displacement": 2}, speed=56)
    assert [r.criterion for r in results] == ["hic15", "chest_compression"]
    assert results[1].limit == 42.0                          # 5th at 56 km/h LPL
    with pytest.raises(ValueError, match="No limit"):
        kpi_checks("hybrid3_50", {"acetabulum_force": 1.0},
                   {"acetabulum_force": 1.0}, 50)


def _scores(value):
    return {name: SensorScore(name, value, dict.fromkeys(axes, value),
                              dict.fromkeys(axes, 1.0 / len(axes)))
            for name, axes in FRONTAL_SENSORS.items()}


def test_validate_load_case():
    quality = check_model_quality(0.04, 0.01, 2.0)
    kpis = [kpi_check("hic15", 420.0, 470.0, 700.0),
            kpi_check("neck_tension", 900.0, 2000.0, 3300.0)]   # test < 50 %
    result = validate_load_case("LC1 driver", _scores(0.8), kpis, quality)
    assert result.passed and result.complete
    assert "dAC_neck_tension" not in result.checks
    assert any("below 50 %" in n for n in result.notes)
    assert "VTC validation (LC1 driver): PASS" in result.summary()

    scores = _scores(0.8)
    scores["shoulder_belt"] = SensorScore("shoulder_belt", 0.5, {"force": 0.5},
                                          {"force": 1.0})
    scores["femur"] = SensorScore("femur", 0.2, {"z": 0.2}, {"z": 1.0})
    del scores["sled"]
    result = validate_load_case("LC3 passenger", scores)
    assert result.failures == ["iso_shoulder_belt"]           # must exceed 0.5
    assert result.not_assessed == ["iso_sled"]
    assert any(n.startswith("monitored: femur") for n in result.notes)
    assert any("plausibility: shoulder_belt" in n for n in result.notes)
    assert "FAIL (1 not assessed)" in result.summary()


# --- Scoring --------------------------------------------------------------------------

GREEN = dict(hic15=300.0, head_a3ms=40.0, neck_shear=500.0, neck_tension=800.0,
             neck_extension=10.0, chest_compression=10.0, viscous_criterion=0.2,
             femur_force=1500.0)
LOWER = dict(knee_displacement=2.0, tibia_index=0.2, tibia_force=1000.0)


def occupant(virtual=False, **changes):
    values = dict(GREEN, **({} if virtual else LOWER))
    values.update(changes)
    return Occupant(values, hard_contact=True)


def test_score_worked_example():
    """Driver, sled load cases 1 and 3, virtual 2, 4 and 5.

    LC1 (H-III 50th, 50 km/h): chest 30 mm, (30 - 20) / (42 - 20) = 0.45
    -> orange, 60 % of 0.3125 = 0.1875; other regions green: 1.125.
    LC3 (50th, 35 km/h): all green, 1.25. Sled 2.375.
    LC2 (H-III 95th, 56 km/h): femur 8.0 kN, (8000 - 4800) / 6700 = 0.48
    -> orange, 0.6 x 0.625 / 3 = 0.125; head and chest green 0.4167: 0.5417.
    LC4 and LC5 (5th): green, 0.625 each. Lower leg by default 0.625.
    Virtual 2.4167. Total 4.7917.
    """
    result = score_sled_virtual(
        "driver",
        sled={1: occupant(chest_compression=30.0), 3: occupant()},
        virtual={2: occupant(True, femur_force=8000.0), 4: occupant(True),
                 5: occupant(True)},
    )
    assert result.sled[1].dummy == "hybrid3_50"
    assert result.virtual[2].dummy == "hybrid3_95"
    assert result.sled[1].regions["chest_abdomen"].band == "orange"
    assert result.sled[1].points == pytest.approx(1.125)
    assert result.sled_points == pytest.approx(2.375)
    assert result.virtual[2].points == pytest.approx(0.625 / 3 * 2 + 0.125)
    assert "lower_leg" not in result.virtual[2].regions
    assert result.lower_leg_virtual_points == pytest.approx(0.625)
    assert result.virtual_points == pytest.approx(2.416667, abs=1e-6)
    assert result.points == pytest.approx(4.791667, abs=1e-6)
    assert result.max_points == 5.0
    text = result.summary()
    assert "4.792 / 5.0" in text and "virtual LC2 hybrid3_95" in text


def test_score_rules_validation_hbm_and_tibia():
    sled = {1: occupant(), 3: occupant()}
    virtual = {2: occupant(True), 4: occupant(True), 5: occupant(True)}
    full = score_sled_virtual("driver", sled, virtual)
    assert full.points == pytest.approx(5.0)
    not_valid = score_sled_virtual("driver", sled, virtual, validated=False)
    assert not_valid.points == pytest.approx(2.5) and not_valid.virtual_points == 0.0
    assert "sled load cases only" in not_valid.notes[0]
    no_hbm = score_sled_virtual("driver", sled, virtual, hbm_provided=False)
    assert no_hbm.virtual_points == pytest.approx(1.25)
    tibia = score_sled_virtual("driver", sled, virtual, tibia_lpl_exceeded=True)
    assert tibia.virtual_points == pytest.approx(2.5 - 0.625)


def test_passenger_uses_passenger_dummies():
    result = score_sled_virtual(
        "front_passenger", {1: occupant(), 2: occupant()},
        {3: occupant(True), 4: occupant(True), 5: occupant(True)})
    assert result.sled[1].dummy == "hybrid3_95" and result.sled[2].dummy == "hybrid3_05"
    assert result.virtual[4].dummy == "hybrid3_50"
    assert result.points == pytest.approx(5.0)


def test_score_input_errors():
    three = {2: occupant(True), 4: occupant(True), 5: occupant(True)}
    with pytest.raises(ValueError, match="position"):
        score_sled_virtual("rear", {1: occupant(), 3: occupant()}, three)
    with pytest.raises(ValueError, match="two sled and three"):
        score_sled_virtual("driver", {1: occupant()}, three)
    with pytest.raises(ValueError, match="both sled and virtual"):
        score_sled_virtual("driver", {2: occupant(), 3: occupant()}, three)
    with pytest.raises(ValueError, match="among"):
        score_sled_virtual("driver", {1: occupant(), 6: occupant()}, three)
    with pytest.raises(ValueError, match="Missing value"):
        score_sled_virtual("driver", {1: occupant(True), 3: occupant()}, three)
