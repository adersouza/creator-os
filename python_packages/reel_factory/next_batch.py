#!/usr/bin/env python3
"""Recommend the next campaign batch from ratings and performance history."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from campaign_store import next_batch_plan


def campaign_factory_next_batch(campaign: str, *, count: int) -> dict | None:
    if os.environ.get("REEL_FACTORY_LOCAL_NEXT_BATCH_ONLY"):
        return None
    try:
        from campaign_factory.config import get_settings
        from campaign_factory.core import CampaignFactory
    except (ImportError, ModuleNotFoundError):
        return None
    cf = CampaignFactory(get_settings())
    try:
        result = cf.recommend_next_batch(campaign, count=count, persist=False)
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        return None
    finally:
        cf.close()
    if result.get("items"):
        result["source"] = "campaign_factory"
        result["fallbackAvailable"] = "reel_factory.local_next_batch"
        return result
    return None


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
