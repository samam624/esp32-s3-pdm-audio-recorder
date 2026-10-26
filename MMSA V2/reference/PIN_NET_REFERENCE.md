# MMSA V2 PCB — Pin/Net Reference

From the Altium netlist export `netlist/MMSA_V2_PCB_altium.net` (2026-10-25), plus the rework on boards 1 and 2 (see `COMPONENT_INDEX.md`). Nets are in alphabetical order. Altium's auto-named nets (`NetXX_n`) are listed under the part they serve.

| Net | Pins | Function |
|---|---|---|
| `1V8` | LDO_1V8-5, FPC-1, C11, C16 | Mic supply as designed. **LDO_1V8 removed and this net shorted to 3V3** on the built boards |
| `3V3` | ESP32_MC-2, SD-1, FB-2, LDO_1V8-1/3, USB_IC-4 (PROG2), USB_IC-17 (CE), R4/R5/R6 (charger LED anodes), R9/R11/R13 (pull-ups), C6, C7, C10, C15 | 3.3 V rail, from LDO_3V3 through the ferrite bead |
| `4V2` | USB_IC-1/20 (OUT), LDO_3V3-1/3 (VIN, EN), C1, C12, C13 | Charger power-path output (battery or USB) |
| `BAT` | LiPo-2, USB_IC-14/15/16 (VBAT, VBAT_SNS), R12, C2 | Battery positive |
| `BATT_ESP32` | ESP32_MC-17 (IO9), R12, R14 | VBAT/2 from the 100k/100k divider → ADC1_CH8. No filter cap |
| `ESP_D+` / `ESP_D-` | R16 / R15 (22 Ω, to ESP32_MC-14 IO20 / -13 IO19), ESD-4 / ESD-6, test points | Native USB, ESP side |
| `GND` | ESP32_MC-1/40/41, SD-6, FPC-2/8/9/10/11/12, LiPo-1, USB_IC-3 (SEL), -9 (TE), -10/11/21, LDO_3V3-2, LDO_1V8-2, R1, R2, R3, R7, R8, R14, D4–D6 cathodes, buttons, USBC shield, … | Ground |
| `MIC_CLK` | FPC-3, R10 (22 Ω, to ESP32_MC-4 IO4) | PDM clock, shared by all mics |
| `MIC_DATA0` | ESP32_MC-5 (IO5), FPC-4 | PDM data: mic0 / mic1 |
| `MIC_DATA1` | ESP32_MC-6 (IO6), FPC-5 | PDM data: mic2 / mic3 |
| `MIC_DATA2` | ESP32_MC-7 (IO7), FPC-6 | PDM data: mic4 / mic5 |
| `MIC_DATA3` | ESP32_MC-12 (IO8), FPC-7 | PDM data: mic6 / mic7 |
| `NetBOOT_2` | ESP32_MC-27 (IO0), BOOT-2, C17 | BOOT button (R11 10k pull-up via `NetBOOT_1`) |
| `NetC3_2` | ESP32_MC-3 (EN), RES-2, C3 | Reset (R9 10k pull-up via `NetR9_1`) |
| `NetC4_1` | LDO_3V3-5 (OUT), FB-1, C4, C14 | 3.3 V before the ferrite bead |
| `NetD1_1` / `NetD2_1` / `NetD3_1` | USB_IC-6 (PG) / -7 (STAT2) / -8 (STAT1) | Charger LEDs D1 green / D2 orange / D3 blue, anodes to 3V3 via R4/R5/R6 470 Ω |
| `NetESP32_MC_28` | ESP32_MC-28 (IO35), REC-2 | REC button as designed (R13 10k pull-up). **Cut on boards 1 and 2; REC is bodged to IO21** (ESP32_MC-23) |
| `NetESP32_MC_33/34/35` | ESP32_MC-33/34/35 (IO40/41/42), R17/R18/R19 470 Ω | Status LEDs D4 green (SD mounted) / D5 red (level meter) / D6 red (REC) |
| `NetR1_1` / `NetR2_1` / `NetR3_1` | USB_IC-13 (PROG1) / -12 (PROG3) / -5 (THERM) | Charger settings: R1 / R2 / R3 to GND |
| `NetR7_1` / `NetR8_1` | USBC-A5 (CC1) / USBC-B5 (CC2) | 5.1k pull-downs (USB-C sink) |
| `SD_CLK` | ESP32_MC-20 (IO12), SD-4 | SD SPI clock |
| `SD_CS` | ESP32_MC-22 (IO14), SD-2 | SD chip select |
| `SD_MISO` | ESP32_MC-19 (IO11), SD-5 | SD data out → ESP |
| `SD_MOSI` | ESP32_MC-21 (IO13), SD-3 | ESP → SD data in |
| `USB_D+` / `USB_D-` | USBC-A6/B6 / USBC-A7/B7, ESD-3 / ESD-1 | USB data, connector side |
| `VBUS` | USBC-A4/B9/B4/A9, USB_IC-18/19 (IN), USB_IC-2 (VPCC), ESD-5, C5 | USB 5 V in |

## Firmware pin map (quick copy)

```cpp
// MMSA V2 boards 1 and 2 (with the IO21 REC bodge): from reference/COMPONENT_INDEX.md
#define MIC_CLK_PIN     4
#define MIC_DATA0_PIN   5    // mic0/mic1
#define MIC_DATA1_PIN   6    // mic2/mic3
#define MIC_DATA2_PIN   7    // mic4/mic5
#define MIC_DATA3_PIN   8    // mic6/mic7
#define BATT_ADC_PIN    9    // VBAT/2, ADC1_CH8
#define SD_MISO_PIN    11
#define SD_SCK_PIN     12
#define SD_MOSI_PIN    13
#define SD_CS_PIN      14
#define LED_SD_PIN     40    // D4 green
#define LED_LEVEL_PIN  41    // D5 red, PWM
#define LED_REC_PIN    42    // D6 red
#define REC_BTN_PIN    21    // active low, INPUT_PULLUP; PSRAM=opi OK
                             // unmodified boards: 35, and PSRAM=disabled (shared with octal PSRAM)
// IO35-37: used by the octal PSRAM
```
