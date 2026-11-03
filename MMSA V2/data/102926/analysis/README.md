# Wind-tunnel analysis outputs

Processed 13 WAV file(s) with 100 ms Hann-windowed spectra.
Microphone labels are firmware labels (`mic0` through `mic7`).

## Files

- `window_levels.csv`: one row per analysis window and microphone.
- `run_summary.csv`: median, upper-percentile, relative-level, peak, and clipping metrics.
- `wing_zone_onsets.csv`: sustained entry into the high-level zone during each wing ramp.
- `session_overview.png`: median broadband level for every available take.
- `wing_profiles.png`: frequency-band profiles along the wing array (when wing WAVs are present).
- `wing_level_heatmaps.png`: absolute broadband level over time (when wing WAVs are present).
- `wing_broadband_psd.csv`: plotted median Welch PSD traces for every microphone in the steady 30 and 60 mph wing runs.
- `wing_peak_zone.png`: each mic relative to the loudest mic in that window; useful for seeing the high-level zone spread from mic0/mic1 toward mic2.

## Clipping

- take 0002 mic4: 1 samples
- take 0002 mic5: 2 samples
- take 0002 mic6: 1 samples
- take 0002 mic7: 1 samples
- take 0006 mic2: 1 samples
- take 0007 mic0: 6328 samples
- take 0007 mic1: 17216 samples
- take 0007 mic2: 22213 samples
- take 0007 mic3: 9552 samples
- take 0007 mic5: 4397 samples
- take 0007 mic7: 16213 samples
- take 0008 mic0: 6560 samples
- take 0008 mic1: 17990 samples
- take 0008 mic2: 25306 samples
- take 0008 mic3: 11236 samples
- take 0008 mic5: 4934 samples
- take 0008 mic7: 15105 samples
- take 0010 mic0: 25 samples
- take 0010 mic1: 824 samples
- take 0011 mic0: 18 samples
- take 0011 mic1: 524 samples
- take 0012 mic0: 36659 samples
- take 0012 mic1: 190351 samples
- take 0012 mic2: 92606 samples
- take 0013 mic0: 36279 samples
- take 0013 mic1: 125220 samples
- take 0013 mic2: 78662 samples

## Interpretation limit

These plots show recorded signal level, not a calibrated wall-pressure spectrum. A moving high-level region is consistent with a flow-regime change, but repeatability, tunnel-speed timing, microphone position, and sensitivity calibration are needed before labeling it as boundary-layer transition.
