from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

ReadinessSeverity = Literal["blocker", "warning", "info"]


class ReadinessFindingPayload(TypedDict):
    code: str
    severity: ReadinessSeverity
    owner: str
    operatorAction: str
    sourceCheck: str
    affectedAssetId: str | None
    affectedAccountId: str | None
    affectedPostId: str | None
    evidence: dict[str, Any]
    retryable: bool


@dataclass(frozen=True, slots=True)
class ReadinessFinding:
    """One stable readiness result shared by Campaign Factory surfaces."""

    code: str
    severity: ReadinessSeverity
    owner: str
    operator_action: str
    source_check: str
    affected_asset_id: str | None
    affected_account_id: str | None
    affected_post_id: str | None
    evidence: dict[str, Any]
    retryable: bool

    def __post_init__(self) -> None:
        for field_name, value in (
            ("code", self.code),
            ("owner", self.owner),
            ("operator_action", self.operator_action),
            ("source_check", self.source_check),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.severity not in {"blocker", "warning", "info"}:
            raise ValueError(f"unsupported readiness severity: {self.severity}")
        if not isinstance(self.evidence, dict):
            raise TypeError("evidence must be a dictionary")

    def to_payload(self) -> ReadinessFindingPayload:
        return {
            "code": self.code,
            "severity": self.severity,
            "owner": self.owner,
            "operatorAction": self.operator_action,
            "sourceCheck": self.source_check,
            "affectedAssetId": self.affected_asset_id,
            "affectedAccountId": self.affected_account_id,
            "affectedPostId": self.affected_post_id,
            "evidence": dict(self.evidence),
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class _FindingSpec:
    owner: str
    operator_action: str
    explanation: str
    retryable: bool = True


# Execution readiness previously carried this policy in a private module-local
# dictionary. It lives here so every readiness producer resolves the same code
# to the same owner and operator action.
_FINDING_SPECS: dict[str, _FindingSpec] = {
    "insufficient_safe_accounts": _FindingSpec(
        "account_capacity",
        "repair_or_wait_for_account_health",
        "Not enough accounts are safe for this requested batch.",
    ),
    "missed_dispatches_unresolved": _FindingSpec(
        "publish_runtime",
        "resolve_missed_dispatches_before_scheduling",
        "ThreadsDashboard has unresolved missed dispatches.",
    ),
    "insufficient_schedule_safe_drafts": _FindingSpec(
        "draft_inventory",
        "create_or_export_schedule_safe_drafts",
        "Not enough drafts passed pre-schedule safety checks.",
    ),
    "missing_handoff_manifest": _FindingSpec(
        "draft_contract",
        "create_or_export_schedule_safe_drafts",
        "A draft is missing the Campaign Factory handoff manifest.",
    ),
    "platform_draft_not_validated": _FindingSpec(
        "draft_contract",
        "revalidate_threadsdashboard_drafts",
        "A draft has not passed platform draft validation.",
    ),
    "quarantined_draft_present": _FindingSpec(
        "draft_contract",
        "remove_or_repair_quarantined_draft",
        "A quarantined draft is still in the candidate batch.",
    ),
    "publishability_failed_draft_present": _FindingSpec(
        "draft_contract",
        "repair_publishability_blockers",
        "A draft failed Campaign Factory publishability checks.",
    ),
    "missing_campaign_factory_asset_id": _FindingSpec(
        "draft_contract",
        "regenerate_draft_handoff_payload",
        "A draft is missing its Campaign Factory asset id.",
    ),
    "missing_campaign_factory_distribution_plan_id": _FindingSpec(
        "draft_contract",
        "rerun_campaign_schedule_plan",
        "A draft is missing its distribution plan id.",
    ),
    "embedded_audio_invalid": _FindingSpec(
        "audio",
        "select_or_verify_native_audio",
        "A draft has invalid embedded audio metadata.",
    ),
    "native_audio_proof_missing": _FindingSpec(
        "audio",
        "select_or_verify_native_audio",
        "A draft has selected or recommended native audio without verified platform proof.",
    ),
    "missing_instagram_post_caption": _FindingSpec(
        "caption",
        "repair_caption_contract",
        "A draft is missing the Instagram post caption.",
    ),
    "missing_burned_captions": _FindingSpec(
        "caption",
        "repair_caption_contract",
        "A draft is missing burned-caption proof.",
    ),
    "missing_burned_caption_text": _FindingSpec(
        "caption",
        "repair_caption_contract",
        "A draft is missing burned-caption text evidence.",
    ),
    "missing_caption_hash": _FindingSpec(
        "caption",
        "repair_caption_contract",
        "A draft is missing caption hash proof.",
    ),
    "missing_caption_outcome_context": _FindingSpec(
        "caption",
        "repair_caption_contract",
        "A draft is missing caption outcome context.",
    ),
    "caption_placement_qc_failed": _FindingSpec(
        "caption",
        "repair_caption_placement",
        "A draft failed caption placement quality control.",
    ),
    "instagram_post_caption_quality_failed": _FindingSpec(
        "caption",
        "repair_caption_contract",
        "A draft failed Instagram post caption quality checks.",
    ),
    "missing_content_fingerprint": _FindingSpec(
        "draft_contract",
        "regenerate_draft_handoff_payload",
        "A draft is missing content fingerprint proof.",
    ),
    "not_approved": _FindingSpec(
        "draft_contract",
        "route_asset_through_review",
        "A draft asset is not approved for scheduling.",
    ),
    "readiness_failed": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "A draft failed upstream readiness checks.",
    ),
    "wrong_visual": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "A draft failed expected visual verification.",
    ),
    "visual_qc_failed": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "A draft failed visual quality control.",
    ),
    "visual_qc_unavailable": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "A draft is missing required visual quality control proof.",
    ),
    "identity_verification_failed": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "A draft failed identity verification.",
    ),
    "identity_verification_unavailable": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "A draft is missing required identity verification proof.",
    ),
    "schedule_plan_not_ready": _FindingSpec(
        "schedule_plan",
        "rerun_campaign_schedule_plan",
        "The schedule plan is not ready.",
    ),
    "insufficient_schedule_plan_items": _FindingSpec(
        "schedule_plan",
        "rerun_campaign_schedule_plan",
        "The schedule plan has too few items for the requested batch.",
    ),
    "variant_cooldown_violation": _FindingSpec(
        "schedule_plan",
        "rerun_campaign_schedule_plan",
        "The schedule plan violates variant cooldown rules.",
    ),
    "duplicate_schedule_risk": _FindingSpec(
        "schedule_plan",
        "rerun_campaign_schedule_plan",
        "The schedule plan has duplicate-posting risk.",
    ),
    "time_plan_not_ready": _FindingSpec(
        "time_plan",
        "rerun_campaign_schedule_time_plan",
        "The time plan is not ready.",
    ),
    "insufficient_time_plan_items": _FindingSpec(
        "time_plan",
        "rerun_campaign_schedule_time_plan",
        "The time plan has too few slots for the requested batch.",
    ),
    "timestamp_collision": _FindingSpec(
        "time_plan",
        "rerun_campaign_schedule_time_plan",
        "Two scheduled items share the same timestamp.",
    ),
    "account_link_sharing_restricted": _FindingSpec(
        "account_health",
        "resolve_account_health_blocker",
        "An account has link sharing restrictions.",
    ),
    "recommendation_not_eligible": _FindingSpec(
        "account_health",
        "resolve_account_health_blocker",
        "An account is not recommendation-eligible.",
    ),
    "account_warming_cadence_exceeded": _FindingSpec(
        "account_health",
        "wait_or_choose_different_account",
        "A warming account would exceed its cadence.",
    ),
    "creative_risk_score_exceeded": _FindingSpec(
        "creative_safety",
        "repair_or_replace_creative",
        "Creative risk is above the allowed threshold.",
    ),
    "similarity_budget_exceeded": _FindingSpec(
        "creative_safety",
        "run_contentforge_variant_plan",
        "Similarity budget is exhausted for the candidate batch.",
    ),
    "scheduled_post_publish_route_missing": _FindingSpec(
        "publish_runtime",
        "verify_threadsdash_runtime",
        "ThreadsDashboard publish route could not be verified.",
    ),
    "campaign_schedule_recovery_route_missing": _FindingSpec(
        "publish_runtime",
        "verify_threadsdash_runtime",
        "ThreadsDashboard schedule recovery route could not be verified.",
    ),
    "campaign_schedule_recovery_cron_missing": _FindingSpec(
        "publish_runtime",
        "verify_threadsdash_runtime",
        "ThreadsDashboard schedule recovery cron could not be verified.",
    ),
}


def _base_code(code: str) -> str:
    return str(code or "").strip().partition(":")[0]


def _owner_for_code(code: str) -> str:
    base = _base_code(code)
    if any(token in base for token in ("caption", "text")):
        return "caption"
    if "audio" in base:
        return "audio"
    if any(token in base for token in ("account", "oauth", "trial")):
        return "account_health"
    if any(token in base for token in ("schedule", "timestamp", "dispatch")):
        return "schedule_plan"
    if any(token in base for token in ("metric", "tracking", "lineage", "canonical")):
        return "learning_evidence"
    if any(token in base for token in ("duplicate", "reuse", "collision")):
        return "content_uniqueness"
    if any(
        token in base
        for token in (
            "media",
            "render",
            "visual",
            "identity",
            "story",
            "carousel",
            "feed",
            "reel",
            "aspect_ratio",
        )
    ):
        return "creative_safety"
    if any(
        token in base
        for token in ("threadsdash", "supabase", "route", "cron", "usage_check")
    ):
        return "threadsdash"
    if any(
        token in base
        for token in (
            "draft",
            "handoff",
            "manifest",
            "contract",
            "publishability",
            "approved",
            "quarantine",
            "fingerprint",
        )
    ):
        return "draft_contract"
    return "campaign_factory"


_OWNER_ACTIONS = {
    "caption": "repair_caption_contract",
    "audio": "select_or_verify_native_audio",
    "account_health": "resolve_account_health_blocker",
    "schedule_plan": "rerun_campaign_schedule_plan",
    "learning_evidence": "repair_learning_evidence",
    "content_uniqueness": "review_duplicate_risk",
    "creative_safety": "repair_or_replace_creative",
    "threadsdash": "verify_threadsdash_readiness",
    "draft_contract": "regenerate_draft_handoff_payload",
    "campaign_factory": "inspect_readiness_finding",
}


def make_readiness_finding(
    code: str,
    *,
    severity: ReadinessSeverity,
    evidence: dict[str, Any] | None = None,
    owner: str | None = None,
    operator_action: str | None = None,
    source_check: str | None = None,
    affected_asset_id: str | None = None,
    affected_account_id: str | None = None,
    affected_post_id: str | None = None,
    retryable: bool | None = None,
) -> ReadinessFinding:
    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise ValueError("readiness finding code must be non-empty")
    base = _base_code(normalized_code)
    spec = _FINDING_SPECS.get(base)
    resolved_owner = owner or (spec.owner if spec else _owner_for_code(base))
    resolved_action = operator_action or (
        spec.operator_action
        if spec
        else _OWNER_ACTIONS.get(resolved_owner, "inspect_readiness_finding")
    )
    resolved_evidence = dict(evidence or {})
    resolved_source_check = str(
        source_check or resolved_evidence.get("source") or "readiness_finding"
    ).strip()
    resolved_asset_id = affected_asset_id or resolved_evidence.get("renderedAssetId")
    resolved_account_id = affected_account_id or resolved_evidence.get("accountId")
    resolved_post_id = affected_post_id or resolved_evidence.get("postId")
    if spec and "explanation" not in resolved_evidence:
        resolved_evidence["explanation"] = spec.explanation
    source_reason = normalized_code.partition(":")[2]
    if source_reason and "sourceReason" not in resolved_evidence:
        resolved_evidence["sourceReason"] = source_reason
    return ReadinessFinding(
        code=normalized_code,
        severity=severity,
        owner=resolved_owner,
        operator_action=resolved_action,
        source_check=resolved_source_check,
        affected_asset_id=_optional_identifier(resolved_asset_id),
        affected_account_id=_optional_identifier(resolved_account_id),
        affected_post_id=_optional_identifier(resolved_post_id),
        evidence=resolved_evidence,
        retryable=spec.retryable
        if retryable is None and spec
        else bool(True if retryable is None else retryable),
    )


def readiness_findings_from_codes(
    codes: list[str],
    *,
    severity: ReadinessSeverity,
    evidence: dict[str, Any] | None = None,
    owner: str | None = None,
    operator_action: str | None = None,
    source_check: str | None = None,
    affected_asset_id: str | None = None,
    affected_account_id: str | None = None,
    affected_post_id: str | None = None,
    retryable: bool | None = None,
) -> list[ReadinessFinding]:
    return [
        make_readiness_finding(
            code,
            severity=severity,
            evidence=evidence,
            owner=owner,
            operator_action=operator_action,
            source_check=source_check,
            affected_asset_id=affected_asset_id,
            affected_account_id=affected_account_id,
            affected_post_id=affected_post_id,
            retryable=retryable,
        )
        for code in sorted({str(code).strip() for code in codes if str(code).strip()})
    ]


def dedupe_readiness_findings(
    findings: list[ReadinessFinding],
) -> list[ReadinessFinding]:
    seen: set[
        tuple[str, str, str, str, str, str | None, str | None, str | None, str, bool]
    ] = set()
    unique: list[ReadinessFinding] = []
    for finding in findings:
        key = (
            finding.code,
            finding.severity,
            finding.owner,
            finding.operator_action,
            finding.source_check,
            finding.affected_asset_id,
            finding.affected_account_id,
            finding.affected_post_id,
            json.dumps(finding.evidence, sort_keys=True, default=str),
            finding.retryable,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def _optional_identifier(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def readiness_finding_payloads(
    findings: list[ReadinessFinding],
) -> list[ReadinessFindingPayload]:
    return [finding.to_payload() for finding in dedupe_readiness_findings(findings)]


def readiness_finding_codes(
    findings: list[ReadinessFinding],
    *,
    severity: ReadinessSeverity | None = None,
) -> list[str]:
    return sorted(
        {
            finding.code
            for finding in findings
            if severity is None or finding.severity == severity
        }
    )


def execution_blocker_detail(
    finding: ReadinessFinding,
) -> dict[str, Any]:
    evidence = finding.evidence
    item: dict[str, Any] = {
        "code": finding.code,
        "category": finding.owner,
        "explanation": evidence.get(
            "explanation", "Execution readiness blocked on an unmapped guardrail."
        ),
        "nextAction": finding.operator_action,
    }
    for key in ("sourceReason", "observed", "required"):
        if key in evidence:
            item[key] = evidence[key]
    return item
