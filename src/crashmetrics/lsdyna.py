"""LS-DYNA output readers and the ``crashmetrics-energy`` command.

Functions
---------
read_glstat, parse_glstat
    Global statistics (``glstat``) ASCII file -> GlobalEnergies.
read_matsum, parse_matsum
    Material/part energy summary (``matsum``) ASCII file -> PartEnergies.
read_d3hsp, parse_d3hsp
    d3hsp file -> D3hsp (see :mod:`crashmetrics.d3hsp`).
check_run
    Read a run directory's glstat (and matsum) and check its energies.
main
    Command-line entry point: ``crashmetrics-energy RUN_DIR``.

The parsers read values by their labels, not by position, so they do
not depend on the line order or on which optional channels a given
LS-DYNA version writes:

- glstat: lines of the form ``kinetic energy.......  1.23456E+05`` (one
  or more dots after the label); a new record starts at each
  ``time...`` line.
- matsum: ``key= value`` pairs; a new record starts at each ``time =``
  and a new part at each ``mat.#=`` (or ``part=``, ``pid=``). Part names
  come from the ``{BEGIN LEGEND}`` block and per-part added mass from
  ``+mass=``.

Fortran numbers such as ``1.23456-100`` (no ``E``) and ``1.0D+03`` are
read correctly. For binout output, read the variables with a binout
reader (for example lasso-python) and pass them to
:meth:`GlobalEnergies.from_mapping` / :meth:`PartEnergies.from_mapping`.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from crashmetrics.d3hsp import D3hsp, parse_d3hsp, read_d3hsp
from crashmetrics.energy_check import (
    EnergyLimits,
    EnergyReport,
    GlobalEnergies,
    PartEnergies,
    check_energies,
    normalise_name,
)

__all__ = [
    "D3hsp",
    "check_run",
    "main",
    "parse_d3hsp",
    "parse_glstat",
    "parse_matsum",
    "read_d3hsp",
    "read_glstat",
    "read_matsum",
]

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd]?[-+]?\d+)?"
_GLSTAT_LINE = re.compile(
    rf"^\s*(?P<label>[A-Za-z][^\n]*?)\s*\.+\s*(?P<value>{_NUMBER})\s*$"
)
_PAIR = re.compile(
    rf"(?P<key>[A-Za-z+\-][A-Za-z0-9_.#+\-]*)\s*=\s*(?P<value>{_NUMBER})"
)
_PART_KEYS = {"mat", "part", "pid", "part_id", "mat_id"}


def _to_float(text: str) -> float:
    """Parse a Fortran-style number, e.g. 1.2E+03, 1.2D+03 or 1.2-100."""
    s = text.strip().replace("D", "E").replace("d", "e")
    if "e" not in s.lower():
        # Exponent without a letter: mantissa then signed exponent.
        match = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+))([-+]\d+)", s)
        if match:
            s = f"{match.group(1)}E{match.group(2)}"
    return float(s)


def parse_glstat(text: str) -> GlobalEnergies:
    """Parse the text of an LS-DYNA glstat ASCII file."""
    records: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    pending = ""  # first half of a label that wraps onto the next line
    for line in text.splitlines():
        match = _GLSTAT_LINE.match(line)
        if not match:
            stripped = line.strip()
            # A text-only line (no digits, no dots) may start a label that
            # continues on the next line, e.g. "number of shell elements
            # that" / "reached the minimum time step..    0".
            wraps = stripped and not any(c.isdigit() for c in stripped)
            pending = stripped if wraps and "." not in stripped else ""
            continue
        label = f"{pending} {match.group('label')}" if pending else match.group("label")
        pending = ""
        key = normalise_name(label)
        try:
            value = _to_float(match.group("value"))
        except ValueError:
            continue
        if key == "time":
            current = {}
            records.append(current)
        if current is not None:
            current[key] = value

    if len(records) < 2:
        raise ValueError(
            f"Found {len(records)} glstat time records; at least two are "
            "needed. Is this a glstat file?"
        )
    keys = sorted({k for r in records for k in r})
    data = {k: np.array([r.get(k, np.nan) for r in records]) for k in keys}
    return GlobalEnergies.from_mapping(data)


def read_glstat(path: str | Path) -> GlobalEnergies:
    """Read an LS-DYNA glstat ASCII file."""
    return parse_glstat(Path(path).read_text(errors="replace"))


def _matsum_key(raw: str) -> str:
    prefix = ""
    if raw.startswith("+"):
        prefix = "plus_"
    elif raw.startswith("-"):
        prefix = "minus_"
    return prefix + normalise_name(raw)


def _legend(text: str) -> dict[int, str]:
    """Part names from a ``{BEGIN LEGEND}`` ... ``{END LEGEND}`` block."""
    names: dict[int, str] = {}
    inside = False
    for line in text.splitlines():
        if "{BEGIN LEGEND}" in line:
            inside = True
            continue
        if "{END LEGEND}" in line:
            break
        if inside:
            match = re.match(r"\s*(\d+)\s+(\S.*?)\s*$", line)
            if match:
                names[int(match.group(1))] = match.group(2)
    return names


def parse_matsum(text: str) -> PartEnergies:
    """Parse the text of an LS-DYNA matsum ASCII file."""
    blocks: list[tuple[float, dict[int, dict[str, float]]]] = []
    parts_in_order: list[int] = []
    seen: set[int] = set()
    current: dict[str, float] | None = None
    in_legend = False

    for line in text.splitlines():
        if "{BEGIN LEGEND}" in line:
            in_legend = True
        if in_legend:
            in_legend = "{END LEGEND}" not in line
            continue
        stripped = line.strip().lower()
        if stripped.startswith("summary"):
            current = None
            continue
        for match in _PAIR.finditer(line):
            key = _matsum_key(match.group("key"))
            try:
                value = _to_float(match.group("value"))
            except ValueError:
                continue
            if key == "time":
                blocks.append((value, {}))
                current = None
            elif key in _PART_KEYS and blocks:
                pid = int(round(value))
                current = blocks[-1][1].setdefault(pid, {})
                if pid not in seen:
                    seen.add(pid)
                    parts_in_order.append(pid)
            elif current is not None:
                current[key] = value

    blocks = [b for b in blocks if b[1]]
    if len(blocks) < 2 or not parts_in_order:
        raise ValueError(
            f"Found {len(blocks)} matsum time records with part data; at "
            "least two are needed. Is this a matsum file?"
        )
    time = np.array([b[0] for b in blocks])
    keys = sorted({k for _, parts in blocks for p in parts.values() for k in p})
    data = {
        k: np.array([[parts.get(pid, {}).get(k, np.nan) for pid in parts_in_order]
                     for _, parts in blocks])
        for k in keys
    }
    return PartEnergies.from_mapping(time, parts_in_order, data, _legend(text))


def read_matsum(path: str | Path) -> PartEnergies:
    """Read an LS-DYNA matsum ASCII file."""
    return parse_matsum(Path(path).read_text(errors="replace"))


def _find(directory: Path, name: str) -> Path | None:
    for candidate in (directory / name, directory / name.upper()):
        if candidate.is_file():
            return candidate
    return None


def check_run(
    run: str | Path,
    matsum: str | Path | None = None,
    limits: EnergyLimits | None = None,
) -> EnergyReport:
    """Check the energies of an LS-DYNA run.

    Parameters
    ----------
    run:
        Run directory containing ``glstat`` (and optionally ``matsum``),
        or the path of a glstat file.
    matsum:
        matsum file; by default ``matsum`` next to the glstat file is
        used if it exists.
    limits:
        Acceptance limits.
    """
    path = Path(run)
    if path.is_dir():
        glstat_path = _find(path, "glstat")
        if glstat_path is None:
            raise FileNotFoundError(f"No glstat file in {path}.")
    elif path.is_file():
        glstat_path = path
    else:
        raise FileNotFoundError(f"{path} does not exist.")

    if matsum is None:
        matsum_path = _find(glstat_path.parent, "matsum")
    else:
        matsum_path = Path(matsum)
        if not matsum_path.is_file():
            raise FileNotFoundError(f"{matsum_path} does not exist.")

    global_energies = read_glstat(glstat_path)
    part_energies = read_matsum(matsum_path) if matsum_path else None
    return check_energies(global_energies, part_energies, limits)


def _optional(value: str) -> float | None:
    return None if value.lower() in ("none", "off") else float(value)


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``crashmetrics-energy``. Exit code 0 = passed, 1 = failed, 2 = error."""
    defaults = EnergyLimits()
    ratio_min, ratio_max = defaults.energy_ratio or (0.95, 1.05)
    parser = argparse.ArgumentParser(
        prog="crashmetrics-energy",
        description="Check the energy balance of LS-DYNA runs (glstat, matsum).",
    )
    parser.add_argument("runs", nargs="+", help="run directories or glstat files")
    parser.add_argument("--matsum", help="matsum file (single run only)")
    parser.add_argument("--ratio-min", type=float, default=ratio_min)
    parser.add_argument("--ratio-max", type=float, default=ratio_max)
    parser.add_argument("--hourglass", type=_optional, default=defaults.hourglass,
                        help="max hourglass / internal energy (or 'off')")
    parser.add_argument("--negative-contact", type=_optional,
                        default=defaults.negative_contact)
    parser.add_argument("--damping", type=_optional, default=defaults.damping)
    parser.add_argument("--added-mass", type=_optional,
                        default=defaults.added_mass_percent, help="max added mass, %%")
    parser.add_argument("--eroded", type=_optional, default=defaults.eroded_energy)
    parser.add_argument("--part-hourglass", type=_optional,
                        default=defaults.part_hourglass)
    parser.add_argument("--part-negative-internal", type=_optional,
                        default=defaults.part_negative_internal)
    parser.add_argument("--part-min-share", type=float,
                        default=defaults.part_min_internal_share)
    args = parser.parse_args(argv)

    if args.matsum and len(args.runs) > 1:
        parser.error("--matsum can only be used with a single run.")

    limits = EnergyLimits(
        energy_ratio=(args.ratio_min, args.ratio_max),
        hourglass=args.hourglass,
        negative_contact=args.negative_contact,
        damping=args.damping,
        added_mass_percent=args.added_mass,
        eroded_energy=args.eroded,
        part_hourglass=args.part_hourglass,
        part_negative_internal=args.part_negative_internal,
        part_min_internal_share=args.part_min_share,
    )

    exit_code = 0
    for run in args.runs:
        print(f"== {run}")
        try:
            report = check_run(run, args.matsum, limits)
        except (OSError, ValueError) as error:
            print(f"ERROR: {error}")
            exit_code = 2
            continue
        print(report.summary())
        print()
        if not report.passed and exit_code == 0:
            exit_code = 1
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
