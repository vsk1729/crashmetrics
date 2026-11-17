"""Card layouts of keywords, and the one generic reader that uses them.

Each keyword is described as data (`Spec`): its cards, the fields of each
card (name, type, what an ID refers to, width), whether a title line or
an ID card comes first, whether its records repeat, which cards an
option adds, and the rows of a list that follows. `read_records` reads
any keyword from its `Spec`; `spec_for` finds the `Spec` of a keyword
name, with its options.

Field syntax: ``name:type:ref/width``; type ``i`` (integer), ``f``
(real, the default) or ``s`` (text); ``ref`` is what the ID refers to
(``node``, ``part``, ``set_part`` ...); width defaults to 10 (20 in long
format). A field called ``_`` is skipped.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from crashmetrics.deck._fields import (
    Slot,
    format_value,
    is_param,
    param_name,
    replace_field,
    split_line,
    to_float,
    to_int,
)

__all__ = [
    "ASCII_OUTPUTS",
    "MATERIAL_NAMES",
    "Card",
    "Field",
    "Record",
    "Spec",
    "read_records",
    "spec_for",
]


# --- Description --------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "f"
    ref: str = ""
    width: int = 10


def _fields(text: str) -> tuple[Field, ...]:
    out = []
    for token in text.split():
        width = 10
        if "/" in token:
            token, w = token.split("/")
            width = int(w)
        parts = token.split(":")
        name = parts[0]
        kind = parts[1] if len(parts) > 1 and parts[1] else "f"
        ref = parts[2] if len(parts) > 2 else ""
        out.append(Field(name, kind, ref, width))
    return tuple(out)


@dataclass(frozen=True)
class Card:
    """One card (line). ``count`` gives how many such lines (values
    collected into the list ``name``) from the values read so far;
    ``when`` whether the card is present; ``optional`` that it is read
    only if the block has lines left."""

    fields: tuple[Field, ...]
    when: Callable[[Mapping[str, Any]], bool] | None = None
    count: Callable[[Mapping[str, Any]], int] | None = None
    name: str = ""
    optional: bool = False


def card(text: str, **kw: Any) -> Card:
    return Card(_fields(text), **kw)


@dataclass(frozen=True)
class Spec:
    """How a keyword's data lines are laid out."""

    cards: tuple[Card, ...]
    title: str = ""
    """``"always"``: a title line starts each record; ``"option"``: only
    with the ``_TITLE`` option."""
    id_card: str = ""
    """Field text of an ID card that starts each record with the ``_ID``
    or ``_TITLE`` option (contacts, rigid walls, cross sections ...)."""
    repeat: bool = False
    """Records repeat until the block ends."""
    rows: tuple[Field, ...] = ()
    """A list of rows after the cards, until the block ends."""
    option_cards: tuple[tuple[str, tuple[Card, ...]], ...] = ()
    """Cards that an option adds after the cards, in this order."""
    defines: tuple[str, str] = ("", "")
    """(namespace, field) of the ID a record defines, e.g. ("part", "pid")."""
    note: str = ""
    mpp: bool = False
    """With the ``_MPP`` option, one or two MPP cards come before the
    cards (the second starts with ``&``); they are skipped."""


def spec(
    cards: Sequence[Card] | str,
    *,
    rows: str = "",
    option_cards: Mapping[str, Sequence[Card]] | None = None,
    **kw: Any,
) -> Spec:
    if isinstance(cards, str):
        cards = [card(cards)]
    oc = tuple((k, tuple(v)) for k, v in (option_cards or {}).items())
    return Spec(tuple(cards), rows=_fields(rows) if rows else (), option_cards=oc, **kw)


# --- Records ------------------------------------------------------------------


@dataclass
class Record:
    """One record of a keyword: its values, and where each value is
    written so it can be changed in place."""

    block: Any
    index: int
    values: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    slots: dict[str, tuple[int, Slot, str]] = field(default_factory=dict)
    """Field -> (line number in the block, slot, type)."""
    params: dict[str, str] = field(default_factory=dict)
    """Field -> parameter name, for values given as ``&name``."""
    title_line: int = -1

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def __contains__(self, name: str) -> bool:
        return name in self.values

    def set(self, name: str, value: Any) -> None:
        """Change a value in the deck text (its field keeps its format).
        A value given by a parameter cannot be changed here; change the
        parameter (`crashmetrics.deck.set_parameter`)."""
        if name not in self.slots:
            raise KeyError(
                f"{name!r} is not a field of this {self.block.keyword} card "
                f"(fields: {list(self.slots)})."
            )
        if name in self.params:
            raise ValueError(
                f"{name} of this {self.block.keyword} is the parameter "
                f"&{self.params[name]}; change the parameter instead."
            )
        line_no, slot, kind = self.slots[name]
        line = self.block.lines[line_no]
        width = slot.width if not slot.comma else 20
        text = format_value(value, width, kind)
        self.block.set_line(line_no, replace_field(line, slot, text))
        self.values[name] = (
            int(value) if kind == "i" else (str(value) if kind == "s" else float(value))
        )

    def set_title(self, title: str) -> None:
        if self.title_line < 0:
            raise ValueError(f"This {self.block.keyword} record has no title line.")
        self.block.set_line(self.title_line, title[:80])
        self.title = title[:80]


def _value(text: str, kind: str, resolve: Callable[[str], Any]) -> tuple[Any, str]:
    if is_param(text):
        name = param_name(text)
        v = resolve(name)
        if kind == "s":
            return str(v), name
        sign = -1 if text.strip().startswith("-") else 1
        num = float(v) * sign
        return (int(num) if kind == "i" else num), name
    if kind == "i":
        return to_int(text), ""
    if kind == "s":
        return text.strip(), ""
    return to_float(text), ""


def _read_card(
    rec: Record,
    c: Card,
    line_no: int,
    line: str,
    long: bool,
    resolve: Callable[[str], Any],
    errors: list[str],
) -> dict[str, Any]:
    widths = [max(f.width, 20) if long and f.kind != "s" else f.width for f in c.fields]
    out: dict[str, Any] = {}
    for f, (text, slot) in zip(c.fields, split_line(line, widths)):
        if f.name == "_":
            continue
        try:
            v, pname = _value(text, f.kind, resolve)
        except (ValueError, KeyError) as exc:
            errors.append(f"{rec.block.where(line_no)}: {f.name} = {text!r}: {exc}")
            v, pname = (0 if f.kind == "i" else ("" if f.kind == "s" else 0.0)), ""
        out[f.name] = v
        rec.slots[f.name] = (line_no, slot, f.kind)
        if pname:
            rec.params[f.name] = pname
    return out


def read_records(
    block: Any, sp: Spec, resolve: Callable[[str], Any], errors: list[str]
) -> list[Record]:
    """The records of a block, read with its spec."""
    lines = block.data_lines()
    long = block.long
    options = block.options
    pos = 0
    records: list[Record] = []
    while pos < len(lines):
        rec = Record(block, len(records))
        if sp.title == "always" or (sp.title == "option" and "TITLE" in options):
            rec.title_line, text = lines[pos]
            rec.title = text.strip()
            pos += 1
        if sp.id_card and ("ID" in options or "TITLE" in options) and pos < len(lines):
            n, text = lines[pos]
            rec.values.update(
                _read_card(rec, card(sp.id_card), n, text, long, resolve, errors)
            )
            pos += 1
        if sp.mpp and "MPP" in options and pos < len(lines):
            pos += 1
            if pos < len(lines) and lines[pos][1].lstrip().startswith("&"):
                pos += 1
        cards = list(sp.cards)
        for opt, extra in sp.option_cards:
            if opt in options:
                cards.extend(extra)
        for c in cards:
            if c.when is not None and not c.when(rec.values):
                continue
            count = c.count(rec.values) if c.count else 1
            if c.optional and pos >= len(lines):
                break
            collected: list[Any] = []
            for _ in range(count):
                if pos >= len(lines):
                    break
                n, text = lines[pos]
                vals = _read_card(rec, c, n, text, long, resolve, errors)
                if c.name:
                    collected.extend(vals.values())
                else:
                    rec.values.update(vals)
                pos += 1
            if c.name:
                rec.values[c.name] = collected
        if sp.rows:
            while pos < len(lines):
                n, text = lines[pos]
                tmp = Record(block, -1)
                rec.rows.append(
                    _read_card(tmp, Card(sp.rows), n, text, long, resolve, errors)
                )
                pos += 1
        records.append(rec)
        if not sp.repeat:
            break
    if pos < len(lines) and not sp.rows:
        block.extra_lines = len(lines) - pos
    return records


# --- The keyword table --------------------------------------------------------

ASCII_OUTPUTS = (
    "ABSTAT",
    "BNDOUT",
    "CURVOUT",
    "DCFAIL",
    "DEFGEO",
    "DEFORC",
    "DEMASSFLOW",
    "ELOUT",
    "GCEOUT",
    "GLSTAT",
    "JNTFORC",
    "MATSUM",
    "NCFORC",
    "NODFOR",
    "NODOUT",
    "PLLYOUT",
    "PRTUBE",
    "RBDOUT",
    "RCFORC",
    "RWFORC",
    "SBTOUT",
    "SECFORC",
    "SLEOUT",
    "SPCFORC",
    "SPHOUT",
    "SSSTAT",
    "SWFORC",
    "TPRINT",
    "TRHIST",
)
"""``*DATABASE_<name>`` keywords that write an ASCII output file."""

MATERIAL_NAMES: dict[str, str] = {
    "001": "ELASTIC",
    "003": "PLASTIC_KINEMATIC",
    "009": "NULL",
    "020": "RIGID",
    "024": "PIECEWISE_LINEAR_PLASTICITY",
    "027": "MOONEY-RIVLIN_RUBBER",
    "036": "3-PARAMETER_BARLAT",
    "037": "TRANSVERSELY_ANISOTROPIC_ELASTIC_PLASTIC",
    "054": "ENHANCED_COMPOSITE_DAMAGE",
    "057": "LOW_DENSITY_FOAM",
    "063": "CRUSHABLE_FOAM",
    "077": "HYPERELASTIC_RUBBER",
    "081": "PLASTICITY_WITH_DAMAGE",
    "083": "FU_CHANG_FOAM",
    "089": "PLASTICITY_POLYMER",
    "098": "SIMPLIFIED_JOHNSON_COOK",
    "100": "SPOTWELD",
    "123": "MODIFIED_PIECEWISE_LINEAR_PLASTICITY",
    "124": "PLASTICITY_COMPRESSION_TENSION",
    "181": "SIMPLIFIED_RUBBER/FOAM",
    "187": "SAMP-1",
    "251": "TAILORED_PROPERTIES",
    "S01": "SPRING_ELASTIC",
    "S02": "DAMPER_VISCOUS",
    "B01": "SEATBELT",
}
"""Material numbers -> names of the common crash materials."""

_ELASTIC = {
    "001",
    "003",
    "020",
    "024",
    "036",
    "037",
    "063",
    "081",
    "089",
    "098",
    "100",
    "123",
    "124",
    "251",
}
"""Materials whose first card is MID RO E PR."""

_NAME_TO_NUMBER = {v: k for k, v in MATERIAL_NAMES.items()}


def material_number(name: str) -> str:
    """``"024"`` for ``PIECEWISE_LINEAR_PLASTICITY``, ``024`` or
    ``024_LOG_INTERPOLATION``; ``""`` when not known."""
    n = name.upper()
    m = re.match(r"^([0-9]{3}|[SB][0-9]{2})(?:_|$)", n)
    if m:
        return m.group(1)
    best = ""
    for full, number in _NAME_TO_NUMBER.items():
        if (n == full or n.startswith(full + "_")) and len(full) > len(best):
            best = full
    return _NAME_TO_NUMBER.get(best, "")


_SETS = {
    "PART": "part",
    "NODE": "node",
    "SHELL": "shell",
    "SOLID": "solid",
    "BEAM": "beam",
    "TSHELL": "tshell",
    "DISCRETE": "discrete",
    "SEGMENT": "segment",
}

_CONTACT_SIMPLE = re.compile(
    r"^(AUTOMATIC_(SINGLE_SURFACE|SURFACE_TO_SURFACE|NODES_TO_SURFACE|GENERAL|BEAMS_TO_SURFACE|ONE_WAY_SURFACE_TO_SURFACE)"
    r"|SURFACE_TO_SURFACE|NODES_TO_SURFACE|SINGLE_SURFACE|ONE_WAY_SURFACE_TO_SURFACE"
    r"|ERODING_(SINGLE_SURFACE|SURFACE_TO_SURFACE|NODES_TO_SURFACE))$"
)

_SPEC_PART = spec(
    [
        card(
            "pid:i secid:i:section mid:i:material eosid:i:eos hgid:i:hourglass"
            " grav:i adpopt:i tmid:i:thmat"
        )
    ],
    title="always",
    repeat=True,
    defines=("part", "pid"),
    option_cards={
        "INERTIA": [
            card("xc yc zc tm ircs:i nodeid:i:node"),
            card("ixx ixy ixz iyy iyz izz"),
            card("vtx vty vtz vrx vry vrz"),
            card(
                "xl yl zl xlip ylip zlip cid:i:coord", when=lambda v: v.get("ircs") == 1
            ),
        ],
        "CONTACT": [card("fs fd dc vc optt sft ssf cparm8")],
        "PRINT": [card("prbf:i")],
    },
)
_PART_OPTIONS = {"INERTIA", "CONTACT", "PRINT", "TITLE"}

_SECTION = {
    "SHELL": spec(
        [
            card("secid:i elform:i shrf nip:i propt qr_irid:i icomp:i setyp:i"),
            card("t1 t2 t3 t4 nloc marea idof edgset:i"),
            card(
                "b1 b2 b3 b4 b5 b6 b7 b8",
                name="angles",
                when=lambda v: v.get("icomp") == 1,
                count=lambda v: math.ceil(max(v.get("nip", 0) or 2, 1) / 8),
            ),
        ],
        title="option",
        repeat=True,
        defines=("section", "secid"),
    ),
    "SOLID": spec(
        "secid:i elform:i aet:i _ _ _ cohoff gaskett",
        title="option",
        repeat=True,
        defines=("section", "secid"),
    ),
    "TSHELL": spec(
        [
            card("secid:i elform:i shrf nip:i propt qr:i icomp:i tshear:i"),
            card(
                "b1 b2 b3 b4 b5 b6 b7 b8",
                name="angles",
                when=lambda v: v.get("icomp") == 1,
                count=lambda v: math.ceil(max(v.get("nip", 0) or 2, 1) / 8),
            ),
        ],
        title="option",
        repeat=True,
        defines=("section", "secid"),
    ),
    "BEAM": spec(
        [
            card("secid:i elform:i shrf qr_irid:i cst:i scoor nsm naupd:i"),
            card("c1 c2 c3 c4 c5 c6 c7 c8", name="geometry"),
        ],
        title="option",
        repeat=True,
        defines=("section", "secid"),
    ),
    "DISCRETE": spec(
        [card("secid:i dro:i kd v0 cl fd"), card("cdl tdl")],
        title="option",
        repeat=True,
        defines=("section", "secid"),
    ),
    "SEATBELT": spec(
        "secid:i area thick", title="option", repeat=True, defines=("section", "secid")
    ),
}

_CONTROL: dict[str, str | list[Card]] = {
    "TERMINATION": "endtim endcyc:i dtmin endeng endmas nosol:i",
    "TIMESTEP": [
        card("dtinit tssfac isdo:i tslimt dt2ms lctm:i:curve erode:i ms1st:i"),
        card(
            "dt2msf dt2mslc:i:curve imscl:i:set_part _ _ rmscl emscl ihdo:i",
            optional=True,
        ),
    ],
    "ENERGY": "hgen:i rwen:i slnten:i rylen:i irgen:i maten:i drlen:i disen:i",
    "HOURGLASS": "ihq:i qh",
    "SHELL": "wrpang esort:i irnxx:i istupd:i theory:i bwc:i miter:i proj:i",
    "CONTACT": "slsfac rwpnal islchk:i shlthk:i penopt:i thkchg:i orien:i enmass:i",
    "ACCURACY": "osu:i inn:i pidosu:i:set_part iacc:i exacc",
    "BULK_VISCOSITY": "q1 q2 type:i btype:i tstype:i",
    "SOLID": "esort:i fmatrix:i niptets:i swlocl:i psfail:i:set_part t10jtol icoh:i"
    " tet13k:i",
    "OUTPUT": "npopt:i neecho:i nrefup:i iaccop:i opifs ipnint:i ikedit:i iflush:i",
    "UNITS": "length:s mass:s time:s temp:s",
    "IMPLICIT_GENERAL": "imflag:i dt0 imform:i nsbs:i igs:i cnstn:i form:i zero_v:i",
    "DYNAMIC_RELAXATION": "nrcyck:i drtol drfctr drterm tssfdr irelal:i edttl idrflg:i",
}

_HISTORY = {
    "NODE": "node",
    "SHELL": "shell",
    "SOLID": "solid",
    "BEAM": "beam",
    "TSHELL": "tshell",
    "DISCRETE": "discrete",
    "SEATBELT": "seatbelt",
}


def _ids_card(ref: str, width: int = 10) -> str:
    return " ".join(f"id{i}:i:{ref}/{width}" for i in range(1, 9))


def spec_for(keyword: str) -> tuple[Spec | None, str, str, frozenset[str]]:
    """(spec, family, subtype, options) of a keyword name (without ``*``);
    spec is None for keywords that are read by special readers or not
    interpreted."""
    k = keyword.upper()
    parts = k.split("_")
    opts: set[str] = set()

    # Parts
    if k == "PART" or (parts[0] == "PART" and set(parts[1:]) <= _PART_OPTIONS):
        return _SPEC_PART, "PART", "", frozenset(parts[1:])
    if k.startswith("PART_COMPOSITE"):
        sp = spec(
            [card("pid:i elform:i shrf nloc marea hgid:i:hourglass adpopt:i thshel:i")],
            title="always",
            rows="mid1:i:material thick1 b1 tmid1:i mid2:i:material thick2 b2 tmid2:i",
            defines=("part", "pid"),
        )
        return sp, "PART_COMPOSITE", "", frozenset(parts[2:])

    # Sections, materials, EOS, hourglass
    if parts[0] == "SECTION" and len(parts) > 1:
        sub = parts[1]
        opts = set(parts[2:])
        sp_ = _SECTION.get(sub)
        if sp_ is not None:
            return sp_, "SECTION", sub, frozenset(opts)
        return (
            spec("secid:i", title="option", defines=("section", "secid")),
            "SECTION",
            sub,
            frozenset(opts),
        )
    if parts[0] == "MAT" and len(parts) > 1:
        if parts[1] in ("ADD", "THERMAL"):
            ns = "thmat" if parts[1] == "THERMAL" else "matadd"
            title_opt = parts[-1] == "TITLE"
            return (
                spec("mid:i", title="option", defines=(ns, "mid")),
                "MAT_" + parts[1],
                "_".join(parts[2:-1] if title_opt else parts[2:]),
                frozenset({"TITLE"} if title_opt else set()),
            )
        title_opt = parts[-1] == "TITLE"
        name = "_".join(parts[1:-1] if title_opt else parts[1:])
        num = material_number(name)
        first = "mid:i ro e pr" if num in _ELASTIC else "mid:i ro"
        cards = [card(first)]
        if num in ("024", "123"):
            cards.append(card("c p lcss:i:curve lcsr:i:curve vp", optional=True))
        return (
            spec(cards, title="option", defines=("material", "mid")),
            "MAT",
            num or name,
            frozenset({"TITLE"} if title_opt else set()),
        )
    if parts[0] == "EOS":
        title_opt = parts[-1] == "TITLE"
        return (
            spec("eosid:i", title="option", defines=("eos", "eosid")),
            "EOS",
            "_".join(parts[1:]),
            frozenset({"TITLE"} if title_opt else set()),
        )
    if parts[0] == "HOURGLASS":
        return (
            spec(
                "hgid:i ihq:i qm ibq:i q1 q2 qb qw",
                title="option",
                repeat=True,
                defines=("hourglass", "hgid"),
            ),
            "HOURGLASS",
            "",
            frozenset(parts[1:]),
        )

    # Sets
    if parts[0] == "SET" and len(parts) > 1 and parts[1] in _SETS:
        return None, "SET", parts[1], frozenset(parts[2:])

    # Contacts
    if parts[0] == "CONTACT" and parts[1:2] == ["2D"]:
        return None, "CONTACT", "_".join(parts[1:]), frozenset()
    if parts[0] == "CONTACT":
        rest = [p for p in parts[1:] if p not in ("ID", "TITLE", "MPP")]
        opts = {p for p in parts[1:] if p in ("ID", "TITLE", "MPP")}
        sub = "_".join(rest)
        cards = [
            card("ssid:i msid:i sstyp:i mstyp:i sboxid:i:box mboxid:i:box spr:i mpr:i"),
            card("fs fd dc vc vdc penchk:i bt dt"),
            card("sfs sfm sst mst sfst sfmt fsf vsf"),
        ]
        if _CONTACT_SIMPLE.match(sub):
            cards.append(
                card(
                    "soft:i sofscl lcidab:i:curve maxpar sbopt depth:i bsort:i"
                    " frcfrq:i",
                    optional=True,
                )
            )
        return (
            spec(
                cards,
                id_card="cid:i heading:s/70",
                defines=("contact", "cid"),
                mpp=True,
            ),
            "CONTACT",
            sub,
            frozenset(opts),
        )

    # Constraints
    if parts[0] == "CONSTRAINED" and len(parts) > 1:
        sub = "_".join(parts[1:])
        if sub.startswith("SPOTWELD"):
            o = frozenset(p for p in parts[2:] if p in ("ID",))
            cards = [card("wid:i", when=lambda v, o=o: "ID" in o)] if o else []
            cards.append(card("n1:i:node n2:i:node sn ss n m tf ep"))
            return spec(cards, repeat=True), "CONSTRAINED", "SPOTWELD", o
        if sub.startswith("NODAL_RIGID_BODY"):
            return (
                spec(
                    "pid:i cid:i:coord nsid:i:set_node pnode:i:node iprt:i drflag:i"
                    " rrflag:i",
                    title="option" if "TITLE" in parts else "",
                    repeat="INERTIA" not in parts,
                ),
                "CONSTRAINED",
                "NODAL_RIGID_BODY",
                frozenset(parts[4:]),
            )
        if sub.startswith("EXTRA_NODES_NODE"):
            return (
                spec("pid:i:part nid:i:node iflag:i", repeat=True),
                "CONSTRAINED",
                "EXTRA_NODES_NODE",
                frozenset(),
            )
        if sub.startswith("EXTRA_NODES_SET"):
            return (
                spec("pid:i:part nsid:i:set_node iflag:i", repeat=True),
                "CONSTRAINED",
                "EXTRA_NODES_SET",
                frozenset(),
            )
        if sub.startswith("RIGID_BODIES"):
            return (
                spec("pidl:i:part pidc:i:part iflag:i", repeat=True),
                "CONSTRAINED",
                "RIGID_BODIES",
                frozenset(),
            )
        if sub.startswith("INTERPOLATION_SPOTWELD"):
            return (
                spec(
                    "pid1:i:part pid2:i:part nsid:i:set_node thick r stiff alpha1"
                    " model:i",
                    note="first card only",
                ),
                "CONSTRAINED",
                "INTERPOLATION_SPOTWELD",
                frozenset(),
            )
        return None, "CONSTRAINED", sub, frozenset()

    # Initial conditions
    if k == "INITIAL_VELOCITY_GENERATION" or k.startswith(
        "INITIAL_VELOCITY_GENERATION_"
    ):
        return (
            spec(
                [
                    card("id:i styp:i omega vx vy vz ivatn:i icid:i:coord"),
                    card("xc yc zc nx ny nz phase:i irigid:i"),
                ],
                repeat=True,
            ),
            "INITIAL",
            "VELOCITY_GENERATION",
            frozenset(parts[3:]),
        )
    if k == "INITIAL_VELOCITY":
        return (
            spec(
                [
                    card(
                        "nsid:i:set_node nsidex:i:set_node boxid:i:box irigid:i"
                        " icid:i:coord"
                    ),
                    card("vx vy vz vxr vyr vzr"),
                    card(
                        "vxe vye vze vxre vyre vzre",
                        when=lambda v: v.get("nsidex", 0) > 0,
                    ),
                ],
                repeat=True,
            ),
            "INITIAL",
            "VELOCITY",
            frozenset(),
        )
    if k == "INITIAL_VELOCITY_NODE":
        return (
            spec("nid:i:node vx vy vz vxr vyr vzr icid:i:coord", repeat=True),
            "INITIAL",
            "VELOCITY_NODE",
            frozenset(),
        )
    if k == "INITIAL_VELOCITY_RIGID_BODY":
        return (
            spec("pid:i:part vx vy vz vxr vyr vzr icid:i:coord", repeat=True),
            "INITIAL",
            "VELOCITY_RIGID_BODY",
            frozenset(),
        )

    # Rigid walls
    if parts[0] == "RIGIDWALL":
        sub = "_".join(p for p in parts[1:] if p not in ("ID", "TITLE"))
        o = frozenset(p for p in parts[1:])
        if parts[1:2] == ["PLANAR"]:
            sp = spec(
                [
                    card(
                        "nsid:i:set_node nsidex:i:set_node boxid:i:box offset birth"
                        " death rwksf"
                    ),
                    card("xt yt zt xh yh zh fric wvel"),
                ],
                id_card="rwid:i heading:s/70",
                option_cards={
                    "FINITE": [card("xhev yhev zhev lenl lenm")],
                    "MOVING": [card("mass v0")],
                },
                note="ORTHO and FORCES cards not read"
                if {"ORTHO", "FORCES"} & o
                else "",
            )
            return sp, "RIGIDWALL", sub, o
        return (
            spec(
                [card("nsid:i:set_node nsidex:i:set_node boxid:i:box birth death")],
                id_card="rwid:i heading:s/70",
            ),
            "RIGIDWALL",
            sub,
            o,
        )

    # Boundary conditions and loads
    if k.startswith("BOUNDARY_SPC_NODE") or k.startswith("BOUNDARY_SPC_SET"):
        ref = "node" if "NODE" in parts[2] else "set_node"
        return (
            spec(
                f"id:i:{ref} cid:i:coord dofx:i dofy:i dofz:i dofrx:i dofry:i dofrz:i",
                id_card="bcid:i heading:s/70",
                repeat=True,
            ),
            "BOUNDARY",
            "SPC_" + parts[2],
            frozenset(parts[3:]),
        )
    if k.startswith("BOUNDARY_PRESCRIBED_MOTION_"):
        what = parts[3] if len(parts) > 3 else ""
        ref = {"NODE": "node", "SET": "set_node", "RIGID": "part"}.get(what, "")
        return (
            spec(
                f"id:i:{ref} dof:i vad:i lcid:i:curve sf vid:i:vector death birth",
                id_card="pmid:i heading:s/70",
                repeat=True,
            ),
            "BOUNDARY",
            "PRESCRIBED_MOTION_" + what,
            frozenset(parts[4:]),
        )
    if parts[0] == "LOAD" and len(parts) >= 3 and parts[1] == "BODY":
        if parts[2] in ("X", "Y", "Z", "RX", "RY", "RZ"):
            return (
                spec("lcid:i:curve sf lciddr:i:curve xc yc zc cid:i:coord"),
                "LOAD",
                "BODY_" + parts[2],
                frozenset(),
            )
        if parts[2] == "PARTS":
            return spec("psid:i:set_part"), "LOAD", "BODY_PARTS", frozenset()

    # Controls
    if parts[0] == "CONTROL":
        sub = "_".join(parts[1:])
        c = _CONTROL.get(sub)
        if c is not None:
            return spec(c), "CONTROL", sub, frozenset()
        return None, "CONTROL", sub, frozenset()

    # Outputs
    if parts[0] == "DATABASE" and len(parts) > 1:
        if parts[1] in ASCII_OUTPUTS:
            return (
                spec("dt binary:i lcur:i:curve ioopt:i"),
                "DATABASE",
                parts[1],
                frozenset(parts[2:]),
            )
        if parts[1] == "BINARY" and len(parts) > 2:
            cards = [card("dt lcdt:i beam:i npltc:i psetid:i:set_part")]
            if parts[2] == "D3PLOT":
                cards.append(
                    card(
                        "ioopt:i rate cutoff window type:i pset:i:set_part",
                        optional=True,
                    )
                )
            return spec(cards), "DATABASE", "BINARY_" + parts[2], frozenset(parts[3:])
        if parts[1] == "HISTORY" and len(parts) > 2 and parts[2] in _HISTORY:
            ref = _HISTORY[parts[2]]
            o = frozenset(parts[3:])
            if "ID" in o:
                return (
                    spec(f"id:i:{ref} heading:s/70", repeat=True),
                    "DATABASE",
                    "HISTORY_" + parts[2],
                    o,
                )
            if "SET" in o:
                return (
                    spec([], rows=_ids_card("set_" + ref)),
                    "DATABASE",
                    "HISTORY_" + parts[2],
                    o,
                )
            return spec([], rows=_ids_card(ref)), "DATABASE", "HISTORY_" + parts[2], o
        if parts[1:3] == ["CROSS", "SECTION"] and len(parts) > 3:
            o = frozenset(parts[4:])
            if parts[3] == "PLANE":
                return (
                    spec(
                        [
                            card("psid:i:set_part xct yct zct xch ych zch radius"),
                            card("xhev yhev zhev lenl lenm id:i itype:i"),
                        ],
                        id_card="csid:i title:s/70",
                        repeat=True,
                    ),
                    "DATABASE",
                    "CROSS_SECTION_PLANE",
                    o,
                )
            if parts[3] == "SET":
                return (
                    spec(
                        "nsid:i:set_node hsid:i:set_shell bsid:i:set_beam"
                        " ssid:i:set_solid tsid:i:set_tshell dsid:i:set_discrete"
                        " id:i itype:i",
                        id_card="csid:i title:s/70",
                        repeat=True,
                    ),
                    "DATABASE",
                    "CROSS_SECTION_SET",
                    o,
                )
        return None, "DATABASE", "_".join(parts[1:]), frozenset()

    # Definitions
    if parts[0] == "DEFINE" and len(parts) > 1:
        title_opt = "TITLE" in parts
        o = frozenset({"TITLE"} if title_opt else set())
        if parts[1] == "CURVE" and (len(parts) == 2 or parts[2] == "TITLE"):
            return None, "DEFINE", "CURVE", o
        if parts[1] == "TABLE" and (len(parts) == 2 or parts[2] == "TITLE"):
            return (
                spec(
                    "tbid:i sfa offa",
                    title="option",
                    rows="value/20",
                    defines=("curve", "tbid"),
                ),
                "DEFINE",
                "TABLE",
                o,
            )
        if parts[1:3] == ["COORDINATE", "SYSTEM"]:
            return (
                spec(
                    [card("cid:i xo yo zo xl yl zl cidl:i"), card("xp yp zp")],
                    title="option",
                    repeat=True,
                    defines=("coord", "cid"),
                ),
                "DEFINE",
                "COORDINATE_SYSTEM",
                o,
            )
        if parts[1:3] == ["COORDINATE", "NODES"]:
            return (
                spec(
                    "cid:i n1:i:node n2:i:node n3:i:node flag:i dir:s",
                    title="option",
                    repeat=True,
                    defines=("coord", "cid"),
                ),
                "DEFINE",
                "COORDINATE_NODES",
                o,
            )
        if parts[1:3] == ["COORDINATE", "VECTOR"]:
            return (
                spec(
                    "cid:i xx yx zx xv yv zv",
                    title="option",
                    repeat=True,
                    defines=("coord", "cid"),
                ),
                "DEFINE",
                "COORDINATE_VECTOR",
                o,
            )
        if parts[1] == "VECTOR" and len(parts) <= 3:
            return (
                spec(
                    "vid:i xt yt zt xh yh zh cid:i:coord",
                    title="option",
                    repeat=True,
                    defines=("vector", "vid"),
                ),
                "DEFINE",
                "VECTOR",
                o,
            )
        if parts[1] == "BOX" and len(parts) <= 3:
            return (
                spec(
                    "boxid:i xmn xmx ymn ymx zmn zmx",
                    title="option",
                    repeat=True,
                    defines=("box", "boxid"),
                ),
                "DEFINE",
                "BOX",
                o,
            )
        if parts[1] == "TRANSFORMATION":
            return (
                spec(
                    "tranid:i",
                    title="option",
                    rows="option:s a1 a2 a3 a4 a5 a6 a7",
                    defines=("transform", "tranid"),
                ),
                "DEFINE",
                "TRANSFORMATION",
                o,
            )
        return None, "DEFINE", "_".join(parts[1:]), o
    return None, parts[0], "_".join(parts[1:]), frozenset()


def references(sp: Spec) -> Iterator[tuple[str, str]]:
    """(field, namespace) of every ID field of a spec."""
    cards = list(sp.cards) + [c for _, cs in sp.option_cards for c in cs]
    for c in cards:
        for f in c.fields:
            if f.ref:
                yield f.name, f.ref
