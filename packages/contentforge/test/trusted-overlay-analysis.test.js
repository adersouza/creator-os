import test from "node:test";
import assert from "node:assert/strict";

import { runTrustedCaptionOverlayAudit } from "../lib/similarity.js";

function highContrastFrame() {
  var width = 180;
  var height = 320;
  var data = Buffer.alloc(width * height * 3);
  for (var y = 0; y < height; y += 1) {
    for (var x = 0; x < width; x += 1) {
      var value = x % 8 < 4 ? 255 : 0;
      var offset = ((y * width) + x) * 3;
      data[offset] = value;
      data[offset + 1] = value;
      data[offset + 2] = value;
    }
  }
  return { width, height, data };
}

function providers(ocrForTime) {
  return {
    frameProvider: async function (_filePath, timeSec) {
      return { ...highContrastFrame(), timeSec };
    },
    pngFrameProvider: async function (_filePath, timeSec) {
      return { width: 360, height: 640, data: Buffer.from("png"), timeSec };
    },
    ocrProvider: async function (_png, file, timeSec) {
      return ocrForTime({ file, timeSec });
    },
    sampleTimes: [0.4, 1.4, 2.4],
  };
}

function measuredBox(text, timeSec, overrides = {}) {
  return {
    file: "output.mp4",
    timeSec,
    ocrText: text,
    confidence: 96,
    box: { x: 80, y: 260, w: 200, h: 48 },
    frame: { width: 360, height: 640 },
    ...overrides,
  };
}

test("measures a timed multi-frame overlay sequence separately from its verdict", async function () {
  var result = await runTrustedCaptionOverlayAudit({
    filePath: "/read-only/output.mp4",
    durationSeconds: 3,
  }, providers(function ({ timeSec }) {
    var text = timeSec < 1 ? "men stop doing this" : "pov one drink later";
    return {
      available: true,
      engine: "fixture_ocr",
      engineVersion: "1.0.0",
      preprocessing: ["original"],
      boxes: [measuredBox(text, timeSec)],
    };
  }));

  assert.equal(result.available, true);
  assert.equal(result.passed, true, JSON.stringify(result.blockingReasons));
  assert.equal(result.sampling.coverageRatio, 1);
  assert.equal(result.sampling.detectionCoverageRatio, 1);
  assert.deepEqual(result.timedSequence.map(function (item) { return item.text; }), [
    "men stop doing this",
    "pov one drink later",
  ]);
  assert.equal(result.timedSequence[1].sampledFrameCount, 2);
  assert.equal(result.frames.length, 3);
  assert.equal(result.frames[0].boxes[0].confidence, 96);
  assert.equal(result.frames[0].boxes[0].safeZoneIssues.length, 0);
  assert.equal(result.readability.passed, true);
  assert.equal(result.safeZone.passed, true);
});

test("fails closed when the OCR tool is missing", async function () {
  var result = await runTrustedCaptionOverlayAudit({
    filePath: "/read-only/output.mp4",
    durationSeconds: 3,
  }, providers(function () {
    return {
      available: false,
      requestedEngine: "tesseract",
      error: "spawn tesseract ENOENT",
      boxes: [],
    };
  }));

  assert.equal(result.available, false);
  assert.equal(result.reason, "overlay_ocr_unavailable");
  assert.equal(result.sampling.coverageRatio, 0);
  assert.equal(result.unavailableFrames.length, 3);
  assert.match(result.unavailableFrames[0].error, /ENOENT/);
});

test("fails closed for an unsupported OCR engine instead of using heuristic evidence", async function () {
  var result = await runTrustedCaptionOverlayAudit({
    filePath: "/read-only/output.mp4",
    durationSeconds: 3,
  }, providers(function () {
    return {
      available: false,
      requestedEngine: "operator_json",
      error: "Unsupported OCR engine: operator_json",
      boxes: [],
    };
  }));

  assert.equal(result.available, false);
  assert.equal(result.reason, "overlay_ocr_unavailable");
  assert.equal(result.unavailableFrames[0].requestedEngine, "operator_json");
  assert.match(result.unavailableFrames[0].error, /Unsupported OCR engine/);
});

test("blocks safe-zone and measured face overlap without inventing body geometry", async function () {
  var faceTrackBoxes = [0.4, 1.4, 2.4].map(function (timeSeconds) {
    return {
      timeSeconds,
      box: { x: 250, y: 500, w: 100, h: 120 },
      frame: { width: 360, height: 640 },
    };
  });
  var result = await runTrustedCaptionOverlayAudit({
    filePath: "/read-only/output.mp4",
    durationSeconds: 3,
    faceTrackBoxes,
  }, providers(function ({ timeSec }) {
    return {
      available: true,
      engine: "fixture_ocr",
      engineVersion: "1.0.0",
      preprocessing: ["original"],
      boxes: [measuredBox("unsafe caption", timeSec, {
        box: { x: 290, y: 560, w: 65, h: 48 },
      })],
    };
  }));

  assert.equal(result.available, true);
  assert.equal(result.passed, false);
  assert.equal(result.safeZone.passed, false);
  assert.equal(result.subjectOverlap.faceGeometryAvailable, true);
  assert.equal(result.subjectOverlap.faceOverlapPassed, false);
  assert.equal(result.subjectOverlap.bodyGeometryAvailable, false);
  assert.equal(result.subjectOverlap.bodyReason, "trusted_body_geometry_analyzer_unavailable");
  assert.equal(result.blockingReasons.includes("overlay_safe_zone_violation"), true);
  assert.equal(result.blockingReasons.includes("overlay_face_overlap"), true);
});
