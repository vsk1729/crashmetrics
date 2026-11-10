"""Tests for crashmetrics.spotweld.

The synthetic frontal model gives a baseline whose welds all hold and a
variant whose LH front rail flange welds unzip (known failure times).
"""

import math

import numpy as np
import pytest

from crashmetrics.lsdyna_ascii import AsciiOutput, detect_kind, read_swforc
from crashmetrics.spotweld import (
    WeldLimits,
    compare_welds,
    failure_history,
    groups_by_id,
    load_welds,
    weld_report,
    weld_summary,
)
from crashmetrics.synthetic import frontal_model, simulate, write_swforc

GROUPS = frontal_model().weld_groups()
LIMITS = {"default": WeldLimits(9.0, 12.0),
          "Front rail LH flange": WeldLimits(11.0, 14.0),
          "Front rail RH flange": WeldLimits(11.0, 14.0),
          "Rear rail LH flange": WeldLimits(9.0, 13.0),
          "Rear rail RH flange": WeldLimits(9.0, 13.0),
          "Upper rail LH flange": WeldLimits(4.5, 6.0),
          "Upper rail RH flange": WeldLimits(4.5, 6.0)}


@pytest.fixture(scope="module")
def sims():
    return {v: simulate(frontal_model(v))
            for v in ("baseline", "weak_welds_front_rail_lh")}


@pytest.fixture(scope="module")
def runs(sims, tmp_path_factory):
    root = tmp_path_factory.mktemp("welds")
    out = {}
    for v, sim in sims.items():
        sim.write(root / v)
        out[v] = load_welds(root / v)
    return out


def test_limits():
    lim = WeldLimits(8.0, 10.0)
    np.testing.assert_allclose(lim.function([8.0, 0.0, 4.0], [0.0, 10.0, 5.0]),
                               [1.0, 1.0, 0.5])
    np.testing.assert_allclose(lim.utilisation([4.0, -8.0], [5.0, 5.0]),
                               [math.sqrt(0.5), 0.5])            # compression ignored
    assert WeldLimits(8.0, 10.0, compression=True).utilisation(-8.0, 0.0) == 1.0
    # Different exponents: scaling both forces by 1 / utilisation meets the limit.
    mixed = WeldLimits(8.0, 10.0, n=1.0, m=2.0)
    u = mixed.utilisation([3.0, 0.0], [6.0, 0.0])
    assert mixed.function(3.0 / u[0], 6.0 / u[0]) == pytest.approx(1.0)
    assert u[1] == 0.0
    with pytest.raises(ValueError, match="positive"):
        WeldLimits(0.0, 1.0)


def test_synthetic_welds(sims):
    base, weak = sims["baseline"], sims["weak_welds_front_rail_lh"]
    assert len(base.weld_ids) == 84 and not np.isfinite(base.weld_failure_time).any()
    line = [weak.weld_ids.index(i) for i in GROUPS["Front rail LH flange"]]
    times = weak.weld_failure_time[line]
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0)    # front first
    assert times[0] == pytest.approx(14.1) and times[-1] == pytest.approx(39.1)
    others = np.delete(weak.weld_failure_time, line)
    assert not np.isfinite(others).any()
    # The rail loses strength as its welds go: it absorbs less energy.
    rail = lambda r: r.plastic_energy[("main LH", 120)][-1]      # noqa: E731
    assert rail(weak) < rail(base) - 2000.0
    with pytest.raises(ValueError, match="No weld line"):
        frontal_model().replace_welds("Door flange", count=3)


def test_swforc_round_trip(sims, runs, tmp_path):
    sim = sims["weak_welds_front_rail_lh"]
    run = runs["weak_welds_front_rail_lh"]
    assert detect_kind(run.source) == "swforc"
    assert run.ids == sim.weld_ids and run.time[1] == pytest.approx(0.5)
    out = sim.weld_output(run.time)
    np.testing.assert_allclose(run.shear, out.data["shear"], atol=1e-4)
    np.testing.assert_allclose(run.axial, out.data["axial"], atol=1e-4)
    # Failure is seen at the first output state at or after the true time.
    late = run.failure_time - sim.weld_failure_time
    assert np.nanmin(late) >= 0 and np.nanmax(late) < 0.5
    assert run.failed[0] == 120001 and len(run.failed) == 14
    assert read_swforc(run.source).data["length"][0, 0] == pytest.approx(1.2)
    with pytest.raises(ValueError, match="Missing channels"):
        write_swforc(tmp_path / "x", AsciiOutput("swforc", np.zeros(1), (1,), {}))
    with pytest.raises(FileNotFoundError, match="No swforc"):
        load_welds(tmp_path)
    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_welds(tmp_path / "missing")
    with pytest.raises(ValueError, match="unit_system"):
        load_welds(run.source, unit_system="inch")
    with pytest.raises(KeyError, match="no weld 5"):
        run.index(5)
    newton = load_welds(sim.weld_output(), "n", unit_system="mm-s-t")
    assert newton.shear.max() == pytest.approx(sim.weld_shear.max() / 1000.0)
    assert newton.time[-1] == pytest.approx(sim.weld_time[-1] * 1000.0)


def test_summary(runs):
    base = weld_summary(runs["baseline"], limits=LIMITS, groups=GROUPS)
    assert base.failed == () and len(base.welds) == 84
    close = base.critical()
    assert [w.weld_id for w in close] == [110001, 111001]
    assert close[0].utilisation == pytest.approx(0.85, abs=0.01)
    assert base.critical(0.99) == ()
    groups = {g.name: g for g in base.groups()}
    assert groups["Front rail LH flange"].welds == 14
    assert groups["Front rail LH flange"].utilisation == pytest.approx(0.74, abs=0.01)
    assert math.isnan(groups["Rear rail LH flange"].first_failure)
    table = base.table()
    assert "84 welds, 0 failed" in table and "| 110001 | Crash box LH flange | 85 %" \
        in table

    weak = weld_summary(runs["weak_welds_front_rail_lh"], limits=LIMITS,
                        groups=GROUPS)
    failed = weak.failed
    assert [w.weld_id for w in failed] == list(GROUPS["Front rail LH flange"])
    first = failed[0]
    assert first.failure_time == pytest.approx(14.5)
    assert first.shear_at_failure == pytest.approx(4.4, abs=0.05)
    assert first.axial_at_failure == pytest.approx(0.0, abs=0.01)
    # It failed far below the design limit: a weld problem, not a load problem.
    assert first.utilisation < 0.4
    assert "| ... 4 more |" in weak.table()

    plain = weld_summary(runs["baseline"])
    assert all(math.isnan(w.utilisation) for w in plain.welds)
    assert plain.groups()[0].name == "(no group)"
    partial = weld_summary(runs["baseline"], limits={"Crash box LH flange":
                                                     WeldLimits(9.0, 12.0)},
                           groups={"Crash box LH flange": [110001, 110002, 5]})
    assert sum(math.isfinite(w.utilisation) for w in partial.welds) == 2
    assert "1 group weld IDs are not in the run" in partial.notes[0]


def test_failure_history(runs):
    none = failure_history(runs["baseline"], groups=GROUPS)
    assert none.sequence == () and none.count[-1] == 0
    assert none.summary() == "Weld failures, baseline: none"
    h = failure_history(runs["weak_welds_front_rail_lh"], groups=GROUPS)
    assert h.count[-1] == 14 and np.all(np.diff(h.count) >= 0)
    assert h.by_group["Front rail LH flange"][-1] == 14
    assert h.by_group["Front rail RH flange"][-1] == 0
    assert h.sequence[0] == (pytest.approx(14.5), 120001, "Front rail LH flange")
    assert h.first == {"Front rail LH flange": (pytest.approx(14.5), 120001)}
    assert [len(b.welds) for b in h.bursts] == [3, 8]
    assert h.bursts[1].start == pytest.approx(39.0)
    assert h.bursts[1].end == pytest.approx(39.5)
    assert "burst: 8 welds of Front rail LH flange" in h.summary()
    wide = failure_history(runs["weak_welds_front_rail_lh"], burst_window=20.0)
    assert [len(b.welds) for b in wide.bursts] == [14] and wide.bursts[0].group == ""
    assert "no group" in wide.summary()


def test_compare(runs):
    base, weak = runs["baseline"], runs["weak_welds_front_rail_lh"]
    c = compare_welds(base, weak, limits=LIMITS, groups=GROUPS)
    assert c.failed == (0, 14) and len(c.new_failures) == 14
    assert c.new_failures[0].weld_id == 120001
    assert c.new_failures[0].utilisation[0] == pytest.approx(0.74, abs=0.01)
    assert ("Front rail LH flange", 14, 0, 14) in c.groups
    text = c.summary()
    assert "failed welds 0 -> 14 (+14)" in text and "... 9 more" in text
    back = compare_welds(weak, base, limits=LIMITS, groups=GROUPS)
    assert len(back.recovered) == 14 and back.new_failures == ()
    same = compare_welds(weak, weak)
    assert same.earlier == same.later == same.new_failures == ()
    # The same welds failing 5 ms sooner, and a weld missing from one run.
    sooner = load_welds(AsciiOutput(
        "swforc", weak.time[:-10], weak.ids[1:],
        {"axial": weak.axial[10:, 1:], "shear": weak.shear[10:, 1:],
         "failure": (weak.time[10:, None] >= np.where(
             np.isfinite(weak.failure_time[1:]), weak.failure_time[1:], np.inf)
         ).astype(float)}), "sooner")
    shifted = compare_welds(weak, sooner, groups=GROUPS)
    assert len(shifted.earlier) == 14 and shifted.later == ()
    assert shifted.earlier[0].failure_time[1] == pytest.approx(
        shifted.earlier[0].failure_time[0] - 5.0)
    assert any("1 welds only in weak_welds_front_rail_lh" in n for n in shifted.notes)
    assert "Earlier failures:" in shifted.summary()
    assert len(compare_welds(sooner, weak).later) == 14
    # A weld that holds in both but is loaded more.
    harder = load_welds(AsciiOutput(
        "swforc", base.time, base.ids,
        {"axial": base.axial, "shear": base.shear * 1.1,
         "failure": np.zeros_like(base.shear)}), "harder")
    more = compare_welds(base, harder, limits=LIMITS, groups=GROUPS)
    assert more.increased[0].utilisation[1] > more.increased[0].utilisation[0]
    assert "Welds that hold but are loaded more:" in more.summary()


def test_groups_by_id_and_report(runs):
    weak = runs["weak_welds_front_rail_lh"]
    auto = groups_by_id(weak)
    assert list(auto)[:2] == ["110xxx", "111xxx"] and len(auto["120xxx"]) == 14
    named = groups_by_id(weak, 1000, {120: "Front rail LH"})
    assert named["Front rail LH"] == list(range(120001, 120015))
    with pytest.raises(ValueError, match="divisor"):
        groups_by_id(weak, 0)
    report = weld_report(weak, baseline=runs["baseline"], limits=LIMITS,
                         groups=GROUPS)
    for text in ("# Spot welds: weak_welds_front_rail_lh", "84 welds, 14 failed",
                 "## Failure over time", "## Against baseline",
                 "failed welds 0 -> 14"):
        assert text in report


def test_failure_measure_and_printed_time():
    # Some weld materials print a failure measure between 0 and 1, and
    # failed welds can carry "failure time=".
    t = np.array([0.0, 1.0, 2.0, 3.0])
    out = AsciiOutput("swforc", t, (7, 8), {
        "axial": np.array([[0, 0], [1, 1], [2, 0], [2.5, 0]], dtype=float),
        "shear": np.zeros((4, 2)),
        "failure": np.array([[0, 0], [0.4, 0.6], [0.7, 1.0], [0.9, 1.0]]),
        "failure_time": np.array([[np.nan] * 2, [np.nan] * 2, [np.nan, 1.6],
                                  [np.nan, 1.6]])})
    run = load_welds(out, "measure")
    assert run.measure is not None
    assert run.failure_time[1] == pytest.approx(1.6) and math.isnan(run.failure_time[0])
    s = weld_summary(run)
    assert s.welds[0].utilisation == pytest.approx(0.9)
    assert "file's own failure measure" in s.notes[0]
    assert [w.weld_id for w in s.critical()] == [7]
