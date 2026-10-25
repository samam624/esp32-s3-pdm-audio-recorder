"""Plot the battery shunt logs (Scopy voltmeter CSVs across a 1-ohm resistor in the battery + line).

Usage:  python plot_power.py ../data/power/2026-10-24
Writes power_<folder>.png (and, for a log with marked steps, _stages.png and _vs_baseline.png) into that folder.
Values are the measured voltage across the shunt (Channel_0_DC_RMS), plotted in mV; with a 1-ohm shunt that is
numerically the current in mA. Negative = current into the battery (charging). Segments someone selected in a
CSV's side columns (pairs of timestamp / value columns, e.g. "Baseline + Mics") are shaded and labelled with their
mean.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt

TIME = re.compile(r"^\d{1,2}:\d\d:\d\d$")
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
TRACE, BAND = "#2a78d6", "#cde2fb"
TITLE = "ESP32 PDM MEMS BOARD CURRENT CHARACTERIZATION"
SUBTITLE = "Voltage across 1 Ω series resistor on VBAT+"
YLABEL = "shunt voltage (mV)"
NAMES = {"Charging Battery": "Charging", "Baseline + Mics": "+ mics", "Baseline + Mics + BL": "+ mics + Bluetooth",
         "Baseling + Bl": "Baseline + Bluetooth", "Baseline + Bl": "Baseline + Bluetooth"}
TITLES = {"Preliminary Test": "Preliminary test", "Idle (Nothing Running)": "Idle (nothing running)",
          "Charging (Plugged into USB)": "Charging from USB",
          "Recording Only (No SD or BL)": "Recording only (no SD writes), steps as marked in the CSV"}


def secs(t: str) -> int:
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s


def num(x: str):
    try:
        return float(x)
    except ValueError:
        return None


def spread(stamps):
    """Scopy stamps whole seconds; spread each second's samples evenly across it."""
    out, i = [], 0
    while i < len(stamps):
        j = i
        while j < len(stamps) and stamps[j] == stamps[i]:
            j += 1
        out += [stamps[i] + k / (j - i) for k in range(j - i)]
        i = j
    return out


def read_log(path: Path):
    rows = list(csv.reader(path.open(newline="", encoding="utf-8", errors="replace")))
    main = [(secs(r[0]), num(r[1])) for r in rows if len(r) > 1 and TIME.match(r[0]) and num(r[1]) is not None]
    t0 = main[0][0]
    t = [x - t0 for x in spread([s for s, _ in main])]
    mv = [v * 1000 for _, v in main]  # volts -> mV
    width = max(len(r) for r in rows)
    segments = []
    for c in range(5, width - 1):
        pts = [(secs(r[c]), num(r[c + 1])) for r in rows
               if len(r) > c + 1 and TIME.match(r[c]) and num(r[c + 1]) is not None]
        if len(pts) < 5:
            continue
        first = next(i for i, r in enumerate(rows) if len(r) > c + 1 and TIME.match(r[c]))
        label = next((rows[i][c].strip() for i in range(first - 1, -1, -1)
                      if len(rows[i]) > c and rows[i][c].strip() and not TIME.match(rows[i][c].strip())
                      and rows[i][c].strip() not in ("Timestamp", "Average Voltage")), "Selected")
        if label.startswith("Portion of Dataset"):
            label = "Selected"
        mean = sum(v for _, v in pts) / len(pts) * 1000
        segments.append({"name": NAMES.get(label, label), "t0": pts[0][0] - t0, "t1": pts[-1][0] - t0 + 1,
                         "mean": mean, "n": len(pts)})
    return t, mv, segments, rows[1][0].replace(";Started on ", "") if len(rows) > 1 else ""


def style(ax, zero_line=True):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    if zero_line:
        ax.axhline(0, color=AXIS, linewidth=0.8)


def panel(ax, path, t, mv, segments, started, label_all):
    style(ax)
    key = path.stem.replace("Power Measurements - ", "")
    clock = started.split()[3][:5] if len(started.split()) > 3 else ""
    ax.set_title(f"{TITLES.get(key, key)}  ·  {clock}", loc="left", fontsize=9.5, color=INK)
    tiled = len(segments) > 1  # back-to-back steps: shade every other one so the boundaries show
    for k, s in enumerate(segments):
        if not tiled or k % 2 == 0:
            ax.axvspan(s["t0"], s["t1"], color=BAND, alpha=0.6, linewidth=0)
        ax.hlines(s["mean"], s["t0"], s["t1"], color=INK, linewidth=1.2)
    ax.plot(t, mv, color=TRACE, linewidth=0.8)
    if not segments:  # nothing selected in the CSV: label how the reading moved over the log
        n = max(1, sum(1 for x in t if x <= 30))
        a, b = sum(mv[:n]) / n, sum(mv[-n:]) / n
        ax.text(0.5, 0.97 if a < 0 else 0.05, f"first 30 s {a:.0f} mV  →  last 30 s {b:.0f} mV",
                transform=ax.transAxes, ha="center", va="top" if a < 0 else "bottom", fontsize=7.5, color=INK2)
    if not label_all:  # one selected window: its mean just above the line
        for s in segments:
            ax.text((s["t0"] + s["t1"]) / 2, s["mean"] + 10, f"mean {s['mean']:.1f} mV", ha="center",
                    va="bottom", fontsize=7.5, color=INK2,
                    bbox=dict(boxstyle="round,pad=0.15", facecolor=SURFACE, edgecolor="none", alpha=0.85))
    ax.set_xlim(0, max(t))
    ax.set_xlabel("time (s)", fontsize=8, color=MUTED)


def step_labels(ax, segments):
    """Label back-to-back steps without touching the trace or each other: each label (name over value) sits in the
    empty space on the far side of zero from its step, joined to it by a dotted leader. A label that would overlap
    one already placed drops to the next row."""
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    lo, hi = ax.get_ylim()
    x_lo, x_hi = ax.get_xlim()
    px_per_s = ax.get_window_extent(renderer).width / (x_hi - x_lo)
    rows_below = [-0.06 * (hi - lo), -0.20 * (hi - lo)]  # for steps above zero: rows below the zero line
    # The trace fills a below-zero step's whole span, including the jump at its end: labels keep clear of it.
    keep_out = [ax.transData.transform((s["t1"] + 1, 0))[0] for s in segments if s["mean"] < 0]
    placed = []
    for s in sorted(segments, key=lambda s: s["t0"]):
        x = (s["t0"] + s["t1"]) / 2
        text = f"{s['name']}\n{s['mean']:.1f} mV"
        if s["mean"] < 0:  # below zero (charging): straight under its own line, where nothing else is
            ax.text(x, s["mean"] - 0.04 * (hi - lo), text, ha="center", va="top", fontsize=7.5, color=INK2,
                    linespacing=1.25)
            continue
        for k, y in enumerate(rows_below):
            label = ax.text(x, y, text, ha="center", va="top", fontsize=7.5, color=INK2, linespacing=1.25)
            box = label.get_window_extent(renderer)
            for edge in keep_out:  # nudge right, clear of a below-zero step's trace
                if box.x0 < edge + 4 < box.x1 + 4:
                    x += (edge + 4 - box.x0) / px_per_s
                    label.set_x(x)
                    box = label.get_window_extent(renderer)
            box = box.expanded(1.08, 1.1)
            if k == len(rows_below) - 1 or not any(box.overlaps(b) for b in placed):
                placed.append(box)
                break
            label.remove()
            x = (s["t0"] + s["t1"]) / 2
        lead = min(max(x, s["t0"] + 1), s["t1"] - 1)  # the leader stays inside its own step
        ax.plot([x, lead], [y + 0.01 * (hi - lo), s["mean"] - 0.015 * (hi - lo)], color=AXIS, linewidth=0.8,
                linestyle=(0, (1, 2)))


BAR_NAMES = {"+ mics": "Baseline + mics", "+ mics + Bluetooth": "Baseline + mics + Bluetooth",
             "Charging": "Charging (into the battery)"}
BAR_ORDER = ["Baseline", "Baseline + Bluetooth", "Baseline + mics", "Baseline + mics + Bluetooth",
             "Charging (into the battery)"]


def stages(segments):
    """Mean per step, pooling steps with the same name (e.g. two baseline readings) over all their samples."""
    pooled = {}
    for s in segments:
        name = BAR_NAMES.get(s["name"], s["name"])
        tot, n, parts = pooled.get(name, (0.0, 0, []))
        pooled[name] = (tot + s["mean"] * s["n"], n + s["n"], parts + [s["mean"]])
    out = [(name, tot / n, parts) for name, (tot, n, parts) in pooled.items()]
    rank = {name: i for i, name in enumerate(BAR_ORDER)}
    return sorted(out, key=lambda x: rank.get(x[0], len(rank)))


def bar_chart(names, values, labels, title, subtitle, xlabel, out):
    fig, ax = plt.subplots(figsize=(8.5, 0.62 * len(names) + 1.6), dpi=150, facecolor=SURFACE)
    style(ax, zero_line=False)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.axvline(0, color=AXIS, linewidth=0.8)
    y = list(range(len(names)))[::-1]  # first name at the top
    ax.barh(y, values, height=0.55, color=TRACE)
    span = max(values) - min(0, min(values))
    for yi, v, lab in zip(y, values, labels):
        ax.text(v + (0.012 * span if v >= 0 else -0.012 * span), yi, lab, va="center",
                ha="left" if v >= 0 else "right", fontsize=8.5, color=INK2)
    ax.set_yticks(y, names, fontsize=9, color=INK)
    ax.tick_params(axis="y", length=0)
    lo, hi = min(0, min(values)), max(0, max(values))
    ax.set_xlim(lo - (0.28 * span if lo < 0 else 0), hi + 0.28 * span)
    ax.set_xlabel(xlabel, fontsize=8.5, color=INK2)
    ax.spines["left"].set_visible(False)
    # Subtitle just above the plot, title above that: offsets in points, so they never overlap.
    ax.annotate(subtitle, xy=(0, 1), xycoords="axes fraction", xytext=(0, 8), textcoords="offset points",
                ha="left", va="bottom", fontsize=8.5, color=INK2)
    ax.annotate(title, xy=(0, 1), xycoords="axes fraction", xytext=(0, 24), textcoords="offset points",
                ha="left", va="bottom", fontsize=11, color=INK)
    fig.savefig(out, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(out)


def stage_charts(folder, path, segments, started):
    st = stages(segments)
    base = next(m for name, m, _ in st if name == "Baseline")
    bar_chart([n for n, _, _ in st], [m for _, m, _ in st],
              [f"{m:.1f} mV" + (f"  ({' / '.join(f'{p:.1f}' for p in parts)})" if len(parts) > 1 else "")
               for _, m, parts in st],
              TITLE, SUBTITLE, YLABEL, folder / f"power_{folder.name}_stages.png")
    rel = [(n, m) for n, m, _ in st if n not in ("Baseline",) and not n.startswith("Charging")]
    bar_chart([n for n, _ in rel], [(m - base) / base * 100 for _, m in rel],
              [f"+{(m - base) / base * 100:.0f}%  (+{m - base:.1f} mV)" if m >= base else
               f"{(m - base) / base * 100:.0f}%  ({m - base:.1f} mV)" for _, m in rel],
              TITLE, f"{SUBTITLE}; baseline {base:.1f} mV", "change from baseline (%)",
              folder / f"power_{folder.name}_vs_baseline.png")


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    logs = sorted(folder.glob("*.csv"), key=lambda p: read_log(p)[3])  # in the order they were logged
    data = {p: read_log(p) for p in logs}
    big = max(logs, key=lambda p: len(data[p][2]))  # the log with the most selected segments
    small = [p for p in logs if p != big]
    fig = plt.figure(figsize=(12, 7.2), dpi=150, facecolor=SURFACE)
    gs = fig.add_gridspec(2, max(len(small), 1), height_ratios=[1, 1.35], hspace=0.42, wspace=0.12)
    axes = [fig.add_subplot(gs[0, i]) for i in range(len(small))]
    bottom = fig.add_subplot(gs[1, :], sharey=axes[0] if axes else None)
    for ax in axes[1:]:
        ax.sharey(axes[0])
    for ax, p in zip(axes, small):
        panel(ax, p, *data[p][:2], data[p][2], data[p][3], label_all=False)
    panel(bottom, big, *data[big][:2], data[big][2], data[big][3], label_all=True)
    lo = min(min(d[1]) for d in data.values())
    hi = max(max(d[1]) for d in data.values())
    bottom.set_ylim(lo - 25, hi + 25)
    step_labels(bottom, data[big][2])
    for ax in axes[1:]:
        ax.tick_params(labelleft=False)
    for ax in (axes[0], bottom) if axes else (bottom,):
        ax.set_ylabel(YLABEL, fontsize=8.5, color=INK2)
    fig.suptitle(TITLE, x=0.06, y=0.985, ha="left", fontsize=11, color=INK)
    fig.text(0.06, 0.948, SUBTITLE, ha="left", fontsize=8.5, color=INK2)
    out = folder / f"power_{folder.name}.png"
    fig.savefig(out, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(out)
    if any(s["name"] == "Baseline" for s in data[big][2]):
        stage_charts(folder, big, data[big][2], data[big][3])
    for p in logs:
        for s in data[p][2]:
            print(f"  {p.stem.replace('Power Measurements - ', ''):30s} {s['name']:22s} {s['mean']:7.1f} mV  "
                  f"({s['t0']:.0f}-{s['t1']:.0f} s)")


if __name__ == "__main__":
    main()
