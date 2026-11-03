"""Section-view previews of the airfoil port test bed, cut from the generated STL meshes.

Reads output/reference/{block,backer,flex,parts}.stl and testbed_design.json
(written by generate_testbed.mjs) and writes output/reference/testbed_sections.png:
  top     full-chord section through the port line, with the flex, mics and backer
  bottom  one close-up per mic, cut through that mic's hole

Usage:
    python preview_testbed.py [OUTPUT_DIR]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

INK = "#0b0b0b"
INK_2 = "#52514e"
SURFACE = "#fcfcfb"
LAYERS = {  # name: (colour, label)
    "block": (INK_2, "printed block"),
    "backer": ("#2a78d6", "printed backer"),
    "flex": ("#eb6834", "flex, 0.11 mm"),
    "parts": ("#1baf7a", "mics and caps"),
}


def read_stl(path: Path) -> np.ndarray:
    """Binary STL -> (n, 3, 3) triangle vertices."""
    data = path.read_bytes()
    n = int.from_bytes(data[80:84], "little")
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                        count=n, offset=84)
    return rec["v"].astype(float)


def section_y(tris: np.ndarray, y0: float) -> np.ndarray:
    """Segments (m, 2, 2) in (x, z) where the plane Y = y0 cuts the mesh."""
    d = tris[:, :, 1] - (y0 + 1e-7)
    cut = (d.min(1) < 0) & (d.max(1) > 0)
    t, d = tris[cut], d[cut]
    pts = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        da, db = d[:, a], d[:, b]
        cross = (da < 0) != (db < 0)
        w = np.where(cross, da / np.where(cross, da - db, 1), 0)[:, None]
        p = t[:, a] + w * (t[:, b] - t[:, a])
        pts.append(np.where(cross[:, None], p[:, [0, 2]], np.nan))
    pts = np.stack(pts, 1)  # (m, 3, 2), exactly two finite rows per triangle
    ok = ~np.isnan(pts[:, :, 0])
    return np.stack([pts[i][ok[i]][:2] for i in range(len(pts))]) if len(pts) else np.zeros((0, 2, 2))


def draw(ax, meshes, y0, lw=0.8):
    for name, tris in meshes.items():
        segs = section_y(tris, y0)
        ax.add_collection(LineCollection(segs, colors=LAYERS[name][0], linewidths=lw))


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "output"
    ref = out / "reference"
    design = json.loads((ref / "testbed_design.json").read_text())
    meshes = {name: read_stl(ref / f"{name}.stl") for name in LAYERS}

    fig = plt.figure(figsize=(16, 12), facecolor=SURFACE)
    gs = fig.add_gridspec(3, 4, height_ratios=[0.75, 1, 1], hspace=0.35, wspace=0.15)

    ax = fig.add_subplot(gs[0, :])
    draw(ax, meshes, -0.6, lw=0.7)
    for m in design["mics"]:
        ax.annotate(f"mic{m['mic']}\nD{m['D']} d{m['d']}", (m["portX"], m["surfaceZ"] + 1.0),
                    ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xlim(-5, 310)
    ax.set_ylim(-8, 26)
    ax.set_aspect("equal")
    ax.set_title("Section through the port line (Y = -0.6 mm). Flex goes in from below; tail exits the front slot",
                 fontsize=10, color=INK, loc="left")
    ax.set_xlabel("x from leading edge (mm)", color=INK_2)
    ax.set_ylabel("z (mm)", color=INK_2)

    for i, m in enumerate(design["mics"]):
        a = fig.add_subplot(gs[1 + i // 4, i % 4])
        draw(a, meshes, m["holeY"], lw=1.0)
        cx = m["portX"]
        a.set_xlim(cx - 9.5, cx + 2.5)  # caps sit forward (smaller x) of each mic
        a.set_ylim(m["roofZ"] - 1.2, m["surfaceZ"] + 1.2)
        a.set_aspect("equal")
        caps = ", ".join(f"{c['name']} skin {c['skin']}" + (" (open)" if c["openThroughTop"] else "")
                         for c in m["caps"])
        a.set_title(f"mic{m['mic']}  x/c {m['portXOverC']}:  D {m['D']}, d {m['d']} mm\n{caps}",
                    fontsize=8, color=INK, loc="left")
        a.tick_params(labelsize=7, colors=INK_2)

    for a in fig.axes:
        a.set_facecolor(SURFACE)
        for s in a.spines.values():
            s.set_color("#d6d5d0")
    handles = [Line2D([], [], color=c, lw=2, label=lab) for c, lab in LAYERS.values()]
    fig.legend(handles=handles, loc="upper right", ncol=4, frameon=False, fontsize=9)
    fig.suptitle("MMSA airfoil port test bed v1: section views (close-ups cut through each hole; leading edge to the left)",
                 x=0.02, ha="left", fontsize=12, color=INK)
    path = ref / "testbed_sections.png"
    fig.savefig(path, dpi=140, facecolor=SURFACE, bbox_inches="tight")
    print("wrote", path)


if __name__ == "__main__":
    main()
