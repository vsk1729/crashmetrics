"""Tests for crashmetrics.loadpath.

The synthetic frontal model (crashmetrics.synthetic) gives runs with a
known cause: a weak LH front rail that crushes before the crash box,
and a car without its lower load path.
"""

import dataclasses
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from crashmetrics.loadpath import (
    UNITS,
    CrashRun,
    SectionForces,
    compare_runs,
    crush_sequence,
    energy_history,
    energy_matrix,
    energy_ranking,
    force_metrics,
    load_run,
    load_split,
    loadpath_report,
    section_forces,
    select_parts,
    select_sections,
)
from crashmetrics.synthetic import frontal_model, simulate

DATA = Path(__file__).parent / "data" / "lsdyna"
_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")
VARIANTS = ("baseline", "weak_front_rail_lh", "no_lower_path")
GROUPS = {"crash boxes": "Crash box*", "front rails": "Front rail*",
          "rear rails": "Rear rail*", "upper rails": "Upper rail*",
          "lower path": "Subframe*", "bumper": "Bumper*"}
PATHS = {"upper": "Upper rail*", "middle": "Front rail*",
         "lower": "Subframe extension*"}
CHAINS = {s: ["Bumper*", f"Crash box {s}", f"Front rail {s}", f"Rear rail {s}"]
          for s in ("LH", "RH")}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    out = {}
    for v in VARIANTS:
        simulate(frontal_model(v)).write(root / v)
        out[v] = load_run(root / v)
    return out


def test_load_and_select(runs, tmp_path):
    b = runs["baseline"]
    assert b.name == "baseline" and b.unit_system == "mm-ms-kg"
    assert select_parts(b, "crash box*") == [110, 111]
    assert select_parts(b, [120, "Front rail*"]) == [120, 121]
    assert select_sections(b, "Upper rail*") == [21, 22]
    with pytest.raises(KeyError, match="No part 999"):
        select_parts(b, 999)
    with pytest.raises(KeyError, match="title matches"):
        select_parts(b, "Door*")
    # Prefixed names and a run with only one of the two files.
    shutil.copy(Path(b.source) / "matsum", tmp_path / "job7.matsum")
    only = load_run(tmp_path)
    assert only.sections is None and only.energies is not None
    with pytest.raises(ValueError, match="no section forces"):
        section_forces(only)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="No matsum or secforc"):
        load_run(empty)
    with pytest.raises(FileNotFoundError, match="not a directory"):
        load_run(tmp_path / "missing")
    with pytest.raises(ValueError, match="unit_system"):
        CrashRun("x", b.energies, unit_system="inch")
    with pytest.raises(ValueError, match="no part energies and no section"):
        CrashRun("x")


def test_energy_ranking(runs):
    b = runs["baseline"]
    r = energy_ranking(b, exclude="Body*", groups=GROUPS)
    assert 200 in r.excluded and all(row.part_id != 200 for row in r.rows)
    assert r.rows[0].name.startswith("Front rail")
    assert sum(x.share for x in r.rows) == pytest.approx(100.0)
    assert r.rows[-1].cumulative == pytest.approx(100.0)
    assert r.total == pytest.approx(sum(x.energy for x in r.rows))
    assert sum(g.energy for g in r.groups) == pytest.approx(r.total)
    crash_boxes = r.groups[0]
    assert crash_boxes.onset < crash_boxes.half < crash_boxes.end < 20.0
    assert r.rows[0].hourglass == pytest.approx(2.0, abs=0.1)     # front rail 2 %
    table = r.table(5)
    assert table.count("\n| ") >= 5 and "| crash boxes |" in table
    early = energy_ranking(b, time=10.0, parts=["Crash box*", "Front rail*"])
    assert early.time == pytest.approx(10.0)
    assert early.rows[0].name.startswith("Crash box")
    t, hist = energy_history(b, {"boxes": "Crash box*"})
    assert hist["boxes"][-1] == pytest.approx(crash_boxes.energy)
    assert len(t) == len(hist["boxes"])


def test_units():
    run = simulate(frontal_model(), end_time=10.0)
    e = run.part_energies()
    a = CrashRun("a", e)
    b = CrashRun("b", dataclasses.replace(
        e, time=e.time / 1000.0, internal=e.internal * 1000.0), unit_system="mm-s-t")
    ra, rb = energy_ranking(a), energy_ranking(b)
    assert rb.total == pytest.approx(ra.total)
    assert rb.time == pytest.approx(ra.time)
    assert UNITS["mm-s-t"] == (1e-3, 1e-6, 1e3)


def test_section_forces_and_metrics(runs):
    b = runs["baseline"]
    f = section_forces(b)
    assert set(f.components) == {"x"}
    # Upper rails are written with a rearward normal (+x compression).
    assert f.flipped == tuple(sid not in (21, 22) for sid in f.ids)
    assert np.all(_trapz(f.force, f.time, axis=0) > 0)
    raw = section_forces(b, [11], component="x", orientation="as_written")
    assert _trapz(raw[11], raw.time) < 0
    total = section_forces(b, [11], component="total")
    assert not total.flipped[0]
    with pytest.raises(KeyError, match="No section 99"):
        f[99]
    filtered = section_forces(b, [11], cfc=60)
    assert filtered[11].max() < f[11].max()
    # Unevenly spaced output (as MPP writes it) is resampled before filtering.
    s = b.sections
    keep = np.unique(np.concatenate([np.arange(0, len(s.time), 2),
                                     np.arange(1, len(s.time), 7)]))
    uneven = dataclasses.replace(s, time=s.time[keep],
                                 data={k: v[keep] for k, v in s.data.items()})
    u = section_forces(CrashRun("uneven", sections=uneven), [11], cfc=60)
    assert np.ptp(np.diff(u.time)) < 1e-9
    assert u[11].max() == pytest.approx(filtered[11].max(), rel=0.05)
    m = {x.section_id: x for x in force_metrics(f)}
    assert m[11].peak > m[13].peak > m[15].peak
    assert m[11].onset < 1.0 and 40 < m[11].end < 60
    # A triangle: peak 100 kN at 10 ms, impulse 1000 kN ms.
    t = np.linspace(0.0, 20.0, 201)
    tri = SectionForces("t", t, (1,), {1: "s"}, (100 - 10 * np.abs(t - 10))[:, None],
                        ("x",), (False,))
    (x,) = force_metrics(tri)
    assert (x.peak, x.peak_time) == (100.0, 10.0)
    assert x.impulse == pytest.approx(1000.0)
    assert (x.onset, x.end) == (pytest.approx(1.0), pytest.approx(19.0))
    (w,) = force_metrics(tri, window=(10.0, 20.0))
    assert w.impulse == pytest.approx(500.0)


def test_load_split(runs):
    f = section_forces(runs["baseline"])
    s = load_split(f, PATHS, target={"upper": 20, "middle": 55, "lower": 25})
    assert sum(s.share) == pytest.approx(100.0)
    assert s.share == pytest.approx((16.6, 59.5, 23.9), abs=0.3)
    assert s.passed and "middle" in s.summary()
    assert s.history.shape == (len(f.time), 3)
    ok = s.history[np.isfinite(s.history[:, 0])]
    np.testing.assert_allclose(ok.sum(axis=1), 100.0)
    tight = load_split(f, PATHS, target={"upper": 20, "middle": 55, "lower": 25},
                       tolerance=2.0)
    assert any(w.startswith("middle carries 59.") for w in tight.warnings)
    twice = load_split(f, {"a": "Front rail LH", "b": ["Front rail LH", 14]})
    assert any("section 13 is in both" in w for w in twice.warnings)
    with pytest.raises(ValueError, match="No target"):
        load_split(f, PATHS, target={"upper": 20})
    shifted = load_split(section_forces(runs["no_lower_path"]),
                         {k: v for k, v in PATHS.items() if k != "lower"})
    assert shifted.share[1] > 75


def test_crush_sequence(runs):
    base = crush_sequence(runs["baseline"], CHAINS)
    assert all(c.passed for c in base)
    lh, rh = crush_sequence(runs["weak_front_rail_lh"], CHAINS)
    assert not lh.passed and rh.passed
    assert lh.violations[0].startswith("Front rail LH starts at 3.99 ms")
    assert "before Crash box LH" in lh.violations[0]
    assert "OUT OF ORDER" in lh.summary()
    strict = crush_sequence(runs["baseline"], CHAINS, overlap=1.01)
    assert strict[0].warnings                     # stages overlap a little
    rear = crush_sequence(runs["baseline"], CHAINS, min_energy=0.1)[0].stages[-1]
    assert not rear.crushed and math.isnan(rear.onset)
    assert "not crushed" in crush_sequence(runs["baseline"], CHAINS,
                                           min_energy=0.1)[0].summary()


def test_compare_runs(runs):
    b = runs["baseline"]
    c = compare_runs(b, runs["weak_front_rail_lh"], exclude="Body*", groups=GROUPS)
    assert c.culprits[0].name == "Front rail LH" and c.culprits[0].change < -10
    assert sum(p.share_of_change for p in c.culprits) >= 80.0
    assert {p.name for p in c.culprits} >= {"Rear rail LH"}
    groups = {g.name: g for g in c.groups}
    assert groups["crash boxes"].change == pytest.approx(0.0, abs=0.01)
    assert groups["rear rails"].change > 5
    ratings = {s.section_id: s.rating for s in c.sections}
    assert all(0 < r <= 1 for r in ratings.values())
    assert ratings[13] < ratings[14]                 # the LH rail changed
    assert "Front rail LH (120)" in c.summary()
    same = compare_runs(b, b, rate=False)
    assert same.culprits == () and same.sections[0].rating is None
    assert same.total[0] == same.total[1]
    gone = compare_runs(b, runs["no_lower_path"], exclude="Body*", groups=GROUPS)
    assert any("parts only in baseline: [150, 151, 152]" in n for n in gone.notes)
    assert any("group lower path: no parts" in n for n in gone.notes)
    assert any("sections only in baseline: [31, 32]" in n for n in gone.notes)
    assert "removed" in gone.summary()


def test_matrix_and_report(runs, tmp_path):
    m = energy_matrix(list(runs.values()), exclude="Body*")
    assert m.runs == tuple(VARIANTS)
    i = m.part_ids.index(152)
    assert math.isnan(m.values[i, 2])
    table = m.table(5)
    assert "| Front rail LH (120) | 32.6" in table and "(-15.2)" in table
    csv = m.to_csv(tmp_path / "m.csv").read_text().splitlines()
    assert csv[0] == "part_id,name,baseline,weak_front_rail_lh,no_lower_path"
    report = loadpath_report(runs["weak_front_rail_lh"], baseline=runs["baseline"],
                             exclude="Body*", groups=GROUPS, paths=PATHS,
                             chains=CHAINS)
    for text in ("# Load paths: weak_front_rail_lh", "## Energy absorption",
                 "## Load split", "## Crush sequence", "❌ **LH**", "✅ **RH**",
                 "## Against baseline", "Front rail LH (120)"):
        assert text in report


def test_real_lsdyna_files():
    # Two runs of a helmet study (MIT data): one upper-neck section.
    a = load_run(DATA / "helmet" / "pendulum", "run0")
    b = load_run(DATA / "helmet" / "pendulum_run1", "run1")
    f = section_forces(a)
    assert f.components == ("z",) and f.flipped == (True,)
    (m,) = force_metrics(f)
    assert m.peak == pytest.approx(3.7824)
    c = compare_runs(a, b)
    assert c.parts == () and "no part energies" in c.summary()
    (s,) = c.sections
    assert s.peak == (pytest.approx(3.7824), pytest.approx(3.8292))
    assert 0.8 < s.rating < 1.0
    # A drop test matsum in mm-ton-s (energies in mJ).
    k = load_run(DATA / "kagent" / "drop_e2e", unit_system="mm-s-t")
    r = energy_ranking(k)
    assert r.rows[0].name.startswith("aluminum plate")
    assert r.total == pytest.approx(
        float(k.energies.internal[-1].sum()) * 1e-6)
