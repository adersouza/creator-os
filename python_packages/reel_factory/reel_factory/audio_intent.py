"""Audio intent sidecars for approved social outputs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_audio_intent

AUDIO_INTENT_MODES = {
    "native_trending_audio",
    "original_voiceover",
    "licensed_music",
    "silent_by_design",
    "platform_auto_music",
}


def audio_intent_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".audio_intent.json")


def read_audio_intent(output_path: Path) -> dict[str, Any] | None:
    path = audio_intent_path(output_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_audio_intent(
    output_path: Path,
    *,
    mode: str,
    platform: str | None = None,
    notes: str | None = None,
    audio_selection: dict[str, Any] | None = None,
) -> Path:
    if mode not in AUDIO_INTENT_MODES:
        raise ValueError(
            f"audio intent mode must be one of {sorted(AUDIO_INTENT_MODES)}"
        )
    payload = {
        "schema": "pipeline.audio_intent.v1",
        "mode": mode,
        "required": mode != "silent_by_design",
        "status": "recommended" if mode != "silent_by_design" else "not_required",
        "platform": platform or "",
        "recommendations": [],
        "gates": {
            "allow_draft_export": True,
            "allow_preview_schedule": False,
            "allow_live_schedule": False,
            "allow_publish": False,
        },
        "notes": notes,
        "audio_selection": audio_selection,
        "createdAt": int(time.time()),
    }
    validate_audio_intent(payload)
    path = audio_intent_path(output_path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
