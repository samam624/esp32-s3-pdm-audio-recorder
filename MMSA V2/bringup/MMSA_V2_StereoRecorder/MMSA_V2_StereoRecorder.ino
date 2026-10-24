// MMSA V2 bring-up: configurable one-line stereo WAV recorder. Defaults to module 1 on IO5.
// Press REC to start, press again to stop. Writes /MMSA_0001.wav, /MMSA_0002.wav, ... to the SD card.
// 48 kHz, 16-bit, 2 channels (same PDM config as V1's recorder):
//   LEFT  channel = PDM left slot  (MIC 0, LR = GND)
//   RIGHT channel = PDM right slot (MIC 1, LR = Vdd)
//
// LEDs (V2 mapping, V1 behaviors):
//   IO40  Rec ready   solid while the SD card is mounted and answering (REC will work); off if the
//                     card is missing/failed. Updates live: probed every 500 ms while idle, remount every 1 s.
//   IO41  Loudness    PWM proportional to input level, always on regardless of recording state
//                     (V1 level-meter math: gated RMS, attack/release smoothing).
//   IO42  REC         blinks (400 ms toggle) while recording, off when idle.
// Build with PSRAM=disabled (REC button on IO35 shares the octal PSRAM).

#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <math.h>
#include <driver/i2s_pdm.h>

#define MIC_CLK_PIN 4
#ifndef MIC_DATA_PIN
#define MIC_DATA_PIN 5
#endif
#ifndef WAV_PREFIX
#define WAV_PREFIX "MMSA"
#endif
#ifndef MIC_LEFT_INDEX
#define MIC_LEFT_INDEX 0
#endif
#ifndef MIC_RIGHT_INDEX
#define MIC_RIGHT_INDEX 1
#endif
#ifndef RECORDER_LABEL
#define RECORDER_LABEL "MMSA V2 stereo recorder"
#endif
#define SD_SCK  12
#define SD_MISO 11
#define SD_MOSI 13
#define SD_CS   14
#define BUTTON_PIN 35
#define LED_SD     40
#define LED_LEVEL  41
#define LED_REC    42

#define SAMPLE_RATE 48000
#define CHANNELS    2
#define DMA_DESC    16
#define DMA_FRAMES  511            // 16 x 511 frames x 4 B = ~32 KB = ~170 ms of DMA buffering
#define CHUNK_BYTES 8192
#define SD_HZ       20000000

#define DEBOUNCE_MS       50
#define PRESS_LOCKOUT_MS  250
#define REC_BLINK_MS      400
#define SD_PROBE_MS       500      // idle + mounted: cheap "still there?" probe
#define SD_REMOUNT_MS     1000     // idle + not mounted: full remount attempt

// V1 level meter constants
#define LEVEL_GAIN      6.0f
#define LEVEL_THRESHOLD 0.035f
#define LEVEL_ATTACK    0.25f
#define LEVEL_RELEASE   0.06f

SPIClass sdSPI(FSPI);
static i2s_chan_handle_t rx = NULL;
static uint8_t chunk[CHUNK_BYTES];
static File wav;
static bool recording = false;
static bool sdReady = false;
static uint32_t dataBytes = 0;
static volatile uint32_t dmaOverflows = 0;
static uint32_t recStartMs = 0;
static float levelSmoothed = 0.0f;
static volatile bool buttonPressed = false;
static volatile uint32_t lastRiseMs = 0, lastPressMs = 0;

// Latch REC in an interrupt so the blocking I2S read cannot miss a short press.
static void IRAM_ATTR onButtonEdge() {
  uint32_t now = millis();
  if (gpio_get_level((gpio_num_t)BUTTON_PIN)) {
    lastRiseMs = now;
  } else if (now - lastRiseMs >= DEBOUNCE_MS && now - lastPressMs >= PRESS_LOCKOUT_MS) {
    lastPressMs = now;
    buttonPressed = true;
  }
}

static bool IRAM_ATTR onOverflow(i2s_chan_handle_t h, i2s_event_data_t *e, void *ctx) {
  dmaOverflows++;
  return false;
}

// Keeps sdReady and the SD LED in lockstep.
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
  if (recording) return;  // never compete with the recording for the SPI bus
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
  uint32_t byteRate = SAMPLE_RATE * CHANNELS * 2;
  uint16_t blockAlign = CHANNELS * 2, bits = 16, fmt = 1, ch = CHANNELS;
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
  cfg.gpio_cfg.clk = (gpio_num_t)MIC_CLK_PIN;
  cfg.gpio_cfg.din = (gpio_num_t)MIC_DATA_PIN;
  ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx, &cfg));
  i2s_event_callbacks_t cbs = {};
  cbs.on_recv_q_ovf = onOverflow;
  i2s_channel_register_event_callback(rx, &cbs, NULL);
  ESP_ERROR_CHECK(i2s_channel_enable(rx));
}

static String nextName() {
  char name[32];
  for (int i = 1; i < 10000; i++) {
    snprintf(name, sizeof(name), "/%s_%04d.wav", WAV_PREFIX, i);
    if (!SD.exists(name)) return String(name);
  }
  snprintf(name, sizeof(name), "/%s_9999.wav", WAV_PREFIX);
  return String(name);
}

static void startRecording() {
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
  dmaOverflows = 0;
  // Drop audio buffered while idle so the file starts at the button press.
  size_t got;
  while (i2s_channel_read(rx, chunk, CHUNK_BYTES, &got, 0) == ESP_OK && got) {
  }
  recording = true;
  recStartMs = millis();
  Serial.printf("REC start: %s\n", name.c_str());
}

static void stopRecording() {
  recording = false;
  digitalWrite(LED_REC, LOW);
  writeWavHeader(wav, dataBytes);
  String name = wav.name();
  wav.close();
  float secs = dataBytes / (float)(SAMPLE_RATE * CHANNELS * 2);
  Serial.printf("REC stop: %s, %.1f s audio (%lu bytes), wall time %.1f s, DMA overflows %lu\n", name.c_str(), secs,
                (unsigned long)dataBytes, (millis() - recStartMs) / 1000.0, (unsigned long)dmaOverflows);
}

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

// V1 level meter on IO41.
static void updateLevelLed(const int16_t *samples, size_t n) {
  if (n == 0) return;
  int64_t sumSq = 0;
  for (size_t i = 0; i < n; i++) sumSq += (int64_t)samples[i] * samples[i];
  float rms = sqrtf((float)sumSq / (float)n) / 32768.0f;
  float gated = 0.0f;
  if (rms > LEVEL_THRESHOLD) {
    gated = (rms - LEVEL_THRESHOLD) / (1.0f - LEVEL_THRESHOLD) * LEVEL_GAIN;
    if (gated > 1.0f) gated = 1.0f;
  }
  float k = gated > levelSmoothed ? LEVEL_ATTACK : LEVEL_RELEASE;
  levelSmoothed = (1.0f - k) * levelSmoothed + k * gated;

  ledcWrite(LED_LEVEL, (uint32_t)(levelSmoothed * 255.0f));
}

void setup() {
  Serial.begin(115200);
  // Native USB writes must not stall recording or button handling when the PC is not reading the port.
  Serial.setTxTimeoutMs(0);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  attachInterrupt(BUTTON_PIN, onButtonEdge, CHANGE);
  if (psramFound())
    Serial.println("WARNING: rebuild with PSRAM=disabled; IO35 (REC) is shared with octal PSRAM.");
  pinMode(LED_SD, OUTPUT);
  pinMode(LED_REC, OUTPUT);
  digitalWrite(LED_SD, LOW);
  digitalWrite(LED_REC, LOW);
  if (!ledcAttach(LED_LEVEL, 5000, 8)) Serial.println("WARNING: ledcAttach(IO41) failed, level LED will stay dark");
  ledcWrite(LED_LEVEL, 0);

  setSdReady(mountSd());
  startPdm();
  Serial.printf("\n%s. Press REC to start/stop (or send 'r' over serial).\n", RECORDER_LABEL);
  Serial.printf("WAV: 48 kHz 16-bit stereo on IO%d. LEFT = mic%d (LR=GND), RIGHT = mic%d (LR=Vdd).\n",
                MIC_DATA_PIN, MIC_LEFT_INDEX, MIC_RIGHT_INDEX);
  Serial.println("LEDs: IO40 record ready (SD mounted), IO41 loudness, IO42 blinks while recording.");
}

void loop() {
  // Button / serial toggle.
  bool toggle = false;
  if (buttonPressed) {
    buttonPressed = false;
    toggle = true;
  }
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'r' || c == 'R') toggle = true;
  }
  if (toggle) recording ? stopRecording() : startRecording();

  // Always drain I2S so the DMA never overflows while idle; write to SD only while recording.
  size_t got = 0;
  if (i2s_channel_read(rx, chunk, CHUNK_BYTES, &got, pdMS_TO_TICKS(100)) == ESP_OK && got) {
    updateLevelLed((const int16_t *)chunk, got / sizeof(int16_t));
    if (recording) {
      if (wav.write(chunk, got) != got) {
        Serial.println("SD write failed (card pulled?), stopping.");
        stopRecording();
        SD.end();
        setSdReady(false);
      } else {
        dataBytes += got;
      }
    }
  }

  updateRecLed();
  updateSdPresence();
}
