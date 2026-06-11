"use client";

import {
  PLATFORM_PRESETS,
  IMAGE_PRESETS,
} from "../lib/presets";
import { REELS_PROFILES } from "../lib/reels-profiles";
import { VARIANT_PRESETS } from "../lib/variant-engine";

function Bar({ pct, color = "#c084fc", h = 3 }) {
  return (
    <div
      className="rounded-full overflow-hidden"
      style={{ height: h, background: "#16161e" }}
    >
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  );
}

export default function ConfigPanel({ config, onChange, mediaType }) {
  const isImage = mediaType === "image";
  const { preset, edits, spins, flip, vertical, variants, outputProfile, variantPreset = "quality", qualityGate = {} } = config;
  const total = isImage ? (variants || 50) : edits * spins;
  const pods = Math.min(5, Math.ceil(total / 10));
  const variant = VARIANT_PRESETS[variantPreset] || VARIANT_PRESETS.quality;

  const applyPreset = (id) => {
    if (isImage) {
      const p = IMAGE_PRESETS.find((x) => x.id === id);
      if (p && id !== "img-custom") {
        onChange({
          ...config,
          preset: id,
          variants: p.variants,
          variantPreset: p.variantPreset || "quality",
        });
      } else {
        onChange({ ...config, preset: id });
      }
    } else {
      const p = PLATFORM_PRESETS.find((x) => x.id === id);
      if (p && id !== "custom") {
        onChange({
          ...config,
          preset: id,
          edits: p.edits,
          spins: p.spins,
          variantPreset: p.variantPreset || "quality",
          flip: p.flip,
          vertical: p.vert,
        });
      } else {
        onChange({ ...config, preset: id });
      }
    }
  };

  const update = (key, value) => {
    const customPreset = isImage ? "img-custom" : "custom";
    onChange({ ...config, [key]: value, preset: customPreset });
  };

  const updateGate = (key, value) => {
    onChange({
      ...config,
      qualityGate: {
        enabled: true,
        minQuality: 88,
        minDifference: 15,
        maxCrossSimilarity: 0.92,
        maxAttempts: 4,
        ...qualityGate,
        [key]: value,
      },
      preset: isImage ? "img-custom" : "custom",
    });
  };

  const updateVariantOption = (key, value) => {
    onChange({
      ...config,
      variantOptions: {
        ...(config.variantOptions || {}),
        [key]: value,
      },
      preset: isImage ? "img-custom" : "custom",
    });
  };

  const presets = isImage ? IMAGE_PRESETS : PLATFORM_PRESETS;
  const reelsProfiles = Object.values(REELS_PROFILES);

  return (
    <div className="flex flex-col gap-8">
      {/* Platform / Image presets */}
      <div>
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
          {isImage ? "Output target" : "Target platform"}
        </span>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {presets.map((p) => (
            <button
              key={p.id}
              onClick={() => applyPreset(p.id)}
              className={`
                rounded-card border p-4 text-left transition-all duration-200 cursor-pointer
                ${preset === p.id ? "border-purple-dim bg-[#0e0e16]" : "border-border hover:border-border-hover bg-card"}
              `}
            >
              <div
                className={`text-lg mb-2 ${preset === p.id ? "opacity-100" : "opacity-30"}`}
              >
                {p.icon}
              </div>
              <div
                className={`text-[13px] font-medium ${preset === p.id ? "text-[#e8e8ec]" : "text-muted"}`}
              >
                {p.label}
              </div>
              <div className="text-[10px] text-muted-dark mt-0.5">
                {p.sub}
              </div>
            </button>
          ))}
        </div>
      </div>

      {!isImage && (
        <div>
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
            Reels export profile
          </span>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {reelsProfiles.map((profile) => (
              <button
                key={profile.id}
                onClick={() => update("outputProfile", profile.id)}
                className={`
                  rounded-card border p-4 text-left transition-all duration-200 cursor-pointer bg-card
                  ${(outputProfile || "organic") === profile.id ? "border-purple-dim bg-[#0e0e16]" : "border-border hover:border-border-hover"}
                `}
              >
                <div className="text-[13px] font-medium text-[#e8e8ec]">
                  {profile.label}
                </div>
                <div className="text-[10px] text-muted-dark mt-1">
                  {profile.width}x{profile.height} · {profile.fps} fps · H.264/AAC
                </div>
                <div className="text-[9px] text-muted-darker mt-2">
                  {profile.maxDuration ? profile.maxDuration + "s max" : "Flexible duration"} · {profile.videoBitrate}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Sliders + total */}
      {isImage ? (
        /* Image: single variants slider */
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="bg-card rounded-card border border-border p-5">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-2">
              Unique variants
            </span>
            <div className="text-[28px] font-light text-purple tracking-tight mb-3 font-mono">
              {variants || 50}
            </div>
            <input
              type="range"
              min={5}
              max={500}
              step={5}
              value={variants || 50}
              onChange={(e) => update("variants", +e.target.value)}
            />
            <div className="flex gap-1.5 mt-3">
              {[5, 10, 25, 50].map((count) => (
                <button
                  key={count}
                  onClick={() => update("variants", count)}
                  className="px-2 py-1 rounded-md border border-border bg-[#08080c] text-[9px] text-muted font-mono"
                >
                  {count}
                </button>
              ))}
            </div>
            <div className="text-[9px] text-muted-darker mt-2">
              Batch sizes: 5, 10, 25, 50, or custom
            </div>
          </div>

          <div className="bg-[#0a0a10] rounded-card border border-[#c084fc15] p-5">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-2">
              Total output
            </span>
            <div className="text-[28px] font-light text-amber tracking-tight mb-1 font-mono">
              {variants || 50}
            </div>
            <div className="text-[10px] text-muted-dark">
              {variants || 50} unique JPEG images
            </div>
            <div className="text-[10px] text-muted-darker mt-0.5">
              High-quality image outputs
            </div>
          </div>
        </div>
      ) : (
        /* Video: edits x spins */
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-card rounded-card border border-border p-5">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-2">
              Creative edits
            </span>
            <div className="text-[28px] font-light text-amber tracking-tight mb-3 font-mono">
              {edits}
            </div>
            <input
              type="range"
              min={2}
              max={30}
              value={edits}
              onChange={(e) => update("edits", +e.target.value)}
            />
            <div className="text-[9px] text-muted-darker mt-2">
              Color {"\u00B7"} framing {"\u00B7"} encode variations
            </div>
          </div>

          <div className="bg-card rounded-card border border-border p-5">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-2">
              Spins per edit
            </span>
            <div className="text-[28px] font-light text-green tracking-tight mb-3 font-mono">
              {spins}
            </div>
            <input
              type="range"
              min={1}
              max={30}
              value={spins}
              onChange={(e) => update("spins", +e.target.value)}
            />
            <div className="flex gap-1.5 mt-3">
              {[1, 2, 5, 10].map((count) => (
                <button
                  key={count}
                  onClick={() => update("spins", count)}
                  className="px-2 py-1 rounded-md border border-border bg-[#08080c] text-[9px] text-muted font-mono"
                >
                  {count}
                </button>
              ))}
            </div>
            <div className="text-[9px] text-muted-darker mt-2">
              Final variants per edit
            </div>
          </div>

          <div className="bg-[#0a0a10] rounded-card border border-[#c084fc15] p-5">
            <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-2">
              Total output
            </span>
            <div className="text-[28px] font-light text-purple tracking-tight mb-1 font-mono">
              {total}
            </div>
            <div className="text-[10px] text-muted-dark">
              {edits} x {spins} = {total} variants
            </div>
            <div className="text-[10px] text-muted-darker mt-0.5">
              {pods} pods {"\u00B7"} ~{Math.ceil(total / pods)} per pod
            </div>
          </div>
        </div>
      )}

      {/* Manipulation level */}
      <div>
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
          Variant preset
        </span>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {Object.values(VARIANT_PRESETS).map((l) => (
            <button
              key={l.id}
              onClick={() => update("variantPreset", l.id)}
              className={`
                rounded-card border p-4 text-left transition-all duration-200 cursor-pointer bg-card
                ${variantPreset === l.id ? "" : "border-border hover:border-border-hover"}
              `}
              style={{
                borderColor:
                  variantPreset === l.id ? "#c084fc40" : undefined,
              }}
            >
              <div className="flex justify-between items-center mb-2">
                <span
                  className="text-xs font-medium"
                  style={{ color: variantPreset === l.id ? "#c084fc" : "#71717a" }}
                >
                  {l.label}
                </span>
                <span className="text-[9px] font-medium text-muted-darker">
                  Q{l.qualityTarget}
                </span>
              </div>
              <div className="text-[10px] text-muted-dark leading-relaxed">
                {l.id === "quality"
                  ? "Full-frame preservation, high bitrate, subtle changes"
                  : l.id === "light"
                    ? "Small crop, light color and timing changes"
                    : l.id === "medium"
                      ? "Balanced changes with quality guardrails"
                      : l.id === "strong"
                        ? "Larger changes, lower quality target"
                        : "Use the custom option fields sent to the API"}
              </div>
              <div className="mt-3">
                <Bar pct={l.differenceTarget} color="#c084fc" />
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Toggles — video only */}
      {!isImage && (
        <div className="flex flex-col gap-3">
          <div className="flex gap-3">
          {[
            {
              key: "flip",
              val: flip,
              label: "Mirror flip",
              icon: "\u2194",
            },
            {
              key: "vertical",
              val: vertical,
              label: "9:16 vertical",
              icon: "\u25AF",
            },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => update(t.key, !t.val)}
              className={`
                px-3.5 py-1.5 rounded-full text-[10px] font-medium tracking-[0.06em] uppercase font-mono
                border transition-all duration-200 cursor-pointer
                ${
                  t.val
                    ? "border-green-dim bg-[#22c55e10] text-green"
                    : "border-border bg-transparent text-muted"
                }
              `}
            >
              {t.icon} {t.label}
            </button>
          ))}
            <button
              onClick={() => updateGate("enabled", !(qualityGate.enabled !== false))}
              className={`
                px-3.5 py-1.5 rounded-full text-[10px] font-medium tracking-[0.06em] uppercase font-mono
                border transition-all duration-200 cursor-pointer
                ${
                  qualityGate.enabled !== false
                    ? "border-green-dim bg-[#22c55e10] text-green"
                    : "border-border bg-transparent text-muted"
                }
              `}
            >
              ✓ Quality gate
            </button>
          </div>
          {variantPreset === "custom" && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {[
                ["minQuality", "Min quality", 0, 100, 1],
                ["minDifference", "Min difference", 0, 100, 1],
                ["maxCrossSimilarity", "Max similarity", 0.5, 1, 0.01],
                ["maxAttempts", "Attempts", 1, 12, 1],
              ].map(([key, label, min, max, step]) => (
                <label key={key} className="text-[9px] text-muted-dark uppercase tracking-[0.08em]">
                  {label}
                  <input
                    className="mt-1 w-full bg-[#08080c] border border-border rounded-md px-2 py-2 text-[11px] text-muted"
                    type="number"
                    min={min}
                    max={max}
                    step={step}
                    value={qualityGate[key] ?? (key === "minQuality" ? 88 : key === "minDifference" ? 15 : key === "maxCrossSimilarity" ? 0.92 : 4)}
                    onChange={(e) => updateGate(key, +e.target.value)}
                  />
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Score targets */}
      {variant && (
        <div className="bg-card rounded-card border border-border p-5">
          <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
            Score targets ({variant.label})
          </span>
          <div className="flex flex-col gap-3">
            {[
              { name: "Quality retained", pct: variant.qualityTarget, color: "#4ade80" },
              { name: "Difference from original", pct: variant.differenceTarget, color: "#c084fc" },
            ].map((p) => (
              <div key={p.name}>
                <div className="flex justify-between text-[11px] mb-1.5">
                  <span className="text-muted">{p.name}</span>
                  <span className="font-medium font-mono" style={{ color: p.color }}>{p.pct}%</span>
                </div>
                <Bar pct={p.pct} color={p.color} />
              </div>
            ))}
          </div>
          <div className="text-[9px] text-muted-darker mt-3">
            Quality First keeps the source looking close while still generating distinct files.
          </div>
        </div>
      )}

      <div className="bg-card rounded-card border border-border p-5">
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium block mb-3">
          Text overlay
        </span>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_120px_90px_120px] gap-2">
          <input
            value={config.variantOptions?.overlayText || ""}
            onChange={(e) => updateVariantOption("overlayText", e.target.value)}
            placeholder="optional text or watermark"
            className="bg-[#08080c] border border-border rounded-md px-3 py-2 text-[12px] text-muted"
          />
          <select
            value={config.variantOptions?.overlayPosition || "bottom"}
            onChange={(e) => updateVariantOption("overlayPosition", e.target.value)}
            className="bg-[#08080c] border border-border rounded-md px-3 py-2 text-[12px] text-muted"
          >
            <option value="bottom">Bottom</option>
            <option value="top">Top</option>
            <option value="center">Center</option>
          </select>
          <input
            value={config.variantOptions?.overlayFontSize || 42}
            onChange={(e) => updateVariantOption("overlayFontSize", +e.target.value)}
            type="number"
            min={18}
            max={96}
            className="bg-[#08080c] border border-border rounded-md px-3 py-2 text-[12px] text-muted"
          />
          <label className="flex items-center gap-2 bg-[#08080c] border border-border rounded-md px-3 py-2">
            <span className="text-[9px] text-muted-dark uppercase">Opacity</span>
            <input
              value={config.variantOptions?.overlayOpacity ?? 0.9}
              onChange={(e) => updateVariantOption("overlayOpacity", +e.target.value)}
              type="range"
              min={0.35}
              max={1}
              step={0.05}
              className="min-w-0"
            />
          </label>
        </div>
      </div>
    </div>
  );
}
