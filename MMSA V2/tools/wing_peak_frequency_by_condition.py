"""Summarize narrowband peak frequency and severity for every wing microphone."""

from __future__ import annotations

import argparse
import csv
import math
import wave
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import medfilt, welch


FS = 48_000
CHANNELS = 8
BLOCK_SECONDS = 2.0
NPERSEG = 4096
NOVERLAP = 2048
SEARCH_BAND = (2000.0, 16_000.0)
FLOOR_HALF_WIDTH_HZ = 400.0
LINE_SPACING_HZ = 1000.0
LINE_HALF_WIDTH_HZ = 200.0
DETECTION_PROMINENCE_DB = 15.0

RUNS = [
    (9, "MMSA8_0009_Wing_0", "Tunnel off"),
    (10, "MMSA8_0010_Wing_0_30", "0–30 mph ramp"),
    (11, "MMSA8_0011_Wing_30", "Steady 30 mph"),
    (12, "MMSA8_0012_Wing_30_60", "30–60 mph ramp"),
    (13, "MMSA8_0013_Wing_60", "Steady 60 mph"),
]


def block_peak(samples: np.ndarray) -> tuple[float, float, float]:
    """Return frequency, prominence, and PSD level of the strongest non-1-kHz peak."""
    frequencies, psd = welch(
        samples,
        fs=FS,
        window="hann",
        nperseg=NPERSEG,
        noverlap=NOVERLAP,
        scaling="density",
    )
    db = 10.0 * np.log10(psd + 1e-30)
    selected = (frequencies >= SEARCH_BAND[0]) & (frequencies <= SEARCH_BAND[1])
    band_f = frequencies[selected]
    band_db = db[selected]
    bin_width = frequencies[1] - frequencies[0]
    kernel = int(FLOOR_HALF_WIDTH_HZ / bin_width) * 2 + 1
    local_floor = medfilt(band_db, kernel_size=kernel)
    prominence = band_db - local_floor

    # Fixed lines at integer multiples of 1 kHz are present even with the
    # tunnel off. Exclude them so the result emphasizes condition-responsive
    # peaks rather than the stationary electrical comb.
    distance_to_line = np.abs(
        ((band_f + LINE_SPACING_HZ / 2.0) % LINE_SPACING_HZ) - LINE_SPACING_HZ / 2.0
    )
    prominence[distance_to_line < LINE_HALF_WIDTH_HZ] = -np.inf
    index = int(np.argmax(prominence))
    return float(band_f[index]), float(prominence[index]), float(band_db[index])


def analyze_run(session: Path, folder: str) -> list[dict[str, float]]:
    paths = sorted((session / folder).glob("*.wav"))
    if not paths:
        raise FileNotFoundError(f"No WAV files found under {session / folder}")

    frequencies: list[list[float]] = [[] for _ in range(CHANNELS)]
    prominences: list[list[float]] = [[] for _ in range(CHANNELS)]
    levels: list[list[float]] = [[] for _ in range(CHANNELS)]
    clipped = np.zeros(CHANNELS, dtype=np.int64)
    sample_count = np.zeros(CHANNELS, dtype=np.int64)
    frames_per_block = round(BLOCK_SECONDS * FS)

    for path in paths:
        with wave.open(str(path), "rb") as wav:
            if wav.getframerate() != FS or wav.getnchannels() != CHANNELS or wav.getsampwidth() != 2:
                raise ValueError(f"Unexpected WAV format: {path}")
            while True:
                raw_bytes = wav.readframes(frames_per_block)
                if not raw_bytes:
                    break
                raw = np.frombuffer(raw_bytes, dtype="<i2")
                complete = len(raw) // CHANNELS
                if complete < NPERSEG:
                    continue
                raw = raw[: complete * CHANNELS].reshape(complete, CHANNELS)
                clipped += np.sum(np.abs(raw.astype(np.int32)) >= 32767, axis=0)
                sample_count += complete
                normalized = raw.astype(np.float32) / 32768.0
                for mic in range(CHANNELS):
                    frequency, prominence, level = block_peak(normalized[:, mic])
                    frequencies[mic].append(frequency)
                    prominences[mic].append(prominence)
                    levels[mic].append(level)

    summaries: list[dict[str, float]] = []
    for mic in range(CHANNELS):
        freq = np.asarray(frequencies[mic])
        prom = np.asarray(prominences[mic])
        level = np.asarray(levels[mic])
        top_cutoff = np.percentile(prom, 90)
        severe = prom >= top_cutoff
        summaries.append(
            {
                "mic": float(mic),
                "peak_frequency_hz": float(np.median(freq[severe])),
                "p95_prominence_db": float(np.percentile(prom, 95)),
                "peak_psd_dbfs_hz": float(np.median(level[severe])),
                "detection_fraction": float(np.mean(prom >= DETECTION_PROMINENCE_DB)),
                "clipped_percent": float(100.0 * clipped[mic] / max(sample_count[mic], 1)),
                "blocks": float(len(prom)),
            }
        )
    return summaries


def annotation_color(value: float, normalized: float) -> str:
    return "white" if normalized < 0.36 or normalized > 0.78 else "#111111"


def plot_summary(rows: list[dict[str, float]], output: Path) -> None:
    conditions = [label for _, _, label in RUNS]
    peak_frequency = np.full((len(RUNS), CHANNELS), np.nan)
    prominence = np.full_like(peak_frequency, np.nan)
    clipped = np.zeros_like(peak_frequency)
    for row in rows:
        condition_index = int(row["condition_index"])
        mic = int(row["mic"])
        peak_frequency[condition_index, mic] = row["peak_frequency_hz"] / 1000.0
        prominence[condition_index, mic] = row["p95_prominence_db"]
        clipped[condition_index, mic] = row["clipped_percent"]

    frequency_display = peak_frequency.copy()
    frequency_display[prominence < DETECTION_PROMINENCE_DB] = np.nan
    frequency_cmap = plt.get_cmap("viridis").copy()
    frequency_cmap.set_bad("#e7e9ec")

    fig, axes = plt.subplots(2, 1, figsize=(15.5, 8.7))
    fig.subplots_adjust(left=0.13, right=0.89, top=0.83, bottom=0.12, hspace=0.43)
    fig.suptitle(
        "Narrowband peaking frequency and severity by microphone",
        y=0.975,
        fontsize=19,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.925,
        "Frequency is reported only when the 95th-percentile prominence is at least 15 dB; severity is retained for every cell",
        ha="center",
        fontsize=11,
        color="#444444",
    )

    frequency_image = axes[0].imshow(
        frequency_display,
        aspect="auto",
        cmap=frequency_cmap,
        vmin=SEARCH_BAND[0] / 1000.0,
        vmax=SEARCH_BAND[1] / 1000.0,
    )
    severity_max = max(25.0, math.ceil(float(np.nanmax(prominence)) / 5.0) * 5.0)
    prominence_image = axes[1].imshow(
        prominence,
        aspect="auto",
        cmap="magma",
        vmin=0.0,
        vmax=severity_max,
    )

    for axis, title in zip(
        axes,
        (
            "Representative peak frequency (kHz)",
            "Peak prominence: 95th percentile (dB above local spectral floor)",
        ),
    ):
        axis.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=8)
        axis.set_xticks(np.arange(CHANNELS), [f"mic{mic}" for mic in range(CHANNELS)])
        axis.set_yticks(np.arange(len(conditions)), conditions)
        axis.tick_params(labelsize=10.5)
        axis.set_xticks(np.arange(-0.5, CHANNELS, 1), minor=True)
        axis.set_yticks(np.arange(-0.5, len(conditions), 1), minor=True)
        axis.grid(which="minor", color="white", linewidth=1.6, alpha=0.7)
        axis.tick_params(which="minor", bottom=False, left=False)

    for condition_index in range(len(conditions)):
        for mic in range(CHANNELS):
            star = "*" if clipped[condition_index, mic] > 0 else ""
            frequency_value = frequency_display[condition_index, mic]
            frequency_norm = (
                (frequency_value - SEARCH_BAND[0] / 1000.0)
                / ((SEARCH_BAND[1] - SEARCH_BAND[0]) / 1000.0)
                if np.isfinite(frequency_value)
                else 0.5
            )
            axes[0].text(
                mic,
                condition_index,
                f"{frequency_value:.1f}{star}" if np.isfinite(frequency_value) else "—",
                ha="center",
                va="center",
                fontsize=10.5,
                fontweight="bold",
                color=annotation_color(frequency_value, frequency_norm) if np.isfinite(frequency_value) else "#666666",
            )
            severity_value = prominence[condition_index, mic]
            severity_norm = severity_value / severity_max
            axes[1].text(
                mic,
                condition_index,
                f"{severity_value:.1f}{star}",
                ha="center",
                va="center",
                fontsize=10.5,
                fontweight="bold",
                color=annotation_color(severity_value, severity_norm),
            )

    fig.colorbar(frequency_image, ax=axes[0], label="Peak frequency (kHz)", pad=0.012)
    fig.colorbar(prominence_image, ax=axes[1], label="Prominence (dB)", pad=0.012)
    fig.text(
        0.5,
        0.025,
        "2 s blocks; 4096-point Welch PSD; 2–16 kHz search. Fixed 1 kHz electrical-comb lines excluded.  * clipping observed; estimate may be biased.",
        ha="center",
        fontsize=9.5,
        color="#444444",
    )
    fig.savefig(output, dpi=220, facecolor="white")
    fig.savefig(output.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, float]] = []
    for condition_index, (take, folder, label) in enumerate(RUNS):
        print(f"analyzing take {take:04d}: {label}", flush=True)
        for summary in analyze_run(args.session, folder):
            rows.append(
                {
                    "condition_index": float(condition_index),
                    "take": float(take),
                    "condition": label,
                    **summary,
                }
            )

    csv_path = args.output_dir / "wing_peak_frequency_by_condition.csv"
    fieldnames = [
        "take",
        "condition",
        "mic",
        "peak_frequency_hz",
        "p95_prominence_db",
        "peak_psd_dbfs_hz",
        "detection_fraction",
        "clipped_percent",
        "blocks",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fieldnames})

    plot_path = args.output_dir / "wing_peak_frequency_by_condition.png"
    plot_summary(rows, plot_path)
    print(csv_path.resolve())
    print(plot_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
