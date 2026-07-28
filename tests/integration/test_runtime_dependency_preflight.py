from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/ensure_runtime_dependencies.py"
    spec = importlib.util.spec_from_file_location(
        "runtime_dependency_preflight_under_test", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root(tmp_path: Path) -> Path:
    for name in (
        "package.json",
        "pnpm-workspace.yaml",
        "pyproject.toml",
        "uv.lock",
    ):
        (tmp_path / name).write_text(f"{name}\n", encoding="utf-8")
    lock = tmp_path / "pnpm-lock.yaml"
    lock.write_text("lock\n", encoding="utf-8")
    node_lock = tmp_path / "node_modules/.pnpm/lock.yaml"
    node_lock.parent.mkdir(parents=True)
    node_lock.write_text(lock.read_text(encoding="utf-8"), encoding="utf-8")
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)
    return tmp_path


def _completed(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "", "")


def test_unchanged_verified_environment_skips_only_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    root = _root(tmp_path)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        module,
        "toolchain_identity",
        lambda: {"python3": {"path": "/python", "sha256": "a", "version": "3"}},
    )

    def run(command: tuple[str, ...], _root: Path):
        calls.append(command)
        return _completed(command)

    monkeypatch.setattr(module, "_run", run)

    assert module.ensure_runtime_dependencies(root) is True
    calls.clear()
    assert module.ensure_runtime_dependencies(root) is False
    assert calls == [module.UV_CHECK]


def test_changed_dependency_or_toolchain_forces_frozen_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    root = _root(tmp_path)
    calls: list[tuple[str, ...]] = []
    toolchain = {"version": "one"}
    monkeypatch.setattr(module, "toolchain_identity", lambda: dict(toolchain))

    def run(command: tuple[str, ...], _root: Path):
        calls.append(command)
        return _completed(command)

    monkeypatch.setattr(module, "_run", run)
    assert module.ensure_runtime_dependencies(root) is True

    (root / "uv.lock").write_text("changed\n", encoding="utf-8")
    calls.clear()
    assert module.ensure_runtime_dependencies(root) is True
    assert module.PNPM_INSTALL in calls
    assert module.UV_SYNC in calls

    toolchain["version"] = "two"
    calls.clear()
    assert module.ensure_runtime_dependencies(root) is True
    assert module.PNPM_INSTALL in calls
    assert module.UV_SYNC in calls


def test_invalid_installed_environment_fails_closed_after_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    root = _root(tmp_path)
    monkeypatch.setattr(module, "toolchain_identity", lambda: {"version": "one"})
    (root / "node_modules/.pnpm/lock.yaml").write_text(
        "substituted\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        module,
        "_run",
        lambda command, _root: _completed(command),
    )

    with pytest.raises(
        RuntimeError, match="runtime dependency environment failed verification"
    ):
        module.ensure_runtime_dependencies(root)

    assert not (root / module.MARKER).exists()
