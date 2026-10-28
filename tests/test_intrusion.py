import math

import numpy as np
import pytest

from crashmetrics.features import flatten
from crashmetrics.intrusion import intrusion, intrusions, node_distance, node_track

N = 61
T = np.linspace(0.0, 0.12, N)                       # s


def rot_y(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def rot_z(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


# Vehicle axes: x forward, y left, z up (mm). Rear structure reference
# points and a footwell point 1.5 m in front of them.
REF0 = np.array([[0.0, -500.0, 0.0], [0.0, 500.0, 0.0],
                 [-300.0, 0.0, 400.0], [100.0, 0.0, 50.0]])
P0 = np.array([1500.0, 300.0, 200.0])
FRACTION = np.clip(T / 0.08, 0.0, 1.0)
# Local deformation: 120 mm rearward at 80 ms, springing back to 100 mm;
# 40 mm upward; 10 mm lateral.
LOCAL = np.column_stack([
    -120.0 * np.sin(np.pi / 2 * FRACTION) + 20.0 * np.clip((T - 0.08) / 0.04, 0, 1),
    -10.0 * FRACTION,
    40.0 * FRACTION,
])


def vehicle_motion(points0, local=None):
    """Move points with the vehicle: 650 mm forward, 4 deg pitch, 2 deg yaw."""
    out = []
    for i in range(N):
        r = rot_z(math.radians(2) * FRACTION[i]) @ rot_y(math.radians(4) * FRACTION[i])
        shift = np.array([650.0, 15.0, -20.0]) * FRACTION[i]
        p = points0 + (0 if local is None else local[i])
        out.append(r @ p + shift)
    return np.array(out)


POINT = vehicle_motion(P0, LOCAL)
REF = np.array([vehicle_motion(r) for r in REF0])            # (4, N, 3)


# --- reference frame: translation and rotation removed --------------------


def test_frame_reference_recovers_local_deformation_exactly():
    r = intrusion(POINT, REF, time=T, direction="-x")
    assert r.reference == "frame"
    np.testing.assert_allclose(r.displacement, LOCAL, atol=1e-9)
    assert r.reference_fit_error == pytest.approx(0.0, abs=1e-9)
    assert r.x_dynamic == pytest.approx(-120.0)
    assert r.t_dynamic_ms == pytest.approx(80.0)
    assert r.x_static == pytest.approx(-100.0)
    assert r.y_static == pytest.approx(-10.0)
    assert r.z_static == pytest.approx(40.0)
    assert r.along_dynamic == pytest.approx(120.0)       # rearward
    assert r.along_static == pytest.approx(100.0)
    assert r.t_along_ms == pytest.approx(80.0)
    assert r.resultant_static == pytest.approx(math.sqrt(100**2 + 10**2 + 40**2))


def test_frame_reference_accepts_a_list_of_nodes_and_three_nodes():
    three = intrusion(POINT, [REF[0], REF[1], REF[2]], time=T)
    np.testing.assert_allclose(three.displacement, LOCAL, atol=1e-9)


def test_single_node_reference_removes_translation_only():
    r = intrusion(POINT, REF[3], time=T)
    assert r.reference == "node"
    # pure translation of the vehicle: exact
    moved = np.array([P0 + LOCAL[i] + [700.0 * FRACTION[i], 0, 0] for i in range(N)])
    ref = np.array([REF0[3] + [700.0 * FRACTION[i], 0, 0] for i in range(N)])
    np.testing.assert_allclose(intrusion(moved, ref).displacement, LOCAL, atol=1e-9)
    # with pitch and yaw the rotation is not removed: a large error 1.4 m away
    assert abs(r.z_static - 40.0) > 50.0


def test_global_reference_includes_vehicle_motion():
    r = intrusion(POINT, time=T)
    assert r.reference == "global"
    assert r.x_static > 400.0              # mostly the vehicle moving forward


def test_static_before_after_measurement_with_noisy_reference_points():
    # 0.1 mm measurement noise on the reference points. Noise is amplified
    # by the lever arm (the point is 1.5 m from points spread over ~0.4 m).
    rng = np.random.default_rng(3)
    before_ref = REF0 + rng.normal(0, 0.1, REF0.shape)
    after_ref = (rot_y(math.radians(1.5)) @ REF0.T).T + [800.0, 30.0, -5.0]
    after_ref = after_ref + rng.normal(0, 0.1, REF0.shape)
    moved = rot_y(math.radians(1.5)) @ (P0 + [-95.0, 0.0, 30.0])
    after_point = moved + [800.0, 30.0, -5.0]
    point = np.array([P0, after_point])
    ref = np.stack([before_ref, after_ref], axis=1)            # (4, 2, 3)
    r = intrusion(point, ref, direction="-x")
    assert r.along_static == pytest.approx(95.0, abs=1.5)
    assert r.z_static == pytest.approx(30.0, abs=1.5)
    assert 0.01 < r.reference_fit_error < 0.5                  # measurement noise
    assert math.isnan(r.t_dynamic_ms)


def test_deforming_reference_shows_in_the_fit_error():
    bent = REF.copy()
    bent[3, :, 2] += 25.0 * FRACTION                           # one point moves 25 mm
    assert intrusion(POINT, bent, time=T).reference_fit_error > 5.0


def test_static_window_averages_the_end():
    disp = np.zeros((N, 3))
    disp[:, 0] = -100.0 * FRACTION                 # settles at -100 after 80 ms
    disp[-6:, 0] += [3.0, -3.0, 3.0, -3.0, 3.0, -3.0]   # springback wobble
    r = intrusion(P0 + disp, time=T, static_window_ms=10.0)   # last 6 samples
    assert r.x_static == pytest.approx(-100.0)
    assert intrusion(P0 + disp, time=T).x_static == pytest.approx(-103.0)


def test_direction_vectors_and_strings():
    p = P0 + LOCAL
    assert intrusion(p, direction="z").along_static == pytest.approx(40.0)
    assert intrusion(p, direction=(0, 0, 2)).along_static == pytest.approx(40.0)
    diag = intrusion(p, direction=(-1, 0, 1)).along_static
    assert diag == pytest.approx((100 + 40) / math.sqrt(2))
    assert math.isnan(intrusion(p).along_dynamic)


@pytest.mark.parametrize("bad", ["w", "--", (0, 0, 0), (1, 2)])
def test_bad_direction(bad):
    with pytest.raises(ValueError, match="direction"):
        intrusion(P0 + LOCAL, direction=bad)


def test_input_validation():
    with pytest.raises(ValueError, match="shape"):
        intrusion(np.zeros((5, 2)))
    with pytest.raises(ValueError, match="at least three"):
        intrusion(POINT, REF[:2])
    with pytest.raises(ValueError, match="one line"):
        line = np.stack([POINT, POINT + 10.0, POINT + 20.0])
        intrusion(POINT, line)
    with pytest.raises(ValueError, match="same rows"):
        intrusion(POINT, REF[0][:10])
    with pytest.raises(ValueError, match="time"):
        intrusion(POINT, time=T[:5])
    with pytest.raises(ValueError, match="needs the time"):
        intrusion(POINT, static_window_ms=5.0)


# --- many points, distances, helpers ----------------------------------------


def test_intrusions_for_many_points_and_flatten():
    column = vehicle_motion(P0 + [-300.0, 0.0, 300.0], LOCAL)
    pts = {"brake_pedal": POINT, "steering_column": column}
    out = intrusions(pts, REF, time=T,
                     direction={"brake_pedal": "-x", "steering_column": "z"})
    assert out["brake_pedal"].along_static == pytest.approx(100.0)
    assert out["steering_column"].along_static == pytest.approx(40.0)
    flat = flatten(out)
    assert flat["brake_pedal.along_dynamic"] == pytest.approx(120.0)
    assert "brake_pedal.displacement" not in flat          # arrays are left out


def test_node_distance_closing_and_remaining_space():
    seat = vehicle_motion(np.array([700.0, 300.0, 300.0]))
    wheel = vehicle_motion(np.array([1200.0, 300.0, 600.0]), LOCAL)
    d = node_distance(wheel, seat, time=T)
    expected = np.linalg.norm(np.array([500.0, 0.0, 300.0]) + LOCAL, axis=1)
    assert d.initial == pytest.approx(expected[0])
    assert d.minimum == pytest.approx(expected.min())
    assert d.closing_dynamic == pytest.approx(expected[0] - expected.min())
    assert d.final == pytest.approx(np.linalg.norm([400.0, -10.0, 340.0]))
    assert d.closing_static == pytest.approx(expected[0] - d.final)
    assert d.t_minimum_ms == pytest.approx(T[np.argmin(expected)] * 1000.0)
    assert d.opening_dynamic >= 0.0
    # rigid motion alone does not change a distance
    rigid = node_distance(vehicle_motion(P0), seat)
    assert rigid.closing_dynamic == pytest.approx(0.0, abs=1e-9)


def test_node_distance_validation():
    with pytest.raises(ValueError, match="same shape"):
        node_distance(POINT, POINT[:5])


def test_node_track():
    xyz = node_track([1, 2], [3, 4], [5, 6])
    np.testing.assert_array_equal(xyz, [[1, 3, 5], [2, 4, 6]])
    moved = node_track([0, 1], [0, 2], [0, 3], initial=(10, 20, 30))
    np.testing.assert_array_equal(moved, [[10, 20, 30], [11, 22, 33]])
    with pytest.raises(ValueError, match="initial"):
        node_track([0], [0], [0], initial=(1, 2))
