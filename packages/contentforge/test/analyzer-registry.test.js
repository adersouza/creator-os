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
  assert.equal(first.analyzers.length, 5);
  assert.equal(registration.analyzerId, "contentforge.motion_specific_qc");
  assert.equal(registration.analyzerVersion, "1.0.0");
  assert.deepEqual(registration.evidenceKinds, ["motion_specific_qc_receipt"]);
  assert.equal(registration.implementationFingerprint, actual);
  assert.ok(first.provenance.sourceReferences.some(function (item) {
    return item.recordId === "contentforge.motion_specific_qc@1.0.0" && item.fingerprint === actual;
  }));
  var trusted = first.analyzers.filter(function (item) {
    return item.analyzerId !== "contentforge.motion_specific_qc";
  });
  assert.deepEqual(trusted.map(function (item) { return item.analyzerId; }), [
    "contentforge.audio_integrity",
    "contentforge.media_integrity",
    "contentforge.overlay_delivery",
    "contentforge.temporal_motion",
  ]);
  assert.ok(trusted.every(function (item) {
    return item.implementationRef === "packages/contentforge/lib/trusted-media-analysis.js";
  }));
});

test("requires an explicit snapshot timestamp", async function () {
  await assert.rejects(
    snapshotMotionSpecificQcAnalyzerRegistry({ repositoryRoot: ROOT }),
    /requires an explicit producedAt/,
  );
});
