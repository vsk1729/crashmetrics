# CrashMetrics

Python tools for automotive crash engineering calculations.

**Development status:** Alpha — not validated for regulatory compliance.

## Features

- Head Injury Criterion (HIC), for example HIC15 and HIC36, via `crashmetrics.pedestrian.calculate_hic`
- Euro NCAP headform grid scoring in `crashmetrics.pedestrian`: HIC colour bands, verification tolerance, correction factor, blue, default red and A-pillar points, and the head score for the 2023 and 2026 protocols (`headform_score`)
- Euro NCAP legform scoring in `crashmetrics.pedestrian`: aPLI femur and knee/tibia (`apli_score`), upper legform pelvis (`upper_legform_score`) with the impact energy check (`upper_legform_energy`), sliding scales, leg colours and the total passive VRU score (`vru_score`)
- Signal processing in `crashmetrics.signals`: SAE J211 CFC filtering (`cfc_filter`), resultants (`resultant`), unit conversion (`to_g`, `to_seconds`) and uniform resampling (`resample_uniform`)
- Acceleration metrics in `crashmetrics.acceleration`: peak value and time (`peak`) and the 3 ms clip, cumulative or continuous (`clip_3ms`)
- Vehicle pulse metrics in `crashmetrics.pulse`: Occupant Load Criterion (`olc`) and a pulse summary with delta-V, time to zero velocity, maximum displacement, rebound and deceleration (`pulse_summary`)
- Frontal impact dummy criteria (Euro NCAP CP 005 and UN-ECE R94) for the Hybrid III and THOR:
  - head (`crashmetrics.head`): DAMAGE (`damage`), BrIC (`bric`) and the end of the loading phase (`loading_phase_end`)
  - neck (`crashmetrics.neck`): occipital condyle moment, peak shear, tension, compression and moments (`neck_loads`), force–duration limits such as R94 (`neck_force_criterion`) and Nij (`nij`)
  - chest and abdomen (`crashmetrics.thorax`): Hybrid III deflection (`chest_deflection`), VC (`viscous_criterion`), THOR Rmax (`thor_chest_deflection`), THOR abdomen deflection (`thor_abdomen_deflection`) and CTI (`cti`)
  - pelvis (`crashmetrics.pelvis`): THOR acetabulum force (`acetabulum_force`) and iliac force drop (`iliac_force_drop`)
  - legs (`crashmetrics.lower_extremity`): Tibia Index (`tibia_index`), tibia compression (`tibia_compression`), knee slider displacement (`knee_slider_displacement`) and femur compressive force against a force–time limit (`femur_force_criterion`)
- AIS-100 pedestrian compliance (India) in `crashmetrics.pedestrian`: Flex-PLI (Rev.1) and legacy legform limits, upper legform to bumper, which legform applies by bumper height, the relaxation width and the HIC1000 / HIC1700 zone rules
- Flex-PLI criteria and scoring in `crashmetrics.pedestrian`: the assessment interval, peaks within it, and Euro NCAP 2014–2022 Flex-PLI point and grid scores
- Euro NCAP frontal scoring (2026 protocols) in `crashmetrics.frontal_scoring`: colour bands from HPL/LPL, body region and dummy scores with modifiers, and the MPDB (`score_mpdb`, 20 points) and full width (`score_fwdb`, 10 points) test scores
- Bharat NCAP adult occupant scoring (AIS-197) in `crashmetrics.bncap`: 4-point sliding scales, neck and femur exceedance-curve scoring, ODB frontal (`score_frontal`) and MDB side (`score_side`) test scores with modifiers and capping, pole test check and the star rating (`aop_rating`, `cop_stars`)
- ES-2 side impact criteria in `crashmetrics.side`: worst rib deflection and VC, total abdominal force and pubic symphysis force
- Generic exceedance helpers in `crashmetrics.acceleration`: `exceedance_level`, `exceedance_duration` and the force–duration limit check `exceedance_check`
- Simulation energy checks for any load case in `crashmetrics.energy_check` (energy ratio, hourglass, negative contact, damping, added mass, eroded energy, per-part hourglass and negative internal energy), LS-DYNA glstat/matsum readers in `crashmetrics.lsdyna`, and the `crashmetrics-energy` command
- LS-DYNA d3hsp reader (`read_d3hsp`): run information, termination status, warnings and errors, model size and settings, keyword counts, part masses, smallest time steps, timing and memory
- Energy and force–displacement metrics in `crashmetrics.energy`: velocity and displacement from acceleration (`integrate_acceleration`), cumulative absorbed energy (`absorbed_energy`), crush summary with peak and mean force, crush force efficiency and specific energy absorption (`crush_metrics`), and `kinetic_energy`

## Installation

```bash
python -m pip install crashmetrics
```

To get the latest unreleased changes, install from GitHub instead:

```bash
python -m pip install "git+https://github.com/vsk1729/crashmetrics.git"
```

Requires Python 3.10 or later and NumPy 1.24 or later.

## Example

```python
from crashmetrics.pedestrian import calculate_hic

time = [0.0, 0.005, 0.010, 0.015]
acceleration = [10.0, 10.0, 10.0, 10.0]

result = calculate_hic(
    time,
    acceleration,
    window_ms=15.0,
)

print(result.value)
print(result.duration_ms)
```

### From LS-DYNA output to HIC15

For a headform model in the mm-ms-kg unit system, with axis
accelerations `ax`, `ay`, `az` in mm/ms² and `time_ms` in ms
(uniformly sampled):

```python
from crashmetrics.pedestrian import calculate_hic
from crashmetrics.signals import cfc_filter, resultant, to_g, to_seconds

t = to_seconds(time_ms, "ms")

# Filter each component with CFC 1000, then form the resultant.
components_g = [
    cfc_filter(t, to_g(a, "mm/ms^2"), cfc=1000) for a in (ax, ay, az)
]
a_res = resultant(*components_g)

hic15 = calculate_hic(t, a_res, window_ms=15.0)
print(f"HIC15 = {hic15.value:.0f} over {hic15.duration_ms:.2f} ms")
```

The same filtered resultant gives the peak and the 3 ms clip:

```python
from crashmetrics.acceleration import clip_3ms, peak

a_peak = peak(t, a_res)
print(f"Peak = {a_peak.value:.1f} g at {a_peak.time * 1000:.2f} ms")
print(f"3 ms clip = {clip_3ms(t, a_res):.1f} g")
```

If the output interval is not uniform, use
`resample_uniform(t, a, sample_rate)` before filtering.

### Simulation energy checks (any load case)

Check the energy balance of LS-DYNA runs from the command line. Each
run is a directory with `glstat` (and optionally `matsum`), or a glstat
file:

```bash
crashmetrics-energy run01 run02 run03
crashmetrics-energy run01 --hourglass 0.05 --added-mass 2 --ratio-min 0.9 --ratio-max 1.1
```

```text
== run01
Energy check: FAILED (1 check)
Reference energy: 100000

Check                   Value    Limit         Status  Where
----------------------  -------  ------------  ------  -------
energy_ratio            1        0.95 to 1.05  PASS    t=0
hourglass               0.03093  <= 0.1        PASS    t=0.1
negative_contact        0        <= 0.05       PASS
damping                 0        <= 0.05       PASS
added_mass              2        <= 5 %        PASS    t=0.1
part_hourglass          0.14     <= 0.1        FAIL    part 2
part_negative_internal  0        <= 0.01       PASS

- failed parts: 2
```

The exit code is 0 if every run passes, 1 if a check fails and 2 if a
run could not be read, so it fits batch scripts and job queues. Use
`off` to switch a limit off, for example `--hourglass off`.

From Python:

```python
from crashmetrics.energy_check import EnergyLimits, check_energies
from crashmetrics.lsdyna import check_run, read_glstat, read_matsum

report = check_run("run01", limits=EnergyLimits(hourglass=0.05))
print(report.summary())
if not report.passed:
    for check in report.failures:
        print(check.name, check.value, check.part)

# Or from the files / your own arrays:
report = check_energies(read_glstat("run01/glstat"), read_matsum("run01/matsum"))
```

| Check | Value | Default limit |
|---|---|---|
| `energy_ratio` | total / (initial total + external work), min and max over the run | 0.95 to 1.05 |
| `hourglass` | peak hourglass / peak internal energy | ≤ 0.10 |
| `negative_contact` | most negative contact (sliding) energy / reference energy | ≤ 0.05 |
| `damping` | peak system damping energy / reference energy | ≤ 0.05 |
| `added_mass` | peak added mass, % of model mass | ≤ 5 % |
| `eroded_energy` | peak eroded energy / reference energy | reported only |
| `part_hourglass` | per part: peak hourglass / peak internal energy | ≤ 0.10 |
| `part_negative_internal` | per part: most negative / peak internal energy | ≤ 0.01 |

- The reference energy is the largest initial total energy plus
  external work, so impacts (initial kinetic energy) and prescribed
  motion or quasi-static cases (external work) are both handled.
- Part checks cover parts with at least 1 % of the model's peak
  internal energy (`part_min_internal_share`); every part's values are
  in `report.parts`.
- Hourglass, damping and rigidwall energies are only in the output when
  `HGEN`, `RYLEN` and `RWEN` are 2 in `*CONTROL_ENERGY`; missing
  channels are reported as skipped, with a hint.
- The 10 % hourglass limits follow LS-DYNA's rule of thumb; the other
  defaults are common rules of thumb. Set your own guideline values in
  `EnergyLimits` or on the command line.
- The readers find values by label (glstat) and `key=` (matsum), so the
  line order and optional channels of different LS-DYNA versions do not
  matter. Part names come from the matsum legend and per-part added mass
  from `+mass=`; the summary lists the parts with the most added mass.
- Verified on real LS-DYNA R14.1 and R16.1 output: every parsed value
  matches the files, and the total-energy and energy-ratio formulas
  reproduce LS-DYNA's own values to the file's 6-digit precision. For binout output, read the variables with a binout reader
  (such as lasso-python) and pass them to `GlobalEnergies.from_mapping`
  and `PartEnergies.from_mapping`, which accept glstat and binout names.

### LS-DYNA d3hsp reader

```python
from crashmetrics.lsdyna import read_d3hsp

run = read_d3hsp("run01/d3hsp")
print(run.summary())
```

```text
Termination: NORMAL (10/23/26 14:41:58)
LS-DYNA smp s R14, revision R14.1.1-4-gaf1eb871e8, WINDOWS X64 SSE2
Input: ball_drop.k
Model: nodes 988, solid_elements 8, shell_elements 900, beam_elements 0, ...
Total mass: 0.000134069 (2 parts, 1 rigid)
Smallest time step: 8.409e-07 (shell 100099, part 1)
Problem time 0.0030004 in 3568 cycles
Elapsed: 1 s using 4 SMP threads, CPU 2 s
Warnings: 0, errors: 0
```

| Attribute | Content |
|---|---|
| `termination`, `termination_time` | `"normal"`, `"error"` or `"incomplete"` (no banner: still running or killed) |
| `version`, `parallel`, `precision`, `release`, `revision`, `platform`, `ncpu`, `command_line`, `input_file`, `run_date` | Run information |
| `messages`, `warnings`, `errors`, `message_counts()` | `*** Warning 41123 (SOL+1123)` messages with their text |
| `model` | Nodes, elements by type, materials, contacts |
| `parameters` | Every echoed `label.....  value` setting, e.g. `parameters["time_step_scale_factor"]` |
| `keyword_counts` | Keywords in the deck, e.g. `keyword_counts["*CONTACT_option"]` |
| `part_masses`, `rigid_parts`, `total_mass` | Mass summary |
| `smallest_timesteps`, `min_timestep` | The 100 smallest time steps table |
| `problem_time`, `problem_cycles`, `cpu_seconds`, `elapsed_seconds`, `workers`, `worker_type`, `timing`, `memory` | Timing breakdown and memory |

The reader was built and tested on real SMP d3hsp files from LS-DYNA
R14.1 and R16.1. It accepts MPP runs (`mpp` in the version line, `MPP
procs` in the elapsed-time line), but has not yet been checked on real
MPP output; please report any MPP file it misreads.

### Energy and crush metrics

For a crash box or rail with force in kN and crush in mm (energy in J):

```python
from crashmetrics.energy import absorbed_energy, crush_metrics

energy_curve = absorbed_energy(crush_mm, force_kN)  # J at each sample

result = crush_metrics(crush_mm, force_kN, mass=1.2, max_displacement=150.0)
print(f"Energy {result.energy:.0f} J, mean force {result.mean_force:.1f} kN")
print(f"Peak {result.peak_force:.1f} kN at {result.peak_force_displacement:.1f} mm")
print(f"CFE {result.crush_force_efficiency:.2f}, SEA {result.specific_energy_absorption:.0f} J/kg")
```

`max_displacement` evaluates the metrics over a fixed stroke. Mean
force is net energy divided by crush distance and CFE is mean force
divided by peak force, so always report the stroke with them.

From a vehicle or impactor acceleration pulse (mm/ms² and ms give
m/s and mm):

```python
from crashmetrics.energy import integrate_acceleration, kinetic_energy

velocity, displacement = integrate_acceleration(time_ms, accel_mm_ms2, v0=15.6)
print(f"Dynamic crush {displacement.max():.0f} mm")
print(f"Initial kinetic energy {kinetic_energy(1200.0, 15.6) / 1000:.1f} kJ")
```

The energy functions do not convert units; use a consistent system.
Integration amplifies sensor offset and drift, so check the input
pulse before integrating test data.

### Euro NCAP headform grid score

Give every grid point its predicted HIC15 (for example from CAE) or a
colour, mark special points with a label, and add the test results:

```python
from crashmetrics.pedestrian import headform_score

grid = {
    (9, 2): 541.0,          # predicted HIC15 -> green
    (1, -1): "yellow",      # or a predicted colour
    (12, -6): "red",
    (16, 8): "a_pillar",
    (18, 0): "default_red",
    (11, 1): "blue",
    # ... every grid point
}

result = headform_score(
    grid,
    verification={(9, 2): 558.9, (1, -1): 813.8},   # 40 km/h tests, HIC15
    blue_results={(11, 1): 1200.0},                  # per blue point
    a_pillar_results={(16, 8): [(20.0, 950.0)]},     # (km/h, HIC15), 2026 only
    protocol="euroncap_2026",
)
print(f"Head score {result.score:.3f} / {result.max_score:g} ({result.percentage:.1f} %)")
print(f"Correction factor {result.correction.factor:.3f}, accepted: {result.correction.accepted}")
```

Without `verification`, no correction is applied, which gives the
predicted score from CAE results alone.

The rules follow the Euro NCAP protocols:

| | `"euroncap_2026"` | `"euroncap_2023"` |
|---|---|---|
| Protocol | Crash Protection – VRU Impacts v1.1 | Assessment Protocol – VRU v11.4 |
| Head maximum | 10 points | 18 points |
| Colour bands (HIC15) | green < 650 ≤ yellow < 1000 ≤ orange < 1350 ≤ brown < 1700 ≤ red | same |
| Points per grid point | 1, 0.75, 0.5, 0.25, 0 | same |
| Correction factor | tested ÷ predicted points of the verification tests, rounded to 3 decimals, accepted 0.850–1.150 | same |
| Verification colour | predicted colour kept if HIC15 is within its 10 % tolerance range, else colour from the measured HIC15 | same |
| Blue points | scored from their tests, not corrected | same |
| A-pillar points | reward for the highest passing speed: 20 km/h HIC15 < 1000 → 1, 30 km/h < 1700 → 2, 40 km/h < 1700 → 3 | default red |

Score = min(corrected predicted points + blue points + A-pillar points,
number of grid points) / number of grid points × head maximum. The
tests reproduce the worked examples of both protocols (2023: 10.554 of
18 points; 2026: correction factor 1.120).

How the A-pillar rewards add to the grid total is this package's
reading of the 2026 protocol (added to the grid score, maximum still
the number of grid points); confirm it before relying on it.

### AIS-100 compliance and Flex-PLI

```python
from crashmetrics.pedestrian import (
    bumper_legform, check_flexpli, check_headform_tests, check_headform_zones,
    flexpli_peaks, flexpli_score,
)

bumper_legform(410.0)            # 'lower_legform' (< 425 mm), 'either', 'upper_legform' (>= 500)

# Flex-PLI peaks inside the assessment interval (AIS-100 Rev.1 3.2 / GTR 9)
peaks = flexpli_peaks(t, [tibia1, tibia2, tibia3, tibia4], mcl, acl, pcl,
                      femur_moments=[femur1, femur2, femur3])
check = check_flexpli(peaks.tibia_moment, peaks.mcl, peaks.acl, peaks.pcl)
print(check.passed, check.worst, check.utilisation)

# Headform: HIC1000 zone share of the projected test areas, and test results
check_headform_zones(child_area=0.6, adult_area=0.4,
                     hic1000_child_area=0.35, hic1000_adult_area=0.32)
check_headform_tests([("hic1000", 850.0), ("hic1700", 1500.0)])

# Euro NCAP (2014-2022) Flex-PLI grid: {point: (tibia N m, MCL, ACL, PCL mm)}
flexpli_score(["L+1", "L0", "L-1"], {"L0": (300.0, 20.0, 5.0, 4.0)}).points
```

- **AIS-100 Rev.1 (2024)**: Flex-PLI MCL ≤ 22 mm, ACL and PCL ≤ 13 mm,
  tibia moment ≤ 340 N m (380 N m inside up to 264 mm of nominated
  width). **Original AIS-100**: legacy legform knee bending ≤ 19°, knee
  shear ≤ 6 mm, tibia acceleration ≤ 170 g (250 g in the nominated
  width). **Both**: upper legform to bumper sum of forces ≤ 7.5 kN and
  moment ≤ 510 N m; the HIC1000 zone must cover half the child test area
  and two thirds of the child + adult areas (two thirds if there is only
  a child area), with HIC ≤ 1700 elsewhere.
- **Assessment interval**: from first contact to the last zero crossing
  of the femur and tibia moments after their first maximum above 15 N m,
  shifting all curves down if a segment never crosses zero.
- **Euro NCAP Flex-PLI score** (v10.0.5): per point, tibia 0.5 × the
  282–340 N m scale plus knee 0.5 × the 19–22 mm MCL scale (0 if ACL or
  PCL reaches 10 mm); the grid is filled by symmetry and worst adjacent
  results and scaled to 6 points.

### Euro NCAP legform scoring and total VRU score

Units: force in N, bending moment in N m, MCL elongation in mm. Give
every grid point (Euro NCAP names such as `"L+3"` or lateral indices)
and the results of the tested points; untested points are filled
automatically:

```python
from crashmetrics.pedestrian import apli_score, upper_legform_score, vru_score

# aPLI: (femur moment, tibia moment, MCL elongation) per tested point.
# Peaks, several gauge peaks or time histories; the worst value is used.
grid_l = ["L+5", "L+4", "L+3", "L+2", "L+1", "L0", "L-1", "L-2", "L-3", "L-4", "L-5"]
apli = apli_score(grid_l, {
    "L+1": (400.0, 257.0, 20.0),
    "L+3": (438.0, 300.0, 29.0),
    "L+5": (385.0, 225.0, 36.0),
})
print(f"Femur {apli.femur.points:.3f} / {apli.femur.max_points}")
print(f"Knee/tibia {apli.knee_tibia.points:.3f} / {apli.knee_tibia.max_points}")

# Upper legform: sum of forces (N) per tested point.
grid_u = ["U+4", "U+3", "U+2", "U+1", "U0", "U-1", "U-2", "U-3", "U-4"]
pelvis = upper_legform_score(grid_u, {"U0": 5260.0, "U-2": 6800.0, "U-4": 4890.0})
print(f"Pelvis {pelvis.points:.3f} / {pelvis.max_points}")

total = vru_score(head_result, pelvis, apli.femur, apli.knee_tibia)
print(f"VRU crash protection {total.total:.3f} / {total.max_total:g}")
```

Each result keeps the score, colour and source of every grid point
(`scores`, `colours`, `sources`), for example `"worst adjacent 'L+3'"`.

| | Higher limit (1 point) | Lower limit (0 points) |
|---|---|---|
| Upper legform sum of forces | 5.0 kN | 6.0 kN |
| aPLI femur bending moment | 390 N m | 440 N m |
| aPLI tibia bending moment | 275 N m | 320 N m |
| aPLI MCL elongation | 27 mm | 32 mm |

- Scores are linear between the limits and rounded to 3 decimals, as in
  the protocols' worked examples (`round_to=None` to keep them exact).
- aPLI femur score: worst femur bending moment. Knee/tibia score: the
  lower of the tibia and MCL scores.
- Untested points take the result of their mirror point (unless
  declared in `asymmetric_points`), else the worst result of the
  adjacent points, separately for each body region.
- Region points = sum of grid-point scores / number of grid points ×
  region maximum: pelvis 2.5, femur 2.5, knee/tibia 5 in
  `"euroncap_2026"` (total VRU 20 with the 10-point head); 4.5, 4.5 and
  9 in `"euroncap_2023"` (total 36 with the 18-point head).
- Leg colours: green 1.000, yellow ≥ 0.750, orange ≥ 0.500, brown
  ≥ 0.001, red 0.000 (`leg_colour`).

The upper legform impact energy decides whether a test is needed:

```python
from crashmetrics.pedestrian import upper_legform_alpha, upper_legform_energy

alpha = upper_legform_alpha(ibrl=(x_ibrl, z_ibrl), wad930=(x_930, z_930))  # x rearward
e = upper_legform_energy(alpha)
print(f"alpha {alpha:.1f} deg, En {e.energy:.0f} J, vt {e.test_velocity:.2f} m/s, "
      f"test required: {e.test_required}")
```

En = 0.5 × 7.4 kg × (11.11 m/s × cos(1.2α))², vt = √(2En / 10.5 kg),
and no test is required below 160 J. Passing `energies` (J per grid
point) to `upper_legform_score` scores untested points below 160 J as
`not_required_score` (default 1.0) and only shares a symmetric or
adjacent result when the energies differ by at most 10 %.

The tests reproduce the protocols' worked examples: 2023 upper legform
1.370 / 4.5, femur 1.898 / 4.5, knee/tibia 3.908 / 9; 2026 upper
legform 0.761 / 2.5.

### Occupant Load Criterion and pulse summary

Inputs are SI (s, m/s², m/s). The acceleration is the vehicle's
longitudinal acceleration in its direction of travel, so it is
negative while decelerating, and the record starts at T0:

```python
from crashmetrics.pulse import olc, pulse_summary
from crashmetrics.signals import cfc_filter

a = cfc_filter(t, accel_x_m_s2, cfc=180)   # Euro NCAP uses CFC 180 for OLC
result = olc(t, a, v0=50 / 3.6)
print(f"OLC = {result.value:.1f} g (t1 = {result.t1*1000:.1f} ms, t2 = {result.t2*1000:.1f} ms)")

summary = pulse_summary(t, a, v0=50 / 3.6)
print(f"delta-V {summary.delta_v:.2f} m/s, max displacement {summary.max_displacement*1000:.0f} mm")
```

`olc` follows the Euro NCAP definition (Data Acquisition and Injury
Calculation protocol): a virtual occupant moves 65 mm in free flight,
then decelerates uniformly over a further 235 mm until it matches the
vehicle velocity. The OLC is that deceleration, expressed in g using
9.81 m/s² as Euro NCAP does (change with `gravity`). The tests check it
against the closed-form solution for constant deceleration and against
an independent numerical formulation.

### Frontal impact dummy criteria

The dummy criteria shared by the Euro NCAP frontal tests (MPDB, full
width) and UN-ECE R94. They follow the Euro NCAP Data Acquisition and
Injury Calculation protocol (CP 005 v1.4.1) unless another source is
named. Inputs are SI (s, N, N m, rad/s) with deflections in mm; filter
each channel first with the CFC that CP 005 gives (`cfc_filter`).

| Region | Criterion | Function | Source |
| --- | --- | --- | --- |
| Head | DAMAGE (THOR) | `head.damage`, `head.damage_from_acceleration` | CP 005 3.1.3 |
| Head | BrIC | `head.bric` | Takhounts et al. 2013 |
| Head | End of the loading phase | `head.loading_phase_end` | CP 005 |
| Neck | Occipital condyle moment, shear, tension, compression, extension and flexion | `neck.occipital_condyle_moment`, `neck.neck_loads` | CP 005 3.2 |
| Neck | Force–duration (exceedance) limits | `neck.neck_force_criterion` | UN-ECE R94 |
| Neck | Nij | `neck.nij` | FMVSS 208 |
| Chest | Hybrid III chest deflection | `thorax.chest_deflection` | CP 005 3.4.1 |
| Chest | THOR Rmax | `thorax.thor_rib_displacement`, `thorax.thor_chest_deflection` | CP 005 3.4.2 |
| Chest | Viscous criterion VC | `thorax.viscous_criterion` | CP 005 3.4.6 |
| Chest | CTI | `thorax.cti`, `thorax.cti_from_signals` | Eppinger et al. 1999 |
| Abdomen | THOR abdomen deflection | `thorax.thor_abdomen_deflection` | CP 005 3.5.2 |
| Pelvis | Iliac force drop | `pelvis.iliac_force_drop` | CP 005 3.6.1 |
| Pelvis | THOR acetabulum force | `pelvis.acetabulum_force` | CP 005 3.6.2 |
| Legs | Knee slider displacement | `lower_extremity.knee_slider_displacement` | CP 005 3.6.3 |
| Legs | Tibia compression | `lower_extremity.tibia_compression` | UN-ECE R94 |

BrIC, Nij and CTI are not Euro NCAP criteria; they are included with
the values of their original sources.

```python
from crashmetrics.head import damage, loading_phase_end
from crashmetrics.neck import neck_force_criterion, neck_loads
from crashmetrics.signals import cfc_filter
from crashmetrics.thorax import thor_chest_deflection

# THOR head: DAMAGE from the CFC 60 angular velocity (rad/s). The window
# runs from T0 for up to 200 ms, or until the external head force drops
# below -500 N when the head x acceleration (g) and neck Fx (N) are given.
w = [cfc_filter(t, w_i, cfc=60) for w_i in (wx, wy, wz)]
result = damage(t, *w, t0=0.0, head_ax_g=head_ax, neck_fx=neck_fx)
print(f"DAMAGE {result.value:.3f} ({result.end_reason})")

# Hybrid III upper neck over the loading phase.
t_end = loading_phase_end(t, head_ax)
loads = neck_loads(t, neck_fx, neck_fz, neck_my, dummy="hybrid3", t_end=t_end)
print(loads.tension.value, loads.shear.value, loads.extension_moment.value)
print(neck_force_criterion(t, neck_fz, "r94_tension").utilisation)

# THOR chest: each IR-TRACC as (R in mm, phi_y and phi_z in degrees).
chest = thor_chest_deflection(t, upper_left, upper_right, lower_left, lower_right)
print(f"Rmax {chest.rmax:.1f} mm ({chest.location})")
```

Sign conventions (check them against your channels):

- Neck: SAE J211, tension and flexion positive. The Hybrid III moment
  is moved to the occipital condyle, `M_OCy = My - Fx * 0.01778 m`; the
  THOR uses the upper neck My directly, as in CP 005. The extension
  moment is `abs(min(M))`.
- Chest deflection and VC: compression positive by default
  (`compression_negative=True` otherwise).
- THOR abdomen: CP 005 writes `max(Dx(t))` with
  `Dx = R cos(phi_z) cos(phi_y) - Dx(0)`. The IR-TRACC length R
  shortens in compression, so `value` is the compression `max(-Dx)`;
  `max_dx` keeps the literal `max(Dx)`.
- Acetabulum: CP 005 takes the resultant force while Fx is
  compressive but does not give the sign; negative Fx is taken as
  compression by default (`compression_negative`).
- Iliac force drop: `IFD = max(F(t + 1 ms) - F(t))` as written in
  CP 005, which assumes the iliac force is negative under load. Pass
  `loaded_negative=False` if yours is positive.
- Tibia compression and knee slider: `abs(min(Fz))` and
  `abs(min(D))`.

How they are verified: DAMAGE matches the model developers' reference
implementation (UVA-CAB/DAMAGE 2.0) to machine precision on a 3-axis
pulse and the closed-form step response of the 3-degree-of-freedom
model (solved mode by mode) to 1e-7; VC is exact for a cubic deflection
and matches the closed-form maximum for a sinusoid; the THOR rib
displacement matches the rotation-matrix geometry of the IR-TRACC; the
other criteria are checked by hand calculations. The constants are
taken from CP 005 (DAMAGE, VC), FMVSS 208 (Nij intercepts in position:
Hybrid III 50th male and 5th female), Takhounts et al. 2013, Table 3
(BrIC: the average of the MPS- and CSDM-based values by default) and
Eppinger et al. 1999 (CTI).

### Euro NCAP frontal scoring (MPDB and full width)

Scores the MPDB (offset) and full width tests to the Euro NCAP Crash
Protection Frontal Impact Protocol v1.1 (2026–2028) and CP 007
Assessment Modifiers v1.1:

```python
from crashmetrics.frontal_scoring import (
    Occupant, compatibility_penalty, damage_modifier, score_mpdb,
)

driver = Occupant(  # THOR 50th; worst of left and right where relevant
    values={"head_peak": 60.0, "neck_shear": 1500.0, "neck_tension": 2800.0,
            "neck_extension": 30.0, "chest_compression": 50.0,  # Rmax, mm
            "abdomen_compression": 70.0, "acetabulum_force": 3000.0,
            "femur_force": 4000.0, "knee_displacement": 5.0,
            "tibia_index": 0.3, "tibia_force": 1500.0},
    modifiers={"head_neck": [damage_modifier(0.44)]},  # % of region points
)
result = score_mpdb(
    {"driver": driver, "front_passenger": ..., "rear_q6": ..., "rear_q10": ...},
    full_scale_modifiers=[2.5],    # e.g. A-pillar, % of 10 points
    compatibility_penalty=compatibility_penalty(sd=119.0, olc=34.9,
                                                bottoming_out=False),  # 2.826
)
print(result.points, result.occupants["driver"].regions["head_neck"])
```

- **Colour bands**: green below the HPL, red at or above the LPL, and
  yellow / orange / brown in three equal bands of width
  `(LPL - HPL) / 3` between them. A criterion with an LPL only is green
  or red. Each body region takes its lowest-scoring criterion; green,
  yellow, orange, brown and red earn 100, 80, 60, 40 and 0 % of the
  region points (1.25 / 1.0 / 0.75 / 0.5 / 0 of 1.25).
- **Points**: MPDB at 50 km/h, 20 points (THOR 50th driver, Hybrid III
  5th passenger, Q6 and Q10 rear, 5 each); full width at 35 km/h, 10
  points (Hybrid III 5th driver 5, THOR 50th passenger 2.5, Hybrid III
  5th rear 2.5). The chest compression limits follow the test speed.
- **Head**: without hard contact (head peak above 80 g, or `hard_contact`)
  HIC15 and the 3 ms acceleration are not applied to adults; the Q
  dummies' head is then scored on the 3 ms acceleration only.
- **Modifiers**: occupant modifiers in % of the region points (Q dummy
  score modifiers in % of the dummy score), full-scale modifiers in % of
  10 points; no score goes below zero. `OCCUPANT_MODIFIERS` and
  `FULL_SCALE_MODIFIERS` list the protocol's values, and
  `damage_modifier` gives the THOR DAMAGE modifier.
- **Compatibility** (CP 007 Appendix A): `compatibility_penalty(sd, olc,
  bottoming_out)` = `1.25 (s + o + 2 s o)` points, plus 1.25 for
  bottoming out, at most 5, where s and o are the SD (50–150 mm) and OLC
  (25–40 g) sliding scales. It reproduces CP 007's three worked examples.
- **Capping**: values at or above a capping limit are listed in
  `capping_exceeded` (the Hybrid III 5th neck capping only for the
  driver); the protocol does not state the consequence.
- **Band points**: the protocol text (Section 3.5) gives 1.25 / 1.0 /
  0.75 / 0.5 / 0 points, its colour band tables (Section 3.4) 100 / 80 /
  40 / 20 / 0 %. The text values are the default; use
  `band_fractions=BAND_FRACTIONS_TABLE` for the table values.
- Limits are in `DUMMY_LIMITS` and `CHEST_COMPRESSION_LIMITS` (by test
  speed), in N, N m, mm, g and m/s.

The limit tables are tested against Section 3.5 of the protocol.

### Bharat NCAP adult occupant scoring (AIS-197)

ODB frontal at 64 km/h (Hybrid III 50th driver and passenger) and MDB
side at 50 km/h (ES-2), 16 points each, plus the 29 km/h pole test:

```python
from crashmetrics.bncap import (
    FrontalOccupant, SideOccupant, a_pillar_modifier, aop_rating,
    backplate_modifier, score_frontal, score_side,
)

driver = FrontalOccupant(
    hic15=600.0, head_a3ms=60.0,                 # used with hard contact
    neck_shear=(t, fx), neck_tension=(t, fz),    # time histories, N
    neck_extension=30.0, chest_compression=32.0, viscous_criterion=0.6,
    femur=((t, fz_femur_l), (t, fz_femur_r)),    # compression negative
    knee_displacement=(3.0, 10.5), tibia_index=(0.85, 0.3),
    tibia_force=(1000.0, 5000.0), pedal_rearward=150.0,
    modifiers={"chest": a_pillar_modifier(150.0)},   # points to subtract
)
frontal = score_frontal(driver, passenger, door_openings=0)
side = score_side(SideOccupant(hic15=400.0, head_a3ms=60.0,
                               rib_deflection=32.0, rib_vc=0.66,
                               abdominal_force=1500.0, pubic_force=3000.0,
                               modifiers={"chest": backplate_modifier(2500.0)}))
rating = aop_rating(frontal, side, max_stars_allowed=5)
print(rating.stars, rating.points, rating.reasons)
```

- **Points**: each criterion scores 0–4 linearly between its higher and
  lower performance limit; neck shear, neck tension and femur
  compression are scored from their cumulative exceedance curves between
  two force–duration curves (the lowest point on the curve). A region
  takes its worst criterion, then point modifiers are subtracted; scores
  are rounded to 3 decimals. Frontal groups (head & neck, chest,
  knee/femur/pelvis, leg & foot) take the worst of driver and passenger.
- **Modifiers**: helpers for the sliding ones (steering column,
  A-pillar, pedal upward and blocking, backplate, T12); fixed ones
  (airbags, steering wheel contact, belt load, knee contact, footwell,
  door opening, fuel leakage) are passed as points.
- **Rating**: 27 / 22 / 16 / 10 / 4 points for 5 to 1 stars; 0 stars if
  a capping limit is exceeded, at most 1 star if a critical region is
  red, one star less if front and side differ by more than 35 %
  (unless both exceed 8.2 points and the total exceeds 22), and
  `max_stars_allowed` for the safety assist qualifiers.
  `pole_test_passed` checks the pole test; `cop_stars` converts child
  occupant points to stars.

### Tibia Index and femur force

Forces in N, moments in N m, compression negative by default (Euro
NCAP convention):

```python
from crashmetrics.lower_extremity import femur_force_criterion, tibia_index

ti = tibia_index(t, mx_upper, my_upper, fz_upper, dummy="hybrid3_50")
print(f"TI upper = {ti.value:.2f}")

femur = femur_force_criterion(t, fz_femur, limit="r94_hybrid3_50")
print(f"Peak {femur.peak_compression/1000:.2f} kN, utilisation {femur.utilisation:.2f}, passed {femur.passed}")
```

- `tibia_index`: `TI = |MR/MRc| + |Fz/Fzc|` while the tibia is in
  compression, zero otherwise, with `MR = sqrt(Mx² + My²)`. Critical
  values for Hybrid III 50th, 5th, 95th and THOR are taken from Euro
  NCAP CP 005 (`TIBIA_INDEX_CRITICAL_VALUES`); you can also pass your
  own.
- `femur_force_criterion`: builds the exceedance curve (force reached
  or exceeded versus duration) and compares it with a force–time limit.
  `"r94_hybrid3_50"` is the UN-ECE R94 limit of 9.07 kN at 0 ms falling
  to 7.58 kN at 10 ms and longer; you can pass your own points. The
  default `mode="cumulative"` adds up separate intervals; use
  `mode="continuous"` if your regulation requires a single interval.

Check all constants against the protocol version you assess to.

### 3 ms clip

`clip_3ms` returns the highest level that the signal reaches or
exceeds for 3 ms (change with `duration_ms`):

- `mode="cumulative"` (default): 3 ms in total, possibly over several
  separate intervals. Computed exactly for the linearly interpolated
  signal.
- `mode="continuous"`: 3 ms in a single interval. Never higher than
  the cumulative value.

Check which definition your assessment protocol requires.

### CFC filter

`cfc_filter` implements the SAE J211-1 Appendix C digital filter: a
2-pole Butterworth low-pass run forward and backward, giving a
phaseless 4-pole response. The tests check the gain against the J211
corridor points for CFC 60, 180, 600 and 1000 (flat to the CFC
frequency, about −3 dB at 1.65 × CFC). The sample rate must exceed
2 × 2.0775 × CFC (about 4.2 kHz for CFC 1000).

Each end of the signal is padded by odd reflection (`pad_ms`, default
10 ms) to reduce start-up transients. This padding choice is part of
this package, not of J211; confirm it matches your protocol.

## HIC units and numerical method

- Time input: seconds
- Acceleration input: non-negative resultant magnitude in g
- HIC window: milliseconds
- Numerical integration: trapezoidal rule on a refined, linearly interpolated time grid

Results depend on the selected grid resolution and the numerical method.

If the record is shorter than `window_ms`, `calculate_hic` issues a `UserWarning` and evaluates HIC over the available duration. Make sure the record contains the whole impact.

## Development

Clone the repository and install it in editable mode with the
development tools (pytest, ruff, mypy, build):

```bash
git clone https://github.com/vsk1729/crashmetrics.git
cd crashmetrics
python -m pip install -e ".[dev]"
```

Run the same checks as CI before opening a pull request:

```bash
python -m pytest      # tests
ruff check .          # lint
mypy                  # type check
```

`examples/hic_convergence.py` shows how the HIC result changes with
`resolution_ms`; run it after changing the HIC algorithm.

The version is set only in `src/crashmetrics/__init__.py`. Record
user-visible changes in [CHANGELOG.md](CHANGELOG.md).

### Releasing

Releases are published by `.github/workflows/release.yml` using PyPI
Trusted Publishing, so no API tokens are stored in the repository.

1. Bump `__version__` and add the CHANGELOG entry; merge to `main`.
2. Optional dry run: run the **Release** workflow manually from the
   Actions tab to publish to TestPyPI.
3. Publish a GitHub release with tag `v<version>`, for example
   `v0.3.0`. The workflow checks the tag matches `__version__`,
   builds and checks the sdist and wheel, and publishes to PyPI.

A version can be uploaded to PyPI only once; fix mistakes with a new
version.

## Engineering disclaimer

This software is an engineering calculation aid. Users must independently validate numerical results and confirm that input processing, filtering, sampling, and calculation methods match the applicable assessment protocol. The software does not certify regulatory compliance.

## Trademarks and affiliation

crashmetrics is an independent open-source project. It is not
affiliated with, endorsed by or sponsored by Ansys, Euro NCAP, UNECE or
any other organisation whose software, file formats, protocols or
regulations it refers to. LS-DYNA, Ansys and Euro NCAP are trademarks or
registered trademarks of their respective owners and are used here only
to describe compatibility.

The LS-DYNA readers were written from the text layout of output files;
no LS-DYNA code or documentation is included.

## License

MIT. See the LICENSE file.