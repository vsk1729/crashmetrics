"""Energy checks for explicit crash simulations, for any load case.

Functions
---------
check_energies
    Run the global and per-part energy checks and return a report.

Classes
-------
GlobalEnergies
    Global energy time histories (LS-DYNA glstat).
PartEnergies
    Per-part energy time histories (LS-DYNA matsum).
EnergyLimits
    Acceptance limits; every one can be changed or switched off.

The checks are solver-agnostic: fill :class:`GlobalEnergies` and
:class:`PartEnergies` from any source, or read LS-DYNA output with
:mod:`crashmetrics.lsdyna`. All energies must use one consistent unit.

Checks
------
=========================  ==================================================
Check                      Value compared with its limit
=========================  ==================================================
energy_ratio               total / (initial total + external work), min and
                           max over time (glstat's own ratio if given)
hourglass                  peak hourglass / peak internal energy
negative_contact           most negative sliding (contact) energy / reference
damping                    peak system damping energy / reference
added_mass                 peak added mass, % of the model mass
eroded_energy              peak eroded energy / reference (reported only)
part_hourglass             per part: peak hourglass / peak internal energy
part_negative_internal     per part: most negative / peak internal energy
=========================  ==================================================

The reference energy is the largest value of initial total energy plus
external work, so the checks work for impacts (initial kinetic energy)
and for prescribed-motion or quasi-static cases (external work) alike.
Part checks cover parts whose peak internal energy is at least
``part_min_internal_share`` of the model's peak internal energy.

Default limits: hourglass energy below 10 % of internal energy, globally
and per part, is LS-DYNA's published rule of thumb. The other defaults
are common rules of thumb, not a standard. Set your own guideline values
in :class:`EnergyLimits`.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "EnergyCheck",
    "EnergyLimits",
    "EnergyReport",
    "GlobalEnergies",
    "PartEnergies",
    "PartResult",
    "check_energies",
    "normalise_name",
]

FloatArray = NDArray[np.float64]

# Normalised names (lower case, words joined by "_") -> GlobalEnergies field.
_GLOBAL_ALIASES: dict[str, str] = {
    "time": "time",
    "time_step": "time_step",
    "kinetic_energy": "kinetic",
    "internal_energy": "internal",
    "hourglass_energy": "hourglass",
    "sliding_interface_energy": "sliding",
    "sliding_energy": "sliding",
    "contact_energy": "sliding",
    "external_work": "external_work",
    "system_damping_energy": "damping",
    "damping_energy": "damping",
    "stonewall_energy": "rigidwall",
    "rigidwall_energy": "rigidwall",
    "rigid_wall_energy": "rigidwall",
    "eroded_kinetic_energy": "eroded_kinetic",
    "eroded_internal_energy": "eroded_internal",
    "eroded_hourglass_energy": "eroded_hourglass",
    "total_energy": "total",
    "total_energy_initial_energy": "energy_ratio",
    "energy_ratio": "energy_ratio",
    "added_mass": "added_mass",
    "percentage_increase": "added_mass_percent",
    "percent_increase": "added_mass_percent",
    "added_mass_percent": "added_mass_percent",
}

# Normalised names -> PartEnergies field.
_PART_ALIASES: dict[str, str] = {
    "inten": "internal",
    "internal_energy": "internal",
    "kinen": "kinetic",
    "kinetic_energy": "kinetic",
    "hgeng": "hourglass",
    "hourglass_energy": "hourglass",
    "plus_mass": "added_mass",
    "added_mass": "added_mass",
}


def normalise_name(name: str) -> str:
    """Lower-case a channel name and join its words with underscores."""
    out = []
    word = ""
    for ch in name.strip().lower():
        if ch.isalnum():
            word += ch
        else:
            if word:
                out.append(word)
            word = ""
    if word:
        out.append(word)
    return "_".join(out)


def _series(values: ArrayLike, name: str, length: int | None) -> FloatArray:
    a = np.asarray(values, dtype=float)
    if a.ndim != 1:
        raise ValueError(f"{name} must be a 1D array.")
    if length is not None and len(a) != length:
        raise ValueError(f"{name} has {len(a)} samples, time has {length}.")
    return a


@dataclass
class GlobalEnergies:
    """Global energy time histories, in one consistent energy unit.

    Only ``time``, ``kinetic`` and ``internal`` are required; checks that
    need a missing channel are reported as skipped.
    """

    time: FloatArray
    kinetic: FloatArray
    internal: FloatArray
    hourglass: FloatArray | None = None
    sliding: FloatArray | None = None
    """Sliding interface (contact) energy."""
    external_work: FloatArray | None = None
    damping: FloatArray | None = None
    """System damping energy."""
    rigidwall: FloatArray | None = None
    eroded_kinetic: FloatArray | None = None
    eroded_internal: FloatArray | None = None
    eroded_hourglass: FloatArray | None = None
    total: FloatArray | None = None
    """Total energy; computed from the components if not given."""
    energy_ratio: FloatArray | None = None
    """Solver's energy ratio; computed if not given."""
    added_mass: FloatArray | None = None
    added_mass_percent: FloatArray | None = None
    """Added mass as a percentage of the model mass."""
    time_step: FloatArray | None = None
    extra: dict[str, FloatArray] = field(default_factory=dict)
    """Other channels, by normalised name."""

    def __post_init__(self) -> None:
        self.time = _series(self.time, "time", None)
        n = len(self.time)
        if n < 2:
            raise ValueError("At least two time samples are needed.")
        for f in fields(self):
            if f.name in ("time", "extra"):
                continue
            value = getattr(self, f.name)
            if value is not None:
                setattr(self, f.name, _series(value, f.name, n))
        self.extra = {k: _series(v, k, n) for k, v in self.extra.items()}

    @classmethod
    def from_mapping(cls, data: Mapping[str, ArrayLike]) -> "GlobalEnergies":
        """Build from named channels, such as glstat or binout variables.

        Names are matched case-insensitively and ignoring punctuation, so
        ``"kinetic energy"``, ``"kinetic_energy"`` and
        ``"Kinetic Energy"`` all work. Unknown channels go to ``extra``.
        """
        known: dict[str, ArrayLike] = {}
        extra: dict[str, ArrayLike] = {}
        for name, values in data.items():
            key = normalise_name(name)
            target = _GLOBAL_ALIASES.get(key)
            if target is None:
                extra[key] = values
            elif target not in known:
                known[target] = values
        missing = [k for k in ("time", "kinetic", "internal") if k not in known]
        if missing:
            raise ValueError(
                f"Missing required channels {missing}; found "
                f"{sorted(normalise_name(n) for n in data)}."
            )
        return cls(**known, extra=extra)  # type: ignore[arg-type]

    def total_energy(self) -> FloatArray:
        """Total energy: the given total, or the sum of the components."""
        if self.total is not None:
            return self.total
        total = self.kinetic + self.internal
        for part in (self.hourglass, self.sliding, self.damping, self.rigidwall):
            if part is not None:
                total = total + part
        return total

    def ratio(self) -> FloatArray:
        """Energy ratio: the given one, or total / (initial + external work).

        As in LS-DYNA, the ratio is 1 where the denominator is below 1e-8.
        """
        if self.energy_ratio is not None:
            return self.energy_ratio
        total = self.total_energy()
        work = self.external_work if self.external_work is not None else 0.0
        denominator = total[0] + work
        safe = np.where(np.abs(denominator) < 1e-8, 1.0, denominator)
        return np.where(np.abs(denominator) < 1e-8, 1.0, total / safe)

    def reference_energy(self) -> float:
        """Largest value of initial total energy plus external work."""
        work = self.external_work if self.external_work is not None else 0.0
        return float(np.nanmax(self.total_energy()[0] + work * np.ones_like(self.time)))


@dataclass
class PartEnergies:
    """Per-part energy time histories, arrays of shape (time, part)."""

    time: FloatArray
    part_ids: NDArray[np.int64]
    internal: FloatArray
    kinetic: FloatArray | None = None
    hourglass: FloatArray | None = None
    added_mass: FloatArray | None = None
    """Added mass from mass scaling (LS-DYNA matsum ``+mass``)."""
    part_names: dict[int, str] = field(default_factory=dict)
    extra: dict[str, FloatArray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.time = _series(self.time, "time", None)
        self.part_ids = np.asarray(self.part_ids, dtype=np.int64)
        if self.part_ids.ndim != 1:
            raise ValueError("part_ids must be a 1D array.")
        self.part_names = {int(k): str(v) for k, v in self.part_names.items()}
        shape = (len(self.time), len(self.part_ids))
        for name in ("internal", "kinetic", "hourglass", "added_mass"):
            value = getattr(self, name)
            if value is None:
                continue
            a = np.asarray(value, dtype=float)
            if a.shape != shape:
                raise ValueError(f"{name} has shape {a.shape}, expected {shape}.")
            setattr(self, name, a)
        self.extra = {k: np.asarray(v, dtype=float) for k, v in self.extra.items()}

    @classmethod
    def from_mapping(
        cls,
        time: ArrayLike,
        part_ids: ArrayLike,
        data: Mapping[str, ArrayLike],
        part_names: Mapping[int, str] | None = None,
    ) -> "PartEnergies":
        """Build from named (time, part) arrays, such as matsum variables.

        ``"internal_energy"`` / ``"inten"``, ``"kinetic_energy"`` /
        ``"kinen"``, ``"hourglass_energy"`` / ``"hgeng"`` and
        ``"added_mass"`` / ``"+mass"`` are recognised.
        """
        known: dict[str, ArrayLike] = {}
        extra: dict[str, ArrayLike] = {}
        for name, values in data.items():
            key = normalise_name(name)
            target = _PART_ALIASES.get(key)
            if target is None:
                extra[key] = values
            elif target not in known:
                known[target] = values
        if "internal" not in known:
            raise ValueError("Missing the part internal energy channel.")
        arrays: dict[str, Any] = {
            k: np.asarray(v, dtype=float) for k, v in known.items()
        }
        return cls(
            time=np.asarray(time, dtype=float),
            part_ids=np.asarray(part_ids, dtype=np.int64),
            part_names=dict(part_names or {}),
            extra={k: np.asarray(v, dtype=float) for k, v in extra.items()},
            **arrays,
        )


@dataclass(frozen=True)
class EnergyLimits:
    """Acceptance limits. Set a limit to None to report the value only.

    Defaults: the 10 % hourglass limits follow LS-DYNA's rule of thumb;
    the others are common rules of thumb. Replace them with your own
    guideline values.
    """

    energy_ratio: tuple[float, float] | None = (0.95, 1.05)
    """Allowed (minimum, maximum) energy ratio over the whole run."""

    hourglass: float | None = 0.10
    """Peak hourglass energy / peak internal energy."""

    negative_contact: float | None = 0.05
    """Most negative contact energy (magnitude) / reference energy."""

    damping: float | None = 0.05
    """Peak system damping energy / reference energy."""

    added_mass_percent: float | None = 5.0
    """Peak added mass, % of the model mass."""

    eroded_energy: float | None = None
    """Peak eroded energy / reference energy (reported only by default)."""

    part_hourglass: float | None = 0.10
    """Per part: peak hourglass / peak internal energy."""

    part_negative_internal: float | None = 0.01
    """Per part: most negative internal energy (magnitude) / peak."""

    part_min_internal_share: float = 0.01
    """Parts with a peak internal energy below this share of the model's
    peak internal energy are not checked."""


@dataclass(frozen=True)
class EnergyCheck:
    """Result of one check."""

    name: str
    description: str
    value: float | None
    limit: str
    status: str
    """``"pass"``, ``"fail"``, ``"info"`` (no limit) or ``"skipped"``."""
    time: float | None = None
    """Time of the worst value."""
    part: int | None = None
    """Worst part, for part checks."""
    note: str = ""


@dataclass(frozen=True)
class PartResult:
    """Energy check values of one part."""

    part_id: int
    name: str
    peak_internal: float
    share: float
    """Peak internal energy / model peak internal energy."""
    checked: bool
    hourglass_ratio: float | None
    negative_internal_ratio: float
    peak_added_mass: float | None
    """Largest added mass from mass scaling, if reported."""
    passed: bool


@dataclass(frozen=True)
class EnergyReport:
    """Results of :func:`check_energies`."""

    checks: tuple[EnergyCheck, ...]
    parts: tuple[PartResult, ...]
    reference_energy: float
    limits: EnergyLimits

    @property
    def passed(self) -> bool:
        """True if no check failed (skipped and info checks do not fail)."""
        return all(c.status != "fail" for c in self.checks)

    @property
    def failures(self) -> tuple[EnergyCheck, ...]:
        return tuple(c for c in self.checks if c.status == "fail")

    @property
    def failed_parts(self) -> tuple[PartResult, ...]:
        return tuple(p for p in self.parts if p.checked and not p.passed)

    def check(self, name: str) -> EnergyCheck:
        """Return a check by name."""
        for c in self.checks:
            if c.name == name:
                return c
        raise KeyError(name)

    def summary(self) -> str:
        """Plain-text table of the results."""
        rows = [("Check", "Value", "Limit", "Status", "Where")]
        for c in self.checks:
            value = "-" if c.value is None else f"{c.value:.4g}"
            where = []
            if c.part is not None:
                where.append(f"part {c.part}")
            if c.time is not None:
                where.append(f"t={c.time:.4g}")
            rows.append((c.name, value, c.limit, c.status.upper(), ", ".join(where)))
        widths = [max(len(r[i]) for r in rows) for i in range(5)]
        lines = ["  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip()
                 for r in rows]
        lines.insert(1, "  ".join("-" * w for w in widths))
        notes = [f"- {c.name}: {c.note}" for c in self.checks if c.note]
        failed = self.failed_parts
        if failed:
            notes.append(
                "- failed parts: "
                + ", ".join(_part_label(p) for p in failed[:20])
                + (" ..." if len(failed) > 20 else "")
            )
        scaled = sorted(
            (p for p in self.parts if p.peak_added_mass),
            key=lambda p: -(p.peak_added_mass or 0.0),
        )
        if scaled:
            notes.append(
                "- largest added mass by part: "
                + ", ".join(f"{_part_label(p)} {p.peak_added_mass:.4g}"
                            for p in scaled[:5])
            )
        n = len(self.failures)
        verdict = "PASSED" if self.passed else f"FAILED ({n} check{'s' * (n != 1)})"
        return "\n".join(
            [f"Energy check: {verdict}",
             f"Reference energy: {self.reference_energy:.6g}", ""]
            + lines + ([""] + notes if notes else [])
        )


def _part_label(part: PartResult) -> str:
    return f"{part.part_id} ({part.name})" if part.name else str(part.part_id)


def _status(value: float, limit: float | None) -> str:
    if limit is None:
        return "info"
    return "pass" if value <= limit else "fail"


def _limit_text(limit: float | None, fmt: str = "<= {:g}") -> str:
    return "-" if limit is None else fmt.format(limit)


def _argmax_time(values: FloatArray, time: FloatArray) -> float:
    return float(time[int(np.nanargmax(values))])


def _global_checks(
    g: GlobalEnergies, limits: EnergyLimits, ref: float
) -> list[EnergyCheck]:
    checks = []
    t = g.time

    ratio = g.ratio()
    lo_i, hi_i = int(np.nanargmin(ratio)), int(np.nanargmax(ratio))
    lo, hi = float(ratio[lo_i]), float(ratio[hi_i])
    worst_i = lo_i if abs(lo - 1.0) >= abs(hi - 1.0) else hi_i
    if limits.energy_ratio is None:
        status, limit = "info", "-"
    else:
        a, b = limits.energy_ratio
        status = "pass" if a <= lo and hi <= b else "fail"
        limit = f"{a:g} to {b:g}"
    source = "solver" if g.energy_ratio is not None else "computed"
    checks.append(EnergyCheck(
        "energy_ratio", "Total energy / (initial energy + external work)",
        float(ratio[worst_i]), limit, status, float(t[worst_i]),
        note=f"min {lo:.4f}, max {hi:.4f} ({source} ratio); added mass "
             "raises the ratio",
    ))

    peak_ie = float(np.nanmax(g.internal))
    if g.hourglass is None:
        checks.append(EnergyCheck(
            "hourglass", "Peak hourglass / peak internal energy", None,
            _limit_text(limits.hourglass), "skipped",
            note="no hourglass energy in the output; set HGEN=2 in "
                 "*CONTROL_ENERGY",
        ))
    elif peak_ie <= 0:
        checks.append(EnergyCheck(
            "hourglass", "Peak hourglass / peak internal energy", None,
            _limit_text(limits.hourglass), "skipped",
            note="internal energy never positive",
        ))
    else:
        value = float(np.nanmax(g.hourglass)) / peak_ie
        checks.append(EnergyCheck(
            "hourglass", "Peak hourglass / peak internal energy", value,
            _limit_text(limits.hourglass), _status(value, limits.hourglass),
            _argmax_time(g.hourglass, t),
        ))

    if g.sliding is None:
        checks.append(EnergyCheck(
            "negative_contact", "Most negative contact energy / reference",
            None, _limit_text(limits.negative_contact), "skipped",
            note="no sliding interface energy in the output",
        ))
    else:
        most_negative = float(np.nanmin(g.sliding))
        value = max(0.0, -most_negative) / ref
        checks.append(EnergyCheck(
            "negative_contact", "Most negative contact energy / reference",
            value, _limit_text(limits.negative_contact),
            _status(value, limits.negative_contact),
            float(t[int(np.nanargmin(g.sliding))]) if most_negative < 0 else None,
        ))

    if g.damping is None:
        checks.append(EnergyCheck(
            "damping", "Peak system damping energy / reference", None,
            _limit_text(limits.damping), "skipped",
            note="no system damping energy in the output (RYLEN=2 in "
                 "*CONTROL_ENERGY)",
        ))
    else:
        value = max(0.0, float(np.nanmax(g.damping))) / ref
        checks.append(EnergyCheck(
            "damping", "Peak system damping energy / reference", value,
            _limit_text(limits.damping), _status(value, limits.damping),
            _argmax_time(g.damping, t) if value > 0 else None,
        ))

    if g.added_mass_percent is None:
        checks.append(EnergyCheck(
            "added_mass", "Peak added mass, % of model mass", None,
            _limit_text(limits.added_mass_percent, "<= {:g} %"), "skipped",
            note="no added mass percentage in the output",
        ))
    else:
        value = float(np.nanmax(g.added_mass_percent))
        checks.append(EnergyCheck(
            "added_mass", "Peak added mass, % of model mass", value,
            _limit_text(limits.added_mass_percent, "<= {:g} %"),
            _status(value, limits.added_mass_percent),
            _argmax_time(g.added_mass_percent, t),
        ))

    eroded = [e for e in (g.eroded_internal, g.eroded_kinetic, g.eroded_hourglass)
              if e is not None]
    if eroded:
        total_eroded = np.sum(eroded, axis=0)
        value = max(0.0, float(np.nanmax(total_eroded))) / ref
        checks.append(EnergyCheck(
            "eroded_energy", "Peak eroded energy / reference", value,
            _limit_text(limits.eroded_energy), _status(value, limits.eroded_energy),
            _argmax_time(total_eroded, t) if value > 0 else None,
        ))
    return checks


def _part_checks(
    p: PartEnergies, limits: EnergyLimits, model_peak_ie: float
) -> tuple[list[EnergyCheck], list[PartResult]]:
    results = []
    peak = np.nanmax(p.internal, axis=0)
    minimum = np.nanmin(p.internal, axis=0)
    hg_peak = None if p.hourglass is None else np.nanmax(p.hourglass, axis=0)
    am_peak = None if p.added_mass is None else np.nanmax(p.added_mass, axis=0)

    for j, pid in enumerate(p.part_ids):
        share = float(peak[j]) / model_peak_ie if model_peak_ie > 0 else 0.0
        checked = model_peak_ie > 0 and share >= limits.part_min_internal_share
        hg_ratio = (
            float(hg_peak[j]) / float(peak[j])
            if hg_peak is not None and peak[j] > 0 else None
        )
        neg_ratio = (
            max(0.0, -float(minimum[j])) / float(peak[j]) if peak[j] > 0 else 0.0
        )
        ok = True
        if checked and limits.part_hourglass is not None and hg_ratio is not None:
            ok &= hg_ratio <= limits.part_hourglass
        if checked and limits.part_negative_internal is not None:
            ok &= neg_ratio <= limits.part_negative_internal
        results.append(PartResult(
            int(pid), p.part_names.get(int(pid), ""), float(peak[j]), share,
            checked, hg_ratio, neg_ratio,
            None if am_peak is None else float(am_peak[j]), bool(ok),
        ))

    checked_parts = [r for r in results if r.checked]
    note = (f"{len(checked_parts)} of {len(results)} parts checked "
            f"(peak internal energy >= {limits.part_min_internal_share:.0%} "
            "of the model's)")
    checks = []

    if p.hourglass is None:
        checks.append(EnergyCheck(
            "part_hourglass", "Per part: peak hourglass / peak internal energy",
            None, _limit_text(limits.part_hourglass), "skipped",
            note="no part hourglass energy in the output; set HGEN=2",
        ))
    elif checked_parts:
        worst = max(checked_parts, key=lambda r: r.hourglass_ratio or 0.0)
        value = worst.hourglass_ratio or 0.0
        n_fail = sum(
            1 for r in checked_parts
            if limits.part_hourglass is not None
            and (r.hourglass_ratio or 0.0) > limits.part_hourglass
        )
        checks.append(EnergyCheck(
            "part_hourglass", "Per part: peak hourglass / peak internal energy",
            value, _limit_text(limits.part_hourglass),
            _status(value, limits.part_hourglass), part=worst.part_id,
            note=note + (
                f"; {n_fail} part{'s' * (n_fail != 1)} over the limit"
                if n_fail else ""
            ),
        ))

    if checked_parts:
        worst = max(checked_parts, key=lambda r: r.negative_internal_ratio)
        value = worst.negative_internal_ratio
        checks.append(EnergyCheck(
            "part_negative_internal",
            "Per part: most negative / peak internal energy", value,
            _limit_text(limits.part_negative_internal),
            _status(value, limits.part_negative_internal),
            part=worst.part_id if value > 0 else None,
        ))
    return checks, results


def check_energies(
    global_energies: GlobalEnergies,
    part_energies: PartEnergies | None = None,
    limits: EnergyLimits | None = None,
) -> EnergyReport:
    """Check the energy balance of a simulation.

    Parameters
    ----------
    global_energies:
        Global energies, for example from
        :func:`crashmetrics.lsdyna.read_glstat`.
    part_energies:
        Optional per-part energies, for example from
        :func:`crashmetrics.lsdyna.read_matsum`, for the part checks.
    limits:
        Acceptance limits; :class:`EnergyLimits` defaults if omitted.

    Returns
    -------
    EnergyReport
        ``report.passed``, ``report.failures``, ``report.summary()``.
    """
    limits = limits or EnergyLimits()
    if limits.energy_ratio is not None:
        a, b = limits.energy_ratio
        if not a < 1.0 < b:
            raise ValueError("energy_ratio limits must bracket 1.0.")

    ref = global_energies.reference_energy()
    if not math.isfinite(ref) or ref <= 0:
        raise ValueError(
            "The reference energy (initial total energy + external work) "
            "must be positive."
        )

    checks = _global_checks(global_energies, limits, ref)
    parts: list[PartResult] = []
    if part_energies is not None:
        model_peak = float(np.nanmax(global_energies.internal))
        if model_peak <= 0:
            model_peak = float(np.nanmax(np.nansum(part_energies.internal, axis=1)))
        part_checks, parts = _part_checks(part_energies, limits, model_peak)
        checks.extend(part_checks)

    return EnergyReport(tuple(checks), tuple(parts), ref, limits)
