// MMSA V2 bring-up: 8-mic PDM level test.
// Reads all 4 PDM data lines (IO5-8, shared clock IO4) = 8 slots (L/R per line) on I2S0 and prints a
// live level bar per slot every 250 ms. Tap each mic and watch which slot jumps.
// Every 5 s it prints a health line flagging slots that look dead (flat/stuck/silent).
//
// Mode: hardware PDM->PCM filter on all 8 slots. NOT YET VALIDATED: identical L/R slots on line 0 and
// constant values on lines 1-3 could be a driver/config limitation, not the board (see MMSA_V2_MicDiag).
//
// LEDs: at boot each LED lights alone in turn (IO40, IO41, IO42, twice) to identify them.
// Then IO40 (REC) mirrors the REC button, IO41 lights with sound (off below -42 dBFS, full at -20),
// and IO42 blinks at 1 Hz as a heartbeat. This also tests the IO41/IO42 LEDs.
// Build with PSRAM=disabled (REC button on IO35 shares the octal PSRAM).

#include <Arduino.h>
#include <math.h>
#include <driver/i2s_pdm.h>
#include "soc/gpio_struct.h"
#include "soc/io_mux_reg.h"

// Debug: dump how IO40/41/42 are configured in the IO_MUX and GPIO matrix.
// mux = IO_MUX function (1 = GPIO on these pins, 0 = JTAG), sig = output signal (256 = plain GPIO),
// oe = output enable, out = output register bit, pad = pad level (only valid if input enabled).
static void dumpLedPins(const char *tag) {
  const uint32_t muxRegs[3] = {IO_MUX_GPIO40_REG, IO_MUX_GPIO41_REG, IO_MUX_GPIO42_REG};
  Serial.printf("[pins %-14s]", tag);
  for (int i = 0; i < 3; i++) {
    int n = 40 + i;
    uint32_t mux = REG_READ(muxRegs[i]);
    Serial.printf("  IO%d mux=%lu ie=%lu sig=%u oe=%lu out=%lu pad=%lu", n, (unsigned long)((mux >> MCU_SEL_S) & MCU_SEL_V),
                  (unsigned long)((mux >> FUN_IE_S) & 1), (unsigned)GPIO.func_out_sel_cfg[n].func_sel,
                  (unsigned long)((GPIO.enable1.val >> (n - 32)) & 1), (unsigned long)((GPIO.out1.val >> (n - 32)) & 1),
                  (unsigned long)((GPIO.in1.val >> (n - 32)) & 1));
  }
  Serial.println();
}

#define MIC_CLK_PIN 4
static const gpio_num_t MIC_DIN[4] = {GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7, GPIO_NUM_8};
#define BUTTON_PIN 35
#define LED_REC    40
#define LED_LEVEL  41
#define LED_BEAT   42

#define SAMPLE_RATE 48000
#define NCH         8
#define FRAMES      256
#define WINDOW_MS   250
#define HEALTH_MS   5000

static i2s_chan_handle_t rx = NULL;
static bool rawMode = false;
static int16_t buf[FRAMES * NCH];

// Slot order assumed to follow the slot-mask bit order (line0 R, line0 L, line1 R, ...).
// Confirm by tapping mics; the label is only a guess until then.
static const char *slotLabel(int ch) {
  static const char *labels[NCH] = {"IO5 R", "IO5 L", "IO6 R", "IO6 L", "IO7 R", "IO7 L", "IO8 R", "IO8 L"};
  return labels[ch];
}

static esp_err_t startPdm(bool raw) {
  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num = 8;
  cc.dma_frame_num = FRAMES;
  esp_err_t e = i2s_new_channel(&cc, NULL, &rx);
  if (e != ESP_OK) return e;

  i2s_pdm_rx_config_t cfg = {};
  i2s_pdm_rx_clk_config_t clk = I2S_PDM_RX_CLK_DEFAULT_CONFIG(raw ? SAMPLE_RATE * 64 : SAMPLE_RATE);
  cfg.clk_cfg = clk;
  if (raw) {
    i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_RAW_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
    cfg.slot_cfg = s;
  } else {
    i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
    cfg.slot_cfg = s;
  }
  cfg.slot_cfg.slot_mask = I2S_PDM_LINE_SLOT_ALL;
  cfg.gpio_cfg.clk = (gpio_num_t)MIC_CLK_PIN;
  for (int i = 0; i < 4; i++) cfg.gpio_cfg.dins[i] = MIC_DIN[i];

  e = i2s_channel_init_pdm_rx_mode(rx, &cfg);
  if (e != ESP_OK) {
    i2s_del_channel(rx);
    rx = NULL;
    return e;
  }
  return i2s_channel_enable(rx);
}

// Per-window accumulators.
static double accSum[NCH], accSq[NCH];
static int32_t accMin[NCH], accMax[NCH];
static uint32_t accN = 0;
// Raw mode: popcount over 4 consecutive 16-bit words (64 PDM bits) per sample.
static int rawGroupBits[NCH];
static int rawGroupWords = 0;
// Health tracking over HEALTH_MS.
static double healthPeakDb[NCH];
static double healthMean[NCH];

static void resetWindow() {
  for (int c = 0; c < NCH; c++) {
    accSum[c] = 0;
    accSq[c] = 0;
    accMin[c] = INT32_MAX;
    accMax[c] = INT32_MIN;
  }
  accN = 0;
}

static inline void addSample(int c, int32_t v) {
  accSum[c] += v;
  accSq[c] += (double)v * v;
  if (v < accMin[c]) accMin[c] = v;
  if (v > accMax[c]) accMax[c] = v;
}

static void processBuffer(size_t frames) {
  for (size_t f = 0; f < frames; f++) {
    const int16_t *fr = &buf[f * NCH];
    if (!rawMode) {
      for (int c = 0; c < NCH; c++) addSample(c, fr[c]);
      accN++;
    } else {
      for (int c = 0; c < NCH; c++) rawGroupBits[c] += __builtin_popcount((uint16_t)fr[c]);
      if (++rawGroupWords == 4) {
        for (int c = 0; c < NCH; c++) {
          addSample(c, rawGroupBits[c]);  // 0..64, 32 = silence
          rawGroupBits[c] = 0;
        }
        rawGroupWords = 0;
        accN++;
      }
    }
  }
}

static void bar(char *out, double db) {
  // 8 chars, -80 dBFS .. -20 dBFS
  int n = (int)((db + 80.0) / 60.0 * 8.0 + 0.5);
  if (n < 0) n = 0;
  if (n > 8) n = 8;
  for (int i = 0; i < 8; i++) out[i] = i < n ? '#' : '.';
  out[8] = 0;
}

static void reportWindow() {
  if (accN == 0) return;
  const double fullScale = rawMode ? 32.0 : 32768.0;
  char line[256];
  int pos = snprintf(line, sizeof(line), "%7.2fs ", millis() / 1000.0);
  double loudest = -120;
  for (int c = 0; c < NCH; c++) {
    double mean = accSum[c] / accN;
    double var = accSq[c] / accN - mean * mean;
    double rms = var > 0 ? sqrt(var) : 0;
    double db = rms > 0 ? 20.0 * log10(rms / fullScale) : -120.0;
    if (db > healthPeakDb[c]) healthPeakDb[c] = db;
    healthMean[c] = mean;
    if (db > loudest) loudest = db;
    char b[9];
    bar(b, db);
    pos += snprintf(line + pos, sizeof(line) - pos, "%d:%4.0f %s ", c, db, b);
  }
  Serial.println(line);

  // Off below -42 dBFS (quiet room sits around -45..-55), full at -20 dBFS, squared so it reads as a jump.
  double x = (loudest + 42.0) / 22.0;
  if (x < 0) x = 0;
  if (x > 1) x = 1;
  ledcWrite(LED_LEVEL, (int)(x * x * 255.0));
}

static void reportHealth() {
  Serial.println("---- health (last 5 s) ----");
  for (int c = 0; c < NCH; c++) {
    const char *status;
    if (rawMode) {
      double density = healthMean[c] / 64.0;
      if (density < 0.02 || density > 0.98) status = "STUCK (line held low/high: mic dead or not driving)";
      else if (healthPeakDb[c] < -70) status = "QUIET (check)";
      else status = "OK";
      Serial.printf("  slot %d (%s): peak %5.1f dBFS, 1s-density %.2f  %s\n", c, slotLabel(c), healthPeakDb[c],
                    density, status);
    } else {
      if (healthPeakDb[c] <= -119) status = "FLAT (no data: mic dead, missing, or no mic on this slot)";
      else if (healthPeakDb[c] < -80) status = "QUIET (check)";
      else status = "OK";
      Serial.printf("  slot %d (%s): peak %5.1f dBFS, DC %7.1f  %s\n", c, slotLabel(c), healthPeakDb[c], healthMean[c],
                    status);
    }
    healthPeakDb[c] = -120;
  }
  Serial.println("---------------------------");
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_REC, OUTPUT);
  pinMode(LED_BEAT, OUTPUT);
  // LED ID: light each LED alone for 1 s, twice, so the physical LEDs can be matched to GPIOs.
  pinMode(LED_LEVEL, OUTPUT);
  const int ids[3] = {LED_REC, LED_LEVEL, LED_BEAT};
  for (int rep = 0; rep < 2; rep++) {
    for (int i = 0; i < 3; i++) {
      for (int j = 0; j < 3; j++) digitalWrite(ids[j], j == i ? HIGH : LOW);
      Serial.printf("LED ID: IO%d on\n", ids[i]);
      delay(1000);
    }
  }
  for (int j = 0; j < 3; j++) digitalWrite(ids[j], LOW);
  dumpLedPins("after LED ID");
  if (!ledcAttach(LED_LEVEL, 5000, 8)) Serial.println("WARNING: ledcAttach(IO41) failed, level LED will stay dark");
  dumpLedPins("after ledc");

  Serial.println("\nMMSA V2 mic test: 4 PDM lines (IO5-8), clock IO4, 8 slots");
  // Hardware PDM->PCM only. The raw-PDM path was removed: the driver rejects 8 raw slots at
  // 3.072 MHz (ESP_ERR_INVALID_ARG, "clock calculate failed"), so it could never have worked as a fallback.
  esp_err_t e = startPdm(false);
  if (e != ESP_OK) {
    Serial.printf("I2S PDM RX init failed (%s). Stopping.\n", esp_err_to_name(e));
    while (true) delay(1000);
  }
  rawMode = false;
  Serial.printf("Mode: hardware PDM->PCM, %d Hz, 8 slots\n", SAMPLE_RATE);
  dumpLedPins("after I2S");
  Serial.println("Slot labels (IOx L/R) are a guess until confirmed by tapping each mic.");
  Serial.println("Bars: -80 dBFS (empty) .. -20 dBFS (full)");
  for (int c = 0; c < NCH; c++) healthPeakDb[c] = -120;
  resetWindow();
}

void loop() {
  static uint32_t winStart = millis(), healthStart = millis();
  size_t bytes = 0;
  if (i2s_channel_read(rx, buf, sizeof(buf), &bytes, pdMS_TO_TICKS(200)) == ESP_OK) {
    processBuffer(bytes / (sizeof(int16_t) * NCH));
  }

  digitalWrite(LED_REC, digitalRead(BUTTON_PIN) == LOW ? HIGH : LOW);
  digitalWrite(LED_BEAT, (millis() / 500) % 2);

  if (millis() - winStart >= WINDOW_MS) {
    reportWindow();
    resetWindow();
    winStart = millis();
  }
  if (millis() - healthStart >= HEALTH_MS) {
    reportHealth();
    healthStart = millis();
  }
}
