"""Tests for crashmetrics.binout (LS-DYNA binout reader).

The real file is the binout of the plate-buckling run in
``tests/data/lsdyna/pladebuk`` (LS-DYNA R14, MIT licence); the same run
wrote the ASCII rcforc, spcforc, glstat and matsum next to it, so every
value is compared with what the solver printed. Synthetic files (written
with `write_binout`) cover single precision, restarts, several files,
sub-folders, per-state IDs, truncated files and whole runs converted to
binout, where every analysis must give the same result as from ASCII.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from crashmetrics.binout import find_binout, main, read_binout, write_binout
from crashmetrics.lsdyna_ascii import read_rcforc, read_run, read_spcforc

PLATE = Path(__file__).parent / "data" / "lsdyna" / "pladebuk"


# --------------------------------------------------------------------------
# The real binout against the ASCII files of the same run


@pytest.fixture(scope="module")
def plate():
    with read_binout(PLATE / "binout") as bo:
        yield bo


def test_structure_and_symbol_tables(plate):
    assert plate.branches == ["glstat", "matsum", "rcforc", "spcforc", "tprint"]
    assert plate.verify() == []  # symbol tables agree with every record
    assert not plate.notes
    meta = plate.metadata("glstat")
    assert meta["version"] == "smp d R14"
    assert meta["revision"] == "515"
    assert meta["date"] == "12/12/2022"
    assert meta["build_id"] == "R14.0_515_8a12796b62"
    assert meta["title"].startswith("LS-DYNA SIMULERING AF VARME")
    assert "spcforc: 2 states, time 0 to 0.1, 32 entities" in plate.summary()
    assert plate.variables("spcforc")[-3:] == ["misc/x_moment0", "misc/y_moment0",
                                               "misc/z_moment0"]
    v = plate.variable("glstat", "time_step")
    assert (v.type, v.count) == (10, 1)
    assert "nodout" not in plate and "rcforc" in plate
    with pytest.raises(KeyError, match="No output 'nodout'"):
        plate.time("nodout")


def test_rcforc_equals_ascii(plate):
    a, b = read_rcforc(PLATE / "rcforc"), plate.output("rcforc")
    assert a.ids == b.ids == (80085, 8008, 80086, 8009)
    assert a.names == b.names
    assert b.names[8008] == "Right_on_right_action"
    np.testing.assert_array_equal(a.time, b.time)
    for name, values in a.data.items():
        np.testing.assert_array_equal(values, b.data[name])
    assert {"surfa_tie_count", "surfb_tie_area"} <= set(b.data)


def test_spcforc_equals_ascii(plate):
    a, b = read_spcforc(PLATE / "spcforc"), plate.output("spcforc")
    assert a.ids == b.ids and len(a.ids) == 32
    np.testing.assert_array_equal(a.time, b.time)
    for name in ("x_force", "y_force", "z_force"):
        # ASCII prints five significant digits
        np.testing.assert_allclose(b.data[name], a.data[name], rtol=5e-5, atol=1e-9)
        np.testing.assert_allclose(b.totals[name], a.totals[name], rtol=5e-5)
    assert b.totals["y_force"][1] == pytest.approx(13.76860144)


def test_glstat_and_matsum_equal_ascii(plate):
    text = (PLATE / "glstat").read_text()
    ascii_values = {
        m.group(1).strip(): float(m.group(2))
        for m in re.finditer(r"^ (\S.*?)\s*\.{2,}\s*([-+0-9.E]+)\s*$", text, re.M)
    }
    pairs = {
        "time step": "time_step",
        "internal energy": "internal_energy",
        "spring and damper energy": "spring_and_damper_energy",
        "total energy": "total_energy",
        "total energy / initial energy": "energy_ratio",
        "kinetic energy": "kinetic_energy",
        "added mass": "added_mass",
        "percentage increase": "percent_increase",
    }
    for label, name in pairs.items():
        assert plate.read("glstat", name)[0] == pytest.approx(ascii_values[label])
    assert plate.read("glstat", "internal_energy")[0] == 2e-20
    m = plate.output("matsum")
    assert m.ids == (1, 2, 3)
    assert m.names == {1: "middle", 2: "left", 3: "right"}  # ASCII legend
    assert np.all(m.data["internal_energy"] == 0.0)


def test_read_shapes_and_text(plate):
    assert plate.read("spcforc", "x_force").shape == (2, 32)
    assert plate.read("spcforc", "x_resultant").shape == (2,)
    assert plate.read("glstat", "cycle").dtype == np.int64
    assert plate.time("spcforc").tolist() == [0.0, 0.1]
    with pytest.raises(KeyError, match="no variable"):
        plate.read("spcforc", "nothing")
    temps = plate.output("tprint")
    assert len(temps.ids) == 20276 and "temperature" in temps.data


def test_run_folder_uses_binout_when_ascii_is_missing(tmp_path):
    shutil.copy(PLATE / "binout", tmp_path / "binout")
    assert find_binout(tmp_path) == [tmp_path / "binout"]
    outputs = read_run(tmp_path)
    assert set(outputs) == {"rcforc", "spcforc"}
    shutil.copy(PLATE / "rcforc", tmp_path / "rcforc")
    outputs = read_run(tmp_path)
    assert outputs["rcforc"].version.startswith("ls-dyna smp d R14 R14.0_515_8a12796 ")


def test_command_line(plate, tmp_path, capsys):
    assert main([str(PLATE / "binout"), "--csv", str(tmp_path), "--output",
                 "spcforc"]) == 0
    out = capsys.readouterr().out
    assert "spcforc: 2 states" in out and "spcforc.csv" in out
    header = (tmp_path / "spcforc.csv").read_text().splitlines()[0]
    assert header.startswith("time,x_force[19381]")


# --------------------------------------------------------------------------
# Synthetic files


def _states(n, start=1, t0=0.0, dt=1.0):
    return [(f"d{start + i:06d}", t0 + i * dt) for i in range(n)]


def test_single_precision_subfolders_and_per_state_ids(tmp_path):
    folders = {
        "/elout/shell/metadata": {"title": "t", "version": "mpp s R12"},
        "/nodout/metadata": {"ids": np.array([5, 7], dtype=np.int32)},
    }
    for k, (d, t) in enumerate(_states(3)):
        folders[f"/elout/shell/{d}"] = {
            "time": np.array([t], dtype=np.float32),
            "ids": np.array([10, 11] if k < 2 else [11, 12], dtype=np.int32),
            "sig_xx": np.array([k, k + 0.5], dtype=np.float32),
            "plastic_strain": np.zeros(6, dtype=np.float32),  # 3 points each
        }
        folders[f"/nodout/{d}"] = {
            "time": np.array([t]),
            "cycle": np.array([10 * k], dtype=np.int32),
            "x_displacement": np.array([k, -k], dtype=np.float32),
        }
        folders[f"/nodout/{d}/misc"] = {"flag": np.array([1, 1], dtype=np.int32)}
    path = write_binout(tmp_path / "binout", folders)
    bo = read_binout(path)
    assert bo.verify() == []
    assert bo.branches == ["elout/shell", "nodout"]
    assert bo.variable("nodout", "x_displacement").type == 9
    e = bo.output("elout/shell")
    assert e.ids == (10, 11, 12)
    np.testing.assert_array_equal(e.data["sig_xx"][:, 0], [0.0, 1.0, np.nan])
    np.testing.assert_array_equal(e.data["sig_xx"][:, 2], [np.nan, np.nan, 2.5])
    assert "plastic_strain" not in e.data  # several values per element
    assert bo.read("elout/shell", "plastic_strain").shape == (3, 6)
    n = bo.output("nodout")
    assert n.ids == (5, 7) and n.cycle.tolist() == [0.0, 10.0, 20.0]
    assert n.data["x_displacement"][:, 1].tolist() == [0.0, -1.0, -2.0]
    assert bo.read("nodout", "misc/flag").tolist() == [[1, 1]] * 3


def test_restart_and_several_files(tmp_path):
    first = {"/glstat/metadata": {"title": "run"}}
    for d, t in _states(5):  # t = 0 ... 4
        first[f"/glstat/{d}"] = {"time": np.array([t]),
                                 "kinetic_energy": np.array([10.0 - t]),
                                 "internal_energy": np.array([t])}
    second = {}
    for d, t in _states(4, start=6, t0=2.5):  # restarted from t = 2.5
        second[f"/glstat/{d}"] = {"time": np.array([t]),
                                  "kinetic_energy": np.array([100.0]),
                                  "internal_energy": np.array([t])}
    write_binout(tmp_path / "binout0000", first)
    write_binout(tmp_path / "binout0001", second)
    (tmp_path / "d3plot").write_bytes(b"x")
    assert [p.name for p in find_binout(tmp_path)] == ["binout0000", "binout0001"]
    bo = read_binout(tmp_path)
    assert bo.time("glstat").tolist() == [0.0, 1.0, 2.0, 2.5, 3.5, 4.5, 5.5]
    g = bo.glstat()
    assert g.kinetic.tolist() == [10.0, 9.0, 8.0, 100.0, 100.0, 100.0, 100.0]
    assert bo.metadata("glstat")["title"] == "run"


def test_truncated_and_invalid_files(tmp_path):
    folders = {"/swforc/metadata": {"ids": np.array([1, 2])}}
    for d, t in _states(4):
        folders[f"/swforc/{d}"] = {"time": np.array([t]),
                                   "axial": np.array([t, 2 * t])}
    path = write_binout(tmp_path / "binout", folders)
    raw = path.read_bytes()
    cut = raw.index(b"axial", raw.index(b"/swforc/d000004")) + 3
    path.write_bytes(raw[:cut])  # the run stopped while writing
    bo = read_binout(path)
    assert bo.time("swforc").tolist() == [0.0, 1.0, 2.0, 3.0]
    axial = bo.output("swforc").data["axial"]
    assert axial[2].tolist() == [2.0, 4.0] and np.isnan(axial[3]).all()
    assert any("incomplete record" in n for n in bo.notes)
    assert any("symbol table" in p for p in bo.verify())
    (tmp_path / "bad").write_bytes(b"\x08\x08\x08\x02\x01\x01\x00\x00" + b"\0" * 9)
    with pytest.raises(ValueError, match="not a binout file"):
        read_binout(tmp_path / "bad")
    (tmp_path / "big").write_bytes(b"\x08\x08\x08\x01\x01\x00\x00\x00" + b"\0" * 9)
    with pytest.raises(ValueError, match="little-endian"):
        read_binout(tmp_path / "big")
    with pytest.raises(FileNotFoundError):
        read_binout(tmp_path / "missing")
    empty = tmp_path / "empty_run"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="No binout"):
        read_binout(empty)


def test_contact_sides_and_single_sided_sleout(tmp_path):
    folders = {
        "/rcforc/metadata": {"ids": np.array([1, 1, 2, 2]),
                             "side": np.array([0, 1, 0, 1])},
        "/sleout/metadata": {"ids": np.array([1, 2]),
                             "single_sided": np.array([1, 0])},
        "/spcforc/metadata": {"force_ids": np.array([9, 9, 8]),
                              "moment_ids": np.array([], dtype=np.int64)},
    }
    for d, t in _states(2):
        folders[f"/rcforc/{d}"] = {"time": np.array([t]),
                                   "x_force": np.array([1.0, -1.0, 2.0, -2.0]) * t}
        folders[f"/sleout/{d}"] = {
            "time": np.array([t]),
            "slave": np.array([3.0, 4.0]) * t,
            "master": np.array([5.0]) * t,  # only the two-sided contact
            "friction_energy": np.array([0.5, 0.25]),
            "total_slave": np.array([7.0 * t]),
            "total_energy": np.array([12.0 * t]),
        }
        folders[f"/spcforc/{d}"] = {"time": np.array([t]),
                                    "x_force": np.array([1.0, 2.0, 4.0]),
                                    "x_resultant": np.array([7.0])}
    bo = read_binout(write_binout(tmp_path / "binout", folders))
    rc = bo.output("rcforc")
    assert rc.ids == (1, 2)
    assert rc.data["surfa_x_force"][1].tolist() == [1.0, 2.0]
    assert rc.data["surfb_x_force"][1].tolist() == [-1.0, -2.0]
    sl = bo.output("sleout")
    assert sl.data["surfa_energy"][1].tolist() == [3.0, 4.0]
    assert sl.data["surfb_energy"][1].tolist() == [0.0, 5.0]
    assert sl.totals["surfa_energy"].tolist() == [0.0, 7.0]
    assert sl.totals["total_energy"].tolist() == [0.0, 12.0]
    spc = bo.output("spcforc")
    assert spc.ids == (9, 8)
    assert spc.data["x_force"][0].tolist() == [3.0, 4.0]  # a node in two sets
    assert spc.totals["x_force"].tolist() == [7.0, 7.0]


# --------------------------------------------------------------------------
# A whole run as binout: every analysis gives the same result


_GLOBAL = {
    "kinetic": "kinetic_energy", "internal": "internal_energy",
    "hourglass": "hourglass_energy", "sliding": "sliding_interface_energy",
    "external_work": "external_work", "damping": "system_damping_energy",
    "total": "total_energy", "energy_ratio": "energy_ratio",
    "added_mass": "added_mass", "added_mass_percent": "percent_increase",
    "time_step": "time_step",
}


def _to_binout(run: Path, target: Path) -> None:
    """Write a run's ASCII outputs as one binout (binout variable names)."""
    from crashmetrics.lsdyna import read_glstat, read_matsum

    folders: dict[str, dict[str, object]] = {}
    g = read_glstat(run / "glstat")
    folders["/glstat/metadata"] = {"title": "synthetic"}
    for i, t in enumerate(g.time):
        d = {"time": np.array([t])}
        for field, name in _GLOBAL.items():
            v = getattr(g, field)
            if v is not None:
                d[name] = np.array([v[i]])
        folders[f"/glstat/d{i + 1:06d}"] = d
    m = read_matsum(run / "matsum")
    ids = np.asarray(m.part_ids)
    folders["/matsum/metadata"] = {
        "ids": ids,
        "legend": "".join(m.part_names.get(int(k), "").ljust(80) for k in ids),
        "legend_ids": ids,
    }
    for i, t in enumerate(m.time):
        d = {"time": np.array([t]), "internal_energy": m.internal[i]}
        for field, name in (("kinetic", "kinetic_energy"),
                            ("hourglass", "hourglass_energy"),
                            ("added_mass", "added_cms_mass")):
            if getattr(m, field) is not None:
                d[name] = getattr(m, field)[i]
        folders[f"/matsum/d{i + 1:06d}"] = d
    outputs = read_run(run)
    for kind in ("secforc", "swforc"):
        o = outputs[kind]
        folders[f"/{kind}/metadata"] = {"ids": np.asarray(o.ids)}
        for i, t in enumerate(o.time):
            d = {"time": np.array([t])}
            d.update({c: v[i] for c, v in o.data.items()})
            folders[f"/{kind}/d{i + 1:06d}"] = d
    s = outputs["sleout"]
    folders["/sleout/metadata"] = {"ids": np.asarray(s.ids),
                                   "single_sided": np.zeros(len(s.ids), dtype=int)}
    names = {"surfa_energy": "slave", "surfb_energy": "master",
             "friction_energy": "friction_energy"}
    totals = {"surfa_energy": "total_slave", "surfb_energy": "total_master",
              "friction_energy": "total_friction", "total_energy": "total_energy"}
    for i, t in enumerate(s.time):
        d = {"time": np.array([t])}
        d.update({names[c]: v[i] for c, v in s.data.items()})
        d.update({totals[c]: np.array([v[i]]) for c, v in s.totals.items()})
        folders[f"/sleout/d{i + 1:06d}"] = d
    write_binout(target / "binout", folders)


def test_synthetic_run_from_binout_gives_the_same_results(tmp_path):
    from crashmetrics.loadpath import energy_ranking, load_run
    from crashmetrics.lsdyna import check_run
    from crashmetrics.quality import check_model
    from crashmetrics.spotweld import load_welds, weld_summary
    from crashmetrics.synthetic import frontal_model, simulate

    ascii_run, binout_run = tmp_path / "ascii", tmp_path / "binout"
    simulate(frontal_model("baseline")).write(ascii_run)
    binout_run.mkdir()
    _to_binout(ascii_run, binout_run)
    shutil.copy(ascii_run / "d3hsp", binout_run / "d3hsp")

    a, b = load_run(ascii_run, "run"), load_run(binout_run, "run")
    assert energy_ranking(a).table() == energy_ranking(b).table()
    np.testing.assert_array_equal(
        a.sections.data["x_force"], b.sections.data["x_force"]
    )
    assert weld_summary(load_welds(ascii_run, "run")).table() == weld_summary(
        load_welds(binout_run, "run")).table()
    target = {"target_mass": 1500.0, "target_cg": (1305, 0, 550)}
    qa = check_model(ascii_run, "run", **target)
    qb = check_model(binout_run, "run", **target)
    assert qa.table() == qb.table()
    assert qb.files["glstat"].endswith("binout")
    assert check_run(ascii_run).summary() == check_run(binout_run).summary()


def test_synthetic_run_written_as_binout(tmp_path):
    from crashmetrics.loadpath import load_run
    from crashmetrics.spotweld import load_welds
    from crashmetrics.synthetic import frontal_model, simulate

    sim = simulate(frontal_model("weak_welds_front_rail_lh"))
    sim.write(tmp_path / "ascii")
    path, _ = sim.write(tmp_path / "bin", binout=True)
    assert sorted(p.name for p in (tmp_path / "bin").iterdir()) == ["binout", "d3hsp"]
    bo = read_binout(path)
    assert bo.verify() == []
    assert bo.branches == ["glstat", "matsum", "secforc", "swforc", "sleout"]
    assert bo.legend("matsum")[120] == "Front rail LH"
    a, b = load_run(tmp_path / "ascii"), load_run(tmp_path / "bin")
    np.testing.assert_allclose(b.energies.internal, a.energies.internal,
                               rtol=1e-4, atol=1e-3)
    wa, wb = load_welds(tmp_path / "ascii"), load_welds(tmp_path / "bin")
    assert wa.ids == wb.ids and np.isfinite(wb.failure_time).sum() > 0
    np.testing.assert_array_equal(wa.failure_time, wb.failure_time)


def test_springs_weld_failure_times_and_sub_outputs(tmp_path):
    one = np.frombuffer(np.float32(1.0).tobytes(), np.int32)[0]  # as LS-DYNA writes
    folders = {
        "/deforc/metadata": {"ids": np.array([1, 2]),
                             "irot": np.array([0, one], dtype=np.int32)},
        "/swforc/metadata": {"ids": np.array([7, 8])},
        "/jntforc/type0/metadata": {"ids": np.array([100])},
        "/jntforc/type1/metadata": {"ids": np.array([200])},
    }
    for k, (d, t) in enumerate(_states(3)):
        folders[f"/deforc/{d}"] = {"time": np.array([t]),
                                   "x_force": np.array([10.0, 2.0]),
                                   "displacement": np.array([0.5, 0.1])}
        folders[f"/swforc/{d}"] = {
            "time": np.array([t]),
            "failure": np.array([0.0, 1.0 if k else 0.0]),
            "failure_time": np.array([1e16, -1e6 if k else 1e16]),
        }
        folders[f"/jntforc/type0/{d}"] = {"time": np.array([t]),
                                          "phi_degrees": np.array([t])}
        folders[f"/jntforc/type1/{d}"] = {"time": np.array([t]),
                                          "alpha_degrees": np.array([2 * t])}
    bo = read_binout(write_binout(tmp_path / "binout", folders))
    springs = bo.output("deforc")
    assert springs.data["x_force"][0].tolist()[0] == 10.0
    assert np.isnan(springs.data["x_force"][0, 1])
    assert springs.data["x_moment"][0, 1] == 2.0
    assert springs.data["change_in_length"][0, 0] == 0.5
    assert springs.data["relative_rotation"][0, 1] == 0.1
    welds = bo.output("swforc")
    assert np.isnan(welds.data["failure_time"]).all()  # no time stored
    assert "jntforc" in bo and "jntforc" not in bo.branches
    joints = bo.output("jntforc")
    assert joints.ids == (100, 200)
    assert joints.data["alpha_degrees"][:, 1].tolist() == [0.0, 2.0, 4.0]
    assert np.isnan(joints.data["alpha_degrees"][:, 0]).all()
