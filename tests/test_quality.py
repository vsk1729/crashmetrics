"""Tests for crashmetrics.quality (model quality check sheet)."""

import dataclasses
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from crashmetrics.d3hsp import read_d3hsp
from crashmetrics.energy_check import EnergyLimits
from crashmetrics.lsdyna import read_glstat, read_matsum
from crashmetrics.lsdyna_ascii import AsciiOutput, read_sleout
from crashmetrics.quality import (
    QualityLimits,
    check_model,
    check_model_data,
    quality_matrix,
)
from crashmetrics.synthetic import (
    ModelQuality,
    frontal_model,
    simulate,
    write_sleout,
)

DATA = Path(__file__).parent / "data" / "lsdyna"
TARGET = {"target_mass": 1500.0, "target_cg": (1305.0, 0.0, 550.0)}


@pytest.fixture(scope="module")
def folders(tmp_path_factory):
    root = tmp_path_factory.mktemp("quality")
    sims = {v: simulate(frontal_model(v))
            for v in ("baseline", "poor_model_quality")}
    for v, sim in sims.items():
        sim.write(root / v)
    broken = replace(frontal_model(), name="error run", quality=ModelQuality(
        error_at=38.0, mass_scaled=False, timestep_drop=0.25))
    simulate(broken).write(root / "error")
    return root, sims


def test_synthetic_files_round_trip(folders):
    root, sims = folders
    sim = sims["poor_model_quality"]
    g = read_glstat(root / "poor_model_quality" / "glstat")
    ref = sim.global_energies(g.time)
    np.testing.assert_allclose(g.total_energy(), ref.total_energy(), rtol=1e-4)
    assert g.added_mass_percent[0] == pytest.approx(5.8)
    assert g.added_mass_percent.max() == pytest.approx(7.9)
    assert g.time_step[0] == pytest.approx(1.0e-3)
    s = read_sleout(root / "poor_model_quality" / "sleout")
    assert s.ids == (1, 2, 3) and s.names[2] == "Front end self contact"
    np.testing.assert_allclose(s.totals["total_energy"],
                               sim.contact_output(s.time).totals["total_energy"],
                               rtol=1e-4, atol=1e-3)
    assert s.data["surfa_energy"][-1, 1] < 0
    d = read_d3hsp(root / "poor_model_quality" / "d3hsp")
    assert d.termination == "normal" and d.total_mass == 1500.0
    assert d.mass_center == (1310.0, 2.0, 545.0)
    assert d.part_masses[200] == pytest.approx(1500.0 - 63.0)
    assert sum(d.part_masses.values()) == pytest.approx(1500.0)
    assert d.smallest_timesteps[0].part_id == 150
    assert len(d.messages) == 37 and d.problem_time == 100.0
    e = read_d3hsp(root / "error" / "d3hsp")
    assert e.termination == "error" and e.problem_time == 38.0
    assert e.messages[-1].kind == "error"
    assert read_glstat(root / "error" / "glstat").time[-1] == 38.0
    with pytest.raises(ValueError, match="Missing channels"):
        write_sleout(root / "x", AsciiOutput("sleout", np.zeros(1), (1,), {}))


def test_good_model(folders):
    root, _ = folders
    sheet = check_model(root / "baseline", **TARGET)
    assert sheet.passed and sheet.failures == () and sheet.warnings == ()
    assert sheet.run == "baseline" and set(sheet.files) == {
        "d3hsp", "glstat", "matsum", "sleout"}
    n = sheet.counts()
    assert n["FAIL"] == 0 and n["SKIP"] == 1 and n["PASS"] >= 15
    assert sheet.verdict() == "PASSED, 1 skipped"
    assert sheet.check("Added mass per part").status == "SKIP"
    assert sheet.check("Total mass").value.startswith("1500.0 kg (+0.00 %")
    assert sheet.check("Centre of gravity").number == pytest.approx(7.35, abs=0.01)
    assert sheet.check("Added mass, peak").number == pytest.approx(0.6)
    assert sheet.check("Energy ratio").number == pytest.approx(1.009, abs=1e-3)
    assert sheet.check("Smallest elements").number == pytest.approx(1.2346, rel=1e-3)
    assert sheet.check("Warnings").status == "INFO"
    assert "PASS Termination" in sheet.summary()
    assert "| Run | Termination | normal | normal | ✅ PASS |" in sheet.table()
    with pytest.raises(KeyError, match="No check"):
        sheet.check("Paint colour")


def test_poor_model(folders):
    root, _ = folders
    sheet = check_model(root / "poor_model_quality", **TARGET)
    assert not sheet.passed
    assert [c.name for c in sheet.failures] == [
        "Added mass, start", "Added mass, peak", "Hourglass energy per part",
        "Negative energy per contact"]
    assert [c.name for c in sheet.warnings] == ["Added mass, growth",
                                               "Smallest elements"]
    assert sheet.verdict() == "FAILED (4 checks), 2 warnings, 1 skipped"
    assert sheet.check("Added mass, peak").value == "7.90 % (118 kg)"
    hg = sheet.check("Hourglass energy per part")
    assert hg.number == pytest.approx(18.8, abs=0.1)
    assert "over the limit: part 110, 111" in hg.note
    contact = sheet.check("Negative energy per contact")
    assert "contact 2 (Front end self contact)" in contact.value
    assert contact.number == pytest.approx(4.43, abs=0.02)
    assert sheet.check("Smallest elements").number == pytest.approx(22.7, abs=0.1)
    # Team limits change the verdict.
    loose = QualityLimits(added_mass=10.0, contact_negative=None, warnings=10,
                          added_mass_growth=None, element_mass_factor=None,
                          energy=EnergyLimits(part_hourglass=0.25))
    relaxed = check_model(root / "poor_model_quality", limits=loose)
    assert relaxed.passed
    assert relaxed.check("Warnings").status == "WARN"
    assert relaxed.check("Negative energy per contact").status == "INFO"
    assert relaxed.check("Total mass").status == "INFO"
    heavy = check_model(root / "baseline", target_mass=1450.0,
                        target_cg=(1280.0, 0.0, 550.0))
    assert [c.name for c in heavy.failures] == ["Total mass", "Centre of gravity"]


def test_error_run_and_missing_files(folders, tmp_path):
    root, _ = folders
    sheet = check_model(root / "error")
    assert sheet.check("Termination").status == "FAIL"
    end = sheet.check("End time reached")
    assert end.status == "FAIL" and end.number == pytest.approx(38.0)
    assert sheet.check("Errors").value == "1"
    assert "40509" in sheet.check("Errors").note
    assert sheet.check("Mass scaling").value == "off (dt2ms 0)"
    step = sheet.check("Time step")
    assert step.status == "WARN" and step.number > 10
    assert sheet.check("Smallest elements").status == "INFO"
    # Only some files, and one that cannot be read.
    shutil.copy(root / "baseline" / "glstat", tmp_path / "job1.glstat")
    (tmp_path / "matsum").write_text("not a matsum file\n")
    partial = check_model(tmp_path, "partial")
    assert partial.passed and "matsum could not be read" in partial.notes[0]
    assert partial.check("Termination").status == "SKIP"
    assert partial.check("Negative energy per contact").status == "SKIP"
    assert "Note: matsum could not be read" in partial.summary()
    assert "- matsum could not be read" in partial.table()
    only = tmp_path / "only"
    only.mkdir()
    shutil.copy(root / "poor_model_quality" / "sleout", only / "sleout")
    no_ref = check_model(only).check("Negative energy per contact")
    assert no_ref.status == "INFO" and "kJ in contact 2" in no_ref.value
    assert check_model(only).check("Energy balance").status == "SKIP"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="No d3hsp"):
        check_model(empty)
    (empty / "glstat").write_text("nothing\n")
    with pytest.raises(ValueError, match="No readable"):
        check_model(empty)
    with pytest.raises(FileNotFoundError, match="not a directory"):
        check_model(tmp_path / "missing")
    with pytest.raises(ValueError, match="at least one"):
        check_model_data("x")
    with pytest.raises(ValueError, match="unit_system"):
        check_model_data("x", glstat=read_glstat(root / "baseline" / "glstat"),
                         unit_system="inch")


def test_added_mass_per_part_and_units(folders):
    root, sims = folders
    d = read_d3hsp(root / "baseline" / "d3hsp")
    p = read_matsum(root / "baseline" / "matsum")
    added = np.zeros_like(p.internal)
    added[:, list(p.part_ids).index(150)] = np.linspace(0.0, 0.4, len(p.time))
    added[:, list(p.part_ids).index(120)] = 0.3
    sheet = check_model_data("parts", d3hsp=d, matsum=dataclasses.replace(
        p, added_mass=added))
    part = sheet.check("Added mass per part")
    assert part.status == "FAIL" and part.number == pytest.approx(40.0)
    assert "part 150 (Subframe extension LH)" in part.value
    assert part.note == "over the limit: part 150"
    # The same run in tonnes and seconds gives the same sheet values.
    g = sims["baseline"].global_energies(np.arange(0.0, 100.5, 0.5))
    tonnes = dataclasses.replace(
        g, time=g.time / 1000.0, time_step=g.time_step / 1000.0,
        added_mass=g.added_mass / 1000.0, added_mass_percent=None)
    d_t = dataclasses.replace(d, total_mass=d.total_mass / 1000.0)
    a = check_model_data("kg", d3hsp=d, glstat=g)
    b = check_model_data("t", d3hsp=d_t, glstat=tonnes, unit_system="mm-s-t")
    for name in ("Total mass", "Added mass, peak", "Time step"):
        assert a.check(name).value == b.check(name).value, name
    metres = check_model_data("m", d3hsp=dataclasses.replace(
        d, mass_center=(1.31, 0.002, 0.545)), unit_system="m-s-kg",
        target_cg=(1305.0, 0.0, 550.0))
    assert metres.check("Centre of gravity").number == pytest.approx(7.35, abs=0.01)


def test_matrix(folders):
    root, _ = folders
    sheets = [check_model(root / v, **TARGET)
              for v in ("baseline", "poor_model_quality")]
    table = quality_matrix(sheets)
    assert "| Group | Check | baseline | poor_model_quality |" in table
    assert "| Mass | Added mass, peak | ✅ 0.600 | ❌ 7.90 |" in table
    assert "| Run | Warnings | ℹ️ 2 | ℹ️ 37 |" in table
    assert "| | **Verdict** | **PASSED** | **FAILED** |" in table
    assert "7.90" not in quality_matrix(sheets, values=False)
    partial = check_model_data("glstat only",
                               glstat=read_glstat(root / "baseline" / "glstat"))
    assert quality_matrix([partial, sheets[0]]).count("\n") == len(
        sheets[0].checks) + 2
    with pytest.raises(ValueError, match="at least one sheet"):
        quality_matrix([])


def test_real_lsdyna_files():
    # MIT data: a drop test's glstat and matsum, and its trimmed d3hsp.
    run = check_model(DATA / "kagent" / "drop_e2e", unit_system="mm-s-t")
    assert run.passed and run.check("Energy ratio").value == "1.000"
    assert run.check("Added mass, peak").status == "SKIP"
    assert run.check("Time step").value.startswith("0.841 µs")
    d = read_d3hsp(DATA / "kagent" / "cold_start" / "d3hsp_minimal")
    assert d.mass_center == pytest.approx((-4.8957577e-10, -4.895761e-10, 2.8125846))
    sheet = check_model_data("cold start", d3hsp=d, unit_system="mm-s-t")
    assert sheet.check("Termination").status == "PASS"
    assert sheet.check("Total mass").value == "0.134 kg"
    assert sheet.check("Centre of gravity").value == "(0, 0, 2.81) mm"
    assert sheet.check("Mass scaling").value == "off (dt2ms 0)"
    assert sheet.check("End time reached").status == "PASS"
