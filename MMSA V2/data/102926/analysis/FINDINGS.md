# Initial findings: October 29, 2026 wind-tunnel test

## Data and microphone health

- The canonical session contains 13 WAV files (takes 0001-0013), totaling 1,235,485,244 bytes.
- Every file is valid eight-channel, 16-bit PCM at 48 kHz.
- All eight microphones recorded continuous audio in the pre-installation check. Lag-1 continuity was 0.99 on every channel.
- Median broadband levels in the two pre-tests differed by only 0.97 dB and 0.91 dB, respectively, across all eight channels.
- All eight channels had the expected falling high-frequency quiet-floor shape. No dead, constant, or broadband-hiss channel was found.

This supports the conclusion that the array was operating correctly before installation.

## The wing high-level region is present in the data

The observed mic0/mic1-to-mic2 progression is strong and broadband, not limited to one narrow frequency band.

| Steady condition | mic0 median | mic1 median | mic2 median | mic2 below louder of mic0/mic1 |
|---|---:|---:|---:|---:|
| 30 mph | -10.8 dBFS | -7.6 dBFS | -34.7 dBFS | 27.1 dB |
| 60 mph | -7.5 dBFS | -8.6 dBFS | -12.3 dBFS | 4.7 dB |

At 30 mph, mic0 and mic1 form a sharply localized high-level region while mic2 remains at approximately the same level as mics3-7. At 60 mph, mic2 is only 4.7 dB below the loudest aft microphone and is 8.6 dB above the median of mics3-7. Across the five individual analysis bands, mic2 is 18.4-36.5 dB below the louder aft mic at 30 mph, but only 3.4-7.5 dB below it at 60 mph.

The ramp data shows the same sequence. Using a reproducible definition—within 6 dB of the loudest channel, with the loudest channel above -20 dBFS, sustained for at least two seconds—mic0 and mic1 are already in the high-level region at the start of take 0012, while mic2 enters it at **138.95 s**, 48.0% of the way through the 30-60 mph recording. Mics3-7 never meet that criterion during the ramp.

This confirms the spatial progression described during the test. It is consistent with a speed-dependent flow-regime change near the aft part of the wing, but it is not yet sufficient to identify boundary-layer transition. The exact tunnel speed at 138.95 s cannot be recovered without the ramp's speed-versus-time record.

Mic7 is also somewhat elevated at 60 mph (about 4.2 dB above the mic3-7 median). Because it is separated from the mic0-mic2 region, it should be checked as a possible array-end, leading-edge, tape, or local-geometry effect.

### Photographic comparison

The chord-normalized overlay places the measured fluorescent line at `x/c = 0.44` (half-maximum width 0.42-0.48) from the aft edge. Mic2 sits at `x/c = 0.42` and mic3 at `0.51` (measured from the mic ports in the array photo), so the line lies in the mic2-mic3 interval, just forward of mic2, where the recorded 60 mph level drops (8.7 dB broadband, 17 dB in the 4-8 kHz band). Registration uses the measured wing edges in both photos (the earlier version had the flow-photo aft edge about 65 px off, which biased the band to 0.43-0.50) and rectifies the array photo row by row. Spanwise position and camera perspective remain approximate.

### Best band for the boundary

`transition_band_search.py` compares 1/3-octave bands. Broadband hides the boundary because low-frequency tunnel noise is similar on every mic and rises with speed (the 125-500 Hz step shrinks from 23 dB at 30 mph to 9 dB at 60 mph). Above 2 kHz the quiet side stays flat and the step stays large. **Recommended watch band: 4-8 kHz** (step 35 dB at 30 mph, 17 dB at 60 mph, minimum 15 dB in any 1/3 octave; quiet side more than 25 dB above the tunnel-off floor). In the 30-60 mph ramp, mic2 switches into the high-level state as a sharp rise at about 70-130 s. The 8-16 kHz band has the largest raw step (min 20 dB) but the quiet side is within 13-16 dB of the floor at 30 mph and mic0-mic2 clip at 60 mph, which adds high-frequency distortion, so use it only as a cross-check. See [`transition_band_search.png`](transition_band_search.png) and its CSV.

## Clipping limits the high-speed amplitude result

Exact full-scale samples occur primarily in the same aft high-level region:

| Wing condition | mic0 clipped | mic1 clipped | mic2 clipped |
|---|---:|---:|---:|
| 0-30 mph ramp | 0.0002% | 0.0078% | 0% |
| Steady 30 mph | 0.0006% | 0.0178% | 0% |
| 30-60 mph ramp | 0.2641% | 1.3713% | 0.6671% |
| Steady 60 mph | 1.2362% | 4.2668% | 2.6803% |

The steady 60 mph signals on mic0, mic1, and mic2 are therefore saturated often enough that their absolute amplitudes and spectra are not fully quantitative. The relative spatial conclusion remains visible before and outside clipped samples, but the high-speed levels should be treated as lower bounds. The floor test also clips substantially at 60 mph on most uncovered microphones.

## Pop-filter material had a large, frequency-dependent effect

On the tunnel floor, mic4 and mic6 were covered and the other microphones were uncovered. Relative to the median uncovered microphone:

- At 30 mph, broadband attenuation was 4.9 dB on mic4 and 4.7 dB on mic6.
- At 60 mph, broadband attenuation was 7.4 dB on mic4 and 9.2 dB on mic6.
- The effect was much stronger above 500 Hz: approximately 12-18 dB attenuation from 500 Hz to 8 kHz at 30 mph, more than 20 dB from 2-8 kHz at 60 mph, and about 34 dB from 8-20 kHz at 60 mph.
- The 20-125 Hz band was not attenuated consistently and was sometimes higher on the covered microphones, suggesting low-frequency flow/material motion or a nonuniform floor flow field.

These are preliminary single-run comparisons, but they show that the material changes both level and spectral shape enough that covered and uncovered wing microphones should not be compared as though they have the same transfer function.

## Most useful next information

1. Tunnel speed versus recording time for takes 0010 and 0012, especially the speed at 138.95 s in take 0012.
2. Mic0-mic7 distances from the wing leading edge and the direction of increasing mic number.
3. The precise definition of the approximately 40-degree installation angle, plus chord and angle of attack.
4. Whether the post-run physical inspection found loose tape, blocked ports, or damaged microphones.
5. Repeat wing runs at 30 and 60 mph. Repeats are necessary to distinguish a stable aerodynamic boundary from mounting or run-to-run effects.
6. A high-speed measurement configuration that avoids overload, followed by an acoustic transfer calibration of each installed port.

## Output guide

- [`wing_peak_zone.png`](wing_peak_zone.png) most directly shows the mic0/mic1-to-mic2 expansion.
- [`flow_array_overlay_60mph.png`](flow_array_overlay_60mph.png) aligns the two photographs on a shared x/c axis and shows the measured fluorescent line, mic positions, and level profiles at 30 and 60 mph.
- [`transition_band_search.png`](transition_band_search.png) and [`transition_band_search.csv`](transition_band_search.csv) show which frequency band best separates the high-level region.
- [`wing_level_heatmaps.png`](wing_level_heatmaps.png) shows absolute broadband level over time.
- [`presentation/17_wing_30_60_broadband_psd.png`](presentation/17_wing_30_60_broadband_psd.png) compares the full steady 30 and 60 mph spectra for all eight microphones; [`wing_broadband_psd.csv`](wing_broadband_psd.csv) contains the plotted values.
- [`wing_profiles.png`](wing_profiles.png) compares the frequency-band profile along the array.
- [`session_overview.png`](session_overview.png) compares every take and microphone.
- [`wing_zone_onsets.csv`](wing_zone_onsets.csv) contains the reproducible onset calculation.
- [`run_summary.csv`](run_summary.csv) and [`window_levels.csv`](window_levels.csv) contain the processed values.
- [`interactive`](interactive/) contains zoomable RMS/peak timelines for the steady-30, 30-60 ramp, and steady-60 wing recordings. These viewers remove the local DC value before reporting their acoustic envelope; use `run_summary.csv` for raw digital peaks and clipping percentages.

