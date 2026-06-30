#!/usr/bin/env node
// Captures REAL ContentForge audit output for a good + a failure fixture, so the
// campaign<->ContentForge handoff can be tested against genuine CF responses
// (not a hand-written mock) in the python CI job — which has no node.
//
// Refresh the goldens whenever the CF similarity response shape changes:
//   node apps/contentforge/scripts/capture-cf-golden.mjs
// Volatile fields (timings) are stripped so re-captures stay stable.

import { copyFile, mkdir, rm, writeFile } from "fs/promises";
import path from "path";
import { POST } from "../app/api/similarity/route.js";
import { UPLOADS_DIR, LEGACY_FINAL_DIR } from "../lib/paths.js";

const ROOT = path.resolve("test/fixtures/campaign-factory");
const SOURCE_REF = path.join(ROOT, "good", "campaign_factory_avconvert_render.mp4");
const OUT_DIR = path.resolve("../../tests/integration/fixtures/contentforge_audit");

const CASES = [
  { name: "iphone_reel", fixture: "good/iphone_reel_upload_ready.mp4" },
  { name: "corrupt_video", fixture: "failures/corrupt_video.mp4" },
];

function stripVolatile(body) {
  // Drop fields that vary run-to-run so the golden is a stable contract sample.
  const out = { ...body };
  delete out.timings;
  return out;
}

async function capture({ name, fixture }) {
  await mkdir(UPLOADS_DIR, { recursive: true });
  await mkdir(LEGACY_FINAL_DIR, { recursive: true });
  const sourceName = `cf_golden_source_${name}.mp4`;
  const targetName = `cf_golden_${name}_${path.basename(fixture)}`;
  const sourcePath = path.join(UPLOADS_DIR, sourceName);
  const targetPath = path.join(LEGACY_FINAL_DIR, targetName);
  await rm(sourcePath, { force: true });
  await rm(targetPath, { force: true });
  await copyFile(SOURCE_REF, sourcePath);
  await copyFile(path.join(ROOT, fixture), targetPath);

  const request = new Request("http://localhost/api/similarity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: sourceName,
      targetFile: targetName,
      auditProfile: "campaign_factory_v1",
      layers: ["forensics"],
    }),
  });
  const response = await POST(request);
  const body = await response.json();
  const outPath = path.join(OUT_DIR, `${name}.json`);
  await writeFile(outPath, JSON.stringify(stripVolatile(body), null, 2) + "\n");
  await rm(sourcePath, { force: true });
  await rm(targetPath, { force: true });
  console.log(`${name}: overallVerdict=${body.overallVerdict} -> ${outPath}`);
}

await mkdir(OUT_DIR, { recursive: true });
for (const c of CASES) await capture(c);
