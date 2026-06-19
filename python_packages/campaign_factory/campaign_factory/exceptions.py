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
        normalize_content_surface: Callable[[str | None], str],
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
        self._normalize_content_surface = normalize_content_surface

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

    def exception_queue_report(
        self,
        *,
        daily_plan: dict[str, Any] | None = None,
        execution_readiness: dict[str, Any] | None = None,
        publishability_report: dict[str, Any] | None = None,
        surface_readiness_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        exceptions: list[dict[str, Any]] = []
        daily = daily_plan or {}
        readiness = execution_readiness or {}
        for account in daily.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            reason = str(account.get("blockedReason") or "")
            if str(account.get("state") or "") == "blocked" and reason:
                exceptions.append(self.exception_queue_item(
                    severity="high",
                    system="account_health",
                    account=account.get("accountId"),
                    asset="",
                    reason=reason,
                    next_action="resolve_account_blocker",
                ))
        for creator in daily.get("creators") or []:
            if not isinstance(creator, dict):
                continue
            shortfall = int(creator.get("inventoryShortfall") or 0)
            if shortfall > 0:
                exceptions.append(self.exception_queue_item(
                    severity="critical",
                    system="inventory",
                    account="",
                    asset="",
                    reason="inventory_shortfall",
                    next_action="create_or_import_schedule_safe_inventory",
                    count=shortfall,
                ))
            for surface, row in (creator.get("surfaceShortfalls") or {}).items():
                if isinstance(row, dict) and int(row.get("shortfall") or 0) > 0:
                    exceptions.append(self.exception_queue_item(
                        severity="high",
                        system="surface_inventory",
                        account="",
                        asset="",
                        reason=f"{self._normalize_content_surface(surface)}_inventory_shortfall",
                        next_action="fill_surface_inventory_buffer",
                        count=int(row.get("shortfall") or 0),
                    ))
        for blocker in readiness.get("blockers") or []:
            exceptions.append(self.exception_queue_item(
                severity=self.exception_severity_for_reason(str(blocker)),
                system="execution_readiness",
                account="",
                asset="",
                reason=str(blocker),
                next_action=self.exception_next_action(str(blocker)),
            ))
        for source, system in ((publishability_report or {}, "publishability"), (surface_readiness_report or {}, "surface_readiness")):
            for item in source.get("assets") or source.get("items") or []:
                if not isinstance(item, dict):
                    continue
                for reason in item.get("blockingReasons") or item.get("failureReasons") or []:
                    exceptions.append(self.exception_queue_item(
                        severity=self.exception_severity_for_reason(str(reason)),
                        system=system,
                        account=item.get("accountId") or "",
                        asset=item.get("assetId") or item.get("renderedAssetId") or "",
                        reason=str(reason),
                        next_action=self.exception_next_action(str(reason)),
                    ))
        return {
            "schema": "creator_os.exception_queue_report.v1",
            "exceptionCount": len(exceptions),
            "exceptions": exceptions,
            "wouldWrite": False,
        }

    def exception_queue_summary(self, **kwargs: Any) -> dict[str, Any]:
        report = self.exception_queue_report(**kwargs)
        by_severity: dict[str, int] = {}
        by_system: dict[str, int] = {}
        by_owner: dict[str, int] = {}
        for item in report.get("exceptions") or []:
            severity = str(item.get("severity") or "low")
            system = str(item.get("system") or "unknown")
            owner = str(item.get("owner") or "operator")
            by_severity[severity] = by_severity.get(severity, 0) + 1
            by_system[system] = by_system.get(system, 0) + 1
            by_owner[owner] = by_owner.get(owner, 0) + 1
        return {
            "schema": "creator_os.exception_queue_summary.v1",
            "exceptionCount": int(report.get("exceptionCount") or 0),
            "bySeverity": dict(sorted(by_severity.items())),
            "bySystem": dict(sorted(by_system.items())),
            "byOwner": dict(sorted(by_owner.items())),
            "largestQueue": max(by_system.items(), key=lambda item: item[1])[0] if by_system else "",
            "wouldWrite": False,
        }

    def exception_queue_priority_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.exception_queue_report(**kwargs)
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        exceptions = sorted(
            report.get("exceptions") or [],
            key=lambda item: (
                rank.get(str(item.get("severity") or "low"), 9),
                -int(item.get("blockingInventory") or 0),
                -int(item.get("blockingAccounts") or 0),
                str(item.get("exceptionId") or ""),
            ),
        )
        return {
            "schema": "creator_os.exception_queue_priority_report.v1",
            "exceptionCount": len(exceptions),
            "exceptions": exceptions,
            "topPriority": exceptions[0] if exceptions else None,
            "wouldWrite": False,
        }

    def exception_queue_owner_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.exception_queue_report(**kwargs)
        grouped: dict[str, dict[str, Any]] = {}
        for item in report.get("exceptions") or []:
            owner = str(item.get("owner") or "operator")
            row = grouped.setdefault(owner, {
                "owner": owner,
                "exceptionCount": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "estimatedResolutionMinutes": 0,
                "blockingAccounts": 0,
                "blockingInventory": 0,
                "nextActions": [],
                "wouldWrite": False,
            })
            severity = str(item.get("severity") or "low")
            row["exceptionCount"] += 1
            if severity in {"critical", "high", "medium", "low"}:
                row[severity] += 1
            row["estimatedResolutionMinutes"] += int(item.get("estimatedResolutionMinutes") or 0)
            row["blockingAccounts"] += int(item.get("blockingAccounts") or 0)
            row["blockingInventory"] += int(item.get("blockingInventory") or 0)
            action = str(item.get("nextAction") or "")
            if action and action not in row["nextActions"]:
                row["nextActions"].append(action)
        owners = sorted(grouped.values(), key=lambda row: (-int(row["critical"]), -int(row["high"]), -int(row["exceptionCount"]), row["owner"]))
        return {
            "schema": "creator_os.exception_queue_owner_report.v1",
            "owners": owners,
            "wouldWrite": False,
        }

    def exception_queue_item(
        self,
        *,
        severity: str,
        system: str,
        account: Any,
        asset: Any,
        reason: str,
        next_action: str,
        count: int | None = None,
    ) -> dict[str, Any]:
        category = self.exception_category_for_reason(reason, system)
        owner = self.exception_owner_for_category(category, system)
        blocking_accounts = 1 if account else 0
        blocking_inventory = int(count or 0) if "inventory" in category else 0
        payload = {
            "exceptionId": self._verification_id("exception", severity, system, account, asset, reason, count or 0),
            "severity": severity,
            "owner": owner,
            "system": system,
            "category": category,
            "account": str(account or ""),
            "accountId": str(account or ""),
            "asset": str(asset or ""),
            "assetId": str(asset or ""),
            "reason": reason,
            "nextAction": next_action,
            "repairable": self.exception_repairable(reason),
            "estimatedResolutionMinutes": self.exception_resolution_minutes(reason, count=count),
            "blockingAccounts": blocking_accounts,
            "blockingInventory": blocking_inventory,
            "wouldWrite": False,
        }
        if count is not None:
            payload["count"] = count
        return payload

    def exception_severity_for_reason(self, reason: str) -> str:
        lowered = reason.lower()
        if any(token in lowered for token in ("missed_dispatch", "handoff", "publishability", "embedded_audio", "inventory_shortfall")):
            return "critical"
        if any(token in lowered for token in ("caption", "restriction", "account", "quarantine")):
            return "high"
        if any(token in lowered for token in ("duplicate", "cooldown", "readiness")):
            return "medium"
        return "low"

    def exception_next_action(self, reason: str) -> str:
        lowered = reason.lower()
        if "caption" in lowered:
            return "repair_caption_contract"
        if "audio" in lowered:
            return "repair_or_replace_audio_valid_asset"
        if "handoff" in lowered:
            return "rebuild_handoff_manifest_preview"
        if "inventory" in lowered:
            return "fill_validated_inventory_buffer"
        if "restriction" in lowered or "account" in lowered:
            return "resolve_account_health_blocker"
        if "missed_dispatch" in lowered:
            return "resolve_missed_dispatch_before_new_schedule"
        return "inspect_and_route_exception"

    def exception_category_for_reason(self, reason: str, system: str) -> str:
        lowered = f"{system} {reason}".lower()
        if "inventory" in lowered:
            return "inventory"
        if "discoverability" in lowered or "caption" in lowered or "dm" in lowered or "link" in lowered:
            return "discoverability"
        if "publishability" in lowered or "handoff" in lowered or "metadata" in lowered:
            return "publishability"
        if "audio" in lowered:
            return "audio"
        if "restriction" in lowered or "account" in lowered or "reauth" in lowered:
            return "account_health"
        if "recommendation" in lowered:
            return "recommendation_eligibility"
        if "schedule" in lowered or "dispatch" in lowered:
            return "schedule_blocker"
        return "manual_review"

    def exception_owner_for_category(self, category: str, system: str) -> str:
        if category in {"inventory", "discoverability", "publishability", "audio"}:
            return "campaign_factory_operator"
        if category in {"account_health", "schedule_blocker"}:
            return "threadsdashboard_operator"
        if category == "recommendation_eligibility":
            return "creative_kb_operator"
        if system == "surface_readiness":
            return "campaign_factory_operator"
        return "operator"

    def exception_repairable(self, reason: str) -> bool:
        lowered = reason.lower()
        if "duplicate_risk" in lowered or "manual_review_rejection" in lowered:
            return False
        return True

    def exception_resolution_minutes(self, reason: str, *, count: int | None = None) -> int:
        lowered = reason.lower()
        base = 10
        if "inventory" in lowered:
            base = 30
        elif "audio" in lowered:
            base = 20
        elif "caption" in lowered or "discoverability" in lowered:
            base = 12
        elif "account" in lowered or "restriction" in lowered or "reauth" in lowered:
            base = 15
        elif "handoff" in lowered or "metadata" in lowered:
            base = 8
        return base + min(120, max(0, int(count or 0)) // 10)

    def _verification_id(self, prefix: str, *parts: Any) -> str:
        digest = hashlib.sha256(":".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{digest}"
