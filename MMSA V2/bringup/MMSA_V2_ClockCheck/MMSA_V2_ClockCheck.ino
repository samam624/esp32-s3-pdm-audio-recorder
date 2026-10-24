// MMSA V2 bring-up: is the PDM clock actually toggling at the pin?
// Runs the normal PDM clock on IO4 (I2S0, 3.072 MHz), enables the pad's input buffer, and samples the pad
// level many times. A healthy clock reads HIGH ~50% of the time. A clock shorted to GND (e.g. a solder
// bridge on the flex) reads mostly LOW; shorted to a supply reads mostly HIGH.
// Also samples the 4 data pins (IO5-8) for activity.
// Build with PSRAM=disabled.

#include <Arduino.h>
#include <driver/i2s_pdm.h>
#include "soc/gpio_struct.h"
#include "soc/io_mux_reg.h"

#define MIC_CLK_PIN 4
static const gpio_num_t MIC_DIN[4] = {GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7, GPIO_NUM_8};
static i2s_chan_handle_t rx = NULL;
static int16_t buf[512];

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);

  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  ESP_ERROR_CHECK(i2s_new_channel(&cc, NULL, &rx));
  i2s_pdm_rx_config_t cfg = {};
  i2s_pdm_rx_clk_config_t clk = I2S_PDM_RX_CLK_DEFAULT_CONFIG(48000);
  cfg.clk_cfg = clk;
  i2s_pdm_rx_slot_config_t s = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  cfg.slot_cfg = s;
  cfg.slot_cfg.slot_mask = I2S_PDM_LINE_SLOT_ALL;
  cfg.gpio_cfg.clk = (gpio_num_t)MIC_CLK_PIN;
  for (int i = 0; i < 4; i++) cfg.gpio_cfg.dins[i] = MIC_DIN[i];
  ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx, &cfg));
  ESP_ERROR_CHECK(i2s_channel_enable(rx));

  // Enable the IO4 pad input buffer so GPIO_IN reflects the real pin voltage while I2S drives it.
  REG_SET_BIT(IO_MUX_GPIO4_REG, FUN_IE);
  Serial.println("\nMMSA V2 clock check: IO4 high-fraction (expect ~0.50) and data-pin activity");
}

void loop() {
  size_t got;
  i2s_channel_read(rx, buf, sizeof(buf), &got, 0);  // keep the DMA drained

  const int N = 200000;
  uint32_t clkHigh = 0, dHigh[4] = {0}, dToggles[4] = {0};
  uint32_t prev = GPIO.in;
  for (int i = 0; i < N; i++) {
    uint32_t v = GPIO.in;
    if (v & (1u << 4)) clkHigh++;
    for (int k = 0; k < 4; k++) {
      uint32_t m = 1u << (5 + k);
      if (v & m) dHigh[k]++;
      if ((v ^ prev) & m) dToggles[k]++;
    }
    prev = v;
  }
  float f = clkHigh / (float)N;
  Serial.printf("CLK IO4 high %.3f -> %s | data high/toggles: IO5 %.2f/%lu  IO6 %.2f/%lu  IO7 %.2f/%lu  IO8 %.2f/%lu\n", f,
                f < 0.05 ? "STUCK LOW (clock shorted to GND?)" : (f > 0.95 ? "STUCK HIGH" : "toggling OK"),
                dHigh[0] / (float)N, (unsigned long)dToggles[0], dHigh[1] / (float)N, (unsigned long)dToggles[1],
                dHigh[2] / (float)N, (unsigned long)dToggles[2], dHigh[3] / (float)N, (unsigned long)dToggles[3]);
  delay(500);
}
