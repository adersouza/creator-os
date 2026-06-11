"use client";

import { useState } from "react";

export default function CoverFramePicker({ runId, file, duration, covers = [], onCoverCreated }) {
  var [timestamp, setTimestamp] = useState(1);
  var [busy, setBusy] = useState(false);
  var [error, setError] = useState(null);
  var max = Math.max(1, Math.floor(duration || 1));

  var extract = async () => {
    if (!file || !runId) return;
    setBusy(true);
    setError(null);
    try {
      var res = await fetch("/api/reels/cover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runId, filename: file, timestamp }),
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.error || "Cover extraction failed");
      if (onCoverCreated) onCoverCreated(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  var autoPick = async () => {
    if (!file || !runId) return;
    setBusy(true);
    setError(null);
    try {
      var res = await fetch("/api/reels/cover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runId, filename: file, auto: true, count: 5 }),
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.error || "Cover extraction failed");
      if (onCoverCreated && data.covers) data.covers.forEach(onCoverCreated);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
          Cover frame
        </span>
        <span className="text-[9px] text-muted-darker font-mono">1:1.55 crop check</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1fr_180px] gap-4">
        <div>
          <input
            type="range"
            min={0}
            max={max}
            step={0.1}
            value={timestamp}
            onChange={(e) => setTimestamp(+e.target.value)}
          />
          <div className="flex items-center justify-between mt-2">
            <span className="text-[10px] text-muted-dark font-mono">{timestamp.toFixed(1)}s</span>
            <button
              onClick={extract}
              disabled={busy}
              className="px-3 py-2 rounded-md bg-purple/10 border border-purple-dim text-purple text-[10px] font-mono cursor-pointer disabled:opacity-50"
            >
              {busy ? "Extracting..." : "Extract JPG"}
            </button>
            <button
              onClick={autoPick}
              disabled={busy}
              className="ml-2 px-3 py-2 rounded-md bg-[#08080c] border border-border text-muted text-[10px] font-mono cursor-pointer disabled:opacity-50"
            >
              Auto 5
            </button>
          </div>
          {error && <div className="text-[10px] text-red-400 mt-2">{error}</div>}
        </div>
        <div className="aspect-[420/654] bg-[#08080c] rounded-lg border border-border overflow-hidden">
          {covers[0] ? (
            <img src={covers[0].url} alt="Cover frame" className="w-full h-full object-cover" />
          ) : (
            <div className="h-full flex items-center justify-center text-[10px] text-muted-darker">
              No cover yet
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
