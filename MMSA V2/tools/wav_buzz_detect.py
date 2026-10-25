"""Buzz detector: for each candidate fundamental f0 (40-500 Hz), score how far its first 15 harmonics stick up
above the neighbouring spectrum. A buzz = strong harmonic comb. Also reports noise floor in quiet stretches."""
import sys
import wave
import numpy as np


def load(path):
    with wave.open(path, "rb") as w:
        nch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float64).reshape(-1, nch)
    return x[int(0.3 * sr):], nch, sr


def spectrum(s, sr, seg=1 << 15):
    s = s - s.mean()
    win = np.hanning(seg)
    P = None
    k = 0
    for i in range(0, len(s) - seg, seg // 2):
        X = np.abs(np.fft.rfft(s[i:i + seg] * win)) ** 2
        P = X if P is None else P + X
        k += 1
    f = np.fft.rfftfreq(seg, 1 / sr)
    return f, 10 * np.log10(P / k + 1e-12)


def comb(f, Pdb, f0, nh=15):
    df = f[1] - f[0]
    score = []
    for h in range(1, nh + 1):
        fh = f0 * h
        if fh > 8000:
            break
        i = int(round(fh / df))
        peak = Pdb[max(i - 2, 0):i + 3].max()
        nb = np.concatenate([Pdb[max(i - 40, 0):max(i - 8, 0)], Pdb[i + 8:i + 40]])
        score.append(peak - np.median(nb))
    return np.mean(score) if score else 0


for p in sys.argv[1:]:
    x, nch, sr = load(p)
    print(f"\n=== {p} ===")
    for c in range(min(nch, 6)):
        f, Pdb = spectrum(x[:, c], sr)
        cands = np.arange(40, 500, 0.5)
        sc = np.array([comb(f, Pdb, f0) for f0 in cands])
        best = cands[np.argmax(sc)]
        # quiet floor: 10th percentile of 50 ms RMS
        b = sr // 20
        s = x[:, c] - x[:, c].mean()
        r = np.sqrt(np.mean(s[: len(s) // b * b].reshape(-1, b) ** 2, axis=1))
        floor = 20 * np.log10(np.percentile(r, 10) / 32768 + 1e-12)
        print(f" ch{c}: strongest harmonic comb f0={best:.1f} Hz, harmonics avg +{sc.max():.1f} dB above neighbours | quiet floor {floor:.1f} dBFS")
