"""Noise-floor shape: PSD (dB per band, relative to 1 kHz band) during the quietest 20% of 50 ms frames.
PDM quantization noise that the decimation filter fails to remove shows up as a floor rising with frequency."""
import sys
import wave
import numpy as np

EDGES = [200, 500, 1000, 2000, 4000, 8000, 12000, 16000, 20000, 24000]


def load(path):
    with wave.open(path, "rb") as w:
        nch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64).reshape(-1, nch)
    return x[int(0.5 * sr):], nch, sr


for p in sys.argv[1:]:
    x, nch, sr = load(p)
    print(f"\n=== {p} ===  quiet-frame PSD by band (dB re 32768^2/Hz):")
    print("       " + " ".join(f"{a//1000 if a>=1000 else a:>5}{'k' if a>=1000 else ' '}" for a in EDGES[:-1]))
    for c in range(min(nch, 6)):
        s = x[:, c] - x[:, c].mean()
        fl = 2400
        frames = s[: len(s) // fl * fl].reshape(-1, fl)
        e = np.mean(frames ** 2, axis=1)
        q = frames[e <= np.percentile(e, 20)]
        win = np.hanning(fl)
        P = np.mean(np.abs(np.fft.rfft(q * win, axis=1)) ** 2, axis=0) / (np.sum(win ** 2) * sr) * 2
        f = np.fft.rfftfreq(fl, 1 / sr)
        vals = []
        for a, b in zip(EDGES[:-1], EDGES[1:]):
            m = (f >= a) & (f < b)
            vals.append(10 * np.log10(np.mean(P[m]) / 32768 ** 2 + 1e-20))
        print(f" ch{c}: " + " ".join(f"{v:6.1f}" for v in vals))
