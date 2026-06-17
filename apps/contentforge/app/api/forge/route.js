import { existsSync } from "fs";
import { runPipeline, runImagePipeline } from "../../../lib/pipeline.js";
import { clientUploadPath, resolveUploadPath } from "../../../lib/paths.js";
import { acquireProcessLock } from "../../../lib/process-lock.js";
import { REELS_PROFILES } from "../../../lib/reels-profiles.js";
import { VARIANT_PRESETS, normalizeVariantPreset, validateQualityGate } from "../../../lib/variant-engine.js";

export const runtime = "nodejs";

// Hard limits
var MAX_EDITS = 30;
var MAX_SPINS = 30;
var MAX_TOTAL = 500;
var MAX_IMAGE_VARIANTS = 500;
var VALID_LEVELS = ["clean", "light", "medium", "heavy", "stealth"];
var VALID_VARIANT_PRESETS = Object.keys(VARIANT_PRESETS);

var IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".heic"];

export function createForgePostHandler(deps = {}) {
  var acquireProcessLockImpl = deps.acquireProcessLockImpl || acquireProcessLock;
  var existsSyncImpl = deps.existsSyncImpl || existsSync;
  var runPipelineImpl = deps.runPipelineImpl || runPipeline;
  var runImagePipelineImpl = deps.runImagePipelineImpl || runImagePipeline;

  return async function POST(request) {
    var lock = await acquireProcessLockImpl("forge");
    if (!lock.acquired) {
      return new Response("A forge run is already active", { status: 429 });
    }

    var config;
    try {
      config = await request.json();
    } catch (e) {
      await lock.release();
      return new Response("Invalid JSON", { status: 400 });
    }

    if (!config.inputFile || typeof config.inputFile !== "string") {
      await lock.release();
      return new Response("Missing inputFile", { status: 400 });
    }

    var inputPath = resolveUploadPath(config.inputFile);
    var safeFile = clientUploadPath(config.inputFile);
    if (!inputPath || !safeFile) {
      await lock.release();
      return new Response("Invalid inputFile", { status: 400 });
    }
    if (!existsSyncImpl(inputPath)) {
      await lock.release();
      return new Response("Input file not found", { status: 404 });
    }

    // Detect media type from extension
    var dotIdx = safeFile.lastIndexOf(".");
    var ext = dotIdx >= 0 ? safeFile.slice(dotIdx).toLowerCase() : "";
    var isImage = IMAGE_EXTS.includes(ext);
    if (config.variantPreset && !VALID_VARIANT_PRESETS.includes(config.variantPreset)) {
      await lock.release();
      return new Response("Invalid variantPreset", { status: 400 });
    }
    var variantPreset = normalizeVariantPreset(config.variantPreset, config.level);
    var variantOptions = config.variantOptions && typeof config.variantOptions === "object" ? config.variantOptions : {};
    if (!validateQualityGate(config.qualityGate)) {
      await lock.release();
      return new Response("Invalid qualityGate", { status: 400 });
    }
    var qualityGate = config.qualityGate && typeof config.qualityGate === "object" ? config.qualityGate : undefined;

    if (isImage) {
      // ─── Image pipeline ───
      var numVariants = parseInt(config.numVariants, 10);
      if (isNaN(numVariants) || numVariants < 1 || numVariants > MAX_IMAGE_VARIANTS) {
        await lock.release();
        return new Response("numVariants must be 1-" + MAX_IMAGE_VARIANTS, { status: 400 });
      }
      if (config.level && VALID_LEVELS.indexOf(config.level) === -1) {
        await lock.release();
        return new Response("Invalid level", { status: 400 });
      }

      var imageConfig = {
        inputFile: safeFile,
        numVariants: numVariants,
        level: config.level,
        variantPreset,
        variantOptions,
        qualityGate,
      };

      return streamPipeline(lock, function (sendEvent) {
        return runImagePipelineImpl(imageConfig, sendEvent);
      });
    } else {
      // ─── Video pipeline ───
      var numEdits = parseInt(config.numEdits, 10);
      var spinsPerEdit = parseInt(config.spinsPerEdit, 10);

      if (isNaN(numEdits) || numEdits < 1 || numEdits > MAX_EDITS) {
        await lock.release();
        return new Response("numEdits must be 1-" + MAX_EDITS, { status: 400 });
      }
      if (isNaN(spinsPerEdit) || spinsPerEdit < 1 || spinsPerEdit > MAX_SPINS) {
        await lock.release();
        return new Response("spinsPerEdit must be 1-" + MAX_SPINS, { status: 400 });
      }
      if (numEdits * spinsPerEdit > MAX_TOTAL) {
        await lock.release();
        return new Response("Total variants exceeds " + MAX_TOTAL, { status: 400 });
      }
      if (config.level && VALID_LEVELS.indexOf(config.level) === -1) {
        await lock.release();
        return new Response("Invalid level", { status: 400 });
      }
      var outputProfile = config.outputProfile || "organic";
      if (!REELS_PROFILES[outputProfile]) {
        await lock.release();
        return new Response("Invalid outputProfile", { status: 400 });
      }

      var videoConfig = {
        inputFile: safeFile,
        numEdits: numEdits,
        spinsPerEdit: spinsPerEdit,
        level: config.level,
        flip: !!config.flip,
        vertical: config.vertical !== false,
        outputProfile,
        variantPreset,
        variantOptions,
        qualityGate,
      };

      return streamPipeline(lock, function (sendEvent) {
        return runPipelineImpl(videoConfig, sendEvent);
      });
    }
  };
}

export const POST = createForgePostHandler();

function streamPipeline(lock, runFn) {
  var encoder = new TextEncoder();
  var aborted = false;

  var stream = new ReadableStream({
    async start(controller) {
      var sendEvent = function (data) {
        if (aborted) return;
        try {
          controller.enqueue(encoder.encode("data: " + JSON.stringify(data) + "\n\n"));
        } catch (e) {
          aborted = true;
        }
      };

      try {
        await runFn(sendEvent);
      } catch (err) {
        sendEvent({ type: "error", message: err.message });
      } finally {
        await lock.release();
        try { controller.close(); } catch (e) { /* already closed */ }
      }
    },
    async cancel() {
      aborted = true;
      await lock.release();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
}
