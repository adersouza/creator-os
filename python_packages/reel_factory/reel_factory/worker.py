#!/usr/bin/env python3
"""Run jobs from the local SQLite render queue."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any

from .render_queue import get_queue


async def _run_one(queue: Any, worker_id: str) -> bool:
    job = queue.claim(worker_id)
    if job is None:
        return False
    queue.mark_running(job["job_id"], worker_id)
    proc = await asyncio.create_subprocess_exec(
        *job["command"],
        cwd=job["cwd"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    last = ""
    while True:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        except TimeoutError:
            queue.heartbeat(job["job_id"], worker_id)
            continue
        if not line:
            break
        last = line.decode(errors="replace").strip()
        queue.heartbeat(job["job_id"], worker_id)
    rc = await proc.wait()
    queue.finish(
        job["job_id"],
        "succeeded" if rc == 0 else "failed",
        error_text=None if rc == 0 else last,
    )
    return True


async def run_workers(
    root: Path, *, workers: int = 3, once: bool = False, backend: str = "sqlite"
) -> dict:
    queue = get_queue(root, backend)
    worker_ids = [
        f"{socket.gethostname()}-{i}-{int(time.time())}" for i in range(workers)
    ]
    completed = 0
    while True:
        queue.recover_stale()
        results = await asyncio.gather(*[_run_one(queue, wid) for wid in worker_ids])
        completed += sum(1 for ok in results if ok)
        if once or not any(results):
            break
        await asyncio.sleep(0.25)
    return {"completed": completed, **queue.status()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--once", action="store_true")
    ap.add_argument(
        "--queue-backend", choices=["sqlite", "redis", "rq"], default="sqlite"
    )
    args = ap.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run_workers(
                    Path(args.root),
                    workers=args.workers,
                    once=args.once,
                    backend=args.queue_backend,
                )
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
