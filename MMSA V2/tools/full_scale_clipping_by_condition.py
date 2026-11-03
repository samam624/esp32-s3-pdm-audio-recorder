"""Plot full-scale clipping frequency and duration for floor and wing tests."""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
from matplotlib.patches import Rectangle
import numpy as np


FS = 48_000
CHANNELS = 8
READ_FRAMES = FS
POPFILTER_MICS = (4, 6)  # covered with pop-filter material for the whole floor sequence

GROUPS = [
    ("Floor | tunnel off", ["MMSA8_0003_Floor_0", "MMSA8_0004_Floor_0"]),
    ("Floor | 0–30 mph ramp", ["MMSA8_0005_Floor_0_30"]),
    ("Floor | steady 30 mph", ["MMSA8_0006_Floor_30"]),
    ("Floor | 30–60 mph ramp", ["MMSA8_0007_Floor_30_60"]),
    ("Floor | steady 60 mph", ["MMSA8_0008_Floor_60"]),
    ("Wing | tunnel off", ["MMSA8_0009_Wing_0"]),
    ("Wing | 0–30 mph ramp", ["MMSA8_0010_Wing_0_30"]),
    ("Wing | steady 30 mph", ["MMSA8_0011_Wing_30"]),
    ("Wing | 30–60 mph ramp", ["MMSA8_0012_Wing_30_60"]),
    ("Wing | steady 60 mph", ["MMSA8_0013_Wing_60"]),
]


def analyze_group(session: Path, folders: list[str]) -> list[dict[str, float]]:
    clipped_samples = np.zeros(CHANNELS, dtype=np.int64)
    clipping_events = np.zeros(CHANNELS, dtype=np.int64)
    sample_count = np.zeros(CHANNELS, dtype=np.int64)

    for folder in folders:
        paths = sorted((session / folder).glob("*.wav"))
        if not paths:
            raise FileNotFoundError(f"No WAV files found under {session / folder}")
        for path in paths:
            previous = np.zeros(CHANNELS, dtype=bool)
            with wave.open(str(path), "rb") as wav:
                if wav.getframerate() != FS or wav.getnchannels() != CHANNELS or wav.getsampwidth() != 2:
                    raise ValueError(f"Unexpected WAV format: {path}")
                while True:
                    raw_bytes = wav.readframes(READ_FRAMES)
                    if not raw_bytes:
                        break
                    raw = np.frombuffer(raw_bytes, dtype="<i2")
                    complete = len(raw) // CHANNELS
                    if complete == 0:
                        continue
                    raw = raw[: complete * CHANNELS].reshape(complete, CHANNELS)
                    clipped = (raw <= -32768) | (raw >= 32767)
                    clipped_samples += np.sum(clipped, axis=0)
                    sample_count += complete
                    clipping_events += clipped[0] & ~previous
                    if complete > 1:
                        clipping_events += np.sum(clipped[1:] & ~clipped[:-1], axis=0)
                    previous = clipped[-1]

    duration_s = sample_count / FS
    return [
        {
            "mic": float(mic),
            "duration_s": float(duration_s[mic]),
            "clipped_samples": float(clipped_samples[mic]),
            "clipped_time_s": float(clipped_samples[mic] / FS),
            "clipped_percent": float(100.0 * clipped_samples[mic] / max(sample_count[mic], 1)),
            "clipping_events": float(clipping_events[mic]),
            "events_per_s": float(clipping_events[mic] / max(duration_s[mic], 1e-12)),
        }
        for mic in range(CHANNELS)
    ]


def cell_text(value: float, kind: str) -> str:
    if value == 0:
        return "—"
    if kind == "events":
        return f"{value:.2f}" if value < 1 else f"{value:.1f}"
    if value < 0.001:
        return f"{value:.5f}%"
    if value < 0.1:
        return f"{value:.3f}%"
    return f"{value:.2f}%"


def text_color(norm, value: float) -> str:
    """Pick black or white text from the rendered cell's luminance."""
    if value == 0:
        return "#9a9a9a"
    r, g, b, _ = plt.get_cmap("magma")(float(norm(value)))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#111111" if luminance > 0.45 else "white"


def plot(rows: list[dict[str, float]], output: Path) -> None:
    labels = [label for label, _ in GROUPS]
    event_rate = np.zeros((len(GROUPS), CHANNELS))
    clipped_percent = np.zeros_like(event_rate)
    for row in rows:
        group = int(row["group_index"])
        mic = int(row["mic"])
        event_rate[group, mic] = row["events_per_s"]
        clipped_percent[group, mic] = row["clipped_percent"]

    event_max = max(1.0, float(np.max(event_rate)))
    percent_max = max(0.1, float(np.max(clipped_percent)))
    event_norm = SymLogNorm(linthresh=0.01, linscale=0.7, vmin=0, vmax=event_max)
    percent_norm = SymLogNorm(linthresh=0.001, linscale=0.7, vmin=0, vmax=percent_max)

    fig, axes = plt.subplots(2, 1, figsize=(15.5, 9.2))
    fig.subplots_adjust(left=0.19, right=0.89, top=0.84, bottom=0.10, hspace=0.34)
    fig.suptitle("Full-scale clipping by microphone and test condition", y=0.975, fontsize=20, fontweight="bold")
    fig.text(
        0.5,
        0.925,
        "Clipping is a raw 16-bit sample at −32768 or +32767; one event is a contiguous run of clipped samples",
        ha="center",
        fontsize=11.5,
        color="#444444",
    )

    event_image = axes[0].imshow(event_rate, aspect="auto", cmap="magma", norm=event_norm)
    percent_image = axes[1].imshow(clipped_percent, aspect="auto", cmap="magma", norm=percent_norm)
    titles = (
        "How often clipping starts: distinct full-scale events per second",
        "How much data is saturated: samples at full scale",
    )
    for axis, title in zip(axes, titles):
        axis.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=8)
        axis.set_xticks(np.arange(CHANNELS), [f"mic{mic}" for mic in range(CHANNELS)])
        axis.set_yticks(np.arange(len(labels)), labels)
        axis.tick_params(labelsize=10)
        axis.set_xticks(np.arange(-0.5, CHANNELS, 1), minor=True)
        axis.set_yticks(np.arange(-0.5, len(labels), 1), minor=True)
        axis.grid(which="minor", color="white", linewidth=1.4, alpha=0.72)
        axis.tick_params(which="minor", bottom=False, left=False)
        axis.axhline(4.5, color="white", lw=4.5)
        for mic in POPFILTER_MICS:
            axis.add_patch(
                Rectangle((mic - 0.5, -0.5), 1, 5, fill=False, edgecolor="#00b8d4", linewidth=3.2, zorder=5)
            )
            axis.text(
                mic,
                1.5,
                "POP FILTER\nMATERIAL",
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="#00e5ff",
                zorder=6,
            )

    for group in range(len(GROUPS)):
        for mic in range(CHANNELS):
            event = event_rate[group, mic]
            percent = clipped_percent[group, mic]
            axes[0].text(
                mic,
                group,
                cell_text(event, "events"),
                ha="center",
                va="center",
                fontsize=9.3,
                fontweight="bold",
                color=text_color(event_norm, event),
            )
            axes[1].text(
                mic,
                group,
                cell_text(percent, "percent"),
                ha="center",
                va="center",
                fontsize=9.0,
                fontweight="bold",
                color=text_color(percent_norm, percent),
            )

    fig.colorbar(event_image, ax=axes[0], label="Clipping events per second", pad=0.012)
    fig.colorbar(percent_image, ax=axes[1], label="Samples at full scale (%)", pad=0.012)
    fig.text(
        0.5,
        0.025,
        "Cyan boxes: floor mic4 and mic6 were covered with pop-filter material, which is why they never reached full scale.",
        ha="center",
        fontsize=9.8,
        color="#444444",
    )
    fig.savefig(output, dpi=220, facecolor="white")
    fig.savefig(output.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--reuse-csv", action="store_true", help="replot from the existing CSV")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = args.output_dir / "full_scale_clipping_by_condition.csv"
    rows: list[dict[str, float]] = []
    if args.reuse_csv and csv_path.is_file():
        labels = [label for label, _ in GROUPS]
        with csv_path.open(encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                rows.append({"group_index": float(labels.index(r["condition"])), "condition": r["condition"], **{k: float(v) for k, v in r.items() if k != "condition"}})
        plot(rows, args.output_dir / "full_scale_clipping_by_condition.png")
        return 0
    for group_index, (label, folders) in enumerate(GROUPS):
        print(f"analyzing {label}", flush=True)
        for summary in analyze_group(args.session, folders):
            rows.append({"group_index": float(group_index), "condition": label, **summary})

    csv_path = args.output_dir / "full_scale_clipping_by_condition.csv"
    fields = [
        "condition",
        "mic",
        "duration_s",
        "clipped_samples",
        "clipped_time_s",
        "clipped_percent",
        "clipping_events",
        "events_per_s",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})

    plot_path = args.output_dir / "full_scale_clipping_by_condition.png"
    plot(rows, plot_path)
    print(csv_path.resolve())
    print(plot_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
