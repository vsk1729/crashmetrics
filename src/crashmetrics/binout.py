"""Reader for LS-DYNA binout files (the binary form of the ASCII outputs).

A binout holds the same time histories as the ASCII files (glstat,
matsum, nodout, rcforc, secforc, sleout, spcforc, swforc, abstat ...),
in one or more files (``binout``, ``binout0000``, ``binout0001`` ...).
`read_binout` reads them all and gives each output as the same objects
the ASCII readers return, so every analysis works on either:

```python
from crashmetrics.binout import read_binout

bo = read_binout("runs/loop12")           # a run folder, a file or a list
print(bo.summary())                        # outputs, states, time range
nodout = bo.output("nodout")               # AsciiOutput, as read_nodout gives
energies = bo.glstat()                     # GlobalEnergies, as read_glstat
parts = bo.matsum()                        # PartEnergies, as read_matsum
bo.read("nodout", "x_acceleration")        # one variable, (states, nodes)
```

The file layout
---------------
This reader was written from the file layout itself, worked out from
public binout files (byte dumps checked against the ASCII files the same
runs wrote). No code or documentation of other binout readers was used.

- **Header** (8 bytes): header length, then the sizes in bytes of the
  record length field (8), of file offsets (8), of the command field (1)
  and of the type field (1), then a byte-order flag (1: little-endian).
- **Records**: ``[length][command][payload]``, the length including its
  own field. Commands: 2 changes the directory (absolute, or relative
  to the current one); 3 stores a variable, ``[type][name length (1
  byte)][name][values]``; 7 gives the offset of the first symbol table;
  5 is a symbol table (a directory and, per variable, its name, type,
  offset and value count, ending with the offset of the next table, 0
  for the last).
- **Types**: 1 text, 3 32-bit and 4 64-bit integers, 9 32-bit and 10
  64-bit floats (single and double precision runs).
- **Directories**: one per output, ``/nodout``, or per output and kind,
  ``/elout/shell``, ``/ncforc/slave_1``, ``/jntforc/type0``. Each has a
  ``metadata`` folder (title, version, IDs, legend) and one folder per
  output state (``d000001``, ``d000002`` ... or ``d1``, ``d2`` ...),
  some with a ``misc`` sub-folder.

The records are read in file order, so a file whose run was stopped
while writing is read up to its last complete record (the symbol tables
are not needed; `Binout.verify` compares them with the records). When a
run was restarted and an output goes back in time, the states from the
restart time on are replaced by the restarted ones, as for the ASCII
files.
"""

from __future__ import annotations

import argparse
import mmap
import posixpath
import re
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from crashmetrics.energy_check import GlobalEnergies, PartEnergies
from crashmetrics.lsdyna_ascii import AsciiOutput

__all__ = [
    "Binout",
    "BinoutVariable",
    "find_binout",
    "main",
    "read_binout",
    "write_binout",
]

_TYPES: dict[int, tuple[str, int]] = {
    1: ("S", 1),
    3: ("i4", 4),
    4: ("i8", 8),
    9: ("f4", 4),
    10: ("f8", 8),
}
"""Type code -> (NumPy kind, bytes per value). Only the codes found in
real files are listed; others are read as raw bytes."""

_STATE = re.compile(r"^d(\d+)$")
_CMD_CD, _CMD_DATA, _CMD_SYMTAB, _CMD_NEXT, _CMD_FIRST = 2, 3, 5, 6, 7


@dataclass(frozen=True)
class BinoutVariable:
    """One stored variable: where its values are."""

    name: str
    type: int
    """Type code (1 text, 3/4 integers, 9/10 floats)."""
    file: int
    """Index of the file in `Binout.files`."""
    offset: int
    """Offset of the first value in the file."""
    nbytes: int
    record: int
    """Offset of the variable's record (as the symbol table gives it)."""

    @property
    def count(self) -> int:
        """Number of values (characters for text)."""
        size = _TYPES.get(self.type, ("u1", 1))[1]
        return self.nbytes // size


class _File:
    def __init__(self, path: Path, notes: list[str]) -> None:
        self.path = path
        handle = open(path, "rb")
        try:
            self.data: Any = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:  # empty file
            self.data = b""
        handle.close()
        self.dirs: dict[str, dict[str, tuple[int, int, int, int]]] = {}
        self.order: list[str] = []
        b = self.data
        if len(b) < 8:
            raise ValueError(f"{path.name}: not a binout file (too short).")
        head = list(b[:8])
        self.header = head
        hlen, lsize, osize, csize, tsize, order = head[:6]
        if lsize not in (4, 8) or osize not in (4, 8) or csize != 1 or tsize != 1:
            raise ValueError(
                f"{path.name}: not a binout file, or a layout not read here "
                f"(header {head})."
            )
        if order != 1:
            raise ValueError(
                f"{path.name}: byte order flag {order}; only little-endian "
                "files (flag 1) are read."
            )
        self.lsize, self.osize = lsize, osize
        self.lfmt = "<Q" if lsize == 8 else "<I"
        self.ofmt = "<Q" if osize == 8 else "<I"
        pos, cwd, n = hlen, "/", len(b)
        while pos < n:
            if pos + lsize + 1 > n:
                notes.append(
                    f"{path.name}: incomplete record at byte {pos}; read up to it."
                )
                break
            length = struct.unpack_from(self.lfmt, b, pos)[0]
            if length < lsize + 1 or pos + length > n:
                notes.append(
                    f"{path.name}: incomplete record at byte {pos} (the run may "
                    "have stopped while writing); read up to it."
                )
                break
            cmd = b[pos + lsize]
            body = pos + lsize + 1
            if cmd == _CMD_CD:
                text = bytes(b[body : pos + length]).decode("latin-1")
                cwd = posixpath.normpath(posixpath.join(cwd, text))
                if cwd.startswith("//"):
                    cwd = cwd[1:]
            elif cmd == _CMD_DATA:
                typ, nlen = b[body], b[body + 1]
                name = bytes(b[body + 2 : body + 2 + nlen]).decode("latin-1")
                start = body + 2 + nlen
                if cwd not in self.dirs:
                    self.dirs[cwd] = {}
                    self.order.append(cwd)
                self.dirs[cwd][name] = (typ, start, pos + length - start, pos)
            pos += length
        self.end = pos

    def close(self) -> None:
        if isinstance(self.data, mmap.mmap):
            self.data.close()


def _decode(file: _File, typ: int, start: int, nbytes: int) -> Any:
    raw = file.data[start : start + nbytes]
    if typ == 1:
        return bytes(raw).decode("latin-1")
    kind, _ = _TYPES.get(typ, ("u1", 1))
    return np.frombuffer(bytes(raw), dtype="<" + kind)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass
class _Branch:
    name: str
    meta: dict[int, str] = field(default_factory=dict)
    """File index -> metadata folder."""
    states: list[tuple[int, str, int]] = field(default_factory=list)
    """(file index, state folder, state number) in file order."""


class Binout:
    """The outputs of one or more binout files of a run.

    Outputs are named by their folder without the leading slash:
    ``"glstat"``, ``"nodout"``, ``"elout/shell"``, ``"ncforc/slave_1"``.
    """

    def __init__(self, paths: Sequence[str | Path]) -> None:
        self.files: tuple[Path, ...] = tuple(Path(p) for p in paths)
        if not self.files:
            raise FileNotFoundError("No binout file given.")
        self.notes: list[str] = []
        self._files = [_File(p, self.notes) for p in self.files]
        self._branches: dict[str, _Branch] = {}
        for i, f in enumerate(self._files):
            for d in f.order:
                parent, leaf = posixpath.split(d)
                m = _STATE.match(leaf)
                if leaf == "metadata":
                    b = self._branch(parent)
                    b.meta.setdefault(i, d)
                elif m:
                    self._branch(parent).states.append((i, d, int(m.group(1))))
        for b in self._branches.values():
            b.states.sort(key=lambda s: (s[0], s[2]))
        self._cache: dict[str, list[tuple[int, str]]] = {}

    def _branch(self, path: str) -> _Branch:
        name = path.strip("/")
        if name not in self._branches:
            self._branches[name] = _Branch(name)
        return self._branches[name]

    # --- context manager ------------------------------------------------------

    def close(self) -> None:
        for f in self._files:
            f.close()

    def __enter__(self) -> Binout:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"<Binout {', '.join(p.name for p in self.files)}: "
            f"{len(self.branches)} outputs>"
        )

    def __contains__(self, branch: object) -> bool:
        if not isinstance(branch, str):
            return False
        key = branch.strip("/")
        return key in self._branches or bool(self._children(key))

    def _children(self, name: str) -> list[str]:
        return [b for b in self._branches if b.startswith(name + "/")]

    # --- structure -------------------------------------------------------------

    @property
    def branches(self) -> list[str]:
        """Output names in file order (``glstat``, ``elout/shell`` ...)."""
        return list(self._branches)

    def _get(self, branch: str) -> _Branch:
        key = branch.strip("/")
        if key not in self._branches:
            raise KeyError(
                f"No output {branch!r} in the binout; outputs: "
                f"{', '.join(self._branches) or 'none'}."
            )
        return self._branches[key]

    def _value(self, file: int, folder: str, name: str) -> Any:
        f = self._files[file]
        typ, start, nbytes, _ = f.dirs[folder][name]
        return _decode(f, typ, start, nbytes)

    def _meta_folder(self, branch: _Branch, file: int) -> tuple[int, str] | None:
        if file in branch.meta:
            return file, branch.meta[file]
        if branch.meta:
            i = min(branch.meta)
            return i, branch.meta[i]
        return None

    def metadata(self, branch: str, file: int | None = None) -> dict[str, Any]:
        """The ``metadata`` folder of an output: text stripped, numbers as
        arrays. From the first file that has it, or from ``file``."""
        b = self._get(branch)
        where = self._meta_folder(b, file if file is not None else min(b.meta or {0}))
        if where is None:
            return {}
        i, folder = where
        out = {}
        for name in self._files[i].dirs[folder]:
            v = self._value(i, folder, name)
            out[name] = v.rstrip() if isinstance(v, str) else v
        return out

    def _states(self, branch: str) -> list[tuple[int, str]]:
        """State folders after restarts are resolved: (file, folder)."""
        key = branch.strip("/")
        if key in self._cache:
            return self._cache[key]
        b = self._get(key)
        kept: list[tuple[int, str]] = []
        times: list[float] = []
        for i, folder, _ in b.states:
            vars_ = self._files[i].dirs[folder]
            t = float(self._value(i, folder, "time")[0]) if "time" in vars_ else np.nan
            if times and not np.isnan(t) and t <= times[-1]:
                cut = int(np.searchsorted(np.asarray(times), t, side="left"))
                del times[cut:], kept[cut:]
            kept.append((i, folder))
            times.append(t)
        self._cache[key] = kept
        return kept

    def time(self, branch: str) -> np.ndarray:
        """Output times of an output (model time unit)."""
        out = []
        for i, folder in self._states(branch):
            v = self._files[i].dirs[folder]
            out.append(
                float(self._value(i, folder, "time")[0]) if "time" in v else np.nan
            )
        return np.asarray(out, dtype=float)

    def variables(self, branch: str) -> list[str]:
        """Names of the variables of an output's states, in file order;
        sub-folder variables as ``"misc/x_moment0"``."""
        names: dict[str, None] = {}
        for i, folder in self._states(branch)[:1] + self._states(branch)[-1:]:
            for d in self._subfolders(i, folder):
                prefix = d[len(folder) + 1 :]
                for name in self._files[i].dirs[d]:
                    names[f"{prefix}/{name}" if prefix else name] = None
        return list(names)

    def _subfolders(self, file: int, folder: str) -> list[str]:
        return [
            d
            for d in self._files[file].order
            if d == folder or d.startswith(folder + "/")
        ]

    def variable(self, branch: str, name: str, state: int = 0) -> BinoutVariable:
        """Where a variable of one state is stored."""
        i, folder = self._states(branch)[state]
        sub, _, leaf = name.rpartition("/")
        d = f"{folder}/{sub}" if sub else folder
        typ, start, nbytes, rec = self._files[i].dirs[d][leaf]
        return BinoutVariable(leaf, typ, i, start, nbytes, rec)

    def read(self, branch: str, name: str) -> np.ndarray:
        """One variable over all states: shape ``(states, values)``, or
        ``(states,)`` when every state has one value. States with fewer
        values are padded with NaN; missing in a state: NaN."""
        rows = []
        for i, folder in self._states(branch):
            sub, _, leaf = name.rpartition("/")
            d = f"{folder}/{sub}" if sub else folder
            vars_ = self._files[i].dirs.get(d, {})
            if leaf in vars_:
                v = _decode(self._files[i], *vars_[leaf][:3])
                if isinstance(v, str):
                    raise TypeError(f"{branch}/{name} is text, not numbers.")
                rows.append(v)
            else:
                rows.append(None)
        if not rows or all(r is None for r in rows):
            raise KeyError(
                f"{branch}: no variable {name!r}; variables: "
                f"{', '.join(self.variables(branch))}."
            )
        width = max(len(r) for r in rows if r is not None)
        same = all(r is not None and len(r) == width for r in rows)
        if same and all(r.dtype.kind == "i" for r in rows):  # type: ignore[union-attr]
            out = np.vstack(rows).astype(np.int64)
        else:
            out = np.full((len(rows), width), np.nan)
            for k, r in enumerate(rows):
                if r is not None:
                    out[k, : len(r)] = r
        return out[:, 0] if width == 1 else out

    def _ids(self, branch: str) -> np.ndarray | None:
        meta = self.metadata(branch)
        for key in ("ids", "force_ids"):
            if key in meta and not isinstance(meta[key], str) and len(meta[key]):
                return np.asarray(meta[key], dtype=np.int64)
        return None

    def legend(self, branch: str) -> dict[int, str]:
        """Entity titles from the metadata legend (fixed-width entries)."""
        meta = self.metadata(branch)
        text, ids = meta.get("legend"), meta.get("legend_ids")
        if not isinstance(text, str) or ids is None or not len(ids):
            return {}
        raw = self._raw_meta(branch, "legend")
        width = len(raw) // len(ids) if len(raw) % len(ids) == 0 else 80
        return {
            int(k): raw[j * width : (j + 1) * width].strip()
            for j, k in enumerate(ids)
            if raw[j * width : (j + 1) * width].strip()
        }

    def _raw_meta(self, branch: str, name: str) -> str:
        b = self._get(branch)
        where = self._meta_folder(b, min(b.meta or {0}))
        if where is None:
            return ""
        v = self._value(where[0], where[1], name)
        return v if isinstance(v, str) else ""

    def summary(self) -> str:
        lines = [
            f"binout: {', '.join(p.name for p in self.files)} "
            f"({len(self.branches)} outputs)"
        ]
        meta = next((self.metadata(b) for b in self.branches if self._get(b).meta), {})
        if meta.get("title"):
            lines.append(f"  {meta['title']}")
        if meta.get("version"):
            lines.append(
                f"  ls-dyna {meta.get('version', '')} {meta.get('build_id', '')} "
                f"date {meta.get('date', '')}".rstrip()
            )
        for b in self.branches:
            t = self.time(b)
            ids = self._ids(b)
            n = f", {len(np.unique(ids))} entities" if ids is not None else ""
            span = f", time {t[0]:.6g} to {t[-1]:.6g}" if len(t) else ""
            lines.append(f"  {b}: {len(t)} states{span}{n}")
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)

    # --- conversion -------------------------------------------------------------

    def output(self, branch: str) -> AsciiOutput:
        """An output as the ASCII readers return it (`AsciiOutput`).

        Channel names are the binout variable names, which the ASCII
        readers use too; rcforc channels get ``surfa_`` / ``surfb_`` by
        the contact side, sleout's slave and master energies become
        ``surfa_energy`` / ``surfb_energy``, spcforc's resultants its
        totals. Variables with one value per state (glstat, the totals)
        go to ``totals``; variables whose length is not the number of
        entities (several integration points) are left out (read them
        with `read`)."""
        key = branch.strip("/")
        if key not in self._branches and self._children(key):
            return self._merged(key)
        kind = key.split("/")[0]
        states = self._states(key)
        meta = self.metadata(key)
        n = len(states)
        time = self.time(key)
        side = meta.get("side") if kind == "rcforc" else None
        meta_ids = self._ids(key)
        moment_ids = meta.get("moment_ids") if kind == "spcforc" else None
        # (state, channel, entity IDs, values, add duplicate IDs)
        pieces: list[tuple[int, str, np.ndarray, np.ndarray, bool]] = []
        totals: dict[str, np.ndarray] = {}
        cycles = np.full(n, np.nan)
        skip = {"time", "cycle", "ids", "side"}
        for s, (i, folder) in enumerate(states):
            vars_ = self._files[i].dirs[folder]
            ids = (
                np.asarray(self._value(i, folder, "ids"), dtype=np.int64)
                if "ids" in vars_
                else meta_ids
            )
            if "cycle" in vars_:
                cycles[s] = float(self._value(i, folder, "cycle")[0])
            for name, (typ, start, nbytes, _) in vars_.items():
                if name in skip or typ == 1:
                    continue
                v = np.asarray(_decode(self._files[i], typ, start, nbytes), dtype=float)
                for channel, keys, values, add in _place(
                    kind, name, v, ids, side, moment_ids, meta
                ):
                    if keys is None:
                        totals.setdefault(channel, np.full(n, np.nan))[s] = values[0]
                    else:
                        pieces.append((s, channel, keys, values, add))
        order: dict[int, None] = {}
        channels: dict[str, None] = {}
        known: set[int] = set()
        for _, channel, keys, _, _ in pieces:
            channels.setdefault(channel, None)
            if id(keys) not in known:
                known.add(id(keys))
                for k in keys.tolist():
                    order.setdefault(k, None)
        ids_out = tuple(order)
        lookup = np.asarray(ids_out, dtype=np.int64)
        sorter = np.argsort(lookup, kind="stable")
        columns: dict[int, np.ndarray] = {}
        data = {c: np.full((n, len(ids_out)), np.nan) for c in channels}
        for s, channel, keys, values, add in pieces:
            col = columns.get(id(keys))
            if col is None:
                col = sorter[np.searchsorted(lookup, keys, sorter=sorter)]
                columns[id(keys)] = col
            row = data[channel][s]
            if add:
                row[col] = np.where(np.isnan(row[col]), 0.0, row[col])
                np.add.at(row, col, values)
            else:
                row[col] = values
        version = " ".join(
            x for x in (meta.get("version", ""), meta.get("build_id", "")) if x
        )
        if meta.get("date"):
            version += f" date {meta['date']}"
        return AsciiOutput(
            kind=key,
            time=time,
            ids=ids_out,
            data=data,
            totals=totals,
            names=self.legend(key),
            title=_text(meta.get("title", "")),
            version=f"ls-dyna {version}".strip() if version else "",
            cycle=cycles if n and not np.all(np.isnan(cycles)) else None,
        )

    def _merged(self, name: str) -> AsciiOutput:
        """One output from the outputs below a folder (``jntforc`` from
        ``jntforc/type0`` and ``jntforc/type1``); their times must agree."""
        parts = [self.output(b) for b in self._children(name)]
        time = parts[0].time
        if any(len(p.time) != len(time) or np.any(p.time != time) for p in parts):
            raise ValueError(
                f"The outputs below {name!r} have different times; read them "
                f"one by one: {', '.join(self._children(name))}."
            )
        ids: dict[int, None] = {}
        for p in parts:
            ids.update(dict.fromkeys(p.ids))
        order = tuple(ids)
        col = {k: j for j, k in enumerate(order)}
        data: dict[str, np.ndarray] = {}
        totals: dict[str, np.ndarray] = {}
        names: dict[int, str] = {}
        for p in parts:
            cols = [col[k] for k in p.ids]
            for c, v in p.data.items():
                arr = data.setdefault(c, np.full((len(time), len(order)), np.nan))
                fill = ~np.isnan(v)
                arr[:, cols] = np.where(fill, v, arr[:, cols])
            for c, v in p.totals.items():
                totals.setdefault(c, v)
            names.update(p.names)
        return AsciiOutput(
            kind=name,
            time=time,
            ids=order,
            data=data,
            totals=totals,
            names=names,
            title=parts[0].title,
            version=parts[0].version,
            cycle=parts[0].cycle,
        )

    def glstat(self) -> GlobalEnergies:
        """The glstat output as `GlobalEnergies` (as `read_glstat`)."""
        key = "glstat"
        data = {"time": self.time(key)}
        for name in self.variables(key):
            if name in ("time", "cycle") or "/" in name:
                continue
            try:
                v = self.read(key, name)
            except TypeError:
                continue
            if v.ndim == 1:
                data[name] = v.astype(float)
        return GlobalEnergies.from_mapping(data)

    def matsum(self) -> PartEnergies:
        """The matsum output as `PartEnergies` (as `read_matsum`). The
        added mass of a part is ``added_mass`` if the file has it, else
        ``added_cms_mass`` + ``added_sms_mass`` (conventional and
        selective mass scaling)."""
        out = self.output("matsum")
        data = dict(out.data)
        if "added_mass" not in data:
            parts = [data[k] for k in ("added_cms_mass", "added_sms_mass") if k in data]
            if parts:
                data["added_mass"] = np.nansum(np.stack(parts), axis=0)
        return PartEnergies.from_mapping(out.time, out.ids, data, out.names)

    def to_csv(
        self, folder: str | Path, branches: Iterable[str] | None = None
    ) -> list[Path]:
        """One CSV per output (`AsciiOutput.to_csv`); returns the files."""
        out_dir = Path(folder)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for b in branches or self.branches:
            o = self.output(b)
            if not len(o):
                continue
            written.append(o.to_csv(out_dir / (b.replace("/", "_") + ".csv")))
        return written

    # --- checking the index -------------------------------------------------------

    def verify(self) -> list[str]:
        """Compare each file's symbol tables with its records: every
        variable must be listed with the right type, place and count.
        Returns the problems found (empty: consistent)."""
        problems: list[str] = []
        for f in self._files:
            b = f.data
            listed: dict[tuple[str, str], tuple[int, int, int]] = {}
            hlen = f.header[0]
            pos = hlen
            length = struct.unpack_from(f.lfmt, b, pos)[0] if len(b) > hlen else 0
            if not length or b[pos + f.lsize] != _CMD_FIRST:
                problems.append(f"{f.path.name}: no symbol table pointer.")
                continue
            table = struct.unpack_from(f.ofmt, b, pos + f.lsize + 1)[0]
            seen = set()
            while table:
                if table in seen or table + f.lsize + 1 > f.end:
                    problems.append(
                        f"{f.path.name}: symbol table at {table} not readable."
                    )
                    break
                seen.add(table)
                tlen = struct.unpack_from(f.lfmt, b, table)[0]
                if b[table + f.lsize] != _CMD_SYMTAB:
                    problems.append(f"{f.path.name}: no symbol table at {table}.")
                    break
                q, end, cwd, nxt = table + f.lsize + 1, table + tlen, "/", 0
                while q < end:
                    sl = struct.unpack_from(f.lfmt, b, q)[0]
                    cmd = b[q + f.lsize]
                    body = bytes(b[q + f.lsize + 1 : q + sl])
                    if cmd == _CMD_CD:
                        cwd = posixpath.normpath(
                            posixpath.join(cwd, body.decode("latin-1"))
                        )
                    elif cmd == 4:
                        tail = 1 + 2 * f.osize
                        name = body[:-tail].decode("latin-1")
                        typ = body[-tail]
                        off = struct.unpack_from(f.ofmt, body, len(body) - 2 * f.osize)[
                            0
                        ]
                        cnt = struct.unpack_from(f.ofmt, body, len(body) - f.osize)[0]
                        listed[(cwd, name)] = (typ, off, cnt)
                    elif cmd == _CMD_NEXT:
                        nxt = struct.unpack_from(f.ofmt, body, 0)[0]
                    q += sl
                table = nxt
            for d, vars_ in f.dirs.items():
                for name, (typ, start, nbytes, rec) in vars_.items():
                    entry = listed.get((d, name))
                    count = nbytes // _TYPES.get(typ, ("u1", 1))[1]
                    if entry is None:
                        problems.append(
                            f"{f.path.name}: {d}/{name} not in a symbol table."
                        )
                    elif entry != (typ, rec, count):
                        problems.append(
                            f"{f.path.name}: {d}/{name}: table {entry}, record "
                            f"{(typ, rec, count)}."
                        )
        return problems


_Piece = tuple[str, "np.ndarray | None", np.ndarray, bool]

_ROTATIONAL = {
    "x_force": "x_moment",
    "y_force": "y_moment",
    "z_force": "z_moment",
    "resultant_force": "resultant_moment",
    "displacement": "relative_rotation",
}
"""deforc channel names of rotational springs (as the ASCII file names
them)."""


def _place(
    kind: str,
    name: str,
    v: np.ndarray,
    ids: np.ndarray | None,
    side: Any,
    moment_ids: Any,
    meta: Mapping[str, Any],
) -> list[_Piece]:
    """Channel pieces of one variable of one state: (channel, entity IDs,
    or None for a total, values, add values of repeated IDs)."""
    if kind == "rcforc" and ids is not None and side is not None:
        if len(v) != len(ids):
            return []
        sd = np.asarray(side, dtype=int)
        out: list[_Piece] = []
        for mask, prefix in ((sd != 1, "surfa_"), (sd == 1, "surfb_")):
            if mask.any():
                out.append((prefix + name, ids[mask], v[mask], False))
        return out
    if kind == "sleout" and ids is not None:
        tots = {
            "total_slave": "surfa_energy",
            "total_master": "surfb_energy",
            "total_friction": "friction_energy",
            "total_energy": "total_energy",
        }
        if name in tots:
            return [(tots[name], None, v[:1], False)]
        if name == "master":
            single = np.asarray(meta.get("single_sided", np.zeros(len(ids))), dtype=int)
            if len(single) != len(ids):
                single = np.zeros(len(ids), dtype=int)
            two = ids[single == 0]
            if len(v) != len(two):
                return []
            out = [("surfb_energy", two, v, False)]
            if (single != 0).any():
                one = ids[single != 0]
                out.append(("surfb_energy", one, np.zeros(len(one)), False))
            return out
        if name == "slave" and len(v) == len(ids):
            return [("surfa_energy", ids, v, False)]
        if name == "friction_energy" and len(v) == len(ids):
            return [(name, ids, v, False)]
        return []
    if kind == "deforc" and ids is not None and len(v) == len(ids):
        irot = np.asarray(meta.get("irot", np.zeros(len(ids))))
        rot = irot != 0 if len(irot) == len(ids) else np.zeros(len(ids), bool)
        out = []
        if (~rot).any():
            moved = {"displacement": "change_in_length"}.get(name, name)
            out.append((moved, ids[~rot], v[~rot], False))
        if rot.any():
            out.append((_ROTATIONAL.get(name, name), ids[rot], v[rot], False))
        return out
    if kind == "swforc" and name == "failure_time":
        v = np.where((v > 0) & (v < 1e15), v, np.nan)
    if kind == "spcforc":
        if name.endswith("_resultant"):
            return [(name.replace("_resultant", "_force"), None, v[:1], False)]
        if "moment" in name:
            if moment_ids is not None and len(v) and len(v) == len(moment_ids):
                return [(name, np.asarray(moment_ids, dtype=np.int64), v, True)]
            return []
        if ids is not None and len(v) == len(ids):
            return [(name, ids, v, True)]
        return []
    if ids is not None and len(ids) and len(v) == len(ids):
        return [(name, ids, v, False)]
    if len(v) == 1:
        return [(name, None, v, False)]
    return []


def find_binout(folder: str | Path) -> list[Path]:
    """The binout files of a run folder (``binout``, ``binout0000`` ...,
    also with a job prefix such as ``run1.binout0000``), in name order."""
    folder = Path(folder)
    pattern = re.compile(r"(^|\.)binout\d*$", re.I)
    return sorted(p for p in folder.iterdir() if p.is_file() and pattern.search(p.name))


def read_binout(path: str | Path | Sequence[str | Path]) -> Binout:
    """Read binout files: a run folder (all its binout files), one file,
    or a list of files (read in the order given)."""
    if isinstance(path, (str, Path)):
        p = Path(path)
        if p.is_dir():
            files = find_binout(p)
            if not files:
                raise FileNotFoundError(f"No binout file in {p}.")
            return Binout(files)
        if not p.is_file():
            raise FileNotFoundError(f"{p} does not exist.")
        return Binout([p])
    return Binout(list(path))


# --- Writing ------------------------------------------------------------------------


def _type_of(value: Any) -> tuple[int, bytes]:
    if isinstance(value, str):
        return 1, value.encode("latin-1")
    a = np.asarray(value)
    if a.dtype.kind in "iub":
        if a.dtype.itemsize <= 4:
            return 3, a.astype("<i4").tobytes()
        return 4, a.astype("<i8").tobytes()
    if a.dtype == np.float32:
        return 9, a.astype("<f4").tobytes()
    return 10, a.astype("<f8").tobytes()


def write_binout(path: str | Path, folders: Mapping[str, Mapping[str, Any]]) -> Path:
    """Write a binout file in the layout read here: ``folders`` maps a
    folder (``"/nodout/metadata"``, ``"/nodout/d000001"``) to its
    variables (text, or integer or float arrays; float32 and int32 arrays
    are written in single precision). One symbol table at the end.

    For tests and synthetic runs; whether LS-PrePost or other tools read
    the files has not been checked."""
    out = bytearray(bytes([8, 8, 8, 1, 1, 1, 0, 0]))

    def record(cmd: int, payload: bytes) -> int:
        start = len(out)
        out.extend(struct.pack("<Q", 9 + len(payload)))
        out.append(cmd)
        out.extend(payload)
        return start

    first = record(_CMD_FIRST, struct.pack("<Q", 0))
    index: list[tuple[str, list[tuple[str, int, int, int]]]] = []
    for folder, variables in folders.items():
        d = "/" + folder.strip("/")
        record(_CMD_CD, d.encode("latin-1"))
        entries = []
        for name, value in variables.items():
            typ, raw = _type_of(value)
            nb = name.encode("latin-1")
            if len(nb) > 255:
                raise ValueError(f"Variable name {name!r} is too long.")
            rec = record(_CMD_DATA, bytes([typ, len(nb)]) + nb + raw)
            entries.append((name, typ, rec, len(raw) // _TYPES[typ][1]))
        index.append((d, entries))
    table = bytearray()

    def sub(cmd: int, payload: bytes) -> None:
        table.extend(struct.pack("<Q", 9 + len(payload)))
        table.append(cmd)
        table.extend(payload)

    for d, entries in index:
        sub(_CMD_CD, d.encode("latin-1"))
        for name, typ, rec, count in sorted(entries):
            sub(
                4,
                name.encode("latin-1") + bytes([typ]) + struct.pack("<QQ", rec, count),
            )
    sub(_CMD_NEXT, struct.pack("<Q", 0))
    at = record(_CMD_SYMTAB, bytes(table))
    struct.pack_into("<Q", out, first + 9, at)
    p = Path(path)
    p.write_bytes(bytes(out))
    return p


# --- Command line ---------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """``crashmetrics-binout PATH [--csv DIR] [--output NAME]``: list the
    outputs of a binout (a run folder or files), or write them as CSV."""
    parser = argparse.ArgumentParser(
        prog="crashmetrics-binout",
        description="List LS-DYNA binout outputs or write them as CSV files.",
    )
    parser.add_argument("path", nargs="+", help="run folder or binout files")
    parser.add_argument("--csv", default=None, help="write one CSV per output here")
    parser.add_argument(
        "--output",
        action="append",
        default=None,
        help="only this output (repeat for several), e.g. nodout",
    )
    args = parser.parse_args(argv)
    bo = read_binout(args.path[0] if len(args.path) == 1 else args.path)
    with bo:
        print(bo.summary())
        if args.csv:
            for p in bo.to_csv(args.csv, args.output):
                print(f"written: {p}")
    return 0
