"""Bharat NCAP adult occupant scorecard (AIS-197 2023).

`scorecard` lays out a scored frontal and side test like a rating
sheet: every body region with its points, colour, governing criterion
and modifiers, every criterion with its value against the higher and
lower performance limits, where the points are lost, and how many
points the next star needs.

- `Scorecard.markdown`: report for a design review or a pull request.
- `Scorecard.rows`: one row per criterion, for
  `crashmetrics.features.write_csv` or a dataframe.
- `Scorecard.losses`: point losses per body region group, largest first.

Edition: AIS-197 of September 2023, for ratings from 1 October 2023 to
30 September 2027 (`crashmetrics.bncap.PROTOCOL`).
"""

from __future__ import annotations

from dataclasses import dataclass

from crashmetrics.bncap import (
    AOP_STAR_THRESHOLDS,
    EDITION,
    FRONTAL_LIMITS,
    MAX_POINTS,
    SIDE_LIMITS,
    AopRating,
    TestResult,
    aop_rating,
    check_edition,
    colour,
)

__all__ = ["CriterionRow", "Loss", "RegionRow", "Scorecard", "scorecard"]

UNITS: dict[str, str] = {
    "hic15": "", "head_a3ms": "g", "neck_shear": "N", "neck_tension": "N",
    "neck_extension": "N m", "chest_compression": "mm", "viscous_criterion": "m/s",
    "femur_force": "N", "knee_displacement": "mm", "tibia_index": "",
    "tibia_force": "N", "pedal_rearward": "mm", "rib_deflection": "mm",
    "rib_vc": "m/s", "abdominal_force": "N", "pubic_force": "N",
}
"""Unit of each criterion value."""

_CURVES = {"neck_shear", "neck_tension", "femur_force"}

_FRONTAL_GROUPS = {
    "head_neck": ("head", "neck"),
    "chest": ("chest",),
    "knee_femur_pelvis": ("knee_left", "knee_right"),
    "leg_foot": ("lower_leg_left", "lower_leg_right", "foot"),
}


@dataclass(frozen=True)
class RegionRow:
    """One body region of one occupant."""

    test: str
    occupant: str
    region: str
    points: float
    raw_points: float
    modifiers: float
    colour: str
    governing: str
    capped: bool


@dataclass(frozen=True)
class CriterionRow:
    """One criterion of one body region."""

    test: str
    occupant: str
    region: str
    criterion: str
    value: float | None
    unit: str
    hpl: float | None
    """Higher performance limit (None for force-duration curves)."""
    lpl: float | None
    """Lower performance limit (None for force-duration curves)."""
    points: float
    governing: bool


@dataclass(frozen=True)
class Loss:
    """Points lost in one scored group (a region of the test score)."""

    test: str
    group: str
    lost: float
    """4 minus the group's points."""
    occupant: str
    region: str
    cause: str
    """Governing criterion, or ``"modifiers"`` if they cost more."""


@dataclass(frozen=True)
class Scorecard:
    """Adult occupant scorecard of a frontal and a side test."""

    protocol: str
    frontal: float
    side: float
    total: float
    stars: int
    reasons: tuple[str, ...]
    """Why the stars are lower than the points give."""
    next_star: int | None
    """The next star level, None at 5 stars."""
    points_to_next_star: float | None
    """Points missing for the next star level by the thresholds alone
    (the markdown leaves it out when ``reasons`` limit the rating)."""
    regions: tuple[RegionRow, ...]
    criteria: tuple[CriterionRow, ...]
    losses: tuple[Loss, ...]
    test_modifiers: dict[str, float]

    def rows(self) -> list[dict[str, object]]:
        """One dict per criterion (with its region's points and colour)."""
        regions = {(r.test, r.occupant, r.region): r for r in self.regions}
        out: list[dict[str, object]] = []
        for c in self.criteria:
            r = regions[(c.test, c.occupant, c.region)]
            out.append({
                "protocol": self.protocol, "test": c.test, "occupant": c.occupant,
                "region": c.region, "criterion": c.criterion, "value": c.value,
                "unit": c.unit, "hpl": c.hpl, "lpl": c.lpl,
                "criterion_points": c.points, "governing": c.governing,
                "region_points": r.points, "modifiers": r.modifiers,
                "colour": r.colour,
            })
        return out

    def markdown(self) -> str:
        """The scorecard as Markdown tables."""
        lines = [
            "# Bharat NCAP adult occupant scorecard",
            "",
            f"Protocol: {self.protocol}",
            "",
            f"**{self.total:.3f} / 32 points: {self.stars} stars** "
            f"(frontal {self.frontal:.3f} / 16, side {self.side:.3f} / 16)",
        ]
        lines += [f"- Rating limited: {r}" for r in self.reasons]
        if (self.next_star is not None and self.points_to_next_star is not None
                and not self.reasons):
            lines.append(f"- {self.points_to_next_star:.3f} more points reach the "
                         f"{self.next_star}-star threshold")
        for test, mods in self.test_modifiers.items():
            if mods:
                lines.append(f"- {test} test modifiers: -{mods:g} points")
        criteria: dict[tuple[str, str, str], list[CriterionRow]] = {}
        for c in self.criteria:
            criteria.setdefault((c.test, c.occupant, c.region), []).append(c)
        for test in ("frontal", "side"):
            lines += ["", f"## {test.capitalize()} test", "",
                      "| Occupant | Region | Points | Colour | Criteria "
                      "(value: points) | Modifiers |",
                      "| --- | --- | --- | --- | --- | --- |"]
            for r in (r for r in self.regions if r.test == test):
                cells = []
                for c in criteria.get((test, r.occupant, r.region), []):
                    value = ("" if c.value is None
                             else f" {_fmt(c.value)} {c.unit}".rstrip())
                    text = f"{c.criterion}{value}: {c.points:.3f}"
                    cells.append(f"**{text}**" if c.governing else text)
                cap = " (capped)" if r.capped else ""
                penalty = f"-{r.modifiers:g}" if r.modifiers else ""
                lines.append(f"| {r.occupant} | {r.region} | {r.points:.3f}{cap} | "
                             f"{r.colour} | {'; '.join(cells)} | {penalty} |")
        lines += ["", "## Where the points are lost", "",
                  "| Test | Group | Lost | Occupant | Region | Cause |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for loss in self.losses:
            if loss.lost > 0:
                lines.append(f"| {loss.test} | {loss.group} | {loss.lost:.3f} | "
                             f"{loss.occupant} | {loss.region} | {loss.cause} |")
        return "\n".join(lines) + "\n"


def _fmt(value: float) -> str:
    return f"{value:.0f}" if abs(value) >= 100 else f"{value:.3g}"


def _limits(test: str, criterion: str) -> tuple[float | None, float | None]:
    table = FRONTAL_LIMITS if test == "frontal" else SIDE_LIMITS
    if criterion in _CURVES or criterion not in table:
        return None, None
    return table[criterion]


def _losses(test: str, result: TestResult) -> list[Loss]:
    if test == "frontal":
        groups = _FRONTAL_GROUPS
    else:
        groups = {name: (name,) for name in result.groups}
    out = []
    for group, members in groups.items():
        candidates = [(r.points, occ, name, r)
                      for occ, regions in result.regions.items()
                      for name, r in regions.items() if name in members]
        points, occ, name, region = min(candidates, key=lambda c: c[0])
        lost = round(MAX_POINTS - result.groups[group], 3)
        modifier = region.raw_points - region.points
        cause = ("modifiers" if modifier > MAX_POINTS - region.raw_points
                 else region.governing)
        out.append(Loss(test, group, lost, occ, name, cause))
    return out


def scorecard(
    frontal: TestResult,
    side: TestResult,
    rating: AopRating | None = None,
    edition: int = EDITION,
) -> Scorecard:
    """Scorecard of the adult occupant tests.

    Parameters
    ----------
    frontal, side:
        From `crashmetrics.bncap.score_frontal` and `score_side`.
    rating:
        The AOP rating (for example `crashmetrics.bncap_rating.
        bncap_rating(...).aop`, which includes the safety assist
        qualifiers). Default: `aop_rating` of the two tests.
    edition:
        Bharat NCAP edition (2023).
    """
    protocol = check_edition(edition)
    rating = rating if rating is not None else aop_rating(frontal, side,
                                                          edition=edition)
    if rating.protocol != protocol:
        raise ValueError(f"The rating was made with {rating.protocol!r}.")
    regions: list[RegionRow] = []
    criteria: list[CriterionRow] = []
    for test, result in (("frontal", frontal), ("side", side)):
        for occupant, by_region in result.regions.items():
            for name, r in by_region.items():
                applied = round(max(0.0, r.raw_points - r.points), 3)
                regions.append(RegionRow(test, occupant, name, r.points,
                                         r.raw_points, applied, colour(r.points),
                                         r.governing, r.capped))
                for criterion, points in r.criteria.items():
                    hpl, lpl = _limits(test, criterion)
                    criteria.append(CriterionRow(
                        test, occupant, name, criterion, r.values.get(criterion),
                        UNITS.get(criterion, ""), hpl, lpl, round(points, 3),
                        criterion == r.governing))
    losses = sorted(_losses("frontal", frontal) + _losses("side", side),
                    key=lambda loss: -loss.lost)
    next_star = None
    to_next = None
    for stars, minimum in sorted(AOP_STAR_THRESHOLDS):
        if rating.points < minimum:
            next_star, to_next = stars, round(minimum - rating.points, 3)
            break
    return Scorecard(protocol, frontal.points, side.points, rating.points,
                     rating.stars, rating.reasons, next_star, to_next,
                     tuple(regions), tuple(criteria), tuple(losses),
                     {"frontal": frontal.test_modifiers,
                      "side": side.test_modifiers})
