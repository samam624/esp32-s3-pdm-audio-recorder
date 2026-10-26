# MMSA V2 — Mic flex: stereo mic module

Transcribed from the user's modular schematic, shared 2026-10-20. The screenshot was only shared in chat; export the sheet to `schematics/` when possible. Other saved screenshots: `schematics/FPC_connector_main_board.png` (main-board FPC connector) and `schematics/ESP32_SD_section.png`.

## Module `LR_n` (one per data line, 4 on the flex = 8 mics)

Sheet entries to the flex top level `Flex_TL`: `1V8`, `GND`, `CLK` (in), `DO` (out).

| Refdes (module 1) | Part | Connections |
|---|---|---|
| MIC_L_LR_1 | IMP34DT05TR | 1 VDD → 1V8, 2 LR → GND (**left**: data valid while CLK low), 3 CLK → CLK, 4 DOUT → DO, 5 GND → GND |
| MIC_R_LR_1 | IMP34DT05TR | 1 VDD → 1V8, 2 LR → 1V8 (**right**: data valid while CLK high), 3 CLK → CLK, 4 DOUT → DO, 5 GND → GND |
| C1_LR_1 / C2_LR_1 | 100 nF / 10 µF 0805 | MIC_L decoupling, 1V8 to GND |
| C3_LR_1 / C4_LR_1 | 10 µF / 100 nF 0805 | MIC_R decoupling, 1V8 to GND |

- Both DOUTs share the `DO` net. That's normal for stereo PDM, because each mic is high-impedance during the other's clock phase.
- **MIC_L pin 4 carries a red X.** In Altium that's usually a *No-ERC* directive (here, hiding the "multiple outputs on one net" warning), not a break. Confirm on the physical flex: MIC_L DOUT pad to MIC_R DOUT pad should be about 0 Ω.
- **Supply naming (resolved 2026-10-25):** the flex calls the mic supply `1V8`, and the design feeds it from a 1.8 V LDO (LDO_1V8, TPS7A2018) on FPC pin 1. On the built boards that LDO was **removed and the `1V8` net shorted to 3V3** (user: to drive the mics harder, a capacitance issue), which is why 3V3 was measured at every flex pad (2026-10-20). 3.3 V suits this setup: the mic is rated 1.6–3.6 V, and at 1.8 V the ESP32's 3.3 V clock would exceed the mic's CLK absolute maximum (Vdd + 0.3 V = 2.1 V).

## IMP34DT05 key facts (datasheet `datasheets/IMP34DT05.pdf`, ST DS12725 Rev 2, Sep 2018)

| Item | Value | Source |
|---|---|---|
| Pins | 1 Vdd, 2 LR, 3 CLK, 4 DOUT, 5 GND (ground ring) | Table 1 |
| Supply | 1.6 / 1.8 / 3.6 V (min/typ/max) | Table 2 |
| Clock | 1.2 – 3.25 MHz normal mode; < 0.23 MHz = power-down | Table 2/3 |
| Logic levels | VIL ≤ 0.35·Vdd, VIH ≥ 0.65·Vdd | Table 2 |
| Abs max, control pins | −0.3 to Vdd + 0.3 V | Table 5 |
| LR = GND | DOUT valid while CLK **low**, Hi-Z while CLK high | Table 6 |
| LR = Vdd | DOUT valid while CLK **high**, Hi-Z while CLK low | Table 6 |
| LR internal pull-down | 200 kΩ (floating LR = left) | Table 6 note |
| Sensitivity / SNR / AOP | −26 dBFS typ / 64 dB(A) / 122.5 dBSPL | Table 2 |
| Current | 650 µA normal | Table 2 |
| Handling | MSL 3, **max 3 reflow cycles**, no vacuum > 7 psi over the port | §4 |
| Decoupling (ST rec.) | 100 nF + 1 µF ceramic close to pin 1 (board uses 100 nF + 10 µF) | §3 |

Firmware clock: `I2S_PDM_RX_CLK_DEFAULT_CONFIG(48000)` → 48 kHz × 64 = **3.072 MHz**, inside the 3.25 MHz max but close to it. Use 44.1 kHz (2.82 MHz) or lower if any mic misbehaves.

## Bring-up findings (module 1, data line IO5)

2026-10-20: the L and R slots are bit-identical (99.9–100% of raw PDM words), so only one mic is actually driving `DO`. The LR straps are correct in the schematic. Suspects, in order:
1. MIC_L (or MIC_R) not soldered on DOUT, CLK, VDD or the ground ring
2. A mic damaged by heat (max 3 reflows)
3. The DOUT connection at the red X, if it really is open in the layout

How to find which mic works: cover one mic's port (a finger or tape on the port side) and talk. The level drops a lot only when you cover the working mic.

2026-10-20 press test (`bringup/MMSA_V2_PressTest`): pressing one mic switched line IO5 from one stream (100% identical) to two distinct streams (~19% identical), and back on release. **RETRACTED (see below):** this was read as an intermittent joint on MIC 0, but a light finger touch anywhere on the DO trace between MIC 1 and the FPC does the same thing. The "second stream" was the undriven, floating left half-cycle being disturbed, not MIC 0.

**Current status (2026-10-20):** MIC 0 (left, LR=GND) is not driving `DO` at all. MIC 1 (right) drives its half-cycle. During the left half-cycle the line floats and holds MIC 1's last bit, so both slots look identical. A light touch on the DO trace, or a half-seated FPC, disturbs the floating line and fakes a "second stream" with density ~0.43. `MMSA_V2_PressTest` now also checks bit-toggle rate, so a floating line isn't counted as a mic. Next: check MIC 0's VDD and CLK at the mic, then replace MIC 0.

**Correction (2026-10-20, from the user's listening test on `MMSA_0001.wav`):** the mic that's missing is **MIC 1 (right, LR → 1V8)**. MIC 0 works and is duplicated onto both WAV channels. My earlier inference that MIC 0 was the dead one came from which edge the finger-touch artifact showed up on, and it was wrong. (The ESP32-S3 slot/channel order versus the LR pin is also unverified, which makes edge-based attribution unreliable.) MIC 0 got reworked by mistake and is at its 3-reflow limit. Next: MIC 1's LR → 1V8 strap, VDD at C3/C4, and its DOUT/CLK joints.

**Resolved (2026-10-20):** MIC 1 had no solder on any inner signal pad. After rework, both module-1 mics work (user listening test).

## Mic numbering (user scheme, 2026-10-20)

**mic0 – mic7, where mic N = 8-slot channel index N = WAV track N+1.** mic0/1 are on IO5 (module 1), mic2/3 on IO6, mic4/5 on IO7, mic6/7 on IO8. Even = left (LR=GND), odd = right (LR=1V8). The order within each pair is supported by data: the tombstoned mic3 and mic5 were exactly the abnormal channels at index 3 and 5.

## Per-mic status (updated 2026-10-21)

| Mic | Line | Status |
|---|---|---|
| mic0 | IO5 | OK |
| mic1 | IO5 | OK (reworked: no solder on inner pads originally) |
| mic2 | IO6 | OK |
| mic3 | IO6 | OK (replaced; two rework bridges CLK→1V8, then CLK→GND, both cleared) |
| **mic4** | IO7 | **Not fitted. Two separate fitted parts produced the same broadband hiss; inspect the footprint/rail/interface before fitting another.** |
| mic5 | IO7 | OK (clean by listening; was tombstoned and reworked) |
| mic6, mic7 | IO8 | Not fitted. They are muted in `MMSA_V2_Recorder8` via `MIC_FITTED`. |

An empty half-slot on a populated PDM line is high-impedance by design. It can hold the partner mic's last bit or
decode as noise depending on leakage, capacitance and receiver threshold. Therefore mic4's noisy empty slot does
**not** by itself prove an IO7 handover fault, and an entirely empty IO8 line is not an equivalent control. The
useful evidence is that two fitted mic4 parts had nearly identical added hiss while mic5 remained clean.

## Measured mic pitch (acoustic, 2026-10-24)

`tools/spatial_track.py` on `data/MMSA8_0084.wav` (a sound source moved along the flex from the mic0 end to the mic7 end) fitted the mic spacing from the arrival-time differences: **39.5 mm pitch, so mic0 to mic7 spans ~276 mm** (delay fit residual 0.09 samples median; pitches from 38 to 42 mm fit almost as well). This assumes the mics sit in a straight line, evenly spaced. It fits the user's "evenly spaced out to 300 mm" if mic0 sits ~20 mm from the connector.
