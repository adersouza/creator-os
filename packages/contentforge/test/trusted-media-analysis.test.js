import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  analyzeTrustedMedia,
  motionEvidenceFromTrustedAnalysis,
} from "../lib/trusted-media-analysis.js";
import { snapshotTrustedMediaAnalyzerRegistry } from "../lib/analyzer-registry.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");

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

async function registry(producedAt) {
  return snapshotTrustedMediaAnalyzerRegistry({ producedAt, repositoryRoot: ROOT });
}

function fixtureRunner({ withAudio = true } = {}) {
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
    if (command === "ffmpeg" && args.includes("rawvideo")) {
      var first = Buffer.alloc(90 * 160, 0);
      var second = Buffer.alloc(90 * 160, 10);
      var third = Buffer.alloc(90 * 160, 10);
      return { ok: true, stdout: Buffer.concat([first, second, third]), stderr: "", error: null };
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
    assert.match(first.analyzerRegistry.registryFingerprint, /^[a-f0-9]{64}$/);
    assert.equal(first.rawObservations.length, 4);
    assert.equal(first.analyzerVerdicts.length, 4);
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
    assert.equal(temporal.observations.sampling.sampledFrames, 3);
    assert.equal(temporal.observations.frozenFrameRatio, 0.5);
    assert.ok(temporal.observations.meanNormalizedFrameDelta > 0);
    var audio = first.rawObservations.find(function (item) {
      return item.analyzerId === "contentforge.audio_integrity";
    });
    assert.equal(audio.observations.clippingObserved, false);
    assert.equal(audio.observations.silence.totalSilenceSeconds, 0.5);
    assert.equal(audio.observations.avStreamStartOffsetMs, 40);
    assert.equal(first.unavailableMeasurements.lipSync, "requires_dedicated_lip_sync_analyzer");
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
  });
});

test("adapts observations and human review without inventing lip sync", async function () {
  await withFixture(async function ({ media }) {
    var analysis = await analyzeTrustedMedia({
      mediaPath: media,
      producedAt: "2026-07-22T20:00:00Z",
      analyzerRegistry: await registry("2026-07-22T20:00:00Z"),
      repositoryRoot: ROOT,
      runner: fixtureRunner(),
    });
    var withoutReview = motionEvidenceFromTrustedAnalysis(analysis);
    assert.equal(withoutReview.identity.available, false);
    assert.equal(withoutReview.anatomy.available, false);
    assert.equal(withoutReview.lipSync.available, false);
    var review = {
      schema: "reel_factory.human_media_review.v1",
      reviewId: "review-1",
      rubricVersion: "1.0.0",
      subjectSha256: analysis.subject.mediaSha256,
      decisions: { creatorIdentityPreserved: true },
      ratings: {
        creatorIdentitySimilarity: 0.91,
        faceArtifactScore: 0.05,
        handsVisible: false,
        handArtifactScore: null,
        bodyArtifactScore: 0.07,
        loopAcceptable: true,
      },
    };
    review.reviewFingerprint = fingerprint(review);
    var withReview = motionEvidenceFromTrustedAnalysis(analysis, { humanReview: review });
    assert.equal(withReview.identity.matched, true);
    assert.equal(withReview.identity.similarityScore, 0.91);
    assert.deepEqual(withReview.anatomy.hands, {
      applicable: false,
      reason: "hands_not_visible_in_reviewed_media",
    });
    assert.equal(withReview.lipSync.available, false);
    assert.equal(withReview.audioAlignment.offsetMs, 40);
  });
});

test("fails closed on registry implementation drift and analysis tampering", async function () {
  await withFixture(async function ({ media }) {
    var exactRegistry = await registry("2026-07-22T20:00:00Z");
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
