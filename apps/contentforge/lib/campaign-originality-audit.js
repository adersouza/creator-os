import { execFile } from "child_process";
import { mkdtemp, rm, writeFile } from "fs/promises";
import { tmpdir } from "os";
import path from "path";
import { CAMPAIGN_FACTORY_AUDIT_CONFIG, campaignFactoryThresholds } from "./campaign-factory-audit-config.js";

var SUPPORTED_EXTS = [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png"];
var VIDEO_EXTS = [".mp4", ".mov", ".webm"];

function runTool(command, args, options = {}) {
  return new Promise(function (resolve) {
    execFile(command, args, {
      timeout: options.timeout || 15000,
      maxBuffer: options.maxBuffer || 4 * 1024 * 1024,
      encoding: options.encoding || "utf8",
    }, function (err, stdout, stderr) {
      if (err) {
        resolve({ ok: false, error: (stderr || err.message || "tool failed").slice(0, 1000), stdout: null });
        return;
      }
      resolve({ ok: true, error: null, stdout });
    });
  });
}

function probeFile(filePath) {
  return runTool("ffprobe", [
    "-v", "quiet",
    "-print_format", "json",
    "-show_format", "-show_streams",
    filePath,
  ], { timeout: 10000, maxBuffer: 1024 * 1024 }).then(function (result) {
    if (!result.ok) return null;
    try {
      return JSON.parse(result.stdout || "{}");
    } catch {
      return null;
    }
  });
}

function extractFrame(filePath, timeSec, width = 180, height = 320) {
  return new Promise(function (resolve) {
    execFile("ffmpeg", [
      "-hide_banner",
      "-loglevel", "error",
      "-ss", String(Math.max(0, timeSec)),
      "-i", filePath,
      "-frames:v", "1",
      "-vf", "scale=" + width + ":" + height + ":force_original_aspect_ratio=decrease,pad=" + width + ":" + height + ":(ow-iw)/2:(oh-ih)/2,format=rgb24",
      "-f", "rawvideo",
      "pipe:1",
    ], {
      timeout: 15000,
      maxBuffer: width * height * 3 + 1024,
      encoding: "buffer",
    }, function (err, stdout) {
      if (err || !stdout || stdout.length < width * height * 3) {
        resolve(null);
        return;
      }
      resolve({ width, height, data: stdout.subarray(0, width * height * 3), timeSec });
    });
  });
}

function extractFramePng(filePath, timeSec, width = 360, height = 640) {
  return new Promise(function (resolve) {
    execFile("ffmpeg", [
      "-hide_banner",
      "-loglevel", "error",
      "-ss", String(Math.max(0, timeSec)),
      "-i", filePath,
      "-frames:v", "1",
      "-vf", "scale=" + width + ":" + height + ":force_original_aspect_ratio=decrease,pad=" + width + ":" + height + ":(ow-iw)/2:(oh-ih)/2",
      "-f", "image2pipe",
      "-vcodec", "png",
      "pipe:1",
    ], {
      timeout: 15000,
      maxBuffer: 4 * 1024 * 1024,
      encoding: "buffer",
    }, function (err, stdout) {
      if (err || !stdout || stdout.length < 100) {
        resolve(null);
        return;
      }
      resolve({ width, height, data: stdout, timeSec });
    });
  });
}

function runChromaprint(filePath) {
  return runTool("fpcalc", ["-json", filePath], { timeout: 15000 }).then(function (result) {
    if (!result.ok) return { fingerprint: null, duration: null, error: result.error };
    try {
      var data = JSON.parse(result.stdout || "{}");
      return { fingerprint: data.fingerprint || null, duration: data.duration || null, error: null };
    } catch {
      return { fingerprint: null, duration: null, error: "Parse failed" };
    }
  });
}

function safeBasenameList(value) {
  var raw = Array.isArray(value) ? value : [];
  return raw
    .map(function (item) { return String(item || ""); })
    .map(function (item) { return item.replace(/^output\/final\//, ""); })
    .filter(function (item) {
      return item && item === path.basename(item) && SUPPORTED_EXTS.includes(path.extname(item).toLowerCase());
    });
}

function normalizeOriginalityText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokenSimilarity(a, b) {
  var left = new Set(normalizeOriginalityText(a).split(" ").filter(Boolean));
  var right = new Set(normalizeOriginalityText(b).split(" ").filter(Boolean));
  if (!left.size || !right.size) return null;
  var intersection = 0;
  for (var token of left) {
    if (right.has(token)) intersection++;
  }
  var union = new Set([...left, ...right]).size;
  return union ? intersection / union : null;
}

function lumaAt(frame, x, y) {
  var idx = ((y * frame.width) + x) * 3;
  return (0.2126 * frame.data[idx]) + (0.7152 * frame.data[idx + 1]) + (0.0722 * frame.data[idx + 2]);
}

function frameDelta(a, b) {
  if (!a || !b || a.width !== b.width || a.height !== b.height) return null;
  var total = 0;
  var samples = 0;
  for (var y = 0; y < a.height; y += 4) {
    for (var x = 0; x < a.width; x += 4) {
      total += Math.abs(lumaAt(a, x, y) - lumaAt(b, x, y));
      samples++;
    }
  }
  return samples ? total / samples : null;
}

function frameSignature(frame) {
  if (!frame) return null;
  var bins = new Array(16).fill(0);
  var centerWeight = 0;
  var edgeWeight = 0;
  for (var y = 0; y < frame.height; y += 4) {
    for (var x = 0; x < frame.width; x += 4) {
      var luma = lumaAt(frame, x, y);
      bins[Math.max(0, Math.min(15, Math.floor(luma / 16)))]++;
      var cx = Math.abs((x / frame.width) - 0.5);
      var cy = Math.abs((y / frame.height) - 0.5);
      if (cx < 0.22 && cy < 0.22) centerWeight += luma;
      if (cx > 0.38 || cy > 0.38) edgeWeight += luma;
    }
  }
  var total = bins.reduce(function (sum, value) { return sum + value; }, 0) || 1;
  return [
    ...bins.map(function (value) { return value / total; }),
    centerWeight / total / 255,
    edgeWeight / total / 255,
  ];
}

function vectorCosine(a, b) {
  if (!a || !b || a.length !== b.length) return null;
  var dot = 0;
  var left = 0;
  var right = 0;
  for (var i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    left += a[i] * a[i];
    right += b[i] * b[i];
  }
  if (!left || !right) return null;
  return dot / (Math.sqrt(left) * Math.sqrt(right));
}

function averageSignatureSimilarity(targetFrames, referenceFrames) {
  var scores = [];
  var count = Math.min(targetFrames.length, referenceFrames.length);
  for (var i = 0; i < count; i++) {
    var similarity = vectorCosine(frameSignature(targetFrames[i]), frameSignature(referenceFrames[i]));
    if (Number.isFinite(similarity)) scores.push(Math.round(similarity * 100));
  }
  return scores.length ? Math.round(scores.reduce(function (sum, value) { return sum + value; }, 0) / scores.length) : null;
}

function visualSimilarityFromDelta(delta) {
  if (!Number.isFinite(delta)) return null;
  return Math.max(0, Math.min(100, Math.round(100 - (delta * 3.2))));
}

function riskFromScore(score, medium, high) {
  if (!Number.isFinite(score)) return "unknown";
  if (score >= high) return "high";
  if (score >= medium) return "medium";
  return "low";
}

function maxRisk(risks) {
  if (risks.includes("high")) return "high";
  if (risks.includes("medium")) return "medium";
  if (risks.includes("low")) return "low";
  return "unknown";
}

function targetHookTextFromOcr(ocr) {
  return (ocr?.results || [])
    .filter(function (item) { return (item.timeSec || 0) <= 3; })
    .map(function (item) { return item.ocrText || ""; })
    .join(" ")
    .trim();
}

async function hookTextForFile(filePath, fileName, timeSec) {
  var pngFrame = await extractFramePng(filePath, timeSec);
  if (!pngFrame) return { text: "", available: false, error: "frame extraction failed" };
  var tempDir = await mkdtemp(path.join(tmpdir(), "contentforge-originality-ocr-"));
  var imagePath = path.join(tempDir, "frame.png");
  try {
    await writeFile(imagePath, pngFrame.data);
    var imageResult = await runTool("tesseract", [imagePath, "stdout", "--psm", "6"], {
      timeout: 15000,
      maxBuffer: 1024 * 1024,
    });
    if (!imageResult.ok) return { text: "", available: false, error: imageResult.error };
    return {
      text: normalizeOriginalityText(imageResult.stdout || ""),
      available: true,
      engine: "tesseract",
      file: fileName,
      timeSec,
    };
  } finally {
    await rm(tempDir, { recursive: true, force: true }).catch(function () {});
  }
}

async function sampleOriginalityFrames(filePath, duration) {
  var requestedTimes = CAMPAIGN_FACTORY_AUDIT_CONFIG.sampling.ocrFrameTimesSec;
  var times = requestedTimes
    .map(function (time) {
      if (!duration || time < duration) return time;
      return Math.max(0, duration - 0.1);
    })
    .filter(function (time, index, arr) { return arr.indexOf(time) === index; });
  if (!times.length) times = [0];
  var frames = [];
  for (var time of times) {
    var frame = await extractFrame(filePath, time);
    if (frame) frames.push(frame);
  }
  return frames;
}

function averageFrameSimilarity(targetFrames, referenceFrames) {
  var scores = [];
  var count = Math.min(targetFrames.length, referenceFrames.length);
  for (var i = 0; i < count; i++) {
    var similarity = visualSimilarityFromDelta(frameDelta(targetFrames[i], referenceFrames[i]));
    if (Number.isFinite(similarity)) scores.push(similarity);
  }
  return scores.length ? Math.round(scores.reduce(function (sum, value) { return sum + value; }, 0) / scores.length) : null;
}

async function audioMatches(targetPath, referencePath) {
  var [target, reference] = await Promise.all([runChromaprint(targetPath), runChromaprint(referencePath)]);
  if (!target.fingerprint || !reference.fingerprint) {
    return { match: null, available: false, reason: target.error || reference.error || "audio fingerprint unavailable" };
  }
  return { match: target.fingerprint === reference.fingerprint, available: true, reason: null };
}

function advisoryWarning(code, label, message, severity = "warn") {
  return { code, label, message, severity };
}

function uniqueWarnings(warnings) {
  var seen = new Set();
  return (warnings || []).filter(function (warning) {
    var key = warning.code + ":" + warning.message;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function variationNotes(overallRisk, componentRisks) {
  var notes = [];
  if (overallRisk === "low") return notes;
  if (componentRisks.opening !== "low" && componentRisks.opening !== "unknown") {
    notes.push("Opening closely follows a reference; keep it for an exact-format variant or adjust pacing/shot choice for a lighter variation.");
  }
  if (componentRisks.hook !== "low" && componentRisks.hook !== "unknown") {
    notes.push("Visible hook closely follows a reference; track it as intentional reuse or rewrite for a more distinct angle.");
  }
  if (componentRisks.cover !== "low" && componentRisks.cover !== "unknown") {
    notes.push("Cover frame closely follows a reference; keep it for close-format variants or choose a different cover for more distance.");
  }
  if (componentRisks.audio !== "low" && componentRisks.audio !== "unknown") {
    notes.push("Audio matches a reference; useful for close variants, but track reuse across accounts.");
  }
  if (componentRisks.template !== "low" && componentRisks.template !== "unknown") {
    notes.push("Template signals match a reference; this is suitable for exact-format variants and should be visible in operator review.");
  }
  if (!notes.length) {
    notes.push("Reference match detected; use the match score to decide whether this should be close-format or more varied.");
  }
  return notes;
}

function referenceMatchSignals(audit) {
  var signals = [];
  if (audit.duplicateRisk === "high" || audit.duplicateRisk === "medium") {
    signals.push(advisoryWarning("reference_match_close", "Close reference match", "Target closely follows a referenced reel", "info"));
  }
  if (audit.sameOpeningRisk === "high" || audit.sameOpeningRisk === "medium") {
    signals.push(advisoryWarning("reference_match_same_opening", "Opening matches reference", "First 3 seconds are visually close to a referenced reel", "info"));
  }
  if (audit.sameHookRisk === "high" || audit.sameHookRisk === "medium") {
    signals.push(advisoryWarning("reference_match_same_hook", "Hook matches reference", "Detected hook text overlaps with a referenced reel", "info"));
  }
  if (audit.sameCoverRisk === "high" || audit.sameCoverRisk === "medium") {
    signals.push(advisoryWarning("reference_match_same_cover", "Cover matches reference", "Cover candidate is visually close to a referenced reel", "info"));
  }
  if (audit.sameAudioRisk === "high" || audit.sameAudioRisk === "medium") {
    signals.push(advisoryWarning("reference_match_same_audio", "Audio matches reference", "Audio fingerprint matches a referenced reel", "info"));
  }
  if (audit.sameTemplateRisk === "high" || audit.sameTemplateRisk === "medium") {
    signals.push(advisoryWarning("reference_match_template_reuse", "Template matches reference", "Multiple match signals suggest the edit template follows a reference", "info"));
  }
  return uniqueWarnings(signals);
}

async function parallelMapLimit(items, limit, worker) {
  var results = new Array(items.length);
  var index = 0;
  async function runNext() {
    while (index < items.length) {
      var current = index++;
      results[current] = await worker(items[current], current);
    }
  }
  var workers = Array.from({ length: Math.min(limit, items.length) }, runNext);
  await Promise.all(workers);
  return results;
}

async function analyzeReference(referenceFile, options, targetContext) {
  var thresholds = campaignFactoryThresholds();
  var referencePath = path.join(options.finalDir, referenceFile);
  var referenceProbe = await probeFile(referencePath);
  var referenceDuration = Number.parseFloat(referenceProbe?.format?.duration || "0");
  var referenceFrames = await sampleOriginalityFrames(referencePath, referenceDuration);
  var openingSimilarity = averageFrameSimilarity(targetContext.frames, referenceFrames);
  var frameSignatureSimilarity = averageSignatureSimilarity(targetContext.frames, referenceFrames);
  var coverSimilarity = null;
  if (targetContext.frames.length && referenceFrames.length) {
    coverSimilarity = visualSimilarityFromDelta(frameDelta(targetContext.frames[0], referenceFrames[0]));
  }
  var hookSimilarity = null;
  if (targetContext.hookText) {
    var referenceHook = await hookTextForFile(referencePath, referenceFile, 0.4);
    hookSimilarity = referenceHook.text ? tokenSimilarity(targetContext.hookText, referenceHook.text) : null;
  }
  var audio = await audioMatches(targetContext.path, referencePath);
  var audioScore = audio.match === true ? 100 : audio.match === false ? 0 : null;
  var weightedScores = [
    { value: openingSimilarity, weight: 0.45 },
    { value: frameSignatureSimilarity, weight: 0.20 },
    { value: coverSimilarity, weight: 0.25 },
    { value: hookSimilarity === null ? null : Math.round(hookSimilarity * 100), weight: 0.20 },
    { value: audioScore, weight: 0.10 },
  ].filter(function (score) { return Number.isFinite(score.value); });
  var score = weightedScores.length
    ? Math.round(weightedScores.reduce(function (sum, item) { return sum + (item.value * item.weight); }, 0) / weightedScores.reduce(function (sum, item) { return sum + item.weight; }, 0))
    : 0;
  var openingRisk = riskFromScore(openingSimilarity, thresholds.originalityOpeningMediumSimilarity, thresholds.originalityOpeningHighSimilarity);
  var coverRisk = riskFromScore(coverSimilarity, thresholds.originalityCoverMediumSimilarity, thresholds.originalityCoverHighSimilarity);
  var hookRisk = hookSimilarity === null ? "unknown" : riskFromScore(hookSimilarity, thresholds.originalityHookMediumSimilarity, thresholds.originalityHookHighSimilarity);
  var audioRisk = audio.match === null ? "unknown" : audio.match ? "high" : "low";
  var templateRisk = maxRisk([openingRisk, coverRisk, hookRisk].filter(function (risk) { return risk !== "unknown"; }));
  var duplicateRisk = riskFromScore(score, thresholds.originalityOverallMediumRisk, thresholds.originalityOverallHighRisk);
  var variationScore = Math.max(0, 100 - score);
  var reasons = [];
  if (openingRisk !== "low" && openingRisk !== "unknown") reasons.push("similar_opening");
  if (coverRisk !== "low" && coverRisk !== "unknown") reasons.push("similar_cover");
  if (hookRisk !== "low" && hookRisk !== "unknown") reasons.push("similar_hook");
  if (audioRisk !== "low" && audioRisk !== "unknown") reasons.push("matching_audio");
  if (templateRisk !== "low" && templateRisk !== "unknown") reasons.push("template_reuse");
  return {
    file: referenceFile,
    score,
    referenceMatchScore: score,
    variationScore,
    duplicateRisk,
    referenceMatchLevel: duplicateRisk,
    openingSimilarity,
    frameSignatureSimilarity,
    hookSimilarity: hookSimilarity === null ? null : Math.round(hookSimilarity * 100) / 100,
    coverSimilarity,
    audioMatch: audio.match,
    reasons,
    framesSampled: referenceFrames.length,
  };
}

export async function runMultiAccountOriginalityAudit(options) {
  var startedAt = Date.now();
  var thresholds = campaignFactoryThresholds();
  var targetFile = options.targetFile;
  var targetPath = path.join(options.finalDir, targetFile);
  var requestedReferences = safeBasenameList(options.referenceFiles);
  var explicitOutputFinalScope = options.originalityScope === "output_final";
  var references = requestedReferences;
  if (!references.length && explicitOutputFinalScope) {
    references = options.allFiles.filter(function (file) {
      return file !== targetFile && VIDEO_EXTS.includes(path.extname(file).toLowerCase());
    });
  }
  references = [...new Set(references)]
    .filter(function (file) { return file !== targetFile && options.allFiles.includes(file); })
    .slice(0, thresholds.originalityMaxReferenceFiles);

  var targetProbe = await probeFile(targetPath);
  var targetDuration = Number.parseFloat(targetProbe?.format?.duration || "0");
  var targetFrames = await sampleOriginalityFrames(targetPath, targetDuration);
  var targetHookText = targetHookTextFromOcr(options.ocr);
  var targetContext = {
    path: targetPath,
    frames: targetFrames,
    hookText: targetHookText,
  };
  var nearestMatches = await parallelMapLimit(references, 3, function (referenceFile) {
    return analyzeReference(referenceFile, options, targetContext);
  });
  nearestMatches = nearestMatches.filter(Boolean).sort(function (a, b) { return b.score - a.score; });
  var top = nearestMatches[0] || null;
  var sameOpeningRisk = maxRisk(nearestMatches.map(function (item) {
    return riskFromScore(item.openingSimilarity, thresholds.originalityOpeningMediumSimilarity, thresholds.originalityOpeningHighSimilarity);
  }));
  var sameCoverRisk = maxRisk(nearestMatches.map(function (item) {
    return riskFromScore(item.coverSimilarity, thresholds.originalityCoverMediumSimilarity, thresholds.originalityCoverHighSimilarity);
  }));
  var sameHookRisk = maxRisk(nearestMatches.map(function (item) {
    return item.hookSimilarity === null ? "unknown" : riskFromScore(item.hookSimilarity, thresholds.originalityHookMediumSimilarity, thresholds.originalityHookHighSimilarity);
  }));
  var sameAudioRisk = maxRisk(nearestMatches.map(function (item) {
    return item.audioMatch === null ? "unknown" : item.audioMatch ? "high" : "low";
  }));
  var sameTemplateRisk = maxRisk([sameOpeningRisk, sameCoverRisk, sameHookRisk].filter(function (risk) { return risk !== "unknown"; }));
  var duplicateRisk = top ? riskFromScore(top.score, thresholds.originalityOverallMediumRisk, thresholds.originalityOverallHighRisk) : "low";
  var referenceMatchScore = top ? top.score : 0;
  var variationScore = top ? Math.max(0, 100 - top.score) : 100;
  var componentRisks = {
    opening: sameOpeningRisk,
    hook: sameHookRisk,
    audio: sameAudioRisk,
    cover: sameCoverRisk,
    template: sameTemplateRisk,
  };
  var notes = variationNotes(duplicateRisk, componentRisks);
  var audit = {
    available: true,
    mode: "reference_match_meter",
    blocking: false,
    verdict: "pass",
    referenceMatchLevel: duplicateRisk,
    referenceMatchScore,
    variationScore,
    duplicateRisk,
    originalityScore: variationScore,
    nearestMatches: nearestMatches.slice(0, 5).map(function (match) {
      return {
        file: match.file,
        score: match.score,
        referenceMatchScore: match.referenceMatchScore,
        variationScore: match.variationScore,
        referenceMatchLevel: match.referenceMatchLevel,
        duplicateRisk: match.duplicateRisk,
        openingSimilarity: match.openingSimilarity,
        frameSignatureSimilarity: match.frameSignatureSimilarity,
        hookSimilarity: match.hookSimilarity,
        coverSimilarity: match.coverSimilarity,
        audioMatch: match.audioMatch,
        reasons: match.reasons,
      };
    }),
    sameOpeningRisk,
    sameHookRisk,
    sameAudioRisk,
    sameCoverRisk,
    sameTemplateRisk,
    sameOpeningLevel: sameOpeningRisk,
    sameHookLevel: sameHookRisk,
    sameAudioLevel: sameAudioRisk,
    sameCoverLevel: sameCoverRisk,
    sameTemplateLevel: sameTemplateRisk,
    variationNotes: notes,
    recommendedCreativeChanges: notes,
    referenceMatchSignals: [],
    warnings: [],
    metrics: {
      targetFile,
      referenceFilesChecked: references.length,
      referenceFilesRequested: requestedReferences.length,
      scope: explicitOutputFinalScope ? "output_final" : requestedReferences.length ? "explicit_references" : "none",
      maxReferenceFiles: thresholds.originalityMaxReferenceFiles,
      framesSampled: targetFrames.length + nearestMatches.reduce(function (sum, match) { return sum + (match.framesSampled || 0); }, 0),
      runtimeMs: Date.now() - startedAt,
      concurrency: 3,
      signatureVersion: "local_frame_signature_v1",
    },
  };
  audit.referenceMatchSignals = referenceMatchSignals(audit);
  return audit;
}
