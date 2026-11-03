# Broadband PSD: steady Wing 30 versus Wing 60

## Suggested slide message

The spatial change is broadband. At steady 30 mph, mic0 and mic1 form the
high-energy region while mic2 follows the low-level microphones. At steady 60
mph, mic2 moves toward the mic0/mic1 spectral level across a wide frequency
range. This is not only a feature of the selected 4-8 kHz monitoring band.

## Signal processing

1. Use the steady `MMSA8_0011_Wing_30` and `MMSA8_0013_Wing_60` recordings.
2. Normalize 16-bit PCM samples by 32768 and skip the first 0.3 s.
3. Divide each recording into complete 2 s blocks.
4. In each block, calculate a one-sided Welch PSD using 2048-sample Hann
   segments, 1024-sample overlap, constant detrending, and a 2048-point FFT.
5. Plot the median PSD across blocks for each microphone from 20 Hz to 20 kHz.

The PSD unit is dBFS squared per hertz because the installed microphone and
port responses were not calibrated to pascals.

## Interpretation limit

Steady 60 mph mic0-mic2 contain full-scale samples, so their spectral amplitudes
and shapes are clipping-limited. Use that panel to show the qualitative spatial
expansion, not as a calibrated amplitude or spectral-slope result.
