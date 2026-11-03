# Port attenuation plan for the printed MMSA wing

Written 2026-10-30 after the first wind-tunnel test (2026-10-29). Goal: stop mic0-mic2 clipping at 60 mph without hurting the 4-8 kHz boundary signal and without disturbing the wing surface. All attenuation numbers below come from a lumped model (`tools/port_filter_model.py`), not from measurements.

## Why

- At steady 60 mph, mic0/mic1/mic2 clip (0.26 / 4.3 / 2.7 % of samples) with median levels of about -7.5 / -8.6 / -12.3 dBFS. The other mics do not clip. At 30 mph clipping is negligible. See `data/102926/analysis/run_summary.csv`.
- The boundary is most visible in 4-8 kHz (about 35 dB step at 30 mph, 17 dB at 60 mph). See `FINDINGS.md` and `data/102926/analysis/transition_band_search.png`.
- The popfilter test on the tunnel floor attenuated more than 20 dB at 2-8 kHz at 60 mph and almost nothing below 125 Hz. That is the wrong shape for this job, so popfilter material over the port is not the answer. `reference/LITERATURE_wing_mounting_and_transition.md` also says to leave ports uncovered for transition work.
- The IMP34DT05 is a **top-port** part (datasheet p.1 and Fig. 11): the sound inlet is in the lid, facing away from the flex. `COMPONENT_INDEX.md` used to say bottom port; fixed 2026-10-30.

## What a port does (model)

| Arrangement | Result |
|---|---|
| Hole over a sealed cavity (Helmholtz) | 0 dB flat, then a peak at f_R. A 0.5 mm x 1 mm hole over 5 mm^3 peaks near 10 kHz, which is inside or next to the band. Keep cavities small (1-2 mm^3). |
| Hole 1 into cavity plus hole 2 leaking to a large quiet volume | Flat attenuator (resistive divider), no filtering. 0.8 mm holes can reach about 10-23 dB flat to 8 kHz (table below). |
| Film over the opening, sealed cavity | Flat attenuation set by film compliance against cavity compliance, until the film resonance (about 15 kHz for the modelled film). No holes to print. |
| Film plus a printable leak | **Fails**: a high-pass with its corner far above the band, which blocks 4-8 kHz. |
| Film plus a needle-sized leak (about 0.1 mm x 1.2 mm) | A true high-pass near 1 kHz. Not printable, and not needed for clipping. |

An earlier version of these notes suggested a leak alone gives a high-pass. That was wrong; a leak without a film only sets the divider ratio.

Divider designs, 0.8 mm holes (hole 1 = surface to cavity, hole 2 = cavity to interior):

| Attenuation | Hole 1 | Hole 2 | Cavity |
|---|---|---|---|
| about 10 dB | 0.8 x 3 mm | 0.8 x 1 mm | 2 mm^3 |
| about 15 dB | 0.8 x 2 mm | 1.5 x 0.8 mm | 1 mm^3 |
| about 20 dB | 0.8 x 5 mm | 1.25 x 0.5 mm | 1 mm^3 |
| about 23 dB | 0.8 x 6 mm | 1.5 x 0.5 mm | 1 mm^3 |

Plots: `reference/port_filter_designs.png` (dividers), `reference/port_filter_membrane.png` (film variants), `reference/port_filter_model.png`.

## Chosen approach: Monokote film over small windows, sealed cavity

Monokote was used before and passed audio. It adds about 25 um to the surface, is flush, and tension is adjustable with heat.

- Print a small window (about 2 mm diameter) in the skin over each mic port and a 0.2-0.4 mm gap (cavity of about 1-3 mm^3) between the skin and the mic's top port. Seal the cavity; no hole 2.
- Attenuation depends on window radius^4 / film tension and on cavity volume. Model: about -6 / -10 / -14 dB for 30 / 60 / 120 N/m film at 1 mm window radius and 2 mm^3 cavity. Real Monokote tension is unknown (guess 25-100 N/m).
- Keep windows to about 2 mm diameter or smaller. The film resonance moves down as the window grows and a 6 mm window would resonate near 5 kHz, inside the band.
- Target about 10 dB on mic0 and mic1 and about 6-10 dB on mic2. Leave mic3-mic7 bare, since they do not clip and need the signal (quiet-side 4-8 kHz levels at 30 mph are within about 20 dB of the recorder floor). Apply a per-mic calibration correction.

## Next steps

1. **Done as the airfoil test bed** (`cad/airfoil_testbed/`, 2026-10-30): one diagonal print of the NACA 0012 upper surface on a flat base, with all 8 mics at their real flex positions (CAD, not the 39.5 mm acoustic estimate). Each port is a different window diameter D (1.6 / 2.0 / 2.4 mm) and skin depth d (0.8 / 1.1 / 1.4 mm; the 10 µF caps stop d going below 0.8 without opening their pockets through the skin). The whole top is wrapped, so there is no bare reference port; the reference is the same print measured before the film goes on (step 4).
2. Print in PETG or ASA, not PLA. PLA softens at about 55-60 C and Monokote needs roughly 105-120 C to seal. Test heat on a scrap piece first. Use the lowest iron setting that bonds, keep the iron moving, and back the skin with metal.
3. Seal one sheet of Monokote over the whole top surface (the final wing gets wrapped the same way), with the flex removed so the iron doesn't heat the mics. Let it cool and settle before testing.
4. Calibrate with a known source: a small speaker about 10 cm above the test bed, log sweep or pink noise, all 8 mics recording. Record once before the film goes on and once after; dividing each mic's after-spectrum by its own before-spectrum cancels the speaker, the position and the mic's sensitivity. Keep the level moderate so nothing clips.
5. Repeat a few hours later (film tension relaxes). Check the coherence between each mic's before and after recordings before trusting a ratio.
6. Pick the window and gap that give about 10 dB, print the wing with them, fit a per-mic correction from the calibration, and re-run the wind-tunnel test.

## Wing build notes (printed wing)

- **The array runs at an angle across the chord, not straight along it (user requirement, 2026-10-30).** Viewed from above (x chordwise, y spanwise), the flex is yawed so each port sits outside the wake of the ports upstream of it. The holes still point straight out of the surface.
  - **Angle:** a disturbance spreads downstream in a wedge of roughly 10° half-angle (typical turbulent-wedge figure, not measured here). At the 40 mm port pitch, a yaw of **15–20°** puts each port 10–14 mm to the side of the one before, clear of that wedge with margin. The Risø NACA0015 model used about 16° (`LITERATURE_wing_mounting_and_transition.md`, stagger recommendation).
  - **Monokote:** under the film the ports are flush and closed, so their wakes are much weaker. Keep the angle anyway.
  - **Fit on the 152.4 mm span:** the surface is a straight extrusion along the span, so it unrolls flat and the strip can lie along any straight line on it. At 20° the 300 × 14 mm strip covers about 287 mm of the 311 mm upper-surface arc and 116 mm of the span. The limit is about 27°. Check tip clearance and the tail's path around the nose when the wing is designed.
  - **The bench test bed** (`cad/airfoil_testbed/`) runs straight along the chord.
  - **NACA 4415 wing (2026-11-01):** the next test uses `Air Foil NACA 4415 Small Slot.step` (243.84 mm chord, 199 mm span, 260 mm upper arc). The 300 mm strip only fits at **36.5° or more**, using ~190 mm of span, so the 15–20° figure above no longer applies. Its bench rig is `cad/airfoil_testbed_4415/` (flex at 36.5°). The file's section is ~20% thick, not the 15% of a true 4415; check before printing the wing.
  - **Printed wing (2026-11-02):** `cad/wing_4415/` is the full wing, in two P1S halves split at the chord line, with the flex, the MMSA V2 board and the 2000 mAh battery inside. mic0 is left unpopulated: its stretch of strip and the tail run round the nose to the board, so there's no extension. That leaves about 256 mm of strip on the surface, so the flex fits at 28° (28–30° works). Board dimensions and the port size are still placeholders. See its README.
- **Next flex revision: use 0402 decoupling caps** (about 0.5 mm tall, below the 1.0–1.1 mm mic lid). The current 0805 10 µF caps are 1.4 mm tall, 0.3 mm above the lid. They force the skin over each mic to at least 0.8 mm; anything thinner opens the cap pocket through the surface, which is bad on an uncoated wing. ST recommends 100 nF + 1 µF at pin 1, and both come in 0402. That's fine for port acoustics, but its x/c positions differ from the angled layout.
- Print the skin outside face down so the surface is smooth. Cavity pockets and any grooves are then open on top, with no overhangs.
- Make a large interior cavity for the controller board and close it before installing. It does not need to be airtight but must have no direct path to the airflow. Any cable pass-through, USB or SD access, or panel needs a gasket or tape.
- Use a removable gasket ring (thin foam or double-sided tape) under each mic so the flex can be removed later.
- Optional: loose cotton in the interior damps its acoustic modes.

## Open questions

- The film's actual tension and attenuation (unmeasured, the coupon answers this).
- Film resonance and damping with Monokote adhesive (model assumed a Kapton-like film and moderate damping).
- Whether 6-10 dB removes enough clipping on mic1 (4.3% of samples at 60 mph). If not, tighten the window or increase the cavity.
- Tunnel speed versus time for takes 0010 and 0012 is still missing; see `FINDINGS.md`.
- No calibration script exists yet. It would generate a sweep WAV and compute each port's gain relative to the reference.

## Files

- `cad/airfoil_testbed/`: the test bed (generator, print files, STEP, README with the variant table).
- `tools/port_filter_model.py`: lumped model (hole divider and film variants).
- `tools/transition_band_search.py`: band search and ramp multiplot.
- `tools/overlay_flow_photos.py`: flow and array overlay.
