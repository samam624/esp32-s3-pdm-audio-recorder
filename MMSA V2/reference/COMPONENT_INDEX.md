# MMSA V2 PCB — Component Index

**Status: partial, hand-built 2026-10-20.** There is no CAD netlist export yet. This was built from:
- the user's description of the board (LEDs, mic, battery divider)
- a schematic screenshot of the ESP32 SD-card section
- each part's datasheet in `datasheets/`

`netlist/MMSA_V2_handbuilt.NET` uses Altium's block format. Refdes `ESP`, `CHG` and `RDIV_*`, and the net names `MIC_*` and `LED_*`, are **placeholders** I made up. `SD`, `SD_*`, `BATT_ESP32` and `3V3` match the real schematic. When the real Altium `.NET` export exists, replace the hand-built file and regenerate both docs (see the `pcb-reference` skill).

| Refdes | Part | Role | Package | Datasheet |
|---|---|---|---|---|
| ESP (TBD) | ESP32-S3-WROOM-1-N8R8 (Espressif) | MCU, Wi-Fi/BLE, USB | 41-pin module | `ESP32-S3-WROOM-1.pdf` (v1.8) |
| CHG (TBD) | MCP73871T-2CCI/ML (Microchip; schematic 2026-10-23, earlier notes said -4CC) | Li-Ion charger with power path | QFN-20 4x4 | `MCP73871.pdf` (DS22090B, 2009) |
| SD | MTSW-106 | 6-pin header to a microSD breakout | 2.54mm header | n/a |
| RDIV_TOP / RDIV_BOT (TBD) | 100k / 100k | Battery voltage divider into IO9 | — | — |
| MIC_L/R_LR_1..4 | IMP34DT05TR (ST) | 8 PDM mics as 4 stereo modules (one per data line) on the flex PCB | 3x4 mm LGA, bottom port | `IMP34DT05.pdf` (DS12725 Rev 2). Module wiring and findings: `MIC_FLEX_MODULE.md` |
| FPC | Molex 52745-1097 | 10-pin connector to the mic flex PCB | 0.5mm ZIF, top contact, SMT | not fetched (molex.com blocked); contact style from RS listing |
| LEDs (TBD) | 3 LEDs on IO40/41/42, colors TBD | Status | — | — |

N8R8 is inferred from esptool on the real board (2026-10-20): ESP32-S3 rev v0.2, "Embedded PSRAM 8MB", flash ID 0x20/0x4017 (8MB). The PSRAM only works with `PSRAM=opi` (see `../bringup/README.md`).

## ESP — ESP32-S3-WROOM-1 (module pin → GPIO, verified against Table 3-1)

| Module pin | GPIO | Net (this board) | Function on this board | Notes |
|---|---|---|---|---|
| 1, 40, 41 (EPAD) | — | GND | Ground | |
| 2 | — | 3V3 | Module supply | |
| 4 | IO4 | MIC_CLK | PDM clock to all mics | Same as V1 |
| 5 | IO5 | MIC_DATA1 | PDM data line 1 (mic pair 1, L/R) | ADC1_CH4. Same pin as V1's single mic |
| 6 | IO6 | MIC_DATA2 | PDM data line 2 | |
| 7 | IO7 | MIC_DATA3 | PDM data line 3 | |
| 12 | IO8 | MIC_DATA4 | PDM data line 4 | Wire seen leaving pin 12 in the screenshot |
| 17 | IO9 | BATT_ESP32 | Battery sense, VBAT/2 | **ADC1_CH8**, so it still reads while Wi-Fi/BLE is on |
| 18 | IO10 | — | Unconnected in screenshot | |
| 19 | IO11 | SD_MISO | SD SPI MISO | Same as V1 |
| 20 | IO12 | SD_CLK | SD SPI SCK | Same as V1 |
| 21 | IO13 | SD_MOSI | SD SPI MOSI | Same as V1 |
| 22 | IO14 | SD_CS | SD SPI CS | Same as V1 |
| 8 | IO15 | — | Unconnected in screenshot | |
| 9 | IO16 | — | Unconnected in screenshot | |
| 33 | IO40 | LED_IO40 | Status LED, color/role TBD | V1: REC LED |
| 34 | IO41 | LED_IO41 | Status LED, color/role TBD | V1: level-meter LED |
| 35 | IO42 | LED_IO42 | Status LED, color/role TBD | V1: SD status LED |
| 13 / 14 | IO19 / IO20 | (USB D- / D+, assumed) | Native USB | Board enumerates as 303A:1001, so USB is wired here |
| 23 | IO21 | REC_BTN* (bodge wire, boards 1 and 2) | REC button, active low, `INPUT_PULLUP` | **Bodged here 2026-10-24** (was IO35). Plain GPIO, no boot role. Verified with PSRAM on. Careful: pad 22 next to it is IO14 = SD_CS |
| 24 / 25 | IO47 / IO48 | — (not in the schematic screenshot) | — | Usable 3.3 V GPIOs on N8R8 (1.8 V only on R16V modules). Second choice for the bodge |
| 26 | IO45 | — (not in the schematic screenshot) | — | Strapping pin: selects the flash/PSRAM supply voltage (VDD_SPI) at reset. Don't wire a switch here |
| 27 | IO0 | — (not in the schematic screenshot) | — | Strapping pin: low at reset = download mode. Don't wire the REC button here |
| 28 | IO35 | — (trace cut on boards 1 and 2) | Octal PSRAM line | **REC button as designed; cut and moved to IO21 on boards 1 and 2 (2026-10-24).** Unmodified boards: REC here, PSRAM must stay off. See gotcha |
| 29–30 | IO36–37 | — | Used by the octal PSRAM | |

All other module pins are not documented yet.

### Gotcha: IO35–37 belong to the PSRAM

On R8 modules, IO35, IO36 and IO37 are wired to the octal PSRAM inside the module and "are not available for other uses" (datasheet Table 3-1, note b). **The V2 REC button is on IO35 anyway** (same as V1, active low, `INPUT_PULLUP`).

It works as long as PSRAM is disabled (`PSRAM=disabled`), the same way V1 ran. Verified 2026-10-20 with `bringup/MMSA_V2_ButtonTest`: 6 clean presses, idles high. **Never enable PSRAM in firmware that reads this button**, because a press pulls a PSRAM data line low and corrupts memory. To get the PSRAM back: bodge the button to a free pin (IO10/15/16) on this board, and move it in the next revision.

### Gotcha: SD MOSI and MISO are routed through the GPIO matrix

IO11–14 are the FSPI IOMUX pins, but in the opposite order: IOMUX wants FSPID (MOSI) on IO11 and FSPIQ (MISO) on IO13, and this board swaps them. That's fine, because `SPI.begin(12, 11, 13, 14)` routes through the GPIO matrix. It only caps the top SPI clock, which SD-card speeds don't reach. The pins match V1 exactly, so V1's SD code carries over unchanged.

### Gotcha: battery divider

- Source impedance is 50 kΩ (100k ∥ 100k). Average a few samples, and check for a filter cap on BATT_ESP32 (not seen in the screenshot).
- Full charge is 4.20 V on the -2CC charger (per the schematic), so the pin sees 2.10 V. Use 12 dB attenuation (`analogSetPinAttenuation(9, ADC_11db)` / `ADC_ATTEN_DB_12`).
- The divider draws VBAT/200k, about 21 µA at 4.2 V, all the time.
- `VBAT = 2 × reading`. Use `analogReadMilliVolts()` for the calibrated value.

### Gotcha: PDM with 4 data lines

The ESP32-S3 supports up to 4 PDM RX data lines (8 mics, stereo pairs sharing the clock) only on **I2S0**. All 4 lines share the IO4 clock. Each line carries an L/R pair set by each mic's SELECT pin; check the SELECT straps per mic when the schematic is available.

## SD — MTSW-106 (6-pin microSD breakout header)

From the schematic screenshot. Check this order against the breakout module's own silkscreen before plugging one in.

| Pin | Net | Function |
|---|---|---|
| 1 | 3V3 | Card supply |
| 2 | SD_CS | Chip select ← IO14 |
| 3 | SD_MOSI | Data to card ← IO13 |
| 4 | SD_CLK | SPI clock ← IO12 |
| 5 | SD_MISO | Data from card → IO11 |
| 6 | GND | Ground |

There's no card-detect pin, same as V1.

## FPC — Molex 52745-1097 (mic flex connector)

From the schematic screenshot (2026-10-20).

| Pin | Net | Function |
|---|---|---|
| 1 | 3V3 (assumed: red-highlighted power trace, same highlight as the SD header's 3V3) | Mic supply |
| 2 | GND | Ground |
| 3–7 | MIC_CLK, MIC_DATA1–4 | Clock + 4 PDM data lines. **Which pin carries which signal is TBD** |
| 8, 9, 10 | GND | Ground (grounds between/around the signals) |
| 11, 12 | GND | Mounting tabs, tied to ground |

The connector is ZIF, top contact: the flex's exposed contacts face up, away from the PCB. 3V3 and GND reach every mic pad on the flex (user measured 2026-10-20). That also confirms the flex isn't inserted flipped: reversed, pin 1's 3V3 would land on a ground pin.

## CHG — MCP73871T-2CCI/ML (verified against DS22090B)

The user's schematic screenshot (2026-10-23) shows **MCP73871T-2CCI/ML**. Earlier notes said -4CC (4.40 V), which was wrong. `-2CC` option (datasheet p.35): **VREG = 4.20 V**, 6 h safety timer, LBO (low-battery warning) at 3.1 V. The package top marking is `2CC`, so check that the fitted chip matches.

Charge settings (fitted parts checked by the user, 2026-10-23: R1 = 15k, R2 = 10k, R3 = 10k):
- **R1 on PROG1 = 15.0 kΩ** (EIA-96 marking `18C`). Intentional: the user changed it in the BOM after drawing the schematic, which still says 2k. Fast charge I_REG = 1000 V / R_PROG1 (Eq. 5-1) = **~67 mA**, ~0.45C for the 150 mAh cell, a sensible rate. The schematic label just needs updating. 2k (~3C) would be too high for a small LiPo. Allowed R_PROG1 range is 1–20 kΩ (1000–50 mA, DS22090B p.7). In USB mode with PROG2 High, the total input is capped at 400–500 mA, with the system load supplied first.
- **R2 = 10 kΩ on PROG3 (fitted part confirmed):** the charge stops when the current falls below I_TERM = 1000 V / R_PROG3 = **100 mA** (75–125 mA). That's *above* the 67 mA charge current, so the charger stops the moment the cell reaches 4.2 V, skipping the constant-voltage top-up and leaving it ~85–90% full. That explains the 2026-10-20 "charge complete" at ~4.15 V. **Fix: R2 → 100 kΩ** (I_TERM 10 mA, 7.5–12.5 mA tested point; 100 kΩ is the top of the 5–100 kΩ range).
- **R3 = 10 kΩ fixed on THERM:** stands in for a 10k NTC at 25 °C, so there is no temperature protection. THERM sources 50 µA (47–53), so it should sit at ~0.50 V. Temperature fault (all 3 LEDs) if it goes outside 0.25–1.24 V (p.6).
- **Reverse-polarity incident (2026-10-23):** a 1200 mAh cell with a reversed JST plug was connected, putting VBAT at about −3.7 V (absolute max is VSS − 0.3 V, p.3). The charger showed all 3 LEDs. With the 150 mAh cell back in, the fault cleared. Survival not yet confirmed: check that the 150 mAh cell charges (blue bright, voltage rising), the board runs on battery alone, and the IC stays cool. A later run-down test can also reveal any extra leakage.
- **USB only, no battery:** with only the VBAT cap and the 200k battery divider on VBAT, the charger fills the cap to 4.2 V, reads "done" (current < 100 mA cutoff), lets the divider bleed it below the recharge threshold, then charges again, cycling many times a second. So orange (and green) look on while blue looks dim. This is expected, not a fault.
- **Bigger cells vs the 6 h timer (TE tied to GND):** 67 mA × 6 h ≈ 400 mAh per charge cycle. A 1200 mAh cell (tried 2026-10-23) would hit a timer fault partway through a charge from low (all 3 LEDs; it clears when the battery is removed). Re-plugging restarts the cycle. For a big cell long-term, use a lower R1 or tie TE High.
- Preconditioning: below V_PTH = 72% of VREG (69–75%, ~3.02 V) it charges at 10% of I_REG.
- Allowed R_PROG3 range is 5–100 kΩ (p.7).
- VPCC: if IN sags to the threshold set at VPCC, charge current is cut back. Tie VPCC to IN to disable it. **On this board VPCC is tied to VBUS (user, 2026-10-23), so it's disabled.**
- PROG2 has no internal pull (leakage ≤1 µA), so an unsoldered pin 4 would float.

Pin table (datasheet §3, QFN-20). Nets from the schematic screenshot (2026-10-23) where shown.

| Pin | Name | Function | Net (this board) |
|---|---|---|---|
| 1, 20 | OUT | System output (power path) | TBD |
| 2 | VPCC | Voltage-proportional charge control | VBUS (feature disabled) |
| 3 | SEL | Low = USB input, High = AC adapter | GND (USB mode) |
| 4 | PROG2 | USB current limit (Low 100 mA / High 500 mA) | 3V3 (500 mA) |
| 5 | THERM | Thermistor input | R3 10k to GND |
| 6 | PG | Power-good, open-drain, LED | TBD (LED) |
| 7 | STAT2 | Charge status 2, open-drain, LED | TBD (LED) |
| 8 | STAT1/LBO | Charge status 1 / low battery, open-drain, LED | TBD (LED) |
| 9 | TE | Timer enable (active low) | GND (6 h timer on) |
| 10, 11, EP | VSS | Ground | GND |
| 12 | PROG3 | Termination set point | R2 10k to GND (100 mA) |
| 13 | PROG1 | Fast-charge current set | R1 15k to GND (`18C`, per BOM; schematic still says 2k) → 67 mA |
| 14, 15 | VBAT | Battery | VBAT (also top of battery divider, assumed) |
| 16–19 | (IN, etc.) | See datasheet §3 | CE (pin 17) = 3V3 (enabled); others TBD |

Status LEDs (Table 5-1). LED on = pin pulled Low. On this board (user-confirmed 2026-10-20): **STAT1 = D3 blue, STAT2 = D2 orange, PG = D1 green**.

| State | STAT1 (D3 blue) | STAT2 (D2 orange) | PG (D1 green) |
|---|---|---|---|
| Charging (precond / CC / CV) | ON | off | ON |
| Charge complete | off | ON | ON |
| Temperature or timer fault | ON | ON | ON |
| Input present, no battery | off | off | ON |
| On battery, VBAT < 3.1 V (LBO) | ON | off | off |
| No input / shutdown | off | off | off |

## Open items

- Real Altium netlist export, to replace the hand-built file
- Refdes for every part
- Mic supply voltage at the mic: the flex net is named 1V8, but 3V3 was measured (see `MIC_FLEX_MODULE.md`)
- LED colors and roles on IO40/41/42, and the charger's 3 LED colors
- Charger fault: all 3 charger LEDs lit on battery alone (no USB), seen 2026-10-20. Per §3.12, PG can't be active without input power, so suspect back-feed into IN or LED anodes on an unexpected rail. Next: measure IN with battery only, and confirm the LED anode rail
- Charger input wiring (SEL / PROG / THERM) and where VBAT, OUT and 3V3 come from (regulator part?)
