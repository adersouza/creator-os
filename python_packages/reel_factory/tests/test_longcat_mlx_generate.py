from __future__ import annotations

import sys
from pathlib import Path

import pytest
from reel_factory.longcat_mlx_generate import (
    _runtime_import_path,
    _upstream_module,
    _verify_runtime_recipe,
)


def _write_runtime(root: Path) -> None:
    files = {
        "longcat_video_avatar/__init__.py": "",
        "longcat_video_avatar/models/__init__.py": "",
        "longcat_video_avatar/models/avatar/__init__.py": "",
        "longcat_video_avatar/models/avatar/longcat_video_dit_avatar.py": (
            "SENTINEL = 'nested-package-loaded'\n"
        ),
        "scripts/run_inference.py": (
            "def build_pipeline():\n"
            "    from longcat_video_avatar.models.avatar."
            "longcat_video_dit_avatar import SENTINEL\n"
            "    return SENTINEL\n"
        ),
    }
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_runtime_import_path_exposes_nested_upstream_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_runtime(tmp_path)
    for name in tuple(sys.modules):
        if name == "longcat_video_avatar" or name.startswith("longcat_video_avatar."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    original_path = list(sys.path)

    with _runtime_import_path(tmp_path):
        upstream = _upstream_module(tmp_path)
        assert upstream.build_pipeline() == "nested-package-loaded"

    assert sys.path == original_path


def test_runtime_import_path_rejects_missing_upstream_package(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="longcat_upstream_package_missing"):
        with _runtime_import_path(tmp_path):
            raise AssertionError("unreachable")


def test_runtime_recipe_requires_exact_dmd_guidance_and_fps() -> None:
    class Config:
        num_sampling_steps = 8
        target_fps = 25
        text_guidance_scale = 4.0
        audio_guidance_scale = 4.0

    class Args:
        sampling_steps = 8
        fps = 25
        text_guidance_scale = 4.0
        audio_guidance_scale = 4.0

    _verify_runtime_recipe(Config(), Args())
    Args.audio_guidance_scale = 5.0
    with pytest.raises(RuntimeError, match="audio_guidance_scale"):
        _verify_runtime_recipe(Config(), Args())
