"""Build a presentation-ready broadband PSD comparison for steady wing runs.

The figure shows all eight microphone channels for the steady 30 and 60 mph
recordings on matched axes. Spectra use the same blockwise Welch estimator as
the paper-style transition analysis: 2 s blocks, 2048-sample Hann segments,
50 percent overlap, and a median across complete blocks.

Usage:
    python wing_broadband_psd.py SESSION OUTPUT_PNG [--csv OUTPUT_CSV]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter
import numpy as np

import paper_transition_metrics as paper


FREQUENCY_LIMITS = (20.0, 20_000.0)
PSD_LIMITS = (-125.0, -30.0)
TICKS_HZ = (20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000)


def psd_db(psd: np.ndarray) -> np.ndarray:
    """Convert full-scale-normalized PSD to dBFS squared per hertz."""
    return 10.0 * np.log10(np.maximum(psd, 1e-30))


def format_hz(value: float, _position: int) -> str:
    if value >= 1_000:
        return f"{value / 1_000:g}k"
    return f"{value:g}"


def style_axis(ax: plt.Axes, condition: str) -> None:
    ax.set_xscale("log")
    ax.set_xlim(*FREQUENCY_LIMITS)
    ax.set_ylim(*PSD_LIMITS)
    ax.xaxis.set_major_locator(FixedLocator(TICKS_HZ))
    ax.xaxis.set_major_formatter(FuncFormatter(format_hz))
    ax.grid(alpha=0.2, which="both")
    ax.set_title(f"Steady {condition} mph", loc="left", fontweight="bold")
    ax.set_xlabel("Frequency (Hz)")


def plot_broadband_psd(metrics: dict[str, paper.TakeMetrics], output_png: Path) -> list[Path]:
    """Render the matched 30/60 mph PSD panels as PNG and SVG."""
    plt.rcParams.update({"font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 6.2), sharex=True, sharey=True)
    cmap = plt.get_cmap("plasma")
    fig.subplots_adjust(left=0.065, right=0.985, top=0.84, bottom=0.20, wspace=0.10)

    for ax, condition in zip(axes, ("30", "60")):
        take = metrics[condition]
        frequency = take.frequency_hz
        keep = (frequency >= FREQUENCY_LIMITS[0]) & (frequency <= FREQUENCY_LIMITS[1])
        for mic in range(paper.CHANNELS):
            ax.plot(
                frequency[keep],
                psd_db(take.median_psd[keep, mic]),
                color=cmap(mic / 7.5),
                lw=1.1,
                label=f"mic{mic}",
            )
        style_axis(ax, condition)

    axes[0].set_ylabel(r"Median PSD (dBFS$^2$/Hz)")

    fig.suptitle(
        "Steady wing broadband power spectral density",
        x=0.055,
        y=0.955,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.055),
        ncol=8,
        frameon=False,
        fontsize=9,
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_svg = output_png.with_suffix(".svg")
    fig.savefig(output_png, dpi=160, facecolor="white")
    fig.savefig(output_svg, facecolor="white")
    plt.close(fig)
    return [output_png, output_svg]


def write_csv(metrics: dict[str, paper.TakeMetrics], output_csv: Path) -> Path:
    """Write the plotted median spectra for traceability and reuse."""
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    frequency = metrics["30"].frequency_hz
    if not np.array_equal(frequency, metrics["60"].frequency_hz):
        raise ValueError("30 and 60 mph PSD frequency grids do not match")
    columns = ["frequency_hz"]
    for condition in ("30", "60"):
        columns.extend(f"wing_{condition}_mic{mic}_dbfs2_per_hz" for mic in range(paper.CHANNELS))
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for index, hz in enumerate(frequency):
            row: list[float] = [float(hz)]
            for condition in ("30", "60"):
                row.extend(float(value) for value in psd_db(metrics[condition].median_psd[index]))
            writer.writerow(row)
    return output_csv


def export(session: Path, output_png: Path, output_csv: Path | None = None) -> list[Path]:
    metrics = {condition: paper.analyse_take(session, condition) for condition in ("30", "60")}
    outputs = plot_broadband_psd(metrics, output_png)
    if output_csv is not None:
        outputs.append(write_csv(metrics, output_csv))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="session directory containing the steady wing WAV folders")
    parser.add_argument("output_png", type=Path, help="presentation-ready PNG output")
    parser.add_argument("--csv", type=Path, help="optional CSV containing every plotted PSD trace")
    args = parser.parse_args()
    if not args.session.is_dir():
        parser.error(f"session directory not found: {args.session}")
    for path in export(args.session, args.output_png, args.csv):
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
