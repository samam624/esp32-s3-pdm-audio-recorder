// ESP32-S3 custom PCB: PDM MEMS microphone recorded to a local SD card (SPI).
//
// Combines the PDM capture from ESP32_S3_USB_Mic/ESP32_S3_USB_Mic.ino with the
// SD/SPI pinout validated in SD_Card_SPI_Diagnostic/SD_Card_SPI_Diagnostic.ino.
//
// Press the button (or send a BLE command) once to start recording a new WAV
// file, again to stop. The REC LED blinks while recording, like a normal
// camcorder/recorder tally light. The LEVEL LED shows input level. The SD
// LED is solid while the card is mounted and ready, and updates live: there's
// no hardware card-detect pin wired on this PCB, so presence is inferred in
// software by updateSdPresence() (periodic probe when idle, immediate on a
// failed write during recording).
//
// Audio is captured on a dedicated FreeRTOS task (pinned to core 0) that never
// blocks on SD I/O, so a slow SD write can't starve the I2S DMA and drop
// samples (the cause of sped-up/glitchy recordings). Captured buffers are
// handed to loop() (core 1) through a queue-backed buffer pool; loop() is the
// only thing that touches the SD card.
//
// Remote trigger: a BLE service exposes a write characteristic (start/stop/
// toggle) and a notify characteristic (recording state) — see the "BLE
// control" section. A future WiFi trigger can hook in the same way, by
// calling toggleRecording() / startRecording() / stopRecording() from its own
// handler; no other changes should be required.
//
// Build with the ESP32 Arduino core using:
//   Board: ESP32S3 Dev Module

#include <Arduino.h>
#include <driver/i2s_pdm.h>
#include <math.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ---- PDM microphone pins (from ESP32_S3_USB_Mic.ino) ----
#define PDM_CLK_PIN       4
#define PDM_DATA_PIN      5
#define BUTTON_PIN        35
#define REC_LED_PIN       40
#define LEVEL_LED_PIN     41
#define SD_STATUS_LED_PIN 42

// ---- SD card SPI pins (from SD_Card_SPI_Diagnostic.ino) ----
// No dedicated card-detect pin is wired on this build of the PCB, so presence
// is inferred in software instead (see updateSdPresence()).
#define SD_SCK            12
#define SD_MOSI           13
#define SD_MISO           11
#define SD_CS             14

#define SAMPLE_RATE       48000
#define CHANNELS          2
#define BITS_PER_SAMPLE   16

// Audio buffer pool shared between the I2S reader task and loop()'s SD writer.
// 32 buffers x 4096 bytes = 128KB, ~680ms of audio headroom to absorb slow SD
// writes without ever blocking the I2S read and losing samples.
#define BUFFER_FRAMES     1024
#define BUFFER_BYTES      (BUFFER_FRAMES * CHANNELS * (BITS_PER_SAMPLE / 8))
#define NUM_BUFFERS       32

#define DEBOUNCE_MS       50
#define REC_BLINK_MS      400

#define LEVEL_GAIN        6.0f
#define LEVEL_THRESHOLD   0.035f
#define LEVEL_ATTACK      0.25f
#define LEVEL_RELEASE     0.06f

#define FLUSH_INTERVAL_MS 1000
#define SD_CHECK_INTERVAL_MS 50

#define BLE_DEVICE_NAME       "ESP32 SD Recorder"
#define BLE_SERVICE_UUID      "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define BLE_CONTROL_CHAR_UUID "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define BLE_STATUS_CHAR_UUID  "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

struct AudioChunk {
  uint8_t *data;
  size_t len;
};

SPIClass sdSPI(FSPI);
i2s_chan_handle_t rx_handle;

static uint8_t audioPool[NUM_BUFFERS][BUFFER_BYTES];
static QueueHandle_t freeQueue;
static QueueHandle_t filledQueue;

bool sdReady = false;
bool recording = false;
File recordingFile;
uint32_t dataBytesWritten = 0;
unsigned long lastFlushMs = 0;
unsigned long lastSdCheckMs = 0;

bool lastButton = HIGH;
unsigned long lastDebounceMs = 0;
unsigned long lastRecBlinkMs = 0;
bool recBlinkState = false;
float levelSmoothed = 0.0f;

BLECharacteristic *bleStatusCharacteristic = nullptr;
bool bleClientConnected = false;

// ---------------------------------------------------------------------------
// WAV header
// ---------------------------------------------------------------------------

static void writeWavHeader(File &f, uint32_t dataSize) {
  uint32_t byteRate = SAMPLE_RATE * CHANNELS * (BITS_PER_SAMPLE / 8);
  uint16_t blockAlign = CHANNELS * (BITS_PER_SAMPLE / 8);
  uint32_t chunkSize = 36 + dataSize;

  uint8_t header[44];
  memcpy(header + 0, "RIFF", 4);
  memcpy(header + 4, &chunkSize, 4);
  memcpy(header + 8, "WAVE", 4);
  memcpy(header + 12, "fmt ", 4);
  uint32_t subchunk1Size = 16;
  memcpy(header + 16, &subchunk1Size, 4);
  uint16_t audioFormat = 1;
  memcpy(header + 20, &audioFormat, 2);
  uint16_t numChannels = CHANNELS;
  memcpy(header + 22, &numChannels, 2);
  uint32_t sampleRate = SAMPLE_RATE;
  memcpy(header + 24, &sampleRate, 4);
  memcpy(header + 28, &byteRate, 4);
  memcpy(header + 32, &blockAlign, 2);
  uint16_t bitsPerSample = BITS_PER_SAMPLE;
  memcpy(header + 34, &bitsPerSample, 2);
  memcpy(header + 36, "data", 4);
  memcpy(header + 40, &dataSize, 4);

  f.seek(0);
  f.write(header, sizeof(header));
}

// ---------------------------------------------------------------------------
// SD card
// ---------------------------------------------------------------------------

// Highest speed first; SD.begin() simply fails and we fall back if the wiring
// on this PCB can't hold the signal integrity at a given clock.
static const uint32_t kSdSpeeds[] = {
  20000000, 16000000, 10000000, 8000000, 4000000, 1000000, 400000
};
static const size_t kSdSpeedCount = sizeof(kSdSpeeds) / sizeof(kSdSpeeds[0]);

static bool mountSd() {
  for (size_t i = 0; i < kSdSpeedCount; i++) {
    SD.end();
    sdSPI.end();
    sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);

    if (SD.begin(SD_CS, sdSPI, kSdSpeeds[i])) {
      Serial.printf("SD mounted at %lu Hz\r\n", (unsigned long)kSdSpeeds[i]);
      return true;
    }
  }

  return false;
}

static bool nextRecordingPath(char *outPath, size_t outPathLen) {
  for (int i = 1; i <= 99999; i++) {
    snprintf(outPath, outPathLen, "/REC_%05d.WAV", i);
    if (!SD.exists(outPath)) {
      return true;
    }
  }
  return false;
}

// Keeps sdReady and the status LED in lockstep so they can never drift apart.
static void setSdReady(bool ready) {
  sdReady = ready;
  digitalWrite(SD_STATUS_LED_PIN, sdReady ? HIGH : LOW);
}

// There's no hardware card-detect pin wired on this PCB, so presence is
// inferred: while mounted, periodically confirm the card still answers a
// cheap directory read; while absent, periodically retry mounting so a card
// inserted later is picked up automatically. Skipped entirely while
// recording so it never competes with the active write for the SPI bus.
static void updateSdPresence() {
  if (recording) {
    return;
  }
  if (millis() - lastSdCheckMs < SD_CHECK_INTERVAL_MS) {
    return;
  }
  lastSdCheckMs = millis();

  bool present = false;
  if (sdReady) {
    File root = SD.open("/");
    if (root) {
      present = true;
      root.close();
    }
  }

  if (!present) {
    present = mountSd();
  }

  if (present != sdReady) {
    setSdReady(present);
    Serial.println(present ? "SD card detected" : "SD card removed");
  }
}

// ---------------------------------------------------------------------------
// BLE status notification
// ---------------------------------------------------------------------------

static void notifyBleStatus() {
  if (!bleStatusCharacteristic) {
    return;
  }

  uint8_t value = recording ? 1 : 0;
  bleStatusCharacteristic->setValue(&value, 1);
  if (bleClientConnected) {
    bleStatusCharacteristic->notify();
  }
}

// ---------------------------------------------------------------------------
// Recording control
// ---------------------------------------------------------------------------

static void startRecording() {
  if (recording || !sdReady) {
    return;
  }

  char path[32];
  if (!nextRecordingPath(path, sizeof(path))) {
    Serial.println("No free recording filename slots on SD card");
    return;
  }

  recordingFile = SD.open(path, FILE_WRITE);
  if (!recordingFile) {
    Serial.printf("Failed to open %s for recording\r\n", path);
    return;
  }

  writeWavHeader(recordingFile, 0);
  dataBytesWritten = 0;
  lastFlushMs = millis();
  recording = true;
  lastRecBlinkMs = millis();
  recBlinkState = true;
  digitalWrite(REC_LED_PIN, HIGH);
  notifyBleStatus();
  Serial.printf("Recording started: %s\r\n", path);
}

static void stopRecording() {
  if (!recording) {
    return;
  }

  writeWavHeader(recordingFile, dataBytesWritten);
  recordingFile.close();
  recording = false;
  digitalWrite(REC_LED_PIN, LOW);
  notifyBleStatus();
  Serial.printf("Recording stopped (%lu bytes)\r\n", (unsigned long)dataBytesWritten);
}

static void toggleRecording() {
  if (recording) {
    stopRecording();
  } else {
    startRecording();
  }
}

// ---------------------------------------------------------------------------
// BLE control
//
// A single GATT service exposes:
//   - a WRITE characteristic: write 0x01/'1' to start, 0x00/'0' to stop, or
//     anything else to toggle (mirrors the physical button).
//   - a NOTIFY characteristic: broadcasts 0x01 while recording, 0x00 when idle.
//
// A future WiFi trigger can live alongside this the same way: have its
// handler call toggleRecording()/startRecording()/stopRecording() directly.
// ---------------------------------------------------------------------------

class BleControlCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    String value = characteristic->getValue();
    if (value.length() == 0) {
      return;
    }

    uint8_t cmd = (uint8_t)value[0];
    if (cmd == '1' || cmd == 1) {
      startRecording();
    } else if (cmd == '0' || cmd == 0) {
      stopRecording();
    } else {
      toggleRecording();
    }
  }
};

class BleServerCallbacksImpl : public BLEServerCallbacks {
  void onConnect(BLEServer *server) override {
    (void)server;
    bleClientConnected = true;
    Serial.println("BLE client connected");
  }

  void onDisconnect(BLEServer *server) override {
    (void)server;
    bleClientConnected = false;
    Serial.println("BLE client disconnected, resuming advertising");
    BLEDevice::startAdvertising();
  }
};

static void beginBle() {
  BLEDevice::init(BLE_DEVICE_NAME);

  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new BleServerCallbacksImpl());

  BLEService *service = server->createService(BLE_SERVICE_UUID);

  BLECharacteristic *controlCharacteristic = service->createCharacteristic(
    BLE_CONTROL_CHAR_UUID,
    BLECharacteristic::PROPERTY_WRITE
  );
  controlCharacteristic->setCallbacks(new BleControlCallbacks());

  bleStatusCharacteristic = service->createCharacteristic(
    BLE_STATUS_CHAR_UUID,
    BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
  );
  bleStatusCharacteristic->addDescriptor(new BLE2902());
  notifyBleStatus();

  service->start();

  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(BLE_SERVICE_UUID);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();

  Serial.printf("BLE advertising as \"%s\"\r\n", BLE_DEVICE_NAME);
}

// ---------------------------------------------------------------------------
// Button + LEDs
// ---------------------------------------------------------------------------

static void checkButton() {
  bool button = digitalRead(BUTTON_PIN);

  if (button != lastButton && millis() - lastDebounceMs > DEBOUNCE_MS) {
    lastDebounceMs = millis();
    lastButton = button;

    if (button == LOW) {
      toggleRecording();
    }
  }
}

static void updateLevelMeter(const int16_t *samples, size_t sampleCount) {
  int64_t sumSquares = 0;

  for (size_t i = 0; i < sampleCount; i++) {
    int32_t v = samples[i];
    sumSquares += (int64_t)v * v;
  }

  float rms = sqrtf((float)sumSquares / (float)sampleCount) / 32768.0f;
  float gated = 0.0f;

  if (rms > LEVEL_THRESHOLD) {
    gated = (rms - LEVEL_THRESHOLD) / (1.0f - LEVEL_THRESHOLD);
    gated *= LEVEL_GAIN;
    if (gated > 1.0f) {
      gated = 1.0f;
    }
  }

  float smoothing = gated > levelSmoothed ? LEVEL_ATTACK : LEVEL_RELEASE;
  levelSmoothed = (1.0f - smoothing) * levelSmoothed + smoothing * gated;

  analogWrite(LEVEL_LED_PIN, (int)(levelSmoothed * 255.0f));
}

static void updateRecordLed() {
  if (!recording) {
    digitalWrite(REC_LED_PIN, LOW);
    return;
  }

  if (millis() - lastRecBlinkMs >= REC_BLINK_MS) {
    lastRecBlinkMs = millis();
    recBlinkState = !recBlinkState;
    digitalWrite(REC_LED_PIN, recBlinkState ? HIGH : LOW);
  }
}

// ---------------------------------------------------------------------------
// PDM microphone
// ---------------------------------------------------------------------------

static void beginPdmMic() {
  i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  // Deeper DMA queue than the default gives the driver its own cushion
  // (on top of the app-level buffer pool) before any data could be dropped.
  chan_cfg.dma_desc_num = 8;
  chan_cfg.dma_frame_num = BUFFER_FRAMES;
  ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &rx_handle));

  i2s_pdm_rx_config_t pdm_rx_cfg = {
    .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
    .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT,
      I2S_SLOT_MODE_STEREO
    ),
    .gpio_cfg = {
      .clk = (gpio_num_t)PDM_CLK_PIN,
      .din = (gpio_num_t)PDM_DATA_PIN,
      .invert_flags = {
        .clk_inv = false,
      },
    },
  };

  ESP_ERROR_CHECK(i2s_channel_init_pdm_rx_mode(rx_handle, &pdm_rx_cfg));
  ESP_ERROR_CHECK(i2s_channel_enable(rx_handle));
}

// ---------------------------------------------------------------------------
// I2S reader task (core 0) — never touches the SD card, so it can always
// keep draining the I2S DMA on schedule regardless of how long a pending SD
// write takes on the other core.
// ---------------------------------------------------------------------------

static void i2sReaderTask(void *param) {
  (void)param;

  for (;;) {
    uint8_t *buf = NULL;
    xQueueReceive(freeQueue, &buf, portMAX_DELAY);

    size_t bytesRead = 0;
    esp_err_t err = i2s_channel_read(rx_handle, buf, BUFFER_BYTES, &bytesRead, portMAX_DELAY);

    if (err == ESP_OK && bytesRead > 0) {
      AudioChunk chunk = { buf, bytesRead };
      xQueueSend(filledQueue, &chunk, portMAX_DELAY);
    } else {
      xQueueSend(freeQueue, &buf, portMAX_DELAY);
    }
  }
}

void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(REC_LED_PIN, OUTPUT);
  pinMode(LEVEL_LED_PIN, OUTPUT);
  pinMode(SD_STATUS_LED_PIN, OUTPUT);

  digitalWrite(REC_LED_PIN, LOW);
  analogWrite(LEVEL_LED_PIN, 0);
  digitalWrite(SD_STATUS_LED_PIN, LOW);

  Serial.begin(115200);
  delay(500);

  beginPdmMic();

  freeQueue = xQueueCreate(NUM_BUFFERS, sizeof(uint8_t *));
  filledQueue = xQueueCreate(NUM_BUFFERS, sizeof(AudioChunk));
  for (int i = 0; i < NUM_BUFFERS; i++) {
    uint8_t *ptr = audioPool[i];
    xQueueSend(freeQueue, &ptr, 0);
  }

  xTaskCreatePinnedToCore(i2sReaderTask, "i2s_reader", 4096, NULL, 10, NULL, 0);

  setSdReady(mountSd());
  if (sdReady) {
    Serial.printf("SD card mounted, %llu MB total\r\n",
                  SD.cardSize() / (1024ULL * 1024ULL));
  } else {
    Serial.println("SD card mount failed, recording disabled");
  }

  beginBle();

  Serial.println("SD recorder ready. Press the button to start/stop recording.");
}

void loop() {
  checkButton();
  updateRecordLed();
  updateSdPresence();

  AudioChunk chunk;
  if (xQueueReceive(filledQueue, &chunk, pdMS_TO_TICKS(50)) != pdTRUE) {
    return;
  }

  size_t sampleCount = chunk.len / sizeof(int16_t);
  updateLevelMeter((const int16_t *)chunk.data, sampleCount);

  if (recording) {
    size_t written = recordingFile.write(chunk.data, chunk.len);
    dataBytesWritten += written;

    if (written != chunk.len) {
      Serial.println("SD write short/failed, stopping recording");
      stopRecording();
      setSdReady(false);
    } else if (millis() - lastFlushMs >= FLUSH_INTERVAL_MS) {
      lastFlushMs = millis();
      recordingFile.flush();
    }
  }

  xQueueSend(freeQueue, &chunk.data, portMAX_DELAY);
}
