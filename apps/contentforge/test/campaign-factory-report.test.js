import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "child_process";
import { mkdtemp, readFile, writeFile } from "fs/promises";
import { tmpdir } from "os";
import path from "path";

function runReport(env) {
  return new Promise(function (resolve, reject) {
    execFile(process.execPath, ["scripts/campaign-audit-report.mjs", "--json"], {
      cwd: process.cwd(),
      env,
      timeout: 180000,
      maxBuffer: 20 * 1024 * 1024,
    }, function (error, stdout, stderr) {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve(JSON.parse(stdout));
    });
  });
}

function runNode(args, env) {
  return new Promise(function (resolve, reject) {
    execFile(process.execPath, args, {
      cwd: process.cwd(),
      env,
      timeout: 180000,
      maxBuffer: 20 * 1024 * 1024,
    }, function (error, stdout, stderr) {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve(stdout);
    });
  });
}

test("Campaign Factory calibration report includes metrics and skips missing real media", async function () {
  var dir = await mkdtemp(path.join(tmpdir(), "contentforge-real-manifest-"));
  var manifestPath = path.join(dir, "real_samples.json");
  await writeFile(manifestPath, JSON.stringify({
    schema: "contentforge.campaign_factory_real_samples.v1",
    samples: [
      {
        file: "missing_real_sample.mp4",
        sourceType: "iphone",
        expectedUploadReady: true,
        expectedWarningCodes: [],
        expectedBlockingCodes: [],
        operatorNotes: "Fixture intentionally absent for report skip coverage",
        acceptedByPlatform: "unknown"
      }
    ]
  }, null, 2));

  var report = await runReport({
    ...process.env,
    CONTENTFORGE_OCR_ENGINE: "tesseract",
    CONTENTFORGE_REAL_SAMPLE_MANIFEST: manifestPath,
  });

  assert.equal(report.schema, "contentforge.campaign_factory_calibration_report.v1");
  assert.equal(report.thresholdSchema, "contentforge.campaign_factory_thresholds.v1");
  assert.equal(report.summary.audited > 0, true);
  assert.equal(report.summary.skipped >= 1, true);
  assert.equal(report.summary.mismatches, 0);
  assert.equal(Array.isArray(report.slowestSamples), true);
  assert.equal(typeof report.warningCodeFrequency, "object");
  assert.equal(typeof report.blockingCodeFrequency, "object");
  assert.equal(typeof report.history, "object");
});

test("Campaign Factory calibration report can record ignored drift history", async function () {
  var dir = await mkdtemp(path.join(tmpdir(), "contentforge-history-"));
  var env = {
    ...process.env,
    CONTENTFORGE_OCR_ENGINE: "tesseract",
    CONTENTFORGE_AUDIT_HISTORY_DIR: dir,
  };

  await new Promise(function (resolve, reject) {
    execFile(process.execPath, ["scripts/campaign-audit-report.mjs", "--json", "--write-history"], {
      cwd: process.cwd(),
      env,
      timeout: 180000,
      maxBuffer: 20 * 1024 * 1024,
    }, function (error, stdout, stderr) {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      var report = JSON.parse(stdout);
      assert.equal(typeof report.historyPath, "string");
      resolve();
    });
  });

  var latest = JSON.parse(await readFile(path.join(dir, "latest.json"), "utf8"));
  assert.equal(latest.schema, "contentforge.campaign_factory_audit_history.v1");
  assert.equal(typeof latest.summary.audited, "number");
});

test("Campaign Factory report can render HTML", async function () {
  var html = await runNode(["scripts/campaign-audit-report.mjs", "--html", "--no-generate"], {
    ...process.env,
    CONTENTFORGE_OCR_ENGINE: "tesseract",
  });
  assert.match(html, /<!doctype html>/i);
  assert.match(html, /Campaign Factory Audit Calibration/);
  assert.match(html, /<table>/);
});

test("Campaign Factory corpus discovery summarizes local videos", async function () {
  var output = await runNode(["scripts/campaign-corpus-discover.mjs", "--dir=test/fixtures/campaign-factory/good", "--maxDepth=0", "--limit=2"], process.env);
  var body = JSON.parse(output);
  assert.equal(body.schema, "contentforge.campaign_factory_corpus_discovery.v1");
  assert.equal(body.count > 0, true);
  assert.equal(typeof body.candidates[0].suggested.expectedUploadReady, "boolean");
});

test("Campaign Factory sample feedback updates a temporary manifest", async function () {
  var dir = await mkdtemp(path.join(tmpdir(), "contentforge-feedback-"));
  var manifestPath = path.join(dir, "real_samples.json");
  await writeFile(manifestPath, JSON.stringify({
    schema: "contentforge.campaign_factory_real_samples.v1",
    samples: [
      {
        file: "real_sample_99.mp4",
        sourceType: "unknown",
        expectedUploadReady: true,
        expectedWarningCodes: [],
        expectedBlockingCodes: [],
        operatorNotes: "",
        acceptedByPlatform: "unknown"
      }
    ]
  }, null, 2));

  var output = await runNode([
    "scripts/campaign-sample-feedback.mjs",
    "--file=real_sample_99.mp4",
    "--acceptedByPlatform=yes",
    "--expectedWarningCodes=caption_low_contrast",
    "--falsePositiveCodes=caption_too_close_to_edge",
  ], {
    ...process.env,
    CONTENTFORGE_REAL_SAMPLE_MANIFEST: manifestPath,
  });
  var sample = JSON.parse(output);
  assert.equal(sample.acceptedByPlatform, "yes");
  assert.equal(sample.expectedWarningCodes.includes("caption_low_contrast"), true);
  assert.equal(sample.operatorFeedback.falsePositiveCodes.includes("caption_too_close_to_edge"), true);
});
