from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from typing import Any

DISCOVERABILITY_SAFE_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("url", re.compile(r"https?://|www\.", re.IGNORECASE)),
    (
        "dm_reference",
        re.compile(
            r"\b(dm|dms|direct\s+message|message\s+me|inbox\s+me)\b", re.IGNORECASE
        ),
    ),
    (
        "link_reference",
        re.compile(
            r"\b(link\s*in\s*bio|bio\s*link|tap\s+link|click\s+link|link)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "subscription_cta",
        re.compile(r"\b(join\s+my\s+page|subscribe)\b", re.IGNORECASE),
    ),
    ("of_reference", re.compile(r"\b(onlyfans|fansly)\b", re.IGNORECASE)),
    ("of_reference", re.compile(r"(^|[^A-Za-z0-9_])#?OF(?![A-Za-z0-9_])")),
    (
        "off_platform_reference",
        re.compile(
            r"\b(snapchat|snap\s+me|telegram|whatsapp|linktree|beacons)\b",
            re.IGNORECASE,
        ),
    ),
)


class DiscoverabilityRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        json_load: Callable[[Any, Any], Any],
        parent_factory_yield_waterfall: Callable[..., dict[str, Any]],
        ratio: Callable[[Any, Any], float],
        score_fraction: Callable[[Any, Any], float],
        wilson_lower_bound: Callable[..., float],
    ) -> None:
        self.conn = conn
        self._json_load = json_load
        self._parent_factory_yield_waterfall = parent_factory_yield_waterfall
        self._ratio = ratio
        self._score_fraction = score_fraction
        self._wilson_lower_bound = wilson_lower_bound

    def discoverability_safe_content_contract(self, *values: Any) -> dict[str, Any]:
        blocked_terms: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            for reason, pattern in DISCOVERABILITY_SAFE_CONTENT_PATTERNS:
                match = pattern.search(value)
                if not match:
                    continue
                key = (reason, match.group(0).lower())
                if key in seen:
                    continue
                seen.add(key)
                blocked_terms.append(
                    {
                        "reason": reason,
                        "matchedText": match.group(0),
                    }
                )
        return {
            "schema": "campaign_factory.discoverability_safe_content_contract.v1",
            "discoverabilitySafe": not blocked_terms,
            "blockedTerms": blocked_terms,
            "blockedReason": "discoverability_risk_link_dm_or_off_platform_reference"
            if blocked_terms
            else "",
            "wouldWrite": False,
        }

    def discoverability_intake_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = self.discoverability_gate_fields(
            payload,
            {
                "source_caption",
                "source_prompt",
                "content_perception",
                "reference_caption",
            },
        )
        return self.discoverability_gate_result("intake", fields)

    def discoverability_generation_gate(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        fields = self.discoverability_gate_fields(
            payload,
            {
                "source_caption",
                "source_prompt",
                "content_perception",
                "reference_caption",
                "prompt",
                "hook",
                "hooks",
                "generated_caption",
                "caption_text",
                "caption_cta",
                "instagram_post_caption",
            },
        )
        return self.discoverability_gate_result("generation", fields)

    def discoverability_pre_render_gate(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        fields = self.discoverability_gate_fields(payload, set(payload.keys()))
        return self.discoverability_gate_result("pre_render", fields)

    def discoverability_violation_origin_map(self) -> dict[str, Any]:
        evidence = self.parent_factory_captured_discoverability_evidence()
        fallback = self.parent_factory_observed_discoverability_terms()
        source = evidence or fallback
        stages: dict[str, int] = {
            "source_content_perception": 0,
            "prompt_generation": 0,
            "caption_generation": 0,
            "burned_caption_generation": 0,
            "caption_family_generation": 0,
            "parent_registration": 0,
            "publishability_validation": 0,
        }
        for item in source:
            stage = self.discoverability_origin_stage(
                str(item.get("sourceField") or ""), str(item.get("reason") or "")
            )
            stages[stage] = stages.get(stage, 0) + 1
        if not any(stages.values()):
            stages["publishability_validation"] = int(
                self.parent_factory_discoverability_loss_analysis().get(
                    "discoverabilityStageLoss"
                )
                or 0
            )
        total = sum(stages.values())
        before_render = sum(
            stages[name]
            for name in (
                "source_content_perception",
                "prompt_generation",
                "caption_generation",
                "caption_family_generation",
            )
        )
        before_registration = before_render + stages["burned_caption_generation"]
        first = next(
            (stage for stage, count in stages.items() if count > 0),
            "publishability_validation",
        )
        earliest = (
            first if first != "publishability_validation" else "caption_generation"
        )
        return {
            "schema": "creator_os.discoverability_violation_origin_map.v1",
            "whereViolationsFirstAppear": first,
            "earliestPreventableStage": earliest,
            "percentPreventableBeforeRender": round((before_render / total) * 100, 1)
            if total
            else 0,
            "percentPreventableBeforeRegistration": round(
                (before_registration / total) * 100, 1
            )
            if total
            else 0,
            "stageCounts": stages,
            "evidenceSource": "captured_rejection_evidence"
            if evidence
            else "observed_caption_scan",
            "wouldWrite": False,
        }

    def parent_factory_discoverability_loss_analysis(
        self, *, waterfall: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        source = waterfall or self._parent_factory_yield_waterfall()
        stage_losses = {
            row["stage"]: int(row.get("lossCount") or 0)
            for row in source.get("stages") or []
        }
        discoverability_stage_loss = int(
            stage_losses.get("discoverability_safety_pass") or 0
        )
        categories = {
            "dm_language": 0,
            "link_language": 0,
            "off_platform_reference": 0,
            "onlyfans_reference": 0,
            "telegram_reference": 0,
            "snapchat_reference": 0,
            "whatsapp_reference": 0,
            "bio_reference": 0,
            "cta_language": 0,
            "other": 0,
        }
        captured_evidence = self.parent_factory_captured_discoverability_evidence()
        evidence_source = (
            captured_evidence or self.parent_factory_observed_discoverability_terms()
        )
        for term in evidence_source:
            categories[
                self.discoverability_loss_category(
                    term.get("reason", ""), term.get("matchedText", "")
                )
            ] += 1
        observed_failures = sum(categories.values())
        if discoverability_stage_loss > observed_failures:
            categories["other"] += discoverability_stage_loss - observed_failures
        total = max(discoverability_stage_loss, sum(categories.values()))
        generation_categories = {
            "off_platform_reference",
            "onlyfans_reference",
            "telegram_reference",
            "snapchat_reference",
            "whatsapp_reference",
        }
        caption_categories = {
            "dm_language",
            "link_language",
            "bio_reference",
            "cta_language",
        }
        generation_count = sum(categories[name] for name in generation_categories)
        caption_count = sum(categories[name] for name in caption_categories)
        registration_count = categories["other"]
        rows = [
            {
                "category": category,
                "frequency": count,
                "percentOfDiscoverabilityFailures": round((count / total) * 100, 1)
                if total
                else 0,
                "preventableAt": self.discoverability_prevention_stage(category),
                "wouldWrite": False,
            }
            for category, count in categories.items()
        ]
        return {
            "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1",
            "discoverabilityStageLoss": discoverability_stage_loss,
            "capturedEvidenceCount": len(captured_evidence),
            "observedClassifiedFailures": observed_failures,
            "discoverabilityRejectionCategories": rows,
            "percentPreventableAtGeneration": round((generation_count / total) * 100, 1)
            if total
            else 0,
            "percentPreventableAtCaptionCreation": round(
                (caption_count / total) * 100, 1
            )
            if total
            else 0,
            "percentPreventableAtRegistration": round(
                (registration_count / total) * 100, 1
            )
            if total
            else 0,
            "wouldWrite": False,
        }

    def parent_factory_waterfall_after_discoverability(self) -> dict[str, Any]:
        current = self._parent_factory_yield_waterfall(required_parents_per_day=53)
        current_stages = current.get("stages") or []
        raw = int(current_stages[0].get("outputCount") or 0) if current_stages else 0
        stages = []
        previous = raw
        for row in current_stages:
            stage = row["stage"]
            if stage == "discoverability_safety_pass":
                continue
            if stage == "raw_candidate":
                output = raw
            elif stage in {
                "publishability_pass",
                "handoff_ready",
                "schedule_safe",
                "parent_accepted",
            }:
                output = previous
            else:
                output = int(row.get("outputCount") or 0)
            stages.append(
                {
                    "stage": stage,
                    "inputCount": previous if stage != "raw_candidate" else output,
                    "outputCount": output,
                    "yieldPct": round(
                        self._ratio(
                            output, previous if stage != "raw_candidate" else output
                        )
                        * 100,
                        1,
                    ),
                    "lossCount": max(
                        0, (previous if stage != "raw_candidate" else output) - output
                    ),
                    "wouldWrite": False,
                }
            )
            previous = output
        downstream = self.post_discoverability_downstream_confidence()
        return {
            "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1",
            "discoverabilityRemoved": True,
            "stages": stages,
            "theoreticalAcceptedParents": previous,
            "downstreamEvidence": downstream,
            "wouldWrite": False,
        }

    def discoverability_prevention_audit(self) -> dict[str, Any]:
        evidence = self.parent_factory_captured_discoverability_evidence()
        before_render = sum(
            1
            for item in evidence
            if item.get("failedStage")
            in {"discoverability_generation_gate", "discoverability_pre_render_gate"}
        )
        after_render = sum(
            1
            for item in evidence
            if item.get("failedStage") in {"discoverability_post_render_gate"}
        )
        at_publishability = sum(
            1
            for item in evidence
            if item.get("failedStage")
            in {"discoverability_safety_pass", "publishability_pass"}
        )
        fallback = self.parent_factory_discoverability_loss_analysis()
        if before_render + after_render + at_publishability == 0:
            at_publishability = int(fallback.get("observedClassifiedFailures") or 0)
        return {
            "schema": "creator_os.discoverability_prevention_audit.v1",
            "violationsCaughtBeforeRender": before_render,
            "violationsCaughtAfterRender": after_render,
            "violationsCaughtAtPublishability": at_publishability,
            "preventionRatePct": round(
                (
                    before_render
                    / max(1, before_render + after_render + at_publishability)
                )
                * 100,
                1,
            ),
            "goal": "move_discoverability_failures_before_render",
            "wouldWrite": False,
        }

    def discoverability_prevention_scorecard(self) -> dict[str, Any]:
        audit = self.discoverability_prevention_audit()
        total = (
            audit["violationsCaughtBeforeRender"]
            + audit["violationsCaughtAfterRender"]
            + audit["violationsCaughtAtPublishability"]
        )
        score = self._score_fraction(audit["violationsCaughtBeforeRender"], total or 1)
        return {
            "schema": "creator_os.discoverability_prevention_scorecard.v1",
            "score": score,
            "upstreamPreventionReady": score >= 8,
            "audit": audit,
            "wouldWrite": False,
        }

    def parent_factory_observed_discoverability_terms(self) -> list[dict[str, str]]:
        terms: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        rows = [
            dict(row)
            for row in self.conn.execute(
                "SELECT id, caption, caption_outcome_context_json, caption_generation_json FROM rendered_assets"
            ).fetchall()
        ]
        for row in rows:
            values = [row.get("caption")]
            for column in ("caption_outcome_context_json", "caption_generation_json"):
                payload = self._json_load(row.get(column), {})
                if not isinstance(payload, dict):
                    continue
                values.extend(self.discoverability_text_values(payload))
            contract = self.discoverability_safe_content_contract(*values)
            for term in contract.get("blockedTerms") or []:
                reason = str(term.get("reason") or "")
                matched = str(term.get("matchedText") or "")
                key = (str(row.get("id") or ""), reason, matched.lower())
                if key in seen:
                    continue
                seen.add(key)
                terms.append({"reason": reason, "matchedText": matched})
        return terms

    def parent_factory_captured_discoverability_evidence(self) -> list[dict[str, str]]:
        rows = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT failed_stage, failure_category, matched_text, source_field, policy_version
                FROM asset_rejection_evidence
                WHERE policy_version LIKE 'discoverability_safe%'
                   OR failed_stage LIKE 'discoverability%'
                ORDER BY created_at, id
                """
            ).fetchall()
        ]
        return [
            {
                "failedStage": str(row.get("failed_stage") or ""),
                "reason": str(row.get("failure_category") or ""),
                "matchedText": str(row.get("matched_text") or ""),
                "sourceField": str(row.get("source_field") or ""),
                "policyVersion": str(row.get("policy_version") or ""),
            }
            for row in rows
        ]

    def discoverability_text_values(self, payload: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in (
            "caption_text",
            "burned_caption_text",
            "instagram_post_caption",
            "caption",
            "captionCta",
            "caption_cta",
            "ctaText",
            "story_cta_text",
            "snapchat_cta_text",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
        for key in ("hashtags", "caption_banks", "captionSceneTags", "reelSceneTags"):
            value = payload.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value if str(item).strip())
        for value in payload.values():
            if isinstance(value, dict):
                values.extend(self.discoverability_text_values(value))
        return values

    def discoverability_loss_category(self, reason: str, matched_text: str) -> str:
        reason_norm = str(reason or "").lower()
        matched_norm = str(matched_text or "").lower()
        if (
            "dm" in reason_norm
            or "direct" in matched_norm
            or matched_norm in {"dm", "dms"}
            or "message me" in matched_norm
        ):
            return "dm_language"
        if (
            "onlyfans" in matched_norm
            or "fansly" in matched_norm
            or reason_norm == "of_reference"
        ):
            return "onlyfans_reference"
        if "telegram" in matched_norm:
            return "telegram_reference"
        if "snap" in matched_norm:
            return "snapchat_reference"
        if "whatsapp" in matched_norm:
            return "whatsapp_reference"
        if (
            "bio" in matched_norm
            or "linktree" in matched_norm
            or "beacons" in matched_norm
        ):
            return "bio_reference"
        if (
            reason_norm in {"url", "link_reference"}
            or "link" in matched_norm
            or "www." in matched_norm
        ):
            return "link_language"
        if (
            "subscribe" in matched_norm
            or "join my page" in matched_norm
            or reason_norm == "subscription_cta"
        ):
            return "cta_language"
        if reason_norm == "off_platform_reference":
            return "off_platform_reference"
        return "other"

    def discoverability_prevention_stage(self, category: str) -> str:
        if category in {
            "dm_language",
            "link_language",
            "bio_reference",
            "cta_language",
        }:
            return "caption_creation"
        if category in {
            "off_platform_reference",
            "onlyfans_reference",
            "telegram_reference",
            "snapchat_reference",
            "whatsapp_reference",
        }:
            return "generation"
        return "registration"

    def discoverability_gate_fields(
        self, payload: dict[str, Any], allowed_fields: set[str]
    ) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = []
        for key, value in (payload or {}).items():
            if key not in allowed_fields:
                continue
            if isinstance(value, str) and value.strip():
                fields.append((key, value))
            elif isinstance(value, list):
                text = " ".join(str(item) for item in value if str(item).strip())
                if text:
                    fields.append((key, text))
        return fields

    def discoverability_gate_result(
        self, gate: str, fields: list[tuple[str, str]]
    ) -> dict[str, Any]:
        violations = self.discoverability_evidence_for_fields(fields)
        return {
            "schema": f"campaign_factory.discoverability_{gate}_gate.v1",
            "gate": gate,
            "canProceed": not violations,
            "violations": violations,
            "policyVersion": "discoverability_safe_v1",
            "nextAction": "reject_before_render" if violations else "continue",
            "wouldWrite": False,
        }

    def discoverability_origin_stage(self, source_field: str, reason: str) -> str:
        field = source_field.lower()
        reason_norm = reason.lower()
        if "source" in field or "perception" in field or "reference" in field:
            return "source_content_perception"
        if "prompt" in field:
            return "prompt_generation"
        if "caption_family" in field or "caption_version" in field:
            return "caption_family_generation"
        if "burned" in field:
            return "burned_caption_generation"
        if "caption" in field or reason_norm in {
            "dm_language",
            "link_language",
            "bio_reference",
            "cta_language",
        }:
            return "caption_generation"
        if "asset" in field or "registration" in field:
            return "parent_registration"
        return "publishability_validation"

    def post_discoverability_downstream_confidence(self) -> dict[str, Any]:
        current = self._parent_factory_yield_waterfall(required_parents_per_day=53)
        stage_counts = {
            row["stage"]: int(row.get("outputCount") or 0)
            for row in current.get("stages") or []
        }
        clean = int(stage_counts.get("discoverability_safety_pass") or 0)
        accepted = int(stage_counts.get("parent_accepted") or 0)
        pass_rate = self._ratio(accepted, clean)
        confidence_adjusted = self._wilson_lower_bound(successes=accepted, trials=clean)
        return {
            "cleanCandidatesObserved": clean,
            "acceptedCleanCandidatesObserved": accepted,
            "measuredDownstreamPassRate": round(pass_rate, 4),
            "confidenceAdjustedPassRate": round(confidence_adjusted, 4),
            "confidenceMethod": "wilson_lower_bound_95pct",
            "nextActualRejectionCategory": "none_measured_after_discoverability"
            if clean == accepted
            else "downstream_rejection_observed",
            "wouldWrite": False,
        }

    def discoverability_evidence_for_fields(
        self, fields: list[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for source_field, value in fields:
            if not isinstance(value, str) or not value.strip():
                continue
            for reason, pattern in DISCOVERABILITY_SAFE_CONTENT_PATTERNS:
                match = pattern.search(value)
                if not match:
                    continue
                matched = match.group(0)
                category = self.discoverability_loss_category(reason, matched)
                key = (source_field, category, matched.lower())
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(
                    {
                        "failedStage": "discoverability_safety_pass",
                        "failureCategory": category,
                        "matchedText": matched,
                        "sourceField": source_field,
                        "policyVersion": "discoverability_safe_v1",
                        "repairable": True,
                        "reason": reason,
                        "preventableAt": self.discoverability_prevention_stage(
                            category
                        ),
                        "wouldWrite": False,
                    }
                )
        return evidence
