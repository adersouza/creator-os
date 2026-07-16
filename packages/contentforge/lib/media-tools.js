import { spawnSync } from "child_process";
import { overlayYExpression } from "./overlay.js";

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
