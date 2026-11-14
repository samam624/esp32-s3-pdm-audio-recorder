"""Plot a whole /BATLOG.CSV that includes deep sleeps, to read the sleep drain.

Usage:  python plot_batlog_sleep.py BATLOG.CSV --out sleep.png
The board has no clock, so the log can't say how long a sleep lasted. The x axis is the awake time in log order,
with each sleep drawn as a fixed-width break labelled with the voltage change across it (wake reading minus the
reading just before sleep) and that change in mAh, using the slope of the 2026-10-25 run-down of the 1200 mAh cell
(MV_PER_MAH: ~0.74 mV/mAh near 3.9 V, ~1 mV/mAh at 4.0 V and above; no run-down data above 4.02 V). Power-on resets are thin breaks. The readings are taken with the
board awake and scatter by roughly +/-10 mV, so only drops well past that mean anything.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt

INK, INK2, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
TRACE, BAND, REC, SLEEP, DROP = "#2a78d6", "#cde2fb", "#f0efec", "#e8e4f3", "#6b4fbb"
SLEEP_W, CYCLE_W = 11.0, 1.0  # break widths in awake-minute units (not to scale)
# (board mV, mV per mAh) for the 1200 mAh cell, from the 2026-10-25 run-down at ~150 mA
MV_PER_MAH = [(3870, 0.74), (3910, 0.74), (3950, 0.81), (4000, 1.0), (4200, 1.0)]


def mv_per_mah(mv: float) -> float:
    pts = MV_PER_MAH
    if mv <= pts[0][0]:
        return pts[0][1]
    for (v1, k1), (v2, k2) in zip(pts, pts[1:]):
        if mv <= v2:
            return k1 + (k2 - k1) * (mv - v1) / (v2 - v1)
    return pts[-1][1]


def mah(before: int, after: int) -> float:
    return abs(after - before) / mv_per_mah((before + after) / 2)


def load(path: Path) -> list[dict]:
    """Return the log as a list of events: boot, row, sleep (rows before the first boot are skipped)."""
    ev: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# boot"):
            reset = re.search(r"reset=([^,(]+)", line).group(1).strip()
            ev.append({"k": "boot", "reset": reset, "mv": int(re.search(r"vbat_mV=(\d+)", line).group(1))})
        elif not ev:
            continue
        elif line.startswith("# sleep"):
            ev.append({"k": "sleep", "mv": int(re.search(r"vbat_mV=(\d+)", line).group(1))})
        elif line and line[0].isdigit():
            f = line.split(",")
            ev.append({"k": "row", "s": int(f[0]), "avg": int(f[1]), "min": int(f[2]), "max": int(f[3]),
                       "rec": f[4] == "1"})
    return ev


def layout(ev: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into awake sessions and the breaks between them, with x positions in minutes."""
    sessions, breaks, x, cur = [], [], 0.0, None
    for e in ev:
        if e["k"] == "boot":
            if cur is not None:
                end = cur["x0"] + cur["len"]
                kind = "sleep" if e["reset"] == "deep-sleep" and cur["slept"] else "cycle"
                w = SLEEP_W if kind == "sleep" else CYCLE_W
                breaks.append({"kind": kind, "x0": end, "x1": end + w, "before": cur["sleep_mv"] or cur["last"],
                               "after": e["mv"]})
                x = end + w
            cur = {"x0": x, "boot_mv": e["mv"], "rows": [], "len": 0.25, "slept": False, "sleep_mv": None,
                   "last": e["mv"]}
            sessions.append(cur)
        elif e["k"] == "row":
            cur["rows"].append(e)
            cur["len"] = max(cur["len"], e["s"] / 60 + 0.25)
            cur["last"] = e["avg"]
        elif e["k"] == "sleep":
            cur["slept"], cur["sleep_mv"] = True, e["mv"]
    if cur is not None and cur["slept"]:  # still asleep when the card was read
        end = cur["x0"] + cur["len"]
        breaks.append({"kind": "open", "x0": end, "x1": end + SLEEP_W, "before": cur["sleep_mv"], "after": None})
    return sessions, breaks


def plot(ev: list[dict], out: Path, title: str) -> list[dict]:
    sessions, breaks = layout(ev)
    fig, ax = plt.subplots(figsize=(13.5, 5.8), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    for s in sessions:
        rows, x0 = s["rows"], s["x0"]
        xs = [x0 + r["s"] / 60 for r in rows]
        for r, xa in zip(rows, xs):
            if r["rec"]:
                ax.axvspan(xa - 0.5, xa, color=REC, lw=0, zorder=0)
        if rows:
            ax.fill_between(xs, [r["min"] / 1000 for r in rows], [r["max"] / 1000 for r in rows], color=BAND,
                            lw=0, zorder=1)
            ax.plot(xs, [r["avg"] / 1000 for r in rows], color=TRACE, lw=1.8, zorder=3)
        ax.plot([x0], [s["boot_mv"] / 1000], "o", color=TRACE, ms=4, zorder=4)
        if s["slept"]:
            ax.plot([x0 + s["len"]], [s["sleep_mv"] / 1000], "o", color=DROP, ms=4, zorder=4)

    ymin, ymax = 3.84, 4.24
    n = 0
    for b in breaks:
        if b["kind"] == "cycle":
            ax.axvline((b["x0"] + b["x1"]) / 2, color=AXIS, lw=0.8, ls=(0, (2, 2)), zorder=0)
            continue
        n += 1
        ax.axvspan(b["x0"], b["x1"], color=SLEEP, lw=0, zorder=0)
        mid = (b["x0"] + b["x1"]) / 2
        if b["kind"] == "open":
            label = f"sleep {n}\nno wake\nlogged"
            ax.text(mid, ymax - 0.005, label, ha="center", va="top", fontsize=8, color=INK2)
            continue
        d = b["after"] - b["before"]
        ax.plot([b["x0"], b["x1"]], [b["before"] / 1000, b["after"] / 1000], color=DROP, lw=1, ls=(0, (3, 2)),
                zorder=2)
        sig = abs(d) >= 15
        label = f"sleep {n}\n{d:+d} mV" + (f"\n≈{mah(b['before'], b['after']):.0f} mAh" if sig else "\n(noise)")
        ax.text(mid, ymax - 0.005, label, ha="center", va="top", fontsize=8,
                color=DROP if sig else INK2, fontweight="bold" if sig else "normal")
        b["n"], b["delta"] = n, d

    end = max(b["x1"] for b in breaks) if breaks else sessions[-1]["x0"] + sessions[-1]["len"]
    ax.set_xlim(-1, end + 1)
    ax.set_ylim(ymin, ymax)
    # 10-minute scale bar in place of x ticks (the breaks aren't to scale)
    ax.plot([1, 11], [ymin + 0.012] * 2, color=INK, lw=2, solid_capstyle="butt")
    ax.text(6, ymin + 0.016, "10 min awake", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks([])
    ax.set_xlabel("log order: awake periods to scale; sleeps (purple) are breaks, not to scale; dotted lines: power cycled",
                  color=INK2, fontsize=9)
    ax.set_ylabel("battery voltage, board reading (V)", color=INK2, fontsize=10)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    fig.suptitle(title, x=0.06, ha="left", color=INK, fontsize=13, fontweight="bold")
    ax.set_title("Line: 30 s average while awake (band: min–max; light shading: recording). Dots: reading at boot "
                 "(blue) and just before sleep (purple). Dashed: change across each sleep.", loc="left",
                 color=INK2, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return breaks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default="Battery voltage across deep sleeps (board 2, 1200 mAh cell)")
    a = ap.parse_args()
    breaks = plot(load(a.csv), a.out, a.title)
    for b in breaks:
        if b["kind"] == "sleep":
            print(f"sleep {b['n']}: {b['before']} -> {b['after']} mV ({b['delta']:+d} mV, "
                  f"~{mah(b['before'], b['after']):.0f} mAh if real)")
        elif b["kind"] == "open":
            print(f"last sleep: entered at {b['before']} mV, no wake logged")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
