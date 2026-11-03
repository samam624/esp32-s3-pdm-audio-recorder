# Slide 06: 2-7 kHz spectral metrics

## Purpose

This figure applies the spectral metrics used by Ozcakmak et al. to the MMSA
wing recordings. It is separate from the empirical band-selection result:
**4-8 kHz is the preferred monitoring band for this MMSA data set**, while
**2-7 kHz is retained here to reproduce the literature-style calculation**.

## Signal processing

1. Start with each 48 kHz, 16-bit microphone channel and normalize the PCM
   samples by 32768, so the waveform is expressed relative to digital full
   scale.
2. Skip the first 0.3 s and divide each steady recording into complete 2 s
   blocks.
3. Estimate a one-sided Welch power spectral density (PSD) in each block using
   2048-sample Hann segments, 1024-sample overlap (50%), constant detrending,
   and a 2048-point FFT. The frequency-bin spacing is 23.4375 Hz.
4. Keep the PSD bins from 2 to 7 kHz and numerically integrate with the
   trapezoidal rule.
5. Calculate one value of each metric per block and microphone. The points in
   the steady 30 and 60 mph plots are the median values across all complete
   2 s blocks.

## Band level, Lp

For one microphone and one 2 s block, let Sxx(f) be the one-sided PSD of the
full-scale-normalized waveform. The 2-7 kHz band power is

    P_2-7k = integral from 2 kHz to 7 kHz of Sxx(f) df

and the plotted band level is

    Lp = 10 log10(P_2-7k).

Because there is no installed microphone/port pressure calibration, this is
reported in **dBFS**, not dB SPL. A flat scalar calibration would shift every
Lp value vertically but would not change the chordwise shape. Microphone and
port frequency-response differences can still alter the shape.

## First spectral moment, f_mu

The first spectral moment is the PSD-weighted mean frequency within the same
2-7 kHz band:

    f_mu = [integral f Sxx(f) df] / [integral Sxx(f) df].

It is the spectrum's center of gravity, not a peak-frequency pick:

- Higher f_mu means a larger fraction of the 2-7 kHz energy lies toward the
  high-frequency end of the band.
- Lower f_mu means the energy is weighted toward the low-frequency end.
- A constant microphone gain cancels between numerator and denominator, but a
  non-flat frequency response does not.

The symbol is **f_mu** (f followed by the Greek letter mu), not "Fu."

## Plot interpretation and limitations

- Dots are the eight measured microphones. The smooth PCHIP curves are visual
  guides only and do not add spatial resolution.
- x/c uses the conventional airfoil coordinate: 0 is the leading edge and 1
  is the trailing edge.
- The 30 mph result is the cleaner quantitative comparison. At 60 mph,
  mic0-mic2 clip, which can increase high-frequency energy and bias both Lp and
  especially f_mu.
- These curves are acoustic transition proxies; they do not independently
  prove laminar or turbulent flow states.
