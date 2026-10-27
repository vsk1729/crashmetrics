import numpy as np
import pytest

from crashmetrics.pedestrian.flexpli import (
    FLEXPLI_LIMITS,
    FlexPliPointScore,
    assessment_interval,
    flexpli_peaks,
    flexpli_point_score,
    flexpli_score,
)

T = np.arange(0, 501) * 1e-4  # 0 to 50 ms


def test_limits_from_euro_ncap_v1005():
    assert FLEXPLI_LIMITS == {"tibia_moment": (282.0, 340.0),
                              "mcl_elongation": (19.0, 22.0),
                              "acl_pcl_elongation": (10.0, 10.0)}


def test_point_score_hand_calculation():
    # tibia 0.5 * (340 - 311) / 58 = 0.25; knee 0.5 * (22 - 20.5) / 3 = 0.25
    score = flexpli_point_score(311.0, 20.5, 5.0, 6.0)
    assert (score.tibia, score.knee, score.total) == pytest.approx((0.25, 0.25, 0.5))
    # ACL or PCL at 10 mm: the knee scores 0 (Euro NCAP worked example)
    assert flexpli_point_score(200.0, 15.0, 10.0, 3.0).knee == 0.0
    assert flexpli_point_score(-200.0, -15.0, 3.0, -9.9).total == 1.0


def test_grid_score_with_symmetry():
    grid = ["L+2", "L+1", "L0", "L-1", "L-2"]
    tests = {"L0": (200.0, 15.0, 3.0, 3.0),        # 1.0
             "L+1": (311.0, 20.5, 5.0, 6.0),       # 0.5
             "L+2": FlexPliPointScore(0.25, 0.0, 0.25)}
    result = flexpli_score(grid, tests)
    assert result.scores == {"L+2": 0.25, "L+1": 0.5, "L0": 1.0, "L-1": 0.5,
                             "L-2": 0.25}
    assert result.sources["L-1"] == "symmetry of 'L+1'"
    assert result.points == pytest.approx(2.5 / 5 * 6.0)


def test_assessment_interval_last_zero_crossing():
    femur = 200.0 * np.sin(np.pi * T / 0.02)
    tibia = 300.0 * np.sin(np.pi * T / 0.03)
    start, end = assessment_interval(T, [femur, tibia])
    assert start == 0.0
    assert end == pytest.approx(0.03, abs=2e-4)
    # A segment that never exceeds 15 N m does not limit the interval.
    small = 10.0 * np.sin(np.pi * T / 0.045)
    assert assessment_interval(T, [femur, tibia, small])[1] == end


def test_assessment_interval_shifts_down_without_crossing():
    # This segment peaks at 10 ms and settles at 40 N m without crossing
    # zero: all curves are shifted down by 40 N m; it then "crosses" at 30 ms.
    stuck = np.where(T < 0.01, 100.0 * np.sin(np.pi * T / 0.02),
                     np.maximum(100.0 - 3000.0 * (T - 0.01), 40.0))
    femur = 200.0 * np.sin(np.pi * T / 0.02)
    _, end = assessment_interval(T, [femur, stuck])
    assert end == pytest.approx(0.03, abs=2e-4)


def test_peaks_within_interval():
    tibia = [300.0 * np.sin(np.pi * T / 0.03), 250.0 * np.sin(np.pi * T / 0.03)]
    # 30 mm after 40 ms, outside the interval: ignored
    mcl = np.where(T > 0.04, 30.0, 18.0 * np.sin(np.pi * T / 0.03))
    acl = np.full_like(T, 2.0)
    pcl = -5.0 * np.sin(np.pi * T / 0.03)
    peaks = flexpli_peaks(T, tibia, mcl, acl, pcl)
    assert peaks.interval[1] == pytest.approx(0.03, abs=2e-4)
    assert peaks.tibia_moment == pytest.approx(300.0, rel=1e-4)
    assert peaks.tibia_segment == 0
    assert peaks.mcl == pytest.approx(18.0, rel=1e-4)
    assert peaks.pcl == pytest.approx(5.0, rel=1e-4)
    fixed = flexpli_peaks(T, tibia, mcl, acl, pcl, interval=(0.0, 0.05))
    assert fixed.mcl == pytest.approx(30.0)


def test_assessment_interval_errors():
    with pytest.raises(ValueError, match="15 N m"):
        assessment_interval(T, [np.zeros_like(T)])
    with pytest.raises(ValueError, match="after the end"):
        assessment_interval(T, [T], t_contact=1.0)
