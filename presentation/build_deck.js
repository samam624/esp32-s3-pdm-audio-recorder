const pptxgen = require(process.env.PPTXGENJS_PATH || "pptxgenjs");
const path = require("path");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Sam Amezcua";
pptx.subject = "ESP32-S3 MEMS microphone recorder project overview";
pptx.title = "MEMS Microphone Recorder System";
pptx.company = "UC Davis";
pptx.lang = "en-US";
pptx.theme = {
  headFontFace: "Aptos Display",
  bodyFontFace: "Aptos",
  lang: "en-US",
};
pptx.defineSlideMaster({
  title: "CONTENT",
  background: { color: "F7F9FC" },
  objects: [
    { rect: { x: 0, y: 0, w: 13.333, h: 0.12, fill: { color: "FFBF00" }, line: { color: "FFBF00" } } },
    { text: { text: "MEMS MICROPHONE RECORDER", options: { x: 0.55, y: 7.12, w: 3.1, h: 0.18, fontFace: "Aptos", fontSize: 8, color: "67768A", bold: true, margin: 0 } } },
    { text: { text: "UC DAVIS  |  DRAFT", options: { x: 10.65, y: 7.12, w: 2.15, h: 0.18, fontFace: "Aptos", fontSize: 8, color: "67768A", align: "right", margin: 0 } } },
  ],
  slideNumber: { x: 12.85, y: 7.10, w: 0.25, h: 0.2, color: "67768A", fontSize: 8, align: "right" },
});

const C = {
  navy: "022851",
  blue: "13639A",
  sky: "DDEAF3",
  gold: "FFBF00",
  goldLight: "FFF3C4",
  ink: "172A3A",
  gray: "67768A",
  light: "F7F9FC",
  white: "FFFFFF",
  green: "3B7A57",
  greenLight: "DFF1E6",
  red: "B44A4A",
  redLight: "F8E2E2",
  teal: "168B8C",
  tealLight: "DDF3F1",
};

const outPath = path.resolve(__dirname, "MEMS_Microphone_Recorder_Project_Draft.pptx");
const dampingFigure = path.resolve(__dirname, "..", "070926_Mic_Damping_Paper_Package", "02_Figures", "01_wind_attenuation.png");

function addTitle(slide, title, subtitle) {
  slide.addText(title, { x: 0.58, y: 0.38, w: 11.9, h: 0.48, fontSize: 27, bold: true, color: C.navy, margin: 0, breakLine: false, fit: "shrink" });
  if (subtitle) slide.addText(subtitle, { x: 0.60, y: 0.90, w: 11.6, h: 0.28, fontSize: 12.5, color: C.gray, margin: 0, fit: "shrink" });
}

function addPill(slide, text, x, y, w, color = C.sky, textColor = C.navy) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.34, rectRadius: 0.08, fill: { color }, line: { color }, radius: 0.08 });
  slide.addText(text, { x: x + 0.08, y: y + 0.055, w: w - 0.16, h: 0.18, fontSize: 9, bold: true, color: textColor, align: "center", margin: 0, fit: "shrink" });
}

function addCard(slide, x, y, w, h, title, body, opts = {}) {
  const fill = opts.fill || C.white;
  const accent = opts.accent || C.blue;
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.06, fill: { color: fill }, line: { color: opts.line || "D8E1EA", width: 1 } });
  slide.addShape(pptx.ShapeType.rect, { x, y, w: 0.08, h, fill: { color: accent }, line: { color: accent } });
  slide.addText(title, { x: x + 0.25, y: y + 0.20, w: w - 0.45, h: 0.35, fontSize: opts.titleSize || 16, bold: true, color: opts.titleColor || C.navy, margin: 0, fit: "shrink" });
  slide.addText(body, { x: x + 0.25, y: y + 0.70, w: w - 0.45, h: h - 0.88, fontSize: opts.bodySize || 12.5, color: opts.bodyColor || C.ink, margin: 0.02, valign: "top", breakLine: false, fit: "shrink", bullet: opts.bullet });
}

function addBulletList(slide, items, x, y, w, h, opts = {}) {
  const runs = [];
  items.forEach((item, i) => {
    const text = typeof item === "string" ? item : item.text;
    runs.push({ text, options: { bullet: { indent: 16 }, hanging: 4, breakLine: i < items.length - 1, bold: typeof item === "object" && !!item.bold, color: typeof item === "object" && item.color ? item.color : (opts.color || C.ink) } });
  });
  slide.addText(runs, { x, y, w, h, fontSize: opts.fontSize || 16, color: opts.color || C.ink, margin: 0.03, breakLine: false, paraSpaceAfterPt: opts.paraSpaceAfterPt || 12, valign: "top", fit: "shrink" });
}

function addArrow(slide, x, y, w, h, color = C.blue) {
  slide.addShape(pptx.ShapeType.chevron, { x, y, w, h, fill: { color }, line: { color } });
}

function drawDevkit(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.05, fill: { color: "2C7257" }, line: { color: "1C4F3B", width: 1.2 } });
  slide.addShape(pptx.ShapeType.roundRect, { x: x + 0.22*w, y: y + 0.14*h, w: 0.46*w, h: 0.43*h, fill: { color: "273645" }, line: { color: "A8B4BE" } });
  slide.addText("ESP32-S3\nDevKitC", { x: x + 0.25*w, y: y + 0.25*h, w: 0.40*w, h: 0.22*h, fontSize: 11, bold: true, color: C.white, align: "center", margin: 0, fit: "shrink" });
  slide.addShape(pptx.ShapeType.rect, { x: x + 0.03*w, y: y + 0.20*h, w: 0.14*w, h: 0.48*h, fill: { color: "C5CCD3" }, line: { color: "87919C" } });
  slide.addText("microSD", { x: x + 0.035*w, y: y + 0.39*h, w: 0.13*w, h: 0.12*h, fontSize: 8, bold: true, color: C.ink, rotate: 270, align: "center", margin: 0, fit: "shrink" });
  [0.72, 0.87].forEach((rx, i) => {
    slide.addShape(pptx.ShapeType.ellipse, { x: x + rx*w, y: y + 0.18*h, w: 0.10*w, h: 0.16*h, fill: { color: "D6D9DC" }, line: { color: "7B858E" } });
    slide.addText(`MIC ${i ? "R" : "L"}`, { x: x + (rx-0.02)*w, y: y + 0.38*h, w: 0.14*w, h: 0.1*h, fontSize: 7.5, color: C.white, align: "center", margin: 0 });
  });
  [0.28, 0.43, 0.58].forEach((rx, i) => slide.addShape(pptx.ShapeType.ellipse, { x: x + rx*w, y: y + 0.78*h, w: 0.05*w, h: 0.08*h, fill: { color: [C.red, C.gold, "7ED6DF"][i] }, line: { color: C.white, transparency: 40 } }));
  slide.addShape(pptx.ShapeType.roundRect, { x: x + 0.76*w, y: y + 0.70*h, w: 0.16*w, h: 0.15*h, fill: { color: "263645" }, line: { color: "18242D" } });
  slide.addText("REC", { x: x + 0.77*w, y: y + 0.74*h, w: 0.14*w, h: 0.07*h, fontSize: 8, bold: true, color: C.white, align: "center", margin: 0 });
}

function drawFlex(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.03, fill: { color: "B87333" }, line: { color: "8D5422", width: 1.2 } });
  for (let i = 0; i < 8; i++) {
    const mx = x + 0.05*w + i*0.105*w;
    slide.addShape(pptx.ShapeType.ellipse, { x: mx, y: y + 0.20*h, w: 0.048*w, h: 0.48*h, fill: { color: "D7D9DB" }, line: { color: "69737D" } });
    slide.addText(`${i}`, { x: mx - 0.006*w, y: y + 0.73*h, w: 0.06*w, h: 0.12*h, fontSize: 7, color: C.white, align: "center", margin: 0 });
  }
  slide.addShape(pptx.ShapeType.rect, { x: x + 0.90*w, y: y + 0.23*h, w: 0.08*w, h: 0.42*h, fill: { color: "E8D59F" }, line: { color: "957D3B" } });
  slide.addText("FPC", { x: x + 0.91*w, y: y + 0.37*h, w: 0.06*w, h: 0.1*h, fontSize: 7, bold: true, color: C.ink, align: "center", margin: 0 });
}

function drawIntegrated(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.05, fill: { color: "275D48" }, line: { color: "183F30", width: 1.2 } });
  slide.addShape(pptx.ShapeType.rect, { x: x + 0.58*w, y: y + 0.12*h, w: 0.31*w, h: 0.29*h, fill: { color: "263645" }, line: { color: "9DA8B1" } });
  slide.addText("ESP32-S3\nWROOM", { x: x + 0.61*w, y: y + 0.19*h, w: 0.25*w, h: 0.15*h, fontSize: 9.5, bold: true, color: C.white, align: "center", margin: 0, fit: "shrink" });
  slide.addShape(pptx.ShapeType.rect, { x: x + 0.02*w, y: y + 0.12*h, w: 0.15*w, h: 0.16*h, fill: { color: "C4C9CF" }, line: { color: "7F8790" } });
  slide.addText("USB-C", { x: x + 0.03*w, y: y + 0.17*h, w: 0.13*w, h: 0.06*h, fontSize: 7, bold: true, color: C.ink, align: "center", margin: 0 });
  slide.addShape(pptx.ShapeType.rect, { x: x + 0.05*w, y: y + 0.45*h, w: 0.12*w, h: 0.32*h, fill: { color: "E8D59F" }, line: { color: "957D3B" } });
  slide.addText("FPC", { x: x + 0.07*w, y: y + 0.57*h, w: 0.08*w, h: 0.08*h, fontSize: 8, bold: true, color: C.ink, align: "center", margin: 0 });
  slide.addShape(pptx.ShapeType.rect, { x: x + 0.72*w, y: y + 0.55*h, w: 0.20*w, h: 0.24*h, fill: { color: "C5CCD3" }, line: { color: "87919C" } });
  slide.addText("SD", { x: x + 0.76*w, y: y + 0.63*h, w: 0.12*w, h: 0.08*h, fontSize: 9, bold: true, color: C.ink, align: "center", margin: 0 });
  slide.addShape(pptx.ShapeType.roundRect, { x: x + 0.25*w, y: y + 0.18*h, w: 0.22*w, h: 0.18*h, fill: { color: "2A3948" }, line: { color: "9DA8B1" } });
  slide.addText("LiPo / power", { x: x + 0.27*w, y: y + 0.235*h, w: 0.18*w, h: 0.06*h, fontSize: 8, color: C.white, align: "center", margin: 0 });
  [0.28, 0.40, 0.52].forEach((rx, i) => slide.addShape(pptx.ShapeType.ellipse, { x: x + rx*w, y: y + 0.70*h, w: 0.05*w, h: 0.08*h, fill: { color: [C.green, C.gold, C.red][i] }, line: { color: C.white, transparency: 50 } }));
}

// 1 — Title
{
  const slide = pptx.addSlide();
  slide.background = { color: C.navy };
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 0.18, h: 7.5, fill: { color: C.gold }, line: { color: C.gold } });
  slide.addText("MEMS Microphone\nRecorder System", { x: 0.75, y: 1.00, w: 7.1, h: 1.65, fontSize: 40, bold: true, color: C.white, margin: 0, breakLine: false, fit: "shrink" });
  slide.addText("PCB development, firmware bring-up, troubleshooting, and next deployment", { x: 0.78, y: 2.86, w: 6.9, h: 0.55, fontSize: 19, color: "C9D8E5", margin: 0, fit: "shrink" });
  slide.addText("Sam Amezcua  |  UC Davis  |  EDIT PRESENTATION DATE", { x: 0.78, y: 6.62, w: 6.4, h: 0.28, fontSize: 11.5, bold: true, color: C.gold, margin: 0 });
  drawFlex(slide, 8.05, 1.04, 4.45, 0.66);
  addArrow(slide, 9.74, 2.00, 0.55, 0.32, C.gold);
  drawIntegrated(slide, 8.45, 2.62, 3.65, 2.42);
  addPill(slide, "PDM audio", 8.10, 5.50, 1.27, "284767", C.white);
  addPill(slide, "local WAV", 9.53, 5.50, 1.27, "284767", C.white);
  addPill(slide, "BLE control", 10.96, 5.50, 1.33, "284767", C.white);
}

// 2 — Objective
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "What I was building", "A compact audio platform that works without a PC in the recording loop");
  addBulletList(slide, [
    "Capture PDM MEMS microphone data as standard WAV files",
    "Store recordings locally for untethered experiments",
    "Trigger without touching the setup: pushbutton or Bluetooth",
    "Make failures visible through LEDs, telemetry, and recoverable files",
    "Support both a quick devkit prototype and custom microphone hardware",
  ], 0.76, 1.55, 6.15, 3.65, { fontSize: 17, paraSpaceAfterPt: 15 });
  slide.addShape(pptx.ShapeType.roundRect, { x: 7.45, y: 1.43, w: 4.95, h: 3.95, fill: { color: C.goldLight }, line: { color: C.gold, width: 2 } });
  slide.addText("PLANNED USE — EDIT THIS LINE", { x: 7.80, y: 1.78, w: 4.25, h: 0.32, fontSize: 13, bold: true, color: C.navy, margin: 0 });
  slide.addText("[Replace with the exact final experiment/application.]", { x: 7.80, y: 2.28, w: 4.15, h: 0.72, fontSize: 22, bold: true, color: C.navy, margin: 0, fit: "shrink" });
  slide.addText("Current evidence supports describing it as a portable, remotely triggered acoustic-data platform for controlled or field measurements.", { x: 7.80, y: 3.34, w: 4.15, h: 1.15, fontSize: 15, color: C.ink, margin: 0, fit: "shrink" });
  slide.addShape(pptx.ShapeType.line, { x: 1.05, y: 5.83, w: 10.95, h: 0, line: { color: "CCD6E0", width: 1.2 } });
  slide.addText("Design principle", { x: 0.78, y: 5.56, w: 1.55, h: 0.28, fontSize: 11, bold: true, color: C.blue, margin: 0 });
  slide.addText("Record first, verify continuously, and preserve usable audio when hardware or storage misbehaves.", { x: 2.45, y: 5.50, w: 9.55, h: 0.56, fontSize: 18, bold: true, color: C.navy, margin: 0, fit: "shrink" });
}

// 3 — Three boards
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Three ordered PCB designs form the hardware path", "Prototype quickly, scale the sensor geometry, then integrate the recorder");
  const xs = [0.55, 4.48, 8.41];
  const titles = ["1  ESP32 devkit carrier", "2  Eight-mic flex array", "3  Integrated controller"];
  const bodies = [
    "Rapid bring-up board\n\n• ESP32-S3 DevKitC\n• Two PDM microphones\n• microSD + buttons + LEDs\n• Platform used for firmware validation",
    "Spatial sensor board\n\n• Eight IMP34DT05TR PDM mics\n• Four left/right microphone pairs\n• Local decoupling\n• 10-pin FPC tail",
    "Portable system direction\n\n• ESP32-S3-WROOM-N8R8\n• USB-C + LiPo charging\n• 3.3 V and 1.8 V rails\n• FPC, SD, buttons, and status LEDs",
  ];
  for (let i = 0; i < 3; i++) addCard(slide, xs[i], 1.45, 3.62, 4.95, titles[i], bodies[i], { accent: [C.blue, C.teal, C.green][i], bodySize: 13.2 });
  drawDevkit(slide, 0.98, 4.75, 2.76, 1.15);
  drawFlex(slide, 4.84, 5.04, 2.88, 0.56);
  drawIntegrated(slide, 8.89, 4.62, 2.68, 1.36);
}

// 4 — Devkit PCB
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Board 1 — ESP32 devkit recorder", "The fast-learning platform: prove the microphone, storage, controls, and enclosure before full integration");
  drawDevkit(slide, 0.72, 1.60, 5.35, 2.98);
  addPill(slide, "48 kHz", 0.95, 4.90, 1.10);
  addPill(slide, "stereo", 2.18, 4.90, 1.10);
  addPill(slide, "16-bit PCM", 3.41, 4.90, 1.30);
  addPill(slide, "microSD", 4.84, 4.90, 1.10);
  addCard(slide, 6.48, 1.47, 5.90, 4.57, "What is on this board", "• ESP32-S3 DevKitC module\n• Two ST IMP34DT05TR PDM microphones\n• 1.8 V microphone regulator\n• microSD socket over SPI\n• Record button and three status LEDs\n• Exported STEP plus printable enclosure files", { accent: C.blue, bodySize: 15 });
  slide.addText("Validated pin map", { x: 0.82, y: 5.64, w: 1.65, h: 0.25, fontSize: 11, bold: true, color: C.gray, margin: 0 });
  slide.addText("PDM 4/5   •   SD SPI 12/13/11/14   •   button 35   •   LEDs 40/41/42", { x: 2.42, y: 5.58, w: 9.38, h: 0.36, fontSize: 14, bold: true, color: C.navy, margin: 0, fit: "shrink" });
}

// 5 — Flex array
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Board 2 — eight-microphone flex array", "A narrow sensor strip for known microphone spacing and multi-point acoustic capture");
  drawFlex(slide, 0.72, 1.57, 11.86, 1.10);
  slide.addText("MIC7", { x: 0.98, y: 2.82, w: 0.65, h: 0.2, fontSize: 9, color: C.gray, align: "center", margin: 0 });
  slide.addText("≈ 350 mm overall", { x: 5.34, y: 2.82, w: 2.55, h: 0.24, fontSize: 12, bold: true, color: C.navy, align: "center", margin: 0 });
  slide.addText("MIC0 + FPC", { x: 11.13, y: 2.82, w: 1.05, h: 0.2, fontSize: 9, color: C.gray, align: "center", margin: 0 });
  addCard(slide, 0.74, 3.42, 3.73, 2.39, "Sensor layout", "Eight ST IMP34DT05TR omnidirectional digital PDM microphones arranged along a narrow flex PCB.", { accent: C.teal, bodySize: 14 });
  addCard(slide, 4.80, 3.42, 3.73, 2.39, "Electrical strategy", "Four left/right PDM pairs, shared clocking, paired data behavior, and local 100 nF / 10 µF decoupling.", { accent: C.teal, bodySize: 14 });
  addCard(slide, 8.86, 3.42, 3.73, 2.39, "System role", "Moves the microphones away from the controller and enables repeatable spatial placement through one 10-pin FPC interface.", { accent: C.teal, bodySize: 14 });
  slide.addText("Design status: ordered PCB design; validate each pair, cable integrity, clock loading, and channel mapping during bring-up.", { x: 0.82, y: 6.16, w: 11.72, h: 0.38, fontSize: 13.5, bold: true, color: C.navy, align: "center", margin: 0, fit: "shrink" });
}

// 6 — Integrated controller
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Board 3 — integrated microphone controller", "Turns the bench prototype into a battery-capable, connectorized recorder");
  drawIntegrated(slide, 0.72, 1.48, 5.30, 3.48);
  const labels = [
    ["USB-C + ESD", 0.74, 5.24, C.blue],
    ["LiPo charge / load share", 2.26, 5.24, C.green],
    ["FPC sensor interface", 4.31, 5.24, C.teal],
  ];
  labels.forEach(([t, x, y, c]) => addPill(slide, t, x, y, t.length > 16 ? 1.93 : 1.40, c, C.white));
  addCard(slide, 6.44, 1.44, 5.92, 4.61, "Integration decisions", "• ESP32-S3-WROOM-1-N8R8 replaces the plug-in dev board\n• MCP73871 battery charging and load sharing\n• Dedicated 3.3 V and 1.8 V regulation\n• 10-position FPC connector for external mic hardware\n• SD interface, USB access, controls, and visible status\n• Mechanical mounting holes and compact enclosure path", { accent: C.green, bodySize: 14.5 });
  slide.addText("Engineering shift", { x: 0.80, y: 6.04, w: 1.65, h: 0.24, fontSize: 11, bold: true, color: C.gray, margin: 0 });
  slide.addText("From “can this record?” to “can this be deployed, powered, connected, and recovered reliably?”", { x: 2.31, y: 5.98, w: 9.94, h: 0.40, fontSize: 16, bold: true, color: C.navy, margin: 0, fit: "shrink" });
}

// 7 — Firmware evolution
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Firmware evolved in five deliberate steps", "Each intermediate build isolated one subsystem before combining them");
  const steps = [
    ["1", "PDM → serial", "Captured raw PCM to a PC with a Python script."],
    ["2", "USB microphone", "Exposed the board as a USB Audio Class device."],
    ["3", "SD diagnostic", "Probed SPI behavior and swept mount speeds."],
    ["4", "Standalone WAV", "Recorded locally with button control and status LEDs."],
    ["5", "BLE + reliability", "Added remote control, telemetry, recovery, and storage guards."],
  ];
  steps.forEach((s, i) => {
    const y = 1.38 + i*1.02;
    slide.addShape(pptx.ShapeType.ellipse, { x: 0.78, y, w: 0.58, h: 0.58, fill: { color: i === 4 ? C.gold : C.navy }, line: { color: i === 4 ? C.gold : C.navy } });
    slide.addText(s[0], { x: 0.78, y: y + 0.13, w: 0.58, h: 0.20, fontSize: 14, bold: true, color: i === 4 ? C.navy : C.white, align: "center", margin: 0 });
    if (i < steps.length - 1) slide.addShape(pptx.ShapeType.line, { x: 1.07, y: y + 0.58, w: 0, h: 0.44, line: { color: "AAB8C6", width: 2 } });
    slide.addText(s[1], { x: 1.62, y: y + 0.03, w: 2.52, h: 0.28, fontSize: 17, bold: true, color: C.navy, margin: 0 });
    slide.addText(s[2], { x: 4.15, y: y + 0.01, w: 7.94, h: 0.42, fontSize: 14.5, color: C.ink, margin: 0, fit: "shrink" });
  });
  slide.addShape(pptx.ShapeType.roundRect, { x: 8.30, y: 6.23, w: 4.02, h: 0.46, fill: { color: C.greenLight }, line: { color: C.green } });
  slide.addText("Current recorder: bench validated and working", { x: 8.46, y: 6.34, w: 3.71, h: 0.18, fontSize: 11.5, bold: true, color: C.green, align: "center", margin: 0, fit: "shrink" });
}

// 8 — Architecture
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "The key reliability fix was separating capture from storage", "SD writes are bursty; microphone sampling cannot wait");
  const blocks = [
    [0.63, 1.72, 2.05, 1.26, "PDM microphones", "48 kHz stereo\n16-bit PCM", C.teal],
    [3.12, 1.72, 2.06, 1.26, "I²S + DMA", "Hardware intake\ndeepened queue", C.blue],
    [5.62, 1.72, 2.06, 1.26, "Core 0 reader", "Never touches\nthe SD card", C.navy],
    [8.12, 1.72, 2.06, 1.26, "128 KB pool", "32 × 4 KB\n≈680 ms headroom", C.gold],
    [10.62, 1.72, 2.06, 1.26, "Core 1 writer", "WAV + periodic\nflush/header update", C.green],
  ];
  blocks.forEach((b, i) => {
    slide.addShape(pptx.ShapeType.roundRect, { x: b[0], y: b[1], w: b[2], h: b[3], fill: { color: i === 3 ? C.goldLight : C.white }, line: { color: b[6], width: 2 } });
    slide.addText(b[4], { x: b[0] + 0.14, y: b[1] + 0.18, w: b[2] - 0.28, h: 0.28, fontSize: 15, bold: true, color: C.navy, align: "center", margin: 0, fit: "shrink" });
    slide.addText(b[5], { x: b[0] + 0.14, y: b[1] + 0.61, w: b[2] - 0.28, h: 0.43, fontSize: 11.5, color: C.gray, align: "center", margin: 0, fit: "shrink" });
    if (i < blocks.length - 1) addArrow(slide, b[0] + b[2] + 0.13, 2.15, 0.27, 0.32, C.gray);
  });
  addCard(slide, 0.74, 3.62, 5.85, 2.26, "Failure observed", "A slow SD transaction could exceed the I²S DMA buffering. Samples were silently lost, so playback sounded sped up with clicks and pops.", { accent: C.red, fill: C.redLight, line: "EDC4C4", bodySize: 15 });
  addCard(slide, 6.76, 3.62, 5.85, 2.26, "Result after redesign", "The reader runs continuously while storage latency consumes buffer headroom. Average SD throughput comfortably exceeds the 192 kB/s audio stream.", { accent: C.green, fill: C.greenLight, line: "BFDCC9", bodySize: 15 });
  slide.addText("Control plane: button + BLE commands → start/stop  |  status path: LEDs + 500 ms BLE heartbeat", { x: 1.05, y: 6.26, w: 11.25, h: 0.34, fontSize: 13.5, bold: true, color: C.navy, align: "center", margin: 0, fit: "shrink" });
}

// 9 — Troubleshooting
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Troubleshooting that materially changed the design", "The project became robust by reproducing failures and adding explicit recovery paths");
  const rows = [
    ["Sped-up audio / clicks", "SD writes blocked capture", "Dedicated core-0 reader + 128 KB queue"],
    ["SD failed after reset", "Card left in partial SPI transaction", "Send ≥74 clocks before every mount"],
    ["Level LED froze with no card", "Full mount retry ran every 50 ms", "Separate 50 ms probe from 1 s remount"],
    ["Pulled card ruined whole WAV", "Header size updated only at stop", "Refresh WAV header every 1 s"],
    ["Old take overwritten", "Flaky remount restarted filename scan", "Monotonic in-RAM recording index"],
    ["No serial / build too large", "Board options were wrong", "CDCOnBoot=cdc + huge_app partition"],
    ["Upload port busy", "IDE daemon held COM port", "Stop the background Arduino CLI process"],
  ];
  const x0 = 0.62, widths = [3.20, 4.00, 4.67], rowH = 0.69;
  ["Observed problem", "Root cause", "Fix / lesson"].forEach((t, i) => {
    const x = x0 + widths.slice(0, i).reduce((a, b) => a+b, 0);
    slide.addShape(pptx.ShapeType.rect, { x, y: 1.35, w: widths[i], h: 0.54, fill: { color: C.navy }, line: { color: C.white, width: 0.5 } });
    slide.addText(t, { x: x + 0.12, y: 1.50, w: widths[i] - 0.24, h: 0.20, fontSize: 12.5, bold: true, color: C.white, margin: 0 });
  });
  rows.forEach((r, ri) => {
    const y = 1.89 + ri*rowH;
    r.forEach((t, i) => {
      const x = x0 + widths.slice(0, i).reduce((a, b) => a+b, 0);
      slide.addShape(pptx.ShapeType.rect, { x, y, w: widths[i], h: rowH, fill: { color: ri % 2 ? "F0F4F8" : C.white }, line: { color: "D8E1EA", width: 0.5 } });
      slide.addText(t, { x: x + 0.12, y: y + 0.13, w: widths[i] - 0.24, h: rowH - 0.18, fontSize: 11.4, bold: i === 0, color: i === 2 ? C.green : C.ink, margin: 0, fit: "shrink" });
    });
  });
}

// 10 — Current system
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "What the recorder can do now", "Bench-tested on the custom ESP32-S3 PCB");
  const items = [
    ["AUDIO", "48 kHz • stereo • 16-bit PCM", "Standard incrementing WAV files"],
    ["CONTROL", "Button or Bluetooth LE", "Self-contained Web Bluetooth remote"],
    ["PROOF", "Live byte counter", "Confirms data is actually reaching the card"],
    ["STORAGE", "20 MHz SPI on a 32 GB card", "200 MB warning / 50 MB hard stop"],
    ["RECOVERY", "Hot-plug inference + periodic headers", "At most ~1 s tail loss on card removal"],
    ["STATUS", "Three LEDs + 500 ms heartbeat", "Recording, SD, free space, and error state"],
  ];
  items.forEach((it, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.70 + col*6.10, y = 1.42 + row*1.63;
    slide.addShape(pptx.ShapeType.roundRect, { x, y, w: 5.55, h: 1.28, fill: { color: C.white }, line: { color: "D8E1EA" } });
    addPill(slide, it[0], x + 0.18, y + 0.18, 1.05, [C.blue, C.teal, C.green][row], C.white);
    slide.addText(it[1], { x: x + 1.42, y: y + 0.17, w: 3.88, h: 0.30, fontSize: 14.5, bold: true, color: C.navy, margin: 0, fit: "shrink" });
    slide.addText(it[2], { x: x + 1.42, y: y + 0.62, w: 3.88, h: 0.30, fontSize: 12, color: C.gray, margin: 0, fit: "shrink" });
  });
  slide.addShape(pptx.ShapeType.roundRect, { x: 2.52, y: 6.36, w: 8.28, h: 0.42, fill: { color: C.greenLight }, line: { color: C.green } });
  slide.addText("Known-good boot: SD mounted at 20 MHz → BLE advertising → ready to record", { x: 2.72, y: 6.46, w: 7.88, h: 0.18, fontSize: 12.2, bold: true, color: C.green, align: "center", margin: 0, fit: "shrink" });
}

// 11 — Damping screen
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Material damping check — feasibility only", "A quick screen to learn what was possible and verify that the recorder produced analyzable data");
  slide.addImage({ path: dampingFigure, x: 0.64, y: 1.36, w: 7.35, h: 4.77 });
  addCard(slide, 8.32, 1.36, 4.28, 2.15, "What was done", "Nine coverings × ambient / low / high hairdryer conditions. One short recording per combination; the source was hand-positioned.", { accent: C.blue, bodySize: 13.8 });
  addCard(slide, 8.32, 3.72, 4.28, 2.15, "Only takeaway", "Bare pop-filter fabric looked promising (~12.5 dB lower recorded level than lid-off under high airflow). This is not calibrated attenuation or a scientific treatment comparison.", { accent: C.gold, fill: C.goldLight, bodySize: 13.8 });
  slide.addShape(pptx.ShapeType.roundRect, { x: 2.08, y: 6.30, w: 9.23, h: 0.45, fill: { color: C.redLight }, line: { color: C.red } });
  slide.addText("Presentation framing: engineering proof-of-concept and material down-selection—not a validated acoustic experiment.", { x: 2.28, y: 6.41, w: 8.83, h: 0.18, fontSize: 11.8, bold: true, color: C.red, align: "center", margin: 0, fit: "shrink" });
}

// 12 — Next steps
{
  const slide = pptx.addSlide("CONTENT");
  addTitle(slide, "Next steps toward deployment", "The core recorder works; the remaining work is board bring-up and application-specific validation");
  const steps = [
    ["1", "Define deployment", "Replace the use-case placeholder with the exact study, placement, duration, and channel requirements."],
    ["2", "Bring up ordered boards", "Verify power rails → USB/flash → PDM clock/data → SD → BLE → multi-mic channel map."],
    ["3", "Connect the flex array", "Measure clock integrity, cable behavior, channel pairing, and simultaneous capture limits."],
    ["4", "Package the system", "Finalize mounting, enclosure, strain relief, acoustic opening, and environmental protection."],
    ["5", "Run a controlled pilot", "Use repeatable geometry, metadata, timing, and a validation recording before field deployment."],
  ];
  steps.forEach((s, i) => {
    const y = 1.33 + i*0.93;
    slide.addShape(pptx.ShapeType.roundRect, { x: 0.72, y, w: 11.90, h: 0.72, fill: { color: i === 0 ? C.goldLight : C.white }, line: { color: i === 0 ? C.gold : "D8E1EA" } });
    slide.addShape(pptx.ShapeType.ellipse, { x: 0.94, y: y + 0.11, w: 0.49, h: 0.49, fill: { color: i === 0 ? C.gold : C.navy }, line: { color: i === 0 ? C.gold : C.navy } });
    slide.addText(s[0], { x: 0.94, y: y + 0.23, w: 0.49, h: 0.17, fontSize: 12, bold: true, color: i === 0 ? C.navy : C.white, align: "center", margin: 0 });
    slide.addText(s[1], { x: 1.67, y: y + 0.16, w: 2.25, h: 0.25, fontSize: 15.5, bold: true, color: C.navy, margin: 0, fit: "shrink" });
    slide.addText(s[2], { x: 4.03, y: y + 0.14, w: 8.22, h: 0.35, fontSize: 12.3, color: C.ink, margin: 0, fit: "shrink" });
  });
  slide.addText("Main message", { x: 0.80, y: 6.27, w: 1.35, h: 0.24, fontSize: 11, bold: true, color: C.gray, margin: 0 });
  slide.addText("The project is now a working recording platform—not just a microphone breakout—and its reliability problems have defined the final hardware and firmware architecture.", { x: 2.14, y: 6.18, w: 10.04, h: 0.48, fontSize: 14.5, bold: true, color: C.navy, margin: 0, fit: "shrink" });
}

pptx.writeFile({ fileName: outPath });

