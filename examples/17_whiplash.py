"""Example 17: rear impact (whiplash) score, BioRID criteria from signals.

Synthetic sled tests of two front seat designs with the medium and high
severity pulses. NIC and Nkm are computed from the T1, head and upper
neck signals; the seat is scored with the 2026 rear impact protocol
(5 points: front seat 4, rear seats 1).
"""

import numpy as np

from crashmetrics.whiplash import (
    RearSeat,
    nic,
    nkm,
    rear_backset_limit,
    score_front_seat,
    score_rear_seats,
    score_whiplash,
    score_whiplash_pulse,
)

t = np.arange(0.0, 0.2, 1e-4)                            # s


def bump(peak, start, width):
    phase = (t - start) / width
    return np.where((phase > 0) & (phase < 1), peak * np.sin(np.pi * phase), 0.0)


def sled_test(severity, gap):
    """BioRID signals; ``gap`` (s) delays head restraint contact."""
    t1 = bump(9.0 * severity, 0.02, 0.09)                # g
    head = bump(9.0 * severity, 0.03 + gap, 0.09)        # head lags T1
    fx = bump(80.0 * severity * (1 + 6 * gap / 0.02), 0.04 + gap, 0.05)
    fz = bump(380.0 * severity * (1 + 4 * gap / 0.02), 0.05 + gap, 0.06)
    my = bump(-6.0 * severity * (1 + 5 * gap / 0.02), 0.04 + gap, 0.05)
    t_hrc_end = 0.12 + gap
    values = {
        "nic": nic(t, t1, head, t_end=t_hrc_end, units="g"),
        "nkm": nkm(t, fx, my, t_end=t_hrc_end).value,
        "upper_neck_fx": float(fx.max()),
        "upper_neck_fz": float(fz.max()),
        "t1": float(t1.max()),
        "t_hrc_start": 1000 * (0.045 + gap),
        "rebound_velocity": 3.2 * severity,
    }
    return values


def show(pulse, values):
    score = score_whiplash_pulse(pulse, values)
    crit = ", ".join(f"{k} {values[k]:.1f}" for k in
                     ("nic", "upper_neck_fx", "upper_neck_fz"))
    capped = f"  capped: {', '.join(score.capped)}" if score.capped else ""
    print(f"  {pulse:6}: NIC/Fx/Fz {crit} | Nkm {values['nkm']:.2f} | "
          f"points {score.points:.3f}{capped}")
    return score


limit = rear_backset_limit(25.0)                          # rear backset limit, mm
rear = score_rear_seats([
    RearSeat(height_lowest=725.0, height_highest=785.0, backset_mid=limit - 20,
             backset_worst=limit + 15, torso_angle=25.0, non_use_position=True),
] * 2)                                                     # symmetric seats

designs = {
    "Seat A: close head restraint (backset 32 mm)": dict(gap=0.002, height=830.0,
                                                          backset=32.0),
    "Seat B: large backset (52 mm), late contact": dict(gap=0.006, height=805.0,
                                                         backset=52.0),
}
for name, d in designs.items():
    print(name)
    medium = show("medium", sled_test(1.0, d["gap"]))
    high = show("high", sled_test(1.35, d["gap"]))
    front = score_front_seat(medium, high, effective_height=d["height"],
                             backset=d["backset"],
                             lowest_rearmost=[(800.0, 62.0), (800.0, 62.0)])
    total = score_whiplash(front, rear)
    print(total.summary())
    print()
