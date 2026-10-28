# Flex-PLI and AIS-100 compliance

Modules: `crashmetrics.pedestrian` (`flexpli_peaks`,
`assessment_interval`, `flexpli_point_score`, `flexpli_score`,
`bumper_legform`, `check_*`).

AIS-100 is India's pedestrian protection standard; Bharat NCAP requires
compliance with it for any star rating. Two editions are covered:

| | AIS-100 Rev.1 (April 2024) | Original AIS-100 (with amendments) |
| --- | --- | --- |
| Lower legform | Flex-PLI (as UN R127 / GTR 9) | Legacy (TRL) legform |
| Upper legform to bumper | 7.5 kN, 510 N m | same |
| Headform | HIC1000 / HIC1700 zones | same |

## Step 1: which legform test applies?

```python
from crashmetrics.pedestrian import bumper_legform

bumper_legform(390.0)   # 'lower_legform'   (lower bumper height < 425 mm)
bumper_legform(460.0)   # 'either'          (425 to < 500 mm, manufacturer's choice)
bumper_legform(520.0)   # 'upper_legform'   (>= 500 mm)
```

## Step 2: Flex-PLI peaks inside the assessment interval

The Flex-PLI peaks count only inside the **assessment interval (AI)**
(AIS-100 Rev.1 §3.2, as in GTR 9): from first contact to the last zero
crossing of the femur and tibia bending moments after their first
maximum above 15 N m. If a segment never crosses zero, all curves are
shifted down until it does (for the AI only).

```python
from crashmetrics.pedestrian import assessment_interval, flexpli_peaks

# All channels CFC 180: tibia T1-T4 and femur F1-F3 in N m, ligaments in mm
peaks = flexpli_peaks(t, [t1, t2, t3, t4], mcl, acl, pcl,
                      femur_moments=[f1, f2, f3])
peaks.interval               # (start, end) in s
peaks.tibia_moment, peaks.tibia_segment, peaks.mcl, peaks.acl, peaks.pcl

# Or compute the interval yourself and pass it in:
ai = assessment_interval(t, [f1, f2, f3, t1, t2, t3, t4], t_contact=0.0)
peaks = flexpli_peaks(t, [t1, t2, t3, t4], mcl, acl, pcl, interval=ai)
```

## Step 3: AIS-100 Rev.1 Flex-PLI check

| Criterion | Limit |
| --- | --- |
| MCL elongation | ≤ 22 mm |
| ACL and PCL elongation | ≤ 13 mm |
| Tibia bending moment | ≤ 340 N m (≤ 380 N m inside the nominated widths) |
| Nominated relaxation widths | ≤ 264 mm in total |

```python
from crashmetrics.pedestrian import check_flexpli, check_relaxation_width

check = check_flexpli(peaks.tibia_moment, peaks.mcl, peaks.acl, peaks.pcl)
check.passed, check.worst, check.utilisation    # utilisation = value / limit

check_flexpli(355.0, 20.0, 8.0, 5.0, relaxed_zone=True).passed   # 380 N m limit
check_relaxation_width([132.0, 132.0]).passed                    # total <= 264 mm
```

Every check returns a `Check` with `passed`, `values`, `limits`,
`utilisation` and `worst`, so you can see how close each criterion is
to its limit.

## Step 4: original AIS-100 and the upper legform

```python
from crashmetrics.pedestrian import check_legacy_legform, check_upper_legform_bumper

# Legacy legform: knee bending <= 19 deg, shear <= 6 mm, tibia <= 170 g (250 g relaxed)
check_legacy_legform(knee_bending_angle=16.5, knee_shear_displacement=4.2,
                     tibia_acceleration=182.0)

# Upper legform to bumper (both editions): sum of forces <= 7.5 kN, moment <= 510 N m
check_upper_legform_bumper(sum_of_forces=6900.0, bending_moment=455.0)
```

## Step 5: headform zones

The manufacturer marks the **HIC1000 zone** (HIC ≤ 1000) and the
**HIC1700 zone** (HIC ≤ 1700) on the projected bonnet top. The HIC1000
zone must cover:

- at least **half** of the child headform test area, and
- at least **two thirds** of the child + adult test areas combined;
- with a child test area only: two thirds of it.

```python
from crashmetrics.pedestrian import check_headform_tests, check_headform_zones

zones = check_headform_zones(child_area=0.62, adult_area=0.41,          # projected areas
                             hic1000_child_area=0.40, hic1000_adult_area=0.30)
zones.passed, zones.values          # {'child_share': ..., 'total_share': ...}

tests = check_headform_tests([("hic1000", 812.0), ("hic1000", 955.0),
                              ("hic1700", 1420.0)])
tests.passed
```

Areas can be in any unit, as long as all four use the same one.

## Euro NCAP Flex-PLI score (2014–2022 protocols)

Euro NCAP scored the Flex-PLI until 2022 (v10.0.5). Each grid point is
worth 1 point:

- **Tibia** (0.5): sliding scale of the worst tibia moment, 282–340 N m.
- **Knee** (0.5): sliding scale of the MCL, 19–22 mm, but **0** if ACL or
  PCL reaches 10 mm.

The grid is filled by symmetry and worst adjacent results, then scaled to
6 points.

```python
from crashmetrics.pedestrian import flexpli_point_score, flexpli_score

flexpli_point_score(tibia_moment=311.0, mcl=20.5, acl=5.0, pcl=6.0).total   # 0.5
grid = ["L+5", "L+4", "L+3", "L+2", "L+1", "L0", "L-1", "L-2", "L-3", "L-4", "L-5"]
flexpli_score(grid, {"L0": (300.0, 20.0, 5.0, 4.0)}).points
```

## Complete example

```python
--8<-- "examples/04_flexpli_ais100.py"
```

Output:

```text
--8<-- "examples/expected/04_flexpli_ais100.txt"
```
