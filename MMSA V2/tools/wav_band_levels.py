"""Per-channel energy by band and crackle (impulse) rate."""
import sys
import wave
import numpy as np

BANDS = [(0, 20), (20, 100), (100, 1000), (1000, 4000), (4000, 12000), (12000, 24000)]


def load(path):
    with wave.open(path, "rb") as w:
        nch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64).reshape(-1, nch)
    return x[int(0.3 * sr):], nch, sr


for p in sys.argv[1:]:
    x, nch, sr = load(p)
    print(f"\n=== {p} ({len(x)/sr:.1f} s) ===   band levels dBFS: " + "  ".join(f"{a}-{b}" for a, b in BANDS))
    for c in range(min(nch, 6)):
        s = x[:, c] - x[:, c].mean()
        S = np.fft.rfft(s)
        f = np.fft.rfftfreq(len(s), 1 / sr)
        tot = []
        for a, b in BANDS:
            m = (f >= a) & (f < b)
            pw = np.sum(np.abs(S[m]) ** 2) * 2 / len(s) ** 2
            tot.append(10 * np.log10(pw / 32768 ** 2 + 1e-15))
        # crackle: high-passed >4 kHz samples exceeding 8x the median absolute value
        H = S.copy()
        H[f < 4000] = 0
        h = np.fft.irfft(H, len(s))
        thr = 8 * np.median(np.abs(h)) + 1e-9
        clicks = np.sum((np.abs(h[1:]) > thr) & (np.abs(h[:-1]) <= thr)) / (len(s) / sr)
        print(f" ch{c}: " + "  ".join(f"{v:7.1f}" for v in tot) + f"   crackle {clicks:7.1f}/s")
