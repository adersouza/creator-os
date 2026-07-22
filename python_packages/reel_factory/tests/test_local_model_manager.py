from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from reel_factory.local_model_manager import (
    _longcat_runtime_status,
    all_model_status,
    install_models,
    install_plan,
    install_runtime,
    model_status,
    runtime_status,
)
from reel_factory.local_video_models import (
    LONGCAT_MLX_REPOSITORY,
    LONGCAT_MLX_REVISION,
    MLX_VIDEO_REPOSITORY,
    MLX_VIDEO_REVISION,
    MODEL_MANIFEST,
    local_install_dependency,
    local_video_model_spec,
)


def test_all_model_plan_deduplicates_ltx_shared_dependencies(tmp_path: Path) -> None:
    plan = install_plan([], models_root=tmp_path)
    assert len(plan["models"]) == 5
    dependency_ids = [value["id"] for value in plan["dependencies"]]
    assert dependency_ids.count("ltx23_shared_mlx") == 1
    assert dependency_ids.count("ltx23_gemma_text_encoder") == 1
    assert dependency_ids.count("wan_umt5_tokenizer") == 1
    assert plan["estimatedDownloadBytes"] > 175_000_000_000
    assert plan["generationDownloadsAllowed"] is False


def test_longcat_plan_is_pinned_mit_and_experimental(tmp_path: Path) -> None:
    plan = install_plan(["local_longcat_avatar15_q4_mlx"], models_root=tmp_path)
    [model] = plan["models"]
    assert model["revision"] == "5d5b5d61ce6c206930a94c760f6941aff03f9389"
    assert model["license_id"] == "mit"
    assert model["family"] == "longcat_avatar"
    assert model["estimated_bytes"] > 25_000_000_000


def test_install_plan_does_not_charge_installed_artifacts_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "reel_factory.local_model_manager.model_status",
        lambda *_args, **_kwargs: {"ready": True, "issues": []},
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager._dependency_ready",
        lambda *_args, **_kwargs: True,
    )
    plan = install_plan(["local_ltx23_distilled_mlx"], models_root=tmp_path)
    assert plan["selectedArtifactBytes"] > 0
    assert plan["installedArtifactEstimateBytes"] == plan["selectedArtifactBytes"]
    assert plan["estimatedDownloadBytes"] == 0
    assert plan["requiredFreeBytes"] == 0
    assert plan["spaceReady"] is True


def test_all_model_status_requires_matching_family_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "reel_factory.local_model_manager.model_status",
        lambda model_id, **_kwargs: {
            "modelId": model_id,
            "ready": True,
            "issues": [],
        },
    )

    def fake_runtime_status(*, family="wan_2", **_kwargs):
        return {
            "ready": family == "longcat_avatar",
            "issues": [] if family == "longcat_avatar" else ["runtime_drift"],
        }

    monkeypatch.setattr(
        "reel_factory.local_model_manager.runtime_status", fake_runtime_status
    )
    status = all_model_status()
    assert len(status["installedModelIds"]) == 5
    assert status["readyModelIds"] == ["local_longcat_avatar15_q4_mlx"]
    assert all(
        not value["ready"]
        for value in status["models"]
        if value["family"] != "longcat_avatar"
    )


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


def test_mlx_runtime_status_rejects_resolved_environment_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "mlx-video"
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("runtime")
    (runtime / ".creator-os-runtime.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_mlx_runtime_installation.v1",
                "repository": MLX_VIDEO_REPOSITORY,
                "revision": MLX_VIDEO_REVISION,
                "python": str(python),
                "resolvedEnvironment": [
                    f"mlx-video @ creator-os-pinned-source:{MLX_VIDEO_REVISION}"
                ],
            }
        )
    )

    def fake_run(command, **_kwargs):
        if command[:3] == ["git", "-C", str(runtime)]:
            return subprocess.CompletedProcess(command, 0, MLX_VIDEO_REVISION, "")
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                command, 0, "mlx-video @ file:///tmp/substituted-runtime\n", ""
            )
        if command[0] == str(python):
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("reel_factory.local_model_manager.subprocess.run", fake_run)
    monkeypatch.setattr(
        "reel_factory.local_model_manager.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager.platform.machine", lambda: "arm64"
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager.shutil.which", lambda _name: "/usr/bin/tool"
    )

    status = runtime_status(runtime_root=runtime)
    assert status["ready"] is False
    assert "mlx_video_runtime_environment_drift" in status["issues"]


def test_longcat_runtime_install_is_separate_pinned_and_records_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "longcat-avatar-mlx"
    partial = runtime.with_name("longcat-avatar-mlx.partial")
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[:2] == ["uv", "venv"]:
            python = partial / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("runtime")
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(command, 0, "mlx==0.32.0\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "reel_factory.local_model_manager._longcat_runtime_status",
        lambda **_kwargs: {"ready": True, "issues": []},
    )
    status = install_runtime(
        runtime_root=runtime, family="longcat_avatar", runner=runner
    )
    assert status["ready"] is True
    assert [
        "git",
        "-C",
        str(partial),
        "checkout",
        "--detach",
        LONGCAT_MLX_REVISION,
    ] in commands
    receipt = json.loads((runtime / ".creator-os-runtime.json").read_text())
    assert receipt["runtimeId"] == "longcat_avatar"
    assert receipt["revision"] == LONGCAT_MLX_REVISION
    assert receipt["requirements"]


def test_longcat_runtime_status_rejects_resolved_environment_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "longcat-avatar-mlx"
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("runtime")
    (runtime / ".creator-os-runtime.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_mlx_runtime_installation.v1",
                "runtimeId": "longcat_avatar",
                "repository": LONGCAT_MLX_REPOSITORY,
                "revision": LONGCAT_MLX_REVISION,
                "python": str(python),
                "requirements": [
                    "mlx==0.32.0",
                    "mlx-arsenal==0.10.1",
                    "safetensors==0.8.0",
                    "huggingface-hub==0.36.0",
                    "numpy==2.3.5",
                    "transformers==4.57.3",
                    "librosa==0.11.0",
                    "Pillow==12.3.0",
                    "imageio==2.37.4",
                    "imageio-ffmpeg==0.6.0",
                ],
                "resolvedEnvironment": [
                    "longcat-video-avatar-mlx @ creator-os-pinned-source:"
                    + LONGCAT_MLX_REVISION
                ],
            }
        )
    )

    def fake_run(command, **_kwargs):
        if command[:3] == ["git", "-C", str(runtime)]:
            return subprocess.CompletedProcess(command, 0, LONGCAT_MLX_REVISION, "")
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                "longcat-video-avatar-mlx @ file:///tmp/substituted-runtime\n",
                "",
            )
        if command[0] == str(python):
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("reel_factory.local_model_manager.subprocess.run", fake_run)
    monkeypatch.setattr(
        "reel_factory.local_model_manager.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager.platform.machine", lambda: "arm64"
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager.shutil.which", lambda _name: "/usr/bin/tool"
    )

    status = _longcat_runtime_status(runtime_root=runtime)
    assert status["ready"] is False
    assert "longcat_mlx_runtime_environment_drift" in status["issues"]
