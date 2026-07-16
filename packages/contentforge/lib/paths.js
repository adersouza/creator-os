import path from "path";
import { fileURLToPath } from "url";

var LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
export var PROJECT_ROOT = path.dirname(LIB_DIR);
export var UPLOADS_DIR = path.join(PROJECT_ROOT, "uploads");
export var OUTPUT_DIR = path.join(PROJECT_ROOT, "output");
var RUNS_DIR = path.join(OUTPUT_DIR, "runs");
export var LEGACY_FINAL_DIR = path.join(OUTPUT_DIR, "final");
var REFERENCE_DIR = path.join(OUTPUT_DIR, "reference");

var RUN_ID_RE = /^[a-f0-9]{8}$/i;

export function isValidRunId(runId) {
  return typeof runId === "string" && RUN_ID_RE.test(runId);
}

function safeBasename(filename) {
  if (!filename || typeof filename !== "string") return null;
  var base = path.basename(filename);
  if (!base || base === "." || base === "..") return null;
  return base;
}

export function ensureInside(baseDir, candidatePath) {
  var base = path.resolve(baseDir);
  var candidate = path.resolve(candidatePath);
  var rel = path.relative(base, candidate);
  if (rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel))) {
    return candidate;
  }
  return null;
}

export function resolveUploadPath(inputFile) {
  var safeName = safeBasename(String(inputFile || "").replace(/^uploads\//, ""));
  if (!safeName) return null;
  return ensureInside(UPLOADS_DIR, path.join(UPLOADS_DIR, safeName));
}

export function clientUploadPath(inputFile) {
  var safeName = safeBasename(String(inputFile || "").replace(/^uploads\//, ""));
  return safeName ? "uploads/" + safeName : null;
}

export function getRunRoot(runId) {
  if (!isValidRunId(runId)) return null;
  return path.join(RUNS_DIR, runId);
}

export function getRunFinalDir(runId) {
  var runRoot = getRunRoot(runId);
  return runRoot ? path.join(runRoot, "final") : null;
}

export function getRunEditsDir(runId) {
  var runRoot = getRunRoot(runId);
  return runRoot ? path.join(runRoot, "edits") : null;
}

export function resolveRunFinalDir(runId) {
  if (runId === "latest") return LEGACY_FINAL_DIR;
  var finalDir = getRunFinalDir(runId);
  if (!finalDir) return null;
  return ensureInside(RUNS_DIR, finalDir);
}

export function resolveRunFile(runId, filename) {
  var finalDir = resolveRunFinalDir(runId);
  var safeName = safeBasename(filename);
  if (!finalDir || !safeName) return null;
  return ensureInside(finalDir, path.join(finalDir, safeName));
}

export function resolveAllowedReferenceTarget(target) {
  if (!target) return LEGACY_FINAL_DIR;

  var candidate = path.resolve(PROJECT_ROOT, target);
  var allowedRoots = [UPLOADS_DIR, OUTPUT_DIR, REFERENCE_DIR, LEGACY_FINAL_DIR, RUNS_DIR];
  for (var root of allowedRoots) {
    var safe = ensureInside(root, candidate);
    if (safe) return safe;
  }
  return null;
}
