import { campaignFactoryThresholds } from "./campaign-factory-audit-config.js";

function numberValue(...values) {
  for (var value of values) {
    if (value === null || value === undefined || value === "") continue;
    var numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric <= 1 && numeric >= 0 ? Math.round(numeric * 100) : Math.round(numeric);
    }
  }
  return null;
}

function warning(code, label, message) {
  return { code, label, message, severity: "warn" };
}

export function buildViralityGate(report, options = {}) {
  var thresholds = campaignFactoryThresholds();
  var required = Boolean(options.required);
  if (!report || typeof report !== "object") {
    return {
      available: false,
      configured: false,
      provider: "higgsfield_virality_predictor",
      modelBacked: false,
      verdict: required ? "warn" : "pass",
      score: null,
      thresholds: {
        minViralityScore: thresholds.minViralityScore,
        minHookViralityScore: thresholds.minHookViralityScore,
        maxRetentionRiskScore: thresholds.maxRetentionRiskScore,
      },
      warnings: required
        ? [warning("virality_not_configured", "Virality gate not configured", "No Higgsfield virality report was supplied for the requested virality gate")]
        : [],
    };
  }

  var metrics = report.metrics || {};
  var prediction = report.prediction || report.result || {};
  var score = numberValue(
    report.viralityScore,
    report.virality_score,
    report.overallScore,
    report.overall_score,
    report.score,
    prediction.viralityScore,
    prediction.score,
    metrics.viralityScore,
    metrics.overallScore
  );
  var hookScore = numberValue(
    report.hookScore,
    report.hook_strength,
    report.hookStrength,
    prediction.hookScore,
    metrics.hookScore,
    metrics.hookStrength
  );
  var retentionRisk = numberValue(
    report.retentionRisk,
    report.retention_risk,
    prediction.retentionRisk,
    metrics.retentionRisk
  );
  var warnings = [];
  if (score === null) {
    warnings.push(warning("virality_score_missing", "Virality score missing", "Higgsfield virality report did not include a usable overall score"));
  } else if (score < thresholds.minViralityScore) {
    warnings.push(warning("virality_score_low", "Virality score low", "Predicted virality is below the Campaign Factory fan-out threshold"));
  }
  if (hookScore !== null && hookScore < thresholds.minHookViralityScore) {
    warnings.push(warning("virality_hook_score_low", "Hook score low", "Predicted hook strength is below the Campaign Factory threshold"));
  }
  if (retentionRisk !== null && retentionRisk > thresholds.maxRetentionRiskScore) {
    warnings.push(warning("virality_retention_risk_high", "Retention risk high", "Predicted retention risk is above the Campaign Factory threshold"));
  }

  return {
    available: true,
    configured: true,
    provider: report.provider || "higgsfield_virality_predictor",
    model: report.model || "virality_predictor",
    modelBacked: report.modelBacked !== false,
    verdict: warnings.length ? "warn" : "pass",
    score,
    hookScore,
    retentionRisk,
    thresholds: {
      minViralityScore: thresholds.minViralityScore,
      minHookViralityScore: thresholds.minHookViralityScore,
      maxRetentionRiskScore: thresholds.maxRetentionRiskScore,
    },
    warnings,
    reportId: report.job_id || report.jobId || report.reportId || null,
  };
}
