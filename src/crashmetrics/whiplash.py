"""Rear impact (whiplash): BioRID criteria and the 2026 Euro NCAP / ANCAP
rear impact score.

Follows the Crash Protection Rear Impact protocol v1.2 (August 2026,
2026-2028) for the points and limits and Euro NCAP CP 005 v1.4.1 for the
criteria. The rear impact score is out of 5 points:

- Front seat, 4 points: static geometry 1 (head restraint height and
  backset) and dynamic 3 (sled tests with the medium and high severity
  pulses, 1.5 points each: NIC, upper neck shear Fx and tension Fz,
  0.5 points each).
- Rear seats, 1 point: head restraint geometry and non-use position.

Functions:

- `nic`: Neck Injury Criterion from T1 and head x accelerations.
- `nkm`: Nkm neck criterion from upper neck Fx and My.
- `score_whiplash_pulse`: Points of one sled test (1.5), with capping.
- `front_geometry_score`: Static geometry of a front seat (0-1).
- `score_front_seat`: The 4-point front seat score.
- `rear_seat_score`, `score_rear_seats`: The 1-point rear score.
- `score_whiplash`: The 5-point total.

Units: accelerations m/s^2 (or g with ``units="g"``), forces N, moments
N m, heights and backsets mm, velocities m/s, times ms, angles deg.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

from crashmetrics._scoring import linear_fraction

__all__ = [
    "NKM_INTERCEPTS",
    "PULSE_POINTS",
    "WHIPLASH_CAPPING",
    "WHIPLASH_LIMITS",
    "FrontSeatScore",
    "NkmResult",
    "PulseScore",
    "RearSeat",
    "WhiplashScore",
    "front_geometry_score",
    "nic",
    "nkm",
    "rear_backset_limit",
    "rear_seat_score",
    "score_front_seat",
    "score_rear_seats",
    "score_whiplash",
    "score_whiplash_pulse",
]

G = 9.81
Pulse = Literal["medium", "high"]

# --- Criteria ----------------------------------------------------------------


def _signals(time: ArrayLike, *signals: ArrayLike) -> tuple[np.ndarray, ...]:
    t = np.asarray(time, dtype=float)
    out = [np.asarray(s, dtype=float) for s in signals]
    if t.ndim != 1 or len(t) < 2 or any(s.shape != t.shape for s in out):
        raise ValueError("time and signals must be 1D arrays of equal length.")
    if not all(np.all(np.isfinite(a)) for a in (t, *out)):
        raise ValueError("Inputs must contain only finite values.")
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time values must be strictly increasing.")
    return (t, *out)


def _window(t: np.ndarray, t_end: float | None) -> np.ndarray:
    if t_end is None:
        return np.ones_like(t, dtype=bool)
    mask = t <= t_end
    if not mask.any():
        raise ValueError("t_end is before the first sample.")
    return mask


def nic(
    time: ArrayLike,
    t1_ax: ArrayLike,
    head_ax: ArrayLike,
    t_end: float | None = None,
    units: Literal["m/s^2", "g"] = "m/s^2",
) -> float:
    """Return the Neck Injury Criterion, m^2/s^2 (CP 005 3.2.6).

    ``NIC(t) = 0.2 a_rel(t) + v_rel(t)^2`` with ``a_rel = a_T1,x -
    a_head,x`` and ``v_rel`` its time integral; the maximum is taken up
    to ``t_end`` (head restraint contact end, T-HRC(end), in s).

    Parameters
    ----------
    time:
        Time in s, starting at T-zero.
    t1_ax, head_ax:
        T1 x acceleration (mean of left and right) and head CoG x
        acceleration, CFC 60.
    t_end:
        End of the evaluation, s (T-HRC(end)); default: whole record.
    units:
        Unit of the accelerations.
    """
    if units not in ("m/s^2", "g"):
        raise ValueError('units must be "m/s^2" or "g".')
    t, a_t1, a_head = _signals(time, t1_ax, head_ax)
    scale = G if units == "g" else 1.0
    a_rel = (a_t1 - a_head) * scale
    v_rel = np.concatenate([[0.0], np.cumsum(np.diff(t) * 0.5 * (a_rel[1:]
                                                                 + a_rel[:-1]))])
    values = 0.2 * a_rel + v_rel**2
    return float(values[_window(t, t_end)].max())


NKM_INTERCEPTS: dict[str, float] = {
    "flexion": 88.1, "extension": -47.5, "shear_anterior": 845.0,
    "shear_posterior": -845.0,
}
"""Nkm intercepts (CP 005 3.2.7): moments N m, forces N."""

OC_DISTANCE = 0.01778
"""Distance from the upper neck load cell to the occipital condyle, m."""


@dataclass(frozen=True)
class NkmResult:
    value: float
    """Largest of the four Nkm combinations."""
    mode: str
    """``"nfa"``, ``"nfp"``, ``"nea"`` or ``"nep"``: flexion /
    extension with anterior / posterior shear."""
    time: float
    """Time of the maximum, s."""


def nkm(
    time: ArrayLike,
    fx: ArrayLike,
    my: ArrayLike,
    t_end: float | None = None,
) -> NkmResult:
    """Return Nkm (CP 005 3.2.7) from upper neck Fx (N) and My (N m).

    ``M_OCy = My - 0.01778 Fx``; each of the four combinations
    ``M_OCy / M_int + Fx / F_int`` (flexion 88.1 or extension -47.5 N m;
    anterior 845 or posterior -845 N) counts only where both the moment
    and the force have that combination's sign (the other terms set to
    zero, an AND condition). Evaluated up to ``t_end`` (T-HRC(end), s).
    """
    t, f, m = _signals(time, fx, my)
    moc = m - OC_DISTANCE * f
    mask = _window(t, t_end)
    i = NKM_INTERCEPTS
    combos = {
        "nfa": (moc >= 0) & (f >= 0),
        "nfp": (moc >= 0) & (f < 0),
        "nea": (moc < 0) & (f >= 0),
        "nep": (moc < 0) & (f < 0),
    }
    best = ("nfa", 0.0, float(t[0]))
    for mode, active in combos.items():
        mint = i["flexion"] if mode[1] == "f" else i["extension"]
        fint = i["shear_anterior"] if mode[2] == "a" else i["shear_posterior"]
        values = np.where(active & mask, moc / mint + f / fint, 0.0)
        k = int(np.argmax(values))
        if values[k] > best[1]:
            best = (mode, float(values[k]), float(t[k]))
    return NkmResult(best[1], best[0], best[2])


# --- Dynamic scoring --------------------------------------------------------

WHIPLASH_LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "medium": {"nic": (11.0, 24.0), "upper_neck_fx": (30.0, 190.0),
               "upper_neck_fz": (360.0, 750.0)},
    "high": {"nic": (13.0, 23.0), "upper_neck_fx": (30.0, 210.0),
             "upper_neck_fz": (470.0, 770.0)},
}
"""Scored criteria per pulse: (higher, lower) performance limits. NIC
m^2/s^2, upper neck shear +Fx and tension Fz in N; 0.5 points each,
linear between the limits."""

WHIPLASH_CAPPING: dict[str, dict[str, float]] = {
    "medium": {
        "nic": 27.0, "rebound_velocity": 5.20,
        "upper_neck_fx": 290.0, "upper_neck_fx_negative": 360.0,
        "upper_neck_fz": 900.0,
        "upper_neck_my_extension": 30.0, "upper_neck_my_flexion": 30.0,
        "lower_neck_fx": 360.0,
        "lower_neck_my_extension": 30.0, "lower_neck_my_flexion": 30.0,
    },
    "high": {
        "nic": 25.5, "nkm": 0.78, "rebound_velocity": 6.0,
        "upper_neck_fx": 364.0, "upper_neck_fx_negative": 360.0,
        "upper_neck_fz": 1024.0,
        "upper_neck_my_extension": 30.0, "upper_neck_my_flexion": 30.0,
        "lower_neck_fx": 360.0,
        "lower_neck_my_extension": 30.0, "lower_neck_my_flexion": 30.0,
        "seatback_deflection": 32.0,
    },
}
"""Capping limits per pulse: reaching any gives no points for that pulse.
Values are compared as magnitudes (negative shear, moments)."""

T1_THRC_CAPPING: dict[str, tuple[float, float]] = {
    "medium": (15.55, 92.0), "high": (17.80, 92.0),
}
"""T1 acceleration (g) and head restraint contact start T-HRC (ms):
capping applies only if both are reached."""

PULSE_POINTS = 1.5
"""Points per pulse (3 criteria x 0.5)."""


@dataclass(frozen=True)
class PulseScore:
    pulse: str
    points: float
    """0-1.5; 0 if capped."""
    criteria: dict[str, float]
    """Points per scored criterion before capping."""
    capped: tuple[str, ...]
    """Capping reasons (empty if none)."""


def score_whiplash_pulse(pulse: Pulse, values: Mapping[str, float]) -> PulseScore:
    """Score one front seat sled test.

    Parameters
    ----------
    pulse:
        ``"medium"`` or ``"high"`` severity.
    values:
        ``"nic"``, ``"upper_neck_fx"`` (positive shear, N),
        ``"upper_neck_fz"`` (tension, N); optionally the capping
        parameters (`WHIPLASH_CAPPING` keys), ``"t1"`` (g) and
        ``"t_hrc_start"`` (ms). Nkm and seatback deflection are only
        used for the high pulse and ignored for the medium one.
    """
    if pulse not in WHIPLASH_LIMITS:
        raise ValueError('pulse must be "medium" or "high".')
    known = set(WHIPLASH_LIMITS[pulse]) | set(WHIPLASH_CAPPING["high"]) | {
        "t1", "t_hrc_start"}            # high-only items are ignored for "medium"
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Unknown values for the {pulse} pulse: {sorted(unknown)}.")
    for name, v in values.items():
        if not math.isfinite(v):
            raise ValueError(f"{name} must be finite.")
    criteria = {}
    for name, (hpl, lpl) in WHIPLASH_LIMITS[pulse].items():
        if name not in values:
            raise ValueError(f"Missing value for {name!r}.")
        criteria[name] = 0.5 * linear_fraction(max(values[name], 0.0), hpl, lpl)
    capped = [name for name, lim in WHIPLASH_CAPPING[pulse].items()
              if name in values and abs(values[name]) >= lim]
    t1_cap, thrc_cap = T1_THRC_CAPPING[pulse]
    if ("t1" in values and "t_hrc_start" in values
            and values["t1"] >= t1_cap and values["t_hrc_start"] >= thrc_cap):
        capped.append("t1 and t_hrc_start")
    points = 0.0 if capped else sum(criteria.values())
    return PulseScore(pulse, points, criteria, tuple(capped))


# --- Front seat ---------------------------------------------------------------


def front_geometry_score(effective_height: float, backset: float) -> float:
    """Static geometry of a front seat in the test position, 0-1.

    The worse of the effective head restraint height (1 at 825 mm or
    more, 0 at 790 mm or less, linear between) and the backset (1 below
    45 mm, 0 at 45 mm or more).
    """
    for name, v in (("effective_height", effective_height), ("backset", backset)):
        if not math.isfinite(v):
            raise ValueError(f"{name} must be finite.")
    height = 1.0 - linear_fraction(effective_height, 790.0, 825.0)
    backset_ok = 1.0 if backset < 45.0 else 0.0
    return min(height, backset_ok)


@dataclass(frozen=True)
class FrontSeatScore:
    points: float
    """0-4."""
    geometry: float
    """0-1."""
    test_position: float
    """Geometry in the test position, 0-1."""
    lowest_rearmost: float
    """Lowest and rearmost credit, 0-0.5."""
    dynamic: float
    """0-3 after modifiers."""
    medium: PulseScore
    high: PulseScore
    notes: tuple[str, ...] = ()
    max_points: float = 4.0


def score_front_seat(
    medium: PulseScore,
    high: PulseScore,
    effective_height: float,
    backset: float,
    lowest_rearmost: Sequence[tuple[float, float]] = (),
    front_seats: int = 2,
    automatic_head_restraint: bool = False,
    head_restraint_structure_ok: bool = True,
    dummy_loading: bool = False,
) -> FrontSeatScore:
    """The 4-point front seat score.

    Parameters
    ----------
    medium, high:
        The two pulse scores.
    effective_height, backset:
        Head restraint geometry in the test position, mm.
    lowest_rearmost:
        (effective height, backset) in the lowest and rearmost position
        of each front seat; a seat meeting 790 mm and 70 mm earns
        0.5 / ``front_seats``. Automatically adjusting head restraints
        earn it only with a raw dynamic score above 1.50.
    front_seats:
        Number of front seats, n.
    head_restraint_structure_ok:
        False if the head restraint structure requirement (120 mm
        cylinder) is not met: geometry 0.
    dummy_loading:
        Seat design exploiting the dummy or loading other body areas
        unfavourably: -1 point.

    Notes
    -----
    Geometry is the test position score plus the lowest and rearmost
    credit, at most 1 point (see the protocol notes).
    """
    if medium.pulse != "medium" or high.pulse != "high":
        raise ValueError("Give the medium and the high pulse scores.")
    if front_seats < 1:
        raise ValueError("front_seats must be at least 1.")
    notes: list[str] = []
    raw_dynamic = medium.points + high.points
    test_position = front_geometry_score(effective_height, backset)
    credit = 0.0
    for h, b in lowest_rearmost:
        if h >= 790.0 and b <= 70.0:
            credit += 0.5 / front_seats
    if automatic_head_restraint and raw_dynamic <= 1.5 and credit > 0:
        credit = 0.0
        notes.append("automatic head restraint: lowest/rearmost credit needs a raw "
                     "dynamic score above 1.50")
    geometry = min(1.0, test_position + credit)
    if not head_restraint_structure_ok:
        geometry = 0.0
        notes.append("head restraint structure requirement not met: geometry 0")
    dynamic = raw_dynamic
    if dummy_loading:
        dynamic = max(0.0, dynamic - 1.0)
        notes.append("dummy loading modifier: -1 point")
    return FrontSeatScore(round(geometry + dynamic, 3), round(geometry, 3),
                          round(test_position, 3), round(credit, 3),
                          round(dynamic, 3), medium, high, tuple(notes))


# --- Rear seats -------------------------------------------------------------


def rear_backset_limit(torso_angle: float) -> float:
    """Rear seat backset limit, mm: 7.128 x torso angle (deg) + 153."""
    if not math.isfinite(torso_angle):
        raise ValueError("torso_angle must be finite.")
    return 7.128 * torso_angle + 153.0


@dataclass(frozen=True)
class RearSeat:
    """Rear outboard seat head restraint measurements."""

    height_lowest: float
    """Effective height in the lowest position, mm."""
    height_highest: float
    """Effective height in the highest position, mm."""
    backset_mid: float
    """Backset in the mid position, mm."""
    backset_worst: float
    """Backset in the worst-case position, mm."""
    torso_angle: float
    """Torso angle, deg (for the backset limit)."""
    roofline_gap: float | None = None
    """Gap to the roofline / headliner at the highest position, mm, if
    the roofline prevents the heights (at most 50 mm is accepted)."""
    non_use_position: bool = False
    """Non-use position accepted (automatic return, rotation > 60 deg,
    torso line change > 10 deg, or the discomfort metric)."""


def rear_seat_score(seat: RearSeat) -> float:
    """Score of one rear outboard seat, 0-1: effective height 0.375,
    backset mid 0.25 and worst-case 0.125 (only with the height), and
    non-use position 0.25 (only with geometry above 0)."""
    height_ok = (seat.height_lowest >= 720.0 and seat.height_highest >= 770.0) or (
        seat.roofline_gap is not None and seat.roofline_gap <= 50.0)
    limit = rear_backset_limit(seat.torso_angle)
    points = 0.0
    if height_ok:
        points += 0.375
        if seat.backset_mid <= limit:
            points += 0.25
        if seat.backset_worst <= limit:
            points += 0.125
    if seat.non_use_position and points > 0:
        points += 0.25
    return points


def score_rear_seats(
    seats: Sequence[RearSeat],
    centre_seat_r17: bool = True,
) -> float:
    """Rear score, 0-1: the outboard seat scores scaled to 1 point (their
    mean). A row scores only if its centre seat meets UN R17 head
    restraint requirements as standard. For symmetric seats give one
    seat twice."""
    if not seats:
        raise ValueError("Give at least one rear outboard seat.")
    if not centre_seat_r17:
        return 0.0
    return round(sum(rear_seat_score(s) for s in seats) / len(seats), 3)


# --- Total -----------------------------------------------------------------


@dataclass(frozen=True)
class WhiplashScore:
    points: float
    front: FrontSeatScore
    rear: float
    max_points: float = 5.0
    notes: tuple[str, ...] = field(default=())

    def summary(self) -> str:
        f = self.front
        lines = [f"Rear impact (whiplash): {self.points:.3f} / 5",
                 f"  Front seat {f.points:.3f} / 4: geometry {f.geometry:.3f} (test "
                 f"position {f.test_position:.3f}, lowest/rearmost "
                 f"{f.lowest_rearmost:.3f}), dynamic {f.dynamic:.3f}"]
        for p in (f.medium, f.high):
            crit = ", ".join(f"{k} {v:.3f}" for k, v in p.criteria.items())
            cap = f"  CAPPED: {', '.join(p.capped)}" if p.capped else ""
            lines.append(f"    {p.pulse:6} pulse {p.points:.3f} / 1.5 ({crit}){cap}")
        lines += [f"    note: {n}" for n in f.notes]
        lines.append(f"  Rear seats {self.rear:.3f} / 1")
        return "\n".join(lines)


def score_whiplash(front: FrontSeatScore, rear: float) -> WhiplashScore:
    """The 5-point rear impact score (front 4 + rear 1)."""
    if not 0.0 <= rear <= 1.0:
        raise ValueError("rear must be between 0 and 1.")
    return WhiplashScore(round(front.points + rear, 3), front, rear)
