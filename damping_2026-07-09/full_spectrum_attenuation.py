"""Full-spectrum (20 Hz-20 kHz) wind-noise attenuation for the 070926 damping test.

Each configuration's hairdryer-high take is mixed to mono, its Welch PSD
(Hann, 4096 points, 50% overlap) is integrated over 20 Hz-20 kHz, and the
result is compared with the lid-off hairdryer-high take. Positive values mean
the configuration recorded a lower level than the bare microphone.

The file mapping uses the content-verified labels from mic_damping_report.html,
not the spreadsheet's literal row order.

Usage: python full_spectrum_attenuation.py
Writes full_spectrum_attenuation.csv and
mic_damping_figures/08_full_spectrum_attenuation.png next to this script.
"""

import csv
import wave
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch


DATA_DIR = Path(__file__).resolve().parent
CSV_PATH = DATA_DIR / "full_spectrum_attenuation.csv"
FIGURE_PATH = DATA_DIR / "mic_damping_figures" / "08_full_spectrum_attenuation.png"

BAND_HZ = (20.0, 20000.0)
NPERSEG = 4096
REFERENCE = "Lid off"
# The other lid-off fan take. The spreadsheet logged it as hairdryer-high, but
# it is 1 dB quieter than REC_00031, so it is reported as a sensitivity check.
ALT_REFERENCE_FILE = "REC_00033.WAV"

# Hairdryer-high take for each configuration (content-verified labels).
HIGH_FAN_FILES = {
    "Lid on": "REC_00009.WAV",
    "Scotch tape": "REC_00012.WAV",
    "Pop filter": "REC_00015.WAV",
    "Pop filter + Scotch tape": "REC_00016.WAV",
    "Pop filter + electrical tape": "REC_00019.WAV",
    "Confor square pad": "REC_00022.WAV",
    "Confor + Scotch tape": "REC_00025.WAV",
    "Confor + electrical tape": "REC_00028.WAV",
    "Lid off": "REC_00031.WAV",
}


def load_mono(path):
    with wave.open(str(path)) as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        frames = wav.readframes(wav.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").reshape(-1, channels) / 32768.0
    return rate, samples.mean(axis=1)


def band_level_dbfs(path):
    """Mean-square level in BAND_HZ, in dB relative to a full-scale amplitude of 1.0."""
    rate, mono = load_mono(path)
    freqs, psd = welch(mono, fs=rate, window="hann", nperseg=NPERSEG, noverlap=NPERSEG // 2)
    in_band = (freqs >= BAND_HZ[0]) & (freqs < BAND_HZ[1])
    return 10 * np.log10(psd[in_band].sum() * (freqs[1] - freqs[0]))


def compute_rows():
    levels = {name: band_level_dbfs(DATA_DIR / f) for name, f in HIGH_FAN_FILES.items()}
    ref_level = levels[REFERENCE]
    alt_ref_level = band_level_dbfs(DATA_DIR / ALT_REFERENCE_FILE)
    rows = [
        {
            "configuration": name,
            "high_fan_file": HIGH_FAN_FILES[name],
            "level_dbfs_20Hz_20kHz": level,
            "attenuation_vs_lid_off_db": ref_level - level,
            "attenuation_if_ref_REC_00033_db": alt_ref_level - level,
        }
        for name, level in levels.items()
    ]
    return sorted(rows, key=lambda r: r["attenuation_vs_lid_off_db"], reverse=True)


def write_csv(rows):
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: f"{v:.2f}" if isinstance(v, float) else v for k, v in row.items()})


def plot(rows):
    quieter, louder = "#2a78d6", "#e34948"
    ink, secondary, gridline, baseline = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

    rows = rows[::-1]  # barh draws bottom-up; put the largest reduction on top
    names = [r["configuration"] for r in rows]
    values = [r["attenuation_vs_lid_off_db"] for r in rows]
    y = np.arange(len(rows))

    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=300)
    ax.barh(y, values, height=0.5, color=[quieter if v >= 0 else louder for v in values], zorder=2)
    ax.axvline(0, color=baseline, linewidth=1, zorder=3)

    pad = 0.25
    for yi, name, v in zip(y, names, values):
        label = "0.0 (reference)" if name == REFERENCE else f"{v:+.1f}".replace("-", "−")
        ax.text(v + pad if v >= 0 else v - pad, yi, label, va="center",
                ha="left" if v >= 0 else "right", fontsize=9, color=ink)

    ax.set_yticks(y, names)
    ax.set_xlim(min(values) - 1.5, max(values) + 2.0)
    ax.xaxis.grid(True, color=gridline, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(baseline)
    ax.tick_params(length=0, colors=secondary, labelsize=9.5)
    ax.tick_params(axis="y", colors=ink)
    ax.set_xlabel("Level reduction vs. lid off, dB (+ = quieter)", color=secondary, fontsize=9.5)
    ax.set_title("Wind-noise attenuation, hairdryer high (20 Hz–20 kHz)",
                 loc="left", fontweight="bold", color=ink, fontsize=12, pad=12)

    fig.tight_layout()
    fig.savefig(FIGURE_PATH, facecolor="white")


def main():
    rows = compute_rows()
    write_csv(rows)
    plot(rows)
    for r in rows:
        print(f"{r['configuration']:30s} {r['attenuation_vs_lid_off_db']:+6.2f} dB")


if __name__ == "__main__":
    main()
