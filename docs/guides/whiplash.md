# Rear impact (whiplash)

Module: `crashmetrics.whiplash`.

The rear impact assessment rates how well the seats protect against
whiplash in low-speed rear-end crashes. It is part of Euro NCAP's (and
ANCAP's) adult occupant protection, **5 points** in the 2026 protocols:

| Seat | Part | Points |
| --- | --- | --- |
| Front | Static geometry (head restraint height and backset) | 1 |
| Front | Dynamic: BioRID sled tests, medium and high severity pulses, 1.5 each | 3 |
| Rear | Head restraint geometry and non-use position | 1 |

Sources: [Crash Protection Rear Impact Protocol v1.2 (August
2026)](https://cdn.ancap.com.au/app/public/assets/c82e6fb632ae0b26cbba585e487ccde7cfcfd0fd/original.pdf?1786511832=)
for the points and limits, [Euro NCAP CP 005
v1.4.1](https://cdn.euroncap.com/cars/assets/CP_005_Data_Acquisition_and_Injury_Calculation_v1_4_1_015875ff46.pdf)
for the criteria. Interpretations are in the
[protocol notes](../protocol-notes.md).

## Step 1: BioRID criteria from signals

```python
from crashmetrics.whiplash import nic, nkm

value_nic = nic(t, t1_ax, head_ax, t_end=t_hrc_end, units="g")
value_nkm = nkm(t, upper_neck_fx, upper_neck_my, t_end=t_hrc_end).value
```

- **NIC** (CP 005 3.2.6): `NIC(t) = 0.2 a_rel + v_rel²` with
  `a_rel = a_T1,x − a_head,x` (T1 the mean of left and right, CFC 60)
  and `v_rel` its integral; maximum up to T-HRC(end).
- **Nkm** (3.2.7): `M_OCy = My − 0.01778 Fx`; the largest of the four
  flexion/extension and anterior/posterior shear combinations
  `M_OCy / M_int + Fx / F_int` with intercepts 88.1 / −47.5 N m and
  ±845 N, each counted only where both signs match.
- T1 acceleration, T-HRC (head restraint contact), rebound velocity and
  seatback deflection come from the test and its film.

## Step 2: score each pulse

```python
from crashmetrics.whiplash import score_whiplash_pulse

medium = score_whiplash_pulse("medium", {
    "nic": 7.2, "upper_neck_fx": 128.0, "upper_neck_fz": 532.0,
    # capping parameters (optional): "nkm", "rebound_velocity", moments ...
    "t1": 9.0, "t_hrc_start": 47.0,
})
```

Three criteria score 0.5 points each, linear between the higher
(full points) and lower (none) performance limits:

| Criterion | Medium pulse | High pulse |
| --- | --- | --- |
| NIC, m²/s² | 11.0 → 24.0 | 13.0 → 23.0 |
| Upper neck shear +Fx, N | 30 → 190 | 30 → 210 |
| Upper neck tension Fz, N | 360 → 750 | 470 → 770 |

**Capping**: reaching any of these gives **no points for that pulse**:

| Parameter | Medium | High |
| --- | --- | --- |
| NIC | 27.0 | 25.5 |
| Nkm | not used | 0.78 |
| Head rebound velocity, m/s | 5.20 | 6.0 |
| Upper neck +Fx / −Fx, N | 290 / 360 | 364 / 360 |
| Upper neck Fz, N | 900 | 1024 |
| Upper and lower neck My extension / flexion, N m | 30 | 30 |
| Lower neck Fx (magnitude), N | 360 | 360 |
| Seatback deflection, deg | not used | 32 |
| T1 acceleration **and** T-HRC start (both reached) | 15.55 g and 92 ms | 17.80 g and 92 ms |

## Step 3: the front seat

```python
from crashmetrics.whiplash import score_front_seat

front = score_front_seat(
    medium, high,
    effective_height=830.0, backset=32.0,               # test position, mm
    lowest_rearmost=[(800.0, 62.0), (800.0, 62.0)],     # each front seat
    front_seats=2,
)
```

- **Geometry, test position (0–1)**: the worse of the effective head
  restraint height (1 at 825 mm, 0 at 790 mm, linear between) and the
  backset (1 below 45 mm, else 0).
- **Lowest and rearmost**: each front seat meeting 790 mm height and
  70 mm backset in that position earns 0.5 / n (n = number of front
  seats). Automatically adjusting head restraints earn it only with a
  raw dynamic score above 1.50.
- Geometry is test position plus lowest/rearmost credit, at most 1
  point; 0 if the head restraint structure requirement (120 mm
  cylinder) fails.
- **Dummy loading** (design exploiting the dummy): −1 point.

## Step 4: rear seats and the total

```python
from crashmetrics.whiplash import RearSeat, rear_backset_limit, score_rear_seats, score_whiplash

seat = RearSeat(height_lowest=725.0, height_highest=785.0,
                backset_mid=310.0, backset_worst=345.0, torso_angle=25.0,
                non_use_position=True)
rear = score_rear_seats([seat, seat])          # symmetric: give one seat twice
total = score_whiplash(front, rear)
print(total.summary())
```

Per rear outboard seat (up to 1): effective height (lowest ≥ 720 mm and
highest ≥ 770 mm, or ≤ 50 mm gap to the roofline) 0.375; backset within
`7.128 × torso angle + 153` mm in the mid position 0.25 and in the worst
case 0.125 (only with the height); non-use position 0.25 (only with
geometry above 0). The seat scores are scaled to 1 point; a row scores
only if its centre seat meets UN R17 as standard.

## Complete example

Two front seat designs: a close head restraint (3.538 / 5) and a large
backset with late head restraint contact (1.875 / 5, the high pulse
capped by Nkm and neck tension):

```python
--8<-- "examples/17_whiplash.py"
```

Output:

```text
--8<-- "examples/expected/17_whiplash.txt"
```

## Protocol documents

- [Crash Protection Rear Impact Protocol v1.2, August 2026 (ANCAP edition)](https://cdn.ancap.com.au/app/public/assets/c82e6fb632ae0b26cbba585e487ccde7cfcfd0fd/original.pdf?1786511832=)
- [Euro NCAP CP 005 Data Acquisition and Injury Calculation v1.4.1, April 2026](https://cdn.euroncap.com/cars/assets/CP_005_Data_Acquisition_and_Injury_Calculation_v1_4_1_015875ff46.pdf)
- [Euro NCAP Whiplash Test Protocol v4.1.2](https://cdn.euroncap.com/cars/assets/euro_ncap_whiplash_test_protocol_v412_41de06c099.pdf) (sled test procedure)
- [ANCAP Assessment Protocol Adult Occupant Protection v9.1.3.1 (2022)](https://s3.amazonaws.com/cdn.ancap.com.au/app/public/assets/0967872638144f22d805bd608d0ce54aa1b04148/original.pdf?1648630601=): the earlier whiplash scoring text (sliding scales, pulse capping)
