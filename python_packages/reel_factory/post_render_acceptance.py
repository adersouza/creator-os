#!/usr/bin/env python3
"""Compact acceptance evidence for already-rendered Reel Factory outputs."""
from __future__ import annotations

import time
from typing import Any


SCHEMA = "reel_factory.post_render_acceptance.v1"


def acceptance_from_readiness(record: dict[str, Any]) -> dict[str, Any]:
    warnings = set(str(item) for item in (record.get("warnings") or []))
    blocking: list[str] = []
    review: list[str] = []

    if record.get("status") == "not_ready":
        blocking.append("readiness_not_ready")
    if not record.get("audioIntent"):
        review.append("missing_audio_intent")
    if not record.get("lineagePresent"):
        review.append("missing_generated_asset_lineage")

    virality = record.get("viralityQc") or {}
    if virality.get("required") is True and virality.get("status") == "failed":
        blocking.extend(str(item) for item in (virality.get("warnings") or []))

    for warning in sorted(warnings):
        if warning.startswith("virality_") and warning not in blocking and virality.get("required") is True:
            blocking.append(warning)
        elif warning not in blocking and warning not in review:
            review.append(warning)

    blocking = sorted(set(blocking))
    review = sorted(set(review))
    status = "reject" if blocking else ("review" if review else "ready")
    score = int(record.get("score") or 0)
    if blocking:
        score = min(score, 40)
    elif review:
        score = min(score, 75)

    return {
        "schema": SCHEMA,
        "createdAt": int(time.time()),
        "filename": record.get("filename"),
        "path": record.get("path"),
        "platform": record.get("platform"),
        "status": status,
        "score": max(0, min(100, score)),
        "blockingReasons": blocking,
        "reviewReasons": review,
        "evidence": {
            "readinessStatus": record.get("status"),
            "dimensions": record.get("dimensions"),
            "safeZone": record.get("safeZone"),
            "audioIntentPresent": bool(record.get("audioIntent")),
            "lineagePresent": bool(record.get("lineagePresent")),
            "viralityQc": record.get("viralityQc"),
        },
    }
