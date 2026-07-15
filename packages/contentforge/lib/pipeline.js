import { spawn, execFile } from "child_process";
import path from "path";
import crypto from "crypto";
import { mkdirSync, unlinkSync, rmSync, writeFileSync } from "fs";
import { buildPhase1Args, buildPhase2Args, buildImageArgs, generateDeviceFilename } from "./ffmpeg.js";
import { PROJECT_ROOT, getRunEditsDir, getRunFinalDir, resolveUploadPath } from "./paths.js";
import { getPythonCommand } from "./python-runtime.js";
import { averageHashSimilarity, multiFrameHash, temporalHashSimilarity } from "./detector.js";
import { getFastQualityMetrics } from "./quality-metrics.js";
import { getQaSignals, probeMedia, validateMediaInfo } from "./reels.js";
import { getReelsProfile } from "./reels-profiles.js";
import { createTextOverlayPng } from "./overlay.js";
import { evaluateQualityGate, getVariantPreset, normalizeQualityGate, normalizeVariantPreset, variantScoreBundle } from "./variant-engine.js";

/**
 * Post-process a video file to strip forensic tells:
 * - x264 UUID SEI in H.264 bitstream
 * - Lavf/Lavc/x264 strings in container atoms
 * - ©too encoder tool atom
 */
function sanitizeVideo(filePath) {
  return new Promise(function (resolve) {
    var scriptPath = path.join(PROJECT_ROOT, "lib", "sanitize.py");
    execFile(getPythonCommand(), [scriptPath, filePath], { timeout: 15000 }, function (err, stdout) {
      if (err) {
        resolve({ error: err.message });
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        resolve({ error: "Failed to parse sanitizer output" });
      }
    });
  });
}

/**
 * Post-process a JPEG file to randomize its quantization tables.
 * Each variant gets a unique QT fingerprint — prevents batch-origin detection.
 */
function randomizeJpegQT(filePath) {
  return new Promise(function (resolve) {
    var scriptPath = path.join(PROJECT_ROOT, "lib", "jpeg_randomize_qt.py");
    execFile(getPythonCommand(), [scriptPath, filePath, "85", "95"], { timeout: 10000 }, function (err, stdout) {
      if (err) {
        resolve({ error: err.message });
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        resolve({ error: "Failed to parse QT randomizer output" });
      }
    });
  });
}

// 5 minute timeout per FFmpeg process
var PROCESS_TIMEOUT_MS = 5 * 60 * 1000;
// 30 second timeout for image processing (single frame)
var IMAGE_TIMEOUT_MS = 30 * 1000;

async function buildVideoCandidateReport({ sourcePath, sourceHashes, keptReports, outputPath, outputProfile, qualityGate }) {
  var mediaInfo = await probeMedia(outputPath);
  var validation = validateMediaInfo(mediaInfo, outputProfile);
  var qaSignals = await getQaSignals(outputPath, mediaInfo);
  var qualityMetrics = await getFastQualityMetrics({ sourcePath, variantPath: outputPath, mediaInfo });
  var candidateHashes = await multiFrameHash(outputPath, true);
  var multiFrameSimilarity = averageHashSimilarity(candidateHashes, sourceHashes);
  var temporalSimilarity = temporalHashSimilarity(candidateHashes, sourceHashes);
  var sourceSimilarity = Math.max(multiFrameSimilarity, temporalSimilarity);
  var maxCrossVariantSimilarity = keptReports.reduce(function (max, report) {
    return Math.max(max, averageHashSimilarity(candidateHashes, report.frameHashes), temporalHashSimilarity(candidateHashes, report.frameHashes));
  }, 0);
  var differenceFromOriginal = Math.round((1 - sourceSimilarity) * 100);
  var scores = variantScoreBundle({
    mediaInfo,
    qualityMetrics,
    checks: validation.checks,
    warnings: qaSignals.warnings,
    differenceFromOriginal,
    qualitySignals: ["technical checks", "qa checks", qualityMetrics.available ? "ssim" : null].filter(Boolean),
    differenceSignals: ["multi-frame hash", "temporal hash"],
  });
  var gate = evaluateQualityGate({
    ...scores,
    reelsScore: validation.score,
    maxCrossVariantSimilarity,
    checks: validation.checks,
    warnings: qaSignals.warnings,
  }, qualityGate);
  return {
    ...scores,
    reelsScore: validation.score,
    mediaInfo,
    qualityMetrics,
    checks: validation.checks,
    warnings: qaSignals.warnings,
    sourceSimilarity: Number(sourceSimilarity.toFixed(4)),
    multiFrameSimilarity: Number(multiFrameSimilarity.toFixed(4)),
    temporalSimilarity: Number(temporalSimilarity.toFixed(4)),
    maxCrossVariantSimilarity: Number(maxCrossVariantSimilarity.toFixed(4)),
    frameHashes: candidateHashes,
    passed: gate.passed,
    rejectionReasons: gate.reasons,
  };
}

async function buildImageCandidateReport({ sourceHashes, keptReports, outputPath, qualityGate }) {
  var candidateHashes = await multiFrameHash(outputPath, false);
  var sourceSimilarity = averageHashSimilarity(candidateHashes, sourceHashes);
  var maxCrossVariantSimilarity = keptReports.reduce(function (max, report) {
    return Math.max(max, averageHashSimilarity(candidateHashes, report.frameHashes));
  }, 0);
  var differenceFromOriginal = Math.round((1 - sourceSimilarity) * 100);
  var scores = variantScoreBundle({
    mediaInfo: {},
    checks: [],
    warnings: [],
    differenceFromOriginal,
    qualitySignals: ["image encoded"],
    differenceSignals: ["image perceptual hash"],
  });
  var gate = evaluateQualityGate({
    ...scores,
    reelsScore: 100,
    maxCrossVariantSimilarity,
    checks: [],
    warnings: [],
  }, qualityGate);
  return {
    ...scores,
    reelsScore: 100,
    sourceSimilarity: Number(sourceSimilarity.toFixed(4)),
    maxCrossVariantSimilarity: Number(maxCrossVariantSimilarity.toFixed(4)),
    frameHashes: candidateHashes,
    passed: gate.passed,
    rejectionReasons: gate.reasons,
  };
}

/**
 * Run a single FFmpeg command with timeout and stderr size cap.
 */
function runFFmpeg(args, onLog, timeout, signal) {
  var timeoutMs = timeout || PROCESS_TIMEOUT_MS;
  return new Promise(function (resolve, reject) {
    if (signal?.aborted) {
      reject(new Error("Pipeline aborted"));
      return;
    }
    var proc = spawn("ffmpeg", args, {
      cwd: PROJECT_ROOT,
      stdio: ["ignore", "ignore", "pipe"],
    });

    var stderr = "";
    var killed = false;
    var settled = false;

    function cleanup() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }

    function fail(err) {
      if (settled) return;
      settled = true;
      cleanup();
      reject(err);
    }

    function abort() {
      killed = true;
      proc.kill("SIGKILL");
      fail(new Error("Pipeline aborted"));
    }

    // Timeout — kill if FFmpeg hangs
    var timer = setTimeout(function () {
      killed = true;
      proc.kill("SIGKILL");
      fail(new Error("FFmpeg timed out after " + (timeoutMs / 1000) + "s"));
    }, timeoutMs);
    signal?.addEventListener("abort", abort, { once: true });

    proc.stderr.on("data", function (chunk) {
      var text = chunk.toString();
      // Cap stderr at 50KB to prevent memory issues on verbose output
      if (stderr.length < 50000) {
        stderr += text;
      }
      if (onLog) onLog(text);
    });

    proc.on("close", function (code) {
      if (settled) return;
      settled = true;
      cleanup();
      if (killed) return; // Already rejected by timeout
      if (code === 0) {
        resolve(stderr);
      } else {
        reject(new Error("FFmpeg exited with code " + code + ": " + stderr.slice(-500)));
      }
    });

    proc.on("error", function (err) {
      fail(err);
    });
  });
}

/**
 * Get video metadata using ffprobe.
 */
function getVideoInfo(inputPath) {
  return new Promise(function (resolve, reject) {
    var proc = spawn("ffprobe", [
      "-v", "quiet",
      "-print_format", "json",
      "-show_format",
      "-show_streams",
      inputPath,
    ]);

    var stdout = "";
    proc.stdout.on("data", function (chunk) {
      stdout += chunk.toString();
    });

    var timer = setTimeout(function () {
      proc.kill("SIGKILL");
      reject(new Error("ffprobe timed out"));
    }, 30000);

    proc.on("close", function (code) {
      clearTimeout(timer);
      if (code === 0) {
        try {
          var info = JSON.parse(stdout);
          var videoStream = (info.streams || []).find(function (s) { return s.codec_type === "video"; });
          var audioStream = (info.streams || []).find(function (s) { return s.codec_type === "audio"; });
          resolve({
            duration: parseFloat((info.format && info.format.duration) || 0),
            width: (videoStream && videoStream.width) || 0,
            height: (videoStream && videoStream.height) || 0,
            codec: (videoStream && videoStream.codec_name) || "unknown",
            size: parseInt((info.format && info.format.size) || 0, 10),
            bitrate: parseInt((info.format && info.format.bit_rate) || 0, 10),
            hasAudio: !!audioStream,
          });
        } catch (e) {
          reject(e);
        }
      } else {
        reject(new Error("ffprobe failed"));
      }
    });

    proc.on("error", function (err) {
      clearTimeout(timer);
      reject(err);
    });
  });
}

/**
 * Get image metadata using ffprobe.
 */
function getImageInfo(inputPath) {
  return new Promise(function (resolve, reject) {
    var proc = spawn("ffprobe", [
      "-v", "quiet",
      "-print_format", "json",
      "-show_format",
      "-show_streams",
      inputPath,
    ]);

    var stdout = "";
    proc.stdout.on("data", function (chunk) {
      stdout += chunk.toString();
    });

    var timer = setTimeout(function () {
      proc.kill("SIGKILL");
      reject(new Error("ffprobe timed out"));
    }, 15000);

    proc.on("close", function (code) {
      clearTimeout(timer);
      if (code === 0) {
        try {
          var info = JSON.parse(stdout);
          var stream = (info.streams || []).find(function (s) { return s.codec_type === "video"; });
          resolve({
            width: (stream && stream.width) || 0,
            height: (stream && stream.height) || 0,
            codec: (stream && stream.codec_name) || "unknown",
            size: parseInt((info.format && info.format.size) || 0, 10),
            format: (info.format && info.format.format_name) || "unknown",
          });
        } catch (e) {
          reject(e);
        }
      } else {
        reject(new Error("ffprobe failed"));
      }
    });

    proc.on("error", function (err) {
      clearTimeout(timer);
      reject(err);
    });
  });
}

/**
 * Run the full video forging pipeline with SSE progress callbacks.
 */
export async function runPipeline(config, sendEvent) {
  var inputFile = config.inputFile;
  var numEdits = config.numEdits;
  var spinsPerEdit = config.spinsPerEdit;
  var variantPresetId = normalizeVariantPreset(config.variantPreset, config.level);
  var requestedVariantOptions = config.variantOptions || {};
  var variantOptions = { ...requestedVariantOptions };
  var variantPreset = getVariantPreset(variantPresetId, variantOptions, config.level);
  var qualityGate = normalizeQualityGate(config.qualityGate);
  var level = variantPreset.level;
  var flip = config.flip;
  var vertical = config.vertical;
  var outputProfile = config.outputProfile || "organic";
  var signal = config.signal;
  var total = numEdits * spinsPerEdit;
  var startTime = Date.now();

  var inputPath = resolveUploadPath(inputFile);

  // Unique run ID — isolates concurrent runs from each other
  var runId = crypto.randomBytes(4).toString("hex");
  var editsDir = getRunEditsDir(runId);
  var finalDir = getRunFinalDir(runId);

  mkdirSync(editsDir, { recursive: true });
  mkdirSync(finalDir, { recursive: true });
  var profile = getReelsProfile(outputProfile);
  var overlayPath = await createTextOverlayPng({
    ...variantOptions,
    width: profile.width,
    height: profile.height,
    outputDir: editsDir,
  });
  if (overlayPath) variantOptions.overlayImagePath = overlayPath;
  writeFileSync(path.join(finalDir, "run_config.json"), JSON.stringify({
    mediaType: "video",
    inputFile,
    outputProfile,
    variantPreset: variantPreset.id,
    variantOptions: requestedVariantOptions,
    qualityGate,
    attemptedCandidates: 0,
    keptCandidates: 0,
    rejectedCandidates: 0,
    rejectionReasons: {},
    generatedAt: new Date().toISOString(),
  }, null, 2));

  var attempted = 0;
  var succeeded = 0;
  var failed = 0;
  var attemptedCandidates = 0;
  var rejectedCandidates = 0;
  var rejectionReasons = {};
  var rejectionSamples = [];
  var keptReports = [];

  // Probe source
  var hasAudio = true;
  try {
    var info = await getVideoInfo(inputPath);
    hasAudio = info.hasAudio;
    sendEvent({ type: "log", text: "Source: " + info.width + "x" + info.height + " " + info.codec + " audio=" + hasAudio + "\n" });
  } catch {
    sendEvent({ type: "log", text: "Could not probe source, assuming audio present\n" });
  }

  sendEvent({ type: "log", text: "Run ID: " + runId + "\n" });
  var sourceHashes = await multiFrameHash(inputPath, true);

  function recordRejection(reasons) {
    for (var reason of reasons) rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
  }

  function recordRejectionSample(filename, candidateReport) {
    if (rejectionSamples.length >= 12) return;
    rejectionSamples.push({
      filename,
      rejectionReasons: candidateReport.rejectionReasons || [],
      qualityRetained: candidateReport.qualityRetained,
      differenceFromOriginal: candidateReport.differenceFromOriginal,
      reelsScore: candidateReport.reelsScore,
      checks: (candidateReport.checks || []).filter(function (check) { return check.status !== "pass"; }).map(function (check) {
        return {
          id: check.id,
          status: check.status,
          label: check.label,
          message: check.message,
        };
      }),
      warnings: candidateReport.warnings || [],
      mediaInfo: {
        width: candidateReport.mediaInfo && candidateReport.mediaInfo.width,
        height: candidateReport.mediaInfo && candidateReport.mediaInfo.height,
        duration: candidateReport.mediaInfo && candidateReport.mediaInfo.duration,
        fps: candidateReport.mediaInfo && candidateReport.mediaInfo.fps,
        videoCodec: candidateReport.mediaInfo && candidateReport.mediaInfo.videoCodec,
        audioCodec: candidateReport.mediaInfo && candidateReport.mediaInfo.audioCodec,
        faststart: candidateReport.mediaInfo && candidateReport.mediaInfo.faststart,
      },
    });
  }

  var successfulEdits = new Set();

  // ─── Clean level: skip Phase 1 entirely, run Phase 2 directly on source ───
  if (level === "clean" || variantPreset.id === "quality") {
    sendEvent({ type: "phase", phase: 1, message: "Phase 1: Skipped (clean mode)" });
    sendEvent({ type: "phase", phase: 2, message: "Phase 2: Clean Forge" });

    for (var ci = 0; ci < total; ci++) {
      var kept = false;
      var maxAttempts = qualityGate.enabled ? qualityGate.maxAttempts : 1;
      for (var candidateAttempt = 0; candidateAttempt < maxAttempts && !kept; candidateAttempt++) {
      attempted++;
      attemptedCandidates++;
      var filename = generateDeviceFilename() + ".mp4";
      var outputPath = path.join(finalDir, filename);

      sendEvent({
        type: "progress", phase: 2,
        current: attempted, total: total,
        totalOverall: total, completedOverall: attempted,
        filename: filename,
        elapsed: formatTime(Date.now() - startTime),
        eta: estimateETA(startTime, attempted, total),
      });

      var attemptOptions = { ...variantOptions, attemptIndex: ci * 2 + candidateAttempt };
      var p2args = buildPhase2Args(inputPath, outputPath, level, hasAudio, vertical, outputProfile, variantPreset.id, attemptOptions);

      try {
        await runFFmpeg(p2args, function (log) { sendEvent({ type: "log", text: log }); }, null, signal);
        // Post-process: strip x264 SEI + Lavf strings
        var sanResult = await sanitizeVideo(outputPath);
        if (sanResult.results && sanResult.results[0] && sanResult.results[0].patches && sanResult.results[0].patches.length > 0) {
          sendEvent({ type: "log", text: "  \u2692 sanitized " + sanResult.results[0].patches.length + " forensic tell(s)\n" });
        }
        var candidateReport = await buildVideoCandidateReport({ sourcePath: inputPath, sourceHashes, keptReports, outputPath, outputProfile, qualityGate });
        if (!candidateReport.passed) {
          rejectedCandidates++;
          failed++;
          recordRejection(candidateReport.rejectionReasons);
          recordRejectionSample(filename, candidateReport);
          try { unlinkSync(outputPath); } catch { /* ignore */ }
          sendEvent({ type: "log", text: "× rejected " + filename + " (" + candidateReport.rejectionReasons.join(", ") + ")\n" });
          continue;
        }
        keptReports.push({ file: filename, frameHashes: candidateReport.frameHashes, ...candidateReport });
        succeeded++;
        kept = true;
        sendEvent({ type: "log", text: "\u2713 [" + succeeded + "/" + total + "] " + filename + " q=" + candidateReport.qualityRetained + " d=" + candidateReport.differenceFromOriginal + "\n" });
      } catch (err) {
        failed++;
        sendEvent({ type: "error", message: "Variant " + attempted + " failed: " + err.message });
      }
      }
    }

    try { rmSync(editsDir, { recursive: true, force: true }); } catch { /* ignore */ }
    writeFileSync(path.join(finalDir, "run_config.json"), JSON.stringify({
      mediaType: "video",
      inputFile,
      outputProfile,
      variantPreset: variantPreset.id,
      variantOptions: requestedVariantOptions,
      qualityGate,
      attemptedCandidates,
      keptCandidates: succeeded,
      rejectedCandidates,
      rejectionReasons,
      rejectionSamples,
      generatedAt: new Date().toISOString(),
    }, null, 2));
    sendEvent({ type: "complete", total: succeeded, attempted, failed, runId, elapsed: formatTime(Date.now() - startTime), outputDir: finalDir, variantPreset: variantPreset.id, variantOptions: requestedVariantOptions, outputProfile, qualityGate, attemptedCandidates, keptCandidates: succeeded, rejectedCandidates, rejectionReasons, rejectionSamples });
    return;
  }

  // ─── Phase 1: Creative Remixes ───
  sendEvent({ type: "phase", phase: 1, message: "Phase 1: Creative Remixes" });

  for (var i = 0; i < numEdits; i++) {
    var editPath = path.join(editsDir, "edit_" + (i + 1) + ".mp4");
    var editNum = i + 1;

    sendEvent({
      type: "progress", phase: 1,
      current: editNum, total: numEdits,
      totalOverall: total, completedOverall: attempted,
      filename: "edit_" + editNum + ".mp4",
      elapsed: formatTime(Date.now() - startTime),
      eta: estimateETA(startTime, attempted, total),
    });

    var p1args = buildPhase1Args(inputPath, editPath, i, {
      flip: flip,
      vertical: vertical,
      hasAudio: hasAudio,
      outputProfile: outputProfile,
      variantPreset: variantPreset.id,
      variantOptions,
      level,
    });

    try {
      await runFFmpeg(p1args, function (log) { sendEvent({ type: "log", text: log }); }, null, signal);
      successfulEdits.add(i);
      sendEvent({ type: "log", text: "\u2713 edit_" + editNum + ".mp4 complete\n" });
    } catch (err) {
      sendEvent({ type: "error", message: "Edit " + editNum + " failed: " + err.message });
    }
  }

  // Abort if ALL edits failed
  if (successfulEdits.size === 0) {
    sendEvent({ type: "error", message: "All Phase 1 edits failed — aborting" });
    sendEvent({ type: "complete", total: 0, attempted: 0, failed: total, runId, elapsed: formatTime(Date.now() - startTime), outputDir: finalDir });
    return;
  }

  // ─── Phase 2: Variant Finalization ───
  sendEvent({ type: "phase", phase: 2, message: "Phase 2: Variant Finalization (" + level + ")" });

  for (var editIdx = 0; editIdx < numEdits; editIdx++) {
    if (!successfulEdits.has(editIdx)) {
      sendEvent({ type: "log", text: "Skipping edit_" + (editIdx + 1) + " spins (Phase 1 failed)\n" });
      attempted += spinsPerEdit;
      failed += spinsPerEdit;
      continue;
    }

    var srcPath = path.join(editsDir, "edit_" + (editIdx + 1) + ".mp4");

    for (var spinIdx = 0; spinIdx < spinsPerEdit; spinIdx++) {
      var kept = false;
      var maxAttempts = qualityGate.enabled ? qualityGate.maxAttempts : 1;
      for (var candidateAttempt = 0; candidateAttempt < maxAttempts && !kept; candidateAttempt++) {
      attempted++;
      attemptedCandidates++;
      var filename = generateDeviceFilename() + ".mp4";
      var outputPath = path.join(finalDir, filename);

      sendEvent({
        type: "progress", phase: 2,
        current: attempted, total: total,
        totalOverall: total, completedOverall: attempted,
        filename: filename,
        elapsed: formatTime(Date.now() - startTime),
        eta: estimateETA(startTime, attempted, total),
        editSource: editIdx + 1, spinNum: spinIdx + 1,
      });

      var attemptOptions = { ...variantOptions, attemptIndex: editIdx * spinsPerEdit + spinIdx * 2 + candidateAttempt };
      var p2args = buildPhase2Args(srcPath, outputPath, level, hasAudio, vertical, outputProfile, variantPreset.id, attemptOptions);

      try {
        await runFFmpeg(p2args, function (log) { sendEvent({ type: "log", text: log }); }, null, signal);
        // Post-process: strip x264 SEI + Lavf strings
        var sanResult = await sanitizeVideo(outputPath);
        if (sanResult.results && sanResult.results[0] && sanResult.results[0].patches && sanResult.results[0].patches.length > 0) {
          sendEvent({ type: "log", text: "  \u2692 sanitized " + sanResult.results[0].patches.length + " forensic tell(s)\n" });
        }
        var candidateReport = await buildVideoCandidateReport({ sourcePath: inputPath, sourceHashes, keptReports, outputPath, outputProfile, qualityGate });
        if (!candidateReport.passed) {
          rejectedCandidates++;
          failed++;
          recordRejection(candidateReport.rejectionReasons);
          recordRejectionSample(filename, candidateReport);
          try { unlinkSync(outputPath); } catch { /* ignore */ }
          sendEvent({ type: "log", text: "× rejected " + filename + " (" + candidateReport.rejectionReasons.join(", ") + ")\n" });
          continue;
        }
        keptReports.push({ file: filename, frameHashes: candidateReport.frameHashes, ...candidateReport });
        succeeded++;
        kept = true;
        sendEvent({ type: "log", text: "\u2713 [" + succeeded + "/" + total + "] " + filename + " q=" + candidateReport.qualityRetained + " d=" + candidateReport.differenceFromOriginal + "\n" });
      } catch (err) {
        failed++;
        sendEvent({ type: "error", message: "Spin " + attempted + " failed: " + err.message });
      }
      }
    }
  }

  // Clean up run-specific edits dir (intermediates no longer needed)
  try { rmSync(editsDir, { recursive: true, force: true }); } catch { /* ignore */ }

  writeFileSync(path.join(finalDir, "run_config.json"), JSON.stringify({
    mediaType: "video",
    inputFile,
    outputProfile,
    variantPreset: variantPreset.id,
    variantOptions: requestedVariantOptions,
    qualityGate,
    attemptedCandidates,
    keptCandidates: succeeded,
    rejectedCandidates,
    rejectionReasons,
    rejectionSamples,
    generatedAt: new Date().toISOString(),
  }, null, 2));

  sendEvent({
    type: "complete",
    total: succeeded,
    attempted,
    failed,
    runId,
    elapsed: formatTime(Date.now() - startTime),
    outputDir: finalDir,
    outputProfile,
    variantPreset: variantPreset.id,
    variantOptions: requestedVariantOptions,
    qualityGate,
    attemptedCandidates,
    keptCandidates: succeeded,
    rejectedCandidates,
    rejectionReasons,
    rejectionSamples,
  });
}

/**
 * Run the image forging pipeline.
 * Generates N unique image variants from one source image.
 */
export async function runImagePipeline(config, sendEvent) {
  var inputFile = config.inputFile;
  var numVariants = config.numVariants;
  var variantPresetId = normalizeVariantPreset(config.variantPreset, config.level);
  var requestedVariantOptions = config.variantOptions || {};
  var variantOptions = { ...requestedVariantOptions };
  var variantPreset = getVariantPreset(variantPresetId, variantOptions, config.level);
  var qualityGate = normalizeQualityGate(config.qualityGate);
  var level = variantPreset.level;
  var startTime = Date.now();

  var inputPath = resolveUploadPath(inputFile);
  var runId = crypto.randomBytes(4).toString("hex");
  var finalDir = getRunFinalDir(runId);

  mkdirSync(finalDir, { recursive: true });
  var overlayPath = await createTextOverlayPng({
    ...variantOptions,
    width: 1080,
    height: 1080,
    outputDir: path.join(finalDir, "_assets"),
  });
  if (overlayPath) variantOptions.overlayImagePath = overlayPath;
  writeFileSync(path.join(finalDir, "run_config.json"), JSON.stringify({
    mediaType: "image",
    inputFile,
    variantPreset: variantPreset.id,
    variantOptions: requestedVariantOptions,
    qualityGate,
    attemptedCandidates: 0,
    keptCandidates: 0,
    rejectedCandidates: 0,
    rejectionReasons: {},
    generatedAt: new Date().toISOString(),
  }, null, 2));

  // Probe source image
  try {
    var info = await getImageInfo(inputPath);
    sendEvent({ type: "log", text: "Source: " + info.width + "x" + info.height + " " + info.codec + " " + Math.round(info.size / 1024) + "KB\n" });
  } catch {
    sendEvent({ type: "log", text: "Could not probe source image\n" });
  }

  sendEvent({ type: "phase", phase: 1, message: "Image Variant Generation (" + variantPreset.label + ")" });
  sendEvent({ type: "log", text: "Generating " + numVariants + " unique variants...\n" });
  sendEvent({ type: "log", text: "Pipeline: crop + modulate + rotate + JPEG diversity\n\n" });

  var attempted = 0;
  var succeeded = 0;
  var failed = 0;
  var attemptedCandidates = 0;
  var rejectedCandidates = 0;
  var rejectionReasons = {};
  var keptReports = [];
  var sourceHashes = await multiFrameHash(inputPath, false);

  function recordImageRejection(reasons) {
    for (var reason of reasons) rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
  }

  for (var i = 0; i < numVariants; i++) {
    var kept = false;
    var maxAttempts = qualityGate.enabled ? qualityGate.maxAttempts : 1;
    for (var candidateAttempt = 0; candidateAttempt < maxAttempts && !kept; candidateAttempt++) {
    attempted++;
    attemptedCandidates++;
    var outputFormat = variantPreset.outputFormat === "webp" ? "webp" : "jpg";
    var filename = generateDeviceFilename() + "." + outputFormat;
    var outputPath = path.join(finalDir, filename);

    sendEvent({
      type: "progress", phase: 1,
      current: attempted, total: numVariants,
      totalOverall: numVariants, completedOverall: attempted,
      filename: filename,
      elapsed: formatTime(Date.now() - startTime),
      eta: estimateETA(startTime, attempted, numVariants),
    });

    var attemptOptions = { ...variantOptions, attemptIndex: i * 2 + candidateAttempt };
    var imgArgs = buildImageArgs(inputPath, outputPath, i, { level: level, variantPreset: variantPreset.id, variantOptions: attemptOptions });

    try {
      await runFFmpeg(imgArgs, function (log) { sendEvent({ type: "log", text: log }); }, IMAGE_TIMEOUT_MS);
      if (outputFormat === "jpg") {
        var qtResult = await randomizeJpegQT(outputPath);
        if (qtResult.results && qtResult.results[0] && qtResult.results[0].qtRandomized) {
          sendEvent({ type: "log", text: "  \u2692 QT randomized (q=" + qtResult.results[0].quality + ")\n" });
        }
      }
      // Post-process: strip Lavc/Lavf strings from JPEG binary
      var sanResult = await sanitizeVideo(outputPath);
      if (sanResult.results && sanResult.results[0] && sanResult.results[0].patches && sanResult.results[0].patches.length > 0) {
        sendEvent({ type: "log", text: "  \u2692 sanitized " + sanResult.results[0].patches.length + " forensic tell(s)\n" });
      }
      var candidateReport = await buildImageCandidateReport({ sourceHashes, keptReports, outputPath, qualityGate });
      if (!candidateReport.passed) {
        rejectedCandidates++;
        failed++;
        recordImageRejection(candidateReport.rejectionReasons);
        try { unlinkSync(outputPath); } catch { /* ignore */ }
        sendEvent({ type: "log", text: "× rejected " + filename + " (" + candidateReport.rejectionReasons.join(", ") + ")\n" });
        continue;
      }
      keptReports.push({ file: filename, frameHashes: candidateReport.frameHashes, ...candidateReport });
      succeeded++;
      kept = true;
      sendEvent({ type: "log", text: "\u2713 [" + succeeded + "/" + numVariants + "] " + filename + " q=" + candidateReport.qualityRetained + " d=" + candidateReport.differenceFromOriginal + "\n" });
    } catch (err) {
      failed++;
      sendEvent({ type: "error", message: "Variant " + attempted + " failed: " + err.message });
    }
    }
  }

  writeFileSync(path.join(finalDir, "run_config.json"), JSON.stringify({
    mediaType: "image",
    inputFile,
    variantPreset: variantPreset.id,
    variantOptions: requestedVariantOptions,
    qualityGate,
    attemptedCandidates,
    keptCandidates: succeeded,
    rejectedCandidates,
    rejectionReasons,
    generatedAt: new Date().toISOString(),
  }, null, 2));

  sendEvent({
    type: "complete",
    total: succeeded,
    attempted,
    failed,
    runId,
    elapsed: formatTime(Date.now() - startTime),
    outputDir: finalDir,
    mediaType: "image",
    variantPreset: variantPreset.id,
    variantOptions: requestedVariantOptions,
    qualityGate,
    attemptedCandidates,
    keptCandidates: succeeded,
    rejectedCandidates,
    rejectionReasons,
  });
}

function formatTime(ms) {
  var s = Math.floor(ms / 1000);
  var m = Math.floor(s / 60);
  var h = Math.floor(m / 60);
  if (h > 0) return h + "h " + (m % 60) + "m " + (s % 60) + "s";
  if (m > 0) return m + "m " + (s % 60) + "s";
  return s + "s";
}

function estimateETA(startTime, completed, total) {
  if (completed <= 0) return "calculating...";
  var elapsed = Date.now() - startTime;
  var perItem = elapsed / completed;
  var remaining = (total - completed) * perItem;
  if (!isFinite(remaining)) return "calculating...";
  return formatTime(remaining);
}
