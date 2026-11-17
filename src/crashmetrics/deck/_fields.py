"""Fields of keyword cards: splitting a line, reading and writing values.

A card line is either fixed format (fields of a set width, 10 by default,
20 in long format) or free format (fields separated by commas). Values
can be parameter references (``&name`` or ``-&name``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

_FORTRAN_EXP = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+))([-+]\d+)$")


@dataclass(frozen=True)
class Slot:
    """Where a field's text is in its line: ``start`` and ``width`` in
    fixed format, or the field number ``index`` in comma format."""

    start: int
    width: int
    index: int = -1

    @property
    def comma(self) -> bool:
        return self.index >= 0


def split_line(line: str, widths: Sequence[int]) -> list[tuple[str, Slot]]:
    """The fields of a line, with where each one is."""
    if "," in line:
        parts = line.split(",")
        out = []
        for i in range(len(widths)):
            out.append((parts[i].strip() if i < len(parts) else "", Slot(0, 0, i)))
        return out
    out, pos = [], 0
    for w in widths:
        out.append((line[pos : pos + w].strip(), Slot(pos, w)))
        pos += w
    return out


def is_param(text: str) -> bool:
    t = text.strip()
    return t.startswith("&") or t.startswith("-&")


def param_name(text: str) -> str:
    return text.strip().lstrip("-").lstrip("&").strip().lower()


def to_float(text: str) -> float:
    """A number as LS-DYNA writes it: ``1.5``, ``1.5E+03``, ``1.5D3``,
    ``1.5+3`` (exponent without E). Blank is 0."""
    t = text.strip()
    if not t:
        return 0.0
    t = t.replace("D", "E").replace("d", "e")
    m = _FORTRAN_EXP.match(t)
    if m:
        t = f"{m.group(1)}E{m.group(2)}"
    return float(t)


def to_int(text: str) -> int:
    t = text.strip()
    if not t:
        return 0
    try:
        return int(t)
    except ValueError:
        v = to_float(t)
        if not math.isfinite(v) or v != int(v):
            raise ValueError(f"{text!r} is not an integer") from None
        return int(v)


def format_value(value: object, width: int, kind: str) -> str:
    """A value written into a field of ``width`` characters (numbers
    right aligned, text left aligned); the shortest exact form that fits."""
    if kind == "s" or isinstance(value, str):
        s = str(value)
        if len(s) > width:
            raise ValueError(f"{s!r} does not fit in {width} characters")
        return s.ljust(width) if kind == "s" else s.rjust(width)
    if kind == "i":
        s = str(int(value))  # type: ignore[call-overload]
        if len(s) > width:
            raise ValueError(f"{s} does not fit in {width} characters")
        return s.rjust(width)
    v = float(value)  # type: ignore[arg-type]
    for s in _float_forms(v):
        if len(s) <= width:
            return s.rjust(width)
    raise ValueError(f"{v} does not fit in {width} characters")


def _float_forms(v: float) -> list[str]:
    if v == 0:
        return ["0.0", "0."]
    forms = []
    r = repr(v)
    if "e" not in r and "inf" not in r and "nan" not in r:
        forms.append(r)
    for p in range(17, 0, -1):
        s = f"{v:.{p}E}"
        mant, exp = s.split("E")
        mant = mant.rstrip("0")
        if mant.endswith("."):
            mant += "0"
        forms.append(f"{mant}E{int(exp):+d}")
        g = f"{v:.{p}g}"
        if "e" not in g:
            forms.append(g if "." in g else g + ".")
    seen, out = set(), []
    # most exact first; then "2.0" before "2."; then the shortest
    for f in sorted(forms, key=lambda s: (-_digits(s, v), s.endswith("."), len(s))):
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _digits(s: str, v: float) -> float:
    """Correct significant digits of a form (100 when exact)."""
    try:
        f = float(s)
    except ValueError:
        return -100.0
    if f == v:
        return 100.0
    return -math.log10(abs(f - v) / abs(v))


def replace_field(line: str, slot: Slot, text: str) -> str:
    """The line with one field replaced (fixed or comma format)."""
    if slot.comma:
        parts = line.split(",")
        while len(parts) <= slot.index:
            parts.append("")
        parts[slot.index] = text.strip() if text.strip() else ""
        return ",".join(parts)
    end = slot.start + slot.width
    padded = line.ljust(end)
    return (padded[: slot.start] + text + padded[end:]).rstrip()
