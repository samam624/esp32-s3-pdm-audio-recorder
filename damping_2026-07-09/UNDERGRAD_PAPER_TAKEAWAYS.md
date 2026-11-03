# MEMS microphone damping test: paper-ready takeaways

## Bottom line

This dataset is best presented as a **preliminary screening experiment**, not as
a final quantitative validation of damping performance. Among the nine tested
covering configurations, **bare pop-filter fabric was the strongest candidate
under the high-hairdryer condition**. Its recorded high-fan level was 12.5 dB
lower than the uncovered ("lid off") microphone over 100 Hz–16 kHz, and 12.4 dB
lower in the 20–150 Hz rumble band.

The pop-filter result is promising because the improvement appears in both the
broad analysis band and the low-frequency band most relevant to turbulence.
The next-best configurations were much weaker:

- Pop filter + electrical tape: 5.1 dB lower over 100 Hz–16 kHz, but only
  1.1 dB lower at 20–150 Hz.
- Bare Confor square pad: 5.0 dB lower over 100 Hz–16 kHz and 2.5 dB lower at
  20–150 Hz.
- All other configurations differed from the lid-off recording by less than
  about 3 dB over the full band.

Adding Scotch or electrical tape to either the pop-filter material or the
Confor pad did not improve the observed high-fan result relative to the
corresponding untaped material. This is a useful design trend to test again
under controlled conditions, but the present data are not sufficient to
establish tape as the cause.

## Suggested paragraph for the paper

> In a preliminary bench screening, nine microphone-covering configurations
> were evaluated using ambient, low-hairdryer, and high-hairdryer recordings,
> with the hairdryer serving as a proxy for turbulent airflow. Under the
> high-hairdryer condition, bare pop-filter fabric produced the lowest recorded
> noise level. Relative to the uncovered microphone, the pop-filter recording
> was 12.5 dB lower over 100 Hz–16 kHz and 12.4 dB lower over the 20–150 Hz
> rumble band. A bare Confor pad and pop-filter material reinforced with
> electrical tape produced smaller full-band reductions of approximately
> 5 dB, while their rumble-band reductions were only 2.5 and 1.1 dB,
> respectively. These results identify bare pop-filter fabric as the leading
> candidate for controlled follow-up testing. Because the acoustic source was
> hand-positioned and only one recording was collected for each
> configuration–stimulus combination, the measured differences should be
> interpreted as screening results rather than calibrated insertion-loss
> measurements.

Use "recorded level was lower" or "observed reduction" for these data. Avoid
calling the 12.5 dB value a definitive treatment effect until the result is
reproduced with a fixed source and replicate trials.

## Results table

The "observed difference" columns compare each high-fan recording with the
high-fan lid-off recording. Positive values mean the test recording was
quieter. These are relative digital recording levels (dB), not calibrated
sound-pressure levels (dB SPL).

| Configuration | High-fan file | High-fan level, 100 Hz–16 kHz (dBFS) | Observed difference vs. lid off, 100 Hz–16 kHz (dB) | Observed difference vs. lid off, 20–150 Hz (dB) |
|---|---:|---:|---:|---:|
| Pop filter | REC_00015 | -46.39 | +12.49 | +12.42 |
| Pop filter + electrical tape | REC_00019 | -38.97 | +5.06 | +1.12 |
| Confor square pad | REC_00022 | -38.94 | +5.03 | +2.45 |
| Scotch tape | REC_00012 | -34.64 | +0.74 | +1.06 |
| Pop filter + Scotch tape | REC_00016 | -34.55 | +0.64 | +1.78 |
| Confor + electrical tape | REC_00028 | -34.02 | +0.11 | +0.20 |
| Lid off (reference) | REC_00031 | -33.91 | 0.00 | 0.00 |
| Confor + Scotch tape | REC_00025 | -32.77 | -1.13 | +1.33 |
| Lid on | REC_00009 | -31.00 | -2.91 | +0.96 |

Differences below roughly 2–3 dB should not be ranked from this experiment.
The Confor pad and pop filter + electrical tape are effectively tied in
full-band level, although the Confor pad had the larger observed reduction in
the rumble band.

## Data-integrity finding

The spreadsheet labels do not match the acoustic content of all files.

- REC_00007 through REC_00012 are consistent with the recorded spreadsheet
  order: background, low fan, high fan.
- From REC_00016 through REC_00033, the acoustic levels show a repeated rotated
  order within each group: high fan, background, low fan. The analysis report
  appropriately corrected this order before calculating the high-fan table.
- REC_00013 and REC_00014 are both background-like and differ by only about
  0.4 dB over 100 Hz–16 kHz. Therefore, the report's assignment of REC_00013
  as the pop-filter low-fan take is not independently supported. The
  pop-filter low-to-high change should not be reported.

This ambiguity does not change the main high-fan comparison because
REC_00015—the spreadsheet's high-fan pop-filter recording—remains the high-fan
file used in the table.

## Claims that should not go into the paper yet

1. **Do not call the ambient-room comparison "frequency-response
   coloration."** Room tone is uncontrolled and close to the microphone noise
   floor. A true frequency-response comparison requires the same controlled
   broadband or swept source, fixed geometry, and preferably a reference
   microphone.

2. **Do not claim that a configuration increased saturation headroom.** No file
   clipped, and the high-fan peaks were below digital full scale. The
   low-to-high level difference is not a direct saturation measurement.

3. **Do not claim statistical significance.** There is only one recording per
   configuration–stimulus combination, so treatment variability and confidence
   intervals cannot be estimated.

4. **Do not interpret the lid-on result as evidence that the lid amplifies wind
   noise.** The source was hand-positioned, so the -2.9 dB relative result could
   reflect geometry or source variation.

5. **Do not use the lid-off low-to-high comparison.** REC_00033 has a roughly
   6 dB mismatch between its two recorded channels and unusually low
   interchannel correlation, unlike the other takes.

## Recommended validation experiment

Repeat the short list of (1) lid off, (2) bare pop-filter fabric, (3) bare
Confor pad, and (4) pop filter + electrical tape. Fix the microphone and source
in a jig; record source distance, angle, and fan setting; randomize treatment
order; and acquire at least 3–5 independent recordings per condition. Include
a no-wind loudspeaker sweep or pink-noise trial to measure speech-band
transmission separately from wind rejection. Report mean differences with
standard deviations or confidence intervals.

## Analysis provenance

The supplied report analyzed 27 WAV files (48 kHz, stereo, 16-bit PCM; about
16 seconds each) using Welch power spectral density, band-limited levels,
peak level, crest factor, and clipping fraction. An independent time-domain
audit confirmed the broad quiet/background versus fan-on classifications and
found no clipping. The dependency-free audit script is
`audio_level_audit.js`.
