# Mic4 fix plan (2026-10-21)

## Current state

- Working and fitted: mic0, mic1, mic2, mic3 and mic5.
- Not fitted: mic4, mic6 and mic7.
- Two different IMP34DT05 parts fitted at mic4 produced nearly the same flat broadband hiss. Mic5 on the same
  IO7 line remained clean.
- With mic4 removed, its decoded half-slot is noisy. That observation is not a fault diagnosis: the DOUT pin is
  intentionally high-impedance during the other slot, so an empty half-slot has no guaranteed logic level.
- IO8 with both mics absent settling to a constant value is not an equivalent control for IO7 with mic5 driving
  every other clock phase.

## Before fitting another mic

Disconnect USB and battery. Compare the empty mic4 footprint with mic5 and, where useful, a known-good module:

1. Mic4 pin 4 (DOUT) to mic5 pin 4: near 0 ohm.
2. Mic4 pin 3 (CLK) to mic5 pin 3: near 0 ohm.
3. Mic4 pin 1 (VDD) to mic5 pin 1: near 0 ohm.
4. Mic4 ground ring to mic5 ground ring: near 0 ohm.
5. Mic4 pin 2 (LR) to ground: near 0 ohm. Mic5 pin 2 should instead connect to VDD.
6. DOUT-to-CLK, DOUT-to-VDD and DOUT-to-ground: no low resistance. Compare the readings with IO5/IO6 because
   capacitors and protection structures can make the displayed resistance change while measuring.
7. Inspect and clean the mic4 footprint and both of its local decoupling capacitors. Check for a damaged pad,
   solder whisker, conductive flux residue or a cracked flex trace.

With power restored, measure the actual voltage from mic pin 1 to its ground ring. The project notes conflict
between 1.8 V and 3.3 V. This matters: at 1.8 V the 3.3 V clock exceeds the mic's VDD+0.3 V absolute maximum and
the mic's DOUT high is not guaranteed to meet the ESP32-S3's 3.3 V input-high threshold. At 3.3 V the IMP34DT05
itself is within its specified 1.6-3.6 V supply range. Do not bridge the supply to 3.3 V until every other load on
that rail has been checked.

## Decisive recording test

After installing mic4, build `MMSA_V2_IO7_Diagnostic/` with `PSRAM=disabled`. It records only IO7 as stereo files
named `/IO7_NNNN.wav`: left is mic4 and right is mic5.

- If mic4 hisses in both the IO7-only file and an 8-channel file, the fault is on the module/interface: footprint,
  trace, FPC contact, supply/decoupling, or logic-voltage margin.
- If mic4 is clean IO7-only but hisses in the 8-channel file, investigate the ESP32 multi-line PDM configuration.
- Do not judge mic4 while its footprint is empty; mute that channel instead.

The normal 8-channel recorder now reflects the actual population and mutes mic4, mic6 and mic7 until they are
installed and validated.
