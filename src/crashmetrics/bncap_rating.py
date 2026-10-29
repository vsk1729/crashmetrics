"""Bharat NCAP safety assist qualifiers and the complete rating
(AIS-197 Section 4 and Annexure VI).

Fitment of safety assist technologies is a qualifier for the adult
occupant protection (AOP) stars (Table 2A): a car gets at most the
highest star level whose requirements it meets.

- Every star level: pedestrian protection to AIS-100 and seat belt
  reminders to AIS-145, fitted as standard.
- 5 and 4 stars: ESC fitted, demonstrated and committed to 100 %
  fitment within 2 years; side head protection fitted on the test model,
  a passed pole test, and a minimum standard fitment share by
  publication year (`side_head_fitment_required`).
- 3 stars: ESC as for 5 stars from October 2025 (optional before);
  side head protection optional in at least one variant and a passed
  pole test.
- 1 and 2 stars: ESC and side head protection optional.

Functions:

- `side_head_fitment_required`: Minimum standard fitment share of side
  head protection for 4 or 5 stars by publication date.
- `safety_assist_max_stars`: Highest star level whose qualifiers are met.
- `bncap_rating`: AOP stars (with the qualifiers) and COP stars together.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from crashmetrics.bncap import AopRating, TestResult, aop_rating
from crashmetrics.bncap_cop import CopScore

__all__ = [
    "BncapRating",
    "SafetyAssist",
    "SafetyAssistResult",
    "bncap_rating",
    "safety_assist_max_stars",
    "side_head_fitment_required",
]

_START = dt.date(2023, 10, 1)


def _period_start(year: int) -> dt.date:
    return dt.date(year, 10, 1)


def side_head_fitment_required(stars: int, publication: dt.date) -> float | None:
    """Minimum share of production with side head protection as standard.

    Annexure VI 2.2 (5 stars) and 3.2 (4 stars), by publication year
    (October to September). Returns a fraction (0.3 = 30 %), 0.0 where
    the protection only has to be optional in at least one variant, or
    None for 3 stars and fewer (no fitment share).

    The 4-star table ends in September 2027 and requires 100 % from
    October 2030; in between the last tabulated value (50 %) is used.
    """
    if publication < _START:
        raise ValueError("AIS-197 ratings start in October 2023.")
    if stars == 5:
        steps = [(2023, 0.30), (2024, 0.50), (2025, 0.70), (2026, 0.90), (2027, 1.0)]
    elif stars == 4:
        steps = [(2023, 0.0), (2024, 0.0), (2025, 0.30), (2026, 0.50), (2030, 1.0)]
    else:
        return None
    required = steps[0][1]
    for year, share in steps:
        if publication >= _period_start(year):
            required = share
    return required


@dataclass(frozen=True)
class SafetyAssist:
    """Safety assist technology fitment of the rated model."""

    publication: dt.date
    """Date of publication of the rating."""
    pedestrian_ais100: bool
    """Pedestrian protection to AIS-100 fitted as standard and shown by a
    test or type approval report."""
    seat_belt_reminder_ais145: bool
    """Seat belt reminders to AIS-145 fitted as standard and shown."""
    esc_fitted: bool = False
    """ESC fitted on the test model."""
    esc_demonstrated: bool = False
    """ESC test (UN GTR 8, UN R140 or AIS-133) passed, or a valid type
    approval report."""
    esc_full_fitment_commitment: bool = False
    """Commitment to fit ESC in 100 % of the model within 2 years of
    publication (stand-alone option meanwhile)."""
    side_head_protection_fitted: bool = False
    """Side head protection fitted on the test model."""
    pole_test_passed: bool = False
    """Side pole test to Annexure III performed and passed
    (`crashmetrics.bncap.pole_test_passed`)."""
    side_head_standard_fitment: float = 0.0
    """Share of production with side head protection as standard (0-1)."""
    side_head_optional_in_variant: bool = False
    """Side head protection offered at least as an option in a variant."""


@dataclass(frozen=True)
class SafetyAssistResult:
    max_stars: int
    """Highest star level whose qualifiers are met (0 if not even 1 star)."""
    missing: dict[int, tuple[str, ...]]
    """For each star level, the requirements not met."""


def _esc_full(sa: SafetyAssist) -> list[str]:
    out = []
    if not sa.esc_fitted:
        out.append("ESC not fitted on the test model")
    if not sa.esc_demonstrated:
        out.append("ESC not demonstrated (UN GTR 8 / UN R140 / AIS-133)")
    if not sa.esc_full_fitment_commitment:
        out.append("no commitment to 100 % ESC fitment within 2 years")
    return out


def _side_head(sa: SafetyAssist, stars: int) -> list[str]:
    out = []
    if not sa.pole_test_passed:
        out.append("side pole test not passed")
    if stars == 3:
        if not (sa.side_head_optional_in_variant or sa.side_head_protection_fitted
                or sa.side_head_standard_fitment > 0):
            out.append("side head protection not offered in any variant")
        return out
    if not sa.side_head_protection_fitted:
        out.append("side head protection not fitted on the test model")
    need = side_head_fitment_required(stars, sa.publication)
    if need == 0.0:
        if not (sa.side_head_optional_in_variant or sa.side_head_standard_fitment > 0
                or sa.side_head_protection_fitted):
            out.append("side head protection not offered in any variant")
    elif need is not None and sa.side_head_standard_fitment < need:
        share = sa.side_head_standard_fitment
        out.append(f"side head protection standard in {share:.0%} of production, "
                   f"{need:.0%} required")
    return out


def safety_assist_max_stars(sa: SafetyAssist) -> SafetyAssistResult:
    """Highest AOP star level allowed by the safety assist qualifiers
    (AIS-197 Annexure VI)."""
    if sa.publication < _START:
        raise ValueError("AIS-197 ratings start in October 2023.")
    if not 0.0 <= sa.side_head_standard_fitment <= 1.0:
        raise ValueError("side_head_standard_fitment must be between 0 and 1.")
    base = []
    if not sa.pedestrian_ais100:
        base.append("pedestrian protection to AIS-100 not met")
    if not sa.seat_belt_reminder_ais145:
        base.append("seat belt reminder to AIS-145 not met")
    missing: dict[int, tuple[str, ...]] = {}
    for stars in (1, 2):
        missing[stars] = tuple(base)
    esc_3 = _esc_full(sa) if sa.publication >= _period_start(2025) else []
    missing[3] = tuple(base + esc_3 + _side_head(sa, 3))
    for stars in (4, 5):
        missing[stars] = tuple(base + _esc_full(sa) + _side_head(sa, stars))
    allowed = 0
    for stars in (1, 2, 3, 4, 5):
        if not missing[stars]:
            allowed = stars
        else:
            break
    return SafetyAssistResult(allowed, missing)


@dataclass(frozen=True)
class BncapRating:
    """Complete Bharat NCAP result."""

    aop: AopRating
    cop: CopScore
    safety_assist: SafetyAssistResult

    def summary(self) -> str:
        a, c = self.aop, self.cop
        lines = [
            f"Bharat NCAP: adult {a.stars} stars, child {c.stars} stars",
            f"  Adult occupant {a.points:.3f} / 32 (frontal {a.frontal:.3f}, "
            f"side {a.side:.3f})",
        ]
        lines += [f"    rating limited: {r}" for r in a.reasons]
        lines.append(f"  Safety assist allows up to {self.safety_assist.max_stars} "
                     "stars")
        nxt = self.safety_assist.max_stars + 1
        if nxt <= 5:
            for item in self.safety_assist.missing[nxt]:
                lines.append(f"    for {nxt} stars: {item}")
        lines.append("  " + c.summary().replace("\n", "\n  "))
        return "\n".join(lines)


def bncap_rating(
    frontal: TestResult,
    side: TestResult,
    cop: CopScore,
    safety_assist: SafetyAssist,
) -> BncapRating:
    """Return the adult and child star ratings.

    The AOP stars come from `crashmetrics.bncap.aop_rating` with the
    safety assist qualifiers as ``max_stars_allowed``; the COP stars
    from the COP points (`crashmetrics.bncap_cop.score_cop`).
    """
    sat = safety_assist_max_stars(safety_assist)
    aop = aop_rating(frontal, side, max_stars_allowed=sat.max_stars)
    return BncapRating(aop, cop, sat)
