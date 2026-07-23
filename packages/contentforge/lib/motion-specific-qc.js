import { createHash } from "node:crypto";

const POLICY = Object.freeze({
  id: "contentforge.motion_specific_qc",
  version: "2.0.0",
  thresholds: Object.freeze({
    minMotionScore: 0.03,
    subtleMotionMax: 0.18,
    moderateMotionMax: 0.5,
    maxTemporalDiscontinuityScore: 0.25,
    maxFrozenFrameRatio: 0.2,
    maxLoopSeamScore: 0.25,
    maxFaceAnomalyScore: 0.25,
    maxHandAnomalyScore: 0.3,
    maxBodyAnomalyScore: 0.25,
    minIdentitySimilarityScore: 0.75,
    minLipSyncConfidence: 0.65,
    maxLipSyncOffsetMs: 120,
    minAudioAlignmentConfidence: 0.65,
    maxAudioAlignmentOffsetMs: 120,
  }),
});

const REQUIREMENT_ORDER = Object.freeze([
  "motion",
  "temporal",
  "freeze",
  "anatomy",
  "identity",
  "loop",
  "lipSync",
  "audioAlignment",
]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function normalizedNumber(value) {
  return finiteNumber(value) && value >= 0 && value <= 1;
}

function nonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function standardNormalCdf(value) {
  var absolute = Math.abs(value);
  var t = 1 / (1 + (0.2316419 * absolute));
  var density = Math.exp(-0.5 * absolute * absolute) / Math.sqrt(2 * Math.PI);
  var tail = density * t * (
    0.319381530
    + t * (-0.356563782
      + t * (1.781477937
        + t * (-1.821255978 + (t * 1.330274429))))
  );
  return value >= 0 ? 1 - tail : tail;
}

function validSha256(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function canonicalJson(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (isRecord(value)) {
    return "{" + Object.keys(value).sort().map(function (key) {
      return JSON.stringify(key) + ":" + canonicalJson(value[key]);
    }).join(",") + "}";
  }
  return JSON.stringify(value);
}

function evidenceFingerprint(value) {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function reason(code, severity, message, details = {}) {
  return { code, severity, message, ...details };
}

function requirementsFrom(options) {
  return {
    motion: true,
    temporal: true,
    freeze: true,
    anatomy: true,
    identity: true,
    loop: options.expectedLoop === true,
    lipSync: options.expectsSpeech === true,
    audioAlignment: options.expectsAudio === true,
  };
}

function thresholdsFrom() {
  return { ...POLICY.thresholds };
}

function evidenceStatus(value, subjectSha256) {
  if (!isRecord(value)) return "missing";
  if (value.available !== true) return "unavailable";
  if (!nonEmptyString(value.analyzer)) return "analyzer_missing";
  if (!validSha256(value.subjectSha256)) return "subject_missing";
  if (value.subjectSha256 !== subjectSha256) return "subject_mismatch";
  return "available";
}

function sourceDescriptor(value) {
  if (!isRecord(value)) {
    return { available: false, analyzer: null, analyzerVersion: null, evidenceId: null };
  }
  return {
    available: value.available === true,
    analyzer: nonEmptyString(value.analyzer) ? value.analyzer.trim() : null,
    analyzerVersion: nonEmptyString(value.analyzerVersion) ? value.analyzerVersion.trim() : null,
    evidenceId: nonEmptyString(value.evidenceId) ? value.evidenceId.trim() : null,
    subjectSha256: validSha256(value.subjectSha256) ? value.subjectSha256 : null,
    analysisFingerprint: validSha256(value.analysisFingerprint) ? value.analysisFingerprint : null,
    analyzerRegistryId: nonEmptyString(value.analyzerRegistryId) ? value.analyzerRegistryId.trim() : null,
    analyzerRegistryFingerprint: validSha256(value.analyzerRegistryFingerprint)
      ? value.analyzerRegistryFingerprint
      : null,
    implementationRef: nonEmptyString(value.implementationRef) ? value.implementationRef.trim() : null,
    implementationFingerprint: validSha256(value.implementationFingerprint)
      ? value.implementationFingerprint
      : null,
    reviewFingerprint: validSha256(value.reviewFingerprint) ? value.reviewFingerprint : null,
  };
}

function addEvidenceBlocker(reasons, name, status) {
  var label = name.replace(/[A-Z]/g, function (letter) { return "_" + letter.toLowerCase(); });
  var code = status === "analyzer_missing" ? label + "_analyzer_missing" : label + "_evidence_" + status;
  reasons.push(reason(
    code,
    "block",
    status === "analyzer_missing"
      ? "Required " + name + " evidence does not identify the analyzer that produced it"
      : "Required " + name + " evidence is " + status,
    { evidence: name }
  ));
}

function motionAmount(score, thresholds) {
  if (!normalizedNumber(score)) return null;
  if (score < thresholds.minMotionScore) return "none";
  if (score <= thresholds.subtleMotionMax) return "subtle";
  if (score <= thresholds.moderateMotionMax) return "moderate";
  return "high";
}

function validateAnatomyPart(part, name, threshold, reasons) {
  if (!isRecord(part)) {
    reasons.push(reason("anatomy_" + name + "_evidence_missing", "block", "Required " + name + " anomaly evidence is missing", { evidence: "anatomy." + name }));
    return { applicable: null, anomalyScore: null, notApplicableReason: null };
  }
  if (part.applicable === false) {
    if (!nonEmptyString(part.reason)) {
      reasons.push(reason("anatomy_" + name + "_not_applicable_reason_missing", "block", "Non-applicable " + name + " evidence must include a reason", { evidence: "anatomy." + name }));
    }
    return {
      applicable: false,
      anomalyScore: null,
      notApplicableReason: nonEmptyString(part.reason) ? part.reason.trim() : null,
    };
  }
  if (!normalizedNumber(part.anomalyScore)) {
    reasons.push(reason("anatomy_" + name + "_score_invalid", "block", name + " anomaly score must be a normalized number", { evidence: "anatomy." + name + ".anomalyScore" }));
    return { applicable: true, anomalyScore: null, notApplicableReason: null };
  }
  if (part.anomalyScore > threshold) {
    reasons.push(reason("anatomy_" + name + "_anomaly", "fail", name + " anomaly evidence exceeds policy threshold", {
      measurement: part.anomalyScore,
      threshold,
    }));
  }
  return { applicable: true, anomalyScore: part.anomalyScore, notApplicableReason: null };
}

function emptyMeasurements() {
  return {
    motion: { score: null, amount: null },
    temporal: {
      discontinuityScore: null,
      discontinuityCandidateCount: 0,
      discontinuityComparisonCount: 0,
      discontinuityRate: null,
      outlierThreshold: null,
    },
    freeze: { frozenFrameRatio: null },
    loop: { seamScore: null, loopable: null },
    anatomy: {
      face: { applicable: null, anomalyScore: null, notApplicableReason: null },
      hands: { applicable: null, anomalyScore: null, notApplicableReason: null },
      body: { applicable: null, anomalyScore: null, notApplicableReason: null },
    },
    identity: { similarityScore: null, matched: null },
    lipSync: {
      confidence: null,
      offsetMs: null,
      aligned: null,
      correlation: null,
      sampleCount: 0,
      faceTrackCoverage: null,
      speechActivityRatio: null,
    },
    audioAlignment: { confidence: null, offsetMs: null, aligned: null },
  };
}

/**
 * Evaluate already-produced motion evidence. This function intentionally does
 * not inspect media, invoke analyzers, call a model/provider, or mutate state.
 */
export function evaluateMotionSpecificQc(evidence = {}, options = {}) {
  var input = isRecord(evidence) ? evidence : {};
  var requirements = requirementsFrom(options);
  var thresholds = thresholdsFrom();
  var reasons = [];
  var measurements = emptyMeasurements();
  var sources = {};

  var subjectSha256 = validSha256(options.mediaSha256) ? options.mediaSha256 : null;
  if (subjectSha256 === null) {
    reasons.push(reason("media_sha256_missing", "block", "Motion QC requires the exact media SHA-256"));
  }

  for (var name of REQUIREMENT_ORDER) {
    sources[name] = sourceDescriptor(input[name]);
    var status = evidenceStatus(input[name], subjectSha256);
    if (requirements[name] && status !== "available") addEvidenceBlocker(reasons, name, status);
  }

  if (evidenceStatus(input.motion, subjectSha256) === "available") {
    if (!normalizedNumber(input.motion.score)) {
      reasons.push(reason("motion_score_invalid", "block", "Motion score must be a normalized number", { evidence: "motion.score" }));
    } else {
      measurements.motion.score = input.motion.score;
      measurements.motion.amount = motionAmount(input.motion.score, thresholds);
      if (input.motion.score < thresholds.minMotionScore) {
        reasons.push(reason("motion_presence_insufficient", "fail", "Measured motion is below the minimum motion threshold", {
          measurement: input.motion.score,
          threshold: thresholds.minMotionScore,
        }));
      }
    }
  }

  if (evidenceStatus(input.temporal, subjectSha256) === "available") {
    if (!normalizedNumber(input.temporal.discontinuityScore)) {
      reasons.push(reason("temporal_discontinuity_score_invalid", "block", "Temporal discontinuity score must be a normalized number", { evidence: "temporal.discontinuityScore" }));
    } else {
      measurements.temporal.discontinuityScore = input.temporal.discontinuityScore;
      if (input.temporal.discontinuityScore > thresholds.maxTemporalDiscontinuityScore) {
        reasons.push(reason("temporal_discontinuity_excessive", "fail", "Temporal discontinuity exceeds the policy threshold", {
          measurement: input.temporal.discontinuityScore,
          threshold: thresholds.maxTemporalDiscontinuityScore,
        }));
      }
    }
    var candidateCount = input.temporal.discontinuityCandidateCount;
    var comparisonCount = input.temporal.discontinuityComparisonCount;
    var candidateRate = input.temporal.discontinuityRate;
    var outlierThreshold = input.temporal.outlierThreshold;
    if (!nonNegativeInteger(candidateCount)
      || !Number.isInteger(comparisonCount)
      || comparisonCount <= 0
      || candidateCount > comparisonCount
      || !normalizedNumber(candidateRate)
      || !normalizedNumber(outlierThreshold)) {
      reasons.push(reason(
        "temporal_discontinuity_candidates_invalid",
        "block",
        "Temporal discontinuity evidence must include exact candidate counts, rate, and outlier threshold",
        { evidence: "temporal.discontinuityCandidates" },
      ));
    } else {
      var exactRate = candidateCount / comparisonCount;
      if (Math.abs(exactRate - candidateRate) > 1e-9
        || Math.abs(input.temporal.discontinuityScore - candidateRate) > 1e-9) {
        reasons.push(reason(
          "temporal_discontinuity_rate_mismatch",
          "block",
          "Temporal discontinuity score must equal the measured scene-cut/outlier candidate rate",
        ));
      } else {
        measurements.temporal.discontinuityCandidateCount = candidateCount;
        measurements.temporal.discontinuityComparisonCount = comparisonCount;
        measurements.temporal.discontinuityRate = candidateRate;
        measurements.temporal.outlierThreshold = outlierThreshold;
      }
    }
  }

  if (evidenceStatus(input.freeze, subjectSha256) === "available") {
    if (!normalizedNumber(input.freeze.frozenFrameRatio)) {
      reasons.push(reason("frozen_frame_ratio_invalid", "block", "Frozen-frame ratio must be a normalized number", { evidence: "freeze.frozenFrameRatio" }));
    } else {
      measurements.freeze.frozenFrameRatio = input.freeze.frozenFrameRatio;
      if (input.freeze.frozenFrameRatio > thresholds.maxFrozenFrameRatio) {
        reasons.push(reason("frozen_frame_ratio_excessive", "fail", "Frozen-frame ratio exceeds the policy threshold", {
          measurement: input.freeze.frozenFrameRatio,
          threshold: thresholds.maxFrozenFrameRatio,
        }));
      }
    }
  }

  if (evidenceStatus(input.loop, subjectSha256) === "available") {
    if (!normalizedNumber(input.loop.seamScore)) {
      reasons.push(reason("loop_seam_score_invalid", "block", "Loop seam score must be a normalized number", { evidence: "loop.seamScore" }));
    } else {
      measurements.loop.seamScore = input.loop.seamScore;
      if (input.loop.seamScore > thresholds.maxLoopSeamScore) {
        reasons.push(reason("loop_seam_visible", "fail", "Loop seam evidence exceeds the loopability threshold", {
          measurement: input.loop.seamScore,
          threshold: thresholds.maxLoopSeamScore,
        }));
      }
    }
    if (typeof input.loop.loopable !== "boolean") {
      reasons.push(reason("loopability_verdict_missing", "block", "Loop evidence must include an explicit loopable verdict", { evidence: "loop.loopable" }));
    } else {
      measurements.loop.loopable = input.loop.loopable;
      if (requirements.loop && input.loop.loopable === false) {
        reasons.push(reason("loop_not_loopable", "fail", "The asset is required to loop but loopability evidence failed"));
      }
    }
  }

  if (evidenceStatus(input.anatomy, subjectSha256) === "available") {
    measurements.anatomy.face = validateAnatomyPart(input.anatomy.face, "face", thresholds.maxFaceAnomalyScore, reasons);
    measurements.anatomy.hands = validateAnatomyPart(input.anatomy.hands, "hands", thresholds.maxHandAnomalyScore, reasons);
    measurements.anatomy.body = validateAnatomyPart(input.anatomy.body, "body", thresholds.maxBodyAnomalyScore, reasons);
  }

  if (evidenceStatus(input.identity, subjectSha256) === "available") {
    if (!normalizedNumber(input.identity.similarityScore)) {
      reasons.push(reason("identity_similarity_score_invalid", "block", "Identity similarity score must be a normalized number", { evidence: "identity.similarityScore" }));
    } else {
      measurements.identity.similarityScore = input.identity.similarityScore;
      if (input.identity.similarityScore < thresholds.minIdentitySimilarityScore) {
        reasons.push(reason("identity_similarity_low", "fail", "Identity similarity is below the policy threshold", {
          measurement: input.identity.similarityScore,
          threshold: thresholds.minIdentitySimilarityScore,
        }));
      }
    }
    if (typeof input.identity.matched !== "boolean") {
      reasons.push(reason("identity_match_verdict_missing", "block", "Identity evidence must include an explicit matched verdict", { evidence: "identity.matched" }));
    } else {
      measurements.identity.matched = input.identity.matched;
      if (!input.identity.matched) reasons.push(reason("identity_mismatch", "fail", "Identity analyzer reported a mismatch"));
    }
  }

  if (evidenceStatus(input.lipSync, subjectSha256) === "available") {
    if (!normalizedNumber(input.lipSync.confidence)) {
      reasons.push(reason("lip_sync_confidence_invalid", "block", "Lip-sync confidence must be a normalized number", { evidence: "lipSync.confidence" }));
    } else {
      measurements.lipSync.confidence = input.lipSync.confidence;
      if (input.lipSync.confidence < thresholds.minLipSyncConfidence) {
        reasons.push(reason("lip_sync_confidence_low", "fail", "Lip-sync confidence is below the policy threshold", {
          measurement: input.lipSync.confidence,
          threshold: thresholds.minLipSyncConfidence,
        }));
      }
    }
    if (!finiteNumber(input.lipSync.offsetMs)) {
      reasons.push(reason("lip_sync_offset_invalid", "block", "Lip-sync offset must be a finite millisecond value", { evidence: "lipSync.offsetMs" }));
    } else {
      measurements.lipSync.offsetMs = input.lipSync.offsetMs;
      if (Math.abs(input.lipSync.offsetMs) > thresholds.maxLipSyncOffsetMs) {
        reasons.push(reason("lip_sync_offset_excessive", "fail", "Lip-sync offset exceeds the policy threshold", {
          measurement: input.lipSync.offsetMs,
          threshold: thresholds.maxLipSyncOffsetMs,
        }));
      }
    }
    if (typeof input.lipSync.aligned !== "boolean") {
      reasons.push(reason("lip_sync_alignment_verdict_missing", "block", "Lip-sync evidence must include an explicit aligned verdict", { evidence: "lipSync.aligned" }));
    } else {
      measurements.lipSync.aligned = input.lipSync.aligned;
      if (!input.lipSync.aligned) reasons.push(reason("lip_sync_not_aligned", "fail", "Lip-sync analyzer reported misalignment"));
    }
    if (!finiteNumber(input.lipSync.correlation)
      || input.lipSync.correlation < -1
      || input.lipSync.correlation > 1
      || !nonNegativeInteger(input.lipSync.sampleCount)
      || input.lipSync.sampleCount < 12
      || !normalizedNumber(input.lipSync.faceTrackCoverage)
      || !normalizedNumber(input.lipSync.speechActivityRatio)) {
      reasons.push(reason(
        "lip_sync_supporting_evidence_invalid",
        "block",
        "Lip-sync evidence must include correlation, sample count, face coverage, and speech activity",
      ));
    } else {
      measurements.lipSync.correlation = input.lipSync.correlation;
      measurements.lipSync.sampleCount = input.lipSync.sampleCount;
      measurements.lipSync.faceTrackCoverage = input.lipSync.faceTrackCoverage;
      measurements.lipSync.speechActivityRatio = input.lipSync.speechActivityRatio;
    }
    var landmarkToolchain = input.lipSync.landmarkToolchain;
    var landmarkToolchainCore = isRecord(landmarkToolchain)
      ? { ...landmarkToolchain }
      : null;
    if (landmarkToolchainCore) delete landmarkToolchainCore.toolchainFingerprint;
    var trustedLandmarkRuntime = validSha256(input.lipSync.landmarkEvidenceFingerprint)
      && validSha256(input.lipSync.landmarkToolchainFingerprint)
      && isRecord(landmarkToolchain)
      && landmarkToolchain.schema === "contentforge.apple_vision_toolchain.v1"
      && landmarkToolchain.toolchainFingerprint
        === input.lipSync.landmarkToolchainFingerprint
      && evidenceFingerprint(landmarkToolchainCore)
        === input.lipSync.landmarkToolchainFingerprint
      && nonEmptyString(landmarkToolchain.macosBuildVersion)
      && nonEmptyString(landmarkToolchain.swiftVersion)
      && validSha256(landmarkToolchain.swiftExecutableSha256)
      && validSha256(landmarkToolchain.embeddedSwiftSourceSha256);
    if (!trustedLandmarkRuntime) {
      reasons.push(reason(
        "lip_sync_landmark_runtime_invalid",
        "block",
        "Lip-sync evidence requires exact content-bound Apple Vision and Swift runtime identity",
      ));
    }
    var correlationEvidence = input.lipSync.correlationEvidence;
    var trustedCorrelationDesign = input.lipSync.analyzerMethod
        === "audio_energy_to_apple_vision_lip_landmarks_train_holdout"
      && isRecord(correlationEvidence)
      && correlationEvidence.design
        === "offset_selected_on_training_evaluated_once_on_interleaved_holdout"
      && correlationEvidence.confidenceMethod
        === "one_sided_fisher_z_against_practical_null"
      && correlationEvidence.candidateOffsetCount === 13
      && nonNegativeInteger(correlationEvidence.trainingSampleCount)
      && correlationEvidence.trainingSampleCount >= 24
      && nonNegativeInteger(correlationEvidence.holdoutSampleCount)
      && correlationEvidence.holdoutSampleCount >= 12
      && correlationEvidence.holdoutSampleCount === input.lipSync.sampleCount
      && finiteNumber(correlationEvidence.trainingCorrelation)
      && correlationEvidence.trainingCorrelation >= -1
      && correlationEvidence.trainingCorrelation <= 1
      && finiteNumber(correlationEvidence.holdoutCorrelation)
      && correlationEvidence.holdoutCorrelation >= -1
      && correlationEvidence.holdoutCorrelation <= 1
      && finiteNumber(correlationEvidence.holdoutCorrelationLower95)
      && Math.abs(
        correlationEvidence.holdoutCorrelationLower95 - input.lipSync.correlation,
      ) <= 1e-9
      && correlationEvidence.nullCorrelation === 0.20
      && finiteNumber(correlationEvidence.fisherStatistic)
      && normalizedNumber(correlationEvidence.oneSidedPValue)
      && normalizedNumber(correlationEvidence.statisticalConfidence)
      && Math.abs(
        correlationEvidence.oneSidedPValue
          + correlationEvidence.statisticalConfidence - 1,
      ) <= 1e-9
      && ["supported", "weak", "unsupported"].includes(
        correlationEvidence.confidenceLabel,
      );
    if (!trustedCorrelationDesign) {
      reasons.push(reason(
        "lip_sync_correlation_design_invalid",
        "block",
        "Lip-sync evidence requires Apple Vision mouth landmarks and a fixed train/holdout lag design",
      ));
    } else {
      var expectedStatistic = (
        Math.atanh(Math.max(
          -0.999999,
          Math.min(0.999999, correlationEvidence.holdoutCorrelation),
        )) - Math.atanh(correlationEvidence.nullCorrelation)
      ) * Math.sqrt(correlationEvidence.holdoutSampleCount - 3);
      var expectedConfidence = standardNormalCdf(expectedStatistic);
      if (Math.abs(expectedStatistic - correlationEvidence.fisherStatistic) > 1e-9
        || Math.abs(expectedConfidence - input.lipSync.confidence) > 1e-9) {
        reasons.push(reason(
          "lip_sync_confidence_mismatch",
          "block",
          "Lip-sync confidence must be the declared holdout Fisher-z evidence probability",
        ));
      }
    }
    if (trustedCorrelationDesign && input.lipSync.aligned
      && correlationEvidence.confidenceLabel !== "supported") {
      reasons.push(reason(
        "lip_sync_alignment_support_mismatch",
        "block",
        "Lip-sync cannot be marked aligned without supported holdout evidence",
      ));
    }
  }

  if (evidenceStatus(input.audioAlignment, subjectSha256) === "available") {
    if (!normalizedNumber(input.audioAlignment.confidence)) {
      reasons.push(reason("audio_alignment_confidence_invalid", "block", "Audio-alignment confidence must be a normalized number", { evidence: "audioAlignment.confidence" }));
    } else {
      measurements.audioAlignment.confidence = input.audioAlignment.confidence;
      if (input.audioAlignment.confidence < thresholds.minAudioAlignmentConfidence) {
        reasons.push(reason("audio_alignment_confidence_low", "fail", "Audio-alignment confidence is below the policy threshold", {
          measurement: input.audioAlignment.confidence,
          threshold: thresholds.minAudioAlignmentConfidence,
        }));
      }
    }
    if (!finiteNumber(input.audioAlignment.offsetMs)) {
      reasons.push(reason("audio_alignment_offset_invalid", "block", "Audio-alignment offset must be a finite millisecond value", { evidence: "audioAlignment.offsetMs" }));
    } else {
      measurements.audioAlignment.offsetMs = input.audioAlignment.offsetMs;
      if (Math.abs(input.audioAlignment.offsetMs) > thresholds.maxAudioAlignmentOffsetMs) {
        reasons.push(reason("audio_alignment_offset_excessive", "fail", "Audio-alignment offset exceeds the policy threshold", {
          measurement: input.audioAlignment.offsetMs,
          threshold: thresholds.maxAudioAlignmentOffsetMs,
        }));
      }
    }
    if (typeof input.audioAlignment.aligned !== "boolean") {
      reasons.push(reason("audio_alignment_verdict_missing", "block", "Audio-alignment evidence must include an explicit aligned verdict", { evidence: "audioAlignment.aligned" }));
    } else {
      measurements.audioAlignment.aligned = input.audioAlignment.aligned;
      if (!input.audioAlignment.aligned) reasons.push(reason("audio_not_aligned", "fail", "Audio-alignment analyzer reported misalignment"));
    }
  }

  var blocked = reasons.some(function (item) { return item.severity === "block"; });
  var failed = reasons.some(function (item) { return item.severity === "fail"; });
  var verdict = blocked ? "blocked" : failed ? "fail" : "pass";

  return {
    policy: { id: POLICY.id, version: POLICY.version },
    subjectSha256,
    verdict,
    passed: verdict === "pass",
    evidenceOnly: true,
    modelCalls: 0,
    providerCalls: 0,
    requirements,
    thresholds,
    measurements,
    evidenceSources: sources,
    reasons,
  };
}

export function motionSpecificQcPolicy() {
  return {
    id: POLICY.id,
    version: POLICY.version,
    thresholds: { ...POLICY.thresholds },
  };
}
