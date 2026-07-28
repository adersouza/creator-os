from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

EVAL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_ROOT))

from assertions import get_assert
from prompts import ROOT, render_prompt

FIXTURES = EVAL_ROOT / "fixtures.json"


def evaluate_case(
    variables: dict[str, Any],
    *,
    prompt_override: str | None = None,
    captured_override: Any | None = None,
) -> dict[str, Any]:
    """Evaluate one captured prompt fixture without network or provider code."""
    prompt = (
        prompt_override
        if prompt_override is not None
        else render_prompt({"vars": variables})
    )
    if captured_override is None:
        fixture_path = (ROOT / str(variables["captured_fixture"])).resolve()
        if ROOT not in fixture_path.parents:
            return {
                "pass": False,
                "score": 0,
                "reason": "captured fixture must stay inside the repository",
            }
        captured = json.loads(fixture_path.read_text(encoding="utf-8"))
    else:
        captured = captured_override
    output = json.dumps(
        {"prompt": prompt, "capturedOutput": captured},
        ensure_ascii=False,
        sort_keys=True,
    )
    return get_assert(output, {"vars": variables})


def load_cases() -> list[dict[str, Any]]:
    value = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("prompt regression fixtures must be a list")
    return [deepcopy(item) for item in value]


def main() -> int:
    failures = 0
    cases = load_cases()
    for case in cases:
        variables = case.get("vars")
        if not isinstance(variables, dict):
            print(f"FAIL {case.get('description')}: missing fixture variables")
            failures += 1
            continue
        result = evaluate_case(variables)
        status = "PASS" if result["pass"] else "FAIL"
        print(f"{status} {case.get('description')}: {result['reason']}")
        failures += int(not result["pass"])
    print(f"prompt regressions: {len(cases) - failures} passed, {failures} failed")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
