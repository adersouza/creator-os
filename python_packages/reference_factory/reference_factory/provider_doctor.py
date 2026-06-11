from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .higgsfield_runner import DEFAULT_STACEY_SOUL_ID


XAI_MODELS_URL = "https://api.x.ai/v1/models"

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
Urlopen = Callable[[urllib.request.Request, float], Any]


def provider_doctor(
    *,
    require_gemini: bool = False,
    check_xai: bool = True,
    check_higgsfield_auth: bool = True,
    runner: Runner | None = None,
    urlopen: Urlopen | None = None,
) -> dict[str, Any]:
    run = runner or _run_command
    open_url = urlopen or urllib.request.urlopen
    checks = [
        _binary_check("ffmpeg"),
        _binary_check("ffprobe"),
        _env_key_check("xai", ["XAI_API_KEY", "GROK_API_KEY"], required=check_xai),
        _env_key_check("gemini", ["GEMINI_API_KEY", "GOOGLE_API_KEY"], required=require_gemini),
        _binary_check("higgsfield", recovery="Install @higgsfield/cli and run `higgsfield auth login`."),
    ]

    xai_key = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
    if check_xai and xai_key:
        checks.append(_xai_models_check(xai_key, urlopen=open_url))
    elif check_xai:
        checks.append({
            "name": "xai.spend",
            "status": "skipped",
            "message": "Set XAI_API_KEY or GROK_API_KEY to verify xAI account/API access.",
        })

    if check_higgsfield_auth and shutil.which("higgsfield"):
        checks.append(_higgsfield_auth_check(run))
        checks.append(_higgsfield_soul_check(run))
    elif check_higgsfield_auth:
        checks.append({
            "name": "higgsfield.auth",
            "status": "blocked",
            "message": "higgsfield CLI not found.",
            "recovery": "Install @higgsfield/cli and run `higgsfield auth login`.",
        })

    status = "ok"
    if any(item["status"] == "blocked" for item in checks):
        status = "blocked"
    elif any(item["status"] == "warning" for item in checks):
        status = "warning"
    return {
        "schema": "reference_factory.provider_doctor.v1",
        "status": status,
        "checks": checks,
    }


def _binary_check(binary: str, *, recovery: str | None = None) -> dict[str, Any]:
    path = shutil.which(binary)
    if path:
        return {"name": f"binary.{binary}", "status": "ok", "path": path}
    return {
        "name": f"binary.{binary}",
        "status": "blocked",
        "message": f"{binary} is not available on PATH.",
        "recovery": recovery or f"Install {binary} and ensure it is on PATH.",
    }


def _env_key_check(name: str, keys: list[str], *, required: bool = True) -> dict[str, Any]:
    found = next((key for key in keys if os.environ.get(key)), None)
    if found:
        return {"name": f"env.{name}", "status": "ok", "envVar": found}
    return {
        "name": f"env.{name}",
        "status": "blocked" if required else "skipped",
        "message": f"Missing one of: {', '.join(keys)}.",
        "recovery": f"Set {keys[0]} in your local shell/env file. Do not paste it into chat or commit it.",
    }


def _xai_models_check(api_key: str, *, urlopen: Urlopen) -> dict[str, Any]:
    request = urllib.request.Request(
        XAI_MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=12) as response:
            status_code = getattr(response, "status", 200)
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body.strip().startswith("{") else {}
        model_count = len(parsed.get("data") or []) if isinstance(parsed, dict) else None
        return {
            "name": "xai.spend",
            "status": "ok" if int(status_code) < 400 else "warning",
            "message": "xAI API key can reach the models endpoint without exposing the key.",
            "modelCount": model_count,
        }
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if status in {401, 403}:
            return {
                "name": "xai.spend",
                "status": "blocked",
                "httpStatus": status,
                "message": "xAI rejected the API check. If this is 403, fix billing/credits/monthly spend limit before Grok automation can run.",
                "recovery": "Rotate the pasted key, add the new key locally, and confirm xAI project billing/spend limits.",
            }
        return {"name": "xai.spend", "status": "warning", "httpStatus": status, "message": "xAI API check returned a non-success status."}
    except Exception as exc:  # noqa: BLE001 - surfaced to operator
        return {"name": "xai.spend", "status": "warning", "message": f"xAI API check could not complete: {exc}"}


def _higgsfield_auth_check(runner: Runner) -> dict[str, Any]:
    result = runner(["higgsfield", "auth", "whoami", "--json"])
    if result.returncode == 0:
        return {"name": "higgsfield.auth", "status": "ok"}
    return {
        "name": "higgsfield.auth",
        "status": "blocked",
        "message": _short_stderr(result) or "Higgsfield auth check failed.",
        "recovery": "Run `higgsfield auth login`.",
    }


def _higgsfield_soul_check(runner: Runner) -> dict[str, Any]:
    result = runner(["higgsfield", "soul-id", "list", "--json"])
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0 and (DEFAULT_STACEY_SOUL_ID in output or "Stacey" in output):
        return {"name": "higgsfield.soul_id.stacey", "status": "ok", "soulId": DEFAULT_STACEY_SOUL_ID}
    return {
        "name": "higgsfield.soul_id.stacey",
        "status": "blocked",
        "message": _short_stderr(result) or "Could not confirm the Stacey Soul ID in Higgsfield.",
        "recovery": "Confirm `higgsfield soul-id list --json` includes Stacey / 5828d958-91dd-4d6d-8909-934503f47644.",
    }


def _short_stderr(result: subprocess.CompletedProcess[str]) -> str:
    return " ".join((result.stderr or result.stdout or "").strip().split())[:300]


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)
