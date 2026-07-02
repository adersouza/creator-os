import path from "node:path";
import { existsSync, readFileSync } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

var APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
var REEL_FACTORY_ROOT =
  process.env.REEL_FACTORY_ROOT ||
  path.resolve(APP_ROOT, "../../python_packages/reel_factory");
var CAMPAIGN_FACTORY_DB =
  process.env.CAMPAIGN_FACTORY_DB ||
  path.resolve(APP_ROOT, "../../python_packages/campaign_factory/campaign_factory.sqlite");
var CONTENTFORGE_RUNS_DIR =
  process.env.CONTENTFORGE_RUNS_DIR || path.resolve(APP_ROOT, "../contentforge/output/runs");
var REEL_GUI_URL = process.env.REEL_GUI_URL || "http://127.0.0.1:8765";

// Known Soul identities (Stacey vs Stacey1 A/B split test).
var SOUL_NAMES = {
  "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36": "Stacey",
  "5828d958-91dd-4d6d-8909-934503f47644": "Stacey1",
};

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
  limit = 6,
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
      "SELECT provider, operation, estimated_cost_usd, created_at FROM ai_cost_events ORDER BY created_at DESC LIMIT 10",
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
var MAX_APPROVAL_RUN_SCAN = 100;

function errorMessage(error) {
  return error && error.message ? error.message : String(error || "unknown error");
}

function withCollectorError(fallback, error) {
  return { ...fallback, available: false, error: errorMessage(error) };
}

async function newestRunIds(runsDir, maxScan = MAX_APPROVAL_RUN_SCAN) {
  var entries = await readdir(runsDir, { withFileTypes: true });
  var runs = await Promise.all(
    entries
      .filter(function (entry) {
        return entry.isDirectory();
      })
      .map(async function (entry) {
        var runPath = path.join(runsDir, entry.name);
        var info = await stat(runPath);
        return { runId: entry.name, mtimeMs: info.mtimeMs };
      }),
  );
  runs.sort(function (a, b) {
    return b.mtimeMs - a.mtimeMs || b.runId.localeCompare(a.runId);
  });
  return {
    runIds: runs.slice(0, maxScan).map(function (entry) {
      return entry.runId;
    }),
    skipped: Math.max(0, runs.length - maxScan),
  };
}

export async function collectApprovals(runsDir = CONTENTFORGE_RUNS_DIR, limit = 8) {
  var summary = {
    available: existsSync(runsDir),
    pending: 0,
    approved: 0,
    rejected: 0,
    scanned: 0,
    skipped: 0,
    runs: [],
  };
  if (!summary.available) return summary;
  var { runIds, skipped } = await newestRunIds(runsDir);
  summary.skipped = skipped;
  summary.scanned = runIds.length;
  var runs = [];
  for (var runId of runIds) {
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
      "SELECT filename, platform, account, soul_id, posted_at, views, likes, comments FROM reel_outcomes ORDER BY posted_at DESC LIMIT ?",
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

export function collectSouls(dbPath = path.join(REEL_FACTORY_ROOT, "manifest.sqlite")) {
  var rows = readRows(
    dbPath,
    "SELECT COALESCE(soul_id, 'unattributed') AS soul_id, COUNT(*) AS posts, COALESCE(SUM(views),0) AS views, COALESCE(SUM(likes),0) AS likes, COALESCE(SUM(comments),0) AS comments, COALESCE(SUM(shares),0) AS shares, COALESCE(SUM(saves),0) AS saves FROM reel_outcomes GROUP BY COALESCE(soul_id, 'unattributed')",
  );
  if (!rows) return [];
  return rows.map(function (row) {
    var views = Number(row.views);
    var interactions =
      Number(row.likes) + Number(row.comments) + Number(row.shares) + Number(row.saves);
    return {
      soulId: row.soul_id,
      name: SOUL_NAMES[row.soul_id] || String(row.soul_id).slice(0, 8),
      posts: Number(row.posts),
      views,
      engagementRate: views > 0 ? interactions / views : null,
    };
  });
}

export async function collectReelGui(baseUrl = REEL_GUI_URL) {
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

export function buildProductionLine({ reelGui, renderQueue, approvals, outcomes }) {
  var queued = Number(renderQueue.counts.queued || 0);
  var running = Number(renderQueue.counts.running || 0) + Number(renderQueue.counts.claimed || 0);
  var scheduled =
    Number(outcomes.slots.planned || 0) +
    Number(outcomes.slots.approved || 0) +
    Number(outcomes.slots.scheduled || 0);
  return [
    {
      key: "generate",
      label: "Generate",
      value: reelGui ? Number(reelGui.in_flight_generations || 0) : null,
      detail: reelGui ? "in flight" : "reel factory offline",
      tone: reelGui ? (Number(reelGui.in_flight_generations || 0) > 0 ? "live" : "idle") : "off",
    },
    {
      key: "render",
      label: "Render",
      value: queued + running,
      detail: running > 0 ? running + " running" : "queued",
      tone: running > 0 ? "live" : queued > 0 ? "signal" : "idle",
    },
    {
      key: "qc",
      label: "QC / Review",
      value: reelGui ? Number(reelGui.needs_review || 0) : null,
      detail: "needs review",
      tone: reelGui && Number(reelGui.needs_review || 0) > 0 ? "signal" : "idle",
    },
    {
      key: "approve",
      label: "Approve",
      value: approvals.pending,
      detail: "awaiting you",
      tone: approvals.pending > 0 ? "signal" : "idle",
    },
    {
      key: "schedule",
      label: "Schedule",
      value: scheduled,
      detail: "slots open",
      tone: scheduled > 0 ? "live" : "idle",
    },
    {
      key: "posted",
      label: "Posted",
      value: outcomes.count,
      detail: "with outcomes",
      tone: outcomes.count > 0 ? "live" : "idle",
    },
  ];
}

export function buildEventLog({ spend, failedGenerations, outcomes }, limit = 12) {
  var events = [];
  for (var cost of spend.recent) {
    events.push({
      at: cost.created_at,
      kind: "cost",
      text: cost.provider + " " + cost.operation,
      value: "$" + Number(cost.estimated_cost_usd).toFixed(2),
    });
  }
  for (var failure of failedGenerations.recent) {
    events.push({
      at: failure.timestamp || failure.created_at || null,
      kind: "failure",
      text: failure.reason || failure.stage || "generation failed",
      value: failure.filename || "",
    });
  }
  for (var outcome of outcomes.recent) {
    events.push({
      at: outcome.posted_at,
      kind: "post",
      text: (outcome.account || outcome.platform || "posted") + " · " + (outcome.filename || ""),
      value: Number(outcome.views || 0) + " views",
    });
  }
  events.sort(function (a, b) {
    return String(b.at || "").localeCompare(String(a.at || ""));
  });
  return events.slice(0, limit);
}

export async function collectState({ collectors = {} } = {}) {
  var collectApprovalsFn = collectors.collectApprovals || collectApprovals;
  var collectReelGuiFn = collectors.collectReelGui || collectReelGui;
  var collectRenderQueueFn = collectors.collectRenderQueue || collectRenderQueue;
  var collectFailedGenerationsFn =
    collectors.collectFailedGenerations || collectFailedGenerations;
  var collectSpendFn = collectors.collectSpend || collectSpend;
  var collectOutcomesFn = collectors.collectOutcomes || collectOutcomes;
  var collectSoulsFn = collectors.collectSouls || collectSouls;
  var [approvals, reelGui] = await Promise.all([
    Promise.resolve()
      .then(function () {
        return collectApprovalsFn();
      })
      .catch(function (error) {
      return withCollectorError(
        { pending: 0, approved: 0, rejected: 0, scanned: 0, skipped: 0, runs: [] },
        error,
      );
    }),
    Promise.resolve()
      .then(function () {
        return collectReelGuiFn();
      })
      .catch(function () {
        return null;
      }),
  ]);
  var renderQueue;
  try {
    renderQueue = collectRenderQueueFn();
  } catch (error) {
    renderQueue = withCollectorError({ counts: {} }, error);
  }
  var failedGenerations;
  try {
    failedGenerations = collectFailedGenerationsFn();
  } catch (error) {
    failedGenerations = withCollectorError({ count: 0, recent: [] }, error);
  }
  var spend;
  try {
    spend = collectSpendFn();
  } catch (error) {
    spend = withCollectorError(
      { todayUsd: 0, todayEvents: 0, budgetUsd: null, recent: [] },
      error,
    );
  }
  var outcomes;
  try {
    outcomes = collectOutcomesFn();
  } catch (error) {
    outcomes = withCollectorError({ count: 0, totals: {}, recent: [], slots: {} }, error);
  }
  var souls;
  try {
    souls = { available: true, items: collectSoulsFn() };
  } catch (error) {
    souls = withCollectorError({ items: [] }, error);
  }
  return {
    schema: "creator_os.command_center.v1",
    generatedAt: new Date().toISOString(),
    onAir: Boolean(reelGui),
    line: buildProductionLine({ reelGui, renderQueue, approvals, outcomes }),
    failedTotal:
      failedGenerations.count + (reelGui ? Number(reelGui.failed_generations || 0) : 0),
    renderQueue,
    failedGenerations,
    spend,
    approvals,
    outcomes,
    souls,
    events: buildEventLog({ spend, failedGenerations, outcomes }),
  };
}
