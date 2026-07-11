from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_contentforge(
    root: Path | str,
    command: str,
    payload: dict[str, Any],
    *,
    timeout: int = 240,
) -> dict[str, Any]:
    contentforge_root = Path(root).expanduser().resolve()
    cli_path = contentforge_root / "cli.mjs"
    if not cli_path.exists():
        raise RuntimeError(f"ContentForge CLI is missing: {cli_path}")
    try:
        completed = subprocess.run(
            ["node", str(cli_path), command],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=contentforge_root,
            timeout=max(1, int(timeout)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ContentForge CLI failed to start: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise RuntimeError(f"ContentForge CLI failed: {detail[:2000]}")
    raw = completed.stdout.strip()
    if not raw:
        raise RuntimeError("ContentForge returned an empty response")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ContentForge returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("ContentForge returned a non-object response")
    if parsed.get("error"):
        raise RuntimeError(f"ContentForge error: {parsed['error']}")
    return parsed
