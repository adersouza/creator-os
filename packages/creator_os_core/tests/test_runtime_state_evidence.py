from __future__ import annotations

import ast
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from creator_os_core.runtime_state_evidence import (
    load_json_manifest,
    parse_utc_timestamp,
    retention_deadline_evidence,
    scan_active_path_references,
    tree_snapshot,
    verify_sqlite_evidence,
)


def _database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO evidence (value) VALUES (?)", (("one",), ("two",))
        )
    path.chmod(0o600)


def test_manifest_and_timestamp_evidence_is_strict_and_read_only(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"schema": "example.v1"}\n', encoding="utf-8")
    before = manifest.read_bytes()

    resolved, body = load_json_manifest(manifest)

    assert resolved == manifest.resolve()
    assert body == {"schema": "example.v1"}
    assert manifest.read_bytes() == before
    assert parse_utc_timestamp("2026-07-15T21:00:00Z") == datetime(
        2026, 7, 15, 21, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="timezone"):
        parse_utc_timestamp("2026-07-15T21:00:00")

    manifest.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_json_manifest(manifest)


def test_tree_snapshot_preserves_manifest_shape_and_excludes_credentials(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "media.mp4").write_bytes(b"media")
    (root / "ops.log").write_text("proof\n", encoding="utf-8")
    (root / "runtime.env").write_text("SECRET=value\n", encoding="utf-8")

    public = tree_snapshot(root, exclude_private=True)
    logs = tree_snapshot(root, logs_only=True, exclude_private=True)

    assert set(public) == {"path", "files", "bytes", "treeSha256"}
    assert public["files"] == 2
    assert logs["files"] == 1
    assert logs["bytes"] == len(b"proof\n")


def test_sqlite_evidence_proves_hash_rows_permissions_and_clean_restore(
    tmp_path: Path,
) -> None:
    database = tmp_path / "private/state.sqlite"
    _database(database)
    before = database.read_bytes()

    initial = verify_sqlite_evidence(database)
    result = verify_sqlite_evidence(
        database,
        expected_sha256=initial["snapshot"]["sha256"],
        expected_row_counts={"evidence": 2},
        required_mode="0o600",
        required_parent_mode="0o700",
        require_clean_restore=True,
    )

    assert result["valid"] is True
    assert all(result["checks"].values())
    assert result["cleanRestore"] == {
        "integrity": "ok",
        "rowCounts": {"evidence": 2},
    }
    assert database.read_bytes() == before


def test_retention_and_active_path_checks_fail_closed(tmp_path: Path) -> None:
    now = datetime(2026, 7, 15, 21, tzinfo=UTC)
    elapsed = retention_deadline_evidence(
        (now - timedelta(seconds=1)).isoformat(), now=now
    )
    pending = retention_deadline_evidence(
        (now + timedelta(seconds=1)).isoformat(), now=now
    )
    assert elapsed["elapsed"] is True
    assert pending["elapsed"] is False

    active = tmp_path / "active"
    active.mkdir()
    old_path = "/legacy/campaign.sqlite"
    (active / "runtime.env").write_text(
        f"CAMPAIGN_FACTORY_DB={old_path}\n", encoding="utf-8"
    )
    result = scan_active_path_references(
        {old_path}, [active, tmp_path / "missing-root"]
    )
    assert result["references"] == [
        {"config": str(active / "runtime.env"), "oldPath": old_path}
    ]
    assert result["scanErrors"] == [
        {"root": str(tmp_path / "missing-root"), "error": "path is missing"}
    ]


def test_runtime_state_evidence_exposes_no_destructive_primitive() -> None:
    module_path = (
        Path(__file__).parents[1] / "creator_os_core/runtime_state_evidence.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_attributes = {"unlink", "rmtree", "remove", "removedirs", "rmdir"}

    assert not any(
        isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(token in node.name for token in ("apply", "delete", "remove"))
        for node in ast.walk(tree)
    )
