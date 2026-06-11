"use client";

import { useEffect, useState } from "react";
import CoverFramePicker from "./CoverFramePicker";
import SafeZonePreview from "./SafeZonePreview";

var PROFILES = [
  { id: "organic", label: "Organic Reels" },
  { id: "boosted", label: "Boosted Reels" },
  { id: "highQuality", label: "High Quality Reels" },
];

var STATUS_COLOR = {
  pass: "#22c55e",
  warn: "#eab308",
  fail: "#ef4444",
};

function StatusDot({ status }) {
  return <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: STATUS_COLOR[status] || "#52525b" }} />;
}

function Stat({ label, value }) {
  return (
    <div className="bg-[#08080c] rounded-lg border border-border p-3">
      <div className="text-[9px] text-muted-darker uppercase tracking-[0.08em]">{label}</div>
      <div className="text-[13px] text-[#d7d7df] font-mono mt-1 truncate">{value || "--"}</div>
    </div>
  );
}

export default function ReelsReadinessPanel({ runId, mediaType, sourceFile }) {
  var [profileId, setProfileId] = useState("organic");
  var [data, setData] = useState(null);
  var [loading, setLoading] = useState(false);
  var [error, setError] = useState(null);

  var analyze = async () => {
    if (!runId || runId === "latest" || mediaType === "image") return;
    setLoading(true);
    setError(null);
    try {
      var res = await fetch("/api/reels/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runId, profileId, sourceFile }),
      });
      var next = await res.json();
      if (!res.ok) throw new Error(next.error || "Analyze failed");
      setData(next);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    analyze();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, profileId, mediaType, sourceFile]);

  if (mediaType === "image") return null;

  var mediaInfo = data?.mediaInfo || {};
  var qa = data?.qaSignals || {};
  var checks = data?.checks || [];
  var uploadCaptions = async (event) => {
    var file = event.target.files?.[0];
    if (!file || !runId) return;
    var form = new FormData();
    form.append("runId", runId);
    form.append("file", file);
    setLoading(true);
    setError(null);
    try {
      var res = await fetch("/api/reels/captions", { method: "POST", body: form });
      var next = await res.json();
      if (!res.ok) throw new Error(next.error || "Caption upload failed");
      await analyze();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  };

  return (
    <div className="bg-card rounded-card border border-border p-5 flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block">
            Reels readiness
          </span>
          <div className="text-[11px] text-muted-darker mt-1 font-mono">
            {data ? data.analyzedFile : "Analyze current run"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={profileId}
            onChange={(e) => setProfileId(e.target.value)}
            className="bg-[#08080c] border border-border rounded-md text-[11px] text-muted px-2 py-2"
          >
            {PROFILES.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          <button
            onClick={analyze}
            disabled={loading}
            className="px-3 py-2 rounded-md bg-purple/10 border border-purple-dim text-purple text-[10px] font-mono cursor-pointer disabled:opacity-50"
          >
            {loading ? "Checking..." : "Re-run"}
          </button>
          <a
            href={data ? "/api/reels/manifest?runId=" + encodeURIComponent(runId) + "&format=json" : "#"}
            className="px-3 py-2 rounded-md bg-[#08080c] border border-border text-muted text-[10px] font-mono cursor-pointer"
          >
            JSON
          </a>
          <a
            href={data ? "/api/reels/manifest?runId=" + encodeURIComponent(runId) + "&format=csv" : "#"}
            className="px-3 py-2 rounded-md bg-[#08080c] border border-border text-muted text-[10px] font-mono cursor-pointer"
          >
            CSV
          </a>
          <label className="px-3 py-2 rounded-md bg-[#08080c] border border-border text-muted text-[10px] font-mono cursor-pointer">
            SRT
            <input type="file" accept=".srt" onChange={uploadCaptions} className="hidden" />
          </label>
        </div>
      </div>

      {error && <div className="text-[11px] text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">{error}</div>}

      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Stat label="Score" value={data.score + "%"} />
            <Stat label="Preset" value={data.variantPreset || "--"} />
            <Stat label="Resolution" value={(mediaInfo.width || 0) + "x" + (mediaInfo.height || 0)} />
            <Stat label="FPS" value={mediaInfo.fps ? mediaInfo.fps.toFixed(2) : "--"} />
            <Stat label="Codec" value={mediaInfo.videoCodec} />
          </div>

          {data.variantReports?.length > 1 && (
            <div className="overflow-x-auto border border-border rounded-card">
              <table className="w-full text-left text-[11px]">
                <thead className="bg-[#08080c] text-muted-dark uppercase text-[9px]">
                  <tr>
                    <th className="p-2">File</th>
                    <th className="p-2">Score</th>
                    <th className="p-2">Quality</th>
                    <th className="p-2">Difference</th>
                    <th className="p-2">Action</th>
                    <th className="p-2">Resolution</th>
                    <th className="p-2">FPS</th>
                    <th className="p-2">VMAF</th>
                    <th className="p-2">SSIM</th>
                    <th className="p-2">PSNR</th>
                    <th className="p-2">Captions</th>
                    <th className="p-2">Warnings</th>
                  </tr>
                </thead>
                <tbody>
                  {data.variantReports.map((report) => (
                    <tr key={report.file} className="border-t border-border">
                      <td className="p-2 font-mono text-muted">{report.file}</td>
                      <td className="p-2 text-purple">{report.score}%</td>
                      <td className="p-2 text-green">{report.qualityRetained ?? "--"}%</td>
                      <td className="p-2 text-purple">{report.differenceFromOriginal ?? "--"}%</td>
                      <td className="p-2 text-muted">{report.recommendedAction || "--"}</td>
                      <td className="p-2 text-muted">{report.mediaInfo.width}x{report.mediaInfo.height}</td>
                      <td className="p-2 text-muted">{report.mediaInfo.fps ? report.mediaInfo.fps.toFixed(2) : "--"}</td>
                      <td className="p-2 text-muted">{report.qualityMetrics?.vmaf ? report.qualityMetrics.vmaf.toFixed(1) : "--"}</td>
                      <td className="p-2 text-muted">{report.qualityMetrics?.ssim ? report.qualityMetrics.ssim.toFixed(3) : "--"}</td>
                      <td className="p-2 text-muted">{report.qualityMetrics?.psnr ? report.qualityMetrics.psnr.toFixed(1) : "--"}</td>
                      <td className="p-2 text-muted">{report.captions?.available ? report.captions.summary.cues : "--"}</td>
                      <td className="p-2 text-amber">{report.qaSignals.warnings.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="flex flex-col gap-2">
              {checks.map((item) => (
                <div key={item.id} className="bg-[#08080c] rounded-lg border border-border p-3 flex items-start gap-3">
                  <div className="pt-1"><StatusDot status={item.status} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex justify-between gap-3">
                      <span className="text-[11px] text-[#d7d7df] font-medium">{item.label}</span>
                      <span className="text-[9px] text-muted-darker font-mono truncate">{item.actual}</span>
                    </div>
                    <div className="text-[9px] text-muted-darker mt-1">{item.message}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-3">
              <SafeZonePreview runId={runId} file={data.analyzedFile} />
              <div className="bg-[#08080c] rounded-card border border-border p-4">
                <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
                  QA signals
                </span>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Black spans" value={(qa.blackFrames || []).length} />
                  <Stat label="Silence spans" value={(qa.silence || []).length} />
                  <Stat label="Letterbox" value={qa.letterbox ? "Possible" : "No"} />
                  <Stat label="Loudness" value={qa.loudness?.inputI ? qa.loudness.inputI + " LUFS" : "--"} />
                </div>
                {qa.warnings?.length > 0 && (
                  <div className="mt-3 flex flex-col gap-1">
                    {qa.warnings.map((warning) => (
                      <div key={warning} className="text-[9px] text-amber">{warning}</div>
                    ))}
                  </div>
                )}
                {data.captions && (
                  <div className="mt-3 border-t border-border pt-3">
                    <div className="text-[9px] text-muted-darker uppercase tracking-[0.08em] mb-2">
                      Caption checks
                    </div>
                    <div className="flex flex-col gap-1">
                      {data.captions.checks.map((item) => (
                        <div key={item.id} className="flex items-center justify-between gap-2 text-[9px]">
                          <span className="text-muted">{item.label}</span>
                          <span className={item.status === "pass" ? "text-green" : item.status === "fail" ? "text-red-400" : "text-amber"}>{item.actual}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          <CoverFramePicker
            runId={runId}
            file={data.analyzedFile}
            duration={mediaInfo.duration}
            covers={data.coverFrames}
            onCoverCreated={(cover) => setData((prev) => ({ ...prev, coverFrames: [cover, ...(prev.coverFrames || [])] }))}
          />
        </>
      )}
    </div>
  );
}
