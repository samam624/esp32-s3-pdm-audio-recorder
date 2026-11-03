# Ozcakmak paper metrics applied to the 2026-10-29 wing data

## What was calculated

The one-sided Welch PSD uses the paper's 2048-point Hann windows, 50% overlap, and 2-7 kHz integration band. Each plotted time sample is a two-second Welch average. `Lp` is reported in dBFS because the installed microphone/port transfer functions were not calibrated to pascals. `f_mu` is the PSD-weighted mean frequency within 2-7 kHz.

The transition proxy is the adjacent microphone pair with the largest positive chordwise slope. The bracket, rather than the interpolation's visual midpoint, is the defensible spatial resolution.

## Results

- **30 mph:** maximum `Lp` slope lies between mic2 and mic1, `x/c = 0.581-0.675` (midpoint 0.628). Across that pair, `Lp` rises 29.4 dB and `f_mu` changes 0.20 kHz. Clipping is 0.000%/0.018% on the two sides.
  The maximum `f_mu` slope is between mic3 and mic2, `x/c = 0.486-0.581`, with a rise of 0.27 kHz.
- **60 mph:** maximum `Lp` slope lies between mic3 and mic2, `x/c = 0.486-0.581` (midpoint 0.533). Across that pair, `Lp` rises 14.3 dB and `f_mu` changes 0.81 kHz. Clipping is 0.000%/2.678% on the two sides.
  The maximum `f_mu` slope is between mic3 and mic2, `x/c = 0.486-0.581`, with a rise of 0.81 kHz.

At 30 mph the `f_mu` location is one microphone interval ahead of the `Lp` location: the spectral centroid rises across mic3-mic2, while total 2-7 kHz energy makes its large jump across mic2-mic1. This is consistent with mic2 being in an earlier spectral-change/transition stage before the high-energy state at mic1, but it needs repeat runs and port-response calibration before being treated as an aerodynamic fact.

The 30 mph `Lp` profile also has the paper's expected peak-and-settle shape: mic1 is the maximum, then the farther-downstream mic0 drops 3.5 dB while remaining 26.3 dB above the leading-side median. If the `f_mu` rise is treated as transition onset and the `Lp` rise/peak as its later stage, the candidate zone spans approximately `x/c = 0.486-0.675` (`0.188c`). That matches the paper's common 15-20% chord transition length, but this interpretation is provisional.
- In the 30-60 mph ramp, the maximum-`Lp` bracket first remains at the mic3-mic2 interval for at least 6 s beginning near **99.3 s**. Tunnel speed was not synchronized, so this cannot be converted reliably to mph.

The 60 mph flow-visualization line previously measured at aft-edge coordinate `x/c = 0.42-0.48` converts to conventional leading-edge coordinate `x/c = 0.52-0.58`, overlapping the 60 mph mic3-mic2 acoustic bracket (`0.486-0.581`).

## Interpretation limits

- These are paper-style **transition proxies**, not proof of laminar and turbulent states. There is one run per steady speed and no independent hot-film/IR/oil-flow truth measurement.
- The 30 mph result is the cleaner quantitative case. At 60 mph, mic0-mic2 clip; clipping raises high-frequency spectral content and can bias both `Lp` and `f_mu`.
- The eight microphones cover only `x/c = 0.111-0.764`. A transition zone narrower than one microphone spacing is unresolved; interpolation does not add physical resolution.
- `f_mu` rejects scalar sensitivity mismatch but not microphone/port frequency-response mismatch. An installed-port acoustic calibration is still needed.
- Absolute values cannot be compared with the paper's dB SPL table until pressure calibration is available.

## Plot guide

- `paper_metrics_spatial.png`: closest equivalent to the paper's chordwise `Lp` and `f_mu` plots.
- `paper_metric_derivatives.png`: the measured adjacent slopes used to select each transition bracket.
- `paper_metrics_ramp_map.png`: equivalent to a time/chord spectrogram, with the `Lp` max-slope bracket tracked through the ramp.
- `paper_metrics_before_after_psd.png`: spectra on the immediately leading and trailing sides of the measured break.
