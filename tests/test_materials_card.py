"""Tests for crashmetrics.materials.card (*MAT_024 writing)."""

import datetime as dt
import math

import numpy as np
import pytest

from crashmetrics.materials import (
    DENSITY_SCALE,
    HardeningCurve,
    Mat024,
    RateTable,
    failure_strain,
    fracture_strain,
    keyword_number,
)

P = np.linspace(0.0, 1.0, 400)
CURVE = HardeningCurve(P, 900.0 * (0.005 + P) ** 0.2, 210_000.0, 0.15, "DP")
TABLE = RateTable([0.001, 100.0], [0.0, 0.1, 1.0],
                  [[400.0, 600.0, 900.0], [500.0, 700.0, 1000.0]])


def fields(line, width=10):
    return [line[i:i + width] for i in range(0, len(line), width)]


def card_lines(text):
    """Data lines (no comments) of the text."""
    return [ln for ln in text.splitlines() if not ln.startswith("$")]


def test_keyword_number():
    assert keyword_number(7.85e-6) == "   7.85e-6"
    assert keyword_number(210.0) == "     210.0"
    assert keyword_number(0.0) == "       0.0"
    assert keyword_number(0.4097123456) == " 0.4097123"
    assert keyword_number(-13.815510558) == " -13.81551"
    assert all(len(keyword_number(v)) == 10 for v in (1e-12, 123456.789, -1e9))
    with pytest.raises(ValueError, match="Cannot write"):
        keyword_number(math.nan)


def test_mat024_with_curve_in_mm_ms_kg():
    mat = Mat024(mid=7, density=7850.0, modulus=210_000.0, curve=CURVE, c=40.4,
                 p=5.0, title="DP600 1.2 mm")
    text = mat.keyword("mm-ms-kg", points=30)
    lines = card_lines(text)
    assert lines[0] == "*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE"
    assert lines[1] == "DP600 1.2 mm"
    mid, ro, e, pr, sigy, etan, fail, tdel = fields(lines[2])
    assert int(mid) == 7
    assert float(ro) == pytest.approx(7.85e-6)
    assert float(e) == pytest.approx(210.0)
    assert float(pr) == 0.3
    assert float(sigy) == pytest.approx(CURVE.stress[0] * 1e-3, rel=1e-6)
    assert float(etan) == float(fail) == float(tdel) == 0.0
    c, p, lcss, lcsr, vp = fields(lines[3])
    assert float(c) == pytest.approx(0.0404)                # 1/ms
    assert float(p) == 5.0 and int(lcss) == 1007 and int(lcsr) == 0
    assert float(vp) == 0.0
    assert lines[4] == lines[5] == "       0.0" * 8
    i = lines.index("*DEFINE_CURVE_TITLE")
    assert lines[i + 1] == "DP600 1.2 mm hardening"
    assert int(lines[i + 2][:10]) == 1007
    data = [(float(ln[:20]), float(ln[20:])) for ln in lines[i + 3:]]
    assert len(data) == 31                                  # 30 + the necking point
    assert data[0] == (0.0, pytest.approx(CURVE.stress[0] * 1e-3))
    assert data[-1][0] == pytest.approx(1.0)
    assert any(abs(x - 0.15) < 1e-9 for x, _ in data)       # necking kept
    assert all(b[0] > a[0] for a, b in zip(data, data[1:]))


def test_unit_systems():
    mat = Mat024(mid=1, density=7850.0, modulus=210_000.0, curve=CURVE, c=40.4,
                 p=5.0)
    expected = {"mm-ms-kg": (7.85e-6, 210.0, 0.0404), "mm-s-t": (7.85e-9, 210_000.0,
                                                                40.4),
                "mm-s-kg": (7.85e-6, 210_000_000.0, 40.4),
                "m-s-kg": (7850.0, 2.1e11, 40.4)}
    for system, (ro, e, c) in expected.items():
        lines = card_lines(mat.keyword(system))
        f1, f2 = fields(lines[1]), fields(lines[2])
        assert float(f1[1]) == pytest.approx(ro, rel=1e-6), system
        assert float(f1[2]) == pytest.approx(e, rel=1e-6), system
        assert float(f2[0]) == pytest.approx(c, rel=1e-6), system
    assert DENSITY_SCALE["mm-s-t"] == 1e-12
    with pytest.raises(ValueError, match="unit_system"):
        mat.keyword("inch-s-lbf")


def test_mat024_with_rate_table():
    mat = Mat024(mid=3, density=7850.0, modulus=210_000.0, table=TABLE, vp=1,
                 curve_id=500)
    text = mat.keyword("mm-s-t")
    lines = card_lines(text)
    assert lines[0] == "*MAT_PIECEWISE_LINEAR_PLASTICITY"
    assert float(fields(lines[1])[4]) == 400.0              # SIGY, lowest rate
    c, p, lcss, _, vp = fields(lines[2])
    assert float(c) == float(p) == 0.0 and int(lcss) == 500 and float(vp) == 1.0
    assert "*DEFINE_TABLE_TITLE" in text and text.count("*DEFINE_CURVE_TITLE") == 2
    j = lines.index("*DEFINE_TABLE_TITLE")
    assert int(lines[j + 2][:10]) == 500
    assert float(lines[j + 3]) == pytest.approx(math.log(0.001))   # ln rates
    linear = card_lines(mat.keyword("mm-s-t", log_rates=False))
    assert float(linear[linear.index("*DEFINE_TABLE_TITLE") + 3]) == pytest.approx(
        0.001)


def test_mat024_validation():
    base = dict(mid=1, density=7850.0, modulus=210_000.0)
    with pytest.raises(ValueError, match="either curve or table"):
        Mat024(**base)
    with pytest.raises(ValueError, match="either curve or table"):
        Mat024(**base, curve=CURVE, table=TABLE)
    with pytest.raises(ValueError, match="leave c"):
        Mat024(**base, table=TABLE, c=40.0, p=5.0)
    with pytest.raises(ValueError, match="both"):
        Mat024(**base, curve=CURVE, c=40.0)
    with pytest.raises(ValueError, match="kg/m"):
        Mat024(mid=1, density=7.85e-6, modulus=210_000.0, curve=CURVE)
    with pytest.raises(ValueError, match="MPa"):
        Mat024(mid=1, density=7850.0, modulus=210.0 * 0.0001, curve=CURVE)
    with pytest.raises(ValueError, match="poisson"):
        Mat024(**base, curve=CURVE, poisson=0.5)
    with pytest.raises(ValueError, match="vp"):
        Mat024(**base, curve=CURVE, vp=2)


def test_write_include_file(tmp_path):
    mat = Mat024(mid=7, density=7850.0, modulus=210_000.0, curve=CURVE,
                 fail=0.42, title="DP600",
                 provenance={"tests": "DP-L01..L03 (0.001 /s)", "law": "Swift-Voce"})
    path = mat.write(tmp_path / "dp600.k", "mm-s-t", date=dt.date(2026, 11, 2))
    text = path.read_text()
    lines = text.splitlines()
    assert lines[0] == "$ DP600 (*MAT_024, MID 7)"
    assert lines[1].startswith("$ Written by crashmetrics ")
    assert lines[1].endswith("on 2026-11-02")
    assert lines[2] == "$ Units: mm-s-t (mm, s, t, N, MPa)"
    assert "$ tests: DP-L01..L03 (0.001 /s)" in lines
    assert "*KEYWORD" in lines and lines[-1] == "*END"
    data = card_lines(text)
    assert float(fields(data[data.index("DP600") + 1])[6]) == 0.42


def test_failure_strain():
    eps_f = fracture_strain(0.55)
    assert eps_f == pytest.approx(math.log(1 / 0.45))
    assert failure_strain(uniform=0.15, fracture=eps_f, element_size=1.2,
                          neck_length=1.2) == pytest.approx(eps_f)
    assert failure_strain(uniform=0.15, fracture=0.75, element_size=5.0,
                          neck_length=1.0) == pytest.approx(0.15 + 0.6 / 5)
    with pytest.raises(ValueError, match="fraction"):
        fracture_strain(55.0)
    with pytest.raises(ValueError, match="uniform < fracture"):
        failure_strain(uniform=0.5, fracture=0.4, element_size=1.0, neck_length=1.0)
