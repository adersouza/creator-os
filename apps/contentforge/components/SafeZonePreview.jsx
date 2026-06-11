"use client";

export default function SafeZonePreview({ runId, file }) {
  if (!file) return null;

  var src = "/api/preview?runId=" + encodeURIComponent(runId) + "&file=" + encodeURIComponent(file);

  return (
    <div className="bg-[#08080c] rounded-card border border-border p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
          Reels preview
        </span>
        <span className="text-[9px] text-muted-darker font-mono">9:16 + safe zones</span>
      </div>
      <div className="mx-auto max-w-[260px] rounded-[18px] overflow-hidden bg-black border border-border relative aspect-[9/16]">
        <video
          src={src}
          className="w-full h-full object-cover"
          muted
          loop
          playsInline
          controls
          preload="metadata"
        />
        <div className="pointer-events-none absolute left-0 right-0 top-0 h-[14%] bg-amber/10 border-b border-amber/40" />
        <div className="pointer-events-none absolute left-0 right-0 bottom-0 h-[35%] bg-purple/10 border-t border-purple/40" />
        <div className="pointer-events-none absolute inset-y-0 left-0 w-[6%] bg-green/10 border-r border-green/30" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-[6%] bg-green/10 border-l border-green/30" />
      </div>
      <div className="grid grid-cols-3 gap-2 mt-3 text-center">
        <div className="text-[8px] text-amber font-mono">TOP 14%</div>
        <div className="text-[8px] text-green font-mono">SIDE 6%</div>
        <div className="text-[8px] text-purple font-mono">BOTTOM 35%</div>
      </div>
    </div>
  );
}
