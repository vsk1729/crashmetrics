"""Tests for crashmetrics.synthetic (the toy frontal crash model)."""

import numpy as np
import pytest

from crashmetrics.lsdyna import read_matsum
from crashmetrics.lsdyna_ascii import detect_kind, read_secforc
from crashmetrics.synthetic import (
    VARIANTS,
    CrushElement,
    frontal_model,
    simulate,
    write_matsum,
    write_secforc,
)


@pytest.fixture(scope="module")
def runs():
    return {v: simulate(frontal_model(v)) for v in VARIANTS}


def test_physics(runs):
    r = runs["baseline"]
    assert r.notes == ()                                    # no path bottoms out
    assert r.velocity[0] == pytest.approx(56.0 / 3.6)
    assert 400 < r.displacement.max() < 480                 # mm of crush
    assert -2.5 < r.velocity[-1] < 0                        # small rebound
    assert 40 < r.deceleration.max() < 60                   # g
    # Energy balance: kinetic + internal + hourglass stays the initial energy.
    p = r.part_energies()
    total = p.internal.sum(1) + p.kinetic.sum(1) + p.hourglass.sum(1)
    e0 = 0.5 * 1500.0 * (56.0 / 3.6) ** 2
    assert total[0] == pytest.approx(e0)
    assert np.max(np.abs(total / e0 - 1)) < 2e-3
    # In a chain the weakest part crushes first.
    weak = runs["weak_front_rail_lh"]

    def onset(run, path, pid):
        e = run.plastic_energy[(path, pid)]
        return run.time[np.argmax(e > 0.1 * e[-1])]

    assert onset(weak, "main LH", 120) < onset(weak, "main LH", 110)
    assert onset(weak, "main RH", 111) < onset(weak, "main RH", 121)
    assert runs["no_lower_path"].crush[("main LH", 130)][-1] > 50     # rear rail


def test_elements_and_variants():
    e = CrushElement(1, "box", 100.0, 150.0, 1.5, 6.0, 30.0, 0.2)
    assert e.strength(0.0) == pytest.approx(150.0)
    assert e.strength(3.0) == pytest.approx(125.0)
    assert e.strength(6.0 + 7.5) == pytest.approx(120.0)            # wave crest
    car = frontal_model()
    assert car.replace_element(110, "main LH", mean_force=10.0).paths[0].elements[
        1].mean_force == 10.0
    with pytest.raises(ValueError, match="No part"):
        car.replace_element(999, mean_force=1.0)
    with pytest.raises(ValueError, match="Unknown paths"):
        car.without_paths("side")
    with pytest.raises(ValueError, match="Unknown variant"):
        frontal_model("convertible")
    with pytest.raises(ValueError, match="no load paths"):
        simulate(car.without_paths(*[p.name for p in car.paths]))
    assert frontal_model(mass=1200.0, speed=50.0).mass == 1200.0


def test_files_round_trip(runs, tmp_path):
    r = runs["baseline"]
    m, s = r.write(tmp_path, matsum_interval=1.0, secforc_interval=0.5)
    p = read_matsum(m)
    ref = r.part_energies(p.time)
    assert list(p.part_ids) == sorted(p.part_ids)
    assert p.part_names[110] == "Crash box LH"
    assert np.max(np.abs(p.internal - ref.internal)) < 1e-4 * np.max(ref.internal)
    sec = read_secforc(s)
    assert detect_kind(s) == "secforc"
    assert sec.ids == tuple(sorted(sec.ids)) and sec.names[21] == "Upper rail LH"
    out = r.section_output(sec.time)
    np.testing.assert_allclose(sec.data["x_force"], out.data["x_force"], atol=0.01)
    assert "not LS-DYNA output" in m.read_text().splitlines()[1]
    assert "-0.0000E+00" not in s.read_text()
    # Sections further back carry slightly less (mass ahead of them).
    f = {sid: np.max(np.abs(out.data["x_force"][:, out.ids.index(sid)]))
         for sid in (11, 13, 15)}
    assert f[11] > f[13] > f[15]


def test_writer_errors(tmp_path):
    with pytest.raises(ValueError, match="shape"):
        write_matsum(tmp_path / "m", [0.0, 1.0], [1], {}, np.zeros((3, 1)))
    run = simulate(frontal_model(), end_time=5.0)
    out = run.section_output()
    out.data.pop("y_force")
    with pytest.raises(ValueError, match="Missing channels"):
        write_secforc(tmp_path / "s", out)
