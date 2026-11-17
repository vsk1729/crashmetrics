"""Nodes, elements, sets, curves and mass elements of a deck.

These keywords hold most of a model's lines, so they have their own fast
readers instead of the generic card reader. ID offsets, the length
factor and the transformation of ``*INCLUDE_TRANSFORM`` are applied.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from crashmetrics.deck._fields import is_param, split_line, to_float, to_int
from crashmetrics.deck.reader import Block, Deck, DeckFile

__all__ = [
    "Curve",
    "Elements",
    "MassElement",
    "Nodes",
    "SetInfo",
    "curves",
    "elements",
    "mass_elements",
    "nodes",
    "record_id",
    "sets",
]

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

ELEMENT_KINDS = ("shell", "solid", "beam", "tshell", "discrete", "seatbelt")


def _value(text: str, block: Block, kind: str) -> float:
    if is_param(text):
        v = float(
            block.file.deck.resolver(block.file)(text.strip().lstrip("-&").lower())
        )
        return -v if text.strip().startswith("-") else v
    return to_int(text) if kind == "i" else to_float(text)


def _fields(line: str, widths: tuple[int, ...]) -> list[str]:
    if "," in line:
        return [t.strip() for t in line.split(",")]
    out, pos = [], 0
    for w in widths:
        out.append(line[pos : pos + w].strip())
        pos += w
    return out


def _widths(
    block: Block, std: tuple[int, ...], pct: tuple[int, ...] | None = None
) -> tuple[int, ...]:
    if block.long:
        return tuple(max(w, 20) for w in std)
    if block.flag == "%" and pct is not None:
        return pct
    return std


# --- Transformations ----------------------------------------------------------


def _matrix(deck: Deck, tranid: int) -> NDArray[np.float64] | None:
    """4x4 matrix of a ``*DEFINE_TRANSFORMATION`` (TRANSL, SCALE, ROTATE
    about an axis through a point by an angle in degrees), None if it
    is not defined or uses another option."""
    for rec in deck.records("DEFINE_TRANSFORMATION*"):
        if rec.get("tranid") != tranid:
            continue
        m = np.eye(4)
        for row in rec.rows:
            op = str(row.get("option", "")).upper()
            a = [row.get(f"a{i}", 0.0) for i in range(1, 8)]
            t = np.eye(4)
            if op == "TRANSL":
                t[:3, 3] = a[:3]
            elif op == "SCALE":
                t[0, 0], t[1, 1], t[2, 2] = (x if x else 1.0 for x in a[:3])
            elif op == "ROTATE" and a[6] != 0:
                axis = np.array(a[:3], dtype=float)
                n = float(np.linalg.norm(axis))
                if n == 0:
                    return None
                k = axis / n
                th = math.radians(a[6])
                kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
                r = np.eye(3) + math.sin(th) * kx + (1 - math.cos(th)) * kx @ kx
                p = np.array(a[3:6], dtype=float)
                t[:3, :3] = r
                t[:3, 3] = p - r @ p
            else:
                deck.notes.append(
                    f"*DEFINE_TRANSFORMATION {tranid}: option {op or '?'} "
                    "is not applied to node coordinates."
                )
                return None
            m = t @ m
        return m
    return None


def record_id(rec: Any, name: str, namespace: str) -> int:
    """An ID field of a record with the ``*INCLUDE_TRANSFORM`` offset of
    its file (0 stays 0: no reference)."""
    v = int(rec.get(name, 0) or 0)
    return v + _file_offset(rec.block.file, namespace) if v > 0 else v


def _file_offset(file: DeckFile, namespace: str) -> int:
    off = 0
    f: DeckFile | None = file
    while f is not None:
        if f.transform is not None:
            off += f.transform.offset(namespace)
        f = f.parent
    return off


# --- Nodes --------------------------------------------------------------------


@dataclass(frozen=True)
class Nodes:
    ids: IntArray
    xyz: FloatArray
    files: tuple[str, ...]
    """Name of the file of each node."""

    def index(self, ids: Iterable[int] | IntArray) -> IntArray:
        """Row of each node ID (-1 where missing)."""
        q = np.asarray(
            list(ids) if not isinstance(ids, np.ndarray) else ids, dtype=np.int64
        )
        if len(self.ids) == 0:
            return np.full(q.shape, -1, dtype=np.int64)
        order = np.argsort(self.ids, kind="stable")
        pos = np.clip(np.searchsorted(self.ids, q, sorter=order), 0, len(self.ids) - 1)
        rows = order[pos]
        return np.where(self.ids[rows] == q, rows, -1)


def nodes(deck: Deck) -> Nodes:
    """All ``*NODE`` rows (later duplicates are kept; the checks report
    them)."""
    if "nodes" in deck.cache:
        return deck.cache["nodes"]  # type: ignore[no-any-return]
    ids: list[int] = []
    xyz: list[tuple[float, float, float]] = []
    files: list[str] = []
    for b in deck.blocks:
        if b.keyword != "NODE":
            continue
        w = _widths(b, (8, 16, 16, 16, 8, 8), (10, 16, 16, 16, 10, 10))
        off = _file_offset(b.file, "node")
        tr = _chain_transform(deck, b.file)
        start = len(ids)
        for line_no, line in b.data_lines():
            if not line.strip():
                continue
            f = _fields(line, w)
            try:
                nid = int(_value(f[0], b, "i"))
                p = (_value(f[1], b, "f"), _value(f[2], b, "f"), _value(f[3], b, "f"))
            except (ValueError, IndexError, KeyError):
                parts = line.split()
                try:
                    nid, p = (
                        int(parts[0]),
                        (float(parts[1]), float(parts[2]), float(parts[3])),
                    )
                except (ValueError, IndexError):
                    deck.notes.append(f"{b.where(line_no)}: unreadable node line.")
                    continue
            ids.append(nid + off)
            xyz.append(p)
            files.append(b.file.name)
        if tr is not None and len(ids) > start:
            pts = np.array(xyz[start:], dtype=float)
            pts = pts @ tr[:3, :3].T + tr[:3, 3]
            xyz[start:] = [tuple(p) for p in pts]
    out = Nodes(
        np.array(ids, dtype=np.int64),
        np.array(xyz, dtype=float).reshape(-1, 3),
        tuple(files),
    )
    deck.cache["nodes"] = out
    return out


def _chain_transform(deck: Deck, file: DeckFile) -> NDArray[np.float64] | None:
    m = np.eye(4)
    used = False
    f: DeckFile | None = file
    while f is not None:
        tr = f.transform
        if tr is not None:
            s = np.eye(4)
            if tr.fctlen != 1.0:
                s[:3, :3] *= tr.fctlen
                used = True
            m = s @ m
            if tr.tranid:
                t = _matrix(deck, tr.tranid)
                if t is not None:
                    m = t @ m
                    used = True
        f = f.parent
    return m if used else None


# --- Elements -----------------------------------------------------------------


@dataclass
class Elements:
    """Elements of one kind: IDs, parts, node IDs (n, nodes per element,
    0 where unused), and the shell thickness given per element (NaN where
    not given)."""

    kind: str
    ids: IntArray
    parts: IntArray
    nodes: IntArray
    thickness: FloatArray
    files: tuple[str, ...]


_ELEMENT_LAYOUT = {
    # kind: (nodes, standard widths, extra-card options)
    "shell": (8, (8,) * 10),
    "solid": (8, (8,) * 10),
    "tshell": (8, (8,) * 10),
    "beam": (3, (8,) * 10),
    "discrete": (2, (8, 8, 8, 8, 8, 16, 8, 16)),
    "seatbelt": (2, (8, 8, 8, 8, 8, 16, 8, 8)),
}
_EXTRA = {
    "shell": {"THICKNESS": 1, "BETA": 1, "MCID": 1, "OFFSET": 1, "DOF": 1},
    "solid": {"ORTHO": 2, "DOF": 1},
    "tshell": {"BETA": 1},
    "beam": {
        "THICKNESS": 1,
        "SECTION": 1,
        "SCALAR": 1,
        "SCALR": 1,
        "OFFSET": 1,
        "ORIENTATION": 1,
        "PID": 1,
        "WARPAGE": 1,
        "ELBOW": 1,
    },
    "discrete": {"LCO": 1},
    "seatbelt": {},
}
_SKIP_OPTIONS = {"TITLE", "LIST", "GENERATE"}


def elements(deck: Deck) -> dict[str, Elements]:
    """Elements by kind (shell, solid, beam, tshell, discrete, seatbelt)."""
    if "elements" in deck.cache:
        return deck.cache["elements"]  # type: ignore[no-any-return]
    acc: dict[str, dict[str, list]] = {
        k: {"ids": [], "parts": [], "nodes": [], "t": [], "files": []}
        for k in _ELEMENT_LAYOUT
    }
    for b in deck.blocks:
        if b.family != "ELEMENT":
            continue
        kind = b.subtype.split("_")[0].lower()
        if kind not in _ELEMENT_LAYOUT:
            continue
        opts = [o for o in b.subtype.split("_")[1:] if o not in _SKIP_OPTIONS]
        extra_table = _EXTRA[kind]
        unknown = [o for o in opts if o not in extra_table]
        if unknown:
            deck.notes.append(
                f"{b.where()}: *{b.keyword}: option(s) {', '.join(unknown)} "
                "not known; their extra cards may be misread."
            )
        extra = sum(extra_table.get(o, 0) for o in opts)
        n_nodes, std = _ELEMENT_LAYOUT[kind]
        w = _widths(b, std, tuple(10 if x == 8 else x for x in std))
        eoff, poff = _file_offset(b.file, kind), _file_offset(b.file, "part")
        noff = _file_offset(b.file, "node")
        a = acc[kind]
        data = [(i, t) for i, t in b.data_lines() if t.strip()]
        two_line = False
        if kind == "solid" and data:
            first = _fields(data[0][1], w)
            two_line = sum(1 for x in first[2:] if x) == 0 and len(data) > 1
        i = 0
        while i < len(data):
            line_no, line = data[i]
            f = _fields(line, w)
            try:
                eid, pid = int(_value(f[0], b, "i")), int(_value(f[1], b, "i"))
                if two_line:
                    i += 1
                    nf = _fields(data[i][1], w) if i < len(data) else []
                    ns = [int(_value(x, b, "i")) for x in nf[:n_nodes] if x]
                else:
                    ns = [int(_value(x, b, "i")) for x in f[2 : 2 + n_nodes] if x]
            except (ValueError, IndexError, KeyError):
                deck.notes.append(f"{b.where(line_no)}: unreadable *{b.keyword} line.")
                i += 1 + extra
                continue
            t = math.nan
            if (
                kind == "shell"
                and {"THICKNESS", "BETA", "MCID"} & set(opts)
                and i + 1 < len(data)
            ):
                tf = _fields(data[i + 1][1], _widths(b, (16, 16, 16, 16, 16)))
                vals = [to_float(x) for x in tf[:4] if x and not is_param(x)]
                vals = [v for v in vals if v > 0]
                if vals:
                    t = float(np.mean(vals))
            ns = [n + noff if n else 0 for n in ns] + [0] * (8 - len(ns))
            a["ids"].append(eid + eoff)
            a["parts"].append(pid + poff)
            a["nodes"].append(ns[:8])
            a["t"].append(t)
            a["files"].append(b.file.name)
            i += 1 + extra
    out = {}
    for kind, a in acc.items():
        if not a["ids"]:
            continue
        out[kind] = Elements(
            kind,
            np.array(a["ids"], dtype=np.int64),
            np.array(a["parts"], dtype=np.int64),
            np.array(a["nodes"], dtype=np.int64).reshape(-1, 8),
            np.array(a["t"], dtype=float),
            tuple(a["files"]),
        )
    deck.cache["elements"] = out
    return out


# --- Mass elements ------------------------------------------------------------


@dataclass(frozen=True)
class MassElement:
    """A lumped mass (``*ELEMENT_MASS``), mass added to a part or part set
    (``*ELEMENT_MASS_PART``), or an inertia element."""

    kind: str
    """``"node"``, ``"part"``, ``"part_set"`` or ``"inertia"``."""
    id: int
    target: int
    """Node, part or part set ID."""
    mass: float
    final_mass: float = 0.0
    part: int = 0
    where: str = ""


def mass_elements(deck: Deck) -> list[MassElement]:
    out = []
    for b in deck.blocks:
        k = b.keyword
        if k.startswith("ELEMENT_MASS_PART"):
            is_set = "SET" in k
            for line_no, line in b.data_lines():
                f = _fields(line, _widths(b, (8, 16, 16, 8)))
                try:
                    out.append(
                        MassElement(
                            "part_set" if is_set else "part",
                            0,
                            int(_value(f[0], b, "i"))
                            + _file_offset(b.file, "set_part" if is_set else "part"),
                            _value(f[1], b, "f") if len(f) > 1 else 0.0,
                            _value(f[2], b, "f") if len(f) > 2 else 0.0,
                            where=b.where(line_no),
                        )
                    )
                except (ValueError, KeyError):
                    deck.notes.append(f"{b.where(line_no)}: unreadable *{k} line.")
        elif k in ("ELEMENT_MASS", "ELEMENT_MASS_NODE_SET"):
            for line_no, line in b.data_lines():
                f = _fields(line, _widths(b, (8, 8, 16, 8)))
                try:
                    out.append(
                        MassElement(
                            "node" if k == "ELEMENT_MASS" else "node_set",
                            int(_value(f[0], b, "i")) + _file_offset(b.file, "mass"),
                            int(_value(f[1], b, "i"))
                            + _file_offset(
                                b.file, "node" if k == "ELEMENT_MASS" else "set_node"
                            ),
                            _value(f[2], b, "f"),
                            part=int(_value(f[3], b, "i"))
                            if len(f) > 3 and f[3]
                            else 0,
                            where=b.where(line_no),
                        )
                    )
                except (ValueError, KeyError, IndexError):
                    deck.notes.append(f"{b.where(line_no)}: unreadable *{k} line.")
        elif k.startswith("ELEMENT_INERTIA"):
            data = b.data_lines()
            step = 3 if "OFFSET" in k else 2
            for j in range(0, len(data) - 1, step):
                f1 = _fields(data[j][1], _widths(b, (8, 8, 8)))
                f2 = _fields(data[j + 1][1], _widths(b, (10,) * 7))
                try:
                    out.append(
                        MassElement(
                            "inertia",
                            int(_value(f1[0], b, "i")),
                            int(_value(f1[1], b, "i")),
                            _value(f2[6], b, "f"),
                            where=b.where(data[j][0]),
                        )
                    )
                except (ValueError, KeyError, IndexError):
                    deck.notes.append(f"{b.where(data[j][0])}: unreadable *{k} lines.")
    return out


# --- Sets ---------------------------------------------------------------------


@dataclass
class SetInfo:
    kind: str
    """``part``, ``node``, ``shell``, ``solid``, ``beam``, ``tshell``,
    ``discrete`` or ``segment``."""
    id: int
    title: str = ""
    members: list[int] = field(default_factory=list)
    """Member IDs (for segments, the node IDs of all segments)."""
    segments: list[tuple[int, ...]] = field(default_factory=list)
    add: list[int] = field(default_factory=list)
    """Set IDs of an ``_ADD`` set."""
    resolved: bool = True
    """False for set types not read here (``_GENERAL``, ``_ADVANCED`` ...)."""
    where: str = ""


_UNRESOLVED = {"GENERAL", "ADVANCED", "INTERSECT", "COLLECT", "EXCLUDE", "ADD_ADVANCED"}


def sets(deck: Deck) -> dict[tuple[str, int], SetInfo]:
    """All sets by (kind, ID); ``_ADD`` sets are expanded."""
    if "sets" in deck.cache:
        return deck.cache["sets"]  # type: ignore[no-any-return]
    out: dict[tuple[str, int], SetInfo] = {}
    for b in deck.blocks:
        if b.family != "SET":
            continue
        kind = b.subtype.lower()
        opts = set(b.options)
        data = b.data_lines()
        if not data:
            continue
        pos = 0
        title = ""
        if "TITLE" in opts:
            title = data[0][1].strip()
            pos = 1
        if pos >= len(data):
            continue
        w = 20 if b.long else 10
        head = _fields(data[pos][1], (w,) * 6)
        try:
            sid = int(_value(head[0], b, "i")) + _file_offset(b.file, "set_" + kind)
        except (ValueError, KeyError):
            deck.notes.append(f"{b.where(data[pos][0])}: unreadable set ID.")
            continue
        s = SetInfo(kind, sid, title, where=b.where())
        pos += 1
        member_off = _file_offset(b.file, kind if kind != "segment" else "node")
        if _UNRESOLVED & opts:
            s.resolved = False
        elif kind == "segment":
            for _, line in data[pos:]:
                f = _fields(line, (w,) * 4)
                seg = tuple(
                    int(_value(x, b, "i")) + member_off for x in f[:4] if x and x != "0"
                )
                if seg:
                    s.segments.append(seg)
                    s.members.extend(seg)
        else:
            values: list[int] = []
            for _, line in data[pos:]:
                for x in _fields(line, (w,) * 8):
                    if x:
                        try:
                            values.append(int(_value(x, b, "i")))
                        except (ValueError, KeyError):
                            deck.notes.append(
                                f"{b.where()}: unreadable set member {x!r}."
                            )
            if "GENERATE" in opts:
                if "INCREMENT" in opts:
                    for j in range(0, len(values) - 2, 3):
                        a, e, inc = values[j : j + 3]
                        s.members.extend(range(a, e + 1, inc or 1))
                else:
                    for j in range(0, len(values) - 1, 2):
                        a, e = values[j : j + 2]
                        if a or e:
                            s.members.extend(range(a, e + 1))
                s.members = [m + member_off for m in s.members]
            elif "ADD" in opts:
                s.add = [
                    v + _file_offset(b.file, "set_" + kind) for v in values if v > 0
                ]
            else:
                s.members = [v + member_off for v in values if v > 0]
        key = (kind, sid)
        if key in out:
            out[key].where += f"; {s.where}"  # duplicate: reported by checks
            deck.cache.setdefault("set_duplicates", []).append((kind, sid, s.where))
            continue
        out[key] = s
    for s in out.values():  # expand _ADD
        if s.add:
            seen, stack, members = set(), list(s.add), []
            while stack:
                sid = stack.pop()
                if sid in seen:
                    continue
                seen.add(sid)
                child = out.get((s.kind, sid))
                if child is None:
                    s.resolved = False
                    continue
                members.extend(child.members)
                stack.extend(child.add)
                s.resolved = s.resolved and child.resolved
            s.members = members
    deck.cache["sets"] = out
    return out


# --- Curves -------------------------------------------------------------------


@dataclass(frozen=True)
class Curve:
    """A ``*DEFINE_CURVE`` with SFA, SFO, OFFA and OFFO applied, or the ID
    of another curve-like definition (table, function) without points."""

    id: int
    title: str
    x: FloatArray
    y: FloatArray
    keyword: str
    where: str


def curves(deck: Deck) -> dict[int, Curve]:
    if "curves" in deck.cache:
        return deck.cache["curves"]  # type: ignore[no-any-return]
    out: dict[int, Curve] = {}
    dups = deck.cache.setdefault("curve_duplicates", [])
    for b in deck.blocks:
        k = b.keyword
        if not (
            k.startswith("DEFINE_CURVE")
            or k.startswith("DEFINE_TABLE")
            or k.startswith("DEFINE_FUNCTION")
        ):
            continue
        data = b.data_lines()
        pos = 1 if "TITLE" in k.split("_") and data else 0
        title = data[0][1].strip() if pos else ""
        if pos >= len(data):
            continue
        w = 20 if b.long else 10
        head = [t for t, _ in split_line(data[pos][1], [w] * 8)]
        try:
            cid = int(_value(head[0], b, "i")) + _file_offset(b.file, "curve")
        except (ValueError, KeyError):
            deck.notes.append(f"{b.where(data[pos][0])}: unreadable curve ID.")
            continue
        x = y = np.zeros(0)
        if k in ("DEFINE_CURVE", "DEFINE_CURVE_TITLE"):
            sfa, sfo, offa, offo = (
                _value(head[i], b, "f") if len(head) > i else 0.0 for i in (2, 3, 4, 5)
            )
            sfa, sfo = sfa or 1.0, sfo or 1.0
            pts = []
            for line_no, line in data[pos + 1 :]:
                f = [t for t, _ in split_line(line, [20, 20])]
                try:
                    pts.append((_value(f[0], b, "f"), _value(f[1], b, "f")))
                except (ValueError, KeyError):
                    deck.notes.append(f"{b.where(line_no)}: unreadable curve point.")
            arr = np.array(pts, dtype=float).reshape(-1, 2)
            x, y = sfa * arr[:, 0] + offa, sfo * arr[:, 1] + offo
        c = Curve(cid, title, x, y, k, b.where())
        if cid in out:
            dups.append((cid, b.where()))
            continue
        out[cid] = c
    deck.cache["curves"] = out
    return out
