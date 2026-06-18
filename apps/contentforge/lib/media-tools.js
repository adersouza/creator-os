import { execFile, spawnSync } from "child_process";
import crypto from "crypto";
import { mkdir, readdir, stat } from "fs/promises";
import { existsSync } from "fs";
import path from "path";
import {
  ensureInside,
  getRunFinalDir,
  resolveRunFile,
  resolveUploadPath,
  safeBasename,
} from "./paths.js";
import { createTextOverlayPng, overlayYExpression } from "./overlay.js";

var VIDEO_EXTS = new Set([".mp4", ".mov", ".webm", ".m4v"]);
var IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".heic"]);
var AUDIO_EXTS = new Set([".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"]);
var filterSupportCache = new Map();

function hasFfmpegFilter(name) {
  if (process.env.CONTENTFORGE_ASSUME_DRAWTEXT === "1" && name === "drawtext") return true;
  if (filterSupportCache.has(name)) return filterSupportCache.get(name);
  var result = spawnSync("ffmpeg", ["-hide_banner", "-filters"], { encoding: "utf8", maxBuffer: 1024 * 1024 });
  var output = (result.stdout || "") + (result.stderr || "");
  var supported = new RegExp("\\b" + name + "\\b").test(output);
  filterSupportCache.set(name, supported);
  return supported;
}

function runTool(command, args, options = {}) {
  return new Promise(function (resolve, reject) {
    execFile(command, args, {
      timeout: options.timeout || 120000,
      maxBuffer: options.maxBuffer || 4 * 1024 * 1024,
    }, function (error, stdout, stderr) {
      if (error) {
        reject(new Error((stderr || error.message).slice(-1200)));
      } else {
        resolve(stdout || "");
      }
    });
  });
}

export function buildConvertArgs(inputPath, outputPath, mode, options = {}) {
  if (mode === "mp4") {
    return ["-i", inputPath, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-y", outputPath];
  }
  if (mode === "jpg") {
    return ["-i", inputPath, "-frames:v", "1", "-q:v", "2", "-y", outputPath];
  }
  if (mode === "gif") {
    var fps = Math.max(6, Math.min(30, parseInt(options.fps, 10) || 12));
    var width = Math.max(240, Math.min(1080, parseInt(options.width, 10) || 540));
    var loop = options.loop === "once" ? "-1" : "0";
    var filters = [
      "fps=" + fps,
      "scale=" + width + ":-1:flags=lanczos",
      "split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=sierra2_4a",
    ];
    return ["-i", inputPath, "-lavfi", filters.join(","), "-loop", loop, "-y", outputPath];
  }
  throw new Error("Unsupported conversion mode");
}

export function buildClipArgs(inputPath, outputPath, start, duration) {
  return ["-ss", String(start), "-i", inputPath, "-t", String(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-y", outputPath];
}

export function buildFramesArgs(inputPath, outputPattern, everySeconds, maxFrames) {
  return ["-i", inputPath, "-vf", "fps=1/" + everySeconds, "-frames:v", String(maxFrames), "-y", outputPattern];
}

export function escapeDrawtext(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/\r\n|\r|\n/g, "\\n")
    .replace(/:/g, "\\:")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;")
    .replace(/%/g, "\\%")
    .replace(/'/g, "\\'")
    .replace(/\[/g, "\\[")
    .replace(/\]/g, "\\]");
}

function buildOverlayFilter(options = {}) {
  var text = (options.overlayText || options.watermarkText || "").trim();
  if (!text) return null;
  if (!hasFfmpegFilter("drawtext")) return null;
  var position = options.overlayPosition || "bottom";
  var y = "h-th-120";
  if (position === "top") y = "100";
  if (position === "center") y = "(h-th)/2";
  var fontSize = Math.max(18, Math.min(96, parseInt(options.overlayFontSize, 10) || 42));
  return "drawtext=text='" + escapeDrawtext(text.slice(0, 120)) +
    "':x=(w-tw)/2:y=" + y +
    ":fontsize=" + fontSize +
    ":fontcolor=white@0.86:box=1:boxcolor=black@0.35:boxborderw=18";
}

function baseFilterChain(filters) {
  return filters.length ? filters.join(",") : "null";
}

export function buildEditArgs(inputPath, outputPath, options = {}, replacementAudioPath = null) {
  var args = [];
  var trimStart = Math.max(0, parseFloat(options.trimStart) || 0);
  var trimDuration = Math.max(0, parseFloat(options.trimDuration) || 0);
  if (trimStart > 0) args.push("-ss", String(trimStart));
  args.push("-i", inputPath);
  if (replacementAudioPath) args.push("-i", replacementAudioPath);
  var overlayInputIndex = replacementAudioPath ? 2 : 1;
  var overlayImagePath = !hasFfmpegFilter("drawtext") ? options.overlayImagePath : null;
  if (overlayImagePath) args.push("-loop", "1", "-i", overlayImagePath);
  if (trimDuration > 0) args.push("-t", String(trimDuration));

  var filters = [];
  var speed = Math.max(0.25, Math.min(4, parseFloat(options.speed) || 1));
  var width = parseInt(options.width, 10);
  var height = parseInt(options.height, 10);
  if (width > 0 && height > 0) filters.push("scale=" + width + ":" + height + ":flags=lanczos");
  if (speed !== 1) filters.push("setpts=" + (1 / speed).toFixed(4) + "*PTS");
  var overlay = buildOverlayFilter(options);
  if (overlay) filters.push(overlay);
  if (overlayImagePath) {
    args.push("-filter_complex", "[0:v]" + baseFilterChain(filters) + "[base];[base][" + overlayInputIndex + ":v]overlay=(W-w)/2:" + overlayYExpression(options.overlayPosition) + ":format=auto[v]");
    args.push("-map", "[v]");
    if (replacementAudioPath) {
      args.push("-map", "1:a:0");
    } else {
      args.push("-map", "0:a?");
    }
  } else if (filters.length) {
    args.push("-vf", filters.join(","));
  }

  var audioFilters = [];
  if (!replacementAudioPath && speed !== 1) audioFilters.push(buildAtempo(speed));
  if (options.normalizeAudio) audioFilters.push("loudnorm=I=-14:TP=-1.5:LRA=11");
  if (audioFilters.length) args.push("-af", audioFilters.join(","));

  if (replacementAudioPath && !overlayImagePath) {
    args.push("-map", "0:v:0", "-map", "1:a:0", "-shortest");
  }
  if (replacementAudioPath || overlayImagePath) args.push("-shortest");
  args.push("-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-y", outputPath);
  return args;
}

function buildAtempo(speed) {
  var parts = [];
  var remaining = speed;
  while (remaining > 2) {
    parts.push("atempo=2");
    remaining = remaining / 2;
  }
  while (remaining < 0.5) {
    parts.push("atempo=0.5");
    remaining = remaining / 0.5;
  }
  parts.push("atempo=" + remaining.toFixed(4));
  return parts.join(",");
}

async function createToolRun(prefix) {
  var runId = crypto.randomBytes(4).toString("hex");
  var finalDir = getRunFinalDir(runId);
  await mkdir(finalDir, { recursive: true });
  return { runId, finalDir, prefix: prefix || "tool" };
}

function resolveInput({ inputFile, runId, filename }) {
  if (runId && filename) {
    var safeName = safeBasename(filename);
    var runFile = resolveRunFile(runId, safeName);
    if (!safeName || !runFile || !existsSync(runFile)) return null;
    return runFile;
  }
  var uploadPath = resolveUploadPath(inputFile);
  if (!uploadPath || !existsSync(uploadPath)) return null;
  return uploadPath;
}

function outputUrl(runId, name) {
  return "/api/preview?runId=" + encodeURIComponent(runId) + "&file=" + encodeURIComponent(name);
}

async function listOutputFiles(runId, finalDir) {
  var entries = await readdir(finalDir);
  var files = [];
  for (var entry of entries) {
    var stats = await stat(path.join(finalDir, entry));
    if (!stats.isFile() || entry.startsWith("overlay_")) continue;
    files.push({ name: entry, size: stats.size, url: outputUrl(runId, entry) });
  }
  return files.sort(function (a, b) { return a.name.localeCompare(b.name); });
}

export async function convertMedia(params) {
  var inputPath = resolveInput(params);
  if (!inputPath) {
    var err = new Error("Input file not found");
    err.status = 404;
    throw err;
  }
  var mode = params.mode || "mp4";
  var ext = mode === "jpg" ? ".jpg" : mode === "gif" ? ".gif" : ".mp4";
  var sourceExt = path.extname(inputPath).toLowerCase();
  if (mode === "jpg" && !IMAGE_EXTS.has(sourceExt) && !VIDEO_EXTS.has(sourceExt)) throw new Error("Unsupported image source");
  if ((mode === "mp4" || mode === "gif") && !VIDEO_EXTS.has(sourceExt)) throw new Error("Unsupported video source");

  var run = await createToolRun("convert");
  var base = path.basename(inputPath).replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 50);
  var outName = "convert_" + base + ext;
  var outputPath = ensureInside(run.finalDir, path.join(run.finalDir, outName));
  await runTool("ffmpeg", buildConvertArgs(inputPath, outputPath, mode, params));
  return { runId: run.runId, files: await listOutputFiles(run.runId, run.finalDir) };
}

export async function exportGif(params) {
  return convertMedia({ ...params, mode: "gif" });
}

export async function generateClips(params) {
  var inputPath = resolveInput(params);
  if (!inputPath) {
    var err = new Error("Input file not found");
    err.status = 404;
    throw err;
  }
  var duration = Math.max(2, Math.min(120, parseFloat(params.clipLength) || 15));
  var count = Math.max(1, Math.min(20, parseInt(params.count, 10) || 5));
  var run = await createToolRun("clips");
  for (var i = 0; i < count; i++) {
    var start = i * duration;
    var outName = "clip_" + String(i + 1).padStart(2, "0") + ".mp4";
    var outPath = ensureInside(run.finalDir, path.join(run.finalDir, outName));
    await runTool("ffmpeg", buildClipArgs(inputPath, outPath, start, duration));
  }
  return { runId: run.runId, files: await listOutputFiles(run.runId, run.finalDir) };
}

export async function generateFrames(params) {
  var inputPath = resolveInput(params);
  if (!inputPath) {
    var err = new Error("Input file not found");
    err.status = 404;
    throw err;
  }
  var everySeconds = Math.max(0.2, Math.min(30, parseFloat(params.everySeconds) || 1));
  var maxFrames = Math.max(1, Math.min(200, parseInt(params.maxFrames, 10) || 20));
  var run = await createToolRun("frames");
  var outputPattern = ensureInside(run.finalDir, path.join(run.finalDir, "frame_%03d.png"));
  await runTool("ffmpeg", buildFramesArgs(inputPath, outputPattern, everySeconds, maxFrames));
  return { runId: run.runId, files: await listOutputFiles(run.runId, run.finalDir) };
}

export async function editMedia(params) {
  var inputPath = resolveInput(params);
  if (!inputPath) {
    var err = new Error("Input file not found");
    err.status = 404;
    throw err;
  }
  var replacementAudioPath = null;
  if (params.replacementAudioFile) {
    replacementAudioPath = resolveUploadPath(params.replacementAudioFile);
    var audioExt = replacementAudioPath ? path.extname(replacementAudioPath).toLowerCase() : "";
    if (!replacementAudioPath || !existsSync(replacementAudioPath) || !AUDIO_EXTS.has(audioExt)) {
      var audioErr = new Error("Replacement audio file not found or unsupported");
      audioErr.status = 404;
      throw audioErr;
    }
  }
  var run = await createToolRun("edit");
  var outPath = ensureInside(run.finalDir, path.join(run.finalDir, "edited.mp4"));
  var overlayPath = await createTextOverlayPng({
    ...params,
    width: params.width || 1080,
    height: params.height || 1920,
    outputDir: path.join(run.finalDir, "_assets"),
  });
  await runTool("ffmpeg", buildEditArgs(inputPath, outPath, { ...params, overlayImagePath: overlayPath }, replacementAudioPath));
  return { runId: run.runId, files: await listOutputFiles(run.runId, run.finalDir) };
}
