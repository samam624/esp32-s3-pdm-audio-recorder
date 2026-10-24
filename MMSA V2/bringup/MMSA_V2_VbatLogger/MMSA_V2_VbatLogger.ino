// MMSA V2 bring-up: battery voltage logger.
// Samples BATT_ESP32 (IO9, VBAT/2 via 100k/100k) at ~1 kHz and prints min/avg/max VBAT every 250 ms,
// so dropouts and charge/terminate cycling on the MCP73871 show up. IO40 LED mirrors the REC button.
// Build with PSRAM=disabled (REC button on IO35 shares the octal PSRAM).

#include <Arduino.h>

#define BATT_PIN   9
#define BUTTON_PIN 35
#define LED_PIN    40
#define WINDOW_MS  250

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  analogReadResolution(12);
  analogSetPinAttenuation(BATT_PIN, ADC_11db);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("\nMMSA V2 VBAT logger: t_ms, vbat_min_mV, vbat_avg_mV, vbat_max_mV, btn");
}

void loop() {
  static uint32_t winStart = millis();
  static uint32_t n = 0, sum = 0, mn = 0xFFFFFFFF, mx = 0;
  uint32_t mv = analogReadMilliVolts(BATT_PIN) * 2;  // divider halves VBAT
  n++; sum += mv;
  if (mv < mn) mn = mv;
  if (mv > mx) mx = mv;
  int btn = digitalRead(BUTTON_PIN);
  digitalWrite(LED_PIN, btn == LOW ? HIGH : LOW);
  if (millis() - winStart >= WINDOW_MS) {
    uint32_t avg = sum / n;
    Serial.printf("%lu, %lu, %lu, %lu, %s%s\n", (unsigned long)millis(), (unsigned long)mn,
                  (unsigned long)avg, (unsigned long)mx, btn == LOW ? "BTN" : "-",
                  (mx - mn > 150) ? "  <-- swing >150mV" : "");
    winStart = millis(); n = 0; sum = 0; mn = 0xFFFFFFFF; mx = 0;
  }
  delayMicroseconds(1000);
}
