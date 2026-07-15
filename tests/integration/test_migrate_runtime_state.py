from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from creator_os_core.runtime_paths import resolve_runtime_paths

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/migrate_runtime_state.py"
SPEC = importlib.util.spec_from_file_location("migrate_runtime_state", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def _database(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO evidence (value) VALUES (?)",
            ((f"value-{index}",) for index in range(rows)),
        )


def _sources(tmp_path: Path) -> dict[str, Path]:
    sources = {
        "campaign_factory": tmp_path / "legacy/campaign.sqlite",
        "reference_factory": tmp_path / "legacy/reference.sqlite",
        "reel_manifest": tmp_path / "legacy/manifest.sqlite",
        "render_queue": tmp_path / "legacy/render-queue.sqlite",
    }
    for index, path in enumerate(sources.values(), start=1):
        _database(path, index)
    return sources


def test_state_migration_copies_and_verifies_without_deleting_sources(
    tmp_path: Path,
) -> None:
    paths = resolve_runtime_paths(
        tmp_path / "creator-os", env={"HOME": str(tmp_path / "home")}
    )
    sources = _sources(tmp_path)
    artifacts = tmp_path / "legacy/artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "reel.mp4").write_bytes(b"media")
    (artifacts / "secrets.toml").write_text("secret", encoding="utf-8")
    shared_fonts = tmp_path / "legacy/fonts"
    shared_fonts.mkdir()
    (shared_fonts / "caption.woff2").write_bytes(b"font")
    (artifacts / "fonts").symlink_to(shared_fonts, target_is_directory=True)
    (artifacts / "backup-fonts").symlink_to(shared_fonts, target_is_directory=True)
    log = tmp_path / "legacy/ops.log"
    log.write_text("runtime proof\n", encoding="utf-8")

    plan = migration.migration_plan(
        database_sources=sources,
        directory_sources=[
            ("artifact", "accepted", artifacts),
            ("log", "ops", log),
        ],
        paths=paths,
    )
    result = migration.apply_migration(plan, tmp_path / "evidence", timestamp="test")
    verification = migration.verify_migration(Path(result["manifest"]))

    assert result["status"] == "migrated"
    assert verification["status"] == "verified"
    assert all(path.exists() for path in sources.values())
    assert paths.campaign_factory_db.exists()
    assert paths.reference_factory_db.exists()
    assert paths.reel_manifest_db.exists()
    assert paths.reel_render_queue_db.exists()
    assert (paths.artifact_root / "media/accepted/reel.mp4").exists()
    assert (paths.artifact_root / "media/accepted/fonts/caption.woff2").exists()
    assert (paths.artifact_root / "media/accepted/backup-fonts/caption.woff2").exists()
    assert not (paths.artifact_root / "media/accepted/secrets.toml").exists()
    assert (paths.log_root / "ops/ops.log").read_text(encoding="utf-8") == (
        "runtime proof\n"
    )


def test_state_migration_refuses_existing_canonical_database(tmp_path: Path) -> None:
    paths = resolve_runtime_paths(
        tmp_path / "creator-os", env={"HOME": str(tmp_path / "home")}
    )
    sources = _sources(tmp_path)
    _database(paths.campaign_factory_db, 1)
    plan = migration.migration_plan(
        database_sources=sources,
        directory_sources=[],
        paths=paths,
    )

    with pytest.raises(FileExistsError, match="database destinations"):
        migration.apply_migration(plan, tmp_path / "evidence", timestamp="test")


def test_state_migration_refuses_destination_nested_inside_source(
    tmp_path: Path,
) -> None:
    paths = resolve_runtime_paths(
        tmp_path / "creator-os", env={"HOME": str(tmp_path / "home")}
    )
    sources = _sources(tmp_path)
    paths.config_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="destination cannot be nested"):
        migration.migration_plan(
            database_sources=sources,
            directory_sources=[("log", "ops", paths.config_root)],
            paths=paths,
        )
