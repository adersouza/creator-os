from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from pipeline_contracts import validate_account_eligibility_decision

SCHEMA = "campaign_factory.account_eligibility_decision.v1"
TRIAL_CAPABILITY_AUTHORIZATIONS = {"operator_canary"}
TRIAL_REEL_PUBLISH_SCOPES = {
    "instagram_content_publish",
    "instagram_business_content_publish",
}


class AccountEligibilityError(ValueError):
    def __init__(self, decision: dict[str, Any]) -> None:
        self.decision = decision
        super().__init__(f"account eligibility blocked: {decision['decisionReason']}")


def evaluate_account_eligibility(
    conn: sqlite3.Connection,
    *,
    account_id: str | None = None,
    instagram_account_id: str | None = None,
    surface: str = "regular_reel",
    requires_trial_capability: bool = False,
    authorization: str | None = None,
    planned_at: str | None = None,
    health_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the one Campaign policy decision for an account and surface.

    ThreadsDashboard remains the source of account/OAuth/Trial facts. Campaign
    owns the policy decision. Missing projection evidence may be used for a
    supervised draft, but never as proof of Trial Reel eligibility.
    """

    normalized_authorization = str(authorization or "").strip().lower() or None
    if (
        normalized_authorization
        and normalized_authorization not in TRIAL_CAPABILITY_AUTHORIZATIONS
    ):
        allowed = ", ".join(sorted(TRIAL_CAPABILITY_AUTHORIZATIONS))
        raise ValueError(f"trial capability authorization must be one of: {allowed}")

    local_row = _account_row(conn, "id", account_id)
    external_row = _account_row(conn, "external_id", instagram_account_id)
    if local_row and external_row and local_row["id"] != external_row["id"]:
        raise ValueError(
            "account_id and instagram_account_id resolve to different accounts"
        )
    row = local_row or external_row
    requested_surface = _normalize_surface(surface)
    scopes = _json_list(row.get("oauth_granted_scopes_json")) if row else None
    trial_status = str((row or {}).get("trial_reels_capability") or "unknown").lower()
    if trial_status not in {"unknown", "eligible", "denied"}:
        trial_status = "unknown"

    projected_active = _nullable_bool((row or {}).get("threadsdash_is_active"))
    needs_reauth = _nullable_bool((row or {}).get("threadsdash_needs_reauth"))
    projected_status = str((row or {}).get("threadsdash_status") or "unknown").lower()
    health = health_decision if isinstance(health_decision, dict) else {}
    health_blockers = [str(item) for item in health.get("blockers") or []]
    health_warnings = [str(item) for item in health.get("warnings") or []]
    health_state = str(health.get("state") or "unknown").lower()
    if health_state not in {"safe", "warming", "blocked", "unknown"}:
        health_state = "unknown"

    cadence = _cadence_evidence(
        conn,
        row=row,
        account_id=account_id,
        instagram_account_id=instagram_account_id,
        surface=requested_surface,
        planned_at=planned_at,
        health=health,
    )
    decision_reason = "account_eligible"
    operator_action: str | None = None
    allowed = True

    if row is None:
        if requires_trial_capability:
            allowed = False
            decision_reason = "account_projection_missing"
            operator_action = "sync_threadsdashboard_account_projection"
        elif account_id or instagram_account_id:
            decision_reason = "account_projection_missing_supervised_draft_only"
            operator_action = "sync_threadsdashboard_account_projection"
        else:
            decision_reason = "unassigned_supervised_draft"
            operator_action = "assign_account_before_export"
    elif projected_active is False:
        allowed = False
        decision_reason = "account_inactive"
        operator_action = "reactivate_account_in_threadsdashboard"
    elif needs_reauth is True:
        allowed = False
        decision_reason = "account_reauth_required"
        operator_action = "reconnect_account_in_threadsdashboard"
    elif any(
        token in projected_status
        for token in ("blocked", "restricted", "disabled", "reauth")
    ):
        allowed = False
        decision_reason = "account_restricted"
        operator_action = "resolve_account_restriction_in_threadsdashboard"
    elif health_state == "blocked" or health_blockers:
        allowed = False
        decision_reason = (
            health_blockers[0] if health_blockers else "account_health_blocked"
        )
        operator_action = "resolve_account_health_blocker"
    elif requires_trial_capability:
        if scopes is None:
            allowed = False
            decision_reason = "trial_oauth_scope_evidence_missing"
            operator_action = "reconnect_account_and_record_oauth_scopes"
        elif not (set(scopes) & TRIAL_REEL_PUBLISH_SCOPES):
            allowed = False
            decision_reason = "trial_publish_scope_missing"
            operator_action = "reconnect_account_with_instagram_publish_scope"
        elif trial_status == "denied":
            allowed = False
            decision_reason = "trial_capability_denied"
            operator_action = "use_regular_reel_or_reconnect_account"
        elif trial_status == "eligible":
            decision_reason = "trial_capability_eligible"
        elif normalized_authorization == "operator_canary":
            decision_reason = "trial_capability_operator_canary"
        else:
            allowed = False
            decision_reason = "trial_capability_unknown_requires_operator_canary"
            operator_action = "authorize_one_bounded_trial_canary"

    evidence_sources = ["campaign_factory.accounts"] if row else []
    if row and any(
        row.get(name) is not None
        for name in (
            "threadsdash_is_active",
            "threadsdash_status",
            "threadsdash_needs_reauth",
            "oauth_granted_scopes_json",
            "trial_reels_capability_checked_at",
        )
    ):
        evidence_sources.append("threadsdashboard.instagram_accounts")
    if health:
        evidence_sources.append("creator_os.account_health_report.v1")

    decision = {
        "schema": SCHEMA,
        "allowed": allowed,
        "decisionReason": decision_reason,
        "operatorAction": operator_action,
        "requestedSurface": requested_surface,
        "account": {
            "accountId": row.get("id") if row else account_id,
            "instagramAccountId": (
                row.get("external_id") if row else instagram_account_id
            ),
            "handle": row.get("handle") if row else None,
            "active": projected_active,
            "status": projected_status,
            "needsReauth": needs_reauth,
            "syncCohort": (row or {}).get("threadsdash_sync_cohort"),
            "projectionObservedAt": (row or {}).get(
                "threadsdash_projection_observed_at"
            ),
        },
        "oauth": {
            "grantedScopes": scopes,
            "verifiedAt": (row or {}).get("oauth_scopes_verified_at"),
        },
        "trial": {
            "required": bool(requires_trial_capability),
            "capability": trial_status,
            "checkedAt": (row or {}).get("trial_reels_capability_checked_at"),
            "reason": (row or {}).get("trial_reels_capability_reason"),
            "authorization": normalized_authorization,
        },
        "health": {
            "state": health_state,
            "warmingStage": health.get("warmingStage"),
            "blockers": health_blockers,
            "warnings": health_warnings,
        },
        "cadence": cadence,
        "evidence": {
            "sources": evidence_sources,
            "factsOwner": "threadsdashboard",
            "policyOwner": "campaign_factory",
        },
    }
    validate_account_eligibility_decision(decision)
    return decision


def enforce_account_eligibility(
    conn: sqlite3.Connection, **kwargs: Any
) -> dict[str, Any]:
    decision = evaluate_account_eligibility(conn, **kwargs)
    if not decision["allowed"]:
        raise AccountEligibilityError(decision)
    return decision


def _account_row(
    conn: sqlite3.Connection, column: str, value: str | None
) -> dict[str, Any] | None:
    if not value:
        return None
    row = conn.execute(
        f"SELECT * FROM accounts WHERE {column} = ?", (value,)
    ).fetchone()
    return dict(row) if row else None


def _normalize_surface(value: str | None) -> str:
    normalized = str(value or "regular_reel").strip().lower().replace("-", "_")
    aliases = {
        "reel": "regular_reel",
        "regular": "regular_reel",
        "trial": "trial_reel",
        "trial_reels": "trial_reel",
        "stories": "story",
        "cta_story": "story_cta",
        "single_image": "feed_single",
        "feed_image": "feed_single",
        "carousel": "feed_carousel",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {
        "regular_reel",
        "trial_reel",
        "story",
        "story_cta",
        "feed_single",
        "feed_carousel",
    }:
        return "regular_reel"
    return normalized


def _json_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return sorted({str(item) for item in value if str(item).strip()})
    if not isinstance(value, str):
        return None
    import json

    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None
    return sorted({str(item) for item in parsed if str(item).strip()})


def _nullable_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _cadence_evidence(
    conn: sqlite3.Connection,
    *,
    row: dict[str, Any] | None,
    account_id: str | None,
    instagram_account_id: str | None,
    surface: str,
    planned_at: str | None,
    health: dict[str, Any],
) -> dict[str, Any]:
    destination = str(
        (row or {}).get("id")
        or (row or {}).get("external_id")
        or account_id
        or instagram_account_id
        or ""
    )
    content_surface = "reel" if surface in {"regular_reel", "trial_reel"} else surface
    requirement = None
    if destination:
        requirement_row = conn.execute(
            """
            SELECT max_per_day, min_gap_hours
            FROM account_content_requirements
            WHERE active = 1 AND content_surface = ?
              AND account_id = ?
            LIMIT 1
            """,
            (content_surface, (row or {}).get("id") or account_id),
        ).fetchone()
        requirement = dict(requirement_row) if requirement_row else None
    planned = _parse_time(planned_at)
    scheduled_count = 0
    if destination and planned:
        day = planned.date().isoformat()
        scheduled_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM distribution_plans
                WHERE COALESCE(NULLIF(instagram_account_id, ''), account_id) IN (?, ?)
                  AND substr(planned_window_start, 1, 10) = ?
                """,
                (
                    str((row or {}).get("id") or account_id or ""),
                    str((row or {}).get("external_id") or instagram_account_id or ""),
                    day,
                ),
            ).fetchone()[0]
            or 0
        )
    max_per_day = int((requirement or {}).get("max_per_day") or 1)
    return {
        "warmingStage": health.get("warmingStage"),
        "plannedAt": planned.isoformat() if planned else None,
        "scheduledOnDay": scheduled_count if planned else None,
        "maxPerDay": max_per_day,
        "minGapHours": int((requirement or {}).get("min_gap_hours") or 4),
        "withinDailyLimit": (
            scheduled_count < max_per_day if planned and destination else None
        ),
        "source": (
            "account_content_requirements" if requirement else "campaign_default"
        ),
    }
