"""Per-band level-vs-chord plots for the wing takes (multiplot version of the overlay charts).

Wide bands cover the low-interest range; narrower bands cover 2-16 kHz where the
high-level boundary is clearest. Mic x/c comes from the mic ports in the array
photo; the green band is the fluorescent line measured from the flow photo.

Usage:
    python band_profiles_xc.py FLOW.jpg ARRAY.heic SESSION_DIR OUTPUT.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageOps

import overlay_flow_photos as ov

BANDS = [("20-125 Hz", (20, 125)), ("125-500 Hz", (125, 500)), ("500 Hz-2 kHz", (500, 2000)),
         ("2-4 kHz", (2000, 4000)), ("4-8 kHz", (4000, 8000)), ("8-16 kHz", (8000, 16000))]
OFF = "MMSA8_0009_Wing_0"
C30, C60, COFF = "#2f6db5", "#d55e00", "#999999"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("flow_photo", "array_photo", "session", "output"):
        ap.add_argument(name, type=Path)
    args = ap.parse_args()

    flow = np.asarray(ImageOps.exif_transpose(Image.open(args.flow_photo)).convert("RGB"))
    peak, lo, hi, _ = ov.ridge_position(ov.crop_flow(flow))
    xc = [ov.mic_xc(i) for i in range(8)]

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5), sharex=True)
    for ax, (name, band) in zip(axes.flat, BANDS):
        lv = {k: ov.band_level(args.session, t, band) for k, t in
              (("off", OFF), ("30", ov.WING_30), ("60", ov.WING_60))}
        ax.axvspan(lo, hi, color="#2e9e3e", alpha=0.18, lw=0)
        ax.axvspan(xc[2], xc[3], color="#f28e2b", alpha=0.18, lw=0)
        ax.plot(xc, lv["off"], "o:", color=COFF, lw=1.5, ms=5, label="tunnel off")
        ax.plot(xc, lv["30"], "o-", color=C30, lw=2.2, ms=7, mec="white", label="30 mph")
        ax.plot(xc, lv["60"], "s-", color=C60, lw=2.2, ms=7, mec="white", label="60 mph")
        s30, s60 = lv["30"][1] - lv["30"][2], lv["60"][2] - lv["60"][3]
        ax.set_title(name, loc="left", fontweight="bold")
        ax.text(0.98, 0.96, f"step 30 mph (mic1|2): {s30:.0f} dB\nstep 60 mph (mic2|3): {s60:.0f} dB",
                transform=ax.transAxes, ha="right", va="top", fontsize=9.5, color="#333")
        for i in range(8):
            ax.annotate(str(i), (xc[i], 0), xycoords=("data", "axes fraction"), xytext=(0, -14),
                        textcoords="offset points", ha="center", fontsize=8.5, color="#666")
        ax.set_xlim(0, 1)
        ax.set_ylabel("Level (dBFS)")
        print(f"{name}: step30 {s30:.1f}  step60 {s60:.1f}")
    for ax in axes[1]:
        ax.set_xlabel("x/c (0 = aft edge, 1 = forward edge)", labelpad=14)
    axes[0, 0].legend(frameon=False, loc="lower left", fontsize=9)
    fig.suptitle("Wing level vs chord position, by frequency band", x=0.01, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.01, 0.925, "Numbers under the axis are mic numbers. Green: fluorescent line (60 mph flow photo). "
             "Orange: mic2-mic3 gap.", fontsize=10.5, color="#333")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=140)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
