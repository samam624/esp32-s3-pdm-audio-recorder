// MMSA V2 bring-up: signs-of-life test.
// Prints chip, flash and PSRAM info over native USB CDC, then a heartbeat once a second.
// Deliberately drives no GPIOs, since the V2 pinout isn't confirmed yet.

#include <Arduino.h>
#include <esp_chip_info.h>
#include <esp_mac.h>

static void printInfo() {
  esp_chip_info_t ci;
  esp_chip_info(&ci);
  uint8_t mac[6];
  esp_efuse_mac_get_default(mac);

  Serial.println();
  Serial.println("=== MMSA V2 signs of life ===");
  Serial.printf("Chip: %s rev %d.%d, %d cores, %lu MHz\n", ESP.getChipModel(),
                ci.revision / 100, ci.revision % 100, ci.cores, (unsigned long)ESP.getCpuFreqMHz());
  Serial.printf("MAC: %02X:%02X:%02X:%02X:%02X:%02X\n", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  Serial.printf("Flash: %lu bytes @ %lu Hz\n", (unsigned long)ESP.getFlashChipSize(),
                (unsigned long)ESP.getFlashChipSpeed());
  Serial.printf("Heap free: %lu bytes\n", (unsigned long)ESP.getFreeHeap());
  if (psramFound()) {
    Serial.printf("PSRAM: %lu bytes total, %lu free\n", (unsigned long)ESP.getPsramSize(),
                  (unsigned long)ESP.getFreePsram());
    // Quick PSRAM write/read check over 1 MB.
    const size_t n = 1024 * 1024;
    uint32_t *buf = (uint32_t *)ps_malloc(n);
    if (buf) {
      size_t words = n / 4, bad = 0;
      for (size_t i = 0; i < words; i++) buf[i] = i * 2654435761u;
      for (size_t i = 0; i < words; i++) if (buf[i] != i * 2654435761u) bad++;
      Serial.printf("PSRAM 1MB pattern test: %s (%u bad words)\n", bad ? "FAIL" : "PASS", (unsigned)bad);
      free(buf);
    } else {
      Serial.println("PSRAM ps_malloc(1MB): FAILED");
    }
  } else {
    Serial.println("PSRAM: NOT FOUND");
  }
  Serial.println("=============================");
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);
  printInfo();
}

void loop() {
  static uint32_t n = 0;
  delay(1000);
  Serial.printf("alive %lu  uptime=%lus  heap=%lu\n", (unsigned long)n++, (unsigned long)(millis() / 1000),
                (unsigned long)ESP.getFreeHeap());
  if (n % 10 == 0) printInfo();
}
