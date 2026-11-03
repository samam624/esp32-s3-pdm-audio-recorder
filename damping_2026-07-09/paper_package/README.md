# MEMS microphone damping results package

Curated figures from the 070926 ESP32 devkit microphone-covering test.
Source data, analysis scripts, the full report and the raw WAVs are in the
parent folder (`../`):

- `figures/`: curated figure set (exploratory coloration plots removed).
- `../UNDERGRAD_PAPER_TAKEAWAYS.md`: reviewed takeaways, suggested wording, limitations.
- `../paper_high_fan_metrics.csv` and `../70926 ESP32 Devkit Test.xlsx`: tables and test labels.
- `../mic_damping_report.html`: self-contained interactive report (open in a browser).

## Most defensible result

Bare pop-filter fabric was the strongest candidate in this screening dataset.
Under the high-hairdryer condition, its recorded level was 12.5 dB lower over
100 Hz–16 kHz and 12.4 dB lower over 20–150 Hz than the lid-off recording.

## Interpretation note

These are preliminary screening results. The hairdryer was hand-positioned and
there was only one recording per configuration–stimulus combination. The
ambient-background comparison is not a controlled frequency-response test, and
the low-to-high plots do not demonstrate clipping or saturation headroom.
Consult `../UNDERGRAD_PAPER_TAKEAWAYS.md` before using the figures or wording
in a manuscript.
