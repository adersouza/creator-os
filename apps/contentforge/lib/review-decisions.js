import path from "path";
import { appendFile, mkdir, readFile, writeFile } from "fs/promises";
import { existsSync, readFileSync } from "fs";
import { resolveRunFile, resolveRunFinalDir, safeBasename } from "./paths.js";

var VALID_DECISIONS = new Set(["approved", "rejected"]);
var DECISION_STATE_FILE = "review_decisions.json";
var DECISION_LOG_FILE = "review_decisions.jsonl";
var APPROVED_MANIFEST_FILE = "approved_variants_manifest.json";

function cleanText(value, maxLength = 500) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function normalizeBoolean(value) {
  return value === true || value === "true" || value === 1 || value === "1";
}

function decisionPaths(runId) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir) return null;
  return {
    finalDir,
    statePath: path.join(finalDir, DECISION_STATE_FILE),
    logPath: path.join(finalDir, DECISION_LOG_FILE),
    approvedManifestPath: path.join(finalDir, APPROVED_MANIFEST_FILE),
  };
}

function emptyState(runId) {
  return {
    schema: "contentforge.review_decisions.v1",
    runId,
    updatedAt: null,
    decisions: {},
  };
}

async function readJsonFile(filePath, fallback) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function loadVariantPackMetadata(finalDir) {
  var reportPath = path.join(finalDir, "variant_pack.json");
  if (!existsSync(reportPath)) return new Map();
  try {
    var report = JSON.parse(readFileSync(reportPath, "utf8"));
    return new Map((report.results || []).map((item) => [item.file, item]));
  } catch {
    return new Map();
  }
}

function recommendationFor(input = {}, variant = null) {
  var recommendedAction = cleanText(input.recommendedAction || variant?.recommendedAction, 80) || null;
  var recommended = input.recommended;
  if (recommended === undefined && variant) recommended = variant.recommended;
  var operatorState = cleanText(input.operatorState || variant?.operatorState, 80) || null;
  var reason = cleanText(input.recommendationReason || input.reason || variant?.recommendationReason, 200) || null;
  var blockingReasons = Array.isArray(input.blockingReasons)
    ? input.blockingReasons
    : Array.isArray(variant?.blockingReasons)
      ? variant.blockingReasons
      : [];

  if (!recommendedAction) {
    if (recommended === true || operatorState === "ready") recommendedAction = "approve_candidate";
    else if (operatorState === "fix") recommendedAction = "reject";
    else if (operatorState === "review") recommendedAction = "review";
  }

  return {
    recommendedAction,
    recommended: recommended === undefined ? null : normalizeBoolean(recommended),
    operatorState,
    reason,
    blockingReasons: blockingReasons.map((item) => cleanText(item, 120)).filter(Boolean),
  };
}

function recommendationApproves(recommendation) {
  if (recommendation.recommendedAction === "approve_candidate") return true;
  if (recommendation.recommended === true) return true;
  return recommendation.operatorState === "ready";
}

function recommendationRejects(recommendation) {
  if (recommendation.recommendedAction === "reject") return true;
  return recommendation.operatorState === "fix" || recommendation.recommended === false;
}

function isOverride(decision, recommendation) {
  if (decision === "approved") return !recommendationApproves(recommendation);
  if (decision === "rejected") return !recommendationRejects(recommendation);
  return false;
}

function buildApprovedManifest({ runId, finalDir, state, manifestPath }) {
  var decisions = Object.values(state.decisions || {});
  var approved = decisions
    .filter((record) => record.decision === "approved")
    .sort((a, b) => Number(b.chosen) - Number(a.chosen) || a.file.localeCompare(b.file))
    .map((record) => ({
      file: record.file,
      outputPath: path.join(finalDir, record.file),
      previewUrl: "/api/preview?runId=" + encodeURIComponent(runId) + "&file=" + encodeURIComponent(record.file),
      downloadUrl: "/api/download?runId=" + encodeURIComponent(runId) + "&file=" + encodeURIComponent(record.file),
      decision: record.decision,
      chosen: record.chosen,
      decidedAt: record.decidedAt,
      overrideOfRecommendation: record.overrideOfRecommendation,
      recommendation: record.recommendation,
      notes: record.notes,
    }));
  return {
    schema: "contentforge.approved_variants_manifest.v1",
    runId,
    generatedAt: new Date().toISOString(),
    approvedCount: approved.length,
    chosenFile: approved.find((item) => item.chosen)?.file || null,
    manifestPath,
    variants: approved,
  };
}

export async function loadReviewDecisions(runId) {
  var paths = decisionPaths(runId);
  if (!paths) throw new Error("Invalid runId");
  var state = await readJsonFile(paths.statePath, emptyState(runId));
  var manifest = await readJsonFile(paths.approvedManifestPath, buildApprovedManifest({
    runId,
    finalDir: paths.finalDir,
    state,
    manifestPath: paths.approvedManifestPath,
  }));
  return {
    schema: "contentforge.review_decisions_response.v1",
    runId,
    state,
    decisions: state.decisions || {},
    approvedManifest: manifest,
    approvedManifestUrl: "/api/review-decisions?runId=" + encodeURIComponent(runId) + "&format=approved-manifest",
  };
}

export async function recordReviewDecision(input = {}) {
  var runId = cleanText(input.runId, 80);
  var safeFile = safeBasename(input.file);
  var decision = cleanText(input.decision, 40);
  if (!runId) throw new Error("Missing runId");
  if (!safeFile) throw new Error("Missing file");
  if (!VALID_DECISIONS.has(decision)) throw new Error("Invalid review decision");

  var paths = decisionPaths(runId);
  if (!paths) throw new Error("Invalid runId");
  var outputPath = resolveRunFile(runId, safeFile);
  if (!outputPath || !existsSync(outputPath)) {
    var missing = new Error("Review target not found");
    missing.status = 404;
    throw missing;
  }

  var variantMetadata = loadVariantPackMetadata(paths.finalDir).get(safeFile) || null;
  var recommendation = recommendationFor(input, variantMetadata);
  var now = new Date().toISOString();
  var record = {
    schema: "contentforge.review_decision.v1",
    runId,
    file: safeFile,
    decision,
    chosen: decision === "approved" && normalizeBoolean(input.chosen),
    overrideOfRecommendation: isOverride(decision, recommendation),
    recommendation,
    notes: cleanText(input.notes, 800),
    source: cleanText(input.source, 80) || "contentforge_ui",
    decidedAt: now,
  };

  var state = await readJsonFile(paths.statePath, emptyState(runId));
  state.schema = "contentforge.review_decisions.v1";
  state.runId = runId;
  state.updatedAt = now;
  state.decisions = state.decisions || {};
  if (record.chosen) {
    for (var existing of Object.values(state.decisions)) {
      existing.chosen = false;
    }
  }
  state.decisions[safeFile] = record;

  var manifest = buildApprovedManifest({
    runId,
    finalDir: paths.finalDir,
    state,
    manifestPath: paths.approvedManifestPath,
  });

  await mkdir(paths.finalDir, { recursive: true });
  await appendFile(paths.logPath, JSON.stringify(record) + "\n");
  await writeFile(paths.statePath, JSON.stringify(state, null, 2));
  await writeFile(paths.approvedManifestPath, JSON.stringify(manifest, null, 2));

  return {
    ok: true,
    record,
    state,
    approvedManifest: manifest,
    approvedManifestUrl: "/api/review-decisions?runId=" + encodeURIComponent(runId) + "&format=approved-manifest",
  };
}

