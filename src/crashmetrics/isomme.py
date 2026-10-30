"""ISO-MME (ISO/TS 13499) test data: read and write.

ISO-MME is the exchange format for crash test and simulation channels
used by test labs, NHTSA and Euro NCAP (for example for virtual testing
submissions). A test is a folder (or a zip of it)::

    <test>/
        <test>.mme              test header ("Key :Value" lines)
        Channel/
            <test>.chn          list of channels
            <test>.001          one file per channel: header, then values
            <test>.002
            ...

Each channel has a 16-character channel code, e.g. ``11HEADCG0000H3ACXA``
is test object 1, position 1, head centre of gravity, Hybrid III,
acceleration, x, CFC 1000 (see `parse_channel_code`).

Functions:

- `read_isomme`: Read a test folder, its ``.mme`` file or a ``.zip``.
- `write_isomme`: Write channels as an ISO-MME test folder (for example
  CAE results for a virtual testing submission).
- `parse_channel_code`: Split a channel code into its fields.

Header keys and values are kept as text. Values ``NOVALUE`` become NaN.
The time of each channel comes from ``Time of first sample`` and
``Sampling interval`` (implicit), from a reference time channel
(explicit), or, if neither is given, is None. Text in UTF-8,
Windows-1252 or ISO-8859-1 is read.
"""

import fnmatch
import io
import math
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "FILTER_CLASSES",
    "Channel",
    "ChannelCode",
    "IsoMmeTest",
    "parse_channel_code",
    "read_isomme",
    "write_isomme",
]

FILTER_CLASSES: dict[str, int | None] = {
    "A": 1000, "B": 600, "C": 180, "D": 60, "0": None,
}
"""Filter class letter (last character of a channel code) -> CFC.
``0`` means unfiltered; other letters are kept as given."""


@dataclass(frozen=True)
class ChannelCode:
    """Fields of a 16-character ISO-MME channel code."""

    code: str
    test_object: str
    """1st character, e.g. ``1`` for the first vehicle or dummy."""
    position: str
    """2nd character, e.g. ``1`` driver, ``3`` front passenger."""
    main_location: str
    """Characters 3-6, e.g. ``HEAD``, ``CHST``, ``PELV``, ``NECK``."""
    fine_location_1: str
    fine_location_2: str
    fine_location_3: str
    """Characters 11-12; often the dummy type (``H3``, ``TH``, ``HF`` ...)."""
    dimension: str
    """Characters 13-14, e.g. ``AC`` acceleration, ``FO`` force, ``DS``
    displacement."""
    direction: str
    """15th character: ``X``, ``Y``, ``Z``, ``R`` (resultant) ..."""
    filter_class: str
    """16th character: ``A`` CFC 1000, ``B`` 600, ``C`` 180, ``D`` 60,
    ``0`` unfiltered."""

    @property
    def cfc(self) -> int | None:
        """CFC of the filter class letter, None if unfiltered or unknown."""
        return FILTER_CLASSES.get(self.filter_class)


def parse_channel_code(code: str) -> ChannelCode:
    """Split a 16-character ISO-MME channel code into its fields."""
    c = code.strip()
    if len(c) != 16:
        raise ValueError(f"A channel code has 16 characters; got {code!r}.")
    return ChannelCode(c, c[0], c[1], c[2:6], c[6:8], c[8:10], c[10:12],
                       c[12:14], c[14], c[15])


@dataclass(frozen=True)
class Channel:
    """One ISO-MME channel."""

    code: str
    name: str
    unit: str
    time: NDArray[np.float64] | None
    """Time in s, or None if the file gives no time base."""
    values: NDArray[np.float64]
    """Values (NaN for ``NOVALUE`` samples)."""
    header: dict[str, list[str]] = field(default_factory=dict)
    """All header entries of the channel file (key -> values in order)."""

    def info(self, key: str, default: str = "") -> str:
        """First value of a header key ("" if missing or ``NOVALUE``)."""
        values = self.header.get(key, [])
        if not values or values[0].upper() == "NOVALUE":
            return default
        return values[0]

    @property
    def parsed_code(self) -> ChannelCode | None:
        """`ChannelCode` fields, or None if the code is not 16 characters."""
        try:
            return parse_channel_code(self.code)
        except ValueError:
            return None

    @property
    def cfc(self) -> int | None:
        """CFC from ``Channel frequency class``, else from the code."""
        text = self.info("Channel frequency class")
        if text:
            try:
                return int(float(text))
            except ValueError:
                pass
        code = self.parsed_code
        return code.cfc if code else None


@dataclass(frozen=True)
class IsoMmeTest:
    """An ISO-MME test: header and channels."""

    test_number: str
    header: dict[str, list[str]]
    """Entries of the ``.mme`` file (key -> values in order; ``Comments``
    and other repeated keys keep every value)."""
    channels: dict[str, Channel]
    """Channels by channel code, in file order."""

    def info(self, key: str, default: str = "") -> str:
        """First value of a test header key ("" if missing or ``NOVALUE``)."""
        values = self.header.get(key, [])
        if not values or values[0].upper() == "NOVALUE":
            return default
        return values[0]

    def find(self, pattern: str) -> list[Channel]:
        """Channels whose code matches a pattern with ``?`` (one
        character) and ``*`` wildcards, e.g. ``"11HEAD??????ACX?"``."""
        return [c for code, c in self.channels.items()
                if fnmatch.fnmatchcase(code, pattern)]

    def channel(self, pattern: str) -> Channel:
        """The one channel matching a code or pattern."""
        if pattern in self.channels:
            return self.channels[pattern]
        found = self.find(pattern)
        if len(found) != 1:
            shown = ", ".join(c.code for c in found[:10]) or "none"
            raise KeyError(f"{len(found)} channels match {pattern!r}: {shown}.")
        return found[0]

    def summary(self) -> str:
        """Short text description of the test."""
        title = f"ISO-MME test {self.test_number}: {self.info('Test type')}"
        lines = [title.rstrip(": "),
                 f"  {len(self.channels)} channels"]
        for code, ch in list(self.channels.items())[:12]:
            n = len(ch.values)
            span = ("" if ch.time is None or n == 0 else
                    f", {ch.time[0] * 1000:.2f} to {ch.time[-1] * 1000:.2f} ms")
            lines.append(f"  {code}  {ch.name} [{ch.unit}] {n} samples{span}")
        if len(self.channels) > 12:
            lines.append(f"  ... ({len(self.channels)} in total)")
        return "\n".join(lines)


# --- Reading -------------------------------------------------------------------

_HEADER = re.compile(r"^(?P<key>[^:]*?)\s*:(?P<value>.*)$")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")  # pragma: no cover


def _number(text: str) -> float | None:
    t = text.strip()
    if t.upper() == "NOVALUE":
        return math.nan
    try:
        return float(t.replace(",", ".") if t.count(",") == 1 and "." not in t else t)
    except ValueError:
        return None


def _parse(text: str) -> tuple[dict[str, list[str]], list[float]]:
    """Header entries and data values of an ISO-MME text file."""
    header: dict[str, list[str]] = {}
    values: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not values:
            match = _HEADER.match(line)
            if match and match.group("key"):
                header.setdefault(match.group("key").strip(), []).append(
                    match.group("value").strip())
                continue
        number = _number(line)
        if number is None:
            raise ValueError(f"Unexpected line in channel data: {raw!r}")
        values.append(number)
    return header, values


class _Source:
    """Files of a test folder or zip, found by name case-insensitively."""

    def __init__(self, path: Path):
        self.path = path
        self.zip: zipfile.ZipFile | None = None
        if path.is_file() and zipfile.is_zipfile(path):
            self.zip = zipfile.ZipFile(path)
            self.names = [n for n in self.zip.namelist() if not n.endswith("/")]
        else:
            root = path if path.is_dir() else path.parent
            self.names = [str(p.relative_to(root)).replace("\\", "/")
                          for p in root.rglob("*") if p.is_file()]
            self.root = root

    def read(self, name: str) -> str:
        if self.zip is not None:
            return _decode(self.zip.read(name))
        return _decode((self.root / name).read_bytes())

    def find(self, suffix_pattern: str) -> list[str]:
        rx = re.compile(suffix_pattern, re.I)
        return sorted(n for n in self.names if rx.search(n))


def read_isomme(path: str | Path) -> IsoMmeTest:
    """Read an ISO-MME test.

    Parameters
    ----------
    path:
        The test folder, its ``.mme`` file, or a ``.zip`` containing the
        test folder.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist.")
    source = _Source(path)
    mme_files = source.find(r"\.mme$")
    if path.suffix.lower() == ".mme":
        mme_files = [path.name]
    if not mme_files:
        raise ValueError(f"No .mme file found in {path}.")
    mme = mme_files[0]
    header, _ = _parse(source.read(mme))
    stem = Path(mme).name[:-4]
    prefix = str(Path(mme).parent).replace("\\", "/")
    prefix = "" if prefix in ("", ".") else prefix + "/"

    channel_files = [n for n in source.names
                     if re.fullmatch(rf"{re.escape(prefix)}channel/{re.escape(stem)}"
                                     r"\.\d{3}", n, re.I)]
    raw: list[tuple[dict[str, list[str]], list[float]]] = []
    for name in sorted(channel_files):
        raw.append(_parse(source.read(name)))

    by_code: dict[str, tuple[dict[str, list[str]], list[float]]] = {}
    for head, data in raw:
        code = (head.get("Channel code") or [""])[0].strip()
        if code:
            by_code[code] = (head, data)

    channels: dict[str, Channel] = {}
    for code, (head, data) in by_code.items():
        values = np.asarray(data, dtype=float)
        channels[code] = Channel(
            code=code,
            name=_text(head, "Name of the channel"),
            unit=_text(head, "Unit"),
            time=_time_axis(head, len(values), by_code),
            values=values,
            header=head,
        )
    number = (header.get("Test number") or [stem])[0] or stem
    return IsoMmeTest(test_number=number, header=header, channels=channels)


def _text(head: Mapping[str, list[str]], key: str) -> str:
    values = head.get(key, [])
    value = values[0].strip() if values else ""
    return "" if value.upper() == "NOVALUE" else value


def _time_axis(
    head: Mapping[str, list[str]],
    n: int,
    by_code: Mapping[str, tuple[dict[str, list[str]], list[float]]],
) -> NDArray[np.float64] | None:
    def get(key: str) -> str:
        values = head.get(key, [])
        return values[0].strip() if values else ""

    if get("Reference channel").lower() == "explicit":
        ref = by_code.get(get("Reference channel name"))
        if ref is not None and len(ref[1]) == n:
            return np.asarray(ref[1], dtype=float)
    first = _number(get("Time of first sample"))
    step = _number(get("Sampling interval"))
    if first is not None and step is not None and math.isfinite(first) \
            and math.isfinite(step) and step > 0:
        return np.asarray(first + step * np.arange(n), dtype=np.float64)
    return None


# --- Writing ---------------------------------------------------------------------

def _line(key: str, value: object) -> str:
    return f"{key:<28}:{value}"


def write_isomme(
    directory: str | Path,
    test_number: str,
    channels: Mapping[str, tuple[ArrayLike, ArrayLike]],
    units: Mapping[str, str] | None = None,
    names: Mapping[str, str] | None = None,
    header: Mapping[str, str | Sequence[str]] | None = None,
    data_source: str = "calculated",
) -> Path:
    """Write channels as an ISO-MME 1.6 test folder.

    Parameters
    ----------
    directory:
        Parent directory; the test folder ``<directory>/<test_number>``
        is created.
    test_number:
        Test number, used for the folder and file names.
    channels:
        Channel code -> ``(time, values)``, time in s and uniformly
        sampled (resample CAE output first, see
        `crashmetrics.signals.resample_uniform`).
    units, names:
        Unit and name per channel code (default: empty).
    header:
        Extra ``.mme`` entries, e.g. ``{"Test type": "Virtual testing",
        "Comments": ["...", "..."]}``.
    data_source:
        ``Data source`` of every channel (``calculated`` for simulations).

    Returns
    -------
    Path
        The test folder.
    """
    if not channels:
        raise ValueError("Give at least one channel.")
    folder = Path(directory) / test_number
    (folder / "Channel").mkdir(parents=True, exist_ok=True)
    units = dict(units or {})
    names = dict(names or {})

    mme = [_line("Data format", "ISO-MME"), _line("Version", "1.6"),
           _line("Test number", test_number)]
    for key, value in (header or {}).items():
        for text in ([value] if isinstance(value, str) else value):
            mme.append(_line(key, text))
    _write(folder / f"{test_number}.mme", mme)

    chn = [_line("Number of channels", len(channels))]
    for i, (code, (time, values)) in enumerate(channels.items(), start=1):
        parse_channel_code(code)
        t = np.asarray(time, dtype=float)
        v = np.asarray(values, dtype=float)
        if t.ndim != 1 or t.shape != v.shape or len(t) < 2:
            raise ValueError(f"{code}: time and values must be 1D, equal length, >= 2.")
        steps = np.diff(t)
        step = float(np.mean(steps))
        if step <= 0 or not np.allclose(steps, step, rtol=1e-6, atol=1e-12):
            raise ValueError(f"{code}: time must be uniformly sampled and increasing.")
        name = names.get(code, "")
        chn.append(_line(f"Name of channel {i:03d}", f"{code} / {name}".rstrip(" /")))
        lines = [
            _line("Channel code", code),
            _line("Name of the channel", name or "NOVALUE"),
            _line("Data source", data_source),
            _line("Unit", units.get(code, "NOVALUE")),
            _line("Reference channel", "implicit"),
            _line("Time of first sample", f"{t[0]:.9g}"),
            _line("Sampling interval", f"{step:.9g}"),
            _line("Number of samples", len(v)),
        ]
        code_fields = parse_channel_code(code)
        if code_fields.cfc is not None:
            lines.insert(4, _line("Channel frequency class", code_fields.cfc))
        lines += ["NOVALUE" if not math.isfinite(x) else f"{x:.6E}" for x in v]
        _write(folder / "Channel" / f"{test_number}.{i:03d}", lines)
    _write(folder / "Channel" / f"{test_number}.chn", chn)
    return folder


def _write(path: Path, lines: Iterable[str]) -> None:
    with io.open(path, "w", encoding="latin-1", errors="replace", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
