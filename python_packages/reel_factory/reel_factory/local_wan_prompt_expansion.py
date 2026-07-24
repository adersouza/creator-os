"""Pinned, provider-free Qwen-VL prompt expansion for local Wan I2V.

Wan's official I2V guidance recommends image-aware prompt extension. This
module implements that one narrow preprocessing step on Apple Silicon. It is
not a generic prompt service and it never downloads during generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.evidence_attestation import (
    load_evidence_secret,
    sign_evidence_attestation,
    verify_evidence_attestation,
)
from creator_os_core.fileops import atomic_write_text, file_lock

Runner = Callable[..., subprocess.CompletedProcess[str]]

PROMPT_EXPANDER_MODEL_ID = "local_qwen25_vl_7b_mlx_q4"
PROMPT_EXPANDER_MODEL_REPOSITORY = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
PROMPT_EXPANDER_MODEL_REVISION = "fdcc572e8b05ba9daeaf71be8c9e4267c826ff9b"
PROMPT_EXPANDER_MODEL_LICENSE = "apache-2.0"
PROMPT_EXPANDER_MODEL_DIRECTORY = "Qwen2.5-VL-7B-Instruct-MLX-Q4"
PROMPT_EXPANDER_MODEL_ESTIMATED_BYTES = 5_653_493_659
PROMPT_EXPANDER_RUNTIME_REPOSITORY = "https://github.com/Blaizzy/mlx-vlm.git"
PROMPT_EXPANDER_RUNTIME_REVISION = "b739dfa4b681951acd4a2d439f343e002e6b3013"
PROMPT_EXPANDER_RUNTIME_VERSION = "0.6.7"
PROMPT_EXPANDER_POLICY_VERSION = "wan_i2v_dynamic_en_v1"
PROMPT_EXPANDER_ATTESTATION_ISSUER = "reel_factory.local_wan_prompt_expansion"

_MODEL_MANIFEST = ".creator-os-prompt-expander-model.json"
_RUNTIME_RECEIPT = ".creator-os-prompt-expander-runtime.json"
_VERIFICATION_CACHE = ".creator-os-prompt-expander-verification.json"
_SAFETY_MARGIN_BYTES = 10 * 1024**3
_MAX_TOKENS = 180
_REQUIRED_MODEL_PATHS = (
    "config.json",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
_MODEL_INCLUDES = (
    "README.md",
    "LICENSE",
    "added_tokens.json",
    "chat_template.json",
    "config.json",
    "merges.txt",
    "model-*.safetensors",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)
_PRIMARY_MOTION_TERMS = (
    "adjusts",
    "adjusting",
    "bends",
    "bending",
    "brushes",
    "brushing",
    "crosses",
    "crossing",
    "dances",
    "dancing",
    "gesturing",
    "gestures",
    "glances",
    "glancing",
    "leans",
    "leaning",
    "lifts",
    "lifting",
    "lowers",
    "lowering",
    "nods",
    "nodding",
    "pivots",
    "pivoting",
    "places",
    "placing",
    "pulling",
    "pulls",
    "pushing",
    "pushes",
    "raises",
    "raising",
    "reaches",
    "reaching",
    "rotates",
    "rotating",
    "sits",
    "sitting",
    "shifts",
    "shifting",
    "slides",
    "sliding",
    "stands",
    "standing",
    "steps",
    "stepping",
    "straightens",
    "straightening",
    "sways",
    "swaying",
    "tilts",
    "tilting",
    "tosses",
    "tossing",
    "turns",
    "turning",
    "uncrosses",
    "uncrossing",
    "walks",
    "walking",
    "waves",
    "waving",
)
_LOW_MOTION_TERMS = ("blink", "blinks", "blinking", "breath", "breathing")


class WanPromptExpansionError(RuntimeError):
    """The prompt expander is unavailable, drifted, or returned unsafe text."""


def _models_root(value: Path | None = None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_MODELS_ROOT")
    selected = selected or Path.home() / ".creator-os/models"
    return Path(selected).expanduser().resolve()


def _model_dir(value: Path | None = None) -> Path:
    return (_models_root(value) / PROMPT_EXPANDER_MODEL_DIRECTORY).resolve()


def _runtime_root(value: Path | None = None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_MLX_VLM_RUNTIME")
    selected = selected or Path.home() / ".creator-os/runtimes/mlx-vlm"
    return Path(selected).expanduser().resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_records(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise WanPromptExpansionError(
                f"prompt_expander_model_symlink_forbidden:{path}"
            )
        if not path.is_file() or path.name == _MODEL_MANIFEST or ".cache" in path.parts:
            continue
        records.append(
            {
                "path": str(path.relative_to(directory)),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if not records:
        raise WanPromptExpansionError("prompt_expander_model_files_missing")
    return records


def _stat_binding(path: Path, *, allowed_root: Path) -> dict[str, Any]:
    allowed = allowed_root.resolve()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(allowed)
    except (OSError, ValueError) as exc:
        raise WanPromptExpansionError(
            f"prompt_expander_verification_path_unsafe:{path}"
        ) from exc
    link_stat = path.lstat()
    target_stat = resolved.stat()
    if not stat.S_ISREG(target_stat.st_mode):
        raise WanPromptExpansionError(
            f"prompt_expander_verification_path_not_regular:{path}"
        )
    return {
        "path": str(path),
        "resolvedPath": str(resolved),
        "isSymlink": path.is_symlink(),
        "link": {
            "mode": link_stat.st_mode,
            "size": link_stat.st_size,
            "mtimeNs": link_stat.st_mtime_ns,
            "ctimeNs": link_stat.st_ctime_ns,
            "inode": link_stat.st_ino,
            "device": link_stat.st_dev,
        },
        "target": {
            "mode": target_stat.st_mode,
            "size": target_stat.st_size,
            "mtimeNs": target_stat.st_mtime_ns,
            "ctimeNs": target_stat.st_ctime_ns,
            "inode": target_stat.st_ino,
            "device": target_stat.st_dev,
        },
    }


def _verification_snapshot(
    *, model: Path, manifest_path: Path, records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": "reel_factory.local_prompt_expander_stat_snapshot.v1",
        "manifest": _stat_binding(manifest_path, allowed_root=model),
        "modelFiles": [
            _stat_binding(model / str(item["path"]), allowed_root=model)
            for item in records
        ],
    }


def _verification_cache_path(models_root: Path | None) -> Path:
    return _models_root(models_root) / ".verification-cache" / _VERIFICATION_CACHE


def _load_verification_cache(
    *,
    models_root: Path | None,
    manifest_sha256: str,
    stat_snapshot_fingerprint: str,
) -> dict[str, Any] | None:
    path = _verification_cache_path(models_root)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        return None
    core = dict(receipt)
    claimed = core.pop("verificationFingerprint", None)
    if (
        payload.get("schema")
        != "reel_factory.local_prompt_expander_verification_cache.v1"
        or payload.get("modelId") != PROMPT_EXPANDER_MODEL_ID
        or payload.get("manifestSha256") != manifest_sha256
        or payload.get("statSnapshotFingerprint") != stat_snapshot_fingerprint
        or receipt.get("manifestSha256") != manifest_sha256
        or receipt.get("statSnapshotFingerprint") != stat_snapshot_fingerprint
        or claimed != _fingerprint(core)
    ):
        return None
    return receipt


def _write_verification_cache(
    *, models_root: Path | None, receipt: Mapping[str, Any]
) -> None:
    path = _verification_cache_path(models_root)
    if path.parent.exists() and path.parent.is_symlink():
        raise WanPromptExpansionError("prompt_expander_verification_cache_unsafe")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "reel_factory.local_prompt_expander_verification_cache.v1",
        "modelId": PROMPT_EXPANDER_MODEL_ID,
        "manifestSha256": receipt["manifestSha256"],
        "statSnapshotFingerprint": receipt["statSnapshotFingerprint"],
        "receipt": dict(receipt),
    }
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _normalized_environment(
    lines: Sequence[str], *, runtime: Path, staging: Path | None = None
) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        if staging is not None:
            value = value.replace(str(staging), str(runtime))
        value = value.replace(
            str(runtime.with_name(runtime.name + ".partial")),
            str(runtime),
        )
        normalized.append(value)
    return sorted(normalized)


def _load_object(path: Path, *, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise WanPromptExpansionError(code)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WanPromptExpansionError(code) from exc
    if not isinstance(payload, dict):
        raise WanPromptExpansionError(code)
    return payload


def prompt_expander_status(
    *,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    model = _model_dir(models_root)
    runtime = _runtime_root(runtime_root)
    model_issues: list[str] = []
    runtime_issues: list[str] = []
    manifest: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    deep_receipt: dict[str, Any] | None = None
    deep_cache_hit = False
    stat_snapshot_fingerprint: str | None = None

    try:
        manifest = _load_object(
            model / _MODEL_MANIFEST,
            code="prompt_expander_model_manifest_missing_or_invalid",
        )
    except WanPromptExpansionError as exc:
        model_issues.append(str(exc))
    if manifest is not None:
        if (
            manifest.get("schema")
            != "reel_factory.local_prompt_expander_model_installation.v1"
            or manifest.get("modelId") != PROMPT_EXPANDER_MODEL_ID
            or manifest.get("repository") != PROMPT_EXPANDER_MODEL_REPOSITORY
            or manifest.get("revision") != PROMPT_EXPANDER_MODEL_REVISION
            or manifest.get("licenseId") != PROMPT_EXPANDER_MODEL_LICENSE
        ):
            model_issues.append("prompt_expander_model_manifest_mismatch")
        records = manifest.get("files")
        if not isinstance(records, list) or not records:
            model_issues.append("prompt_expander_model_file_receipts_missing")
        else:
            observed = {
                str(item.get("path")) for item in records if isinstance(item, dict)
            }
            if not set(_REQUIRED_MODEL_PATHS).issubset(observed):
                model_issues.append("prompt_expander_model_required_files_missing")
            for item in records:
                if not isinstance(item, dict):
                    model_issues.append("prompt_expander_model_file_receipt_invalid")
                    break
                relative = Path(str(item.get("path") or ""))
                path = model / relative
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not path.is_file()
                    or path.is_symlink()
                    or path.stat().st_size != item.get("size")
                ):
                    model_issues.append("prompt_expander_model_file_drift")
                    break
            manifest_path = model / _MODEL_MANIFEST
            manifest_sha256 = _sha256_file(manifest_path)
            if deep and not model_issues:
                try:
                    stat_snapshot = _verification_snapshot(
                        model=model,
                        manifest_path=manifest_path,
                        records=records,
                    )
                    stat_snapshot_fingerprint = _fingerprint(stat_snapshot)
                    deep_receipt = _load_verification_cache(
                        models_root=models_root,
                        manifest_sha256=manifest_sha256,
                        stat_snapshot_fingerprint=stat_snapshot_fingerprint,
                    )
                    deep_cache_hit = deep_receipt is not None
                except WanPromptExpansionError as exc:
                    model_issues.append(str(exc))
            if deep and not model_issues and deep_receipt is None:
                for item in records:
                    path = model / str(item["path"])
                    if _sha256_file(path) != item.get("sha256"):
                        model_issues.append("prompt_expander_model_file_hash_mismatch")
                        break
            if (
                deep
                and not model_issues
                and deep_receipt is None
                and stat_snapshot_fingerprint is not None
            ):
                deep_core = {
                    "schema": "reel_factory.local_prompt_expander_deep_verification.v1",
                    "modelId": PROMPT_EXPANDER_MODEL_ID,
                    "repository": PROMPT_EXPANDER_MODEL_REPOSITORY,
                    "revision": PROMPT_EXPANDER_MODEL_REVISION,
                    "manifestSha256": manifest_sha256,
                    "fileBindings": [
                        {
                            "path": str(item["path"]),
                            "size": int(item["size"]),
                            "sha256": str(item["sha256"]),
                        }
                        for item in records
                    ],
                    "statSnapshotFingerprint": stat_snapshot_fingerprint,
                    "verifiedAt": datetime.now(UTC).isoformat(),
                    "providerCalls": 0,
                    "paidGeneration": False,
                }
                deep_receipt = {
                    **deep_core,
                    "verificationFingerprint": _fingerprint(deep_core),
                }
                _write_verification_cache(
                    models_root=models_root,
                    receipt=deep_receipt,
                )

    python = runtime / ".venv/bin/python"
    try:
        receipt = _load_object(
            runtime / _RUNTIME_RECEIPT,
            code="prompt_expander_runtime_receipt_missing_or_invalid",
        )
    except WanPromptExpansionError as exc:
        runtime_issues.append(str(exc))
    observed_revision = None
    if not runtime.is_dir() or runtime.is_symlink():
        runtime_issues.append("prompt_expander_runtime_missing")
    else:
        completed = subprocess.run(
            ["git", "-C", str(runtime), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        observed_revision = (
            completed.stdout.strip() if completed.returncode == 0 else None
        )
        if observed_revision != PROMPT_EXPANDER_RUNTIME_REVISION:
            runtime_issues.append("prompt_expander_runtime_revision_mismatch")
    if receipt is not None and (
        receipt.get("schema")
        != "reel_factory.local_prompt_expander_runtime_installation.v1"
        or receipt.get("repository") != PROMPT_EXPANDER_RUNTIME_REPOSITORY
        or receipt.get("revision") != PROMPT_EXPANDER_RUNTIME_REVISION
        or receipt.get("version") != PROMPT_EXPANDER_RUNTIME_VERSION
        or receipt.get("python") != str(python)
    ):
        runtime_issues.append("prompt_expander_runtime_receipt_mismatch")
    current_environment: list[str] | None = None
    if not python.is_file():
        runtime_issues.append("prompt_expander_runtime_python_missing")
    else:
        probe = subprocess.run(
            [str(python), "-c", "import mlx_vlm; print(mlx_vlm.__version__)"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=_offline_environment(),
        )
        if (
            probe.returncode != 0
            or probe.stdout.strip() != PROMPT_EXPANDER_RUNTIME_VERSION
        ):
            runtime_issues.append("prompt_expander_runtime_import_failed")
        frozen = subprocess.run(
            ["uv", "pip", "freeze", "--python", str(python)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if frozen.returncode != 0:
            runtime_issues.append("prompt_expander_runtime_environment_unreadable")
        else:
            current_environment = _normalized_environment(
                frozen.stdout.splitlines(),
                runtime=runtime,
            )
            if receipt is not None and current_environment != receipt.get(
                "resolvedEnvironment"
            ):
                runtime_issues.append("prompt_expander_runtime_environment_drift")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        runtime_issues.append("prompt_expander_apple_silicon_required")

    worker = Path(__file__).with_name("local_wan_prompt_expansion_worker.py").resolve()
    implementation = {
        "path": str(worker),
        "sha256": _sha256_file(worker) if worker.is_file() else None,
    }
    model_manifest_sha = (
        _sha256_file(model / _MODEL_MANIFEST)
        if (model / _MODEL_MANIFEST).is_file()
        else None
    )
    model_binding = {
        "modelId": PROMPT_EXPANDER_MODEL_ID,
        "repository": PROMPT_EXPANDER_MODEL_REPOSITORY,
        "revision": PROMPT_EXPANDER_MODEL_REVISION,
        "licenseId": PROMPT_EXPANDER_MODEL_LICENSE,
        "directory": str(model),
        "manifestSha256": model_manifest_sha,
        "deepVerified": deep_receipt is not None,
        "deepVerificationReceipt": deep_receipt,
    }
    runtime_binding = {
        "repository": PROMPT_EXPANDER_RUNTIME_REPOSITORY,
        "revision": PROMPT_EXPANDER_RUNTIME_REVISION,
        "version": PROMPT_EXPANDER_RUNTIME_VERSION,
        "directory": str(runtime),
        "python": str(python),
        "resolvedEnvironment": current_environment,
        "receiptSha256": (
            _sha256_file(runtime / _RUNTIME_RECEIPT)
            if (runtime / _RUNTIME_RECEIPT).is_file()
            else None
        ),
    }
    return {
        "schema": "reel_factory.local_prompt_expander_capability.v1",
        "model": model_binding,
        "modelBindingFingerprint": _fingerprint(model_binding),
        "runtime": runtime_binding,
        "runtimeBindingFingerprint": _fingerprint(runtime_binding),
        "implementation": implementation,
        "implementationFingerprint": _fingerprint(implementation),
        "deepVerificationCacheHit": deep_cache_hit,
        "ready": not model_issues and not runtime_issues,
        "issues": [*model_issues, *runtime_issues],
        "generationDownloadsAllowed": False,
        "providerCalls": 0,
    }


def prompt_expander_install_plan(
    *, models_root: Path | None = None, runtime_root: Path | None = None
) -> dict[str, Any]:
    status = prompt_expander_status(
        models_root=models_root, runtime_root=runtime_root, deep=False
    )
    model_missing = (
        bool(status["issues"]) and not Path(status["model"]["directory"]).is_dir()
    )
    runtime_missing = (
        bool(status["issues"]) and not Path(status["runtime"]["directory"]).is_dir()
    )
    download_bytes = PROMPT_EXPANDER_MODEL_ESTIMATED_BYTES if model_missing else 0
    root = _models_root(models_root)
    probe_root = root if root.exists() else root.parent
    available = shutil.disk_usage(probe_root).free
    required = download_bytes + (_SAFETY_MARGIN_BYTES if download_bytes else 0)
    return {
        "schema": "reel_factory.local_prompt_expander_install_plan.v1",
        "modelId": PROMPT_EXPANDER_MODEL_ID,
        "modelRepository": PROMPT_EXPANDER_MODEL_REPOSITORY,
        "modelRevision": PROMPT_EXPANDER_MODEL_REVISION,
        "runtimeRepository": PROMPT_EXPANDER_RUNTIME_REPOSITORY,
        "runtimeRevision": PROMPT_EXPANDER_RUNTIME_REVISION,
        "modelInstallRequired": model_missing,
        "runtimeInstallRequired": runtime_missing,
        "estimatedDownloadBytes": download_bytes,
        "safetyMarginBytes": _SAFETY_MARGIN_BYTES,
        "requiredFreeBytes": required,
        "availableFreeBytes": available,
        "spaceReady": available >= required,
        "currentStatus": status,
    }


def install_prompt_expander(
    *,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    plan = prompt_expander_install_plan(
        models_root=models_root, runtime_root=runtime_root
    )
    if not plan["spaceReady"]:
        raise OSError("prompt_expander_install_insufficient_disk_space")
    lock_root = _models_root(models_root)
    lock_root.mkdir(parents=True, exist_ok=True)
    try:
        with file_lock(
            lock_root / ".creator-os-prompt-expander-installer", blocking=False
        ):
            _install_prompt_runtime(runtime_root=runtime_root, runner=runner)
            _install_prompt_model(models_root=models_root, runner=runner)
    except BlockingIOError as exc:
        raise WanPromptExpansionError("prompt_expander_installer_busy") from exc
    status = prompt_expander_status(
        models_root=models_root, runtime_root=runtime_root, deep=True
    )
    if status["ready"] is not True:
        raise WanPromptExpansionError(
            "prompt_expander_install_verification_failed:" + ",".join(status["issues"])
        )
    return {
        "schema": "reel_factory.local_prompt_expander_install_run.v1",
        "status": status,
        "providerCalls": 0,
        "paidGeneration": False,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def _install_prompt_runtime(*, runtime_root: Path | None, runner: Runner) -> None:
    runtime = _runtime_root(runtime_root)
    if runtime.exists():
        status = prompt_expander_status(runtime_root=runtime, deep=False)
        if status["runtime"]["revision"] == PROMPT_EXPANDER_RUNTIME_REVISION and not [
            issue
            for issue in status["issues"]
            if issue.startswith("prompt_expander_runtime")
        ]:
            return
        raise WanPromptExpansionError(
            "prompt_expander_runtime_destination_requires_recovery"
        )
    partial = runtime.with_name(runtime.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise FileExistsError("prompt_expander_runtime_partial_requires_recovery")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    _run_checked(
        runner,
        [
            "git",
            "clone",
            "--filter=blob:none",
            PROMPT_EXPANDER_RUNTIME_REPOSITORY,
            str(partial),
        ],
    )
    _run_checked(
        runner,
        [
            "git",
            "-C",
            str(partial),
            "checkout",
            "--detach",
            PROMPT_EXPANDER_RUNTIME_REVISION,
        ],
    )
    _run_checked(runner, ["uv", "venv", str(partial / ".venv")])
    python = partial / ".venv/bin/python"
    _run_checked(
        runner,
        ["uv", "pip", "install", "--python", str(python), str(partial)],
    )
    frozen = _run_checked(
        runner, ["uv", "pip", "freeze", "--python", str(python)]
    ).stdout.splitlines()
    payload = {
        "schema": "reel_factory.local_prompt_expander_runtime_installation.v1",
        "repository": PROMPT_EXPANDER_RUNTIME_REPOSITORY,
        "revision": PROMPT_EXPANDER_RUNTIME_REVISION,
        "version": PROMPT_EXPANDER_RUNTIME_VERSION,
        "python": str(runtime / ".venv/bin/python"),
        "resolvedEnvironment": _normalized_environment(
            frozen,
            runtime=runtime,
            staging=partial,
        ),
    }
    atomic_write_text(
        partial / _RUNTIME_RECEIPT,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, runtime)


def _install_prompt_model(*, models_root: Path | None, runner: Runner) -> None:
    model = _model_dir(models_root)
    if model.exists():
        status = prompt_expander_status(models_root=models_root, deep=False)
        if not [
            issue
            for issue in status["issues"]
            if issue.startswith("prompt_expander_model")
        ]:
            return
        raise WanPromptExpansionError(
            "prompt_expander_model_destination_requires_recovery"
        )
    partial = model.with_name(model.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise FileExistsError("prompt_expander_model_partial_requires_recovery")
    partial.mkdir(parents=True, exist_ok=False)
    command = [
        "hf",
        "download",
        PROMPT_EXPANDER_MODEL_REPOSITORY,
        "--revision",
        PROMPT_EXPANDER_MODEL_REVISION,
        "--local-dir",
        str(partial),
    ]
    for pattern in _MODEL_INCLUDES:
        command.extend(["--include", pattern])
    _run_checked(runner, command)
    payload = {
        "schema": "reel_factory.local_prompt_expander_model_installation.v1",
        "modelId": PROMPT_EXPANDER_MODEL_ID,
        "repository": PROMPT_EXPANDER_MODEL_REPOSITORY,
        "revision": PROMPT_EXPANDER_MODEL_REVISION,
        "licenseId": PROMPT_EXPANDER_MODEL_LICENSE,
        "quantization": "4bit",
        "files": _file_records(partial),
    }
    atomic_write_text(
        partial / _MODEL_MANIFEST,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, model)


def _run_checked(
    runner: Runner, command: list[str]
) -> subprocess.CompletedProcess[str]:
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed")[-4000:]
        raise WanPromptExpansionError(
            f"prompt_expander_install_command_failed:{detail}"
        )
    return completed


def _system_instruction() -> str:
    return (
        "You write image-to-video prompts for Wan. Inspect the supplied image and "
        "rewrite the user's motion intent as one continuous 6-8 second vertical "
        "video description. Focus on a clear, physically plausible primary action "
        "sequence and one or two secondary natural motions. Blinking and breathing "
        "may be secondary but never the only movement. Preserve the same person, "
        "face, body proportions, outfit, visible objects, setting, framing, and "
        "lighting. Mention camera behavior only when useful. Do not invent speech, "
        "people, objects, scene changes, cuts, text, logos, or interfaces. Avoid "
        "static image description. Keep identity and the face stable. Write 35-90 "
        "English words. Output only plain prompt prose with no labels or markup."
    )


def _user_instruction(original_prompt: str) -> str:
    return f"Rewrite this motion intent for the supplied image: {original_prompt}"


def _normalize_expanded_prompt(value: Any) -> tuple[str, dict[str, Any]]:
    raw = str(value or "")
    raw_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    known_prefix = re.compile(
        r"^\s*<\|im_start\|>\s+addCriterion\s+",
        flags=re.IGNORECASE,
    )
    cleaned, substitutions = known_prefix.subn("", raw, count=1)
    text = " ".join(cleaned.replace("\\n", " ").split())
    word_count = len(text.split())
    lowered = text.lower()
    if not 35 <= word_count <= 100:
        raise WanPromptExpansionError("prompt_expander_output_length_invalid")
    if (
        "<|" in text
        or "|>" in text
        or "addcriterion" in lowered
        or "assistant:" in lowered
        or "system:" in lowered
        or any(character in text for character in ("{", "}", "[", "]"))
    ):
        raise WanPromptExpansionError("prompt_expander_output_not_plain_prose")
    tokens = {match.group(0) for match in re.finditer(r"\b[a-z]+\b", lowered)}
    primary_terms = tokens.intersection(_PRIMARY_MOTION_TERMS)
    if not primary_terms:
        if tokens.intersection(_LOW_MOTION_TERMS):
            raise WanPromptExpansionError("prompt_expander_blink_only_output_rejected")
        raise WanPromptExpansionError("prompt_expander_primary_motion_missing")
    return text, {
        "schema": "reel_factory.local_prompt_output_normalization.v1",
        "rawOutputSha256": raw_sha256,
        "knownPrefixRemoved": (
            "mlx_qwen_add_criterion_v1" if substitutions == 1 else None
        ),
    }


def _offline_environment(tmpdir: Path | None = None) -> dict[str, str]:
    source = os.environ
    environment = {
        key: str(source[key])
        for key in ("HOME", "LANG", "LC_ALL", "PATH")
        if source.get(key)
    }
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "NO_PROXY": "*",
            "PYTHONNOUSERSITE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    if tmpdir is not None:
        environment["TMPDIR"] = str(tmpdir)
        environment["HF_HOME"] = str(tmpdir / "hf")
        environment["XDG_CACHE_HOME"] = str(tmpdir / "cache")
    return environment


def _sandbox_profile(tmpdir: Path) -> str:
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        "(deny file-write*)\n"
        f'(allow file-write* (subpath "{tmpdir}"))\n'
    )


def _sandbox_executable() -> Path | None:
    candidate = Path("/usr/bin/sandbox-exec")
    return candidate if candidate.is_file() else None


def expand_wan_i2v_prompt(
    *,
    image_path: Path,
    original_prompt: str,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    image = Path(image_path).expanduser().resolve()
    if not image.is_file() or image.is_symlink():
        raise WanPromptExpansionError("prompt_expander_source_image_missing_or_unsafe")
    normalized_original = " ".join(str(original_prompt or "").split())
    if len(normalized_original) < 20:
        raise WanPromptExpansionError("prompt_expander_original_prompt_too_short")
    status = prompt_expander_status(
        models_root=models_root, runtime_root=runtime_root, deep=True
    )
    if status["ready"] is not True:
        raise WanPromptExpansionError(
            "prompt_expander_unavailable:" + ",".join(status["issues"])
        )
    sandbox = _sandbox_executable()
    if sandbox is None:
        raise WanPromptExpansionError("prompt_expander_sandbox_unavailable")
    worker = Path(status["implementation"]["path"])
    temporary_root = Path.home() / ".creator-os/tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="creator-os-wan-prompt-",
        dir=str(temporary_root),
    ) as temporary:
        tmpdir = Path(temporary).resolve()
        profile = _sandbox_profile(tmpdir)
        command = [
            str(sandbox),
            "-p",
            profile,
            "--",
            str(status["runtime"]["python"]),
            str(worker),
            "--model",
            str(status["model"]["directory"]),
            "--image",
            str(image),
            "--system-prompt",
            _system_instruction(),
            "--user-prompt",
            _user_instruction(normalized_original),
            "--max-tokens",
            str(_MAX_TOKENS),
        ]
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15 * 60,
            env=_offline_environment(tmpdir),
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "worker failed")[-4000:]
        raise WanPromptExpansionError(f"prompt_expander_worker_failed:{detail}")
    try:
        worker_result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WanPromptExpansionError("prompt_expander_worker_output_invalid") from exc
    if (
        not isinstance(worker_result, dict)
        or worker_result.get("schema")
        != "reel_factory.local_wan_prompt_expansion_worker.v1"
    ):
        raise WanPromptExpansionError("prompt_expander_worker_output_invalid")
    expanded, output_normalization = _normalize_expanded_prompt(
        worker_result.get("text")
    )
    if expanded == normalized_original:
        raise WanPromptExpansionError("prompt_expander_output_unchanged")
    source = {"path": str(image), "sha256": _sha256_file(image)}
    core = {
        "schema": "reel_factory.wan_i2v_prompt_expansion.v1",
        "policyVersion": PROMPT_EXPANDER_POLICY_VERSION,
        "method": "local_qwen_vl",
        "producedAt": datetime.now(UTC).isoformat(),
        "originalPrompt": normalized_original,
        "expandedPrompt": expanded,
        "sourceImage": source,
        "model": status["model"],
        "modelBindingFingerprint": status["modelBindingFingerprint"],
        "runtime": status["runtime"],
        "runtimeBindingFingerprint": status["runtimeBindingFingerprint"],
        "implementation": status["implementation"],
        "implementationFingerprint": status["implementationFingerprint"],
        "outputNormalization": output_normalization,
        "inference": {
            "temperature": 0.0,
            "maxTokens": _MAX_TOKENS,
            "promptTokens": worker_result.get("promptTokens"),
            "generationTokens": worker_result.get("generationTokens"),
            "peakMemoryGb": worker_result.get("peakMemoryGb"),
        },
        "isolation": {
            "sandboxExecutable": str(sandbox),
            "sandboxExecutableSha256": _sha256_file(sandbox),
            "profileFingerprint": _fingerprint({"profile": profile}),
            "networkDenied": True,
            "writesRestrictedToTemporaryDirectory": True,
            "sensitiveEnvironmentInherited": False,
        },
        "providerCalls": 0,
        "paidGeneration": False,
        "productionWritesAllowed": False,
    }
    attested = {**core, "expansionFingerprint": _fingerprint(core)}
    return {
        **attested,
        "producerAttestation": sign_evidence_attestation(
            attested,
            issuer=PROMPT_EXPANDER_ATTESTATION_ISSUER,
            issued_at=str(core["producedAt"]),
            secret=load_evidence_secret(),
        ),
    }


def validate_wan_prompt_expansion(
    receipt: Mapping[str, Any],
    *,
    image_path: Path,
    expanded_prompt: str,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    payload = dict(receipt)
    expected = {
        "schema",
        "policyVersion",
        "method",
        "producedAt",
        "originalPrompt",
        "expandedPrompt",
        "sourceImage",
        "model",
        "modelBindingFingerprint",
        "runtime",
        "runtimeBindingFingerprint",
        "implementation",
        "implementationFingerprint",
        "outputNormalization",
        "inference",
        "isolation",
        "providerCalls",
        "paidGeneration",
        "productionWritesAllowed",
        "expansionFingerprint",
        "producerAttestation",
    }
    if set(payload) != expected:
        raise WanPromptExpansionError("prompt_expansion_receipt_schema_invalid")
    attestation = payload.pop("producerAttestation")
    claimed = str(payload.pop("expansionFingerprint") or "")
    if _fingerprint(payload) != claimed:
        raise WanPromptExpansionError("prompt_expansion_receipt_fingerprint_mismatch")
    attested = {**payload, "expansionFingerprint": claimed}
    if not isinstance(attestation, Mapping):
        raise WanPromptExpansionError("prompt_expansion_attestation_invalid")
    try:
        verify_evidence_attestation(
            attestation,
            attested,
            secret=load_evidence_secret(),
            expected_issuer=PROMPT_EXPANDER_ATTESTATION_ISSUER,
        )
    except ValueError as exc:
        raise WanPromptExpansionError("prompt_expansion_attestation_invalid") from exc
    if (
        payload.get("schema") != "reel_factory.wan_i2v_prompt_expansion.v1"
        or payload.get("policyVersion") != PROMPT_EXPANDER_POLICY_VERSION
        or payload.get("method") != "local_qwen_vl"
        or payload.get("providerCalls") != 0
        or payload.get("paidGeneration") is not False
        or payload.get("productionWritesAllowed") is not False
        or payload.get("expandedPrompt") != " ".join(expanded_prompt.split())
    ):
        raise WanPromptExpansionError("prompt_expansion_receipt_binding_invalid")
    image = Path(image_path).expanduser().resolve()
    source = payload.get("sourceImage")
    if (
        not image.is_file()
        or image.is_symlink()
        or not isinstance(source, Mapping)
        or source.get("path") != str(image)
        or source.get("sha256") != _sha256_file(image)
    ):
        raise WanPromptExpansionError("prompt_expansion_source_image_mismatch")
    status = prompt_expander_status(
        models_root=models_root, runtime_root=runtime_root, deep=True
    )
    if status["ready"] is not True:
        raise WanPromptExpansionError("prompt_expansion_capability_unavailable")
    for field in (
        "model",
        "modelBindingFingerprint",
        "runtime",
        "runtimeBindingFingerprint",
        "implementation",
        "implementationFingerprint",
    ):
        if payload.get(field) != status.get(field):
            raise WanPromptExpansionError(f"prompt_expansion_{field}_drift")
    return {
        **payload,
        "expansionFingerprint": claimed,
        "producerAttestation": dict(attestation),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install, verify, or run the pinned local Wan prompt expander."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    mode = install.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--deep", action="store_true")
    expand = sub.add_parser("expand")
    expand.add_argument("--image", type=Path, required=True)
    expand.add_argument("--prompt", required=True)
    for command in (install, status, expand):
        command.add_argument("--models-root", type=Path)
        command.add_argument("--runtime-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            payload = prompt_expander_status(
                models_root=args.models_root,
                runtime_root=args.runtime_root,
                deep=args.deep,
            )
        elif args.command == "install":
            payload = (
                prompt_expander_install_plan(
                    models_root=args.models_root, runtime_root=args.runtime_root
                )
                if args.dry_run
                else install_prompt_expander(
                    models_root=args.models_root, runtime_root=args.runtime_root
                )
            )
        else:
            payload = expand_wan_i2v_prompt(
                image_path=args.image,
                original_prompt=args.prompt,
                models_root=args.models_root,
                runtime_root=args.runtime_root,
            )
    except (OSError, ValueError, WanPromptExpansionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
