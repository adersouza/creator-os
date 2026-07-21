import test from "node:test";
import assert from "node:assert/strict";
import { deriveVisualPacingSignal, scoreAudioFit } from "../lib/audio-fit.js";

test("audio fit scores a strong rule-based match without publishing authority", function () {
  var result = scoreAudioFit({
    captionTags: ["tutorial", "growth", "practical"],
    hookTags: ["how-to", "tips"],
    hook: { tone: "educational" },
    visualSignal: { pacing: "medium", cutsPerSecond: 1.1 },
    audioCatalogItem: {
      id: "audio_01",
      tags: ["how to", "tutorial", "tips", "steady"],
      tone: "educational",
      energy: "medium",
      bpm: 112,
    },
    trendSnapshot: {
      capturedAt: "2026-05-22T10:00:00.000Z",
      velocity: "rising",
      saturation: "moderate",
    },
  }, { now: "2026-05-22T14:00:00.000Z" });

  assert.equal(result.available, true);
  assert.equal(result.advisoryOnly, true);
  assert.equal(result.publishAuthority, false);
  assert.equal(result.semanticEngine, "rule_audio_fit_v1");
  assert.equal(result.modelBacked, false);
  assert.equal(result.audioFitScore >= 75, true);
  assert.equal(result.warnings.length, 0);
  assert.equal(result.reasons.some((item) => item.code === "tag_match"), true);
  assert.equal(result.reasons.some((item) => item.code === "tone_match"), true);
  assert.equal(result.components.energyFit >= 70, true);
});

test("audio fit warns for stale and saturated trend snapshots", function () {
  var result = scoreAudioFit({
    captionTags: ["luxury", "before after"],
    hookTags: ["premium"],
    audioTags: ["luxury", "cinematic"],
    audio: { tone: "aspirational", energy: "low" },
    trendSnapshot: {
      capturedAt: "2026-05-18T12:00:00.000Z",
      velocity: "falling",
      saturation: 0.91,
    },
  }, { now: "2026-05-22T14:00:00.000Z" });

  var codes = result.warnings.map((item) => item.code);
  assert.equal(codes.includes("audio_fit_stale_trend"), true);
  assert.equal(codes.includes("audio_fit_saturated_trend"), true);
  assert.equal(result.reasons.some((item) => item.code === "trend_stale"), true);
  assert.equal(result.reasons.some((item) => item.code === "trend_saturated"), true);
  assert.equal(result.components.trendFit < 55, true);
});

test("audio fit warns on tone mismatch", function () {
  var result = scoreAudioFit({
    captionTags: ["calm", "educational"],
    hook: { tone: "calm" },
    audioCatalogItem: {
      tags: ["hype", "urgent", "fast"],
      tone: "urgent",
      energy: "high",
    },
    visual: { energy: "low" },
  });

  assert.equal(result.warnings.some((item) => item.code === "audio_fit_tone_mismatch"), true);
  assert.equal(result.reasons.some((item) => item.code === "tone_mismatch"), true);
  assert.equal(result.components.toneFit < 50, true);
  assert.equal(result.audioFitScore < 60, true);
});

test("audio fit warns when scoring metadata is missing", function () {
  var result = scoreAudioFit({
    caption: { text: "Three mistakes to avoid" },
    audioCatalogItem: { id: "audio_missing" },
  });

  assert.equal(result.warnings.some((item) => item.code === "audio_fit_missing_metadata"), true);
  assert.equal(result.reasons.some((item) => item.code === "metadata_missing"), true);
  assert.equal(result.signals.contentTags.length, 0);
  assert.equal(result.signals.audioTags.length, 0);
  assert.equal(result.audioFitScore <= 52, true);
});

test("visual pacing signal derives stable energy from existing audit metrics", function () {
  var low = deriveVisualPacingSignal({
    hookVisibility: { metrics: { avgFrameDelta: 4.4 } },
  });
  var high = deriveVisualPacingSignal({
    metrics: { cutsPerSecond: 2.1, avgFrameDelta: 18 },
  });

  assert.equal(low.available, true);
  assert.equal(low.method, "avg_frame_delta");
  assert.equal(low.pacing, "low");
  assert.equal(low.openingStatic, true);
  assert.equal(high.method, "cuts_per_second");
  assert.equal(high.pacing, "high");
  assert.equal(high.openingStatic, false);
});

test("audio fit uses derived visual pacing to separate high and low energy tracks", function () {
  var shared = {
    captionTags: ["hype", "fast"],
    audioTags: ["hype", "fast"],
    audit: { hookVisibility: { metrics: { avgFrameDelta: 20 } } },
  };
  var high = scoreAudioFit({
    ...shared,
    audio: { tags: ["hype", "fast"], energy: "high", bpm: 140 },
  });
  var low = scoreAudioFit({
    ...shared,
    audio: { tags: ["hype", "fast"], energy: "low", bpm: 72 },
  });

  assert.equal(high.components.energyFit > low.components.energyFit, true);
  assert.equal(high.audioFitScore > low.audioFitScore, true);
  assert.equal(high.signals.visualPacing.pacing, "high");
});
