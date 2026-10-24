// MMSA V2 bring-up: DC short check on the mic lines (CLK IO4, DATA IO5-IO8), seen from the board.
// No I2S running: each pin is used as a plain GPIO.
//   1. All pins input + pull-DOWN, then + pull-UP: a pin stuck against its pull = tied to GND or a supply.
//   2. Drive each pin HIGH (others pulled down) and LOW (others pulled up): any other pin that follows
//      is shorted to it.
// Only detects shorts. An open (cracked trace, connector pin not touching) looks like a normal floating pin.
// Note: 1V8 sits between the ESP32's logic thresholds, so a pin tied to 1V8 may read either way; a pin that
// reads HIGH with pull-down is tied to a supply (1V8 or 3V3).
// Build with PSRAM=disabled.

#include <Arduino.h>
#include <driver/gpio.h>
#include <soc/gpio_reg.h>
#include <esp_cpu.h>

static const gpio_num_t PINS[5] = {GPIO_NUM_4, GPIO_NUM_5, GPIO_NUM_6, GPIO_NUM_7, GPIO_NUM_8};
static const char *NAMES[5] = {"CLK(IO4)", "D1(IO5)", "D2(IO6)", "D3(IO7)", "D4(IO8)"};

static void setInput(gpio_num_t p, bool up) {
  gpio_reset_pin(p);
  gpio_set_direction(p, GPIO_MODE_INPUT);
  gpio_set_pull_mode(p, up ? GPIO_PULLUP_ONLY : GPIO_PULLDOWN_ONLY);
}

static void drive(gpio_num_t p, int lv) {
  gpio_reset_pin(p);
  gpio_set_direction(p, GPIO_MODE_INPUT_OUTPUT);
  gpio_set_level(p, lv);
}

static void readAll(int *r) {
  delay(20);
  for (int i = 0; i < 5; i++) r[i] = gpio_get_level(PINS[i]);
}

static void printRow(const char *label, const int *r) {
  Serial.printf("%-34s", label);
  for (int i = 0; i < 5; i++) Serial.printf(" %s=%d", NAMES[i], r[i]);
  Serial.println();
}

// ---- Timing comparison between lines (added 2026-10-21, for IO7/IO8 vs IO5/IO6) ----
// Rise/fall: drive the pin to one level, release it with the internal ~45 kOhm pull to the other level, and time
// until the input flips. Time ~ R x C, so it compares each line's capacitance (board + FPC + flex).
// Hold: drive the pin, release it with NO pull, and time how long it keeps its level. A soft leak (residue,
// damaged pad) to another node makes the hold much shorter on that line only.
static uint32_t edgeNs(gpio_num_t p, int from) {
  uint32_t best = UINT32_MAX;
  for (int k = 0; k < 15; k++) {
    gpio_reset_pin(p);
    gpio_set_pull_mode(p, from ? GPIO_PULLDOWN_ONLY : GPIO_PULLUP_ONLY);
    gpio_set_direction(p, GPIO_MODE_INPUT_OUTPUT);
    gpio_set_level(p, from);
    delayMicroseconds(200);
    uint32_t bit = 1u << p, cycles = 0;
    noInterrupts();
    uint32_t t0 = esp_cpu_get_cycle_count();
    REG_WRITE(GPIO_ENABLE_W1TC_REG, bit);  // stop driving: only the pull remains
    while (((REG_READ(GPIO_IN_REG) & bit) != 0) == (from != 0)) {
      cycles = esp_cpu_get_cycle_count() - t0;
      if (cycles > 240000) break;  // 1 ms timeout
    }
    interrupts();
    if (cycles < best) best = cycles;
  }
  return (uint32_t)(best * 1000ULL / 240);  // 240 MHz CPU -> ns
}

static uint32_t holdUs(gpio_num_t p, int level) {
  gpio_reset_pin(p);
  gpio_set_pull_mode(p, GPIO_FLOATING);
  gpio_set_direction(p, GPIO_MODE_INPUT_OUTPUT);
  gpio_set_level(p, level);
  delayMicroseconds(200);
  uint32_t bit = 1u << p;
  uint32_t t0 = micros();
  REG_WRITE(GPIO_ENABLE_W1TC_REG, bit);
  while (((REG_READ(GPIO_IN_REG) & bit) != 0) == (level != 0)) {
    if (micros() - t0 > 2000000) break;  // 2 s cap
  }
  return micros() - t0;
}

static void timingTest() {
  Serial.println("\n=== Line timing (data lines; best of 15 for edges) ===");
  Serial.println("line       rise via pull-up   fall via pull-down   hold HIGH floating   hold LOW floating");
  for (int i = 1; i < 5; i++) {
    uint32_t r = edgeNs(PINS[i], 0), f = edgeNs(PINS[i], 1);
    uint32_t hh = holdUs(PINS[i], 1), hl = holdUs(PINS[i], 0);
    Serial.printf("%-9s %10lu ns %17lu ns %16lu us %17lu us%s\n", NAMES[i], (unsigned long)r, (unsigned long)f,
                  (unsigned long)hh, (unsigned long)hl, (hh >= 2000000 || hl >= 2000000) ? "  (>=2 s = capped)" : "");
    setInput(PINS[i], false);
  }
}

static void runTest() {
  int r[5];
  bool anyIssue = false;
  Serial.println("\n=== Mic line short check ===");

  for (int i = 0; i < 5; i++) setInput(PINS[i], false);
  readAll(r);
  printRow("All inputs, pull-DOWN (expect 0):", r);
  for (int i = 0; i < 5; i++)
    if (r[i]) {
      Serial.printf("  !! %s reads HIGH against pull-down: tied to a supply (1V8/3V3) or driven high\n", NAMES[i]);
      anyIssue = true;
    }

  for (int i = 0; i < 5; i++) setInput(PINS[i], true);
  readAll(r);
  printRow("All inputs, pull-UP (expect 1):", r);
  for (int i = 0; i < 5; i++)
    if (!r[i]) {
      Serial.printf("  !! %s reads LOW against pull-up: tied to GND or held low by something\n", NAMES[i]);
      anyIssue = true;
    }

  for (int d = 0; d < 5; d++) {
    for (int i = 0; i < 5; i++) setInput(PINS[i], false);
    drive(PINS[d], 1);
    readAll(r);
    char lbl[48];
    snprintf(lbl, sizeof(lbl), "Drive %s HIGH, others pull-down:", NAMES[d]);
    printRow(lbl, r);
    if (!r[d]) {
      Serial.printf("  !! %s can't be driven HIGH: hard short to GND\n", NAMES[d]);
      anyIssue = true;
    }
    for (int i = 0; i < 5; i++)
      if (i != d && r[i]) {
        Serial.printf("  !! %s follows %s HIGH: shorted together\n", NAMES[i], NAMES[d]);
        anyIssue = true;
      }

    for (int i = 0; i < 5; i++) setInput(PINS[i], true);
    drive(PINS[d], 0);
    readAll(r);
    snprintf(lbl, sizeof(lbl), "Drive %s LOW, others pull-up:", NAMES[d]);
    printRow(lbl, r);
    if (r[d]) {
      Serial.printf("  !! %s can't be driven LOW: hard short to a supply\n", NAMES[d]);
      anyIssue = true;
    }
    for (int i = 0; i < 5; i++)
      if (i != d && !r[i]) {
        Serial.printf("  !! %s follows %s LOW: shorted together\n", NAMES[i], NAMES[d]);
        anyIssue = true;
      }
  }
  for (int i = 0; i < 5; i++) setInput(PINS[i], false);
  Serial.println(anyIssue ? "RESULT: issues flagged above" : "RESULT: no shorts found (opens can't be seen by this test)");
  timingTest();
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  runTest();
}

void loop() {
  delay(8000);
  runTest();
}
