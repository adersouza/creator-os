#!/usr/bin/env python3
"""Recommend the next campaign batch from ratings and performance history."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .campaign_store import next_batch_plan

CAMPAIGN_FACTORY_REQUEST_ENV = "CAMPAIGN_FACTORY_NEXT_BATCH_REQUEST"
CAMPAIGN_FACTORY_TIMEOUT_ENV = "REEL_FACTORY_CAMPAIGN_FACTORY_TIMEOUT_SECONDS"


def campaign_factory_next_batch(campaign: str, *, count: int) -> dict | None:
    if os.environ.get("REEL_FACTORY_LOCAL_NEXT_BATCH_ONLY"):
        return None
    try:
        timeout = float(os.environ.get(CAMPAIGN_FACTORY_TIMEOUT_ENV, "30"))
    except ValueError:
        timeout = 30.0
    env = os.environ.copy()
    env[CAMPAIGN_FACTORY_REQUEST_ENV] = json.dumps(
        {"campaign": campaign, "count": count},
        separators=(",", ":"),
    )
    try:
        completed = subprocess.run(
            _campaign_factory_command(),
            check=True,
            capture_output=True,
            env=env,
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


def _campaign_factory_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "campaign_factory.recommendation_bridge",
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
