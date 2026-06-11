"use client";

import { useState } from "react";
import ToolResultList from "./ToolResultList";

export default function GeneratorPanel({ file }) {
  var [clipLength, setClipLength] = useState(15);
  var [count, setCount] = useState(5);
  var [everySeconds, setEverySeconds] = useState(1);
  var [maxFrames, setMaxFrames] = useState(20);
  var [busy, setBusy] = useState(false);
  var [result, setResult] = useState(null);
  var [error, setError] = useState("");

  var run = async (endpoint, body) => {
    if (!file?.path) return;
    setBusy(true);
    setError("");
    try {
      var res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inputFile: file.path, ...body }),
      });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium mb-2">
        Generator
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-card border border-border bg-[#08080c] p-4">
          <div className="text-[12px] text-[#e8e8ec] mb-3">Long-video clips</div>
          <label className="block text-[10px] text-muted-dark mb-1">Clip length</label>
          <input type="number" value={clipLength} min={2} max={120} onChange={(e) => setClipLength(e.target.value)} className="w-full mb-3 bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
          <label className="block text-[10px] text-muted-dark mb-1">Clip count</label>
          <input type="number" value={count} min={1} max={20} onChange={(e) => setCount(e.target.value)} className="w-full mb-3 bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
          <button disabled={!file || busy} onClick={() => run("/api/tools/clips", { clipLength, count })} className="w-full rounded-md border border-purple-dim bg-purple/10 px-3 py-2 text-[10px] text-purple font-mono disabled:opacity-40">
            Generate clips
          </button>
        </div>
        <div className="rounded-card border border-border bg-[#08080c] p-4">
          <div className="text-[12px] text-[#e8e8ec] mb-3">PNG frames</div>
          <label className="block text-[10px] text-muted-dark mb-1">Seconds between frames</label>
          <input type="number" value={everySeconds} min={0.2} max={30} step={0.5} onChange={(e) => setEverySeconds(e.target.value)} className="w-full mb-3 bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
          <label className="block text-[10px] text-muted-dark mb-1">Max frames</label>
          <input type="number" value={maxFrames} min={1} max={200} onChange={(e) => setMaxFrames(e.target.value)} className="w-full mb-3 bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
          <button disabled={!file || busy} onClick={() => run("/api/tools/frames", { everySeconds, maxFrames })} className="w-full rounded-md border border-purple-dim bg-purple/10 px-3 py-2 text-[10px] text-purple font-mono disabled:opacity-40">
            Extract frames
          </button>
        </div>
      </div>
      {error && <div className="text-[11px] text-red-400 mt-3">{error}</div>}
      <ToolResultList result={result} />
    </div>
  );
}
