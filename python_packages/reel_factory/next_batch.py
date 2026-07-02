#!/usr/bin/env python3
"""Recommend the next campaign batch from ratings and performance history."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from campaign_store import next_batch_plan

CAMPAIGN_FACTORY_CLI_ENV = "REEL_FACTORY_CAMPAIGN_FACTORY_CLI"
CAMPAIGN_FACTORY_TIMEOUT_ENV = "REEL_FACTORY_CAMPAIGN_FACTORY_TIMEOUT_SECONDS"


def campaign_factory_next_batch(campaign: str, *, count: int) -> dict | None:
    if os.environ.get("REEL_FACTORY_LOCAL_NEXT_BATCH_ONLY"):
        return None
    try:
        timeout = float(os.environ.get(CAMPAIGN_FACTORY_TIMEOUT_ENV, "30"))
    except ValueError:
        timeout = 30.0
    cmd = _campaign_factory_command(campaign, count=count)
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result = json.loads(completed.stdout)
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ):
        return None
    if result.get("items"):
        result["source"] = "campaign_factory"
        result["fallbackAvailable"] = "reel_factory.local_next_batch"
        return result
    return None


def _campaign_factory_command(campaign: str, *, count: int) -> list[str]:
    override = os.environ.get(CAMPAIGN_FACTORY_CLI_ENV)
    base = (
        shlex.split(override)
        if override
        else [sys.executable, "-m", "campaign_factory.cli"]
    )
    return [
        *base,
        "recommend-next-batch",
        "--campaign",
        campaign,
        "--count",
        str(count),
    ]


def select_next_batch(
    root: Path, *, campaign: str, count: int, persist: bool = False
) -> dict:
    plan = campaign_factory_next_batch(campaign, count=count)
    if plan is not None:
        return plan
    plan = next_batch_plan(root, campaign=campaign, count=count, persist=persist)
    plan["source"] = "reel_factory.local_next_batch"
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--count", type=int, default=20)
    args = ap.parse_args()
    plan = select_next_batch(Path(args.root), campaign=args.campaign, count=args.count)
    print(
        json.dumps(
            plan,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
