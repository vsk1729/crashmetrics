"""Read an LS-DYNA keyword deck: blocks, include files, parameters.

`read_deck` reads a main file and every file it includes, in the order
LS-DYNA reads them, into a `Deck`:

- **Blocks.** Each keyword and its lines, kept exactly as written
  (comments included), so a deck written back is identical except where
  it was edited. Fixed (10-character fields), long (``+`` after the
  keyword or ``*KEYWORD LONG=Y``, 20-character fields) and free
  (comma-separated) formats.
- **Includes.** ``*INCLUDE``, ``*INCLUDE_PATH``, ``*INCLUDE_PATH_RELATIVE``
  and ``*INCLUDE_TRANSFORM`` (its ID offsets, scale factors and
  transformation are recorded for the model tables), recursively; file
  names continued with `` +``. Missing files and circular includes are
  reported, not fatal.
- **Parameters.** ``*PARAMETER``, ``*PARAMETER_LOCAL`` and
  ``*PARAMETER_EXPRESSION`` (evaluated safely, never with ``eval``);
  fields given as ``&name`` or ``-&name`` read the parameter's value.
- **Version information.** The ``*KEYWORD`` line, the title, and the
  comment lines pre- and post-processors write (`DeckInfo`).

Typed values of any keyword come from `Deck.records`, which reads them
with the keyword's layout (`crashmetrics.deck.cards`). Keywords without
a layout are kept, listed and written back unchanged.
"""

from __future__ import annotations

import ast
import fnmatch
import math
import operator
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crashmetrics.deck._fields import split_line, to_float, to_int
from crashmetrics.deck.cards import Record, read_records, spec_for

__all__ = [
    "Block",
    "Deck",
    "DeckFile",
    "DeckInfo",
    "IncludeTransform",
    "Parameter",
    "parse_deck",
    "read_deck",
]

_CREATOR = re.compile(
    r"(created|generated|written|exported|version|ls-prepost|ansa|"
    r"hypermesh|primer|oasys|lspp|keyword file)",
    re.I,
)


# --- Blocks and files ---------------------------------------------------------


class Block:
    """One keyword with its lines (``lines[0]`` is the keyword line)."""

    def __init__(self, file: DeckFile, lines: list[str], start: int) -> None:
        self.file = file
        self.lines = lines
        self.start = start
        """Line number of the keyword line in its file (from 1)."""
        self.modified = False
        self.extra_lines = 0
        head = lines[0][1:].strip()
        tokens = head.split()
        name = tokens[0] if tokens else ""
        flag = ""
        if name and name[-1] in "+%":
            name, flag = name[:-1], name[-1]
        elif len(name) > 1 and name.endswith("-") and not name.endswith("--"):
            name, flag = name[:-1], "-"
        rest = tokens[1:]
        if rest and rest[0] in ("+", "-", "%"):
            flag = rest.pop(0)
        self.keyword = name.upper()
        self.flag = flag
        self.args = " ".join(rest)
        self.spec, self.family, self.subtype, self.options = spec_for(self.keyword)
        self._records: list[Record] | None = None

    def __repr__(self) -> str:
        return f"<Block *{self.keyword} {self.where()}>"

    @property
    def long(self) -> bool:
        """Long format (20-character fields)."""
        return self.flag == "+" or (self.file.deck.long_format and self.flag != "-")

    def where(self, line_no: int = 0) -> str:
        return f"{self.file.name}:{self.start + line_no}"

    def data_lines(self) -> list[tuple[int, str]]:
        """(line number in the block, text) of the data lines: no comments;
        blank lines count as cards of default values, except at the end."""
        out = [(i, t) for i, t in enumerate(self.lines) if i and not t.startswith("$")]
        while out and not out[-1][1].strip():
            out.pop()
        return out

    def set_line(self, line_no: int, text: str) -> None:
        if line_no <= 0 or line_no >= len(self.lines):
            raise IndexError("Only data lines can be changed.")
        self.lines[line_no] = text
        self.modified = True
        self.file.modified = True
        self._records = None
        self.file.deck.cache.clear()

    def records(self) -> list[Record]:
        """Typed records (empty for keywords without a layout)."""
        if self._records is None:
            if self.spec is None:
                self._records = []
            else:
                deck = self.file.deck
                errors: list[str] = []
                self._records = read_records(
                    self, self.spec, deck.resolver(self.file), errors
                )
                deck.notes.extend(e for e in errors if e not in deck.notes)
        return self._records

    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class IncludeTransform:
    """``*INCLUDE_TRANSFORM`` settings of an include file."""

    idnoff: int = 0
    ideoff: int = 0
    idpoff: int = 0
    idmoff: int = 0
    idsoff: int = 0
    idfoff: int = 0
    iddoff: int = 0
    idroff: int = 0
    prefix: str = ""
    suffix: str = ""
    fctmas: float = 1.0
    fcttim: float = 1.0
    fctlen: float = 1.0
    fcttem: str = ""
    tranid: int = 0

    def offset(self, namespace: str) -> int:
        """The offset that applies to IDs of a namespace."""
        return {
            "node": self.idnoff,
            "shell": self.ideoff,
            "solid": self.ideoff,
            "beam": self.ideoff,
            "tshell": self.ideoff,
            "discrete": self.ideoff,
            "seatbelt": self.ideoff,
            "element": self.ideoff,
            "mass": self.ideoff,
            "part": self.idpoff,
            "section": self.idpoff,
            "hourglass": self.idpoff,
            "material": self.idmoff,
            "eos": self.idmoff,
            "thmat": self.idmoff,
            "curve": self.idfoff,
            "contact": self.idroff,
            "rigidwall": self.idroff,
            "coord": self.iddoff,
            "vector": self.iddoff,
            "box": self.iddoff,
            "transform": self.iddoff,
        }.get(namespace, self.idsoff if namespace.startswith("set_") else 0)


class DeckFile:
    """One file of a deck."""

    def __init__(
        self,
        deck: Deck,
        path: Path,
        text: str,
        parent: DeckFile | None,
        include: Block | None = None,
    ) -> None:
        self.deck = deck
        self.path = path
        self.parent = parent
        self.include = include
        """The ``*INCLUDE`` block that read this file (None for the main file)."""
        self.transform: IncludeTransform | None = None
        self.modified = False
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.trailing_newline = text.endswith(("\n", "\r"))
        lines = text.splitlines()
        self.preamble: list[str] = []
        self.blocks: list[Block] = []
        current: list[str] | None = None
        start = 0
        for i, line in enumerate(lines):
            if line.startswith("*"):
                if current is not None:
                    self.blocks.append(Block(self, current, start))
                current, start = [line], i + 1
            elif current is None:
                self.preamble.append(line)
            else:
                current.append(line)
        if current is not None:
            self.blocks.append(Block(self, current, start))
        self.children: list[DeckFile] = []

    @property
    def name(self) -> str:
        try:
            return str(self.path.relative_to(self.deck.root))
        except ValueError:
            return str(self.path)

    def __repr__(self) -> str:
        return f"<DeckFile {self.name}: {len(self.blocks)} keywords>"

    def text(self) -> str:
        lines = list(self.preamble)
        for b in self.blocks:
            lines.extend(b.lines)
        out = self.newline.join(lines)
        return out + self.newline if self.trailing_newline else out

    def comments(self) -> list[str]:
        """Comment lines before the first keyword and right after
        ``*KEYWORD``."""
        out = [ln for ln in self.preamble if ln.startswith("$")]
        if self.blocks and self.blocks[0].keyword == "KEYWORD":
            out += [ln for ln in self.blocks[0].lines[1:] if ln.startswith("$")]
        return out

    def insert(self, block_text: str, before: Block | None = None) -> Block:
        """Add a keyword block (its text, keyword line first) before a
        block, or before ``*END`` (the end of the file without one)."""
        lines = block_text.rstrip("\n").splitlines()
        if not lines or not lines[0].startswith("*"):
            raise ValueError("A block starts with its keyword line.")
        if before is None:
            ends = [b for b in self.blocks if b.keyword == "END"]
            before = ends[0] if ends else None
        idx = self.blocks.index(before) if before is not None else len(self.blocks)
        start = (
            before.start
            if before is not None
            else (
                self.blocks[-1].start + len(self.blocks[-1].lines) if self.blocks else 1
            )
        )
        block = Block(self, lines, start)
        block.modified = True
        self.blocks.insert(idx, block)
        self.modified = True
        self.deck._order = None
        self.deck.cache.clear()
        return block


# --- Parameters ---------------------------------------------------------------


@dataclass
class Parameter:
    name: str
    kind: str
    """``R`` (real), ``I`` (integer) or ``C`` (text)."""
    value: Any
    file: DeckFile
    block: Block
    record: int = 0
    local: bool = False
    expression: str = ""
    slot: tuple[int, Any] | None = None
    """(line number in the block, Slot) of the value, for editing."""


_FUNCS: dict[str, Callable[..., float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "abs": abs,
    "min": min,
    "max": max,
    "int": lambda x: float(int(x)),
    "aint": lambda x: float(int(x)),
    "nint": lambda x: float(round(x)),
    "floor": math.floor,
    "ceil": math.ceil,
    "sign": lambda a, b: abs(a) if b >= 0 else -abs(a),
    "mod": math.fmod,
}
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def evaluate(expression: str, names: Callable[[str], float]) -> float:
    """A ``*PARAMETER_EXPRESSION`` value: numbers, parameter names,
    + - * / ** (or ^), and the usual functions (angles in radians)."""
    text = expression.strip().replace("^", "**")
    text = re.sub(r"(?<=[0-9.])[dD](?=[-+]?[0-9])", "e", text)
    tree = ast.parse(text, mode="eval")

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return float(_OPS[type(node.op)](ev(node.left), ev(node.right)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Name):
            if node.id.lower() == "pi":
                return math.pi
            return float(names(node.id.lower()))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.lower() in _FUNCS
            and not node.keywords
        ):
            return float(_FUNCS[node.func.id.lower()](*[ev(a) for a in node.args]))
        raise ValueError(
            f"not allowed in a parameter expression: {ast.dump(node)[:60]}"
        )

    return ev(tree)


# --- The deck -----------------------------------------------------------------


@dataclass(frozen=True)
class DeckInfo:
    """What a deck says about itself and its origin."""

    keyword_line: str
    title: str
    long_format: bool
    creators: tuple[str, ...]
    """Comment lines about the tool and version that wrote the files."""
    files: int
    keywords: int
    unknown: tuple[str, ...]
    """Keywords without a layout here (kept unchanged)."""

    @property
    def version(self) -> str:
        """The writing tool and version, from the first creator line that
        names one (empty if none)."""
        for line in self.creators:
            m = re.search(r"(LS-PrePost(?:\(R\))?\s*\S+(?:\s*\([^)]*\))?)", line, re.I)
            if m:
                return m.group(1).replace("(R)", "").strip()
            m = re.search(
                r"\b(ANSA|HyperMesh|PRIMER|Oasys PRIMER)\b[^0-9]*([0-9][\w.\-]*)",
                line,
                re.I,
            )
            if m:
                return f"{m.group(1)} {m.group(2)}"
        return ""

    def summary(self) -> str:
        lines = [
            f"{self.title or '(no title)'}: {self.keywords} keywords in {self.files} "
            f"file{'s' if self.files != 1 else ''}"
            + (", long format" if self.long_format else "")
        ]
        if self.version:
            lines.append(f"  written by {self.version}")
        if self.unknown:
            lines.append(
                f"  {len(self.unknown)} keyword types not interpreted (kept "
                f"unchanged): {', '.join(self.unknown[:8])}"
                + (" ..." if len(self.unknown) > 8 else "")
            )
        return "\n".join(lines)


class Deck:
    """A keyword deck: its files, blocks in reading order, parameters."""

    def __init__(self) -> None:
        self.root = Path(".")
        self.main: DeckFile
        self.files: list[DeckFile] = []
        self.parameters: dict[str, Parameter] = {}
        self.local_parameters: dict[tuple[int, str], Parameter] = {}
        self.notes: list[str] = []
        self.long_format = False
        self._order: list[Block] | None = None
        self.cache: dict[str, Any] = {}

    def __repr__(self) -> str:
        n = len(self.blocks)
        return f"<Deck {self.main.name}: {len(self.files)} files, {n} keywords>"

    @property
    def blocks(self) -> list[Block]:
        """All blocks in the order LS-DYNA reads them (an include file's
        blocks where its ``*INCLUDE`` is)."""
        if self._order is None:
            order: list[Block] = []

            def walk(f: DeckFile) -> None:
                for b in f.blocks:
                    order.append(b)
                    for c in f.children:
                        if c.include is b:
                            walk(c)

            walk(self.main)
            self._order = order
        return self._order

    def find(self, pattern: str) -> list[Block]:
        """Blocks whose keyword matches a pattern (``SECTION_SHELL*``,
        ``CONTACT_*``; case ignored)."""
        p = pattern.upper().lstrip("*")
        return [b for b in self.blocks if fnmatch.fnmatchcase(b.keyword, p)]

    def records(self, pattern: str) -> Iterator[Record]:
        """Typed records of every block matching a pattern."""
        for b in self.find(pattern):
            yield from b.records()

    def resolver(self, file: DeckFile) -> Callable[[str], Any]:
        def resolve(name: str) -> Any:
            f: DeckFile | None = file
            while f is not None:
                p = self.local_parameters.get((id(f), name))
                if p is not None:
                    return p.value
                f = f.parent
            if name in self.parameters:
                return self.parameters[name].value
            raise KeyError(f"parameter &{name} is not defined")

        return resolve

    @property
    def info(self) -> DeckInfo:
        title = ""
        for b in self.find("TITLE"):
            data = b.data_lines()
            if data:
                title = data[0][1].strip()
                break
        kw = (
            self.main.blocks[0].lines[0].strip()
            if (self.main.blocks and self.main.blocks[0].keyword == "KEYWORD")
            else ""
        )
        creators = tuple(
            c for f in self.files for c in f.comments() if _CREATOR.search(c)
        )
        unknown = sorted(
            {
                b.keyword
                for b in self.blocks
                if b.spec is None
                and b.family not in _SPECIAL_FAMILIES
                and b.keyword not in _SPECIAL
            }
        )
        return DeckInfo(
            kw,
            title,
            self.long_format,
            creators,
            len(self.files),
            len(self.blocks),
            tuple(unknown),
        )

    def text(self) -> str:
        """The main file's text."""
        return self.main.text()

    def refresh(self) -> None:
        """Read the parameters again and forget derived tables (after
        parameter edits)."""
        self.parameters.clear()
        self.local_parameters.clear()
        self.notes = [n for n in self.notes if "parameter" not in n]
        _collect_parameters(self)
        self.cache.clear()
        for b in self.blocks:
            b._records = None

    def write(self, folder: str | Path, *, only_modified: bool = False) -> list[Path]:
        """Write the deck into a folder: the main file and the include files
        inside its folder at the same relative paths. Include files outside
        it are not copied; their ``*INCLUDE`` lines are changed to their
        absolute paths. Returns the files written."""
        out_root = Path(folder)
        written = []
        for f in self.files:
            try:
                rel = f.path.relative_to(self.root)
            except ValueError:
                inc = f.include
                if inc is not None:
                    for i, line in enumerate(inc.lines):
                        if (
                            i
                            and not line.startswith("$")
                            and Path(line.strip().strip('"')).name == f.path.name
                        ):
                            inc.set_line(i, str(f.path))
                continue
            if only_modified and not f.modified and f is not self.main:
                continue
            target = out_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.text().encode("latin-1", errors="replace"))
            written.append(target)
        return written


_SPECIAL = {
    "KEYWORD",
    "TITLE",
    "END",
    "COMMENT",
    "NODE",
    "PARAMETER",
    "PARAMETER_LOCAL",
    "PARAMETER_EXPRESSION",
    "PARAMETER_EXPRESSION_LOCAL",
    "PARAMETER_DUPLICATION",
    "INCLUDE",
    "INCLUDE_PATH",
    "INCLUDE_PATH_RELATIVE",
    "INCLUDE_TRANSFORM",
    "DEFINE_CURVE",
    "DEFINE_CURVE_TITLE",
    "ELEMENT_MASS",
    "ELEMENT_MASS_PART",
    "ELEMENT_MASS_PART_SET",
}
_SPECIAL_FAMILIES = {"SET", "ELEMENT"}


# --- Reading ------------------------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("latin-1")


def _logical_lines(block: Block) -> list[tuple[int, str]]:
    """Data lines with file names continued by a trailing `` +`` joined."""
    out: list[tuple[int, str]] = []
    pending = ""
    first = -1
    for i, text in block.data_lines():
        t = text.rstrip()
        if t.endswith(" +"):
            if first < 0:
                first = i
            pending += t[:-2].strip()
            continue
        out.append(
            (first if first >= 0 else i, (pending + t.strip()) if pending else t)
        )
        pending, first = "", -1
    if pending:
        out.append((first, pending))
    return out


def _transform(block: Block, lines: list[tuple[int, str]]) -> IncludeTransform:
    tr = IncludeTransform()
    long = block.long
    w = 20 if long else 10
    cards = [text for _, text in lines[1:]]

    def fields(i: int, n: int) -> list[str]:
        if i >= len(cards):
            return [""] * n
        return [t for t, _ in split_line(cards[i], [w] * n)]

    a = fields(0, 7)
    tr.idnoff, tr.ideoff, tr.idpoff, tr.idmoff, tr.idsoff, tr.idfoff, tr.iddoff = (
        to_int(x) for x in a
    )
    b = fields(1, 4)
    tr.idroff = to_int(b[0])
    tr.prefix, tr.suffix = b[2], b[3]
    c = fields(2, 4)
    tr.fctmas = to_float(c[0]) or 1.0
    tr.fcttim = to_float(c[1]) or 1.0
    tr.fctlen = to_float(c[2]) or 1.0
    tr.fcttem = c[3]
    tr.tranid = to_int(fields(3, 1)[0])
    return tr


def _resolve_include(
    name: str, file: DeckFile, deck: Deck, paths: list[Path], relative: list[Path]
) -> Path | None:
    p = Path(name.strip().strip('"').strip("'"))
    if p.is_absolute():
        return p if p.is_file() else None
    candidates = [file.path.parent / p, deck.root / p]
    candidates += [d / p for d in relative]
    candidates += [(d if d.is_absolute() else deck.root / d) / p for d in paths]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def _load(deck: Deck, file: DeckFile, stack: list[Path], paths: list[Path]) -> None:
    relative: list[Path] = []
    for block in list(file.blocks):
        k = block.keyword
        if k == "KEYWORD" and file is deck.main:
            if re.search(r"LONG\s*=\s*Y", block.args, re.I):
                deck.long_format = True
        if k in ("INCLUDE_PATH", "INCLUDE_PATH_RELATIVE"):
            for _, line in _logical_lines(block):
                d = Path(line.strip())
                if k == "INCLUDE_PATH_RELATIVE" and not d.is_absolute():
                    relative.append(file.path.parent / d)
                else:
                    paths.append(d)
            continue
        if not k.startswith("INCLUDE") or k in (
            "INCLUDE_PATH",
            "INCLUDE_PATH_RELATIVE",
        ):
            continue
        lines = _logical_lines(block)
        if not lines:
            continue
        if k == "INCLUDE":
            names = [t.strip() for _, t in lines if t.strip()]
            tr = None
        elif k == "INCLUDE_TRANSFORM":
            names = [lines[0][1].strip()]
            tr = _transform(block, lines)
        else:
            deck.notes.append(
                f"{block.where()}: *{k} is not followed (only *INCLUDE, "
                "*INCLUDE_PATH and *INCLUDE_TRANSFORM are)."
            )
            continue
        for name in names:
            target = _resolve_include(name, file, deck, paths, relative)
            if target is None:
                deck.notes.append(f"{block.where()}: include file {name!r} not found.")
                continue
            if target in stack:
                deck.notes.append(
                    f"{block.where()}: {name!r} includes itself (circular "
                    "include); not read again."
                )
                continue
            child = DeckFile(deck, target, _read_text(target), file, block)
            child.transform = tr
            file.children.append(child)
            deck.files.append(child)
            _load(deck, child, stack + [target], paths)


def _collect_parameters(deck: Deck) -> None:
    pending: list[tuple[Block, Parameter]] = []
    duplication = 1
    for block in deck.blocks:
        k = block.keyword
        if k == "PARAMETER_DUPLICATION":
            data = block.data_lines()
            if data:
                duplication = to_int(split_line(data[0][1], [10])[0][0] or "1") or 1
            continue
        if not k.startswith("PARAMETER") or k == "PARAMETER_TYPE":
            continue
        local = k.endswith("_LOCAL")
        expr = "EXPRESSION" in k
        w = 20 if block.long else 10
        for line_no, text in block.data_lines():
            if expr:
                parts = split_line(text, [w, 80 if not block.long else 140])
                (name_text, _), (ex, slot) = parts[0], parts[1]
                pairs = [(name_text, ex, slot)]
            else:
                parts = split_line(text, [w] * 8)
                pairs = [
                    (parts[i][0], parts[i + 1][0], parts[i + 1][1])
                    for i in range(0, 8, 2)
                    if parts[i][0]
                ]
            for name_text, value_text, slot in pairs:
                kind = (
                    name_text[0].upper()
                    if name_text and name_text[0].upper() in "RIC"
                    else "R"
                )
                name = (
                    name_text[1:].strip().lower()
                    if name_text[0].upper() in "RIC"
                    else name_text.strip().lower()
                )
                if not name:
                    continue
                p = Parameter(
                    name,
                    kind,
                    None,
                    block.file,
                    block,
                    local=local,
                    expression=value_text if expr else "",
                    slot=(line_no, slot),
                )
                if not expr:
                    try:
                        p.value = (
                            value_text.strip()
                            if kind == "C"
                            else to_int(value_text)
                            if kind == "I"
                            else to_float(value_text)
                        )
                    except ValueError:
                        deck.notes.append(
                            f"{block.where(line_no)}: parameter {name}: "
                            f"cannot read {value_text!r}."
                        )
                        continue
                    _define(deck, p, duplication)
                else:
                    pending.append((block, p))
    for _ in range(len(pending) + 1):  # expressions, in dependency order
        left = []
        for block, p in pending:
            try:
                v = evaluate(p.expression, deck.resolver(p.file))
            except KeyError:
                left.append((block, p))
                continue
            except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
                deck.notes.append(
                    f"{block.where()}: parameter {p.name}: expression "
                    f"{p.expression!r}: {exc}"
                )
                continue
            p.value = int(round(v)) if p.kind == "I" else v
            _define(deck, p, duplication)
        if len(left) == len(pending):
            for block, p in left:
                deck.notes.append(
                    f"{block.where()}: parameter {p.name}: expression "
                    f"{p.expression!r} uses an undefined parameter."
                )
            break
        pending = left


def _define(deck: Deck, p: Parameter, duplication: int) -> None:
    table = deck.local_parameters if p.local else deck.parameters
    key: Any = (id(p.file), p.name) if p.local else p.name
    old = table.get(key)
    if old is not None and old.value != p.value:
        keep_old = duplication == 2
        deck.notes.append(
            f"{p.block.where()}: parameter {p.name} defined again ({old.value} at "
            f"{old.block.where()}, now {p.value}); "
            + (
                "the first value is kept (*PARAMETER_DUPLICATION 2)."
                if keep_old
                else "the new value is used."
            )
        )
        if keep_old:
            return
    table[key] = p


def parse_deck(text: str, name: str = "deck.k") -> Deck:
    """A deck from text (includes are looked for next to ``name``)."""
    deck = Deck()
    path = Path(name).resolve()
    deck.root = path.parent
    deck.main = DeckFile(deck, path, text, None)
    deck.files = [deck.main]
    _load(deck, deck.main, [path], [])
    deck._order = None
    _collect_parameters(deck)
    return deck


def read_deck(path: str | Path) -> Deck:
    """Read a keyword deck and every file it includes.

    Problems that do not stop reading (missing include files, undefined
    parameters, unreadable fields) are listed in `Deck.notes`.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"No keyword file {p}.")
    return parse_deck(_read_text(p), str(p))
