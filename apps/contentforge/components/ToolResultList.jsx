"use client";

export default function ToolResultList({ result }) {
  if (!result) return null;
  return (
    <div className="mt-4 rounded-card border border-border bg-[#08080c] p-4">
      <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium mb-3">
        Output run {result.runId}
      </div>
      <div className="flex flex-col gap-2">
        {(result.files || []).map((file) => (
          <a
            key={file.name}
            href={file.url}
            target="_blank"
            className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-[11px] text-muted hover:text-[#e8e8ec] hover:border-border-hover"
          >
            <span className="font-mono truncate">{file.name}</span>
            <span className="text-[9px] text-purple">Open</span>
          </a>
        ))}
      </div>
      <a
        href={"/api/download?all=true&runId=" + encodeURIComponent(result.runId)}
        className="block mt-3 text-center px-3 py-2 rounded-md bg-purple/10 border border-purple-dim text-[10px] text-purple font-mono"
      >
        Download all
      </a>
    </div>
  );
}
