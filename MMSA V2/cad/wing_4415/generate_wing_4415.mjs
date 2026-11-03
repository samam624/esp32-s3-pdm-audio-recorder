/**
 * MMSA NACA 4415 wing: the full printed wing with the mic flex, recorder board
 * and battery inside. Two P1S prints plus a backer printed in place.
 *
 * Outside: the airfoil from the wing file (upper and lower surfaces sampled
 * from "Air Foil NACA 4415 Small Slot.step", 243.84 mm chord, 199.14 mm span)
 * and the two Ø8.9 mm mounting holes in the root face. The old bottom bay,
 * skin slot and bosses are gone. It splits at the chord line (z = 0, where the
 * leading and trailing edges sit) into:
 *   - the top half: flex channel, mic pockets and ports under the upper skin,
 *     the board (components facing down) on its flat bottom face, and the battery in
 *     a pocket above the board;
 *   - the cover (bottom half): clearance for the board's parts and the flex
 *     tail, held on with countersunk M3 screws into heat-set inserts. Taking it off
 *     exposes USB-C, the SD card, the buttons and the flex connector.
 *
 * Flex. mic0 is left unpopulated. The strip lies under the upper skin at `yaw`
 * from the leading edge (near the root) to the trailing edge (near the tip),
 * mic1..mic7 in pockets as on the test bed. Past mic1 the strip wraps round the
 * nose and runs straight back inside the cover to the board's FPC connector:
 * mic0's stretch of strip plus the 46 mm tail are the cable (no extension).
 * After the nose the strip's top faces down, which is why the board sits upside down.
 *
 * Geometry on the roof (the flex's top surface) uses developed coordinates
 * (sigma = arc length along the roof from the leading edge, y = span), the same
 * as ../airfoil_testbed_4415. Frame: X chordwise from the leading edge, Y = STEP
 * y (root face at -199.14, tip face at 0), Z up, chord line at Z = 0.
 *
 * Writes output/:
 *   MMSA_wing_4415_top_print.3mf     top half + backer (printed in place), P1S plate
 *   MMSA_wing_4415_cover_print.3mf   cover, flipped onto its flat face, P1S plate
 *   MMSA_wing_4415.step              top half, backer, cover (open in Fusion 360)
 *   reference/MMSA_wing_4415_fitcheck.step   adds dummy flex, mics, caps, board, battery
 *   reference/*.stl, reference/wing_design.json   for preview_wing_4415.py
 *
 * Run:  node generate_wing_4415.mjs   (--dry prints the layout only, --yaw=30 sets the angle; 28-30 fit)
 */
import fs from 'node:fs';
import path from 'node:path';
import v8 from 'node:v8';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { buildThreeMf, meshStats, weldMesh } from '../airfoil_testbed/threemf.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(here, 'output');
const refDir = path.join(outDir, 'reference');
const DRY = process.argv.includes('--dry');
const yawArg = process.argv.find((a) => a.startsWith('--yaw='));
const STEP_FILE = process.env.AIRFOIL_STEP
  ?? path.join(here, '..', 'airfoil_testbed_4415', 'input', 'Air Foil NACA 4415 Small Slot.step');

// ---------------------------------------------------------------- parameters (mm)
const P = {
  yawDeg: yawArg ? Number(yawArg.slice(6)) : 28, // flex angle across the chord (--yaw=30 overrides); > ~11 deg keeps each port out of the turbulent wedge of the one upstream
  port: { D: 2.0, d: 1.1 }, // placeholder: use the winner from the port test bed
  micsFitted: [1, 2, 3, 4, 5, 6, 7], // mic0 unpopulated: its stretch of strip is the cable to the board

  // Flex (MIC_FLEX_MODULE.md). u runs along the strip: 0 at the tail end, 300 at the mic7 end.
  flexLength: 300.0,
  flexWidth: 14.0,
  flexThickness: 0.11,
  taper: 4.25,
  tailLength: 46.0,
  tailWidth: 5.5,
  zifInsertion: 3.5, // tail length that goes into the connector
  portXf: [284, 245, 204, 165, 125, 84, 45, 4], // mic0..mic7, strip x (0 at the mic7 end)
  portYfOffset: 0.78,
  micHeight: 1.1,
  micBody: [3.0, 4.28],
  lidHalfWidth: 2.0,
  cap10u: { xf: [3.28, 4.72], h: 1.4 },
  cap100n: { xf: [6.28, 7.72], h: 1.0 },
  capHalfWidth: 0.6,

  // Fits, same as the test bed
  channelClearance: 0.3,
  micPocketClearance: 0.15,
  gasket: 0.10,
  pocketLeadIn: 0.3,
  capMargin: 0.48,
  capHeadroom: 0.15,
  minSkin: 0.4,
  holeLidMargin: 0.35,
  cavityEndClearance: 1.5,
  backerFoam: 1.0, // use foam tape ~1.2-1.5 mm thick so the cover squeezes it a little
  backerSideClearance: 0.4,
  backerEndGap: 1.0,
  backerPeelGap: 1.0, // backer starts this far (along the strip) past the peel line
  minPrintGap: 0.35,

  // Strip placement
  peelSigma: 4.5, // strip centreline leaves the upper roof this far (roof arc) from the leading edge
  peelMargin: 2.5, // plain strip between the peel line and mic1's first cap pocket
  stripYAtPeel: null, // null = as close to the root as the board allows
  tipWall: 4.0, // channel corner stays this far from the tip face
  teMargin: 3.0,
  rootY: -199.14,
  tipY: 0,

  // Recorder board, components facing down. Sizes are scaled from the 3D render
  // (docs/images/mmsa_v2_pcb_3d.png, ESP32 module = 18 x 25.5 mm): measure before printing.
  board: {
    w: 51.8, // along X (FPC edge forward)
    l: 69.8, // along Y (battery-connector end toward the root)
    t: 1.6,
    holeInset: 2.2, // hole centres from each edge
    zifFromLipoEnd: 41.9, // FPC connector centre from the battery-connector end
    usbFromLipoEnd: 28.0,
    jstFromFpcEdge: 21.5, // battery connector centre from the FPC edge
    partsBelow: 3.0, // tallest part (user: 3 mm with everything fitted)
    pocketBelow: 6.0, // cover clearance below the PCB (room for taller parts than that)
    backPins: 1.8, // through-hole pins sticking out of the back
    aftOverhang: 7.0, // SD card ~5 mm and ESP32 antenna ~6 mm past the aft edge
    edgeClearance: 0.6,
    zifLevel: -2.4, // height of the tail where it enters the connector
  },
  boardInsert: { dia: 3.6, depth: 5.0, bossClear: 3.4 }, // M2.5 heat-set inserts
  boardX: null, // null = as far forward as the flex channel allows
  boardFrontClear: 3.0, // cover pocket in front of the FPC edge (connector, USB-C)
  jstClearance: 12.0, // cover pocket past the battery-connector end (plug + wires)
  rootWall: 3.0,

  // Battery: PKCELL LP803860, 2000 mAh, max 62 x 38.5 x 8.5 (datasheet drawing)
  battery: { l: 62.0, w: 38.5, t: 8.5, clearance: 0.75, gapAbovePins: 0.5 },

  // Cable path and cover
  skin: 1.6, // minimum skin around interior cavities
  bayHalfWidth: 10.0, // cable bay in the cover, either side of the cable centreline
  bayBottom: -7.5,
  // M3 countersunk (90 deg) into heat-set inserts; a clearance hole past the insert takes longer screws.
  coverInsert: { dia: 4.0, depth: 6.0, tailDia: 3.2, tailDepth: 6.0, clearDia: 3.4, headDia: 6.4 },
  screwLengths: [8, 10, 12, 16, 20, 25, 30], // stock M3 countersunk lengths (ISO 10642)
  // In order of preference; the first maxCoverScrews that clear everything are used.
  coverScrewCandidates: [
    [14, -180], [14, -16], [110, -16], [170, -178], [100, -102], [60, -45], [195, -100], [165, -16],
    [14, -60], [150, -128], [40, -176], [60, -16], [118, -48], [140, -95], [195, -150],
  ],
  maxCoverScrews: 8,
  screwClear: { channel: 5.0, pocket: 4.5, hole: 5.0, face: 6.0, coverMin: 5.0, topMin: 14.0 },
  mountHoles: { x: [31.75, 133.35], dia: 8.9, depth: 15.24 }, // from the STEP, centred on Z = 0

  labelFont: 'C:/Windows/Fonts/arialbd.ttf',
  labelSize: 4.0,
  labelDepth: 0.4,
};

// ---------------------------------------------------------------- CAD kernel
const nodeModules = process.env.REPLICAD_NODE_MODULES
  ?? 'C:/Users/samca/Desktop/ProjectTreebeard/MSV3/hardware/MSV3_Probe_PCB_Enclosure/tools/node/node_modules';
const load = (rel) => import(pathToFileURL(path.join(nodeModules, rel)).href);
const replicad = await load('replicad/dist/replicad.js');
const { default: opencascade } = await load('replicad-opencascadejs/dist/replicad_single.js');
replicad.setOC(await opencascade({
  locateFile: () => path.join(nodeModules, 'replicad-opencascadejs/dist/replicad_single.wasm'),
}));
const oc = replicad.getOC();

// replicad frees OpenCascade objects from JS finalizers; force GC between heavy steps.
v8.setFlagsFromString('--expose-gc');
const forceGc = vm.runInNewContext('gc');
async function freeMemory() {
  forceGc();
  await new Promise((resolve) => { setTimeout(resolve, 0); });
  forceGc();
  await new Promise((resolve) => { setTimeout(resolve, 0); });
}

// ---------------------------------------------------------------- airfoil from the STEP
const wingFile = await replicad.importSTEP(new Blob([fs.readFileSync(STEP_FILE)]));
const wingSolids = [];
{
  const explorer = new oc.TopExp_Explorer(wingFile.wrapped, oc.TopAbs_ShapeEnum.TopAbs_SOLID, oc.TopAbs_ShapeEnum.TopAbs_SHAPE);
  while (explorer.More()) { wingSolids.push(replicad.cast(explorer.Current())); explorer.Next(); }
}
const wing = wingSolids.sort((a, b) => replicad.measureVolume(b) - replicad.measureVolume(a))[0];
const skinFaces = wing.faces.filter((f) => f.geomType === 'BSPLINE_SURFACE')
  .sort((a, b) => b.boundingBox.bounds[1][2] - a.boundingBox.bounds[1][2]);
const N = 20000;

// Profile of a surface face: points LE -> TE in (X, Z) with outward unit normals.
function sampleProfile(face, outwardUp) {
  const edge = face.edges.find((e) => {
    const [mn, mx] = e.boundingBox.bounds;
    return Math.abs(mx[1] - mn[1]) < 0.01 && replicad.measureLength(e) > 100;
  });
  if (!edge) throw new Error('no profile edge found in the STEP');
  let raw = Array.from({ length: N + 1 }, (_, k) => {
    const p = edge.pointAt(k / N);
    const t = edge.tangentAt(k / N);
    return { x: p.x, z: p.z, tx: t.x, tz: t.z };
  });
  if (raw[0].x > raw[N].x) raw = raw.reverse().map((q) => ({ ...q, tx: -q.tx, tz: -q.tz }));
  return raw.map((q) => {
    const len = Math.hypot(q.tx, q.tz);
    const t = [q.tx / len, q.tz / len];
    return { x: q.x, z: q.z, n: outwardUp ? [-t[1], t[0]] : [t[1], -t[0]] };
  });
}
const upRaw = sampleProfile(skinFaces[0], true);
const loRaw = sampleProfile(skinFaces[1], false);
const LE = { x: upRaw[0].x, z: upRaw[0].z };
const grid = upRaw.map((q) => ({ x: q.x - LE.x, z: q.z - LE.z, n: q.n }));
const lower = loRaw.map((q) => ({ x: q.x - LE.x, z: q.z - LE.z, n: q.n }));
const chord = grid[N].x;
for (const [what, pts] of [['upper', grid], ['lower', lower]]) {
  if (Math.hypot(pts[0].x, pts[0].z) > 0.01 || Math.abs(pts[N].x - chord) > 0.01 || Math.abs(pts[N].z) > 0.01) {
    throw new Error(`${what} profile does not run LE to TE on z = 0`);
  }
}
if (grid[0].n[0] > -0.99 || lower[0].n[0] > -0.99) throw new Error('leading-edge normals are not -x');
const sOuter = new Float64Array(N + 1);
for (let k = 1; k <= N; k += 1) sOuter[k] = sOuter[k - 1] + Math.hypot(grid[k].x - grid[k - 1].x, grid[k].z - grid[k - 1].z);
const zMax = Math.max(...grid.map((g) => g.z));
const zMin = Math.min(...lower.map((g) => g.z));
const interp = (pts, x) => { // Z of a profile at plan X
  let lo = 0;
  let hi = pts.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].x <= x) lo = mid;
    else hi = mid;
  }
  const u = (x - pts[lo].x) / (pts[hi].x - pts[lo].x || 1);
  return pts[lo].z + (pts[hi].z - pts[lo].z) * u;
};
const zUpAt = (x) => interp(grid, Math.min(Math.max(x, 0), chord));
const zLoAt = (x) => interp(lower, Math.min(Math.max(x, 0), chord));

// ---------------------------------------------------------------- roof and developed coordinates
const micPocketHalf = P.micBody[0] / 2 + P.micPocketClearance;
const micPocketHalfY = P.micBody[1] / 2 + P.micPocketClearance;
const cavityWidth = P.flexWidth + 2 * P.channelClearance;
const roofDepth = P.port.d + P.micHeight + P.gasket; // one port design, so the roof is a constant offset
const sigma = new Float64Array(N + 1);
{
  let px = grid[0].x - roofDepth * grid[0].n[0];
  let pz = grid[0].z - roofDepth * grid[0].n[1];
  for (let k = 1; k <= N; k += 1) {
    const qx = grid[k].x - roofDepth * grid[k].n[0];
    const qz = grid[k].z - roofDepth * grid[k].n[1];
    sigma[k] = sigma[k - 1] + Math.hypot(qx - px, qz - pz);
    if (sigma[k] <= sigma[k - 1]) throw new Error(`roof line folds back at k=${k}`);
    px = qx;
    pz = qz;
  }
}
const sigmaN = sigma[N];

function atSigma(target) {
  if (target < -1e-9 || target > sigmaN + 1e-9) throw new Error(`sigma ${target} outside 0..${sigmaN}`);
  target = Math.min(Math.max(target, 0), sigmaN);
  let lo = 0;
  let hi = N;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (sigma[mid] <= target) lo = mid;
    else hi = mid;
  }
  const u = (target - sigma[lo]) / (sigma[hi] - sigma[lo]);
  const lerp = (a, b) => a + (b - a) * u;
  const a = grid[lo];
  const b = grid[hi];
  const nx = lerp(a.n[0], b.n[0]);
  const nz = lerp(a.n[1], b.n[1]);
  const nl = Math.hypot(nx, nz);
  const n = [nx / nl, nz / nl];
  const x = lerp(a.x, b.x);
  const z = lerp(a.z, b.z);
  return {
    x, z, n,
    t: [n[1], -n[0]],
    s: lerp(sOuter[lo], sOuter[hi]),
    roof: [x - roofDepth * n[0], z - roofDepth * n[1]],
    offset: (extra) => [x - (roofDepth + extra) * n[0], z - (roofDepth + extra) * n[1]],
  };
}
function planX(sg, extra = 0) {
  if (sg < 0) return 2 * planX(0, extra) - planX(-sg, extra);
  if (sg > sigmaN) {
    const k = (planX(sigmaN, extra) - planX(sigmaN - 0.5, extra)) / 0.5;
    return planX(sigmaN, extra) + (sg - sigmaN) * k;
  }
  return atSigma(sg).offset(extra)[0];
}

const th = (P.yawDeg * Math.PI) / 180;
const [cs, sn] = [Math.cos(th), Math.sin(th)];
const micU = P.portXf.map((xf) => P.flexLength - xf);
const capPocketEnd = P.cap100n.xf[1] + P.capMargin;
const firstMic = Math.min(...P.micsFitted);
const uPeel = micU[firstMic] - capPocketEnd - P.peelMargin;
const uEnd = P.flexLength + P.cavityEndClearance;

// Developed point for strip coordinates (u along, v across) once the strip's span at the peel is known.
let yPeel = 0;
const dev = (u, v) => ({ sigma: P.peelSigma + (u - uPeel) * cs - v * sn, y: yPeel + (u - uPeel) * sn + v * cs });
const planOf = (p, extra = 0) => [planX(p.sigma, extra), p.y];
const planSlope = (sg) => (planX(sg + 0.05) - planX(sg - 0.05)) / 0.1;
const planDir = (sg) => {
  const d = [planSlope(sg) * cs, sn];
  const l = Math.hypot(d[0], d[1]);
  return [d[0] / l, d[1] / l];
};
function bandEdge(v, u0, u1, extra = 0) {
  const us = [];
  let u = u0;
  while (u < u1) {
    us.push(u);
    const sg = dev(u, v).sigma;
    u += (Math.abs(sg) < 20 ? 0.15 : 0.8) / cs;
  }
  us.push(u1);
  return us.map((uu) => planOf(dev(uu, v), extra));
}

// ---------------------------------------------------------------- layout
// The strip's centreline reaches the stagnation line (sigma 0) here; past it the
// strip wraps into the cover and turns aft, so the cable runs aft along this Y.
const B = P.board;
const uStagnation = uPeel - P.peelSigma / cs;
const cableYOffset = (uStagnation - uPeel) * sn; // cable centreline relative to yPeel
const peelLimit = P.peelSigma - (cavityWidth / 2) * sn;
if (peelLimit < 0.2) throw new Error(`peel line runs past the leading edge (sigma ${peelLimit.toFixed(2)})`);

// Span: the board (battery-connector end toward the root) sets the lowest yPeel, the tip face the highest.
const yPeelMin = P.rootY + P.rootWall + P.jstClearance + B.zifFromLipoEnd - cableYOffset;
const yPeelMax = P.tipY - P.tipWall - (cavityWidth / 2) * cs - (uEnd - uPeel) * sn;
yPeel = P.stripYAtPeel ?? Math.min(Math.max(yPeelMin + 0.5, yPeelMin), yPeelMax);
if (yPeel < yPeelMin - 1e-9 || yPeel > yPeelMax + 1e-9) {
  throw new Error(`no room in span: strip y at the peel must be in ${yPeelMin.toFixed(1)}..${yPeelMax.toFixed(1)}`);
}
const yCable = yPeel + cableYOffset;
const farCornerSigma = dev(uEnd, -cavityWidth / 2).sigma;
if (farCornerSigma > sigmaN - P.teMargin) throw new Error(`channel runs into the trailing edge (sigma ${farCornerSigma.toFixed(1)} of ${sigmaN.toFixed(1)})`);

const boardY0 = yCable - B.zifFromLipoEnd; // battery-connector end (root side)
const boardY1 = boardY0 + B.l; // button end (tip side)
const channelRootEdge = bandEdge(-cavityWidth / 2, uPeel - 12, uEnd).filter(([x]) => x >= 0);
const edgeYAt = (pts, x) => { // Y of a plan polyline (monotonic in X) at X
  for (let i = 1; i < pts.length; i += 1) {
    if (pts[i][0] >= x) {
      const [a, b] = [pts[i - 1], pts[i]];
      return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0] || 1);
    }
  }
  return pts[pts.length - 1][1];
};
// Board X: the cover pocket's tip-side front corner must clear the channel (and its backer) by 1.5 mm,
// and the top half's recess must keep a 2.5 mm wall to the channel.
let boardX = P.boardX;
if (boardX === null) {
  for (let x = 20; x < 120; x += 0.25) {
    const okCover = edgeYAt(channelRootEdge, x - P.boardFrontClear) >= boardY1 + B.edgeClearance + 1.5;
    const okTop = edgeYAt(channelRootEdge, x - B.edgeClearance) >= boardY1 + B.edgeClearance + 2.5;
    if (okCover && okTop) { boardX = x; break; }
  }
  if (boardX === null) throw new Error('board does not fit beside the flex channel');
}
const boardXEnd = boardX + B.w;
// Cover pocket: the board and its overhangs, plus a narrow zone past the
// battery-connector end for the plug and wires.
const coverPocket = {
  x0: boardX - P.boardFrontClear,
  x1: boardXEnd + B.aftOverhang + 1.0,
  y0: boardY0 - B.edgeClearance - 1.0,
  y1: boardY1 + B.edgeClearance + 1.0,
  z0: -(B.t + B.pocketBelow),
};
const jstX = boardX + B.jstFromFpcEdge;
const plugZone = { x0: jstX - 9, x1: jstX + 9, y0: boardY0 - P.jstClearance, y1: coverPocket.y0 + 1, z0: coverPocket.z0 };
// Mounting holes reach 15.24 mm in from the root face at Z +-4.45: keep the board, plug zone and wire slot clear.
const holeReachY = P.rootY + P.mountHoles.depth + 1.0;
for (const hx of P.mountHoles.x) {
  const r = P.mountHoles.dia / 2 + 1.0;
  for (const [what, z] of [['board pocket', coverPocket], ['plug zone', plugZone]]) {
    if (z.x1 > hx - r && z.x0 < hx + r && z.y0 < holeReachY) throw new Error(`${what} runs into the mounting hole at X ${hx}`);
  }
}
const battery = {};
{
  const w = P.battery.w + 2 * P.battery.clearance;
  const l = P.battery.l + 2 * P.battery.clearance;
  battery.x0 = boardX + (B.w - w) / 2;
  battery.x1 = battery.x0 + w;
  battery.y0 = boardY0 + (B.l - l) / 2;
  battery.y1 = battery.y0 + l;
  battery.zTop = B.backPins + P.battery.gapAbovePins + P.battery.t + P.battery.clearance;
}
const boardHoles = [[0, 0], [1, 0], [0, 1], [1, 1]].map(([i, j]) => [
  boardX + B.holeInset + i * (B.w - 2 * B.holeInset),
  boardY0 + B.holeInset + j * (B.l - 2 * B.holeInset),
]);
for (const [hx, hy] of boardHoles) { // insert wall to the battery pocket
  const dx = Math.max(battery.x0 - hx, 0, hx - battery.x1);
  const dy = Math.max(battery.y0 - hy, 0, hy - battery.y1);
  if (Math.hypot(dx, dy) < P.boardInsert.dia / 2 + 1.2) throw new Error('battery pocket too close to a board insert');
}

// Cable: from the peel line round the nose (along the roof to the stagnation line), down
// into the cover and straight aft to the connector. Rough path length vs what the flex has.
const peelPt = atSigma(P.peelSigma).roof;
const cableCentreZ = (P.bayBottom + 0) / 2;
const cableNeeded = P.peelSigma + (Math.PI / 2) * Math.abs(cableCentreZ) + (boardX + P.zifInsertion - roofDepth)
  + Math.abs(B.zifLevel - cableCentreZ);
const cableHave = uPeel + P.taper + P.tailLength;

const mics = P.micsFitted.map((i) => {
  const centre = dev(micU[i], 0);
  const holeV = -Math.min(P.portYfOffset, P.lidHalfWidth - P.holeLidMargin - P.port.D / 2);
  const hole = dev(micU[i], holeV);
  const port = dev(micU[i], -P.portYfOffset);
  const f = atSigma(port.sigma);
  return {
    mic: i,
    centre,
    hole,
    holeV,
    portX: +f.x.toFixed(2),
    portY: +port.y.toFixed(2),
    portZ: +f.z.toFixed(2),
    portXOverC: +(f.x / chord).toFixed(3),
    surfaceSlopeDeg: +((Math.atan2(f.n[0], f.n[1]) * -180) / Math.PI).toFixed(1),
  };
});
const capPockets = [{ name: 'C10u', ...P.cap10u }, { name: 'C100n', ...P.cap100n }].map((cap) => ({
  ...cap,
  center: (cap.xf[0] + cap.xf[1]) / 2,
  half: (cap.xf[1] - cap.xf[0]) / 2 + P.capMargin,
  pocketHeight: cap.h + P.capHeadroom,
}));

// Cover screws: keep the candidates that clear everything.
const channelTipEdge = bandEdge(cavityWidth / 2, uPeel - 12, uEnd).filter(([x]) => x >= 0);
const distToPolyline = (p, pts) => {
  let best = Infinity;
  for (let i = 1; i < pts.length; i += 1) {
    const [a, b] = [pts[i - 1], pts[i]];
    const d = [b[0] - a[0], b[1] - a[1]];
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / (d[0] ** 2 + d[1] ** 2 || 1)));
    best = Math.min(best, Math.hypot(p[0] - a[0] - t * d[0], p[1] - a[1] - t * d[1]));
  }
  return best;
};
const rectDist = ([x, y], r) => Math.hypot(Math.max(r.x0 - x, 0, x - r.x1), Math.max(r.y0 - y, 0, y - r.y1));
const inChannel = ([x, y]) => y > edgeYAt(channelRootEdge, x) && y < edgeYAt(channelTipEdge, x);
const bay = { x0: 0, x1: coverPocket.x0 + 1, y0: yCable - P.bayHalfWidth, y1: yCable + P.bayHalfWidth };
const screws = [];
const screwRejects = [];
for (const s of P.coverScrewCandidates) {
  const why = [];
  const sc = P.screwClear;
  const dCh = Math.min(distToPolyline(s, channelRootEdge), distToPolyline(s, channelTipEdge));
  if (inChannel(s) || dCh < sc.channel) why.push(`channel ${dCh.toFixed(1)}`);
  if (rectDist(s, coverPocket) < sc.pocket || rectDist(s, plugZone) < sc.pocket) why.push('board pocket');
  if (rectDist(s, bay) < sc.pocket) why.push('cable bay');
  if (rectDist(s, battery) < sc.pocket) why.push('battery');
  for (const hx of P.mountHoles.x) if (rectDist(s, { x0: hx - 4.45, x1: hx + 4.45, y0: P.rootY, y1: P.rootY + P.mountHoles.depth }) < sc.hole) why.push('mount hole');
  if (s[1] - P.rootY < sc.face || P.tipY - s[1] < sc.face) why.push('end face');
  if (-zLoAt(s[0]) < sc.coverMin) why.push(`cover ${(-zLoAt(s[0])).toFixed(1)} thick`);
  if (zUpAt(s[0]) < sc.topMin) why.push(`top ${zUpAt(s[0]).toFixed(1)} thick`);
  if (why.length) screwRejects.push({ at: s, why });
  else if (screws.length < P.maxCoverScrews) screws.push(s);
}
if (screws.length < 6) throw new Error(`only ${screws.length} cover screws fit: ${JSON.stringify(screwRejects)}`);
// Screw length per position: at least 4.5 mm into the insert, no further than the clearance hole allows.
const screwLengths = screws.map(([sx]) => {
  const ci = P.coverInsert;
  const t = -zLoAt(sx) - 0.2; // cover thickness under the countersunk head
  const L = P.screwLengths.find((l) => l >= t + 4.5 && l <= t + ci.depth + ci.tailDepth - 0.5);
  if (!L) throw new Error(`no stock screw length fits at X ${sx} (cover ${t.toFixed(1)} mm)`);
  return L;
});

const summary = {
  generated: new Date().toISOString(),
  units: 'mm',
  frame: 'X chordwise from the leading edge, Y = STEP y (root face -199.14, tip face 0), Z up, chord line Z = 0. '
    + `STEP frame = this + (${LE.x.toFixed(2)}, 0, ${LE.z.toFixed(2)}).`,
  source: path.basename(STEP_FILE),
  airfoil: { chord: +chord.toFixed(3), maxZ: +zMax.toFixed(2), minZ: +zMin.toFixed(2), outerArcLength: +sOuter[N].toFixed(2), roofArc: +sigmaN.toFixed(2) },
  parameters: P,
  layout: {
    yawDeg: P.yawDeg,
    uPeel: +uPeel.toFixed(2),
    yPeel: +yPeel.toFixed(2),
    yPeelRange: [+yPeelMin.toFixed(2), +yPeelMax.toFixed(2)],
    cableY: +yCable.toFixed(2),
    channelFarCornerSigma: +farCornerSigma.toFixed(2),
    tipGap: +(P.tipY - (yPeel + (uEnd - uPeel) * sn + (cavityWidth / 2) * cs)).toFixed(2),
    board: { x0: +boardX.toFixed(2), x1: +boardXEnd.toFixed(2), y0: +boardY0.toFixed(2), y1: +boardY1.toFixed(2), holes: boardHoles.map((h) => h.map((v) => +v.toFixed(2))) },
    coverPocket: Object.fromEntries(Object.entries(coverPocket).map(([k, v]) => [k, +v.toFixed(2)])),
    battery: Object.fromEntries(Object.entries(battery).map(([k, v]) => [k, +v.toFixed(2)])),
    cable: { needed: +cableNeeded.toFixed(1), available: +cableHave.toFixed(1), slack: +(cableHave - cableNeeded).toFixed(1) },
    peel: { x: +peelPt[0].toFixed(2), z: +peelPt[1].toFixed(2) },
    coverScrews: screws,
    coverScrewLengths: screwLengths,
    coverScrewRejects: screwRejects,
  },
  mics: mics.map(({ centre, hole, ...m }) => m),
};
const L = summary.layout;
console.log(`airfoil: chord ${chord.toFixed(2)}, z ${zMin.toFixed(2)}..${zMax.toFixed(2)}, roof arc ${sigmaN.toFixed(2)}`);
console.log(`yaw ${P.yawDeg} deg; peel at u ${L.uPeel}, strip y at peel ${L.yPeel} (allowed ${L.yPeelRange.join('..')}); tip gap ${L.tipGap}; far corner sigma ${L.channelFarCornerSigma}`);
console.log(`board X ${L.board.x0}..${L.board.x1}, Y ${L.board.y0}..${L.board.y1}; cover pocket X ${L.coverPocket.x0}..${L.coverPocket.x1}`);
console.log(`cable: needs ~${L.cable.needed} mm, flex has ${L.cable.available} (slack ${L.cable.slack})`);
console.log(`cover screws ${screws.length}: ${JSON.stringify(screws)}, M3 x ${screwLengths.join('/')}; rejected ${screwRejects.map((r) => `${r.at}(${r.why.join(',')})`).join(' ')}`);
for (const m of mics) console.log(`mic${m.mic}: x/c ${m.portXOverC} (x ${m.portX}, y ${m.portY}), slope ${m.surfaceSlopeDeg}`);
if (cableHave - cableNeeded < 3) throw new Error('flex too short to reach the board connector');
fs.mkdirSync(refDir, { recursive: true });
summary.plan = {
  channelEdges: [channelRootEdge, channelTipEdge].map((e) => e.filter((_, i) => i % 4 === 0).map(([x, y]) => [+x.toFixed(2), +y.toFixed(2)])),
  ports: mics.map((m) => ({ mic: m.mic, x: +planOf(m.hole)[0].toFixed(2), y: +m.hole.y.toFixed(2) })),
  stripDirection: mics.map((m) => planDir(m.centre.sigma).map((x) => +x.toFixed(4))),
  bay,
};
if (DRY) {
  fs.writeFileSync(path.join(refDir, 'wing_layout_dry.json'), `${JSON.stringify(summary, null, 2)}\n`);
  process.exit(0);
}

// ---------------------------------------------------------------- CAD helpers
const t0 = Date.now();
const step = (what) => console.log(`[${((Date.now() - t0) / 1000).toFixed(0)} s] ${what}`);
const BSPLINE = { tolerance: 0.002, degMin: 3, degMax: 8 };

function chainSolid(chain, to3d, extrusion) {
  const splines = chain.map((seg) => (seg.length > 2 ? replicad.makeBSplineApproximation(seg.map(to3d), BSPLINE) : null));
  const ends = chain.map((seg, i) => {
    if (!splines[i]) return [to3d(seg[0]), to3d(seg[1])];
    const a = splines[i].startPoint;
    const b = splines[i].endPoint;
    for (const [got, want] of [[a, to3d(seg[0])], [b, to3d(seg[seg.length - 1])]]) {
      if (Math.hypot(got.x - want[0], got.y - want[1], got.z - want[2]) > 1e-4) throw new Error('B-spline missed its end point');
    }
    return [[a.x, a.y, a.z], [b.x, b.y, b.z]];
  });
  chain.forEach((_, i) => {
    if (splines[i]) return;
    const prev = (i + chain.length - 1) % chain.length;
    const next = (i + 1) % chain.length;
    if (splines[prev]) ends[i][0] = ends[prev][1];
    if (splines[next]) ends[i][1] = ends[next][0];
  });
  const edges = chain.map((_, i) => splines[i] ?? replicad.makeLine(ends[i][0], ends[i][1]));
  const face = replicad.makeFace(replicad.assembleWire(edges));
  return replicad.basicFaceExtrusion(face, new replicad.Vector(extrusion));
}
const sectionSolid = (chain, y0, y1) => chainSolid(chain, ([x, z]) => [x, y0, z], [0, y1 - y0, 0]);
const planSolid = (chain, z0, z1) => chainSolid(chain, ([x, y]) => [x, y, z0], [0, 0, z1 - z0]);
const box = (x0, x1, y0, y1, z0, z1) => replicad.makeBox([x0, y0, z0], [x1, y1, z1]);

function sampleSigma(from, to, fineUntil = 12, fine = 0.1, coarse = 0.5) {
  const out = [];
  let sg = from;
  while (sg < to) {
    out.push(sg);
    sg += sg < fineUntil ? fine : coarse;
  }
  out.push(to);
  return out;
}
function bandPrism(half, u0, u1, z0, z1, extra = 0) {
  const a = bandEdge(-half, u0, u1, extra);
  const b = bandEdge(half, u0, u1, extra).reverse();
  return planSolid([a, [a[a.length - 1], b[0]], b, [b[b.length - 1], a[0]]], z0, z1);
}
function offsetPolyline(pts, dist) {
  return pts.map((p, i) => {
    const a = pts[Math.max(i - 1, 0)];
    const b = pts[Math.min(i + 1, pts.length - 1)];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const l = Math.hypot(dx, dy);
    return [p[0] - (dy / l) * dist, p[1] + (dx / l) * dist];
  });
}
// Everything on the tail side (smaller u) of the developed line u = const, as a big prism.
function tailSideOf(u, z0, z1) {
  const c = planOf(dev(u, 0));
  const d = planDir(Math.max(dev(u, 0).sigma, 0.05));
  const across = [-d[1], d[0]];
  const w = 160;
  const back = 700;
  const pts = [
    [c[0] - across[0] * w, c[1] - across[1] * w],
    [c[0] + across[0] * w, c[1] + across[1] * w],
    [c[0] + across[0] * w - d[0] * back, c[1] + across[1] * w - d[1] * back],
    [c[0] - across[0] * w - d[0] * back, c[1] - across[1] * w - d[1] * back],
  ];
  return replicad.basicFaceExtrusion(replicad.makePolygon(pts.map(([x, y]) => [x, y, z0])), new replicad.Vector([0, 0, z1 - z0]));
}
function localBox(p, [a0, b0, n0], [a1, b1, n1]) {
  const f = atSigma(p.sigma);
  const phi = (Math.atan2(f.t[1], f.t[0]) * 180) / Math.PI;
  return replicad.makeBox([a0, b0, n0], [a1, b1, n1])
    .rotate(P.yawDeg, [0, 0, 0], [0, 0, 1])
    .rotate(-phi, [0, 0, 0], [0, 1, 0])
    .translate([f.roof[0], p.y, f.roof[1]]);
}
function leadIn(p, halfA, halfB, lead) {
  const f = atSigma(p.sigma);
  const phi = (Math.atan2(f.t[1], f.t[0]) * 180) / Math.PI;
  const below = 0.6;
  const rect = (ha, hb, n) => replicad.makePolygon([[-ha, -hb, n], [ha, -hb, n], [ha, hb, n], [-ha, hb, n]]).outerWire();
  return replicad.loft([
    rect(halfA + lead + below, halfB + lead + below, -below),
    rect(halfA, halfB, lead),
  ], { ruled: true })
    .rotate(P.yawDeg, [0, 0, 0], [0, 0, 1])
    .rotate(-phi, [0, 0, 0], [0, 1, 0])
    .translate([f.roof[0], p.y, f.roof[1]]);
}
// 48-sided prism instead of a cylinder: a true cylinder through the curved skin
// gave a mesh with an open hole outline on the test bed.
// `phase` (fraction of a step) turns the polygon, e.g. 0.5 keeps vertices off a
// plane through the axis, so no prism edge lies in a face it cuts.
function polyPrism(r, height, base, dir, sides = 48, phase = 0) {
  const e1 = Math.abs(dir[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  const e2 = [dir[1] * e1[2] - dir[2] * e1[1], dir[2] * e1[0] - dir[0] * e1[2], dir[0] * e1[1] - dir[1] * e1[0]];
  const pts = Array.from({ length: sides }, (_, k) => {
    const a = (2 * Math.PI * (k + phase)) / sides;
    return [0, 1, 2].map((i) => base[i] + r * (Math.cos(a) * e1[i] + Math.sin(a) * e2[i]));
  });
  return replicad.basicFaceExtrusion(replicad.makePolygon(pts), new replicad.Vector(dir.map((x) => x * height)));
}
const vCyl = (x, y, r, z0, z1) => polyPrism(r, z1 - z0, [x, y, z0], [0, 0, 1]);
function measure(shape) {
  const [min, max] = shape.boundingBox.bounds;
  return { min, max, volume: replicad.measureVolume(shape) };
}

// Airfoil point lists for B-splines (cosine spacing, denser at both edges).
function cosinePoints(pts, count = 400) {
  const s = new Float64Array(pts.length);
  for (let k = 1; k < pts.length; k += 1) s[k] = s[k - 1] + Math.hypot(pts[k].x - pts[k - 1].x, pts[k].z - pts[k - 1].z);
  const total = s[pts.length - 1];
  const out = Array.from({ length: count + 1 }, (_, j) => {
    const target = (total * (1 - Math.cos((Math.PI * j) / count))) / 2;
    let lo = 0;
    let hi = pts.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (s[mid] <= target) lo = mid;
      else hi = mid;
    }
    const u = (target - s[lo]) / (s[hi] - s[lo] || 1);
    return [pts[lo].x + (pts[hi].x - pts[lo].x) * u, pts[lo].z + (pts[hi].z - pts[lo].z) * u];
  });
  out[0] = [pts[0].x, pts[0].z];
  out[count] = [pts[pts.length - 1].x, pts[pts.length - 1].z];
  return out;
}

// ---------------------------------------------------------------- CAD
fs.mkdirSync(refDir, { recursive: true });
const Y0 = P.rootY;
const Y1 = P.tipY;
const zTop = zMax + 5;
const zBot = zMin - 5;
const upperPts = cosinePoints(grid);
const lowerPts = cosinePoints(lower);
const nose = upperPts[0];
const tail = upperPts[upperPts.length - 1];

step('halves');
let top = sectionSolid([upperPts, [tail, nose]], Y0, Y1);
let cover = sectionSolid([lowerPts, [tail, nose]], Y0, Y1);

// Inside skin: the airfoil shrunk by `skin`, used to keep interior cavities off the outside.
const insideSkin = (() => {
  const xMax = 200;
  const inUp = grid.filter((_, k) => k % 10 === 0).map((g) => ({ x: g.x - P.skin * g.n[0], z: g.z - P.skin * g.n[1] })).filter((q) => q.x <= xMax);
  const inLo = lower.filter((_, k) => k % 10 === 0).map((g) => ({ x: g.x - P.skin * g.n[0], z: g.z - P.skin * g.n[1] })).filter((q) => q.x <= xMax);
  const a = cosinePoints(inUp, 300);
  const b = cosinePoints(inLo, 300).reverse();
  b[b.length - 1] = a[0];
  return sectionSolid([a, [a[a.length - 1], b[0]], b], Y0 - 1, Y1 + 1);
})();

// Flex channel under the upper skin, from round the nose to past mic7, open down to Z = 0.
step('channel');
const roofPts = sampleSigma(0, Math.min(sigmaN, farCornerSigma + 0.5)).map((sg) => atSigma(sg).roof);
const roofStart = roofPts[0];
const roofEnd = roofPts[roofPts.length - 1];
const cavitySection = sectionSolid([
  roofPts,
  [roofEnd, [roofEnd[0], -1]],
  [[roofEnd[0], -1], [roofStart[0], -1]],
  [[roofStart[0], -1], roofStart],
], Y0, Y1);
const uChannel0 = uStagnation - 6; // channel runs a little past the stagnation line, where the strip wraps into the cover
top = top.cut(cavitySection.intersect(bandPrism(cavityWidth / 2, uChannel0, uEnd, zBot, zTop)));
await freeMemory();

// Mic pockets, ports, cap pockets (mic1..mic7).
step('pockets');
const tools = [];
for (const m of mics) {
  const micPocketTop = P.micHeight + P.gasket;
  tools.push(localBox(m.centre, [-micPocketHalf, -micPocketHalfY, -0.6], [micPocketHalf, micPocketHalfY, micPocketTop]));
  tools.push(leadIn(m.centre, micPocketHalf, micPocketHalfY, P.pocketLeadIn));
  const f = atSigma(m.hole.sigma);
  const start = micPocketTop - 0.05;
  tools.push(polyPrism(P.port.D / 2, roofDepth - start + 1.5, [f.roof[0] + f.n[0] * start, m.hole.y, f.roof[1] + f.n[1] * start], [f.n[0], 0, f.n[1]]));
  for (const cap of capPockets) {
    const skin = roofDepth - cap.pocketHeight;
    const topZ = skin < P.minSkin ? roofDepth + 1.5 : cap.pocketHeight;
    const halfW = P.capHalfWidth + P.capMargin;
    tools.push(localBox(dev(micU[m.mic] - cap.center, 0), [-cap.half, -halfW, -0.6], [cap.half, halfW, topZ]));
  }
}
for (const tool of tools) {
  top = top.cut(tool);
  await freeMemory();
}

// Board recess (back-side pins), battery pocket, wire slot, inserts.
step('board and battery');
const bx0 = boardX - B.edgeClearance;
const bx1 = boardXEnd + B.edgeClearance;
const by0 = boardY0 - B.edgeClearance;
const by1 = boardY1 + B.edgeClearance;
let recess = box(bx0, bx1, by0, by1, -1, B.backPins + 0.2);
for (const [hx, hy] of boardHoles) recess = recess.cut(vCyl(hx, hy, P.boardInsert.bossClear, -2, B.backPins + 1));
top = top.cut(recess);
top = top.cut(box(battery.x0, battery.x1, battery.y0, battery.y1, -1, battery.zTop));
// Wire slot from the battery pocket's root end past the board's battery-connector end.
top = top.cut(box(plugZone.x0, plugZone.x1, plugZone.y0 + 2, battery.y0 + 6, -1, battery.zTop));
for (const [hx, hy] of boardHoles) top = top.cut(vCyl(hx, hy, P.boardInsert.dia / 2, -1, P.boardInsert.depth));
await freeMemory();

// Cover: board pocket, cable bay, screw holes.
step('cover');
cover = cover.cut(box(coverPocket.x0, coverPocket.x1, coverPocket.y0, coverPocket.y1, coverPocket.z0, 1));
cover = cover.cut(box(plugZone.x0, plugZone.x1, plugZone.y0, plugZone.y1 + 1, plugZone.z0, 1));
// The inside-skin shape comes to a point at the nose exactly on Z = 0; start the
// bay just behind it so the cut doesn't pinch to a line on the cover's top face.
cover = cover.cut(box(P.skin + 0.4, bay.x1, bay.y0, bay.y1, P.bayBottom, 1).intersect(insideSkin.clone()));
await freeMemory();

// Cover screws: countersunk from the lower surface into inserts in the top half.
step('screws');
const ci = P.coverInsert;
for (const [sx, sy] of screws) {
  const zl = zLoAt(sx);
  top = top.cut(vCyl(sx, sy, ci.dia / 2, -1, ci.depth));
  top = top.cut(vCyl(sx, sy, ci.tailDia / 2, ci.depth - 0.5, ci.depth + ci.tailDepth));
  cover = cover.cut(vCyl(sx, sy, ci.clearDia / 2, zl - 2, 1));
  // 90 deg countersink as one 45 deg cone: head diameter at 0.2 mm inside the
  // surface, carried on past the surface so it crosses the skin cleanly.
  const headR = ci.headDia / 2;
  const zFlush = zl + 0.2;
  const ring = (r, z) => replicad.makePolygon(Array.from({ length: 48 }, (_, k) => {
    const a = (2 * Math.PI * (k + 0.5)) / 48;
    return [sx + r * Math.cos(a), sy + r * Math.sin(a), z];
  })).outerWire();
  const cone = replicad.loft([ring(headR + 3, zFlush - 3), ring(ci.clearDia / 2, zFlush + headR - ci.clearDia / 2)], { ruled: true });
  cover = cover.cut(cone);
  await freeMemory();
}

// Mounting holes in the root face (half in each part).
for (const hx of P.mountHoles.x) {
  const hole = polyPrism(P.mountHoles.dia / 2, P.mountHoles.depth + 1, [hx, Y0 - 1, 0], [0, 1, 0], 48, 0.5);
  top = top.cut(hole.clone());
  cover = cover.cut(hole);
}
await freeMemory();

// Mic numbers engraved in the top half's bottom face, mirrored to read from below.
step('labels');
const fontBytes = fs.readFileSync(P.labelFont);
await replicad.loadFont(fontBytes.buffer.slice(fontBytes.byteOffset, fontBytes.byteOffset + fontBytes.byteLength), 'label');
const labels = [];
for (const m of mics) {
  const p = dev(micU[m.mic], cavityWidth / 2 + 5);
  const [cx, cy] = planOf(p);
  if (cx < 8 || cx > chord - 15) continue;
  const drawing = replicad.drawText(String(m.mic), { fontSize: P.labelSize, fontFamily: 'label' });
  const [[x0, y0], [x1, y1]] = drawing.boundingBox.bounds;
  const plane = new replicad.Plane([0, 0, -0.2], [1, 0, 0], [0, 0, -1]);
  top = top.cut(drawing.translate(-(x0 + x1) / 2, -(y0 + y1) / 2).translate(cx, -cy).sketchOnPlane(plane)
    .extrude(P.labelDepth + 0.2, { extrusionDirection: [0, 0, 1] }));
  labels.push({ mic: m.mic, x: +cx.toFixed(1), y: +cy.toFixed(1) });
  await freeMemory();
}

// Backer: printed in place in the channel, pressed up by the cover through ~1 mm of foam.
step('backer');
const backerGap = P.flexThickness + P.backerFoam;
const sigmaBackerEnd = Math.min(sigmaN, farCornerSigma + 0.5);
const backerPts = sampleSigma(0, sigmaBackerEnd).map((sg) => atSigma(sg).offset(backerGap));
// The offset roof starts at about Z = 0 at the nose. Close the section 1 mm
// below that (a closing edge of ~zero length breaks the solid) and trim at Z = 0 after.
const bStart = backerPts[0];
const bEnd = backerPts[backerPts.length - 1];
const backerSection = sectionSolid([
  backerPts,
  [bEnd, [bEnd[0], -1]],
  [[bEnd[0], -1], [bStart[0], -1]],
  [[bStart[0], -1], bStart],
], Y0, Y1).intersect(box(-5, chord + 5, Y0 - 1, Y1 + 1, 0, zTop));
if (!(replicad.measureVolume(backerSection) > 0)) throw new Error('backer section is empty');
// Its sides follow the channel edges; it starts just past the peel line (the
// straight plan segment between the two edge points there) so the cable part
// of the strip, round the nose, has no backer under it.
const backerA = offsetPolyline(bandEdge(-cavityWidth / 2, uPeel + P.backerPeelGap, uEnd + 6), P.backerSideClearance);
const backerB = offsetPolyline(bandEdge(cavityWidth / 2, uPeel + P.backerPeelGap, uEnd + 6), -P.backerSideClearance).reverse();
const backerSides = planSolid([backerA, [backerA[backerA.length - 1], backerB[0]], backerB, [backerB[backerB.length - 1], backerA[0]]], zBot, zTop);
const backer = backerSection.intersect(backerSides)
  .intersect(tailSideOf(uEnd - P.backerEndGap, zBot, zTop));
await freeMemory();
{
  const v = replicad.measureVolume(backer);
  console.log(`backer volume ${(v / 1000).toFixed(1)} cm^3`);
  if (!(v > 1000)) throw new Error('backer came out empty');
}

// Fit-check dummies.
step('dummies');
const flexSigma = [P.peelSigma - (P.flexWidth / 2) * sn, Math.min(sigmaN, dev(P.flexLength, -P.flexWidth / 2).sigma + 0.5)];
const flexTop = sampleSigma(flexSigma[0], flexSigma[1], flexSigma[0] + 12).map((sg) => atSigma(sg).offset(0.002));
const flexBottom = sampleSigma(flexSigma[0], flexSigma[1], flexSigma[0] + 12).map((sg) => atSigma(sg).offset(0.002 + P.flexThickness)).reverse();
const flex = sectionSolid([
  flexTop,
  [flexTop[flexTop.length - 1], flexBottom[0]],
  flexBottom,
  [flexBottom[flexBottom.length - 1], flexTop[0]],
], Y0, Y1).intersect(bandPrism(P.flexWidth / 2, uPeel, P.flexLength, zBot, zTop, 0.002 + P.flexThickness / 2));
const parts = [];
for (const m of mics) {
  parts.push({ name: `mic${m.mic}`, shape: localBox(m.centre, [-P.micBody[0] / 2, -P.micBody[1] / 2, 0], [P.micBody[0] / 2, P.micBody[1] / 2, P.micHeight]) });
  for (const cap of capPockets) {
    const half = (cap.xf[1] - cap.xf[0]) / 2;
    parts.push({ name: `mic${m.mic}_${cap.name}`, shape: localBox(dev(micU[m.mic] - cap.center, 0), [-half, -P.capHalfWidth, 0], [half, P.capHalfWidth, cap.h]) });
  }
}
const boardDummy = [
  { name: 'board_pcb', shape: box(boardX, boardXEnd, boardY0, boardY1, -B.t, 0) },
  { name: 'board_parts', shape: box(boardX, boardXEnd, boardY0, boardY1, -B.t - B.partsBelow, -B.t) },
  { name: 'board_sd_antenna', shape: box(boardXEnd, boardXEnd + B.aftOverhang, boardY0 + 4, boardY1 - 4, -B.t - B.partsBelow, -B.t) },
  // through-hole pins (buttons, connectors, SD header) sit well inside the corner holes
  { name: 'board_back_pins', shape: box(boardX + 6, boardXEnd - 6, boardY0 + 6, boardY1 - 6, 0, B.backPins) },
];
const batteryDummy = box(
  battery.x0 + P.battery.clearance, battery.x1 - P.battery.clearance,
  battery.y0 + P.battery.clearance, battery.y1 - P.battery.clearance,
  battery.zTop - P.battery.clearance - P.battery.t, battery.zTop - P.battery.clearance,
);

// ---------------------------------------------------------------- checks
await freeMemory();
step('checks');
const checks = { interference: {} };
const overlap = async (a, b) => {
  const volume = replicad.measureVolume(a.clone().intersect(b.clone()));
  await freeMemory();
  return volume;
};
{ // positive control: a 1 mm cube inside the top half near the trailing edge
  const cx = 150;
  const cy = boardY0 + 10;
  const control = await overlap(top, box(cx - 0.5, cx + 0.5, cy - 0.5, cy + 0.5, 12, 13));
  if (Math.abs(control - 1) > 1e-3) throw new Error(`interference check is broken (control ${control})`);
}
checks.interference.mics_and_caps = +(await overlap(top, replicad.makeCompound(parts.map((p) => p.shape.clone())))).toFixed(5);
if (checks.interference.mics_and_caps > 0.01) {
  for (const { name, shape } of parts) checks.interference[name] = +(await overlap(top, shape)).toFixed(5);
}
checks.interference.flex = +(await overlap(top, flex)).toFixed(5);
checks.interference.backer_vs_top = +(await overlap(top, backer)).toFixed(5);
checks.interference.backer_vs_flex = +(await overlap(backer, flex)).toFixed(5);
checks.interference.cover_vs_top = +(await overlap(top, cover)).toFixed(5);
checks.interference.cover_vs_backer = +(await overlap(cover, backer)).toFixed(5);
for (const { name, shape } of boardDummy) {
  checks.interference[`${name}_vs_top`] = +(await overlap(top, shape)).toFixed(5);
  checks.interference[`${name}_vs_cover`] = +(await overlap(cover, shape)).toFixed(5);
}
checks.interference.battery_vs_top = +(await overlap(top, batteryDummy)).toFixed(5);
checks.interference.battery_vs_cover = +(await overlap(cover, batteryDummy)).toFixed(5);
step(`checks done, WASM heap ${(oc.wasmMemory.buffer.byteLength / 2 ** 20).toFixed(0)} MB`);
console.log('interference', JSON.stringify(checks.interference));
for (const [name, shape] of [['top', top], ['cover', cover], ['backer', backer]]) {
  try {
    checks[name] = measure(shape);
  } catch (err) {
    console.log(`measure(${name}) failed: ${err}`);
  }
}
step('gap');

// Print-in-place gap between the backer and the top half, from the meshes
// (OpenCascade's shape-to-shape distance throws on a part this size).
function closestOnTriangle(p, a, b, c) { // Ericson, Real-Time Collision Detection 5.1.5
  const sub = (u, v) => [u[0] - v[0], u[1] - v[1], u[2] - v[2]];
  const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const add = (u, v, s) => [u[0] + v[0] * s, u[1] + v[1] * s, u[2] + v[2] * s];
  const ab = sub(b, a);
  const ac = sub(c, a);
  const ap = sub(p, a);
  const d1 = dot(ab, ap);
  const d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return a;
  const bp = sub(p, b);
  const d3 = dot(ab, bp);
  const d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return b;
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return add(a, ab, d1 / (d1 - d3));
  const cp = sub(p, c);
  const d5 = dot(ab, cp);
  const d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return c;
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return add(a, ac, d2 / (d2 - d6));
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) return add(b, sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)));
  const denom = 1 / (va + vb + vc);
  return add(add(a, ab, vb * denom), ac, vc * denom);
}
// Smallest distance from points of one mesh to triangles of the other, up to maxDist.
function pointsToMesh(points, mesh, maxDist, cell = 4) {
  const V = mesh.vertices;
  const T = mesh.triangles;
  const pmin = [Infinity, Infinity, Infinity];
  const pmax = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < points.length; i += 3) {
    for (let k = 0; k < 3; k += 1) {
      pmin[k] = Math.min(pmin[k], points[i + k]);
      pmax[k] = Math.max(pmax[k], points[i + k]);
    }
  }
  const key = (i, j, k) => `${i},${j},${k}`;
  const grid = new Map();
  for (let t = 0; t < T.length; t += 3) {
    const ia = T[t] * 3;
    const ib = T[t + 1] * 3;
    const ic = T[t + 2] * 3;
    const lo = [0, 1, 2].map((k) => Math.min(V[ia + k], V[ib + k], V[ic + k]) - maxDist);
    const hi = [0, 1, 2].map((k) => Math.max(V[ia + k], V[ib + k], V[ic + k]) + maxDist);
    if (lo.some((v, k) => v > pmax[k]) || hi.some((v, k) => v < pmin[k])) continue;
    const c0 = lo.map((v, k) => Math.floor(Math.max(v, pmin[k] - cell) / cell));
    const c1 = hi.map((v, k) => Math.floor(Math.min(v, pmax[k] + cell) / cell));
    for (let i = c0[0]; i <= c1[0]; i += 1) {
      for (let j = c0[1]; j <= c1[1]; j += 1) {
        for (let k = c0[2]; k <= c1[2]; k += 1) {
          const kk = key(i, j, k);
          if (!grid.has(kk)) grid.set(kk, []);
          grid.get(kk).push(t);
        }
      }
    }
  }
  let best = maxDist;
  for (let i = 0; i < points.length; i += 3) {
    const p = [points[i], points[i + 1], points[i + 2]];
    const list = grid.get(key(...p.map((v) => Math.floor(v / cell))));
    if (!list) continue;
    for (const t of list) {
      const a = [V[T[t] * 3], V[T[t] * 3 + 1], V[T[t] * 3 + 2]];
      const b = [V[T[t + 1] * 3], V[T[t + 1] * 3 + 1], V[T[t + 1] * 3 + 2]];
      const c = [V[T[t + 2] * 3], V[T[t + 2] * 3 + 1], V[T[t + 2] * 3 + 2]];
      const q = closestOnTriangle(p, a, b, c);
      best = Math.min(best, Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]));
    }
  }
  return best;
}
await freeMemory();
const GAP_MESH = { tolerance: 0.005, angularTolerance: 0.05 };
const topMesh = weldMesh(meshShape(top, GAP_MESH));
const backerMesh = weldMesh(meshShape(backer, GAP_MESH));
checks.backerPrintGap = +Math.min(
  pointsToMesh(backerMesh.vertices, topMesh, 1.5),
  pointsToMesh(topMesh.vertices, backerMesh, 1.5),
).toFixed(3);
console.log(`backer-to-top gap ${checks.backerPrintGap} mm`);
if (checks.backerPrintGap < P.minPrintGap) throw new Error('backer too close to the top half to print in place');
const worst = Math.max(...Object.values(checks.interference));
checks.maxInterference = worst;
console.log(`max interference ${worst.toFixed(5)} mm^3`);
if (worst > 0.01) {
  console.log(checks.interference);
  throw new Error('parts collide');
}

// ---------------------------------------------------------------- export
async function writeBlob(filename, blob) {
  fs.writeFileSync(filename, Buffer.from(await blob.arrayBuffer()));
}
const MESH = { tolerance: 0.01, angularTolerance: 0.1 };
function meshShape(shape, { tolerance, angularTolerance }) {
  const rawMesh = oc.ReplicadMeshExtractor.extract(shape.wrapped, tolerance, angularTolerance, false);
  const { buffer } = oc.wasmMemory;
  const vp = (rawMesh.getVerticesPtr() >>> 0) / 4;
  const tp = (rawMesh.getTrianglesPtr() >>> 0) / 4;
  const vertices = Array.from(new Float32Array(buffer).subarray(vp, vp + rawMesh.getVerticesSize()));
  const triangles = Array.from(new Uint32Array(buffer).subarray(tp, tp + rawMesh.getTrianglesSize()));
  rawMesh.delete();
  return { vertices, triangles };
}
const BED = { size: 256, exclude: [[0, 0], [18, 28]], margin: 5 };
function convexHull(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lowerH = [];
  for (const p of pts) {
    while (lowerH.length >= 2 && cross(lowerH[lowerH.length - 2], lowerH[lowerH.length - 1], p) <= 0) lowerH.pop();
    lowerH.push(p);
  }
  const upperH = [];
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    const p = pts[i];
    while (upperH.length >= 2 && cross(upperH[upperH.length - 2], upperH[upperH.length - 1], p) <= 0) upperH.pop();
    upperH.push(p);
  }
  return lowerH.slice(0, -1).concat(upperH.slice(0, -1));
}
const excludeDistance = (x, y) => {
  const [[ex0, ey0], [ex1, ey1]] = BED.exclude;
  return Math.hypot(Math.max(ex0 - x, 0, x - ex1), Math.max(ey0 - y, 0, y - ey1));
};
// Merge shapes into one object, optionally turned over (180 deg about X), rotated
// about Z for the most room on the bed, centred, base on Z = 0.
function bedLayout(shapes, name, flip = false) {
  const v = [];
  const tris = [];
  let triangleCount = 0;
  for (const shape of shapes) {
    const mesh = weldMesh(meshShape(shape, MESH));
    const stats = meshStats(mesh);
    if (!stats.watertight) {
      // Say where: edges not shared by exactly two triangles.
      const count = new Map();
      const T = mesh.triangles;
      for (let t = 0; t < T.length; t += 3) {
        for (const [a, b] of [[T[t], T[t + 1]], [T[t + 1], T[t + 2]], [T[t + 2], T[t]]]) {
          const k = a < b ? `${a},${b}` : `${b},${a}`;
          count.set(k, (count.get(k) ?? 0) + 1);
        }
      }
      const V = mesh.vertices;
      const bad = [...count].filter(([, n]) => n !== 2).slice(0, 20).map(([k, n]) => {
        const [a, b] = k.split(',').map(Number);
        return `${n}x @ (${[0, 1, 2].map((i) => ((V[a * 3 + i] + V[b * 3 + i]) / 2).toFixed(1)).join(', ')})`;
      });
      throw new Error(`${name} mesh is not watertight: ${JSON.stringify(stats)}; bad edges: ${bad.join('; ')}`);
    }
    const offset = v.length / 3;
    for (let i = 0; i < mesh.vertices.length; i += 3) {
      const [x, y, z] = [mesh.vertices[i], mesh.vertices[i + 1], mesh.vertices[i + 2]];
      if (flip) v.push(x, -y, -z);
      else v.push(x, y, z);
    }
    for (const t of mesh.triangles) tris.push(t + offset);
    triangleCount += stats.triangleCount;
  }
  const xy = [];
  for (let i = 0; i < v.length; i += 3) xy.push([v[i], v[i + 1]]);
  const hull = convexHull(xy);
  let best = null;
  for (let deg = 0; deg < 360; deg += 0.5) {
    const a = (deg * Math.PI) / 180;
    const [c, s] = [Math.cos(a), Math.sin(a)];
    const r = hull.map(([x, y]) => [c * x - s * y, s * x + c * y]);
    const xs = r.map((p) => p[0]);
    const ys = r.map((p) => p[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const shift = [BED.size / 2 - (x0 + x1) / 2, BED.size / 2 - (y0 + y1) / 2];
    const edgeGap = Math.min(BED.size - (x1 - x0), BED.size - (y1 - y0)) / 2;
    const excludeGap = Math.min(...r.map(([x, y]) => excludeDistance(x + shift[0], y + shift[1])));
    const score = Math.min(edgeGap, excludeGap);
    if (!best || score > best.score + 1e-9) best = { deg, c, s, shift, score };
  }
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < v.length; i += 3) {
    const [x, y] = [v[i], v[i + 1]];
    v[i] = best.c * x - best.s * y + best.shift[0];
    v[i + 1] = best.s * x + best.c * y + best.shift[1];
    for (let a = 0; a < 3; a += 1) {
      min[a] = Math.min(min[a], v[i + a]);
      max[a] = Math.max(max[a], v[i + a]);
    }
  }
  for (let i = 2; i < v.length; i += 3) v[i] -= min[2];
  let edgeGap = Infinity;
  let excludeGap = Infinity;
  for (let i = 0; i < v.length; i += 3) {
    const [x, y] = [v[i], v[i + 1]];
    edgeGap = Math.min(edgeGap, x, y, BED.size - x, BED.size - y);
    excludeGap = Math.min(excludeGap, excludeDistance(x, y));
  }
  if (edgeGap < BED.margin || excludeGap < BED.margin) {
    throw new Error(`${name} too close to the bed edge (${edgeGap.toFixed(1)} mm) or no-print zone (${excludeGap.toFixed(1)} mm)`);
  }
  return {
    object: { name, vertices: v, triangles: tris },
    rotationDeg: best.deg,
    footprint: [max[0] - min[0], max[1] - min[1]],
    height: max[2] - min[2],
    triangles: triangleCount,
    edgeGap: +edgeGap.toFixed(1),
    excludeGap: +excludeGap.toFixed(1),
  };
}

await freeMemory();
step(`mesh + bed layout, WASM heap ${(oc.wasmMemory.buffer.byteLength / 2 ** 20).toFixed(0)} MB`);
const topBed = bedLayout([top, backer], 'wing_top_with_backer');
const coverBed = bedLayout([cover], 'wing_cover', true);
fs.writeFileSync(path.join(outDir, 'MMSA_wing_4415_top_print.3mf'), buildThreeMf('MMSA NACA 4415 wing - top half + backer (printed in place)', [topBed.object]));
fs.writeFileSync(path.join(outDir, 'MMSA_wing_4415_cover_print.3mf'), buildThreeMf('MMSA NACA 4415 wing - cover', [coverBed.object]));
const bedSummary = (b) => ({
  rotationDeg: b.rotationDeg,
  footprint: b.footprint.map((x) => +x.toFixed(1)),
  height: +b.height.toFixed(2),
  triangles: b.triangles,
  edgeGap: b.edgeGap,
  noPrintZoneGap: b.excludeGap,
});
checks.print = { top: bedSummary(topBed), cover: bedSummary(coverBed) };

await writeBlob(path.join(outDir, 'MMSA_wing_4415.step'), replicad.exportSTEP([
  { shape: top, name: 'wing_top', color: '#c8c8c8' },
  { shape: backer, name: 'flex_backer', color: '#3b7dd8' },
  { shape: cover, name: 'wing_cover', color: '#9a9a9a' },
]));
await writeBlob(path.join(refDir, 'MMSA_wing_4415_fitcheck.step'), replicad.exportSTEP([
  { shape: top, name: 'wing_top', color: '#c8c8c8', alpha: 0.5 },
  { shape: backer, name: 'flex_backer', color: '#3b7dd8' },
  { shape: cover, name: 'wing_cover', color: '#9a9a9a', alpha: 0.5 },
  { shape: flex, name: 'flex_strip', color: '#e0b000' },
  ...parts.map(({ name, shape }) => ({ shape, name, color: name.includes('_C') ? '#8b5a2b' : '#202020' })),
  ...boardDummy.map(({ name, shape }) => ({ shape, name, color: '#2e9a4a' })),
  { shape: batteryDummy, name: 'battery', color: '#7b3fa0' },
]));
await writeBlob(path.join(refDir, 'top.stl'), top.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'cover.stl'), cover.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'backer.stl'), backer.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'flex.stl'), flex.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'parts.stl'), replicad.makeCompound(parts.map((p) => p.shape)).blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'board.stl'), replicad.makeCompound(boardDummy.map((p) => p.shape)).blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'battery.stl'), batteryDummy.blobSTL({ ...MESH, binary: true }));

summary.labels = labels;
summary.checks = checks;
fs.writeFileSync(path.join(refDir, 'wing_design.json'), `${JSON.stringify(summary, null, 2)}\n`);
console.log('print', JSON.stringify(checks.print));
console.log('wrote', outDir);
