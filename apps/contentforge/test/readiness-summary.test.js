import test from "node:test";
import assert from "node:assert/strict";
import { buildReadinessSummary } from "../app/api/similarity/route.js";

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
