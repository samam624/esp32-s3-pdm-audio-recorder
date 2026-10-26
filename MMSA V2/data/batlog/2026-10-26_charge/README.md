# Battery charge, 2026-10-26 (board 2, 1200 mAh cell)

`BATLOG.CSV` is the SD card's whole log. Its first 3457 lines are `../2026-10-25_rundown/BATLOG.CSV`; the charge is the last boot section (41 of 41), plugged in on USB straight after the run-down's cutoff. `batlog_2026-10-26_charge.png` is its plot (`tools/plot_batlog_charge.py`).

- **Full in 2.58 h** from 3.50 V (board reading). The charger stopped at 4.10 V on the board, ~4.19 V allowing for the ADC reading ~90 mV low.
- The voltage climbs straight to the stop with no flat constant-voltage tail, which fits the charger stopping early with R2 = 10k.
- The charger topped up twice, about 4 min each, at 2.81 h and 5.63 h. After that the board sat at ~4.01 V (~4.10 V) until the log ended at 10.16 h.
- The board was idle the whole time (not recording, Bluetooth off).
