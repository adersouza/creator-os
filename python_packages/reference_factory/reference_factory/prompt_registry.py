"""Approved Reference Factory prompt definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from creator_os_core.prompt_governance import (
    bind_prompt_receipt,
    fingerprint,
    prompt_definition,
    prompt_registry,
    python_source_fingerprint,
)

_PACKAGE_ROOT = Path(__file__).resolve().parent
_GROK_COMPILER_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "reference_grok.py",
    source_id="reference_factory.reference_grok",
    symbols=("_grok_prompt_builder",),
)
_GROK_TEMPLATE_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "reference_grok.py",
    source_id="reference_factory.reference_grok.templates",
    symbols=("_grok_prompt_builder",),
)
_GROK_PROMPT_COMPILER_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "reference_grok.py",
    source_id="reference_factory.reference_grok.prompt_compiler",
    symbols=("_grok_prompt_compiler_prompt",),
)
_GEMINI_ANALYSIS_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "reference_prompt_generation.py",
    source_id="reference_factory.reference_prompt_generation.gemini_analysis",
    symbols=("gemini_analysis_prompt", "_minimal_gemini_analysis_prompt"),
)
_PROVIDER_COMPILER_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "reference_prompt_generation.py",
    source_id="reference_factory.reference_prompt_generation",
    symbols=(
        "_prompt_for_tool",
        "_compose_higgsfield_main_prompt",
        "_compose_kling_main_prompt",
        "_motion_directives",
        "_higgsfield_prompt",
        "_kling_prompt",
    ),
)
_PROVIDER_TEMPLATE_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "reference_prompt_generation.py",
    source_id="reference_factory.reference_prompt_generation.templates",
    symbols=(
        "_compose_higgsfield_main_prompt",
        "_compose_kling_main_prompt",
        "_motion_directives",
    ),
)
GROK_ANALYSIS_REGRESSION_FIXTURE = (
    "77eee6eddfe41f6c9e49797266428de55c0fbc9d37d72c283ec18bdbaaff41bb"
)
GROK_PROMPT_COMPILATION_REGRESSION_FIXTURE = (
    "e7e080be1a782e13993210c1cc41066ff8babccd271285d3cdbe233ade6562db"
)
PROVIDER_COMPILE_REGRESSION_FIXTURE = (
    "bf360188893fe5fa2e735c94e30df5b75a3bb0134b232b77ac3a19ccb5713099"
)
GEMINI_ANALYSIS_REGRESSION_FIXTURE = (
    "d9b9df5b261d00e305f5ba628bc9835d31303de73369abc90846219d2ef490e1"
)


def _definition(
    prompt_id: str,
    version: str,
    purpose: str,
    provider: str,
    models: tuple[str, ...],
    builder: Any,
    compiler_source_fingerprint: str,
    template_source_fingerprint: str,
    input_contract: str,
    output_contract: str,
    cost_behavior: str,
    regression_fixture: str,
    approved_material_fingerprint: str,
) -> dict[str, Any]:
    return prompt_definition(
        prompt_id=prompt_id,
        version=version,
        owner="reference_factory",
        purpose=purpose,
        provider=provider,
        models=models,
        template_version=f"{prompt_id}.v{version}",
        builder_fingerprint=fingerprint(builder),
        compiler_source_fingerprint=compiler_source_fingerprint,
        template_source_fingerprint=template_source_fingerprint,
        input_contract=input_contract,
        output_contract=output_contract,
        approval={
            "state": "approved",
            "approvedBy": "creator_os_reference_baseline",
            "approvedAt": "2026-07-26T00:00:00+00:00",
            "evidence": "reference_factory_current_production_baseline",
            "materialFingerprint": approved_material_fingerprint,
        },
        effective_at="2026-07-26T00:00:00+00:00",
        cost_behavior=cost_behavior,
        regression_fixtures=(regression_fixture,),
    )


PROMPT_REGISTRY = prompt_registry(
    (
        _definition(
            "reference.grok_analysis",
            "1",
            "analyze an authorized reference into structured evidence",
            "xai",
            ("grok-4",),
            {
                "styles": ["minimal", "imageat"],
                "output": "reference.analysis.v2",
            },
            _GROK_COMPILER_SOURCE,
            _GROK_TEMPLATE_SOURCE,
            "reference_factory.reference_analysis_job.v1",
            "reference.analysis.v2",
            "paid_provider_call",
            GROK_ANALYSIS_REGRESSION_FIXTURE,
            "a0337a5921bad38c6e98ba667636b2b94e24a34a7a998cd6620d4e5c2540c7c0",
        ),
        _definition(
            "reference.grok_prompt_compilation",
            "1",
            "compile authorized reference prompts through xAI",
            "xai",
            ("grok-4",),
            {
                "output": "reference_factory.grok_compiled_prompts.v1",
                "strict_json": True,
            },
            _GROK_PROMPT_COMPILER_SOURCE,
            _GROK_PROMPT_COMPILER_SOURCE,
            "reference_factory.grok_prompt_compiler_input.v1",
            "reference_factory.grok_compiled_prompts.v1",
            "paid_provider_call",
            GROK_PROMPT_COMPILATION_REGRESSION_FIXTURE,
            "9fb11b358a42479578e556af90595fd8c9bdf856624a555e664a2e143b64340f",
        ),
        _definition(
            "reference.gemini_analysis",
            "1",
            "analyze an authorized reference into structured evidence",
            "gemini",
            ("gemini-2.5-flash",),
            {
                "styles": ["minimal", "guided"],
                "output": "reference.analysis.v2",
            },
            _GEMINI_ANALYSIS_SOURCE,
            _GEMINI_ANALYSIS_SOURCE,
            "reference_factory.reference_analysis_job.v1",
            "reference.analysis.v2",
            "paid_provider_call",
            GEMINI_ANALYSIS_REGRESSION_FIXTURE,
            "497fcc9335bbd122396f5196fe3b85931ef8d3abaa75e302d1602f39f9411e79",
        ),
        _definition(
            "reference.provider_prompt_compile",
            "1",
            "compile analyzed reference evidence for approved generation tools",
            "any",
            ("*",),
            {
                "targets": ["higgsfield_soul_image", "kling_3_video"],
                "evidence_bound": True,
            },
            _PROVIDER_COMPILER_SOURCE,
            _PROVIDER_TEMPLATE_SOURCE,
            "reference_factory.reference_analysis.v1",
            "reference_factory.generated_video_prompt.v1",
            "local_compile",
            PROVIDER_COMPILE_REGRESSION_FIXTURE,
            "e25d42cba56720a6d48ad0ce5d18726af3d8cf857291f62b70fb058d95cf2ef6",
        ),
    )
)


def bind_reference_prompt(
    *,
    prompt_id: str,
    version: str,
    provider: str,
    model: str,
    compiled_prompt: Any,
    inputs: Any,
) -> dict[str, Any]:
    return bind_prompt_receipt(
        PROMPT_REGISTRY,
        prompt_id=prompt_id,
        version=version,
        provider=provider,
        model=model,
        compiled_prompt=compiled_prompt,
        input_fingerprint=fingerprint(inputs),
    )
