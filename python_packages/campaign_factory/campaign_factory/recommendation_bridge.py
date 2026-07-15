"""Subprocess bridge for boundary-safe recommendation calls."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from .config import get_settings
from .core import CampaignFactory

NEXT_BATCH_REQUEST_ENV = "CAMPAIGN_FACTORY_NEXT_BATCH_REQUEST"


def next_batch_request_from_env(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, int]:
    source = os.environ if environ is None else environ
    raw = source.get(NEXT_BATCH_REQUEST_ENV)
    if not raw:
        raise ValueError(f"{NEXT_BATCH_REQUEST_ENV} is required")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("next-batch request must be a JSON object")
    campaign = data.get("campaign")
    if not isinstance(campaign, str) or not campaign.strip():
        raise ValueError("next-batch request requires a campaign")
    count = _positive_int(data.get("count"), default=20)
    return campaign, count


def recommend_next_batch_from_env(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    campaign, count = next_batch_request_from_env(environ)
    cf = CampaignFactory(get_settings())
    try:
        return cf.domains.recommendations.recommend_next_batch(
            campaign, count=count, persist=False
        )
    finally:
        cf.close()


def main() -> int:
    print(json.dumps(recommend_next_batch_from_env(), indent=2, ensure_ascii=False))
    return 0


def _positive_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    count = int(value)
    if count < 1:
        raise ValueError("count must be positive")
    return count


if __name__ == "__main__":
    raise SystemExit(main())
