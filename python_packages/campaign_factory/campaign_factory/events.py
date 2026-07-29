from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .persistence import json_load

_PIPELINE_SAFE_REPLAY_CLASSES = {
    "contentforge_audit": "LOCAL",
    "static_mp4": "LOCAL",
    "sync_performance": "IDEMPOTENT_EXTERNAL",
}
_EFFECT_STATES = {
    "PRE_EFFECT",
    "SUBMISSION_STARTED",
    "EXTERNAL_ID_KNOWN",
    "AMBIGUOUS",
    "NO_EFFECT_CONFIRMED",
    "EFFECT_CONFIRMED",
    "FINALIZED",
}
_EFFECT_TRANSITIONS = {
    "PRE_EFFECT": {"SUBMISSION_STARTED", "EXTERNAL_ID_KNOWN", "FINALIZED"},
    "SUBMISSION_STARTED": {
        "EXTERNAL_ID_KNOWN",
        "AMBIGUOUS",
        "NO_EFFECT_CONFIRMED",
        "EFFECT_CONFIRMED",
        "FINALIZED",
    },
    "EXTERNAL_ID_KNOWN": {"AMBIGUOUS", "EFFECT_CONFIRMED", "FINALIZED"},
    "AMBIGUOUS": {
        "EXTERNAL_ID_KNOWN",
        "NO_EFFECT_CONFIRMED",
        "EFFECT_CONFIRMED",
    },
    "NO_EFFECT_CONFIRMED": {"PRE_EFFECT", "FINALIZED"},
    "EFFECT_CONFIRMED": {"FINALIZED"},
    "FINALIZED": set(),
}


def _pipeline_recovery_state(row: dict[str, Any]) -> dict[str, Any]:
    input_payload = json_load(row.get("input_json"), {})
    result_payload = json_load(row.get("result_json"), {})
    safe_replay_class = str(
        row.get("recovery_policy")
        or _PIPELINE_SAFE_REPLAY_CLASSES.get(
            str(row.get("job_type")), "NEVER_AUTOMATIC"
        )
    )
    effect_state = str(row.get("effect_state") or "PRE_EFFECT")
    if effect_state not in _EFFECT_STATES:
        effect_state = "AMBIGUOUS"
    reconciliation_required = effect_state == "AMBIGUOUS"

    def first_string(*values: Any) -> str | None:
        return next(
            (value for value in values if isinstance(value, str) and value.strip()),
            None,
        )

    return {
        "workItemId": first_string(row.get("work_item_id")) or str(row["id"]),
        "authorizationId": first_string(
            row.get("authorization_id"),
            input_payload.get("authorizationId"),
            result_payload.get("authorizationId"),
        ),
        "attemptId": first_string(row.get("attempt_id"))
        or f"{row['id']}:{int(row.get('attempt_count') or 0)}",
        "externalOperationId": first_string(
            row.get("external_operation_id"),
            result_payload.get("externalOperationId"),
            result_payload.get("generationId"),
            result_payload.get("containerId"),
            input_payload.get("externalOperationId"),
            input_payload.get("generationId"),
            input_payload.get("containerId"),
        ),
        "effectState": effect_state,
        "reconciliationRequired": reconciliation_required,
        "safeReplayClass": safe_replay_class,
        "reconciliationClassification": row.get("reconciliation_classification"),
        "reconciliation": json_load(row.get("reconciliation_json"), {}),
    }


class EventRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        new_id: Callable[[str], str],
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._new_id = new_id
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now

    def record_event(
        self,
        event_type: str,
        *,
        campaign_id: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        render_job_id: str | None = None,
        audit_report_id: str | None = None,
        threadsdash_export_id: str | None = None,
        pipeline_job_id: str | None = None,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if status not in {"info", "success", "warning", "failure"}:
            raise ValueError(
                "activity event status must be info, success, warning, or failure"
            )
        event_id = self._new_id("evt")
        now = self._utc_now()
        self.conn.execute(
            """
            INSERT INTO activity_events
            (id, event_type, campaign_id, source_asset_id, rendered_asset_id, render_job_id,
             audit_report_id, threadsdash_export_id, pipeline_job_id, status, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                campaign_id,
                source_asset_id,
                rendered_asset_id,
                render_job_id,
                audit_report_id,
                threadsdash_export_id,
                pipeline_job_id,
                status,
                message or event_type.replace("_", " "),
                json.dumps(
                    self._sanitize_for_storage(metadata or {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
            ),
        )
        if commit:
            self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM activity_events WHERE id = ?", (event_id,)
            ).fetchone()
        )

    def event_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "eventType": row["event_type"],
            "campaignId": row["campaign_id"],
            "sourceAssetId": row["source_asset_id"],
            "renderedAssetId": row["rendered_asset_id"],
            "renderJobId": row["render_job_id"],
            "auditReportId": row["audit_report_id"],
            "threadsdashExportId": row["threadsdash_export_id"],
            "pipelineJobId": row["pipeline_job_id"],
            "status": row["status"],
            "message": row["message"],
            "metadata": json_load(row["metadata_json"], {}),
            "createdAt": row["created_at"],
        }

    def events_for_campaign(
        self, campaign_slug: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT id FROM campaigns WHERE slug = ?", (self._slugify(campaign_slug),)
        ).fetchone()
        if not row:
            raise ValueError(f"campaign not found: {campaign_slug}")
        rows = self.conn.execute(
            "SELECT * FROM activity_events WHERE campaign_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (row["id"], max(1, min(limit, 1000))),
        ).fetchall()
        return [self.event_payload(dict(event_row)) for event_row in rows]

    def events_for_asset(
        self, rendered_asset_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM activity_events WHERE rendered_asset_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (rendered_asset_id, max(1, min(limit, 1000))),
        ).fetchall()
        return [self.event_payload(dict(row)) for row in rows]

    def mark_asset_operator_removed(
        self,
        rendered_asset_id: str,
        *,
        operator: str,
        reason: str,
        relocated_output_path: str | None = None,
        post_ids: list[str] | None = None,
        cancellation_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"rendered asset not found: {rendered_asset_id}")
        asset = dict(row)
        metadata = json_load(asset.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        relocated_sha = None
        if relocated_output_path:
            relocated = Path(relocated_output_path)
            if relocated.is_file():
                relocated_sha = hashlib.sha256(relocated.read_bytes()).hexdigest()
        receipt = {
            "schema": "creator_os.operator_media_removal_receipt.v1",
            "assetId": rendered_asset_id,
            "postIds": post_ids or [],
            "operator": operator,
            "reason": reason,
            "generationStatus": "completed",
            "creativeDecision": "rejected",
            "lifecycleStatus": "operator_removed",
            "scheduleStatus": "cancelled",
            "technicalFailure": False,
            "providerFailure": False,
            "qcFailure": False,
            "learningEligible": False,
            "originalOutputPath": asset.get("output_path"),
            "relocatedOutputPath": relocated_output_path,
            "originalContentSha": asset.get("content_hash"),
            "relocatedContentSha": relocated_sha,
            "cancellationEvidence": cancellation_evidence or [],
            "recordedAt": self._utc_now(),
        }
        metadata.update(
            {
                key: receipt[key]
                for key in (
                    "generationStatus",
                    "creativeDecision",
                    "lifecycleStatus",
                    "scheduleStatus",
                    "technicalFailure",
                    "providerFailure",
                    "qcFailure",
                    "learningEligible",
                )
            }
        )
        metadata["operatorRemoval"] = receipt
        with self.conn:
            self.conn.execute(
                """
                UPDATE rendered_assets
                SET review_state = 'rejected', metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(
                        self._sanitize_for_storage(metadata),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    receipt["recordedAt"],
                    rendered_asset_id,
                ),
            )
            event = self.record_event(
                "operator_media_removed",
                campaign_id=asset.get("campaign_id"),
                source_asset_id=asset.get("source_asset_id"),
                rendered_asset_id=rendered_asset_id,
                status="warning",
                message="Operator removed scheduled derivative",
                metadata=receipt,
                commit=False,
            )
        return {
            "assetId": rendered_asset_id,
            "reviewState": "rejected",
            "receipt": receipt,
            "activityEventId": event["id"],
        }

    def jobs_for_campaign(
        self,
        campaign_slug: str | None = None,
        limit: int = 100,
        statuses: list[str] | None = None,
        stuck_hours: float | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if campaign_slug:
            row = self.conn.execute(
                "SELECT id FROM campaigns WHERE slug = ?",
                (self._slugify(campaign_slug),),
            ).fetchone()
            if not row:
                raise ValueError(f"campaign not found: {campaign_slug}")
            clauses.append("pipeline_jobs.campaign_id = ?")
            params.append(row["id"])
        if statuses:
            normalized = [
                status.strip().lower() for status in statuses if status.strip()
            ]
            if normalized:
                placeholders = ", ".join("?" for _ in normalized)
                clauses.append(f"pipeline_jobs.status IN ({placeholders})")
                params.extend(normalized)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT pipeline_jobs.*, campaigns.slug AS campaign_slug, campaigns.name AS campaign_name
            FROM pipeline_jobs
            LEFT JOIN campaigns ON campaigns.id = pipeline_jobs.campaign_id
            {where}
            ORDER BY pipeline_jobs.created_at DESC, pipeline_jobs.id DESC
            LIMIT ?
            """,
            (*params, max(1, min(limit, 1000))),
        ).fetchall()
        return [
            self.pipeline_job_payload(dict(job_row), stuck_hours=stuck_hours)
            for job_row in rows
        ]

    def create_pipeline_job(
        self,
        job_type: str,
        campaign_id: str | None,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = self._new_id("job")
        now = self._utc_now()
        payload = self._sanitize_for_storage(input_payload or {})
        recovery_policy = _PIPELINE_SAFE_REPLAY_CLASSES.get(
            job_type, "NEVER_AUTOMATIC"
        )
        work_item_id = str(payload.get("workItemId") or job_id)
        authorization_id = _optional_text(payload.get("authorizationId"))
        external_operation_id = _first_optional_text(
            payload.get("externalOperationId"),
            payload.get("generationId"),
            payload.get("containerId"),
        )
        effect_state = (
            "EXTERNAL_ID_KNOWN" if external_operation_id else "PRE_EFFECT"
        )
        self.conn.execute(
            """
            INSERT INTO pipeline_jobs
            (id, job_type, campaign_id, status, effect_state, recovery_policy,
             work_item_id, authorization_id, attempt_id, external_operation_id,
             reconciliation_classification, reconciliation_json,
             input_json, result_json, error, attempt_count,
             started_at, finished_at, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, NULL, ?, NULL, '{}',
                    ?, '{}', NULL, 0, NULL, NULL, ?, ?)
            """,
            (
                job_id,
                job_type,
                campaign_id,
                effect_state,
                recovery_policy,
                work_item_id,
                authorization_id,
                external_operation_id,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.pipeline_job(job_id)

    def start_pipeline_job(self, job_id: str) -> dict[str, Any]:
        now = self._utc_now()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'running', attempt_count = attempt_count + 1,
                    attempt_id = id || ':' || (attempt_count + 1),
                    started_at = ?, finished_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            self._require_pipeline_job_transition(
                job_id, cursor, expected=("queued",), target="running"
            )
        return self.pipeline_job(job_id)

    def finish_pipeline_job(
        self, job_id: str, result_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = self._utc_now()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'succeeded', result_json = ?, error = NULL,
                    effect_state = 'FINALIZED',
                    external_operation_id = COALESCE(?, external_operation_id),
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    json.dumps(
                        self._sanitize_for_storage(result_payload or {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    _first_optional_text(
                        (result_payload or {}).get("externalOperationId"),
                        (result_payload or {}).get("generationId"),
                        (result_payload or {}).get("containerId"),
                    ),
                    now,
                    now,
                    job_id,
                ),
            )
            self._require_pipeline_job_transition(
                job_id, cursor, expected=("running",), target="succeeded"
            )
        return self.pipeline_job(job_id)

    def fail_pipeline_job(
        self, job_id: str, error: str, result_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = self._utc_now()
        row = self.conn.execute(
            """
            SELECT status, effect_state, external_operation_id
            FROM pipeline_jobs WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"pipeline job not found: {job_id}")
        if (
            row["status"] == "running"
            and row["effect_state"] in {"SUBMISSION_STARTED", "AMBIGUOUS"}
            and not row["external_operation_id"]
        ):
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE pipeline_jobs
                    SET effect_state = 'AMBIGUOUS', result_json = ?, error = ?,
                        reconciliation_classification = 'HISTORY_REQUIRED',
                        updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (
                        json.dumps(
                            self._sanitize_for_storage(result_payload or {}),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        error,
                        now,
                        job_id,
                    ),
                )
            return self.pipeline_job(job_id)
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'failed', result_json = ?, error = ?,
                    effect_state = 'FINALIZED',
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    json.dumps(
                        self._sanitize_for_storage(result_payload or {}),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    error,
                    now,
                    now,
                    job_id,
                ),
            )
            self._require_pipeline_job_transition(
                job_id, cursor, expected=("running",), target="failed"
            )
        return self.pipeline_job(job_id)

    def mark_pipeline_effect_state(
        self,
        job_id: str,
        effect_state: str,
        *,
        authorization_id: str | None = None,
        external_operation_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = str(effect_state).strip().upper()
        if target not in _EFFECT_STATES:
            raise ValueError(f"unsupported effect state: {effect_state}")
        row = self.conn.execute(
            "SELECT * FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"pipeline job not found: {job_id}")
        current = str(row["effect_state"] or "PRE_EFFECT")
        if target != current and target not in _EFFECT_TRANSITIONS.get(current, set()):
            raise RuntimeError(
                f"invalid_pipeline_effect_transition:{current}->{target}"
            )
        now = self._utc_now()
        with self.conn:
            self.conn.execute(
                """
                UPDATE pipeline_jobs
                SET effect_state = ?,
                    authorization_id = COALESCE(?, authorization_id),
                    external_operation_id = COALESCE(?, external_operation_id),
                    reconciliation_json = CASE
                      WHEN ? IS NULL THEN reconciliation_json ELSE ? END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    target,
                    _optional_text(authorization_id),
                    _optional_text(external_operation_id),
                    (
                        None
                        if evidence is None
                        else json.dumps(
                            self._sanitize_for_storage(evidence),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                    (
                        None
                        if evidence is None
                        else json.dumps(
                            self._sanitize_for_storage(evidence),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                    now,
                    job_id,
                ),
            )
        return self.pipeline_job(job_id)

    def reconcile_pipeline_external_effect(
        self,
        job_id: str,
        *,
        classification: str,
        operator: str,
        external_operation_id: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(classification).strip().upper()
        target_by_classification = {
            "EXACT_MATCH": "EXTERNAL_ID_KNOWN",
            "PROVIDER_PROVED_NO_EFFECT": "NO_EFFECT_CONFIRMED",
            "MULTIPLE_MATCHES": "AMBIGUOUS",
            "HISTORY_UNAVAILABLE": "AMBIGUOUS",
        }
        target = target_by_classification.get(normalized)
        if target is None:
            raise ValueError(f"unsupported reconciliation classification: {classification}")
        if normalized == "EXACT_MATCH" and not _optional_text(external_operation_id):
            raise ValueError("EXACT_MATCH requires external_operation_id")
        receipt = {
            "schema": "campaign_factory.pipeline_effect_reconciliation.v1",
            "jobId": job_id,
            "classification": normalized,
            "operator": _required_text(operator, "operator"),
            "externalOperationId": _optional_text(external_operation_id),
            "evidence": self._sanitize_for_storage(evidence or {}),
            "reconciledAt": self._utc_now(),
        }
        with self.conn:
            self.conn.execute(
                """
                UPDATE pipeline_jobs
                SET effect_state = ?, external_operation_id = COALESCE(?, external_operation_id),
                    reconciliation_classification = ?, reconciliation_json = ?,
                    error = CASE WHEN ? = 'AMBIGUOUS'
                      THEN 'manual_hold_unknown_external_effect' ELSE error END,
                    updated_at = ?
                WHERE id = ? AND status = 'running'
                  AND effect_state IN ('SUBMISSION_STARTED', 'AMBIGUOUS')
                """,
                (
                    target,
                    _optional_text(external_operation_id),
                    normalized,
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                    target,
                    receipt["reconciledAt"],
                    job_id,
                ),
            )
        return self.pipeline_job(job_id)

    def authorize_pipeline_retry(
        self, job_id: str, *, authorization_id: str, operator: str
    ) -> dict[str, Any]:
        now = self._utc_now()
        authorization = _required_text(authorization_id, "authorization_id")
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'queued', effect_state = 'PRE_EFFECT',
                    authorization_id = ?, attempt_id = NULL,
                    external_operation_id = NULL, error = NULL,
                    started_at = NULL, finished_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'running'
                  AND effect_state = 'NO_EFFECT_CONFIRMED'
                """,
                (authorization, now, job_id),
            )
            self._require_pipeline_job_transition(
                job_id, cursor, expected=("running",), target="queued"
            )
            self.record_event(
                "pipeline_retry_authorized",
                pipeline_job_id=job_id,
                status="warning",
                message="New provider attempt authorized after proven no effect",
                metadata={
                    "authorizationId": authorization,
                    "operator": _required_text(operator, "operator"),
                    "authorizedAt": now,
                },
                commit=False,
            )
        return self.pipeline_job(job_id)

    def _require_pipeline_job_transition(
        self,
        job_id: str,
        cursor: sqlite3.Cursor,
        *,
        expected: tuple[str, ...],
        target: str,
    ) -> None:
        if cursor.rowcount == 1:
            return
        row = self.conn.execute(
            "SELECT status FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"pipeline job not found: {job_id}")
        current = str(row["status"])
        allowed = ", ".join(expected)
        raise RuntimeError(
            f"pipeline_job_transition_conflict: {job_id} is {current}; "
            f"expected {allowed} before {target}"
        )

    def set_pipeline_job_campaign(
        self, job_id: str, campaign_id: str
    ) -> dict[str, Any]:
        self.conn.execute(
            "UPDATE pipeline_jobs SET campaign_id = ?, updated_at = ? WHERE id = ?",
            (campaign_id, self._utc_now(), job_id),
        )
        self.conn.commit()
        return self.pipeline_job(job_id)

    def reclaim_stale_pipeline_jobs(
        self,
        stuck_hours: float,
        *,
        action: str = "fail",
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        """Recover pipeline jobs stranded in 'queued'/'running' by a crashed worker.

        action='fail' marks stale jobs failed. action='requeue' is allowed only
        for jobs proven pre-effect or registered as safely replayable; unknown
        running work is put in a terminal manual hold.
        """
        if stuck_hours <= 0:
            raise ValueError("stuck_hours must be positive")
        if action not in {"fail", "requeue"}:
            raise ValueError(f"unsupported reclaim action: {action}")
        now = self._utc_now()
        reclaimed: list[dict[str, Any]] = []
        with self.conn:
            rows = self.conn.execute(
                "SELECT * FROM pipeline_jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                stuck, age_hours = _pipeline_job_stuck_status(row, stuck_hours)
                if not stuck:
                    continue
                attempts = int(row.get("attempt_count") or 0)
                recovery = _pipeline_recovery_state(row)
                requeue = (
                    action == "requeue"
                    and (max_attempts is None or attempts < max_attempts)
                    and (
                        recovery["effectState"] == "PRE_EFFECT"
                        or recovery["safeReplayClass"]
                        in {"LOCAL", "IDEMPOTENT_EXTERNAL"}
                    )
                )
                expected_status = str(row["status"])
                expected_updated_at = str(row["updated_at"])
                if requeue:
                    cursor = self.conn.execute(
                        """
                        UPDATE pipeline_jobs
                        SET status = 'queued', effect_state = 'PRE_EFFECT',
                            error = NULL, started_at = NULL,
                            finished_at = NULL, updated_at = ?
                        WHERE id = ? AND status = ? AND updated_at = ?
                        """,
                        (now, row["id"], expected_status, expected_updated_at),
                    )
                    outcome = "requeued"
                else:
                    manual_hold = (
                        recovery["safeReplayClass"] == "NEVER_AUTOMATIC"
                        and recovery["effectState"]
                        in {
                            "SUBMISSION_STARTED",
                            "EXTERNAL_ID_KNOWN",
                            "AMBIGUOUS",
                            "EFFECT_CONFIRMED",
                        }
                    )
                    if manual_hold:
                        error = (
                            "known_external_operation_awaiting_poll"
                            if recovery["externalOperationId"]
                            else "manual_hold_unknown_external_effect"
                        )
                    elif age_hours is None:
                        error = (
                            "reclaimed as stale: unparseable updated_at/created_at "
                            f"timestamps (threshold {stuck_hours}h)"
                        )
                    else:
                        error = (
                            f"reclaimed as stale after {round(age_hours, 3)}h "
                            f"(threshold {stuck_hours}h)"
                        )
                    if manual_hold:
                        cursor = self.conn.execute(
                            """
                            UPDATE pipeline_jobs
                            SET effect_state = ?, error = ?,
                                reconciliation_classification = ?,
                                updated_at = ?
                            WHERE id = ? AND status = ? AND updated_at = ?
                            """,
                            (
                                (
                                    "EXTERNAL_ID_KNOWN"
                                    if recovery["externalOperationId"]
                                    else "AMBIGUOUS"
                                ),
                                error,
                                (
                                    "EXACT_MATCH"
                                    if recovery["externalOperationId"]
                                    else "HISTORY_REQUIRED"
                                ),
                                now,
                                row["id"],
                                expected_status,
                                expected_updated_at,
                            ),
                        )
                        outcome = "manual_hold"
                        recovery = {
                            **recovery,
                            "effectState": (
                                "EXTERNAL_ID_KNOWN"
                                if recovery["externalOperationId"]
                                else "AMBIGUOUS"
                            ),
                            "reconciliationRequired": not bool(
                                recovery["externalOperationId"]
                            ),
                            "reconciliationClassification": (
                                "EXACT_MATCH"
                                if recovery["externalOperationId"]
                                else "HISTORY_REQUIRED"
                            ),
                        }
                    else:
                        cursor = self.conn.execute(
                            """
                            UPDATE pipeline_jobs
                            SET status = 'failed', effect_state = 'FINALIZED',
                                error = ?, finished_at = ?, updated_at = ?
                            WHERE id = ? AND status = ? AND updated_at = ?
                            """,
                            (
                                error,
                                now,
                                now,
                                row["id"],
                                expected_status,
                                expected_updated_at,
                            ),
                        )
                        outcome = "failed"
                if cursor.rowcount != 1:
                    continue
                reclaimed.append(
                    {
                        "id": row["id"],
                        "jobType": row["job_type"],
                        "campaignId": row["campaign_id"],
                        "previousStatus": expected_status,
                        "attemptCount": attempts,
                        "ageHours": (
                            round(age_hours, 3) if age_hours is not None else None
                        ),
                        "outcome": outcome,
                        **recovery,
                    }
                )
        return {
            "stuckThresholdHours": stuck_hours,
            "action": action,
            "maxAttempts": max_attempts,
            "scanned": len(rows),
            "reclaimedCount": len(reclaimed),
            "reclaimed": reclaimed,
        }

    def pipeline_job(self, job_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"pipeline job not found: {job_id}")
        return self.pipeline_job_payload(dict(row))

    def pipeline_job_payload(
        self, row: dict[str, Any], *, stuck_hours: float | None = None
    ) -> dict[str, Any]:
        payload = {
            "id": row["id"],
            "jobType": row["job_type"],
            "campaignId": row["campaign_id"],
            "status": row["status"],
            "input": json_load(row["input_json"], {}),
            "result": json_load(row["result_json"], {}),
            "error": row["error"],
            "attemptCount": row["attempt_count"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if "campaign_slug" in row:
            payload["campaignSlug"] = row.get("campaign_slug")
            payload["campaignName"] = row.get("campaign_name")
        if stuck_hours is not None:
            stuck, age_hours = _pipeline_job_stuck_status(row, stuck_hours)
            payload["stuck"] = stuck
            payload["stuckAgeHours"] = (
                round(age_hours, 3) if age_hours is not None else None
            )
            payload["stuckThresholdHours"] = stuck_hours
        payload["recovery"] = _pipeline_recovery_state(row)
        return payload


def _parse_sqlite_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # SQLite datetime() emits naive UTC strings; never interpret as local.
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _pipeline_job_stuck_status(
    row: dict[str, Any], threshold_hours: float
) -> tuple[bool, float | None]:
    if str(row.get("status") or "").lower() not in {"queued", "running"}:
        return False, None
    timestamp = _parse_sqlite_timestamp(
        row.get("updated_at")
    ) or _parse_sqlite_timestamp(row.get("created_at"))
    if timestamp is None:
        # A queued/running job whose timestamps are missing or corrupted can
        # never age past the threshold; treating it as "not stuck" would strand
        # it forever with no operator signal. Fail loudly: report it stuck with
        # unknown age so reclaim recovers it (crash-recovery audit).
        return True, None
    age_hours = max(0.0, (datetime.now(UTC) - timestamp).total_seconds() / 3600.0)
    return age_hours >= threshold_hours, age_hours


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_optional_text(*values: Any) -> str | None:
    return next((text for value in values if (text := _optional_text(value))), None)


def _required_text(value: Any, label: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{label} is required")
    return text
