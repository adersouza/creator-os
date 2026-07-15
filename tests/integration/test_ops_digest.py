from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops_digest.py"
SPEC = importlib.util.spec_from_file_location("ops_digest", SCRIPT)
assert SPEC and SPEC.loader
ops_digest_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops_digest_module)


def _sqlite(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        for statement in statements:
            conn.execute(statement)


def test_ops_digest_reports_healthy_runtime_snapshot(tmp_path: Path) -> None:
    now = datetime(2026, 7, 2, 21, 30, tzinfo=UTC)
    repo = tmp_path / "repo"
    ops_log = tmp_path / "ops.log"
    ops_log.write_text(
        "2026-07-02T21:00:00Z [info] performance-sync: ok in 2s\n",
        encoding="utf-8",
    )
    _sqlite(
        repo / "python_packages" / "reel_factory" / "manifest.sqlite",
        [
            "CREATE TABLE reel_outcomes (imported_at INTEGER)",
            f"INSERT INTO reel_outcomes VALUES ({int(now.timestamp())})",
        ],
    )
    _sqlite(
        repo / "python_packages" / "reference_factory" / "reference_factory.sqlite",
        [
            "CREATE TABLE audio_catalog (updated_at TEXT)",
            "CREATE TABLE reference_items (id INTEGER PRIMARY KEY)",
            "INSERT INTO audio_catalog VALUES ('2026-07-02T20:00:00Z')",
            "INSERT INTO reference_items DEFAULT VALUES",
        ],
    )
    backup_log = tmp_path / "backup.log"
    backup_log.write_text(
        "2026-07-02T20:30:00Z backup ok: /snap/20260702 ( 23M)\n",
        encoding="utf-8",
    )
    ticks = (
        repo
        / "python_packages"
        / "reel_factory"
        / "project_data"
        / "orchestrator_ticks"
    )
    ticks.mkdir(parents=True)
    (ticks / "20260702T210000Z.json").write_text(
        json.dumps({"stateCounts": {"planned": 2, "awaiting_approval": 1}}),
        encoding="utf-8",
    )

    result = ops_digest_module.digest(
        repo, ops_log, data_root=repo, backup_log=backup_log, now=now
    )

    assert result["level"] == "info"
    assert "outcomes 1(+1)" in result["line"]
    assert "sync ok 30m old" in result["line"]
    assert "backup 23M 1h old" in result["line"]
    assert "gen planned 2 inbox 1" in result["line"]
    assert "audio 1h old" in result["line"]


def test_ops_digest_escalates_stale_sync_backup_and_audio(tmp_path: Path) -> None:
    now = datetime(2026, 7, 2, 21, 30, tzinfo=UTC)
    repo = tmp_path / "repo"
    ops_log = tmp_path / "ops.log"
    ops_log.write_text(
        "2026-07-02T10:00:00Z [error] performance-sync: FAILED exit=2\n",
        encoding="utf-8",
    )
    _sqlite(
        repo / "python_packages" / "reference_factory" / "reference_factory.sqlite",
        [
            "CREATE TABLE audio_catalog (updated_at TEXT)",
            "INSERT INTO audio_catalog VALUES ('2026-06-01T20:00:00Z')",
        ],
    )
    backup_log = tmp_path / "backup.log"
    backup_log.write_text(
        "2026-06-29T20:30:00Z backup ok: /snap/20260629 ( 23M)\n",
        encoding="utf-8",
    )

    result = ops_digest_module.digest(
        repo, ops_log, data_root=repo, backup_log=backup_log, now=now
    )

    assert result["level"] == "error"
    assert "sync failed" in result["line"]
    assert "backup" in result["line"]
    assert "audio 31d old" in result["line"]


def test_ops_digest_can_split_runtime_evidence_from_canonical_data(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 2, 21, 30, tzinfo=UTC)
    runtime = tmp_path / "runtime"
    data_root = tmp_path / "data"
    ops_log = tmp_path / "ops.log"
    ops_log.write_text(
        "2026-07-02T21:00:00Z [info] performance-sync: ok in 2s\n",
        encoding="utf-8",
    )
    _sqlite(
        data_root / "python_packages" / "reel_factory" / "manifest.sqlite",
        [
            "CREATE TABLE reel_outcomes (imported_at INTEGER)",
            f"INSERT INTO reel_outcomes VALUES ({int(now.timestamp())})",
        ],
    )
    _sqlite(
        data_root
        / "python_packages"
        / "reference_factory"
        / "reference_factory.sqlite",
        [
            "CREATE TABLE audio_catalog (updated_at TEXT)",
            "CREATE TABLE reference_items (id INTEGER PRIMARY KEY)",
            "INSERT INTO audio_catalog VALUES ('2026-07-02T20:00:00Z')",
            "INSERT INTO reference_items DEFAULT VALUES",
        ],
    )
    ticks = (
        runtime
        / "python_packages"
        / "reel_factory"
        / "project_data"
        / "orchestrator_ticks"
    )
    ticks.mkdir(parents=True)
    (ticks / "20260702T210000Z.json").write_text(
        json.dumps({"stateCounts": {"planned": 3, "awaiting_approval": 2}}),
        encoding="utf-8",
    )
    backup_log = tmp_path / "backup.log"
    backup_log.write_text(
        "2026-07-02T20:30:00Z backup ok: /snap/20260702 ( 23M)\n",
        encoding="utf-8",
    )

    result = ops_digest_module.digest(
        runtime,
        ops_log,
        data_root=data_root,
        backup_log=backup_log,
        now=now,
    )

    assert result["level"] == "info"
    assert "outcomes 1(+1)" in result["line"]
    assert "gen planned 3 inbox 2" in result["line"]
    assert "audio 1h old" in result["line"]
