"""Example 35: check an LS-DYNA keyword deck before running it, then edit it.

Real decks (MIT licence, see tests/data/lsdyna/README.md): a ball dropped
on a plate and a tube crushed against a rigid wall, both written for
LS-DYNA R14, and a small deck with a deliberate fault.

1. Read: files, includes, version, unknown keywords.
2. Model table: parts, masses and centre of gravity (equal to what
   LS-DYNA printed in d3hsp for this run), estimated time step.
3. Checks: a clean deck and one with a missing section.
4. Load case and output requirements for crashmetrics' analyses.
5. Edit: thickness, end time, impact speed, missing outputs; write back
   with only the changed lines different.
6. DOE: three variants from a Latin hypercube.
"""

from pathlib import Path

from crashmetrics import deck as dk
from crashmetrics.doe import latin_hypercube

data = Path(__file__).resolve().parents[1] / "tests" / "data" / "lsdyna"
ball = data / "kagent" / "cold_start" / "ball_drop.k"
tube = data / "kagent" / "crash" / "crash.k"
broken = data / "lsprepost_mcp" / "impact_broken.k"

# --- 1. Read --------------------------------------------------------------------
deck = dk.read_deck(ball)
print(deck.info.summary())
print("files:", ", ".join(f.name for f in deck.files))

# --- 2. Model table -------------------------------------------------------------
summary = dk.model_summary(deck)  # units guessed from the materials: mm-s-t
print()
print(summary.summary())
print(summary.table())
print("d3hsp of this run: part 1 1.2149954E-04, part 2 1.2569384E-05, "
      "centre z 2.8125846")
print(dk.time_steps(deck).summary(top=1))
print("d3hsp of this run: smallest time step 8.4091E-07")

# --- 3. Checks ------------------------------------------------------------------
print()
print(dk.check_deck(deck).summary())
print(dk.check_deck(dk.read_deck(broken)).summary())

# --- 4. Load case and outputs ---------------------------------------------------
crash = dk.read_deck(tube)
print()
print(dk.load_case(crash).summary())
print(dk.output_requirements(crash, ["quality", "contacts", "nodes"]).summary())

# --- 5. Edit and write back -----------------------------------------------------
dk.set_thickness(crash, 1, 1.8)
dk.set_end_time(crash, 6e-3)
dk.set_initial_velocity(crash, speed=15_000.0)  # 54 km/h in mm/s
for change in dk.prepare_outputs(crash, ["quality", "contacts", "nodes"],
                                 dt=1e-5, node_dt=1e-6):
    print("added:", change)
dk.add_history_nodes(crash, [1, 49, 97])
written = crash.write("edited", only_modified=True)
print("written:", ", ".join(p.name for p in written), "(mesh_tube.k unchanged)")
before = tube.read_text().splitlines()
after = written[0].read_text().splitlines()
for old, new in zip(before[:-1], after):
    if old != new:
        print(f"  - {old}\n  + {new}")
print(f"  + {len(after) - len(before)} new lines before *END")
again = dk.read_deck(written[0])
print(dk.output_requirements(again, ["quality", "contacts", "nodes"]).summary())

# --- 6. DOE variants ------------------------------------------------------------
design = latin_hypercube({"thickness": (1.2, 2.0), "speed": (12_000.0, 16_000.0)},
                         3, seed=7)
table = dk.write_variants(
    tube, design, "doe",
    setters={"thickness": lambda d, t: dk.set_thickness(d, 1, t),
             "speed": lambda d, v: dk.set_initial_velocity(d, speed=v)},
)
print()
print(table.read_text().strip())
for run in sorted(Path("doe").glob("run_*")):
    d = dk.read_deck(run / "crash.k")
    s, lc = dk.model_summary(d), dk.load_case(d)
    print(f"{run.name}: t {s.part(1).thickness:g} mm, mass {s.mass_kg:.3f} kg, "
          f"{lc.kmh(lc.speeds[0]):.1f} km/h")
