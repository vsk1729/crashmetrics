"""Tests for crashmetrics.materials.corrections and .specimens."""

import numpy as np
import pytest

from crashmetrics.materials import (
    TensileTest,
    clean_tensile,
    correct_compliance,
    luders_plateau,
    mean_curve,
    property_scatter,
    scatter_summary,
    smooth_luders,
    tensile_properties,
)

E = 210_000.0
REH, DIP, REL, AE_END = 320.0, 280.0, 290.0, 0.025


def mild_steel():
    """Elastic to ReH, transient dip to 280, plateau oscillating between
    290 and 296 MPa up to 2.5 % strain, then hardening to Rm."""
    e_el = np.linspace(0.0, REH / E, 60)
    s_el = e_el * E
    e_pl = np.linspace(REH / E + 1e-5, AE_END, 400)
    phase = (e_pl - e_pl[0]) / (AE_END - e_pl[0])
    s_pl = REL + 3.0 + 3.0 * np.cos(2 * np.pi * 8 * phase)       # 290 ... 296
    s_pl[:15] = np.linspace(DIP, REL + 6.0, 15)                    # transient
    e_h = np.linspace(AE_END + 1e-4, 0.30, 600)
    s_h = 296.0 + 700.0 * (e_h - AE_END) ** 0.55 * np.exp(-1.6 * (e_h - AE_END))
    return TensileTest(np.concatenate((e_el, e_pl, e_h)),
                       np.concatenate((s_el, s_pl, s_h)), "mild")


def swift(k=900.0, n=0.2, eps0=0.005, eps_p_max=0.3):
    sig = np.concatenate((np.linspace(0, k * eps0 ** n, 50, endpoint=False),
                          k * (eps0 + np.linspace(0, eps_p_max, 800)) ** n))
    eps = sig / E + np.concatenate((np.zeros(50), np.linspace(0, eps_p_max, 800)))
    return TensileTest(np.expm1(eps), sig * np.exp(-eps), f"K{k:g}")


def test_luders_plateau_found():
    p = luders_plateau(mild_steel())
    assert p is not None
    assert p.upper_yield == pytest.approx(REH)
    assert p.lower_yield == pytest.approx(REL, abs=0.05)      # transient 280 ignored
    assert p.start_strain == pytest.approx(REH / E)
    assert p.end_strain == pytest.approx(AE_END, abs=1.5e-3)
    assert p.elongation == pytest.approx(AE_END - REH / E, abs=1.5e-3)


def test_single_transient_dip_is_rel():
    # The dip to 280 MPa is followed by a steady rise, no later dip: it is
    # the only minimum, so it is ReL.
    t = mild_steel()
    plateau = (t.strain > REH / E) & (t.strain <= AE_END)
    s = t.stress.copy()
    s[plateau] = np.linspace(DIP, 300.0, int(plateau.sum()))
    p = luders_plateau(TensileTest(t.strain, s))
    assert p is not None and p.lower_yield == pytest.approx(DIP)


def test_continuous_yielding_has_no_plateau():
    assert luders_plateau(swift()) is None
    unchanged = smooth_luders(swift())
    assert unchanged.info["luders"] == {"found": False}
    np.testing.assert_array_equal(unchanged.stress, swift().stress)


def test_smooth_luders_flat_and_remove():
    t = mild_steel()
    p = luders_plateau(t)
    flat = smooth_luders(t, p)
    inside = (flat.strain > p.start_strain) & (flat.strain <= p.end_strain)
    assert np.all(flat.stress[inside] == pytest.approx(REL, abs=0.05))
    assert flat.stress.max() == pytest.approx(t.stress.max())
    assert flat.info["luders"]["mode"] == "flat"
    removed = smooth_luders(t, mode="remove")
    shift = removed.info["luders"]["strain_removed"]
    assert shift == pytest.approx(p.end_strain - REL / E, abs=1e-6)
    assert removed.strain[-1] == pytest.approx(t.strain[-1] - shift)
    assert np.all(np.diff(removed.strain) > 0)
    # After removal, hardening starts right at the yield point.
    yield_index = int(np.flatnonzero(removed.stress >= REL)[0])
    assert removed.strain[yield_index] == pytest.approx(REL / E, rel=1e-6)
    with pytest.raises(ValueError, match="mode"):
        smooth_luders(t, mode="cut")


def test_luders_with_noise_and_smoothing():
    t = mild_steel()
    noisy = TensileTest(t.strain, t.stress + np.random.default_rng(4).normal(
        0, 1.0, len(t)))
    raw = luders_plateau(noisy)
    assert raw is not None
    assert raw.upper_yield == pytest.approx(REH, abs=3.0)
    assert raw.lower_yield == pytest.approx(REL, abs=4.0)    # noise lowers the minimum
    assert raw.end_strain == pytest.approx(AE_END, abs=2e-3)
    smooth = luders_plateau(clean_tensile(noisy, smooth=7, toe=False))
    assert smooth is not None
    assert smooth.upper_yield < raw.upper_yield               # the spike is rounded
    assert smooth.lower_yield == pytest.approx(REL, abs=2.0)
    assert smooth.end_strain == pytest.approx(AE_END, abs=2e-3)


def test_compliance_correction():
    ref = swift()
    machine = 1 / 120_000.0 - 1 / E               # strain per MPa from the frame
    soft = TensileTest(ref.strain + ref.stress * machine, ref.stress, "crosshead",
                       {"area_mm2": 30.0, "gauge_length_mm": 80.0})
    assert tensile_properties(soft).modulus == pytest.approx(120_000.0, rel=5e-3)
    fixed = correct_compliance(soft, modulus=E)
    assert tensile_properties(fixed).modulus == pytest.approx(E, rel=1e-6)
    np.testing.assert_allclose(fixed.strain, ref.strain, atol=2e-5)
    assert fixed.info["compliance"]["measured_modulus"] == pytest.approx(
        tensile_properties(soft).modulus)
    assert fixed.info["compliance_mm_per_n"] == pytest.approx(
        fixed.info["compliance"]["strain_per_mpa"] * 80.0 / 30.0)
    with pytest.raises(ValueError, match="no compliance"):
        correct_compliance(ref, modulus=150_000.0)


def test_mean_curve_and_scatter():
    tests = [swift(k) for k in (880.0, 900.0, 920.0)]
    m = mean_curve(tests, points=200)
    assert m.count == 3 and m.names == ("K880", "K900", "K920")
    assert m.strain[-1] == pytest.approx(min(t.strain[-1] for t in tests))
    mid = 150
    stresses = [np.interp(m.strain[mid], t.strain, t.stress) for t in tests]
    assert m.mean[mid] == pytest.approx(np.mean(stresses))
    assert m.std[mid] == pytest.approx(np.std(stresses, ddof=1))
    assert m.minimum[mid] == pytest.approx(min(stresses))
    assert np.all(m.maximum >= m.mean) and np.all(m.mean >= m.minimum)
    curve = m.as_test()
    assert curve.name == "mean" and len(curve) == 200
    assert mean_curve(tests, strain_max=0.1).strain[-1] == 0.1
    with pytest.raises(ValueError, match="strain_max"):
        mean_curve(tests, strain_max=5.0)
    shifted = TensileTest(tests[0].strain + 0.01, tests[0].stress)
    with pytest.raises(ValueError, match="clean them first"):
        mean_curve([shifted])

    sc = property_scatter(tests)
    rm = [tensile_properties(t).tensile_strength for t in tests]
    assert sc["tensile_strength"].mean == pytest.approx(np.mean(rm))
    assert sc["tensile_strength"].cv == pytest.approx(np.std(rm, ddof=1) / np.mean(rm))
    assert sc["modulus"].std < 1e-6 * E * 100
    text = scatter_summary(sc)
    assert text.splitlines()[0].split() == ["mean", "std", "CV", "min", "max"]
    assert "Rm" in text and "GPa" in text
    single = property_scatter(tests[:1])
    assert single["yield_strength"].std == 0.0
