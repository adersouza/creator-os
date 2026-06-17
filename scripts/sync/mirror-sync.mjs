// Regenerate monorepo mirrors from their source split repos at the pinned SHA.
// Usage:
//   node scripts/sync/mirror-sync.mjs            regenerate all mirrors in-place
//   node scripts/sync/mirror-sync.mjs --dry-run  materialize to a temp dir, report counts, change nothing
//   node scripts/sync/mirror-sync.mjs --update    bump each sourceCommit to the source repo's current main HEAD, then sync
//   node scripts/sync/mirror-sync.mjs --only <mirrorPath>   limit to one mirror
//
// Source of truth = the split repo. Mirrors are GENERATED. Never hand-edit them.

import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, cpSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { loadConfig, materialize, REPO_ROOT } from "./mirror-lib.mjs";

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const doUpdate = args.includes("--update");
const onlyIdx = args.indexOf("--only");
const only = onlyIdx >= 0 ? args[onlyIdx + 1] : null;

const cfg = loadConfig();
let mirrors = cfg.mirrors;
if (only) mirrors = mirrors.filter((m) => m.mirrorPath === only);
if (mirrors.length === 0) {
  if (!only) {
    console.log("No committed mirrors configured; nothing to sync.");
    process.exit(0);
  }
  console.error(`No mirror matched --only ${only}`);
  process.exit(2);
}

if (doUpdate) {
  // Bump pinned SHAs to current source main, persist mirror-sources.json.
  const raw = JSON.parse(readFileSync(join(REPO_ROOT, "mirror-sources.json"), "utf8"));
  for (const m of raw.mirrors) {
    if (only && m.mirrorPath !== only) continue;
    const repo = resolve(REPO_ROOT, m.sourceRepoPath);
    const head = execFileSync("git", ["-C", repo, "rev-parse", "main"], {
      encoding: "utf8",
    }).trim();
    if (head !== m.sourceCommit) {
      console.log(`update ${m.mirrorPath}: ${m.sourceCommit.slice(0, 8)} -> ${head.slice(0, 8)}`);
      m.sourceCommit = head;
    }
  }
  writeFileSync(
    join(REPO_ROOT, "mirror-sources.json"),
    JSON.stringify(raw, null, 2) + "\n",
  );
  // reload with merged excludes
  mirrors = loadConfig().mirrors.filter((m) => !only || m.mirrorPath === only);
}

const dest = dryRun ? mkdtempSync(join(tmpdir(), "mirror-dry-")) : REPO_ROOT;
let total = 0;
for (const m of mirrors) {
  const { files } = materialize(m, dest);
  total += files.length;
  console.log(
    `${dryRun ? "[dry] " : ""}${m.mirrorPath}  <- ${m.sourceRepoPath}@${m.sourceCommit.slice(0, 8)}  (${files.length} files)`,
  );
}
console.log(`${dryRun ? "[dry] " : ""}done: ${mirrors.length} mirror(s), ${total} files.`);
if (dryRun) {
  console.log(`materialized to ${dest} (left in place for inspection).`);
}
