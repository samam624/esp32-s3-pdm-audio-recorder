"""Stress tests for the MMSA V2 recorder (firmware/MMSA_V2_Recorder_BLE), run over USB serial and Bluetooth.

Flash a short-file test build first, so file switches happen often (keep the --wrap link flags from the README):
    --build-property "compiler.cpp.extra_flags=-DSEGMENT_SECONDS=15"

Usage:  python stress_test.py COM3 [--tests cycles,rapid,ble,remote,resets,scan] [--quick]

Tests
  cycles  many start/stop takes of random length, some long enough to switch files; checks every stop report
  rapid   bursts of fast and doubled REC commands; the board must stay consistent and never be left recording
  ble     one long take while Bluetooth is switched on/off and the PC connects, reads status and disconnects
  remote  start/stop from the Bluetooth remote (control characteristic), checking the status follows
  recover simulated SD write failures (test build with -DSTRESS_HOOKS, serial F): each must continue in a new file
          with no audio lost; two within 5 s must stop the recording cleanly
  resets  resets mid-recording (a stand-in for crashes): time to remount, numbering, and a take right after
  scan    a reset at the end, to time the boot scan of all the take folders on the card

Writes the full serial log and a results file to MMSA V2/data/stress/. Afterwards, put the card in a reader and run
verify_card.py on it: it checks every file, including the ones the resets cut off.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import time
from pathlib import Path

from mmsa_serial import BLE_CONTROL, BLE_NAME, BLE_STATUS, Board, parse_status

BYTES_PER_S = 48000 * 16
BLOCK = 16384
BAD = re.compile(r"WARNING|failed|FAILED|Could not|NOT started|!! audio loss|AUDIO WAS LOST|Boot, reset reason|"
                 r"[Pp]anic|Guru|abort\(|assert|Backtrace|SD NOT available|card pulled|REC ignored|card full")
STOP_1 = re.compile(r"REC stop: (\S+), ([\d.]+) s audio \(\d+ bytes\), wall time ([\d.]+) s")
STOP_N = re.compile(r"REC stop: (\S+) \([\d.]+ s\)\. Recording: ([\d.]+) s audio in (\d+) files from \S+ .*"
                    r"wall time ([\d.]+) s")

results: list[dict] = []


def problems(lines, allow=()):
    return [l for l in lines if BAD.search(l) and not any(a in l for a in allow)]


def stop_info(lines):
    for l in lines:
        m = STOP_N.search(l)
        if m:
            return {"audio": float(m.group(2)), "files": int(m.group(3)), "wall": float(m.group(4))}
        m = STOP_1.search(l)
        if m:
            return {"audio": float(m.group(2)), "files": 1, "wall": float(m.group(3))}
    return None


def expected_files(audio_s, seg_s):
    seg = (seg_s * BYTES_PER_S // BLOCK) * BLOCK / BYTES_PER_S  # files hold whole 16 KB blocks
    n = int(audio_s // seg) + 1
    near = min(audio_s % seg, seg - audio_s % seg) < 0.2
    return n, near


def record(name, passed, details, issues):
    results.append({"test": name, "passed": passed, "details": details, "issues": issues[:30]})
    print(f"\n=== {name}: {'PASS' if passed else 'FAIL'}  {details}")
    for i in issues[:15]:
        print("    - " + i)


RECOVERED = re.compile(r"SD write failed in (/MMSA8_(\d{4})/MMSA8_\d{4}_(\d\d)\.wav) at .*recovered")
recovered_parts: list[dict] = []  # files that ended early because the recorder recovered from a write error


def note_recoveries(lines):
    n = 0
    for l in lines:
        m = RECOVERED.search(l)
        if m:
            n += 1
            recovered_parts.append({"take": int(m.group(2)), "part": int(m.group(3))})
    return n


def check_take(b, m, seg, issues, label, allow=()):
    """Check the stop report of the take that started after mark m."""
    lines = b.since(m)
    info = stop_info(lines)
    if not info:
        issues.append(f"{label}: no stop report")
        return None
    if not any("-> NO AUDIO LOST" in l for l in lines):
        issues.append(f"{label}: audio lost ({info})")
    diff = info["audio"] - info["wall"]
    if not -0.15 <= diff <= 0.5:
        issues.append(f"{label}: audio {info['audio']} s vs wall {info['wall']} s")
    recov = note_recoveries(lines)  # each recovered write error starts an extra file
    if recov:
        issues.append(f"{label}: note: recovered from {recov} SD write error(s)")
    n, near = expected_files(info["audio"], seg)
    if recov:  # a recovery starts a new file and restarts its length count, so only bounds are known
        if not recov + 1 <= info["files"] <= n + recov:
            issues.append(f"{label}: {info['files']} files for {info['audio']} s with {recov} recoveries")
    elif info["files"] != n and not (near and abs(info["files"] - n) == 1):
        issues.append(f"{label}: {info['files']} files for {info['audio']} s (expected {n})")
    for p in problems(lines, allow=allow + ("recovered in", "(test build)")):
        issues.append(f"{label}: {p}")
    return info


def recording_now(b) -> bool:
    h = b.health()
    return bool(h and h["rec"])


def take(b, seconds, seg, issues, label):
    m = b.mark()
    b.send("r")
    if not b.wait_for(r"REC start: /\S+", 3, m):
        issues.append(f"{label}: no REC start")
        return None
    time.sleep(seconds)
    if not recording_now(b):  # never send a blind 'r': it would start a new take
        issues.append(f"{label}: the recording stopped by itself: " + " | ".join(problems(b.since(m))[:3]))
        return None
    b.send("r")
    if not b.wait_for(r"-> (NO AUDIO LOST|AUDIO WAS LOST)", 10):
        issues.append(f"{label}: no stop summary")
    time.sleep(0.2)
    return check_take(b, m, seg, issues, label)


def heap_note(h0, h1):
    if not h0 or not h1:
        return "heap: n/a", []
    d = h1["heap"] - h0["heap"]
    note = f"heap {h0['heap']} -> {h1['heap']} ({d:+d} B), lowest ever {h1['heapmin']}, largest block {h1['heapblk']}"
    return note, ([f"internal heap fell {-d} bytes"] if d < -4096 else [])


# ---------------- tests ----------------
def t_cycles(b, seg, n):
    issues, audio = [], 0.0
    h0 = b.health()
    for i in range(n):
        long = i % 8 == 7
        secs = random.uniform(seg + 1, 2.3 * seg) if long else random.uniform(0.5, 6)
        info = take(b, secs, seg, issues, f"take {i + 1}/{n} ({secs:.1f} s)")
        if info:
            audio += info["audio"]
        time.sleep(random.uniform(0.3, 2))
    h1 = b.health()
    note, extra = heap_note(h0, h1)
    issues += extra
    record("cycles", not issues, f"{n} takes, {audio:.0f} s audio; {note}", issues)


def t_rapid(b, seg, n):
    issues = []
    m0 = b.mark()
    kinds = ["short", "double", "triple", "instant"]
    for i in range(n):
        kind = random.choice(kinds)
        if kind == "short":
            b.send("r"); time.sleep(random.uniform(0.05, 0.5)); b.send("r")
        elif kind == "double":
            b.send("rr")
        elif kind == "triple":
            b.send("rrr"); time.sleep(0.5); b.send("r")
        else:
            b.send("r"); time.sleep(0.01); b.send("r")
        time.sleep(0.6)
        h = b.health()
        if not h:
            issues.append(f"action {i + 1} ({kind}): no health reply")
        elif h["rec"]:
            issues.append(f"action {i + 1} ({kind}): left recording")
            b.send("r"); time.sleep(0.6)
    lines = b.since(m0)
    starts = sum("REC start:" in l for l in lines)
    stops = sum(l.startswith("REC stop: /") for l in lines)
    if starts != stops:
        issues.append(f"{starts} starts but {stops} stops")
    issues += problems(lines)
    record("rapid", not issues, f"{n} bursts, {starts} takes started and stopped", issues)


async def t_ble(b, seg, minutes):
    from bleak import BleakClient, BleakScanner
    issues = []
    h0 = b.health()
    m0 = b.mark()
    b.send("r")
    if not b.wait_for(r"REC start: /\S+", 3, m0):
        record("ble", False, "recording did not start", ["no REC start"])
        return
    t_rec = time.time()
    end = t_rec + minutes * 60
    toggles = connects = reads = drops_while_connected = 0
    last_secs = -1
    while time.time() < end:
        await asyncio.sleep(random.uniform(3, 10))
        h = b.health()
        if not h:
            issues.append("no health reply")
            continue
        if h["ble"] == 0 or random.random() < 0.3:
            m = b.mark()
            b.send("b")
            toggles += 1
            if not b.wait_for(r"Bluetooth (ON|OFF)", 5, m):
                issues.append(f"switch {toggles}: no ON/OFF confirmation")
            continue
        dev = await BleakScanner.find_device_by_name(BLE_NAME, timeout=8)
        if not dev:
            issues.append("Bluetooth on, but a scan didn't find the board")
            continue
        switched_off = False
        try:
            async with BleakClient(dev, timeout=15) as c:
                connects += 1
                for _ in range(random.randint(1, 4)):
                    st = parse_status(bytes(await c.read_gatt_char(BLE_STATUS)))
                    reads += 1
                    el = time.time() - t_rec
                    if st["len"] != 16 or not st["recording"]:
                        issues.append(f"status {st}")
                    elif st["rec_secs"] < last_secs or not el - 7 <= st["rec_secs"] <= el + 1:
                        issues.append(f"status rec_secs {st['rec_secs']} at {el:.0f} s elapsed (last {last_secs})")
                    last_secs = st.get("rec_secs", last_secs)
                    await asyncio.sleep(random.uniform(0.3, 2))
                if random.random() < 0.25:  # switch Bluetooth off while the PC is connected
                    switched_off = True
                    b.send("b")
                    toggles += 1
                    drops_while_connected += 1
                    await asyncio.sleep(1.5)
        except Exception as e:
            if not switched_off:  # a dropped link is expected after switching off mid-session
                issues.append(f"Bluetooth session failed: {type(e).__name__}: {e}")
    h = b.health()
    if h and h["ble"]:
        b.send("b")
        b.wait_for(r"Bluetooth OFF", 5)
    if recording_now(b):
        b.send("r")
        b.wait_for(r"-> (NO AUDIO LOST|AUDIO WAS LOST)", 10)
    else:
        issues.append("the long take stopped by itself: " + " | ".join(problems(b.since(m0))[:3]))
    time.sleep(0.3)
    info = check_take(b, m0, seg, issues, "long take")
    h1 = b.health()
    note, extra = heap_note(h0, h1)
    issues += extra
    record("ble", not issues, f"{minutes} min take ({info['files'] if info else '?'} files), {toggles} switches "
           f"({drops_while_connected} while connected), {connects} connections, {reads} status reads; {note}", issues)


async def t_remote(b, seg, n):
    from bleak import BleakClient, BleakScanner
    issues = []
    h = b.health()
    if h and not h["ble"]:
        b.send("b")
        b.wait_for(r"Bluetooth ON", 5)
    dev = await BleakScanner.find_device_by_name(BLE_NAME, timeout=10)
    if not dev:
        record("remote", False, "board not found over Bluetooth", ["scan failed"])
        return
    async with BleakClient(dev, timeout=15) as c:
        async def write(v):
            try:
                await c.write_gatt_char(BLE_CONTROL, bytes([v]), response=True)
            except Exception:
                await c.write_gatt_char(BLE_CONTROL, bytes([v]), response=False)

        for i in range(n):
            toggle = i % 4 == 3
            m = b.mark()
            await write(2 if toggle else 1)
            if not b.wait_for(r"REC start: /\S+", 5, m):
                issues.append(f"cycle {i + 1}: remote start didn't start a take")
                continue
            await asyncio.sleep(random.uniform(1, 5))
            st = parse_status(bytes(await c.read_gatt_char(BLE_STATUS)))
            if not st["recording"]:
                issues.append(f"cycle {i + 1}: status says not recording during a take")
            await write(2 if toggle else 0)
            if not b.wait_for(r"-> (NO AUDIO LOST|AUDIO WAS LOST)", 10, m):
                issues.append(f"cycle {i + 1}: remote stop didn't stop the take")
            await asyncio.sleep(0.8)
            st = parse_status(bytes(await c.read_gatt_char(BLE_STATUS)))
            if st["recording"]:
                issues.append(f"cycle {i + 1}: status still says recording after the stop")
            check_take(b, m, seg, issues, f"cycle {i + 1}")
            await asyncio.sleep(random.uniform(0.3, 1.5))
    await asyncio.sleep(1)
    b.send("b")
    b.wait_for(r"Bluetooth OFF", 5)
    record("remote", not issues, f"{n} remote start/stop cycles ({n // 4} by toggle)", issues)


def t_resets(b, seg, n, crashed):
    issues, mounts = [], []
    for i in range(n):
        m = b.mark()
        b.send("r")
        st = b.wait_for(r"REC start: (/\S+)", 3, m)
        if not st:
            issues.append(f"reset {i + 1}: no REC start")
            continue
        take_no = int(re.search(r"MMSA8_(\d{4})", st.group(1)).group(1))
        secs = random.uniform(4, 2 * seg + 5)
        time.sleep(secs)
        m = b.mark()
        t0 = time.time()
        b.reset()
        mount = b.wait_for(r"^SD mounted", 30, m)
        t_mount = time.time() - t0
        nxt = b.wait_for(r"next recording will go in /MMSA8_(\d+)/", 5, m)
        if not mount or not nxt:
            issues.append(f"reset {i + 1}: card not mounted within 30 s")
            continue
        mounts.append(t_mount)
        if int(nxt.group(1)) <= take_no:
            issues.append(f"reset {i + 1}: next take {nxt.group(1)} would reuse take {take_no}")
        crashed.append({"take": take_no, "reset_after_s": round(secs, 1)})
        b.wait_for(r"^MODE: idle", 5, m)
        time.sleep(0.5)
        info = take(b, 3, seg, issues, f"take right after reset {i + 1}")
        if info is None:
            issues.append(f"reset {i + 1}: couldn't record right after the reset")
    record("resets", not issues, f"{n} resets mid-recording; card mounted {min(mounts, default=0):.1f}-"
           f"{max(mounts, default=0):.1f} s after reset", issues)


def t_recover(b, seg, n):
    """Simulated SD write failures (test build's serial F): each must start a new file and lose nothing; a second one
    within 5 s must stop the recording cleanly, and the card must come back for the next take."""
    issues = []
    m0 = b.mark()
    b.send("r")
    if not b.wait_for(r"REC start: /\S+", 3, m0):
        record("recover", False, "no REC start", ["no REC start"])
        return
    for i in range(n):
        time.sleep(random.uniform(5.5, 12))
        m = b.mark()
        b.send("F")
        if not b.wait_for(r"recovered in \d+ ms", 5, m):
            issues.append(f"failure {i + 1}: no recovery: " + " | ".join(b.since(m)[-3:]))
    time.sleep(random.uniform(5.5, 8))
    if recording_now(b):
        b.send("r")
        b.wait_for(r"-> (NO AUDIO LOST|AUDIO WAS LOST)", 10)
    time.sleep(0.3)
    info = check_take(b, m0, seg, issues, f"take with {n} failures")
    issues[:] = [i for i in issues if "note: recovered" not in i]
    # Two failures within 5 s: the recorder gives up, finishes its files and remounts the card.
    m = b.mark()
    b.send("r")
    b.wait_for(r"REC start: /\S+", 3, m)
    time.sleep(6)
    b.send("F")
    time.sleep(1)
    b.send("F")
    if not b.wait_for(r"SD write failed \(card pulled\?\), stopping", 5, m):
        issues.append("second failure within 5 s didn't stop the recording")
    if not b.wait_for(r"^SD mounted", 10, m):
        issues.append("card didn't come back after the give-up")
    note_recoveries(b.since(m))
    for p in problems(b.since(m), allow=("SD write failed", "SD NOT available", "card pulled", "recovered in",
                                         "(test build)")):
        issues.append("give-up: " + p)
    time.sleep(1)
    after = take(b, 3, seg, issues, "take after the give-up")
    record("recover", not issues, f"{n} simulated write failures recovered in one take "
           f"({info['files'] if info else '?'} files); give-up path ok; next take "
           f"{'ok' if after else 'FAILED'}", issues)


def t_scan(b):
    m = b.mark()
    b.reset()
    sc = b.wait_for(r"next recording will go in /MMSA8_(\d+)/ \(([\d.]+) GB free; scan took (\d+) ms\)", 30, m)
    if not sc:
        record("scan", False, "no boot scan line", ["no 'next recording' line after reset"])
        return
    takes, ms = int(sc.group(1)) - 1, int(sc.group(3))
    issues = [f"boot scan took {ms} ms"] if ms > 2000 else []
    record("scan", not issues, f"boot scan of {takes} takes took {ms} ms ({ms / max(takes, 1):.1f} ms per take), "
           f"{sc.group(2)} GB free", issues)
    b.wait_for(r"^MODE: idle", 5, m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("--tests", default="cycles,rapid,ble,remote,recover,resets,scan")
    ap.add_argument("--quick", action="store_true", help="fewer repetitions (a ~6 minute smoke run)")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else int(time.time())
    random.seed(seed)
    out = Path(__file__).resolve().parents[1] / "data" / "stress"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M")
    log = out / f"stress_{stamp}.log"
    b = Board(a.port, str(log))
    b.note(f"stress test start, tests={a.tests}, quick={a.quick}, seed={seed}")

    m = b.mark()
    b.reset()
    fw = b.wait_for(r"a new file every (\d+) s, checkpoints every (\d+) s", 20, m)
    if not b.wait_for(r"^MODE: idle", 20, m) or not fw:
        b.note("board didn't boot with this firmware's banner (flash the current build?)")
        b.close()
        raise SystemExit(1)
    seg = int(fw.group(1))
    hooks = any("TEST BUILD: serial F" in l for l in b.since(m))
    b.note(f"firmware: a new file every {seg} s, checkpoint every {fw.group(2)} s, test hooks {'on' if hooks else 'off'}")
    if seg > 120:
        b.note("this is a long-file build; file switches won't be exercised much (flash -DSEGMENT_SECONDS=15)")
    time.sleep(1)

    q = a.quick
    crashed: list[dict] = []
    tests = a.tests.split(",")
    t_start = time.time()
    try:
        if "cycles" in tests:
            t_cycles(b, seg, 12 if q else 48)
        if "rapid" in tests:
            t_rapid(b, seg, 12 if q else 40)
        if "ble" in tests:
            asyncio.run(t_ble(b, seg, 1.5 if q else 6))
        if "remote" in tests:
            asyncio.run(t_remote(b, seg, 4 if q else 12))
        if "recover" in tests:
            if hooks:
                t_recover(b, seg, 2 if q else 4)
            else:
                b.note("skipping 'recover': needs a test build (-DSTRESS_HOOKS)")
        if "resets" in tests:
            t_resets(b, seg, 2 if q else 6, crashed)
        if "scan" in tests:
            t_scan(b)
    finally:
        h = b.health()
        if h and h["rec"]:
            b.send("r")
            time.sleep(1)
        summary = {"when": stamp, "seed": seed, "segment_s": seg, "minutes": round((time.time() - t_start) / 60, 1),
                   "results": results, "reset_takes": crashed, "recovered_parts": recovered_parts,
                   "port_drops": b.port_drops, "log": log.name}
        (out / f"stress_{stamp}.json").write_text(json.dumps(summary, indent=2))
        b.note("stress test end")
        b.close()
    print("\n================ SUMMARY ================")
    for r in results:
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['test']:7s} {r['details']}")
    if crashed:
        print("  takes cut off by a reset (verify_card.py checks they're playable): "
              + ", ".join(f"MMSA8_{c['take']:04d} (~{c['reset_after_s']} s)" for c in crashed))
    print(f"  log: {log}")


if __name__ == "__main__":
    main()
