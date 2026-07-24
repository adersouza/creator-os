"""Audio intent sidecars for approved social outputs."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_audio_intent

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text

AUDIO_INTENT_MODES = {
    "embedded_trending_audio",
    "embedded_original_audio",
    "embedded_creator_voice",
    "embedded_royalty_free_audio",
    "native_trending_audio",
    "original_voiceover",
    "silent_by_design",
    "platform_auto_music",
}

POLICY_FOR_MODE = {
    "embedded_trending_audio": "embedded_trending_required",
    "embedded_original_audio": "original_embedded",
    "embedded_creator_voice": "creator_voice",
    "embedded_royalty_free_audio": "royalty_free",
    "native_trending_audio": "native_trending_required",
    "original_voiceover": "creator_voice",
    "silent_by_design": "silent_allowed",
    "platform_auto_music": "native_trending_required",
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
    policy = POLICY_FOR_MODE[mode]
    silent = policy == "silent_allowed"
    now = datetime.now(UTC).isoformat()
    payload = {
        "schema": "pipeline.audio_intent.v1",
        "policy": policy,
        "mode": mode,
        "required": not silent,
        "status": "recommended" if not silent else "not_required",
        "platform": platform or "",
        "recommendations": [],
        "operator_selection": (
            {
                "selected_reason": notes
                or "Operator explicitly selected silent_by_design",
                "selected_at": now,
            }
            if silent
            else {}
        ),
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
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path
