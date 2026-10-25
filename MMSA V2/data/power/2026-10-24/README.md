# Battery shunt voltage, 2026-10-24

Voltage across a **1 Ω resistor in series with the battery + line** of the MMSA V2 board, logged with Scopy's voltmeter (`Channel_0_DC_RMS`, in volts in the CSVs). The values below and in the plots are in mV. Through a 1 Ω shunt, 1 mV corresponds to 1 mA of battery current, within the resistor's tolerance. Negative values mean current flowing into the battery (charging).

| File | Logged (local time) | What was running |
|---|---|---|
| `Power Measurements - Preliminary Test.csv` | 14:31–14:34 | First check of the setup |
| `Power Measurements - Idle (Nothing Running).csv` | 14:42–14:43 | Idle |
| `Power Measurements - Charging (Plugged into USB).csv` | 14:50–15:00 | USB plugged in, battery charging |
| `Power Measurements - Recording Only (No SD or BL).csv` | 15:02–15:06 | Stepped through the modes in the table below |

Averages worked out in the CSVs (the side columns of each file show which rows were selected):

| Condition | Average shunt voltage |
|---|---|
| Preliminary test | 73.8 mV |
| Idle (nothing running) | 75.3 mV |
| Charging battery | −97.6 mV (into the battery) |
| Baseline | 79.5 mV, and 79.8 mV when repeated at the end |
| Baseline + mics | 117.9 mV |
| Baseline + mics + Bluetooth | 141.1 mV |
| Baseline + Bluetooth | 102.9 mV |

The shunt drops 80–140 mV while the board runs, so the board ran slightly below the battery voltage.

## Plots

Made with `MMSA V2/tools/plot_power.py` (`python plot_power.py ../data/power/2026-10-24`):

- `power_2026-10-24.png`: every log over time, with the selected portions shaded and their means.
- `power_2026-10-24_stages.png`: the mean of each step of the recording-only log. The two baseline readings are pooled over all their samples (79.7 mV).
- `power_2026-10-24_vs_baseline.png`: each step's change from that baseline, in % and mV (charging left out).
