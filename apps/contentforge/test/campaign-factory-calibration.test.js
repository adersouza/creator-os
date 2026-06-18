import test from "node:test";
import assert from "node:assert/strict";
import { copyFile, mkdir, readFile, rm } from "fs/promises";
import path from "path";
import { POST } from "../app/api/similarity/route.js";
import { generateCampaignFactoryFixtures } from "../scripts/generate-campaign-fixtures.mjs";
import { LEGACY_FINAL_DIR, UPLOADS_DIR } from "../lib/paths.js";
import { skipWhenMissingTools } from "./tool-availability.js";

const FIXTURE_ROOT = path.resolve("test/fixtures/campaign-factory");
const MANIFEST_PATH = path.join(FIXTURE_ROOT, "manifests", "expected_verdicts.json");
const SOURCE_NAME = "cf_calibration_source.mp4";

if (!process.env.CONTENTFORGE_OCR_ENGINE) {
  process.env.CONTENTFORGE_OCR_ENGINE = "tesseract";
}

var MEDIA_TOOLS = ["ffmpeg", "ffprobe", "tesseract"];

function similarityRequest(body) {
  return new Request("http://localhost/api/similarity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function loadManifest() {
  return JSON.parse(await readFile(MANIFEST_PATH, "utf8"));
}

async function stageFixture(fixtureFile) {
  await mkdir(UPLOADS_DIR, { recursive: true });
  await mkdir(LEGACY_FINAL_DIR, { recursive: true });
  var sourcePath = path.join(UPLOADS_DIR, SOURCE_NAME);
  var targetName = "cf_calibration_" + path.basename(fixtureFile);
  var targetPath = path.join(LEGACY_FINAL_DIR, targetName);
  await rm(sourcePath, { force: true });
  await rm(targetPath, { force: true });
  await copyFile(path.join(FIXTURE_ROOT, "good", "campaign_factory_avconvert_render.mp4"), sourcePath);
  await copyFile(path.join(FIXTURE_ROOT, fixtureFile), targetPath);
  return { sourcePath, targetPath, sourceName: SOURCE_NAME, targetName };
}

async function cleanupStaged(staged) {
  if (!staged) return;
  await rm(staged.sourcePath, { force: true });
  await rm(staged.targetPath, { force: true });
}

function assertContract(body) {
  assert.equal(body.contractVersion, "campaign_factory_audit.v1.4");
  assert.equal(body.auditProfile, "campaign_factory_v1");
  assert.equal(typeof body.targetFile, "string");
  assert.equal(typeof body.readinessSummary.summaryText, "string");
  assert.equal(typeof body.readinessSummary.uploadReady, "boolean");
  assert.equal(Array.isArray(body.readinessSummary.blockingReasons), true);
  assert.equal(Array.isArray(body.readinessSummary.warnings), true);
  assert.equal(Array.isArray(body.readinessSummary.topWarnings), true);
  assert.equal(Array.isArray(body.readinessSummary.warningCodes), true);
  assert.equal(Array.isArray(body.readinessSummary.blockingCodes), true);
  assert.equal(typeof body.readinessSummary.operatorLabels, "object");
  assert.equal(Array.isArray(body.readinessSummary.operatorLabels.blocking), true);
  assert.equal(Array.isArray(body.readinessSummary.operatorLabels.needsReview), true);
  assert.equal(Array.isArray(body.readinessSummary.operatorLabels.advisory), true);
  assert.equal(Array.isArray(body.readinessSummary.operatorLabels.informational), true);
  assert.equal(["approve_candidate", "review", "reject"].includes(body.readinessSummary.recommendedAction), true);
  assert.equal(typeof body.verdictCodes, "object");
  assert.equal(typeof body.ocr, "object");
  assert.equal(Array.isArray(body.captionBoxes), true);
  assert.equal(typeof body.safeZoneScore, "number");
  assert.equal(typeof body.readabilityScore, "number");
  assert.equal(typeof body.hookVisibilityScore, "number");
  assert.equal(typeof body.safeZone, "object");
  assert.equal(typeof body.readability, "object");
  assert.equal(Array.isArray(body.coverCandidates), true);
  assert.equal(typeof body.hookVisibility, "object");
  assert.equal(typeof body.timings, "object");
  assert.equal(typeof body.timings.totalMs, "number");
  assert.equal(typeof body.timings.layersMs, "object");
}

function assertCodes(actual, expectedCodes, label) {
  for (var code of expectedCodes || []) {
    assert.equal(actual.includes(code), true, label + " missing " + code);
  }
}

function assertCodesAbsent(actual, expectedCodes, label) {
  for (var code of expectedCodes || []) {
    assert.equal(actual.includes(code), false, label + " unexpectedly included " + code);
  }
}

test("Campaign Factory fixture manifest calibrates /api/similarity response contract", async function (t) {
  if (skipWhenMissingTools(t, MEDIA_TOOLS)) return;
  await generateCampaignFactoryFixtures();
  var manifest = await loadManifest();
  assert.equal(manifest.schema, "contentforge.campaign_factory_calibration.v1");

  for (var fixture of manifest.fixtures) {
    var staged = await stageFixture(fixture.file);
    try {
      var response = await POST(similarityRequest({
        source: staged.sourceName,
        targetFile: staged.targetName,
        auditProfile: "campaign_factory_v1",
        layers: ["forensics"],
      }));
      var body = await response.json();
      var expected = fixture.expected || {};
      assert.equal(response.status, 200, fixture.file + " returned non-200: " + JSON.stringify(body));
      assertContract(body);
      assert.equal(body.targetFile, staged.targetName);
      assert.equal(body.filesAnalyzed, 1);
      assert.equal(body.overallVerdict, expected.overallVerdict, fixture.file + " overallVerdict");
      assert.equal(body.readinessSummary.uploadReady, expected.uploadReady, fixture.file + " uploadReady");
      assertCodes(body.readinessSummary.warningCodes, expected.mustIncludeWarningCodes, fixture.file + " warningCodes");
      assertCodes(body.readinessSummary.blockingCodes, expected.mustIncludeBlockingCodes, fixture.file + " blockingCodes");
      assertCodesAbsent(body.readinessSummary.blockingCodes, expected.mustNotIncludeBlockingCodes, fixture.file + " blockingCodes");

      for (var code of (expected.mustIncludeWarningCodes || []).filter((item) => /^(caption|hook|cover)_/.test(item))) {
        assert.equal(
          body.readinessSummary.topWarnings.some((warning) => warning.code === code),
          true,
          fixture.file + " topWarnings missing " + code
        );
      }
    } finally {
      await cleanupStaged(staged);
    }
  }
});
