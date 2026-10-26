"""Plot battery voltage over time for one run of the recorder's /BATLOG.CSV.

Usage:  python plot_batlog.py BATLOG.CSV --out run.png [--run N]
A run is everything after one "# boot" line. The default is the last run; --run 1 is the first, -2 the one before
last. The line is the 30 s average VBAT the firmware logs; the band is the min-max of the readings in each 30 s.
Times the board was recording are shaded. The dashed line is the cutoff from the boot line.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt

INK, INK2, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
TRACE, BAND, REC = "#2a78d6", "#cde2fb", "#f0efec"


def load_runs(path: Path) -> list[dict]:
    runs: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# boot"):
            m = re.search(r"cutoff_mV=(\d+)", line)
            runs.append({"boot": line, "cutoff": int(m.group(1)) if m else None, "rows": [], "low": False})
        elif not runs:
            continue
        elif line.startswith("# LOW BATTERY"):
            runs[-1]["low"] = True
        elif line and line[0].isdigit():
            f = line.split(",")
            runs[-1]["rows"].append({"t": int(f[0]) / 3600, "avg": int(f[1]) / 1000, "min": int(f[2]) / 1000,
                                     "max": int(f[3]) / 1000, "rec": f[4] == "1",
                                     "ble": int(f[5]) if len(f) > 5 else 0})
    return [r for r in runs if r["rows"]]


def rec_spans(rows: list[dict]) -> list[tuple[float, float]]:
    spans, start = [], None
    for r in rows:
        if r["rec"] and start is None:
            start = r["t"]
        elif not r["rec"] and start is not None:
            spans.append((start, r["t"]))
            start = None
    if start is not None:
        spans.append((start, rows[-1]["t"]))
    return spans


def plot(run: dict, out: Path, title: str) -> None:
    rows = run["rows"]
    t = [r["t"] for r in rows]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    spans = rec_spans(rows)
    for a, b in spans:
        ax.axvspan(a, b, color=REC, lw=0, zorder=0)
    ax.fill_between(t, [r["min"] for r in rows], [r["max"] for r in rows], color=BAND, lw=0, zorder=1)
    ax.plot(t, [r["avg"] for r in rows], color=TRACE, lw=2, zorder=3, solid_capstyle="round")

    if run["cutoff"]:
        cut = run["cutoff"] / 1000
        ax.axhline(cut, color=INK2, lw=1, ls=(0, (4, 3)), zorder=2)
        ax.text(0.01, cut, f"cutoff {cut:.2f} V", transform=ax.get_yaxis_transform(), color=INK2, fontsize=9,
                va="bottom", ha="left")

    first, last = rows[0], rows[-1]
    ax.annotate(f"{first['avg']:.2f} V", (first["t"], first["avg"]), xytext=(6, 6), textcoords="offset points",
                color=INK, fontsize=9)
    end = "recording stopped at the cutoff" if run["low"] else "log ends (power lost or reset)"
    ax.annotate(f"{last['avg']:.2f} V at {last['t']:.2f} h\n{end}", (last["t"], last["avg"]), xytext=(-40, 85),
                textcoords="offset points", ha="right", color=INK, fontsize=9,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    for i, (a, b) in enumerate(spans):
        ax.text((a + b) / 2, 0.97, "recording" if i == 0 else "", transform=ax.get_xaxis_transform(), ha="center",
                va="top", color=INK2, fontsize=9)

    ax.set_xlim(0, last["t"] * 1.01)
    ax.set_xlabel("hours since boot", color=INK2, fontsize=10)
    ax.set_ylabel("battery voltage (V)", color=INK2, fontsize=10)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    fig.suptitle(title, x=0.07, ha="left", color=INK, fontsize=13, fontweight="bold")
    ax.set_title("Line: 30 s average of the board's readings (ADC reads ~90 mV low). Band: lowest to highest reading "
                 "in each 30 s. Shaded: recording.", loc="left", color=INK2, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--run", type=int, default=-1, help="which run: -1 = last (default), 1 = first")
    ap.add_argument("--title", default=None)
    a = ap.parse_args()
    runs = load_runs(a.csv)
    run = runs[a.run - 1 if a.run > 0 else a.run]
    rows = run["rows"]
    rec_h = sum(b - x for x, b in rec_spans(rows))
    title = a.title or f"Battery voltage over {rows[-1]['t']:.2f} h"
    plot(run, a.out, title)
    print(f"{len(runs)} runs in {a.csv.name}; plotted run {a.run}: {len(rows)} lines, {rows[-1]['t']:.2f} h, "
          f"{rows[0]['avg']:.3f} -> {rows[-1]['avg']:.3f} V, recording {rec_h:.2f} h, "
          f"{'LOW BATTERY cutoff' if run['low'] else 'no cutoff line'} -> {a.out}")


if __name__ == "__main__":
    main()
