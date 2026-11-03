"""Preview images for the NACA 4415 port test bed.

Reads output/reference/{block,backer,flex,parts}.stl and testbed_design.json
(written by generate_testbed_4415.mjs) and writes output/reference/:
  testbed_plan.png      top and bottom views (bottom = as seen with the block upside down)
  testbed_ports.png     a cut along the flex through each port
Run:  python preview_testbed_4415.py
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


def shaded(ax, tris, from_below=False, cmap_lo=0.35):
    """Orthographic top (or bottom) view with simple Lambert shading, painter-sorted."""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([-0.4, 0.5, 0.77]) * (np.array([1, 1, -1]) if from_below else 1)
    light /= np.linalg.norm(light)
    shade = np.clip(n @ light, 0, 1) * (1 - cmap_lo) + cmap_lo
    facing = n[:, 2] < 0 if from_below else n[:, 2] > 0
    order = np.argsort(tris[:, :, 2].mean(axis=1) * (-1 if from_below else 1))
    order = order[facing[order]]
    xy = tris[order][:, :, :2].copy()
    if from_below:
        xy[:, :, 0] *= -1
    ax.add_collection(PolyCollection(xy, facecolors=np.repeat(shade[order, None], 3, axis=1), edgecolors="none"))
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
    return np.array(segs)


def main():
    design = json.loads((REF / "testbed_design.json").read_text())
    block, backer, flex, parts = (load_stl(REF / f"{n}.stl") for n in ("block", "backer", "flex", "parts"))

    # ---- plan views
    fig, axs = plt.subplots(1, 2, figsize=(16, 8.5))
    shaded(axs[0], block)
    for e in design["plan"]["channelEdges"]:
        e = np.array(e)
        axs[0].plot(e[:, 0], e[:, 1], color="#3b7dd8", lw=0.6, ls="--")
    for p in design["plan"]["ports"]:
        axs[0].annotate(f"mic{p['mic']}\nD{p['D']}", (p["x"], p["y"]), xytext=(-18, 6), textcoords="offset points",
                        fontsize=7, color="#c03030", ha="right")
    axs[0].set_title(f"Top (leading edge left). Flex yawed {design['yawDeg']}°; dashed = flex channel under the skin")
    shaded(axs[1], np.concatenate([block, backer]), from_below=True)
    axs[1].set_title("Bottom, as seen with the block upside down (labels, channel, backer)")
    for ax in axs:
        ax.grid(alpha=0.25)
        ax.set_xlabel("mm")
    fig.tight_layout()
    fig.savefig(REF / "testbed_plan.png", dpi=130)
    plt.close(fig)

    # ---- cut along the flex through each port
    fig, axs = plt.subplots(2, 4, figsize=(18, 7.5))
    for ax, m, d in zip(axs.flat, design["mics"], design["plan"]["stripDirection"]):
        port = next(p for p in design["plan"]["ports"] if p["mic"] == m["mic"])
        p0 = np.array([port["x"], port["y"], 0.0])
        dvec = np.array([d[0], d[1], 0.0])
        normal = np.array([-d[1], d[0], 0.0])
        for tris, color, lw in ((block, "k", 0.9), (backer, "#3b7dd8", 0.8), (flex, "#e0b000", 1.2), (parts, "#8b5a2b", 0.9)):
            segs = slice_plane(tris, p0, normal)
            for a, b in segs:
                ta, tb = (a - p0) @ dvec, (b - p0) @ dvec
                if abs(ta) < 14 or abs(tb) < 14:
                    ax.plot([ta, tb], [a[2], b[2]], color=color, lw=lw)
        ax.set_xlim(-12, 12)
        ax.set_ylim(m["portZ"] - 6, m["portZ"] + 2)
        ax.set_aspect("equal")
        ax.grid(alpha=0.25)
        ax.set_title(f"mic{m['mic']}: D {m['D']}  d {m['d']}  (x/c {m['portXOverC']})", fontsize=9)
    fig.suptitle("Cut along the flex through each hole (left = toward the leading edge / tail end). "
                 "Black block, yellow flex, brown mic + caps, blue backer", fontsize=10)
    fig.tight_layout()
    fig.savefig(REF / "testbed_ports.png", dpi=130)
    plt.close(fig)
    print("wrote", REF / "testbed_plan.png", REF / "testbed_ports.png")


if __name__ == "__main__":
    main()
