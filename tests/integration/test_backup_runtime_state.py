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
verify_backup = backup_module.verify_backup


def _sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (name) VALUES ('ok')")


def test_backup_runtime_state_vacuums_dbs_and_copies_runtime_dirs(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    _sqlite_db(repo / "python_packages/reel_factory/render_queue.sqlite")
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
    assert set(backed_up) == {
        "reel_manifest",
        "render_queue",
        "campaign_factory",
        "reference_factory",
    }
    backup_root = tmp_path / "backups/test"
    with sqlite3.connect(backup_root / backed_up["reel_manifest"]) as conn:
        assert conn.execute("SELECT name FROM items").fetchone()[0] == "ok"
    assert (
        tmp_path
        / "backups/test/python_packages/reel_factory/03_audio_library/track.json"
    ).exists()
    verification = verify_backup(backup_root)
    assert verification["status"] == "ok"
    assert {row["name"] for row in verification["databases"]} == set(backed_up)


def test_backup_runtime_state_never_copies_creator_os_credentials(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    credentials = tmp_path / ".creator-os"
    credentials.mkdir()
    (credentials / "campaign-factory-ingest.env").write_text(
        "CAMPAIGN_FACTORY_INGEST_SECRET=never-copy-me\n", encoding="utf-8"
    )

    result = backup_runtime_state(repo, tmp_path / "backups", timestamp="safe")

    backup_root = Path(result["backupDir"])
    assert not any(".creator-os" in str(path) for path in backup_root.rglob("*"))
    assert "never-copy-me" not in "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in backup_root.rglob("*")
        if path.is_file()
    )


def test_verify_backup_rejects_tampered_database(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    result = backup_runtime_state(repo, tmp_path / "backups", timestamp="tamper")
    backup_root = Path(result["backupDir"])
    db = backup_root / "databases/manifest.sqlite"
    db.write_bytes(db.read_bytes() + b"tampered")

    try:
        verify_backup(backup_root)
    except RuntimeError as exc:
        assert "reel_manifest" in str(exc)
    else:
        raise AssertionError("tampered backup must fail verification")
