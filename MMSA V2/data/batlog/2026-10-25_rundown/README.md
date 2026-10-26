# Battery run-down, 2026-10-25 (board 2, 1200 mAh cell)

`BATLOG.CSV` is the SD card's whole log. The run is the last boot section (40 of 40). `batlog_2026-10-25_rundown.png` is its plot (`tools/plot_batlog.py`).

- **Ran 6.55 h from boot**, recording 8 mics with Bluetooth connected for 6.47 h of that. It stopped itself at the 3.40 V cutoff (`# LOW BATTERY` line).
- The cell wasn't full: it read ~4.0 V once off USB (the charger stopped early with R2 = 10k).
- **Average current ~141–154 mA:** 141 mA is the bench measurement for recording + Bluetooth (`../../power/2026-10-24/`), and 154 mA (±20%) is the estimate from this log (`tools/batlog_analyze.py --mah 1200 --start-min 5 --offset-mv 90`: about 83% of 1200 mAh used). The run matches the bench number.
- At that rate a full 1200 mAh charge lasts ~7.8–8.5 h.
- Crossing times (board reading): 4.0 V 0.09 h, 3.9 V 0.83 h, 3.8 V 1.75 h, 3.7 V 2.60 h, 3.6 V 3.72 h, 3.5 V 5.17 h, 3.4 V 6.55 h. The last 0.1 V took 1.4 h, with no steep drop yet at the cutoff.
