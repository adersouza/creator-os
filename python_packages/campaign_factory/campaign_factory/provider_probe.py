"""Zero-generation provider capability, balance, and quote probes."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

SOUL_MODEL = "text2image_soul_v2"
REQUIRED_VIDEO_MODEL_TOKENS = ("kling", "seedance")
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_provider_probe(
    *, artifact_root: Path, trace_id: str, runner: Runner | None = None
) -> dict[str, Any]:
    """Probe Higgsfield without calling create, reserve, upload, or wait."""
    run = runner or _run
    if not shutil.which("higgsfield") and runner is None:
        raise RuntimeError("Higgsfield CLI is not available")
    if not artifact_root.is_dir() or not artifact_root.parent.is_dir():
        raise RuntimeError("canonical artifact workspace is not ready")

    account = _json_command(run, ["higgsfield", "account", "status", "--json"])
    workspace = _json_command(run, ["higgsfield", "workspace", "status", "--json"])
    image_models = _json_command(
        run, ["higgsfield", "model", "list", "--image", "--json"]
    )
    video_models = _json_command(
        run, ["higgsfield", "model", "list", "--video", "--json"]
    )
    quote = _json_command(
        run,
        [
            "higgsfield",
            "generate",
            "cost",
            SOUL_MODEL,
            "--prompt",
            "Creator OS zero-spend readiness probe",
            "--aspect_ratio",
            "9:16",
            "--json",
        ],
    )

    image_names = _model_names(image_models)
    video_names = _model_names(video_models)
    if SOUL_MODEL not in image_names:
        raise RuntimeError(f"required provider model unavailable: {SOUL_MODEL}")
    missing_video = [
        token
        for token in REQUIRED_VIDEO_MODEL_TOKENS
        if not any(token in name for name in video_names)
    ]
    if missing_video:
        raise RuntimeError(
            "required provider video capability unavailable: "
            + ", ".join(missing_video)
        )
    credits = _number(account, "credits", "available_credits", "balance")
    if credits is None:
        raise RuntimeError("provider balance was not returned")
    quote_amount = _number(quote, "credits_exact", "credits", "amount")
    if quote_amount is None or quote_amount < 0:
        raise RuntimeError("provider free quote was not returned")
    if not isinstance(workspace, dict):
        raise RuntimeError("provider workspace status was not returned")
    return {
        "schema": "campaign_factory.provider_probe.v1",
        "status": "PASS",
        "traceId": trace_id,
        "provider": "higgsfield",
        "accountReachable": True,
        "workspaceReachable": True,
        "availableCredits": credits,
        "models": {
            "soul": SOUL_MODEL,
            "videoCapabilities": list(REQUIRED_VIDEO_MODEL_TOKENS),
        },
        "quote": {"amountCredits": quote_amount, "createdJob": False},
        "providerCalls": 0,
        "costEventsCreated": 0,
        "workspace": str(artifact_root),
    }


def _json_command(run: Runner, command: list[str]) -> Any:
    allowed = {
        ("account", "status"),
        ("workspace", "status"),
        ("model", "list"),
        ("generate", "cost"),
    }
    if len(command) < 3 or (command[1], command[2]) not in allowed:
        raise ValueError("provider probe command is not read-only allowlisted")
    result = run(command)
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split())[:240]
        raise RuntimeError(
            f"provider probe failed: {command[1]} {command[2]}: {detail}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"provider probe returned invalid JSON: {command[1]} {command[2]}"
        ) from exc


def _model_names(value: Any) -> set[str]:
    if not isinstance(value, list):
        raise RuntimeError("provider model list was not returned")
    return {
        str(item.get("job_set_type", "")).lower()
        for item in value
        if isinstance(item, dict) and item.get("job_set_type")
    }


def _number(value: Any, *keys: str) -> float | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
        if isinstance(candidate, dict):
            nested = _number(candidate, "available", "balance", "credits", "amount")
            if nested is not None:
                return nested
    for candidate in value.values():
        if isinstance(candidate, dict):
            nested = _number(candidate, *keys)
            if nested is not None:
                return nested
    return None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, text=True, capture_output=True, timeout=30, check=False
    )
