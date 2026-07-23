from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from creator_os_core.fileops import file_lock
from reel_factory.local_model_manager import (
    _dependency_ready,
    _install_dependency,
    _longcat_runtime_status,
    all_model_status,
    install_models,
    install_plan,
    install_runtime,
    legacy_storage_report,
    model_status,
    runtime_status,
)
from reel_factory.local_video_models import (
    LONGCAT_MLX_REPOSITORY,
    LONGCAT_MLX_REVISION,
    LTX_MLX_REPOSITORY,
    LTX_MLX_REVISION,
    MLX_VIDEO_REPOSITORY,
    MLX_VIDEO_REVISION,
    MODEL_MANIFEST,
    LocalInstallDependency,
    local_install_dependency,
    local_video_model_spec,
)


def _cache_only_dependency_fixture(
    root: Path,
) -> tuple[LocalInstallDependency, Path, Path]:
    dependency = local_install_dependency("wan_umt5_tokenizer")
    repository_root = root / ".hf-home/hub/models--google--umt5-xxl"
    snapshot = repository_root / "snapshots" / dependency.revision
    snapshot.mkdir(parents=True)
    files = []
    tokenizer = snapshot / "tokenizer.json"
    for relative in dependency.required_paths:
        path = snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"original" if relative == "tokenizer.json" else relative.encode()
        )
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    receipt = root / ".receipts" / "wan_umt5_tokenizer.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "repository": dependency.repository,
                "revision": dependency.revision,
                "resolvedPath": str(snapshot),
                "files": files,
            }
        )
    )
    return dependency, tokenizer, repository_root / "refs/main"


def _cache_dependency_receipt(root: Path) -> Path:
    return root / ".receipts" / "wan_umt5_tokenizer.json"


def test_all_model_plan_deduplicates_quantized_ltx_dependencies(tmp_path: Path) -> None:
    plan = install_plan([], models_root=tmp_path)
    assert len(plan["models"]) == 5
    dependency_ids = [value["id"] for value in plan["dependencies"]]
    assert dependency_ids.count("ltx23_gemma_text_encoder") == 1
    assert dependency_ids.count("wan_umt5_tokenizer") == 1
    assert plan["estimatedDownloadBytes"] > 100_000_000_000
    assert plan["generationDownloadsAllowed"] is False


def test_longcat_plan_is_pinned_mit_and_experimental(tmp_path: Path) -> None:
    plan = install_plan(["local_longcat_avatar15_q4_mlx"], models_root=tmp_path)
    [model] = plan["models"]
    assert model["revision"] == "5d5b5d61ce6c206930a94c760f6941aff03f9389"
    assert model["license_id"] == "mit"
    assert model["family"] == "longcat_avatar"
    assert model["estimated_bytes"] > 25_000_000_000


def test_legacy_ltx_storage_report_is_non_destructive(tmp_path: Path) -> None:
    legacy = tmp_path / "LTX-2.3-dev-MLX"
    legacy.mkdir()
    (legacy / "weights.safetensors").write_bytes(b"legacy")
    report = legacy_storage_report(models_root=tmp_path)
    assert report["candidateBytes"] == len(b"legacy")
    assert report["deletionPerformed"] is False
    assert report["destructiveActionAvailable"] is False
    assert report["candidates"][0]["deletionAllowed"] is False
    assert (legacy / "weights.safetensors").read_bytes() == b"legacy"


def test_storage_report_covers_partial_orphan_and_unpinned_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = tmp_path / "Wan2.2-TI2V-5B.partial"
    orphan = tmp_path / "LTX-2.3.orphan.123"
    snapshot = tmp_path / ".hf-home/hub/models--example--model/snapshots/unpinned"
    for directory in (partial, orphan, snapshot):
        directory.mkdir(parents=True)
        (directory / "artifact.bin").write_bytes(b"evidence")
    monkeypatch.setenv("CREATOR_OS_LOCAL_MODELS_ROOT", str(tmp_path))

    report = legacy_storage_report(models_root=tmp_path)

    classifications = {value["classification"] for value in report["candidates"]}
    assert "incomplete_model_install_staging" in classifications
    assert "preserved_model_install_orphan" in classifications
    assert "unreferenced_huggingface_snapshot_revision" in classifications
    assert report["configuredRoots"]["environmentOverrides"][
        "CREATOR_OS_LOCAL_MODELS_ROOT"
    ] == str(tmp_path)
    assert report["deletionPerformed"] is False


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


def test_model_installer_process_lock_fails_closed_before_commands(
    tmp_path: Path,
) -> None:
    root = tmp_path / "models"
    called = False

    def runner(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("contended installer must not execute commands")

    with file_lock(root / ".creator-os-model-installer", blocking=False):
        with pytest.raises(RuntimeError, match="local_model_installer_busy"):
            install_models(
                ["local_wan22_ti2v_5b_mlx"],
                models_root=root,
                accepted_licenses=(),
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
            "sha256": "0" * 64,
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
    dependency, tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    missing_reference = model_status(spec.model_id, models_root=tmp_path, deep=True)
    assert missing_reference["ready"] is False
    assert (
        "local_model_dependency_runtime_reference_missing:wan_umt5_tokenizer"
        in missing_reference["issues"]
    )
    repair_plan = install_plan([spec.model_id], models_root=tmp_path)
    assert repair_plan["models"][0]["installed"] is True
    assert repair_plan["dependencies"][0]["repairRequired"] is True
    assert repair_plan["estimatedDownloadBytes"] == 0
    reference.parent.mkdir(parents=True)
    reference.write_text(dependency.revision)

    first_verified = model_status(spec.model_id, models_root=tmp_path, deep=True)
    assert first_verified["ready"]
    assert first_verified["deepVerificationCacheHit"] is False
    cached = model_status(spec.model_id, models_root=tmp_path, deep=True)
    assert cached["ready"]
    assert cached["deepVerificationCacheHit"] is True
    assert (
        cached["deepVerificationReceipt"]["verificationFingerprint"]
        == first_verified["deepVerificationReceipt"]["verificationFingerprint"]
    )
    model_file = directory / spec.required_paths[0]
    original_model_bytes = model_file.read_bytes()
    model_file.write_bytes(b"x" * len(original_model_bytes))
    substituted = model_status(spec.model_id, models_root=tmp_path, deep=True)
    assert substituted["ready"] is False
    assert (
        f"local_model_file_hash_mismatch:{spec.required_paths[0]}"
        in substituted["issues"]
    )
    model_file.write_bytes(original_model_bytes)
    assert model_status(spec.model_id, models_root=tmp_path, deep=True)["ready"]
    tokenizer.write_bytes(b"changed!")  # Same size, different fingerprint.

    shallow = model_status(spec.model_id, models_root=tmp_path, deep=False)
    deep = model_status(spec.model_id, models_root=tmp_path, deep=True)
    assert shallow["ready"] is True
    assert deep["ready"] is False
    assert "local_model_dependency_missing:wan_umt5_tokenizer" in deep["issues"]


def test_cache_only_dependency_requires_runtime_reference(tmp_path: Path) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)

    assert not reference.exists()
    assert _dependency_ready(dependency, tmp_path, deep=True) is False
    assert (
        _dependency_ready(
            dependency,
            tmp_path,
            deep=True,
            require_runtime_reference=False,
        )
        is True
    )


def test_cache_only_dependency_rejects_incomplete_receipt_before_reference_repair(
    tmp_path: Path,
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    receipt = _cache_dependency_receipt(tmp_path)
    payload = json.loads(receipt.read_text())
    payload["files"] = payload["files"][1:]
    receipt.write_text(json.dumps(payload))

    assert not _dependency_ready(
        dependency, tmp_path, deep=True, require_runtime_reference=False
    )
    with pytest.raises(AssertionError, match="incomplete receipt must download"):
        _install_dependency(
            dependency,
            root=tmp_path,
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("incomplete receipt must download")
            ),
        )
    assert not reference.exists()


@pytest.mark.parametrize("unsafe_path", ("/tmp/tokenizer.json", "../tokenizer.json"))
def test_cache_only_dependency_rejects_unsafe_receipt_paths(
    tmp_path: Path, unsafe_path: str
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    receipt = _cache_dependency_receipt(tmp_path)
    payload = json.loads(receipt.read_text())
    payload["files"][0]["path"] = unsafe_path
    receipt.write_text(json.dumps(payload))

    assert not _dependency_ready(
        dependency, tmp_path, deep=True, require_runtime_reference=False
    )
    assert not reference.exists()


def test_cache_only_dependency_rejects_duplicate_receipt_paths(
    tmp_path: Path,
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    receipt = _cache_dependency_receipt(tmp_path)
    payload = json.loads(receipt.read_text())
    payload["files"].append(dict(payload["files"][0]))
    receipt.write_text(json.dumps(payload))

    assert not _dependency_ready(
        dependency, tmp_path, deep=True, require_runtime_reference=False
    )
    assert not reference.exists()


def test_cache_only_dependency_rejects_symlink_receipt(tmp_path: Path) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    receipt = _cache_dependency_receipt(tmp_path)
    target = tmp_path / "receipt-target.json"
    target.write_text(receipt.read_text())
    receipt.unlink()
    receipt.symlink_to(target)

    assert not _dependency_ready(
        dependency, tmp_path, deep=True, require_runtime_reference=False
    )
    assert not reference.exists()


def test_cache_only_dependency_repairs_reference_without_download(
    tmp_path: Path,
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)

    def runner(*_args, **_kwargs):
        raise AssertionError("verified cache-reference repair must not download")

    result = _install_dependency(dependency, root=tmp_path, runner=runner)

    assert result["status"] == "repaired_runtime_reference"
    assert reference.read_text() == dependency.revision
    assert _dependency_ready(dependency, tmp_path, deep=True) is True


def test_cache_only_dependency_canonicalizes_matching_reference_whitespace(
    tmp_path: Path,
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    reference.parent.mkdir(parents=True)
    reference.write_text(dependency.revision + "\n")

    result = _install_dependency(
        dependency,
        root=tmp_path,
        runner=lambda *_args, **_kwargs: pytest.fail("repair must not download"),
    )

    assert result["status"] == "repaired_runtime_reference"
    assert reference.read_text() == dependency.revision
    assert _dependency_ready(dependency, tmp_path, deep=True) is True


def test_install_plan_classifies_verified_reference_repair_as_zero_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cache_only_dependency_fixture(tmp_path)
    monkeypatch.setattr(
        "reel_factory.local_model_manager.model_status",
        lambda *_args, **_kwargs: {"ready": True, "issues": []},
    )

    plan = install_plan(["local_wan22_ti2v_5b_mlx"], models_root=tmp_path)

    [dependency] = plan["dependencies"]
    assert dependency["installed"] is True
    assert dependency["ready"] is False
    assert dependency["repairRequired"] is True
    assert plan["estimatedDownloadBytes"] == 0


def test_cache_only_dependency_rejects_conflicting_reference(
    tmp_path: Path,
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    reference.parent.mkdir(parents=True)
    reference.write_text("0" * 40 + "\n")

    def runner(*_args, **_kwargs):
        raise AssertionError("conflicting reference must not download")

    with pytest.raises(RuntimeError, match="local_model_dependency_reference_conflict"):
        _install_dependency(
            dependency,
            root=tmp_path,
            runner=runner,
        )

    assert reference.read_text() == "0" * 40 + "\n"


@pytest.mark.parametrize("reference_kind", ("directory", "symlink", "broken_symlink"))
def test_cache_only_dependency_rejects_unsafe_runtime_reference(
    tmp_path: Path, reference_kind: str
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    reference.parent.mkdir(parents=True)
    if reference_kind == "directory":
        reference.mkdir()
    else:
        target = tmp_path / "reference-target"
        if reference_kind == "symlink":
            target.write_text(dependency.revision)
        reference.symlink_to(target)

    with pytest.raises(RuntimeError, match="local_model_dependency_reference_unsafe"):
        _install_dependency(
            dependency,
            root=tmp_path,
            runner=lambda *_args, **_kwargs: pytest.fail("repair must not download"),
        )


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


def test_ltx_runtime_install_is_exact_frozen_and_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "ltx-2-mlx"
    partial = runtime.with_name("ltx-2-mlx.partial")
    partial.mkdir(parents=True)
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[:2] == ["git", "-C"] and command[3:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, LTX_MLX_REVISION + "\n", "")
        if command[:2] == ["uv", "sync"]:
            target = Path(command[-1])
            python = target / ".venv/bin/python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("runtime")
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                (
                    f"-e {(runtime / 'packages/ltx-core-mlx').as_uri()}\n"
                    f"-e {(runtime / 'packages/ltx-pipelines-mlx').as_uri()}\n"
                ),
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "reel_factory.local_model_manager._ltx_runtime_status",
        lambda **_kwargs: {"ready": True, "issues": []},
    )
    status = install_runtime(runtime_root=runtime, family="ltx_2", runner=runner)
    assert status["ready"] is True
    assert [
        "uv",
        "sync",
        "--frozen",
        "--no-dev",
        "--directory",
        str(partial),
    ] in commands
    assert [
        "uv",
        "sync",
        "--frozen",
        "--no-dev",
        "--directory",
        str(runtime),
    ] in commands
    receipt = json.loads((runtime / ".creator-os-runtime.json").read_text())
    assert receipt["runtimeId"] == "ltx_2_mlx"
    assert receipt["repository"] == LTX_MLX_REPOSITORY
    assert receipt["revision"] == LTX_MLX_REVISION
    assert all(".partial" not in value for value in receipt["resolvedEnvironment"])
    assert receipt["resolvedEnvironment"] == [
        f"ltx-core-mlx @ creator-os-pinned-source:{LTX_MLX_REVISION}",
        f"ltx-pipelines-mlx @ creator-os-pinned-source:{LTX_MLX_REVISION}",
    ]


def test_ltx_runtime_install_repairs_promoted_editable_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "ltx-2-mlx"
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("runtime")
    (runtime / ".creator-os-runtime.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_mlx_runtime_installation.v1",
                "runtimeId": "ltx_2_mlx",
                "repository": LTX_MLX_REPOSITORY,
                "revision": LTX_MLX_REVISION,
                "python": str(python),
                "resolvedEnvironment": [
                    "-e file:///tmp/ltx-2-mlx.partial/packages/ltx-core-mlx"
                ],
            }
        )
    )
    statuses = iter(
        [
            {"ready": False, "issues": ["ltx_mlx_runtime_environment_drift"]},
            {"ready": True, "issues": []},
        ]
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager._ltx_runtime_status",
        lambda **_kwargs: next(statuses),
    )
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(command, 0, LTX_MLX_REVISION + "\n", "")
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                f"-e {(runtime / 'packages/ltx-core-mlx').as_uri()}\n",
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    status = install_runtime(runtime_root=runtime, family="ltx_2", runner=runner)

    assert status["ready"] is True
    assert [
        "uv",
        "sync",
        "--frozen",
        "--no-dev",
        "--directory",
        str(runtime),
    ] in commands
    receipt = json.loads((runtime / ".creator-os-runtime.json").read_text())
    assert receipt["resolvedEnvironment"] == [
        f"ltx-core-mlx @ creator-os-pinned-source:{LTX_MLX_REVISION}"
    ]


def test_ltx_runtime_status_rejects_temporary_path_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "ltx-2-mlx"
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("runtime")
    (runtime / ".creator-os-runtime.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.local_mlx_runtime_installation.v1",
                "runtimeId": "ltx_2_mlx",
                "repository": LTX_MLX_REPOSITORY,
                "revision": LTX_MLX_REVISION,
                "python": str(python),
                "resolvedEnvironment": [
                    f"-e {runtime.with_name('ltx-2-mlx.partial').as_uri()}"
                    "/packages/ltx-core-mlx"
                ],
            }
        )
    )

    def fake_run(command, **_kwargs):
        if command[:3] == ["git", "-C", str(runtime)]:
            return subprocess.CompletedProcess(command, 0, LTX_MLX_REVISION, "")
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                f"-e {(runtime / 'packages/ltx-core-mlx').as_uri()}\n",
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("reel_factory.local_model_manager.subprocess.run", fake_run)

    status = runtime_status(runtime_root=runtime, family="ltx_2")

    assert status["ready"] is False
    assert "ltx_mlx_runtime_receipt_temporary_path" in status["issues"]
    assert "ltx_mlx_runtime_worktree_dirty" in status["issues"]


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
    assert "mlx_video_runtime_worktree_dirty" in status["issues"]


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
    assert len(receipt["requirementsFingerprint"]) == 64


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
    assert "longcat_mlx_runtime_worktree_dirty" in status["issues"]
