"""Make the README overview figure and the GitHub social preview image.

Every number in the pictures comes from crashmetrics, run on the
synthetic data of the examples (01, 22, 27 and 29). Needs matplotlib,
which is not a crashmetrics dependency:

    python -m pip install matplotlib
    python tools/make_readme_images.py

Writes docs/assets/overview.png and docs/assets/social-preview.png.
"""

from __future__ import annotations

import contextlib
import io
import os
import runpy
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"

# Reference palette (first three categorical slots, light mode), text and
# surface tokens.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
SURFACE, GRID = "#fcfcfb", "#e4e3df"


def run_example(name: str) -> dict:
    """Run an example quietly in a temporary folder; return its globals."""
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return runpy.run_path(str(ROOT / "examples" / name))
        finally:
            os.chdir(here)


def style(ax, title: str, subtitle: str) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0, pad=4)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK,
                 pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9.5, color=INK2,
            va="bottom")


def label(ax, x, y, text, color=INK2, **kw):
    ax.annotate(text, (x, y), fontsize=9, color=color, **kw)


def hic_panel(ax, ex) -> None:
    t_ms = ex["t"] * 1000.0
    a = ex["a_res"]
    hic = ex["hic"]
    style(ax, "Injury criteria", "Headform resultant (CFC 1000) and its HIC15 window")
    t0, t1 = hic.start_time * 1000.0, hic.end_time * 1000.0
    ax.axvspan(t0, t1, color=BLUE, alpha=0.10, linewidth=0)
    ax.plot(t_ms, a, color=BLUE, linewidth=2)
    ax.set_xlim(0, 20)
    ax.set_ylim(0, float(np.max(a)) * 1.25)
    label(ax, 11.0, float(np.max(a)) * 0.92, f"HIC15 = {hic.value:.0f}\n"
          f"window {t0:.1f}–{t1:.1f} ms (shaded)", color=INK, va="center")
    ax.set_xlabel("Time (ms)", color=INK2, fontsize=9)
    ax.set_ylabel("Acceleration (g)", color=INK2, fontsize=9)


def ncap_panel(ax, ex) -> None:
    card = ex["card"]
    losses = sorted(card.losses, key=lambda x: x.lost)[-6:]
    def cause(c: str) -> str:
        return c.replace("hic15", "HIC15").replace("_", " ")

    names = [f"{x.occupant} {x.region.replace('_', ' ')}: {cause(x.cause)}"
             for x in losses]
    style(ax, "NCAP scoring",
          f"Bharat NCAP: {card.total:.1f} / 32 points, {card.stars} stars. "
          "Where the points are lost:")
    y = np.arange(len(losses))
    ax.barh(y, [x.lost for x in losses], height=0.62, color=BLUE)
    ax.set_yticks(y, names)
    ax.tick_params(axis="y", labelsize=9, colors=INK)
    ax.grid(False, axis="y")
    for yi, x in zip(y, losses):
        label(ax, x.lost + 0.05, yi, f"{x.lost:.2f}", color=INK, va="center")
    ax.set_xlim(0, max(x.lost for x in losses) * 1.2)
    ax.set_xlabel("Points lost", color=INK2, fontsize=9)


def material_panel(ax, ex) -> None:
    test, full, curve = ex["test"], ex["full"], ex["curve"]
    style(ax, "Material cards",
          "Tensile test to the *MAT_024 curve, extrapolated beyond necking")
    ax.plot(test.strain, test.stress, color=BLUE, linewidth=2,
            label="Tensile test (engineering stress vs strain)")
    measured = full.plastic_strain <= curve.necking_strain + 1e-9
    ax.plot(full.plastic_strain[measured], full.stress[measured], color=ORANGE,
            linewidth=2, label="Card curve (true stress vs plastic strain)")
    ax.plot(full.plastic_strain[~measured], full.stress[~measured], color=ORANGE,
            linewidth=2, linestyle=(0, (4, 2)), label="Swift-Voce extrapolation")
    s_neck = float(np.interp(curve.necking_strain, full.plastic_strain, full.stress))
    ax.plot([curve.necking_strain], [s_neck], "o", color=ORANGE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2)
    label(ax, curve.necking_strain, s_neck + 45, "necking", color=INK2,
          ha="center")
    ax.set_xlim(0, 0.6)
    ax.set_ylim(0, 1100)
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK)
    ax.set_xlabel("Strain", color=INK2, fontsize=9)
    ax.set_ylabel("Stress (MPa)", color=INK2, fontsize=9)


def worst(fit) -> str:
    """Largest error of the predicted fracture strain over the tests."""
    return f"{np.max(np.abs(fit.errors)) * 100:.0f} %"


def gissmo_panel(ax, ex, *, compact: bool = False) -> None:
    tests, hc, jc = ex["tests"], ex["hc"], ex["jc"]
    if compact:
        style(ax, "GISSMO failure curve", "Fracture tests, two fitted models")
    else:
        style(ax, "Failure (GISSMO)",
              "Failure strain vs stress triaxiality, fitted to five fracture tests")
    x = np.linspace(-0.05, 2 / 3, 300)
    ax.plot([t.eta for t in tests], [t.fracture_strain for t in tests], "o",
            color=BLUE, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2,
            zorder=3, label="Fracture tests (path-average triaxiality)")
    ax.plot(x, hc(x), color=ORANGE, linewidth=2,
            label=f"Hosford-Coulomb: worst test {worst(hc)}")
    ax.plot(x, jc(x), color=AQUA, linewidth=2, linestyle=(0, (4, 2)),
            label=f"Johnson-Cook: worst test {worst(jc)}")
    ax.set_xlim(-0.05, 0.72)
    ax.set_ylim(0.25, 0.68)
    label(ax, 0.565, 0.345, "plane strain", color=INK2, ha="center")
    ax.legend(loc="lower left", frameon=False, fontsize=9 if not compact else 10,
              labelcolor=INK)
    ax.set_xlabel("Stress triaxiality", color=INK2, fontsize=9)
    ax.set_ylabel("Plastic strain to failure", color=INK2, fontsize=9)


def overview(hic, bncap, mat, gissmo) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 7.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    hic_panel(axes[0, 0], hic)
    ncap_panel(axes[0, 1], bncap)
    material_panel(axes[1, 0], mat)
    gissmo_panel(axes[1, 1], gissmo)
    fig.text(0.012, 0.012, "Synthetic data from the crashmetrics examples 01, 22, 27 "
             "and 29.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1), h_pad=2.6, w_pad=2.0)
    fig.savefig(OUT / "overview.png", facecolor=SURFACE)
    plt.close(fig)


def social(gissmo) -> None:
    fig = plt.figure(figsize=(12.8, 6.4), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.05, 0.74, "crashmetrics", fontsize=50, fontweight="bold", color=INK)
    fig.text(0.05, 0.57, "Python for crash CAE engineers", fontsize=22, color=INK)
    fig.text(0.05, 0.36, "Euro NCAP and Bharat NCAP scores\n"
             "Dummy criteria: HIC, Nij, BrIC, VC ...\n"
             "LS-DYNA outputs, *MAT_024 and GISSMO cards",
             fontsize=15.5, color=INK2, linespacing=1.6)
    fig.text(0.05, 0.12, "pip install crashmetrics", fontsize=17, color=BLUE,
             family="monospace", fontweight="bold")
    fig.text(0.05, 0.05, "github.com/vsk1729/crashmetrics  ·  MIT licence",
             fontsize=12, color=MUTED)
    ax = fig.add_axes((0.57, 0.17, 0.39, 0.62))
    gissmo_panel(ax, gissmo, compact=True)
    fig.savefig(OUT / "social-preview.png", facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hic = run_example("01_signals_hic.py")
    bncap = run_example("22_bncap_channels_scorecard.py")
    mat = run_example("27_mat024_card.py")
    gissmo = run_example("29_gissmo_failure.py")
    overview(hic, bncap, mat, gissmo)
    social(gissmo)
    print(f"Wrote {OUT / 'overview.png'} and {OUT / 'social-preview.png'}")


if __name__ == "__main__":
    main()
