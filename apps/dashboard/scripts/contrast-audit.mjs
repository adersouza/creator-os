#!/usr/bin/env node
/**
 * APCA contrast audit for the Juno33 design system.
 *
 * Computes APCA Lc for every foreground token × every material thickness
 * × both modes. Materials are translucent so we alpha-composite them on
 * top of the page substrate before measuring.
 *
 * Usage: node scripts/contrast-audit.mjs
 *
 * APCA implementation: APCA-W3 v0.1.9 reference math.
 * Reference thresholds (Andrew Somers, git.apcacontrast.com):
 *   Lc 90  body text below 14px
 *   Lc 75  body text 14–18px regular weight
 *   Lc 60  text 16px+ medium / 18px+ regular   (~WCAG 4.5:1 equiv)
 *   Lc 45  large text 24px+ or non-text UI     (~WCAG 3:1 equiv)
 *   Lc 30  decorative / invisible
 *
 * Sign convention: positive Lc = dark text on light bg, negative = light on dark.
 * We work in absolute value for thresholds.
 */

// ────────── APCA-W3 v0.1.9 reference implementation ──────────

function sRGBtoY([r, g, b]) {
  const mainTRC = 2.4;
  const sR = 0.2126729;
  const sG = 0.7151522;
  const sB = 0.0721750;
  return (
    sR * Math.pow(r / 255, mainTRC) +
    sG * Math.pow(g / 255, mainTRC) +
    sB * Math.pow(b / 255, mainTRC)
  );
}

function apcaContrast(yText, yBg) {
  const normBG = 0.56;
  const normTXT = 0.57;
  const revTXT = 0.62;
  const revBG = 0.65;
  const blkThrs = 0.022;
  const blkClmp = 1.414;
  const scaleBoW = 1.14;
  const scaleWoB = 1.14;
  const loBoWoffset = 0.027;
  const loWoBoffset = 0.027;
  const deltaYmin = 0.0005;
  const loClip = 0.1;

  if (yText < blkThrs) yText += Math.pow(blkThrs - yText, blkClmp);
  if (yBg < blkThrs) yBg += Math.pow(blkThrs - yBg, blkClmp);
  if (Math.abs(yBg - yText) < deltaYmin) return 0;

  let out;
  if (yBg > yText) {
    const SAPC = (Math.pow(yBg, normBG) - Math.pow(yText, normTXT)) * scaleBoW;
    out = SAPC < loClip ? 0 : SAPC - loBoWoffset;
  } else {
    const SAPC = (Math.pow(yBg, revBG) - Math.pow(yText, revTXT)) * scaleWoB;
    out = SAPC > -loClip ? 0 : SAPC + loWoBoffset;
  }
  return out * 100;
}

function lc(textRgb, bgRgb) {
  return apcaContrast(sRGBtoY(textRgb), sRGBtoY(bgRgb));
}

// ────────── Color utilities ──────────

function hexToRgb(hex) {
  const m = hex.replace('#', '').match(/.{2}/g);
  if (!m) throw new Error(`bad hex: ${hex}`);
  return m.map((s) => parseInt(s, 16));
}

function rgbToHex([r, g, b]) {
  return '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
}

/** Composite translucent fg over opaque bg. fg = [r,g,b,a]. */
function composite(fgRgba, bgRgb) {
  const a = fgRgba[3];
  return [
    fgRgba[0] * a + bgRgb[0] * (1 - a),
    fgRgba[1] * a + bgRgb[1] * (1 - a),
    fgRgba[2] * a + bgRgb[2] * (1 - a),
  ];
}

// ────────── Tokens (verbatim from src/index.css, post-2026-04-27 calibration) ──────────

const SUBSTRATE = {
  light: hexToRgb('#F2F0EC'),  // --color-background
  dark: hexToRgb('#0A0A0B'),
};

// Material thicknesses are translucent white over substrate.
// Effective bg = composite(rgba(255,255,255,A), substrate).
const MATERIAL_ALPHA = {
  light: { thin: 0.45, regular: 0.62, thick: 0.85 },
  dark: { thin: 0.035, regular: 0.04, thick: 0.065 },
};

function materialBg(mode, thickness) {
  return composite([255, 255, 255, MATERIAL_ALPHA[mode][thickness]], SUBSTRATE[mode]);
}

// Foreground tokens. Translucent ones are composited against the same
// material they sit on (worst-case).
const FG_TOKENS = {
  light: {
    'foreground (#0A0A0B)': { rgba: [10, 10, 11, 1] },
    'accent / oxblood-deep (#7B1E2E)': { rgba: [123, 30, 46, 1] },
    'oxblood whisper (#C54D2E)': { rgba: [197, 77, 46, 1] },
    'oxblood-bar (#C54D2E)': { rgba: [197, 77, 46, 1] },
    'health-good (#3F6B52)': { rgba: [63, 107, 82, 1] },
    'health-idle warm-patina (#7A7368)': { rgba: [122, 115, 104, 1] },
    'health-warn / gold (#B48A3A)': { rgba: [180, 138, 58, 1] },
    'health-critical (= oxblood whisper)': { rgba: [197, 77, 46, 1] },
    'label-secondary (10,10,11 @0.68)': { rgba: [10, 10, 11, 0.68] },
    'label-tertiary (10,10,11 @0.65)': { rgba: [10, 10, 11, 0.65] },
    'label-quaternary (10,10,11 @0.6)': { rgba: [10, 10, 11, 0.6] },
  },
  dark: {
    'foreground (#FAFAFA)': { rgba: [250, 250, 250, 1] },
    'accent / oxblood (#D85F5F) — calibrated 2026-04-27': { rgba: [216, 95, 95, 1] },
    'oxblood-bar (#F07070) — calibrated 2026-04-27': { rgba: [240, 112, 112, 1] },
    'health-good (#5A8568)': { rgba: [90, 133, 104, 1] },
    'health-idle warm-patina (#8A8068) — calibrated': { rgba: [138, 128, 104, 1] },
    'health-warn (#D0A060)': { rgba: [208, 160, 96, 1] },
    'health-critical (= accent oxblood)': { rgba: [216, 95, 95, 1] },
    'label-secondary (250,250,250 @0.62)': { rgba: [250, 250, 250, 0.62] },
    'label-tertiary (250,250,250 @0.6)': { rgba: [250, 250, 250, 0.6] },
    'label-quaternary (250,250,250 @0.55)': { rgba: [250, 250, 250, 0.55] },
  },
};

// ────────── Audit ──────────

function fmtLc(v) {
  const a = Math.abs(v);
  return (v >= 0 ? ' ' : '-') + a.toFixed(1).padStart(5, ' ');
}

function status(absLc, intent) {
  // Return PASS/WARN/FAIL with a tag for the threshold the surface is meant to clear.
  // intent: 'body' (Lc 60+), 'large' (Lc 45+), 'ui' (Lc 45+ for non-text UI)
  const required = intent === 'body' ? 60 : 45;
  if (absLc >= required) return 'PASS';
  if (absLc >= required - 15) return 'WARN';
  return 'FAIL';
}

const intent = {
  // Map each token name fragment → intended use. Body-text tokens need Lc 60+;
  // accent/UI elements need Lc 45+.
  body: ['foreground', 'label-secondary', 'label-tertiary'],
  large: [], // no large-text tokens called out separately
  ui: ['accent', 'oxblood', 'health', 'label-quaternary', 'oxblood-bar'],
};

function intentFor(tokenName) {
  if (intent.body.some((k) => tokenName.includes(k))) return 'body';
  if (intent.large.some((k) => tokenName.includes(k))) return 'large';
  return 'ui';
}

console.log('\nJUNO33 — APCA contrast audit (2026-04-27 calibration)');
console.log('======================================================\n');

for (const mode of ['light', 'dark']) {
  console.log(`────── ${mode.toUpperCase()} MODE ──────\n`);

  // Show effective material backgrounds
  const bgs = {
    'page substrate': SUBSTRATE[mode],
    'material-thin': materialBg(mode, 'thin'),
    'material-regular': materialBg(mode, 'regular'),
    'material-thick': materialBg(mode, 'thick'),
  };
  console.log('Effective material backgrounds (after compositing on substrate):');
  for (const [name, rgb] of Object.entries(bgs)) {
    console.log(`  ${name.padEnd(20)} ${rgbToHex(rgb)}`);
  }
  console.log();

  // Header
  console.log(
    'Foreground'.padEnd(50) +
      'page'.padStart(7) +
      'thin'.padStart(7) +
      'regular'.padStart(8) +
      'thick'.padStart(7) +
      '   intent'
  );
  console.log('-'.repeat(85));

  for (const [tokenName, { rgba }] of Object.entries(FG_TOKENS[mode])) {
    const i = intentFor(tokenName);
    const cells = [];
    for (const [, bgRgb] of Object.entries(bgs)) {
      // Composite translucent fg against this bg
      const fgComposited = rgba[3] === 1 ? rgba.slice(0, 3) : composite(rgba, bgRgb);
      const v = lc(fgComposited, bgRgb);
      const s = status(Math.abs(v), i);
      const flag = s === 'FAIL' ? '!' : s === 'WARN' ? '~' : ' ';
      cells.push(fmtLc(v) + flag);
    }
    console.log(tokenName.padEnd(50) + cells.join('') + '   ' + i);
  }
  console.log();
}

console.log(
  'Legend: PASS (≥ threshold)  ~ WARN (within 15 of threshold)  ! FAIL (below threshold)'
);
console.log('Thresholds: body Lc 60+, ui/accent Lc 45+, large/decorative Lc 30+');
console.log();
