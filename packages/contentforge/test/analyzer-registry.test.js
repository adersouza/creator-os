import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { snapshotMotionSpecificQcAnalyzerRegistry } from "../lib/analyzer-registry.js";

const PRODUCED_AT = "2026-07-22T12:00:00Z";
const ROOT = path.resolve(import.meta.dirname, "../../..");

test("snapshots the exact deterministic motion-QC implementation", async function () {
  var first = await snapshotMotionSpecificQcAnalyzerRegistry({
    producedAt: PRODUCED_AT,
    repositoryRoot: ROOT,
  });
  var second = await snapshotMotionSpecificQcAnalyzerRegistry({
    producedAt: PRODUCED_AT,
    repositoryRoot: ROOT,
  });
  var registration = first.analyzers.find(function (item) {
    return item.analyzerId === "contentforge.motion_specific_qc";
  });
  var implementation = path.join(ROOT, registration.implementationRef);
  var actual = createHash("sha256").update(await readFile(implementation)).digest("hex");

  assert.deepEqual(first, second);
  assert.equal(first.schema, "creator_os.analyzer_registry.v1");
  assert.equal(first.analyzers.length, 8);
  assert.equal(registration.analyzerId, "contentforge.motion_specific_qc");
  assert.equal(registration.analyzerVersion, "2.0.0");
  assert.deepEqual(registration.evidenceKinds, ["motion_specific_qc_receipt"]);
  assert.equal(registration.implementationFingerprint, actual);
  assert.ok(first.provenance.sourceReferences.some(function (item) {
    return item.recordId === "contentforge.motion_specific_qc@2.0.0" && item.fingerprint === actual;
  }));
  var humanReview = first.analyzers.find(function (item) {
    return item.analyzerId === "reel_factory.structured_human_media_review";
  });
  assert.equal(humanReview.analyzerVersion, "1.0.0");
  assert.deepEqual(humanReview.evidenceKinds, ["human_media_review"]);
  assert.equal(
    humanReview.implementationRef,
    "python_packages/reel_factory/reel_factory/human_media_review.py",
  );
  assert.match(humanReview.implementationFingerprint, /^[a-f0-9]{64}$/);
  var trusted = first.analyzers.filter(function (item) {
    return item.analyzerId.startsWith("contentforge.")
      && item.analyzerId !== "contentforge.motion_specific_qc";
  });
  assert.deepEqual(trusted.map(function (item) { return item.analyzerId; }), [
    "contentforge.audio_integrity",
    "contentforge.local_face_mouth_track",
    "contentforge.local_lip_sync",
    "contentforge.media_integrity",
    "contentforge.overlay_delivery",
    "contentforge.temporal_motion",
  ]);
  var lipSync = trusted.find(function (item) {
    return item.analyzerId === "contentforge.local_lip_sync";
  });
  assert.equal(
    lipSync.implementationRef,
    "packages/contentforge/lib/trusted-media-analysis.js",
  );
  var overlay = trusted.find(function (item) {
    return item.analyzerId === "contentforge.overlay_delivery";
  });
  assert.equal(
    overlay.implementationRef,
    "packages/contentforge/lib/similarity.js",
  );
  assert.equal(
    overlay.implementationFingerprint,
    createHash("sha256").update(await readFile(path.join(ROOT, overlay.implementationRef))).digest("hex"),
  );
  var faceTrack = first.analyzers.find(function (item) {
    return item.analyzerId === "contentforge.local_face_mouth_track";
  });
  assert.equal(
    faceTrack.implementationRef,
    "packages/contentforge/scripts/local-lip-sync-analyzer.py",
  );
  assert.match(faceTrack.implementationFingerprint, /^[a-f0-9]{64}$/);
  assert.ok(trusted.filter(function (item) {
    return !["contentforge.local_face_mouth_track", "contentforge.overlay_delivery"].includes(item.analyzerId);
  }).every(function (item) {
    return item.implementationRef === "packages/contentforge/lib/trusted-media-analysis.js";
  }));
});

test("requires an explicit snapshot timestamp", async function () {
  await assert.rejects(
    snapshotMotionSpecificQcAnalyzerRegistry({ repositoryRoot: ROOT }),
    /requires an explicit producedAt/,
  );
});
