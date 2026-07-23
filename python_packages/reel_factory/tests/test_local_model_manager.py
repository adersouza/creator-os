from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from creator_os_core.fileops import file_lock
from reel_factory.local_generation_queue import fingerprint
from reel_factory.local_model_manager import (
    _dependency_ready,
    _git_worktree_issue,
    _install_dependency,
    _load_deep_verification_cache,
    _longcat_runtime_status,
    _runtime_probe_environment,
    _umt5_semantic_preflight,
    _verified_runtime_binding,
    _write_deep_verification_cache,
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


_UMT5_TOKEN_IDS = [
    [5991, 38700, 4709, 82892, 30463, 274, 348, 14221, 1908, 333, 80405, 274, 1],
    [23231, 275, 3914, 332, 16349, 103613, 274, 1],
    [12831, 645, 22964, 645, 11124, 182944, 1],
    [5100, 1249, 5100, 2816, 1],
    [156081, 5452, 200932, 1561, 8584, 1],
]
_UMT5_PRETOKENIZER = (
    'Sequence(pretokenizers=[WhitespaceSplit(), Metaspace(replacement="▁", '
    "prepend_scheme=always, split=True)])"
)


def _umt5_probe_output(
    *,
    alias_ids: list[list[int]] | None = None,
    local_ids: list[list[int]] | None = None,
) -> str:
    def record(label: str, token_ids: list[list[int]]) -> dict[str, object]:
        digest = hashlib.sha256(
            json.dumps(token_ids, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "label": label,
            "class": "T5Tokenizer",
            "isFast": True,
            "fixMistralRegex": None,
            "preTokenizer": _UMT5_PRETOKENIZER,
            "tokenIds": token_ids,
            "tokenIdsSha256": digest,
        }

    return json.dumps(
        {
            "schema": "reel_factory.umt5_semantic_probe_output.v1",
            "isolation": {
                "writeOpenDenied": True,
                "localNetworkBindDenied": True,
            },
            "records": [
                record("alias-default", alias_ids or _UMT5_TOKEN_IDS),
                record("local-default", local_ids or _UMT5_TOKEN_IDS),
            ],
        }
    )


def test_deep_cache_is_invalidated_by_toolchain_fingerprint_change(
    tmp_path: Path,
) -> None:
    runtime_binding = {
        "runtimeId": "fixture",
        "ffmpegSha256": "a" * 64,
        "ffprobeSha256": "b" * 64,
    }
    runtime_fingerprint = fingerprint(runtime_binding)
    core = {
        "manifestSha256": "c" * 64,
        "statSnapshotFingerprint": "d" * 64,
        "runtimeBindingFingerprint": runtime_fingerprint,
    }
    receipt = {**core, "verificationFingerprint": fingerprint(core)}
    _write_deep_verification_cache(
        root=tmp_path, model_id="fixture-model", receipt=receipt
    )
    assert (
        _load_deep_verification_cache(
            root=tmp_path,
            model_id="fixture-model",
            manifest_sha256="c" * 64,
            stat_snapshot_fingerprint="d" * 64,
            runtime_binding_fingerprint=runtime_fingerprint,
        )
        == receipt
    )
    changed_toolchain = fingerprint({**runtime_binding, "ffmpegSha256": "e" * 64})
    assert (
        _load_deep_verification_cache(
            root=tmp_path,
            model_id="fixture-model",
            manifest_sha256="c" * 64,
            stat_snapshot_fingerprint="d" * 64,
            runtime_binding_fingerprint=changed_toolchain,
        )
        is None
    )


def test_runtime_probe_environment_strips_caller_python_paths_and_secrets() -> None:
    environment = _runtime_probe_environment(
        {
            "HOME": "/tmp/home",
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": "/tmp/substituted-source",
            "CREATOR_OS_EVIDENCE_AUTH_SECRET": "must-not-leak",
        }
    )

    assert environment["HOME"] == "/tmp/home"
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert "PYTHONPATH" not in environment
    assert "CREATOR_OS_EVIDENCE_AUTH_SECRET" not in environment


def test_umt5_semantic_preflight_binds_matching_alias_under_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    reference.parent.mkdir(parents=True)
    reference.write_text(dependency.revision)
    python = tmp_path / "runtime-python"
    python.write_text("python")
    sandbox = tmp_path / "sandbox-exec"
    sandbox.write_text("sandbox")
    monkeypatch.setattr(
        "reel_factory.local_model_manager._UMT5_SANDBOX_EXECUTABLE", sandbox
    )
    observed: dict[str, object] = {}

    def runner(command, **kwargs):
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, _umt5_probe_output(), "")

    evidence = _umt5_semantic_preflight(
        root=tmp_path, python_executable=python, runner=runner
    )

    command = observed["command"]
    environment = observed["environment"]
    assert isinstance(command, list)
    assert command[:3] == [
        str(sandbox),
        "-p",
        "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n",
    ]
    assert "fix_mistral_regex=" not in command[5]
    assert isinstance(environment, dict)
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert evidence["tokenIdsSha256"] == (
        "cee60e2f5d072f2de4a20b0fa2db55e799ddc6f2bef3ccb2d120990171016443"
    )
    assert evidence["aliasMatchesSnapshot"] is True
    assert evidence["isolation"]["networkDenied"] is True
    assert evidence["isolation"]["writesDenied"] is True
    assert evidence["providerCalls"] == 0
    assert evidence["productionWritesAllowed"] is False
    assert len(evidence["behaviorFingerprint"]) == 64


def test_umt5_semantic_preflight_rejects_alias_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    reference.parent.mkdir(parents=True)
    reference.write_text(dependency.revision)
    python = tmp_path / "runtime-python"
    python.write_text("python")
    sandbox = tmp_path / "sandbox-exec"
    sandbox.write_text("sandbox")
    monkeypatch.setattr(
        "reel_factory.local_model_manager._UMT5_SANDBOX_EXECUTABLE", sandbox
    )
    changed = [list(vector) for vector in _UMT5_TOKEN_IDS]
    changed[0][0] += 1

    with pytest.raises(RuntimeError, match="local_model_umt5_alias_semantic_drift"):
        _umt5_semantic_preflight(
            root=tmp_path,
            python_executable=python,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                _umt5_probe_output(local_ids=changed),
                "",
            ),
        )


def test_umt5_semantic_preflight_rejects_shared_behavior_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency, _tokenizer, reference = _cache_only_dependency_fixture(tmp_path)
    reference.parent.mkdir(parents=True)
    reference.write_text(dependency.revision)
    python = tmp_path / "runtime-python"
    python.write_text("python")
    sandbox = tmp_path / "sandbox-exec"
    sandbox.write_text("sandbox")
    monkeypatch.setattr(
        "reel_factory.local_model_manager._UMT5_SANDBOX_EXECUTABLE", sandbox
    )
    changed = [list(vector) for vector in _UMT5_TOKEN_IDS]
    changed[0][0] += 1

    with pytest.raises(RuntimeError, match="local_model_umt5_semantic_drift"):
        _umt5_semantic_preflight(
            root=tmp_path,
            python_executable=python,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                _umt5_probe_output(alias_ids=changed, local_ids=changed),
                "",
            ),
        )


def test_wan_runtime_binding_includes_umt5_behavior_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    python.write_text("python")
    behavior = {
        "schema": "reel_factory.umt5_tokenizer_behavior.v1",
        "behaviorFingerprint": "f" * 64,
    }
    monkeypatch.setattr(
        "reel_factory.local_model_manager.runtime_status",
        lambda **_kwargs: {
            "ready": True,
            "issues": [],
            "receipt": {"schema": "fixture"},
            "resolvedEnvironment": ["mlx==fixture"],
            "python": str(python),
            "runtimeId": "mlx_video",
            "repository": MLX_VIDEO_REPOSITORY,
            "observedRevision": MLX_VIDEO_REVISION,
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "python": "3.12.0",
                    "executable": str(python),
                    "mlx": "fixture",
                }
            ),
            "",
        ),
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager._tool_evidence",
        lambda executable: {
            "executable": f"/fixture/{executable}",
            "sha256": "a" * 64,
            "size": 1,
            "version": f"{executable} fixture",
        },
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager._umt5_semantic_preflight",
        lambda **_kwargs: behavior,
    )

    binding = _verified_runtime_binding("wan_2", models_root=tmp_path)

    assert binding["umt5TokenizerBehavior"] == behavior
    assert binding["umt5TokenizerBehaviorFingerprint"] == "f" * 64


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


def test_deep_model_status_hashes_cache_only_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "reel_factory.local_model_manager._verified_runtime_binding",
        lambda _family, **_kwargs: {
            "runtimeId": "fixture-runtime",
            "repository": "creator-os/test-runtime",
            "revision": "fixture-revision",
            "python": "3.12.0",
            "mlxVersion": "fixture",
            "ffmpegSha256": "a" * 64,
            "ffprobeSha256": "b" * 64,
            "umt5TokenizerBehavior": {
                "schema": "reel_factory.umt5_tokenizer_behavior.v1",
                "behaviorFingerprint": "f" * 64,
            },
            "umt5TokenizerBehaviorFingerprint": "f" * 64,
        },
    )
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
    assert (
        first_verified["deepVerificationReceipt"]["runtimeBinding"][
            "umt5TokenizerBehaviorFingerprint"
        ]
        == "f" * 64
    )
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
        if command[:2] == ["git", "-C"] and command[3:] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(
                command, 0, LONGCAT_MLX_REVISION + "\n", ""
            )
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
    assert [
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime / ".venv/bin/python"),
        "--no-deps",
        str(runtime),
    ] in commands


def test_longcat_runtime_install_repairs_historical_partial_path_receipt(
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
                "requirements": ["historical"],
                "resolvedEnvironment": [
                    "longcat-video-avatar-mlx @ "
                    + runtime.with_name("longcat-avatar-mlx.partial").as_uri()
                ],
                "capabilityStatus": "experimental",
            }
        )
    )
    statuses = iter(
        [
            {"ready": False, "issues": ["longcat_mlx_runtime_receipt_mismatch"]},
            {"ready": True, "issues": []},
        ]
    )
    monkeypatch.setattr(
        "reel_factory.local_model_manager._longcat_runtime_status",
        lambda **_kwargs: next(statuses),
    )
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(
                command, 0, LONGCAT_MLX_REVISION + "\n", ""
            )
        if command[:3] == ["uv", "pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                f"longcat-video-avatar-mlx @ {runtime.as_uri()}\nmlx==0.32.0\n",
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    status = install_runtime(
        runtime_root=runtime, family="longcat_avatar", runner=runner
    )

    assert status["ready"] is True
    receipt = json.loads((runtime / ".creator-os-runtime.json").read_text())
    assert receipt["requirementsFingerprint"]
    assert receipt["resolvedEnvironment"] == [
        f"longcat-video-avatar-mlx @ creator-os-pinned-source:{LONGCAT_MLX_REVISION}",
        "mlx==0.32.0",
    ]
    assert all(".partial" not in value for value in receipt["resolvedEnvironment"])
    assert [
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-deps",
        str(runtime),
    ] in commands


def test_runtime_worktree_allows_only_valid_installer_owned_paths(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    subprocess.run(["git", "init", "-q", str(runtime)], check=True)
    subprocess.run(
        ["git", "-C", str(runtime), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(runtime), "config", "user.name", "Test"], check=True
    )
    source = runtime / "runtime.py"
    source.write_text("PINNED = True\n")
    subprocess.run(["git", "-C", str(runtime), "add", "runtime.py"], check=True)
    subprocess.run(
        ["git", "-C", str(runtime), "commit", "-q", "-m", "fixture"], check=True
    )

    (runtime / ".creator-os-runtime.json").write_text("{}\n")
    build = runtime / "build/lib"
    build.mkdir(parents=True)
    (build / "runtime.py").write_text("PINNED = True\n")
    assert _git_worktree_issue(runtime) is None

    unexpected = runtime / "unexpected.py"
    unexpected.write_text("drift\n")
    assert _git_worktree_issue(runtime) == "dirty"
    unexpected.unlink()

    source.write_text("PINNED = False\n")
    assert _git_worktree_issue(runtime) == "dirty"


def test_runtime_worktree_rejects_symlinked_installer_artifact(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    subprocess.run(["git", "init", "-q", str(runtime)], check=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (runtime / "build").symlink_to(outside, target_is_directory=True)

    assert _git_worktree_issue(runtime) == "dirty"


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
