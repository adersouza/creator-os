from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .readiness_finding import (
    ReadinessFinding,
    execution_blocker_detail,
    make_readiness_finding,
    readiness_finding_payloads,
    readiness_findings_from_codes,
)


def _threadsdash_route_present(
    root: Path,
    *,
    direct_path: str,
    gateway_path: str,
    implementation_path: str,
    route_key: str,
) -> bool:
    """Accept direct Vercel functions or an explicit consolidated gateway."""
    if (root / direct_path).is_file():
        return True
    gateway = root / gateway_path
    implementation = root / implementation_path
    if not gateway.is_file() or not implementation.is_file():
        return False
    try:
        return f'"{route_key}"' in gateway.read_text(encoding="utf-8")
    except OSError:
        return False


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

        blocker_findings = self._creator_os_execution_blocker_findings(
            unique_blockers,
            requested=requested,
            safe_accounts=safe_accounts,
            schedule_safe_drafts=len(schedule_safe_drafts),
            schedule_items=len(schedule_items),
            time_items=len(time_items),
        )
        warning_findings = readiness_findings_from_codes(
            warnings,
            severity="warning",
            evidence={"source": "execution_readiness"},
        )

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
            "blockerDetails": [
                execution_blocker_detail(finding) for finding in blocker_findings
            ],
            "warnings": sorted(set(warnings)),
            "findings": readiness_finding_payloads(
                [*blocker_findings, *warning_findings]
            ),
            "preCommitChecklist": checklist,
            "nextSafeActions": list(dict.fromkeys(next_actions)),
            "wouldWrite": False,
            "inputs": {
                "threadsdashReportSchema": report.get("schema"),
                "schedulePlanSchema": schedule.get("schema"),
                "timePlanSchema": time_report.get("schema"),
            },
        }

    def _creator_os_execution_blocker_findings(
        self,
        blockers: list[str],
        *,
        requested: int,
        safe_accounts: int,
        schedule_safe_drafts: int,
        schedule_items: int,
        time_items: int,
    ) -> list[ReadinessFinding]:
        findings: list[ReadinessFinding] = []
        counts = {
            "insufficient_safe_accounts": safe_accounts,
            "insufficient_schedule_safe_drafts": schedule_safe_drafts,
            "insufficient_schedule_plan_items": schedule_items,
            "insufficient_time_plan_items": time_items,
        }
        for code in blockers:
            base = code.partition(":")[0]
            evidence: dict[str, Any] = {"source": "execution_readiness"}
            if base in counts:
                evidence["observed"] = counts[base]
                evidence["required"] = requested
            findings.append(
                make_readiness_finding(
                    code,
                    severity="blocker",
                    evidence=evidence,
                )
            )
        return findings

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
        if not _threadsdash_route_present(
            threadsdash_root,
            direct_path="api/scheduled-post-publish.ts",
            gateway_path="api/[route].ts",
            implementation_path="api/_scheduled-post-publish.ts",
            route_key="scheduled-post-publish",
        ):
            blockers.append("scheduled_post_publish_route_missing")
        if not _threadsdash_route_present(
            threadsdash_root,
            direct_path="api/cron/campaign-schedule-recovery.ts",
            gateway_path="api/cron/[job].ts",
            implementation_path="api/cron/_campaign-schedule-recovery.ts",
            route_key="campaign-schedule-recovery",
        ):
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
