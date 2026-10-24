"""Is each channel continuous audio? Lag-1 autocorrelation (real 48 kHz audio is very smooth: ~0.9+),
band-limited (300-3000 Hz) cross-correlation between channels, and alternative de-interleave hypotheses."""
import sys
import wave
import numpy as np


def load(path):
    with wave.open(path, "rb") as w:
        nch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64)
    return x, nch, sr


def lag1(s):
    s = s - s.mean()
    return float(np.dot(s[:-1], s[1:]) / (np.dot(s, s) + 1e-12))


def bandpass(s, sr, lo=300, hi=3000):
    S = np.fft.rfft(s - s.mean())
    f = np.fft.rfftfreq(len(s), 1 / sr)
    S[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(S, len(s))


for p in sys.argv[1:]:
    x, nch, sr = load(p)
    x = x[int(0.3 * sr) * nch:]
    x = x[: (len(x) // (8 * nch)) * 8 * nch]
    print(f"\n=== {p}: {nch} ch ===")
    ch = x.reshape(-1, nch)
    print(" lag-1 autocorr per channel (as stored):", " ".join(f"{lag1(ch[:, c]):.2f}" for c in range(nch)))
    if nch >= 2:
        k = min(nch, 6)
        bp = np.stack([bandpass(ch[:, c], sr) for c in range(k)], axis=1)
        cc = np.corrcoef(bp.T)
        print(" 300-3000 Hz cross-correlation:")
        for i in range(k):
            print("   " + " ".join(f"{cc[i, j]:5.2f}" for j in range(k)))
    if nch == 8:
        # Hypotheses: the real frame might be ordered differently. Try stride-s re-slicing of the raw stream
        # and report lag-1 smoothness of the first 6 resulting streams.
        for stride in (2, 4, 16):
            r = x[: (len(x) // stride) * stride].reshape(-1, stride)
            print(f" stride {stride:2d}: lag-1 of each column:", " ".join(f"{lag1(r[:, c]):.2f}" for c in range(min(stride, 16))))
        # Raw look: first 4 frames
        print(" first 4 frames (raw int16):")
        for fr in ch[:4]:
            print("   " + " ".join(f"{int(v):7d}" for v in fr))
