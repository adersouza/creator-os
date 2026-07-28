#!/usr/bin/env python3
"""Fail-closed runtime dependency setup with an exact local environment receipt."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "creator_os.runtime_dependency_environment.v1"
MARKER = ".venv/.creator-os-runtime-dependencies.json"
PNPM_INSTALL = ("pnpm", "install", "--frozen-lockfile")
UV_SYNC = ("uv", "sync", "--all-extras", "--all-packages", "--frozen")
UV_CHECK = (*UV_SYNC, "--check")
TOOLS = ("node", "pnpm", "python3", "uv")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def dependency_inputs(root: Path) -> dict[str, str]:
    candidates = [
        root / "package.json",
        root / "pnpm-lock.yaml",
        root / "pnpm-workspace.yaml",
        root / "pyproject.toml",
        root / "uv.lock",
        *root.glob("packages/*/package.json"),
        *root.glob("packages/*/pyproject.toml"),
        *root.glob("python_packages/*/pyproject.toml"),
    ]
    files = sorted({path for path in candidates if path.is_file()})
    return {str(path.relative_to(root)): _sha256(path) for path in files}


def toolchain_identity() -> dict[str, dict[str, str]]:
    identity: dict[str, dict[str, str]] = {}
    for tool in TOOLS:
        command = shutil.which(tool)
        if not command:
            raise RuntimeError(f"runtime dependency tool missing: {tool}")
        resolved = Path(command).resolve()
        completed = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(f"runtime dependency tool unreadable: {tool}")
        identity[tool] = {
            "path": str(resolved),
            "sha256": _sha256(resolved),
            "version": (completed.stdout or completed.stderr).strip().splitlines()[0],
        }
    return identity


def _run(command: tuple[str, ...], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def environment_valid(root: Path) -> bool:
    node_lock = root / "node_modules/.pnpm/lock.yaml"
    source_lock = root / "pnpm-lock.yaml"
    if (
        not node_lock.is_file()
        or not source_lock.is_file()
        or _sha256(node_lock) != _sha256(source_lock)
    ):
        return False
    python = root / ".venv/bin/python"
    if not python.is_file() or not os.access(python, os.X_OK):
        return False
    return _run(UV_CHECK, root).returncode == 0


def _expected(root: Path) -> dict[str, Any]:
    core = {
        "schema": SCHEMA,
        "dependencyInputs": dependency_inputs(root),
        "toolchain": toolchain_identity(),
    }
    return {**core, "fingerprint": _fingerprint(core)}


def _load_marker(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_marker(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def ensure_runtime_dependencies(root: Path) -> bool:
    root = root.resolve()
    marker_path = root / MARKER
    expected = _expected(root)
    if _load_marker(marker_path) == expected and environment_valid(root):
        print(
            "runtime dependencies: verified unchanged environment; "
            "frozen reconstruction skipped"
        )
        return False

    for command in (PNPM_INSTALL, UV_SYNC):
        completed = _run(command, root)
        if completed.returncode:
            sys.stdout.write(completed.stdout)
            sys.stderr.write(completed.stderr)
            raise RuntimeError(
                "runtime dependency reconstruction failed: " + " ".join(command)
            )
    if not environment_valid(root):
        raise RuntimeError("runtime dependency environment failed verification")
    _write_marker(marker_path, expected)
    print("runtime dependencies: frozen environment reconstructed and verified")
    return True


def main() -> int:
    try:
        ensure_runtime_dependencies(Path.cwd())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
