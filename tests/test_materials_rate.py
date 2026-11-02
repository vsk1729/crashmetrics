"""Tests for crashmetrics.materials.rate.

Hardening curves at several strain rates are generated from a Swift
static curve and a known rate law; the fits must give the law back.
"""

import math

import numpy as np
import pytest

from crashmetrics.materials import (
    UNIT_SYSTEMS,
    CowperSymonds,
    HardeningCurve,
    RateTable,
    fit_cowper_symonds,
    fit_johnson_cook_rate,
    rate_table_from_curves,
    rate_table_from_model,
)

C, P = 40.4, 5.0                       # classic mild steel values
RATES = (0.001, 1.0, 10.0, 100.0, 500.0)


def static(p):
    return 900.0 * (0.005 + p) ** 0.2


def cs_factor(rate):
    return 1.0 + (rate / C) ** (1.0 / P)


def curve(rate, factor=cs_factor, p_max=0.15):
    p = np.linspace(0.0, p_max, 300)
    return HardeningCurve(p, static(p) * factor(rate), 210_000.0, p_max, f"{rate}")


def curves(factor=cs_factor, p_max=0.15):
    return {r: curve(r, factor, p_max) for r in RATES}


def test_cowper_symonds_recovers_c_and_p():
    fit = fit_cowper_symonds(curves())
    assert fit.c == pytest.approx(C, rel=1e-4)
    assert fit.p == pytest.approx(P, rel=1e-4)
    assert fit.reference_rate == 0.001
    assert fit.rms < 1e-8
    assert fit.points == 4 * 6
    np.testing.assert_allclose(fit.factor([0.0, 100.0]), [1.0, cs_factor(100.0)],
                               rtol=1e-6)
    assert fit.ratio(0.001) == pytest.approx(1.0)


def test_cowper_symonds_with_a_slow_reference_and_errors():
    # The reference test at 0.001 /s is not static; the fit accounts for it.
    fit = fit_cowper_symonds(curves(), strains=[0.0, 0.05, 0.1])
    assert fit.c == pytest.approx(C, rel=1e-4)
    with pytest.raises(ValueError, match="two or more"):
        fit_cowper_symonds({1.0: curve(1.0)})
    with pytest.raises(ValueError, match="no rate effect"):
        fit_cowper_symonds(curves(lambda r: 1.0))
    with pytest.raises(ValueError, match="measured range"):
        fit_cowper_symonds(curves(), strains=[0.5])
    with pytest.raises(ValueError, match="reference rate"):
        fit_cowper_symonds(curves(), reference_rate=2.0)


def test_johnson_cook_rate():
    jc = lambda r: 1.0 + 0.014 * max(math.log(r / 0.001), 0.0)   # noqa: E731
    fit = fit_johnson_cook_rate(curves(jc))
    assert fit.c == pytest.approx(0.014, rel=1e-9)
    assert fit.rms < 1e-12
    assert fit.ratio(1e-4) == 1.0                    # no effect below rate0
    assert fit.ratio(100.0) == pytest.approx(jc(100.0))
    with pytest.raises(ValueError, match="positive"):
        fit.ratio(0.0)


def test_rate_table_from_model_and_keyword():
    law = fit_cowper_symonds(curves())
    base = curve(0.001, lambda r: 1.0, p_max=1.0)            # extrapolated static
    table = rate_table_from_model(base, CowperSymonds(C, P, 0.0, 0.0, 0),
                                  [100.0, 0.001, 1.0], points=30)
    assert table.rates.tolist() == [0.001, 1.0, 100.0]
    assert table.plastic_strain[0] == 0.0 and table.plastic_strain[-1] == 1.0
    assert np.all(np.diff(table.plastic_strain) > 0)
    reference = np.interp(table.plastic_strain, base.plastic_strain, base.stress)
    np.testing.assert_allclose(table.curve(100.0), reference * cs_factor(100.0),
                               rtol=1e-12)
    assert table.check().passed
    # Relative to a reference rate (fitted law): the reference curve is kept.
    rel = rate_table_from_model(base, law, [0.001, 10.0])
    np.testing.assert_allclose(rel.curve(0.001), np.interp(
        rel.plastic_strain, base.plastic_strain, base.stress))

    text = table.keyword(100, unit_system="mm-ms-kg", title="DP600 rates")
    lines = text.splitlines()
    assert lines[:2] == ["*DEFINE_TABLE_TITLE", "DP600 rates"]
    assert lines[3] == f"{100:10d}{1.0:10.1f}{0.0:10.1f}"
    assert float(lines[5]) == pytest.approx(1e-6)            # 0.001 /s in 1/ms
    assert float(lines[7]) == pytest.approx(0.1)             # 100 /s in 1/ms
    assert text.count("*DEFINE_CURVE_TITLE") == 3
    first_curve = lines.index("*DEFINE_CURVE_TITLE")
    assert lines[first_curve + 3].startswith(f"{101:10d}")
    data = lines[first_curve + 5]
    assert len(data) == 40
    assert float(data[20:]) == pytest.approx(static(0.0) * cs_factor(0.001) * 1e-3)
    log = table.keyword(5, log_rates=True, unit_system="mm-ms-kg")
    assert float(log.splitlines()[4]) == pytest.approx(math.log(1e-6))
    with pytest.raises(ValueError, match="unit_system"):
        table.keyword(5, unit_system="inch")


def test_rate_table_from_curves_and_checks():
    table = rate_table_from_curves(curves(), points=20)
    assert table.rates.tolist() == list(RATES)
    assert table.plastic_strain[-1] == pytest.approx(0.15)
    result = table.check()
    assert result.passed
    assert any("100x apart" in w for w in result.warnings)   # 0.001 -> 1 /s
    assert table.check(log_rates=True, unit_system="mm-ms-kg").passed

    crossing = dict(curves())
    weak = crossing[100.0]
    crossing[100.0] = HardeningCurve(weak.plastic_strain, weak.stress * np.where(
        weak.plastic_strain > 0.1, 0.7, 1.0), weak.modulus, weak.necking_strain)
    bad = rate_table_from_curves(crossing)
    check = bad.check()
    assert not check.passed
    assert any("curves cross" in i and "100 /s" in i for i in check.issues)
    assert any("softens" in w for w in check.warnings)
    assert "FAILED" in check.summary()
    with pytest.raises(ValueError, match="errors"):
        bad.keyword(1)

    fast_only = RateTable([1.0, 10.0], [0.0, 0.1], [[300.0, 400.0], [330.0, 440.0]])
    lg = fast_only.check(log_rates=True, unit_system="mm-s-t")
    assert any("not negative" in i for i in lg.issues)
    assert any("no quasi-static" in w for w in fast_only.check().warnings)
    unsorted = RateTable([10.0, 1.0], [0.0, 0.1], [[300.0, 400.0], [330.0, 440.0]])
    assert any("not strictly increasing" in i for i in unsorted.check().issues)
    with pytest.raises(ValueError, match="shape"):
        RateTable([1.0], [0.0, 0.1], [[1.0, 2.0, 3.0]])
    with pytest.raises(ValueError, match="No curve at rate"):
        table.curve(7.0)
    assert set(UNIT_SYSTEMS) == {"mm-ms-kg", "mm-s-t", "mm-s-kg", "m-s-kg"}
