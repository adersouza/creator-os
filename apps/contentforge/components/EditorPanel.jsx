"use client";

import { useState } from "react";
import ToolResultList from "./ToolResultList";

export default function EditorPanel({ file }) {
  var [form, setForm] = useState({ trimStart: 0, trimDuration: 0, speed: 1, width: 1080, height: 1920, normalizeAudio: true, overlayText: "", overlayPosition: "bottom", overlayFontSize: 42, overlayOpacity: 0.9 });
  var [busy, setBusy] = useState(false);
  var [audioBusy, setAudioBusy] = useState(false);
  var [result, setResult] = useState(null);
  var [error, setError] = useState("");
  var [audioFile, setAudioFile] = useState(null);

  var update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  var uploadAudio = async (selectedFile) => {
    if (!selectedFile) return;
    setAudioBusy(true);
    setError("");
    try {
      var formData = new FormData();
      formData.append("file", selectedFile);
      var res = await fetch("/api/upload", { method: "POST", body: formData });
      if (!res.ok) {
        var err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Audio upload failed");
      }
      var data = await res.json();
      setAudioFile(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setAudioBusy(false);
    }
  };

  var run = async () => {
    if (!file?.path) return;
    setBusy(true);
    setError("");
    try {
      var res = await fetch("/api/tools/edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inputFile: file.path, replacementAudioFile: audioFile?.path || "", ...form }),
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
        Editor
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {[
          ["trimStart", "Trim start"],
          ["trimDuration", "Duration"],
          ["speed", "Speed"],
          ["width", "Width"],
          ["height", "Height"],
        ].map(([key, label]) => (
          <label key={key} className="text-[10px] text-muted-dark">
            {label}
            <input value={form[key]} type="number" step={key === "speed" ? 0.05 : 1} onChange={(e) => update(key, e.target.value)} className="mt-1 w-full bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
          </label>
        ))}
        <label className="text-[10px] text-muted-dark flex items-center gap-2 pt-5">
          <input type="checkbox" checked={form.normalizeAudio} onChange={(e) => update("normalizeAudio", e.target.checked)} />
          Normalize audio
        </label>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1fr_120px_90px_120px] gap-3 mt-4">
        <label className="text-[10px] text-muted-dark">
          Overlay text
          <input value={form.overlayText} onChange={(e) => update("overlayText", e.target.value)} className="mt-1 w-full bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
        </label>
        <label className="text-[10px] text-muted-dark">
          Position
          <select value={form.overlayPosition} onChange={(e) => update("overlayPosition", e.target.value)} className="mt-1 w-full bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted">
            <option value="bottom">Bottom</option>
            <option value="top">Top</option>
            <option value="center">Center</option>
          </select>
        </label>
        <label className="text-[10px] text-muted-dark">
          Size
          <input value={form.overlayFontSize} type="number" min={18} max={96} onChange={(e) => update("overlayFontSize", e.target.value)} className="mt-1 w-full bg-[#050509] border border-border rounded-md px-3 py-2 text-[12px] text-muted" />
        </label>
        <label className="text-[10px] text-muted-dark">
          Opacity
          <input value={form.overlayOpacity} type="range" min={0.35} max={1} step={0.05} onChange={(e) => update("overlayOpacity", e.target.value)} className="mt-3 w-full" />
        </label>
      </div>
      <div className="mt-4 rounded-md border border-border bg-[#08080c] p-3">
        <label className="text-[10px] text-muted-dark uppercase tracking-[0.08em]">
          Replacement audio
          <input type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg" onChange={(e) => uploadAudio(e.target.files?.[0])} className="mt-2 block w-full text-[11px] text-muted" />
        </label>
        <div className="text-[10px] text-muted-darker mt-2">
          {audioBusy ? "Uploading audio..." : audioFile ? audioFile.filename : "Optional"}
        </div>
      </div>
      <button disabled={!file || busy} onClick={run} className="mt-4 w-full rounded-md border border-purple-dim bg-purple/10 px-3 py-2 text-[10px] text-purple font-mono disabled:opacity-40">
        Export edit
      </button>
      {error && <div className="text-[11px] text-red-400 mt-3">{error}</div>}
      <ToolResultList result={result} />
    </div>
  );
}
