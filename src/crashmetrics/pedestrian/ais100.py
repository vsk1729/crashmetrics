"""AIS-100 pedestrian protection compliance checks (India).

AIS-100 Rev.1 (April 2024) follows UN GTR 9 / UN R127 with the Flex-PLI;
the original AIS-100 (with Amendments) uses the legacy (TRL) lower
legform. Both use the same upper legform and headform requirements.

Functions:

- `bumper_legform`: Which legform test applies for a lower bumper height
  (Section 4.1).
- `check_flexpli`: Flex-PLI to bumper (Rev.1, 5.1.1).
- `check_legacy_legform`: Legacy lower legform to bumper (original
  AIS-100, 5.1.1).
- `check_upper_legform_bumper`: Upper legform to bumper (5.1.2 in both
  editions).
- `check_relaxation_width`: Total bumper width nominated for the relaxed
  tibia limit (264 mm).
- `check_headform_zones`, `check_headform_tests`: HIC1000 / HIC1700 zone
  areas and test results (5.2.3-5.2.4).

Each check returns `Check` with the measured values, limits,
utilisation (value / limit, worst first) and ``passed``.

Units: moments in N m, elongations and displacements in mm, angles in
degrees, accelerations in g, forces in N, areas in any consistent unit.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "AIS100_FLEXPLI_LIMITS",
    "AIS100_LEGACY_LEGFORM_LIMITS",
    "AIS100_UPPER_LEGFORM_LIMITS",
    "RELAXATION_WIDTH_LIMIT",
    "Check",
    "bumper_legform",
    "check_flexpli",
    "check_headform_tests",
    "check_headform_zones",
    "check_legacy_legform",
    "check_relaxation_width",
    "check_upper_legform_bumper",
]

AIS100_FLEXPLI_LIMITS: dict[str, float] = {
    "mcl": 22.0,
    "acl": 13.0,
    "pcl": 13.0,
    "tibia_moment": 340.0,
    "tibia_moment_relaxed": 380.0,
}
"""AIS-100 Rev.1, 5.1.1: absolute values, mm and N m. The relaxed tibia
limit applies in the nominated widths (264 mm in total)."""

AIS100_LEGACY_LEGFORM_LIMITS: dict[str, float] = {
    "knee_bending_angle": 19.0,
    "knee_shear_displacement": 6.0,
    "tibia_acceleration": 170.0,
    "tibia_acceleration_relaxed": 250.0,
}
"""Original AIS-100, 5.1.1: degrees, mm and g (upper tibia)."""

AIS100_UPPER_LEGFORM_LIMITS: dict[str, float] = {
    "sum_of_forces": 7500.0,
    "bending_moment": 510.0,
}
"""Upper legform to bumper, 5.1.2 (both editions): N and N m."""

RELAXATION_WIDTH_LIMIT = 264.0
"""Total bumper test width the manufacturer may nominate for the relaxed
tibia limit, mm."""

HIC_LIMIT = 1000.0
HIC_RELAXED_LIMIT = 1700.0


@dataclass(frozen=True)
class Check:
    """Result of a compliance check."""

    passed: bool
    values: dict[str, float]
    limits: dict[str, float]
    utilisation: dict[str, float]
    """value / limit per criterion."""
    notes: tuple[str, ...] = ()

    @property
    def worst(self) -> str:
        """Criterion with the highest utilisation."""
        return max(self.utilisation, key=lambda k: self.utilisation[k])


def _check(values: dict[str, float], limits: dict[str, float],
           notes: tuple[str, ...] = ()) -> Check:
    util = {k: abs(values[k]) / limits[k] for k in values}
    return Check(all(u <= 1.0 for u in util.values()),
                 {k: abs(v) for k, v in values.items()}, limits, util, notes)


def bumper_legform(
    lower_bumper_height: float,
) -> Literal["lower_legform", "either", "upper_legform"]:
    """Legform test to the bumper by lower bumper height, mm (Section 4.1):
    below 425 mm the lower legform; 425 to below 500 mm either, at the
    manufacturer's choice; 500 mm and above the upper legform."""
    if lower_bumper_height < 425.0:
        return "lower_legform"
    if lower_bumper_height < 500.0:
        return "either"
    return "upper_legform"


def check_flexpli(
    tibia_moment: float,
    mcl: float,
    acl: float,
    pcl: float,
    relaxed_zone: bool = False,
) -> Check:
    """Flex-PLI to bumper (AIS-100 Rev.1, 5.1.1).

    Peaks within the assessment interval (see
    `crashmetrics.pedestrian.flexpli.flexpli_peaks`): MCL <= 22 mm,
    ACL and PCL <= 13 mm, tibia bending moment <= 340 N m, or 380 N m at
    a point inside the nominated relaxation width (``relaxed_zone``).
    """
    lim = AIS100_FLEXPLI_LIMITS
    tibia_limit = lim["tibia_moment_relaxed"] if relaxed_zone else lim["tibia_moment"]
    return _check(
        {"tibia_moment": tibia_moment, "mcl": mcl, "acl": acl, "pcl": pcl},
        {"tibia_moment": tibia_limit, "mcl": lim["mcl"], "acl": lim["acl"],
         "pcl": lim["pcl"]},
    )


def check_legacy_legform(
    knee_bending_angle: float,
    knee_shear_displacement: float,
    tibia_acceleration: float,
    relaxed_zone: bool = False,
) -> Check:
    """Legacy lower legform to bumper (original AIS-100, 5.1.1): knee
    bending angle <= 19 deg, knee shearing displacement <= 6.0 mm, upper
    tibia acceleration <= 170 g (250 g inside the nominated relaxation
    width)."""
    lim = AIS100_LEGACY_LEGFORM_LIMITS
    acc_limit = (lim["tibia_acceleration_relaxed"] if relaxed_zone
                 else lim["tibia_acceleration"])
    return _check(
        {"knee_bending_angle": knee_bending_angle,
         "knee_shear_displacement": knee_shear_displacement,
         "tibia_acceleration": tibia_acceleration},
        {"knee_bending_angle": lim["knee_bending_angle"],
         "knee_shear_displacement": lim["knee_shear_displacement"],
         "tibia_acceleration": acc_limit},
    )


def check_upper_legform_bumper(sum_of_forces: float, bending_moment: float) -> Check:
    """Upper legform to bumper (5.1.2): instantaneous sum of the impact
    forces <= 7.5 kN and bending moment <= 510 N m."""
    return _check({"sum_of_forces": sum_of_forces, "bending_moment": bending_moment},
                  dict(AIS100_UPPER_LEGFORM_LIMITS))


def check_relaxation_width(widths: Iterable[float]) -> Check:
    """The nominated relaxation widths (mm) must total at most 264 mm."""
    total = float(sum(widths))
    if total < 0:
        raise ValueError("Widths must be non-negative.")
    return _check({"relaxation_width": total},
                  {"relaxation_width": RELAXATION_WIDTH_LIMIT})


def check_headform_zones(
    child_area: float,
    adult_area: float,
    hic1000_child_area: float,
    hic1000_adult_area: float,
) -> Check:
    """Area requirement for the HIC1000 zone (5.2.3), on projected areas.

    The HIC1000 zone must cover at least half the child headform test
    area and two thirds of the combined child and adult test areas; with
    a child test area only (``adult_area == 0``), two thirds of it. The
    rest (HIC1700 zone) must stay below HIC 1700.

    ``utilisation`` here is required share / actual share (<= 1 passes).
    """
    for name, v in (("child_area", child_area), ("adult_area", adult_area),
                    ("hic1000_child_area", hic1000_child_area),
                    ("hic1000_adult_area", hic1000_adult_area)):
        if v < 0:
            raise ValueError(f"{name} must be non-negative.")
    if child_area <= 0:
        raise ValueError("child_area must be positive.")
    if hic1000_child_area > child_area or hic1000_adult_area > adult_area:
        raise ValueError("A HIC1000 area cannot exceed its test area.")

    def ratio(required: float, actual: float) -> float:
        return required / actual if actual > 0 else float("inf")

    if adult_area == 0:
        share = hic1000_child_area / child_area
        return Check(share >= 2 / 3, {"child_share": share}, {"child_share": 2 / 3},
                     {"child_share": ratio(2 / 3, share)},
                     ("child headform test area only",))
    child_share = hic1000_child_area / child_area
    total_share = (hic1000_child_area + hic1000_adult_area) / (child_area + adult_area)
    return Check(
        child_share >= 0.5 and total_share >= 2 / 3,
        {"child_share": child_share, "total_share": total_share},
        {"child_share": 0.5, "total_share": 2 / 3},
        {"child_share": ratio(0.5, child_share),
         "total_share": ratio(2 / 3, total_share)},
    )


def check_headform_tests(
    results: Iterable[tuple[Literal["hic1000", "hic1700"], float]],
) -> Check:
    """Headform test results by zone: HIC <= 1000 in the HIC1000 zone and
    <= 1700 in the HIC1700 zone (5.2.3). ``results`` are (zone, HIC)
    pairs; the worst utilisation per zone is reported."""
    worst: dict[str, float] = {}
    for zone, hic in results:
        if zone not in ("hic1000", "hic1700"):
            raise ValueError(f"Unknown zone {zone!r}.")
        worst[zone] = max(worst.get(zone, 0.0), float(hic))
    if not worst:
        raise ValueError("No headform results.")
    limits = {"hic1000": HIC_LIMIT, "hic1700": HIC_RELAXED_LIMIT}
    return _check(worst, {z: limits[z] for z in worst})
