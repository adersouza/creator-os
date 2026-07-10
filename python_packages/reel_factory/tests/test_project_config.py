"""Regression tests for project_config save/load roundtrip.

``save_config`` previously crashed with a NameError
(``config_pathatomic_write_text``) because the path helper and the atomic
writer were fused into a single missing identifier. These tests exercise the
full write path so any regression in the writer call fails loudly.
"""

from __future__ import annotations

from pathlib import Path

from reel_factory.project_config import (
    DEFAULT_CONFIG,
    config_path,
    load_config,
    save_config,
)


def test_save_config_writes_file_and_roundtrips(tmp_path: Path) -> None:
    result = save_config(tmp_path, {"workers": 7, "audio_enabled": True})

    cfg_file = config_path(tmp_path)
    assert cfg_file.exists(), "save_config must write reel_factory.toml"

    loaded = load_config(tmp_path)
    assert loaded == result
    assert loaded["workers"] == 7
    assert loaded["audio_enabled"] is True
    # untouched keys keep defaults
    assert loaded["caption_renderer"] == DEFAULT_CONFIG["caption_renderer"]


def test_save_config_ignores_unknown_keys(tmp_path: Path) -> None:
    save_config(tmp_path, {"not_a_real_key": "x", "workers": 2})
    loaded = load_config(tmp_path)
    assert "not_a_real_key" not in loaded
    assert loaded["workers"] == 2


def test_save_config_renders_lists_and_strings(tmp_path: Path) -> None:
    save_config(
        tmp_path,
        {"target_ratios": ["9:16", "1:1"], "output_profile": 'weird "quoted" name'},
    )
    loaded = load_config(tmp_path)
    assert loaded["target_ratios"] == ["9:16", "1:1"]
    assert loaded["output_profile"] == 'weird "quoted" name'
