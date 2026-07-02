from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_runtime_state.py"
SPEC = importlib.util.spec_from_file_location("backup_runtime_state", SCRIPT)
assert SPEC and SPEC.loader
backup_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_module)
backup_runtime_state = backup_module.backup_runtime_state


def _sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (name) VALUES ('ok')")


def test_backup_runtime_state_vacuums_dbs_and_copies_runtime_dirs(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    _sqlite_db(repo / "python_packages/campaign_factory/campaign_factory.sqlite")
    _sqlite_db(repo / "python_packages/reference_factory/reference_factory.sqlite")
    audio = repo / "python_packages/reel_factory/03_audio_library"
    audio.mkdir(parents=True)
    (audio / "track.json").write_text("{}", encoding="utf-8")

    result = backup_runtime_state(repo, tmp_path / "backups", timestamp="test")

    backed_up = {
        row["name"]: Path(row["path"])
        for row in result["databases"]
        if row["status"] == "backed_up"
    }
    assert set(backed_up) == {"reel_manifest", "campaign_factory", "reference_factory"}
    with sqlite3.connect(backed_up["reel_manifest"]) as conn:
        assert conn.execute("SELECT name FROM items").fetchone()[0] == "ok"
    assert (
        tmp_path
        / "backups/test/python_packages/reel_factory/03_audio_library/track.json"
    ).exists()
