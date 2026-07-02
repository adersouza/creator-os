import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { mkdtempSync, mkdirSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import {
  buildEventLog,
  buildProductionLine,
  collectApprovals,
  collectFailedGenerations,
  collectOutcomes,
  collectRenderQueue,
  collectSouls,
  collectSpend,
  collectState,
} from "../lib/data.js";

function tempDir() {
  return mkdtempSync(path.join(tmpdir(), "cc-"));
}

function outcomesDb() {
  var dbPath = path.join(tempDir(), "manifest.sqlite");
  var db = new DatabaseSync(dbPath);
  db.exec(
    "CREATE TABLE reel_outcomes (filename TEXT, platform TEXT, account TEXT, soul_id TEXT, posted_at TEXT, views INT, likes INT, comments INT, shares INT, saves INT)",
  );
  db.exec(
    "INSERT INTO reel_outcomes VALUES " +
      "('r1.mp4','threads','a','d63ea9c7-b2c7-439c-bf0c-edfdf9938a36','2026-07-01',1000,50,5,0,0)," +
      "('r2.mp4','threads','b','5828d958-91dd-4d6d-8909-934503f47644','2026-07-02',200,80,10,0,10)",
  );
  db.close();
  return dbPath;
}

test("collectSpend sums only today's events (UTC prefix)", function () {
  var dbPath = path.join(tempDir(), "campaign_factory.sqlite");
  var db = new DatabaseSync(dbPath);
  db.exec(
    "CREATE TABLE ai_cost_events (id TEXT PRIMARY KEY, provider TEXT, operation TEXT, estimated_cost_usd REAL, created_at TEXT)",
  );
  var insert = db.prepare(
    "INSERT INTO ai_cost_events (id, provider, operation, estimated_cost_usd, created_at) VALUES (?, ?, ?, ?, ?)",
  );
  insert.run("a", "higgsfield", "kling3_0", 1.5, "2026-07-02T01:00:00Z");
  insert.run("b", "higgsfield", "soul_v2", 0.5, "2026-07-02T09:30:00Z");
  insert.run("c", "higgsfield", "kling3_0", 9.0, "2026-07-01T23:59:00Z");
  db.close();
  var spend = collectSpend({ dbPath, now: new Date("2026-07-02T12:00:00Z") });
  assert.equal(spend.todayUsd, 2);
  assert.equal(spend.todayEvents, 2);
});

test("collectRenderQueue groups by status; missing db tolerated", function () {
  var dbPath = path.join(tempDir(), "render_queue.sqlite");
  var db = new DatabaseSync(dbPath);
  db.exec("CREATE TABLE queue_jobs (id INTEGER PRIMARY KEY, status TEXT)");
  db.exec("INSERT INTO queue_jobs (status) VALUES ('queued'), ('running')");
  db.close();
  assert.deepEqual(collectRenderQueue(dbPath).counts, { queued: 1, running: 1 });
  assert.equal(collectRenderQueue(path.join(tempDir(), "nope.sqlite")).available, false);
});

test("collectFailedGenerations reads jsonl tail newest-first", function () {
  var jsonlPath = path.join(tempDir(), "failed_generations.jsonl");
  writeFileSync(jsonlPath, ['{"reason":"r1"}', '{"reason":"r2"}'].join("\n") + "\n");
  var failed = collectFailedGenerations(jsonlPath, 5);
  assert.equal(failed.count, 2);
  assert.equal(failed.recent[0].reason, "r2");
});

test("collectApprovals derives pending from media minus decisions", async function () {
  var runsDir = tempDir();
  var finalDir = path.join(runsDir, "run1", "final");
  mkdirSync(finalDir, { recursive: true });
  for (var name of ["a.mp4", "b.mp4", "c.mp4"]) writeFileSync(path.join(finalDir, name), "x");
  writeFileSync(
    path.join(finalDir, "review_decisions.json"),
    JSON.stringify({ decisions: { "a.mp4": { decision: "approved" } } }),
  );
  var approvals = await collectApprovals(runsDir);
  assert.equal(approvals.pending, 2);
  assert.equal(approvals.approved, 1);
  assert.equal(approvals.scanned, 1);
  assert.equal(approvals.skipped, 0);
});

test("collectApprovals scans only the newest 100 run directories", async function () {
  var runsDir = tempDir();
  for (var i = 0; i < 105; i++) {
    var runId = "run-" + String(i).padStart(3, "0");
    var finalDir = path.join(runsDir, runId, "final");
    mkdirSync(finalDir, { recursive: true });
    if (i === 0 || i === 104) writeFileSync(path.join(finalDir, "clip.mp4"), "x");
    var when = new Date("2026-07-02T00:00:00Z").getTime() / 1000 + i;
    utimesSync(path.join(runsDir, runId), when, when);
  }

  var approvals = await collectApprovals(runsDir);
  assert.equal(approvals.scanned, 100);
  assert.equal(approvals.skipped, 5);
  assert.equal(approvals.pending, 1);
  assert.deepEqual(
    approvals.runs.map(function (run) {
      return run.runId;
    }),
    ["run-104"],
  );
});

test("collectOutcomes + collectSouls aggregate and name souls", function () {
  var dbPath = outcomesDb();
  var outcomes = collectOutcomes(dbPath, 5);
  assert.equal(outcomes.count, 2);
  assert.equal(outcomes.totals.views, 1200);
  var souls = collectSouls(dbPath);
  var stacey = souls.find(function (soul) {
    return soul.name === "Stacey";
  });
  var stacey1 = souls.find(function (soul) {
    return soul.name === "Stacey1";
  });
  assert.equal(stacey.views, 1000);
  assert.equal(stacey1.posts, 1);
  assert.ok(stacey1.engagementRate > stacey.engagementRate);
});

test("buildProductionLine tones + buildEventLog ordering", function () {
  var line = buildProductionLine({
    reelGui: { in_flight_generations: 2, needs_review: 3, ready_to_post: 1, failed_generations: 0 },
    renderQueue: { counts: { queued: 1, running: 1 } },
    approvals: { pending: 4 },
    outcomes: { count: 0, slots: { planned: 2 } },
  });
  assert.equal(line.find((s) => s.key === "generate").tone, "live");
  assert.equal(line.find((s) => s.key === "approve").value, 4);
  assert.equal(line.find((s) => s.key === "schedule").value, 2);

  var events = buildEventLog({
    spend: { recent: [{ provider: "hf", operation: "kling", estimated_cost_usd: 1, created_at: "2026-07-02T01:00:00Z" }] },
    failedGenerations: { recent: [{ reason: "qc", timestamp: "2026-07-02T03:00:00Z" }] },
    outcomes: { recent: [{ account: "a", filename: "r.mp4", views: 10, posted_at: "2026-07-01T00:00:00Z" }] },
  });
  assert.equal(events[0].kind, "failure");
  assert.equal(events[2].kind, "post");
});

test("collectState marks thrown collectors unavailable without failing the route", async function () {
  var state = await collectState({
    collectors: {
      collectApprovals: async function () {
        return { pending: 7, approved: 1, rejected: 0, scanned: 1, skipped: 0, runs: [] };
      },
      collectReelGui: async function () {
        return null;
      },
      collectRenderQueue: function () {
        throw new Error("queue broken");
      },
      collectFailedGenerations: function () {
        return { count: 0, recent: [] };
      },
      collectSpend: function () {
        return { available: true, todayUsd: 0, todayEvents: 0, budgetUsd: null, recent: [] };
      },
      collectOutcomes: function () {
        return { available: true, count: 0, totals: {}, recent: [], slots: {} };
      },
      collectSouls: function () {
        throw new Error("soul db broken");
      },
    },
  });

  assert.equal(state.approvals.pending, 7);
  assert.equal(state.renderQueue.available, false);
  assert.equal(state.renderQueue.error, "queue broken");
  assert.equal(state.souls.available, false);
  assert.equal(state.souls.error, "soul db broken");
});
