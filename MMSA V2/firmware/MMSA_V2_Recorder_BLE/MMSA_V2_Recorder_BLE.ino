// MMSA V2: 8-channel WAV recorder with switchable Bluetooth LE, for bench-testing operating modes and current draw.
// Built from bringup/MMSA_V2_Recorder8 (left unchanged as the bring-up reference). The audio path is identical:
// hardware PDM->PCM, 48 kHz, 16-bit, 8 mics on 4 data lines, shared clock IO4. Each recording (take) goes in its own
// folder: /MMSA8_0001/MMSA8_0001_01.wav, then /MMSA8_0002/MMSA8_0002_01.wav, ...
//
// Controls
//   REC short press      start / stop recording (acts on release)
//   REC hold 1 s         Bluetooth on / off (works while recording too)
//   serial 'r' / 'b'     same as short press / hold;  's' = SD-crosstalk snapshot test (idle only)
//   serial 'c' / 'k'     calibration check (1 kHz, 10 s) / keep the last check as the baseline (see the cal section)
//   Bluetooth remote     ble_control.html in this folder (Chrome/Edge, or Bluefy on iPhone): start/stop + live status
//                        + calibration checks
//
// Continuous recording: every SEGMENT_SECONDS (30 min) the file is closed and the recording carries on in the next one
// in the take's folder (MMSA8_0001_02.wav, ...) with no audio lost, so a recording only ends on a stop, a full card or
// a low battery.
//
// Bluetooth switch confirmation (all three LEDs flash together):
//   2 short flashes = Bluetooth ON     1 long flash = Bluetooth OFF     5 fast flashes = switch FAILED (see serial)
// No LED stays lit to show that Bluetooth is on, because a lit LED would add to the current being measured.
// Bluetooth starts OFF at boot (BLE_ON_AT_BOOT). OFF means the whole stack is shut down (NimBLE host stopped,
// controller disabled and deinitialised, radio off), as if the firmware had no Bluetooth at all.
//
// Operating modes for current measurements (every change prints a "MODE:" line over serial):
//   idle,      Bluetooth off            boot state
//   idle,      Bluetooth advertising    hold REC 1 s
//   idle,      Bluetooth connected      then Connect from ble_control.html
//   recording, Bluetooth off/adv/conn   short press from any of the above
// "Idle" still runs the CPU, PDM clock, 8 mics and the record-ready/loudness LEDs, so it isn't a sleep state.
//
// Mic numbering: micN = 8-slot channel index N = WAV track N+1.
//   mic0-1 = IO5, mic2-3 = IO6, mic4-5 = IO7, mic6-7 = IO8
//
// Architecture (as Recorder8): an I2S reader task on core 0 fills a pool of RAM blocks and never touches the SD card;
// loop() on core 1 is the only SD user and writes full 16 KB blocks. Bluetooth runs in its own task (bleTask), so
// switching it on or off (~0.3 s) never stalls the SD writes; remote commands are queued to loop().
//
// LEDs: IO40 record ready (SD mounted), IO41 loudness (loudest mic), IO42 blinks while recording.
// /BATLOG.CSV: VBAT every 30 s with the recording and Bluetooth state (ble: 0 off, 1 advertising, 2 connected).
// Build with PSRAM=disabled (IO35 = REC button is shared with the octal PSRAM).

#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <math.h>
#include <sys/time.h>
#include <driver/i2s_pdm.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <host/ble_gap.h>
#include <host/ble_hs.h>
#include <esp_bt.h>
#include <esp_ipc.h>
#include <map>
#include <vector>
#include <functional>
#include <Preferences.h>
// The BLE library gives BLEService a private destructor and never deletes services, so every Bluetooth on/off cycle
// leaked one (~850 bytes, measured 2026-10-24). Opening up access for the BLE library headers only lets bleStop()
// delete it. Access specifiers don't change object layout in GCC, and every system header is included above, so
// only the BLE library's own classes are affected.
#define private public
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#undef private

#define MIC_CLK_PIN 4
static const gpio_num_t MIC_DIN[4] = {GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7, GPIO_NUM_8};

// Which mics are fitted. Unfitted PDM half-slots read back as undefined data, so they are written as digital silence.
// All 8 fitted and working since 2026-10-21 (mic rail on 3.3 V).
static const bool MIC_FITTED[8] = {true, true, true, true, true, true, true, true};
#define SD_SCK  12
#define SD_MISO 11
#define SD_MOSI 13
#define SD_CS   14
// REC button. Board bodge 2026-10-24: moved from IO35 (module pad 28, an octal-PSRAM line) to IO21 (pad 23), so the
// PSRAM can be used (build with PSRAM=opi). For an unmodified board build with PSRAM=disabled and
// --build-property "compiler.cpp.extra_flags=-DBUTTON_PIN=35" (see README).
#ifndef BUTTON_PIN
#define BUTTON_PIN 21
#endif
#define LED_SD     40
#define LED_LEVEL  41
#define LED_REC    42

// PDM clock = 64 x SAMPLE_RATE. Stay at 48000: at 32000 the ESP32 PDM->PCM path output white noise (2026-10-21).
#define SAMPLE_RATE 48000
#define CHANNELS    8
#define FRAME_BYTES (CHANNELS * 2)
#define DMA_DESC    8
#define DMA_FRAMES  256              // 8 x 256 frames x 16 B = 32 KB (~43 ms) of DMA buffering
#define BLOCK_BYTES 16384            // one pool block = 1024 frames = 21.3 ms; also the SD write size
#define BLOCK_FRAMES (BLOCK_BYTES / FRAME_BYTES)
#define POOL_BLOCKS_MAX 12           // internal-RAM pool (no PSRAM): up to 192 KB (~256 ms); fewer if RAM is short
#define POOL_BLOCKS_MIN 4
#define PSRAM_POOL_BYTES (4 * 1024 * 1024)  // with PSRAM: 256 blocks = 4 MB (~5.5 s) to ride out SD slowdowns
#define POOL_SLOTS  (PSRAM_POOL_BYTES / BLOCK_BYTES)
#define BACKLOG_REPORT_BLOCKS 12     // report an SD slowdown once the backlog passes what the internal pool could hold
#define SD_HZ       20000000

// Continuous recording: a recording is split into files of SEGMENT_SECONDS each (the last one shorter). They join with
// no gap, because blocks keep queuing in the pool while one file is closed and the next opened. FAT32 caps a file at
// 4 GiB (93.2 min at 768 KB/s). Before this, the write that hit the cap ended the recording as "SD write failed"
// (2026-10-24). 30 min = 1.38 GB, under the 2 GiB that some WAV readers can't handle. Override with
// -DSEGMENT_SECONDS=N (a short value tests the file switch).
#ifndef SEGMENT_SECONDS
#define SEGMENT_SECONDS 1800
#endif
#define SEGMENT_BYTES ((uint32_t)((uint64_t)SEGMENT_SECONDS * SAMPLE_RATE * FRAME_BYTES / BLOCK_BYTES * BLOCK_BYTES))
static_assert((uint64_t)SEGMENT_SECONDS * SAMPLE_RATE * FRAME_BYTES < 0xFFFFFFFFull - 44,
              "SEGMENT_SECONDS is too long for one FAT32 file / WAV");
static_assert(SEGMENT_BYTES >= BLOCK_BYTES, "SEGMENT_SECONDS is too short");

// Checkpoints: every CHECKPOINT_SECONDS of audio the file is synced (so the card's directory holds its real size) and
// its header updated to the length so far. A reset, crash or power loss mid-recording then leaves a playable file that
// is missing at most the last CHECKPOINT_SECONDS. Before this, such files were 0 bytes, or their header said 0 bytes.
#ifndef CHECKPOINT_SECONDS
#define CHECKPOINT_SECONDS 10
#endif
#define CHECKPOINT_BYTES ((uint32_t)CHECKPOINT_SECONDS * SAMPLE_RATE * FRAME_BYTES)

// Space kept free on the card. A recording stops cleanly (queued audio written, remote error 6) once the card is down
// to LOW_SPACE_STOP_MB (~5.7 min of audio), and a new one won't start below it (error 7). A card written to its last
// few MB stalls: in the 2026-10-25 soak, two writes with ~30 MB left took 9 s each, overflowing the 5.5 s pool, and
// 18 s were lost before the write that hit the end failed. Override with -DLOW_SPACE_STOP_MB=N (a big value tests
// the stop without filling a card).
#ifndef LOW_SPACE_STOP_MB
#define LOW_SPACE_STOP_MB 256
#endif

// RAM budget. The audio pool is sized at boot to leave SD_HEAP_HEADROOM for SD/FS (as in Recorder8) plus
// BLE_HEAP_RESERVE so Bluetooth can be switched on later. Measured 2026-10-24: the radio controller keeps ~35 KB from
// the boot warm-up on (see the controller wrap), and switching Bluetooth on takes ~40 KB more (printed each time as
// "uses N bytes"). Bluetooth refuses to start unless BLE_MIN_FREE is free, so ~14 KB stays free for SD/FS while it
// runs. Each on/off cycle leaks ~850 bytes (see bleStop()), which allows ~25 switches per power-up.
#define SD_HEAP_HEADROOM 28000
#define SD_MOUNT_RAM     32000      // RAM a card mount takes (30.4 KB measured); reserved too if no card at boot
#define BLE_HEAP_RESERVE 46000
#define BLE_MIN_FREE     (BLE_HEAP_RESERVE + 14000)

#define DEBOUNCE_MS   50
#define BLE_HOLD_MS   1000           // hold REC this long to switch Bluetooth
#define REC_BLINK_MS  400
#define SD_PROBE_MS   500
#define SD_REMOUNT_MS 1000
#define STATUS_MS     2000

#define LEVEL_GAIN      6.0f
#define LEVEL_THRESHOLD 0.035f
#define LEVEL_ATTACK    0.25f
#define LEVEL_RELEASE   0.06f

// ---------------- Bluetooth settings ----------------
// Same GATT layout as the V1 recorder (ESP32_devkit_test/ESP32_S3_SD_Recorder), so its remote page works. The
// remote finds the board by service UUID, so the name only changes what the device chooser shows.
#define BLE_ON_AT_BOOT        0
#define BLE_DEVICE_NAME       "MMSA V2"
#define BLE_SERVICE_UUID      "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define BLE_CONTROL_CHAR_UUID "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  // write: 1 start, 0 stop, other = toggle
#define BLE_STATUS_CHAR_UUID  "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  // read/notify: 17-byte status, below
#define BLE_TIME_CHAR_UUID    "6e400004-b5a3-f393-e0a9-e50e24dcca9e"  // write: uint32 local time (WAV file dates)
#define BLE_LEVELS_CHAR_UUID  "6e400005-b5a3-f393-e0a9-e50e24dcca9e"  // notify: live per-mic levels (levels section)
#define BLE_CAL_CHAR_UUID     "6e400006-b5a3-f393-e0a9-e50e24dcca9e"  // read/notify: calibration check result (cal section)
#define BLE_STATUS_MS         500    // status heartbeat to a connected remote
#define LOW_SPACE_WARN_MB     (LOW_SPACE_STOP_MB + 1024)  // remote's low-space warning: ~22 min of recording left

// Status payload (17 bytes, little-endian): [0] flags, [1-4] bytes in the current/last file, [5-8] SD free MB,
// [9] error code, [10] RSSI dBm (int8, 0 = not measured), [11] HCI reason of the last disconnect (0 = none),
// [12-15] seconds of audio in the whole current/last recording (all its files), [16] mics that clipped in the last
// CLIP_HOLD_MS (bit N = micN). Older remotes read only what they know.
#define STATUS_FLAG_RECORDING 0x01
#define STATUS_FLAG_SD_READY  0x02
#define STATUS_FLAG_LOW_SPACE 0x04
#define STATUS_FLAG_ERROR     0x08
#define STATUS_FLAG_CLIPPING  0x10
#define STATUS_FLAG_BATT_LOW  0x20  // VBAT fell below BATLOG_CUTOFF_MV: recording stopped, SD card switched off
// Error codes, numbered as the remote page expects.
enum : uint8_t { RERR_NONE = 0, RERR_SD_NOT_READY = 1, RERR_WRITE_FAILED = 2, RERR_CARD_REMOVED = 3,
                 RERR_OPEN_FAILED = 5, RERR_CARD_FULL = 6, RERR_LOW_SPACE = 7 };
enum : uint8_t { CMD_STOP = 0, CMD_START = 1, CMD_TOGGLE = 2, CMD_CAL = 3, CMD_CAL_SAVE = 4 };
enum : uint8_t { MODE_BLE_OFF = 0, MODE_BLE_ADV = 1, MODE_BLE_CONN = 2 };
enum : uint8_t { BLERES_NONE = 0, BLERES_ON, BLERES_OFF, BLERES_FAILED };
#define EVT_TOGGLE      (1u << 0)
#define EVT_STATUS      (1u << 1)
#define EVT_READVERTISE (1u << 2)
#define EVT_LEVELS      (1u << 3)
#define EVT_CAL         (1u << 4)

// Calibration check request and result (see the cal section). Defined here, ahead of every function, because the
// Arduino build puts its generated function prototypes above the first function.
#define CAL_MAX_TONES 4
struct CalSpec { uint8_t seconds, n; uint16_t hz[CAL_MAX_TONES]; };
struct CalResult {  // also the NVS baseline record
  uint8_t ver, n;
  uint16_t hz[CAL_MAX_TONES];
  int16_t lvl[CAL_MAX_TONES][CHANNELS];  // 0.01 dBFS
  int16_t ph[CAL_MAX_TONES][CHANNELS];   // 0.1 degree, re mic0
};
#define CAL_RESULT_VER 1

SPIClass sdSPI(FSPI);
static i2s_chan_handle_t rx = NULL;
static uint8_t *pool[POOL_SLOTS];
static int poolBlocks = 0;
static bool poolInPsram = false;
static uint8_t *writeBuf = NULL;     // internal DMA-capable copy of a PSRAM block for the SD write
static bool buttonEnabled = true;
static QueueHandle_t freeQ, fullQ;   // queues of block indices

static File wav;
static volatile bool recording = false;
static volatile bool sdReady = false;
static volatile uint32_t dataBytes = 0;        // audio bytes in the current file
static String currentFile;                       // the file being (or last) written
static uint64_t sessionBytesDone = 0;          // audio bytes in this recording's earlier files (see SEGMENT_SECONDS)
static volatile uint32_t sessionSecsDone = 0;  // the same in seconds, for the remote
static uint32_t sessionFiles = 0;              // files in this recording so far
static String sessionFirstFile;
static uint32_t checkpointAt = 0;              // dataBytes at the current file's last checkpoint
static uint32_t checkpoints = 0, checkpointFails = 0, maxCheckpointUs = 0;
static int hMinFree = POOL_SLOTS;              // lowest free-block count since the last health line (recording only)
static uint32_t hWorstWriteUs = 0;             // slowest block write since the last health line
static uint32_t recStartMs = 0;
static volatile uint32_t dmaOverflows = 0;
static volatile uint32_t poolDrops = 0;      // blocks lost because no free block was available
static volatile uint32_t streamGaps = 0;     // any discarded read, recording or idle (the calibration check drops
                                             // a window that spans one)
static uint32_t maxWriteUs = 0;
static uint64_t sumWriteUs = 0;              // total SD write time this recording (average write speed)
static uint32_t writes = 0;
static bool backlogActive = false;           // an SD slowdown is being ridden out (see loop())
static int backlogPeak = 0;
static uint32_t backlogStartMs = 0;
static int minFreeBlocks = 0;
static volatile float loudestRms = 0;        // set by reader task, used for the loudness LED
static bool batlogStopped = false;           // battery below cutoff: SD card no longer used (see battery logger)
static float levelSmoothed = 0.0f;
static volatile uint8_t errorCode = RERR_NONE;
static volatile uint32_t freeMb = 0, freeMbAtStart = 0;
static int nextFileIndex = 1;                // next take number to try (see findNextFreeFile())
static int takeIndex = 0;                    // number of the current/last take
static uint32_t stopPressMs = 0;             // when a stop was asked for (see stopRecordingAtPress()), for wall time
static uint32_t writeErrors = 0;             // failed SD writes recovered from in this recording (see recoverWrite())
static uint32_t sdErrorsSinceBoot = 0, lastRecoverMs = 0;
static void scanTakes();
#ifdef STRESS_HOOKS
static volatile bool failNextWrite = false;  // serial 'F' (test builds only): the next block write counts as failed
#endif
static String takeDir;                       // its folder, "/MMSA8_0001" ("" = card root; see startRecording())
static void findNextFreeFile();

// Bluetooth state. bleOn is written only by bleTask; the others by the NimBLE host task's callbacks.
static volatile bool bleOn = false;
static volatile bool bleConnected = false;
static volatile bool bleStopping = false;    // shutting down: don't restart advertising on the disconnect
static volatile int8_t bleRssi = 0;
static volatile uint8_t bleLastDisconnectReason = 0;
static volatile uint16_t bleConnHandle = BLE_HS_CONN_HANDLE_NONE;
static volatile uint8_t bleResult = BLERES_NONE;  // outcome of the last switch, for loop()'s LED flash
static TaskHandle_t bleTaskHandle = NULL;
static QueueHandle_t cmdQ;                   // record commands from the remote, executed by loop()

// Idle per-mic status accumulators (loop side).
static double stSq[CHANNELS], stSum[CHANNELS];
static int16_t stMin[CHANNELS], stMax[CHANNELS];
static uint32_t stFrames = 0, stPairSame[CHANNELS / 2];

static void bleWake(uint32_t bits) {
  if (bleTaskHandle) xTaskNotify(bleTaskHandle, bits, eSetBits);
}
static void bleStatusChanged() { bleWake(EVT_STATUS); }
static void requestBleToggle() { bleWake(EVT_TOGGLE); }
static uint8_t bleMode() { return !bleOn ? MODE_BLE_OFF : (bleConnected ? MODE_BLE_CONN : MODE_BLE_ADV); }

static void printMode() {
  static const char *name[3] = {"off", "advertising", "connected"};
  Serial.printf("MODE: %s, Bluetooth %s\n", recording ? "RECORDING" : "idle", name[bleMode()]);
}

static bool IRAM_ATTR onOverflow(i2s_chan_handle_t h, i2s_event_data_t *e, void *ctx) {
  dmaOverflows++;
  return false;
}

// REC button, latched by interrupt so a busy loop() can never miss a press. A falling edge counts as a press
// only if the pin had been released for DEBOUNCE_MS (rejects release bounce), and presses are locked out for
// PRESS_LOCKOUT_MS (rejects press bounce). loop() then times the press to tell a short press from a hold.
#define PRESS_LOCKOUT_MS 250
// loop() then decides what the press was (see handleButton()):
#define MIN_PRESS_MS     40    // down for less than this = a bounce or electrical noise, ignored
#define RELEASE_MS       30    // up this long (continuously) = released; shorter blips don't end a press
#define AFTER_HOLD_MS    500   // after a Bluetooth hold: up this long (continuously) before REC counts again
static volatile bool buttonPressed = false;
static volatile uint32_t buttonPressCount = 0;  // every accepted press (PSRAM/button check)
static volatile uint32_t lastRiseMs = 0, lastPressMs = 0;
static uint32_t buttonNoise = 0;                // presses ignored as too short (HEALTH line)
enum : uint8_t { BTN_IDLE, BTN_PRESSED, BTN_HELD, BTN_AFTER_HOLD };
static uint8_t btnState = BTN_IDLE;
static void resetButton() {  // after the button tests, which use the button themselves
  buttonPressed = false;
  btnState = BTN_IDLE;
}
static void IRAM_ATTR onButtonEdge() {
  uint32_t now = millis();
  if (gpio_get_level((gpio_num_t)BUTTON_PIN)) {
    lastRiseMs = now;
  } else if (now - lastRiseMs >= DEBOUNCE_MS && now - lastPressMs >= PRESS_LOCKOUT_MS) {
    lastPressMs = now;
    buttonPressed = true;
    buttonPressCount++;
  }
}

// ---------------- I2S reader task (core 0): never touches SD ----------------
static void readerTask(void *) {
  int cur = -1;
  size_t fill = 0;
  static uint8_t scratch[4096];
  for (;;) {
    if (cur < 0) {
      if (xQueueReceive(freeQ, &cur, 0) != pdTRUE) {
        // No free block: read and discard so the DMA keeps flowing, and count the loss. Count it only if the
        // recording had already started when this read began. While idle the pool overflows whenever loop() is
        // busy (e.g. startRecording() opening the file), and a discard read that began before REC start holds
        // pre-start audio, not a gap in the recording.
        bool rec = recording;
        size_t got = 0;
        i2s_channel_read(rx, scratch, sizeof(scratch), &got, portMAX_DELAY);
        if (rec) poolDrops++;
        streamGaps++;
        cur = -1;
        continue;
      }
      fill = 0;
    }
    size_t got = 0;
    if (i2s_channel_read(rx, pool[cur] + fill, BLOCK_BYTES - fill, &got, portMAX_DELAY) != ESP_OK) continue;
    fill += got;
    if (fill >= BLOCK_BYTES) {
      // Loudest-mic RMS for the loudness LED (fitted mics only, DC removed).
      const int16_t *s = (const int16_t *)pool[cur];
      double sq[CHANNELS] = {0}, sum[CHANNELS] = {0};
      for (int f = 0; f < BLOCK_FRAMES; f++)
        for (int c = 0; c < CHANNELS; c++) {
          double v = s[f * CHANNELS + c];
          sq[c] += v * v;
          sum[c] += v;
        }
      double mx = 0;
      for (int c = 0; c < CHANNELS; c++) {
        if (!MIC_FITTED[c]) continue;
        double mean = sum[c] / BLOCK_FRAMES;
        double var = sq[c] / BLOCK_FRAMES - mean * mean;
        if (var > mx) mx = var;
      }
      loudestRms = sqrtf((float)mx) / 32768.0f;
      xQueueSend(fullQ, &cur, portMAX_DELAY);
      cur = -1;
    }
  }
}

// ---------------- SD ----------------
static void refreshFreeSpace() {
  // Can take a few seconds the first time on a big card (FAT scan); only called while idle.
  uint64_t total = SD.totalBytes(), used = SD.usedBytes();
  freeMb = total > used ? (uint32_t)((total - used) >> 20) : 0;
}

static void setSdReady(bool ready) {
  bool changed = ready != sdReady;
  if (changed) Serial.printf("SD %s\n", ready ? "mounted" : "NOT available");
  sdReady = ready;
  digitalWrite(LED_SD, ready ? HIGH : LOW);
  if (changed && ready) {
    // A card is back: clear the remote's "no card" errors, which described the state that just ended (before
    // 2026-10-25 "SD card was removed" stayed up until the next REC press). Errors about a recording that stopped
    // (write failed, couldn't open a file, card full) stay until the next REC, so they aren't missed.
    if (errorCode == RERR_CARD_REMOVED || errorCode == RERR_SD_NOT_READY) errorCode = RERR_NONE;
    refreshFreeSpace();
    // Scan forward from the current number, never back to 1 within a boot: V1 once overwrote an earlier take when a
    // flaky remount made SD.exists() miss a file and the scan restarted from 1.
    uint32_t t0 = millis();
    scanTakes();
    Serial.printf("SD: next recording will go in /MMSA8_%04d/ (%.1f GB free; scan took %lu ms)\n", nextFileIndex,
                  freeMb / 1024.0f, (unsigned long)(millis() - t0));
  }
  if (changed) bleStatusChanged();
}

// probeFirst (the idle check for a card, every SD_REMOUNT_MS while there is none): mount only if a card answers CMD0
// (go idle) with R1 = 0x01, which takes < 1 ms. With no card, SD.begin() spends ~0.6 s in retries (3 x 100 ms per
// command, twice), and that stalled loop() for 0.6 s in every second while the card was out: the remote's live levels
// froze (2026-10-25). Not used at boot or after a failed write, where a busy card needs SD.begin()'s longer waits.
static bool mountSd(bool probeFirst = false) {
  SD.end();
  sdSPI.end();
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  // Wake-up clocks (>= 74 with CS high, per the SD spec) before mounting. A reset in the middle of a write leaves the
  // card waiting for the rest of that transfer, ignoring the mount; this flushes it (from V1's recorder). Without it
  // the card stayed unmountable for ~12 s after a reset mid-recording (2026-10-24).
  pinMode(SD_CS, OUTPUT);
  digitalWrite(SD_CS, HIGH);
  sdSPI.beginTransaction(SPISettings(400000, MSBFIRST, SPI_MODE0));
  for (int i = 0; i < 10; i++) sdSPI.transfer(0xFF);
  bool answered = true;
  if (probeFirst) {
    static const uint8_t CMD0[6] = {0x40, 0, 0, 0, 0, 0x95};
    digitalWrite(SD_CS, LOW);
    for (uint8_t b : CMD0) sdSPI.transfer(b);
    uint8_t r = 0xFF;
    for (int i = 0; i < 9 && (r & 0x80); i++) r = sdSPI.transfer(0xFF);  // R1 comes within 8 bytes
    digitalWrite(SD_CS, HIGH);
    sdSPI.transfer(0xFF);
    answered = r == 0x01;
  }
  sdSPI.endTransaction();
  if (!answered) return false;
  return SD.begin(SD_CS, sdSPI, SD_HZ) && SD.cardType() != CARD_NONE;
}

static void updateSdPresence() {
  static uint32_t lastCheck = 0;
  if (recording || batlogStopped) return;
  uint32_t now = millis();
  if (sdReady) {
    if (now - lastCheck < SD_PROBE_MS) return;
    lastCheck = now;
    File root = SD.open("/");
    bool ok = (bool)root;
    if (root) root.close();
    if (!ok) {
      SD.end();
      errorCode = RERR_CARD_REMOVED;
      setSdReady(false);
    }
  } else {
    if (now - lastCheck < SD_REMOUNT_MS) return;
    lastCheck = now;
    setSdReady(mountSd(true));
  }
}

static bool writeWavHeader(File &f, uint32_t dataLen) {
  uint8_t h[44];
  uint32_t byteRate = SAMPLE_RATE * FRAME_BYTES;
  uint16_t blockAlign = FRAME_BYTES, bits = 16, fmt = 1, ch = CHANNELS;
  uint32_t fmtLen = 16, riffLen = 36 + dataLen, sr = SAMPLE_RATE;
  memcpy(h, "RIFF", 4);
  memcpy(h + 4, &riffLen, 4);
  memcpy(h + 8, "WAVEfmt ", 8);
  memcpy(h + 16, &fmtLen, 4);
  memcpy(h + 20, &fmt, 2);
  memcpy(h + 22, &ch, 2);
  memcpy(h + 24, &sr, 4);
  memcpy(h + 28, &byteRate, 4);
  memcpy(h + 32, &blockAlign, 2);
  memcpy(h + 34, &bits, 2);
  memcpy(h + 36, "data", 4);
  memcpy(h + 40, &dataLen, 4);
  return f.seek(0) && f.write(h, 44) == 44;
}

// Writes the header for `bytes` of audio into `path` through a second handle, so the recording handle stays at the end
// of the file (seeking it back to the end would walk the whole cluster chain of a GB-sized file). With `verify`, reads
// the header back. The recording handle never caches the header sector: it is long past it.
static bool patchWavHeader(const String &path, uint32_t bytes, bool verify) {
  File h = SD.open(path, "r+");
  if (!h) return false;
  bool ok = writeWavHeader(h, bytes);
  h.close();
  if (!ok || !verify) return ok;
  h = SD.open(path, FILE_READ);
  if (!h) return false;
  uint8_t b[44];
  uint32_t got = 0;
  ok = h.read(b, 44) == 44;
  h.close();
  memcpy(&got, b + 40, 4);
  return ok && got == bytes;
}

// Closes the recording file and writes its final header. The close syncs the file's size to the card even after a
// failed write, but the failed write leaves the handle refusing further writes. Writing the final header through it
// is what failed on the 93-minute take of 2026-10-24 (header left saying 0 bytes), so the header goes through a fresh
// handle.
static bool finishWav() {
  wav.close();
  return patchWavHeader(currentFile, dataBytes, true);
}

// See CHECKPOINT_SECONDS. Runs between block writes. ~10-30 ms on a fast card; the pool absorbs it.
static void checkpointWav() {
  uint32_t t = micros();
  wav.flush();  // fflush + fsync: the directory entry now holds the size so far
  bool ok = patchWavHeader(currentFile, dataBytes, false);
  uint32_t dt = micros() - t;
  if (dt > maxCheckpointUs) maxCheckpointUs = dt;
  checkpointAt = dataBytes;
  checkpoints++;
  if (!ok && checkpointFails++ == 0) Serial.printf("  WARNING: checkpoint of %s failed\n", currentFile.c_str());
}

// ---------------- I2S ----------------
static void startPdm() {
  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num = DMA_DESC;
  cc.dma_frame_num = DMA_FRAMES;
  ESP_ERROR_CHECK(i2s_new_channel(&cc, NULL, &rx));
  i2s_pdm_rx_config_t cfg = {};
  i2s_pdm_rx_clk_config_t clk = I2S_PDM_RX_CLK_DEFAULT_CONFIG(SAMPLE_RATE);
  cfg.clk_cfg = clk;
  i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  cfg.slot_cfg = s;
  cfg.slot_cfg.slot_mask = I2S_PDM_LINE_SLOT_ALL;
  cfg.gpio_cfg.clk = (gpio_num_t)MIC_CLK_PIN;
  for (int i = 0; i < 4; i++) cfg.gpio_cfg.dins[i] = MIC_DIN[i];
  ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx, &cfg));
  i2s_event_callbacks_t cbs = {};
  cbs.on_recv_q_ovf = onOverflow;
  i2s_channel_register_event_callback(rx, &cbs, NULL);
  ESP_ERROR_CHECK(i2s_channel_enable(rx));
  // NO pull-downs on the data lines (they killed mic1 and degraded mic4/5 on 2026-10-21).
}

// ---------------- Clipping and live levels ----------------
// Clipping: every block is scanned for samples at full scale. A clipped sample means the mic or the PDM converter
// saturated (above about 120 dB SPL for the IMP34DT05: -26 dBFS at 94 dB SPL), so that stretch of that channel is not
// usable. Reported on serial at most once a second, per mic in the stop report and HEALTH line, and to the remote
// (status flag + byte 16), which shows a warning.
// Live levels: while the remote is connected, every other block is analysed (DC removed, Hann window, 1024-point FFT,
// two mics per complex FFT) into LEVEL_BANDS bands. Every LEVELS_MS each mic's peak, total and band levels go to the
// remote in one notification. Analysis is skipped while the SD card is behind, so recording always comes first.
#define CLIP_LEVEL     32767  // |sample| at or above this is at full scale
#define CLIP_HOLD_MS   2000   // a clip keeps its warning up this long
#define CLIP_REPORT_MS 1000   // serial clip report at most this often
#define LEVELS_MS      250    // live levels to the remote, 4 a second
#define LEVEL_BANDS    5
#define FFT_N          BLOCK_FRAMES  // 1024 frames = one pool block per FFT; bins 46.9 Hz apart
#define LEVELS_MSG_BYTES (4 + CHANNELS * (2 + LEVEL_BANDS))
// Band edges in Hz: roughly two octaves each across the mics' range. The remote page labels them the same way.
static const uint16_t BAND_EDGE_HZ[LEVEL_BANDS + 1] = {20, 125, 500, 2000, 8000, 20000};
static uint32_t clipTotal[CHANNELS];          // clipped samples in the current/last recording
static uint32_t clipWin[CHANNELS];            // clipped samples since the last serial report
static uint32_t clipLastMs[CHANNELS];         // when each mic last clipped (0 = not this boot)
static volatile uint8_t clipMask = 0;         // mics that clipped in the last CLIP_HOLD_MS (bit N = micN)
static uint16_t peakWin[CHANNELS];            // highest |sample| since the last levels message
static float bandAcc[CHANNELS][LEVEL_BANDS];  // summed band mean squares since the last levels message
static uint16_t bandBlocks = 0;               // blocks analysed into bandAcc
static uint32_t levelsBlockCount = 0;
static float *fftRe = NULL, *fftIm = NULL, *fftWin = NULL, *twCos = NULL, *twSin = NULL;
static float fftWinPow = 0;                   // sum of the squared window (power scaling)
static uint16_t bandLo[LEVEL_BANDS], bandHi[LEVEL_BANDS];  // FFT bins of each band
static portMUX_TYPE levelsMux = portMUX_INITIALIZER_UNLOCKED;
static uint8_t levelsMsg[LEVELS_MSG_BYTES];   // built by loop(), sent by bleTask

// ~18 KB of internal RAM for the FFT, so only on the PSRAM build, which has plenty spare (the internal-RAM build needs
// its RAM for the audio pool and Bluetooth). Without it the remote still gets peaks and clipping, just no bands.
static bool levelsInit() {
  if (!poolInPsram) return false;
  const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  fftRe = (float *)heap_caps_malloc(FFT_N * sizeof(float), caps);
  fftIm = (float *)heap_caps_malloc(FFT_N * sizeof(float), caps);
  fftWin = (float *)heap_caps_malloc(FFT_N * sizeof(float), caps);
  twCos = (float *)heap_caps_malloc(FFT_N / 2 * sizeof(float), caps);
  twSin = (float *)heap_caps_malloc(FFT_N / 2 * sizeof(float), caps);
  if (!fftRe || !fftIm || !fftWin || !twCos || !twSin) {
    free(fftRe), free(fftIm), free(fftWin), free(twCos), free(twSin);
    fftRe = fftIm = fftWin = twCos = twSin = NULL;
    return false;
  }
  fftWinPow = 0;
  for (int i = 0; i < FFT_N; i++) {
    fftWin[i] = 0.5f - 0.5f * cosf(2.0f * (float)PI * i / FFT_N);  // periodic Hann
    fftWinPow += fftWin[i] * fftWin[i];
  }
  for (int k = 0; k < FFT_N / 2; k++) {
    twCos[k] = cosf(2.0f * (float)PI * k / FFT_N);
    twSin[k] = -sinf(2.0f * (float)PI * k / FFT_N);
  }
  const float df = (float)SAMPLE_RATE / FFT_N;
  for (int b = 0; b < LEVEL_BANDS; b++) {
    int lo = (int)ceilf(BAND_EDGE_HZ[b] / df), hi = (int)ceilf(BAND_EDGE_HZ[b + 1] / df) - 1;
    bandLo[b] = lo < 1 ? 1 : lo;
    bandHi[b] = hi > FFT_N / 2 - 1 ? FFT_N / 2 - 1 : hi;
  }
  return true;
}

// In-place radix-2 complex FFT of FFT_N points (forward).
static void fftInPlace(float *re, float *im) {
  for (int i = 1, j = 0; i < FFT_N; i++) {
    int bit = FFT_N >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      float t = re[i]; re[i] = re[j]; re[j] = t;
      t = im[i]; im[i] = im[j]; im[j] = t;
    }
  }
  for (int len = 2; len <= FFT_N; len <<= 1) {
    int half = len >> 1, step = FFT_N / len;
    for (int i = 0; i < FFT_N; i += len)
      for (int k = 0; k < half; k++) {
        float wr = twCos[k * step], wi = twSin[k * step];
        int a = i + k, b = a + half;
        float tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr;
        im[b] = im[a] - ti;
        re[a] += tr;
        im[a] += ti;
      }
  }
}

// Clip and peak scan of one block (every block, recording or idle). The peak is taken after removing each mic's DC
// offset (the previous block's mean): the offsets (up to ~300 counts, about -40 dBFS) held the quiet-room peak near
// -36 dBFS, so a finger snap barely moved it (2026-10-25). Clipping is judged on the raw samples.
static int32_t dcPrev[CHANNELS];
static void scanBlock(const int16_t *s) {
  uint32_t now = millis();
  int32_t sum[CHANNELS] = {0};
  for (int f = 0; f < BLOCK_FRAMES; f++, s += CHANNELS)
    for (int c = 0; c < CHANNELS; c++) {
      int v = s[c];
      sum[c] += v;
      int ac = v - dcPrev[c];
      uint16_t p = (uint16_t)min(ac < 0 ? -ac : ac, 65535);
      if (p > peakWin[c]) peakWin[c] = p;
      uint16_t a = (uint16_t)(v < 0 ? -v : v);
      if (a >= CLIP_LEVEL) {
        clipWin[c]++;
        if (recording) clipTotal[c]++;
        clipLastMs[c] = now ? now : 1;
      }
    }
  for (int c = 0; c < CHANNELS; c++) dcPrev[c] = sum[c] / BLOCK_FRAMES;
}

// Band levels of one block, into bandAcc. Two mics per complex FFT: real part = mic p, imaginary part = mic p+1.
static void analyzeBlock(const int16_t *s) {
  const float scale = 2.0f / ((float)FFT_N * fftWinPow);  // one-sided band mean square from |X|^2
  for (int p = 0; p < CHANNELS; p += 2) {
    float m0 = 0, m1 = 0;
    for (int f = 0; f < FFT_N; f++) {
      m0 += s[f * CHANNELS + p];
      m1 += s[f * CHANNELS + p + 1];
    }
    m0 /= FFT_N;
    m1 /= FFT_N;
    for (int f = 0; f < FFT_N; f++) {
      fftRe[f] = (s[f * CHANNELS + p] - m0) * fftWin[f];
      fftIm[f] = (s[f * CHANNELS + p + 1] - m1) * fftWin[f];
    }
    fftInPlace(fftRe, fftIm);
    // Split the two real spectra: A_k = (Z_k + conj Z_{N-k}) / 2, B_k = (Z_k - conj Z_{N-k}) / 2i.
    for (int b = 0; b < LEVEL_BANDS; b++) {
      float pa = 0, pb = 0;
      for (int k = bandLo[b]; k <= bandHi[b]; k++) {
        float zr = fftRe[k], zi = fftIm[k], cr = fftRe[FFT_N - k], ci = -fftIm[FFT_N - k];
        float ar = 0.5f * (zr + cr), ai = 0.5f * (zi + ci);
        float br = 0.5f * (zi - ci), bi = -0.5f * (zr - cr);
        pa += ar * ar + ai * ai;
        pb += br * br + bi * bi;
      }
      bandAcc[p][b] += pa * scale;
      bandAcc[p + 1][b] += pb * scale;
    }
  }
  bandBlocks++;
}

// ---------------- Calibration check ----------------
// Measures one to four known tones on all 8 mics, recording or not, so the array can be checked in place without
// touching it: from the remote ('C' on the control characteristic) or serial 'c'. Something has to play the tones:
// the remote page can play them through the computer's audio output, or any fixed speaker can. Each mic's response at
// each tone comes from Hann-windowed 8192-sample windows (bins 5.9 Hz apart, so a tone stands well clear of broadband
// noise such as flow), averaged over the requested seconds:
//   level  tone level in dBFS (sine amplitude re full scale), after subtracting the noise measured 47 Hz either side
//   snr    tone over that noise in the same bandwidth, dB (below ~10 dB the level is unreliable)
//   phase  phase relative to mic0 at the tone, from the averaged cross-spectrum (the tone is coherent across mics;
//          flow noise mostly isn't, so it averages out)
//   delta  level minus the saved baseline at the same frequency
// The baseline (serial 'k', remote 'K'; idle only, since writing flash can stall the audio) is kept in NVS, so it
// survives power cycles. Every result is appended to /CAL.CSV with the take and the position in the recording, so the
// tones can also be found and re-analysed in the WAV. A window that sees the SD card behind (8+ blocks queued) or a gap
// in the audio stream is dropped, so recording always comes first.
#define CAL_WIN            8192                    // samples per window (171 ms)
#define CAL_WIN_BLOCKS     (CAL_WIN / BLOCK_FRAMES)
#define CAL_SIDE_BINS      8                       // noise measured this many bins either side of a tone (46.9 Hz)
#define CAL_NF             (CAL_MAX_TONES * 3)     // per tone: the tone, the bin below, the bin above
#define CAL_MIN_WINDOWS    5                       // fewer than this: the result is flagged unreliable
#define CAL_BEHIND_BLOCKS  8
#define CAL_DEFAULT_HZ     1000
#define CAL_DEFAULT_S      10
#define CAL_MAX_S          120
#define CAL_MIN_HZ         100
#define CAL_MAX_HZ         20000
#define CAL_MIN_SPACING_HZ 100                     // closer tones would sit in each other's noise bins
#define CAL_FILE           "/CAL.CSV"
#define CAL_NONE           INT16_MIN               // no value (no tone found, no baseline)
#define CAL_MSG_BYTES(n)   (6 + (n) * (2 + CHANNELS * 7))
#define CAL_MSG_MAX        CAL_MSG_BYTES(CAL_MAX_TONES)
// Remote message flags and notes (byte [1] and [5] of the cal message; see calBuildMsg()).
#define CALF_RECORDING  0x01
#define CALF_BASELINE   0x02
#define CALF_UNRELIABLE 0x04
#define CALF_RUNNING    0x08
enum : uint8_t { CALN_OK = 0, CALN_BUSY, CALN_BAD_TONES, CALN_SAVE_NEEDS_IDLE, CALN_NOTHING_TO_SAVE, CALN_SAVED,
                 CALN_SAVE_FAILED };
// CalSpec and CalResult are defined with the globals at the top (the Arduino build's generated prototypes need them).

static portMUX_TYPE calMux = portMUX_INITIALIZER_UNLOCKED;
static CalSpec calReq;                     // from the remote (NimBLE task), taken by loop()
static bool calActive = false;
static CalSpec cal;                        // the check running
static uint32_t calBlocksLeft = 0, calWindows = 0, calDropped = 0, calMaxUs = 0, calGapMark = 0;
static int calWinPos = 0;                  // blocks into the current window
static float calPr[CAL_NF], calPi[CAL_NF], calRr[CAL_NF], calRi[CAL_NF];  // phasor e^{-jwn} and its per-sample step
static float calXr[CAL_NF][CHANNELS], calXi[CAL_NF][CHANNELS];            // this window's DFT values
static float calQr, calQi, calQsr, calQsi;                                // Hann phasor e^{j2pi n/N} and its step
static float calP[CAL_MAX_TONES][CHANNELS], calN[CAL_MAX_TONES][CHANNELS];   // summed tone and noise power
static float calCr[CAL_MAX_TONES][CHANNELS], calCi[CAL_MAX_TONES][CHANNELS]; // summed cross-spectrum with mic0
static CalResult calLast, calBase;
static int8_t calLastSnr[CAL_MAX_TONES][CHANNELS];
static bool calHaveLast = false, calHaveBase = false, calLastRec = false;
static float calLastRecSecs = -1;          // position in the recording when the last check started (-1 idle)
static uint8_t calMsg[CAL_MSG_MAX];
static uint16_t calMsgLen = 0;

// Checks and fills in a request (0 seconds or tones = defaults). Returns a CALN_ note.
static uint8_t calCheckSpec(CalSpec &s) {
  if (s.seconds == 0) s.seconds = CAL_DEFAULT_S;
  if (s.seconds > CAL_MAX_S) s.seconds = CAL_MAX_S;
  if (s.n == 0) {
    s.n = 1;
    s.hz[0] = CAL_DEFAULT_HZ;
  }
  if (s.n > CAL_MAX_TONES) return CALN_BAD_TONES;
  for (int t = 0; t < s.n; t++) {
    if (s.hz[t] < CAL_MIN_HZ || s.hz[t] > CAL_MAX_HZ) return CALN_BAD_TONES;
    for (int u = 0; u < t; u++)
      if (abs((int)s.hz[t] - (int)s.hz[u]) < CAL_MIN_SPACING_HZ) return CALN_BAD_TONES;
  }
  return CALN_OK;
}

static void calDspStart(const CalSpec &s) {
  cal = s;
  const float side = (float)CAL_SIDE_BINS * SAMPLE_RATE / CAL_WIN;
  for (int t = 0; t < s.n; t++) {
    const float f[3] = {(float)s.hz[t], s.hz[t] - side, s.hz[t] + side};
    for (int j = 0; j < 3; j++) {
      int k = t * 3 + j;
      float w = 2.0f * (float)PI * f[j] / SAMPLE_RATE;
      calRr[k] = cosf(w);
      calRi[k] = -sinf(w);
      calPr[k] = 1.0f;
      calPi[k] = 0.0f;
    }
    for (int c = 0; c < CHANNELS; c++) calP[t][c] = calN[t][c] = calCr[t][c] = calCi[t][c] = 0.0f;
  }
  float qw = 2.0f * (float)PI / CAL_WIN;
  calQsr = cosf(qw);
  calQsi = sinf(qw);
  calWinPos = 0;
  calWindows = calDropped = calMaxUs = 0;
  calBlocksLeft = (uint32_t)s.seconds * SAMPLE_RATE / BLOCK_FRAMES;
}

// One block into the current window. dc: each mic's offset (removed before the window).
static void calDspBlock(const int16_t *s, const int32_t *dc) {
  if (calWinPos == 0) {
    memset(calXr, 0, sizeof(calXr));
    memset(calXi, 0, sizeof(calXi));
    calQr = 1.0f;
    calQi = 0.0f;
  }
  const int nf = cal.n * 3;
  float x[CHANNELS];
  for (int f = 0; f < BLOCK_FRAMES; f++, s += CHANNELS) {
    float w = 0.5f - 0.5f * calQr;  // periodic Hann over the window
    for (int c = 0; c < CHANNELS; c++) x[c] = (float)(s[c] - dc[c]) * w;
    for (int k = 0; k < nf; k++) {
      float pr = calPr[k], pi = calPi[k];
      float *xr = calXr[k], *xi = calXi[k];
      for (int c = 0; c < CHANNELS; c++) {
        xr[c] += x[c] * pr;
        xi[c] += x[c] * pi;
      }
      calPr[k] = pr * calRr[k] - pi * calRi[k];
      calPi[k] = pr * calRi[k] + pi * calRr[k];
    }
    float qr = calQr * calQsr - calQi * calQsi;
    calQi = calQr * calQsi + calQi * calQsr;
    calQr = qr;
  }
  // Renormalise the phasors once a block (float rounding grows slowly over many rotations).
  for (int k = 0; k < nf; k++) {
    float m = 1.0f / sqrtf(calPr[k] * calPr[k] + calPi[k] * calPi[k]);
    calPr[k] *= m;
    calPi[k] *= m;
  }
  float m = 1.0f / sqrtf(calQr * calQr + calQi * calQi);
  calQr *= m;
  calQi *= m;
  calWinPos++;
}

// A finished window: add its tone power, noise power and cross-spectrum with mic0.
static void calDspWindowEnd() {
  for (int t = 0; t < cal.n; t++) {
    const int k = t * 3;
    const float x0r = calXr[k][0], x0i = calXi[k][0];
    for (int c = 0; c < CHANNELS; c++) {
      const float xr = calXr[k][c], xi = calXi[k][c];
      calP[t][c] += xr * xr + xi * xi;
      float lo = calXr[k + 1][c] * calXr[k + 1][c] + calXi[k + 1][c] * calXi[k + 1][c];
      float hi = calXr[k + 2][c] * calXr[k + 2][c] + calXi[k + 2][c] * calXi[k + 2][c];
      calN[t][c] += 0.5f * (lo + hi);
      calCr[t][c] += xr * x0r + xi * x0i;  // X_c * conj(X_0)
      calCi[t][c] += xi * x0r - xr * x0i;
    }
  }
  calWindows++;
}

// Turns the sums into calLast / calLastSnr. A Hann window sums to N/2, so a sine of amplitude A gives |X| = A N / 4.
static void calDspResult() {
  CalResult &r = calLast;
  r.ver = CAL_RESULT_VER;
  r.n = cal.n;
  const float toFs = 16.0f / ((float)CAL_WIN * CAL_WIN) / (32768.0f * 32768.0f);  // |X|^2 -> (A / full scale)^2
  for (int t = 0; t < CAL_MAX_TONES; t++) {
    r.hz[t] = t < cal.n ? cal.hz[t] : 0;
    for (int c = 0; c < CHANNELS; c++) {
      r.lvl[t][c] = r.ph[t][c] = CAL_NONE;
      calLastSnr[t][c] = -127;
      if (t >= cal.n || !calWindows || !MIC_FITTED[c]) continue;
      float p = calP[t][c] / calWindows, n = calN[t][c] / calWindows, sig = p - n;
      if (sig > 0) {
        float db = 10.0f * log10f(sig * toFs);
        r.lvl[t][c] = (int16_t)lroundf(constrain(db, -320.0f, 30.0f) * 100.0f);
        float snr = n > 0 ? 10.0f * log10f(sig / n) : 127.0f;
        calLastSnr[t][c] = (int8_t)lroundf(constrain(snr, -127.0f, 127.0f));
      }
    }
    // Phase only where both this mic and mic0 found the tone (otherwise it's the phase of noise).
    for (int c = 0; t < cal.n && c < CHANNELS; c++) {
      if (r.lvl[t][c] == CAL_NONE || r.lvl[t][0] == CAL_NONE) continue;
      r.ph[t][c] = c == 0 ? 0 : (int16_t)lroundf(atan2f(calCi[t][c], calCr[t][c]) * 1800.0f / (float)PI);
    }
  }
}

// Level minus the baseline's at the same frequency, 0.01 dB (CAL_NONE if either is missing).
static int16_t calDelta(int t, int c) {
  if (!calHaveBase || calLast.lvl[t][c] == CAL_NONE) return CAL_NONE;
  for (int u = 0; u < calBase.n && u < CAL_MAX_TONES; u++)
    if (calBase.hz[u] == calLast.hz[t] && calBase.lvl[u][c] != CAL_NONE)
      return (int16_t)constrain((int)calLast.lvl[t][c] - calBase.lvl[u][c], -32767, 32767);
  return CAL_NONE;
}

// Remote message: [0] format 1, [1] flags (CALF_*), [2] tones n, [3-4] windows used (u16), [5] note (CALN_*),
// then per tone: Hz (u16), and per mic (mic0..mic7): level 0.01 dBFS (i16), delta vs baseline 0.01 dB (i16),
// SNR dB (i8), phase re mic0 0.1 degree (i16). INT16_MIN = no value. Little-endian. n = 0 while running.
static void calBuildMsg(bool running, uint8_t note) {
  uint8_t m[CAL_MSG_MAX];
  int n = (!running && calHaveLast) ? calLast.n : 0;
  m[0] = 1;
  m[1] = (calLastRec ? CALF_RECORDING : 0) | (calHaveBase ? CALF_BASELINE : 0) |
         (n && calWindows < CAL_MIN_WINDOWS ? CALF_UNRELIABLE : 0) | (running ? CALF_RUNNING : 0);
  m[2] = (uint8_t)n;
  uint16_t w = (uint16_t)min(calWindows, (uint32_t)65535);
  memcpy(m + 3, &w, 2);
  m[5] = note;
  int o = 6;
  for (int t = 0; t < n; t++) {
    memcpy(m + o, &calLast.hz[t], 2);
    o += 2;
    for (int c = 0; c < CHANNELS; c++) {
      int16_t d = calDelta(t, c);
      memcpy(m + o, &calLast.lvl[t][c], 2);
      memcpy(m + o + 2, &d, 2);
      m[o + 4] = (uint8_t)calLastSnr[t][c];
      memcpy(m + o + 5, &calLast.ph[t][c], 2);
      o += 7;
    }
  }
  portENTER_CRITICAL(&calMux);
  memcpy(calMsg, m, o);
  calMsgLen = o;
  portEXIT_CRITICAL(&calMux);
  bleWake(EVT_CAL);
}

static void calPrintResult() {
  Serial.printf("CAL done: %lu windows (%lu dropped), %s, baseline %s%s\n", (unsigned long)calWindows,
                (unsigned long)calDropped, calLastRec ? "recording" : "idle", calHaveBase ? "saved" : "none",
                calWindows < CAL_MIN_WINDOWS ? "  ** too few windows, unreliable **" : "");
  if (calLastRec) Serial.printf("  started at %.1f s into take %d\n", calLastRecSecs, takeIndex);
  for (int t = 0; t < calLast.n; t++) {
    Serial.printf("  %u Hz:\n", calLast.hz[t]);
    for (int c = 0; c < CHANNELS; c++) {
      int16_t l = calLast.lvl[t][c], d = calDelta(t, c), p = calLast.ph[t][c];
      Serial.printf("    mic%d %8s dBFS  snr %4d dB  phase %7s  vs base %7s dB\n", c,
                    l == CAL_NONE ? "none" : String(l / 100.0f, 2).c_str(), (int)calLastSnr[t][c],
                    p == CAL_NONE ? "-" : String(p / 10.0f, 1).c_str(),
                    d == CAL_NONE ? "-" : String(d / 100.0f, 2).c_str());
    }
  }
  Serial.printf("  check cost: worst %lu us per 21.3 ms block\n", (unsigned long)calMaxUs);
}

// One line per tone in /CAL.CSV (header on a new file).
static void calLogCsv() {
  if (!sdReady || batlogStopped) return;
  bool fresh = !SD.exists(CAL_FILE);
  File f = SD.open(CAL_FILE, FILE_APPEND);
  if (!f) {
    Serial.println("CAL: couldn't open " CAL_FILE);
    return;
  }
  if (fresh) {
    f.print("uptime_s,date,take,rec_s,tone_hz,windows,dropped,baseline");
    for (int c = 0; c < CHANNELS; c++) f.printf(",mic%d_dbfs,mic%d_snr_db,mic%d_phase_deg,mic%d_delta_db", c, c, c, c);
    f.println();
  }
  char date[24] = "";
  time_t now = time(NULL);
  if (now > 1600000000) {
    struct tm tmv;
    localtime_r(&now, &tmv);
    strftime(date, sizeof(date), "%Y-%m-%d %H:%M:%S", &tmv);
  }
  for (int t = 0; t < calLast.n; t++) {
    f.printf("%lu,%s,%d,%.1f,%u,%lu,%lu,%d", (unsigned long)(millis() / 1000), date, calLastRec ? takeIndex : 0,
             calLastRecSecs, calLast.hz[t], (unsigned long)calWindows, (unsigned long)calDropped, calHaveBase ? 1 : 0);
    for (int c = 0; c < CHANNELS; c++) {
      int16_t l = calLast.lvl[t][c], d = calDelta(t, c), p = calLast.ph[t][c];
      f.print(',');
      if (l != CAL_NONE) f.printf("%.2f", l / 100.0f);
      f.printf(",%d,", (int)calLastSnr[t][c]);
      if (p != CAL_NONE) f.printf("%.1f", p / 10.0f);
      f.print(',');
      if (d != CAL_NONE) f.printf("%.2f", d / 100.0f);
    }
    f.println();
  }
  f.close();
}

static void calStart(CalSpec s) {
  if (calActive) {
    Serial.println("CAL ignored: a check is already running");
    calBuildMsg(true, CALN_BUSY);
    return;
  }
  uint8_t note = calCheckSpec(s);
  if (note != CALN_OK) {
    Serial.printf("CAL refused: 1-%d tones, each %d-%d Hz and at least %d Hz apart\n", CAL_MAX_TONES, CAL_MIN_HZ,
                  CAL_MAX_HZ, CAL_MIN_SPACING_HZ);
    calBuildMsg(false, note);
    return;
  }
  calDspStart(s);
  calLastRec = recording;
  calLastRecSecs = recording ? sessionSecsDone + (float)dataBytes / (SAMPLE_RATE * FRAME_BYTES) : -1.0f;
  calActive = true;
  Serial.printf("CAL: measuring");
  for (int t = 0; t < s.n; t++) Serial.printf(" %u", s.hz[t]);
  Serial.printf(" Hz on all mics for %u s%s. Play the tone(s) now.\n", s.seconds,
                recording ? " (the recording carries on)" : "");
  calBuildMsg(true, CALN_OK);
}

// Called for every block (after scanBlock, which leaves this block's mean in dcPrev).
static void calBlock(const int16_t *s) {
  if (!calActive) return;
  uint32_t t0 = micros();
  if (uxQueueMessagesWaiting(fullQ) >= CAL_BEHIND_BLOCKS) {
    if (calWinPos) calDropped++;  // the SD card is behind: drop this window, recording comes first
    calWinPos = 0;
  } else {
    if (calWinPos == 0) calGapMark = streamGaps + dmaOverflows;
    calDspBlock(s, dcPrev);
    if (calWinPos == CAL_WIN_BLOCKS) {
      if (streamGaps + dmaOverflows == calGapMark) calDspWindowEnd();
      else calDropped++;  // audio went missing inside this window
      calWinPos = 0;
    }
  }
  uint32_t dt = micros() - t0;
  if (dt > calMaxUs) calMaxUs = dt;
  if (calBlocksLeft) calBlocksLeft--;
  if (calBlocksLeft) return;
  calActive = false;
  calDspResult();
  calHaveLast = true;
  calPrintResult();
  calLogCsv();
  calBuildMsg(false, CALN_OK);
}

static void calSaveBaseline() {
  uint8_t note = CALN_SAVED;
  if (recording) {
    Serial.println("Baseline NOT saved: stop recording first (writing flash can stall the audio)");
    note = CALN_SAVE_NEEDS_IDLE;
  } else if (!calHaveLast || calActive) {
    Serial.println("Baseline NOT saved: run a check first (serial c, or the remote)");
    note = CALN_NOTHING_TO_SAVE;
  } else {
    Preferences p;
    bool ok = p.begin("mmsacal", false) && p.putBytes("base", &calLast, sizeof(calLast)) == sizeof(calLast);
    p.end();
    if (ok) {
      calBase = calLast;
      calHaveBase = true;
      Serial.println("Baseline saved (kept through power cycles); later checks report each mic against it");
      if (sdReady && !batlogStopped) {
        File f = SD.open(CAL_FILE, FILE_APPEND);
        if (f) {
          f.printf("# baseline saved from the check above, uptime %lu s\n", (unsigned long)(millis() / 1000));
          f.close();
        }
      }
    } else {
      Serial.println("Baseline NOT saved: NVS write failed");
      note = CALN_SAVE_FAILED;
    }
  }
  calBuildMsg(false, note);
}

static void calLoadBaseline() {
  Preferences p;
  if (p.begin("mmsacal", true)) {
    CalResult b;
    if (p.getBytesLength("base") == sizeof(b) && p.getBytes("base", &b, sizeof(b)) == sizeof(b) &&
        b.ver == CAL_RESULT_VER && b.n >= 1 && b.n <= CAL_MAX_TONES) {
      calBase = b;
      calHaveBase = true;
    }
    p.end();
  }
  if (!calHaveBase) {
    Serial.println("Calibration baseline: none saved");
    return;
  }
  Serial.print("Calibration baseline: saved at");
  for (int t = 0; t < calBase.n; t++) Serial.printf(" %u", calBase.hz[t]);
  Serial.println(" Hz");
}

// Called by loop() for every block. Band analysis only while the remote is connected, on every other block, and only
// when the SD card isn't behind.
static void levelsBlock(const int16_t *s) {
  scanBlock(s);
  calBlock(s);
  if (fftRe && bleConnected && (++levelsBlockCount & 1) && uxQueueMessagesWaiting(fullQ) < 4) analyzeBlock(s);
}

static int8_t msToDbfs(float ms) {
  if (ms <= 0) return -127;
  float db = 10.0f * log10f(ms / (32768.0f * 32768.0f / 2.0f));  // 0 dBFS = full-scale sine
  return (int8_t)(db < -127 ? -127 : (db > 3 ? 3 : lroundf(db)));
}

// Every LEVELS_MS while connected: [0] format 1, [1] flags (bit0 recording, bit1 bands present), [2] clip mask,
// [3] number of bands, then per mic (mic0..mic7): peak dBFS, total 20 Hz-20 kHz dBFS, one dBFS per band (all int8).
static void buildLevels() {
  uint8_t m[LEVELS_MSG_BYTES];
  m[0] = 1;
  m[1] = (recording ? 1 : 0) | (bandBlocks ? 2 : 0);
  m[2] = clipMask;
  m[3] = LEVEL_BANDS;
  for (int c = 0; c < CHANNELS; c++) {
    uint8_t *d = m + 4 + c * (2 + LEVEL_BANDS);
    float pk = peakWin[c] ? 20.0f * log10f(peakWin[c] / 32768.0f) : -127;
    d[0] = (uint8_t)(int8_t)(pk < -127 ? -127 : lroundf(pk));
    float tot = 0;
    for (int b = 0; b < LEVEL_BANDS; b++) {
      tot += bandAcc[c][b];
      d[2 + b] = (uint8_t)(bandBlocks ? msToDbfs(bandAcc[c][b] / bandBlocks) : -127);
      bandAcc[c][b] = 0;
    }
    d[1] = (uint8_t)(bandBlocks ? msToDbfs(tot / bandBlocks) : -127);
    peakWin[c] = 0;
  }
  bandBlocks = 0;
  portENTER_CRITICAL(&levelsMux);
  memcpy(levelsMsg, m, sizeof(m));
  portEXIT_CRITICAL(&levelsMux);
  bleWake(EVT_LEVELS);
}

static uint32_t clipSum() {  // clipped samples in the current/last recording, all mics
  uint32_t n = 0;
  for (int c = 0; c < CHANNELS; c++) n += clipTotal[c];
  return n;
}

// Every CLIP_REPORT_MS: serial warning for any mic that clipped since the last report, and the remote's clip mask.
static void reportClipping() {
  uint32_t now = millis();
  uint8_t mask = 0;
  char list[96];
  int n = 0;
  for (int c = 0; c < CHANNELS; c++) {
    if (clipLastMs[c] && now - clipLastMs[c] < CLIP_HOLD_MS) mask |= 1 << c;
    if (clipWin[c] && n < (int)sizeof(list) - 24)
      n += snprintf(list + n, sizeof(list) - n, " mic%d %lu", c, (unsigned long)clipWin[c]);
    clipWin[c] = 0;
  }
  if (n)
    Serial.printf("!! CLIPPING%s:%s samples at full scale in the last second (over ~120 dB SPL); that audio is "
                  "saturated\n", recording ? "" : " (not recording)", list);
  if (mask != clipMask) {
    clipMask = mask;
    bleStatusChanged();
  }
}

// ---------------- Recording ----------------
// File numbering. Each SD.exists() takes ~7 ms, so scanning from 1 at every REC press got slower with every file on
// the card (~290 ms at 43 files). Instead the scan runs when the card mounts (setSdReady()), and a REC press only
// re-checks the number found then. nextFileIndex is declared with the globals.
// Each take (REC press) gets a folder, /MMSA8_0001/, holding its files MMSA8_0001_01.wav, _02.wav, ... (one per
// SEGMENT_SECONDS). A number is taken if its folder exists, or a root /MMSA8_NNNN.wav from older firmware does.
static void findNextFreeFile() {
  char name[24];
  for (; nextFileIndex < 9999; nextFileIndex++) {
    snprintf(name, sizeof(name), "/MMSA8_%04d", nextFileIndex);
    if (SD.exists(name)) continue;
    strcat(name, ".wav");
    if (!SD.exists(name)) return;
  }
}

// At mount: the next take is one past the highest take number on the card (a folder, or an older firmware's root
// MMSA8_NNNN.wav), found in one pass over the root's names. Checking number by number got slow: each SD.exists()
// searches the whole root, so that scan grew with the square of the takes (2.7 s at 155 takes, 2026-10-24). It never
// goes back within a boot (setSdReady()), and a deleted take's number isn't reused out of order.
static void scanTakes() {
  File root = SD.open("/");
  if (root) {
    int highest = 0;
    for (;;) {
      String n = root.getNextFileName();  // readdir only: doesn't open each entry
      if (!n.length()) break;
      int s = n.lastIndexOf('/') + 1;
      if (n.length() < s + 10 || !n.substring(s, s + 6).equals("MMSA8_")) continue;
      bool digits = true;
      for (int i = s + 6; i < s + 10; i++) digits = digits && isDigit(n[i]);
      if (!digits) continue;  // e.g. an old MMSA8_32k_0001.wav
      int v = n.substring(s + 6, s + 10).toInt();
      if (v > highest) highest = v;
    }
    root.close();
    if (highest + 1 > nextFileIndex) nextFileIndex = highest + 1;
  }
  findNextFreeFile();  // and confirm that number is free
}

// Path of file `part` (1, 2, ...) of the current take.
static String partPath(int part) {
  char name[48];
  snprintf(name, sizeof(name), "%s/MMSA8_%04d_%02d.wav", takeDir.c_str(), takeIndex, part);
  return String(name);
}

static void drainFullBlocks() {
  int idx;
  while (xQueueReceive(fullQ, &idx, 0) == pdTRUE) {
    xQueueSend(freeQ, &idx, 0);
    streamGaps++;  // discarded audio: a calibration window spanning it is dropped
  }
}

// Free space during (or after) a recording, estimated from the space at its start: asking the card means a FAT scan.
// It reads ~0.1% high (the card was full at an estimated 29 MB of 28.2 GB in the 2026-10-25 soak).
static uint32_t recFreeMb() {
  uint32_t usedMb = (uint32_t)((sessionBytesDone + dataBytes) >> 20);
  return freeMbAtStart > usedMb ? freeMbAtStart - usedMb : 0;
}

static void startRecording() {
  errorCode = RERR_NONE;  // a new attempt clears the last error shown on the remote
  if (batlogStopped || !sdReady) {
    Serial.println(batlogStopped ? "REC ignored: battery below cutoff, SD card disabled to protect it."
                                 : "REC ignored: not ready, no SD card mounted (IO40 off).");
    errorCode = RERR_SD_NOT_READY;
    bleStatusChanged();
    return;
  }
  if (freeMb <= LOW_SPACE_STOP_MB) {
    Serial.printf("REC ignored: SD card full (%lu MB free; recordings stop with %d MB left, see LOW_SPACE_STOP_MB).\n",
                  (unsigned long)freeMb, LOW_SPACE_STOP_MB);
    errorCode = RERR_LOW_SPACE;
    bleStatusChanged();
    return;
  }
  uint32_t tStart = millis();
  // Start at the button press: drop the idle audio queued so far, but keep what arrives while the folder and file are
  // made (~160 ms), so that goes into the file.
  drainFullBlocks();
  findNextFreeFile();
  takeIndex = nextFileIndex++;
  char dir[16];
  snprintf(dir, sizeof(dir), "/MMSA8_%04d", takeIndex);
  // If the take's folder can't be made, record into the card's root rather than not at all.
  takeDir = SD.mkdir(dir) ? String(dir) : String("");
  if (!takeDir.length()) Serial.printf("Could not make folder %s; recording into the card's root.\n", dir);
  String name = partPath(1);
  wav = SD.open(name, FILE_WRITE);
  if (!wav) {
    Serial.printf("Could not open %s\n", name.c_str());
    errorCode = RERR_OPEN_FAILED;
    setSdReady(false);
    bleStatusChanged();
    return;
  }
  writeWavHeader(wav, 0);
  dataBytes = 0;
  currentFile = name;
  sessionBytesDone = 0;
  sessionSecsDone = 0;
  sessionFiles = 1;
  sessionFirstFile = name;
  checkpointAt = 0;
  checkpoints = checkpointFails = maxCheckpointUs = 0;
  writeErrors = 0;
  stopPressMs = 0;
  memset(clipTotal, 0, sizeof(clipTotal));
  maxWriteUs = 0;
  sumWriteUs = 0;
  writes = 0;
  backlogActive = false;
  minFreeBlocks = poolBlocks;
  freeMbAtStart = freeMb;
  dmaOverflows = 0;
  poolDrops = 0;
  recStartMs = millis();
  recording = true;
  Serial.printf("REC start: %s (8 ch; file opened in %lu ms)\n", name.c_str(), (unsigned long)(recStartMs - tStart));
  printMode();
  bleStatusChanged();
}

// ---------------- PSRAM + button check (serial 'p', idle only) ----------------
// For checking the REC-button bodge: hammers 1 MB of PSRAM with write/read-back passes for 30 s (all three LEDs lit)
// while the user presses
// REC. If the button were still connected to IO35 (a PSRAM data line), presses would corrupt PSRAM and show as
// errors (or crash). Presses made during the test are counted and then discarded.
static void psramButtonTest() {
  if (!psramFound() || recording) {
    Serial.println(recording ? "PSRAM test: stop recording first." : "PSRAM test: no PSRAM in this build.");
    return;
  }
  const size_t words = 1024 * 1024 / 4;
  uint32_t *buf = (uint32_t *)heap_caps_malloc(words * 4, MALLOC_CAP_SPIRAM);
  if (!buf) {
    Serial.println("PSRAM test: could not allocate 1 MB of PSRAM.");
    return;
  }
  Serial.println("PSRAM test: 30 s, all LEDs lit. Press REC several times now (short presses and one long hold)...");
  digitalWrite(LED_SD, HIGH);
  digitalWrite(LED_REC, HIGH);
  ledcWrite(LED_LEVEL, 255);
  uint32_t presses0 = buttonPressCount, errors = 0, passes = 0, t0 = millis();
  while (millis() - t0 < 30000) {
    uint32_t seed = (passes + 1) * 2654435761u;
    for (size_t i = 0; i < words; i++) buf[i] = seed ^ (uint32_t)(i * 2246822519u);
    for (size_t i = 0; i < words; i++)
      if (buf[i] != (seed ^ (uint32_t)(i * 2246822519u))) errors++;
    passes++;
    drainFullBlocks();  // keep the idle audio pool cycling
    vTaskDelay(1);
  }
  heap_caps_free(buf);
  digitalWrite(LED_SD, sdReady ? HIGH : LOW);  // the other LEDs are rewritten by their updaters
  uint32_t presses = buttonPressCount - presses0;
  resetButton();  // don't act on presses made during the test
  Serial.printf("PSRAM test done: %lu passes over 1 MB, %lu errors, %lu REC presses seen -> %s\n", (unsigned long)passes,
                (unsigned long)errors, (unsigned long)presses,
                errors ? "PSRAM CORRUPTED (button still on a PSRAM line?)"
                       : (presses ? "PASS: button works and PSRAM is undisturbed" : "PSRAM OK, but no presses seen"));
}

// ---------------- Button monitor (serial 'i') ----------------
// For checking the button wiring: for 20 s, prints every level change on BUTTON_PIN and lights the REC LED (IO42)
// while the pin reads pressed (low). Also reports how many presses the interrupt counted.
static void buttonMonitor() {
  if (!buttonEnabled) {
    Serial.println("Button monitor: the button is disabled in this build (it's on a PSRAM pin).");
    return;
  }
  int last = digitalRead(BUTTON_PIN);
  Serial.printf("Button monitor: 20 s. IO%d reads %s. The REC LED lights while the button reads pressed.\n", BUTTON_PIN,
                last ? "HIGH (released)" : "LOW (pressed)");
  ledcWrite(LED_LEVEL, 0);
  uint32_t t0 = millis(), changes = 0, presses0 = buttonPressCount;
  while (millis() - t0 < 20000) {
    int v = digitalRead(BUTTON_PIN);
    digitalWrite(LED_REC, v ? LOW : HIGH);
    if (v != last) {
      changes++;
      Serial.printf("  +%lu ms: IO%d %s\n", (unsigned long)(millis() - t0), BUTTON_PIN, v ? "HIGH (released)" : "LOW (pressed)");
      last = v;
    }
    drainFullBlocks();
    vTaskDelay(pdMS_TO_TICKS(5));
  }
  digitalWrite(LED_REC, LOW);
  resetButton();  // don't act on presses made during the test
  Serial.printf("Button monitor done: %lu level changes, %lu presses counted by the interrupt\n", (unsigned long)changes,
                (unsigned long)(buttonPressCount - presses0));
}

static void stopRecording() {
  recording = false;
  digitalWrite(LED_REC, LOW);
  // wav is already closed if continuing into a new file failed (see rollOver()).
  bool finished = wav ? finishWav() : true;
  float secs = dataBytes / (float)(SAMPLE_RATE * FRAME_BYTES);
  // Wall time up to the stop press, not to the end of writing the queued audio (see stopRecordingAtPress()).
  float wall = ((stopPressMs ? stopPressMs : millis()) - recStartMs) / 1000.0f;
  stopPressMs = 0;
  uint64_t totalBytes = sessionBytesDone + dataBytes;
  if (sessionFiles > 1)
    Serial.printf("REC stop: %s (%.1f s). Recording: %.1f s audio in %lu files from %s (%.2f GB), wall time %.1f s\n",
                  currentFile.c_str(), secs, totalBytes / (float)(SAMPLE_RATE * FRAME_BYTES),
                  (unsigned long)sessionFiles, sessionFirstFile.c_str(), totalBytes / 1073741824.0f, wall);
  else
    Serial.printf("REC stop: %s, %.1f s audio (%lu bytes), wall time %.1f s\n", currentFile.c_str(), secs,
                  (unsigned long)dataBytes, wall);
  if (!finished)
    Serial.printf("  WARNING: could not write %s's final header (card gone?). Its last checkpoint covers all but the "
                  "last %d s.\n", currentFile.c_str(), CHECKPOINT_SECONDS);
  Serial.printf("  Checkpoints: %lu, worst %.1f ms%s\n", (unsigned long)checkpoints, maxCheckpointUs / 1000.0f,
                checkpointFails ? ", SOME FAILED" : "");
  if (writeErrors)
    Serial.printf("  SD write errors recovered from: %lu (each started a new file, no audio lost)\n",
                  (unsigned long)writeErrors);
  {  // per-mic clipping over the whole recording
    char list[160];
    int n = 0;
    uint64_t frames = totalBytes / FRAME_BYTES;
    for (int c = 0; c < CHANNELS; c++)
      if (clipTotal[c] && n < (int)sizeof(list) - 32)
        n += snprintf(list + n, sizeof(list) - n, " mic%d %lu (%.3f%%)", c, (unsigned long)clipTotal[c],
                      frames ? 100.0 * clipTotal[c] / frames : 0.0);
    if (n)
      Serial.printf("  CLIPPING (samples at full scale):%s -> those mics' audio is saturated in places\n", list);
    else
      Serial.println("  Clipping: none");
  }
  Serial.printf("  DMA overflows %lu, pool drops %lu, worst SD write %.1f ms, min free blocks %d/%d -> %s\n",
                (unsigned long)dmaOverflows, (unsigned long)poolDrops, maxWriteUs / 1000.0f, minFreeBlocks, poolBlocks,
                (dmaOverflows == 0 && poolDrops == 0) ? "NO AUDIO LOST" : "AUDIO WAS LOST");
  // Average SD write speed while recording (time inside wav.write only) vs the 768 KB/s the audio needs.
  if (writes)
    Serial.printf("  SD write speed avg %.0f KB/s (need %d KB/s); deepest backlog %d blocks = %lu ms of audio%s\n",
                  writes * (BLOCK_BYTES / 1024.0) / (sumWriteUs / 1e6), SAMPLE_RATE * FRAME_BYTES / 1024,
                  poolBlocks - minFreeBlocks,
                  (unsigned long)((poolBlocks - minFreeBlocks) * BLOCK_FRAMES * 1000UL / SAMPLE_RATE),
                  poolInPsram ? " (PSRAM pool)" : "");
  freeMb = recFreeMb();  // an estimate: this also runs after a failed write, when the card may be gone
  printMode();
  bleStatusChanged();
}

// Continuous recording (see SEGMENT_SECONDS): finishes the full file and carries on in the next one. The reader task
// keeps filling the pool meanwhile, so no audio is lost unless the switch outlasts the pool (~5.5 s with PSRAM).
// Returns false if the next file can't be opened; the recording is then stopped, with its files so far complete.
static bool rollOver() {
  uint32_t t0 = millis();
  String closed = currentFile;
  if (!finishWav()) Serial.printf("  WARNING: could not write %s's final header\n", closed.c_str());
  String name = partPath(sessionFiles + 1);
  wav = SD.open(name, FILE_WRITE);
  if (!wav || !writeWavHeader(wav, 0)) {
    Serial.printf("Could not open %s to continue the recording, stopping. Files up to %s are complete.\n",
                  name.c_str(), closed.c_str());
    if (wav) wav.close();
    stopRecording();  // reports the file just finished
    errorCode = RERR_OPEN_FAILED;
    setSdReady(false);
    bleStatusChanged();
    return false;
  }
  sessionBytesDone += dataBytes;
  sessionSecsDone = (uint32_t)(sessionBytesDone / (SAMPLE_RATE * FRAME_BYTES));
  dataBytes = 0;
  checkpointAt = 0;
  currentFile = name;
  sessionFiles++;
  Serial.printf("REC continues in %s (finished %s; %.1f s recorded so far; switch took %lu ms)\n", name.c_str(),
                closed.c_str(), sessionBytesDone / (float)(SAMPLE_RATE * FRAME_BYTES), (unsigned long)(millis() - t0));
  bleStatusChanged();
  return true;
}

// A block write failed but the card isn't full. That has been a one-off SD error, not a pulled card: in a stress test
// (2026-10-24) one write failed 1.4 s after the PC connected over Bluetooth, and the card remounted at once. The SD
// driver retries a rejected data block 3 times but not other errors. So: finish the file, remount the card only if it
// needs it, and carry on in the next part, starting with the block that failed (still in memory), so no audio is lost.
// The failed file may end with up to a block of extra bytes after its audio; players ignore them. Returns false (the
// caller stops the recording) if the card can't be reached, or if the previous recovery was under 5 s ago.
static bool recoverWrite(const uint8_t *src) {
  uint32_t t0 = millis();
  if (writeErrors && t0 - lastRecoverMs < 5000) return false;
  String failed = currentFile;
  float at = (sessionBytesDone + dataBytes) / (float)(SAMPLE_RATE * FRAME_BYTES);
  wav.close();  // syncs the size; the handle refuses further writes after the error
  bool remounted = false, header = patchWavHeader(failed, dataBytes, true);
  if (!header) {
    remounted = true;
    if (!mountSd()) return false;
    header = patchWavHeader(failed, dataBytes, true);
  }
  String name = partPath(sessionFiles + 1);
  wav = SD.open(name, FILE_WRITE);
  if (!wav || !writeWavHeader(wav, 0) || wav.write(src, BLOCK_BYTES) != BLOCK_BYTES) {
    if (wav) wav.close();
    return false;
  }
  sessionBytesDone += dataBytes;
  sessionSecsDone = (uint32_t)(sessionBytesDone / (SAMPLE_RATE * FRAME_BYTES));
  dataBytes = 0;
  checkpointAt = 0;
  currentFile = name;
  sessionFiles++;
  writeErrors++;
  sdErrorsSinceBoot++;
  lastRecoverMs = millis();
  Serial.printf("SD write failed in %s at %.1f s; recovered in %lu ms%s, carrying on in %s with no audio lost%s\n",
                failed.c_str(), at, (unsigned long)(lastRecoverMs - t0), remounted ? " (card remounted)" : "",
                name.c_str(), header ? "" : " (the failed file's header couldn't be finalized)");
  bleStatusChanged();
  return true;
}

// Writes one full pool block to the recording, moving on to the next file and checkpointing when due. Returns false if
// the recording stopped (failed write, or no next file). The caller returns the block to the pool either way.
static bool recordBlock(int idx) {
  // Continuous recording: this block would overfill the file, so finish it and carry on in the next one.
  if (dataBytes + BLOCK_BYTES > SEGMENT_BYTES && !rollOver()) return false;
  uint32_t t = micros();
  // Mute unfitted mics (empty pads read back as glitchy floating data).
  int16_t *fr = (int16_t *)pool[idx];
  for (int f = 0; f < BLOCK_FRAMES; f++, fr += CHANNELS)
    for (int c = 0; c < CHANNELS; c++)
      if (!MIC_FITTED[c]) fr[c] = 0;
  // A PSRAM block is copied to internal DMA-capable RAM first, so the SD driver gets a buffer it can DMA from.
  const uint8_t *src = pool[idx];
  if (poolInPsram) {
    memcpy(writeBuf, pool[idx], BLOCK_BYTES);
    src = writeBuf;
  }
#ifdef STRESS_HOOKS
  size_t w = failNextWrite ? 0 : wav.write(src, BLOCK_BYTES);  // a simulated failure writes nothing
  failNextWrite = false;
#else
  size_t w = wav.write(src, BLOCK_BYTES);
#endif
  uint32_t dt = micros() - t;
  if (dt > maxWriteUs) maxWriteUs = dt;
  if (dt > hWorstWriteUs) hWorstWriteUs = dt;
  sumWriteUs += dt;
  writes++;
  if (w != BLOCK_BYTES) {
    // A full card fails like a pulled one. Tell them apart by the space there was when the recording began. (A fallback:
    // recordings normally stop at LOW_SPACE_STOP_MB, see loop(), so this means the free-space estimate was off.)
    bool full = recFreeMb() <= 32;
    if (!full && recoverWrite(src)) {
      dataBytes += BLOCK_BYTES;  // the block went into the new file
      levelsBlock((const int16_t *)src);
      return true;
    }
    Serial.println(full ? "SD card full, stopping. The recording's files are complete."
                        : "SD write failed (card pulled?), stopping.");
    stopRecording();
    SD.end();
    errorCode = full ? RERR_CARD_FULL : RERR_WRITE_FAILED;
    setSdReady(false);
    return false;
  }
  dataBytes += BLOCK_BYTES;
  if (dataBytes - checkpointAt >= CHECKPOINT_BYTES) checkpointWav();
  levelsBlock((const int16_t *)src);  // clipping and live levels (src: the block as written)
  return true;
}

// A stop from REC, serial or the remote: first writes the audio still queued in the pool, so the recording keeps
// everything up to the press. Plain stopRecording() dropped that backlog: 0.9 s on a test stop during an SD slowdown
// (2026-10-24), up to the whole pool (~5.5 s) in a long one. The block the reader is still filling (< 21 ms) is lost.
static void stopRecordingAtPress() {
  int pending = uxQueueMessagesWaiting(fullQ), written = 0;
  uint32_t t0 = millis();
  stopPressMs = t0;
  int idx;
  while (pending-- > 0 && recording && xQueueReceive(fullQ, &idx, 0) == pdTRUE) {
    bool ok = recordBlock(idx);
    xQueueSend(freeQ, &idx, 0);
    if (!ok) return;  // a failed write has already stopped the recording
    written++;
  }
  if (written > 3)
    Serial.printf("REC stop: wrote the %d queued blocks (%lu ms of audio) first, in %lu ms\n", written,
                  (unsigned long)(written * BLOCK_FRAMES * 1000UL / SAMPLE_RATE), (unsigned long)(millis() - t0));
  stopRecording();
}

// ---------------- SD-crosstalk snapshot test (serial 's', idle only) ----------------
// Captures alternating chunks of SNAP_CHUNK_BLOCKS blocks: "idle" with the SD bus silent, then "busy" while dummy
// 4 KB writes keep the SD SPI bus running. Both go into /SNAP_NNNN.wav in the order idle, busy, idle, busy, ...
// Analyse with tools/snap_compare.py.
#define SNAP_CHUNK_BLOCKS 10
#define SNAP_PAIRS        8

static void snapshotTest() {
  if (!sdReady) {
    Serial.println("SNAP ignored: no SD card mounted.");
    return;
  }
  int chunk = SNAP_CHUNK_BLOCKS;
  if (chunk > poolBlocks - 2) chunk = poolBlocks - 2;
  char name[24];
  for (int i = 1; i < 10000; i++) {
    snprintf(name, sizeof(name), "/SNAP_%04d.wav", i);
    if (!SD.exists(name)) break;
  }
  File snap = SD.open(name, FILE_WRITE);
  File dummy = SD.open("/snap_busy.bin", FILE_WRITE);
  uint8_t *junk = (uint8_t *)malloc(4096);
  if (!snap || !dummy || !junk) {
    Serial.println("SNAP: could not open files / allocate buffer.");
    if (snap) snap.close();
    if (dummy) dummy.close();
    free(junk);
    return;
  }
  for (int i = 0; i < 4096; i++) junk[i] = (i & 1) ? 0xAA : 0x55;  // toggling data, like real audio traffic
  digitalWrite(LED_REC, HIGH);
  Serial.printf("SNAP start: %s, %d pairs of idle/busy chunks, %d blocks (%d ms) each\n", name, SNAP_PAIRS, chunk,
                chunk * BLOCK_FRAMES * 1000 / SAMPLE_RATE);
  writeWavHeader(snap, 0);
  uint32_t bytes = 0, busyWrites = 0, dropsBefore = poolDrops, ovfBefore = dmaOverflows;
  int got[SNAP_CHUNK_BLOCKS];
  for (int pair = 0; pair < SNAP_PAIRS; pair++) {
    for (int busy = 0; busy <= 1; busy++) {
      drainFullBlocks();
      bool skipFirst = true;  // the block in progress may have started during the previous SD activity
      int n = 0;
      uint32_t t0 = millis();
      while (n < chunk && millis() - t0 < 2000) {
        int idx;
        if (xQueueReceive(fullQ, &idx, busy ? 0 : pdMS_TO_TICKS(5)) == pdTRUE) {
          if (skipFirst) {
            skipFirst = false;
            xQueueSend(freeQ, &idx, 0);
          } else {
            got[n++] = idx;
          }
        }
        if (busy) {
          dummy.write(junk, 4096);
          busyWrites++;
          if (busyWrites % 64 == 0) dummy.seek(0);  // keep the dummy file small (256 KB)
        }
      }
      for (int i = 0; i < n; i++) {
        int16_t *fr = (int16_t *)pool[got[i]];
        for (int f = 0; f < BLOCK_FRAMES; f++, fr += CHANNELS)
          for (int c = 0; c < CHANNELS; c++)
            if (!MIC_FITTED[c]) fr[c] = 0;
        bytes += snap.write(pool[got[i]], BLOCK_BYTES);
        xQueueSend(freeQ, &got[i], 0);
      }
      if (n < chunk) Serial.printf("SNAP: chunk %d/%s only got %d blocks\n", pair, busy ? "busy" : "idle", n);
    }
  }
  dummy.close();
  SD.remove("/snap_busy.bin");
  free(junk);
  writeWavHeader(snap, bytes);
  snap.close();
  digitalWrite(LED_REC, LOW);
  drainFullBlocks();
  Serial.printf("SNAP done: %s, %lu bytes, %lu dummy 4 KB writes during busy chunks. Order: idle,busy,... "
                "chunk = %d frames. (pool drops during test %lu, DMA overflows %lu: expected, between chunks)\n",
                name, (unsigned long)bytes, (unsigned long)busyWrites, chunk * BLOCK_FRAMES,
                (unsigned long)(poolDrops - dropsBefore), (unsigned long)(dmaOverflows - ovfBefore));
}

// ---------------- LEDs / status ----------------
// Flash overlay on all three LEDs, used to confirm a Bluetooth switch. Each pattern lists durations in ms,
// alternating dark / lit and starting dark (so the flash shows even when an LED was already on). While it runs, the
// normal LED updates are paused.
static const uint16_t FLASH_BLE_ON[] = {150, 120, 120, 120, 150};                     // 2 short flashes
static const uint16_t FLASH_BLE_OFF[] = {150, 700, 150};                             // 1 long flash
static const uint16_t FLASH_FAILED[] = {100, 60, 60, 60, 60, 60, 60, 60, 60, 60, 100};  // 5 fast flashes
static const uint16_t *flashPat = NULL;
static int flashLen = 0, flashStep = 0;
static uint32_t flashStepAt = 0;

static void startFlash(const uint16_t *pat, int len) {
  flashPat = pat;
  flashLen = len;
  flashStep = 0;
  flashStepAt = millis();
}

static bool updateFlash() {  // true while the overlay owns the LEDs
  if (!flashPat) return false;
  uint32_t now = millis();
  while (flashStep < flashLen && now - flashStepAt >= flashPat[flashStep]) flashStepAt += flashPat[flashStep++];
  if (flashStep >= flashLen) {
    flashPat = NULL;
    digitalWrite(LED_SD, sdReady ? HIGH : LOW);  // the REC and level LEDs are rewritten by their own updaters
    return false;
  }
  bool lit = flashStep & 1;
  digitalWrite(LED_SD, lit ? HIGH : LOW);
  digitalWrite(LED_REC, lit ? HIGH : LOW);
  ledcWrite(LED_LEVEL, lit ? 255 : 0);
  return true;
}

static void updateRecLed() {
  static uint32_t lastBlink = 0;
  static bool on = false;
  if (!recording) {
    on = false;
  } else if (millis() - lastBlink >= REC_BLINK_MS) {
    lastBlink = millis();
    on = !on;
  }
  digitalWrite(LED_REC, on ? HIGH : LOW);
}

static void updateLevelLed() {
  float rms = loudestRms;
  float gated = 0.0f;
  if (rms > LEVEL_THRESHOLD) {
    gated = (rms - LEVEL_THRESHOLD) / (1.0f - LEVEL_THRESHOLD) * LEVEL_GAIN;
    if (gated > 1.0f) gated = 1.0f;
  }
  float k = gated > levelSmoothed ? LEVEL_ATTACK : LEVEL_RELEASE;
  levelSmoothed = (1.0f - k) * levelSmoothed + k * gated;
  ledcWrite(LED_LEVEL, (uint32_t)(levelSmoothed * 255.0f));
}

static void resetStatus() {
  for (int c = 0; c < CHANNELS; c++) {
    stSq[c] = 0;
    stSum[c] = 0;
    stMin[c] = INT16_MAX;
    stMax[c] = INT16_MIN;
  }
  for (int p = 0; p < CHANNELS / 2; p++) stPairSame[p] = 0;
  stFrames = 0;
}

static void accumulateStatus(const int16_t *s, int frames) {
  for (int f = 0; f < frames; f++) {
    const int16_t *fr = &s[f * CHANNELS];
    for (int c = 0; c < CHANNELS; c++) {
      double v = fr[c];
      stSq[c] += v * v;
      stSum[c] += v;
      if (fr[c] < stMin[c]) stMin[c] = fr[c];
      if (fr[c] > stMax[c]) stMax[c] = fr[c];
    }
    for (int p = 0; p < CHANNELS / 2; p++)
      if (fr[2 * p] == fr[2 * p + 1]) stPairSame[p]++;
  }
  stFrames += frames;
}

static void printStatus() {
  if (recording || stFrames == 0) return;
  static const char *lineName[4] = {"IO5", "IO6", "IO7", "IO8"};
  Serial.print("signal dBFS:");
  double dc[CHANNELS], ac[CHANNELS];
  for (int c = 0; c < CHANNELS; c++) {
    dc[c] = stSum[c] / stFrames;
    double var = stSq[c] / stFrames - dc[c] * dc[c];
    ac[c] = var > 0 ? sqrt(var) : 0;
    if (MIC_FITTED[c])
      Serial.printf(" mic%d %5.1f", c, ac[c] > 0 ? 20 * log10(ac[c] / 32768.0) : -120.0);
    else
      Serial.printf(" mic%d muted", c);
  }
  Serial.print("\n    DC:     ");
  for (int c = 0; c < CHANNELS; c++) {
    if (MIC_FITTED[c])
      Serial.printf(" mic%d %6.0f", c, dc[c]);
    else
      Serial.printf(" mic%d     --", c);
  }
  Serial.println();
  for (int c = 0; c < CHANNELS; c++) {
    if (!MIC_FITTED[c]) continue;
    if (ac[c] < 3.0 && fabs(dc[c]) > 1000)
      Serial.printf("  mic%d: STUCK (steady DC %.0f, no signal): dead or not driving\n", c, dc[c]);
    else if (fabs(dc[c]) > 10000)
      Serial.printf("  mic%d: ABNORMAL (DC %.0f pinned near the rail): mostly not driving, check joints\n", c, dc[c]);
  }
  for (int p = 0; p < CHANNELS / 2; p++) {
    if (!MIC_FITTED[2 * p] || !MIC_FITTED[2 * p + 1]) continue;
    bool flat = stMin[2 * p] == stMax[2 * p] && stMin[2 * p + 1] == stMax[2 * p + 1];
    float same = 100.0f * stPairSame[p] / stFrames;
    if (flat)
      Serial.printf("  %s (mic%d-%d): FLAT, no data on this line (no mics fitted, or line not converted)\n",
                    lineName[p], 2 * p, 2 * p + 1);
    else if (same > 95)
      Serial.printf("  %s (mic%d-%d): pair %.0f%% identical, only ONE mic on this line is driving\n", lineName[p],
                    2 * p, 2 * p + 1, same);
  }
  resetStatus();
}

// ---------------- Battery logger ----------------
// Logs VBAT to /BATLOG.CSV: a "# boot" line on every power-up (with the reset reason), a column header, then one
// line every BATLOG_MS with uptime, VBAT avg/min/max over that interval, and the recording and Bluetooth state at the
// time of the line. Each line is appended and the file closed at once, so nothing is lost when the battery dies.
// Below BATLOG_CUTOFF_MV (interval average) it writes a final line, stops any recording and stops using the SD card.
// Analyse with tools/batlog_analyze.py.
#define VBAT_PIN         9      // BATT_ESP32 = VBAT/2 (100k/100k), ADC1_CH8
#define BATLOG_FILE      "/BATLOG.CSV"
#define BATLOG_MS        30000
#define VBAT_SAMPLE_MS   250
#define BATLOG_CUTOFF_MV 3400
#define VBAT_SMOOTH_N    64     // remote's VBAT: running average over ~64 readings (~16 s). Single readings scatter
                                // about +-70 mV; a 2 s average still wandered +-20 mV and flickered the page's warning.

static uint32_t vbN = 0, vbSum = 0, vbMin = UINT32_MAX, vbMax = 0;
static float vbatFilt = 0.0f;            // float so the slow average doesn't stall on integer rounding
static volatile uint16_t vbatMvNow = 0;  // smoothed VBAT for the remote (see VBAT_SMOOTH_N), 0 = not read yet

static uint32_t readVbatMv() {
  uint32_t s = 0;
  for (int i = 0; i < 16; i++) s += analogReadMilliVolts(VBAT_PIN);
  return s * 2 / 16;  // divider halves VBAT
}

static bool batlogAppend(const char *line) {
  if (!sdReady || batlogStopped) return false;
  File f = SD.open(BATLOG_FILE, FILE_APPEND);
  if (!f) return false;
  f.println(line);
  f.close();
  return true;
}

static const char *resetReasonName() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_EXT: return "external";
    case ESP_RST_DEEPSLEEP: return "deep-sleep";
    default: return "other (USB/flash reset)";
  }
}

static void batlogStart() {
  analogReadResolution(12);
  analogSetPinAttenuation(VBAT_PIN, ADC_11db);
  uint32_t mv = readVbatMv();
  vbatFilt = (float)mv;
  vbatMvNow = (uint16_t)mv;
  char line[160];
  if (mv < BATLOG_CUTOFF_MV) {
    // Booting on an almost-empty battery (e.g. brownout reset loop): don't write to the card at all.
    batlogStopped = true;
    SD.end();
    setSdReady(false);
    Serial.printf("Battery log: VBAT %lu mV at boot is below the %d mV cutoff; SD card left alone.\n",
                  (unsigned long)mv, BATLOG_CUTOFF_MV);
    return;
  }
  snprintf(line, sizeof(line), "# boot, reset=%s, vbat_mV=%lu, interval_s=%d, cutoff_mV=%d, fw=Recorder_BLE",
           resetReasonName(), (unsigned long)mv, BATLOG_MS / 1000, BATLOG_CUTOFF_MV);
  bool ok = batlogAppend(line);
  batlogAppend("uptime_s,vbat_avg_mV,vbat_min_mV,vbat_max_mV,recording,ble");
  snprintf(line, sizeof(line), "0,%lu,%lu,%lu,0,%d", (unsigned long)mv, (unsigned long)mv, (unsigned long)mv,
           bleMode());
  batlogAppend(line);
  Serial.printf("Battery log: %s %s, VBAT %lu mV, a line every %d s, stops below %d mV.\n", BATLOG_FILE,
                ok ? "started" : "NOT written (no SD card)", (unsigned long)mv, BATLOG_MS / 1000, BATLOG_CUTOFF_MV);
}

static void batlogUpdate() {
  static uint32_t lastSample = 0, lastLog = 0;
  uint32_t now = millis();
  if (now - lastSample < VBAT_SAMPLE_MS) return;
  lastSample = now;
  uint32_t mv = readVbatMv();
  vbatFilt = vbatFilt > 0.0f ? vbatFilt + ((float)mv - vbatFilt) / VBAT_SMOOTH_N : (float)mv;
  vbatMvNow = (uint16_t)(vbatFilt + 0.5f);
  vbN++;
  vbSum += mv;
  if (mv < vbMin) vbMin = mv;
  if (mv > vbMax) vbMax = mv;
  if (now - lastLog < BATLOG_MS) return;
  lastLog = now;
  uint32_t avg = vbSum / vbN;
  char line[96];
  snprintf(line, sizeof(line), "%lu,%lu,%lu,%lu,%d,%d", (unsigned long)(now / 1000), (unsigned long)avg,
           (unsigned long)vbMin, (unsigned long)vbMax, recording ? 1 : 0, bleMode());
  vbN = 0;
  vbSum = 0;
  vbMin = UINT32_MAX;
  vbMax = 0;
  Serial.printf("VBAT log: %s\n", line);
  if (batlogStopped) return;
  if (avg < BATLOG_CUTOFF_MV) {
    if (recording) stopRecording();  // finalize the WAV while the card still has good power
    batlogAppend(line);
    batlogAppend("# LOW BATTERY: average below cutoff; logging and SD card use stopped to protect the card");
    batlogStopped = true;
    SD.end();
    setSdReady(false);  // IO40 (record ready) goes off
    Serial.println("Battery below cutoff: SD card disabled.");
    return;
  }
  if (!batlogAppend(line) && sdReady) Serial.println("Battery log: SD write failed");
}

// ---------------- Bluetooth LE ----------------
// All Bluetooth API calls happen in bleTask (switch on/off, status notifications, re-advertising). The NimBLE
// callbacks below run on the NimBLE host task and only set flags, queue record commands for loop() (the only SD
// user) or wake bleTask.
// ---- Keep the radio controller initialised between switches (link-time wrap; needs the build flags in README) ----
// Initialising the controller allocates its interrupts through ESP-IDF's core-0 IPC task, which has a 1 KB stack
// (fixed in the prebuilt Arduino libraries). An interrupt landing during that overflowed it: panic "Stack canary
// watchpoint triggered (ipc0)", about 1 in 20 switch-ons (2026-10-24). The Arduino BLE library initialises the
// controller on every start and tears it down on every stop, so these wrappers make it initialise once (in the boot
// warm-up, before the mics and audio task start) and only disable/enable it after that. Disable still powers the radio
// and Bluetooth modem down; only the controller's memory stays allocated.
static volatile bool btCtrlWrapActive = false;
extern "C" esp_err_t __real_esp_bt_controller_init(esp_bt_controller_config_t *cfg);
extern "C" esp_err_t __wrap_esp_bt_controller_init(esp_bt_controller_config_t *cfg) {
  btCtrlWrapActive = true;
  if (esp_bt_controller_get_status() != ESP_BT_CONTROLLER_STATUS_IDLE) return ESP_OK;  // already initialised: reuse
  return __real_esp_bt_controller_init(cfg);
}
extern "C" esp_err_t __wrap_esp_bt_controller_deinit(void) {
  return ESP_OK;  // keep it initialised; esp_bt_controller_disable() has already powered it down
}

// The one controller init that remains (the boot warm-up) still allocates interrupts through the IPC task, and that
// panicked once at boot (2026-10-24, PSRAM build). Those calls come from the controller's own task ("btController",
// core 0) asking for core 0, i.e. its own core. For such same-core calls from the Bluetooth tasks, run the function
// directly on the caller's stack (when it has > 2 KB free) instead of handing it to the 1 KB IPC task. Every other IPC
// call goes through unchanged. (Link flag -Wl,--wrap=esp_ipc_call_blocking.)
static volatile uint32_t ipcDirectCalls = 0, ipcViaTask = 0;
extern "C" esp_err_t __real_esp_ipc_call_blocking(uint32_t cpu_id, esp_ipc_func_t func, void *arg);
extern "C" esp_err_t __wrap_esp_ipc_call_blocking(uint32_t cpu_id, esp_ipc_func_t func, void *arg) {
  TaskHandle_t me = xTaskGetCurrentTaskHandle();
  bool btTask = (bleTaskHandle != NULL && me == bleTaskHandle) || strcmp(pcTaskGetName(me), "btController") == 0;
  uint8_t here;
  size_t stackFree = (size_t)(&here - pxTaskGetStackStart(me));
  if (btTask && cpu_id == (uint32_t)xPortGetCoreID() && stackFree > 2048) {
    func(arg);
    ipcDirectCalls++;
    return ESP_OK;
  }
  if (btTask) ipcViaTask++;
  return __real_esp_ipc_call_blocking(cpu_id, func, arg);
}

static BLEServer *bleServer = NULL;
static BLEService *bleService = NULL;
static BLECharacteristic *bleControlChr = NULL, *bleTimeChr = NULL, *bleStatusChr = NULL, *bleLevelsChr = NULL,
                         *bleCalChr = NULL;
static ble_gap_event_listener bleGapListener;
static size_t bleHeapAtFirstStart = 0;  // free RAM just before Bluetooth was first switched on (leak check)
static uint32_t bleCycles = 0;

class ControlCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String v = c->getValue();
    if (v.length() == 0) return;
    uint8_t b = (uint8_t)v[0];
    uint8_t cmd;
    if (b == 'C') {
      // Calibration check: 'C', seconds (u8, 0 = default), then 0-4 tones as u16 Hz little-endian (none = 1 kHz).
      CalSpec s = {};
      s.seconds = v.length() > 1 ? (uint8_t)v[1] : 0;
      for (size_t i = 2; i + 1 < v.length() && s.n < CAL_MAX_TONES; i += 2)
        s.hz[s.n++] = (uint16_t)((uint8_t)v[i] | ((uint8_t)v[i + 1] << 8));
      portENTER_CRITICAL(&calMux);
      calReq = s;
      portEXIT_CRITICAL(&calMux);
      cmd = CMD_CAL;
    } else if (b == 'K') {
      cmd = CMD_CAL_SAVE;  // keep the last check as the baseline
    } else {
      cmd = (b == 1 || b == '1') ? CMD_START : (b == 0 || b == '0') ? CMD_STOP : CMD_TOGGLE;
    }
    xQueueSend(cmdQ, &cmd, 0);
  }
};

// The remote writes local wall-clock time (Unix seconds shifted by its UTC offset) on connect. With TZ left at UTC,
// FatFS then stamps WAV files with the right local date. Survives a reset, not a power loss.
class TimeCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    String v = c->getValue();
    if (v.length() < 4) return;
    uint32_t secs;
    memcpy(&secs, v.c_str(), 4);
    struct timeval tv = {(time_t)secs, 0};
    settimeofday(&tv, NULL);
    time_t t = (time_t)secs;
    struct tm tmv;
    localtime_r(&t, &tmv);
    char stamp[24];
    strftime(stamp, sizeof(stamp), "%Y-%m-%d %H:%M:%S", &tmv);
    Serial.printf("Clock set over Bluetooth: %s\n", stamp);
  }
};

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *) override {
    bleConnected = true;
    Serial.println("Bluetooth: remote connected");
    printMode();
    bleStatusChanged();
  }
  void onDisconnect(BLEServer *) override {
    bleConnected = false;
    if (bleStopping) return;
    Serial.println("Bluetooth: remote disconnected, advertising again");
    printMode();
    bleWake(EVT_READVERTISE | EVT_STATUS);
  }
};

static ControlCallbacks controlCb;
static TimeCallbacks timeCb;
static ServerCallbacks serverCb;

static const char *disconnectReasonText(uint8_t hci) {
  switch (hci) {
    case BLE_ERR_CONN_SPVN_TMO: return "link lost / supervision timeout (signal, range or interference)";
    case BLE_ERR_REM_USER_CONN_TERM: return "closed by the computer/browser";
    case BLE_ERR_CONN_TERM_LOCAL: return "closed by this device (firmware)";
    case BLE_ERR_LMP_LL_RSP_TMO: return "link-layer response timeout";
    case BLE_ERR_CONN_ESTABLISHMENT: return "connection failed to establish (signal)";
    case BLE_ERR_CONN_TERM_MIC: return "packet integrity check failed (interference)";
    default: return "other";
  }
}

// GAP listener: tracks the connection handle (for RSSI and for closing the link on switch-off) and the real
// disconnect reason, which BLEServerCallbacks doesn't pass along.
static int onBleGapEvent(struct ble_gap_event *event, void *) {
  ble_gap_conn_desc desc;
  switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
      if (event->connect.status == 0) {
        bleConnHandle = event->connect.conn_handle;
        bleRssi = 0;
        if (ble_gap_conn_find(event->connect.conn_handle, &desc) == 0)
          Serial.printf("Bluetooth link up: interval %.2f ms, latency %u, supervision timeout %u ms\n",
                        desc.conn_itvl * 1.25f, desc.conn_latency, desc.supervision_timeout * 10);
        // Ask for bigger packets: the live-levels message is 60 bytes, and the default ATT packet carries only 20.
        // Some browsers (Chrome on Windows, iOS) negotiate this themselves; asking from this side covers the rest.
        ble_gattc_exchange_mtu(event->connect.conn_handle, NULL, NULL);
      }
      break;
    case BLE_GAP_EVENT_MTU:
      Serial.printf("Bluetooth packet size (MTU): %u bytes\n", (unsigned)event->mtu.value);
      break;
    case BLE_GAP_EVENT_CONN_UPDATE:
      if (event->conn_update.status == 0 && ble_gap_conn_find(event->conn_update.conn_handle, &desc) == 0)
        Serial.printf("Bluetooth link params: interval %.2f ms, latency %u, supervision timeout %u ms\n",
                      desc.conn_itvl * 1.25f, desc.conn_latency, desc.supervision_timeout * 10);
      break;
    case BLE_GAP_EVENT_DISCONNECT: {
      int r = event->disconnect.reason;
      uint8_t hci = (r >= BLE_HS_ERR_HCI_BASE && r < BLE_HS_ERR_HCI_BASE + 0x100) ? (uint8_t)(r - BLE_HS_ERR_HCI_BASE)
                                                                                  : 0xFF;
      bleLastDisconnectReason = hci;
      bleConnHandle = BLE_HS_CONN_HANDLE_NONE;
      Serial.printf("Bluetooth link down: reason 0x%02X (%s), last RSSI %d dBm\n", hci, disconnectReasonText(hci),
                    (int)bleRssi);
      break;
    }
    default:
      break;
  }
  return 0;
}

static void bleSendStatus() {
  if (!bleStatusChr) return;
  uint32_t bytes = dataBytes;
  uint32_t secsDone = sessionSecsDone;
  uint32_t mb = freeMb;
  if (recording) {
    uint32_t usedMb = (uint32_t)(((uint64_t)secsDone * SAMPLE_RATE * FRAME_BYTES + bytes) >> 20);
    mb = freeMbAtStart > usedMb ? freeMbAtStart - usedMb : 0;
  }
  uint32_t recSecs = secsDone + bytes / (SAMPLE_RATE * FRAME_BYTES);
  uint8_t err = errorCode;
  uint8_t flags = 0;
  if (recording) flags |= STATUS_FLAG_RECORDING;
  if (sdReady) flags |= STATUS_FLAG_SD_READY;
  if (sdReady && mb < LOW_SPACE_WARN_MB) flags |= STATUS_FLAG_LOW_SPACE;
  if (err != RERR_NONE) flags |= STATUS_FLAG_ERROR;
  uint8_t clips = clipMask;
  if (clips) flags |= STATUS_FLAG_CLIPPING;
  if (batlogStopped) flags |= STATUS_FLAG_BATT_LOW;
  uint16_t vbat = vbatMvNow;
  uint8_t p[19];
  p[0] = flags;
  memcpy(p + 1, &bytes, 4);
  memcpy(p + 5, &mb, 4);
  p[9] = err;
  p[10] = (uint8_t)bleRssi;
  p[11] = bleLastDisconnectReason;
  memcpy(p + 12, &recSecs, 4);
  p[16] = clips;
  memcpy(p + 17, &vbat, 2);  // battery, mV (smoothed; see batlogUpdate())
  bleStatusChr->setValue(p, sizeof(p));
  if (bleConnected) bleStatusChr->notify();
}

static bool bleStart() {
  uint32_t t0 = millis();
  if (!btCtrlWrapActive) {
    Serial.println("Bluetooth NOT started: this build lacks the link flags that keep the radio controller initialised "
                   "(see README, Build). Without them, switching Bluetooth on can crash the board.");
    return false;
  }
  size_t before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  if (before < BLE_MIN_FREE) {
    Serial.printf("Bluetooth NOT started: only %u bytes of RAM free, %u needed (Bluetooth ~40 KB + room for the SD "
                  "card). Reset the board: each on/off cycle leaks a little RAM.\n",
                  (unsigned)before, (unsigned)BLE_MIN_FREE);
    return false;
  }
  if (bleHeapAtFirstStart == 0) bleHeapAtFirstStart = before;
  bleStopping = false;
  bleConnected = false;
  bleConnHandle = BLE_HS_CONN_HANDLE_NONE;
  bleRssi = 0;
  if (!BLEDevice::init(BLE_DEVICE_NAME)) {
    Serial.println("Bluetooth NOT started: BLEDevice::init failed (out of RAM, or the controller didn't shut down "
                   "cleanly last time; a reset clears it).");
    return false;
  }
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(&serverCb);
  ble_gap_event_listener_register(&bleGapListener, onBleGapEvent, NULL);  // EALREADY after a restart is fine
  bleService = bleServer->createService(BLEUUID(BLE_SERVICE_UUID), 30);  // room for 5 characteristics
  bleControlChr = bleService->createCharacteristic(BLE_CONTROL_CHAR_UUID, BLECharacteristic::PROPERTY_WRITE);
  bleControlChr->setCallbacks(&controlCb);
  bleTimeChr = bleService->createCharacteristic(BLE_TIME_CHAR_UUID, BLECharacteristic::PROPERTY_WRITE);
  bleTimeChr->setCallbacks(&timeCb);
  bleStatusChr = bleService->createCharacteristic(BLE_STATUS_CHAR_UUID,
                                                  BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  bleLevelsChr = bleService->createCharacteristic(BLE_LEVELS_CHAR_UUID,
                                                  BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  bleCalChr = bleService->createCharacteristic(BLE_CAL_CHAR_UUID,
                                               BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  {
    uint8_t m[CAL_MSG_MAX];
    portENTER_CRITICAL(&calMux);
    uint16_t len = calMsgLen;
    memcpy(m, calMsg, len);
    portEXIT_CRITICAL(&calMux);
    if (len) bleCalChr->setValue(m, len);  // the last check, for the remote's first read
  }
  bleSendStatus();  // initial value for the remote's first read
  bleService->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(BLE_SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
  bleOn = true;
  size_t after = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  Serial.printf("Bluetooth ON: advertising as \"%s\" (%lu ms; uses %u bytes of RAM, %u still free)\n", BLE_DEVICE_NAME,
                (unsigned long)(millis() - t0), (unsigned)(before - after), (unsigned)after);
  return true;
}

static void bleStop() {
  uint32_t t0 = millis();
  bleStopping = true;
  uint16_t h = bleConnHandle;
  if (h != BLE_HS_CONN_HANDLE_NONE) {
    // Close the link politely first, so the remote sees a clean disconnect instead of a timeout.
    ble_gap_terminate(h, BLE_ERR_REM_USER_CONN_TERM);
    for (int i = 0; i < 50 && bleConnHandle != BLE_HS_CONN_HANDLE_NONE; i++) vTaskDelay(pdMS_TO_TICKS(10));
  }
  bleOn = false;
  // false = keep the controller's memory reserved so Bluetooth can be started again (true would release it for good).
  BLEDevice::deinit(false);
  // deinit deletes the server but not its service and characteristics; free them so repeated switching doesn't leak
  // (the service's destructor is private in the library; see the includes). Service first: its destructor only frees
  // its own GATT tables. The line below prints any remaining loss so it can be checked on the bench.
  delete bleService;
  delete bleControlChr;
  delete bleTimeChr;
  delete bleStatusChr;
  delete bleLevelsChr;
  delete bleCalChr;
  bleControlChr = bleTimeChr = bleStatusChr = bleLevelsChr = bleCalChr = NULL;
  bleService = NULL;
  bleServer = NULL;
  bleConnected = false;
  bleConnHandle = BLE_HS_CONN_HANDLE_NONE;
  bleCycles++;
  vTaskDelay(pdMS_TO_TICKS(50));  // let the idle task free the stopped NimBLE host task's stack before measuring
  size_t freeNow = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  long lost = (long)bleHeapAtFirstStart - (long)freeNow;
  Serial.printf("Bluetooth OFF: stack shut down, radio off (%lu ms; %u bytes of RAM free, %ld lost over %lu "
                "on/off cycles)\n", (unsigned long)(millis() - t0), (unsigned)freeNow, lost,
                (unsigned long)bleCycles);
}

// The first Bluetooth start after power-up runs the radio's full RF calibration, which stalls long enough to overflow
// the I2S DMA (2026-10-24: 1 DMA overflow on the first switch-on during a recording, on two boots out of two; none on
// later switch-ons). Run that first start once here, before the PDM clock starts and with no advertising, so every
// switch-on after boot is the quick kind.
static volatile bool bleWarmedUp = false;
static void bleWarmUp() {
  uint32_t t0 = millis();
  bool ok = BLEDevice::init(BLE_DEVICE_NAME);
  if (ok) BLEDevice::deinit(false);
  Serial.printf("Bluetooth warm-up (controller init + RF calibration) %s in %lu ms (%lu interrupt setup(s) run directly, "
                "bypassing the 1 KB IPC task); Bluetooth is off.%s\n",
                ok ? "done" : "FAILED", (unsigned long)(millis() - t0), (unsigned long)ipcDirectCalls,
                btCtrlWrapActive ? "" : " WARNING: built without the controller link flags (see README); "
                                        "Bluetooth switching is disabled.");
  if (ipcViaTask)
    Serial.printf("WARNING: %lu Bluetooth interrupt setups still went through the 1 KB IPC task\n",
                  (unsigned long)ipcViaTask);
  bleWarmedUp = true;
}

static void bleTask(void *) {
  bleWarmUp();
  uint32_t lastStatus = 0;
  for (;;) {
    uint32_t ev = 0;
    xTaskNotifyWait(0, UINT32_MAX, &ev, pdMS_TO_TICKS(BLE_STATUS_MS));
    if (ev & EVT_TOGGLE) {
      if (bleOn) {
        bleStop();
        bleResult = BLERES_OFF;
      } else {
        bleResult = bleStart() ? BLERES_ON : BLERES_FAILED;
      }
      printMode();
    }
    if (!bleOn) continue;
    if ((ev & EVT_READVERTISE) && !bleConnected) BLEDevice::startAdvertising();
    if ((ev & EVT_LEVELS) && bleConnected && bleLevelsChr) {
      uint8_t m[LEVELS_MSG_BYTES];
      portENTER_CRITICAL(&levelsMux);
      memcpy(m, levelsMsg, sizeof(m));
      portEXIT_CRITICAL(&levelsMux);
      bleLevelsChr->setValue(m, sizeof(m));
      bleLevelsChr->notify();
    }
    if ((ev & EVT_CAL) && bleCalChr) {
      uint8_t m[CAL_MSG_MAX];
      portENTER_CRITICAL(&calMux);
      uint16_t len = calMsgLen;
      memcpy(m, calMsg, len);
      portEXIT_CRITICAL(&calMux);
      bleCalChr->setValue(m, len);
      if (bleConnected) bleCalChr->notify();
    }
    // Status on a change, and as a heartbeat every BLE_STATUS_MS. Levels wake this task 4 times a second, so the
    // heartbeat keeps its own clock rather than relying on the wait timing out.
    if ((ev & ~EVT_LEVELS) || millis() - lastStatus >= BLE_STATUS_MS) {
      uint16_t h = bleConnHandle;
      int8_t rssi;
      if (bleConnected && h != BLE_HS_CONN_HANDLE_NONE && ble_gap_conn_rssi(h, &rssi) == 0) bleRssi = rssi;
      bleSendStatus();
      lastStatus = millis();
    }
  }
}

// ---------------- Health line (every HEALTH_MS, and serial 'h') ----------------
// One line for long unattended runs (tools/soak_log.py logs and summarises them): uptime, state, internal heap (free,
// lowest ever, largest block), PSRAM free, and since the previous line the deepest pool backlog and slowest SD write.
#define HEALTH_MS 60000
static void printHealth() {
  uint32_t secs = sessionSecsDone + dataBytes / (SAMPLE_RATE * FRAME_BYTES);
  uint32_t mb = recording ? recFreeMb() : freeMb;
  int backlog = poolBlocks - (hMinFree < poolBlocks ? hMinFree : poolBlocks);
  Serial.printf("HEALTH: up=%lu rec=%d take=%d part=%lu recsecs=%lu free_mb=%lu heap=%u heapmin=%u heapblk=%u "
                "psram=%u backlog_ms=%lu write_ms=%.1f ovf=%lu drops=%lu ble=%d sd=%d sderr=%lu btnnoise=%lu clip=%lu "
                "clipmask=%u\n",
                (unsigned long)(millis() / 1000), recording ? 1 : 0, takeIndex, (unsigned long)sessionFiles,
                (unsigned long)secs, (unsigned long)mb, (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
                (unsigned long)(backlog * BLOCK_FRAMES * 1000UL / SAMPLE_RATE), hWorstWriteUs / 1000.0f,
                (unsigned long)dmaOverflows, (unsigned long)poolDrops, bleMode(), sdReady ? 1 : 0,
                (unsigned long)sdErrorsSinceBoot, (unsigned long)buttonNoise, (unsigned long)clipSum(),
                (unsigned)clipMask);
  hMinFree = poolBlocks;
  hWorstWriteUs = 0;
}

// ---------------- setup / loop ----------------
void setup() {
  Serial.begin(115200);
  // USB serial must never block. With USB plugged into a PC that isn't reading the port, each print otherwise
  // waits up to 100 ms (up to ~2 s total), stalling loop() long enough to miss REC presses.
  Serial.setTxTimeoutMs(0);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  // IO33-37 are the octal PSRAM's lines inside this module (WROOM-1-N8R8). In a PSRAM build, never touch them: a press
  // of the IO35 button would pull a PSRAM data line low and corrupt memory. Until the button is moved to a free pin
  // (IO10/15/16; set BUTTON_PIN), a PSRAM build runs with the button disabled (use serial or the remote).
  buttonEnabled = !(psramFound() && BUTTON_PIN >= 33 && BUTTON_PIN <= 37);
  if (buttonEnabled) {
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    attachInterrupt(BUTTON_PIN, onButtonEdge, CHANGE);
  }
  pinMode(LED_SD, OUTPUT);
  pinMode(LED_REC, OUTPUT);
  digitalWrite(LED_SD, LOW);
  digitalWrite(LED_REC, LOW);
  if (!ledcAttach(LED_LEVEL, 5000, 8)) Serial.println("WARNING: ledcAttach(IO41) failed, loudness LED will stay dark");
  ledcWrite(LED_LEVEL, 0);

  Serial.printf("\nBoot, reset reason: %s\n", resetReasonName());
  if (buttonEnabled)
    Serial.printf("REC button on IO%d reads %s.\n", BUTTON_PIN,
                  digitalRead(BUTTON_PIN) ? "HIGH (released, as expected)" : "LOW (pressed or shorted to GND?)");
  if (!buttonEnabled)
    Serial.printf("PSRAM build: REC button on IO%d is DISABLED (that pin is a PSRAM data line). Don't press it; use "
                  "serial 'r'/'b' or the remote until the button is moved to a free pin.\n", BUTTON_PIN);
  setSdReady(mountSd());
  batlogStart();

  // Bluetooth task on core 0, the core the radio controller is pinned to. Started from core 1, the controller hands
  // its interrupt setup to ESP-IDF's core-0 IPC task, whose 1 KB stack overflowed when an interrupt landed during it
  // (panic "Stack canary watchpoint triggered (ipc0)" while switching on mid-recording, 2026-10-24). The task first
  // runs the warm-up (see bleWarmUp()); wait for it before starting the PDM clock and sizing the pool.
  cmdQ = xQueueCreate(8, sizeof(uint8_t));
  xTaskCreatePinnedToCore(bleTask, "ble", 6144, NULL, 1, &bleTaskHandle, 0);
  uint32_t tw = millis();
  while (!bleWarmedUp && millis() - tw < 3000) delay(10);
  startPdm();

  // Audio pool from what's left, keeping SD_HEAP_HEADROOM + BLE_HEAP_RESERVE free, plus room for the card's mount
  // if it isn't mounted yet (otherwise a card that mounts after boot eats the Bluetooth reserve; seen 2026-10-24).
  size_t heapBefore = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  size_t keep = SD_HEAP_HEADROOM + BLE_HEAP_RESERVE + (sdReady ? 0 : SD_MOUNT_RAM);
  freeQ = xQueueCreate(POOL_SLOTS, sizeof(int));
  fullQ = xQueueCreate(POOL_SLOTS, sizeof(int));
  // With PSRAM: one 4 MB block in PSRAM, sliced into 16 KB pool blocks, plus a 16 KB internal buffer for SD writes.
  uint8_t *big = psramFound() ? (uint8_t *)heap_caps_malloc(PSRAM_POOL_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)
                              : NULL;
  writeBuf = big ? (uint8_t *)heap_caps_malloc(BLOCK_BYTES, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA) : NULL;
  if (big && writeBuf) {
    poolInPsram = true;
    for (int i = 0; i < POOL_SLOTS; i++) {
      pool[i] = big + (size_t)i * BLOCK_BYTES;
      xQueueSend(freeQ, &i, 0);
      poolBlocks++;
    }
  } else if (big) {
    heap_caps_free(big);
    Serial.println("WARNING: no internal RAM for the SD write buffer; using the internal pool instead of PSRAM");
  }
  for (int i = 0; !poolInPsram && i < POOL_BLOCKS_MAX; i++) {
    bool roomy = heap_caps_get_free_size(MALLOC_CAP_INTERNAL) >= BLOCK_BYTES + keep &&
                 heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL) >= BLOCK_BYTES + 4096;
    if (!roomy && poolBlocks >= POOL_BLOCKS_MIN) break;
    pool[i] = (uint8_t *)heap_caps_malloc(BLOCK_BYTES, MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    if (!pool[i]) break;
    xQueueSend(freeQ, &i, 0);
    poolBlocks++;
  }
  minFreeBlocks = poolBlocks;
  Serial.printf("\nBuffer pool: %d x %d KB = %d KB (~%d ms) in %s. Free internal RAM: %u before the pool, %u after "
                "(keeping %u for SD%s + %u for Bluetooth)\n",
                poolBlocks, BLOCK_BYTES / 1024, poolBlocks * BLOCK_BYTES / 1024,
                poolBlocks * BLOCK_FRAMES * 1000 / SAMPLE_RATE, poolInPsram ? "PSRAM" : "internal RAM",
                (unsigned)heapBefore,
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL), (unsigned)(keep - BLE_HEAP_RESERVE),
                sdReady ? "" : " incl. a later card mount", BLE_HEAP_RESERVE);
  Serial.printf("Clip warning on (full scale ~120 dB SPL). Live levels to the remote: %s\n",
                levelsInit() ? "peak + 5 bands (20-125, 125-500, 500-2k, 2k-8k, 8k-20k Hz), 4 a second"
                             : "peak and clipping only (no PSRAM for the band analysis)");
  xTaskCreatePinnedToCore(readerTask, "i2sReader", 4096, NULL, configMAX_PRIORITIES - 2, NULL, 0);

  resetStatus();
  Serial.println("MMSA V2 8-channel recorder with Bluetooth switch.");
  Serial.printf("WAV: %d Hz 16-bit, 8 ch (PDM clock %.3f MHz). ", SAMPLE_RATE, SAMPLE_RATE * 64 / 1e6);
  Serial.println(" mic0-1 IO5, mic2-3 IO6, mic4-5 IO7, mic6-7 IO8 (WAV track N+1 = mic N).");
  Serial.printf("Files: a folder per take, a new file every %d s, checkpoints every %d s.\n", SEGMENT_SECONDS,
                CHECKPOINT_SECONDS);
#ifdef STRESS_HOOKS
  Serial.println("TEST BUILD: serial F makes the next SD block write count as failed.");
#endif
  Serial.println("REC: short press = start/stop recording, hold 1 s = Bluetooth on/off.");
  Serial.println("     Flashes on all LEDs: 2 short = Bluetooth ON, 1 long = OFF, 5 fast = failed.");
  Serial.println("Serial: r = record, b = Bluetooth, h = health line, s = SD-crosstalk snapshot test, p = PSRAM + button "
                 "check, i = button monitor, c = calibration check (1 kHz, 10 s), k = keep the last check as the "
                 "baseline.");
  calLoadBaseline();
  Serial.println("LEDs: IO40 record ready (SD mounted), IO41 loudness, IO42 blinks while recording.");
  if (BLE_ON_AT_BOOT) requestBleToggle();
  printMode();
}

// REC button: a short press (down MIN_PRESS_MS or more, released before BLE_HOLD_MS) toggles recording on release.
// Holding BLE_HOLD_MS switches Bluetooth at once, while still held. After that hold the button is ignored until it
// has been up for AFTER_HOLD_MS without a break, so the release (and its bounce) can never start or stop a recording,
// whichever way Bluetooth was switched and whether or not it's recording; only a new full press counts. Before
// 2026-10-24 any falling edge counted as a press once 50 ms had passed, even if the pin was low for a moment: a
// recording started after nearly every Bluetooth hold. Press and release times come from the interrupt, so a busy
// loop() still times them right. Returns true for a short press.
static bool handleButton() {
  static uint32_t pressAt = 0, quietFrom = 0;
  if (!buttonEnabled) return false;  // a PSRAM build with REC on a PSRAM pin: never touch the pin
  uint32_t now = millis();
  bool up = digitalRead(BUTTON_PIN) == HIGH;
  bool released = up && now - lastRiseMs >= RELEASE_MS;  // up continuously since lastRiseMs
  switch (btnState) {
    case BTN_IDLE:
      if (!buttonPressed) return false;
      buttonPressed = false;
      pressAt = lastPressMs;
      btnState = BTN_PRESSED;
      return false;
    case BTN_PRESSED:
      if (released) {
        btnState = BTN_IDLE;
        uint32_t downMs = lastRiseMs - pressAt;
        if (downMs < MIN_PRESS_MS) {
          buttonNoise++;
          Serial.printf("REC press ignored: down only %lu ms (bounce or noise)\n", (unsigned long)downMs);
          return false;
        }
        Serial.println("REC button");
        return true;
      }
      if (!up && now - pressAt >= BLE_HOLD_MS) {
        btnState = BTN_HELD;
        Serial.println("REC held: switching Bluetooth (release REC; it counts again once up for 0.5 s)");
        requestBleToggle();
      }
      return false;
    case BTN_HELD:
      if (released) {
        btnState = BTN_AFTER_HOLD;
        quietFrom = now;
      }
      return false;
    case BTN_AFTER_HOLD:
      if (!up || buttonPressed) {  // any press or blip restarts the quiet time
        buttonPressed = false;
        quietFrom = now;
      } else if (now - quietFrom >= AFTER_HOLD_MS) {
        btnState = BTN_IDLE;
      }
      return false;
  }
  return false;
}

void loop() {
  static uint32_t lastStatus = 0;
  bool toggle = handleButton();
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'r' || c == 'R') {
      Serial.println("'r'");
      toggle = true;
    }
    if (c == 'b' || c == 'B') {
      Serial.println("'b': switching Bluetooth");
      requestBleToggle();
    }
    if ((c == 's' || c == 'S') && !recording) snapshotTest();
    if (c == 'p' || c == 'P') psramButtonTest();
    if (c == 'h' || c == 'H') printHealth();
#ifdef STRESS_HOOKS
    if (c == 'F' && recording) {
      failNextWrite = true;
      Serial.println("'F' (test build): the next block write counts as failed");
    }
#endif
    if ((c == 'i' || c == 'I') && !recording) buttonMonitor();
    if (c == 'c') {
      CalSpec s = {};  // defaults: 1 kHz for 10 s
      calStart(s);
    }
    if (c == 'k') calSaveBaseline();
  }
  if (toggle) recording ? stopRecordingAtPress() : startRecording();
  uint8_t cmd;
  while (xQueueReceive(cmdQ, &cmd, 0) == pdTRUE) {
    if (cmd == CMD_CAL) {
      portENTER_CRITICAL(&calMux);
      CalSpec s = calReq;
      portEXIT_CRITICAL(&calMux);
      Serial.println("CAL via Bluetooth remote");
      calStart(s);
      continue;
    }
    if (cmd == CMD_CAL_SAVE) {
      Serial.println("CAL baseline save via Bluetooth remote");
      calSaveBaseline();
      continue;
    }
    bool want = cmd == CMD_TOGGLE ? !recording : cmd == CMD_START;
    if (want == recording) {
      bleStatusChanged();  // already in that state: just re-confirm to the remote
      continue;
    }
    Serial.println("REC via Bluetooth remote");
    want ? startRecording() : stopRecordingAtPress();
  }

  // Bluetooth switch finished: confirm on the LEDs.
  uint8_t r = bleResult;
  if (r != BLERES_NONE) {
    bleResult = BLERES_NONE;
    if (r == BLERES_ON) startFlash(FLASH_BLE_ON, sizeof(FLASH_BLE_ON) / sizeof(FLASH_BLE_ON[0]));
    else if (r == BLERES_OFF) startFlash(FLASH_BLE_OFF, sizeof(FLASH_BLE_OFF) / sizeof(FLASH_BLE_OFF[0]));
    else startFlash(FLASH_FAILED, sizeof(FLASH_FAILED) / sizeof(FLASH_FAILED[0]));
  }

  // Consume full blocks: write to SD while recording, otherwise feed the idle status stats.
  int idx;
  if (xQueueReceive(fullQ, &idx, pdMS_TO_TICKS(20)) == pdTRUE) {
    if (recording) {
      int freeNow = uxQueueMessagesWaiting(freeQ);
      if (freeNow < minFreeBlocks) minFreeBlocks = freeNow;
      if (freeNow < hMinFree) hMinFree = freeNow;
      // SD slowdown report: once the backlog passes what an internal-RAM pool could hold, follow the episode and
      // print it when the backlog has drained (printing during the stall would only add to it).
      int backlog = poolBlocks - freeNow;
      if (!backlogActive && backlog >= BACKLOG_REPORT_BLOCKS) {
        backlogActive = true;
        backlogPeak = backlog;
        backlogStartMs = millis();
      } else if (backlogActive) {
        if (backlog > backlogPeak) backlogPeak = backlog;
        if (backlog <= 3) {
          backlogActive = false;
          Serial.printf("  SD slowdown absorbed at +%lu ms: backlog peaked at %d blocks (%lu ms of audio), drained "
                        "after %lu ms\n", (unsigned long)(backlogStartMs - recStartMs), backlogPeak,
                        (unsigned long)(backlogPeak * BLOCK_FRAMES * 1000UL / SAMPLE_RATE),
                        (unsigned long)(millis() - backlogStartMs));
        }
      }
      if (!recordBlock(idx)) {  // the recording stopped (failed write, or no next file)
        xQueueSend(freeQ, &idx, 0);
        return;
      }
    } else {
      accumulateStatus((const int16_t *)pool[idx], BLOCK_FRAMES);
      levelsBlock((const int16_t *)pool[idx]);  // clipping and live levels while idle too (e.g. checking a mount)
    }
    xQueueSend(freeQ, &idx, 0);
    // Stop before the card fills up (see LOW_SPACE_STOP_MB), writing the queued audio first, as a stop press does.
    // "SD card full" is what tools/soak_log.py looks for.
    if (recording && recFreeMb() <= LOW_SPACE_STOP_MB) {
      Serial.printf("SD card full: %lu MB left, the reserve kept so the card never fills to the end (it stalls there). "
                    "Stopping; the recording's files are complete.\n", (unsigned long)recFreeMb());
      errorCode = RERR_CARD_FULL;  // set first: stopRecording() sends the status, and a failed write overrides it
      stopRecordingAtPress();
    }
  }

  if (!updateFlash()) {
    updateLevelLed();
    updateRecLed();
  }
  // Report audio loss the moment it happens, timed from REC start, so it can be matched to other serial events
  // (e.g. a Bluetooth switch).
  static uint32_t seenOvf = 0, seenDrops = 0;
  if (!recording) {
    seenOvf = 0;
    seenDrops = 0;
  } else if (dmaOverflows != seenOvf || poolDrops != seenDrops) {
    Serial.printf("  !! audio loss at +%lu ms into the recording: DMA overflows %lu, pool drops %lu (Bluetooth %s)\n",
                  (unsigned long)(millis() - recStartMs), (unsigned long)dmaOverflows, (unsigned long)poolDrops,
                  bleOn ? "on" : "off");
    seenOvf = dmaOverflows;
    seenDrops = poolDrops;
  }
  updateSdPresence();
  batlogUpdate();
  static uint32_t lastHealth = 0, lastClipReport = 0, lastLevels = 0;
  if (millis() - lastHealth >= HEALTH_MS) {
    lastHealth = millis();
    printHealth();
  }
  if (millis() - lastClipReport >= CLIP_REPORT_MS) {
    lastClipReport = millis();
    reportClipping();
  }
  if (bleConnected && millis() - lastLevels >= LEVELS_MS) {
    lastLevels = millis();
    buildLevels();
  }
  if (millis() - lastStatus >= STATUS_MS) {
    lastStatus = millis();
    printStatus();
  }
}
