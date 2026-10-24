"""Build an interactive dB-vs-time view from an MMSA eight-channel WAV.

The recorder writes signed 16-bit PCM with eight interleaved tracks. This tool
streams that WAV in short windows, removes each window's DC component, and
calculates peak and RMS dBFS for every microphone. It writes:

* a standalone HTML viewer with eight DAW-style tracks, synchronized zoom/pan,
  cursor readout, and a ribbon showing the loudest microphone over time;
* a CSV containing the reduced envelope data for later analysis or plotting.

The WAV is processed a window at a time, so even long recordings do not need to
fit in RAM. If necessary, the requested window is enlarged automatically to
keep the HTML responsive.

Usage:
    python mic_timeline.py recording.wav
    python mic_timeline.py recording.wav --window-ms 10 --floor-db -80
    python mic_timeline.py recording.wav --output sweep.html
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import wave

import numpy as np


FULL_SCALE = 32768.0


def dbfs(values: np.ndarray, floor_db: float) -> np.ndarray:
    """Convert non-negative full-scale ratios to dBFS with a display floor."""
    floor_linear = 10.0 ** (floor_db / 20.0)
    return np.maximum(20.0 * np.log10(np.maximum(values, floor_linear)), floor_db)


def read_envelopes(path: Path, window_ms: float, max_points: int, floor_db: float):
    """Stream one PCM WAV and return time, RMS, and peak arrays."""
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.getnframes()
        compression = wav.getcomptype()

        if channels != 8:
            raise ValueError(f"expected an 8-channel MMSA WAV; found {channels} channels")
        if sample_width != 2:
            raise ValueError(f"expected signed 16-bit PCM; found {sample_width * 8}-bit samples")
        if compression != "NONE":
            raise ValueError(f"expected uncompressed PCM; found {compression}")
        if sample_rate <= 0 or frames <= 0:
            raise ValueError("WAV contains no audio frames")

        requested_frames = max(1, round(sample_rate * window_ms / 1000.0))
        responsive_frames = max(1, math.ceil(frames / max_points))
        frames_per_window = max(requested_frames, responsive_frames)

        times: list[float] = []
        rms_rows: list[np.ndarray] = []
        peak_rows: list[np.ndarray] = []
        frame_start = 0

        while frame_start < frames:
            raw = wav.readframes(min(frames_per_window, frames - frame_start))
            if not raw:
                break
            samples = np.frombuffer(raw, dtype="<i2")
            complete_frames = samples.size // channels
            if complete_frames == 0:
                break
            samples = samples[: complete_frames * channels].reshape(complete_frames, channels).astype(np.float64)

            # Removing the local mean prevents microphone/PDM DC offsets from
            # appearing as acoustic level. RMS represents sustained energy;
            # peak preserves short transients in a DAW-like envelope.
            samples -= samples.mean(axis=0, keepdims=True)
            rms = np.sqrt(np.mean(samples * samples, axis=0)) / FULL_SCALE
            peak = np.max(np.abs(samples), axis=0) / FULL_SCALE

            times.append((frame_start + complete_frames / 2.0) / sample_rate)
            # Retain data below the initial display floor so the viewer can be
            # switched down to -120 dBFS without reprocessing the WAV.
            stored_floor_db = min(floor_db, -120.0)
            rms_rows.append(dbfs(rms, stored_floor_db))
            peak_rows.append(dbfs(peak, stored_floor_db))
            frame_start += complete_frames

    if not times:
        raise ValueError("WAV did not contain a complete eight-channel frame")

    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "frames": frame_start,
        "duration": frame_start / sample_rate,
        "frames_per_window": frames_per_window,
        "window_ms": frames_per_window * 1000.0 / sample_rate,
        "times": np.asarray(times, dtype=np.float64),
        "rms": np.vstack(rms_rows),
        "peak": np.vstack(peak_rows),
    }


def write_csv(path: Path, data: dict) -> None:
    labels = [f"mic{i + 1}" for i in range(data["channels"])]
    header = ["time_s"]
    header += [f"{label}_rms_dbfs" for label in labels]
    header += [f"{label}_peak_dbfs" for label in labels]
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(header)
        for i, time_s in enumerate(data["times"]):
            writer.writerow(
                [f"{time_s:.6f}"]
                + [f"{value:.3f}" for value in data["rms"][i]]
                + [f"{value:.3f}" for value in data["peak"][i]]
            )


def json_for_html(value) -> str:
    """JSON safe to embed inside an HTML script element."""
    return (
        json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def write_html(path: Path, wav_path: Path, data: dict, floor_db: float) -> None:
    payload = {
        "file": wav_path.name,
        "sampleRate": data["sample_rate"],
        "channels": data["channels"],
        "frames": data["frames"],
        "duration": round(data["duration"], 9),
        "windowMs": round(data["window_ms"], 6),
        "floorDb": floor_db,
        "times": np.round(data["times"], 6).tolist(),
        # Channel-major arrays make the JavaScript drawing loop straightforward.
        "rms": np.round(data["rms"].T, 2).tolist(),
        "peak": np.round(data["peak"].T, 2).tolist(),
    }
    encoded = json_for_html(payload)
    html = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMSA microphone timeline</title>
<style>
  :root { color-scheme: dark; --bg:#0b0f14; --panel:#121923; --ink:#e8eef7; --muted:#91a0b5; --grid:#273242; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui,Segoe UI,sans-serif; }
  main { max-width:1500px; margin:auto; padding:20px; }
  h1 { font-size:22px; margin:0 0 4px; }
  #meta { color:var(--muted); margin-bottom:14px; }
  .toolbar { display:flex; gap:14px; align-items:center; flex-wrap:wrap; padding:10px 12px; background:var(--panel); border:1px solid #202b39; border-radius:8px 8px 0 0; }
  label { color:var(--muted); }
  select,button { margin-left:5px; color:var(--ink); background:#192332; border:1px solid #34445a; border-radius:5px; padding:5px 8px; }
  button { cursor:pointer; }
  #stage { position:relative; width:100%; background:#0e141d; border:1px solid #202b39; border-top:0; overflow:hidden; }
  canvas { display:block; width:100%; }
  #overlay { position:absolute; inset:0; }
  #tip { position:fixed; display:none; pointer-events:none; z-index:3; min-width:185px; padding:8px 10px; border:1px solid #52647d; border-radius:6px; background:#0a0e14ee; box-shadow:0 5px 18px #0008; font-variant-numeric:tabular-nums; }
  .hint { color:var(--muted); margin:10px 2px 0; }
  .swatch { display:inline-block; width:14px; height:3px; vertical-align:middle; margin:0 4px 2px 12px; }
  code { color:#b8d7ff; }
</style>
</head>
<body><main>
  <h1 id="title"></h1>
  <div id="meta"></div>
  <div class="toolbar">
    <label>Display<select id="mode"><option value="both">Peak + RMS</option><option value="peak">Peak only</option><option value="rms">RMS only</option></select></label>
    <label>Floor<select id="floor"><option>-120</option><option>-100</option><option selected>-90</option><option>-80</option><option>-70</option><option>-60</option></select> dBFS</label>
    <button id="reset">Reset zoom</button>
    <span><span class="swatch" style="background:#7388a8"></span>peak <span class="swatch" style="background:#fff"></span>RMS</span>
  </div>
  <div id="stage"><canvas id="plot"></canvas><canvas id="overlay"></canvas></div>
  <div class="hint">Wheel to zoom, drag to pan, double-click to reset. The colored ribbon identifies the highest-RMS microphone in each time window. Mic 1–8 correspond to WAV tracks 1–8 and firmware mic0–7.</div>
  <div id="tip"></div>
</main>
<script>
window.addEventListener('error', event => {
  const meta=document.getElementById('meta');
  meta.style.color='#ff7b8d';
  meta.textContent=`Viewer error: ${event.message} (line ${event.lineno})`;
});
</script>
<script>
const D = __PAYLOAD__;
const colors = ['#51a8ff','#00d1b2','#8bdd5b','#f0d34f','#ff9f43','#ff647c','#c47dff','#ea73cf'];
const plot = document.getElementById('plot'), overlay = document.getElementById('overlay');
const stage = document.getElementById('stage'), tip = document.getElementById('tip');
const mode = document.getElementById('mode'), floorSel = document.getElementById('floor');
document.getElementById('title').textContent = D.file;
document.getElementById('meta').textContent = `${D.channels} channels · ${D.sampleRate.toLocaleString()} Hz · ${D.duration.toFixed(2)} s · ${D.windowMs.toFixed(2)} ms envelope · ${D.times.length.toLocaleString()} points`;
if (![...floorSel.options].some(o => Number(o.value) === D.floorDb)) {
  const option=document.createElement('option'); option.value=String(D.floorDb); option.textContent=String(D.floorDb); floorSel.appendChild(option);
}
floorSel.value = String(D.floorDb);
let view0 = 0, view1 = D.duration, dragging = false, dragX = 0, drag0 = 0, drag1 = 0, hoverX = null;
const left = 72, right = 48, chartTop = 35, bottom = 34;
const cssHeight = Math.max(590, D.channels * 86 + chartTop + bottom);
plot.style.height = overlay.style.height = `${cssHeight}px`;

function setupCanvas(c) {
  const ratio = window.devicePixelRatio || 1, w = stage.clientWidth;
  c.width = Math.round(w * ratio); c.height = Math.round(cssHeight * ratio);
  c.style.height = `${cssHeight}px`;
  const x = c.getContext('2d'); x.setTransform(ratio,0,0,ratio,0,0); return x;
}
function lowerBound(a, value) { let l=0,h=a.length; while(l<h){const m=(l+h)>>1; if(a[m]<value)l=m+1;else h=m;} return l; }
function niceStep(span) { const raw=span/8, p=10**Math.floor(Math.log10(raw)), q=raw/p; return (q<=1?1:q<=2?2:q<=5?5:10)*p; }
function xFor(t,w){ return left + (t-view0)/(view1-view0)*(w-left-right); }
function timeFor(x,w){ return view0 + (x-left)/(w-left-right)*(view1-view0); }
function yFor(db,row,rowH,floor){ const usable=rowH-16; return chartTop+row*rowH+6 + (0-db)/(0-floor)*usable; }

function draw() {
  const ctx=setupCanvas(plot), w=stage.clientWidth, h=cssHeight, floor=Number(floorSel.value), rowH=(h-chartTop-bottom)/D.channels;
  ctx.clearRect(0,0,w,h); ctx.font='12px system-ui,Segoe UI,sans-serif'; ctx.textBaseline='middle';
  const a=Math.max(0,lowerBound(D.times,view0)-1), b=Math.min(D.times.length,lowerBound(D.times,view1)+1);

  // Loudest-microphone ribbon. It uses RMS rather than peak so one-sample clicks do not win.
  for(let i=a;i<b;i++){
    let winner=0,best=-Infinity; for(let c=0;c<D.channels;c++){if(D.rms[c][i]>best){best=D.rms[c][i];winner=c;}}
    const x0=xFor(i ? (D.times[i-1]+D.times[i])/2 : 0,w), x1=xFor(i+1<D.times.length ? (D.times[i]+D.times[i+1])/2 : D.duration,w);
    ctx.globalAlpha=Math.max(0.15,Math.min(1,(best-floor)/(0-floor))); ctx.fillStyle=colors[winner%colors.length]; ctx.fillRect(x0,5,Math.max(1,x1-x0),10);
  }
  ctx.globalAlpha=1; ctx.fillStyle='#91a0b5'; ctx.fillText('loudest mic',4,10);

  for(let c=0;c<D.channels;c++){
    const y0=chartTop+c*rowH, base=yFor(floor,c,rowH,floor);
    ctx.fillStyle=c%2?'#101721':'#0d141d'; ctx.fillRect(left,y0,w-left-right,rowH);
    ctx.strokeStyle='#273242'; ctx.lineWidth=1;
    for(let db=Math.ceil(floor/20)*20;db<=0;db+=20){const y=yFor(db,c,rowH,floor);ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();}
    ctx.fillStyle='#718096';ctx.font='10px system-ui,Segoe UI,sans-serif';ctx.textAlign='left';
    for(const db of [0,Math.round(floor/20)*10,floor])ctx.fillText(`${db}`,w-right+6,yFor(db,c,rowH,floor));
    ctx.fillStyle=colors[c%colors.length]; ctx.font='600 13px system-ui,Segoe UI,sans-serif'; ctx.fillText(`Mic ${c+1}`,8,y0+rowH/2-8);
    ctx.fillStyle='#77869a'; ctx.font='11px system-ui,Segoe UI,sans-serif'; ctx.fillText(`track ${c+1}`,8,y0+rowH/2+9);

    if(mode.value!=='rms'){
      ctx.beginPath();ctx.moveTo(xFor(D.times[a],w),base);
      for(let i=a;i<b;i++)ctx.lineTo(xFor(D.times[i],w),yFor(D.peak[c][i],c,rowH,floor));
      ctx.lineTo(xFor(D.times[Math.max(a,b-1)],w),base);ctx.closePath();
      ctx.globalAlpha=.30;ctx.fillStyle=colors[c%colors.length];ctx.fill();ctx.globalAlpha=1;
    }
    if(mode.value!=='peak'){
      ctx.beginPath(); for(let i=a;i<b;i++){const x=xFor(D.times[i],w),y=yFor(D.rms[c][i],c,rowH,floor);i===a?ctx.moveTo(x,y):ctx.lineTo(x,y);}
      ctx.strokeStyle=colors[c%colors.length];ctx.lineWidth=1.6;ctx.stroke();
    }
  }
  ctx.strokeStyle='#526075';ctx.beginPath();ctx.moveTo(left,chartTop);ctx.lineTo(left,h-bottom);ctx.lineTo(w-right,h-bottom);ctx.stroke();
  const step=niceStep(view1-view0), first=Math.ceil(view0/step)*step;
  ctx.fillStyle='#91a0b5';ctx.textAlign='center';ctx.font='11px system-ui,Segoe UI,sans-serif';
  for(let t=first;t<=view1+step*.01;t+=step){const x=xFor(t,w);ctx.strokeStyle='#344154';ctx.beginPath();ctx.moveTo(x,h-bottom);ctx.lineTo(x,h-bottom+5);ctx.stroke();ctx.fillText(`${t.toFixed(step<1?2:step<10?1:0)} s`,x,h-bottom+17);}
  ctx.textAlign='left'; drawOverlay();
}

function drawOverlay() {
  const ctx=setupCanvas(overlay), w=stage.clientWidth,h=cssHeight;ctx.clearRect(0,0,w,h);
  if(hoverX===null||hoverX<left||hoverX>w-right)return;
  ctx.strokeStyle='#dce8f7aa';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(hoverX,chartTop);ctx.lineTo(hoverX,h-bottom);ctx.stroke();
}
function showTip(ev) {
  const w=stage.clientWidth,t=Math.max(0,Math.min(D.duration,timeFor(ev.offsetX,w))),i=Math.min(D.times.length-1,lowerBound(D.times,t));
  let winner=0;for(let c=1;c<D.channels;c++)if(D.rms[c][i]>D.rms[winner][i])winner=c;
  let s=`<b>${D.times[i].toFixed(3)} s</b><br>`;
  for(let c=0;c<D.channels;c++)s+=`<span style="color:${colors[c]}">Mic ${c+1}</span> ${D.rms[c][i].toFixed(1)} RMS / ${D.peak[c][i].toFixed(1)} peak${c===winner?' ◀':''}<br>`;
  tip.innerHTML=s;tip.style.display='block';tip.style.left=`${Math.min(innerWidth-220,ev.clientX+14)}px`;tip.style.top=`${Math.min(innerHeight-235,ev.clientY+12)}px`;
}
overlay.addEventListener('mousemove',ev=>{hoverX=ev.offsetX;drawOverlay();showTip(ev);if(dragging){const span=drag1-drag0,dt=(ev.offsetX-dragX)/(stage.clientWidth-left-right)*span;view0=Math.max(0,Math.min(D.duration-span,drag0-dt));view1=view0+span;draw();}});
overlay.addEventListener('mouseleave',()=>{hoverX=null;dragging=false;tip.style.display='none';drawOverlay();});
overlay.addEventListener('mousedown',ev=>{dragging=true;dragX=ev.offsetX;drag0=view0;drag1=view1;});
window.addEventListener('mouseup',()=>dragging=false);
overlay.addEventListener('wheel',ev=>{ev.preventDefault();const w=stage.clientWidth,anchor=timeFor(ev.offsetX,w),old=view1-view0,factor=ev.deltaY>0?1.35:1/1.35,span=Math.max(D.windowMs/500,Math.min(D.duration,old*factor)),f=(anchor-view0)/old;view0=Math.max(0,Math.min(D.duration-span,anchor-f*span));view1=view0+span;draw();},{passive:false});
function reset(){view0=0;view1=D.duration;draw();}
overlay.addEventListener('dblclick',reset);document.getElementById('reset').addEventListener('click',reset);
mode.addEventListener('change',draw);floorSel.addEventListener('change',draw);window.addEventListener('resize',draw);draw();
</script></body></html>'''.replace("__PAYLOAD__", encoded)
    path.write_text(html, encoding="utf-8")


def default_output(input_path: Path) -> Path:
    return input_path.parent / "visualizations" / f"{input_path.stem}_timeline.html"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav", type=Path, help="eight-channel 16-bit PCM WAV from the MMSA recorder")
    parser.add_argument("--output", "-o", type=Path, help="output HTML path (default: visualizations/<name>_timeline.html)")
    parser.add_argument("--window-ms", type=float, default=20.0, help="minimum envelope window in milliseconds (default: 20)")
    parser.add_argument("--max-points", type=int, default=15000, help="maximum timeline points; window grows for long files (default: 15000)")
    parser.add_argument("--floor-db", type=float, default=-90.0, help="initial HTML display floor in dBFS (default: -90)")
    parser.add_argument("--no-csv", action="store_true", help="do not write the envelope CSV beside the HTML")
    args = parser.parse_args(argv)
    if args.window_ms <= 0:
        parser.error("--window-ms must be positive")
    if args.max_points < 100:
        parser.error("--max-points must be at least 100")
    if not -160 <= args.floor_db <= -20:
        parser.error("--floor-db must be between -160 and -20")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    wav_path = args.wav.resolve()
    if not wav_path.is_file():
        print(f"error: WAV not found: {wav_path}", file=sys.stderr)
        return 2
    output = (args.output or default_output(wav_path)).resolve()
    if output.suffix.lower() != ".html":
        print("error: --output must end in .html", file=sys.stderr)
        return 2

    try:
        data = read_envelopes(wav_path, args.window_ms, args.max_points, args.floor_db)
    except (ValueError, wave.Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    write_html(output, wav_path, data, args.floor_db)
    print(f"HTML: {output}")
    if not args.no_csv:
        csv_path = output.with_suffix(".csv")
        write_csv(csv_path, data)
        print(f"CSV:  {csv_path}")
    print(
        f"Input: {data['channels']} ch, {data['sample_rate']} Hz, {data['duration']:.3f} s; "
        f"envelope {data['window_ms']:.3f} ms, {len(data['times'])} points"
    )
    for channel in range(data["channels"]):
        i = int(np.argmax(data["peak"][:, channel]))
        print(f"  Mic {channel + 1}: peak {data['peak'][i, channel]:.1f} dBFS at {data['times'][i]:.3f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
