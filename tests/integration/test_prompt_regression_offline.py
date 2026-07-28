from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = ROOT / "evals" / "prompt_regressions"


def test_offline_prompt_harness_passes_captured_fixture() -> None:
    runner = _module("offline_runner", "runner.py")
    variables = _fixture_variables(0)

    result = runner.evaluate_case(variables)

    assert result["pass"] is True


def test_offline_prompt_harness_catches_deliberate_prompt_regression() -> None:
    prompts = _module("offline_prompts_regression", "prompts.py")
    runner = _module("offline_runner_regression", "runner.py")
    variables = _fixture_variables(0)
    prompt = prompts.render_prompt({"vars": variables}) + " accidental drift"

    result = runner.evaluate_case(variables, prompt_override=prompt)

    assert result["pass"] is False
    assert "prompt snapshot changed" in result["reason"]


def test_offline_prompt_harness_catches_malformed_captured_output() -> None:
    runner = _module("offline_runner_malformed", "runner.py")
    variables = _fixture_variables(0)
    fixture_path = ROOT / variables["captured_fixture"]
    captured = json.loads(fixture_path.read_text(encoding="utf-8"))
    del captured["referenceId"]

    result = runner.evaluate_case(variables, captured_override=captured)

    assert result["pass"] is False
    assert "referenceId" in result["reason"]


def _fixture_variables(index: int) -> dict:
    fixtures = json.loads((EVAL_ROOT / "fixtures.json").read_text(encoding="utf-8"))
    return deepcopy(fixtures[index]["vars"])


def _module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EVAL_ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
