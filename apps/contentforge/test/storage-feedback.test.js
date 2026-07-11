import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, rm, utimes, writeFile } from "node:fs/promises";
import path from "node:path";
import { inspectLocalMediaCleanup } from "../lib/local-media-cleanup.js";
import { UPLOADS_DIR } from "../lib/paths.js";

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
