"""Example 21: probabilistic Bharat NCAP star rating.

A design scores 27.7 / 32 adult occupant points: 5 stars, but only just
(27 points needed). How likely is it to keep 5 stars in the official
test, given test-to-test scatter of the dummy readings? Each criterion
scatters (relative standard deviation 5-10 %, typical repeatability of
dummy channels); time histories (neck tension, femur) scatter as a
whole. 400 Monte Carlo samples of the complete AIS-197 scoring (use a
few thousand for a decision).
"""

import numpy as np

from crashmetrics.bncap import (
    FrontalOccupant,
    SideOccupant,
    aop_rating,
    score_frontal,
    score_side,
)
from crashmetrics.sensitivity import rank_sensitivity
from crashmetrics.uncertainty import (
    monte_carlo,
    relative,
    scale,
    star_probabilities,
)

t = np.arange(0.0, 0.12, 1e-4)                            # s


def plateau(level, start_ms, end_ms):
    ms = t * 1000.0
    up = np.clip((ms - start_ms + 2.0) / 2.0, 0.0, 1.0)
    down = np.clip((end_ms + 2.0 - ms) / 2.0, 0.0, 1.0)
    return level * np.minimum(up, down)


def rating(v):
    """Adult occupant points and stars for one set of criteria values."""
    driver = FrontalOccupant(
        hic15=v["hic15"], head_a3ms=v["head_a3ms"],
        neck_shear=(t, plateau(-700.0, 20.0, 40.0)),
        neck_tension=(t, plateau(1900.0 * v["neck_scale"], 20.0, 45.0)),
        neck_extension=18.0,
        chest_compression=v["chest"], viscous_criterion=v["vc"],
        femur=((t, plateau(-3300.0 * v["femur_scale"], 30.0, 36.0)),
               (t, plateau(-3000.0 * v["femur_scale"], 30.0, 36.0))),
        knee_displacement=(3.0, 3.5),
        tibia_index=(v["tibia_index"], 0.40), tibia_force=(2100.0, 2000.0),
        pedal_rearward=60.0,
    )
    passenger = FrontalOccupant(
        hard_contact=False,
        neck_shear=(t, plateau(-600.0, 20.0, 40.0)),
        neck_tension=(t, plateau(1700.0, 20.0, 45.0)),
        neck_extension=15.0,
        chest_compression=v["chest_p"], viscous_criterion=0.32,
        femur=((t, plateau(-2800.0, 30.0, 36.0)), (t, plateau(-2700.0, 30.0, 36.0))),
        knee_displacement=(2.0, 2.5),
        tibia_index=(0.42, 0.40), tibia_force=(1900.0, 2000.0),
    )
    side = SideOccupant(
        hic15=300.0, head_a3ms=46.0, rib_deflection=v["rib"], rib_vc=v["rib_vc"],
        abdominal_force=v["abdomen"], pubic_force=v["pubic"],
    )
    result = aop_rating(score_frontal(driver, passenger), score_side(side))
    return {"points": result.points, "stars": result.stars}


nominal = {"hic15": 520.0, "head_a3ms": 58.0, "neck_scale": 1.0, "chest": 31.0,
           "vc": 0.45, "femur_scale": 1.0, "tibia_index": 0.55, "chest_p": 24.0,
           "rib": 27.0, "rib_vc": 0.42, "abdomen": 1150.0, "pubic": 2500.0}
scatter = {"hic15": relative(0.10), "head_a3ms": relative(0.07),
           "neck_scale": scale(0.08), "chest": relative(0.06), "vc": relative(0.10),
           "femur_scale": scale(0.08), "tibia_index": relative(0.08),
           "chest_p": relative(0.06), "rib": relative(0.06), "rib_vc": relative(0.10),
           "abdomen": relative(0.10), "pubic": relative(0.10)}

result = monte_carlo(rating, nominal, scatter, n=400, seed=2026)
print(f"Nominal design: {result.nominal['points']:.2f} / 32 points, "
      f"{result.nominal['stars']:.0f} stars")
print(result.summary(["points"]))
print("\nStar rating probabilities:")
for stars, p in star_probabilities(result).items():
    if p:
        print(f"  {stars} stars: {p:6.1%}")
print(f"P(5 stars) = {result.probability('stars', at_least=5):.1%}")

# Which criteria decide the fifth star? Rank the inputs by their effect on
# the points (partial rank correlation over the samples).
ranking = rank_sensitivity(result.rows(), list(scatter), "points")
print()
print(ranking.summary())
