import crypto from "crypto";
import path from "path";
import { createReadStream, existsSync, renameSync, rmSync, statSync, writeFileSync } from "fs";
import { mkdir } from "fs/promises";
import { spawn } from "child_process";
import { buildEditArgs } from "./media-tools.js";
import { getRunFinalDir } from "./paths.js";
import { probeMedia } from "./reels.js";

var PROCESS_TIMEOUT_MS = 5 * 60 * 1000;
var editorialExecutor = runFfmpeg;
var editorialProbe = probeMedia;
var editorialRunIdFactory = () => crypto.randomBytes(4).toString("hex");

var RECIPE_DEFINITIONS = [
  {
    familyName: "head_trim",
    profile: "trim_head_4_frames",
    operation: "trim_head_frames",
    frameCount: 4,
  },
  {
    familyName: "tail_trim",
    profile: "trim_tail_2_frames",
    operation: "trim_tail_frames",
    frameCount: 2,
  },
  {
    familyName: "speed_up",
    profile: "speed_1_03x",
    operation: "retime",
    speed: 1.03,
  },
  {
    familyName: "slow_down",
    profile: "speed_0_97x",
    operation: "retime",
    speed: 0.97,
  },
];

export function buildKlingEditorialRecipes(mediaInfo, requestedCount = 2) {
  var fps = Number(mediaInfo?.fps || 0);
  var duration = Number(mediaInfo?.duration || 0);
  if (!Number.isFinite(fps) || fps <= 0) {
    throw new Error("kling_editorial_source_fps_missing");
  }
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error("kling_editorial_source_duration_missing");
  }
  var count = Math.max(1, Math.min(RECIPE_DEFINITIONS.length, parseInt(requestedCount, 10) || 2));
  return RECIPE_DEFINITIONS.slice(0, count).map(function (definition, index) {
    return materializeRecipe(definition, index, fps, duration);
  });
}

function materializeRecipe(definition, index, fps, duration) {
  var editOptions = {};
  var expectedDuration = duration;
  var operationDetails;
  if (definition.operation === "trim_head_frames") {
    var trimStart = definition.frameCount / fps;
    expectedDuration = duration - trimStart;
    editOptions.trimStart = roundSeconds(trimStart);
    operationDetails = {
      type: definition.operation,
      frameCount: definition.frameCount,
      seconds: roundSeconds(trimStart),
    };
  } else if (definition.operation === "trim_tail_frames") {
    var tailSeconds = definition.frameCount / fps;
    expectedDuration = duration - tailSeconds;
    editOptions.trimDuration = roundSeconds(expectedDuration);
    operationDetails = {
      type: definition.operation,
      frameCount: definition.frameCount,
      seconds: roundSeconds(tailSeconds),
    };
  } else {
    editOptions.speed = definition.speed;
    expectedDuration = duration / definition.speed;
    operationDetails = {
      type: definition.operation,
      speed: definition.speed,
    };
  }
  if (expectedDuration <= Math.max(0.25, 2 / fps)) {
    throw new Error("kling_editorial_source_too_short_for_" + definition.familyName);
  }
  return {
    variantIndex: index + 1,
    operationSet: "kling_editorial",
    familyName: definition.familyName,
    variantFamilyRecipe: {
      preset: "kling_editorial",
      familyName: definition.familyName,
      profile: definition.profile,
      temporalConsistency: "whole_clip",
    },
    operationSetSummary: definition.profile,
    operationDetails,
    editOptions,
    expectedDurationSeconds: roundSeconds(expectedDuration),
    outputFilename: "kling_editorial_" + String(index + 1).padStart(2, "0") + "_" + definition.profile + ".mp4",
    operationSignals: {
      coverFrameDifferent: definition.familyName === "head_trim",
      temporalDifferent: true,
      captionLaneDifferent: false,
      cropFamilyDifferent: false,
      colorProfileDifferent: false,
      audioOffsetDifferent: false,
      containerMetadataDifferent: false,
      encoderSignatureDifferent: false,
      handoffManifestDifferent: false,
      metadataChanged: false,
      horizontalFlip: false,
      heavyColorShift: false,
      artificialDegradation: false,
      captionTextChanged: false,
      faceRiskCrop: false,
    },
    blockedOperations: [
      "horizontal_flip",
      "color_shift",
      "artificial_degradation",
      "metadata_spoofing",
      "caption_render",
      "provider_generation",
    ],
  };
}

export async function runKlingEditorialDerivatives({
  sourcePath,
  sourceClientPath,
  variantCount = 2,
  sourceCaptionState,
  sourceCaptionEvidence,
  signal,
  sendEvent,
}) {
  if (!sourcePath || !existsSync(sourcePath)) {
    throw new Error("kling_editorial_source_missing");
  }
  if (sourceCaptionState !== "uncaptioned_verified" || !String(sourceCaptionEvidence || "").trim()) {
    throw new Error("kling_editorial_uncaptioned_source_evidence_missing");
  }
  if (signal?.aborted) throw new Error("kling_editorial_aborted");
  var sourceMedia = await editorialProbe(sourcePath);
  var recipes = buildKlingEditorialRecipes(sourceMedia, variantCount);
  assertDistinctOutputs(recipes);
  var sourceSha256 = await sha256File(sourcePath);
  var runId = editorialRunIdFactory();
  var outputDir = getRunFinalDir(runId);
  if (!outputDir) throw new Error("kling_editorial_output_dir_invalid");
  if (existsSync(outputDir)) throw new Error("kling_editorial_run_collision:" + runId);
  await mkdir(outputDir, { recursive: true });
  var startedAt = new Date().toISOString();
  var state = {
    schema: "contentforge.kling_editorial_run.v1",
    runId,
    status: "running",
    sourcePath,
    sourceClientPath,
    sourceSha256,
    sourceMedia,
    requestedVariants: recipes.length,
    completedArtifacts: [],
    startedAt,
    updatedAt: startedAt,
    captionStatus: captionPendingStatus(sourceCaptionEvidence),
    providerActivity: {
      providerCalls: 0,
      paidGenerationCalls: 0,
    },
  };
  writeRunState(outputDir, state);
  sendEvent?.({
    type: "phase",
    phase: "editorial",
    message: "Rendering deterministic Kling timing derivatives",
  });
  try {
    for (var recipe of recipes) {
      if (signal?.aborted) throw new Error("kling_editorial_aborted");
      var outputPath = path.join(outputDir, recipe.outputFilename);
      if (existsSync(outputPath)) {
        throw new Error("kling_editorial_output_collision:" + recipe.outputFilename);
      }
      var args = buildEditArgs(sourcePath, outputPath, {
        ...recipe.editOptions,
        width: sourceMedia.width,
        height: sourceMedia.height,
        fps: sourceMedia.fps,
      });
      assertEditorialArgs(args);
      sendEvent?.({
        type: "progress",
        phase: "editorial",
        current: recipe.variantIndex,
        total: recipes.length,
        filename: recipe.outputFilename,
        recipe: recipe.variantFamilyRecipe,
      });
      try {
        await editorialExecutor(args, { signal });
      } catch (error) {
        rmSync(outputPath, { force: true });
        throw error;
      }
      if (!existsSync(outputPath) || statSync(outputPath).size <= 0) {
        throw new Error("kling_editorial_output_missing:" + recipe.outputFilename);
      }
      var outputMedia;
      var outputSha256;
      try {
        outputMedia = await editorialProbe(outputPath);
        verifyRenderedEvidence({
          recipe,
          sourceMedia,
          outputMedia,
        });
        outputSha256 = await sha256File(outputPath);
        if (outputSha256 === sourceSha256) {
          throw new Error("kling_editorial_output_matches_source:" + recipe.familyName);
        }
        if (state.completedArtifacts.some((artifact) => artifact.outputSha256 === outputSha256)) {
          throw new Error("kling_editorial_duplicate_output_fingerprint:" + recipe.familyName);
        }
      } catch (error) {
        rmSync(outputPath, { force: true });
        throw error;
      }
      var artifact = {
        filename: recipe.outputFilename,
        filePath: outputPath,
        recipe,
        ffmpegArgs: args,
        sourceSha256,
        outputSha256,
        sourceMedia,
        outputMedia,
        expectedDurationSeconds: recipe.expectedDurationSeconds,
        captionStatus: captionPendingStatus(sourceCaptionEvidence),
        providerActivity: {
          providerCalls: 0,
          paidGenerationCalls: 0,
        },
      };
      state.completedArtifacts.push(artifact);
      state.updatedAt = new Date().toISOString();
      writeRunState(outputDir, state);
      sendEvent?.({
        type: "log",
        text: "✓ " + recipe.outputFilename + " " + recipe.operationSetSummary + "\n",
      });
    }
    state.status = "completed";
    state.completedAt = new Date().toISOString();
    state.updatedAt = state.completedAt;
    writeRunState(outputDir, state);
    return {
      runId,
      outputDir,
      total: state.completedArtifacts.length,
      attempted: state.completedArtifacts.length,
      failed: 0,
      variantPreset: "kling_editorial",
      renderedArtifacts: state.completedArtifacts,
      providerActivity: state.providerActivity,
      captionStatus: state.captionStatus,
    };
  } catch (error) {
    state.status = signal?.aborted || error?.message === "kling_editorial_aborted" ? "interrupted" : "failed";
    state.error = String(error?.message || error);
    state.updatedAt = new Date().toISOString();
    state.retryOrResumeSafe = true;
    writeRunState(outputDir, state);
    throw error;
  }
}

export function verifyRenderedEvidence({ recipe, sourceMedia, outputMedia }) {
  var fps = Number(sourceMedia?.fps || 0);
  var tolerance = Math.max(0.12, fps > 0 ? 2 / fps : 0.12);
  var actualDuration = Number(outputMedia?.duration || 0);
  if (!Number.isFinite(actualDuration) || actualDuration <= 0) {
    throw new Error("kling_editorial_output_duration_missing:" + recipe.familyName);
  }
  if (Math.abs(actualDuration - recipe.expectedDurationSeconds) > tolerance) {
    throw new Error("kling_editorial_duration_mismatch:" + recipe.familyName);
  }
  if (
    Number(outputMedia?.width || 0) !== Number(sourceMedia?.width || 0) ||
    Number(outputMedia?.height || 0) !== Number(sourceMedia?.height || 0)
  ) {
    throw new Error("kling_editorial_dimensions_mismatch:" + recipe.familyName);
  }
  var outputFps = Number(outputMedia?.fps || 0);
  if (outputFps <= 0) {
    throw new Error("kling_editorial_output_fps_missing:" + recipe.familyName);
  }
  if (Math.abs(outputFps - fps) > 0.05) {
    throw new Error("kling_editorial_fps_mismatch:" + recipe.familyName);
  }
  return true;
}

export function assertEditorialArgs(args) {
  var joined = args.join(" ");
  for (var forbidden of [
    "hflip",
    "noise=",
    "rotate=",
    "hue=",
    "colorbalance=",
    "creation_time=",
    "handler_name=",
    "drawtext=",
    "crop=",
    "pad=",
    "overlay=",
    "transpose=",
    "vflip",
    "zoompan=",
    "eq=",
    "-metadata",
    "-map_metadata",
  ]) {
    if (joined.includes(forbidden)) {
      throw new Error("kling_editorial_forbidden_ffmpeg_operation:" + forbidden);
    }
  }
  return true;
}

function assertDistinctOutputs(recipes) {
  var filenames = recipes.map((recipe) => recipe.outputFilename);
  if (new Set(filenames).size !== filenames.length) {
    throw new Error("kling_editorial_duplicate_output_mapping");
  }
}

function captionPendingStatus(sourceCaptionEvidence) {
  return {
    status: "pending_reel_factory",
    sourceCaptionState: "uncaptioned_verified",
    sourceCaptionEvidence: String(sourceCaptionEvidence),
    burnedByThisStage: false,
    burnedIntoMedia: false,
    placementDecisionRequired: true,
    requiredRenderer: "reel_factory.placement_to_caption_render",
  };
}

function roundSeconds(value) {
  return Number(value.toFixed(6));
}

function writeRunState(outputDir, state) {
  var destination = path.join(outputDir, "run_config.json");
  var temp = destination + "." + process.pid + ".tmp";
  writeFileSync(temp, JSON.stringify(state, null, 2));
  renameSync(temp, destination);
}

function sha256File(filePath) {
  return new Promise(function (resolve, reject) {
    var digest = crypto.createHash("sha256");
    var stream = createReadStream(filePath);
    stream.on("error", reject);
    stream.on("data", (chunk) => digest.update(chunk));
    stream.on("end", () => resolve(digest.digest("hex")));
  });
}

function runFfmpeg(args, { signal } = {}) {
  return new Promise(function (resolve, reject) {
    if (signal?.aborted) {
      reject(new Error("kling_editorial_aborted"));
      return;
    }
    var child = spawn("ffmpeg", args, {
      stdio: ["ignore", "ignore", "pipe"],
    });
    var stderr = "";
    var settled = false;
    function cleanup() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
    function fail(error) {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    }
    function abort() {
      child.kill("SIGKILL");
      fail(new Error("kling_editorial_aborted"));
    }
    var timer = setTimeout(function () {
      child.kill("SIGKILL");
      fail(new Error("kling_editorial_ffmpeg_timeout"));
    }, PROCESS_TIMEOUT_MS);
    signal?.addEventListener("abort", abort, { once: true });
    child.stderr.on("data", function (chunk) {
      if (stderr.length < 50000) stderr += chunk.toString();
    });
    child.on("error", fail);
    child.on("close", function (code) {
      if (settled) return;
      settled = true;
      cleanup();
      if (code === 0) resolve(stderr);
      else reject(new Error("kling_editorial_ffmpeg_failed:" + code + ":" + stderr.slice(-500)));
    });
  });
}

export function __setEditorialRuntimeForTests({ executor, probe, runIdFactory } = {}) {
  editorialExecutor = executor || runFfmpeg;
  editorialProbe = probe || probeMedia;
  editorialRunIdFactory = runIdFactory || (() => crypto.randomBytes(4).toString("hex"));
}
