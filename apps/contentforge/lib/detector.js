import { createHash } from "crypto";
import { execFile } from "child_process";
import { readFile, stat, unlink } from "fs/promises";
import { createReadStream, existsSync } from "fs";
import path from "path";
import { listRunFiles } from "./reels.js";
import { resolveRunFile, resolveRunFinalDir, resolveUploadPath, safeBasename } from "./paths.js";
import { getLocalDiagnostics } from "./diagnostics.js";
import { formatBytes } from "./reels.js";
import { variantScoreBundle } from "./variant-engine.js";

function runTool(command, args, options = {}) {
  return new Promise(function (resolve) {
    execFile(command, args, {
      timeout: options.timeout || 20000,
      maxBuffer: options.maxBuffer || 2 * 1024 * 1024,
      encoding: options.encoding,
    }, function (error, stdout, stderr) {
      resolve({ error, stdout: stdout || Buffer.alloc(0), stderr: stderr || "" });
    });
  });
}

export function hammingDistance(a, b) {
  if (!a || !b || a.length !== b.length) return a && b ? Math.max(a.length, b.length) : 256;
  var dist = 0;
  for (var i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) dist++;
  }
  return dist;
}

export function bucketSimilarity(similarity, exactMatch, threshold = 0.92) {
  if (exactMatch || similarity >= threshold) return "duplicate";
  if (similarity >= Math.max(0, threshold - 0.12)) return "similar";
  return "unique";
}

async function exactHash(filePath) {
  return new Promise(function (resolve, reject) {
    var hash = createHash("sha256");
    var stream = createReadStream(filePath);
    stream.on("data", function (chunk) { hash.update(chunk); });
    stream.on("error", reject);
    stream.on("end", function () { resolve(hash.digest("hex")); });
  });
}

var SAMPLE_POINTS = [0.05, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90];

async function probeDuration(filePath) {
  var result = await runTool("ffprobe", [
    "-v", "quiet",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    filePath,
  ], { timeout: 10000, maxBuffer: 1024 * 1024, encoding: "utf8" });
  if (result.error) return 0;
  return parseFloat(result.stdout) || 0;
}

async function frameHashAt(filePath, seconds, isVideo) {
  var args = [
    "-hide_banner",
  ];
  if (isVideo) args.push("-ss", String(Math.max(0, seconds || 0)));
  args.push(
    "-i", filePath,
    "-vframes", "1",
    "-vf", "scale=32:32,format=gray",
    "-f", "rawvideo",
    "-",
  );
  var result = await runTool("ffmpeg", args, { timeout: 15000, maxBuffer: 1024 * 1024, encoding: "buffer" });

  if (result.error || !result.stdout || result.stdout.length === 0) return null;
  var buffer = Buffer.isBuffer(result.stdout) ? result.stdout : Buffer.from(result.stdout, "binary");
  var total = 0;
  for (var byte of buffer) total += byte;
  var avg = total / buffer.length;
  var bits = "";
  for (var pixel of buffer) bits += pixel >= avg ? "1" : "0";
  return bits;
}

export async function frameHash(filePath, isVideo) {
  return frameHashAt(filePath, isVideo ? 1 : 0, isVideo);
}

export function averageHashSimilarity(a = [], b = []) {
  var count = Math.min(a.length, b.length);
  if (!count) return 0;
  var total = 0;
  for (var i = 0; i < count; i++) {
    total += 1 - (hammingDistance(a[i], b[i]) / Math.max(a[i].length, 1));
  }
  return total / count;
}

export function temporalHashSimilarity(a = [], b = []) {
  var count = Math.min(a.length, b.length);
  if (!count) return 0;
  var best = 0;
  var maxOffset = Math.max(1, Math.ceil(count * 0.08));
  for (var offset = -maxOffset; offset <= maxOffset; offset++) {
    var total = 0;
    var matched = 0;
    for (var i = 0; i < count; i++) {
      var j = i + offset;
      if (j < 0 || j >= b.length) continue;
      total += 1 - (hammingDistance(a[i], b[j]) / Math.max(a[i].length, 1));
      matched++;
    }
    if (matched) best = Math.max(best, total / matched);
  }
  return best;
}

export async function multiFrameHash(filePath, isVideo) {
  if (!isVideo) {
    var still = await frameHashAt(filePath, 0, false);
    return still ? [still] : [];
  }
  var duration = await probeDuration(filePath);
  var hashes = [];
  for (var point of SAMPLE_POINTS) {
    var hash = await frameHashAt(filePath, duration ? duration * point : 1, true);
    if (hash) hashes.push(hash);
  }
  return hashes;
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

async function resolveDetectorSource({ runId, sourceFile, files }) {
  var explicit = sourceFile ? resolveUploadPath(sourceFile) : null;
  if (explicit && existsSync(explicit)) return { path: explicit, name: path.basename(explicit), type: "source" };
  var config = await readRunConfig(runId);
  var configured = config && config.inputFile ? resolveUploadPath(config.inputFile) : null;
  if (configured && existsSync(configured)) return { path: configured, name: path.basename(configured), type: "source" };
  var first = files[0];
  return first ? { path: first.path, name: first.name, type: first.type, fallback: true } : null;
}

export async function analyzeRunSimilarity({ runId, threshold = 0.92, sourceFile = null } = {}) {
  var parsedThreshold = Math.max(0.5, Math.min(1, parseFloat(threshold) || 0.92));
  var files = (await listRunFiles(runId)).filter(function (file) { return file.type === "video" || file.type === "image"; });
  if (files.length === 0) {
    var err = new Error("No files found in run");
    err.status = 404;
    throw err;
  }

  var sourceFileInfo = await resolveDetectorSource({ runId, sourceFile, files });
  if (!sourceFileInfo) {
    var sourceErr = new Error("No source file found");
    sourceErr.status = 404;
    throw sourceErr;
  }
  var sourceSig = {
    name: sourceFileInfo.name,
    type: sourceFileInfo.type,
    size: existsSync(sourceFileInfo.path) ? await stat(sourceFileInfo.path).then(function (s) { return s.size; }).catch(function () { return 0; }) : 0,
    exactHash: await exactHash(sourceFileInfo.path),
    frameHashes: await multiFrameHash(sourceFileInfo.path, sourceFileInfo.type === "video" || /\.(mp4|mov|webm)$/i.test(sourceFileInfo.name)),
  };

  var signatures = [];
  for (var file of files) {
    var hash = await exactHash(file.path);
    var perceptual = await multiFrameHash(file.path, file.type === "video");
    signatures.push({
      name: file.name,
      type: file.type,
      size: file.size,
      exactHash: hash,
      frameHashes: perceptual,
    });
  }

  var pairs = [];
  var rows = signatures.map(function (sig) {
    var exactMatch = sig.exactHash === sourceSig.exactHash;
    var multiFrameSimilarity = sig.frameHashes && sourceSig.frameHashes
      ? averageHashSimilarity(sig.frameHashes, sourceSig.frameHashes)
      : 0;
    var temporalSimilarity = sig.frameHashes && sourceSig.frameHashes
      ? temporalHashSimilarity(sig.frameHashes, sourceSig.frameHashes)
      : 0;
    var sourceSimilarity = exactMatch ? 1 : Math.max(multiFrameSimilarity, temporalSimilarity);
    var difference = (1 - sourceSimilarity) * 100;
    var bundle = variantScoreBundle({
      mediaInfo: { size: sig.size },
      sourceSimilarity,
      exactMatch,
      differenceFromOriginal: difference,
      qualitySignals: ["file size " + formatBytes(sig.size)],
      differenceSignals: [
        exactMatch ? "exact hash match" : "exact hash changed",
        sig.frameHashes && sourceSig.frameHashes ? "multi-frame hash" : null,
        sig.frameHashes && sourceSig.frameHashes ? "temporal hash" : null,
      ].filter(Boolean),
    });
    return {
      name: sig.name,
      type: sig.type,
      size: sig.size,
      exactHash: sig.exactHash,
      exactMatch,
      sourceSimilarity: Number(sourceSimilarity.toFixed(4)),
      variantSimilarity: Number(sourceSimilarity.toFixed(4)),
      crossVariantSimilarity: 0,
      maxCrossVariantSimilarity: 0,
      multiFrameSimilarity: Number(multiFrameSimilarity.toFixed(4)),
      temporalSimilarity: Number(temporalSimilarity.toFixed(4)),
      ...bundle,
      bucket: bucketSimilarity(sourceSimilarity, exactMatch, parsedThreshold),
    };
  });

  for (var i = 0; i < signatures.length; i++) {
    for (var j = i + 1; j < signatures.length; j++) {
      var a = signatures[i];
      var b = signatures[j];
      var exact = a.exactHash === b.exactHash;
      var multi = a.frameHashes && b.frameHashes ? averageHashSimilarity(a.frameHashes, b.frameHashes) : 0;
      var temporal = a.frameHashes && b.frameHashes ? temporalHashSimilarity(a.frameHashes, b.frameHashes) : 0;
      var sim = exact ? 1 : Math.max(multi, temporal);
      pairs.push({
        a: a.name,
        b: b.name,
        similarity: Number(sim.toFixed(4)),
        multiFrameSimilarity: Number(multi.toFixed(4)),
        temporalSimilarity: Number(temporal.toFixed(4)),
        bucket: bucketSimilarity(sim, exact, parsedThreshold),
      });
    }
  }

  for (var row of rows) {
    var related = pairs.filter(function (pair) { return pair.a === row.name || pair.b === row.name; });
    var maxCross = related.reduce(function (max, pair) { return Math.max(max, pair.similarity); }, 0);
    row.crossVariantSimilarity = Number(maxCross.toFixed(4));
    row.maxCrossVariantSimilarity = row.crossVariantSimilarity;
    if (row.bucket !== "duplicate" && maxCross >= parsedThreshold) row.bucket = "duplicate";
  }

  var diagnostics = await getLocalDiagnostics();
  return {
    runId,
    threshold: parsedThreshold,
    source: sourceSig.name,
    sourceFile: sourceSig.name,
    sourceFallback: !!sourceFileInfo.fallback,
    files: rows,
    pairs,
    layers: {
      exactHash: { available: true, label: "Exact hash" },
      perceptualFrame: { available: true, label: "Sampled frame hash" },
      audio: {
        available: diagnostics.fpcalc.available,
        label: "Audio fingerprint",
        reason: diagnostics.fpcalc.available ? null : "fpcalc not installed",
      },
      sscd: {
        available: diagnostics.sscd.modelPresent,
        label: "SSCD embedding",
        reason: diagnostics.sscd.modelPresent ? null : "SSCD model not installed",
      },
      temporal: {
        available: diagnostics.ffmpeg.available,
        label: "Temporal video checks",
        reason: diagnostics.ffmpeg.available ? null : "FFmpeg not available",
      },
    },
    summary: {
      total: rows.length,
      duplicate: rows.filter(function (row) { return row.bucket === "duplicate"; }).length,
      similar: rows.filter(function (row) { return row.bucket === "similar"; }).length,
      unique: rows.filter(function (row) { return row.bucket === "unique"; }).length,
    },
  };
}

export async function deleteRunFiles({ runId, files }) {
  if (!Array.isArray(files) || files.length === 0) {
    var missing = new Error("No files selected");
    missing.status = 400;
    throw missing;
  }
  var deleted = [];
  for (var file of files) {
    var safeName = safeBasename(file);
    var filePath = resolveRunFile(runId, safeName);
    if (!safeName || !filePath || !existsSync(filePath)) continue;
    await unlink(filePath);
    deleted.push(path.basename(filePath));
  }
  return { runId, deleted };
}
