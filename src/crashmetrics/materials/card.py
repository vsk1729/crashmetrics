"""Write ``*MAT_PIECEWISE_LINEAR_PLASTICITY`` (``*MAT_024``) cards.

`Mat024` holds one material in engineering units (density kg/m³, stress
and modulus MPa, strain rates 1/s) with its hardening curve
(`crashmetrics.materials.HardeningCurve`) or strain-rate table
(`crashmetrics.materials.RateTable`), and writes it for an LS-DYNA unit
system:

- `Mat024.keyword`: the material card followed by its ``*DEFINE_CURVE``
  or ``*DEFINE_TABLE`` (fixed 10- and 20-character fields).
- `Mat024.write`: an include file with a header recording where the card
  came from (`provenance`), the unit system and the date.
- `failure_strain`: a simple element-size dependent plastic strain at
  failure (FAIL), and `fracture_strain` from the reduction of area. A
  rough approach; damage models such as GISSMO describe failure far
  better.

Unit systems (`UNIT_SYSTEMS`): ``"mm-ms-kg"`` (GPa, kg/mm³, 1/ms),
``"mm-s-t"`` (MPa, t/mm³, 1/s), ``"mm-s-kg"`` (kPa, kg/mm³, 1/s),
``"m-s-kg"`` (Pa, kg/m³, 1/s).
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from crashmetrics.materials.hardening import HardeningCurve
from crashmetrics.materials.rate import UNIT_SYSTEMS, RateTable, _grid

__all__ = [
    "DENSITY_SCALE",
    "Mat024",
    "failure_strain",
    "fracture_strain",
    "keyword_number",
]

FloatArray = NDArray[np.float64]

DENSITY_SCALE: dict[str, float] = {
    "mm-ms-kg": 1e-9,
    "mm-s-t": 1e-12,
    "mm-s-kg": 1e-9,
    "m-s-kg": 1.0,
}
"""Density in the unit system per kg/m³ (7850 kg/m³ = 7.85e-6 kg/mm³ =
7.85e-9 t/mm³)."""


def keyword_number(value: float, width: int = 10) -> str:
    """A number right-aligned in a fixed keyword field, with as many
    significant digits as fit while keeping one leading blank
    (``7.85e-6``, ``210.0``, ``0.3``)."""
    if not math.isfinite(value):
        raise ValueError(f"Cannot write {value} in a keyword field.")
    if value == 0:
        return f"{0.0:>{width}.1f}"
    if float(value).is_integer() and abs(value) < 10 ** (width - 3):
        return f"{value:>{width}.1f}"
    for digits in range(width - 1, 0, -1):
        text = f"{value:.{digits}g}"
        if "e" in text:
            mantissa, exp = text.split("e")
            text = f"{mantissa}e{int(exp)}"     # e-06 -> e-6
        if len(text) < width:                  # keep a blank between fields
            return text.rjust(width)
    raise ValueError(f"{value} does not fit a {width}-character field.")


def _int(value: int, width: int = 10) -> str:
    text = f"{value:d}"
    if len(text) > width:
        raise ValueError(f"ID {value} does not fit a {width}-character field.")
    return text.rjust(width)


def _resample(curve: HardeningCurve, points: int) -> tuple[FloatArray, FloatArray]:
    """The curve at ``points`` plastic strains, dense near yield, with
    the measured necking point kept."""
    grid = _grid(float(curve.plastic_strain[-1]), points)
    neck = curve.necking_strain
    if 0 < neck < grid[-1] and not np.any(np.isclose(grid, neck, rtol=1e-6)):
        grid = np.sort(np.append(grid[:-1], [neck, grid[-1]]))
    return grid, np.interp(grid, curve.plastic_strain, curve.stress)


# --- Failure -----------------------------------------------------------------------


def fracture_strain(reduction_of_area: float) -> float:
    """True strain at fracture from the reduction of area Z (fraction,
    ``0.55`` for 55 %): ``ln(1 / (1 - Z))``. It is the strain in the neck,
    measured on the broken specimen."""
    if not 0 < reduction_of_area < 1:
        raise ValueError("reduction_of_area must be a fraction between 0 and 1.")
    return math.log(1.0 / (1.0 - reduction_of_area))


def failure_strain(
    *,
    uniform: float,
    fracture: float,
    element_size: float,
    neck_length: float,
) -> float:
    """Plastic strain at failure (FAIL) for an element of a given size.

    The strain to fracture is reached only over the neck (length about
    the sheet thickness); an element larger than the neck averages it
    with the uniformly strained material around:

    ``FAIL = uniform + (fracture - uniform) * min(1, neck_length / element_size)``

    Parameters
    ----------
    uniform:
        Plastic strain at necking (`HardeningCurve.necking_strain`).
    fracture:
        Local plastic strain at fracture (`fracture_strain` from the
        reduction of area, or DIC).
    element_size, neck_length:
        Element edge length and neck length (about the thickness), mm.

    Notes
    -----
    A rough size regularisation for simple element deletion: it ignores
    the stress state (triaxiality). Use it for screening, and a damage
    model (GISSMO) for failure predictions.
    """
    if not 0 <= uniform < fracture:
        raise ValueError("Need 0 <= uniform < fracture.")
    if element_size <= 0 or neck_length <= 0:
        raise ValueError("element_size and neck_length must be positive.")
    return uniform + (fracture - uniform) * min(1.0, neck_length / element_size)


# --- The card -----------------------------------------------------------------------


@dataclass(frozen=True)
class Mat024:
    """One ``*MAT_PIECEWISE_LINEAR_PLASTICITY`` material.

    Give the hardening as ``curve`` (one curve; optional Cowper-Symonds
    ``c`` and ``p``) or as ``table`` (a strain-rate table; then ``c``
    and ``p`` must stay 0, as both would scale the stress).
    """

    mid: int
    """Material ID."""
    density: float
    """kg/m³ (7850 for steel)."""
    modulus: float
    """Young's modulus, MPa."""
    curve: HardeningCurve | None = None
    table: RateTable | None = None
    poisson: float = 0.3
    c: float = 0.0
    """Cowper-Symonds C, 1/s (0: no rate effect)."""
    p: float = 0.0
    """Cowper-Symonds P."""
    vp: int = 0
    """0: scale the yield stress with the rate (default); 1: viscoplastic
    formulation."""
    fail: float = 0.0
    """Plastic strain at failure (0: no failure)."""
    tdel: float = 0.0
    """Minimum time step for element deletion, in the model's time unit."""
    curve_id: int | None = None
    """ID of the curve or table (default ``mid + 1000``)."""
    title: str = ""
    provenance: Mapping[str, object] = field(default_factory=dict)
    """Where the card came from (tests, fits, author); written in the
    include file header."""

    def __post_init__(self) -> None:
        if (self.curve is None) == (self.table is None):
            raise ValueError("Give either curve or table.")
        if self.table is not None and (self.c or self.p):
            raise ValueError("A rate table already holds the rate effect; leave c "
                             "and p at 0.")
        if (self.c == 0) != (self.p == 0):
            raise ValueError("Give both Cowper-Symonds c and p, or neither.")
        if self.c < 0 or self.p < 0:
            raise ValueError("c and p must be >= 0.")
        if not (self.density > 0 and self.modulus > 0):
            raise ValueError("density and modulus must be positive.")
        if not 0 <= self.poisson < 0.5:
            raise ValueError("poisson must be in [0, 0.5).")
        if self.vp not in (0, 1):
            raise ValueError("vp must be 0 or 1.")
        if self.fail < 0 or self.tdel < 0:
            raise ValueError("fail and tdel must be >= 0.")
        if self.density > 30_000 or self.density < 1:
            raise ValueError("density looks wrong: give it in kg/m³ (steel 7850).")
        if self.modulus < 100 or self.modulus > 1e6:
            raise ValueError("modulus looks wrong: give it in MPa (steel 210000).")

    @property
    def yield_stress(self) -> float:
        """SIGY: the first stress of the curve (of the lowest-rate curve of
        a table), MPa."""
        if self.curve is not None:
            return float(self.curve.stress[0])
        assert self.table is not None
        return float(self.table.stress[0][0])

    @property
    def lcss(self) -> int:
        """ID of the curve or table referenced as LCSS."""
        return self.curve_id if self.curve_id is not None else self.mid + 1000

    def keyword(self, unit_system: str = "mm-ms-kg", *, points: int = 50,
                log_rates: bool = True) -> str:
        """The material card and its curve or table, in ``unit_system``.

        A single curve is resampled at ``points`` plastic strains (denser
        near yield, the necking point kept); a table keeps its own grid.
        ``log_rates`` applies to a table (ln of the rates).
        """
        if unit_system not in UNIT_SYSTEMS:
            raise ValueError(f"Unknown unit_system; known: {list(UNIT_SYSTEMS)}.")
        s_scale, t_scale = UNIT_SYSTEMS[unit_system]
        n = keyword_number
        head = ("*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE" if self.title
                else "*MAT_PIECEWISE_LINEAR_PLASTICITY")
        lines = [head]
        if self.title:
            lines.append(self.title[:80])
        lines += [
            "$#     mid        ro         e        pr      sigy      etan      fail"
            "      tdel",
            _int(self.mid) + n(self.density * DENSITY_SCALE[unit_system])
            + n(self.modulus * s_scale) + n(self.poisson)
            + n(self.yield_stress * s_scale) + n(0.0) + n(self.fail) + n(self.tdel),
            "$#       c         p      lcss      lcsr        vp",
            n(self.c * t_scale) + n(self.p) + _int(self.lcss) + _int(0)
            + n(float(self.vp)),
            "$#    eps1      eps2      eps3      eps4      eps5      eps6      eps7"
            "      eps8",
            n(0.0) * 8,
            "$#     es1       es2       es3       es4       es5       es6       es7"
            "       es8",
            n(0.0) * 8,
        ]
        text = "\n".join(lines) + "\n"
        if self.table is not None:
            return text + self.table.keyword(self.lcss, unit_system=unit_system,
                                             log_rates=log_rates,
                                             title=f"{self.title or self.mid} rates")
        assert self.curve is not None
        strain, stress = _resample(self.curve, points)
        curve = ["*DEFINE_CURVE_TITLE", f"{self.title or self.mid} hardening",
                 "$#    lcid      sidr       sfa       sfo      offa      offo",
                 _int(self.lcss) + _int(0) + n(1.0) + n(1.0) + n(0.0) + n(0.0),
                 "$#                a1                  o1"]
        curve += [f"{e:20.8g}{s * s_scale:20.8g}" for e, s in zip(strain, stress)]
        return text + "\n".join(curve) + "\n"

    def write(self, path: str | Path, unit_system: str = "mm-ms-kg", *,
              points: int = 50, log_rates: bool = True,
              date: dt.date | None = None) -> Path:
        """Write an include file: header, ``*KEYWORD``, the card, ``*END``.

        The header names crashmetrics and its version, the unit system,
        the date (``date``, default today) and every ``provenance`` entry.
        """
        from crashmetrics import __version__

        units = {"mm-ms-kg": "mm, ms, kg, kN, GPa", "mm-s-t": "mm, s, t, N, MPa",
                 "mm-s-kg": "mm, s, kg, mN, kPa", "m-s-kg": "m, s, kg, N, Pa"}
        header = [
            f"$ {self.title or 'Material'} (*MAT_024, MID {self.mid})",
            f"$ Written by crashmetrics {__version__} on "
            f"{(date or dt.date.today()).isoformat()}",
            f"$ Units: {unit_system} ({units.get(unit_system, '')})",
        ]
        header += [f"$ {k}: {v}" for k, v in self.provenance.items()]
        text = ("\n".join(header) + "\n*KEYWORD\n"
                + self.keyword(unit_system, points=points, log_rates=log_rates)
                + "*END\n")
        out = Path(path)
        out.write_text(text)
        return out
