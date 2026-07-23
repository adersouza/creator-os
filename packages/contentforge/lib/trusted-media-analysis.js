import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { createReadStream, readFileSync } from "node:fs";
import {
  chmod,
  copyFile,
  lstat,
  mkdtemp,
  readFile,
  rm,
  stat,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import {
  canonicalJsonDeep,
  signEvidenceAttestation,
  verifyEvidenceAttestation,
} from "./evidence-attestation.js";
import { evaluateMotionSpecificQc } from "./motion-specific-qc.js";
import { getPythonCommand } from "./python-runtime.js";

export const TRUSTED_ANALYZERS = Object.freeze([
  Object.freeze({
    analyzerId: "contentforge.media_integrity",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["media_integrity_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.temporal_motion",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["temporal_motion_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.audio_integrity",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["audio_integrity_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.overlay_delivery",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["overlay_delivery_observation"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.local_lip_sync",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["lip_sync_observation"]),
  }),
]);

const ANALYSIS_SCHEMA = "contentforge.trusted_media_analysis.v1";
const SAMPLE_FRAMES_PER_SECOND = 8;
const SAMPLE_WIDTH = 180;
const SAMPLE_HEIGHT = 320;
const FRAME_BYTES = SAMPLE_WIDTH * SAMPLE_HEIGHT;
const FROZEN_DELTA_THRESHOLD = 0.002;
const DISCONTINUITY_ABSOLUTE_THRESHOLD = 0.18;
const DISCONTINUITY_MAD_SCALE = 6;
const DISCONTINUITY_MIN_EXCESS = 0.05;
const LIP_SYNC_SAMPLE_RATE = 16000;
const LIP_SYNC_MIN_SAMPLES = 7;
const LIP_SYNC_MIN_FACE_COVERAGE = 0.60;
const LIP_SYNC_MIN_AUDIO_ACTIVITY_RATIO = 0.15;
const LIP_SYNC_MIN_VISUAL_SPREAD = 0.001;
const LIP_SYNC_OFFSET_LIMIT_MS = 240;
const LIP_SYNC_OFFSET_STEP_MS = 40;
const REPOSITORY_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const LIP_SYNC_ANALYZER_PATH = path.join(
  REPOSITORY_ROOT,
  "packages/contentforge/scripts/local-lip-sync-analyzer.py",
);
const SCHEMA_ROOT = path.join(REPOSITORY_ROOT, "packages/pipeline_contracts/pipeline_contracts/schemas");
const ajv = new Ajv2020({ allErrors: true, strict: false, formats: { "date-time": true } });
const evidenceProvenanceSchema = JSON.parse(readFileSync(path.join(SCHEMA_ROOT, "evidence_provenance.v1.schema.json"), "utf8"));
const evidenceAttestationSchema = JSON.parse(readFileSync(path.join(SCHEMA_ROOT, "evidence_attestation.v1.schema.json"), "utf8"));
const analyzerRegistrySchema = JSON.parse(readFileSync(path.join(SCHEMA_ROOT, "analyzer_registry.v1.schema.json"), "utf8"));
const trustedAnalysisSchema = JSON.parse(readFileSync(path.join(SCHEMA_ROOT, "trusted_media_analysis.v1.schema.json"), "utf8"));
const humanReviewSchema = JSON.parse(readFileSync(path.join(SCHEMA_ROOT, "human_media_review.v1.schema.json"), "utf8"));
ajv.addSchema(evidenceProvenanceSchema, "evidence_provenance.v1.schema.json");
ajv.addSchema(evidenceAttestationSchema, "evidence_attestation.v1.schema.json");
ajv.addSchema(analyzerRegistrySchema, "analyzer_registry.v1.schema.json");
ajv.addSchema(trustedAnalysisSchema, "trusted_media_analysis.v1.schema.json");
ajv.addSchema(humanReviewSchema, "human_media_review.v1.schema.json");
const validateTrustedAnalysisSchema = ajv.getSchema("trusted_media_analysis.v1.schema.json");
const validateHumanReviewSchema = ajv.getSchema("human_media_review.v1.schema.json");
const validateAnalyzerRegistrySchema = ajv.getSchema("analyzer_registry.v1.schema.json");
const validateMotionReceiptSchema = ajv.compile(JSON.parse(readFileSync(path.join(SCHEMA_ROOT, "motion_specific_qc_receipt.v2.schema.json"), "utf8")));

const RFC3339_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ANALYSIS_ATTESTATION_ISSUER = "contentforge.trusted_media_analysis";
const HUMAN_REVIEW_ATTESTATION_ISSUER = "reel_factory.structured_human_media_review";
const RECEIPT_ATTESTATION_ISSUER = "contentforge.trusted_motion_qc";
const REQUIRED_DECISIVE_ANALYZERS = Object.freeze([
  Object.freeze({
    analyzerId: "contentforge.motion_specific_qc",
    analyzerVersion: "2.0.0",
    evidenceKinds: Object.freeze(["motion_specific_qc_receipt"]),
  }),
  Object.freeze({
    analyzerId: HUMAN_REVIEW_ATTESTATION_ISSUER,
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["human_media_review"]),
  }),
  Object.freeze({
    analyzerId: "contentforge.local_face_mouth_track",
    analyzerVersion: "1.0.0",
    evidenceKinds: Object.freeze(["face_mouth_track_observation"]),
  }),
]);

function requireCurrentTimestamp(value, code) {
  if (typeof value !== "string" || !RFC3339_WITH_ZONE.test(value) || Number.isNaN(Date.parse(value))) {
    throw new Error(`${code}_invalid`);
  }
  if (Date.parse(value) > Date.now()) throw new Error(`${code}_from_future`);
}

function fingerprint(value) {
  return createHash("sha256").update(canonicalJsonDeep(value)).digest("hex");
}

function requireSchema(validator, value, code) {
  if (!validator(value)) {
    var details = (validator.errors || []).map(function (error) {
      return `${error.instancePath || "$"}:${error.message}`;
    }).join(",");
    throw new Error(`${code}:${details}`);
  }
}

function validateAnalysisRecord(analysis) {
  requireSchema(validateTrustedAnalysisSchema, analysis, "trusted_media_analysis_schema_invalid");
  var claimedFingerprint = analysis.analysisFingerprint;
  var fingerprintPayload = { ...analysis };
  delete fingerprintPayload.analysisFingerprint;
  delete fingerprintPayload.producerAttestation;
  if (claimedFingerprint !== fingerprint(fingerprintPayload)) {
    throw new Error("trusted_media_analysis_fingerprint_mismatch");
  }
  var attestedPayload = { ...analysis };
  delete attestedPayload.producerAttestation;
  verifyEvidenceAttestation(analysis.producerAttestation, attestedPayload, {
    expectedIssuer: ANALYSIS_ATTESTATION_ISSUER,
    expectedIssuedAt: analysis.producedAt,
  });
  requireCurrentTimestamp(analysis.producedAt, "trusted_media_analysis_timestamp");
  var observations = new Map();
  for (var record of analysis.rawObservations) {
    var identity = `${record.analyzerId}@${record.analyzerVersion}`;
    if (observations.has(identity)) throw new Error("trusted_media_analysis_duplicate_analyzer");
    observations.set(identity, record);
  }
  var expected = new Set(TRUSTED_ANALYZERS.map(function (item) {
    return `${item.analyzerId}@${item.analyzerVersion}`;
  }));
  if (observations.size !== expected.size || [...expected].some(function (key) { return !observations.has(key); })) {
    throw new Error("trusted_media_analysis_required_analyzers_mismatch");
  }
  for (var requiredMeasured of ["contentforge.media_integrity@1.0.0", "contentforge.temporal_motion@1.0.0"]) {
    if (observations.get(requiredMeasured)?.status !== "measured") {
      throw new Error(`trusted_media_analysis_critical_measurement_missing:${requiredMeasured}`);
    }
  }
  var temporalSampling = observations.get("contentforge.temporal_motion@1.0.0")
    ?.observations?.sampling;
  var humanReviewSampling = analysis.humanReviewSampling;
  var expectedBriefFrameOutlierCount = observations.get("contentforge.temporal_motion@1.0.0")
    ?.observations?.briefFrameOutlierCount;
  if (!temporalSampling
    || humanReviewSampling.sampleFps !== temporalSampling.framesPerSecond
    || humanReviewSampling.width !== temporalSampling.width
    || humanReviewSampling.height !== temporalSampling.height
    || humanReviewSampling.sampledFrames !== temporalSampling.sampledFrames
    || humanReviewSampling.totalFrames !== temporalSampling.totalFrames
    || Math.abs(humanReviewSampling.durationSeconds - temporalSampling.durationSeconds) > 1e-9
    || humanReviewSampling.durationCoverageRatio !== temporalSampling.durationCoverageRatio
    || humanReviewSampling.frameSetFingerprint !== temporalSampling.frameSetFingerprint
    || humanReviewSampling.briefFrameOutlierCount !== expectedBriefFrameOutlierCount) {
    throw new Error("trusted_media_analysis_human_review_sampling_mismatch");
  }
  var expectedAnalysisId = "analysis_" + fingerprint({
    mediaSha256: analysis.subject.mediaSha256,
    sourceSha256: analysis.subject.sourceSha256,
    registryFingerprint: analysis.analyzerRegistry.registryFingerprint,
    analyzers: analysis.rawObservations,
  }).slice(0, 24);
  if (analysis.analysisId !== expectedAnalysisId) {
    throw new Error("trusted_media_analysis_id_mismatch");
  }
  var verdicts = new Map();
  for (var verdict of analysis.analyzerVerdicts) {
    var identity = `${verdict.policy.id}@${verdict.policy.version}`;
    if (verdicts.has(identity)) throw new Error("trusted_media_analysis_duplicate_verdict");
    verdicts.set(identity, verdict);
  }
  if (verdicts.size !== observations.size) throw new Error("trusted_media_analysis_verdict_set_mismatch");
  for (var [identity, observation] of observations) {
    var verdict = verdicts.get(identity);
    var expectedPass = observation.status === "measured" || observation.status === "not_applicable";
    if (!verdict
      || verdict.subjectSha256 !== analysis.subject.mediaSha256
      || verdict.analysisId !== analysis.analysisId
      || verdict.observationFingerprint !== fingerprint(observation)
      || verdict.analyzerRegistryId !== observation.analyzerRegistryId
      || verdict.analyzerRegistryFingerprint !== observation.analyzerRegistryFingerprint
      || verdict.implementationRef !== observation.implementationRef
      || verdict.implementationFingerprint !== observation.implementationFingerprint
      || verdict.passed !== expectedPass
      || verdict.verdict !== (expectedPass ? "pass" : "blocked")
      || (expectedPass && verdict.reasons.length !== 0)
      || (!expectedPass && (verdict.reasons.length !== 1
        || verdict.reasons[0].severity !== "block"
        || verdict.reasons[0].code !== observation.observations.reason))) {
      throw new Error(`trusted_media_analysis_verdict_mismatch:${identity}`);
    }
  }
  return observations;
}

function validateHumanReviewRecord(review, analysis) {
  requireSchema(validateHumanReviewSchema, review, "human_media_review_schema_invalid");
  var claimedFingerprint = review.reviewFingerprint;
  var fingerprintPayload = { ...review };
  delete fingerprintPayload.reviewFingerprint;
  delete fingerprintPayload.operatorAttestation;
  if (claimedFingerprint !== fingerprint(fingerprintPayload)) {
    throw new Error("human_media_review_fingerprint_mismatch");
  }
  var attestedPayload = { ...review };
  delete attestedPayload.operatorAttestation;
  verifyEvidenceAttestation(review.operatorAttestation, attestedPayload, {
    expectedIssuer: HUMAN_REVIEW_ATTESTATION_ISSUER,
    expectedIssuedAt: review.reviewedAt,
  });
  if (review.rubricVersion !== "1.0.0") throw new Error("human_media_review_rubric_unsupported");
  requireCurrentTimestamp(review.reviewedAt, "human_media_review_timestamp");
  if (Date.parse(review.reviewedAt) < Date.parse(analysis.producedAt)) {
    throw new Error("human_media_review_predates_analysis");
  }
  if (review.subjectSha256 !== analysis.subject.mediaSha256) {
    throw new Error("human_media_review_subject_mismatch");
  }
  if (!analysis.subject.sourceSha256 || review.sourceSha256 !== analysis.subject.sourceSha256) {
    throw new Error("human_media_review_source_mismatch");
  }
  var sampling = analysis.humanReviewSampling;
  var reviewSampling = review.samplingEvidence;
  if (reviewSampling.analysisId !== analysis.analysisId
    || reviewSampling.analysisFingerprint !== analysis.analysisFingerprint
    || reviewSampling.sampleFps !== sampling.sampleFps
    || reviewSampling.width !== sampling.width
    || reviewSampling.height !== sampling.height
    || reviewSampling.sampledFrames !== sampling.sampledFrames
    || reviewSampling.totalFrames !== sampling.totalFrames
    || Math.abs(reviewSampling.durationSeconds - sampling.durationSeconds) > 1e-9
    || reviewSampling.durationCoverageRatio !== sampling.durationCoverageRatio
    || reviewSampling.frameSetFingerprint !== sampling.frameSetFingerprint
    || reviewSampling.briefFrameOutlierCount !== sampling.briefFrameOutlierCount
    || reviewSampling.briefFrameOutliersReviewed !== true) {
    throw new Error("human_media_review_sampling_evidence_mismatch");
  }
  var exactAnalysisReference = review.provenance.sourceReferences.some(function (reference) {
    return reference.recordId === analysis.analysisId
      && reference.fingerprint === analysis.analysisFingerprint;
  });
  if (!exactAnalysisReference) throw new Error("human_media_review_analysis_reference_missing");
  return review;
}

function runTool(command, args, options = {}) {
  return new Promise(function (resolve) {
    execFile(command, args, {
      timeout: options.timeout || 30000,
      maxBuffer: options.maxBuffer || 8 * 1024 * 1024,
      encoding: options.encoding || "utf8",
    }, function (error, stdout, stderr) {
      resolve({
        ok: !error,
        error: error ? String(error.message || error) : null,
        stdout: stdout || (options.encoding === "buffer" ? Buffer.alloc(0) : ""),
        stderr: stderr || "",
      });
    });
  });
}

async function sha256File(filePath) {
  var digest = createHash("sha256");
  for await (var chunk of createReadStream(filePath)) digest.update(chunk);
  return digest.digest("hex");
}

async function requireRegularNonSymlink(filePath, code) {
  var fileStat = await lstat(filePath);
  if (fileStat.isSymbolicLink() || !fileStat.isFile()) {
    throw new Error(`${code}_not_regular_or_symlinked`);
  }
  return fileStat;
}

async function stableMediaSnapshot(mediaPath) {
  await requireRegularNonSymlink(mediaPath, "trusted_media_input");
  var root = await mkdtemp(path.join(os.tmpdir(), "contentforge-trusted-media-"));
  var extension = path.extname(mediaPath) || ".bin";
  var snapshotPath = path.join(root, `snapshot${extension}`);
  try {
    await copyFile(mediaPath, snapshotPath);
    await chmod(snapshotPath, 0o400);
    await requireRegularNonSymlink(snapshotPath, "trusted_media_snapshot");
    var mediaSha256 = await sha256File(snapshotPath);
    return {
      path: snapshotPath,
      sha256: mediaSha256,
      cleanup: async function () {
        await rm(root, { recursive: true, force: true });
      },
    };
  } catch (error) {
    await rm(root, { recursive: true, force: true });
    throw error;
  }
}

function parseRate(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  var parts = value.split("/");
  var numerator = Number(parts[0]);
  var denominator = parts.length === 2 ? Number(parts[1]) : 1;
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator === 0) return null;
  return numerator / denominator;
}

function finiteOrUnavailable(value, reason) {
  return Number.isFinite(value) ? value : { available: false, reason };
}

function percentile(values, fraction) {
  if (!values.length) return null;
  var sorted = [...values].sort(function (a, b) { return a - b; });
  var index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * fraction) - 1));
  return sorted[index];
}

function mean(values) {
  return values.length ? values.reduce(function (sum, value) { return sum + value; }, 0) / values.length : null;
}

function median(values) {
  if (!values.length) return null;
  var sorted = [...values].sort(function (a, b) { return a - b; });
  var middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function standardDeviation(values) {
  if (values.length < 2) return 0;
  var average = mean(values);
  return Math.sqrt(mean(values.map(function (value) {
    return (value - average) ** 2;
  })));
}

function correlation(first, second) {
  if (first.length !== second.length || first.length < 3) return null;
  var firstMean = mean(first);
  var secondMean = mean(second);
  var numerator = 0;
  var firstSquare = 0;
  var secondSquare = 0;
  for (var index = 0; index < first.length; index += 1) {
    var firstCentered = first[index] - firstMean;
    var secondCentered = second[index] - secondMean;
    numerator += firstCentered * secondCentered;
    firstSquare += firstCentered ** 2;
    secondSquare += secondCentered ** 2;
  }
  var denominator = Math.sqrt(firstSquare * secondSquare);
  return denominator > 0 ? numerator / denominator : null;
}

function longestRun(values, predicate) {
  var longest = 0;
  var current = 0;
  for (var value of values) {
    current = predicate(value) ? current + 1 : 0;
    longest = Math.max(longest, current);
  }
  return longest;
}

function frameDelta(first, second) {
  var total = 0;
  for (var index = 0; index < FRAME_BYTES; index += 1) {
    total += Math.abs(first[index] - second[index]);
  }
  return total / (FRAME_BYTES * 255);
}

function splitFrames(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length < FRAME_BYTES) return [];
  var complete = Math.floor(buffer.length / FRAME_BYTES);
  var frames = [];
  for (var index = 0; index < complete; index += 1) {
    frames.push(buffer.subarray(index * FRAME_BYTES, (index + 1) * FRAME_BYTES));
  }
  return frames;
}

async function toolRevision(tool, runner) {
  var result = await runner(tool, ["-version"], { timeout: 5000, maxBuffer: 256 * 1024 });
  if (!result.ok) return { available: false, reason: `${tool}_unavailable` };
  var line = String(result.stdout || result.stderr || "").split(/\r?\n/, 1)[0].trim();
  return line ? { available: true, version: line } : { available: false, reason: `${tool}_version_unavailable` };
}

async function probeMedia(mediaPath, runner) {
  var result = await runner("ffprobe", [
    "-v", "error",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    mediaPath,
  ], { timeout: 15000, maxBuffer: 3 * 1024 * 1024 });
  if (!result.ok) throw new Error(`trusted_media_ffprobe_failed:${result.error || "unknown"}`);
  var payload;
  try {
    payload = JSON.parse(String(result.stdout || "{}"));
  } catch (error) {
    throw new Error("trusted_media_ffprobe_invalid_json", { cause: error });
  }
  var streams = Array.isArray(payload.streams) ? payload.streams : [];
  var video = streams.find(function (stream) { return stream.codec_type === "video"; });
  if (!video) throw new Error("trusted_media_video_stream_missing");
  var audio = streams.find(function (stream) { return stream.codec_type === "audio"; }) || null;
  var format = payload.format && typeof payload.format === "object" ? payload.format : {};
  var duration = Number(format.duration ?? video.duration);
  if (!Number.isFinite(duration) || duration <= 0) throw new Error("trusted_media_duration_invalid");
  return {
    raw: payload,
    video,
    audio,
    format,
    duration,
  };
}

async function temporalObservations(mediaPath, runner, { durationSeconds, totalFrames }) {
  var result = await runner("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-i", mediaPath,
    "-vf", `fps=${SAMPLE_FRAMES_PER_SECOND},scale=${SAMPLE_WIDTH}:${SAMPLE_HEIGHT}:force_original_aspect_ratio=decrease,pad=${SAMPLE_WIDTH}:${SAMPLE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=gray`,
    "-an", "-f", "rawvideo", "pipe:1",
  ], { timeout: 45000, maxBuffer: 128 * 1024 * 1024, encoding: "buffer" });
  if (!result.ok) {
    return { available: false, reason: "frame_sampling_failed", error: result.error };
  }
  var frames = splitFrames(result.stdout);
  if (frames.length < 2) return { available: false, reason: "insufficient_sampled_frames", sampledFrames: frames.length };
  var expectedSamples = Math.max(2, Math.floor(durationSeconds * SAMPLE_FRAMES_PER_SECOND));
  var durationCoverageRatio = Math.min(1, frames.length / expectedSamples);
  if (durationCoverageRatio < 0.95) {
    return {
      available: false,
      reason: "incomplete_temporal_sampling",
      sampledFrames: frames.length,
      expectedSamples,
      durationCoverageRatio,
    };
  }
  var frameSetFingerprint = fingerprint(frames.map(function (frame) {
    return createHash("sha256").update(frame).digest("hex");
  }));
  var deltas = [];
  for (var index = 1; index < frames.length; index += 1) deltas.push(frameDelta(frames[index - 1], frames[index]));
  var average = mean(deltas);
  var frozen = deltas.filter(function (value) { return value <= FROZEN_DELTA_THRESHOLD; }).length / deltas.length;
  var active = deltas.filter(function (value) { return value > FROZEN_DELTA_THRESHOLD; }).length / deltas.length;
  var deltaMedian = median(deltas);
  var absoluteDeviations = deltas.map(function (value) {
    return Math.abs(value - deltaMedian);
  });
  var medianAbsoluteDeviation = median(absoluteDeviations);
  var discontinuityThreshold = Math.min(1, Math.max(
    DISCONTINUITY_ABSOLUTE_THRESHOLD,
    deltaMedian + DISCONTINUITY_MIN_EXCESS,
    deltaMedian + (DISCONTINUITY_MAD_SCALE * medianAbsoluteDeviation),
  ));
  var discontinuities = deltas.map(function (value, index) {
    return {
      comparisonIndex: index,
      normalizedFrameDelta: value,
      excessAboveThreshold: Math.max(0, value - discontinuityThreshold),
    };
  }).filter(function (item) {
    return item.normalizedFrameDelta >= discontinuityThreshold;
  });
  var briefFrameOutlierCandidates = [];
  for (var frameIndex = 1; frameIndex < frames.length - 1; frameIndex += 1) {
    var previousToCurrent = deltas[frameIndex - 1];
    var currentToNext = deltas[frameIndex];
    var previousToNext = frameDelta(frames[frameIndex - 1], frames[frameIndex + 1]);
    if (previousToCurrent >= discontinuityThreshold
      && currentToNext >= discontinuityThreshold
      && previousToNext < discontinuityThreshold) {
      briefFrameOutlierCandidates.push({
        sampledFrameIndex: frameIndex,
        previousToCurrentDelta: previousToCurrent,
        currentToNextDelta: currentToNext,
        previousToNextDelta: previousToNext,
      });
    }
  }
  var discontinuityRate = discontinuities.length / deltas.length;
  return {
    available: true,
    sampling: {
      framesPerSecond: SAMPLE_FRAMES_PER_SECOND,
      width: SAMPLE_WIDTH,
      height: SAMPLE_HEIGHT,
      pixelFormat: "gray8",
      sampledFrames: frames.length,
      comparisons: deltas.length,
      totalFrames,
      durationSeconds,
      durationCoverageRatio: 1,
      frameSetFingerprint,
    },
    adjacentNormalizedMeanAbsoluteDeltas: deltas,
    meanNormalizedFrameDelta: average,
    medianNormalizedFrameDelta: deltaMedian,
    medianAbsoluteDeviation,
    p95NormalizedFrameDelta: percentile(deltas, 0.95),
    maxNormalizedFrameDelta: Math.max(...deltas),
    frozenFrameRatio: frozen,
    activeFrameRatio: active,
    longestFrozenRunComparisons: longestRun(deltas, function (value) {
      return value <= FROZEN_DELTA_THRESHOLD;
    }),
    frozenDeltaThreshold: FROZEN_DELTA_THRESHOLD,
    discontinuityThreshold,
    discontinuityAbsoluteFloor: DISCONTINUITY_ABSOLUTE_THRESHOLD,
    discontinuityMadScale: DISCONTINUITY_MAD_SCALE,
    discontinuityMinExcess: DISCONTINUITY_MIN_EXCESS,
    discontinuityCandidates: discontinuities,
    discontinuityCandidateCount: discontinuities.length,
    discontinuityComparisonCount: deltas.length,
    discontinuityRate,
    briefFrameOutlierCandidates,
    briefFrameOutlierCount: briefFrameOutlierCandidates.length,
    loopSeamScore: frameDelta(frames[0], frames[frames.length - 1]),
  };
}

function parseSilence(stderr, duration) {
  var starts = [...String(stderr || "").matchAll(/silence_start:\s*([\d.]+)/g)].map(function (match) { return Number(match[1]); });
  var ends = [...String(stderr || "").matchAll(/silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)/g)];
  var intervals = ends.map(function (match, index) {
    return { startSeconds: starts[index] ?? null, endSeconds: Number(match[1]), durationSeconds: Number(match[2]) };
  });
  var total = intervals.reduce(function (sum, interval) { return sum + (Number.isFinite(interval.durationSeconds) ? interval.durationSeconds : 0); }, 0);
  return { intervals, totalSilenceSeconds: total, silenceRatio: duration > 0 ? Math.min(1, total / duration) : null };
}

async function audioObservations(mediaPath, probe, runner) {
  if (!probe.audio) return { available: false, reason: "audio_stream_missing" };
  var [silenceResult, volumeResult, truePeakResult] = await Promise.all([
    runner("ffmpeg", [
      "-hide_banner", "-i", mediaPath,
      "-af", "silencedetect=noise=-35dB:d=0.25",
      "-vn", "-f", "null", "-",
    ], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }),
    runner("ffmpeg", [
      "-hide_banner", "-i", mediaPath,
      "-af", "volumedetect",
      "-vn", "-f", "null", "-",
    ], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }),
    runner("ffmpeg", [
      "-hide_banner", "-i", mediaPath,
      "-af", "ebur128=peak=true",
      "-vn", "-f", "null", "-",
    ], { timeout: 30000, maxBuffer: 2 * 1024 * 1024 }),
  ]);
  var silence = silenceResult.ok
    ? parseSilence(silenceResult.stderr, probe.duration)
    : { available: false, reason: "silence_analysis_failed" };
  var maxVolumeMatch = String(volumeResult.stderr || "").match(/max_volume:\s*(-?[\d.]+)\s*dB/i);
  var maxVolumeDb = maxVolumeMatch ? Number(maxVolumeMatch[1]) : null;
  var truePeakMatches = [...String(truePeakResult.stderr || "").matchAll(/Peak:\s*(-?[\d.]+)\s*dBFS/gi)];
  var truePeakDbfs = truePeakMatches.length
    ? Number(truePeakMatches[truePeakMatches.length - 1][1])
    : null;
  var videoStart = Number(probe.video.start_time ?? 0);
  var audioStart = Number(probe.audio.start_time ?? 0);
  var audioDuration = Number(probe.audio.duration ?? probe.format.duration);
  var startOffsetMs = Number.isFinite(videoStart) && Number.isFinite(audioStart)
    ? Math.round((audioStart - videoStart) * 1000)
    : null;
  var durationDeltaMs = Number.isFinite(audioDuration)
    ? Math.round((audioDuration - probe.duration) * 1000)
    : null;
  return {
    available: true,
    codec: probe.audio.codec_name || null,
    sampleRate: Number(probe.audio.sample_rate) || null,
    channels: Number(probe.audio.channels) || null,
    durationSeconds: Number.isFinite(audioDuration) ? audioDuration : null,
    silence,
    maxVolumeDb: finiteOrUnavailable(maxVolumeDb, "max_volume_unavailable"),
    truePeakDbfs: finiteOrUnavailable(truePeakDbfs, "true_peak_unavailable"),
    clippingObserved: Number.isFinite(truePeakDbfs)
      ? truePeakDbfs >= -0.1
      : { available: false, reason: "true_peak_unavailable" },
    avStreamStartOffsetMs: finiteOrUnavailable(startOffsetMs, "stream_start_offset_unavailable"),
    avDurationDeltaMs: finiteOrUnavailable(durationDeltaMs, "stream_duration_delta_unavailable"),
    alignmentScope: "container_stream_timing_only_not_lip_sync",
  };
}

function pcmRmsAt(buffer, timeSeconds, sampleRate = LIP_SYNC_SAMPLE_RATE) {
  var center = Math.round(timeSeconds * sampleRate);
  var halfWindow = Math.round(sampleRate * 0.04);
  var start = Math.max(0, center - halfWindow);
  var end = Math.min(Math.floor(buffer.length / 2), center + halfWindow);
  if (end - start < Math.round(sampleRate * 0.02)) return null;
  var squareSum = 0;
  for (var index = start; index < end; index += 1) {
    var normalized = buffer.readInt16LE(index * 2) / 32768;
    squareSum += normalized ** 2;
  }
  return Math.sqrt(squareSum / (end - start));
}

function lipSyncFailure(reason, details = {}) {
  return { available: false, reason, ...details };
}

async function lipSyncObservations(mediaPath, probe, runner, visualRegistration) {
  var visualResult = await runner(getPythonCommand(), [LIP_SYNC_ANALYZER_PATH, mediaPath], {
    timeout: 60000,
    maxBuffer: 8 * 1024 * 1024,
  });
  if (!visualResult.ok) {
    return lipSyncFailure("local_face_analysis_failed", {
      error: visualResult.error || "unknown",
    });
  }
  var visual;
  try {
    visual = JSON.parse(String(visualResult.stdout || "{}"));
  } catch (error) {
    return lipSyncFailure("local_face_analysis_invalid_json", {
      error: String(error.message || error),
    });
  }
  if (visual.available !== true) {
    return lipSyncFailure(visual.reason || "local_face_analysis_unavailable", {
      visualAnalysis: visual,
    });
  }
  if (!probe.audio) {
    return lipSyncFailure("audio_stream_missing", { visualAnalysis: visual });
  }
  var pcmResult = await runner("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-i", mediaPath,
    "-vn", "-ac", "1", "-ar", String(LIP_SYNC_SAMPLE_RATE),
    "-f", "s16le", "pipe:1",
  ], {
    timeout: 45000,
    maxBuffer: 64 * 1024 * 1024,
    encoding: "buffer",
  });
  if (!pcmResult.ok || !Buffer.isBuffer(pcmResult.stdout) || pcmResult.stdout.length < 2) {
    return lipSyncFailure("audio_pcm_sampling_failed", {
      error: pcmResult.error || "empty_audio_pcm",
      visualAnalysis: visual,
    });
  }
  var faceCoverage = Number(visual.sampling?.faceTrackCoverage);
  var samples = Array.isArray(visual.mouthMotionEnvelope)
    ? visual.mouthMotionEnvelope.map(function (item) {
        return {
          timeSeconds: Number(item.timeSeconds),
          articulationMotion: Number(item.articulationMotion),
        };
      }).filter(function (item) {
        return Number.isFinite(item.timeSeconds)
          && item.timeSeconds >= 0
          && Number.isFinite(item.articulationMotion)
          && item.articulationMotion >= 0
          && item.articulationMotion <= 1;
      })
    : [];
  if (!Number.isFinite(faceCoverage) || faceCoverage < LIP_SYNC_MIN_FACE_COVERAGE) {
    return lipSyncFailure("face_track_incomplete", {
      faceTrackCoverage: Number.isFinite(faceCoverage) ? faceCoverage : null,
    });
  }
  if (samples.length < LIP_SYNC_MIN_SAMPLES) {
    return lipSyncFailure("insufficient_lip_sync_samples", {
      sampleCount: samples.length,
      faceTrackCoverage: faceCoverage,
    });
  }
  var visualEnvelope = samples.map(function (item) { return item.articulationMotion; });
  var visualSpread = standardDeviation(visualEnvelope);
  if (visualSpread < LIP_SYNC_MIN_VISUAL_SPREAD) {
    return lipSyncFailure("visual_speech_motion_missing", {
      sampleCount: samples.length,
      faceTrackCoverage: faceCoverage,
      visualSpread,
    });
  }
  var baselineAudio = samples.map(function (item) {
    return pcmRmsAt(pcmResult.stdout, item.timeSeconds);
  }).filter(Number.isFinite);
  if (baselineAudio.length < LIP_SYNC_MIN_SAMPLES) {
    return lipSyncFailure("insufficient_audio_samples", {
      sampleCount: baselineAudio.length,
      faceTrackCoverage: faceCoverage,
    });
  }
  var audioP10 = percentile(baselineAudio, 0.10);
  var audioP90 = percentile(baselineAudio, 0.90);
  var activityThreshold = Math.max(0.003, audioP10 + Math.max(0.001, (audioP90 - audioP10) * 0.20));
  var speechActivityRatio = baselineAudio.filter(function (value) {
    return value >= activityThreshold;
  }).length / baselineAudio.length;
  if (speechActivityRatio < LIP_SYNC_MIN_AUDIO_ACTIVITY_RATIO || audioP90 - audioP10 < 0.001) {
    return lipSyncFailure("speech_activity_missing", {
      sampleCount: baselineAudio.length,
      faceTrackCoverage: faceCoverage,
      speechActivityRatio,
      audioRmsP10: audioP10,
      audioRmsP90: audioP90,
    });
  }

  var candidates = [];
  for (var offsetMs = -LIP_SYNC_OFFSET_LIMIT_MS;
    offsetMs <= LIP_SYNC_OFFSET_LIMIT_MS;
    offsetMs += LIP_SYNC_OFFSET_STEP_MS) {
    var matchedVisual = [];
    var matchedAudio = [];
    for (var sample of samples) {
      var rms = pcmRmsAt(pcmResult.stdout, sample.timeSeconds + (offsetMs / 1000));
      if (!Number.isFinite(rms)) continue;
      matchedVisual.push(sample.articulationMotion);
      matchedAudio.push(rms);
    }
    var exactCorrelation = correlation(matchedVisual, matchedAudio);
    if (exactCorrelation !== null && matchedVisual.length >= LIP_SYNC_MIN_SAMPLES) {
      candidates.push({
        offsetMs,
        correlation: Math.max(-1, Math.min(1, exactCorrelation)),
        sampleCount: matchedVisual.length,
      });
    }
  }
  if (!candidates.length) {
    return lipSyncFailure("insufficient_correlation_evidence", {
      sampleCount: samples.length,
      faceTrackCoverage: faceCoverage,
      speechActivityRatio,
    });
  }
  candidates.sort(function (first, second) {
    return second.correlation - first.correlation
      || Math.abs(first.offsetMs) - Math.abs(second.offsetMs)
      || first.offsetMs - second.offsetMs;
  });
  var best = candidates[0];
  var confidence = Math.max(0, Math.min(1, (best.correlation + 1) / 2));
  return {
    available: true,
    analyzerMethod: "audio_energy_to_local_face_tracked_mouth_articulation",
    visualAnalyzer: {
      analyzerId: visualRegistration.analyzerId,
      analyzerVersion: visualRegistration.analyzerVersion,
      implementationRef: visualRegistration.implementationRef,
      implementationFingerprint: visualRegistration.implementationFingerprint,
    },
    confidence,
    offsetMs: best.offsetMs,
    aligned: confidence >= 0.65 && Math.abs(best.offsetMs) <= 120,
    correlation: best.correlation,
    sampleCount: best.sampleCount,
    faceTrackCoverage: faceCoverage,
    speechActivityRatio,
    speechActivityConfirmed: true,
    visualSpread,
    audioRmsP10: audioP10,
    audioRmsP90: audioP90,
    activityThreshold,
    testedOffsetsMs: candidates.map(function (item) { return item.offsetMs; }),
    visualAnalysis: visual,
  };
}

function overlayObservations(overlayEvidence, mediaSha256, overlaysExist) {
  if (!overlaysExist) return { available: false, reason: "overlay_not_present", applicable: false };
  if (!overlayEvidence || typeof overlayEvidence !== "object" || Array.isArray(overlayEvidence)) {
    return { available: false, reason: "overlay_evidence_missing", applicable: true };
  }
  var subject = overlayEvidence.subjectSha256 || overlayEvidence.mediaSha256 || null;
  if (subject !== mediaSha256) return { available: false, reason: "overlay_subject_mismatch", applicable: true };
  return {
    available: true,
    applicable: true,
    subjectSha256: subject,
    evidenceFingerprint: fingerprint(overlayEvidence),
    evidence: overlayEvidence,
  };
}

function analyzerResult(definition, registration, registry, observations, toolRevisions) {
  var requiredTools = definition.analyzerId.endsWith("media_integrity")
    ? ["ffprobe"]
    : definition.analyzerId.endsWith("overlay_delivery")
      ? []
      : ["ffmpeg", "ffprobe"];
  var unavailableTool = requiredTools.find(function (tool) {
    return toolRevisions[tool]?.available !== true;
  });
  var effectiveObservations = unavailableTool
    ? { available: false, reason: `${unavailableTool}_revision_unavailable` }
    : observations;
  return {
    analyzerId: definition.analyzerId,
    analyzerVersion: definition.analyzerVersion,
    evidenceKinds: [...definition.evidenceKinds],
    analyzerRegistryId: registry.registryId,
    analyzerRegistryFingerprint: registry.registryFingerprint,
    implementationRef: registration.implementationRef,
    implementationFingerprint: registration.implementationFingerprint,
    toolRevisions,
    status: effectiveObservations.applicable === false
      ? "not_applicable"
      : effectiveObservations.available === false
        ? "unavailable"
        : "measured",
    observations: effectiveObservations,
  };
}

function analyzerVerdict(record, subjectSha256, analysisId) {
  var passed = record.status === "measured" || record.status === "not_applicable";
  return {
    schema: "contentforge.trusted_analyzer_receipt.v1",
    policy: { id: record.analyzerId, version: record.analyzerVersion },
    subjectSha256,
    analysisId,
    observationFingerprint: fingerprint(record),
    analyzerRegistryId: record.analyzerRegistryId,
    analyzerRegistryFingerprint: record.analyzerRegistryFingerprint,
    implementationRef: record.implementationRef,
    implementationFingerprint: record.implementationFingerprint,
    verdict: passed ? "pass" : "blocked",
    passed,
    evidenceOnly: true,
    providerCalls: 0,
    reasons: passed ? [] : [{
      code: record.observations.reason || "measurement_unavailable",
      severity: "block",
    }],
  };
}

async function verifiedRegistry(analyzerRegistry, repositoryRoot) {
  requireSchema(validateAnalyzerRegistrySchema, analyzerRegistry, "trusted_media_analyzer_registry_schema_invalid");
  if (!analyzerRegistry || analyzerRegistry.schema !== "creator_os.analyzer_registry.v1") {
    throw new Error("trusted_media_analyzer_registry_invalid");
  }
  if (typeof analyzerRegistry.registryId !== "string" || !analyzerRegistry.registryId.trim()) {
    throw new Error("trusted_media_analyzer_registry_id_missing");
  }
  if (!Array.isArray(analyzerRegistry.analyzers)) {
    throw new Error("trusted_media_analyzer_registry_entries_missing");
  }
  requireCurrentTimestamp(
    analyzerRegistry.provenance.producedAt,
    "trusted_media_analyzer_registry_timestamp",
  );
  var root = path.resolve(repositoryRoot || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../.."));
  var registrations = new Map();
  for (var item of analyzerRegistry.analyzers) {
    if (!item || typeof item !== "object") throw new Error("trusted_media_analyzer_registration_invalid");
    var key = `${item.analyzerId}@${item.analyzerVersion}`;
    if (registrations.has(key)) throw new Error("trusted_media_duplicate_analyzer_registration");
    if (!/^[a-f0-9]{64}$/.test(item.implementationFingerprint || "")) {
      throw new Error(`trusted_media_analyzer_implementation_fingerprint_invalid:${key}`);
    }
    var implementationPath = path.resolve(root, String(item.implementationRef || ""));
    var relative = path.relative(root, implementationPath);
    if (!relative || relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
      throw new Error(`trusted_media_analyzer_implementation_outside_root:${key}`);
    }
    var implementationStat = await stat(implementationPath);
    if (!implementationStat.isFile()) throw new Error(`trusted_media_analyzer_implementation_missing:${key}`);
    var actual = createHash("sha256").update(await readFile(implementationPath)).digest("hex");
    if (actual !== item.implementationFingerprint) {
      throw new Error(`trusted_media_analyzer_implementation_drift:${key}`);
    }
    registrations.set(key, item);
  }
  for (var definition of [...TRUSTED_ANALYZERS, ...REQUIRED_DECISIVE_ANALYZERS]) {
    var key = `${definition.analyzerId}@${definition.analyzerVersion}`;
    var registration = registrations.get(key);
    if (!registration) throw new Error(`trusted_media_required_analyzer_missing:${key}`);
    if (canonicalJsonDeep(registration.evidenceKinds) !== canonicalJsonDeep([...definition.evidenceKinds])) {
      throw new Error(`trusted_media_analyzer_evidence_kinds_mismatch:${key}`);
    }
  }
  var orderedKeys = analyzerRegistry.analyzers.map(function (item) {
    return `${item.analyzerId}@${item.analyzerVersion}`;
  });
  if (canonicalJsonDeep(orderedKeys) !== canonicalJsonDeep([...orderedKeys].sort())) {
    throw new Error("trusted_media_analyzer_registry_order_invalid");
  }
  var references = new Map(analyzerRegistry.provenance.sourceReferences.map(function (item) {
    return [item.recordId, item.fingerprint];
  }));
  if (references.size !== analyzerRegistry.analyzers.length || analyzerRegistry.analyzers.some(function (item) {
    return references.get(`${item.analyzerId}@${item.analyzerVersion}`) !== item.implementationFingerprint;
  })) throw new Error("trusted_media_analyzer_registry_provenance_mismatch");
  return {
    registryId: analyzerRegistry.registryId,
    registryFingerprint: fingerprint(analyzerRegistry),
    registrations,
  };
}

export async function analyzeTrustedMedia({
  mediaPath,
  sourcePath = null,
  expectedMediaSha256 = null,
  expectedSourceSha256 = null,
  producedAt,
  overlaysExist = false,
  overlayEvidence = null,
  analyzerRegistry,
  repositoryRoot = null,
  runner = runTool,
} = {}) {
  requireCurrentTimestamp(producedAt, "trusted_media_analysis_timestamp");
  var registry = await verifiedRegistry(analyzerRegistry, repositoryRoot);
  var resolvedMedia = path.resolve(String(mediaPath || ""));
  await requireRegularNonSymlink(resolvedMedia, "trusted_media_input");
  var snapshot = await stableMediaSnapshot(resolvedMedia);
  try {
    var mediaStat = await stat(snapshot.path);
    var mediaSha256 = snapshot.sha256;
    if (expectedMediaSha256 && expectedMediaSha256 !== mediaSha256) throw new Error("trusted_media_output_sha256_mismatch");
    var sourceSha256 = null;
    var resolvedSource = null;
    if (sourcePath) {
      resolvedSource = path.resolve(sourcePath);
      await requireRegularNonSymlink(resolvedSource, "trusted_media_source");
      sourceSha256 = await sha256File(resolvedSource);
      if (expectedSourceSha256 && expectedSourceSha256 !== sourceSha256) throw new Error("trusted_media_source_sha256_mismatch");
    } else if (expectedSourceSha256) {
      throw new Error("trusted_media_expected_source_missing");
    }

  var probe = await probeMedia(snapshot.path, runner);
  var sourceFramesPerSecond = parseRate(
    probe.video.avg_frame_rate || probe.video.r_frame_rate,
  );
  var totalFrames = Number(probe.video.nb_frames)
    || (sourceFramesPerSecond
      ? Math.max(1, Math.round(probe.duration * sourceFramesPerSecond))
      : null);
  if (!Number.isInteger(totalFrames) || totalFrames <= 0) {
    throw new Error("trusted_media_total_frames_unavailable");
  }
  var [temporal, ffmpegRevision, ffprobeRevision] = await Promise.all([
    temporalObservations(snapshot.path, runner, {
      durationSeconds: probe.duration,
      totalFrames,
    }),
    toolRevision("ffmpeg", runner),
    toolRevision("ffprobe", runner),
  ]);
  if (temporal.available !== true || !temporal.sampling) {
    throw new Error(
      `trusted_media_analysis_critical_measurement_missing:contentforge.temporal_motion@1.0.0:${temporal.reason || "measurement_unavailable"}`,
    );
  }
  var [audio, lipSync] = await Promise.all([
    audioObservations(snapshot.path, probe, runner),
    lipSyncObservations(
      snapshot.path,
      probe,
      runner,
      registry.registrations.get("contentforge.local_face_mouth_track@1.0.0"),
    ),
  ]);
  var media = {
    available: true,
    bytes: mediaStat.size,
    container: probe.format.format_name || null,
    durationSeconds: probe.duration,
    video: {
      codec: probe.video.codec_name || null,
      profile: probe.video.profile || null,
      pixelFormat: probe.video.pix_fmt || null,
      width: Number(probe.video.width) || null,
      height: Number(probe.video.height) || null,
      aspectRatio: Number(probe.video.width) > 0 && Number(probe.video.height) > 0
        ? Number(probe.video.width) / Number(probe.video.height)
        : null,
      framesPerSecond: sourceFramesPerSecond,
      frameCount: totalFrames,
    },
  };
  var tools = { node: process.version, platform: `${os.platform()}-${os.arch()}-${os.release()}`, ffmpeg: ffmpegRevision, ffprobe: ffprobeRevision };
  var analyzerResults = TRUSTED_ANALYZERS.map(function (definition) {
    var observations = definition.analyzerId.endsWith("media_integrity")
      ? media
      : definition.analyzerId.endsWith("temporal_motion")
        ? temporal
        : definition.analyzerId.endsWith("audio_integrity")
          ? audio
          : definition.analyzerId.endsWith("local_lip_sync")
            ? lipSync
            : overlayObservations(overlayEvidence, mediaSha256, overlaysExist);
    var registration = registry.registrations.get(`${definition.analyzerId}@${definition.analyzerVersion}`);
    return analyzerResult(definition, registration, registry, observations, tools);
  });
  await requireRegularNonSymlink(resolvedMedia, "trusted_media_input");
  if (await sha256File(resolvedMedia) !== mediaSha256) {
    throw new Error("trusted_media_input_changed_during_analysis");
  }
  if (await sha256File(snapshot.path) !== mediaSha256) {
    throw new Error("trusted_media_snapshot_changed_during_analysis");
  }
  if (resolvedSource) {
    await requireRegularNonSymlink(resolvedSource, "trusted_media_source");
    if (await sha256File(resolvedSource) !== sourceSha256) {
      throw new Error("trusted_media_source_changed_during_analysis");
    }
  }
  var analysisId = "analysis_" + fingerprint({ mediaSha256, sourceSha256, registryFingerprint: registry.registryFingerprint, analyzers: analyzerResults }).slice(0, 24);
  var core = {
    schema: ANALYSIS_SCHEMA,
    analysisId,
    subject: {
      mediaPath: resolvedMedia,
      mediaSha256,
      sourcePath: resolvedSource,
      sourceSha256,
    },
    producedAt,
    producer: "contentforge.trusted_media_analysis",
    analyzerRegistry: {
      registryId: registry.registryId,
      registryFingerprint: registry.registryFingerprint,
    },
    rawObservations: analyzerResults,
    analyzerVerdicts: analyzerResults.map(function (record) {
      return analyzerVerdict(record, mediaSha256, analysisId);
    }),
    unavailableMeasurements: {
      creatorIdentity: "requires_identity_analyzer_or_structured_human_review",
      faceStability: "requires_face_tracking_analyzer_or_structured_human_review",
      anatomyArtifacts: "requires_anatomy_analyzer_or_structured_human_review",
      ...(lipSync.available === true ? {} : {
        lipSync: lipSync.reason || "local_lip_sync_measurement_unavailable",
      }),
    },
    humanReviewSampling: {
      sampleFps: temporal.sampling.framesPerSecond,
      width: temporal.sampling.width,
      height: temporal.sampling.height,
      sampledFrames: temporal.sampling.sampledFrames,
      totalFrames: temporal.sampling.totalFrames,
      durationSeconds: temporal.sampling.durationSeconds,
      durationCoverageRatio: temporal.sampling.durationCoverageRatio,
      frameSetFingerprint: temporal.sampling.frameSetFingerprint,
      briefFrameOutlierCount: temporal.briefFrameOutlierCount,
    },
  };
  var signedPayload = { ...core, analysisFingerprint: fingerprint(core) };
  var analysis = {
    ...signedPayload,
    producerAttestation: signEvidenceAttestation(signedPayload, {
      issuer: ANALYSIS_ATTESTATION_ISSUER,
      issuedAt: producedAt,
    }),
  };
  requireSchema(validateTrustedAnalysisSchema, analysis, "trusted_media_analysis_schema_invalid");
  return analysis;
  } finally {
    await snapshot.cleanup();
  }
}

export function motionEvidenceFromTrustedAnalysis(
  analysis,
  { humanReview = null, analyzerRegistry = null } = {},
) {
  var observations = validateAnalysisRecord(analysis);
  var subjectSha256 = analysis.subject && analysis.subject.mediaSha256;
  var registry = analysis.analyzerRegistry;
  if (!registry || !/^[a-f0-9]{64}$/.test(registry.registryFingerprint || "")) {
    throw new Error("trusted_media_analysis_registry_missing");
  }
  if (analysis.rawObservations.some(function (record) {
    return record.analyzerRegistryId !== registry.registryId
      || record.analyzerRegistryFingerprint !== registry.registryFingerprint;
  })) throw new Error("trusted_media_analysis_registry_mismatch");
  var byId = Object.fromEntries([...observations.values()].map(function (record) { return [record.analyzerId, record]; }));
  var temporal = byId["contentforge.temporal_motion"];
  var audio = byId["contentforge.audio_integrity"];
  var lipSync = byId["contentforge.local_lip_sync"];
  var review = humanReview === null ? null : validateHumanReviewRecord(humanReview, analysis);
  var humanRegistration = analyzerRegistry?.analyzers?.find(function (item) {
    return item.analyzerId === HUMAN_REVIEW_ATTESTATION_ISSUER
      && item.analyzerVersion === "1.0.0";
  }) || null;
  function descriptor(record, values) {
    if (!record || record.status !== "measured") return { available: false, reason: record?.observations?.reason || "measurement_unavailable", subjectSha256 };
    return {
      available: true,
      analyzer: record.analyzerId,
      analyzerVersion: record.analyzerVersion,
      evidenceId: analysis.analysisId,
      subjectSha256,
      analysisFingerprint: analysis.analysisFingerprint,
      analyzerRegistryId: record.analyzerRegistryId,
      analyzerRegistryFingerprint: record.analyzerRegistryFingerprint,
      implementationRef: record.implementationRef,
      implementationFingerprint: record.implementationFingerprint,
      ...values,
    };
  }
  function human(values, reason) {
    return review
      ? {
          available: true,
          analyzer: HUMAN_REVIEW_ATTESTATION_ISSUER,
          analyzerVersion: review.rubricVersion,
          evidenceId: review.reviewId,
          subjectSha256,
          analysisFingerprint: analysis.analysisFingerprint,
          analyzerRegistryId: registry.registryId,
          analyzerRegistryFingerprint: registry.registryFingerprint,
          implementationRef: humanRegistration?.implementationRef || null,
          implementationFingerprint: humanRegistration?.implementationFingerprint || null,
          reviewFingerprint: review.reviewFingerprint,
          ...values,
        }
      : { available: false, reason, subjectSha256 };
  }
  var temporalValues = temporal?.observations || {};
  var audioValues = audio?.observations || {};
  var offset = typeof audioValues.avStreamStartOffsetMs === "number" ? audioValues.avStreamStartOffsetMs : null;
  var durationDelta = typeof audioValues.avDurationDeltaMs === "number" ? audioValues.avDurationDeltaMs : null;
  var technicalConfidence = offset === null || durationDelta === null
    ? null
    : Math.max(0, 1 - Math.min(1, Math.max(Math.abs(offset), Math.abs(durationDelta)) / 1000));
  return {
    trustedAnalysis: {
      analysisId: analysis.analysisId,
      analysisFingerprint: analysis.analysisFingerprint,
      analyzerRegistryId: registry.registryId,
      analyzerRegistryFingerprint: registry.registryFingerprint,
      humanReviewId: review?.reviewId || null,
      humanReviewFingerprint: review?.reviewFingerprint || null,
    },
    motion: descriptor(temporal, { score: temporalValues.meanNormalizedFrameDelta }),
    temporal: descriptor(temporal, {
      discontinuityScore: temporalValues.discontinuityRate,
      discontinuityCandidateCount: temporalValues.discontinuityCandidateCount,
      discontinuityComparisonCount: temporalValues.discontinuityComparisonCount,
      discontinuityRate: temporalValues.discontinuityRate,
      outlierThreshold: temporalValues.discontinuityThreshold,
    }),
    freeze: descriptor(temporal, { frozenFrameRatio: temporalValues.frozenFrameRatio }),
    loop: descriptor(temporal, {
      seamScore: temporalValues.loopSeamScore,
      loopable: review ? review.ratings.loopAcceptable : false,
      reviewFingerprint: review?.reviewFingerprint || null,
    }),
    identity: human({ similarityScore: review?.ratings?.creatorIdentitySimilarity, matched: review?.decisions?.creatorIdentityPreserved }, "identity_review_unavailable"),
    anatomy: human({
      face: { applicable: true, anomalyScore: review?.ratings?.faceArtifactScore },
      hands: review?.ratings?.handsVisible === false ? { applicable: false, reason: "hands_not_visible_in_reviewed_media" } : { applicable: true, anomalyScore: review?.ratings?.handArtifactScore },
      body: { applicable: true, anomalyScore: review?.ratings?.bodyArtifactScore },
    }, "anatomy_review_unavailable"),
    lipSync: descriptor(lipSync, {
      confidence: lipSync?.observations?.confidence,
      offsetMs: lipSync?.observations?.offsetMs,
      aligned: lipSync?.observations?.aligned,
      correlation: lipSync?.observations?.correlation,
      sampleCount: lipSync?.observations?.sampleCount,
      faceTrackCoverage: lipSync?.observations?.faceTrackCoverage,
      speechActivityRatio: lipSync?.observations?.speechActivityRatio,
    }),
    audioAlignment: technicalConfidence === null
      ? { available: false, reason: "audio_stream_timing_unavailable", subjectSha256 }
      : descriptor(audio, { confidence: technicalConfidence, offsetMs: offset, aligned: Math.abs(offset) <= 120 }),
  };
}

export async function buildTrustedMotionSpecificQc({
  analysis,
  analyzerRegistry,
  humanReview,
  options = {},
  repositoryRoot = REPOSITORY_ROOT,
} = {}) {
  var registry = await verifiedRegistry(analyzerRegistry, repositoryRoot);
  validateAnalysisRecord(analysis);
  var review = validateHumanReviewRecord(humanReview, analysis);
  if (analysis.analyzerRegistry.registryId !== registry.registryId
    || analysis.analyzerRegistry.registryFingerprint !== registry.registryFingerprint) {
    throw new Error("trusted_media_analysis_registry_snapshot_mismatch");
  }
  var evidence = motionEvidenceFromTrustedAnalysis(analysis, {
    humanReview: review,
    analyzerRegistry,
  });
  var evaluation = evaluateMotionSpecificQc(evidence, {
    ...options,
    mediaSha256: analysis.subject.mediaSha256,
  });
  var reasons = [...evaluation.reasons];
  if (!review.decisions.anatomyAcceptable) {
    reasons.push({
      code: "human_review_anatomy_rejected",
      severity: "fail",
      message: "Structured human review rejected anatomy",
    });
  }
  if (!review.decisions.creatorIdentityPreserved
    && !reasons.some(function (item) { return item.code === "identity_mismatch"; })) {
    reasons.push({
      code: "human_review_identity_rejected",
      severity: "fail",
      message: "Structured human review rejected creator identity",
    });
  }
  if (!review.decisions.operatorUseful) {
    reasons.push({
      code: "human_review_operator_usefulness_rejected",
      severity: "fail",
      message: "Structured human review rejected operator usefulness",
    });
  }
  if (!review.decisions.approvedForBenchmark) {
    reasons.push({
      code: "human_review_benchmark_approval_rejected",
      severity: "fail",
      message: "Structured human review rejected benchmark eligibility",
    });
  }
  if (review.provenance.reviewMode !== "blinded") {
    reasons.push({
      code: "human_review_not_blinded",
      severity: "block",
      message: "Motion QC requires a genuinely blinded human review",
    });
  }
  var blocked = reasons.some(function (item) { return item.severity === "block"; });
  var failed = reasons.some(function (item) { return item.severity === "fail"; });
  var verdict = blocked ? "blocked" : failed ? "fail" : "pass";
  var core = {
    ...evaluation,
    schema: "contentforge.motion_specific_qc_receipt.v2",
    producer: "contentforge.trusted_motion_qc",
    policy: { id: "contentforge.motion_specific_qc", version: "2.0.0" },
    sourceSha256: analysis.subject.sourceSha256,
    verdict,
    passed: verdict === "pass",
    reasons,
    trustedEvidence: {
      analysis,
      analyzerRegistry,
      humanReview: review,
    },
    bindings: {
      analysisId: analysis.analysisId,
      analysisFingerprint: analysis.analysisFingerprint,
      analyzerRegistryId: registry.registryId,
      analyzerRegistryFingerprint: registry.registryFingerprint,
      humanReviewId: review.reviewId,
      humanReviewFingerprint: review.reviewFingerprint,
    },
  };
  delete core.trustedAnalysis;
  var signedPayload = { ...core, receiptFingerprint: fingerprint(core) };
  var receipt = {
    ...signedPayload,
    producerAttestation: signEvidenceAttestation(signedPayload, {
      issuer: RECEIPT_ATTESTATION_ISSUER,
      issuedAt: review.reviewedAt,
    }),
  };
  requireSchema(validateMotionReceiptSchema, receipt, "trusted_motion_qc_receipt_schema_invalid");
  return receipt;
}

export async function rerunTrustedMotionSpecificQc({
  mediaPath,
  sourcePath,
  expectedMediaSha256 = null,
  expectedSourceSha256 = null,
  producedAt,
  overlaysExist = false,
  overlayEvidence = null,
  analyzerRegistry,
  humanReview,
  options = {},
  repositoryRoot = REPOSITORY_ROOT,
  runner = runTool,
} = {}) {
  if (typeof sourcePath !== "string" || !sourcePath.trim()) {
    throw new Error("trusted_motion_qc_source_path_required");
  }
  var analysis = await analyzeTrustedMedia({
    mediaPath,
    sourcePath,
    expectedMediaSha256,
    expectedSourceSha256,
    producedAt,
    overlaysExist,
    overlayEvidence,
    analyzerRegistry,
    repositoryRoot,
    runner,
  });
  return buildTrustedMotionSpecificQc({
    analysis,
    analyzerRegistry,
    humanReview,
    options,
    repositoryRoot,
  });
}

export function trustedMediaAnalysisSchema() {
  return ANALYSIS_SCHEMA;
}
