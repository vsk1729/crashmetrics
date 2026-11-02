"""Summary table and a material library with provenance.

- `card_summary`: one row per ``*MAT_024`` card (density, E, SIGY,
  stress at chosen strains, rate model, FAIL, provenance), as dicts for
  CSV and as a Markdown table (`summary_markdown`).
- `MaterialLibrary`: a folder of cards stored as JSON in engineering
  units with their full provenance (tests, fits, who and when).
  ``save`` / ``load`` / ``names`` / ``export`` (to a ``.k`` include in any
  unit system). Plain JSON files: diff them, keep them in git.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from crashmetrics.materials.card import Mat024
from crashmetrics.materials.hardening import HardeningCurve
from crashmetrics.materials.rate import RateTable

__all__ = ["MaterialLibrary", "card_summary", "summary_markdown"]

FORMAT = "crashmetrics-material/1"


def card_summary(
    cards: Sequence[Mat024],
    *,
    strains: Sequence[float] = (0.05, 0.2, 0.5, 1.0),
) -> list[dict[str, object]]:
    """One row per card: MID, title, density (kg/m³), E (GPa), SIGY and
    the static stress at ``strains`` (MPa), rate model, FAIL and the
    provenance entries (``prov.<key>``)."""
    rows = []
    for m in cards:
        if m.table is not None:
            rate = f"table, {len(m.table.rates)} rates {m.table.rates[0]:g}-" \
                   f"{m.table.rates[-1]:g}/s"
        elif m.c:
            rate = f"Cowper-Symonds C {m.c:g}/s P {m.p:g}"
        else:
            rate = "none"
        row: dict[str, object] = {
            "mid": m.mid, "title": m.title, "density": m.density,
            "E_GPa": m.modulus / 1000.0, "sigy": m.yield_stress,
        }
        stress = m.stress(np.asarray(strains, dtype=float))
        row.update({f"stress@{e:g}": float(s) for e, s in zip(strains, stress)})
        row.update(rate=rate, fail=m.fail)
        row.update({f"prov.{k}": v for k, v in m.provenance.items()})
        rows.append(row)
    return rows


def summary_markdown(rows: Sequence[Mapping[str, object]]) -> str:
    """Markdown table of `card_summary` rows (provenance columns left out)."""
    if not rows:
        return ""
    keys = [k for k in rows[0] if not k.startswith("prov.")]

    def cell(v: object) -> str:
        if isinstance(v, float):
            return f"{v:.4g}"
        return str(v)

    lines = ["| " + " | ".join(keys) + " |", "|" + " --- |" * len(keys)]
    lines += ["| " + " | ".join(cell(r.get(k, "")) for k in keys) + " |" for r in rows]
    return "\n".join(lines)


def _to_json(m: Mat024) -> dict[str, object]:
    data: dict[str, object] = {
        "mid": m.mid, "title": m.title, "density": m.density, "modulus": m.modulus,
        "poisson": m.poisson, "c": m.c, "p": m.p, "vp": m.vp, "fail": m.fail,
        "tdel": m.tdel, "curve_id": m.curve_id,
        "provenance": {k: str(v) for k, v in m.provenance.items()},
    }
    if m.curve is not None:
        data["curve"] = {"plastic_strain": m.curve.plastic_strain.tolist(),
                         "stress": m.curve.stress.tolist(),
                         "necking_strain": m.curve.necking_strain}
    else:
        assert m.table is not None
        data["table"] = {"rates": m.table.rates.tolist(),
                         "plastic_strain": m.table.plastic_strain.tolist(),
                         "stress": m.table.stress.tolist()}
    return data


def _from_json(data: Mapping[str, object]) -> Mat024:
    curve = table = None
    if "curve" in data:
        c = data["curve"]
        assert isinstance(c, dict)
        curve = HardeningCurve(np.asarray(c["plastic_strain"]), np.asarray(c["stress"]),
                               float(data["modulus"]),  # type: ignore[arg-type]
                               float(c["necking_strain"]), str(data.get("title", "")))
    else:
        t = data["table"]
        assert isinstance(t, dict)
        table = RateTable(np.asarray(t["rates"]), np.asarray(t["plastic_strain"]),
                          np.asarray(t["stress"]))
    prov = data.get("provenance", {})
    return Mat024(
        mid=int(data["mid"]),  # type: ignore[call-overload]
        density=float(data["density"]),  # type: ignore[arg-type]
        modulus=float(data["modulus"]),  # type: ignore[arg-type]
        curve=curve, table=table,
        poisson=float(data.get("poisson", 0.3)),  # type: ignore[arg-type]
        c=float(data.get("c", 0.0)),  # type: ignore[arg-type]
        p=float(data.get("p", 0.0)),  # type: ignore[arg-type]
        vp=int(data.get("vp", 0)),  # type: ignore[call-overload]
        fail=float(data.get("fail", 0.0)),  # type: ignore[arg-type]
        tdel=float(data.get("tdel", 0.0)),  # type: ignore[arg-type]
        curve_id=data.get("curve_id"),  # type: ignore[arg-type]
        title=str(data.get("title", "")),
        provenance=dict(prov) if isinstance(prov, dict) else {},
    )


class MaterialLibrary:
    """A folder of ``*MAT_024`` materials as JSON files with provenance.

    Each material is ``<name>.json`` holding the card in engineering
    units (kg/m³, MPa, 1/s), its curve or table, the provenance given
    to `Mat024`, and when and with which crashmetrics version it was
    saved.
    """

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._\-]+", name):
            raise ValueError("Library names use letters, digits, '.', '_' and '-'.")
        return self.directory / f"{name}.json"

    def names(self) -> list[str]:
        """Names of the stored materials."""
        return sorted(p.stem for p in self.directory.glob("*.json"))

    def save(self, mat: Mat024, name: str | None = None, *, overwrite: bool = False,
             date: dt.date | None = None, note: str = "") -> Path:
        """Store a card; ``name`` defaults to the title (or ``mat<MID>``).
        Refuses to replace an existing entry unless ``overwrite``."""
        from crashmetrics import __version__

        key = name or re.sub(r"[^A-Za-z0-9._\-]+", "_", mat.title).strip("_") \
            or f"mat{mat.mid}"
        path = self._path(key)
        if path.exists() and not overwrite:
            raise FileExistsError(f"{key} exists in the library; overwrite=True to "
                                  "replace it.")
        record = {"format": FORMAT, "saved": (date or dt.date.today()).isoformat(),
                  "crashmetrics": __version__, "note": note, "material": _to_json(mat)}
        path.write_text(json.dumps(record, indent=1) + "\n")
        return path

    def load(self, name: str) -> Mat024:
        """The stored card."""
        path = self._path(name)
        if not path.exists():
            raise KeyError(f"No material {name!r}; stored: {self.names()}.")
        record = json.loads(path.read_text())
        if record.get("format") != FORMAT:
            raise ValueError(f"{path} is not a crashmetrics material file.")
        return _from_json(record["material"])

    def info(self, name: str) -> dict[str, object]:
        """Saved date, crashmetrics version, note and provenance."""
        record = json.loads(self._path(name).read_text())
        return {"saved": record["saved"], "crashmetrics": record["crashmetrics"],
                "note": record.get("note", ""),
                "provenance": record["material"].get("provenance", {})}

    def summary(self, **options: Sequence[float]) -> list[dict[str, object]]:
        """`card_summary` of every stored card, with a ``name`` column."""
        rows = []
        for name in self.names():
            row = card_summary([self.load(name)], **options)[0]
            rows.append({"name": name, **row})
        return rows

    def export(self, name: str, path: str | Path, unit_system: str = "mm-ms-kg",
               **options: object) -> Path:
        """Write a stored card as an include file (`Mat024.write`)."""
        return self.load(name).write(path, unit_system, **options)  # type: ignore[arg-type]
