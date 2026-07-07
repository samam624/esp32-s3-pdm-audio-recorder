# ESP32_S3_SD_Recorder

Records the onboard PDM MEMS microphone to WAV files on the SD card.
Start/stop by pressing the physical button or by sending a command over
Bluetooth LE. Validated working on the bench PCB over COM13 (2026-07-07).

## What it does

- 48kHz stereo, 16-bit PCM, written as standard WAV files: `/REC_00001.WAV`,
  `/REC_00002.WAV`, ... (auto-incrementing, never overwrites).
- Press the button once to start a new recording, press again to stop.
- Same start/stop trigger available over BLE (see below) — useful for
  triggering from a laptop/phone without touching the board.
- Three LEDs report status at a glance (see **LEDs** below).

## Pinout

| Signal | GPIO |
|---|---|
| PDM mic clock | 4 |
| PDM mic data | 5 |
| Record button | 35 (`INPUT_PULLUP`, active low) |
| REC LED | 40 |
| Level-meter LED | 41 |
| SD status LED | 42 |
| SD SPI SCK | 12 |
| SD SPI MOSI | 13 |
| SD SPI MISO | 11 |
| SD SPI CS | 14 |

No hardware SD card-detect pin — see **SD card presence detection** below.

## LEDs

| LED | Behavior |
|---|---|
| REC (40) | Off when idle. **Blinks** (400ms toggle) while recording — a tally-light style indicator, not solid-on. |
| Level (41) | PWM'd proportional to input level (gated/attack-release smoothed), regardless of recording state — lets you check mic health any time. |
| SD status (42) | Solid on while the card is considered present and mounted; off if it's missing/failed. Updates live (see below), not just at boot. |

## SD card presence detection (no CD pin)

This PCB revision has no dedicated card-detect pin (the SD socket was
jury-rigged), so `updateSdPresence()` in the firmware infers presence in
software instead of reading a hardware signal:

- While idle, every `SD_CHECK_INTERVAL_MS` (currently **50ms**) it does a
  cheap `SD.open("/")` probe. If that fails while we thought the card was
  mounted, the card is marked absent and the LED turns off. If the card was
  absent, it retries a full `mountSd()` — so reinserting a card is picked up
  automatically within ~50ms, no reboot needed.
- This check is **skipped entirely while actively recording** so it never
  competes with the SD write for the SPI bus.
- If a **write fails during an active recording** (the strongest possible
  signal the card was just pulled), the firmware marks the card gone
  immediately rather than waiting for the next poll.

If you ever need a longer/shorter interval, it's the one `#define` near the
top of the sketch (`SD_CHECK_INTERVAL_MS`). Going much below ~50ms buys
nothing perceptible and adds SPI bus churn while idle.

## Bluetooth LE control

The board advertises as **`ESP32 SD Recorder`**. GATT layout:

| Characteristic | UUID | Properties | Purpose |
|---|---|---|---|
| Service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | — | Container for the two below |
| Control | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Write | Write `0x01`/`'1'` to start, `0x00`/`'0'` to stop, anything else toggles |
| Status | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Read, Notify | `0x01` while recording, `0x00` when idle; notifies on every state change |

### `ble_control.html` — one-button remote

A self-contained Web Bluetooth control page (no build step, no server, no
external dependencies — everything is inlined in one HTML file). Connect,
then tap one button to start/stop; it shows a live elapsed-recording timer
and a collapsible technical log (useful for debugging the BLE link itself).

**How to use it:**
1. Open `ble_control.html` directly in **Chrome or Edge** — double-click it,
   or drag it into an open browser window/tab.
2. Confirm the address bar shows a `file:///...` URL (i.e. it's its own
   top-level tab). This matters: Web Bluetooth is **not available to embedded
   pages** (e.g. Claude Artifact previews, VS Code's Simple Browser, any
   iframe) — the browser blocks it by security policy regardless of the
   page's own code. It has to be a real top-level tab.
3. Tap **Connect**, pick "ESP32 SD Recorder" from the device chooser.
4. Tap the big button to start/stop.

**Browser support:** Chrome/Edge on desktop or Android. **iOS Safari does not
support Web Bluetooth at all** — use the free **Bluefy** browser app on
iPhone/iPad instead.

**Using it on another machine:** the file is fully self-contained, so just
copy `ble_control.html` to any computer with Bluetooth and open it the same
way — no install, no server, no re-pairing step beyond what the page does
itself.

### Adding WiFi control later

The trigger plumbing is already factored out so a WiFi handler is a small
addition, not a rewrite: `toggleRecording()` / `startRecording()` /
`stopRecording()` in the sketch are the only entry points anything needs to
call. The BLE write-characteristic callback calls them today; a future WiFi
command handler (HTTP endpoint, WebSocket, MQTT, whatever) would just call
the same three functions from its own handler. Not implemented yet.

## Architecture note: why audio capture is split across both cores

Early versions of this firmware read one chunk of PDM audio and immediately
`SD.write()`'d it, both in `loop()`. SD card writes are occasionally slow
(FAT bookkeeping, wear leveling) — sometimes 100ms+. The ESP32's I2S DMA ring
buffer only holds ~30ms of audio by default, so whenever a write stalled,
incoming mic audio had nowhere to go and got silently dropped. The recording
still claimed 48kHz, but actually contained less audio than the elapsed real
time — so on playback it sounded **sped up, with clicks/pops** at every drop.

The fix, and the current architecture:

- A dedicated FreeRTOS task (`i2sReaderTask`), pinned to **core 0**, does
  nothing but continuously pull audio off the I2S/PDM peripheral. It never
  touches the SD card, so it can never be blocked by a slow write.
- A **32-buffer pool** (4KB each, 128KB total, ~680ms of audio headroom) sits
  between the reader task and `loop()` as a queue-backed producer/consumer
  pipeline. The reader task fills buffers and hands them off; `loop()` (core
  1) is the only thing that touches the SD card, pulling filled buffers out
  and writing them whenever it gets to them.
- The I2S driver's own DMA queue was also deepened (`dma_desc_num=8`,
  `dma_frame_num=1024`) as a second line of defense.
- The SD SPI clock auto-negotiates the fastest speed the wiring supports,
  trying 20MHz down to 400kHz (see `kSdSpeeds` in the sketch). On this board
  it mounts at the full 20MHz.

Net effect: an occasional slow SD write just eats into the buffer pool's
headroom instead of dropping samples. As long as the *average* write speed
keeps up with the audio bitrate (it comfortably does at 20MHz SPI), recordings
come out clean.

## Building and flashing

Built with `arduino-cli` (the copy bundled with Arduino IDE 2 works fine):

```
CLI="/c/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe"
SKETCH="path/to/ESP32_S3_SD_Recorder"
FQBN="esp32:esp32:esp32s3:UploadSpeed=921600,USBMode=hwcdc,CDCOnBoot=cdc,MSCOnBoot=default,DFUOnBoot=default,UploadMode=default,CPUFreq=240,FlashMode=qio,FlashSize=4M,PartitionScheme=huge_app,DebugLevel=none,PSRAM=disabled,LoopCore=1,EventsCore=1,EraseFlash=none,JTAGAdapter=default,ZigbeeMode=default"

"$CLI" compile -b "$FQBN" "$SKETCH"
"$CLI" upload -b "$FQBN" -p COM13 "$SKETCH"
```

Notes on the board options, since defaults silently break things here:
- **`CDCOnBoot=cdc`** is required — with it left at the default (disabled),
  `Serial` output doesn't reach the native USB port at all, even though the
  board still enumerates and flashes fine. (Board: **ESP32S3 Dev Module**.)
- **`PartitionScheme=huge_app`** gives enough app-partition room for the BLE
  stack alongside the audio buffer pool (~671KB flash, ~48% RAM at last
  build — comfortable headroom on both).
- **`PSRAM=disabled`** — not currently used by this firmware (the 128KB
  audio buffer pool lives in internal SRAM), even though the chip has 8MB of
  embedded PSRAM available if a future feature needs it.

**Windows gotcha:** if upload fails with `Could not open COM13, the port is
busy` / `Access is denied`, it's almost always the Arduino IDE's own
background `arduino-cli daemon` process holding the Serial Monitor connection
open — not the IDE window itself. Find and stop just that process rather than
closing the IDE:

```powershell
Get-CimInstance Win32_Process -Filter "Name='arduino-cli.exe'" | Select-Object ProcessId, CommandLine
Stop-Process -Id <that PID> -Force
```

### Verifying it after flashing

There's no need for a Serial Monitor session open (which would just cause
the port-busy problem above) — a one-off Python snippet resets the board and
captures the boot log without leaving the port open:

```python
import serial, time
ser = serial.Serial('COM13', 115200, timeout=1)
ser.dtr = False
ser.rts = True
time.sleep(0.1)
ser.rts = False
time.sleep(0.1)
data = b''
start = time.time()
while time.time() - start < 6:
    chunk = ser.read(256)
    if chunk:
        data += chunk
ser.close()
print(data.decode(errors='replace'))
```

A healthy boot looks like:

```
SD mounted at 20000000 Hz
SD card mounted, 30436 MB total
BLE advertising as "ESP32 SD Recorder"
SD recorder ready. Press the button to start/stop recording.
```

## Known-good hardware state (as of 2026-07-07)

- SD card mounts at the full 20MHz SPI clock — signal integrity on this PCB
  is good, no need to fall back to a slower speed.
- Card capacity seen: 30,436MB (~32GB card).
- No hardware CD pin; software presence detection handles hot-plug instead.
