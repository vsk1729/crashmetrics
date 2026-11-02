"""Read, check, convert and compare existing ``*MAT_024`` cards.

- `read_keyword`: the ``*MAT_PIECEWISE_LINEAR_PLASTICITY`` (``*MAT_024``)
  cards of a keyword file or text, with the ``*DEFINE_CURVE`` and
  ``*DEFINE_TABLE`` they use. Fixed (10/20 characters), long
  (``*KEYWORD LONG=Y`` or a ``+`` after the keyword) and comma-separated
  formats; ``_TITLE`` variants. Includes are not followed.
- `guess_unit_system`: the unit system from density and Young's modulus.
- `KeywordDeck.material`: one card as a `crashmetrics.materials.Mat024`
  in engineering units, to check, compare, convert or rewrite it.
- `check_keyword`: finds unit-system mix-ups, curve and table errors,
  hardening steeper than elasticity, crossing rate curves, curve detail
  lost to LS-DYNA's re-discretisation, and more.
- `convert_keyword`: the cards in another unit system.
- `compare_cards`: two cards side by side (E, density, SIGY, C, P, the
  stress at chosen strains and rates).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from crashmetrics.materials.card import DENSITY_SCALE, Mat024
from crashmetrics.materials.gissmo import GissmoCard, RegularizationCurve
from crashmetrics.materials.hardening import HardeningCurve
from crashmetrics.materials.rate import UNIT_SYSTEMS, RateTable
from crashmetrics.materials.verify import LENGTH_SCALE

__all__ = [
    "CardCheck",
    "CardComparison",
    "KeywordCurve",
    "KeywordDeck",
    "KeywordTable",
    "Mat024Keyword",
    "GissmoKeyword",
    "check_gissmo",
    "check_keyword",
    "compare_cards",
    "convert_keyword",
    "guess_unit_system",
    "read_keyword",
]

FloatArray = NDArray[np.float64]

_MAT024 = re.compile(r"^\*MAT_(PIECEWISE_LINEAR_PLASTICITY|024)(_TITLE)?(\+)?\s*$",
                     re.I)
_CURVE = re.compile(r"^\*DEFINE_CURVE(_TITLE)?(\+)?\s*$", re.I)
_TABLE = re.compile(r"^\*DEFINE_TABLE(_TITLE)?(\+)?\s*$", re.I)
_GISSMO = re.compile(r"^\*MAT_ADD_DAMAGE_GISSMO(_TITLE)?(\+)?\s*$", re.I)


# --- Data ------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordCurve:
    """A ``*DEFINE_CURVE``, with SFA/SFO/OFFA/OFFO applied
    (``x = SFA a + OFFA``, ``y = SFO o + OFFO``)."""

    lcid: int
    x: FloatArray
    y: FloatArray
    title: str = ""
    line: int = 0


@dataclass(frozen=True)
class KeywordTable:
    """A ``*DEFINE_TABLE`` and the curves that follow it."""

    tbid: int
    values: FloatArray
    """Table values (strain rates, or ln(rate) when the first is
    negative), SFA and OFFA applied."""
    curve_ids: tuple[int, ...]
    title: str = ""
    line: int = 0

    @property
    def log_rates(self) -> bool:
        """LS-DYNA reads the values as ln(rate) when the first is negative."""
        return bool(self.values[0] < 0)


@dataclass(frozen=True)
class Mat024Keyword:
    """One ``*MAT_024`` card as written (model units)."""

    mid: int
    ro: float
    e: float
    pr: float
    sigy: float
    etan: float
    fail: float
    tdel: float
    c: float
    p: float
    lcss: int
    lcsr: int
    vp: float
    eps: tuple[float, ...]
    es: tuple[float, ...]
    title: str = ""
    line: int = 0
    parameters: tuple[str, ...] = ()
    """Fields given as ``&parameters`` (not evaluated; read as 0)."""


@dataclass(frozen=True)
class GissmoKeyword:
    """One ``*MAT_ADD_DAMAGE_GISSMO`` card as written (model units)."""

    mid: int
    dtyp: float
    refsz: float
    numfip: float
    lcsdg: int
    ecrit: float
    dmgexp: float
    dcrit: float
    fadexp: float
    lcregd: int
    lcsrs: int
    shrf: float
    biaxf: float
    line: int = 0
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeywordDeck:
    """``*MAT_024`` cards with their curves and tables, and
    ``*MAT_ADD_DAMAGE_GISSMO`` cards."""

    materials: dict[int, Mat024Keyword]
    curves: dict[int, KeywordCurve]
    tables: dict[int, KeywordTable]
    source: str = ""
    notes: tuple[str, ...] = ()
    """What the reader skipped (unsupported keywords, includes)."""
    gissmo: dict[int, GissmoKeyword] = field(default_factory=dict)
    """``*MAT_ADD_DAMAGE_GISSMO`` cards by MID."""

    def _units(self, mid: int, unit_system: str | None) -> tuple[str, bool]:
        """Unit system for a MID: given, else from its *MAT_024, else mm-ms-kg
        (second value False when assumed)."""
        if unit_system:
            return unit_system, True
        if mid in self.materials:
            m = self.materials[mid]
            guessed = guess_unit_system(m.ro, m.e)
            if guessed:
                return guessed, True
        return "mm-ms-kg", False

    def damage(self, mid: int, unit_system: str | None = None) -> GissmoCard:
        """A ``*MAT_ADD_DAMAGE_GISSMO`` card as a `GissmoCard` (element
        sizes in mm, rates in 1/s). The unit system comes from
        ``unit_system``, else from the ``*MAT_024`` of the same MID, else
        mm-ms-kg is assumed (length in mm)."""
        if mid not in self.gissmo:
            raise ValueError(f"No *MAT_ADD_DAMAGE_GISSMO with MID {mid}; MIDs: "
                             f"{sorted(self.gissmo)}.")
        g = self.gissmo[mid]
        us, _ = self._units(mid, unit_system)
        length = LENGTH_SCALE[us]
        _, t_scale = UNIT_SYSTEMS[us]

        def curve(lcid: int, what: str) -> KeywordCurve:
            if lcid in self.tables:
                raise ValueError(f"MID {mid}: {what} {lcid} is a table (Lode or "
                                 "temperature dependent); not supported.")
            if lcid not in self.curves:
                raise ValueError(f"MID {mid}: {what} {lcid} is not in the deck.")
            return self.curves[lcid]

        fail = curve(g.lcsdg, "LCSDG")
        instability: tuple[FloatArray, FloatArray] | float | None = None
        if g.ecrit < 0:
            c = curve(int(-g.ecrit), "ECRIT curve")
            instability = (c.x, c.y)
        elif g.ecrit > 0:
            instability = g.ecrit
        fadexp: float | tuple[FloatArray, FloatArray] = g.fadexp or 1.0
        if g.fadexp < 0:
            c = curve(int(-g.fadexp), "FADEXP curve")
            fadexp = (c.x * length, c.y)
        regularization = None
        if g.lcregd:
            c = curve(g.lcregd, "LCREGD")
            regularization = RegularizationCurve(c.x * length, c.y)
        rate = None
        if g.lcsrs:
            c = curve(abs(g.lcsrs), "LCSRS")
            r = np.exp(c.x) if c.x[0] < 0 else c.x
            rate = (r / t_scale, c.y)
        return GissmoCard(
            mid=mid, failure=(fail.x, fail.y), instability=instability,
            dmgexp=g.dmgexp or 1.0, dcrit=g.dcrit, fadexp=fadexp,
            regularization=regularization, rate_scaling=rate,
            scale_instability_with_rate=g.lcsrs >= 0, dtyp=int(g.dtyp),
            numfip=g.numfip or 1.0, refsz=g.refsz * length, shrf=g.shrf,
            biaxf=g.biaxf, first_curve_id=g.lcsdg)

    def material(self, mid: int, unit_system: str | None = None) -> Mat024:
        """One card as a `Mat024` in engineering units (kg/m³, MPa, 1/s).

        ``unit_system`` defaults to `guess_unit_system`. The hardening
        comes from LCSS (curve or table) or, without LCSS, from the
        EPS/ES pairs or SIGY and ETAN (bilinear to plastic strain 1).
        """
        if mid not in self.materials:
            raise ValueError(f"No *MAT_024 with MID {mid}; MIDs: "
                             f"{sorted(self.materials)}.")
        m = self.materials[mid]
        us = unit_system or guess_unit_system(m.ro, m.e)
        if us is None:
            raise ValueError(f"MID {mid}: RO {m.ro:g} and E {m.e:g} do not match one "
                             "unit system; give unit_system.")
        if us not in UNIT_SYSTEMS:
            raise ValueError(f"Unknown unit_system; known: {list(UNIT_SYSTEMS)}.")
        s_scale, t_scale = UNIT_SYSTEMS[us]
        modulus = m.e / s_scale
        curve: HardeningCurve | None = None
        table: RateTable | None = None
        if m.lcss in self.tables:
            tb = self.tables[m.lcss]
            rates = (np.exp(tb.values) if tb.log_rates else tb.values) / t_scale
            members = [self.curves[i] for i in tb.curve_ids if i in self.curves]
            if len(members) != len(tb.curve_ids):
                raise ValueError(f"Table {tb.tbid}: missing curves.")
            end = min(float(c.x[-1]) for c in members)
            grid = np.unique(np.concatenate([c.x[c.x <= end] for c in members]))
            stress = np.array([np.interp(grid, c.x, c.y) / s_scale for c in members])
            table = RateTable(rates, grid, stress, {"tbid": tb.tbid})
        elif m.lcss in self.curves:
            lc = self.curves[m.lcss]
            curve = HardeningCurve(lc.x, lc.y / s_scale, modulus, float(lc.x[-1]),
                                   m.title or str(mid), {"lcid": lc.lcid})
        elif m.lcss:
            raise ValueError(f"MID {mid}: LCSS {m.lcss} is not in the deck.")
        else:
            x, y = _bilinear_or_pairs(m)
            curve = HardeningCurve(x, y / s_scale, modulus, float(x[-1]),
                                   m.title or str(mid), {"from": "SIGY/ETAN/EPS"})
        return Mat024(
            mid=mid, density=m.ro / DENSITY_SCALE[us], modulus=modulus, curve=curve,
            table=table, poisson=m.pr, c=m.c / t_scale if table is None else 0.0,
            p=m.p if table is None else 0.0, vp=int(m.vp), fail=max(m.fail, 0.0),
            tdel=m.tdel * t_scale, curve_id=m.lcss or None, title=m.title,
            provenance={"source": self.source, "line": m.line, "unit_system": us})


def _bilinear_or_pairs(m: Mat024Keyword) -> tuple[FloatArray, FloatArray]:
    pairs = [(e, s) for e, s in zip(m.eps, m.es) if s > 0]
    if pairs:
        x = np.array([e for e, _ in pairs])
        y = np.array([s for _, s in pairs])
        return x, y
    if m.sigy <= 0:
        raise ValueError(f"MID {m.mid}: no LCSS, EPS/ES or SIGY.")
    return np.array([0.0, 1.0]), np.array([m.sigy, m.sigy + m.etan])


# --- Reading ------------------------------------------------------------------------


def _fields(line: str, width: int, count: int) -> list[str]:
    if "," in line:
        parts = [f.strip() for f in line.split(",")]
    else:
        parts = [line[i:i + width].strip() for i in range(0, width * count, width)]
    return (parts + [""] * count)[:count]


def _num(text: str, params: list[str], name: str) -> float:
    if not text:
        return 0.0
    if text.startswith("&") or text.startswith("-&"):
        params.append(f"{name}={text}")
        return 0.0
    t = text.replace("D", "E").replace("d", "e")
    if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)[-+]\d+", t):     # Fortran 1.0-3
        t = re.sub(r"(\d)([-+]\d+)$", r"\1e\2", t)
    return float(t)


def _blocks(lines: list[str]) -> Iterable[tuple[int, str, list[tuple[int, str]]]]:
    """(line number, keyword, data lines) for every keyword."""
    current: tuple[int, str] | None = None
    data: list[tuple[int, str]] = []
    for no, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n\r")
        if line.startswith("*"):
            if current:
                yield current[0], current[1], data
            current, data = (no, line.strip()), []
        elif current and line.strip() and not line.startswith("$"):
            data.append((no, line))
    if current:
        yield current[0], current[1], data


def read_keyword(source: str | Path) -> KeywordDeck:
    """Read the ``*MAT_024`` cards, curves and tables of a keyword file.

    ``source`` is a path or the keyword text itself (any text with a
    line break). Only ``*MAT_PIECEWISE_LINEAR_PLASTICITY`` /
    ``*MAT_024`` cards are read as materials; every ``*DEFINE_CURVE``
    and ``*DEFINE_TABLE`` is read (the curves directly after a table
    belong to it). ``*INCLUDE`` files are not followed (noted in
    ``notes``).
    """
    if isinstance(source, Path) or "\n" not in str(source):
        path = Path(source)
        text = path.read_text(errors="replace")
        name = str(path)
    else:
        text, name = str(source), "<text>"
    lines = text.splitlines()
    long_format = any(re.match(r"^\*KEYWORD.*LONG\s*=\s*[YS]", ln, re.I)
                      for ln in lines[:200])
    materials: dict[int, Mat024Keyword] = {}
    gissmo: dict[int, GissmoKeyword] = {}
    curves: dict[int, KeywordCurve] = {}
    tables: dict[int, KeywordTable] = {}
    notes: list[str] = []
    pending_table: tuple[int, FloatArray, str, int, int] | None = None
    table_curves: list[int] = []

    def close_table() -> None:
        nonlocal pending_table, table_curves
        if pending_table is not None:
            tbid, values, title, line, _ = pending_table
            tables[tbid] = KeywordTable(tbid, values, tuple(table_curves), title, line)
        pending_table, table_curves = None, []

    for no, kw, data in _blocks(lines):
        upper = kw.upper().split()[0]
        wide = long_format or upper.endswith("+")
        w10, w20 = (20, 40) if wide else (10, 20)
        if upper.startswith("*INCLUDE"):
            notes.append(f"line {no}: {upper} not followed")
            continue
        mat = _MAT024.match(upper)
        crv = _CURVE.match(upper)
        tab = _TABLE.match(upper)
        if pending_table is not None and not crv:
            close_table()
        if mat:
            titled = bool(mat.group(2))
            title = data[0][1].strip() if titled and data else ""
            cards = data[1:] if titled else data
            if len(cards) < 2:
                notes.append(f"line {no}: incomplete *MAT_024 card")
                continue
            params: list[str] = []
            c1 = _fields(cards[0][1], w10, 8)
            c2 = _fields(cards[1][1], w10, 6)
            c3 = _fields(cards[2][1], w10, 8) if len(cards) > 2 else [""] * 8
            c4 = _fields(cards[3][1], w10, 8) if len(cards) > 3 else [""] * 8
            names = ("mid", "ro", "e", "pr", "sigy", "etan", "fail", "tdel")
            v1 = [_num(f, params, n) for f, n in zip(c1, names)]
            v2 = [_num(f, params, n) for f, n in
                  zip(c2, ("c", "p", "lcss", "lcsr", "vp", "lcf"))]
            mid = int(v1[0])
            materials[mid] = Mat024Keyword(
                mid=mid, ro=v1[1], e=v1[2], pr=v1[3], sigy=v1[4], etan=v1[5],
                fail=v1[6], tdel=v1[7], c=v2[0], p=v2[1], lcss=int(v2[2]),
                lcsr=int(v2[3]), vp=v2[4],
                eps=tuple(_num(f, params, "eps") for f in c3),
                es=tuple(_num(f, params, "es") for f in c4), title=title, line=no,
                parameters=tuple(params))
        elif crv:
            titled = bool(crv.group(1))
            title = data[0][1].strip() if titled and data else ""
            rows = data[1:] if titled else data
            if not rows:
                notes.append(f"line {no}: empty *DEFINE_CURVE")
                continue
            params = []
            head = [_num(f, params, "curve") for f in _fields(rows[0][1], w10, 7)]
            lcid = int(head[0])
            sfa, sfo = head[2] or 1.0, head[3] or 1.0
            pts = [[_num(f, params, "point") for f in _fields(r, w20, 2)]
                   for _, r in rows[1:]]
            arr = np.array(pts, dtype=float).reshape(-1, 2)
            curves[lcid] = KeywordCurve(lcid, sfa * arr[:, 0] + head[4],
                                        sfo * arr[:, 1] + head[5], title, no)
            if pending_table is not None:
                table_curves.append(lcid)
                if len(table_curves) == pending_table[4]:
                    close_table()
        elif tab:
            titled = bool(tab.group(1))
            title = data[0][1].strip() if titled and data else ""
            rows = data[1:] if titled else data
            params = []
            head = [_num(f, params, "table") for f in _fields(rows[0][1], w10, 3)]
            values = np.array([_num(_fields(r, w20, 1)[0], params, "value")
                               for _, r in rows[1:]])
            sfa = head[1] or 1.0
            pending_table = (int(head[0]), sfa * values + head[2], title, no,
                             len(values))
        elif gm := _GISSMO.match(upper):
            titled = bool(gm.group(1))
            cards = data[1:] if titled else data
            if len(cards) < 2:
                notes.append(f"line {no}: incomplete *MAT_ADD_DAMAGE_GISSMO card")
                continue
            params = []
            g1 = [_num(f, params, "gissmo") for f in _fields(cards[0][1], w10, 4)]
            g2 = [_num(f, params, "gissmo") for f in _fields(cards[1][1], w10, 7)]
            g3 = ([_num(f, params, "gissmo") for f in _fields(cards[2][1], w10, 3)]
                  if len(cards) > 2 else [0.0, 0.0, 0.0])
            gissmo[int(g1[0])] = GissmoKeyword(
                mid=int(g1[0]), dtyp=g1[1], refsz=g1[2], numfip=g1[3],
                lcsdg=int(g2[0]), ecrit=g2[1], dmgexp=g2[2], dcrit=g2[3],
                fadexp=g2[4], lcregd=int(g2[5]), lcsrs=int(g3[0]), shrf=g3[1],
                biaxf=g3[2], line=no, parameters=tuple(params))
        elif upper.startswith("*MAT_ADD_EROSION"):
            notes.append(f"line {no}: {upper} not read (GISSMO in *MAT_ADD_EROSION "
                         "is the older form)")
        elif upper.startswith("*DEFINE_TABLE"):
            notes.append(f"line {no}: {upper} not supported")
    close_table()
    return KeywordDeck(materials, curves, tables, name, tuple(notes), gissmo)


# --- Unit system ----------------------------------------------------------------------


def guess_unit_system(ro: float, e: float) -> str | None:
    """The unit system that makes both density and Young's modulus
    plausible for a ``*MAT_024`` solid (density 500-25 000 kg/m³, E
    500 MPa to 1000 GPa: plastics to steels), or None if none does (or
    more than one)."""
    hits = []
    for us, (s_scale, _) in UNIT_SYSTEMS.items():
        density = ro / DENSITY_SCALE[us]
        modulus = e / s_scale
        if 500 <= density <= 25_000 and 500 <= modulus <= 1e6:
            hits.append(us)
    if len(hits) == 2 and set(hits) == {"mm-ms-kg", "mm-s-kg"}:
        return None
    return hits[0] if len(hits) == 1 else None


# --- Checks ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardCheck:
    """Check result of one ``*MAT_024`` card."""

    mid: int
    unit_system: str | None
    issues: tuple[str, ...]
    """Errors: wrong or unstable results."""
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        head = (f"MID {self.mid} ({self.unit_system or 'unit system unknown'}): "
                + ("passed" if self.passed else "FAILED"))
        return "\n".join([head, *(f"  error: {i}" for i in self.issues),
                          *(f"  warning: {w}" for w in self.warnings)])


def _span(values: FloatArray) -> str:
    lo, hi = float(np.min(values)), float(np.max(values))
    return f"{lo:.4g}" if lo == hi else f"{lo:.4g}-{hi:.4g}"


def _rediscretisation_error(x: FloatArray, y: FloatArray, lcint: int) -> float:
    """Largest relative stress error when LS-DYNA re-samples the curve at
    ``lcint`` equal intervals over its abscissa range."""
    grid = np.linspace(x[0], x[-1], lcint + 1)
    coarse = np.interp(x, grid, np.interp(grid, x, y))
    return float(np.max(np.abs(coarse - y) / np.maximum(np.abs(y), 1e-30)))


def _check_curve(name: str, x: FloatArray, y: FloatArray, e: float, sigy: float,
                 lcint: int, issues: list[str], warnings: list[str]) -> None:
    if len(x) < 2:
        issues.append(f"{name}: fewer than 2 points")
        return
    if abs(x[0]) > 1e-12:
        issues.append(f"{name}: starts at plastic strain {x[0]:g}, not 0")
    if np.any(np.diff(x) <= 0):
        issues.append(f"{name}: plastic strain not strictly increasing")
        return
    if np.any(y <= 0):
        issues.append(f"{name}: stress zero or negative")
    slope = np.diff(y) / np.diff(x)
    if np.any(slope > e):
        k = int(np.argmax(slope))
        issues.append(f"{name}: hardening slope {slope[k]:.4g} above E {e:.4g} at "
                      f"plastic strain {x[k]:.4g} (unstable)")
    if np.any(slope < 0):
        warnings.append(f"{name}: stress decreases (softening) at plastic strain "
                        f"{float(np.min(x[:-1][slope < 0])):.4g}")
    if sigy > 0 and abs(y[0] - sigy) > 0.01 * y[0]:
        warnings.append(f"{name}: SIGY {sigy:.4g} differs from the curve's first "
                        f"stress {y[0]:.4g}")
    err = _rediscretisation_error(x, y, lcint)
    if err > 0.01:
        warnings.append(f"{name}: re-sampled at {lcint} equal intervals (LCINT) the "
                        f"curve changes by up to {err * 100:.1f} %; add points near "
                        "yield, shorten the curve or raise LCINT")
    if x[-1] < 0.5:
        warnings.append(f"{name}: ends at plastic strain {x[-1]:.3g}; LS-DYNA "
                        "extrapolates the last segment beyond it")


def check_keyword(
    deck: KeywordDeck,
    *,
    unit_system: str | None = None,
    mids: Sequence[int] | None = None,
    lcint: int = 100,
) -> list[CardCheck]:
    """Check every ``*MAT_024`` card of a deck (or ``mids``).

    Errors:

    - density and Young's modulus not of one unit system (or not of the
      given ``unit_system``);
    - Poisson's ratio outside 0-0.5; LCSS not in the deck; no hardening;
    - a curve not starting at zero plastic strain, not increasing in
      strain, with zero or negative stress, or hardening more steeply
      than E (unstable);
    - a rate table whose values do not increase, with missing curves,
      or with crossing curves (negative rate sensitivity).

    Warnings: SIGY not matching the curve; softening; curve detail lost
    when LS-DYNA re-samples the curve at ``lcint`` equal intervals
    (``*CONTROL_SOLUTION`` LCINT, default 100); a curve ending below
    50 % plastic strain; C and P given with a rate table (ignored);
    implausible rates for the unit system; ``&parameters`` not checked.
    """
    results = []
    for mid in (mids if mids is not None else sorted(deck.materials)):
        m = deck.materials[mid]
        issues: list[str] = []
        warnings: list[str] = []
        guessed = guess_unit_system(m.ro, m.e)
        us = unit_system or guessed
        if unit_system and guessed and guessed != unit_system:
            issues.append(f"RO {m.ro:g} and E {m.e:g} look like {guessed}, not "
                          f"{unit_system}")
        elif unit_system and not guessed:
            s_scale, _ = UNIT_SYSTEMS[unit_system]
            issues.append(f"RO {m.ro:g} ({m.ro / DENSITY_SCALE[unit_system]:.4g} "
                          f"kg/m³) and E {m.e:g} ({m.e / s_scale:.4g} MPa) are not "
                          f"plausible together in {unit_system}")
        elif not unit_system and not guessed:
            issues.append(f"RO {m.ro:g} and E {m.e:g} do not belong to one unit "
                          "system (mm-ms-kg: 7.85e-6 / 210; mm-s-t: 7.85e-9 / "
                          "210000)")
        if not 0 <= m.pr < 0.5:
            issues.append(f"PR {m.pr:g} outside 0-0.5")
        if m.parameters:
            warnings.append("fields given as parameters, not checked: "
                            + ", ".join(m.parameters))
        if m.lcss and m.lcss in deck.tables:
            tb = deck.tables[m.lcss]
            if m.c or m.p:
                warnings.append("C and P are given with a rate table (LCSS); the "
                                "table holds the rate effect")
            if np.any(np.diff(tb.values) <= 0):
                issues.append(f"table {tb.tbid}: values not strictly increasing")
            missing = [i for i in tb.curve_ids if i not in deck.curves]
            if missing or not tb.curve_ids:
                issues.append(f"table {tb.tbid}: curves missing {missing}")
            else:
                members = [deck.curves[i] for i in tb.curve_ids]
                for value, lc in zip(tb.values, members):
                    _check_curve(f"table {tb.tbid} curve {lc.lcid} (value {value:g})",
                                 lc.x, lc.y, m.e, m.sigy if lc is members[0] else 0.0,
                                 lcint, issues, warnings)
                end = min(float(lc.x[-1]) for lc in members)
                grid = np.unique(np.concatenate([lc.x[lc.x <= end] for lc in members]))
                rows = [np.interp(grid, lc.x, lc.y) for lc in members]
                for k in range(1, len(rows)):
                    below = rows[k] < rows[k - 1] * (1 - 1e-9)
                    if np.any(below):
                        issues.append(
                            f"table {tb.tbid}: curve {members[k].lcid} below curve "
                            f"{members[k - 1].lcid} at plastic strain "
                            f"{_span(grid[below])} (curves cross)")
                if us:
                    _, t_scale = UNIT_SYSTEMS[us]
                    rates = (np.exp(tb.values) if tb.log_rates else tb.values) / t_scale
                    if rates[-1] > 1e5:
                        warnings.append(f"table {tb.tbid}: highest rate "
                                        f"{rates[-1]:.3g} /s in {us}; check the "
                                        "time unit")
                    if rates[-1] < 1.0:
                        warnings.append(f"table {tb.tbid}: highest rate "
                                        f"{rates[-1]:.3g} /s in {us}; check the "
                                        "time unit")
        elif m.lcss and m.lcss in deck.curves:
            lc = deck.curves[m.lcss]
            _check_curve(f"curve {lc.lcid}", lc.x, lc.y, m.e, m.sigy, lcint, issues,
                         warnings)
        elif m.lcss:
            issues.append(f"LCSS {m.lcss} is not in the deck (in an include?)")
        elif m.sigy <= 0 and not any(s > 0 for s in m.es):
            issues.append("no hardening: LCSS, EPS/ES and SIGY all empty")
        if (m.c == 0) != (m.p == 0) and m.lcss not in deck.tables:
            warnings.append("only one of C and P is given: no rate effect")
        results.append(CardCheck(mid, us, tuple(issues), tuple(warnings)))
    return results


def check_gissmo(
    deck: KeywordDeck,
    *,
    unit_system: str | None = None,
    mids: Sequence[int] | None = None,
) -> list[CardCheck]:
    """Check every ``*MAT_ADD_DAMAGE_GISSMO`` card of a deck (or ``mids``).

    Errors: curves referenced by LCSDG, ECRIT, FADEXP, LCREGD or LCSRS
    missing; Lode- or temperature-dependent tables (not checked); and
    the errors of `GissmoCard.check`. Warnings: no ``*MAT_024`` with
    the same MID in the deck; DMGEXP or FADEXP left blank (LS-DYNA
    default used); element sizes assumed in mm; the warnings of
    `GissmoCard.check` (failure curve range, critical strain above the
    failure strain, no coupling, DMGEXP below 1, regularisation rising
    with size).
    """
    results = []
    for mid in (mids if mids is not None else sorted(deck.gissmo)):
        g = deck.gissmo[mid]
        issues: list[str] = []
        warnings: list[str] = []
        us, known = deck._units(mid, unit_system)
        if mid not in deck.materials:
            warnings.append("no *MAT_024 with this MID in the deck (another "
                            "material, or in an include)")
        if not known:
            warnings.append("unit system unknown: element sizes taken as mm")
        if g.dmgexp == 0:
            warnings.append("DMGEXP blank: LS-DYNA default 1 used")
        if g.fadexp == 0:
            warnings.append("FADEXP blank: 1 assumed here; check your LS-DYNA "
                            "version's default")
        if g.parameters:
            warnings.append("fields given as parameters, not checked: "
                            + ", ".join(g.parameters))
        try:
            card = deck.damage(mid, us)
        except ValueError as exc:
            issues.append(str(exc).split(": ", 1)[-1])
            results.append(CardCheck(mid, us if known else None, tuple(issues),
                                     tuple(warnings)))
            continue
        errs, warns = card.check()
        issues += list(errs)
        warnings += list(warns)
        results.append(CardCheck(mid, us if known else None, tuple(issues),
                                 tuple(warnings)))
    return results


# --- Conversion and comparison ------------------------------------------------


def convert_keyword(
    source: str | Path | KeywordDeck,
    to_system: str,
    *,
    from_system: str | None = None,
    mids: Sequence[int] | None = None,
) -> str:
    """The ``*MAT_024`` cards (with their curves and tables) of a deck in
    another unit system, as keyword text.

    The original points, IDs and titles are kept; ``from_system``
    defaults to `guess_unit_system` per card. Tables are written with
    ln(rate) values when they had them.
    """
    deck = source if isinstance(source, KeywordDeck) else read_keyword(source)
    out = []
    for mid in (mids if mids is not None else sorted(deck.materials)):
        mat = deck.material(mid, from_system)
        lcss = deck.materials[mid].lcss
        log = deck.tables[lcss].log_rates if lcss in deck.tables else True
        out.append(mat.keyword(to_system, points=None, log_rates=log))
    return "".join(out)


@dataclass(frozen=True)
class CardComparison:
    """Two cards side by side (engineering units)."""

    names: tuple[str, str]
    rows: tuple[tuple[str, float, float], ...]
    """(quantity, value a, value b)."""

    def summary(self) -> str:
        a, b = self.names
        lines = [f"{'':28} {a[:12]:>12} {b[:12]:>12} {'diff %':>8}"]
        for label, va, vb in self.rows:
            if va == vb or (va and abs(vb - va) <= 1e-9 * abs(va)):
                diff = "0.00"
            elif va:
                diff = f"{(vb - va) / va * 100:.2f}"
            else:
                diff = "-"
            lines.append(f"{label:28} {va:12.5g} {vb:12.5g} {diff:>8}")
        return "\n".join(lines)


def compare_cards(
    a: Mat024,
    b: Mat024,
    *,
    strains: Sequence[float] = (0.0, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0),
    rates: Sequence[float | None] = (None, 100.0),
    names: tuple[str, str] | None = None,
) -> CardComparison:
    """Compare two cards (for example a supplier's and your own, or the
    same card before and after a change).

    Rows: density, E, Poisson's ratio, SIGY, C, P, FAIL, and the true
    stress (`Mat024.stress`) at every plastic strain in ``strains`` and
    rate in ``rates`` (``None``: without rate effect, the lowest table
    curve).
    """
    rows: list[tuple[str, float, float]] = [
        ("density kg/m3", a.density, b.density),
        ("E MPa", a.modulus, b.modulus),
        ("PR", a.poisson, b.poisson),
        ("SIGY MPa", a.yield_stress, b.yield_stress),
        ("C 1/s", a.c, b.c), ("P", a.p, b.p), ("FAIL", a.fail, b.fail),
    ]
    for rate in rates:
        tag = "static" if rate is None else f"{rate:g}/s"
        pts = np.asarray(strains, dtype=float)
        sa, sb = a.stress(pts, rate), b.stress(pts, rate)
        rows += [(f"stress {tag} @ {e:g} MPa", float(x), float(y))
                 for e, x, y in zip(strains, sa, sb)]
    return CardComparison(names or (a.title or str(a.mid), b.title or str(b.mid)),
                          tuple(rows))
