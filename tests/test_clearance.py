"""Tests for crashmetrics.pedestrian.clearance and .synthetic (bonnet
clearance, bottoming out, why a headform point is red)."""

import math
from pathlib import Path

import numpy as np
import pytest

from crashmetrics.lsdyna_ascii import read_nodout
from crashmetrics.mesh import read_mesh
from crashmetrics.pedestrian import headform_score
from crashmetrics.pedestrian.clearance import (
    DIAGNOSES,
    HEADFORMS,
    PULSE_SHAPES,
    Clearance,
    Headform,
    HeadImpact,
    assess_grid,
    assess_impact,
    clearance,
    clearance_map,
    clearance_table,
    compare_grids,
    head_impact,
    impact_direction,
    read_impact_points,
    required_clearance,
    surface_normals,
)
from crashmetrics.pedestrian.synthetic import VARIANTS, bonnet_model, simulate_grid
from crashmetrics.synthetic import write_nodout

DATA = Path(__file__).parent / "data" / "lsdyna"
G = 9.80665


# --- Headforms, directions, geometry --------------------------------------------


def test_headforms_and_directions():
    child, adult = HEADFORMS["child"], HEADFORMS["adult"]
    assert (child.mass, child.angle, adult.mass, adult.angle) == (3.5, 50.0, 4.5, 65.0)
    assert child.radius == 82.5 and child.velocity == pytest.approx(11.111, abs=1e-3)
    assert child.energy == pytest.approx(0.5 * 3.5 * (40 / 3.6) ** 2)
    d = impact_direction("child")
    np.testing.assert_allclose(d, [math.cos(math.radians(50)), 0,
                                   -math.sin(math.radians(50))])
    np.testing.assert_allclose(impact_direction(90.0), [0, 0, -1], atol=1e-12)
    np.testing.assert_allclose(impact_direction(0.0, rearward=(-1, 0, 0)), [-1, 0, 0])
    with pytest.raises(ValueError, match="perpendicular"):
        impact_direction("adult", rearward=(1, 0, 1))
    with pytest.raises(ValueError, match="Unknown headform"):
        impact_direction("giant")


def test_swept_sphere_against_known_geometry():
    plane = np.array([[x, y, 0.0] for x in range(-300, 301, 5)
                      for y in range(-300, 301, 5)], dtype=float)
    top = (0.0, 0.0, 60.0)
    # Straight down onto a plane: the free space is the height.
    c = clearance({"p": top}, {"Floor": plane}, (0, 0, -1))["p"]
    assert c.distance == pytest.approx(60.0, abs=1e-9) and c.part == "Floor"
    assert c.lateral == pytest.approx(0.0, abs=1e-9)
    # At 50 degrees to a level surface: the sphere touches the surface at
    # the point with its centre above it, so the travel is height / sin(50).
    level = plane + [0, 0, 60.0]
    c = clearance([top], {"Floor": plane}, impact_direction(50.0), surface=level)[0]
    assert c.distance == pytest.approx(60.0 / math.sin(math.radians(50)), abs=0.2)
    assert c.centre == pytest.approx((0.0, 0.0, 142.5))
    assert c.normal_distance == pytest.approx(60.0, abs=1e-6)
    # Without the surface the point is taken as the sphere's leading point
    # along the path (head-on), which is lower here: less space.
    head_on = clearance([top], {"Floor": plane}, impact_direction(50.0))[0]
    r = 82.5
    assert head_on.distance == pytest.approx(
        (60 + r * math.sin(math.radians(50)) - r) / math.sin(math.radians(50)),
        abs=0.2)
    # One point 40 mm off the line: u = s + R - sqrt(R^2 - r^2).
    q = {"Bolt": np.array([[40.0, 0.0, -100.0]])}
    c = clearance([(0, 0, 0)], q, (0, 0, -1))[0]
    assert c.distance == pytest.approx(100 + 82.5 - math.sqrt(82.5 ** 2 - 40 ** 2))
    assert c.lateral == pytest.approx(40.0) and c.contact == (40.0, 0.0, -100.0)
    # Off the sphere's path, or farther than max_distance: free.
    assert clearance([(0, 0, 0)], {"Bolt": np.array([[90.0, 0, -50]])},
                     (0, 0, -1))[0].free
    assert clearance([(0, 0, 0)], q, (0, 0, -1), max_distance=50)[0].free
    # The nearest of several parts; metres are converted.
    two = {"Far": np.array([[0, 0, -0.2]]), "Near": np.array([[0, 0, -0.05]])}
    c = clearance([(0, 0, 0)], two, (0, 0, -1), unit_system="m-s-kg")[0]
    assert c.part == "Near" and c.distance == pytest.approx(50.0)
    with pytest.raises(ValueError, match="at least one hard part"):
        clearance([top], {}, (0, 0, -1))


def test_surface_normals_and_normal_clearance():
    xs = np.linspace(-200, 200, 41)
    gx, gy = np.meshgrid(xs, xs)
    tilt = math.radians(10)
    surface = np.column_stack([gx.ravel(), gy.ravel(), np.tan(tilt) * gx.ravel()])
    n = surface_normals(surface, [(0, 0, 0)])[0]
    np.testing.assert_allclose(n, [-math.sin(tilt), 0, math.cos(tilt)], atol=1e-9)
    floor = surface - [0, 0, 70.0]
    c = clearance([(0, 0, 0)], {"Floor": floor}, (0, 0, -1), surface=surface)[0]
    assert c.normal_distance == pytest.approx(70 * math.cos(tilt), abs=0.5)
    assert c.normal_part == "Floor"


def test_required_clearance_matches_the_square_wave_analytically():
    v = 40 / 3.6
    t = (v / G) ** (5 / 3) * 1000 ** (-2 / 3)              # s, shorter than 15 ms
    assert required_clearance(1000, shape="square") == pytest.approx(
        1000 * v * t / 2, rel=5e-3)                        # 68.4 mm
    a = (300 / 0.015) ** 0.4                                # window-limited
    assert required_clearance(300, shape="square") == pytest.approx(
        1000 * v * (v / (a * G)) / 2, rel=5e-3)
    sizes = [required_clearance(1000, shape=s) for s in ("square", "half_sine",
                                                         "triangle")]
    assert sizes == sorted(sizes)
    assert required_clearance(650) > required_clearance(1000) > required_clearance(1700)
    assert required_clearance(1000, speed=35) < required_clearance(1000)
    assert set(PULSE_SHAPES) >= {"square", "half_sine", "triangle"}
    table = clearance_table()
    assert "| 1000 (yellow) | 68 |" in table and table.count("\n") == 7
    with pytest.raises(ValueError, match="Unknown shape"):
        required_clearance(1000, shape="sawtooth")


def test_read_impact_points(tmp_path):
    path = tmp_path / "points.csv"
    path.write_text("Row,Column,x,y,z,headform,run\n3,-2,300,-200,820,adult,r3\n"
                    "A,1,0,0,0,,\n")
    pts = read_impact_points(path)
    assert pts[(3, -2)].point == (300.0, -200.0, 820.0)
    assert pts[(3, -2)].headform == "adult"
    assert pts[(3, -2)].run == str(tmp_path / "r3")
    assert pts[("A", 1)].headform == "child" and pts[("A", 1)].run == ""
    bad = tmp_path / "bad.csv"
    bad.write_text("row,x\n1,2\n")
    with pytest.raises(ValueError, match="needs the columns"):
        read_impact_points(bad)


# --- One impact -----------------------------------------------------------------


def _impact(acc_g, dt=0.05, headform="child"):
    """A HeadImpact from an acceleration pulse (g) starting at contact."""
    hf = HEADFORMS[headform]
    a = np.asarray(acc_g, dtype=float)
    t = np.arange(len(a)) * dt
    v = hf.velocity - np.concatenate(([0.0], np.cumsum(0.5 * (a[1:] + a[:-1]) * dt)
                                      )) * G / 1000.0
    x = np.concatenate(([0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * dt)))
    return HeadImpact("pulse", t, a, x, v, hf, (1.0, 0.0, 0.0), 0.0, None)


def test_bottoming_found_in_the_pulse_alone():
    t = np.arange(0, 16, 0.05)
    a = np.where(t < 2, 120 * np.sin(np.pi * t / 2), 50.0)
    a = a + np.where((t >= 8) & (t <= 10), 300 * np.sin(np.pi * (t - 8) / 2), 0.0)
    imp = _impact(a)
    r = assess_impact(imp)
    assert r.bottoming and r.bottoming_source == "pulse"
    assert 7.9 < r.bottoming_time < 8.6
    assert r.residual_speed == pytest.approx(np.interp(r.bottoming_time, imp.time,
                                                       imp.velocity))
    assert r.diagnosis == "bottoming" and r.colour == "red"
    assert r.extra_space == pytest.approx(
        1000 * r.residual_speed ** 2 / (2 * r.plateau * G))
    assert r.residual_share == pytest.approx(r.residual_energy / HEADFORMS["child"]
                                             .energy)
    assert math.isnan(r.clearance) and math.isnan(r.margin)
    # The same pulse with a geometry: both say so; geometry gives the time.
    both = assess_impact(imp, 70.0)
    assert both.bottoming_source in ("both", "geometry")
    assert both.margin < 0


def test_ok_stiff_and_first_peak_diagnoses():
    t = np.arange(0, 16, 0.05)
    soft = _impact(np.where(t < 2, 100 * np.sin(np.pi * t / 2), 55.0) * (t < 15))
    r = assess_impact(soft, Clearance((0, 0, 0), (1, 0, 0), 150.0, "Engine", None,
                                      0.0))
    assert r.diagnosis == "ok" and not r.bottoming and r.colour in ("green", "yellow")
    assert r.margin == pytest.approx(150 - 5 + 3 - r.penetration)
    stiff = _impact(np.where(t < 2, 100 * np.sin(np.pi * t / 2), 110.0) * (t < 10.5))
    assert assess_impact(stiff, 300.0).diagnosis == "stiff"
    spike = _impact(np.where(t < 1.5, 450 * np.sin(np.pi * t / 1.5), 40.0)
                    * (t < 13))
    s = assess_impact(spike, 300.0)
    assert s.diagnosis == "first_peak" and s.colour in ("brown", "red")
    assert "gives HIC" in s.reason
    assert set(DIAGNOSES) == {"ok", "bottoming", "light_bottoming", "first_peak",
                              "stiff"}


def test_head_impact_units_and_direction(tmp_path):
    t = np.arange(0, 12.0, 0.1)                                # ms
    hf = HEADFORMS["adult"]
    d = impact_direction(hf)
    a = np.where(t > 1.0, 80.0, 0.0)                           # g along -d
    v = hf.velocity - np.cumsum(a) * 0.1 * G / 1000.0
    x = np.cumsum(v) * 0.1
    def shape(s):
        return s[:, None, None] * d[None, None, :]
    write_nodout(tmp_path / "nodout", t, [7], shape(x), shape(v),
                 -shape(a) * G / 1000.0)
    ms = head_impact(tmp_path, headform="adult", cfc=None)
    np.testing.assert_allclose(ms.acceleration, a, atol=1e-3)
    assert ms.contact_time == pytest.approx(1.025, abs=0.03)
    write_nodout(tmp_path / "run.nodout", t / 1000.0, [7], shape(x), shape(v) * 1000,
                 -shape(a) * G * 1000.0)                      # mm, s
    s = head_impact(tmp_path / "run.nodout", headform="adult", cfc=None,
                    unit_system="mm-s-t", node=7)
    np.testing.assert_allclose(s.time, t, atol=1e-6)
    np.testing.assert_allclose(s.acceleration, a, atol=1e-2)
    np.testing.assert_allclose(s.penetration, ms.penetration, atol=1e-3)
    with pytest.raises(FileNotFoundError):
        head_impact(tmp_path / "nothing_here" if (tmp_path / "x").mkdir() is None
                    else tmp_path)
    with pytest.raises(ValueError, match="Unknown unit_system"):
        head_impact(tmp_path, unit_system="inch")


def test_real_helmet_drop_nodout():
    """MIT data (tests/data/lsdyna/helmet): a helmeted Hybrid III head
    drop at 3.12 m/s; the study's own HIC is 195.24."""
    hf = Headform("Hybrid III head", 4.54, 165.0, 90.0, 3.12 * 3.6)
    imp = head_impact(DATA / "helmet" / "drop", direction=(0, 0, -1), headform=hf)
    assert imp.velocity[0] == pytest.approx(3.12)
    r = assess_impact(imp)
    assert r.hic == pytest.approx(195.24, rel=5e-3)
    assert r.colour == "green" and r.diagnosis in ("ok", "light_bottoming")
    assert 20 < r.penetration < 30
    out = read_nodout(DATA / "helmet" / "drop" / "nodout")
    assert imp.time[-1] == pytest.approx(out.time[-1], rel=1e-3)


# --- The synthetic bonnet: known truth ------------------------------------------


@pytest.fixture(scope="module")
def grids(tmp_path_factory):
    root = tmp_path_factory.mktemp("bonnet")
    out = {}
    for v in ("baseline", "lower_engine"):
        run = simulate_grid(bonnet_model(v))
        run.write(root / v)
        mesh = read_mesh(root / v / "bonnet.k")
        pts = read_impact_points(root / v / "impact_points.csv")
        hard = {mesh.part_name(p): mesh.points(p) for p in mesh.part_ids if p != 100}
        gaps = clearance({k: p.point for k, p in pts.items()}, hard,
                         {k: impact_direction(p.headform) for k, p in pts.items()},
                         surface=mesh.points(100))
        impacts = {k: head_impact(p.run, headform=p.headform)
                   for k, p in pts.items()}
        out[v] = (run, gaps, assess_grid(impacts, gaps))
    return out


def test_synthetic_files(grids):
    run, gaps, _ = grids["baseline"]
    assert len(run.keys) == 130 and set(VARIANTS) == {"baseline", "lower_engine",
                                                      "stiff_inner"}
    for k in run.keys:      # the mesh read back gives the model's own clearance
        assert gaps[k].distance == pytest.approx(run.clearances[k].distance,
                                                 abs=1e-2)
        assert gaps[k].part == run.clearances[k].part
    with pytest.raises(ValueError, match="Unknown variant"):
        bonnet_model("no_bonnet")


def test_bottoming_matches_the_truth(grids):
    run, _, grid = grids["baseline"]
    found = 0
    for k, p in grid.points.items():
        truth = run.truth[k]
        assert p.bottoming == math.isfinite(truth.bottoming_time), k
        if p.bottoming:
            found += 1
            assert p.bottoming_time == pytest.approx(truth.bottoming_time, abs=0.8)
            assert p.residual_speed == pytest.approx(truth.residual_speed, abs=1.0)
            assert p.part == truth.part
    assert found >= 40


def test_why_points_are_red(grids):
    _, _, grid = grids["baseline"]
    p = grid.points
    assert p[(2, 0)].diagnosis == "bottoming" and p[(2, 0)].part == "Intake plenum"
    assert "Intake plenum" in p[(2, 0)].reason and p[(2, 0)].colour == "red"
    assert p[(4, 5)].part == "Strut tower LH" and p[(4, 5)].diagnosis == "bottoming"
    assert p[(10, 6)].part == "Hinge LH" and p[(10, 6)].colour == "red"
    assert p[(1, 0)].diagnosis == "first_peak"                # heavy latch
    assert p[(1, -6)].diagnosis == "stiff" and not p[(1, -6)].bottoming   # wing edge
    assert p[(8, 0)].colour == "green" and p[(8, 0)].diagnosis == "ok"
    assert p[(2, 0)].hic_share_after > 0.5 and p[(2, 0)].extra_space > 10
    assert p[(5, 0)].margin > 0


def test_grid_outputs(grids):
    _, _, grid = grids["baseline"]
    colours = grid.colours()
    assert sum(colours.values()) == 130 and colours["red"] > 20
    lost = grid.lost_points()
    assert sum(lost.values()) == pytest.approx(130 - sum(p.points for p in
                                                         grid.points.values()))
    assert lost["bottoming"] > lost["stiff"] > 0
    score = grid.score()
    assert score.score == pytest.approx(
        headform_score({k: p.hic for k, p in grid.points.items()}).score)
    lines = grid.map().splitlines()
    assert len(lines) == 12 and lines[0].split()[1:] == [str(c) for c in range(-6, 7)]
    assert "R*" in grid.map() and "^" in lines[1]
    assert grid.table(top=5).count("\n") == 6
    assert "Head score" in grid.summary() and "bottoming:" in grid.summary()


def test_clearance_map_and_csv(grids, tmp_path):
    run, gaps, grid = grids["baseline"]
    text = clearance_map(gaps, needed=86)
    lines = text.splitlines()
    assert len(lines) == 12 and "less than 86 mm" in lines[-1]
    row10 = lines[10].split()
    assert row10[0] == "10" and row10[1] == "0!"          # the hinge corner
    assert "    -" in lines[8]                            # nothing under row 8
    assert "surface normal" in clearance_map(gaps, normal=True)
    with pytest.raises(ValueError, match="row, column"):
        clearance_map({0: gaps[(1, 0)]})
    path = grid.to_csv(tmp_path / "grid.csv")
    rows = path.read_text().splitlines()
    assert len(rows) == 131 and rows[0].startswith("point,hic,colour")
    assert any("Intake plenum" in r for r in rows)


def test_lower_engine_fixes_the_plenum_points(grids):
    base, low = grids["baseline"][2], grids["lower_engine"][2]
    cmp = compare_grids(base, low, names=("baseline", "lower_engine"))
    assert cmp.score[1] > cmp.score[0]
    assert cmp.grid_points[1] > cmp.grid_points[0]
    improved = {k for k, *_ in cmp.changes}
    assert (3, 0) in improved and not cmp.new_bottoming
    assert all(low.points[k].hic <= base.points[k].hic + 1e-6 for k in base.points)
    assert "lower_engine against baseline" in cmp.summary()
