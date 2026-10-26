# MMSA V2 update, 2026-10-25

## 1. A sound source moved along the 8-mic array

`1_array_levels_tone_vs_noise.png`

Each row is one mic (mic0 to mic7, 39.5 mm apart in a line). The shading is that mic's level in 1–16 kHz above its own noise floor, so the dark band shows where the sound was over time. The source was a speaker held about 30 mm from the mics.

- **Top, 1 kHz tone:** moved from mic0 to mic7 at about 32 mm/s.
- **Bottom, white noise:** moved from mic0 to mic7 at about 21 mm/s, then back at about 43 mm/s.

Both plots use the same 1–16 kHz band, so we don't need to know the source's frequency in advance. For the noise, the arrival-time differences between mics also give the source's position and its distance from the mic line (about 30 mm on both passes). A pure tone can only be followed by level: room reflections dominate its phase across the array.

## 2–4. Board current in each configuration (measured 2026-10-24)

Measured as the voltage across a 1 Ω resistor in series with the battery's + line. Baseline is the board on but not recording, with Bluetooth off. "+ mics" is the board recording to the SD card (card in, REC LED blinking).

| Configuration | Voltage across the resistor | Change from baseline |
|---|---|---|
| Baseline | 79.7 mV | |
| Baseline + Bluetooth | 102.9 mV | +29% |
| Baseline + mics | 117.9 mV | +48% |
| Baseline + mics + Bluetooth | 141.1 mV | +77% |
| Charging from USB | −97.6 mV (current into the battery) | |

- `2_current_draw_by_config.png`: the average voltage in each configuration.
- `3_current_draw_vs_baseline.png`: each configuration's increase over baseline.
- `4_current_draw_logs.png`: the raw logs over time, with the averaged stretches shaded.
