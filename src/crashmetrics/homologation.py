"""Homologation compliance checks: UN R94, R95, R135 and post-crash
electrical safety (India and Europe).

India's AIS standards follow these UN Regulations: AIS-098 (offset
frontal) follows R94 and AIS-099 (side) follows R95. Check the AIS
revision in force for any differences.

Functions:

- `check_r94_occupant`, `check_r94_vehicle`: UN R94 (05 series,
  56 km/h 40 % offset deformable barrier, Hybrid III 50th male in both
  front seats), paragraphs 5.2.1 to 5.2.7.
- `check_r95_occupant`, `check_r95_vehicle`: UN R95 lateral collision
  (ES-2 dummy), paragraphs 5.2 and 5.3.
- `check_r135_occupant`, `check_r135_vehicle`: UN R135 pole side
  impact (01 series, 32 km/h at 75 deg, WorldSID 50th male), paragraphs
  5.3 to 5.5.
- `check_electrical_safety`: Post-crash electrical safety (R94
  5.2.8, R137 5.2.8, R95 5.3.7): protection against electric shock per
  high-voltage bus, electrolyte leakage, REESS retention, fire.
- `combine`: One result from several (both front occupants and the
  vehicle, for example).

Every check returns a `ComplianceResult`: per requirement the value,
limit, utilisation (value / limit), pass/fail and clause. A requirement
whose value is not given is listed as not assessed and never counts as
passed: ``complete`` tells whether everything was assessed.

Units: forces N, moments N m, deflections and displacements mm, VC m/s,
accelerations g, voltages V, resistances ohm, energies J. Peak values
are magnitudes unless stated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from numpy.typing import ArrayLike

from crashmetrics.acceleration import clip_3ms
from crashmetrics.lower_extremity import femur_force_criterion
from crashmetrics.neck import neck_force_criterion

__all__ = [
    "ComplianceResult",
    "ElectricalLimits",
    "HVBus",
    "R94_LIMITS",
    "R95_LIMITS",
    "R135_LIMITS",
    "Requirement",
    "check_electrical_safety",
    "check_r94_occupant",
    "check_r94_vehicle",
    "check_r95_occupant",
    "check_r95_vehicle",
    "check_r135_occupant",
    "check_r135_vehicle",
    "combine",
]

Series = tuple[ArrayLike, ArrayLike]
"""(time in s, signal)."""

R94_LIMITS: dict[str, float] = {
    "hpc": 1000.0,                 # 5.2.1.1
    "head_a3ms": 80.0,             # 5.2.1.1, cumulative, rebound excluded
    "neck_extension": 57.0,        # 5.2.1.3, N m
    "thcc": 42.0,                  # 5.2.1.4, mm
    "vc": 1.0,                     # 5.2.1.5, m/s
    "tibia_compression": 8000.0,   # 5.2.1.7, N
    "tibia_index": 1.3,            # 5.2.1.8
    "knee_slider": 15.0,           # 5.2.1.9, mm
    "steering_upward": 80.0,       # 5.2.2, mm
    "steering_rearward": 100.0,    # 5.2.2, mm
    "fuel_leakage_rate": 30.0,     # 5.2.6.1 (05 series), g/min
}
"""UN R94 limits (04 and 05 series). Neck tension and shear (Figures 1
and 2) and the femur force criterion (Figure 3) are force-duration
curves: `crashmetrics.neck.NECK_FORCE_LIMITS` (``"r94_tension"``,
``"r94_shear"``) and `crashmetrics.lower_extremity.FEMUR_FORCE_LIMITS`
(``"r94_hybrid3_50"``)."""

R95_LIMITS: dict[str, float] = {
    "hpc": 1000.0,                 # 5.2.1.1
    "rdc": 42.0,                   # 5.2.1.2 (a), mm
    "vc": 1.0,                     # 5.2.1.2 (b), m/s
    "pspf": 6000.0,                # 5.2.1.3, N
    "apf": 2500.0,                 # 5.2.1.4, N internal (4.5 kN external)
    "fuel_leakage_rate": 30.0,     # 5.3.6, g/min
}
"""UN R95 limits (ES-2 dummy)."""

R135_LIMITS: dict[str, float] = {
    "hic36": 1000.0,                     # 5.3.2.1
    "shoulder_force": 3000.0,            # 5.3.3.1, N
    "thorax_rib_deflection": 55.0,       # 5.3.4.1, mm
    "abdominal_rib_deflection": 65.0,    # 5.3.5.1, mm
    "lower_spine_3ms": 75.0,             # 5.3.5.2, g, cumulative 3 ms
    "pubic_force": 3360.0,               # 5.3.6.1, N
    "fuel_leakage_first_5_min": 142.0,   # 5.5.1.1, g in total
    "fuel_leakage_rate_5_30_min": 28.0,  # 5.5.1.2, g/min
}
"""UN R135 limits (01 series, WorldSID 50th male)."""


# --- Results ---------------------------------------------------------------


@dataclass(frozen=True)
class Requirement:
    """One requirement of a regulation and its assessment."""

    name: str
    """Requirement name, e.g. ``"thcc"``."""
    clause: str
    """Paragraph of the regulation."""
    value: float | bool | None
    """Measured value (None if not given)."""
    limit: float | bool | None
    """Limit (the required state for yes/no requirements)."""
    utilisation: float | None
    """value / limit for numeric limits (1.0 = at the limit); for
    force-duration curves the largest ratio of the curve to the limit."""
    passed: bool | None
    """True or False, or None if not assessed."""
    unit: str = ""
    note: str = ""


@dataclass(frozen=True)
class ComplianceResult:
    """Result of a compliance check."""

    regulation: str
    """For example ``"UN R94 (driver)"``."""
    requirements: dict[str, Requirement]
    """Every requirement, assessed or not."""
    notes: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        """True if every assessed requirement passed. Check ``complete``
        as well: requirements that were not assessed are not included."""
        return all(r.passed for r in self.requirements.values()
                   if r.passed is not None)

    @property
    def complete(self) -> bool:
        """True if every requirement was assessed."""
        return all(r.passed is not None for r in self.requirements.values())

    @property
    def failures(self) -> list[str]:
        """Requirements that failed."""
        return [k for k, r in self.requirements.items() if r.passed is False]

    @property
    def not_assessed(self) -> list[str]:
        """Requirements without a value."""
        return [k for k, r in self.requirements.items() if r.passed is None]

    @property
    def worst(self) -> str | None:
        """Assessed numeric requirement with the highest utilisation."""
        rated = {k: r.utilisation for k, r in self.requirements.items()
                 if r.utilisation is not None}
        return max(rated, key=lambda k: rated[k]) if rated else None

    def summary(self) -> str:
        """A text table: one line per requirement."""
        status = ("PASS" if self.passed else "FAIL") + (
            "" if self.complete else f" ({len(self.not_assessed)} not assessed)")
        lines = [f"{self.regulation}: {status}"]
        width = max([len(n) for n in self.requirements] + [20])
        for r in self.requirements.values():
            if r.passed is None:
                lines.append(f"  {r.name:{width}} {'-':>10}  not assessed   "
                             f"[{r.clause}]")
                continue
            if r.value is None:                       # satisfied without a value
                shown, lim = "-", ""
            elif isinstance(r.value, bool) or isinstance(r.limit, bool):
                shown, lim = ("yes" if r.value else "no"), (
                    "required" if r.limit else "not allowed")
            else:
                shown = f"{r.value:.4g}"
                lim = f"<= {r.limit:.4g}" if r.limit is not None else ""
            util = f"{r.utilisation:6.0%}" if r.utilisation is not None else " " * 6
            mark = "ok  " if r.passed else "FAIL"
            lines.append(f"  {r.name:{width}} {shown:>10} {r.unit:5} {lim:12} {util} "
                         f"{mark} [{r.clause}]{'  ' + r.note if r.note else ''}")
        lines.extend(f"  Note: {n}" for n in self.notes)
        return "\n".join(lines)


def combine(regulation: str, *results: ComplianceResult) -> ComplianceResult:
    """Return one result from several, with requirement names prefixed
    by each part's name in brackets (``"driver: thcc"``)."""
    merged: dict[str, Requirement] = {}
    notes: list[str] = []
    for res in results:
        part = res.regulation.split("(")[-1].rstrip(")") if "(" in res.regulation \
            else res.regulation
        for key, req in res.requirements.items():
            name = f"{part}: {key}"
            merged[name] = Requirement(name, req.clause, req.value, req.limit,
                                       req.utilisation, req.passed, req.unit, req.note)
        notes.extend(f"{part}: {n}" for n in res.notes)
    return ComplianceResult(regulation, merged, tuple(notes))


# --- Building blocks ---------------------------------------------------------


def _upper(name: str, clause: str, value: float | None, limit: float,
           unit: str = "", note: str = "") -> Requirement:
    """Numeric requirement: |value| <= limit."""
    if value is None:
        return Requirement(name, clause, None, limit, None, None, unit, note)
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite.")
    util = abs(v) / limit
    return Requirement(name, clause, abs(v), limit, util, util <= 1.0, unit, note)


def _state(name: str, clause: str, value: bool | None, required: bool,
           note: str = "") -> Requirement:
    """Yes/no requirement: value must equal ``required``."""
    if value is None:
        return Requirement(name, clause, None, required, None, None, "", note)
    return Requirement(name, clause, bool(value), required, None,
                       bool(value) == required, "", note)


def _curve(name: str, clause: str, result: object | None, limit_label: str,
           unit: str = "N") -> Requirement:
    """Force-duration curve requirement from an exceedance result."""
    if result is None:
        return Requirement(name, clause, None, None, None, None, unit, limit_label)
    peak = float(getattr(result, "peak", getattr(result, "peak_compression", math.nan)))
    util = float(getattr(result, "utilisation"))
    return Requirement(name, clause, peak, None, util, util <= 1.0, unit,
                       f"{limit_label}; peak shown")


def _pair(x: object) -> tuple[ArrayLike, ArrayLike]:
    """(time, signal) from a 2-tuple or list."""
    if not isinstance(x, (tuple, list)) or len(x) != 2:
        raise ValueError("Give a time history as (time, signal) or a result object.")
    return x[0], x[1]


# --- UN R94 / AIS-098 -------------------------------------------------------


def check_r94_occupant(
    hpc: float | None = None,
    head_contact: bool = True,
    head_a3ms: float | None = None,
    neck_tension: Series | object | None = None,
    neck_shear: Series | object | None = None,
    neck_extension: float | None = None,
    thcc: float | None = None,
    vc: float | None = None,
    femur_left: Series | object | None = None,
    femur_right: Series | object | None = None,
    tibia_compression: float | None = None,
    tibia_index: float | None = None,
    knee_slider: float | None = None,
    position: str = "occupant",
) -> ComplianceResult:
    """Check a Hybrid III 50th male against UN R94 5.2.1.

    Parameters
    ----------
    hpc:
        Head performance criterion (HIC over intervals up to 36 ms,
        Annex 4: ``calculate_hic(t, a, window_ms=36)``).
    head_contact:
        False if the head had no contact with the vehicle: the HPC
        requirement is then satisfied (Annex 4, 1.1).
    head_a3ms:
        Resultant head acceleration exceeded for 3 ms cumulatively,
        rebound excluded, g.
    neck_tension, neck_shear:
        (time s, Fz) and (time s, Fx) at the upper neck in N, or the
        result of `crashmetrics.neck.neck_force_criterion`; checked
        against Figures 1 and 2 (cumulative exceedance).
    neck_extension:
        Peak extension bending moment about y, N m.
    thcc:
        Thorax compression criterion (chest deflection), mm.
    vc:
        Viscous criterion, m/s.
    femur_left, femur_right:
        (time s, Fz) femur axial force in N (compression negative), or
        the result of `crashmetrics.lower_extremity.femur_force_criterion`;
        checked against Figure 3.
    tibia_compression:
        Largest tibia compressive force (any tibia), N.
    tibia_index:
        Largest tibia index (top and bottom of each tibia).
    knee_slider:
        Largest knee sliding displacement, mm.
    position:
        Seat name for the report (``"driver"``, ``"passenger"``).
    """
    lim = R94_LIMITS
    notes: list[str] = []

    def neck(x: Series | object | None, key: str) -> object | None:
        if x is None or hasattr(x, "utilisation"):
            return x
        t, f = _pair(x)
        return neck_force_criterion(t, f, key)

    def femur(x: Series | object | None) -> object | None:
        if x is None or hasattr(x, "utilisation"):
            return x
        t, f = _pair(x)
        return femur_force_criterion(t, f, "r94_hybrid3_50")

    if not head_contact:
        hpc_req = Requirement("hpc", "5.2.1.1, Annex 4 1.1", None, lim["hpc"],
                              None, True, "", "no head contact: satisfied")
    else:
        hpc_req = _upper("hpc", "5.2.1.1", hpc, lim["hpc"])
    reqs = [
        hpc_req,
        _upper("head_a3ms", "5.2.1.1", head_a3ms, lim["head_a3ms"], "g"),
        _curve("neck_tension", "5.2.1.2, Fig. 1", neck(neck_tension, "r94_tension"),
               "3.3 kN at 0, 2.9 kN at 35, 1.1 kN at 60 ms"),
        _curve("neck_shear", "5.2.1.2, Fig. 2", neck(neck_shear, "r94_shear"),
               "3.1 kN at 0, 1.5 kN at 25-35, 1.1 kN at 45 ms"),
        _upper("neck_extension", "5.2.1.3", neck_extension,
               lim["neck_extension"], "N m"),
        _upper("thcc", "5.2.1.4", thcc, lim["thcc"], "mm"),
        _upper("vc", "5.2.1.5", vc, lim["vc"], "m/s"),
        _curve("femur_left", "5.2.1.6, Fig. 3", femur(femur_left),
               "9.07 kN at 0, 7.58 kN from 10 ms"),
        _curve("femur_right", "5.2.1.6, Fig. 3", femur(femur_right),
               "9.07 kN at 0, 7.58 kN from 10 ms"),
        _upper("tibia_compression", "5.2.1.7", tibia_compression,
               lim["tibia_compression"], "N"),
        _upper("tibia_index", "5.2.1.8", tibia_index, lim["tibia_index"]),
        _upper("knee_slider", "5.2.1.9", knee_slider, lim["knee_slider"], "mm"),
    ]
    return ComplianceResult(f"UN R94 ({position})", {r.name: r for r in reqs},
                            tuple(notes))


def check_r94_vehicle(
    steering_upward: float | None = None,
    steering_rearward: float | None = None,
    door_opened: bool | None = None,
    doors_unlocked_after: bool | None = None,
    doors_open_without_tools: bool | None = None,
    fuel_leakage_rate: float | None = None,
) -> ComplianceResult:
    """Check the vehicle requirements of UN R94 5.2.2 to 5.2.7.

    Parameters
    ----------
    steering_upward, steering_rearward:
        Residual displacement of the steering wheel hub centre, mm
        (`crashmetrics.intrusion` static values).
    door_opened:
        True if any door opened during the test.
    doors_unlocked_after:
        True if the side doors were unlocked after the impact.
    doors_open_without_tools:
        True if at least one door per row (or seat displacement)
        allows evacuation without tools.
    fuel_leakage_rate:
        Continuous fuel leakage rate after the collision, g/min.
    """
    lim = R94_LIMITS
    reqs = [
        _upper("steering_upward", "5.2.2", steering_upward,
               lim["steering_upward"], "mm"),
        _upper("steering_rearward", "5.2.2", steering_rearward,
               lim["steering_rearward"], "mm"),
        _state("door_opened", "5.2.3", door_opened, False),
        _state("doors_unlocked_after", "5.2.4", doors_unlocked_after, True),
        _state("doors_open_without_tools", "5.2.5.1", doors_open_without_tools, True),
        _upper("fuel_leakage_rate", "5.2.6.1", fuel_leakage_rate,
               lim["fuel_leakage_rate"], "g/min"),
    ]
    return ComplianceResult("UN R94 (vehicle)", {r.name: r for r in reqs})


# --- UN R95 / AIS-099 ------------------------------------------------------


def check_r95_occupant(
    hpc: float | None = None,
    head_contact: bool = True,
    rdc: float | None = None,
    vc: float | None = None,
    pspf: float | None = None,
    apf: float | None = None,
) -> ComplianceResult:
    """Check an ES-2 dummy against UN R95 5.2.1.

    Parameters
    ----------
    hpc:
        Head performance criterion. With ``head_contact=False`` HPC is
        not calculated ("No Head Contact" is recorded) and the
        requirement is satisfied.
    rdc:
        Rib deflection criterion: largest deflection of the three ribs,
        mm.
    vc:
        Largest viscous criterion of the three ribs, m/s.
    pspf:
        Pubic symphysis peak force, N.
    apf:
        Abdominal peak force: sum of the three abdominal load cells, N
        (internal force; 2.5 kN corresponds to 4.5 kN external).
    """
    lim = R95_LIMITS
    if not head_contact:
        hpc_req = Requirement("hpc", "5.2.1.1", None, lim["hpc"], None, True, "",
                              "no head contact: satisfied")
    else:
        hpc_req = _upper("hpc", "5.2.1.1", hpc, lim["hpc"])
    reqs = [
        hpc_req,
        _upper("rdc", "5.2.1.2 (a)", rdc, lim["rdc"], "mm"),
        _upper("vc", "5.2.1.2 (b)", vc, lim["vc"], "m/s"),
        _upper("pspf", "5.2.1.3", pspf, lim["pspf"], "N"),
        _upper("apf", "5.2.1.4", apf, lim["apf"], "N"),
    ]
    return ComplianceResult("UN R95 (driver)", {r.name: r for r in reqs})


def check_r95_vehicle(
    door_opened: bool | None = None,
    non_struck_doors_unlocked: bool | None = None,
    egress_possible: bool | None = None,
    dangerous_detachment: bool | None = None,
    fuel_leakage_rate: float | None = None,
) -> ComplianceResult:
    """Check the vehicle requirements of UN R95 5.3.

    Parameters
    ----------
    door_opened:
        True if any door opened during the test (5.3.1).
    non_struck_doors_unlocked:
        True if the doors on the non-struck side were unlocked after the
        impact (5.3.2).
    egress_possible:
        True if, without tools, doors could be opened, seats tilted and
        the dummy released and removed (5.3.3).
    dangerous_detachment:
        True if interior components came loose and noticeably increase
        the risk of injury from sharp or jagged parts (5.3.4).
    fuel_leakage_rate:
        Continuous fuel leakage rate, g/min (5.3.6).
    """
    reqs = [
        _state("door_opened", "5.3.1", door_opened, False),
        _state("non_struck_doors_unlocked", "5.3.2", non_struck_doors_unlocked, True),
        _state("egress_possible", "5.3.3", egress_possible, True),
        _state("dangerous_detachment", "5.3.4", dangerous_detachment, False),
        _upper("fuel_leakage_rate", "5.3.6", fuel_leakage_rate,
               R95_LIMITS["fuel_leakage_rate"], "g/min"),
    ]
    return ComplianceResult("UN R95 (vehicle)", {r.name: r for r in reqs})


# --- UN R135 -------------------------------------------------------------------


def check_r135_occupant(
    hic36: float | None = None,
    shoulder_force: float | None = None,
    thorax_rib_deflection: float | None = None,
    abdominal_rib_deflection: float | None = None,
    lower_spine: Series | float | None = None,
    pubic_force: float | None = None,
) -> ComplianceResult:
    """Check a WorldSID 50th male against UN R135 5.3 (01 series).

    Parameters
    ----------
    hic36:
        HIC with intervals up to 36 ms (Annex 10).
    shoulder_force:
        Peak lateral shoulder force, N.
    thorax_rib_deflection:
        Largest thorax rib deflection, mm.
    abdominal_rib_deflection:
        Largest abdominal rib deflection, mm.
    lower_spine:
        Lower spine resultant acceleration as (time s, g), or the value
        exceeded for 3 ms cumulatively; must not exceed 75 g except for
        intervals whose cumulative duration is at most 3 ms.
    pubic_force:
        Peak pubic symphysis force, N.
    """
    lim = R135_LIMITS
    spine: float | None
    if lower_spine is None or isinstance(lower_spine, (int, float)):
        spine = lower_spine
    else:
        t, a = _pair(lower_spine)
        spine = clip_3ms(t, a, mode="cumulative")
    reqs = [
        _upper("hic36", "5.3.2.1", hic36, lim["hic36"]),
        _upper("shoulder_force", "5.3.3.1", shoulder_force, lim["shoulder_force"], "N"),
        _upper("thorax_rib_deflection", "5.3.4.1", thorax_rib_deflection,
               lim["thorax_rib_deflection"], "mm"),
        _upper("abdominal_rib_deflection", "5.3.5.1", abdominal_rib_deflection,
               lim["abdominal_rib_deflection"], "mm"),
        _upper("lower_spine_3ms", "5.3.5.2", spine, lim["lower_spine_3ms"], "g"),
        _upper("pubic_force", "5.3.6.1", pubic_force, lim["pubic_force"], "N"),
    ]
    return ComplianceResult("UN R135 (driver)", {r.name: r for r in reqs})


def check_r135_vehicle(
    struck_door_separated: bool | None = None,
    other_doors_held: bool | None = None,
    fuel_leakage_first_5_min: float | None = None,
    fuel_leakage_rate_5_30_min: float | None = None,
) -> ComplianceResult:
    """Check the door and fuel requirements of UN R135 5.4 and 5.5.1.

    Parameters
    ----------
    struck_door_separated:
        True if a side door struck by the pole separated totally from
        the vehicle (5.4.1).
    other_doors_held:
        True if the other doors stayed latched, with latch, striker and
        hinges attached (5.4.2).
    fuel_leakage_first_5_min:
        Liquid fuel spilled in the first 5 minutes after first contact,
        g in total (5.5.1.1).
    fuel_leakage_rate_5_30_min:
        Spillage rate from 5 to 30 minutes, g/min (5.5.1.2).
    """
    lim = R135_LIMITS
    reqs = [
        _state("struck_door_separated", "5.4.1", struck_door_separated, False),
        _state("other_doors_held", "5.4.2", other_doors_held, True),
        _upper("fuel_leakage_first_5_min", "5.5.1.1", fuel_leakage_first_5_min,
               lim["fuel_leakage_first_5_min"], "g"),
        _upper("fuel_leakage_rate_5_30_min", "5.5.1.2", fuel_leakage_rate_5_30_min,
               lim["fuel_leakage_rate_5_30_min"], "g/min"),
    ]
    return ComplianceResult("UN R135 (vehicle)", {r.name: r for r in reqs})


# --- Post-crash electrical safety -----------------------------------------


@dataclass(frozen=True)
class ElectricalLimits:
    """Limits of the post-crash electrical safety requirements.

    The defaults are those of UN R94 (04 and 05 series) 5.2.8 and UN
    R137 (02 series) 5.2.8. Earlier series of some regulations (for
    example older R95 texts) allowed 2.0 J and a 30-minute electrolyte
    window: use ``ElectricalLimits(max_energy=2.0, electrolyte_minutes=30)``
    for those.
    """

    max_dc_voltage: float = 60.0
    """5.2.8.1.1: within 60 s after the impact, V DC."""
    max_ac_voltage: float = 30.0
    """5.2.8.1.1: V AC."""
    max_energy: float = 0.2
    """5.2.8.1.2: total energy and each Y-capacitor energy, J (less
    than)."""
    max_chassis_resistance: float = 0.1
    """5.2.8.1.3: exposed conductive parts to the electrical chassis,
    ohm (less than)."""
    min_isolation_dc: float = 100.0
    """5.2.8.1.4.1: ohm per volt of working voltage, DC buses."""
    min_isolation_ac: float = 500.0
    """5.2.8.1.4.1: ohm per volt, AC buses (and combined buses)."""
    max_electrolyte_outside_percent: float = 7.0
    """5.2.8.2.1: aqueous electrolyte outside the passenger
    compartment, % of the REESS electrolyte."""
    max_electrolyte_outside_litres: float = 5.0
    """5.2.8.2.1: and at most this volume, litres."""
    electrolyte_minutes: float = 60.0
    """Observation period after the impact, minutes (informational)."""


@dataclass(frozen=True)
class HVBus:
    """Post-crash measurements of one high-voltage bus.

    Give what was measured; the bus is protected if at least one of the
    four criteria of 5.2.8.1 is met.
    """

    name: str
    """For example ``"traction DC"``."""
    kind: Literal["DC", "AC", "DC+AC"] = "DC"
    """``"DC+AC"`` for DC and AC buses that are conductively connected."""
    working_voltage: float | None = None
    """Working voltage, V (for the isolation requirement)."""
    voltage: float | None = None
    """Largest of Ub, U1 and U2 measured within 60 s after the impact, V."""
    energy: float | None = None
    """Largest of the total energy TE and the Y-capacitor energies, J."""
    ipxxb: bool | None = None
    """True if protection degree IPXXB is provided."""
    chassis_resistance: float | None = None
    """Largest resistance of exposed conductive parts to the electrical
    chassis, ohm."""
    isolation_resistance: float | None = None
    """Isolation resistance Ri, ohm."""
    ac_part_protected: bool | None = None
    """``"DC+AC"`` buses only: True if the AC part meets the physical
    protection or the voltage criterion (then 100 ohm/V suffices)."""


def _bus_requirement(bus: HVBus, lim: ElectricalLimits) -> Requirement:
    met: list[str] = []
    tried: list[str] = []
    if bus.voltage is not None:
        tried.append("voltage")
        vmax = lim.max_ac_voltage if bus.kind == "AC" else lim.max_dc_voltage
        if bus.kind == "DC+AC":
            vmax = min(lim.max_ac_voltage, lim.max_dc_voltage)
        if abs(bus.voltage) <= vmax:
            met.append(f"voltage {abs(bus.voltage):.4g} V <= {vmax:g} V")
    if bus.energy is not None:
        tried.append("energy")
        if bus.energy < lim.max_energy:
            met.append(f"energy {bus.energy:.4g} J < {lim.max_energy:g} J")
    if bus.ipxxb is not None:
        tried.append("physical protection")
        r_ok = bus.chassis_resistance is not None and \
            bus.chassis_resistance < lim.max_chassis_resistance
        if bus.ipxxb and r_ok:
            met.append(f"IPXXB and chassis resistance {bus.chassis_resistance:.3g} ohm")
    if bus.isolation_resistance is not None:
        tried.append("isolation")
        if bus.working_voltage is None or bus.working_voltage <= 0:
            raise ValueError(f"{bus.name}: the working voltage is needed for the "
                             "isolation requirement.")
        per_volt = bus.isolation_resistance / bus.working_voltage
        if bus.kind == "DC":
            need = lim.min_isolation_dc
        elif bus.kind == "AC":
            need = lim.min_isolation_ac
        else:
            protected = bool(bus.ac_part_protected)
            need = lim.min_isolation_dc if protected else lim.min_isolation_ac
        if per_volt >= need:
            met.append(f"isolation {per_volt:.4g} ohm/V >= {need:g} ohm/V")
    if not tried:
        return Requirement(f"shock_protection[{bus.name}]", "5.2.8.1", None, True,
                           None, None, "", "no measurement given")
    passed = bool(met)
    note = met[0] if met else "none of: " + ", ".join(tried)
    return Requirement(f"shock_protection[{bus.name}]", "5.2.8.1", passed, True,
                       None, passed, "", note)


def check_electrical_safety(
    buses: Sequence[HVBus] = (),
    electrolyte: Literal["aqueous", "non-aqueous"] | None = None,
    electrolyte_in_cabin: bool | None = None,
    electrolyte_outside_percent: float | None = None,
    electrolyte_outside_litres: float | None = None,
    electrolyte_leaked_anywhere: bool | None = None,
    reess_retained: bool | None = None,
    reess_entered_cabin: bool | None = None,
    fire_or_explosion: bool | None = None,
    limits: ElectricalLimits | None = None,
    regulation: str = "UN R94/R137 5.2.8",
) -> ComplianceResult:
    """Check post-crash electrical safety of a vehicle with a high-voltage
    electric power train (UN R94 and R137 5.2.8; R95 5.3.7).

    Parameters
    ----------
    buses:
        One `HVBus` per high-voltage bus. Each must meet at least one
        criterion: voltage, low energy, physical protection, or
        isolation resistance.
    electrolyte:
        Electrolyte type of the REESS.
    electrolyte_in_cabin:
        True if electrolyte spilled into the passenger compartment.
    electrolyte_outside_percent, electrolyte_outside_litres:
        Aqueous electrolyte spilled outside the passenger compartment.
    electrolyte_leaked_anywhere:
        Non-aqueous electrolyte: True if liquid leaked into the passenger
        or luggage compartment or outside the vehicle.
    reess_retained:
        True if the REESS stayed attached by at least one anchorage,
        bracket or structure (5.2.8.3).
    reess_entered_cabin:
        True if a REESS located outside the passenger compartment, or a
        part of it, entered the compartment.
    fire_or_explosion:
        True if there was any evidence of fire or explosion from the
        REESS within 60 minutes (5.2.8.4).
    limits:
        `ElectricalLimits`; default: R94 05 series and R137 02 series.
    regulation:
        Name used in the report.
    """
    lim = limits or ElectricalLimits()
    reqs = [_bus_requirement(b, lim) for b in buses]
    if electrolyte == "aqueous":
        reqs += [
            _state("electrolyte_in_cabin", "5.2.8.2.1", electrolyte_in_cabin, False),
            _upper("electrolyte_outside_percent", "5.2.8.2.1",
                   electrolyte_outside_percent,
                   lim.max_electrolyte_outside_percent, "%"),
            _upper("electrolyte_outside_litres", "5.2.8.2.1",
                   electrolyte_outside_litres, lim.max_electrolyte_outside_litres, "l"),
        ]
    elif electrolyte == "non-aqueous":
        reqs.append(_state("electrolyte_leaked", "5.2.8.2.2",
                           electrolyte_leaked_anywhere, False))
    elif electrolyte is not None:
        raise ValueError('electrolyte must be "aqueous" or "non-aqueous".')
    reqs += [
        _state("reess_retained", "5.2.8.3", reess_retained, True),
        _state("reess_entered_cabin", "5.2.8.3", reess_entered_cabin, False),
        _state("fire_or_explosion", "5.2.8.4", fire_or_explosion, False),
    ]
    notes = (f"Electrolyte observed for {lim.electrolyte_minutes:g} min after the "
             "impact; voltage within 60 s.",)
    return ComplianceResult(f"{regulation} (electrical)", {r.name: r for r in reqs},
                            notes)

