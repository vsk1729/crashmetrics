"""Verify a ``*MAT_024`` card with a single-element tension test.

- `single_element_deck`: a complete LS-DYNA model of one solid element
  (a cube) pulled in z under uniaxial stress, with the card under test,
  writing ``spcforc`` and ``nodout``. Run it with your LS-DYNA.
- `verify_single_element`: reads those two files back
  (`crashmetrics.lsdyna_ascii`) and compares the true stress against
  plastic strain of the element with the card's curve.
- `compare_tension`: the same comparison from force and displacement
  arrays.

A one-element test shows what the solver makes of the card: curve
re-discretisation (LCINT), extrapolation beyond the last point, rate
scaling and unit mistakes all show up as a difference to the input
curve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.lsdyna_ascii import AsciiOutput, read_nodout, read_spcforc
from crashmetrics.materials.card import Mat024, keyword_number
from crashmetrics.materials.rate import UNIT_SYSTEMS

__all__ = [
    "FORCE_SCALE",
    "LENGTH_SCALE",
    "SingleElementCheck",
    "compare_tension",
    "single_element_deck",
    "verify_single_element",
]

FloatArray = NDArray[np.float64]

FORCE_SCALE: dict[str, float] = {"mm-ms-kg": 1000.0, "mm-s-t": 1.0, "mm-s-kg": 1e-3,
                                 "m-s-kg": 1.0}
"""N per force unit of the unit system (kN, N, mN, N)."""

LENGTH_SCALE: dict[str, float] = {"mm-ms-kg": 1.0, "mm-s-t": 1.0, "mm-s-kg": 1.0,
                                  "m-s-kg": 1000.0}
"""mm per length unit of the unit system."""

TOP_NODE = 5
"""Node at the top of the element whose z displacement gives the strain."""


def _n8(value: int) -> str:
    return f"{value:8d}"


def _f16(value: float) -> str:
    return f"{value:16.8g}"


def single_element_deck(
    mat: Mat024,
    unit_system: str = "mm-ms-kg",
    *,
    size: float = 1.0,
    strain: float = 0.5,
    rate: float = 1.0,
    rate_effect: bool = False,
    title: str = "",
) -> str:
    """Keyword text of a one-element uniaxial tension test.

    A cube of edge ``size`` (mm) is pulled in z at a constant strain
    rate ``rate`` (1/s, nominal) to the engineering strain ``strain``,
    with a smooth start over the first 2 % of the time. Symmetry
    constraints leave the lateral faces free (uniaxial stress). The
    solid uses the fully integrated formulation (ELFORM 2), so no
    hourglass control is involved.

    ``rate_effect=False`` (default) writes the card without C and P so
    the static curve is checked; with a rate table the lowest-rate
    curve dominates at slow rates. Output: ``spcforc`` and ``nodout``
    (node 5 at the top) at 500 steps, ``glstat``, and ``d3plot``.
    """
    if unit_system not in UNIT_SYSTEMS:
        raise ValueError(f"Unknown unit_system; known: {list(UNIT_SYSTEMS)}.")
    if not (size > 0 and 0 < strain <= 2.0 and rate > 0):
        raise ValueError("size, strain and rate must be positive (strain <= 2).")
    _, t_scale = UNIT_SYSTEMS[unit_system]
    length = size / LENGTH_SCALE[unit_system]
    end_time = strain / rate / t_scale            # model time units
    velocity = strain * length / end_time
    card = mat if rate_effect else replace(mat, c=0.0, p=0.0)
    n = keyword_number
    xyz = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
           (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    lines = ["*KEYWORD",
             "*TITLE", (title or f"Single element tension, MID {mat.mid}")[:80],
             "*CONTROL_TERMINATION",
             "$#  endtim", n(end_time),
             "*DATABASE_SPCFORC", n(end_time / 500),
             "*DATABASE_NODOUT", n(end_time / 500),
             "*DATABASE_GLSTAT", n(end_time / 500),
             "*DATABASE_BINARY_D3PLOT", n(end_time / 50),
             "*DATABASE_HISTORY_NODE", f"{TOP_NODE:10d}",
             "*PART", f"single element MID {mat.mid}",
             "$#     pid     secid       mid",
             f"{1:10d}{1:10d}{mat.mid:10d}",
             "*SECTION_SOLID", "$#   secid    elform", f"{1:10d}{2:10d}",
             "*NODE"]
    lines += [_n8(i + 1) + _f16(x * length) + _f16(y * length) + _f16(z * length)
              for i, (x, y, z) in enumerate(xyz)]
    lines += ["*ELEMENT_SOLID", _n8(1) + _n8(1) + "".join(_n8(i) for i in range(1, 9))]
    # Symmetry: bottom face fixed in z, x = 0 face in x, y = 0 face in y.
    constraints = {1: (1, 1, 1), 2: (0, 1, 1), 3: (0, 0, 1), 4: (1, 0, 1),
                   5: (1, 1, 0), 6: (0, 1, 0), 8: (1, 0, 0)}
    lines += ["*BOUNDARY_SPC_NODE",
              "$#     nid       cid      dofx      dofy      dofz     dofrx     "
              "dofry     dofrz"]
    lines += [f"{nid:10d}{0:10d}" + "".join(f"{d:10d}" for d in dof) + f"{0:10d}" * 3
              for nid, dof in constraints.items()]
    lines += ["*SET_NODE_LIST", f"{1:10d}", "".join(f"{i:10d}" for i in (5, 6, 7, 8)),
              "*BOUNDARY_PRESCRIBED_MOTION_SET",
              "$#    nsid       dof       vad      lcid        sf",
              f"{1:10d}{3:10d}{0:10d}{9001:10d}" + n(1.0),
              "*DEFINE_CURVE_TITLE", "pull velocity",
              f"{9001:10d}{0:10d}" + n(1.0) + n(1.0) + n(0.0) + n(0.0),
              f"{0.0:20.8g}{0.0:20.8g}", f"{0.02 * end_time:20.8g}{velocity:20.8g}",
              f"{2.0 * end_time:20.8g}{velocity:20.8g}"]
    text = "\n".join(lines) + "\n"
    body = card.keyword(unit_system, points=None).replace("*KEYWORD\n", "")
    return text + body + "*END\n"


@dataclass(frozen=True)
class SingleElementCheck:
    """Element response against the card's curve."""

    plastic_strain: FloatArray
    stress: FloatArray
    """True stress of the element, MPa."""
    expected: FloatArray
    """Card stress at the same plastic strain, MPa."""
    max_error: float
    """Largest relative difference (fraction) above 0.2 % plastic strain."""
    rms_error: float
    """RMS of the relative difference."""

    @property
    def passed(self) -> bool:
        """Within 2 %."""
        return self.max_error <= 0.02

    def summary(self) -> str:
        return (f"Single element: max difference {self.max_error * 100:.2f} %, RMS "
                f"{self.rms_error * 100:.2f} % over plastic strain "
                f"{self.plastic_strain[0]:.3g}-{self.plastic_strain[-1]:.3g} -> "
                + ("passed" if self.passed else "CHECK"))


def compare_tension(
    displacement: ArrayLike,
    force: ArrayLike,
    mat: Mat024,
    *,
    size: float = 1.0,
    rate: float | None = None,
) -> SingleElementCheck:
    """Compare a one-element tension response with the card's curve.

    ``displacement`` (mm) of the top face and ``force`` (N) on it, of a
    cube of edge ``size`` (mm). True strain ``ln(1 + u / L)``, true
    stress ``F (L + u) / (A L)`` (constant volume, plasticity dominant),
    plastic strain ``eps - sigma / E``; compared with
    `Mat024.stress` at ``rate`` (``None``: static curve) above 0.2 %
    plastic strain.
    """
    u = np.asarray(displacement, dtype=float)
    f = np.abs(np.asarray(force, dtype=float))
    if u.shape != f.shape or len(u) < 3:
        raise ValueError("displacement and force need equal lengths (>= 3).")
    eps = np.log1p(u / size)
    sig = f * (size + u) / (size ** 3)
    ep = eps - sig / mat.modulus
    keep = ep > 0.002
    if int(keep.sum()) < 3:
        raise ValueError("Fewer than 3 points above 0.2 % plastic strain.")
    ep, sig = ep[keep], sig[keep]
    expected = mat.stress(ep, rate)
    rel = (sig - expected) / expected
    return SingleElementCheck(ep, sig, expected, float(np.max(np.abs(rel))),
                              float(np.sqrt(np.mean(rel ** 2))))


def verify_single_element(
    run_dir: str | Path,
    mat: Mat024,
    unit_system: str = "mm-ms-kg",
    *,
    size: float = 1.0,
    rate: float | None = None,
    spcforc: AsciiOutput | None = None,
    nodout: AsciiOutput | None = None,
) -> SingleElementCheck:
    """Read ``spcforc`` and ``nodout`` of a `single_element_deck` run in
    ``run_dir`` (or pass them) and compare with the card
    (`compare_tension`). The reaction force is the z total of
    ``spcforc``, the displacement node 5's z displacement in ``nodout``.
    """
    d = Path(run_dir)
    sp = spcforc if spcforc is not None else read_spcforc(d / "spcforc")
    nd = nodout if nodout is not None else read_nodout(d / "nodout")
    if "z_force" not in sp.totals:
        raise ValueError("spcforc has no z force totals.")
    u = nd.channel("z_displacement", TOP_NODE) * LENGTH_SCALE[unit_system]
    f = sp.totals["z_force"] * FORCE_SCALE[unit_system]
    n = min(len(u), len(f))
    if not math.isclose(float(nd.time[n - 1]), float(sp.time[n - 1]), rel_tol=1e-3):
        f = np.interp(nd.time[:n], sp.time, sp.totals["z_force"]) * \
            FORCE_SCALE[unit_system]
    return compare_tension(u[:n], f[:n], mat, size=size, rate=rate)
