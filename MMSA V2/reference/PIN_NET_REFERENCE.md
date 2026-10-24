# MMSA V2 PCB — Pin/Net Reference

**Partial, hand-built 2026-10-20.** These are the nets known so far, in alphabetical order. See `COMPONENT_INDEX.md` for sources and which names are placeholders (marked *). Refdes key: ESP = ESP32-S3-WROOM-1, SD = MTSW-106 microSD header, FPC = Molex 52745-1097 mic flex connector, CHG = MCP73871, RDIV_* = battery divider.

| Net | Pins | Function |
|---|---|---|
| `3V3` | ESP-2, SD-1, FPC-1 (assumed) | 3.3 V rail: module and SD card supply. Source regulator TBD |
| `BATT_ESP32` | ESP-17 (IO9), RDIV_TOP-2, RDIV_BOT-1 | VBAT/2 from the 100k/100k divider → ADC1_CH8 |
| `GND` | ESP-1/40/41, SD-6, FPC-2/8/9/10/11/12, RDIV_BOT-2, CHG-10/11/EP | Ground |
| `LED_IO40`* | ESP-33 (IO40) | Record-ready LED: on while SD mounted (user-defined) |
| `LED_IO41`* | ESP-34 (IO41) | Loudness meter LED, PWM (user-defined) |
| `LED_IO42`* | ESP-35 (IO42) | REC LED, blinks while recording (user-defined) |
| `MIC_CLK`* | ESP-4 (IO4), FPC-3..7 (which pin TBD), all mic CLK pins | PDM clock, shared |
| `MIC_DATA1`* | ESP-5 (IO5), FPC-3..7 (which pin TBD) | PDM data line 1 (one L/R mic pair) |
| `MIC_DATA2`* | ESP-6 (IO6), FPC-3..7 (which pin TBD) | PDM data line 2 |
| `MIC_DATA3`* | ESP-7 (IO7), FPC-3..7 (which pin TBD) | PDM data line 3 |
| `MIC_DATA4`* | ESP-12 (IO8), FPC-3..7 (which pin TBD) | PDM data line 4 |
| `REC_BTN`* | ESP-23 (IO21) on boards 1 and 2 (bodge wire, 2026-10-24); ESP-28 (IO35) as designed | REC button, active low. As designed it shares IO35 with the octal PSRAM (PSRAM must stay off); board 1 is bodged to IO21 so PSRAM can be used |
| `SD_CLK` | ESP-20 (IO12), SD-4 | SD SPI clock |
| `SD_CS` | ESP-22 (IO14), SD-2 | SD chip select |
| `SD_MISO` | ESP-19 (IO11), SD-5 | SD data out → ESP |
| `SD_MOSI` | ESP-21 (IO13), SD-3 | ESP → SD data in |
| `VBAT`* | CHG-14/15, RDIV_TOP-1 | Battery positive (divider tap assumed on VBAT) |

## Firmware pin map (quick copy)

```cpp
// MMSA V2: from reference/COMPONENT_INDEX.md
#define MIC_CLK_PIN    4
#define MIC_DATA1_PIN  5
#define MIC_DATA2_PIN  6
#define MIC_DATA3_PIN  7
#define MIC_DATA4_PIN  8
#define BATT_ADC_PIN   9    // VBAT/2, ADC1_CH8
#define SD_MISO_PIN   11
#define SD_SCK_PIN    12
#define SD_MOSI_PIN   13
#define SD_CS_PIN     14
#define LED_A_PIN     40    // role TBD
#define LED_B_PIN     41    // role TBD
#define LED_C_PIN     42    // role TBD
#define REC_BTN_PIN   21    // boards 1 and 2 after the 2026-10-24 bodge (active low, INPUT_PULLUP; PSRAM=opi OK)
                            // unmodified boards: 35, and PSRAM=disabled (shared with octal PSRAM)
// IO36-37: used by the octal PSRAM
```
