// MMSA V2 bring-up: mic press test (data line IO5, MIC_L + MIC_R).
// Captures raw PDM on both clock edges of line 0 and prints, every 500 ms, how many 16-bit words are
// identical between the LEFT-edge and RIGHT-edge slots.
//   ~100% identical -> only one stream on the line (one mic not driving, or both on the same edge)
//   low (< ~50%)    -> two distinct streams: both mics driving on their own edges
// Press firmly on one mic at a time and watch whether the number changes: a joint that only connects
// under pressure shows up as the % dropping while pressed.
// Build with PSRAM=disabled.

#include <Arduino.h>
#include <driver/i2s_pdm.h>

#define MIC_CLK_PIN 4
#define MIC_DATA_PIN 5
#define FRAMES 256
#define REPORT_MS 250
#define LED_TWO 40  // REC LED: lit while two distinct streams are on the line

static i2s_chan_handle_t rx = NULL;
static int16_t buf[FRAMES * 2];

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  pinMode(LED_TWO, OUTPUT);

  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num = 8;
  cc.dma_frame_num = FRAMES;
  ESP_ERROR_CHECK(i2s_new_channel(&cc, NULL, &rx));
  i2s_pdm_rx_config_t cfg = {};
  i2s_pdm_rx_clk_config_t clk = I2S_PDM_RX_CLK_DEFAULT_CONFIG(48000 * 64);  // 3.072 MHz PDM clock
  cfg.clk_cfg = clk;
  i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_RAW_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  cfg.slot_cfg = s;
  cfg.gpio_cfg.clk = (gpio_num_t)MIC_CLK_PIN;
  cfg.gpio_cfg.din = (gpio_num_t)MIC_DATA_PIN;
  ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx, &cfg));
  ESP_ERROR_CHECK(i2s_channel_enable(rx));
  Serial.println("\nMMSA V2 press test: raw PDM, line IO5, LEFT edge vs RIGHT edge");
  Serial.println("time_s  identical%  L_density  R_density");
}

void loop() {
  static uint32_t words = 0, same = 0, onesL = 0, onesR = 0, last = millis();
  // Bit-transition rate inside each word. A live PDM mic toggles constantly (high rate); a floating,
  // undriven line that's merely disturbed (finger, coupling) changes slowly (low rate).
  static uint32_t trL = 0, trR = 0;
  // Bit agreement between the LEFT and RIGHT samples of the same clock period. A floating line that holds
  // MIC 1's bit and gets disturbed stays ~90%+ in agreement; an independent second mic sits near ~50%.
  static uint32_t diffBits = 0;
  size_t bytes = 0;
  if (i2s_channel_read(rx, buf, sizeof(buf), &bytes, pdMS_TO_TICKS(200)) == ESP_OK) {
    size_t frames = bytes / 4;
    for (size_t f = 0; f < frames; f++) {
      uint16_t a = buf[2 * f], b = buf[2 * f + 1];
      words++;
      if (a == b) same++;
      onesL += __builtin_popcount(a);
      onesR += __builtin_popcount(b);
      trL += __builtin_popcount((a ^ (a >> 1)) & 0x7FFF);
      trR += __builtin_popcount((b ^ (b >> 1)) & 0x7FFF);
      diffBits += __builtin_popcount((uint16_t)(a ^ b));
    }
  }
  if (millis() - last >= REPORT_MS) {
    float pct = words ? 100.0f * same / words : 0;
    float tl = words ? trL / (15.0f * words) : 0, tr = words ? trR / (15.0f * words) : 0;
    float agree = words ? 1.0f - diffBits / (16.0f * words) : 1.0f;
    // Real second mic: bit agreement well below the ~90% a disturbed floating copy shows.
    bool realTwo = agree < 0.75f;
    digitalWrite(LED_TWO, realTwo ? HIGH : LOW);  // REC LED on = a genuine second mic stream
    const char *state = agree > 0.99f ? "ONE STREAM          "
                        : (realTwo ? "TWO MICS            " : "COPY + DISTURBANCE  ");
    Serial.printf("%6.1f  words %5.1f%%  bits %5.1f%%  %s dens %.3f %.3f  toggle %.3f %.3f\n", millis() / 1000.0, pct,
                  100.0f * agree, state, words ? onesL / (16.0 * words) : 0, words ? onesR / (16.0 * words) : 0, tl, tr);
    words = same = onesL = onesR = trL = trR = diffBits = 0;
    last = millis();
  }
}
