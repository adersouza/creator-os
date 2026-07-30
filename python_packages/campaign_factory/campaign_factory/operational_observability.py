from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class OperationalObservabilityRepository:
    """Read-only operational truth assembled from canonical Campaign evidence."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now

    def report(
        self,
        *,
        stale_after_minutes: int = 60,
        activity_limit: int = 200,
    ) -> dict[str, Any]:
        if stale_after_minutes < 1:
            raise ValueError("stale_after_minutes must be positive")
        now = _parse_time(self._utc_now())
        if now is None:
            raise RuntimeError("utc_now returned an invalid timestamp")
        cutoff = now - timedelta(minutes=stale_after_minutes)
        observations: list[dict[str, Any]] = []
        observations.extend(self._pipeline_jobs(cutoff))
        observations.extend(self._orchestrator_runs(cutoff))
        observations.extend(self._provider_authorizations(cutoff))
        observations.extend(self._cost_events())
        observations.extend(self._incidents())
        observations.extend(self._activity_events(activity_limit))
        manual_holds = [
            item
            for item in observations
            if item["manualHold"] or item["state"] == "manual_hold"
        ]
        stale = [item for item in observations if item["stale"]]
        blockers = [
            item
            for item in observations
            if item["severity"] in {"high", "critical"}
            and item["state"] not in {"closed", "succeeded", "completed", "reconciled"}
        ]
        ambiguous = [
            item
            for item in observations
            if item.get("effectState") in {"AMBIGUOUS", "ambiguous", "unknown"}
            and item["state"] not in {"closed", "reconciled"}
        ]
        if manual_holds or blockers or ambiguous:
            health = "blocked"
            reason = "manual_hold_or_unreconciled_high_risk_evidence"
        elif stale:
            health = "degraded"
            reason = "stale_operational_evidence"
        elif not observations:
            health = "unknown"
            reason = "no_operational_evidence"
        else:
            health = "healthy"
            reason = "fresh_evidence_and_no_open_blocker"
        runtime = self.runtime_truth(
            stale_after_minutes=stale_after_minutes,
            activity_limit=activity_limit,
        )
        if runtime["loaded"] and runtime["executing"] is not True:
            if health == "healthy":
                health = "degraded"
            reason = "runtime_loaded_without_fresh_execution_evidence"
        return {
            "schema": "campaign_factory.operational_observability.v1",
            "observedAt": self._utc_now(),
            "health": health,
            "healthReason": reason,
            "freshnessPolicyMinutes": stale_after_minutes,
            "counts": {
                "observations": len(observations),
                "stale": len(stale),
                "manualHolds": len(manual_holds),
                "blockers": len(blockers),
                "ambiguousExternalEffects": len(ambiguous),
            },
            "runtime": runtime,
            "observations": observations,
        }

    def runtime_truth(
        self, *, stale_after_minutes: int = 60, activity_limit: int = 200
    ) -> dict[str, Any]:
        now = _parse_time(self._utc_now())
        if now is None:
            raise RuntimeError("utc_now returned an invalid timestamp")
        cutoff = now - timedelta(minutes=stale_after_minutes)
        rows = self.conn.execute(
            """
            SELECT id, event_type, status, message, metadata_json, created_at
            FROM activity_events
            WHERE event_type IN (
              'launch_agent_loaded', 'runtime_execution_started',
              'runtime_execution_heartbeat', 'runtime_execution_stopped',
              'runtime_promotion_verified'
            )
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (activity_limit,),
        ).fetchall()
        loaded = any(row["event_type"] == "launch_agent_loaded" for row in rows)
        execution_rows = [
            row
            for row in rows
            if row["event_type"]
            in {"runtime_execution_started", "runtime_execution_heartbeat"}
        ]
        newest_execution = execution_rows[0] if execution_rows else None
        stopped = next(
            (row for row in rows if row["event_type"] == "runtime_execution_stopped"),
            None,
        )
        execution_time = (
            _parse_time(str(newest_execution["created_at"]))
            if newest_execution is not None
            else None
        )
        stopped_time = (
            _parse_time(str(stopped["created_at"])) if stopped is not None else None
        )
        executing = bool(
            execution_time
            and execution_time >= cutoff
            and (stopped_time is None or execution_time > stopped_time)
        )
        return {
            "schema": "campaign_factory.runtime_execution_truth.v1",
            "loaded": loaded,
            "executing": executing,
            "executionEvidence": dict(newest_execution) if newest_execution else None,
            "fresh": bool(execution_time and execution_time >= cutoff),
            "warning": (
                "A loaded LaunchAgent is configuration evidence, not execution proof."
                if loaded and not executing
                else None
            ),
        }

    def _pipeline_jobs(self, cutoff: datetime) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, campaign_id, status, effect_state, recovery_policy,
                   reconciliation_classification, error, created_at, updated_at
            FROM pipeline_jobs ORDER BY updated_at DESC
            """
        ).fetchall()
        return [
            self._item(
                source_type="pipeline_job",
                source_id=str(row["id"]),
                state=str(row["status"]),
                observed_at=str(row["updated_at"]),
                campaign_id=row["campaign_id"],
                severity="high" if row["status"] == "failed" else "medium",
                owner="campaign_factory",
                action=(
                    "reconcile external effect"
                    if row["effect_state"] == "AMBIGUOUS"
                    else str(row["recovery_policy"])
                ),
                stale=(
                    row["status"] in {"queued", "running"}
                    and (_parse_time(str(row["updated_at"])) or cutoff) < cutoff
                ),
                manual_hold=False,
                evidence={
                    "effectState": row["effect_state"],
                    "reconciliationClassification": row[
                        "reconciliation_classification"
                    ],
                    "error": row["error"],
                },
                effect_state=str(row["effect_state"]),
            )
            for row in rows
        ]

    def _orchestrator_runs(self, cutoff: datetime) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, status, stop_reason, next_run_reason, created_at, updated_at
            FROM daily_orchestrator_runs ORDER BY updated_at DESC
            """
        ).fetchall()
        return [
            self._item(
                source_type="daily_orchestrator_run",
                source_id=str(row["id"]),
                state=str(row["status"]),
                observed_at=str(row["updated_at"]),
                campaign_id=None,
                severity="medium" if row["status"] == "blocked" else "info",
                owner="campaign_factory",
                action=str(row["next_run_reason"]),
                stale=(
                    row["status"] in {"planned", "running"}
                    and (_parse_time(str(row["updated_at"])) or cutoff) < cutoff
                ),
                manual_hold=False,
                evidence={"stopReason": row["stop_reason"]},
            )
            for row in rows
        ]

    def _provider_authorizations(self, cutoff: datetime) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT authorization_id, campaign_id, creator_id, status, expires_at,
                   issued_at, scope_json
            FROM provider_spend_authorizations ORDER BY issued_at DESC
            """
        ).fetchall()
        return [
            self._item(
                source_type="provider_authorization",
                source_id=str(row["authorization_id"]),
                state=str(row["status"]),
                observed_at=str(row["issued_at"]),
                campaign_id=row["campaign_id"],
                model_id=row["creator_id"],
                severity="medium",
                owner="campaign_factory",
                action=(
                    "reconcile or cancel expired authorization"
                    if row["status"] == "authorized"
                    else "none"
                ),
                stale=(
                    row["status"] == "authorized"
                    and (_parse_time(str(row["expires_at"])) or cutoff) < cutoff
                ),
                manual_hold=False,
                evidence={"scope": json.loads(str(row["scope_json"]))},
            )
            for row in rows
        ]

    def _cost_events(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, campaign_id, provider, operation, cost_state,
                   usd_cost_state, unknown_reason, metadata_json, created_at
            FROM ai_cost_events ORDER BY created_at DESC
            """
        ).fetchall()
        return [
            self._item(
                source_type="cost_event",
                source_id=str(row["id"]),
                state=str(row["cost_state"]),
                observed_at=str(row["created_at"]),
                campaign_id=row["campaign_id"],
                severity="high" if row["cost_state"] == "unknown" else "info",
                owner="campaign_factory",
                action=(
                    "reconcile provider cost"
                    if row["cost_state"] == "unknown"
                    or row["usd_cost_state"] == "unknown"
                    else "none"
                ),
                stale=False,
                manual_hold=False,
                evidence={
                    "provider": row["provider"],
                    "operation": row["operation"],
                    "unknownReason": row["unknown_reason"],
                    "metadata": json.loads(str(row["metadata_json"] or "{}")),
                },
            )
            for row in rows
        ]

    def _incidents(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, state, severity, domain_owner, model_id, campaign_id,
                   external_effect_state, owner, next_action, updated_at
            FROM incident_records ORDER BY updated_at DESC
            """
        ).fetchall()
        return [
            self._item(
                source_type="incident",
                source_id=str(row["id"]),
                state=str(row["state"]),
                observed_at=str(row["updated_at"]),
                campaign_id=row["campaign_id"],
                model_id=row["model_id"],
                severity=str(row["severity"]),
                owner=str(row["owner"]),
                action=str(row["next_action"]),
                stale=False,
                manual_hold=row["state"] == "manual_hold",
                evidence={"domainOwner": row["domain_owner"]},
                effect_state=str(row["external_effect_state"]),
            )
            for row in rows
        ]

    def _activity_events(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, event_type, campaign_id, status, message, metadata_json,
                   created_at FROM activity_events
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            self._item(
                source_type="activity_event",
                source_id=str(row["id"]),
                state=str(row["status"]),
                observed_at=str(row["created_at"]),
                campaign_id=row["campaign_id"],
                severity=("high" if row["status"] in {"error", "failed"} else "info"),
                owner="campaign_factory",
                action="inspect linked evidence",
                stale=False,
                manual_hold=row["event_type"] == "manual_hold",
                evidence={
                    "eventType": row["event_type"],
                    "message": row["message"],
                    "metadata": json.loads(str(row["metadata_json"] or "{}")),
                },
            )
            for row in rows
        ]

    @staticmethod
    def _item(
        *,
        source_type: str,
        source_id: str,
        state: str,
        observed_at: str,
        campaign_id: Any,
        severity: str,
        owner: str,
        action: str,
        stale: bool,
        manual_hold: bool,
        evidence: dict[str, Any],
        model_id: Any = None,
        effect_state: str | None = None,
    ) -> dict[str, Any]:
        return {
            "sourceType": source_type,
            "sourceId": source_id,
            "state": state,
            "observedAt": observed_at,
            "modelId": model_id,
            "campaignId": campaign_id,
            "severity": severity,
            "owner": owner,
            "nextAction": action,
            "stale": stale,
            "fresh": not stale,
            "manualHold": manual_hold,
            "effectState": effect_state,
            "evidence": evidence,
        }
