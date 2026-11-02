"""Tests for crashmetrics.materials.keyword, .verify and .library."""

import datetime as dt
import math

import numpy as np
import pytest

from crashmetrics.materials import (
    HardeningCurve,
    Mat024,
    MaterialLibrary,
    RateTable,
    card_summary,
    check_keyword,
    compare_cards,
    compare_tension,
    convert_keyword,
    guess_unit_system,
    read_keyword,
    single_element_deck,
    summary_markdown,
    verify_single_element,
)

P = np.concatenate(([0.0], np.geomspace(1e-3, 1.0, 59)))
CURVE = HardeningCurve(P, 900.0 * (0.005 + P) ** 0.2, 210_000.0, 0.15, "DP")
TABLE = RateTable([0.001, 1.0, 100.0], P,
                  [CURVE.stress, CURVE.stress * 1.2, CURVE.stress * 1.5])
MAT = Mat024(mid=7, density=7850.0, modulus=210_000.0, curve=CURVE, c=40.4, p=5.0,
             fail=0.4, title="DP600")
TMAT = Mat024(mid=8, density=7850.0, modulus=210_000.0, table=TABLE, vp=1,
              title="DP600 rates")

# A hand-written deck: comma format, long-free fixed format, a Fortran
# exponent, SFO scaling and an &parameter.
HAND = """*KEYWORD
$ hand-written
*MAT_PIECEWISE_LINEAR_PLASTICITY
$#     mid        ro         e        pr      sigy      etan      fail      tdel
        11   7.85e-6     210.0      0.30     0.350       0.0       0.0       0.0
       0.0       0.0        21         0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
       0.0       0.0       0.0       0.0       0.0       0.0       0.0       0.0
*DEFINE_CURVE
21,0,1.0,0.001
0.0,350.0
0.1,450.0
0.4,600.0
*MAT_024_TITLE
mild
12,7.85e-9,210000.0,0.3,&sy,0.0
0.0,0.0,0,0,0.0
*MAT_PIECEWISE_LINEAR_PLASTICITY
        13   7.85e-9  210000.0       0.3     300.0    1000.0
       0.0       0.0         0
*MAT_PIECEWISE_LINEAR_PLASTICITY
        14   7.85e-6  210000.0       0.3     300.0    1000.0
       0.0       0.0         0
*INCLUDE
other.k
"""


def test_read_round_trip_curve_and_table():
    text = MAT.keyword("mm-ms-kg", points=None) + TMAT.keyword("mm-s-t")
    deck = read_keyword(text)
    assert sorted(deck.materials) == [7, 8]
    m7 = deck.materials[7]
    assert (m7.mid, m7.lcss, m7.title) == (7, 1007, "DP600")
    assert m7.ro == pytest.approx(7.85e-6) and m7.e == pytest.approx(210.0)
    assert m7.c == pytest.approx(0.0404)
    back = deck.material(7)
    assert back.provenance["unit_system"] == "mm-ms-kg"
    assert back.density == pytest.approx(7850.0) and back.modulus == pytest.approx(
        210_000.0)
    assert back.c == pytest.approx(40.4) and back.p == 5.0 and back.fail == 0.4
    np.testing.assert_allclose(back.curve.stress, CURVE.stress, rtol=1e-7)
    tb = deck.tables[1008]
    assert tb.log_rates and tb.curve_ids == (1009, 1010, 1011)
    tback = deck.material(8)
    np.testing.assert_allclose(tback.table.rates, TABLE.rates, rtol=1e-7)
    np.testing.assert_allclose(tback.table.stress, TABLE.stress, rtol=1e-7)
    assert tback.vp == 1
    assert all(c.passed for c in check_keyword(deck))


def test_read_hand_written_formats():
    deck = read_keyword(HAND)
    assert sorted(deck.materials) == [11, 12, 13, 14]
    assert deck.curves[21].y.tolist() == pytest.approx([0.35, 0.45, 0.6])  # SFO
    m12 = deck.materials[12]
    assert m12.title == "mild" and m12.parameters == ("sigy=&sy",)
    assert any("INCLUDE" in n for n in deck.notes)
    bilinear = deck.material(13, "mm-s-t")
    assert bilinear.curve.stress.tolist() == [300.0, 1300.0]
    long_text = MAT.keyword("mm-s-t").replace("*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE",
                                              "*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE")
    assert read_keyword(long_text).materials[7].sigy == pytest.approx(
        CURVE.stress[0], rel=1e-6)
    with pytest.raises(ValueError, match="No \\*MAT_024"):
        deck.material(99)


def test_guess_unit_system():
    assert guess_unit_system(7.85e-6, 210.0) == "mm-ms-kg"
    assert guess_unit_system(7.85e-9, 210_000.0) == "mm-s-t"
    assert guess_unit_system(7.85e-6, 2.1e8) == "mm-s-kg"
    assert guess_unit_system(7850.0, 2.1e11) == "m-s-kg"
    assert guess_unit_system(7.85e-9, 210.0) is None          # mixed up
    assert guess_unit_system(2.7e-6, 70.0) == "mm-ms-kg"      # aluminium


def test_check_finds_errors():
    deck = read_keyword(HAND)
    results = {c.mid: c for c in check_keyword(deck)}
    c11 = results[11]
    assert c11.passed and c11.unit_system == "mm-ms-kg"
    assert any("ends at plastic strain 0.4" in w for w in c11.warnings)
    assert any("parameters" in w for w in results[12].warnings)
    assert results[13].passed and results[13].unit_system == "mm-s-t"
    c14 = results[14]                                           # RO kg/mm³, E MPa
    assert not c14.passed and "do not belong to one unit system" in c14.issues[0]
    with pytest.raises(ValueError, match="do not match one unit system"):
        deck.material(14)
    wrong = check_keyword(deck, unit_system="mm-s-t", mids=[11])[0]
    assert "look like mm-ms-kg, not mm-s-t" in wrong.issues[0]

    bad = """*MAT_PIECEWISE_LINEAR_PLASTICITY
         1   7.85e-6     210.0       0.3      0.35
       0.0       0.0       100         0
*DEFINE_CURVE
       100
 0.01, 0.30
 0.02, 0.29
 0.0201, 2.5
*MAT_PIECEWISE_LINEAR_PLASTICITY
         2   7.85e-6     210.0       0.6       0.3
       0.0       0.0       200
*DEFINE_TABLE
       200
 -13.8
 -9.0
 -2.3
*DEFINE_CURVE
       201
 0.0, 0.40
 1.0, 0.90
*DEFINE_CURVE
       202
 0.0, 0.45
 1.0, 0.80
*DEFINE_CURVE
       203
 0.0, 0.50
 1.0, 1.10
"""
    r = {c.mid: c for c in check_keyword(read_keyword(bad))}
    text1 = r[1].summary()
    assert "not 0" in text1 and "above E" in text1 and "softening" in text1
    assert "SIGY" in text1
    text2 = r[2].summary()
    assert "PR 0.6" in text2 and "curve 202 below curve 201" in text2
    assert "FAILED" in text2


def test_rediscretisation_warning():
    # Curve to 1.0 with the yield bend inside the first 1 %.
    x = np.concatenate(([0.0], np.geomspace(1e-5, 1.0, 40)))
    y = 300.0 + 400.0 * (1 - np.exp(-300.0 * x)) + 50.0 * x
    m = Mat024(mid=3, density=7850.0, modulus=210_000.0,
               curve=HardeningCurve(x, y, 210_000.0, 0.1))
    check = check_keyword(read_keyword(m.keyword("mm-s-t", points=None)))[0]
    assert any("LCINT" in w for w in check.warnings)
    assert not any("LCINT" in w for w in check_keyword(
        read_keyword(m.keyword("mm-s-t", points=None)), lcint=100_000)[0].warnings)


def test_convert_keyword():
    source = MAT.keyword("mm-ms-kg", points=None) + TMAT.keyword("mm-ms-kg")
    converted = convert_keyword(source, "mm-s-t")
    deck = read_keyword(converted)
    assert deck.materials[7].ro == pytest.approx(7.85e-9)
    assert deck.materials[7].e == pytest.approx(210_000.0)
    assert deck.materials[7].c == pytest.approx(40.4)
    assert len(deck.curves[1007].x) == len(P)                 # points kept
    np.testing.assert_allclose(deck.curves[1007].y, CURVE.stress, rtol=1e-7)
    assert deck.tables[1008].values[0] == pytest.approx(math.log(0.001))
    assert all(c.passed for c in check_keyword(deck, unit_system="mm-s-t"))


def test_compare_cards_and_stress():
    other = Mat024(mid=9, density=7800.0, modulus=205_000.0,
                   curve=HardeningCurve(P, CURVE.stress * 1.05, 205_000.0, 0.15),
                   title="supplier")
    comp = compare_cards(MAT, other, strains=(0.0, 0.5), rates=(None,))
    rows = {label: (a, b) for label, a, b in comp.rows}
    assert rows["E MPa"] == (210_000.0, 205_000.0)
    assert rows["stress static @ 0.5 MPa"][1] == pytest.approx(
        rows["stress static @ 0.5 MPa"][0] * 1.05)
    text = comp.summary()
    assert "DP600" in text and "supplier" in text and "5.00" in text
    # Stress lookup: Cowper-Symonds, extrapolation, table interpolation.
    assert MAT.stress([0.5], 100.0)[0] == pytest.approx(
        MAT.stress([0.5])[0] * (1 + (100 / 40.4) ** 0.2))
    slope = (CURVE.stress[-1] - CURVE.stress[-2]) / (P[-1] - P[-2])
    assert MAT.stress([1.5])[0] == pytest.approx(CURVE.stress[-1] + 0.5 * slope)
    w = math.log(10.0 / 1.0) / math.log(100.0 / 1.0)
    assert TMAT.stress([0.0], 10.0)[0] == pytest.approx(
        CURVE.stress[0] * (1.2 + w * 0.3))
    assert TMAT.stress([0.0], 1e4)[0] == pytest.approx(CURVE.stress[0] * 1.5)


def test_single_element_deck():
    text = single_element_deck(MAT, "mm-ms-kg", size=2.0, strain=0.4, rate=1.0)
    deck = read_keyword(text)
    assert list(deck.materials) == [7]
    assert deck.materials[7].c == 0.0                          # rate effect off
    lines = text.splitlines()
    i = lines.index("*CONTROL_TERMINATION")
    assert float(lines[i + 2]) == pytest.approx(0.4 / 1.0 * 1000.0)   # ms
    j = lines.index("*NODE")
    nodes = [ln for ln in lines[j + 1: j + 9]]
    assert float(nodes[6][8:24]) == pytest.approx(2.0)
    assert lines[lines.index("*ELEMENT_SOLID") + 1] == "".join(
        f"{v:8d}" for v in (1, 1, 1, 2, 3, 4, 5, 6, 7, 8))
    assert text.count("*BOUNDARY_SPC_NODE") == 1 and "*DATABASE_SPCFORC" in text
    vel = lines[lines.index("pull velocity") + 3]
    assert float(vel[20:]) == pytest.approx(0.4 * 2.0 / 400.0)  # mm/ms
    assert text.rstrip().endswith("*END")
    with_rate = single_element_deck(MAT, "mm-s-t", rate_effect=True)
    assert read_keyword(with_rate).materials[7].c == pytest.approx(40.4)
    with pytest.raises(ValueError, match="positive"):
        single_element_deck(MAT, strain=0.0)


def test_compare_tension_from_exact_response():
    size = 1.0
    ep = np.linspace(0.0, 0.6, 200)
    sig = MAT.stress(ep)
    eps = ep + sig / MAT.modulus
    u = np.expm1(eps) * size
    force = sig * size ** 3 / (size + u)
    good = compare_tension(u, force, MAT, size=size)
    assert good.max_error < 1e-9 and good.passed
    assert "passed" in good.summary()
    off = compare_tension(u, force * 1.05, MAT, size=size)
    assert off.max_error == pytest.approx(0.05, rel=0.05) and not off.passed


def test_verify_single_element_from_outputs():
    class Out:                                      # stand-in for AsciiOutput
        def __init__(self, time, totals=None, disp=None):
            self.time, self.totals, self._disp = time, totals or {}, disp

        def channel(self, name, node):
            assert (name, node) == ("z_displacement", 5)
            return self._disp

    ep = np.linspace(0.0, 0.5, 100)
    sig = MAT.stress(ep)
    u = np.expm1(ep + sig / MAT.modulus)
    t = np.linspace(0.0, 1.0, 100)
    force_kn = -sig / (1.0 + u) / 1000.0            # reaction, kN (mm-ms-kg)
    check = verify_single_element(".", MAT, "mm-ms-kg",
                                  spcforc=Out(t, {"z_force": force_kn}),
                                  nodout=Out(t, disp=u))
    assert check.passed and check.max_error < 1e-9


def test_summary_and_library(tmp_path):
    rows = card_summary([MAT, TMAT])
    assert rows[0]["mid"] == 7 and rows[0]["E_GPa"] == 210.0
    assert rows[0]["rate"].startswith("Cowper-Symonds")
    assert rows[1]["rate"].startswith("table, 3 rates")
    md = summary_markdown(rows)
    assert md.splitlines()[0].startswith("| mid | title |")
    assert summary_markdown([]) == ""

    lib = MaterialLibrary(tmp_path / "lib")
    mat = Mat024(mid=7, density=7850.0, modulus=210_000.0, curve=CURVE, c=40.4,
                 p=5.0, title="DP600 1.2 mm", provenance={"tests": "L1-L3"})
    path = lib.save(mat, date=dt.date(2026, 11, 2), note="rolling direction")
    assert path.name == "DP600_1.2_mm.json"
    lib.save(TMAT, "dp600_rates")
    assert lib.names() == ["DP600_1.2_mm", "dp600_rates"]
    back = lib.load("DP600_1.2_mm")
    assert back.c == 40.4 and back.provenance == {"tests": "L1-L3"}
    np.testing.assert_allclose(back.curve.stress, CURVE.stress)
    np.testing.assert_allclose(lib.load("dp600_rates").table.stress, TABLE.stress)
    info = lib.info("DP600_1.2_mm")
    assert info["saved"] == "2026-11-02" and info["note"] == "rolling direction"
    assert [r["name"] for r in lib.summary()] == lib.names()
    out = lib.export("DP600_1.2_mm", tmp_path / "dp.k", "mm-s-t")
    assert read_keyword(out).materials[7].e == pytest.approx(210_000.0)
    with pytest.raises(FileExistsError):
        lib.save(mat)
    lib.save(mat, overwrite=True)
    with pytest.raises(KeyError):
        lib.load("missing")
    with pytest.raises(ValueError, match="Library names"):
        lib.save(mat, "a/b")
