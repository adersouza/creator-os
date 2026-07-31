from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from creator_os_core.configuration_registry import configuration_manifest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_runtime_state.py"
SPEC = importlib.util.spec_from_file_location("backup_runtime_state", SCRIPT)
assert SPEC and SPEC.loader
backup_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_module)
backup_runtime_state = backup_module.backup_runtime_state
audit_backup_script_coverage = backup_module.audit_backup_script_coverage
verify_backup = backup_module.verify_backup
restore_runtime_state = backup_module.restore_runtime_state


def _sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (name) VALUES ('ok')")


def _runtime_env(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "CREATOR_OS_STATE_ROOT": str(tmp_path / "state"),
        "CREATOR_OS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
        "CREATOR_OS_MODEL_ROOT": str(tmp_path / "models"),
        "CREATOR_OS_LOG_ROOT": str(tmp_path / "logs"),
    }


def test_backup_coverage_audit_detects_partial_canonical_root_selection(
    tmp_path: Path,
) -> None:
    script = tmp_path / "backup.sh"
    script.write_text(
        """#!/bin/bash
STATE_ROOT="${CREATOR_OS_STATE_ROOT:-$HOME/.creator-os/state}"
ARTIFACT_ROOT="${CREATOR_OS_ARTIFACT_ROOT:-$HOME/.creator-os/artifacts}"
MODEL_ROOT="${CREATOR_OS_MODEL_ROOT:-$HOME/.creator-os/models}"
LOG_ROOT="${CREATOR_OS_LOG_ROOT:-$HOME/.creator-os/logs}"
sqlite3 "$STATE_ROOT/reel_factory/manifest.sqlite" ".backup out.sqlite"
rsync -a "$ARTIFACT_ROOT/media/runtime_campaigns/" out/
rsync -a "$MODEL_ROOT/reel_factory/" out/
rsync -a "$LOG_ROOT/" out/
""",
        encoding="utf-8",
    )

    result = audit_backup_script_coverage(script, env=_runtime_env(tmp_path))

    assert result["status"] == "drift_detected"
    assert result["canonicalToolDelegation"] is False
    assert set(result["missingCoverage"]) == {
        "campaign_factory_db",
        "reference_factory_db",
        "reel_render_queue_db",
        "artifact_root",
        "model_root",
    }
    assert result["coverage"][-1]["covered"] is True


def test_backup_coverage_audit_accepts_reviewed_canonical_backup_tool(
    tmp_path: Path,
) -> None:
    script = tmp_path / "backup.sh"
    script.write_text(
        '#!/bin/bash\npython3 "/reviewed/scripts/backup_runtime_state.py"\n',
        encoding="utf-8",
    )

    result = audit_backup_script_coverage(script, env=_runtime_env(tmp_path))

    assert result["status"] == "ok"
    assert result["canonicalToolDelegation"] is True
    assert result["missingCoverage"] == []
    assert all(item["covered"] for item in result["coverage"])


def test_backup_coverage_audit_does_not_treat_copying_tool_as_delegation(
    tmp_path: Path,
) -> None:
    script = tmp_path / "backup.sh"
    script.write_text(
        'cp "/reviewed/scripts/backup_runtime_state.py" "/tmp/evidence/"\n',
        encoding="utf-8",
    )

    result = audit_backup_script_coverage(script, env=_runtime_env(tmp_path))

    assert result["canonicalToolDelegation"] is False
    assert result["status"] == "drift_detected"


def test_backup_runtime_state_vacuums_dbs_and_copies_runtime_dirs(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    _sqlite_db(repo / "python_packages/reel_factory/render_queue.sqlite")
    _sqlite_db(repo / "python_packages/campaign_factory/campaign_factory.sqlite")
    _sqlite_db(repo / "python_packages/reference_factory/reference_factory.sqlite")
    audio = repo / "python_packages/reel_factory/03_audio_library"
    audio.mkdir(parents=True)
    (audio / "track.json").write_text("{}", encoding="utf-8")
    (audio / "historical.mp4").symlink_to(repo / "removed-source.mp4")

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
    assert oct(backup_root.stat().st_mode & 0o777) == "0o700"
    assert oct((backup_root / "backup-manifest.json").stat().st_mode & 0o777) == (
        "0o600"
    )
    for relative_path in backed_up.values():
        assert oct((backup_root / relative_path).stat().st_mode & 0o777) == "0o600"
    with sqlite3.connect(backup_root / backed_up["reel_manifest"]) as conn:
        assert conn.execute("SELECT name FROM items").fetchone()[0] == "ok"
    assert (
        tmp_path
        / "backups/test/python_packages/reel_factory/03_audio_library/track.json"
    ).exists()
    historical = (
        tmp_path
        / "backups/test/python_packages/reel_factory/03_audio_library/historical.mp4"
    )
    assert historical.is_symlink()
    assert historical.readlink() == repo / "removed-source.mp4"
    verification = verify_backup(backup_root)
    assert verification["status"] == "ok"
    assert {row["name"] for row in verification["databases"]} == set(backed_up)
    assert {row["mode"] for row in verification["databases"]} == {"0o600"}


def test_backup_runtime_state_never_copies_creator_os_credentials(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    project_data = repo / "python_packages/reel_factory/project_data"
    project_data.mkdir(parents=True)
    (project_data / "secrets.toml").write_text(
        'api_key = "never-copy-project-secret"\n', encoding="utf-8"
    )
    (project_data / "orchestrator.toml").write_text(
        "enabled = false\n", encoding="utf-8"
    )
    credentials = tmp_path / ".creator-os"
    credentials.mkdir()
    (credentials / "campaign-factory-ingest.env").write_text(
        "CAMPAIGN_FACTORY_INGEST_SECRET=never-copy-me\n", encoding="utf-8"
    )

    result = backup_runtime_state(repo, tmp_path / "backups", timestamp="safe")

    backup_root = Path(result["backupDir"])
    assert not any(".creator-os" in str(path) for path in backup_root.rglob("*"))
    assert not (
        backup_root / "python_packages/reel_factory/project_data/secrets.toml"
    ).exists()
    assert (
        backup_root / "python_packages/reel_factory/project_data/orchestrator.toml"
    ).exists()
    assert "never-copy-me" not in "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in backup_root.rglob("*")
        if path.is_file()
    )
    assert "never-copy-project-secret" not in "".join(
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


def test_verify_backup_rejects_public_database_permissions(tmp_path: Path):
    repo = tmp_path / "repo"
    _sqlite_db(repo / "python_packages/reel_factory/manifest.sqlite")
    result = backup_runtime_state(repo, tmp_path / "backups", timestamp="mode")
    backup_root = Path(result["backupDir"])
    (backup_root / "databases/manifest.sqlite").chmod(0o644)

    try:
        verify_backup(backup_root)
    except RuntimeError as exc:
        assert "reel_manifest" in str(exc)
    else:
        raise AssertionError("public backup permissions must fail verification")


def _complete_backup(
    tmp_path: Path,
    *,
    created_at: datetime | None = None,
    include_models: bool = True,
) -> dict[str, Any]:
    runtime = tmp_path / "lost-machine"
    campaign_db = runtime / "state/campaign.sqlite"
    reference_db = runtime / "state/reference.sqlite"
    _sqlite_db(campaign_db)
    _sqlite_db(reference_db)
    artifacts = runtime / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "receipt.json").write_text(
        '{"schema":"receipt.v1","createdAt":"2026-07-29T00:00:00Z"}',
        encoding="utf-8",
    )
    models = runtime / "models"
    if include_models:
        models.mkdir()
        (models / "detector.bin").write_bytes(b"qualified-model")
    return backup_runtime_state(
        runtime,
        tmp_path / "backups",
        timestamp=f"backup-{len(list((tmp_path / 'backups').glob('*'))) if (tmp_path / 'backups').exists() else 0}",
        created_at=created_at,
        database_sources=(
            ("campaign_factory", campaign_db, Path("campaign.sqlite")),
            ("reference_factory", reference_db, Path("reference.sqlite")),
        ),
        directory_sources=(
            ("artifacts", artifacts, Path("artifacts")),
            ("models", models, Path("models")),
        ),
        required_databases=("campaign_factory", "reference_factory"),
        required_directories=("artifacts", "models"),
        config_evidence=configuration_manifest(
            values={
                "OPENAI_API_KEY": "never-copy-provider-secret",
                "CREATOR_OS_STATE_ROOT": str(runtime / "state"),
            }
        ),
        rpo_seconds=3600,
        rto_seconds=60,
    )


def test_complete_machine_loss_restore_uses_new_root_and_path_rebinding(
    tmp_path: Path,
) -> None:
    result = _complete_backup(tmp_path)
    backup_root = Path(result["backupDir"])
    new_mac_root = tmp_path / "new-mac" / "creator-os-restored"

    receipt = restore_runtime_state(
        backup_root,
        new_mac_root,
        operator="restore-operator",
        authorized=True,
        path_rebindings={
            "campaign_factory": "databases/campaign.sqlite",
            "reference_factory": "databases/reference.sqlite",
            "artifacts": "retained/artifacts",
            "models": "retained/models",
        },
    )

    assert receipt["isolatedRestore"] is True
    assert receipt["canonicalStateOverwritten"] is False
    assert receipt["rpoMet"] is True
    assert receipt["rtoMet"] is True
    assert receipt["postRestoreReconciliation"]["required"] is True
    assert (new_mac_root / "retained/models/detector.bin").read_bytes() == (
        b"qualified-model"
    )
    with sqlite3.connect(new_mac_root / "databases/campaign.sqlite") as conn:
        assert conn.execute("SELECT name FROM items").fetchone()[0] == "ok"
    restore_receipt = json.loads(
        (new_mac_root / "restore-receipt.json").read_text(encoding="utf-8")
    )
    assert restore_receipt["backupManifestFingerprint"] == result["manifestFingerprint"]
    assert "never-copy-provider-secret" not in json.dumps(result)
    assert "never-copy-provider-secret" not in json.dumps(restore_receipt)


def test_schema_upgrade_runs_only_on_isolated_restored_database(
    tmp_path: Path,
) -> None:
    result = _complete_backup(tmp_path)
    backup_db = Path(result["backupDir"]) / "databases/campaign.sqlite"
    before_sha = backup_module.sha256_file(backup_db)

    def upgrade(path: Path) -> None:
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE schema_receipts (version INTEGER NOT NULL PRIMARY KEY)"
            )
            conn.execute("INSERT INTO schema_receipts VALUES (2)")

    destination = tmp_path / "schema-upgraded"
    receipt = restore_runtime_state(
        Path(result["backupDir"]),
        destination,
        operator="migration-operator",
        authorized=True,
        database_upgraders={"campaign_factory": upgrade},
    )

    assert receipt["schemaUpgradeApplied"] is True
    campaign = next(
        row for row in receipt["databases"] if row["name"] == "campaign_factory"
    )
    assert campaign["schemaUpgraded"] is True
    with sqlite3.connect(
        destination / "state/campaign_factory/campaign_factory.sqlite"
    ) as conn:
        assert conn.execute("SELECT version FROM schema_receipts").fetchone()[0] == 2
    assert backup_module.sha256_file(backup_db) == before_sha


def test_partial_backup_and_missing_model_bytes_fail_before_restore(
    tmp_path: Path,
) -> None:
    result = _complete_backup(tmp_path, include_models=False)
    backup_root = Path(result["backupDir"])
    assert result["status"] == "partial"
    verification = verify_backup(backup_root)
    assert verification["status"] == "partial"
    assert verification["missingRequired"] == ["directories:models"]
    assert any(
        warning["code"] == "backup_partial" for warning in verification["warnings"]
    )

    destination = tmp_path / "must-not-exist"
    with pytest.raises(RuntimeError, match="required components missing"):
        restore_runtime_state(
            backup_root,
            destination,
            operator="restore-operator",
            authorized=True,
        )
    assert not destination.exists()


def test_stale_backup_requires_override_and_reports_rpo_truthfully(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    result = _complete_backup(tmp_path, created_at=now - timedelta(hours=2))
    backup_root = Path(result["backupDir"])
    destination = tmp_path / "stale-restore"

    with pytest.raises(RuntimeError, match="stale_backup"):
        restore_runtime_state(
            backup_root,
            destination,
            operator="restore-operator",
            authorized=True,
            now=now,
        )
    assert not destination.exists()

    receipt = restore_runtime_state(
        backup_root,
        destination,
        operator="restore-operator",
        authorized=True,
        now=now,
        allow_stale=True,
    )
    assert receipt["staleBackupAccepted"] is True
    assert receipt["rpoMet"] is False


def test_missing_configuration_and_secret_material_block_selected_operation(
    tmp_path: Path,
) -> None:
    result = _complete_backup(tmp_path)
    destination = tmp_path / "config-blocked"
    with pytest.raises(PermissionError) as error:
        restore_runtime_state(
            Path(result["backupDir"]),
            destination,
            operator="restore-operator",
            authorized=True,
            required_operation="paid_openai",
            target_configuration={
                "CREATOR_OS_ENVIRONMENT": "production",
                "CREATOR_OS_KILL_SWITCH": "0",
            },
        )
    message = str(error.value)
    assert "CREATOR_OS_SPEND_AUTH_SECRET" in message
    assert "OPENAI_API_KEY" in message
    assert "secret" not in message.lower().replace("creator_os_spend_auth_secret", "")
    assert not destination.exists()


def test_newer_receipts_block_stale_state_replacement(tmp_path: Path) -> None:
    created = datetime(2026, 7, 30, 12, tzinfo=UTC)
    result = _complete_backup(tmp_path, created_at=created)
    newer = tmp_path / "canonical-newer-receipt.json"
    newer.write_text(
        json.dumps({"createdAt": (created + timedelta(minutes=5)).isoformat()}),
        encoding="utf-8",
    )
    destination = tmp_path / "blocked-by-newer-receipt"

    with pytest.raises(RuntimeError, match="newer_canonical_receipts"):
        restore_runtime_state(
            Path(result["backupDir"]),
            destination,
            operator="restore-operator",
            authorized=True,
            now=created + timedelta(minutes=10),
            canonical_receipts=(newer,),
        )
    assert not destination.exists()

    reconciled_destination = tmp_path / "isolated-newer-receipt-reconciliation"
    receipt = restore_runtime_state(
        Path(result["backupDir"]),
        reconciled_destination,
        operator="restore-operator",
        authorized=True,
        now=created + timedelta(minutes=10),
        canonical_receipts=(newer,),
        allow_newer_receipts=True,
    )
    assert receipt["canonicalStateOverwritten"] is False
    assert receipt["newerReceiptsRequireReconciliation"] is True
    assert receipt["newerCanonicalReceipts"] == [
        {
            "path": str(newer.resolve()),
            "createdAt": (created + timedelta(minutes=5)).isoformat(),
        }
    ]


def test_restore_never_blindly_overwrites_even_an_empty_destination(
    tmp_path: Path,
) -> None:
    result = _complete_backup(tmp_path)
    destination = tmp_path / "existing-canonical-state"
    destination.mkdir()
    marker = destination / "newer.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        restore_runtime_state(
            Path(result["backupDir"]),
            destination,
            operator="restore-operator",
            authorized=True,
        )
    assert marker.read_text(encoding="utf-8") == "keep"


def test_verify_backup_rejects_tampered_runtime_directory(tmp_path: Path) -> None:
    result = _complete_backup(tmp_path)
    backup_root = Path(result["backupDir"])
    (backup_root / "models/detector.bin").write_bytes(b"tampered-model")
    with pytest.raises(RuntimeError, match="models"):
        verify_backup(backup_root)


def test_failed_backup_is_not_published_as_a_restorable_snapshot(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    corrupt = runtime / "broken.sqlite"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(sqlite3.DatabaseError):
        backup_runtime_state(
            runtime,
            tmp_path / "backups",
            timestamp="failed",
            database_sources=(("broken", corrupt, Path("broken.sqlite")),),
            required_databases=("broken",),
        )
    assert not (tmp_path / "backups/failed").exists()
    assert not list((tmp_path / "backups").glob(".failed.*.tmp"))
