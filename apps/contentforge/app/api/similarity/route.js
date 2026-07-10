import { NextResponse } from "next/server.js";
import { execFile } from "child_process";
import { readdir, access, open, mkdtemp, symlink, rm, writeFile } from "fs/promises";
import { tmpdir } from "os";
import path from "path";
import sharp from "sharp";
import { resolveRunFinalDir, resolveUploadPath } from "../../../lib/paths.js";
import { getPythonCommand } from "../../../lib/python-runtime.js";
import { CAMPAIGN_FACTORY_AUDIT_CONFIG, campaignFactoryThresholds } from "../../../lib/campaign-factory-audit-config.js";
import { runMultiAccountOriginalityAudit } from "../../../lib/campaign-originality-audit.js";
import { buildCreativeQualityAudit } from "../../../lib/creative-quality-audit.js";
import { buildViralityGate } from "../../../lib/virality-gate.js";
import { buildVideoAnalysisGate } from "../../../lib/video-analysis-gate.js";
import { getQualityMetrics } from "../../../lib/quality-metrics.js";
import { getQaSignals } from "../../../lib/reels.js";

var SUPPORTED_EXTS = [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png"];
var VIDEO_EXTS = [".mp4", ".mov", ".webm"];
var VALID_LAYERS = new Set(["pdq", "sscd", "audio", "forensics", "compression", "provenance", "reference", "temporal", "ssim", "safeZone", "readability", "cover", "hookVisibility", "watchability", "originality", "creativeQuality", "virality", "videoAnalysis"]);
var REVIEW_ONLY_LAYERS = new Set(["pdq", "sscd", "audio", "reference", "temporal", "ssim"]);
var VALID_AUDIT_PROFILES = new Set(["default", "campaign_factory_v1"]);
var CAMPAIGN_FACTORY_CONTRACT_VERSION = "campaign_factory_audit.v1.10";
var OCR_ENGINE_CHOICES = new Set(["auto", "apple_vision", "tesseract", "heuristic"]);
var versionCache = new Map();

function parseJsonOutput(stdout, fallback) {
  try {
    return JSON.parse(stdout || "{}");
  } catch {
    return fallback;
  }
}

function optionalLayerResult(layer, reason, extra = {}) {
  return {
    available: false,
    reason,
    error: reason,
    severity: "warn",
    ...extra,
  };
}

function runPythonJson(scriptName, args, options = {}) {
  return new Promise((resolve) => {
    var scriptPath = path.join(process.cwd(), "lib", scriptName);
    execFile(getPythonCommand(), [scriptPath, ...args], {
      timeout: options.timeout || 60000,
      maxBuffer: options.maxBuffer || 5 * 1024 * 1024,
    }, (err, stdout, stderr) => {
      var fallback = optionalLayerResult(options.layer || scriptName, err?.message || "Python layer failed", options.fallback || {});
      if (err) {
        var parsedError = parseJsonOutput(stdout, null);
        if (parsedError && (parsedError.error || parsedError.available === false)) {
          resolve({
            available: false,
            reason: parsedError.error || parsedError.reason || err.message,
            error: parsedError.error || parsedError.reason || err.message,
            severity: "warn",
            ...options.fallback,
            ...parsedError,
          });
          return;
        }
        resolve({
          ...fallback,
          stderr: (stderr || "").slice(0, 2000),
        });
        return;
      }
      resolve(parseJsonOutput(stdout, optionalLayerResult(
        options.layer || scriptName,
        "Failed to parse " + (options.layer || scriptName) + " output: " + (stdout || "").slice(0, 200),
        options.fallback || {}
      )));
    });
  });
}

// ─── Layer 1: PDQ Hash (Meta's exact production algorithm) ───
function runPDQCheck(sourcePath, outputDir) {
  return runPythonJson("pdq_check.py", [sourcePath, outputDir, "100"], {
    layer: "pdq",
    timeout: 120000,
    fallback: { results: [], stats: {} },
  });
}

// ─── Layer 1b: SSCD Neural Embedding (Meta's copy detection model) ───
function runSSCDCheck(sourcePath, outputDir) {
  return runPythonJson("sscd_check.py", [sourcePath, outputDir, "50"], {
    layer: "sscd",
    timeout: 180000,
    fallback: { results: [], stats: {} },
  });
}

// ─── Layer 2: Audio Fingerprint (Chromaprint/AcoustID) ───
function runChromaprint(filePath) {
  return new Promise((resolve) => {
    execFile("fpcalc", ["-json", filePath], { timeout: 15000 }, (err, stdout) => {
      if (err) {
        resolve({ fingerprint: null, duration: null, error: err.message });
        return;
      }
      try {
        var data = JSON.parse(stdout);
        resolve({ fingerprint: data.fingerprint, duration: data.duration, error: null });
      } catch {
        resolve({ fingerprint: null, duration: null, error: "Parse failed" });
      }
    });
  });
}

async function runAudioCheck(sourcePath, outputDir, files) {
  var srcExt = path.extname(sourcePath).toLowerCase();
  if (!VIDEO_EXTS.includes(srcExt)) {
    return { available: false, reason: "Image mode — no audio" };
  }

  var sourceResult = await runChromaprint(sourcePath);
  if (!sourceResult.fingerprint) {
    return { available: false, reason: sourceResult.error || "No audio in source" };
  }

  var videoFiles = files.filter(f => VIDEO_EXTS.includes(path.extname(f).toLowerCase())).slice(0, 30);
  var results = [];
  var matchCount = 0;

  // Process in batches
  for (var i = 0; i < videoFiles.length; i += 5) {
    var batch = videoFiles.slice(i, i + 5);
    var batchResults = await Promise.all(batch.map(async (fname) => {
      var variantResult = await runChromaprint(path.join(outputDir, fname));
      if (!variantResult.fingerprint) {
        return { name: fname, match: null, error: variantResult.error };
      }
      // Compare fingerprints — if identical string, audio is unchanged
      var match = sourceResult.fingerprint === variantResult.fingerprint;
      if (match) matchCount++;
      return { name: fname, match, error: null };
    }));
    results.push(...batchResults);
  }

  return {
    available: true,
    results,
    stats: {
      total: results.length,
      identicalCount: matchCount,
      identicalPercent: results.length > 0 ? Math.round((matchCount / results.length) * 100) : 0,
      safe: matchCount === 0,
    }
  };
}

// ─── Layer 3: Metadata Forensics ───
function probeFile(filePath) {
  return new Promise((resolve) => {
    execFile("ffprobe", [
      "-v", "quiet",
      "-print_format", "json",
      "-show_format", "-show_streams",
      filePath
    ], { timeout: 10000, maxBuffer: 1024 * 1024 }, (err, stdout) => {
      if (err) { resolve(null); return; }
      try { resolve(JSON.parse(stdout)); } catch { resolve(null); }
    });
  });
}

function checkStrings(filePath) {
  return new Promise((resolve) => {
    execFile("strings", [filePath], { timeout: 10000, maxBuffer: 2 * 1024 * 1024 }, (err, stdout) => {
      if (err) { resolve(""); return; }
      resolve(stdout || "");
    });
  });
}

async function hasFaststart(filePath) {
  var fh;
  try {
    fh = await open(filePath, "r");
    var buffer = Buffer.alloc(1024 * 1024);
    var result = await fh.read(buffer, 0, buffer.length, 0);
    var head = buffer.slice(0, result.bytesRead).toString("latin1");
    var moov = head.indexOf("moov");
    var mdat = head.indexOf("mdat");
    return moov >= 0 && (mdat < 0 || moov < mdat);
  } catch {
    return false;
  } finally {
    if (fh) await fh.close().catch(function () {});
  }
}

function addIssue(issues, severity, field, value, msg, code, blocking = severity === "critical" || severity === "high") {
  issues.push({ severity, field, value, msg, code, blocking });
}

function isEpochCreationTime(value) {
  return !value || /^1970-01-01T00:00:00/i.test(value);
}

function isMp4Compatible(formatName, majorBrand) {
  var haystack = (formatName + " " + majorBrand).toLowerCase();
  return /mp4|mov|m4a|3gp|mj2|qt/.test(haystack);
}

function isVerticalSocialReady(width, height) {
  var thresholds = campaignFactoryThresholds();
  if (width <= 0 || height <= 0) return false;
  var aspect = width / height;
  return width >= thresholds.minSocialWidth &&
    height >= thresholds.minSocialHeight &&
    Math.abs(aspect - thresholds.verticalAspectRatio) <= thresholds.verticalAspectTolerance;
}

function audioPolicyPasses(audioStream) {
  if (!audioStream || !audioStream.codec_name) return true;
  var codec = audioStream.codec_name || "";
  var rate = parseInt(audioStream.sample_rate || 0, 10);
  return codec === "aac" && (!rate || rate === 44100 || rate === 48000);
}

function fileScore(issues) {
  if (issues.some(function (issue) { return issue.blocking; })) return "fail";
  if (issues.length > 0) return "warn";
  return "pass";
}

function uniqueMessages(items) {
  return [...new Set(items.filter(Boolean))];
}

function addReadinessItem(list, code, message, label = message, severity = "warn") {
  list.push({ code, message, label, severity });
}

function addAdvisoryWarnings(warningItems, layer, warnings) {
  for (var warning of warnings || []) {
    addReadinessItem(
      warningItems,
      warning.code || layer + "_review",
      warning.message || warning.label || layer + " needs review",
      warning.label || warning.message || layer + " needs review",
      warning.severity || "warn"
    );
  }
}

function addProfileWarnings(blockingItems, warningItems, layer, warnings, shouldBlock) {
  for (var warning of warnings || []) {
    var destination = shouldBlock(warning) ? blockingItems : warningItems;
    addReadinessItem(
      destination,
      warning.code || layer + "_review",
      warning.message || warning.label || layer + " needs review",
      warning.label || warning.message || layer + " needs review",
      warning.severity || "warn"
    );
  }
}

function warningPriority(item) {
  var code = item.code || "";
  if (/^caption_|^hook_|^cover_|^creative_/.test(code)) return 0;
  if (/^(originality_|reference_match_)/.test(code)) return 5;
  if (/^compression_/.test(code)) return 2;
  if (/^provenance_/.test(code)) return 3;
  if (/^forensics_/.test(code)) return 4;
  return 4;
}

function operatorLabelForWarningCode(code) {
  if (/^(originality_|reference_match_)/.test(code || "")) return "informational";
  if (/^(caption|hook|cover|safe_zone|compression|creative)_/.test(code || "")) return "needs review";
  if (/^(forensics_ffmpeg_signature|forensics_binary_signature|forensics_audio_missing|provenance_c2pa_unavailable|reference_review|reference_unavailable|ocr_unavailable)$/.test(code || "")) {
    return "advisory";
  }
  if (/^(forensics_missing_creation_time|forensics_default_handler_name|forensics_bitrate_review|provenance_unavailable)$/.test(code || "")) {
    return "informational";
  }
  return "needs review";
}

function operatorLabelGroups(blockingItems, warningItems) {
  var groups = {
    blocking: blockingItems.map(function (item) { return { ...item, operatorLabel: "blocking" }; }),
    needsReview: [],
    advisory: [],
    informational: [],
  };
  for (var item of warningItems) {
    var label = item.operatorLabel || operatorLabelForWarningCode(item.code);
    var payload = { ...item, operatorLabel: label };
    if (label === "advisory") groups.advisory.push(payload);
    else if (label === "informational") groups.informational.push(payload);
    else groups.needsReview.push(payload);
  }
  return groups;
}

export function buildDetectorVerdicts(results, auditProfile = "default", options = {}) {
  var thresholds = campaignFactoryThresholds();
  var campaignProfile = auditProfile === "campaign_factory_v1";
  var hasVariantCount = Object.prototype.hasOwnProperty.call(options, "variantCount");
  var fanoutDistinctness = !campaignProfile || !hasVariantCount || Number(options.variantCount || 0) > 1;
  var verdicts = {};
  var pdq = results.pdq;
  if (pdq) {
    if (campaignProfile && !fanoutDistinctness) {
      verdicts.pdq = "pass";
    } else if (pdq.available === false || pdq.error) {
      verdicts.pdq = campaignProfile ? "fail" : "warn";
    } else if (campaignProfile) {
      var pdqStats = pdq.stats || {};
      var pdqFailed = !Number.isFinite(pdqStats.minDistance) ||
        pdqStats.minDistance <= thresholds.pdqSafeDistance ||
        Number(pdqStats.crossCollisions || 0) > 0 ||
        Number(pdqStats.crossSafeTargetViolations || 0) > 0;
      verdicts.pdq = pdqFailed ? "fail" : "pass";
    } else {
      var avgDist = pdq.stats?.avgDistance;
      verdicts.pdq = Number.isFinite(avgDist) ? (avgDist > 60 ? "pass" : avgDist > 30 ? "warn" : "fail") : "warn";
    }
  }
  var sscd = results.sscd;
  if (sscd) {
    if (campaignProfile && !fanoutDistinctness) {
      verdicts.sscd = "pass";
    } else if (sscd.available === false || sscd.error) {
      verdicts.sscd = campaignProfile ? "fail" : "warn";
    } else if (campaignProfile) {
      var sscdStats = sscd.stats || {};
      var sscdFailed = !Number.isFinite(sscdStats.maxSimilarity) ||
        sscdStats.maxSimilarity >= thresholds.sscdSafeSimilarity ||
        Number(sscdStats.crossVariantCollisions || 0) > 0 ||
        Number(sscdStats.crossVariantSafeTargetViolations || 0) > 0;
      verdicts.sscd = sscdFailed ? "fail" : "pass";
    } else {
      var avgSim = sscd.stats?.avgSimilarity;
      verdicts.sscd = Number.isFinite(avgSim) ? (avgSim < 0.50 ? "pass" : avgSim < 0.75 ? "warn" : "fail") : "warn";
    }
  }
  return verdicts;
}

export function buildReadinessSummary(results, verdicts, options = {}) {
  var auditProfile = options.auditProfile || "default";
  var campaignProfile = auditProfile === "campaign_factory_v1";
  var requestedLayers = new Set(options.requestedLayers || []);
  var hasVariantCount = Object.prototype.hasOwnProperty.call(options, "variantCount");
  var fanoutDistinctness = !campaignProfile || !hasVariantCount || Number(options.variantCount || 0) > 1;
  var blockingReasons = [];
  var warnings = [];
  var blockingItems = [];
  var warningItems = [];

  for (var report of results.forensics?.fileReports || []) {
    for (var issue of report.issues || []) {
      var message = report.name + ": " + issue.field + " - " + issue.msg;
      if (issue.blocking) {
        blockingReasons.push(message);
        addReadinessItem(blockingItems, issue.code || "forensics_blocking_issue", message, issue.msg);
      } else {
        warnings.push(message);
        addReadinessItem(warningItems, issue.code || "forensics_review", message, issue.msg);
      }
    }
  }

  var compression = results.compression;
  if (compression?.available === false || compression?.error) {
    addReadinessItem(warningItems, "compression_unavailable", "compression: Compression check unavailable", "Compression check unavailable");
  } else if (compression?.summary) {
    if ((compression.summary.failed || 0) > 0) {
      var message = "compression: Compression pattern needs review";
      if (verdicts.compression === "fail") addReadinessItem(blockingItems, "compression_gop_review", message, "Compression pattern needs review");
      else addReadinessItem(warningItems, "compression_gop_review", message, "Compression pattern needs review");
    }
    if ((compression.summary.warnings || 0) > 0) {
      addReadinessItem(warningItems, "compression_pattern_review", "compression: Compression pattern needs review", "Compression pattern needs review");
    }
  }

  var provenance = results.provenance;
  if (provenance?.available === false || provenance?.error) {
    addReadinessItem(warningItems, "provenance_unavailable", "provenance: Provenance check unavailable", "Provenance check unavailable");
  } else if (provenance?.summary) {
    if ((provenance.summary.flagged || 0) > 0) {
      addReadinessItem(blockingItems, "provenance_ai_flagged", "provenance: AI/provenance signal needs review", "AI/provenance signal needs review");
    }
    if ((provenance.summary.unavailable || 0) > 0) {
      addReadinessItem(warningItems, "provenance_c2pa_unavailable", "provenance: Optional C2PA check unavailable", "Optional C2PA check unavailable");
    }
  }

  addAdvisoryWarnings(campaignProfile ? blockingItems : warningItems, "safe_zone", results.safeZone?.warnings);
  addProfileWarnings(
    blockingItems,
    warningItems,
    "caption",
    results.readability?.warnings,
    function (warning) {
      return campaignProfile && !["caption_not_detected", "ocr_unavailable"].includes(warning.code);
    }
  );
  addAdvisoryWarnings(warningItems, "cover", results.cover?.warnings);
  addAdvisoryWarnings(campaignProfile ? blockingItems : warningItems, "hook", results.hookVisibility?.warnings);
  addAdvisoryWarnings(campaignProfile ? blockingItems : warningItems, "watchability", results.watchability?.warnings);
  addAdvisoryWarnings(
    campaignProfile && requestedLayers.has("creativeQuality") ? blockingItems : warningItems,
    "creative",
    results.creativeQuality?.warnings
  );
  addAdvisoryWarnings(campaignProfile ? blockingItems : warningItems, "virality", results.virality?.warnings);
  addAdvisoryWarnings(campaignProfile ? blockingItems : warningItems, "video_analysis", results.videoAnalysis?.warnings);
  addAdvisoryWarnings(warningItems, "originality", results.multiAccountOriginalityAudit?.warnings);

  for (var [layer, verdict] of Object.entries(verdicts)) {
    if (campaignProfile && (layer === "pdq" || layer === "sscd")) {
      var detector = results[layer] || {};
      var stats = detector.stats || {};
      if (detector.available === false || detector.error) {
        addReadinessItem(
          fanoutDistinctness ? blockingItems : warningItems,
          layer + "_unavailable",
          layer + ": detector unavailable",
          layer.toUpperCase() + " detector unavailable"
        );
      } else if (fanoutDistinctness && (Number(stats.crossCollisions || 0) > 0 || Number(
        layer === "pdq" ? stats.crossSafeTargetViolations || 0 : stats.crossVariantSafeTargetViolations || 0
      ) > 0)) {
        addReadinessItem(
          blockingItems,
          layer + "_sibling_collision",
          layer + ": sibling collision detected",
          layer.toUpperCase() + " sibling collision detected"
        );
      } else if (verdict === "fail") {
        addReadinessItem(blockingItems, layer + "_failed", layer + ": detector threshold failed", layer + " failed");
      } else if (verdict === "warn") {
        addReadinessItem(warningItems, layer + "_review", layer + ": layer warning", layer + " needs review");
      }
      continue;
    }
    if (verdict === "fail" && REVIEW_ONLY_LAYERS.has(layer)) {
      addReadinessItem(warningItems, layer + "_review", layer + ": layer needs review", layer + " needs review");
    } else if (verdict === "fail" && !["forensics", "compression", "provenance", "safeZone", "readability", "cover", "hookVisibility", "watchability", "creativeQuality", "virality", "videoAnalysis", "originality"].includes(layer)) {
      addReadinessItem(blockingItems, layer + "_failed", layer + ": layer failed", layer + " failed");
    }
    if (verdict === "warn" && !["forensics", "compression", "provenance", "safeZone", "readability", "cover", "hookVisibility", "watchability", "creativeQuality", "virality", "videoAnalysis", "originality"].includes(layer)) {
      addReadinessItem(warningItems, layer + "_review", layer + ": layer warning", layer + " needs review");
    }
  }

  blockingReasons = blockingItems.map(function (item) { return item.message; });
  warnings = warningItems.map(function (item) { return item.message; });
  blockingReasons = uniqueMessages(blockingReasons);
  warnings = uniqueMessages(warnings);
  var blockingCodes = uniqueMessages(blockingItems.map(function (item) { return item.code; }));
  var warningCodes = uniqueMessages(warningItems.map(function (item) { return item.code; }));
  blockingItems = blockingItems.map(function (item) { return { ...item, operatorLabel: "blocking" }; });
  warningItems = warningItems.map(function (item) {
    return { ...item, operatorLabel: operatorLabelForWarningCode(item.code) };
  });
  var topWarnings = [...warningItems]
    .sort(function (a, b) { return warningPriority(a) - warningPriority(b); })
    .slice(0, 5);
  var uploadReady = blockingReasons.length === 0;
  var recommendedAction = !uploadReady ? "reject" : warnings.length > 0 ? "review" : "approve_candidate";
  var operatorLabels = operatorLabelGroups(blockingItems, warningItems);
  return {
    summaryText: !uploadReady
      ? "Blocked by " + blockingReasons.length + " audit issue(s)."
      : warnings.length > 0
        ? "Upload-ready candidate with " + warnings.length + " review warning(s)."
        : "Upload-ready candidate with no blocking audit issues.",
    blockingReasons,
    warnings,
    blockingCodes,
    warningCodes,
    topWarnings,
    operatorLabels,
    uploadReady,
    recommendedAction,
  };
}

async function runForensicCheck(outputDir, files, options = {}) {
  var auditProfile = options.auditProfile || "default";
  var sampleFiles = files.slice(0, 10); // Check first 10
  var fileReports = [];

  for (var fname of sampleFiles) {
    var fpath = path.join(outputDir, fname);
    var fileIssues = [];
    var metadata = null;
    var uploadReady = false;
    var signatureWarningAllowed = false;

    // Probe metadata
    var probe = await probeFile(fpath);
    if (probe) {
      var fmt = probe.format || {};
      var tags = fmt.tags || {};
      var videoStream = (probe.streams || []).find(s => s.codec_type === "video") || {};
      var audioStream = (probe.streams || []).find(s => s.codec_type === "audio") || {};
      var fext = path.extname(fname).toLowerCase();
      var isVideoFile = [".mp4", ".mov", ".webm"].includes(fext);
      var majorBrand = tags.major_brand || tags.MAJOR_BRAND || "";
      var creationTime = tags.creation_time || videoStream.tags?.creation_time || "";
      var vHandler = videoStream.tags?.handler_name || "";
      var aHandler = audioStream.tags?.handler_name || "";
      var faststart = isVideoFile ? await hasFaststart(fpath) : null;
      var width = videoStream.width || 0;
      var height = videoStream.height || 0;
      var videoCodec = videoStream.codec_name || "";
      var formatName = fmt.format_name || "";
      metadata = {
        videoCodec,
        width,
        height,
        formatName,
        majorBrand,
        faststart,
        creationTime,
        handlerName: vHandler,
        audioHandlerName: aHandler,
        audioCodec: audioStream.codec_name || "none",
        audioSampleRate: audioStream.sample_rate || null,
        encoder: tags.encoder || tags.ENCODER || "",
      };

      var isCampaignFactory = auditProfile === "campaign_factory_v1";
      var codecOk = videoCodec === "h264";
      var dimensionsOk = isVerticalSocialReady(width, height);
      var containerOk = isMp4Compatible(formatName, majorBrand);
      var creationOk = !isEpochCreationTime(creationTime);
      var handlerOk = vHandler !== "VideoHandler" && vHandler !== "SoundHandler";
      var audioOk = audioPolicyPasses(audioStream);
      uploadReady = isVideoFile && codecOk && dimensionsOk && containerOk && audioOk;
      signatureWarningAllowed = isCampaignFactory;

      if (isVideoFile && !codecOk) {
        addIssue(fileIssues, "critical", "video_codec", videoCodec || "missing", "Video codec must be H.264 for Campaign Factory upload readiness", "forensics_invalid_codec");
      }
      if (isVideoFile && !dimensionsOk) {
        addIssue(fileIssues, "high", "dimensions", width + "x" + height, "Video dimensions are not vertical/social-ready", "forensics_bad_dimensions");
      }
      if (isVideoFile && !containerOk) {
        addIssue(fileIssues, "high", "container", formatName || majorBrand || "unknown", "Container is not MP4/MOV-compatible", "forensics_invalid_container");
      }
      if (isVideoFile && !faststart) {
        addIssue(
          fileIssues,
          isCampaignFactory ? "warn" : "high",
          "faststart",
          "missing",
          "Streaming optimization missing",
          "forensics_missing_faststart",
          !isCampaignFactory
        );
      }
      if (isVideoFile && !creationOk) {
        addIssue(
          fileIssues,
          isCampaignFactory ? "warn" : "high",
          "creation_time",
          creationTime || "missing",
          "Missing or epoch creation timestamp",
          "forensics_missing_creation_time",
          !isCampaignFactory
        );
      }
      if (isVideoFile && !handlerOk) {
        addIssue(
          fileIssues,
          isCampaignFactory ? "warn" : "high",
          "handler_name",
          vHandler || "missing",
          "Generic video handler name detected",
          "forensics_default_handler_name",
          !isCampaignFactory
        );
      }
      if (isVideoFile && !audioOk) {
        addIssue(fileIssues, "high", "audio_policy", audioStream.codec_name || "unknown", "Audio is present but does not match expected AAC policy", "forensics_audio_policy");
      }
      if (isCampaignFactory && isVideoFile && !audioStream.codec_name) {
        addIssue(fileIssues, "warn", "audio", "missing", "No audio track present", "forensics_audio_missing", false);
      }

      // Check encoder string
      var encoder = metadata.encoder;
      if (/lavf|lavc|ffmpeg|x264|handbrake/i.test(encoder)) {
        var encoderIsBlocking = !signatureWarningAllowed;
        addIssue(
          fileIssues,
          encoderIsBlocking ? "critical" : "warn",
          "encoder",
          encoder,
          "FFmpeg/x264 encoder signature detected",
          "forensics_ffmpeg_signature",
          encoderIsBlocking
        );
      }

      // Check handler names
      if (vHandler && !/Core Media Video|VideoHandle/i.test(vHandler) && vHandler !== "VideoHandler") {
        // Non-standard but not FFmpeg default — could be ok
      }

      // Check bitrate
      var bitrate = parseInt(fmt.bit_rate || videoStream.bit_rate || 0);
      var bitrateKbps = Math.round(bitrate / 1000);
      if (bitrateKbps > 0 && bitrateKbps < 10000) {
        addIssue(fileIssues, "medium", "bitrate", bitrateKbps + " kbps", "Bitrate needs review", "forensics_bitrate_review", false);
      }

      // Check audio sample rate
      var audioRate = parseInt(audioStream.sample_rate || 0);
      if (audioRate > 0 && audioRate !== 44100 && audioRate !== 48000) {
        addIssue(fileIssues, "low", "audio_rate", audioRate + " Hz", "Non-standard audio sample rate", "forensics_audio_sample_rate", false);
      }
    } else if (VIDEO_EXTS.includes(path.extname(fname).toLowerCase())) {
      addIssue(fileIssues, "critical", "media", "unreadable", "Video is corrupt or unreadable", "invalid_video", true);
    }

    // Check for telltale strings in binary
    var strOutput = await checkStrings(fpath);
    if (/x264|Lavf|Lavc|ffmpeg/i.test(strOutput)) {
      var matched = [];
      if (/x264/i.test(strOutput)) matched.push("x264");
      if (/Lavf/i.test(strOutput)) matched.push("Lavf");
      if (/Lavc/i.test(strOutput)) matched.push("Lavc");
      var binaryStringsBlocking = !signatureWarningAllowed;
      addIssue(
        fileIssues,
        binaryStringsBlocking ? "critical" : "warn",
        "binary_strings",
        matched.join(", "),
        "Encoder signatures found in binary data (SEI/container)",
        "forensics_binary_signature",
        binaryStringsBlocking
      );
    }

    var score = fileScore(fileIssues);
    fileReports.push({
      name: fname,
      metadata,
      uploadReady,
      issues: fileIssues,
      score,
    });
  }

  // Cross-variant correlation check
  var crossCorrelation = { checked: false };
  if (sampleFiles.length >= 3) {
    var probes = [];
    for (var fname of sampleFiles.slice(0, 5)) {
      var p = await probeFile(path.join(outputDir, fname));
      if (p) probes.push(p);
    }
    if (probes.length >= 3) {
      var bitrates = probes.map(p => parseInt(p.format?.bit_rate || 0)).filter(b => b > 0);
      var bitrateRange = bitrates.length > 1 ? Math.max(...bitrates) - Math.min(...bitrates) : 0;
      var bitrateVariation = bitrates.length > 1 ? Math.round((bitrateRange / (bitrates.reduce((a, b) => a + b, 0) / bitrates.length)) * 100) : 0;

      crossCorrelation = {
        checked: true,
        bitrateVariation: bitrateVariation + "%",
        tooUniform: bitrateVariation < 5,
        msg: bitrateVariation < 5
          ? "Variants have nearly identical bitrates — looks like batch processing"
          : "Good bitrate diversity across variants"
      };
    }
  }

  // Summary
  var criticalCount = fileReports.filter(r => r.score === "fail").length;
  var warnCount = fileReports.filter(r => r.score === "warn").length;

  return {
    fileReports,
    crossCorrelation,
    stats: {
      filesChecked: fileReports.length,
      critical: criticalCount,
      warnings: warnCount,
      clean: fileReports.filter(r => r.score === "pass").length,
      overallScore: criticalCount > 0 ? "fail" : warnCount > 0 ? "warn" : "pass",
    }
  };
}

function buildAudioFitSignals(results, files) {
  var tags = [];
  var reasons = [];
  var creative = results.creativeQuality || {};
  var creativeWarnings = Array.isArray(creative.warnings) ? creative.warnings : [];
  if (creative.verdict === "pass") {
    tags.push("polished");
    reasons.push("Creative quality checks passed");
  }
  if (creativeWarnings.some(function (warning) { return /hook|caption/i.test(warning.code || warning.message || ""); })) {
    tags.push("hook_driven");
    reasons.push("Caption or hook warnings are present");
  }
  if (creativeWarnings.some(function (warning) { return /cover|visibility/i.test(warning.code || warning.message || ""); })) {
    tags.push("visual_first");
    reasons.push("Cover or visibility checks are active");
  }
  if (results.audio?.available === false) {
    tags.push("silent_draft");
    reasons.push("No final audio was detected in the draft");
  }
  if (files.length > 1) tags.push("batch_variant");
  return {
    schema: "contentforge.audio_fit_signals.v1",
    scoringEnabled: false,
    advisoryOnly: true,
    variantTags: [...new Set(tags)],
    reasons,
    note: "Tags are for Campaign Factory audio matching context only; ContentForge is not scoring audio fit yet.",
  };
}

function verdictCode(layer, verdict) {
  if (layer === "safeZone") return "safe_zone_" + (verdict || "unknown");
  if (layer === "readability") {
    if (verdict === "pass") return "caption_readable";
    if (verdict === "fail") return "caption_unreadable";
    return "caption_review";
  }
  if (layer === "cover") return "cover_" + (verdict || "unknown");
  if (layer === "hookVisibility") return "hook_" + (verdict || "unknown");
  if (layer === "creativeQuality") return "creative_quality_" + (verdict || "unknown");
  if (layer === "virality") return "virality_" + (verdict || "unknown");
  if (layer === "videoAnalysis") return "video_analysis_" + (verdict || "unknown");
  if (layer === "originality") return "originality_" + (verdict || "unknown");
  return layer + "_" + (verdict || "unknown");
}

// ─── Layer 4: Compression Forensics (DCT analysis, GOP periodicity, encoder fingerprints) ───
function runCompressionForensics(outputDir) {
  return runPythonJson("forensics_check.py", [outputDir, "10"], {
    layer: "compression",
    timeout: 60000,
    fallback: { reports: [], summary: { total: 0, passed: 0, failed: 0, warnings: 1, unavailable: 1 } },
  });
}

// ─── Layer 5: C2PA/IPTC AI Provenance Detection ───
function runProvenanceCheck(outputDir) {
  return runPythonJson("provenance_check.py", [outputDir, "20"], {
    layer: "provenance",
    timeout: 30000,
    fallback: { results: [], summary: { total: 0, flagged: 0, clean: 0, unavailable: 1 } },
  });
}

async function timeLayer(name, timings, fn) {
  var startedAt = Date.now();
  try {
    return await fn();
  } finally {
    timings.layersMs[name] = Date.now() - startedAt;
  }
}

function firstLineVersion(command, args) {
  var key = command + " " + args.join(" ");
  if (versionCache.has(key)) return versionCache.get(key);
  var promise = new Promise((resolve) => {
    execFile(command, args, { timeout: 5000, maxBuffer: 256 * 1024 }, (err, stdout, stderr) => {
      if (err) {
        resolve(null);
        return;
      }
      resolve(((stdout || stderr || "").split(/\r?\n/)[0] || "").trim() || null);
    });
  });
  versionCache.set(key, promise);
  return promise;
}

async function timeOperation(metrics, key, fn) {
  var startedAt = Date.now();
  try {
    return await fn();
  } finally {
    metrics[key] = (metrics[key] || 0) + (Date.now() - startedAt);
  }
}

// ─── Layer 6: Reference Database (FAISS cross-batch comparison) ───
function runReferenceQuery(outputDir) {
  return runPythonJson("reference_db.py", ["query", outputDir, "30"], {
    layer: "reference",
    timeout: 120000,
    fallback: { results: [], stats: {} },
  });
}

// ─── Layer 7: Temporal PDQ (TMK Level 1 approximation for video) ───
function runTemporalPDQ(sourcePath, outputDir) {
  return runPythonJson("temporal_pdq.py", [sourcePath, outputDir, "20"], {
    layer: "temporal",
    timeout: 180000,
    fallback: { available: false, reason: "Temporal analysis unavailable" },
  });
}

// ─── Layer 8: SSIM (Visual Quality Indicator) ───
function runSSIM(sourcePath, variantPath, isVideo) {
  return new Promise((resolve) => {
    var filters = isVideo
      ? "[0:v]trim=start=0:end=0.1,setpts=PTS-STARTPTS,scale=256:256:flags=lanczos,format=yuv420p[a];" +
        "[1:v]trim=start=0:end=0.1,setpts=PTS-STARTPTS,scale=256:256:flags=lanczos,format=yuv420p[b];" +
        "[a][b]ssim"
      : "[0:v]scale=256:256:flags=lanczos,format=yuv420p[a];" +
        "[1:v]scale=256:256:flags=lanczos,format=yuv420p[b];" +
        "[a][b]ssim";

    execFile("ffmpeg", ["-i", sourcePath, "-i", variantPath, "-lavfi", filters, "-f", "null", "-"],
      { timeout: 15000, maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
        var combined = (stdout || "") + "\n" + (stderr || "");
        var match = combined.match(/All:([\d.]+)/);
        resolve(match ? parseFloat(match[1]) : null);
      });
  });
}

async function runSSIMCheck(sourcePath, outputDir, files) {
  var srcExt = path.extname(sourcePath).toLowerCase();
  var isVideo = VIDEO_EXTS.includes(srcExt);
  var checkFiles = files.slice(0, 20);
  var results = [];

  for (var i = 0; i < checkFiles.length; i += 5) {
    var batch = checkFiles.slice(i, i + 5);
    var batchResults = await Promise.all(batch.map(async (fname) => {
      var ssim = await runSSIM(sourcePath, path.join(outputDir, fname), isVideo);
      return { name: fname, ssim, quality: ssim !== null ? (ssim >= 0.90 ? "good" : ssim >= 0.80 ? "acceptable" : "degraded") : null };
    }));
    results.push(...batchResults);
  }

  var valid = results.filter(r => r.ssim !== null).map(r => r.ssim);
  return {
    results,
    stats: {
      avg: valid.length > 0 ? Math.round((valid.reduce((a, b) => a + b, 0) / valid.length) * 1000) / 1000 : null,
      min: valid.length > 0 ? Math.round(Math.min(...valid) * 1000) / 1000 : null,
      max: valid.length > 0 ? Math.round(Math.max(...valid) * 1000) / 1000 : null,
    }
  };
}

// ─── V1.1 Advisory Reel Signals: caption readability, safe zones, covers, opening hook ───
function extractFrame(filePath, timeSec, width = 180, height = 320) {
  return new Promise((resolve) => {
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
    }, (err, stdout) => {
      if (err || !stdout || stdout.length < width * height * 3) {
        resolve(null);
        return;
      }
      resolve({ width, height, data: stdout.subarray(0, width * height * 3), timeSec });
    });
  });
}

function extractFramePng(filePath, timeSec, width = 360, height = 640) {
  return new Promise((resolve) => {
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
    }, (err, stdout) => {
      if (err || !stdout || stdout.length < 100) {
        resolve(null);
        return;
      }
      resolve({ width, height, data: stdout, timeSec });
    });
  });
}

function parseTesseractTsv(tsv, frame, file, timeSec) {
  var lines = (tsv || "").trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  var headers = lines[0].split("\t");
  var index = Object.fromEntries(headers.map((name, i) => [name, i]));
  var boxes = [];
  for (var line of lines.slice(1)) {
    var parts = line.split("\t");
    var text = (parts[index.text] || "").trim();
    var confidence = Number.parseFloat(parts[index.conf] || "-1");
    if (!text || !Number.isFinite(confidence) || confidence < 25) continue;
    var left = Number.parseFloat(parts[index.left] || "0");
    var top = Number.parseFloat(parts[index.top] || "0");
    var width = Number.parseFloat(parts[index.width] || "0");
    var height = Number.parseFloat(parts[index.height] || "0");
    if (width <= 0 || height <= 0) continue;
    boxes.push({
      file,
      timeSec: Math.round(timeSec * 10) / 10,
      ocrText: text,
      confidence: Math.round(confidence),
      preprocessing: frame.preprocessing || "original",
      box: {
        x: Math.round(left),
        y: Math.round(top),
        w: Math.round(width),
        h: Math.round(height),
      },
      frame: {
        width: frame.width,
        height: frame.height,
      },
    });
  }
  return boxes;
}

function scaleOcrBoxes(boxes, variant, originalFrame) {
  var scaleX = originalFrame.width / Math.max(1, variant.width);
  var scaleY = originalFrame.height / Math.max(1, variant.height);
  return boxes.map(function (box) {
    return {
      ...box,
      box: {
        x: Math.round(box.box.x * scaleX),
        y: Math.round(box.box.y * scaleY),
        w: Math.round(box.box.w * scaleX),
        h: Math.round(box.box.h * scaleY),
      },
      frame: {
        width: originalFrame.width,
        height: originalFrame.height,
      },
    };
  });
}

function boxIou(a, b) {
  var ax1 = a.box.x;
  var ay1 = a.box.y;
  var ax2 = a.box.x + a.box.w;
  var ay2 = a.box.y + a.box.h;
  var bx1 = b.box.x;
  var by1 = b.box.y;
  var bx2 = b.box.x + b.box.w;
  var by2 = b.box.y + b.box.h;
  var ix1 = Math.max(ax1, bx1);
  var iy1 = Math.max(ay1, by1);
  var ix2 = Math.min(ax2, bx2);
  var iy2 = Math.min(ay2, by2);
  var iw = Math.max(0, ix2 - ix1);
  var ih = Math.max(0, iy2 - iy1);
  var intersection = iw * ih;
  var union = (a.box.w * a.box.h) + (b.box.w * b.box.h) - intersection;
  return union > 0 ? intersection / union : 0;
}

function mergeOcrBoxes(boxes) {
  var merged = [];
  var sorted = [...boxes].sort(function (a, b) { return (b.confidence || 0) - (a.confidence || 0); });
  for (var box of sorted) {
    var matchIndex = merged.findIndex(function (item) {
      return boxIou(item, box) >= 0.45 ||
        (item.ocrText.toLowerCase() === box.ocrText.toLowerCase() && boxIou(item, box) >= 0.20);
    });
    if (matchIndex < 0) {
      merged.push(box);
      continue;
    }
    var existing = merged[matchIndex];
    if ((box.confidence || 0) > (existing.confidence || 0)) {
      merged[matchIndex] = box;
    }
  }
  return merged.sort(function (a, b) {
    return a.box.y === b.box.y ? a.box.x - b.box.x : a.box.y - b.box.y;
  });
}

async function ocrFrameVariants(pngFrame) {
  var base = sharp(pngFrame.data);
  var width2x = pngFrame.width * 2;
  var height2x = pngFrame.height * 2;
  var variants = [
    { name: "original", width: pngFrame.width, height: pngFrame.height, data: pngFrame.data },
  ];
  try {
    var enhanced = await base
      .clone()
      .resize(width2x, height2x, { kernel: sharp.kernel.lanczos3 })
      .grayscale()
      .normalize()
      .sharpen()
      .png()
      .toBuffer();
    variants.push({ name: "enhanced_2x", width: width2x, height: height2x, data: enhanced });
  } catch {
    // Keep OCR advisory. If preprocessing fails, the original frame still runs.
  }
  try {
    var threshold = await base
      .clone()
      .resize(width2x, height2x, { kernel: sharp.kernel.lanczos3 })
      .grayscale()
      .normalize()
      .threshold(145)
      .png()
      .toBuffer();
    variants.push({ name: "threshold_2x", width: width2x, height: height2x, data: threshold });
  } catch {
    // Keep OCR advisory. If preprocessing fails, the original frame still runs.
  }
  return variants;
}

async function runTesseractOnVariant(tempDir, variant, file, timeSec) {
  var imagePath = path.join(tempDir, "frame-" + variant.name + ".png");
  await writeFile(imagePath, variant.data);
  return await new Promise((resolve) => {
    execFile("tesseract", [imagePath, "stdout", "--psm", "6", "tsv"], {
      timeout: 15000,
      maxBuffer: 2 * 1024 * 1024,
    }, (err, stdout, stderr) => {
      if (err) {
        resolve({
          available: false,
          error: (stderr || err.message || "tesseract failed").slice(0, 500),
          boxes: [],
        });
        return;
      }
      resolve({
        available: true,
        boxes: parseTesseractTsv(stdout, variant, file, timeSec),
      });
    });
  });
}

async function runTesseractOcr(pngFrame, file, timeSec) {
  var tempDir = await mkdtemp(path.join(tmpdir(), "contentforge-ocr-"));
  try {
    var engineVersion = await firstLineVersion("tesseract", ["--version"]);
    var variants = await ocrFrameVariants(pngFrame);
    var allBoxes = [];
    var errors = [];
    var successfulVariants = 0;
    for (var variant of variants) {
      var result = await runTesseractOnVariant(tempDir, variant, file, timeSec);
      if (result.available === false) {
        errors.push(variant.name + ": " + (result.error || "failed"));
        continue;
      }
      successfulVariants++;
      allBoxes.push(...scaleOcrBoxes(result.boxes, variant, pngFrame));
    }
    if (!successfulVariants) {
      return {
        available: false,
        error: errors.join("; ") || "tesseract failed",
        boxes: [],
      };
    }
    var mergedBoxes = mergeOcrBoxes(allBoxes);
    return {
      available: true,
      engine: "tesseract",
      engineVersion,
      preprocessing: variants.map((variant) => variant.name),
      boxesBeforeMerge: allBoxes.length,
      boxes: mergedBoxes,
    };
  } finally {
    await rm(tempDir, { recursive: true, force: true }).catch(function () {});
  }
}

async function runAppleVisionOcr(pngFrame, file, timeSec) {
  var tempDir = await mkdtemp(path.join(tmpdir(), "contentforge-vision-"));
  var imagePath = path.join(tempDir, "frame.png");
  var scriptPath = process.env.CONTENTFORGE_APPLE_VISION_SCRIPT ||
    path.join(process.cwd(), "scripts", "apple-vision-ocr.swift");
  try {
    await writeFile(imagePath, pngFrame.data);
    return await new Promise((resolve) => {
      execFile("swift", [scriptPath, imagePath], {
        timeout: 20000,
        maxBuffer: 2 * 1024 * 1024,
      }, (err, stdout, stderr) => {
        if (err) {
          resolve({
            available: false,
            engine: "apple_vision",
            error: (stderr || err.message || "apple vision failed").slice(0, 500),
            boxes: [],
          });
          return;
        }
        var parsed = parseJsonOutput(stdout, null);
        if (!parsed || parsed.available === false) {
          resolve({
            available: false,
            engine: "apple_vision",
            error: parsed?.error || "Apple Vision output parse failed",
            boxes: [],
          });
          return;
        }
        var boxes = (parsed.boxes || []).map(function (box) {
          return {
            file,
            timeSec: Math.round(timeSec * 10) / 10,
            ocrText: box.ocrText || "",
            confidence: Math.round(box.confidence || 0),
            box: box.box || { x: 0, y: 0, w: 0, h: 0 },
            frame: box.frame || { width: pngFrame.width, height: pngFrame.height },
          };
        }).filter(function (box) {
          return box.ocrText && box.box.w > 0 && box.box.h > 0 && box.confidence >= 25;
        });
        resolve({
          available: true,
          engine: "apple_vision",
          engineVersion: parsed.engineVersion || "Vision",
          preprocessing: ["original"],
          boxesBeforeMerge: boxes.length,
          boxes,
        });
      });
    });
  } finally {
    await rm(tempDir, { recursive: true, force: true }).catch(function () {});
  }
}

function ocrEngineOrder(requested) {
  if (!OCR_ENGINE_CHOICES.has(requested)) return [];
  if (requested === "auto") return ["apple_vision", "tesseract"];
  if (requested === "heuristic") return [];
  return [requested];
}

async function runSelectedOcr(pngFrame, file, timeSec) {
  var requestedEngine = (process.env.CONTENTFORGE_OCR_ENGINE || "auto").toLowerCase();
  if (requestedEngine === "heuristic") {
    return {
      available: false,
      requestedEngine,
      engine: "heuristic",
      engineVersion: null,
      fallbackUsed: true,
      fallbackReason: "OCR engine set to heuristic; using frame-analysis fallback only",
      error: "OCR engine set to heuristic",
      boxes: [],
    };
  }
  var order = ocrEngineOrder(requestedEngine);
  if (!order.length) {
    return {
      available: false,
      requestedEngine,
      engine: null,
      engineVersion: null,
      fallbackUsed: false,
      fallbackReason: "Unsupported OCR engine: " + requestedEngine,
      error: "Unsupported OCR engine: " + requestedEngine,
      boxes: [],
    };
  }

  var errors = [];
  for (var i = 0; i < order.length; i++) {
    var engine = order[i];
    var result = engine === "apple_vision"
      ? await runAppleVisionOcr(pngFrame, file, timeSec)
      : await runTesseractOcr(pngFrame, file, timeSec);
    if (result.available !== false) {
      return {
        ...result,
        requestedEngine,
        boxesBeforeMerge: result.boxesBeforeMerge ?? result.boxes?.length ?? 0,
        fallbackUsed: i > 0,
        fallbackReason: i > 0 ? errors.join("; ") : null,
      };
    }
    errors.push(engine + ": " + (result.error || result.reason || "unavailable"));
  }

  return {
    available: false,
    requestedEngine,
    engine: null,
    engineVersion: null,
    fallbackUsed: order.length > 1,
    fallbackReason: errors.join("; "),
    error: errors.join("; "),
    boxes: [],
  };
}

function lumaAt(frame, x, y) {
  var idx = ((y * frame.width) + x) * 3;
  return (0.2126 * frame.data[idx]) + (0.7152 * frame.data[idx + 1]) + (0.0722 * frame.data[idx + 2]);
}

function regionContrast(frame, box) {
  var scaleX = frame.width / Math.max(1, box.frame?.width || frame.width);
  var scaleY = frame.height / Math.max(1, box.frame?.height || frame.height);
  var x0 = Math.max(0, Math.floor(box.box.x * scaleX));
  var y0 = Math.max(0, Math.floor(box.box.y * scaleY));
  var x1 = Math.min(frame.width - 1, Math.ceil((box.box.x + box.box.w) * scaleX));
  var y1 = Math.min(frame.height - 1, Math.ceil((box.box.y + box.box.h) * scaleY));
  var min = 255;
  var max = 0;
  var samples = 0;
  for (var y = y0; y <= y1; y += 2) {
    for (var x = x0; x <= x1; x += 2) {
      var l = lumaAt(frame, x, y);
      min = Math.min(min, l);
      max = Math.max(max, l);
      samples++;
    }
  }
  return samples ? Math.round(max - min) : null;
}

function frameStats(frame) {
  var total = 0;
  var totalSq = 0;
  var count = frame.width * frame.height;
  var edgeTotal = 0;
  for (var y = 1; y < frame.height - 1; y += 2) {
    for (var x = 1; x < frame.width - 1; x += 2) {
      var l = lumaAt(frame, x, y);
      total += l;
      totalSq += l * l;
      edgeTotal += Math.abs(l - lumaAt(frame, x + 1, y)) + Math.abs(l - lumaAt(frame, x, y + 1));
    }
  }
  var sampled = Math.max(1, Math.floor((frame.width - 2) / 2) * Math.floor((frame.height - 2) / 2));
  var mean = total / sampled;
  var variance = Math.max(0, (totalSq / sampled) - (mean * mean));
  return {
    brightness: Math.round(mean),
    contrast: Math.round(Math.sqrt(variance)),
    edgeScore: Math.round(edgeTotal / sampled),
    fullPixelCount: count,
  };
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

function componentBoxes(cells, cols, rows, cellW, cellH) {
  var seen = new Set();
  var boxes = [];
  function key(cx, cy) { return cx + "," + cy; }
  for (var cy = 0; cy < rows; cy++) {
    for (var cx = 0; cx < cols; cx++) {
      var start = key(cx, cy);
      if (!cells.has(start) || seen.has(start)) continue;
      var stack = [[cx, cy]];
      var minX = cx;
      var maxX = cx;
      var minY = cy;
      var maxY = cy;
      var count = 0;
      seen.add(start);
      while (stack.length) {
        var [x, y] = stack.pop();
        count++;
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
        for (var [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {
          var nk = key(nx, ny);
          if (nx < 0 || ny < 0 || nx >= cols || ny >= rows || seen.has(nk) || !cells.has(nk)) continue;
          seen.add(nk);
          stack.push([nx, ny]);
        }
      }
      if (count >= 2) {
        boxes.push({
          x: minX * cellW,
          y: minY * cellH,
          w: ((maxX - minX) + 1) * cellW,
          h: ((maxY - minY) + 1) * cellH,
          cells: count,
        });
      }
    }
  }
  return boxes;
}

function detectTextLikeBoxes(frame) {
  var cols = 24;
  var rows = 40;
  var cellW = frame.width / cols;
  var cellH = frame.height / rows;
  var active = new Set();
  var contrasts = [];
  for (var cy = 0; cy < rows; cy++) {
    for (var cx = 0; cx < cols; cx++) {
      var min = 255;
      var max = 0;
      var edge = 0;
      var samples = 0;
      var x0 = Math.floor(cx * cellW);
      var y0 = Math.floor(cy * cellH);
      var x1 = Math.min(frame.width - 2, Math.floor((cx + 1) * cellW));
      var y1 = Math.min(frame.height - 2, Math.floor((cy + 1) * cellH));
      for (var y = y0; y < y1; y += 2) {
        for (var x = x0; x < x1; x += 2) {
          var l = lumaAt(frame, x, y);
          min = Math.min(min, l);
          max = Math.max(max, l);
          edge += Math.abs(l - lumaAt(frame, x + 1, y)) + Math.abs(l - lumaAt(frame, x, y + 1));
          samples++;
        }
      }
      var contrast = max - min;
      var edgeScore = samples ? edge / samples : 0;
      if (contrast >= 55 && edgeScore >= 12) {
        active.add(cx + "," + cy);
        contrasts.push(contrast);
      }
    }
  }
  var boxes = componentBoxes(active, cols, rows, cellW, cellH)
    .filter(function (box) {
      return box.w >= frame.width * 0.08 && box.h >= frame.height * 0.018 && box.w <= frame.width * 0.95;
    })
    .map(function (box) {
      return {
        x: Math.round(box.x),
        y: Math.round(box.y),
        w: Math.round(box.w),
        h: Math.round(box.h),
        cells: box.cells,
      };
    });
  return {
    boxes,
    avgContrast: contrasts.length ? Math.round(contrasts.reduce((a, b) => a + b, 0) / contrasts.length) : 0,
  };
}

function textBoxSafeZoneIssues(box, frame) {
  var thresholds = campaignFactoryThresholds();
  var issues = [];
  var x = box.box ? box.box.x : box.x;
  var y = box.box ? box.box.y : box.y;
  var w = box.box ? box.box.w : box.w;
  var h = box.box ? box.box.h : box.h;
  var frameWidth = box.frame?.width || frame.width;
  var frameHeight = box.frame?.height || frame.height;
  var x1 = x;
  var y1 = y;
  var x2 = x + w;
  var y2 = y + h;
  if (x1 < frameWidth * thresholds.captionEdgeMarginRatio || x2 > frameWidth * (1 - thresholds.captionEdgeMarginRatio)) issues.push("caption_too_close_to_edge");
  if (x2 > frameWidth * thresholds.rightUiStartRatio && y2 > frameHeight * thresholds.rightUiMinYRatio) issues.push("caption_overlaps_ui_safe_zone");
  if (y2 > frameHeight * thresholds.bottomUiStartRatio || y1 < frameHeight * thresholds.topUiEndRatio) issues.push("caption_overlaps_ui_safe_zone");
  return issues;
}

function advisoryWarning(code, label, message, severity = "warn") {
  return { code, label, message, severity };
}

function plausibleOcrBox(box) {
  var textLength = String(box.ocrText || "").replace(/[^a-z0-9]/gi, "").length;
  var frameWidth = Math.max(1, Number(box.frame?.width || 0));
  var frameHeight = Math.max(1, Number(box.frame?.height || 0));
  var width = Math.max(0, Number(box.box?.w || 0));
  var height = Math.max(0, Number(box.box?.h || 0));
  var areaRatio = (width * height) / (frameWidth * frameHeight);
  var heightRatio = height / frameHeight;
  var confidence = Number(box.confidence || 0);
  var highConfidenceSmallText = textLength >= 3 && heightRatio >= 0.008 && confidence >= 90;
  var readableScale = heightRatio >= 0.035 ||
    (heightRatio >= 0.015 && confidence >= 55) ||
    highConfidenceSmallText;
  return textLength >= 2 && readableScale && areaRatio <= 0.65 && heightRatio <= 0.50;
}

function plausibleHeuristicCaptionBox(box, frame) {
  var widthRatio = box.w / Math.max(1, frame.width);
  var heightRatio = box.h / Math.max(1, frame.height);
  var aspectRatio = box.w / Math.max(1, box.h);
  return box.cells >= 30 && widthRatio >= 0.25 && widthRatio <= 0.90 && heightRatio >= 0.015 && heightRatio <= 0.12 && aspectRatio >= 3;
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

function finiteNumber(value) {
  var number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function buildWatchabilityWarnings({ qualityMetrics = {}, qaSignals = {}, fileName = "target", thresholds = campaignFactoryThresholds() } = {}) {
  var warnings = [];
  var vmaf = finiteNumber(qualityMetrics.vmaf);
  var ssim = finiteNumber(qualityMetrics.ssim);
  var psnr = finiteNumber(qualityMetrics.psnr);
  var referenceMetricsPass = (ssim !== null && ssim >= 0.70) || (psnr !== null && psnr >= 18);
  if (vmaf !== null && vmaf < thresholds.minVmaf && !referenceMetricsPass) {
    warnings.push(advisoryWarning("video_vmaf_low", "Low VMAF score", fileName + ": VMAF " + vmaf + " is below " + thresholds.minVmaf));
  }

  var cambi = finiteNumber(qualityMetrics.cambi?.value ?? qualityMetrics.cambi);
  if (cambi !== null && cambi > thresholds.maxCambi) {
    warnings.push(advisoryWarning("video_cambi_banding", "Banding risk detected", fileName + ": CAMBI " + cambi + " is above " + thresholds.maxCambi));
  }

  var loudness = qaSignals.loudness || {};
  var integratedLufs = finiteNumber(loudness.inputI);
  if (integratedLufs !== null && (integratedLufs < thresholds.minIntegratedLufs || integratedLufs > thresholds.maxIntegratedLufs)) {
    warnings.push(advisoryWarning("audio_loudness_out_of_range", "Audio loudness outside target range", fileName + ": integrated loudness " + integratedLufs + " LUFS is outside " + thresholds.minIntegratedLufs + " to " + thresholds.maxIntegratedLufs));
  }
  var truePeak = finiteNumber(loudness.inputTp);
  if (truePeak !== null && truePeak > thresholds.maxTruePeakDb) {
    warnings.push(advisoryWarning("audio_true_peak_too_hot", "Audio true peak is too hot", fileName + ": true peak " + truePeak + " dB exceeds " + thresholds.maxTruePeakDb));
  }

  for (var warningText of qaSignals.warnings || []) {
    if (/black segment/i.test(warningText)) {
      warnings.push(advisoryWarning("watchability_black_segment", "Long black segment detected", fileName + ": " + warningText));
    } else if (/silence/i.test(warningText)) {
      warnings.push(advisoryWarning("audio_long_silence", "Long silence detected", fileName + ": " + warningText));
    } else if (/letterbox|border/i.test(warningText)) {
      warnings.push(advisoryWarning("framing_letterbox_or_crop", "Possible letterbox or border detected", fileName + ": " + warningText));
    }
  }

  return uniqueWarnings(warnings);
}

async function runReelAdvisoryAudit(outputDir, files, sourcePath = null) {
  var startedAt = Date.now();
  var thresholds = campaignFactoryThresholds();
  var videoFiles = files.filter(f => VIDEO_EXTS.includes(path.extname(f).toLowerCase())).slice(0, CAMPAIGN_FACTORY_AUDIT_CONFIG.sampling.maxVideos);
  var safeWarnings = [];
  var readabilityWarnings = [];
  var hookWarnings = [];
  var watchabilityWarnings = [];
  var watchabilityItems = [];
  var coverWarnings = [];
  var coverCandidates = [];
  var ocrResults = [];
  var captionBoxes = [];
  var ocrAvailable = null;
  var ocrError = null;
  var ocrSuccessCount = 0;
  var ocrFailureCount = 0;
  var ocrEngine = null;
  var ocrEngineVersion = null;
  var ocrFallbackUsed = false;
  var ocrFallbackReason = null;
  var ocrConfidenceValues = [];
  var ocrPreprocessing = new Set();
  var ocrBoxesBeforeMerge = 0;
  var frameSamples = 0;
  var textBoxesDetected = 0;
  var ocrTextBoxesDetected = 0;
  var lowContrastBoxes = 0;
  var smallCaptionBoxes = 0;
  var unsafeBoxes = 0;
  var heuristicCaptionBoxes = [];
  var rawHeuristicBoxes = [];
  var earlyTextBoxes = 0;
  var deltas = [];
  var timingMetrics = {
    frameExtractionMs: 0,
    ocrMs: 0,
    coverFrameExtractionMs: 0,
  };

  for (var fname of videoFiles) {
    var filePath = path.join(outputDir, fname);
    var probe = await probeFile(filePath);
    var duration = Number.parseFloat(probe?.format?.duration || "0");
    var videoStream = (probe?.streams || []).find(function (stream) { return stream.codec_type === "video"; }) || {};
    var mediaInfo = {
      width: Number.parseInt(videoStream.width || 0, 10),
      height: Number.parseInt(videoStream.height || 0, 10),
      bitrate: Number.parseInt(probe?.format?.bit_rate || videoStream.bit_rate || 0, 10),
      duration,
    };
    var qualityMetrics = sourcePath
      ? await getQualityMetrics({ sourcePath, variantPath: filePath, mediaInfo }).catch(function (error) {
        return { available: false, reason: error.message || "quality metrics unavailable" };
      })
      : { available: false, reason: "Source file unavailable for reference metrics" };
    var qaSignals = await getQaSignals(filePath, mediaInfo).catch(function (error) {
      return { available: false, reason: error.message || "watchability signals unavailable", warnings: [] };
    });
    var fileWatchabilityWarnings = buildWatchabilityWarnings({
      qualityMetrics,
      qaSignals,
      fileName: fname,
      thresholds,
    });
    watchabilityWarnings.push(...fileWatchabilityWarnings);
    watchabilityItems.push({
      file: fname,
      qualityMetrics,
      qaSignals,
      warnings: fileWatchabilityWarnings,
    });
    var times = CAMPAIGN_FACTORY_AUDIT_CONFIG.sampling.ocrFrameTimesSec.filter(function (time) { return !duration || time < duration; });
    if (times.length === 0) times = [0];
    var frames = [];
    for (var time of times) {
      var frame = await timeOperation(timingMetrics, "frameExtractionMs", function () { return extractFrame(filePath, time); });
      if (frame) frames.push(frame);
    }
    frameSamples += frames.length;

    var previous = null;
    for (var frame of frames) {
      var pngFrame = await timeOperation(timingMetrics, "frameExtractionMs", function () { return extractFramePng(filePath, frame.timeSec); });
      var ocrFrameResult = pngFrame
        ? await timeOperation(timingMetrics, "ocrMs", function () { return runSelectedOcr(pngFrame, fname, frame.timeSec); })
        : { available: false, requestedEngine: process.env.CONTENTFORGE_OCR_ENGINE || "auto", engine: null, error: "frame extraction failed", boxes: [] };
      if (ocrFrameResult.available === false) {
        ocrFailureCount++;
        ocrError = ocrFrameResult.error || ocrError;
      } else {
        ocrSuccessCount++;
        ocrEngine = ocrFrameResult.engine || ocrEngine;
        ocrEngineVersion = ocrFrameResult.engineVersion || ocrEngineVersion;
      }
      if (ocrFrameResult.fallbackUsed) ocrFallbackUsed = true;
      if (ocrFrameResult.fallbackReason && !ocrFallbackReason) ocrFallbackReason = ocrFrameResult.fallbackReason;
      for (var method of ocrFrameResult.preprocessing || []) ocrPreprocessing.add(method);
      ocrBoxesBeforeMerge += ocrFrameResult.boxesBeforeMerge ?? ocrFrameResult.boxes?.length ?? 0;
      var plausibleBoxes = (ocrFrameResult.boxes || []).filter(plausibleOcrBox);
      var plausibleConfidence = plausibleBoxes.length
        ? plausibleBoxes.reduce(function (sum, box) { return sum + (box.confidence || 0); }, 0) / plausibleBoxes.length
        : null;
      if (plausibleBoxes.length > 12 && plausibleConfidence < 60) plausibleBoxes = [];
      var frameOcrBoxes = plausibleBoxes.map(function (box) {
        var contrast = regionContrast(frame, box);
        var safeZoneIssues = textBoxSafeZoneIssues(box, frame);
        var frameHeight = Math.max(1, box.frame?.height || frame.height || 1);
        var fontHeightRatio = Math.max(0, (box.box?.h || 0) / frameHeight);
        var fontSizeScore = Math.max(0, Math.min(100, Math.round((fontHeightRatio / thresholds.captionMinHeightRatio) * 100)));
        if (Number.isFinite(box.confidence)) ocrConfidenceValues.push(box.confidence);
        return {
          ...box,
          contrast,
          fontHeightRatio: Math.round(fontHeightRatio * 1000) / 1000,
          fontSizeScore,
          readabilityScore: Math.max(0, Math.min(100, Math.round(((box.confidence || 0) * 0.55) + ((contrast || 0) * 0.25) + (fontSizeScore * 0.2)))),
          safeZoneOverlap: safeZoneIssues,
        };
      });
      captionBoxes.push(...frameOcrBoxes);
      ocrTextBoxesDetected += frameOcrBoxes.length;
      ocrResults.push({
        file: fname,
        timeSec: Math.round(frame.timeSec * 10) / 10,
        available: ocrFrameResult.available !== false,
        engine: ocrFrameResult.engine || null,
        engineVersion: ocrFrameResult.engineVersion || null,
        preprocessing: ocrFrameResult.preprocessing || [],
        boxesBeforeMerge: ocrFrameResult.boxesBeforeMerge ?? frameOcrBoxes.length,
        fallbackUsed: Boolean(ocrFrameResult.fallbackUsed),
        fallbackReason: ocrFrameResult.fallbackReason || null,
        ocrText: frameOcrBoxes.map(function (box) { return box.ocrText; }).join(" ").trim(),
        confidence: frameOcrBoxes.length ? Math.round(frameOcrBoxes.reduce((sum, box) => sum + box.confidence, 0) / frameOcrBoxes.length) : null,
        captionBoxes: frameOcrBoxes,
        ...(process.env.CONTENTFORGE_DEBUG_OCR_BOXES === "1"
          ? { rawCaptionBoxes: ocrFrameResult.boxes || [] }
          : {}),
      });

      if (previous) {
        var delta = frameDelta(previous, frame);
        if (Number.isFinite(delta)) deltas.push(delta);
      }
      previous = frame;
      var detected = detectTextLikeBoxes(frame);
      if (process.env.CONTENTFORGE_DEBUG_OCR_BOXES === "1") {
        rawHeuristicBoxes.push(...detected.boxes.map(function (box) {
          return { ...box, timeSec: frame.timeSec };
        }));
      }
      var frameTextBoxCount = Math.max(detected.boxes.length, frameOcrBoxes.length);
      textBoxesDetected += frameTextBoxCount;
      if (frame.timeSec <= 3) earlyTextBoxes += frameTextBoxCount;
      for (var ocrBox of frameOcrBoxes) {
        if ((ocrBox.confidence || 0) < thresholds.ocrLowConfidence) {
          readabilityWarnings.push(advisoryWarning("caption_low_confidence", "Caption OCR confidence is low", "Detected caption text has low OCR confidence"));
        }
        if ((ocrBox.contrast || 0) < thresholds.captionLowContrast) lowContrastBoxes++;
        if ((ocrBox.fontHeightRatio || 0) < thresholds.captionMinHeightRatio) smallCaptionBoxes++;
        if ((ocrBox.safeZoneOverlap || []).length) unsafeBoxes++;
      }
      for (var box of detected.boxes) {
        if (detected.avgContrast > 0 && detected.avgContrast < thresholds.heuristicLowContrast) lowContrastBoxes++;
        if (
          frameOcrBoxes.length === 0 &&
          detected.boxes.length <= 4 &&
          plausibleHeuristicCaptionBox(box, frame)
        ) {
          var issues = textBoxSafeZoneIssues(box, frame);
          if (issues.length) {
            unsafeBoxes++;
            heuristicCaptionBoxes.push({ ...box, issues });
          }
        }
      }
    }

    var candidateTimes = [
      0.5,
      Math.max(0.8, duration ? duration * CAMPAIGN_FACTORY_AUDIT_CONFIG.sampling.coverCandidateFractions[0] : 1.5),
      Math.max(1.2, duration ? duration * CAMPAIGN_FACTORY_AUDIT_CONFIG.sampling.coverCandidateFractions[1] : 2.5),
    ];
    var candidateFrames = [];
    for (var candidateTime of candidateTimes) {
      if (duration && candidateTime >= duration) candidateTime = Math.max(0, duration - 0.1);
      var candidateFrame = await timeOperation(timingMetrics, "coverFrameExtractionMs", function () { return extractFrame(filePath, candidateTime); });
      if (!candidateFrame) continue;
      candidateFrames.push(candidateFrame);
      var stats = frameStats(candidateFrame);
      var warnings = [];
      if (stats.brightness < thresholds.coverDarkBrightness) warnings.push("cover_too_dark");
      if (stats.edgeScore < thresholds.coverBlurEdgeScore) warnings.push("cover_may_be_blurry");
      var score = Math.max(0, Math.min(100, Math.round(70 + (stats.edgeScore * 2) - Math.abs(stats.brightness - 128) / 3)));
      coverCandidates.push({
        file: fname,
        timeSec: Math.round(candidateTime * 10) / 10,
        score,
        warnings,
        stats: {
          brightness: stats.brightness,
          contrast: stats.contrast,
          edgeScore: stats.edgeScore,
        },
      });
    }
    var candidateDeltas = [];
    for (var i = 1; i < candidateFrames.length; i++) {
      var candidateDelta = frameDelta(candidateFrames[i - 1], candidateFrames[i]);
      if (Number.isFinite(candidateDelta)) candidateDeltas.push(candidateDelta);
    }
    if (candidateDeltas.length && Math.max(...candidateDeltas) < thresholds.coverCandidateSimilarityDelta) {
      coverWarnings.push(advisoryWarning("cover_candidates_similar", "Cover frames look too similar", fname + ": cover candidate frames are visually similar"));
    }
  }

  if (frameSamples === 0 && videoFiles.length > 0 && !ocrError) {
    ocrError = "No frames available for OCR";
  }
  ocrAvailable = ocrSuccessCount > 0 || (ocrFailureCount === 0 && videoFiles.length === 0);

  if (ocrAvailable === false) {
    readabilityWarnings.push(advisoryWarning("ocr_unavailable", "OCR unavailable", "OCR engine unavailable or failed: " + (ocrError || "unknown error")));
  }
  if (frameSamples === 0 && videoFiles.length > 0) {
    readabilityWarnings.push(advisoryWarning("caption_text_unreadable", "Caption text unreadable", "Could not sample frames for caption readability"));
  } else if (textBoxesDetected === 0 && videoFiles.length > 0) {
    readabilityWarnings.push(advisoryWarning("caption_not_detected", "No caption text detected", "No large readable overlay text detected in sampled frames"));
  }
  if (lowContrastBoxes > 0) {
    readabilityWarnings.push(advisoryWarning("caption_low_contrast", "Caption contrast is low", "Detected caption-like regions with low contrast"));
  }
  if (smallCaptionBoxes > 0) {
    readabilityWarnings.push(advisoryWarning("caption_text_too_small", "Caption text too small", "Detected caption text is below the minimum readable frame-height ratio"));
  }
  if (unsafeBoxes > 0) {
    safeWarnings.push(advisoryWarning("caption_too_close_to_edge", "Caption may be too close to edge", "Caption-like text is close to an edge or platform UI safe zone"));
    safeWarnings.push(advisoryWarning("caption_overlaps_ui_safe_zone", "Caption may overlap Reels controls", "Caption-like text may overlap bottom or right-side Reels UI controls"));
  }
  var avgDelta = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : null;
  if (
    earlyTextBoxes === 0 &&
    videoFiles.length > 0 &&
    (avgDelta === null || avgDelta < thresholds.weakOpeningDelta)
  ) {
    hookWarnings.push(advisoryWarning("hook_text_missing_first_3_seconds", "No hook text found early", "No large hook text detected in a low-motion opening"));
  }
  if (avgDelta !== null && avgDelta < thresholds.staticOpeningDelta) {
    hookWarnings.push(advisoryWarning("static_opening", "Opening has little motion", "The first 3 seconds have little visual change"));
  }
  if (earlyTextBoxes === 0 && avgDelta !== null && avgDelta < thresholds.weakOpeningDelta) {
    hookWarnings.push(advisoryWarning("weak_first_3_seconds", "Weak first 3 seconds", "Opening frames have limited text or visual change"));
  }

  safeWarnings = uniqueWarnings(safeWarnings);
  readabilityWarnings = uniqueWarnings(readabilityWarnings);
  coverWarnings = uniqueWarnings(coverWarnings);
  hookWarnings = uniqueWarnings(hookWarnings);
  watchabilityWarnings = uniqueWarnings(watchabilityWarnings);

  return {
    ocr: {
      available: ocrAvailable !== false,
      engine: ocrAvailable === false ? null : (ocrEngine || "heuristic"),
      engineVersion: ocrAvailable === false ? null : ocrEngineVersion,
      fallbackUsed: ocrFallbackUsed,
      fallbackReason: ocrFallbackReason,
      preprocessing: [...ocrPreprocessing],
      boxesBeforeMerge: ocrBoxesBeforeMerge,
      error: ocrAvailable === false ? ocrError : null,
      frameSamples,
      sampleCount: ocrResults.length,
      avgConfidence: ocrConfidenceValues.length
        ? Math.round(ocrConfidenceValues.reduce(function (sum, value) { return sum + value; }, 0) / ocrConfidenceValues.length)
        : null,
      results: ocrResults,
    },
    captionBoxes,
    safeZoneScore: unsafeBoxes > 0 ? Math.max(0, 100 - (unsafeBoxes * 25)) : 100,
    readabilityScore: captionBoxes.length
      ? Math.round(captionBoxes.reduce(function (sum, box) { return sum + (box.readabilityScore || 0); }, 0) / captionBoxes.length)
      : 0,
    hookVisibilityScore: earlyTextBoxes > 0 ? 100 : avgDelta !== null && avgDelta >= 10 ? 60 : 20,
    safeZone: {
      verdict: safeWarnings.length ? "warn" : "pass",
      warnings: safeWarnings,
      metrics: {
        frameSamples,
        textBoxesDetected,
        ocrTextBoxesDetected,
        unsafeBoxes,
        heuristicCaptionBoxes,
        ...(process.env.CONTENTFORGE_DEBUG_OCR_BOXES === "1"
          ? { rawHeuristicBoxes }
          : {}),
      },
    },
    readability: {
      verdict: readabilityWarnings.length ? "warn" : "pass",
      warnings: readabilityWarnings,
      metrics: { frameSamples, textBoxesDetected, ocrTextBoxesDetected, lowContrastBoxes, smallCaptionBoxes },
    },
    cover: {
      verdict: coverWarnings.length ? "warn" : "pass",
      warnings: coverWarnings,
      metrics: { candidateCount: coverCandidates.length },
      candidates: coverCandidates,
    },
    hookVisibility: {
      verdict: hookWarnings.length ? "warn" : "pass",
      warnings: hookWarnings,
      metrics: {
        frameSamples,
        earlyTextBoxes,
        avgFrameDelta: avgDelta === null ? null : Math.round(avgDelta * 10) / 10,
      },
    },
    watchability: {
      verdict: watchabilityWarnings.length ? "warn" : "pass",
      warnings: watchabilityWarnings,
      metrics: {
        fileCount: watchabilityItems.length,
        measuredFiles: watchabilityItems.filter(function (item) {
          return item.qualityMetrics?.available || item.qaSignals?.loudness || item.qaSignals?.crop;
        }).length,
      },
      files: watchabilityItems,
    },
    coverCandidates,
    timings: {
      totalMs: Date.now() - startedAt,
      ...timingMetrics,
      frameSamples,
      ocrFrameSamples: ocrResults.length,
      ocrTextBoxesDetected,
      ocrBoxesBeforeMerge,
      ocrFallbackUsed,
      ocrFallbackReason,
      advisoryLatencySoftLimitMs: thresholds.advisoryLatencySoftLimitMs,
      coverCandidates: coverCandidates.length,
    },
  };
}

// ─── Main API Handler ───
export async function POST(request) {
  var scopedDirToCleanup = null;
  var requestStartedAt = Date.now();
  try {
    var body = await request.json();
    var sourcePath = resolveUploadPath(body.source);
    var runId = body.runId || "latest";
    var layers = body.layers || ["pdq", "sscd", "audio", "forensics", "compression", "provenance", "reference", "temporal", "ssim"];
    var auditProfile = VALID_AUDIT_PROFILES.has(body.auditProfile) ? body.auditProfile : "default";
    var targetFile = body.targetFile || body.target || body.variant || body.outputFile || null;
    var requestedComparisonFiles = body.comparisonFiles ?? [];

    if (!sourcePath) {
      return NextResponse.json({ error: "Missing or invalid source path" }, { status: 400 });
    }
    layers = layers.filter(function (layer) { return VALID_LAYERS.has(layer); });
    if (auditProfile === "campaign_factory_v1") {
      if (!layers.includes("pdq")) layers.push("pdq");
      if (!layers.includes("sscd")) layers.push("sscd");
    }

    try { await access(sourcePath); } catch {
      return NextResponse.json({ error: "Source file not found" }, { status: 404 });
    }

    var finalDir = resolveRunFinalDir(runId);
    if (!finalDir) {
      return NextResponse.json({ error: "Invalid runId" }, { status: 400 });
    }
    var entries;
    try { entries = await readdir(finalDir); } catch {
      return NextResponse.json({ error: "No output files found" }, { status: 404 });
    }

    var files = entries
      .filter(e => SUPPORTED_EXTS.includes(path.extname(e).toLowerCase()))
      .sort((a, b) => a.localeCompare(b));
    var allFiles = [...files];

    if (!Array.isArray(requestedComparisonFiles) || requestedComparisonFiles.some(function (file) {
      return typeof file !== "string";
    })) {
      return NextResponse.json({ error: "comparisonFiles must be an array of filenames" }, { status: 400 });
    }

    var comparisonFiles = [];
    if (targetFile) {
      var safeTarget = path.basename(String(targetFile));
      if (!safeTarget || safeTarget !== String(targetFile).replace(/^output\/final\//, "")) {
        return NextResponse.json({ error: "Invalid targetFile" }, { status: 400 });
      }
      files = files.filter(function (file) { return file === safeTarget; });
      if (files.length === 0) {
        return NextResponse.json({ error: "Target file not found" }, { status: 404 });
      }
      for (var requestedComparison of requestedComparisonFiles) {
        var safeComparison = path.basename(requestedComparison);
        if (!safeComparison || safeComparison !== requestedComparison || safeComparison === safeTarget) {
          return NextResponse.json({ error: "Invalid comparisonFiles entry" }, { status: 400 });
        }
        if (!allFiles.includes(safeComparison)) {
          return NextResponse.json({ error: "Comparison file not found: " + safeComparison }, { status: 400 });
        }
        if (!comparisonFiles.includes(safeComparison)) comparisonFiles.push(safeComparison);
      }
      files = [safeTarget, ...comparisonFiles];
    } else if (requestedComparisonFiles.length > 0) {
      return NextResponse.json({ error: "comparisonFiles requires targetFile" }, { status: 400 });
    }

    if (files.length === 0) {
      return NextResponse.json({ error: "No variant files found" }, { status: 404 });
    }

    var auditDir = finalDir;
    if (targetFile) {
      scopedDirToCleanup = await mkdtemp(path.join(tmpdir(), "contentforge-similarity-"));
      for (var scopedFile of files) {
        await symlink(path.join(finalDir, scopedFile), path.join(scopedDirToCleanup, scopedFile));
      }
      auditDir = scopedDirToCleanup;
    }

    // Run all requested layers
    var results = {};
    var timings = {
      totalMs: null,
      layersMs: {},
    };

    // PDQ and forensics can run in parallel
    var promises = [];

    if (layers.includes("pdq")) {
      promises.push(timeLayer("pdq", timings, function () { return runPDQCheck(sourcePath, auditDir); }).then(r => { results.pdq = r; }));
    }
    if (layers.includes("sscd")) {
      promises.push(timeLayer("sscd", timings, function () { return runSSCDCheck(sourcePath, auditDir); }).then(r => { results.sscd = r; }));
    }
    if (layers.includes("forensics")) {
      promises.push(timeLayer("forensics", timings, function () { return runForensicCheck(auditDir, files, { auditProfile }); }).then(r => { results.forensics = r; }));
    }
    if (layers.includes("compression")) {
      promises.push(timeLayer("compression", timings, function () { return runCompressionForensics(auditDir); }).then(r => { results.compression = r; }));
    }
    if (layers.includes("provenance")) {
      promises.push(timeLayer("provenance", timings, function () { return runProvenanceCheck(auditDir); }).then(r => { results.provenance = r; }));
    }
    if (layers.includes("reference")) {
      promises.push(timeLayer("reference", timings, function () { return runReferenceQuery(auditDir); }).then(r => { results.reference = r; }));
    }
    if (layers.includes("temporal")) {
      promises.push(timeLayer("temporal", timings, function () { return runTemporalPDQ(sourcePath, auditDir); }).then(r => { results.temporal = r; }));
    }
    await Promise.all(promises);

    // Audio and SSIM run after (can be parallel with each other)
    var promises2 = [];
    if (layers.includes("audio")) {
      promises2.push(timeLayer("audio", timings, function () { return runAudioCheck(sourcePath, auditDir, files); }).then(r => { results.audio = r; }));
    }
    if (layers.includes("ssim")) {
      promises2.push(timeLayer("ssim", timings, function () { return runSSIMCheck(sourcePath, auditDir, files); }).then(r => { results.ssim = r; }));
    }
    await Promise.all(promises2);

    var shouldRunReelAdvisory = auditProfile === "campaign_factory_v1" ||
      layers.includes("safeZone") ||
      layers.includes("readability") ||
      layers.includes("cover") ||
      layers.includes("hookVisibility") ||
      layers.includes("watchability") ||
      layers.includes("creativeQuality");
    if (shouldRunReelAdvisory) {
      var advisory = await timeLayer("advisory", timings, function () { return runReelAdvisoryAudit(auditDir, files, sourcePath); });
      results.ocr = advisory.ocr;
      results.captionBoxes = advisory.captionBoxes;
      results.safeZoneScore = advisory.safeZoneScore;
      results.readabilityScore = advisory.readabilityScore;
      results.hookVisibilityScore = advisory.hookVisibilityScore;
      results.safeZone = advisory.safeZone;
      results.readability = advisory.readability;
      results.cover = advisory.cover;
      results.hookVisibility = advisory.hookVisibility;
      results.watchability = advisory.watchability;
      results.coverCandidates = advisory.coverCandidates;
      results.creativeQuality = buildCreativeQualityAudit(advisory);
      timings.advisory = advisory.timings;
    }

    var shouldRunOriginality = layers.includes("originality") ||
      Array.isArray(body.originalityReferenceFiles) ||
      body.originalityScope === "output_final";
    if (shouldRunOriginality && targetFile && VIDEO_EXTS.includes(path.extname(files[0]).toLowerCase())) {
      var originality = await timeLayer("originality", timings, function () {
        return runMultiAccountOriginalityAudit({
          finalDir,
          allFiles,
          targetFile: files[0],
          referenceFiles: body.originalityReferenceFiles || [],
          originalityScope: body.originalityScope || null,
          ocr: results.ocr || null,
        });
      });
      results.multiAccountOriginalityAudit = originality;
    }

    if (layers.includes("virality") || body.viralityReport) {
      results.virality = buildViralityGate(body.viralityReport, {
        required: layers.includes("virality"),
        auditProfile,
        targetFile: targetFile ? files[0] : null,
      });
    }
    if (layers.includes("videoAnalysis") || body.videoAnalysisReport) {
      results.videoAnalysis = buildVideoAnalysisGate(body.videoAnalysisReport, {
        required: layers.includes("videoAnalysis"),
        auditProfile,
        targetFile: targetFile ? files[0] : null,
      });
    }

    // Compute overall verdict
    var verdicts = {};
    function unavailableVerdict(result) {
      return result && (result.available === false || result.error) ? "warn" : null;
    }
    Object.assign(verdicts, buildDetectorVerdicts(results, auditProfile, { variantCount: files.length }));
    if (results.audio?.stats) {
      verdicts.audio = results.audio.stats.identicalPercent === 0 ? "pass" : results.audio.stats.identicalPercent <= 20 ? "warn" : "fail";
    } else if (layers.includes("audio") && results.audio?.available === false) {
      verdicts.audio = "warn";
    }
    if (results.forensics?.stats) {
      verdicts.forensics = unavailableVerdict(results.forensics) || results.forensics.stats.overallScore || "warn";
    }
    if (results.compression?.summary) {
      var compSum = results.compression.summary;
      verdicts.compression = unavailableVerdict(results.compression) || (compSum.failed === 0 ? "pass" : compSum.failed <= 2 ? "warn" : "fail");
    }
    if (results.provenance?.summary) {
      verdicts.provenance = unavailableVerdict(results.provenance) || (results.provenance.summary.flagged > 0 ? "fail" : results.provenance.summary.unavailable > 0 ? "warn" : "pass");
    }
    if (results.reference?.stats) {
      var refStats = results.reference.stats;
      verdicts.reference = results.reference.error ? "warn" :
        refStats.fail > 0 ? "fail" : refStats.warn > 0 ? "warn" : "pass";
    } else if (layers.includes("reference") && results.reference?.error) {
      verdicts.reference = "warn";
    }
    if (results.temporal?.stats) {
      verdicts.temporal = results.temporal.stats.failCount === 0 ? "pass" :
        results.temporal.stats.failCount <= 2 ? "warn" : "fail";
    } else if (layers.includes("temporal") && results.temporal?.available === false) {
      verdicts.temporal = "warn";
    }
    if (results.ssim?.stats) {
      verdicts.ssim = Number.isFinite(results.ssim.stats.avg) ? (results.ssim.stats.avg >= 0.80 ? "pass" : results.ssim.stats.avg >= 0.60 ? "warn" : "fail") : "warn";
    }
    if (results.safeZone?.verdict) {
      verdicts.safeZone = results.safeZone.verdict;
    }
    if (results.readability?.verdict) {
      verdicts.readability = results.readability.verdict;
    }
    if (results.cover?.verdict) {
      verdicts.cover = results.cover.verdict;
    }
    if (results.hookVisibility?.verdict) {
      verdicts.hookVisibility = results.hookVisibility.verdict;
    }
    if (results.watchability?.verdict) {
      verdicts.watchability = results.watchability.verdict;
    }
    if (results.creativeQuality?.verdict) {
      verdicts.creativeQuality = results.creativeQuality.verdict;
    }
    if (results.virality?.verdict) {
      verdicts.virality = results.virality.verdict;
    }
    if (results.videoAnalysis?.verdict) {
      verdicts.videoAnalysis = results.videoAnalysis.verdict;
    }
    if (results.multiAccountOriginalityAudit?.verdict) {
      verdicts.originality = results.multiAccountOriginalityAudit.verdict;
    }

    var readinessSummary = buildReadinessSummary(results, verdicts, {
      auditProfile,
      variantCount: files.length,
      requestedLayers: layers,
    });
    var overallVerdict = readinessSummary.blockingReasons.length > 0 ? "fail"
      : readinessSummary.warnings.length > 0 ? "warn" : "pass";
    var verdictCodes = Object.fromEntries(Object.entries(verdicts).map(function ([layer, verdict]) {
      return [layer, verdictCode(layer, verdict)];
    }));

    timings.totalMs = Date.now() - requestStartedAt;
    var responseBody = {
      contractVersion: auditProfile === "campaign_factory_v1" ? CAMPAIGN_FACTORY_CONTRACT_VERSION : null,
      auditProfile,
      targetFile: targetFile ? files[0] : null,
      comparisonFiles,
      layers: results,
      verdicts,
      verdictCodes,
      overallVerdict,
      readinessSummary,
      ocr: results.ocr || null,
      captionBoxes: results.captionBoxes || [],
      safeZoneScore: results.safeZoneScore ?? null,
      readabilityScore: results.readabilityScore ?? null,
      hookVisibilityScore: results.hookVisibilityScore ?? null,
      safeZone: results.safeZone || null,
      readability: results.readability || null,
      coverCandidates: results.coverCandidates || [],
      hookVisibility: results.hookVisibility || null,
      watchability: results.watchability || null,
      creativeQuality: results.creativeQuality || null,
      virality: results.virality || null,
      videoAnalysis: results.videoAnalysis || null,
      audioFitSignals: buildAudioFitSignals(results, files),
      referenceMatch: results.multiAccountOriginalityAudit || null,
      multiAccountOriginalityAudit: results.multiAccountOriginalityAudit || null,
      timings,
      filesAnalyzed: files.length,
    };
    if (scopedDirToCleanup) await rm(scopedDirToCleanup, { recursive: true, force: true });
    return NextResponse.json(responseBody);
  } catch (error) {
    if (scopedDirToCleanup) await rm(scopedDirToCleanup, { recursive: true, force: true }).catch(function () {});
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
