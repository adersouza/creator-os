import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, rm, utimes, writeFile } from "node:fs/promises";
import path from "node:path";
import { POST as feedbackPost } from "../app/api/audit-feedback/route.js";
import { inspectLocalMediaCleanup } from "../lib/local-media-cleanup.js";
import { UPLOADS_DIR } from "../lib/paths.js";

function jsonRequest(body) {
  return new Request("http://localhost/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

test("audit feedback API records operator labels", async function () {
  var response = await feedbackPost(jsonRequest({
    code: "creative_hook_generic",
    label: "useful",
    message: "Hook may be generic",
    note: "Good call",
    targetFile: "candidate.mp4",
    runId: "deadbeef",
    auditProfile: "campaign_factory_v1",
  }));
  var body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.ok, true);
  assert.equal(body.record.code, "creative_hook_generic");
  assert.equal(body.record.label, "useful");
});

test("local media cleanup dry-run reports old ignored uploads", async function () {
  await mkdir(UPLOADS_DIR, { recursive: true });
  var file = path.join(UPLOADS_DIR, "cleanup_test_" + Date.now() + ".tmp");
  await writeFile(file, "old");
  var oldDate = new Date(Date.now() - 40 * 24 * 60 * 60 * 1000);
  await utimes(file, oldDate, oldDate);
  try {
    var report = await inspectLocalMediaCleanup({ olderThanDays: 30 });
    assert.equal(report.schema, "contentforge.local_media_cleanup.v1");
    assert.equal(report.candidates.some((item) => item.file.endsWith(path.basename(file))), true);
  } finally {
    await rm(file, { force: true });
  }
});
