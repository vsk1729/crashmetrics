"""Load paths and energy absorption, in one run and across runs.

The questions after every crash run: which parts absorbed the energy,
how the load was shared between the upper, middle and lower load paths,
whether the structure crushed in the intended order, and, against a
baseline, which parts changed (the "culprit").

- **Runs**: `load_run` reads ``matsum`` (part energies) and ``secforc``
  (section forces) of a run folder into a `CrashRun`; `select_parts` /
  `select_sections` pick IDs by number or by title pattern
  (``"Crash box*"``).
- **Energy**: `energy_ranking` (absorbed energy per part and per group,
  share, cumulative share, when each part absorbs it, hourglass share),
  `energy_history` (groups over time).
- **Section forces**: `section_forces` (one component, consistent sign,
  optional CFC filter), `force_metrics` (peak, mean, impulse, onset),
  `load_split` (share of each load path, over the run and over time,
  against a target).
- **Crush sequence**: `crush_sequence` checks that chains of parts start
  to absorb energy in the intended order.
- **Comparison**: `compare_runs` (part energy and section force changes
  ranked, the parts that explain most of the change, ISO/TS 18571
  similarity of the force curves), `energy_matrix` (many runs side by
  side), `loadpath_report` (all of it as Markdown).

Results are in **kJ, kN and ms**; the run's unit system (`UNITS`)
converts them. `crashmetrics.synthetic` writes runs to try all of this
without a solver.
"""

from __future__ import annotations

import fnmatch
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from crashmetrics.energy_check import PartEnergies
from crashmetrics.lsdyna import read_matsum
from crashmetrics.lsdyna_ascii import AsciiOutput, read_secforc

__all__ = [
    "UNITS",
    "CrashRun",
    "EnergyMatrix",
    "EnergyRanking",
    "LoadSplit",
    "PartChange",
    "PartEnergy",
    "RunComparison",
    "SectionChange",
    "SectionForces",
    "SectionMetrics",
    "SequenceCheck",
    "SequenceStage",
    "compare_runs",
    "crush_sequence",
    "energy_history",
    "energy_matrix",
    "energy_ranking",
    "force_metrics",
    "load_run",
    "load_split",
    "loadpath_report",
    "section_forces",
    "select_parts",
    "select_sections",
]

FloatArray = NDArray[np.float64]
Selector = int | str
"""A part or section: its ID, or a title pattern (``*`` and ``?``, case
ignored)."""

# np.trapezoid is NumPy 2; np.trapz the same in NumPy 1.
_trapz: Callable[..., Any] = getattr(np, "trapezoid", None) or getattr(np, "trapz")

UNITS: dict[str, tuple[float, float, float]] = {
    "mm-ms-kg": (1.0, 1e-3, 1.0),
    "mm-s-t": (1e-3, 1e-6, 1e3),
    "mm-s-kg": (1e-6, 1e-9, 1e3),
    "m-s-kg": (1e-3, 1e-3, 1e3),
}
"""Unit system -> factors to kN, kJ and ms (force, energy, time). In
mm-ms-kg the force is kN and the energy J (kN mm); in mm-s-t N and mJ."""


# --- Runs and selection ---------------------------------------------------------


@dataclass(frozen=True)
class CrashRun:
    """Part energies and section forces of one run (model units)."""

    name: str
    energies: PartEnergies | None = None
    sections: AsciiOutput | None = None
    unit_system: str = "mm-ms-kg"
    source: str = ""

    def __post_init__(self) -> None:
        if self.unit_system not in UNITS:
            raise ValueError(f"Unknown unit_system {self.unit_system!r}; known: "
                             f"{list(UNITS)}.")
        if self.energies is None and self.sections is None:
            raise ValueError(f"{self.name}: no part energies and no section forces.")

    @property
    def factors(self) -> tuple[float, float, float]:
        """To kN, kJ and ms."""
        return UNITS[self.unit_system]

    def part_name(self, part_id: int) -> str:
        names = self.energies.part_names if self.energies is not None else {}
        return names.get(int(part_id)) or f"Part {part_id}"

    def section_name(self, section_id: int) -> str:
        names = self.sections.names if self.sections is not None else {}
        return names.get(int(section_id)) or f"Section {section_id}"

    def _need_energies(self) -> PartEnergies:
        if self.energies is None:
            raise ValueError(f"{self.name}: no part energies (matsum).")
        return self.energies

    def _need_sections(self) -> AsciiOutput:
        if self.sections is None:
            raise ValueError(f"{self.name}: no section forces (secforc).")
        return self.sections


def _find_file(folder: Path, kind: str) -> Path | None:
    exact = [folder / kind, folder / kind.upper()]
    for p in exact:
        if p.is_file():
            return p
    prefixed = sorted(p for p in folder.iterdir() if p.is_file()
                      and p.name.lower().endswith("." + kind))
    return prefixed[0] if prefixed else None


def load_run(directory: str | Path, name: str | None = None, *,
             unit_system: str = "mm-ms-kg", matsum: str | Path | None = None,
             secforc: str | Path | None = None) -> CrashRun:
    """Read the ``matsum`` and ``secforc`` of a run folder.

    Files are found by name (``matsum``, ``MATSUM`` or a job prefix such
    as ``run1.matsum``), or given; either may be missing, not both.
    ``name`` defaults to the folder name.
    """
    folder = Path(directory)
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a directory.")
    m = Path(matsum) if matsum is not None else _find_file(folder, "matsum")
    s = Path(secforc) if secforc is not None else _find_file(folder, "secforc")
    if m is None and s is None:
        raise FileNotFoundError(f"No matsum or secforc in {folder}.")
    return CrashRun(name or folder.name, read_matsum(m) if m else None,
                    read_secforc(s) if s else None, unit_system, str(folder))


def _select(ids: Sequence[int], names: Mapping[int, str],
            selectors: Selector | Iterable[Selector], what: str) -> list[int]:
    items = [selectors] if isinstance(selectors, (int, str)) else list(selectors)
    out: list[int] = []
    for item in items:
        if isinstance(item, (int, np.integer)):
            if int(item) not in ids:
                raise KeyError(f"No {what} {item}; IDs: {list(ids)[:30]}.")
            found = [int(item)]
        else:
            pattern = str(item).lower()
            found = [i for i in ids if fnmatch.fnmatchcase(names.get(i, "").lower(),
                                                           pattern)]
            if not found:
                raise KeyError(f"No {what} title matches {item!r}.")
        out += [i for i in found if i not in out]
    return out


def select_parts(run: CrashRun, selectors: Selector | Iterable[Selector]) -> list[int]:
    """Part IDs from IDs and title patterns (``"Crash box*"``)."""
    e = run._need_energies()
    return _select([int(i) for i in e.part_ids], e.part_names, selectors, "part")


def select_sections(run: CrashRun,
                    selectors: Selector | Iterable[Selector]) -> list[int]:
    """Section IDs from IDs and title patterns."""
    s = run._need_sections()
    return _select([int(i) for i in s.ids], s.names, selectors, "section")


# --- Energy -----------------------------------------------------------------------


def _absorbed(run: CrashRun, include_eroded: bool) -> tuple[FloatArray, FloatArray,
                                                           FloatArray]:
    """(time ms, absorbed energy kJ (time, part), hourglass kJ)."""
    e = run._need_energies()
    _, ek, tk = run.factors
    ie = np.nan_to_num(e.internal)
    if include_eroded and "eroded_ie" in e.extra:
        ie = ie + np.nan_to_num(e.extra["eroded_ie"])
    hg = np.zeros_like(ie) if e.hourglass is None else np.nan_to_num(e.hourglass)
    return e.time * tk, ie * ek, hg * ek


def _crossing(t: FloatArray, y: FloatArray, level: float) -> float:
    """First time ``y`` reaches ``level`` (linear interpolation), NaN if never."""
    above = np.flatnonzero(y >= level)
    if not len(above):
        return math.nan
    k = int(above[0])
    if k == 0 or y[k] == y[k - 1]:
        return float(t[k])
    return float(t[k - 1] + (level - y[k - 1]) / (y[k] - y[k - 1]) * (t[k] - t[k - 1]))


@dataclass(frozen=True)
class PartEnergy:
    """Energy absorbed by one part (or group)."""

    part_id: int
    name: str
    energy: float
    """kJ at the ranking time."""
    peak: float
    """Largest absorbed energy, kJ (above ``energy`` if the part unloads)."""
    share: float
    """% of the energy of all ranked parts."""
    cumulative: float
    """% of the parts down to this one."""
    hourglass: float
    """Hourglass energy, % of the part's energy."""
    onset: float
    """ms when the part has absorbed ``onset`` of its energy."""
    half: float
    """ms at 50 % of its energy."""
    end: float
    """ms at 90 % of its energy."""


@dataclass(frozen=True)
class EnergyRanking:
    """Parts ranked by absorbed energy."""

    run: str
    time: float
    """ms."""
    total: float
    """kJ of all ranked parts."""
    rows: tuple[PartEnergy, ...]
    groups: tuple[PartEnergy, ...] = ()
    """Groups (``part_id`` 0), in the order given."""
    excluded: tuple[int, ...] = ()

    def table(self, top: int | None = 10) -> str:
        """Markdown table of the ``top`` parts (and the groups)."""
        lines = [f"Absorbed energy, {self.run}, at {_ms(self.time)} ms: "
                 f"{_num(self.total)} kJ",
                 "", "| # | Part | kJ | Share | Cumulative | 10/50/90 % at ms | "
                 "Hourglass |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for i, r in enumerate(self.rows[:top] if top else self.rows, 1):
            lines.append(f"| {i} | {r.name} ({r.part_id}) | {_num(r.energy)} | "
                         f"{r.share:.1f} % | {r.cumulative:.1f} % | "
                         f"{_ms(r.onset)} / {_ms(r.half)} / {_ms(r.end)} | "
                         f"{r.hourglass:.1f} % |")
        if self.groups:
            lines += ["", "| Group | kJ | Share | 10/50/90 % at ms |",
                      "| --- | --- | --- | --- |"]
            lines += [f"| {g.name} | {_num(g.energy)} | {g.share:.1f} % | "
                      f"{_ms(g.onset)} / {_ms(g.half)} / {_ms(g.end)} |"
                      for g in self.groups]
        return "\n".join(lines)


def _num(value: float, sig: int = 4, signed: bool = False) -> str:
    """Readable number: ``sig`` significant digits, at most 2 decimals
    from 1 up and 3 below, no exponent."""
    if not math.isfinite(value):
        return "-"
    if value == 0:
        return "+0" if signed else "0"
    digits = sig - 1 - math.floor(math.log10(abs(value)))
    digits = max(0, min(digits, 2 if abs(value) >= 1 else 3))
    text = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return text


def _ms(value: float) -> str:
    return _num(value, 3)


def _row(pid: int, name: str, t: FloatArray, w: FloatArray, h: FloatArray, k: int,
         total: float, onset: float) -> PartEnergy:
    final = float(w[k])
    level = max(final, 0.0)

    def at(f: float) -> float:
        return _crossing(t[:k + 1], w[:k + 1], f * level) if level > 0 else math.nan

    return PartEnergy(pid, name, final, float(np.max(w)),
                      100.0 * final / total if total else 0.0, 0.0,
                      100.0 * float(h[k]) / final if final > 0 else 0.0,
                      at(onset), at(0.5), at(0.9))


def energy_ranking(
    run: CrashRun,
    *,
    time: float | None = None,
    parts: Selector | Iterable[Selector] | None = None,
    exclude: Selector | Iterable[Selector] | None = None,
    groups: Mapping[str, Selector | Iterable[Selector]] | None = None,
    include_eroded: bool = True,
    onset: float = 0.1,
) -> EnergyRanking:
    """Parts ranked by absorbed (internal) energy.

    Parameters
    ----------
    time:
        ms; default the end of the run.
    parts, exclude:
        Parts to rank (default all) and to leave out (rigid barriers,
        the body carrying the kinetic energy).
    groups:
        Name -> parts, summed (for example ``{"crash boxes": "Crash box*"}``).
    include_eroded:
        Add the internal energy of eroded elements (matsum ``eroded_ie``).
    onset:
        Fraction of its energy at which a part counts as started.
    """
    e = run._need_energies()
    t, w, h = _absorbed(run, include_eroded)
    all_ids = [int(i) for i in e.part_ids]
    ids = select_parts(run, parts) if parts is not None else list(all_ids)
    dropped = select_parts(run, exclude) if exclude is not None else []
    ids = [i for i in ids if i not in dropped]
    k = len(t) - 1 if time is None else int(np.clip(np.searchsorted(t, time), 0,
                                                     len(t) - 1))
    col = {pid: j for j, pid in enumerate(all_ids)}
    total = float(sum(max(w[k, col[i]], 0.0) for i in ids))
    rows = sorted((_row(i, run.part_name(i), t, w[:, col[i]], h[:, col[i]], k, total,
                        onset) for i in ids), key=lambda r: -r.energy)
    cum = 0.0
    ranked = []
    for r in rows:
        cum += r.share
        ranked.append(PartEnergy(**{**r.__dict__, "cumulative": cum}))
    group_rows = []
    for gname, sel in (groups or {}).items():
        gi = [i for i in select_parts(run, sel) if i not in dropped]
        gw = w[:, [col[i] for i in gi]].sum(axis=1)
        gh = h[:, [col[i] for i in gi]].sum(axis=1)
        group_rows.append(_row(0, gname, t, gw, gh, k, total, onset))
    return EnergyRanking(run.name, float(t[k]), total, tuple(ranked),
                         tuple(group_rows), tuple(dropped))


def energy_history(run: CrashRun,
                   groups: Mapping[str, Selector | Iterable[Selector]], *,
                   include_eroded: bool = True
                   ) -> tuple[FloatArray, dict[str, FloatArray]]:
    """(time ms, group name -> absorbed energy kJ over time), for plots."""
    e = run._need_energies()
    t, w, _ = _absorbed(run, include_eroded)
    col = {int(pid): j for j, pid in enumerate(e.part_ids)}
    return t, {g: w[:, [col[i] for i in select_parts(run, sel)]].sum(axis=1)
               for g, sel in groups.items()}


# --- Section forces ---------------------------------------------------------------

Component = Literal["x", "y", "z", "total", "auto"]


@dataclass(frozen=True)
class SectionForces:
    """One force component of several sections, kN, main load positive."""

    run: str
    time: FloatArray
    """ms."""
    ids: tuple[int, ...]
    names: dict[int, str]
    force: FloatArray
    """(time, section), kN."""
    components: tuple[str, ...]
    """Component used for each section."""
    flipped: tuple[bool, ...]
    """Sections whose sign was reversed (``orientation="auto"``)."""
    cfc: float | None = None

    def __getitem__(self, section_id: int) -> FloatArray:
        try:
            return self.force[:, self.ids.index(int(section_id))]
        except ValueError:
            raise KeyError(f"No section {section_id}; IDs: {self.ids}.") from None


def section_forces(
    run: CrashRun,
    sections: Selector | Iterable[Selector] | None = None,
    *,
    component: Component = "auto",
    orientation: Literal["auto", "as_written"] = "auto",
    cfc: float | None = None,
) -> SectionForces:
    """Section forces in kN with a consistent sign.

    Parameters
    ----------
    component:
        ``"x"``, ``"y"``, ``"z"``, ``"total"`` (magnitude) or ``"auto"``
        (per section, the axis with the largest impulse).
    orientation:
        ``"auto"`` reverses sections whose force is mainly negative, so
        the main load is positive whatever the section normal; with
        ``"as_written"`` the sign is the file's.
    cfc:
        SAE J211 filter class (60 or 180 for structure); default none.
        Unevenly spaced output (MPP) is first resampled at its median
        time step.
    """
    s = run._need_sections()
    fk, _, tk = run.factors
    ids = select_sections(run, sections) if sections is not None else [
        int(i) for i in s.ids]
    t = s.time * tk
    out = np.zeros((len(t), len(ids)))
    comps, flips = [], []
    for j, sid in enumerate(ids):
        col = s.index(sid)
        if component == "auto":
            imp = {c: abs(float(_trapz(
                np.nan_to_num(s.data[f"{c}_force"][:, col]), t))) for c in "xyz"}
            comp = max(imp, key=lambda c: imp[c])
        else:
            comp = component
        f = np.nan_to_num(s.data[f"{comp}_force"][:, col]) * fk
        flip = orientation == "auto" and comp != "total" and float(
            _trapz(f, t)) < 0
        if flip:
            f = -f
        out[:, j] = f
        comps.append(comp)
        flips.append(flip)
    if cfc is not None:
        from crashmetrics.signals import cfc_filter
        step = np.diff(t)
        if len(t) > 2 and np.ptp(step) > 1e-6 * float(np.median(step)):
            # MPP output is often not evenly spaced: resample before filtering.
            grid = np.arange(t[0], t[-1] + 0.5 * float(np.median(step)),
                             float(np.median(step)))
            out = np.column_stack([np.interp(grid, t, out[:, j])
                                   for j in range(out.shape[1])])
            t = grid
        out = np.column_stack([cfc_filter(t / 1000.0, out[:, j], cfc)
                               for j in range(out.shape[1])])
    return SectionForces(run.name, t, tuple(ids), {i: run.section_name(i) for i in ids},
                         out, tuple(comps), tuple(flips), cfc)


@dataclass(frozen=True)
class SectionMetrics:
    """Force measures of one section (kN, ms; impulse kN ms = N s)."""

    section_id: int
    name: str
    peak: float
    peak_time: float
    mean: float
    """Impulse divided by the time from onset to the end of loading."""
    impulse: float
    onset: float
    """First time the force reaches ``onset`` of its peak."""
    end: float
    """Last time the force is above ``onset`` of its peak."""


def _window(forces: SectionForces, window: tuple[float, float] | None
            ) -> tuple[FloatArray, FloatArray]:
    t, f = forces.time, forces.force
    if window is None:
        return t, f
    keep = (t >= window[0]) & (t <= window[1])
    return t[keep], f[keep]


def force_metrics(forces: SectionForces, *, window: tuple[float, float] | None = None,
                  onset: float = 0.1) -> tuple[SectionMetrics, ...]:
    """Peak, mean force, impulse and loading time of each section."""
    t, f = _window(forces, window)
    rows = []
    for j, sid in enumerate(forces.ids):
        y = f[:, j]
        k = int(np.argmax(y))
        peak = float(y[k])
        imp = float(_trapz(np.maximum(y, 0.0), t))
        active = np.flatnonzero(y >= onset * peak) if peak > 0 else np.array([], int)
        t0 = float(t[active[0]]) if len(active) else math.nan
        t1 = float(t[active[-1]]) if len(active) else math.nan
        span = t1 - t0
        rows.append(SectionMetrics(sid, forces.names[sid], peak, float(t[k]),
                                   imp / span if span > 0 else math.nan, imp, t0, t1))
    return tuple(rows)


@dataclass(frozen=True)
class LoadSplit:
    """Share of the load carried by each load path."""

    run: str
    paths: tuple[str, ...]
    sections: tuple[tuple[int, ...], ...]
    impulse: tuple[float, ...]
    """kN ms per path."""
    share: tuple[float, ...]
    """% of the summed impulse."""
    peak: tuple[float, ...]
    """kN, peak force of each path (its sections summed)."""
    time: FloatArray
    force: FloatArray
    """(time, path), kN."""
    history: FloatArray
    """(time, path), % of the total force at each time (NaN below 5 % of the
    total peak)."""
    target: tuple[float, ...] | None = None
    tolerance: float = 5.0
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.warnings

    def summary(self) -> str:
        lines = [f"Load split, {self.run}:"]
        for i, p in enumerate(self.paths):
            goal = (f" (target {self.target[i]:.0f} % ± {self.tolerance:g})"
                    if self.target else "")
            lines.append(f"  {p:<10} {self.share[i]:5.1f} %{goal}  impulse "
                         f"{_num(self.impulse[i])} kN ms, peak {_num(self.peak[i])} kN")
        lines += [f"  warning: {w}" for w in self.warnings]
        return "\n".join(lines)


def load_split(
    forces: SectionForces,
    paths: Mapping[str, Selector | Iterable[Selector]],
    *,
    window: tuple[float, float] | None = None,
    target: Mapping[str, float] | None = None,
    tolerance: float = 5.0,
) -> LoadSplit:
    """Share of the load in each path, from section forces.

    Give each path the sections that cut it **once** (for example the
    front rails LH and RH for the middle path); sections in series along
    the same path carry the same load and would count it twice.
    ``target`` (path -> %) is checked with ``tolerance`` percentage
    points.
    """
    t, f = _window(forces, window)
    names = forces.names
    ids = list(forces.ids)
    chosen = {p: _select(ids, names, sel, "section") for p, sel in paths.items()}
    used: dict[int, str] = {}
    warnings = []
    for p, sids in chosen.items():
        for sid in sids:
            if sid in used:
                warnings.append(f"section {sid} is in both {used[sid]} and {p}")
            used[sid] = p
    pf = np.column_stack([f[:, [ids.index(s) for s in sids]].sum(axis=1)
                          for sids in chosen.values()])
    imp = np.array([float(_trapz(np.maximum(pf[:, i], 0.0), t))
                    for i in range(pf.shape[1])])
    share = 100.0 * imp / imp.sum() if imp.sum() > 0 else np.zeros_like(imp)
    total = pf.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        hist = 100.0 * pf / total[:, None]
    hist[total < 0.05 * max(float(np.max(total)), 1e-12)] = np.nan
    goal = None
    if target is not None:
        missing = set(chosen) - set(target)
        if missing:
            raise ValueError(f"No target for {sorted(missing)}.")
        goal = tuple(float(target[p]) for p in chosen)
        for p, s, g in zip(chosen, share, goal):
            if abs(s - g) > tolerance:
                warnings.append(f"{p} carries {s:.1f} % (target {g:.0f} % ± "
                                f"{tolerance:g})")
    return LoadSplit(forces.run, tuple(chosen),
                     tuple(tuple(v) for v in chosen.values()),
                     tuple(float(x) for x in imp), tuple(float(x) for x in share),
                     tuple(float(np.max(pf[:, i])) for i in range(pf.shape[1])),
                     t, pf, hist, goal, tolerance, tuple(warnings))


# --- Crush sequence ---------------------------------------------------------------


@dataclass(frozen=True)
class SequenceStage:
    """One stage of a crush chain."""

    name: str
    parts: tuple[int, ...]
    energy: float
    """kJ at the end."""
    onset: float
    """ms when the stage has absorbed ``onset`` of its energy (NaN if it
    does not crush)."""
    end: float
    """ms at 90 % of its energy."""
    crushed: bool
    """Absorbs at least ``min_energy`` of the chain's energy."""


@dataclass(frozen=True)
class SequenceCheck:
    """Crush order of one chain, front to rear."""

    chain: str
    stages: tuple[SequenceStage, ...]
    violations: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        head = f"{self.chain}: {'in order' if self.passed else 'OUT OF ORDER'}"
        order = " -> ".join(
            f"{s.name} {_ms(s.onset)} ms" if s.crushed else f"({s.name}: not crushed)"
            for s in self.stages)
        lines = [head, f"  {order}"]
        lines += [f"  violation: {v}" for v in self.violations]
        lines += [f"  warning: {w}" for w in self.warnings]
        return "\n".join(lines)


def crush_sequence(
    run: CrashRun,
    chains: Mapping[str, Sequence[Selector | Iterable[Selector]]],
    *,
    onset: float = 0.1,
    overlap: float = 0.5,
    min_energy: float = 0.02,
) -> tuple[SequenceCheck, ...]:
    """Check that the parts of each chain start crushing in order.

    Parameters
    ----------
    chains:
        Name -> stages front to rear; a stage is a part, a title pattern
        or a list of them (summed), for example
        ``{"main LH": ["Bumper*", "Crash box LH", "Front rail LH"]}``.
    onset:
        A stage starts when it has absorbed this fraction of its energy.
    overlap:
        Warning when a stage starts before the stage in front of it has
        absorbed this fraction of its energy.
    min_energy:
        Stages absorbing less than this fraction of the chain's energy
        count as not crushed (elastic only) and are left out of the
        order check.
    """
    e = run._need_energies()
    t, w, _ = _absorbed(run, True)
    col = {int(pid): j for j, pid in enumerate(e.part_ids)}
    checks = []
    for chain, stages_sel in chains.items():
        histories = []
        for sel in stages_sel:
            pids = select_parts(run, sel)
            name = (run.part_name(pids[0]) if len(pids) == 1
                    else str(sel) if isinstance(sel, str) else
                    " + ".join(run.part_name(p) for p in pids))
            histories.append((name, tuple(pids),
                              w[:, [col[p] for p in pids]].sum(axis=1)))
        total = sum(max(float(h[-1]), 0.0) for _, _, h in histories)
        stages = []
        for name, members, h in histories:
            final = float(h[-1])
            crushed = total > 0 and final >= min_energy * total
            stages.append(SequenceStage(
                name, members, final,
                _crossing(t, h, onset * final) if crushed else math.nan,
                _crossing(t, h, 0.9 * final) if crushed else math.nan, crushed))
        violations, warnings = [], []
        active = [(s, h) for s, (_, _, h) in zip(stages, histories) if s.crushed]
        for (front, hf), (rear, _) in zip(active, active[1:]):
            if rear.onset < front.onset:
                violations.append(f"{rear.name} starts at {_ms(rear.onset)} ms, before "
                                  f"{front.name} ({_ms(front.onset)} ms)")
            else:
                done = float(np.interp(rear.onset, t, hf)) / front.energy
                if done < overlap:
                    warnings.append(f"{rear.name} starts at {_ms(rear.onset)} ms, when "
                                    f"{front.name} has absorbed {100 * done:.0f} % "
                                    "of its energy")
        checks.append(SequenceCheck(chain, tuple(stages), tuple(violations),
                                    tuple(warnings)))
    return tuple(checks)


# --- Comparison -------------------------------------------------------------------


@dataclass(frozen=True)
class PartChange:
    """Absorbed energy of a part in two runs."""

    part_id: int
    name: str
    baseline: float
    """kJ (NaN if the part is not in the baseline)."""
    variant: float
    change: float
    """kJ."""
    change_pct: float
    """% of the baseline energy (NaN for a new part)."""
    share_of_change: float
    """% of the summed absolute changes of all parts."""


@dataclass(frozen=True)
class SectionChange:
    """Force measures of a section in two runs."""

    section_id: int
    name: str
    peak: tuple[float, float]
    impulse: tuple[float, float]
    impulse_change_pct: float
    rating: float | None
    """ISO/TS 18571 rating of the variant curve against the baseline (1:
    the same curve)."""


@dataclass(frozen=True)
class RunComparison:
    """A variant against a baseline."""

    baseline: str
    variant: str
    total: tuple[float, float]
    """Absorbed energy of the compared parts, kJ."""
    parts: tuple[PartChange, ...]
    """By absolute change, largest first."""
    sections: tuple[SectionChange, ...] = ()
    groups: tuple[PartChange, ...] = ()
    culprits: tuple[PartChange, ...] = ()
    """The fewest parts that explain ``explain`` of the absolute change."""
    notes: tuple[str, ...] = ()

    def summary(self, top: int = 5) -> str:
        a, b = self.total
        lines = [f"{self.variant} against {self.baseline}: " + (
            f"absorbed energy {_num(a)} -> {_num(b)} kJ ({_num(b - a, 3, True)})"
            if math.isfinite(a) and math.isfinite(b) else "no part energies")]
        if self.culprits:
            lines.append("Parts that explain most of the change:")
            lines += [f"  {c.name} ({c.part_id}): {_kj(c.baseline)} -> {_kj(c.variant)}"
                      f" kJ ({_num(c.change, 3, True)}, {c.share_of_change:.0f} % of "
                      "all change)"
                      for c in self.culprits[:top]]
        if self.groups:
            lines.append("Groups:")
            lines += [f"  {g.name}: {_num(g.baseline)} -> {_num(g.variant)} kJ "
                      f"({_num(g.change, 3, True)})" for g in self.groups]
        changed = sorted(self.sections, key=lambda s: (
            s.rating if s.rating is not None else 1.0, -abs(s.impulse_change_pct)))
        if changed:
            lines.append("Sections, most changed first:")
            for s in changed[:top]:
                r = f", ISO 18571 {s.rating:.2f}" if s.rating is not None else ""
                lines.append(f"  {s.name} ({s.section_id}): peak {_num(s.peak[0])} -> "
                             f"{_num(s.peak[1])} kN, impulse "
                             f"{s.impulse_change_pct:+.1f} %{r}")
        lines += [f"Note: {n}" for n in self.notes]
        return "\n".join(lines)


def _kj(value: float) -> str:
    return "removed" if math.isnan(value) else f"{_num(value)}"


def _final(run: CrashRun) -> dict[int, float]:
    e = run._need_energies()
    _, w, _ = _absorbed(run, True)
    return {int(pid): float(w[-1, j]) for j, pid in enumerate(e.part_ids)}


def compare_runs(
    baseline: CrashRun,
    variant: CrashRun,
    *,
    exclude: Selector | Iterable[Selector] | None = None,
    groups: Mapping[str, Selector | Iterable[Selector]] | None = None,
    sections: Selector | Iterable[Selector] | None = None,
    component: Component = "auto",
    cfc: float | None = None,
    rate: bool = True,
    explain: float = 0.8,
) -> RunComparison:
    """Part energies and section forces of a variant against a baseline.

    Parts and sections are matched by ID. ``culprits`` are the fewest
    parts, largest change first, that together explain ``explain`` of the
    summed absolute energy change. With ``rate``, each section's force
    curve gets an ISO/TS 18571 rating against the baseline curve.
    """
    notes: list[str] = []
    parts: list[PartChange] = []
    group_rows: list[PartChange] = []
    total = (math.nan, math.nan)
    if baseline.energies is not None and variant.energies is not None:
        a, b = _final(baseline), _final(variant)
        drop = set()
        if exclude is not None:
            for run in (baseline, variant):
                try:
                    drop |= set(select_parts(run, exclude))
                except KeyError:
                    pass
        ids = [i for i in dict.fromkeys([*a, *b]) if i not in drop]
        only_a = [i for i in ids if i not in b]
        only_b = [i for i in ids if i not in a]
        if only_a:
            notes.append(f"parts only in {baseline.name}: {only_a}")
        if only_b:
            notes.append(f"parts only in {variant.name}: {only_b}")
        changes = {i: b.get(i, 0.0) - a.get(i, 0.0) for i in ids}
        summed = sum(abs(c) for c in changes.values())
        for i in ids:
            base = a.get(i, math.nan)
            new = b.get(i, math.nan)
            name = (baseline.part_name(i) if i in a else variant.part_name(i))
            parts.append(PartChange(
                i, name, base, new, changes[i],
                100.0 * changes[i] / base if i in a and base > 0 else math.nan,
                100.0 * abs(changes[i]) / summed if summed > 0 else 0.0))
        parts.sort(key=lambda p: -abs(p.change))
        total = (sum(a.get(i, 0.0) for i in ids), sum(b.get(i, 0.0) for i in ids))
        def group_sum(run: CrashRun, energy: dict[int, float],
                      sel: Selector | Iterable[Selector], gname: str) -> float:
            try:
                return sum(energy[i] for i in select_parts(run, sel) if i not in drop)
            except KeyError:
                notes.append(f"group {gname}: no parts in {run.name}")
                return 0.0

        for gname, sel in (groups or {}).items():
            ga = group_sum(baseline, a, sel, gname)
            gb = group_sum(variant, b, sel, gname)
            group_rows.append(PartChange(0, gname, ga, gb, gb - ga,
                                         100.0 * (gb - ga) / ga if ga > 0 else math.nan,
                                         100.0 * abs(gb - ga) / summed
                                         if summed else 0.0))
    culprits: list[PartChange] = []
    covered = 0.0
    for p in parts:
        if covered >= 100.0 * explain or p.share_of_change <= 0:
            break
        culprits.append(p)
        covered += p.share_of_change
    section_rows: list[SectionChange] = []
    if baseline.sections is not None and variant.sections is not None:
        fa = section_forces(baseline, sections, component=component, cfc=cfc)
        common = [i for i in fa.ids if i in variant.sections.ids]
        missing = [i for i in fa.ids if i not in common]
        if missing:
            notes.append(f"sections only in {baseline.name}: {missing}")
        fb = section_forces(variant, common, component=component, cfc=cfc)
        ma = {m.section_id: m for m in force_metrics(fa)}
        mb = {m.section_id: m for m in force_metrics(fb)}
        for sid in common:
            rating = None
            if rate:
                from crashmetrics.correlation import iso18571
                rating = float(iso18571(fa.time / 1000.0, fa[sid], fb[sid],
                                        fb.time / 1000.0).rating)
            ia, ib = ma[sid].impulse, mb[sid].impulse
            section_rows.append(SectionChange(
                sid, fa.names[sid], (ma[sid].peak, mb[sid].peak), (ia, ib),
                100.0 * (ib - ia) / ia if ia > 0 else math.nan, rating))
    return RunComparison(baseline.name, variant.name, total, tuple(parts),
                         tuple(section_rows), tuple(group_rows), tuple(culprits),
                         tuple(notes))


@dataclass(frozen=True)
class EnergyMatrix:
    """Absorbed energy of parts (rows) in several runs (columns), kJ."""

    runs: tuple[str, ...]
    part_ids: tuple[int, ...]
    names: tuple[str, ...]
    values: FloatArray
    """(part, run), kJ; NaN where a run lacks the part."""

    def table(self, top: int | None = None, relative_to: int | None = 0) -> str:
        """Markdown table, parts by their largest energy; with
        ``relative_to`` (a run index) the other runs show the change."""
        order = np.argsort(-np.nanmax(self.values, axis=1))
        if top:
            order = order[:top]
        head = "| Part | " + " | ".join(self.runs) + " |"
        lines = [head, "| --- |" + " --- |" * len(self.runs)]
        for i in order:
            cells = []
            for j in range(len(self.runs)):
                v = self.values[i, j]
                if relative_to is not None and j != relative_to:
                    ref = self.values[i, relative_to]
                    cells.append("-" if not np.isfinite(v) else
                                 f"{_num(v)} ({_num(v - ref, 3, True)})"
                                 if np.isfinite(ref) else _num(v))
                else:
                    cells.append("-" if not np.isfinite(v) else f"{_num(v)}")
            lines.append(f"| {self.names[i]} ({self.part_ids[i]}) | "
                         + " | ".join(cells) + " |")
        return "\n".join(lines)

    def to_csv(self, path: str | Path) -> Path:
        """Write ``part_id,name,<run>...`` (kJ)."""
        target = Path(path)
        rows = ["part_id,name," + ",".join(self.runs)]
        for i, pid in enumerate(self.part_ids):
            name = self.names[i].replace(",", " ")
            rows.append(f"{pid},{name}," + ",".join(
                "" if not np.isfinite(v) else f"{v:.6g}" for v in self.values[i]))
        target.write_text("\n".join(rows) + "\n")
        return target


def energy_matrix(runs: Sequence[CrashRun], *,
                  exclude: Selector | Iterable[Selector] | None = None) -> EnergyMatrix:
    """Absorbed energy at the end of each run, parts by ID."""
    finals = [_final(r) for r in runs]
    ids = list(dict.fromkeys(i for f in finals for i in f))
    drop: set[int] = set()
    if exclude is not None:
        for r in runs:
            try:
                drop |= set(select_parts(r, exclude))
            except KeyError:
                pass
    ids = [i for i in ids if i not in drop]
    names = []
    for i in ids:
        owner = next(r for r, f in zip(runs, finals) if i in f)
        names.append(owner.part_name(i))
    values = np.array([[f.get(i, math.nan) for f in finals] for i in ids])
    return EnergyMatrix(tuple(r.name for r in runs), tuple(ids), tuple(names), values)


# --- Report -----------------------------------------------------------------------


def loadpath_report(
    run: CrashRun,
    *,
    baseline: CrashRun | None = None,
    exclude: Selector | Iterable[Selector] | None = None,
    groups: Mapping[str, Selector | Iterable[Selector]] | None = None,
    paths: Mapping[str, Selector | Iterable[Selector]] | None = None,
    target: Mapping[str, float] | None = None,
    chains: Mapping[str, Sequence[Selector | Iterable[Selector]]] | None = None,
    top: int = 10,
    cfc: float | None = None,
) -> str:
    """Markdown report: energy ranking, load split, crush sequence and,
    with ``baseline``, the comparison."""
    lines = [f"# Load paths: {run.name}", ""]
    if run.source:
        lines += [f"Source: `{run.source}`", ""]
    if run.energies is not None:
        ranking = energy_ranking(run, exclude=exclude, groups=groups)
        lines += ["## Energy absorption", "", ranking.table(top), ""]
    if paths and run.sections is not None:
        split = load_split(section_forces(run, cfc=cfc), paths, target=target)
        lines += ["## Load split", "", "| Path | Share | Impulse kN ms | Peak kN |",
                  "| --- | --- | --- | --- |"]
        lines += [f"| {p} | {split.share[i]:.1f} %"
                  + (f" (target {split.target[i]:.0f} %)" if split.target else "")
                  + f" | {_num(split.impulse[i])} | {_num(split.peak[i])} |"
                  for i, p in enumerate(split.paths)]
        lines += [f"- ⚠️ {w}" for w in split.warnings] + [""]
    if chains and run.energies is not None:
        lines += ["## Crush sequence", ""]
        for c in crush_sequence(run, chains):
            mark = "✅" if c.passed else "❌"
            order = " → ".join(f"{s.name} ({_ms(s.onset)} ms)" if s.crushed
                               else f"~~{s.name}~~ (not crushed)" for s in c.stages)
            lines.append(f"- {mark} **{c.chain}**: {order}")
            lines += [f"  - ❌ {v}" for v in c.violations]
            lines += [f"  - ⚠️ {w}" for w in c.warnings]
        lines.append("")
    if baseline is not None:
        comp = compare_runs(baseline, run, exclude=exclude, groups=groups, cfc=cfc)
        lines += [f"## Against {baseline.name}", "", "```text", comp.summary(), "```",
                  ""]
    return "\n".join(lines)

