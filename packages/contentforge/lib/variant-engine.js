var VARIANT_PRESETS = {
  quality: {
    id: "quality",
    label: "Quality First",
    level: "clean",
    qualityTarget: 94,
    differenceTarget: 18,
    crop: 0.988,
    colorShift: 0.012,
    speedShift: 0.008,
    sharpen: false,
    denoise: false,
    preserveFrame: true,
    videoCrf: 13,
    imageQuality: [2, 2],
  },
  light: {
    id: "light",
    label: "Light",
    level: "light",
    qualityTarget: 93,
    differenceTarget: 28,
    crop: 0.985,
    colorShift: 0.012,
    speedShift: 0.008,
    sharpen: false,
    denoise: false,
    preserveFrame: true,
    videoCrf: 14,
    imageQuality: [2, 3],
  },
  medium: {
    id: "medium",
    label: "Medium",
    level: "medium",
    qualityTarget: 88,
    differenceTarget: 45,
    crop: 0.97,
    colorShift: 0.025,
    speedShift: 0.02,
    sharpen: true,
    denoise: false,
    preserveFrame: true,
    videoCrf: 16,
    imageQuality: [2, 3],
  },
  strong: {
    id: "strong",
    label: "Strong",
    level: "heavy",
    qualityTarget: 82,
    differenceTarget: 65,
    crop: 0.945,
    colorShift: 0.055,
    speedShift: 0.05,
    sharpen: true,
    denoise: false,
    preserveFrame: false,
    videoCrf: 18,
    imageQuality: [2, 4],
  },
  custom: {
    id: "custom",
    label: "Custom",
    level: "medium",
    qualityTarget: 88,
    differenceTarget: 45,
    crop: 0.98,
    colorShift: 0.02,
    speedShift: 0.015,
    sharpen: false,
    denoise: false,
    preserveFrame: true,
    videoCrf: 15,
    imageQuality: [2, 3],
  },
};

var DEFAULT_QUALITY_GATE = {
  enabled: true,
  minQuality: 88,
  minDifference: 15,
  maxCrossSimilarity: 0.92,
  maxAttempts: 4,
};

var LEGACY_LEVEL_TO_PRESET = {
  clean: "quality",
  light: "light",
  medium: "medium",
  heavy: "strong",
  stealth: "medium",
};

export function normalizeVariantPreset(value, fallbackLevel) {
  if (VARIANT_PRESETS[value]) return value;
  if (LEGACY_LEVEL_TO_PRESET[fallbackLevel]) return LEGACY_LEVEL_TO_PRESET[fallbackLevel];
  return "quality";
}

export function getVariantPreset(presetId, options = {}, fallbackLevel) {
  var id = normalizeVariantPreset(presetId, fallbackLevel);
  var base = VARIANT_PRESETS[id] || VARIANT_PRESETS.quality;
  var cropPct = clampNumber(options.cropAmount, 0, 10, null);
  var colorPct = clampNumber(options.colorShiftAmount, 0, 10, null);
  var speedPct = clampNumber(options.speedShiftAmount, 0, 10, null);
  return {
    ...base,
    crop: cropPct === null ? base.crop : 1 - (cropPct / 100),
    colorShift: colorPct === null ? base.colorShift : colorPct / 100,
    speedShift: speedPct === null ? base.speedShift : speedPct / 100,
    sharpen: options.sharpen === undefined ? base.sharpen : !!options.sharpen,
    denoise: options.denoise === undefined ? base.denoise : !!options.denoise,
    preserveFrame: options.preserveFrame === undefined ? base.preserveFrame : !!options.preserveFrame,
    outputFormat: options.outputFormat || "jpg",
    batchCount: clampNumber(options.batchCount, 1, 500, null),
    attemptIndex: clampNumber(options.attemptIndex, 0, 999, 0),
  };
}

function clampNumber(value, min, max, fallback) {
  var parsed = parseFloat(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

export function normalizeQualityGate(value = {}) {
  var raw = value && typeof value === "object" ? value : {};
  return {
    enabled: raw.enabled === undefined ? DEFAULT_QUALITY_GATE.enabled : !!raw.enabled,
    minQuality: clampNumber(raw.minQuality, 0, 100, DEFAULT_QUALITY_GATE.minQuality),
    minDifference: clampNumber(raw.minDifference, 0, 100, DEFAULT_QUALITY_GATE.minDifference),
    maxCrossSimilarity: clampNumber(raw.maxCrossSimilarity, 0.5, 1, DEFAULT_QUALITY_GATE.maxCrossSimilarity),
    maxAttempts: Math.round(clampNumber(raw.maxAttempts, 1, 12, DEFAULT_QUALITY_GATE.maxAttempts)),
    allowLowVisualDifference: raw.allowLowVisualDifference === true,
    allowHighCrossSimilarity: raw.allowHighCrossSimilarity === true,
  };
}

export function evaluateQualityGate(candidate, gate = DEFAULT_QUALITY_GATE) {
  var reasons = [];
  var checks = candidate.checks || [];
  var warnings = candidate.warnings || [];
  if ((candidate.qualityRetained || 0) < gate.minQuality) reasons.push("quality");
  if (!gate.allowLowVisualDifference && (candidate.differenceFromOriginal || 0) < gate.minDifference) reasons.push("difference");
  if (!gate.allowHighCrossSimilarity && (candidate.maxCrossVariantSimilarity || 0) >= gate.maxCrossSimilarity) reasons.push("cross-similarity");
  if ((candidate.reelsScore || 0) < 95) reasons.push("reels-score");
  if (checks.some(function (check) { return check.status === "fail"; })) reasons.push("technical-fail");
  if (warnings.some(function (warning) { return /black|silence|letterbox/i.test(warning); })) reasons.push("qa-warning");
  return {
    passed: !gate.enabled || reasons.length === 0,
    reasons,
  };
}

function scoreQuality({ mediaInfo = {}, qualityMetrics = {}, checks = [], warnings = [] } = {}) {
  var score = 100;
  if (qualityMetrics.vmaf !== null && qualityMetrics.vmaf !== undefined && qualityMetrics.vmaf > 1) {
    if (qualityMetrics.vmaf < 70) score -= 20;
    else if (qualityMetrics.vmaf < 82) score -= 10;
    else if (qualityMetrics.vmaf < 90) score -= 4;
  }
  if (qualityMetrics.ssim !== null && qualityMetrics.ssim !== undefined) {
    if (qualityMetrics.ssim < 0.75) score -= 8;
    else if (qualityMetrics.ssim < 0.84) score -= 6;
    else if (qualityMetrics.ssim < 0.9) score -= 5;
  }
  if (qualityMetrics.psnr !== null && qualityMetrics.psnr !== undefined) {
    if (qualityMetrics.psnr < 18) score -= 4;
    else if (qualityMetrics.psnr < 24) score -= 2;
  }
  if (mediaInfo.width && mediaInfo.height && mediaInfo.width < 1080 && mediaInfo.height < 1920) score -= 8;
  if (mediaInfo.bitrate && mediaInfo.duration && mediaInfo.bitrate < 4000000) score -= 6;
  score -= checks.filter(function (item) { return item.status === "fail"; }).length * 10;
  score -= checks.filter(function (item) { return item.status === "warn"; }).length * 3;
  score -= warnings.length * 4;
  return Math.round(Math.max(0, Math.min(100, score)));
}

function scoreDifference({ sourceSimilarity = 1, exactMatch = false, signals = {} } = {}) {
  var score = exactMatch ? 0 : (1 - Math.max(0, Math.min(1, sourceSimilarity))) * 100;
  if (signals.audioDifferent) score += 5;
  if (signals.temporalDifferent) score += 8;
  if (signals.metadataChanged) score += 4;
  return Math.round(Math.max(0, Math.min(100, score)));
}

function recommendedAction(qualityRetained, differenceFromOriginal) {
  if (qualityRetained < 75) return "reject";
  if (qualityRetained < 86 || differenceFromOriginal < 8) return "review";
  return "keep";
}

export function variantScoreBundle(input = {}) {
  var qualityRetained = scoreQuality(input);
  var differenceFromOriginal = input.differenceFromOriginal !== undefined && input.differenceFromOriginal !== null
    ? Math.round(Math.max(0, Math.min(100, input.differenceFromOriginal)))
    : scoreDifference(input);
  return {
    qualityRetained,
    differenceFromOriginal,
    qualitySignals: input.qualitySignals || [],
    differenceSignals: input.differenceSignals || [],
    recommendedAction: recommendedAction(qualityRetained, differenceFromOriginal),
  };
}
