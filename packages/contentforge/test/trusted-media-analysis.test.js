import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  analyzeTrustedMedia,
  buildTrustedMotionSpecificQc,
  motionEvidenceFromTrustedAnalysis,
  rerunTrustedMotionSpecificQc,
} from "../lib/trusted-media-analysis.js";
import { snapshotTrustedMediaAnalyzerRegistry } from "../lib/analyzer-registry.js";
import { signEvidenceAttestation } from "../lib/evidence-attestation.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");
const TEST_SECRET = "contentforge-test-secret-0123456789-abcdef";
const ORIGINAL_SECRET = process.env.CREATOR_OS_EVIDENCE_AUTH_SECRET;

test.before(function () {
  process.env.CREATOR_OS_EVIDENCE_AUTH_SECRET = TEST_SECRET;
});

test.after(function () {
  if (ORIGINAL_SECRET === undefined) delete process.env.CREATOR_OS_EVIDENCE_AUTH_SECRET;
  else process.env.CREATOR_OS_EVIDENCE_AUTH_SECRET = ORIGINAL_SECRET;
});

function canonicalJson(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(function (key) {
      return JSON.stringify(key) + ":" + canonicalJson(value[key]);
    }).join(",") + "}";
  }
  return JSON.stringify(value);
}

function fingerprint(value) {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function resignReview(review) {
  var core = { ...review };
  delete core.reviewFingerprint;
  delete core.operatorAttestation;
  var signedPayload = { ...core, reviewFingerprint: fingerprint(core) };
  return {
    ...signedPayload,
    operatorAttestation: signEvidenceAttestation(signedPayload, {
      issuer: "reel_factory.structured_human_media_review",
      issuedAt: signedPayload.reviewedAt,
    }),
  };
}

async function registry(producedAt) {
  return snapshotTrustedMediaAnalyzerRegistry({ producedAt, repositoryRoot: ROOT });
}

function humanReview(analysis, overrides = {}) {
  var sampling = analysis.humanReviewSampling;
  var review = {
    schema: "reel_factory.human_media_review.v1",
    reviewId: "review-1",
    arenaPlanId: "arena-plan-1",
    sampleId: "sample-1",
    blindedCandidateId: "candidate-1",
    subjectSha256: analysis.subject.mediaSha256,
    sourceSha256: analysis.subject.sourceSha256,
    reviewer: "operator-fixture",
    reviewedAt: "2026-07-22T20:01:00Z",
    rubricVersion: "1.0.0",
    samplingEvidence: {
      analysisId: analysis.analysisId,
      analysisFingerprint: analysis.analysisFingerprint,
      sampleFps: sampling.sampleFps,
      width: sampling.width,
      height: sampling.height,
      sampledFrames: sampling.sampledFrames,
      totalFrames: sampling.totalFrames,
      durationSeconds: sampling.durationSeconds,
      durationCoverageRatio: sampling.durationCoverageRatio,
      frameSetFingerprint: sampling.frameSetFingerprint,
      briefFrameOutlierCount: sampling.briefFrameOutlierCount,
      briefFrameOutliersReviewed: true,
    },
    ratings: {
      realism: 0.9,
      attractiveness: 0.9,
      creatorIdentitySimilarity: 0.91,
      faceStability: 0.9,
      motionNaturalness: 0.88,
      faceArtifactScore: 0.05,
      handsVisible: false,
      handArtifactScore: null,
      bodyArtifactScore: 0.07,
      conversionUsefulness: 0.86,
      intentAdherence: 0.92,
      loopAcceptable: true,
    },
    decisions: {
      creatorIdentityPreserved: true,
      anatomyAcceptable: true,
      operatorUseful: true,
      approvedForBenchmark: true,
    },
    provenance: {
      reviewMode: "blinded",
      unblindingReason: null,
      sourceReferences: [{
        recordId: analysis.analysisId,
        fingerprint: analysis.analysisFingerprint,
      }],
    },
    ...overrides,
  };
  return resignReview(review);
}

function fixtureLipEnvelope() {
  var pattern = [0.01, 0.09, 0.02, 0.13, 0.03, 0.11, 0.015, 0.08];
  return Array.from({ length: 24 }, function (_, index) {
    return {
      timeSeconds: 0.2 + (index * 0.23),
      mouthDelta: pattern[index % pattern.length] + 0.01,
      upperFaceDelta: 0.01,
      articulationMotion: pattern[index % pattern.length],
    };
  });
}

function fixturePcm(envelope, { shiftSeconds = 0, silent = false } = {}) {
  var sampleRate = 16000;
  var durationSeconds = 6;
  var buffer = Buffer.alloc(sampleRate * durationSeconds * 2);
  for (var index = 0; index < sampleRate * durationSeconds; index += 1) {
    var time = (index / sampleRate) - shiftSeconds;
    var nearest = envelope.reduce(function (best, item) {
      return Math.abs(item.timeSeconds - time) < Math.abs(best.timeSeconds - time) ? item : best;
    }, envelope[0]);
    var amplitude = silent ? 0 : Math.round(300 + (nearest.articulationMotion * 20000));
    buffer.writeInt16LE(index % 2 ? -amplitude : amplitude, index * 2);
  }
  return buffer;
}

function fixtureRunner({
  withAudio = true,
  lipSyncMode = "aligned",
  temporalFrameValues = null,
} = {}) {
  var lipEnvelope = fixtureLipEnvelope();
  var exactTemporalFrameValues = temporalFrameValues || Array.from(
    { length: 48 },
    function (_, index) {
      return index <= 25 ? index * 10 : (50 - index) * 10;
    },
  );
  return async function runner(command, args, options = {}) {
    if (args[0] === "-version") {
      return { ok: true, stdout: `${command} version fixture-1.0\n`, stderr: "", error: null };
    }
    if (command === "ffprobe") {
      return {
        ok: true,
        stdout: JSON.stringify({
          streams: [
            {
              codec_type: "video",
              codec_name: "h264",
              profile: "High",
              pix_fmt: "yuv420p",
              width: 1080,
              height: 1920,
              avg_frame_rate: "30/1",
              nb_frames: "180",
              start_time: "0.000000",
            },
            ...(withAudio ? [{
              codec_type: "audio",
              codec_name: "aac",
              sample_rate: "48000",
              channels: 2,
              duration: "6.000000",
              start_time: "0.040000",
            }] : []),
          ],
          format: { duration: "6.000000", size: "1024", format_name: "mov,mp4" },
        }),
        stderr: "",
        error: null,
      };
    }
    if (String(args[0]).endsWith("local-lip-sync-analyzer.py")) {
      if (lipSyncMode === "missing_face") {
        return {
          ok: true,
          stdout: JSON.stringify({
            available: false,
            reason: "insufficient_face_track",
            sampling: { faceTrackCoverage: 0, sampledFrames: 24, faceFrames: 0 },
          }),
          stderr: "",
          error: null,
        };
      }
      return {
        ok: true,
        stdout: JSON.stringify({
          available: true,
          runtime: { python: "fixture", opencv: "fixture", detector: "fixture" },
          sampling: {
            effectiveFramesPerSecond: 12,
            sampledFrames: 25,
            faceFrames: 25,
            faceTrackCoverage: 1,
            multipleFaceFrames: 0,
            multipleFaceRatio: 0,
          },
          mouthMotionEnvelope: lipEnvelope,
        }),
        stderr: "",
        error: null,
      };
    }
    if (command === "ffmpeg" && args.includes("rawvideo")) {
      return {
        ok: true,
        stdout: Buffer.concat(exactTemporalFrameValues.map(function (value) {
          return Buffer.alloc(180 * 320, value);
        })),
        stderr: "",
        error: null,
      };
    }
    if (command === "ffmpeg" && args.includes("s16le")) {
      return {
        ok: true,
        stdout: fixturePcm(lipEnvelope, {
          shiftSeconds: lipSyncMode === "misaligned" ? 0.2 : 0,
          silent: lipSyncMode === "missing_speech",
        }),
        stderr: "",
        error: null,
      };
    }
    if (command === "ffmpeg" && args.includes("silencedetect=noise=-35dB:d=0.25")) {
      return { ok: true, stdout: "", stderr: "silence_start: 1.0\nsilence_end: 1.5 | silence_duration: 0.5\n", error: null };
    }
    if (command === "ffmpeg" && args.includes("volumedetect")) {
      return { ok: true, stdout: "", stderr: "max_volume: -0.2 dB\n", error: null };
    }
    if (command === "ffmpeg" && args.includes("ebur128=peak=true")) {
      return { ok: true, stdout: "", stderr: "True peak:\n Peak: -0.2 dBFS\n", error: null };
    }
    return {
      ok: false,
      stdout: options.encoding === "buffer" ? Buffer.alloc(0) : "",
      stderr: "",
      error: `unexpected command: ${command} ${args.join(" ")}`,
    };
  };
}

async function withFixture(callback) {
  var root = await mkdtemp(path.join(os.tmpdir(), "contentforge-trusted-analysis-"));
  try {
    var media = path.join(root, "output.mp4");
    var source = path.join(root, "source.png");
    await writeFile(media, "measured media bytes");
    await writeFile(source, "source image bytes");
    return await callback({ root, media, source });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

function run(command, args) {
  return new Promise(function (resolve, reject) {
    execFile(command, args, { timeout: 60000 }, function (error, stdout, stderr) {
      if (error) reject(new Error(stderr || error.message));
      else resolve({ stdout, stderr });
    });
  });
}

test("produces deterministic raw observations from exact media", async function () {
  await withFixture(async function ({ media, source }) {
    var args = {
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: await registry("2026-07-22T20:00:00Z"),
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    };
    var first = await analyzeTrustedMedia(args);
    var second = await analyzeTrustedMedia(args);
    assert.deepEqual(second, first);
    assert.equal(first.schema, "contentforge.trusted_media_analysis.v1");
    assert.match(first.subject.mediaSha256, /^[a-f0-9]{64}$/);
    assert.match(first.subject.sourceSha256, /^[a-f0-9]{64}$/);
    assert.match(first.analysisFingerprint, /^[a-f0-9]{64}$/);
    assert.equal(first.producerAttestation.issuer, "contentforge.trusted_media_analysis");
    assert.equal(first.producerAttestation.issuedAt, first.producedAt);
    assert.match(first.producerAttestation.signature, /^[a-f0-9]{64}$/);
    assert.match(first.analyzerRegistry.registryFingerprint, /^[a-f0-9]{64}$/);
    assert.equal(first.rawObservations.length, 5);
    assert.equal(first.analyzerVerdicts.length, 5);
    assert.ok(first.analyzerVerdicts.every(function (item) {
      return item.subjectSha256 === first.subject.mediaSha256 && item.passed;
    }));
    var mediaObservation = first.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.media_integrity";
    });
    assert.equal(mediaObservation.observations.video.width, 1080);
    assert.equal(mediaObservation.observations.video.height, 1920);
    assert.equal(mediaObservation.observations.video.framesPerSecond, 30);
    var temporal = first.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.temporal_motion";
    });
    assert.equal(temporal.observations.sampling.sampledFrames, 48);
    assert.equal(temporal.observations.sampling.framesPerSecond, 8);
    assert.equal(temporal.observations.sampling.width, 180);
    assert.equal(temporal.observations.sampling.height, 320);
    assert.equal(temporal.observations.frozenFrameRatio, 0);
    assert.ok(temporal.observations.meanNormalizedFrameDelta > 0);
    assert.equal(temporal.observations.discontinuityRate, 0);
    assert.deepEqual(first.humanReviewSampling, {
      sampleFps: 8,
      width: 180,
      height: 320,
      sampledFrames: 48,
      totalFrames: 180,
      durationSeconds: 6,
      durationCoverageRatio: 1,
      frameSetFingerprint: temporal.observations.sampling.frameSetFingerprint,
      briefFrameOutlierCount: 0,
    });
    var audio = first.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.audio_integrity";
    });
    assert.equal(audio.observations.clippingObserved, false);
    assert.equal(audio.observations.silence.totalSilenceSeconds, 0.5);
    assert.equal(audio.observations.avStreamStartOffsetMs, 40);
    var lipSync = first.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.local_lip_sync";
    });
    assert.equal(lipSync.status, "measured");
    assert.equal(lipSync.observations.aligned, true);
    assert.ok(lipSync.observations.confidence >= 0.65);
    assert.equal(Object.hasOwn(first.unavailableMeasurements, "lipSync"), false);
  });
});

test("fails closed on substituted output and reports missing audio as unavailable", async function () {
  await withFixture(async function ({ media }) {
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: media,
        expectedMediaSha256: "b".repeat(64),
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: await registry("2026-07-22T20:00:00Z"),
        repositoryRoot: ROOT,
        runner: fixtureRunner({ withAudio: false }),
      }),
      /trusted_media_output_sha256_mismatch/,
    );
    var measured = await analyzeTrustedMedia({
      mediaPath: media,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: await registry("2026-07-22T20:00:00Z"),
      repositoryRoot: ROOT,
      runner: fixtureRunner({ withAudio: false }),
    });
    var audio = measured.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.audio_integrity";
    });
    assert.equal(audio.status, "unavailable");
    assert.equal(audio.observations.reason, "audio_stream_missing");
    assert.notEqual(audio.observations.reason, 0);
    var audioVerdict = measured.analyzerVerdicts.find(function (item) {
      return item.policy.id === "contentforge.audio_integrity";
    });
    assert.equal(audioVerdict.verdict, "blocked");
    assert.equal(audioVerdict.passed, false);
    var lipSync = measured.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.local_lip_sync";
    });
    assert.equal(lipSync.status, "unavailable");
    assert.equal(lipSync.observations.reason, "audio_stream_missing");
    assert.equal(measured.unavailableMeasurements.lipSync, "audio_stream_missing");
  });
});

test("rejects symlinked media/source and detects input mutation during analysis", async function () {
  await withFixture(async function ({ root, media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    var mediaLink = path.join(root, "media-link.mp4");
    var sourceLink = path.join(root, "source-link.png");
    await symlink(media, mediaLink);
    await symlink(source, sourceLink);
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: mediaLink,
        sourcePath: source,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: exactRegistry,
        repositoryRoot: ROOT,
        runner: fixtureRunner(),
      }),
      /trusted_media_input_not_regular_or_symlinked/,
    );
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: media,
        sourcePath: sourceLink,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: exactRegistry,
        repositoryRoot: ROOT,
        runner: fixtureRunner(),
      }),
      /trusted_media_source_not_regular_or_symlinked/,
    );
    var baseRunner = fixtureRunner();
    var mutated = false;
    async function mutatingRunner(command, args, options) {
      if (!mutated && command === "ffprobe") {
        mutated = true;
        await writeFile(media, "mutated after immutable snapshot");
      }
      return baseRunner(command, args, options);
    }
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: media,
        sourcePath: source,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: exactRegistry,
        repositoryRoot: ROOT,
        runner: mutatingRunner,
      }),
      /trusted_media_input_changed_during_analysis/,
    );
  });
});

test("scores discontinuity from robust outlier candidates instead of ordinary p95 motion", async function () {
  await withFixture(async function ({ media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    var uniformMotion = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner({
        temporalFrameValues: Array.from({ length: 48 }, function (_, index) {
          return index % 2 === 0 ? 0 : 60;
        }),
      }),
    });
    var uniformTemporal = uniformMotion.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.temporal_motion";
    }).observations;
    assert.ok(uniformTemporal.p95NormalizedFrameDelta > 0.18);
    assert.equal(uniformTemporal.discontinuityCandidateCount, 0);
    assert.equal(uniformTemporal.discontinuityComparisonCount, 47);
    assert.equal(uniformTemporal.discontinuityRate, 0);
    var uniformEvidence = motionEvidenceFromTrustedAnalysis(uniformMotion);
    assert.equal(uniformEvidence.temporal.discontinuityScore, 0);

    var oneCut = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner({
        temporalFrameValues: Array.from({ length: 48 }, function (_, index) {
          return index < 24 ? index * 5 : 230 - ((index - 24) * 5);
        }),
      }),
    });
    var cutTemporal = oneCut.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.temporal_motion";
    }).observations;
    assert.equal(cutTemporal.discontinuityCandidateCount, 1);
    assert.equal(cutTemporal.discontinuityComparisonCount, 47);
    assert.equal(cutTemporal.discontinuityRate, 1 / 47);
    assert.equal(cutTemporal.discontinuityCandidates[0].comparisonIndex, 23);
    assert.ok(cutTemporal.discontinuityCandidates[0].excessAboveThreshold > 0);
    assert.equal(
      motionEvidenceFromTrustedAnalysis(oneCut).temporal.discontinuityScore,
      1 / 47,
    );

    var oneBriefOutlier = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner({
        temporalFrameValues: Array.from({ length: 48 }, function (_, index) {
          return index === 24 ? 230 : 0;
        }),
      }),
    });
    var briefTemporal = oneBriefOutlier.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.temporal_motion";
    }).observations;
    assert.equal(briefTemporal.briefFrameOutlierCount, 1);
    assert.equal(briefTemporal.briefFrameOutlierCandidates[0].sampledFrameIndex, 24);
    assert.equal(oneBriefOutlier.humanReviewSampling.briefFrameOutlierCount, 1);
  });
});

test("speaking QC fails closed without audio, speech activity, or a usable face track", async function () {
  await withFixture(async function ({ media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    for (var scenario of [
      { runner: fixtureRunner({ withAudio: false }), reason: "audio_stream_missing" },
      { runner: fixtureRunner({ lipSyncMode: "missing_speech" }), reason: "speech_activity_missing" },
      { runner: fixtureRunner({ lipSyncMode: "missing_face" }), reason: "insufficient_face_track" },
    ]) {
      var analysis = await analyzeTrustedMedia({
        mediaPath: media,
        sourcePath: source,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: exactRegistry,
        repositoryRoot: ROOT,
        runner: scenario.runner,
      });
      var lipSync = analysis.rawObservations.find(function (item) {
        return item.analyzerId === "contentforge.local_lip_sync";
      });
      assert.equal(lipSync.status, "unavailable");
      assert.equal(lipSync.observations.reason, scenario.reason);
      var review = humanReview(analysis);
      var receipt = await buildTrustedMotionSpecificQc({
        analysis,
        analyzerRegistry: exactRegistry,
        humanReview: review,
        options: { expectsSpeech: true, expectsAudio: true },
        repositoryRoot: ROOT,
      });
      assert.equal(receipt.verdict, "blocked");
      assert.ok(receipt.reasons.some(function (reason) {
        return reason.code === "lip_sync_evidence_unavailable";
      }));
    }
  });
});

test("speaking QC accepts measured alignment and rejects a measured lip-sync offset", async function () {
  await withFixture(async function ({ media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    async function receiptFor(runner) {
      var analysis = await analyzeTrustedMedia({
        mediaPath: media,
        sourcePath: source,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: exactRegistry,
        repositoryRoot: ROOT,
        runner,
      });
      return buildTrustedMotionSpecificQc({
        analysis,
        analyzerRegistry: exactRegistry,
        humanReview: humanReview(analysis),
        options: { expectsSpeech: true, expectsAudio: true },
        repositoryRoot: ROOT,
      });
    }
    var aligned = await receiptFor(fixtureRunner());
    assert.equal(aligned.passed, true, JSON.stringify(aligned.reasons));
    assert.equal(aligned.measurements.lipSync.aligned, true);
    assert.ok(aligned.measurements.lipSync.sampleCount >= 7);
    assert.ok(aligned.measurements.lipSync.faceTrackCoverage >= 0.6);
    assert.ok(aligned.measurements.lipSync.speechActivityRatio >= 0.15);

    var misaligned = await receiptFor(fixtureRunner({ lipSyncMode: "misaligned" }));
    assert.equal(misaligned.passed, false);
    assert.ok(Math.abs(misaligned.measurements.lipSync.offsetMs) > 120);
    assert.ok(misaligned.reasons.some(function (reason) {
      return reason.code === "lip_sync_offset_excessive"
        || reason.code === "lip_sync_not_aligned";
    }));
  });
});

test("adapts measured local lip sync and complete human review", async function () {
  await withFixture(async function ({ media, source }) {
    var analysis = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: await registry("2026-07-22T20:00:00Z"),
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    var withoutReview = motionEvidenceFromTrustedAnalysis(analysis);
    assert.equal(withoutReview.identity.available, false);
    assert.equal(withoutReview.anatomy.available, false);
    assert.equal(withoutReview.lipSync.available, true);
    assert.equal(withoutReview.lipSync.analyzer, "contentforge.local_lip_sync");
    var review = humanReview(analysis);
    var withReview = motionEvidenceFromTrustedAnalysis(analysis, { humanReview: review });
    assert.equal(withReview.identity.matched, true);
    assert.equal(withReview.identity.similarityScore, 0.91);
    assert.deepEqual(withReview.anatomy.hands, {
      applicable: false,
      reason: "hands_not_visible_in_reviewed_media",
    });
    assert.equal(withReview.lipSync.available, true);
    assert.equal(withReview.lipSync.aligned, true);
    assert.equal(withReview.audioAlignment.offsetMs, 40);
  });
});

test("builds a fingerprint-bound v2 receipt and rejects incomplete or substituted reviews", async function () {
  await withFixture(async function ({ media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    var analysis = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    var review = humanReview(analysis);
    var first = await buildTrustedMotionSpecificQc({
      analysis,
      analyzerRegistry: exactRegistry,
      humanReview: review,
      repositoryRoot: ROOT,
    });
    var second = await buildTrustedMotionSpecificQc({
      analysis,
      analyzerRegistry: exactRegistry,
      humanReview: review,
      repositoryRoot: ROOT,
    });
    assert.deepEqual(second, first);
    assert.equal(first.schema, "contentforge.motion_specific_qc_receipt.v2");
    assert.equal(first.policy.version, "2.0.0");
    assert.equal(first.bindings.analysisFingerprint, analysis.analysisFingerprint);
    assert.equal(first.bindings.analyzerRegistryId, exactRegistry.registryId);
    assert.equal(first.bindings.humanReviewFingerprint, review.reviewFingerprint);
    assert.match(first.receiptFingerprint, /^[a-f0-9]{64}$/);
    assert.equal(first.producerAttestation.issuer, "contentforge.trusted_motion_qc");
    assert.equal(first.producerAttestation.issuedAt, review.reviewedAt);

    var incomplete = humanReview(analysis);
    delete incomplete.ratings.realism;
    incomplete.reviewFingerprint = fingerprint((function () {
      var core = { ...incomplete };
      delete core.reviewFingerprint;
      delete core.operatorAttestation;
      return core;
    })());
    await assert.rejects(
      buildTrustedMotionSpecificQc({
        analysis,
        analyzerRegistry: exactRegistry,
        humanReview: incomplete,
        repositoryRoot: ROOT,
      }),
      /human_media_review_schema_invalid/,
    );

    var substituted = humanReview(analysis, { subjectSha256: "b".repeat(64) });
    await assert.rejects(
      buildTrustedMotionSpecificQc({
        analysis,
        analyzerRegistry: exactRegistry,
        humanReview: substituted,
        repositoryRoot: ROOT,
      }),
      /human_media_review_subject_mismatch/,
    );

    var samplingMismatch = humanReview(analysis);
    samplingMismatch.samplingEvidence.sampledFrames += 1;
    samplingMismatch = resignReview(samplingMismatch);
    await assert.rejects(
      buildTrustedMotionSpecificQc({
        analysis,
        analyzerRegistry: exactRegistry,
        humanReview: samplingMismatch,
        repositoryRoot: ROOT,
      }),
      /human_media_review_sampling_evidence_mismatch/,
    );
  });
});

test("reruns exact analyzers and rejects plausible recomputed-fingerprint forgeries", async function () {
  await withFixture(async function ({ media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    var firstAnalysis = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    var review = humanReview(firstAnalysis);
    var rerun = await rerunTrustedMotionSpecificQc({
      mediaPath: media,
      sourcePath: source,
      expectedMediaSha256: firstAnalysis.subject.mediaSha256,
      expectedSourceSha256: firstAnalysis.subject.sourceSha256,
      producedAt: firstAnalysis.producedAt,
      analyzerRegistry: exactRegistry,
      humanReview: review,
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    assert.equal(rerun.bindings.analysisId, firstAnalysis.analysisId);
    assert.equal(
      rerun.trustedEvidence.analysis.analysisFingerprint,
      firstAnalysis.analysisFingerprint,
    );

    var forgedAnalysis = deepClone(firstAnalysis);
    forgedAnalysis.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.temporal_motion";
    }).observations.meanNormalizedFrameDelta = 0.12;
    var analysisCore = { ...forgedAnalysis };
    delete analysisCore.analysisFingerprint;
    delete analysisCore.producerAttestation;
    forgedAnalysis.analysisFingerprint = fingerprint(analysisCore);
    await assert.rejects(
      buildTrustedMotionSpecificQc({
        analysis: forgedAnalysis,
        analyzerRegistry: exactRegistry,
        humanReview: review,
        repositoryRoot: ROOT,
      }),
      /evidence_attestation_payload_mismatch/,
    );

    var forgedReview = deepClone(review);
    forgedReview.ratings.creatorIdentitySimilarity = 1;
    var reviewCore = { ...forgedReview };
    delete reviewCore.reviewFingerprint;
    delete reviewCore.operatorAttestation;
    forgedReview.reviewFingerprint = fingerprint(reviewCore);
    await assert.rejects(
      buildTrustedMotionSpecificQc({
        analysis: firstAnalysis,
        analyzerRegistry: exactRegistry,
        humanReview: forgedReview,
        repositoryRoot: ROOT,
      }),
      /evidence_attestation_payload_mismatch/,
    );
  });
});

test("authenticated review decisions and blinding remain decisive", async function () {
  await withFixture(async function ({ media, source }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    var analysis = await analyzeTrustedMedia({
      mediaPath: media,
      sourcePath: source,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    var rejected = humanReview(analysis, {
      decisions: {
        creatorIdentityPreserved: true,
        anatomyAcceptable: true,
        operatorUseful: true,
        approvedForBenchmark: false,
      },
    });
    var rejectedReceipt = await buildTrustedMotionSpecificQc({
      analysis,
      analyzerRegistry: exactRegistry,
      humanReview: rejected,
      repositoryRoot: ROOT,
    });
    assert.equal(rejectedReceipt.passed, false);
    assert.ok(rejectedReceipt.reasons.some(function (reason) {
      return reason.code === "human_review_benchmark_approval_rejected";
    }));

    var unblinded = humanReview(analysis, {
      provenance: {
        reviewMode: "unblinded",
        unblindingReason: "operator inspected model identity",
        sourceReferences: [{
          recordId: analysis.analysisId,
          fingerprint: analysis.analysisFingerprint,
        }],
      },
    });
    var unblindedReceipt = await buildTrustedMotionSpecificQc({
      analysis,
      analyzerRegistry: exactRegistry,
      humanReview: unblinded,
      repositoryRoot: ROOT,
    });
    assert.equal(unblindedReceipt.verdict, "blocked");
    assert.ok(unblindedReceipt.reasons.some(function (reason) {
      return reason.code === "human_review_not_blinded";
    }));
  });
});

test("public motion-qc CLI quarantines raw and incomplete evidence", async function () {
  var root = await mkdtemp(path.join(os.tmpdir(), "contentforge-motion-cli-"));
  try {
    var rawRequest = path.join(root, "raw.json");
    await writeFile(rawRequest, JSON.stringify({ evidence: {} }));
    await assert.rejects(
      run("node", [path.join(ROOT, "packages/contentforge/cli.mjs"), "motion-qc", rawRequest]),
      /caller-supplied evidence or analysis cannot produce a trusted receipt/,
    );
    var incompleteRequest = path.join(root, "incomplete.json");
    await writeFile(incompleteRequest, JSON.stringify({ analysis: {} }));
    await assert.rejects(
      run("node", [path.join(ROOT, "packages/contentforge/cli.mjs"), "motion-qc", incompleteRequest]),
      /caller-supplied evidence or analysis cannot produce a trusted receipt/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("fails closed on registry implementation drift and analysis tampering", async function () {
  await withFixture(async function ({ media }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
    var missingHumanReview = deepClone(exactRegistry);
    missingHumanReview.analyzers = missingHumanReview.analyzers.filter(function (item) {
      return item.analyzerId !== "reel_factory.structured_human_media_review";
    });
    missingHumanReview.provenance.sourceReferences = missingHumanReview.provenance.sourceReferences.filter(
      function (item) {
        return item.recordId !== "reel_factory.structured_human_media_review@1.0.0";
      },
    );
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: media,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: missingHumanReview,
        repositoryRoot: ROOT,
        runner: fixtureRunner(),
      }),
      /trusted_media_required_analyzer_missing:reel_factory.structured_human_media_review@1.0.0/,
    );
    var missingPolicy = deepClone(exactRegistry);
    missingPolicy.analyzers = missingPolicy.analyzers.filter(function (item) {
      return item.analyzerId !== "contentforge.motion_specific_qc";
    });
    missingPolicy.provenance.sourceReferences = missingPolicy.provenance.sourceReferences.filter(
      function (item) {
        return item.recordId !== "contentforge.motion_specific_qc@2.0.0";
      },
    );
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: media,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: missingPolicy,
        repositoryRoot: ROOT,
        runner: fixtureRunner(),
      }),
      /trusted_media_required_analyzer_missing:contentforge.motion_specific_qc@2.0.0/,
    );
    var drifted = JSON.parse(JSON.stringify(exactRegistry));
    drifted.analyzers[0].implementationFingerprint = "b".repeat(64);
    await assert.rejects(
      analyzeTrustedMedia({
        mediaPath: media,
        producedAt: "2026-07-22T20:00:00Z",
        analyzerRegistry: drifted,
        repositoryRoot: ROOT,
        runner: fixtureRunner(),
      }),
      /trusted_media_analyzer_implementation_drift/,
    );
    var analysis = await analyzeTrustedMedia({
      mediaPath: media,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: exactRegistry,
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    analysis.rawObservations[0].status = "unavailable";
    assert.throws(
      function () { motionEvidenceFromTrustedAnalysis(analysis); },
      /trusted_media_analysis_fingerprint_mismatch/,
    );
  });
});

test("measures a real ffmpeg MP4 without provider or model calls", async function () {
  var root = await mkdtemp(path.join(os.tmpdir(), "contentforge-real-analysis-"));
  try {
    var media = path.join(root, "real.mp4");
    await run("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-y",
      "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24:duration=2",
      "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
      media,
    ]);
    var analysis = await analyzeTrustedMedia({
      mediaPath: media,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: await registry("2026-07-22T20:00:00Z"),
      repositoryRoot: ROOT,
    });
    var mediaResult = analysis.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.media_integrity";
    });
    var temporalResult = analysis.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.temporal_motion";
    });
    var audioResult = analysis.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.audio_integrity";
    });
    assert.equal(mediaResult.status, "measured");
    assert.equal(mediaResult.observations.video.width, 360);
    assert.equal(mediaResult.observations.video.height, 640);
    assert.equal(temporalResult.status, "measured");
    assert.ok(temporalResult.observations.sampling.sampledFrames >= 3);
    assert.equal(audioResult.status, "measured");
    assert.equal(audioResult.observations.channels, 1);
    assert.equal(analysis.analyzerVerdicts.every(function (item) {
      return item.providerCalls === 0;
    }), true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
