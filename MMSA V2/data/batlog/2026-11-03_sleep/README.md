# Deep-sleep battery log, read 2026-11-03 (board 2, 1200 mAh cell assumed)

`BATLOG.CSV` is the SD card's whole log (copied from `ESP32_devkit_test/BATLOG.CSV`). The plot is `batlog_2026-11-03_sleep.png`, made with `tools/plot_batlog_sleep.py`.

- The log has no clock times, so it can't tell how long each sleep lasted. The plot shows the awake periods in order and draws each sleep as a break. The voltage change across a sleep is the wake reading minus the reading just before sleep.
- Seven BOOT-hold sleeps. Only two show a drop beyond the readings' scatter (~±10 mV):
  - Sleep 2: 4111 → 4087 mV (−24 mV, ≈24 mAh at ~1 mV/mAh).
  - Sleep 6: 3925 → 3900 mV (−25 mV, ≈34 mAh at ~0.74 mV/mAh). This looks like the multi-day sleep: the board was then woken for under 30 s and put back to sleep (sleep 7, 3897 mV, no wake logged).
- The mV per mAh comes from the slope of the 2026-10-25 run-down of the same cell. Each mAh figure is uncertain by roughly ±15 mAh.
- Average sleep current = mAh ÷ hours asleep. For sleep 6: 2 days ≈ 0.7 mA, 3 days ≈ 0.47 mA, 4 days ≈ 0.35 mA. **To do: get the real sleep length from the user.**
- Between them, the awake sessions used ~50 min of Bluetooth and recording (4.09 → 3.98 V) and ~45 min more (3.98 → 3.92 V).

## Is it the SD card? (2026-11-03)

SanDisk doesn't publish an idle current for the Ultra. Measured figures for a mounted SanDisk Ultra that isn't being used:
- **~0.25 mA** for a SanDisk Ultra 16 GB with the Arduino SD library, measured after the file was closed (WashU NeuroTech Hub, Joulescope). In that test, most cards stayed at tens of mA after `SD.begin()` until the first write, and on the ESP32-S3 `SD.end()` raised the current instead of lowering it.
- **~1.25 mA** for a SanDisk Ultra in SPI mode at 3.3 V after a benchmark (Gough Lui).

The 0.35–0.7 mA estimated above falls inside that 0.25–1.25 mA range, so the card alone could explain the sleep drain. It also rules out the tens-of-mA stuck state: 25 mA for 3 days would be ~1800 mAh, more than the whole cell.

Before sleep, the firmware calls `SD.end()` and holds CS high. SCK, MOSI and MISO (IO12/IO13/IO11) have no pull-ups on V2 and float during sleep, which can add a little current in the card.

To get the real number: put a meter in series with the battery while the board sleeps, once with the card in and once with it out.

Sources: https://neurotechhub.wustl.edu/?p=1727 , https://goughlui.com/2021/02/27/experiment-microsd-card-power-consumption-spi-performance/
