"""Bharat NCAP child occupant protection (AIS-197 Annexure V).

The child occupant protection (COP) score is out of 49 points (22 for
vehicles without rear seats, such as two-seaters), the sum of:

- Dynamic assessment, 24 points: Q1.5 and Q3 in the ODB frontal test
  (8 points each: head 4, neck 2, chest 2) and the MDB side test (4
  points each, head). `score_child_frontal`, `score_child_side`,
  `score_cop_dynamic`.
- CRS installation, 12 points: installation list (10) and the two
  manufacturer-recommended CRS (2). `score_crs_installation`.
- Vehicle based assessments, 13 points (10 for two-seaters).
  `score_vehicle_based`.

`score_cop` adds them up and gives the COP stars (Annexure VIII 4.3).
Scores are rounded to 3 decimals (Section 4.2 of the standard).

Edition: AIS-197 of September 2023, for ratings from 1 October 2023 to
30 September 2027 (`crashmetrics.bncap.PROTOCOL`); `score_cop` takes
``edition=2023`` and its result carries the ``protocol`` text.

Units: accelerations g, forces N, excursions mm.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from crashmetrics._scoring import linear_fraction
from crashmetrics.bncap import EDITION, PROTOCOL, check_edition, cop_stars

__all__ = [
    "CHILD_FRONTAL_LIMITS",
    "CHILD_HEAD_CONTACT_PEAK",
    "CHILD_SIDE_LIMITS",
    "ChildFrontalScore",
    "ChildSideScore",
    "CopDynamicScore",
    "CopScore",
    "CrsInstallation",
    "CrsInstallationScore",
    "VehicleBasedAssessment",
    "VehicleBasedScore",
    "score_child_frontal",
    "score_child_side",
    "score_cop",
    "score_cop_dynamic",
    "score_crs_installation",
    "score_vehicle_based",
]

Dummy = Literal["q1.5", "q3"]
Facing = Literal["forward", "rearward"]

CHILD_HEAD_CONTACT_PEAK: dict[str, float] = {"q1.5": 80.0, "q3": 96.0}
"""Peak resultant head acceleration (g) at or above which head contact
with the CRS is assumed (4.2.2.1, 4.2.3.2)."""

CHILD_FRONTAL_LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "q1.5": {"head_a3ms": (72.0, 88.0), "neck_tension": (1700.0, 2620.0),
             "chest_a3ms": (41.0, 55.0), "head_excursion": (549.0, 550.0)},
    "q3": {"head_a3ms": (87.0, 100.0), "neck_tension": (1700.0, 2620.0),
           "chest_a3ms": (50.0, 66.0), "head_excursion": (549.0, 550.0)},
}
"""Frontal (higher, lower) performance limits (Annexure V 4.2.2): full
points at or below the first value, none at or above the second, linear
between. Head 3 ms acceleration only applies with head contact."""

CHILD_SIDE_LIMITS: dict[str, tuple[float, float]] = {"head_a3ms": (72.0, 88.0)}
"""Side head 3 ms acceleration limits for both dummies (4.2.3.2)."""


def _r3(x: float) -> float:
    return round(x + 0.0, 3)


def _check(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")


def _dummy(dummy: str) -> str:
    if dummy not in CHILD_FRONTAL_LIMITS:
        raise ValueError('dummy must be "q1.5" or "q3".')
    return dummy


# --- Dynamic assessment ----------------------------------------------------


@dataclass(frozen=True)
class ChildFrontalScore:
    """Frontal impact score of one child dummy (8 points)."""

    dummy: str
    points: float
    head: float
    """Worst of head contact, excursion (forward facing) or exposure
    (rearward facing), 0-4."""
    neck: float
    """0-2."""
    chest: float
    """0-2."""
    head_governing: str
    """What set the head score."""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChildSideScore:
    """Side impact score of one child dummy (4 points, head)."""

    dummy: str
    points: float
    head_governing: str
    notes: tuple[str, ...] = ()


def _head_contact(dummy: str, head_peak: float | None, evidence: bool) -> bool:
    return evidence or (head_peak is not None
                        and head_peak >= CHILD_HEAD_CONTACT_PEAK[dummy])


def score_child_frontal(
    dummy: Dummy,
    facing: Facing,
    head_a3ms: float,
    neck_tension: float,
    chest_a3ms: float,
    head_peak: float | None = None,
    crs_head_contact: bool = False,
    head_excursion: float | None = None,
    head_exposure_ok: bool = True,
    vehicle_head_contact: bool = False,
) -> ChildFrontalScore:
    """Score a Q1.5 or Q3 in the ODB frontal test (Annexure V 4.2.2).

    Parameters
    ----------
    dummy:
        ``"q1.5"`` or ``"q3"``.
    facing:
        ``"forward"`` or ``"rearward"`` facing CRS.
    head_a3ms:
        Head resultant acceleration, 3 ms exceedance, g (used only with
        head contact with the CRS).
    neck_tension:
        Upper neck Fz tension, N.
    chest_a3ms:
        Chest resultant acceleration, 3 ms exceedance, g.
    head_peak:
        Peak head resultant acceleration, g: contact with the CRS is
        assumed at or above 80 g (Q1.5) or 96 g (Q3).
    crs_head_contact:
        Direct evidence of head contact with the CRS.
    head_excursion:
        Forward facing: largest forward head excursion relative to the
        Cr point, mm (4 points up to 549 mm, 0 from 550 mm); None if it
        cannot be estimated (then deemed 549 mm or less).
    head_exposure_ok:
        Rearward facing: no compressive load on the top of the head and
        the head contained in the shell (4.2.2.3).
    vehicle_head_contact:
        Head contact with the vehicle at any time (4.2.1): no head points
        in this test.

    Notes
    -----
    A Q1.5 in a forward facing CRS loses 6 points, 4 for the head and 2
    for the neck (4.1.1).
    """
    lim = CHILD_FRONTAL_LIMITS[_dummy(dummy)]
    if facing not in ("forward", "rearward"):
        raise ValueError('facing must be "forward" or "rearward".')
    for name, v in (("head_a3ms", head_a3ms), ("neck_tension", neck_tension),
                    ("chest_a3ms", chest_a3ms), ("head_peak", head_peak),
                    ("head_excursion", head_excursion)):
        _check(name, v)

    notes: list[str] = []
    candidates: dict[str, float] = {}
    if _head_contact(dummy, head_peak, crs_head_contact):
        candidates["head contact with CRS"] = 4.0 * linear_fraction(
            head_a3ms, *lim["head_a3ms"])
    else:
        candidates["no head contact with CRS"] = 4.0
    if facing == "forward":
        excursion = head_excursion if head_excursion is not None else 549.0
        candidates["head excursion"] = 4.0 * linear_fraction(
            excursion, *lim["head_excursion"])
    else:
        candidates["head exposure"] = 4.0 if head_exposure_ok else 0.0
    governing = min(candidates, key=lambda k: candidates[k])
    head = candidates[governing]
    neck = 2.0 * linear_fraction(abs(neck_tension), *lim["neck_tension"])
    chest = 2.0 * linear_fraction(chest_a3ms, *lim["chest_a3ms"])

    if vehicle_head_contact:
        head, governing = 0.0, "head contact with the vehicle"
        notes.append("head contact with the vehicle: no head points (4.2.1)")
    if dummy == "q1.5" and facing == "forward":
        head, neck = 0.0, 0.0
        governing = "Q1.5 in a forward facing CRS"
        notes.append("Q1.5 in a forward facing CRS: -6 points (4.1.1)")
    head, neck, chest = _r3(head), _r3(neck), _r3(chest)
    return ChildFrontalScore(dummy, _r3(head + neck + chest), head, neck, chest,
                             governing, tuple(notes))


def score_child_side(
    dummy: Dummy,
    head_a3ms: float,
    head_peak: float | None = None,
    crs_head_contact: bool = False,
    head_contained: bool = True,
    vehicle_head_contact: bool = False,
) -> ChildSideScore:
    """Score a Q1.5 or Q3 in the MDB side test (Annexure V 4.2.3), 4
    points.

    The head must stay contained in the CRS shell (else 0); without head
    contact with the CRS it scores 4, with contact 4 points at 72 g or
    less and none from 88 g (head 3 ms acceleration).
    """
    _dummy(dummy)
    _check("head_a3ms", head_a3ms)
    _check("head_peak", head_peak)
    if not head_contained:
        return ChildSideScore(dummy, 0.0, "head not contained in the CRS",
                              ("head not contained: 0 points (4.2.3.1)",))
    if vehicle_head_contact:
        return ChildSideScore(dummy, 0.0, "head contact with the vehicle",
                              ("head contact with the vehicle: no head points "
                               "(4.2.1)",))
    if _head_contact(dummy, head_peak, crs_head_contact):
        pts = 4.0 * linear_fraction(head_a3ms, *CHILD_SIDE_LIMITS["head_a3ms"])
        return ChildSideScore(dummy, _r3(pts), "head contact with CRS")
    return ChildSideScore(dummy, 4.0, "no head contact with CRS")


@dataclass(frozen=True)
class CopDynamicScore:
    """Dynamic assessment, 24 points."""

    points: float
    frontal: dict[str, ChildFrontalScore]
    side: dict[str, ChildSideScore]
    notes: tuple[str, ...] = ()
    max_points: float = 24.0


def score_cop_dynamic(
    frontal: Sequence[ChildFrontalScore],
    side: Sequence[ChildSideScore],
    ejected: Sequence[str] = (),
    recommendation_valid: bool = True,
) -> CopDynamicScore:
    """Combine the child dummy scores of the frontal and side tests.

    Parameters
    ----------
    frontal, side:
        One score per dummy (Q1.5 and Q3) and test.
    ejected:
        Dummies (``"q1.5"``, ``"q3"``) that were fully or partly ejected
        from their CRS, or whose CRS came partly or wholly loose from a
        vehicle interface: no dynamic points in either test (4.1).
    recommendation_valid:
        False if the manufacturer gave no (appropriate) CRS
        recommendation: no dynamic points (2.1.4).
    """
    f = {s.dummy: s for s in frontal}
    s_ = {s.dummy: s for s in side}
    if len(f) != len(frontal) or len(s_) != len(side):
        raise ValueError("One score per dummy and test.")
    for d in ejected:
        _dummy(d)
    notes = []
    total = 0.0
    for d in sorted(set(f) | set(s_)):
        if d in ejected:
            notes.append(f"{d}: ejection or CRS released, 0 dynamic points (4.1)")
            continue
        total += (f[d].points if d in f else 0.0) + (s_[d].points if d in s_ else 0.0)
    if not recommendation_valid:
        notes.append("no valid CRS recommendation: no dynamic points (2.1.4)")
        total = 0.0
    return CopDynamicScore(_r3(total), f, s_, tuple(notes))


# --- CRS installation -------------------------------------------------------


@dataclass(frozen=True)
class CrsInstallation:
    """Installation result of one CRS over its eligible seating positions."""

    name: str
    eligible_positions: int
    """Ti: eligible seating positions in which the CRS was fitted."""
    failed: int = 0
    """Fi: failed installations."""
    exempt: bool = False
    """Exempted for all seating positions (single seat row cars):
    excluded from the average (3.7.5)."""


@dataclass(frozen=True)
class CrsInstallationScore:
    points: float
    """0-12 (0-10 without a recommendation)."""
    installation_list: float
    """0-10."""
    recommended: float
    """0-2."""
    crs_scores: dict[str, float]
    """CRSi = (Ti - Fi) / Ti per CRS."""
    halved: bool
    max_points: float = 12.0


def _crs_i(c: CrsInstallation) -> float:
    if c.eligible_positions < 0 or not 0 <= c.failed <= max(c.eligible_positions, 0):
        raise ValueError(f"{c.name}: need 0 <= failed <= eligible_positions.")
    if c.eligible_positions == 0:
        return 0.0                                   # 3.7.3: zero points
    return (c.eligible_positions - c.failed) / c.eligible_positions


def score_crs_installation(
    installation_list: Sequence[CrsInstallation],
    recommended: Sequence[CrsInstallation] | None = None,
    coverage_requirements_met: bool = True,
) -> CrsInstallationScore:
    """CRS installation score, 12 points (Annexure V 3.7).

    Parameters
    ----------
    installation_list:
        Every CRS on the original installation list. CRSi = (Ti - Fi) /
        Ti; their average (exempt CRS excluded) times 10 points.
    recommended:
        The two manufacturer-recommended CRS: their average CRSi times 2
        points. None if there is no recommendation (maximum 10 points).
    coverage_requirements_met:
        False if not every passenger seating position (front row
        excepted) accommodates a group 0+ and a group I CRS from the
        list, or not every group 0-III is accommodated somewhere: the
        installation score is halved (3.2.9).
    """
    scores = {c.name: _crs_i(c) for c in installation_list}
    counted = [scores[c.name] for c in installation_list if not c.exempt]
    list_points = 10.0 * (sum(counted) / len(counted)) if counted else 0.0
    rec_points = 0.0
    if recommended:
        rec = [_crs_i(c) for c in recommended]
        rec_points = 2.0 * sum(rec) / len(rec)
        scores.update({f"recommended: {c.name}": v for c, v in zip(recommended, rec)})
    total = list_points + rec_points
    if not coverage_requirements_met:
        total /= 2.0
    return CrsInstallationScore(_r3(total), _r3(list_points), _r3(rec_points), scores,
                                not coverage_requirements_met,
                                12.0 if recommended else 10.0)


# --- Vehicle based assessments --------------------------------------------

AirbagState = Literal["label_not_ok", "label_only", "manual", "automatic"]

AIRBAG_POINTS: dict[str, float] = {
    "label_not_ok": 0.0, "label_only": 1.0, "manual": 3.0, "automatic": 4.0,
}
"""Passenger airbag warning marking and disabling (5.6): label not OK 0;
label OK, no disconnection 1; manual disconnection 3; automatic 4 (the
label is a precondition)."""


@dataclass(frozen=True)
class VehicleBasedAssessment:
    """Inputs of the vehicle based assessments (Annexure V Section 5)."""

    three_point_belts: bool = True
    """5.1: every passenger seat has a 3-point automatic belt meeting the
    regulations; otherwise all vehicle based points are 0."""
    gabarit_all_seats: bool = False
    """5.2.2 a) to e) met on all passenger seats: 1 point."""
    gabarit_handbook_and_airbag: bool = False
    """5.2.2 f) to h) met as well (handbook seat suitability, airbag
    statements, airbag disabling standard): 1 more point."""
    three_simultaneous: bool = False
    """5.3.1: three seating positions take installation-list CRS (groups
    0-III) at the same time: 1 point (not for two-seaters)."""
    three_simultaneous_isize: bool = False
    """5.3.1.3: three seating positions take i-Size CRS at the same time:
    1 point (not for two-seaters)."""
    isofix_un: bool = False
    """5.4 A): ISOFIX to UN regulation (precondition, 0 points)."""
    isofix_marked: bool = False
    """5.4 B): anchorages and pairs marked: 1 point (needs A)."""
    isofix_isize_ready: bool = False
    """5.4 C): i-Size ready: 1 more point (needs A and B)."""
    two_largest_isofix: bool = False
    """5.5: two seating positions take the largest rearward facing ISOFIX
    CRS (two-seaters: the passenger seat): 1 point."""
    airbag: AirbagState = "label_not_ok"
    """5.6: passenger airbag warning marking and disabling."""
    integrated_crs: bool = False
    """5.7.1: integrated CRS as standard: 1 point."""
    integrated_crs_group_1_3: bool = False
    """5.7.2: a group I-III integrated CRS as standard: 1 more point."""


@dataclass(frozen=True)
class VehicleBasedScore:
    points: float
    items: dict[str, float]
    notes: tuple[str, ...]
    max_points: float


def score_vehicle_based(
    v: VehicleBasedAssessment, two_seater: bool = False
) -> VehicleBasedScore:
    """Vehicle based assessment score: 13 points, or 10 for vehicles
    without rear seats (Annexure V Section 5 and 6.1.3, Annexure VIII
    4.2)."""
    if v.airbag not in AIRBAG_POINTS:
        raise ValueError(f"airbag must be one of {sorted(AIRBAG_POINTS)}.")
    notes: list[str] = []
    isofix = 0.0
    if v.isofix_un and v.isofix_marked:
        isofix = 1.0 + (1.0 if v.isofix_isize_ready else 0.0)
    items = {
        "gabarit": float(v.gabarit_all_seats) + (
            0.0 if two_seater else float(v.gabarit_all_seats
                                         and v.gabarit_handbook_and_airbag)),
        "three_simultaneous": 0.0 if two_seater else float(v.three_simultaneous)
        + float(v.three_simultaneous_isize),
        "isofix_usability": isofix,
        "two_largest_isofix": float(v.two_largest_isofix),
        "airbag": AIRBAG_POINTS[v.airbag],
        "integrated_crs": float(v.integrated_crs) + float(
            v.integrated_crs and v.integrated_crs_group_1_3),
    }
    max_points = 10.0 if two_seater else 13.0
    if not v.three_point_belts:
        notes.append("a passenger seat without a compliant 3-point belt: "
                     "0 points (5.1)")
        items = dict.fromkeys(items, 0.0)
    elif two_seater and v.airbag in ("label_not_ok", "label_only"):
        notes.append("two-seater with a passenger airbag and no deactivation: "
                     "0 points (6.1.4)")
        items = dict.fromkeys(items, 0.0)
    return VehicleBasedScore(_r3(sum(items.values())), items, tuple(notes), max_points)


# --- Total -------------------------------------------------------------------


@dataclass(frozen=True)
class CopScore:
    """Child occupant protection score and stars."""

    points: float
    max_points: float
    stars: int
    dynamic: CopDynamicScore | None
    installation: CrsInstallationScore
    vehicle_based: VehicleBasedScore
    two_seater: bool
    notes: tuple[str, ...] = field(default=())
    protocol: str = PROTOCOL
    """Rules that produced the result (`crashmetrics.bncap.PROTOCOL`)."""

    def summary(self) -> str:
        """A short text report."""
        lines = [f"Bharat NCAP child occupant protection: {self.points:.3f} / "
                 f"{self.max_points:g} -> {self.stars} stars"]
        if self.dynamic is not None:
            d = self.dynamic
            lines.append(f"  Dynamic          {d.points:7.3f} / 24")
            for name, f in d.frontal.items():
                lines.append(f"    frontal {name:4} {f.points:6.3f} / 8  (head "
                             f"{f.head:.3f} [{f.head_governing}], neck {f.neck:.3f}, "
                             f"chest {f.chest:.3f})")
            for name, s in d.side.items():
                lines.append(f"    side    {name:4} {s.points:6.3f} / 4  "
                             f"[{s.head_governing}]")
            lines += [f"    note: {n}" for n in d.notes]
        i = self.installation
        lines.append(f"  CRS installation {i.points:7.3f} / {i.max_points:g}  (list "
                     f"{i.installation_list:.3f}, recommended {i.recommended:.3f}"
                     f"{', halved' if i.halved else ''})")
        v = self.vehicle_based
        lines.append(f"  Vehicle based    {v.points:7.3f} / {v.max_points:g}  (" +
                     ", ".join(f"{k} {p:g}" for k, p in v.items.items()) + ")")
        lines += [f"    note: {n}" for n in v.notes]
        return "\n".join(lines)


def score_cop(
    installation: CrsInstallationScore,
    vehicle_based: VehicleBasedScore,
    dynamic: CopDynamicScore | None = None,
    two_seater: bool = False,
    edition: int = EDITION,
) -> CopScore:
    """Child occupant protection total and stars (AIS-197 2023).

    49 points (dynamic 24, installation 12, vehicle based 13) with the
    star thresholds 41 / 35 / 27 / 18 / 9; two-seaters (no dynamic
    assessment) 22 points with 20 / 17 / 13 / 9 / 5 (Annexure VIII 4.3).
    """
    protocol = check_edition(edition)
    if two_seater and dynamic is not None:
        raise ValueError("Two-seaters have no dynamic assessment (6.1.2.1).")
    if not two_seater and dynamic is None:
        raise ValueError("Give the dynamic assessment (or two_seater=True).")
    if vehicle_based.max_points != (10.0 if two_seater else 13.0):
        raise ValueError("Score the vehicle based assessment with the same "
                         "two_seater setting.")
    points = _r3(installation.points + vehicle_based.points
                 + (dynamic.points if dynamic else 0.0))
    return CopScore(points, 22.0 if two_seater else 49.0,
                    cop_stars(points, two_seater), dynamic, installation,
                    vehicle_based, two_seater, protocol=protocol)
