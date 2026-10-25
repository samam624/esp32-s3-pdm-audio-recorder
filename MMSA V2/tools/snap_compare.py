"""Compare SD-idle vs SD-busy chunks in a /SNAP_NNNN.wav from MMSA_V2_Recorder8's snapshot test (hold REC 1.5 s).

The file is a sequence of equal chunks: idle, busy, idle, busy, ... (chunk = 10 blocks x 1024 frames by default).
Idle chunks were captured with the SD SPI bus silent, busy chunks while dummy SD writes kept it running.
If a mic's hiss is crosstalk from the SD traces, its high-band noise is much higher in busy chunks than idle ones.

Usage:
    python snap_compare.py <SNAP_NNNN.wav> [chunk_frames]
"""
import sys
import wave

import numpy as np


def main(path, chunk):
    with wave.open(path, "rb") as w:
        nch, sr = w.getnchannels(), w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, nch).astype(np.float64)
    n = len(x) // chunk
    print(f"{path}: {n} chunks of {chunk} frames ({chunk / sr * 1000:.0f} ms), {nch} ch, {sr} Hz")
    trim = 256  # skip chunk edges (discontinuities and the high-pass filter settling)
    f = np.fft.rfftfreq(chunk - 2 * trim, 1 / sr)
    hi = (f >= 4000) & (f < 20000)
    res = {"idle": [], "busy": []}
    for k in range(n):
        seg = x[k * chunk + trim:(k + 1) * chunk - trim]
        seg = seg - seg.mean(axis=0)
        win = np.hanning(len(seg))[:, None]
        P = np.abs(np.fft.rfft(seg * win, axis=0)) ** 2 / (np.sum(win ** 2) * sr) * 2
        hiband = 10 * np.log10(P[hi].mean(axis=0) / 32768 ** 2 + 1e-20)
        lag1 = [np.corrcoef(seg[:-1, c], seg[1:, c])[0, 1] if seg[:, c].std() > 0 else 0 for c in range(nch)]
        same45 = 100 * np.mean(x[k * chunk + trim:(k + 1) * chunk - trim, 4] == x[k * chunk + trim:(k + 1) * chunk - trim, 5]) if nch > 5 else 0
        res["busy" if k % 2 else "idle"].append((hiband, np.array(lag1), same45))
    for kind in ("idle", "busy"):
        if not res[kind]:
            continue
        hb = np.mean([r[0] for r in res[kind]], axis=0)
        l1 = np.mean([r[1] for r in res[kind]], axis=0)
        s45 = np.mean([r[2] for r in res[kind]])
        print(f"\n{kind.upper()} ({len(res[kind])} chunks)")
        print("  4-20 kHz noise (dB re FS^2/Hz): " + " ".join(f"mic{c} {hb[c]:6.1f}" for c in range(min(nch, 6))))
        print("  lag-1 autocorr:                 " + " ".join(f"mic{c} {l1[c]:6.2f}" for c in range(min(nch, 6))))
        print(f"  mic4 == mic5 identical samples: {s45:.1f}%")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10 * 1024)
