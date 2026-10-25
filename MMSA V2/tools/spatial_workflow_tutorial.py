"""Build the MMSA spatial signal-processing workflow one understandable stage at a time.

Stage 1:
    Read an eight-channel WAV file and understand its sample layout.

Stage 2 (implemented here):
    Select one microphone and plot a short waveform against time.

Stage 3 (implemented here):
    Divide all microphones into short, overlapping time windows.

Stage 4 (implemented here):
    Measure band-limited energy and draw the microphone-row heatmap.

Stage 5 (implemented here for one selected window):
    Estimate when the sound reached each microphone using GCC-PHAT.

Planned later stages:
    6. Fit those delays to a physical source-location model.

Run from the repository root:
    python "MMSA V2/tools/spatial_workflow_tutorial.py" "MMSA V2/data/MMSA8_0084.wav"

Choose a microphone and a 20 ms section beginning at 4.5 seconds:
    python "MMSA V2/tools/spatial_workflow_tutorial.py" "MMSA V2/data/MMSA8_0084.wav" --mic 0 --start-s 4.5 --duration-s 0.02

Stage 1 uses Python's standard-library ``wave`` module and NumPy. Stage 2 uses
Matplotlib to draw the waveform. Stages 3–4 use NumPy to organize and analyze
the samples.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import wave

import matplotlib.pyplot as plt
import numpy as np


EXPECTED_CHANNELS = 8
EXPECTED_SAMPLE_WIDTH_BYTES = 2  # 2 bytes = 16 bits per sample
SPEED_OF_SOUND_MM_S = 343_000.0
GCC_INTERPOLATION = 8


def load_mmsa_wav(path: Path) -> tuple[int, np.ndarray]:
    """Read an uncompressed, 16-bit, eight-channel MMSA WAV file.

    A WAV stores the samples interleaved in time:

        frame 0: mic0, mic1, mic2, ... mic7
        frame 1: mic0, mic1, mic2, ... mic7
        frame 2: mic0, mic1, mic2, ... mic7

    ``np.frombuffer`` first sees that as one long list. ``reshape`` turns the
    list into a table whose rows are time samples and columns are microphones.
    """

    with wave.open(str(path), "rb") as wav_file:
        channel_count = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        compression = wav_file.getcomptype()

        if compression != "NONE":
            raise ValueError(f"Expected uncompressed PCM, found {compression!r}.")
        if channel_count != EXPECTED_CHANNELS:
            raise ValueError(f"Expected 8 channels, found {channel_count}.")
        if sample_width != EXPECTED_SAMPLE_WIDTH_BYTES:
            raise ValueError(
                f"Expected 16-bit samples (2 bytes), found {sample_width} bytes."
            )

        raw_bytes = wav_file.readframes(frame_count)

    # "<i2" means little-endian ("<"), signed integer ("i"), 2 bytes ("2").
    interleaved_samples = np.frombuffer(raw_bytes, dtype="<i2")
    samples_by_mic = interleaved_samples.reshape(frame_count, channel_count)

    return sample_rate, samples_by_mic


def print_summary(path: Path, sample_rate: int, samples: np.ndarray) -> None:
    """Print enough information to verify that the WAV was decoded correctly."""

    frame_count, channel_count = samples.shape
    duration_s = frame_count / sample_rate

    print(f"File: {path}")
    print(f"Sample rate: {sample_rate:,} frames/second")
    print(f"Channels: {channel_count}")
    print(f"Frames: {frame_count:,}")
    print(f"Duration: {duration_s:.3f} seconds")
    print(f"Array shape: {samples.shape} = (time frames, microphones)")

    print("\nFirst five frames (columns are mic0 through mic7):")
    print(samples[:5])

    # Convert before squaring. Squaring int16 values directly can overflow.
    samples_float = samples.astype(np.float64)
    rms = np.sqrt(np.mean(samples_float**2, axis=0))

    print("\nBasic value checks:")
    print(" mic      minimum      maximum         mean          RMS")
    for mic in range(channel_count):
        channel = samples[:, mic]
        print(
            f" mic{mic}  "
            f"{channel.min():11d}  "
            f"{channel.max():11d}  "
            f"{channel.mean():11.2f}  "
            f"{rms[mic]:11.2f}"
        )


def plot_one_microphone(
    wav_path: Path,
    sample_rate: int,
    samples: np.ndarray,
    mic: int,
    start_s: float,
    duration_s: float,
    output_path: Path | None,
) -> None:
    """Plot one microphone over a selected time interval.

    Array indexing uses integer frame numbers, so the requested times are
    converted into frame indices:

        frame number = time in seconds * frames per second

    The selected microphone is one column of the two-dimensional sample array.
    """

    if not 0 <= mic < samples.shape[1]:
        raise ValueError(f"Microphone must be 0 through {samples.shape[1] - 1}.")
    if start_s < 0:
        raise ValueError("Start time cannot be negative.")
    if duration_s <= 0:
        raise ValueError("Duration must be greater than zero.")

    start_frame = round(start_s * sample_rate)
    end_frame = min(samples.shape[0], start_frame + round(duration_s * sample_rate))

    if start_frame >= samples.shape[0]:
        raise ValueError(
            f"Start time {start_s:g} s is beyond the {samples.shape[0] / sample_rate:.3f} s recording."
        )

    # ``samples[:, mic]`` means every time frame from one microphone column.
    mic_samples = samples[:, mic]
    selected_samples = mic_samples[start_frame:end_frame]

    # Every sample is separated by 1 / sample_rate seconds. Dividing the frame
    # numbers by the sample rate gives the horizontal time axis in seconds.
    frame_numbers = np.arange(start_frame, end_frame)
    time_s = frame_numbers / sample_rate

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(time_s, selected_samples, linewidth=0.8)
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.5)
    ax.set(
        title=f"{wav_path.name}: mic{mic} waveform",
        xlabel="Time (seconds)",
        ylabel="Raw 16-bit PCM value",
    )
    ax.grid(True, alpha=0.25)
    fig.tight_layout()

    print("\nStage 2 selection:")
    print(f"Microphone column: mic{mic}")
    print(f"Frame range: {start_frame:,} through {end_frame - 1:,}")
    print(f"Samples plotted: {len(selected_samples):,}")
    print(f"Time range: {time_s[0]:.6f} through {time_s[-1]:.6f} seconds")

    if output_path is not None:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=160)
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)


def divide_into_windows(
    samples: np.ndarray,
    sample_rate: int,
    window_ms: float,
    hop_ms: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Copy the recording into overlapping analysis windows.

    The returned array has three dimensions:

        windows[window number, frame within that window, microphone]

    A 100 ms window at 48 kHz contains 4,800 frames. If a new window starts
    every 50 ms, adjacent windows overlap by 2,400 frames, or 50 percent.
    """

    window_frames = round(window_ms / 1000 * sample_rate)
    hop_frames = round(hop_ms / 1000 * sample_rate)

    if window_frames <= 0:
        raise ValueError("Window length must be greater than zero.")
    if hop_frames <= 0:
        raise ValueError("Hop length must be greater than zero.")
    if window_frames > samples.shape[0]:
        raise ValueError("Window length is longer than the recording.")

    # These are the frame numbers where windows 0, 1, 2, ... begin.
    start_frames = np.arange(
        0,
        samples.shape[0] - window_frames + 1,
        hop_frames,
    )

    # Allocate the result, then copy the same frame range from all 8 mics into
    # each window. This explicit loop is intentionally easier to inspect than
    # a more advanced NumPy stride-based view.
    windows = np.empty(
        (len(start_frames), window_frames, samples.shape[1]),
        dtype=samples.dtype,
    )
    for window_number, start_frame in enumerate(start_frames):
        end_frame = start_frame + window_frames
        windows[window_number] = samples[start_frame:end_frame, :]

    return start_frames, windows


def print_window_summary(
    start_frames: np.ndarray,
    windows: np.ndarray,
    sample_rate: int,
) -> None:
    """Explain the dimensions and timing of the window array."""

    window_frames = windows.shape[1]
    hop_frames = start_frames[1] - start_frames[0] if len(start_frames) > 1 else window_frames
    overlap_frames = max(0, window_frames - hop_frames)
    overlap_percent = 100 * overlap_frames / window_frames
    center_times_s = (start_frames + window_frames / 2) / sample_rate

    print("\nStage 3 windows:")
    print(f"Window length: {window_frames:,} frames = {window_frames / sample_rate * 1000:.1f} ms")
    print(f"Hop length: {hop_frames:,} frames = {hop_frames / sample_rate * 1000:.1f} ms")
    print(f"Overlap: {overlap_frames:,} frames = {overlap_percent:.1f}%")
    print(f"Number of complete windows: {len(windows):,}")
    print(f"Window array shape: {windows.shape} = (windows, frames per window, microphones)")
    print(f"First five window-center times: {center_times_s[:5]} seconds")

    if len(windows) > 1:
        first_end = start_frames[0] + window_frames - 1
        second_end = start_frames[1] + window_frames - 1
        print(f"Window 0 uses original frames {start_frames[0]:,} through {first_end:,}")
        print(f"Window 1 uses original frames {start_frames[1]:,} through {second_end:,}")


def measure_band_energy(
    windows: np.ndarray,
    sample_rate: int,
    low_hz: float,
    high_hz: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Measure each microphone's energy in one frequency band per window.

    Returns:
        frequencies_hz: frequency represented by each FFT bin
        band_power:      shape (windows, microphones), linear power units
        db_above_floor:  shape (windows, microphones), relative decibels
    """

    if not 0 <= low_hz < high_hz <= sample_rate / 2:
        raise ValueError(
            f"Band must satisfy 0 <= low < high <= {sample_rate / 2:g} Hz."
        )

    # A finite chunk ends abruptly at its boundaries. Multiplying by a Hann
    # taper smoothly reduces both ends toward zero and reduces FFT leakage.
    window_frames = windows.shape[1]
    hann_taper = np.hanning(window_frames)
    frequencies_hz = np.fft.rfftfreq(window_frames, d=1 / sample_rate)
    in_band = (frequencies_hz >= low_hz) & (frequencies_hz <= high_hz)
    band_power = np.empty((windows.shape[0], windows.shape[2]), dtype=np.float64)

    # Process one 100 ms window at a time so every intermediate array is only
    # (frames per window, microphones), rather than the entire recording.
    for window_number, window in enumerate(windows):
        # Floating point is needed for averaging, tapering, and the FFT.
        working = window.astype(np.float64)

        # Remove each microphone's average value within this window. This
        # removes DC offset but keeps the changing sound waveform around it.
        working = working - working.mean(axis=0, keepdims=True)
        tapered = working * hann_taper[:, None]

        # The real FFT converts the frame axis from amplitude-versus-time into
        # complex amplitude-versus-frequency. The mic axis stays intact.
        spectrum = np.fft.rfft(tapered, axis=0)

        # Keep bins inside the requested band and sum amplitude squared.
        # Squared magnitude is proportional to signal power.
        band_power[window_number] = (
            (np.abs(spectrum[in_band, :]) ** 2).sum(axis=0) / window_frames
        )

    # Estimate each mic's quiet baseline independently as its 10th-percentile
    # power across the recording. This is relative level, not calibrated SPL.
    floor_power = np.percentile(band_power, 10, axis=0)
    safe_power = np.maximum(band_power, 1e-30)
    safe_floor = np.maximum(floor_power, 1e-30)
    db_above_floor = 10 * np.log10(safe_power / safe_floor)

    return frequencies_hz, band_power, db_above_floor


def print_energy_summary(
    frequencies_hz: np.ndarray,
    band_power: np.ndarray,
    db_above_floor: np.ndarray,
    low_hz: float,
    high_hz: float,
) -> None:
    """Print the dimensions and interpretation of the Stage 4 result."""

    frequency_spacing = frequencies_hz[1] - frequencies_hz[0]
    print("\nStage 4 band energy:")
    print(f"FFT-bin spacing: {frequency_spacing:.1f} Hz")
    print(f"Selected band: {low_hz:g} through {high_hz:g} Hz")
    print(f"Band-power shape: {band_power.shape} = (windows, microphones)")
    print(f"Relative-level shape: {db_above_floor.shape} = (windows, microphones)")
    print("First window, dB above each microphone's floor:")
    print(np.round(db_above_floor[0], 2))


def plot_energy_heatmap(
    wav_path: Path,
    start_frames: np.ndarray,
    windows: np.ndarray,
    sample_rate: int,
    db_above_floor: np.ndarray,
    low_hz: float,
    high_hz: float,
    output_path: Path | None,
) -> None:
    """Draw one row per microphone and one column per analysis window."""

    window_frames = windows.shape[1]
    center_times_s = (start_frames + window_frames / 2) / sample_rate
    half_hop_s = (center_times_s[1] - center_times_s[0]) / 2 if len(center_times_s) > 1 else 0
    window_ms = window_frames / sample_rate * 1000
    hop_ms = half_hop_s * 2 * 1000
    left_s = center_times_s[0] - half_hop_s
    right_s = center_times_s[-1] + half_hop_s

    fig, ax = plt.subplots(figsize=(11, 4.8))
    image = ax.imshow(
        db_above_floor.T,
        origin="lower",
        aspect="auto",
        extent=(left_s, right_s, -0.5, db_above_floor.shape[1] - 0.5),
        cmap="Blues",
        vmin=0,
        vmax=40,
        interpolation="nearest",
    )
    ax.set(
        title=(
            f"{wav_path.name}: {window_ms:g} ms window / {hop_ms:g} ms hop — "
            "level above each microphone's quiet baseline"
        ),
        xlabel="Time (seconds)",
        ylabel="Microphone",
        yticks=np.arange(db_above_floor.shape[1]),
        yticklabels=[f"mic{mic}" for mic in range(db_above_floor.shape[1])],
    )
    colorbar = fig.colorbar(image, ax=ax)
    colorbar.set_label(f"Power in {low_hz / 1000:g}–{high_hz / 1000:g} kHz band (dB above floor)")
    fig.tight_layout()

    if output_path is not None:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=160)
        print(f"Heatmap saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)


def measure_gcc_phat_delays(
    window: np.ndarray,
    sample_rate: int,
    reference_mic: int,
    low_hz: float,
    high_hz: float,
    mic_pitch_mm: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Estimate every mic's arrival delay relative to one reference mic.

    A positive delay means that microphone heard the sound after the reference.
    The returned correlations are included so we can plot and inspect the peaks
    instead of treating GCC-PHAT as a black box.
    """

    if mic_pitch_mm <= 0:
        raise ValueError("Microphone pitch must be greater than zero.")

    microphone_count = window.shape[1]
    array_span_mm = (microphone_count - 1) * mic_pitch_mm

    # The largest physically expected delay occurs between the two end mics.
    # Four extra raw samples provide a little tolerance around that limit.
    max_lag_samples = int(
        np.ceil(array_span_mm / SPEED_OF_SOUND_MM_S * sample_rate)
    ) + 4

    working = window.astype(np.float64)
    working = working - working.mean(axis=0, keepdims=True)

    # Zero-padding to twice the window length prevents the circular wraparound
    # of the FFT correlation from interfering with the short lags we inspect.
    fft_length = 2 * window.shape[0]
    spectrum = np.fft.rfft(working, n=fft_length, axis=0)
    frequencies_hz = np.fft.rfftfreq(fft_length, d=1 / sample_rate)

    # Cross-spectrum between every mic and the selected reference mic.
    reference_spectrum = spectrum[:, reference_mic : reference_mic + 1]
    cross_spectrum = spectrum * np.conj(reference_spectrum)

    # PHAT normalization discards magnitude and retains phase alignment. This
    # makes the peak depend less on one mic simply being louder than another.
    phat_spectrum = cross_spectrum / (np.abs(cross_spectrum) + 1e-12)
    in_band = (frequencies_hz >= low_hz) & (frequencies_hz <= high_hz)
    phat_spectrum[~in_band, :] = 0

    # A longer inverse FFT interpolates the correlation peak between original
    # 48 kHz sample positions. It does not create new acoustic information.
    interpolated_length = fft_length * GCC_INTERPOLATION
    circular_correlation = np.fft.irfft(
        phat_spectrum,
        n=interpolated_length,
        axis=0,
    )

    search_radius = max_lag_samples * GCC_INTERPOLATION
    correlations = np.concatenate(
        (
            circular_correlation[-search_radius:, :],
            circular_correlation[: search_radius + 1, :],
        ),
        axis=0,
    )
    lag_samples = np.arange(-search_radius, search_radius + 1) / GCC_INTERPOLATION

    peak_indices = np.argmax(correlations, axis=0)
    delay_samples = lag_samples[peak_indices]
    delays_s = delay_samples / sample_rate

    # This is a normalized peak-height confidence measure used later to reject
    # microphones whose waveforms do not correlate clearly with the reference.
    peak_values = correlations[peak_indices, np.arange(microphone_count)]
    strengths = peak_values * interpolated_length / (2 * in_band.sum())

    return delays_s, strengths, lag_samples, correlations


def print_delay_summary(
    window_number: int,
    center_time_s: float,
    sample_rate: int,
    reference_mic: int,
    delays_s: np.ndarray,
    strengths: np.ndarray,
) -> None:
    """Print the selected window's relative arrival-time measurements."""

    print("\nStage 5 GCC-PHAT delays:")
    print(f"Selected window: {window_number}, centered at {center_time_s:.3f} s")
    print(f"Reference: mic{reference_mic}, the loudest mic in this window")
    print("Positive delay means the mic heard the sound after the reference.")
    print(" mic    delay (samples)    delay (us)    path difference (mm)    peak strength")
    for mic, (delay_s, strength) in enumerate(zip(delays_s, strengths)):
        delay_samples = delay_s * sample_rate
        delay_us = delay_s * 1_000_000
        path_difference_mm = delay_s * SPEED_OF_SOUND_MM_S
        print(
            f" mic{mic}  {delay_samples:15.3f}  {delay_us:12.2f}  "
            f"{path_difference_mm:20.2f}  {strength:13.3f}"
        )


def plot_delay_correlations(
    wav_path: Path,
    window_number: int,
    center_time_s: float,
    sample_rate: int,
    reference_mic: int,
    lag_samples: np.ndarray,
    correlations: np.ndarray,
    output_path: Path | None,
) -> None:
    """Plot the eight GCC-PHAT curves whose peaks produce the delays."""

    lag_us = lag_samples / sample_rate * 1_000_000
    fig, axes = plt.subplots(4, 2, figsize=(11, 9), sharex=True)
    for mic, ax in enumerate(axes.flat):
        curve = correlations[:, mic]
        scale = np.max(np.abs(curve))
        normalized_curve = curve / scale if scale > 0 else curve
        peak_index = int(np.argmax(curve))
        ax.plot(lag_us, normalized_curve, linewidth=0.9)
        ax.axvline(lag_us[peak_index], color="tab:orange", linewidth=1.2)
        ax.axvline(0, color="black", linewidth=0.6, alpha=0.5)
        ax.set_title(f"mic{mic} vs mic{reference_mic}: peak {lag_us[peak_index]:.1f} us")
        ax.set_ylabel("Normalized correlation")
        ax.grid(True, alpha=0.25)

    axes[-1, 0].set_xlabel("Relative arrival delay (microseconds)")
    axes[-1, 1].set_xlabel("Relative arrival delay (microseconds)")
    fig.suptitle(
        f"{wav_path.name}: GCC-PHAT, window {window_number} at {center_time_s:.3f} s",
        fontsize=12,
    )
    fig.tight_layout()

    if output_path is not None:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=160)
        print(f"GCC-PHAT plot saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stages 1–5 of the MMSA spatial-processing tutorial."
    )
    parser.add_argument("wav", type=Path, help="Path to an eight-channel MMSA WAV file")
    parser.add_argument("--mic", type=int, default=0, help="Microphone column to plot (default: 0)")
    parser.add_argument("--start-s", type=float, default=0.0, help="Plot start time in seconds (default: 0)")
    parser.add_argument(
        "--duration-s", type=float, default=0.02, help="Amount of audio to plot in seconds (default: 0.02)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save the plot as an image instead of opening a window",
    )
    parser.add_argument(
        "--window-ms",
        type=float,
        default=100.0,
        help="Analysis-window length in milliseconds (default: 100)",
    )
    parser.add_argument(
        "--hop-ms",
        type=float,
        default=50.0,
        help="Distance between window starts in milliseconds (default: 50)",
    )
    parser.add_argument(
        "--band",
        type=float,
        nargs=2,
        default=[1000.0, 16000.0],
        metavar=("LOW_HZ", "HIGH_HZ"),
        help="Frequency band used for the heatmap (default: 1000 16000)",
    )
    parser.add_argument(
        "--heatmap-output",
        type=Path,
        help="Save the Stage 4 heatmap as an image instead of opening a window",
    )
    parser.add_argument(
        "--delay-time-s",
        type=float,
        default=6.0,
        help="Time whose nearest window is inspected with GCC-PHAT (default: 6.0)",
    )
    parser.add_argument(
        "--pitch-mm",
        type=float,
        default=39.5,
        help="Physical spacing between neighboring microphones (default: 39.5)",
    )
    parser.add_argument(
        "--delay-output",
        type=Path,
        help="Save the Stage 5 GCC-PHAT curves instead of opening a window",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wav_path = args.wav.resolve()

    if not wav_path.is_file():
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    sample_rate, samples = load_mmsa_wav(wav_path)
    print_summary(wav_path, sample_rate, samples)
    plot_one_microphone(
        wav_path=wav_path,
        sample_rate=sample_rate,
        samples=samples,
        mic=args.mic,
        start_s=args.start_s,
        duration_s=args.duration_s,
        output_path=args.output,
    )
    start_frames, windows = divide_into_windows(
        samples=samples,
        sample_rate=sample_rate,
        window_ms=args.window_ms,
        hop_ms=args.hop_ms,
    )
    print_window_summary(start_frames, windows, sample_rate)
    frequencies_hz, band_power, db_above_floor = measure_band_energy(
        windows=windows,
        sample_rate=sample_rate,
        low_hz=args.band[0],
        high_hz=args.band[1],
    )
    print_energy_summary(
        frequencies_hz=frequencies_hz,
        band_power=band_power,
        db_above_floor=db_above_floor,
        low_hz=args.band[0],
        high_hz=args.band[1],
    )
    plot_energy_heatmap(
        wav_path=wav_path,
        start_frames=start_frames,
        windows=windows,
        sample_rate=sample_rate,
        db_above_floor=db_above_floor,
        low_hz=args.band[0],
        high_hz=args.band[1],
        output_path=args.heatmap_output,
    )

    window_frames = windows.shape[1]
    center_times_s = (start_frames + window_frames / 2) / sample_rate
    if not center_times_s[0] <= args.delay_time_s <= center_times_s[-1]:
        raise ValueError(
            f"Delay-analysis time must be between {center_times_s[0]:.3f} "
            f"and {center_times_s[-1]:.3f} seconds."
        )
    delay_window = int(np.argmin(np.abs(center_times_s - args.delay_time_s)))
    reference_mic = int(np.argmax(band_power[delay_window]))
    delays_s, strengths, lag_samples, correlations = measure_gcc_phat_delays(
        window=windows[delay_window],
        sample_rate=sample_rate,
        reference_mic=reference_mic,
        low_hz=args.band[0],
        high_hz=args.band[1],
        mic_pitch_mm=args.pitch_mm,
    )
    print_delay_summary(
        window_number=delay_window,
        center_time_s=center_times_s[delay_window],
        sample_rate=sample_rate,
        reference_mic=reference_mic,
        delays_s=delays_s,
        strengths=strengths,
    )
    plot_delay_correlations(
        wav_path=wav_path,
        window_number=delay_window,
        center_time_s=center_times_s[delay_window],
        sample_rate=sample_rate,
        reference_mic=reference_mic,
        lag_samples=lag_samples,
        correlations=correlations,
        output_path=args.delay_output,
    )


if __name__ == "__main__":
    main()
