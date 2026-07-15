from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from creator_os_core.runtime_paths import resolve_runtime_paths

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_script("migrate_runtime_state.py")
backup = _load_script("backup_runtime_state.py")
cleanup = _load_script("runtime_state_cleanup_eligibility.py")


def _database(path: Path, rows: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO evidence (value) VALUES (?)",
            ((f"value-{index}",) for index in range(rows)),
        )


def _fixture(tmp_path: Path) -> dict[str, object]:
    paths = resolve_runtime_paths(
        tmp_path / "creator-os", env={"HOME": str(tmp_path / "home")}
    )
    sources = {
        "campaign_factory": tmp_path / "legacy/campaign.sqlite",
        "reference_factory": tmp_path / "legacy/reference.sqlite",
        "reel_manifest": tmp_path / "legacy/manifest.sqlite",
        "render_queue": tmp_path / "legacy/render-queue.sqlite",
    }
    for index, path in enumerate(sources.values(), start=1):
        _database(path, index)

    plan = migration.migration_plan(
        database_sources=sources,
        directory_sources=[],
        paths=paths,
    )
    result = migration.apply_migration(plan, tmp_path / "evidence", timestamp="test")
    manifest_path = Path(result["manifest"])

    # Legitimate post-cutover state must not invalidate cleanup eligibility.
    with sqlite3.connect(paths.campaign_factory_db) as conn:
        conn.execute("INSERT INTO evidence (value) VALUES ('post-cutover')")

    backup_result = backup.backup_runtime_state(
        paths.source_root,
        tmp_path / "backups",
        timestamp="fresh",
        database_sources=(
            ("campaign_factory", paths.campaign_factory_db, Path("campaign.sqlite")),
            ("reference_factory", paths.reference_factory_db, Path("reference.sqlite")),
            ("reel_manifest", paths.reel_manifest_db, Path("manifest.sqlite")),
            ("render_queue", paths.reel_render_queue_db, Path("render-queue.sqlite")),
        ),
        directory_sources=(),
    )
    now = datetime.now(UTC)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rollbackRetainUntil"] = (now - timedelta(seconds=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    operating_cycle = tmp_path / "operating-cycle.json"
    operating_cycle.write_text(
        json.dumps(
            {
                "schema": cleanup.OPERATING_CYCLE_SCHEMA,
                "status": "PASS",
                "completedAt": now.isoformat(),
                "checks": {
                    "runtimeShaMatched": True,
                    "performanceSyncSucceeded": True,
                    "learningFanoutObserved": True,
                },
            }
        ),
        encoding="utf-8",
    )
    active_config = tmp_path / "active-config"
    active_config.mkdir()
    return {
        "now": now,
        "paths": paths,
        "sources": sources,
        "manifest": manifest_path,
        "backup": Path(backup_result["backupDir"]),
        "operating_cycle": operating_cycle,
        "active_config": active_config,
    }


def _report(fixture: dict[str, object], **overrides):
    arguments = {
        "operating_cycle_evidence": fixture["operating_cycle"],
        "backup_dir": fixture["backup"],
        "active_config_roots": [fixture["active_config"]],
        "now": fixture["now"],
    }
    arguments.update(overrides)
    return cleanup.cleanup_eligibility_report(fixture["manifest"], **arguments)


def test_cleanup_eligibility_accepts_legitimate_live_database_drift(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    protected = [
        *fixture["sources"].values(),
        fixture["paths"].campaign_factory_db,
        fixture["paths"].reference_factory_db,
        fixture["paths"].reel_manifest_db,
        fixture["paths"].reel_render_queue_db,
    ]
    before = {path: path.read_bytes() for path in protected}

    report = _report(fixture)

    assert report["status"] == "ELIGIBLE"
    assert report["reportOnly"] is True
    assert report["deletionPerformed"] is False
    assert report["candidates"]
    assert all(row["cleanupEligible"] for row in report["candidates"])
    canonical = next(
        check for check in report["checks"] if check["name"] == "canonical-databases"
    )
    campaign = next(
        row for row in canonical["databases"] if row["name"] == "campaign_factory"
    )
    assert campaign["rowCountsChangedSinceCutover"] is True
    assert all(path.exists() for path in fixture["sources"].values())
    assert {path: path.read_bytes() for path in protected} == before


def test_cleanup_eligibility_fails_before_retention_gate(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["rollbackRetainUntil"] = (fixture["now"] + timedelta(days=1)).isoformat()
    fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    report = _report(fixture)

    assert report["status"] == "INELIGIBLE"
    assert not any(row["cleanupEligible"] for row in report["candidates"])


def test_cleanup_eligibility_requires_complete_operating_cycle(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    evidence = json.loads(fixture["operating_cycle"].read_text(encoding="utf-8"))
    evidence["checks"]["learningFanoutObserved"] = False
    fixture["operating_cycle"].write_text(json.dumps(evidence), encoding="utf-8")

    report = _report(fixture)

    assert report["status"] == "INELIGIBLE"
    check = next(row for row in report["checks"] if row["name"] == "operating-cycle")
    assert check["status"] == "FAIL"


def test_cleanup_eligibility_rejects_incomplete_migration_manifest(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["databases"] = manifest["databases"][:-1]
    fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    report = _report(fixture)

    assert report["status"] == "INELIGIBLE"
    check = next(
        row for row in report["checks"] if row["name"] == "migration-manifest-safety"
    )
    assert check["status"] == "FAIL"


def test_cleanup_eligibility_rejects_active_old_path_reference(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    old_path = fixture["sources"]["campaign_factory"]
    (fixture["active_config"] / "runtime.env").write_text(
        f"CAMPAIGN_FACTORY_DB={old_path}\n", encoding="utf-8"
    )

    report = _report(fixture)

    assert report["status"] == "INELIGIBLE"
    check = next(
        row for row in report["checks"] if row["name"] == "active-old-path-references"
    )
    assert check["status"] == "FAIL"
    assert check["references"][0]["oldPath"] == str(old_path)


def test_cleanup_eligibility_fails_closed_when_config_root_is_missing(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    report = _report(fixture, active_config_roots=[tmp_path / "missing-active-config"])

    assert report["status"] == "INELIGIBLE"
    check = next(
        row for row in report["checks"] if row["name"] == "active-old-path-references"
    )
    assert check["scanErrors"]


def test_cleanup_eligibility_requires_private_canonical_and_backup_modes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture["paths"].reference_factory_db.chmod(0o644)
    backup_db = fixture["backup"] / "databases/reference.sqlite"
    backup_db.chmod(0o644)

    report = _report(fixture)

    assert report["status"] == "INELIGIBLE"
    failed = {row["name"] for row in report["checks"] if row["status"] == "FAIL"}
    assert {"canonical-databases", "fresh-backup-restore"} <= failed


def test_cleanup_eligibility_requires_fresh_backup(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    backup_manifest = fixture["backup"] / "backup-manifest.json"
    body = json.loads(backup_manifest.read_text(encoding="utf-8"))
    body["createdAt"] = (fixture["now"] - timedelta(hours=25)).isoformat()
    backup_manifest.write_text(json.dumps(body), encoding="utf-8")

    report = _report(fixture)

    assert report["status"] == "INELIGIBLE"
    check = next(
        row for row in report["checks"] if row["name"] == "fresh-backup-restore"
    )
    assert check["status"] == "FAIL"


def test_cleanup_eligibility_script_has_no_deletion_primitives() -> None:
    script = (ROOT / "scripts/runtime_state_cleanup_eligibility.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(script)
    forbidden_attributes = {"unlink", "rmtree", "remove", "removedirs", "rmdir"}

    assert not any(
        isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
        for node in ast.walk(tree)
    )
    assert "--apply" not in script
    assert "--delete" not in script
