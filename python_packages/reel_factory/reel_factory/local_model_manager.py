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
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text, file_lock
from .local_lora_registry import register_local_lora
from .local_video_models import (
    LONGCAT_MLX_REPOSITORY,
    LONGCAT_MLX_REVISION,
    LTX_MLX_REPOSITORY,
    LTX_MLX_REVISION,
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
_LONGCAT_RUNTIME_REQUIREMENTS_FINGERPRINT = hashlib.sha256(
    "\n".join(_LONGCAT_RUNTIME_REQUIREMENTS).encode("utf-8")
).hexdigest()
_UMT5_DEPENDENCY_ID = "wan_umt5_tokenizer"
_UMT5_TOKEN_VECTOR_SHA256 = (
    "cee60e2f5d072f2de4a20b0fa2db55e799ddc6f2bef3ccb2d120990171016443"
)
_UMT5_TOKENIZER_CLASS = "T5Tokenizer"
_UMT5_PRETOKENIZER = (
    'Sequence(pretokenizers=[WhitespaceSplit(), Metaspace(replacement="▁", '
    "prepend_scheme=always, split=True)])"
)
_UMT5_PROBE_PROMPTS = (
    "Subtle natural portrait motion. Stable face and identity.",
    "Hello, world!  Two spaces.",
    "café — 東京 — مرحبا",
    "line one\nline two",
    "emoji 🙂 punctuation?!",
)
_UMT5_SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
_UMT5_SANDBOX_PROFILE = (
    "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n"
)
_UMT5_SEMANTIC_PROBE_SCRIPT = """\
import hashlib
import json
import os
import socket
import sys

from transformers import AutoTokenizer

snapshot, alias, prompts_json = sys.argv[1:]
prompts = json.loads(prompts_json)

def isolation_probe():
    try:
        descriptor = os.open(
            os.path.join(snapshot, "config.json"),
            os.O_WRONLY,
        )
    except PermissionError:
        write_open_denied = True
    else:
        os.close(descriptor)
        write_open_denied = False
    local_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        local_socket.bind(("127.0.0.1", 0))
    except PermissionError:
        local_network_bind_denied = True
    else:
        local_network_bind_denied = False
    finally:
        local_socket.close()
    return {
        "writeOpenDenied": write_open_denied,
        "localNetworkBindDenied": local_network_bind_denied,
    }

def record(label, source):
    tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
    token_ids = [
        tokenizer.encode(prompt, add_special_tokens=True) for prompt in prompts
    ]
    encoded = json.dumps(token_ids, separators=(",", ":")).encode("utf-8")
    return {
        "label": label,
        "class": type(tokenizer).__name__,
        "isFast": tokenizer.is_fast,
        "fixMistralRegex": getattr(tokenizer, "fix_mistral_regex", None),
        "preTokenizer": str(tokenizer.backend_tokenizer.pre_tokenizer),
        "tokenIds": token_ids,
        "tokenIdsSha256": hashlib.sha256(encoded).hexdigest(),
    }

print(json.dumps({
    "schema": "reel_factory.umt5_semantic_probe_output.v1",
    "isolation": isolation_probe(),
    "records": [
        record("alias-default", alias),
        record("local-default", snapshot),
    ],
}, ensure_ascii=False, sort_keys=True))
"""


def _runtime_probe_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a minimal environment for pinned-runtime import probes.

    Creator OS is commonly invoked with a source-worktree ``PYTHONPATH``.  Letting
    that path leak into a different pinned runtime can shadow its own packages and
    report a false import failure (or, worse, make an invalid runtime appear
    healthy).  Runtime receipts bind the installed environment, so probes must use
    that environment rather than caller-controlled Python import paths.
    """

    source = os.environ if environment is None else environment
    probe = {
        key: str(source[key])
        for key in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        if source.get(key)
    }
    probe.update(
        {
            "HF_HUB_OFFLINE": "1",
            "PYTHONNOUSERSITE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    return probe


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


def _normalize_ltx_environment(values: Sequence[str], *, runtime: Path) -> list[str]:
    normalized: list[str] = []
    runtime_uris = (
        runtime.as_uri(),
        runtime.with_name(runtime.name + ".partial").as_uri(),
    )
    source_suffixes = {
        "ltx-2-mlx": "",
        "ltx-core-mlx": "/packages/ltx-core-mlx",
        "ltx-pipelines-mlx": "/packages/ltx-pipelines-mlx",
    }
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        editable_source = stripped[3:] if stripped.startswith("-e ") else None
        for package, suffix in source_suffixes.items():
            prefix = f"{package} @ "
            direct_source = (
                stripped[len(prefix) :] if stripped.lower().startswith(prefix) else None
            )
            allowed_sources = {base + suffix for base in runtime_uris}
            if direct_source in allowed_sources or editable_source in allowed_sources:
                stripped = f"{package} @ creator-os-pinned-source:{LTX_MLX_REVISION}"
                break
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
            if not str(issue).startswith("local_model_dependency_")
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
        ready = _dependency_ready(dependency, root)
        repair_required = bool(
            dependency.cache_only
            and not ready
            and _dependency_ready(
                dependency,
                root,
                deep=True,
                require_runtime_reference=False,
            )
        )
        installed = ready or repair_required
        if not installed:
            missing_dependency_bytes += dependency.estimated_bytes
        dependency_entries.append(
            {
                **_dependency_payload(dependency, root),
                "installed": installed,
                "ready": ready,
                "repairRequired": repair_required,
            }
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
    ltx_runtime_root: Path | None = None,
    longcat_runtime_root: Path | None = None,
    accepted_licenses: Sequence[str] = (),
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root = _models_root(models_root)
    try:
        with file_lock(root / ".creator-os-model-installer", blocking=False):
            return _install_models_locked(
                model_ids,
                models_root=root,
                runtime_root=runtime_root,
                ltx_runtime_root=ltx_runtime_root,
                longcat_runtime_root=longcat_runtime_root,
                accepted_licenses=accepted_licenses,
                runner=runner,
            )
    except BlockingIOError as exc:
        raise RuntimeError("local_model_installer_busy") from exc


def _install_models_locked(
    model_ids: Sequence[str],
    *,
    models_root: Path,
    runtime_root: Path | None,
    ltx_runtime_root: Path | None,
    longcat_runtime_root: Path | None,
    accepted_licenses: Sequence[str],
    runner: Runner,
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
    if "wan_2" in runtime_families:
        runtimes["mlx_video"] = install_runtime(
            runtime_root=runtime_root, runner=runner
        )
    if "ltx_2" in runtime_families:
        runtimes["ltx_2_mlx"] = install_runtime(
            runtime_root=ltx_runtime_root, family="ltx_2", runner=runner
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
        "runtime": (
            runtimes.get("mlx_video")
            or runtimes.get("ltx_2_mlx")
            or runtimes.get("longcat_avatar")
        ),
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
    selected_root = {
        "wan_2": _runtime_root,
        "ltx_2": _ltx_runtime_root,
        "longcat_avatar": _longcat_runtime_root,
    }[family](runtime_root)
    try:
        with file_lock(
            selected_root.parent / f".{selected_root.name}-installer", blocking=False
        ):
            return _install_runtime_locked(
                runtime_root=selected_root, family=family, runner=runner
            )
    except BlockingIOError as exc:
        raise RuntimeError("local_runtime_installer_busy") from exc


def _install_runtime_locked(
    *,
    runtime_root: Path,
    family: LocalFamily,
    runner: Runner,
) -> dict[str, Any]:
    if family == "longcat_avatar":
        return _install_longcat_runtime(runtime_root=runtime_root, runner=runner)
    if family == "ltx_2":
        return _install_ltx_runtime(runtime_root=runtime_root, runner=runner)
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
    _require_clean_git_worktree(
        partial, runner=runner, error="local_mlx_runtime_partial_worktree_dirty"
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
    if family == "ltx_2":
        return _ltx_runtime_status(runtime_root=runtime_root)
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
        worktree_issue = _git_worktree_issue(runtime)
        if worktree_issue == "unreadable":
            issues.append("mlx_video_runtime_worktree_unreadable")
        elif worktree_issue == "dirty":
            issues.append("mlx_video_runtime_worktree_dirty")
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
            env=_runtime_probe_environment(),
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


def _install_ltx_runtime(
    *, runtime_root: Path | None = None, runner: Runner = subprocess.run
) -> dict[str, Any]:
    runtime = _ltx_runtime_root(runtime_root)
    if runtime.exists():
        status = _ltx_runtime_status(runtime_root=runtime)
        if status["ready"]:
            return status
        repairable = {
            "ltx_mlx_runtime_receipt_missing_or_invalid",
            "ltx_mlx_python_missing",
            "ltx_mlx_runtime_import_failed",
            "ltx_mlx_runtime_environment_unreadable",
            "ltx_mlx_runtime_receipt_environment_missing",
            "ltx_mlx_runtime_receipt_temporary_path",
            "ltx_mlx_runtime_environment_drift",
        }
        if set(status["issues"]).issubset(repairable):
            return _repair_ltx_runtime_environment(runtime, runner=runner)
        raise RuntimeError(
            "local_ltx_runtime_exists_but_is_not_pinned: " + ", ".join(status["issues"])
        )
    partial = runtime.with_name(runtime.name + ".partial")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    if partial.exists():
        observed_revision = _git_revision(partial, runner=runner)
        if observed_revision != LTX_MLX_REVISION:
            raise FileExistsError(
                "local_ltx_runtime_partial_revision_mismatch: "
                f"expected {LTX_MLX_REVISION}, got "
                f"{observed_revision or 'unreadable'}"
            )
    else:
        _run_checked(
            runner,
            ["git", "clone", "--filter=blob:none", LTX_MLX_REPOSITORY, str(partial)],
        )
        _run_checked(
            runner,
            ["git", "-C", str(partial), "checkout", "--detach", LTX_MLX_REVISION],
        )
    _require_clean_git_worktree(
        partial, runner=runner, error="local_ltx_runtime_partial_worktree_dirty"
    )
    _run_checked(
        runner,
        ["uv", "sync", "--frozen", "--no-dev", "--directory", str(partial)],
    )
    # uv installs workspace packages in editable mode, so its .pth files bind
    # to the absolute checkout path. Promote the verified source first, then
    # sync once more from the final path before recording environment evidence.
    os.replace(partial, runtime)
    return _repair_ltx_runtime_environment(runtime, runner=runner)


def _ltx_runtime_receipt(runtime: Path, frozen: Sequence[str]) -> dict[str, Any]:
    return {
        "schema": _RUNTIME_SCHEMA,
        "runtimeId": "ltx_2_mlx",
        "repository": LTX_MLX_REPOSITORY,
        "revision": LTX_MLX_REVISION,
        "python": str(runtime / ".venv/bin/python"),
        "resolvedEnvironment": _normalize_ltx_environment(frozen, runtime=runtime),
    }


def _repair_ltx_runtime_environment(
    runtime: Path, *, runner: Runner = subprocess.run
) -> dict[str, Any]:
    observed_revision = _git_revision(runtime, runner=runner)
    if observed_revision != LTX_MLX_REVISION:
        raise RuntimeError(
            "local_ltx_runtime_repair_revision_mismatch: "
            f"expected {LTX_MLX_REVISION}, got {observed_revision or 'unreadable'}"
        )
    _run_checked(
        runner,
        ["uv", "sync", "--frozen", "--no-dev", "--directory", str(runtime)],
    )
    python = runtime / ".venv/bin/python"
    frozen = _run_checked(
        runner, ["uv", "pip", "freeze", "--python", str(python)]
    ).stdout.splitlines()
    atomic_write_text(
        runtime / ".creator-os-runtime.json",
        json.dumps(_ltx_runtime_receipt(runtime, frozen), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    status = _ltx_runtime_status(runtime_root=runtime)
    if not status["ready"]:
        raise RuntimeError(
            "local_ltx_runtime_repair_verification_failed: "
            + ", ".join(status["issues"])
        )
    return status


def _ltx_runtime_status(*, runtime_root: Path | None = None) -> dict[str, Any]:
    runtime = _ltx_runtime_root(runtime_root)
    python = runtime / ".venv/bin/python"
    receipt = runtime / ".creator-os-runtime.json"
    issues: list[str] = []
    revision = None
    payload: dict[str, Any] | None = None
    current_environment: list[str] | None = None
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        issues.append("apple_silicon_required_for_mlx_backend")
    if not runtime.is_dir():
        issues.append("ltx_mlx_runtime_missing")
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
            issues.append("ltx_mlx_runtime_revision_unreadable")
        if revision != LTX_MLX_REVISION:
            issues.append("ltx_mlx_runtime_revision_mismatch")
        worktree_issue = _git_worktree_issue(runtime)
        if worktree_issue == "unreadable":
            issues.append("ltx_mlx_runtime_worktree_unreadable")
        elif worktree_issue == "dirty":
            issues.append("ltx_mlx_runtime_worktree_dirty")
    try:
        decoded = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issues.append("ltx_mlx_runtime_receipt_missing_or_invalid")
    else:
        if isinstance(decoded, dict):
            payload = decoded
        if (
            payload is None
            or payload.get("schema") != _RUNTIME_SCHEMA
            or payload.get("runtimeId") != "ltx_2_mlx"
            or payload.get("repository") != LTX_MLX_REPOSITORY
            or payload.get("revision") != LTX_MLX_REVISION
            or payload.get("python") != str(python)
        ):
            issues.append("ltx_mlx_runtime_receipt_mismatch")
    if not python.is_file():
        issues.append("ltx_mlx_python_missing")
    else:
        proc = subprocess.run(
            [str(python), "-c", "import mlx, ltx_core_mlx, ltx_pipelines_mlx"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=_runtime_probe_environment(),
        )
        if proc.returncode != 0:
            issues.append("ltx_mlx_runtime_import_failed")
        try:
            freeze_proc = subprocess.run(
                ["uv", "pip", "freeze", "--python", str(python)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            issues.append("ltx_mlx_runtime_environment_unreadable")
        else:
            if freeze_proc.returncode != 0:
                issues.append("ltx_mlx_runtime_environment_unreadable")
            else:
                current_environment = _normalize_ltx_environment(
                    freeze_proc.stdout.splitlines(), runtime=runtime
                )
                recorded = payload.get("resolvedEnvironment") if payload else None
                if not isinstance(recorded, list) or not all(
                    isinstance(value, str) for value in recorded
                ):
                    issues.append("ltx_mlx_runtime_receipt_environment_missing")
                else:
                    if any(".partial" in value for value in recorded):
                        issues.append("ltx_mlx_runtime_receipt_temporary_path")
                    if current_environment != _normalize_ltx_environment(
                        recorded, runtime=runtime
                    ):
                        issues.append("ltx_mlx_runtime_environment_drift")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        issues.append("ffmpeg_or_ffprobe_missing")
    return {
        "schema": "reel_factory.local_mlx_runtime_capability.v1",
        "runtimeId": "ltx_2_mlx",
        "runtimeDir": str(runtime),
        "python": str(python),
        "repository": LTX_MLX_REPOSITORY,
        "expectedRevision": LTX_MLX_REVISION,
        "observedRevision": revision,
        "receipt": payload,
        "resolvedEnvironment": current_environment,
        "ready": not issues,
        "issues": issues,
    }


def _install_longcat_runtime(
    *, runtime_root: Path | None = None, runner: Runner = subprocess.run
) -> dict[str, Any]:
    runtime = _longcat_runtime_root(runtime_root)
    if runtime.exists():
        status = _longcat_runtime_status(runtime_root=runtime)
        if status["ready"]:
            return status
        repairable = {
            "longcat_mlx_runtime_receipt_missing_or_invalid",
            "longcat_mlx_runtime_receipt_mismatch",
            "longcat_mlx_python_missing",
            "longcat_mlx_runtime_import_failed",
            "longcat_mlx_runtime_environment_unreadable",
            "longcat_mlx_runtime_receipt_environment_missing",
            "longcat_mlx_runtime_environment_drift",
        }
        if set(status["issues"]).issubset(repairable):
            return _repair_longcat_runtime_environment(runtime, runner=runner)
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
    _require_clean_git_worktree(
        partial,
        runner=runner,
        error="local_longcat_runtime_partial_worktree_dirty",
    )
    python = partial / ".venv/bin/python"
    if not python.is_file():
        _run_checked(runner, ["uv", "venv", "--python", "3.12", str(partial / ".venv")])
    # Promote the verified source before installing it. Package metadata and
    # the durable receipt must bind the final runtime path, never the temporary
    # bootstrap directory.
    os.replace(partial, runtime)
    return _repair_longcat_runtime_environment(runtime, runner=runner)


def _repair_longcat_runtime_environment(
    runtime: Path, *, runner: Runner = subprocess.run
) -> dict[str, Any]:
    observed_revision = _git_revision(runtime, runner=runner)
    if observed_revision != LONGCAT_MLX_REVISION:
        raise RuntimeError(
            "local_longcat_runtime_repair_revision_mismatch: "
            f"expected {LONGCAT_MLX_REVISION}, got "
            f"{observed_revision or 'unreadable'}"
        )
    python = runtime / ".venv/bin/python"
    if not python.is_file():
        _run_checked(runner, ["uv", "venv", "--python", "3.12", str(runtime / ".venv")])
    _run_checked(
        runner,
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(runtime)],
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
        "requirementsFingerprint": _LONGCAT_RUNTIME_REQUIREMENTS_FINGERPRINT,
        "resolvedEnvironment": _normalize_longcat_environment(frozen, runtime=runtime),
        "capabilityStatus": "experimental",
    }
    atomic_write_text(
        runtime / ".creator-os-runtime.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    status = _longcat_runtime_status(runtime_root=runtime)
    if not status["ready"]:
        raise RuntimeError(
            "local_longcat_runtime_repair_verification_failed: "
            + ", ".join(status["issues"])
        )
    return status


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
        worktree_issue = _git_worktree_issue(runtime)
        if worktree_issue == "unreadable":
            issues.append("longcat_mlx_runtime_worktree_unreadable")
        elif worktree_issue == "dirty":
            issues.append("longcat_mlx_runtime_worktree_dirty")
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
            or payload.get("requirementsFingerprint")
            != _LONGCAT_RUNTIME_REQUIREMENTS_FINGERPRINT
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
            env=_runtime_probe_environment(),
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


def _tool_evidence(executable: str) -> dict[str, Any]:
    path = shutil.which(executable)
    if path is None:
        raise RuntimeError(f"local_model_runtime_tool_missing:{executable}")
    try:
        completed = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_runtime_probe_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"local_model_runtime_tool_unreadable:{executable}") from exc
    first_line = (completed.stdout or completed.stderr).splitlines()
    if completed.returncode != 0 or not first_line:
        raise RuntimeError(f"local_model_runtime_tool_unreadable:{executable}")
    resolved = Path(path).resolve(strict=True)
    return {
        "executable": str(resolved),
        "sha256": _sha256_file(resolved),
        "size": resolved.stat().st_size,
        "version": first_line[0].strip(),
    }


def _umt5_semantic_preflight(
    *,
    root: Path,
    python_executable: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Verify pinned UMT5 behavior under an offline, write-denied sandbox."""

    dependency = local_install_dependency(_UMT5_DEPENDENCY_ID)
    if dependency.revision != "66cb9e7e85526fe440a945569e42c72fb6cbc0ad":
        raise RuntimeError("local_model_umt5_catalog_revision_drift")
    if not _dependency_ready(dependency, root, deep=True):
        raise RuntimeError("local_model_umt5_dependency_not_deep_verified")

    snapshot = _cache_snapshot_path(dependency, root).resolve()
    reference = _cache_runtime_reference_path(dependency, root).resolve()
    sandbox = _UMT5_SANDBOX_EXECUTABLE.resolve()
    try:
        resolved_python = python_executable.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("local_model_umt5_semantic_preflight_unsafe") from exc
    if (
        not snapshot.is_dir()
        or snapshot.is_symlink()
        or not reference.is_file()
        or reference.is_symlink()
        or not resolved_python.is_file()
        or not sandbox.is_file()
        or sandbox.is_symlink()
    ):
        raise RuntimeError("local_model_umt5_semantic_preflight_unsafe")

    environment = _runtime_probe_environment()
    environment.update(
        {
            "HF_HOME": str(hf_home(root)),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    command = [
        str(sandbox),
        "-p",
        _UMT5_SANDBOX_PROFILE,
        str(python_executable),
        "-c",
        _UMT5_SEMANTIC_PROBE_SCRIPT,
        str(snapshot),
        dependency.repository,
        json.dumps(_UMT5_PROBE_PROMPTS, ensure_ascii=False),
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=environment,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else None
    except (
        OSError,
        subprocess.SubprocessError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError("local_model_umt5_semantic_probe_failed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("local_model_umt5_semantic_probe_failed")
    records = payload.get("records")
    isolation = payload.get("isolation")
    if (
        payload.get("schema") != "reel_factory.umt5_semantic_probe_output.v1"
        or not isinstance(records, list)
        or len(records) != 2
        or not isinstance(isolation, dict)
        or isolation.get("writeOpenDenied") is not True
        or isolation.get("localNetworkBindDenied") is not True
    ):
        raise RuntimeError("local_model_umt5_semantic_isolation_failed")
    by_label = {
        record.get("label"): record for record in records if isinstance(record, dict)
    }
    alias = by_label.get("alias-default")
    local = by_label.get("local-default")
    if not isinstance(alias, dict) or not isinstance(local, dict):
        raise RuntimeError("local_model_umt5_semantic_probe_invalid")

    def validated_token_ids(
        record: Mapping[str, Any],
    ) -> tuple[list[list[int]], str]:
        token_ids = record.get("tokenIds")
        if (
            record.get("class") != _UMT5_TOKENIZER_CLASS
            or record.get("isFast") is not True
            or record.get("fixMistralRegex") is not None
            or record.get("preTokenizer") != _UMT5_PRETOKENIZER
            or not isinstance(token_ids, list)
            or len(token_ids) != len(_UMT5_PROBE_PROMPTS)
            or not all(
                isinstance(vector, list)
                and vector
                and all(
                    isinstance(token, int)
                    and not isinstance(token, bool)
                    and token >= 0
                    for token in vector
                )
                for vector in token_ids
            )
        ):
            raise RuntimeError("local_model_umt5_semantic_drift")
        observed_digest = hashlib.sha256(
            json.dumps(token_ids, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if record.get("tokenIdsSha256") != observed_digest:
            raise RuntimeError("local_model_umt5_semantic_drift")
        return token_ids, observed_digest

    alias_ids, alias_digest = validated_token_ids(alias)
    local_ids, local_digest = validated_token_ids(local)
    if alias_ids != local_ids:
        raise RuntimeError("local_model_umt5_alias_semantic_drift")
    if (
        alias_digest != _UMT5_TOKEN_VECTOR_SHA256
        or local_digest != _UMT5_TOKEN_VECTOR_SHA256
    ):
        raise RuntimeError("local_model_umt5_semantic_drift")

    behavior = {
        "schema": "reel_factory.umt5_tokenizer_behavior.v1",
        "dependencyId": dependency.id,
        "repository": dependency.repository,
        "revision": dependency.revision,
        "tokenizerClass": _UMT5_TOKENIZER_CLASS,
        "isFast": True,
        "fixMistralRegex": None,
        "preTokenizer": _UMT5_PRETOKENIZER,
        "probeCorpusSha256": hashlib.sha256(
            json.dumps(
                _UMT5_PROBE_PROMPTS,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "tokenIdsSha256": _UMT5_TOKEN_VECTOR_SHA256,
        "aliasMatchesSnapshot": True,
    }
    return {
        **behavior,
        "behaviorFingerprint": _fingerprint(behavior),
        "snapshotPath": str(snapshot),
        "dependencyReceiptSha256": _sha256_file(
            _dependency_receipt_path(dependency, root)
        ),
        "runtimeReferencePath": str(reference),
        "runtimeReferenceSha256": _sha256_file(reference),
        "probeScriptSha256": hashlib.sha256(
            _UMT5_SEMANTIC_PROBE_SCRIPT.encode("utf-8")
        ).hexdigest(),
        "isolation": {
            "sandboxExecutable": str(sandbox),
            "sandboxExecutableSha256": _sha256_file(sandbox),
            "profileFingerprint": _fingerprint({"profile": _UMT5_SANDBOX_PROFILE}),
            "networkDenied": isolation["localNetworkBindDenied"],
            "writesDenied": isolation["writeOpenDenied"],
        },
        "providerCalls": 0,
        "productionWritesAllowed": False,
    }


def _verified_runtime_binding(
    family: LocalFamily, *, models_root: Path | None = None
) -> dict[str, Any]:
    status = runtime_status(family=family)
    if status.get("ready") is not True:
        raise RuntimeError(
            "local_model_runtime_not_ready:"
            + ",".join(str(issue) for issue in status.get("issues", []))
        )
    receipt = status.get("receipt")
    environment = status.get("resolvedEnvironment")
    python_path = Path(str(status.get("python") or "")).expanduser()
    try:
        resolved_python = python_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("local_model_runtime_evidence_incomplete") from exc
    if (
        not isinstance(receipt, dict)
        or not isinstance(environment, list)
        or not all(isinstance(item, str) for item in environment)
        or not resolved_python.is_file()
    ):
        raise RuntimeError("local_model_runtime_evidence_incomplete")
    probe_script = (
        "import importlib.metadata,json,platform,sys;"
        "print(json.dumps({'python':platform.python_version(),"
        "'executable':sys.executable,'mlx':importlib.metadata.version('mlx')}))"
    )
    try:
        probe = subprocess.run(
            [str(python_path), "-c", probe_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_runtime_probe_environment(),
        )
        versions = json.loads(probe.stdout) if probe.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RuntimeError("local_model_runtime_version_probe_failed") from exc
    if not isinstance(versions, dict):
        raise RuntimeError("local_model_runtime_version_probe_failed")
    runtime_id, repository, expected_revision = runtime_identity(family)
    if (
        status.get("runtimeId", runtime_id) != runtime_id
        or status.get("repository") != repository
        or status.get("observedRevision") != expected_revision
        or Path(str(versions.get("executable") or "")).resolve() != resolved_python
    ):
        raise RuntimeError("local_model_runtime_identity_drift")
    ffmpeg = _tool_evidence("ffmpeg")
    ffprobe = _tool_evidence("ffprobe")
    binding = {
        "runtimeId": runtime_id,
        "repository": repository,
        "revision": expected_revision,
        "platform": platform.system(),
        "platformRelease": platform.release(),
        "osBuild": platform.version(),
        "machine": platform.machine(),
        "python": str(versions.get("python") or ""),
        "pythonExecutable": str(python_path),
        "pythonExecutableResolved": str(resolved_python),
        "mlxVersion": str(versions.get("mlx") or ""),
        "runtimeReceiptFingerprint": _fingerprint(receipt),
        "resolvedEnvironmentFingerprint": _fingerprint(
            {"resolvedEnvironment": environment}
        ),
        "ffmpegExecutable": ffmpeg["executable"],
        "ffmpegSha256": ffmpeg["sha256"],
        "ffmpegSize": ffmpeg["size"],
        "ffmpegVersion": ffmpeg["version"],
        "ffprobeExecutable": ffprobe["executable"],
        "ffprobeSha256": ffprobe["sha256"],
        "ffprobeSize": ffprobe["size"],
        "ffprobeVersion": ffprobe["version"],
    }
    if family == "wan_2":
        behavior = _umt5_semantic_preflight(
            root=_models_root(models_root),
            python_executable=python_path,
        )
        binding["umt5TokenizerBehavior"] = behavior
        binding["umt5TokenizerBehaviorFingerprint"] = behavior["behaviorFingerprint"]
    return binding


def model_status(
    model_id: str,
    *,
    models_root: Path | None = None,
    deep: bool = True,
) -> dict[str, Any]:
    spec = local_video_model_spec(model_id)
    root = _models_root(models_root)
    directory = spec.directory(root)
    manifest_path = directory / MODEL_MANIFEST
    issues: list[str] = []
    manifest: dict[str, Any] | None = None
    records: list[dict[str, Any]] | None = None
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
        records = _validated_dependency_records(
            manifest.get("files"), required_paths=spec.required_paths
        )
        if records is None:
            issues.append("local_model_file_manifest_missing")
        else:
            for record in records:
                relative = str(record["path"])
                path = directory / relative
                if path.is_symlink() or not path.is_file():
                    issues.append(f"local_model_file_missing:{relative}")
                    continue
                if path.stat().st_size != int(record["size"]):
                    issues.append(f"local_model_file_size_mismatch:{relative}")
    for relative in spec.required_paths:
        if not (directory / relative).is_file():
            issues.append(f"local_model_required_file_missing:{relative}")
    for dependency_id in spec.dependency_ids:
        dependency = local_install_dependency(dependency_id)
        if not _dependency_ready(dependency, root, deep=False):
            if dependency.cache_only and _dependency_ready(
                dependency,
                root,
                deep=False,
                require_runtime_reference=False,
            ):
                reference_issue = _cache_runtime_reference_issue(dependency, root)
                issues.append(
                    f"local_model_dependency_{reference_issue}:{dependency_id}"
                )
            else:
                issues.append(f"local_model_dependency_missing:{dependency_id}")
    manifest_sha256 = _sha256_file(manifest_path) if manifest_path.is_file() else None
    deep_receipt: dict[str, Any] | None = None
    deep_cache_hit = False
    stat_snapshot_fingerprint: str | None = None
    runtime_binding: dict[str, Any] | None = None
    runtime_binding_fingerprint: str | None = None
    if (
        deep
        and not issues
        and manifest is not None
        and manifest_sha256 is not None
        and records is not None
    ):
        try:
            runtime_binding = _verified_runtime_binding(spec.family, models_root=root)
        except RuntimeError as exc:
            issues.append(str(exc))
            runtime_binding = None
        if runtime_binding is None:
            runtime_binding_fingerprint = None
        else:
            runtime_binding_fingerprint = _fingerprint(runtime_binding)
        stat_snapshot = _deep_verification_stat_snapshot(
            directory=directory,
            manifest_path=manifest_path,
            records=records,
            dependency_ids=spec.dependency_ids,
            root=root,
        )
        stat_snapshot_fingerprint = _fingerprint(stat_snapshot)
        if runtime_binding_fingerprint is not None:
            deep_receipt = _load_deep_verification_cache(
                root=root,
                model_id=spec.model_id,
                manifest_sha256=manifest_sha256,
                stat_snapshot_fingerprint=stat_snapshot_fingerprint,
                runtime_binding_fingerprint=runtime_binding_fingerprint,
            )
        deep_cache_hit = deep_receipt is not None
    if deep and not issues and deep_receipt is None and records is not None:
        for record in records:
            relative = str(record["path"])
            if _sha256_file(directory / relative) != record["sha256"]:
                issues.append(f"local_model_file_hash_mismatch:{relative}")
        for dependency_id in spec.dependency_ids:
            dependency = local_install_dependency(dependency_id)
            if not _dependency_ready(dependency, root, deep=True):
                issues.append(f"local_model_dependency_missing:{dependency_id}")
    if (
        deep
        and not issues
        and deep_receipt is None
        and manifest is not None
        and manifest_sha256 is not None
        and records is not None
        and stat_snapshot_fingerprint is not None
        and runtime_binding is not None
        and runtime_binding_fingerprint is not None
    ):
        deep_core = {
            "schema": "reel_factory.local_model_deep_verification.v1",
            "modelId": spec.model_id,
            "repository": spec.repository,
            "revision": spec.revision,
            "manifestSha256": manifest_sha256,
            "fileBindings": [
                {
                    "path": str(record["path"]),
                    "size": int(record["size"]),
                    "sha256": str(record["sha256"]),
                }
                for record in records
            ],
            "dependencyBindings": [
                {
                    "dependencyId": dependency_id,
                    "receiptSha256": _sha256_file(
                        _dependency_receipt_path(
                            local_install_dependency(dependency_id), root
                        )
                    ),
                }
                for dependency_id in spec.dependency_ids
            ],
            "statSnapshotFingerprint": stat_snapshot_fingerprint,
            "runtimeBinding": runtime_binding,
            "runtimeBindingFingerprint": runtime_binding_fingerprint,
            "verifiedAt": datetime.now(UTC).isoformat(),
            "providerCalls": 0,
            "paidGeneration": False,
        }
        deep_receipt = {
            **deep_core,
            "verificationFingerprint": _fingerprint(deep_core),
        }
        _write_deep_verification_cache(
            root=root,
            model_id=spec.model_id,
            receipt=deep_receipt,
        )
    return {
        "schema": "reel_factory.local_model_capability.v1",
        "modelId": spec.model_id,
        "modelDir": str(directory),
        "runtimeModelDir": str(runtime_model_dir(spec, directory)),
        "manifestPath": str(manifest_path),
        "manifestSha256": manifest_sha256,
        "manifest": manifest,
        "deepVerified": deep_receipt is not None,
        "deepVerificationReceipt": deep_receipt,
        "deepVerificationCacheHit": deep_cache_hit,
        "ready": not issues,
        "issues": issues,
        "providerCalls": 0,
        "paidGeneration": False,
    }


def _deep_verification_cache_path(root: Path, model_id: str) -> Path:
    return root / ".verification-cache" / f"{model_id}.json"


def _safe_stat_binding(path: Path, *, allowed_root: Path) -> dict[str, Any]:
    allowed = allowed_root.resolve()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(allowed)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"local_model_verification_path_unsafe:{path}") from exc
    link_stat = path.lstat()
    target_stat = resolved.stat()
    if not stat.S_ISREG(target_stat.st_mode):
        raise RuntimeError(f"local_model_verification_path_not_regular:{path}")
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


def _deep_verification_stat_snapshot(
    *,
    directory: Path,
    manifest_path: Path,
    records: Sequence[Mapping[str, Any]],
    dependency_ids: Sequence[str],
    root: Path,
) -> dict[str, Any]:
    model_bindings = [
        _safe_stat_binding(directory / str(record["path"]), allowed_root=directory)
        for record in records
    ]
    dependency_bindings: list[dict[str, Any]] = []
    for dependency_id in dependency_ids:
        dependency = local_install_dependency(dependency_id)
        receipt_path = _dependency_receipt_path(dependency, root)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"local_model_dependency_receipt_invalid:{dependency_id}"
            ) from exc
        dependency_records = _validated_dependency_records(
            receipt.get("files") if isinstance(receipt, dict) else None,
            required_paths=dependency.required_paths,
        )
        if dependency_records is None:
            raise RuntimeError(
                f"local_model_dependency_receipt_invalid:{dependency_id}"
            )
        dependency_directory = (
            Path(str(receipt.get("resolvedPath") or "")).resolve()
            if dependency.cache_only
            else dependency.directory(root)
        )
        allowed_root = (
            _cache_repository_root(dependency, root)
            if dependency.cache_only
            else dependency_directory
        )
        dependency_bindings.append(
            {
                "dependencyId": dependency_id,
                "receipt": _safe_stat_binding(
                    receipt_path, allowed_root=receipt_path.parent
                ),
                "files": [
                    _safe_stat_binding(
                        dependency_directory / str(record["path"]),
                        allowed_root=allowed_root,
                    )
                    for record in dependency_records
                ],
                "runtimeReference": (
                    _safe_stat_binding(
                        _cache_runtime_reference_path(dependency, root),
                        allowed_root=_cache_repository_root(dependency, root),
                    )
                    if dependency.cache_only
                    else None
                ),
            }
        )
    return {
        "schema": "reel_factory.local_model_stat_snapshot.v1",
        "manifest": _safe_stat_binding(
            manifest_path, allowed_root=manifest_path.parent
        ),
        "modelFiles": model_bindings,
        "dependencies": dependency_bindings,
    }


def _load_deep_verification_cache(
    *,
    root: Path,
    model_id: str,
    manifest_sha256: str,
    stat_snapshot_fingerprint: str,
    runtime_binding_fingerprint: str,
) -> dict[str, Any] | None:
    path = _deep_verification_cache_path(root, model_id)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        return None
    claimed = receipt.get("verificationFingerprint")
    core = dict(receipt)
    core.pop("verificationFingerprint", None)
    if (
        payload.get("schema") != "reel_factory.local_model_verification_cache.v1"
        or payload.get("modelId") != model_id
        or payload.get("manifestSha256") != manifest_sha256
        or payload.get("statSnapshotFingerprint") != stat_snapshot_fingerprint
        or payload.get("runtimeBindingFingerprint") != runtime_binding_fingerprint
        or claimed != _fingerprint(core)
        or receipt.get("statSnapshotFingerprint") != stat_snapshot_fingerprint
        or receipt.get("runtimeBindingFingerprint") != runtime_binding_fingerprint
    ):
        return None
    return receipt


def _write_deep_verification_cache(
    *, root: Path, model_id: str, receipt: Mapping[str, Any]
) -> None:
    path = _deep_verification_cache_path(root, model_id)
    if path.parent.exists() and path.parent.is_symlink():
        raise RuntimeError("local_model_verification_cache_unsafe")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "reel_factory.local_model_verification_cache.v1",
        "modelId": model_id,
        "manifestSha256": receipt["manifestSha256"],
        "statSnapshotFingerprint": receipt["statSnapshotFingerprint"],
        "runtimeBindingFingerprint": receipt["runtimeBindingFingerprint"],
        "receipt": dict(receipt),
    }
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def all_model_status(
    *,
    models_root: Path | None = None,
    runtime_root: Path | None = None,
    ltx_runtime_root: Path | None = None,
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
        "ltx_2_mlx": runtime_status(runtime_root=ltx_runtime_root, family="ltx_2"),
        "longcat_avatar": runtime_status(
            runtime_root=longcat_runtime_root, family="longcat_avatar"
        ),
    }
    models = []
    for spec, status in zip(specs, file_statuses, strict=True):
        runtime_key = {
            "wan_2": "mlx_video",
            "ltx_2": "ltx_2_mlx",
            "longcat_avatar": "longcat_avatar",
        }[spec.family]
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


def legacy_storage_report(*, models_root: Path | None = None) -> dict[str, Any]:
    """Report superseded local-model directories without deleting anything."""

    root = _models_root(models_root)
    names = (
        "LTX-2.3-distilled-MLX",
        "LTX-2.3-dev-MLX",
        "LTX-2.3-shared-MLX",
        "LTX-Gemma3-12B",
    )
    candidates: list[dict[str, Any]] = []
    observed: set[Path] = set()

    def add_candidate(path: Path, classification: str, reason: str) -> None:
        resolved = path.resolve()
        if resolved in observed:
            return
        observed.add(resolved)
        candidates.append(
            {
                "path": str(resolved),
                "estimatedBytes": _directory_size(path) if path.is_dir() else 0,
                "classification": classification,
                "deletionAllowed": False,
                "reason": reason,
            }
        )

    for name in names:
        path = root / name
        if not path.exists():
            continue
        add_candidate(
            path,
            "superseded_ltx_runtime_artifact",
            "preserve until quantized replacements pass deep verification, "
            "a visual canary, and an operator reference audit",
        )
    if root.is_dir():
        for path in sorted(root.iterdir()):
            if path.name.endswith(".partial") or ".partial." in path.name:
                add_candidate(
                    path,
                    "incomplete_model_install_staging",
                    "inspect installer evidence before any operator-approved removal",
                )
            elif ".orphan." in path.name:
                add_candidate(
                    path,
                    "preserved_model_install_orphan",
                    "preserved recovery evidence; never remove automatically",
                )
    expected_dependency_revisions = {
        value.revision for value in local_install_dependencies()
    }
    snapshot_root = hf_home(root) / "hub"
    if snapshot_root.is_dir():
        for path in sorted(snapshot_root.glob("models--*/snapshots/*")):
            if path.name not in expected_dependency_revisions:
                add_candidate(
                    path,
                    "unreferenced_huggingface_snapshot_revision",
                    "revision is not pinned by the current Creator OS catalog",
                )
    runtime_roots = {
        "wan": _runtime_root(None),
        "ltx": _ltx_runtime_root(None),
        "longcat": _longcat_runtime_root(None),
    }
    for runtime in runtime_roots.values():
        for path in sorted(runtime.parent.glob(runtime.name + ".partial*")):
            add_candidate(
                path,
                "incomplete_runtime_install_staging",
                "inspect pinned revision and installer evidence before removal",
            )
        for path in sorted(runtime.parent.glob(runtime.name + ".orphan.*")):
            add_candidate(
                path,
                "preserved_runtime_install_orphan",
                "preserved recovery evidence; never remove automatically",
            )
    return {
        "schema": "reel_factory.local_model_legacy_storage_report.v1",
        "modelsRoot": str(root),
        "candidates": candidates,
        "candidateBytes": sum(value["estimatedBytes"] for value in candidates),
        "configuredRoots": {
            "models": str(root),
            "runtimes": {key: str(value) for key, value in runtime_roots.items()},
            "huggingFaceHome": str(hf_home(root)),
            "environmentOverrides": {
                key: os.environ.get(key)
                for key in (
                    "CREATOR_OS_LOCAL_MODELS_ROOT",
                    "CREATOR_OS_LOCAL_MLX_RUNTIME",
                    "CREATOR_OS_LOCAL_LTX_RUNTIME",
                    "CREATOR_OS_LOCAL_LONGCAT_RUNTIME",
                    "HF_HOME",
                )
                if os.environ.get(key)
            },
        },
        "deletionPerformed": False,
        "destructiveActionAvailable": False,
    }


def _install_dependency(
    dependency: LocalInstallDependency, *, root: Path, runner: Runner
) -> dict[str, Any]:
    if _dependency_ready(dependency, root):
        return {**_dependency_payload(dependency, root), "status": "already_installed"}
    if dependency.cache_only:
        # ``hf download --revision <commit>`` creates the immutable snapshot but
        # does not necessarily create ``refs/main``.  The pinned mlx-video
        # runtime asks Transformers for the repository name without a revision,
        # so offline execution cannot resolve an otherwise complete snapshot
        # without that reference.  Repair only this cache metadata after a deep
        # verification of the already-recorded snapshot; never use repair as a
        # reason to download or accept substituted files.
        if _dependency_ready(
            dependency,
            root,
            deep=True,
            require_runtime_reference=False,
        ):
            _write_cache_runtime_reference(dependency, root)
            if not _dependency_ready(dependency, root, deep=True):
                raise RuntimeError(
                    f"local_model_dependency_reference_repair_failed:{dependency.id}"
                )
            return {
                **_dependency_payload(dependency, root),
                "status": "repaired_runtime_reference",
            }
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
        expected_snapshot = _cache_snapshot_path(dependency, root)
        if Path(resolved_path).expanduser().resolve() != expected_snapshot.resolve():
            raise RuntimeError(
                f"local_model_dependency_snapshot_mismatch:{dependency.id}"
            )
        _write_cache_runtime_reference(dependency, root)
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
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(
            f"local_model_dependency_destination_requires_recovery:{dependency.id}"
        )
    partial = directory.with_name(directory.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise FileExistsError(
            f"local_model_dependency_partial_requires_recovery:{dependency.id}"
        )
    partial.mkdir(parents=True, exist_ok=False)
    _hf_download(
        dependency.repository,
        dependency.revision,
        dependency.includes,
        partial,
        runner=runner,
    )
    records = _file_records(partial)
    payload = {
        **_dependency_payload(dependency, root),
        "schema": "reel_factory.local_model_dependency.v1",
        "files": records,
    }
    atomic_write_text(
        partial / MODEL_MANIFEST,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, directory)
    return {**payload, "status": "installed"}


def _install_model(
    spec: LocalVideoModelSpec, *, root: Path, runner: Runner
) -> dict[str, Any]:
    existing = model_status(spec.model_id, models_root=root)
    if existing["ready"]:
        return {**existing, "status": "already_installed"}
    directory = spec.directory(root)
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(
            f"local_model_destination_requires_recovery:{spec.model_id}"
        )
    partial = directory.with_name(directory.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise FileExistsError(f"local_model_partial_requires_recovery:{spec.model_id}")
    partial.mkdir(parents=True, exist_ok=False)
    _hf_download(
        spec.repository,
        spec.revision,
        spec.includes,
        partial,
        runner=runner,
    )
    records = _file_records(partial)
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
        partial / MODEL_MANIFEST,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, directory)
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


def _dependency_ready(
    dependency: LocalInstallDependency,
    root: Path,
    *,
    deep: bool = False,
    require_runtime_reference: bool = True,
) -> bool:
    receipt = _dependency_receipt_path(dependency, root)
    if not receipt.is_file() or receipt.is_symlink():
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
    records = _validated_dependency_records(
        payload.get("files"), required_paths=dependency.required_paths
    )
    if records is None:
        return False
    directory = (
        Path(str(payload.get("resolvedPath") or ""))
        if dependency.cache_only
        else dependency.directory(root)
    )
    if not directory.is_dir() or directory.is_symlink():
        return False
    if dependency.cache_only:
        if (
            directory.expanduser().resolve()
            != _cache_snapshot_path(dependency, root).resolve()
        ):
            return False
        if require_runtime_reference and not _cache_runtime_reference_ready(
            dependency, root
        ):
            return False
    return all(
        (directory / record["path"]).is_file()
        and (directory / record["path"]).stat().st_size == record["size"]
        and (not deep or _sha256_file(directory / record["path"]) == record["sha256"])
        for record in records
    )


def _validated_dependency_records(
    raw_records: Any, *, required_paths: Sequence[str]
) -> list[dict[str, Any]] | None:
    """Validate receipt paths before they can authorize cache metadata repair."""

    if not isinstance(raw_records, list) or not raw_records:
        return None
    records: list[dict[str, Any]] = []
    observed_paths: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            return None
        relative_text = raw.get("path")
        if not isinstance(relative_text, str) or not relative_text:
            return None
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or "\\" in relative_text
            or ".." in relative.parts
            or relative.as_posix() != relative_text
            or relative_text in observed_paths
        ):
            return None
        size = raw.get("size")
        digest = raw.get("sha256")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            return None
        observed_paths.add(relative_text)
        records.append({"path": relative_text, "size": size, "sha256": digest})
    if not set(required_paths).issubset(observed_paths):
        return None
    return records


def _dependency_receipt_path(dependency: LocalInstallDependency, root: Path) -> Path:
    if dependency.cache_only:
        return root / ".receipts" / f"{dependency.id}.json"
    return dependency.directory(root) / MODEL_MANIFEST


def _dependency_payload(
    dependency: LocalInstallDependency, root: Path
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": dependency.id,
        "repository": dependency.repository,
        "revision": dependency.revision,
        "directory": str(dependency.directory(root)),
        "includes": list(dependency.includes),
        "requiredPaths": list(dependency.required_paths),
        "estimatedBytes": dependency.estimated_bytes,
        "licenseId": dependency.license_id,
        "cacheOnly": dependency.cache_only,
    }
    if dependency.cache_only:
        payload["runtimeReference"] = {
            "name": "main",
            "path": str(_cache_runtime_reference_path(dependency, root)),
            "revision": dependency.revision,
        }
    return payload


def _cache_repository_root(dependency: LocalInstallDependency, root: Path) -> Path:
    parts = dependency.repository.split("/")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError(f"local_model_dependency_repository_invalid:{dependency.id}")
    owner, name = parts
    return hf_home(root) / "hub" / f"models--{owner}--{name}"


def _cache_snapshot_path(dependency: LocalInstallDependency, root: Path) -> Path:
    return _cache_repository_root(dependency, root) / "snapshots" / dependency.revision


def _cache_runtime_reference_path(
    dependency: LocalInstallDependency, root: Path
) -> Path:
    return _cache_repository_root(dependency, root) / "refs" / "main"


def _cache_runtime_reference_ready(
    dependency: LocalInstallDependency, root: Path
) -> bool:
    return _cache_runtime_reference_issue(dependency, root) is None


def _cache_runtime_reference_issue(
    dependency: LocalInstallDependency, root: Path
) -> str | None:
    reference = _cache_runtime_reference_path(dependency, root)
    repository_root = _cache_repository_root(dependency, root)
    references_root = reference.parent
    if (
        repository_root.is_symlink()
        or (repository_root.exists() and not repository_root.is_dir())
        or references_root.is_symlink()
        or (references_root.exists() and not references_root.is_dir())
        or reference.is_symlink()
        or (reference.exists() and not reference.is_file())
    ):
        return "runtime_reference_unsafe"
    if not reference.exists():
        return "runtime_reference_missing"
    try:
        observed = reference.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "runtime_reference_unsafe"
    if observed != dependency.revision:
        return "runtime_reference_drift"
    return None


def _write_cache_runtime_reference(
    dependency: LocalInstallDependency, root: Path
) -> Path:
    reference = _cache_runtime_reference_path(dependency, root)
    repository_root = _cache_repository_root(dependency, root)
    references_root = reference.parent
    if (
        repository_root.is_symlink()
        or (repository_root.exists() and not repository_root.is_dir())
        or references_root.is_symlink()
        or (references_root.exists() and not references_root.is_dir())
    ):
        raise RuntimeError(f"local_model_dependency_reference_unsafe:{dependency.id}")
    if reference.exists() or reference.is_symlink():
        if not reference.is_file() or reference.is_symlink():
            raise RuntimeError(
                f"local_model_dependency_reference_unsafe:{dependency.id}"
            )
        try:
            observed = reference.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"local_model_dependency_reference_unsafe:{dependency.id}"
            ) from exc
        if observed == dependency.revision:
            return reference
        if observed.strip() != dependency.revision:
            raise RuntimeError(
                f"local_model_dependency_reference_conflict:{dependency.id}"
            )
        atomic_write_text(reference, dependency.revision, encoding="utf-8")
        if not _cache_runtime_reference_ready(dependency, root):
            raise RuntimeError(
                f"local_model_dependency_reference_write_failed:{dependency.id}"
            )
        return reference
    reference.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(reference, dependency.revision, encoding="utf-8")
    if not _cache_runtime_reference_ready(dependency, root):
        raise RuntimeError(
            f"local_model_dependency_reference_write_failed:{dependency.id}"
        )
    return reference


def _file_records(directory: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"local_model_download_symlink_forbidden:{path}")
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


def _directory_size(directory: Path) -> int:
    total = 0
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


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


def _ltx_runtime_root(value: Path | None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_LTX_RUNTIME")
    selected = selected or Path.home() / ".creator-os/runtimes/ltx-2-mlx"
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


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _installer_owned_untracked_path(runtime: Path, relative: str) -> bool:
    """Return whether one untracked runtime path is an expected installer output.

    The receipt is validated independently by every runtime status function.
    ``build/`` is setuptools' non-imported wheel staging tree. No other
    untracked path is tolerated, and symlinks at or below either owned path are
    rejected so an allowlisted name cannot escape the runtime checkout.
    """

    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    if relative != ".creator-os-runtime.json" and not relative.startswith("build/"):
        return False
    current = runtime / candidate
    while current != runtime:
        if current.is_symlink():
            return False
        current = current.parent
    return True


def _git_worktree_issue(path: Path) -> str | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "-z",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unreadable"
    if completed.returncode != 0:
        return "unreadable"
    entries = [entry for entry in completed.stdout.split("\0") if entry]
    for entry in entries:
        if len(entry) < 4 or entry[:3] != "?? ":
            return "dirty"
        if not _installer_owned_untracked_path(path, entry[3:]):
            return "dirty"
    return None


def _require_clean_git_worktree(path: Path, *, runner: Runner, error: str) -> None:
    completed = runner(
        [
            "git",
            "-C",
            str(path),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or completed.stdout.strip():
        raise RuntimeError(error)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan, install, and verify pinned local Creator OS video models."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    storage = sub.add_parser("storage-report")
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
    for value in (plan, install, status, storage):
        value.add_argument("--models-root", type=Path)
    for value in (install, status):
        value.add_argument("--runtime-root", type=Path)
        value.add_argument("--ltx-runtime-root", type=Path)
        value.add_argument("--longcat-runtime-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "catalog":
            payload = local_model_catalog()
        elif args.command == "storage-report":
            payload = legacy_storage_report(models_root=args.models_root)
        elif args.command == "plan":
            payload = install_plan(args.model, models_root=args.models_root)
        elif args.command == "status":
            payload = all_model_status(
                models_root=args.models_root,
                runtime_root=args.runtime_root,
                ltx_runtime_root=args.ltx_runtime_root,
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
                ltx_runtime_root=args.ltx_runtime_root,
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
