"""Python tools for automotive crash engineering.

Modules
-------
crashmetrics.signals
    CFC filtering, resultants, unit conversion and resampling.
crashmetrics.pedestrian
    HIC, Euro NCAP pedestrian scoring (headform, legforms, total),
    Flex-PLI criteria and scoring, and AIS-100 compliance checks.
crashmetrics.acceleration
    Peak acceleration and the 3 ms clip.
crashmetrics.energy
    Energy and force-displacement metrics.
crashmetrics.lsdyna, crashmetrics.d3hsp
    LS-DYNA glstat, matsum and d3hsp readers.
crashmetrics.lsdyna_ascii
    LS-DYNA ASCII output readers (nodout, rcforc, sleout, secforc, rwforc,
    sbtout, deforc, jntforc, abstat, rbdout, spcforc, swforc).
crashmetrics.energy_check
    Simulation energy checks for any load case.
crashmetrics.pulse
    Occupant Load Criterion and crash pulse summary.
crashmetrics.head
    DAMAGE, BrIC and the frontal loading phase.
crashmetrics.neck
    Neck loads, occipital condyle moment, force-duration limits and Nij.
crashmetrics.thorax
    Chest deflection, VC, THOR Rmax and abdomen deflection, and CTI.
crashmetrics.pelvis
    THOR acetabulum force and iliac force drop.
crashmetrics.lower_extremity
    Tibia Index, tibia compression, knee slider and femur force.
crashmetrics.frontal_scoring
    Euro NCAP MPDB and full width test scoring.
crashmetrics.side
    ES-2 side impact criteria.
crashmetrics.bncap
    Bharat NCAP (AIS-197) adult occupant scoring and star rating.
"""

# Single source of the package version; pyproject.toml reads it.
__version__ = "0.12.0"
