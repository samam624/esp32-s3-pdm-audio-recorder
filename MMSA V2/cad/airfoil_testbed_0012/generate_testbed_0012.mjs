/**
 * MMSA airfoil mic-port test bed, NACA 0012 (superseded by ../airfoil_testbed_4415).
 *
 * A 30 mm wide slice of the NACA 0012 upper surface (304.8 mm chord, same as
 * "Air Foil NACA 0012.step") sitting on a flat 4 mm base. The mic flex goes in
 * from below, components up, and each mic presses into its own pocket under a
 * port hole. Prints base-down with no supports; the backer prints in place
 * inside the channel on the same plate. Each of the 8 ports has a different hole diameter D and skin
 * depth d (skin over the mic lid = hole length), so one print tests 8 port
 * geometries at once. The whole top gets one Monokote wrap.
 *
 * Flex data: "Flex Array_PCB.step" (port positions, parts) and the JLC order
 * (0.11 mm 2-layer flex, 0.225 mm PI stiffener under the connector fingers).
 * mic0 is the end nearest the FPC tail, so the tail goes at the leading edge
 * and leaves through a slot in the front face.
 *
 * Writes output/:
 *   MMSA_testbed_0012_print.3mf                    block + backer on one 256 mm bed plate (the print)
 *   MMSA_testbed_0012.step                         block + backer, opens in Fusion 360
 *   reference/MMSA_testbed_0012_backer_only.3mf    spare backer
 *   reference/MMSA_testbed_0012_fitcheck.step      adds a dummy flex, mics and caps
 *   reference/*.stl, reference/testbed_design.json          for preview_testbed.py and the README
 *
 * Run:  node generate_testbed.mjs        (add --dry to print the layout only)
 * Needs replicad + replicad-opencascadejs. Set REPLICAD_NODE_MODULES if they
 * are not at the default path below.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { buildThreeMf, meshStats, weldMesh } from './threemf.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(here, 'output');
const refDir = path.join(outDir, 'reference');
const DRY = process.argv.includes('--dry');

// ---------------------------------------------------------------- parameters (mm)
const P = {
  chord: 304.8,
  span: 30.0, // block width: 7.7 mm walls each side of the flex channel; on the diagonal it leaves room for a brim
  baseDepth: 4.0, // flat base below the chord line (the tail slot is 3 mm tall)

  // Flex, from Flex Array_PCB.step. xf runs along the strip, 0 at the mic7 end,
  // 300 at the tail end. yf runs across it, 0..14, centre 7.
  flexWidth: 14.0,
  flexThickness: 0.11, // JLC order (the KiCad STEP shows 0.411)
  portXf: [284, 245, 204, 165, 125, 84, 45, 4], // mic0..mic7 (port = package centre along xf)
  portYfOffset: 0.78, // port sits 0.78 mm off the package centre toward +yf
  micHeight: 1.1, // CAD body incl. solder; datasheet H = 1.00 +/- 0.1
  micBody: [3.0, 4.28], // along xf, across (CAD lid outline 4.28; datasheet 3 x 4)
  lidHalfWidth: 2.0, // datasheet W/2, used to keep big holes on the lid
  cap10u: { xf: [3.28, 4.72], h: 1.4 }, // relative to the mic centre, both caps at yf 6.4..7.6
  cap100n: { xf: [6.28, 7.72], h: 1.0 },
  capHalfWidth: 0.6,

  // Placement: arc length along the flex (pocket roof line) from the leading
  // edge to the mic0 port. 16 mm of strip lies forward of mic0.
  mic0PortSigma: 17.0,

  // Fits
  channelClearance: 0.3, // per side, flex in the channel
  micPocketClearance: 0.15, // per side
  gasket: 0.10, // thin double-sided tape between the mic lid and the pocket roof
  pocketLeadIn: 0.3, // 45 deg chamfer at each mic pocket's mouth so the mics find their pockets
  capMargin: 0.48, // around cap bodies (pads, fillets, placement)
  capHeadroom: 0.15,
  minSkin: 0.4, // a cap pocket with less skin than this is opened through the top
  // The 10 uF cap is 0.3 mm taller than the mic, so its skin is d - 0.35 mm.
  // d >= 0.8 keeps every cap pocket closed under >= 0.45 mm.
  holeLidMargin: 0.35, // keep the hole edge this far inside the lid edge
  plateauMargin: 1.5, // flat roof beyond each mic's pockets before the depth ramps
  cavityEndClearance: 1.5,
  frontSlotTop: -1.0, // tail exit slot through the front face, from the sill up to this z
  frontSlotSill: 0.6, // keeps the block's first layer a closed ring, so a slicer brim can't run into the channel

  // Backer: printed in place inside the channel (same plate), then pushed out,
  // fitted with foam tape and pushed back to hold the flex up from below.
  backerFoam: 1.0, // gap for ~1 mm foam mounting tape between backer and flex
  backerSideClearance: 0.4, // print-in-place gap to the channel walls
  backerEndGap: 1.0,
  minPrintGap: 0.35, // build fails if the backer comes closer than this to the block

  labelFont: 'C:/Windows/Fonts/arialbd.ttf',
  labelSize: 2.6,
  labelDepth: 0.4,
};

// Port variants, one per mic. D = hole diameter, d = skin over the mic lid.
// 3 x 3 grid minus the deepest-smallest corner, spread along the chord.
const VARIANTS = [
  { D: 2.0, d: 1.1 }, // mic0
  { D: 2.4, d: 1.4 }, // mic1
  { D: 1.6, d: 0.8 }, // mic2
  { D: 2.0, d: 1.4 }, // mic3
  { D: 2.4, d: 0.8 }, // mic4
  { D: 1.6, d: 1.1 }, // mic5
  { D: 2.4, d: 1.1 }, // mic6
  { D: 2.0, d: 0.8 }, // mic7
];

// ---------------------------------------------------------------- airfoil geometry
// Upper surface, parametrised by beta in [0, pi]: x/c = (1 - cos beta) / 2.
// X chordwise from the leading edge, Z up, Y spanwise. n is the outward normal.
// Closed (sharp) trailing edge, x^4 coefficient -0.1036 instead of the standard
// -0.1015: this is what "Air Foil NACA 0012.step" uses (its trailing edge is a
// single edge at z = 0; checked 2026-10-30, see README).
const A4 = -0.1036;
function naca(beta) {
  const xc = (1 - Math.cos(beta)) / 2;
  const yt = 0.6 * (0.2969 * Math.sqrt(xc) - 0.1260 * xc - 0.3516 * xc ** 2 + 0.2843 * xc ** 3 + A4 * xc ** 4);
  const dx = (P.chord / 2) * Math.sin(beta);
  const dz = P.chord * 0.6 * (0.2969 * 0.5 * Math.cos(beta / 2)
    + (-0.1260 - 2 * 0.3516 * xc + 3 * 0.2843 * xc ** 2 + 4 * A4 * xc ** 3) * Math.sin(beta) / 2);
  const len = Math.hypot(dx, dz);
  const t = [dx / len, dz / len];
  return { x: P.chord * xc, z: P.chord * yt, n: [-t[1], t[0]] };
}

const N = 20000;
const grid = Array.from({ length: N + 1 }, (_, k) => naca((Math.PI * k) / N));
const sOuter = new Float64Array(N + 1);
for (let k = 1; k <= N; k += 1) {
  sOuter[k] = sOuter[k - 1] + Math.hypot(grid[k].x - grid[k - 1].x, grid[k].z - grid[k - 1].z);
}

// Pocket roof line ("ceiling"): the flex top surface. It sits C below the
// outer surface, with C = d + mic height + gasket, flat over each mic's
// pockets and blended smoothly between mics.
const portSigma = P.portXf.map((xf) => P.mic0PortSigma + (P.portXf[0] - xf));
const micPocketHalf = P.micBody[0] / 2 + P.micPocketClearance;
const capPocketEnd = P.cap100n.xf[1] + P.capMargin; // furthest cap pocket edge from the mic centre
const roofDepth = VARIANTS.map(({ d }) => d + P.micHeight + P.gasket);
const plateau = portSigma.map((sg) => [sg - capPocketEnd - P.plateauMargin, sg + micPocketHalf + P.plateauMargin]);

function depthAtSigma(sigma) {
  if (sigma <= plateau[0][1]) return roofDepth[0];
  for (let i = 0; i < VARIANTS.length - 1; i += 1) {
    const a = plateau[i][1];
    const b = plateau[i + 1][0];
    if (sigma <= a) return roofDepth[i];
    if (sigma < b) {
      const w = (1 - Math.cos((Math.PI * (sigma - a)) / (b - a))) / 2;
      return roofDepth[i] + (roofDepth[i + 1] - roofDepth[i]) * w;
    }
  }
  return roofDepth[VARIANTS.length - 1];
}

// C depends on arc length along the roof line, which depends on C: iterate.
const C = new Float64Array(N + 1).fill(roofDepth[0]);
const sigma = new Float64Array(N + 1);
function roofArcLength() {
  let px = grid[0].x - C[0] * grid[0].n[0];
  let pz = grid[0].z - C[0] * grid[0].n[1];
  for (let k = 1; k <= N; k += 1) {
    const qx = grid[k].x - C[k] * grid[k].n[0];
    const qz = grid[k].z - C[k] * grid[k].n[1];
    sigma[k] = sigma[k - 1] + Math.hypot(qx - px, qz - pz);
    if (sigma[k] <= sigma[k - 1]) throw new Error(`roof line folds back at k=${k}`);
    px = qx;
    pz = qz;
  }
}
for (let iteration = 0; iteration < 20; iteration += 1) {
  roofArcLength();
  let change = 0;
  for (let k = 0; k <= N; k += 1) {
    const next = depthAtSigma(sigma[k]);
    change = Math.max(change, Math.abs(next - C[k]));
    C[k] = next;
  }
  if (change < 1e-9) break;
}
roofArcLength();

// Everything below is placed by sigma (arc length along the roof line).
function atSigma(target) {
  if (target < 0 || target > sigma[N]) throw new Error(`sigma ${target} outside 0..${sigma[N]}`);
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
  const c = lerp(C[lo], C[hi]);
  return {
    x, z, n, c,
    t: [n[1], -n[0]], // tangent, pointing aft
    s: lerp(sOuter[lo], sOuter[hi]),
    roof: [x - c * n[0], z - c * n[1]],
    offset: (extra) => [x - (c + extra) * n[0], z - (c + extra) * n[1]],
  };
}

const sigmaStripStart = portSigma[0] - (300 - P.portXf[0]); // tail-end edge of the strip
const sigmaStripEnd = portSigma[7] + P.portXf[7]; // mic7-end edge of the strip
const sigmaCavityEnd = sigmaStripEnd + P.cavityEndClearance;
if (sigmaStripStart < 0) throw new Error('strip runs past the leading edge; raise mic0PortSigma');
if (sigmaCavityEnd > sigma[N] - 2) throw new Error('strip runs off the trailing edge; lower mic0PortSigma');

// Span positions. The flex lies components-up with xf pointing forward, so
// +yf maps to -Y: the ports sit at Y = -0.78.
const portY = -P.portYfOffset;
const holeY = VARIANTS.map(({ D }) => -Math.min(P.portYfOffset, P.lidHalfWidth - P.holeLidMargin - D / 2));

const capPockets = [
  { name: 'C10u', ...P.cap10u },
  { name: 'C100n', ...P.cap100n },
].map((cap) => ({
  ...cap,
  center: (cap.xf[0] + cap.xf[1]) / 2, // distance forward of the mic centre
  half: (cap.xf[1] - cap.xf[0]) / 2 + P.capMargin,
  pocketHeight: cap.h + P.capHeadroom,
}));

const mics = VARIANTS.map((variant, i) => {
  const port = atSigma(portSigma[i]);
  const slope = (Math.atan2(port.n[0], port.n[1]) * -180) / Math.PI; // surface angle, + = rising aft
  const caps = capPockets.map((cap) => {
    const skin = roofDepth[i] - cap.pocketHeight;
    return { name: cap.name, skin: +skin.toFixed(3), openThroughTop: skin < P.minSkin };
  });
  return {
    mic: i,
    flexX: P.portXf[i],
    D: variant.D,
    d: variant.d,
    roofDepth: +roofDepth[i].toFixed(3),
    portX: +port.x.toFixed(2),
    portXOverC: +(port.x / P.chord).toFixed(3),
    surfaceArc: +port.s.toFixed(2),
    surfaceZ: +port.z.toFixed(2),
    surfaceSlopeDeg: +slope.toFixed(1),
    roofZ: +port.roof[1].toFixed(2),
    holeY: +holeY[i].toFixed(2),
    portY,
    caps,
  };
});

const lePoint = atSigma(0);
const tePoint = atSigma(sigmaCavityEnd);
const summary = {
  generated: new Date().toISOString(),
  units: 'mm',
  frame: 'X chordwise from the leading edge, Y spanwise (block centred), Z up; chord line at Z = 0, base bottom at Z = -baseDepth',
  parameters: P,
  outerArcLength: +sOuter[N].toFixed(2),
  roofArcLength: +sigma[N].toFixed(2),
  stripOnRoof: { start: +sigmaStripStart.toFixed(2), end: +sigmaStripEnd.toFixed(2) },
  cavity: { frontX: +lePoint.roof[0].toFixed(2), endX: +tePoint.roof[0].toFixed(2), width: P.flexWidth + 2 * P.channelClearance },
  mics,
};

console.log(`outer arc ${summary.outerArcLength} mm, roof arc ${summary.roofArcLength} mm`);
console.log(`strip on roof: sigma ${summary.stripOnRoof.start}..${summary.stripOnRoof.end}; cavity x ${summary.cavity.frontX}..${summary.cavity.endX}`);
for (const m of mics) {
  const caps = m.caps.map((c) => `${c.name} skin ${c.skin}${c.openThroughTop ? ' OPEN' : ''}`).join(', ');
  console.log(`mic${m.mic}: x/c ${m.portXOverC} (x ${m.portX}), slope ${m.surfaceSlopeDeg} deg, D ${m.D} d ${m.d}, roof z ${m.roofZ}, hole y ${m.holeY}; ${caps}`);
}
if (DRY) process.exit(0);

// ---------------------------------------------------------------- CAD
fs.mkdirSync(refDir, { recursive: true });
const nodeModules = process.env.REPLICAD_NODE_MODULES
  ?? 'C:/Users/samca/Desktop/ProjectTreebeard/MSV3/hardware/MSV3_Probe_PCB_Enclosure/tools/node/node_modules';
const load = (rel) => import(pathToFileURL(path.join(nodeModules, rel)).href);
const replicad = await load('replicad/dist/replicad.js');
const { default: opencascade } = await load('replicad-opencascadejs/dist/replicad_single.js');
replicad.setOC(await opencascade({
  locateFile: () => path.join(nodeModules, 'replicad-opencascadejs/dist/replicad_single.wasm'),
}));

const BSPLINE = { tolerance: 0.002, degMin: 3, degMax: 8 };

// Closed XZ profile at Y = y0 from a chain of segments (each a list of [x, z];
// more than 2 points = B-spline, 2 points = line), extruded `width` along +Y.
function profileSolid(chain, y0, width) {
  const splines = chain.map((seg) => (seg.length > 2
    ? replicad.makeBSplineApproximation(seg.map(([x, z]) => [x, y0, z]), BSPLINE)
    : null));
  const ends = chain.map((seg, i) => {
    if (!splines[i]) return [[seg[0][0], y0, seg[0][1]], [seg[1][0], y0, seg[1][1]]];
    const a = splines[i].startPoint;
    const b = splines[i].endPoint;
    const want = [seg[0], seg[seg.length - 1]];
    for (const [got, [x, z]] of [[a, want[0]], [b, want[1]]]) {
      if (Math.hypot(got.x - x, got.z - z) > 1e-4) throw new Error('B-spline missed its end point');
    }
    return [[a.x, a.y, a.z], [b.x, b.y, b.z]];
  });
  chain.forEach((_, i) => { // snap lines onto neighbouring spline ends
    if (splines[i]) return;
    const prev = (i + chain.length - 1) % chain.length;
    const next = (i + 1) % chain.length;
    if (splines[prev]) ends[i][0] = ends[prev][1];
    if (splines[next]) ends[i][1] = ends[next][0];
  });
  const edges = chain.map((_, i) => splines[i] ?? replicad.makeLine(ends[i][0], ends[i][1]));
  const face = replicad.makeFace(replicad.assembleWire(edges));
  return replicad.basicFaceExtrusion(face, new replicad.Vector([0, width, 0]));
}

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

// A box in the local frame at roof position sigma (t aft along the roof, y
// spanwise, n outward), placed in the world frame.
function localBox(sg, [t0, y0, n0], [t1, y1, n1]) {
  const f = atSigma(sg);
  const phi = (Math.atan2(f.t[1], f.t[0]) * 180) / Math.PI;
  return replicad.makeBox([t0, y0, n0], [t1, y1, n1])
    .rotate(-phi, [0, 0, 0], [0, 1, 0])
    .translate([f.roof[0], 0, f.roof[1]]);
}

// 45-degree lead-in at a pocket mouth: a frustum `lead` wider per side at the
// roof (n = 0) that meets the pocket walls at n = lead. It starts below the
// roof, in the open channel, so the cut is clean.
function leadIn(sg, halfT, halfY, lead) {
  const f = atSigma(sg);
  const phi = (Math.atan2(f.t[1], f.t[0]) * 180) / Math.PI;
  const below = 0.6;
  const rect = (ht, hy, n) => replicad.makePolygon([[-ht, -hy, n], [ht, -hy, n], [ht, hy, n], [-ht, hy, n]]).outerWire();
  return replicad.loft([
    rect(halfT + lead + below, halfY + lead + below, -below),
    rect(halfT, halfY, lead),
  ], { ruled: true })
    .rotate(-phi, [0, 0, 0], [0, 1, 0])
    .translate([f.roof[0], 0, f.roof[1]]);
}

function measure(shape) {
  const [min, max] = shape.boundingBox.bounds;
  return { min, max, volume: replicad.measureVolume(shape) };
}

const B = P.baseDepth;
const nose = naca(0);
const tail = naca(Math.PI);

// Block: upper surface on a flat base.
const outerPts = Array.from({ length: 301 }, (_, j) => {
  const g = naca((Math.PI * j) / 300);
  return [g.x, g.z];
});
let block = profileSolid([
  outerPts,
  [[tail.x, tail.z], [P.chord, -B]],
  [[P.chord, -B], [0, -B]],
  [[0, -B], [nose.x, nose.z]],
], -P.span / 2, P.span);

// Rotation sanity check: a box 1 mm along t must move along the roof tangent.
{
  const f = atSigma(portSigma[0]);
  const probe = localBox(portSigma[0], [0.5, -0.1, -0.1], [1.5, 0.1, 0.1]).boundingBox.center;
  const want = [f.roof[0] + f.t[0], f.roof[1] + f.t[1]];
  if (Math.hypot(probe[0] - want[0], probe[2] - want[1]) > 0.02) {
    throw new Error(`local frame rotation is wrong: got ${probe}, want ${want}`);
  }
}

// Flex channel, open at the bottom, with the tail slot through the front face.
const cavityWidth = P.flexWidth + 2 * P.channelClearance;
const roofPts = sampleSigma(0, sigmaCavityEnd).map((sg) => atSigma(sg).roof);
const roofStart = roofPts[0];
const roofEnd = roofPts[roofPts.length - 1];
const cavity = profileSolid([
  roofPts,
  [roofEnd, [roofEnd[0], -B - 1]],
  [[roofEnd[0], -B - 1], [roofStart[0], -B - 1]],
  [[roofStart[0], -B - 1], [roofStart[0], -B + P.frontSlotSill]],
  [[roofStart[0], -B + P.frontSlotSill], [-1, -B + P.frontSlotSill]],
  [[-1, -B + P.frontSlotSill], [-1, P.frontSlotTop]],
  [[-1, P.frontSlotTop], [roofStart[0], P.frontSlotTop]],
  [[roofStart[0], P.frontSlotTop], roofStart],
], -cavityWidth / 2, cavityWidth);
block = block.cut(cavity);

// Mic pockets, port holes, cap pockets.
const tools = [];
mics.forEach((m, i) => {
  const sg = portSigma[i];
  const C0 = roofDepth[i];
  const micPocketTop = P.micHeight + P.gasket;
  const halfY = P.micBody[1] / 2 + P.micPocketClearance;
  tools.push(localBox(sg, [-micPocketHalf, -halfY, -0.6], [micPocketHalf, halfY, micPocketTop]));
  tools.push(leadIn(sg, micPocketHalf, halfY, P.pocketLeadIn));

  const f = atSigma(sg);
  const start = micPocketTop - 0.05;
  tools.push(replicad.makeCylinder(
    m.D / 2,
    C0 - start + 1.5,
    [f.roof[0] + f.n[0] * start, m.holeY, f.roof[1] + f.n[1] * start],
    [f.n[0], 0, f.n[1]],
  ));

  capPockets.forEach((cap, j) => {
    const top = m.caps[j].openThroughTop ? C0 + 1.5 : cap.pocketHeight;
    const halfW = P.capHalfWidth + P.capMargin;
    tools.push(localBox(sg - cap.center, [-cap.half, -halfW, -0.6], [cap.half, halfW, top]));
  });
});
for (const tool of tools) block = block.cut(tool);

// Labels on the -Y side face (reads left to right with the leading edge on the left).
const fontBytes = fs.readFileSync(P.labelFont);
await replicad.loadFont(fontBytes.buffer.slice(fontBytes.byteOffset, fontBytes.byteOffset + fontBytes.byteLength), 'label');
function engrave(text, xCenter, zCenter) {
  const drawing = replicad.drawText(text, { fontSize: P.labelSize, fontFamily: 'label' });
  const [[x0, z0], [x1, z1]] = drawing.boundingBox.bounds;
  return drawing
    .translate(xCenter - (x0 + x1) / 2, zCenter - (z0 + z1) / 2)
    .sketchOnPlane('XZ', [0, -P.span / 2 - 0.2, 0])
    .extrude(P.labelDepth + 0.2, { extrusionDirection: [0, 1, 0] });
}
const labelZ = -B / 2 - 0.4;
for (const m of mics) {
  block = block.cut(engrave(`${m.mic}: D${m.D.toFixed(1)} d${m.d.toFixed(1)}`, Math.min(Math.max(m.portX, 14), P.chord - 14), labelZ));
}

// Backer: pushes the flex up from below through ~1 mm of foam tape.
const backerWidth = cavityWidth - 2 * P.backerSideClearance;
const backerGap = P.flexThickness + P.backerFoam;
const backerPts = sampleSigma(0, sigmaCavityEnd - P.backerEndGap).map((sg) => atSigma(sg).offset(backerGap));
const bStart = backerPts[0];
const bEnd = backerPts[backerPts.length - 1];
const backer = profileSolid([
  backerPts,
  [bEnd, [bEnd[0], -B]],
  [[bEnd[0], -B], [bStart[0], -B]],
  [[bStart[0], -B], bStart],
], -backerWidth / 2, backerWidth);

// Fit-check dummies: flex strip (curved), mics and caps.
const flexTop = sampleSigma(sigmaStripStart, sigmaStripEnd, sigmaStripStart + 12).map((sg) => atSigma(sg).offset(0.002));
const flexBottom = sampleSigma(sigmaStripStart, sigmaStripEnd, sigmaStripStart + 12).map((sg) => atSigma(sg).offset(0.002 + P.flexThickness)).reverse();
const flex = profileSolid([
  flexTop,
  [flexTop[flexTop.length - 1], flexBottom[0]],
  flexBottom,
  [flexBottom[flexBottom.length - 1], flexTop[0]],
], -P.flexWidth / 2, P.flexWidth);
const parts = [];
mics.forEach((m, i) => {
  const sg = portSigma[i];
  parts.push({ name: `mic${i}`, shape: localBox(sg, [-1.5, -P.micBody[1] / 2, 0], [1.5, P.micBody[1] / 2, P.micHeight]) });
  capPockets.forEach((cap) => {
    const half = (cap.xf[1] - cap.xf[0]) / 2;
    parts.push({ name: `mic${i}_${cap.name}`, shape: localBox(sg - cap.center, [-half, -P.capHalfWidth, 0], [half, P.capHalfWidth, cap.h]) });
  });
});

// ---------------------------------------------------------------- checks
const checks = { interference: {} };
const overlap = (a, b) => replicad.measureVolume(a.clone().intersect(b.clone()));
// Positive control: a 1 x 4 x 1 mm box in the solid tail of the block must read 4 mm^3.
const control = overlap(block, replicad.makeBox([302, -2, -P.baseDepth + 1], [303, 2, -P.baseDepth + 2]));
if (Math.abs(control - 4) > 1e-3) throw new Error(`interference check is broken (control ${control})`);
for (const { name, shape } of parts) checks.interference[name] = +overlap(block, shape).toFixed(5);
checks.interference.flex = +overlap(block, flex).toFixed(5);
checks.interference.backer_vs_block = +overlap(block, backer).toFixed(5);
checks.interference.backer_vs_flex = +overlap(backer, flex).toFixed(5);
checks.block = measure(block);
checks.backer = measure(backer);
checks.backerPrintGap = +replicad.measureDistanceBetween(block, backer).toFixed(3);
console.log(`backer-to-block gap ${checks.backerPrintGap} mm`);
if (checks.backerPrintGap < P.minPrintGap) throw new Error('backer too close to the block to print in place');
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

// Same as replicad's Shape.mesh(), but reads the WASM pointers as unsigned.
// After this many booleans the heap is past 2 GB and replicad 1.0.0 reads
// them as negative numbers, which returns garbage vertices and indices.
function meshShape(shape, { tolerance, angularTolerance }) {
  const oc = replicad.getOC();
  const raw = oc.ReplicadMeshExtractor.extract(shape.wrapped, tolerance, angularTolerance, false);
  const { buffer } = oc.wasmMemory;
  const vp = (raw.getVerticesPtr() >>> 0) / 4;
  const tp = (raw.getTrianglesPtr() >>> 0) / 4;
  const vertices = Array.from(new Float32Array(buffer).subarray(vp, vp + raw.getVerticesSize()));
  const triangles = Array.from(new Uint32Array(buffer).subarray(tp, tp + raw.getTrianglesSize()));
  raw.delete();
  return { vertices, triangles };
}

// P1S bed: 256 x 256 mm with a no-print zone at the front-left corner
// (bed_exclude_area in the Bambu profile). Keep 5 mm clear of both for a brim.
const BED = { size: 256, exclude: [[0, 0], [18, 28]], margin: 5 };

// Merge the shapes into one object (keeps the backer in place inside the
// channel), turn -45 degrees about Z so the ends sit in the back-left and
// front-right corners (clear of the front-left no-print zone), centre on the
// bed, base on Z = 0.
function bedLayout(shapes, name) {
  const v = [];
  const tris = [];
  let triangleCount = 0;
  for (const shape of shapes) {
    const mesh = weldMesh(meshShape(shape, MESH));
    const stats = meshStats(mesh);
    if (!stats.watertight) throw new Error(`${name} mesh is not watertight: ${JSON.stringify(stats)}`);
    const offset = v.length / 3;
    for (const x of mesh.vertices) v.push(x);
    for (const t of mesh.triangles) tris.push(t + offset);
    triangleCount += stats.triangleCount;
  }
  const mesh = { triangles: tris };
  const stats = { triangleCount };
  const c = Math.SQRT1_2;
  for (let i = 0; i < v.length; i += 3) {
    const [x, y] = [v[i], v[i + 1]];
    v[i] = c * x + c * y;
    v[i + 1] = -c * x + c * y;
  }
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < v.length; i += 3) {
    for (let a = 0; a < 3; a += 1) {
      min[a] = Math.min(min[a], v[i + a]);
      max[a] = Math.max(max[a], v[i + a]);
    }
  }
  const shift = [128 - (min[0] + max[0]) / 2, 128 - (min[1] + max[1]) / 2, -min[2]];
  for (let i = 0; i < v.length; i += 3) for (let a = 0; a < 3; a += 1) v[i + a] += shift[a];
  const footprint = [max[0] - min[0], max[1] - min[1]];
  let edgeGap = Infinity;
  let excludeGap = Infinity;
  const [[ex0, ey0], [ex1, ey1]] = BED.exclude;
  for (let i = 0; i < v.length; i += 3) {
    const [x, y] = [v[i], v[i + 1]];
    edgeGap = Math.min(edgeGap, x, y, BED.size - x, BED.size - y);
    excludeGap = Math.min(excludeGap, Math.hypot(Math.max(ex0 - x, 0, x - ex1), Math.max(ey0 - y, 0, y - ey1)));
  }
  if (edgeGap < BED.margin || excludeGap < BED.margin) {
    throw new Error(`${name} too close to the bed edge (${edgeGap.toFixed(1)} mm) or no-print zone (${excludeGap.toFixed(1)} mm)`);
  }
  return {
    object: { name, vertices: v, triangles: mesh.triangles },
    footprint,
    height: max[2] - min[2],
    triangles: stats.triangleCount,
    edgeGap: +edgeGap.toFixed(1),
    excludeGap: +excludeGap.toFixed(1),
  };
}

const plateBed = bedLayout([block, backer], 'testbed_with_backer');
const backerBed = bedLayout([backer], 'flex_backer');
fs.writeFileSync(path.join(outDir, 'MMSA_testbed_0012_print.3mf'), buildThreeMf('MMSA port test bed NACA 0012 (block + backer printed in place)', [plateBed.object]));
fs.writeFileSync(path.join(refDir, 'MMSA_testbed_0012_backer_only.3mf'), buildThreeMf('MMSA port test bed NACA 0012 - spare backer', [backerBed.object]));
checks.print = {
  plate: {
    footprint: plateBed.footprint.map((x) => +x.toFixed(1)),
    height: +plateBed.height.toFixed(2),
    triangles: plateBed.triangles,
    edgeGap: plateBed.edgeGap,
    noPrintZoneGap: plateBed.excludeGap,
  },
  backerOnly: { footprint: backerBed.footprint.map((x) => +x.toFixed(1)), height: +backerBed.height.toFixed(2), triangles: backerBed.triangles },
};

await writeBlob(path.join(outDir, 'MMSA_testbed_0012.step'), replicad.exportSTEP([
  { shape: block, name: 'testbed_block', color: '#c8c8c8' },
  { shape: backer, name: 'flex_backer', color: '#3b7dd8' },
]));
await writeBlob(path.join(refDir, 'MMSA_testbed_0012_fitcheck.step'), replicad.exportSTEP([
  { shape: block, name: 'testbed_block', color: '#c8c8c8', alpha: 0.5 },
  { shape: backer, name: 'flex_backer', color: '#3b7dd8' },
  { shape: flex, name: 'flex_strip', color: '#e0b000' },
  ...parts.map(({ name, shape }) => ({ shape, name, color: name.includes('_C') ? '#8b5a2b' : '#202020' })),
]));
await writeBlob(path.join(refDir, 'block.stl'), block.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'backer.stl'), backer.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'flex.stl'), flex.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'parts.stl'), replicad.makeCompound(parts.map((p) => p.shape)).blobSTL({ ...MESH, binary: true }));

summary.checks = checks;
fs.writeFileSync(path.join(refDir, 'testbed_design.json'), `${JSON.stringify(summary, null, 2)}\n`);
console.log('print', JSON.stringify(checks.print));
console.log('wrote', outDir);
