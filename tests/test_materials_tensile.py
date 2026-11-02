"""Tests for crashmetrics.materials.tensile.

The reference curve is a synthetic steel with Swift hardening
``sigma = K (eps0 + eps_p)^n`` (true stress, true plastic strain) and
E = 210 GPa, converted to engineering values; every property is checked
against values computed independently from the same law.
"""

import math
import zipfile

import numpy as np
import pytest

from crashmetrics.materials import (
    TensileTest,
    clean_tensile,
    read_tensile,
    tensile_properties,
)

E, K, EPS0, N = 210_000.0, 900.0, 0.005, 0.2


def swift_curve(eps_p_max=0.35, points=1500, fracture=True):
    """Engineering strain and stress of the Swift steel, elastic part included."""
    sig_y = K * EPS0 ** N
    sig_el = np.linspace(0.0, sig_y, 60, endpoint=False)
    eps_p = np.linspace(0.0, eps_p_max, points)
    sig = np.concatenate((sig_el, K * (EPS0 + eps_p) ** N))
    eps_true = sig / E + np.concatenate((np.zeros(60), eps_p))
    e_eng = np.expm1(eps_true)
    s_eng = sig * np.exp(-eps_true)
    if fracture:                                   # sudden drop, then a tail
        e_eng = np.concatenate((e_eng, e_eng[-1] + [1e-4, 2e-4, 3e-4]))
        s_eng = np.concatenate((s_eng, [80.0, 10.0, 2.0]))
    return e_eng, s_eng


def exact_rm_ag():
    """Rm and Agt of the Swift steel: maximum of the engineering stress."""
    eps_p = np.linspace(0.1, 0.3, 200_001)
    sig = K * (EPS0 + eps_p) ** N
    eps = sig / E + eps_p
    s = sig * np.exp(-eps)
    i = int(np.argmax(s))
    return s[i], np.expm1(eps[i])


def exact_rp02():
    """Engineering stress where the curve crosses E (e - 0.002)."""
    eps_p = np.linspace(0.0, 0.02, 400_001)
    sig = K * (EPS0 + eps_p) ** N
    eps = sig / E + eps_p
    e, s = np.expm1(eps), sig * np.exp(-eps)
    gap = s - E * (e - 0.002)
    i = int(np.flatnonzero(gap <= 0)[0])
    return s[i]


def test_properties_of_the_swift_steel():
    e, s = swift_curve(fracture=False)
    p = tensile_properties(TensileTest(e, s))
    # Small-strain slope of the engineering curve: E (1 - 2 eps) ~ E.
    assert p.modulus == pytest.approx(E, rel=2e-3)
    assert p.modulus_r2 > 0.9999
    assert p.yield_strength == pytest.approx(exact_rp02(), rel=2e-3)
    rm, agt = exact_rm_ag()
    assert p.tensile_strength == pytest.approx(rm, rel=1e-5)
    assert p.uniform_elongation_total == pytest.approx(agt, rel=2e-3)
    assert p.uniform_elongation == pytest.approx(
        p.uniform_elongation_total - p.tensile_strength / p.modulus, rel=1e-12)
    # Considère: necking near eps_true_p = n - eps0 = 0.195.
    assert math.log1p(p.uniform_elongation_total) == pytest.approx(N - EPS0 + rm
                                                                   / E, abs=3e-3)
    assert p.yield_ratio == pytest.approx(p.yield_strength / p.tensile_strength)
    assert "Rp0.2" in p.summary("DX") and "GPa" in p.summary()


def test_force_elongation_conversion():
    e, s = swift_curve(fracture=False)
    area, gauge = 20.0 * 1.5, 80.0
    t = TensileTest.from_force_elongation(s * area, e * gauge, gauge_length=gauge,
                                          width=20.0, thickness=1.5, name="flat")
    np.testing.assert_allclose(t.stress, s)
    np.testing.assert_allclose(t.strain, e)
    assert t.info["area_mm2"] == 30.0
    round_ = TensileTest.from_force_elongation([0.0, 100.0, 200.0], [0, 0.1, 0.2],
                                               gauge_length=50.0, diameter=10.0)
    assert round_.stress[1] == pytest.approx(100.0 / (math.pi * 25.0))
    with pytest.raises(ValueError, match="one of them"):
        TensileTest.from_force_elongation([1, 2, 3], [1, 2, 3], gauge_length=50.0,
                                          area=10.0, diameter=3.0)
    with pytest.raises(ValueError, match="gauge_length"):
        TensileTest.from_force_elongation([1, 2, 3], [1, 2, 3], gauge_length=0.0,
                                          area=10.0)


def test_cut_after_fracture():
    e, s = swift_curve()
    clean = clean_tensile(TensileTest(e, s), toe=False)
    assert len(clean) == len(e) - 3
    assert clean.info["cleaning"]["points_cut"] == 3
    p = tensile_properties(clean)
    assert p.fracture_stress == pytest.approx(s[-4])
    assert p.elongation_after_fracture == pytest.approx(e[-4] - s[-4] / p.modulus)


def test_toe_correction_recovers_the_origin():
    e, s = swift_curve()
    # Seating toe: 0.3 % extra strain at the start, softening below 60 MPa.
    toe = 0.003 + 0.002 * np.clip(1 - s / 60.0, 0, 1) ** 2
    raw = TensileTest(e + np.where(s > 0, toe, 0.0), s)
    clean = clean_tensile(raw)
    assert clean.strain[0] == 0.0 and clean.stress[0] == 0.0
    assert clean.info["cleaning"]["toe_strain_shift"] == pytest.approx(0.003, abs=1e-5)
    p, ref = tensile_properties(clean), tensile_properties(TensileTest(e, s))
    assert p.yield_strength == pytest.approx(ref.yield_strength, rel=1e-3)
    assert p.uniform_elongation_total == pytest.approx(
        ref.uniform_elongation_total, abs=1e-5)


def test_smoothing_removes_noise():
    e, s = swift_curve(fracture=False)
    noisy = s + np.random.default_rng(1).normal(0.0, 4.0, len(s))
    clean = clean_tensile(TensileTest(e, noisy), smooth=31, toe=False,
                          cut_fracture=False)
    plastic = slice(200, None)
    assert np.std(clean.stress[plastic] - s[plastic]) < 1.5
    assert clean.info["cleaning"]["smoothing_window"] == 31
    with pytest.raises(ValueError, match="odd"):
        clean_tensile(TensileTest(e, s), smooth=30)


def test_errors():
    with pytest.raises(ValueError, match="equal length"):
        TensileTest([0, 1, 2], [0, 1])
    with pytest.raises(ValueError, match="finite"):
        TensileTest([0, 1, np.nan], [0, 1, 2])
    e, s = swift_curve(fracture=False)
    with pytest.raises(ValueError, match="points between"):
        tensile_properties(TensileTest(e[::200], s[::200]), modulus_window=(0.1, 0.2))
    with pytest.raises(ValueError, match="fractions"):
        tensile_properties(TensileTest(e, s), modulus_window=(0.5, 0.2))


# --- Files -----------------------------------------------------------------


def test_read_csv_stress_strain_with_units_row(tmp_path):
    e, s = swift_curve(fracture=False)
    lines = ["Test DP-01;;", "Strain;Stress;Time", "[%];[MPa];[s]"]
    lines += [f"{x * 100:.6f};{y:.4f};{i * 0.01:.2f}".replace(".", ",")
              for i, (x, y) in enumerate(zip(e, s))]
    path = tmp_path / "dp01.csv"
    path.write_text("\n".join(lines), encoding="cp1252")
    t = read_tensile(path)
    assert t.name == "dp01"
    assert t.info["units"] == {"strain": "%", "stress": "MPa"}
    np.testing.assert_allclose(t.strain, e, atol=1e-8)
    np.testing.assert_allclose(t.stress, s, atol=1e-4)


def test_read_text_force_elongation_in_kn(tmp_path):
    e, s = swift_curve(fracture=False)
    area, gauge = 12.5 * 2.0, 50.0
    lines = ["Time(s) Force(kN) Extension(mm)"]
    lines += [f"{i * 0.01:.2f} {y * area / 1000:.7f} {x * gauge:.6f}"
              for i, (x, y) in enumerate(zip(e, s))]
    path = tmp_path / "run.txt"
    path.write_text("\n".join(lines))
    t = read_tensile(path, gauge_length=gauge, width=12.5, thickness=2.0)
    assert t.info["units"] == {"force": "kN", "elongation": "mm"}
    np.testing.assert_allclose(t.stress, s, rtol=1e-6, atol=1e-3)
    np.testing.assert_allclose(t.strain, e, atol=2e-8)
    with pytest.raises(ValueError, match="gauge_length"):
        read_tensile(path, width=12.5, thickness=2.0)


def test_read_by_column_name_and_index(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("eps,sig,eps_true\n0,0,0\n0.001,210,0.001\n0.002,300,0.002\n")
    t = read_tensile(path, strain="eps", stress=1)
    assert t.stress.tolist() == [0.0, 210.0, 300.0]
    with pytest.raises(ValueError, match="several columns"):
        read_tensile(path, strain="eps", stress="s")
    with pytest.raises(ValueError, match="Could not find"):
        read_tensile(path)
    with pytest.raises(ValueError, match="not both"):
        read_tensile(path, strain=0, stress=1, force=2)


def _xlsx(path, rows):
    """Minimal .xlsx: shared strings for text, numbers inline."""
    strings = sorted({c for r in rows for c in r if isinstance(c, str)})
    index = {t: i for i, t in enumerate(strings)}

    def cell(j, i, v):
        ref = f"{chr(65 + j)}{i + 1}"
        if isinstance(v, str):
            return f'<c r="{ref}" t="s"><v>{index[v]}</v></c>'
        return f'<c r="{ref}"><v>{v!r}</v></c>'

    sheet = "".join(f'<row r="{i + 1}">' + "".join(cell(j, i, v) for j, v in
                                                   enumerate(r)) + "</row>"
                    for i, r in enumerate(rows))
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    p = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{m}" xmlns:r="{r}"><sheets>'
                   f'<sheet name="Notes" sheetId="1" r:id="rId1"/>'
                   f'<sheet name="Data" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="{p}">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
                   '</Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{m}">' + "".join(
            f"<si><t>{t}</t></si>" for t in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<worksheet xmlns="{m}"><sheetData/></worksheet>')
        z.writestr("xl/worksheets/sheet2.xml",
                   f'<worksheet xmlns="{m}"><sheetData>{sheet}</sheetData></worksheet>')


def test_read_xlsx(tmp_path):
    e, s = swift_curve(fracture=False)
    rows = [["Specimen", "DP-02"], ["Eng. strain (-)", "Eng. stress (GPa)"]]
    rows += [[float(x), float(y) / 1000.0] for x, y in zip(e[::10], s[::10])]
    path = tmp_path / "dp02.xlsx"
    _xlsx(path, rows)
    t = read_tensile(path, sheet="Data")
    assert t.info["units"]["stress"] == "GPa"
    np.testing.assert_allclose(t.stress, s[::10], rtol=1e-12)
    assert read_tensile(path, sheet=1).stress[5] == pytest.approx(s[50])
    with pytest.raises(ValueError, match="No sheet"):
        read_tensile(path, sheet="Raw")
    (tmp_path / "old.xls").write_bytes(b"x")
    with pytest.raises(ValueError, match=".xls files"):
        read_tensile(tmp_path / "old.xls")
