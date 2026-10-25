#include <Arduino.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"

// MMSA V2 bring-up: SD card test. Adapted from V1's SD_Card_SPI_Diagnostic.
// SD pins are identical to V1 (see MMSA V2/reference/COMPONENT_INDEX.md). V2 has no card-detect pin.
// Runs at boot; rerun with 't' over serial or by pressing REC.
// REC LED (IO40): solid = all passed, fast blink = failed.
// Build with PSRAM=disabled (REC button on IO35 shares the octal PSRAM).
#define SD_SCK   12
#define SD_MOSI  13
#define SD_MISO  11
#define SD_CS    14
#define BUTTON_PIN 35
#define LED_PIN    40

#define SERIAL_BAUD       115200
#define SPI_INIT_HZ       400000
#define SPI_RETRY_SLOW_HZ 100000
#define SPI_FAST_HZ       4000000
#define SPI_RECORD_HZ     20000000   // speed V1's recorder runs the card at

static bool lastResult = false;

SPIClass sdSPI(FSPI);

static void printHexByte(uint8_t value) {
  if (value < 0x10) {
    Serial.print('0');
  }
  Serial.print(value, HEX);
}

static void printBytes(const uint8_t *bytes, size_t count) {
  for (size_t i = 0; i < count; i++) {
    Serial.print(" 0x");
    printHexByte(bytes[i]);
  }
  Serial.println();
}

static void deselectCard() {
  digitalWrite(SD_CS, HIGH);
  sdSPI.transfer(0xFF);
}

static void selectCard() {
  digitalWrite(SD_CS, LOW);
  sdSPI.transfer(0xFF);
}

static uint8_t waitResponse(uint32_t timeoutMs) {
  uint32_t start = millis();

  while (millis() - start < timeoutMs) {
    uint8_t response = sdSPI.transfer(0xFF);
    if ((response & 0x80) == 0) {
      return response;
    }
  }

  return 0xFF;
}

static uint8_t sendSdCommand(uint8_t cmd, uint32_t arg, uint8_t crc, uint8_t *extra, size_t extraLen) {
  selectCard();

  sdSPI.transfer(0x40 | cmd);
  sdSPI.transfer((arg >> 24) & 0xFF);
  sdSPI.transfer((arg >> 16) & 0xFF);
  sdSPI.transfer((arg >> 8) & 0xFF);
  sdSPI.transfer(arg & 0xFF);
  sdSPI.transfer(crc);

  uint8_t response = waitResponse(250);

  for (size_t i = 0; i < extraLen; i++) {
    extra[i] = sdSPI.transfer(0xFF);
  }

  deselectCard();
  return response;
}

static void printR1(const char *label, uint8_t r1) {
  Serial.print(label);
  Serial.print(" R1=0x");
  printHexByte(r1);

  if (r1 == 0xFF) {
    Serial.println(" (no response on MISO)");
    return;
  }

  if (r1 & 0x01) Serial.print(" idle");
  if (r1 & 0x02) Serial.print(" erase-reset");
  if (r1 & 0x04) Serial.print(" illegal-cmd");
  if (r1 & 0x08) Serial.print(" crc-error");
  if (r1 & 0x10) Serial.print(" erase-seq-error");
  if (r1 & 0x20) Serial.print(" address-error");
  if (r1 & 0x40) Serial.print(" parameter-error");
  if (r1 == 0x00) Serial.print(" ready");

  Serial.println();
}

static void printCardType(uint8_t cardType) {
  Serial.print("Card type: ");
  if (cardType == CARD_MMC) {
    Serial.println("MMC");
  } else if (cardType == CARD_SD) {
    Serial.println("SDSC");
  } else if (cardType == CARD_SDHC) {
    Serial.println("SDHC/SDXC");
  } else if (cardType == CARD_NONE) {
    Serial.println("NONE");
  } else {
    Serial.println("UNKNOWN");
  }
}

static void printPinState() {
  pinMode(SD_CS, OUTPUT);
  digitalWrite(SD_CS, HIGH);

  pinMode(SD_MISO, INPUT_PULLUP);

  Serial.println();
  Serial.println("Pin state before SPI:");
  Serial.printf("  SCK=%d MOSI=%d MISO=%d CS=%d (no card-detect on V2)\r\n", SD_SCK, SD_MOSI, SD_MISO, SD_CS);
  Serial.printf("  CS idle level: %s\r\n", digitalRead(SD_CS) ? "HIGH" : "LOW");
  Serial.printf("  MISO with INPUT_PULLUP before bus start: %s\r\n", digitalRead(SD_MISO) ? "HIGH" : "LOW");
}

static void rawSpiProbe() {
  uint8_t highBytes[12];
  uint8_t lowBytes[12];

  Serial.println();
  Serial.printf("Raw SPI probe at %lu Hz:\r\n", (unsigned long)SPI_INIT_HZ);

  SD.end();
  sdSPI.end();
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  sdSPI.beginTransaction(SPISettings(SPI_INIT_HZ, MSBFIRST, SPI_MODE0));

  digitalWrite(SD_CS, HIGH);
  for (size_t i = 0; i < sizeof(highBytes); i++) {
    highBytes[i] = sdSPI.transfer(0xFF);
  }

  digitalWrite(SD_CS, LOW);
  for (size_t i = 0; i < sizeof(lowBytes); i++) {
    lowBytes[i] = sdSPI.transfer(0xFF);
  }
  digitalWrite(SD_CS, HIGH);
  sdSPI.transfer(0xFF);

  sdSPI.endTransaction();

  Serial.print("  MISO bytes with CS HIGH:");
  printBytes(highBytes, sizeof(highBytes));
  Serial.print("  MISO bytes with CS LOW:");
  printBytes(lowBytes, sizeof(lowBytes));

  Serial.println("  Expected: CS HIGH is usually all 0xFF. All 0x00 often means MISO is held low.");
}

static void lowLevelSdProbe() {
  uint8_t extra[4] = {0};

  Serial.println();
  Serial.println("Low-level SD command probe:");

  SD.end();
  sdSPI.end();
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  sdSPI.beginTransaction(SPISettings(SPI_INIT_HZ, MSBFIRST, SPI_MODE0));

  digitalWrite(SD_CS, HIGH);
  for (int i = 0; i < 10; i++) {
    sdSPI.transfer(0xFF);
  }

  uint8_t r1 = sendSdCommand(0, 0x00000000, 0x95, nullptr, 0);
  printR1("  CMD0  GO_IDLE_STATE", r1);

  r1 = sendSdCommand(8, 0x000001AA, 0x87, extra, sizeof(extra));
  printR1("  CMD8  SEND_IF_COND", r1);
  Serial.print("        CMD8 extra:");
  printBytes(extra, sizeof(extra));

  bool ready = false;
  for (int attempt = 1; attempt <= 20; attempt++) {
    r1 = sendSdCommand(55, 0x00000000, 0x65, nullptr, 0);
    uint8_t acmd41 = sendSdCommand(41, 0x40000000, 0x77, nullptr, 0);

    if (attempt == 1 || attempt == 5 || attempt == 10 || attempt == 20 || acmd41 == 0x00) {
      Serial.printf("  ACMD41 attempt %d: ", attempt);
      printR1("", acmd41);
    }

    if (r1 != 0xFF && acmd41 == 0x00) {
      ready = true;
      break;
    }

    delay(50);
  }

  memset(extra, 0, sizeof(extra));
  r1 = sendSdCommand(58, 0x00000000, 0xFD, extra, sizeof(extra));
  printR1("  CMD58 READ_OCR", r1);
  Serial.print("        OCR:");
  printBytes(extra, sizeof(extra));

  sdSPI.endTransaction();

  if (!ready) {
    Serial.println("  Low-level init did not reach ready state.");
  } else {
    Serial.println("  Low-level init reached ready state.");
  }
}

static bool mountAt(uint32_t frequency) {
  Serial.printf("Trying SD.begin at %lu Hz... ", (unsigned long)frequency);

  SD.end();
  sdSPI.end();
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);

  bool mounted = SD.begin(SD_CS, sdSPI, frequency);
  Serial.println(mounted ? "OK" : "FAILED");
  return mounted;
}

static bool fileSystemTest() {
  Serial.println();
  Serial.println("Filesystem mount/write/read test:");

  bool mounted = mountAt(SPI_RETRY_SLOW_HZ);
  if (!mounted) mounted = mountAt(SPI_INIT_HZ);
  if (!mounted) mounted = mountAt(SPI_FAST_HZ);

  if (!mounted) {
    Serial.println("SD mount failed at all tested speeds.");
    Serial.println("Check CS, MISO continuity/pull-up, 3.3V power, ground, and whether another device is driving MISO.");
    return false;
  }

  uint8_t cardType = SD.cardType();
  printCardType(cardType);

  if (cardType == CARD_NONE) {
    Serial.println("Mounted bus, but the SD library reports CARD_NONE.");
    return false;
  }

  Serial.printf("Card size: %llu MB\r\n", SD.cardSize() / (1024ULL * 1024ULL));
  Serial.printf("Total bytes: %llu\r\n", SD.totalBytes());
  Serial.printf("Used bytes:  %llu\r\n", SD.usedBytes());

  File file = SD.open("/sd_diag.txt", FILE_APPEND);
  if (!file) {
    Serial.println("Failed to open /sd_diag.txt for append.");
    return false;
  }

  // Unique token so the read-back proves this run's record actually landed on the card.
  char token[48];
  snprintf(token, sizeof(token), "SD diagnostic write id=%08lX", (unsigned long)esp_random());
  file.printf("%s millis=%lu\r\n", token, (unsigned long)millis());
  file.close();
  Serial.printf("Appended to /sd_diag.txt: %s\r\n", token);

  // Verify: scan the whole file for the token just written.
  file = SD.open("/sd_diag.txt", FILE_READ);
  if (!file) {
    Serial.println("Failed to reopen /sd_diag.txt for verify.");
    return false;
  }
  bool found = false;
  while (file.available()) {
    String line = file.readStringUntil('\n');
    if (line.indexOf(token) >= 0) found = true;
  }
  file.close();
  Serial.printf("Append verify: %s\r\n", found ? "PASS (new record read back)" : "FAIL (new record not found)");
  if (!found) return false;

  file = SD.open("/sd_diag.txt", FILE_READ);
  if (!file) {
    Serial.println("Failed to reopen /sd_diag.txt for read.");
    return false;
  }

  Serial.println("First bytes from /sd_diag.txt:");
  size_t shown = 0;
  while (file.available() && shown < 256) {
    Serial.write(file.read());
    shown++;
  }
  file.close();

  Serial.println();
  Serial.println("Root directory:");
  File root = SD.open("/");
  if (!root) {
    Serial.println("Failed to open root directory.");
    return false;
  }

  File entry = root.openNextFile();
  while (entry) {
    Serial.print(entry.isDirectory() ? "  <DIR> " : "        ");
    Serial.print(entry.name());
    if (!entry.isDirectory()) {
      Serial.printf("  %llu bytes", (unsigned long long)entry.size());
    }
    Serial.println();
    entry.close();
    entry = root.openNextFile();
  }
  root.close();
  return true;
}

// Write-speed test at recording speed: 1 MB in 4 KB chunks, like an audio recorder would.
// For scale: 8 mics x 16-bit x 48 kHz = 768 KB/s sustained (adjust for the real sample rate).
static bool speedTest() {
  Serial.println();
  Serial.println("Write-speed test (1 MB in 4 KB chunks):");
  if (!mountAt(SPI_RECORD_HZ)) {
    Serial.println("  Could not mount at 20 MHz. Card works at slow speed only: check SPI wiring length/quality.");
    return false;
  }
  static uint8_t buf[4096];
  for (size_t i = 0; i < sizeof(buf); i++) buf[i] = (uint8_t)i;
  File f = SD.open("/speed_test.bin", FILE_WRITE);
  if (!f) {
    Serial.println("  Failed to open /speed_test.bin for write.");
    return false;
  }
  const int chunks = 256;
  uint32_t maxUs = 0, slow = 0;
  uint32_t t0 = micros();
  for (int i = 0; i < chunks; i++) {
    uint32_t c0 = micros();
    if (f.write(buf, sizeof(buf)) != sizeof(buf)) {
      Serial.printf("  Short write at chunk %d\r\n", i);
      f.close();
      return false;
    }
    uint32_t dt = micros() - c0;
    if (dt > maxUs) maxUs = dt;
    if (dt > 50000) slow++;
  }
  f.close();
  uint32_t totalUs = micros() - t0;
  float kbps = (chunks * 4.0f) / (totalUs / 1e6f);
  Serial.printf("  %d KB in %lu ms = %.0f KB/s. Chunk write avg %lu us, max %lu us, %lu chunks > 50 ms\r\n",
                chunks * 4, (unsigned long)(totalUs / 1000), kbps, (unsigned long)(totalUs / chunks),
                (unsigned long)maxUs, (unsigned long)slow);

  // Read back and verify.
  f = SD.open("/speed_test.bin", FILE_READ);
  if (!f) {
    Serial.println("  Failed to reopen /speed_test.bin for verify.");
    return false;
  }
  static uint8_t rb[4096];
  uint32_t bad = 0;
  for (int i = 0; i < chunks; i++) {
    if (f.read(rb, sizeof(rb)) != (int)sizeof(rb) || memcmp(rb, buf, sizeof(rb)) != 0) bad++;
  }
  f.close();
  SD.remove("/speed_test.bin");
  Serial.printf("  Read-back verify: %s (%lu bad chunks)\r\n", bad ? "FAIL" : "PASS", (unsigned long)bad);
  return bad == 0;
}

static void runDiagnostics() {
  Serial.println();
  Serial.println("========================================");
  Serial.println("ESP32-S3 SPI SD Card Diagnostic");
  Serial.println("========================================");

  printPinState();
  rawSpiProbe();
  lowLevelSdProbe();
  bool fsOk = fileSystemTest();
  bool speedOk = fsOk && speedTest();
  lastResult = fsOk && speedOk;

  Serial.println();
  Serial.printf("RESULT: mount/write/read %s, 20 MHz speed+verify %s\r\n", fsOk ? "PASS" : "FAIL",
                fsOk ? (speedOk ? "PASS" : "FAIL") : "skipped");

  Serial.println();
  Serial.println("Diagnostics complete. Type 't' + Enter, or press REC, to run again.");
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Serial.setTimeout(10);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  delay(2000);

  runDiagnostics();
}

void loop() {
  // REC LED: solid on pass, fast blink on fail.
  digitalWrite(LED_PIN, lastResult ? HIGH : ((millis() / 150) % 2));

  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(30);
    if (digitalRead(BUTTON_PIN) == LOW) {
      while (digitalRead(BUTTON_PIN) == LOW) delay(5);
      runDiagnostics();
    }
    return;
  }

  if (!Serial.available()) {
    delay(25);
    return;
  }

  char command = Serial.read();
  if (command == 't' || command == 'T' || command == '\n' || command == '\r') {
    while (Serial.available()) {
      Serial.read();
    }
    runDiagnostics();
  }
}
