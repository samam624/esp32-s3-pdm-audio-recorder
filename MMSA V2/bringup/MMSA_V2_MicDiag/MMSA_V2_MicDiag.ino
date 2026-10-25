// MMSA V2 bring-up: PDM slot diagnostic.
// Cycles through several I2S PDM RX configurations (2 s each) and reports, per configuration:
//   - per-slot level and DC
//   - for 2+ slots: % of samples where slot 0 == slot 1 exactly, and their correlation
// Two separate mics are never bit-identical, so identical% near 100 means one data stream duplicated
// (wrong SELECT strap, one mic not driving, or a driver/hardware limitation).
// Build with PSRAM=disabled.

#include <Arduino.h>
#include <math.h>
#include <driver/i2s_pdm.h>

#define MIC_CLK_PIN 4
static const gpio_num_t MIC_DIN[4] = {GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7, GPIO_NUM_8};
#define SAMPLE_RATE 48000
#define FRAMES 256
#define RUN_MS 2000

struct Exp {
  const char *name;
  bool raw;
  i2s_slot_mode_t mode;
  uint32_t mask;
  int nch;
};

static const Exp EXPS[] = {
  {"PCM line0 stereo (L+R)", false, I2S_SLOT_MODE_STEREO, I2S_PDM_SLOT_BOTH, 2},
  {"PCM line0 LEFT only", false, I2S_SLOT_MODE_MONO, I2S_PDM_SLOT_LEFT, 1},
  {"PCM line0 RIGHT only", false, I2S_SLOT_MODE_MONO, I2S_PDM_SLOT_RIGHT, 1},
  {"PCM all 4 lines (8 slots)", false, I2S_SLOT_MODE_STEREO, I2S_PDM_LINE_SLOT_ALL, 8},
  {"RAW line0 stereo (L+R)", true, I2S_SLOT_MODE_STEREO, I2S_PDM_SLOT_BOTH, 2},
};

static i2s_chan_handle_t rx = NULL;
static int16_t buf[FRAMES * 8];

static esp_err_t start(const Exp &x) {
  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num = 8;
  cc.dma_frame_num = FRAMES;
  esp_err_t e = i2s_new_channel(&cc, NULL, &rx);
  if (e != ESP_OK) return e;
  i2s_pdm_rx_config_t cfg = {};
  i2s_pdm_rx_clk_config_t clk = I2S_PDM_RX_CLK_DEFAULT_CONFIG(x.raw ? SAMPLE_RATE * 64 : SAMPLE_RATE);
  cfg.clk_cfg = clk;
  if (x.raw) {
    i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_RAW_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, x.mode);
    cfg.slot_cfg = s;
  } else {
    i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, x.mode);
    cfg.slot_cfg = s;
  }
  cfg.slot_cfg.slot_mask = (i2s_pdm_slot_mask_t)x.mask;
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

static void stop() {
  if (!rx) return;
  i2s_channel_disable(rx);
  i2s_del_channel(rx);
  rx = NULL;
}

// Returns slot 0 level in dBFS (or -999 if the config was refused).
static double runExp(const Exp &x) {
  Serial.printf("\n== %s ==\n", x.name);
  esp_err_t e = start(x);
  if (e != ESP_OK) {
    Serial.printf("  init refused: %s\n", esp_err_to_name(e));
    return -999;
  }
  const int n = x.nch;
  double sum[8] = {0}, sq[8] = {0};
  double xy = 0;            // cross term for correlation between derived ch0/ch1 samples
  uint32_t samples = 0;     // derived samples per channel
  uint32_t words = 0, same01 = 0;
  int grp[8] = {0}, gw = 0;
  uint16_t firstWords[8][4];
  int fwCount = 0;

  uint32_t t0 = millis();
  bool skipFirst = true;
  while (millis() - t0 < RUN_MS) {
    size_t bytes = 0;
    if (i2s_channel_read(rx, buf, sizeof(int16_t) * FRAMES * n, &bytes, pdMS_TO_TICKS(200)) != ESP_OK) continue;
    if (skipFirst) {  // let filters settle
      skipFirst = false;
      continue;
    }
    size_t frames = bytes / (sizeof(int16_t) * n);
    for (size_t f = 0; f < frames; f++) {
      const int16_t *fr = &buf[f * n];
      if (n >= 2) {
        words++;
        if (fr[0] == fr[1]) same01++;
      }
      if (x.raw && fwCount < 4) {
        for (int c = 0; c < n; c++) firstWords[c][fwCount] = (uint16_t)fr[c];
        fwCount++;
      }
      if (!x.raw) {
        for (int c = 0; c < n; c++) {
          sum[c] += fr[c];
          sq[c] += (double)fr[c] * fr[c];
        }
        if (n >= 2) xy += (double)fr[0] * fr[1];
        samples++;
      } else {
        for (int c = 0; c < n; c++) grp[c] += __builtin_popcount((uint16_t)fr[c]);
        if (++gw == 4) {
          for (int c = 0; c < n; c++) {
            sum[c] += grp[c];
            sq[c] += (double)grp[c] * grp[c];
          }
          if (n >= 2) xy += (double)grp[0] * grp[1];
          for (int c = 0; c < n; c++) grp[c] = 0;
          gw = 0;
          samples++;
        }
      }
    }
  }
  stop();

  const double fs = x.raw ? 32.0 : 32768.0;
  double mean[8], sd[8];
  for (int c = 0; c < n; c++) {
    mean[c] = samples ? sum[c] / samples : 0;
    double v = samples ? sq[c] / samples - mean[c] * mean[c] : 0;
    sd[c] = v > 0 ? sqrt(v) : 0;
    double db = sd[c] > 0 ? 20 * log10(sd[c] / fs) : -120;
    if (x.raw)
      Serial.printf("  slot %d: level %6.1f dBFS, 1s-density %.3f", c, db, mean[c] / 64.0);
    else
      Serial.printf("  slot %d: level %6.1f dBFS, DC %8.1f", c, db, mean[c]);
    if (x.raw) {
      Serial.print("  words:");
      for (int k = 0; k < fwCount; k++) Serial.printf(" %04X", firstWords[c][k]);
    }
    Serial.println();
  }
  if (n >= 2) {
    double cov = samples ? xy / samples - mean[0] * mean[1] : 0;
    double corr = (sd[0] > 0 && sd[1] > 0) ? cov / (sd[0] * sd[1]) : 0;
    Serial.printf("  slot0 vs slot1: identical %.1f%% of words, correlation %.3f  -> %s\n",
                  words ? 100.0 * same01 / words : 0, corr,
                  (words && same01 * 100 / words > 95) ? "DUPLICATE (same stream)" : "distinct streams");
  }
  return sd[0] > 0 ? 20 * log10(sd[0] / fs) : -120;
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  Serial.println("\nMMSA V2 PDM slot diagnostic");
}

// Cover test: keep a steady sound going (phone playing music or a tone near the flex), cover ONE mic's
// port for a few cycles, then the other. Compare the LEFT-edge and RIGHT-edge levels:
//   - covering MIC_L drops only LEFT and covering MIC_R drops only RIGHT -> both mics work, and the
//     identical stereo slots are a driver/config issue
//   - one mic's cover drops BOTH levels and the other's drops neither -> only one mic reaches the
//     data line (hardware: joint, dead mic, or routing)
// Taps are not a valid per-mic test: the vibration travels through the flex to both mics.
void loop() {
  double lv[sizeof(EXPS) / sizeof(EXPS[0])];
  int i = 0;
  for (const Exp &x : EXPS) lv[i++] = runExp(x);
  Serial.printf("\n>>> COVER TEST: LEFT-edge (MIC_L, LR=GND) %.1f dBFS | RIGHT-edge (MIC_R, LR=Vdd) %.1f dBFS\n", lv[1], lv[2]);
  Serial.println("------------- cycle done -------------");
}
