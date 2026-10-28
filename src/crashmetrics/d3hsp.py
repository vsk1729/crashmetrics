"""LS-DYNA d3hsp reader.

Functions:

- `read_d3hsp`, `parse_d3hsp`: Read a d3hsp file into a `D3hsp`
  summary.

What is read
------------
- Run information: version, SMP/MPP, precision, revision, platform,
  run date, command line options, input file, number of CPUs.
- Termination status: ``"normal"``, ``"error"`` or ``"incomplete"``
  (no termination banner: still running, killed or crashed).
- Warnings and errors (``*** Warning 41123 (SOL+1123)`` and the message
  lines after it), with counts by message number.
- Model size (nodes, elements by type, materials, contacts) and every
  ``label.......  value`` setting echoed by LS-DYNA (``parameters``),
  plus the keyword counts (``total # of *KEYWORD....  n``).
- Mass summary: mass of each part (rigid bodies marked) and total mass.
- The smallest time steps table: element type, element, part, time step.
- Timing: problem time and cycles, CPU and elapsed time, threads or
  processes, the CPU/clock breakdown by solver phase, and memory.

The reader works from labels and patterns, not line numbers, and was
built and tested on SMP d3hsp files from LS-DYNA R14.1 and R16.1. MPP
runs use the same layout for these items; the reader accepts ``mpp`` in
the version line and ``MPP procs`` in the elapsed-time line, but check it
on your own MPP output.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crashmetrics.energy_check import normalise_name

__all__ = [
    "D3hsp",
    "D3hspMessage",
    "TimestepElement",
    "TimingRow",
    "parse_d3hsp",
    "read_d3hsp",
]

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd]?[-+]?\d+)?"
# "label.......  value": one or more dots, then spaces (labels that fill
# their field end in a single dot).
_SETTING = re.compile(
    rf"^\s*(?P<label>[A-Za-z#][^\n]*?)\s*(?:\.{{2,}}\s*|\.\s+)(?P<value>{_NUMBER})\s*$"
)
# "total # of *KEYWORD....  n", where long names may have one dot or none.
_KEYWORD_COUNT = re.compile(
    r"^\s*total # of\s+(?P<keyword>\*.*?)[.\s]*\s(?P<count>\d+)\s*$"
)
_BOX = re.compile(
    r"^\s*\|\s*(?P<key>Version|Revision|Platform|OS Level|Compiler|Hostname"
    r"|Precision|AnLicVer)\s*:\s*(?P<value>.*?)\s*\|\s*$"
)
_RUN_DATE = re.compile(r"^\s*Date:\s*(?P<date>\S+)\s+Time:\s*(?P<time>\S+)\s*$")
_MESSAGE = re.compile(
    r"^\s*\*\*\*\s*(?P<kind>Warning|Error)\s+(?P<number>\d+)"
    r"\s*(?:\((?P<code>[^)]*)\))?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_TERMINATION = re.compile(
    r"^\s*(?P<kind>N\s+o\s+r\s+m\s+a\s+l|E\s+r\s+r\s+o\s+r)\s+"
    r"t\s+e\s+r\s+m\s+i\s+n\s+a\s+t\s+i\s+o\s+n\s*(?P<when>.*)$"
)
_PART_MASS = re.compile(
    rf"^\s*part\s+id\s*=?\s*(?P<pid>\d+)\s+mass\s*=\s*(?P<mass>{_NUMBER})"
    r"\s*(?P<rigid>rigid\s+body)?",
    re.IGNORECASE,
)
_TOTAL_MASS = re.compile(
    rf"^\s*t\s+o\s+t\s+a\s+l\s+m\s+a\s+s\s+s\s*=\s*(?P<mass>{_NUMBER})"
)
_TIMESTEP_ROW = re.compile(
    rf"^\s*(?P<type>[A-Za-z][\w-]*)\s+(?P<eid>\d+)\s+(?P<pid>\d+)\s+(?P<dt>{_NUMBER})\s*$"
)
_TIMING_ROW = re.compile(
    rf"^(?P<indent>\s+)(?P<name>\S.*?)[\s.]+(?P<cpu>{_NUMBER})\s+(?P<cpu_pct>{_NUMBER})"
    rf"\s+(?P<clock>{_NUMBER})\s+(?P<clock_pct>{_NUMBER})\s*$"
)
_ELAPSED = re.compile(
    r"^\s*Elapsed time\s+(?P<seconds>\d+)\s+seconds?\s+for\s+(?P<cycles>\d+)"
    r"\s+cycles?\s+using\s+(?P<count>\d+)\s+(?P<unit>.+?)\s*$"
)
_MEMORY = re.compile(
    r"^\s*(?P<label>Memory required to (?:begin|complete) solution|"
    r"Additional dynamically allocated memory|Total)\s*:\s*(?P<value>\S+)\s*$"
)

# Model-size settings and the names they are reported under.
_MODEL_KEYS = {
    "number_of_nodal_scalar_points": "nodes",
    "number_of_solid_elements": "solid_elements",
    "number_of_shell_elements": "shell_elements",
    "number_of_beam_elements": "beam_elements",
    "number_of_thick_shell_elements": "thick_shell_elements",
    "number_of_materials_or_property_sets": "materials",
    "number_of_number_of_contact_definitions": "contacts",
    "number_of_contact_definitions": "contacts",
    "number_of_parts_with_added_mass": "parts_with_added_mass",
}


def _number(text: str) -> float:
    s = text.strip().replace("D", "E").replace("d", "e")
    match = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+))([-+]\d+)", s)
    if match:
        s = f"{match.group(1)}E{match.group(2)}"
    return float(s)


@dataclass(frozen=True)
class D3hspMessage:
    """A warning or error message."""

    kind: str
    """``"warning"`` or ``"error"``."""
    number: int
    code: str
    """Category code, e.g. ``"SOL+1123"``."""
    text: str
    """Message text (the lines following the header, joined)."""
    line: int
    """Line number in the file (1-based)."""


@dataclass(frozen=True)
class TimestepElement:
    """One row of the smallest time steps table."""

    element_type: str
    element_id: int
    part_id: int
    timestep: float


@dataclass(frozen=True)
class TimingRow:
    """One row of the timing information table."""

    name: str
    cpu: float
    cpu_percent: float
    clock: float
    clock_percent: float
    level: int
    """0 for a solver phase, 1 for a sub-item of the phase above."""


@dataclass(frozen=True)
class D3hsp:
    """Summary of an LS-DYNA d3hsp file. Missing items are None or empty."""

    version: str | None = None
    """Version line, e.g. ``"smp d R16"``."""
    parallel: str | None = None
    """``"smp"`` or ``"mpp"``."""
    precision: str | None = None
    """``"single"`` or ``"double"``."""
    release: str | None = None
    """e.g. ``"R16"``."""
    revision: str | None = None
    platform: str | None = None
    compiler: str | None = None
    hostname: str | None = None
    run_date: str | None = None
    """Date and time the run started, as printed."""
    command_line: tuple[str, ...] = ()
    input_file: str | None = None
    ncpu: int | None = None

    termination: str = "incomplete"
    """``"normal"``, ``"error"`` or ``"incomplete"``."""
    termination_time: str | None = None

    messages: tuple[D3hspMessage, ...] = ()

    model: dict[str, int] = field(default_factory=dict)
    """Nodes, elements by type, materials, contacts (when reported)."""
    parameters: dict[str, float] = field(default_factory=dict)
    """Every echoed ``label.....  value`` setting, by normalised label
    (first occurrence), e.g. ``"termination_time"``,
    ``"time_step_scale_factor"``."""
    keyword_counts: dict[str, int] = field(default_factory=dict)
    """Number of each keyword in the input, e.g. ``{"*CONTACT_option": 2}``
    (first occurrence where LS-DYNA prints a name twice)."""

    part_masses: dict[int, float] = field(default_factory=dict)
    rigid_parts: tuple[int, ...] = ()
    total_mass: float | None = None

    smallest_timesteps: tuple[TimestepElement, ...] = ()

    problem_time: float | None = None
    problem_cycles: int | None = None
    cpu_seconds: float | None = None
    elapsed_seconds: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    workers: int | None = None
    """Number of SMP threads or MPP processes from the elapsed-time line."""
    worker_type: str | None = None
    """e.g. ``"SMP threads"``."""
    timing: tuple[TimingRow, ...] = ()
    memory: dict[str, str] = field(default_factory=dict)
    """Last memory report, e.g. ``{"total": "755K"}``."""

    @property
    def normal_termination(self) -> bool:
        return self.termination == "normal"

    @property
    def warnings(self) -> tuple[D3hspMessage, ...]:
        return tuple(m for m in self.messages if m.kind == "warning")

    @property
    def errors(self) -> tuple[D3hspMessage, ...]:
        return tuple(m for m in self.messages if m.kind == "error")

    def message_counts(self) -> dict[tuple[str, int], int]:
        """Number of messages by (kind, number), most frequent first."""
        counts = Counter((m.kind, m.number) for m in self.messages)
        return dict(counts.most_common())

    @property
    def min_timestep(self) -> TimestepElement | None:
        """Element with the smallest time step, from the d3hsp table."""
        if not self.smallest_timesteps:
            return None
        return min(self.smallest_timesteps, key=lambda e: e.timestep)

    def summary(self) -> str:
        """Plain-text summary of the run."""
        lines = [f"Termination: {self.termination.upper()}"
                 + (f" ({self.termination_time})" if self.termination_time else "")]
        if self.version:
            lines.append(
                f"LS-DYNA {self.version}"
                + (f", revision {self.revision}" if self.revision else "")
                + (f", {self.platform}" if self.platform else "")
            )
        if self.input_file:
            lines.append(f"Input: {self.input_file}")
        if self.model:
            lines.append(
                "Model: " + ", ".join(f"{k} {v}" for k, v in self.model.items())
            )
        if self.total_mass is not None:
            lines.append(
                f"Total mass: {self.total_mass:.6g} ({len(self.part_masses)} parts, "
                f"{len(self.rigid_parts)} rigid)"
            )
        smallest = self.min_timestep
        if smallest is not None:
            lines.append(
                f"Smallest time step: {smallest.timestep:.4g} ("
                f"{smallest.element_type} {smallest.element_id}, "
                f"part {smallest.part_id})"
            )
        if self.problem_cycles is not None:
            lines.append(
                f"Problem time {self.problem_time:.6g} in {self.problem_cycles} cycles"
            )
        if self.elapsed_seconds is not None:
            workers = (f" using {self.workers} {self.worker_type}"
                       if self.workers is not None else "")
            lines.append(f"Elapsed: {self.elapsed_seconds:g} s{workers}"
                         + (f", CPU {self.cpu_seconds:g} s"
                            if self.cpu_seconds is not None else ""))
        lines.append(f"Warnings: {len(self.warnings)}, errors: {len(self.errors)}")
        for (kind, number), count in list(self.message_counts().items())[:10]:
            first = next(m for m in self.messages
                         if m.kind == kind and m.number == number)
            lines.append(
                f"  {kind} {number} ({first.code}) x{count}: {first.text[:70]}"
            )
        return "\n".join(lines)


def parse_d3hsp(text: str) -> D3hsp:
    """Parse the text of an LS-DYNA d3hsp file."""
    lines = text.splitlines()
    info: dict[str, Any] = {}
    box: dict[str, str] = {}
    command_line: list[str] = []
    messages: list[D3hspMessage] = []
    parameters: dict[str, float] = {}
    keyword_counts: dict[str, int] = {}
    part_masses: dict[int, float] = {}
    rigid: list[int] = []
    timesteps: list[TimestepElement] = []
    timing: list[TimingRow] = []
    memory: dict[str, str] = {}

    in_command_line = False
    in_timesteps = False
    in_timing = False
    in_mass_summary = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if (m := _BOX.match(line)) and m.group("key") not in box:
            box[m.group("key")] = m.group("value")
        elif "run_date" not in info and (m := _RUN_DATE.match(line)):
            info["run_date"] = f"{m.group('date')} {m.group('time')}"

        if stripped.startswith("Command line options:"):
            in_command_line = True
            stripped = stripped.split(":", 1)[1].strip()
        if in_command_line:
            if stripped:
                command_line.extend(stripped.split())
            else:
                in_command_line = False
        if stripped.startswith("Input file:"):
            info["input_file"] = stripped.split(":", 1)[1].strip()

        if m := _MESSAGE.match(line):
            body = [m.group("rest").strip()] if m.group("rest").strip() else []
            j = i + 1
            while j < len(lines) and lines[j].strip() and not _MESSAGE.match(lines[j]):
                body.append(lines[j].strip())
                j += 1
            messages.append(D3hspMessage(
                kind=m.group("kind").lower(), number=int(m.group("number")),
                code=(m.group("code") or "").strip(), text=" ".join(body), line=i + 1,
            ))

        if m := _TERMINATION.match(line):
            kind = m.group("kind").replace(" ", "").lower()
            info["termination"] = "normal" if kind == "normal" else "error"
            info["termination_time"] = m.group("when").strip() or None

        if m := _KEYWORD_COUNT.match(line):
            keyword_counts.setdefault(m.group("keyword"), int(m.group("count")))
        elif (m := _SETTING.match(line)) and not stripped.startswith("|"):
            label = m.group("label")
            if label.startswith("#"):  # "# of solid elements ..." -> number of
                label = "number" + label[1:]
            key = normalise_name(label)
            if key not in parameters:
                parameters[key] = _number(m.group("value"))

        if stripped.lower() == "summary of mass":
            in_mass_summary = True
        elif in_mass_summary:
            if m := _PART_MASS.match(line):
                pid = int(m.group("pid"))
                part_masses[pid] = _number(m.group("mass"))
                if m.group("rigid"):
                    rigid.append(pid)
            elif m := _TOTAL_MASS.match(line):
                info["total_mass"] = _number(m.group("mass"))
                in_mass_summary = False

        if "smallest timesteps" in stripped.lower():
            in_timesteps = True
            timesteps = []  # keep the last table if printed more than once
        elif in_timesteps:
            if m := _TIMESTEP_ROW.match(line):
                timesteps.append(TimestepElement(
                    m.group("type"), int(m.group("eid")), int(m.group("pid")),
                    _number(m.group("dt")),
                ))
            elif stripped and not stripped.startswith(("-", "element")):
                in_timesteps = False

        if stripped.replace(" ", "").lower() == "timinginformation":
            in_timing = True
            timing = []
        elif in_timing:
            if stripped.replace(" ", "").lower().startswith("totals"):
                in_timing = False
            elif m := _TIMING_ROW.match(line):
                timing.append(TimingRow(
                    name=m.group("name").strip(" ."),
                    cpu=_number(m.group("cpu")),
                    cpu_percent=_number(m.group("cpu_pct")),
                    clock=_number(m.group("clock")),
                    clock_percent=_number(m.group("clock_pct")),
                    level=0 if len(m.group("indent")) <= 2 else 1,
                ))

        if m := _MEMORY.match(line):
            memory[normalise_name(m.group("label"))] = m.group("value")

        if m := re.match(rf"^\s*Problem time\s*=\s*({_NUMBER})", line):
            info["problem_time"] = _number(m.group(1))
        elif m := re.match(r"^\s*Problem cycle\s*=\s*(\d+)", line):
            info["problem_cycles"] = int(m.group(1))
        elif m := re.match(r"^\s*Total CPU time\s*=\s*(\d+)\s+seconds?", line):
            info["cpu_seconds"] = float(m.group(1))
        elif m := re.match(r"^\s*Number of CPU'?s\s+(\d+)", line):
            info["ncpu"] = int(m.group(1))
        elif m := re.match(r"^\s*Start time\s+(\d.*?)\s*$", line):
            info["start_time"] = m.group(1)
        elif m := re.match(r"^\s*End time\s+(\d.*?)\s*$", line):
            info["end_time"] = m.group(1)
        elif m := _ELAPSED.match(line):
            info["elapsed_seconds"] = float(m.group("seconds"))
            info["workers"] = int(m.group("count"))
            info["worker_type"] = m.group("unit")
        i += 1

    if "ncpu" not in info:
        for option in command_line:
            if option.lower().startswith("ncpu="):
                try:
                    info["ncpu"] = abs(int(option.split("=", 1)[1]))
                except ValueError:
                    pass

    version = box.get("Version")
    parallel = precision = release = None
    if version:
        tokens = version.split()
        if tokens and tokens[0].lower() in ("smp", "mpp"):
            parallel = tokens[0].lower()
        if len(tokens) > 1 and tokens[1].lower() in ("s", "d"):
            precision = "single" if tokens[1].lower() == "s" else "double"
        release = next((t for t in tokens if re.fullmatch(r"R\d.*", t)), None)
    if precision is None and "Precision" in box:
        text_precision = box["Precision"].lower()
        precision = ("double" if "double" in text_precision
                     else "single" if "single" in text_precision else None)

    model = {name: int(parameters[key]) for key, name in _MODEL_KEYS.items()
             if key in parameters}

    if not (version or parameters or messages or "termination" in info):
        raise ValueError("No LS-DYNA d3hsp content found. Is this a d3hsp file?")

    return D3hsp(
        version=version,
        parallel=parallel,
        precision=precision,
        release=release,
        revision=box.get("Revision"),
        platform=box.get("Platform"),
        compiler=box.get("Compiler"),
        hostname=box.get("Hostname"),
        run_date=info.get("run_date"),
        command_line=tuple(command_line),
        input_file=info.get("input_file"),
        ncpu=info.get("ncpu"),
        termination=info.get("termination", "incomplete"),
        termination_time=info.get("termination_time"),
        messages=tuple(messages),
        model=model,
        parameters=parameters,
        keyword_counts=keyword_counts,
        part_masses=part_masses,
        rigid_parts=tuple(rigid),
        total_mass=info.get("total_mass"),
        smallest_timesteps=tuple(timesteps),
        problem_time=info.get("problem_time"),
        problem_cycles=info.get("problem_cycles"),
        cpu_seconds=info.get("cpu_seconds"),
        elapsed_seconds=info.get("elapsed_seconds"),
        start_time=info.get("start_time"),
        end_time=info.get("end_time"),
        workers=info.get("workers"),
        worker_type=info.get("worker_type"),
        timing=tuple(timing),
        memory=memory,
    )


def read_d3hsp(path: str | Path) -> D3hsp:
    """Read an LS-DYNA d3hsp file."""
    return parse_d3hsp(Path(path).read_text(errors="replace"))
