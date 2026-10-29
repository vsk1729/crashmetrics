---
title: 'crashmetrics: open, verified crash-safety metrics from vehicle tests and LS-DYNA simulations in Python'
tags:
  - Python
  - crashworthiness
  - vehicle safety
  - injury criteria
  - Euro NCAP
  - Bharat NCAP
  - LS-DYNA
  - CAE
authors:
  - name: Satish Kumar Voonna
    orcid: 0000-0000-0000-0000
    affiliation: 1
affiliations:
  - name: Independent researcher, India
    index: 1
date: 29 October 2026
bibliography: paper.bib
---

# Summary

Vehicle crash safety is assessed with injury criteria computed from
dummy and impactor signals, such as the Head Injury Criterion (HIC)
[@versace1971], the Brain Injury Criterion [@takhounts2013bric] and the
neck injury criterion Nij, and with the scoring rules of consumer
programmes and regulations that turn those criteria into points, colours
and star ratings. The same calculations are applied to physical tests
and, in far larger numbers, to finite element simulations, mostly run
with LS-DYNA.

`crashmetrics` is a Python package that implements these calculations in
one tested, documented library with NumPy [@harris2020numpy] as its only
dependency. It covers SAE J211 channel filtering [@saej211]; head, neck,
chest, abdomen, pelvis and lower-extremity criteria for the Hybrid III,
THOR, ES-2, WorldSID, BioRID and Q-series dummies [@euroncap_cp005;
@gabler2019damage]; the Euro NCAP 2026 frontal, side, far-side, rear and
pedestrian assessments [@euroncap_frontal; @euroncap_side]; Bharat NCAP
adult and child occupant scoring and star rating [@ais197];
pedestrian compliance under AIS-100 [@ais100]; pass/fail homologation
checks for UN R94, R95 and R135 and post-crash electrical safety
[@unr94]; intrusion measurement; test-versus-simulation correlation with
ISO/TS 18571 and a corridor and cross-correlation rating [@iso18571;
@gehre2009cora]; readers for LS-DYNA ASCII output with energy-balance
checks; and feature extraction that turns runs into tables for
statistical and machine-learning studies.

# Statement of need

Researchers and engineers in vehicle safety repeatedly reimplement the
same criteria and scoring rules in spreadsheets, scripts or macros of
commercial post-processors. The protocols are long and change often:
Euro NCAP revised its whole crash protection scheme in 2026, and India
introduced Bharat NCAP in 2023. Small differences in interpretation
(the HIC time grid, filter padding, how a sliding scale is capped, which
modifier applies) change results, yet such choices are rarely written
down. This makes results hard to compare between groups and studies hard
to reproduce.

`crashmetrics` targets three groups: researchers who study occupant and
pedestrian protection with simulation or test data and need citable,
inspectable implementations; engineers who automate design-of-experiment
and optimisation loops around crash simulations; and teaching, where
students can follow a protocol from a signal to a star rating. Every
interpretation the package makes where a protocol is ambiguous is listed
in a dedicated protocol-notes page with the reasoning and the parameter
that changes it.

# State of the field

Injury criteria and rating templates are available in commercial
post-processors such as LS-PrePost, Oasys T/HIS, Altair HyperGraph and
d3VIEW, but their implementations are closed and tied to the tools'
licences and file formats. Open-source Python projects address other
parts of the workflow: `lasso-python` [@lassopython] reads LS-DYNA binary
results, `PyDyna` [@pydyna] builds and runs LS-DYNA input decks, and
`objective-rating-metrics` [@orm] implements the ISO/TS 18571 metric. To
the author's knowledge, no open-source package combines injury criteria,
current consumer-test and regulatory scoring (in particular Bharat NCAP
and the Euro NCAP 2026 protocols), simulation output readers and
correlation metrics with documented interpretations and tests against
the protocols' own worked examples. `crashmetrics` complements the
existing readers: its channel names follow the LS-DYNA binout variable
names, so arrays read with other tools can be passed in directly.

# Software design

The package is organised by task (`signals`, `head`, `neck`, `thorax`,
`pedestrian`, `frontal_scoring`, `side_scoring`, `whiplash`, `bncap`,
`homologation`, `correlation`, `intrusion`, `lsdyna_ascii`, `features`
and others). Functions take plain NumPy arrays in SI units or g, so they
work with test data, simulation output or arrays from other readers, and
return small frozen dataclasses that carry the value together with its
context (for HIC the time window, for a score each criterion's limit,
points and colour). Scoring functions build on shared, protocol-neutral
pieces (sliding scales, capping, modifiers), and each protocol version
is a data table of limits that can be overridden.

Correctness is addressed in four ways. First, the test suite (over 640
tests, run on Python 3.10 to 3.13 and NumPy 1.24 to 2.x) reproduces the
worked examples published in the protocols wherever they exist, for
example the child-restraint installation example of AIS-197, and checks
other formulas against hand calculations and closed-form solutions.
Second, the ISO/TS 18571 implementation agrees with an independent
implementation [@orm] to $10^{-15}$ on 40 crash-like signal pairs.
Third, the LS-DYNA readers were run on real output files from public
projects and compared value by value with a second, independent parser;
for 36 runs of a published helmet study [@helmetstudy], HIC, BrIC and
neck moments recomputed from the arrays read by `crashmetrics` equal the
study's own results to $10^{-15}$. Fourth, eighteen runnable examples
are executed in continuous integration and their printed output is
compared with the output shown in the documentation, so the
documentation cannot drift from the code.

# Research impact statement

<!-- TODO before submission: replace with real, verifiable evidence of
research use (studies, theses, reports or projects that used
crashmetrics, with links or DOIs). JOSS does not accept planned or
aspirational use. -->

`crashmetrics` is used by the author for research on automated
assessment of crash simulations, including correlation of simulation
models with tests and the generation of training data for surrogate
models of injury criteria. The package is distributed on PyPI, and its
documentation, with step-by-step guides for each load case, is published
at <https://vsk1729.github.io/crashmetrics/>.

# AI usage disclosure

Generative AI was used in the development of this software and paper.
The author used Claude (Anthropic; model Claude Opus 5.5, through Claude
Code) to write and revise source code, tests, documentation, examples
and a first draft of this paper. The author defined the scope and
design of each module, selected the protocols and their versions,
decided every protocol interpretation, and reviewed, edited and
validated all AI-assisted output, including the verification against
protocol examples and real LS-DYNA output described above. The author
takes full responsibility for the content.

# Conflict of interest and funding

The author is employed in the automotive industry and developed
`crashmetrics` in a personal capacity, outside of employment, using only
publicly available protocols and data. The work received no funding.
The author declares no competing interests.

# Acknowledgements

The author thanks the authors of the public LS-DYNA projects whose output
files were used for verification, in particular P. D. for the
MIT-licensed helmet study data [@helmetstudy].

# References
