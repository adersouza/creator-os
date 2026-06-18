import { COLOR_PRESETS, CROP_STYLES, BORDER_STYLES, DEVICE_PREFIXES } from "./presets.js";
import { applyOutputProfileArgs, containBlurFilterForProfile, getReelsProfile, scaleFilterForProfile } from "./reels-profiles.js";
import { getVariantPreset } from "./variant-engine.js";
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

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function randInt(min, max) {
  return Math.floor(rand(min, max + 1));
}

function pick(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
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

function overlayFilter(options = {}) {
  var text = (options.overlayText || options.watermarkText || "").trim();
  if (!text) return null;
  if (!hasFfmpegFilter("drawtext")) return null;
  var position = options.overlayPosition || "bottom";
  var y = "h-th-140";
  if (position === "top") y = "120";
  if (position === "center") y = "(h-th)/2";
  var fontSize = Math.max(18, Math.min(96, parseInt(options.overlayFontSize, 10) || 42));
  var opacity = Math.max(0.35, Math.min(1, parseFloat(options.overlayOpacity) || 0.82));
  return "drawtext=text='" + escapeDrawtext(text.slice(0, 120)) +
    "':x=(w-tw)/2:y=" + y +
    ":fontsize=" + fontSize +
    ":fontcolor=white@" + opacity.toFixed(2) +
    ":box=1:boxcolor=black@0.35:boxborderw=18";
}

function overlayImagePath(options = {}) {
  if (hasFfmpegFilter("drawtext")) return null;
  return options.overlayImagePath || null;
}

function baseFilterChain(filters) {
  return filters.length ? filters.join(",") : "null";
}

function horizontalFlipAllowed(options = {}) {
  return options.allowHorizontalFlip !== false && !options.preserveBurnedCaptions;
}

function strongVisualTransformsAllowed(options = {}) {
  return options.allowStrongColorShift !== false && !options.preserveBurnedCaptions;
}

function colorTransformsAllowed(options = {}) {
  return options.preserveColor !== true;
}

function audioTransformsAllowed(options = {}) {
  return options.preserveAudio !== true;
}

function timingTransformsAllowed(options = {}) {
  return options.preserveTiming !== true;
}

function geometryTransformsAllowed(options = {}) {
  return options.preserveGeometry !== true;
}

function frameRateTransformsAllowed(options = {}) {
  return options.preserveFrameRate !== true;
}

function pushVideoFilters(args, filters, options = {}, hasAudio = true) {
  var imagePath = overlayImagePath(options);
  if (!imagePath) {
    args.push("-vf", filters.join(","));
    return;
  }
  args.push("-loop", "1", "-i", imagePath);
  args.push("-filter_complex", "[0:v]" + baseFilterChain(filters) + "[base];[base][1:v]overlay=(W-w)/2:" + overlayYExpression(options.overlayPosition) + ":format=auto[v]");
  args.push("-map", "[v]");
  if (hasAudio) args.push("-map", "0:a?");
  args.push("-shortest");
}

function pushImageFilters(args, filters, options = {}) {
  var imagePath = overlayImagePath(options);
  if (!imagePath) {
    if (filters.length > 0) args.push("-vf", filters.join(","));
    return;
  }
  args.push("-i", imagePath);
  args.push("-filter_complex", "[0:v]" + baseFilterChain(filters) + "[base];[base][1:v]overlay=(W-w)/2:" + overlayYExpression(options.overlayPosition) + ":format=auto[v]");
  args.push("-map", "[v]", "-frames:v", "1");
}

function generateDeviceFilename() {
  var prefix = pick(DEVICE_PREFIXES);
  var ts = Date.now() - randInt(86400000, 86400000 * 30);
  var date = new Date(ts);
  var y = date.getFullYear();
  var mo = String(date.getMonth() + 1).padStart(2, "0");
  var d = String(date.getDate()).padStart(2, "0");
  var h = String(date.getHours()).padStart(2, "0");
  var mi = String(date.getMinutes()).padStart(2, "0");
  var se = String(date.getSeconds()).padStart(2, "0");
  var ms = String(date.getMilliseconds()).padStart(3, "0");
  var dateStr = y + mo + d;
  var timeStr = h + mi + se;

  if (prefix === "IMG_" || prefix === "VID_") {
    return prefix + dateStr + "_" + timeStr + "_" + randInt(100, 999);
  }
  if (prefix === "PXL_") {
    return prefix + dateStr + "_" + timeStr + ms;
  }
  if (prefix === "RPReplay_") {
    return prefix + "Final" + dateStr + randInt(10, 99);
  }
  return prefix + dateStr + "_" + randInt(1000, 9999);
}

// ─── Device Profiles (research-backed container forensics) ───
// Each profile matches the encoding characteristics of real device captures.
// Source: compression forensics research — container atoms, bitrate, GOP, audio rate, handler names.

var DEVICE_PROFILES = {
  iphone: {
    models: ["iPhone 16 Pro Max", "iPhone 16 Pro", "iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 14 Pro", "iPhone 13"],
    software: ["18.0", "18.1", "17.6.1", "17.4.1", "17.3", "17.1.1", "16.7.2"],
    bitrate: function() { return randInt(20000, 24000); },
    maxrate: function() { return randInt(26000, 30000); },
    crf: null, // iPhone uses ABR, not CRF — we use -b:v instead
    gop: function() { return 60; }, // 2s GOP at 30fps
    bframes: function() { return randInt(1, 2); },
    refs: function() { return randInt(2, 4); },
    audioRate: 44100,
    audioBitrate: 128,
    handlerVideo: "Core Media Video",
    handlerAudio: "Core Media Audio",
    profile: "high",
    level: "4.2",
    colorFlags: true,
    x264Params: function(br, gop, bf, refs) {
      return "keyint=" + gop + ":min-keyint=" + Math.floor(gop / 2) +
        ":bframes=" + bf + ":ref=" + refs +
        ":weightp=0:aq-mode=1:no-mbtree:cqm=flat" +
        ":nal-hrd=cbr:vbv-maxrate=" + Math.round(br * 1.3) + ":vbv-bufsize=" + Math.round(br * 1.3) +
        ":colorprim=bt709:transfer=bt709:colormatrix=bt709";
    },
  },
  samsung: {
    models: ["Samsung SM-S928B", "Samsung SM-S926B", "Samsung SM-S911B", "Samsung SM-G991B", "Samsung SM-A546B"],
    software: ["Android 15", "Android 14", "OneUI 6.1", "OneUI 7.0"],
    bitrate: function() { return randInt(17000, 20000); },
    maxrate: function() { return randInt(20000, 24000); },
    crf: null,
    gop: function() { return 30; }, // 1s GOP at 30fps (Android default)
    bframes: function() { return 0; }, // Android hardware encoders don't use B-frames
    refs: function() { return randInt(1, 2); },
    audioRate: 48000,
    audioBitrate: 256,
    handlerVideo: "VideoHandle",
    handlerAudio: "SoundHandle",
    profile: "high",
    level: "4.1",
    colorFlags: true,
    x264Params: function(br, gop, bf, refs) {
      return "keyint=" + gop + ":min-keyint=" + gop + ":scenecut=0" +
        ":bframes=0:ref=" + refs +
        ":weightp=0:no-mbtree:aq-mode=0" +
        ":nal-hrd=cbr:vbv-maxrate=" + Math.round(br * 1.2) + ":vbv-bufsize=" + Math.round(br * 1.2) +
        ":cqm=flat:me=dia:subme=1:trellis=0" +
        ":colorprim=bt709:transfer=bt709:colormatrix=bt709";
    },
  },
  pixel: {
    models: ["Pixel 9 Pro", "Pixel 9", "Pixel 8 Pro", "Pixel 8", "Pixel 7a"],
    software: ["Android 15", "Android 14"],
    bitrate: function() { return randInt(12000, 16000); },
    maxrate: function() { return randInt(16000, 20000); },
    crf: null,
    gop: function() { return 30; },
    bframes: function() { return 0; },
    refs: function() { return 1; },
    audioRate: 48000,
    audioBitrate: 192,
    handlerVideo: "VideoHandle",
    handlerAudio: "SoundHandle",
    profile: "high",
    level: "4.1",
    colorFlags: true,
    x264Params: function(br, gop, bf, refs) {
      return "keyint=" + gop + ":min-keyint=" + gop + ":scenecut=0" +
        ":bframes=0:ref=1" +
        ":weightp=0:no-mbtree:aq-mode=0" +
        ":nal-hrd=cbr:vbv-maxrate=" + Math.round(br * 1.2) + ":vbv-bufsize=" + Math.round(br * 1.2) +
        ":cqm=flat:me=dia:subme=1:trellis=0" +
        ":colorprim=bt709:transfer=bt709:colormatrix=bt709";
    },
  },
};

function pickDeviceProfile() {
  var types = Object.keys(DEVICE_PROFILES);
  var type = pick(types);
  return { type, profile: DEVICE_PROFILES[type] };
}

// ─── Phase 1: Creative Remix ───
export function buildPhase1Args(inputPath, outputPath, editIndex, opts) {
  var flip = opts.flip;
  var vertical = opts.vertical;
  var hasAudio = opts.hasAudio !== false;
  var outputProfile = opts.outputProfile || "organic";
  var variantPreset = getVariantPreset(opts.variantPreset, opts.variantOptions || {}, opts.level);
  var allowColorTransforms = colorTransformsAllowed(opts.variantOptions || {});

  var colorPreset = COLOR_PRESETS[editIndex % COLOR_PRESETS.length];
  var cropStyle = CROP_STYLES[editIndex % CROP_STYLES.length];
  var borderStyle = BORDER_STYLES[editIndex % BORDER_STYLES.length];
  var speed = rand(1 - variantPreset.speedShift, 1 + variantPreset.speedShift);

  var filters = [];
  var overlay = overlayFilter(opts.variantOptions || {});

  // Speed via PTS
  filters.push("setpts=" + (1 / speed).toFixed(4) + "*PTS");

  // Color preset
  if (allowColorTransforms && variantPreset.id !== "quality" && colorPreset.eq) {
    filters.push(colorPreset.eq);
  } else if (allowColorTransforms && variantPreset.colorShift > 0) {
    var qGamma = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
    var qSat = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
    filters.push("eq=gamma=" + qGamma.toFixed(4) + ":saturation=" + qSat.toFixed(4));
  }

  if (variantPreset.crop < 0.999) {
    filters.push(
      "crop=iw*" + variantPreset.crop.toFixed(4) + ":ih*" + variantPreset.crop.toFixed(4) +
      ":iw*(1-" + variantPreset.crop.toFixed(4) + ")*" + cropStyle.x +
      ":ih*(1-" + variantPreset.crop.toFixed(4) + ")*" + cropStyle.y
    );
  }

  // Scale to exact target
  if (vertical) {
    filters.push(variantPreset.preserveFrame ? containBlurFilterForProfile(outputProfile) : scaleFilterForProfile(outputProfile));
  } else {
    filters.push("scale=-2:1080:flags=lanczos");
  }

  if (flip && horizontalFlipAllowed(opts.variantOptions || {})) {
    filters.push("hflip");
  }

  // Borders
  if (variantPreset.id !== "quality" && borderStyle === "vignette") {
    filters.push("vignette=PI/4");
  } else if (variantPreset.id !== "quality" && borderStyle === "thin-white") {
    filters.push("pad=iw+4:ih+4:2:2:white");
    filters.push("scale=1080:1920:flags=lanczos");
  } else if (variantPreset.id !== "quality" && borderStyle === "letterbox") {
    filters.push("pad=iw:ih+40:0:20:black");
    filters.push("scale=1080:1920:flags=lanczos");
  } else if (variantPreset.id !== "quality" && borderStyle === "dark-gray") {
    filters.push("pad=iw+4:ih+4:2:2:0x1a1a1a");
    filters.push("scale=1080:1920:flags=lanczos");
  }

  // Per-edit gamma (clamped)
  var editGamma = Math.min(1.05, 1 - variantPreset.colorShift + (editIndex * variantPreset.colorShift / 10));
  var editBright = Math.max(-0.02, Math.min(0.02, -variantPreset.colorShift / 3 + (editIndex * variantPreset.colorShift / 20)));
  if (allowColorTransforms && variantPreset.colorShift > 0) {
    filters.push("eq=gamma=" + editGamma.toFixed(3) + ":brightness=" + editBright.toFixed(3));
  }
  if (overlay) filters.push(overlay);

  var args = ["-i", inputPath];
  pushVideoFilters(args, filters, opts.variantOptions || {}, hasAudio);

  if (hasAudio) {
    args.push("-af", "atempo=" + speed.toFixed(4));
  } else {
    args.push("-an");
  }

  args.push("-preset", variantPreset.id === "quality" ? "slow" : "medium", "-crf", String(variantPreset.videoCrf));
  applyOutputProfileArgs(args, outputProfile, hasAudio, { crf: variantPreset.videoCrf });
  args.push("-y", outputPath);

  return args;
}

// ─── Phase 2: Hash Breaking + Device Profile Spoofing ───
// Research-backed (2026):
// - PDQ: 256-bit DCT hash on 64x64 grid, 31-bit Hamming threshold
// - SSCD: 512-d neural embeddings, cosine similarity >= 0.75 = match
// - Texture bias exploit: sharpen + grain shift embeddings 0.10-0.25 at SSIM > 0.90
// - Audio fingerprinting: pitch shift ±5-50 cents + time stretch breaks spectral landmarks
// - Container forensics: encoder strings, handler names, bitrate, ftyp, SEI

export function buildPhase2Args(inputPath, outputPath, level, hasAudio, vertical, outputProfile, variantPresetId, variantOptions) {
  if (hasAudio === undefined) hasAudio = true;
  if (vertical === undefined) vertical = true;
  if (!outputProfile) outputProfile = "organic";
  var reelProfile = getReelsProfile(outputProfile);
  var variantPreset = getVariantPreset(variantPresetId, variantOptions || {}, level);
  var allowHflip = horizontalFlipAllowed(variantOptions || {});
  var allowStrongTransforms = strongVisualTransformsAllowed(variantOptions || {});
  var allowColorTransforms = colorTransformsAllowed(variantOptions || {});
  var allowAudioTransforms = audioTransformsAllowed(variantOptions || {});
  var allowTimingTransforms = timingTransformsAllowed(variantOptions || {});
  var allowGeometryTransforms = geometryTransformsAllowed(variantOptions || {});
  var allowFrameRateTransforms = frameRateTransformsAllowed(variantOptions || {});

  // Pick a random device profile per variant
  var { profile: dev } = pickDeviceProfile();
  var bitrate = parseInt(reelProfile.videoBitrate, 10) || dev.bitrate();
  var maxrate = parseInt(reelProfile.maxrate, 10) || dev.maxrate();
  var gop = dev.gop();
  var bframes = dev.bframes();
  var refs = dev.refs();

  // ─── "clean" level: metadata + imperceptible transforms only ───
  // Research-backed: crop + time warp + pitch shift are all invisible but defeat fingerprinting
  if (level === "clean" || variantPreset.id === "quality") {
    var attemptIndex = parseInt(variantPreset.attemptIndex || 0, 10) || 0;
    var speedShiftClean = allowTimingTransforms ? rand(1 - variantPreset.speedShift, 1 + variantPreset.speedShift) : 1;
    var warpAmpClean = allowTimingTransforms ? rand(0, Math.max(0.001, variantPreset.speedShift * 0.8)) : 0;
    var warpPeriodClean = rand(2, 5);
    var startOffset = allowTimingTransforms ? Math.min(0.85, attemptIndex * 0.085 + rand(0, 0.04)) : 0;
    var args = [];
    if (startOffset > 0) args.push("-ss", startOffset.toFixed(3));
    args.push("-i", inputPath);

    var attemptBand = attemptIndex % 8;
    var preserveBurnedCaptions = !!(variantOptions && variantOptions.preserveBurnedCaptions);
    var cropFloor = attemptBand >= 4
      ? Math.max(0.94, variantPreset.crop - attemptBand * 0.008)
      : Math.max(0.962, variantPreset.crop - attemptBand * 0.004);
    var cropPctClean = !allowGeometryTransforms
      ? 1
      : preserveBurnedCaptions
      ? rand(0.997, 0.999)
      : rand(cropFloor, Math.min(0.996, cropFloor + 0.01));
    var anchorSlots = [
      [0.50, 0.50],
      [0.12, 0.18],
      [0.88, 0.22],
      [0.18, 0.82],
      [0.82, 0.78],
      [0.50, 0.12],
      [0.48, 0.88],
      [0.30, 0.50],
    ];
    var slot = anchorSlots[attemptBand] || anchorSlots[0];
    var cropAnchorX = preserveBurnedCaptions
      ? (1 - cropPctClean) / 2
      : Math.max(0, Math.min(1 - cropPctClean, (1 - cropPctClean) * slot[0] + rand(-0.002, 0.002)));
    var cropAnchorY = preserveBurnedCaptions
      ? 0
      : Math.max(0, Math.min(1 - cropPctClean, (1 - cropPctClean) * slot[1] + rand(-0.002, 0.002)));
    var ptsClean = (1 / speedShiftClean).toFixed(4);

    var cleanOverlay = overlayFilter(variantOptions || {});
    var geometryLockedScale = vertical
      ? "scale=" + reelProfile.width + ":" + reelProfile.height + ":force_original_aspect_ratio=decrease:flags=lanczos,pad=" + reelProfile.width + ":" + reelProfile.height + ":(ow-iw)/2:(oh-ih)/2:black"
      : "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black";
    var vfClean = [
      !allowGeometryTransforms ? geometryLockedScale : vertical ? (variantPreset.preserveFrame ? containBlurFilterForProfile(outputProfile) : scaleFilterForProfile(outputProfile)) : "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
      "format=yuv420p",
    ];
    if (allowGeometryTransforms && cropPctClean < 0.9999) {
      vfClean.unshift("crop=iw*" + cropPctClean.toFixed(4) + ":ih*" + cropPctClean.toFixed(4) + ":iw*" + cropAnchorX.toFixed(4) + ":ih*" + cropAnchorY.toFixed(4));
    }
    if (allowTimingTransforms) {
      vfClean.splice(vfClean.length - 1, 0, "setpts=PTS*" + ptsClean + "*(1+" + warpAmpClean.toFixed(4) + "*sin(PTS/" + warpPeriodClean.toFixed(2) + "))");
    }
    if (allowColorTransforms && variantPreset.colorShift > 0) {
      vfClean.splice(2, 0, "eq=gamma=" + (1 + ((attemptBand - 3.5) * variantPreset.colorShift * 0.35)).toFixed(4) + ":saturation=" + (1 + ((attemptBand % 3) - 1) * variantPreset.colorShift).toFixed(4));
    }
    if (allowHflip && (attemptBand === 2 || attemptBand === 5)) vfClean.splice(2, 0, "hflip");
    if (allowStrongTransforms && (attemptBand === 3 || attemptBand === 6)) vfClean.splice(2, 0, "rotate=" + (attemptBand === 3 ? "0.006" : "-0.006") + ":fillcolor=black:bilinear=1");
    if (cleanOverlay) vfClean.splice(vfClean.length - 1, 0, cleanOverlay);
    pushVideoFilters(args, vfClean, variantOptions || {}, hasAudio);

    if (hasAudio && allowAudioTransforms) {
      var pitchCentsClean = rand(-6, 6);
      var pitchFactorClean = Math.pow(2, pitchCentsClean / 1200);
      var origRateClean = dev.audioRate;
      var shiftedRateClean = Math.round(origRateClean * pitchFactorClean);
      args.push("-af", "asetrate=" + shiftedRateClean + ",aresample=" + origRateClean + ",atempo=" + speedShiftClean.toFixed(4));
    } else if (!hasAudio) {
      args.push("-an");
    }

    // Device-matched encoding
    var fakeDateClean = new Date(Date.now() - randInt(86400000, 86400000 * 60));
    if (allowFrameRateTransforms) args.push("-r", String(reelProfile.fps));
    args.push("-c:v", "libx264", "-preset", "slow", "-crf", String(variantPreset.videoCrf), "-profile:v", "high", "-level", reelProfile.fps >= 60 ? "5.1" : dev.level);
    args.push("-maxrate", reelProfile.maxrate, "-bufsize", reelProfile.bufsize);
    args.push("-g", String(gop));
    args.push("-pix_fmt", "yuv420p", "-movflags", "+faststart");
    if (dev.colorFlags) {
      args.push("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709");
      args.push("-color_range", "tv");
    }
    if (hasAudio) {
      args.push("-c:a", "aac", "-b:a", reelProfile.audioBitrate, "-ar", String(reelProfile.audioRate || dev.audioRate));
    }
    args.push("-map_metadata", "-1");
    args.push("-metadata", "creation_time=" + fakeDateClean.toISOString());
    args.push("-metadata:s:v", "handler_name=" + dev.handlerVideo);
    if (hasAudio) {
      args.push("-metadata:s:a", "handler_name=" + dev.handlerAudio);
    }
    args.push("-loglevel", "warning");
    args.push("-y", outputPath);
    return args;
  }

  // ─── All other levels: full visual + audio transforms ───
  var gamma = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
  var contrast = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
  var saturation = rand(1 - variantPreset.colorShift * 1.5, 1 + variantPreset.colorShift * 1.5);
  var hueShift = allowStrongTransforms ? rand(-variantPreset.colorShift * 80, variantPreset.colorShift * 80) : 0;
  var noiseStr = allowStrongTransforms && variantPreset.id === "strong" ? randInt(2, 5) : 0;

  // Per-spin structural randomization
  var driftAmpX = rand(0.01, 0.02);
  var driftAmpY = rand(0.01, 0.02);
  var driftFreqX = rand(20, 40);
  var driftFreqY = rand(25, 45);
  var warpAmp = rand(0.005, Math.max(0.006, variantPreset.speedShift));
  var warpPeriod = rand(2, 5);
  var speedShift = rand(1 - variantPreset.speedShift, 1 + variantPreset.speedShift);

  var filters = [];

  // Color adjustments
  if (allowColorTransforms && variantPreset.colorShift > 0) {
    filters.push("eq=gamma=" + gamma.toFixed(3) + ":contrast=" + contrast.toFixed(3) + ":saturation=" + saturation.toFixed(3));
  }
  if (allowColorTransforms && allowStrongTransforms) filters.push("hue=h=" + hueShift.toFixed(1));

  if (variantPreset.sharpen && allowStrongTransforms) {
    var sharpStr = rand(0.5, 1.0);
    filters.push("unsharp=3:3:" + sharpStr.toFixed(1) + ":3:3:0.0");
  }

  if (noiseStr > 0) filters.push("noise=c0s=" + noiseStr + ":c0f=t+u");

  if (allowHflip && Math.random() > 0.5) {
    filters.push("hflip");
  }

  var rotateDeg = 0;
  if (allowGeometryTransforms) {
    rotateDeg = allowStrongTransforms ? rand(0.2, 0.8) * (Math.random() > 0.5 ? 1 : -1) : rand(0.05, 0.18) * (Math.random() > 0.5 ? 1 : -1);
    var rotateRad = rotateDeg * 0.01745;
    filters.push("rotate=" + rotateRad.toFixed(5) + ":fillcolor=black:bilinear=1");

    var rotCropPct = Math.max(0.93, 1 - (Math.abs(rotateDeg) * 0.04));
    filters.push("crop=iw*" + rotCropPct.toFixed(4) + ":ih*" + rotCropPct.toFixed(4) +
      ":iw*(1-" + rotCropPct.toFixed(4) + ")/2:ih*(1-" + rotCropPct.toFixed(4) + ")/2");
  }

  if (allowGeometryTransforms && (level === "stealth" || level === "heavy")) {
    var driftCropPct = rand(0.93, 0.97);
    var cx = "(iw*(1-" + driftCropPct.toFixed(3) + ")/2)+(iw*" + driftAmpX.toFixed(4) + "*sin(n/" + driftFreqX.toFixed(0) + "))";
    var cy = "(ih*(1-" + driftCropPct.toFixed(3) + ")/2)+(ih*" + driftAmpY.toFixed(4) + "*cos(n/" + driftFreqY.toFixed(0) + "))";
    filters.push("crop=iw*" + driftCropPct.toFixed(3) + ":ih*" + driftCropPct.toFixed(3) + ":" + cx + ":" + cy);
  }

  if (vertical) {
    filters.push(variantPreset.preserveFrame ? containBlurFilterForProfile(outputProfile) : scaleFilterForProfile(outputProfile));
  } else {
    filters.push("scale=1920:1080:flags=lanczos");
  }

  if (allowTimingTransforms && (level === "stealth" || level === "heavy")) {
    var ptsMultiplier = (1 / speedShift).toFixed(4);
    filters.push("setpts=PTS*" + ptsMultiplier + "*(1+" + warpAmp.toFixed(4) + "*sin(PTS/" + warpPeriod.toFixed(2) + "))");
  } else if (allowTimingTransforms) {
    filters.push("setpts=" + (1 / speedShift).toFixed(4) + "*PTS");
  }

  if (level === "stealth") {
    var lumaAmp = randInt(2, 4);
    var lumaWaveX = randInt(60, 120);
    var lumaSpeed = rand(0.06, 0.15);
    filters.push("geq=lum='lum(X\\,Y)+" + lumaAmp + "*sin(X/" + lumaWaveX + "+N*" + lumaSpeed.toFixed(3) + ")':cb='cb(X\\,Y)':cr='cr(X\\,Y)'");
  }

  if (allowColorTransforms && variantPreset.colorShift > 0) {
    var cbRS = rand(-0.03, 0.03);
    var cbGS = rand(-0.03, 0.03);
    var cbBS = rand(-0.03, 0.03);
    filters.push("colorbalance=rs=" + cbRS.toFixed(3) + ":gs=" + cbGS.toFixed(3) + ":bs=" + cbBS.toFixed(3));
  }

  var phase2Overlay = overlayFilter(variantOptions || {});
  if (phase2Overlay) filters.push(phase2Overlay);
  filters.push("format=yuv420p");

  var args = ["-i", inputPath];
  pushVideoFilters(args, filters, variantOptions || {}, hasAudio);

  if (hasAudio && allowAudioTransforms) {
    var audioFilters = [];
    var pitchCents = rand(-50, 50);
    var pitchFactor = Math.pow(2, pitchCents / 1200);
    var origRate = dev.audioRate;
    var shiftedRate = Math.round(origRate * pitchFactor);
    audioFilters.push("asetrate=" + shiftedRate);
    audioFilters.push("aresample=" + origRate);
    var tempo = speedShift * rand(0.99, 1.01);
    if (tempo < 0.5) tempo = 0.5;
    if (tempo > 2.0) tempo = 2.0;
    audioFilters.push("atempo=" + tempo.toFixed(4));
    if (variantPreset.id === "strong") audioFilters.push("aecho=0.6:0.6:" + randInt(12, 30) + ":0.04");
    args.push("-af", audioFilters.join(","));
  } else if (!hasAudio) {
    args.push("-an");
  }

  var fakeDate = new Date(Date.now() - randInt(86400000, 86400000 * 60));
  if (allowFrameRateTransforms) args.push("-r", String(reelProfile.fps));
  args.push("-c:v", "libx264", "-preset", variantPreset.id === "strong" ? "medium" : "slow", "-crf", String(variantPreset.videoCrf), "-profile:v", dev.profile, "-level", reelProfile.fps >= 60 ? "5.1" : dev.level);
  args.push("-maxrate", reelProfile.maxrate, "-bufsize", reelProfile.bufsize);
  args.push("-g", String(gop));
  args.push("-x264-params", dev.x264Params(bitrate, gop, bframes, refs));
  args.push("-pix_fmt", "yuv420p", "-movflags", "+faststart");
  if (dev.colorFlags) {
    args.push("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709");
    args.push("-color_range", "tv");
  }
  if (hasAudio) {
    args.push("-c:a", "aac", "-b:a", reelProfile.audioBitrate, "-ar", String(reelProfile.audioRate || dev.audioRate));
  }
  args.push("-map_metadata", "-1");
  args.push("-metadata", "creation_time=" + fakeDate.toISOString());
  args.push("-metadata:s:v", "handler_name=" + dev.handlerVideo);
  if (hasAudio) {
    args.push("-metadata:s:a", "handler_name=" + dev.handlerAudio);
  }
  args.push("-loglevel", "warning");
  args.push("-y", outputPath);

  return args;
}

// ─── Image Hash Breaking ───
// Research-backed (2026):
// PDQ: 64x64 DCT grid → 256-bit hash, 31-bit Hamming threshold
// SSCD: 512-d neural embeddings, cosine >= 0.75 = match
// Texture bias: sharpen + grain shift embeddings disproportionately to perceptual quality
// 3-5% crop shifts content on grid → Hamming 30-83 bits (over threshold)
// Combined: PSNR >40 dB (visually lossless) but unique hash per variant

var DEVICE_MODELS_IMG = [
  "iPhone 16 Pro Max", "iPhone 16 Pro", "iPhone 15 Pro Max", "iPhone 15 Pro",
  "iPhone 14 Pro", "iPhone 13",
  "Samsung SM-S928B", "Samsung SM-S911B", "Samsung SM-G991B",
  "Pixel 9 Pro", "Pixel 8 Pro", "Pixel 7a",
];

export function buildImageArgs(inputPath, outputPath, index, opts) {
  var level = opts.level || "clean";
  var variantPreset = getVariantPreset(opts.variantPreset, opts.variantOptions || {}, level);
  var attemptIndex = parseInt(variantPreset.attemptIndex || 0, 10) || 0;
  var allowColorTransforms = colorTransformsAllowed(opts.variantOptions || {});

  // ─── Clean level: crop + JPEG quality variation only ───
  // Research: IG always re-encodes — upload highest quality to minimize double-compression artifacts
  if (level === "clean" || variantPreset.id === "quality") {
    var cleanCrop = rand(Math.max(0.975, variantPreset.crop - (attemptIndex % 6) * 0.004), 0.997);
    var cleanOffX = rand(0, 1 - cleanCrop);
    var cleanOffY = rand(0, 1 - cleanCrop);
    var cleanImageOverlay = overlayFilter(opts.variantOptions || {});
    var cleanFilters = [
      "crop=iw*" + cleanCrop.toFixed(4) + ":ih*" + cleanCrop.toFixed(4) +
        ":iw*" + cleanOffX.toFixed(4) + ":ih*" + cleanOffY.toFixed(4),
      "format=yuvj420p",  // Force sRGB-compatible colorspace (IG desaturates wide-gamut)
    ];
    if (allowColorTransforms && variantPreset.colorShift > 0) {
      cleanFilters.splice(1, 0, "eq=gamma=" + (1 + ((attemptIndex % 5) - 2) * variantPreset.colorShift * 0.4).toFixed(4) + ":saturation=" + (1 + ((attemptIndex % 3) - 1) * variantPreset.colorShift).toFixed(4));
    }
    if (attemptIndex % 5 === 3) cleanFilters.splice(1, 0, "hflip");
    if (cleanImageOverlay) cleanFilters.splice(cleanFilters.length - 1, 0, cleanImageOverlay);
    var cleanArgs = ["-i", inputPath];
    pushImageFilters(cleanArgs, cleanFilters, opts.variantOptions || {});
    cleanArgs.push("-q:v", String(randInt(variantPreset.imageQuality[0], variantPreset.imageQuality[1])));
    cleanArgs.push("-map_metadata", "-1");
    var cleanDate = new Date(Date.now() - randInt(86400000, 86400000 * 60));
    cleanArgs.push("-metadata", "creation_time=" + cleanDate.toISOString());
    cleanArgs.push("-loglevel", "warning");
    cleanArgs.push("-y", outputPath);
    return cleanArgs;
  }

  var filters = [];

  // ─── Crop: PDQ's #1 weakness ───
  var cropPct;
  if (level === "light") {
    cropPct = rand(Math.min(0.99, variantPreset.crop), 0.995);
  } else if (level === "medium") {
    cropPct = rand(Math.min(0.98, variantPreset.crop), 0.99);
  } else {
    cropPct = rand(Math.min(0.97, variantPreset.crop), 0.985);
  }

  var maxOffset = 1 - cropPct;
  var anchorX = rand(0, maxOffset);
  var anchorY = rand(0, maxOffset);
  filters.push("crop=iw*" + cropPct.toFixed(4) + ":ih*" + cropPct.toFixed(4) +
    ":iw*" + anchorX.toFixed(4) + ":ih*" + anchorY.toFixed(4));

  // ─── Color modulation: flips DCT threshold bits ───
  if (allowColorTransforms && level !== "light") {
    var gamma = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
    var saturation = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
    var hueShift = rand(-variantPreset.colorShift * 60, variantPreset.colorShift * 60);
    filters.push("eq=gamma=" + gamma.toFixed(4) + ":saturation=" + saturation.toFixed(4));
    filters.push("hue=h=" + Math.round(hueShift));
  }

  // ─── Sub-degree rotation: defeats neural embeddings ───
  if (level === "medium" || level === "heavy" || level === "stealth") {
    var rotateDeg = rand(0.1, 0.5) * (Math.random() > 0.5 ? 1 : -1);
    var rotateRad = rotateDeg * 0.01745;
    filters.push("rotate=" + rotateRad.toFixed(6) + ":fillcolor=white:bilinear=1");
    var trimPct = Math.max(0.96, 1 - Math.abs(rotateDeg) * 0.03);
    filters.push("crop=iw*" + trimPct.toFixed(4) + ":ih*" + trimPct.toFixed(4) +
      ":iw*(1-" + trimPct.toFixed(4) + ")/2:ih*(1-" + trimPct.toFixed(4) + ")/2");
  }

  // ─── Texture bias exploit: sharpen (shifts embeddings >> perceptual impact) ───
  // Research: unsharp=3:3:0.8 at SSIM > 0.92 shifts embedding cosine by 0.05-0.15
  if (variantPreset.sharpen) {
    var sharpStr = rand(0.4, 0.8);
    filters.push("unsharp=3:3:" + sharpStr.toFixed(1) + ":3:3:0.0");
  }

  // ─── Film grain: temporal+uniform noise exploits CNN texture sensitivity ───
  if (variantPreset.id === "strong") {
    filters.push("noise=c0s=" + randInt(2, 4) + ":c0f=t+u");
  }

  // ─── Subtle color balance shift ───
  if (allowColorTransforms && level === "stealth") {
    var cbRS = rand(-0.02, 0.02);
    var cbGS = rand(-0.02, 0.02);
    var cbBS = rand(-0.02, 0.02);
    filters.push("colorbalance=rs=" + cbRS.toFixed(3) + ":gs=" + cbGS.toFixed(3) + ":bs=" + cbBS.toFixed(3));
  }

  // ─── Random mirror (50% chance) ───
  if (Math.random() > 0.5) {
    filters.push("hflip");
  }

  // ─── Force sRGB-compatible colorspace ───
  // Research: IG desaturates wide-gamut (P3/Adobe RGB) uploads. Always output in sRGB.
  var imageOverlay = overlayFilter(opts.variantOptions || {});
  if (imageOverlay) filters.push(imageOverlay);
  filters.push("format=yuvj420p");

  // Build args
  var args = ["-i", inputPath];
  pushImageFilters(args, filters, opts.variantOptions || {});

  // JPEG quality: Q80-92 (FFmpeg q:v 2-3)
  // Research: IG always re-encodes at ~Q70-76. Uploading highest quality = less double-compression.
  // Pre-compressing to IG's target quality causes WORSE artifacts (confirmed by Josh Wright's CIEDE2000 analysis).
  var quality = randInt(variantPreset.imageQuality[0], variantPreset.imageQuality[1]);
  args.push("-q:v", String(quality));

  // Strip ALL metadata
  args.push("-map_metadata", "-1");

  // Spoofed metadata matching real device
  var fakeDate = new Date(Date.now() - randInt(86400000, 86400000 * 60));
  var fakeDevice = pick(DEVICE_MODELS_IMG);
  args.push("-metadata", "creation_time=" + fakeDate.toISOString());

  // NOTE: Do NOT add encoder= metadata. Real device photos don't have Lavf/Lavc strings.

  args.push("-loglevel", "warning");
  args.push("-y", outputPath);

  return args;
}

export { generateDeviceFilename };
