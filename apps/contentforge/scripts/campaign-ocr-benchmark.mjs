import { buildCampaignAuditReport } from "./campaign-audit-report.mjs";

const ENGINES = ["tesseract", "apple_vision"];

function summarize(engine, report) {
  var auditedResults = report.results.filter((result) => !result.skipped);
  var confidenceValues = auditedResults
    .map((result) => result.ocr?.avgConfidence)
    .filter((value) => Number.isFinite(value));
  return {
    engine,
    audited: report.summary.audited,
    mismatches: report.summary.mismatches,
    ocrFallbackRate: report.summary.ocrFallbackRate,
    avgConfidence: confidenceValues.length
      ? Math.round(confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length)
      : null,
    warningCodeFrequency: report.warningCodeFrequency,
    blockingCodeFrequency: report.blockingCodeFrequency,
    slowestSamples: report.slowestSamples,
  };
}

async function runBenchmark() {
  var originalEngine = process.env.CONTENTFORGE_OCR_ENGINE;
  var results = [];
  for (var engine of ENGINES) {
    process.env.CONTENTFORGE_OCR_ENGINE = engine;
    var report = await buildCampaignAuditReport({ generate: results.length === 0, limit: 4 });
    results.push(summarize(engine, report));
  }
  if (originalEngine === undefined) delete process.env.CONTENTFORGE_OCR_ENGINE;
  else process.env.CONTENTFORGE_OCR_ENGINE = originalEngine;
  return {
    schema: "contentforge.campaign_factory_ocr_benchmark.v1",
    generatedAt: new Date().toISOString(),
    sampleLimit: 4,
    results,
  };
}

runBenchmark()
  .then((report) => {
    console.log(JSON.stringify(report, null, 2));
  })
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
