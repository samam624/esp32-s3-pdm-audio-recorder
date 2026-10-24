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

## Controls

| Action | What it does |
|---|---|
| REC short press | Start / stop recording (acts on release) |
| REC hold 1 s | Bluetooth on / off. Works while recording too. |
| Serial `r` / `b` | Same as a short press / a hold |
| Serial `s` | SD-crosstalk snapshot test (idle only; this used to be the 1.5 s hold in Recorder8) |
| Serial `i` | Button monitor (idle): 20 s of live REC pin levels; the REC LED lights while the pin reads pressed |
| Serial `p` | PSRAM + button check (idle, PSRAM build): 30 s of PSRAM write/read-back with all LEDs lit, while you press REC; reports errors and presses seen |

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

`ble_control.html` (in this folder) is V1's remote page, with the name changed and its "audio saved" duration corrected for 8 channels. Open it as a local file in Chrome or Edge (Bluefy on iPhone), press Connect and pick "MMSA V2". It starts and stops recording and shows live bytes written, free space, signal strength and errors. It also sets the board's clock on connect, so WAV files get the right date.

The GATT service is the same as V1's (UUIDs `6e400001…`–`6e400004…`). See `ESP32_devkit_test/ESP32_S3_SD_Recorder/README.md` for the status payload.

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

1. **SD card slowdowns (fixed by the PSRAM build; cause not yet pinned down).** Every 1–4 minutes the card spends 3–5 s unable to keep up with 768 KB/s. The internal-RAM buffer (192 ms) lost 0.7–1.3 s of audio each time, with or without Bluetooth (1 in 726 s with it off, 3 in ~550 s with it on). The SD link averages ~1.5 MB/s (SPI at 20 MHz), only 2× the need; the card's 10 MB/s rating applies to its native SD bus with 4 MB-aligned writes, not SPI. Likely cause: the card's internal housekeeping, provoked by FatFs updating its allocation table as the file grows. **Next to try:** time the writes inside a slowdown (slow writes = card, gaps = ESP), and reserve the file up front with FatFs `f_expand` (enabled in this core) so recording is purely sequential.
2. **Slow SD mount after a reset.** If the board is reset (flashing, the serial reset, a crash) within a few seconds of a recording, the card can refuse to mount for ~8–12 s. IO40 lights when it's ready, and presses before then are ignored with a serial message. A power cycle avoids it. The wake-up clocks from V1 (now in `mountSd()`) didn't cure it.
