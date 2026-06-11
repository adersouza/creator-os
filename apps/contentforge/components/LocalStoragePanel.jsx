"use client";

import { useEffect, useState } from "react";

function formatBytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  var units = ["B", "KB", "MB", "GB", "TB"];
  var size = value;
  var index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index++;
  }
  return size.toFixed(index === 0 ? 0 : 1) + " " + units[index];
}

export default function LocalStoragePanel() {
  var [olderThanDays, setOlderThanDays] = useState(14);
  var [maxBytes, setMaxBytes] = useState("");
  var [data, setData] = useState(null);
  var [busy, setBusy] = useState(false);
  var [error, setError] = useState("");

  var inspect = async () => {
    setBusy(true);
    setError("");
    try {
      var params = new URLSearchParams({
        olderThanDays: String(olderThanDays),
        maxBytes: String(maxBytes || 0),
      });
      var response = await fetch("/api/storage/cleanup?" + params.toString());
      var next = await response.json();
      if (!response.ok) throw new Error(next.error || "Storage scan failed");
      setData(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  var cleanup = async () => {
    if (!data?.candidateFiles) return;
    setBusy(true);
    setError("");
    try {
      var response = await fetch("/api/storage/cleanup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          olderThanDays,
          maxBytes: Number(maxBytes || 0),
          confirm: true,
        }),
      });
      var next = await response.json();
      if (!response.ok) throw new Error(next.error || "Cleanup failed");
      setData(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    inspect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
            Local storage
          </div>
          <div className="text-[11px] text-muted-darker mt-1">
            Dry-run cleanup for ignored uploads, outputs, runs, and thumbnails.
          </div>
        </div>
        <button
          onClick={inspect}
          disabled={busy}
          className="rounded-md border border-purple-dim bg-purple/10 px-3 py-2 text-[10px] text-purple font-mono disabled:opacity-40"
        >
          {busy ? "Scanning..." : "Dry run"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <label className="bg-[#08080c] rounded-lg border border-border p-3">
          <span className="text-[9px] text-muted-darker uppercase tracking-[0.08em]">Age</span>
          <select
            value={olderThanDays}
            onChange={(event) => setOlderThanDays(Number(event.target.value))}
            className="w-full mt-2 bg-[#0c0c14] border border-border rounded-md px-2 py-2 text-[11px] text-muted"
          >
            {[7, 14, 30, 60, 90].map((days) => <option key={days} value={days}>{days} days</option>)}
          </select>
        </label>
        <label className="bg-[#08080c] rounded-lg border border-border p-3">
          <span className="text-[9px] text-muted-darker uppercase tracking-[0.08em]">Max bytes target</span>
          <input
            value={maxBytes}
            onChange={(event) => setMaxBytes(event.target.value.replace(/[^0-9]/g, ""))}
            placeholder="optional"
            className="w-full mt-2 bg-[#0c0c14] border border-border rounded-md px-2 py-2 text-[11px] text-muted"
          />
        </label>
        <div className="bg-[#08080c] rounded-lg border border-border p-3">
          <span className="text-[9px] text-muted-darker uppercase tracking-[0.08em]">Candidates</span>
          <div className="text-[18px] text-[#e8e8ec] font-mono mt-1">{data?.candidateFiles ?? "--"}</div>
          <div className="text-[10px] text-muted-darker">{formatBytes(data?.candidateBytes || 0)}</div>
        </div>
      </div>

      {error && <div className="text-[11px] text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2 mb-3">{error}</div>}

      {data && (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="bg-[#08080c] rounded-lg border border-border p-3">
              <div className="text-[9px] text-muted-darker uppercase">Scanned</div>
              <div className="text-[13px] text-muted font-mono mt-1">{data.scannedFiles} files</div>
            </div>
            <div className="bg-[#08080c] rounded-lg border border-border p-3">
              <div className="text-[9px] text-muted-darker uppercase">Total size</div>
              <div className="text-[13px] text-muted font-mono mt-1">{formatBytes(data.scannedBytes)}</div>
            </div>
            <div className="bg-[#08080c] rounded-lg border border-border p-3">
              <div className="text-[9px] text-muted-darker uppercase">Mode</div>
              <div className="text-[13px] text-muted font-mono mt-1">{data.mode}</div>
            </div>
            <button
              disabled={busy || !data.candidateFiles || data.mode === "deleted"}
              onClick={cleanup}
              className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-[10px] text-red-400 font-mono disabled:opacity-40"
            >
              Delete candidates
            </button>
          </div>

          {data.candidates?.length > 0 && (
            <div className="max-h-[220px] overflow-y-auto rounded-card border border-border">
              <table className="w-full text-left text-[10px]">
                <thead className="bg-[#08080c] text-muted-dark uppercase text-[9px]">
                  <tr>
                    <th className="p-2">File</th>
                    <th className="p-2">Size</th>
                    <th className="p-2">Modified</th>
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.slice(0, 80).map((item) => (
                    <tr key={item.file} className="border-t border-border">
                      <td className="p-2 text-muted font-mono truncate max-w-[360px]">{item.file}</td>
                      <td className="p-2 text-muted-darker">{formatBytes(item.size)}</td>
                      <td className="p-2 text-muted-darker">{item.modifiedAt?.slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
