"""Spectrograms and spectral-peak tracks for the wing speed ramps (takes 0010, 0012).

Outputs (in OUTPUT_DIR):
    wing_ramp_spectrograms.png  mic0-mic3 spectrograms for both ramps
    wing_ramp_peak_tracks.png   peak frequency/level vs time and vs assumed speed
    wing_ramp_peaks.csv         the peak tracks behind the plot

No tunnel-speed log was recorded, so speed is ASSUMED to rise linearly across
each take (0-30 mph for 0010, 30-60 mph for 0012). A data-derived proxy, the
125-500 Hz level of the quiet mics (mic3-mic7), is overlaid so the assumption
can be checked: if it is wrong the proxy will not rise as a straight line.

Usage:
    python wing_ramp_spectrograms.py SESSION_DIR OUTPUT_DIR
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, medfilt, sosfilt, spectrogram

FS = 48000
RAMPS = {
    "0010": ("MMSA8_0010_Wing_0_30", 0.0, 30.0),
    "0012": ("MMSA8_0012_Wing_30_60", 30.0, 60.0),
}
SPEC_MICS = [0, 1, 2, 3]
PEAK_MICS = [3, 4, 5, 6, 7]
PEAK_BAND = (2000.0, 16000.0)  # above the speed-dependent tunnel rumble
MIN_PROMINENCE_DB = 15.0  # a tone must stand this far above the local median floor
FLOOR_HALF_WIDTH_HZ = 400.0
LINE_SPACING_HZ = 1000.0  # fixed interference lines sit at multiples of 1 kHz
LINE_HALF_WIDTH_HZ = 200.0
ONSET_RISE_DB = 10.0  # tunnel start = proxy level this far above its initial floor
NPERSEG = 4096  # 85 ms, 11.7 Hz bins
HOP = 2048
SMOOTH = 9  # median-filter length (frames) for the peak tracks
DB_RANGE = (-110, -30)


def load(session: Path, folder: str, mics: list[int]) -> dict[int, np.ndarray]:
    path = next((session / folder).glob("*.wav"))
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == FS and w.getsampwidth() == 2
        n_ch = w.getnchannels()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    raw = raw.reshape(-1, n_ch)
    return {m: raw[:, m].astype(np.float32) / 32768.0 for m in mics}


def stft_db(x: np.ndarray):
    f, t, s = spectrogram(x, fs=FS, nperseg=NPERSEG, noverlap=NPERSEG - HOP,
                          window="hann", scaling="spectrum", mode="psd")
    return f, t, 10 * np.log10(s + 1e-20)


def band_level(x: np.ndarray, lo: float, hi: float) -> tuple[np.ndarray, np.ndarray]:
    sos = butter(4, [lo, hi], btype="band", fs=FS, output="sos")
    y = sosfilt(sos, x)
    n = len(y) // HOP
    frames = y[: n * HOP].reshape(n, HOP)
    db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-20)
    return (np.arange(n) * HOP + NPERSEG / 2) / FS, db


def tone_track(f: np.ndarray, db: np.ndarray):
    """Per frame, the most prominent narrow peak in PEAK_BAND, or NaN if none.

    Prominence is measured against a running median across frequency, and the
    fixed 1 kHz-spaced interference lines are masked out.
    """
    sel = (f >= PEAK_BAND[0]) & (f <= PEAK_BAND[1])
    fs_, d = f[sel], db[sel]
    k = int(FLOOR_HALF_WIDTH_HZ / (f[1] - f[0])) * 2 + 1
    floor = np.apply_along_axis(medfilt, 0, d, k)
    prom = d - floor
    off = np.abs(((fs_ + LINE_SPACING_HZ / 2) % LINE_SPACING_HZ) - LINE_SPACING_HZ / 2)
    prom[off < LINE_HALF_WIDTH_HZ] = -np.inf
    idx = np.argmax(prom, axis=0)
    best = prom[idx, np.arange(prom.shape[1])]
    ok = best >= MIN_PROMINENCE_DB
    return np.where(ok, fs_[idx], np.nan), np.where(ok, d[idx, np.arange(d.shape[1])], np.nan)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    fig_s, axes_s = plt.subplots(len(SPEC_MICS), len(RAMPS), figsize=(15, 10), sharex="col", sharey=True)
    fig_p, axes_p = plt.subplots(3, len(RAMPS), figsize=(15, 10))
    rows = []
    colors = plt.cm.viridis(np.linspace(0, 0.9, len(PEAK_MICS)))

    for col, (take, (folder, v0, v1)) in enumerate(RAMPS.items()):
        mics = sorted(set(SPEC_MICS) | set(PEAK_MICS) | {3, 4, 5, 6, 7})
        sig = load(args.session, folder, mics)
        dur = len(sig[0]) / FS

        for row, m in enumerate(SPEC_MICS):
            f, t, db = stft_db(sig[m])
            ax = axes_s[row, col]
            im = ax.pcolormesh(t, f / 1000, db, vmin=DB_RANGE[0], vmax=DB_RANGE[1],
                               cmap="magma", shading="auto", rasterized=True)
            ax.set_ylim(0, 16)
            ax.set_ylabel(f"mic{m}  kHz")
            if row == 0:
                ax.set_title(f"take {take}: {v0:.0f}-{v1:.0f} mph ramp")
        axes_s[-1, col].set_xlabel("time (s)")

        # speed proxy: quiet-mic 125-500 Hz level
        proxy = np.mean([band_level(sig[m], 125, 500)[1] for m in (3, 4, 5, 6, 7)], axis=0)
        t_band, _ = band_level(sig[3], 125, 500)
        proxy = medfilt(proxy, SMOOTH)
        # tunnel-start time: first frame where the proxy is ONSET_RISE_DB above its opening floor
        floor0 = np.median(proxy[:20])
        t_on = float(t_band[np.argmax(proxy > floor0 + ONSET_RISE_DB)]) if v0 == 0 else 0.0

        ax_t, ax_l, ax_v = axes_p[:, col]
        for color, m in zip(colors, PEAK_MICS):
            f, t, db = stft_db(sig[m])
            pk_f, pk_db = tone_track(f, db)
            speed = v0 + (v1 - v0) * np.clip((t - t_on) / (dur - t_on), 0, 1)
            ax_t.plot(t, pk_f / 1000, ".", ms=2, color=color, label=f"mic{m}")
            ax_l.plot(t, pk_db, ".", ms=2, color=color)
            ax_v.plot(speed, pk_f / 1000, ".", ms=2, color=color)
            rows += [[take, m, round(float(a), 3), round(float(b), 2), round(float(c), 1), round(float(d), 2)]
                     for a, b, c, d in zip(t, speed, pk_f, pk_db) if not np.isnan(c)]

        ax_p2 = ax_l.twinx()
        ax_p2.plot(t_band, proxy, color="tab:red", lw=1.2, alpha=0.7)
        ax_p2.set_ylabel("125-500 Hz quiet-mic level (dB)\n[speed proxy, red]", color="tab:red")

        ax_t.set_title(f"take {take}: tonal peaks >{MIN_PROMINENCE_DB:.0f} dB above floor, "
                       f"{PEAK_BAND[0] / 1000:.0f}-{PEAK_BAND[1] / 1000:.0f} kHz")
        ax_t.set_ylabel("tone frequency (kHz)")
        ax_l.set_ylabel("peak level (dB/bin)")
        ax_l.set_xlabel("time (s)")
        ax_v.set_xlabel(f"assumed speed (mph), linear {v0:.0f}->{v1:.0f} from t={t_on:.0f} s")
        ax_v.set_ylabel("tone frequency (kHz)")
        ax_t.legend(ncol=5, fontsize=8, markerscale=4)

    fig_s.colorbar(im, ax=axes_s, label="dB re FS (PSD)", shrink=0.6)
    fig_s.suptitle("Wing ramp spectrograms")
    fig_p.suptitle("Tonal-peak tracks (fixed 1 kHz lines masked). No speed log: speed axis is "
                   "an assumption; red proxy checks it")
    fig_s.savefig(args.output / "wing_ramp_spectrograms.png", dpi=130, bbox_inches="tight")
    fig_p.savefig(args.output / "wing_ramp_peak_tracks.png", dpi=130, bbox_inches="tight")

    with open(args.output / "wing_ramp_peaks.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["take", "mic", "time_s", "assumed_speed_mph", "tone_freq_hz", "tone_db"])
        w.writerows(rows)
    print("wrote", args.output)


if __name__ == "__main__":
    main()
