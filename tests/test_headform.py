"""Tests for Euro NCAP headform grid scoring.

The worked examples are from:
- Euro NCAP Assessment Protocol - VRU v11.4 (2023), Section 1.3.2.2
- Euro NCAP Crash Protection - VRU Impacts v1.1 (2026), Section 4.4.2.4
"""

import pytest

from crashmetrics.pedestrian import (
    COLOUR_POINTS,
    PROTOCOLS,
    correction_factor,
    headform_score,
    hic_colour,
    verification_colour,
)


def make_grid(counts, start=0):
    """Grid with the given number of points per label, keyed (i, 0)."""
    grid = {}
    i = start
    for label, n in counts.items():
        for _ in range(n):
            grid[(i, 0)] = label
            i += 1
    return grid


# --- colour bands ----------------------------------------------------------


@pytest.mark.parametrize(
    "hic, colour",
    [
        (0.0, "green"), (649.99, "green"), (650.0, "yellow"),
        (999.99, "yellow"), (1000.0, "orange"), (1349.99, "orange"),
        (1350.0, "brown"), (1699.99, "brown"), (1700.0, "red"),
        (9999.0, "red"),
    ],
)
def test_hic_colour_bands(hic, colour):
    assert hic_colour(hic) == colour


def test_colour_points():
    assert COLOUR_POINTS == {
        "green": 1.0, "yellow": 0.75, "orange": 0.5, "brown": 0.25, "red": 0.0
    }


def test_hic_colour_rejects_invalid():
    with pytest.raises(ValueError):
        hic_colour(-1.0)
    with pytest.raises(ValueError):
        hic_colour(float("nan"))


# --- verification tolerance (accepted ranges from both protocols) ----------


@pytest.mark.parametrize(
    "predicted, measured, expected",
    [
        ("green", 722.21, "green"),     # within green's 10 % range
        ("green", 722.22, "yellow"),    # outside: colour from measured HIC
        ("yellow", 590.91, "yellow"),
        ("yellow", 590.90, "green"),
        ("yellow", 1111.10, "yellow"),
        ("yellow", 1111.11, "orange"),
        ("orange", 909.09, "orange"),
        ("orange", 909.08, "yellow"),
        ("orange", 1499.99, "orange"),
        ("orange", 1500.00, "brown"),
        ("brown", 1227.27, "brown"),
        ("brown", 1888.89, "red"),
        ("red", 1545.45, "red"),
        ("red", 1545.44, "brown"),
    ],
)
def test_verification_tolerance_ranges(predicted, measured, expected):
    assert verification_colour(predicted, measured) == expected


# --- 2026 worked example: verification tests ------------------------------

# Section 4.4.2.4: (point, predicted colour, measured HIC15, actual points)
VERIFICATION_2026 = [
    ((12, -6), "red", 2782.73, 0.00),
    ((9, 2), "green", 541.06, 1.00),
    ((2, 5), "orange", 768.13, 0.75),
    ((1, -1), "yellow", 813.81, 0.75),
    ((8, -4), "green", 558.93, 1.00),
    ((14, -1), "yellow", 372.36, 1.00),
    ((13, 7), "red", 9999.00, 0.00),
    ((4, -5), "yellow", 750.97, 0.75),
    ((15, 5), "yellow", 347.62, 1.00),
    ((10, 1), "yellow", 600.48, 0.75),  # 600.48 is green, but within
]                                       # yellow's tolerance: stays yellow


def test_2026_example_correction_factor():
    tests = {p: (colour, hic) for p, colour, hic, _ in VERIFICATION_2026}

    result = correction_factor(tests, protocol="euroncap_2026")

    assert result.predicted_score == pytest.approx(6.25)
    assert result.actual_score == pytest.approx(7.00)
    assert result.factor == pytest.approx(1.120)
    assert result.accepted
    for test, (_, _, _, points) in zip(result.tests, VERIFICATION_2026):
        assert test.actual_points == points


def test_2026_example_head_score():
    # Section 4.4.2.4 prediction summary: 259 grid points.
    verification_points = {p: colour for p, colour, _, _ in VERIFICATION_2026}
    remaining = {"green": 63, "yellow": 98, "orange": 34, "brown": 3, "red": 39}
    for colour in verification_points.values():
        remaining[colour] -= 1
    grid = dict(verification_points)
    grid.update(make_grid(remaining, start=100))
    grid.update(make_grid({"default_red": 11, "a_pillar": 8}, start=400))
    blue = {(11, 1): "blue", (11, 0): "blue", (11, -1): "blue"}
    grid.update(blue)
    assert len(grid) == 259

    result = headform_score(
        grid,
        verification={p: hic for p, _, hic, _ in VERIFICATION_2026},
        blue_results={p: 1200.0 for p in blue},  # zone result 1200 = orange
        protocol="euroncap_2026",
    )

    assert result.predicted_points == pytest.approx(154.250)
    assert result.correction.factor == pytest.approx(1.120)
    assert result.corrected_points == pytest.approx(154.25 * 1.12)
    assert result.blue_points == pytest.approx(1.5)
    assert result.a_pillar_points == 0.0  # A-pillar points left untested
    assert result.total_points == pytest.approx(174.26)
    assert result.score == pytest.approx(174.26 / 259 * 10)
    assert result.max_score == 10.0
    assert result.colour_counts["default_red"] == 11


# --- 2023 worked example ---------------------------------------------------


def test_2023_example_head_score():
    """Section 1.3.2.2: correction 6.50 / 7.00 = 0.929, predicted
    144.00 x 0.929 = 133.776, plus 2.250 from 5 blue points gives
    136.026 of 232 = 58.632 %, x 18 = 10.554 points."""
    # 10 verification points: 7 green, 3 red (predicted 7.00).
    verification = {}
    grid = {}
    for i in range(7):
        grid[("v", i)] = "green"
        verification[("v", i)] = 500.0 if i < 5 else 900.0  # 2 become yellow
    for i in range(7, 10):
        grid[("v", i)] = "red"
        verification[("v", i)] = 2000.0
    # Remaining coloured points so all 204 predicted points total 144.00:
    # 93 green + 40 yellow + 28 orange + 33 red, plus the 10 above.
    grid.update(make_grid({"green": 93, "yellow": 40, "orange": 28, "red": 33}))
    grid.update(make_grid({"default_red": 23}, start=500))
    blue = {("b", i): "blue" for i in range(5)}
    grid.update(blue)
    blue_results = {("b", 0): 800.0, ("b", 1): 800.0, ("b", 2): 800.0,
                    ("b", 3): 1800.0, ("b", 4): 1800.0}  # 3 x 0.75 = 2.25
    assert len(grid) == 232

    result = headform_score(grid, verification, blue_results,
                            protocol="euroncap_2023")

    assert result.predicted_points == pytest.approx(144.00)
    assert result.correction.predicted_score == pytest.approx(7.00)
    assert result.correction.actual_score == pytest.approx(6.50)
    assert result.correction.factor == pytest.approx(0.929)
    assert result.corrected_points == pytest.approx(133.776)
    assert result.blue_points == pytest.approx(2.250)
    assert result.total_points == pytest.approx(136.026)
    assert result.percentage == pytest.approx(58.632, abs=5e-4)
    assert result.score == pytest.approx(10.554, abs=5e-4)
    assert result.max_score == 18.0


def test_unrounded_correction_factor_option():
    grid = {(i, 0): "green" for i in range(7)}
    verification = {(i, 0): (500.0 if i < 5 else 900.0) for i in range(7)}

    rounded = headform_score(grid, verification)
    exact = headform_score(grid, verification, round_correction_factor=None)

    assert rounded.correction.factor == 0.929
    assert exact.correction.factor == pytest.approx(6.5 / 7.0)


# --- general behaviour -----------------------------------------------------


def test_no_verification_gives_uncorrected_prediction():
    grid = {(0, 0): 500.0, (1, 0): 800.0, (2, 0): 1200.0, (3, 0): "default_red"}

    result = headform_score(grid)

    assert result.correction is None
    assert result.total_points == pytest.approx(1.0 + 0.75 + 0.5)
    assert result.score == pytest.approx(2.25 / 4 * 10)


def test_score_is_capped_at_100_percent():
    grid = {(i, 0): "green" for i in range(10)}
    grid[(10, 0)] = "yellow"
    # Yellow point tests green -> factor 10.75... capped at 100 %.
    result = headform_score(grid, verification={(10, 0): 300.0})

    assert result.total_points > len(grid)
    assert result.percentage == 100.0
    assert result.score == 10.0


def test_correction_factor_outside_range_is_flagged():
    grid = {(i, 0): "yellow" for i in range(4)}
    result = headform_score(grid, verification={(0, 0): 300.0, (1, 0): 300.0})

    assert result.correction.factor == pytest.approx(round(2.0 / 1.5, 3))
    assert not result.correction.accepted


# --- A-pillar rewards (2026) ---------------------------------------------


@pytest.mark.parametrize(
    "tests, points",
    [
        ([(20.0, 950.0)], 1.0),
        ([(20.0, 1000.0)], 0.0),         # 20 km/h needs HIC15 < 1000
        ([(30.0, 1650.0)], 2.0),
        ([(40.0, 1699.0)], 3.0),
        ([(40.0, 1700.0)], 0.0),
        ([(20.0, 800.0), (30.0, 1600.0)], 2.0),  # highest passing speed
        ([(20.0, 800.0), (30.0, 1900.0)], 1.0),
    ],
)
def test_a_pillar_rewards(tests, points):
    grid = {("a", 0): "a_pillar", ("g", 0): "green"}
    result = headform_score(grid, a_pillar_results={("a", 0): tests})
    assert result.a_pillar_points == points
    assert result.total_points == 1.0 + points


def test_untested_a_pillar_scores_zero():
    result = headform_score({("a", 0): "a_pillar", ("g", 0): "green"})
    assert result.a_pillar_points == 0.0
    assert result.score == pytest.approx(5.0)


def test_2023_protocol_has_no_a_pillar_rewards():
    grid = {("a", 0): "a_pillar", ("g", 0): "green"}
    with pytest.raises(ValueError, match="no A-pillar rewards"):
        headform_score(grid, a_pillar_results={("a", 0): [(20.0, 500.0)]},
                       protocol="euroncap_2023")
    assert headform_score(grid, protocol="euroncap_2023").score == 9.0


# --- validation ----------------------------------------------------------


def test_protocol_tables():
    assert PROTOCOLS["euroncap_2026"].max_points == 10.0
    assert PROTOCOLS["euroncap_2023"].max_points == 18.0
    assert PROTOCOLS["euroncap_2026"].correction_range == (0.85, 1.15)


def test_validation_errors():
    with pytest.raises(ValueError, match="no test result"):
        headform_score({(0, 0): "blue"})
    with pytest.raises(ValueError, match="coloured"):
        headform_score({(0, 0): "blue", (1, 0): "green"},
                       verification={(0, 0): 500.0},
                       blue_results={(0, 0): 500.0})
    with pytest.raises(ValueError, match="unknown label"):
        headform_score({(0, 0): "purple"})
    with pytest.raises(ValueError, match="not a 'blue' grid point"):
        headform_score({(0, 0): "green"}, blue_results={(0, 0): 500.0})
    with pytest.raises(ValueError, match="Unknown protocol"):
        headform_score({(0, 0): "green"}, protocol="iihs")
    with pytest.raises(ValueError, match="not one of"):
        headform_score({(0, 0): "a_pillar"}, a_pillar_results={(0, 0): [(25.0, 500)]})
    with pytest.raises(ValueError):
        headform_score({})
