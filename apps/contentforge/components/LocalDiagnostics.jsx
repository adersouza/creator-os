"use client";

import { useEffect, useState } from "react";

function Pill({ ok, label }) {
  return (
    <span className={"px-2 py-1 rounded-md border text-[9px] font-mono " + (ok ? "border-green-dim bg-green/10 text-green" : "border-border bg-[#08080c] text-muted-dark")}>
      {label}: {ok ? "on" : "off"}
    </span>
  );
}

export default function LocalDiagnostics() {
  var [data, setData] = useState(null);

  useEffect(() => {
    fetch("/api/diagnostics")
      .then((res) => res.json())
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) return null;
  var filters = data.ffmpeg?.filters || {};
  var setup = data.setup || [];

  return (
    <div className="bg-card rounded-card border border-border p-5">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="text-[10px] text-muted-dark uppercase tracking-[0.1em] font-medium">
          Local diagnostics
        </div>
        <div className="text-[9px] text-muted-darker">
          Optional tools never block core generation
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Pill ok={data.ffmpeg?.available} label="ffmpeg" />
        <Pill ok={filters.libvmaf} label="libvmaf" />
        <Pill ok={filters.ssim} label="ssim" />
        <Pill ok={filters.psnr} label="psnr" />
        <Pill ok={filters.vmafmotion} label="vmafmotion" />
        <Pill ok={filters.cambi} label="cambi" />
        <Pill ok={data.fpcalc?.available} label="fpcalc" />
        <Pill ok={data.python?.available} label="python" />
        <Pill ok={data.sscd?.modelPresent} label="sscd model" />
      </div>
      {setup.length > 0 && (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-2">
          {setup.map((item) => (
            <div key={item.id} className="rounded-md border border-border bg-[#08080c] p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] text-[#d7d7df] font-mono">{item.label}</span>
                <span className={"text-[9px] font-mono " + (item.ok ? "text-green" : "text-amber")}>
                  {item.ok ? "ready" : "optional"}
                </span>
              </div>
              <div className="text-[9px] text-muted-darker mt-1 leading-relaxed">
                {item.detail}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
