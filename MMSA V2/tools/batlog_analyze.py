"""Analyse /BATLOG.CSV written by the battery logger in MMSA_V2_Recorder8 / MMSA_V2_Recorder_BLE.

The file holds one section per power-up ("# boot, reset=..., vbat_mV=...") followed by lines
uptime_s,vbat_avg_mV,vbat_min_mV,vbat_max_mV,recording[,ble] (one every 30 s), and possibly a "# LOW BATTERY" line.
The ble column (Recorder_BLE only) is the Bluetooth state when the line was written: 0 off, 1 advertising,
2 connected. Older logs without it read as Bluetooth off.

For each boot it prints how long the board ran, VBAT at start/end, a coarse timeline, and an estimate of the
average current drawn from the battery:  I ~= capacity x (SoC_start - SoC_end) / hours.
SoC comes from a typical LiPo voltage curve. The voltages are measured under load (they sag a little), and the
ADC hasn't been checked against a meter, so treat the current as an estimate (roughly +/-20%).
If USB was still plugged in at the start of a boot, VBAT is the charger's voltage, not the battery's: use
--start-min to begin the estimate after you unplugged.

Usage:
    python batlog_analyze.py BATLOG.CSV [--mah 150] [--start-min 0]
"""
import argparse

# Typical single-cell LiPo state of charge vs voltage (light load).
SOC_CURVE = [(4200, 100), (4150, 95), (4110, 90), (4080, 85), (4020, 80), (3980, 75), (3950, 70), (3910, 65),
             (3870, 60), (3850, 55), (3840, 50), (3820, 45), (3800, 40), (3790, 35), (3770, 30), (3750, 25),
             (3730, 20), (3710, 15), (3690, 11), (3610, 7), (3500, 4), (3400, 2), (3300, 0)]


def soc(mv):
    if mv >= SOC_CURVE[0][0]:
        return 100.0
    for (v1, s1), (v2, s2) in zip(SOC_CURVE, SOC_CURVE[1:]):
        if v2 <= mv <= v1:
            return s2 + (s1 - s2) * (mv - v2) / (v1 - v2)
    return 0.0


def load(path):
    boots, cur = [], None
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# boot"):
            cur = {"header": line, "rows": [], "low": False}
            boots.append(cur)
        elif line.startswith("# LOW"):
            if cur:
                cur["low"] = True
        elif line[0].isdigit() and cur is not None:
            p = line.split(",")
            if len(p) >= 5:
                ble = int(p[5]) if len(p) >= 6 else 0
                cur["rows"].append((int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), ble))
    return boots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--mah", type=float, default=150.0)
    ap.add_argument("--start-min", type=float, default=0.0, help="ignore the first N minutes of each boot")
    ap.add_argument("--offset-mv", type=int, default=0,
                    help="add to every reading to correct the ADC (2026-10-21: meter 4.15 V vs ADC 4.06 V on USB -> ~+90)")
    a = ap.parse_args()
    boots = load(a.path)
    print(f"{a.path}: {len(boots)} boot(s)\n")
    for i, b in enumerate(boots, 1):
        o = a.offset_mv
        rows = [(r[0], r[1] + o, r[2] + o, r[3] + o, r[4], r[5]) for r in b["rows"] if r[0] >= a.start_min * 60]
        print(f"=== Boot {i}: {b['header'][2:]}")
        if len(rows) < 2:
            print("    (too short to analyse)\n")
            continue
        t0, t1 = rows[0][0], rows[-1][0]
        v0, v1 = rows[0][1], rows[-1][1]
        hours = (t1 - t0) / 3600
        print(f"    ran {hours * 60:.0f} min ({hours:.2f} h) after the start point; VBAT {v0} -> {v1} mV; "
              f"lowest min {min(r[2] for r in rows)} mV; recording in {sum(r[4] for r in rows)} of {len(rows)} lines, "
              f"Bluetooth on in {sum(1 for r in rows if r[5])}")
        print(f"    ended with: {'LOW BATTERY cutoff (logger stopped itself)' if b['low'] else 'log just stops (power lost or reset)'}")
        step = max(1, len(rows) // 12)
        print("    timeline (min: avg mV [min-max]):")
        for r in rows[::step] + ([rows[-1]] if (len(rows) - 1) % step else []):
            print(f"      {r[0] / 60:6.1f}: {r[1]} [{r[2]}-{r[3]}]{'  REC' if r[4] else ''}"
                  f"{['', '  BLE adv', '  BLE conn'][r[5]] if 0 <= r[5] <= 2 else ''}")
        used = soc(v0) - soc(v1)
        if hours < 0.25 or used < 5:
            print("    too short / too little discharge for a current estimate (USB connected, or a quick reset?)")
        elif used > 0:
            ma = a.mah * used / 100 / hours
            print(f"    estimated SoC {soc(v0):.0f}% -> {soc(v1):.0f}% = {used:.0f}% of {a.mah:.0f} mAh in {hours:.2f} h"
                  f"  ->  average current ~{ma:.0f} mA")
            print(f"    -> a full {a.mah:.0f} mAh charge would last ~{a.mah / ma:.1f} h at this rate")
        else:
            print("    no net discharge in this window (USB/charger connected?)")
        print()


if __name__ == "__main__":
    main()
