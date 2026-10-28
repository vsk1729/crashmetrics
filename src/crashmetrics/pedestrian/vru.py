"""Total Euro NCAP passive VRU (pedestrian and cyclist) crash protection score."""

import math
from dataclasses import dataclass

from crashmetrics.pedestrian.headform import PROTOCOLS as HEADFORM_PROTOCOLS
from crashmetrics.pedestrian.headform import HeadformScore
from crashmetrics.pedestrian.legform import LEGFORM_PROTOCOLS, LegRegionScore

__all__ = ["VRUScore", "vru_score"]


@dataclass(frozen=True)
class VRUScore:
    """Passive VRU crash protection points by body region."""

    total: float
    max_total: float
    percentage: float
    head: float
    pelvis: float
    femur: float
    knee_tibia: float
    protocol: str


def _points(value, region: str, max_points: float, protocol: str) -> float:
    if isinstance(value, HeadformScore):
        if region != "head":
            raise ValueError(f"A headform score was given for {region!r}.")
        if value.protocol != protocol:
            raise ValueError(
                f"The head score uses {value.protocol!r}, not {protocol!r}."
            )
        points = value.score
    elif isinstance(value, LegRegionScore):
        if value.region != region:
            raise ValueError(
                f"A {value.region!r} score was given for {region!r}."
            )
        if value.protocol != protocol:
            raise ValueError(
                f"The {region} score uses {value.protocol!r}, not {protocol!r}."
            )
        points = value.points
    else:
        points = float(value)

    if not math.isfinite(points) or points < 0 or points > max_points + 1e-9:
        raise ValueError(
            f"{region} points must be between 0 and {max_points:g}, got {points!r}."
        )
    return points


def vru_score(
    head: HeadformScore | float,
    pelvis: LegRegionScore | float,
    femur: LegRegionScore | float,
    knee_tibia: LegRegionScore | float,
    protocol: str = "euroncap_2026",
) -> VRUScore:
    """Return the passive VRU crash protection score.

    Parameters
    ----------
    head:
        `crashmetrics.pedestrian.headform_score` result or points.
    pelvis:
        `crashmetrics.pedestrian.upper_legform_score` result or
        points.
    femur, knee_tibia:
        The ``femur`` and ``knee_tibia`` of an
        `crashmetrics.pedestrian.apli_score` result, or points.
    protocol:
        ``"euroncap_2026"``: head 10 + pelvis 2.5 + femur 2.5 +
        knee/tibia 5 = 20 points. ``"euroncap_2023"``: 18 + 4.5 + 4.5 +
        9 = 36 points.
    """
    if protocol not in LEGFORM_PROTOCOLS or protocol not in HEADFORM_PROTOCOLS:
        known = ", ".join(sorted(LEGFORM_PROTOCOLS))
        raise ValueError(f"Unknown protocol {protocol!r}. Known: {known}.")
    legs = LEGFORM_PROTOCOLS[protocol]
    head_max = HEADFORM_PROTOCOLS[protocol].max_points

    head_points = _points(head, "head", head_max, protocol)
    pelvis_points = _points(pelvis, "pelvis", legs.pelvis_points, protocol)
    femur_points = _points(femur, "femur", legs.femur_points, protocol)
    knee_points = _points(knee_tibia, "knee_tibia", legs.knee_tibia_points, protocol)

    total = head_points + pelvis_points + femur_points + knee_points
    max_total = (
        head_max + legs.pelvis_points + legs.femur_points + legs.knee_tibia_points
    )
    return VRUScore(
        total=total,
        max_total=max_total,
        percentage=100.0 * total / max_total,
        head=head_points,
        pelvis=pelvis_points,
        femur=femur_points,
        knee_tibia=knee_points,
        protocol=protocol,
    )
