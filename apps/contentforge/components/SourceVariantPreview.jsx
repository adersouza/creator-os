"use client";

import { useMemo, useState } from "react";

export default function SourceVariantPreview({ sourceFile, files, runId, mediaType }) {
  var variants = useMemo(function () {
    return files || [];
  }, [files]);
  var [selected, setSelected] = useState("");
  var current = useMemo(function () {
    return variants.find(function (file) { return file.name === selected; }) || variants[0];
  }, [selected, variants]);

  if (!sourceFile || !current) return null;

  var sourceUrl = "/api/upload-preview?file=" + encodeURIComponent(sourceFile);
  var variantUrl = "/api/preview?runId=" + encodeURIComponent(runId || "latest") + "&file=" + encodeURIComponent(current.name);
  var isImage = mediaType === "image";

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between gap-3 mb-4">
        <div>
          <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
            A/B preview
          </div>
          <div className="text-[11px] text-muted-darker mt-1">
            Source beside selected output.
          </div>
        </div>
        <select
          value={current.name}
          onChange={(e) => setSelected(e.target.value)}
          className="bg-[#08080c] border border-border rounded-md text-[11px] text-muted px-2 py-2 max-w-[260px]"
        >
          {variants.map((file) => <option key={file.name} value={file.name}>{file.name}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <PreviewPane label="Source" url={sourceUrl} isImage={isImage} />
        <PreviewPane label="Variant" url={variantUrl} isImage={isImage} />
      </div>
    </div>
  );
}

function PreviewPane({ label, url, isImage }) {
  return (
    <div className="rounded-card border border-border bg-black overflow-hidden">
      <div className="px-3 py-2 text-[9px] uppercase tracking-[0.1em] text-muted-dark bg-[#08080c]">
        {label}
      </div>
      <div className={isImage ? "aspect-square" : "aspect-[9/16]"}>
        {isImage ? (
          <img src={url} alt={label} className="w-full h-full object-contain" />
        ) : (
          <video src={url} className="w-full h-full object-contain" controls playsInline />
        )}
      </div>
    </div>
  );
}
