"""Narrow XAI vision transport used by generated-media QC.

This module intentionally owns no prompt-generation workflow.  It only renders
image inputs, calls the XAI Responses API, and loads the existing API key for
the fail-closed anatomy/postability checks.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from pipeline_contracts.llm_resilience import urlopen_json_with_retry

from .project_config import config_path

XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = "grok-4.3"


def data_uri(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    media_type = (
        guessed
        if guessed in {"image/jpeg", "image/png"}
        else ("image/png" if path.suffix.lower() == ".png" else "image/jpeg")
    )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def build_xai_payload(
    *, model: str, frames: list[Path], instruction: str
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": instruction,
        }
    ]
    for frame in frames:
        content.append(
            {
                "type": "input_image",
                "image_url": data_uri(frame),
                "detail": "high",
            }
        )
    return {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }


def response_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text":
                parts.append(str(content.get("text") or ""))
    if parts:
        return "\n".join(parts).strip()
    choices = payload.get("choices") or []
    if choices:
        return str((choices[0].get("message") or {}).get("content") or "").strip()
    return ""


def strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def call_grok(
    payload: dict[str, Any], *, api_key: str, timeout: int = 120
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        XAI_RESPONSES_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return urlopen_json_with_retry(req, timeout=timeout)


def _load_secret_value(
    root: Path, names: tuple[str, ...], env_names: tuple[str, ...]
) -> str | None:
    for env_name in env_names:
        env_key = os.getenv(env_name)
        if env_key:
            return env_key
    for path in (
        root / "project_data" / "secrets.toml",
        config_path(root).with_suffix(".secrets.toml"),
    ):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in names:
                return value.strip().strip('"').strip("'") or None
    return None


def load_xai_api_key(root: Path) -> str | None:
    return _load_secret_value(root, ("xai_api_key",), ("XAI_API_KEY",))
