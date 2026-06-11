import { execFile } from "child_process";
import { mkdir, open, readdir, readFile, rm, stat, writeFile } from "fs/promises";
import { existsSync } from "fs";
import path from "path";
import {
  OUTPUT_DIR,
  RUNS_DIR,
  ensureInside,
  getRunRoot,
  resolveRunFile,
  resolveRunFinalDir,
  resolveUploadPath,
  safeBasename,
} from "./paths.js";
import { analyzeCaptions } from "./captions.js";
import { getQualityMetrics } from "./quality-metrics.js";
import { REELS_PROFILES } from "./reels-profiles.js";
import { variantScoreBundle } from "./variant-engine.js";

export { REELS_PROFILES };

var VIDEO_EXTS = new Set([".mp4", ".mov", ".webm"]);
var IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif"]);

function runTool(command, args, options = {}) {
  return new Promise(function (resolve) {
    execFile(command, args, {
      timeout: options.timeout || 20000,
      maxBuffer: options.maxBuffer || 2 * 1024 * 1024,
      cwd: options.cwd,
    }, function (error, stdout, stderr) {
      resolve({ error, stdout: stdout || "", stderr: stderr || "" });
    });
  });
}

function parseFps(rate) {
  if (!rate || typeof rate !== "string") return 0;
  var parts = rate.split("/");
  if (parts.length === 2) {
    var n = parseFloat(parts[0]);
    var d = parseFloat(parts[1]);
    return d ? n / d : 0;
  }
  return parseFloat(rate) || 0;
}

function statusRank(status) {
  return status === "pass" ? 1 : status === "warn" ? 0.5 : 0;
}

function check(id, label, status, actual, expected, message) {
  return { id, label, status, actual, expected, message };
}

export function validateMediaInfo(mediaInfo, profileId) {
  var profile = REELS_PROFILES[profileId] || REELS_PROFILES.organic;
  var checks = [];
  var width = mediaInfo.width || 0;
  var height = mediaInfo.height || 0;
  var aspect = height ? width / height : 0;
  var aspectDelta = Math.abs(aspect - profile.preferredAspect);
  var videoCodec = mediaInfo.videoCodec || "unknown";
  var audioCodec = mediaInfo.audioCodec || "none";
  var audioBitrate = mediaInfo.audioBitrate || 0;
  var formatName = mediaInfo.formatName || "";

  checks.push(check(
    "aspect",
    "Aspect ratio",
    aspectDelta <= profile.aspectTolerance ? "pass" : "warn",
    width + "x" + height,
    "9:16",
    aspectDelta <= profile.aspectTolerance ? "Vertical framing looks right" : "Preview/crop to 9:16"
  ));

  checks.push(check(
    "resolution",
    "Resolution",
    width >= profile.minWidth && height >= profile.minHeight ? "pass" : "fail",
    width + "x" + height,
    profile.minWidth + "x" + profile.minHeight + "+",
    width >= profile.minWidth && height >= profile.minHeight ? "Resolution meets profile" : "Export at a larger vertical size"
  ));

  checks.push(check(
    "fps",
    "Frame rate",
    mediaInfo.fps >= profile.minFps ? "pass" : "fail",
    mediaInfo.fps ? mediaInfo.fps.toFixed(2) + " fps" : "unknown",
    profile.minFps + " fps+",
    mediaInfo.fps >= profile.minFps ? "Frame rate meets profile" : "Export at 30 fps or higher"
  ));

  if (profile.targetFps) {
    checks.push(check(
      "targetFps",
      "High quality FPS",
      mediaInfo.fps >= profile.targetFps ? "pass" : "warn",
      mediaInfo.fps ? mediaInfo.fps.toFixed(2) + " fps" : "unknown",
      profile.targetFps + " fps target",
      mediaInfo.fps >= profile.targetFps ? "Hits high quality target" : "Good enough, but 60 fps is the target"
    ));
  }

  checks.push(check(
    "videoCodec",
    "Video codec",
    profile.videoCodecs.includes(videoCodec) ? "pass" : "warn",
    videoCodec,
    profile.videoCodecs.join(", "),
    profile.videoCodecs.includes(videoCodec) ? "Codec matches profile" : "H.264 is the safest Reels export"
  ));

  checks.push(check(
    "container",
    "Container",
    profile.containers.some(function (fmt) { return formatName.includes(fmt) || fmt.includes(formatName); }) ? "pass" : "warn",
    formatName || "unknown",
    "mp4/mov",
    "MP4 or MOV is expected"
  ));

  checks.push(check(
    "audioCodec",
    "Audio codec",
    !audioCodec || audioCodec === "none" || profile.audioCodecs.includes(audioCodec) ? "pass" : "warn",
    audioCodec || "none",
    "aac",
    audioCodec === "aac" ? "Audio codec matches profile" : "AAC is the safest audio export"
  ));

  checks.push(check(
    "audioBitrate",
    "Audio bitrate",
    !audioBitrate || audioBitrate >= profile.minAudioBitrate ? "pass" : "warn",
    audioBitrate ? Math.round(audioBitrate / 1000) + " kbps" : "unknown",
    Math.round(profile.minAudioBitrate / 1000) + " kbps+",
    "Higher audio bitrate is better for clean playback"
  ));

  if (profile.maxDuration) {
    checks.push(check(
      "duration",
      "Duration",
      mediaInfo.duration <= profile.maxDuration ? "pass" : "fail",
      mediaInfo.duration ? mediaInfo.duration.toFixed(1) + "s" : "unknown",
      profile.maxDuration + "s max",
      mediaInfo.duration <= profile.maxDuration ? "Duration fits profile" : "Trim for this profile"
    ));
  } else {
    checks.push(check(
      "duration",
      "Duration",
      mediaInfo.duration > 0 ? "pass" : "warn",
      mediaInfo.duration ? mediaInfo.duration.toFixed(1) + "s" : "unknown",
      "valid duration",
      "Duration is readable"
    ));
  }

  checks.push(check(
    "fileSize",
    "File size",
    mediaInfo.size <= profile.maxFileSize ? "pass" : "fail",
    formatBytes(mediaInfo.size),
    formatBytes(profile.maxFileSize) + " max",
    mediaInfo.size <= profile.maxFileSize ? "File size fits profile" : "Reduce bitrate or duration"
  ));

  checks.push(check(
    "faststart",
    "Fast start",
    mediaInfo.faststart ? "pass" : "warn",
    mediaInfo.faststart ? "moov before mdat" : "not detected",
    "moov before mdat",
    mediaInfo.faststart ? "Playback startup is optimized" : "Add -movflags +faststart"
  ));

  var score = Math.round((checks.reduce(function (sum, c) {
    return sum + statusRank(c.status);
  }, 0) / checks.length) * 100);

  return { profile, checks, score };
}

export function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "unknown";
  if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB";
  if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
  return bytes + " B";
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

export async function probeMedia(filePath) {
  var result = await runTool("ffprobe", [
    "-v", "quiet",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    filePath,
  ], { timeout: 15000, maxBuffer: 3 * 1024 * 1024 });

  if (result.error) {
    throw new Error("ffprobe failed: " + result.error.message);
  }

  var data = JSON.parse(result.stdout);
  var video = (data.streams || []).find(function (s) { return s.codec_type === "video"; }) || {};
  var audio = (data.streams || []).find(function (s) { return s.codec_type === "audio"; }) || {};
  var fmt = data.format || {};
  return {
    filename: path.basename(filePath),
    width: video.width || 0,
    height: video.height || 0,
    fps: parseFps(video.avg_frame_rate || video.r_frame_rate),
    videoCodec: video.codec_name || "unknown",
    pixelFormat: video.pix_fmt || "unknown",
    duration: parseFloat(fmt.duration || video.duration || 0),
    size: parseInt(fmt.size || 0, 10),
    bitrate: parseInt(fmt.bit_rate || video.bit_rate || 0, 10),
    formatName: fmt.format_name || "unknown",
    audioCodec: audio.codec_name || "none",
    audioBitrate: parseInt(audio.bit_rate || 0, 10),
    audioSampleRate: parseInt(audio.sample_rate || 0, 10),
    faststart: await hasFaststart(filePath),
  };
}

async function runBlackDetect(filePath) {
  var result = await runTool("ffmpeg", [
    "-hide_banner",
    "-i", filePath,
    "-vf", "blackdetect=d=0.25:pix_th=0.10",
    "-an",
    "-f", "null",
    "-",
  ], { timeout: 20000, maxBuffer: 2 * 1024 * 1024 });
  var matches = [...result.stderr.matchAll(/black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)/g)];
  return matches.map(function (m) {
    return { start: parseFloat(m[1]), end: parseFloat(m[2]), duration: parseFloat(m[3]) };
  });
}

async function runSilenceDetect(filePath) {
  var result = await runTool("ffmpeg", [
    "-hide_banner",
    "-i", filePath,
    "-af", "silencedetect=noise=-35dB:d=0.35",
    "-f", "null",
    "-",
  ], { timeout: 20000, maxBuffer: 2 * 1024 * 1024 });
  var starts = [...result.stderr.matchAll(/silence_start:\s*([\d.]+)/g)].map(function (m) { return parseFloat(m[1]); });
  var ends = [...result.stderr.matchAll(/silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)/g)];
  return ends.map(function (m, i) {
    return { start: starts[i] ?? null, end: parseFloat(m[1]), duration: parseFloat(m[2]) };
  });
}

async function runLoudnorm(filePath) {
  var result = await runTool("ffmpeg", [
    "-hide_banner",
    "-i", filePath,
    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
    "-f", "null",
    "-",
  ], { timeout: 20000, maxBuffer: 2 * 1024 * 1024 });
  var start = result.stderr.lastIndexOf("{");
  var end = result.stderr.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    return JSON.parse(result.stderr.slice(start, end + 1));
  } catch {
    return null;
  }
}

async function runCropDetect(filePath) {
  var result = await runTool("ffmpeg", [
    "-hide_banner",
    "-ss", "0",
    "-t", "4",
    "-i", filePath,
    "-vf", "cropdetect=24:16:0",
    "-an",
    "-f", "null",
    "-",
  ], { timeout: 15000, maxBuffer: 2 * 1024 * 1024 });
  var matches = [...result.stderr.matchAll(/crop=(\d+):(\d+):(\d+):(\d+)/g)];
  if (matches.length === 0) return null;
  var last = matches[matches.length - 1];
  return { width: parseInt(last[1], 10), height: parseInt(last[2], 10), x: parseInt(last[3], 10), y: parseInt(last[4], 10) };
}

export async function getQaSignals(filePath, mediaInfo) {
  var [blackFrames, silence, loudnorm, crop] = await Promise.all([
    runBlackDetect(filePath),
    runSilenceDetect(filePath),
    runLoudnorm(filePath),
    runCropDetect(filePath),
  ]);

  var letterbox = false;
  if (crop && mediaInfo.width && mediaInfo.height) {
    letterbox = crop.width < mediaInfo.width * 0.96 || crop.height < mediaInfo.height * 0.96;
  }

  var warnings = [];
  if (blackFrames.some(function (b) { return b.duration >= 0.75; })) warnings.push("Long black segment detected");
  if (silence.some(function (s) { return s.duration >= 1.5; })) warnings.push("Long silence segment detected");
  if (letterbox) warnings.push("Possible border or letterbox detected");
  if (mediaInfo.bitrate > 0 && mediaInfo.bitrate < 2500000) warnings.push("Low video bitrate");

  return {
    blackFrames,
    silence,
    loudness: loudnorm ? {
      inputI: loudnorm.input_i,
      inputTp: loudnorm.input_tp,
      inputLra: loudnorm.input_lra,
      inputThresh: loudnorm.input_thresh,
    } : null,
    crop,
    letterbox,
    warnings,
  };
}

export async function listRunFiles(runId) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir || !existsSync(finalDir)) return [];
  var entries = await readdir(finalDir);
  var files = [];
  for (var entry of entries) {
    var ext = path.extname(entry).toLowerCase();
    if (!VIDEO_EXTS.has(ext) && !IMAGE_EXTS.has(ext)) continue;
    var filePath = path.join(finalDir, entry);
    var stats = await stat(filePath);
    files.push({
      name: entry,
      path: filePath,
      size: stats.size,
      created: stats.birthtime.toISOString(),
      type: VIDEO_EXTS.has(ext) ? "video" : "image",
    });
  }
  return files.sort(function (a, b) { return a.name.localeCompare(b.name); });
}

async function readRunCaptions(runId) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir) return null;
  var captionPath = path.join(finalDir, "captions.srt");
  if (!existsSync(captionPath)) return null;
  return readFile(captionPath, "utf8");
}

async function readRunConfig(runId) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir) return null;
  var configPath = path.join(finalDir, "run_config.json");
  if (!existsSync(configPath)) return null;
  try {
    return JSON.parse(await readFile(configPath, "utf8"));
  } catch {
    return null;
  }
}

async function listCoverFrames(runId) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir || !existsSync(finalDir)) return [];
  var entries = await readdir(finalDir);
  return entries
    .filter(function (entry) { return /^cover_.*\.jpg$/i.test(entry); })
    .sort()
    .map(function (entry) { return { name: entry, url: "/api/preview?runId=" + encodeURIComponent(runId) + "&file=" + encodeURIComponent(entry) }; });
}

export async function analyzeReelsRun({ runId, profileId = "organic", sourceFile = null }) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir || !existsSync(finalDir)) {
    var err = new Error("Run output not found");
    err.status = 404;
    throw err;
  }

  var files = await listRunFiles(runId);
  var videoFiles = files.filter(function (file) { return file.type === "video"; });
  if (videoFiles.length === 0) {
    var noVideo = new Error("No video files found in run");
    noVideo.status = 404;
    throw noVideo;
  }

  var sourcePath = sourceFile ? resolveUploadPath(sourceFile) : null;
  if (sourcePath && !existsSync(sourcePath)) sourcePath = null;
  var captionText = await readRunCaptions(runId);
  var runConfig = await readRunConfig(runId);
  var variantReports = [];
  for (var videoFile of videoFiles) {
    var itemMediaInfo = await probeMedia(videoFile.path);
    var itemValidation = validateMediaInfo(itemMediaInfo, profileId);
    var itemQaSignals = await getQaSignals(videoFile.path, itemMediaInfo);
    var itemCaptions = analyzeCaptions(captionText, itemMediaInfo);
    var itemQualityMetrics = await getQualityMetrics({
      sourcePath,
      variantPath: videoFile.path,
      mediaInfo: itemMediaInfo,
    });
    var itemScore = Math.max(0, itemValidation.score - Math.min(20, itemQaSignals.warnings.length * 5));
    var estimatedDifference = itemQualityMetrics && itemQualityMetrics.ssim !== null && itemQualityMetrics.ssim !== undefined
      ? (1 - itemQualityMetrics.ssim) * 100
      : null;
    var scoreBundle = variantScoreBundle({
      mediaInfo: itemMediaInfo,
      qualityMetrics: itemQualityMetrics,
      checks: itemValidation.checks,
      warnings: itemQaSignals.warnings,
      differenceFromOriginal: estimatedDifference,
      qualitySignals: [
        itemQualityMetrics && itemQualityMetrics.vmaf !== null ? "vmaf" : null,
        itemQualityMetrics && itemQualityMetrics.ssim !== null ? "ssim" : null,
        itemQualityMetrics && itemQualityMetrics.psnr !== null ? "psnr" : null,
      ].filter(Boolean),
      differenceSignals: ["analyze route"],
    });
    variantReports.push({
      file: videoFile.name,
      score: itemScore,
      ...scoreBundle,
      checks: itemValidation.checks,
      mediaInfo: itemMediaInfo,
      qaSignals: itemQaSignals,
      qualityMetrics: itemQualityMetrics,
      captions: itemCaptions,
    });
  }

  var primary = videoFiles[0];
  var primaryReport = variantReports[0];
  var coverFrames = await listCoverFrames(runId);
  var totalChecks = variantReports.flatMap(function (report) { return report.checks; });
  var summary = {
    pass: totalChecks.filter(function (c) { return c.status === "pass"; }).length,
    warn: totalChecks.filter(function (c) { return c.status === "warn"; }).length,
    fail: totalChecks.filter(function (c) { return c.status === "fail"; }).length,
    warnings: variantReports.reduce(function (sum, report) { return sum + report.qaSignals.warnings.length; }, 0),
  };

  var result = {
    runId,
    profileId: primaryReport.checks.length ? (REELS_PROFILES[profileId] || REELS_PROFILES.organic).id : "organic",
    profile: REELS_PROFILES[profileId] || REELS_PROFILES.organic,
    score: Math.round(variantReports.reduce(function (sum, report) { return sum + report.score; }, 0) / variantReports.length),
    checks: primaryReport.checks,
    mediaInfo: primaryReport.mediaInfo,
    qaSignals: primaryReport.qaSignals,
    variantReports,
    summary,
    coverFrames,
    analyzedFile: primary.name,
    filesAnalyzed: videoFiles.length,
    sourceFile: sourceFile || null,
    variantPreset: runConfig && runConfig.variantPreset || null,
    variantOptions: runConfig && runConfig.variantOptions || {},
    qualityGate: runConfig && runConfig.qualityGate || null,
    attemptedCandidates: runConfig && runConfig.attemptedCandidates || variantReports.length,
    keptCandidates: runConfig && runConfig.keptCandidates || variantReports.length,
    rejectedCandidates: runConfig && runConfig.rejectedCandidates || 0,
    rejectionReasons: runConfig && runConfig.rejectionReasons || {},
    captions: primaryReport.captions,
    generatedAt: new Date().toISOString(),
  };

  await writeFile(path.join(finalDir, "reels_manifest.json"), JSON.stringify(result, null, 2));
  return result;
}

export function formatManifestCsv(manifest) {
  var rows = [["file", "score", "qualityRetained", "differenceFromOriginal", "recommendedAction", "width", "height", "fps", "duration", "codec", "bitrate", "vmaf", "ssim", "psnr", "captions", "warnings", "failures"]];
  var reports = manifest.variantReports || [];
  for (var report of reports) {
    var info = report.mediaInfo || {};
    var metrics = report.qualityMetrics || {};
    var failures = (report.checks || []).filter(function (c) { return c.status === "fail"; }).map(function (c) { return c.id; }).join("|");
    rows.push([
      report.file,
      report.score,
      report.qualityRetained,
      report.differenceFromOriginal,
      report.recommendedAction,
      info.width,
      info.height,
      info.fps,
      info.duration,
      info.videoCodec,
      info.bitrate,
      metrics.vmaf,
      metrics.ssim,
      metrics.psnr,
      report.captions && report.captions.available ? report.captions.summary.cues : "none",
      (report.qaSignals && report.qaSignals.warnings || []).join("|"),
      failures,
    ]);
  }
  return rows.map(function (row) {
    return row.map(function (cell) {
      var value = cell === undefined || cell === null ? "" : String(cell);
      return "\"" + value.replace(/"/g, "\"\"") + "\"";
    }).join(",");
  }).join("\n");
}

export async function saveRunCaptions({ runId, text }) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir || !existsSync(finalDir)) {
    var err = new Error("Run output not found");
    err.status = 404;
    throw err;
  }
  var value = String(text || "").slice(0, 512 * 1024);
  var analysis = analyzeCaptions(value);
  if (!value || analysis.cues.length === 0) {
    var invalid = new Error("Invalid SRT captions");
    invalid.status = 400;
    throw invalid;
  }
  var captionPath = ensureInside(finalDir, path.join(finalDir, "captions.srt"));
  await writeFile(captionPath, value);
  return { saved: true, runId, cues: analysis.cues.length };
}

export async function extractCoverFrame({ runId, filename, timestamp = 1 }) {
  var safeName = safeBasename(filename);
  var filePath = resolveRunFile(runId, safeName);
  if (!safeName || !filePath || !existsSync(filePath)) {
    var err = new Error("Video not found");
    err.status = 404;
    throw err;
  }

  var finalDir = resolveRunFinalDir(runId);
  var seconds = Math.max(0, Math.min(parseFloat(timestamp) || 0, 600));
  var base = safeName.replace(/\.[^.]+$/, "");
  var coverName = "cover_" + base.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 50) + "_" + Math.round(seconds * 10) + ".jpg";
  var coverPath = ensureInside(finalDir, path.join(finalDir, coverName));
  if (!coverPath) {
    var invalid = new Error("Invalid cover path");
    invalid.status = 400;
    throw invalid;
  }

  var result = await runTool("ffmpeg", [
    "-ss", String(seconds),
    "-i", filePath,
    "-vframes", "1",
    "-q:v", "2",
    "-y",
    coverPath,
  ], { timeout: 15000, maxBuffer: 1024 * 1024 });

  if (result.error) {
    var err2 = new Error("Cover extraction failed");
    err2.status = 500;
    throw err2;
  }

  return {
    name: coverName,
    url: "/api/preview?runId=" + encodeURIComponent(runId) + "&file=" + encodeURIComponent(coverName),
  };
}

export async function extractCoverCandidates({ runId, filename, count = 5 }) {
  var safeName = safeBasename(filename);
  var filePath = resolveRunFile(runId, safeName);
  if (!safeName || !filePath || !existsSync(filePath)) {
    var err = new Error("Video not found");
    err.status = 404;
    throw err;
  }
  var mediaInfo = await probeMedia(filePath);
  var duration = Math.max(1, mediaInfo.duration || 1);
  var n = Math.max(1, Math.min(8, parseInt(count, 10) || 5));
  var covers = [];
  for (var i = 0; i < n; i++) {
    var timestamp = Math.min(duration - 0.1, Math.max(0, duration * ((i + 1) / (n + 1))));
    covers.push(await extractCoverFrame({ runId, filename: safeName, timestamp }));
  }
  return covers;
}

export async function listRuns() {
  if (!existsSync(RUNS_DIR)) return [];
  var entries = await readdir(RUNS_DIR);
  var runs = [];
  for (var runId of entries) {
    var root = getRunRoot(runId);
    if (!root || !existsSync(root)) continue;
    var finalDir = path.join(root, "final");
    var rootStats = await stat(root);
    var files = existsSync(finalDir) ? await listRunFiles(runId) : [];
    var manifestPath = path.join(finalDir, "reels_manifest.json");
    var manifest = null;
    if (existsSync(manifestPath)) {
      try {
        manifest = JSON.parse(await readFile(manifestPath, "utf8"));
      } catch {
        manifest = null;
      }
    }
    runs.push({
      runId,
      created: rootStats.birthtime.toISOString(),
      updated: rootStats.mtime.toISOString(),
      count: files.length,
      size: files.reduce(function (sum, file) { return sum + file.size; }, 0),
      score: manifest && manifest.score,
      profileId: manifest && manifest.profileId,
    });
  }
  return runs.sort(function (a, b) { return b.created.localeCompare(a.created); });
}

export async function deleteRun(runId) {
  var root = getRunRoot(runId);
  if (!root) {
    var invalid = new Error("Invalid runId");
    invalid.status = 400;
    throw invalid;
  }
  await rm(root, { recursive: true, force: true });
  return { success: true, runId };
}

export async function cleanupOldFiles({ olderThanDays = 14, maxBytes = 0 } = {}) {
  var cutoff = Date.now() - olderThanDays * 24 * 60 * 60 * 1000;
  var deleted = [];
  if (existsSync(RUNS_DIR)) {
    var entries = await readdir(RUNS_DIR);
    for (var runId of entries) {
      var root = getRunRoot(runId);
      if (!root || !existsSync(root)) continue;
      var stats = await stat(root);
      if (stats.mtime.getTime() < cutoff) {
        await rm(root, { recursive: true, force: true });
        deleted.push(runId);
      }
    }
  }
  if (maxBytes > 0 && existsSync(RUNS_DIR)) {
    var runs = await listRuns();
    var totalBytes = runs.reduce(function (sum, run) { return sum + run.size; }, 0);
    var oldestFirst = [...runs].sort(function (a, b) { return a.created.localeCompare(b.created); });
    for (var run of oldestFirst) {
      if (totalBytes <= maxBytes) break;
      var root = getRunRoot(run.runId);
      if (!root || !existsSync(root)) continue;
      await rm(root, { recursive: true, force: true });
      deleted.push(run.runId);
      totalBytes -= run.size;
    }
  }
  await mkdir(OUTPUT_DIR, { recursive: true });
  return { deleted, olderThanDays, maxBytes };
}
