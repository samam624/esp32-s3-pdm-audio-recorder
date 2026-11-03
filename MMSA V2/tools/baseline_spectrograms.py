"""Spectrograms of the tunnel-off reference takes, all eight mics.

Takes: 0001 pre-install check, 0002 in tunnel (off), 0004 floor tunnel-off,
0009 wing tunnel-off. Same STFT and colour scale as wing_ramp_spectrograms.py
so the baselines can be compared directly with the ramps.

Usage:
    python baseline_spectrograms.py SESSION_DIR OUTPUT_DIR
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from wing_ramp_spectrograms import DB_RANGE, load, stft_db

TAKES = {
    "0001 pre-install": "MMSA8_0001_test_record",
    "0002 in tunnel, off": "MMSA8_0002_test_record_in_tunnel",
    "0004 floor, off": "MMSA8_0004_Floor_0",
    "0009 wing, off": "MMSA8_0009_Wing_0",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(8, len(TAKES), figsize=(16, 16), sharey=True)
    for col, (label, folder) in enumerate(TAKES.items()):
        sig = load(args.session, folder, list(range(8)))
        for m in range(8):
            f, t, db = stft_db(sig[m])
            ax = axes[m, col]
            im = ax.pcolormesh(t, f / 1000, db, vmin=DB_RANGE[0], vmax=DB_RANGE[1],
                               cmap="magma", shading="auto", rasterized=True)
            ax.set_ylim(0, 16)
            if col == 0:
                ax.set_ylabel(f"mic{m}  kHz")
            if m == 0:
                ax.set_title(f"{label} ({t[-1]:.0f} s)")
        axes[-1, col].set_xlabel("time (s)")
    fig.colorbar(im, ax=axes, label="dB re FS (PSD)", shrink=0.5)
    fig.suptitle("Tunnel-off reference spectrograms (same scale as the ramp plots)")
    fig.savefig(args.output / "baseline_spectrograms.png", dpi=110, bbox_inches="tight")
    print("wrote", args.output / "baseline_spectrograms.png")


if __name__ == "__main__":
    main()
