import test from "node:test";
import assert from "node:assert/strict";
import {
  buildDetectorVerdicts,
  buildReadinessSummary,
  buildWatchabilityWarnings,
} from "../app/api/similarity/route.js";
import { buildViralityGate } from "../lib/virality-gate.js";
import { buildVideoAnalysisGate } from "../lib/video-analysis-gate.js";

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

test("default profile keeps virality gate warnings advisory", function () {
  var virality = buildViralityGate({
    provider: "higgsfield_virality_predictor",
    score: 52,
    hookScore: 58,
    retentionRisk: 70,
  }, { required: true });
  var summary = buildReadinessSummary({ virality }, { virality: virality.verdict }, {
    auditProfile: "default",
  });

  assert.equal(virality.modelBacked, true);
  assert.equal(virality.verdict, "warn");
  assert.equal(summary.uploadReady, true);
  assert.equal(summary.warningCodes.includes("virality_score_low"), true);
  assert.equal(summary.warningCodes.includes("virality_hook_score_low"), true);
  assert.equal(summary.warningCodes.includes("virality_retention_risk_high"), true);
  assert.equal(summary.blockingCodes.length, 0);
});

test("campaign profile blocks low configured virality predictions", function () {
  var virality = buildViralityGate({
    provider: "higgsfield_virality_predictor",
    viralityScore: 0.42,
    hookStrength: 0.50,
    retentionRisk: 0.80,
  }, { required: true });
  var summary = buildReadinessSummary({ virality }, { virality: virality.verdict }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(virality.score, 42);
  assert.equal(virality.hookScore, 50);
  assert.equal(virality.retentionRisk, 80);
  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("virality_score_low"), true);
  assert.equal(summary.blockingCodes.includes("virality_hook_score_low"), true);
  assert.equal(summary.blockingCodes.includes("virality_retention_risk_high"), true);
});

test("campaign profile blocks requested virality gate when report is missing", function () {
  var virality = buildViralityGate(null, { required: true });
  var summary = buildReadinessSummary({ virality }, { virality: virality.verdict }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(virality.available, false);
  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("virality_not_configured"), true);
});

test("default profile keeps video analysis warnings advisory", function () {
  var videoAnalysis = buildVideoAnalysisGate({
    provider: "higgsfield_video_analysis",
    score: 55,
    subjectClarityScore: 59,
    firstThreeSecondsScore: 58,
    shareabilityScore: 57,
  }, { required: true });
  var summary = buildReadinessSummary({ videoAnalysis }, { videoAnalysis: videoAnalysis.verdict }, {
    auditProfile: "default",
  });

  assert.equal(videoAnalysis.modelBacked, true);
  assert.equal(videoAnalysis.verdict, "warn");
  assert.equal(summary.uploadReady, true);
  assert.equal(summary.warningCodes.includes("video_analysis_score_low"), true);
  assert.equal(summary.warningCodes.includes("video_analysis_subject_clarity_low"), true);
  assert.equal(summary.warningCodes.includes("video_analysis_first3s_low"), true);
  assert.equal(summary.warningCodes.includes("video_analysis_shareability_low"), true);
  assert.equal(summary.blockingCodes.length, 0);
});

test("campaign profile blocks low configured video analysis evidence", function () {
  var videoAnalysis = buildVideoAnalysisGate({
    provider: "higgsfield_video_analysis",
    reportId: "va_test_1",
    scores: {
      overallScore: 0.50,
      subjectClarityScore: 0.52,
      firstThreeSecondsScore: 0.48,
      shareabilityScore: 0.44,
    },
  }, { required: true });
  var summary = buildReadinessSummary({ videoAnalysis }, { videoAnalysis: videoAnalysis.verdict }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(videoAnalysis.score, 50);
  assert.equal(videoAnalysis.subjectClarityScore, 52);
  assert.equal(videoAnalysis.firstThreeSecondsScore, 48);
  assert.equal(videoAnalysis.shareabilityScore, 44);
  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("video_analysis_score_low"), true);
  assert.equal(summary.blockingCodes.includes("video_analysis_subject_clarity_low"), true);
  assert.equal(summary.blockingCodes.includes("video_analysis_first3s_low"), true);
  assert.equal(summary.blockingCodes.includes("video_analysis_shareability_low"), true);
});

test("campaign profile blocks requested video analysis gate when report is missing", function () {
  var videoAnalysis = buildVideoAnalysisGate(null, { required: true });
  var summary = buildReadinessSummary({ videoAnalysis }, { videoAnalysis: videoAnalysis.verdict }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(videoAnalysis.available, false);
  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("video_analysis_not_configured"), true);
});

test("watchability warning classifier uses available quality and audio evidence", function () {
  var warnings = buildWatchabilityWarnings({
    fileName: "variant.mp4",
    thresholds: {
      minVmaf: 78,
      maxCambi: 18,
      minIntegratedLufs: -20,
      maxIntegratedLufs: -8,
      maxTruePeakDb: -1,
    },
    qualityMetrics: {
      vmaf: 62,
      cambi: { value: 24 },
    },
    qaSignals: {
      loudness: { inputI: "-24.2", inputTp: "-0.3" },
      warnings: ["Long silence segment detected", "Possible border or letterbox detected"],
    },
  });
  var codes = warnings.map((warning) => warning.code);

  assert.equal(codes.includes("video_vmaf_low"), true);
  assert.equal(codes.includes("video_cambi_banding"), true);
  assert.equal(codes.includes("audio_loudness_out_of_range"), true);
  assert.equal(codes.includes("audio_true_peak_too_hot"), true);
  assert.equal(codes.includes("audio_long_silence"), true);
  assert.equal(codes.includes("framing_letterbox_or_crop"), true);
});

test("default profile keeps quality watchability warnings advisory", function () {
  var results = {
    watchability: {
      verdict: "warn",
      warnings: [
        { code: "video_vmaf_low", message: "low vmaf", severity: "warn" },
        { code: "audio_loudness_out_of_range", message: "bad loudness", severity: "warn" },
      ],
    },
  };
  var summary = buildReadinessSummary(results, { watchability: "warn" }, {
    auditProfile: "default",
  });

  assert.equal(summary.uploadReady, true);
  assert.equal(summary.warningCodes.includes("video_vmaf_low"), true);
  assert.equal(summary.warningCodes.includes("audio_loudness_out_of_range"), true);
  assert.equal(summary.blockingCodes.length, 0);
});

test("campaign profile blocks quality watchability warnings", function () {
  var results = {
    watchability: {
      verdict: "warn",
      warnings: [
        { code: "video_vmaf_low", message: "low vmaf", severity: "warn" },
        { code: "audio_loudness_out_of_range", message: "bad loudness", severity: "warn" },
      ],
    },
  };
  var summary = buildReadinessSummary(results, { watchability: "warn" }, {
    auditProfile: "campaign_factory_v1",
  });

  assert.equal(summary.uploadReady, false);
  assert.equal(summary.blockingCodes.includes("video_vmaf_low"), true);
  assert.equal(summary.blockingCodes.includes("audio_loudness_out_of_range"), true);
  assert.equal(summary.warningCodes.includes("video_vmaf_low"), false);
});
