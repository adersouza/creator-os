import path from "node:path";
import { existsSync, readFileSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import { PROJECT_ROOT, RUNS_DIR } from "./paths.js";

// ponytail: direct read-only sqlite/jsonl reads of the python packages' data
// files — no shared client library; add one if a third consumer appears.
var REEL_FACTORY_ROOT =
  process.env.REEL_FACTORY_ROOT ||
  path.resolve(PROJECT_ROOT, "../../python_packages/reel_factory");
var CAMPAIGN_FACTORY_DB =
  process.env.CAMPAIGN_FACTORY_DB ||
  path.resolve(PROJECT_ROOT, "../../python_packages/campaign_factory/campaign_factory.sqlite");
var REEL_GUI_URL = process.env.REEL_GUI_URL || "http://127.0.0.1:8765";

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

export function collectRenderQueue(dbPath = path.join(REEL_FACTORY_ROOT, "render_queue.sqlite")) {
  var rows = readRows(dbPath, "SELECT status, COUNT(*) AS n FROM queue_jobs GROUP BY status");
  if (!rows) return { available: false, counts: {} };
  var counts = {};
  for (var row of rows) counts[row.status] = Number(row.n);
  return { available: true, counts };
}

export function collectFailedGenerations(
  jsonlPath = path.join(REEL_FACTORY_ROOT, "failed_generations.jsonl"),
  limit = 5,
) {
  if (!existsSync(jsonlPath)) return { count: 0, recent: [] };
  var lines = readFileSync(jsonlPath, "utf8").split("\n").filter(Boolean);
  var recent = lines.slice(-limit).map(function (line) {
    try {
      return JSON.parse(line);
    } catch {
      return { reason: line.slice(0, 200) };
    }
  });
  return { count: lines.length, recent: recent.reverse() };
}

export function collectSpend({ dbPath = CAMPAIGN_FACTORY_DB, now = new Date() } = {}) {
  // Mirrors higgsfield_cost_preflight._spent_today_usd: UTC day prefix match.
  var day = now.toISOString().slice(0, 10);
  var budgetRaw = Number(process.env.HIGGSFIELD_DAILY_BUDGET_USD);
  var budgetUsd = Number.isFinite(budgetRaw) && budgetRaw > 0 ? budgetRaw : null;
  var totals = readRows(
    dbPath,
    "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS usd, COUNT(*) AS n FROM ai_cost_events WHERE substr(created_at, 1, 10) = ?",
    [day],
  );
  if (!totals) return { available: false, todayUsd: 0, todayEvents: 0, budgetUsd, recent: [] };
  var recent =
    readRows(
      dbPath,
      "SELECT provider, operation, estimated_cost_usd, created_at FROM ai_cost_events ORDER BY created_at DESC LIMIT 8",
    ) || [];
  return {
    available: true,
    todayUsd: Number(totals[0].usd) || 0,
    todayEvents: Number(totals[0].n) || 0,
    budgetUsd,
    recent,
  };
}

var MEDIA_RE = /\.(mp4|mov|webm|png|jpe?g|webp)$/i;

export async function collectApprovals(runsDir = RUNS_DIR, limit = 6) {
  var summary = { pending: 0, approved: 0, rejected: 0, runs: [] };
  if (!existsSync(runsDir)) return summary;
  var entries = await readdir(runsDir).catch(function () {
    return [];
  });
  var runs = [];
  for (var runId of entries) {
    var finalDir = path.join(runsDir, runId, "final");
    if (!existsSync(finalDir)) continue;
    var files = await readdir(finalDir).catch(function () {
      return [];
    });
    var mediaCount = files.filter(function (f) {
      return MEDIA_RE.test(f);
    }).length;
    if (mediaCount === 0) continue;
    var decisions = {};
    var statePath = path.join(finalDir, "review_decisions.json");
    if (existsSync(statePath)) {
      try {
        decisions = JSON.parse(readFileSync(statePath, "utf8")).decisions || {};
      } catch {
        decisions = {};
      }
    }
    var approved = 0;
    var rejected = 0;
    for (var record of Object.values(decisions)) {
      if (record.decision === "approved") approved += 1;
      else if (record.decision === "rejected") rejected += 1;
    }
    var pending = Math.max(0, mediaCount - approved - rejected);
    runs.push({ runId, media: mediaCount, pending, approved, rejected });
    summary.pending += pending;
    summary.approved += approved;
    summary.rejected += rejected;
  }
  runs.sort(function (a, b) {
    return b.pending - a.pending || b.media - a.media;
  });
  summary.runs = runs.slice(0, limit);
  return summary;
}

export function collectOutcomes(dbPath = path.join(REEL_FACTORY_ROOT, "manifest.sqlite"), limit = 8) {
  var totalsRows = readRows(
    dbPath,
    "SELECT COUNT(*) AS n, COALESCE(SUM(views),0) AS views, COALESCE(SUM(likes),0) AS likes, COALESCE(SUM(comments),0) AS comments, COALESCE(SUM(shares),0) AS shares, COALESCE(SUM(saves),0) AS saves FROM reel_outcomes",
  );
  var totals = totalsRows ? totalsRows[0] : null;
  var recent =
    readRows(
      dbPath,
      "SELECT filename, platform, account, posted_at, views, likes, comments FROM reel_outcomes ORDER BY posted_at DESC LIMIT ?",
      [limit],
    ) || [];
  var slotRows =
    readRows(dbPath, "SELECT post_status, COUNT(*) AS n FROM posting_slots GROUP BY post_status") || [];
  var slots = {};
  for (var row of slotRows) slots[row.post_status] = Number(row.n);
  return {
    available: totals !== null,
    count: totals ? Number(totals.n) : 0,
    totals: totals
      ? {
          views: Number(totals.views),
          likes: Number(totals.likes),
          comments: Number(totals.comments),
          shares: Number(totals.shares),
          saves: Number(totals.saves),
        }
      : {},
    recent,
    slots,
  };
}

export async function collectInFlight(baseUrl = REEL_GUI_URL) {
  // In-flight generation jobs live only in reel_gui process memory; null = offline.
  try {
    var headers = {};
    if (process.env.CREATOR_OS_API_TOKEN) {
      headers.Authorization = "Bearer " + process.env.CREATOR_OS_API_TOKEN;
    }
    var res = await fetch(baseUrl + "/api/dashboard/summary", {
      headers,
      signal: AbortSignal.timeout(1500),
    });
    if (!res.ok) return null;
    var data = await res.json();
    return data.command_center || null;
  } catch {
    return null;
  }
}

export async function collectDashboard() {
  var [approvals, inFlight] = await Promise.all([collectApprovals(), collectInFlight()]);
  return {
    schema: "contentforge.dashboard.v1",
    generatedAt: new Date().toISOString(),
    renderQueue: collectRenderQueue(),
    failedGenerations: collectFailedGenerations(),
    spend: collectSpend(),
    approvals,
    outcomes: collectOutcomes(),
    reelGui: inFlight ? { online: true, commandCenter: inFlight } : { online: false, commandCenter: null },
  };
}
