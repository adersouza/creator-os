"use client";

import { useState, useCallback } from "react";
import DropZone from "../components/DropZone";
import ConfigPanel from "../components/ConfigPanel";
import ForgeProgress from "../components/ForgeProgress";
import ResultsGrid from "../components/ResultsGrid";
import ReelsReadinessPanel from "../components/ReelsReadinessPanel";
import RunHistory from "../components/RunHistory";
import ToolTabs from "../components/ToolTabs";
import SimilarityDetectorPanel from "../components/SimilarityDetectorPanel";
import ConverterPanel from "../components/ConverterPanel";
import GeneratorPanel from "../components/GeneratorPanel";
import EditorPanel from "../components/EditorPanel";
import LocalDiagnostics from "../components/LocalDiagnostics";
import LocalStoragePanel from "../components/LocalStoragePanel";
import VariationLabPanel from "../components/VariationLabPanel";

const STEPS = [
  { label: "Upload & Configure", idx: 0 },
  { label: "Forging", idx: 1 },
  { label: "Results", idx: 2 },
];

export default function Home() {
  const [step, setStep] = useState(0);
  const [file, setFile] = useState(null);
  const [fileQueue, setFileQueue] = useState([]);
  const [mediaType, setMediaType] = useState(null); // "video" | "image"
  const [config, setConfig] = useState({
    // Video defaults
    preset: "both",
    edits: 10,
    spins: 5,
    variantPreset: "quality",
    variantOptions: {},
    qualityGate: { enabled: true, minQuality: 88, minDifference: 15, maxCrossSimilarity: 0.92, maxAttempts: 4 },
    flip: false,
    vertical: true,
    outputProfile: "organic",
    // Image defaults
    variants: 50,
  });
  const [forgeResult, setForgeResult] = useState(null);
  const [activeTool, setActiveTool] = useState("repurpose");

  const isImage = mediaType === "image";
  const total = isImage ? (config.variants || 50) : config.edits * config.spins;

  const onFileUploaded = useCallback((fileData) => {
    setFile(fileData);
    setFileQueue([fileData]);
    const type = fileData.mediaType || "video";
    setMediaType(type);

    // Set sensible defaults based on media type
    if (type === "image") {
      setConfig((prev) => ({
        ...prev,
        preset: "ig-feed",
        variantPreset: "quality",
        variants: 50,
      }));
    } else {
      setConfig((prev) => ({
        ...prev,
        preset: "both",
        variantPreset: "quality",
        outputProfile: "organic",
      }));
    }
  }, []);

  const onFilesUploaded = useCallback((files) => {
    if (!files?.length) return;
    setFileQueue(files);
    setFile(files[0]);
  }, []);

  const startForging = () => {
    if (!file) return;
    setStep(1);
  };

  const onForgeComplete = useCallback((result) => {
    setForgeResult(result);
    setTimeout(() => setStep(2), 1500);
  }, []);

  // Build forge config based on media type
  const forgeConfig = isImage
    ? {
        inputFile: file?.path,
        numVariants: config.variants || 50,
        variantPreset: config.variantPreset || "quality",
        variantOptions: config.variantOptions || {},
        qualityGate: config.qualityGate,
      }
    : {
        inputFile: file?.path,
        numEdits: config.edits,
        spinsPerEdit: config.spins,
        variantPreset: config.variantPreset || "quality",
        variantOptions: config.variantOptions || {},
        qualityGate: config.qualityGate,
        flip: config.flip,
        vertical: config.vertical,
        outputProfile: config.outputProfile || "organic",
      };
  const queuedForgeConfig = fileQueue.length > 1
    ? {
        batchConfigs: fileQueue
          .filter((item) => item.mediaType === mediaType)
          .map((item) => isImage
            ? {
                inputFile: item.path,
                numVariants: config.variants || 50,
                variantPreset: config.variantPreset || "quality",
                variantOptions: config.variantOptions || {},
                qualityGate: config.qualityGate,
              }
            : {
                inputFile: item.path,
                numEdits: config.edits,
                spinsPerEdit: config.spins,
                variantPreset: config.variantPreset || "quality",
                variantOptions: config.variantOptions || {},
                qualityGate: config.qualityGate,
                flip: config.flip,
                vertical: config.vertical,
                outputProfile: config.outputProfile || "organic",
              }),
      }
    : forgeConfig;

  return (
    <div className="min-h-screen relative overflow-hidden">
      <div className="noise-overlay" />
      <div className="glow-overlay" />

      <div className="relative z-10 max-w-[960px] mx-auto px-8 pt-9 pb-20">
        {/* Header */}
        <div className="mb-10">
          <div className="flex items-baseline gap-3 mb-1">
            <span className="text-[11px] text-purple tracking-[0.15em] uppercase font-medium font-mono">
              ContentForge
            </span>
            <span className="text-[10px] text-muted-darker">v5.0</span>
            {mediaType && (
              <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono uppercase tracking-wider ${
                isImage
                  ? "bg-amber/10 text-amber border border-amber-dim"
                  : "bg-purple/10 text-purple border border-purple-dim"
              }`}>
                {isImage ? "image mode" : "video mode"}
              </span>
            )}
          </div>
          <h1 className="text-[36px] font-normal m-0 leading-tight text-[#e8e8ec] font-serif italic">
            {step === 0 && "Configure your forge"}
            {step === 1 && (isImage ? "Generating variants" : "Forging variants")}
            {step === 2 && "Outputs ready"}
          </h1>

          <div className="flex gap-1 mt-4">
            {STEPS.map((s) => (
              <div
                key={s.idx}
                onClick={() => {
                  if (s.idx < step) setStep(s.idx);
                }}
                className="h-0.5 rounded-sm transition-all duration-500"
                style={{
                  width: s.idx === step ? 48 : 24,
                  background:
                    s.idx < step
                      ? "#4ade80"
                      : s.idx === step
                        ? "#c084fc"
                        : "#1e1e28",
                  cursor: s.idx < step ? "pointer" : "default",
                }}
              />
            ))}
          </div>
        </div>

        <ToolTabs active={activeTool} onChange={setActiveTool} />

        {/* Step 0: Upload + Configure */}
        {activeTool === "repurpose" && step === 0 && (
          <div className="flex flex-col gap-8">
            <DropZone onFileUploaded={onFileUploaded} onFilesUploaded={onFilesUploaded} />
            {fileQueue.length > 1 && (
              <div className="bg-card rounded-card border border-border p-4">
                <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium mb-2">
                  Batch queue
                </div>
                <div className="flex flex-col gap-1">
                  {fileQueue.map((item, index) => (
                    <div key={item.path} className="flex justify-between gap-3 text-[10px] font-mono text-muted">
                      <span className="truncate">{index + 1}. {item.filename}</span>
                      <span className="text-muted-darker uppercase">{item.mediaType}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <ConfigPanel config={config} onChange={setConfig} mediaType={mediaType} />

            <button
              onClick={startForging}
              disabled={!file}
              className={`
                w-full py-4 px-6 rounded-card border-none text-white text-[13px] font-medium
                font-mono tracking-[0.02em] transition-all
                ${file ? "cursor-pointer opacity-100" : "cursor-not-allowed opacity-40"}
              `}
              style={{
                background: file
                  ? "linear-gradient(135deg, #7c3aed, #6d28d9)"
                  : "#1c1c24",
                boxShadow: file
                  ? "0 8px 32px rgba(124, 58, 237, 0.2)"
                  : "none",
              }}
            >
              {file
                ? isImage
                  ? `Generate ${total} image variants \u2192`
                  : `Start Forging \u2192 ${total} variants`
                : "Upload a file first"}
            </button>
          </div>
        )}

        {/* Step 1: Forging */}
        {activeTool === "repurpose" && step === 1 && (
          <ForgeProgress config={queuedForgeConfig} onComplete={onForgeComplete} mediaType={mediaType} />
        )}

        {/* Step 2: Results */}
        {activeTool === "repurpose" && step === 2 && (
          <div className="flex flex-col gap-6">
            <ResultsGrid config={config} forgeResult={forgeResult} mediaType={mediaType} sourceFile={file?.path} />
            <ReelsReadinessPanel runId={forgeResult?.runId} mediaType={mediaType} sourceFile={file?.path} />
            <RunHistory currentRunId={forgeResult?.runId} />

            <button
              onClick={() => {
                setStep(0);
                setFile(null);
                setFileQueue([]);
                setMediaType(null);
                setForgeResult(null);
              }}
              className="w-full py-3 px-6 rounded-card border border-border bg-transparent
                text-muted text-[13px] font-medium font-mono tracking-[0.02em] cursor-pointer
                hover:border-border-hover transition-all"
            >
              {"\u2190"} New session
            </button>
          </div>
        )}

        {activeTool === "detector" && (
          <div className="flex flex-col gap-4">
            <SimilarityDetectorPanel runId={forgeResult?.runId} sourceFile={file?.path} />
            <LocalDiagnostics />
          </div>
        )}

        {activeTool === "variation-lab" && (
          <VariationLabPanel file={file} />
        )}

        {activeTool === "converter" && (
          <ConverterPanel file={file} />
        )}

        {activeTool === "generator" && (
          <GeneratorPanel file={file} />
        )}

        {activeTool === "editor" && (
          <EditorPanel file={file} />
        )}

        {activeTool === "runs" && (
          <div className="flex flex-col gap-4">
            <LocalStoragePanel />
            <RunHistory currentRunId={forgeResult?.runId} expanded />
            <LocalDiagnostics />
          </div>
        )}

        <div className="text-center mt-16 text-[9px] text-[#1e1e28] tracking-[0.12em] uppercase">
          ContentForge v5 {"\u00B7"} Local FFmpeg pipeline {"\u00B7"} Video + Image {"\u00B7"} Free
          forever
        </div>
      </div>
    </div>
  );
}
