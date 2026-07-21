const DEFAULT_STALE_HOURS = 72;
const DEFAULT_SATURATION_WARN = 0.78;

const TONE_GROUPS = {
  educational: ["educational", "how to", "tutorial", "explainer", "tips", "practical", "informative"],
  aspirational: ["aspirational", "luxury", "premium", "cinematic", "inspiring", "uplifting"],
  urgent: ["urgent", "dramatic", "high intensity", "fast", "hype", "breaking"],
  playful: ["playful", "funny", "humor", "quirky", "casual", "meme"],
  calm: ["calm", "soft", "ambient", "relaxed", "minimal", "soothing"],
};

const TAG_ALIASES = new Map([
  ["howto", "how to"],
  ["how-to", "how to"],
  ["tutorials", "tutorial"],
  ["explainers", "explainer"],
  ["premium", "luxury"],
  ["upbeat", "uplifting"],
  ["motivational", "inspiring"],
  ["comedy", "funny"],
  ["humorous", "funny"],
  ["viral", "trend"],
  ["trending", "trend"],
]);

function warning(code, label, message, severity = "warn") {
  return { code, label, message, severity };
}

function reason(code, label, impact, detail) {
  return { code, label, impact, detail };
}

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function normalizeTag(value) {
  var normalized = String(value || "")
    .toLowerCase()
    .replace(/[_/]+/g, " ")
    .replace(/[^a-z0-9\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return TAG_ALIASES.get(normalized) || normalized;
}

function tagsFrom(value) {
  if (!value) return [];
  var raw = Array.isArray(value) ? value : String(value).split(/[,\n|]/g);
  var tags = raw.map(normalizeTag).filter(Boolean);
  return Array.from(new Set(tags));
}

function collectTags(...values) {
  return Array.from(new Set(values.flatMap(tagsFrom)));
}

function detectTone(inputTone, tags) {
  var explicit = normalizeTag(inputTone);
  if (explicit) {
    var explicitGroup = toneGroupFor(explicit);
    return explicitGroup || explicit;
  }
  for (var tag of tags) {
    var group = toneGroupFor(tag);
    if (group) return group;
  }
  return null;
}

function toneGroupFor(value) {
  var normalized = normalizeTag(value);
  for (var [group, names] of Object.entries(TONE_GROUPS)) {
    if (group === normalized || names.includes(normalized)) return group;
  }
  return null;
}

function toneCompatible(contentTone, audioTone) {
  if (!contentTone || !audioTone) return null;
  if (contentTone === audioTone) return true;
  var compatible = new Set([
    "educational:calm",
    "calm:educational",
    "aspirational:calm",
    "calm:aspirational",
    "urgent:aspirational",
    "aspirational:urgent",
    "playful:urgent",
    "urgent:playful",
  ]);
  return compatible.has(contentTone + ":" + audioTone);
}

function scoreTagAffinity(contentTags, audioTags) {
  if (!contentTags.length || !audioTags.length) return null;
  var audioSet = new Set(audioTags);
  var directMatches = contentTags.filter(function (tag) { return audioSet.has(tag); });
  var groupMatches = contentTags.filter(function (tag) {
    var group = toneGroupFor(tag);
    return group && audioTags.some(function (audioTag) { return toneGroupFor(audioTag) === group; });
  });
  var matchCount = new Set([...directMatches, ...groupMatches]).size;
  var coverage = matchCount / Math.max(1, Math.min(contentTags.length, 6));
  return clamp(35 + (coverage * 65));
}

function numericEnergy(value) {
  if (Number.isFinite(value)) return clamp(value, 0, 1);
  var normalized = normalizeTag(value);
  if (["low", "slow", "calm", "soft", "minimal"].includes(normalized)) return 0.25;
  if (["medium", "balanced", "steady"].includes(normalized)) return 0.55;
  if (["high", "fast", "hype", "urgent", "energetic"].includes(normalized)) return 0.85;
  return null;
}

function energyFromBpm(bpm) {
  if (!Number.isFinite(bpm) || bpm <= 0) return null;
  if (bpm < 85) return 0.25;
  if (bpm < 125) return 0.55;
  return 0.85;
}

function scoreEnergyFit(visual, audio) {
  var visualEnergy = numericEnergy(visual?.energy ?? visual?.visualEnergy ?? visual?.pacing);
  var cutsPerSecond = visual?.cutsPerSecond ?? visual?.cutRate ?? visual?.avgFrameDelta;
  if (visualEnergy === null && Number.isFinite(cutsPerSecond)) {
    visualEnergy = clamp(cutsPerSecond / 2.5, 0, 1);
  }
  var audioEnergy = numericEnergy(audio?.energy ?? audio?.pacing) ?? energyFromBpm(audio?.bpm);
  if (visualEnergy === null || audioEnergy === null) return null;
  var distance = Math.abs(visualEnergy - audioEnergy);
  return clamp(100 - (distance * 100));
}

function finiteNumber(...values) {
  for (var value of values) {
    var numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric;
  }
  return null;
}

function pacingLabel(energy) {
  if (!Number.isFinite(energy)) return null;
  if (energy < 0.35) return "low";
  if (energy < 0.68) return "medium";
  return "high";
}

export function deriveVisualPacingSignal(source = {}) {
  var directEnergy = numericEnergy(source?.energy ?? source?.visualEnergy ?? source?.pacing);
  var metrics = source?.hookVisibility?.metrics
    || source?.openingStrength?.metrics
    || source?.openingStrength
    || source?.metrics
    || source?.visual
    || {};
  var cutsPerSecond = finiteNumber(
    source?.cutsPerSecond,
    source?.cutRate,
    metrics?.cutsPerSecond,
    metrics?.cutRate
  );
  var avgFrameDelta = finiteNumber(
    source?.avgFrameDelta,
    source?.frameDelta,
    metrics?.avgFrameDelta,
    metrics?.frameDelta
  );
  var motionScore = finiteNumber(
    source?.motionScore,
    source?.motion,
    metrics?.motionScore,
    metrics?.motion
  );
  var vmafMotion = finiteNumber(
    source?.vmafmotion,
    source?.vmafMotion,
    metrics?.vmafmotion,
    metrics?.vmafMotion
  );

  var derivedEnergy = directEnergy;
  var method = directEnergy === null ? null : "explicit";
  if (derivedEnergy === null && cutsPerSecond !== null) {
    derivedEnergy = clamp(cutsPerSecond / 2.5, 0, 1);
    method = "cuts_per_second";
  }
  if (derivedEnergy === null && avgFrameDelta !== null) {
    derivedEnergy = clamp(avgFrameDelta / 22, 0, 1);
    method = "avg_frame_delta";
  }
  if (derivedEnergy === null && motionScore !== null) {
    derivedEnergy = clamp(motionScore > 1 ? motionScore / 100 : motionScore, 0, 1);
    method = "motion_score";
  }
  if (derivedEnergy === null && vmafMotion !== null) {
    derivedEnergy = clamp(vmafMotion / 18, 0, 1);
    method = "vmafmotion";
  }

  if (derivedEnergy === null && cutsPerSecond === null && avgFrameDelta === null && motionScore === null && vmafMotion === null) {
    return {};
  }

  return {
    available: true,
    method: method || "visual_metrics",
    energy: derivedEnergy === null ? null : Number(derivedEnergy.toFixed(3)),
    pacing: pacingLabel(derivedEnergy),
    cutsPerSecond,
    avgFrameDelta,
    motionScore,
    vmafMotion,
    openingStatic: (derivedEnergy !== null && derivedEnergy < 0.28) || (avgFrameDelta !== null && avgFrameDelta < 6),
  };
}

function trendAgeHours(snapshot, now) {
  if (Number.isFinite(snapshot?.freshnessHours)) return snapshot.freshnessHours;
  var stamp = snapshot?.capturedAt || snapshot?.updatedAt || snapshot?.observedAt || snapshot?.createdAt;
  if (!stamp) return null;
  var time = new Date(stamp).getTime();
  if (!Number.isFinite(time)) return null;
  return Math.max(0, (now.getTime() - time) / 36e5);
}

function velocityScore(value) {
  if (Number.isFinite(value)) return clamp(50 + (value * 50));
  var normalized = normalizeTag(value);
  if (["surging", "rising", "accelerating", "up"].includes(normalized)) return 92;
  if (["steady", "flat", "stable"].includes(normalized)) return 65;
  if (["falling", "declining", "down", "spent"].includes(normalized)) return 32;
  return null;
}

function saturationValue(value) {
  if (Number.isFinite(value)) return value > 1 ? value / 100 : value;
  var normalized = normalizeTag(value);
  if (["low", "fresh", "niche"].includes(normalized)) return 0.25;
  if (["medium", "moderate"].includes(normalized)) return 0.55;
  if (["high", "saturated", "overused"].includes(normalized)) return 0.9;
  return null;
}

function scoreTrend(snapshot, now, options, warnings, reasons) {
  if (!snapshot) return null;
  var ageHours = trendAgeHours(snapshot, now);
  var velocity = velocityScore(snapshot.velocity ?? snapshot.velocityScore);
  var saturation = saturationValue(snapshot.saturation ?? snapshot.saturationScore);
  var score = 55;
  if (ageHours !== null) score += clamp(30 - (ageHours / 4), -25, 30);
  if (velocity !== null) score += (velocity - 50) * 0.35;
  if (saturation !== null) score -= saturation * 28;

  if (ageHours !== null && ageHours > (options.staleHours ?? DEFAULT_STALE_HOURS)) {
    warnings.push(warning("audio_fit_stale_trend", "Trend snapshot is stale", "Audio trend data is older than the configured freshness window"));
    reasons.push(reason("trend_stale", "Stale trend snapshot", -14, Math.round(ageHours) + " hours old"));
  }
  if (saturation !== null && saturation >= (options.saturationWarnAt ?? DEFAULT_SATURATION_WARN)) {
    warnings.push(warning("audio_fit_saturated_trend", "Audio trend may be saturated", "Trend saturation suggests the sound may already be overused"));
    reasons.push(reason("trend_saturated", "High trend saturation", -12, Math.round(saturation * 100) + "% saturation"));
  }
  return clamp(score);
}

function uniqueByCode(items) {
  var seen = new Set();
  return items.filter(function (item) {
    if (seen.has(item.code)) return false;
    seen.add(item.code);
    return true;
  });
}

export function scoreAudioFit(input = {}, options = {}) {
  var now = options.now ? new Date(options.now) : new Date();
  var caption = input.caption || input.captionMetadata || {};
  var hook = input.hook || input.hookMetadata || {};
  var audio = input.audio || input.audioCatalogItem || input.audioCatalog || {};
  var visual = deriveVisualPacingSignal(input.visual || input.visualSignal || input.visualPacing || input.advisory || input.creativeAudit || input.qualityAudit || input.audit || {});
  var trendSnapshot = input.trendSnapshot || input.trend || audio.trendSnapshot || null;
  var warnings = [];
  var reasons = [];

  var contentTags = collectTags(input.captionTags, input.hookTags, caption.tags, hook.tags);
  var audioTags = collectTags(input.audioTags, audio.tags, audio.genres, audio.moods);
  var contentTone = detectTone(input.tone || caption.tone || hook.tone, contentTags);
  var audioTone = detectTone(audio.tone || audio.mood, audioTags);

  var missing = [];
  if (!contentTags.length && !contentTone) missing.push("caption/hook tags");
  if (!audioTags.length && !audioTone) missing.push("audio catalog tags");
  if (missing.length) {
    warnings.push(warning("audio_fit_missing_metadata", "Audio-fit metadata is incomplete", "Missing " + missing.join(" and ") + " for rule-based scoring"));
    reasons.push(reason("metadata_missing", "Missing metadata", -16, missing.join(", ")));
  }

  var tagAffinity = scoreTagAffinity(contentTags, audioTags);
  if (tagAffinity !== null) {
    var matches = contentTags.filter(function (tag) { return audioTags.includes(tag); });
    reasons.push(reason(
      matches.length ? "tag_match" : "tag_overlap_weak",
      matches.length ? "Caption/hook tags match audio tags" : "Caption/hook tags have limited audio overlap",
      matches.length ? 18 : -8,
      matches.length ? matches.join(", ") : "No direct tag match"
    ));
  }

  var toneFit = 60;
  var toneState = toneCompatible(contentTone, audioTone);
  if (toneState === true) {
    toneFit = contentTone === audioTone ? 96 : 82;
    reasons.push(reason("tone_match", "Tone is compatible", 16, [contentTone, audioTone].filter(Boolean).join(" to ")));
  } else if (toneState === false) {
    toneFit = 30;
    warnings.push(warning("audio_fit_tone_mismatch", "Audio tone may not fit", "Audio tone does not match the caption or hook tone"));
    reasons.push(reason("tone_mismatch", "Tone mismatch", -20, [contentTone, audioTone].filter(Boolean).join(" vs ")));
  }

  var energyFit = scoreEnergyFit(visual, audio);
  if (energyFit !== null) {
    reasons.push(reason(
      energyFit >= 70 ? "energy_fit" : "energy_gap",
      energyFit >= 70 ? "Audio energy fits visual pacing" : "Audio energy may not fit visual pacing",
      energyFit >= 70 ? 10 : -8,
      "energy score " + Math.round(energyFit)
    ));
  }

  var trendFit = scoreTrend(trendSnapshot, now, options, warnings, reasons);
  if (trendFit !== null && trendFit >= 72) {
    reasons.push(reason("trend_fit", "Trend signal is fresh enough", 10, "trend score " + Math.round(trendFit)));
  }

  var weighted = [
    { value: tagAffinity, weight: 0.42 },
    { value: toneFit, weight: 0.22 },
    { value: energyFit, weight: 0.16 },
    { value: trendFit, weight: 0.20 },
  ].filter(function (item) { return Number.isFinite(item.value); });

  var audioFitScore = weighted.length
    ? Math.round(weighted.reduce(function (sum, item) { return sum + (item.value * item.weight); }, 0) / weighted.reduce(function (sum, item) { return sum + item.weight; }, 0))
    : 35;

  if (missing.length) audioFitScore -= 8;
  audioFitScore = clamp(audioFitScore);

  return {
    available: true,
    advisoryOnly: true,
    publishAuthority: false,
    semanticEngine: "rule_audio_fit_v1",
    modelBacked: false,
    audioFitScore,
    reasons: uniqueByCode(reasons),
    warnings: uniqueByCode(warnings),
    components: {
      tagAffinity: tagAffinity === null ? null : Math.round(tagAffinity),
      toneFit: Math.round(toneFit),
      energyFit: energyFit === null ? null : Math.round(energyFit),
      trendFit: trendFit === null ? null : Math.round(trendFit),
    },
    signals: {
      contentTags,
      audioTags,
      contentTone,
      audioTone,
      visualPacing: visual,
      trendSnapshotAgeHours: trendAgeHours(trendSnapshot, now),
    },
  };
}
