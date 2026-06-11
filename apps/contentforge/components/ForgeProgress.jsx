"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import TerminalLog from "./TerminalLog";

export default function ForgeProgress({ config, onComplete, mediaType }) {
  const isImage = mediaType === "image";
  const configs = useMemo(() => Array.isArray(config?.batchConfigs) && config.batchConfigs.length ? config.batchConfigs : [config], [config]);
  const [phase, setPhase] = useState(0);
  const [phaseLabel, setPhaseLabel] = useState("");
  const [current, setCurrent] = useState(0);
  const totalExpected = configs.reduce((sum, item) => {
    return sum + (isImage ? (item.numVariants || 50) : ((item.numEdits || 0) * (item.spinsPerEdit || 0)));
  }, 0);
  const [total, setTotal] = useState(totalExpected);
  const [filename, setFilename] = useState("");
  const [elapsed, setElapsed] = useState("0s");
  const [eta, setEta] = useState("calculating...");
  const [logs, setLogs] = useState([]);
  const [errors, setErrors] = useState([]);
  const [isComplete, setIsComplete] = useState(false);
  const [completedTotal, setCompletedTotal] = useState(0);
  const abortRef = useRef(null);

  const startForge = useCallback(async () => {
    var totalLabel = configs.length > 1
      ? configs.length + " queued sources"
      : isImage
      ? (config.numVariants || "?") + " image variants"
      : (config.numEdits || "?") + " edits x " + (config.spinsPerEdit || "?") + " spins = " + ((config.numEdits || 0) * (config.spinsPerEdit || 0)) + " variants";
    setLogs(["[ContentForge] Starting " + (isImage ? "image" : "video") + " pipeline: " + totalLabel + "\n"]);

    const controller = new AbortController();
    abortRef.current = controller;

    var results = [];
    for (var batchIndex = 0; batchIndex < configs.length; batchIndex++) {
      var activeConfig = configs[batchIndex];
      setIsComplete(false);
      setLogs((prev) => [...prev, "\n[Queue] Source " + (batchIndex + 1) + " / " + configs.length + "\n"]);
      let response;
      try {
        response = await fetch("/api/forge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(activeConfig),
          signal: controller.signal,
        });
      } catch (err) {
        if (err.name !== "AbortError") {
          setErrors((prev) => [...prev, "Connection failed: " + err.message]);
        }
        return;
      }

      if (!response.ok) {
        setErrors((prev) => [...prev, "Server error: " + response.status]);
        continue;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));

          switch (data.type) {
            case "phase":
              setPhase(data.phase);
              setPhaseLabel(data.message);
              setLogs((prev) => [
                ...prev,
                `\n--- ${data.message} ---\n`,
              ]);
              break;

            case "progress":
              setCurrent(data.completedOverall || data.current);
              setTotal(data.totalOverall || data.total);
              setFilename(data.filename);
              setElapsed(data.elapsed);
              setEta(data.eta);
              break;

            case "log":
              setLogs((prev) => {
                const next = [...prev, data.text];
                // Keep last 500 lines
                return next.length > 500 ? next.slice(-500) : next;
              });
              break;

            case "error":
              setErrors((prev) => [...prev, data.message]);
              setLogs((prev) => [
                ...prev,
                `\u2717 ERROR: ${data.message}\n`,
              ]);
              break;

            case "complete":
              setIsComplete(true);
              setCompletedTotal(data.total);
              setElapsed(data.elapsed);
              setLogs((prev) => [
                ...prev,
                `\n=== COMPLETE: ${data.total} succeeded${data.failed ? `, ${data.failed} failed` : ""} in ${data.elapsed} ===\n`,
              ]);
              results.push(data);
              if (configs.length === 1 && onComplete) onComplete(data);
              break;
          }
          } catch (e) {
            // Skip malformed events
          }
        }
      }
    }
    if (results.length > 1 && onComplete) {
      var lastElapsed = results[results.length - 1]?.elapsed || "0s";
      setIsComplete(true);
      setCompletedTotal(results.reduce((sum, item) => sum + (item.total || 0), 0));
      setElapsed(lastElapsed);
      onComplete({
        type: "complete",
        batch: true,
        total: results.reduce((sum, item) => sum + (item.total || 0), 0),
        attemptedCandidates: results.reduce((sum, item) => sum + (item.attemptedCandidates || 0), 0),
        rejectedCandidates: results.reduce((sum, item) => sum + (item.rejectedCandidates || 0), 0),
        elapsed: lastElapsed,
        results,
        runId: results[results.length - 1]?.runId,
      });
    }
  }, [config, configs, isImage, onComplete]);

  useEffect(() => {
    startForge();
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [startForge]);

  const pct = total > 0 ? (current / total) * 100 : 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Phase indicator */}
      <div className="bg-card rounded-card border border-border p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {!isComplete && (
              <div className="w-2 h-2 rounded-full bg-purple animate-pulse" />
            )}
            {isComplete && (
              <div className="w-2 h-2 rounded-full bg-green" />
            )}
            <span className="text-sm font-medium text-[#e8e8ec]">
              {isComplete ? "Forging Complete" : phaseLabel || "Initializing..."}
            </span>
          </div>
          <span className="text-xs text-muted font-mono">
            {isImage ? "Image Pipeline" : `Phase ${phase}/2`}
          </span>
        </div>

        {/* Progress bar */}
        <div className="h-1 rounded-full bg-[#16161e] overflow-hidden mb-3">
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{
              width: `${pct}%`,
              background: isComplete
                ? "#22c55e"
                : "linear-gradient(90deg, #7c3aed, #a855f7)",
            }}
          />
        </div>

        {/* Stats row */}
        <div className="flex justify-between text-[11px]">
          <span className="text-muted-dark font-mono">
            {current} / {total} variants
          </span>
          <span className="text-muted-dark font-mono truncate max-w-[200px] mx-4">
            {filename}
          </span>
          <div className="flex gap-4">
            <span className="text-muted-dark">
              <span className="text-muted-darker">Elapsed:</span>{" "}
              <span className="font-mono">{elapsed}</span>
            </span>
            {!isComplete && (
              <span className="text-muted-dark">
                <span className="text-muted-darker">ETA:</span>{" "}
                <span className="font-mono">{eta}</span>
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Phase visual indicators */}
      {isImage ? (
        /* Single phase for images */
        <div className="grid grid-cols-1 gap-4">
          <div className={`bg-card rounded-card border p-4 transition-all ${phase >= 1 ? "border-purple-dim" : "border-border"}`}>
            <div className="flex items-center gap-2 mb-2">
              {phase >= 1 && !isComplete && (
                <div className="w-1.5 h-1.5 rounded-full bg-purple animate-pulse" />
              )}
              {isComplete && (
                <span className="text-green text-xs">{"\u2713"}</span>
              )}
              <span className={`text-[10px] uppercase tracking-[0.1em] font-medium ${phase >= 1 ? "text-purple" : "text-muted-darker"}`}>
                Image Variant Generation
              </span>
            </div>
            <div className="text-xs text-muted-dark">
              {config.numVariants} variants with crop + modulate + rotate + JPEG diversity
            </div>
          </div>
        </div>
      ) : (
        /* Two phases for video */
        <div className="grid grid-cols-2 gap-4">
          <div
            className={`bg-card rounded-card border p-4 transition-all ${phase >= 1 ? "border-amber-dim" : "border-border"}`}
          >
            <div className="flex items-center gap-2 mb-2">
              {phase === 1 && !isComplete && (
                <div className="w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
              )}
              {(phase > 1 || isComplete) && (
                <span className="text-green text-xs">{"\u2713"}</span>
              )}
              <span
                className={`text-[10px] uppercase tracking-[0.1em] font-medium ${phase >= 1 ? "text-amber" : "text-muted-darker"}`}
              >
                Phase 1: Creative Remixes
              </span>
            </div>
            <div className="text-xs text-muted-dark">
              {config.numEdits} unique edits with color, hook, crop, speed
            </div>
          </div>

          <div
            className={`bg-card rounded-card border p-4 transition-all ${phase >= 2 ? "border-purple-dim" : "border-border"}`}
          >
            <div className="flex items-center gap-2 mb-2">
              {phase === 2 && !isComplete && (
                <div className="w-1.5 h-1.5 rounded-full bg-purple animate-pulse" />
              )}
              {isComplete && (
                <span className="text-green text-xs">{"\u2713"}</span>
              )}
              <span
                className={`text-[10px] uppercase tracking-[0.1em] font-medium ${phase >= 2 ? "text-purple" : "text-muted-darker"}`}
              >
                Phase 2: Finalization
              </span>
            </div>
            <div className="text-xs text-muted-dark">
              {config.spinsPerEdit} spins per edit with stealth manipulations
            </div>
          </div>
        </div>
      )}

      {/* Terminal log */}
      <div>
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-2">
          FFmpeg output
        </span>
        <TerminalLog logs={logs} />
      </div>

      {/* Errors */}
      {errors.length > 0 && (
        <div className="bg-[#1a0a0a] rounded-card border border-red-900/30 p-4">
          <span className="text-[10px] text-red-400 uppercase tracking-[0.1em] font-medium block mb-2">
            Errors ({errors.length})
          </span>
          {errors.map((err, i) => (
            <div key={i} className="text-xs text-red-400/80 font-mono mb-1">
              {err}
            </div>
          ))}
        </div>
      )}

      {/* Complete stats */}
      {isComplete && (
        <div className="bg-card rounded-card border border-green-dim p-6">
          <div className="grid grid-cols-3 gap-6 text-center">
            <div>
              <div className="text-2xl font-light text-green font-mono">
                {completedTotal}
              </div>
              <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
                Variants created
              </div>
            </div>
            <div>
              <div className="text-2xl font-light text-[#c8c8d0] font-mono">
                {elapsed}
              </div>
              <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
                Total time
              </div>
            </div>
            <div>
              <div className="text-2xl font-light text-purple font-mono">
                {config.level}
              </div>
              <div className="text-[9px] text-muted-dark uppercase tracking-[0.12em] mt-1">
                {isImage ? "Variation level" : "Transform level"}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
