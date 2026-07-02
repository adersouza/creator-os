import test from "node:test";
import assert from "node:assert/strict";
import { costLabelFromSpend, showSummarySkeleton } from "../lib/review-summary.js";

test("review summary shows cost from available ledger spend", function () {
  assert.equal(costLabelFromSpend({ available: true, todayUsd: 2.5 }), "$2.50");
});

test("review summary hides cost when ledger spend is absent", function () {
  assert.equal(costLabelFromSpend({ available: false, todayUsd: 0 }), null);
  assert.equal(costLabelFromSpend(null), null);
});

test("review summary skeleton appears while scan output is pending", function () {
  assert.equal(showSummarySkeleton({ scanPending: true, files: [] }), true);
  assert.equal(showSummarySkeleton({ scanPending: true, files: [{ name: "a.mp4" }] }), false);
  assert.equal(showSummarySkeleton({ scanPending: false, files: [] }), false);
});
