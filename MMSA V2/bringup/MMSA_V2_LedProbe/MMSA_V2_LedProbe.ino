// MMSA V2 bring-up: LED pin probe for IO40/41/42 (module pads 33/34/35, adjacent).
// Phase A (automatic): checks each pin's pad level with pull-ups/pull-downs and while driving its
// neighbours, to catch shorts/bridges between the three pins or an unexpected LED topology.
// Phase B (visual, loops): steps through fixed LED patterns, 2.5 s each, printing the step name.
// Nothing else runs (no mic, no button logic). Build with PSRAM=disabled.

#include <Arduino.h>
#include <driver/gpio.h>

static const gpio_num_t PINS[3] = {GPIO_NUM_40, GPIO_NUM_41, GPIO_NUM_42};
#define BUTTON_PIN 35

static void setInput(gpio_num_t p, bool pullup) {
  gpio_reset_pin(p);
  gpio_set_direction(p, GPIO_MODE_INPUT);
  gpio_set_pull_mode(p, pullup ? GPIO_PULLUP_ONLY : GPIO_PULLDOWN_ONLY);
}

static void drive(gpio_num_t p, int level) {
  gpio_reset_pin(p);
  gpio_set_direction(p, GPIO_MODE_INPUT_OUTPUT);  // output, with pad readback
  gpio_set_level(p, level);
}

static void readAll(char *out) {
  delay(5);
  for (int i = 0; i < 3; i++) out[i] = gpio_get_level(PINS[i]) ? '1' : '0';
  out[3] = 0;
}

static void phaseA() {
  char r[4];
  Serial.println("\n=== Phase A: pad checks (pads listed as IO40 IO41 IO42) ===");

  for (int i = 0; i < 3; i++) setInput(PINS[i], false);
  readAll(r);
  Serial.printf("All inputs, pull-DOWN:          %s   (expect 000; a 1 means something external pulls it high)\n", r);
  for (int i = 0; i < 3; i++) setInput(PINS[i], true);
  readAll(r);
  Serial.printf("All inputs, pull-UP:            %s   (expect 111; a 0 means something external pulls it low)\n", r);

  for (int d = 0; d < 3; d++) {
    for (int i = 0; i < 3; i++) setInput(PINS[i], false);
    drive(PINS[d], 1);
    readAll(r);
    Serial.printf("Drive IO%d HIGH, others pull-down: %s", 40 + d, r);
    bool bad = r[d] != '1';
    for (int i = 0; i < 3; i++)
      if (i != d && r[i] == '1') {
        Serial.printf("  <-- IO%d follows IO%d (short/bridge?)", 40 + i, 40 + d);
        bad = true;
      }
    if (r[d] != '1') Serial.printf("  <-- IO%d pad won't go HIGH (shorted to GND/neighbour?)", 40 + d);
    Serial.println(bad ? "" : "  ok");

    for (int i = 0; i < 3; i++) setInput(PINS[i], true);
    drive(PINS[d], 0);
    readAll(r);
    Serial.printf("Drive IO%d LOW,  others pull-up:   %s", 40 + d, r);
    bad = r[d] != '0';
    for (int i = 0; i < 3; i++)
      if (i != d && r[i] == '0') {
        Serial.printf("  <-- IO%d follows IO%d (short/bridge?)", 40 + i, 40 + d);
        bad = true;
      }
    if (r[d] != '0') Serial.printf("  <-- IO%d pad won't go LOW (shorted to 3V3/neighbour?)", 40 + d);
    Serial.println(bad ? "" : "  ok");
  }
  for (int i = 0; i < 3; i++) drive(PINS[i], 0);
}

struct Step {
  const char *name;
  int lv[3];
};
static const Step STEPS[] = {
  {"ALL LOW (expect all LEDs off)", {0, 0, 0}},
  {"IO40 HIGH only", {1, 0, 0}},
  {"IO41 HIGH only", {0, 1, 0}},
  {"IO42 HIGH only", {0, 0, 1}},
  {"ALL HIGH (expect all LEDs on)", {1, 1, 1}},
};

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.println("\nMMSA V2 LED probe");
  phaseA();
  Serial.println("\n=== Phase B: visual steps, 2.5 s each (loops) ===");
}

void loop() {
  static int cycle = 0;
  for (const Step &s : STEPS) {
    char r[4];
    for (int i = 0; i < 3; i++) drive(PINS[i], s.lv[i]);
    readAll(r);
    Serial.printf("[cycle %d] %-32s set %d%d%d  pads %s  REC=%s\n", cycle, s.name, s.lv[0], s.lv[1], s.lv[2], r,
                  digitalRead(BUTTON_PIN) == LOW ? "pressed" : "up");
    delay(2500);
  }
  cycle++;
  if (cycle % 4 == 0) phaseA();
}
