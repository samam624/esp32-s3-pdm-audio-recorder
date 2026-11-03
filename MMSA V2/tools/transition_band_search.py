"""Find the frequency band that shows the wing high-level/low-level boundary best.

For each 1/3-octave band the tool measures, on the steady-30 and steady-60 wing
takes, the level step across the boundary (mic1|mic2 at 30 mph, mic2|mic3 at
60 mph), how flat the quiet-side plateau (mic3-mic7) is, and how far the quiet
side sits above the tunnel-off floor. It also tracks the 30-60 ramp in a few
wide bands to show when each microphone switches into the high-level region.

Clipping caveat: at 60 mph mic0-mic2 clip, which adds broadband distortion at
high frequency, so the 30 mph step (almost no clipping) is the cleaner check.

Usage:
    python transition_band_search.py SESSION_DIR OUTPUT_DIR
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, sosfilt, welch

FS = 48000
TAKES = {
    "off": "MMSA8_0009_Wing_0",
    "30": "MMSA8_0011_Wing_30",
    "ramp": "MMSA8_0012_Wing_30_60",
    "60": "MMSA8_0013_Wing_60",
}
CENTERS = [31.5 * 2 ** (k / 3) for k in range(30)]
CENTERS = [c for c in CENTERS if c < 19000]
TICKS = [int(np.argmin([abs(c - f) for c in CENTERS])) for f in (63, 250, 1000, 4000, 16000)]
TICK_LABELS = ["63", "250", "1k", "4k", "16k"]
RAMP_BANDS = {"125-500 Hz": (125, 500), "500-2k Hz": (500, 2000),
              "2-4 kHz": (2000, 4000), "4-8 kHz": (4000, 8000), "8-16 kHz": (8000, 16000)}


def load(session: Path, key: str) -> np.ndarray:
    folder = session / TAKES[key]
    with wave.open(str(next(folder.glob("*.wav")))) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 8) / 32768.0
    return x[int(0.3 * FS):] - x[int(0.3 * FS):].mean(0)


def third_octave_db(x: np.ndarray) -> np.ndarray:
    f, p = welch(x, fs=FS, nperseg=16384, axis=0)
    out = np.empty((len(CENTERS), 8))
    for i, c in enumerate(CENTERS):
        m = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
        out[i] = 10 * np.log10(p[m].sum(0) + 1e-20)
    return out


def ramp_levels(x: np.ndarray, lo: float, hi: float, win: int = 4, hop: int = 4):
    sos = butter(4, [lo, hi], btype="band", fs=FS, output="sos")
    y = sosfilt(sos, x, axis=0)
    starts = range(0, int(len(y) / FS) - win, hop)
    t = np.array([s + win / 2 for s in starts])
    lv = np.array([10 * np.log10((y[s * FS:(s + win) * FS] ** 2).mean(0) + 1e-20) for s in starts])
    return t, lv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    lv = {k: third_octave_db(load(args.session, k)) for k in ("off", "30", "60")}
    step30 = lv["30"][:, 1] - lv["30"][:, 2]
    step60 = lv["60"][:, 2] - lv["60"][:, 3]
    spread60 = lv["60"][:, 3:].std(1)
    spread30 = lv["30"][:, 2:].std(1)
    margin30 = (lv["30"][:, 2:] - lv["off"][:, 2:]).mean(1)
    margin60 = (lv["60"][:, 3:] - lv["off"][:, 3:]).mean(1)
    robust = np.minimum(step30, step60)

    with open(args.output / "transition_band_search.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["center_hz", "step_30mph_mic1_to_2_db", "step_60mph_mic2_to_3_db",
                    "min_step_db", "quiet_plateau_spread_30_db", "quiet_plateau_spread_60_db",
                    "quiet_above_tunnel_off_30_db", "quiet_above_tunnel_off_60_db"])
        for i, c in enumerate(CENTERS):
            w.writerow([f"{c:.0f}", *(f"{v:.1f}" for v in (step30[i], step60[i], robust[i], spread30[i],
                                                           spread60[i], margin30[i], margin60[i]))])

    best = int(np.argmax(np.where((margin30 > 10) & (margin60 > 10), robust, -99)))
    print(f"best 1/3-octave band by min(step30, step60): {CENTERS[best]:.0f} Hz "
          f"(30 mph {step30[best]:.1f} dB, 60 mph {step60[best]:.1f} dB)")
    for lo, hi in ((500, 2000), (2000, 8000), (4000, 8000), (4000, 16000), (8000, 16000)):
        idx = [i for i, c in enumerate(CENTERS) if lo <= c < hi]
        print(f"  {lo}-{hi} Hz: mean step 30 mph {step30[idx].mean():.1f} dB, 60 mph {step60[idx].mean():.1f} dB, "
              f"min {robust[idx].min():.1f} dB")

    ramp = load(args.session, "ramp")
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig = plt.figure(figsize=(14, 9.2), constrained_layout=True)
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1])

    vmin, vmax = -70, -10
    for col, (key, title) in enumerate((("30", "Steady 30 mph"), ("60", "Steady 60 mph"))):
        ax = fig.add_subplot(gs[0, col])
        im = ax.imshow(lv[key].T, aspect="auto", origin="lower", cmap="viridis", vmin=vmin, vmax=vmax,
                       extent=(-0.5, len(CENTERS) - 0.5, -0.5, 7.5))
        ax.set_xticks(TICKS, TICK_LABELS)
        ax.set_yticks(range(8), [f"mic{m}" for m in range(8)])
        ax.set_title(f"{title}: 1/3-octave level (dBFS)", loc="left", fontweight="bold")
        ax.set_xlabel("Frequency (Hz)")
        for s in ax.spines.values():
            s.set_visible(False)
    fig.colorbar(im, ax=fig.axes[:2], shrink=0.85, label="dBFS")

    ax = fig.add_subplot(gs[0, 2])
    xs = np.arange(len(CENTERS))
    ax.axvspan(*(np.searchsorted(CENTERS, [3900, 8100]) - 0.5), color="#f7c59f", alpha=0.45, lw=0)
    ax.plot(xs, step30, "o-", color="#1f77b4", label="30 mph, mic1|mic2", ms=4)
    ax.plot(xs, step60, "s-", color="#d55e00", label="60 mph, mic2|mic3", ms=4)
    ax.set_xticks(TICKS, TICK_LABELS)
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_ylabel("Level step across boundary (dB)")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_title("Boundary contrast vs frequency", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="upper left")
    ax.text(np.searchsorted(CENTERS, 4000), ax.get_ylim()[0] + 1, "4-8 kHz", color="#a04000", fontsize=9)

    for col, name in enumerate(("2-4 kHz", "4-8 kHz", "125-500 Hz")):
        ax = fig.add_subplot(gs[1, col])
        t, lvl = ramp_levels(ramp, *RAMP_BANDS[name])
        cmap = plt.get_cmap("plasma")
        for m in range(8):
            ax.plot(t, lvl[:, m], color=cmap(m / 7.5), lw=1.8, label=f"mic{m}")
        ax.set_title(f"30-60 mph ramp, {name} band", loc="left", fontweight="bold")
        ax.set_xlabel("Time in take 0012 (s)")
        ax.set_ylabel("dBFS")
        if col == 0:
            ax.legend(frameon=False, ncol=4, fontsize=8, loc="lower right")
    fig.suptitle("Which band shows the wing high-level boundary?", x=0.01, ha="left", fontsize=14, fontweight="bold")
    out = args.output / "transition_band_search.png"
    fig.savefig(out, dpi=130)
    print(out)

    # One ramp plot per band; wide bands where the boundary is not of interest.
    bands = [("20-125 Hz", (20, 125)), ("125-500 Hz", (125, 500)), ("500 Hz-2 kHz", (500, 2000)),
             ("2-4 kHz", (2000, 4000)), ("4-8 kHz", (4000, 8000)), ("8-16 kHz", (8000, 16000))]
    fig, axes = plt.subplots(2, 3, figsize=(16, 9), constrained_layout=True)
    cmap = plt.get_cmap("plasma")
    for ax, (name, band) in zip(axes.flat, bands):
        t, lvl = ramp_levels(ramp, *band)
        for m in range(8):
            ax.plot(t, lvl[:, m], color=cmap(m / 7.5), lw=1.8, label=f"mic{m}")
        ax.set_title(f"30-60 mph ramp, {name}", loc="left", fontweight="bold")
        ax.set_xlabel("Time in take 0012 (s)")
        ax.set_ylabel("dBFS")
    axes[0, 0].legend(frameon=False, ncol=4, fontsize=8, loc="lower right")
    fig.suptitle("Ramp level per microphone, by frequency band", x=0.01, ha="left", fontsize=14, fontweight="bold")
    out2 = args.output / "ramp_band_multiplot.png"
    fig.savefig(out2, dpi=130)
    print(out2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
