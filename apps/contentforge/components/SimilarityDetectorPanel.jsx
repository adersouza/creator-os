"use client";

import { useState } from "react";

export default function SimilarityDetectorPanel({ runId, sourceFile }) {
  var [threshold, setThreshold] = useState(0.92);
  var [data, setData] = useState(null);
  var [selected, setSelected] = useState({});
  var [busy, setBusy] = useState(false);
  var [error, setError] = useState("");

  var analyze = async () => {
    if (!runId) return;
    setBusy(true);
    setError("");
    try {
      var res = await fetch("/api/detector", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runId, threshold, sourceFile }),
      });
      if (!res.ok) throw new Error(await res.text());
      setData(await res.json());
      setSelected({});
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  var deleteSelected = async () => {
    var files = Object.keys(selected).filter((key) => selected[key]);
    if (files.length === 0) return;
    setBusy(true);
    try {
      await fetch("/api/detector", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runId, files }),
      });
      await analyze();
    } finally {
      setBusy(false);
    }
  };

  var selectedFiles = Object.keys(selected).filter((key) => selected[key]);
  var includedFiles = data?.files
    ?.filter((file) => file.bucket !== "source" && !selected[file.name])
    .map((file) => file.name) || [];

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between gap-4 mb-4">
        <div>
          <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
            Detector
          </div>
          <div className="text-[12px] text-muted mt-1">
            Similarity buckets for the current output run.
          </div>
        </div>
        <button disabled={!runId || busy} onClick={analyze} className="rounded-md border border-purple-dim bg-purple/10 px-3 py-2 text-[10px] text-purple font-mono disabled:opacity-40">
          Analyze
        </button>
      </div>
      <label className="block text-[10px] text-muted-dark uppercase tracking-[0.1em] mb-2">
        Threshold {Math.round(threshold * 100)}%
      </label>
      <input type="range" min={0.75} max={0.99} step={0.01} value={threshold} onChange={(e) => setThreshold(+e.target.value)} />
      {error && <div className="text-[11px] text-red-400 mt-3">{error}</div>}
      {data && (
        <div className="mt-4">
          {data.layers && (
            <div className="flex flex-wrap gap-2 mb-3">
              {Object.entries(data.layers).map(([key, layer]) => (
                <span key={key} className={"px-2 py-1 rounded-md border text-[9px] font-mono " + (layer.available ? "border-green-dim bg-green/10 text-green" : "border-border bg-[#08080c] text-muted-dark")}>
                  {layer.label}: {layer.available ? "ready" : layer.reason}
                </span>
              ))}
            </div>
          )}
          <div className="grid grid-cols-3 gap-2 mb-3">
            {["duplicate", "similar", "unique"].map((key) => (
              <div key={key} className="rounded-md border border-border bg-[#08080c] p-3">
                <div className="text-[9px] text-muted-dark uppercase">{key}</div>
                <div className="text-[20px] text-[#e8e8ec] font-mono">{data.summary[key]}</div>
              </div>
            ))}
          </div>
          <div className="rounded-md border border-border bg-[#08080c] p-3 mb-3">
            <div className="text-[9px] text-muted-dark uppercase">Original source</div>
            <div className="text-[11px] text-muted font-mono mt-1">{data.sourceFile || data.source}</div>
          </div>
          <div className="overflow-x-auto border border-border rounded-card">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-[#08080c] text-muted-dark uppercase text-[9px]">
                <tr>
                  <th className="p-2">Exclude</th>
                  <th className="p-2">File</th>
                  <th className="p-2">Source sim</th>
                  <th className="p-2">Quality</th>
                  <th className="p-2">Difference</th>
                  <th className="p-2">Max variant sim</th>
                  <th className="p-2">Action</th>
                  <th className="p-2">Bucket</th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((file) => (
                  <tr key={file.name} className="border-t border-border">
                    <td className="p-2">
                      {file.bucket !== "source" && (
                        <input type="checkbox" checked={!!selected[file.name]} onChange={(e) => setSelected((prev) => ({ ...prev, [file.name]: e.target.checked }))} />
                      )}
                    </td>
                    <td className="p-2 font-mono text-muted">{file.name}</td>
                    <td className="p-2 text-muted">{Math.round(file.sourceSimilarity * 100)}%</td>
                    <td className="p-2 text-green">{file.qualityRetained ?? "--"}%</td>
                    <td className="p-2 text-purple">{file.differenceFromOriginal ?? "--"}%</td>
                    <td className="p-2 text-amber">{Math.round((file.maxCrossVariantSimilarity || 0) * 100)}%</td>
                    <td className="p-2 text-muted">{file.recommendedAction || "--"}</td>
                    <td className="p-2 text-purple">{file.bucket}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2 mt-3">
            <button disabled={selectedFiles.length === 0 || busy} onClick={deleteSelected} className="rounded-md border border-red-400/30 bg-red-400/10 px-3 py-2 text-[10px] text-red-400 font-mono disabled:opacity-40">
              Delete selected
            </button>
            <a href={"/api/download?all=true&runId=" + encodeURIComponent(runId) + "&files=" + encodeURIComponent(includedFiles.join(","))} className="rounded-md border border-border px-3 py-2 text-[10px] text-muted font-mono">
              Download included
            </a>
            <span className="text-[9px] text-muted-darker self-center">{selectedFiles.length} excluded</span>
          </div>
        </div>
      )}
    </div>
  );
}
