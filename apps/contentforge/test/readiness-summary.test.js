import test from "node:test";
import assert from "node:assert/strict";
import {
  buildDetectorVerdicts,
  buildReadinessSummary,
} from "../app/api/similarity/route.js";

test("readiness summary blocks severe compression failures", function () {
  var summary = buildReadinessSummary({
    compression: {
      summary: {
        failed: 3,
        warnings: 0,
      },
    },
  }, {
    compression: "fail",
  });

  assert.equal(summary.uploadReady, false);
  assert.equal(summary.recommendedAction, "reject");
  assert.equal(summary.blockingCodes.includes("compression_gop_review"), true);
  assert.equal(summary.warningCodes.includes("compression_gop_review"), false);
});

test("readiness summary keeps compression and C2PA review signals nonblocking", function () {
  var summary = buildReadinessSummary({
    compression: {
      summary: {
        failed: 1,
        warnings: 1,
      },
    },
    provenance: {
      summary: {
        flagged: 0,
        unavailable: 1,
      },
    },
  }, {
    compression: "warn",
    provenance: "warn",
  });

  assert.equal(summary.uploadReady, true);
  assert.equal(summary.recommendedAction, "review");
  assert.equal(summary.warningCodes.includes("compression_gop_review"), true);
  assert.equal(summary.warningCodes.includes("provenance_c2pa_unavailable"), true);
  assert.equal(summary.blockingCodes.length, 0);
});

test("readiness summary treats similarity layers as review-only signals", function () {
  var summary = buildReadinessSummary({}, {
    sscd: "fail",
    temporal: "fail",
    ssim: "fail",
    pdq: "fail",
  });

  assert.equal(summary.uploadReady, true);
  assert.equal(summary.recommendedAction, "review");
  assert.equal(summary.blockingCodes.length, 0);
  assert.equal(summary.warningCodes.includes("sscd_review"), true);
  assert.equal(summary.warningCodes.includes("temporal_review"), true);
  assert.equal(summary.warningCodes.includes("ssim_review"), true);
  assert.equal(summary.warningCodes.includes("pdq_review"), true);
});

test("campaign profile fails closed when perceptual detectors are unavailable", function () {
  var results = {
    pdq: { available: false, error: "pdqhash missing" },
    sscd: { available: false, error: "model missing" },
  };
  var verdicts = buildDetectorVerdicts(results, "campaign_factory_v1");
  var summary = buildReadinessSummary(results, verdicts, {
    auditProfile: "campaign_factory_v1",
  });

  assert.deepEqual(verdicts, { pdq: "fail", sscd: "fail" });
  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("pdq_unavailable"), true);
  assert.equal(summary.blockingCodes.includes("sscd_unavailable"), true);
});

test("default profile keeps unavailable perceptual detectors advisory", function () {
  var results = {
    pdq: { available: false, error: "pdqhash missing" },
    sscd: { available: false, error: "model missing" },
  };
  var verdicts = buildDetectorVerdicts(results, "default");
  var summary = buildReadinessSummary(results, verdicts, {
    auditProfile: "default",
  });

  assert.deepEqual(verdicts, { pdq: "warn", sscd: "warn" });
  assert.equal(summary.uploadReady, true);
  assert.equal(summary.warningCodes.includes("pdq_review"), true);
  assert.equal(summary.warningCodes.includes("sscd_review"), true);
});

test("campaign detector verdicts use worst-case evidence instead of safe averages", function () {
  var results = {
    pdq: {
      stats: {
        avgDistance: 90,
        minDistance: 12,
        crossCollisions: 0,
        crossSafeTargetViolations: 0,
      },
    },
    sscd: {
      stats: {
        avgSimilarity: 0.1,
        maxSimilarity: 0.82,
        crossVariantCollisions: 0,
        crossVariantSafeTargetViolations: 0,
      },
    },
  };

  assert.deepEqual(buildDetectorVerdicts(results, "campaign_factory_v1"), {
    pdq: "fail",
    sscd: "fail",
  });
  assert.deepEqual(buildDetectorVerdicts(results, "default"), {
    pdq: "pass",
    sscd: "pass",
  });
});

test("campaign readiness emits stable sibling collision blocking codes", function () {
  var results = {
    pdq: {
      stats: {
        avgDistance: 90,
        minDistance: 80,
        crossCollisions: 0,
        crossSafeTargetViolations: 1,
      },
    },
    sscd: {
      stats: {
        avgSimilarity: 0.1,
        maxSimilarity: 0.2,
        crossVariantCollisions: 0,
        crossVariantSafeTargetViolations: 2,
      },
    },
  };
  var verdicts = buildDetectorVerdicts(results, "campaign_factory_v1");
  var summary = buildReadinessSummary(results, verdicts, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(summary.blockingCodes.includes("pdq_sibling_collision"), true);
  assert.equal(summary.blockingCodes.includes("sscd_sibling_collision"), true);
});

test("default profile keeps safe-zone warnings advisory", function () {
  var results = {
    safeZone: {
      verdict: "warn",
      warnings: [
        { code: "caption_too_close_to_edge", message: "caption close to edge", severity: "warn" },
        { code: "caption_overlaps_ui_safe_zone", message: "caption overlaps UI", severity: "warn" },
      ],
    },
  };
  var summary = buildReadinessSummary(results, { safeZone: "warn" }, {
    auditProfile: "default",
  });

  assert.equal(summary.uploadReady, true);
  assert.equal(summary.warningCodes.includes("caption_too_close_to_edge"), true);
  assert.equal(summary.warningCodes.includes("caption_overlaps_ui_safe_zone"), true);
  assert.equal(summary.blockingCodes.length, 0);
});

test("campaign profile blocks safe-zone overlap warnings", function () {
  var results = {
    safeZone: {
      verdict: "warn",
      warnings: [
        { code: "caption_too_close_to_edge", message: "caption close to edge", severity: "warn" },
        { code: "caption_overlaps_ui_safe_zone", message: "caption overlaps UI", severity: "warn" },
      ],
    },
  };
  var summary = buildReadinessSummary(results, { safeZone: "warn" }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("caption_too_close_to_edge"), true);
  assert.equal(summary.blockingCodes.includes("caption_overlaps_ui_safe_zone"), true);
  assert.equal(summary.warningCodes.includes("caption_too_close_to_edge"), false);
});

test("default profile keeps watchability warnings advisory", function () {
  var results = {
    readability: {
      verdict: "warn",
      warnings: [
        { code: "caption_text_too_small", message: "caption too small", severity: "warn" },
        { code: "caption_low_contrast", message: "caption low contrast", severity: "warn" },
      ],
    },
    hookVisibility: {
      verdict: "warn",
      warnings: [
        { code: "weak_first_3_seconds", message: "weak hook", severity: "warn" },
      ],
    },
    creativeQuality: {
      verdict: "warn",
      warnings: [
        { code: "creative_quality_review", message: "creative review", severity: "warn" },
      ],
    },
  };
  var summary = buildReadinessSummary(results, {
    readability: "warn",
    hookVisibility: "warn",
    creativeQuality: "warn",
  }, {
    auditProfile: "default",
  });

  assert.equal(summary.uploadReady, true);
  assert.equal(summary.warningCodes.includes("caption_text_too_small"), true);
  assert.equal(summary.warningCodes.includes("caption_low_contrast"), true);
  assert.equal(summary.warningCodes.includes("weak_first_3_seconds"), true);
  assert.equal(summary.warningCodes.includes("creative_quality_review"), true);
  assert.equal(summary.blockingCodes.length, 0);
});

test("campaign profile blocks watchability warnings", function () {
  var results = {
    readability: {
      verdict: "warn",
      warnings: [
        { code: "caption_text_too_small", message: "caption too small", severity: "warn" },
        { code: "caption_low_contrast", message: "caption low contrast", severity: "warn" },
      ],
    },
    hookVisibility: {
      verdict: "warn",
      warnings: [
        { code: "weak_first_3_seconds", message: "weak hook", severity: "warn" },
      ],
    },
    creativeQuality: {
      verdict: "warn",
      warnings: [
        { code: "creative_quality_review", message: "creative review", severity: "warn" },
      ],
    },
  };
  var summary = buildReadinessSummary(results, {
    readability: "warn",
    hookVisibility: "warn",
    creativeQuality: "warn",
  }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("caption_text_too_small"), true);
  assert.equal(summary.blockingCodes.includes("caption_low_contrast"), true);
  assert.equal(summary.blockingCodes.includes("weak_first_3_seconds"), true);
  assert.equal(summary.blockingCodes.includes("creative_quality_review"), true);
  assert.equal(summary.warningCodes.includes("caption_text_too_small"), false);
});
