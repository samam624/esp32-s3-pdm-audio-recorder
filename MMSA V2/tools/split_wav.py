"""Split a multichannel MMSA recording into one mono WAV per mic.

Why: an 8-channel WAV without a speaker map is treated as 7.1 surround by most players and downmixed to
stereo (track 3 = center, track 4 = LFE/subwoofer low-passed, 5-8 = surrounds), which mangles the sound.
Listening to each mic on its own avoids that.

Usage:
    python split_wav.py <file.wav> [more.wav ...]
Writes split/<name>/mic0.wav ... (one folder per recording) next to each input. Mic N = WAV track N+1.
"""
import os
import sys
import wave

import numpy as np


def split(path):
    with wave.open(path, "rb") as w:
        nch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, nch)
    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "split", base)
    os.makedirs(out_dir, exist_ok=True)
    for c in range(nch):
        ch = data[:, c]
        if np.all(ch == ch[0]):
            print(f"  mic{c}: constant (no mic / no data), skipped")
            continue
        out = os.path.join(out_dir, f"mic{c}.wav")
        with wave.open(out, "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(sr)
            o.writeframes(np.ascontiguousarray(ch).tobytes())
        print(f"  mic{c}: {out}")


for p in sys.argv[1:]:
    print(p)
    split(p)
