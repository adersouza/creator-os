import path from "node:path";
import { existsSync, readFileSync } from "node:fs";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

var APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
var REPO_ROOT = path.resolve(APP_ROOT, "../..");
var REEL_FACTORY_ROOT =
  process.env.REEL_FACTORY_ROOT || path.resolve(REPO_ROOT, "python_packages/reel_factory");

export var DECISIONS = ["approved", "rejected", "regenerate"];
var ASSET_ID_RE = /^[A-Za-z0-9._-]+$/;

function manifestPath(root = REEL_FACTORY_ROOT) {
  return path.join(root, "manifest.sqlite");
}

function readRows(dbPath, sql, params = []) {
  if (!existsSync(dbPath)) return null;
  var db;
  try {
    db = new DatabaseSync(dbPath, { readOnly: true });
    return db.prepare(sql).all(...params);
  } catch {
    return null;
  } finally {
    if (db) {
      try {
        db.close();
      } catch {
        // already closed
      }
    }
  }
}

function parseJson(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// Best-effort caption/QC pull from the lineage sidecar; shapes vary by
// pipeline stage, so surface what exists rather than requiring a schema.
function readLineageSummary(lineagePath) {
  if (!lineagePath || !existsSync(lineagePath)) return null;
  var lineage;
  try {
    lineage = JSON.parse(readFileSync(lineagePath, "utf8"));
  } catch {
    return null;
  }
  var caption = lineage.caption;
  return {
    caption:
      typeof caption === "string" ? caption : caption && (caption.text || caption.caption) || null,
    captionHash:
      lineage.caption_hash || (caption && (caption.hash || caption.caption_hash)) || null,
    qc: lineage.qc || lineage.qc_summary || null,
    features: lineage.features || null,
  };
}

function rowToItem(row) {
  return {
    assetId: row.asset_id,
    campaign: row.campaign,
    runId: row.run_id,
    state: row.state,
    attempts: Number(row.attempts || 0),
    rankScore: row.rank_score == null ? null : Number(row.rank_score),
    predictedEngagement: parseJson(row.predicted_engagement_json),
    lineage: readLineageSummary(row.lineage_path),
    lineagePath: row.lineage_path || null,
    outputPath: row.output_path || null,
    hasMedia: Boolean(row.output_path && existsSync(row.output_path)),
    decision: row.approval_decision || null,
    reason: row.approval_reason || null,
    approvedAt: row.approved_at == null ? null : Number(row.approved_at),
    stateUpdatedAt: Number(row.state_updated_at),
    createdAt: Number(row.created_at),
  };
}

export function collectInbox(dbPath = manifestPath()) {
  var rows = readRows(
    dbPath,
    "SELECT * FROM asset_pipeline_state WHERE state = 'awaiting_approval'" +
      " ORDER BY rank_score DESC, created_at ASC",
  );
  if (!rows) return { available: false, items: [] };
  return { available: true, items: rows.map(rowToItem) };
}

export function collectInboxHistory(dbPath = manifestPath(), limit = 50) {
  var rows = readRows(
    dbPath,
    "SELECT * FROM asset_pipeline_state WHERE approval_decision IS NOT NULL" +
      " ORDER BY COALESCE(approved_at, state_updated_at) DESC LIMIT ?",
    [limit],
  );
  if (!rows) return { available: false, items: [] };
  return { available: true, items: rows.map(rowToItem) };
}

export function getInboxAsset(assetId, dbPath = manifestPath()) {
  if (!ASSET_ID_RE.test(String(assetId || ""))) return null;
  var rows = readRows(dbPath, "SELECT * FROM asset_pipeline_state WHERE asset_id = ?", [assetId]);
  if (!rows || rows.length === 0) return null;
  return rowToItem(rows[0]);
}

export function validateDecision({ assetId, decision }) {
  if (!ASSET_ID_RE.test(String(assetId || ""))) return "invalid_asset_id";
  if (!DECISIONS.includes(decision)) return "invalid_decision";
  return null;
}

// Writes go through the Python orchestrator CLI so the single-writer
// discipline and legal-transition checks live in exactly one place.
export function submitDecision({ assetId, decision, reason, root = REEL_FACTORY_ROOT }) {
  var invalid = validateDecision({ assetId, decision });
  if (invalid) return Promise.resolve({ ok: false, status: 400, reason: invalid });
  var args = [
    "run",
    "--directory",
    root,
    "python",
    "-m",
    "reel_factory.orchestrator",
    "decide",
    "--root",
    root,
    "--asset-id",
    assetId,
    "--decision",
    decision,
  ];
  if (reason) args.push("--reason", String(reason).slice(0, 2000));
  return new Promise(function (resolve) {
    execFile("uv", args, { timeout: 60000, cwd: REPO_ROOT }, function (error, stdout, stderr) {
      var body = parseJson(String(stdout || "").trim());
      if (!error && body && !body.error) {
        resolve({ ok: true, status: 200, result: body });
        return;
      }
      var reasonText =
        (body && body.error) || String(stderr || "").slice(0, 500) || (error && error.message) || "decision failed";
      var conflict = /illegal transition|unknown asset_id/.test(reasonText);
      resolve({ ok: false, status: conflict ? 409 : 500, reason: reasonText });
    });
  });
}
