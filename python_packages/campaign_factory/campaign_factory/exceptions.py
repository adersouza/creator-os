from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Callable


EXCEPTION_STATUSES = {"open", "snoozed", "resolved"}
EXCEPTION_SEVERITIES = {"low", "medium", "high", "critical"}


class ExceptionRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        sanitize_for_storage: Callable[[Any], Any],
        json_load: Callable[[Any, Any], Any],
        utc_now: Callable[[], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., str | None],
        graph_id_for: Callable[..., str | None],
        autonomy_level: Callable[[], str],
        recommendation_proof_summary: Callable[[str], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._sanitize_for_storage = sanitize_for_storage
        self._json_load = json_load
        self._utc_now = utc_now
        self._campaign_by_slug = campaign_by_slug
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for
        self._autonomy_level = autonomy_level
        self._recommendation_proof_summary = recommendation_proof_summary

    def create_exception(
        self,
        *,
        reason_code: str,
        severity: str = "medium",
        campaign_id: str | None = None,
        account_id: str | None = None,
        entity_graph_id: str | None = None,
        recommendation_item_id: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if severity not in EXCEPTION_SEVERITIES:
            severity = "medium"
        key = f"{campaign_id or ''}:{reason_code}:{entity_graph_id or ''}:{recommendation_item_id or ''}:{account_id or ''}"
        exception_id = f"ex_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"
        now = self._utc_now()
        self.conn.execute(
            """
            INSERT INTO trust_exceptions (
              id, status, severity, reason_code, entity_graph_id, recommendation_item_id,
              campaign_id, account_id, payload_json, resolution_json, created_at, updated_at
            )
            VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status = CASE WHEN trust_exceptions.status = 'resolved' THEN trust_exceptions.status ELSE 'open' END,
              severity = excluded.severity,
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at
            """,
            (
                exception_id,
                severity,
                reason_code,
                entity_graph_id,
                recommendation_item_id,
                campaign_id,
                account_id,
                json.dumps(self._sanitize_for_storage(payload or {}), ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        exception_graph_id = self._ensure_graph_node(
            "trust_exception",
            local_table="trust_exceptions",
            local_id=exception_id,
            payload={"reasonCode": reason_code, "severity": severity, "campaignId": campaign_id, "accountId": account_id},
        )
        self._ensure_graph_edge(
            entity_graph_id,
            exception_graph_id,
            "entity_to_trust_exception",
            evidence={"reasonCode": reason_code},
        )
        if recommendation_item_id:
            rec_graph_id = self._graph_id_for(
                "recommendation_items",
                recommendation_item_id,
                entity_type="recommendation_item",
            )
            self._ensure_graph_edge(
                rec_graph_id,
                exception_graph_id,
                "recommendation_item_to_trust_exception",
                evidence={"reasonCode": reason_code},
            )
        if commit:
            self.conn.commit()
        return self.exception(exception_id)

    def exception(self, exception_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM trust_exceptions WHERE id = ?", (exception_id,)).fetchone()
        if not row:
            raise ValueError(f"exception not found: {exception_id}")
        return self.exception_payload(dict(row))

    def exceptions(self, campaign_slug: str | None = None, *, status: str = "open") -> dict[str, Any]:
        params: list[Any] = []
        where = []
        if campaign_slug:
            campaign = self._campaign_by_slug(campaign_slug)
            where.append("campaign_id = ?")
            params.append(campaign["id"])
        if status and status != "all":
            if status not in EXCEPTION_STATUSES:
                raise ValueError(f"exception status must be one of {sorted(EXCEPTION_STATUSES)}")
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM trust_exceptions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, updated_at DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return {
            "schema": "campaign_factory.exceptions.v1",
            "campaign": campaign_slug,
            "status": status,
            "generatedAt": self._utc_now(),
            "exceptions": [self.exception_payload(dict(row)) for row in rows],
        }

    def trust_summary(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        account_rows = self.conn.execute(
            "SELECT confidence, sample_size FROM account_memory WHERE campaign_id = ?",
            (campaign["id"],),
        ).fetchall()
        exception_rows = self.conn.execute(
            "SELECT status, severity FROM trust_exceptions WHERE campaign_id = ?",
            (campaign["id"],),
        ).fetchall()
        lifecycle_rows = self.conn.execute(
            """
            SELECT ri.status, COUNT(*) AS count
            FROM recommendation_items ri
            JOIN recommendation_runs rr ON rr.id = ri.run_id
            WHERE rr.campaign_id = ?
            GROUP BY ri.status
            """,
            (campaign["id"],),
        ).fetchall()
        accepted_waiting = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM recommendation_items ri
            JOIN recommendation_runs rr ON rr.id = ri.run_id
            WHERE rr.campaign_id = ? AND ri.status = 'accepted'
            """,
            (campaign["id"],),
        ).fetchone()[0]
        blocked_jobs = self.conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE campaign_id = ? AND status = 'failed'",
            (campaign["id"],),
        ).fetchone()[0]
        open_exceptions = [dict(row) for row in exception_rows if row["status"] in {"open", "snoozed"}]
        severity_counts = {severity: 0 for severity in ("critical", "high", "medium", "low")}
        for row in open_exceptions:
            severity = row.get("severity") if row.get("severity") in severity_counts else "medium"
            severity_counts[severity] += 1
        account_confidence_counts = {level: 0 for level in ("high", "medium", "low")}
        for row in account_rows:
            confidence = row["confidence"] if row["confidence"] in account_confidence_counts else "low"
            account_confidence_counts[confidence] += 1
        recommended_action = "ready_for_level_2_execution"
        if severity_counts["critical"] or severity_counts["high"]:
            recommended_action = "review_high_severity_exceptions"
        elif accepted_waiting:
            recommended_action = "execute_accepted_recommendations"
        elif not account_rows:
            recommended_action = "rebuild_account_memory_after_metrics_sync"
        elif blocked_jobs:
            recommended_action = "inspect_failed_pipeline_jobs"
        trust_score = 100
        trust_score -= severity_counts["critical"] * 30
        trust_score -= severity_counts["high"] * 20
        trust_score -= severity_counts["medium"] * 8
        trust_score -= severity_counts["low"] * 3
        trust_score -= int(blocked_jobs) * 10
        if not account_rows:
            trust_score -= 15
        trust_score = int(max(0, min(100, trust_score)))
        return {
            "schema": "campaign_factory.trust_summary.v1",
            "campaign": campaign["slug"],
            "generatedAt": self._utc_now(),
            "autonomyLevel": self._autonomy_level(),
            "trustScore": trust_score,
            "recommendedAction": recommended_action,
            "accountMemory": {
                "accountCount": len(account_rows),
                "confidenceCounts": account_confidence_counts,
                "totalSamples": sum(int(row["sample_size"] or 0) for row in account_rows),
            },
            "exceptions": {
                "openCount": len(open_exceptions),
                "severityCounts": severity_counts,
            },
            "recommendations": {
                "statusCounts": {row["status"]: int(row["count"]) for row in lifecycle_rows},
                "acceptedWaitingExecution": int(accepted_waiting),
                "proof": self._recommendation_proof_summary(campaign["id"]),
            },
            "pipeline": {
                "failedJobs": int(blocked_jobs),
            },
        }

    def resolve_exception(
        self,
        exception_id: str,
        *,
        resolution: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.update_exception_status(
            exception_id,
            "resolved",
            resolution={"resolution": resolution, "operator": operator, "resolvedAt": self._utc_now()},
        )

    def snooze_exception(
        self,
        exception_id: str,
        *,
        until: str | None = None,
        reason: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.update_exception_status(
            exception_id,
            "snoozed",
            snoozed_until=until,
            resolution={"reason": reason, "operator": operator, "snoozedAt": self._utc_now()},
        )

    def reopen_exception(
        self,
        exception_id: str,
        *,
        reason: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.update_exception_status(
            exception_id,
            "open",
            resolution={"reason": reason, "operator": operator, "reopenedAt": self._utc_now()},
        )

    def update_exception_status(
        self,
        exception_id: str,
        status: str,
        *,
        resolution: dict[str, Any] | None = None,
        snoozed_until: str | None = None,
    ) -> dict[str, Any]:
        if status not in EXCEPTION_STATUSES:
            raise ValueError(f"exception status must be one of {sorted(EXCEPTION_STATUSES)}")
        now = self._utc_now()
        resolved_at = now if status == "resolved" else None
        cursor = self.conn.execute(
            """
            UPDATE trust_exceptions
            SET status = ?, resolution_json = ?, snoozed_until = ?, resolved_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                json.dumps(self._sanitize_for_storage(resolution or {}), ensure_ascii=False, sort_keys=True),
                snoozed_until if status == "snoozed" else None,
                resolved_at,
                now,
                exception_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"exception not found: {exception_id}")
        self.conn.commit()
        return self.exception(exception_id)

    def exception_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["status"],
            "severity": row["severity"],
            "reasonCode": row["reason_code"],
            "entityGraphId": row["entity_graph_id"],
            "recommendationItemId": row["recommendation_item_id"],
            "campaignId": row["campaign_id"],
            "accountId": row["account_id"],
            "payload": self._json_load(row["payload_json"], {}),
            "resolution": self._json_load(row["resolution_json"], {}),
            "snoozedUntil": row["snoozed_until"],
            "resolvedAt": row["resolved_at"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "graphId": self._graph_id_for("trust_exceptions", row["id"]),
        }
