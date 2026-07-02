"use client";

import { useState } from "react";

var LAYER_INFO = {
  pdq: {
    label: "PDQ Hash",
    desc: "Meta's production fingerprint algorithm (Hamming distance, threshold 31/256)",
    icon: "#",
  },
  sscd: {
    label: "SSCD Embedding",
    desc: "Meta's neural copy detection model (cosine similarity, 512-d vectors)",
    icon: "\u29C9",
  },
  audio: {
    label: "Audio Fingerprint",
    desc: "Chromaprint spectral landmark comparison",
    icon: "\u266B",
  },
  forensics: {
    label: "Metadata Forensics",
    desc: "Encoder signatures, container atoms, bitrate analysis",
    icon: "\u2316",
  },
  compression: {
    label: "Compression Forensics",
    desc: "DCT periodicity, GOP analysis, x264 SEI detection, encoder fingerprints",
    icon: "\u2623",
  },
  provenance: {
    label: "AI Provenance",
    desc: "C2PA manifests, IPTC DigitalSourceType, PNG AI chunks (SD/ComfyUI)",
    icon: "\u2318",
  },
  reference: {
    label: "Reference Database",
    desc: "FAISS cross-batch comparison against published content index",
    icon: "\u2637",
  },
  temporal: {
    label: "Temporal PDQ",
    desc: "Multi-frame temporal hash sequence (TMK Level 1 approximation)",
    icon: "\u23F1",
  },
  ssim: {
    label: "Visual Quality",
    desc: "SSIM structural similarity (quality indicator only)",
    icon: "\u25A3",
  },
};

var VERDICT_COLORS = {
  pass: "#22c55e",
  warn: "#eab308",
  fail: "#ef4444",
};

var VERDICT_LABELS = {
  pass: "Pass",
  warn: "Warning",
  fail: "Fail",
};

function VerdictBadge({ verdict }) {
  if (!verdict) return null;
  return (
    <span
      className="text-[10px] font-mono font-medium px-2 py-0.5 rounded-full"
      style={{
        color: VERDICT_COLORS[verdict],
        background: VERDICT_COLORS[verdict] + "15",
        border: "1px solid " + VERDICT_COLORS[verdict] + "30",
      }}
    >
      {VERDICT_LABELS[verdict]}
    </span>
  );
}

function LayerHeader({ layerKey, verdict, expanded, onToggle }) {
  var info = LAYER_INFO[layerKey];
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center justify-between p-3 bg-[#0a0a10] rounded-lg border border-border
        hover:border-border-hover transition-all cursor-pointer text-left"
    >
      <div className="flex items-center gap-3">
        <span className="text-[14px] w-6 text-center text-muted-dark">{info.icon}</span>
        <div>
          <div className="text-[11px] text-[#c8c8d0] font-medium">{info.label}</div>
          <div className="text-[9px] text-muted-darker">{info.desc}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <VerdictBadge verdict={verdict} />
        <span className="text-[10px] text-muted-darker">{expanded ? "\u25B2" : "\u25BC"}</span>
      </div>
    </button>
  );
}

// ─── PDQ Layer Detail ───
function PDQDetail({ data }) {
  if (data.error) return <div className="text-[11px] text-red-400 p-3">{data.error}</div>;
  var stats = data.stats || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-2">
        <StatMini value={stats.safePercent + "%"} label="Pass rate" color={stats.safePercent >= 90 ? "#22c55e" : stats.safePercent >= 70 ? "#eab308" : "#ef4444"} />
        <StatMini value={stats.avgDistance != null ? stats.avgDistance : "--"} label="Avg distance" color="#c8c8d0" />
        <StatMini value={stats.minDistance != null ? stats.minDistance : "--"} label="Min (closest)" color={stats.minDistance <= 31 ? "#ef4444" : "#eab308"} />
        <StatMini value={stats.crossCollisions || 0} label="Cross-collisions" color={stats.crossCollisions > 0 ? "#ef4444" : "#22c55e"} />
      </div>
      <div className="text-[9px] text-muted-darker flex items-center gap-2">
        <span>Threshold: Hamming distance {">"} 31 = safe</span>
        <span>|</span>
        <span>Source quality: {data.sourceQuality}/100</span>
      </div>
      {data.results && data.results.length > 0 && (
        <div className="max-h-[180px] overflow-y-auto rounded border border-border">
          <table className="w-full">
            <tbody>
              {data.results.map((r, i) => (
                <tr key={r.name} className={i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]"}>
                  <td className="px-2 py-1.5 text-[9px] text-muted-dark font-mono truncate max-w-[180px]">{r.name}</td>
                  <td className="px-2 py-1.5 text-right">
                    {r.distance != null ? (
                      <span className="text-[10px] font-mono" style={{ color: r.safe ? "#22c55e" : "#ef4444" }}>
                        {r.distance}/256
                      </span>
                    ) : (
                      <span className="text-[9px] text-muted-darker">{r.error || "--"}</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 w-[80px]">
                    <div className="h-1 bg-[#1c1c24] rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{
                        width: r.distance != null ? Math.min(100, (r.distance / 256) * 100) + "%" : "0%",
                        background: r.distance != null ? (r.safe ? "#22c55e" : "#ef4444") : "#1c1c24",
                      }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── SSCD Layer Detail ───
function SSCDDetail({ data }) {
  if (data.error) return <div className="text-[11px] text-red-400 p-3">{data.error}</div>;
  var stats = data.stats || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-2">
        <StatMini value={stats.passPercent != null ? stats.passPercent + "%" : "--"} label="Pass rate" color={stats.passPercent >= 80 ? "#22c55e" : stats.passPercent >= 50 ? "#eab308" : "#ef4444"} />
        <StatMini value={stats.avgSimilarity != null ? stats.avgSimilarity.toFixed(3) : "--"} label="Avg cosine sim" color="#c8c8d0" />
        <StatMini value={stats.maxSimilarity != null ? stats.maxSimilarity.toFixed(3) : "--"} label="Most similar" color={stats.maxSimilarity >= 0.75 ? "#ef4444" : stats.maxSimilarity >= 0.50 ? "#eab308" : "#22c55e"} />
        <StatMini value={stats.crossVariantCollisions || 0} label="Cross-collisions" color={stats.crossVariantCollisions > 0 ? "#ef4444" : "#22c55e"} />
      </div>
      <div className="text-[9px] text-muted-darker flex items-center gap-2">
        <span>{"< 0.50 = pass"}</span><span>|</span>
        <span>{"0.50-0.75 = warn"}</span><span>|</span>
        <span>{"> 0.75 = copy detected (90% precision)"}</span>
      </div>
      {data.results && data.results.length > 0 && (
        <div className="max-h-[180px] overflow-y-auto rounded border border-border">
          <table className="w-full">
            <tbody>
              {data.results.map((r, i) => (
                <tr key={r.name} className={i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]"}>
                  <td className="px-2 py-1.5 text-[9px] text-muted-dark font-mono truncate max-w-[180px]">{r.name}</td>
                  <td className="px-2 py-1.5 text-right">
                    {r.similarity != null ? (
                      <span className="text-[10px] font-mono" style={{ color: r.verdict === "pass" ? "#22c55e" : r.verdict === "warn" ? "#eab308" : "#ef4444" }}>
                        {r.similarity.toFixed(3)}
                      </span>
                    ) : (
                      <span className="text-[9px] text-muted-darker">{r.error || "--"}</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 w-[80px]">
                    <div className="h-1 bg-[#1c1c24] rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{
                        width: r.similarity != null ? Math.min(100, r.similarity * 100) + "%" : "0%",
                        background: r.verdict === "pass" ? "#22c55e" : r.verdict === "warn" ? "#eab308" : "#ef4444",
                      }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Audio Layer Detail ───
function AudioDetail({ data }) {
  if (!data.available) return <div className="text-[11px] text-muted-darker p-3">{data.reason}</div>;
  var stats = data.stats || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <StatMini value={stats.total || 0} label="Checked" color="#c8c8d0" />
        <StatMini value={stats.identicalCount || 0} label="Identical audio" color={stats.identicalCount > 0 ? "#ef4444" : "#22c55e"} />
        <StatMini value={stats.identicalPercent + "%"} label="Match rate" color={stats.identicalPercent === 0 ? "#22c55e" : "#ef4444"} />
      </div>
      {stats.identicalCount > 0 && (
        <div className="text-[10px] text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
          {stats.identicalCount} variant(s) have identical audio fingerprints to source.
          Audio fingerprints still match the source. Consider a clearer audio transform or remove audio for this variant set.
        </div>
      )}
      {stats.identicalCount === 0 && (
        <div className="text-[10px] text-green bg-green/10 border border-green/20 rounded-lg px-3 py-2">
          All variants have unique audio fingerprints.
        </div>
      )}
    </div>
  );
}

// ─── Forensics Layer Detail ───
function ForensicsDetail({ data }) {
  var stats = data.stats || {};
  var cross = data.crossCorrelation || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <StatMini value={stats.clean || 0} label="Clean" color="#22c55e" />
        <StatMini value={stats.critical || 0} label="Critical" color={stats.critical > 0 ? "#ef4444" : "#22c55e"} />
        <StatMini value={stats.warnings || 0} label="Warnings" color={stats.warnings > 0 ? "#eab308" : "#22c55e"} />
      </div>

      {cross.checked && (
        <div className={"text-[10px] rounded-lg px-3 py-2 border " + (
          cross.tooUniform
            ? "text-amber bg-amber/10 border-amber/20"
            : "text-green bg-green/10 border-green/20"
        )}>
          Bitrate variation: {cross.bitrateVariation} — {cross.msg}
        </div>
      )}

      {data.fileReports && data.fileReports.length > 0 && (
        <div className="max-h-[200px] overflow-y-auto rounded border border-border">
          {data.fileReports.map((report, i) => (
            <div key={report.name} className={"px-3 py-2 border-b border-border last:border-b-0 " + (i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]")}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[9px] text-muted-dark font-mono truncate max-w-[200px]">{report.name}</span>
                <VerdictBadge verdict={report.score === "info" ? "warn" : report.score} />
              </div>
              {report.issues.length > 0 && (
                <div className="flex flex-col gap-0.5">
                  {report.issues.map((issue, j) => (
                    <div key={j} className="text-[9px] flex items-start gap-1.5">
                      <span style={{ color: issue.severity === "critical" ? "#ef4444" : issue.severity === "high" ? "#f97316" : "#eab308" }}>
                        {issue.severity === "critical" ? "\u2717" : "\u26A0"}
                      </span>
                      <span className="text-muted-darker">
                        <span className="text-muted-dark">{issue.field}:</span> {issue.msg}
                        {issue.value && <span className="text-muted-darker"> ({issue.value})</span>}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {report.issues.length === 0 && (
                <div className="text-[9px] text-green">{"\u2713"} No forensic issues detected</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Compression Forensics Layer Detail ───
function CompressionDetail({ data }) {
  if (data.error) return <div className="text-[11px] text-red-400 p-3">{data.error}</div>;
  var summary = data.summary || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <StatMini value={summary.passed || 0} label="Clean files" color="#22c55e" />
        <StatMini value={summary.failed || 0} label="Issues found" color={summary.failed > 0 ? "#ef4444" : "#22c55e"} />
        <StatMini value={summary.passRate + "%"} label="Pass rate" color={summary.passRate >= 80 ? "#22c55e" : summary.passRate >= 50 ? "#eab308" : "#ef4444"} />
      </div>

      {data.reports && data.reports.length > 0 && (
        <div className="max-h-[280px] overflow-y-auto rounded border border-border">
          {data.reports.map((report, i) => (
            <div key={report.file} className={"px-3 py-2 border-b border-border last:border-b-0 " + (i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]")}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[9px] text-muted-dark font-mono truncate max-w-[200px]">{report.file}</span>
                <VerdictBadge verdict={report.verdict} />
              </div>
              <div className="flex flex-col gap-1">
                {(report.checks || []).map((check, j) => (
                  <div key={j} className="text-[9px] flex items-start gap-1.5">
                    <span style={{ color: check.pass === true ? "#22c55e" : check.pass === false ? "#ef4444" : "#6b7280" }}>
                      {check.pass === true ? "\u2713" : check.pass === false ? "\u2717" : "\u2022"}
                    </span>
                    <span className="text-muted-darker">
                      <span className="text-muted-dark">{check.label}:</span> {check.detail}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="text-[9px] text-muted-darker">
        Checks: DCT histogram periodicity (combing pattern), Benford{"'"}s law on DCT coefficients,
        GOP structure + DFT periodicity, x264 SEI UUID, encoder identification via MediaInfo
      </div>
    </div>
  );
}

// ─── Provenance Layer Detail ───
function ProvenanceDetail({ data }) {
  if (data.error) return <div className="text-[11px] text-red-400 p-3">{data.error}</div>;
  var summary = data.summary || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <StatMini value={summary.clean || 0} label="Clean" color="#22c55e" />
        <StatMini value={summary.flagged || 0} label="AI flagged" color={summary.flagged > 0 ? "#ef4444" : "#22c55e"} />
        <StatMini value={summary.passRate + "%"} label="Pass rate" color={summary.passRate >= 90 ? "#22c55e" : "#ef4444"} />
      </div>
      {summary.flagged > 0 && (
        <div className="text-[10px] text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
          {summary.flagged} file(s) contain AI generation metadata. Review provenance requirements before publishing.
        </div>
      )}
      {data.results && data.results.length > 0 && (
        <div className="max-h-[160px] overflow-y-auto rounded border border-border">
          {data.results.map((r, i) => (
            <div key={r.file} className={"px-3 py-1.5 border-b border-border last:border-b-0 flex items-center justify-between " + (i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]")}>
              <span className="text-[9px] text-muted-dark font-mono truncate max-w-[200px]">{r.file}</span>
              <span className={"text-[9px] font-mono " + (r.flagged ? "text-red-400" : "text-green")}>
                {r.flagged ? "AI detected" : "Clean"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Reference Database Layer Detail ───
function ReferenceDetail({ data }) {
  if (data.error && !data.results) {
    return (
      <div className="p-3 flex flex-col gap-2">
        <div className="text-[10px] text-amber bg-amber/10 border border-amber/20 rounded-lg px-3 py-2">
          {data.error}
        </div>
        <div className="text-[9px] text-muted-darker">
          Add published content to the reference index via the API: POST /api/reference with a directory path or upload reference images.
        </div>
      </div>
    );
  }
  var stats = data.stats || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-2">
        <StatMini value={stats.pass || 0} label="Unique" color="#22c55e" />
        <StatMini value={stats.warn || 0} label="Similar" color="#eab308" />
        <StatMini value={stats.fail || 0} label="Duplicate" color={stats.fail > 0 ? "#ef4444" : "#22c55e"} />
        <StatMini value={data.totalInIndex || 0} label="In index" color="#c8c8d0" />
      </div>
      {data.results && data.results.length > 0 && (
        <div className="max-h-[200px] overflow-y-auto rounded border border-border">
          {data.results.map((r, i) => (
            <div key={r.file} className={"px-3 py-2 border-b border-border last:border-b-0 " + (i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]")}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[9px] text-muted-dark font-mono truncate max-w-[180px]">{r.file}</span>
                <VerdictBadge verdict={r.verdict} />
              </div>
              {r.sscdMatches && r.sscdMatches.length > 0 && (
                <div className="text-[9px] text-muted-darker">
                  Closest: <span className="text-muted-dark">{r.sscdMatches[0].refFile}</span>
                  {" "}(cosine {r.sscdMatches[0].similarity.toFixed(3)})
                  {r.pdqMinDistance != null && <span> | PDQ {r.pdqMinDistance}/256</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="text-[9px] text-muted-darker">
        Add published content: POST /api/reference {"\u00B7"} Upload reference images or point to a directory
      </div>
    </div>
  );
}

// ─── Temporal PDQ Layer Detail ───
function TemporalDetail({ data }) {
  if (!data.available) return <div className="text-[11px] text-muted-darker p-3">{data.reason}</div>;
  var stats = data.stats || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-2">
        <StatMini value={stats.passCount || 0} label="Unique" color="#22c55e" />
        <StatMini value={stats.warnCount || 0} label="Similar" color="#eab308" />
        <StatMini value={stats.failCount || 0} label="Match" color={stats.failCount > 0 ? "#ef4444" : "#22c55e"} />
        <StatMini value={stats.avgSimilarity != null ? stats.avgSimilarity.toFixed(3) : "--"} label="Avg temporal sim" color="#c8c8d0" />
      </div>
      <div className="text-[9px] text-muted-darker flex items-center gap-2">
        <span>{"< 0.70 = pass"}</span><span>|</span>
        <span>{"0.70-0.90 = warn"}</span><span>|</span>
        <span>{">= 0.90 = temporal match"}</span><span>|</span>
        <span>{stats.sourceFrames || 0} source frames analyzed</span>
      </div>
      {data.results && data.results.length > 0 && (
        <div className="max-h-[160px] overflow-y-auto rounded border border-border">
          <table className="w-full">
            <tbody>
              {data.results.map((r, i) => (
                <tr key={r.name} className={i % 2 === 0 ? "bg-[#0a0a10]" : "bg-[#0c0c14]"}>
                  <td className="px-2 py-1.5 text-[9px] text-muted-dark font-mono truncate max-w-[160px]">{r.name}</td>
                  <td className="px-2 py-1.5 text-right">
                    {r.similarity != null ? (
                      <span className="text-[10px] font-mono" style={{ color: r.verdict === "pass" ? "#22c55e" : r.verdict === "warn" ? "#eab308" : "#ef4444" }}>
                        {r.similarity.toFixed(3)}
                      </span>
                    ) : (
                      <span className="text-[9px] text-muted-darker">{r.error || "--"}</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-[9px] text-muted-darker">
                    {r.sequenceStats ? "avg " + r.sequenceStats.avgFrameDistance.toFixed(0) + "/256" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── SSIM Layer Detail ───
function SSIMDetail({ data }) {
  var stats = data.stats || {};
  return (
    <div className="p-3 flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <StatMini value={stats.avg != null ? stats.avg.toFixed(3) : "--"} label="Avg SSIM" color="#c8c8d0" />
        <StatMini value={stats.min != null ? stats.min.toFixed(3) : "--"} label="Min (worst)" color={stats.min < 0.80 ? "#ef4444" : "#c8c8d0"} />
        <StatMini value={stats.max != null ? stats.max.toFixed(3) : "--"} label="Max (best)" color="#c8c8d0" />
      </div>
      <div className="text-[9px] text-muted-darker">
        SSIM measures visual quality preservation.
        {" > "}0.90 = near-identical quality | 0.80-0.90 = acceptable | {"< "}0.80 = visible degradation
      </div>
    </div>
  );
}

function StatMini({ value, label, color }) {
  return (
    <div className="bg-[#08080c] rounded-lg p-2 text-center border border-border">
      <div className="text-[14px] font-light font-mono" style={{ color }}>{value}</div>
      <div className="text-[8px] text-muted-darker mt-0.5">{label}</div>
    </div>
  );
}

// ─── Main Component ───
export default function SimilarityChecker({ sourcePath, runId }) {
  var [data, setData] = useState(null);
  var [loading, setLoading] = useState(false);
  var [error, setError] = useState(null);
  var [feedbackNote, setFeedbackNote] = useState("");
  var [feedbackStatus, setFeedbackStatus] = useState({});
  var [expanded, setExpanded] = useState({ pdq: true, sscd: true, audio: true, forensics: true, compression: true, provenance: true, reference: true, temporal: false, ssim: false });

  var runCheck = async () => {
    setLoading(true);
    setError(null);
    try {
      var res = await fetch("/api/similarity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: sourcePath,
          runId: runId || "latest",
          layers: ["pdq", "sscd", "audio", "forensics", "compression", "provenance", "reference", "temporal", "ssim", "virality", "videoAnalysis"],
        }),
      });
      if (!res.ok) {
        var errData = await res.json();
        throw new Error(errData.error || "Analysis failed");
      }
      setData(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  var toggleLayer = (key) => {
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }));
  };

  var sendFeedback = async (item, label) => {
    var key = item.code + ":" + label;
    setFeedbackStatus((prev) => ({ ...prev, [key]: "saving" }));
    try {
      var response = await fetch("/api/audit-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: item.code,
          label,
          message: item.message || item.label,
          note: feedbackNote,
          targetFile: data?.targetFile,
          runId,
          auditProfile: data?.auditProfile,
        }),
      });
      var body = await response.json();
      if (!response.ok) throw new Error(body.error || "Feedback failed");
      setFeedbackStatus((prev) => ({ ...prev, [key]: "saved" }));
    } catch (err) {
      setFeedbackStatus((prev) => ({ ...prev, [key]: err.message }));
    }
  };

  // Not yet run
  if (!data && !loading) {
    return (
      <div className="bg-card rounded-card border border-border p-5">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
            Similarity checker
          </span>
          <span className="text-[9px] text-muted-darker font-mono">v2 — multi-layer</span>
        </div>
        <p className="text-[11px] text-muted-dark mb-4 leading-relaxed">
          Pre-publish audit across multiple quality and similarity layers: PDQ hash comparison,
          audio fingerprint comparison, metadata forensics, and visual quality verification.
        </p>
        {error && (
          <div className="text-[11px] text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2 mb-3">{error}</div>
        )}
        <button
          onClick={runCheck}
          className="w-full py-3 px-6 rounded-card border border-purple-dim bg-purple/10
            text-purple text-[12px] font-medium font-mono tracking-[0.02em] cursor-pointer
            hover:bg-purple/20 hover:border-purple transition-all"
        >
          Run pre-publish audit
        </button>
      </div>
    );
  }

  // Loading
  if (loading) {
    return (
      <div className="bg-card rounded-card border border-border p-5">
        <div className="flex items-center justify-between mb-4">
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
            Similarity checker
          </span>
          <span className="text-[10px] text-purple font-mono animate-pulse">Analyzing...</span>
        </div>
        <div className="flex flex-col gap-2">
          {["PDQ hash comparison", "SSCD neural embedding", "Audio fingerprint analysis", "Metadata forensics", "Compression forensics", "AI provenance scan", "Reference DB query", "Temporal PDQ (video)", "SSIM quality"].map((step, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-purple animate-pulse" />
              <span className="text-[10px] text-muted-darker">{step}</span>
            </div>
          ))}
        </div>
        <div className="h-1 bg-[#1c1c24] rounded-full overflow-hidden mt-4">
          <div className="h-full rounded-full animate-pulse" style={{ width: "45%", background: "linear-gradient(90deg, #7c3aed, #a855f7)" }} />
        </div>
      </div>
    );
  }

  // Results
  var overallColor = VERDICT_COLORS[data.overallVerdict] || "#c8c8d0";

  return (
    <div className="bg-card rounded-card border border-border p-5 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
            Pre-publish audit
          </span>
          <span
            className="text-[11px] font-mono font-semibold px-2.5 py-0.5 rounded-full"
            style={{
              color: overallColor,
              background: overallColor + "15",
              border: "1px solid " + overallColor + "40",
            }}
          >
            {data.overallVerdict === "pass" ? "ALL CLEAR" : data.overallVerdict === "warn" ? "WARNINGS" : "ISSUES FOUND"}
          </span>
        </div>
        <button onClick={runCheck} className="text-[9px] text-purple hover:text-purple-light font-mono cursor-pointer bg-transparent border-none">
          Re-run
        </button>
      </div>

      {/* Overall verdicts bar */}
      <div className="flex gap-2">
        {Object.entries(data.verdicts || {}).map(([key, verdict]) => (
          <div key={key} className="flex-1 bg-[#0a0a10] rounded-lg p-2 text-center border border-border">
            <div className="text-[9px] text-muted-darker mb-1">{LAYER_INFO[key]?.label || key}</div>
            <VerdictBadge verdict={verdict} />
          </div>
        ))}
      </div>

      {data.readinessSummary?.topWarnings?.length > 0 && (
        <div className="bg-[#08080c] rounded-card border border-border p-4">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <div>
              <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
                Operator feedback
              </div>
              <div className="text-[10px] text-muted-darker mt-1">
                Mark whether warnings are useful so calibration reports can surface noisy rules.
              </div>
            </div>
            <input
              value={feedbackNote}
              onChange={(event) => setFeedbackNote(event.target.value)}
              placeholder="optional note"
              className="bg-[#0c0c14] border border-border rounded-md px-2 py-2 text-[10px] text-muted min-w-[220px]"
            />
          </div>
          <div className="flex flex-col gap-2">
            {data.readinessSummary.topWarnings.map((item) => (
              <div key={item.code + item.message} className="rounded-lg border border-border bg-[#0c0c14] p-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-[10px] text-[#d7d7df] font-mono">{item.code}</div>
                    <div className="text-[10px] text-muted-darker mt-1">{item.message || item.label}</div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {[
                      ["useful", "Useful"],
                      ["false_positive", "False +"],
                      ["too_strict", "Too strict"],
                      ["missed_issue", "Missed"],
                    ].map(([label, text]) => {
                      var status = feedbackStatus[item.code + ":" + label];
                      return (
                        <button
                          key={label}
                          onClick={() => sendFeedback(item, label)}
                          className="rounded-md border border-border bg-[#08080c] px-2 py-1 text-[9px] text-muted font-mono hover:border-purple-dim hover:text-purple"
                        >
                          {status === "saved" ? "Saved" : text}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Layer details */}
      <div className="flex flex-col gap-2">
        {data.layers?.pdq && (
          <div>
            <LayerHeader layerKey="pdq" verdict={data.verdicts?.pdq} expanded={expanded.pdq} onToggle={() => toggleLayer("pdq")} />
            {expanded.pdq && <PDQDetail data={data.layers.pdq} />}
          </div>
        )}
        {data.layers?.sscd && (
          <div>
            <LayerHeader layerKey="sscd" verdict={data.verdicts?.sscd} expanded={expanded.sscd} onToggle={() => toggleLayer("sscd")} />
            {expanded.sscd && <SSCDDetail data={data.layers.sscd} />}
          </div>
        )}
        {data.layers?.audio && (
          <div>
            <LayerHeader layerKey="audio" verdict={data.verdicts?.audio} expanded={expanded.audio} onToggle={() => toggleLayer("audio")} />
            {expanded.audio && <AudioDetail data={data.layers.audio} />}
          </div>
        )}
        {data.layers?.forensics && (
          <div>
            <LayerHeader layerKey="forensics" verdict={data.verdicts?.forensics} expanded={expanded.forensics} onToggle={() => toggleLayer("forensics")} />
            {expanded.forensics && <ForensicsDetail data={data.layers.forensics} />}
          </div>
        )}
        {data.layers?.compression && (
          <div>
            <LayerHeader layerKey="compression" verdict={data.verdicts?.compression} expanded={expanded.compression} onToggle={() => toggleLayer("compression")} />
            {expanded.compression && <CompressionDetail data={data.layers.compression} />}
          </div>
        )}
        {data.layers?.provenance && (
          <div>
            <LayerHeader layerKey="provenance" verdict={data.verdicts?.provenance} expanded={expanded.provenance} onToggle={() => toggleLayer("provenance")} />
            {expanded.provenance && <ProvenanceDetail data={data.layers.provenance} />}
          </div>
        )}
        {data.layers?.reference && (
          <div>
            <LayerHeader layerKey="reference" verdict={data.verdicts?.reference} expanded={expanded.reference} onToggle={() => toggleLayer("reference")} />
            {expanded.reference && <ReferenceDetail data={data.layers.reference} />}
          </div>
        )}
        {data.layers?.temporal && (
          <div>
            <LayerHeader layerKey="temporal" verdict={data.verdicts?.temporal} expanded={expanded.temporal} onToggle={() => toggleLayer("temporal")} />
            {expanded.temporal && <TemporalDetail data={data.layers.temporal} />}
          </div>
        )}
        {data.layers?.ssim && (
          <div>
            <LayerHeader layerKey="ssim" verdict={data.verdicts?.ssim} expanded={expanded.ssim} onToggle={() => toggleLayer("ssim")} />
            {expanded.ssim && <SSIMDetail data={data.layers.ssim} />}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="text-[8px] text-[#1e1e28] text-center pt-1">
        PDQ via Meta{"'"}s pdqhash {"\u00B7"} SSCD via Meta{"'"}s copy detection model {"\u00B7"} Audio via Chromaprint {"\u00B7"} Forensics via ffprobe + MediaInfo {"\u00B7"} {data.filesAnalyzed} files analyzed
      </div>
    </div>
  );
}
