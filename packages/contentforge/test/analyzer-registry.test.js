import test from "node:test";
import assert from "node:assert/strict";
import {
  cp,
  mkdtemp,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { snapshotTrustedMediaAnalyzerRegistry } from "../lib/analyzer-registry.js";
import { verifyAnalyzerValidationManifest } from "../lib/analyzer-validation-manifest.js";

const PRODUCED_AT = "2026-07-31T08:00:00Z";
const ROOT = path.resolve(import.meta.dirname, "../../..");

test("loads production authority after executable qualification passes", async function () {
  var registry = await snapshotTrustedMediaAnalyzerRegistry({
    producedAt: PRODUCED_AT,
    repositoryRoot: ROOT,
  });

  assert.equal(registry.schema, "creator_os.analyzer_registry.v2");
  assert.equal(registry.analyzers.length, 9);
  assert.ok(registry.analyzers.every(function (item) {
    return item.validationDataset.datasetId === "contentforge.production_authority.v2"
      && item.authorityReview.decision === "approved";
  }));
});

test("requires an explicit snapshot timestamp", async function () {
  await assert.rejects(
    snapshotTrustedMediaAnalyzerRegistry({ repositoryRoot: ROOT }),
    /requires an explicit producedAt/,
  );
});

test("keeps v1 snapshots available only for historical verification", async function () {
  var historical = await snapshotTrustedMediaAnalyzerRegistry({
    producedAt: PRODUCED_AT,
    repositoryRoot: ROOT,
    authorityVersion: 1,
  });

  assert.equal(historical.schema, "creator_os.analyzer_registry.v1");
  assert.equal(historical.analyzers.length, 9);
  assert.ok(historical.analyzers.every(function (item) {
    return !Object.hasOwn(item, "authorityReview");
  }));
});

test("fails closed when production authority has expired", async function () {
  await assert.rejects(
    snapshotTrustedMediaAnalyzerRegistry({
      producedAt: "2027-02-01T00:00:00Z",
      repositoryRoot: ROOT,
    }),
    /production authority expired/,
  );
});

test("rejects replayed production authority after its renewal time", async function () {
  var originalNow = Date.now;
  Date.now = function () { return Date.parse("2027-02-01T00:00:00Z"); };
  try {
    await assert.rejects(
      snapshotTrustedMediaAnalyzerRegistry({
        producedAt: PRODUCED_AT,
        repositoryRoot: ROOT,
      }),
      /production authority expired/,
    );
  } finally {
    Date.now = originalNow;
  }
});

test("binds analyzer authority to validation fixture bytes", async function () {
  var temporary = await mkdtemp(path.join(os.tmpdir(), "contentforge-analyzer-"));
  try {
    await cp(path.join(ROOT, "packages/contentforge/analyzer-validation"), path.join(
      temporary,
      "packages/contentforge/analyzer-validation",
    ), { recursive: true });
    await cp(path.join(ROOT, "packages/contentforge/test/fixtures"), path.join(
      temporary,
      "packages/contentforge/test/fixtures",
    ), { recursive: true });
    var manifestRef = "packages/contentforge/analyzer-validation/production-authority-v2.json";
    await verifyAnalyzerValidationManifest(temporary, manifestRef);
    await writeFile(
      path.join(
        temporary,
        "packages/contentforge/test/fixtures/detector-calibration/media_pairs.json",
      ),
      "{}",
    );
    await assert.rejects(
      verifyAnalyzerValidationManifest(temporary, manifestRef),
      /fixture drift/,
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
