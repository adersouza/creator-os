#!/usr/bin/env python3
"""Operator-controlled phase driver for the paid, draft-only acceptance smoke.

Each phase delegates to one explicitly configured local command. Commands inherit
credentials from this process environment; the driver forwards only the redacted
JSON phase payload on stdin and requires one JSON object on stdout.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any

PHASES = {
    "verify_soul",
    "quote",
    "reserve",
    "consume",
    "cancel",
    "generate",
    "render_static_mp4",
    "reel_qc",
    "contentforge_qc",
    "hmac_ingest_preview_draft",
    "verify_draft",
}
COMMAND_PREFIX = "CREATOR_OS_ACCEPTANCE_PHASE_"


def command_env_name(phase: str) -> str:
    return f"{COMMAND_PREFIX}{phase.upper()}_COMMAND"


def run_phase(payload: dict[str, Any]) -> dict[str, Any]:
    phase = payload.get("phase")
    if not isinstance(phase, str) or phase not in PHASES:
        raise ValueError("unsupported acceptance phase")
    _enforce_draft_only(payload)
    command_text = os.environ.get(command_env_name(phase), "").strip()
    if not command_text:
        raise RuntimeError(f"{command_env_name(phase)} is required")
    command = shlex.split(command_text)
    if not command:
        raise RuntimeError(f"{command_env_name(phase)} is empty")
    completed = subprocess.run(
        command,
        input=json.dumps(payload, sort_keys=True),
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()[:300]
        raise RuntimeError(f"phase command failed: {phase}: {detail}")
    try:
        result = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"phase command returned invalid JSON: {phase}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"phase command returned non-object JSON: {phase}")
    return result


def _enforce_draft_only(payload: dict[str, Any]) -> None:
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict):
        return
    if lineage.get("scheduleMode") != "draft":
        raise ValueError("acceptance lineage must remain draft-only")
    if lineage.get("publishRequested") is not False:
        raise ValueError("acceptance lineage must not request publishing")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("phase input must be a JSON object")
        result = run_phase(payload)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
