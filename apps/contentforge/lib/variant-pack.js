import path from "path";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "fs";
import { runPipeline } from "./pipeline.js";
import { resolveUploadPath, resolveRunFinalDir, clientUploadPath } from "./paths.js";
import { averageHashSimilarity, multiFrameHash, temporalHashSimilarity } from "./detector.js";
import { getFastQualityMetrics } from "./quality-metrics.js";
import { getQaSignals, probeMedia, validateMediaInfo } from "./reels.js";
import { variantScoreBundle } from "./variant-engine.js";

var PACK_PRESETS = {
  caption_safe: {
    variantPreset: "quality",
    label: "Caption Safe",
    minVariation: 6,
    recipes: ["micro crop", "mild timing shift", "mild color balance", "caption readability preserved"],
    qualityGate: {
      enabled: true,
      minQuality: 90,
      minDifference: 5,
      maxCrossSimilarity: 0.98,
      maxAttempts: 6,
    },
    variantOptions: {
      preserveBurnedCaptions: true,
      allowHorizontalFlip: false,
      allowStrongColorShift: false,
      cropAmount: 1.0,
      colorShiftAmount: 0.8,
      speedShiftAmount: 0.6,
      preserveFrame: true,
      sharpen: false,
    },
  },
  caption_safe_v2: {
    variantPreset: "quality",
    label: "Caption Safe v2",
    schema: "contentforge.variant_pack.v2",
    minVariation: 20,
    minOperationDiversity: 25,
    minQuality: 90,
    minReadability: 95,
    minFocalSafety: 95,
    recipes: [
      "cover frame family",
      "timing trim family",
      "caption lane timing family",
      "crop zoom family",
      "color profile family",
      "audio offset family",
    ],
    familySequence: ["cover_frame", "timing_trim", "caption_lane_timing", "crop_zoom_family", "color_profile", "audio_offset"],
    qualityGate: {
      enabled: true,
      minQuality: 90,
      minDifference: 20,
      maxCrossSimilarity: 0.99,
      maxAttempts: 8,
      allowLowVisualDifference: true,
      allowHighCrossSimilarity: true,
    },
    variantOptions: {
      preserveBurnedCaptions: true,
      preserveColor: true,
      preserveAudio: true,
      preserveTiming: false,
      preserveGeometry: true,
      preserveFrameRate: false,
      allowHorizontalFlip: false,
      allowStrongColorShift: false,
      cropAmount: 0,
      colorShiftAmount: 0,
      speedShiftAmount: 0,
      preserveFrame: true,
      sharpen: false,
    },
  },
  strong_safe: {
    variantPreset: "quality",
    label: "Strong Safe",
    schema: "contentforge.variant_pack.v2",
    minVariation: 20,
    minOperationDiversity: 25,
    minQuality: 90,
    minReadability: 95,
    minFocalSafety: 95,
    recipes: [
      "strong cover frame family",
      "timing trim family",
      "caption lane timing family",
      "crop zoom family",
      "color profile family",
      "audio offset family",
    ],
    familySequence: ["cover_frame", "timing_trim", "caption_lane_timing", "crop_zoom_family", "color_profile", "audio_offset"],
    qualityGate: {
      enabled: true,
      minQuality: 90,
      minDifference: 20,
      maxCrossSimilarity: 0.985,
      maxAttempts: 8,
      allowLowVisualDifference: true,
      allowHighCrossSimilarity: true,
    },
    variantOptions: {
      preserveBurnedCaptions: true,
      preserveColor: true,
      preserveAudio: true,
      preserveTiming: false,
      preserveGeometry: true,
      preserveFrameRate: false,
      allowHorizontalFlip: false,
      allowStrongColorShift: false,
      cropAmount: 0,
      colorShiftAmount: 0,
      speedShiftAmount: 0,
      preserveFrame: true,
      sharpen: false,
    },
  },
  subtle: {
    variantPreset: "quality",
    label: "Subtle",
    minVariation: 8,
    recipes: ["small crop", "light color shift", "safe caption placement"],
  },
  balanced: {
    variantPreset: "medium",
    label: "Balanced",
    minVariation: 15,
    recipes: ["crop/zoom", "timing shift", "color shift", "caption swaps"],
  },
  strong: {
    variantPreset: "strong",
    label: "Strong",
    minVariation: 28,
    recipes: ["strong crop/zoom", "timing changes", "alternate covers", "caption structure changes"],
  },
};

var VIDEO_EXTS = new Set([".mp4", ".mov", ".webm"]);

export function normalizeVariantPackRequest(input = {}) {
  var source = input.source || input.inputFile;
  var safeSource = clientUploadPath(source);
  var preset = PACK_PRESETS[input.variationPreset] ? input.variationPreset : "balanced";
  var count = Math.max(1, Math.min(30, parseInt(input.variantCount || input.count || 8, 10) || 8));
  var captionMode = ["none", "keep_original", "generated_hooks", "supplied_hooks"].includes(input.captionMode)
    ? input.captionMode
    : "none";
  var suppliedHooks = Array.isArray(input.suppliedHooks)
    ? input.suppliedHooks.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  var preserveBurnedCaptions = !!(input.preserveBurnedCaptions || input.captionBurned || preset === "caption_safe" || preset === "caption_safe_v2" || preset === "strong_safe");
  return {
    source: safeSource,
    variantCount: count,
    variationPreset: preset,
    captionMode,
    suppliedHooks,
    recipeSet: Array.isArray(input.recipeSet) ? input.recipeSet.filter(Boolean) : [],
    preserveBurnedCaptions,
  };
}

export function planVariantFamilyRecipes(request = {}) {
  var preset = PACK_PRESETS[request.variationPreset] || PACK_PRESETS.balanced;
  var count = Math.max(1, Math.min(30, parseInt(request.variantCount || 8, 10) || 8));
  var sequence = preset.familySequence || ["generic_variant"];
  var recipes = [];
  for (var index = 0; index < count; index++) {
    var familyName = sequence[index % sequence.length];
    var round = Math.floor(index / sequence.length);
    recipes.push(buildFamilyRecipe({
      presetId: request.variationPreset || "balanced",
      familyName,
      variantIndex: index + 1,
      round,
    }));
  }
  return recipes;
}

function buildFamilyRecipe({ presetId, familyName, variantIndex, round }) {
  var profiles = {
    cover_frame: ["early_hook", "mid_expression", "late_pose"],
    timing_trim: ["trim_head_0_10s", "trim_tail_0_15s", "trim_head_tail_0_08s"],
    caption_lane_timing: ["top_safe", "center_safe", "bottom_safe"],
    crop_zoom_family: ["centered_1_03x", "face_safe_1_05x", "upper_body_1_07x", "slight_left_1_04x", "slight_right_1_04x"],
    color_profile: ["metadata_srgb", "metadata_display_p3", "metadata_rec709"],
    audio_offset: ["offset_plus_0_30s", "offset_plus_0_50s", "offset_plus_0_80s"],
    generic_variant: ["generic_safe"],
  };
  var profileList = profiles[familyName] || profiles.generic_variant;
  var profile = profileList[round % profileList.length];
  var operationSignals = operationSignalsForFamily(familyName);
  return {
    variantIndex,
    operationSet: presetId,
    familyName,
    variantFamilyRecipe: {
      preset: presetId,
      familyName,
      profile,
      temporalConsistency: "whole_clip",
    },
    operationSetSummary: profile,
    operationSignals,
    blockedOperations: ["horizontal_flip", "heavy_color_shift", "artificial_degradation", "caption_text_change", "face_risk_crop"],
  };
}

function operationSignalsForFamily(familyName) {
  return {
    coverFrameDifferent: familyName === "cover_frame",
    temporalDifferent: familyName === "timing_trim",
    captionLaneDifferent: familyName === "caption_lane_timing",
    cropFamilyDifferent: familyName === "crop_zoom_family",
    colorProfileDifferent: familyName === "color_profile",
    audioOffsetDifferent: familyName === "audio_offset",
    containerMetadataDifferent: familyName === "container_metadata",
    encoderSignatureDifferent: familyName === "encoder_signature",
    handoffManifestDifferent: familyName === "handoff_manifest",
    metadataChanged: true,
    horizontalFlip: false,
    heavyColorShift: false,
    artificialDegradation: false,
    captionTextChanged: false,
    faceRiskCrop: false,
  };
}

export async function runVariantPack(input, sendEvent) {
  var request = normalizeVariantPackRequest(input);
  var sourcePath = resolveUploadPath(request.source);
  if (!sourcePath || !existsSync(sourcePath)) {
    throw new Error("Source upload not found");
  }
  var preset = PACK_PRESETS[request.variationPreset];
  var events = [];
  var complete = null;
  var pipelineConfig = {
    inputFile: request.source,
    numEdits: request.variantCount,
    spinsPerEdit: 1,
    variantPreset: preset.variantPreset,
    qualityGate: preset.qualityGate || { enabled: false },
    vertical: true,
    outputProfile: "organic",
    variantOptions: variantOptionsForCaptions(request),
  };
  await runPipeline(pipelineConfig, function (event) {
    events.push(event);
    if (event.type === "complete") complete = event;
    if (sendEvent) sendEvent(event);
  });
  if (!complete?.runId) {
    throw new Error("Variant pack run did not complete");
  }
  var report = await buildVariantPackReport({
    runId: complete.runId,
    sourcePath,
    request,
    complete,
    events,
  });
  writeFileSync(path.join(report.outputDir, "variant_pack.json"), JSON.stringify(report, null, 2));
  return report;
}

export async function loadVariantPack(runId) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir) throw new Error("Invalid runId");
  var reportPath = path.join(finalDir, "variant_pack.json");
  if (!existsSync(reportPath)) throw new Error("Variant pack report not found");
  return JSON.parse(readFileSync(reportPath, "utf8"));
}

export async function buildVariantPackReport({ runId, sourcePath, request, complete, events = [] }) {
  var outputDir = resolveRunFinalDir(runId);
  if (!outputDir) throw new Error("Invalid run output directory");
  var sourceHashes = await multiFrameHash(sourcePath, true);
  var previous = [];
  var plannedRecipes = planVariantFamilyRecipes(request);
  var files = readdirSync(outputDir)
    .filter((name) => VIDEO_EXTS.has(path.extname(name).toLowerCase()))
    .sort();
  var results = [];
  for (var index = 0; index < files.length; index++) {
    var filename = files[index];
    var filePath = path.join(outputDir, filename);
    var result = await scoreVariant({
      filePath,
      filename,
      sourcePath,
      sourceHashes,
      previous,
      preset: request.variationPreset,
      caption: captionForIndex(request, index),
      familyRecipe: plannedRecipes[index] || null,
    });
    previous.push({ frameHashes: result._frameHashes });
    delete result._frameHashes;
    results.push(result);
  }
  results.sort(function (a, b) {
    return (Number(b.recommended) - Number(a.recommended)) ||
      (b.variationScore - a.variationScore) ||
      (b.creativeQualityScore - a.creativeQualityScore);
  });
  return {
    schema: schemaForPreset(request.variationPreset),
    runId,
    source: path.basename(sourcePath),
    sourcePath,
    outputDir,
    manifestPath: path.join(outputDir, "variant_pack.json"),
    manifestUrl: "/api/variant-pack/" + encodeURIComponent(runId) + "/manifest",
    createdAt: new Date().toISOString(),
    request,
    variationPreset: request.variationPreset,
    recipeList: presetRecipeList(request),
    plannedFamilies: plannedRecipes,
    complete: {
      total: complete.total || results.length,
      attempted: complete.attempted || 0,
      failed: complete.failed || 0,
      elapsed: complete.elapsed,
      variantPreset: complete.variantPreset,
      attemptedCandidates: complete.attemptedCandidates || 0,
      keptCandidates: complete.keptCandidates || results.length,
      rejectedCandidates: complete.rejectedCandidates || 0,
      rejectionReasons: complete.rejectionReasons || {},
      rejectionSamples: complete.rejectionSamples || [],
    },
    operatorSummary: summarizeResults(results),
    results,
    events: events.filter((event) => ["phase", "error", "complete"].includes(event.type)),
  };
}

async function scoreVariant({ filePath, filename, sourcePath, sourceHashes, previous, preset, caption, familyRecipe = null }) {
  var mediaInfo = await probeMedia(filePath);
  var validation = validateMediaInfo(mediaInfo, "organic");
  var qa = await getQaSignals(filePath, mediaInfo);
  var metrics = await getFastQualityMetrics({ sourcePath, variantPath: filePath, mediaInfo });
  var hashes = await multiFrameHash(filePath, true);
  var sourceSimilarityRaw = Math.max(
    averageHashSimilarity(hashes, sourceHashes),
    temporalHashSimilarity(hashes, sourceHashes)
  );
  var variantToVariantRaw = previous.reduce(function (max, item) {
    return Math.max(max, averageHashSimilarity(hashes, item.frameHashes), temporalHashSimilarity(hashes, item.frameHashes));
  }, 0);
  var variationScore = Math.round((1 - Math.max(0, Math.min(1, sourceSimilarityRaw))) * 100);
  var bundle = variantScoreBundle({
    mediaInfo,
    qualityMetrics: metrics,
    checks: validation.checks,
    warnings: qa.warnings,
    differenceFromOriginal: variationScore,
    qualitySignals: ["technical checks", "qa checks", metrics.available ? "ssim" : null].filter(Boolean),
    differenceSignals: ["multi-frame hash", "temporal hash"],
  });
  var failedChecks = validation.checks.filter((item) => item.status === "fail");
  var warningLabels = validation.checks
    .filter((item) => item.status === "warn")
    .map((item) => item.message || item.label)
    .concat(qa.warnings || [])
    .filter(Boolean);
  var uploadReady = failedChecks.length === 0;
  var mainWarnings = failedChecks.map((item) => item.message || item.label).concat(warningLabels).slice(0, 4);
  var readabilityScore = readabilityScoreFor({ validation, qa, mediaInfo, metrics });
  var safeZoneScore = safeZoneScoreFor({ validation, qa, mediaInfo });
  var focalSafetyScore = focalSafetyScoreFor({ validation, qa, mediaInfo });
  var operationDiversityScore = operationDiversityScoreFor(familyRecipe?.operationSignals || {});
  var decision = scoreVariantRecommendation({
    preset,
    uploadReady,
    qualityScore: bundle.qualityRetained,
    differenceScore: variationScore,
    operationDiversityScore,
    captionReadabilityScore: readabilityScore,
    focalSafetyScore,
    warnings: warningLabels,
    operationSignals: familyRecipe?.operationSignals || {},
  });
  var operatorState = decision.operatorState;
  var recommendedFixes = recommendedFixesFor({ failedChecks, warningLabels, variationScore, preset, mediaInfo });
  var scoreBreakdown = scoreBreakdownFor({
    sourceSimilarityRaw,
    variantToVariantRaw,
    variationScore,
    readabilityScore,
    safeZoneScore,
    validation,
    qa,
    metrics,
  });
  if (isVariantPackV2(preset)) {
    scoreBreakdown.push({
      label: "Operation diversity",
      value: operationDiversityScore,
      summary: operationDiversityScore >= presetOperationMinimum(preset) ? "intentional family operation is meaningful" : "operation family is subtle",
    });
    scoreBreakdown.push({
      label: "Focal safety",
      value: focalSafetyScore,
      summary: focalSafetyScore >= presetFocalMinimum(preset) ? "no blocking focal safety signals" : "review face/body/caption safety",
    });
  }
  return {
    file: filename,
    recipe: preset + "_variant",
    caption,
    familyName: familyRecipe?.familyName || null,
    variantFamilyRecipe: familyRecipe?.variantFamilyRecipe || null,
    operationSet: familyRecipe?.operationSet || preset,
    operationSignals: familyRecipe?.operationSignals || {},
    uploadReady,
    variationScore,
    qualityScore: bundle.qualityRetained,
    differenceScore: variationScore,
    operationDiversityScore,
    captionReadabilityScore: readabilityScore,
    focalSafetyScore,
    sourceSimilarity: Math.round(sourceSimilarityRaw * 100),
    variantToVariantSimilarity: Math.round(variantToVariantRaw * 100),
    referenceMatchLevel: sourceSimilarityRaw >= 0.72 ? "high" : sourceSimilarityRaw >= 0.42 ? "medium" : "low",
    creativeQualityScore: bundle.qualityRetained,
    readabilityScore,
    safeZoneScore,
    mainWarnings,
    operatorState,
    recommendationReason: decision.reason,
    blockingReasons: decision.blockingReasons,
    recommendedFixes,
    scoreBreakdown,
    recommended: decision.recommended,
    fileSizeBytes: statSync(filePath).size,
    _frameHashes: hashes,
  };
}

export function scoreVariantRecommendation(input = {}) {
  var preset = input.preset || "balanced";
  var uploadReady = input.uploadReady === true;
  var qualityScore = clampScore(input.qualityScore);
  var differenceScore = clampScore(input.differenceScore);
  var operationDiversityScore = clampScore(input.operationDiversityScore);
  var captionReadabilityScore = clampScore(input.captionReadabilityScore);
  var focalSafetyScore = clampScore(input.focalSafetyScore);
  var warnings = Array.isArray(input.warnings) ? input.warnings.filter(Boolean) : [];
  var operationSignals = input.operationSignals || {};
  var blockingReasons = [];
  if (!uploadReady) blockingReasons.push("not_upload_ready");
  if (unsafeTransformPresent(operationSignals)) blockingReasons.push("unsafe_transform");

  if (!isVariantPackV2(preset)) {
    if (differenceScore < presetMinimum(preset)) blockingReasons.push("difference_below_preset_minimum");
    var legacyRecommended = blockingReasons.length === 0;
    return {
      recommended: legacyRecommended,
      operatorState: !uploadReady || unsafeTransformPresent(operationSignals) ? "fix" : legacyRecommended && warnings.length === 0 ? "ready" : "review",
      reason: legacyRecommended ? "legacy_difference_passed" : "legacy_difference_or_upload_ready_failed",
      blockingReasons,
    };
  }

  if (qualityScore < presetQualityMinimum(preset)) blockingReasons.push("quality_below_minimum");
  if (captionReadabilityScore < presetReadabilityMinimum(preset)) blockingReasons.push("caption_readability_below_minimum");
  if (focalSafetyScore < presetFocalMinimum(preset)) blockingReasons.push("focal_safety_below_minimum");
  if (differenceScore < presetMinimum(preset) && operationDiversityScore < presetOperationMinimum(preset)) {
    blockingReasons.push("difference_or_operation_diversity_below_minimum");
  }
  if (operationDiversityScore < presetOperationMinimum(preset)) blockingReasons.push("operation_diversity_below_minimum");
  var recommended = blockingReasons.length === 0;
  return {
    recommended,
    operatorState: !uploadReady || blockingReasons.includes("unsafe_transform") ? "fix" : recommended && warnings.length === 0 ? "ready" : "review",
    reason: recommended ? "quality_and_operation_diversity_passed" : "quality_difference_or_safety_failed",
    blockingReasons,
  };
}

function schemaForPreset(preset) {
  return (PACK_PRESETS[preset] || PACK_PRESETS.balanced).schema || "contentforge.variant_pack.v1";
}

function isVariantPackV2(preset) {
  return schemaForPreset(preset) === "contentforge.variant_pack.v2";
}

function presetMinimum(preset) {
  return (PACK_PRESETS[preset] || PACK_PRESETS.balanced).minVariation;
}

function presetOperationMinimum(preset) {
  return (PACK_PRESETS[preset] || PACK_PRESETS.balanced).minOperationDiversity || presetMinimum(preset);
}

function presetQualityMinimum(preset) {
  return (PACK_PRESETS[preset] || PACK_PRESETS.balanced).minQuality || 0;
}

function presetReadabilityMinimum(preset) {
  return (PACK_PRESETS[preset] || PACK_PRESETS.balanced).minReadability || 0;
}

function presetFocalMinimum(preset) {
  return (PACK_PRESETS[preset] || PACK_PRESETS.balanced).minFocalSafety || 0;
}

function clampScore(value) {
  var parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function unsafeTransformPresent(signals = {}) {
  return !!(
    signals.horizontalFlip ||
    signals.heavyColorShift ||
    signals.artificialDegradation ||
    signals.captionTextChanged ||
    signals.faceRiskCrop ||
    signals.captionCollision
  );
}

function operationDiversityScoreFor(signals = {}) {
  var score = 0;
  if (signals.coverFrameDifferent) score += 28;
  if (signals.temporalDifferent) score += 24;
  if (signals.captionLaneDifferent) score += 26;
  if (signals.cropFamilyDifferent) score += 30;
  if (signals.colorProfileDifferent) score += 22;
  if (signals.audioOffsetDifferent) score += 20;
  if (signals.containerMetadataDifferent) score += 25;
  if (signals.encoderSignatureDifferent) score += 25;
  if (signals.handoffManifestDifferent) score += 25;
  if (signals.metadataChanged) score += 5;
  if (unsafeTransformPresent(signals)) score = 0;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function captionForIndex(request, index) {
  if (request.captionMode !== "supplied_hooks" || !request.suppliedHooks.length) return "";
  return request.suppliedHooks[index % request.suppliedHooks.length];
}

function variantOptionsForCaptions(request) {
  var preset = PACK_PRESETS[request.variationPreset] || PACK_PRESETS.balanced;
  var options = { ...(preset.variantOptions || {}) };
  if (request.preserveBurnedCaptions) {
    options.preserveBurnedCaptions = true;
    options.allowHorizontalFlip = false;
    options.allowStrongColorShift = false;
  }
  if (request.captionMode !== "supplied_hooks" || !request.suppliedHooks.length) return options;
  return {
    ...options,
    overlayText: request.suppliedHooks[0],
    overlayPosition: "center",
    overlayFontSize: 64,
    overlayOpacity: 0.92,
  };
}

function presetRecipeList(request) {
  if (request.recipeSet && request.recipeSet.length) return request.recipeSet;
  return (PACK_PRESETS[request.variationPreset] || PACK_PRESETS.balanced).recipes;
}

export function readabilityScoreFor({ validation, qa, mediaInfo }) {
  var score = 100;
  score -= validation.checks.filter((item) => item.status === "fail").length * 18;
  score -= validation.checks.filter((item) => item.status === "warn").length * 5;
  score -= (qa.warnings || []).length * 5;
  if (mediaInfo.bitrate > 0 && mediaInfo.bitrate < 3000000) score -= 8;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function safeZoneScoreFor({ validation, qa, mediaInfo }) {
  var score = 100;
  var aspectCheck = validation.checks.find((item) => item.id === "aspect");
  if (aspectCheck && aspectCheck.status === "warn") score -= 12;
  if (qa.letterbox) score -= 14;
  if (mediaInfo.width && mediaInfo.height && mediaInfo.width / mediaInfo.height > 0.7) score -= 8;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function focalSafetyScoreFor({ validation, qa, mediaInfo }) {
  var score = safeZoneScoreFor({ validation, qa, mediaInfo });
  var labels = validation.checks
    .filter((item) => item.status === "warn" || item.status === "fail")
    .map((item) => item.message || item.label || "")
    .concat(qa.warnings || []);
  if (labels.some((item) => /face|head|crop|cut.?off/i.test(item))) score -= 22;
  if (labels.some((item) => /caption|text|overlay/i.test(item))) score -= 18;
  if (labels.some((item) => /blur|motion/i.test(item))) score -= 8;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function recommendedFixesFor({ failedChecks, warningLabels, variationScore, preset, mediaInfo }) {
  var fixes = [];
  if (failedChecks.length) fixes.push("Fix technical export settings before review.");
  if (variationScore < presetMinimum(preset)) fixes.push("Use a stronger crop, timing, cover, or caption-structure variant.");
  if (warningLabels.some((item) => /bitrate/i.test(item))) fixes.push("Raise export bitrate or use a cleaner source.");
  if (warningLabels.some((item) => /letterbox|border/i.test(item))) fixes.push("Crop to full-frame vertical before export.");
  if (mediaInfo.fps && mediaInfo.fps < 30) fixes.push("Export at 30 fps or higher.");
  if (!fixes.length) fixes.push("Ready for human review.");
  return fixes.slice(0, 4);
}

function scoreBreakdownFor({ sourceSimilarityRaw, variantToVariantRaw, variationScore, readabilityScore, safeZoneScore, validation, qa, metrics }) {
  var rows = [];
  rows.push({
    label: "Source difference",
    value: variationScore,
    summary: sourceSimilarityRaw < 0.42 ? "clearly different from source" : sourceSimilarityRaw < 0.72 ? "moderately different from source" : "close to source family",
  });
  rows.push({
    label: "Pack diversity",
    value: Math.round((1 - Math.max(0, Math.min(1, variantToVariantRaw))) * 100),
    summary: variantToVariantRaw < 0.42 ? "different from other variants" : variantToVariantRaw < 0.72 ? "some overlap with other variants" : "similar to another variant",
  });
  rows.push({
    label: "Readability",
    value: readabilityScore,
    summary: readabilityScore >= 85 ? "clean technical/readability signals" : "review readability and export quality",
  });
  rows.push({
    label: "Safe framing",
    value: safeZoneScore,
    summary: safeZoneScore >= 85 ? "vertical framing looks safe" : "review crop, borders, or safe-zone fit",
  });
  rows.push({
    label: "Technical checks",
    value: validation.score,
    summary: validation.checks.some((item) => item.status === "fail") ? "technical failures need fixing" : "no blocking technical failures",
  });
  if (metrics.available) {
    rows.push({
      label: "Quality retained",
      value: metrics.ssim !== null ? Math.round(metrics.ssim * 100) : null,
      summary: "source-to-variant quality metric available",
    });
  }
  if ((qa.warnings || []).length) {
    rows.push({ label: "QA warnings", value: qa.warnings.length, summary: qa.warnings.join(", ") });
  }
  return rows;
}

function summarizeResults(results) {
  var ready = results.filter((item) => item.operatorState === "ready").length;
  var review = results.filter((item) => item.operatorState === "review").length;
  var fix = results.filter((item) => item.operatorState === "fix").length;
  var failed = results.filter((item) => item.operatorState === "failed").length;
  var recommended = results.filter((item) => item.recommended).length;
  var avgVariation = results.length
    ? Math.round(results.reduce((sum, item) => sum + item.variationScore, 0) / results.length)
    : 0;
  return { total: results.length, ready, review, fix, failed, recommended, avgVariation };
}
