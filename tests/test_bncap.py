import math

import numpy as np
import pytest

from crashmetrics.bncap import (
    AOP_STAR_THRESHOLDS,
    FEMUR_CURVES,
    FRONTAL_LIMITS,
    NECK_SHEAR_CURVES,
    NECK_TENSION_CURVES,
    SIDE_LIMITS,
    FrontalOccupant,
    SideOccupant,
    a_pillar_modifier,
    aop_rating,
    backplate_modifier,
    colour,
    cop_stars,
    curve_points,
    pedal_blocking_modifier,
    pedal_upward_modifier,
    pole_test_passed,
    score_frontal,
    score_side,
    sliding_points,
    steering_column_modifier,
    t12_modifier,
)

T = np.arange(1001) * 1e-4  # 0 to 100 ms


def plateau(level, start_ms, end_ms):
    ms = np.round(T * 1000.0, 6)
    return T, np.where((ms >= start_ms) & (ms <= end_ms), level, 0.0)


ZERO = (T, np.zeros_like(T))

# --- Limits and points ---------------------------------------------------------


def test_limits_from_ais_197():
    assert FRONTAL_LIMITS["hic15"] == (500.0, 700.0)
    assert FRONTAL_LIMITS["head_a3ms"] == (72.0, 88.0)
    assert FRONTAL_LIMITS["chest_compression"] == (22.0, 42.0)
    assert FRONTAL_LIMITS["tibia_force"] == (2000.0, 8000.0)
    assert FRONTAL_LIMITS["pedal_rearward"] == (100.0, 200.0)
    assert SIDE_LIMITS["rib_vc"] == (0.32, 1.0)
    assert SIDE_LIMITS["abdominal_force"] == (1000.0, 2500.0)
    assert SIDE_LIMITS["pubic_force"] == (3000.0, 6000.0)
    assert NECK_TENSION_CURVES[1] == ((0.0, 3300.0), (35.0, 2900.0), (60.0, 1100.0))
    assert NECK_SHEAR_CURVES[0][1:3] == ((25.0, 1200.0), (35.0, 1200.0))
    assert FEMUR_CURVES[1] == ((0.0, 9070.0), (10.0, 7560.0))
    assert AOP_STAR_THRESHOLDS == ((5, 27.0), (4, 22.0), (3, 16.0), (2, 10.0),
                                   (1, 4.0))


def test_sliding_points_and_colours():
    assert sliding_points(600.0, 500.0, 700.0) == pytest.approx(2.0)
    assert sliding_points(450.0, 500.0, 700.0) == 4.0
    assert sliding_points(700.0, 500.0, 700.0) == 0.0
    assert [colour(p) for p in (4.0, 3.999, 2.67, 2.669, 1.33, 1.329, 0.001, 0.0)] \
        == ["green", "yellow", "yellow", "orange", "orange", "brown", "brown", "red"]


# --- Exceedance curve scoring --------------------------------------------------


def test_curve_points_neck_tension():
    # 2.5 kN for 40 ms: higher curve 2.06 kN, lower curve 2.54 kN at 40 ms.
    result = curve_points(*plateau(2500.0, 10.0, 50.0), NECK_TENSION_CURVES)
    assert result.points == pytest.approx(4 * (2540 - 2500) / (2540 - 2060))
    assert result.duration_ms == pytest.approx(40.0)
    assert not result.exceeds_lower


def test_curve_points_femur_and_shear():
    # Femur -5 kN for 5 ms: lower curve 8.315 kN at 5 ms.
    femur = curve_points(*plateau(-5000.0, 10.0, 15.0), FEMUR_CURVES,
                         direction="negative")
    assert femur.points == pytest.approx(4 * (8315 - 5000) / (8315 - 3800))
    # Shear -2 kN for 30 ms is above the 1.5 kN lower curve: 0 and capping.
    shear = curve_points(*plateau(-2000.0, 10.0, 40.0), NECK_SHEAR_CURVES,
                         direction="absolute")
    assert shear.points == 0.0 and shear.exceeds_lower
    assert curve_points(*ZERO, NECK_SHEAR_CURVES).points == 4.0


# --- Modifiers -----------------------------------------------------------------


def test_modifier_helpers():
    assert steering_column_modifier(rearward=100.0) == pytest.approx(0.5)
    assert steering_column_modifier(rearward=50.0, upward=88.0) == 1.0
    assert a_pillar_modifier(150.0) == pytest.approx(1.0)
    assert a_pillar_modifier(250.0) == 2.0
    assert pedal_upward_modifier(80.0) == pytest.approx(0.5)
    assert pedal_blocking_modifier(112.5) == pytest.approx(0.5)
    assert backplate_modifier(-2500.0) == pytest.approx(1.0)
    assert t12_modifier(1750.0, 100.0) == pytest.approx(1.0)
    assert t12_modifier(1000.0, -190.0) == pytest.approx(1.6)


# --- Hand-calculated frontal + side + rating ------------------------------------


def _driver(**changes):
    values = dict(
        hic15=600.0, head_a3ms=60.0,                          # head 2.0
        neck_shear=ZERO, neck_tension=plateau(2500.0, 10.0, 50.0),  # 0.333
        neck_extension=30.0,
        chest_compression=32.0, viscous_criterion=0.6,        # chest 2.0
        femur=(plateau(-5000.0, 10.0, 15.0), ZERO),           # 2.937 / 4
        knee_displacement=(3.0, 10.5),                        # 4 / 2.0
        tibia_index=(0.85, 0.3), tibia_force=(1000.0, 5000.0),  # 2.0 / 2.0
        pedal_rearward=150.0,                                 # 2.0
        modifiers={"chest": a_pillar_modifier(150.0)},        # chest 2 - 1
    )
    values.update(changes)
    return FrontalOccupant(**values)


def _passenger():
    return FrontalOccupant(
        neck_shear=ZERO, neck_tension=ZERO, neck_extension=10.0,
        chest_compression=27.0, viscous_criterion=0.3,        # chest 3.0
        femur=(ZERO, ZERO), knee_displacement=(1.0, 1.0),
        tibia_index=(0.2, 0.2), tibia_force=(500.0, 500.0),
        hard_contact=False,                                   # head 4
    )


def _side(**changes):
    values = dict(hic15=400.0, head_a3ms=60.0,                # head 4
                  rib_deflection=32.0, rib_vc=0.66,           # chest 2.0
                  abdominal_force=1500.0, pubic_force=3000.0,  # 2.667 / 4
                  modifiers={"chest": backplate_modifier(2500.0)})  # -1
    values.update(changes)
    return SideOccupant(**values)


def test_frontal_hand_calculation():
    result = score_frontal(_driver(), _passenger(), door_openings=1)
    drv = result.regions["driver"]
    assert drv["head"].points == pytest.approx(2.0)
    assert drv["neck"].points == pytest.approx(0.333)
    assert drv["neck"].governing == "neck_tension"
    assert drv["chest"].raw_points == pytest.approx(2.0)
    assert drv["chest"].points == pytest.approx(1.0)
    assert drv["knee_left"].points == pytest.approx(2.937)
    assert result.regions["passenger"]["head"].points == 4.0
    assert "foot" not in result.regions["passenger"]
    assert result.groups == pytest.approx({"head_neck": 0.333, "chest": 1.0,
                                           "knee_femur_pelvis": 2.0,
                                           "leg_foot": 2.0})
    assert result.points == pytest.approx(5.333 - 1.0)
    assert not result.capped and not result.critical_zero


def test_side_hand_calculation():
    result = score_side(_side())
    assert result.groups == pytest.approx({"head": 4.0, "chest": 1.0,
                                           "abdomen": 2.667, "pelvis": 4.0})
    assert result.points == pytest.approx(11.667)


def test_rating_with_balance_rule():
    rating = aop_rating(score_frontal(_driver(), _passenger(), door_openings=1),
                        score_side(_side()))
    # 16.000 points = 3 stars, but front and side differ by 7.334 / 16 = 46 %
    assert rating.points == pytest.approx(16.0)
    assert rating.stars == 2
    assert rating.reasons == ("front / side difference above 35 %",)


def test_capping_and_critical_zero():
    capped_side = score_side(_side(rib_deflection=43.0))
    assert capped_side.capped and capped_side.points == 0.0
    frontal = score_frontal(_driver(), _passenger())
    assert aop_rating(frontal, capped_side).stars == 0

    zero_chest = score_frontal(_driver(modifiers={"chest": 3.0}), _passenger())
    assert zero_chest.critical_zero
    good_side = score_side(_side(modifiers={}))
    assert aop_rating(zero_chest, good_side).stars <= 1


def test_qualifiers_limit_stars():
    good = FrontalOccupant(
        neck_shear=ZERO, neck_tension=ZERO, neck_extension=0.0,
        chest_compression=10.0, viscous_criterion=0.1, femur=(ZERO, ZERO),
        knee_displacement=(0.0, 0.0), tibia_index=(0.1, 0.1),
        tibia_force=(100.0, 100.0), hard_contact=False, pedal_rearward=0.0)
    side = score_side(_side(rib_deflection=10.0, rib_vc=0.1, abdominal_force=500.0,
                            modifiers={}))
    frontal = score_frontal(good, good)
    assert frontal.points == 16.0 and side.points == 16.0
    assert aop_rating(frontal, side).stars == 5
    limited = aop_rating(frontal, side, max_stars_allowed=3)
    assert limited.stars == 3 and limited.reasons == ("safety assist qualifiers",)


def test_input_errors():
    with pytest.raises(ValueError, match="pedal_rearward"):
        score_frontal(_driver(pedal_rearward=None), _passenger())
    with pytest.raises(ValueError, match="Unknown modifier"):
        score_frontal(_driver(modifiers={"pelvis": 1.0}), _passenger())
    with pytest.raises(ValueError, match="hic15"):
        score_frontal(_driver(hic15=None), _passenger())


# --- Pole and child stars ------------------------------------------------------


def test_pole_test():
    ok = dict(hic15=650.0, head_peak=75.0, head_contact=False, rib_deflection=40.0,
              rib_vc=0.9, abdominal_force=2400.0, pubic_force=5000.0)
    assert pole_test_passed(**ok)
    for key, bad in (("hic15", 700.0), ("head_peak", 80.0), ("head_contact", True),
                     ("rib_deflection", 43.0), ("pubic_force", 6100.0)):
        assert not pole_test_passed(**{**ok, key: bad})


def test_cop_stars():
    assert [cop_stars(p) for p in (49, 41, 40.99, 27, 18, 9, 8.99)] == \
        [5, 5, 4, 3, 2, 1, 0]
    assert cop_stars(20.0, two_seater=True) == 5
    assert cop_stars(4.99, two_seater=True) == 0
    with pytest.raises(ValueError):
        cop_stars(math.nan)


def test_curve_points_full_score_reports_peak_duration():
    result = curve_points(*plateau(1000.0, 10.0, 50.0), NECK_TENSION_CURVES)
    assert result.points == 4.0
    assert result.level == 1000.0
    assert result.duration_ms == pytest.approx(40.0)


# --- Protocol edition ----------------------------------------------------------


def test_edition_constants_and_dates():
    import datetime as dt

    from crashmetrics.bncap import (
        EDITION,
        PROTOCOL,
        VALID_FROM,
        VALID_UNTIL,
        check_edition,
        edition_for_date,
    )
    assert EDITION == 2023
    assert (VALID_FROM, VALID_UNTIL) == (dt.date(2023, 10, 1), dt.date(2027, 9, 30))
    assert check_edition(2023) == PROTOCOL
    assert edition_for_date(dt.date(2023, 10, 1)) == 2023
    assert edition_for_date(dt.date(2027, 9, 30)) == 2023
    with pytest.raises(ValueError, match="not implemented yet"):
        edition_for_date(dt.date(2027, 10, 1))
    with pytest.raises(ValueError, match="started"):
        edition_for_date(dt.date(2023, 9, 30))
    with pytest.raises(ValueError, match="Unknown Bharat NCAP edition"):
        check_edition(2019)


def test_results_carry_protocol_and_refuse_other_editions():
    from crashmetrics.bncap import PROTOCOL
    frontal = score_frontal(_driver(), _passenger())
    side = score_side(_side())
    assert frontal.protocol == side.protocol == PROTOCOL
    assert aop_rating(frontal, side).protocol == PROTOCOL
    for call in (lambda: score_frontal(_driver(), _passenger(), edition=2027),
                 lambda: score_side(_side(), edition=2027),
                 lambda: aop_rating(frontal, side, edition=2027),
                 lambda: pole_test_passed(500, 70, False, 30, 0.5, 1500, 3000,
                                          edition=2027)):
        with pytest.raises(ValueError, match="Bharat NCAP 2.0"):
            call()
    other = type(frontal)(**{**frontal.__dict__, "protocol": "other rules"})
    with pytest.raises(ValueError, match="different protocol"):
        aop_rating(other, side)


def test_region_values_recorded():
    result = score_frontal(_driver(), _passenger())
    drv = result.regions["driver"]
    assert drv["head"].values == {"hic15": 600.0, "head_a3ms": 60.0}
    assert drv["neck"].values["neck_tension"] == pytest.approx(2500.0)
    assert drv["knee_left"].values["femur_force"] == pytest.approx(5000.0)
    assert drv["foot"].values == {"pedal_rearward": 150.0}
    assert result.regions["passenger"]["head"].values == {}
    assert score_side(_side()).regions["driver"]["pelvis"].values == {
        "pubic_force": 3000.0}


# --- Named modifiers -----------------------------------------------------------


def test_frontal_modifiers_by_name():
    from crashmetrics.bncap import frontal_modifiers
    mods = frontal_modifiers(
        steering_column=(100.0, 0.0, 0.0),           # head 0.5
        unstable_airbag_contact=True,                # head 1
        a_pillar=150.0,                              # chest 1
        shoulder_belt_load=6500.0,                   # chest 2
        knee_concentrated_load=(True, False),        # knee left 1
        pedal_upward=(0.0, 80.0),                    # lower leg right 0.5
        blocked_pedal_rearward=112.5,                # foot 0.5
        footwell_rupture=True,                       # foot 1
        incorrect_airbag_deployment="chest",         # chest 1
    )
    assert mods == pytest.approx({"head": 1.5, "chest": 4.0, "knee_left": 1.0,
                                  "lower_leg_right": 0.5, "foot": 1.5})
    assert frontal_modifiers(shoulder_belt_load=6000.0) == {}
    assert frontal_modifiers() == {}
    result = score_frontal(_driver(modifiers=mods), _passenger())
    assert result.regions["driver"]["chest"].points == 0.0
    with pytest.raises(ValueError, match="Driver-only"):
        frontal_modifiers(driver=False, footwell_rupture=True)
    with pytest.raises(ValueError, match="must be a region"):
        frontal_modifiers(incorrect_airbag_deployment="arm")


def test_side_modifiers_by_name():
    from crashmetrics.bncap import side_modifiers
    assert side_modifiers(backplate_fy=-2500.0) == {"chest": 1.0}
    assert side_modifiers(backplate_fy=2500.0, t12_fy=1750.0, t12_mx=100.0) == \
        pytest.approx({"chest": 2.0})
    assert side_modifiers() == {}
    with pytest.raises(ValueError, match="both"):
        side_modifiers(t12_fy=1750.0)
