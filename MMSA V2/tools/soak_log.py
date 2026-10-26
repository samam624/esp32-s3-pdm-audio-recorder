"""Overnight soak test for the MMSA V2 recorder: keeps a recording running, logs everything, and summarises it.

Usage:
    python soak_log.py COM3 [--hours 12] [--ble] [--ble-poll-min 10] [--no-restart]
    python soak_log.py --summarize ../data/soak/soak_XXXX.log

Run it with the production build (30-min files). While it runs it:
  - keeps the PC from going to sleep (the screen may still turn off)
  - logs every serial line with a timestamp to MMSA V2/data/soak/soak_<date>.log
  - starts a recording; with --ble it also switches Bluetooth on and, every --ble-poll-min minutes, connects from the
    PC, reads the status a few times and disconnects (what the phone remote does)
  - if the recording stops by itself or the board reboots, logs it as an INCIDENT and starts a new recording (unless
    the card is full, the battery is below its cutoff, or --no-restart is given)
  - at the end (--hours, a full card, or Ctrl+C) stops the recording and prints the summary
The firmware prints a HEALTH line every minute (heap, backlog, slowest SD write); the summary trends those.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import re
import sys
import time
from datetime import datetime
from pathlib import Path

BAD = re.compile(r"WARNING|failed|FAILED|Could not|NOT started|!! audio loss|AUDIO WAS LOST|[Pp]anic|Guru|"
                 r"abort\(|assert|Backtrace|SD NOT available|card pulled|REC ignored|CLIPPING")


def keep_awake():
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        print("note: couldn't ask Windows to stay awake; set the PC's sleep to Never for tonight")


async def ble_poll(b):
    from bleak import BleakClient, BleakScanner
    from mmsa_serial import BLE_NAME, BLE_STATUS, parse_status
    try:
        dev = await BleakScanner.find_device_by_name(BLE_NAME, timeout=12)
        if not dev:
            b.note("BLE poll FAILED: board not found in a 12 s scan")
            return False
        async with BleakClient(dev, timeout=20) as c:
            last = None
            for _ in range(3):
                last = parse_status(bytes(await c.read_gatt_char(BLE_STATUS)))
                await asyncio.sleep(1.5)
        b.note(f"BLE poll ok: recording={last['recording']} rec_secs={last.get('rec_secs')} "
               f"free_mb={last['free_mb']} error={last['error']}")
        return True
    except Exception as e:
        b.note(f"BLE poll FAILED: {type(e).__name__}: {e}")
        return False


def start_recording(b) -> bool:
    m = b.mark()
    b.send("r")
    if b.wait_for(r"REC start: /\S+", 5, m):
        return True
    b.note("couldn't start a recording: " + " | ".join(b.since(m)[-3:]))
    return False


def run(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mmsa_serial import Board
    keep_awake()
    out = Path(__file__).resolve().parents[1] / "data" / "soak"
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"soak_{time.strftime('%Y%m%d_%H%M')}.log"
    b = Board(a.port, str(log), echo_filter=lambda t: t.startswith(("REC ", "HEALTH", "Boot", "SD ", "  ", "!!",
                                                                      "Battery", "MODE", "Bluetooth ON", "Bluetooth OFF")))
    b.note(f"soak start: hours={a.hours} ble={a.ble} poll={a.ble_poll_min} min restart={not a.no_restart}")
    h = b.health()
    if not h:
        b.note("no HEALTH reply: flash the current firmware first")
        b.close()
        raise SystemExit(1)
    if a.ble and not h["ble"]:
        b.send("b")
        b.wait_for(r"Bluetooth ON", 5)
    if not h["rec"]:
        start_recording(b)
    end = time.time() + a.hours * 3600
    next_poll = time.time() + 60
    mark = b.mark()
    restart_at = None
    finished = None
    try:
        while time.time() < end and not finished:
            time.sleep(1)
            new = b.since(mark)
            mark += len(new)
            for i, line in enumerate(new):
                if line.startswith("Boot, reset reason"):
                    b.note(f"INCIDENT: board rebooted ({line})")
                    restart_at = time.time() + 10
                elif line.startswith("REC stop: /") and not finished:  # a card-full/battery stop is the planned end
                    context = " | ".join(new[max(0, i - 4):i])
                    b.note(f"INCIDENT: recording stopped by itself: {line}  [before: {context}]")
                    restart_at = time.time() + 5
                elif "SD card full" in line:
                    finished = "card full"
                elif "Battery below cutoff" in line or "below the" in line and "cutoff" in line:
                    finished = "battery below cutoff"
            if restart_at and time.time() >= restart_at and not finished:
                restart_at = None
                if a.no_restart:
                    finished = "recording stopped (--no-restart)"
                    break
                h = b.health()
                if h and not h["rec"]:
                    if a.ble and not h["ble"]:
                        b.send("b")
                        b.wait_for(r"Bluetooth ON", 5)
                    if not start_recording(b):
                        restart_at = time.time() + 30
            if a.ble and time.time() >= next_poll:
                next_poll = time.time() + a.ble_poll_min * 60
                asyncio.run(ble_poll(b))
    except KeyboardInterrupt:
        finished = "stopped by Ctrl+C"
    b.note(f"soak end: {finished or 'time up'}")
    h = b.health()
    if h and h["rec"]:
        b.send("r")
        b.wait_for(r"-> (NO AUDIO LOST|AUDIO WAS LOST)", 15)
        time.sleep(1)
    b.health()
    time.sleep(1)
    b.close()
    summarize(log)


LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) (## )?(.*)$")


def summarize(path):
    path = Path(path)
    rows = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(raw)
        if m:
            rows.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f"), bool(m.group(2)), m.group(3)))
    if not rows:
        print("empty log")
        return
    t0, t1 = rows[0][0], rows[-1][0]
    hours = max((t1 - t0).total_seconds() / 3600, 1e-6)
    board = [(t, s) for t, pc, s in rows if not pc]
    pc = [(t, s) for t, pc_, s in rows if pc_]
    health = []
    for t, s in board:
        if s.startswith("HEALTH:"):
            d = {k: float(v) for k, v in re.findall(r"(\w+)=(-?[\d.]+)", s)}
            d["t"] = (t - t0).total_seconds() / 3600
            health.append(d)
    slow = [tuple(map(int, m.groups())) for _, s in board
            if (m := re.search(r"backlog peaked at \d+ blocks \((\d+) ms of audio\), drained after (\d+) ms", s))]
    switches = [int(m.group(1)) for _, s in board if (m := re.search(r"switch took (\d+) ms", s))]
    vbat = [int(m.group(1)) for _, s in board if (m := re.match(r"VBAT log: \d+,(\d+),", s))]
    stops = [s for _, s in board if s.startswith("REC stop: /")]
    lost = [s for _, s in board if "AUDIO WAS LOST" in s or s.startswith("  !! audio loss")]
    reboots = [f"{t:%H:%M:%S} {s}" for t, s in board if s.startswith("Boot, reset reason")]
    # A full card ends the soak on purpose: the stop that follows it, and the card going offline, aren't faults.
    # (Logs from before this fix can hold an INCIDENT for that stop, with the card-full line in its context.)
    full_at = next((t for t, s in board if s.startswith("SD card full")), None)
    incidents = [f"{t:%H:%M:%S} {s}" for t, s in pc if s.startswith("INCIDENT") and "SD card full" not in s]
    polls_ok = sum(s.startswith("BLE poll ok") for _, s in pc)
    polls_bad = [f"{t:%H:%M:%S} {s}" for t, s in pc if s.startswith("BLE poll FAILED")]
    errors = [f"{t:%H:%M:%S} {s}" for t, s in board if BAD.search(s) and "5 fast = failed" not in s
              and not (s == "SD NOT available" and full_at and 0 <= (t - full_at).total_seconds() < 5)]
    end_note = next((s for _, s in reversed(pc) if s.startswith("soak end:")), "soak end: still running")
    port = [f"{t:%H:%M:%S} {s}" for t, s in pc if s.startswith("port ")]

    print(f"Soak log {path.name}: {t0:%Y-%m-%d %H:%M} to {t1:%H:%M} ({hours:.2f} h; {end_note})")
    print(f"  takes started: {sum(s.startswith('REC start:') for _, s in board)}, file switches: {len(switches)}"
          + (f" (slowest {max(switches)} ms)" if switches else ""))
    if health:
        rec = [h for h in health if h.get("rec")]
        last = health[-1]
        print(f"  audio recorded (last take): {last.get('recsecs', 0) / 3600:.2f} h;  card free: "
              f"{health[0].get('free_mb', 0) / 1024:.1f} -> {last.get('free_mb', 0) / 1024:.1f} GB")
        hp = [h["heap"] for h in health]
        # Leak trend: recording-time points only, with the same Bluetooth state (switching it moves ~40 KB).
        same = [h for h in rec if h.get("ble") == (rec[-1].get("ble") if rec else None)]
        trend = "n/a (under 1 h of recording)"
        if len(same) > 10 and same[-1]["t"] - same[0]["t"] >= 1:
            ts, ys = [h["t"] for h in same], [h["heap"] for h in same]
            mt, my = sum(ts) / len(ts), sum(ys) / len(ys)
            slope = sum((x - mt) * (y - my) for x, y in zip(ts, ys)) / (sum((x - mt) ** 2 for x in ts) or 1)
            trend = f"{slope:+.0f} B/h while recording"
        print(f"  internal heap: {hp[0]:.0f} -> {hp[-1]:.0f} B (trend {trend}), lowest ever "
              f"{min(h['heapmin'] for h in health):.0f}, smallest largest-block {min(h['heapblk'] for h in health):.0f}")
        if rec:
            print(f"  while recording: deepest backlog {max(h['backlog_ms'] for h in rec):.0f} ms of the ~5461 ms "
                  f"buffer, slowest SD write {max(h['write_ms'] for h in rec):.0f} ms")
    print(f"  SD slowdowns absorbed: {len(slow)} ({len(slow) / hours:.1f}/h)"
          + (f", worst backlog {max(s[0] for s in slow)} ms, longest {max(s[1] for s in slow)} ms to drain"
             if slow else ""))
    if vbat:
        print(f"  VBAT (30 s averages): {vbat[0]} -> {vbat[-1]} mV, lowest {min(vbat)} mV")
    print(f"  Bluetooth polls: {polls_ok} ok, {len(polls_bad)} failed")
    print(f"  stop reports: {len(stops)};  audio-loss reports: {len(lost)};  reboots: {len(reboots)};  "
          f"incidents: {len(incidents)};  USB port drops: {sum('lost' in p for p in port)}")
    for title, items in (("INCIDENTS", incidents), ("REBOOTS", reboots), ("AUDIO LOSS", lost),
                         ("BLE POLL FAILURES", polls_bad), ("ERROR LINES", errors)):
        if items:
            print(f"  {title}:")
            for x in items[:12]:
                print("    " + x)
            if len(items) > 12:
                print(f"    ... {len(items) - 12} more")
    verdict = not (incidents or reboots or lost or errors)
    print(f"  VERDICT: {'clean run' if verdict else 'see the items above'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", nargs="?")
    ap.add_argument("--hours", type=float, default=12)
    ap.add_argument("--ble", action="store_true", help="Bluetooth on, and poll it from the PC")
    ap.add_argument("--ble-poll-min", type=float, default=10)
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--summarize", metavar="LOG")
    a = ap.parse_args()
    if a.summarize:
        summarize(a.summarize)
    elif a.port:
        run(a)
    else:
        ap.error("give a COM port, or --summarize LOG")


if __name__ == "__main__":
    main()
