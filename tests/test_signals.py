import math

import numpy as np
import pytest

from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import (
    STANDARD_GRAVITY,
    cfc_filter,
    resample_uniform,
    resultant,
    to_g,
    to_seconds,
)


def sine_gain_db(cfc, frequency, sample_rate):
    """Steady-state gain of the CFC filter for a pure sine."""
    duration = max(0.5, 40.0 / frequency)
    t = np.arange(0.0, duration, 1.0 / sample_rate)
    x = np.sin(2.0 * np.pi * frequency * t)
    y = cfc_filter(t, x, cfc, pad_ms=0.0)
    middle = slice(len(t) // 4, 3 * len(t) // 4)
    return 20.0 * math.log10(np.std(y[middle]) / np.std(x[middle]))


# SAE J211 corridor points: flat to the CFC frequency (+0.5/-1 dB) and
# about -3 dB at FN = 1.65 x CFC.
@pytest.mark.parametrize(
    "cfc, sample_rate",
    [(60, 10_000), (180, 10_000), (600, 20_000), (1000, 20_000)],
)
def test_cfc_frequency_response_matches_j211_corridor(cfc, sample_rate):
    assert sine_gain_db(cfc, 0.1 * cfc, sample_rate) == pytest.approx(
        0.0, abs=0.05
    )
    assert -1.0 <= sine_gain_db(cfc, cfc, sample_rate) <= 0.5
    assert sine_gain_db(cfc, 1.65 * cfc, sample_rate) == pytest.approx(
        -3.0, abs=0.5
    )
    assert sine_gain_db(cfc, 5.0 * cfc, sample_rate) < -24.0


def test_cfc_matches_direct_recursion():
    """Forward-backward pass equals the J211 recursion written out."""
    fs = 10_000.0
    t = np.arange(0.0, 0.05, 1.0 / fs)
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(size=t.size))

    wa = math.tan(math.pi * 600 * 2.0775 / fs)
    d = 1.0 + math.sqrt(2.0) * wa + wa**2
    a0 = wa**2 / d
    b1 = -2.0 * (wa**2 - 1.0) / d
    b2 = (-1.0 + math.sqrt(2.0) * wa - wa**2) / d

    def one_pass(s):
        y = np.empty_like(s)
        x1 = x2 = y1 = y2 = s[0]
        for i, xi in enumerate(s):
            y[i] = a0 * xi + 2 * a0 * x1 + a0 * x2 + b1 * y1 + b2 * y2
            x2, x1, y2, y1 = x1, xi, y1, y[i]
        return y

    expected = one_pass(one_pass(x)[::-1])[::-1]
    actual = cfc_filter(t, x, 600, pad_ms=0.0)

    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-10)


def test_cfc_preserves_constant_and_ramp():
    t = np.arange(0.0, 0.05, 1.0e-4)
    constant = np.full_like(t, 42.0)
    ramp = 3.0 + 1000.0 * t

    np.testing.assert_allclose(cfc_filter(t, constant, 1000), constant)
    # Odd-reflection padding keeps a linear signal exact at the ends.
    np.testing.assert_allclose(cfc_filter(t, ramp, 180), ramp, atol=1e-9)


def test_cfc_is_zero_phase():
    fs = 20_000.0
    t = np.arange(0.0, 0.1, 1.0 / fs)
    pulse = np.exp(-(((t - 0.05) / 0.004) ** 2))

    filtered = cfc_filter(t, pulse, 180)

    assert t[np.argmax(filtered)] == pytest.approx(0.05, abs=1.0 / fs)


def test_cfc_output_has_same_length():
    t = np.arange(0.0, 0.002, 1.0e-4)  # 20 samples, shorter than pad
    y = cfc_filter(t, np.sin(t * 1000), 1000)
    assert y.shape == t.shape


def test_cfc_rejects_low_sample_rate():
    t = np.arange(0.0, 0.1, 1.0e-3)  # 1 kHz
    with pytest.raises(ValueError, match="too low"):
        cfc_filter(t, np.zeros_like(t), 1000)


def test_cfc_rejects_nonuniform_sampling():
    t = np.array([0.0, 1e-4, 2e-4, 4e-4, 5e-4])
    with pytest.raises(ValueError, match="uniformly sampled"):
        cfc_filter(t, np.zeros_like(t), 60)


@pytest.mark.parametrize("cfc", [0, -60, float("nan")])
def test_cfc_rejects_invalid_class(cfc):
    t = np.arange(0.0, 0.01, 1e-4)
    with pytest.raises(ValueError):
        cfc_filter(t, np.zeros_like(t), cfc)


def test_cfc_rejects_non_finite_signal():
    t = np.arange(0.0, 0.01, 1e-4)
    x = np.zeros_like(t)
    x[5] = np.nan
    with pytest.raises(ValueError):
        cfc_filter(t, x, 60)


def test_resultant():
    np.testing.assert_allclose(resultant([3.0], [4.0]), [5.0])
    np.testing.assert_allclose(resultant([1.0], [2.0], [2.0]), [3.0])


def test_resultant_rejects_bad_input():
    with pytest.raises(ValueError):
        resultant([1.0])
    with pytest.raises(ValueError):
        resultant([1.0, 2.0], [1.0])


@pytest.mark.parametrize(
    "unit, value",
    [
        ("g", 1.0),
        ("m/s^2", STANDARD_GRAVITY),
        ("mm/s^2", STANDARD_GRAVITY * 1e3),
        ("mm/ms^2", STANDARD_GRAVITY * 1e-3),
        ("ft/s^2", STANDARD_GRAVITY / 0.3048),
        ("M/S2", STANDARD_GRAVITY),
        ("mm/ms²", STANDARD_GRAVITY * 1e-3),
    ],
)
def test_to_g(unit, value):
    assert to_g([value], unit)[0] == pytest.approx(1.0)


def test_to_g_rejects_unknown_unit():
    with pytest.raises(ValueError, match="Unknown acceleration unit"):
        to_g([1.0], "furlong/fortnight^2")


def test_to_seconds():
    np.testing.assert_allclose(to_seconds([15.0], "ms"), [0.015])
    np.testing.assert_allclose(to_seconds([1.0], "s"), [1.0])
    with pytest.raises(ValueError):
        to_seconds([1.0], "min")


def test_resample_uniform():
    t = np.array([0.0, 0.001, 0.0025, 0.004])
    x = np.array([0.0, 1.0, 2.5, 4.0])

    new_t, new_x = resample_uniform(t, x, 2000.0)

    np.testing.assert_allclose(new_t, [0.0, 0.0005, 0.001, 0.0015,
                                       0.002, 0.0025, 0.003, 0.0035,
                                       0.004])
    np.testing.assert_allclose(new_x, new_t * 1000.0)


def test_lsdyna_style_pipeline_to_hic():
    """mm-ms-kg components -> g, CFC 1000, resultant, HIC15."""
    time_ms = np.arange(0.0, 30.0, 0.05)  # 20 kHz
    pulse_g = 100.0 * np.sin(np.pi * np.clip(time_ms / 10.0, 0, 1))
    g_mm_ms2 = STANDARD_GRAVITY * 1e-3

    ax = 0.8 * pulse_g * g_mm_ms2
    ay = 0.0 * pulse_g * g_mm_ms2
    az = 0.6 * pulse_g * g_mm_ms2

    t = to_seconds(time_ms, "ms")
    filtered = [cfc_filter(t, to_g(c, "mm/ms^2"), 1000) for c in (ax, ay, az)]
    a_res = resultant(*filtered)

    assert np.max(a_res) == pytest.approx(100.0, rel=0.01)

    hic_filtered = calculate_hic(t, a_res, window_ms=15)
    hic_raw = calculate_hic(t, pulse_g, window_ms=15)
    assert hic_filtered.value == pytest.approx(hic_raw.value, rel=0.01)
