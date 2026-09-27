# MEMS microphone recorder presentation draft

This is the editable speaking outline for `MEMS_Microphone_Recorder_Project_Draft.pptx`.
The deck is designed for roughly 8–10 minutes. Nearly every visual is made from
PowerPoint shapes, so labels, colors, and diagrams can be edited directly.

## Before presenting

1. Replace the yellow planned-use placeholder on slide 2 with the exact
   application, deployment location, required recording duration, and why the
   flex array matters to that study.
2. Replace the schematic board drawings with photographs of the three ordered
   boards if good photos are available. The drawings are intentionally editable
   placeholders based on the Altium design files.
3. Add your name, lab/group, presentation date, and acknowledgements.
4. Confirm whether the flex array and integrated controller have been assembled
   and electrically tested. The deck currently distinguishes the validated
   devkit recorder from the ordered custom designs.

## Slide-by-slide speaking cues

### 1. MEMS Microphone Recorder System — 30 seconds

The central project is not the damping experiment. It is the development of a
portable ESP32-S3 acoustic recorder and the PCB ecosystem needed to move from
bench testing toward the final deployment.

### 2. What I was building — 45 seconds

The goal was to remove the PC from the recording loop. The platform needed to
capture PDM microphones, save standard WAV files locally, start without touching
the setup, show whether data was really being saved, and survive realistic SD
card faults.

Replace the highlighted paragraph with the specific research use. A concise
formula is: “This recorder will be used to [measure what] at [location/subject]
for [duration], where [why remote/local/multi-point recording matters].”

### 3. Three ordered PCB designs — 60 seconds

- The ESP32 devkit carrier was the fast prototype and is the board on which the
  recorder firmware was validated.
- The flex board moves eight microphones into a repeatable linear geometry.
- The integrated board combines the controller, power, charging, storage, and
  flex connection into the portable system direction.

### 4. ESP32 devkit recorder — 50 seconds

The board carries an ESP32-S3 DevKitC, two ST IMP34DT05TR PDM microphones, a
microSD socket, a 1.8 V microphone supply, a recording button, and status LEDs.
The firmware pin mapping was validated on hardware. STEP and printable enclosure
files also exist, so this board was both the electrical and mechanical prototype.

### 5. Eight-microphone flex array — 45 seconds

The flex is approximately 350 mm long and 14 mm wide. It contains eight PDM
microphones, organized as four left/right pairs, with local decoupling and a
10-pin FPC tail. Its value is controlled sensor spacing and separation between
the microphones and recorder electronics.

### 6. Integrated controller — 55 seconds

This board removes the plug-in development module and uses an ESP32-S3-WROOM
module directly. It adds USB-C with protection, LiPo charging/load sharing,
separate 3.3 V and 1.8 V rails, the flex connector, SD interface, controls, and
status indicators. This is the transition from a bench tool to a deployable
instrument.

### 7. Firmware evolution — 60 seconds

Each firmware version answered a separate question: does PDM capture work; can
the board appear as a USB microphone; does the SD bus work; can it record valid
WAV files without a PC; and can it be controlled and monitored remotely? This
staged approach made hardware and firmware failures easier to isolate.

### 8. Capture/storage architecture — 75 seconds

The most important bug was that SD writes occasionally stalled longer than the
I²S DMA buffer. Samples were dropped, but the WAV header still claimed 48 kHz,
so playback sounded fast and clicked. The fix was a dedicated core-0 reader and
a 32 × 4 KB queue. Core 1 performs SD writes. The queue provides about 680 ms of
headroom while the average data rate is only 192 kB/s.

### 9. Troubleshooting — 90 seconds

Choose three or four examples rather than reading every row. The strongest
examples are the audio dropout architecture change, SPI reset recovery, periodic
WAV-header repair, and prevention of filename reuse after a flaky remount. These
show how observed failures directly changed the implementation.

### 10. Current system — 45 seconds

The current recorder saves 48 kHz stereo 16-bit WAV files, can be controlled by
button or BLE, reports a live byte count and free space, detects a stale link or
stalled write, protects against a nearly full card, and has been validated with
the SD card running at 20 MHz SPI.

### 11. Damping check — 30 seconds

Frame this explicitly as a feasibility screen. It used one hand-positioned
recording per material/condition, so it cannot establish calibrated attenuation
or statistical significance. Bare pop-filter material looked promising and can
be carried into a controlled follow-up. The more important result here is that
the recorder produced usable files for downstream analysis.

### 12. Next steps — 45 seconds

The remaining work is to connect the finished electronics to the exact research
protocol: bring up the ordered boards in a fixed sequence, verify the flex-array
signals and channel mapping, finalize the enclosure and acoustic interface, and
run a controlled pilot before deployment.

## Technical facts used in the deck

- Current recorder: 48 kHz, stereo, 16-bit PCM WAV.
- Audio stream: 192,000 bytes/s.
- Buffer pool: 32 × 4096 bytes = 128 KiB, about 0.68 s of audio.
- SD mount verified at 20 MHz; card reported about 30,436 MB.
- BLE status heartbeat: 500 ms.
- Storage thresholds: warning below 200 MB; stop/refuse below 50 MB.
- Flex array: eight IMP34DT05TR microphones and a 10-position FPC tail;
  Gerber outline is approximately 350 × 14 mm.
- Integrated board: ESP32-S3-WROOM-1-N8R8, MCP73871 charging/load sharing,
  USB-C, 3.3 V and 1.8 V regulators, FPC interface, and SD connection.

