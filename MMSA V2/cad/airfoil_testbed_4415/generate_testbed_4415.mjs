/**
 * MMSA airfoil mic-port test bed, NACA 4415 version.
 *
 * Same job as ../airfoil_testbed (v1, NACA 0012): one print that tests 8 port
 * geometries (hole diameter D, skin depth d) under a Monokote skin, with the
 * real mic flex in a channel under the surface. What changed:
 *  - The surface comes from the user's wing file, input/"Air Foil NACA 4415
 *    Small Slot.step" (upper surface only, 243.84 mm chord). Its upper arc is
 *    ~260 mm, too short for the 300 mm flex laid straight along the chord.
 *  - So the flex runs at an angle (yaw) across the chord, the way the real wing
 *    carries it. The block is a straight diagonal slice of the airfoil around
 *    the flex (side walls at least 7.7 mm beside the channel), on a flat 4 mm base.
 *
 * Geometry. The airfoil is a straight extrusion along the span, so it unrolls
 * flat. Positions on the pocket roof (the flex's top surface) use developed
 * coordinates (sigma, y): sigma = arc length along the roof profile from the
 * leading edge, y = span. There the flex is a straight band at angle `yaw`.
 * The roof depth below the outer surface depends on sigma only (flat over each
 * mic, blended between mics), so the roof is still an extrusion along y and
 * the flex lies on it without stretching. Channel, block and backer walls are
 * vertical. The channel and backer plan outlines come from mapping the
 * developed band to plan view, x = roof x at that sigma; the block's outer
 * walls are two straight lines outside that (blockOutline).
 *
 * Writes output/:
 *   MMSA_testbed_4415_print.3mf                 block + backer on one P1S plate (the print)
 *   MMSA_testbed_4415.step                      block + backer, opens in Fusion 360
 *   reference/MMSA_testbed_4415_backer_only.3mf spare backer
 *   reference/MMSA_testbed_4415_fitcheck.step   adds a dummy flex, mics and caps
 *   reference/*.stl, reference/testbed_design.json   for preview_testbed_4415.py
 *
 * Run:  node generate_testbed_4415.mjs   (--dry prints the layout only, --yaw=38 forces an angle)
 * Needs replicad + replicad-opencascadejs. Set REPLICAD_NODE_MODULES if they
 * are not at the default path below, and AIRFOIL_STEP to use another wing file.
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
const STEP_FILE = process.env.AIRFOIL_STEP ?? path.join(here, 'input', 'Air Foil NACA 4415 Small Slot.step');

// ---------------------------------------------------------------- parameters (mm)
const P = {
  yawDeg: yawArg ? Number(yawArg.slice(6)) : null, // null = smallest angle (0.5 deg steps) that fits
  bandWidth: 30.0, // sets the side walls: (30 - 14.6) / 2 = 7.7 mm minimum beside the channel, as v1
  baseDepth: 4.0, // flat base below the chord line (the tail slot is 2.4 mm tall)

  // Flex, from Flex Array_PCB.step. xf runs along the strip, 0 at the mic7 end,
  // 300 at the tail end. yf runs across it, 0..14, centre 7.
  flexLength: 300.0,
  flexWidth: 14.0,
  flexThickness: 0.11, // JLC order (the KiCad STEP shows 0.411)
  portXf: [284, 245, 204, 165, 125, 84, 45, 4], // mic0..mic7 (port = package centre along xf)
  portYfOffset: 0.78, // port sits 0.78 mm off the package centre toward +yf
  micHeight: 1.1, // CAD body incl. solder; datasheet H = 1.00 +/- 0.1
  micBody: [3.0, 4.28], // along xf, across (CAD lid outline 4.28; datasheet 3 x 4)
  lidHalfWidth: 2.0, // datasheet W/2, used to keep big holes on the lid
  cap10u: { xf: [3.28, 4.72], h: 1.4 }, // relative to the mic centre (toward the tail), both caps at yf 6.4..7.6
  cap100n: { xf: [6.28, 7.72], h: 1.0 },
  capHalfWidth: 0.6,

  // Placement on the roof (developed coordinates)
  stripStartMargin: 1.0, // the strip corner nearest the leading edge sits this far (roof arc) from it
  teMargin: 3.0, // the channel's far corner stays this far (roof arc) from the trailing edge

  // Fits (same as v1)
  channelClearance: 0.3, // per side, flex in the channel
  micPocketClearance: 0.15, // per side
  gasket: 0.10, // thin double-sided tape between the mic lid and the pocket roof
  pocketLeadIn: 0.3, // 45 deg chamfer at each mic pocket's mouth
  capMargin: 0.48, // around cap bodies (pads, fillets, placement)
  capHeadroom: 0.15,
  minSkin: 0.4, // a cap pocket with less skin than this is opened through the top
  holeLidMargin: 0.35, // keep the hole edge this far inside the lid edge
  plateauMargin: 1.5, // flat roof beyond each mic's footprint before the depth ramps
  cavityEndClearance: 1.5,
  frontSlotTop: -1.0, // tail exit slot through the front face, from the sill up to this z
  frontSlotSill: 0.6, // keeps the block's first layer a closed ring, so a slicer brim can't run into the channel

  // Backer: printed in place inside the channel, then pushed out, fitted with
  // foam tape and pushed back to hold the flex up from below.
  backerFoam: 1.0,
  backerSideClearance: 0.4, // print-in-place gap to the channel walls, measured in plan
  backerEndGap: 1.0,
  minPrintGap: 0.35, // build fails if the backer comes closer than this to the block

  labelFont: 'C:/Windows/Fonts/arialbd.ttf',
  labelSize: 2.6,
  labelDepth: 0.4, // engraved into the bottom face, mirrored so it reads with the block upside down
  labelEdgeMargin: 5.0, // labels stay this far inside the leading and trailing edges (plan x)
};

// Port variants, one per mic. D = hole diameter, d = skin over the mic lid. Same as v1.
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

// replicad frees OpenCascade objects from JS finalizers, which only run after
// a garbage collection and a turn of the event loop. Force both between heavy steps.
v8.setFlagsFromString('--expose-gc');
const forceGc = vm.runInNewContext('gc');
async function freeMemory() {
  forceGc();
  await new Promise((resolve) => { setTimeout(resolve, 0); });
  forceGc();
  await new Promise((resolve) => { setTimeout(resolve, 0); });
}

// ---------------------------------------------------------------- airfoil from the STEP
// Upper surface profile, sampled from the wing's upper B-spline face at one
// end of the span. X chordwise from the leading edge, Z up, n outward.
const wingFile = await replicad.importSTEP(new Blob([fs.readFileSync(STEP_FILE)]));
const wingSolids = [];
{
  const explorer = new oc.TopExp_Explorer(wingFile.wrapped, oc.TopAbs_ShapeEnum.TopAbs_SOLID, oc.TopAbs_ShapeEnum.TopAbs_SHAPE);
  while (explorer.More()) { wingSolids.push(replicad.cast(explorer.Current())); explorer.Next(); }
}
const wing = wingSolids.sort((a, b) => replicad.measureVolume(b) - replicad.measureVolume(a))[0];
const upperFace = wing.faces
  .filter((f) => f.geomType === 'BSPLINE_SURFACE')
  .sort((a, b) => b.boundingBox.bounds[1][2] - a.boundingBox.bounds[1][2])[0];
const profileEdge = upperFace.edges.find((e) => {
  const [mn, mx] = e.boundingBox.bounds;
  return Math.abs(mx[1] - mn[1]) < 0.01 && replicad.measureLength(e) > 100;
});
if (!profileEdge) throw new Error('no upper-surface profile edge found in the STEP');

const N = 20000;
let raw = Array.from({ length: N + 1 }, (_, k) => {
  const p = profileEdge.pointAt(k / N);
  const t = profileEdge.tangentAt(k / N);
  return { x: p.x, z: p.z, tx: t.x, tz: t.z };
});
if (raw[0].x > raw[N].x) raw = raw.reverse().map((q) => ({ ...q, tx: -q.tx, tz: -q.tz }));
const stepLE = { x: raw[0].x, z: raw[0].z };
const chord = raw[N].x - raw[0].x;
const stepY = profileEdge.boundingBox.bounds[0][1];
const grid = raw.map((q) => {
  const len = Math.hypot(q.tx, q.tz);
  const t = [q.tx / len, q.tz / len];
  return { x: q.x - stepLE.x, z: q.z - stepLE.z, n: [-t[1], t[0]] };
});
if (Math.abs(stepLE.z) > 0.01 || Math.abs(raw[N].z - stepLE.z) > 0.01) throw new Error('profile does not run LE to TE on z = 0');
if (grid[0].n[0] > -0.99) throw new Error(`leading-edge normal is not -x (${grid[0].n})`);
const sOuter = new Float64Array(N + 1);
let maxStep = 0;
for (let k = 1; k <= N; k += 1) {
  const ds = Math.hypot(grid[k].x - grid[k - 1].x, grid[k].z - grid[k - 1].z);
  sOuter[k] = sOuter[k - 1] + ds;
  maxStep = Math.max(maxStep, ds);
}
if (maxStep > 0.1) throw new Error(`profile sampling too coarse (${maxStep.toFixed(3)} mm)`);
const zMax = Math.max(...grid.map((g) => g.z));

// ---------------------------------------------------------------- layout for a given yaw
const micPocketHalf = P.micBody[0] / 2 + P.micPocketClearance;
const micPocketHalfY = P.micBody[1] / 2 + P.micPocketClearance;
const capPocketEnd = P.cap100n.xf[1] + P.capMargin; // furthest cap pocket edge from the mic centre
const cavityWidth = P.flexWidth + 2 * P.channelClearance;
const roofDepth = VARIANTS.map(({ d }) => d + P.micHeight + P.gasket);
const micU = P.portXf.map((xf) => P.flexLength - xf); // along the strip from the tail end

function layoutFor(yawDeg) {
  const th = (yawDeg * Math.PI) / 180;
  const [cs, sn] = [Math.cos(th), Math.sin(th)];
  const sigmaTail = P.stripStartMargin + (P.flexWidth / 2) * sn; // strip centreline at u = 0
  const dev = (u, v) => ({ sigma: sigmaTail + u * cs - v * sn, y: u * sn + v * cs });

  // Each mic's flat-roof zone in sigma covers its pockets across the whole channel width.
  const offMin = -capPocketEnd * cs - (cavityWidth / 2) * sn;
  const offMax = (micPocketHalf + P.pocketLeadIn) * cs + (cavityWidth / 2) * sn;
  const micSigma = micU.map((u) => dev(u, 0).sigma);
  const plateau = micSigma.map((sg) => [sg + offMin - P.plateauMargin, sg + offMax + P.plateauMargin]);
  for (let i = 0; i + 1 < plateau.length; i += 1) {
    if (plateau[i][1] >= plateau[i + 1][0]) return { yawDeg, fits: false, why: `mic${i}/mic${i + 1} flat zones overlap` };
  }
  const depthAtSigma = (sg) => {
    if (sg <= plateau[0][1]) return roofDepth[0];
    for (let i = 0; i < VARIANTS.length - 1; i += 1) {
      const a = plateau[i][1];
      const b = plateau[i + 1][0];
      if (sg <= a) return roofDepth[i];
      if (sg < b) {
        const w = (1 - Math.cos((Math.PI * (sg - a)) / (b - a))) / 2;
        return roofDepth[i] + (roofDepth[i + 1] - roofDepth[i]) * w;
      }
    }
    return roofDepth[VARIANTS.length - 1];
  };

  // C (roof depth) depends on sigma, which depends on C: iterate.
  const C = new Float64Array(N + 1).fill(roofDepth[0]);
  const sigma = new Float64Array(N + 1);
  const roofArc = () => {
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
  };
  for (let it = 0; it < 30; it += 1) {
    roofArc();
    let change = 0;
    for (let k = 0; k <= N; k += 1) {
      const next = depthAtSigma(sigma[k]);
      change = Math.max(change, Math.abs(next - C[k]));
      C[k] = next;
    }
    if (change < 1e-9) break;
  }
  roofArc();
  const sigmaN = sigma[N];
  const uEnd = P.flexLength + P.cavityEndClearance;
  const channelFarCorner = dev(uEnd, -cavityWidth / 2).sigma;
  const fits = channelFarCorner <= sigmaN - P.teMargin;
  return {
    yawDeg, th, cs, sn, sigmaTail, dev, plateau, C, sigma, sigmaN, uEnd, channelFarCorner, fits,
    why: fits ? '' : `channel end reaches sigma ${channelFarCorner.toFixed(1)} of ${sigmaN.toFixed(1)}`,
  };
}

let L;
if (P.yawDeg !== null) {
  L = layoutFor(P.yawDeg);
  if (!L.fits) throw new Error(`flex does not fit at yaw ${P.yawDeg} deg: ${L.why}`);
} else {
  for (let yaw = 20; yaw <= 50; yaw += 0.5) {
    L = layoutFor(yaw);
    if (L.fits) break;
  }
  if (!L.fits) throw new Error(`flex does not fit at any yaw up to 50 deg: ${L.why}`);
}
const { cs, sn, dev, C, sigma, sigmaN, uEnd } = L;
const yawDeg = L.yawDeg;

// Point on the roof (or offset below it) at a given sigma.
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
  const c = lerp(C[lo], C[hi]);
  return {
    x, z, n, c,
    t: [n[1], -n[0]], // tangent, pointing aft
    s: lerp(sOuter[lo], sOuter[hi]),
    roof: [x - c * n[0], z - c * n[1]],
    offset: (extra) => [x - (c + extra) * n[0], z - (c + extra) * n[1]],
  };
}

// Plan-view x of a developed point. Past the leading edge the map is mirrored
// (smooth, keeps going forward); past the trailing edge it continues straight.
function planX(sg, extra = 0) {
  if (sg < 0) return 2 * planX(0, extra) - planX(-sg, extra);
  if (sg > sigmaN) {
    const k = (planX(sigmaN, extra) - planX(sigmaN - 0.5, extra)) / 0.5;
    return planX(sigmaN, extra) + (sg - sigmaN) * k;
  }
  return atSigma(sg).offset(extra)[0];
}
const planOf = (p, extra = 0) => [planX(p.sigma, extra), p.y];
const planSlope = (sg) => (planX(sg + 0.05) - planX(sg - 0.05)) / 0.1; // d(plan x)/d(sigma)
const planDir = (sg) => { // unit plan direction of the strip (toward mic7) at sigma
  const d = [planSlope(sg) * cs, sn];
  const l = Math.hypot(d[0], d[1]);
  return [d[0] / l, d[1] / l];
};

// Positions
const holeV = VARIANTS.map(({ D }) => -Math.min(P.portYfOffset, P.lidHalfWidth - P.holeLidMargin - D / 2));
const capPockets = [
  { name: 'C10u', ...P.cap10u },
  { name: 'C100n', ...P.cap100n },
].map((cap) => ({
  ...cap,
  center: (cap.xf[0] + cap.xf[1]) / 2, // distance from the mic centre toward the tail
  half: (cap.xf[1] - cap.xf[0]) / 2 + P.capMargin,
  pocketHeight: cap.h + P.capHeadroom,
}));

const mics = VARIANTS.map((variant, i) => {
  const centre = dev(micU[i], 0);
  const hole = dev(micU[i], holeV[i]);
  const port = dev(micU[i], -P.portYfOffset);
  const f = atSigma(port.sigma);
  const slope = (Math.atan2(f.n[0], f.n[1]) * -180) / Math.PI; // surface angle, + = rising aft
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
    centre,
    hole,
    port: { sigma: +port.sigma.toFixed(2), y: +port.y.toFixed(2) },
    portX: +f.x.toFixed(2),
    portY: +port.y.toFixed(2),
    portZ: +f.z.toFixed(2),
    portXOverC: +(f.x / chord).toFixed(3),
    surfaceArc: +f.s.toFixed(2),
    surfaceSlopeDeg: +slope.toFixed(1),
    holeV: +holeV[i].toFixed(2),
    caps,
  };
});

const stripCorners = [[0, -1], [0, 1], [P.flexLength, -1], [P.flexLength, 1]].map(([u, s]) => dev(u, (s * P.flexWidth) / 2).sigma);
const summary = {
  generated: new Date().toISOString(),
  units: 'mm',
  frame: 'X chordwise from the leading edge, Y spanwise, Z up; chord line at Z = 0, base bottom at Z = -baseDepth. '
    + `STEP frame = this + (${stepLE.x.toFixed(2)}, 0, ${stepLE.z.toFixed(2)}).`,
  source: path.basename(STEP_FILE),
  airfoil: { chord: +chord.toFixed(3), maxZ: +zMax.toFixed(2), outerArcLength: +sOuter[N].toFixed(2), sampledAtStepY: +stepY.toFixed(2) },
  parameters: P,
  yawDeg,
  yawNote: P.yawDeg === null ? 'smallest angle in 0.5 deg steps that fits the flex on the upper surface' : 'set on the command line',
  roofArcLength: +sigmaN.toFixed(2),
  stripSigmaRange: [+Math.min(...stripCorners).toFixed(2), +Math.max(...stripCorners).toFixed(2)],
  channelFarCornerSigma: +L.channelFarCorner.toFixed(2),
  mics: mics.map(({ centre, hole, ...m }) => m),
};

console.log(`airfoil: chord ${chord.toFixed(2)} mm, max z ${zMax.toFixed(2)}, upper arc ${sOuter[N].toFixed(2)}, roof arc ${sigmaN.toFixed(2)}`);
console.log(`yaw ${yawDeg} deg; strip on roof sigma ${summary.stripSigmaRange.join('..')}; channel far corner ${summary.channelFarCornerSigma}`);
for (const m of mics) {
  const caps = m.caps.map((c) => `${c.name} skin ${c.skin}${c.openThroughTop ? ' OPEN' : ''}`).join(', ');
  console.log(`mic${m.mic}: x/c ${m.portXOverC} (x ${m.portX}, y ${m.portY}), slope ${m.surfaceSlopeDeg} deg, D ${m.D} d ${m.d}; ${caps}`);
}
if (DRY) process.exit(0);

// ---------------------------------------------------------------- CAD helpers
fs.mkdirSync(refDir, { recursive: true });
const t0 = Date.now();
const step = (what) => console.log(`[${((Date.now() - t0) / 1000).toFixed(0)} s] ${what}`);
const BSPLINE = { tolerance: 0.002, degMin: 3, degMax: 8 };

// Closed planar profile from a chain of segments (each a list of 2D points;
// more than 2 points = B-spline, 2 points = line), mapped to 3D by `to3d` and
// extruded along `extrusion`.
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
  chain.forEach((_, i) => { // snap lines onto neighbouring spline ends
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
// XZ section extruded along Y from y0 to y1.
const sectionSolid = (chain, y0, y1) => chainSolid(chain, ([x, z]) => [x, y0, z], [0, y1 - y0, 0]);
// XY outline extruded along Z from z0 to z1.
const planSolid = (chain, z0, z1) => chainSolid(chain, ([x, y]) => [x, y, z0], [0, 0, z1 - z0]);

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

// One long edge of a developed band (v fixed, u0..u1) in plan, finely sampled where the map bends.
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
// Vertical prism over the developed band |v| <= half, u0..u1 (ends are straight lines in plan).
function bandPrism(half, u0, u1, z0, z1, extra = 0) {
  const a = bandEdge(-half, u0, u1, extra);
  const b = bandEdge(half, u0, u1, extra).reverse();
  return planSolid([a, [a[a.length - 1], b[0]], b, [b[b.length - 1], a[0]]], z0, z1);
}
// Shift a plan polyline sideways by `dist` (positive = to the left of its direction).
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
// Big box covering everything on the tail side of the developed line u = const
// (a straight line in plan; the map is close to linear near the trailing edge).
function tailSideOf(u, z0, z1) {
  const c = planOf(dev(u, 0));
  const d = planDir(dev(u, 0).sigma);
  const across = [-d[1], d[0]];
  const w = 120;
  const back = 700;
  const pts = [
    [c[0] - across[0] * w, c[1] - across[1] * w],
    [c[0] + across[0] * w, c[1] + across[1] * w],
    [c[0] + across[0] * w - d[0] * back, c[1] + across[1] * w - d[1] * back],
    [c[0] - across[0] * w - d[0] * back, c[1] - across[1] * w - d[1] * back],
  ];
  return replicad.basicFaceExtrusion(replicad.makePolygon(pts.map(([x, y]) => [x, y, z0])), new replicad.Vector([0, 0, z1 - z0]));
}

// A box in the local frame at a developed point (a along the strip toward
// mic7, b across it, n outward), placed in the world frame.
function localBox(p, [a0, b0, n0], [a1, b1, n1]) {
  const f = atSigma(p.sigma);
  const phi = (Math.atan2(f.t[1], f.t[0]) * 180) / Math.PI;
  return replicad.makeBox([a0, b0, n0], [a1, b1, n1])
    .rotate(yawDeg, [0, 0, 0], [0, 0, 1])
    .rotate(-phi, [0, 0, 0], [0, 1, 0])
    .translate([f.roof[0], p.y, f.roof[1]]);
}
// 45-degree lead-in at a pocket mouth (a frustum `lead` wider per side at the roof).
function leadIn(p, halfA, halfB, lead) {
  const f = atSigma(p.sigma);
  const phi = (Math.atan2(f.t[1], f.t[0]) * 180) / Math.PI;
  const below = 0.6;
  const rect = (ha, hb, n) => replicad.makePolygon([[-ha, -hb, n], [ha, -hb, n], [ha, hb, n], [-ha, hb, n]]).outerWire();
  return replicad.loft([
    rect(halfA + lead + below, halfB + lead + below, -below),
    rect(halfA, halfB, lead),
  ], { ruled: true })
    .rotate(yawDeg, [0, 0, 0], [0, 0, 1])
    .rotate(-phi, [0, 0, 0], [0, 1, 0])
    .translate([f.roof[0], p.y, f.roof[1]]);
}

// Port hole as a 48-sided prism (0.003 mm from round at D 2.4). A true
// cylinder cut through the top surface left mic6's hole outline as half an
// ellipse, which the mesher can't close; flat facets intersect cleanly.
function holePrism(r, height, base, dir) {
  const e1 = [0, 1, 0];
  const e2 = [-dir[2], 0, dir[0]];
  const sides = 48;
  const pts = Array.from({ length: sides }, (_, k) => {
    const a = (2 * Math.PI * k) / sides;
    return [0, 1, 2].map((i) => base[i] + r * (Math.cos(a) * e1[i] + Math.sin(a) * e2[i]));
  });
  return replicad.basicFaceExtrusion(replicad.makePolygon(pts), new replicad.Vector(dir.map((x) => x * height)));
}

function measure(shape) {
  const [min, max] = shape.boundingBox.bounds;
  return { min, max, volume: replicad.measureVolume(shape) };
}

// ---------------------------------------------------------------- CAD
const B = P.baseDepth;
const zTop = zMax + 5;
const zBot = -B - 2;

const blockHalf = P.bandWidth / 2;
const wallMin = blockHalf - cavityWidth / 2; // side wall thickness beside the channel (7.7 mm, as v1)
const uChannel0 = (-12 - L.sigmaTail - (cavityWidth / 2) * sn) / cs;
for (const v of [-1, 1]) {
  if (planOf(dev(uChannel0, (v * cavityWidth) / 2))[0] > -1.2) throw new Error('channel does not reach out through the front face');
}

// Block outline in plan: two straight walls, so the rig is a plain diagonal
// slice of the wing. (A straight strip laid at an angle over the rounded nose
// curves in plan view, so walls that followed it hooked round at the leading
// edge.) The channel inside still follows the flex; the walls sit at least
// wallMin outside it everywhere, so they are thicker near the nose.
const blockOutline = (() => {
  const cLE = planOf(dev(-L.sigmaTail / cs, 0)); // flex centreline at the leading edge
  const cTE = planOf(dev((sigmaN - L.sigmaTail) / cs, 0)); // ... and at the trailing edge
  const len = Math.hypot(cTE[0] - cLE[0], cTE[1] - cLE[1]);
  const d = [(cTE[0] - cLE[0]) / len, (cTE[1] - cLE[1]) / len];
  const across = [-d[1], d[0]];
  const channelPts = [
    ...bandEdge(-cavityWidth / 2, uChannel0, uEnd),
    ...bandEdge(cavityWidth / 2, uChannel0, uEnd),
  ].filter(([x]) => x >= -1);
  const off = channelPts.map(([x, y]) => (x - cLE[0]) * across[0] + (y - cLE[1]) * across[1]);
  const sLo = Math.min(...off) - wallMin;
  const sHi = Math.max(...off) + wallMin;
  const at = (t, s) => [cLE[0] + d[0] * t + across[0] * s, cLE[1] + d[1] * t + across[1] * s];
  const corners = [at(-80, sLo), at(len + 80, sLo), at(len + 80, sHi), at(-80, sHi)];
  if (Math.max(at(-80, sLo)[0], at(-80, sHi)[0]) > -1 || Math.min(at(len + 80, sLo)[0], at(len + 80, sHi)[0]) < chord + 1) {
    throw new Error('block outline does not run past both edges');
  }
  return { corners, width: sHi - sLo, angleDeg: (Math.atan2(d[1], d[0]) * 180) / Math.PI };
})();
const yLo = Math.min(...blockOutline.corners.map((p) => p[1])) - 5;
const yHi = Math.max(...blockOutline.corners.map((p) => p[1])) + 5;
console.log(`block: straight walls ${blockOutline.width.toFixed(1)} mm apart, at ${blockOutline.angleDeg.toFixed(1)} deg to the chord in plan`);

// Airfoil slab: upper surface on a flat base, then trimmed to the band.
const outerPts = Array.from({ length: 401 }, (_, j) => {
  const target = (sOuter[N] * (1 - Math.cos((Math.PI * j) / 400))) / 2;
  let lo = 0;
  let hi = N;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (sOuter[mid] <= target) lo = mid;
    else hi = mid;
  }
  const u = (target - sOuter[lo]) / (sOuter[hi] - sOuter[lo] || 1);
  return [grid[lo].x + (grid[hi].x - grid[lo].x) * u, grid[lo].z + (grid[hi].z - grid[lo].z) * u];
});
outerPts[0] = [grid[0].x, grid[0].z];
outerPts[400] = [grid[N].x, grid[N].z];
const nose = outerPts[0];
const tail = outerPts[400];
step('slab');
const slab = sectionSolid([
  outerPts,
  [tail, [tail[0], -B]],
  [[tail[0], -B], [nose[0], -B]],
  [[nose[0], -B], nose],
], yLo, yHi);
step('block band');
let block = slab.intersect(replicad.basicFaceExtrusion(
  replicad.makePolygon(blockOutline.corners.map(([x, y]) => [x, y, zBot])),
  new replicad.Vector([0, 0, zTop - zBot]),
));

// Rotation sanity check: a box 1 mm along the local a axis must move along the strip on the roof.
{
  const p = mics[0].centre;
  const f = atSigma(p.sigma);
  const probe = localBox(p, [0.5, -0.1, -0.1], [1.5, 0.1, 0.1]).boundingBox.center;
  const want = [f.roof[0] + f.t[0] * cs, p.y + sn, f.roof[1] + f.t[1] * cs];
  if (Math.hypot(probe[0] - want[0], probe[1] - want[1], probe[2] - want[2]) > 0.02) {
    throw new Error(`local frame rotation is wrong: got ${probe}, want ${want}`);
  }
}

// Flex channel: open at the bottom, tail slot through the front face, square end at the mic7 end.
const sigmaChannelEnd = Math.min(sigmaN, L.channelFarCorner + 0.5);
const roofPts = sampleSigma(0, sigmaChannelEnd).map((sg) => atSigma(sg).roof);
const roofStart = roofPts[0];
const roofEnd = roofPts[roofPts.length - 1];
const cavitySection = sectionSolid([
  roofPts,
  [roofEnd, [roofEnd[0], -B - 1]],
  [[roofEnd[0], -B - 1], [roofStart[0], -B - 1]],
  [[roofStart[0], -B - 1], [roofStart[0], -B + P.frontSlotSill]],
  [[roofStart[0], -B + P.frontSlotSill], [-1, -B + P.frontSlotSill]],
  [[-1, -B + P.frontSlotSill], [-1, P.frontSlotTop]],
  [[-1, P.frontSlotTop], [roofStart[0], P.frontSlotTop]],
  [[roofStart[0], P.frontSlotTop], roofStart],
], yLo, yHi);
const channelPlanA = bandEdge(-cavityWidth / 2, uChannel0, uEnd);
const channelPlanB = bandEdge(cavityWidth / 2, uChannel0, uEnd);
step('channel');
const channel = cavitySection.intersect(bandPrism(cavityWidth / 2, uChannel0, uEnd, zBot, zTop));
block = block.cut(channel);
await freeMemory();
step('pockets');

// Mic pockets, port holes, cap pockets.
const tools = [];
mics.forEach((m, i) => {
  const C0 = roofDepth[i];
  const micPocketTop = P.micHeight + P.gasket;
  tools.push(localBox(m.centre, [-micPocketHalf, -micPocketHalfY, -0.6], [micPocketHalf, micPocketHalfY, micPocketTop]));
  tools.push(leadIn(m.centre, micPocketHalf, micPocketHalfY, P.pocketLeadIn));

  const f = atSigma(m.hole.sigma);
  const start = micPocketTop - 0.05;
  tools.push(holePrism(
    m.D / 2,
    C0 - start + 1.5,
    [f.roof[0] + f.n[0] * start, m.hole.y, f.roof[1] + f.n[1] * start],
    [f.n[0], 0, f.n[1]],
  ));

  capPockets.forEach((cap, j) => {
    const top = m.caps[j].openThroughTop ? C0 + 1.5 : cap.pocketHeight;
    const halfW = P.capHalfWidth + P.capMargin;
    tools.push(localBox(dev(micU[i] - cap.center, 0), [-cap.half, -halfW, -0.6], [cap.half, halfW, top]));
  });
});
for (const tool of tools) {
  block = block.cut(tool);
  await freeMemory();
}
step('labels');

// Labels engraved in the bottom face beside each mic, on the wall at +v,
// mirrored so they read with the block upside down (how it's assembled).
const fontBytes = fs.readFileSync(P.labelFont);
await replicad.loadFont(fontBytes.buffer.slice(fontBytes.byteOffset, fontBytes.byteOffset + fontBytes.byteLength), 'label');
const labelV = (cavityWidth / 2 + blockHalf) / 2;
const labels = [];
for (const m of mics) {
  const text = `${m.mic}: D${m.D.toFixed(1)} d${m.d.toFixed(1)}`;
  const drawing = replicad.drawText(text, { fontSize: P.labelSize, fontFamily: 'label' });
  const [[x0, y0], [x1, y1]] = drawing.boundingBox.bounds;
  const half = (x1 - x0) / 2;
  let u = micU[m.mic];
  const mid = P.flexLength / 2;
  const ok = (uu) => {
    const p = dev(uu, labelV);
    const c = planOf(p);
    const d = planDir(p.sigma);
    const xs = [c[0] - d[0] * half, c[0] + d[0] * half];
    return Math.min(...xs) >= P.labelEdgeMargin && Math.max(...xs) <= chord - P.labelEdgeMargin;
  };
  while (!ok(u)) {
    u += Math.sign(mid - u) * 0.5;
    if (Math.abs(u - mid) < 1) throw new Error(`no room for label ${text}`);
  }
  const p = dev(u, labelV);
  const [cx, cy] = planOf(p);
  const d = planDir(p.sigma);
  const angle = (Math.atan2(d[1], d[0]) * 180) / Math.PI;
  // Plane looking up from below: drawing (a, b) -> world (a, -b), so text reads correctly from underneath.
  const plane = new replicad.Plane([0, 0, -B - 0.2], [1, 0, 0], [0, 0, -1]);
  const cutter = drawing
    .translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
    .rotate(-angle, [0, 0])
    .translate(cx, -cy)
    .sketchOnPlane(plane)
    .extrude(P.labelDepth + 0.2, { extrusionDirection: [0, 0, 1] });
  block = block.cut(cutter);
  await freeMemory();
  labels.push({ text, x: +cx.toFixed(2), y: +cy.toFixed(2), angleDeg: +angle.toFixed(1), u: +u.toFixed(1) });
}

// Backer: pushes the flex up from below through ~1 mm of foam tape. Its sides
// sit backerSideClearance inside the channel walls in plan (where the print gap is set).
const backerGap = P.flexThickness + P.backerFoam;
const sigmaBackerEnd = Math.min(sigmaN, L.channelFarCorner + 0.5);
const backerPts = sampleSigma(0, sigmaBackerEnd).map((sg) => atSigma(sg).offset(backerGap));
const bStart = backerPts[0];
const bEnd = backerPts[backerPts.length - 1];
step('backer');
const backerSection = sectionSolid([
  backerPts,
  [bEnd, [bEnd[0], -B]],
  [[bEnd[0], -B], [bStart[0], -B]],
  [[bStart[0], -B], bStart],
], yLo, yHi);
const backerA = offsetPolyline(bandEdge(-cavityWidth / 2, uChannel0, uEnd + 6), P.backerSideClearance);
const backerB = offsetPolyline(bandEdge(cavityWidth / 2, uChannel0, uEnd + 6), -P.backerSideClearance).reverse();
const backerSides = planSolid([backerA, [backerA[backerA.length - 1], backerB[0]], backerB, [backerB[backerB.length - 1], backerA[0]]], zBot, zTop);
const backer = backerSection.intersect(backerSides).intersect(tailSideOf(uEnd - P.backerEndGap, zBot, zTop));

// Fit-check dummies: flex strip (on the roof), mics and caps.
const flexSigma = [Math.max(0, summary.stripSigmaRange[0] - 0.5), Math.min(sigmaN, summary.stripSigmaRange[1] + 0.5)];
const flexTop = sampleSigma(flexSigma[0], flexSigma[1], flexSigma[0] + 12).map((sg) => atSigma(sg).offset(0.002));
const flexBottom = sampleSigma(flexSigma[0], flexSigma[1], flexSigma[0] + 12).map((sg) => atSigma(sg).offset(0.002 + P.flexThickness)).reverse();
step('fit-check flex');
const flexSection = sectionSolid([
  flexTop,
  [flexTop[flexTop.length - 1], flexBottom[0]],
  flexBottom,
  [flexBottom[flexBottom.length - 1], flexTop[0]],
], yLo, yHi);
const flex = flexSection.intersect(bandPrism(P.flexWidth / 2, 0, P.flexLength, zBot, zTop, 0.002 + P.flexThickness / 2));
const parts = [];
mics.forEach((m, i) => {
  parts.push({ name: `mic${i}`, shape: localBox(m.centre, [-P.micBody[0] / 2, -P.micBody[1] / 2, 0], [P.micBody[0] / 2, P.micBody[1] / 2, P.micHeight]) });
  capPockets.forEach((cap) => {
    const half = (cap.xf[1] - cap.xf[0]) / 2;
    parts.push({ name: `mic${i}_${cap.name}`, shape: localBox(dev(micU[i] - cap.center, 0), [-half, -P.capHalfWidth, 0], [half, P.capHalfWidth, cap.h]) });
  });
});

// ---------------------------------------------------------------- checks
await freeMemory();
step('checks');
const checks = { interference: {} };
// Each boolean on the block holds ~150 MB until garbage collection, and the
// WASM heap tops out at 4 GB, so free memory after every check.
const overlap = async (a, b) => {
  const volume = replicad.measureVolume(a.clone().intersect(b.clone()));
  await freeMemory();
  return volume;
};
// Positive control: a 1 mm cube inside a side wall must read 1 mm^3.
{
  const [cx, cy] = planOf(dev(P.flexLength / 2, labelV));
  const control = await overlap(block, replicad.makeBox([cx - 0.5, cy - 0.5, -B + 1], [cx + 0.5, cy + 0.5, -B + 2]));
  if (Math.abs(control - 1) > 1e-3) throw new Error(`interference check is broken (control ${control})`);
}
// All mics and caps in one boolean; per part only if something touches.
checks.interference.mics_and_caps = +(await overlap(block, replicad.makeCompound(parts.map((p) => p.shape.clone())))).toFixed(5);
if (checks.interference.mics_and_caps > 0.01) {
  for (const { name, shape } of parts) checks.interference[name] = +(await overlap(block, shape)).toFixed(5);
}
checks.interference.flex = +(await overlap(block, flex)).toFixed(5);
checks.interference.backer_vs_block = +(await overlap(block, backer)).toFixed(5);
checks.interference.backer_vs_flex = +(await overlap(backer, flex)).toFixed(5);
step(`checks done, WASM heap ${(oc.wasmMemory.buffer.byteLength / 2 ** 20).toFixed(0)} MB`);
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
  const rawMesh = oc.ReplicadMeshExtractor.extract(shape.wrapped, tolerance, angularTolerance, false);
  const { buffer } = oc.wasmMemory;
  const vp = (rawMesh.getVerticesPtr() >>> 0) / 4;
  const tp = (rawMesh.getTrianglesPtr() >>> 0) / 4;
  const vertices = Array.from(new Float32Array(buffer).subarray(vp, vp + rawMesh.getVerticesSize()));
  const triangles = Array.from(new Uint32Array(buffer).subarray(tp, tp + rawMesh.getTrianglesSize()));
  rawMesh.delete();
  return { vertices, triangles };
}

// P1S bed: 256 x 256 mm with a no-print zone at the front-left corner
// (bed_exclude_area in the Bambu profile). Keep 5 mm clear of both for a brim.
const BED = { size: 256, exclude: [[0, 0], [18, 28]], margin: 5 };

function convexHull(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}
const excludeDistance = (x, y) => {
  const [[ex0, ey0], [ex1, ey1]] = BED.exclude;
  return Math.hypot(Math.max(ex0 - x, 0, x - ex1), Math.max(ey0 - y, 0, y - ey1));
};

// Merge the shapes into one object (keeps the backer in place inside the
// channel), turn it about Z to the angle that leaves the most room to the bed
// edges and the no-print zone, centre it on the bed, base on Z = 0.
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
if (process.env.DUMP_BREP) {
  fs.writeFileSync(path.join(process.env.DUMP_BREP, 'block.brep'), block.serialize());
  fs.writeFileSync(path.join(process.env.DUMP_BREP, 'backer.brep'), backer.serialize());
}
const plateBed = bedLayout([block, backer], 'testbed_4415_with_backer');
const backerBed = bedLayout([backer], 'flex_backer_4415');
fs.writeFileSync(path.join(outDir, 'MMSA_testbed_4415_print.3mf'), buildThreeMf('MMSA port test bed, NACA 4415 (block + backer printed in place)', [plateBed.object]));
fs.writeFileSync(path.join(refDir, 'MMSA_testbed_4415_backer_only.3mf'), buildThreeMf('MMSA port test bed, NACA 4415 - spare backer', [backerBed.object]));
const bedSummary = (b) => ({
  rotationDeg: b.rotationDeg,
  footprint: b.footprint.map((x) => +x.toFixed(1)),
  height: +b.height.toFixed(2),
  triangles: b.triangles,
  edgeGap: b.edgeGap,
  noPrintZoneGap: b.excludeGap,
});
checks.print = { plate: bedSummary(plateBed), backerOnly: bedSummary(backerBed) };

await writeBlob(path.join(outDir, 'MMSA_testbed_4415.step'), replicad.exportSTEP([
  { shape: block, name: 'testbed_block', color: '#c8c8c8' },
  { shape: backer, name: 'flex_backer', color: '#3b7dd8' },
]));
await writeBlob(path.join(refDir, 'MMSA_testbed_4415_fitcheck.step'), replicad.exportSTEP([
  { shape: block, name: 'testbed_block', color: '#c8c8c8', alpha: 0.5 },
  { shape: backer, name: 'flex_backer', color: '#3b7dd8' },
  { shape: flex, name: 'flex_strip', color: '#e0b000' },
  ...parts.map(({ name, shape }) => ({ shape, name, color: name.includes('_C') ? '#8b5a2b' : '#202020' })),
]));
await writeBlob(path.join(refDir, 'block.stl'), block.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'backer.stl'), backer.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'flex.stl'), flex.blobSTL({ ...MESH, binary: true }));
await writeBlob(path.join(refDir, 'parts.stl'), replicad.makeCompound(parts.map((p) => p.shape)).blobSTL({ ...MESH, binary: true }));

summary.labels = labels;
summary.plan = {
  channelEdges: [channelPlanA, channelPlanB].map((e) => e.filter((_, i) => i % 4 === 0).map(([x, y]) => [+x.toFixed(2), +y.toFixed(2)])),
  ports: mics.map((m) => ({ mic: m.mic, x: +planOf(m.hole)[0].toFixed(2), y: +m.hole.y.toFixed(2), D: m.D })),
  stripDirection: mics.map((m) => planDir(m.centre.sigma).map((x) => +x.toFixed(4))),
};
summary.checks = checks;
fs.writeFileSync(path.join(refDir, 'testbed_design.json'), `${JSON.stringify(summary, null, 2)}\n`);
console.log('print', JSON.stringify(checks.print));
console.log('wrote', outDir);
