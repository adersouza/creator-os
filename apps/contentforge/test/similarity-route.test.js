import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "child_process";
import { mkdir, rm, writeFile } from "fs/promises";
import path from "path";
import { POST } from "../app/api/similarity/route.js";
import { LEGACY_FINAL_DIR, UPLOADS_DIR } from "../lib/paths.js";

if (!process.env.CONTENTFORGE_OCR_ENGINE) {
  process.env.CONTENTFORGE_OCR_ENGINE = "tesseract";
}

async function seedCampaignFactoryFiles() {
  await mkdir(UPLOADS_DIR, { recursive: true });
  await mkdir(LEGACY_FINAL_DIR, { recursive: true });
  var source = path.join(UPLOADS_DIR, "cf_similarity_source.jpg");
  var variant = path.join(LEGACY_FINAL_DIR, "cf_similarity_variant.jpg");
  await writeFile(source, "source fixture");
  await writeFile(variant, "variant fixture");
  return { source, variant, sourceName: path.basename(source), variantName: path.basename(variant) };
}

async function cleanupCampaignFactoryFiles(files) {
  if (!files) return;
  await rm(files.source, { force: true });
  await rm(files.variant, { force: true });
}

function similarityRequest(body) {
  return new Request("http://localhost/api/similarity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function run(command, args) {
  return new Promise(function (resolve, reject) {
    execFile(command, args, { timeout: 60000, maxBuffer: 4 * 1024 * 1024 }, function (error, stdout, stderr) {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

async function seedMp4Fixture({ sourceName, variantName, uploadReady, variantSize = "1080x1920", variantFilter = null, variantLavfi = null }) {
  await mkdir(UPLOADS_DIR, { recursive: true });
  await mkdir(LEGACY_FINAL_DIR, { recursive: true });
  var source = path.join(UPLOADS_DIR, sourceName);
  var variant = path.join(LEGACY_FINAL_DIR, variantName);
  await rm(source, { force: true });
  await rm(variant, { force: true });

  await run("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30",
    "-t", "0.5",
    "-an",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
    "-metadata", "creation_time=2026-05-14T12:00:00Z",
    "-metadata:s:v:0", "handler_name=Core Media Video",
    "-y", source,
  ]);

  var variantArgs = [
    "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", variantLavfi || "testsrc=size=" + variantSize + ":rate=30",
    "-t", "0.5",
    "-an",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-pix_fmt", "yuv420p",
  ];
  if (variantFilter) {
    variantArgs.push("-vf", variantFilter);
  }
  if (uploadReady) {
    variantArgs.push(
      "-movflags", "+faststart",
      "-brand", "mp42",
      "-metadata", "creation_time=2026-05-14T12:00:00Z",
      "-metadata:s:v:0", "handler_name=Core Media Video"
    );
  }
  variantArgs.push("-y", variant);
  await run("ffmpeg", variantArgs);
  return { source, variant, sourceName, variantName };
}

async function cleanupMp4Fixture(files) {
  if (!files) return;
  await rm(files.source, { force: true });
  await rm(files.variant, { force: true });
}

test("/api/similarity returns 200 for Campaign Factory staged source and output/final file", async function () {
  var files = await seedCampaignFactoryFiles();
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.filesAnalyzed >= 1, true);
    assert.equal(typeof body.layers.forensics, "object");
    assert.equal(["pass", "warn", "fail"].includes(body.overallVerdict), true);
    assert.equal(Object.hasOwn(body.verdicts, "forensics"), true);
  } finally {
    await cleanupCampaignFactoryFiles(files);
  }
});

test("/api/similarity warns but does not fail an upload-ready Campaign Factory FFmpeg render", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_ready_source.mp4",
    variantName: "000_cf_ready_variant.mp4",
    uploadReady: true,
  });
  var stale = await seedMp4Fixture({
    sourceName: "000_cf_stale_source.mp4",
    variantName: "000_cf_stale_variant.mp4",
    uploadReady: false,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    var report = body.layers.forensics.fileReports.find((item) => item.name === files.variantName);
    assert.equal(response.status, 200);
    assert.equal(body.contractVersion, "campaign_factory_audit.v1.3");
    assert.equal(body.auditProfile, "campaign_factory_v1");
    assert.equal(body.targetFile, files.variantName);
    assert.equal(body.filesAnalyzed, 1);
    assert.equal(report.score, "warn");
    assert.equal(report.uploadReady, true);
    assert.equal(body.verdicts.forensics, "warn");
    assert.equal(body.verdictCodes.forensics, "forensics_warn");
    assert.equal(Object.hasOwn(body.verdictCodes, "safeZone"), true);
    assert.equal(Object.hasOwn(body.verdictCodes, "readability"), true);
    assert.equal(Object.hasOwn(body.verdictCodes, "creativeQuality"), true);
    assert.equal(Array.isArray(body.coverCandidates), true);
    assert.equal(typeof body.creativeQuality.score, "number");
    assert.equal(body.creativeQuality.semanticEngine, "heuristic_v1");
    assert.equal(typeof body.timings.totalMs, "number");
    assert.notEqual(body.overallVerdict, "fail");
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.equal(body.readinessSummary.blockingReasons.length, 0);
    assert.equal(body.readinessSummary.warningCodes.includes("forensics_ffmpeg_signature"), true);
    assert.equal(body.readinessSummary.warningCodes.includes("forensics_binary_signature"), true);
    assert.equal(body.readinessSummary.topWarnings.every((item) => item.severity === "warn"), true);
    assert.equal(body.readinessSummary.operatorLabels.advisory.some((item) => item.code === "forensics_ffmpeg_signature"), true);
    assert.match(body.readinessSummary.summaryText, /Upload-ready candidate/);
  } finally {
    await cleanupMp4Fixture(files);
    await cleanupMp4Fixture(stale);
  }
});

test("/api/similarity adds advisory caption safe-zone warnings for Campaign Factory reels", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_caption_source.mp4",
    variantName: "000_cf_caption_variant.mp4",
    uploadReady: true,
    variantLavfi: "color=c=black:s=1080x1920:r=30",
    variantFilter: "drawbox=x=20:y=1740:w=850:h=42:color=white:t=fill,drawbox=x=20:y=1810:w=700:h=42:color=white:t=fill",
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    var warningCodes = body.readinessSummary.warningCodes;
    assert.equal(response.status, 200);
    assert.equal(body.safeZone.verdict, "warn");
    assert.equal(body.verdictCodes.safeZone, "safe_zone_warn");
    assert.equal(body.verdictCodes.readability, "caption_readable");
    assert.equal(body.safeZone.metrics.frameSamples > 0, true);
    assert.equal(body.safeZone.metrics.textBoxesDetected > 0, true);
    assert.equal(warningCodes.includes("caption_too_close_to_edge"), true);
    assert.equal(warningCodes.includes("caption_overlaps_ui_safe_zone"), true);
    assert.equal(body.readinessSummary.topWarnings.some((item) => item.code === "caption_too_close_to_edge" && item.severity === "warn"), true);
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.notEqual(body.overallVerdict, "fail");
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity reports hook and cover advisory signals without blocking", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_static_source.mp4",
    variantName: "000_cf_static_variant.mp4",
    uploadReady: true,
    variantFilter: null,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(Array.isArray(body.coverCandidates), true);
    assert.equal(body.coverCandidates.length > 0, true);
    assert.equal(Object.hasOwn(body.verdictCodes, "hookVisibility"), true);
    assert.equal(Object.hasOwn(body.hookVisibility.metrics, "avgFrameDelta"), true);
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.notEqual(body.overallVerdict, "fail");
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity reports creative-quality warnings for weak openings", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_creative_source.mp4",
    variantName: "000_cf_creative_variant.mp4",
    uploadReady: true,
    variantLavfi: "color=c=black:s=1080x1920:r=30",
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics", "creativeQuality"],
    }));
    var body = await response.json();
    var creativeCodes = body.creativeQuality.warnings.map((item) => item.code);
    assert.equal(response.status, 200);
    assert.equal(body.verdicts.creativeQuality, "warn");
    assert.equal(body.verdictCodes.creativeQuality, "creative_quality_warn");
    assert.equal(body.creativeQuality.modelBacked, false);
    assert.equal(["weak", "medium", "strong"].includes(body.creativeQuality.hookClarity.level), true);
    assert.equal(Object.hasOwn(body.creativeQuality, "subjectVisibility"), true);
    assert.equal(Object.hasOwn(body.creativeQuality, "visualClarity"), true);
    assert.equal(Object.hasOwn(body.creativeQuality, "openingStrength"), true);
    assert.equal(creativeCodes.includes("creative_hook_missing"), true);
    assert.equal(body.readinessSummary.warningCodes.includes("creative_hook_missing"), true);
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.notEqual(body.overallVerdict, "fail");
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity reports explicit reference matches as a non-blocking variation meter", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_originality_source.mp4",
    variantName: "000_cf_originality_target.mp4",
    uploadReady: true,
  });
  var prior = await seedMp4Fixture({
    sourceName: "000_cf_originality_prior_source.mp4",
    variantName: "000_cf_originality_prior.mp4",
    uploadReady: true,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      originalityReferenceFiles: [prior.variantName],
      layers: ["forensics", "originality"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.filesAnalyzed, 1);
    assert.equal(body.verdicts.originality, "pass");
    assert.equal(body.verdictCodes.originality, "originality_pass");
    assert.equal(body.multiAccountOriginalityAudit.mode, "reference_match_meter");
    assert.equal(body.multiAccountOriginalityAudit.blocking, false);
    assert.equal(body.multiAccountOriginalityAudit.referenceMatchLevel, "high");
    assert.equal(body.multiAccountOriginalityAudit.duplicateRisk, "high");
    assert.equal(body.referenceMatch.referenceMatchScore >= 78, true);
    assert.equal(body.referenceMatch.variationScore <= 22, true);
    assert.equal(body.multiAccountOriginalityAudit.nearestMatches[0].file, prior.variantName);
    assert.equal(body.multiAccountOriginalityAudit.nearestMatches[0].score >= 78, true);
    assert.equal(body.multiAccountOriginalityAudit.sameOpeningRisk, "high");
    assert.equal(body.multiAccountOriginalityAudit.sameCoverRisk, "high");
    assert.equal(body.multiAccountOriginalityAudit.variationNotes.length > 0, true);
    assert.equal(body.multiAccountOriginalityAudit.referenceMatchSignals.some(function (signal) {
      return signal.code === "reference_match_close";
    }), true);
    assert.equal(body.multiAccountOriginalityAudit.referenceMatchSignals.some(function (signal) {
      return signal.code === "reference_match_same_opening";
    }), true);
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.notEqual(body.overallVerdict, "fail");
    assert.equal(body.readinessSummary.warningCodes.includes("originality_duplicate_risk"), false);
    assert.equal(body.readinessSummary.warningCodes.includes("originality_same_opening"), false);
    assert.equal(body.readinessSummary.warningCodes.includes("reference_match_close"), false);
  } finally {
    await cleanupMp4Fixture(files);
    await cleanupMp4Fixture(prior);
  }
});

test("/api/similarity preserves forced Tesseract OCR metadata", async function () {
  var originalEngine = process.env.CONTENTFORGE_OCR_ENGINE;
  process.env.CONTENTFORGE_OCR_ENGINE = "tesseract";
  var files = await seedMp4Fixture({
    sourceName: "000_cf_tesseract_source.mp4",
    variantName: "000_cf_tesseract_variant.mp4",
    uploadReady: true,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.ocr.available, true);
    assert.equal(body.ocr.engine, "tesseract");
    assert.equal(typeof body.ocr.engineVersion, "string");
    assert.equal(body.ocr.fallbackUsed, false);
    assert.equal(typeof body.ocr.sampleCount, "number");
    assert.equal(Object.hasOwn(body.ocr, "avgConfidence"), true);
    assert.equal(body.ocr.preprocessing.includes("enhanced_2x"), true);
    assert.equal(typeof body.ocr.boxesBeforeMerge, "number");
  } finally {
    if (originalEngine === undefined) delete process.env.CONTENTFORGE_OCR_ENGINE;
    else process.env.CONTENTFORGE_OCR_ENGINE = originalEngine;
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity keeps unavailable forced OCR engine advisory-only", async function () {
  var originalEngine = process.env.CONTENTFORGE_OCR_ENGINE;
  var originalVisionScript = process.env.CONTENTFORGE_APPLE_VISION_SCRIPT;
  process.env.CONTENTFORGE_OCR_ENGINE = "apple_vision";
  process.env.CONTENTFORGE_APPLE_VISION_SCRIPT = path.join(process.cwd(), "does-not-exist.swift");
  var files = await seedMp4Fixture({
    sourceName: "000_cf_ocr_unavailable_source.mp4",
    variantName: "000_cf_ocr_unavailable_variant.mp4",
    uploadReady: true,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.ocr.available, false);
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.equal(body.readinessSummary.warningCodes.includes("ocr_unavailable"), true);
    assert.notEqual(body.overallVerdict, "fail");
  } finally {
    if (originalEngine === undefined) delete process.env.CONTENTFORGE_OCR_ENGINE;
    else process.env.CONTENTFORGE_OCR_ENGINE = originalEngine;
    if (originalVisionScript === undefined) delete process.env.CONTENTFORGE_APPLE_VISION_SCRIPT;
    else process.env.CONTENTFORGE_APPLE_VISION_SCRIPT = originalVisionScript;
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity auto OCR falls back from Apple Vision to Tesseract", async function () {
  var originalEngine = process.env.CONTENTFORGE_OCR_ENGINE;
  var originalVisionScript = process.env.CONTENTFORGE_APPLE_VISION_SCRIPT;
  process.env.CONTENTFORGE_OCR_ENGINE = "auto";
  process.env.CONTENTFORGE_APPLE_VISION_SCRIPT = path.join(process.cwd(), "does-not-exist.swift");
  var files = await seedMp4Fixture({
    sourceName: "000_cf_ocr_fallback_source.mp4",
    variantName: "000_cf_ocr_fallback_variant.mp4",
    uploadReady: true,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.ocr.available, true);
    assert.equal(body.ocr.engine, "tesseract");
    assert.equal(body.ocr.fallbackUsed, true);
    assert.match(body.ocr.fallbackReason, /apple_vision/i);
    assert.equal(body.readinessSummary.warningCodes.includes("ocr_unavailable"), false);
    assert.notEqual(body.overallVerdict, "fail");
  } finally {
    if (originalEngine === undefined) delete process.env.CONTENTFORGE_OCR_ENGINE;
    else process.env.CONTENTFORGE_OCR_ENGINE = originalEngine;
    if (originalVisionScript === undefined) delete process.env.CONTENTFORGE_APPLE_VISION_SCRIPT;
    else process.env.CONTENTFORGE_APPLE_VISION_SCRIPT = originalVisionScript;
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity warns on legacy FFmpeg metadata when the media is otherwise compatible", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_legacy_source.mp4",
    variantName: "000_cf_legacy_variant.mp4",
    uploadReady: false,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    var report = body.layers.forensics.fileReports.find((item) => item.name === files.variantName);
    assert.equal(response.status, 200);
    assert.equal(report.score, "warn");
    assert.equal(report.uploadReady, true);
    assert.equal(body.overallVerdict, "warn");
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.equal(body.readinessSummary.recommendedAction, "review");
    assert.equal(body.readinessSummary.blockingReasons.length, 0);
    assert.equal(body.readinessSummary.warningCodes.includes("forensics_missing_creation_time"), true);
    assert.equal(body.readinessSummary.warningCodes.includes("forensics_default_handler_name"), true);
    assert.equal(body.readinessSummary.warningCodes.includes("forensics_missing_faststart"), true);
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity fails a Campaign Factory render with invalid social dimensions", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_bad_source.mp4",
    variantName: "000_cf_bad_variant.mp4",
    uploadReady: false,
    variantSize: "640x640",
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    var report = body.layers.forensics.fileReports.find((item) => item.name === files.variantName);
    assert.equal(response.status, 200);
    assert.equal(report.score, "fail");
    assert.equal(report.uploadReady, false);
    assert.equal(body.overallVerdict, "fail");
    assert.equal(body.readinessSummary.uploadReady, false);
    assert.equal(body.readinessSummary.recommendedAction, "reject");
    assert.equal(body.readinessSummary.blockingCodes.includes("forensics_bad_dimensions"), true);
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity keeps Campaign Factory profile explicit", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_default_source.mp4",
    variantName: "000_cf_default_variant.mp4",
    uploadReady: true,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      targetFile: files.variantName,
      layers: ["forensics"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.auditProfile, "default");
    assert.equal(body.overallVerdict, "fail");
    assert.equal(body.readinessSummary.blockingCodes.includes("forensics_ffmpeg_signature"), true);
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity reports optional Python layer failures as warnings", async function () {
  var files = await seedCampaignFactoryFiles();
  var originalPython = process.env.CONTENTFORGE_PYTHON;
  process.env.CONTENTFORGE_PYTHON = process.execPath;
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      layers: ["compression"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.verdicts.compression, "warn");
    assert.equal(body.layers.compression.available, false);
    assert.equal(body.filesAnalyzed >= 1, true);
  } finally {
    if (originalPython === undefined) delete process.env.CONTENTFORGE_PYTHON;
    else process.env.CONTENTFORGE_PYTHON = originalPython;
    await cleanupCampaignFactoryFiles(files);
  }
});

test("/api/similarity keeps optional c2pa unavailability as a warning", async function () {
  var files = await seedCampaignFactoryFiles();
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      layers: ["provenance"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.verdicts.provenance, "warn");
    assert.equal(body.overallVerdict, "warn");
    assert.equal(body.readinessSummary.uploadReady, true);
    assert.equal(body.readinessSummary.blockingReasons.length, 0);
    assert.equal(body.readinessSummary.warningCodes.includes("provenance_c2pa_unavailable"), true);
    assert.match(body.readinessSummary.warnings.join("\n"), /c2pa|provenance/i);
  } finally {
    await cleanupCampaignFactoryFiles(files);
  }
});

test("/api/similarity keeps compression review findings as warnings when layer verdict is warn", async function () {
  var files = await seedMp4Fixture({
    sourceName: "000_cf_compression_source.mp4",
    variantName: "000_cf_compression_variant.mp4",
    uploadReady: true,
  });
  try {
    var response = await POST(similarityRequest({
      source: files.sourceName,
      auditProfile: "campaign_factory_v1",
      targetFile: files.variantName,
      layers: ["compression"],
    }));
    var body = await response.json();
    assert.equal(response.status, 200);
    if (body.verdicts.compression === "warn") {
      var warningText = body.readinessSummary.warnings.join("\n");
      var warningCodes = body.readinessSummary.warningCodes;
      var compressionSummary = body.layers.compression?.summary || {};
      assert.equal(body.overallVerdict, "warn");
      assert.equal(body.readinessSummary.uploadReady, true);
      assert.equal(body.readinessSummary.blockingReasons.length, 0);
      assert.equal(warningCodes.some(function (code) { return /^compression_/.test(code); }), true);
      assert.match(warningText, /compression/i);
      if ((compressionSummary.failed || 0) > 0) {
        assert.equal(warningCodes.includes("compression_gop_review"), true);
        assert.match(warningText, /Compression pattern needs review/i);
      }
    }
  } finally {
    await cleanupMp4Fixture(files);
  }
});

test("/api/similarity rejects missing and nonexistent source clearly", async function () {
  var missing = await POST(similarityRequest({ layers: ["forensics"] }));
  assert.equal(missing.status, 400);
  assert.match((await missing.json()).error, /source/i);

  var nonexistent = await POST(similarityRequest({
    source: "does-not-exist.mp4",
    layers: ["forensics"],
  }));
  assert.equal(nonexistent.status, 404);
  assert.match((await nonexistent.json()).error, /not found/i);
});
