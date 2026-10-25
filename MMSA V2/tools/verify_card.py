"""Check the MMSA V2 recorder's SD card (or a copy of it): every take folder, every file, and the joins between files.

Usage:  python verify_card.py H:\\  [--segment-seconds 1800] [--stress ../data/stress/stress_XXXX.json]

For each take folder /MMSA8_NNNN/ it checks:
  - every file is a complete WAV: 8 ch, 48 kHz, 16-bit, and the header's length matches the file
  - the parts are numbered 01, 02, ... with no gaps, and every part but the last is a full file
  - each join between parts is smooth (the sample step across the join is in the normal range of the audio around it)
With --stress, takes that a stress-test reset cut off are checked to hold the audio up to their last checkpoint.
Loose WAVs in the card's root (older firmware, or a take whose folder couldn't be made) are listed too.
Only reads the card.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import wave
from pathlib import Path

import numpy as np

BPS = 48000 * 16
BLOCK = 16384
CHECKPOINT_S = 10


def wav_info(p: Path) -> dict:
    size = p.stat().st_size
    if size < 44:
        return {"ok": False, "why": f"{size} bytes, no header", "secs": 0.0}
    with open(p, "rb") as f:
        h = f.read(44)
    if h[:4] != b"RIFF" or h[8:16] != b"WAVEfmt " or h[36:40] != b"data":
        return {"ok": False, "why": "not this recorder's WAV layout", "secs": 0.0}
    riff = struct.unpack("<I", h[4:8])[0]
    tag, ch, rate, brate, align, bits = struct.unpack("<HHIIHH", h[20:36])
    dlen = struct.unpack("<I", h[40:44])[0]
    why, note = [], ""
    extra = size - 44 - dlen
    if (tag, ch, rate, bits) != (1, 8, 48000, 16):
        why.append(f"format {tag}/{ch} ch/{rate} Hz/{bits}-bit")
    if 0 < extra <= 65536 and riff == 36 + dlen:
        # A write that failed part-way leaves a few KB after the audio; the recorder then carries on in a new file.
        note = f"{extra:,} bytes after the audio (left by a failed SD write the recorder recovered from)"
    elif dlen != size - 44:
        why.append(f"header says {dlen:,} data bytes, file has {size - 44:,}")
    elif riff != size - 8:
        why.append("RIFF size wrong")
    if align and dlen % align:
        why.append("ends in a partial frame")
    return {"ok": not why, "why": "; ".join(why), "note": note, "secs": dlen / brate if brate else 0.0,
            "data": dlen}


def edge(p: Path, last: bool, frames: int = 48000) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        n = w.getnframes()
        k = min(frames, n)
        w.setpos(n - k if last else 0)
        return np.frombuffer(w.readframes(k), dtype="<i2").reshape(-1, w.getnchannels()).astype(np.int32)


def join_ratio(a: Path, b: Path) -> float:
    """Sample step across the join, relative to the 99.9th percentile step in the second before it (worst channel)."""
    end, start = edge(a, True), edge(b, False, 2)
    if len(end) < 100 or len(start) == 0:
        return float("nan")
    p999 = np.percentile(np.abs(np.diff(end, axis=0)), 99.9, axis=0)
    return float((np.abs(start[0] - end[-1]) / np.maximum(p999, 1)).max())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("card")
    ap.add_argument("--segment-seconds", type=int, help="file length the firmware was built with (default: inferred)")
    ap.add_argument("--stress", help="stress_test.py results .json, to check the takes its resets cut off")
    a = ap.parse_args()
    root = Path(a.card)
    takes = sorted(p for p in root.iterdir() if p.is_dir() and re.fullmatch(r"MMSA8_\d{4}", p.name))
    loose = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".wav")
    infos = {t: {p: wav_info(p) for p in sorted(t.glob("*.wav"))} for t in takes}

    seg_bytes = None
    if a.segment_seconds:
        seg_bytes = a.segment_seconds * BPS // BLOCK * BLOCK
    else:  # the size of non-final parts of multi-part takes
        sizes = [i["data"] for t in takes for p, i in list(infos[t].items())[:-1] if i.get("data")]
        seg_bytes = max(set(sizes), key=sizes.count) if sizes else None
    reset_takes, recovered = {}, set()
    if a.stress:
        st = json.loads(Path(a.stress).read_text())
        for c in st["reset_takes"]:
            reset_takes[c["take"]] = c["reset_after_s"]
        recovered = {(r["take"], r["part"]) for r in st.get("recovered_parts", [])}

    bad_takes, total_s, nfiles, worst_join = 0, 0.0, 0, 0.0
    print(f"{len(takes)} take folders" + (f", files of {seg_bytes / BPS:.3f} s" if seg_bytes else ""))
    for t in takes:
        parts = list(infos[t].items())
        issues, notes = [], []
        if not parts:
            issues.append("empty folder")
        names = [p.name for p, _ in parts]
        want = [f"{t.name}_{k:02d}.wav" for k in range(1, len(parts) + 1)]
        if names != want:
            issues.append(f"parts named {names}, expected {want}")
        n = int(t.name[-4:])
        for k, (p, i) in enumerate(parts):
            last = k == len(parts) - 1
            if not i["ok"] and last and p.stat().st_size <= 44:
                # The recorder was reset/crashed/lost power within the file's first CHECKPOINT_S: it has no audio.
                if n not in reset_takes:
                    issues.append(f"{p.name}: empty, so the recording was cut off (crash or power loss?) "
                                  f"within {CHECKPOINT_S} s of this file starting")
            elif not i["ok"]:
                issues.append(f"{p.name}: {i['why']}")
            elif seg_bytes and k < len(parts) - 1 and i["data"] != seg_bytes:
                if (n, k + 1) in recovered or i["note"]:
                    notes.append(f"{p.name}: {i['secs']:.3f} s, ended early by a recovered SD write error")
                else:
                    issues.append(f"{p.name}: {i['secs']:.3f} s, but only the last part may be short")
            if i.get("note"):
                notes.append(f"{p.name}: {i['note']}")
        for (p1, i1), (p2, i2) in zip(parts, parts[1:]):
            if i1["ok"] and i2["ok"] and i2["secs"] > 0:
                r = join_ratio(p1, p2)
                worst_join = max(worst_join, r)
                if r > 2:
                    issues.append(f"join {p1.name} -> {p2.name}: step {r:.1f}x the normal maximum (gap?)")
        secs = sum(i["secs"] for _, i in parts if i["ok"])
        note = ""
        if n in reset_takes:
            r = reset_takes[n]
            note = f"  [reset at ~{r} s]"
            if not r - CHECKPOINT_S - 1.5 <= secs <= r + 1:
                issues.append(f"cut off by a reset at ~{r} s but holds {secs:.1f} s (expected {r - CHECKPOINT_S:.0f}"
                              f"-{r:.0f} s)")
        total_s += secs
        nfiles += len(parts)
        bad_takes += bool(issues)
        print(f"  {t.name}: {len(parts)} file(s), {secs:8.1f} s  {'OK' if not issues else 'PROBLEM'}{note}")
        for i in issues:
            print(f"      - {i}")
        for i in notes:
            print(f"      note: {i}")
    for p in loose:
        i = wav_info(p)
        print(f"  loose in root: {p.name}  {i['secs']:.1f} s  {'OK' if i['ok'] else i['why']}")
    print(f"\n{len(takes)} takes, {nfiles} files, {total_s / 60:.1f} min of audio; "
          f"{bad_takes} take(s) with problems; worst join {worst_join:.2f}x the normal step (<= 2 is fine)")


if __name__ == "__main__":
    main()
