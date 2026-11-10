"""Spot weld and connection failure, in one run and across runs.

A load path only works while its connections hold. LS-DYNA writes the
force of every spot weld (and other ``*CONSTRAINED`` connections) to
``swforc``; this module turns that file into answers:

- **Runs**: `load_welds` reads ``swforc`` into a `WeldRun` (forces in
  kN, time in ms, failure time of each weld).
- **Every weld**: `weld_summary` gives peak axial and shear force, the
  forces just before failure, and with `WeldLimits` the utilisation
  (share of the failing load reached) of each weld; `WeldSummary.failed`
  and `WeldSummary.critical` list the failed welds and the ones close to
  failure.
- **Failure over time**: `failure_history` gives the number of failed
  welds over time, the failure sequence, the first failure per group
  and bursts (several welds of a group failing within a short time:
  unzipping).
- **Comparison**: `compare_welds` gives the welds that fail only in the
  variant, those that no longer fail, earlier and later failures, counts
  per group and the largest utilisation changes.
- `weld_report` puts it in one Markdown page.

swforc has no titles, so groups are given as name -> weld IDs (for
example ID ranges of a flange; `groups_by_id` builds them from the
numbering). Forces are in **kN** and times in
**ms** for any unit system (`crashmetrics.loadpath.UNITS`).
`crashmetrics.synthetic` writes runs with failing welds to try this
without a solver.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.loadpath import UNITS, _ms, _num
from crashmetrics.lsdyna_ascii import AsciiOutput, read_swforc

__all__ = [
    "Burst",
    "FailureHistory",
    "GroupCount",
    "Weld",
    "WeldChange",
    "WeldComparison",
    "WeldLimits",
    "WeldRun",
    "WeldSummary",
    "compare_welds",
    "failure_history",
    "groups_by_id",
    "load_welds",
    "weld_report",
    "weld_summary",
]

FloatArray = NDArray[np.float64]
Groups = Mapping[str, Iterable[int]]
"""Group name -> weld IDs (a list, a ``range`` ...). A weld in several
groups counts in the first."""


# --- Limits ---------------------------------------------------------------------


@dataclass(frozen=True)
class WeldLimits:
    """Force-based failure criterion of a spot weld,
    ``(axial / axial_limit)^n + (shear / shear_limit)^m >= 1``
    (``*CONSTRAINED_SPOTWELD``; with n = m = 2 the usual ellipse).
    Limits in kN. Axial compression does not count unless
    ``compression`` is set.
    """

    axial: float
    shear: float
    n: float = 2.0
    m: float = 2.0
    compression: bool = False

    def __post_init__(self) -> None:
        if self.axial <= 0 or self.shear <= 0 or self.n <= 0 or self.m <= 0:
            raise ValueError("Limits and exponents must be positive.")

    def function(self, axial: ArrayLike, shear: ArrayLike) -> FloatArray:
        """The failure function (1 or more: failed)."""
        a = np.asarray(axial, dtype=float)
        a = np.abs(a) if self.compression else np.maximum(a, 0.0)
        s = np.abs(np.asarray(shear, dtype=float))
        return np.asarray((a / self.axial) ** self.n + (s / self.shear) ** self.m)

    def utilisation(self, axial: ArrayLike, shear: ArrayLike) -> FloatArray:
        """Share of the failing load reached: 1 / the factor by which
        both forces could grow until the criterion is met (0.8: at 80 %
        of failure). Equal to ``function^(1/n)`` when n = m."""
        f = self.function(axial, shear)
        if self.n == self.m:
            return np.asarray(f ** (1.0 / self.n))
        a = np.asarray(axial, dtype=float)
        a = np.abs(a) if self.compression else np.maximum(a, 0.0)
        s = np.abs(np.asarray(shear, dtype=float))
        # Solve (a u)^n + (s u)^m = 1 for the load factor u by bisection
        # in log space; utilisation = 1 / u.
        lo = np.full(f.shape, -12.0)
        hi = np.full(f.shape, 12.0)
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            u = np.exp(mid)
            over = (a * u / self.axial) ** self.n + (s * u / self.shear) ** self.m >= 1
            hi = np.where(over, mid, hi)
            lo = np.where(over, lo, mid)
        return np.asarray(np.where(f > 0, np.exp(-0.5 * (lo + hi)), 0.0))


# --- Runs -----------------------------------------------------------------------


@dataclass(frozen=True)
class WeldRun:
    """Spot weld forces of one run."""

    name: str
    time: FloatArray
    """ms."""
    ids: tuple[int, ...]
    axial: FloatArray
    """(time, weld), kN; tension positive."""
    shear: FloatArray
    """(time, weld), kN."""
    failure_time: FloatArray
    """ms per weld; NaN if it holds to the end."""
    measure: FloatArray | None = None
    """The file's own failure measure (time, weld) where it prints
    fractions (some weld materials), else None."""
    source: str = ""

    def index(self, weld_id: int) -> int:
        try:
            return self.ids.index(int(weld_id))
        except ValueError:
            raise KeyError(f"{self.name}: no weld {weld_id}.") from None

    @property
    def failed(self) -> tuple[int, ...]:
        """IDs of the failed welds, by failure time."""
        order = np.argsort(self.failure_time, kind="stable")
        return tuple(self.ids[k] for k in order if np.isfinite(self.failure_time[k]))


def _from_output(out: AsciiOutput, name: str, unit_system: str, source: str) -> WeldRun:
    if unit_system not in UNITS:
        raise ValueError(f"Unknown unit_system {unit_system!r}; known: {list(UNITS)}.")
    fk, _, tk = UNITS[unit_system]
    t = out.time * tk
    flag = np.nan_to_num(out.data["failure"])
    failed = flag >= 1.0
    first = np.where(failed.any(axis=0), t[np.argmax(failed, axis=0)], math.nan)
    if "failure_time" in out.data:
        printed = np.nanmin(np.where(np.isfinite(out.data["failure_time"]),
                                     out.data["failure_time"], np.inf), axis=0) * tk
        first = np.where(np.isfinite(printed) & ~(printed > first), printed, first)
    fractions = np.any((flag > 0) & (flag < 1))
    return WeldRun(name, t, tuple(int(i) for i in out.ids),
                   np.nan_to_num(out.data["axial"]) * fk,
                   np.nan_to_num(out.data["shear"]) * fk, first,
                   flag if fractions else None, source)


def load_welds(path: str | Path | AsciiOutput, name: str | None = None, *,
               unit_system: str = "mm-ms-kg") -> WeldRun:
    """Read the spot weld forces of a run.

    ``path`` is a run folder (with ``swforc``, ``SWFORC`` or a job prefix
    such as ``run1.swforc``), a swforc file, or an `AsciiOutput` already
    read. A weld counts as failed from the first state LS-DYNA marks it
    ``failure``. ``name`` defaults to the folder name.
    """
    if isinstance(path, AsciiOutput):
        return _from_output(path, name or "run", unit_system, "")
    target = Path(path)
    if target.is_dir():
        found = [target / "swforc", target / "SWFORC"] + sorted(
            p for p in target.iterdir() if p.name.lower().endswith(".swforc"))
        files = [p for p in found if p.is_file()]
        if not files:
            raise FileNotFoundError(f"No swforc in {target}.")
        file, label = files[0], target.name
    elif target.is_file():
        file, label = target, target.parent.name
    else:
        raise FileNotFoundError(f"{target} does not exist.")
    return _from_output(read_swforc(file), name or label, unit_system, str(file))


def groups_by_id(run: WeldRun, divisor: int = 1000,
                 names: Mapping[int, str] | None = None) -> dict[str, list[int]]:
    """Groups from the weld numbering: welds with the same ``ID //
    divisor`` form a group, named ``names[prefix]`` or ``"<prefix>xxx"``
    (for models that number welds by part or flange)."""
    if divisor < 1:
        raise ValueError("divisor must be 1 or more.")
    digits = len(str(divisor)) - 1
    out: dict[str, list[int]] = {}
    for i in run.ids:
        prefix = i // divisor
        label = (names or {}).get(prefix) or f"{prefix}{'x' * digits}"
        out.setdefault(label, []).append(i)
    return out


def _group_of(ids: Iterable[int], groups: Groups | None) -> dict[int, str]:
    out: dict[int, str] = {}
    for gname, members in (groups or {}).items():
        for i in members:
            out.setdefault(int(i), gname)
    return {i: out.get(int(i), "") for i in ids}


# --- Summary of every weld ------------------------------------------------------


@dataclass(frozen=True)
class Weld:
    """One weld over the run (kN, ms)."""

    weld_id: int
    group: str
    peak_axial: float
    peak_shear: float
    peak_time: float
    """ms of the peak resultant force (of the peak utilisation with limits)."""
    utilisation: float
    """Peak share of the failing load (NaN without limits for this weld)."""
    failed: bool
    failure_time: float
    axial_at_failure: float
    """Forces at the last state before failure (NaN if the weld holds)."""
    shear_at_failure: float


@dataclass(frozen=True)
class WeldSummary:
    """Every weld of a run."""

    run: str
    welds: tuple[Weld, ...]
    notes: tuple[str, ...] = ()

    @property
    def failed(self) -> tuple[Weld, ...]:
        """Failed welds, first failure first."""
        return tuple(sorted((w for w in self.welds if w.failed),
                            key=lambda w: (w.failure_time, w.weld_id)))

    def critical(self, threshold: float = 0.8) -> tuple[Weld, ...]:
        """Welds that hold but reach ``threshold`` of their failing load,
        highest first (needs limits)."""
        close = [w for w in self.welds if not w.failed
                 and math.isfinite(w.utilisation) and w.utilisation >= threshold]
        return tuple(sorted(close, key=lambda w: -w.utilisation))

    def groups(self) -> tuple[GroupCount, ...]:
        """Welds, failed welds and highest utilisation per group."""
        out: dict[str, list[Weld]] = {}
        for w in self.welds:
            out.setdefault(w.group or "(no group)", []).append(w)
        rows = []
        for gname, ws in out.items():
            failed = [w for w in ws if w.failed]
            util = [w.utilisation for w in ws if math.isfinite(w.utilisation)]
            rows.append(GroupCount(
                gname, len(ws), len(failed),
                min((w.failure_time for w in failed), default=math.nan),
                max(util, default=math.nan)))
        return tuple(rows)

    def table(self, top: int = 10) -> str:
        """Markdown: groups, failed welds (first ``top``) and critical welds."""
        failed = self.failed
        lines = [f"Spot welds, {self.run}: {len(self.welds)} welds, "
                 f"{len(failed)} failed", "",
                 "| Group | Welds | Failed | First failure ms | Highest utilisation |",
                 "| --- | --- | --- | --- | --- |"]
        lines += [f"| {g.name} | {g.welds} | {g.failed} | {_ms(g.first_failure)} | "
                  f"{_pct(g.utilisation)} |" for g in self.groups()]
        if failed:
            lines += ["", "| Failed weld | Group | At ms | Axial kN before | "
                      "Shear kN before | Peak axial | Peak shear |",
                      "| --- | --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {w.weld_id} | {w.group or '-'} | {_ms(w.failure_time)} | "
                      f"{_num(w.axial_at_failure, 3)} | {_num(w.shear_at_failure, 3)}"
                      f" | {_num(w.peak_axial, 3)} | {_num(w.peak_shear, 3)} |"
                      for w in failed[:top]]
            if len(failed) > top:
                lines.append(f"| ... {len(failed) - top} more | | | | | | |")
        close = self.critical()
        if close:
            lines += ["", "| Critical weld (holds) | Group | Utilisation | At ms | "
                      "Peak axial | Peak shear |",
                      "| --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {w.weld_id} | {w.group or '-'} | {_pct(w.utilisation)} | "
                      f"{_ms(w.peak_time)} | {_num(w.peak_axial, 3)} | "
                      f"{_num(w.peak_shear, 3)} |" for w in close[:top]]
        return "\n".join(lines)


@dataclass(frozen=True)
class GroupCount:
    """Welds of one group."""

    name: str
    welds: int
    failed: int
    first_failure: float
    """ms, NaN if none failed."""
    utilisation: float
    """Highest peak utilisation of the group (NaN without limits)."""


def _pct(value: float) -> str:
    return "-" if not math.isfinite(value) else f"{100 * value:.0f} %"


def _limits_of(limits: WeldLimits | Mapping[str, WeldLimits] | None, group: str
               ) -> WeldLimits | None:
    if limits is None or isinstance(limits, WeldLimits):
        return limits
    return limits.get(group) or limits.get("default")


def weld_summary(run: WeldRun, *, limits: WeldLimits | Mapping[str, WeldLimits] | None
                 = None, groups: Groups | None = None) -> WeldSummary:
    """Peak forces, utilisation and failure of every weld.

    Parameters
    ----------
    limits:
        One `WeldLimits` for all welds, or group name -> limits (a
        ``"default"`` entry covers the other welds). Without limits the
        utilisation is NaN, unless the file prints its own failure
        measure (then its peak is used).
    groups:
        Group name -> weld IDs.
    """
    group = _group_of(run.ids, groups)
    notes = []
    if groups:
        unknown = sorted({int(i) for m in groups.values() for i in m} - set(run.ids))
        if unknown:
            notes.append(f"{len(unknown)} group weld IDs are not in the run "
                         f"(first: {unknown[:5]})")
    resultant = np.hypot(np.maximum(run.axial, 0.0), run.shear)
    welds = []
    for j, wid in enumerate(run.ids):
        ft = float(run.failure_time[j])
        failed = math.isfinite(ft)
        lim = _limits_of(limits, group[wid])
        if lim is not None:
            u = lim.utilisation(run.axial[:, j], run.shear[:, j])
            k = int(np.argmax(u))
            util = float(u[k])
        elif run.measure is not None:
            k = int(np.argmax(run.measure[:, j]))
            util = float(run.measure[k, j])
        else:
            k = int(np.argmax(resultant[:, j]))
            util = math.nan
        before = int(np.searchsorted(run.time, ft)) - 1 if failed else -1
        welds.append(Weld(
            wid, group[wid], float(np.max(run.axial[:, j])),
            float(np.max(np.abs(run.shear[:, j]))), float(run.time[k]), util, failed,
            ft, float(run.axial[before, j]) if before >= 0 else math.nan,
            float(run.shear[before, j]) if before >= 0 else math.nan))
    if run.measure is not None and limits is None:
        notes.append("utilisation is the file's own failure measure")
    return WeldSummary(run.name, tuple(welds), tuple(notes))


# --- Failure over time ----------------------------------------------------------


@dataclass(frozen=True)
class Burst:
    """Several welds of one group failing close together (unzipping)."""

    group: str
    start: float
    end: float
    welds: tuple[int, ...]


@dataclass(frozen=True)
class FailureHistory:
    """Weld failures over time."""

    run: str
    time: FloatArray
    """ms."""
    count: FloatArray
    """Failed welds at each time."""
    by_group: dict[str, FloatArray]
    sequence: tuple[tuple[float, int, str], ...]
    """(ms, weld ID, group), in order of failure."""
    first: dict[str, tuple[float, int]]
    """Group -> (ms, weld ID) of its first failure."""
    bursts: tuple[Burst, ...]

    def summary(self, top: int = 8) -> str:
        n = len(self.sequence)
        if not n:
            return f"Weld failures, {self.run}: none"
        lines = [f"Weld failures, {self.run}: {n}, first at "
                 f"{_ms(self.sequence[0][0])} ms (weld {self.sequence[0][1]}"
                 + (f", {self.sequence[0][2]})" if self.sequence[0][2] else ")")]
        for g, (t, wid) in self.first.items():
            total = int(self.by_group[g][-1])
            lines.append(f"  {g}: {total} failed, first weld {wid} at {_ms(t)} ms")
        for b in self.bursts[:top]:
            lines.append(f"  burst: {len(b.welds)} welds of {b.group or 'no group'} "
                         f"between {_ms(b.start)} and {_ms(b.end)} ms")
        return "\n".join(lines)


def failure_history(run: WeldRun, *, groups: Groups | None = None,
                    burst_window: float = 1.0, burst_size: int = 3) -> FailureHistory:
    """Failed welds over time, the failure sequence and bursts.

    A burst is ``burst_size`` or more welds of one group, each failing
    within ``burst_window`` ms of the one before (welds outside every
    group form one group of their own).
    """
    group = _group_of(run.ids, groups)
    ft = run.failure_time
    failed = np.isfinite(ft)
    count = (run.time[:, None] >= np.where(failed, ft, np.inf)[None, :])
    names = list(dict.fromkeys(g for g in group.values() if g))
    by_group = {g: count[:, [j for j, i in enumerate(run.ids) if group[i] == g]]
                .sum(axis=1).astype(float) for g in names}
    seq = sorted((float(ft[j]), run.ids[j], group[run.ids[j]])
                 for j in np.flatnonzero(failed))
    first: dict[str, tuple[float, int]] = {}
    for t, wid, g in seq:
        if g:
            first.setdefault(g, (t, wid))
    bursts = []
    for g in [*names, ""]:
        members = [(t, wid) for t, wid, gg in seq if gg == g]
        chain: list[tuple[float, int]] = []
        for item in [*members, (math.inf, 0)]:
            if chain and item[0] - chain[-1][0] > burst_window:
                if len(chain) >= burst_size:
                    bursts.append(Burst(g, chain[0][0], chain[-1][0],
                                        tuple(w for _, w in chain)))
                chain = []
            chain.append(item)
    bursts.sort(key=lambda b: b.start)
    return FailureHistory(run.name, run.time, count.sum(axis=1).astype(float),
                          by_group, tuple(seq), first, tuple(bursts))


# --- Comparison -----------------------------------------------------------------


@dataclass(frozen=True)
class WeldChange:
    """One weld in two runs."""

    weld_id: int
    group: str
    failure_time: tuple[float, float]
    """ms in the baseline and the variant (NaN: holds)."""
    utilisation: tuple[float, float]
    peak_shear: tuple[float, float]
    peak_axial: tuple[float, float]


@dataclass(frozen=True)
class WeldComparison:
    """Weld failures of a variant against a baseline."""

    baseline: str
    variant: str
    failed: tuple[int, int]
    """Number of failed welds in each run."""
    new_failures: tuple[WeldChange, ...]
    """Fail in the variant only, first failure first."""
    recovered: tuple[WeldChange, ...]
    """Fail in the baseline only."""
    earlier: tuple[WeldChange, ...]
    """Fail in both, sooner in the variant (largest shift first)."""
    later: tuple[WeldChange, ...]
    increased: tuple[WeldChange, ...]
    """Welds holding in both, by utilisation increase (largest first)."""
    groups: tuple[tuple[str, int, int, int], ...]
    """(group, welds, failed in baseline, failed in variant)."""
    notes: tuple[str, ...] = ()

    def summary(self, top: int = 5) -> str:
        a, b = self.failed
        lines = [f"{self.variant} against {self.baseline}: failed welds {a} -> {b} "
                 f"({b - a:+d}); {len(self.new_failures)} new, "
                 f"{len(self.recovered)} no longer fail, {len(self.earlier)} earlier, "
                 f"{len(self.later)} later"]
        changed = [g for g in self.groups if g[2] != g[3]]
        if changed:
            lines.append("Groups that changed:")
            lines += [f"  {g}: {x} -> {y} of {n} welds failed"
                      for g, n, x, y in changed]
        if self.new_failures:
            lines.append("New failures, first first:")
            lines += [f"  weld {c.weld_id}" + (f" ({c.group})" if c.group else "")
                      + f" at {_ms(c.failure_time[1])} ms"
                      + (f" ({_pct(c.utilisation[0])} of its limit in "
                         f"{self.baseline})"
                         if math.isfinite(c.utilisation[0]) else "")
                      for c in self.new_failures[:top]]
            if len(self.new_failures) > top:
                lines.append(f"  ... {len(self.new_failures) - top} more")
        if self.earlier:
            lines.append("Earlier failures:")
            lines += [f"  weld {c.weld_id}: {_ms(c.failure_time[0])} -> "
                      f"{_ms(c.failure_time[1])} ms" for c in self.earlier[:top]]
        rising = [c for c in self.increased
                  if c.utilisation[1] - c.utilisation[0] >= 0.05]
        if rising:
            lines.append("Welds that hold but are loaded more:")
            lines += [f"  weld {c.weld_id}" + (f" ({c.group})" if c.group else "")
                      + f": {_pct(c.utilisation[0])} -> {_pct(c.utilisation[1])}"
                      for c in rising[:top]]
        lines += [f"Note: {n}" for n in self.notes]
        return "\n".join(lines)


def compare_welds(baseline: WeldRun, variant: WeldRun, *,
                  limits: WeldLimits | Mapping[str, WeldLimits] | None = None,
                  groups: Groups | None = None,
                  time_tolerance: float = 0.5) -> WeldComparison:
    """Weld failures and loading of a variant against a baseline.

    Welds are matched by ID. A failure counts as earlier or later when
    its time differs by more than ``time_tolerance`` ms.
    """
    sa = {w.weld_id: w for w in weld_summary(baseline, limits=limits,
                                             groups=groups).welds}
    sb = {w.weld_id: w for w in weld_summary(variant, limits=limits,
                                             groups=groups).welds}
    common = [i for i in sa if i in sb]
    notes = []
    for run, mine, other in ((baseline, sa, sb), (variant, sb, sa)):
        only = [i for i in mine if i not in other]
        if only:
            notes.append(f"{len(only)} welds only in {run.name} (first: {only[:5]})")

    def change(i: int) -> WeldChange:
        a, b = sa[i], sb[i]
        return WeldChange(i, a.group, (a.failure_time, b.failure_time),
                          (a.utilisation, b.utilisation),
                          (a.peak_shear, b.peak_shear), (a.peak_axial, b.peak_axial))

    new = sorted((change(i) for i in common if sb[i].failed and not sa[i].failed),
                 key=lambda c: (c.failure_time[1], c.weld_id))
    gone = sorted((change(i) for i in common if sa[i].failed and not sb[i].failed),
                  key=lambda c: (c.failure_time[0], c.weld_id))
    both = [change(i) for i in common if sa[i].failed and sb[i].failed]
    earlier = sorted((c for c in both
                      if c.failure_time[1] < c.failure_time[0] - time_tolerance),
                     key=lambda c: c.failure_time[1] - c.failure_time[0])
    later = sorted((c for c in both
                    if c.failure_time[1] > c.failure_time[0] + time_tolerance),
                   key=lambda c: c.failure_time[0] - c.failure_time[1])
    holding = [change(i) for i in common if not sa[i].failed and not sb[i].failed
               and math.isfinite(sa[i].utilisation)
               and math.isfinite(sb[i].utilisation)]
    increased = sorted(holding, key=lambda c: c.utilisation[0] - c.utilisation[1])
    names = list(dict.fromkeys(sa[i].group for i in common))
    group_rows = tuple(
        (g or "(no group)", sum(1 for i in common if sa[i].group == g),
         sum(1 for i in common if sa[i].group == g and sa[i].failed),
         sum(1 for i in common if sa[i].group == g and sb[i].failed)) for g in names)
    return WeldComparison(
        baseline.name, variant.name,
        (sum(w.failed for w in sa.values()), sum(w.failed for w in sb.values())),
        tuple(new), tuple(gone), tuple(earlier), tuple(later), tuple(increased),
        group_rows, tuple(notes))


# --- Report ---------------------------------------------------------------------


def weld_report(run: WeldRun, *, baseline: WeldRun | None = None,
                limits: WeldLimits | Mapping[str, WeldLimits] | None = None,
                groups: Groups | None = None, top: int = 10) -> str:
    """Markdown report: groups, failed and critical welds, the failure
    sequence and, with ``baseline``, the comparison."""
    summary = weld_summary(run, limits=limits, groups=groups)
    history = failure_history(run, groups=groups)
    lines = [f"# Spot welds: {run.name}", ""]
    if run.source:
        lines += [f"Source: `{run.source}`", ""]
    lines += [summary.table(top), ""]
    lines += [f"- ⚠️ {n}" for n in summary.notes]
    lines += ["", "## Failure over time", "", "```text", history.summary(), "```", ""]
    if baseline is not None:
        comp = compare_welds(baseline, run, limits=limits, groups=groups)
        lines += [f"## Against {baseline.name}", "", "```text", comp.summary(top),
                  "```", ""]
    return "\n".join(lines)
