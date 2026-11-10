"""Model quality check sheet: is this run fit to be trusted?

Before anyone reads injury values or intrusions from a crash run, the
run itself is checked: did it finish, is the mass right, how much mass
did mass scaling add, is the energy balance sound, do the contacts
behave. `check_model` does that in one pass from the files every run
writes and returns a `QualitySheet` with a status per check.

- **Run** (d3hsp, glstat): termination, end time reached, errors,
  warnings.
- **Mass** (d3hsp, glstat, matsum): total mass and centre of gravity
  against targets; added mass at the start and at its peak, its growth,
  added mass per part.
- **Time step** (glstat, d3hsp): time step and its drop, the mass
  scaling setting, the smallest elements and the mass factor they need.
- **Energy** (glstat, matsum): energy ratio, hourglass, negative contact
  energy, damping and the part checks of `crashmetrics.energy_check`.
- **Contacts** (sleout, glstat): negative energy of each contact.

A check is ``PASS``, ``FAIL``, ``WARN`` (advisory limits), ``INFO`` (no
limit) or ``SKIP`` (file or value missing); a sheet passes when nothing
fails. Limits are in `QualityLimits`; they are common practice, not a
standard, so set your team's values. Values are reported in **kg, mm,
ms and kJ**. `quality_matrix` puts several runs side by side.
`crashmetrics.synthetic` writes runs to try this without a solver.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from crashmetrics.d3hsp import D3hsp, read_d3hsp
from crashmetrics.energy_check import (
    EnergyLimits,
    GlobalEnergies,
    PartEnergies,
    check_energies,
)
from crashmetrics.loadpath import UNITS, _find_file, _num
from crashmetrics.lsdyna import read_glstat, read_matsum
from crashmetrics.lsdyna_ascii import AsciiOutput, read_sleout

__all__ = [
    "MASS_TO_KG",
    "QualityCheck",
    "QualityLimits",
    "QualitySheet",
    "check_model",
    "check_model_data",
    "quality_matrix",
]

MASS_TO_KG: dict[str, float] = {"mm-ms-kg": 1.0, "mm-s-t": 1000.0, "mm-s-kg": 1.0,
                                "m-s-kg": 1.0}
"""Unit system -> factor from the model's mass unit to kg."""
_LENGTH_TO_MM = {"mm-ms-kg": 1.0, "mm-s-t": 1.0, "mm-s-kg": 1.0, "m-s-kg": 1000.0}

_ICON = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️", "SKIP": "➖"}


@dataclass(frozen=True)
class QualityLimits:
    """Acceptance limits of the check sheet (None switches a check to
    ``INFO``). Breaking a limit fails the check, except the advisory
    ones, which warn."""

    mass_tolerance: float = 1.0
    """Total mass against the target, %."""
    cg_tolerance: float = 10.0
    """Distance of the centre of gravity from the target, mm."""
    added_mass: float | None = 5.0
    """Added mass at the start and at its peak, % of the model mass."""
    added_mass_growth: float | None = 1.0
    """Advisory: growth of the added mass during the run, % points."""
    part_added_mass: float | None = 20.0
    """Added mass of a part, % of the part's mass."""
    end_time: float = 99.5
    """Problem time reached, % of the termination time."""
    timestep_drop: float | None = 10.0
    """Advisory: fall of the time step below its first value, %."""
    element_mass_factor: float | None = 4.0
    """Advisory: mass factor the smallest element needs to reach the
    mass-scaled time step, ``(dt / dt_element)^2``."""
    contact_negative: float | None = 1.0
    """Most negative energy of one contact, % of the peak internal energy."""
    warnings: int | None = None
    """Advisory: number of solver warnings."""
    energy: EnergyLimits = field(default_factory=EnergyLimits)
    """Limits of the energy checks (its added mass limit is not used:
    ``added_mass`` above is)."""


@dataclass(frozen=True)
class QualityCheck:
    """One line of the sheet."""

    group: str
    name: str
    value: str
    limit: str
    status: str
    """``PASS``, ``FAIL``, ``WARN``, ``INFO`` or ``SKIP``."""
    note: str = ""
    number: float | None = None
    """The value as a number, where it is one."""


@dataclass(frozen=True)
class QualitySheet:
    """The check sheet of one run."""

    run: str
    checks: tuple[QualityCheck, ...]
    files: dict[str, str] = field(default_factory=dict)
    """File kind -> path read."""
    notes: tuple[str, ...] = ()
    """Files that could not be read."""

    @property
    def passed(self) -> bool:
        """No check failed."""
        return not self.failures

    @property
    def failures(self) -> tuple[QualityCheck, ...]:
        return tuple(c for c in self.checks if c.status == "FAIL")

    @property
    def warnings(self) -> tuple[QualityCheck, ...]:
        return tuple(c for c in self.checks if c.status == "WARN")

    def check(self, name: str) -> QualityCheck:
        """A check by name."""
        for c in self.checks:
            if c.name == name:
                return c
        raise KeyError(f"No check {name!r}; checks: {[c.name for c in self.checks]}.")

    def counts(self) -> dict[str, int]:
        """Number of checks per status."""
        out = dict.fromkeys(_ICON, 0)
        for c in self.checks:
            out[c.status] += 1
        return out

    def verdict(self) -> str:
        n = self.counts()
        head = "PASSED" if self.passed else (
            f"FAILED ({n['FAIL']} check{'s' if n['FAIL'] > 1 else ''})")
        tail = (f", {n['WARN']} warning{'s' if n['WARN'] > 1 else ''}"
                if n["WARN"] else "")
        skipped = f", {n['SKIP']} skipped" if n["SKIP"] else ""
        return f"{head}{tail}{skipped}"

    def summary(self) -> str:
        """Plain text: the verdict and one line per check."""
        lines = [f"Model quality, {self.run}: {self.verdict()}"]
        width = max(len(c.name) for c in self.checks)
        group = ""
        for c in self.checks:
            if c.group != group:
                group = c.group
                lines.append(f"{group}:")
            note = f"  ({c.note})" if c.note else ""
            limit = f"  [{c.limit}]" if c.limit != "-" else ""
            lines.append(f"  {c.status:<4} {c.name:<{width}}  {c.value}{limit}{note}")
        lines += [f"Note: {n}" for n in self.notes]
        return "\n".join(lines)

    def table(self) -> str:
        """Markdown table of the sheet."""
        lines = [f"**Model quality, {self.run}: {self.verdict()}**", "",
                 "| Group | Check | Value | Limit | Status | Note |",
                 "| --- | --- | --- | --- | --- | --- |"]
        lines += [f"| {c.group} | {c.name} | {c.value} | {c.limit} | "
                  f"{_ICON[c.status]} {c.status} | {c.note} |" for c in self.checks]
        lines += ["", *[f"- {n}" for n in self.notes]] if self.notes else []
        return "\n".join(lines)


# --- Helpers --------------------------------------------------------------------


def _limit(value: float, limit: float | None, *, advisory: bool = False) -> str:
    if limit is None:
        return "INFO"
    if value <= limit:
        return "PASS"
    return "WARN" if advisory else "FAIL"


def _le(limit: float | None, unit: str = "") -> str:
    return "-" if limit is None else f"≤ {limit:g}{unit}"


def _skip(group: str, name: str, why: str) -> QualityCheck:
    return QualityCheck(group, name, "-", "-", "SKIP", why)


def _run_checks(d: D3hsp | None, g: GlobalEnergies | None, lim: QualityLimits,
                tk: float) -> list[QualityCheck]:
    out = []
    if d is None:
        return [_skip("Run", "Termination", "no d3hsp"),
                _skip("Run", "End time reached", "no d3hsp"),
                _skip("Run", "Errors", "no d3hsp"),
                _skip("Run", "Warnings", "no d3hsp")]
    out.append(QualityCheck(
        "Run", "Termination", d.termination, "normal",
        "PASS" if d.termination == "normal" else "FAIL",
        "no termination banner: still running, killed or crashed"
        if d.termination == "incomplete" else ""))
    planned = d.parameters.get("termination_time")
    reached = d.problem_time if d.problem_time is not None else (
        float(g.time[-1]) if g is not None else None)
    if planned and reached is not None:
        share = 100.0 * reached / planned
        out.append(QualityCheck(
            "Run", "End time reached", f"{_num(reached * tk)} of "
            f"{_num(planned * tk)} ms ({share:.1f} %)", f"≥ {lim.end_time:g} %",
            "PASS" if share >= lim.end_time else "FAIL", number=share))
    else:
        out.append(_skip("Run", "End time reached",
                         "termination time or problem time not in d3hsp"))
    errors = [m for m in d.messages if m.kind == "error"]
    warns = [m for m in d.messages if m.kind == "warning"]
    out.append(QualityCheck(
        "Run", "Errors", str(len(errors)), "0", "PASS" if not errors else "FAIL",
        "; ".join(f"{m.number}: {m.text[:60]}" for m in errors[:2]),
        float(len(errors))))
    numbers: dict[int, int] = {}
    for m in warns:
        numbers[m.number] = numbers.get(m.number, 0) + 1
    top = ", ".join(f"{k} x{v}" for k, v in sorted(numbers.items(),
                                                   key=lambda kv: -kv[1])[:3])
    out.append(QualityCheck(
        "Run", "Warnings", str(len(warns)), _le(lim.warnings),
        _limit(len(warns), lim.warnings, advisory=True),
        f"most frequent: {top}" if top else "", float(len(warns))))
    return out


def _mass_checks(d: D3hsp | None, g: GlobalEnergies | None, p: PartEnergies | None,
                 lim: QualityLimits, mk: float, lk: float, target_mass: float | None,
                 target_cg: Sequence[float] | None) -> list[QualityCheck]:
    out = []
    total = d.total_mass * mk if d is not None and d.total_mass is not None else None
    if total is None:
        out.append(_skip("Mass", "Total mass", "no mass summary in d3hsp"))
    elif target_mass is None:
        out.append(QualityCheck("Mass", "Total mass", f"{_num(total, 5)} kg", "-",
                                "INFO", "no target given", total))
    else:
        dev = 100.0 * (total - target_mass) / target_mass
        out.append(QualityCheck(
            "Mass", "Total mass", f"{_num(total, 5)} kg ({dev:+.2f} % of target "
            f"{_num(target_mass, 5)})", f"± {lim.mass_tolerance:g} %",
            "PASS" if abs(dev) <= lim.mass_tolerance else "FAIL", number=total))
    cg = d.mass_center if d is not None else None
    if cg is None:
        out.append(_skip("Mass", "Centre of gravity", "not in d3hsp"))
    else:
        mm = [0.0 if abs(c * lk) < 1e-6 else c * lk for c in cg]
        text = "(" + ", ".join(_num(c, 4) for c in mm) + ") mm"
        if target_cg is None:
            out.append(QualityCheck("Mass", "Centre of gravity", text, "-", "INFO",
                                    "no target given"))
        else:
            dist = math.dist(mm, [float(c) for c in target_cg])
            out.append(QualityCheck(
                "Mass", "Centre of gravity", f"{text}, {_num(dist, 3)} mm from target",
                f"≤ {lim.cg_tolerance:g} mm",
                "PASS" if dist <= lim.cg_tolerance else "FAIL", number=dist))
    # Added mass, % of the model mass.
    percent = None
    if g is not None and g.added_mass_percent is not None:
        percent = np.nan_to_num(g.added_mass_percent)
    elif g is not None and g.added_mass is not None and total:
        percent = 100.0 * np.nan_to_num(g.added_mass) * mk / total
    if percent is None:
        why = "no glstat" if g is None else "no added mass in glstat (no mass scaling)"
        out += [_skip("Mass", "Added mass, start", why),
                _skip("Mass", "Added mass, peak", why),
                _skip("Mass", "Added mass, growth", why)]
    else:
        start, peak = float(percent[0]), float(np.max(percent))
        kg = f" ({_num(peak / 100.0 * total, 3)} kg)" if total else ""
        out.append(QualityCheck("Mass", "Added mass, start", f"{start:.2f} %",
                                _le(lim.added_mass, " %"),
                                _limit(start, lim.added_mass), number=start))
        out.append(QualityCheck("Mass", "Added mass, peak", f"{peak:.2f} %{kg}",
                                _le(lim.added_mass, " %"),
                                _limit(peak, lim.added_mass), number=peak))
        out.append(QualityCheck(
            "Mass", "Added mass, growth", f"{peak - start:+.2f} % points",
            _le(lim.added_mass_growth, " % points"),
            _limit(peak - start, lim.added_mass_growth, advisory=True),
            "elements deform into smaller time steps" if peak - start > 0.5 else "",
            peak - start))
    if p is None or p.added_mass is None:
        out.append(_skip("Mass", "Added mass per part",
                         "no matsum" if p is None else "no added mass in matsum"))
    elif d is None or not d.part_masses:
        out.append(_skip("Mass", "Added mass per part", "no part masses in d3hsp"))
    else:
        peaks = np.nanmax(np.nan_to_num(p.added_mass), axis=0)
        rows = [(100.0 * float(peaks[j]) / d.part_masses[int(pid)], int(pid))
                for j, pid in enumerate(p.part_ids)
                if d.part_masses.get(int(pid), 0.0) > 0]
        rows.sort(reverse=True)
        worst, pid = rows[0]
        over = [r for r in rows if lim.part_added_mass is not None
                and r[0] > lim.part_added_mass]
        name = p.part_names.get(pid, "")
        out.append(QualityCheck(
            "Mass", "Added mass per part", f"{worst:.1f} % in part {pid}"
            + (f" ({name})" if name else ""), _le(lim.part_added_mass, " %"),
            _limit(worst, lim.part_added_mass),
            "over the limit: part " + ", ".join(str(r[1]) for r in over[:6])
            if over else "", worst))
    return out


def _timestep_checks(d: D3hsp | None, g: GlobalEnergies | None, lim: QualityLimits,
                     tk: float) -> list[QualityCheck]:
    out = []
    dt2ms = d.parameters.get("time_step_size_for_mass_scaled_solution_dt2ms") \
        if d is not None else None
    tssfac = d.parameters.get("time_step_scale_factor", 0.9) if d is not None else 0.9
    step = None
    if g is None or g.time_step is None:
        out.append(_skip("Time step", "Time step", "no glstat"))
    else:
        dt = np.asarray(g.time_step, dtype=float)
        dt = dt[np.isfinite(dt) & (dt > 0)]
        step = float(dt[0])
        drop = 100.0 * (1.0 - float(np.min(dt)) / step)
        out.append(QualityCheck(
            "Time step", "Time step", f"{_num(step * tk * 1000.0)} µs, lowest "
            f"{_num(float(np.min(dt)) * tk * 1000.0)} µs (-{drop:.1f} %)",
            _le(lim.timestep_drop, " % drop"),
            _limit(drop, lim.timestep_drop, advisory=True), number=drop))
    if dt2ms is None:
        out.append(_skip("Time step", "Mass scaling", "dt2ms not in d3hsp"))
    elif dt2ms == 0:
        out.append(QualityCheck("Time step", "Mass scaling", "off (dt2ms 0)", "-",
                                "INFO"))
    else:
        scaled = abs(dt2ms) * (tssfac if dt2ms < 0 else 1.0)
        out.append(QualityCheck(
            "Time step", "Mass scaling", f"dt2ms {dt2ms:g}: time step "
            f"{_num(scaled * tk * 1000.0)} µs", "-", "INFO",
            "negative dt2ms: mass added only where needed" if dt2ms < 0 else
            "positive dt2ms: every element scaled to this step"))
        step = step or scaled
    small = d.smallest_timesteps if d is not None else ()
    if not small:
        out.append(_skip("Time step", "Smallest elements",
                         "no smallest time steps table in d3hsp"))
    else:
        first = min(small, key=lambda e: e.timestep)
        parts: dict[int, int] = {}
        for e in small:
            parts[e.part_id] = parts.get(e.part_id, 0) + 1
        where = ", ".join(f"part {k} x{v}" for k, v in sorted(
            parts.items(), key=lambda kv: -kv[1])[:3])
        text = (f"{_num(first.timestep * tk * 1000.0)} µs: {first.element_type} "
                f"{first.element_id} of part {first.part_id}")
        if dt2ms and step:
            factor = max((step / first.timestep) ** 2, 1.0)
            out.append(QualityCheck(
                "Time step", "Smallest elements", f"{text}; mass factor "
                f"{_num(factor, 3)}", _le(lim.element_mass_factor, " x mass"),
                _limit(factor, lim.element_mass_factor, advisory=True),
                f"in the table: {where}", factor))
        else:
            out.append(QualityCheck("Time step", "Smallest elements", text, "-",
                                    "INFO", f"in the table: {where}"))
    return out


def _energy_checks(g: GlobalEnergies | None, p: PartEnergies | None,
                   lim: QualityLimits) -> list[QualityCheck]:
    if g is None:
        return [_skip("Energy", "Energy balance", "no glstat")]
    report = check_energies(g, p, lim.energy)
    labels = {"energy_ratio": "Energy ratio", "hourglass": "Hourglass energy",
              "negative_contact": "Negative contact energy",
              "damping": "Damping energy", "eroded_energy": "Eroded energy",
              "part_hourglass": "Hourglass energy per part",
              "part_negative_internal": "Negative internal energy per part"}
    status = {"pass": "PASS", "fail": "FAIL", "info": "INFO", "skipped": "SKIP"}
    out = []
    for c in report.checks:
        if c.name == "added_mass":
            continue
        where = []
        if c.part is not None:
            name = p.part_names.get(c.part, "") if p is not None else ""
            where.append(f"part {c.part}" + (f" ({name})" if name else ""))
        failed = [f"{x.part_id}" for x in report.failed_parts]
        if c.name.startswith("part_") and c.status == "fail" and failed:
            where.append("over the limit: part " + ", ".join(failed[:6]))
        value = "-" if c.value is None else (
            f"{c.value:.3f}" if c.name == "energy_ratio" else f"{100 * c.value:.1f} %")
        limit = c.limit
        if c.name != "energy_ratio" and limit.startswith("<= "):
            limit = f"≤ {100 * float(limit[3:]):g} %"
        out.append(QualityCheck("Energy", labels.get(c.name, c.name), value,
                                limit.replace("<=", "≤"), status[c.status],
                                "; ".join(where),
                                None if c.value is None else c.value if c.name
                                == "energy_ratio" else 100.0 * c.value))
    return out


def _contact_checks(s: AsciiOutput | None, g: GlobalEnergies | None,
                    lim: QualityLimits, ek: float) -> list[QualityCheck]:
    if s is None:
        return [_skip("Contacts", "Negative energy per contact", "no sleout")]
    energy = np.nan_to_num(s.data["surfa_energy"]) + np.nan_to_num(
        s.data["surfb_energy"])
    lowest = energy.min(axis=0)
    j = int(np.argmin(lowest))
    cid = int(s.ids[j])
    name = s.names.get(cid, "")
    label = f"contact {cid}" + (f" ({name})" if name else "")
    if g is None:
        return [QualityCheck(
            "Contacts", "Negative energy per contact",
            f"{float(lowest[j]) * ek:.3g} kJ in {label}", "-", "INFO",
            "no glstat: no reference energy", float(lowest[j]) * ek)]
    ref = float(np.nanmax(np.abs(g.internal)))
    share = 100.0 * max(-float(lowest[j]), 0.0) / ref if ref > 0 else 0.0
    over = [int(s.ids[k]) for k in np.argsort(lowest)
            if lim.contact_negative is not None and ref > 0
            and 100.0 * -lowest[k] / ref > lim.contact_negative]
    value = (f"{share:.2f} % ({float(lowest[j]) * ek:.3g} kJ) in {label}"
             if share > 0 else f"none ({len(s.ids)} contacts)")
    return [QualityCheck(
        "Contacts", "Negative energy per contact", value,
        _le(lim.contact_negative, " % of internal energy"),
        _limit(share, lim.contact_negative),
        "over the limit: contact " + ", ".join(map(str, over[:6])) if over else "",
        share)]


# --- Entry points ---------------------------------------------------------------


def check_model_data(
    name: str,
    *,
    d3hsp: D3hsp | None = None,
    glstat: GlobalEnergies | None = None,
    matsum: PartEnergies | None = None,
    sleout: AsciiOutput | None = None,
    unit_system: str = "mm-ms-kg",
    target_mass: float | None = None,
    target_cg: Sequence[float] | None = None,
    limits: QualityLimits | None = None,
    files: dict[str, str] | None = None,
    notes: Sequence[str] = (),
) -> QualitySheet:
    """The check sheet from data already read (see `check_model`)."""
    if unit_system not in UNITS:
        raise ValueError(f"Unknown unit_system {unit_system!r}; known: {list(UNITS)}.")
    if d3hsp is None and glstat is None and matsum is None and sleout is None:
        raise ValueError("Give at least one of d3hsp, glstat, matsum and sleout.")
    lim = limits or QualityLimits()
    _, ek, tk = UNITS[unit_system]
    mk, lk = MASS_TO_KG[unit_system], _LENGTH_TO_MM[unit_system]
    checks = (_run_checks(d3hsp, glstat, lim, tk)
              + _mass_checks(d3hsp, glstat, matsum, lim, mk, lk, target_mass,
                             target_cg)
              + _timestep_checks(d3hsp, glstat, lim, tk)
              + _energy_checks(glstat, matsum, lim)
              + _contact_checks(sleout, glstat, lim, ek))
    return QualitySheet(name, tuple(checks), dict(files or {}), tuple(notes))


def check_model(
    directory: str | Path,
    name: str | None = None,
    *,
    unit_system: str = "mm-ms-kg",
    target_mass: float | None = None,
    target_cg: Sequence[float] | None = None,
    limits: QualityLimits | None = None,
) -> QualitySheet:
    """The model quality check sheet of a run folder.

    Parameters
    ----------
    directory:
        Run folder with ``d3hsp``, ``glstat``, ``matsum`` and ``sleout``
        (upper case or a job prefix such as ``run1.glstat`` also work).
        Missing files skip their checks; at least one is needed.
    name:
        Run name; the folder name by default.
    unit_system:
        Unit system of the model (masses to kg, lengths to mm, times to
        ms, energies to kJ).
    target_mass, target_cg:
        Target vehicle mass (kg) and centre of gravity (x, y, z in mm, in
        the model's coordinate system); without them mass and centre of
        gravity are reported only.
    limits:
        `QualityLimits`; the defaults if omitted.
    """
    folder = Path(directory)
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a directory.")
    paths = {k: _find_file(folder, k) for k in ("d3hsp", "glstat", "matsum", "sleout")}
    found = {k: p for k, p in paths.items() if p is not None}
    if not found:
        raise FileNotFoundError(f"No d3hsp, glstat, matsum or sleout in {folder}.")
    readers = {"d3hsp": read_d3hsp, "glstat": read_glstat, "matsum": read_matsum,
               "sleout": read_sleout}
    data: dict[str, Any] = {}
    notes = []
    for kind, file in found.items():
        try:
            data[kind] = readers[kind](file)
        except ValueError as exc:
            notes.append(f"{file.name} could not be read: {str(exc)[:80]}")
    if not data:
        raise ValueError(f"No readable d3hsp, glstat, matsum or sleout in {folder}: "
                         + "; ".join(notes))
    return check_model_data(
        name or folder.name, d3hsp=data.get("d3hsp"), glstat=data.get("glstat"),
        matsum=data.get("matsum"), sleout=data.get("sleout"),
        unit_system=unit_system, target_mass=target_mass, target_cg=target_cg,
        limits=limits, files={k: str(p) for k, p in found.items() if k in data},
        notes=notes)


def quality_matrix(sheets: Sequence[QualitySheet], *, values: bool = True) -> str:
    """Markdown table of several runs side by side: one row per check,
    one column per run (status, and the number where the check has one)."""
    if not sheets:
        raise ValueError("Give at least one sheet.")
    names: list[tuple[str, str]] = []
    for s in sheets:
        for c in s.checks:
            if (c.group, c.name) not in names:
                names.append((c.group, c.name))
    lines = ["| Group | Check | " + " | ".join(s.run for s in sheets) + " |",
             "| --- | --- |" + " --- |" * len(sheets)]
    for group, name in names:
        cells = []
        for s in sheets:
            found = [x for x in s.checks if (x.group, x.name) == (group, name)]
            if not found:
                cells.append("")
                continue
            c = found[0]
            number = ""
            if values and c.number is not None and c.status != "SKIP":
                whole = float(c.number).is_integer() and abs(c.number) < 1e6
                number = f" {int(c.number)}" if whole else f" {_num(c.number, 3)}"
            cells.append(f"{_ICON[c.status]}{number}")
        lines.append(f"| {group} | {name} | " + " | ".join(cells) + " |")
    lines.append("| | **Verdict** | " + " | ".join(
        f"**{'PASSED' if s.passed else 'FAILED'}**" for s in sheets) + " |")
    return "\n".join(lines)
