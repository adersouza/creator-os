from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable


class AccountHealthRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now: Callable[[], str],
        creator_label: Callable[[Any], str],
        truthy: Callable[[Any], bool],
        normalize_content_surface: Callable[[str | None], str],
        account_trust_states: set[str],
        recommendation_eligibility_states: set[str],
        warming_stages: set[str],
        content_surfaces: tuple[str, ...],
        creative_risk_block_threshold: int,
        creative_risk_caution_threshold: int,
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now
        self._creator_label = creator_label
        self._truthy = truthy
        self._normalize_content_surface = normalize_content_surface
        self._account_trust_states = account_trust_states
        self._recommendation_eligibility_states = recommendation_eligibility_states
        self._warming_stages = warming_stages
        self._content_surfaces = content_surfaces
        self._creative_risk_block_threshold = creative_risk_block_threshold
        self._creative_risk_caution_threshold = creative_risk_caution_threshold

    def creator_os_account_tiers(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        report = threadsdash_report or {}
        accounts = [
            dict(item)
            for item in report.get("accounts") or []
            if isinstance(item, dict) and self._creator_label(item.get("creator") or creator_label) in {creator_label, "unknown"}
        ]
        health_report = self.creator_os_account_health_report(
            creator=creator_label,
            threadsdash_report=report,
            generated_at=generated_at,
        )
        health_by_account = {row["accountId"]: row for row in health_report.get("accounts") or []}
        rows = []
        for account in accounts:
            account_id = str(account.get("accountId") or account.get("id") or account.get("instagramAccountId") or "").strip()
            health = health_by_account.get(account_id) or self.creator_os_account_health_decision(account, missed=[])
            state = str(health.get("state") or "safe")
            tier = str(health.get("accountTier") or "normal")
            rows.append({
                "accountId": account_id,
                "username": account.get("username") or account.get("handle"),
                "creator": creator_label,
                "state": state,
                "tier": tier,
                "blockedReason": health.get("blockedReason") or "",
                "postingGuidance": health.get("postingGuidance") or self.creator_os_tier_posting_guidance(tier),
                "accountHealth": health,
                "wouldWrite": False,
            })
        return {
            "schema": "creator_os.account_tiers.v1",
            "generatedAt": generated_at or self._utc_now(),
            "creator": creator_label,
            "tierSummary": self.creator_os_account_tier_summary(rows, key="tier"),
            "accounts": rows,
            "wouldWrite": False,
            "inputs": {
                "threadsdashReportSchema": report.get("schema"),
            },
        }

    def creator_os_account_health_report(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        report = threadsdash_report or {}
        accounts = [
            dict(item)
            for item in report.get("accounts") or []
            if isinstance(item, dict) and self._creator_label(item.get("creator") or creator_label) in {creator_label, "unknown"}
        ]
        missed_by_account: dict[str, list[dict[str, Any]]] = {}
        for missed in report.get("missedDispatches") or []:
            if not isinstance(missed, dict):
                continue
            account_id = str(missed.get("accountId") or missed.get("instagramAccountId") or missed.get("instagram_account_id") or "").strip()
            if account_id:
                missed_by_account.setdefault(account_id, []).append(missed)

        rows = []
        for account in accounts:
            account_id = str(account.get("accountId") or account.get("id") or account.get("instagramAccountId") or "").strip()
            rows.append(self.creator_os_account_health_decision(account, missed=missed_by_account.get(account_id, [])))

        summary = self.creator_os_account_health_summary(rows)
        return {
            "schema": "creator_os.account_health_report.v1",
            "generatedAt": generated_at or self._utc_now(),
            "creator": creator_label,
            "summary": summary,
            "accounts": rows,
            "wouldWrite": False,
            "inputs": {
                "threadsdashReportSchema": report.get("schema"),
                "missedDispatchCount": len(report.get("missedDispatches") or []),
            },
        }

    def creator_os_restricted_account_report(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        report = self.creator_os_account_health_report(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )
        accounts = [
            row for row in report.get("accounts") or []
            if isinstance(row, dict) and (
                row.get("linkSharingRestricted")
                or (row.get("restrictionStatus") or {}).get("active")
                or row.get("recommendationEligibilityState") in {"limited", "not_recommended"}
            )
        ]
        return {
            "schema": "creator_os.restricted_account_report.v1",
            "generatedAt": report.get("generatedAt"),
            "creator": report.get("creator"),
            "restrictedAccounts": len(accounts),
            "accounts": accounts,
            "wouldWrite": False,
        }

    def creator_os_manual_review_queue(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        report = self.creator_os_account_health_report(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )
        accounts = [
            row for row in report.get("accounts") or []
            if isinstance(row, dict) and (
                row.get("accountTrustState") == "manual_review_required"
                or row.get("recommendationEligibilityState") == "manual_review_required"
                or row.get("linkSharingRestricted")
                or "account_link_sharing_restricted" in (row.get("blockers") or [])
                or "account_manual_review_required" in (row.get("blockers") or [])
                or "recent_publish_failure_unresolved" in (row.get("blockers") or [])
            )
        ]
        return {
            "schema": "creator_os.manual_review_queue.v1",
            "generatedAt": report.get("generatedAt"),
            "creator": report.get("creator"),
            "manualReviewAccounts": len(accounts),
            "accounts": accounts,
            "wouldWrite": False,
        }

    def creator_os_account_warmup_report(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        report = self.creator_os_account_health_report(
            creator=creator,
            threadsdash_report=threadsdash_report,
            generated_at=generated_at,
        )
        accounts = [
            row for row in report.get("accounts") or []
            if isinstance(row, dict) and row.get("accountTier") == "warming"
        ]
        return {
            "schema": "creator_os.account_warmup_report.v1",
            "generatedAt": report.get("generatedAt"),
            "creator": report.get("creator"),
            "warmingAccounts": len(accounts),
            "accounts": accounts,
            "wouldWrite": False,
        }

    def creator_os_execution_account_health_blockers(self, account_health: dict[str, Any]) -> list[str]:
        blockers: set[str] = set()
        for account in account_health.get("accounts") or []:
            if not isinstance(account, dict) or account.get("safeToSchedule") is not False:
                continue
            for blocker in account.get("blockers") or []:
                raw = str(blocker)
                if raw in {"link_sharing_restricted", "account_link_sharing_restricted"}:
                    blockers.add("account_link_sharing_restricted")
                elif raw in {"recommendation_not_eligible", "account_manual_review_required"}:
                    blockers.add("recommendation_not_eligible" if raw == "recommendation_not_eligible" else "account_manual_review_required")
                elif raw == "account_warming_cadence_exceeded":
                    blockers.add("account_warming_cadence_exceeded")
                elif raw == "creative_risk_score_exceeded":
                    blockers.add("creative_risk_score_exceeded")
                elif raw == "similarity_budget_exceeded":
                    blockers.add("similarity_budget_exceeded")
                elif raw in {"recent_publish_failure_unresolved", "missed_dispatches_unresolved"}:
                    blockers.add(raw)
                elif "restricted" in raw:
                    blockers.add("account_restricted")
                elif raw:
                    blockers.add(raw)
        return sorted(blockers)

    def creator_os_execution_account_health_warnings(self, account_health: dict[str, Any]) -> list[str]:
        warnings: set[str] = set()
        for account in account_health.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            for warning in account.get("warnings") or []:
                warnings.add(str(warning))
        return sorted(warnings)

    def creator_os_account_tier_summary(self, accounts: list[dict[str, Any]], *, key: str = "accountTier") -> dict[str, int]:
        summary = {tier: 0 for tier in ("warming", "normal", "growth", "winner", "resting", "blocked")}
        for account in accounts:
            tier = str(account.get(key) or "normal")
            if tier not in summary:
                tier = "normal"
            summary[tier] += 1
        return summary

    def creator_os_account_health_decision(self, account: dict[str, Any], *, missed: list[dict[str, Any]]) -> dict[str, Any]:
        account_id = str(account.get("accountId") or account.get("id") or account.get("instagramAccountId") or "").strip()
        restriction = self.creator_os_restriction_status(account)
        recommendation_state = self.creator_os_recommendation_eligibility(account)
        maturity_score = self.creator_os_maturity_score(account)
        warming_stage = self.creator_os_warming_stage(account, maturity_score=maturity_score)
        explicit_trust = self.creator_os_account_trust_state(account)
        recent_failure_count = max(
            int(self.creator_os_numeric(account.get("recentPublishFailureCount") or account.get("recent_publish_failure_count"))),
            1 if str(account.get("bucket") or "") == "blocked_recent_failure" else 0,
        )
        creative_risk = self.creator_os_creative_risk(account)
        similarity_budget = self.creator_os_similarity_budget(account)
        active_restriction = bool(restriction.get("active"))
        link_restricted = bool(account.get("linkSharingRestricted") or account.get("link_sharing_restricted"))
        blocked_reason = self.creator_os_blocked_reason(account, missed)
        blockers: list[str] = [blocked_reason] if blocked_reason else []
        warnings: list[str] = []

        if missed:
            blockers.append("missed_dispatches_unresolved")
        if active_restriction:
            blockers.append(str(restriction.get("type") or "account_restricted"))
        if link_restricted:
            blockers.append("account_link_sharing_restricted")
        if explicit_trust in {"restricted", "blocked", "manual_review_required"}:
            blockers.append(f"account_{explicit_trust}")
        if recommendation_state in {"limited", "not_recommended", "manual_review_required"}:
            blockers.append("recommendation_not_eligible")
        elif recommendation_state == "unknown":
            warnings.append("recommendation_eligibility_unknown_conservative_cadence")
        if recent_failure_count > 0:
            blockers.append("recent_publish_failure_unresolved")
        if creative_risk["creativeRiskScore"] >= self._creative_risk_block_threshold:
            blockers.append("creative_risk_score_exceeded")
        elif creative_risk["creativeRiskScore"] >= self._creative_risk_caution_threshold:
            warnings.append("creative_risk_caution")
        if similarity_budget.get("blocked"):
            blockers.append("similarity_budget_exceeded")

        trust_state = explicit_trust
        if blockers:
            trust_state = "blocked"
        elif trust_state == "unknown":
            if warming_stage in {"day_0_3", "day_4_7", "week_2"} or maturity_score < 30:
                trust_state = "warming"
            elif maturity_score >= 80:
                trust_state = "normal"
            else:
                trust_state = "normal"

        account_tier = self.creator_os_account_tier_from_health(
            account,
            trust_state=trust_state,
            maturity_score=maturity_score,
        )
        guidance = self.creator_os_tier_posting_guidance(account_tier)
        if account_tier not in {"blocked", "resting"}:
            guidance = {
                **guidance,
                **self.creator_os_cadence_overrides(account, warming_stage=warming_stage, maturity_score=maturity_score),
            }
        over_cadence = self.creator_os_account_over_cadence(account, guidance)
        if over_cadence and trust_state != "blocked":
            blockers.append("account_warming_cadence_exceeded")
            trust_state = "blocked"
            account_tier = "blocked"
            guidance = self.creator_os_tier_posting_guidance("blocked")

        unique_blockers = list(dict.fromkeys([str(item) for item in blockers if str(item)]))
        state = "blocked" if unique_blockers else ("warming" if account_tier == "warming" else "safe")
        blocked_reason_final = unique_blockers[0] if unique_blockers else ""
        return {
            "accountId": account_id,
            "username": account.get("username") or account.get("handle"),
            "creator": self._creator_label(account.get("creator")),
            "state": state,
            "accountTier": account_tier,
            "accountTrustState": trust_state,
            "recommendationEligibilityState": recommendation_state,
            "accountMaturityScore": maturity_score,
            "warmingStage": warming_stage,
            "restrictionStatus": restriction,
            "linkSharingRestricted": link_restricted,
            "recentPublishFailureCount": recent_failure_count,
            "creativeRiskScore": creative_risk["creativeRiskScore"],
            "creativeRiskLevel": creative_risk["creativeRiskLevel"],
            "creativeRiskReasons": creative_risk["creativeRiskReasons"],
            "similarityBudget": similarity_budget,
            "safeToSchedule": not unique_blockers,
            "blockedReason": blocked_reason_final,
            "blockers": unique_blockers,
            "warnings": sorted(set(warnings)),
            "postingGuidance": guidance,
            "allowedSurfaces": guidance.get("allowedSurfaces") or [],
            "wouldWrite": False,
        }

    def creator_os_account_health_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        valid_rows = [row for row in rows if isinstance(row, dict)]
        trust_summary: dict[str, int] = {state: 0 for state in sorted(self._account_trust_states)}
        rec_summary: dict[str, int] = {state: 0 for state in sorted(self._recommendation_eligibility_states)}
        maturity_distribution = {"lt30": 0, "30_59": 0, "60_plus": 0, "unknown": 0}
        risk_distribution = {"safe": 0, "caution": 0, "blocked": 0}
        similarity_warnings = []
        for row in valid_rows:
            trust = str(row.get("accountTrustState") or "normal")
            trust_summary[trust if trust in trust_summary else "normal"] += 1
            rec = str(row.get("recommendationEligibilityState") or "unknown")
            rec_summary[rec if rec in rec_summary else "unknown"] += 1
            score = row.get("accountMaturityScore")
            if score is None:
                maturity_distribution["unknown"] += 1
            elif int(score) < 30:
                maturity_distribution["lt30"] += 1
            elif int(score) < 60:
                maturity_distribution["30_59"] += 1
            else:
                maturity_distribution["60_plus"] += 1
            risk = str(row.get("creativeRiskLevel") or "safe")
            risk_distribution[risk if risk in risk_distribution else "safe"] += 1
            budget = row.get("similarityBudget") if isinstance(row.get("similarityBudget"), dict) else {}
            if budget.get("warning") or budget.get("blocked"):
                similarity_warnings.append({
                    "accountId": row.get("accountId"),
                    "username": row.get("username"),
                    "reason": budget.get("reason"),
                })
        return {
            "accounts": len(valid_rows),
            "safeToSchedule": sum(1 for row in valid_rows if row.get("safeToSchedule") is True),
            "blockedAccounts": sum(1 for row in valid_rows if row.get("safeToSchedule") is False),
            "restrictedAccounts": sum(1 for row in valid_rows if (row.get("restrictionStatus") or {}).get("active") or row.get("linkSharingRestricted")),
            "manualReviewAccounts": sum(1 for row in valid_rows if row.get("accountTrustState") == "manual_review_required" or row.get("recommendationEligibilityState") == "manual_review_required"),
            "trustStateSummary": trust_summary,
            "recommendationEligibilitySummary": rec_summary,
            "maturityDistribution": maturity_distribution,
            "creativeRiskDistribution": risk_distribution,
            "similarityBudgetWarnings": similarity_warnings,
        }

    def creator_os_account_trust_state(self, account: dict[str, Any]) -> str:
        raw = str(account.get("accountTrustState") or account.get("account_trust_state") or account.get("trustState") or "").strip().lower().replace("-", "_")
        if raw in self._account_trust_states:
            return raw
        raw_state = str(account.get("accountState") or account.get("state") or "").strip().lower().replace("-", "_")
        if raw_state == "high_performing":
            return "winner"
        if raw_state in self._account_trust_states:
            return raw_state
        return "unknown"

    def creator_os_recommendation_eligibility(self, account: dict[str, Any]) -> str:
        raw = str(
            account.get("recommendationEligibilityState")
            or account.get("recommendation_eligibility_state")
            or account.get("recommendationEligible")
            or account.get("recommendation_eligible")
            or ""
        ).strip().lower().replace("-", "_")
        if raw in {"true", "1", "yes"}:
            return "eligible"
        if raw in {"false", "0", "no"}:
            return "not_recommended"
        if raw in self._recommendation_eligibility_states:
            return raw
        return "unknown"

    def creator_os_restriction_status(self, account: dict[str, Any]) -> dict[str, Any]:
        restriction = account.get("restrictionStatus") if isinstance(account.get("restrictionStatus"), dict) else {}
        raw_status = str(restriction.get("status") or account.get("restriction_status") or account.get("restrictionStatus") or "").strip()
        restriction_type = str(restriction.get("type") or account.get("restrictionType") or account.get("restriction_type") or "").strip()
        started_at = str(restriction.get("startedAt") or account.get("restriction_started_at") or account.get("restrictionStartedAt") or "").strip()
        ends_at = str(restriction.get("endsAt") or account.get("restriction_ends_at") or account.get("restrictionEndsAt") or "").strip()
        active = self._truthy(restriction.get("active")) or raw_status.lower() in {"active", "restricted", "blocked"}
        if ends_at:
            try:
                active = active and datetime.fromisoformat(ends_at.replace("Z", "+00:00")) > datetime.now(timezone.utc)
            except ValueError:
                pass
        return {
            "active": active,
            "status": raw_status or ("active" if active else ""),
            "type": restriction_type or ("link_sharing_restricted" if account.get("linkSharingRestricted") or account.get("link_sharing_restricted") else ""),
            "startedAt": started_at,
            "endsAt": ends_at,
        }

    def creator_os_maturity_score(self, account: dict[str, Any]) -> int:
        explicit = account.get("accountMaturityScore") if account.get("accountMaturityScore") is not None else account.get("account_maturity_score")
        if explicit is not None:
            return max(0, min(100, int(self.creator_os_numeric(explicit))))
        maturity_signal_keys = {
            "accountAgeDays", "account_age_days", "followers", "followersCount", "followers_count",
            "successfulPublishes", "successful_publishes", "publishedCount", "lastRestrictionAt",
            "last_restriction_at", "lastWarningAt", "last_warning_at", "lastManualReviewAt",
            "last_manual_review_at", "manualVerificationCompleted",
        }
        if not any(key in account for key in maturity_signal_keys):
            return 60
        score = 0
        age_days = self.creator_os_numeric(account.get("accountAgeDays") or account.get("account_age_days"))
        followers = self.creator_os_numeric(account.get("followers") or account.get("followersCount") or account.get("followers_count"))
        published = self.creator_os_numeric(account.get("successfulPublishes") or account.get("successful_publishes") or account.get("publishedCount"))
        if age_days >= 30:
            score += 35
        elif age_days >= 14:
            score += 24
        elif age_days >= 7:
            score += 14
        elif age_days > 0:
            score += 6
        if followers >= 1000:
            score += 25
        elif followers >= 250:
            score += 18
        elif followers >= 50:
            score += 10
        elif followers > 0:
            score += 4
        if published >= 25:
            score += 25
        elif published >= 10:
            score += 18
        elif published >= 3:
            score += 10
        if account.get("lastRestrictionAt") or account.get("last_restriction_at"):
            score -= 20
        if account.get("lastWarningAt") or account.get("last_warning_at"):
            score -= 10
        if account.get("lastManualReviewAt") or account.get("last_manual_review_at") or account.get("manualVerificationCompleted"):
            score += 10
        return max(0, min(100, int(score)))

    def creator_os_warming_stage(self, account: dict[str, Any], *, maturity_score: int) -> str:
        raw = str(account.get("warmingStage") or account.get("warming_stage") or "").strip().lower().replace("-", "_")
        if raw in self._warming_stages:
            return raw
        age_days = self.creator_os_numeric(account.get("accountAgeDays") or account.get("account_age_days"))
        if age_days > 0:
            if age_days <= 3:
                return "day_0_3"
            if age_days <= 7:
                return "day_4_7"
            if age_days <= 14:
                return "week_2"
            if age_days <= 28:
                return "week_3_4"
            return "mature"
        if maturity_score < 30:
            return "unknown"
        if maturity_score >= 60:
            return "mature"
        return "week_3_4"

    def creator_os_creative_risk(self, account: dict[str, Any]) -> dict[str, Any]:
        explicit = account.get("creativeRisk") if isinstance(account.get("creativeRisk"), dict) else {}
        score = int(self.creator_os_numeric(explicit.get("score") or account.get("creativeRiskScore") or account.get("creative_risk_score")))
        reasons = list(explicit.get("reasons") or account.get("creativeRiskReasons") or [])
        if account.get("discoverabilitySafe") is False:
            score = max(score, self._creative_risk_block_threshold)
            reasons.append("discoverability_safety_failed")
        if account.get("duplicateVisualRisk") or account.get("duplicate_visual_risk"):
            score = max(score, self._creative_risk_caution_threshold)
            reasons.append("duplicate_visual_risk")
        level = "blocked" if score >= self._creative_risk_block_threshold else ("caution" if score >= self._creative_risk_caution_threshold else "safe")
        return {
            "creativeRiskScore": max(0, min(100, score)),
            "creativeRiskLevel": level,
            "creativeRiskReasons": sorted({str(reason) for reason in reasons if str(reason)}),
        }

    def creator_os_similarity_budget(self, account: dict[str, Any]) -> dict[str, Any]:
        budget = account.get("similarityBudget") if isinstance(account.get("similarityBudget"), dict) else {}
        blocked = bool(budget.get("blocked") or account.get("similarityBudgetExceeded") or account.get("similarity_budget_exceeded"))
        warning = bool(budget.get("warning") or account.get("similarityBudgetWarning") or account.get("similarity_budget_warning"))
        return {
            "visualSimilarityCluster": budget.get("visualSimilarityCluster") or account.get("visual_similarity_cluster") or "",
            "captionSimilarityCluster": budget.get("captionSimilarityCluster") or account.get("caption_similarity_cluster") or "",
            "windowDays": int(self.creator_os_numeric(budget.get("windowDays") or budget.get("window_days") or 14)),
            "maxAccounts": int(self.creator_os_numeric(budget.get("maxAccounts") or budget.get("max_accounts") or 0)),
            "currentAccounts": int(self.creator_os_numeric(budget.get("currentAccounts") or budget.get("current_accounts") or 0)),
            "blocked": blocked,
            "warning": warning,
            "reason": str(budget.get("reason") or ("similarity_budget_exceeded" if blocked else "")),
        }

    def creator_os_account_tier_from_health(self, account: dict[str, Any], *, trust_state: str, maturity_score: int) -> str:
        if trust_state in {"blocked", "restricted", "manual_review_required"}:
            return "blocked"
        raw = str(account.get("accountTier") or account.get("tier") or "").strip().lower().replace("-", "_")
        if raw in {"warming", "normal", "growth", "winner", "resting"}:
            return raw
        if trust_state in {"warming", "resting", "growth", "winner"}:
            return trust_state
        if maturity_score < 30:
            return "warming"
        return self.creator_os_account_tier(account, state="safe", blocked_reason="")

    def creator_os_cadence_overrides(self, account: dict[str, Any], *, warming_stage: str, maturity_score: int) -> dict[str, Any]:
        if account.get("maxPostsPerDay") is not None or account.get("max_posts_per_day") is not None:
            max_posts = int(self.creator_os_numeric(account.get("maxPostsPerDay") or account.get("max_posts_per_day")))
        elif warming_stage == "day_0_3":
            max_posts = 1
        elif warming_stage == "day_4_7":
            max_posts = 1
        elif warming_stage == "week_2":
            max_posts = 2
        elif warming_stage == "week_3_4":
            max_posts = 2
        elif maturity_score < 30:
            max_posts = 1
        else:
            max_posts = 2
        if account.get("minimumGapHours") is not None or account.get("minimum_gap_hours") is not None:
            gap = int(self.creator_os_numeric(account.get("minimumGapHours") or account.get("minimum_gap_hours")))
        elif warming_stage in {"day_0_3", "day_4_7"} or maturity_score < 30:
            gap = 24
        elif warming_stage == "week_2":
            gap = 12
        else:
            gap = 8
        allowed = account.get("allowedSurfaces") or account.get("allowed_surfaces")
        if not isinstance(allowed, list):
            allowed = ["story", "reel"] if warming_stage in {"day_0_3", "day_4_7"} or maturity_score < 30 else list(self._content_surfaces)
        return {
            "recommendedPostCount": max_posts,
            "maxPostsPerDay": max_posts,
            "minimumGapHours": gap,
            "allowedSurfaces": [self._normalize_content_surface(item) for item in allowed],
        }

    def creator_os_account_over_cadence(self, account: dict[str, Any], guidance: dict[str, Any]) -> bool:
        max_posts = int(self.creator_os_numeric(guidance.get("maxPostsPerDay") or guidance.get("recommendedPostCount") or 0))
        posts_today = int(self.creator_os_numeric(account.get("postsToday") or account.get("posts_today") or account.get("publishedToday") or account.get("published_today")))
        scheduled_today = int(self.creator_os_numeric(account.get("scheduledToday") or account.get("scheduled_today")))
        return max_posts > 0 and (posts_today + scheduled_today) >= max_posts

    def creator_os_account_tier(self, account: dict[str, Any], *, state: str, blocked_reason: str) -> str:
        if blocked_reason or state == "blocked":
            return "blocked"
        raw = str(account.get("accountTier") or account.get("tier") or "").strip().lower().replace("_", "-")
        explicit = raw.replace("-", "_")
        if explicit in {"warming", "normal", "growth", "winner", "resting"}:
            return explicit
        if state == "resting":
            return "resting"
        if state == "warming":
            return "warming"
        if state == "high-performing":
            return "winner"
        performance = account.get("performance") if isinstance(account.get("performance"), dict) else {}
        metrics = account.get("metrics") if isinstance(account.get("metrics"), dict) else {}
        views_7d = self.creator_os_numeric(performance.get("views7d") or performance.get("views_7d") or metrics.get("views7d") or metrics.get("views_7d"))
        posts_7d = self.creator_os_numeric(performance.get("posts7d") or performance.get("posts_7d") or metrics.get("posts7d") or metrics.get("posts_7d"))
        avg_views = self.creator_os_numeric(performance.get("avgViews") or performance.get("avg_views") or metrics.get("avgViews") or metrics.get("avg_views"))
        if avg_views >= 500 or (posts_7d > 0 and views_7d / max(posts_7d, 1) >= 500):
            return "winner"
        if avg_views >= 100 or (posts_7d > 0 and views_7d / max(posts_7d, 1) >= 100):
            return "growth"
        return "normal"

    def creator_os_numeric(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def creator_os_tier_posting_guidance(self, tier: str) -> dict[str, Any]:
        guidance = {
            "warming": {
                "recommendedPostCount": 1,
                "minimumGapHours": 24,
                "priority": "gentle_warmup",
                "managerAction": "schedule_lightly_with_safe_inventory",
            },
            "normal": {
                "recommendedPostCount": 1,
                "minimumGapHours": 18,
                "priority": "balanced_rotation",
                "managerAction": "schedule_standard_inventory",
            },
            "growth": {
                "recommendedPostCount": 2,
                "minimumGapHours": 12,
                "priority": "increase_reel_cadence",
                "managerAction": "prioritize_stronger_concepts",
            },
            "winner": {
                "recommendedPostCount": 2,
                "minimumGapHours": 8,
                "priority": "prioritize_winning_concepts",
                "managerAction": "fanout_winners_and_high_quality_variants",
            },
            "resting": {
                "recommendedPostCount": 0,
                "minimumGapHours": 48,
                "priority": "reduce_posting_frequency",
                "managerAction": "observe_and_recover_before_scheduling",
            },
            "blocked": {
                "recommendedPostCount": 0,
                "minimumGapHours": None,
                "priority": "do_not_schedule",
                "managerAction": "resolve_account_blocker",
            },
        }
        return dict(guidance.get(tier, guidance["normal"]))

    def creator_os_blocked_reason(self, account: dict[str, Any], missed: list[dict[str, Any]]) -> str:
        if missed:
            return str(missed[0].get("blockingReason") or missed[0].get("reason") or "overdue_dispatch_no_publish_attempt")
        reason = account.get("blockingReason") or account.get("blockedReason")
        if reason:
            return str(reason)
        bucket = str(account.get("bucket") or "")
        if bucket.startswith("blocked_"):
            return bucket
        return ""
