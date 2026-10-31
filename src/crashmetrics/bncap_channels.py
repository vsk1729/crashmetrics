"""Bharat NCAP occupant inputs from dummy channels (AIS-197 2023).

Turns dummy time histories, from a test (for example ISO-MME) or from a
simulation, into the inputs of the Bharat NCAP scoring in one call:

- `frontal_occupant_from_channels`: Hybrid III 50th in the ODB frontal
  test -> `crashmetrics.bncap.FrontalOccupant`.
- `side_occupant_from_channels`: ES-2 in the MDB side test ->
  `crashmetrics.bncap.SideOccupant`, with the backplate and T12
  modifiers when those channels are given.
- `pole_test_from_channels`: ES-2 in the pole test -> pass / fail.
- `channels_from_isomme`: the named channels of one dummy from an
  ISO-MME test (`HYBRID3_ISOMME` codes from Euro NCAP CP 005; give your
  own patterns for other dummies), converted to the units below and
  filtered with the protocol CFC if they are not filtered yet.

Channels are given by name as ``{name: (time_s, values)}`` in the units
and with the filter classes of `FRONTAL_CHANNELS` and `SIDE_CHANNELS`.
With ``filtered=False`` (the default) each channel is filtered here with
its CFC, which needs uniform sampling (`crashmetrics.signals.
resample_uniform` first if needed). Channels used together (the three
head axes, the neck, the tibia loads of one location, the three ribs)
must share a time base.

Sign conventions are those of the rest of the package (see the units and
signs page): femur and tibia Fz compression negative, neck Fz tension
positive, Hybrid III chest deflection compression positive (set
``chest_compression_negative=True`` otherwise), knee slider negative in
compression, ES-2 rib deflections and abdominal forces positive in
loading.

Edition: AIS-197 of September 2023, for ratings from 1 October 2023 to
30 September 2027 (`crashmetrics.bncap.PROTOCOL`); every function takes
``edition=2023``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from crashmetrics.acceleration import clip_3ms
from crashmetrics.bncap import (
    EDITION,
    FrontalOccupant,
    SideOccupant,
    check_edition,
    pole_test_passed,
    side_modifiers,
)
from crashmetrics.isomme import IsoMmeTest
from crashmetrics.lower_extremity import (
    knee_slider_displacement,
    tibia_compression,
    tibia_index,
)
from crashmetrics.neck import neck_loads
from crashmetrics.pedestrian.hic import calculate_hic
from crashmetrics.side import (
    es2_abdominal_force,
    es2_rib_deflection,
    es2_rib_vc,
    pubic_symphysis_force,
)
from crashmetrics.signals import cfc_filter, resultant, to_g
from crashmetrics.thorax import chest_deflection, viscous_criterion

__all__ = [
    "FRONTAL_CHANNELS",
    "HEAD_CONTACT_PEAK",
    "HYBRID3_ISOMME",
    "SIDE_CHANNELS",
    "channels_from_isomme",
    "frontal_occupant_from_channels",
    "pole_test_from_channels",
    "side_occupant_from_channels",
]

Series = tuple[ArrayLike, ArrayLike]
"""(time in s, values) of one channel."""

FloatArray = NDArray[np.float64]

HEAD_CONTACT_PEAK = 80.0
"""Peak resultant head acceleration (g) above which a frontal head
contact is assumed when ``head_contact`` is not given (AIS-197 2023: no
hard contact if the peak is at most 80 g and there is no other
evidence)."""

_TIBIA = tuple(f"tibia_{leg}_{loc}_{c}" for leg in ("left", "right")
               for loc in ("upper", "lower") for c in ("mx", "my", "fz"))

FRONTAL_CHANNELS: dict[str, tuple[str, int]] = {
    "head_ax": ("g", 1000), "head_ay": ("g", 1000), "head_az": ("g", 1000),
    "neck_fx": ("N", 1000), "neck_fz": ("N", 1000), "neck_my": ("N m", 600),
    "chest_deflection": ("mm", 180),
    "femur_fz_left": ("N", 600), "femur_fz_right": ("N", 600),
    "knee_left": ("mm", 180), "knee_right": ("mm", 180),
    **{name: ("N" if name.endswith("fz") else "N m", 600) for name in _TIBIA},
}
"""Hybrid III 50th channels: name -> (unit, CFC). Tibia loads are needed
at the upper or the lower location (or both: the worse is used)."""

SIDE_CHANNELS: dict[str, tuple[str, int]] = {
    "head_ax": ("g", 1000), "head_ay": ("g", 1000), "head_az": ("g", 1000),
    "rib_upper": ("mm", 180), "rib_middle": ("mm", 180), "rib_lower": ("mm", 180),
    "abdomen_front": ("N", 600), "abdomen_middle": ("N", 600),
    "abdomen_rear": ("N", 600), "pubic_fy": ("N", 600),
    "backplate_fy": ("N", 600), "t12_fy": ("N", 600), "t12_mx": ("N m", 600),
}
"""ES-2 channels: name -> (unit, CFC). ``backplate_fy``, ``t12_fy`` and
``t12_mx`` are optional (they give the chest modifiers)."""

_SIDE_OPTIONAL = ("backplate_fy", "t12_fy", "t12_mx")

HYBRID3_ISOMME: dict[str, str] = {
    "head_ax": "HEAD0000H3ACX", "head_ay": "HEAD0000H3ACY",
    "head_az": "HEAD0000H3ACZ",
    "neck_fx": "NECKUP00H3FOX", "neck_fz": "NECKUP00H3FOZ",
    "neck_my": "NECKUP00H3MOY",
    "chest_deflection": "CHST????H3DSX",
    "femur_fz_left": "FEMRLE00H3FOZ", "femur_fz_right": "FEMRRI00H3FOZ",
    "knee_left": "KNSLLE00H3DSX", "knee_right": "KNSLRI00H3DSX",
    **{f"tibia_{leg}_{loc}_{c}":
       f"TIBI{leg[:2].upper()}{loc[:2].upper()}H3{'FO' if c == 'fz' else 'MO'}"
       f"{c[1].upper()}"
       for leg in ("left", "right") for loc in ("upper", "lower")
       for c in ("mx", "my", "fz")},
}
"""ISO-MME channel codes of the Hybrid III 50th (Euro NCAP CP 005),
characters 3 to 15: the test object, the seating position and the filter
class are added by `channels_from_isomme`. ``?`` matches any character
(chest deflection fine locations differ between labs)."""


# --- Helpers -----------------------------------------------------------------


def _series(channels: Mapping[str, Series], name: str) -> tuple[FloatArray,
                                                                 FloatArray]:
    if name not in channels:
        raise ValueError(f"Channel {name!r} is missing.")
    t, x = channels[name]
    return np.asarray(t, dtype=float), np.asarray(x, dtype=float)


def _group(channels: Mapping[str, Series], names: Sequence[str],
           table: Mapping[str, tuple[str, int]], filtered: bool
           ) -> tuple[FloatArray, list[FloatArray]]:
    """Channels sharing a time base, filtered with their CFC if needed."""
    t0, _ = _series(channels, names[0])
    out = []
    for name in names:
        t, x = _series(channels, name)
        if t.shape != t0.shape or not np.allclose(t, t0, rtol=0.0, atol=1e-9):
            raise ValueError(f"Channels {', '.join(names)} need the same time "
                             "base; resample them first.")
        if t.shape != x.shape:
            raise ValueError(f"Channel {name!r}: time and values differ in length.")
        out.append(x if filtered else cfc_filter(t, x, table[name][1]))
    return t0, out


def _head(t: FloatArray, axes: list[FloatArray]) -> tuple[float, float, float]:
    """HIC15, 3 ms clip and peak of the resultant head acceleration."""
    res = resultant(*axes)
    return (calculate_hic(t, res, window_ms=15.0).value, clip_3ms(t, res),
            float(np.max(res)))


# --- Frontal -----------------------------------------------------------------


def frontal_occupant_from_channels(
    channels: Mapping[str, Series],
    *,
    driver: bool = True,
    filtered: bool = False,
    head_contact: bool | None = None,
    pedal_rearward: float | None = None,
    modifiers: Mapping[str, float] | None = None,
    chest_compression_negative: bool = False,
    edition: int = EDITION,
) -> FrontalOccupant:
    """`FrontalOccupant` of a Hybrid III 50th from its channels.

    Calculates HIC15 and the 3 ms clip of the resultant head
    acceleration, the neck shear and tension histories and the extension
    moment at the occipital condyle, chest compression and VC, femur
    histories, knee slider displacements, and per leg the worst Tibia
    Index and tibia compression of the given locations.

    Parameters
    ----------
    channels:
        ``{name: (time_s, values)}`` with the names, units and CFCs of
        `FRONTAL_CHANNELS`.
    driver:
        False for the passenger (no pedal assessment).
    filtered:
        True if the channels are already filtered with their CFC.
    head_contact:
        Hard head contact. None: assumed if the peak resultant head
        acceleration exceeds `HEAD_CONTACT_PEAK` (80 g).
    pedal_rearward:
        Worst rearward pedal displacement, mm (driver).
    modifiers:
        Points per region, for example from
        `crashmetrics.bncap.frontal_modifiers`.
    chest_compression_negative:
        True if chest deflection is negative in compression.
    edition:
        Bharat NCAP edition (2023).

    Returns
    -------
    FrontalOccupant
        Ready for `crashmetrics.bncap.score_frontal`.
    """
    check_edition(edition)
    T = FRONTAL_CHANNELS
    t, axes = _group(channels, ("head_ax", "head_ay", "head_az"), T, filtered)
    hic15, a3ms, peak = _head(t, axes)
    contact = peak > HEAD_CONTACT_PEAK if head_contact is None else head_contact

    t_neck, (fx, fz, my) = _group(channels, ("neck_fx", "neck_fz", "neck_my"), T,
                                  filtered)
    extension = neck_loads(t_neck, fx, fz, my,
                           dummy="hybrid3").extension_moment.value

    t, (d,) = _group(channels, ("chest_deflection",), T, filtered)
    compression = chest_deflection(
        t, d, compression_negative=chest_compression_negative).value
    vc = viscous_criterion(t, d, dummy="hybrid3_50",
                           compression_negative=chest_compression_negative).value

    femur = []
    knee = []
    ti = []
    tf = []
    for leg in ("left", "right"):
        tt, (f,) = _group(channels, (f"femur_fz_{leg}",), T, filtered)
        femur.append((tt, f))
        tt, (k,) = _group(channels, (f"knee_{leg}",), T, filtered)
        knee.append(knee_slider_displacement(tt, k).value)
        index, force = [], []
        for loc in ("upper", "lower"):
            names = [f"tibia_{leg}_{loc}_{c}" for c in ("mx", "my", "fz")]
            present = [n in channels for n in names]
            if not any(present):
                continue
            if not all(present):
                raise ValueError(f"Give Mx, My and Fz for the {leg} {loc} tibia.")
            tt, (mx, my_, fz_) = _group(channels, names, T, filtered)
            index.append(tibia_index(tt, mx, my_, fz_, dummy="hybrid3_50").value)
            force.append(tibia_compression(tt, fz_).value)
        if not index:
            raise ValueError(f"Give the {leg} tibia loads (upper or lower).")
        ti.append(max(index))
        tf.append(max(force))

    return FrontalOccupant(
        neck_shear=(t_neck, fx),
        neck_tension=(t_neck, fz),
        neck_extension=extension,
        chest_compression=compression,
        viscous_criterion=vc,
        femur=(femur[0], femur[1]),
        knee_displacement=(knee[0], knee[1]),
        tibia_index=(ti[0], ti[1]),
        tibia_force=(tf[0], tf[1]),
        hic15=hic15,
        head_a3ms=a3ms,
        hard_contact=contact,
        pedal_rearward=pedal_rearward if driver else None,
        modifiers=dict(modifiers or {}),
    )


# --- Side and pole ------------------------------------------------------------


def _side_values(channels: Mapping[str, Series], filtered: bool
                 ) -> dict[str, float]:
    T = SIDE_CHANNELS
    t, axes = _group(channels, ("head_ax", "head_ay", "head_az"), T, filtered)
    hic15, a3ms, peak = _head(t, axes)
    t, (up, mid, low) = _group(channels, ("rib_upper", "rib_middle",
                                          "rib_lower"), T, filtered)
    t_a, (front, middle, rear) = _group(channels, ("abdomen_front",
                                                   "abdomen_middle",
                                                   "abdomen_rear"), T, filtered)
    t_p, (pub,) = _group(channels, ("pubic_fy",), T, filtered)
    return {
        "hic15": hic15, "head_a3ms": a3ms, "head_peak": peak,
        "rib_deflection": es2_rib_deflection(t, up, mid, low).value,
        "rib_vc": es2_rib_vc(t, up, mid, low).value,
        "abdominal_force": es2_abdominal_force(t_a, front, middle, rear).value,
        "pubic_force": pubic_symphysis_force(t_p, pub).value,
    }


def _peak_abs(channels: Mapping[str, Series], name: str, filtered: bool) -> float:
    _, (x,) = _group(channels, (name,), SIDE_CHANNELS, filtered)
    return float(np.max(np.abs(x)))


def side_occupant_from_channels(
    channels: Mapping[str, Series],
    *,
    filtered: bool = False,
    modifiers: Mapping[str, float] | None = None,
    edition: int = EDITION,
) -> SideOccupant:
    """`SideOccupant` of an ES-2 in the MDB side test from its channels.

    Calculates HIC15 and the 3 ms clip of the resultant head
    acceleration, the worst rib deflection and rib VC, the peak total
    abdominal force and the peak pubic symphysis force. If
    ``backplate_fy`` or ``t12_fy`` and ``t12_mx`` are given, their
    chest modifiers (`crashmetrics.bncap.side_modifiers`) are added to
    ``modifiers``.

    Parameters
    ----------
    channels:
        ``{name: (time_s, values)}`` with the names, units and CFCs of
        `SIDE_CHANNELS`.
    filtered:
        True if the channels are already filtered with their CFC.
    modifiers:
        Further points to subtract per region.
    edition:
        Bharat NCAP edition (2023).
    """
    check_edition(edition)
    v = _side_values(channels, filtered)
    has_t12 = "t12_fy" in channels or "t12_mx" in channels
    auto = side_modifiers(
        backplate_fy=(_peak_abs(channels, "backplate_fy", filtered)
                      if "backplate_fy" in channels else None),
        t12_fy=_peak_abs(channels, "t12_fy", filtered) if has_t12 else None,
        t12_mx=_peak_abs(channels, "t12_mx", filtered) if has_t12 else None,
        edition=edition,
    )
    combined = dict(modifiers or {})
    for region, points in auto.items():
        combined[region] = round(combined.get(region, 0.0) + points, 3)
    return SideOccupant(
        hic15=v["hic15"], head_a3ms=v["head_a3ms"],
        rib_deflection=v["rib_deflection"], rib_vc=v["rib_vc"],
        abdominal_force=v["abdominal_force"], pubic_force=v["pubic_force"],
        modifiers=combined,
    )


def pole_test_from_channels(
    channels: Mapping[str, Series],
    *,
    head_contact: bool,
    filtered: bool = False,
    edition: int = EDITION,
) -> bool:
    """Pole side test result (29 km/h, ES-2) from its channels, with
    `crashmetrics.bncap.pole_test_passed`: HIC15 < 700, peak head
    acceleration < 80 g, no head contact with the pole (``head_contact``,
    from the film), and rib, abdomen and pubic values below the side
    lower performance limits."""
    v = _side_values(channels, filtered)
    return pole_test_passed(v["hic15"], v["head_peak"], head_contact,
                            v["rib_deflection"], v["rib_vc"],
                            v["abdominal_force"], v["pubic_force"],
                            edition=edition)


# --- ISO-MME -----------------------------------------------------------------

_FORCE = {"N": 1.0, "KN": 1000.0, "DAN": 10.0}
_MOMENT = {"NM": 1.0, "N M": 1.0, "N*M": 1.0, "N.M": 1.0, "KNM": 1000.0,
           "KN*MM": 1.0, "KNMM": 1.0, "NMM": 0.001, "N*MM": 0.001}
_LENGTH = {"MM": 1.0, "M": 1000.0, "CM": 10.0}


def _convert(values: FloatArray, unit: str, target: str, name: str) -> FloatArray:
    u = re.sub(r"\s+", " ", unit.strip()).upper()
    if target == "g":
        text = unit.strip().replace("**", "^").replace(" ", "")
        if text.lower() in ("g", "g's", "gs"):
            return values
        return to_g(values, text)
    table = {"N": _FORCE, "N m": _MOMENT, "mm": _LENGTH}[target]
    if u not in table:
        raise ValueError(f"Channel {name!r}: unit {unit!r} is not a known "
                         f"{target} unit ({', '.join(table)}).")
    return values * table[u]


def channels_from_isomme(
    test: IsoMmeTest,
    *,
    position: str = "1",
    test_object: str = "1",
    patterns: Mapping[str, str] = HYBRID3_ISOMME,
    table: Mapping[str, tuple[str, int]] = FRONTAL_CHANNELS,
    optional: Sequence[str] = (*_TIBIA, *_SIDE_OPTIONAL),
    filter: bool = True,
) -> dict[str, Series]:
    """Named channels of one dummy from an ISO-MME test.

    Parameters
    ----------
    test:
        From `crashmetrics.isomme.read_isomme`.
    position:
        Seating position, the 2nd code character: ``"1"`` driver,
        ``"3"`` front passenger.
    test_object:
        1st code character (``"1"``: vehicle 1 and its occupants).
    patterns:
        Name -> code characters 3 to 15, ``?`` as a wildcard. The default
        is the Hybrid III 50th (`HYBRID3_ISOMME`); for the ES-2 give the
        codes your laboratory uses with ``table=SIDE_CHANNELS``.
    table:
        Name -> (unit, CFC): `FRONTAL_CHANNELS` or `SIDE_CHANNELS`.
    optional:
        Names that may be missing (tibia locations, side modifier loads).
    filter:
        Filter channels whose filter class says unfiltered with the CFC
        of ``table``. A channel already filtered with another CFC raises
        an error.

    Returns
    -------
    dict
        ``{name: (time_s, values)}`` in the units of ``table``, filtered
        with its CFCs; pass it with ``filtered=True``.
    """
    out: dict[str, Series] = {}
    for name, body in patterns.items():
        if name not in table:
            raise ValueError(f"Unknown channel name {name!r}.")
        found = test.find(f"{test_object}{position}{body}?")
        if not found:
            if name in optional:
                continue
            raise ValueError(f"No ISO-MME channel for {name!r} "
                             f"(pattern {test_object}{position}{body}?).")
        if len(found) > 1:
            raise ValueError(f"Several ISO-MME channels match {name!r}: "
                             f"{', '.join(c.code for c in found)}.")
        channel = found[0]
        if channel.time is None:
            raise ValueError(f"Channel {channel.code} has no time base.")
        unit, cfc = table[name]
        values = _convert(np.asarray(channel.values, dtype=float), channel.unit,
                          unit, name)
        if np.any(np.isnan(values)):
            raise ValueError(f"Channel {channel.code} has missing samples.")
        if channel.cfc is None:
            if filter:
                values = cfc_filter(channel.time, values, cfc)
        elif channel.cfc != cfc:
            raise ValueError(f"Channel {channel.code} is filtered with CFC "
                             f"{channel.cfc}; the protocol needs CFC {cfc}.")
        out[name] = (channel.time, values)
    return out
