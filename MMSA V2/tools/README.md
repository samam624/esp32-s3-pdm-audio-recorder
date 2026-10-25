# MMSA V2 tools

PC-side helpers used during bring-up. Python 3 + numpy (no scipy needed). Run them on WAVs copied into `MMSA V2/data`.

| Script | What it does |
|---|---|
| `mic_timeline.py <8-channel.wav>` | Streams an MMSA recording into a standalone interactive HTML viewer plus CSV. Shows synchronized peak and RMS dBFS envelopes for all eight microphones, a loudest-mic ribbon, cursor values, zoom, and pan. Defaults to 20 ms bins and automatically coarsens very long recordings to keep the viewer responsive. |
| `spatial_track.py <8-channel.wav> [--pitch-mm N]` | Locates a sound source moving along the array. For each 100 ms window it measures arrival-time differences between mics (GCC-PHAT, 1-16 kHz) and fits a point source: position along the array and distance from the mic line. It fits the mic pitch from the recording unless given. Writes `visualizations/<name>_spatial.html` (to-scale side view of the array with the source, a level-per-mic heatmap with the track overlaid, distance over time, audio playback with a moving cursor, table view; light/dark) plus a CSV. Uses mic0–mic7 labels. |
| `split_wav.py <file.wav>` | Splits a multichannel recording into one mono WAV per mic (`data/split/<name>/micN.wav`, one folder per recording). **Use this before listening to 8-ch files**: players treat an 8-ch WAV as 7.1 surround and downmix it (mic3 becomes the LFE/subwoofer channel), which sounds buzzy and wrongly panned. |
| `wav_noise_floor.py <files>` | Noise-floor PSD by band during the quietest 20% of frames. A healthy mic falls off above ~12 kHz. A **flat floor up to 20 kHz = broadband hiss** (how mic4 was found). |
| `wav_band_levels.py <files>` | Energy per band (0–20 Hz … 12–24 kHz) per channel. Large sub-20 Hz / 20–100 Hz energy = handling rumble. (Its "crackle" column isn't meaningful; ignore it.) |
| `wav_continuity_corr.py <files>` | Per-channel lag-1 autocorrelation (is each track continuous audio?) and 300–3000 Hz correlation between mics (low = a mic not hearing the same sound as its neighbours). |
| `snap_compare.py <SNAP_NNNN.wav>` | Compares SD-idle vs SD-busy chunks from the Recorder8 snapshot test (hold REC 1.5 s). Hiss only in busy chunks = crosstalk from the SD traces. |
| `batlog_analyze.py <BATLOG.CSV> [--mah 150] [--start-min N]` | Reads the Recorder8 battery log from the SD card: runtime per power-up, VBAT timeline, and estimated average current / hours per 150 mAh charge. |
| `wav_buzz_detect.py <files>` | Looks for a harmonic comb (tonal buzz/hum). Found none on this board so far. |
| `stress_test.py COMx [--quick] [--tests ...]` | Stress tests for `MMSA_V2_Recorder_BLE` over USB serial and Bluetooth (`pip install pyserial bleak`): many start/stop takes, bursts of fast REC commands, a long take while Bluetooth is switched and the PC connects, start/stop from the remote, resets mid-recording, and the boot scan. Flash a short-file build first (`-DSEGMENT_SECONDS=15`) so file switches happen often. Writes a log and a results `.json` to `data/stress/`; `--quick` is a ~6 min smoke run. |
| `soak_log.py COMx [--hours 12] [--ble]` | Overnight soak test with the production build: keeps a recording running, logs every serial line to `data/soak/`, polls the board over Bluetooth every 10 min (`--ble`), logs any stop or reboot as an INCIDENT and restarts the recording, and keeps the PC awake. Prints a summary at the end; `--summarize LOG` re-prints it (heap trend, SD slowdowns, backlog, audio loss, VBAT, incidents). |
| `verify_card.py H:\ [--stress results.json]` | Checks the SD card's take folders: every file is a complete WAV, parts are numbered without gaps and all but the last are full length, joins between files are smooth, and (with `--stress`) takes cut off by stress-test resets hold their audio up to the last checkpoint. Read-only. |
| `mmsa_serial.py` | Shared helper for the tools above: opens the port without resetting the board, logs lines, `send`, `wait_for`, `health`, `reset`. |
| `serial_log.py <seconds>` | Logs COM5 serial output for N seconds. |
| `serial_reset_log.py <seconds>` | Resets the ESP32 over USB, then logs COM5 (catches boot output). |

Mic numbering everywhere: **mic N = WAV track N+1**; mic0/1 on IO5, mic2/3 IO6, mic4/5 IO7, mic6/7 IO8.
