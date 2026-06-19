import test from "node:test";
import assert from "node:assert/strict";
import { buildDetectorVerdicts, buildReadinessSummary, buildWatchabilityWarnings } from "../app/api/similarity/route.js";

test("detector failures are review-only by default but blocking for Campaign Factory", function () {
  var results = {
    pdq: {
      available: true,
      stats: {
        avgDistance: 18,
        minDistance: 18,
        crossCollisions: 0,
        crossSafeTargetViolations: 0,
      },
    },
    sscd: {
      available: true,
      stats: {
        avgSimilarity: 0.82,
        maxSimilarity: 0.82,
        crossVariantCollisions: 0,
        crossVariantSafeTargetViolations: 0,
      },
    },
  };

  var defaultVerdicts = buildDetectorVerdicts(results);
  var defaultReadiness = buildReadinessSummary(results, defaultVerdicts);
  var campaignVerdicts = buildDetectorVerdicts(results, "campaign_factory_v1");
  var campaignReadiness = buildReadinessSummary(results, campaignVerdicts, { auditProfile: "campaign_factory_v1" });

  assert.deepEqual(defaultVerdicts, { pdq: "fail", sscd: "fail" });
  assert.equal(defaultReadiness.uploadReady, true);
  assert.deepEqual(defaultReadiness.blockingCodes, []);
  assert.equal(defaultReadiness.warningCodes.includes("pdq_review"), true);
  assert.equal(defaultReadiness.warningCodes.includes("sscd_review"), true);

  assert.deepEqual(campaignVerdicts, { pdq: "fail", sscd: "fail" });
  assert.equal(campaignReadiness.uploadReady, false);
  assert.equal(campaignReadiness.blockingCodes.includes("pdq_failed"), true);
  assert.equal(campaignReadiness.blockingCodes.includes("sscd_failed"), true);
  assert.equal(campaignReadiness.warningCodes.includes("pdq_review"), false);
});

test("Campaign Factory blocks sibling detector collisions before upload readiness", function () {
  var results = {
    pdq: {
      available: true,
      stats: {
        minDistance: 88,
        crossCollisions: 1,
        crossSafeTargetViolations: 1,
      },
    },
    sscd: {
      available: true,
      stats: {
        maxSimilarity: 0.1,
        crossVariantCollisions: 1,
        crossVariantSafeTargetViolations: 1,
      },
    },
  };
  var verdicts = buildDetectorVerdicts(results, "campaign_factory_v1");
  var readiness = buildReadinessSummary(results, verdicts, { auditProfile: "campaign_factory_v1" });

  assert.deepEqual(verdicts, { pdq: "fail", sscd: "fail" });
  assert.equal(readiness.uploadReady, false);
  assert.equal(readiness.blockingCodes.includes("pdq_sibling_collision"), true);
  assert.equal(readiness.blockingCodes.includes("sscd_sibling_collision"), true);
  assert.equal(readiness.operatorLabels.blocking.every((item) => item.operatorLabel === "blocking"), true);
});

test("quality-floor warnings are advisory by default and blocking for Campaign Factory", function () {
  var results = {
    safeZone: {
      warnings: [{ code: "caption_too_close_to_edge", label: "Caption edge", message: "caption too close" }],
    },
    readability: {
      warnings: [{ code: "caption_low_contrast", label: "Caption contrast", message: "caption contrast low" }],
    },
    creativeQuality: {
      warnings: [{ code: "creative_hook_missing", label: "Weak hook", message: "hook missing" }],
    },
  };
  var verdicts = { safeZone: "warn", readability: "warn", creativeQuality: "warn" };

  var defaultReadiness = buildReadinessSummary(results, verdicts);
  var campaignReadiness = buildReadinessSummary(results, verdicts, { auditProfile: "campaign_factory_v1" });

  assert.equal(defaultReadiness.uploadReady, true);
  assert.equal(defaultReadiness.warningCodes.includes("caption_too_close_to_edge"), true);
  assert.equal(defaultReadiness.warningCodes.includes("creative_hook_missing"), true);
  assert.deepEqual(defaultReadiness.blockingCodes, []);

  assert.equal(campaignReadiness.uploadReady, false);
  assert.equal(campaignReadiness.blockingCodes.includes("caption_too_close_to_edge"), true);
  assert.equal(campaignReadiness.blockingCodes.includes("caption_low_contrast"), true);
  assert.equal(campaignReadiness.blockingCodes.includes("creative_hook_missing"), true);
  assert.equal(campaignReadiness.topWarnings.some((item) => item.code === "creative_hook_missing"), false);
});

test("watchability warnings include quality metric and QA signal reasons", function () {
  var warnings = buildWatchabilityWarnings({
    qualityMetrics: {
      available: true,
      vmaf: 61,
      cambi: { value: 19 },
    },
    qaSignals: {
      loudness: { inputI: -35, inputTp: 1 },
      warnings: ["black segment from 0s to 2s", "silence detected", "letterbox detected"],
    },
    fileName: "candidate.mp4",
  });
  var codes = warnings.map((item) => item.code);

  assert.equal(codes.includes("video_vmaf_low"), true);
  assert.equal(codes.includes("video_cambi_banding"), true);
  assert.equal(codes.includes("audio_loudness_out_of_range"), true);
  assert.equal(codes.includes("audio_true_peak_too_hot"), true);
  assert.equal(codes.includes("watchability_black_segment"), true);
  assert.equal(codes.includes("audio_long_silence"), true);
  assert.equal(codes.includes("framing_letterbox_or_crop"), true);
});
