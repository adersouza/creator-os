import test from "node:test";
import assert from "node:assert/strict";
import { evaluateMotionSpecificQc, motionSpecificQcPolicy } from "../lib/motion-specific-qc.js";

const SUBJECT_SHA256 = "a".repeat(64);

function analyzer(extra = {}) {
  return {
    available: true,
    analyzer: "fixture_analyzer",
    analyzerVersion: "1.2.3",
    subjectSha256: SUBJECT_SHA256,
    ...extra,
  };
}

function evaluate(evidence, options = {}) {
  return evaluateMotionSpecificQc(evidence, { mediaSha256: SUBJECT_SHA256, ...options });
}

function passingEvidence() {
  return {
    motion: analyzer({ score: 0.27, evidenceId: "motion-1" }),
    temporal: analyzer({
      discontinuityScore: 0.08,
      discontinuityCandidateCount: 2,
      discontinuityComparisonCount: 25,
      discontinuityRate: 0.08,
      outlierThreshold: 0.24,
    }),
    freeze: analyzer({ frozenFrameRatio: 0.04 }),
    anatomy: analyzer({
      face: { anomalyScore: 0.05 },
      hands: { anomalyScore: 0.08 },
      body: { anomalyScore: 0.04 },
    }),
    identity: analyzer({ similarityScore: 0.93, matched: true }),
  };
}

test("passes complete deterministic evidence without invoking models or providers", function () {
  var first = evaluate(passingEvidence());
  var second = evaluate(passingEvidence());

  assert.deepEqual(first, second);
  assert.equal(first.policy.id, "contentforge.motion_specific_qc");
  assert.equal(first.policy.version, "2.0.0");
  assert.equal(first.verdict, "pass");
  assert.equal(first.passed, true);
  assert.equal(first.evidenceOnly, true);
  assert.equal(first.modelCalls, 0);
  assert.equal(first.providerCalls, 0);
  assert.equal(first.measurements.motion.amount, "moderate");
  assert.equal(first.evidenceSources.motion.evidenceId, "motion-1");
  assert.doesNotThrow(function () { JSON.stringify(first); });
});

test("blocks when required evidence or analyzer identity is missing", function () {
  var evidence = passingEvidence();
  delete evidence.temporal;
  evidence.identity = { available: true, similarityScore: 0.91, matched: true };

  var result = evaluate(evidence);

  assert.equal(result.verdict, "blocked");
  assert.equal(result.passed, false);
  assert.deepEqual(result.reasons.map(function (item) { return item.code; }), [
    "temporal_evidence_missing",
    "identity_analyzer_missing",
  ]);
  assert.equal(result.measurements.temporal.discontinuityScore, null);
  assert.equal(result.measurements.identity.similarityScore, null);
});

test("blocks invalid measurements instead of inventing fallback values", function () {
  var evidence = passingEvidence();
  evidence.motion.score = undefined;
  evidence.freeze.frozenFrameRatio = "0.03";
  evidence.identity.matched = undefined;

  var result = evaluate(evidence);

  assert.equal(result.verdict, "blocked");
  assert.equal(result.measurements.motion.score, null);
  assert.equal(result.measurements.freeze.frozenFrameRatio, null);
  assert.equal(result.measurements.identity.matched, null);
  assert.deepEqual(result.reasons.map(function (item) { return item.code; }), [
    "motion_score_invalid",
    "frozen_frame_ratio_invalid",
    "identity_match_verdict_missing",
  ]);
});

test("fails measured motion, temporal, freeze, anatomy, and identity defects", function () {
  var evidence = passingEvidence();
  evidence.motion.score = 0.01;
  evidence.temporal.discontinuityScore = 0.4;
  evidence.temporal.discontinuityCandidateCount = 4;
  evidence.temporal.discontinuityComparisonCount = 10;
  evidence.temporal.discontinuityRate = 0.4;
  evidence.freeze.frozenFrameRatio = 0.3;
  evidence.anatomy.face.anomalyScore = 0.4;
  evidence.anatomy.hands.anomalyScore = 0.5;
  evidence.anatomy.body.anomalyScore = 0.45;
  evidence.identity.similarityScore = 0.5;
  evidence.identity.matched = false;

  var result = evaluate(evidence);
  var codes = result.reasons.map(function (item) { return item.code; });

  assert.equal(result.verdict, "fail");
  assert.equal(result.measurements.motion.amount, "none");
  assert.deepEqual(codes, [
    "motion_presence_insufficient",
    "temporal_discontinuity_excessive",
    "frozen_frame_ratio_excessive",
    "anatomy_face_anomaly",
    "anatomy_hands_anomaly",
    "anatomy_body_anomaly",
    "identity_similarity_low",
    "identity_mismatch",
  ]);
});

test("requires loop, lip-sync, and audio evidence only for declared job capabilities", function () {
  var ordinary = evaluate(passingEvidence());
  var required = evaluate(passingEvidence(), {
    expectedLoop: true,
    expectsSpeech: true,
    expectsAudio: true,
  });

  assert.equal(ordinary.verdict, "pass");
  assert.equal(required.verdict, "blocked");
  assert.deepEqual(required.reasons.map(function (item) { return item.code; }), [
    "loop_evidence_missing",
    "lip_sync_evidence_missing",
    "audio_alignment_evidence_missing",
  ]);
});

test("passes loop, lip-sync, and audio alignment backed by complete evidence", function () {
  var evidence = passingEvidence();
  evidence.loop = analyzer({ seamScore: 0.08, loopable: true });
  evidence.lipSync = analyzer({
    confidence: 0.91,
    offsetMs: -34,
    aligned: true,
    correlation: 0.82,
    sampleCount: 24,
    faceTrackCoverage: 0.92,
    speechActivityRatio: 0.75,
  });
  evidence.audioAlignment = analyzer({ confidence: 0.87, offsetMs: 42, aligned: true });

  var result = evaluate(evidence, {
    expectedLoop: true,
    expectsSpeech: true,
    expectsAudio: true,
  });

  assert.equal(result.verdict, "pass");
  assert.equal(result.measurements.loop.loopable, true);
  assert.equal(result.measurements.lipSync.offsetMs, -34);
  assert.equal(result.measurements.audioAlignment.offsetMs, 42);
});

test("blocks substituted discontinuity rates and self-asserted lip-sync confidence", function () {
  var evidence = passingEvidence();
  evidence.temporal.discontinuityRate = 0.12;
  evidence.lipSync = analyzer({
    confidence: 0.99,
    offsetMs: 20,
    aligned: true,
    correlation: 0.82,
    sampleCount: 24,
    faceTrackCoverage: 0.92,
    speechActivityRatio: 0.75,
  });

  var result = evaluate(evidence, { expectsSpeech: true });

  assert.equal(result.verdict, "blocked");
  assert.ok(result.reasons.some(function (item) {
    return item.code === "temporal_discontinuity_rate_mismatch";
  }));
  assert.ok(result.reasons.some(function (item) {
    return item.code === "lip_sync_confidence_mismatch";
  }));
});

test("fails visible loop seams and measured lip/audio misalignment", function () {
  var evidence = passingEvidence();
  evidence.loop = analyzer({ seamScore: 0.61, loopable: false });
  evidence.lipSync = analyzer({
    confidence: 0.3,
    offsetMs: 180,
    aligned: false,
    correlation: -0.4,
    sampleCount: 24,
    faceTrackCoverage: 0.92,
    speechActivityRatio: 0.75,
  });
  evidence.audioAlignment = analyzer({ confidence: 0.4, offsetMs: -170, aligned: false });

  var result = evaluate(evidence, {
    expectedLoop: true,
    expectsSpeech: true,
    expectsAudio: true,
  });

  assert.equal(result.verdict, "fail");
  assert.deepEqual(result.reasons.map(function (item) { return item.code; }), [
    "loop_seam_visible",
    "loop_not_loopable",
    "lip_sync_confidence_low",
    "lip_sync_offset_excessive",
    "lip_sync_not_aligned",
    "audio_alignment_confidence_low",
    "audio_alignment_offset_excessive",
    "audio_not_aligned",
  ]);
});

test("accepts explicit anatomy non-applicability but blocks an unexplained omission", function () {
  var explained = passingEvidence();
  explained.anatomy.hands = { applicable: false, reason: "hands outside crop" };
  var unexplained = passingEvidence();
  unexplained.anatomy.hands = { applicable: false };

  var pass = evaluate(explained);
  var blocked = evaluate(unexplained);

  assert.equal(pass.verdict, "pass");
  assert.equal(pass.measurements.anatomy.hands.notApplicableReason, "hands outside crop");
  assert.equal(blocked.verdict, "blocked");
  assert.equal(blocked.reasons[0].code, "anatomy_hands_not_applicable_reason_missing");
});

test("returns a copy of policy thresholds", function () {
  var first = motionSpecificQcPolicy();
  first.thresholds.minMotionScore = 0.99;
  var second = motionSpecificQcPolicy();

  assert.equal(second.thresholds.minMotionScore, 0.03);
});

test("cannot disable core checks or override policy thresholds", function () {
  var result = evaluateMotionSpecificQc({}, {
    mediaSha256: SUBJECT_SHA256,
    requirements: {
      motion: false,
      temporal: false,
      freeze: false,
      anatomy: false,
      identity: false,
    },
    thresholds: { minMotionScore: 0 },
  });

  assert.equal(result.verdict, "blocked");
  assert.equal(result.thresholds.minMotionScore, 0.03);
  assert.deepEqual(result.reasons.map(function (item) { return item.code; }), [
    "motion_evidence_missing",
    "temporal_evidence_missing",
    "freeze_evidence_missing",
    "anatomy_evidence_missing",
    "identity_evidence_missing",
  ]);
});

test("requires media and evidence to share the exact subject SHA-256", function () {
  var missingMedia = evaluateMotionSpecificQc(passingEvidence());
  var mismatched = passingEvidence();
  mismatched.identity.subjectSha256 = "b".repeat(64);
  var mismatchResult = evaluate(mismatched);

  assert.equal(missingMedia.verdict, "blocked");
  assert.equal(missingMedia.reasons[0].code, "media_sha256_missing");
  assert.equal(mismatchResult.verdict, "blocked");
  assert.ok(mismatchResult.reasons.some(function (item) {
    return item.code === "identity_evidence_subject_mismatch";
  }));
});
