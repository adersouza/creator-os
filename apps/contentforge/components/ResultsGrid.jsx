"use client";

import { useState, useEffect, useRef } from "react";
import { DAYS } from "../lib/presets";
import SourceVariantPreview from "./SourceVariantPreview";

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "--";
  if (bytes > 1e6) return (bytes / 1e6).toFixed(1) + " MB";
  return (bytes / 1e3).toFixed(0) + " KB";
}

function VideoPreview({ file, index, runId }) {
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef(null);

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (playing) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setPlaying(!playing);
  };

  const downloadFile = (e) => {
    e.stopPropagation();
    window.location.href = "/api/download?runId=" + encodeURIComponent(runId || "latest") + "&file=" + encodeURIComponent(file.name);
  };

  return (
    <div className="bg-[#0a0a10] rounded-lg border border-border overflow-hidden group">
      <div
        className="relative aspect-[9/16] cursor-pointer bg-black"
        onClick={togglePlay}
      >
        <video
          ref={videoRef}
          src={"/api/preview?runId=" + encodeURIComponent(runId || "latest") + "&file=" + encodeURIComponent(file.name)}
          className="w-full h-full object-cover"
          loop
          muted
          playsInline
          preload="metadata"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        {!playing && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30">
            <div className="w-10 h-10 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="white">
                <polygon points="4,2 14,8 4,14" />
              </svg>
            </div>
          </div>
        )}
        <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded text-[9px] font-mono text-white/70">
          #{index + 1}
        </div>
      </div>
      <FileInfo file={file} onDownload={downloadFile} />
    </div>
  );
}

function ImagePreview({ file, index, runId }) {
  const downloadFile = (e) => {
    e.stopPropagation();
    window.location.href = "/api/download?runId=" + encodeURIComponent(runId || "latest") + "&file=" + encodeURIComponent(file.name);
  };

  return (
    <div className="bg-[#0a0a10] rounded-lg border border-border overflow-hidden group">
      <div className="relative aspect-square cursor-pointer bg-black">
        <img
          src={"/api/preview?runId=" + encodeURIComponent(runId || "latest") + "&file=" + encodeURIComponent(file.name)}
          alt={`Variant #${index + 1}`}
          className="w-full h-full object-cover"
          loading="lazy"
        />
        <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded text-[9px] font-mono text-white/70">
          #{index + 1}
        </div>
      </div>
      <FileInfo file={file} onDownload={downloadFile} />
    </div>
  );
}

function FileInfo({ file, onDownload }) {
  return (
    <div className="p-2.5 flex items-center justify-between">
      <div className="min-w-0 flex-1">
        <div className="text-[10px] text-muted-dark font-mono truncate">
          {file.name}
        </div>
        <div className="text-[9px] text-muted-darker mt-0.5">
          {formatSize(file.size)}
        </div>
      </div>
      <button
        onClick={onDownload}
        className="ml-2 shrink-0 w-7 h-7 rounded-md bg-[#16161e] hover:bg-purple/20 border border-border
          hover:border-purple-dim flex items-center justify-center transition-all cursor-pointer"
        title="Download"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#a855f7" strokeWidth="1.5">
          <path d="M6 1v7M3 6l3 3 3-3M2 10h8" />
        </svg>
      </button>
    </div>
  );
}

function BatchRunSummary({ result }) {
  if (!result?.batch || !Array.isArray(result.results) || result.results.length === 0) return null;
  var total = result.results.reduce((sum, item) => sum + (item.total || 0), 0);
  var attempted = result.results.reduce((sum, item) => sum + (item.attemptedCandidates || 0), 0);
  var rejected = result.results.reduce((sum, item) => sum + (item.rejectedCandidates || 0), 0);
  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between gap-3 mb-3">
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
          Batch runs
        </span>
        <span className="text-[10px] text-muted-darker">
          {result.results.length} sources · {total} outputs · {attempted} attempted · {rejected} rejected
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {result.results.map((run, index) => (
          <div key={run.runId || index} className="rounded-lg border border-border bg-[#08080c] p-3 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] text-muted-dark uppercase tracking-[0.08em]">Source {index + 1}</div>
              <div className="text-[12px] text-[#d7d7df] font-mono truncate">{run.runId || "unknown"}</div>
              <div className="text-[9px] text-muted-darker mt-1">
                {run.total || 0} kept · {run.attemptedCandidates || 0} attempted · {run.rejectedCandidates || 0} rejected · {run.elapsed || "--"}
              </div>
            </div>
            {run.runId && (
              <div className="flex items-center gap-2">
                <a href={"/api/download?all=true&runId=" + encodeURIComponent(run.runId)} className="px-2 py-1 rounded-md bg-[#111118] border border-border text-[9px] text-muted font-mono">
                  ZIP
                </a>
                <a href={"/api/reels/manifest?runId=" + encodeURIComponent(run.runId) + "&format=json"} className="px-2 py-1 rounded-md bg-[#111118] border border-border text-[9px] text-muted font-mono">
                  JSON
                </a>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ResultsGrid({ config, forgeResult, mediaType, sourceFile }) {
  const isImage = mediaType === "image";
  const [files, setFiles] = useState([]);
  const [scores, setScores] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const runId = forgeResult?.runId || "latest";
  const total = isImage ? (config.variants || 50) : config.edits * config.spins;
  const pods = Math.min(5, Math.ceil(total / 10));

  useEffect(() => {
    async function loadFiles() {
      try {
        const res = await fetch("/api/scan-output?runId=" + encodeURIComponent(runId));
        if (res.ok) {
          const data = await res.json();
          setFiles(data.files || []);
        }
      } catch (e) {
        // ignore
      }
    }
    loadFiles();
  }, [forgeResult, runId]);

  useEffect(() => {
    async function loadScores() {
      if (!forgeResult?.runId) return;
      try {
        const res = await fetch("/api/detector", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ runId: forgeResult.runId, threshold: 0.92, sourceFile }),
        });
        if (res.ok) setScores(await res.json());
      } catch (e) {
        // scoring is optional for the preview grid
      }
    }
    loadScores();
  }, [forgeResult, sourceFile]);

  const downloadAll = async () => {
    setDownloading(true);
    try {
      const res = await fetch("/api/download?all=true&runId=" + encodeURIComponent(runId));
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "contentforge_variants.zip";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Download failed: " + e.message);
    } finally {
      setDownloading(false);
    }
  };

  // Filter files by type for display
  const displayFiles = isImage
    ? files.filter(f => f.type === "image")
    : files.filter(f => f.type === "video");

  return (
    <div className="flex flex-col gap-6">
      <BatchRunSummary result={forgeResult} />

      {/* Summary stats */}
      <div
        className="bg-card rounded-card border border-green-dim p-6"
        style={{ background: "linear-gradient(135deg, #0c0c12, #0a140e)" }}
      >
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4 text-center">
          <div>
            <div className="text-2xl font-light text-green font-mono">
              {displayFiles.length || forgeResult?.total || total}
            </div>
            <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
              Variants
            </div>
          </div>
          <div>
            <div className="text-2xl font-light text-amber font-mono">
              {forgeResult?.attemptedCandidates ?? "--"}
            </div>
            <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
              Attempted
            </div>
          </div>
          <div>
            <div className="text-2xl font-light text-red-400 font-mono">
              {forgeResult?.rejectedCandidates ?? 0}
            </div>
            <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
              Rejected
            </div>
          </div>
          <div>
            <div className="text-2xl font-light text-[#c8c8d0] font-mono">
              {forgeResult?.elapsed || "--"}
            </div>
            <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
              Total time
            </div>
          </div>
          <div>
            <div className="text-2xl font-light text-purple font-mono">
              {isImage ? "1" : pods}
            </div>
            <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
              {isImage ? "Source" : "Pods"}
            </div>
          </div>
          <div>
            <div className="text-2xl font-light text-green font-mono">$0</div>
            <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
              Cost
            </div>
          </div>
        </div>
      </div>

      {/* Preview grid */}
      {displayFiles.length > 0 && (
        <div>
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
              Preview variants ({displayFiles.length})
            </span>
            <span className="text-[10px] text-muted-darker">
              {isImage ? "Click to preview \u00B7 Hover for download" : "Click to play \u00B7 Hover for download"}
            </span>
          </div>
          <div className={`grid gap-3 ${
            isImage
              ? "grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6"
              : "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5"
          }`}>
            {displayFiles.map((file, i) =>
              file.type === "image" ? (
                <ImagePreview key={file.name} file={file} index={i} runId={runId} />
              ) : (
                <VideoPreview key={file.name} file={file} index={i} runId={runId} />
              )
            )}
          </div>
        </div>
      )}

      <SourceVariantPreview sourceFile={sourceFile} files={displayFiles} runId={runId} mediaType={mediaType} />

      {scores?.files?.length > 0 && (
        <div className="bg-card rounded-card border border-border p-5">
          <div className="flex justify-between items-center mb-3">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
              Variant score table
            </span>
            <span className="text-[10px] text-muted-darker">
              Quality retained {"\u00B7"} Difference from original
            </span>
          </div>
          <div className="overflow-x-auto border border-border rounded-card">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-[#08080c] text-muted-dark uppercase text-[9px]">
                <tr>
                  <th className="p-2">File</th>
                  <th className="p-2">Quality</th>
                  <th className="p-2">Difference</th>
                  <th className="p-2">Max variant sim</th>
                  <th className="p-2">Size</th>
                  <th className="p-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {scores.files.filter((file) => file.bucket !== "source").map((file) => (
                  <tr key={file.name} className="border-t border-border">
                    <td className="p-2 font-mono text-muted">{file.name}</td>
                    <td className="p-2 text-green">{file.qualityRetained ?? "--"}%</td>
                    <td className="p-2 text-purple">{file.differenceFromOriginal ?? "--"}%</td>
                    <td className="p-2 text-amber">{Math.round((file.maxCrossVariantSimilarity || 0) * 100)}%</td>
                    <td className="p-2 text-muted">{formatSize(file.size)}</td>
                    <td className="p-2 text-muted">{file.recommendedAction || "--"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Batch grouping — video only */}
      {!isImage && (
        <div className="bg-card rounded-card border border-border p-5">
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
            Batch groups
          </span>
          <div
            className="grid gap-2"
            style={{ gridTemplateColumns: "repeat(" + pods + ", 1fr)" }}
          >
            {Array.from({ length: pods }, (_, p) => {
              const perPod = Math.ceil(total / pods);
              const s = p * perPod + 1;
              const e = Math.min((p + 1) * perPod, total);
              return (
                <div
                  key={p}
                  className="bg-[#0a0a10] rounded-[10px] p-3 text-center border border-border"
                >
                  <div className="text-[10px] text-amber font-medium">
                    {DAYS[p % 5]}
                  </div>
                  <div className="text-lg font-light text-[#c8c8d0] my-1 font-mono">
                    {e - s + 1}
                  </div>
                  <div className="text-[9px] text-muted-dark">Pod {p + 1}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Image batch info */}
      {isImage && displayFiles.length > 0 && (
        <div className="bg-card rounded-card border border-border p-5">
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
            Image batch
          </span>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="bg-[#0a0a10] rounded-[10px] p-3 border border-border">
              <div className="text-lg font-light text-amber my-1 font-mono">
                {displayFiles.length}
              </div>
              <div className="text-[9px] text-muted-dark">Images</div>
            </div>
            <div className="bg-[#0a0a10] rounded-[10px] p-3 border border-border">
              <div className="text-lg font-light text-green my-1 font-mono">
                {displayFiles.length}
              </div>
              <div className="text-[9px] text-muted-dark">Selected outputs</div>
            </div>
            <div className="bg-[#0a0a10] rounded-[10px] p-3 border border-border">
              <div className="text-lg font-light text-purple my-1 font-mono">
                0%
              </div>
              <div className="text-[9px] text-muted-dark">Warnings</div>
            </div>
          </div>
        </div>
      )}

      {/* Download actions */}
      <div className="flex gap-3">
        <button
          onClick={downloadAll}
          disabled={downloading || displayFiles.length === 0}
          className={
            "flex-1 py-4 px-6 rounded-card border-none text-white text-[13px] font-medium font-mono " +
            "tracking-[0.02em] cursor-pointer transition-all " +
            (downloading ? "opacity-50" : "")
          }
          style={{
            background: "linear-gradient(135deg, #7c3aed, #6d28d9)",
            boxShadow: "0 8px 32px rgba(124, 58, 237, 0.2)",
          }}
        >
          {downloading
            ? "Zipping..."
            : "Download all " + displayFiles.length + " variants (.zip)"}
        </button>
      </div>
    </div>
  );
}
