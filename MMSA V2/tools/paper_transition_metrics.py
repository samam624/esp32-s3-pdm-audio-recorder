"""Apply the Ozcakmak et al. transition metrics to the 2026-10-29 wing data.

The paper integrates the one-sided pressure PSD from 2 to 7 kHz and uses:

    Lp = 10 log10(integral(PSD df)) + calibration constant
    f_mu = integral(f PSD df) / integral(PSD df)

The MMSA recordings do not yet have an installed-port pressure calibration, so
this script reports the first quantity as band level in dBFS.  The unknown SPL
calibration is a vertical offset for a flat sensitivity response; it does not
change the chordwise derivative.  f_mu is invariant to a scalar sensitivity
factor, but remains sensitive to frequency response and clipping.

Microphone x/c values are obtained from the registered array photograph.  They
are converted to the conventional airfoil coordinate (0 = leading edge,
1 = trailing edge).  Because only eight spatial samples exist, transition is
reported as the microphone-to-microphone bracket containing the largest
positive chordwise slope, not as a falsely precise interpolated coordinate.

Outputs:
    paper_metrics_spatial.png
    paper_metric_derivatives.png
    paper_metrics_ramp_map.png
    paper_metrics_before_after_psd.png
    paper_transition_profiles.csv
    paper_transition_picks.csv
    paper_ramp_metrics.csv
    PAPER_METHODS.md

Usage:
    python paper_transition_metrics.py SESSION_DIR OUTPUT_DIR
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import wave

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.signal import welch

import overlay_flow_photos as photo_registration


FS = 48_000
CHANNELS = 8
NFFT = 2048
NOVERLAP = 1024
BAND = (2_000.0, 7_000.0)
BLOCK_SECONDS = 2.0

TAKES = {
    "off": "MMSA8_0009_Wing_0",
    "30": "MMSA8_0011_Wing_30",
    "ramp": "MMSA8_0012_Wing_30_60",
    "60": "MMSA8_0013_Wing_60",
}

# Photo-registered coordinates, converted from the image's aft-edge convention
# to conventional distance from the leading edge.  Derive them directly from
# the shared registration so corrected port centers cannot drift out of sync.
MIC_XC = 1.0 - np.array([photo_registration.mic_xc(i) for i in range(CHANNELS)])

COLORS = {"off": "#777777", "30": "#2f6db5", "60": "#d55e00"}
LOW_COLOR = "#dceaf7"
TRANS_COLOR = "#f9d7a8"
HIGH_COLOR = "#f6c5bf"


@dataclass
class TakeMetrics:
    key: str
    wav: Path
    times_s: np.ndarray
    lp_dbfs: np.ndarray
    fmu_hz: np.ndarray
    clipped_percent: np.ndarray
    frequency_hz: np.ndarray
    median_psd: np.ndarray


@dataclass(frozen=True)
class Pick:
    condition: str
    metric: str
    leading_mic: int
    trailing_mic: int
    x_lo: float
    x_hi: float
    x_mid: float
    delta: float
    slope: float


def find_wav(session: Path, key: str) -> Path:
    wavs = sorted((session / TAKES[key]).glob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"No WAV found under {session / TAKES[key]}")
    return wavs[0]


def band_metrics(frequency: np.ndarray, psd: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mask = (frequency >= BAND[0]) & (frequency <= BAND[1])
    f = frequency[mask]
    p = psd[mask]
    power = np.trapezoid(p, f, axis=0)
    lp = 10.0 * np.log10(np.maximum(power, 1e-30))
    fmu = np.trapezoid(f[:, None] * p, f, axis=0) / np.maximum(power, 1e-30)
    return lp, fmu


def analyse_take(session: Path, key: str, block_seconds: float = BLOCK_SECONDS) -> TakeMetrics:
    wav_path = find_wav(session, key)
    block_frames = round(block_seconds * FS)
    skip_frames = round(0.3 * FS)
    times: list[float] = []
    levels: list[np.ndarray] = []
    moments: list[np.ndarray] = []
    clipping: list[np.ndarray] = []
    spectra: list[np.ndarray] = []
    frequency: np.ndarray | None = None

    with wave.open(str(wav_path), "rb") as wav_file:
        if (wav_file.getframerate(), wav_file.getnchannels(), wav_file.getsampwidth()) != (FS, CHANNELS, 2):
            raise ValueError(f"Unexpected WAV format: {wav_path}")
        wav_file.setpos(min(skip_frames, wav_file.getnframes()))
        block_index = 0
        while True:
            raw = wav_file.readframes(block_frames)
            if len(raw) < block_frames * CHANNELS * 2:
                break
            pcm = np.frombuffer(raw, dtype="<i2").reshape(-1, CHANNELS)
            x = pcm.astype(np.float32) / 32768.0
            frequency, psd = welch(
                x,
                fs=FS,
                window="hann",
                nperseg=NFFT,
                noverlap=NOVERLAP,
                nfft=NFFT,
                detrend="constant",
                return_onesided=True,
                scaling="density",
                axis=0,
            )
            lp, fmu = band_metrics(frequency, psd)
            levels.append(lp)
            moments.append(fmu)
            spectra.append(psd.astype(np.float32))
            clipping.append(100.0 * np.mean((pcm <= -32768) | (pcm >= 32767), axis=0))
            times.append(0.3 + (block_index + 0.5) * block_seconds)
            block_index += 1

    if frequency is None or not levels:
        raise ValueError(f"No complete analysis block in {wav_path}")
    return TakeMetrics(
        key=key,
        wav=wav_path,
        times_s=np.asarray(times),
        lp_dbfs=np.asarray(levels),
        fmu_hz=np.asarray(moments),
        clipped_percent=np.asarray(clipping),
        frequency_hz=frequency,
        median_psd=np.median(np.asarray(spectra), axis=0),
    )


def sorted_profile(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    order = np.argsort(MIC_XC)
    return MIC_XC[order], np.asarray(values)[order], order


def transition_pick(condition: str, metric: str, values: np.ndarray) -> Pick:
    x, y, order = sorted_profile(values)
    slopes = np.diff(y) / np.diff(x)
    edge = int(np.argmax(slopes))
    return Pick(
        condition=condition,
        metric=metric,
        leading_mic=int(order[edge]),
        trailing_mic=int(order[edge + 1]),
        x_lo=float(x[edge]),
        x_hi=float(x[edge + 1]),
        x_mid=float((x[edge] + x[edge + 1]) / 2.0),
        delta=float(y[edge + 1] - y[edge]),
        slope=float(slopes[edge]),
    )


def dense_profile(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x, y, _ = sorted_profile(values)
    dense_x = np.linspace(x[0], x[-1], 400)
    dense_y = PchipInterpolator(x, y)(dense_x)
    return dense_x, dense_y


def shade_flow_sides(ax: plt.Axes, pick: Pick) -> None:
    xmin, xmax = float(MIC_XC.min()), float(MIC_XC.max())
    ax.axvspan(xmin, pick.x_lo, color=LOW_COLOR, alpha=0.58, lw=0)
    ax.axvspan(pick.x_lo, pick.x_hi, color=TRANS_COLOR, alpha=0.72, lw=0)
    ax.axvspan(pick.x_hi, xmax, color=HIGH_COLOR, alpha=0.46, lw=0)
    ax.axvline(pick.x_mid, color="#8c510a", lw=1.2, ls="--")


def plot_spatial(metrics: dict[str, TakeMetrics], picks: dict[tuple[str, str], Pick], output: Path) -> None:
    plt.rcParams.update({"font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=True)

    for col, condition in enumerate(("30", "60")):
        take = metrics[condition]
        lp = np.median(take.lp_dbfs, axis=0)
        fmu = np.median(take.fmu_hz, axis=0)
        lp_pick = picks[(condition, "Lp")]
        fmu_pick = picks[(condition, "fmu")]

        for row, (values, pick, ylabel, title) in enumerate((
            (lp, lp_pick, r"$L_{p,2-7\,kHz}$ (dBFS)", r"Band pressure level $L_p$"),
            (fmu / 1000.0, fmu_pick, r"$f_\mu$ (kHz)", r"First spectral moment $f_\mu$"),
        )):
            ax = axes[row, col]
            shade_flow_sides(ax, lp_pick)
            dx, dy = dense_profile(values)
            ax.plot(dx, dy, color=COLORS[condition], lw=2.0, alpha=0.72)
            x, y, order = sorted_profile(values)
            ax.plot(x, y, "o", color=COLORS[condition], ms=7, mec="white", mew=1.2, zorder=3)
            for xx, yy, mic in zip(x, y, order):
                ax.annotate(f"m{mic}", (xx, yy), xytext=(0, 8), textcoords="offset points",
                            ha="center", fontsize=8, color="#333")
            if row == 1 and abs(fmu_pick.x_mid - lp_pick.x_mid) > 0.01:
                ax.axvline(fmu_pick.x_mid, color="#542788", lw=1.1, ls=":",
                           label=r"$f_\mu$ max-slope midpoint")
                ax.legend(frameon=False, fontsize=8, loc="best")
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.2)
            ax.set_title(f"{condition} mph — {title}", loc="left", fontweight="bold")
            if row == 0:
                ax.text(0.02, 0.04,
                        f"max-slope bracket: m{lp_pick.leading_mic}–m{lp_pick.trailing_mic}\n"
                        f"x/c = {lp_pick.x_lo:.3f}–{lp_pick.x_hi:.3f}",
                        transform=ax.transAxes, va="bottom", fontsize=9,
                        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "none", "alpha": 0.82})

    for ax in axes[1]:
        ax.set_xlabel("x/c from leading edge (0 = leading, 1 = trailing)")
    fig.suptitle("Paper-style 2–7 kHz transition metrics on the MMSA wing array",
                 x=0.055, y=0.985, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.055, 0.94,
             "Blue = low-level/leading side; orange = unresolved transition bracket; red = high-level/trailing side. "
             "Shading is an acoustic classification, not an independently confirmed laminar/turbulent state.",
             ha="left", color="#333")
    handles = [plt.Rectangle((0, 0), 1, 1, color=LOW_COLOR, alpha=0.8),
               plt.Rectangle((0, 0), 1, 1, color=TRANS_COLOR, alpha=0.9),
               plt.Rectangle((0, 0), 1, 1, color=HIGH_COLOR, alpha=0.7)]
    fig.legend(handles, ["low-level side", "max-slope bracket", "high-level side"],
               frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 0.005))
    fig.tight_layout(rect=(0.04, 0.055, 1, 0.925))
    fig.savefig(output, dpi=240, facecolor="white")
    if output.suffix.lower() == ".png":
        fig.savefig(output.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def plot_spatial_clean(metrics: dict[str, TakeMetrics], output: Path) -> None:
    """Presentation version of the spatial metrics without transition picks.

    This intentionally omits all low/transition/high classification shading,
    maximum-slope brackets, bracket midpoints, and derivative annotations.  The
    markers remain the eight measured microphone values; the PCHIP curves are
    retained only as visual guides between those measurements.
    """
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=True)

    for col, condition in enumerate(("30", "60")):
        take = metrics[condition]
        lp = np.median(take.lp_dbfs, axis=0)
        fmu = np.median(take.fmu_hz, axis=0)

        for row, (values, ylabel, title) in enumerate((
            (lp, r"$L_{p,2-7\,kHz}$ (dBFS)", r"Band level $L_p$"),
            (fmu / 1000.0, r"$f_\mu$ (kHz)", r"First spectral moment $f_\mu$"),
        )):
            ax = axes[row, col]
            dense_x, dense_y = dense_profile(values)
            ax.plot(dense_x, dense_y, color=COLORS[condition], lw=2.4, alpha=0.76)
            x, y, order = sorted_profile(values)
            ax.plot(x, y, "o", color=COLORS[condition], ms=8, mec="white", mew=1.3, zorder=3)
            for xx, yy, mic in zip(x, y, order):
                ax.annotate(
                    f"m{mic}",
                    (xx, yy),
                    xytext=(0, 8),
                    textcoords="offset points",
                    ha="center",
                    fontsize=9,
                    color="#333333",
                )
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.2)
            ax.set_title(f"{condition} mph - {title}", loc="left", fontweight="bold")

    for ax in axes[1]:
        ax.set_xlabel("x/c from leading edge (0 = leading, 1 = trailing)")
    fig.suptitle(
        "2-7 kHz pressure-spectrum metrics on the MMSA wing array",
        x=0.055,
        y=0.985,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.055,
        0.945,
        "Dots are measured microphone values; curves are shape-preserving interpolation for visualization only.",
        ha="left",
        color="#333333",
    )
    fig.tight_layout(rect=(0.04, 0.04, 1, 0.925))
    fig.savefig(output, dpi=240, facecolor="white")
    if output.suffix.lower() == ".png":
        fig.savefig(output.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def plot_derivatives(metrics: dict[str, TakeMetrics], picks: dict[tuple[str, str], Pick], output: Path) -> None:
    """Show the finite spatial derivatives that determine each bracket."""
    plt.rcParams.update({"font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 8.5), sharex=True)
    for col, condition in enumerate(("30", "60")):
        take = metrics[condition]
        for row, (metric, values, ylabel) in enumerate((
            ("Lp", np.median(take.lp_dbfs, axis=0), r"$dL_p/d(x/c)$ (dB per x/c)"),
            ("fmu", np.median(take.fmu_hz, axis=0) / 1000.0, r"$df_\mu/d(x/c)$ (kHz per x/c)"),
        )):
            ax = axes[row, col]
            x, y, order = sorted_profile(values)
            mids = 0.5 * (x[:-1] + x[1:])
            slopes = np.diff(y) / np.diff(x)
            maximum = int(np.argmax(slopes))
            colors = [COLORS[condition] if i == maximum else "#bac7d5" for i in range(len(slopes))]
            ax.bar(mids, slopes, width=np.diff(x) * 0.72, color=colors, edgecolor="white")
            ax.axhline(0, color="#777", lw=0.8)
            pick = picks[(condition, metric)]
            ax.axvline(pick.x_mid, color="#8c510a", lw=1.3, ls="--")
            ax.annotate(
                f"m{order[maximum]}–m{order[maximum + 1]}",
                (mids[maximum], slopes[maximum]),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
            )
            ax.set_ylabel(ylabel)
            ax.grid(axis="y", alpha=0.2)
            ax.margins(y=0.16)
            name = r"$L_p$" if metric == "Lp" else r"$f_\mu$"
            ax.set_title(f"{condition} mph — adjacent slopes of {name}", loc="left", fontweight="bold")
            ax.text(0.02, 0.04,
                    f"selected interval: m{pick.leading_mic}–m{pick.trailing_mic}\n"
                    f"x/c = {pick.x_lo:.3f}–{pick.x_hi:.3f}",
                    transform=ax.transAxes, va="bottom", fontsize=9,
                    bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "none", "alpha": 0.85})
    for ax in axes[1]:
        ax.set_xlabel("midpoint x/c from leading edge")
    fig.suptitle("Paper criterion applied to MMSA: largest positive chordwise derivative",
                 x=0.055, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.055, 0.925,
             "Bars are measured finite differences between adjacent microphones. The highlighted bar is the reported bracket; "
             "interpolation is not used to claim sub-spacing resolution.", color="#333")
    fig.tight_layout(rect=(0.04, 0.04, 1, 0.9))
    fig.savefig(output, dpi=240, facecolor="white")
    if output.suffix.lower() == ".png":
        fig.savefig(output.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def ramp_track(lp_dbfs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return edge midpoint, adjacent dB step, and edge index for every time block."""
    x, _, order = sorted_profile(lp_dbfs[0])
    y = lp_dbfs[:, order]
    differences = np.diff(y, axis=1)
    slopes = differences / np.diff(x)[None, :]
    indices = np.argmax(slopes, axis=1)
    rows = np.arange(len(indices))
    steps = differences[rows, indices]
    mids = (x[indices] + x[indices + 1]) / 2.0
    mids = np.where(steps >= 6.0, mids, np.nan)
    return mids, steps, indices


def interpolate_space(values: np.ndarray, dense_x: np.ndarray) -> np.ndarray:
    x, _, order = sorted_profile(values[0])
    return np.asarray([PchipInterpolator(x, row[order])(dense_x) for row in values])


def plot_ramp_map(ramp: TakeMetrics, output: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dense_x = np.linspace(MIC_XC.min(), MIC_XC.max(), 160)
    lp_map = interpolate_space(ramp.lp_dbfs, dense_x)
    fmu_map = interpolate_space(ramp.fmu_hz / 1000.0, dense_x)
    track, steps, edge_indices = ramp_track(ramp.lp_dbfs)

    plt.rcParams.update({"font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.2), sharex=True, sharey=True)
    quantities = ((lp_map, r"$L_{p,2-7\,kHz}$ (dBFS)", "magma"),
                  (fmu_map, r"$f_\mu$ (kHz)", "viridis"))
    for ax, (z, label, cmap) in zip(axes, quantities):
        lo, hi = np.nanpercentile(z, [2, 98])
        image = ax.imshow(z.T, origin="lower", aspect="auto", cmap=cmap, vmin=lo, vmax=hi,
                          extent=(ramp.times_s[0] - BLOCK_SECONDS / 2,
                                  ramp.times_s[-1] + BLOCK_SECONDS / 2,
                                  dense_x[0], dense_x[-1]))
        valid = np.isfinite(track)
        ax.plot(ramp.times_s[valid], track[valid], color="white", lw=1.0, alpha=0.9,
                label=r"max $dL_p/dx$ bracket midpoint (step ≥ 6 dB)")
        ax.scatter(ramp.times_s[valid], track[valid], color="white", s=8, alpha=0.7)
        for mic, xc in enumerate(MIC_XC):
            ax.axhline(xc, color="white", lw=0.35, alpha=0.28)
            ax.text(ramp.times_s[-1] + 4, xc, f"m{mic}", va="center", fontsize=8, clip_on=False)
        fig.colorbar(image, ax=ax, pad=0.02, label=label)
        ax.set_xlabel("Time in take 0012 (s); tunnel-speed timing was not recorded")
        ax.legend(frameon=False, fontsize=8, loc="lower left", labelcolor="white")
    axes[0].set_ylabel("x/c from leading edge")
    axes[0].set_title(r"30–60 mph ramp: $L_p$", loc="left", fontweight="bold")
    axes[1].set_title(r"30–60 mph ramp: $f_\mu$", loc="left", fontweight="bold")
    fig.suptitle("Paper-style time–chord maps for the speed ramp",
                 x=0.055, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.055, 0.925,
             "Spatial interpolation is for visualization only; the thin horizontal lines show the eight actual microphone positions.",
             color="#333")
    fig.tight_layout(rect=(0.04, 0.03, 0.98, 0.91))
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return track, steps, edge_indices


def plot_before_after(metrics: dict[str, TakeMetrics], picks: dict[tuple[str, str], Pick], output: Path) -> None:
    plt.rcParams.update({"font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 6.2), sharex=True, sharey=True)
    for ax, condition in zip(axes, ("30", "60")):
        take = metrics[condition]
        pick = picks[(condition, "Lp")]
        low, high = pick.leading_mic, pick.trailing_mic
        lp = np.median(take.lp_dbfs, axis=0)
        fmu = np.median(take.fmu_hz, axis=0)
        clip = np.mean(take.clipped_percent, axis=0)
        mask = (take.frequency_hz >= 100) & (take.frequency_hz <= 20_000)
        for mic, name, color in ((low, "leading / low-level side", "#2f6db5"),
                                 (high, "trailing / high-level side", "#d55e00")):
            spectrum = 10.0 * np.log10(np.maximum(take.median_psd[:, mic], 1e-30))
            ax.semilogx(take.frequency_hz[mask], spectrum[mask], color=color, lw=2,
                        label=f"m{mic}: {name}")
            ax.axvline(fmu[mic], color=color, lw=1.0, ls=":")
        ax.axvspan(*BAND, color=TRANS_COLOR, alpha=0.35, lw=0)
        ax.set_title(f"{condition} mph: m{low} before vs m{high} after the break",
                     loc="left", fontweight="bold")
        ax.set_xlabel("Frequency (Hz)")
        ax.grid(alpha=0.2, which="both")
        ax.legend(frameon=False, loc="lower left", fontsize=9)
        ax.text(0.98, 0.97,
                f"2–7 kHz ΔLp = {lp[high] - lp[low]:.1f} dB\n"
                f"Δfμ = {(fmu[high] - fmu[low]) / 1000:.2f} kHz\n"
                f"clipping: m{low} {clip[low]:.3f}%, m{high} {clip[high]:.3f}%",
                transform=ax.transAxes, ha="right", va="top", fontsize=9,
                bbox={"boxstyle": "round,pad=0.35", "fc": "white", "ec": "#bbb", "alpha": 0.9})
    axes[0].set_ylabel(r"Median PSD (dBFS$^2$/Hz)")
    fig.suptitle("Spectra immediately before and after the spatial level break",
                 x=0.055, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.055, 0.915,
             "Dotted lines mark each spectrum's first moment within the shaded 2–7 kHz band. "
             "The 60 mph high-level spectrum is clipping-limited.", color="#333")
    fig.tight_layout(rect=(0.04, 0.04, 1, 0.89))
    fig.savefig(output, dpi=160)
    plt.close(fig)


def write_profiles(path: Path, metrics: dict[str, TakeMetrics]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["condition", "mic", "x_over_c_from_leading_edge",
                         "lp_2_7khz_median_dbfs", "lp_p10_dbfs", "lp_p90_dbfs",
                         "fmu_median_hz", "fmu_p10_hz", "fmu_p90_hz", "clipped_percent"])
        for condition in ("off", "30", "60"):
            take = metrics[condition]
            for mic in range(CHANNELS):
                writer.writerow([
                    condition, mic, f"{MIC_XC[mic]:.4f}",
                    f"{np.median(take.lp_dbfs[:, mic]):.4f}",
                    f"{np.percentile(take.lp_dbfs[:, mic], 10):.4f}",
                    f"{np.percentile(take.lp_dbfs[:, mic], 90):.4f}",
                    f"{np.median(take.fmu_hz[:, mic]):.3f}",
                    f"{np.percentile(take.fmu_hz[:, mic], 10):.3f}",
                    f"{np.percentile(take.fmu_hz[:, mic], 90):.3f}",
                    f"{np.mean(take.clipped_percent[:, mic]):.6f}",
                ])


def write_picks(path: Path, picks: dict[tuple[str, str], Pick]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["condition_mph", "metric", "leading_side_mic", "trailing_side_mic",
                         "x_over_c_lo", "x_over_c_hi", "bracket_midpoint", "adjacent_change", "slope_per_x_over_c"])
        for condition in ("30", "60"):
            for metric in ("Lp", "fmu"):
                p = picks[(condition, metric)]
                writer.writerow([condition, metric, p.leading_mic, p.trailing_mic,
                                 f"{p.x_lo:.4f}", f"{p.x_hi:.4f}", f"{p.x_mid:.4f}",
                                 f"{p.delta:.4f}", f"{p.slope:.4f}"])


def write_ramp(path: Path, ramp: TakeMetrics, track: np.ndarray, steps: np.ndarray, edge_indices: np.ndarray) -> None:
    x_sorted, _, order = sorted_profile(ramp.lp_dbfs[0])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time_s", "mic", "x_over_c_from_leading_edge", "lp_2_7khz_dbfs",
                         "fmu_hz", "clipped_percent", "lp_edge_midpoint_x_over_c", "lp_edge_step_db",
                         "lp_edge_leading_mic", "lp_edge_trailing_mic"])
        for i, time_s in enumerate(ramp.times_s):
            edge = int(edge_indices[i])
            leading_mic = int(order[edge])
            trailing_mic = int(order[edge + 1])
            midpoint = "" if not np.isfinite(track[i]) else f"{track[i]:.4f}"
            for mic in range(CHANNELS):
                writer.writerow([f"{time_s:.3f}", mic, f"{MIC_XC[mic]:.4f}",
                                 f"{ramp.lp_dbfs[i, mic]:.4f}", f"{ramp.fmu_hz[i, mic]:.3f}",
                                 f"{ramp.clipped_percent[i, mic]:.6f}", midpoint, f"{steps[i]:.4f}",
                                 leading_mic, trailing_mic])


def first_sustained_forward_shift(ramp: TakeMetrics, track: np.ndarray, sustain_blocks: int = 3) -> float | None:
    target = (MIC_XC[3] + MIC_XC[2]) / 2.0
    match = np.isfinite(track) & (np.abs(track - target) < 0.02)
    if len(match) < sustain_blocks:
        return None
    run = np.convolve(match.astype(int), np.ones(sustain_blocks, dtype=int), mode="valid")
    hits = np.flatnonzero(run == sustain_blocks)
    return None if not len(hits) else float(ramp.times_s[hits[0]])


def write_report(path: Path, metrics: dict[str, TakeMetrics], picks: dict[tuple[str, str], Pick], shift_time: float | None) -> None:
    lines = [
        "# Ozcakmak paper metrics applied to the 2026-10-29 wing data",
        "",
        "## What was calculated",
        "",
        "The one-sided Welch PSD uses the paper's 2048-point Hann windows, 50% overlap, and 2-7 kHz integration band. "
        "Each plotted time sample is a two-second Welch average. `Lp` is reported in dBFS because the installed microphone/port transfer functions "
        "were not calibrated to pascals. `f_mu` is the PSD-weighted mean frequency within 2-7 kHz.",
        "",
        "The transition proxy is the adjacent microphone pair with the largest positive chordwise slope. The bracket, rather than the interpolation's "
        "visual midpoint, is the defensible spatial resolution.",
        "",
        "## Results",
        "",
    ]
    for condition in ("30", "60"):
        take = metrics[condition]
        lp = np.median(take.lp_dbfs, axis=0)
        fmu = np.median(take.fmu_hz, axis=0)
        clip = np.mean(take.clipped_percent, axis=0)
        pick = picks[(condition, "Lp")]
        moment_pick = picks[(condition, "fmu")]
        low, high = pick.leading_mic, pick.trailing_mic
        lines += [
            f"- **{condition} mph:** maximum `Lp` slope lies between mic{low} and mic{high}, "
            f"`x/c = {pick.x_lo:.3f}-{pick.x_hi:.3f}` (midpoint {pick.x_mid:.3f}). "
            f"Across that pair, `Lp` rises {lp[high] - lp[low]:.1f} dB and `f_mu` changes "
            f"{(fmu[high] - fmu[low]) / 1000:.2f} kHz. Clipping is {clip[low]:.3f}%/"
            f"{clip[high]:.3f}% on the two sides.",
            f"  The maximum `f_mu` slope is between mic{moment_pick.leading_mic} and mic{moment_pick.trailing_mic}, "
            f"`x/c = {moment_pick.x_lo:.3f}-{moment_pick.x_hi:.3f}`, with a rise of {moment_pick.delta / 1000:.2f} kHz.",
        ]
    lines += [
        "",
        "At 30 mph the `f_mu` location is one microphone interval ahead of the `Lp` location: the spectral centroid rises across mic3-mic2, "
        "while total 2-7 kHz energy makes its large jump across mic2-mic1. This is consistent with mic2 being in an earlier spectral-change/transition "
        "stage before the high-energy state at mic1, but it needs repeat runs and port-response calibration before being treated as an aerodynamic fact.",
    ]
    lp30 = np.median(metrics["30"].lp_dbfs, axis=0)
    low_side30 = float(np.median(lp30[[2, 3, 4, 5, 6, 7]]))
    lp30_pick = picks[("30", "Lp")]
    fmu30_pick = picks[("30", "fmu")]
    candidate_lo = min(lp30_pick.x_lo, fmu30_pick.x_lo)
    candidate_hi = max(lp30_pick.x_hi, fmu30_pick.x_hi)
    candidate_width = candidate_hi - candidate_lo
    lp60_pick = picks[("60", "Lp")]
    lines += [
        "",
        f"The 30 mph `Lp` profile also has the paper's expected peak-and-settle shape: mic1 is the maximum, then the farther-downstream mic0 "
        f"drops {lp30[1] - lp30[0]:.1f} dB while remaining {lp30[0] - low_side30:.1f} dB above the leading-side median. If the `f_mu` rise is "
        f"treated as transition onset and the `Lp` rise/peak as its later stage, the candidate zone spans approximately "
        f"`x/c = {candidate_lo:.3f}-{candidate_hi:.3f}` (`{candidate_width:.3f}c`). That matches the paper's common 15-20% chord "
        "transition length, but this interpretation is provisional.",
    ]
    if shift_time is not None:
        lines += [
            f"- In the 30-60 mph ramp, the maximum-`Lp` bracket first remains at the mic3-mic2 interval for at least "
            f"{3 * BLOCK_SECONDS:.0f} s beginning near **{shift_time:.1f} s**. Tunnel speed was not synchronized, so this cannot be converted reliably to mph.",
        ]
    lines += [
        "",
        "The 60 mph flow-visualization line previously measured at aft-edge coordinate `x/c = 0.42-0.48` converts to conventional "
        f"leading-edge coordinate `x/c = 0.52-0.58`, overlapping the 60 mph mic3-mic2 acoustic bracket "
        f"(`{lp60_pick.x_lo:.3f}-{lp60_pick.x_hi:.3f}`).",
        "",
        "## Interpretation limits",
        "",
        "- These are paper-style **transition proxies**, not proof of laminar and turbulent states. There is one run per steady speed and no independent hot-film/IR/oil-flow truth measurement.",
        "- The 30 mph result is the cleaner quantitative case. At 60 mph, mic0-mic2 clip; clipping raises high-frequency spectral content and can bias both `Lp` and `f_mu`.",
        f"- The eight microphones cover only `x/c = {np.min(MIC_XC):.3f}-{np.max(MIC_XC):.3f}`. A transition zone narrower than one microphone spacing is unresolved; interpolation does not add physical resolution.",
        "- `f_mu` rejects scalar sensitivity mismatch but not microphone/port frequency-response mismatch. An installed-port acoustic calibration is still needed.",
        "- Absolute values cannot be compared with the paper's dB SPL table until pressure calibration is available.",
        "",
        "## Plot guide",
        "",
        "- `paper_metrics_spatial.png`: closest equivalent to the paper's chordwise `Lp` and `f_mu` plots.",
        "- `paper_metric_derivatives.png`: the measured adjacent slopes used to select each transition bracket.",
        "- `paper_metrics_ramp_map.png`: equivalent to a time/chord spectrogram, with the `Lp` max-slope bracket tracked through the ramp.",
        "- `paper_metrics_before_after_psd.png`: spectra on the immediately leading and trailing sides of the measured break.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    metrics = {key: analyse_take(args.session, key) for key in ("off", "30", "ramp", "60")}
    picks: dict[tuple[str, str], Pick] = {}
    for condition in ("30", "60"):
        take = metrics[condition]
        picks[(condition, "Lp")] = transition_pick(condition, "Lp", np.median(take.lp_dbfs, axis=0))
        picks[(condition, "fmu")] = transition_pick(condition, "fmu", np.median(take.fmu_hz, axis=0))

    plot_spatial(metrics, picks, args.output / "paper_metrics_spatial.png")
    plot_derivatives(metrics, picks, args.output / "paper_metric_derivatives.png")
    track, steps, edge_indices = plot_ramp_map(metrics["ramp"], args.output / "paper_metrics_ramp_map.png")
    plot_before_after(metrics, picks, args.output / "paper_metrics_before_after_psd.png")
    write_profiles(args.output / "paper_transition_profiles.csv", metrics)
    write_picks(args.output / "paper_transition_picks.csv", picks)
    write_ramp(args.output / "paper_ramp_metrics.csv", metrics["ramp"], track, steps, edge_indices)
    shift_time = first_sustained_forward_shift(metrics["ramp"], track)
    write_report(args.output / "PAPER_METHODS.md", metrics, picks, shift_time)

    for condition in ("30", "60"):
        p = picks[(condition, "Lp")]
        print(f"{condition} mph Lp bracket: mic{p.leading_mic}-mic{p.trailing_mic}, "
              f"x/c {p.x_lo:.3f}-{p.x_hi:.3f}, delta {p.delta:.1f} dB")
        q = picks[(condition, "fmu")]
        print(f"{condition} mph fmu bracket: mic{q.leading_mic}-mic{q.trailing_mic}, "
              f"x/c {q.x_lo:.3f}-{q.x_hi:.3f}, delta {q.delta / 1000:.2f} kHz")
    if shift_time is not None:
        print(f"sustained ramp shift to mic3-mic2 bracket: {shift_time:.1f} s")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
