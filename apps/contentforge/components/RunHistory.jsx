"use client";

import { useEffect, useState } from "react";

function formatSize(bytes) {
  if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + " GB";
  if (bytes > 1e6) return (bytes / 1e6).toFixed(1) + " MB";
  if (bytes > 1e3) return Math.round(bytes / 1e3) + " KB";
  return (bytes || 0) + " B";
}

export default function RunHistory({ currentRunId, expanded = false }) {
  var [runs, setRuns] = useState([]);
  var [busy, setBusy] = useState(false);
  var [olderThanDays, setOlderThanDays] = useState(14);
  var [maxGb, setMaxGb] = useState("");

  var loadRuns = async () => {
    try {
      var res = await fetch("/api/runs");
      var data = await res.json();
      if (res.ok) setRuns(data.runs || []);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadRuns();
  }, [currentRunId]);

  var deleteRun = async (runId) => {
    setBusy(true);
    try {
      await fetch("/api/runs?runId=" + encodeURIComponent(runId), { method: "DELETE" });
      await loadRuns();
    } finally {
      setBusy(false);
    }
  };

  var cleanup = async () => {
    setBusy(true);
    try {
      await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          olderThanDays: Math.max(1, parseInt(olderThanDays, 10) || 14),
          maxBytes: maxGb ? Math.max(0, Math.round((parseFloat(maxGb) || 0) * 1024 * 1024 * 1024)) : 0,
        }),
      });
      await loadRuns();
    } finally {
      setBusy(false);
    }
  };

  if (runs.length === 0) return null;

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
          Run history
        </span>
        <div className="flex items-center gap-2">
          {expanded && (
            <>
              <input
                type="number"
                min={1}
                max={365}
                value={olderThanDays}
                onChange={(e) => setOlderThanDays(e.target.value)}
                className="w-14 bg-[#08080c] border border-border rounded-md px-2 py-1 text-[9px] text-muted font-mono"
                title="Age in days"
              />
              <input
                type="number"
                min={0}
                step={0.5}
                value={maxGb}
                onChange={(e) => setMaxGb(e.target.value)}
                className="w-16 bg-[#08080c] border border-border rounded-md px-2 py-1 text-[9px] text-muted font-mono"
                placeholder="GB"
                title="Storage cap in GB"
              />
            </>
          )}
          <button
            onClick={cleanup}
            disabled={busy}
            className="text-[9px] text-purple hover:text-purple-light font-mono cursor-pointer bg-transparent border-none disabled:opacity-40"
          >
            Cleanup
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-2 max-h-[240px] overflow-y-auto">
        {runs.map((run) => (
          <div key={run.runId} className={"rounded-lg border p-3 flex items-center justify-between gap-3 " + (run.runId === currentRunId ? "border-purple-dim bg-purple/5" : "border-border bg-[#08080c]")}>
            <div className="min-w-0">
              <div className="text-[11px] text-[#d7d7df] font-mono">{run.runId}</div>
              <div className="text-[9px] text-muted-darker mt-1">
                {run.count} files · {formatSize(run.size)} · {new Date(run.created).toLocaleString()}
                {run.score ? " · " + run.score + "% · " + run.profileId : ""}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {expanded && (
                <>
                  <a href={"/api/download?all=true&runId=" + encodeURIComponent(run.runId)} className="px-2 py-1 rounded-md bg-[#111118] border border-border text-[9px] text-muted font-mono">
                    ZIP
                  </a>
                  <a href={"/api/reels/manifest?runId=" + encodeURIComponent(run.runId) + "&format=json"} className="px-2 py-1 rounded-md bg-[#111118] border border-border text-[9px] text-muted font-mono">
                    JSON
                  </a>
                  <a href={"/api/reels/manifest?runId=" + encodeURIComponent(run.runId) + "&format=csv"} className="px-2 py-1 rounded-md bg-[#111118] border border-border text-[9px] text-muted font-mono">
                    CSV
                  </a>
                </>
              )}
              <button
                onClick={() => deleteRun(run.runId)}
                disabled={busy || run.runId === currentRunId}
                className="px-2 py-1 rounded-md bg-[#111118] border border-border text-[9px] text-muted font-mono cursor-pointer disabled:opacity-30"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
