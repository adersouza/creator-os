"""Read-only byte reconciliation and explicit, backed-up repair actions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import connect_sqlite

from .artifact_storage import (
    atomic_copy,
    is_regular_file,
    managed_roots,
    root_keyed_path,
    sha256_file,
)

MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
}
TEMP_SUFFIXES = {".tmp", ".part", ".partial"}
STATE_FILE_SUFFIXES = {
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
}
REPAIRABLE_FILE_FINDINGS = {
    "abandoned_temp_file",
    "file_without_database_row",
    "provider_output_retained_not_registered",
}


def reconciliation_report(
    conn: sqlite3.Connection,
    settings: Any,
    *,
    now: datetime | None = None,
    temp_ttl_hours: int = 24,
) -> dict[str, Any]:
    observed_at = now or datetime.now(UTC)
    roots = managed_roots(settings)
    findings: list[dict[str, Any]] = []
    known_paths: dict[Path, list[dict[str, Any]]] = {}
    rendered = _rows(conn, "rendered_assets")
    quarantined_rendered = {
        str(row["rendered_asset_id"])
        for row in _rows(conn, "quarantined_assets")
        if row.get("rendered_asset_id")
    }
    active_rendered = [
        row
        for row in rendered
        if str(row["id"]) not in quarantined_rendered and not _is_operator_removed(row)
    ]
    active_rendered_ids = {str(row["id"]) for row in active_rendered}
    rendered_by_id = {str(row["id"]): row for row in rendered}

    for row in _rows(conn, "source_assets"):
        path = Path(str(row.get("stored_path") or "")).expanduser()
        lifecycle = _source_lifecycle(conn, str(row["id"]))
        if lifecycle and lifecycle.get("lifecycle_state") in {
            "quarantined",
            "rejected",
            "superseded",
            "archived",
            "deleted",
        }:
            _remember_registered_path(
                known_paths,
                path,
                expected_sha=str(row.get("content_hash") or ""),
                subject_type="source_asset",
                subject_id=str(row["id"]),
            )
            continue
        external = bool(
            lifecycle and lifecycle.get("storage_policy") == "external_reference"
        )
        _check_registered_path(
            findings,
            known_paths,
            path=path,
            expected_sha=str(row.get("content_hash") or ""),
            subject_type="source_asset",
            subject_id=str(row["id"]),
            external=external,
            roots=roots,
        )
        if lifecycle is None:
            _add(
                findings,
                "source_lifecycle_missing",
                "source_asset",
                str(row["id"]),
                {"path": str(path), "repair": "run_source_lifecycle_backfill"},
            )
        elif (
            external
            and lifecycle.get("backup_state") != "managed"
            and root_keyed_path(path, roots) is None
        ):
            _add(
                findings,
                "external_reference_outside_backup_coverage",
                "source_asset",
                str(row["id"]),
                {
                    "path": str(path),
                    "backupState": lifecycle.get("backup_state"),
                },
            )

    for row in active_rendered:
        path = Path(str(row.get("output_path") or "")).expanduser()
        _check_registered_path(
            findings,
            known_paths,
            path=path,
            expected_sha=str(row.get("content_hash") or ""),
            subject_type="rendered_asset",
            subject_id=str(row["id"]),
            external=False,
            roots=roots,
        )
    for row in rendered:
        if str(row["id"]) not in active_rendered_ids:
            _remember_registered_path(
                known_paths,
                Path(str(row.get("output_path") or "")).expanduser(),
                expected_sha="",
                subject_type="rendered_asset",
                subject_id=str(row["id"]),
            )

    _collect_generation_attempt_paths(
        conn,
        known_paths,
        ignored_rendered_ids=set(rendered_by_id) - active_rendered_ids,
    )
    _collect_other_database_paths(settings, findings, known_paths, roots)
    _check_receipt_paths(conn, findings, known_paths, roots)
    _check_path_identity_conflicts(findings, known_paths)
    _check_stale_evidence(
        conn,
        findings,
        rendered_by_id,
        ignored_asset_ids=set(rendered_by_id) - active_rendered_ids,
    )
    _check_reservations(conn, findings)
    _check_final_evidence(conn, findings, active_rendered)
    _scan_managed_files(
        findings,
        known_paths,
        roots,
        older_than=observed_at - timedelta(hours=max(1, temp_ttl_hours)),
    )
    findings.sort(key=lambda item: (item["findingClass"], item["caseId"]))
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["findingClass"]] = counts.get(finding["findingClass"], 0) + 1
    return {
        "schema": "creator_os.artifact_reconciliation_report.v1",
        "mode": "read_only",
        "observedAt": observed_at.isoformat(),
        "database": str(getattr(settings, "db_path", "")),
        "managedRoots": {key: str(value) for key, value in roots.items()},
        "findingCount": len(findings),
        "counts": counts,
        "findings": findings,
    }


def summarize_reconciliation_report(
    report: dict[str, Any], *, examples_per_class: int = 3
) -> dict[str, Any]:
    """Return a bounded, deterministic operator view of a full report."""

    if examples_per_class < 0 or examples_per_class > 20:
        raise ValueError("examples_per_class must be between 0 and 20")
    findings = sorted(
        report.get("findings") or [],
        key=lambda item: (str(item["findingClass"]), str(item["caseId"])),
    )
    repair_actions: dict[str, int] = {}
    examples: dict[str, list[dict[str, Any]]] = {}
    repairable = 0
    for finding in findings:
        finding_class = str(finding["findingClass"])
        if finding.get("repairSupported"):
            repairable += 1
            action = str(finding.get("repairAction") or "unspecified")
            repair_actions[action] = repair_actions.get(action, 0) + 1
        selected = examples.setdefault(finding_class, [])
        if len(selected) < examples_per_class:
            selected.append(
                {
                    "caseId": finding["caseId"],
                    "fingerprint": finding["fingerprint"],
                    "subjectType": finding["subjectType"],
                    "subjectId": finding["subjectId"],
                    "repairSupported": bool(finding.get("repairSupported")),
                    "repairAction": finding.get("repairAction"),
                    "evidence": finding.get("evidence") or {},
                }
            )
    return {
        "schema": "creator_os.artifact_reconciliation_summary.v1",
        "mode": "read_only",
        "observedAt": report.get("observedAt"),
        "database": report.get("database"),
        "managedRoots": report.get("managedRoots") or {},
        "findingCount": len(findings),
        "repairableFindingCount": repairable,
        "manualReviewFindingCount": len(findings) - repairable,
        "counts": {
            key: int(value)
            for key, value in sorted((report.get("counts") or {}).items())
        },
        "repairActions": dict(sorted(repair_actions.items())),
        "examplesPerClass": examples_per_class,
        "examples": {key: examples[key] for key in sorted(examples)},
        "fullReportOmitted": True,
        "repairGuard": (
            "Preview one case, then apply with its exact case ID and fingerprint; "
            "missing bytes are quarantined in state and are never reconstructed."
        ),
    }


def repair_reconciliation_case(
    conn: sqlite3.Connection,
    settings: Any,
    *,
    case_id: str,
    operator: str,
    reason: str,
    apply: bool,
    expected_fingerprint: str | None = None,
) -> dict[str, Any]:
    if not operator.strip() or not reason.strip():
        raise ValueError("operator and reason are required")
    if apply and not expected_fingerprint:
        raise ValueError("case fingerprint is required when applying a repair")
    prior_by_case = (
        conn.execute(
            "SELECT * FROM artifact_reconciliation_repairs WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if _rows_table_exists(conn, "artifact_reconciliation_repairs")
        else None
    )
    if prior_by_case:
        if (
            expected_fingerprint
            and str(prior_by_case["case_fingerprint"]) != expected_fingerprint
        ):
            raise ValueError("case fingerprint does not match the repair receipt")
        return {
            "schema": "creator_os.artifact_reconciliation_repair_plan.v1",
            "caseId": case_id,
            "caseFingerprint": str(prior_by_case["case_fingerprint"]),
            "action": prior_by_case["action"],
            "operator": operator.strip(),
            "reason": reason.strip(),
            "applied": True,
            "changed": False,
            "idempotentReplay": True,
            "repairReceiptId": prior_by_case["id"],
        }
    report = reconciliation_report(conn, settings)
    matches = [item for item in report["findings"] if item["caseId"] == case_id]
    if len(matches) != 1:
        raise ValueError("case must resolve to exactly one current finding")
    finding = matches[0]
    if expected_fingerprint and finding["fingerprint"] != expected_fingerprint:
        raise ValueError("case fingerprint no longer matches the current finding")
    if not finding["repairSupported"]:
        raise ValueError(f"repair is not supported for {finding['findingClass']}")
    plan = {
        "schema": "creator_os.artifact_reconciliation_repair_plan.v1",
        "case": finding,
        "caseFingerprint": finding["fingerprint"],
        "action": finding["repairAction"],
        "operator": operator.strip(),
        "reason": reason.strip(),
        "applied": False,
    }
    if not apply:
        return plan

    prior = conn.execute(
        """
        SELECT * FROM artifact_reconciliation_repairs
        WHERE case_id = ? AND case_fingerprint = ? AND action = ?
        """,
        (case_id, finding["fingerprint"], finding["repairAction"]),
    ).fetchone()
    if prior:
        return {
            **plan,
            "applied": True,
            "changed": False,
            "idempotentReplay": True,
            "repairReceiptId": prior["id"],
        }

    backup_dir = (
        Path(settings.campaigns_dir).expanduser().resolve()
        / "_reconciliation"
        / case_id
    )
    backup_dir.mkdir(parents=True, exist_ok=True)
    database_backup = backup_dir / "campaign_factory.before.sqlite"
    _backup_database(conn, database_backup)
    database_backup_sha = sha256_file(database_backup)
    subject_path = _finding_path(finding)
    file_backup: Path | None = None
    file_backup_sha: str | None = None
    if subject_path and is_regular_file(subject_path):
        file_backup = backup_dir / f"subject{subject_path.suffix}"
        file_backup_sha = sha256_file(subject_path)
        atomic_copy(
            subject_path,
            file_backup,
            expected_sha256=file_backup_sha,
            storage_root=Path(settings.campaigns_dir),
        )

    moved_from: Path | None = None
    moved_to: Path | None = None
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        result: dict[str, Any]
        if finding["findingClass"] in REPAIRABLE_FILE_FINDINGS:
            if subject_path is None or file_backup_sha is None:
                raise ValueError("repair subject file is no longer present")
            quarantine = (
                Path(settings.campaigns_dir).expanduser().resolve()
                / "_reconciliation"
                / "quarantine"
                / f"{case_id}{subject_path.suffix}"
            )
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            if quarantine.exists() and sha256_file(quarantine) != file_backup_sha:
                raise FileExistsError("reconciliation quarantine collision")
            if not quarantine.exists():
                os.replace(subject_path, quarantine)
                moved_from, moved_to = subject_path, quarantine
            result = {
                "disposition": "moved_to_quarantine",
                "originalPath": str(subject_path),
                "quarantinePath": str(quarantine),
                "sha256": file_backup_sha,
            }
        elif finding["findingClass"] == "database_row_with_missing_file":
            result = _quarantine_missing_source(conn, finding, now, operator, reason)
        elif finding["findingClass"] in {
            "approval_against_stale_bytes",
            "audit_against_stale_bytes",
            "registered_asset_without_final_evidence",
        }:
            result = _quarantine_rendered_asset(conn, finding, now, operator, reason)
        elif finding["findingClass"] == "reservation_against_missing_asset":
            result = _cancel_broken_reservation(conn, finding, now)
        else:
            raise ValueError(f"unsupported repair action: {finding['findingClass']}")

        repair_id = (
            "reconcile_repair_"
            + hashlib.sha256(
                f"{case_id}:{finding['fingerprint']}:{finding['repairAction']}".encode()
            ).hexdigest()[:20]
        )
        conn.execute(
            """
            INSERT INTO artifact_reconciliation_repairs
            (id, case_id, case_fingerprint, finding_class, action, operator,
             reason, database_backup_path, database_backup_sha256,
             file_backup_path, file_backup_sha256, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repair_id,
                case_id,
                finding["fingerprint"],
                finding["findingClass"],
                finding["repairAction"],
                operator.strip(),
                reason.strip(),
                str(database_backup),
                database_backup_sha,
                str(file_backup) if file_backup else None,
                file_backup_sha,
                json.dumps(result, sort_keys=True),
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        if moved_from and moved_to and moved_to.exists() and not moved_from.exists():
            os.replace(moved_to, moved_from)
        raise
    return {
        **plan,
        "applied": True,
        "changed": True,
        "repairReceiptId": repair_id,
        "databaseBackup": {
            "path": str(database_backup),
            "sha256": database_backup_sha,
        },
        "fileBackup": (
            {"path": str(file_backup), "sha256": file_backup_sha}
            if file_backup
            else None
        ),
        "result": result,
    }


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return []
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]


def _source_lifecycle(
    conn: sqlite3.Connection, source_asset_id: str
) -> dict[str, Any] | None:
    if not _rows_table_exists(conn, "source_asset_lifecycle"):
        return None
    row = conn.execute(
        "SELECT * FROM source_asset_lifecycle WHERE source_asset_id = ?",
        (source_asset_id,),
    ).fetchone()
    return dict(row) if row else None


def _rows_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _check_registered_path(
    findings: list[dict[str, Any]],
    known: dict[Path, list[dict[str, Any]]],
    *,
    path: Path,
    expected_sha: str,
    subject_type: str,
    subject_id: str,
    external: bool,
    roots: dict[str, Path],
) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    _remember_registered_path(
        known,
        absolute,
        expected_sha=expected_sha,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    _check_registered_path_bytes(
        findings,
        absolute=absolute,
        expected_sha=expected_sha,
        subject_type=subject_type,
        subject_id=subject_id,
        external=external,
        roots=roots,
    )


def _remember_registered_path(
    known: dict[Path, list[dict[str, Any]]],
    path: Path,
    *,
    expected_sha: str,
    subject_type: str,
    subject_id: str,
) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    known.setdefault(absolute, []).append(
        {
            "subjectType": subject_type,
            "subjectId": subject_id,
            "expectedSha256": expected_sha,
        }
    )


def _collect_generation_attempt_paths(
    conn: sqlite3.Connection,
    known: dict[Path, list[dict[str, Any]]],
    *,
    ignored_rendered_ids: set[str],
) -> None:
    blobs = {
        str(row["id"]): str(row.get("content_sha256") or "")
        for row in _rows(conn, "generation_output_blobs")
    }
    for row in _rows(conn, "generation_attempts"):
        path = Path(str(row.get("attempted_output_path") or "")).expanduser()
        if not str(path).strip():
            continue
        _remember_registered_path(
            known,
            path,
            expected_sha=(
                ""
                if str(row.get("rendered_asset_id") or "") in ignored_rendered_ids
                else blobs.get(str(row.get("output_blob_id") or ""), "")
            ),
            subject_type="generation_attempt",
            subject_id=str(row["id"]),
        )


def _is_operator_removed(row: dict[str, Any]) -> bool:
    try:
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
    except (TypeError, ValueError):
        return False
    return str(metadata.get("lifecycleStatus") or "").lower() == "operator_removed"


def _check_registered_path_bytes(
    findings: list[dict[str, Any]],
    *,
    absolute: Path,
    expected_sha: str,
    subject_type: str,
    subject_id: str,
    external: bool,
    roots: dict[str, Path],
) -> None:
    if not absolute.is_absolute() or not is_regular_file(absolute):
        _add(
            findings,
            "database_row_with_missing_file",
            subject_type,
            subject_id,
            {"path": str(absolute), "expectedSha256": expected_sha},
            repair_supported=subject_type == "source_asset",
            repair_action="quarantine_missing_source"
            if subject_type == "source_asset"
            else None,
        )
        return
    actual_sha = sha256_file(absolute)
    if expected_sha and actual_sha != expected_sha:
        _add(
            findings,
            "path_containing_different_bytes_than_recorded",
            subject_type,
            subject_id,
            {
                "path": str(absolute),
                "expectedSha256": expected_sha,
                "actualSha256": actual_sha,
            },
        )
    if root_keyed_path(absolute, roots) is None and not external:
        _add(
            findings,
            "absolute_path_outside_managed_roots",
            subject_type,
            subject_id,
            {"path": str(absolute), "sha256": actual_sha},
        )


def _check_receipt_paths(
    conn: sqlite3.Connection,
    findings: list[dict[str, Any]],
    known: dict[Path, list[dict[str, Any]]],
    roots: dict[str, Path],
) -> None:
    specs = (
        ("audit_reports", "id", "report_path", None, "rendered_asset_id"),
        (
            "motion_qc_receipts",
            "id",
            "receipt_path",
            "receipt_sha256",
            "rendered_asset_id",
        ),
        ("threadsdash_exports", "id", "manifest_path", None, "campaign_id"),
    )
    for table, id_field, path_field, sha_field, subject_field in specs:
        rows = _rows(conn, table)
        managed_audit_copies: set[tuple[str, str]] = set()
        managed_audit_semantics: set[tuple[str, ...]] = set()
        if table == "audit_reports":
            for row in rows:
                candidate = Path(str(row.get(path_field) or "")).expanduser()
                if root_keyed_path(candidate, roots) is not None and is_regular_file(
                    candidate
                ):
                    managed_audit_copies.add(
                        (str(row.get(subject_field) or ""), sha256_file(candidate))
                    )
                    managed_audit_semantics.add(_audit_semantic_key(row))
        for row in rows:
            receipt_id = str(row[id_field])
            subject_id = str(row.get(subject_field) or "")
            if not subject_id:
                _add(
                    findings,
                    "receipt_with_missing_subject",
                    table,
                    receipt_id,
                    {"subjectField": subject_field},
                )
            path = Path(str(row.get(path_field) or "")).expanduser()
            if table == "threadsdash_exports" and str(
                row.get("status") or ""
            ).lower() in {"dry_run", "failed", "rejected", "superseded"}:
                _remember_registered_path(
                    known,
                    path,
                    expected_sha="",
                    subject_type=table,
                    subject_id=receipt_id,
                )
                continue
            if (
                table == "audit_reports"
                and root_keyed_path(path, roots) is None
                and _audit_semantic_key(row) in managed_audit_semantics
            ):
                _remember_registered_path(
                    known,
                    path,
                    expected_sha="",
                    subject_type=table,
                    subject_id=receipt_id,
                )
                continue
            immutable_audit_has_managed_copy = (
                table == "audit_reports"
                and is_regular_file(path)
                and (subject_id, sha256_file(path)) in managed_audit_copies
            )
            _check_registered_path(
                findings,
                known,
                path=path,
                expected_sha=str(row.get(sha_field) or "") if sha_field else "",
                subject_type=table,
                subject_id=receipt_id,
                external=immutable_audit_has_managed_copy,
                roots=roots,
            )


def _audit_semantic_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(field) or "")
        for field in (
            "campaign_id",
            "rendered_asset_id",
            "contentforge_run_id",
            "subject_sha256",
            "score",
            "status",
            "layers_json",
            "verdicts_json",
            "overall_verdict",
            "files_analyzed",
            "failed_checks_json",
            "warnings_json",
        )
    )


def _collect_other_database_paths(
    settings: Any,
    findings: list[dict[str, Any]],
    known: dict[Path, list[dict[str, Any]]],
    roots: dict[str, Path],
) -> None:
    databases = (
        (
            "reference_factory",
            Path(settings.reference_factory_db),
            (
                ("source_files", "reference_id", "path", "content_hash"),
                ("source_files", "reference_id", "intake_receipt_path", None),
                ("reference_anchor_receipts", "id", "receipt_path", None),
                ("frame_samples", "id", "frame_path", None),
                ("contact_sheets", "id", "sheet_path", None),
                ("contact_sheets", "id", "html_path", None),
                ("public_posts", "id", "local_path", None),
                ("audio_catalog", "id", "local_preview_path", None),
            ),
        ),
        (
            "reel_factory",
            Path(settings.reel_manifest_db),
            (
                ("videos", "video_id", "source_path", "source_video_hash"),
                ("variations", "job_key", "output_path", "output_hash"),
                ("render_attempts", "attempt_id", "final_path", None),
                ("prompt_runs", "prompt_run_id", "prompt_json_path", None),
                ("prompt_runs", "prompt_run_id", "lineage_path", None),
                ("asset_generations", "asset_generation_id", "local_image_path", None),
                ("asset_generations", "asset_generation_id", "local_video_path", None),
                ("asset_generations", "asset_generation_id", "lineage_path", None),
                ("campaign_outputs", "campaign_output_id", "output_path", None),
                ("campaign_outputs", "campaign_output_id", "export_path", None),
                (
                    "reference_analysis",
                    "analysis_id",
                    "reference_path",
                    "reference_hash",
                ),
                ("reference_analysis", "analysis_id", "sidecar_path", None),
                ("media_embeddings", "embedding_id", "path", None),
                ("reel_features", "feature_id", "output_path", None),
            ),
        ),
    )
    for database_name, database_path, specs in databases:
        if not database_path.is_file():
            continue
        external = connect_sqlite(database_path, readonly=True, wal=False)
        try:
            tables = {
                str(row["name"])
                for row in external.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            deleted_reference_ids = (
                {
                    str(row["reference_id"])
                    for row in external.execute(
                        "SELECT reference_id FROM reference_lifecycle_state "
                        "WHERE reference_status = 'deleted'"
                    ).fetchall()
                }
                if database_name == "reference_factory"
                and "reference_lifecycle_state" in tables
                else set()
            )
            for table, id_field, path_field, hash_field in specs:
                if table not in tables:
                    continue
                columns = {
                    str(row["name"])
                    for row in external.execute(f"PRAGMA table_info({table})")
                }
                required = {id_field, path_field}
                if hash_field:
                    required.add(hash_field)
                if not required <= columns:
                    continue
                selected = f"{id_field}, {path_field}"
                if hash_field:
                    selected += f", {hash_field}"
                if table == "frame_samples" and "reference_id" in columns:
                    selected += ", reference_id"
                if table == "variations" and "review_state" in columns:
                    selected += ", review_state"
                for raw in external.execute(
                    f"SELECT {selected} FROM {table} WHERE {path_field} IS NOT NULL"
                ):
                    row = dict(raw)
                    if not str(row.get(path_field) or "").strip():
                        continue
                    path = Path(str(row[path_field])).expanduser()
                    expected_sha = str(row.get(hash_field) or "") if hash_field else ""
                    historical_reference = (
                        table == "source_files"
                        and str(row[id_field]) in deleted_reference_ids
                    ) or (
                        table == "frame_samples"
                        and str(row.get("reference_id") or "") in deleted_reference_ids
                    )
                    historical_render = table == "render_attempts" or (
                        table == "variations"
                        and str(row.get("review_state") or "").lower()
                        not in {"approved", "reviewed"}
                    )
                    if historical_reference or historical_render:
                        _remember_registered_path(
                            known,
                            path,
                            expected_sha=expected_sha,
                            subject_type=f"{database_name}.{table}",
                            subject_id=str(row[id_field]),
                        )
                        continue
                    if database_name == "reference_factory" and (
                        table == "public_posts"
                        or (table == "source_files" and not expected_sha)
                    ):
                        _remember_registered_path(
                            known,
                            path,
                            expected_sha=expected_sha,
                            subject_type=f"{database_name}.{table}",
                            subject_id=str(row[id_field]),
                        )
                        continue
                    _check_registered_path(
                        findings,
                        known,
                        path=path,
                        expected_sha=expected_sha,
                        subject_type=f"{database_name}.{table}",
                        subject_id=str(row[id_field]),
                        external=(
                            database_name == "reel_factory"
                            and table == "render_attempts"
                        ),
                        roots=roots,
                    )
        finally:
            external.close()


def _check_path_identity_conflicts(
    findings: list[dict[str, Any]], known: dict[Path, list[dict[str, Any]]]
) -> None:
    for path, claims in known.items():
        hashes = {
            claim["expectedSha256"] for claim in claims if claim["expectedSha256"]
        }
        if len(hashes) > 1:
            _add(
                findings,
                "multiple_files_claiming_conflicting_identity",
                "path",
                str(path),
                {"path": str(path), "claims": claims},
            )


def _check_stale_evidence(
    conn: sqlite3.Connection,
    findings: list[dict[str, Any]],
    rendered_by_id: dict[str, dict[str, Any]],
    *,
    ignored_asset_ids: set[str],
) -> None:
    for table, finding_class in (
        ("approval_decisions", "approval_against_stale_bytes"),
        ("audit_reports", "audit_against_stale_bytes"),
    ):
        for row in _rows(conn, table):
            rendered = rendered_by_id.get(str(row.get("rendered_asset_id") or ""))
            if rendered is None:
                _add(
                    findings,
                    "receipt_with_missing_subject",
                    table,
                    str(row["id"]),
                    {"renderedAssetId": row.get("rendered_asset_id")},
                )
                continue
            if str(rendered["id"]) in ignored_asset_ids:
                continue
            subject_sha = str(row.get("subject_sha256") or "")
            final_sha = str(rendered.get("content_hash") or "")
            if subject_sha and subject_sha != final_sha:
                _add(
                    findings,
                    finding_class,
                    "rendered_asset",
                    str(rendered["id"]),
                    {
                        "evidenceTable": table,
                        "evidenceId": row["id"],
                        "subjectSha256": subject_sha,
                        "finalSha256": final_sha,
                        "campaignId": rendered["campaign_id"],
                    },
                    repair_supported=True,
                    repair_action="quarantine_stale_evidence",
                )


def _check_reservations(
    conn: sqlite3.Connection, findings: list[dict[str, Any]]
) -> None:
    if not _rows_table_exists(conn, "asset_inventory_reservations"):
        return
    rows = conn.execute(
        """
        SELECT r.* FROM asset_inventory_reservations r
        LEFT JOIN rendered_assets a ON a.id = r.asset_id
        WHERE a.id IS NULL AND r.status IN ('pending', 'committed')
        """
    ).fetchall()
    for raw in rows:
        row = dict(raw)
        _add(
            findings,
            "reservation_against_missing_asset",
            "asset_inventory_reservation",
            str(row["id"]),
            {
                "reservationId": row["id"],
                "assetId": row["asset_id"],
                "status": row["status"],
            },
            repair_supported=True,
            repair_action="cancel_broken_reservation",
        )


def _check_final_evidence(
    conn: sqlite3.Connection,
    findings: list[dict[str, Any]],
    rendered: list[dict[str, Any]],
) -> None:
    rendered_by_id = {str(row["id"]): row for row in rendered}
    approved = {
        str(row["rendered_asset_id"])
        for row in _rows(conn, "approval_decisions")
        if str(row.get("decision") or "").lower() == "approved"
        and str(row.get("subject_sha256") or "")
        == str(
            rendered_by_id.get(str(row.get("rendered_asset_id") or ""), {}).get(
                "content_hash"
            )
            or ""
        )
    }
    approved.update(
        str(row["rendered_asset_id"])
        for row in _rows(conn, "existing_media_asset_reviews")
        if str(row.get("verdict") or "").upper() == "WOULD_POST"
        and str(row.get("final_sha256") or "")
        == str(
            rendered_by_id.get(str(row.get("rendered_asset_id") or ""), {}).get(
                "content_hash"
            )
            or ""
        )
    )
    audited = {
        str(row["rendered_asset_id"])
        for row in _rows(conn, "audit_reports")
        if str(row.get("subject_sha256") or "")
        == str(
            rendered_by_id.get(str(row.get("rendered_asset_id") or ""), {}).get(
                "content_hash"
            )
            or ""
        )
        and str(row.get("status") or "").lower()
        in {"approved", "approved_candidate", "needs_review", "pass", "passed"}
        and str(row.get("overall_verdict") or "").lower()
        in {"approved", "pass", "passed", "warn"}
        and _has_no_failed_checks(row.get("failed_checks_json"))
    }
    for row in rendered:
        claims_final = str(row.get("review_state") or "").lower() in {
            "approved",
            "reviewed",
        } or str(row.get("audit_status") or "").lower() in {"passed", "approved"}
        if claims_final and (
            str(row["id"]) not in approved or str(row["id"]) not in audited
        ):
            _add(
                findings,
                "registered_asset_without_final_evidence",
                "rendered_asset",
                str(row["id"]),
                {
                    "campaignId": row["campaign_id"],
                    "hasExactApproval": str(row["id"]) in approved,
                    "hasExactAudit": str(row["id"]) in audited,
                    "reviewState": row.get("review_state"),
                    "auditStatus": row.get("audit_status"),
                },
                repair_supported=True,
                repair_action="quarantine_missing_final_evidence",
            )


def _has_no_failed_checks(value: Any) -> bool:
    try:
        return json.loads(str(value or "[]")) == []
    except (TypeError, ValueError):
        return False


def _scan_managed_files(
    findings: list[dict[str, Any]],
    known: dict[Path, list[dict[str, Any]]],
    roots: dict[str, Path],
    *,
    older_than: datetime,
) -> None:
    scan_roots: list[tuple[str, Path]] = [
        ("campaigns", roots["campaigns"]),
        ("creative_approvals", roots["creative_approvals"]),
        ("reference_factory", roots["reference_factory"]),
    ]
    reel_root = roots["reel_factory"]
    scan_roots.extend(
        (f"reel_factory/{name}", reel_root / name)
        for name in (
            "00_source_videos",
            "01_captions",
            "02_processed",
            "03_audio",
            "04_review",
        )
    )
    visited: set[Path] = set()
    for root_key, scan_root in scan_roots:
        if not scan_root.is_dir():
            continue
        for directory, names, files in os.walk(scan_root, followlinks=False):
            names[:] = [name for name in names if name != "_reconciliation"]
            parent = Path(directory)
            for name in files:
                path = parent / name
                absolute = Path(os.path.abspath(os.fspath(path)))
                if absolute in visited:
                    continue
                visited.add(absolute)
                _check_managed_file(
                    findings,
                    known,
                    path,
                    root_key=root_key,
                    older_than=older_than,
                )


def _check_managed_file(
    findings: list[dict[str, Any]],
    known: dict[Path, list[dict[str, Any]]],
    path: Path,
    *,
    root_key: str,
    older_than: datetime,
) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if path.is_symlink():
        _add(
            findings,
            "symlink_in_managed_root",
            "file",
            str(absolute),
            {"path": str(absolute), "rootKey": root_key},
        )
        return
    if not is_regular_file(path):
        return
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if path.suffix.lower() in TEMP_SUFFIXES and modified < older_than:
        _add(
            findings,
            "abandoned_temp_file",
            "file",
            str(absolute),
            {
                "path": str(absolute),
                "modifiedAt": modified.isoformat(),
                "rootKey": root_key,
            },
            repair_supported=True,
            repair_action="move_temp_to_quarantine",
        )
        return
    if absolute in known:
        return
    lower_name = path.name.lower()
    if lower_name.endswith(tuple(STATE_FILE_SUFFIXES)) or lower_name in {
        ".ds_store",
        "thumbs.db",
    }:
        return
    if _is_declared_support_artifact(path, root_key=root_key):
        return
    media = path.suffix.lower() in MEDIA_SUFFIXES
    finding_class = (
        "provider_output_retained_not_registered"
        if media
        and any(segment in path.parts for segment in ("02_rendered", "04_approved"))
        else "file_without_database_row"
    )
    _add(
        findings,
        finding_class,
        "file",
        str(absolute),
        {
            "path": str(absolute),
            "sha256": sha256_file(path),
            "rootKey": root_key,
        },
        repair_supported=media,
        repair_action="move_orphan_to_quarantine" if media else None,
    )


def _is_declared_support_artifact(path: Path, *, root_key: str) -> bool:
    parts = set(path.parts)
    if root_key == "creative_approvals" or root_key == "reel_factory/01_captions":
        return True
    if root_key == "campaigns":
        if ".audio-cache" in parts:
            return True
        lanes = parts & {
            "01_reel_inputs",
            "02_rendered",
            "03_contentforge_audits",
            "05_threadsdash_exports",
            "06_reports",
        }
        return bool(lanes) and (
            path.suffix.lower() not in MEDIA_SUFFIXES
            or bool(
                lanes
                & {"03_contentforge_audits", "05_threadsdash_exports", "06_reports"}
            )
        )
    if root_key != "reference_factory":
        return False
    reference_lanes = {
        "learning",
        "thumbnails",
        "url_intake",
        "curated",
        "tiktok",
    }
    if parts & reference_lanes or any(
        part.startswith(("import_", "dryrun_")) for part in path.parts
    ):
        return True
    return "frame_samples" in parts and path.suffix.lower() not in MEDIA_SUFFIXES


def _add(
    findings: list[dict[str, Any]],
    finding_class: str,
    subject_type: str,
    subject_id: str,
    evidence: dict[str, Any],
    *,
    repair_supported: bool = False,
    repair_action: str | None = None,
) -> None:
    core = {
        "findingClass": finding_class,
        "subjectType": subject_type,
        "subjectId": subject_id,
        "evidence": evidence,
    }
    fingerprint = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    findings.append(
        {
            **core,
            "caseId": f"reconcile_{fingerprint[:20]}",
            "fingerprint": fingerprint,
            "repairSupported": repair_supported,
            "repairAction": repair_action,
        }
    )


def _finding_path(finding: dict[str, Any]) -> Path | None:
    value = finding.get("evidence", {}).get("path")
    return Path(str(value)).expanduser() if value else None


def _backup_database(conn: sqlite3.Connection, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".sqlite.tmp")
    temporary.unlink(missing_ok=True)
    backup = connect_sqlite(temporary, wal=False)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    os.replace(temporary, destination)


def _quarantine_missing_source(
    conn: sqlite3.Connection,
    finding: dict[str, Any],
    now: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    source_id = finding["subjectId"]
    prior = conn.execute(
        """
        SELECT l.lifecycle_state, l.version, s.status AS source_status
        FROM source_asset_lifecycle l
        JOIN source_assets s ON s.id = l.source_asset_id
        WHERE l.source_asset_id = ?
        """,
        (source_id,),
    ).fetchone()
    if not prior:
        raise ValueError("source lifecycle is missing; backfill before repair")
    lifecycle_cursor = conn.execute(
        """
        UPDATE source_asset_lifecycle
        SET lifecycle_state = 'quarantined',
            quarantine_reason = 'registered_bytes_missing',
            version = version + 1, updated_at = ?
        WHERE source_asset_id = ? AND lifecycle_state = ? AND version = ?
        """,
        (now, source_id, prior["lifecycle_state"], prior["version"]),
    )
    if lifecycle_cursor.rowcount != 1:
        raise RuntimeError("source lifecycle changed during reconciliation")
    source_cursor = conn.execute(
        """
        UPDATE source_assets SET status = 'quarantined', updated_at = ?
        WHERE id = ? AND status = ?
        """,
        (now, source_id, prior["source_status"]),
    )
    if source_cursor.rowcount != 1:
        raise RuntimeError("source status changed during reconciliation")
    event_id = (
        "source_lifecycle_"
        + hashlib.sha256(
            f"{source_id}:registered_bytes_missing:{finding['fingerprint']}".encode()
        ).hexdigest()[:20]
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO source_asset_lifecycle_events
        (id, source_asset_id, previous_state, new_state, reason, actor,
         evidence_json, created_at)
        VALUES (?, ?, ?, 'quarantined', ?, ?, ?, ?)
        """,
        (
            event_id,
            source_id,
            prior["lifecycle_state"],
            reason,
            operator,
            json.dumps(finding, sort_keys=True),
            now,
        ),
    )
    return {
        "sourceAssetId": source_id,
        "lifecycleState": "quarantined",
        "sourceStatus": "quarantined",
    }


def _quarantine_rendered_asset(
    conn: sqlite3.Connection,
    finding: dict[str, Any],
    now: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    asset_id = finding["subjectId"]
    campaign_id = finding["evidence"]["campaignId"]
    quarantine_id = (
        "quarantine_"
        + hashlib.sha256(f"{asset_id}:{finding['fingerprint']}".encode()).hexdigest()[
            :20
        ]
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO quarantined_assets
        (id, campaign_id, rendered_asset_id, reason, root_cause,
         blocking_reason, excluded_from_metrics, metadata_json, created_at,
         created_by)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            quarantine_id,
            campaign_id,
            asset_id,
            reason,
            finding["findingClass"],
            "artifact_reconciliation_required",
            json.dumps(finding, sort_keys=True),
            now,
            operator,
        ),
    )
    return {"renderedAssetId": asset_id, "quarantineId": quarantine_id}


def _cancel_broken_reservation(
    conn: sqlite3.Connection, finding: dict[str, Any], now: str
) -> dict[str, Any]:
    reservation_id = finding["subjectId"]
    conn.execute(
        """
        UPDATE asset_inventory_reservations
        SET status = 'cancelled', updated_at = ?
        WHERE id = ? AND status IN ('pending', 'committed')
        """,
        (now, reservation_id),
    )
    return {"reservationId": reservation_id, "status": "cancelled"}
