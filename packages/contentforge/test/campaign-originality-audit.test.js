import test from "node:test";
import assert from "node:assert/strict";
import { __testInternals } from "../lib/campaign-originality-audit.js";

function frameFromLuma(values, width = 4, height = 4) {
  var data = Buffer.alloc(width * height * 3);
  values.forEach(function (value, idx) {
    data[idx * 3] = value;
    data[idx * 3 + 1] = value;
    data[idx * 3 + 2] = value;
  });
  return { width, height, data };
}

test("originality frame scoring remains deterministic for identical inputs", function () {
  var target = [
    frameFromLuma(new Array(16).fill(40)),
    frameFromLuma(new Array(16).fill(180)),
  ];
  var reference = [
    frameFromLuma(new Array(16).fill(40)),
    frameFromLuma(new Array(16).fill(180)),
  ];

  assert.equal(__testInternals.averageFrameSimilarity(target, reference), 100);
  assert.equal(__testInternals.averageSignatureSimilarity(target, reference), 100);
});

test("reference match signals are advisory and deduplicated", function () {
  var signals = __testInternals.referenceMatchSignals({
    duplicateRisk: "high",
    sameOpeningRisk: "medium",
    sameHookRisk: "low",
    sameCoverRisk: "medium",
    sameAudioRisk: "unknown",
    sameTemplateRisk: "high",
  });

  assert.deepEqual(signals.map((item) => item.code), [
    "reference_match_close",
    "reference_match_same_opening",
    "reference_match_same_cover",
    "reference_match_template_reuse",
  ]);
  assert.equal(signals.every((item) => item.severity === "info"), true);
});

test("token similarity and variation notes preserve existing scoring semantics", function () {
  assert.equal(__testInternals.tokenSimilarity("same hook text", "same hook"), 2 / 3);
  assert.deepEqual(__testInternals.variationNotes("low", { opening: "low" }), []);
  assert.equal(__testInternals.riskFromScore(80, 50, 75), "high");
});
