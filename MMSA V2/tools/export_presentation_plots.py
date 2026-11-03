"""Export standalone, presentation-ready figures from the 60 mph overlay analysis.

The registered source photographs are not stored in this repository.  The three
photo panels are therefore cropped, without resampling, from the existing
``flow_array_overlay_60mph.png`` composition.  The two level charts are rebuilt
from the original WAV recordings using the same filtering, microphone
coordinates, and level calculation as ``overlay_flow_photos.py``.

The chart exports intentionally retain the green 60 mph fluorescent-line zone
and omit the orange mic2--mic3 gap shading used in the diagnostic composite.

Usage:
    python export_presentation_plots.py SESSION COMPOSITE OUTPUT_DIR
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageOps

import overlay_flow_photos as ov
import paper_transition_metrics as paper
import wing_broadband_psd as broadband_psd


# Rounded half-maximum interval and peak printed on the current registered
# composite.  These define the green physical-reference band on the clean plots.
FLOW_ZONE_XC = (0.41, 0.48)
FLOW_PEAK_XC = 0.44

# Normalized crop boxes (left, top, right, bottom) for the three top-row panels
# in the existing 16.5 x 11.5 inch, 150 dpi diagnostic composition.  Keeping the
# boxes normalized makes the export tolerate a uniformly rescaled composite.
PHOTO_CROPS = (
    ("01_60mph_flow_visualization", (0.046, 0.092, 0.334, 0.563)),
    ("03_60mph_flow_array_overlay", (0.696, 0.092, 0.984, 0.563)),
)

LEGACY_OUTPUTS = (
    "01_60mph_flow_visualization.png",
    "02_mmsa_array_rectified.png",
    "03_60mph_flow_array_overlay.png",
    "04_steady_60mph_levels_clean.png",
    "04_steady_60mph_levels_clean.svg",
    "05_4_8khz_30_vs_60mph_clean.png",
    "05_4_8khz_30_vs_60mph_clean.svg",
    "02_60mph_flow_visualization.png",
    "03_mmsa_array_rectified.png",
    "04_60mph_flow_array_overlay.png",
    "05_steady_60mph_levels_clean.png",
    "05_steady_60mph_levels_clean.svg",
    "06_4_8khz_30_vs_60mph_clean.png",
    "06_4_8khz_30_vs_60mph_clean.svg",
    "01_paper_metrics_2_7khz_clean.png",
    "01_paper_metrics_2_7khz_clean.svg",
    "02_paper_metric_spatial_derivatives.png",
    "02_paper_metric_spatial_derivatives.svg",
    "03_60mph_flow_visualization.png",
    "04_mmsa_array_rectified.png",
    "05_60mph_flow_array_overlay.png",
    "06_steady_60mph_levels_clean.png",
    "06_steady_60mph_levels_clean.svg",
    "07_4_8khz_30_vs_60mph_clean.png",
    "07_4_8khz_30_vs_60mph_clean.svg",
    "02_mmsa_array_rectified.svg",
    "context_peak_frequency_by_condition.png",
    "context_peak_frequency_by_condition.svg",
)


def crop_photo_panels(composite_path: Path, output_dir: Path) -> list[Path]:
    """Crop the registered photo panels without resizing their pixels."""
    composite = Image.open(composite_path)
    width, height = composite.size
    outputs: list[Path] = []
    for stem, normalized_box in PHOTO_CROPS:
        left, top, right, bottom = normalized_box
        box = (
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        )
        path = output_dir / f"{stem}.png"
        composite.crop(box).save(path, optimize=True)
        outputs.append(path)
    return outputs


def export_flow_reference(session: Path, output_png: Path) -> list[Path]:
    """Export the flow photo using the conventional leading-edge x/c coordinate.

    The registered photograph is kept in its native physical orientation (aft
    edge at image left, forward edge at image right).  Tick labels therefore
    decrease left-to-right: x/c from the leading edge is 1 at the aft edge and
    0 at the forward edge.  This matches the coordinate reported on the
    rectified-array and paper-method figures.
    """
    source = session / "source_photos" / "flow_60mph.jpg"
    if not source.is_file():
        raise FileNotFoundError(f"flow source photo not found: {source}")
    flow = np.asarray(ImageOps.exif_transpose(Image.open(source)).convert("RGB"))
    panel = ov.crop_flow(flow)
    peak_aft, lo_aft, hi_aft, _profile = ov.ridge_position(panel)
    ratio = panel.shape[0] / panel.shape[1]

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(7.2, 8.2), facecolor="white")
    ax.imshow(panel, extent=(0, 1, ratio, 0), aspect="equal")
    ax.set_xlim(0, 1)
    ax.set_ylim(ratio, 0)
    ticks = np.linspace(0, 1, 5)
    ax.set_xticks(ticks, [f"{1.0 - value:.2f}" for value in ticks])
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.axvspan(lo_aft, hi_aft, color=ov.C_FLOW, alpha=0.18, lw=0)
    ax.axvline(peak_aft, color="white", lw=1.4, ls=(0, (4, 3)))
    ax.set_title("60 mph fluorescent flow visualization", loc="left", fontsize=15, fontweight="bold")
    ax.set_xlabel("x/c from leading edge", labelpad=8)
    fig.tight_layout(pad=0.45)

    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_svg = output_png.with_suffix(".svg")
    fig.savefig(output_png, dpi=200, facecolor="white")
    fig.savefig(output_svg, facecolor="white")
    plt.close(fig)
    return [output_png, output_svg]


def style_level_axis(ax: plt.Axes, xc: np.ndarray, title: str) -> None:
    """Apply the shared presentation styling and physical reference zone."""
    ax.axvspan(*FLOW_ZONE_XC, color=ov.C_FLOW, alpha=0.18, lw=0, zorder=0)
    ax.set_title(title, loc="left", fontsize=16, fontweight="bold", pad=10)
    ax.set_ylabel("Level (dBFS)", fontsize=13)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xlabel("x/c  (0 = aft edge, 1 = forward edge)", fontsize=12, labelpad=31)
    ax.tick_params(axis="both", labelsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for mic, position in enumerate(xc):
        ax.annotate(
            str(mic),
            (position, 0),
            xycoords=("data", "axes fraction"),
            xytext=(0, -25),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=10,
            color="#555555",
            annotation_clip=False,
        )


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> list[Path]:
    """Save a high-resolution bitmap and an editable vector version."""
    png = output_dir / f"{stem}.png"
    svg = output_dir / f"{stem}.svg"
    fig.savefig(png, dpi=240, facecolor="white")
    fig.savefig(svg, facecolor="white")
    plt.close(fig)
    return [png, svg]


def export_level_plots(session: Path, output_dir: Path) -> list[Path]:
    xc = np.asarray([ov.mic_xc(i) for i in range(8)])
    broadband_60 = ov.band_level(session, ov.WING_60, None)
    band_60 = ov.band_level(session, ov.WING_60, ov.BAND)
    band_30 = ov.band_level(session, ov.WING_30, ov.BAND)
    outputs: list[Path] = []

    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    fig.subplots_adjust(left=0.13, right=0.97, top=0.87, bottom=0.23)
    style_level_axis(ax, xc, "Steady 60 mph: level at each mic")
    ax.plot(
        xc,
        broadband_60,
        "o-",
        color="#555555",
        lw=2.4,
        ms=7.5,
        mec="white",
        mew=1,
        label="Broadband 20 Hz-20 kHz",
        zorder=2,
    )
    ax.plot(
        xc,
        band_60,
        "s-",
        color=ov.C_HI,
        lw=2.4,
        ms=7,
        mec="white",
        mew=1,
        label="4-8 kHz",
        zorder=2,
    )
    ax.legend(frameon=False, loc="lower left", fontsize=11)
    outputs.extend(save_figure(fig, output_dir, "04_steady_60mph_levels_clean"))

    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    fig.subplots_adjust(left=0.13, right=0.97, top=0.87, bottom=0.23)
    style_level_axis(ax, xc, "4-8 kHz: break moves forward with speed")
    ax.plot(
        xc,
        band_30,
        "o-",
        color=ov.C_MIC,
        lw=2.4,
        ms=7.5,
        mec="white",
        mew=1,
        label="30 mph, 4-8 kHz",
        zorder=2,
    )
    ax.plot(
        xc,
        band_60,
        "s-",
        color=ov.C_HI,
        lw=2.4,
        ms=7,
        mec="white",
        mew=1,
        label="60 mph, 4-8 kHz",
        zorder=2,
    )
    ax.legend(frameon=False, loc="lower left", fontsize=11)
    outputs.extend(save_figure(fig, output_dir, "05_4_8khz_30_vs_60mph_clean"))
    return outputs


def export_paper_metrics(session: Path, output_dir: Path) -> list[Path]:
    """Export the clean profiles followed by their finite-difference slopes."""
    metrics = {key: paper.analyse_take(session, key) for key in ("30", "60")}
    profile_png = output_dir / "06_paper_metrics_2_7khz_clean.png"
    paper.plot_spatial_clean(metrics, profile_png)

    picks: dict[tuple[str, str], paper.Pick] = {}
    for condition in ("30", "60"):
        take = metrics[condition]
        picks[(condition, "Lp")] = paper.transition_pick(
            condition, "Lp", np.median(take.lp_dbfs, axis=0)
        )
        picks[(condition, "fmu")] = paper.transition_pick(
            condition, "fmu", np.median(take.fmu_hz, axis=0)
        )
    derivative_png = output_dir / "07_paper_metric_spatial_derivatives.png"
    paper.plot_derivatives(metrics, picks, derivative_png)
    return [
        profile_png,
        profile_png.with_suffix(".svg"),
        derivative_png,
        derivative_png.with_suffix(".svg"),
    ]


def export_array_positions(session: Path, output_dir: Path) -> list[Path]:
    """Build the coordinate-provenance slide from the original array photo."""
    source = session / "source_photos" / "IMG_6677_array_wing.HEIC"
    if not source.is_file():
        raise FileNotFoundError(f"array source photo not found: {source}")
    png = output_dir / "02_mmsa_array_rectified.png"
    ov.save_array_positions(source, png)
    return [png, png.with_suffix(".svg")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="session directory containing the wing WAV folders")
    parser.add_argument("composite", type=Path, help="existing registered flow/array composite PNG")
    parser.add_argument("output_dir", type=Path, help="directory for presentation assets")
    args = parser.parse_args()

    if not args.session.is_dir():
        parser.error(f"session directory not found: {args.session}")
    if not args.composite.is_file():
        parser.error(f"composite image not found: {args.composite}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename in LEGACY_OUTPUTS:
        (args.output_dir / filename).unlink(missing_ok=True)

    ramp_source = args.composite.parent / "ramp_band_multiplot.png"
    if not ramp_source.is_file():
        parser.error(f"ramp frequency-band figure not found: {ramp_source}")
    ramp_output = args.output_dir / "00_ramp_frequency_band_comparison.png"
    shutil.copy2(ramp_source, ramp_output)

    overview_sources = (
        ("wing_level_heatmaps.png", "context_wing_level_timeline.png"),
        ("wing_ramp_spectrograms.png", "context_ramp_spectrograms.png"),
        ("full_scale_clipping_by_condition.png", "context_full_scale_clipping_by_condition.png"),
        ("full_scale_clipping_by_condition.svg", "context_full_scale_clipping_by_condition.svg"),
    )
    overview_outputs = []
    for source_name, output_name in overview_sources:
        source = args.composite.parent / source_name
        if not source.is_file():
            parser.error(f"context figure not found: {source}")
        output = args.output_dir / output_name
        shutil.copy2(source, output)
        overview_outputs.append(output)

    outputs = [*overview_outputs, ramp_output]
    outputs.extend(export_flow_reference(args.session, args.output_dir / "09_60mph_flow_visualization.png"))
    outputs.extend(
        broadband_psd.export(
            args.session,
            args.output_dir / "17_wing_30_60_broadband_psd.png",
            args.composite.parent / "wing_broadband_psd.csv",
        )
    )
    outputs.extend(export_paper_metrics(args.session, args.output_dir))
    outputs.extend(crop_photo_panels(args.composite, args.output_dir))
    outputs.extend(export_array_positions(args.session, args.output_dir))
    outputs.extend(export_level_plots(args.session, args.output_dir))
    for path in outputs:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
