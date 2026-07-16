"""Validate Campaign-owned generation policy at the Reel Factory boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_generation_execution_plan

_ALLOWED_MODES_BY_ACTION = {
    "reference-image": {"soul_static", "reference_video_remix"},
    "image": {"soul_static", "reference_video_remix"},
    "video": {"best_only_kling", "reference_video_remix"},
}


def load_generation_execution_plan(
    path: str | Path, *, worker_action: str
) -> dict[str, Any]:
    """Load a plan and fail closed when it does not authorize this worker action."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"generation execution plan not found: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("generation execution plan is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("generation execution plan must be an object")
    validate_generation_execution_plan(payload)

    action = str(worker_action).removesuffix("-dry-run")
    allowed_modes = _ALLOWED_MODES_BY_ACTION.get(action)
    if allowed_modes is None:
        raise ValueError(f"unsupported generation worker action: {worker_action}")
    creative_mode = str(payload["creativeMode"])
    if creative_mode not in allowed_modes:
        raise PermissionError(
            f"{creative_mode} execution plan does not authorize {action}"
        )
    paid_field = "paidVideoGeneration" if action == "video" else "paidImageGeneration"
    if payload[paid_field] is not True:
        raise PermissionError(
            f"{creative_mode} execution plan does not authorize paid {action} generation"
        )
    if payload["providerAuthorization"] != "required_per_paid_call":
        raise PermissionError(
            f"{creative_mode} execution plan lacks paid provider authorization policy"
        )
    return payload
