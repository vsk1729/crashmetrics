import math

import numpy as np
import pytest

from crashmetrics.whiplash import (
    NKM_INTERCEPTS,
    WHIPLASH_CAPPING,
    WHIPLASH_LIMITS,
    RearSeat,
    front_geometry_score,
    nic,
    nkm,
    rear_backset_limit,
    rear_seat_score,
    score_front_seat,
    score_rear_seats,
    score_whiplash,
    score_whiplash_pulse,
)

T = np.linspace(0.0, 0.1, 1001)


# --- criteria ---------------------------------------------------------------


def test_nic_closed_form():
    # constant relative acceleration A: v_rel = A t, NIC = 0.2 A + (A t)^2
    a = 10.0
    value = nic(T, np.full_like(T, a), np.zeros_like(T))
    assert value == pytest.approx(0.2 * a + (a * 0.1) ** 2, rel=1e-6)
    early = nic(T, np.full_like(T, a), np.zeros_like(T), t_end=0.05)
    assert early == pytest.approx(0.2 * a + (a * 0.05) ** 2, rel=1e-6)
    in_g = nic(T, np.full_like(T, a / 9.81), np.zeros_like(T), units="g")
    assert in_g == pytest.approx(value, rel=1e-9)
    with pytest.raises(ValueError, match="units"):
        nic(T, T, T, units="km/h")


def test_nkm_modes_and_intercepts():
    assert NKM_INTERCEPTS == {"flexion": 88.1, "extension": -47.5,
                              "shear_anterior": 845.0, "shear_posterior": -845.0}
    zero = np.zeros_like(T)
    flex = nkm(T, zero, np.full_like(T, 44.05))
    assert flex.value == pytest.approx(0.5) and flex.mode == "nfa"
    ext_post = nkm(T, np.full_like(T, -422.5), zero - 0.01778 * 422.5 - 23.75)
    # M_OC = My - D Fx = -23.75 N m (extension); Fx posterior
    assert ext_post.value == pytest.approx(0.5 + 0.5) and ext_post.mode == "nep"
    shear = nkm(T, np.full_like(T, 845.0), 0.01778 * np.full_like(T, 845.0))
    assert shear.value == pytest.approx(1.0) and shear.mode == "nfa"


# --- dynamic scoring --------------------------------------------------------


def test_limits_are_the_protocol_values():
    assert WHIPLASH_LIMITS == {
        "medium": {"nic": (11.0, 24.0), "upper_neck_fx": (30.0, 190.0),
                   "upper_neck_fz": (360.0, 750.0)},
        "high": {"nic": (13.0, 23.0), "upper_neck_fx": (30.0, 210.0),
                 "upper_neck_fz": (470.0, 770.0)},
    }
    assert WHIPLASH_CAPPING["medium"]["nic"] == 27.0
    assert WHIPLASH_CAPPING["high"]["nic"] == 25.5
    assert WHIPLASH_CAPPING["high"]["nkm"] == 0.78
    assert "nkm" not in WHIPLASH_CAPPING["medium"]
    assert WHIPLASH_CAPPING["high"]["seatback_deflection"] == 32.0


def test_pulse_sliding_scales():
    best = score_whiplash_pulse("medium", {"nic": 9.0, "upper_neck_fx": 20.0,
                                           "upper_neck_fz": 300.0})
    assert best.points == 1.5 and best.capped == ()
    mid = score_whiplash_pulse("medium", {"nic": 17.5, "upper_neck_fx": 110.0,
                                          "upper_neck_fz": 555.0})
    assert mid.criteria == pytest.approx({"nic": 0.25, "upper_neck_fx": 0.25,
                                          "upper_neck_fz": 0.25})
    worst = score_whiplash_pulse("high", {"nic": 23.0, "upper_neck_fx": 210.0,
                                          "upper_neck_fz": 770.0})
    assert worst.points == 0.0 and worst.capped == ()


@pytest.mark.parametrize("pulse, extra, reason", [
    ("medium", {"nic": 27.0}, "nic"),
    ("high", {"nkm": 0.78}, "nkm"),
    ("high", {"rebound_velocity": 6.0}, "rebound_velocity"),
    ("medium", {"upper_neck_fx_negative": -360.0}, "upper_neck_fx_negative"),
    ("medium", {"upper_neck_my_extension": -30.0}, "upper_neck_my_extension"),
    ("high", {"lower_neck_fx": -360.0}, "lower_neck_fx"),
    ("high", {"seatback_deflection": 32.0}, "seatback_deflection"),
    ("high", {"t1": 17.8, "t_hrc_start": 92.0}, "t1 and t_hrc_start"),
])
def test_capping_zeroes_the_pulse(pulse, extra, reason):
    values = {"nic": 9.0, "upper_neck_fx": 20.0, "upper_neck_fz": 300.0, **extra}
    r = score_whiplash_pulse(pulse, values)
    assert r.points == 0.0 and reason in r.capped


def test_t1_or_thrc_alone_does_not_cap():
    values = {"nic": 9.0, "upper_neck_fx": 20.0, "upper_neck_fz": 300.0}
    assert score_whiplash_pulse("medium", {**values, "t1": 20.0,
                                           "t_hrc_start": 80.0}).points == 1.5
    assert score_whiplash_pulse("medium", {**values, "t1": 10.0,
                                           "t_hrc_start": 100.0}).points == 1.5


def test_pulse_errors():
    with pytest.raises(ValueError, match="pulse"):
        score_whiplash_pulse("low", {})
    with pytest.raises(ValueError, match="Missing"):
        score_whiplash_pulse("high", {"nic": 1.0, "upper_neck_fx": 1.0})
    with pytest.raises(ValueError, match="Unknown"):
        score_whiplash_pulse("medium", {"nic": 1.0, "upper_neck_fx": 1.0,
                                        "upper_neck_fz": 1.0, "femur": 0.5})
    # Nkm is a high pulse item: accepted and ignored for the medium pulse
    ok = score_whiplash_pulse("medium", {"nic": 9.0, "upper_neck_fx": 20.0,
                                         "upper_neck_fz": 300.0, "nkm": 0.9})
    assert ok.points == 1.5


# --- geometry and front seat ------------------------------------------------


@pytest.mark.parametrize("height, backset, score", [
    (830.0, 30.0, 1.0), (825.0, 44.9, 1.0), (807.5, 30.0, 0.5), (790.0, 30.0, 0.0),
    (830.0, 45.0, 0.0), (807.5, 50.0, 0.0),
])
def test_front_geometry(height, backset, score):
    assert front_geometry_score(height, backset) == pytest.approx(score)


def pulses(medium=1.5, high=1.5):
    good = {"nic": 9.0, "upper_neck_fx": 20.0, "upper_neck_fz": 300.0}
    m = score_whiplash_pulse("medium", good if medium == 1.5 else
                             {**good, "nic": 17.5, "upper_neck_fx": 110.0,
                              "upper_neck_fz": 555.0})
    h = score_whiplash_pulse("high", good if high == 1.5 else
                             {**good, "nic": 23.0, "upper_neck_fx": 210.0,
                              "upper_neck_fz": 770.0})
    return m, h


def test_front_seat_score():
    m, h = pulses()
    full = score_front_seat(m, h, 830.0, 30.0)
    assert full.points == 4.0 and full.geometry == 1.0 and full.dynamic == 3.0
    # test position 0.5 + lowest/rearmost 0.25 for one of two seats
    part = score_front_seat(m, h, 807.5, 30.0,
                            lowest_rearmost=[(795.0, 65.0), (780.0, 65.0)])
    parts = (part.test_position, part.lowest_rearmost, part.geometry)
    assert parts == (0.5, 0.25, 0.75)
    capped_total = score_front_seat(m, h, 830.0, 30.0,
                                    lowest_rearmost=[(800.0, 60.0), (800.0, 60.0)])
    assert capped_total.geometry == 1.0
    no_structure = score_front_seat(m, h, 830.0, 30.0,
                                    head_restraint_structure_ok=False)
    assert no_structure.geometry == 0.0
    loaded = score_front_seat(m, h, 830.0, 30.0, dummy_loading=True)
    assert loaded.points == 3.0


def test_automatic_head_restraint_credit_needs_dynamic_above_1_5():
    m, h = pulses(medium=0.75, high=0.0)          # raw dynamic 0.75
    r = score_front_seat(m, h, 800.0, 30.0, lowest_rearmost=[(800.0, 60.0)],
                         front_seats=1, automatic_head_restraint=True)
    assert r.lowest_rearmost == 0.0 and "1.50" in r.notes[0]
    m2, h2 = pulses()
    ok = score_front_seat(m2, h2, 800.0, 30.0, lowest_rearmost=[(800.0, 60.0)],
                          front_seats=1, automatic_head_restraint=True)
    assert ok.lowest_rearmost == 0.5


# --- rear seats and total ---------------------------------------------------


def test_rear_backset_limit():
    assert rear_backset_limit(25.0) == pytest.approx(7.128 * 25 + 153)


def test_rear_seat_points():
    lim = rear_backset_limit(25.0)
    full = RearSeat(730.0, 780.0, lim - 1, lim - 1, 25.0, non_use_position=True)
    assert rear_seat_score(full) == pytest.approx(1.0)
    mid_only = RearSeat(730.0, 780.0, lim, lim + 10, 25.0)
    assert rear_seat_score(mid_only) == pytest.approx(0.375 + 0.25)
    low = RearSeat(700.0, 780.0, 100.0, 100.0, 25.0, non_use_position=True)
    assert rear_seat_score(low) == 0.0                 # no height: nothing
    roof = RearSeat(700.0, 740.0, lim, lim, 25.0, roofline_gap=45.0)
    assert rear_seat_score(roof) == pytest.approx(0.75)
    mean = (1 + 0.625) / 2
    assert score_rear_seats([full, mid_only]) == pytest.approx(mean, abs=1e-3)
    assert score_rear_seats([full, full], centre_seat_r17=False) == 0.0


def test_total_and_summary():
    m, h = pulses()
    lim = rear_backset_limit(25.0)
    seat = RearSeat(730.0, 780.0, lim, lim, 25.0, non_use_position=True)
    total = score_whiplash(score_front_seat(m, h, 830.0, 30.0),
                           score_rear_seats([seat, seat]))
    assert total.points == 5.0
    assert "Rear impact (whiplash): 5.000 / 5" in total.summary()
    with pytest.raises(ValueError, match="rear"):
        score_whiplash(score_front_seat(m, h, 830.0, 30.0), 1.5)
    assert math.isfinite(total.front.points)
