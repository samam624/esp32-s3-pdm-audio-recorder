"""Slide-14 style Lp / f_mu chordwise profiles for several analysis bands.

Reuses the paper_transition_metrics pipeline (2048-pt Hann Welch, 2 s blocks,
median over blocks) and only changes the integration band, so the figures are
directly comparable to 14_paper_metrics_2_7khz.png.

Usage:
    python band_compare_metrics.py SESSION_DIR OUTPUT_DIR
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import paper_transition_metrics as paper

BANDS = {
    "2_7khz": ((2_000.0, 7_000.0), "2-7 kHz"),
    "4_8khz": ((4_000.0, 8_000.0), "4-8 kHz"),
    "broadband": ((20.0, 20_000.0), "broadband 20 Hz-20 kHz"),
}


def plot_clean(metrics, label: str, output: Path) -> None:
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=True)
    for col, condition in enumerate(("30", "60")):
        take = metrics[condition]
        lp = np.median(take.lp_dbfs, axis=0)
        fmu = np.median(take.fmu_hz, axis=0)
        for row, (values, ylabel, title) in enumerate((
            (lp, rf"$L_p$, {label} (dBFS)", r"Band level $L_p$"),
            (fmu / 1000.0, r"$f_\mu$ (kHz)", r"First spectral moment $f_\mu$"),
        )):
            ax = axes[row, col]
            dx, dy = paper.dense_profile(values)
            ax.plot(dx, dy, color=paper.COLORS[condition], lw=2.4, alpha=0.76)
            x, y, order = paper.sorted_profile(values)
            ax.plot(x, y, "o", color=paper.COLORS[condition], ms=8, mec="white", mew=1.3, zorder=3)
            for xx, yy, mic in zip(x, y, order):
                ax.annotate(f"m{mic}", (xx, yy), xytext=(0, 8), textcoords="offset points",
                            ha="center", fontsize=9, color="#333333")
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.2)
            ax.set_title(f"{condition} mph - {title}", loc="left", fontweight="bold")
    for ax in axes[1]:
        ax.set_xlabel("x/c from leading edge (0 = leading, 1 = trailing)")
    fig.suptitle(f"{label} pressure-spectrum metrics on the MMSA wing array",
                 x=0.055, y=0.985, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.055, 0.945,
             "Dots are measured microphone values; curves are shape-preserving interpolation for visualization only.",
             ha="left", color="#333333")
    fig.tight_layout(rect=(0.04, 0.04, 1, 0.925))
    fig.savefig(output, dpi=240, facecolor="white")
    plt.close(fig)


def plot_overlay(results: dict, output: Path) -> None:
    """Lp offset by each band's leading-side median so shapes compare directly."""
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=True)
    colors = {"2_7khz": "#2f6db5", "4_8khz": "#d55e00", "broadband": "#2a9d4b"}
    for col, condition in enumerate(("30", "60")):
        for key, (_, label) in BANDS.items():
            take = results[key][condition]
            lp = np.median(take.lp_dbfs, axis=0)
            fmu = np.median(take.fmu_hz, axis=0) / 1000.0
            for row, values in enumerate((lp - np.median(lp[[3, 4, 5, 6, 7]]), fmu)):
                ax = axes[row, col]
                x, y, _ = paper.sorted_profile(values)
                ax.plot(x, y, "o-", color=colors[key], lw=2, ms=6, mec="white", label=label)
        axes[0, col].set_title(f"{condition} mph - $L_p$ relative to leading-side median (m3-m7)",
                               loc="left", fontweight="bold")
        axes[1, col].set_title(f"{condition} mph - $f_\\mu$", loc="left", fontweight="bold")
        axes[0, col].set_ylabel("dB re leading-side median")
        axes[1, col].set_ylabel(r"$f_\mu$ (kHz)")
        axes[1, col].set_xlabel("x/c from leading edge (0 = leading, 1 = trailing)")
    for ax in axes.flat:
        ax.grid(alpha=0.2)
    axes[0, 0].legend(frameon=False)
    fig.suptitle("Band comparison on the MMSA wing array", x=0.055, y=0.985, ha="left",
                 fontsize=17, fontweight="bold")
    fig.tight_layout(rect=(0.04, 0.03, 1, 0.95))
    fig.savefig(output, dpi=240, facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    results = {}
    for key, (band, label) in BANDS.items():
        paper.BAND = band
        metrics = {c: paper.analyse_take(args.session, c) for c in ("30", "60")}
        results[key] = metrics
        plot_clean(metrics, label, args.output / f"paper_metrics_{key}.png")
        with (args.output / f"paper_metrics_{key}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["condition", "mic", "x_over_c", "lp_dbfs", "fmu_hz", "clipped_percent"])
            for c in ("30", "60"):
                t = metrics[c]
                for m in range(paper.CHANNELS):
                    w.writerow([c, m, f"{paper.MIC_XC[m]:.4f}", f"{np.median(t.lp_dbfs[:, m]):.3f}",
                                f"{np.median(t.fmu_hz[:, m]):.1f}", f"{np.mean(t.clipped_percent[:, m]):.5f}"])
        for c in ("30", "60"):
            p = paper.transition_pick(c, "Lp", np.median(metrics[c].lp_dbfs, axis=0))
            print(f"{label:28s} {c} mph max-slope Lp bracket m{p.leading_mic}-m{p.trailing_mic} "
                  f"x/c {p.x_lo:.3f}-{p.x_hi:.3f}, +{p.delta:.1f} dB")
    plot_overlay(results, args.output / "paper_metrics_band_overlay.png")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
