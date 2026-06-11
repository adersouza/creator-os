import test from "node:test";
import assert from "node:assert/strict";
import { buildCreativeQualityAudit } from "../lib/creative-quality-audit.js";

test("creative quality flags generic hook language from OCR text", function () {
  var result = buildCreativeQualityAudit({
    ocr: {
      frameSamples: 3,
      results: [
        {
          timeSec: 0.4,
          ocrText: "WATCH THIS",
          confidence: 92,
          captionBoxes: [{ ocrText: "WATCH THIS" }],
        },
      ],
    },
    coverCandidates: [
      {
        score: 82,
        stats: { brightness: 90, contrast: 50, edgeScore: 12 },
      },
    ],
    readabilityScore: 88,
    hookVisibilityScore: 90,
    hookVisibility: {
      metrics: {
        earlyTextBoxes: 1,
        avgFrameDelta: 12,
      },
    },
    safeZone: {
      metrics: { frameSamples: 3 },
    },
  });

  assert.equal(result.semanticEngine, "heuristic_v1");
  assert.equal(result.modelBacked, false);
  assert.equal(result.verdict, "warn");
  assert.equal(result.hookClarity.text, "WATCH THIS");
  assert.equal(result.hookClarity.warnings.some((item) => item.code === "creative_hook_generic"), true);
  assert.equal(result.warnings.some((item) => item.code === "creative_hook_generic"), true);
  assert.equal(result.subjectVisibility.level !== "weak", true);
});
