from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from .config import Settings

_BLOCKER_GUIDANCE = {
    "insufficient_safe_accounts": (
        "account_capacity",
        "Not enough accounts are safe for this requested batch.",
        "repair_or_wait_for_account_health",
    ),
    "missed_dispatches_unresolved": (
        "publish_runtime",
        "ThreadsDashboard has unresolved missed dispatches.",
        "resolve_missed_dispatches_before_scheduling",
    ),
    "insufficient_schedule_safe_drafts": (
        "draft_inventory",
        "Not enough drafts passed pre-schedule safety checks.",
        "create_or_export_schedule_safe_drafts",
    ),
    "missing_handoff_manifest": (
        "draft_contract",
        "A draft is missing the Campaign Factory handoff manifest.",
        "create_or_export_schedule_safe_drafts",
    ),
    "platform_draft_not_validated": (
        "draft_contract",
        "A draft has not passed platform draft validation.",
        "revalidate_threadsdashboard_drafts",
    ),
    "quarantined_draft_present": (
        "draft_contract",
        "A quarantined draft is still in the candidate batch.",
        "remove_or_repair_quarantined_draft",
    ),
    "publishability_failed_draft_present": (
        "draft_contract",
        "A draft failed Campaign Factory publishability checks.",
        "repair_publishability_blockers",
    ),
    "missing_campaign_factory_asset_id": (
        "draft_contract",
        "A draft is missing its Campaign Factory asset id.",
        "regenerate_draft_handoff_payload",
    ),
    "missing_campaign_factory_distribution_plan_id": (
        "draft_contract",
        "A draft is missing its distribution plan id.",
        "rerun_campaign_schedule_plan",
    ),
    "embedded_audio_invalid": (
        "audio",
        "A draft has invalid embedded audio metadata.",
        "select_or_verify_native_audio",
    ),
    "native_audio_proof_missing": (
        "audio",
        "A draft has selected or recommended native audio without verified platform proof.",
        "select_or_verify_native_audio",
    ),
    "missing_instagram_post_caption": (
        "caption",
        "A draft is missing the Instagram post caption.",
        "repair_caption_contract",
    ),
    "missing_burned_captions": (
        "caption",
        "A draft is missing burned-caption proof.",
        "repair_caption_contract",
    ),
    "missing_burned_caption_text": (
        "caption",
        "A draft is missing burned-caption text evidence.",
        "repair_caption_contract",
    ),
    "missing_caption_hash": (
        "caption",
        "A draft is missing caption hash proof.",
        "repair_caption_contract",
    ),
    "missing_caption_outcome_context": (
        "caption",
        "A draft is missing caption outcome context.",
        "repair_caption_contract",
    ),
    "caption_placement_qc_failed": (
        "caption",
        "A draft failed caption placement quality control.",
        "repair_caption_placement",
    ),
    "instagram_post_caption_quality_failed": (
        "caption",
        "A draft failed Instagram post caption quality checks.",
        "repair_caption_contract",
    ),
    "missing_content_fingerprint": (
        "draft_contract",
        "A draft is missing content fingerprint proof.",
        "regenerate_draft_handoff_payload",
    ),
    "not_approved": (
        "draft_contract",
        "A draft asset is not approved for scheduling.",
        "route_asset_through_review",
    ),
    "readiness_failed": (
        "creative_safety",
        "A draft failed upstream readiness checks.",
        "repair_or_replace_creative",
    ),
    "wrong_visual": (
        "creative_safety",
        "A draft failed expected visual verification.",
        "repair_or_replace_creative",
    ),
    "visual_qc_failed": (
        "creative_safety",
        "A draft failed visual quality control.",
        "repair_or_replace_creative",
    ),
    "visual_qc_unavailable": (
        "creative_safety",
        "A draft is missing required visual quality control proof.",
        "repair_or_replace_creative",
    ),
    "identity_verification_failed": (
        "creative_safety",
        "A draft failed identity verification.",
        "repair_or_replace_creative",
    ),
    "identity_verification_unavailable": (
        "creative_safety",
        "A draft is missing required identity verification proof.",
        "repair_or_replace_creative",
    ),
    "schedule_plan_not_ready": (
        "schedule_plan",
        "The schedule plan is not ready.",
        "rerun_campaign_schedule_plan",
    ),
    "insufficient_schedule_plan_items": (
        "schedule_plan",
        "The schedule plan has too few items for the requested batch.",
        "rerun_campaign_schedule_plan",
    ),
    "variant_cooldown_violation": (
        "schedule_plan",
        "The schedule plan violates variant cooldown rules.",
        "rerun_campaign_schedule_plan",
    ),
    "duplicate_schedule_risk": (
        "schedule_plan",
        "The schedule plan has duplicate-posting risk.",
        "rerun_campaign_schedule_plan",
    ),
    "time_plan_not_ready": (
        "time_plan",
        "The time plan is not ready.",
        "rerun_campaign_schedule_time_plan",
    ),
    "insufficient_time_plan_items": (
        "time_plan",
        "The time plan has too few slots for the requested batch.",
        "rerun_campaign_schedule_time_plan",
    ),
    "timestamp_collision": (
        "time_plan",
        "Two scheduled items share the same timestamp.",
        "rerun_campaign_schedule_time_plan",
    ),
    "account_link_sharing_restricted": (
        "account_health",
        "An account has link sharing restrictions.",
        "resolve_account_health_blocker",
    ),
    "recommendation_not_eligible": (
        "account_health",
        "An account is not recommendation-eligible.",
        "resolve_account_health_blocker",
    ),
    "account_warming_cadence_exceeded": (
        "account_health",
        "A warming account would exceed its cadence.",
        "wait_or_choose_different_account",
    ),
    "creative_risk_score_exceeded": (
        "creative_safety",
        "Creative risk is above the allowed threshold.",
        "repair_or_replace_creative",
    ),
    "similarity_budget_exceeded": (
        "creative_safety",
        "Similarity budget is exhausted for the candidate batch.",
        "run_contentforge_variant_plan",
    ),
    "scheduled_post_publish_route_missing": (
        "publish_runtime",
        "ThreadsDashboard publish route could not be verified.",
        "verify_threadsdashboard_runtime",
    ),
    "campaign_schedule_recovery_route_missing": (
        "publish_runtime",
        "ThreadsDashboard schedule recovery route could not be verified.",
        "verify_threadsdashboard_runtime",
    ),
    "campaign_schedule_recovery_cron_missing": (
        "publish_runtime",
        "ThreadsDashboard schedule recovery cron could not be verified.",
        "verify_threadsdashboard_runtime",
    ),
}


class ExecutionReadinessRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        creator_label: Callable[[Any], str],
        creator_os_daily_plan: Callable[..., dict[str, Any]],
        creator_os_draft_items: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        creator_os_schedule_safe_drafts: Callable[
            [str, list[dict[str, Any]]], list[dict[str, Any]]
        ],
        creator_os_account_health_report: Callable[..., dict[str, Any]],
        creator_os_execution_draft_blockers: Callable[
            [str, list[dict[str, Any]]], list[str]
        ],
        creator_os_execution_account_health_blockers: Callable[
            [dict[str, Any]], list[str]
        ],
        creator_os_execution_account_health_warnings: Callable[
            [dict[str, Any]], list[str]
        ],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._creator_label = creator_label
        self._creator_os_daily_plan = creator_os_daily_plan
        self._creator_os_draft_items = creator_os_draft_items
        self._creator_os_schedule_safe_drafts = creator_os_schedule_safe_drafts
        self._creator_os_account_health_report = creator_os_account_health_report
        self._creator_os_execution_draft_blockers = creator_os_execution_draft_blockers
        self._creator_os_execution_account_health_blockers = (
            creator_os_execution_account_health_blockers
        )
        self._creator_os_execution_account_health_warnings = (
            creator_os_execution_account_health_warnings
        )
        self._utc_now = utc_now

    def creator_os_execution_readiness(
        self,
        *,
        creator: str,
        requested_count: int,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        requested = max(1, int(requested_count or 1))
        creator_label = self._creator_label(creator)
        report = threadsdash_report or {}
        schedule = schedule_plan or {}
        time_report = time_plan or {}
        daily = self._creator_os_daily_plan(
            creators=[creator_label],
            threadsdash_report=report,
            schedule_plan=schedule,
            time_plan=time_report,
            generated_at=generated_at,
        )
        creator_row = daily["creators"][0] if daily.get("creators") else {}
        missed_dispatches = [
            item
            for item in report.get("missedDispatches") or []
            if isinstance(item, dict)
        ]
        draft_items = self._creator_os_draft_items(
            [item for item in (time_report, schedule) if isinstance(item, dict)]
        )
        schedule_safe_drafts = self._creator_os_schedule_safe_drafts(
            creator_label, draft_items
        )
        account_health = self._creator_os_account_health_report(
            creator=creator_label,
            threadsdash_report=report,
            generated_at=generated_at,
        )
        safe_accounts = int(creator_row.get("safeAccounts") or 0)
        blockers: list[str] = []
        warnings: list[str] = []

        if safe_accounts < requested:
            blockers.append("insufficient_safe_accounts")
        if missed_dispatches:
            blockers.append("missed_dispatches_unresolved")
        if len(schedule_safe_drafts) < requested:
            blockers.append("insufficient_schedule_safe_drafts")

        blockers.extend(
            self._creator_os_execution_draft_blockers(creator_label, draft_items)
        )
        blockers.extend(
            self._creator_os_execution_account_health_blockers(account_health)
        )
        warnings.extend(
            self._creator_os_execution_account_health_warnings(account_health)
        )

        schedule_status = str(schedule.get("status") or "").lower()
        schedule_items = [
            item for item in schedule.get("items") or [] if isinstance(item, dict)
        ]
        if schedule_status != "ready":
            reason = str(schedule.get("blockingReason") or "schedule_plan_not_ready")
            blockers.append(f"schedule_plan_not_ready:{reason}")
        elif len(schedule_items) < requested:
            blockers.append("insufficient_schedule_plan_items")

        time_status = str(time_report.get("status") or "").lower()
        time_items = [
            item for item in time_report.get("items") or [] if isinstance(item, dict)
        ]
        if time_status != "ready":
            reason = str(time_report.get("blockingReason") or "time_plan_not_ready")
            blockers.append(f"time_plan_not_ready:{reason}")
        elif len(time_items) < requested:
            blockers.append("insufficient_time_plan_items")
        if self._creator_os_has_time_collision(time_items):
            blockers.append("timestamp_collision")

        runtime_warnings, runtime_blockers = self._creator_os_publish_runtime_findings(
            missed_dispatches
        )
        warnings.extend(runtime_warnings)
        blockers.extend(runtime_blockers)

        unique_blockers = sorted(set(blockers))
        account_readiness = (
            "pass" if safe_accounts >= requested and not missed_dispatches else "fail"
        )
        draft_readiness = (
            "pass"
            if len(schedule_safe_drafts) >= requested
            and not any(
                blocker in unique_blockers
                for blocker in {
                    "missing_handoff_manifest",
                    "platform_draft_not_validated",
                    "quarantined_draft_present",
                    "publishability_failed_draft_present",
                    "missing_campaign_factory_asset_id",
                    "missing_campaign_factory_distribution_plan_id",
                    "missing_content_fingerprint",
                    "not_approved",
                    "embedded_audio_invalid",
                    "native_audio_proof_missing",
                    "instagram_post_caption_quality_failed",
                    "visual_qc_failed",
                    "visual_qc_unavailable",
                    "identity_verification_failed",
                    "identity_verification_unavailable",
                    "insufficient_schedule_safe_drafts",
                }
            )
            else "fail"
        )
        schedule_readiness = (
            "pass"
            if schedule_status == "ready"
            and len(schedule_items) >= requested
            and not any(
                blocker in unique_blockers
                for blocker in {"variant_cooldown_violation", "duplicate_schedule_risk"}
            )
            else "fail"
        )
        time_readiness = (
            "pass"
            if time_status == "ready"
            and len(time_items) >= requested
            and "timestamp_collision" not in unique_blockers
            else "fail"
        )
        publish_readiness = (
            "pass" if not missed_dispatches and not runtime_blockers else "fail"
        )
        caption_readiness = (
            "pass"
            if not any(
                blocker in unique_blockers
                for blocker in {
                    "missing_instagram_post_caption",
                    "missing_burned_captions",
                    "missing_burned_caption_text",
                    "missing_caption_hash",
                    "missing_caption_outcome_context",
                    "caption_placement_qc_failed",
                    "instagram_post_caption_quality_failed",
                }
            )
            else "fail"
        )
        audio_readiness = (
            "pass"
            if not any(
                blocker in unique_blockers
                for blocker in {"embedded_audio_invalid", "native_audio_proof_missing"}
            )
            else "fail"
        )
        quality_readiness = (
            "pass"
            if not any(
                blocker in unique_blockers
                for blocker in {
                    "readiness_failed",
                    "wrong_visual",
                    "visual_qc_failed",
                    "visual_qc_unavailable",
                    "identity_verification_failed",
                    "identity_verification_unavailable",
                }
            )
            else "fail"
        )
        checklist = {
            "accountReadiness": account_readiness,
            "accountHealthReadiness": "pass"
            if not self._creator_os_execution_account_health_blockers(account_health)
            else "fail",
            "draftReadiness": draft_readiness,
            "schedulePlanReadiness": schedule_readiness,
            "timePlanReadiness": time_readiness,
            "publishRuntimeReadiness": publish_readiness,
            "qualityReadiness": quality_readiness,
            "audioReadiness": audio_readiness,
            "captionContractReadiness": caption_readiness,
        }

        if all(value == "pass" for value in checklist.values()) and not unique_blockers:
            decision = "ready_to_schedule"
            reason = "all_precommit_checks_passed"
            execution_ready = True
            next_actions = ["commit_campaign_schedule_batch"]
        elif (
            len(schedule_safe_drafts) < requested
            and account_readiness == "pass"
            and publish_readiness == "pass"
        ):
            decision = "needs_inventory"
            reason = "schedule_safe_draft_inventory_short"
            execution_ready = False
            next_actions = [
                "create_or_export_schedule_safe_drafts",
                "rerun_campaign_schedule_plan",
            ]
        else:
            decision = "blocked"
            reason = unique_blockers[0] if unique_blockers else "precommit_check_failed"
            execution_ready = False
            next_actions = []
            if missed_dispatches:
                next_actions.append("resolve_missed_dispatches_before_scheduling")
            if schedule_readiness == "fail":
                next_actions.append("rerun_campaign_schedule_plan")
            if time_readiness == "fail":
                next_actions.append("rerun_campaign_schedule_time_plan")
            if draft_readiness == "fail":
                next_actions.append("create_or_export_schedule_safe_drafts")

        return {
            "schema": "creator_os.execution_readiness.v1",
            "generatedAt": generated_at or self._utc_now(),
            "creator": creator_label,
            "requestedCount": requested,
            "managerDecision": decision,
            "managerReason": reason,
            "executionReady": execution_ready,
            "safeAccountsAvailable": safe_accounts,
            "scheduleSafeDraftsAvailable": len(schedule_safe_drafts),
            "accountHealthSummary": account_health.get("summary") or {},
            "blockers": unique_blockers,
            "blockerDetails": self._creator_os_execution_blocker_details(
                unique_blockers,
                requested=requested,
                safe_accounts=safe_accounts,
                schedule_safe_drafts=len(schedule_safe_drafts),
                schedule_items=len(schedule_items),
                time_items=len(time_items),
            ),
            "warnings": sorted(set(warnings)),
            "preCommitChecklist": checklist,
            "nextSafeActions": list(dict.fromkeys(next_actions)),
            "wouldWrite": False,
            "inputs": {
                "threadsdashReportSchema": report.get("schema"),
                "schedulePlanSchema": schedule.get("schema"),
                "timePlanSchema": time_report.get("schema"),
            },
        }

    def _creator_os_execution_blocker_details(
        self,
        blockers: list[str],
        *,
        requested: int,
        safe_accounts: int,
        schedule_safe_drafts: int,
        schedule_items: int,
        time_items: int,
    ) -> list[dict[str, Any]]:
        details = []
        counts = {
            "insufficient_safe_accounts": safe_accounts,
            "insufficient_schedule_safe_drafts": schedule_safe_drafts,
            "insufficient_schedule_plan_items": schedule_items,
            "insufficient_time_plan_items": time_items,
        }
        for code in blockers:
            base, _, source_reason = code.partition(":")
            category, explanation, next_action = _BLOCKER_GUIDANCE.get(
                base,
                (
                    "unknown",
                    "Execution readiness blocked on an unmapped guardrail.",
                    "inspect_blocker_code",
                ),
            )
            item: dict[str, Any] = {
                "code": code,
                "category": category,
                "explanation": explanation,
                "nextAction": next_action,
            }
            if source_reason:
                item["sourceReason"] = source_reason
            if base in counts:
                item["observed"] = counts[base]
                item["required"] = requested
            details.append(item)
        return details

    def _creator_os_has_time_collision(self, items: list[dict[str, Any]]) -> bool:
        seen: set[str] = set()
        for item in items:
            scheduled_for = str(
                item.get("scheduledFor") or item.get("scheduled_for") or ""
            ).strip()
            if not scheduled_for:
                continue
            if scheduled_for in seen:
                return True
            seen.add(scheduled_for)
        return False

    def _creator_os_publish_runtime_findings(
        self, missed_dispatches: list[dict[str, Any]]
    ) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        blockers: list[str] = []
        if missed_dispatches:
            blockers.append("missed_dispatches_unresolved")
        threadsdash_root = self.settings.threadsdash_root
        if not threadsdash_root.exists():
            warnings.append("threadsdashboard_runtime_routes_unverified")
            return warnings, blockers
        if not (threadsdash_root / "api" / "scheduled-post-publish.ts").exists():
            blockers.append("scheduled_post_publish_route_missing")
        if not (
            threadsdash_root / "api" / "cron" / "campaign-schedule-recovery.ts"
        ).exists():
            blockers.append("campaign_schedule_recovery_route_missing")
        vercel_config = threadsdash_root / "vercel.json"
        if vercel_config.exists():
            try:
                if (
                    "/api/cron/campaign-schedule-recovery"
                    not in vercel_config.read_text(encoding="utf-8")
                ):
                    blockers.append("campaign_schedule_recovery_cron_missing")
            except OSError:
                warnings.append("campaign_schedule_recovery_cron_unverified")
        else:
            warnings.append("vercel_json_unavailable")
        return warnings, blockers
