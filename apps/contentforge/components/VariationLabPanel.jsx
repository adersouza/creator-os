"use client";

import { useState } from "react";

function stateClass(state) {
  if (state === "ready") return "text-green-400";
  if (state === "review") return "text-amber";
  if (state === "fix") return "text-red-300";
  return "text-muted";
}

export default function VariationLabPanel({ file }) {
  const [variantCount, setVariantCount] = useState(8);
  const [variationPreset, setVariationPreset] = useState("balanced");
  const [captionMode, setCaptionMode] = useState("none");
  const [suppliedHooks, setSuppliedHooks] = useState("");
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  async function runPack() {
    if (!file?.path) return;
    setRunning(true);
    setError("");
    setReport(null);
    try {
      const res = await fetch("/api/variant-pack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: file.path,
          variantCount,
          variationPreset,
          captionMode,
          suppliedHooks: suppliedHooks.split(/\n+/).map((line) => line.trim()).filter(Boolean),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Variant pack failed");
      setReport(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="bg-card rounded-card border border-border p-5">
        <div className="flex items-center justify-between gap-3 mb-4">
          <div>
            <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
              Variation Lab
            </div>
            <div className="text-[13px] text-[#d7d7df] mt-1">
              One source in, ranked reusable variant pack out.
            </div>
          </div>
          <button
            onClick={runPack}
            disabled={!file || running}
            className="px-4 py-2 rounded-card border border-purple-dim bg-purple/10 text-purple text-[11px] font-mono disabled:opacity-40"
          >
            {running ? "Running..." : "Run Pack"}
          </button>
        </div>

        {!file && (
          <div className="text-[12px] text-muted">
            Upload a source video in Repurpose first, then open this tab.
          </div>
        )}

        {file && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="text-[10px] text-muted-dark uppercase tracking-[0.08em]">
              Source
              <div className="mt-1 text-[11px] text-muted font-mono truncate normal-case">{file.filename || file.path}</div>
            </label>
            <label className="text-[10px] text-muted-dark uppercase tracking-[0.08em]">
              Variant count
              <input
                type="number"
                min="1"
                max="30"
                value={variantCount}
                onChange={(event) => setVariantCount(Number(event.target.value))}
                className="mt-1 w-full bg-[#08080c] border border-border rounded-card px-3 py-2 text-[12px] text-[#e8e8ec]"
              />
            </label>
            <label className="text-[10px] text-muted-dark uppercase tracking-[0.08em]">
              Variation preset
              <select
                value={variationPreset}
                onChange={(event) => setVariationPreset(event.target.value)}
                className="mt-1 w-full bg-[#08080c] border border-border rounded-card px-3 py-2 text-[12px] text-[#e8e8ec]"
              >
                <option value="subtle">Subtle</option>
                <option value="balanced">Balanced</option>
                <option value="strong">Strong</option>
              </select>
            </label>
            <label className="text-[10px] text-muted-dark uppercase tracking-[0.08em]">
              Caption mode
              <select
                value={captionMode}
                onChange={(event) => setCaptionMode(event.target.value)}
                className="mt-1 w-full bg-[#08080c] border border-border rounded-card px-3 py-2 text-[12px] text-[#e8e8ec]"
              >
                <option value="none">None</option>
                <option value="keep_original">Keep original</option>
                <option value="generated_hooks">Generated hooks</option>
                <option value="supplied_hooks">Supplied hooks</option>
              </select>
            </label>
            <label className="md:col-span-2 text-[10px] text-muted-dark uppercase tracking-[0.08em]">
              Supplied hooks
              <textarea
                value={suppliedHooks}
                onChange={(event) => setSuppliedHooks(event.target.value)}
                rows={4}
                className="mt-1 w-full bg-[#08080c] border border-border rounded-card px-3 py-2 text-[12px] text-[#e8e8ec]"
                placeholder="optional, one hook per line"
              />
            </label>
          </div>
        )}
        {error && <div className="mt-3 text-[12px] text-red-300">{error}</div>}
      </div>

      {report && (
        <div className="bg-card rounded-card border border-border p-5">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">Ranked variants</div>
              <div className="text-[11px] text-muted mt-1">
                {report.operatorSummary.recommended} recommended · avg variation {report.operatorSummary.avgVariation}
              </div>
            </div>
            <a
              className="px-3 py-2 rounded-card border border-border text-[10px] text-muted font-mono"
              href={report.manifestUrl || ("/api/variant-pack/" + encodeURIComponent(report.runId) + "/manifest")}
            >
              Manifest
            </a>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(report.results || []).map((item, index) => (
              <div key={item.file} className="rounded-card border border-border bg-[#08080c] p-3">
                <video
                  className="w-full aspect-[9/16] object-cover bg-black rounded-md mb-3"
                  controls
                  muted
                  preload="metadata"
                  src={"/api/preview?runId=" + encodeURIComponent(report.runId) + "&file=" + encodeURIComponent(item.file)}
                />
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] text-muted font-mono truncate">#{index + 1} {item.file}</span>
                  <span className={"text-[10px] uppercase font-mono " + stateClass(item.operatorState)}>{item.operatorState}</span>
                </div>
                <div className="grid grid-cols-3 gap-2 mt-3 text-[10px] text-muted">
                  <span>variation <b className="text-[#d7d7df]">{item.variationScore}</b></span>
                  <span>source sim <b className="text-[#d7d7df]">{item.sourceSimilarity}</b></span>
                  <span>quality <b className="text-[#d7d7df]">{item.creativeQualityScore}</b></span>
                  <span>readability <b className="text-[#d7d7df]">{item.readabilityScore ?? "-"}</b></span>
                  <span>safe zone <b className="text-[#d7d7df]">{item.safeZoneScore ?? "-"}</b></span>
                  <span>pack sim <b className="text-[#d7d7df]">{item.variantToVariantSimilarity}</b></span>
                </div>
                {item.mainWarnings?.length ? (
                  <div className="mt-2 text-[10px] text-amber">Review: {item.mainWarnings.join(", ")}</div>
                ) : (
                  <div className="mt-2 text-[10px] text-green-400">No major issues</div>
                )}
                {item.recommendedFixes?.length ? (
                  <details className="mt-2 text-[10px] text-muted">
                    <summary>Recommended fixes</summary>
                    <ul className="mt-1 space-y-1">
                      {item.recommendedFixes.map((fix) => <li key={fix}>{fix}</li>)}
                    </ul>
                  </details>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
