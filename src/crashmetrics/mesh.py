"""Read the mesh of an LS-DYNA keyword file: nodes, elements and parts.

`read_mesh` reads ``*NODE``, ``*ELEMENT_SHELL``, ``*ELEMENT_SOLID``,
``*ELEMENT_BEAM`` (and their ``_TITLE`` or option forms), and the
titles of ``*PART`` cards, in fixed, long (``+`` or ``%``) and comma
formats. The result, a `Mesh`, gives the node coordinates of any parts,
for geometry checks such as bonnet clearance
(`crashmetrics.pedestrian.clearance`). `write_mesh` writes nodes and
shell elements in the keyword format.

Includes (``*INCLUDE``) are not followed: read each file and combine the
meshes with `Mesh.merge`, or give the file that holds the parts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

__all__ = ["Mesh", "read_mesh", "write_mesh"]

FloatArray = NDArray[np.float64]

_ELEMENT_NODES = {"shell": 8, "solid": 8, "beam": 3}


@dataclass(frozen=True)
class Mesh:
    """Nodes, elements and parts of a keyword file (model units)."""

    node_ids: NDArray[np.int64]
    coordinates: FloatArray
    """(node, 3)."""
    elements: dict[str, dict[int, tuple[int, tuple[int, ...]]]] = field(
        default_factory=dict)
    """Element type -> element ID -> (part ID, node IDs)."""
    part_names: dict[int, str] = field(default_factory=dict)
    source: str = ""

    @property
    def part_ids(self) -> tuple[int, ...]:
        """Parts that have elements, by ID."""
        return tuple(sorted({pid for elems in self.elements.values()
                             for pid, _ in elems.values()}))

    def part_name(self, part_id: int) -> str:
        return self.part_names.get(int(part_id)) or f"Part {part_id}"

    def part_nodes(self, part_id: int) -> NDArray[np.int64]:
        """IDs of the nodes of a part's elements, sorted."""
        ids = {n for elems in self.elements.values() for pid, nodes in elems.values()
               if pid == int(part_id) for n in nodes if n}
        if not ids:
            raise KeyError(f"No elements of part {part_id}; parts: "
                           f"{list(self.part_ids)[:30]}.")
        return np.array(sorted(ids), dtype=np.int64)

    def points(self, parts: int | Iterable[int]) -> FloatArray:
        """Coordinates (n, 3) of the nodes of one or several parts."""
        items = [parts] if isinstance(parts, (int, np.integer)) else list(parts)
        ids = np.unique(np.concatenate([self.part_nodes(p) for p in items]))
        return self.coordinates_of(ids)

    def coordinates_of(self, node_ids: Sequence[int] | NDArray[np.int64]) -> FloatArray:
        """Coordinates (n, 3) of the given nodes."""
        ids = np.asarray(node_ids, dtype=np.int64)
        order = np.argsort(self.node_ids)
        k = np.searchsorted(self.node_ids, ids, sorter=order)
        k = np.clip(k, 0, len(self.node_ids) - 1)
        found = self.node_ids[order[k]] == ids
        if not np.all(found):
            missing = ids[~found][:10].tolist()
            raise KeyError(f"Nodes not in the mesh: {missing}.")
        return np.asarray(self.coordinates[order[k]])

    def find_parts(self, pattern: str) -> list[int]:
        """Part IDs whose title matches a pattern (``*``, ``?``; case
        ignored)."""
        import fnmatch
        p = pattern.lower()
        return [i for i in self.part_ids
                if fnmatch.fnmatchcase(self.part_names.get(i, "").lower(), p)]

    def merge(self, other: Mesh) -> Mesh:
        """This mesh and another (for example an include file)."""
        ids = np.concatenate([self.node_ids, other.node_ids])
        coords = np.vstack([self.coordinates, other.coordinates])
        _, first = np.unique(ids, return_index=True)
        elements = {k: dict(v) for k, v in self.elements.items()}
        for kind, elems in other.elements.items():
            elements.setdefault(kind, {}).update(elems)
        return Mesh(ids[first], coords[first], elements,
                    {**self.part_names, **other.part_names},
                    ";".join(s for s in (self.source, other.source) if s))


def _fields(line: str, widths: Sequence[int]) -> list[str]:
    if "," in line:
        return [f.strip() for f in line.split(",")]
    out, pos = [], 0
    for w in widths:
        out.append(line[pos:pos + w].strip())
        pos += w
    return out


def _float(text: str) -> float:
    if not text:
        return 0.0
    t = text.replace("D", "E").replace("d", "e")
    m = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+))([-+]\d+)", t)
    return float(f"{m.group(1)}E{m.group(2)}" if m else t)


def read_mesh(path: str | Path, *, parts: Iterable[int] | None = None) -> Mesh:
    """Read nodes, elements and part titles of a keyword file.

    ``parts`` keeps only the elements of those parts (and all nodes).
    """
    target = Path(path)
    text = target.read_text(errors="replace")
    keep = None if parts is None else {int(p) for p in parts}
    node_ids: list[int] = []
    coords: list[tuple[float, float, float]] = []
    elements: dict[str, dict[int, tuple[int, tuple[int, ...]]]] = {}
    names: dict[int, str] = {}
    block: str | None = None
    long_format = False
    part_lines: list[str] = []

    def flush_part() -> None:
        """A *PART block: a title line, then the line starting with the
        part ID; later cards (contact, inertia ...) are ignored."""
        lines = part_lines[:2]
        part_lines.clear()
        if len(lines) < 2:
            return
        f = _fields(lines[1], (20 if long_format else 10,) * 8)
        try:
            pid = int(float(f[0]))
        except ValueError:
            return
        if lines[0].strip():
            names[pid] = lines[0].strip()

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("$"):
            continue
        if line.startswith("*"):
            if block == "part":
                flush_part()
            head = line.strip().upper()
            long_format = head.endswith(("+", "%"))
            head = head.rstrip("+%")
            if head.startswith("*NODE") and not head.startswith("*NODE_"):
                block = "node"
            elif head.startswith("*ELEMENT_SHELL"):
                block = "shell"
            elif head.startswith("*ELEMENT_SOLID"):
                block = "solid"
            elif head.startswith("*ELEMENT_BEAM"):
                block = "beam"
            elif head.startswith("*PART") and not head.startswith(("*PART_SENSOR",
                                                                     "*PART_MOVE")):
                block = "part"
            else:
                block = None
            continue
        if block is None or not line.strip():
            continue
        if block == "node":
            f = _fields(line, (20, 32, 32, 32) if long_format else (8, 16, 16, 16))
            try:
                node_ids.append(int(f[0]))
                coords.append((_float(f[1]), _float(f[2]), _float(f[3])))
            except (ValueError, IndexError):
                continue
        elif block in _ELEMENT_NODES:
            n = _ELEMENT_NODES[block]
            w: tuple[int, ...] = (20 if long_format else 8,) * (2 + n)
            f = _fields(line, w)
            try:
                eid, pid = int(f[0]), int(f[1])
                nodes = tuple(k for k in (int(x) for x in f[2:2 + n] if x)
                              if k)          # 0: no node (beam orientation)
            except (ValueError, IndexError):
                continue                       # thickness or option lines
            if keep is None or pid in keep:
                elements.setdefault(block, {})[eid] = (pid, nodes)
        elif block == "part":
            part_lines.append(line)
    if block == "part":
        flush_part()
    if not node_ids:
        raise ValueError(f"No *NODE in {target}.")
    ids = np.array(node_ids, dtype=np.int64)
    xyz = np.array(coords, dtype=float)
    _, last = np.unique(ids[::-1], return_index=True)
    pick = len(ids) - 1 - last                        # a node given twice: the last
    return Mesh(ids[pick], xyz[pick], elements, names, str(target))


def write_mesh(path: str | Path, node_ids: Sequence[int] | NDArray[np.int64],
               coordinates: FloatArray,
               shells: Mapping[int, tuple[int, Sequence[int]]],
               part_names: Mapping[int, str], *, title: str = "") -> Path:
    """Write ``*NODE``, ``*PART`` (title only, no section or material) and
    ``*ELEMENT_SHELL`` in fixed format."""
    xyz = np.asarray(coordinates, dtype=float)
    out = ["*KEYWORD"]
    if title:
        out += ["*TITLE", title[:80]]
    for pid, name in part_names.items():
        out += ["*PART", name[:70], f"{pid:10d}{0:10d}{0:10d}"]
    out.append("*NODE")
    out += [f"{int(i):8d}{x:16.6f}{y:16.6f}{z:16.6f}"
            for i, (x, y, z) in zip(node_ids, xyz)]
    out.append("*ELEMENT_SHELL")
    for eid, (pid, nodes) in shells.items():
        out.append(f"{eid:8d}{pid:8d}" + "".join(f"{n:8d}" for n in nodes))
    out.append("*END")
    target = Path(path)
    target.write_text("\n".join(out) + "\n")
    return target
