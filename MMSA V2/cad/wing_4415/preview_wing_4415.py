"""Preview images for the NACA 4415 wing.

Reads output/reference/*.stl and wing_design.json (written by
generate_wing_4415.mjs) and writes output/reference/:
  wing_plan.png       top half seen from below (cover off) and the cover seen from above
  wing_sections.png   chordwise cuts through the cable path and through the board + battery
  wing_ports.png      a cut along the flex through each port
Run:  python preview_wing_4415.py
"""
import json
import struct
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

REF = Path(__file__).resolve().parent / "output" / "reference"


def load_stl(path):
    data = path.read_bytes()
    count = struct.unpack("<I", data[80:84])[0]
    rec = np.frombuffer(data[84:84 + count * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return rec["v"].astype(float)


def shaded(ax, tris, from_below=False, tint=(1, 1, 1), lo=0.35):
    """Orthographic view along Z with Lambert shading, painter-sorted."""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([-0.4, 0.5, 0.77]) * (np.array([1, 1, -1]) if from_below else 1)
    light /= np.linalg.norm(light)
    shade = np.clip(n @ light, 0, 1) * (1 - lo) + lo
    facing = n[:, 2] < 0 if from_below else n[:, 2] > 0
    order = np.argsort(tris[:, :, 2].mean(axis=1) * (-1 if from_below else 1))
    order = order[facing[order]]
    xy = tris[order][:, :, :2].copy()
    if from_below:
        xy[:, :, 1] *= -1  # looking up: mirror so the view is as you see it with the wing upside down
    # Flat faces all shade the same, so also darken with depth (away from the viewer).
    z = tris[order][:, :, 2].mean(axis=1) * (-1 if from_below else 1)
    zn = (z - z.min()) / (np.ptp(z) + 1e-9)
    colors = (shade[order] * (0.45 + 0.55 * zn))[:, None] * np.array(tint)[None, :]
    ax.add_collection(PolyCollection(xy, facecolors=colors, edgecolors="none"))
    ax.autoscale()
    ax.set_aspect("equal")


def slice_plane(tris, p0, normal):
    d = (tris - p0) @ normal
    segs = []
    for t, dd in zip(tris, d):
        if dd.max() <= 0 or dd.min() >= 0:
            continue
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if (dd[i] > 0) != (dd[j] > 0):
                u = dd[i] / (dd[i] - dd[j])
                pts.append(t[i] + u * (t[j] - t[i]))
        if len(pts) == 2:
            segs.append(pts)
    return segs


def main():
    design = json.loads((REF / "wing_design.json").read_text())
    lay = design["layout"]
    top, cover, backer, flex, parts, board, battery = (
        load_stl(REF / f"{n}.stl") for n in ("top", "cover", "backer", "flex", "parts", "board", "battery"))

    # ---- plan views
    fig, axs = plt.subplots(1, 2, figsize=(17, 8.5))
    shaded(axs[0], np.concatenate([top, backer]), from_below=True)
    shaded(axs[0], board, from_below=True, tint=(0.55, 0.85, 0.6))
    axs[0].set_title("Top half from below (cover off, wing upside down): board, flex channel + backer, inserts")
    shaded(axs[1], cover)
    axs[1].set_title("Cover from above (inside face): board pocket, cable bay, screw holes")
    for ax in axs:
        ax.grid(alpha=0.25)
        ax.set_xlabel("chord X (mm)")
    fig.tight_layout()
    fig.savefig(REF / "wing_plan.png", dpi=120)
    plt.close(fig)

    # ---- chordwise sections: cable path, and through the board/battery
    b = lay["board"]
    cuts = [("cable path", lay["cableY"]), ("board + battery", (b["y0"] + b["y1"]) / 2)]
    fig, axs = plt.subplots(len(cuts), 1, figsize=(16, 4.2 * len(cuts)))
    for ax, (what, y) in zip(axs, cuts):
        p0 = np.array([0.0, y, 0.0])
        nrm = np.array([0.0, 1.0, 0.0])
        for tris, color, lw in ((top, "k", 0.8), (cover, "0.45", 0.8), (backer, "#3b7dd8", 0.8),
                                (flex, "#e0b000", 1.2), (board, "#2e9a4a", 1.0), (battery, "#7b3fa0", 1.0)):
            for a, c in slice_plane(tris, p0, nrm):
                ax.plot([a[0], c[0]], [a[2], c[2]], color=color, lw=lw)
        if what == "cable path":
            ax.plot([3, b["x0"] + 3.5], [-3.75, -2.4], color="#e0b000", lw=2, ls="--")
        ax.axhline(0, color="r", lw=0.5, ls=":")
        ax.set_aspect("equal")
        ax.set_xlim(-5, 250)
        ax.grid(alpha=0.25)
        ax.set_title(f"Cut at Y = {y:.1f} ({what}). Black top half, grey cover, green board, purple battery, "
                     "blue backer, yellow flex (dashed = cable, drawn by hand)", fontsize=9)
    fig.tight_layout()
    fig.savefig(REF / "wing_sections.png", dpi=120)
    plt.close(fig)

    # ---- cut along the flex through each port
    mics = design["mics"]
    fig, axs = plt.subplots(2, 4, figsize=(18, 7.5))
    for ax in axs.flat[len(mics):]:
        ax.axis("off")
    for ax, m, d in zip(axs.flat, mics, design["plan"]["stripDirection"]):
        port = next(p for p in design["plan"]["ports"] if p["mic"] == m["mic"])
        p0 = np.array([port["x"], port["y"], 0.0])
        dvec = np.array([d[0], d[1], 0.0])
        normal = np.array([-d[1], d[0], 0.0])
        for tris, color, lw in ((top, "k", 0.9), (backer, "#3b7dd8", 0.8), (flex, "#e0b000", 1.2), (parts, "#8b5a2b", 0.9)):
            for a, c in slice_plane(tris, p0, normal):
                ta, tb = (a - p0) @ dvec, (c - p0) @ dvec
                if abs(ta) < 14 or abs(tb) < 14:
                    ax.plot([ta, tb], [a[2], c[2]], color=color, lw=lw)
        ax.set_xlim(-12, 12)
        ax.set_ylim(m["portZ"] - 6, m["portZ"] + 2)
        ax.set_aspect("equal")
        ax.grid(alpha=0.25)
        ax.set_title(f"mic{m['mic']} (x/c {m['portXOverC']}, slope {m['surfaceSlopeDeg']} deg)", fontsize=9)
    fig.suptitle("Cut along the flex through each hole (left = toward the leading edge). "
                 "Black top half, yellow flex, brown mic + caps, blue backer", fontsize=10)
    fig.tight_layout()
    fig.savefig(REF / "wing_ports.png", dpi=120)
    plt.close(fig)
    print("wrote", REF / "wing_plan.png", REF / "wing_sections.png", REF / "wing_ports.png")


if __name__ == "__main__":
    main()
