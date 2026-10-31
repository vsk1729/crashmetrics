"""Bharat NCAP child occupant protection and safety assist qualifiers,
checked clause by clause against AIS-197 (Annexures V, VI and VIII)."""

import datetime as dt

import pytest

from crashmetrics.bncap import FrontalOccupant, SideOccupant, score_frontal, score_side
from crashmetrics.bncap_cop import (
    CHILD_FRONTAL_LIMITS,
    CHILD_HEAD_CONTACT_PEAK,
    CrsInstallation,
    VehicleBasedAssessment,
    score_child_frontal,
    score_child_side,
    score_cop,
    score_cop_dynamic,
    score_crs_installation,
    score_vehicle_based,
)
from crashmetrics.bncap_rating import (
    SafetyAssist,
    bncap_rating,
    safety_assist_max_stars,
    side_head_fitment_required,
)

# --- Dynamic: limits (Annexure V 4.2.2, 4.2.3) ------------------------------


def test_frontal_limits_are_the_standard_values():
    assert CHILD_FRONTAL_LIMITS["q1.5"] == {
        "head_a3ms": (72.0, 88.0), "neck_tension": (1700.0, 2620.0),
        "chest_a3ms": (41.0, 55.0), "head_excursion": (549.0, 550.0)}
    assert CHILD_FRONTAL_LIMITS["q3"] == {
        "head_a3ms": (87.0, 100.0), "neck_tension": (1700.0, 2620.0),
        "chest_a3ms": (50.0, 66.0), "head_excursion": (549.0, 550.0)}
    assert CHILD_HEAD_CONTACT_PEAK == {"q1.5": 80.0, "q3": 96.0}


def good_frontal(dummy="q3", facing="forward", **kw):
    args = dict(head_a3ms=60.0, neck_tension=1500.0, chest_a3ms=40.0,
                head_peak=70.0, head_excursion=480.0)
    args.update(kw)
    return score_child_frontal(dummy, facing, **args)


def test_frontal_full_points_and_sliding_scales():
    assert good_frontal().points == 8.0
    # neck: 2 points at 1.70 kN, 0 at 2.62 kN, linear between
    assert good_frontal(neck_tension=2160.0).neck == pytest.approx(1.0)
    assert good_frontal(neck_tension=2620.0).neck == 0.0
    # chest Q3: 50 -> 66 g; Q1.5 (rearward facing): 41 -> 55 g
    assert good_frontal(chest_a3ms=58.0).chest == pytest.approx(1.0)
    q15 = good_frontal("q1.5", "rearward", chest_a3ms=48.0)
    assert q15.chest == pytest.approx(1.0)


def test_frontal_head_contact_uses_3ms_scale():
    # no contact (peak below 96 g for the Q3): 4 points whatever the 3 ms value
    assert good_frontal(head_a3ms=95.0, head_peak=95.0).head == 4.0
    # contact by peak >= 96 g: Q3 4 points at 87 g, 0 at 100 g
    r = good_frontal(head_a3ms=93.5, head_peak=96.0)
    assert r.head == pytest.approx(2.0) and r.head_governing == "head contact with CRS"
    # contact by direct evidence; Q1.5 72 -> 88 g
    q15 = good_frontal("q1.5", "rearward", head_a3ms=80.0, head_peak=60.0,
                       crs_head_contact=True)
    assert q15.head == pytest.approx(2.0)


def test_frontal_excursion_and_exposure():
    assert good_frontal(head_excursion=549.0).head == 4.0
    assert good_frontal(head_excursion=550.0).head == 0.0
    assert good_frontal(head_excursion=None).head == 4.0   # cannot be estimated
    rwf = good_frontal("q1.5", "rearward", head_exposure_ok=False)
    assert rwf.head == 0.0 and rwf.head_governing == "head exposure"


def test_frontal_penalties():
    contact = good_frontal(vehicle_head_contact=True)
    assert contact.head == 0.0 and contact.points == 4.0          # 4.2.1
    fwf = good_frontal("q1.5", "forward")
    assert (fwf.head, fwf.neck, fwf.points) == (0.0, 0.0, 2.0)    # 4.1.1: -6


def test_side_scoring():
    assert score_child_side("q3", head_a3ms=90.0, head_peak=90.0).points == 4.0
    contact = score_child_side("q3", head_a3ms=80.0, head_peak=97.0)
    assert contact.points == pytest.approx(2.0)                    # 72 -> 88 g
    assert score_child_side("q1.5", 70.0, crs_head_contact=True).points == 4.0
    assert score_child_side("q1.5", 50.0, head_contained=False).points == 0.0
    assert score_child_side("q3", 50.0, vehicle_head_contact=True).points == 0.0


def test_dynamic_total_ejection_and_recommendation():
    f = [good_frontal("q1.5", "rearward"), good_frontal("q3")]
    s = [score_child_side("q1.5", 50.0), score_child_side("q3", 50.0)]
    assert score_cop_dynamic(f, s).points == 24.0
    ejected = score_cop_dynamic(f, s, ejected=["q3"])
    assert ejected.points == 12.0 and "q3" in ejected.notes[0]
    assert score_cop_dynamic(f, s, recommendation_valid=False).points == 0.0
    with pytest.raises(ValueError, match="One score per dummy"):
        score_cop_dynamic(f + f[:1], s)


# --- CRS installation (Annexure V 3.7) --------------------------------------


def test_crs_installation_reproduces_the_standards_example():
    """AIS-197 Annexure V 3.7, Table 1: reference list 7.143, OEM 2.000,
    total 9.143."""
    reference = [
        CrsInstallation("Peg Perego Viaggio Switchable", 2, 0),
        CrsInstallation("Roemer Baby Safe", 2, 0),
        CrsInstallation("Bebe Confort Streety Fix / Maxi Cosi Citi SPS", 2, 2),
        CrsInstallation("Peg Perego Viaggio Switchable FWF", 3, 0),
        CrsInstallation("Graco Cadeira Nautilus FWF", 3, 2),
        CrsInstallation("Cybex Solution M-Fix", 3, 1),
        CrsInstallation("Graco Cadeira Nautilus", 3, 0),
    ]
    oem = [CrsInstallation("Manufacturer CRS for Q1.5", 2, 0),
           CrsInstallation("Manufacturer CRS for Q3", 2, 0)]
    r = score_crs_installation(reference, oem)
    assert r.installation_list == 7.143
    assert r.recommended == 2.0
    assert r.points == 9.143
    assert r.crs_scores["Graco Cadeira Nautilus FWF"] == pytest.approx(1 / 3)


def test_crs_installation_rules():
    ok = [CrsInstallation("a", 3, 0), CrsInstallation("b", 2, 0)]
    assert score_crs_installation(ok, ok).points == 12.0
    no_rec = score_crs_installation(ok)
    assert no_rec.points == 10.0 and no_rec.max_points == 10.0      # 3.7.9
    halved = score_crs_installation(ok, ok, coverage_requirements_met=False)
    assert halved.points == 6.0                                     # 3.2.9
    zero = score_crs_installation([CrsInstallation("a", 2, 0),
                                   CrsInstallation("none", 0, 0)])
    assert zero.installation_list == 5.0                            # 3.7.3
    exempt = score_crs_installation([CrsInstallation("a", 2, 0),
                                     CrsInstallation("x", 0, 0, exempt=True)])
    assert exempt.installation_list == 10.0                         # 3.7.5
    with pytest.raises(ValueError, match="failed"):
        score_crs_installation([CrsInstallation("bad", 2, 3)])


# --- Vehicle based assessments (Annexure V 5, 6.1.3; Annexure VIII 4.2) -----


FULL = VehicleBasedAssessment(
    gabarit_all_seats=True, gabarit_handbook_and_airbag=True,
    three_simultaneous=True, three_simultaneous_isize=True,
    isofix_un=True, isofix_marked=True, isofix_isize_ready=True,
    two_largest_isofix=True, airbag="automatic",
    integrated_crs=True, integrated_crs_group_1_3=True)


def test_vehicle_based_maximum_is_13_and_10():
    full = score_vehicle_based(FULL)
    assert full.points == 13.0 and full.max_points == 13.0
    assert full.items == {"gabarit": 2.0, "three_simultaneous": 2.0,
                          "isofix_usability": 2.0, "two_largest_isofix": 1.0,
                          "airbag": 4.0, "integrated_crs": 2.0}
    two = score_vehicle_based(FULL, two_seater=True)
    assert two.points == 10.0 and two.max_points == 10.0
    assert two.items["three_simultaneous"] == 0.0 and two.items["gabarit"] == 1.0


@pytest.mark.parametrize("state, points", [
    ("label_not_ok", 0.0), ("label_only", 1.0), ("manual", 3.0), ("automatic", 4.0),
])
def test_airbag_points(state, points):
    assert score_vehicle_based(VehicleBasedAssessment(airbag=state)).points == points


def test_vehicle_based_preconditions():
    # ISOFIX: A precondition to B, B to C (5.4)
    only_c = VehicleBasedAssessment(isofix_un=True, isofix_isize_ready=True)
    assert score_vehicle_based(only_c).items["isofix_usability"] == 0.0
    a_b = VehicleBasedAssessment(isofix_un=True, isofix_marked=True)
    assert score_vehicle_based(a_b).items["isofix_usability"] == 1.0
    no_un = VehicleBasedAssessment(isofix_marked=True, isofix_isize_ready=True)
    assert score_vehicle_based(no_un).items["isofix_usability"] == 0.0
    # 3-point belts missing: all vehicle based points 0 (5.1)
    belts = VehicleBasedAssessment(three_point_belts=False, airbag="automatic")
    assert score_vehicle_based(belts).points == 0.0
    # two-seater with passenger airbag and no deactivation: 0 (6.1.4)
    two = VehicleBasedAssessment(airbag="label_only", two_largest_isofix=True)
    assert score_vehicle_based(two, two_seater=True).points == 0.0
    # second Gabarit / integrated point only with the first
    assert score_vehicle_based(VehicleBasedAssessment(
        gabarit_handbook_and_airbag=True, integrated_crs_group_1_3=True)).points == 0.0


# --- COP total and stars (Table 2B, Annexure VIII 4.3) -----------------------


@pytest.mark.parametrize("points, stars", [
    (49.0, 5), (41.0, 5), (40.99, 4), (35.0, 4), (27.0, 3), (26.99, 2), (18.0, 2),
    (9.0, 1), (8.99, 0),
])
def test_cop_stars_thresholds(points, stars):
    from crashmetrics.bncap import cop_stars
    assert cop_stars(points) == stars


def test_cop_total():
    f = [good_frontal("q1.5", "rearward"), good_frontal("q3")]
    s = [score_child_side("q1.5", 50.0), score_child_side("q3", 50.0)]
    ok = [CrsInstallation("a", 3, 0)]
    cop = score_cop(score_crs_installation(ok, ok), score_vehicle_based(FULL),
                    score_cop_dynamic(f, s))
    assert cop.points == 49.0 and cop.stars == 5 and cop.max_points == 49.0
    assert "49.000 / 49 -> 5 stars" in cop.summary()
    two = score_cop(score_crs_installation(ok, ok),
                    score_vehicle_based(FULL, two_seater=True), two_seater=True)
    assert (two.points, two.max_points, two.stars) == (22.0, 22.0, 5)
    with pytest.raises(ValueError, match="dynamic"):
        score_cop(score_crs_installation(ok), score_vehicle_based(FULL))
    with pytest.raises(ValueError, match="no dynamic"):
        score_cop(score_crs_installation(ok), score_vehicle_based(FULL, True),
                  score_cop_dynamic(f, s), two_seater=True)
    with pytest.raises(ValueError, match="two_seater"):
        score_cop(score_crs_installation(ok), score_vehicle_based(FULL),
                  two_seater=True)


# --- Safety assist qualifiers (Annexure VI) ---------------------------------


@pytest.mark.parametrize("stars, date, share", [
    (5, dt.date(2023, 10, 1), 0.30), (5, dt.date(2024, 9, 30), 0.30),
    (5, dt.date(2024, 10, 1), 0.50), (5, dt.date(2025, 10, 1), 0.70),
    (5, dt.date(2026, 10, 1), 0.90), (5, dt.date(2027, 10, 1), 1.0),
    (4, dt.date(2024, 1, 1), 0.0), (4, dt.date(2025, 9, 30), 0.0),
    (4, dt.date(2025, 10, 1), 0.30), (4, dt.date(2026, 10, 1), 0.50),
    (4, dt.date(2029, 1, 1), 0.50), (4, dt.date(2030, 10, 1), 1.0),
    (3, dt.date(2026, 1, 1), None),
])
def test_side_head_fitment_by_publication(stars, date, share):
    assert side_head_fitment_required(stars, date) == share


def full_sat(date=dt.date(2026, 11, 1), **kw):
    args = dict(publication=date, pedestrian_ais100=True,
                seat_belt_reminder_ais145=True, esc_fitted=True,
                esc_demonstrated=True, esc_full_fitment_commitment=True,
                side_head_protection_fitted=True, pole_test_passed=True,
                side_head_standard_fitment=1.0, side_head_optional_in_variant=True)
    args.update(kw)
    return SafetyAssist(**args)


def test_safety_assist_levels():
    assert safety_assist_max_stars(full_sat()).max_stars == 5
    # Nov 2026: 5 stars need 90 %, 4 stars need 50 %
    r = safety_assist_max_stars(full_sat(side_head_standard_fitment=0.6))
    assert r.max_stars == 4 and "90% required" in r.missing[5][0]
    low = full_sat(side_head_standard_fitment=0.4)
    assert safety_assist_max_stars(low).max_stars == 3
    # no ESC commitment: 4/5 lost; from Oct 2025 also 3 stars
    assert safety_assist_max_stars(full_sat(esc_full_fitment_commitment=False)
                                   ).max_stars == 2
    early = full_sat(dt.date(2024, 6, 1), esc_fitted=False, esc_demonstrated=False,
                     esc_full_fitment_commitment=False)
    assert safety_assist_max_stars(early).max_stars == 3       # ESC optional for 3
    # no passed pole test: at most 2 stars
    assert safety_assist_max_stars(full_sat(pole_test_passed=False)).max_stars == 2
    # pedestrian or SBR missing: not even 1 star
    assert safety_assist_max_stars(full_sat(pedestrian_ais100=False)).max_stars == 0
    assert safety_assist_max_stars(full_sat(seat_belt_reminder_ais145=False)
                                   ).max_stars == 0
    # 4 stars before Oct 2025: optional in a variant is enough
    opt = full_sat(dt.date(2024, 11, 1), side_head_standard_fitment=0.0)
    assert safety_assist_max_stars(opt).max_stars == 4
    with pytest.raises(ValueError, match="October 2023"):
        safety_assist_max_stars(full_sat(dt.date(2023, 1, 1)))


# --- Complete rating ---------------------------------------------------------


def test_bncap_rating_applies_the_qualifiers():
    import numpy as np

    t = np.arange(0.0, 0.1, 1e-4)
    quiet = (t, np.zeros_like(t))
    occupant = FrontalOccupant(
        neck_shear=quiet, neck_tension=quiet, neck_extension=10.0,
        chest_compression=15.0, viscous_criterion=0.2, femur=(quiet, quiet),
        knee_displacement=(1.0, 1.0), tibia_index=(0.3, 0.3),
        tibia_force=(1000.0, 1000.0), hard_contact=False, pedal_rearward=0.0)
    frontal = score_frontal(occupant, occupant)
    side = score_side(SideOccupant(hic15=200.0, head_a3ms=30.0, rib_deflection=20.0,
                                   rib_vc=0.3, abdominal_force=900.0,
                                   pubic_force=2500.0))
    f = [good_frontal("q1.5", "rearward"), good_frontal("q3")]
    s = [score_child_side("q1.5", 50.0), score_child_side("q3", 50.0)]
    ok = [CrsInstallation("a", 3, 0)]
    cop = score_cop(score_crs_installation(ok, ok), score_vehicle_based(FULL),
                    score_cop_dynamic(f, s))
    full = bncap_rating(frontal, side, cop, full_sat())
    assert full.aop.stars == 5 and full.cop.stars == 5
    sat = full_sat(side_head_standard_fitment=0.6)
    capped = bncap_rating(frontal, side, cop, sat)
    assert capped.aop.stars == 4
    assert "safety assist qualifiers" in capped.aop.reasons
    assert "for 5 stars: side head protection standard in 60%" in capped.summary()
    # Every result names its protocol; other editions are refused.
    from crashmetrics.bncap import PROTOCOL
    assert full.protocol == full.aop.protocol == full.cop.protocol == PROTOCOL
    assert f"Protocol: {PROTOCOL}" in full.summary()
    with pytest.raises(ValueError, match="Bharat NCAP 2.0"):
        bncap_rating(frontal, side, cop, full_sat(), edition=2027)
    with pytest.raises(ValueError, match="Bharat NCAP 2.0"):
        score_cop(score_crs_installation(ok, ok), score_vehicle_based(FULL),
                  score_cop_dynamic(f, s), edition=2027)
    other = type(cop)(**{**cop.__dict__, "protocol": "other rules"})
    with pytest.raises(ValueError, match="child score"):
        bncap_rating(frontal, side, other, full_sat())
