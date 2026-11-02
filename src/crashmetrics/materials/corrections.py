"""Corrections of tensile curves: Lüders plateau and machine compliance.

- `luders_plateau`: finds discontinuous yielding (the Lüders plateau of
  mild and some micro-alloyed steels): upper yield strength ReH, lower
  yield strength ReL and the yield point elongation Ae (ISO 6892-1
  definitions).
- `smooth_luders`: prepares such a curve for a ``*MAT_024`` card, which
  cannot represent the plateau: either a flat line at ReL in place of the
  spike and the oscillations (``mode="flat"``), or the plateau removed so
  hardening starts at the yield point (``mode="remove"``).
- `correct_compliance`: removes the machine and grip compliance from a
  strain measured with the cross-head travel (no extensometer), using a
  known Young's modulus.

Units: stress MPa, strain dimensionless, compliance mm/N.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from crashmetrics.materials.tensile import TensileTest, _fit_modulus

__all__ = [
    "LudersPlateau",
    "correct_compliance",
    "luders_plateau",
    "smooth_luders",
]


@dataclass(frozen=True)
class LudersPlateau:
    """Discontinuous yielding of a tensile curve (ISO 6892-1 terms)."""

    upper_yield: float
    """ReH: stress at the first drop of force after yielding, MPa."""
    lower_yield: float
    """ReL: lowest stress during the plateau, the initial transient
    minimum after ReH ignored, MPa."""
    start_strain: float
    """Strain at ReH, where discontinuous yielding starts."""
    end_strain: float
    """Strain where uniform work hardening starts: from here on the
    stress stays above ``ReL * (1 + band)``."""
    band: float
    """Relative band above ReL used for the end of the plateau."""

    @property
    def elongation(self) -> float:
        """Ae: yield point elongation, ``end_strain - start_strain``."""
        return self.end_strain - self.start_strain


def luders_plateau(
    test: TensileTest,
    *,
    drop: float = 0.01,
    band: float = 0.02,
    min_elongation: float = 0.002,
) -> LudersPlateau | None:
    """Find a Lüders plateau; None if the material yields continuously.

    1. **ReH**: the running maximum of the stress at the first point
       where the stress falls more than ``drop`` (fraction, default 1 %)
       below it, before the tensile strength.
    2. **ReL**: the lowest stress between ReH and the point where the
       stress first returns to ReH (or to Rm). As ISO 6892-1, the initial
       transient dip straight after ReH (up to where the curve first
       reaches the median stress of that range) is ignored when the
       plateau dips again later; otherwise that dip is ReL.
    3. **End of the plateau** (start of uniform work hardening): the
       point from which the stress stays above ``ReL * (1 + band)``
       (default 2 %) up to Rm.

    A plateau shorter than ``min_elongation`` (default 0.2 % strain) is
    treated as noise and None is returned. Smooth noisy data first
    (`crashmetrics.materials.clean_tensile`, ``smooth=``), with a short
    window so the yield point is not rounded away.
    """
    if not (0 < drop < 0.5 and 0 < band < 0.5):
        raise ValueError("drop and band must be fractions between 0 and 0.5.")
    e, s = test.strain, test.stress
    peak = int(np.argmax(s))
    running = np.maximum.accumulate(s[: peak + 1])
    # Ignore the noise at the start of loading (below 10 % of Rm).
    fallen = np.flatnonzero((s[: peak + 1] < running * (1.0 - drop))
                            & (running > 0.1 * s[peak]))
    if not len(fallen):
        return None
    j = int(fallen[0])
    i_h = int(np.argmax(s[:j]))
    reh = float(s[i_h])

    back = np.flatnonzero(s[i_h + 1: peak + 1] >= reh)
    k = i_h + 1 + int(back[0]) if len(back) else peak
    region = s[i_h + 1: max(k, i_h + 2)]
    # Initial transient (ISO 6892-1): the dip straight after ReH, up to
    # where the curve first reaches the plateau's typical (median) level.
    level = float(np.median(region))
    under = np.flatnonzero(region < level)
    dip_start = int(under[0]) if len(under) else 0
    reach = np.flatnonzero(region[dip_start:] >= level)
    dip_end = dip_start + int(reach[0]) if len(reach) else len(region)
    transient = float(np.min(region[: max(dip_end, 1)]))
    later = region[dip_end:]
    rel = float(np.min(later)) if len(later) and np.min(later) < level else transient

    above = s[i_h: peak + 1] > rel * (1.0 + band)
    below = np.flatnonzero(~above)
    end = i_h + int(below[-1]) + 1 if len(below) else i_h
    end = min(end, peak)
    plateau = LudersPlateau(reh, rel, float(e[i_h]), float(e[end]), band)
    if plateau.elongation < min_elongation:
        return None
    return plateau


def smooth_luders(
    test: TensileTest,
    plateau: LudersPlateau | None = None,
    *,
    mode: Literal["flat", "remove"] = "flat",
    **find: float,
) -> TensileTest:
    """Replace the Lüders plateau for use in a material card.

    The plateau (``plateau``, or found with `luders_plateau` and the
    keyword arguments in ``find``) is replaced from the point where the
    loading line reaches ReL to the end of the plateau:

    - ``mode="flat"``: a straight line at ReL. The upper yield spike and
      the oscillations go; the plateau strain stays (the card then has a
      perfectly plastic start).
    - ``mode="remove"``: the plateau strain is taken out and the
      hardening curve moved back to the yield point, so hardening starts
      at ReL. Common for crash cards: the plateau is a local,
      band-propagation effect that a ``*MAT_024`` element cannot
      reproduce.

    Returns the curve unchanged (with a note in ``info``) when there is
    no plateau.
    """
    if mode not in ("flat", "remove"):
        raise ValueError('mode must be "flat" or "remove".')
    plateau = plateau if plateau is not None else luders_plateau(test, **find)
    info = dict(test.info)
    if plateau is None:
        info["luders"] = {"found": False}
        return replace(test, info=info)
    e, s = test.strain, test.stress
    rel = plateau.lower_yield
    a = int(np.flatnonzero(s >= rel)[0])
    if a == 0:
        raise ValueError("The curve starts above ReL; check the data.")
    w = (rel - s[a - 1]) / (s[a] - s[a - 1])
    e_yield = float(e[a - 1] + w * (e[a] - e[a - 1]))
    end = int(np.searchsorted(e, plateau.end_strain))
    head_e, head_s = e[:a], s[:a]
    tail_e, tail_s = e[end:], s[end:]
    if mode == "flat":
        new_e = np.concatenate((head_e, [e_yield, plateau.end_strain], tail_e[1:]))
        new_s = np.concatenate((head_s, [rel, rel], tail_s[1:]))
        removed = 0.0
    else:
        removed = plateau.end_strain - e_yield
        new_e = np.concatenate((head_e, [e_yield], tail_e[1:] - removed))
        new_s = np.concatenate((head_s, [rel], tail_s[1:]))
    info["luders"] = {"found": True, "mode": mode, "upper_yield": plateau.upper_yield,
                      "lower_yield": rel, "elongation": plateau.elongation,
                      "strain_removed": removed}
    return replace(test, strain=new_e, stress=new_s, info=info)


def correct_compliance(
    test: TensileTest,
    modulus: float,
    *,
    modulus_window: tuple[float, float] = (0.1, 0.4),
    modulus_stress: tuple[float, float] | None = None,
) -> TensileTest:
    """Remove the machine and grip compliance from a cross-head strain.

    Without an extensometer the measured elongation includes the
    deflection of the frame, load cell and grips, so the elastic slope
    comes out too low (often 50-150 GPa for steel). With the material's
    real Young's modulus ``modulus`` (MPa, for example 210 000 for steel)
    the extra strain is removed at every point:

    ``strain_corrected = strain - stress * (1 / E_measured - 1 / E)``

    where ``E_measured`` is fitted on the loading curve as in
    `crashmetrics.materials.tensile_properties`. This assumes a linear
    machine; the toe region should be corrected after this
    (`crashmetrics.materials.clean_tensile`). When the test was built
    from force and elongation, ``info["compliance_mm_per_n"]`` gives the
    machine compliance ``C = (1 / E_measured - 1 / E) * L0 / S0``.
    Strains past necking are local and not corrected by this; use them
    with care.
    """
    if not (math.isfinite(modulus) and modulus > 0):
        raise ValueError("modulus must be positive (MPa).")
    fit = _fit_modulus(test.strain, test.stress, modulus_window, modulus_stress)
    if fit.slope >= modulus:
        raise ValueError(f"The measured slope ({fit.slope:.0f} MPa) is not below "
                         f"modulus ({modulus:.0f} MPa): no compliance to remove.")
    extra = 1.0 / fit.slope - 1.0 / modulus                # per MPa
    info = dict(test.info)
    log: dict[str, object] = {"measured_modulus": fit.slope, "modulus": modulus,
                              "strain_per_mpa": extra}
    area, gauge = info.get("area_mm2"), info.get("gauge_length_mm")
    if isinstance(area, float) and isinstance(gauge, float):
        log["compliance_mm_per_n"] = extra * gauge / area
        info["compliance_mm_per_n"] = log["compliance_mm_per_n"]
    info["compliance"] = log
    return replace(test, strain=test.strain - test.stress * extra, info=info)
