"""Tensile test data for material cards: read, clean, properties.

The first step towards an LS-DYNA ``*MAT_PIECEWISE_LINEAR_PLASTICITY``
(``*MAT_024``) card:

- `read_tensile`: a tensile test from a CSV / text export or an Excel
  ``.xlsx`` file, as force-elongation (with the specimen size) or as
  engineering stress-strain. Columns are found by their header names.
- `TensileTest`: engineering stress-strain curve of one specimen;
  `TensileTest.from_force_elongation` builds it from machine data.
- `clean_tensile`: cuts the curve after fracture, smooths noise and
  removes the toe region at the start (the initial non-linear part from
  specimen seating and slack), so the curve starts at the origin with
  the elastic slope.
- `tensile_properties`: Young's modulus (linear fit), offset yield
  strength Rp0.2, tensile strength Rm, uniform elongation and
  elongation after fracture, following the definitions of ISO 6892-1.

Units: stress in MPa (N/mm²), force in N, lengths in mm, strain
dimensionless (mm/mm, not %). Young's modulus is in MPa (210 000 MPa for
steel).
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "TensileProperties",
    "TensileTest",
    "clean_tensile",
    "read_tensile",
    "tensile_properties",
]

FloatArray = NDArray[np.float64]
Column = str | int


# --- The test ----------------------------------------------------------------


@dataclass(frozen=True)
class TensileTest:
    """Engineering stress-strain curve of one tensile specimen."""

    strain: FloatArray
    """Engineering strain, - (mm/mm)."""
    stress: FloatArray
    """Engineering stress, MPa."""
    name: str = ""
    info: Mapping[str, object] = field(default_factory=dict)
    """Specimen data, source file, columns and processing steps."""

    def __post_init__(self) -> None:
        strain = np.asarray(self.strain, dtype=float)
        stress = np.asarray(self.stress, dtype=float)
        if strain.ndim != 1 or stress.shape != strain.shape:
            raise ValueError("strain and stress must be 1D arrays of equal length.")
        if len(strain) < 3:
            raise ValueError("A tensile curve needs at least 3 points.")
        if not (np.all(np.isfinite(strain)) and np.all(np.isfinite(stress))):
            raise ValueError("strain and stress must be finite.")
        object.__setattr__(self, "strain", strain)
        object.__setattr__(self, "stress", stress)
        object.__setattr__(self, "info", dict(self.info))

    def __len__(self) -> int:
        return len(self.strain)

    @classmethod
    def from_force_elongation(
        cls,
        force: ArrayLike,
        elongation: ArrayLike,
        *,
        gauge_length: float,
        area: float | None = None,
        width: float | None = None,
        thickness: float | None = None,
        diameter: float | None = None,
        name: str = "",
        info: Mapping[str, object] | None = None,
    ) -> TensileTest:
        """Engineering stress-strain from force (N) and elongation (mm).

        ``stress = force / area`` with the original cross-section: give
        ``area`` (mm²), ``width`` and ``thickness`` (flat specimen, mm) or
        ``diameter`` (round specimen, mm). ``strain = elongation /
        gauge_length`` (extensometer gauge length, mm).
        """
        s0 = _area(area, width, thickness, diameter)
        if not (math.isfinite(gauge_length) and gauge_length > 0):
            raise ValueError("gauge_length must be positive.")
        f = np.asarray(force, dtype=float)
        dl = np.asarray(elongation, dtype=float)
        meta = {"area_mm2": s0, "gauge_length_mm": float(gauge_length),
                **(dict(info) if info else {})}
        return cls(dl / gauge_length, f / s0, name, meta)


def _area(area: float | None, width: float | None, thickness: float | None,
          diameter: float | None) -> float:
    given = [area is not None, width is not None or thickness is not None,
             diameter is not None]
    if sum(given) != 1:
        raise ValueError("Give the cross-section as area, as width and thickness, "
                         "or as diameter (one of them).")
    if area is not None:
        s0 = float(area)
    elif diameter is not None:
        s0 = math.pi * float(diameter) ** 2 / 4.0
    else:
        if width is None or thickness is None:
            raise ValueError("Give both width and thickness.")
        s0 = float(width) * float(thickness)
    if not (math.isfinite(s0) and s0 > 0):
        raise ValueError("The cross-section must be positive.")
    return s0


# --- Reading files -----------------------------------------------------------

_NUMBER = re.compile(r"^[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?$")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _read_text_table(path: Path, delimiter: str | None) -> list[list[str]]:
    text = _decode(path.read_bytes())
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path} is empty.")
    if delimiter is None:
        # The separator that makes the most lines rows of 2+ numbers (a
        # decimal comma rules out the comma); ties: tab, ";", ",", space.
        sample = lines[: min(len(lines), 200)]

        def numeric_rows(d: str) -> int:
            count = 0
            for ln in sample:
                cells = [c.strip() for c in (ln.split() if d == " " else ln.split(d))]
                cells = [c for c in cells if c]
                count += len(cells) >= 2 and all(_is_number(c) for c in cells)
            return count

        delimiter = max(("\t", ";", ",", " "), key=numeric_rows)
    if delimiter == " ":
        return [ln.split() for ln in lines]
    return [[cell.strip() for cell in row]
            for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)]


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    if not letters:
        raise ValueError(f"Bad cell reference {ref!r}.")
    index = 0
    for ch in letters.group(0):
        index = index * 26 + ord(ch) - 64
    return index - 1


def _read_xlsx(path: Path, sheet: str | int | None) -> list[list[str]]:
    """Cell texts of one worksheet of an .xlsx file (values, not formulas)."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        sheets = [(s.get("name", ""), s.get(f"{{{_NS['r']}}}id", ""))
                  for s in book.iterfind("m:sheets/m:sheet", _NS)]
        if not sheets:
            raise ValueError(f"{path} has no worksheets.")
        if sheet is None:
            chosen = sheets[0]
        elif isinstance(sheet, int):
            chosen = sheets[sheet]
        else:
            match = [s for s in sheets if s[0] == sheet]
            if not match:
                raise ValueError(f"No sheet {sheet!r} in {path}; sheets: "
                                 f"{', '.join(s[0] for s in sheets)}.")
            chosen = match[0]
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target", "") for r in rels.iterfind("p:Relationship", _NS)
                      if r.get("Id") == chosen[1])
        target = target.lstrip("/")
        sheet_path = target if target.startswith("xl/") else f"xl/{target}"
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            sst = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sst.iterfind("m:si", _NS):
                texts = si.iter(f"{{{_NS['m']}}}t")
                shared.append("".join(t.text or "" for t in texts))
        root = ElementTree.fromstring(z.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.iterfind("m:sheetData/m:row", _NS):
        cells: dict[int, str] = {}
        for i, c in enumerate(row.iterfind("m:c", _NS)):
            ref = c.get("r")
            col = _column_index(ref) if ref else i
            kind = c.get("t", "n")
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                v = c.find("m:v", _NS)
                text = v.text or "" if v is not None else ""
                if kind == "s" and text:
                    text = shared[int(text)]
            cells[col] = text.strip()
        if cells:
            rows.append([cells.get(j, "") for j in range(max(cells) + 1)])
    return rows


def _is_number(text: str) -> bool:
    return bool(_NUMBER.match(text.replace(" ", "")))


def _to_number(text: str, decimal_comma: bool) -> float:
    t = text.replace(" ", "")
    if decimal_comma:
        t = t.replace(".", "").replace(",", ".") if t.count(",") == 1 else t
    return float(t)


def _split_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Column labels (all text rows above the data, joined) and data rows."""
    start = None
    for i, row in enumerate(rows):
        cells = [c for c in row if c]
        if len(cells) >= 2 and all(_is_number(c) for c in cells):
            start = i
            break
    if start is None:
        raise ValueError("No numeric data rows found.")
    width = max(len(r) for r in rows)
    labels = [" ".join(r[j] for r in rows[:start] if j < len(r) and r[j]).strip()
              for j in range(width)]
    return labels, rows[start:]


def _find_column(labels: Sequence[str], wanted: Column, role: str) -> int:
    if isinstance(wanted, int):
        if not 0 <= wanted < len(labels):
            raise ValueError(f"{role}: column {wanted} does not exist.")
        return wanted
    key = wanted.lower()
    exact = [j for j, lab in enumerate(labels) if lab.lower() == key]
    if len(exact) == 1:
        return exact[0]
    found = [j for j, lab in enumerate(labels) if key in lab.lower()]
    if len(found) != 1:
        raise ValueError(f"{role}: {'no' if not found else 'several'} columns "
                         f"match {wanted!r}; columns: {list(labels)}.")
    return found[0]


_AUTO = {
    "stress": ("stress", "spannung"),
    "strain": ("strain", "dehnung"),
    "force": ("force", "load", "kraft"),
    "elongation": ("elongation", "extension", "displacement", "deformation",
                   "verlängerung"),
}


def _auto_column(labels: Sequence[str], role: str) -> int | None:
    hits = [j for j, lab in enumerate(labels)
            if any(word in lab.lower() for word in _AUTO[role])]
    if len(hits) > 1:
        raise ValueError(f"Several columns could be the {role}: "
                         f"{[labels[j] for j in hits]}; name it with {role}=.")
    return hits[0] if hits else None


def _unit_scale(label: str, given: str | None, table: Mapping[str, float],
                default: str, role: str) -> tuple[float, str]:
    if given is None:
        text = label.lower()
        given = next((u for u in sorted(table, key=len, reverse=True)
                      if re.search(rf"(^|[\s\[(/]){re.escape(u.lower())}($|[\s\])])",
                                   text)), default)
    if given not in table:
        raise ValueError(f"Unknown {role} unit {given!r}; known: {', '.join(table)}.")
    return table[given], given


_STRAIN_UNITS = {"-": 1.0, "%": 0.01, "mm/mm": 1.0}
_STRESS_UNITS = {"MPa": 1.0, "N/mm2": 1.0, "N/mm²": 1.0, "GPa": 1000.0,
                 "kPa": 0.001, "Pa": 1e-6}
_FORCE_UNITS = {"N": 1.0, "kN": 1000.0}
_LENGTH_UNITS = {"mm": 1.0, "m": 1000.0, "µm": 0.001, "um": 0.001}


def read_tensile(
    path: str | Path,
    *,
    strain: Column | None = None,
    stress: Column | None = None,
    force: Column | None = None,
    elongation: Column | None = None,
    gauge_length: float | None = None,
    area: float | None = None,
    width: float | None = None,
    thickness: float | None = None,
    diameter: float | None = None,
    strain_unit: str | None = None,
    stress_unit: str | None = None,
    force_unit: str | None = None,
    elongation_unit: str | None = None,
    sheet: str | int | None = None,
    delimiter: str | None = None,
    decimal: str | None = None,
    name: str | None = None,
) -> TensileTest:
    """Read a tensile test from a CSV / text file or an ``.xlsx`` file.

    Give either engineering ``strain`` and ``stress`` columns, or
    ``force`` and ``elongation`` columns with ``gauge_length`` and the
    cross-section (``area``, ``width`` and ``thickness``, or
    ``diameter``; see `TensileTest.from_force_elongation`). Columns are
    header names (case-insensitive; a unique part of the name is
    enough) or 0-based indices. Without any column names, columns whose
    headers contain "stress" and "strain" (or "force"/"load" and
    "elongation"/"extension"/"displacement") are used.

    All text rows above the data are read as headers, so a units row
    under the names is fine. Units are taken from the header when they
    appear there (for example ``Strain [%]``, ``Force (kN)``), or from
    the ``*_unit`` arguments: strain ``"-"`` or ``"%"``; stress
    ``"MPa"``, ``"GPa"``, ``"Pa"``; force ``"N"`` or ``"kN"``;
    elongation ``"mm"`` or ``"m"``.

    Parameters
    ----------
    path:
        ``.csv``, ``.txt``, ``.dat`` (any delimiter: comma, semicolon,
        tab or spaces) or ``.xlsx``. Old ``.xls`` files: save as
        ``.xlsx`` or CSV first.
    sheet:
        Worksheet name or 0-based index (``.xlsx``; default the first).
    delimiter:
        Text files: the column separator (default: detected).
    decimal:
        ``","`` for decimal commas (default: detected for semicolon or
        tab separated files).
    name:
        Specimen name (default: the file name).

    Returns
    -------
    TensileTest
        With ``info`` recording the file, sheet, columns and units used.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".xls":
        raise ValueError("Old .xls files are not supported; save as .xlsx or CSV.")
    rows = _read_xlsx(p, sheet) if suffix in (".xlsx", ".xlsm") else \
        _read_text_table(p, delimiter)
    labels, data = _split_header(rows)

    if decimal is None:
        sample = [c for r in data[:50] for c in r if c]
        decimal_comma = (any(re.fullmatch(r"[-+]?\d+,\d+", c) for c in sample)
                         and not any("." in c for c in sample))
    else:
        decimal_comma = decimal == ","

    use_stress = strain is not None or stress is not None
    use_force = force is not None or elongation is not None
    if use_stress and use_force:
        raise ValueError("Give strain and stress, or force and elongation, not both.")
    if not (use_stress or use_force):
        auto = {role: _auto_column(labels, role) for role in _AUTO}
        if auto["stress"] is not None and auto["strain"] is not None:
            strain, stress = auto["strain"], auto["stress"]
            use_stress = True
        elif auto["force"] is not None and auto["elongation"] is not None:
            force, elongation = auto["force"], auto["elongation"]
            use_force = True
        else:
            raise ValueError("Could not find stress/strain or force/elongation "
                             f"columns in {list(labels)}; name them.")

    def column(wanted: Column | None, role: str) -> tuple[FloatArray, str]:
        if wanted is None:
            raise ValueError(f"Give the {role} column.")
        j = _find_column(labels, wanted, role)
        values = []
        for r in data:
            cell = r[j] if j < len(r) else ""
            if cell and _is_number(cell):
                values.append(_to_number(cell, decimal_comma))
            else:
                values.append(math.nan)
        return np.asarray(values), labels[j]

    meta: dict[str, object] = {"source": str(p)}
    if suffix in (".xlsx", ".xlsm"):
        meta["sheet"] = sheet if sheet is not None else 0
    if use_stress:
        e, e_label = column(strain, "strain")
        s, s_label = column(stress, "stress")
        e_scale, e_unit = _unit_scale(e_label, strain_unit, _STRAIN_UNITS, "-",
                                      "strain")
        s_scale, s_unit = _unit_scale(s_label, stress_unit, _STRESS_UNITS, "MPa",
                                      "stress")
        keep = np.isfinite(e) & np.isfinite(s)
        meta.update(columns={"strain": e_label, "stress": s_label},
                    units={"strain": e_unit, "stress": s_unit})
        return TensileTest(e[keep] * e_scale, s[keep] * s_scale, name or p.stem, meta)
    if gauge_length is None:
        raise ValueError("Force-elongation data needs gauge_length (mm).")
    f, f_label = column(force, "force")
    dl, dl_label = column(elongation, "elongation")
    f_scale, f_unit = _unit_scale(f_label, force_unit, _FORCE_UNITS, "N", "force")
    l_scale, l_unit = _unit_scale(dl_label, elongation_unit, _LENGTH_UNITS, "mm",
                                  "elongation")
    keep = np.isfinite(f) & np.isfinite(dl)
    meta.update(columns={"force": f_label, "elongation": dl_label},
                units={"force": f_unit, "elongation": l_unit})
    return TensileTest.from_force_elongation(
        f[keep] * f_scale, dl[keep] * l_scale, gauge_length=gauge_length, area=area,
        width=width, thickness=thickness, diameter=diameter, name=name or p.stem,
        info=meta)


# --- Cleaning ----------------------------------------------------------------


@dataclass(frozen=True)
class _Modulus:
    slope: float
    intercept: float
    r2: float
    points: int


def _fit_modulus(strain: FloatArray, stress: FloatArray,
                 window: tuple[float, float],
                 window_stress: tuple[float, float] | None) -> _Modulus:
    """Least-squares line through the loading curve between two stresses."""
    peak = int(np.argmax(stress))
    if window_stress is not None:
        lo, hi = window_stress
    else:
        if not 0.0 <= window[0] < window[1] <= 1.0:
            raise ValueError("modulus_window must be fractions 0 <= low < high <= 1.")
        lo, hi = window[0] * stress[peak], window[1] * stress[peak]
    if not lo < hi:
        raise ValueError("The modulus window needs low < high.")
    # Loading branch only: up to the first point above the window.
    above = np.flatnonzero(stress[: peak + 1] > hi)
    end = int(above[0]) if len(above) else peak + 1
    sel = np.flatnonzero((stress[:end] >= lo) & (stress[:end] <= hi))
    if len(sel) < 3:
        raise ValueError(f"Only {len(sel)} points between {lo:.1f} and {hi:.1f} MPa "
                         "for the modulus fit; widen modulus_window or check the "
                         "data.")
    x, y = strain[sel], stress[sel]
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / total if total > 0 else 1.0
    if slope <= 0:
        raise ValueError("The elastic slope is not positive; check the columns.")
    return _Modulus(float(slope), float(intercept), r2, len(sel))


def _savgol(y: FloatArray, window: int, order: int = 2) -> FloatArray:
    """Savitzky-Golay smoothing (least-squares polynomial in a moving window)."""
    if window < order + 2 or window % 2 == 0:
        raise ValueError("smooth must be an odd number of points >= "
                         f"{order + 3 - (order % 2)}.")
    half = window // 2
    x = np.arange(-half, half + 1, dtype=float)
    coeffs = np.linalg.pinv(np.vander(x, order + 1, increasing=True))[0]
    padded = np.concatenate((2 * y[0] - y[half:0:-1], y,
                             2 * y[-1] - y[-2:-half - 2:-1]))
    return np.convolve(padded, coeffs[::-1], mode="valid")


def clean_tensile(
    test: TensileTest,
    *,
    cut_fracture: bool = True,
    fracture_drop: float = 0.1,
    smooth: int = 0,
    toe: bool = True,
    modulus_window: tuple[float, float] = (0.1, 0.4),
    modulus_stress: tuple[float, float] | None = None,
) -> TensileTest:
    """Clean an engineering stress-strain curve, in this order:

    1. **Cut after fracture** (``cut_fracture``): the curve ends at the
       last point before the first sudden stress drop after the maximum,
       a drop larger than ``fracture_drop`` times the maximum stress from
       one point to the next (default 10 %), or where the stress falls
       below 10 % of the maximum.
    2. **Smooth** (``smooth``, odd number of points, 0 = off): Savitzky-
       Golay filter (quadratic) on the stress. Use the smallest window
       that removes the noise; it rounds sharp yield points.
    3. **Toe correction** (``toe``, as ISO 6892-1): a straight line is
       fitted to the loading curve between ``modulus_window`` fractions
       of the maximum stress (or between ``modulus_stress`` in MPa). The
       strain is shifted so the line passes through the origin, the
       points below the window are replaced by the origin, and the
       curve then rises with the fitted slope.

    Returns a new `TensileTest`; ``info["cleaning"]`` records what was
    done (cut point, strain shift, points removed).
    """
    strain, stress = test.strain.copy(), test.stress.copy()
    log: dict[str, object] = {}
    if cut_fracture:
        if not 0 < fracture_drop < 1:
            raise ValueError("fracture_drop must be between 0 and 1.")
        peak = int(np.argmax(stress))
        top = stress[peak]
        drops = np.flatnonzero((np.diff(stress[peak:]) < -fracture_drop * top)
                               | (stress[peak + 1:] < 0.1 * top))
        if len(drops):
            end = peak + int(drops[0]) + 1
            log["cut_after_strain"] = float(strain[end - 1])
            log["points_cut"] = len(strain) - end
            strain, stress = strain[:end], stress[:end]
    if smooth:
        if smooth > len(stress):
            raise ValueError("smooth is longer than the curve.")
        stress = _savgol(stress, smooth)
        log["smoothing_window"] = smooth
    if toe:
        mod = _fit_modulus(strain, stress, modulus_window, modulus_stress)
        shift = -mod.intercept / mod.slope
        lo = (modulus_stress[0] if modulus_stress is not None
              else modulus_window[0] * float(np.max(stress)))
        first = int(np.flatnonzero(stress >= lo)[0])
        strain = np.concatenate(([0.0], strain[first:] - shift))
        stress = np.concatenate(([0.0], stress[first:]))
        log.update(toe_strain_shift=float(shift), toe_points_removed=first,
                   modulus=mod.slope)
    if len(strain) < 3:
        raise ValueError("Fewer than 3 points left after cleaning.")
    info = dict(test.info)
    info["cleaning"] = log
    return replace(test, strain=strain, stress=stress, info=info)


# --- Properties --------------------------------------------------------------


@dataclass(frozen=True)
class TensileProperties:
    """Tensile properties of one engineering stress-strain curve
    (ISO 6892-1 definitions)."""

    modulus: float
    """Young's modulus E, MPa (slope of the linear fit)."""
    modulus_r2: float
    """Coefficient of determination of the modulus fit."""
    yield_strength: float
    """Offset yield strength Rp (Rp0.2 by default), MPa."""
    yield_strain: float
    """Total engineering strain at Rp."""
    offset: float
    """Plastic strain offset used for Rp (0.002 = 0.2 %)."""
    tensile_strength: float
    """Tensile strength Rm (maximum engineering stress), MPa."""
    uniform_elongation_total: float
    """Agt: total engineering strain at Rm."""
    uniform_elongation: float
    """Ag: plastic engineering strain at Rm, ``Agt - Rm / E``."""
    fracture_strain_total: float
    """At: total engineering strain at the end of the curve (fracture,
    if the curve was cut there)."""
    elongation_after_fracture: float
    """A: plastic engineering strain at fracture, ``At - stress / E``."""
    fracture_stress: float
    """Engineering stress at the end of the curve, MPa."""

    @property
    def yield_ratio(self) -> float:
        """Rp / Rm."""
        return self.yield_strength / self.tensile_strength

    def summary(self, name: str = "") -> str:
        """Short text report (strains in %)."""
        title = f"Tensile properties{f' of {name}' if name else ''}"
        return "\n".join([
            title,
            f"  E       {self.modulus / 1000:9.1f} GPa   (R² {self.modulus_r2:.4f})",
            f"  Rp{self.offset * 100:g}   {self.yield_strength:9.1f} MPa",
            f"  Rm      {self.tensile_strength:9.1f} MPa   (Rp/Rm "
            f"{self.yield_ratio:.3f})",
            f"  Ag      {self.uniform_elongation * 100:9.2f} %     (Agt "
            f"{self.uniform_elongation_total * 100:.2f} %)",
            f"  A       {self.elongation_after_fracture * 100:9.2f} %     (At "
            f"{self.fracture_strain_total * 100:.2f} %)",
        ])


def tensile_properties(
    test: TensileTest,
    *,
    modulus_window: tuple[float, float] = (0.1, 0.4),
    modulus_stress: tuple[float, float] | None = None,
    offset: float = 0.002,
) -> TensileProperties:
    """Young's modulus, Rp, Rm, uniform elongation and elongation after
    fracture of an engineering stress-strain curve.

    - **E**: least-squares line through the loading curve between
      ``modulus_window`` fractions of Rm (default 10-40 %), or between
      ``modulus_stress`` (MPa) if given.
    - **Rp**: first intersection of the curve with the fitted line moved
      by ``offset`` in strain (Rp0.2 with the default 0.002), linearly
      interpolated between samples. The line keeps its fitted intercept,
      so a toe region does not shift Rp.
    - **Rm**, **Agt**, **Ag**: maximum stress, total and plastic strain
      there.
    - **At**, **A**: total and plastic strain at the last point. Cut the
      curve at fracture first (`clean_tensile`).
    """
    if not 0 <= offset < 0.1:
        raise ValueError("offset must be a strain between 0 and 0.1.")
    e, s = test.strain, test.stress
    mod = _fit_modulus(e, s, modulus_window, modulus_stress)
    peak = int(np.argmax(s))
    gap = s[: peak + 1] - (mod.slope * (e[: peak + 1] - offset) + mod.intercept)
    below = np.flatnonzero((gap[:-1] > 0) & (gap[1:] <= 0))
    if not len(below):
        raise ValueError(f"The curve does not cross the {offset * 100:g} % offset "
                         "line before Rm; check the data or the modulus window.")
    i = int(below[0])
    w = gap[i] / (gap[i] - gap[i + 1])
    rp_strain = float(e[i] + w * (e[i + 1] - e[i]))
    rp = float(s[i] + w * (s[i + 1] - s[i]))
    rm = float(s[peak])
    agt = float(e[peak])
    at = float(e[-1])
    return TensileProperties(
        modulus=mod.slope, modulus_r2=mod.r2, yield_strength=rp,
        yield_strain=rp_strain, offset=offset, tensile_strength=rm,
        uniform_elongation_total=agt, uniform_elongation=agt - rm / mod.slope,
        fracture_strain_total=at,
        elongation_after_fracture=at - float(s[-1]) / mod.slope,
        fracture_stress=float(s[-1]),
    )
