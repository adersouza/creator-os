from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = ROOT / "evals" / "prompt_regressions"


def test_offline_prompt_harness_passes_captured_fixture() -> None:
    prompts = _module("offline_prompts", "prompts.py")
    provider = _module("offline_provider", "local_provider.py")
    assertions = _module("offline_assertions", "assertions.py")
    variables = _fixture_variables(0)
    prompt = prompts.render_prompt({"vars": variables})
    response = provider.call_api(prompt, {}, {"vars": variables})

    result = assertions.get_assert(response["output"], {"vars": variables})

    assert result["pass"] is True
    assert response["cost"] == 0
    assert response["tokenUsage"]["numRequests"] == 0


def test_offline_prompt_harness_catches_deliberate_prompt_regression() -> None:
    prompts = _module("offline_prompts_regression", "prompts.py")
    provider = _module("offline_provider_regression", "local_provider.py")
    assertions = _module("offline_assertions_regression", "assertions.py")
    variables = _fixture_variables(0)
    prompt = prompts.render_prompt({"vars": variables}) + " accidental drift"
    response = provider.call_api(prompt, {}, {"vars": variables})

    result = assertions.get_assert(response["output"], {"vars": variables})

    assert result["pass"] is False
    assert "prompt snapshot changed" in result["reason"]


def test_offline_prompt_harness_catches_malformed_captured_output() -> None:
    prompts = _module("offline_prompts_malformed", "prompts.py")
    provider = _module("offline_provider_malformed", "local_provider.py")
    assertions = _module("offline_assertions_malformed", "assertions.py")
    variables = _fixture_variables(0)
    prompt = prompts.render_prompt({"vars": variables})
    response = provider.call_api(prompt, {}, {"vars": variables})
    envelope = json.loads(response["output"])
    del envelope["capturedOutput"]["referenceId"]

    result = assertions.get_assert(
        json.dumps(envelope, sort_keys=True), {"vars": variables}
    )

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
