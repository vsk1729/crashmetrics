"""Tests for crashmetrics.materials.hardening.

Synthetic materials with a known hardening law (true stress against
effective plastic strain) are converted to engineering curves; the
chain must give the law back.
"""

import math

import numpy as np
import pytest

from crashmetrics.materials import (
    LAWS,
    TensileTest,
    compare_fits,
    extrapolate_curve,
    fit_hardening,
    n_value,
    necking_point,
    plastic_curve,
    true_curve,
)

E = 210_000.0


def material(law, p_max=0.4, points=2000):
    """Engineering curve of a law sigma(eps_p), elastic part included."""
    p = np.linspace(0.0, p_max, points)
    sig = law(p)
    sig_el = np.linspace(0.0, sig[0], 40, endpoint=False)
    s_true = np.concatenate((sig_el, sig))
    eps = s_true / E + np.concatenate((np.zeros(40), p))
    return TensileTest(np.expm1(eps), s_true * np.exp(-eps))


def swift_law(p, k=950.0, e0=0.006, n=0.21):
    return k * (e0 + p) ** n


def voce_law(p, s0=350.0, q=280.0, b=12.0):
    return s0 + q * (1 - np.exp(-b * p))


def test_true_curve_conversion_and_cut_at_necking():
    t = material(swift_law)
    tc = true_curve(t)
    peak = int(np.argmax(t.stress))
    assert len(tc.strain) == peak + 1
    np.testing.assert_allclose(tc.strain, np.log1p(t.strain[: peak + 1]))
    np.testing.assert_allclose(tc.stress, t.stress[: peak + 1] * (1 + t.strain[
        : peak + 1]))
    assert len(true_curve(t, after_necking=True).strain) == len(t)


def test_necking_point_satisfies_considere():
    t = material(swift_law)
    neck = necking_point(t)
    # Swift: necking at d sigma / d eps_true = sigma; with E large,
    # eps_p,neck ~ n - eps0 (Considère).
    p_neck = math.log1p(neck.engineering_strain) - neck.true_stress / E
    assert p_neck == pytest.approx(0.21 - 0.006, abs=2e-3)
    assert neck.considere_ratio == pytest.approx(1.0, abs=0.02)
    assert neck.engineering_stress == pytest.approx(t.stress.max(), rel=1e-5)
    with pytest.raises(ValueError, match="window"):
        necking_point(t, window=0.0)
    with pytest.raises(ValueError, match="Fewer than 5"):
        necking_point(t, window=1e-6)


def test_plastic_curve_recovers_the_law():
    t = material(swift_law)
    zero = plastic_curve(t, start="zero", modulus=E)
    assert zero.plastic_strain[0] == 0.0
    np.testing.assert_allclose(zero.stress, swift_law(zero.plastic_strain), rtol=1e-6)
    assert zero.yield_stress == pytest.approx(swift_law(0.0), rel=1e-6)
    offset = plastic_curve(t, modulus=E)               # starts at Rp0.2
    assert offset.yield_stress == pytest.approx(swift_law(0.002), rel=1e-5)
    np.testing.assert_allclose(offset.stress, swift_law(offset.plastic_strain + 0.002),
                               rtol=1e-6)
    assert offset.necking_strain == pytest.approx(zero.necking_strain - 0.002,
                                                  abs=2e-4)
    assert np.all(np.diff(offset.plastic_strain) > 0)
    fitted_e = plastic_curve(t)                         # E fitted on the curve
    assert fitted_e.modulus == pytest.approx(E, rel=3e-3)


def test_swift_fit_recovers_the_parameters():
    curve = plastic_curve(material(swift_law), start="zero", modulus=E)
    fits = fit_hardening(curve, ["swift", "voce"])
    sw = fits["swift"]
    assert sw.params["K"] == pytest.approx(950.0, rel=1e-3)
    assert sw.params["eps0"] == pytest.approx(0.006, rel=1e-2)
    assert sw.params["n"] == pytest.approx(0.21, rel=1e-3)
    assert sw.rms < 0.05 and sw.r2 > 0.999999
    assert sw.considere_ratio == pytest.approx(1.0, abs=0.01)
    np.testing.assert_allclose(sw.stress([0.5, 1.0]), swift_law(np.array([0.5, 1.0])),
                               rtol=2e-3)
    assert fits["voce"].rms > sw.rms


def test_voce_and_hockett_sherby_fits():
    curve = plastic_curve(material(voce_law, p_max=0.3), start="zero", modulus=E)
    fits = fit_hardening(curve)
    assert set(fits) == set(LAWS)
    vo = fits["voce"]
    assert vo.params["sigma0"] == pytest.approx(350.0, rel=1e-3)
    assert vo.params["Q"] == pytest.approx(280.0, rel=1e-2)
    assert vo.params["beta"] == pytest.approx(12.0, rel=1e-2)
    # Hockett-Sherby contains Voce (m = 1); Swift-Voce contains Voce (alpha 0).
    assert fits["hockett_sherby"].rms < 0.5
    assert fits["swift_voce"].rms <= fits["voce"].rms * 1.5 + 0.05
    assert fits["hockett_sherby"].params["sigma_s"] > fits["hockett_sherby"].params[
        "sigma0"]
    assert 0.0 <= fits["swift_voce"].params["alpha"] <= 1.0
    with pytest.raises(ValueError, match="Unknown laws"):
        fit_hardening(curve, ["johnson"])


def test_fit_range_and_compare_table():
    curve = plastic_curve(material(swift_law), modulus=E)
    fits = fit_hardening(curve, ["swift", "voce"],
                         fit_range=(0.02, curve.necking_strain))
    assert fits["swift"].fit_range[0] == 0.02
    table = compare_fits(fits, strains=(0.1, 1.0))
    lines = table.splitlines()
    assert lines[0].split()[:4] == ["law", "RMS", "MPa", "R2"]
    assert lines[1].startswith("swift") and lines[2].startswith("voce")
    # Voce saturates: below Swift at large strain.
    assert fits["voce"].stress(1.0)[()] < fits["swift"].stress(1.0)[()]
    with pytest.raises(ValueError, match="Fewer than 5"):
        fit_hardening(curve, fit_range=(0.5, 0.6))


def test_extrapolated_curve():
    curve = plastic_curve(material(swift_law), modulus=E)
    fit = fit_hardening(curve, ["swift"])["swift"]
    full = extrapolate_curve(curve, fit, strain_max=1.0, points=20)
    assert full.plastic_strain[-1] == 1.0
    assert len(full.plastic_strain) == len(curve.plastic_strain) + 20
    assert np.all(np.diff(full.plastic_strain) > 0)
    assert np.all(np.diff(full.stress) > 0)
    assert full.info["extrapolation"]["law"] == "swift"
    assert abs(full.info["extrapolation"]["shift"]) < 0.5
    np.testing.assert_allclose(full.stress[-1], swift_law(1.002), rtol=3e-3)
    with pytest.raises(ValueError, match="above the necking"):
        extrapolate_curve(curve, fit, strain_max=0.05)


def test_n_value():
    # Hollomon in plastic strain: n and K come back with strain="plastic".
    t = material(lambda p: 900.0 * np.maximum(p, 1e-9) ** 0.18 + 0.0 * p, p_max=0.3)
    nv = n_value(t, strain="plastic", modulus=E)
    assert nv.n == pytest.approx(0.18, rel=1e-3)
    assert nv.k == pytest.approx(900.0, rel=2e-3)
    assert nv.r2 > 0.99999
    assert nv.strain_range[0] == 0.10
    total = n_value(t)                                  # total true strain
    assert total.n == pytest.approx(0.18, abs=0.01)
    fixed = n_value(t, strain_range=(0.10, 0.15))
    assert fixed.strain_range == (0.10, 0.15)
    with pytest.raises(ValueError, match="Invalid strain range"):
        n_value(t, strain_range=(0.5, None))
