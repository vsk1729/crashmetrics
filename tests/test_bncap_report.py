"""Tests for crashmetrics.bncap_report (adult occupant scorecard)."""

import pytest
from test_bncap import _driver, _passenger, _side

from crashmetrics.bncap import PROTOCOL, aop_rating, score_frontal, score_side
from crashmetrics.bncap_report import scorecard


def _card(**kw):
    frontal = score_frontal(_driver(), _passenger(), door_openings=1)
    side = score_side(_side())
    return scorecard(frontal, side, **kw), frontal, side


def test_scorecard_totals_and_next_star():
    card, frontal, side = _card()
    assert card.protocol == PROTOCOL
    assert (card.frontal, card.side, card.total) == pytest.approx(
        (4.333, 11.667, 16.0))
    assert card.stars == 2                       # balance rule
    assert card.reasons == ("front / side difference above 35 %",)
    assert card.next_star == 4 and card.points_to_next_star == pytest.approx(6.0)
    assert card.test_modifiers == {"frontal": 1.0, "side": 0.0}


def test_scorecard_regions_criteria_and_losses():
    card, _, _ = _card()
    chest = next(r for r in card.regions if r.test == "frontal"
                 and r.occupant == "driver" and r.region == "chest")
    assert (chest.points, chest.raw_points, chest.modifiers, chest.colour) == (
        1.0, 2.0, 1.0, "brown")
    hic = next(c for c in card.criteria if c.test == "frontal"
               and c.occupant == "driver" and c.criterion == "hic15")
    assert (hic.value, hic.hpl, hic.lpl, hic.points, hic.governing) == (
        600.0, 500.0, 700.0, 2.0, True)
    tension = next(c for c in card.criteria if c.criterion == "neck_tension"
                   and c.occupant == "driver")
    assert tension.hpl is None and tension.unit == "N" and tension.governing
    losses = {(loss.test, loss.group): loss for loss in card.losses}
    assert losses[("frontal", "head_neck")].lost == pytest.approx(3.667)
    assert losses[("frontal", "head_neck")].cause == "neck_tension"
    assert losses[("frontal", "chest")].cause == "chest_compression"
    assert losses[("side", "chest")].cause == "rib_deflection"
    assert [loss.lost for loss in card.losses] == sorted(
        (loss.lost for loss in card.losses), reverse=True)


def test_scorecard_outputs():
    card, _, _ = _card()
    text = card.markdown()
    assert text.startswith("# Bharat NCAP adult occupant scorecard")
    assert PROTOCOL in text
    assert "16.000 / 32 points: 2 stars" in text
    assert "more points reach" not in text       # rating limited by a rule
    assert "| driver | chest | 1.000 | brown |" in text
    assert "**neck_tension 2500 N: 0.333**" in text
    assert "- frontal test modifiers: -1 points" in text
    rows = card.rows()
    assert len(rows) == len(card.criteria)
    assert rows[0]["protocol"] == PROTOCOL
    assert {"region_points", "colour", "hpl", "lpl"} <= set(rows[0])


def test_scorecard_with_given_rating_and_edition():
    frontal = score_frontal(_driver(), _passenger())
    side = score_side(_side())
    limited = aop_rating(frontal, side, max_stars_allowed=1)
    card = scorecard(frontal, side, rating=limited)
    assert card.stars == 1 and "safety assist qualifiers" in card.reasons
    with pytest.raises(ValueError, match="Bharat NCAP 2.0"):
        scorecard(frontal, side, edition=2027)
