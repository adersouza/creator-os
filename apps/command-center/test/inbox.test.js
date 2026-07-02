import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import {
  collectInbox,
  collectInboxHistory,
  getInboxAsset,
  validateDecision,
} from "../lib/inbox.js";

function tempDir() {
  return mkdtempSync(path.join(tmpdir(), "cc-inbox-"));
}

function stateDb(rows) {
  var dir = tempDir();
  var dbPath = path.join(dir, "manifest.sqlite");
  var db = new DatabaseSync(dbPath);
  db.exec(
    "CREATE TABLE asset_pipeline_state (asset_id TEXT PRIMARY KEY, campaign TEXT," +
      " run_id TEXT, state TEXT, state_updated_at INT, attempts INT DEFAULT 0," +
      " last_error TEXT, lineage_path TEXT, output_path TEXT, rank_score REAL," +
      " predicted_engagement_json TEXT, approval_decision TEXT, approval_reason TEXT," +
      " approved_at INT, created_at INT)",
  );
  var insert = db.prepare(
    "INSERT INTO asset_pipeline_state (asset_id, campaign, run_id, state," +
      " state_updated_at, attempts, lineage_path, output_path, rank_score," +
      " predicted_engagement_json, approval_decision, approval_reason, approved_at, created_at)" +
      " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
  );
  for (var row of rows) {
    insert.run(
      row.assetId,
      row.campaign || "camp",
      row.runId || "run1",
      row.state,
      row.stateUpdatedAt || 100,
      row.attempts || 0,
      row.lineagePath || null,
      row.outputPath || null,
      row.rankScore == null ? null : row.rankScore,
      row.predictedEngagementJson || null,
      row.decision || null,
      row.reason || null,
      row.approvedAt || null,
      row.createdAt || 100,
    );
  }
  db.close();
  return { dir, dbPath };
}

test("collectInbox returns awaiting_approval sorted by rank, with lineage summary", function () {
  var dir = tempDir();
  var lineagePath = path.join(dir, "asset_a.lineage.json");
  writeFileSync(
    lineagePath,
    JSON.stringify({ caption: "hot take", caption_hash: "abc123", qc: { passed: true } }),
  );
  var mediaPath = path.join(dir, "asset_a.mp4");
  writeFileSync(mediaPath, "x");
  var { dbPath } = stateDb([
    { assetId: "asset_a", state: "awaiting_approval", rankScore: 0.4, lineagePath, outputPath: mediaPath },
    { assetId: "asset_b", state: "awaiting_approval", rankScore: 0.9 },
    { assetId: "asset_c", state: "planned", rankScore: 0.99 },
  ]);

  var inbox = collectInbox(dbPath);

  assert.equal(inbox.available, true);
  assert.deepEqual(
    inbox.items.map(function (item) {
      return item.assetId;
    }),
    ["asset_b", "asset_a"],
  );
  var withLineage = inbox.items[1];
  assert.equal(withLineage.lineage.caption, "hot take");
  assert.equal(withLineage.lineage.captionHash, "abc123");
  assert.equal(withLineage.hasMedia, true);
  assert.equal(inbox.items[0].hasMedia, false);
});

test("collectInbox tolerates missing db", function () {
  assert.equal(collectInbox(path.join(tempDir(), "nope.sqlite")).available, false);
});

test("collectInboxHistory returns decided assets newest-first", function () {
  var { dbPath } = stateDb([
    { assetId: "old", state: "rejected", decision: "rejected", reason: "meh", stateUpdatedAt: 100 },
    { assetId: "new", state: "approved", decision: "approved", approvedAt: 300, stateUpdatedAt: 200 },
    { assetId: "undecided", state: "awaiting_approval" },
  ]);

  var history = collectInboxHistory(dbPath);

  assert.deepEqual(
    history.items.map(function (item) {
      return item.assetId;
    }),
    ["new", "old"],
  );
  assert.equal(history.items[1].reason, "meh");
});

test("getInboxAsset rejects hostile ids and unknown assets", function () {
  var { dbPath } = stateDb([{ assetId: "asset_a", state: "awaiting_approval" }]);
  assert.equal(getInboxAsset("../../etc/passwd", dbPath), null);
  assert.equal(getInboxAsset("missing", dbPath), null);
  assert.equal(getInboxAsset("asset_a", dbPath).assetId, "asset_a");
});

test("validateDecision gates decision + asset id", function () {
  assert.equal(validateDecision({ assetId: "a1", decision: "approved" }), null);
  assert.equal(validateDecision({ assetId: "a1", decision: "exported" }), "invalid_decision");
  assert.equal(validateDecision({ assetId: "a/../b", decision: "approved" }), "invalid_asset_id");
});
