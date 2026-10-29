import pytest

from crashmetrics.features import flatten
from crashmetrics.frontal_scoring import BAND_FRACTIONS_TABLE
from crashmetrics.side_scoring import (
    AE_MDB_OCCUPANTS,
    FAR_SIDE_ZONE_POINTS,
    POLE_OCCUPANTS,
    SIDE_DUMMY_LIMITS,
    FarSideCase,
    SideOccupant,
    far_side_zone,
    score_ae_mdb,
    score_far_side,
    score_far_side_case,
    score_pole,
    score_side,
    score_side_dummy,
)

GREEN_WS = {"hic15": 300.0, "head_a3ms": 50.0, "chest_compression": 20.0,
            "abdomen_compression": 30.0, "pubic_force": 1000.0}
GREEN_Q = {"hic15": 300.0, "head_a3ms": 40.0, "neck_tension": 1000.0,
           "chest_a3ms": 30.0}


def ws(**changes):
    return SideOccupant({**GREEN_WS, **changes}, hard_contact=True)


def q(**changes):
    return SideOccupant({**GREEN_Q, **changes}, hard_contact=True)


# --- protocol values ------------------------------------------------------------


def test_points_layout_and_limits():
    assert sum(AE_MDB_OCCUPANTS["driver"][1].values()) == 10.0
    assert sum(AE_MDB_OCCUPANTS["rear_q6"][1].values()) == 2.5
    assert sum(AE_MDB_OCCUPANTS["rear_q10"][1].values()) == 2.5
    assert sum(POLE_OCCUPANTS["driver"][1].values()) == 10.0
    w = SIDE_DUMMY_LIMITS["worldsid_50"]
    assert (w["hic15"].hpl, w["hic15"].lpl) == (500.0, 700.0)
    assert (w["head_a3ms"].hpl, w["head_a3ms"].lpl) == (72.0, 80.0)
    assert (w["chest_compression"].hpl, w["chest_compression"].lpl) == (28.0, 50.0)
    assert (w["abdomen_compression"].hpl, w["abdomen_compression"].lpl) == (47.0, 65.0)
    assert (w["pubic_force"].hpl, w["pubic_force"].lpl) == (1700.0, 2800.0)
    assert SIDE_DUMMY_LIMITS["q6"]["neck_tension"].lpl == 2400.0
    assert SIDE_DUMMY_LIMITS["q10"]["neck_tension"].lpl == 2200.0


# --- near side dummies -------------------------------------------------------------


def test_all_green_scores_full_points():
    t = score_ae_mdb(ws(), q(), q())
    assert t.points == pytest.approx(15.0) and t.max_points == 15.0
    assert score_pole(ws()).points == pytest.approx(10.0)


@pytest.mark.parametrize("value, band, points", [
    (27.9, "green", 2.5), (28.0, "yellow", 2.0), (35.3, "yellow", 2.0),
    (35.4, "orange", 1.5), (42.7, "brown", 1.0), (49.9, "brown", 1.0),
    (50.0, "red", 0.0),
])
def test_chest_bands(value, band, points):
    d = score_side_dummy("worldsid_50", ws(chest_compression=value),
                         AE_MDB_OCCUPANTS["driver"][1])
    assert d.regions["chest"].band == band
    assert d.regions["chest"].points == pytest.approx(points)


def test_table_band_fractions_option():
    d = score_side_dummy("worldsid_50", ws(chest_compression=36.0),
                         AE_MDB_OCCUPANTS["driver"][1],
                         band_fractions=BAND_FRACTIONS_TABLE)
    assert d.regions["chest"].band == "orange"
    assert d.regions["chest"].points == pytest.approx(0.4 * 2.5)


def test_chest_capping_differs_between_tests():
    pts = AE_MDB_OCCUPANTS["driver"][1]
    mdb = score_side_dummy("worldsid_50", ws(chest_compression=52.0), pts, "ae_mdb")
    pole = score_side_dummy("worldsid_50", ws(chest_compression=52.0), pts, "pole")
    assert "chest_compression" in mdb.capping_exceeded
    assert "chest_compression" not in pole.capping_exceeded
    assert mdb.regions["chest"].points == pole.regions["chest"].points == 0.0


def test_no_hard_contact_uses_head_3ms_only():
    pts = AE_MDB_OCCUPANTS["driver"][1]
    hard = score_side_dummy("worldsid_50", ws(hic15=690.0), pts)
    no_contact = SideOccupant({**GREEN_WS, "hic15": 690.0}, hard_contact=False)
    soft = score_side_dummy("worldsid_50", no_contact, pts)
    assert hard.regions["head"].band == "brown"
    assert soft.regions["head"].band == "green"
    inferred = score_side_dummy(
        "worldsid_50", SideOccupant({**GREEN_WS, "head_peak": 85.0}), pts)
    assert inferred.hard_contact is True
    with pytest.raises(ValueError, match="hard_contact"):
        score_side_dummy("worldsid_50", SideOccupant(GREEN_WS), pts)


def test_worldsid_modifiers():
    pts = AE_MDB_OCCUPANTS["driver"][1]
    shoulder = score_side_dummy("worldsid_50", ws(shoulder_force=3000.0), pts)
    assert shoulder.regions["chest"].points == 0.0
    assert shoulder.points == pytest.approx(7.5)
    vc = score_side_dummy("worldsid_50", ws(chest_vc=1.0, abdomen_vc=1.0), pts)
    assert vc.points == pytest.approx(5.0)
    below = score_side_dummy("worldsid_50", ws(shoulder_force=2999.0, chest_vc=0.99),
                             pts)
    assert below.points == pytest.approx(10.0)
    bad_airbag = SideOccupant(GREEN_WS, hard_contact=True,
                              incorrect_airbag_deployment=True)
    airbag = score_side_dummy("worldsid_50", bad_airbag, pts)
    assert airbag.points == pytest.approx(8.0)          # -20 % of each region


def test_q_dummy_and_dummy_modifier():
    pts = AE_MDB_OCCUPANTS["rear_q10"][1]
    assert score_side_dummy("q10", q(neck_tension=2200.0), pts).regions["neck"].band \
        == "red"
    assert score_side_dummy("q6", q(neck_tension=2200.0), pts).regions["neck"].band \
        == "green"                                     # Q6 limit is 2.4 kN
    crs = SideOccupant(GREEN_Q, hard_contact=True, dummy_modifiers=[50.0])
    assert score_side_dummy("q6", crs, pts).points == pytest.approx(1.25)


def test_test_modifiers():
    assert score_ae_mdb(ws(), q(), q(), door_openings=2).points == pytest.approx(14.0)
    # % of the 10-point adult load case: the child dummies' 5 points remain
    assert score_ae_mdb(ws(), q(), q(), door_detachment=True).points == 5.0
    pole = score_pole(ws(), curtain_zone_rows_failed=2, rollover_protection=False)
    assert pole.points == pytest.approx(10.0 - 2.0 - 2.0)
    none = score_pole(None, head_protection_fitted=False)
    assert none.points == 0.0 and none.max_points == 10.0


def test_input_errors():
    pts = AE_MDB_OCCUPANTS["driver"][1]
    with pytest.raises(ValueError, match="Unknown criteria"):
        score_side_dummy("worldsid_50", ws(neck_tension=1.0), pts)
    with pytest.raises(ValueError, match="Missing"):
        score_side_dummy("worldsid_50", SideOccupant({"hic15": 1.0}, hard_contact=True),
                         pts)
    with pytest.raises(ValueError, match="Unknown dummy"):
        score_side_dummy("es2", ws(), pts)
    with pytest.raises(ValueError, match="test"):
        score_side_dummy("worldsid_50", ws(), pts, test="frontal")


# --- far side ---------------------------------------------------------------------


@pytest.mark.parametrize("clearance, red, zone", [
    (300, 200, "green"), (250, 200, "green"), (249, 200, "yellow"),
    (125, 200, "yellow"), (124, 200, "orange"), (0, 200, "orange"),
    (-1, 200, "brown"), (-1, 125, "red"), (-150, 200, "brown"),
    (-201, 200, "capping"), (40, -50, "capping"), (60, -50, "orange"),
])
def test_far_side_zones(clearance, red, zone):
    assert far_side_zone(clearance, red) == zone


def test_far_side_zone_points_tables():
    assert FAR_SIDE_ZONE_POINTS[True] == {
        "green": 2.0, "yellow": 2.0, "orange": 1.5, "brown": 1.0, "red": 0.5,
        "capping": 0.0}
    assert FAR_SIDE_ZONE_POINTS[False] == {
        "green": 2.0, "yellow": 1.0, "orange": 0.5, "brown": 0.0, "red": 0.0,
        "capping": 0.0}


def test_far_side_case_capping_and_pelvis_modifier():
    ok = score_far_side_case(FarSideCase("orange", {"chest_compression": 30.0}), True)
    assert ok.points == 1.5 and ok.capped == ()
    capped = score_far_side_case(FarSideCase("green", {"upper_neck_tension": 3740.0}),
                                 True)
    assert capped.points == 0.0 and capped.capped == ("upper_neck_tension",)
    pelvis = score_far_side_case(FarSideCase("green", {"lumbar_mx": 125.0}), True)
    assert pelvis.points == pytest.approx(1.5) and pelvis.pelvis_modifier == 0.5
    extension = score_far_side_case(
        FarSideCase("green", {"upper_neck_extension": -55.0}), True)
    assert extension.points == 0.0                      # magnitude of negative My
    with pytest.raises(ValueError, match="Unknown far side"):
        score_far_side_case(FarSideCase("green", {"femur": 1.0}), True)
    with pytest.raises(ValueError, match="zone"):
        score_far_side_case(FarSideCase("purple"), True)


def test_far_side_total_and_robustness():
    full = score_far_side(FarSideCase("yellow"), FarSideCase("green"),
                          robustness_ae_mdb=["yellow", "orange", "green", "yellow"],
                          robustness_pole=["yellow", "green"],
                          occupant_to_occupant_passed=True,
                          near_side_driver_points=18.0)
    assert full.points == pytest.approx(10.0)
    # two zones worse than the main case, or a red case: no robustness points
    worse = score_far_side(FarSideCase("green"), FarSideCase("green"),
                           robustness_ae_mdb=["orange"], robustness_pole=["red"])
    assert worse.robustness_ae_mdb == 0.0 and worse.robustness_pole == 0.0
    # virtual tests not validated: main load cases only
    no_vt = score_far_side(FarSideCase("green"), FarSideCase("green"),
                           robustness_ae_mdb=["green"], robustness_pole=["green"],
                           virtual_testing_validated=False)
    assert no_vt.points == pytest.approx(4.0)
    # without a countermeasure, robustness only if the main case is green
    no_cm = score_far_side(FarSideCase("yellow"), FarSideCase("green"),
                           robustness_ae_mdb=["yellow"], robustness_pole=["green"],
                           countermeasure=False)
    assert (no_cm.main_ae_mdb.points, no_cm.robustness_ae_mdb) == (1.0, 0.0)
    assert no_cm.robustness_pole == 2.0


def test_far_side_capping_zone_caps_both_and_disqualification():
    cap = score_far_side(FarSideCase("capping"), FarSideCase("green"))
    assert cap.main_ae_mdb.points == 0.0 and cap.main_pole.points == 0.0
    assert "capping zone" in cap.main_pole.capped
    dq = score_far_side(FarSideCase("green"), FarSideCase("green"),
                        occupant_to_occupant_passed=True, near_side_driver_points=16.9)
    assert dq.points == 0.0 and "below 17.0" in dq.disqualified[0]
    for kwargs in ({"structural_failure": True}, {"far_side_restraint_failure": True}):
        assert score_far_side(FarSideCase("green"), FarSideCase("green"),
                              **kwargs).points == 0.0


def test_side_total_summary_and_flatten():
    total = score_side(score_ae_mdb(ws(), q(), q()), score_pole(ws()),
                       score_far_side(FarSideCase("green"), FarSideCase("green"),
                                      ["green"], ["green"], True,
                                      occupant_to_occupant_passed=True,
                                      near_side_driver_points=20.0))
    assert total.points == pytest.approx(35.0)
    assert "Euro NCAP side impact: 35.000 / 35" in total.summary()
    flat = flatten(total)
    assert flat["far_side.main_pole.zone"] == "green"
    assert flat["ae_mdb.occupants.driver.regions.chest.band"] == "green"
