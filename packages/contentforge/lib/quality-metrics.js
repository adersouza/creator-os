import { execFile } from "child_process";
import { mkdtemp, readFile, rm } from "fs/promises";
import os from "os";
import path from "path";
import { getLocalDiagnostics } from "./diagnostics.js";

function runTool(args, options = {}) {
  return new Promise(function (resolve) {
    execFile("ffmpeg", args, {
      timeout: options.timeout || 45000,
      maxBuffer: options.maxBuffer || 4 * 1024 * 1024,
    }, function (error, stdout, stderr) {
      resolve({ error, stdout: stdout || "", stderr: stderr || "" });
    });
  });
}

function metricFilter(width, height, filterName) {
  return "[0:v]scale=" + width + ":" + height + ":flags=bicubic,format=yuv420p,setpts=PTS-STARTPTS[ref];" +
    "[1:v]scale=" + width + ":" + height + ":flags=bicubic,format=yuv420p,setpts=PTS-STARTPTS[dist];" +
    "[ref][dist]" + filterName;
}

export function parseSsim(stderr) {
  var match = String(stderr || "").match(/All:([0-9.]+)/);
  return match ? parseFloat(match[1]) : null;
}

export function parsePsnr(stderr) {
  var match = String(stderr || "").match(/average:([0-9.]+)/);
  return match ? parseFloat(match[1]) : null;
}

export function parseVmafJson(jsonText) {
  try {
    var data = JSON.parse(jsonText);
    return data.pooled_metrics && data.pooled_metrics.vmaf ? data.pooled_metrics.vmaf.mean : null;
  } catch {
    return null;
  }
}

async function runSsim(sourcePath, variantPath, mediaInfo) {
  var result = await runTool([
    "-i", sourcePath,
    "-i", variantPath,
    "-lavfi", metricFilter(mediaInfo.width || 1080, mediaInfo.height || 1920, "ssim"),
    "-f", "null",
    "-",
  ]);
  return result.error ? null : parseSsim(result.stderr);
}

export async function getFastQualityMetrics({ sourcePath, variantPath, mediaInfo }) {
  if (!sourcePath) return { available: false, reason: "Source file unavailable for SSIM" };
  var diagnostics = await getLocalDiagnostics();
  var filters = diagnostics.ffmpeg.filters || {};
  var ssim = filters.ssim ? await runSsim(sourcePath, variantPath, mediaInfo) : null;
  return {
    available: ssim !== null,
    ssim,
    reason: ssim === null ? "SSIM unavailable" : null,
  };
}

async function runPsnr(sourcePath, variantPath, mediaInfo) {
  var result = await runTool([
    "-i", sourcePath,
    "-i", variantPath,
    "-lavfi", metricFilter(mediaInfo.width || 1080, mediaInfo.height || 1920, "psnr"),
    "-f", "null",
    "-",
  ]);
  return result.error ? null : parsePsnr(result.stderr);
}

async function runVmaf(sourcePath, variantPath, mediaInfo) {
  var tempDir = await mkdtemp(path.join(os.tmpdir(), "contentforge-vmaf-"));
  var logPath = path.join(tempDir, "vmaf.json");
  try {
    var result = await runTool([
      "-i", sourcePath,
      "-i", variantPath,
      "-lavfi", metricFilter(mediaInfo.width || 1080, mediaInfo.height || 1920, "libvmaf=log_fmt=json:log_path=" + logPath),
      "-f", "null",
      "-",
    ], { timeout: 90000 });
    if (result.error) return null;
    return parseVmafJson(await readFile(logPath, "utf8"));
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
}

async function runVmafMotion(variantPath) {
  var result = await runTool([
    "-i", variantPath,
    "-vf", "vmafmotion",
    "-f", "null",
    "-",
  ]);
  var match = result.stderr.match(/VMAF Motion avg:\s*([0-9.]+)/i);
  return match ? parseFloat(match[1]) : null;
}

export async function getQualityMetrics({ sourcePath, variantPath, mediaInfo }) {
  if (!sourcePath) {
    return { available: false, reason: "Source file unavailable for reference metrics" };
  }
  var diagnostics = await getLocalDiagnostics();
  var filters = diagnostics.ffmpeg.filters || {};
  var metrics = {
    available: true,
    vmaf: filters.libvmaf ? await runVmaf(sourcePath, variantPath, mediaInfo) : null,
    ssim: filters.ssim ? await runSsim(sourcePath, variantPath, mediaInfo) : null,
    psnr: filters.psnr ? await runPsnr(sourcePath, variantPath, mediaInfo) : null,
    vmafmotion: filters.vmafmotion ? await runVmafMotion(variantPath) : null,
    cambi: { available: !!filters.cambi, value: null },
  };
  metrics.available = metrics.vmaf !== null || metrics.ssim !== null || metrics.psnr !== null || metrics.vmafmotion !== null;
  if (!metrics.available) metrics.reason = "No optional quality metrics completed";
  return metrics;
}
