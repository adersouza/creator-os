import { COLOR_PRESETS, CROP_STYLES, BORDER_STYLES } from "./presets.js";
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

function generateVariantFilename() {
  return "contentforge_variant_" + Date.now() + "_" + randInt(100000, 999999);
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

// ─── Phase 2: quality-preserving editorial variation ───

export function buildPhase2Args(inputPath, outputPath, level, hasAudio, vertical, outputProfile, variantPresetId, variantOptions) {
  if (hasAudio === undefined) hasAudio = true;
  if (vertical === undefined) vertical = true;
  if (!outputProfile) outputProfile = "organic";
  var reelProfile = getReelsProfile(outputProfile);
  var variantPreset = getVariantPreset(variantPresetId, variantOptions || {}, level);
  var allowHflip = horizontalFlipAllowed(variantOptions || {});
  var allowColorTransforms = colorTransformsAllowed(variantOptions || {});
  var allowAudioTransforms = audioTransformsAllowed(variantOptions || {});
  var allowTimingTransforms = timingTransformsAllowed(variantOptions || {});
  var allowGeometryTransforms = geometryTransformsAllowed(variantOptions || {});
  var allowFrameRateTransforms = frameRateTransformsAllowed(variantOptions || {});

  var dev = {
    audioRate: reelProfile.audioRate || 48000,
    level: reelProfile.fps >= 60 ? "5.1" : "4.2",
    profile: "high",
    colorFlags: true,
  };
  var gop = Math.max(1, Math.round((reelProfile.fps || 30) * 2));

  // ─── "clean" level: conservative editorial transforms only ───
  if (level === "clean" || variantPreset.id === "quality") {
    var attemptIndex = parseInt(variantPreset.attemptIndex || 0, 10) || 0;
    var speedShiftClean = allowTimingTransforms && (!hasAudio || allowAudioTransforms)
      ? rand(1 - variantPreset.speedShift, 1 + variantPreset.speedShift)
      : 1;
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
      vfClean.splice(vfClean.length - 1, 0, "setpts=PTS*" + ptsClean);
    }
    if (allowColorTransforms && variantPreset.colorShift > 0) {
      vfClean.splice(2, 0, "eq=gamma=" + (1 + ((attemptBand - 3.5) * variantPreset.colorShift * 0.35)).toFixed(4) + ":saturation=" + (1 + ((attemptBand % 3) - 1) * variantPreset.colorShift).toFixed(4));
    }
    if (allowHflip && (attemptBand === 2 || attemptBand === 5)) vfClean.splice(2, 0, "hflip");
    if (cleanOverlay) vfClean.splice(vfClean.length - 1, 0, cleanOverlay);
    pushVideoFilters(args, vfClean, variantOptions || {}, hasAudio);

    if (hasAudio && allowAudioTransforms && speedShiftClean !== 1) {
      args.push("-af", "atempo=" + speedShiftClean.toFixed(4));
    } else if (!hasAudio) {
      args.push("-an");
    }

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
    args.push("-loglevel", "warning");
    args.push("-y", outputPath);
    return args;
  }

  // ─── Light and medium editorial transforms ───
  var gamma = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
  var contrast = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
  var saturation = rand(1 - variantPreset.colorShift * 1.5, 1 + variantPreset.colorShift * 1.5);
  var speedShift = allowTimingTransforms && (!hasAudio || allowAudioTransforms)
    ? rand(1 - variantPreset.speedShift, 1 + variantPreset.speedShift)
    : 1;

  var filters = [];

  // Color adjustments
  if (allowColorTransforms && variantPreset.colorShift > 0) {
    filters.push("eq=gamma=" + gamma.toFixed(3) + ":contrast=" + contrast.toFixed(3) + ":saturation=" + saturation.toFixed(3));
  }
  if (variantPreset.sharpen) {
    var sharpStr = rand(0.3, 0.5);
    filters.push("unsharp=3:3:" + sharpStr.toFixed(1) + ":3:3:0.0");
  }

  if (allowHflip && Math.random() > 0.5) {
    filters.push("hflip");
  }

  var rotateDeg = 0;
  if (allowGeometryTransforms) {
    rotateDeg = rand(0.05, 0.18) * (Math.random() > 0.5 ? 1 : -1);
    var rotateRad = rotateDeg * 0.01745;
    filters.push("rotate=" + rotateRad.toFixed(5) + ":fillcolor=black:bilinear=1");

    var rotCropPct = Math.max(0.93, 1 - (Math.abs(rotateDeg) * 0.04));
    filters.push("crop=iw*" + rotCropPct.toFixed(4) + ":ih*" + rotCropPct.toFixed(4) +
      ":iw*(1-" + rotCropPct.toFixed(4) + ")/2:ih*(1-" + rotCropPct.toFixed(4) + ")/2");
  }

  if (vertical) {
    filters.push(variantPreset.preserveFrame ? containBlurFilterForProfile(outputProfile) : scaleFilterForProfile(outputProfile));
  } else {
    filters.push("scale=1920:1080:flags=lanczos");
  }

  if (allowTimingTransforms) {
    filters.push("setpts=" + (1 / speedShift).toFixed(4) + "*PTS");
  }

  var phase2Overlay = overlayFilter(variantOptions || {});
  if (phase2Overlay) filters.push(phase2Overlay);
  filters.push("format=yuv420p");

  var args = ["-i", inputPath];
  pushVideoFilters(args, filters, variantOptions || {}, hasAudio);

  if (hasAudio && allowAudioTransforms && speedShift !== 1) {
    args.push("-af", "atempo=" + speedShift.toFixed(4));
  } else if (!hasAudio) {
    args.push("-an");
  }

  if (allowFrameRateTransforms) args.push("-r", String(reelProfile.fps));
  args.push("-c:v", "libx264", "-preset", "slow", "-crf", String(variantPreset.videoCrf), "-profile:v", dev.profile, "-level", reelProfile.fps >= 60 ? "5.1" : dev.level);
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
  args.push("-loglevel", "warning");
  args.push("-y", outputPath);

  return args;
}

// ─── Image editorial variation ───

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
    cleanArgs.push("-loglevel", "warning");
    cleanArgs.push("-y", outputPath);
    return cleanArgs;
  }

  var filters = [];

  // ─── Editorial crop ───
  var cropPct;
  if (level === "light") {
    cropPct = rand(Math.min(0.99, variantPreset.crop), 0.995);
  } else if (level === "medium") {
    cropPct = rand(Math.min(0.98, variantPreset.crop), 0.99);
  } else {
    cropPct = rand(Math.min(0.98, variantPreset.crop), 0.99);
  }

  var maxOffset = 1 - cropPct;
  var anchorX = rand(0, maxOffset);
  var anchorY = rand(0, maxOffset);
  filters.push("crop=iw*" + cropPct.toFixed(4) + ":ih*" + cropPct.toFixed(4) +
    ":iw*" + anchorX.toFixed(4) + ":ih*" + anchorY.toFixed(4));

  // ─── Mild color correction ───
  if (allowColorTransforms && level !== "light") {
    var gamma = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
    var saturation = rand(1 - variantPreset.colorShift, 1 + variantPreset.colorShift);
    var hueShift = rand(-variantPreset.colorShift * 60, variantPreset.colorShift * 60);
    filters.push("eq=gamma=" + gamma.toFixed(4) + ":saturation=" + saturation.toFixed(4));
    filters.push("hue=h=" + Math.round(hueShift));
  }

  // ─── Mild editorial rotation ───
  if (level === "medium") {
    var rotateDeg = rand(0.1, 0.5) * (Math.random() > 0.5 ? 1 : -1);
    var rotateRad = rotateDeg * 0.01745;
    filters.push("rotate=" + rotateRad.toFixed(6) + ":fillcolor=white:bilinear=1");
    var trimPct = Math.max(0.96, 1 - Math.abs(rotateDeg) * 0.03);
    filters.push("crop=iw*" + trimPct.toFixed(4) + ":ih*" + trimPct.toFixed(4) +
      ":iw*(1-" + trimPct.toFixed(4) + ")/2:ih*(1-" + trimPct.toFixed(4) + ")/2");
  }

  // ─── Optional sharpening for perceived clarity ───
  if (variantPreset.sharpen) {
    var sharpStr = rand(0.4, 0.8);
    filters.push("unsharp=3:3:" + sharpStr.toFixed(1) + ":3:3:0.0");
  }

  // ─── Random mirror (50% chance) ───
  if (horizontalFlipAllowed(opts.variantOptions || {}) && Math.random() > 0.5) {
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

  args.push("-loglevel", "warning");
  args.push("-y", outputPath);

  return args;
}

export { generateVariantFilename };
