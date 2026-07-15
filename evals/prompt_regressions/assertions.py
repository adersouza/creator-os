from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "packages/pipeline_contracts",
    "packages/creator_os_core",
    "python_packages/reel_factory",
):
    sys.path.insert(0, str(ROOT / relative))

from reel_factory.caption_bank import (  # noqa: E402
    caption_hash,
    caption_static_metadata,
)

from pipeline_contracts import (  # noqa: E402
    validate_higgsfield_soul_image_prompt,
    validate_reference_video_motion_analysis,
)


def get_assert(output: str, context: dict[str, Any]) -> dict[str, Any]:
    try:
        envelope = json.loads(output)
        prompt = str(envelope["prompt"])
        captured = envelope["capturedOutput"]
        variables = context.get("vars") or {}
        _assert_prompt_snapshot(prompt, variables)
        _assert_captured_output(captured, variables)
        _assert_human_rubric(variables)
    except Exception as exc:
        return {"pass": False, "score": 0, "reason": str(exc)}
    return {
        "pass": True,
        "score": 1,
        "reason": "Prompt snapshot and captured schema pass; human rubric retained for manual review.",
    }


def _assert_prompt_snapshot(prompt: str, variables: dict[str, Any]) -> None:
    actual = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    expected = str(variables.get("expected_prompt_sha256") or "")
    if actual != expected:
        raise AssertionError(
            f"prompt snapshot changed for {variables.get('surface')}: {actual}"
        )
    surface = str(variables.get("surface") or "")
    checks: dict[str, Callable[[], bool]] = {
        "gemini_motion_analysis": lambda: (
            "reel_factory.reference_video_motion_analysis.v1" in prompt
            and str(variables.get("reference_id")) in prompt
            and "one continuous 9:16 shot" in prompt
            and "sourceTextPolicy.reuseVerbatim to false" in prompt
        ),
        "soul_reference_still": lambda: (
            "Return only this JSON" in prompt
            and "exactly one standalone image" in prompt
            and str(variables.get("creative_direction")) in prompt
        ),
        "caption_hook": lambda: bool(prompt.strip()),
    }
    if surface not in checks or not checks[surface]():
        raise AssertionError(f"deterministic prompt rules failed for {surface}")


def _assert_captured_output(captured: Any, variables: dict[str, Any]) -> None:
    surface = str(variables.get("surface") or "")
    if surface == "gemini_motion_analysis":
        validate_reference_video_motion_analysis(captured)
        return
    if surface == "soul_reference_still":
        validate_higgsfield_soul_image_prompt(captured)
        return
    if surface == "caption_hook":
        if not isinstance(captured, dict):
            raise AssertionError("caption fixture must be an object")
        text = str(captured.get("text") or "")
        if caption_hash(text) != captured.get("captionHash"):
            raise AssertionError("caption fixture hash does not match its text")
        metadata = caption_static_metadata(text)
        if metadata["word_count"] != captured.get("wordCount"):
            raise AssertionError("caption fixture word count drifted")
        if metadata["line_count"] != captured.get("lineCount"):
            raise AssertionError("caption fixture line count drifted")
        return
    raise AssertionError(f"unknown captured-output surface: {surface}")


def _assert_human_rubric(variables: dict[str, Any]) -> None:
    rubric = variables.get("human_rubric")
    if not isinstance(rubric, list) or len(rubric) < 2:
        raise AssertionError(
            "every prompt fixture requires at least two human rubric items"
        )
    if any(not isinstance(item, str) or not item.strip() for item in rubric):
        raise AssertionError("human rubric items must be non-empty strings")
