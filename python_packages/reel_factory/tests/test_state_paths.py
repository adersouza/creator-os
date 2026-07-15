from __future__ import annotations

from pathlib import Path

from reel_factory.state_paths import manifest_db_path, render_queue_db_path, state_root


def test_state_paths_default_outside_checkout(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path / "home")}

    assert manifest_db_path(env=env) == (
        tmp_path / "home/.creator-os/state/reel_factory/manifest.sqlite"
    )
    assert render_queue_db_path(env=env) == (
        tmp_path / "home/.creator-os/state/reel_factory/render_queue.sqlite"
    )
    assert state_root(env=env) == tmp_path / "home/.creator-os/state/reel_factory"


def test_state_paths_keep_explicit_component_overrides(tmp_path: Path) -> None:
    env = {
        "REEL_FACTORY_MANIFEST_DB": str(tmp_path / "manifest.sqlite"),
        "REEL_FACTORY_RENDER_QUEUE_DB": str(tmp_path / "queue.sqlite"),
    }

    assert manifest_db_path(env=env) == tmp_path / "manifest.sqlite"
    assert render_queue_db_path(env=env) == tmp_path / "queue.sqlite"


def test_state_paths_keep_explicit_legacy_root_without_overrides(
    tmp_path: Path,
) -> None:
    assert manifest_db_path(tmp_path, env={}) == tmp_path / "manifest.sqlite"
    assert render_queue_db_path(tmp_path, env={}) == tmp_path / "render_queue.sqlite"
