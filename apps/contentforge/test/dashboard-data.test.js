import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import {
  collectApprovals,
  collectFailedGenerations,
  collectOutcomes,
  collectRenderQueue,
  collectSpend,
} from "../lib/dashboard-data.js";

function tempDir() {
  return mkdtempSync(path.join(tmpdir(), "cf-dash-"));
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
  assert.equal(spend.available, true);
  assert.equal(spend.todayUsd, 2);
  assert.equal(spend.todayEvents, 2);
  assert.equal(spend.recent.length, 3);
});

test("collectSpend handles missing db", function () {
  var spend = collectSpend({ dbPath: path.join(tempDir(), "nope.sqlite") });
  assert.equal(spend.available, false);
  assert.equal(spend.todayUsd, 0);
});

test("collectRenderQueue groups by status", function () {
  var dbPath = path.join(tempDir(), "render_queue.sqlite");
  var db = new DatabaseSync(dbPath);
  db.exec("CREATE TABLE queue_jobs (id INTEGER PRIMARY KEY, status TEXT)");
  db.exec(
    "INSERT INTO queue_jobs (status) VALUES ('queued'), ('queued'), ('running'), ('failed')",
  );
  db.close();
  var queue = collectRenderQueue(dbPath);
  assert.deepEqual(queue, { available: true, counts: { queued: 2, running: 1, failed: 1 } });
});

test("collectFailedGenerations reads jsonl tail, newest first", function () {
  var jsonlPath = path.join(tempDir(), "failed_generations.jsonl");
  var lines = [];
  for (var i = 1; i <= 7; i++) lines.push(JSON.stringify({ reason: "r" + i }));
  writeFileSync(jsonlPath, lines.join("\n") + "\n");
  var failed = collectFailedGenerations(jsonlPath, 3);
  assert.equal(failed.count, 7);
  assert.deepEqual(
    failed.recent.map(function (r) {
      return r.reason;
    }),
    ["r7", "r6", "r5"],
  );
});

test("collectApprovals derives pending from media minus decisions", async function () {
  var runsDir = tempDir();
  var finalDir = path.join(runsDir, "run1", "final");
  mkdirSync(finalDir, { recursive: true });
  for (var name of ["a.mp4", "b.mp4", "c.mp4", "notes.json"]) {
    writeFileSync(path.join(finalDir, name), "x");
  }
  writeFileSync(
    path.join(finalDir, "review_decisions.json"),
    JSON.stringify({
      decisions: {
        "a.mp4": { decision: "approved" },
        "b.mp4": { decision: "rejected" },
      },
    }),
  );
  var approvals = await collectApprovals(runsDir);
  assert.equal(approvals.pending, 1);
  assert.equal(approvals.approved, 1);
  assert.equal(approvals.rejected, 1);
  assert.equal(approvals.runs[0].runId, "run1");
  assert.equal(approvals.runs[0].media, 3);
});

test("collectOutcomes totals + slots; missing tables tolerated", function () {
  var dbPath = path.join(tempDir(), "manifest.sqlite");
  var db = new DatabaseSync(dbPath);
  db.exec(
    "CREATE TABLE reel_outcomes (filename TEXT, platform TEXT, account TEXT, posted_at TEXT, views INT, likes INT, comments INT, shares INT, saves INT)",
  );
  db.exec(
    "INSERT INTO reel_outcomes VALUES ('r1.mp4','threads','stacey','2026-07-01',1000,50,5,2,3), ('r2.mp4','threads','stacey1','2026-07-02',200,80,9,1,4)",
  );
  db.close();
  var outcomes = collectOutcomes(dbPath, 5);
  assert.equal(outcomes.available, true);
  assert.equal(outcomes.count, 2);
  assert.equal(outcomes.totals.views, 1200);
  assert.equal(outcomes.recent[0].filename, "r2.mp4");
  assert.deepEqual(outcomes.slots, {});
});
