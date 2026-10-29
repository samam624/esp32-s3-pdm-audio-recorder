# MMSA_V2_Recorder_BLE

The 8-channel recorder (`bringup/MMSA_V2_Recorder8`) plus a Bluetooth LE switch on the REC button, for measuring current draw in each operating mode. The audio path is the same as Recorder8's. Recorder8 stays as the bring-up reference.

**Build it with the link flags in [Build / flash](#build--flash).** A plain Arduino IDE build still runs, but Bluetooth switching is disabled (the boot log says why).

## Status (2026-10-24, tested on the board)

Tested over serial and from a PC acting as the remote (Python `bleak`):
- Bluetooth on in ~230 ms, off in ~55 ms. A scan doesn't see the board when off, and finds it ~1 s after switching on.
- **No crashes in ~320 switches**, many of them during recordings. Each on/off cycle loses ~24 bytes of RAM.
- Remote: connect, 12-byte status (~2 updates/s), clock set, START/STOP all work. Switching off while connected drops the link cleanly (reason 0x16). A disconnect from the PC side makes the board advertise again.
- All 8 mics healthy (−47 to −53 dBFS in a quiet room).
- REC hold (1 s) and the LED flashes confirmed working by the user.
- **Open issues:** see [Known issues](#known-issues): SD card slowdowns lose audio in long recordings (with or without Bluetooth), and the card mounts slowly after a reset.

## Recording files (2026-10-24, tested on board 2)

- **One folder per take.** Each REC press makes a folder, and the take's files go in it:

  ```
  /MMSA8_0001/MMSA8_0001_01.wav   30:00
  /MMSA8_0001/MMSA8_0001_02.wav   30:00
  /MMSA8_0001/MMSA8_0001_03.wav   10:00
  /MMSA8_0002/MMSA8_0002_01.wav   05:12
  /BATLOG.CSV
  ```

  The folder is made at REC start (start to recording takes ~160 ms, and the audio from the press on is kept), so nothing has to happen after the stop. If the folder can't be made, the take goes in the card's root instead. At boot, the next take number skips existing folders and older firmware's root `MMSA8_NNNN.wav` files.
- **Recordings are continuous.** Every 30 min (`SEGMENT_SECONDS`), the file is finished and the recording carries on in the next part in the same folder. The switch takes ~20 ms and loses no audio, because the pool keeps filling meanwhile. Join a folder's files in order for the full take. A recording ends only on a stop, a full card ("SD card full", remote error 6, with 256 MB still free: see [the card-full stop](#overnight-soak-and-the-card-full-stop-2026-10-25)) or a low battery. Serial shows each switch as `REC continues in …`, and the stop report gives the whole recording's length and file count.
  - Why: FAT32 caps a file at 4 GiB, which is 93.2 min at 768 KB/s. Before this, the write that hit the cap ended the recording as "SD write failed (card pulled?)". 30-min files (1.38 GB) also stay under the 2 GiB that some WAV readers can't handle. exFAT isn't an option, because this core's FatFs is built without it (`FF_FS_EXFAT 0`), and a standard WAV can't exceed 4 GiB anyway.
- **Checkpoints every 10 s** (`CHECKPOINT_SECONDS`): the file is synced and its header updated to the length so far (~12–16 ms). A reset, crash or power loss mid-recording leaves a playable file missing at most the last 10 s. Tested: a reset 15 s into a file left a valid 10.0 s WAV. Before, such files were 0 bytes.
- **The final header is written through a fresh file handle** and read back. After a failed write, the recording's own handle refuses further writes. That's how the 93-minute take of 2026-10-24 ended up with a header saying 0 bytes, which players treat as an empty file.
- **A failed SD write no longer ends the recording.** The file is finished, the card is remounted only if it needs it, and the recording carries on in the next part, starting with the block that failed (still in memory), so no audio is lost. Serial shows `SD write failed in … recovered in N ms`, and that part is shorter than 30 min. If a second failure comes within 5 s, or the card can't be reached, the recording stops as before ("SD write failed (card pulled?)"). Found by `tools/stress_test.py`: one write failed 1.4 s after the PC connected over Bluetooth, while the card itself remounted at once. The SD driver retries a rejected data block 3 times, but not other errors.
- **The boot scan is one pass** over the card's root (names only), so the next take number is found quickly however many takes there are. Checking number by number took 2.7 s at 155 takes. The next take is one past the highest number on the card, so a deleted take's number isn't reused out of order.
- **A stop writes the queued audio first**, so the file runs up to the press. Before, the backlog was dropped (0.9 s on one test stop during an SD slowdown, up to ~5.5 s in a long one).
- Testing: build with `--build-property "compiler.cpp.extra_flags=-DSEGMENT_SECONDS=20"` (keep the `--wrap` property too) to see the switch every 20 s. A 20 s setting gives 19.989 s files, since files hold whole 16 KB blocks. 1800 s comes out exact.

## Clipping warning and live levels (2026-10-25, tested on the board)

- **Peak without the DC offset (2026-10-25).** The peak used to include each mic's DC offset (up to ~300 counts, about −40 dBFS), so a quiet room read −35 to −48 and a finger snap barely moved it. Now it's taken after removing the offset (the previous block's mean). Quiet room: −55 to −58 dBFS; clicks near the board: about −30 on all mics, 22–29 dB up. The page holds each mic's peak for 1.5 s, since one update covers only 250 ms. Clipping is still judged on the raw samples.
- **Confirmed by hand 2026-10-25:** a finger on a mic set off the clipping alert, and `ble_control.html` works over real Bluetooth in the browser (levels table, alerts).

- **Tested 2026-10-25** from a PC acting as the remote (`bleak`), connected through a 10-min recording: MTU 256, levels 3.9/s (60 bytes, format 1), bands present in 99.7% of messages, total ≥ every band and peak ≥ total in all of them, **no audio lost** with the FFT running. Quiet room with a PC fan: all 8 mics −56 to −60 dBFS overall, loudest in 125–500 Hz. `ble_control.html` was run in headless Chrome on the captured payloads (Web Bluetooth stubbed): the table, the error 6/7 alerts and a mic3 clip (injected into a real payload) all render, with no script errors.

- **Clipping:** every block is scanned for samples at full scale on each mic. For the IMP34DT05, full scale is about 120 dB SPL (−26 dBFS at 94 dB SPL). A clipped stretch of a channel is saturated and not usable. Any clipping prints `!! CLIPPING: mic3 124 …` on serial (at most once a second, while idle too). The stop report gives per-mic counts and percentages, or `Clipping: none`. The health line carries `clip=` (this recording) and `clipmask=`. The remote gets a flag and the clipping mics in status byte 16, and shows a red alert.
- **Live levels over Bluetooth:** while the remote is connected, a new characteristic (`6e400005…`, notify) sends each mic's peak, total (20 Hz–20 kHz) and 5 band levels (20–125, 125–500, 500–2k, 2k–8k, 8k–20k Hz), all in dBFS, 4 times a second, recording or not. That's handy for checking a mounting on the bench or in the tunnel before recording. The bands come from a 1024-point FFT of every other 21 ms block (Hann window, DC removed, two mics per complex FFT). The analysis is skipped while the SD card is behind, so recording always comes first. The lowest band is coarse, because bins are 47 Hz apart. The maths was checked against known tones (a −20 dBFS tone reads −20.0 in its band). The message is 60 bytes, so the board asks for a larger Bluetooth packet on connect and logs the agreed size (`Bluetooth packet size (MTU)`).
- **Message format** (version 1): `[0]` format, `[1]` flags (bit0 recording, bit1 bands present), `[2]` clip mask, `[3]` number of bands, then per mic (mic0…mic7): peak, total, and one int8 dBFS per band (−127 = nothing).
- The PSRAM build only: the FFT needs about 18 KB of internal RAM. Without PSRAM, the remote still gets peaks and clipping.

## Calibration check (2026-10-25; compiled, maths and remote page tested off the board, not yet on the board)

Checks every mic against a known tone without touching the array, recording or not: from the remote page's **Run check**, or serial `c` (1 kHz, 10 s).

- **What it measures:** for each of 1–4 tones (100–20,000 Hz, at least 100 Hz apart), each mic's tone level (dBFS), its SNR, its phase relative to mic0, and its change against a saved baseline. Hann-windowed 8192-sample windows (5.9 Hz bins) are averaged over the check, so the tone stands clear of broadband noise like flow. The noise 47 Hz either side is subtracted.
- **Accuracy (host test of the same code on synthetic audio, ±60–80 ppm clock offset, DC offsets, rumble):** within 0.1 dB and 0.3° when the broadband noise is as loud overall as the tone; 0.3 dB in 10 s and 0.1 dB in 60 s with noise 20 dB louder than the tone. With no tone, the level reads none.
- **Baseline:** **Save as baseline** (serial `k`) keeps the last check in flash (NVS), through power cycles. Idle only: writing flash can stall the audio.
- **"vs others"** on the page is each mic's change minus the median change. A speaker level change, or flow altering the sound path, moves every mic together and cancels out there. A single hole, plug or mic that shifted stands out: amber above 1 dB, red above 3 dB. Rows with SNR under 10 dB are greyed: play the tone louder or check longer.
- **Tones:** the page can play them through the computer's audio output (WebAudio). Route that to a speaker fixed near the wing, or use any other fixed source playing the same frequencies.
- **Recording comes first:** a window is dropped if the SD card falls 8+ blocks behind or audio goes missing. The serial result prints the check's worst cost per block, so its load can be watched on the board.
- **Log:** every result is appended to `/CAL.CSV`: uptime, date, take, position in the recording (s), tone, windows used, then level/SNR/phase/delta per mic. The tones can be found in the WAV and re-analysed later.
- **Remote:** characteristic `6e400006…` (read/notify) carries the result: `[0]` format 1, `[1]` flags (recording, baseline saved, unreliable, running), `[2]` tones, `[3-4]` windows, `[5]` note, then per tone Hz (u16) and per mic level 0.01 dBFS (i16), delta 0.01 dB (i16), SNR dB (i8), phase 0.1° (i16). Control writes: `'C'`, seconds, tones as u16 Hz; `'K'` saves the baseline. The page shows the panel only on firmware with this characteristic, because older firmware treats `'C'` as a record toggle.

**Suggested use**
1. **Out of the wing:** clamp the flex under a coupon of the real skin (same hole, same padding plug). Put a small sealed cap with a speaker over one hole at a time and run a check per hole. Calibrate the cap once against a reference mic or sound level meter to turn dBFS into dB SPL. This gives each hole+plug+mic's sensitivity. Repeat at the tones you care about to see what the padding does to the response.
2. **In the wing:** fix a speaker (tunnel wall or wing root), wind off, run a check, **Save as baseline**.
3. **At will, during a run:** **Run check** from the page while recording. "vs others" shows whether any hole or plug changed (padding compressed, wet or shifted, a mount loosened). Wind-on checks need a louder tone or a longer check (up to 120 s).

## Overnight soak and the card-full stop (2026-10-25)

- **Soak:** `tools/soak_log.py COM3 --hours 12 --ble` (30-min files, Bluetooth on, the PC connecting every 10 min). One take ran **10.93 h (22 files, 28.15 GB) until the card filled** at 10:46. No reboots or unplanned stops. Internal heap flat (−1 B/h), battery steady at 4.0 V, 21 file switches (slowest 121 ms). 64 of 66 Bluetooth polls worked; the 2 misses were while a phone remote held the board's only connection. 117 SD slowdowns were absorbed (10.7/h), the worst using 2.5 s of the 5.5 s buffer.
- **Audio lost when the card filled (fixed and tested 2026-10-25).** With ~30 MB left, two writes took 9 s each. The pool overflowed and 12.6 s were dropped, then the write that hit the end failed, and the 5.5 s still queued had nowhere to go: 18 s lost at the very end. Everything before was gap-free. Now:
  - A recording **stops with `LOW_SPACE_STOP_MB` (256 MB, ~5.7 min of audio) still free**. It writes the queued audio first, like a stop press, prints `SD card full: N MB left…` and the remote shows error 6.
  - REC with less than that free is refused (`REC ignored: SD card full`, remote error 7).
  - The remote's low-space warning starts at 1.25 GB (~22 min of recording left).
  - The free-space estimate used while recording reads ~0.1% high (the card was full at an estimated 29 MB). The reserve covers that.
  - Testing: build with `--build-property "compiler.cpp.extra_flags=-DLOW_SPACE_STOP_MB=N"` (keep the `--wrap` property too), with N a few hundred MB below the card's free space (`free_mb` in the health line). The recording then stops after a few minutes, without filling the card.
  - **Tested** that way (reserve 29,896 MB, 450 MB below the card's free space): the recording stopped itself after 614.4 s with **no audio lost**, the card stayed mounted, and the remote got error 6 at once. START from the remote and REC over serial were then refused (error 7, `REC ignored: SD card full`). With the normal build, 20 s started and stopped from the remote lost no audio, and the low-space flag stayed off at 29.9 GB free.

## Controls

| Action | What it does |
|---|---|
| REC short press | Start / stop recording (acts on release). The button must be down at least 40 ms; shorter blips (bounce, electrical noise) are ignored and counted (`btnnoise` in the health line). |
| REC hold 1 s | Bluetooth on / off. Works while recording too, and doesn't stop the recording. After a hold, REC is ignored until it has been released and stayed up for 0.5 s, so letting go never starts or stops a recording, whichever way Bluetooth was switched. (Before 2026-10-24 a recording started after nearly every Bluetooth hold.) |
| Serial `r` / `b` | Same as a short press / a hold |
| Serial `h` | Health line now (it also prints every minute): uptime, take/part, recorded seconds, free space, internal heap (free, lowest ever, largest block), PSRAM, deepest backlog and slowest SD write since the last line, audio loss counters, Bluetooth state, SD write errors recovered, button noise. `tools/soak_log.py` trends these. |
| Serial `F` | Test builds only (`-DSTRESS_HOOKS`): the next SD block write counts as failed, to exercise the recovery. |
| Serial `s` | SD-crosstalk snapshot test (idle only; this used to be the 1.5 s hold in Recorder8) |
| Serial `i` | Button monitor (idle): 20 s of live REC pin levels; the REC LED lights while the pin reads pressed |
| Serial `p` | PSRAM + button check (idle, PSRAM build): 30 s of PSRAM write/read-back with all LEDs lit, while you press REC; reports errors and presses seen |
| Serial `c` / `k` | Calibration check at 1 kHz for 10 s (play the tone) / keep the last check as the baseline (idle only). See [Calibration check](#calibration-check-2026-10-25-compiled-maths-and-remote-page-tested-off-the-board-not-yet-on-the-board) |

**Bluetooth confirmation:** all three LEDs flash together.

| Flash | Meaning |
|---|---|
| 2 short flashes | Bluetooth ON (advertising as "MMSA V2") |
| 1 long flash | Bluetooth OFF |
| 5 fast flashes | The switch failed (the reason is on serial) |

No LED stays lit while Bluetooth is on, because a lit LED would add to the current being measured. Bluetooth is **off at boot**. Change `BLE_ON_AT_BOOT` to start with it on.

**What "off" means.** The NimBLE host is shut down, and the radio controller is disabled, which powers down the radio and the Bluetooth modem. The controller is initialised once at boot (a 0.25 s warm-up) and its ~35 KB of RAM stays allocated after that. It isn't freed and recreated on every switch, because recreating it crashed the board about 1 switch in 20 (see `bleWarmUp()` and the controller wrap in the sketch).

## Operating modes for current measurements

Every mode change prints a `MODE:` line over serial.

| Mode | How to get there |
|---|---|
| idle, Bluetooth off | Power-up |
| idle, Bluetooth advertising | Hold REC 1 s (2 flashes) |
| idle, Bluetooth connected | Then press Connect in `ble_control.html` |
| recording, any Bluetooth state | Short press from any of the above |

- "Idle" is not a sleep state. The CPU (240 MHz), PDM clock, all 8 mics, the record-ready LED (IO40) and the loudness LED (IO41) all keep running. For a clean comparison, keep the room quiet (the loudness LED's brightness changes the reading) and keep the SD card in.
- **Advertising uses the library's default fast interval** (NimBLE: every 30–60 ms). That interval dominates the "advertising" current: a slower one (e.g. 500 ms, via `BLEAdvertising::setMinInterval/setMaxInterval` in `bleStart()`) would draw much less, at the cost of slower discovery. The PC remote connected with a 60 ms connection interval.
- `/BATLOG.CSV` has a `ble` column (0 off, 1 advertising, 2 connected), and `tools/batlog_analyze.py` shows it in the timeline. A long battery run-down can therefore be split by mode too.

## Bluetooth remote

`ble_control.html` (in this folder) is V1's remote page, with the name changed and its "audio saved" duration corrected for 8 channels. Its "audio saved" counts the whole recording across files. The status is 16 bytes since 2026-10-24: bytes 12–15 carry the recording's total seconds, while bytes 1–4 now count the current file only. An older copy of the page still works, but its count restarts at each new file. Open it as a local file in Chrome or Edge (Bluefy on iPhone), press Connect and pick "MMSA V2". It starts and stops recording and shows live bytes written, free space, signal strength and errors. It also sets the board's clock on connect, so WAV files get the right date.

The GATT service is the same as V1's (UUIDs `6e400001…`–`6e400004…`), plus live levels (`6e400005…`), calibration checks (`6e400006…`) and recording names (`6e400007…`). See `ESP32_devkit_test/ESP32_S3_SD_Recorder/README.md` for the status payload.

**Recording names (2026-10-29, flashed to board 2 and confirmed working from the page):** type a name in the page's *Recording name* box before pressing record. The board puts it after the take number, so the take goes in `/MMSA8_0086_wing_15ms/MMSA8_0086_wing_15ms_01.wav` (the number keeps every take unique and in order). Only letters, digits and `-` are kept; any other run of characters becomes one `_` (`15 m/s run #2` → `15_m_s_run_2`), up to 32 characters. The page shows the folder the next take will get. The name stays set for every following take, including ones started with the REC button, until it is changed or cleared on the page; a reset clears it. The page remembers the box between visits and sends it again on connect and just before each start. Characteristic `6e400007…`: write the name as text (a lone space clears it); read/notify gives `<next take number>\n<name>\n<current or last take folder>`. With older firmware the page says names aren't supported and records numbered takes as before. `tools/verify_card.py` and `tools/stress_test.py` accept named folders.

**Battery meter (2026-10-25, flashed to board 2):** the status is 19 bytes. Bytes 17–18 carry VBAT in mV (u16; running average of the 250 ms readings over ~16 s, since single readings scatter about ±70 mV), and flag `0x20` means VBAT fell below the 3.40 V cutoff (recording stopped, SD card off). The page shows volts and a rough charge % (single-cell Li-ion curve; volts are what to trust under load or while charging). It averages again over ~8 s and moves the shown value in 10 mV steps. It warns below 3.55 V and keeps the warning up until 3.60 V, so noise can't make it blink. It alerts at the cutoff and logs every 50 mV change. (The page side works with the flashed firmware; the ~16 s firmware average needs a reflash.) `/BATLOG.CSV` still records VBAT every 30 s for the full run-down.

## Build / flash

```
CLI="C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
FQBN="esp32:esp32:esp32s3:UploadSpeed=921600,USBMode=hwcdc,CDCOnBoot=cdc,CPUFreq=240,FlashMode=qio,FlashSize=8M,PartitionScheme=default_8MB,PSRAM=opi,DebugLevel=none"
"$CLI" compile -b "$FQBN" --build-property "compiler.c.elf.extra_flags=-Wl,--wrap=esp_bt_controller_init -Wl,--wrap=esp_bt_controller_deinit -Wl,--wrap=esp_ipc_call_blocking" MMSA_V2_Recorder_BLE
"$CLI" upload  -b "$FQBN" -p COM5 MMSA_V2_Recorder_BLE
```

**Unmodified board (REC still on IO35):** use `PSRAM=disabled` in the FQBN and add `--build-property "compiler.cpp.extra_flags=-DBUTTON_PIN=35"` to the compile command (keep the `--wrap` property too). That build has the 192 ms internal buffer, so long recordings can still lose audio in SD slowdowns.

| Board | MAC | REC pin | Build |
|---|---|---|---|
| Board 1 (COM5) | 7C:E8:B1:B9:0A:5C | IO21 (bodged 2026-10-24) | default (`PSRAM=opi`) |
| Board 2 (COM6) | 7C:E8:B1:B9:0B:04 | IO21 (bodged 2026-10-24) | default (`PSRAM=opi`) |

- **The `--wrap` link flags are required** for Bluetooth switching. The first two keep the radio controller initialised between switches. The third makes the controller's one-time interrupt setup (in the boot warm-up) run on the calling task's own stack instead of ESP-IDF's 1 KB IPC task; the setup panicked once at boot on the PSRAM build before that. Without them, every switch-on re-creates the controller, and that overflowed ESP-IDF's 1 KB core-0 IPC task stack about 1 time in 20 (panic "Stack canary watchpoint triggered (ipc0)"). The Arduino IDE can't add link flags per sketch, so build with the command above. An IDE build boots with a warning and refuses to switch Bluetooth on.
- `PSRAM=opi` is for the **bodged board** (REC moved to IO21, `BUTTON_PIN 21`, the sketch default since 2026-10-24). For an unmodified board (REC on IO35), set `BUTTON_PIN 35` and build with `PSRAM=disabled`. A PSRAM build with `BUTTON_PIN 35` runs with the button disabled.
- Flash use is 716 KB. The sketch deletes a BLE library object whose destructor the library makes private (see the `#define private public` note at the includes). Without that, each on/off cycle leaked ~850 bytes.

## RAM (measured 2026-10-24)

- Audio buffer pool: **9 blocks (144 KB, ~192 ms)**, down from Recorder8's 12. That leaves ~77 KB free with the card mounted.
- Bluetooth controller: ~35 KB, kept from boot. Switching Bluetooth on takes **~40 KB** more, and an open WAV file ~9 KB. Bluetooth refuses to start below 60 KB free (`BLE_MIN_FREE`), keeping ~14 KB spare while it runs.
- Each on/off cycle loses ~24 bytes, so switching is effectively unlimited.
- If no card is mounted at boot, the pool keeps room for a later mount (~30 KB). Otherwise a card inserted after boot would eat the Bluetooth reserve.

## PSRAM build (standard since the REC button bodge)

The same sketch auto-detects PSRAM. Built with `PSRAM=opi` (FQBN as above with `PSRAM=disabled` changed to `PSRAM=opi`, plus the same link flags):
- The audio buffer is **4 MB in PSRAM (256 blocks, ~5.5 s)**. Each block is copied to an internal 16 KB buffer for the SD write. Internal RAM has ~236 KB free.
- **The REC button stays disabled while `BUTTON_PIN` is 35.** IO35 is a PSRAM data line, and a press would corrupt memory, so the firmware never touches it. Use serial `r`/`b` or the remote. **Don't press REC** with this build until the bodge is done.
- **Bodge (done on board 1, 2026-10-24):** button trace cut at module pad 28 (IO35), button wired to **pad 23 (IO21)**, `BUTTON_PIN 21`. Verified with `p`: 27 REC presses during 577 write/read-back passes over 1 MB of PSRAM, 0 errors. Pads 24/25 (IO47/IO48) would also work; avoid 26 (IO45) and 27 (IO0), which are boot strapping pins.
- Every slowdown it rides out is logged as `SD slowdown absorbed at +N ms: backlog peaked at …`, and the stop report shows the average SD write speed and the deepest backlog.
- **Tested 2026-10-24:** 3 × 300 s recordings (Bluetooth off, on, switching every 10 s): **0 audio lost**. Two slowdowns were absorbed (backlog peaks 1.02 s and 0.90 s, drained in 4–6 s). The deepest backlog used 19% of the buffer. SD average 1.47–1.50 MB/s.

## Known issues

(Fixed 2026-10-24: recordings stopping at 93 min, unplayable files after a failed write or a crash, and the stop dropping queued audio. See [Recording files](#recording-files-2026-10-24-tested-on-board-2).)

(Fixed 2026-10-25, not yet tested by pulling a card: the remote's live levels froze while the card was out, because each once-a-second remount attempt blocked the main loop for ~0.6 s in the SD library's retries. The idle check now sends one CMD0 and mounts only if a card answers, in under 1 ms. And "SD card was removed" stayed on the remote after the card went back in, until the next REC press; a mount now clears it.)

1. **SD card slowdowns (fixed by the PSRAM build; cause not yet pinned down).** Every 1–4 minutes the card spends 3–5 s unable to keep up with 768 KB/s. The internal-RAM buffer (192 ms) lost 0.7–1.3 s of audio each time, with or without Bluetooth (1 in 726 s with it off, 3 in ~550 s with it on). The SD link averages ~1.5 MB/s (SPI at 20 MHz), only 2× the need; the card's 10 MB/s rating applies to its native SD bus with 4 MB-aligned writes, not SPI. Likely cause: the card's internal housekeeping, provoked by FatFs updating its allocation table as the file grows. **Next to try:** time the writes inside a slowdown (slow writes = card, gaps = ESP), and reserve the file up front with FatFs `f_expand` (enabled in this core) so recording is purely sequential.
2. **Slow SD mount after a reset.** If the board is reset (flashing, the serial reset, a crash) within a few seconds of a recording, the card can refuse to mount for ~8–12 s. IO40 lights when it's ready, and presses before then are ignored with a serial message. A power cycle avoids it. The wake-up clocks from V1 (now in `mountSd()`) didn't cure it.
