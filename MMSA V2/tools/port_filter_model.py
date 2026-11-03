"""Lumped model of a flush mic port: surface -> hole 1 -> small cavity over the mic -> hole 2 -> quiet interior.

Hole 1 is the series element, the cavity is a compliance, and hole 2 is a shunt leak to
a large quiet volume. The mic senses the cavity pressure. Each hole is a resistance
(small-tube viscous loss) plus an inertance (air mass). With no hole 2 the cavity is
sealed and the response is a plain Helmholtz resonator.

Estimates only: no thermal losses, no flow effects, ideal geometry. Calibrate the real
port in place (speaker sweep against a flush reference mic).

Usage:
    python port_filter_model.py OUTPUT.png
    python port_filter_model.py OUTPUT.png --design "label;d1_mm;L1_mm;d2_mm;L2_mm;V_mm3[;extra_R1]"

A film instead of hole 1: set d1 = L1 = 0 and append ;mem_radius_mm;tension_N_per_m;thickness_um.
Design strings can be repeated. d2_mm = 0 means no leak. extra_R1 is added series
resistance for stuffing, in Pa*s/m^3 (0 if omitted).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

RHO, C0, ETA = 1.2, 343.0, 1.8e-5

DEFAULTS = [
    "bare hole 0.5x1 mm, 5 mm3 (no leak);0.5;1;0;0;5",
        "bad: 0.2x3 / 0.2x1.4, 5 mm3;0.2;3;0.2;1.4;5",
    "~6 dB flat: 0.3x0.3 / 0.3x0.3, 1 mm3;0.3;0.3;0.3;0.3;1",
    "~10 dB flat: 0.3x1 / 0.3x0.3, 2 mm3;0.3;1;0.3;0.3;2",
]


def hole_impedance(d_mm: float, l_mm: float, w: np.ndarray) -> np.ndarray:
    r, length = d_mm / 2e3, l_mm / 1e3
    area = np.pi * r ** 2
    res_poiseuille = 8 * ETA * length / (np.pi * r ** 4)
    res_wide = length / (np.pi * r ** 3) * np.sqrt(2 * w * RHO * ETA)
    inertance = RHO * (length + 1.7 * r) / area
    return np.maximum(res_poiseuille, res_wide) + 1j * w * inertance


def membrane_impedance(a_mm: float, tension: float, thick_um: float, w: np.ndarray, q: float = 3.0) -> np.ndarray:
    """Circular film (Kapton-like, 1420 kg/m^3) stretched across a window of radius a_mm."""
    a = a_mm / 1e3
    compliance = np.pi * a ** 4 / (8 * tension)            # m^3/Pa, static
    w_m = 2.405 / a * np.sqrt(tension / (thick_um * 1e-6 * 1420))
    mass = 1 / (w_m ** 2 * compliance)
    return 1 / (1j * w * compliance) + 1j * w * mass + np.sqrt(mass / compliance) / q


def response(design: dict, f: np.ndarray) -> np.ndarray:
    w = 2 * np.pi * f
    if design["mem_a"] > 0:
        z1 = membrane_impedance(design["mem_a"], design["mem_T"], design["mem_t"], w) + design["extra"]
    else:
        z1 = hole_impedance(design["d1"], design["l1"], w) + design["extra"]
    y_shunt = 1j * w * (design["vol"] * 1e-9) / (RHO * C0 ** 2)
    if design["d2"] > 0:
        y_shunt = y_shunt + 1 / hole_impedance(design["d2"], design["l2"], w)
    return 1 / (1 + z1 * y_shunt)


def parse(text: str) -> dict:
    parts = text.split(";")
    vals = [float(p) for p in parts[1:]]
    keys = ("d1", "l1", "d2", "l2", "vol", "extra", "mem_a", "mem_T", "mem_t")
    return {"label": parts[0], **dict(zip(keys, vals + [0.0] * (9 - len(vals))))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output", type=Path)
    ap.add_argument("--design", action="append", help='"label;d1_mm;L1_mm;d2_mm;L2_mm;V_mm3[;extra_R1]"')
    args = ap.parse_args()
    designs = [parse(t) for t in (args.design or DEFAULTS)]

    f = np.logspace(np.log10(20), np.log10(20000), 600)
    marks = (500, 1000, 2000, 4000, 8000, 16000)
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axvspan(4000, 8000, color="#f7c59f", alpha=0.4, lw=0, label="4-8 kHz band")
    print("gain (dB) at " + "  ".join(f"{m} Hz" for m in marks))
    for d in designs:
        g = 20 * np.log10(np.abs(response(d, f)))
        ax.semilogx(f, g, lw=2, label=d["label"])
        gm = 20 * np.log10(np.abs(response(d, np.array(marks, float))))
        print(f"{d['label']}: " + "  ".join(f"{v:6.1f}" for v in gm))
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_ylim(-32, 15)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Cavity pressure / surface pressure (dB)")
    ax.set_title("Port filter response (lumped estimate)", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    ax.set_xticks([30, 100, 300, 1000, 3000, 10000], ["30", "100", "300", "1k", "3k", "10k"])
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=140)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
