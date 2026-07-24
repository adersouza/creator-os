from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from reel_factory import local_wan_prompt_expansion as expansion

EVIDENCE_SECRET = "prompt-expansion-test-secret-" + ("x" * 40)


@pytest.fixture(autouse=True)
def _evidence_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_OS_EVIDENCE_AUTH_SECRET", EVIDENCE_SECRET)


def _capability(tmp_path: Path) -> dict:
    model = tmp_path / "model"
    runtime = tmp_path / "runtime"
    worker = tmp_path / "worker.py"
    model.mkdir()
    runtime.mkdir()
    worker.write_text("# exact worker\n", encoding="utf-8")
    model_binding = {
        "modelId": expansion.PROMPT_EXPANDER_MODEL_ID,
        "repository": expansion.PROMPT_EXPANDER_MODEL_REPOSITORY,
        "revision": expansion.PROMPT_EXPANDER_MODEL_REVISION,
        "licenseId": expansion.PROMPT_EXPANDER_MODEL_LICENSE,
        "directory": str(model),
        "manifestSha256": "a" * 64,
        "deepVerified": True,
    }
    runtime_binding = {
        "repository": expansion.PROMPT_EXPANDER_RUNTIME_REPOSITORY,
        "revision": expansion.PROMPT_EXPANDER_RUNTIME_REVISION,
        "version": expansion.PROMPT_EXPANDER_RUNTIME_VERSION,
        "directory": str(runtime),
        "python": str(runtime / ".venv/bin/python"),
        "resolvedEnvironment": ["mlx-vlm==0.6.7"],
        "receiptSha256": "b" * 64,
    }
    implementation = {
        "path": str(worker),
        "sha256": expansion._sha256_file(worker),
    }
    return {
        "schema": "reel_factory.local_prompt_expander_capability.v1",
        "model": model_binding,
        "modelBindingFingerprint": expansion._fingerprint(model_binding),
        "runtime": runtime_binding,
        "runtimeBindingFingerprint": expansion._fingerprint(runtime_binding),
        "implementation": implementation,
        "implementationFingerprint": expansion._fingerprint(implementation),
        "ready": True,
        "issues": [],
        "generationDownloadsAllowed": False,
        "providerCalls": 0,
    }


def _expanded_text() -> str:
    return (
        "She shifts her weight toward one hip, turns her shoulders slightly toward "
        "the camera, then raises one hand to adjust her hair before lowering it. "
        "Her expression softens into a small smile while the camera makes a gentle "
        "steady push forward and the original room remains unchanged."
    )


def test_expansion_is_offline_deterministic_and_evidence_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "still.png"
    image.write_bytes(b"exact-image")
    sandbox = tmp_path / "sandbox-exec"
    sandbox.write_bytes(b"exact-sandbox")
    capability = _capability(tmp_path)
    monkeypatch.setattr(
        expansion,
        "prompt_expander_status",
        lambda **_kwargs: capability,
    )
    monkeypatch.setattr(expansion, "_sandbox_executable", lambda: sandbox)
    observed: dict = {}

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "schema": "reel_factory.local_wan_prompt_expansion_worker.v1",
                    "text": _expanded_text(),
                    "promptTokens": 210,
                    "generationTokens": 61,
                    "peakMemoryGb": 7.25,
                }
            ),
            stderr="",
        )

    receipt = expansion.expand_wan_i2v_prompt(
        image_path=image,
        original_prompt=(
            "Create natural confident movement with a small shoulder turn and "
            "gentle camera push"
        ),
        runner=runner,
    )

    assert receipt["expandedPrompt"] == _expanded_text()
    assert receipt["sourceImage"]["sha256"] == expansion._sha256_file(image)
    assert receipt["model"]["revision"] == expansion.PROMPT_EXPANDER_MODEL_REVISION
    assert receipt["providerCalls"] == 0
    assert receipt["productionWritesAllowed"] is False
    assert receipt["isolation"]["networkDenied"] is True
    assert observed["command"][0] == str(sandbox)
    assert "HF_HUB_OFFLINE" in observed["env"]
    assert "HF_TOKEN" not in observed["env"]
    assert "CREATOR_OS_EVIDENCE_AUTH_SECRET" not in observed["env"]
    core = dict(receipt)
    core.pop("producerAttestation")
    claimed = core.pop("expansionFingerprint")
    assert expansion._fingerprint(core) == claimed


def test_expansion_rejects_blink_only_or_short_output() -> None:
    with pytest.raises(
        expansion.WanPromptExpansionError,
        match="output_length_invalid",
    ):
        expansion._normalize_expanded_prompt("She blinks and breathes.")
    with pytest.raises(
        expansion.WanPromptExpansionError,
        match="blink_only_output_rejected",
    ):
        expansion._normalize_expanded_prompt(
            "She blinks naturally and keeps breathing softly while the camera "
            "holds the portrait steadily. Her expression stays calm and her face "
            "remains stable throughout the continuous shot as the room and light "
            "remain completely unchanged behind her."
        )


def test_expansion_strips_only_the_known_mlx_qwen_prefix() -> None:
    text, normalization = expansion._normalize_expanded_prompt(
        "<|im_start|>\n addCriterion\n" + _expanded_text()
    )
    assert text == _expanded_text()
    assert normalization["knownPrefixRemoved"] == "mlx_qwen_add_criterion_v1"
    with pytest.raises(
        expansion.WanPromptExpansionError,
        match="not_plain_prose",
    ):
        expansion._normalize_expanded_prompt("<|tool|>\n" + _expanded_text())


@pytest.mark.parametrize(
    "motion",
    (
        "adjusting",
        "crossing",
        "glancing",
        "nodding",
        "pivoting",
        "swaying",
        "walking",
    ),
)
def test_expansion_accepts_natural_dynamic_motion_forms(motion: str) -> None:
    text = (
        f"The woman begins {motion} naturally while keeping her face stable and "
        "her gaze near the camera. Her shoulders follow the action with subtle "
        "secondary movement as her hair responds realistically. The framing and "
        "lighting remain unchanged, and the steady camera preserves the original "
        "composition throughout the short sequence."
    )
    normalized, _normalization = expansion._normalize_expanded_prompt(text)
    assert normalized == text


def test_receipt_rejects_source_substitution_and_capability_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "still.png"
    image.write_bytes(b"exact-image")
    sandbox = tmp_path / "sandbox-exec"
    sandbox.write_bytes(b"exact-sandbox")
    capability = _capability(tmp_path)
    monkeypatch.setattr(expansion, "_sandbox_executable", lambda: sandbox)
    monkeypatch.setattr(
        expansion,
        "prompt_expander_status",
        lambda **_kwargs: capability,
    )

    def runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "schema": "reel_factory.local_wan_prompt_expansion_worker.v1",
                    "text": _expanded_text(),
                    "promptTokens": 210,
                    "generationTokens": 61,
                    "peakMemoryGb": 7.25,
                }
            ),
            stderr="",
        )

    receipt = expansion.expand_wan_i2v_prompt(
        image_path=image,
        original_prompt=(
            "Create natural confident movement with a small shoulder turn and "
            "gentle camera push"
        ),
        runner=runner,
    )
    expansion.validate_wan_prompt_expansion(
        receipt,
        image_path=image,
        expanded_prompt=_expanded_text(),
    )

    forged = deepcopy(receipt)
    forged["producerAttestation"]["signature"] = "0" * 64
    with pytest.raises(
        expansion.WanPromptExpansionError,
        match="attestation_invalid",
    ):
        expansion.validate_wan_prompt_expansion(
            forged,
            image_path=image,
            expanded_prompt=_expanded_text(),
        )

    image.write_bytes(b"substituted-image")
    with pytest.raises(
        expansion.WanPromptExpansionError,
        match="source_image_mismatch",
    ):
        expansion.validate_wan_prompt_expansion(
            receipt,
            image_path=image,
            expanded_prompt=_expanded_text(),
        )

    image.write_bytes(b"exact-image")
    drifted = deepcopy(capability)
    drifted["implementationFingerprint"] = "f" * 64
    monkeypatch.setattr(
        expansion,
        "prompt_expander_status",
        lambda **_kwargs: drifted,
    )
    with pytest.raises(
        expansion.WanPromptExpansionError,
        match="implementationFingerprint_drift",
    ):
        expansion.validate_wan_prompt_expansion(
            receipt,
            image_path=image,
            expanded_prompt=_expanded_text(),
        )


def test_catalog_uses_commercially_usable_official_wan_qwen_size() -> None:
    assert expansion.PROMPT_EXPANDER_MODEL_REPOSITORY.endswith(
        "Qwen2.5-VL-7B-Instruct-4bit"
    )
    assert expansion.PROMPT_EXPANDER_MODEL_LICENSE == "apache-2.0"
    assert expansion.PROMPT_EXPANDER_MODEL_ESTIMATED_BYTES > 5_000_000_000


def test_runtime_environment_normalizes_staging_path(tmp_path: Path) -> None:
    runtime = tmp_path / "mlx-vlm"
    staging = tmp_path / "mlx-vlm.partial"
    result = expansion._normalized_environment(
        [f"mlx-vlm @ file://{staging}", "mlx==1.0"],
        runtime=runtime,
        staging=staging,
    )
    assert result == [f"mlx-vlm @ file://{runtime}", "mlx==1.0"]


def test_deep_verification_cache_avoids_rehash_until_stat_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models_root = tmp_path / "models"
    model = models_root / expansion.PROMPT_EXPANDER_MODEL_DIRECTORY
    model.mkdir(parents=True)
    for index, relative in enumerate(expansion._REQUIRED_MODEL_PATHS):
        path = model / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"model-file-{index}".encode())
    manifest = {
        "schema": "reel_factory.local_prompt_expander_model_installation.v1",
        "modelId": expansion.PROMPT_EXPANDER_MODEL_ID,
        "repository": expansion.PROMPT_EXPANDER_MODEL_REPOSITORY,
        "revision": expansion.PROMPT_EXPANDER_MODEL_REVISION,
        "licenseId": expansion.PROMPT_EXPANDER_MODEL_LICENSE,
        "quantization": "4bit",
        "files": expansion._file_records(model),
    }
    (model / expansion._MODEL_MANIFEST).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    runtime = tmp_path / "runtime"
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_receipt = {
        "schema": "reel_factory.local_prompt_expander_runtime_installation.v1",
        "repository": expansion.PROMPT_EXPANDER_RUNTIME_REPOSITORY,
        "revision": expansion.PROMPT_EXPANDER_RUNTIME_REVISION,
        "version": expansion.PROMPT_EXPANDER_RUNTIME_VERSION,
        "python": str(python),
        "resolvedEnvironment": ["mlx-vlm==0.6.7"],
    }
    (runtime / expansion._RUNTIME_RECEIPT).write_text(
        json.dumps(runtime_receipt),
        encoding="utf-8",
    )

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if command[:3] == ["git", "-C", str(runtime)]:
            stdout = expansion.PROMPT_EXPANDER_RUNTIME_REVISION + "\n"
        elif command[:2] == [str(python), "-c"]:
            stdout = expansion.PROMPT_EXPANDER_RUNTIME_VERSION + "\n"
        else:
            assert command[:3] == ["uv", "pip", "freeze"]
            stdout = "mlx-vlm==0.6.7\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(expansion.subprocess, "run", fake_run)
    monkeypatch.setattr(expansion.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(expansion.platform, "machine", lambda: "arm64")

    first = expansion.prompt_expander_status(
        models_root=models_root,
        runtime_root=runtime,
        deep=True,
    )
    assert first["ready"] is True
    assert first["deepVerificationCacheHit"] is False

    original_sha = expansion._sha256_file
    model_hashes = 0

    def counted_sha(path: Path) -> str:
        nonlocal model_hashes
        if path.parent == model and path.name != expansion._MODEL_MANIFEST:
            model_hashes += 1
        return original_sha(path)

    monkeypatch.setattr(expansion, "_sha256_file", counted_sha)
    second = expansion.prompt_expander_status(
        models_root=models_root,
        runtime_root=runtime,
        deep=True,
    )
    assert second["ready"] is True
    assert second["deepVerificationCacheHit"] is True
    assert model_hashes == 0
