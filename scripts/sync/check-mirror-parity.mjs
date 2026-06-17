// Parity gate: FAIL if any monorepo mirror differs from its source split repo
// (at the pinned SHA) or was hand-edited. One diff catches both directions.
//
// Usage:
//   node scripts/sync/check-mirror-parity.mjs            blocking: exit 1 on any drift
//   node scripts/sync/check-mirror-parity.mjs --report   report-only: print drift, exit 0
//
// Strategy: re-materialize each mirror from its pinned source SHA into a temp
// dir, then diff against the committed mirror on disk. No network, deterministic.

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig, materialize, diffMirror } from "./mirror-lib.mjs";

const reportOnly = process.argv.includes("--report");
const cfg = loadConfig();
if (!cfg.mirrors.length) {
  console.log("No committed mirrors configured; parity check is satisfied.");
  process.exit(0);
}
const temp = mkdtempSync(join(tmpdir(), "mirror-parity-"));

let drift = 0;
const summary = [];
try {
  for (const m of cfg.mirrors) {
    materialize(m, temp); // expected tree at temp/<mirrorPath>
    const { missing, changed, extra } = diffMirror(m, temp);
    const n = missing.length + changed.length + extra.length;
    drift += n;
    summary.push({ mirror: m.mirrorPath, missing: missing.length, changed: changed.length, extra: extra.length });
    if (n > 0) {
      console.log(`\nDRIFT  ${m.mirrorPath}  (source ${m.sourceRepoPath}@${m.sourceCommit.slice(0, 8)})`);
      const show = (label, arr) => {
        if (!arr.length) return;
        console.log(`  ${label} (${arr.length}):`);
        for (const p of arr.slice(0, 25)) console.log(`    ${p}`);
        if (arr.length > 25) console.log(`    … +${arr.length - 25} more`);
      };
      show("missing-from-mirror (source has, mirror lacks)", missing);
      show("changed (mirror differs from source / hand-edited)", changed);
      show("extra-in-mirror (mirror has, source lacks)", extra);
    } else {
      console.log(`OK     ${m.mirrorPath}`);
    }
  }
} finally {
  rmSync(temp, { recursive: true, force: true });
}

console.log("\nsummary:");
for (const s of summary) {
  console.log(`  ${s.mirror}: missing=${s.missing} changed=${s.changed} extra=${s.extra}`);
}

if (drift > 0) {
  console.log(`\n${drift} mirror file(s) out of parity.`);
  if (reportOnly) {
    console.log("report-only mode: not failing. Run `node scripts/sync/mirror-sync.mjs` to regenerate mirrors from source.");
    process.exit(0);
  }
  console.log("FAIL: mirrors are not in parity with their source repos.");
  console.log("Fix: never hand-edit mirrors. Edit the source split repo, then `node scripts/sync/mirror-sync.mjs --update`.");
  process.exit(1);
}
console.log("\nall mirrors in parity.");
