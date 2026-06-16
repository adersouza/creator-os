#!/usr/bin/env python3
"""Read-only Reel Factory render capacity benchmark using synthetic media."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


SCHEMA = "reel_factory.render_capacity_benchmark.v1"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _render_fixture(out: Path, *, duration: float, encoder: str) -> dict[str, Any]:
    start = time.perf_counter()
    codec_args = ["-c:v", encoder]
    if encoder == "libx264":
        codec_args += ["-preset", "veryfast", "-crf", "24"]
    else:
        codec_args += ["-b:v", "6M", "-maxrate", "8M", "-bufsize", "12M"]
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-y",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=360x640:rate=30:duration={duration:.3f}",
        *codec_args,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(30, int(duration * 20)))
    elapsed = time.perf_counter() - start
    return {
        "ok": proc.returncode == 0 and out.exists(),
        "durationSec": round(elapsed, 3),
        "returnCode": proc.returncode,
        "error": "" if proc.returncode == 0 else (proc.stderr[-1000:] or "ffmpeg render failed"),
    }


def run_render_capacity_benchmark(
    *,
    concurrencies: list[int] | None = None,
    jobs_per_concurrency: int = 8,
    duration: float = 1.0,
    encoder: str = "libx264",
    queue_backend: str = "sqlite",
) -> dict[str, Any]:
    concurrencies = concurrencies or [3, 6, 8]
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="reel-render-benchmark-") as tmp:
        tmp_path = Path(tmp)
        for concurrency in concurrencies:
            job_count = max(concurrency, jobs_per_concurrency)
            started = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [
                    pool.submit(_render_fixture, tmp_path / f"c{concurrency}_{idx}.mp4", duration=duration, encoder=encoder)
                    for idx in range(job_count)
                ]
                results = [future.result() for future in futures]
            elapsed = max(time.perf_counter() - started, 0.001)
            successful = [row for row in results if row["ok"]]
            render_times = [row["durationSec"] for row in successful]
            rows.append({
                "concurrency": concurrency,
                "jobsAttempted": job_count,
                "jobsSucceeded": len(successful),
                "jobsFailed": job_count - len(successful),
                "p50RenderSeconds": round(statistics.median(render_times), 3) if render_times else None,
                "p95RenderSeconds": round(statistics.quantiles(render_times, n=20)[18], 3) if len(render_times) >= 20 else (max(render_times) if render_times else None),
                "wallClockSeconds": round(elapsed, 3),
                "successfulRendersPerHour": round(len(successful) / elapsed * 3600, 1),
                "errors": [row["error"] for row in results if not row["ok"]][:3],
            })
    return {
        "schema": SCHEMA,
        "queueBackend": queue_backend,
        "encoder": encoder,
        "fixtureDurationSeconds": duration,
        "results": rows,
        "writesProductionState": False,
        "scheduled": 0,
        "published": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, action="append", dest="concurrencies")
    parser.add_argument("--jobs-per-concurrency", type=int, default=8)
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--encoder", default="libx264")
    parser.add_argument("--queue-backend", default="sqlite")
    args = parser.parse_args()
    print(json.dumps(run_render_capacity_benchmark(
        concurrencies=args.concurrencies,
        jobs_per_concurrency=args.jobs_per_concurrency,
        duration=args.duration,
        encoder=args.encoder,
        queue_backend=args.queue_backend,
    ), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
