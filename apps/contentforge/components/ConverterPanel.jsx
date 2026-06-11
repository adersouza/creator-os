"use client";

import { useState } from "react";
import ToolResultList from "./ToolResultList";

export default function ConverterPanel({ file }) {
  var [busy, setBusy] = useState(false);
  var [result, setResult] = useState(null);
  var [error, setError] = useState("");
  var [gifOptions, setGifOptions] = useState({ fps: 12, width: 540, loop: "forever" });

  var run = async (mode) => {
    if (!file?.path) return;
    setBusy(true);
    setError("");
    try {
      var res = await fetch(mode === "gif" ? "/api/tools/gif" : "/api/tools/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inputFile: file.path, mode, ...(mode === "gif" ? gifOptions : {}) }),
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
        Converter
      </div>
      <div className="text-[12px] text-muted mb-4">
        Convert the current upload into MP4, JPEG still, or GIF.
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {[
          ["mp4", "MOV/WebM to MP4"],
          ["jpg", "Image/still to JPEG"],
          ["gif", "Video to GIF"],
        ].map(([mode, label]) => (
          <button
            key={mode}
            onClick={() => run(mode)}
            disabled={!file || busy}
            className="rounded-card border border-border bg-[#08080c] px-3 py-3 text-[11px] text-muted font-mono disabled:opacity-40 hover:border-border-hover"
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <label className="text-[9px] text-muted-dark uppercase tracking-[0.08em]">
          GIF FPS
          <input className="mt-1 w-full bg-[#08080c] border border-border rounded-md px-2 py-2 text-[11px] text-muted" type="number" min="6" max="30" value={gifOptions.fps} onChange={(e) => setGifOptions((prev) => ({ ...prev, fps: +e.target.value }))} />
        </label>
        <label className="text-[9px] text-muted-dark uppercase tracking-[0.08em]">
          GIF width
          <input className="mt-1 w-full bg-[#08080c] border border-border rounded-md px-2 py-2 text-[11px] text-muted" type="number" min="240" max="1080" value={gifOptions.width} onChange={(e) => setGifOptions((prev) => ({ ...prev, width: +e.target.value }))} />
        </label>
        <label className="text-[9px] text-muted-dark uppercase tracking-[0.08em]">
          Loop
          <select className="mt-1 w-full bg-[#08080c] border border-border rounded-md px-2 py-2 text-[11px] text-muted" value={gifOptions.loop} onChange={(e) => setGifOptions((prev) => ({ ...prev, loop: e.target.value }))}>
            <option value="forever">Forever</option>
            <option value="once">Once</option>
          </select>
        </label>
      </div>
      {error && <div className="text-[11px] text-red-400 mt-3">{error}</div>}
      <ToolResultList result={result} />
    </div>
  );
}
