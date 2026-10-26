"""Locate a moving sound source along the MMSA eight-mic line array and build an interactive spatial view.

The eight mics sit in a straight line (mic0 nearest the connector, mic7 farthest), evenly spaced. For each short
window the tool:

1. measures each mic's level in a band (default 1-16 kHz, where a phone speaker or similar source is far above the
   room noise), relative to that mic's own noise floor;
2. measures the arrival-time difference of every mic against the loudest one (GCC-PHAT cross-correlation, 8x
   interpolated, so well under one 48 kHz sample = 7 mm of sound travel);
3. fits a source position to those delays: distance along the array x and distance from the array line h. A line
   array can't tell which side of itself the source is on, so h is "height above the mics" in any direction.

The mic pitch is fitted from the recording unless given (--pitch-mm). Windows where the source isn't clearly above
the noise, or where the fit doesn't explain the delays, are left out of the track. A source that goes across and back
is split into passes, each with its own speed.

Needs a broadband source (noise, speech, music). A pure tone can't be located this way: GCC-PHAT has no broadband
detail to lock onto, and the tone's phase across the array is dominated by reflections. In MMSA8_0003 (a 1 kHz tone
moved along the array, 2026-10-25), neighbouring mics differed by up to 73 degrees, where a single path allows at most
41.5 degrees at 39.5 mm. For a tone, --levels-only --band around it (e.g. 950 1050) skips the fit and shows just the
level heatmap.

Writes visualizations/<name>_spatial.html (side view of the array with the source, a level heatmap with the track
overlaid, height over time, audio playback with a moving cursor, and a table) and a CSV of the track.

Usage:
    python spatial_track.py recording.wav
    python spatial_track.py recording.wav --pitch-mm 40 --band 1000 16000
    python spatial_track.py tone_recording.wav --levels-only --band 950 1050
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
from pathlib import Path
import sys
import wave

import numpy as np

SPEED_OF_SOUND_MM_S = 343_000.0
INTERP = 8                 # GCC-PHAT time interpolation factor
H_MAX_MM = 300.0           # fits pinned at this distance are treated as "far / not located"
BOARD_PITCH_MM = 39.5      # fitted from broadband takes (MMSA8_0084, MMSA8_0004); used by --levels-only


def read_wav(path: Path):
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 8 or w.getsampwidth() != 2 or w.getcomptype() != "NONE":
            raise ValueError("expected an 8-channel 16-bit PCM MMSA WAV")
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, 8)
    return sr, x


def analyse_windows(x: np.ndarray, sr: int, win: int, hop: int, band, max_lag: int):
    """Per window: band power per mic, loudest mic, delay of every mic vs the loudest, and peak strength."""
    f_win = np.fft.rfftfreq(win, 1 / sr)
    in_band = (f_win >= band[0]) & (f_win <= band[1])
    taper = np.hanning(win)[:, None]
    nfft = 2 * win
    f_cc = np.fft.rfftfreq(nfft, 1 / sr)
    keep = (f_cc >= band[0]) & (f_cc <= band[1])
    m = max_lag * INTERP
    times, power, ref_mic, delays, strength = [], [], [], [], []
    for start in range(0, len(x) - win + 1, hop):
        seg = x[start:start + win].astype(np.float64)
        seg -= seg.mean(axis=0)
        spec = np.fft.rfft(seg * taper, axis=0)
        p = (np.abs(spec[in_band]) ** 2).sum(axis=0) / win
        ref = int(np.argmax(p))
        full = np.fft.rfft(seg, nfft, axis=0)
        cross = full * np.conj(full[:, ref:ref + 1])
        cross /= np.abs(cross) + 1e-12
        cross[~keep] = 0
        cc = np.fft.irfft(cross, nfft * INTERP, axis=0)
        cc = np.concatenate((cc[-m:], cc[:m + 1]), axis=0)
        k = np.argmax(cc, axis=0)
        times.append((start + win / 2) / sr)
        power.append(p)
        ref_mic.append(ref)
        delays.append((k - m) / INTERP / sr)                       # seconds; positive = this mic hears it later
        strength.append(cc[k, np.arange(8)] * nfft * INTERP / (2 * keep.sum()))   # 1.0 = perfect match
    return np.array(times), np.array(power), np.array(ref_mic), np.array(delays), np.array(strength)


def robust_speed(t, xs, sel):
    """Line fit of x over t on the selected windows, dropping stray fits far off the line. Returns (slope, kept)."""
    sel = sel.copy()
    for _ in range(3):
        if sel.sum() < 5:
            return None, sel
        slope, icpt = np.polyfit(t[sel], xs[sel], 1)
        res = xs - (slope * t + icpt)
        mad = np.median(np.abs(res[sel])) + 1e-9
        sel &= np.abs(res) <= max(15.0, 4 * mad)
    return (float(np.polyfit(t[sel], xs[sel], 1)[0]) if sel.sum() >= 5 else None), sel


def find_passes(t, xs, hs, span):
    """Split a track into passes in one direction: a turn is where the smoothed position (median over +-0.5 s) falls
    back from its furthest point by more than a quarter of the array. Speed per pass from the windows over the array."""
    sm = np.array([np.median(xs[np.abs(t - ti) <= 0.5]) for ti in t])
    hyst, d, lo, hi, ext, turns = span / 4, 0, 0, 0, 0, []
    for i in range(len(t)):
        if d == 0:
            lo = i if sm[i] < sm[lo] else lo
            hi = i if sm[i] > sm[hi] else hi
            if sm[hi] - sm[lo] > hyst:
                d, ext = (1, hi) if hi > lo else (-1, lo)
        elif d * (sm[i] - sm[ext]) >= 0:
            ext = i
        elif abs(sm[ext] - sm[i]) > hyst:
            turns.append(ext)
            d, ext = -d, i
    bounds = [0] + turns + [len(t) - 1]
    passes = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        sel = np.zeros(len(t), bool)
        sel[a:b + 1] = True
        sel &= (xs >= 0) & (xs <= span)
        slope, kept = robust_speed(t, xs, sel)
        if slope is not None and t[kept].max() - t[kept].min() >= 1.0:
            passes.append({"speed_mm_s": round(slope, 1), "t": [round(float(t[kept].min()), 2), round(float(t[kept].max()), 2)],
                           "h_median": round(float(np.median(hs[kept])), 1), "windows": int(kept.sum())})
    return passes


class Locator:
    """Grid fit of (x, h) to the delays of one window, then a finer local grid."""

    def __init__(self, pitch_mm: float):
        self.pos = np.arange(8) * pitch_mm
        span = self.pos[-1]
        self.gx = np.arange(-0.6 * span, 1.6 * span + 1e-9, span / 120)
        self.gh = np.arange(5.0, H_MAX_MM + 1e-9, 5.0)
        gx, gh = np.meshgrid(self.gx, self.gh)
        self.dist = np.sqrt((self.pos[None, None, :] - gx[..., None]) ** 2 + gh[..., None] ** 2)

    def fit(self, tau, weight, ref, sr, refine=True):
        pred = (self.dist - self.dist[..., ref:ref + 1]) / SPEED_OF_SOUND_MM_S
        err = (((pred - tau) ** 2) * weight).sum(axis=2) / weight.sum()
        hi, xi = np.unravel_index(np.argmin(err), err.shape)
        x0, h0, best = self.gx[xi], self.gh[hi], err[hi, xi]
        if refine:
            fx = np.arange(x0 - 6, x0 + 6.01, 0.5)
            fh = np.arange(max(1.0, h0 - 6), min(H_MAX_MM, h0 + 6) + 0.01, 0.5)
            gx, gh = np.meshgrid(fx, fh)
            d = np.sqrt((self.pos[None, None, :] - gx[..., None]) ** 2 + gh[..., None] ** 2)
            p2 = (d - d[..., ref:ref + 1]) / SPEED_OF_SOUND_MM_S
            e2 = (((p2 - tau) ** 2) * weight).sum(axis=2) / weight.sum()
            j, i = np.unravel_index(np.argmin(e2), e2.shape)
            x0, h0, best = fx[i], fh[j], e2[j, i]
        return x0, h0, math.sqrt(best) * sr


def mic_weights(excess_db, strength):
    return ((strength > 0.1) & (excess_db > 6)).astype(np.float64)


def fit_pitch(times, ref, delays, strength, excess, usable, sr, lo, hi):
    """Pick the pitch whose geometry best explains the delays over the usable windows."""
    idx = np.where(usable)[0]
    if len(idx) > 300:
        idx = idx[np.linspace(0, len(idx) - 1, 300).astype(int)]

    def cost(pitch):
        loc = Locator(pitch)
        res = []
        for i in idx:
            w = mic_weights(excess[i], strength[i])
            if w.sum() >= 4:
                res.append(loc.fit(delays[i], w, ref[i], sr, refine=False)[2])
        return float(np.median(res)) if res else float("inf")

    coarse = {p: cost(p) for p in np.arange(lo, hi + 0.01, 2.0)}
    p0 = min(coarse, key=coarse.get)
    fine = {p: cost(p) for p in np.arange(max(lo, p0 - 2), min(hi, p0 + 2) + 0.01, 0.5)}
    best = min(fine, key=fine.get)
    return best, sorted({**coarse, **fine}.items())


def audio_data_uri(x: np.ndarray, sr: int, out_sr: int = 24000) -> str:
    """Average of all eight mics, band-limited and resampled, normalised, as a WAV data URI."""
    mono = x.astype(np.float64).mean(axis=1)
    mono -= mono.mean()
    step = max(1, sr // out_sr)
    spec = np.fft.rfft(mono)
    f = np.fft.rfftfreq(len(mono), 1 / sr)
    spec[f > 0.46 * sr / step] = 0
    spec[f < 40] = 0
    y = np.fft.irfft(spec, len(mono))[::step]
    y *= 0.7 * 32767 / max(1e-9, np.max(np.abs(y)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr // step)
        w.writeframes(y.astype("<i2").tobytes())
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def json_for_html(value) -> str:
    return (json.dumps(value, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=Path)
    ap.add_argument("--output", "-o", type=Path, help="HTML path (default: visualizations/<name>_spatial.html)")
    ap.add_argument("--window-ms", type=float, default=100.0)
    ap.add_argument("--hop-ms", type=float, default=50.0)
    ap.add_argument("--band", type=float, nargs=2, default=[1000.0, 16000.0], metavar=("LO_HZ", "HI_HZ"))
    ap.add_argument("--pitch-mm", type=float, help="mic spacing; default: fitted from the recording")
    ap.add_argument("--pitch-range", type=float, nargs=2, default=[25.0, 80.0], metavar=("LO_MM", "HI_MM"))
    ap.add_argument("--min-snr-db", type=float, default=15.0, help="loudest mic must be this far above its floor")
    ap.add_argument("--max-resid", type=float, default=1.0, help="max rms delay misfit, in samples, to keep a fit")
    ap.add_argument("--levels-only", action="store_true",
                    help="no position fit, just the level heatmap (for a pure tone; set --band around it)")
    ap.add_argument("--label", help="what the source was (e.g. \"1 kHz tone\"), shown in the page's headings")
    ap.add_argument("--no-audio", action="store_true", help="don't embed the audio")
    ap.add_argument("--audio-max-s", type=float, default=180.0, help="skip audio for longer recordings")
    a = ap.parse_args(argv)

    wav_path = a.wav.resolve()
    sr, x = read_wav(wav_path)
    duration = len(x) / sr
    win, hop = int(sr * a.window_ms / 1000), int(sr * a.hop_ms / 1000)
    pitch_hi = a.pitch_mm or a.pitch_range[1]
    max_lag = int(math.ceil(7 * pitch_hi / SPEED_OF_SOUND_MM_S * sr)) + 4
    times, power, ref, delays, strength = analyse_windows(x, sr, win, hop, a.band, max_lag)

    floor = np.percentile(power, 10, axis=0)
    excess = 10 * np.log10(np.maximum(power, 1e-30) / floor)       # dB above each mic's own noise floor
    usable = excess.max(axis=1) >= a.min_snr_db

    pitch_curve = []
    if a.pitch_mm or a.levels_only:
        pitch = a.pitch_mm or BOARD_PITCH_MM
    else:
        pitch, pitch_curve = fit_pitch(times, ref, delays, strength, excess, usable, sr, *a.pitch_range)

    loc = Locator(pitch)
    track = []
    for i in range(len(times)):
        row = {"t": round(float(times[i]), 4), "loudest": int(ref[i]), "x": None, "h": None, "resid": None,
               "mics": 0, "ok": False}
        w = mic_weights(excess[i], strength[i])
        if usable[i] and w.sum() >= 4 and not a.levels_only:
            xs, hs, resid = loc.fit(delays[i], w, ref[i], sr)
            row.update(x=round(float(xs), 1), h=round(float(hs), 1), resid=round(float(resid), 3), mics=int(w.sum()))
            row["ok"] = bool(resid <= a.max_resid and hs < 0.95 * H_MAX_MM)
        track.append(row)

    # Continuity: a real source moves smoothly, so keep a fit only if a window within +-2 hops agrees with it
    # (position within 30 mm). This drops isolated jumps from noise bursts.
    ok0 = [r["ok"] for r in track]
    for i, r in enumerate(track):
        if ok0[i]:
            r["ok"] = any(ok0[j] and abs(track[j]["x"] - r["x"]) < 30 and abs(track[j]["h"] - r["h"]) < 30
                          for j in range(max(0, i - 2), min(len(track), i + 3)) if j != i)
    good = [r for r in track if r["ok"]]
    summary = {"located": len(good), "windows": len(track)}
    if len(good) >= 5:
        t = np.array([r["t"] for r in good])
        xs = np.array([r["x"] for r in good])
        hs = np.array([r["h"] for r in good])
        # Speed from the windows over the array itself (x between the end mics), where the fit is best constrained,
        # per pass. The headline speed is the longest pass's (an average over a there-and-back trip means nothing).
        passes = find_passes(t, xs, hs, loc.pos[-1])
        summary["passes"] = passes
        if passes:
            main_pass = max(passes, key=lambda p: p["t"][1] - p["t"][0])
            summary["speed_mm_s"] = main_pass["speed_mm_s"]
            summary["over_t"] = main_pass["t"]
            summary["h_over_median"] = main_pass["h_median"]
        summary["x_range"] = [round(float(xs.min()), 1), round(float(xs.max()), 1)]
        summary["resid_median"] = round(float(np.median([r["resid"] for r in good])), 3)

    out = (a.output or wav_path.parent / "visualizations" / f"{wav_path.stem}_spatial.html").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["time_s", "x_mm", "h_mm", "resid_samples", "mics_used", "located", "loudest_mic"]
                    + [f"mic{i}_db_above_floor" for i in range(8)])
        for r, e in zip(track, excess):
            wr.writerow([r["t"], r["x"], r["h"], r["resid"], r["mics"], int(r["ok"]), r["loudest"]]
                        + [round(float(v), 2) for v in e])

    # Heatmap colour range: 0-40 dB above the floor; a tone (--levels-only) can sit 40+ dB up on every mic, so there it
    # spans the top 30 dB below the loudest level instead, which shows the nearest mic standing out.
    ramp_db = [0, 40]
    if a.levels_only:
        top = int(math.ceil(np.percentile(excess, 99.5) / 5) * 5)
        ramp_db = [max(0, top - 30), max(top, 10)]

    audio = None
    if not a.no_audio and duration <= a.audio_max_s:
        audio = audio_data_uri(x, sr)
    payload = {
        "file": wav_path.name, "sampleRate": sr, "duration": round(duration, 4),
        "windowMs": a.window_ms, "hopMs": a.hop_ms, "band": a.band, "pitch": pitch,
        "pitchFitted": not a.pitch_mm and not a.levels_only, "levelsOnly": a.levels_only, "rampDb": ramp_db, "label": a.label, "pitchCurve": [[round(p, 1), round(c, 3)] for p, c in pitch_curve],
        "mics": [round(float(p), 1) for p in loc.pos], "minSnr": a.min_snr_db, "maxResid": a.max_resid,
        "track": track, "excess": np.round(np.clip(excess, -10, 60), 1).T.tolist(), "summary": summary,
        "audio": audio,
    }
    out.write_text(HTML.replace("__PAYLOAD__", json_for_html(payload)), encoding="utf-8")

    print(f"HTML: {out}\nCSV:  {out.with_suffix('.csv')}")
    print(f"{wav_path.name}: {duration:.2f} s, {len(track)} windows, source located in {len(good)}")
    print(f"mic pitch {pitch:.1f} mm ({'fitted' if payload['pitchFitted'] else 'given'}); array span {loc.pos[-1]:.0f} mm"
          + ("; levels only, no position fit" if a.levels_only else ""))
    for i, p in enumerate(summary.get("passes", [])):
        print(f"pass {i + 1} over the array {p['t'][0]:.2f}-{p['t'][1]:.2f} s: {abs(p['speed_mm_s']):.0f} mm/s toward "
              f"{'mic7' if p['speed_mm_s'] > 0 else 'mic0'}, median distance from the mic line {p['h_median']:.0f} mm")
    if "x_range" in summary:
        print(f"track x {summary['x_range'][0]:.0f} to {summary['x_range'][1]:.0f} mm; median delay misfit "
              f"{summary['resid_median']:.2f} samples")
    return 0


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMSA source track</title>
<style>
  .viz-root {
    color-scheme: light;
    --page:#f9f9f7; --surface-1:#fcfcfb; --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
    --track:#eb6834; --ring:#fcfcfb;
    --seq-0:#cde2fb; --seq-1:#9ec5f4; --seq-2:#6da7ec; --seq-3:#3987e5; --seq-4:#256abf; --seq-5:#184f95; --seq-6:#0d366b;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --page:#0d0d0d; --surface-1:#1a1a19; --text-primary:#f0efec; --text-secondary:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
      --track:#d95926; --ring:#1a1a19;
      --seq-0:#104281; --seq-1:#1c5cab; --seq-2:#2a78d6; --seq-3:#3987e5; --seq-4:#6da7ec; --seq-5:#9ec5f4; --seq-6:#cde2fb;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --page:#0d0d0d; --surface-1:#1a1a19; --text-primary:#f0efec; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --track:#d95926; --ring:#1a1a19;
    --seq-0:#104281; --seq-1:#1c5cab; --seq-2:#2a78d6; --seq-3:#3987e5; --seq-4:#6da7ec; --seq-5:#9ec5f4; --seq-6:#cde2fb;
  }
  * { box-sizing:border-box; }
  body { margin:0; }
  .viz-root { background:var(--page); color:var(--text-primary); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; min-height:100vh; }
  main { max-width:1280px; margin:auto; padding:20px 16px 40px; }
  h1 { font-size:20px; margin:0 0 2px; font-weight:600; }
  .meta { color:var(--text-secondary); margin-bottom:16px; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; margin-bottom:16px; }
  .tile { background:var(--surface-1); border:1px solid var(--border); border-radius:8px; padding:10px 12px; }
  .tile .k { color:var(--text-secondary); font-size:12px; }
  .tile .v { font-size:22px; font-weight:600; margin-top:2px; }
  .tile .s { color:var(--muted); font-size:12px; }
  .card { background:var(--surface-1); border:1px solid var(--border); border-radius:8px; padding:12px 12px 8px; margin-bottom:14px; }
  .card h2 { font-size:14px; font-weight:600; margin:0 0 2px; }
  .card .sub { color:var(--text-secondary); font-size:12px; margin-bottom:6px; }
  .controls { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
  button { font:inherit; color:var(--text-primary); background:var(--surface-1); border:1px solid var(--axis); border-radius:6px; padding:6px 14px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  #clock { font-variant-numeric:tabular-nums; color:var(--text-secondary); }
  .legend { display:flex; gap:16px; align-items:center; flex-wrap:wrap; color:var(--text-secondary); font-size:12px; }
  .legend .line { display:inline-block; width:18px; height:2px; background:var(--track); vertical-align:middle; margin-right:5px; }
  .legend .grad { display:inline-block; width:120px; height:10px; border-radius:2px; vertical-align:middle; margin:0 6px; }
  canvas { display:block; width:100%; }
  .wrap { position:relative; }
  #tip { position:fixed; display:none; pointer-events:none; z-index:5; padding:8px 10px; border-radius:6px; background:var(--surface-1); color:var(--text-primary); border:1px solid var(--border); box-shadow:0 4px 16px rgba(0,0,0,.18); font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap; }
  details { margin-top:6px; }
  summary { cursor:pointer; color:var(--text-secondary); }
  table { border-collapse:collapse; font-size:12px; font-variant-numeric:tabular-nums; margin-top:8px; }
  th,td { padding:3px 10px; text-align:right; border-bottom:1px solid var(--grid); }
  th { color:var(--text-secondary); font-weight:600; position:sticky; top:0; background:var(--surface-1); }
  .tablewrap { max-height:340px; overflow:auto; }
  .note { color:var(--muted); font-size:12px; margin-top:12px; }
</style>
</head>
<body>
<div class="viz-root"><main>
  <h1 id="title"></h1>
  <div class="meta" id="meta"></div>
  <div class="tiles" id="tiles"></div>
  <div class="controls">
    <button id="play">Play</button>
    <span id="clock">0.00 s</span>
    <span class="legend"><span><span class="line"></span>source position (delay fit)</span>
      <span>level above noise floor <span class="grad" id="grad"></span><span id="gradLabel"></span></span></span>
  </div>
  <div class="card">
    <h2>Side view at the cursor</h2>
    <div class="sub">The array seen from the side, to scale. Mics are shaded by how loud they are right now; the dot is the fitted source position, with its last 2 s as a trail.</div>
    <div class="wrap"><canvas id="side"></canvas></div>
  </div>
  <div class="card">
    <h2>Where the sound is along the array, over time</h2>
    <div class="sub">Each row is a mic at its position; shading is its level above its own noise floor. The line is the fitted source position along the array. Drag or click to move the cursor.</div>
    <div class="wrap"><canvas id="heat"></canvas></div>
  </div>
  <div class="card">
    <h2>Distance from the mic line</h2>
    <div class="sub">How far the source was from the line of mics (a line array can't tell above from below or front from back).</div>
    <div class="wrap"><canvas id="height"></canvas></div>
  </div>
  <details><summary>Table view of the track</summary><div class="tablewrap"><table id="table"></table></div></details>
  <div class="note" id="note"></div>
  <div id="tip"></div>
  <audio id="audio" preload="auto"></audio>
</main></div>
<script>
const D = __PAYLOAD__;
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(n).trim();
const T = D.track, N = T.length, M = D.mics.length, span = D.mics[M-1];
const dt = D.hopMs / 1000;
let cursor = 0, playing = false;
$('title').textContent = D.label ? `${D.label} (${D.file})` : `${D.file}: moving source`;
$('meta').textContent = `${D.duration.toFixed(2)} s · ${D.sampleRate.toLocaleString()} Hz · ${D.windowMs} ms windows every ${D.hopMs} ms · band ${D.band[0]/1000}-${D.band[1]/1000} kHz · mic pitch ${D.pitch} mm (${D.pitchFitted ? 'fitted from this recording' : 'given'})`;

// ---- summary tiles
const S = D.summary, tiles = [];
if (D.levelsOnly) {
  tiles.push(['Levels only', `${D.band[0]}-${D.band[1]} Hz`, 'each mic\'s level in this band; no position fit']);
  document.querySelector('.legend .line').parentElement.style.display = 'none';  // no track to show
  $('height').closest('.card').style.display = 'none';
  $('table').closest('details').style.display = 'none';
  const subs = document.querySelectorAll('.card .sub');
  subs[0].textContent = 'The array seen from the side, to scale. Mics are shaded by how loud they are right now.';
  subs[1].textContent = 'Each row is a mic at its position; shading is its level above its own noise floor.';
  $('heat').closest('.card').querySelector('h2').textContent =
    `${D.label ? `${D.label} · ` : ''}${D.file}: level along the array, ${D.band[0] / 1000}-${D.band[1] / 1000} kHz (${D.rampDb[0]}-${D.rampDb[1]} dB above floor)`;
}
else tiles.push(['Located', `${S.located} / ${S.windows}`, 'windows with a confident fit']);
if (S.passes && S.passes.length > 1) {
  S.passes.forEach((p, i) => tiles.push([`Pass ${i + 1}`, `${Math.abs(p.speed_mm_s).toFixed(0)} mm/s`,
    `toward ${p.speed_mm_s > 0 ? 'mic7' : 'mic0'}, ${p.t[0].toFixed(1)}-${p.t[1].toFixed(1)} s, ${p.h_median.toFixed(0)} mm from the mics`]));
} else if (S.speed_mm_s !== undefined) {
  tiles.push(['Speed over the array', `${Math.abs(S.speed_mm_s).toFixed(0)} mm/s`, `toward ${S.speed_mm_s > 0 ? 'mic7' : 'mic0'}, ${S.over_t[0].toFixed(1)}-${S.over_t[1].toFixed(1)} s`]);
  tiles.push(['Distance from the mics', `${S.h_over_median.toFixed(0)} mm`, 'median while over the array']);
}
if (S.x_range) tiles.push(['Path tracked', `${S.x_range[0].toFixed(0)} to ${S.x_range[1].toFixed(0)} mm`, `mic0 = 0, mic7 = ${span.toFixed(0)} mm`]);
tiles.push(['Mic pitch', `${D.pitch} mm`, D.pitchFitted ? 'fitted from the delays' : (D.levelsOnly ? 'this board\'s, from broadband takes' : 'given')]);
if (S.resid_median !== undefined) tiles.push(['Fit quality', `${S.resid_median.toFixed(2)} samples`, 'median delay misfit (1 sample = 7 mm)']);
$('tiles').innerHTML = tiles.map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join('');

// ---- sequential ramp (one hue), level above floor minDb..maxDb
const [minDb, maxDb] = D.rampDb;
function rampColor(db) {
  const stops = [0,1,2,3,4,5,6].map(i => css(`--seq-${i}`));
  const u = Math.max(0, Math.min(1, (db - minDb) / (maxDb - minDb))) * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(u)), f = u - i;
  const a = hex(stops[i]), b = hex(stops[i+1]);
  return `rgb(${a.map((v,k)=>Math.round(v+(b[k]-v)*f)).join(',')})`;
}
function hex(h) { h = h.replace('#',''); return [0,2,4].map(i => parseInt(h.substr(i,2),16)); }
function paintLegend() {
  $('grad').style.background = `linear-gradient(90deg, ${[0,1,2,3,4,5,6].map(i=>css(`--seq-${i}`)).join(',')})`;
  $('gradLabel').textContent = `${minDb ? `${minDb}-` : '0-'}${maxDb}+ dB`;
}

function setup(c, h) {
  const r = window.devicePixelRatio || 1, w = c.parentElement.clientWidth;
  c.width = Math.round(w * r); c.height = Math.round(h * r); c.style.height = h + 'px';
  const x = c.getContext('2d'); x.setTransform(r,0,0,r,0,0); return [x, w];
}
function indexAt(t) { return Math.max(0, Math.min(N-1, Math.round((t - T[0].t) / dt))); }

// ---- side view (to scale)
const xLo = -0.55 * span, xHi = 1.55 * span, hTop = 150;
function drawSide() {
  const c = $('side'), padL = 44, padR = 16, padT = 14, padB = 44;
  const wAvail = c.parentElement.clientWidth - padL - padR, scale = wAvail / (xHi - xLo);
  const h = Math.round(hTop * scale) + padT + padB;
  const [g, w] = setup(c, h);
  const X = v => padL + (v - xLo) * scale, Y = v => h - padB - v * scale;
  g.clearRect(0,0,w,h); g.font = '11px system-ui,-apple-system,"Segoe UI",sans-serif';
  g.strokeStyle = css('--grid'); g.lineWidth = 1; g.fillStyle = css('--muted'); g.textAlign = 'right'; g.textBaseline = 'middle';
  for (let v = 50; v <= hTop; v += 50) { g.beginPath(); g.moveTo(padL, Y(v)); g.lineTo(w - padR, Y(v)); g.stroke(); g.fillText(`${v}`, padL - 6, Y(v)); }
  g.save(); g.translate(12, (padT + h - padB) / 2); g.rotate(-Math.PI/2); g.textAlign = 'center'; g.fillText('mm from mic line', 0, 0); g.restore();
  g.strokeStyle = css('--axis'); g.beginPath(); g.moveTo(padL, Y(0)); g.lineTo(w - padR, Y(0)); g.stroke();
  g.textAlign = 'center'; g.textBaseline = 'top';
  for (let v = Math.ceil(xLo/100)*100; v <= xHi; v += 100) g.fillText(`${v} mm`, X(v), Y(0) + 28);
  const i = indexAt(cursor), ex = D.excess;
  for (let m = 0; m < M; m++) {
    g.beginPath(); g.arc(X(D.mics[m]), Y(0), 6, 0, 2*Math.PI);
    g.fillStyle = rampColor(ex[m][i]); g.fill(); g.lineWidth = 2; g.strokeStyle = css('--ring'); g.stroke();
    g.lineWidth = 1; g.strokeStyle = css('--axis'); g.beginPath(); g.arc(X(D.mics[m]), Y(0), 7.5, 0, 2*Math.PI); g.stroke();
    g.fillStyle = css('--text-secondary'); g.fillText(`mic${m}`, X(D.mics[m]), Y(0) + 11);
  }
  // trail (last 2 s) and current position
  const t0 = cursor - 2;
  g.lineWidth = 2; g.strokeStyle = css('--track'); g.globalAlpha = 0.35; g.beginPath(); let pen = false;
  for (let k = indexAt(t0); k <= i; k++) { const r = T[k]; if (!r.ok) { pen = false; continue; }
    const px = X(r.x), py = Y(Math.min(hTop, r.h)); pen ? g.lineTo(px, py) : g.moveTo(px, py); pen = true; }
  g.stroke(); g.globalAlpha = 1;
  const r = T[i];
  if (r.ok) {
    g.beginPath(); g.arc(X(r.x), Y(Math.min(hTop, r.h)), 7, 0, 2*Math.PI); g.fillStyle = css('--track'); g.fill();
    g.lineWidth = 2; g.strokeStyle = css('--ring'); g.stroke();
    g.fillStyle = css('--text-primary'); g.textAlign = 'left'; g.textBaseline = 'bottom';
    g.fillText(`x ${r.x.toFixed(0)} mm, ${r.h.toFixed(0)} mm from the line`, Math.min(X(r.x) + 10, w - 190), Y(Math.min(hTop, r.h)) - 8);
  } else if (!D.levelsOnly) {
    g.fillStyle = css('--muted'); g.textAlign = 'left'; g.textBaseline = 'top'; g.fillText('no confident position at this moment', padL + 6, padT);
  }
}

// ---- heatmap: time (x) by mic position (y), with track overlay
const H = { padL: 64, padR: 64, padT: 8, padB: 28, h: 380 };
function heatGeom(w) {
  const yMin = xLo, yMax = xHi;   // same along-array range as the side view
  return { X: t => H.padL + (t / D.duration) * (w - H.padL - H.padR), Y: v => H.padT + (yMax - v) / (yMax - yMin) * (H.h - H.padT - H.padB), yMin, yMax };
}
function drawHeat() {
  const [g, w] = setup($('heat'), H.h), G = heatGeom(w);
  g.clearRect(0,0,w,H.h); g.font = '11px system-ui,-apple-system,"Segoe UI",sans-serif';
  const half = (D.mics[1] - D.mics[0]) / 2;
  for (let m = 0; m < M; m++) {
    const y0 = G.Y(D.mics[m] + half) + 1, y1 = G.Y(D.mics[m] - half) - 1;   // 2px surface gap between rows
    for (let k = 0; k < N; k++) {
      const x0 = G.X(T[k].t - dt/2), x1 = G.X(T[k].t + dt/2);
      g.fillStyle = rampColor(D.excess[m][k]); g.fillRect(x0, y0, Math.max(1, x1 - x0 + 0.5), y1 - y0);
    }
  }
  g.fillStyle = css('--text-secondary'); g.textAlign = 'right'; g.textBaseline = 'middle';
  for (let m = 0; m < M; m++) g.fillText(`mic${m}`, H.padL - 8, G.Y(D.mics[m]));
  // Position scale (mm along the array) on the right, with hairlines outside the array where the track can go.
  g.textAlign = 'left'; g.fillStyle = css('--muted'); g.strokeStyle = css('--grid'); g.lineWidth = 1;
  for (let v = Math.ceil(G.yMin / 100) * 100; v <= G.yMax; v += 100) {
    const y = G.Y(v);
    if (v < D.mics[0] - half || v > span + half) { g.beginPath(); g.moveTo(H.padL, y); g.lineTo(w - H.padR, y); g.stroke(); }
    g.fillText(`${v} mm`, w - H.padR + 6, y);
  }
  g.fillText(`beyond the mic7 end`, H.padL + 6, G.Y(span + half) - 10);
  g.fillText(`beyond the mic0 end`, H.padL + 6, G.Y(D.mics[0] - half) + 12);
  g.strokeStyle = css('--axis'); g.beginPath(); g.moveTo(H.padL, H.h - H.padB); g.lineTo(w - H.padR, H.h - H.padB); g.stroke();
  g.textAlign = 'center'; g.textBaseline = 'top'; g.fillStyle = css('--muted');
  const step = niceStep(D.duration);
  for (let t = 0; t <= D.duration + 1e-9; t += step) g.fillText(`${t.toFixed(step < 1 ? 1 : 0)} s`, G.X(t), H.h - H.padB + 6);
  // track: ring then line, broken where there is no confident fit
  for (const [col, lw] of [[css('--ring'), 4], [css('--track'), 2]]) {
    g.strokeStyle = col; g.lineWidth = lw; g.lineJoin = 'round'; g.beginPath(); let pen = false;
    for (let k = 0; k < N; k++) { const r = T[k]; if (!r.ok || r.x < G.yMin || r.x > G.yMax) { pen = false; continue; }
      const px = G.X(r.t), py = G.Y(r.x); pen ? g.lineTo(px, py) : g.moveTo(px, py); pen = true; }
    g.stroke();
  }
  // cursor
  const cx = G.X(cursor); g.strokeStyle = css('--text-primary'); g.lineWidth = 1; g.beginPath(); g.moveTo(cx, H.padT); g.lineTo(cx, H.h - H.padB); g.stroke();
  const r = T[indexAt(cursor)];
  if (r.ok && r.x >= G.yMin && r.x <= G.yMax) { g.beginPath(); g.arc(cx, G.Y(r.x), 5, 0, 2*Math.PI); g.fillStyle = css('--track'); g.fill(); g.lineWidth = 2; g.strokeStyle = css('--ring'); g.stroke(); }
}
function niceStep(span) { const raw = span / 10, p = 10 ** Math.floor(Math.log10(raw)), q = raw / p; return (q <= 1 ? 1 : q <= 2 ? 2 : q <= 5 ? 5 : 10) * p; }

// ---- height over time
const HH = { padL: 64, padR: 64, padT: 10, padB: 28, h: 150 };
function drawHeight() {
  const [g, w] = setup($('height'), HH.h), top = 150;
  const X = t => HH.padL + (t / D.duration) * (w - HH.padL - HH.padR), Y = v => HH.padT + (1 - Math.min(top, v) / top) * (HH.h - HH.padT - HH.padB);
  g.clearRect(0,0,w,HH.h); g.font = '11px system-ui,-apple-system,"Segoe UI",sans-serif';
  g.strokeStyle = css('--grid'); g.lineWidth = 1; g.fillStyle = css('--muted'); g.textAlign = 'right'; g.textBaseline = 'middle';
  for (let v = 0; v <= top; v += 50) { g.beginPath(); g.moveTo(HH.padL, Y(v)); g.lineTo(w - HH.padR, Y(v)); g.stroke(); g.fillText(`${v} mm`, HH.padL - 8, Y(v)); }
  g.textAlign = 'center'; g.textBaseline = 'top';
  const step = niceStep(D.duration);
  for (let t = 0; t <= D.duration + 1e-9; t += step) g.fillText(`${t.toFixed(step < 1 ? 1 : 0)} s`, X(t), HH.h - HH.padB + 6);
  g.strokeStyle = css('--track'); g.lineWidth = 2; g.lineJoin = 'round'; g.beginPath(); let pen = false;
  for (let k = 0; k < N; k++) { const r = T[k]; if (!r.ok) { pen = false; continue; } const px = X(r.t), py = Y(r.h); pen ? g.lineTo(px, py) : g.moveTo(px, py); pen = true; }
  g.stroke();
  const cx = X(cursor); g.strokeStyle = css('--text-primary'); g.lineWidth = 1; g.beginPath(); g.moveTo(cx, HH.padT); g.lineTo(cx, HH.h - HH.padB); g.stroke();
}

function drawAll() { drawSide(); drawHeat(); drawHeight(); $('clock').textContent = `${cursor.toFixed(2)} s`; }

// ---- interaction: hover tooltip on the heatmap, click/drag to move the cursor
function heatHit(ev) {
  const w = $('heat').parentElement.clientWidth, G = heatGeom(w);
  const t = (ev.offsetX - H.padL) / (w - H.padL - H.padR) * D.duration;
  if (t < 0 || t > D.duration) return null;
  const along = G.yMax - (ev.offsetY - H.padT) / (H.h - H.padT - H.padB) * (G.yMax - G.yMin);
  let m = 0; for (let k = 1; k < M; k++) if (Math.abs(D.mics[k] - along) < Math.abs(D.mics[m] - along)) m = k;
  return { t, m, i: indexAt(t) };
}
function showTip(ev, hit) {
  const r = T[hit.i];
  let s = `<b>${r.t.toFixed(2)} s</b><br>mic${hit.m}: ${D.excess[hit.m][hit.i].toFixed(1)} dB above its floor<br>loudest: mic${r.loudest}<br>`;
  s += r.ok ? `source: x ${r.x.toFixed(0)} mm, ${r.h.toFixed(0)} mm from the line<br>delay misfit ${r.resid.toFixed(2)} samples (${r.mics} mics)` : 'no confident position';
  $('tip').innerHTML = s; $('tip').style.display = 'block';
  $('tip').style.left = Math.min(innerWidth - 270, ev.clientX + 14) + 'px'; $('tip').style.top = (ev.clientY + 14) + 'px';
}
let dragging = false;
function seek(t) { cursor = Math.max(0, Math.min(D.duration, t)); if (audioEl.src) audioEl.currentTime = cursor; drawAll(); }
for (const id of ['heat', 'height']) {
  const c = $(id);
  c.addEventListener('mousedown', ev => { dragging = true; const p = id === 'heat' ? H : HH; seek((ev.offsetX - p.padL) / (c.parentElement.clientWidth - p.padL - p.padR) * D.duration); });
  c.addEventListener('mousemove', ev => {
    const p = id === 'heat' ? H : HH;
    if (dragging) seek((ev.offsetX - p.padL) / (c.parentElement.clientWidth - p.padL - p.padR) * D.duration);
    if (id === 'heat') { const hit = heatHit(ev); hit ? showTip(ev, hit) : ($('tip').style.display = 'none'); }
  });
  c.addEventListener('mouseleave', () => { $('tip').style.display = 'none'; });
}
window.addEventListener('mouseup', () => dragging = false);

// ---- audio playback drives the cursor
const audioEl = $('audio');
if (D.audio) { audioEl.src = D.audio; } else { $('play').disabled = true; $('play').title = 'audio not embedded'; }
$('play').addEventListener('click', () => { if (audioEl.paused) { if (cursor >= D.duration - 0.05) seek(0); audioEl.play(); } else audioEl.pause(); });
audioEl.addEventListener('play', () => { playing = true; $('play').textContent = 'Pause'; requestAnimationFrame(tick); });
audioEl.addEventListener('pause', () => { playing = false; $('play').textContent = 'Play'; });
audioEl.addEventListener('ended', () => { playing = false; $('play').textContent = 'Play'; });
function tick() { if (!playing) return; cursor = audioEl.currentTime; drawAll(); requestAnimationFrame(tick); }

// ---- table view
const rows = T.filter(r => r.ok);
$('table').innerHTML = '<tr><th>time (s)</th><th>x along array (mm)</th><th>from mic line (mm)</th><th>misfit (samples)</th><th>mics used</th><th>loudest</th></tr>' +
  rows.map(r => `<tr><td>${r.t.toFixed(2)}</td><td>${r.x.toFixed(0)}</td><td>${r.h.toFixed(0)}</td><td>${r.resid.toFixed(2)}</td><td>${r.mics}</td><td>mic${r.loudest}</td></tr>`).join('');
$('note').textContent = D.levelsOnly ? `Levels only: per ${D.windowMs} ms window, each mic's level in ${D.band[0]}-${D.band[1]} Hz above its own noise floor (its quietest 10% of windows). No position fit: a pure tone can't be located from arrival times, because its phase across the array is dominated by reflections. Mics ${D.pitch} mm apart in a straight line (mic0 at 0 mm). Audio is the average of all eight mics, normalised.` : `Method: per ${D.windowMs} ms window, arrival-time differences between mics (GCC-PHAT in ${D.band[0]/1000}-${D.band[1]/1000} kHz) fitted to a point source at distance x along the array and distance h from the mic line, speed of sound 343 m/s, mics ${D.pitch} mm apart in a straight line (mic0 at 0 mm). A window is located only if the loudest mic is at least ${D.minSnr} dB above its noise floor, at least 4 mics hear the source clearly, and the delays fit within ${D.maxResid} sample. Audio is the average of all eight mics, normalised.`;

// Open in the middle of the pass over the array, so the side view shows the source at once.
if (S.over_t) cursor = (S.over_t[0] + S.over_t[1]) / 2;
paintLegend(); drawAll();
window.addEventListener('resize', drawAll);
if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { paintLegend(); drawAll(); });
</script>
</body>
</html>'''

if __name__ == "__main__":
    raise SystemExit(main())
