// MMSA V2 bring-up: REC button on IO35.
// IO35 is shared with the module's octal PSRAM, so this must be built with PSRAM=disabled
// (same as V1). Prints each press/release, and lights the IO40 LED while held.

#include <Arduino.h>

#define BUTTON_PIN 35
#define LED_PIN    40

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  Serial.printf("\nMMSA V2 button test. psramFound=%d. IO35 idle level=%d\n", psramFound(),
                digitalRead(BUTTON_PIN));
}

void loop() {
  static int last = -1;
  static uint32_t presses = 0, lastChange = 0, lastBeat = 0;
  int b = digitalRead(BUTTON_PIN);
  if (b != last && millis() - lastChange > 30) {
    lastChange = millis();
    if (last != -1) {
      if (b == LOW) presses++;
      Serial.printf("[%lu ms] IO35 %s  (presses=%lu)\n", (unsigned long)millis(),
                    b == LOW ? "PRESSED" : "released", (unsigned long)presses);
    }
    last = b;
    digitalWrite(LED_PIN, b == LOW ? HIGH : LOW);
  }
  if (millis() - lastBeat > 5000) {
    lastBeat = millis();
    Serial.printf("alive, IO35=%d presses=%lu\n", b, (unsigned long)presses);
  }
  delay(2);
}
