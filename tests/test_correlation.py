import math

import numpy as np
import pytest

from crashmetrics.correlation import (
    CORAParameters,
    ISO18571Parameters,
    compare,
    cora,
    error_measures,
    iso18571,
    iso18571_grade,
    resample_pair,
)
from crashmetrics.features import feature_table, flatten

T = np.arange(0.0, 0.12, 1e-4)


def pulse(amp, start, width, t=T):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), amp * np.sin(np.pi * phase), 0.0)


# --- ISO/TS 18571 against an independent implementation --------------------
# Reference values from objective-rating-metrics 1.3 (Vehicle Safety
# Institute, TU Graz, MIT licence), an ISO/TS 18571:2024 implementation.
# Only the numbers are used here.

REFERENCE_CASES = {
    # name: (reference, comparison, [corridor, phase, magnitude, slope, rating])
    "scaled_late": (
        pulse(80, 0.010, 0.040), pulse(92, 0.013, 0.040),
        [0.839534983522, 0.875, 0.927992423471, 0.925, 0.881412478103],
    ),
    "early_narrow": (
        pulse(-60, 0.020, 0.050), pulse(-55, 0.017, 0.042),
        [0.74994231529, 0.708333333333, 0.958078252416, 0.796139356307,
         0.792487114527],
    ),
    "double_hit": (
        pulse(100, 0.010, 0.030) + pulse(60, 0.034, 0.020), pulse(110, 0.011, 0.034),
        [0.840377690545, 0.9875, 0.947623885959, 0.552272979515, 0.833630449313],
    ),
}


@pytest.mark.parametrize("name", REFERENCE_CASES)
def test_iso18571_matches_reference_implementation(name):
    ref, comp, expected = REFERENCE_CASES[name]
    r = iso18571(T, ref, comp)
    got = [r.corridor, r.phase, r.magnitude, r.slope, r.rating]
    assert got == pytest.approx(expected, abs=1e-10)


def test_iso18571_readme_examples_of_reference_implementation():
    t = np.arange(0, 0.150, 0.0001)
    scaled = iso18571(t, np.sin(t * 20), np.sin(t * 20) * 1.3)
    assert round(scaled.rating, 3) == 0.713
    assert scaled.grade == "fair"
    # different time bases: the common interval is used
    shifted = iso18571(t + 0.02, np.sin(t * 20), np.sin(t * 20),
                       comparison_time=t + 0.03)
    assert round(shifted.rating, 3) == 0.815
    assert shifted.time_shift_ms == pytest.approx(10.0)      # comparison late
    assert shifted.t_start == pytest.approx(0.03)


def test_iso18571_identical_signals_score_one():
    ref = pulse(50, 0.01, 0.05)
    r = iso18571(T, ref, ref)
    assert r.rating == pytest.approx(1.0)
    assert (r.corridor, r.phase, r.magnitude, r.slope) == pytest.approx((1, 1, 1, 1))
    assert r.grade == "excellent"
    assert r.time_shift_ms == 0.0 and r.n_points == len(T)


def test_iso18571_time_shift_sign_and_phase_score():
    ref = pulse(50, 0.02, 0.04)
    late = iso18571(T, ref, pulse(50, 0.026, 0.04))
    early = iso18571(T, ref, pulse(50, 0.014, 0.04))
    assert late.time_shift_ms == pytest.approx(6.0)
    assert early.time_shift_ms == pytest.approx(-6.0)
    # phase falls linearly to 0 at 20 % of the interval (24 ms here)
    assert late.phase == pytest.approx(1 - 60 / (0.2 * len(T)))
    assert late.magnitude == pytest.approx(1.0) and late.slope == pytest.approx(1.0)


def test_iso18571_corridor_closed_form():
    # constant offset of 10 % of the peak: between the corridors,
    # ((0.5 - 0.1) / (0.5 - 0.05))^2 everywhere
    ref = pulse(100, 0.0, 0.12)
    r = iso18571(T, ref, ref + 10.0)
    assert r.corridor == pytest.approx((0.4 / 0.45) ** 2)


def test_iso18571_magnitude_and_slope_of_a_scaled_signal():
    ref = pulse(100, 0.01, 0.05)
    r = iso18571(T, ref, 1.2 * ref)
    # Time warping absorbs part of a pure scaling (it pairs the larger
    # comparison values with earlier, smaller reference values), so the
    # magnitude error is below the plain 20 %.
    assert 0.0 < r.magnitude_error < 0.2
    assert r.magnitude == pytest.approx(1 - r.magnitude_error / 0.5)
    # The slope has no warping: exactly 20 % error.
    assert r.slope_error == pytest.approx(0.2, rel=1e-6)
    assert r.slope == pytest.approx(1 - 0.2 / 2.0, rel=1e-6)


def test_iso18571_parameters_and_interval():
    ref, comp = pulse(80, 0.01, 0.04), pulse(70, 0.012, 0.04)
    window = iso18571(T, ref, comp, t_start=0.0, t_end=0.06)
    assert window.t_end == pytest.approx(0.06) and window.n_points == 601
    corridor_only = iso18571(T, ref, comp, parameters=ISO18571Parameters(
        w_z=1.0, w_p=0.0, w_m=0.0, w_s=0.0))
    assert corridor_only.rating == pytest.approx(corridor_only.corridor)
    with pytest.raises(ValueError, match="add up to 1"):
        iso18571(T, ref, comp, parameters=ISO18571Parameters(w_z=0.5))


@pytest.mark.parametrize("rating, grade", [
    (0.95, "excellent"), (0.94, "good"), (0.81, "good"), (0.80, "fair"),
    (0.59, "fair"), (0.58, "poor"), (0.0, "poor"),
])
def test_iso18571_grades(rating, grade):
    assert iso18571_grade(rating) == grade


# --- CORA ---------------------------------------------------------------------


def test_cora_identical_signals_score_one():
    ref = pulse(50, 0.01, 0.05)
    r = cora(T, ref, ref)
    assert r.rating == pytest.approx(1.0)
    assert (r.phase, r.size, r.shape) == pytest.approx((1, 1, 1))


def test_cora_size_and_shape_of_a_scaled_signal():
    ref = pulse(100, 0.01, 0.05)
    r = cora(T, ref, 1.25 * ref)
    assert r.size == pytest.approx(1 / 1.25**2)
    assert r.shape == pytest.approx(1.0) and r.phase == 1.0
    assert r.cross_correlation == pytest.approx((1 + 1 / 1.25**2 + 1) / 3)
    assert r.rating == pytest.approx(0.5 * r.corridor + 0.5 * r.cross_correlation)


def test_cora_phase_between_d_min_and_d_max():
    # interval 119.9 ms: full points up to 1.2 ms, zero from 14.4 ms
    ref = pulse(50, 0.02, 0.04)
    duration = (len(T) - 1) * 1e-4
    r = cora(T, ref, pulse(50, 0.026, 0.04))
    assert r.time_shift_ms == pytest.approx(6.0)
    expected = (0.12 * duration - 0.006) / ((0.12 - 0.01) * duration)
    assert r.phase == pytest.approx(expected)
    assert r.shape == pytest.approx(1.0) and r.size == pytest.approx(1.0)
    assert cora(T, ref, pulse(50, 0.0205, 0.04)).phase == 1.0
    assert cora(T, ref, pulse(50, 0.036, 0.04)).phase == 0.0


def test_cora_parameters():
    ref, comp = pulse(10, 0.01, 0.04), pulse(9, 0.012, 0.04)
    wide = cora(T, ref, comp, parameters=CORAParameters(norm=100.0))
    assert wide.corridor == pytest.approx(1.0)      # small signal, large norm
    with pytest.raises(ValueError, match="add up to 1"):
        cora(T, ref, comp, parameters=CORAParameters(w_phase=0.5))
    with pytest.raises(ValueError, match="d_min"):
        cora(T, ref, comp, parameters=CORAParameters(d_min=0.2))


# --- Error measures ---------------------------------------------------------


def test_error_measures_of_a_scaled_signal():
    ref = pulse(100, 0.01, 0.05)
    e = error_measures(T, ref, 1.2 * ref)
    assert e.peak_error == pytest.approx(0.2)
    assert e.peak_time_error_ms == pytest.approx(0.0)
    assert e.correlation == pytest.approx(1.0)
    assert e.sprague_geers_magnitude == pytest.approx(0.2)
    assert e.sprague_geers_phase == pytest.approx(0.0, abs=1e-6)
    assert e.sprague_geers_comprehensive == pytest.approx(0.2, abs=1e-6)
    rel = (1.44 - 1) / 1.2
    assert e.russell_magnitude == pytest.approx(math.log10(1 + rel))
    assert e.russell_comprehensive == pytest.approx(
        math.sqrt(math.pi / 4) * math.log10(1 + rel), abs=1e-6)
    assert e.max_error == pytest.approx(20.0, rel=1e-6)
    assert e.nrmse == pytest.approx(e.rmse / 100.0, rel=1e-6)


def test_error_measures_quarter_period_shift():
    # sine against cosine over whole periods: orthogonal, phase error 0.5
    t = np.arange(0.0, 0.1, 1e-5)
    e = error_measures(t, np.sin(2 * np.pi * 50 * t), np.cos(2 * np.pi * 50 * t))
    assert e.sprague_geers_phase == pytest.approx(0.5, abs=1e-3)
    assert e.sprague_geers_magnitude == pytest.approx(0.0, abs=1e-3)
    assert e.correlation == pytest.approx(0.0, abs=1e-3)


def test_error_measures_peak_timing_and_r_squared():
    ref = pulse(-80, 0.02, 0.04)
    e = error_measures(T, ref, pulse(-72, 0.023, 0.04))
    assert e.peak_reference == pytest.approx(-80.0, rel=1e-6)
    assert e.peak_error == pytest.approx(-0.1, rel=1e-6)
    assert e.peak_time_error_ms == pytest.approx(3.0)
    assert e.r_squared < 1.0
    assert e.russell_phase == e.sprague_geers_phase


# --- Common grid, compare, feature tables -----------------------------------


def test_resample_pair_common_interval_and_errors():
    t_cae = np.arange(0.005, 0.2, 1e-5)
    t, r, c = resample_pair(T, np.ones_like(T), 2 * np.ones_like(t_cae),
                            comparison_time=t_cae)
    assert t[0] == pytest.approx(0.005) and t[-1] == pytest.approx(0.1199, abs=1e-9)
    assert np.allclose(np.diff(t), 1e-4)
    assert np.all(r == 1.0) and np.all(c == 2.0)
    with pytest.raises(ValueError, match="not covered"):
        resample_pair(T, np.ones_like(T), np.ones_like(T), t_end=0.5)
    with pytest.raises(ValueError, match="finite"):
        resample_pair(T, np.full_like(T, np.nan), np.ones_like(T))
    with pytest.raises(ValueError, match="10 samples"):
        resample_pair(T, np.ones_like(T), np.ones_like(T), t_end=0.0005)


def test_zero_reference_is_rejected():
    with pytest.raises(ValueError, match="zero"):
        iso18571(T, np.zeros_like(T), pulse(1, 0.01, 0.02))


def test_compare_and_feature_table():
    ref, comp = pulse(80, 0.01, 0.04), pulse(92, 0.013, 0.04)
    c = compare(T, ref, comp, channel="head_ax")
    assert c.iso == iso18571(T, ref, comp)
    assert c.cora == cora(T, ref, comp)
    assert "head_ax: ISO 18571 0.881 (good" in c.summary()
    flat = flatten(c, prefix="head_")
    assert flat["head_iso.rating"] == pytest.approx(0.881412478103)
    assert flat["head_cora.size"] == c.cora.size
    assert flat["head_errors.peak_error"] == pytest.approx(0.15, rel=1e-3)

    runs = {"v1": (ref, comp), "v2": (ref, ref), "bad": (ref, np.zeros(3))}
    rows = feature_table(runs, lambda pair: compare(T, *pair).iso)
    assert rows[1]["rating"] == pytest.approx(1.0)
    assert "error" in rows[2]
