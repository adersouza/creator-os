import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import {
  OUTPUT_DIR,
  UPLOADS_DIR,
  ensureInside,
  isValidRunId,
  resolveAllowedReferenceTarget,
  resolveRunFile,
  resolveUploadPath,
} from "../lib/paths.js";

test("output directory is absolute", function () {
  assert.equal(path.isAbsolute(OUTPUT_DIR), true);
});

test("resolveUploadPath keeps uploads inside the uploads directory", function () {
  assert.equal(resolveUploadPath("../secret.mp4"), path.join(UPLOADS_DIR, "secret.mp4"));
  assert.equal(resolveUploadPath("uploads/video.mp4"), path.join(UPLOADS_DIR, "video.mp4"));
});

test("ensureInside rejects paths outside the allowed root", function () {
  assert.equal(ensureInside(UPLOADS_DIR, path.join(UPLOADS_DIR, "ok.mp4")), path.join(UPLOADS_DIR, "ok.mp4"));
  assert.equal(ensureInside(UPLOADS_DIR, path.join(UPLOADS_DIR, "..", "outside.mp4")), null);
});

test("run-scoped output requires a valid run id and safe filename", function () {
  assert.equal(isValidRunId("deadbeef"), true);
  assert.equal(isValidRunId("../bad"), false);
  assert.equal(resolveRunFile("../bad", "clip.mp4"), null);
  assert.equal(resolveRunFile("deadbeef", "../clip.mp4"), path.join(OUTPUT_DIR, "runs", "deadbeef", "final", "clip.mp4"));
});

test("reference targets are limited to project uploads and output directories", function () {
  assert.equal(resolveAllowedReferenceTarget(path.join(OUTPUT_DIR, "reference"))?.startsWith(OUTPUT_DIR), true);
  assert.equal(resolveAllowedReferenceTarget("/tmp"), null);
});
