import { access, appendFile, copyFile, mkdir, readdir, readFile, rm, writeFile } from "fs/promises";
import path from "path";
import { POST } from "../app/api/similarity/route.js";
import { LEGACY_FINAL_DIR, UPLOADS_DIR } from "../lib/paths.js";
import { CAMPAIGN_FACTORY_AUDIT_CONFIG } from "../lib/campaign-factory-audit-config.js";
import { generateCampaignFactoryFixtures } from "./generate-campaign-fixtures.mjs";

const ROOT = path.resolve("test/fixtures/campaign-factory");
const EXPECTED_MANIFEST = path.join(ROOT, "manifests", "expected_verdicts.json");
const REAL_MANIFEST = process.env.CONTENTFORGE_REAL_SAMPLE_MANIFEST ||
  path.join(ROOT, "manifests", "real_samples.json");
const HISTORY_DIR = process.env.CONTENTFORGE_AUDIT_HISTORY_DIR ||
  path.resolve("test/fixtures/campaign-factory/reports");
const SOURCE_NAME = "cf_report_source_" + process.pid + ".mp4";

function hasFlag(name) {
  return process.argv.includes(name);
}

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

async function readJson(file, fallback) {
  if (!(await exists(file))) return fallback;
  return JSON.parse(await readFile(file, "utf8"));
}

function similarityRequest(body) {
  return new Request("http://localhost/api/similarity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function stageFixture(fixtureFile, prefix) {
  await mkdir(UPLOADS_DIR, { recursive: true });
  await mkdir(LEGACY_FINAL_DIR, { recursive: true });
  var sourcePath = path.join(UPLOADS_DIR, SOURCE_NAME);
  var targetName = prefix + "_" + process.pid + "_" + path.basename(fixtureFile);
  var targetPath = path.join(LEGACY_FINAL_DIR, targetName);
  await rm(sourcePath, { force: true });
  await rm(targetPath, { force: true });
  await copyFile(path.join(ROOT, "good", "campaign_factory_avconvert_render.mp4"), sourcePath);
  await copyFile(path.join(ROOT, fixtureFile), targetPath);
  return { sourcePath, targetPath, sourceName: SOURCE_NAME, targetName };
}

async function cleanup(staged) {
  if (!staged) return;
  await rm(staged.sourcePath, { force: true });
  await rm(staged.targetPath, { force: true });
}

function expectedFromFixture(fixture) {
  var expected = fixture.expected || {};
  return {
    overallVerdict: expected.overallVerdict,
    uploadReady: expected.uploadReady ?? expected.expectedUploadReady,
    warningCodes: expected.mustIncludeWarningCodes || expected.expectedWarningCodes || [],
    blockingCodes: expected.mustIncludeBlockingCodes || expected.expectedBlockingCodes || [],
    forbiddenBlockingCodes: expected.mustNotIncludeBlockingCodes || [],
  };
}

function compareCodes(actual, expected, fixtureFile) {
  var warnings = actual.readinessSummary?.warningCodes || [];
  var blockers = actual.readinessSummary?.blockingCodes || [];
  var mismatches = [];
  if (expected.overallVerdict && actual.overallVerdict !== expected.overallVerdict) {
    mismatches.push({
      type: "overallVerdict",
      expected: expected.overallVerdict,
      actual: actual.overallVerdict,
    });
  }
  if (typeof expected.uploadReady === "boolean" && actual.readinessSummary?.uploadReady !== expected.uploadReady) {
    mismatches.push({
      type: "uploadReady",
      expected: expected.uploadReady,
      actual: actual.readinessSummary?.uploadReady,
    });
  }
  for (var code of expected.warningCodes || []) {
    if (!warnings.includes(code)) {
      mismatches.push({ type: "missingWarningCode", code });
    }
  }
  for (var code of expected.blockingCodes || []) {
    if (!blockers.includes(code)) {
      mismatches.push({ type: "missingBlockingCode", code });
    }
  }
  for (var code of expected.forbiddenBlockingCodes || []) {
    if (blockers.includes(code)) {
      mismatches.push({ type: "unexpectedBlockingCode", code });
    }
  }
  return mismatches.map(function (mismatch) {
    return { fixture: fixtureFile, ...mismatch };
  });
}

function incrementAll(map, codes) {
  for (var code of codes || []) {
    map[code] = (map[code] || 0) + 1;
  }
}

async function auditFixture(fixture, index, source) {
  var staged = await stageFixture(fixture.file, "cf_report_" + index);
  try {
    var response = await POST(similarityRequest({
      source: staged.sourceName,
      targetFile: staged.targetName,
      auditProfile: "campaign_factory_v1",
      layers: ["forensics"],
    }));
    var body = await response.json();
    return {
      source,
      file: fixture.file,
      skipped: false,
      status: response.status,
      overallVerdict: body.overallVerdict,
      uploadReady: body.readinessSummary?.uploadReady,
      warningCodes: body.readinessSummary?.warningCodes || [],
      blockingCodes: body.readinessSummary?.blockingCodes || [],
      ocr: {
        engine: body.ocr?.engine || null,
        fallbackUsed: Boolean(body.ocr?.fallbackUsed),
        avgConfidence: body.ocr?.avgConfidence ?? null,
      },
      timings: body.timings || {},
      mismatches: compareCodes(body, expectedFromFixture(fixture), fixture.file),
    };
  } finally {
    await cleanup(staged);
  }
}

function normalizeRealFixture(entry) {
  return {
    file: "real/" + entry.file,
    expected: {
      uploadReady: entry.expectedUploadReady,
      mustIncludeWarningCodes: entry.expectedWarningCodes || [],
      mustIncludeBlockingCodes: entry.expectedBlockingCodes || [],
    },
  };
}

function markdownReport(report) {
  var lines = [
    "# Campaign Factory Audit Calibration Report",
    "",
    "- Schema: `" + report.schema + "`",
    "- Thresholds: `" + report.thresholdSchema + "`",
    "- Samples audited: " + report.summary.audited,
    "- Samples skipped: " + report.summary.skipped,
    "- Mismatches: " + report.summary.mismatches,
    "- OCR fallback rate: " + report.summary.ocrFallbackRate,
    "- Slowest sample: " + (report.slowestSamples[0]?.file || "n/a"),
    "- History runs loaded: " + (report.history?.runsLoaded || 0),
    "",
    "## Warning Codes",
    "",
  ];
  for (var [code, count] of Object.entries(report.warningCodeFrequency)) {
    lines.push("- `" + code + "`: " + count);
  }
  lines.push("", "## Blocking Codes", "");
  for (var [code, count] of Object.entries(report.blockingCodeFrequency)) {
    lines.push("- `" + code + "`: " + count);
  }
  if (report.mismatches.length) {
    lines.push("", "## Mismatches", "");
    for (var mismatch of report.mismatches) {
      lines.push("- `" + mismatch.fixture + "`: " + mismatch.type + (mismatch.code ? " `" + mismatch.code + "`" : ""));
    }
  }
  return lines.join("\n");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function htmlReport(report) {
  var rows = report.results.map(function (result) {
    var warnings = (result.warningCodes || []).map((code) => "<code>" + escapeHtml(code) + "</code>").join(" ");
    var blockers = (result.blockingCodes || []).map((code) => "<code>" + escapeHtml(code) + "</code>").join(" ");
    var mismatch = (result.mismatches || []).map((item) => escapeHtml(item.type + (item.code ? ":" + item.code : ""))).join("<br>");
    return "<tr>" +
      "<td>" + escapeHtml(result.file) + "</td>" +
      "<td>" + escapeHtml(result.source) + "</td>" +
      "<td>" + escapeHtml(result.overallVerdict || (result.skipped ? "skipped" : "")) + "</td>" +
      "<td>" + escapeHtml(result.uploadReady) + "</td>" +
      "<td>" + warnings + "</td>" +
      "<td>" + blockers + "</td>" +
      "<td>" + escapeHtml(result.timings?.totalMs || "") + "</td>" +
      "<td>" + escapeHtml(result.ocr?.engine || "") + "</td>" +
      "<td>" + mismatch + "</td>" +
      "</tr>";
  }).join("\n");
  return "<!doctype html><html><head><meta charset=\"utf-8\">" +
    "<title>ContentForge Campaign Factory Audit</title>" +
    "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:24px;color:#111827}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #d1d5db;padding:6px;vertical-align:top}th{background:#f3f4f6;text-align:left}code{background:#eef2ff;padding:1px 3px;border-radius:3px}.fail{color:#b91c1c}.warn{color:#92400e}</style>" +
    "</head><body>" +
    "<h1>Campaign Factory Audit Calibration</h1>" +
    "<p><strong>Generated:</strong> " + escapeHtml(report.generatedAt) + "</p>" +
    "<p><strong>Audited:</strong> " + report.summary.audited +
    " <strong>Skipped:</strong> " + report.summary.skipped +
    " <strong>Mismatches:</strong> " + report.summary.mismatches +
    " <strong>OCR fallback:</strong> " + escapeHtml(report.summary.ocrFallbackRate) + "</p>" +
    "<p><strong>History runs loaded:</strong> " + (report.history?.runsLoaded || 0) +
    " <strong>Mismatch delta:</strong> " + (report.history?.mismatchDelta || 0) + "</p>" +
    "<h2>Samples</h2><table><thead><tr><th>File</th><th>Source</th><th>Verdict</th><th>Upload Ready</th><th>Warnings</th><th>Blockers</th><th>Total ms</th><th>OCR</th><th>Mismatches</th></tr></thead><tbody>" +
    rows +
    "</tbody></table></body></html>";
}

async function loadHistory(limit = 20) {
  if (!(await exists(HISTORY_DIR))) return [];
  var entries = await readdir(HISTORY_DIR);
  var jsonlFiles = entries.filter((entry) => entry.endsWith(".jsonl")).sort();
  var records = [];
  for (var file of jsonlFiles) {
    var text = await readFile(path.join(HISTORY_DIR, file), "utf8");
    for (var line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        records.push(JSON.parse(line));
      } catch {
        // Ignore malformed local history lines; they should not break audit reports.
      }
    }
  }
  return records.slice(-limit);
}

function codeDelta(previous, current) {
  var delta = {};
  var codes = new Set([...Object.keys(previous || {}), ...Object.keys(current || {})]);
  for (var code of codes) {
    var diff = (current?.[code] || 0) - (previous?.[code] || 0);
    if (diff !== 0) delta[code] = diff;
  }
  return delta;
}

function historySummary(history, report) {
  var previous = history[history.length - 1] || null;
  return {
    runsLoaded: history.length,
    previousGeneratedAt: previous?.generatedAt || null,
    mismatchDelta: previous ? report.summary.mismatches - (previous.summary?.mismatches || 0) : 0,
    warningCodeDelta: previous ? codeDelta(previous.warningCodeFrequency, report.warningCodeFrequency) : {},
    blockingCodeDelta: previous ? codeDelta(previous.blockingCodeFrequency, report.blockingCodeFrequency) : {},
  };
}

async function writeHistory(report) {
  await mkdir(HISTORY_DIR, { recursive: true });
  var date = new Date().toISOString().slice(0, 10);
  var historyRecord = {
    schema: "contentforge.campaign_factory_audit_history.v1",
    generatedAt: report.generatedAt,
    summary: report.summary,
    warningCodeFrequency: report.warningCodeFrequency,
    blockingCodeFrequency: report.blockingCodeFrequency,
    slowestSamples: report.slowestSamples,
    mismatches: report.mismatches,
  };
  var historyPath = path.join(HISTORY_DIR, date + ".jsonl");
  await appendFile(historyPath, JSON.stringify(historyRecord) + "\n");
  await writeFile(path.join(HISTORY_DIR, "latest.json"), JSON.stringify(historyRecord, null, 2) + "\n");
  return historyPath;
}

export async function buildCampaignAuditReport(options = {}) {
  if (options.generate !== false) await generateCampaignFactoryFixtures();
  var expectedManifest = await readJson(EXPECTED_MANIFEST, { fixtures: [] });
  var realManifest = await readJson(REAL_MANIFEST, { samples: [] });
  var fixtures = [
    ...expectedManifest.fixtures.map((fixture) => ({ fixture, source: "generated" })),
  ];
  for (var sample of realManifest.samples || []) {
    var fixture = normalizeRealFixture(sample);
    fixtures.push({ fixture, source: "real" });
  }
  if (Number.isInteger(options.limit) && options.limit > 0) {
    fixtures = fixtures.slice(0, options.limit);
  }

  var results = [];
  for (var i = 0; i < fixtures.length; i++) {
    var item = fixtures[i];
    if (!(await exists(path.join(ROOT, item.fixture.file)))) {
      results.push({
        source: item.source,
        file: item.fixture.file,
        skipped: true,
        reason: "fixture file missing",
        mismatches: [],
      });
      continue;
    }
    results.push(await auditFixture(item.fixture, i, item.source));
  }

  var warningCodeFrequency = {};
  var blockingCodeFrequency = {};
  var mismatches = [];
  var fallbackCount = 0;
  for (var result of results) {
    incrementAll(warningCodeFrequency, result.warningCodes);
    incrementAll(blockingCodeFrequency, result.blockingCodes);
    mismatches.push(...(result.mismatches || []));
    if (result.ocr?.fallbackUsed) fallbackCount++;
  }
  var audited = results.filter((result) => !result.skipped).length;
  var skipped = results.length - audited;
  var slowestSamples = results
    .filter((result) => !result.skipped)
    .sort((a, b) => (b.timings?.totalMs || 0) - (a.timings?.totalMs || 0))
    .slice(0, 5)
    .map((result) => ({
      file: result.file,
      totalMs: result.timings?.totalMs || 0,
      advisoryMs: result.timings?.layersMs?.advisory || 0,
      ocrMs: result.timings?.advisory?.ocrMs || 0,
    }));

  var report = {
    schema: "contentforge.campaign_factory_calibration_report.v1",
    thresholdSchema: CAMPAIGN_FACTORY_AUDIT_CONFIG.schema,
    generatedAt: new Date().toISOString(),
    summary: {
      total: results.length,
      audited,
      skipped,
      mismatches: mismatches.length,
      ocrFallbackRate: audited ? Math.round((fallbackCount / audited) * 100) + "%" : "0%",
      advisoryLatencySoftLimitMs: CAMPAIGN_FACTORY_AUDIT_CONFIG.thresholds.advisoryLatencySoftLimitMs,
    },
    warningCodeFrequency,
    blockingCodeFrequency,
    slowestSamples,
    mismatches,
    results,
  };
  report.history = historySummary(await loadHistory(), report);
  return report;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  buildCampaignAuditReport({ generate: !hasFlag("--no-generate") })
    .then(async (report) => {
      if (hasFlag("--write-history")) {
        report.historyPath = await writeHistory(report);
      }
      if (hasFlag("--html")) console.log(htmlReport(report));
      else if (hasFlag("--markdown")) console.log(markdownReport(report));
      else console.log(JSON.stringify(report, null, 2));
      if (hasFlag("--fail-on-mismatch") && report.mismatches.length) process.exitCode = 1;
    })
    .catch((error) => {
      console.error(error.stack || error.message);
      process.exit(1);
    });
}
