#!/usr/bin/env python3
"""Recommend the next campaign batch from ratings and performance history."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from campaign_store import next_batch_plan


def campaign_factory_next_batch(campaign: str, *, count: int) -> dict | None:
    if os.environ.get("REEL_FACTORY_LOCAL_NEXT_BATCH_ONLY"):
        return None
    try:
        from campaign_factory.config import get_settings
        from campaign_factory.core import CampaignFactory
    except Exception:
        return None
    cf = CampaignFactory(get_settings())
    try:
        result = cf.recommend_next_batch(campaign, count=count, persist=False)
    except Exception:
        return None
    finally:
        cf.close()
    if result.get("items"):
        result["source"] = "campaign_factory"
        result["fallbackAvailable"] = "reel_factory.local_next_batch"
        return result
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--count", type=int, default=20)
    args = ap.parse_args()
    plan = campaign_factory_next_batch(args.campaign, count=args.count)
    if plan is None:
        plan = next_batch_plan(Path(args.root), campaign=args.campaign, count=args.count)
        plan["source"] = "reel_factory.local_next_batch"
    print(json.dumps(
        plan,
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
