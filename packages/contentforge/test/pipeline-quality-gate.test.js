import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, rm } from "fs/promises";
import path from "path";
import sharp from "sharp";
import { runImagePipeline } from "../lib/pipeline.js";
import { UPLOADS_DIR } from "../lib/paths.js";
import { skipWhenMissingTools } from "./tool-availability.js";

test("image pipeline records quality-gate rejections instead of keeping weak candidates", async function (t) {
  if (skipWhenMissingTools(t, ["ffmpeg"])) return;
  await mkdir(UPLOADS_DIR, { recursive: true });
  var inputName = "quality_gate_source.png";
  var inputPath = path.join(UPLOADS_DIR, inputName);
  await sharp({
    create: {
      width: 720,
      height: 720,
      channels: 3,
      background: { r: 34, g: 110, b: 220 },
    },
  })
    .png()
    .toFile(inputPath);

  var events = [];
  try {
    await runImagePipeline(
      {
        inputFile: inputName,
        numVariants: 1,
        variantPreset: "quality",
        qualityGate: {
          enabled: true,
          minQuality: 0,
          minDifference: 100,
          maxAttempts: 2,
        },
      },
      function (event) {
        events.push(event);
      }
    );

    var complete = events.find((event) => event.type === "complete");
    assert.equal(complete.total, 0);
    assert.equal(complete.attempted, 2);
    assert.equal(complete.failed, 2);
    assert.equal(complete.keptCandidates, 0);
    assert.equal(complete.rejectedCandidates, 2);
    assert.equal(complete.rejectionReasons.difference, 2);
    assert.equal(events.some((event) => event.type === "log" && /rejected/.test(event.text || "")), true);
    await rm(complete.outputDir, { recursive: true, force: true });
  } finally {
    await rm(inputPath, { force: true });
  }
});
