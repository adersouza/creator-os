import { execFile } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { getPythonCommand } from "./python-runtime.js";

function run(command, args) {
  return new Promise(function (resolve) {
    execFile(command, args, { timeout: 10000, maxBuffer: 2 * 1024 * 1024 }, function (error, stdout, stderr) {
      resolve({ error, stdout: stdout || "", stderr: stderr || "" });
    });
  });
}

export async function getLocalDiagnostics() {
  var filters = await run("ffmpeg", ["-hide_banner", "-filters"]);
  var filterText = filters.stdout + filters.stderr;
  var fpcalc = await run("fpcalc", ["-version"]);
  var pythonCommand = getPythonCommand();
  var python = await run(pythonCommand, ["--version"]);
  var sscdModelPath = path.join(process.cwd(), "models", "sscd_disc_mixup.torchscript.pt");
  return {
    ffmpeg: {
      available: !filters.error,
      filters: {
        libvmaf: /libvmaf/i.test(filterText),
        vmafmotion: /vmafmotion/i.test(filterText),
        psnr: /(^|\s)psnr(\s|$)/i.test(filterText),
        ssim: /(^|\s)ssim(\s|$)/i.test(filterText),
        cambi: /cambi/i.test(filterText),
        blackdetect: /blackdetect/i.test(filterText),
        silencedetect: /silencedetect/i.test(filterText),
        loudnorm: /loudnorm/i.test(filterText),
        cropdetect: /cropdetect/i.test(filterText),
      },
    },
    fpcalc: {
      available: !fpcalc.error,
      version: fpcalc.stdout.trim() || fpcalc.stderr.trim() || null,
    },
    python: {
      available: !python.error,
      version: python.stdout.trim() || python.stderr.trim() || null,
      command: pythonCommand,
    },
    sscd: {
      modelPresent: existsSync(sscdModelPath),
      modelPath: sscdModelPath,
    },
    setup: [
      {
        id: "ffmpeg",
        label: "FFmpeg",
        ok: !filters.error,
        detail: !filters.error ? "available" : "Install ffmpeg and make sure it is on PATH.",
      },
      {
        id: "qualityFilters",
        label: "Quality filters",
        ok: /(^|\s)ssim(\s|$)/i.test(filterText) && /(^|\s)psnr(\s|$)/i.test(filterText),
        detail: "SSIM/PSNR are used for fast local quality checks.",
      },
      {
        id: "libvmaf",
        label: "libvmaf",
        ok: /libvmaf/i.test(filterText),
        detail: "Optional: enables deeper VMAF scoring when FFmpeg includes libvmaf.",
      },
      {
        id: "drawtext",
        label: "drawtext",
        ok: /drawtext/i.test(filterText),
        detail: "Optional: ContentForge falls back to PNG overlays when drawtext is missing.",
      },
      {
        id: "fpcalc",
        label: "fpcalc",
        ok: !fpcalc.error,
        detail: "Optional: install Chromaprint/fpcalc for audio fingerprint checks.",
      },
      {
        id: "sscd",
        label: "SSCD model",
        ok: existsSync(sscdModelPath),
        detail: "Optional: place sscd_disc_mixup.torchscript.pt in ./models for SSCD similarity.",
      },
    ],
  };
}
