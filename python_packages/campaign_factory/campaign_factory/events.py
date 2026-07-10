from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .persistence import json_load


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
        self.conn.execute(
            """
            INSERT INTO pipeline_jobs
            (id, job_type, campaign_id, status, input_json, result_json, error, attempt_count,
             started_at, finished_at, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, '{}', NULL, 0, NULL, NULL, ?, ?)
            """,
            (
                job_id,
                job_type,
                campaign_id,
                json.dumps(
                    self._sanitize_for_storage(input_payload or {}),
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
        self.conn.execute(
            "UPDATE pipeline_jobs SET status = 'running', attempt_count = attempt_count + 1, started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?",
            (now, now, job_id),
        )
        self.conn.commit()
        return self.pipeline_job(job_id)

    def finish_pipeline_job(
        self, job_id: str, result_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = self._utc_now()
        self.conn.execute(
            "UPDATE pipeline_jobs SET status = 'succeeded', result_json = ?, error = NULL, finished_at = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(
                    self._sanitize_for_storage(result_payload or {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                now,
                job_id,
            ),
        )
        self.conn.commit()
        return self.pipeline_job(job_id)

    def fail_pipeline_job(
        self, job_id: str, error: str, result_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = self._utc_now()
        self.conn.execute(
            "UPDATE pipeline_jobs SET status = 'failed', result_json = ?, error = ?, finished_at = ?, updated_at = ? WHERE id = ?",
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
        self.conn.commit()
        return self.pipeline_job(job_id)

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

        action='fail' marks stale jobs failed; action='requeue' returns them to
        'queued' (unless max_attempts is set and already reached, in which case
        the job is failed instead). Returns a summary with the touched jobs.
        """
        if stuck_hours <= 0:
            raise ValueError("stuck_hours must be positive")
        if action not in {"fail", "requeue"}:
            raise ValueError(f"unsupported reclaim action: {action}")
        rows = self.conn.execute(
            "SELECT * FROM pipeline_jobs WHERE status IN ('queued', 'running')"
        ).fetchall()
        now = self._utc_now()
        reclaimed: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            stuck, age_hours = _pipeline_job_stuck_status(row, stuck_hours)
            if not stuck:
                continue
            attempts = int(row.get("attempt_count") or 0)
            requeue = action == "requeue" and (
                max_attempts is None or attempts < max_attempts
            )
            if requeue:
                self.conn.execute(
                    "UPDATE pipeline_jobs SET status = 'queued', error = NULL, started_at = NULL, updated_at = ? WHERE id = ? AND status IN ('queued', 'running')",
                    (now, row["id"]),
                )
                outcome = "requeued"
            else:
                error = (
                    f"reclaimed as stale after {round(age_hours or 0.0, 3)}h "
                    f"(threshold {stuck_hours}h)"
                )
                self.conn.execute(
                    "UPDATE pipeline_jobs SET status = 'failed', error = ?, finished_at = ?, updated_at = ? WHERE id = ? AND status IN ('queued', 'running')",
                    (error, now, now, row["id"]),
                )
                outcome = "failed"
            reclaimed.append(
                {
                    "id": row["id"],
                    "jobType": row["job_type"],
                    "campaignId": row["campaign_id"],
                    "previousStatus": row["status"],
                    "attemptCount": attempts,
                    "ageHours": round(age_hours, 3) if age_hours is not None else None,
                    "outcome": outcome,
                }
            )
        self.conn.commit()
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
        return False, None
    age_hours = max(0.0, (datetime.now(UTC) - timestamp).total_seconds() / 3600.0)
    return age_hours >= threshold_hours, age_hours
