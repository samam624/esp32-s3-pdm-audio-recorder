"""Analyze a labeled MMSA wind-tunnel session and visualize flow-level progression.

The session directory is expected to contain one folder per take, for example::

    MMSA8_0005_Floor_0_30/
    MMSA8_0010_Wing_0_30/

Each folder may contain one or more eight-channel, 16-bit PCM WAV segments. The
tool keeps firmware microphone numbering (mic0 through mic7), measures the same
five frequency bands used by the recorder firmware plus a 20 Hz-20 kHz total,
checks clipping, and writes both machine-readable CSVs and summary figures.

The wing figures are intended to reveal a high-level or "peaking" region moving
from the aft microphones (mic0/mic1 in the first tunnel installation) toward
mic2 as tunnel speed increases. They visualize acoustic/electrical level only;
identifying boundary-layer transition requires repeat runs and synchronized
tunnel-speed/geometry metadata.

Usage::

    python wind_tunnel_analysis.py "MMSA V2/data/102926/102926"
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys
import wave

import matplotlib.pyplot as plt
import numpy as np


FULL_SCALE = 32768.0
BANDS = (
    ("total_20_20k", 20.0, 20_000.0),
    ("band_20_125", 20.0, 125.0),
    ("band_125_500", 125.0, 500.0),
    ("band_500_2k", 500.0, 2_000.0),
    ("band_2k_8k", 2_000.0, 8_000.0),
    ("band_8k_20k", 8_000.0, 20_000.0),
)
RUN_RE = re.compile(
    r"^MMSA8_(?P<take>\d{4})_(?P<mount>Floor|Wing)_(?P<condition>.+)$",
    re.IGNORECASE,
)
TAKE_RE = re.compile(r"MMSA8_(?P<take>\d{4})", re.IGNORECASE)


@dataclass(frozen=True)
class Run:
    take: int
    mount: str
    condition: str
    label: str
    wav: Path


@dataclass
class Analysis:
    run: Run
    sample_rate: int
    duration_s: float
    times_s: np.ndarray
    levels_dbfs: np.ndarray  # window, mic, band
    peak_dbfs: np.ndarray  # mic
    clipped_samples: np.ndarray  # mic


def parse_run(wav_path: Path) -> Run:
    """Use the closest labeled parent folder, falling back to the WAV name."""
    for candidate in (wav_path.parent.name, wav_path.stem):
        match = RUN_RE.match(candidate)
        if match:
            take = int(match.group("take"))
            mount = match.group("mount").title()
            condition = match.group("condition")
            return Run(take, mount, condition, f"{take:04d} {mount} {condition}", wav_path)

    match = TAKE_RE.search(wav_path.stem)
    take = int(match.group("take")) if match else 9999
    return Run(take, "Pretest", wav_path.parent.name, f"{take:04d} Pretest", wav_path)


def discover_runs(session_dir: Path) -> list[Run]:
    wavs = [p for p in session_dir.rglob("*.wav") if "analysis" not in p.parts]
    runs = [parse_run(p) for p in wavs]
    return sorted(runs, key=lambda run: (run.take, run.wav.name.lower()))


def analyze_wav(run: Run, window_ms: float, hop_ms: float) -> Analysis:
    with wave.open(str(run.wav), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.getnframes()
        compression = wav_file.getcomptype()
        if channels != 8 or sample_width != 2 or compression != "NONE":
            raise ValueError(
                f"{run.wav}: expected 8-channel, 16-bit uncompressed PCM; "
                f"found {channels} channels, {sample_width * 8} bit, {compression}"
            )
        raw = wav_file.readframes(frames)

    samples = np.frombuffer(raw, dtype="<i2").reshape(-1, channels)
    window_frames = max(1, round(sample_rate * window_ms / 1000.0))
    hop_frames = max(1, round(sample_rate * hop_ms / 1000.0))
    if len(samples) < window_frames:
        raise ValueError(f"{run.wav}: recording is shorter than one analysis window")

    starts = np.arange(0, len(samples) - window_frames + 1, hop_frames)
    times_s = (starts + window_frames / 2.0) / sample_rate
    frequencies = np.fft.rfftfreq(window_frames, 1.0 / sample_rate)
    taper = np.hanning(window_frames)[:, None]
    taper_energy = float(np.sum(taper[:, 0] ** 2))
    masks = [(frequencies >= lo) & (frequencies < hi) for _, lo, hi in BANDS]
    levels = np.empty((len(starts), channels, len(BANDS)), dtype=np.float32)

    for index, start in enumerate(starts):
        segment = samples[start : start + window_frames].astype(np.float64)
        segment -= segment.mean(axis=0, keepdims=True)
        spectrum = np.fft.rfft(segment * taper, axis=0)
        power_bins = np.abs(spectrum) ** 2
        if window_frames % 2 == 0:
            power_bins[1:-1] *= 2.0
        else:
            power_bins[1:] *= 2.0
        for band_index, mask in enumerate(masks):
            mean_square = power_bins[mask].sum(axis=0) / (window_frames * taper_energy)
            levels[index, :, band_index] = 10.0 * np.log10(
                np.maximum(mean_square, 1e-30) / FULL_SCALE**2
            )

    # Use raw stored values for digital peak/clipping. A locally de-meaned
    # signal can mathematically exceed full scale even though the ADC/PDM
    # samples cannot, which makes a misleading positive dBFS peak.
    peak = np.max(np.abs(samples.astype(np.int32)), axis=0)
    peak_dbfs = 20.0 * np.log10(np.maximum(peak, 1e-30) / FULL_SCALE)
    clipped = np.sum((samples <= -32768) | (samples >= 32767), axis=0)
    return Analysis(
        run=run,
        sample_rate=sample_rate,
        duration_s=len(samples) / sample_rate,
        times_s=times_s,
        levels_dbfs=levels,
        peak_dbfs=peak_dbfs,
        clipped_samples=clipped,
    )


def write_window_csv(path: Path, analyses: list[Analysis]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            ["take", "mount", "condition", "wav", "time_s", "mic"]
            + [name + "_dbfs" for name, _, _ in BANDS]
        )
        for analysis in analyses:
            for window_index, time_s in enumerate(analysis.times_s):
                for mic in range(8):
                    writer.writerow(
                        [
                            f"{analysis.run.take:04d}",
                            analysis.run.mount,
                            analysis.run.condition,
                            analysis.run.wav.name,
                            f"{time_s:.4f}",
                            mic,
                        ]
                        + [f"{value:.3f}" for value in analysis.levels_dbfs[window_index, mic]]
                    )


def write_summary_csv(path: Path, analyses: list[Analysis]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "take",
                "mount",
                "condition",
                "wav",
                "duration_s",
                "sample_rate_hz",
                "mic",
                "band",
                "median_dbfs",
                "p90_dbfs",
                "p99_dbfs",
                "relative_to_mic3_7_median_db",
                "peak_dbfs",
                "clipped_samples",
                "clipped_percent",
            ]
        )
        for analysis in analyses:
            medians = np.median(analysis.levels_dbfs, axis=0)
            p90 = np.percentile(analysis.levels_dbfs, 90, axis=0)
            p99 = np.percentile(analysis.levels_dbfs, 99, axis=0)
            forward_reference = np.median(medians[3:8], axis=0)
            for mic in range(8):
                for band_index, (band_name, _, _) in enumerate(BANDS):
                    writer.writerow(
                        [
                            f"{analysis.run.take:04d}",
                            analysis.run.mount,
                            analysis.run.condition,
                            analysis.run.wav.name,
                            f"{analysis.duration_s:.4f}",
                            analysis.sample_rate,
                            mic,
                            band_name,
                            f"{medians[mic, band_index]:.3f}",
                            f"{p90[mic, band_index]:.3f}",
                            f"{p99[mic, band_index]:.3f}",
                            f"{medians[mic, band_index] - forward_reference[band_index]:.3f}",
                            f"{analysis.peak_dbfs[mic]:.3f}",
                            int(analysis.clipped_samples[mic]),
                            f"{100.0 * analysis.clipped_samples[mic] / (analysis.duration_s * analysis.sample_rate):.6f}",
                        ]
                    )


def write_zone_onsets_csv(path: Path, analyses: list[Analysis]) -> None:
    """Report sustained entry into the broadband high-level region.

    A mic is in the region when it is within 6 dB of that window's loudest
    channel while the loudest channel exceeds -20 dBFS. Requiring two seconds
    of consecutive windows rejects short tunnel/handling transients.
    """
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "take",
                "condition",
                "mic",
                "onset_s",
                "recording_fraction",
                "within_loudest_db",
                "minimum_loudest_dbfs",
                "sustain_s",
            ]
        )
        for analysis in analyses:
            if analysis.run.mount != "Wing" or "_" not in analysis.run.condition:
                continue
            total = analysis.levels_dbfs[:, :, 0]
            window_max = np.max(total, axis=1)
            hop_s = float(np.median(np.diff(analysis.times_s))) if len(analysis.times_s) > 1 else 0.05
            required = max(1, math.ceil(2.0 / hop_s))
            for mic in range(8):
                in_zone = (window_max > -20.0) & (total[:, mic] >= window_max - 6.0)
                sustained = np.convolve(in_zone.astype(np.int16), np.ones(required, dtype=np.int16), mode="valid")
                matches = np.flatnonzero(sustained == required)
                if len(matches):
                    onset = float(analysis.times_s[matches[0]])
                    writer.writerow(
                        [
                            f"{analysis.run.take:04d}",
                            analysis.run.condition,
                            mic,
                            f"{onset:.3f}",
                            f"{onset / analysis.duration_s:.5f}",
                            6,
                            -20,
                            2,
                        ]
                    )
                else:
                    writer.writerow(
                        [f"{analysis.run.take:04d}", analysis.run.condition, mic, "", "", 6, -20, 2]
                    )


def save_overview(path: Path, analyses: list[Analysis]) -> None:
    values = np.stack([np.median(a.levels_dbfs[:, :, 0], axis=0) for a in analyses])
    fig_height = max(3.5, 0.48 * len(analyses) + 1.8)
    fig, ax = plt.subplots(figsize=(10.5, fig_height))
    lo, hi = np.percentile(values, [2, 98])
    image = ax.imshow(values, aspect="auto", cmap="magma", vmin=lo, vmax=hi)
    ax.set(
        title="Wind-tunnel session: median 20 Hz-20 kHz level",
        xlabel="Firmware microphone number",
        ylabel="Take / installation / condition",
        xticks=np.arange(8),
        yticks=np.arange(len(analyses)),
        yticklabels=[a.run.label for a in analyses],
    )
    colorbar = fig.colorbar(image, ax=ax, pad=0.02)
    colorbar.set_label("Median level (dBFS)")
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            ax.text(column, row, f"{values[row, column]:.1f}", ha="center", va="center", fontsize=7,
                    color="white" if values[row, column] < (lo + hi) / 2 else "black")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def save_wing_profiles(path: Path, wing: list[Analysis]) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), sharex=True)
    for band_index, ((band_name, lo_hz, hi_hz), ax) in enumerate(zip(BANDS, axes.flat)):
        all_values = []
        for analysis in wing:
            median = np.median(analysis.levels_dbfs[:, :, band_index], axis=0)
            all_values.extend(median.tolist())
            ax.plot(np.arange(8), median, marker="o", linewidth=1.6, label=analysis.run.condition)
        ax.axvspan(-0.25, 2.25, color="#ff9f1c", alpha=0.08)
        ax.set_title(f"{band_name.replace('_', ' ')} ({lo_hz:g}-{hi_hz:g} Hz)")
        ax.set_xticks(np.arange(8))
        ax.grid(alpha=0.25)
        if all_values:
            low, high = np.percentile(all_values, [2, 98])
            margin = max(2.0, 0.12 * (high - low))
            ax.set_ylim(low - margin, high + margin)
    axes[0, 0].legend(title="Wing condition", fontsize=8)
    for ax in axes[:, 0]:
        ax.set_ylabel("Median level (dBFS)")
    for ax in axes[-1, :]:
        ax.set_xlabel("Microphone (mic0/mic1 aftmost)")
    fig.suptitle("Wing installation: level profile along the array", fontsize=14)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def save_wing_heatmaps(path: Path, wing: list[Analysis], relative: bool) -> None:
    rows = len(wing)
    fig, axes = plt.subplots(rows, 1, figsize=(13, max(3.2, 2.6 * rows)), squeeze=False)
    matrices = []
    for analysis in wing:
        matrix = analysis.levels_dbfs[:, :, 0].T
        if relative:
            matrix = matrix - np.max(matrix, axis=0, keepdims=True)
        matrices.append(matrix)

    if relative:
        vmin, vmax, cmap = -15.0, 0.0, "viridis"
        title = "Wing runs: level relative to the loudest microphone in each 100 ms window"
        color_label = "Level below window maximum (dB)"
    else:
        joined = np.concatenate([matrix.ravel() for matrix in matrices])
        vmin, vmax = np.percentile(joined, [2, 98])
        cmap = "magma"
        title = "Wing runs: 20 Hz-20 kHz level over time"
        color_label = "Level (dBFS)"

    last_image = None
    for ax, analysis, matrix in zip(axes[:, 0], wing, matrices):
        extent = [0.0, analysis.duration_s, 7.5, -0.5]
        last_image = ax.imshow(matrix, aspect="auto", interpolation="nearest", extent=extent,
                               cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_ylabel("Mic")
        ax.set_yticks(np.arange(8))
        ax.set_title(f"Take {analysis.run.take:04d}: {analysis.run.condition}", loc="left", fontsize=10)
        ax.axhline(2.5, color="white", alpha=0.45, linewidth=0.8)
    axes[-1, 0].set_xlabel("Time in recording (s)")
    fig.suptitle(title, fontsize=14)
    fig.subplots_adjust(right=0.88, top=0.92, hspace=0.42)
    color_ax = fig.add_axes([0.90, 0.12, 0.018, 0.74])
    fig.colorbar(last_image, cax=color_ax, label=color_label)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_readme(path: Path, analyses: list[Analysis], missing_labels: list[str]) -> None:
    clipped = [
        f"take {a.run.take:04d} mic{mic}: {int(count)} samples"
        for a in analyses
        for mic, count in enumerate(a.clipped_samples)
        if count
    ]
    lines = [
        "# Wind-tunnel analysis outputs",
        "",
        f"Processed {len(analyses)} WAV file(s) with 100 ms Hann-windowed spectra.",
        "Microphone labels are firmware labels (`mic0` through `mic7`).",
        "",
        "## Files",
        "",
        "- `window_levels.csv`: one row per analysis window and microphone.",
        "- `run_summary.csv`: median, upper-percentile, relative-level, peak, and clipping metrics.",
        "- `wing_zone_onsets.csv`: sustained entry into the high-level zone during each wing ramp.",
        "- `session_overview.png`: median broadband level for every available take.",
        "- `wing_profiles.png`: frequency-band profiles along the wing array (when wing WAVs are present).",
        "- `wing_level_heatmaps.png`: absolute broadband level over time (when wing WAVs are present).",
        "- `wing_peak_zone.png`: each mic relative to the loudest mic in that window; useful for seeing the high-level zone spread from mic0/mic1 toward mic2.",
        "",
        "## Clipping",
        "",
    ]
    lines.extend([f"- {item}" for item in clipped] or ["- No exact full-scale samples detected."])
    if missing_labels:
        lines += ["", "## Missing expected runs", ""]
        lines.extend(f"- {label}" for label in missing_labels)
    lines += [
        "",
        "## Interpretation limit",
        "",
        "These plots show recorded signal level, not a calibrated wall-pressure spectrum. A moving high-level region is consistent with a flow-regime change, but repeatability, tunnel-speed timing, microphone position, and sensitivity calibration are needed before labeling it as boundary-layer transition.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", type=Path, help="directory containing the labeled take folders")
    parser.add_argument("--output", "-o", type=Path, help="output directory (default: SESSION/analysis)")
    parser.add_argument("--window-ms", type=float, default=100.0)
    parser.add_argument("--hop-ms", type=float, default=50.0)
    args = parser.parse_args(argv)
    if args.window_ms <= 0 or args.hop_ms <= 0:
        parser.error("window and hop lengths must be positive")

    session = args.session.resolve()
    if not session.is_dir():
        parser.error(f"session directory not found: {session}")
    output = (args.output or session / "analysis").resolve()
    output.mkdir(parents=True, exist_ok=True)

    runs = discover_runs(session)
    if not runs:
        print(f"error: no WAV files found under {session}", file=sys.stderr)
        return 2

    analyses = []
    for run in runs:
        analysis = analyze_wav(run, args.window_ms, args.hop_ms)
        analyses.append(analysis)
        clip_text = ", ".join(
            f"mic{mic}={int(count)}" for mic, count in enumerate(analysis.clipped_samples) if count
        ) or "none"
        print(
            f"{run.label}: {analysis.duration_s:.2f} s, {analysis.sample_rate} Hz, "
            f"{len(analysis.times_s)} windows, clipping {clip_text}"
        )

    write_window_csv(output / "window_levels.csv", analyses)
    write_summary_csv(output / "run_summary.csv", analyses)
    write_zone_onsets_csv(output / "wing_zone_onsets.csv", analyses)
    save_overview(output / "session_overview.png", analyses)

    wing = [analysis for analysis in analyses if analysis.run.mount == "Wing"]
    if wing:
        save_wing_profiles(output / "wing_profiles.png", wing)
        save_wing_heatmaps(output / "wing_level_heatmaps.png", wing, relative=False)
        save_wing_heatmaps(output / "wing_peak_zone.png", wing, relative=True)
    else:
        print("No wing WAVs found; wing-specific figures were not created.")

    expected = [
        "0003 Floor 0",
        "0004 Floor 0",
        "0005 Floor 0_30",
        "0006 Floor 30",
        "0007 Floor 30_60",
        "0008 Floor 60",
        "0009 Wing 0",
        "0010 Wing 0_30",
        "0011 Wing 30",
        "0012 Wing 30_60",
        "0013 Wing 60",
    ]
    present = {f"{a.run.take:04d} {a.run.mount} {a.run.condition}" for a in analyses}
    missing = [label for label in expected if label not in present]
    write_readme(output / "README.md", analyses, missing)
    print(f"Outputs: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
