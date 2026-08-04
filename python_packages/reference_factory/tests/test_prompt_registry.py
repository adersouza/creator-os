from __future__ import annotations

import pytest
from creator_os_core.prompt_governance import regression_fixture_hash
from reference_factory.prompt_registry import (
    GEMINI_ANALYSIS_REGRESSION_FIXTURE,
    GROK_ANALYSIS_REGRESSION_FIXTURE,
    GROK_PROMPT_COMPILATION_REGRESSION_FIXTURE,
    PROVIDER_COMPILE_REGRESSION_FIXTURE,
    bind_reference_prompt,
)
from reference_factory.reference_grok import (
    _grok_prompt_builder,
    _grok_prompt_compiler_prompt,
)
from reference_factory.reference_prompt_generation import (
    _prompt_for_tool,
    gemini_analysis_prompt,
)


def test_reference_prompt_regression_fixtures_execute_real_compilers() -> None:
    gemini_source = {
        "path": "/fixtures/reference.mp4",
        "account": "fixture_account",
        "reference_id": "fixture_ref",
    }
    assert GEMINI_ANALYSIS_REGRESSION_FIXTURE == regression_fixture_hash(
        fixture_id="reference.gemini_analysis.minimal.v1",
        inputs={
            "source": gemini_source,
            "platform": "instagram",
            "promptStyle": "minimal",
        },
        compiled_prompt=gemini_analysis_prompt(
            gemini_source,
            platform="instagram",
            prompt_style="minimal",
        ),
    )

    grok_job = {"referenceId": "fixture_ref", "fileName": "fixture.mp4"}
    assert GROK_ANALYSIS_REGRESSION_FIXTURE == regression_fixture_hash(
        fixture_id="reference.grok_analysis.minimal.v1",
        inputs={"job": grok_job, "promptStyle": "minimal"},
        compiled_prompt=_grok_prompt_builder(grok_job, prompt_style="minimal"),
    )

    image_prompt = {"referenceId": "fixture_ref", "prompt": "image fixture"}
    video_prompt = {"referenceId": "fixture_ref", "prompt": "video fixture"}
    assert GROK_PROMPT_COMPILATION_REGRESSION_FIXTURE == regression_fixture_hash(
        fixture_id="reference.grok_prompt_compilation.v1",
        inputs={
            "referenceId": "fixture_ref",
            "imagePrompt": image_prompt,
            "videoPrompt": video_prompt,
            "instructions": "preserve composition",
        },
        compiled_prompt=_grok_prompt_compiler_prompt(
            reference_id="fixture_ref",
            image_prompt=image_prompt,
            video_prompt=video_prompt,
            instructions="preserve composition",
        ),
    )

    provider_job = {"reference_id": "fixture_ref", "content_hash": "a" * 64}
    analysis = {
        "summary": "calm room selfie",
        "contentFormat": "selfie_video",
        "subject": {
            "action": "poses naturally",
            "pose": "standing",
            "expression": "soft confident",
            "wardrobe": "black top",
        },
        "setting": {
            "location": "bright room",
            "lighting": "soft daylight",
            "background": "plain wall",
        },
        "camera": {
            "framing": "vertical medium shot",
            "angle": "eye level",
            "movement": "subtle handheld",
        },
    }
    assert PROVIDER_COMPILE_REGRESSION_FIXTURE == regression_fixture_hash(
        fixture_id="reference.provider_prompt_compile.kling.v1",
        inputs={
            "targetTool": "kling_3_video",
            "job": provider_job,
            "analysis": analysis,
            "modelProfile": "fixture_creator",
        },
        compiled_prompt=_prompt_for_tool(
            "kling_3_video", provider_job, analysis, "fixture_creator"
        ),
    )


def test_paid_reference_prompt_rejects_unapproved_model_substitution() -> None:
    with pytest.raises(PermissionError, match="model_mismatch"):
        bind_reference_prompt(
            prompt_id="reference.grok_analysis",
            version="1",
            provider="xai",
            model="substituted-unapproved-model",
            compiled_prompt="fixture",
            inputs={"referenceId": "fixture_ref"},
        )
