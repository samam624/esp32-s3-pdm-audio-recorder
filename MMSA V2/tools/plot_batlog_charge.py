"""Plot one run of the recorder's /BATLOG.CSV as a charge cycle (board on USB, charger filling the cell).

Usage:  python plot_batlog_charge.py BATLOG.CSV --out charge.png [--run N]
Same file, runs and style as plot_batlog.py (default: the last run). Shaded spans are when the charger was on,
found from steps in the 30 s average: a drop of 40 mV or more from above 4.08 V is the charger finishing, and a
jump of 40 mV or more is a top-up starting.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from plot_batlog import AXIS, BAND, GRID, INK, INK2, REC, SURFACE, TRACE, load_runs


def charger_spans(rows: list[dict]) -> list[tuple[float, float, float]]:
    """(start h, end h, voltage at end) for each time the charger was on. The run starts with it on."""
    spans, start = [], rows[0]["t"]
    for a, b in zip(rows, rows[1:]):
        d = b["avg"] - a["avg"]
        if start is not None and d <= -0.040 and a["avg"] > 4.08:
            spans.append((start, a["t"], a["avg"]))
            start = None
        elif start is None and d >= 0.040:
            start = a["t"]
    if start is not None:
        spans.append((start, rows[-1]["t"], rows[-1]["avg"]))
    return spans


def plot(rows: list[dict], spans: list[tuple[float, float, float]], out: Path) -> float:
    t = [r["t"] for r in rows]
    avg = [r["avg"] for r in rows]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for a, b, _ in spans:
        ax.axvspan(a, b, color=REC, lw=0, zorder=0)
    ax.fill_between(t, [r["min"] for r in rows], [r["max"] for r in rows], color=BAND, lw=0, zorder=1)
    ax.plot(t, avg, color=TRACE, lw=2, zorder=3, solid_capstyle="round")

    full_t, full_v = spans[0][1], spans[0][2]
    ax.annotate(f"{avg[0]:.2f} V at plug-in", (t[0], avg[0]), xytext=(8, -4), textcoords="offset points",
                color=INK, fontsize=9, va="top")
    ax.annotate(f"charge done at {full_t:.2f} h ({full_v:.2f} V)", (full_t, full_v), xytext=(-12, 22),
                textcoords="offset points", ha="right", color=INK, fontsize=9,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    for a, b, v in spans[1:]:
        ax.annotate("top-up", ((a + b) / 2, v), xytext=(0, 14), textcoords="offset points", ha="center",
                    color=INK2, fontsize=9)
    tail = [r["avg"] for r in rows if r["t"] > spans[-1][1]] or avg[-1:]
    rest = sum(tail) / len(tail)
    ax.annotate(f"rests at {rest:.2f} V, {t[-1]:.1f} h", (t[-1], avg[-1]), xytext=(0, -40),
                textcoords="offset points", ha="right", color=INK, fontsize=9,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.text((spans[0][0] + spans[0][1]) / 2, 0.97, "charging", transform=ax.get_xaxis_transform(), ha="center",
            va="top", color=INK2, fontsize=9)

    ax.set_xlim(0, t[-1] * 1.01)
    ax.set_ylim(3.4, 4.25)
    ax.set_xlabel("hours since plug-in", color=INK2, fontsize=10)
    ax.set_ylabel("battery voltage (V)", color=INK2, fontsize=10)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    fig.suptitle(f"Charge from {avg[0]:.2f} V: full in {full_t:.1f} h", x=0.07, ha="left", color=INK, fontsize=13,
                 fontweight="bold")
    ax.set_title("Line: 30 s average of the board's readings (ADC reads ~90 mV low). Band: lowest to highest "
                 "reading in each 30 s. Shaded: charger on.", loc="left", color=INK2, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return rest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--run", type=int, default=-1, help="which run: -1 = last (default), 1 = first")
    a = ap.parse_args()
    runs = load_runs(a.csv)
    rows = runs[a.run - 1 if a.run > 0 else a.run]["rows"]
    spans = charger_spans(rows)
    rest = plot(rows, spans, a.out)
    for s, e, v in spans:
        print(f"charger on {s:.2f}-{e:.2f} h, {v:.3f} V at the end")
    print(f"{len(runs)} runs in {a.csv.name}; plotted run {a.run}: {len(rows)} lines, {rows[-1]['t']:.2f} h, "
          f"rests at {rest:.3f} V -> {a.out}")


if __name__ == "__main__":
    main()
