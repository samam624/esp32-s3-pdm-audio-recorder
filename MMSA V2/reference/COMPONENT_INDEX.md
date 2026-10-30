# MMSA V2 PCB — Component Index

**Source (2026-10-25):** the Altium netlist export `netlist/MMSA_V2_PCB_altium.net` (schematic and PCB dated 2026-09-04), the two BOM exports `netlist/MMSA_V2_BOM_altium.csv` and `netlist/MMSA_V2_BOM_JLCPCB.csv`, the user's charger schematic screenshot (2026-10-25), and the rework the user listed below. Datasheets are in `datasheets/`, each with an `_extracted.txt` text copy for searching.

`netlist/MMSA_V2_handbuilt.NET` is the older hand-built guess, kept for history. Its refdes `ESP`, `CHG` and `RDIV_*` were placeholders; the real ones are `ESP32_MC`, `USB_IC` and `R12`/`R14`.

## Rework on the built boards (boards 1 and 2, user 2026-10-25)

The design files don't show these changes:

- **REC button moved from IO35 to IO21** (bodge wire), so IO35 is free for the octal PSRAM and the firmware can use `PSRAM=opi`.
- **LDO_1V8 (TPS7A2018) removed, and the `1V8` net shorted to `3V3`**, so the mics run at 3.3 V. User's reason: to drive the mics harder (a capacitance issue). This is why 3V3 was measured on the flex's "1V8" pads.
- **SD card on a breakout board** that has its own series resistors and decoupling caps, plugged into the 6-pin `SD` header.
- **Charger resistors changed for the large cell.** Board 2 (1200 mAh): R1 on PROG1 = **2k**, R2 on PROG3 = **100k** (was 10k; changed and verified 2026-10-26), R3 on THERM = **10k**. PROG2 goes straight to 3V3 (no resistor).

## Parts

| Refdes | Part | Role | Package | Datasheet |
|---|---|---|---|---|
| ESP32_MC | ESP32-S3-WROOM-1-N8R8 (Espressif) | MCU, Wi-Fi/BLE, native USB | 41-pin module | `ESP32-S3-WROOM-1.pdf` (module), `ESP32-S3_chip_datasheet.pdf` (chip: ADC, brownout, electrical) |
| USB_IC | MCP73871T-2CCI/ML (Microchip) | Li-ion charger with power path | QFN-20 4x4 | `MCP73871.pdf` (DS22090B) |
| LDO_3V3 | AP2112K-3.3TRG1 (Diodes Inc.) | 3.3 V, 600 mA LDO, fed from the charger's OUT (`4V2` net) | SOT-25 | `Diodes_AP2112.pdf` |
| FB | MPZ1608D600BTD25 (TDK) | Ferrite bead, LDO_3V3 output → `3V3` rail | 0603 | `TDK_MPZ1608D600BTD25.pdf` |
| LDO_1V8 | TPS7A2018PDBVR (TI) | 1.8 V mic supply. **Removed; 1V8 shorted to 3V3** | SOT-23-5 | `TI_TPS7A20.pdf` |
| ESD | USBLC6-2P6 (ST) | ESD protection on USB D+/D− and VBUS | SOT-666 | `ST_USBLC6-2.pdf` |
| USBC | 10155435-00011LF (Amphenol) | USB-C receptacle | SMD | **Not downloaded** (amphenol-cs.com blocks scripted downloads) |
| R7, R8 | 5.1k | CC1 / CC2 pull-downs (USB-C sink, so a C-to-C cable gives 5 V) | 0603 | `UniOhm_0603WAF.pdf` |
| R15, R16 | 22 Ω | Series resistors on USB D− (IO19) / D+ (IO20) | 0603 | `Yageo_RC0603FR-07.pdf` |
| D+, D− | Test points | USB data, ESP side | — | — |
| LiPo | S2B-PH-K-S(LF)(SN) (JST PH) | Battery connector: pin 1 GND, pin 2 `BAT` | 2 mm, right angle | `JST_PH.pdf` |
| R12 / R14 | 100k / 100k, 1% | Battery divider: R12 `BAT` → `BATT_ESP32`, R14 `BATT_ESP32` → GND | 0603 | `Resistor_0603_100k_1pct_C2889376.pdf` (JLC BOM part; the Altium BOM names TE CRGP0603F100K) |
| R1 / R2 / R3 | 2k / 10k / 10k in the design; board 2 has R2 = 100k (see rework) | Charger PROG1 / PROG3 / THERM | 0603 | — |
| D1 / D2 / D3 | LTST-C190KGKT green / LTST-C190KFKT orange / LTST-C191TBKT blue (Lite-On) | Charger PG / STAT2 / STAT1 LEDs | 0603 | `LiteOn_*.pdf` |
| R4 / R5 / R6 | 470 Ω | Charger LED resistors, anodes to 3V3 | 0603 | `Yageo_RC0603FR-07.pdf` |
| D4 / D5 / D6 | LTST-C190KGKT green / LTST-C190KRKT red / LTST-C190KRKT red | Status LEDs on IO40 / IO41 / IO42 | 0603 | `LiteOn_*.pdf` |
| R17 / R18 / R19 | 470 Ω | Status LED series resistors | 0603 | `Yageo_RC0603FR-07.pdf` |
| REC, RES, BOOT | B3F-1000 (Omron) | Buttons: record, reset (EN), boot (IO0) | THT 4-pin | `Omron_B3F.pdf` |
| R13 / R9 / R11 | 10k | Pull-ups to 3V3 for REC / EN / IO0 | 0603 | `UniOhm_0603WAF.pdf` |
| C3 / C17 | 0.1 µF | EN and IO0 to GND (reset delay, debounce) | 0603 | `Yageo_CC0603KRX7R9BB104.pdf` |
| R10 | 22 Ω | Series resistor on MIC_CLK (IO4 → FPC pin 3) | 0603 | `Yageo_RC0603FR-07.pdf` |
| SD | MTSW-106-09-T-S-540 (Samtec) | 6-pin header for the microSD breakout | 2.54 mm THT | `Samtec_MTSW.pdf` |
| FPC | 687110183622 (Würth), fitted in place of the designed Molex 52745-1097 (a matching part that was in stock; the netlist footprint keeps the Molex name) | 10-pin connector to the mic flex | 0.5 mm ZIF, top contact, SMT | **Not downloaded** (we-online.com blocks scripted downloads) |
| (flex) | IMP34DT05TR (ST) ×8 | PDM mics, 4 stereo pairs | 3x4 mm LGA, bottom port | `IMP34DT05.pdf`. Flex wiring: `MIC_FLEX_MODULE.md` |
| C1, C2 | 4.7 µF | Charger OUT (`4V2`) and `BAT` | 0603 | `Samsung_CL10A475KA8NQNC.pdf` |
| C5 | 10 µF | VBUS | 0603 | — (LCSC only has Samsung's general catalog) |
| C12 / C13 | 0.1 µF / 10 µF | `4V2` (LDO_3V3 input) | 0603 | `Yageo_CC0603KRX7R9BB104.pdf` / — |
| C14 / C4 | 0.1 µF / 10 µF | LDO_3V3 output, before the bead | 0603 | as above |
| C6, C15 / C7, C10 | 0.1 µF / 10 µF | `3V3` rail | 0603 | as above |
| C16 / C11 | 0.1 µF / 10 µF | `1V8` (now 3V3) at the FPC | 0603 | as above |

N8R8 was confirmed on the real board with esptool (2026-10-20): ESP32-S3 rev v0.2, 8 MB embedded PSRAM, 8 MB flash. The PSRAM only works with `PSRAM=opi` (see `../bringup/README.md`).

### Where the two BOMs disagree

The Altium BOM and the JLCPCB BOM list the same values but sometimes different parts:
- **Charger:** the fitted part is **MCP73871-2CC (4.20 V)**, confirmed by the user. The netlist, the JLCPCB BOM and the schematic agree. The Altium BOM's -4CC entry is out of date.
- **Charger LEDs:** the JLCPCB BOM lists D1/D3 green and D2 red. The Altium BOM lists D1 green, D2 orange, D3 blue, and the user saw blue and orange on the board (2026-10-20), so the Altium colors are what's fitted.
- **R1:** 2k in both BOMs. Board 1 was found with 15k (`18C`); board 2 now has 2k.
- **Passive makers:** the Altium BOM names Yageo, Kemet, TE and Vishay parts; the JLCPCB BOM names Yageo, Samsung and UniOhm. The datasheets here are for the JLCPCB parts. Values are the same, so this only matters for things like capacitor DC-bias derating.

## Power path (from the netlist)

```
USB-C VBUS ── C5, ESD ──> USB_IC IN (18, 19), VPCC (2)
                              │
LiPo + ── BAT (C2, R12) ──> USB_IC VBAT (14, 15), VBAT_SNS (16)
                              │
                         USB_IC OUT (1, 20) = net 4V2 (C1, C12, C13)
                              │
                         LDO_3V3 AP2112K (VIN 1, EN 3) ── C4, C14 ── FB ──> 3V3 (C6, C7, C10, C15)
                                                                             │
   3V3 feeds: ESP32 module, SD header pin 1, mic flex (via the 1V8 short), charger PROG2 and CE,
              pull-ups R9/R11/R13, charger LED anodes (R4–R6)
```

- **AP2112K-3.3 dropout:** typically ~125 mV at 300 mA (200 mV max) and 250 mV at 600 mA (400 mV max). Scaled to the board's ~120–140 mA it's roughly 60 mV, so 3V3 holds until the battery is about 3.35 V and then follows it down.
- **Board current from the battery** (`../data/power/2026-10-24/`): ~75 mA idle, ~118 mA recording, ~141 mA recording with Bluetooth connected.
- **Low-battery limits:** the cell's own protection cuts the supply at almost exactly 3.0 V (user's tests). The ESP32 is rated to run below 3 V. The firmware's 3.40 V cutoff is kept on purpose: it leaves margin above 3.0 V, and since the ADC reads ~90 mV low, it is ~3.49 V on a meter.

## ESP32_MC — ESP32-S3-WROOM-1 (module pin → GPIO, from the netlist and Table 3-1)

| Module pin | GPIO | Net | Function on this board | Notes |
|---|---|---|---|---|
| 1, 40, 41 (EPAD) | — | GND | Ground | |
| 2 | — | 3V3 | Module supply | |
| 3 | EN | NetC3_2 | Reset | RES button to GND, R9 10k pull-up, C3 0.1 µF |
| 4 | IO4 | (R10 22 Ω) → MIC_CLK | PDM clock to all mics | FPC pin 3 |
| 5 | IO5 | MIC_DATA0 | PDM data, mic0/mic1 | FPC pin 4 |
| 6 | IO6 | MIC_DATA1 | PDM data, mic2/mic3 | FPC pin 5 |
| 7 | IO7 | MIC_DATA2 | PDM data, mic4/mic5 | FPC pin 6 |
| 12 | IO8 | MIC_DATA3 | PDM data, mic6/mic7 | FPC pin 7 |
| 13 / 14 | IO19 / IO20 | (R15 / R16 22 Ω) → ESP_D− / ESP_D+ | Native USB | Through the USBLC6 to the USB-C connector |
| 17 | IO9 | BATT_ESP32 | Battery sense, VBAT/2 | **ADC1_CH8**, so it still reads while Wi-Fi/BLE is on |
| 19 | IO11 | SD_MISO | SD SPI MISO | |
| 20 | IO12 | SD_CLK | SD SPI SCK | |
| 21 | IO13 | SD_MOSI | SD SPI MOSI | |
| 22 | IO14 | SD_CS | SD SPI CS | |
| 23 | IO21 | — (bodge wire on boards 1 and 2) | REC button, active low, `INPUT_PULLUP` | **Moved here 2026-10-24** (was IO35). Careful: pad 22 next to it is IO14 = SD_CS |
| 27 | IO0 | NetBOOT_2 | BOOT button | R11 10k pull-up, C17 0.1 µF. Strapping pin: low at reset = download mode |
| 28 | IO35 | NetESP32_MC_28 (trace cut on boards 1 and 2) | REC button as designed, R13 10k pull-up | Octal PSRAM line. See gotcha |
| 33 | IO40 | (R17 470 Ω) → D4 green | `LED_SD`: on while the SD card is mounted | |
| 34 | IO41 | (R18 470 Ω) → D5 red | `LED_LEVEL`: loudness meter, PWM | |
| 35 | IO42 | (R19 470 Ω) → D6 red | `LED_REC`: blinks while recording | |

Not connected in the netlist: pins 8–11 (IO15–18), 15 (IO3), 16 (IO46), 18 (IO10), 24–26 (IO47, IO48, IO45), 29–32 (IO36–39) and 36–39 (RXD0, TXD0, IO2, IO1). IO47/IO48 are usable 3.3 V GPIOs on N8R8. IO45 and IO46 are strapping pins, and IO36–37 belong to the PSRAM.

### Gotcha: IO35–37 belong to the PSRAM

On R8 modules, IO35, IO36 and IO37 are wired to the octal PSRAM inside the module and "are not available for other uses" (datasheet Table 3-1, note b). The design put the REC button on IO35 (same as V1). That only works with PSRAM disabled, because a press pulls a PSRAM data line low and corrupts memory (verified 2026-10-20 with `bringup/MMSA_V2_ButtonTest`). Boards 1 and 2 have the trace cut and the button moved to IO21, so PSRAM is on. **Next revision: route REC to IO21 (or IO47/48).**

### Gotcha: SD MOSI and MISO are routed through the GPIO matrix

IO11–14 are the FSPI IOMUX pins, but in the opposite order: IOMUX wants FSPID (MOSI) on IO11 and FSPIQ (MISO) on IO13, and this board swaps them. That's fine, because `SPI.begin(12, 11, 13, 14)` routes through the GPIO matrix. It only caps the top SPI clock, which SD-card speeds don't reach. The pins match V1 exactly.

### Gotcha: battery divider

- Source impedance is 50 kΩ (100k ∥ 100k), and **the netlist has no filter cap on BATT_ESP32**. That's part of why single ADC readings scatter about ±70 mV; the firmware averages over ~16 s. A 100 nF cap from BATT_ESP32 to GND would quiet it on the next revision.
- Full charge is 4.20 V (-2CC), so the pin sees 2.10 V. Use 12 dB attenuation (`analogSetPinAttenuation(9, ADC_11db)`).
- The divider draws VBAT/200k, about 21 µA at 4.2 V, all the time.
- `VBAT = 2 × reading`, using `analogReadMilliVolts()`. One meter check (2026-10-21) found it reads ~90 mV low.

### Gotcha: PDM with 4 data lines

The ESP32-S3 supports up to 4 PDM RX data lines (8 mics, stereo pairs sharing the clock) only on **I2S0**. All 4 lines share the IO4 clock. Each line carries an L/R pair set by each mic's SELECT (LR) pin; see `MIC_FLEX_MODULE.md`.

## SD — MTSW-106 (6-pin header to the microSD breakout)

| Pin | Net | Function |
|---|---|---|
| 1 | 3V3 | Card supply |
| 2 | SD_CS | Chip select ← IO14 |
| 3 | SD_MOSI | Data to card ← IO13 |
| 4 | SD_CLK | SPI clock ← IO12 |
| 5 | SD_MISO | Data from card → IO11 |
| 6 | GND | Ground |

The breakout carries its own series resistors and decoupling caps (rework). There's no card-detect pin, same as V1.

## FPC — 10-pin mic flex connector

| Pin | Net | Function |
|---|---|---|
| 1 | 1V8 (shorted to 3V3 on the built boards) | Mic supply. C11 10 µF + C16 0.1 µF here |
| 2 | GND | Ground |
| 3 | MIC_CLK | PDM clock (IO4 through R10 22 Ω) |
| 4 | MIC_DATA0 | IO5, mic0/mic1 |
| 5 | MIC_DATA1 | IO6, mic2/mic3 |
| 6 | MIC_DATA2 | IO7, mic4/mic5 |
| 7 | MIC_DATA3 | IO8, mic6/mic7 |
| 8, 9, 10 | GND | Ground |
| 11, 12 | GND | Mounting tabs |

The connector is ZIF, top contact: the flex's exposed contacts face up, away from the PCB. With the flex reversed, pin 1's supply would land on a ground pin.

## USB_IC — MCP73871T-2CCI/ML (checked against DS22090B and the schematic)

`-2CC` option (datasheet p.35): **VREG = 4.20 V**, 6 h safety timer, LBO (low-battery warning) at 3.1 V.

| Pin | Name | Function | Net (this board) |
|---|---|---|---|
| 1, 20 | OUT | System output (power path) | `4V2` → LDO_3V3 input and enable; C1 4.7 µF, C12, C13 |
| 2 | VPCC | Voltage-proportional charge control | VBUS (feature disabled) |
| 3 | SEL | Low = USB input, High = AC adapter | GND (USB mode) |
| 4 | PROG2 | USB current limit (Low 100 mA / High 500 mA) | 3V3 directly (500 mA) |
| 5 | THERM | Thermistor input | R3 10k to GND (no temperature sensing) |
| 6 | PG | Power-good, open-drain | D1 green, anode to 3V3 through R4 470 Ω |
| 7 | STAT2 | Charge status 2, open-drain | D2 orange, anode to 3V3 through R5 470 Ω |
| 8 | STAT1/LBO | Charge status 1 / low battery, open-drain | D3 blue, anode to 3V3 through R6 470 Ω |
| 9 | TE | Timer enable (active low) | GND (6 h timer on) |
| 10, 11, 21 (EP) | VSS | Ground | GND |
| 12 | PROG3 | Termination current | R2 to GND: 10k in the design (100 mA); 100k on board 2 (10 mA) |
| 13 | PROG1 | Fast-charge current | R1 to GND: 2k on board 2 (~500 mA); board 1 had 15k (~67 mA) |
| 14, 15 | VBAT | Battery | `BAT`: LiPo pin 2, C2 4.7 µF, R12 (divider top) |
| 16 | VBAT_SNS | Battery voltage sense | `BAT` |
| 17 | CE | Charge enable | 3V3 (enabled) |
| 18, 19 | IN | Input supply | VBUS (C5 10 µF, USBLC6) |

Charge settings and history:
- **Board 2, 1200 mAh cell (2026-10-25):** R1 = 2k gives I_REG = 1000 V / R_PROG1 = ~500 mA (Eq. 5-1). On USB with PROG2 High, the total input is capped at 400–500 mA, with the system load supplied first. That's about 0.4C, fine for this cell, and well inside the 6 h timer. With R2 = 10k, the charge ended at ~4.02 V on the remote (~81%). The 2026-10-26 charge log (`../data/batlog/2026-10-26_charge/`) shows why: it stopped the moment the cell reached 4.2 V, with no constant-voltage top-up, and the cell then settled to ~4.10 V. **2026-10-26: R2 changed to 100k (10 mA cutoff), verified by the user.** The charge now includes the top-up, so it takes longer, and the cell read 4.19 V when USB was unplugged. From the 2026-10-25 run-down, a full cell should give ~7.8–8.5 h of recording with Bluetooth (6.55 h last time, from the partial charge).
- **R2 on PROG3 sets the termination current** I_TERM = 1000 V / R_PROG3: 10k gives **100 mA** (75–125 mA), 100k gives 10 mA (7.5–12.5 mA). The allowed range is 5–100 kΩ (p.7). If I_TERM is at or above the charge current, the charger stops the moment the cell reaches 4.2 V and skips the constant-voltage top-up. That's what happened on board 1 (I_REG 67 mA < I_TERM 100 mA, "complete" at ~4.15 V on 2026-10-20).
- **Board 1, 150 mAh cell (2026-10-23):** R1 = 15.0 kΩ (EIA-96 marking `18C`) gave I_REG ≈ 67 mA, ~0.45C. The allowed R_PROG1 range is 1–20 kΩ (1000–50 mA, p.7).
- **R3 = 10 kΩ fixed on THERM:** stands in for a 10k NTC at 25 °C, so there is no temperature protection. THERM sources 50 µA (47–53), so it should sit at ~0.50 V. Temperature fault (all 3 LEDs) if it goes outside 0.25–1.24 V (p.6).
- **Reverse-polarity incident (2026-10-23):** a 1200 mAh cell with a reversed JST plug put VBAT at about −3.7 V (absolute max is VSS − 0.3 V, p.3). The charger showed all 3 LEDs. With the 150 mAh cell back in, the fault cleared.
- **USB only, no battery:** with only C2 and the 200k divider on `BAT`, the charger fills the cap to 4.2 V, reads "done", lets the divider bleed it below the recharge threshold, then charges again, many times a second. Orange (and green) look on while blue looks dim. This is expected.
- **Bigger cells vs the 6 h timer (TE tied to GND):** at 67 mA, 6 h is only ~400 mAh, so a 1200 mAh cell hit a timer fault (all 3 LEDs) on 2026-10-23. With R1 = 2k, 6 h covers it.
- Preconditioning: below V_PTH = 72% of VREG (69–75%, ~3.02 V) it charges at 10% of I_REG.
- PROG2 has no internal pull (leakage ≤1 µA), so an unsoldered pin 4 would float.

Status LEDs (Table 5-1). LED on = pin pulled low. **STAT1 = D3 blue, STAT2 = D2 orange, PG = D1 green** (user-confirmed 2026-10-20, matches the netlist).

| State | STAT1 (D3 blue) | STAT2 (D2 orange) | PG (D1 green) |
|---|---|---|---|
| Charging (precond / CC / CV) | ON | off | ON |
| Charge complete | off | ON | ON |
| Temperature or timer fault | ON | ON | ON |
| Input present, no battery | off | off | ON |
| On battery, VBAT < 3.1 V (LBO) | ON | off | off |
| No input / shutdown | off | off | off |

## Open items

- Charger resistors: R2 → 100k planned (see rework).
- USB-C (Amphenol 10155435-00011LF) and FPC (Würth 687110183622) drawings: download by hand from amphenol-cs.com and we-online.com if needed.
- Next revision: REC on IO21 in the design, drop or bypass LDO_1V8 in the design, add a filter cap on BATT_ESP32.
