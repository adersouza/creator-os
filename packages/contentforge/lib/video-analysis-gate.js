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

function nested(report) {
  return report?.scores || report?.metrics || report?.analysis || report?.result || {};
}

export function buildVideoAnalysisGate(report, options = {}) {
  var thresholds = campaignFactoryThresholds();
  var required = Boolean(options.required);
  if (!report || typeof report !== "object") {
    return {
      available: false,
      configured: false,
      provider: "higgsfield_video_analysis",
      modelBacked: false,
      verdict: required ? "warn" : "pass",
      score: null,
      thresholds: {
        minVideoAnalysisScore: thresholds.minVideoAnalysisScore,
        minSubjectClarityScore: thresholds.minSubjectClarityScore,
        minFirstThreeSecondsScore: thresholds.minFirstThreeSecondsScore,
        minShareabilityScore: thresholds.minShareabilityScore,
      },
      warnings: required
        ? [warning("video_analysis_not_configured", "Video analysis not configured", "No Higgsfield video_analysis or VLM report was supplied for the requested quality gate")]
        : [],
    };
  }

  var body = nested(report);
  var score = numberValue(report.score, report.overallScore, report.qualityScore, body.score, body.overallScore, body.qualityScore);
  var subjectClarityScore = numberValue(
    report.subjectClarityScore,
    report.subject_score,
    report.subjectVisibilityScore,
    body.subjectClarityScore,
    body.subjectVisibilityScore
  );
  var firstThreeSecondsScore = numberValue(
    report.firstThreeSecondsScore,
    report.first3sScore,
    report.openingScore,
    body.firstThreeSecondsScore,
    body.first3sScore,
    body.openingScore
  );
  var shareabilityScore = numberValue(report.shareabilityScore, report.sendWorthinessScore, body.shareabilityScore, body.sendWorthinessScore);
  var warnings = [];
  if (score === null) {
    warnings.push(warning("video_analysis_score_missing", "Video analysis score missing", "Video analysis report did not include a usable overall quality score"));
  } else if (score < thresholds.minVideoAnalysisScore) {
    warnings.push(warning("video_analysis_score_low", "Video analysis score low", "Model-backed creative quality is below the Campaign Factory fan-out threshold"));
  }
  if (subjectClarityScore !== null && subjectClarityScore < thresholds.minSubjectClarityScore) {
    warnings.push(warning("video_analysis_subject_clarity_low", "Subject clarity low", "Main subject clarity is below the Campaign Factory threshold"));
  }
  if (firstThreeSecondsScore !== null && firstThreeSecondsScore < thresholds.minFirstThreeSecondsScore) {
    warnings.push(warning("video_analysis_first3s_low", "Opening quality low", "First-three-seconds quality is below the Campaign Factory threshold"));
  }
  if (shareabilityScore !== null && shareabilityScore < thresholds.minShareabilityScore) {
    warnings.push(warning("video_analysis_shareability_low", "Shareability low", "Predicted shareability is below the Campaign Factory threshold"));
  }

  return {
    available: true,
    configured: true,
    provider: report.provider || "higgsfield_video_analysis",
    model: report.model || "video_analysis",
    modelBacked: report.modelBacked !== false,
    verdict: warnings.length ? "warn" : "pass",
    score,
    subjectClarityScore,
    firstThreeSecondsScore,
    shareabilityScore,
    thresholds: {
      minVideoAnalysisScore: thresholds.minVideoAnalysisScore,
      minSubjectClarityScore: thresholds.minSubjectClarityScore,
      minFirstThreeSecondsScore: thresholds.minFirstThreeSecondsScore,
      minShareabilityScore: thresholds.minShareabilityScore,
    },
    warnings,
    reportId: report.job_id || report.jobId || report.reportId || null,
  };
}
