# Contributing to crashmetrics

Thank you for helping. crashmetrics is a NumPy-only Python library for
automotive crash safety calculations: SAE J211 signals, HIC, Euro NCAP,
Bharat NCAP (AIS-197), AIS-100, UN R94 / R95 / R135, whiplash, intrusion,
LS-DYNA ASCII readers, test-versus-CAE correlation (ISO/TS 18571) and
DOE / ML analytics. Crash engineers, LS-DYNA users, protocol reviewers
and Python developers are all welcome here.

## Contents

1. [What you can contribute](#1-what-you-can-contribute)
2. [Quick start](#2-quick-start)
3. [Repository map](#3-repository-map)
4. [Coding standards](#4-coding-standards)
5. [Adding a protocol or criterion](#5-adding-a-protocol-or-criterion)
6. [Adding an LS-DYNA reader or fixing a format](#6-adding-an-ls-dyna-reader-or-fixing-a-format)
7. [Adding an example](#7-adding-an-example)
8. [Adding a test](#8-adding-a-test)
9. [Documentation](#9-documentation)
10. [Reporting bugs and requesting features](#10-reporting-bugs-and-requesting-features)
11. [Pull request checklist](#11-pull-request-checklist)
12. [Branches and commits](#12-branches-and-commits)
13. [Review process](#13-review-process)
14. [Licensing and sources](#14-licensing-and-sources)
15. [Getting help](#15-getting-help)

## 1. What you can contribute

- **Bug reports**: a wrong value, a crash, a file that does not parse.
- **Protocol corrections**: a limit, formula or interpretation that does
  not match the public protocol. These are the most valuable reports.
- **New criteria and protocols**, from public sources.
- **LS-DYNA format reports**: output from a version or keyword the
  readers do not handle yet.
- **Test data**: small, openly licensed test or CAE output (see
  [section 14](#14-licensing-and-sources)).
- **Examples and documentation**: clearer explanations, worked cases.

**Respect the disclaimer.** crashmetrics is an engineering aid, not a
certification tool, and it is not affiliated with Ansys, Euro NCAP,
Bharat NCAP, ARAI, UNECE, ISO, PDB or any other organisation it refers
to. Contributions must not include proprietary code or documentation
(LS-DYNA or otherwise) or copied protocol text. Formulas and limit
values from public sources, cited and in your own words, are fine.

## 2. Quick start

```bash
# Fork on GitHub, then:
git clone https://github.com/<your-user>/crashmetrics.git
cd crashmetrics
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev,docs]"
```

The checks that CI runs (confirm against `.github/workflows/tests.yml`
and `docs.yml`):

```bash
python -m pytest -q                # all tests, including every example's output
ruff check .                       # lint (line length 88, import order)
mypy                               # type check of src/
mkdocs build --strict              # documentation; warnings fail the build
```

Run one example, or preview the docs:

```bash
python examples/07_bharat_ncap.py
mkdocs serve                       # http://127.0.0.1:8000
```

CI runs the tests on Python 3.10-3.13 with the latest NumPy and on
Python 3.10 with NumPy 1.24, the oldest supported version. The release
workflow also installs the built wheel on Python 3.10-3.13 and runs the
whole suite against it.

## 3. Repository map

| Path | Purpose | Who touches it |
| --- | --- | --- |
| `src/crashmetrics/` | Package source: one module per domain (`signals`, `head`, `neck`, `bncap`, `homologation`, `lsdyna_ascii`, ...); `pedestrian/` is a subpackage | Everyone adding or fixing code |
| `tests/` | pytest suite, one `test_<module>.py` per module | Everyone; every change needs tests |
| `tests/data/` | Small real output files, each folder with its licence and a README | Contributors adding readers or data |
| `examples/` | Numbered runnable scripts `NN_topic.py` | Feature authors |
| `examples/expected/` | The exact output of each numbered example, checked by the tests | Regenerated, never hand-edited |
| `docs/` | MkDocs site: guides, protocol notes, API reference pages | Feature and docs authors |
| `.github/workflows/` | CI: tests, docs, release | Maintainer |
| `CHANGELOG.md`, `CITATION.cff`, `pyproject.toml` | Change log, citation, packaging | Changelog: everyone; the others: maintainer at release |

## 4. Coding standards

- **Style**: PEP 8, enforced by `ruff` (line length 88). There is no
  separate formatter; keep the style of the surrounding code.
- **Types**: type hints on every public function and class; `mypy` must
  pass.
- **Docstrings**: NumPy style (the API reference is generated from
  them). Extra paragraphs go under a `Notes` heading, or the strict docs
  build fails.
- **Units**: every input and output states its unit in the docstring.
  The library uses SI units with a few protocol exceptions: time in s,
  head and chest acceleration in g, force in N, moment in N m,
  deflection in mm (see [Units, signs and filters](https://vsk1729.github.io/crashmetrics/getting-started/conventions/)).
  LS-DYNA readers return values in the model's units (often
  mm-ms-kg or mm-s-t); say so and never convert silently.
- **Naming**: modules named after the domain, functions `snake_case`,
  classes `PascalCase`, constants `UPPER_CASE`. Private helpers start
  with `_`.
- **Results**: return frozen dataclasses, not dicts or tuples. Pass/fail
  results follow the existing pattern (`passed`, `utilisation` against
  the limit, a `summary()`); reuse `homologation.ComplianceResult` or
  the `_scoring` helpers where they fit.
- **Public API**: a new public symbol needs a docstring with units, type
  hints, a test, an entry in `__all__` and a mention in the docs.
- **Dependencies**: the only runtime dependency is NumPy (>= 1.24).
  Open an issue before proposing another one. Optional imports for
  convenience (such as pandas output) must fail with a clear message.
- **Regulatory modules**: state in the module docstring that the code
  is an engineering aid, not a certification tool, and record every
  interpretation in `docs/protocol-notes.md`.

## 5. Adding a protocol or criterion

This is the most common larger contribution. Follow the steps in order.

1. **Open an issue first** with:
   - protocol name, issuing body, document number, version and date;
   - the formulas, limits and units, with section numbers;
   - any worked example in the document;
   - anything the document leaves open and how you would interpret it.
2. **Write the code** in the matching module of `src/crashmetrics/`, or
   a new module for a new domain. Inputs as plain arrays and floats (or a
   small input dataclass when there are many), results as a frozen
   dataclass.
3. **Cite the source** in the docstring: document, version, section.
   State each interpretation you made.
4. **Test it** (see [section 8](#8-adding-a-test)): at least one value
   calculated by hand, and the document's worked example if it has one.
5. **Add an example** if the feature is user-facing (see
   [section 7](#7-adding-an-example)).
6. **Document it**: a guide section or page in `docs/guides/`, the
   reference page in `docs/reference/` (an mkdocstrings `:::` line),
   `mkdocs.yml` nav, a row in `docs/protocol-notes.md` for each
   interpretation, and the feature tables in `README.md` and
   `docs/index.md` if it is a new area.
7. **Update `CHANGELOG.md`** under `## [Unreleased]`.

## 6. Adding an LS-DYNA reader or fixing a format

The readers in `lsdyna_ascii.py`, `lsdyna.py` and `d3hsp.py` parse the
**text layout** of output files only. No LS-DYNA code or documentation
is included, and none should be added.

Please include in the issue or pull request:

- the LS-DYNA version and precision (from the file header or `d3hsp`),
  SMP or MPP, and platform if known;
- a **minimal sample**: the header and a few data blocks that show the
  problem, with model names, paths and host names removed;
- what you expected the reader to return (times, IDs, values).

Real files can be added under `tests/data/lsdyna/<source>/` only if they
are MIT-licensed (or your own and you release them under MIT). Add the
licence file and a section in `tests/data/lsdyna/README.md` naming the
source, commit and LS-DYNA version; that README is the record of which
versions are tested. Files under other licences stay on your computer:
describe the layout in the issue instead.

## 7. Adding an example

- **Name**: `examples/NN_topic.py`, the next free two-digit number,
  topic in `snake_case`.
- **Self-contained**: synthetic data, or a small committed file under
  `tests/data/`. No network access, no randomness without a fixed seed.
- **Deterministic output**: it must print the same text on every
  supported Python and NumPy version. Round printed numbers, and turn
  `-0.00` into `0.00` (for example `round(v, 2) + 0.0`).
- **Expected output**: generate it, then read it:

  ```bash
  CRASHMETRICS_UPDATE_EXAMPLES=1 python -m pytest tests/test_examples.py -k NN
  git diff examples/expected
  ```

  `tests/test_examples.py` finds every numbered script automatically and
  compares its output with `examples/expected/NN_topic.txt`; no new test
  is needed.
- **Link it**: add a row to `examples/README.md` and the guides table in
  `docs/guides/index.md`, include the script and its output in the
  guide with `--8<--`, and update the example count in `README.md`.

## 8. Adding a test

- Files are `tests/test_<module>.py`; tests are plain `test_*` functions.
- The kinds of tests the project uses:

  | Kind | Example |
  | --- | --- |
  | Hand calculation or closed form | Constant acceleration gives `HIC = T * a^2.5` |
  | Protocol worked example | A value table or example printed in the protocol |
  | Independent reference | A brute-force search, or another open-source tool's numbers |
  | Property | Scaling (`HIC ~ a^2.5`), monotonicity, unit round trips |
  | Errors | Invalid input raises `ValueError` with a clear message |
  | Example output | Automatic, see section 7 |

- **Tolerances**: use `pytest.approx` with an explicit `rel` or `abs`.
  Closed forms should match to `1e-9` or better. Against protocol tables,
  match the precision the document prints (crash criteria are usually
  given to 3-4 significant figures).
- **Analytics and ML code** needs a check against a known answer: for
  example PRCC on a linear model, sampling designs against their
  definition, Monte Carlo against an analytical probability.
- Tests must pass on NumPy 1.24 as well as the latest NumPy.

## 9. Documentation

- Sources live in `docs/` and are built with MkDocs Material; the API
  reference is generated from docstrings, so do not copy signatures by
  hand.
- **Style**: short sentences, a unit on every number, cite the public
  document, and say what the code assumes.
- **Protocol notes**: every interpretation (anything the protocol leaves
  open or that the code simplifies) gets a row in
  `docs/protocol-notes.md`.
- Examples in the docs are included from `examples/` with `--8<--`, so
  they cannot drift from the tested code.
- Check with `mkdocs build --strict` before pushing.

## 10. Reporting bugs and requesting features

Search the [existing issues](https://github.com/vsk1729/crashmetrics/issues)
first.

**Bug report**

- crashmetrics version (`python -c "import crashmetrics; print(crashmetrics.__version__)"`),
  Python version, NumPy version, operating system;
- a minimal script that shows the problem;
- what you expected and what you got (paste the full traceback);
- for file readers: the solver or file version and a minimal, cleaned
  sample (see [section 6](#6-adding-an-ls-dyna-reader-or-fixing-a-format)).

**Feature request**

- the area (frontal, side, pedestrian, signals, LS-DYNA, analytics, ...);
- the public source: document, version, date, sections;
- formulas, limits and units, and any worked example;
- whether you can provide a test case or test data.

## 11. Pull request checklist

- [ ] Linked issue (for anything larger than a small fix)
- [ ] Tests added or updated; `python -m pytest -q` passes
- [ ] `ruff check .` and `mypy` pass
- [ ] Example added for a new feature, with its expected output regenerated
- [ ] Docs updated (guide, reference page, `mkdocs.yml`, protocol notes);
      `mkdocs build --strict` passes
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
- [ ] No new runtime dependency (or agreed in the issue)
- [ ] Sources cited and interpretations noted; no copied protocol text
- [ ] Type hints and docstrings (with units) on public symbols
- [ ] Any new test data is MIT-licensed, with its licence and README entry
- [ ] CI green

## 12. Branches and commits

- **Branches**: `feat/<area>-<short-desc>`, `fix/<area>-<short-desc>`,
  `docs/<short-desc>` (for example `fix/lsdyna-nodout-mpp-header`).
- **Commits**: a short imperative summary line ("Add ES-2re rib
  deflection criterion", "Fix nodout parsing for MPP headers"), then a
  blank line and the why if it is not obvious.
- **One logical change per pull request**, and keep it reviewable
  (ideally under about 400 changed lines, test data excluded).
- Pull requests are squash-merged, so the PR title becomes the commit on
  `main`; make it descriptive.
- Do not change the version number; releases are made by the maintainer
  (see [Development and releases](https://vsk1729.github.io/crashmetrics/about/development/)).

## 13. Review process

- The maintainer aims to respond within about a week. This is a
  best-effort goal for a project maintained in spare time.
- Reviews focus on: correctness against the public source, units,
  numerical tolerances, test coverage, documentation, and the
  disclaimer and licensing rules.
- Be kind and assume good faith. Disagreements about a protocol are
  settled by citing the public document; where it is genuinely
  ambiguous, the choice is recorded in the protocol notes.

## 14. Licensing and sources

- crashmetrics is MIT-licensed. By submitting a pull request you agree
  that your contribution is released under the MIT licence.
- **Protocols and standards**: paraphrase formulas in your own words,
  give limit values and cite document, version and section. Do not paste
  protocol or standard text, tables or figures.
- **Third-party code**: only MIT-compatible code, with its copyright
  notice kept, and only when there is a real reason not to write it
  yourself.
- **Test data**: only files under the MIT licence are committed, each
  with its licence file and a README entry giving the source. Data under
  other licences, and any employer or customer data, must never be
  committed.
- If your contribution adapts a published method in a substantial way,
  cite the paper in the docstring and the guide's References section.

## 15. Getting help

- **Questions and ideas**: open an [issue](https://github.com/vsk1729/crashmetrics/issues)
  (the `question` label is fine).
- **Docs**: <https://vsk1729.github.io/crashmetrics/>, especially the
  guides and the protocol notes.
- **Examples**: the `examples/` folder, one script per topic, with its
  output in `examples/expected/`.
- **First contribution?** Look for issues labelled
  [`good first issue`](https://github.com/vsk1729/crashmetrics/labels/good%20first%20issue);
  the maintainer tags them.

---

Thank you to everyone who reports a problem, checks a value against a
protocol or improves the docs. Crash engineers, LS-DYNA users and NCAP
protocol reviewers are especially welcome: domain review is what keeps
the numbers right.
