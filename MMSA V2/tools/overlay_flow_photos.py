"""Chord-normalized comparison of the 60 mph flow photo, the array photo and the mic levels.

This is a deterministic composition (no generative processing). Both photos are
resampled onto a shared chordwise coordinate, x/c, using the visible wing edges
(aft edge = 0, forward edge = 1). The array photo is rectified row by row because
the wing edges converge slightly in perspective. The fluorescent line position is
measured from the flow photo (peak and half-maximum width of the green-excess
profile) instead of being drawn by eye. Spanwise position is NOT registered.

Usage:
    python overlay_flow_photos.py FLOW.jpg ARRAY.heic SESSION_DIR OUTPUT.png
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.signal import butter, sosfilt

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# Wing edges measured on the supplied full-resolution photographs.
FLOW_LEFT, FLOW_RIGHT = 1605, 3405           # aft edge, forward edge (flow photo x, px)
FLOW_ROWS = (600, 2760)                       # spanwise window shown from the flow photo
ARRAY_ROWS = (1250, 2680)                     # spanwise window shown from the array photo
# Array photo wing edges are linear in y: (y, aft-edge x, forward-edge x).
ARRAY_EDGES = ((1500, 895, 2100), (2365, 915, 2085))

# Mic acoustic-port centers remeasured at native resolution in the array photo,
# px.  These are the bright circular ports within the dark microphone packages,
# not the package corners or nearby solder joints.
MIC_CENTERS = [(1190, 2287), (1294, 2184), (1404, 2070), (1515, 1966),
               (1630, 1848), (1747, 1731), (1855, 1618), (1966, 1499)]

WING_60 = "MMSA8_0013_Wing_60"
WING_30 = "MMSA8_0011_Wing_30"
FS = 48000
BAND = (4000, 8000)
OUT_W = 600                                   # rectified panel width, px (x/c 0..1)

C_FLOW, C_GAP, C_MIC, C_HI = "#2e9e3e", "#f28e2b", "#2f6db5", "#d55e00"


def array_edges(y: float) -> tuple[float, float]:
    (y0, l0, r0), (y1, l1, r1) = ARRAY_EDGES
    t = (y - y0) / (y1 - y0)
    return l0 + t * (l1 - l0), r0 + t * (r1 - r0)


def mic_xc(i: int) -> float:
    x, y = MIC_CENTERS[i]
    left, right = array_edges(y)
    return (x - left) / (right - left)


def mic_yc(i: int) -> float:
    return (MIC_CENTERS[i][1] - ARRAY_ROWS[0]) / (ARRAY_EDGES[0][2] - ARRAY_EDGES[0][1])


def rectify_array(img: np.ndarray) -> np.ndarray:
    """Resample each row between its own wing edges so x/c is the same column everywhere."""
    y0, y1 = ARRAY_ROWS
    scale = (ARRAY_EDGES[0][2] - ARRAY_EDGES[0][1]) / OUT_W
    h = round((y1 - y0) / scale)
    ys = y0 + np.arange(h) * scale
    xs = np.array([np.linspace(*array_edges(y), OUT_W) for y in ys])
    yy = np.repeat(ys[:, None], OUT_W, axis=1)
    return np.dstack([map_coordinates(img[..., c], [yy, xs], order=1) for c in range(3)])


def crop_flow(img: np.ndarray) -> np.ndarray:
    y0, y1 = FLOW_ROWS
    crop = Image.fromarray(img[y0:y1, FLOW_LEFT:FLOW_RIGHT])
    h = round(OUT_W * (y1 - y0) / (FLOW_RIGHT - FLOW_LEFT))
    return np.asarray(crop.resize((OUT_W, h), Image.Resampling.LANCZOS))


def green_excess(img: np.ndarray) -> np.ndarray:
    f = img.astype(float)
    return f[..., 1] - np.maximum(f[..., 0], f[..., 2])


def ridge_position(flow_panel: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    prof = gaussian_filter(green_excess(flow_panel).mean(0), 2)
    x = np.arange(OUT_W) / OUT_W
    lo, hi = int(0.08 * OUT_W), int(0.58 * OUT_W)      # skip the bright aft-edge line and the zigzag tape
    pk = lo + int(np.argmax(prof[lo:hi]))
    base = np.median(prof[lo:hi])
    half = base + (prof[pk] - base) / 2
    l = pk
    while l > 0 and prof[l] > half:
        l -= 1
    r = pk
    while r < OUT_W - 1 and prof[r] > half:
        r += 1
    return x[pk], x[l], x[r], prof


def band_level(session: Path, take: str, band: tuple[float, float] | None) -> np.ndarray:
    with wave.open(str(next((session / take).glob("*.wav")))) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 8) / 32768.0
    x = x[int(0.3 * FS):]
    x = x - x.mean(0)
    if band is not None:
        x = sosfilt(butter(4, band, btype="band", fs=FS, output="sos"), x, axis=0)
    n = len(x) // FS
    win = np.array([10 * np.log10((x[i * FS:(i + 1) * FS] ** 2).mean(0) + 1e-20) for i in range(n)])
    return np.median(win, axis=0)


def fluor_overlay(array_panel: np.ndarray, flow_panel: np.ndarray) -> np.ndarray:
    ex = green_excess(flow_panel)
    ex = np.asarray(Image.fromarray(ex.astype(np.float32)).resize(array_panel.shape[1::-1], Image.Resampling.BILINEAR))
    ex = gaussian_filter(ex, 1.5)
    alpha = np.clip((ex - 18) / 60, 0, 1)[..., None] * 0.9
    base = array_panel.astype(float) * 0.85
    lime = np.array([60, 255, 70], float)
    return np.clip(base * (1 - alpha) + lime * alpha, 0, 255).astype(np.uint8)


def save_array_positions(array_photo: Path, output: Path) -> None:
    """Export the rectified array photo with neutral markers and measured x/c.

    The photo remains in its original aft-to-forward left-to-right orientation.
    The bottom axis shows that image-registration coordinate.  The top axis and
    the microphone labels show the conventional leading-edge coordinate used by
    the downstream spatial plots.
    """
    array = np.asarray(ImageOps.exif_transpose(Image.open(array_photo)).convert("RGB"))
    panel = rectify_array(array)
    ratio = panel.shape[0] / OUT_W
    xc_aft = np.asarray([mic_xc(i) for i in range(8)])
    xc_leading = 1.0 - xc_aft

    plt.rcParams.update({"font.size": 11, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(8.1, 9.6), facecolor="white")
    ax.imshow(panel, extent=(0, 1, ratio, 0), aspect="equal")
    ax.set_xlim(0, 1)
    ax.set_ylim(ratio, 0)
    ticks = [0, 0.25, 0.5, 0.75, 1]
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)

    for value in ticks:
        ax.plot(
            [value, value],
            [1.0, 1.012],
            transform=ax.get_xaxis_transform(),
            color="#222222",
            lw=0.9,
            clip_on=False,
        )
        ax.text(
            value,
            1.018,
            f"{1.0 - value:.2f}",
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=10.5,
            color="#222222",
        )
    ax.text(
        0.5,
        1.065,
        "Coordinate used in analysis: x/c from leading edge",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=11,
        color="#222222",
    )

    stroke = [path_effects.withStroke(linewidth=2.6, foreground="black")]
    guide_effects = [
        path_effects.Stroke(linewidth=3.0, foreground="black", alpha=0.82),
        path_effects.Normal(),
    ]
    for mic in range(8):
        xx, yy = xc_aft[mic], mic_yc(mic)
        # In the rectified image the chord direction is horizontal and the
        # leading edge is x=1.  The dotted segment therefore measures the
        # leading-edge-to-port distance directly on the common chord axis.
        guide, = ax.plot(
            [xx, 1.0],
            [yy, yy],
            color="white",
            lw=1.25,
            linestyle=(0, (1.2, 2.2)),
            solid_capstyle="round",
            zorder=4,
        )
        guide.set_path_effects(guide_effects)
        ax.plot(
            xx,
            yy,
            "o",
            ms=9,
            mfc="#f7f7f7",
            mec="#222222",
            mew=1.6,
            zorder=5,
        )
        ax.annotate(
            f"mic{mic}",
            (xx, yy),
            xytext=(-7, -7),
            textcoords="offset points",
            ha="right",
            va="top",
            color="white",
            fontsize=9.5,
            fontweight="bold",
            zorder=6,
            path_effects=stroke,
        )
        ax.annotate(
            f"{xc_leading[mic]:.3f}c",
            ((xx + 1.0) / 2.0, yy),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color="white",
            fontsize=8.8,
            fontweight="bold",
            zorder=6,
            path_effects=stroke,
        )

    fig.suptitle(
        "Measured microphone positions on the rectified wing image",
        x=0.5,
        y=0.988,
        ha="center",
        fontsize=14.5,
        fontweight="bold",
    )
    fig.subplots_adjust(left=0.07, right=0.98, top=0.90, bottom=0.03)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=240, facecolor="white")
    if output.suffix.lower() == ".png":
        fig.savefig(output.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("flow_photo", type=Path)
    ap.add_argument("array_photo", type=Path)
    ap.add_argument("session", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()

    flow = np.asarray(ImageOps.exif_transpose(Image.open(args.flow_photo)).convert("RGB"))
    array = np.asarray(ImageOps.exif_transpose(Image.open(args.array_photo)).convert("RGB"))
    flow_panel, array_panel = crop_flow(flow), rectify_array(array)
    overlay = fluor_overlay(array_panel, flow_panel)
    peak, lo, hi, prof = ridge_position(flow_panel)
    xc = [mic_xc(i) for i in range(8)]
    print(f"fluorescent line x/c = {peak:.3f} (half-max {lo:.3f}-{hi:.3f}); mic2 {xc[2]:.3f}, mic3 {xc[3]:.3f}")

    b60, t60 = band_level(args.session, WING_60, BAND), band_level(args.session, WING_60, None)
    b30 = band_level(args.session, WING_30, BAND)

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig = plt.figure(figsize=(16.5, 11.5), facecolor="white")
    gs = fig.add_gridspec(2, 3, height_ratios=[1.55, 1], hspace=0.28, wspace=0.12,
                          left=0.045, right=0.985, top=0.885, bottom=0.11)
    ratio_flow = flow_panel.shape[0] / OUT_W
    ratio_arr = array_panel.shape[0] / OUT_W

    def photo(ax, im, ratio, title):
        ax.imshow(im, extent=(0, 1, ratio, 0), aspect="equal")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.axvspan(lo, hi, color=C_FLOW, alpha=0.18, lw=0)
        ax.axvline(peak, color="white", lw=1.4, ls=(0, (4, 3)))

    ax1, ax2, ax3 = (fig.add_subplot(gs[0, k]) for k in range(3))
    photo(ax1, flow_panel, ratio_flow, "60 mph fluorescent flow visualization")
    photo(ax2, array_panel, ratio_arr, "MMSA array on the wing (rectified)")
    photo(ax3, overlay, ratio_arr, "Overlay on the shared chord axis")
    for ax in (ax1, ax2, ax3):
        ax.axvline(peak, color=C_FLOW, lw=0.8, alpha=0.0)
    ax2.set_ylim(ratio_arr, 0)
    ax1.set_ylim(ratio_flow, 0)

    for ax in (ax2, ax3):
        for i in range(8):
            hi_zone = i <= 2
            ax.plot(xc[i], mic_yc(i), "o", ms=9, mfc=C_HI if hi_zone else C_MIC, mec="white", mew=1.6, zorder=5)
            ax.annotate(f"mic{i}", (xc[i], mic_yc(i)), xytext=(8, 7), textcoords="offset points",
                        color="white", fontsize=10, fontweight="bold", zorder=6,
                        path_effects=[__import__("matplotlib.patheffects").patheffects.withStroke(linewidth=2.5, foreground="black")])
    ax3.axvspan(xc[2], xc[3], color=C_GAP, alpha=0.22, lw=0)
    for ax in (ax1, ax2, ax3):
        ax.set_xlim(0, 1)
    ax3.text(0.5 * (xc[2] + xc[3]), 0.03 * ratio_arr, "mic2-mic3\nlevel break", ha="center", va="top",
             fontsize=9, color="white", fontweight="bold",
             path_effects=[__import__("matplotlib.patheffects").patheffects.withStroke(linewidth=2.5, foreground="black")])

    # Row 2: charts sharing the x/c axis of the photos above.
    ax4, ax5, ax6 = (fig.add_subplot(gs[1, k]) for k in range(3))
    ax4.plot(np.arange(OUT_W) / OUT_W, prof, color=C_FLOW, lw=2)
    ax4.axvspan(lo, hi, color=C_FLOW, alpha=0.18, lw=0)
    ax4.axvline(peak, color=C_FLOW, lw=1.2, ls="--")
    ax4.set_ylabel("Green excess (spanwise mean)")
    ax4.set_title(f"Measured fluorescent line: x/c = {peak:.2f} ({lo:.2f}-{hi:.2f})", loc="left", fontweight="bold")
    ax4.set_yticks([])

    def level_axis(ax, series, title, gap=None):
        ax.axvspan(lo, hi, color=C_FLOW, alpha=0.18, lw=0)
        if gap:
            ax.axvspan(xc[gap], xc[gap + 1], color=C_GAP, alpha=0.22, lw=0)
        for label, lvl, color, style in series:
            ax.plot(xc, lvl, style, color=color, lw=2, ms=7, label=label, mec="white")
        for i in range(8):
            ax.annotate(str(i), (xc[i], 0), xycoords=("data", "axes fraction"), xytext=(0, -26),
                        textcoords="offset points", ha="center", fontsize=9, color="#555")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_ylabel("Level (dBFS)")
        ax.legend(frameon=False, loc="lower left", fontsize=9)

    level_axis(ax5, [("Broadband 20 Hz-20 kHz", t60, "#555555", "o-"), ("4-8 kHz", b60, C_HI, "s-")],
               "Steady 60 mph: level at each mic", gap=2)
    level_axis(ax6, [("30 mph, 4-8 kHz", b30, C_MIC, "o-"), ("60 mph, 4-8 kHz", b60, C_HI, "s-")],
               "4-8 kHz: break moves forward with speed")
    ax6.axvspan(xc[1], xc[2], color=C_GAP, alpha=0.12, lw=0)
    for ax in (ax4, ax5, ax6):
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    for ax in (ax4, ax5, ax6):
        ax.set_xlabel("x/c (0 = aft edge, 1 = forward edge)")
    for ax in (ax5, ax6):
        ax.xaxis.labelpad = 24

    fig.suptitle("Fluorescent flow line vs microphone level break on the wing", x=0.045, y=0.975, ha="left",
                 fontsize=17, fontweight="bold")
    fig.text(0.045, 0.912, f"Green band: half-maximum width of the fluorescent line from the flow photo. "
             f"Orange band: gap between mic2 and mic3 (x/c {xc[2]:.2f}-{xc[3]:.2f}), where the 60 mph level drops.\n"
             "Orange dots: mics in the high-level region at 60 mph.", fontsize=10.5, color="#333", ha="left")
    fig.text(0.045, 0.015, "Registration aligns the aft and forward wing edges only; spanwise position and camera perspective "
             "remain approximate (spanwise windows differ between photos). No generative processing used.",
             fontsize=9.5, color="#555", ha="left")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
