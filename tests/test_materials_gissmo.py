"""Tests for crashmetrics.materials.gissmo (and GISSMO reading/checking)."""

import math

import numpy as np
import pytest

from crashmetrics.materials import (
    TRIAXIALITY,
    FractureTest,
    GissmoCard,
    HardeningCurve,
    Mat024,
    RegularizationCurve,
    average_triaxiality,
    check_gissmo,
    fit_failure_curve,
    instability_from_flc,
    integrate_damage,
    lode_parameter,
    plane_stress_strains,
    read_keyword,
    regularization_estimate,
    triaxiality_from_strain_ratio,
)
from crashmetrics.materials.gissmo import _hosford_coulomb

TRUTH = {"a": 1.4, "b": 0.55, "c": 0.06, "n": 0.1}


def hc(eta):
    return _hosford_coulomb(np.asarray(eta, dtype=float), TRUTH["a"], TRUTH["b"],
                            TRUTH["c"], TRUTH["n"])


def proportional_tests(curve=hc):
    states = {"shear": 0.0, "uniaxial": 1 / 3, "notch R10": 0.45,
              "plane strain": 1 / math.sqrt(3), "biaxial": 2 / 3}
    return [FractureTest(name, float(curve(eta)), eta) for name, eta in states.items()]


def path_test(name, eta_path, curve=hc):
    """A test whose path is eta(eps); its fracture strain is where the
    exact damage integral of the true curve reaches 1."""
    e = np.linspace(0.0, 3.0, 30001)
    eta = eta_path(e)
    inv = 1.0 / curve(eta)
    integral = np.concatenate(([0.0], np.cumsum(0.5 * (inv[1:] + inv[:-1]) *
                                                np.diff(e))))
    k = int(np.searchsorted(integral, 1.0))
    ef = e[k - 1] + (1 - integral[k - 1]) / (integral[k] - integral[k - 1]) * (
        e[k] - e[k - 1])
    pe = np.append(e[e < ef], ef)
    return FractureTest(name, float(ef), path_strain=pe,
                        path_triaxiality=eta_path(pe))


def test_stress_states():
    assert TRIAXIALITY["uniaxial"] == pytest.approx(1 / 3)
    np.testing.assert_allclose(triaxiality_from_strain_ratio([-1, -0.5, 0, 1]),
                               [0.0, 1 / 3, 1 / math.sqrt(3), 2 / 3], atol=1e-12)
    np.testing.assert_allclose(lode_parameter([1 / 3, 0.0, 1 / math.sqrt(3), 2 / 3]),
                               [1.0, 0.0, 0.0, -1.0], atol=1e-12)
    eta, eq = plane_stress_strains([0.3, 0.2, 0.25], [-0.15, 0.0, 0.25])
    np.testing.assert_allclose(eta, [1 / 3, 1 / math.sqrt(3), 2 / 3])
    np.testing.assert_allclose(eq, [0.3, 2 / math.sqrt(3) * 0.2, 0.5])  # eq = e1 in UT
    with pytest.raises(ValueError, match="major"):
        plane_stress_strains([0.1], [0.2])
    assert average_triaxiality([0, 0.1, 0.3], [0.2, 0.4, 0.4]) == pytest.approx(
        (0.03 + 0.08) / 0.3)


def test_hosford_coulomb_shape():
    # b in uniaxial and equibiaxial tension; lowest near plane strain.
    np.testing.assert_allclose(hc([1 / 3, 2 / 3]), [0.55, 0.55], rtol=1e-12)
    grid = np.linspace(0.0, 2 / 3, 201)
    assert grid[int(np.argmin(hc(grid)))] == pytest.approx(1 / math.sqrt(3), abs=0.01)


def test_fit_hosford_coulomb_proportional():
    fit = fit_failure_curve(proportional_tests())
    for k in ("a", "b", "c"):
        assert fit.params[k] == pytest.approx(TRUTH[k], rel=2e-3), k
    assert np.max(np.abs(fit.errors)) < 1e-6
    assert "plane strain" in fit.summary()


def test_fit_with_non_proportional_paths():
    tests = proportional_tests()[:3] + [
        path_test("notch, rising", lambda e: 0.40 + 0.25 * np.minimum(e / 0.3, 1.0)),
        path_test("shear to tension", lambda e: 0.05 + 0.3 * np.minimum(e, 1.0))]
    fit = fit_failure_curve(tests)
    assert np.max(np.abs(fit.errors)) < 1e-4
    assert fit.params["b"] == pytest.approx(0.55, rel=1e-3)
    # Treating the path tests as proportional at their average misses.
    flat = [FractureTest(t.name, t.fracture_strain, t.eta) for t in tests]
    assert np.max(np.abs(fit_failure_curve(flat).errors)) > 0.01


def test_fit_johnson_cook_and_tabulated():
    jc = lambda eta: 0.1 + 0.6 * np.exp(-1.5 * np.asarray(eta))   # noqa: E731
    fit = fit_failure_curve(proportional_tests(jc), "johnson_cook")
    assert fit.params == pytest.approx({"d1": 0.1, "d2": 0.6, "d3": -1.5}, rel=1e-4)
    tests = proportional_tests()
    tab = fit_failure_curve(tests, "tabulated")
    np.testing.assert_allclose(tab([t.eta for t in tests]),
                               [t.fracture_strain for t in tests], rtol=1e-12)
    path = path_test("rising", lambda e: 0.3 + 0.2 * np.minimum(e / 0.5, 1.0))
    tab2 = fit_failure_curve(tests[:2] + [path], "tabulated")
    assert abs(tab2.errors[-1]) < 1e-6
    with pytest.raises(ValueError, match="3 or more"):
        fit_failure_curve(tests[:2])
    with pytest.raises(ValueError, match="Unknown model"):
        fit_failure_curve(tests, "wilkins")
    with pytest.raises(ValueError, match="triaxiality or a path"):
        FractureTest("x", 0.3)
    with pytest.raises(ValueError, match="end at the fracture"):
        FractureTest("x", 0.3, path_strain=[0.0, 0.2], path_triaxiality=[0.3, 0.3])


def test_integrate_damage_constant_state():
    e = np.linspace(0.0, 0.6, 601)
    eta = np.full_like(e, 1 / 3)
    h = integrate_damage(e, eta, 0.5, dmgexp=2.0, instability=0.2, fadexp=2.0)
    np.testing.assert_allclose(h.damage[:501], (e[:501] / 0.5) ** 2, atol=1e-12)
    assert h.coupling_strain == pytest.approx(0.2)
    assert h.critical_damage == pytest.approx((0.2 / 0.5) ** 2)
    assert h.fracture_strain == pytest.approx(0.5)
    i = 400                                                  # eps 0.4
    dc = h.critical_damage
    assert h.fading[i] == pytest.approx(1 - ((0.64 - dc) / (1 - dc)) ** 2)
    assert h.fading[100] == 1.0 and h.fading[-1] == 0.0
    np.testing.assert_allclose(h.instability[:201], (e[:201] / 0.2) ** 2, atol=1e-12)
    brittle = integrate_damage(e, eta, 0.5)
    assert math.isnan(brittle.critical_damage) and brittle.fading[499] == 1.0
    with_dcrit = integrate_damage(e, eta, 0.5, dcrit=0.5)
    assert with_dcrit.coupling_strain == pytest.approx(0.25, rel=1e-9)


def test_instability_and_regularization():
    x, y = instability_from_flc([0.30, 0.20, 0.25], [-0.15, 0.0, 0.25])
    np.testing.assert_allclose(x, [-1 / 3, 1 / 3, 1 / math.sqrt(3), 2 / 3])
    np.testing.assert_allclose(y, [0.3, 0.3, 2 / math.sqrt(3) * 0.2, 0.5])
    reg = regularization_estimate([1.0, 2.5, 5.0], reference_size=0.5,
                                  necking_strain=0.15, fracture_strain=0.75,
                                  neck_length=1.2)
    assert reg(0.5) == 1.0
    assert reg(2.5) == pytest.approx((0.15 + 0.6 * 1.2 / 2.5) / 0.75)
    assert reg(10.0) == reg(5.0)
    assert np.all(np.diff(reg.factor) <= 0)
    with pytest.raises(ValueError, match="increasing"):
        RegularizationCurve([2.0, 1.0], [1.0, 0.9])


def card(**kw):
    fit = fit_failure_curve(proportional_tests())
    base = dict(mid=600, failure=fit, instability=instability_from_flc(
        [0.30, 0.20, 0.18], [-0.15, 0.0, 0.18]), dmgexp=2.0, fadexp=2.0,
        regularization=regularization_estimate([1.0, 2.5, 5.0], reference_size=0.5,
                                               necking_strain=0.15,
                                               fracture_strain=0.75, neck_length=1.2),
        rate_scaling=([0.001, 1.0, 100.0], [1.0, 1.05, 1.1]), numfip=3.0)
    base.update(kw)
    return GissmoCard(**base)


def fields(line, width=10):
    return [line[i:i + width] for i in range(0, len(line), width)]


def test_card_keyword_and_units():
    c = card()
    text = c.keyword("mm-ms-kg")
    lines = [ln for ln in text.splitlines() if not ln.startswith("$")]
    assert lines[0] == "*MAT_ADD_DAMAGE_GISSMO"
    mid, dtyp, refsz, numfip = fields(lines[1])
    assert (int(mid), float(dtyp), float(refsz), float(numfip)) == (600, 1, 0, 3)
    lcsdg, ecrit, dmgexp, dcrit, fadexp, lcregd = fields(lines[2])
    ids = c.curve_ids()
    assert int(lcsdg) == ids["failure"] == 2600
    assert float(ecrit) == -ids["instability"]
    assert (float(dmgexp), float(dcrit), float(fadexp)) == (2.0, 0.0, 2.0)
    assert int(lcregd) == ids["regularization"]
    assert int(fields(lines[3])[0]) == ids["rate"]
    assert text.count("*DEFINE_CURVE_TITLE") == 4
    deck = read_keyword(text)
    g = deck.gissmo[600]
    assert g.lcsdg == 2600 and g.ecrit == -ids["instability"] and g.numfip == 3.0
    np.testing.assert_allclose(deck.curves[ids["rate"]].x[0], math.log(1e-6))
    # m-s-kg: element sizes in m.
    msk = read_keyword(c.keyword("m-s-kg"))
    np.testing.assert_allclose(msk.curves[ids["regularization"]].x,
                               c.regularization.element_size / 1000.0)
    back = deck.damage(600, "mm-ms-kg")
    np.testing.assert_allclose(back.regularization.element_size,
                               c.regularization.element_size)
    np.testing.assert_allclose(back.rate_scaling[0], [0.001, 1.0, 100.0], rtol=1e-6)
    np.testing.assert_allclose(back.failure_curve()[1], c.failure_curve()[1],
                               rtol=1e-7)


def test_card_checks_and_damage():
    errors, warnings = card(regularization=None).check()
    assert errors == () and warnings == ()
    # Large elements: the regularised failure strain drops below ECRIT.
    _, w = card().check()
    assert w == ("from element size 2.5 mm the regularised failure strain is at or "
                 "below the critical strain (triaxiality 0.16 to 0.173, 0.38 to "
                 "0.667): no fading there",)
    low = card(failure=(np.array([0.0, 1 / 3, 2 / 3]), np.array([0.2, 0.25, 0.3])))
    _, w = low.check()
    assert any("no fading there" in x for x in w)
    _, w = card(failure=(np.array([0.1, 0.5]), np.array([0.5, 0.4])),
                instability=None).check()
    assert any("covers triaxiality" in x for x in w)
    assert any("no stress fading" in x for x in w)
    bad = card(failure=(np.array([0.0, 0.3, 0.6]), np.array([0.4, -0.1, 0.3])))
    with pytest.raises(ValueError, match="negative"):
        bad.keyword()
    _, w = card(shrf=1.0).check()
    assert w[0].endswith("SHRF / BIAXF not taken into account")
    with pytest.raises(ValueError, match="fadexp"):
        card(fadexp=0.0)
    h = card().damage(np.linspace(0, 1.0, 1001), np.full(1001, 1 / 3),
                      element_size=2.5)
    expected = 0.55 * card().regularization(2.5)
    assert h.fracture_strain == pytest.approx(expected, rel=1e-3)
    assert h.coupling_strain == pytest.approx(0.3, rel=1e-3)   # FLC uniaxial point


def test_mat024_with_gissmo_and_check_deck(tmp_path):
    p = np.concatenate(([0.0], np.geomspace(1e-3, 1.0, 40)))
    mat = Mat024(mid=600, density=7850.0, modulus=210_000.0,
                 curve=HardeningCurve(p, 900 * (0.005 + p) ** 0.2, 210_000.0, 0.15))
    path = mat.write(tmp_path / "dp.k", "mm-ms-kg", damage=card())
    text = path.read_text()
    assert "*MAT_ADD_DAMAGE_GISSMO" in text and "$ Failure: *MAT_ADD_DAMAGE_GISSMO" \
        in text
    results = check_gissmo(read_keyword(path))
    assert results[0].passed and results[0].unit_system == "mm-ms-kg"
    with pytest.raises(ValueError, match="MID 600"):
        Mat024(mid=601, density=7850.0, modulus=210_000.0, curve=mat.curve).write(
            tmp_path / "x.k", damage=card())

    broken = """*MAT_ADD_DAMAGE_GISSMO
       700       1.0       0.0       1.0
      9999     -8888       0.0       0.0       0.0
"""
    r = check_gissmo(read_keyword(broken))[0]
    assert not r.passed and "9999" in r.issues[0]
    assert any("no *MAT_024" in w for w in r.warnings)
    assert any("DMGEXP blank" in w for w in r.warnings)
    assert any("unit system unknown" in w for w in r.warnings)
    assert any("not read" in n for n in read_keyword(
        "*MAT_ADD_EROSION\n 1, 0\n").notes)


def test_card_variants_round_trip():
    # Constant ECRIT, a fading-exponent curve, rates written as rates
    # (not ln), rate not scaling ECRIT, m-s-kg sizes.
    c = card(instability=0.25, fadexp=([0.5, 2.0, 5.0], [2.0, 4.0, 8.0]),
             scale_instability_with_rate=False, refsz=1.5, shrf=0.6, biaxf=0.4,
             first_curve_id=9000)
    ids = c.curve_ids()
    assert list(ids) == ["failure", "regularization", "fading", "rate"]
    assert ids["fading"] == 9200
    text = c.keyword("m-s-kg", log_rates=False)
    deck = read_keyword(text)
    g = deck.gissmo[600]
    assert g.ecrit == 0.25 and g.fadexp == -9200 and g.lcsrs == -9300
    assert g.refsz == pytest.approx(0.0015) and (g.shrf, g.biaxf) == (0.6, 0.4)
    np.testing.assert_allclose(deck.curves[9300].x, [0.001, 1.0, 100.0])
    back = deck.damage(600, "m-s-kg")
    assert back.instability == 0.25 and not back.scale_instability_with_rate
    np.testing.assert_allclose(back.fadexp[0], [0.5, 2.0, 5.0])
    assert back.refsz == pytest.approx(1.5)
    np.testing.assert_allclose(c.critical_strain([0.0, 0.5]), [0.25, 0.25])
    assert c.failure_strain(1 / 3, rate=1.0) == pytest.approx(0.55 * 1.05, rel=1e-3)
    e = np.linspace(0.0, 0.6, 601)
    plain = card(instability=0.25, fadexp=([0.5, 2.0, 5.0], [2.0, 4.0, 8.0]),
                 regularization=None)
    i = int(np.searchsorted(e, 0.45))
    fading = [plain.damage(e, np.full_like(e, 1 / 3), element_size=s).fading[i]
              for s in (0.5, 5.0)]
    dc = (0.25 / 0.55) ** 2
    r = ((0.45 / 0.55) ** 2 - dc) / (1 - dc)
    np.testing.assert_allclose(fading, [1 - r ** 2, 1 - r ** 8], rtol=2e-3)
    assert card(instability=None, dcrit=0.3).curve_ids() == {
        "failure": 2600, "regularization": 2700, "rate": 2800}
    with pytest.raises(ValueError, match="log_rates=False"):
        card(rate_scaling=([1.0, 10.0], [1.0, 1.1])).keyword("mm-s-t")
    with pytest.raises(ValueError, match="unit_system"):
        c.keyword("inch")


def test_card_validation_and_warnings():
    for kw, msg in [({"dtyp": 2}, "dtyp"), ({"dmgexp": 0.0}, "dmgexp"),
                    ({"dcrit": 1.0}, "dcrit"), ({"points": 2}, "points")]:
        with pytest.raises(ValueError, match=msg):
            card(**kw)
    _, w = card(dmgexp=0.8).check()
    assert any("below 1" in x for x in w)
    rising = RegularizationCurve([1.0, 5.0], [1.0, 1.2])
    _, w = card(regularization=rising).check()
    assert any("rise with element size" in x for x in w)
    errors, _ = card(instability=(np.array([0.0, 0.6]), np.array([0.2, -0.1])),
                     fadexp=([2.0, 1.0], [2.0, 2.0]),
                     rate_scaling=([1.0, 0.1], [1.0, 1.1]),
                     failure=(np.array([0.0, 0.0, 0.6]),
                              np.array([0.4, 0.3, 0.3]))).check()
    assert len(errors) == 4
    clash = card(first_curve_id=None, mid=600)
    assert len(set(clash.curve_ids().values())) == len(clash.curve_ids())


def test_input_validation():
    with pytest.raises(ValueError, match="positive"):
        FractureTest("x", 0.0, 0.3)
    with pytest.raises(ValueError, match="both path arrays"):
        FractureTest("x", 0.3, path_strain=[0.0, 0.3])
    with pytest.raises(ValueError, match="equal length"):
        FractureTest("x", 0.3, path_strain=[0.0, 0.3], path_triaxiality=[0.3])
    with pytest.raises(ValueError, match="weight"):
        FractureTest("x", 0.3, 0.3, weight=0.0)
    with pytest.raises(ValueError, match="at least one"):
        fit_failure_curve([], "tabulated")
    same = [FractureTest("a", 0.3, 0.3), FractureTest("b", 0.4, 0.3)]
    with pytest.raises(ValueError, match="different triaxialities"):
        fit_failure_curve(same, "tabulated")
    with pytest.raises(ValueError, match="different strain ratios"):
        instability_from_flc([0.3, 0.3], [0.1, 0.1])
    x, y = instability_from_flc([0.3, 0.2], [-0.15, 0.0], extend_to=(-1 / 3, 0.7))
    assert x[-1] == 0.7 and y[-1] == y[-2]
    with pytest.raises(ValueError, match="equal length"):
        RegularizationCurve([1.0], [1.0])
    with pytest.raises(ValueError, match="positive"):
        RegularizationCurve([1.0, 2.0], [1.0, 0.0])
    with pytest.raises(ValueError, match="necking_strain"):
        regularization_estimate([1.0], reference_size=0.5, necking_strain=0.5,
                                fracture_strain=0.4, neck_length=1.0)
    with pytest.raises(ValueError, match="positive"):
        regularization_estimate([1.0], reference_size=0.0, necking_strain=0.1,
                                fracture_strain=0.4, neck_length=1.0)
    with pytest.raises(ValueError, match="non-decreasing"):
        integrate_damage([0.0, 0.2, 0.1], [0.3, 0.3, 0.3], 0.5)
    with pytest.raises(ValueError, match="positive"):
        integrate_damage([0.0, 0.1], [0.3, 0.3], 0.5, dmgexp=0.0)
    with pytest.raises(ValueError, match="non-decreasing"):
        average_triaxiality([0.1, 0.0], [0.3, 0.3])
    h = integrate_damage([0.0, 0.1, 0.2], [0.3, 0.3, 0.3], 0.5, instability=1.0)
    assert math.isnan(h.fracture_strain) and math.isnan(h.critical_damage)


def test_reading_titled_and_parameter_cards():
    deck = read_keyword("""*KEYWORD
*MAT_ADD_DAMAGE_GISSMO_TITLE
DP800 damage
       800         1       0.0         1
       801      &ecr         2         0         2
*DEFINE_TABLE
       801
                 0.0
*DEFINE_CURVE
       802
                 0.0                 0.4
                 1.0                 0.4
*MAT_ADD_DAMAGE_GISSMO
       810         1
*END
""")
    assert set(deck.gissmo) == {800}
    assert any("incomplete *MAT_ADD_DAMAGE_GISSMO" in n for n in deck.notes)
    r = check_gissmo(deck)[0]
    assert any("parameters" in w for w in r.warnings)
    assert not r.passed and "table" in r.issues[0]
    with pytest.raises(ValueError, match="MIDs"):
        deck.damage(1)
