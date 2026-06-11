import test from "node:test";
import assert from "node:assert/strict";
import { rm } from "fs/promises";
import path from "path";
import {
  normalizeVariantPackRequest,
  planVariantFamilyRecipes,
  readabilityScoreFor,
  scoreVariantRecommendation,
} from "../lib/variant-pack.js";
import { OUTPUT_DIR } from "../lib/paths.js";
import {
  __setVariantPackJobRunnerForTests,
  buildVariantPackJobId,
  loadVariantPackJob,
  startVariantPackJob,
} from "../lib/variant-pack-jobs.js";
import { buildPhase2Args } from "../lib/ffmpeg.js";
import { evaluateQualityGate } from "../lib/variant-engine.js";

async function cleanupVariantPackJob(input) {
  var runId = buildVariantPackJobId(input);
  await rm(path.join(OUTPUT_DIR, "variant-pack-jobs", runId + ".json"), { force: true });
  return runId;
}

function deferred() {
  var resolve;
  var reject;
  var promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("normalizes variant pack request defaults", function () {
  var request = normalizeVariantPackRequest({
    source: "sample.mp4",
    variantCount: 500,
    variationPreset: "balanced",
    captionMode: "supplied_hooks",
    suppliedHooks: [" one ", "", "two"],
  });
  assert.equal(request.source, "uploads/sample.mp4");
  assert.equal(request.variantCount, 30);
  assert.equal(request.variationPreset, "balanced");
  assert.equal(request.captionMode, "supplied_hooks");
  assert.deepEqual(request.suppliedHooks, ["one", "two"]);
});

test("variant pack falls back to balanced preset and no captions", function () {
  var request = normalizeVariantPackRequest({
    inputFile: "uploads/sample.mp4",
    variantCount: "bad",
    variationPreset: "wild",
    captionMode: "bad",
  });
  assert.equal(request.variantCount, 8);
  assert.equal(request.variationPreset, "balanced");
  assert.equal(request.captionMode, "none");
});

test("variant pack accepts every operator preset", function () {
  for (var preset of ["caption_safe", "caption_safe_v2", "strong_safe", "subtle", "balanced", "strong"]) {
    var request = normalizeVariantPackRequest({
      source: "sample.mp4",
      variationPreset: preset,
      variantCount: 3,
    });
    assert.equal(request.variationPreset, preset);
    assert.equal(request.variantCount, 3);
  }
});

test("caption-safe variant pack preserves burned captions by default", function () {
  for (var variationPreset of ["caption_safe", "caption_safe_v2", "strong_safe"]) {
    var request = normalizeVariantPackRequest({
      source: "sample.mp4",
      variationPreset,
      captionMode: "none",
    });
    assert.equal(request.variationPreset, variationPreset);
    assert.equal(request.preserveBurnedCaptions, true);
  }
});

test("caption-safe-v2 plans named variant families instead of generic attempts", function () {
  var request = normalizeVariantPackRequest({
    source: "sample.mp4",
    variationPreset: "caption_safe_v2",
    variantCount: 12,
  });
  var recipes = planVariantFamilyRecipes(request);
  assert.equal(request.variationPreset, "caption_safe_v2");
  assert.equal(request.preserveBurnedCaptions, true);
  assert.equal(recipes.length, 12);
  assert.deepEqual([...new Set(recipes.map((item) => item.familyName))], [
    "cover_frame",
    "timing_trim",
    "caption_lane_timing",
    "crop_zoom_family",
    "color_profile",
    "audio_offset",
  ]);
  assert.equal(recipes.every((item) => item.operationSet === "caption_safe_v2"), true);
  assert.equal(recipes.some((item) => item.operationSignals.coverFrameDifferent), true);
  assert.equal(recipes.some((item) => item.operationSignals.temporalDifferent), true);
  assert.equal(recipes.some((item) => item.operationSignals.captionLaneDifferent), true);
  assert.equal(recipes.some((item) => item.operationSignals.cropFamilyDifferent), true);
  assert.equal(recipes.some((item) => item.operationSignals.colorProfileDifferent), true);
  assert.equal(recipes.some((item) => item.operationSignals.audioOffsetDifferent), true);
});

test("caption-safe-v2 preserves original color by default", function () {
  var request = normalizeVariantPackRequest({
    source: "sample.mp4",
    variationPreset: "caption_safe_v2",
    variantCount: 3,
  });
  assert.equal(request.preserveBurnedCaptions, true);

  var args = buildPhase2Args("input.mp4", "output.mp4", "clean", true, true, "organic", "quality", {
    preserveBurnedCaptions: true,
    preserveColor: true,
    colorShiftAmount: 0,
    attemptIndex: 2,
  });
  var filterArg = args[args.indexOf("-vf") + 1] || "";
  assert.equal(filterArg.includes("eq="), false);
  assert.equal(filterArg.includes("hue="), false);
  assert.equal(filterArg.includes("colorbalance="), false);
});

test("caption-safe-v2 defaults allow timing and frame-rate normalization for upload-ready variants", function () {
  var request = normalizeVariantPackRequest({
    source: "sample.mp4",
    variationPreset: "caption_safe_v2",
    variantCount: 3,
  });
  assert.equal(request.preserveBurnedCaptions, true);

  var args = buildPhase2Args("input.mp4", "output.mp4", "clean", true, true, "organic", "quality", {
    preserveBurnedCaptions: true,
    preserveColor: true,
    preserveAudio: true,
    preserveTiming: false,
    preserveGeometry: true,
    preserveFrameRate: false,
    colorShiftAmount: 0,
    speedShiftAmount: 0.6,
    attemptIndex: 2,
  });
  assert.equal(args.includes("-r"), true);
  assert.equal(args[args.indexOf("-r") + 1], "30");
  assert.equal(args.includes("-ss"), true);
  assert.equal(args.includes("-af"), false);
  assert.equal(args.join(" ").includes("eq="), false);
  assert.equal(args.join(" ").includes("crop="), false);
});

test("safe variant families include color-profile coverage without unlocking strong color shifts", function () {
  for (var variationPreset of ["caption_safe_v2", "strong_safe"]) {
    var request = normalizeVariantPackRequest({
      source: "sample.mp4",
      variationPreset,
      variantCount: 12,
    });
    var recipes = planVariantFamilyRecipes(request);
    assert.equal(recipes.some((item) => item.familyName === "color_profile"), true);
    assert.equal(recipes.some((item) => item.operationSignals.colorProfileDifferent), true);
    assert.equal(recipes.every((item) => item.blockedOperations.includes("heavy_color_shift")), true);
  }
});

test("safe variant families include audio-offset coverage without changing audio selection", function () {
  for (var variationPreset of ["caption_safe_v2", "strong_safe"]) {
    var request = normalizeVariantPackRequest({
      source: "sample.mp4",
      variationPreset,
      variantCount: 12,
    });
    var recipes = planVariantFamilyRecipes(request);
    assert.equal(recipes.some((item) => item.familyName === "audio_offset"), true);
    assert.equal(recipes.some((item) => item.operationSignals.audioOffsetDifferent), true);
  }

  var args = buildPhase2Args("input.mp4", "output.mp4", "clean", true, true, "organic", "quality", {
    preserveBurnedCaptions: true,
    preserveColor: true,
    preserveAudio: true,
    colorShiftAmount: 0,
    speedShiftAmount: 0,
    attemptIndex: 2,
  });
  assert.equal(args.includes("-af"), false);
  assert.equal(args.includes("-an"), false);
});

test("safe video args preserve timing, geometry, audio, and frame rate when locked", function () {
  var args = buildPhase2Args("input.mp4", "output.mp4", "clean", true, true, "organic", "quality", {
    preserveBurnedCaptions: true,
    preserveColor: true,
    preserveAudio: true,
    preserveTiming: true,
    preserveGeometry: true,
    preserveFrameRate: true,
    cropAmount: 0,
    colorShiftAmount: 0,
    speedShiftAmount: 0,
    attemptIndex: 7,
  });
  var joined = args.join(" ");
  var filterArg = args[args.indexOf("-vf") + 1] || "";
  assert.equal(args.includes("-ss"), false);
  assert.equal(args.includes("-af"), false);
  assert.equal(args.includes("-an"), false);
  assert.equal(args.includes("-r"), false);
  assert.equal(filterArg.includes("crop="), false);
  assert.equal(filterArg.includes("setpts="), false);
  assert.equal(joined.includes("hflip"), false);
  assert.equal(joined.includes("rotate="), false);
  assert.equal(joined.includes("unsharp="), false);
  assert.equal(joined.includes("noise="), false);
  assert.equal(joined.includes("eq="), false);
  assert.equal(joined.includes("hue="), false);
  assert.equal(joined.includes("colorbalance="), false);
});

test("caption-safe-v2 recommendation can use operation diversity when visual difference is modest", function () {
  var decision = scoreVariantRecommendation({
    preset: "caption_safe_v2",
    uploadReady: true,
    qualityScore: 94,
    differenceScore: 20,
    operationDiversityScore: 32,
    captionReadabilityScore: 96,
    focalSafetyScore: 98,
    warnings: [],
  });
  assert.equal(decision.recommended, true);
  assert.equal(decision.operatorState, "ready");
  assert.equal(decision.reason, "quality_and_operation_diversity_passed");
});

test("caption-safe-v2 recommendation can use operation diversity when visual hash distance is low", function () {
  var decision = scoreVariantRecommendation({
    preset: "caption_safe_v2",
    uploadReady: true,
    qualityScore: 96,
    differenceScore: 2,
    operationDiversityScore: 32,
    captionReadabilityScore: 98,
    focalSafetyScore: 98,
    warnings: [],
  });
  assert.equal(decision.recommended, true);

  var weakOperation = scoreVariantRecommendation({
    preset: "caption_safe_v2",
    uploadReady: true,
    qualityScore: 96,
    differenceScore: 2,
    operationDiversityScore: 12,
    captionReadabilityScore: 98,
    focalSafetyScore: 98,
    warnings: [],
  });
  assert.equal(weakOperation.recommended, false);
  assert.equal(weakOperation.blockingReasons.includes("operation_diversity_below_minimum"), true);
}
);

test("quality gate can admit safe operation-diversity candidates before v2 scoring", function () {
  var decision = evaluateQualityGate({
    qualityRetained: 96,
    differenceFromOriginal: 1,
    maxCrossVariantSimilarity: 1,
    reelsScore: 100,
    checks: [],
    warnings: [],
  }, {
    enabled: true,
    minQuality: 90,
    minDifference: 20,
    maxCrossSimilarity: 0.99,
    maxAttempts: 8,
    allowLowVisualDifference: true,
    allowHighCrossSimilarity: true,
  });

  assert.equal(decision.passed, true);
}
);

test("caption readability is not penalized for intentional source difference", function () {
  var score = readabilityScoreFor({
    validation: { checks: [] },
    qa: { warnings: [] },
    mediaInfo: { bitrate: 8000000 },
    metrics: { available: true, ssim: 0.72 },
  });
  assert.equal(score, 100);
});

test("caption-safe-v2 enforces high-level default thresholds", function () {
  var decision = scoreVariantRecommendation({
    preset: "caption_safe_v2",
    uploadReady: true,
    qualityScore: 90,
    differenceScore: 20,
    operationDiversityScore: 25,
    captionReadabilityScore: 95,
    focalSafetyScore: 95,
    warnings: [],
  });
  assert.equal(decision.recommended, true);

  var lowQuality = scoreVariantRecommendation({
    preset: "caption_safe_v2",
    uploadReady: true,
    qualityScore: 89,
    differenceScore: 40,
    operationDiversityScore: 50,
    captionReadabilityScore: 99,
    focalSafetyScore: 99,
  });
  assert.equal(lowQuality.recommended, false);
  assert.equal(lowQuality.blockingReasons.includes("quality_below_minimum"), true);
});

test("caption-safe-v2 blocks unsafe transform signals", function () {
  var decision = scoreVariantRecommendation({
    preset: "caption_safe_v2",
    uploadReady: true,
    qualityScore: 96,
    differenceScore: 40,
    operationDiversityScore: 50,
    captionReadabilityScore: 96,
    focalSafetyScore: 95,
    operationSignals: { horizontalFlip: true },
  });
  assert.equal(decision.recommended, false);
  assert.equal(decision.operatorState, "fix");
  assert.equal(decision.blockingReasons.includes("unsafe_transform"), true);
});

test("variant pack job start returns run id before long work and supports idempotent polling", async function () {
  var input = {
    source: "uploads/job-start-sample.mp4",
    variantCount: 2,
    variationPreset: "caption_safe_v2",
    captionMode: "none",
    preserveBurnedCaptions: true,
    idempotencyKey: "unit-job-start-idempotent",
  };
  await cleanupVariantPackJob(input);
  var gate = deferred();
  var calls = 0;
  __setVariantPackJobRunnerForTests(async () => {
    calls += 1;
    await gate.promise;
    return {
      schema: "contentforge.variant_pack.v2",
      runId: "inner_run_1",
      outputDir: "/tmp/contentforge-job-test",
      results: [],
    };
  });
  try {
    var started = await startVariantPackJob(input);
    var duplicate = await startVariantPackJob(input);

    assert.equal(started.runId, duplicate.runId);
    assert.equal(["queued", "running"].includes(started.status), true);
    assert.equal(["queued", "running"].includes(duplicate.status), true);
    assert.equal(started.pollUrl, "/api/variant-pack/jobs/" + started.runId);
    assert.equal(calls, 1);

    gate.resolve();
    var terminal = null;
    for (var index = 0; index < 20; index++) {
      terminal = await loadVariantPackJob(started.runId);
      if (terminal.status === "succeeded") break;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    assert.equal(terminal.status, "succeeded");
    assert.equal(terminal.report.runId, "inner_run_1");
    assert.deepEqual(terminal.artifacts, []);
  } finally {
    __setVariantPackJobRunnerForTests(null);
    await cleanupVariantPackJob(input);
  }
});

test("variant pack job records failed terminal state without rerunning duplicate request", async function () {
  var input = {
    source: "uploads/job-failure-sample.mp4",
    variantCount: 1,
    variationPreset: "caption_safe_v2",
    idempotencyKey: "unit-job-failed-terminal",
  };
  await cleanupVariantPackJob(input);
  var calls = 0;
  __setVariantPackJobRunnerForTests(async () => {
    calls += 1;
    throw new Error("simulated variant job failure");
  });
  try {
    var started = await startVariantPackJob(input);
    var terminal = null;
    for (var index = 0; index < 20; index++) {
      terminal = await loadVariantPackJob(started.runId);
      if (terminal.status === "failed") break;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    var duplicate = await startVariantPackJob(input);

    assert.equal(terminal.status, "failed");
    assert.equal(terminal.error, "simulated variant job failure");
    assert.equal(duplicate.runId, started.runId);
    assert.equal(duplicate.status, "failed");
    assert.equal(calls, 1);
  } finally {
    __setVariantPackJobRunnerForTests(null);
    await cleanupVariantPackJob(input);
  }
});
