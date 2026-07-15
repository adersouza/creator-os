import { execFile } from "child_process";
import { open, rm } from "fs/promises";
import path from "path";
import {
  getRunRoot,
} from "./paths.js";
import { REELS_PROFILES } from "./reels-profiles.js";

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
  var aspectLabel = profile.aspectLabel || "9:16";

  checks.push(check(
    "aspect",
    "Aspect ratio",
    aspectDelta <= profile.aspectTolerance ? "pass" : "warn",
    width + "x" + height,
    aspectLabel,
    aspectDelta <= profile.aspectTolerance ? "Framing matches profile" : "Preview/crop to " + aspectLabel
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

function formatBytes(bytes) {
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
