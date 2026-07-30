from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from creator_os_core.prompt_governance import (
    bind_prompt_receipt,
    fingerprint,
    governed_material_fingerprint,
    prompt_definition,
    prompt_registry,
    python_source_fingerprint,
    regression_fixture_hash,
    resolve_prompt,
    verify_prompt_receipt,
)


def _definition(*, state: str = "approved", retired: str | None = None) -> dict:
    builder = {"template": "Animate {subject} calmly"}
    builder_fingerprint = fingerprint(builder)
    compiler_source_fingerprint = fingerprint({"source": "def compile(subject): ..."})
    template_source_fingerprint = fingerprint({"template": "Animate {subject} calmly"})
    regression_fixtures = (
        regression_fixture_hash(
            fixture_id="test.passive.basic.v1",
            inputs={"subject": "the approved creator"},
            compiled_prompt="Animate the approved creator calmly",
        ),
    )
    material_fingerprint = governed_material_fingerprint(
        prompt_id="test.passive",
        version="1",
        owner="reel_factory",
        purpose="fixture",
        provider="higgsfield",
        models=("kling3_0",),
        template_version="fixture.v1",
        builder_fingerprint=builder_fingerprint,
        compiler_source_fingerprint=compiler_source_fingerprint,
        template_source_fingerprint=template_source_fingerprint,
        input_contract="test.input.v1",
        output_contract="test.output.v1",
        compatibility="production",
        cost_behavior="provider_call",
        regression_fixtures=regression_fixtures,
    )
    return prompt_definition(
        prompt_id="test.passive",
        version="1",
        owner="reel_factory",
        purpose="fixture",
        provider="higgsfield",
        models=("kling3_0",),
        template_version="fixture.v1",
        builder_fingerprint=builder_fingerprint,
        compiler_source_fingerprint=compiler_source_fingerprint,
        template_source_fingerprint=template_source_fingerprint,
        input_contract="test.input.v1",
        output_contract="test.output.v1",
        approval={
            "state": state,
            "approvedBy": "operator",
            "approvedAt": "2026-01-01T00:00:00+00:00",
            "materialFingerprint": material_fingerprint,
        },
        effective_at="2026-01-02T00:00:00+00:00",
        retirement_at=retired,
        regression_fixtures=regression_fixtures,
    )


def test_registry_binds_exact_definition_inputs_and_compiled_prompt() -> None:
    registry = prompt_registry((_definition(),))
    first = bind_prompt_receipt(
        registry,
        prompt_id="test.passive",
        version="1",
        provider="higgsfield",
        model="kling3_0",
        compiled_prompt="Animate the approved creator calmly",
        input_fingerprint="a" * 64,
        at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    second = bind_prompt_receipt(
        registry,
        prompt_id="test.passive",
        version="1",
        provider="higgsfield",
        model="kling3_0",
        compiled_prompt="Animate the approved creator with a head turn",
        input_fingerprint="a" * 64,
        at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert first["registryFingerprint"] == registry["registryFingerprint"]
    assert (
        first["definitionFingerprint"]
        == registry["definitions"][0]["definitionFingerprint"]
    )
    assert first["compiledPromptFingerprint"] != second["compiledPromptFingerprint"]
    assert first["receiptFingerprint"] != second["receiptFingerprint"]


def test_unapproved_and_retired_prompts_fail_closed() -> None:
    with pytest.raises(PermissionError, match="not_approved"):
        _definition(state="pending")

    registry = prompt_registry((_definition(retired="2026-02-01T00:00:00+00:00"),))
    with pytest.raises(PermissionError, match="retired"):
        resolve_prompt(
            registry,
            prompt_id="test.passive",
            version="1",
            provider="higgsfield",
            model="kling3_0",
            at=datetime(2026, 2, 2, tzinfo=UTC),
        )


def test_registry_rejects_model_substitution_and_tampering() -> None:
    definition = _definition()
    registry = prompt_registry((definition,))
    with pytest.raises(PermissionError, match="model_mismatch"):
        resolve_prompt(
            registry,
            prompt_id="test.passive",
            version="1",
            provider="higgsfield",
            model="seedance_2_0",
            at=datetime(2026, 2, 1, tzinfo=UTC),
        )
    definition["purpose"] = "tampered"
    with pytest.raises(ValueError, match="fingerprint_invalid"):
        prompt_registry((definition,))


def test_receipt_requires_current_exact_registry_prompt_and_inputs() -> None:
    registry = prompt_registry((_definition(),))
    inputs = {"subjectSha256": "a" * 64}
    receipt = bind_prompt_receipt(
        registry,
        prompt_id="test.passive",
        version="1",
        provider="higgsfield",
        model="kling3_0",
        compiled_prompt="Animate the approved creator calmly",
        input_fingerprint=fingerprint(inputs),
        at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    verified = verify_prompt_receipt(
        registry,
        receipt,
        provider="higgsfield",
        model="kling3_0",
        compiled_prompt="Animate the approved creator calmly",
        inputs=inputs,
        at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert verified == receipt

    with pytest.raises(PermissionError, match="stale_or_material_mismatch"):
        verify_prompt_receipt(
            registry,
            receipt,
            provider="higgsfield",
            model="kling3_0",
            compiled_prompt="Animate a substituted creator",
            inputs=inputs,
            at=datetime(2026, 2, 1, tzinfo=UTC),
        )
    with pytest.raises(PermissionError, match="stale_or_material_mismatch"):
        verify_prompt_receipt(
            registry,
            receipt,
            provider="higgsfield",
            model="kling3_0",
            compiled_prompt="Animate the approved creator calmly",
            inputs={"subjectSha256": "b" * 64},
            at=datetime(2026, 2, 1, tzinfo=UTC),
        )


def test_approval_binds_source_and_real_regression_material() -> None:
    definition = _definition()
    changed = dict(definition)
    changed["compilerSourceFingerprint"] = "f" * 64
    core = {
        key: value for key, value in changed.items() if key != "definitionFingerprint"
    }
    changed["definitionFingerprint"] = fingerprint(core)
    with pytest.raises(PermissionError, match="approval_material_mismatch"):
        prompt_registry((changed,))


def test_python_source_and_regression_fingerprints_change_with_material(
    tmp_path: Path,
) -> None:
    source = tmp_path / "compiler.py"
    source.write_text(
        'TEMPLATE = "hello {name}"\n'
        "def compile_prompt(name):\n"
        "    return TEMPLATE.format(name=name)\n",
        encoding="utf-8",
    )
    first = python_source_fingerprint(
        source, source_id="fixture.compiler", symbols=("TEMPLATE", "compile_prompt")
    )
    source.write_text(
        'TEMPLATE = "hello {name}!"\n'
        "def compile_prompt(name):\n"
        "    return TEMPLATE.format(name=name)\n",
        encoding="utf-8",
    )
    second = python_source_fingerprint(
        source, source_id="fixture.compiler", symbols=("TEMPLATE", "compile_prompt")
    )
    assert first != second
    assert regression_fixture_hash(
        fixture_id="fixture.v1",
        inputs={"name": "Ada"},
        compiled_prompt="hello Ada",
    ) != regression_fixture_hash(
        fixture_id="fixture.v1",
        inputs={"name": "Ada"},
        compiled_prompt="hello Ada!",
    )
    symlink = tmp_path / "compiler-link.py"
    symlink.symlink_to(source)
    with pytest.raises(ValueError, match="prompt_source_file_invalid"):
        python_source_fingerprint(
            symlink,
            source_id="fixture.compiler",
            symbols=("TEMPLATE", "compile_prompt"),
        )
