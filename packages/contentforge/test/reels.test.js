import test from "node:test";
import assert from "node:assert/strict";
import { analyzeCaptions, parseSrt, parseSrtTime } from "../lib/captions.js";
import { averageHashSimilarity, bucketSimilarity, hammingDistance, temporalHashSimilarity } from "../lib/detector.js";
import { buildClipArgs, buildConvertArgs, buildEditArgs, buildFramesArgs } from "../lib/media-tools.js";
import { parsePsnr, parseSsim, parseVmafJson } from "../lib/quality-metrics.js";
import { applyOutputProfileArgs, containBlurFilterForProfile } from "../lib/reels-profiles.js";
import { deleteRun, formatManifestCsv, validateMediaInfo } from "../lib/reels.js";
import { buildImageArgs, buildPhase2Args } from "../lib/ffmpeg.js";
import { evaluateQualityGate, getVariantPreset, normalizeQualityGate, variantScoreBundle } from "../lib/variant-engine.js";

var baseMedia = {
  width: 1080,
  height: 1920,
  fps: 30,
  videoCodec: "h264",
  audioCodec: "aac",
  audioBitrate: 128000,
  formatName: "mov,mp4,m4a,3gp,3g2,mj2",
  duration: 45,
  size: 40 * 1024 * 1024,
  faststart: true,
};

test("organic reels profile passes a standard 1080x1920 H.264/AAC file", function () {
  var result = validateMediaInfo(baseMedia, "organic");
  assert.equal(result.profile.id, "organic");
  assert.equal(result.checks.every((c) => c.status !== "fail"), true);
  assert.equal(result.score, 100);
});

test("boosted reels profile fails duration above 90 seconds", function () {
  var result = validateMediaInfo({ ...baseMedia, duration: 91 }, "boosted");
  var duration = result.checks.find((c) => c.id === "duration");
  assert.equal(duration.status, "fail");
});

test("high quality reels profile warns when below 60 fps target", function () {
  var result = validateMediaInfo(baseMedia, "highQuality");
  var fps = result.checks.find((c) => c.id === "targetFps");
  assert.equal(fps.status, "warn");
});

test("profile validation catches low resolution and bad aspect ratio", function () {
  var result = validateMediaInfo({ ...baseMedia, width: 720, height: 720 }, "boosted");
  assert.equal(result.checks.find((c) => c.id === "aspect").status, "warn");
  assert.equal(result.checks.find((c) => c.id === "resolution").status, "fail");
});

test("feed and square profiles validate native Instagram aspects", function () {
  var feed = validateMediaInfo({ ...baseMedia, width: 1080, height: 1350 }, "feedPortrait");
  assert.equal(feed.profile.id, "feedPortrait");
  assert.equal(feed.checks.find((c) => c.id === "aspect").status, "pass");
  assert.equal(feed.checks.find((c) => c.id === "aspect").expected, "4:5");

  var square = validateMediaInfo({ ...baseMedia, width: 1080, height: 1080 }, "square");
  assert.equal(square.profile.id, "square");
  assert.equal(square.checks.find((c) => c.id === "aspect").status, "pass");
  assert.equal(square.checks.find((c) => c.id === "aspect").expected, "1:1");
});

test("deleteRun rejects invalid run ids", async function () {
  await assert.rejects(() => deleteRun("../bad"), /Invalid runId/);
});

test("profile args use high quality export settings", function () {
  var args = [];
  applyOutputProfileArgs(args, "highQuality", true);
  assert.equal(args.includes("-r"), true);
  assert.equal(args[args.indexOf("-r") + 1], "60");
  assert.equal(args[args.indexOf("-b:v") + 1], "32000k");
  assert.equal(args[args.indexOf("-b:a") + 1], "192k");
  assert.equal(args.includes("+faststart"), true);
});

test("media tool argument builders target expected output commands", function () {
  assert.deepEqual(buildConvertArgs("in.mov", "out.mp4", "mp4").slice(-2), ["-y", "out.mp4"]);
  assert.equal(buildConvertArgs("in.mp4", "out.gif", "gif").includes("-lavfi"), true);
  assert.match(buildConvertArgs("in.mp4", "out.gif", "gif").join(" "), /palettegen/);
  assert.equal(buildClipArgs("in.mp4", "clip.mp4", 5, 15).includes("-t"), true);
  assert.equal(buildFramesArgs("in.mp4", "frame_%03d.png", 2, 10).includes("fps=1/2"), true);
});

test("edit args compose trim scale speed and loudness filters", function () {
  var args = buildEditArgs("in.mp4", "out.mp4", {
    trimStart: 2,
    trimDuration: 10,
    speed: 1.25,
    width: 1080,
    height: 1920,
    fps: 30,
    normalizeAudio: true,
    overlayText: "Demo text",
    overlayPosition: "top",
  });
  assert.equal(args.includes("-ss"), true);
  assert.equal(args.includes("-t"), true);
  assert.equal(args[args.indexOf("-vf") + 1].includes("scale=1080:1920"), true);
  assert.equal(args[args.indexOf("-vf") + 1].includes("fps=30"), true);
  assert.equal(args[args.indexOf("-af") + 1].includes("loudnorm"), true);
});

test("edit args can swap replacement audio", function () {
  var args = buildEditArgs("in.mp4", "out.mp4", {
    speed: 1.5,
    normalizeAudio: true,
  }, "audio.wav");
  assert.equal(args.filter((item) => item === "-i").length, 2);
  assert.equal(args.includes("-map"), true);
  assert.equal(args.includes("-shortest"), true);
  assert.equal(args[args.indexOf("-af") + 1].includes("loudnorm"), true);
  assert.equal(args[args.indexOf("-af") + 1].includes("atempo"), false);
});

test("similarity bucketing respects duplicate similar unique thresholds", function () {
  assert.equal(hammingDistance("1010", "1001"), 2);
  assert.equal(bucketSimilarity(0.95, false, 0.92), "duplicate");
  assert.equal(bucketSimilarity(0.85, false, 0.92), "similar");
  assert.equal(bucketSimilarity(0.60, false, 0.92), "unique");
  assert.equal(bucketSimilarity(0.10, true, 0.92), "duplicate");
});

test("multi-frame and temporal similarity handle frame differences and shifts", function () {
  var a = ["11110000", "11001100", "10101010"];
  var b = ["11110000", "00001111", "10101010"];
  assert.equal(averageHashSimilarity(a, a), 1);
  assert.equal(averageHashSimilarity(a, b) < 1, true);
  assert.equal(temporalHashSimilarity(["0000", "1111"], ["1111", "0000"]) >= 0.5, true);
});

test("manifest CSV includes one row per analyzed variant", function () {
  var csv = formatManifestCsv({
    variantReports: [
      {
        file: "a.mp4",
        score: 88,
        qualityRetained: 91,
        differenceFromOriginal: 16,
        recommendedAction: "keep",
        checks: [{ id: "fps", status: "pass" }],
        mediaInfo: { width: 1080, height: 1920, fps: 30, duration: 12, videoCodec: "h264", bitrate: 1000 },
        qaSignals: { warnings: ["Low video bitrate"] },
      },
    ],
  });
  assert.match(csv, /"file","score"/);
  assert.match(csv, /"a\.mp4","88","91","16","keep"/);
  assert.match(csv, /"Low video bitrate"/);
});

test("quality-first video args use CRF and preserve-frame filter", function () {
  var args = buildPhase2Args("in.mp4", "out.mp4", "clean", false, true, "organic", "quality", { overlayText: "Hook" });
  assert.equal(args.includes("-crf"), true);
  assert.equal(args[args.indexOf("-crf") + 1], "13");
  assert.match(args[args.indexOf("-vf") + 1], /boxblur=24:2/);
  assert.equal(containBlurFilterForProfile("organic").includes("overlay=(W-w)/2:(H-h)/2"), true);
});

test("caption-burned video args never mirror readable text", function () {
  for (var attemptIndex of [0, 2, 5, 7]) {
    var args = buildPhase2Args("in.mp4", "out.mp4", "clean", true, true, "organic", "quality", {
      attemptIndex,
      preserveBurnedCaptions: true,
      allowHorizontalFlip: false,
    });
    assert.doesNotMatch(args.join(" "), /hflip/);
  }
});

test("caption-burned video args protect top framing", function () {
  var args = buildPhase2Args("in.mp4", "out.mp4", "clean", true, true, "organic", "quality", {
    attemptIndex: 5,
    preserveBurnedCaptions: true,
    allowHorizontalFlip: false,
  });
  assert.match(args.join(" "), /crop=iw\*0\.99[7-9][0-9]:ih\*0\.99[7-9][0-9]:iw\*0\.00[0-2][0-9]:ih\*0\.0000/);
});

test("video overlay image fallback terminates with source media", function () {
  var args = buildPhase2Args("in.mp4", "out.mp4", "clean", true, true, "organic", "quality", {
    overlayText: "Hook",
    overlayImagePath: "overlay.png",
  });
  if (args.includes("-filter_complex")) {
    assert.equal(args.includes("-loop"), true);
    assert.equal(args.includes("-shortest"), true);
    assert.match(args[args.indexOf("-filter_complex") + 1], /overlay=/);
  }
});

test("quality-first image args avoid aggressive default filters", function () {
  var args = buildImageArgs("in.png", "out.jpg", 0, { variantPreset: "quality", variantOptions: { overlayText: "Watermark" } });
  var text = args.join(" ");
  assert.match(text, /-q:v 2/);
  assert.doesNotMatch(text, /noise=/);
  assert.doesNotMatch(text, /rotate=/);
});

test("variant presets and score bundles normalize quality-first defaults", function () {
  var preset = getVariantPreset("quality");
  assert.equal(preset.preserveFrame, true);
  assert.equal(preset.videoCrf, 13);
  var scores = variantScoreBundle({
    mediaInfo: { width: 1080, height: 1920, bitrate: 12000000, duration: 5 },
    qualityMetrics: { ssim: 0.94, psnr: 34, vmaf: null },
    checks: [],
    warnings: [],
    differenceFromOriginal: 14,
  });
  assert.equal(scores.qualityRetained >= 90, true);
  assert.equal(scores.differenceFromOriginal, 14);
  assert.equal(scores.recommendedAction, "keep");
});

test("quality gate accepts good candidates and rejects weak ones", function () {
  var gate = normalizeQualityGate({});
  assert.equal(gate.enabled, true);
  assert.equal(evaluateQualityGate({
    qualityRetained: 92,
    differenceFromOriginal: 18,
    maxCrossVariantSimilarity: 0.4,
    reelsScore: 100,
    checks: [],
    warnings: [],
  }, gate).passed, true);
  var rejected = evaluateQualityGate({
    qualityRetained: 80,
    differenceFromOriginal: 4,
    maxCrossVariantSimilarity: 0.97,
    reelsScore: 90,
    checks: [{ status: "fail" }],
    warnings: ["Possible letterbox detected"],
  }, gate);
  assert.equal(rejected.passed, false);
  assert.equal(rejected.reasons.includes("cross-similarity"), true);
});

test("quality metric parsers read FFmpeg output shapes", function () {
  assert.equal(parseSsim("SSIM Y:0.9 U:0.9 V:0.9 All:0.987654 (18.0)"), 0.987654);
  assert.equal(parsePsnr("PSNR y:40 u:41 v:42 average:40.123 min:30 max:50"), 40.123);
  assert.equal(parseVmafJson(JSON.stringify({ pooled_metrics: { vmaf: { mean: 91.25 } } })), 91.25);
});

test("SRT parser and caption checks catch dense and long cues", function () {
  var srt = "1\n00:00:00,000 --> 00:00:01,000\nThis line is intentionally much longer than forty two characters\n\n2\n00:00:01,200 --> 00:00:02,000\nOne two three four five six";
  assert.equal(parseSrtTime("00:00:01,250"), 1.25);
  assert.equal(parseSrt(srt).length, 2);
  var result = analyzeCaptions(srt, { duration: 3 });
  assert.equal(result.available, true);
  assert.equal(result.checks.find((c) => c.id === "captionLineLength").status, "warn");
  assert.equal(result.checks.find((c) => c.id === "captionDensity").status, "warn");
});

test("missing captions degrade as an optional warning", function () {
  var result = analyzeCaptions("", { duration: 3 });
  assert.equal(result.available, false);
  assert.equal(result.checks[0].status, "warn");
});
