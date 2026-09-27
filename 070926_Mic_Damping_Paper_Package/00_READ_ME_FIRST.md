# MEMS microphone damping results package

This package contains the graphs, tables, source spreadsheet, and analysis
summary for the 070926 ESP32 devkit microphone-covering test. The raw WAV
recordings are intentionally excluded to keep the package small.

## Folder contents

- `01_Paper_Summary`: reviewed takeaways, suggested manuscript wording, and
  experimental limitations.
- `02_Figures`: curated figure set with the exploratory coloration plots and
  relabeling-note text removed.
- `03_Tables_and_Source`: cleaned high-fan comparison table and the original
  test-label spreadsheet.
- `04_Interactive_Report`: self-contained HTML report containing the plotted
  metrics and spectra. Open it in a web browser.

## Most defensible result

Bare pop-filter fabric was the strongest candidate in this screening dataset.
Under the high-hairdryer condition, its recorded level was 12.5 dB lower over
100 Hz–16 kHz and 12.4 dB lower over 20–150 Hz than the lid-off recording.

## Interpretation note

These are preliminary screening results. The hairdryer was hand-positioned and
there was only one recording per configuration–stimulus combination. The
ambient-background comparison is not a controlled frequency-response test, and
the low-to-high plots do not demonstrate clipping or saturation headroom.
Consult `01_Paper_Summary/UNDERGRAD_PAPER_TAKEAWAYS.md` before using the figures
or wording in a manuscript.
