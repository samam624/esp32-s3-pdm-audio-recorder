// MMSA V2: 8-channel WAV recorder (all 4 PDM data lines, 8 mics).
// Same PDM setup as V1/StereoRecorder (hardware PDM->PCM, 48 kHz, 16-bit, shared clock IO4), extended to
// 4 data lines with all 8 slots enabled. Press REC to start/stop. Writes /MMSA8_0001.wav, ... (8 channels).
//
// Mic numbering: micN = 8-slot channel index N = WAV track N+1.
//   mic0-1 = IO5 pair (module 1)   -> WAV tracks 1-2
//   mic2-3 = IO6 pair (module 2)   -> WAV tracks 3-4
//   mic4-5 = IO7 pair (module 3)   -> WAV tracks 5-6
//   mic6-7 = IO8 pair (module 4)   -> WAV tracks 7-8
//
// Architecture (like V1): an I2S reader task on core 0 fills a pool of RAM blocks and never touches the SD
// card; loop() on core 1 writes full 16 KB blocks to SD. SD stalls are absorbed by the pool instead of
// overflowing the I2S DMA. 8 ch x 2 B x 48 kHz = 768 KB/s. (No PSRAM: the REC button on IO35 shares it.)
//
// Every 2 s while idle, serial prints per-mic signal (DC removed) and DC, and flags stuck/abnormal mics.
// On REC stop it prints audio length vs wall time, DMA overflows, pool drops, worst SD write and pool margin.
//
// LEDs: IO40 record ready (SD mounted, live), IO41 loudness (loudest mic), IO42 blinks while recording.
// Build with PSRAM=disabled.

#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <math.h>
#include <driver/i2s_pdm.h>
#include <freertos/queue.h>

#define MIC_CLK_PIN 4
static const gpio_num_t MIC_DIN[4] = {GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7, GPIO_NUM_8};

// Which mics are physically fitted. Unfitted PDM half-slots are high-impedance and their decoded value is
// undefined, so write them to the WAV as digital silence. As of 2026-10-21 (16:40) mic6 and mic7 are fitted and
// mic4 is not, but mic4 is deliberately left UNMUTED so its raw (undefined) slot data is recorded for comparison
// while IO7 is investigated. Set mic4 false for real recordings until a mic is fitted there.
static const bool MIC_FITTED[8] = {true, true, true, true, true, true, true, true};
#define SD_SCK  12
#define SD_MISO 11
#define SD_MOSI 13
#define SD_CS   14
#define BUTTON_PIN 35
#define LED_SD     40
#define LED_LEVEL  41
#define LED_REC    42

// PDM clock = 64 x SAMPLE_RATE. Normal: 48000 (3.072 MHz). TEST 2026-10-21: 32000 (2.048 MHz) to see whether
// mic4 hiss. Result: at 32000 EVERY mic came out as white noise (-65 dB, uncorrelated), so the ESP32 PDM->PCM path
// does not work at 32 kHz with this config (mic is rated 1.2-3.25 MHz). Stay at 48000.
#define SAMPLE_RATE 48000
#define CHANNELS    8
#define FRAME_BYTES (CHANNELS * 2)
#define DMA_DESC    8
#define DMA_FRAMES  256              // 8 x 256 frames x 16 B = 32 KB (~43 ms) of DMA buffering
#define BLOCK_BYTES 16384            // one pool block = 1024 frames = 21.3 ms; also the SD write size
#define BLOCK_FRAMES (BLOCK_BYTES / FRAME_BYTES)
#define POOL_BLOCKS_MAX 12           // up to 192 KB (~256 ms); fewer if RAM is short
#define POOL_BLOCKS_MIN 4
#define SD_HZ       20000000

#define DEBOUNCE_MS   50
#define REC_BLINK_MS  400
#define SD_PROBE_MS   500
#define SD_REMOUNT_MS 1000
#define STATUS_MS     2000

#define LEVEL_GAIN      6.0f
#define LEVEL_THRESHOLD 0.035f
#define LEVEL_ATTACK    0.25f
#define LEVEL_RELEASE   0.06f

SPIClass sdSPI(FSPI);
static i2s_chan_handle_t rx = NULL;
static uint8_t *pool[POOL_BLOCKS_MAX];
static int poolBlocks = 0;
static QueueHandle_t freeQ, fullQ;   // queues of block indices

static File wav;
static volatile bool recording = false;
static bool sdReady = false;
static uint32_t dataBytes = 0;
static uint32_t recStartMs = 0;
static volatile uint32_t dmaOverflows = 0;
static volatile uint32_t poolDrops = 0;      // blocks lost because no free block was available
static uint32_t maxWriteUs = 0;
static int minFreeBlocks = POOL_BLOCKS_MAX;
static volatile float loudestRms = 0;        // set by reader task, used for the loudness LED
static bool batlogStopped = false;           // battery below cutoff: SD card no longer used (see battery logger)
static float levelSmoothed = 0.0f;

// Idle per-mic status accumulators (loop side).
static double stSq[CHANNELS], stSum[CHANNELS];
static int16_t stMin[CHANNELS], stMax[CHANNELS];
static uint32_t stFrames = 0, stPairSame[CHANNELS / 2];

static bool IRAM_ATTR onOverflow(i2s_chan_handle_t h, i2s_event_data_t *e, void *ctx) {
  dmaOverflows++;
  return false;
}

// REC button, latched by interrupt so a busy loop() can never miss a press. A falling edge counts as a press
// only if the pin had been released for DEBOUNCE_MS (rejects release bounce), and presses are locked out for
// PRESS_LOCKOUT_MS (rejects press bounce).
#define PRESS_LOCKOUT_MS 250
static volatile bool buttonPressed = false;
static volatile uint32_t lastRiseMs = 0, lastPressMs = 0;
static void IRAM_ATTR onButtonEdge() {
  uint32_t now = millis();
  if (gpio_get_level((gpio_num_t)BUTTON_PIN)) {
    lastRiseMs = now;
  } else if (now - lastRiseMs >= DEBOUNCE_MS && now - lastPressMs >= PRESS_LOCKOUT_MS) {
    lastPressMs = now;
    buttonPressed = true;
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
        // No free block: read and discard so the DMA keeps flowing, and count the loss.
        size_t got = 0;
        i2s_channel_read(rx, scratch, sizeof(scratch), &got, portMAX_DELAY);
        if (recording) poolDrops++;
        cur = -1;
        continue;
      }
      fill = 0;
    }
    size_t got = 0;
    if (i2s_channel_read(rx, pool[cur] + fill, BLOCK_BYTES - fill, &got, portMAX_DELAY) != ESP_OK) continue;
    fill += got;
    if (fill >= BLOCK_BYTES) {
      // Loudest-mic RMS for the loudness LED (cheap: 1024 frames). Fitted mics only, DC removed: an empty
      // line sits at a constant ~-30935, which would otherwise read as near full scale and pin the LED on.
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
static void setSdReady(bool ready) {
  if (ready != sdReady) Serial.printf("SD %s\n", ready ? "mounted" : "NOT available");
  sdReady = ready;
  digitalWrite(LED_SD, ready ? HIGH : LOW);
}

static bool mountSd() {
  SD.end();
  sdSPI.end();
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
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
      setSdReady(false);
    }
  } else {
    if (now - lastCheck < SD_REMOUNT_MS) return;
    lastCheck = now;
    setSdReady(mountSd());
  }
}

static void writeWavHeader(File &f, uint32_t dataLen) {
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
  f.seek(0);
  f.write(h, 44);
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
  // NO pull-downs on the data lines. Tried 2026-10-21: with internal pull-downs, mic1 went dead (DC -30935) and
  // mic4/mic5 degraded; removing them restored all three. Empty lines are muted via MIC_FITTED[] instead.
}

// ---------------- Recording ----------------
static String nextName() {
  char name[24];
  for (int i = 1; i < 10000; i++) {
    // Non-48 kHz test recordings get the rate in the name (e.g. /MMSA8_32k_0001.wav) so they can't be mixed up.
    if (SAMPLE_RATE == 48000) snprintf(name, sizeof(name), "/MMSA8_%04d.wav", i);
    else snprintf(name, sizeof(name), "/MMSA8_%dk_%04d.wav", SAMPLE_RATE / 1000, i);
    if (!SD.exists(name)) return String(name);
  }
  return String("/MMSA8_9999.wav");
}

static void drainFullBlocks() {
  int idx;
  while (xQueueReceive(fullQ, &idx, 0) == pdTRUE) xQueueSend(freeQ, &idx, 0);
}

static void startRecording() {
  if (batlogStopped) {
    Serial.println("REC ignored: battery below cutoff, SD card disabled to protect it.");
    return;
  }
  if (!sdReady) {
    Serial.println("REC ignored: not ready, no SD card mounted (IO40 off).");
    return;
  }
  String name = nextName();
  wav = SD.open(name, FILE_WRITE);
  if (!wav) {
    Serial.printf("Could not open %s\n", name.c_str());
    setSdReady(false);
    return;
  }
  writeWavHeader(wav, 0);
  dataBytes = 0;
  maxWriteUs = 0;
  minFreeBlocks = poolBlocks;
  drainFullBlocks();  // start at the button press, not with stale idle audio
  dmaOverflows = 0;
  poolDrops = 0;
  recStartMs = millis();
  recording = true;
  Serial.printf("REC start: %s (8 ch)\n", name.c_str());
}

// ---------------- SD-crosstalk snapshot test (hold REC 1.5 s) ----------------
// Captures alternating chunks of SNAP_CHUNK_BLOCKS blocks (~213 ms): "idle" with the SD bus completely silent,
// then "busy" while dummy 4 KB writes keep the SD SPI bus running (like a real recording). Both kinds go into
// /SNAP_NNNN.wav in the order idle, busy, idle, busy, ... (each chunk = SNAP_CHUNK_BLOCKS * 1024 frames, with a
// discontinuity between chunks). If a mic's hiss is crosstalk from the SD traces, it shows in busy chunks only.
#define SNAP_CHUNK_BLOCKS 10
#define SNAP_PAIRS        8
#define SNAP_HOLD_MS      1500

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
  int got[POOL_BLOCKS_MAX];
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

static void stopRecording() {
  recording = false;
  digitalWrite(LED_REC, LOW);
  writeWavHeader(wav, dataBytes);
  String name = wav.name();
  wav.close();
  float secs = dataBytes / (float)(SAMPLE_RATE * FRAME_BYTES);
  float wall = (millis() - recStartMs) / 1000.0f;
  Serial.printf("REC stop: %s, %.1f s audio (%lu bytes), wall time %.1f s\n", name.c_str(), secs,
                (unsigned long)dataBytes, wall);
  Serial.printf("  DMA overflows %lu, pool drops %lu, worst SD write %.1f ms, min free blocks %d/%d -> %s\n",
                (unsigned long)dmaOverflows, (unsigned long)poolDrops, maxWriteUs / 1000.0f, minFreeBlocks, poolBlocks,
                (dmaOverflows == 0 && poolDrops == 0) ? "NO AUDIO LOST" : "AUDIO WAS LOST");
}

// ---------------- LEDs / status ----------------
static void updateRecLed() {
  static uint32_t lastBlink = 0;
  static bool on = false;
  if (!recording) {
    on = false;
    digitalWrite(LED_REC, LOW);
    return;
  }
  if (millis() - lastBlink >= REC_BLINK_MS) {
    lastBlink = millis();
    on = !on;
    digitalWrite(LED_REC, on ? HIGH : LOW);
  }
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
    if (!MIC_FITTED[c]) continue;  // muted in recordings; not expected to have signal
    if (ac[c] < 3.0 && fabs(dc[c]) > 1000)
      Serial.printf("  mic%d: STUCK (steady DC %.0f, no signal): dead or not driving\n", c, dc[c]);
    else if (fabs(dc[c]) > 10000)
      Serial.printf("  mic%d: ABNORMAL (DC %.0f pinned near the rail): mostly not driving, check joints\n", c, dc[c]);
  }
  for (int p = 0; p < CHANNELS / 2; p++) {
    // Pair comparisons only mean anything when both time slots have microphones installed.
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

// ---------------- Battery logger (added 2026-10-21) ----------------
// Logs VBAT to /BATLOG.CSV so an overnight run-down can be read back: a "# boot" line on every power-up (with the
// reset reason, so brownout resets show), a column header, then one line every BATLOG_MS with uptime and VBAT
// avg/min/max over that interval. Each line is appended and the file closed at once, so nothing is lost when the
// battery dies. Below BATLOG_CUTOFF_MV (interval average) it writes a final line, stops any recording and stops
// using the SD card, so a browning-out board can't corrupt the card. Analyse with tools/batlog_analyze.py.
#define VBAT_PIN         9      // BATT_ESP32 = VBAT/2 (100k/100k), ADC1_CH8
#define BATLOG_FILE      "/BATLOG.CSV"
#define BATLOG_MS        30000
#define VBAT_SAMPLE_MS   250
#define BATLOG_CUTOFF_MV 3400

static uint32_t vbN = 0, vbSum = 0, vbMin = UINT32_MAX, vbMax = 0;

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
  snprintf(line, sizeof(line), "# boot, reset=%s, vbat_mV=%lu, interval_s=%d, cutoff_mV=%d", resetReasonName(),
           (unsigned long)mv, BATLOG_MS / 1000, BATLOG_CUTOFF_MV);
  bool ok = batlogAppend(line);
  batlogAppend("uptime_s,vbat_avg_mV,vbat_min_mV,vbat_max_mV,recording");
  snprintf(line, sizeof(line), "0,%lu,%lu,%lu,0", (unsigned long)mv, (unsigned long)mv, (unsigned long)mv);
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
  vbN++;
  vbSum += mv;
  if (mv < vbMin) vbMin = mv;
  if (mv > vbMax) vbMax = mv;
  if (now - lastLog < BATLOG_MS) return;
  lastLog = now;
  uint32_t avg = vbSum / vbN;
  char line[96];
  snprintf(line, sizeof(line), "%lu,%lu,%lu,%lu,%d", (unsigned long)(now / 1000), (unsigned long)avg,
           (unsigned long)vbMin, (unsigned long)vbMax, recording ? 1 : 0);
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

// ---------------- setup / loop ----------------
void setup() {
  Serial.begin(115200);
  // USB serial must never block. With USB plugged into a PC that isn't reading the port, each print otherwise
  // waits up to 100 ms (up to ~2 s total), stalling loop() long enough to miss REC presses.
  Serial.setTxTimeoutMs(0);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  attachInterrupt(BUTTON_PIN, onButtonEdge, CHANGE);
  if (psramFound())
    Serial.println("WARNING: built with PSRAM enabled. IO35 (REC button) belongs to the PSRAM, so the button "
                   "will NOT work. Rebuild with PSRAM=disabled.");
  pinMode(LED_SD, OUTPUT);
  pinMode(LED_REC, OUTPUT);
  digitalWrite(LED_SD, LOW);
  digitalWrite(LED_REC, LOW);
  if (!ledcAttach(LED_LEVEL, 5000, 8)) Serial.println("WARNING: ledcAttach(IO41) failed, loudness LED will stay dark");
  ledcWrite(LED_LEVEL, 0);

  setSdReady(mountSd());
  batlogStart();
  startPdm();

  // Allocate the block pool from what's left (keep ~40 KB headroom for SD/FS and the rest).
  freeQ = xQueueCreate(POOL_BLOCKS_MAX, sizeof(int));
  fullQ = xQueueCreate(POOL_BLOCKS_MAX, sizeof(int));
  for (int i = 0; i < POOL_BLOCKS_MAX; i++) {
    if (heap_caps_get_largest_free_block(MALLOC_CAP_8BIT) < BLOCK_BYTES + 40000 && poolBlocks >= POOL_BLOCKS_MIN) break;
    pool[i] = (uint8_t *)heap_caps_malloc(BLOCK_BYTES, MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    if (!pool[i]) break;
    xQueueSend(freeQ, &i, 0);
    poolBlocks++;
  }
  minFreeBlocks = poolBlocks;
  Serial.printf("\nBuffer pool: %d x %d KB = %d KB (~%d ms), free heap after: %lu bytes\n", poolBlocks, BLOCK_BYTES / 1024,
                poolBlocks * BLOCK_BYTES / 1024, poolBlocks * BLOCK_FRAMES * 1000 / SAMPLE_RATE,
                (unsigned long)ESP.getFreeHeap());
  xTaskCreatePinnedToCore(readerTask, "i2sReader", 4096, NULL, configMAX_PRIORITIES - 2, NULL, 0);

  resetStatus();
  Serial.println("MMSA V2 8-channel recorder. Press REC to start/stop (or send 'r' over serial).");
  Serial.printf("WAV: %d Hz 16-bit, 8 ch (PDM clock %.3f MHz). ", SAMPLE_RATE, SAMPLE_RATE * 64 / 1e6);
  Serial.println(" mic0-1 IO5, mic2-3 IO6, mic4-5 IO7, mic6-7 IO8 (WAV track N+1 = mic N).");
  Serial.print("Fitted mics:");
  for (int c = 0; c < CHANNELS; c++)
    if (MIC_FITTED[c]) Serial.printf(" mic%d", c);
  Serial.println("; all other WAV tracks are muted to digital silence.");
  Serial.println("LEDs: IO40 record ready (SD mounted), IO41 loudness, IO42 blinks while recording.");
}

void loop() {
  static uint32_t lastStatus = 0, pressAt = 0;
  static bool pressPending = false;
  bool toggle = false;
  // Short press = start/stop recording (acts on release when idle, immediately when recording).
  // Hold 1.5 s while idle = SD-crosstalk snapshot test.
  if (buttonPressed) {
    buttonPressed = false;
    pressPending = true;
    pressAt = millis();
  }
  if (pressPending) {
    uint32_t held = millis() - pressAt;
    if (recording) {
      pressPending = false;
      toggle = true;
    } else if (held > DEBOUNCE_MS && digitalRead(BUTTON_PIN) == HIGH) {
      pressPending = false;
      toggle = true;
    } else if (held >= SNAP_HOLD_MS) {
      pressPending = false;
      Serial.println("REC held: running SD-crosstalk snapshot test");
      snapshotTest();
    }
  }
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'r' || c == 'R') toggle = true;
    if ((c == 's' || c == 'S') && !recording) snapshotTest();
  }
  if (toggle) Serial.println("REC button / 'r'");
  if (toggle) recording ? stopRecording() : startRecording();

  // Consume full blocks: write to SD while recording, otherwise feed the idle status stats.
  int idx;
  if (xQueueReceive(fullQ, &idx, pdMS_TO_TICKS(20)) == pdTRUE) {
    if (recording) {
      int freeNow = uxQueueMessagesWaiting(freeQ);
      if (freeNow < minFreeBlocks) minFreeBlocks = freeNow;
      uint32_t t = micros();
      // Mute unfitted mics (empty pads read back as glitchy floating data).
      int16_t *fr = (int16_t *)pool[idx];
      for (int f = 0; f < BLOCK_FRAMES; f++, fr += CHANNELS)
        for (int c = 0; c < CHANNELS; c++)
          if (!MIC_FITTED[c]) fr[c] = 0;
      size_t w = wav.write(pool[idx], BLOCK_BYTES);
      uint32_t dt = micros() - t;
      if (dt > maxWriteUs) maxWriteUs = dt;
      if (w != BLOCK_BYTES) {
        xQueueSend(freeQ, &idx, 0);
        Serial.println("SD write failed (card pulled?), stopping.");
        stopRecording();
        SD.end();
        setSdReady(false);
        return;
      }
      dataBytes += BLOCK_BYTES;
    } else {
      accumulateStatus((const int16_t *)pool[idx], BLOCK_FRAMES);
    }
    xQueueSend(freeQ, &idx, 0);
  }

  updateLevelLed();
  updateRecLed();
  updateSdPresence();
  batlogUpdate();
  if (millis() - lastStatus >= STATUS_MS) {
    lastStatus = millis();
    printStatus();
  }
}
