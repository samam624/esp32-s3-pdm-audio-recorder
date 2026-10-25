# Microphones on a wing for transition and separation: literature notes

Compiled 2026-10-25 for the MMSA V2 wing work: how to mount the microphones so they don't trip the flow or clip, and how the published work detects laminar-to-turbulent transition and separation from surface-pressure signals. Sources are listed at the end. Numbers marked *estimate* are worked out here from the sources plus stated assumptions; check them against your tunnel speed, chord and the real mounting.

## Bottom line

1. **The mount can create the flow it's trying to measure.** A step or bump on a laminar boundary layer trips it to turbulent once its height passes a critical Reynolds number (about U·h/ν ≈ 900 for a backward-facing step, ≈ 1,800 for a forward-facing step). The IMP34DT05 package alone is 1 mm tall, which is above both limits at 20 m/s. Sensors on top of the surface will likely see a turbulent boundary layer everywhere behind the first one. The published arrays are flush: sensors inside the model behind small holes, or a thin flex board under a face sheet with cut-outs.
2. **Clipping is a real risk above about 30–40 m/s.** The IMP34DT05 reaches digital full scale at about 120 dB SPL. Turbulent wall-pressure RMS is about 0.006 × dynamic pressure, so the peaks reach full scale around 40 m/s. That's sooner near the suction peak, in separated flow, or where vortices hit. Hence the clip counter in the firmware.
3. **Every pinhole/cavity mount is a resonator and needs in-situ calibration.** Keep the cavity tiny so the resonance sits above the band of interest. Calibrate each channel in place, since an uncorrected response adds false spectral humps and hides real ones.
4. **The simplest robust transition marker is where the pressure-fluctuation RMS peaks along the chord.** It also works on a pitching airfoil. Spectral cues add detail: instability-wave peaks, then a broadband hump, then a turbulent spectrum.
5. **For a rotating or pitching wing, log the angle against the audio.** Transition location shows hysteresis, so the same angle gives a different transition point on the way up and on the way down.

## 1. Don't trip the boundary layer you're measuring

**Step criteria.** For 2D surface steps, the critical step Reynolds number Re_h = U∞·h/ν is about 900 for backward-facing steps, 1,800 for forward-facing steps, and 15,000 for gaps (Nenni & Gluyas 1966). Later flight tests allowed forward-facing steps up to 3,600 [Step-1]. A 2023 flat-plate study found the step-Reynolds-number idea works cleanly for backward-facing steps but not for forward-facing ones, where there seems to be no single critical value [Step-1].

*Estimate,* with ν = 1.5×10⁻⁵ m²/s, using freestream velocity:

| U∞ | Backward-facing step (900) | Forward-facing step (1,800) | Forward-facing, flight-test limit (3,600) |
|---|---|---|---|
| 10 m/s | 1.35 mm | 2.7 mm | 5.4 mm |
| 20 m/s | 0.68 mm | 1.35 mm | 2.7 mm |
| 30 m/s | 0.45 mm | 0.90 mm | 1.8 mm |
| 40 m/s | 0.34 mm | 0.68 mm | 1.35 mm |

The IMP34DT05 is a 3 × 4 × 1 mm package (datasheet). Add the flex (as thin as 0.1 mm for polyimide [Flex-1]) and adhesive, and a strip on top of the skin stands about 1.1–1.4 mm proud. The aft edge of the strip acts as a backward-facing step, the most sensitive case. Velocities on a wing's suction side exceed freestream, which lowers these heights further. Treat the table as order-of-magnitude.

**Isolated roughness** (each mic package is a 3D bump). Braslow and Knox's method predicts the critical height of roughness from a roughness Reynolds number built on the local laminar velocity at the roughness height [Rough-1]. Measured critical values range from about 250 to 600 for Mach numbers up to 2 [Rough-2]. Roughness below the critical height has no effect on natural transition. Taller roughness causes premature transition [Rough-3]. Distributed roughness lowers the critical value compared with isolated elements [Rough-4].

**What the instrumented models in the literature did:**
- **LM Wind Power / Risø NACA0015** (0.9 m chord, 30–50 m/s): microphones *flush-mounted beneath the surface*, reading through surface pressure holes. Some were connected through tubing that needed its own calibration. The chordwise microphones were also offset spanwise: z = 615 → 655 mm for x/c = 0.83 → 0.98. Zig-zag tape at 5% chord forced transition on comparison runs [Risø-1].
- **NASA Langley MEMS arrays:** polyimide flex boards (down to 0.1 mm) bonded to the tunnel surface and covered by a glass/epoxy face sheet with a cut-out per microphone. The microphones are flush and the outer surface is smooth, including on curved surfaces [Flex-1].
- **Rotating fan blade** (Rozenberg, in [Roger]): small Knowles microphones in tubes inside resealed grooves, each reading through a 0.6 mm pinhole. This is the closest precedent to a self-contained recorder riding on a rotating part.
- **TU Delft / Torino wing sleeve:** a flexible PCB carrying MEMS microphones and pressure sensors on a NACA 63₃-018 wing. It detected a laminar separation bubble and propeller tip-vortex traces [Sleeve-1, Sleeve-2]. The search didn't surface its thickness or how flush it is, so get the paper for those details.
- Limiting the number of sensors is also cited as a way to avoid tripping the boundary layer or disturbing sensors further downstream [Wake-1].

## 2. Don't clip: dynamic range

**The sensor.** IMP34DT05 sensitivity is −26 dBFS at 94 dB SPL, so 0 dBFS (full-scale sine) ≈ 120 dB SPL ≈ 20 Pa RMS, or 28 Pa instantaneous peak. The acoustic overload point is 122.5 dB SPL (datasheet).

**The load.** Willmarth measured turbulent-boundary-layer wall-pressure RMS at about 0.006 of the freestream dynamic pressure, independent of Mach and Reynolds number (an earlier campaign gave 0.0035) [TBL-1].

*Estimate,* with ρ = 1.2 kg/m³, p_rms = 0.006·q, and peaks assumed at 4–5 × RMS:

| U∞ | q | p_rms | Level | Peaks | vs. 28 Pa full scale |
|---|---|---|---|---|---|
| 20 m/s | 240 Pa | 1.4 Pa | 97 dB SPL | 6–7 Pa | fine |
| 30 m/s | 540 Pa | 3.2 Pa | 104 dB SPL | 13–16 Pa | about 5 dB to spare |
| 40 m/s | 960 Pa | 5.8 Pa | 109 dB SPL | 23–29 Pa | at the limit |
| 50 m/s | 1,500 Pa | 9.0 Pa | 113 dB SPL | 36–45 Pa | clipping |

**It gets worse locally.** Suction-side dynamic pressure can be well above freestream, and separated or vortex-impinging flow is louder still. Roger reports electret microphones with about 120 dB saturation working on a high-lift model, but not near an airfoil leading edge hit by rod vortices, where levels went "largely exceeding the 120 dB". For very high levels, Kulite sensors replace microphones. Roger also notes that a remote microphone's tube attenuation can be used deliberately to avoid saturation [Roger]. A digital MEMS array under a turbulent boundary layer up to 50 m/s reported no acoustic overload [MEMS-2], but that used a different microphone. Don't assume the IMP34DT05 does the same.

**So:** monitor clipping per channel during runs (firmware clip counter and live peak meter, in progress), and plan speeds with the table above.

## 3. Pinholes, cavities and calibration

- **Helmholtz resonance.** A pinhole over a cavity is a resonator: f_R = (c₀ / 2π)·√(A / (V·L_e)), where A is the neck area, L_e the effective neck length (the skin thickness plus end corrections) and V the cavity volume [Roger]. *Estimate:* a 0.5 mm hole through 1 mm of skin (L_e ≈ 1.4 mm) gives about 14 kHz over a 2 mm³ cavity but about 6 kHz over 10 mm³. Keep the volume between the hole and the microphone's port as small as possible. Typical holes in the literature are 0.3 mm (Knowles microphones near a NACA0012 trailing edge [Pin-1]), 0.5 mm [Roger] and 0.6 mm (Rozenberg [Roger]).
- **Flow changes the resonance.** The amplitude and frequency of a pinhole sensor's Helmholtz resonance shift with boundary-layer conditions, so a calibration done without flow may not hold. The resonance can be strongly amplified when it coincides with a cavity (Rossiter) mode [Pin-2]. Longer front cavities over a MEMS microphone reduce levels above a few hundred Hz [Pin-3].
- **Spatial averaging.** A sensing area that's large compared with the boundary layer's small eddies averages them away. A sensor with d⁺ ≈ 50 showed strong high-frequency loss and about 27% lower RMS. The Corcos correction compensates only partly [Res-1, Res-2]. Small holes resolve more.
- **In-situ calibration** (Roger's procedure): a small loudspeaker drives a 1 cm tube containing a reference ¼″ microphone. It's placed over each pinhole in turn, then over a flush reference, and the ratio of the two transfer functions gives each channel's response. Above a few kHz, a spark source compared against a flush reference gives the high-frequency response. In Roger's example, a pinhole–cavity response is flat to about 3 kHz, then peaks at the Helmholtz resonance [Roger]. The calibrator's own geometry can add spurious resonances, and corrections exist [Cal-1].
- **Why it matters.** In Roger's NACA-0012 example at 30 m/s, the uncorrected spectra showed humps from the probe itself. After correction, the real instability-wave content appeared as a broad bump near 4 kHz [Roger].

## 4. Detecting transition and separation

- **The RMS peak.** Transition is where the pressure-fluctuation RMS peaks along the chord. Thirty flush Kulite sensors on a pitching OA209 airfoil showed this static-airfoil criterion still works while pitching [Pitch-1]. A flat-plate study with a row of embedded microphones also located transition from the RMS [Plate-1].
- **Rise in spectral level.** The LM Wind Power campaigns detected transition from an increase in the mean of the Fourier spectrum, described as numerically very stable, and also tracked Tollmien–Schlichting frequencies [Risø-2].
- **Spectral stages.** The primary instability (Tollmien–Schlichting waves) appears as peaks in the wall-pressure spectrum. The secondary instability appears as a broad hump, before the fully turbulent spectrum [RMP-1].
- **Laminar separation bubbles.** Reported signatures include a high-frequency peak from the bubble's size and position oscillating, several equally spaced tones, and humps and peaks in the spectrum just downstream of the bubble. A pressure-side bubble near the trailing edge can drive tonal noise through an acoustic feedback loop [LSB-1]. A plateau in the mean pressure also marks a bubble, but these microphones can't measure mean pressure.
- **Pitching and dynamic stall.** With eight closely spaced hot-film sensors on an oscillating NACA 0012, transition and the boundary layer's state were tracked through the cycle. The transition location traced a hysteresis loop whose shape depends on reduced frequency and mean angle [Pitch-2]. Time–frequency analysis of hot-film signals has been used to find both transition onset and relaminarization [Pitch-2]. Pitching shows wider hysteresis than plunging at large mean angles [Pitch-3].
- **A caveat.** Different methods can disagree on separation location. Validate against an independent method: oil-flow or infrared thermography, or trip tape for a known turbulent case [LSB-1, Risø-1].

## 5. What this suggests for the MMSA mount

1. **Make it flush.** Recess the flex strip into the skin so the microphone lids sit flush, or put the microphones inside the wing behind 0.3–0.6 mm holes. Fair and seal the edges, measure the remaining steps, and compare them with the table in section 1 for your speed.
2. **Stagger the chordwise microphones spanwise,** so each one isn't in the wake of the one upstream. The Risø model did this.
3. **Keep each hole-to-microphone cavity a few mm³ and calibrate every channel in place.** Repeat a check with flow if you can.
4. **Watch for clipping on every run,** and budget speed against the table in section 2.
5. **Leave the ports uncovered for transition work.** Fabric or foam wind-noise treatments attenuate exactly the boundary-layer pressure you want to see, and can disturb the boundary layer themselves.
6. **Record the wing angle with sample-accurate sync,** to separate pitch-up from pitch-down behaviour.
7. **Validate with trip tape:** compare a tripped run against a clean one, and check against oil flow or infrared if available.

## Gaps found

- No paper found using the IMP34DT05 (or a similar ~120 dB SPL MEMS part) for wall pressure on a wing, so its behaviour in flow needs your own calibration and tests.
- No source found that applies intermittency statistics (burst fraction, kurtosis) to microphone signals for transition. That's done with hot-films and is worth trying on the MMSA data.
- Forward-facing step criteria vary between datasets (1,800–3,600, and possibly no unique value).

## Sources

- [Roger] M. Roger, *Microphone Measurements in Aeroacoustic Installations*, NATO STO-EN-AVT-287, lecture 3. https://publications.sto.nato.int/publications/STO%20Educational%20Notes/STO-EN-AVT-287/EN-AVT-287-03.pdf
- [Risø-1] F. Bertagnolio, *Boundary Layer Measurements of the NACA0015 and Implications for Noise Modeling*, Risø-R-1761(EN), 2011. https://www.osti.gov/etdeweb/servlets/purl/1004722
- [Risø-2] M. Doessing, *High frequency microphone measurements for transition detection on airfoils*, Risø-R-1645(EN), 2008. https://www.osti.gov/etdeweb/biblio/932280
- [Step-1] Forward/backward-facing step and gap criteria, critical step Reynolds numbers: https://link.springer.com/article/10.1007/s00348-023-03614-x ; NASA: https://ntrs.nasa.gov/api/citations/20190028838/downloads/20190028838.pdf
- [Rough-1] Braslow & Knox, simplified method for the critical height of distributed roughness: https://digital.library.unt.edu/ark:/67531/metadc57502/
- [Rough-2] NASA, roughness effects on boundary-layer transition: https://ntrs.nasa.gov/api/citations/19660023725/downloads/19660023725.pdf
- [Rough-3] NASA TN D-3384: https://ntrs.nasa.gov/api/citations/19660023650/downloads/19660023650.pdf
- [Rough-4] Distributed roughness spacing, JFM: https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/boundary-layer-transition-due-to-distributed-roughness-effect-of-roughness-spacing/949313A4248D97BCD4EC0400A123F266
- [Flex-1] NASA Langley, *Arrays of Miniature Microphones for Aeroacoustic Testing*, NASA Tech Briefs, Feb 2007. https://www.techbriefs.com/component/content/article/1168-lar-17171-1
- [MEMS-1] *Road to Acquisition: Preparing a MEMS Microphone Array for Measurement of Fuselage Surface Pressure Fluctuations*, Micromachines 12(8):961, 2021. https://doi.org/10.3390/mi12080961
- [MEMS-2] *A new MEMS microphone array for the wavenumber analysis of wall-pressure fluctuations*. https://www.researchgate.net/publication/333195749
- [MEMS-3] Sanders, De Santana, Azarpeyvand, Venner, *Unsteady surface pressure measurements on trailing edge serrations based on digital MEMS microphones*, AIAA 2018-3290. https://research-information.bris.ac.uk/en/publications/unsteady-surface-pressure-measurements-on-trailing-edge-serration/
- [Sleeve-1] *Unsteady surface pressure measurements of propeller–wing interaction with a MEMS-embedded sleeve*, Aerospace Science and Technology 175, 2026. https://www.sciencedirect.com/science/article/pii/S1270963826003603 (record: https://iris.polito.it/handle/11583/3008045)
- [Sleeve-2] P. Dutta, TU Delft MSc thesis, 2025 (flexible PCB with microphones and pressure sensors). https://repository.tudelft.nl/
- [TBL-1] Willmarth, wall-pressure fluctuations beneath a turbulent boundary layer (NASA Memo 3-17-59W; NACA TN 4139). https://ntrs.nasa.gov/api/citations/19930084980/downloads/19930084980.pdf
- [Pin-1] NACA0012 with Knowles FG-23329-P07 microphones under 0.3 mm pinholes: https://arxiv.org/pdf/2108.01897
- [Pin-2] *Flow Effect on Helmholtz Resonance of Pinhole-Mounted Wall Pressure Sensors*, AIAA Journal. https://arc.aiaa.org/doi/10.2514/1.J064522
- [Pin-3] Tubular front cavity for wind-noise suppression in MEMS microphones: https://pmc.ncbi.nlm.nih.gov/articles/PMC13029217/
- [Res-1] Transducer resolution effect on pressure fluctuations beneath hypersonic turbulent boundary layers (Sandia, 2024): https://www.sandia.gov/research/publications/details/transducer-resolution-effect-on-pressure-fluctuations-beneath-hypersonic-tu-2024-01-11/
- [Res-2] Resolution and structure of the wall-pressure field beneath a turbulent boundary layer, JFM: https://core-cms.cambridgecore.org/core/journals/journal-of-fluid-mechanics/article/resolution-and-structure-of-the-wall-pressure-field-beneath-a-turbulent-boundary-layer/91DA9728E5B918C6AC4EB843125D1DF1
- [Cal-1] Calibration of remote-microphone probes and calibrator artefacts (Exp. Fluids 2023): https://link.springer.com/article/10.1007/s00348-023-03630-x
- [RMP-1] *Study of the development of a boundary layer using the remote microphone probe technique*, University of Twente, 2023. https://research.utwente.nl/en/publications/study-of-the-development-of-a-boundary-layer-using-the-remote-mic/
- [Plate-1] Embedded microphone row for transition location on a flat plate, J. Mechanics Engineering and Automation 7 (2017) 221–234. https://pdfs.semanticscholar.org/6b0d/2a7a6a6330e7ecb7b39c8de6a3e3343cd737.pdf
- [Pitch-1] Unsteady transition on a pitching OA209 airfoil with dynamic pressure sensors, J. Mech. Sci. Technol., 2016, doi:10.1007/s12206-016-0928-5. https://www.researchgate.net/publication/309280968
- [Pitch-2] Dynamic stall with hot-wire/hot-film measurements, NASA: https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/19830009234.pdf ; oscillating airfoil flow, JFM: https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/abs/investigation-of-flow-over-an-oscillating-airfoil/2B4B4BBD890CB2DA0085DC8ABC75674A
- [Pitch-3] Transitional boundary layer over an airfoil in combined pitch–plunge motions: https://www.researchgate.net/publication/338561620
- [LSB-1] Laminar separation bubbles and tonal noise: https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/abs/laminar-separation-bubble-development-on-an-airfoil-emitting-tonal-noise/76574ABB1894AFFDADC429B498CB0D1A ; near-stall SD7003: https://arxiv.org/pdf/2307.02109 ; turbulence-intensity effects: https://kurelek.smithengineering.queensu.ca/wp-content/uploads/2024/10/Istvan-Kurelek-Yarusevych_2018_Turbulence-Intensity-Effects-on-Laminar-Separation-Bubbles-Formed-over-an-Airfoil.pdf
- [Wake-1] Limiting sensor count to avoid tripping or disturbing downstream measurements (Wind Energy Science preprint, 2024): https://wes.copernicus.org/preprints/wes-2024-4/wes-2024-4.pdf
- IMP34DT05 datasheet (in this repo): `datasheets/IMP34DT05.pdf`
