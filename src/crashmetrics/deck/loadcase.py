"""The load case of a deck, and whether it writes what the analysis needs.

`load_case` summarises how a deck is set up to run:

- termination time, time step controls and mass scaling, energy and
  hourglass settings;
- initial velocities (speed in km/h and direction), rigid walls,
  prescribed motions, gravity;
- contacts (type, what each side is, friction);
- every output: ASCII files with their interval and whether they are
  written as ASCII or only to binout, d3plot, history nodes and cross
  sections.

`output_requirements` checks the outputs against what crashmetrics'
analyses read: model quality and energy checks (glstat, matsum,
sleout, the energy settings that make them complete), load paths
(matsum, secforc and cross sections), spot welds (swforc), head and
dummy criteria from nodes (nodout, history nodes, a sampling rate high
enough for the filter class), contact and wall forces (rcforc,
rwforc). Each is PASS, FAIL or WARN with the fix.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from crashmetrics.deck.bulk import record_id
from crashmetrics.deck.cards import ASCII_OUTPUTS
from crashmetrics.deck.checks import DeckCheck, DeckSheet
from crashmetrics.deck.model import UNIT_SYSTEMS, guess_units
from crashmetrics.deck.reader import Deck

__all__ = ["ANALYSES", "LoadCase", "Output", "load_case", "output_requirements"]

_BINARY = {0: "solver default", 1: "ASCII", 2: "binout only", 3: "ASCII and binout"}
_CONTACT_SIDE = {
    0: "segment set",
    1: "shell set",
    2: "part set",
    3: "part",
    4: "node set",
    5: "all parts",
    6: "part set (excluded)",
}
_IVG = {1: "part set", 2: "part", 3: "node set"}
_VAD = {0: "velocity", 1: "acceleration", 2: "displacement"}


@dataclass(frozen=True)
class Output:
    name: str
    """``GLSTAT``, ``NODOUT`` ... or ``BINARY_D3PLOT``."""
    dt: float
    """Model time units (0: not written at an interval)."""
    binary: int
    where: str

    @property
    def ascii(self) -> bool:
        """Written as an ASCII file (BINARY 1 or 3, or the default)."""
        return self.binary in (0, 1, 3)


@dataclass(frozen=True)
class LoadCase:
    title: str
    unit_system: str | None
    end_time: float
    """Model time units (0: not set)."""
    tssfac: float
    dt2ms: float
    energy: dict[str, int]
    """CONTROL_ENERGY flags (hgen, rwen, slnten, rylen)."""
    hourglass: dict[str, float]
    velocities: tuple[str, ...]
    speeds: tuple[float, ...]
    """Initial speeds, model velocity units."""
    walls: tuple[str, ...]
    motions: tuple[str, ...]
    gravity: tuple[str, ...]
    contacts: tuple[str, ...]
    outputs: dict[str, Output]
    history_nodes: tuple[int, ...]
    history_node_sets: tuple[int, ...]
    cross_sections: tuple[str, ...]
    implicit: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def _t(self, v: float) -> str:
        if not self.unit_system:
            return f"{v:.4g} (model time)"
        return f"{v * UNIT_SYSTEMS[self.unit_system][1]:.4g} ms"

    def kmh(self, speed: float) -> float:
        """A model velocity in km/h (NaN without a unit system)."""
        if not self.unit_system:
            return math.nan
        length, time, _ = UNIT_SYSTEMS[self.unit_system]
        return speed * length / time * 3.6  # mm/ms = m/s

    def summary(self) -> str:
        us = self.unit_system or "unknown units"
        lines = [
            f"{self.title or '(no title)'} [{us}]",
            f"End time {self._t(self.end_time) if self.end_time else 'NOT SET'}"
            + (", implicit" if self.implicit else ""),
            f"Time step: TSSFAC {self.tssfac:g}"
            + (
                f", mass scaling DT2MS {self.dt2ms:g}"
                if self.dt2ms
                else ", no mass scaling"
            ),
            "Energy: "
            + (
                ", ".join(f"{k.upper()} {v}" for k, v in self.energy.items())
                or "no *CONTROL_ENERGY"
            ),
        ]
        for v, s in zip(self.velocities, self.speeds):
            kmh = self.kmh(s)
            lines.append(
                f"Initial velocity: {v}"
                + (f" ({kmh:.1f} km/h)" if not math.isnan(kmh) else "")
            )
        lines += [f"Rigid wall: {w}" for w in self.walls]
        lines += [f"Prescribed motion: {m}" for m in self.motions]
        lines += [f"Gravity: {g}" for g in self.gravity]
        lines.append(f"{len(self.contacts)} contacts" + (":" if self.contacts else ""))
        lines += [f"  {c}" for c in self.contacts]
        outs = [
            f"{o.name.lower().replace('binary_', '')} every {self._t(o.dt)}"
            + (
                ""
                if o.name.startswith("BINARY_")
                else f" ({_BINARY.get(o.binary, o.binary)})"
            )
            for o in self.outputs.values()
        ]
        lines.append("Outputs: " + ("; ".join(outs) if outs else "none"))
        if self.history_nodes or self.history_node_sets:
            lines.append(
                f"History nodes: {len(self.history_nodes)} nodes, "
                f"{len(self.history_node_sets)} node sets"
            )
        if self.cross_sections:
            lines.append(f"Cross sections: {', '.join(self.cross_sections)}")
        lines += [f"Note: {n}" for n in self.notes]
        return "\n".join(lines)


def load_case(deck: Deck, unit_system: str | None = None) -> LoadCase:
    """How a deck is set up to run (see the module notes)."""
    us = unit_system or guess_units(deck)
    notes: list[str] = []
    term = next(iter(deck.records("CONTROL_TERMINATION")), None)
    ts = next(iter(deck.records("CONTROL_TIMESTEP")), None)
    en = next(iter(deck.records("CONTROL_ENERGY")), None)
    hg = next(iter(deck.records("CONTROL_HOURGLASS")), None)
    implicit = any(r.get("imflag", 0) for r in deck.records("CONTROL_IMPLICIT_GENERAL"))

    velocities, speeds = [], []
    for r in deck.records("INITIAL_VELOCITY*"):
        v = [r.get("vx", 0.0), r.get("vy", 0.0), r.get("vz", 0.0)]
        speed = math.sqrt(sum(x * x for x in v))
        sub = r.block.subtype
        if sub == "VELOCITY_GENERATION":
            styp = r.get("styp", 0)
            what = f"{_IVG.get(styp, f'styp {styp}')} {r.get('id')}"
            if r.get("omega", 0.0):
                what += f", rotating at {r['omega']:g}"
        elif sub == "VELOCITY":
            what = f"node set {r.get('nsid')}" if r.get("nsid") else "all nodes"
        elif sub == "VELOCITY_RIGID_BODY":
            what = f"rigid part {r.get('pid')}"
        else:
            what = f"node {r.get('nid')}"
        velocities.append(f"{what}: ({v[0]:g}, {v[1]:g}, {v[2]:g})")
        speeds.append(speed)

    walls = []
    for r in deck.records("RIGIDWALL_*"):
        if r.block.subtype.startswith("PLANAR"):
            n = [
                r.get("xh", 0.0) - r.get("xt", 0.0),
                r.get("yh", 0.0) - r.get("yt", 0.0),
                r.get("zh", 0.0) - r.get("zt", 0.0),
            ]
            text = (
                f"planar at ({r.get('xt', 0.0):g}, {r.get('yt', 0.0):g}, "
                f"{r.get('zt', 0.0):g}), normal ({n[0]:g}, {n[1]:g}, {n[2]:g}), "
                f"friction {r.get('fric', 0.0):g}"
            )
            if "MOVING" in r.block.options:
                text += (
                    f", moving: mass {r.get('mass', 0.0):g}, speed {r.get('v0', 0.0):g}"
                )
            if "FINITE" in r.block.options:
                text += f", finite {r.get('lenl', 0.0):g} x {r.get('lenm', 0.0):g}"
        else:
            text = r.block.subtype.lower().replace("_", " ")
        if r.get("nsid", 0):
            text += f", slave nodes: set {r['nsid']}"
        walls.append(text)

    motions = [
        f"{r.block.subtype.split('_')[-1].lower()} {r.get('id')}: dof {r.get('dof')}, "
        f"{_VAD.get(r.get('vad', 0), 'vad ' + str(r.get('vad')))} "
        f"curve {r.get('lcid')} x {r.get('sf', 1.0) or 1.0:g}"
        for r in deck.records("BOUNDARY_PRESCRIBED_MOTION_*")
    ]
    gravity = [
        f"{r.block.subtype.split('_')[-1]}: curve {r.get('lcid')} x "
        f"{r.get('sf', 1.0) or 1.0:g}"
        for r in deck.records("LOAD_BODY_*")
        if r.block.subtype.split("_")[-1] in ("X", "Y", "Z")
    ]

    contacts = []
    for r in deck.records("CONTACT_*"):
        s = _CONTACT_SIDE.get(r.get("sstyp", 0), f"type {r.get('sstyp')}")
        m = _CONTACT_SIDE.get(r.get("mstyp", 0), f"type {r.get('mstyp')}")
        head = r.get("heading", "") or ""
        text = (
            f"{r.block.subtype.lower()}"
            + (f" {r.get('cid')} '{head}'" if r.get("cid") else "")
            + f": {s} {r.get('ssid')}"
            + (f" / {m} {r.get('msid')}" if r.get("msid") else "")
            + f", friction {r.get('fs', 0.0):g}/{r.get('fd', 0.0):g}"
        )
        if r.get("soft"):
            text += f", SOFT {r['soft']}"
        contacts.append(text)
    for b in deck.find("CONTACT_*"):
        if b.spec is None:
            contacts.append(f"{b.keyword.lower()} (not read here)")

    outputs: dict[str, Output] = {}
    for b in deck.blocks:
        if b.family != "DATABASE":
            continue
        name = (
            b.subtype.split("_")[0]
            if b.subtype.split("_")[0] in ASCII_OUTPUTS
            else b.subtype
        )
        if name in ASCII_OUTPUTS or name.startswith("BINARY_"):
            for r in b.records():
                outputs[name] = Output(
                    name,
                    float(r.get("dt", 0.0)),
                    int(r.get("binary", 0)) if name in ASCII_OUTPUTS else 2,
                    b.where(),
                )
    nodes_, nsets = [], []
    for b in deck.find("DATABASE_HISTORY_NODE*"):
        for r in b.records():
            if "SET" in b.options:
                nsets += [int(v) for row in r.rows for v in row.values() if v]
            elif "ID" in b.options:
                nodes_.append(record_id(r, "id", "node"))
            else:
                nodes_ += [int(v) for row in r.rows for v in row.values() if v]
    sections: list[str] = []
    for b in deck.find("DATABASE_CROSS_SECTION_*"):
        for i, r in enumerate(b.records()):
            sid = r.get("csid") or len(sections) + 1
            title = r.get("title", "") or ""
            sections.append(f"{sid}" + (f" {title}" if title else ""))
    title = deck.info.title
    return LoadCase(
        title,
        us,
        float(term.get("endtim", 0.0)) if term is not None else 0.0,
        float((ts.get("tssfac", 0.0) if ts is not None else 0.0) or 0.9),
        float(ts.get("dt2ms", 0.0)) if ts is not None else 0.0,
        {k: int(en.get(k, 0)) for k in ("hgen", "rwen", "slnten", "rylen")}
        if en is not None
        else {},
        {"ihq": hg.get("ihq", 0), "qh": hg.get("qh", 0.0)} if hg is not None else {},
        tuple(velocities),
        tuple(speeds),
        tuple(walls),
        tuple(motions),
        tuple(gravity),
        tuple(contacts),
        outputs,
        tuple(nodes_),
        tuple(nsets),
        tuple(sections),
        implicit,
        tuple(notes),
    )


# --- What the analyses need ---------------------------------------------------

ANALYSES: dict[str, str] = {
    "quality": "model quality and energy checks (crashmetrics.quality, .energy_check)",
    "load_paths": "load paths and energy across runs (crashmetrics.loadpath)",
    "spot_welds": "spot weld failure (crashmetrics.spotweld)",
    "nodes": "head and dummy criteria, intrusions and pulses from nodout "
    "(crashmetrics.pedestrian.clearance, .intrusion, .pulse)",
    "contacts": "contact forces (rcforc)",
    "walls": "rigid wall forces (rwforc)",
}
"""Analyses `output_requirements` checks for."""


def output_requirements(
    deck: Deck,
    analyses: Sequence[str] = tuple(ANALYSES),
    *,
    unit_system: str | None = None,
    cfc: float = 1000.0,
) -> DeckSheet:
    """Does the deck write what these analyses read? (keys of `ANALYSES`)

    ``cfc``: filter class of the node channels; the nodout interval must
    give at least 10 samples per CFC cutoff (CFC 1000: 0.1 ms, 10 kHz).
    """
    unknown = [a for a in analyses if a not in ANALYSES]
    if unknown:
        raise ValueError(f"Unknown analyses {unknown}; known: {list(ANALYSES)}.")
    lc = load_case(deck, unit_system)
    tf = UNIT_SYSTEMS[lc.unit_system][1] if lc.unit_system else None
    checks: list[DeckCheck] = []
    add = checks.append

    def need(group: str, name: str, why: str) -> Output | None:
        o = lc.outputs.get(name)
        if o is None or o.dt <= 0:
            add(
                DeckCheck(
                    group,
                    name.lower(),
                    "FAIL",
                    f"not written; add *DATABASE_{name} ({why})",
                )
            )
            return None
        if not o.ascii:
            add(
                DeckCheck(
                    group,
                    name.lower(),
                    "WARN",
                    f"written to binout only (BINARY 2); set BINARY 3 or convert "
                    f"binout to ASCII before reading ({o.where})",
                )
            )
            return o
        add(DeckCheck(group, name.lower(), "PASS", f"every {lc._t(o.dt)} ({o.where})"))
        return o

    if not lc.end_time:
        add(
            DeckCheck(
                "Run", "End time", "FAIL", "*CONTROL_TERMINATION missing or ENDTIM 0"
            )
        )
    if "quality" in analyses:
        g = "Model quality"
        need(g, "GLSTAT", "energies, added mass, time step")
        need(g, "MATSUM", "part energies")
        if lc.contacts:
            need(g, "SLEOUT", "contact energies")
        e = lc.energy
        if not e:
            add(
                DeckCheck(
                    g,
                    "control_energy",
                    "FAIL",
                    "no *CONTROL_ENERGY: hourglass, "
                    "contact and rigid wall energies are not computed; add it with "
                    "HGEN 2, RWEN 2, SLNTEN 2",
                )
            )
        else:
            for k, why in (
                ("hgen", "hourglass energy"),
                ("slnten", "contact energy"),
                ("rwen", "rigid wall energy"),
            ):
                if k == "rwen" and not lc.walls:
                    continue
                ok = e.get(k) == 2
                add(
                    DeckCheck(
                        g,
                        f"control_energy {k}",
                        "PASS" if ok else "FAIL",
                        f"{k.upper()} {e.get(k)}"
                        + ("" if ok else f": set 2 to compute the {why}"),
                    )
                )
    if "load_paths" in analyses:
        g = "Load paths"
        need(g, "MATSUM", "part energies")
        need(g, "SECFORC", "section forces")
        add(
            DeckCheck(
                g,
                "cross sections",
                "PASS" if lc.cross_sections else "FAIL",
                f"{len(lc.cross_sections)} defined"
                if lc.cross_sections
                else "none: add a *DATABASE_CROSS_SECTION_PLANE or _SET per load path",
            )
        )
    if "spot_welds" in analyses:
        g = "Spot welds"
        need(g, "SWFORC", "spot weld forces")
    if "nodes" in analyses:
        g = "Node channels"
        o = need(g, "NODOUT", "node motion")
        has = bool(lc.history_nodes or lc.history_node_sets)
        add(
            DeckCheck(
                g,
                "history nodes",
                "PASS" if has else "FAIL",
                f"{len(lc.history_nodes)} nodes, {len(lc.history_node_sets)} node sets"
                if has
                else "none: add *DATABASE_HISTORY_NODE",
            )
        )
        if o is not None and tf is not None:
            limit = 1000.0 / (10 * cfc)  # ms
            dt_ms = o.dt * tf
            add(
                DeckCheck(
                    g,
                    "nodout sampling",
                    "PASS" if dt_ms <= limit * 1.0001 else "FAIL",
                    f"{dt_ms:.4g} ms ({1 / dt_ms:.3g} kHz); CFC {cfc:g} needs "
                    f"{limit:.3g} ms or less",
                )
            )
        elif o is not None:
            add(
                DeckCheck(
                    g,
                    "nodout sampling",
                    "WARN",
                    "unit system unknown; give unit_system to check the interval",
                )
            )
    if "contacts" in analyses and lc.contacts:
        need("Contacts", "RCFORC", "contact forces")
    if "walls" in analyses and lc.walls:
        need("Rigid walls", "RWFORC", "rigid wall forces")
    if lc.end_time and tf is not None:
        for o in lc.outputs.values():
            if o.dt > lc.end_time:
                add(
                    DeckCheck(
                        "Run",
                        f"{o.name.lower()} interval",
                        "WARN",
                        f"{lc._t(o.dt)} is longer than the run ({lc._t(lc.end_time)})",
                    )
                )
    return DeckSheet(f"{deck.main.name}: outputs", tuple(checks))
