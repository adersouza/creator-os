#!/usr/bin/env python3
"""Inspect and recover the local render queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .render_queue import get_queue


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--recover-stale", action="store_true")
    ap.add_argument("--stale-after-sec", type=int, default=300)
    args = ap.parse_args()
    queue = get_queue(Path(args.root))
    result = {}
    if args.recover_stale:
        result["recovered"] = queue.recover_stale(args.stale_after_sec)
    if args.status or not result:
        result.update(queue.status())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
