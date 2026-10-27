import numpy as np
import pytest

from crashmetrics.side import (
    es2_abdominal_force,
    es2_rib_deflection,
    es2_rib_vc,
    pubic_symphysis_force,
)
from crashmetrics.thorax import VC_CONSTANTS


def test_es2_rib_deflection_worst_rib():
    t = np.array([0.0, 0.01, 0.02])
    result = es2_rib_deflection(t, [0, 20, 5], [0, 31.5, 10], [0, 12, 28])
    assert result.value == 31.5 and result.rib == "middle" and result.time == 0.01
    assert result.per_rib == {"upper": 20.0, "middle": 31.5, "lower": 28.0}


def test_es2_rib_vc_sinusoid():
    # D = A sin(w t): VC max = A^2 w / (2 * 0.140) with sf 1.0 (AIS-197).
    assert VC_CONSTANTS["es2"] == (1.0, 0.140)
    amplitude, w = 0.03, 2 * np.pi / 0.04
    t = np.linspace(0.0, 0.02, 2001)
    d = 1000.0 * amplitude * np.sin(w * t)
    result = es2_rib_vc(t, 0.5 * d, d, 0.8 * d)
    assert result.rib == "middle"
    assert result.value == pytest.approx(amplitude**2 * w / (2 * 0.140), rel=1e-5)


def test_abdominal_force_is_peak_of_sum():
    t = np.array([0.0, 0.01, 0.02])
    # Individual peaks at different times; the sum peaks at 10 ms.
    result = es2_abdominal_force(t, [0, 800, 900], [0, 700, 100], [0, 600, 0])
    assert result.value == pytest.approx(2100.0) and result.time == 0.01


def test_pubic_symphysis_force_magnitude():
    t = np.array([0.0, 0.01, 0.02])
    assert pubic_symphysis_force(t, [0.0, -3500.0, 1200.0]).value == 3500.0
