from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from reel_factory.local_model_manager import (
    install_models,
    install_plan,
    install_runtime,
    model_status,
)
from reel_factory.local_video_models import (
    MLX_VIDEO_REVISION,
    MODEL_MANIFEST,
    local_install_dependency,
    local_video_model_spec,
)


def test_all_model_plan_deduplicates_ltx_shared_dependencies(tmp_path: Path) -> None:
    plan = install_plan([], models_root=tmp_path)
    assert len(plan["models"]) == 4
    dependency_ids = [value["id"] for value in plan["dependencies"]]
    assert dependency_ids.count("ltx23_shared_mlx") == 1
    assert dependency_ids.count("ltx23_gemma_text_encoder") == 1
    assert dependency_ids.count("wan_umt5_tokenizer") == 1
    assert plan["estimatedDownloadBytes"] > 150_000_000_000
    assert plan["generationDownloadsAllowed"] is False


def test_ltx_install_requires_explicit_license_ack_before_any_command(
    tmp_path: Path,
) -> None:
    called = False

    def runner(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("license gate must run before installer commands")

    with pytest.raises(PermissionError, match="license_acknowledgement_required"):
        install_models(
            ["local_ltx23_distilled_mlx"],
            models_root=tmp_path / "models",
            runtime_root=tmp_path / "runtime",
            runner=runner,
        )
    assert called is False


def test_model_status_fails_closed_on_revision_substitution(tmp_path: Path) -> None:
    spec = local_video_model_spec("local_wan22_ti2v_5b_mlx")
    directory = spec.directory(tmp_path)
    directory.mkdir(parents=True)
    for relative in spec.required_paths:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    files = [
        {
            "path": relative,
            "size": (directory / relative).stat().st_size,
            "sha256": "not-needed-for-shallow-status",
        }
        for relative in spec.required_paths
    ]
    (directory / MODEL_MANIFEST).write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_model_installation.v1",
                "modelId": spec.model_id,
                "repository": spec.repository,
                "revision": "substituted-revision",
                "runtimeRevision": MLX_VIDEO_REVISION,
                "files": files,
            }
        )
    )
    status = model_status(spec.model_id, models_root=tmp_path)
    assert status["ready"] is False
    assert "local_model_manifest_mismatch:revision" in status["issues"]


def test_model_status_detects_file_collision_or_truncation(tmp_path: Path) -> None:
    spec = local_video_model_spec("local_wan22_ti2v_5b_mlx")
    directory = spec.directory(tmp_path)
    directory.mkdir(parents=True)
    for relative in spec.required_paths:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    target = directory / spec.required_paths[0]
    records = [
        {
            "path": relative,
            "size": (directory / relative).stat().st_size,
            "sha256": "unused",
        }
        for relative in spec.required_paths
    ]
    (directory / MODEL_MANIFEST).write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_model_installation.v1",
                "modelId": spec.model_id,
                "repository": spec.repository,
                "revision": spec.revision,
                "runtimeRevision": MLX_VIDEO_REVISION,
                "files": records,
            }
        )
    )
    target.write_bytes(b"truncated")
    status = model_status(spec.model_id, models_root=tmp_path)
    assert status["ready"] is False
    assert any("file_size_mismatch" in value for value in status["issues"])


def test_deep_model_status_hashes_cache_only_dependencies(tmp_path: Path) -> None:
    spec = local_video_model_spec("local_wan22_ti2v_5b_mlx")
    directory = spec.directory(tmp_path)
    directory.mkdir(parents=True)
    records = []
    for relative in spec.required_paths:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
        records.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (directory / MODEL_MANIFEST).write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_model_installation.v1",
                "modelId": spec.model_id,
                "repository": spec.repository,
                "revision": spec.revision,
                "runtimeRevision": MLX_VIDEO_REVISION,
                "files": records,
            }
        )
    )
    dependency = local_install_dependency("wan_umt5_tokenizer")
    snapshot = tmp_path / "tokenizer-snapshot"
    snapshot.mkdir()
    tokenizer = snapshot / "tokenizer.json"
    tokenizer.write_bytes(b"original")
    receipt = tmp_path / ".receipts" / "wan_umt5_tokenizer.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "repository": dependency.repository,
                "revision": dependency.revision,
                "resolvedPath": str(snapshot),
                "files": [
                    {
                        "path": tokenizer.name,
                        "size": tokenizer.stat().st_size,
                        "sha256": hashlib.sha256(tokenizer.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )

    assert model_status(spec.model_id, models_root=tmp_path, deep=True)["ready"]
    tokenizer.write_bytes(b"changed!")  # Same size, different fingerprint.

    shallow = model_status(spec.model_id, models_root=tmp_path, deep=False)
    deep = model_status(spec.model_id, models_root=tmp_path, deep=True)
    assert shallow["ready"] is True
    assert deep["ready"] is False
    assert "local_model_dependency_missing:wan_umt5_tokenizer" in deep["issues"]


def test_runtime_install_resumes_exact_partial_with_frozen_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "mlx-video"
    partial = runtime.with_name("mlx-video.partial")
    partial.mkdir(parents=True)
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[:4] == ["git", "-C", str(partial), "rev-parse"]:
            return subprocess.CompletedProcess(
                command, 0, MLX_VIDEO_REVISION + "\n", ""
            )
        if command[:2] == ["uv", "sync"]:
            python = partial / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("runtime")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "reel_factory.local_model_manager.runtime_status",
        lambda **_kwargs: {"ready": True, "issues": []},
    )

    status = install_runtime(runtime_root=runtime, runner=runner)

    assert status["ready"] is True
    assert not any(command[:2] == ["git", "clone"] for command in commands)
    assert [
        "uv",
        "sync",
        "--frozen",
        "--no-dev",
        "--no-install-project",
        "--directory",
        str(partial),
    ] in commands
    assert [
        "uv",
        "pip",
        "install",
        "--python",
        str(partial / ".venv/bin/python"),
        "--no-deps",
        str(partial),
    ] in commands
    receipt = json.loads((runtime / ".creator-os-runtime.json").read_text())
    assert receipt["python"] == str(runtime / ".venv/bin/python")


def test_runtime_install_rejects_substituted_partial_before_sync(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "mlx-video"
    partial = runtime.with_name("mlx-video.partial")
    partial.mkdir(parents=True)
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "wrong-revision\n", "")

    with pytest.raises(FileExistsError, match="partial_revision_mismatch"):
        install_runtime(runtime_root=runtime, runner=runner)

    assert not any(command[:2] == ["uv", "sync"] for command in commands)
