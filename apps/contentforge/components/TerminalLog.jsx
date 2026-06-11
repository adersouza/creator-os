"use client";

import { useEffect, useRef } from "react";

export default function TerminalLog({ logs }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div ref={containerRef} className="terminal-log">
      {logs.map((line, i) => (
        <span
          key={i}
          className={
            line.includes("\u2713")
              ? "text-green"
              : line.includes("\u2717") || line.includes("ERROR")
                ? "text-red-400"
                : line.includes("---")
                  ? "text-purple"
                  : line.includes("===")
                    ? "text-amber"
                    : ""
          }
        >
          {line}
        </span>
      ))}
    </div>
  );
}
