"""Explicit installer and verifier for pinned local video models.

This command is the only networked part of the local MLX path.  Generation
itself forces Hugging Face and Transformers offline and refuses an incomplete
or mismatched installation receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text
from .local_lora_registry import register_local_lora
from .local_video_models import (
    LONGCAT_MLX_REPOSITORY,
    LONGCAT_MLX_REVISION,
    LTX23_SHARED,
    MLX_VIDEO_REPOSITORY,
    MLX_VIDEO_REVISION,
    MODEL_MANIFEST,
    LocalFamily,
    LocalInstallDependency,
    LocalVideoModelSpec,
    local_install_dependencies,
    local_install_dependency,
    local_model_catalog,
    local_video_model_spec,
    local_video_model_specs,
    runtime_identity,
)

Runner = Callable[..., subprocess.CompletedProcess[str]]
_RECEIPT_SCHEMA = "reel_factory.local_model_installation.v1"
_RUNTIME_SCHEMA = "reel_factory.local_mlx_runtime_installation.v1"
_SAFETY_MARGIN_BYTES = 30 * 1024**3
_LONGCAT_RUNTIME_REQUIREMENTS = (
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
)


def _normalize_longcat_environment(
    values: Sequence[str], *, runtime: Path
) -> list[str]:
    """Return stable, exact environment evidence for the pinned local runtime."""

    normalized: list[str] = []
    direct_source_prefix = "longcat-video-avatar-mlx @ "
    pinned_source = (
        f"{direct_source_prefix}creator-os-pinned-source:{LONGCAT_MLX_REVISION}"
    )
    allowed_sources = {
        runtime.as_uri(),
        runtime.with_name(runtime.name + ".partial").as_uri(),
    }
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        if (
            stripped.lower().startswith(direct_source_prefix)
            and stripped[len(direct_source_prefix) :] in allowed_sources
        ):
            stripped = pinned_source
        normalized.append(stripped)
    return sorted(normalized)


def _normalize_mlx_video_environment(
    values: Sequence[str], *, runtime: Path
) -> list[str]:
    normalized: list[str] = []
    direct_source_prefix = "mlx-video @ "
    pinned_source = (
        f"{direct_source_prefix}creator-os-pinned-source:{MLX_VIDEO_REVISION}"
    )
    allowed_sources = {
        runtime.as_uri(),
        runtime.with_name(runtime.name + ".partial").as_uri(),
    }
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        if (
            stripped.lower().startswith(direct_source_prefix)
            and stripped[len(direct_source_prefix) :] in allowed_sources
        ):
            stripped = pinned_source
        normalized.append(stripped)
    return sorted(normalized)


def install_plan(
    model_ids: Sequence[str], *, models_root: Path | None = None
) -> dict[str, Any]:
    specs = _selected_specs(model_ids)
    dependencies = _unique_dependencies(specs)
    root = _models_root(models_root)
    model_entries = []
    missing_model_bytes = 0
    for spec in specs:
        status = model_status(spec.model_id, models_root=root, deep=False)
        material_issues = [
            issue
            for issue in status["issues"]
            if not str(issue).startswith("local_model_dependency_missing:")
            and not str(issue).startswith("local_model_shared_component_missing:")
        ]
        installed = not material_issues
        if not installed:
            missing_model_bytes += spec.estimated_bytes
        model_entries.append(
            {
                **spec.to_dict(),
                "installed": installed,
                "ready": status["ready"],
                "issues": status["issues"],
            }
        )
    dependency_entries = []
    missing_dependency_bytes = 0
    for dependency in dependencies:
        installed = _dependency_ready(dependency, root)
        if not installed:
            missing_dependency_bytes += dependency.estimated_bytes
        dependency_entries.append(
            {**_dependency_payload(dependency, root), "installed": installed}
        )
    selected_artifact_bytes = sum(spec.estimated_bytes for spec in specs) + sum(
        value.estimated_bytes for value in dependencies
    )
    download_bytes = missing_model_bytes + missing_dependency_bytes
    free = shutil.disk_usage(root.parent if not root.exists() else root).free
    required = download_bytes + (_SAFETY_MARGIN_BYTES if download_bytes else 0)
    return {
        "schema": "reel_factory.local_model_install_plan.v1",
        "models": model_entries,
        "dependencies": dependency_entries,
        "selectedArtifactBytes": selected_artifact_bytes,
        "installedArtifactEstimateBytes": selected_artifact_bytes - download_bytes,
        "estimatedDownloadBytes": download_bytes,
        "safetyMarginBytes": _SAFETY_MARGIN_BYTES,
        "requiredFreeBytes": required,
        "availableFreeBytes": free,
        "spaceReady": free >= required,
        "generationDownloadsAllowed": False,
    }


def install_models(
    model_ids: Sequence[str],
    *,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
    longcat_runtime_root: Path | None = None,
    accepted_licenses: Sequence[str] = (),
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    specs = _selected_specs(model_ids)
    plan = install_plan([spec.model_id for spec in specs], models_root=models_root)
    required_licenses = {
        spec.license_id
        for spec in specs
        if spec.license_id not in {"apache-2.0", "mit"}
    }
    required_licenses.update(
        dependency.license_id
        for dependency in _unique_dependencies(specs)
        if dependency.license_id not in {"apache-2.0", "mit"}
    )
    missing_licenses = sorted(required_licenses.difference(accepted_licenses))
    if missing_licenses:
        raise PermissionError(
            "local_model_license_acknowledgement_required: "
            + ", ".join(missing_licenses)
        )
    if not plan["spaceReady"]:
        raise OSError("local_model_install_insufficient_disk_space")
    runtime_families = {spec.family for spec in specs}
    runtimes: dict[str, Any] = {}
    if runtime_families.intersection({"wan_2", "ltx_2"}):
        runtimes["mlx_video"] = install_runtime(
            runtime_root=runtime_root, runner=runner
        )
    if "longcat_avatar" in runtime_families:
        runtimes["longcat_avatar"] = install_runtime(
            runtime_root=longcat_runtime_root,
            family="longcat_avatar",
            runner=runner,
        )
    root = _models_root(models_root)
    root.mkdir(parents=True, exist_ok=True)
    installed_dependencies = [
        _install_dependency(value, root=root, runner=runner)
        for value in _unique_dependencies(specs)
    ]
    installed_models = [
        _install_model(spec, root=root, runner=runner) for spec in specs
    ]
    return {
        "schema": "reel_factory.local_model_install_run.v1",
        "runtime": runtimes.get("mlx_video") or runtimes.get("longcat_avatar"),
        "runtimes": runtimes,
        "models": installed_models,
        "dependencies": installed_dependencies,
        "providerCalls": 0,
        "paidGeneration": False,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def install_runtime(
    *,
    runtime_root: Path | None = None,
    family: LocalFamily = "wan_2",
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    if family == "longcat_avatar":
        return _install_longcat_runtime(runtime_root=runtime_root, runner=runner)
    runtime = _runtime_root(runtime_root)
    receipt = runtime / ".creator-os-runtime.json"
    if runtime.exists():
        status = runtime_status(runtime_root=runtime)
        if status["ready"]:
            return status
        repairable = {
            "mlx_video_runtime_receipt_environment_missing",
            "mlx_video_runtime_environment_drift",
        }
        if set(status["issues"]).issubset(repairable):
            return _repair_mlx_runtime_environment(runtime, runner=runner)
        raise RuntimeError(
            "local_mlx_runtime_exists_but_is_not_pinned: " + ", ".join(status["issues"])
        )
    partial = runtime.with_name(runtime.name + ".partial")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if partial.exists():
        observed_revision = _git_revision(partial, runner=runner)
        if observed_revision != MLX_VIDEO_REVISION:
            raise FileExistsError(
                "local_mlx_runtime_partial_revision_mismatch: "
                f"expected {MLX_VIDEO_REVISION}, got {observed_revision or 'unreadable'}"
            )
    else:
        _run_checked(
            runner,
            [
                "git",
                "clone",
                "--filter=blob:none",
                MLX_VIDEO_REPOSITORY,
                str(partial),
            ],
        )
        _run_checked(
            runner,
            ["git", "-C", str(partial), "checkout", "--detach", MLX_VIDEO_REVISION],
        )
    _run_checked(
        runner,
        [
            "uv",
            "sync",
            "--frozen",
            "--no-dev",
            "--no-install-project",
            "--directory",
            str(partial),
        ],
    )
    _run_checked(
        runner,
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(partial / ".venv/bin/python"),
            "--no-deps",
            str(partial),
        ],
    )
    frozen = _run_checked(
        runner,
        ["uv", "pip", "freeze", "--python", str(partial / ".venv/bin/python")],
    ).stdout.splitlines()
    payload = _mlx_runtime_receipt(runtime, frozen)
    atomic_write_text(
        partial / receipt.name,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # A failed bootstrap intentionally leaves the named partial directory as
    # recoverable evidence. Only a complete pinned runtime is promoted here.
    os.replace(partial, runtime)
    return runtime_status(runtime_root=runtime)


def runtime_status(
    *, runtime_root: Path | None = None, family: LocalFamily = "wan_2"
) -> dict[str, Any]:
    if family == "longcat_avatar":
        return _longcat_runtime_status(runtime_root=runtime_root)
    runtime = _runtime_root(runtime_root)
    python = runtime / ".venv/bin/python"
    issues: list[str] = []
    revision = None
    payload: dict[str, Any] | None = None
    current_environment: list[str] | None = None
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        issues.append("apple_silicon_required_for_mlx_backend")
    if not runtime.is_dir():
        issues.append("mlx_video_runtime_missing")
    else:
        proc = subprocess.run(
            ["git", "-C", str(runtime), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            revision = proc.stdout.strip()
        else:
            issues.append("mlx_video_runtime_revision_unreadable")
        if revision != MLX_VIDEO_REVISION:
            issues.append("mlx_video_runtime_revision_mismatch")
    try:
        decoded = json.loads((runtime / ".creator-os-runtime.json").read_text())
    except (OSError, json.JSONDecodeError):
        issues.append("mlx_video_runtime_receipt_missing_or_invalid")
    else:
        if isinstance(decoded, dict):
            payload = decoded
        if (
            payload is None
            or payload.get("schema") != _RUNTIME_SCHEMA
            or payload.get("repository") != MLX_VIDEO_REPOSITORY
            or payload.get("revision") != MLX_VIDEO_REVISION
            or payload.get("python") != str(python)
        ):
            issues.append("mlx_video_runtime_receipt_mismatch")
    if not python.is_file():
        issues.append("mlx_video_python_missing")
    else:
        proc = subprocess.run(
            [str(python), "-c", "import mlx, mlx_video"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            issues.append("mlx_video_runtime_import_failed")
        try:
            freeze_proc = subprocess.run(
                ["uv", "pip", "freeze", "--python", str(python)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            issues.append("mlx_video_runtime_environment_unreadable")
        else:
            if freeze_proc.returncode != 0:
                issues.append("mlx_video_runtime_environment_unreadable")
            else:
                current_environment = _normalize_mlx_video_environment(
                    freeze_proc.stdout.splitlines(), runtime=runtime
                )
                recorded = payload.get("resolvedEnvironment") if payload else None
                if not isinstance(recorded, list) or not all(
                    isinstance(value, str) for value in recorded
                ):
                    issues.append("mlx_video_runtime_receipt_environment_missing")
                elif current_environment != _normalize_mlx_video_environment(
                    recorded, runtime=runtime
                ):
                    issues.append("mlx_video_runtime_environment_drift")
    if not shutil.which("ffprobe"):
        issues.append("ffprobe_missing")
    return {
        "schema": "reel_factory.local_mlx_runtime_capability.v1",
        "runtimeDir": str(runtime),
        "python": str(python),
        "repository": MLX_VIDEO_REPOSITORY,
        "expectedRevision": MLX_VIDEO_REVISION,
        "observedRevision": revision,
        "receipt": payload,
        "resolvedEnvironment": current_environment,
        "ready": not issues,
        "issues": issues,
    }


def _mlx_runtime_receipt(runtime: Path, frozen: Sequence[str]) -> dict[str, Any]:
    return {
        "schema": _RUNTIME_SCHEMA,
        "repository": MLX_VIDEO_REPOSITORY,
        "revision": MLX_VIDEO_REVISION,
        "python": str(runtime / ".venv/bin/python"),
        "resolvedEnvironment": _normalize_mlx_video_environment(
            frozen, runtime=runtime
        ),
    }


def _repair_mlx_runtime_environment(
    runtime: Path, *, runner: Runner = subprocess.run
) -> dict[str, Any]:
    python = runtime / ".venv/bin/python"
    _run_checked(
        runner,
        [
            "uv",
            "sync",
            "--frozen",
            "--no-dev",
            "--no-install-project",
            "--directory",
            str(runtime),
        ],
    )
    _run_checked(
        runner,
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(runtime)],
    )
    frozen = _run_checked(
        runner, ["uv", "pip", "freeze", "--python", str(python)]
    ).stdout.splitlines()
    atomic_write_text(
        runtime / ".creator-os-runtime.json",
        json.dumps(_mlx_runtime_receipt(runtime, frozen), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    status = runtime_status(runtime_root=runtime)
    if not status["ready"]:
        raise RuntimeError(
            "local_mlx_runtime_repair_verification_failed: "
            + ", ".join(status["issues"])
        )
    return status


def _install_longcat_runtime(
    *, runtime_root: Path | None = None, runner: Runner = subprocess.run
) -> dict[str, Any]:
    runtime = _longcat_runtime_root(runtime_root)
    receipt = runtime / ".creator-os-runtime.json"
    if runtime.exists():
        status = _longcat_runtime_status(runtime_root=runtime)
        if status["ready"]:
            return status
        raise RuntimeError(
            "local_longcat_runtime_exists_but_is_not_pinned: "
            + ", ".join(status["issues"])
        )
    partial = runtime.with_name(runtime.name + ".partial")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if partial.exists():
        observed_revision = _git_revision(partial, runner=runner)
        if observed_revision != LONGCAT_MLX_REVISION:
            raise FileExistsError(
                "local_longcat_runtime_partial_revision_mismatch: "
                f"expected {LONGCAT_MLX_REVISION}, got "
                f"{observed_revision or 'unreadable'}"
            )
    else:
        _run_checked(
            runner,
            [
                "git",
                "clone",
                "--filter=blob:none",
                LONGCAT_MLX_REPOSITORY,
                str(partial),
            ],
        )
        _run_checked(
            runner,
            ["git", "-C", str(partial), "checkout", "--detach", LONGCAT_MLX_REVISION],
        )
    python = partial / ".venv/bin/python"
    if not python.is_file():
        _run_checked(runner, ["uv", "venv", "--python", "3.12", str(partial / ".venv")])
    _run_checked(
        runner,
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(partial)],
    )
    _run_checked(
        runner,
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            *_LONGCAT_RUNTIME_REQUIREMENTS,
        ],
    )
    frozen = _run_checked(
        runner,
        ["uv", "pip", "freeze", "--python", str(python)],
    ).stdout.splitlines()
    payload = {
        "schema": _RUNTIME_SCHEMA,
        "runtimeId": "longcat_avatar",
        "repository": LONGCAT_MLX_REPOSITORY,
        "revision": LONGCAT_MLX_REVISION,
        "python": str(runtime / ".venv/bin/python"),
        "requirements": list(_LONGCAT_RUNTIME_REQUIREMENTS),
        "resolvedEnvironment": _normalize_longcat_environment(frozen, runtime=runtime),
        "capabilityStatus": "experimental",
    }
    atomic_write_text(
        partial / receipt.name,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, runtime)
    return _longcat_runtime_status(runtime_root=runtime)


def _longcat_runtime_status(*, runtime_root: Path | None = None) -> dict[str, Any]:
    runtime = _longcat_runtime_root(runtime_root)
    python = runtime / ".venv/bin/python"
    receipt = runtime / ".creator-os-runtime.json"
    issues: list[str] = []
    revision = None
    payload: dict[str, Any] | None = None
    current_environment: list[str] | None = None
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        issues.append("apple_silicon_required_for_mlx_backend")
    if not runtime.is_dir():
        issues.append("longcat_mlx_runtime_missing")
    else:
        proc = subprocess.run(
            ["git", "-C", str(runtime), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0:
            revision = proc.stdout.strip()
        else:
            issues.append("longcat_mlx_runtime_revision_unreadable")
        if revision != LONGCAT_MLX_REVISION:
            issues.append("longcat_mlx_runtime_revision_mismatch")
    try:
        decoded = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issues.append("longcat_mlx_runtime_receipt_missing_or_invalid")
    else:
        if isinstance(decoded, dict):
            payload = decoded
        if (
            payload is None
            or payload.get("schema") != _RUNTIME_SCHEMA
            or payload.get("runtimeId") != "longcat_avatar"
            or payload.get("repository") != LONGCAT_MLX_REPOSITORY
            or payload.get("revision") != LONGCAT_MLX_REVISION
            or payload.get("python") != str(python)
            or payload.get("requirements") != list(_LONGCAT_RUNTIME_REQUIREMENTS)
        ):
            issues.append("longcat_mlx_runtime_receipt_mismatch")
    if not python.is_file():
        issues.append("longcat_mlx_python_missing")
    else:
        proc = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import imageio, librosa, mlx, mlx_arsenal, safetensors, "
                    "transformers, longcat_video_avatar"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if proc.returncode != 0:
            issues.append("longcat_mlx_runtime_import_failed")
        try:
            freeze_proc = subprocess.run(
                ["uv", "pip", "freeze", "--python", str(python)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            issues.append("longcat_mlx_runtime_environment_unreadable")
        else:
            if freeze_proc.returncode != 0:
                issues.append("longcat_mlx_runtime_environment_unreadable")
            else:
                current_environment = _normalize_longcat_environment(
                    freeze_proc.stdout.splitlines(), runtime=runtime
                )
                recorded = payload.get("resolvedEnvironment") if payload else None
                if not isinstance(recorded, list) or not all(
                    isinstance(value, str) for value in recorded
                ):
                    issues.append("longcat_mlx_runtime_receipt_environment_missing")
                elif current_environment != _normalize_longcat_environment(
                    recorded, runtime=runtime
                ):
                    issues.append("longcat_mlx_runtime_environment_drift")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        issues.append("ffmpeg_or_ffprobe_missing")
    return {
        "schema": "reel_factory.local_mlx_runtime_capability.v1",
        "runtimeId": "longcat_avatar",
        "runtimeDir": str(runtime),
        "python": str(python),
        "repository": LONGCAT_MLX_REPOSITORY,
        "expectedRevision": LONGCAT_MLX_REVISION,
        "observedRevision": revision,
        "receipt": payload,
        "resolvedEnvironment": current_environment,
        "capabilityStatus": "experimental",
        "ready": not issues,
        "issues": issues,
    }


def model_status(
    model_id: str,
    *,
    models_root: Path | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    spec = local_video_model_spec(model_id)
    root = _models_root(models_root)
    directory = spec.directory(root)
    manifest_path = directory / MODEL_MANIFEST
    issues: list[str] = []
    manifest: dict[str, Any] | None = None
    if not manifest_path.is_file():
        issues.append("local_model_manifest_missing")
    else:
        try:
            decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            issues.append("local_model_manifest_invalid")
        else:
            if isinstance(decoded, dict):
                manifest = decoded
            else:
                issues.append("local_model_manifest_invalid")
    if manifest is not None:
        _runtime_id, _runtime_repository, runtime_revision = runtime_identity(
            spec.family
        )
        expected = {
            "schema": _RECEIPT_SCHEMA,
            "modelId": spec.model_id,
            "repository": spec.repository,
            "revision": spec.revision,
            "runtimeRevision": runtime_revision,
        }
        for key, value in expected.items():
            if manifest.get(key) != value:
                issues.append(f"local_model_manifest_mismatch:{key}")
        records = manifest.get("files")
        if not isinstance(records, list):
            issues.append("local_model_file_manifest_missing")
        else:
            for record in records:
                if not isinstance(record, dict):
                    issues.append("local_model_file_manifest_invalid")
                    continue
                relative = str(record.get("path") or "")
                path = directory / relative
                if not path.is_file():
                    issues.append(f"local_model_file_missing:{relative}")
                    continue
                if path.stat().st_size != int(record.get("size") or -1):
                    issues.append(f"local_model_file_size_mismatch:{relative}")
                    continue
                if deep and _sha256_file(path) != record.get("sha256"):
                    issues.append(f"local_model_file_hash_mismatch:{relative}")
    for relative in spec.required_paths:
        if not (directory / relative).is_file():
            issues.append(f"local_model_required_file_missing:{relative}")
    for dependency_id in spec.dependency_ids:
        dependency = local_install_dependency(dependency_id)
        if not _dependency_ready(dependency, root, deep=deep):
            issues.append(f"local_model_dependency_missing:{dependency_id}")
    if spec.family == "ltx_2":
        for relative in _ltx_shared_links():
            if not (directory / relative).exists():
                issues.append(f"local_model_shared_component_missing:{relative}")
    return {
        "schema": "reel_factory.local_model_capability.v1",
        "modelId": spec.model_id,
        "modelDir": str(directory),
        "runtimeModelDir": str(runtime_model_dir(spec, directory)),
        "manifestPath": str(manifest_path),
        "manifestSha256": (
            _sha256_file(manifest_path) if manifest_path.is_file() else None
        ),
        "manifest": manifest,
        "deepVerified": deep,
        "ready": not issues,
        "issues": issues,
        "providerCalls": 0,
        "paidGeneration": False,
    }


def all_model_status(
    *,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
    longcat_runtime_root: Path | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    specs = local_video_model_specs()
    file_statuses = [
        model_status(spec.model_id, models_root=models_root, deep=deep)
        for spec in specs
    ]
    runtimes = {
        "mlx_video": runtime_status(runtime_root=runtime_root),
        "longcat_avatar": runtime_status(
            runtime_root=longcat_runtime_root, family="longcat_avatar"
        ),
    }
    models = []
    for spec, status in zip(specs, file_statuses, strict=True):
        runtime_key = (
            "longcat_avatar" if spec.family == "longcat_avatar" else "mlx_video"
        )
        runtime_ready = bool(runtimes[runtime_key]["ready"])
        files_ready = bool(status["ready"])
        models.append(
            {
                **status,
                "family": spec.family,
                "filesReady": files_ready,
                "runtimeReady": runtime_ready,
                "ready": files_ready and runtime_ready,
            }
        )
    return {
        "schema": "reel_factory.local_model_status.v1",
        "runtime": runtimes["mlx_video"],
        "runtimes": runtimes,
        "models": models,
        "installedModelIds": [
            value["modelId"] for value in models if value["filesReady"]
        ],
        "readyModelIds": [value["modelId"] for value in models if value["ready"]],
        "generationDownloadsAllowed": False,
    }


def runtime_model_dir(spec: LocalVideoModelSpec, directory: Path) -> Path:
    if spec.model_id == "local_wan22_i2v_a14b_q4_mlx":
        return directory / "q4"
    return directory


def hf_home(models_root: Path | None = None) -> Path:
    return _models_root(models_root) / ".hf-home"


def _install_dependency(
    dependency: LocalInstallDependency, *, root: Path, runner: Runner
) -> dict[str, Any]:
    if _dependency_ready(dependency, root):
        return {**_dependency_payload(dependency, root), "status": "already_installed"}
    if dependency.cache_only:
        cache = hf_home(root) / "hub"
        cache.mkdir(parents=True, exist_ok=True)
        command = [
            "hf",
            "download",
            dependency.repository,
            "--revision",
            dependency.revision,
            "--cache-dir",
            str(cache),
            "--quiet",
        ]
        for pattern in dependency.includes:
            command.extend(["--include", pattern])
        completed = _run_checked(runner, command)
        resolved_path = completed.stdout.strip().splitlines()[-1]
        receipt = _dependency_receipt_path(dependency, root)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **_dependency_payload(dependency, root),
            "resolvedPath": resolved_path,
            "files": _file_records(Path(resolved_path)),
        }
        atomic_write_text(
            receipt,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {**payload, "status": "installed"}

    directory = dependency.directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    _hf_download(
        dependency.repository,
        dependency.revision,
        dependency.includes,
        directory,
        runner=runner,
    )
    records = _file_records(directory)
    payload = {
        **_dependency_payload(dependency, root),
        "schema": "reel_factory.local_model_dependency.v1",
        "files": records,
    }
    atomic_write_text(
        directory / MODEL_MANIFEST,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**payload, "status": "installed"}


def _install_model(
    spec: LocalVideoModelSpec, *, root: Path, runner: Runner
) -> dict[str, Any]:
    existing = model_status(spec.model_id, models_root=root)
    if existing["ready"]:
        return {**existing, "status": "already_installed"}
    directory = spec.directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    _hf_download(
        spec.repository,
        spec.revision,
        spec.includes,
        directory,
        runner=runner,
    )
    if spec.family == "ltx_2":
        _link_ltx_shared_components(directory, root=root)
    records = _file_records(directory)
    runtime_id, runtime_repository, runtime_revision = runtime_identity(spec.family)
    payload = {
        "schema": _RECEIPT_SCHEMA,
        "modelId": spec.model_id,
        "family": spec.family,
        "repository": spec.repository,
        "revision": spec.revision,
        "sourceRepository": spec.source_repository,
        "sourceRevision": spec.source_revision,
        "runtimeId": runtime_id,
        "runtimeRepository": runtime_repository,
        "runtimeRevision": runtime_revision,
        "quantization": spec.quantization,
        "pipeline": spec.pipeline,
        "licenseId": spec.license_id,
        "aiDisclosureRequired": spec.ai_disclosure_required,
        "commercialRevenueLimitUsd": spec.commercial_revenue_limit_usd,
        "files": records,
        "dependencies": list(spec.dependency_ids),
    }
    atomic_write_text(
        directory / MODEL_MANIFEST,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verified = model_status(spec.model_id, models_root=root, deep=False)
    if not verified["ready"]:
        raise RuntimeError(
            "local_model_install_verification_failed: " + ", ".join(verified["issues"])
        )
    return {**verified, "status": "installed"}


def _hf_download(
    repository: str,
    revision: str,
    includes: Sequence[str],
    directory: Path,
    *,
    runner: Runner,
) -> None:
    command = [
        "hf",
        "download",
        repository,
        "--revision",
        revision,
        "--local-dir",
        str(directory),
    ]
    for pattern in includes:
        command.extend(["--include", pattern])
    _run_checked(runner, command)


def _link_ltx_shared_components(directory: Path, *, root: Path) -> None:
    shared = LTX23_SHARED.directory(root)
    for relative in _ltx_shared_links():
        target = shared / relative
        link = directory / relative
        if not target.exists():
            raise FileNotFoundError(f"ltx_shared_component_missing:{target}")
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if link.exists() or link.is_symlink():
            raise FileExistsError(f"ltx_shared_component_collision:{link}")
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=target.is_dir())


def _ltx_shared_links() -> tuple[str, ...]:
    return (
        "audio_vae",
        "text_projections",
        "vae",
        "vocoder",
        "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
    )


def _dependency_ready(
    dependency: LocalInstallDependency, root: Path, *, deep: bool = False
) -> bool:
    receipt = _dependency_receipt_path(dependency, root)
    if not receipt.is_file():
        return False
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    identity_matches = bool(
        payload.get("repository") == dependency.repository
        and payload.get("revision") == dependency.revision
    )
    if not identity_matches:
        return False
    records = payload.get("files")
    if not isinstance(records, list) or not records:
        return False
    directory = (
        Path(str(payload.get("resolvedPath") or ""))
        if dependency.cache_only
        else dependency.directory(root)
    )
    if not directory.is_dir():
        return False
    return all(
        isinstance(record, dict)
        and (directory / str(record.get("path") or "")).is_file()
        and (directory / str(record.get("path") or "")).stat().st_size
        == int(record.get("size") or -1)
        and (
            not deep
            or _sha256_file(directory / str(record.get("path") or ""))
            == record.get("sha256")
        )
        for record in records
    )


def _dependency_receipt_path(dependency: LocalInstallDependency, root: Path) -> Path:
    if dependency.cache_only:
        return root / ".receipts" / f"{dependency.id}.json"
    return dependency.directory(root) / MODEL_MANIFEST


def _dependency_payload(
    dependency: LocalInstallDependency, root: Path
) -> dict[str, Any]:
    return {
        "id": dependency.id,
        "repository": dependency.repository,
        "revision": dependency.revision,
        "directory": str(dependency.directory(root)),
        "includes": list(dependency.includes),
        "estimatedBytes": dependency.estimated_bytes,
        "licenseId": dependency.license_id,
        "cacheOnly": dependency.cache_only,
    }


def _file_records(directory: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == MODEL_MANIFEST or ".cache" in path.parts:
            continue
        relative = str(path.relative_to(directory))
        records.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if not records:
        raise RuntimeError(f"local_model_download_produced_no_files:{directory}")
    return records


def _selected_specs(model_ids: Sequence[str]) -> tuple[LocalVideoModelSpec, ...]:
    if not model_ids or model_ids == ("all",) or list(model_ids) == ["all"]:
        return local_video_model_specs()
    selected = tuple(local_video_model_spec(value) for value in model_ids)
    if len({value.model_id for value in selected}) != len(selected):
        raise ValueError("duplicate local model selection")
    return selected


def _unique_dependencies(
    specs: Sequence[LocalVideoModelSpec],
) -> tuple[LocalInstallDependency, ...]:
    ids = {dependency_id for spec in specs for dependency_id in spec.dependency_ids}
    return tuple(value for value in local_install_dependencies() if value.id in ids)


def _models_root(value: Path | None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_MODELS_ROOT")
    selected = selected or Path.home() / ".creator-os/models"
    return Path(selected).expanduser().resolve()


def _runtime_root(value: Path | None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_MLX_RUNTIME")
    selected = selected or Path.home() / ".creator-os/runtimes/mlx-video"
    return Path(selected).expanduser().resolve()


def _longcat_runtime_root(value: Path | None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_LONGCAT_RUNTIME")
    selected = selected or Path.home() / ".creator-os/runtimes/longcat-avatar-mlx"
    return Path(selected).expanduser().resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_checked(
    runner: Runner, command: list[str]
) -> subprocess.CompletedProcess[str]:
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed")[-4000:]
        raise RuntimeError(f"local_model_install_command_failed: {detail}")
    return completed


def _git_revision(path: Path, *, runner: Runner) -> str | None:
    completed = runner(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan, install, and verify pinned local Creator OS video models."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    plan = sub.add_parser("plan")
    plan.add_argument("--model", action="append", default=[])
    install = sub.add_parser("install")
    install.add_argument("--model", action="append", default=[])
    install.add_argument("--accept-license", action="append", default=[])
    apply_mode = install.add_mutually_exclusive_group(required=True)
    apply_mode.add_argument("--dry-run", action="store_true")
    apply_mode.add_argument("--apply", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--deep", action="store_true")
    lora = sub.add_parser("register-lora")
    lora.add_argument("--path", type=Path, required=True)
    lora.add_argument("--id", required=True)
    lora.add_argument("--model", action="append", required=True)
    lora.add_argument("--license", required=True)
    lora.add_argument("--source-repository", required=True)
    lora.add_argument("--source-revision", required=True)
    lora_mode = lora.add_mutually_exclusive_group(required=True)
    lora_mode.add_argument("--dry-run", action="store_true")
    lora_mode.add_argument("--apply", action="store_true")
    for value in (plan, install, status):
        value.add_argument("--models-root", type=Path)
    for value in (install, status):
        value.add_argument("--runtime-root", type=Path)
        value.add_argument("--longcat-runtime-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "catalog":
            payload = local_model_catalog()
        elif args.command == "plan":
            payload = install_plan(args.model, models_root=args.models_root)
        elif args.command == "status":
            payload = all_model_status(
                models_root=args.models_root,
                runtime_root=args.runtime_root,
                longcat_runtime_root=args.longcat_runtime_root,
                deep=args.deep,
            )
        elif args.command == "register-lora":
            payload = register_local_lora(
                args.path,
                lora_id=args.id,
                compatible_model_ids=args.model,
                license_id=args.license,
                source_repository=args.source_repository,
                source_revision=args.source_revision,
                apply=args.apply,
            )
        elif args.dry_run:
            payload = install_plan(args.model, models_root=args.models_root)
        else:
            payload = install_models(
                args.model,
                models_root=args.models_root,
                runtime_root=args.runtime_root,
                longcat_runtime_root=args.longcat_runtime_root,
                accepted_licenses=args.accept_license,
            )
    except (OSError, PermissionError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
