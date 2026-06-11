"use client";

var TABS = [
  { id: "repurpose", label: "Repurpose" },
  { id: "variation-lab", label: "Variation Lab" },
  { id: "detector", label: "Detector" },
  { id: "converter", label: "Converter" },
  { id: "generator", label: "Generator" },
  { id: "editor", label: "Editor" },
  { id: "runs", label: "Runs" },
];

export default function ToolTabs({ active, onChange }) {
  return (
    <div className="mb-8 overflow-x-auto">
      <div className="flex gap-2 min-w-max">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={
              "px-3 py-2 rounded-card border text-[10px] uppercase tracking-[0.08em] font-mono transition-all cursor-pointer " +
              (active === tab.id
                ? "border-purple-dim bg-purple/10 text-purple"
                : "border-border bg-card text-muted hover:border-border-hover")
            }
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}
