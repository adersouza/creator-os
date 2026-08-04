from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from campaign_factory.existing_media import review_existing_asset
from campaign_factory.reconciliation import (
    reconciliation_report,
    repair_reconciliation_case,
    summarize_reconciliation_report,
)
from campaign_test_support import make_factory


def _source(cf, path: Path, *, source_id: str = "source_reconcile") -> str:
    model = cf.domains.models.upsert_model("stacey")
    campaign = cf.domains.models.upsert_campaign("reconcile", "stacey")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    now = "2026-07-30T00:00:00+00:00"
    cf.conn.execute(
        """
        INSERT INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path,
         filename, media_type, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'imported', ?, ?)
        """,
        (
            source_id,
            campaign["id"],
            model["id"],
            digest,
            str(path),
            str(path),
            path.name,
            now,
            now,
        ),
    )
    cf.conn.execute(
        """
        INSERT INTO source_asset_lifecycle
        (source_asset_id, lifecycle_state, storage_policy,
         classification_authority, probe_json, backup_state, updated_at)
        VALUES (?, 'cataloged', 'managed_copy', 'probe', '{}', 'managed', ?)
        """,
        (source_id, now),
    )
    cf.conn.commit()
    return source_id


def test_reconciliation_report_is_read_only_and_finds_byte_drift(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        sources = cf.settings.campaigns_dir / "stacey" / "reconcile" / "00_sources"
        sources.mkdir(parents=True)
        registered = sources / "registered.mp4"
        registered.write_bytes(b"registered")
        _source(cf, registered)
        registered.write_bytes(b"substituted")
        orphan = sources / "orphan.mp4"
        orphan.write_bytes(b"orphan")
        temporary = sources / "crashed.part"
        temporary.write_bytes(b"partial")
        state_db = cf.settings.campaigns_dir / "state.sqlite"
        state_db.write_bytes(b"sqlite-control")
        unknown_receipt = cf.settings.campaigns_dir / "unregistered-receipt.json"
        unknown_receipt.write_text('{"schema":"unknown"}', encoding="utf-8")
        old = datetime.now(UTC) - timedelta(days=2)
        os.utime(temporary, (old.timestamp(), old.timestamp()))
        before = cf.conn.total_changes
        files_before = {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in cf.settings.campaigns_dir.rglob("*")
            if path.is_file()
        }

        report = reconciliation_report(
            cf.conn, cf.settings, now=datetime.now(UTC), temp_ttl_hours=24
        )

        assert report["mode"] == "read_only"
        assert cf.conn.total_changes == before
        assert files_before == {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in cf.settings.campaigns_dir.rglob("*")
            if path.is_file()
        }
        classes = {finding["findingClass"] for finding in report["findings"]}
        assert "path_containing_different_bytes_than_recorded" in classes
        assert "file_without_database_row" in classes
        assert "abandoned_temp_file" in classes
        assert not any(
            finding["evidence"].get("path") == str(state_db)
            for finding in report["findings"]
        )
        receipt_finding = next(
            finding
            for finding in report["findings"]
            if finding["evidence"].get("path") == str(unknown_receipt)
        )
        assert receipt_finding["repairSupported"] is False
        evidence_cache = cf.settings.reference_reels_root / "thumbnails" / "cache.jpg"
        evidence_cache.parent.mkdir(parents=True, exist_ok=True)
        evidence_cache.write_bytes(b"cache")
        rescanned = reconciliation_report(cf.conn, cf.settings)
        assert not any(
            item["evidence"].get("path") == str(evidence_cache)
            for item in rescanned["findings"]
        )
    finally:
        cf.close()


def test_reconciliation_tracks_active_provider_identity_evidence(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey")
        manifest = tmp_path / "provider-profile.json"
        manifest.write_text('{"creatorKey":"stacey"}', encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        evidence = tmp_path / "reviewed-provider-facts.json"
        evidence.write_text('{"reviewedBy":"operator"}', encoding="utf-8")
        evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
        now = "2026-08-03T00:00:00Z"
        cf.conn.execute(
            """
            INSERT INTO creator_identity_profiles
            (id, model_id, provider, provider_identity_id, version, profile_json,
             profile_fingerprint, identity_manifest_path, identity_manifest_sha256,
             canonical_source_asset_id, canonical_evidence_type,
             provider_identity_evidence_path, provider_identity_evidence_sha256,
             status, activated_at, retired_at, operator, created_at)
            VALUES ('identity_provider', ?, 'higgsfield', 'soul-stacey', 1, '{}',
                    ?, ?, ?, NULL, 'provider_identity_attestation', ?, ?,
                    'active', ?, NULL, 'test', ?)
            """,
            (
                model["id"],
                "f" * 64,
                str(manifest),
                manifest_sha,
                str(evidence),
                evidence_sha,
                now,
                now,
            ),
        )
        cf.conn.commit()

        report = reconciliation_report(cf.conn, cf.settings)
        assert any(
            item["findingClass"] == "external_identity_evidence_outside_backup_coverage"
            and item["subjectType"] == "provider_identity_evidence"
            for item in report["findings"]
        )

        evidence.write_text("tampered", encoding="utf-8")
        drifted = reconciliation_report(cf.conn, cf.settings)
        assert any(
            item["findingClass"] == "path_containing_different_bytes_than_recorded"
            and item["subjectType"] == "provider_identity_evidence"
            for item in drifted["findings"]
        )
    finally:
        cf.close()


def test_immutable_audit_path_is_covered_by_exact_managed_copy(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        source_path = cf.settings.campaigns_dir / "stacey" / "reconcile" / "source.mp4"
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(b"source")
        source_id = _source(cf, source_path)
        campaign_id = cf.conn.execute(
            "SELECT campaign_id FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()[0]
        output = source_path.parent / "rendered.mp4"
        output.write_bytes(b"rendered")
        output_sha = hashlib.sha256(output.read_bytes()).hexdigest()
        now = "2026-07-30T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, audit_status, review_state, created_at,
             updated_at)
            VALUES ('rendered_audit_copy', ?, ?, ?, ?, ?, ?, 'pending',
                    'pending', ?, ?)
            """,
            (
                campaign_id,
                source_id,
                output_sha,
                str(output),
                str(output),
                output.name,
                now,
                now,
            ),
        )
        external = tmp_path / "reports" / "audit.json"
        external.parent.mkdir()
        external.write_bytes(b'{"status":"passed"}')
        managed = source_path.parent / "audit-copy.json"
        managed.write_bytes(external.read_bytes())
        for audit_id, report_path in (
            ("audit_original", external),
            ("audit_managed_copy", managed),
        ):
            cf.conn.execute(
                """
                INSERT INTO audit_reports
                (id, campaign_id, rendered_asset_id, subject_sha256, report_path,
                 score, status, overall_verdict, failed_checks_json, created_at)
                VALUES (?, ?, 'rendered_audit_copy', ?, ?, 100, 'passed',
                        'passed', '[]', ?)
                """,
                (audit_id, campaign_id, output_sha, str(report_path), now),
            )
        cf.conn.commit()

        report = reconciliation_report(cf.conn, cf.settings)

        assert not any(
            item["findingClass"] == "absolute_path_outside_managed_roots"
            and item["subjectId"] == "audit_original"
            for item in report["findings"]
        )
        external.unlink()
        missing_original = reconciliation_report(cf.conn, cf.settings)
        assert not any(
            item["findingClass"] == "database_row_with_missing_file"
            and item["subjectId"] == "audit_original"
            for item in missing_original["findings"]
        )
    finally:
        cf.close()


def test_immutable_render_attempt_does_not_require_retained_attempt_bytes(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        external = tmp_path / "historical-render.mp4"
        external.write_bytes(b"rendered")
        manifest = sqlite3.connect(cf.settings.reel_manifest_db)
        manifest.execute(
            """
            CREATE TABLE render_attempts (
                attempt_id TEXT PRIMARY KEY,
                final_path TEXT NOT NULL
            )
            """
        )
        manifest.execute(
            "INSERT INTO render_attempts VALUES ('attempt-1', ?)", (str(external),)
        )
        manifest.commit()
        manifest.close()

        report = reconciliation_report(cf.conn, cf.settings)
        assert not any(
            item["findingClass"] == "absolute_path_outside_managed_roots"
            and item["subjectId"] == "attempt-1"
            for item in report["findings"]
        )

        external.unlink()
        missing = reconciliation_report(cf.conn, cf.settings)
        assert not any(
            item["findingClass"] == "database_row_with_missing_file"
            and item["subjectId"] == "attempt-1"
            for item in missing["findings"]
        )
    finally:
        cf.close()


def test_deleted_reference_does_not_report_intentionally_removed_bytes(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        cf.settings.reference_factory_db.parent.mkdir(parents=True, exist_ok=True)
        reference = sqlite3.connect(cf.settings.reference_factory_db)
        reference.executescript(
            """
            CREATE TABLE source_files (
                reference_id TEXT PRIMARY KEY,
                path TEXT,
                content_hash TEXT,
                intake_receipt_path TEXT
            );
            CREATE TABLE reference_lifecycle_state (
                reference_id TEXT PRIMARY KEY,
                reference_status TEXT NOT NULL
            );
            CREATE TABLE frame_samples (
                id TEXT PRIMARY KEY,
                reference_id TEXT NOT NULL,
                frame_path TEXT NOT NULL
            );
            """
        )
        missing = tmp_path / "removed-reference.mp4"
        reference.execute(
            "INSERT INTO source_files VALUES ('deleted-ref', ?, ?, NULL)",
            (str(missing), hashlib.sha256(b"removed").hexdigest()),
        )
        reference.execute(
            "INSERT INTO source_files VALUES ('active-ref', ?, ?, NULL)",
            (str(missing), hashlib.sha256(b"active").hexdigest()),
        )
        reference.execute(
            "INSERT INTO reference_lifecycle_state VALUES ('deleted-ref', 'deleted')"
        )
        reference.execute(
            "INSERT INTO frame_samples VALUES ('deleted-frame', 'deleted-ref', ?)",
            (str(tmp_path / "removed-frame.jpg"),),
        )
        reference.execute(
            "INSERT INTO frame_samples VALUES ('active-frame', 'active-ref', ?)",
            (str(tmp_path / "active-frame.jpg"),),
        )
        reference.commit()
        reference.close()

        report = reconciliation_report(cf.conn, cf.settings)
        missing_ids = {
            item["subjectId"]
            for item in report["findings"]
            if item["findingClass"] == "database_row_with_missing_file"
        }
        assert "deleted-ref" not in missing_ids
        assert "active-ref" in missing_ids
        assert "deleted-frame" not in missing_ids
        assert "active-frame" in missing_ids
    finally:
        cf.close()


def test_quarantined_asset_no_longer_conflicts_with_active_path(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        directory = cf.settings.campaigns_dir / "stacey" / "reconcile"
        directory.mkdir(parents=True)
        source_path = directory / "source.mp4"
        source_path.write_bytes(b"source")
        source_id = _source(cf, source_path)
        campaign_id = cf.conn.execute(
            "SELECT campaign_id FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()[0]
        shared = directory / "shared.mp4"
        shared.write_bytes(b"active")
        active_sha = hashlib.sha256(shared.read_bytes()).hexdigest()
        stale_sha = hashlib.sha256(b"stale").hexdigest()
        now = "2026-07-30T00:00:00+00:00"
        for asset_id, digest in (
            ("asset_active", active_sha),
            ("asset_stale", stale_sha),
        ):
            cf.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path,
                 campaign_path, filename, audit_status, review_state, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'draft', ?, ?)
                """,
                (
                    asset_id,
                    campaign_id,
                    source_id,
                    digest,
                    str(shared),
                    str(shared),
                    shared.name,
                    now,
                    now,
                ),
            )
            blob_id = f"blob_{asset_id}"
            cf.conn.execute(
                """
                INSERT INTO generation_output_blobs
                (id, content_sha256, byte_size, media_type, created_at)
                VALUES (?, ?, 6, 'video', ?)
                """,
                (blob_id, digest, now),
            )
            cf.conn.execute(
                """
                INSERT INTO generation_attempts
                (id, campaign_id, source_asset_id, rendered_asset_id,
                 output_blob_id, model_id, motion_task, attempted_output_path,
                 duplicate_disposition, created_at)
                VALUES (?, ?, ?, ?, ?, 'test', 'legacy_unknown', ?,
                        'legacy_reference', ?)
                """,
                (
                    f"attempt_{asset_id}",
                    campaign_id,
                    source_id,
                    asset_id,
                    blob_id,
                    str(shared),
                    now,
                ),
            )
        cf.conn.execute(
            """
            INSERT INTO quarantined_assets
            (id, campaign_id, rendered_asset_id, reason, excluded_from_metrics,
             created_at)
            VALUES ('quarantine_stale', ?, 'asset_stale', 'identity conflict', 1, ?)
            """,
            (campaign_id, now),
        )
        cf.conn.commit()

        report = reconciliation_report(cf.conn, cf.settings)
        assert not any(
            item["findingClass"] == "multiple_files_claiming_conflicting_identity"
            and item["subjectId"] == str(shared)
            for item in report["findings"]
        )
    finally:
        cf.close()


def test_reconciliation_summary_is_bounded_sorted_and_actionable(
    tmp_path: Path,
) -> None:
    findings = []
    for index, finding_class in enumerate(("z_problem", "a_problem", "z_problem")):
        fingerprint = f"{index + 1:064x}"
        findings.append(
            {
                "findingClass": finding_class,
                "caseId": f"reconcile_{fingerprint[:20]}",
                "fingerprint": fingerprint,
                "subjectType": "file",
                "subjectId": str(tmp_path / f"{index}.mp4"),
                "repairSupported": index != 1,
                "repairAction": "move_orphan_to_quarantine" if index != 1 else None,
                "evidence": {"path": str(tmp_path / f"{index}.mp4")},
            }
        )
    full = {
        "observedAt": "2026-07-31T00:00:00+00:00",
        "database": str(tmp_path / "campaign.sqlite"),
        "managedRoots": {"campaigns": str(tmp_path)},
        "findingCount": 3,
        "counts": {"z_problem": 2, "a_problem": 1},
        "findings": findings,
    }

    summary = summarize_reconciliation_report(full, examples_per_class=1)

    assert summary["findingCount"] == full["findingCount"]
    assert summary["repairableFindingCount"] == 2
    assert summary["manualReviewFindingCount"] == 1
    assert summary["repairActions"] == {"move_orphan_to_quarantine": 2}
    assert list(summary["counts"]) == ["a_problem", "z_problem"]
    assert list(summary["examples"]) == ["a_problem", "z_problem"]
    assert all(len(rows) == 1 for rows in summary["examples"].values())
    assert len(summary["examples"]["z_problem"][0]["fingerprint"]) == 64
    assert summary["fullReportOmitted"] is True


def test_repair_fingerprint_blocks_stale_operator_input_without_changes(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        root = cf.settings.campaigns_dir / "stacey" / "reconcile" / "02_rendered"
        root.mkdir(parents=True)
        orphan = root / "provider.mp4"
        orphan.write_bytes(b"provider-output")
        finding = next(
            item
            for item in reconciliation_report(cf.conn, cf.settings)["findings"]
            if item["evidence"].get("path") == str(orphan)
        )
        before_changes = cf.conn.total_changes

        with pytest.raises(ValueError, match="fingerprint"):
            repair_reconciliation_case(
                cf.conn,
                cf.settings,
                case_id=finding["caseId"],
                expected_fingerprint="0" * 64,
                operator="operator",
                reason="stale pasted input",
                apply=True,
            )

        assert orphan.read_bytes() == b"provider-output"
        assert cf.conn.total_changes == before_changes
        assert not (
            cf.settings.campaigns_dir / "_reconciliation" / finding["caseId"]
        ).exists()
    finally:
        cf.close()


def test_failed_exact_sha_audit_is_not_final_evidence(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        path = (
            cf.settings.campaigns_dir
            / "stacey"
            / "reconcile"
            / "00_sources"
            / "source.mp4"
        )
        path.parent.mkdir(parents=True)
        path.write_bytes(b"source")
        source_id = _source(cf, path)
        source = cf.conn.execute(
            "SELECT campaign_id FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()
        output = path.parents[1] / "02_rendered" / "approved.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        now = "2026-07-30T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, audit_status, review_state, created_at,
             updated_at)
            VALUES ('rendered_failed_audit', ?, ?, ?, ?, ?, ?, 'passed',
                    'approved', ?, ?)
            """,
            (
                source["campaign_id"],
                source_id,
                digest,
                str(output),
                str(output),
                output.name,
                now,
                now,
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO approval_decisions
            (id, campaign_id, rendered_asset_id, subject_sha256, decision, created_at)
            VALUES ('approval_exact', ?, 'rendered_failed_audit', ?, 'approved', ?)
            """,
            (source["campaign_id"], digest, now),
        )
        cf.conn.execute(
            """
            INSERT INTO audit_reports
            (id, campaign_id, rendered_asset_id, subject_sha256, report_path,
             score, status, overall_verdict, failed_checks_json, created_at)
            VALUES ('audit_failed', ?, 'rendered_failed_audit', ?, ?, 0,
                    'failed', 'fail', '["decode"]', ?)
            """,
            (
                source["campaign_id"],
                digest,
                str(output.with_suffix(".audit.json")),
                now,
            ),
        )
        cf.conn.commit()

        finding = next(
            item
            for item in reconciliation_report(cf.conn, cf.settings)["findings"]
            if item["findingClass"] == "registered_asset_without_final_evidence"
            and item["subjectId"] == "rendered_failed_audit"
        )

        assert finding["evidence"]["hasExactApproval"] is True
        assert finding["evidence"]["hasExactAudit"] is False
        repair_reconciliation_case(
            cf.conn,
            cf.settings,
            case_id=finding["caseId"],
            expected_fingerprint=finding["fingerprint"],
            operator="operator",
            reason="failed exact audit cannot remain final",
            apply=True,
        )
        assert not any(
            item["findingClass"] == "registered_asset_without_final_evidence"
            and item["subjectId"] == "rendered_failed_audit"
            for item in reconciliation_report(cf.conn, cf.settings)["findings"]
        )
    finally:
        cf.close()


def test_exact_would_post_review_and_warning_audit_are_final_evidence(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source_path = tmp_path / "source.mp4"
        source_path.write_bytes(b"source")
        source_id = _source(cf, source_path)
        campaign_id = cf.conn.execute(
            "SELECT campaign_id FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()[0]
        output = tmp_path / "approved.mp4"
        output.write_bytes(b"rendered")
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        now = "2026-07-30T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, audit_status, review_state, created_at,
             updated_at)
            VALUES ('warned_asset', ?, ?, ?, ?, ?, ?, 'needs_review',
                    'review_ready', ?, ?)
            """,
            (
                campaign_id,
                source_id,
                digest,
                str(output),
                str(output),
                output.name,
                now,
                now,
            ),
        )
        cf.conn.commit()
        review_existing_asset(
            cf.conn,
            rendered_asset_id="warned_asset",
            final_sha256=digest,
            reviewer="operator",
            verdict="WOULD_POST",
            results={},
            notes=None,
            apply=True,
        )
        report_path = tmp_path / "warned.audit.json"
        report_path.write_text("{}", encoding="utf-8")
        cf.conn.execute(
            """
            INSERT INTO audit_reports
            (id, campaign_id, rendered_asset_id, subject_sha256, report_path,
             score, status, overall_verdict, failed_checks_json, created_at)
            VALUES ('warned_audit', ?, 'warned_asset', ?, ?, 84,
                    'needs_review', 'warn', '[]', ?)
            """,
            (campaign_id, digest, str(report_path), now),
        )
        cf.conn.commit()

        assert not any(
            item["findingClass"] == "registered_asset_without_final_evidence"
            and item["subjectId"] == "warned_asset"
            for item in reconciliation_report(cf.conn, cf.settings)["findings"]
        )
    finally:
        cf.close()


def test_terminal_threadsdash_export_does_not_require_ephemeral_manifest(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source_path = tmp_path / "source.mp4"
        source_path.write_bytes(b"source")
        source_id = _source(cf, source_path)
        campaign_id = cf.conn.execute(
            "SELECT campaign_id FROM source_assets WHERE id = ?", (source_id,)
        ).fetchone()[0]
        missing = tmp_path / "dry-run-export.json"
        cf.conn.execute(
            """
            INSERT INTO threadsdash_exports
            (id, campaign_id, manifest_path, user_id, dry_run, status, created_at)
            VALUES ('dry_export', ?, ?, 'operator', 1, 'dry_run', ?)
            """,
            (campaign_id, str(missing), "2026-07-30T00:00:00+00:00"),
        )
        cf.conn.commit()

        assert not any(
            item["findingClass"] == "database_row_with_missing_file"
            and item["subjectId"] == "dry_export"
            for item in reconciliation_report(cf.conn, cf.settings)["findings"]
        )
    finally:
        cf.close()


def test_orphan_repair_is_backed_up_audited_and_idempotent(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        root = cf.settings.campaigns_dir / "stacey" / "reconcile" / "02_rendered"
        root.mkdir(parents=True)
        orphan = root / "provider.mp4"
        orphan.write_bytes(b"provider-output")
        report = reconciliation_report(cf.conn, cf.settings)
        finding = next(
            item
            for item in report["findings"]
            if item["findingClass"] == "provider_output_retained_not_registered"
            and item["evidence"]["path"] == str(orphan)
        )

        preview = repair_reconciliation_case(
            cf.conn,
            cf.settings,
            case_id=finding["caseId"],
            operator="operator",
            reason="unregistered provider output",
            apply=False,
        )
        assert preview["applied"] is False
        assert orphan.exists()

        applied = repair_reconciliation_case(
            cf.conn,
            cf.settings,
            case_id=finding["caseId"],
            expected_fingerprint=preview["caseFingerprint"],
            operator="operator",
            reason="unregistered provider output",
            apply=True,
        )
        assert applied["changed"] is True
        assert not orphan.exists()
        assert Path(applied["databaseBackup"]["path"]).is_file()
        assert Path(applied["fileBackup"]["path"]).read_bytes() == b"provider-output"
        receipt = cf.conn.execute(
            "SELECT * FROM artifact_reconciliation_repairs WHERE case_id = ?",
            (finding["caseId"],),
        ).fetchone()
        assert receipt is not None
        assert (
            json.loads(receipt["result_json"])["disposition"] == "moved_to_quarantine"
        )

        replay = repair_reconciliation_case(
            cf.conn,
            cf.settings,
            case_id=finding["caseId"],
            expected_fingerprint=preview["caseFingerprint"],
            operator="operator",
            reason="repeat is safe",
            apply=True,
        )
        assert replay["changed"] is False
        assert replay["idempotentReplay"] is True
    finally:
        cf.close()


def test_missing_source_repair_tombstones_state_without_deleting_evidence(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        path = (
            cf.settings.campaigns_dir
            / "stacey"
            / "reconcile"
            / "00_sources"
            / "gone.mp4"
        )
        path.parent.mkdir(parents=True)
        path.write_bytes(b"gone")
        source_id = _source(cf, path)
        cf.conn.execute(
            "UPDATE source_asset_lifecycle SET lifecycle_state = 'approved' "
            "WHERE source_asset_id = ?",
            (source_id,),
        )
        cf.conn.execute(
            "UPDATE source_assets SET status = 'approved' WHERE id = ?",
            (source_id,),
        )
        cf.conn.commit()
        path.unlink()
        report = reconciliation_report(cf.conn, cf.settings)
        finding = next(
            item
            for item in report["findings"]
            if item["findingClass"] == "database_row_with_missing_file"
            and item["subjectId"] == source_id
        )

        applied = repair_reconciliation_case(
            cf.conn,
            cf.settings,
            case_id=finding["caseId"],
            expected_fingerprint=finding["fingerprint"],
            operator="operator",
            reason="bytes missing during reconciliation",
            apply=True,
        )

        assert applied["result"]["lifecycleState"] == "quarantined"
        lifecycle = cf.conn.execute(
            "SELECT * FROM source_asset_lifecycle WHERE source_asset_id = ?",
            (source_id,),
        ).fetchone()
        assert lifecycle["quarantine_reason"] == "registered_bytes_missing"
        assert (
            cf.conn.execute(
                "SELECT status FROM source_assets WHERE id = ?", (source_id,)
            ).fetchone()["status"]
            == "quarantined"
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM source_asset_lifecycle_events "
                "WHERE source_asset_id = ?",
                (source_id,),
            ).fetchone()[0]
            == 1
        )
        assert not any(
            item["subjectId"] == source_id
            for item in reconciliation_report(cf.conn, cf.settings)["findings"]
        )
    finally:
        cf.close()


def test_managed_external_source_does_not_claim_missing_backup(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        path = cf.settings.campaigns_dir / "stacey" / "reconcile" / "source.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"managed")
        source_id = _source(cf, path)
        cf.conn.execute(
            """
            UPDATE source_asset_lifecycle
            SET storage_policy = 'external_reference', backup_state = 'unknown'
            WHERE source_asset_id = ?
            """,
            (source_id,),
        )
        cf.conn.commit()

        report = reconciliation_report(cf.conn, cf.settings)

        assert not any(
            item["findingClass"] == "external_reference_outside_backup_coverage"
            and item["subjectId"] == source_id
            for item in report["findings"]
        )
    finally:
        cf.close()
