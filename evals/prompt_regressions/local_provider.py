from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def call_api(
    prompt: str, _options: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Return only local fixture data; this provider has no network code."""
    variables = context.get("vars") or {}
    fixture_path = (ROOT / str(variables["captured_fixture"])).resolve()
    if ROOT not in fixture_path.parents:
        return {"error": "captured fixture must stay inside the repository"}
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    return {
        "output": json.dumps(
            {"prompt": prompt, "capturedOutput": fixture},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "cost": 0,
        "tokenUsage": {
            "total": 0,
            "prompt": 0,
            "completion": 0,
            "numRequests": 0,
        },
    }
