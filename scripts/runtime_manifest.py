#!/usr/bin/env python3
"""Build a secret-free manifest of inputs needed to reproduce Creator OS.

The manifest establishes equivalent dependency, toolchain, configuration, font,
contract, and model inputs.  It deliberately does not claim byte-identical
media output across macOS, hardware, codecs, or native rendering frameworks.
"""

from __future__ import annotations

import argparse
import ast
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
from importlib import util as importlib_util
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "creator_os.equivalent_runtime_manifest.v1"
EQUIVALENCE_SCOPE: Final = "exact_inputs_without_byte_output_equivalence"
REQUIRED_TOOLS: Final = (
    "node",
    "pnpm",
    "python3",
    "uv",
    "ffmpeg",
    "ffprobe",
    "tesseract",
)
OPTIONAL_TOOLS: Final = ("fpcalc", "swift", "strings")
BREW_FORMULAE: Final = ("ffmpeg", "tesseract", "chromaprint")
MODEL_CATALOG_PATHS: Final = (
    "python_packages/campaign_factory/campaign_factory/production_motion_recipe.py",
)
ENVIRONMENT_KEYS: Final = (
    "CREATOR_OS_ROOT",
    "CREATOR_OS_RUNTIME_ROOT",
    "CREATOR_OS_STATE_ROOT",
    "CREATOR_OS_ARTIFACT_ROOT",
    "CREATOR_OS_MODEL_ROOT",
    "CREATOR_OS_LOG_ROOT",
    "CAMPAIGN_FACTORY_ROOT",
    "CAMPAIGN_FACTORY_DB",
    "REEL_FACTORY_ROOT",
    "REEL_FACTORY_MANIFEST_DB",
    "REEL_FACTORY_RENDER_QUEUE_DB",
    "REFERENCE_FACTORY_ROOT",
    "REFERENCE_FACTORY_DB",
    "REFERENCE_FACTORY_DATA_ROOT",
    "CONTENTFORGE_ROOT",
    "THREADSDASH_ROOT",
    "CREATOR_OS_KILL_SWITCH",
    "CREATOR_OS_SPEND_KILL_SWITCH",
    "CREATOR_OS_SPEND_AUTH_SECRET",
    "CAMPAIGN_FACTORY_INGEST_SECRET",
    "OPENAI_API_KEY",
    "HIGGSFIELD_API_KEY",
    "GEMINI_API_KEY",
)
_SENSITIVE_NAME = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASS|API_KEY|PRIVATE_KEY|CREDENTIAL)", re.IGNORECASE
)
_ACTION = re.compile(r"^\s*(?:-\s*)?uses:\s*([^@\s]+)@([^\s#]+)")
_SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


class RuntimeManifestError(RuntimeError):
    """Raised when required equivalence evidence cannot be captured."""


def _dependency_inputs(root: Path) -> dict[str, str]:
    """Reuse the frozen-environment input collector without importing app code."""

    helper = Path(__file__).resolve().with_name("ensure_runtime_dependencies.py")
    spec = importlib_util.spec_from_file_location(
        "creator_os_runtime_dependency_inputs", helper
    )
    if spec is None or spec.loader is None:
        raise RuntimeManifestError("runtime dependency helper is unavailable")
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.dependency_inputs(root)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run(
    command: list[str], *, cwd: Path, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def _version_arguments(tool: str) -> list[str]:
    if tool in {"ffmpeg", "ffprobe", "fpcalc"}:
        return ["-version"]
    return ["--version"]


def binary_record(tool: str, *, root: Path) -> dict[str, Any] | None:
    executable = shutil.which(tool)
    if not executable:
        return None
    resolved = Path(executable).resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise RuntimeManifestError(f"runtime tool is not a regular file: {tool}")
    completed = _run(
        [str(resolved), *_version_arguments(tool)],
        cwd=root,
        timeout=20,
    )
    lines = (completed.stdout or completed.stderr).splitlines()
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "version": lines[0][:500] if lines else None,
        "versionCommandReturnCode": completed.returncode,
    }


def binary_inventory(root: Path) -> dict[str, Any]:
    tools = {
        tool: binary_record(tool, root=root)
        for tool in (*REQUIRED_TOOLS, *OPTIONAL_TOOLS)
    }
    missing = [tool for tool in REQUIRED_TOOLS if tools[tool] is None]
    if missing:
        raise RuntimeManifestError(
            "required runtime tools missing: " + ", ".join(sorted(missing))
        )
    return {
        "required": {tool: tools[tool] for tool in REQUIRED_TOOLS},
        "optional": {tool: tools[tool] for tool in OPTIONAL_TOOLS},
        "missingOptional": sorted(
            tool for tool in OPTIONAL_TOOLS if tools[tool] is None
        ),
    }


def git_identity(root: Path) -> dict[str, Any]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=root)
    if commit.returncode:
        raise RuntimeManifestError("repository commit is unreadable")
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root
    )
    if status.returncode:
        raise RuntimeManifestError("repository status is unreadable")
    return {
        "commitSha": commit.stdout.strip(),
        "dirty": bool(status.stdout.strip()),
        "dirtyEntryCount": len(status.stdout.splitlines()),
    }


def workflow_inventory(root: Path) -> dict[str, Any]:
    workflows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    workflow_root = root / ".github" / "workflows"
    for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        relative = path.relative_to(root).as_posix()
        workflows.append({"path": relative, "sha256": sha256_file(path)})
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = _ACTION.match(line)
            if not match:
                continue
            owner, reference = match.groups()
            actions.append(
                {
                    "workflow": relative,
                    "line": line_number,
                    "action": owner,
                    "reference": reference,
                    "fullCommitPin": bool(_SHA_PIN.fullmatch(reference)),
                }
            )
    return {
        "files": workflows,
        "actions": actions,
        "allActionsPinned": bool(actions)
        and all(item["fullCommitPin"] for item in actions),
    }


def brew_inventory(root: Path) -> dict[str, Any]:
    brew = shutil.which("brew")
    if not brew:
        return {"available": False, "formulae": {}}
    resolved = Path(brew).resolve()
    completed = _run(
        [str(resolved), "list", "--versions", *BREW_FORMULAE],
        cwd=root,
        timeout=30,
    )
    formulae: dict[str, list[str]] = {name: [] for name in BREW_FORMULAE}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] in formulae:
            formulae[parts[0]] = parts[1:]
    return {
        "available": True,
        "executable": {
            "path": str(resolved),
            "sha256": sha256_file(resolved),
        },
        "formulae": formulae,
        "queryReturnCode": completed.returncode,
    }


def _file_records(root: Path, paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(set(paths)):
        if not path.is_file() or path.is_symlink():
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return records


def font_inventory(root: Path) -> list[dict[str, Any]]:
    font_root = root / "python_packages" / "reel_factory" / "fonts"
    return _file_records(
        root,
        [
            path
            for path in font_root.glob("*")
            if path.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}
        ],
    )


def contract_inventory(root: Path) -> list[dict[str, Any]]:
    contract_root = root / "packages" / "pipeline_contracts"
    paths = [
        contract_root / "contract-manifest.json",
        contract_root / "typescript" / "generated-schemas.ts",
        *list((contract_root / "pipeline_contracts" / "schemas").glob("*.json")),
    ]
    return _file_records(root, paths)


def native_integration_inventory(root: Path) -> list[dict[str, Any]]:
    return _file_records(
        root,
        [
            *root.glob("packages/**/*.swift"),
            *root.glob("python_packages/**/*.swift"),
        ],
    )


def _literal_string(node: ast.AST) -> str | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, str) else None


def model_catalog_inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in MODEL_CATALOG_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        identities: set[tuple[str, str]] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                value_node = node.value
                value = _literal_string(value_node) if value_node is not None else None
                for target in targets:
                    if (
                        isinstance(target, ast.Name)
                        and value
                        and any(
                            marker in target.id.upper()
                            for marker in ("MODEL", "REVISION", "COMMIT")
                        )
                    ):
                        identities.add((target.id, value))
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg not in {
                        "model_id",
                        "model_revision",
                        "repo_id",
                        "revision",
                    }:
                        continue
                    value = _literal_string(keyword.value)
                    if value:
                        identities.add((keyword.arg, value))
        records.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "declaredIdentities": [
                    {"field": field, "value": value}
                    for field, value in sorted(identities)
                ],
            }
        )
    return records


def model_file_inventory(model_root: Path) -> dict[str, Any]:
    resolved = model_root.expanduser().resolve()
    if not resolved.exists():
        return {
            "root": str(resolved),
            "present": False,
            "files": [],
            "complete": True,
        }
    if not resolved.is_dir() or resolved.is_symlink():
        raise RuntimeManifestError("model root must be a regular directory")
    files: list[dict[str, Any]] = []
    unsafe: list[str] = []
    for path in sorted(resolved.rglob("*")):
        try:
            path_stat = path.lstat()
        except OSError:
            unsafe.append(str(path))
            continue
        if stat.S_ISLNK(path_stat.st_mode):
            unsafe.append(str(path))
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            continue
        files.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "bytes": path_stat.st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "root": str(resolved),
        "present": True,
        "files": files,
        "unsafeEntries": unsafe,
        "complete": not unsafe,
    }


def environment_inventory(env: dict[str, str] | os._Environ[str]) -> dict[str, Any]:
    return {
        "secretMaterialIncluded": False,
        "variables": [
            {
                "name": name,
                "configured": bool(env.get(name)),
                "sensitive": bool(_SENSITIVE_NAME.search(name)),
                "valueRecorded": False,
            }
            for name in ENVIRONMENT_KEYS
        ],
    }


def build_manifest(
    root: Path,
    *,
    env: dict[str, str] | os._Environ[str] | None = None,
    model_root: Path | None = None,
) -> dict[str, Any]:
    resolved_root = root.expanduser().resolve()
    values = os.environ if env is None else env
    selected_model_root = model_root or Path(
        values.get("CREATOR_OS_MODEL_ROOT") or Path.home() / ".creator-os" / "models"
    )
    core = {
        "schema": SCHEMA,
        "claim": {
            "scope": EQUIVALENCE_SCOPE,
            "byteIdenticalMediaOutputClaimed": False,
            "limitations": [
                "host-native codecs and renderers may differ across macOS releases",
                "hardware acceleration may differ across Intel and Apple Silicon",
                "font and native framework behavior requires output qualification",
                "secret values are intentionally excluded and must be supplied securely",
            ],
        },
        "repository": git_identity(resolved_root),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "pythonImplementation": platform.python_implementation(),
            "pythonVersion": platform.python_version(),
        },
        "dependencyInputs": _dependency_inputs(resolved_root),
        "toolchain": binary_inventory(resolved_root),
        "homebrew": brew_inventory(resolved_root),
        "workflows": workflow_inventory(resolved_root),
        "fonts": font_inventory(resolved_root),
        "pipelineContracts": contract_inventory(resolved_root),
        "nativeIntegrationSources": native_integration_inventory(resolved_root),
        "modelCatalogs": model_catalog_inventory(resolved_root),
        "modelFiles": model_file_inventory(selected_model_root),
        "environment": environment_inventory(values),
    }
    qualification_blockers: list[str] = []
    if not core["workflows"]["allActionsPinned"]:
        qualification_blockers.append("github_actions_not_fully_commit_pinned")
    if not core["modelFiles"]["complete"]:
        qualification_blockers.append("model_file_inventory_incomplete")
    core["qualification"] = {
        "equivalentInputManifestComplete": not qualification_blockers,
        "blockers": qualification_blockers,
        "runtimeHealthProven": False,
        "mediaOutputEquivalenceProven": False,
    }
    return {**core, "manifestFingerprint": fingerprint(core)}


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model-root", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = build_manifest(
            args.root,
            model_root=args.model_root,
        )
        write_manifest(args.out, payload)
    except (OSError, RuntimeManifestError, subprocess.SubprocessError) as exc:
        print(f"runtime manifest failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "manifestFingerprint": payload["manifestFingerprint"],
                "output": str(args.out.expanduser().resolve()),
                "qualification": payload["qualification"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
