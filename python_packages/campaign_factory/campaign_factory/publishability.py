from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .ai_disclosure import AI_DISCLOSURE_BLOCKER, AiDisclosurePublishabilityMixin
from .caption_outcome import load_context_json
from .caption_policy import (
    CAPTION_PLACEMENT_QC_WARNING_CODES,
    SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL,
)
from .creative_approval import (
    CreativeApprovalStore,
    asset_requires_creative_approval,
)
from .distribution_surface import normalize_distribution_surface
from .motion_qc_publishability import MotionQcPublishabilityMixin
from .persistence import json_load
from .readiness_finding import (
    readiness_finding_codes,
    readiness_finding_payloads,
    readiness_findings_from_codes,
)


class PublishabilityRepository(
    AiDisclosurePublishabilityMixin, MotionQcPublishabilityMixin
):
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now: Callable[[], str],
        sanitize_for_storage: Callable[[Any], Any],
        normalize_content_surface: Callable[[str | None], str],
        rendered_asset: Callable[[str], dict[str, Any]],
        record_event: Callable[..., dict[str, Any]],
        distribution_plan_payload: Callable[[dict[str, Any]], dict[str, Any]],
        audit_report_payload: Callable[[dict[str, Any]], dict[str, Any]],
        latest_audit_for_asset: Callable[[str], dict[str, Any] | None],
        verification_id: Callable[..., str],
        text_hash: Callable[[str], str],
        caption_lineage_sidecar: Callable[[str], dict[str, Any]],
        variant_lineage_for_asset: Callable[[str], dict[str, Any]],
        active_quarantine_for_asset: Callable[[str], dict[str, Any] | None],
        audio_selection_for_asset: Callable[
            [dict[str, Any]], tuple[dict[str, Any], str | None]
        ],
        audio_segment_for_asset: Callable[[dict[str, Any]], dict[str, Any] | None],
        cover_frame_for_asset: Callable[
            [dict[str, Any], dict[str, Any] | None], dict[str, Any] | None
        ],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        content_trust_status_blockers: Callable[..., tuple[list[str], dict[str, str]]],
        audio_intent_claims_embedded_media: Callable[[dict[str, Any]], bool],
        embedded_audio_verified: Callable[[str], bool | None],
        discoverability_safe_content_contract: Callable[..., dict[str, Any]],
        discoverability_evidence_for_fields: Callable[
            [list[tuple[str, str]]], list[dict[str, Any]]
        ],
        reference_hook_is_schedule_safe: Callable[[str], bool],
        audio_intent_is_attached: Callable[[dict[str, Any], str | None], bool],
        requires_operator_visual_review_for_handoff: Callable[[dict[str, Any]], bool],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        ig_media_type_for_surface: Callable[[str, str], str],
        creative_approvals_dir: Path,
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now
        self._sanitize_for_storage = sanitize_for_storage
        self._normalize_content_surface = normalize_content_surface
        self._creative_approval_store = CreativeApprovalStore(creative_approvals_dir)
        self.rendered_asset = rendered_asset
        self.record_event = record_event

        self._distribution_plan_payload = distribution_plan_payload
        self._audit_report_payload = audit_report_payload
        self._latest_audit_for_asset = latest_audit_for_asset
        self._verification_id = verification_id
        self._text_hash = text_hash
        self._caption_lineage_sidecar = caption_lineage_sidecar
        self._variant_lineage_for_asset = variant_lineage_for_asset
        self._active_quarantine_for_asset = active_quarantine_for_asset
        self._audio_selection_for_asset = audio_selection_for_asset
        self._audio_segment_for_asset = audio_segment_for_asset
        self._cover_frame_for_asset = cover_frame_for_asset
        self._instagram_post_caption_for_asset = instagram_post_caption_for_asset
        self._content_trust_status_blockers = content_trust_status_blockers
        self._audio_intent_claims_embedded_media = audio_intent_claims_embedded_media
        self._embedded_audio_verified = embedded_audio_verified
        self.discoverability_safe_content_contract = (
            discoverability_safe_content_contract
        )
        self._discoverability_evidence_for_fields = discoverability_evidence_for_fields
        self._reference_hook_is_schedule_safe = reference_hook_is_schedule_safe
        self._audio_intent_is_attached = audio_intent_is_attached
        self._requires_operator_visual_review_for_handoff = (
            requires_operator_visual_review_for_handoff
        )
        self._surface_report_assets = surface_report_assets
        self._ig_media_type_for_surface = ig_media_type_for_surface

    def creative_approval_for_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        return self._creative_approval_store.status_for_asset(
            self.rendered_asset(rendered_asset_id)
        )

    def latest_audit_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (rendered_asset_id,),
        ).fetchone()
        return self._audit_report_payload(dict(row)) if row else None

    def active_quarantine_for_asset(
        self, rendered_asset_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM quarantined_assets WHERE rendered_asset_id = ? LIMIT 1",
            (rendered_asset_id,),
        ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["metadata"] = json_load(payload.get("metadata_json"), {})
        return payload

    def verification_id(self, prefix: str, *parts: Any) -> str:
        digest = hashlib.sha256(
            ":".join(str(part or "") for part in parts).encode("utf-8")
        ).hexdigest()[:16]
        return f"{prefix}_{digest}"

    def text_hash(self, value: str) -> str:
        normalized = " ".join((value or "").strip().lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def caption_generation_payload(self, asset: dict[str, Any]) -> dict[str, Any]:
        caption_generation = asset.get("captionGeneration")
        if not isinstance(caption_generation, dict):
            caption_generation = json_load(asset.get("caption_generation_json"), {})
        return caption_generation if isinstance(caption_generation, dict) else {}

    def normalize_caption_placement_policy(self, value: Any) -> str | None:
        text = str(value or "").strip().lower().replace("-", "_")
        if not text:
            return None
        if text in {"focal_safe", "focal_safe_v1"}:
            return "focal_safe_v1"
        return text

    def instagram_post_caption_for_asset(
        self,
        asset: dict[str, Any],
        caption_context: dict[str, Any] | None,
        *,
        distribution_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        caption_generation = self.caption_generation_payload(asset)
        source_records = [
            distribution_plan or {},
            caption_generation,
            caption_generation.get("instagramPostCaption")
            if isinstance(caption_generation.get("instagramPostCaption"), dict)
            else {},
            caption_generation.get("instagram_post_caption")
            if isinstance(caption_generation.get("instagram_post_caption"), dict)
            else {},
            caption_context or {},
            asset,
        ]
        post_caption = ""
        explicit_post_caption = False
        for record in source_records:
            if not isinstance(record, dict):
                continue
            for key in (
                "instagram_post_caption",
                "instagramPostCaption",
                "post_caption",
                "postCaption",
            ):
                if key in record and isinstance(record.get(key), str):
                    post_caption = str(record.get(key) or "").strip()
                    explicit_post_caption = True
                    break
            if explicit_post_caption:
                break
        burned_caption = str(
            asset.get("caption") or (caption_context or {}).get("caption_text") or ""
        ).strip()
        caption_cta = next(
            (
                str(value).strip()
                for record in source_records
                if isinstance(record, dict)
                for value in (record.get("caption_cta"), record.get("captionCta"))
                if isinstance(value, str) and value.strip()
            ),
            "",
        )
        hashtags: list[str] = []
        for record in source_records:
            if not isinstance(record, dict):
                continue
            raw_tags = (
                record.get("hashtags")
                or record.get("instagram_hashtags")
                or record.get("instagramHashtags")
            )
            if not isinstance(raw_tags, list):
                continue
            for tag in raw_tags:
                if not isinstance(tag, str):
                    continue
                cleaned = re.sub(r"[^A-Za-z0-9_]", "", tag.strip().lstrip("#"))
                if cleaned and f"#{cleaned}" not in hashtags:
                    hashtags.append(f"#{cleaned}")
                if len(hashtags) >= 5:
                    break
            if len(hashtags) >= 5:
                break
        style = next(
            (
                str(value).strip()
                for record in source_records
                if isinstance(record, dict)
                for value in (
                    record.get("post_caption_style"),
                    record.get("postCaptionStyle"),
                )
                if isinstance(value, str) and value.strip()
            ),
            "short_natural",
        )
        final_caption = post_caption
        if caption_cta and caption_cta.lower() not in final_caption.lower():
            final_caption = f"{final_caption}\n{caption_cta}".strip()
        missing_tags = [
            tag for tag in hashtags if tag.lower() not in final_caption.lower()
        ]
        if missing_tags:
            final_caption = f"{final_caption}\n{' '.join(missing_tags)}".strip()
        final_caption, disclosure_fields = self.append_ai_disclosure(
            final_caption, asset
        )
        return {
            "instagram_post_caption": final_caption,
            "instagram_post_caption_hash": self._text_hash(final_caption)
            if final_caption
            else None,
            "caption_cta": caption_cta or None,
            "hashtags": hashtags,
            "post_caption_style": style,
            "burned_caption_text": burned_caption,
            "burned_caption_hash": self._text_hash(burned_caption)
            if burned_caption
            else None,
            **disclosure_fields,
        }

    def caption_lineage_sidecar(self, output_path: str) -> dict[str, Any]:
        if not output_path:
            return {}
        sidecar_path = Path(output_path + ".caption_lineage.json")
        if not sidecar_path.exists():
            return {}
        try:
            payload = json_load(sidecar_path.read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def quarantine_asset(
        self,
        rendered_asset_id: str,
        *,
        reason: str,
        root_cause: str | None = None,
        blocking_reason: str | None = None,
        distribution_plan_id: str | None = None,
        threadsdash_post_id: str | None = None,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        asset = self.rendered_asset(rendered_asset_id)
        now = self._utc_now()
        quarantine_id = f"qasset_{hashlib.sha256(rendered_asset_id.encode('utf-8')).hexdigest()[:12]}"
        payload = self._sanitize_for_storage(metadata or {})
        self.conn.execute(
            """
            INSERT INTO quarantined_assets
            (id, campaign_id, rendered_asset_id, distribution_plan_id, threadsdash_post_id,
             reason, root_cause, blocking_reason, excluded_from_metrics, metadata_json,
             created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(rendered_asset_id) DO UPDATE SET
              distribution_plan_id = COALESCE(excluded.distribution_plan_id, quarantined_assets.distribution_plan_id),
              threadsdash_post_id = COALESCE(excluded.threadsdash_post_id, quarantined_assets.threadsdash_post_id),
              reason = excluded.reason,
              root_cause = excluded.root_cause,
              blocking_reason = excluded.blocking_reason,
              excluded_from_metrics = 1,
              metadata_json = excluded.metadata_json,
              created_by = excluded.created_by
            """,
            (
                quarantine_id,
                asset["campaign_id"],
                rendered_asset_id,
                distribution_plan_id,
                threadsdash_post_id,
                reason,
                root_cause,
                blocking_reason or reason,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now,
                created_by,
            ),
        )
        self.record_event(
            "asset_quarantined",
            campaign_id=asset["campaign_id"],
            rendered_asset_id=rendered_asset_id,
            status="failure",
            message=f"Asset quarantined: {reason}",
            metadata={
                "reason": reason,
                "rootCause": root_cause,
                "blockingReason": blocking_reason or reason,
                "distributionPlanId": distribution_plan_id,
                "threadsdashPostId": threadsdash_post_id,
            },
            commit=False,
        )
        if commit:
            self.conn.commit()
        return self._active_quarantine_for_asset(rendered_asset_id) or {}

    def local_export_readiness(
        self, asset: dict[str, Any], latest_audit: dict[str, Any] | None
    ) -> dict[str, Any]:
        blocking: list[str] = []
        warnings: list[str] = []
        publishability = self.publishability_check(asset, latest_audit)
        blocking.extend(publishability.get("blockingReasons") or [])
        warnings.extend(publishability.get("warnings") or [])
        if asset["review_state"] != "approved":
            blocking.append(f"review_state:{asset['review_state']}")
        if not latest_audit:
            blocking.append("missing_audit")
        else:
            readiness = latest_audit.get("readinessSummary") or {}
            blocking_codes = readiness.get("blockingCodes") or []
            if blocking_codes:
                blocking.extend([f"audit_failed:{check}" for check in blocking_codes])
            for reason in readiness.get("blockingReasons") or []:
                blocking.append(f"upload_readiness:{reason}")
            if latest_audit.get("overallVerdict") == "fail":
                blocking.append("contentforge_verdict:fail")
            elif latest_audit.get("overallVerdict") == "warn":
                warnings.append("contentforge_verdict:warn")
            for warning in latest_audit.get("warnings") or []:
                warnings.append(f"audit_warning:{warning}")
        state = "blocked" if blocking else ("warning" if warnings else "ready")
        score = 100
        if state == "blocked":
            score -= 70
        elif state == "warning":
            score -= 10
        score -= min(30, len(set(warnings)) * 5)
        score -= min(40, len(set(blocking)) * 10)
        findings = [
            *readiness_findings_from_codes(
                blocking,
                severity="blocker",
                evidence={
                    "source": "local_export_readiness",
                    "renderedAssetId": asset.get("id"),
                },
            ),
            *readiness_findings_from_codes(
                warnings,
                severity="warning",
                evidence={
                    "source": "local_export_readiness",
                    "renderedAssetId": asset.get("id"),
                },
            ),
        ]
        return {
            "state": state,
            "operatorScore": max(0, score),
            "blockingReasons": sorted(set(blocking)),
            "warnings": sorted(set(warnings)),
            "findings": readiness_finding_payloads(findings),
            "publishability": publishability,
        }

    def explain_publishability(
        self,
        rendered_asset_id: str,
        *,
        distribution_plan_id: str | None = None,
    ) -> dict[str, Any]:
        asset = self.rendered_asset(rendered_asset_id)
        latest_audit = self._latest_audit_for_asset(rendered_asset_id)
        plan = None
        if distribution_plan_id:
            row = self.conn.execute(
                "SELECT * FROM distribution_plans WHERE id = ?",
                (distribution_plan_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"distribution plan not found: {distribution_plan_id}")
            plan = self._distribution_plan_payload(dict(row))
        return self.publishability_check(asset, latest_audit, distribution_plan=plan)

    def capture_publishability_rejection_evidence(
        self, rendered_asset_id: str
    ) -> dict[str, Any]:
        result = self.explain_publishability(rendered_asset_id)
        return self.capture_publishability_rejection_evidence_from_result(
            rendered_asset_id, result, commit=True
        )

    def capture_publishability_rejection_evidence_from_result(
        self,
        rendered_asset_id: str,
        result: dict[str, Any],
        *,
        commit: bool,
    ) -> dict[str, Any]:
        asset = self.rendered_asset(rendered_asset_id)
        now = self._utc_now()
        evidence_rows = [
            row
            for row in result.get("rejectionEvidence") or []
            if row.get("failedStage") == "discoverability_safety_pass"
        ]
        for row in evidence_rows:
            evidence_id = self._verification_id(
                "rejectev",
                rendered_asset_id,
                row.get("failedStage"),
                row.get("failureCategory"),
                row.get("matchedText"),
                row.get("sourceField"),
                row.get("policyVersion"),
            )
            self.conn.execute(
                """
                INSERT INTO asset_rejection_evidence
                (id, rendered_asset_id, source_asset_id, campaign_id, content_surface,
                 failed_stage, failure_category, matched_text, source_field, policy_version,
                 repairable, evidence_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rendered_asset_id, failed_stage, failure_category, matched_text, source_field, policy_version)
                DO UPDATE SET
                  evidence_json = excluded.evidence_json,
                  updated_at = excluded.updated_at
                """,
                (
                    evidence_id,
                    rendered_asset_id,
                    asset.get("source_asset_id"),
                    asset.get("campaign_id"),
                    self._normalize_content_surface(asset.get("content_surface")),
                    row.get("failedStage"),
                    row.get("failureCategory"),
                    row.get("matchedText"),
                    row.get("sourceField"),
                    row.get("policyVersion"),
                    1 if row.get("repairable", True) else 0,
                    json.dumps(
                        self._sanitize_for_storage(row),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                ),
            )
        if commit:
            self.conn.commit()
        captured_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM asset_rejection_evidence WHERE rendered_asset_id = ?",
            (rendered_asset_id,),
        ).fetchone()["c"]
        return {
            "schema": "campaign_factory.rejection_evidence_capture.v1",
            "renderedAssetId": rendered_asset_id,
            "failedStage": "discoverability_safety_pass" if evidence_rows else "",
            "capturedCount": int(captured_count or 0),
            "wouldWrite": True,
        }

    def capture_discoverability_gate_rejection_evidence(
        self,
        *,
        gate_result: dict[str, Any],
        failed_stage: str,
        campaign_id: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        content_surface: str = "reel",
        commit: bool,
    ) -> dict[str, Any]:
        now = self._utc_now()
        evidence_rows = gate_result.get("violations") or []
        captured_ids: list[str] = []
        for row in evidence_rows:
            evidence = {
                **row,
                "failedStage": failed_stage,
                "gate": gate_result.get("gate"),
                "gateSchema": gate_result.get("schema"),
            }
            evidence_id = self._verification_id(
                "rejectev",
                rendered_asset_id or "",
                source_asset_id or "",
                campaign_id or "",
                failed_stage,
                row.get("failureCategory"),
                row.get("matchedText"),
                row.get("sourceField"),
                row.get("policyVersion"),
            )
            self.conn.execute(
                """
                INSERT INTO asset_rejection_evidence
                (id, rendered_asset_id, source_asset_id, campaign_id, content_surface,
                 failed_stage, failure_category, matched_text, source_field, policy_version,
                 repairable, evidence_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  evidence_json = excluded.evidence_json,
                  updated_at = excluded.updated_at
                """,
                (
                    evidence_id,
                    rendered_asset_id,
                    source_asset_id,
                    campaign_id,
                    self._normalize_content_surface(content_surface),
                    failed_stage,
                    row.get("failureCategory"),
                    row.get("matchedText"),
                    row.get("sourceField"),
                    row.get("policyVersion"),
                    1 if row.get("repairable", True) else 0,
                    json.dumps(
                        self._sanitize_for_storage(evidence),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                ),
            )
            captured_ids.append(evidence_id)
        if commit:
            self.conn.commit()
        return {
            "schema": "campaign_factory.discoverability_gate_rejection_capture.v1",
            "failedStage": failed_stage if evidence_rows else "",
            "capturedCount": len(captured_ids),
            "evidenceIds": captured_ids,
            "wouldWrite": True,
        }

    def record_proof_run(
        self,
        *,
        campaign_id: str | None,
        rendered_asset_id: str,
        distribution_plan_id: str | None = None,
        threadsdash_draft_id: str | None = None,
        threadsdash_post_id: str | None = None,
        status: str = "started",
        current_state: str = "creative_approved",
        blocking_reason: str | None = None,
        root_cause: str | None = None,
        metrics_eligible: bool = False,
        metadata: dict[str, Any] | None = None,
        proof_run_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = self._utc_now()
        key = (
            proof_run_id
            or f"proof_{hashlib.sha256(':'.join(str(part or '') for part in (campaign_id, rendered_asset_id, distribution_plan_id, threadsdash_post_id)).encode('utf-8')).hexdigest()[:12]}"
        )
        self.conn.execute(
            """
            INSERT INTO proof_runs
            (id, campaign_id, rendered_asset_id, distribution_plan_id, threadsdash_draft_id,
             threadsdash_post_id, status, current_state, blocking_reason, root_cause,
             metrics_eligible, metadata_json, started_at, completed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              distribution_plan_id = excluded.distribution_plan_id,
              threadsdash_draft_id = excluded.threadsdash_draft_id,
              threadsdash_post_id = excluded.threadsdash_post_id,
              status = excluded.status,
              current_state = excluded.current_state,
              blocking_reason = excluded.blocking_reason,
              root_cause = excluded.root_cause,
              metrics_eligible = excluded.metrics_eligible,
              metadata_json = excluded.metadata_json,
              completed_at = excluded.completed_at,
              updated_at = excluded.updated_at
            """,
            (
                key,
                campaign_id,
                rendered_asset_id,
                distribution_plan_id,
                threadsdash_draft_id,
                threadsdash_post_id,
                status,
                current_state,
                blocking_reason,
                root_cause,
                1 if metrics_eligible else 0,
                json.dumps(
                    self._sanitize_for_storage(metadata or {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
                now
                if status in {"passed", "failed", "complete", "completed"}
                else None,
                now,
                now,
            ),
        )
        if commit:
            self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM proof_runs WHERE id = ?", (key,)
        ).fetchone()
        return dict(row) if row else {}

    def publishability_discoverability_fields(
        self,
        *,
        asset: dict[str, Any],
        caption_text: str,
        caption_context: dict[str, Any],
        post_caption: dict[str, Any],
    ) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = []
        candidates = [
            ("asset_caption", asset.get("caption")),
            ("caption_text", caption_text),
            ("caption_context_caption_text", caption_context.get("caption_text")),
            (
                "burned_caption_text",
                post_caption.get("burned_caption_text")
                or caption_context.get("burned_caption_text"),
            ),
            (
                "instagram_post_caption",
                post_caption.get("instagram_post_caption")
                or caption_context.get("instagram_post_caption"),
            ),
            (
                "caption_cta",
                post_caption.get("caption_cta") or caption_context.get("caption_cta"),
            ),
        ]
        seen: set[tuple[str, str]] = set()
        for source_field, value in candidates:
            if not isinstance(value, str) or not value.strip():
                continue
            key = (source_field, value)
            if key in seen:
                continue
            seen.add(key)
            fields.append((source_field, value))
        return fields

    def instagram_post_caption_quality(
        self, post_caption: dict[str, Any]
    ) -> dict[str, Any]:
        caption = str(post_caption.get("instagram_post_caption") or "").strip()
        burned = str(post_caption.get("burned_caption_text") or "").strip()
        hashtags = list(post_caption.get("hashtags") or [])
        reasons: list[str] = []
        if not caption:
            return {
                "passed": False,
                "reasons": ["blank_instagram_post_caption"],
                "policy": "simple_ig_post_caption_v1",
                "maxCharacters": 140,
                "maxLines": 3,
                "maxHashtags": 5,
            }
        lines = [line for line in caption.splitlines() if line.strip()]
        if len(caption) > 140:
            reasons.append("instagram_post_caption_too_long")
        if len(lines) > 3:
            reasons.append("instagram_post_caption_too_many_lines")
        if len(re.findall(r"#[A-Za-z0-9_]+", caption)) > 5 or len(hashtags) > 5:
            reasons.append("instagram_post_caption_too_many_hashtags")
        if re.search(
            r"https?://|www\.|link\s*in\s*bio|dm\s+me|message\s+me|text\s+me|telegram|whatsapp|onlyfans|fansly",
            caption,
            re.IGNORECASE,
        ):
            reasons.append("instagram_post_caption_platform_risk")
        caption_words = re.findall(r"[A-Za-z0-9']+", caption.lower())
        burned_words = re.findall(r"[A-Za-z0-9']+", burned.lower())
        if burned and caption.lower() == burned.lower() and len(burned_words) > 8:
            reasons.append("instagram_post_caption_copied_long_burned_caption")
        return {
            "passed": not reasons,
            "reasons": sorted(set(reasons)),
            "policy": "simple_ig_post_caption_v1",
            "maxCharacters": 140,
            "maxLines": 3,
            "maxHashtags": 5,
            "characterCount": len(caption),
            "lineCount": len(lines),
            "wordCount": len(caption_words),
            "hashtagCount": max(
                len(re.findall(r"#[A-Za-z0-9_]+", caption)), len(hashtags)
            ),
        }

    def caption_quality_repair_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        assets = self._surface_report_assets(
            creator=creator, campaign_slug=campaign_slug
        )
        if content_surface:
            normalized_surface = self._normalize_content_surface(content_surface)
            assets = [
                asset
                for asset in assets
                if self._normalize_content_surface(
                    asset.get("content_surface") or asset.get("source_content_surface")
                )
                == normalized_surface
            ]
        candidates: list[dict[str, Any]] = []
        blocked_by_caption_quality = 0
        recoverable_by_caption_rewrite = 0
        recoverable_by_hashtag_trim = 0
        recoverable_by_cta_removal = 0
        unrecoverable = 0
        for asset in assets:
            surface = self._normalize_content_surface(
                asset.get("content_surface") or asset.get("source_content_surface")
            )
            if surface == "story":
                continue
            publishability = self.explain_publishability(str(asset["id"]))
            failure_reasons = list(
                publishability.get("publishability_failure_reasons") or []
            )
            if "instagram_post_caption_quality_failed" not in failure_reasons:
                continue
            blocked_by_caption_quality += 1
            non_caption_blockers = sorted(
                reason
                for reason in failure_reasons
                if reason
                not in {
                    "instagram_post_caption_quality_failed",
                    "unsafe_reel_caption_link_or_dm_reference",
                }
            )
            post_caption_quality = (
                publishability.get("instagramPostCaptionQuality")
                if isinstance(publishability.get("instagramPostCaptionQuality"), dict)
                else {}
            )
            quality_reasons = list(post_caption_quality.get("reasons") or [])
            current_caption = str(publishability.get("instagram_post_caption") or "")
            suggested_caption = self.suggest_simple_instagram_post_caption(
                asset_id=str(asset["id"]),
                current_caption=current_caption,
                burned_caption=str(publishability.get("burned_caption_text") or ""),
            )
            suggested_payload = {
                "instagram_post_caption": suggested_caption,
                "hashtags": [],
                "burned_caption_text": str(
                    publishability.get("burned_caption_text") or ""
                ),
            }
            suggested_quality = self.instagram_post_caption_quality(suggested_payload)
            discoverability_contract = self.discoverability_safe_content_contract(
                suggested_caption
            )
            would_pass = bool(
                suggested_quality.get("passed")
                and discoverability_contract.get("discoverabilitySafe")
                and not non_caption_blockers
            )
            recovery_class = self.caption_quality_recovery_class(quality_reasons)
            if non_caption_blockers:
                unrecoverable += 1
            elif recovery_class == "recoverableByHashtagTrim":
                recoverable_by_hashtag_trim += 1
            elif recovery_class == "recoverableByCTARemoval":
                recoverable_by_cta_removal += 1
            else:
                recoverable_by_caption_rewrite += 1
            if len(candidates) < max(1, int(limit or 200)):
                candidates.append(
                    {
                        "assetId": asset["id"],
                        "contentSurface": surface,
                        "currentCaption": current_caption,
                        "failureReasons": failure_reasons,
                        "qualityFailureReasons": quality_reasons,
                        "nonCaptionBlockers": non_caption_blockers,
                        "recoveryClass": "unrecoverable"
                        if non_caption_blockers
                        else recovery_class,
                        "suggestedInstagramPostCaption": suggested_caption,
                        "suggestedInstagramPostCaptionHash": self._text_hash(
                            suggested_caption
                        )
                        if suggested_caption
                        else "",
                        "suggestedCaptionQuality": suggested_quality,
                        "suggestedDiscoverabilitySafe": bool(
                            discoverability_contract.get("discoverabilitySafe")
                        ),
                        "wouldPassQualityGate": would_pass,
                        "burnedCaptionText": publishability.get("burned_caption_text")
                        or "",
                        "burnedCaptionHash": publishability.get("burned_caption_hash")
                        or "",
                        "wouldWrite": False,
                    }
                )
        return {
            "schema": "campaign_factory.caption_quality_repair_plan.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": self._normalize_content_surface(content_surface)
            if content_surface
            else "",
            "blockedByCaptionQuality": blocked_by_caption_quality,
            "recoverableByCaptionRewrite": recoverable_by_caption_rewrite,
            "recoverableByHashtagTrim": recoverable_by_hashtag_trim,
            "recoverableByCTARemoval": recoverable_by_cta_removal,
            "unrecoverable": unrecoverable,
            "replacementCandidates": candidates,
            "wouldWrite": False,
        }

    def caption_quality_recovery_class(self, quality_reasons: list[str]) -> str:
        reason_set = set(quality_reasons)
        if reason_set and reason_set <= {
            "instagram_post_caption_too_many_hashtags",
            "instagram_post_caption_too_many_lines",
        }:
            return "recoverableByHashtagTrim"
        if "instagram_post_caption_platform_risk" in reason_set:
            return "recoverableByCTARemoval"
        return "recoverableByCaptionRewrite"

    def suggest_simple_instagram_post_caption(
        self, *, asset_id: str, current_caption: str, burned_caption: str
    ) -> str:
        start = int(hashlib.sha256(asset_id.encode("utf-8")).hexdigest()[:8], 16) % len(
            SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL
        )
        current_normalized = " ".join(current_caption.lower().split())
        burned_normalized = " ".join(burned_caption.lower().split())
        for offset in range(len(SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL)):
            suggestion = SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL[
                (start + offset) % len(SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL)
            ]
            normalized = suggestion.lower()
            if normalized == current_normalized or normalized == burned_normalized:
                continue
            quality = self.instagram_post_caption_quality(
                {
                    "instagram_post_caption": suggestion,
                    "hashtags": [],
                    "burned_caption_text": burned_caption,
                }
            )
            discoverability = self.discoverability_safe_content_contract(suggestion)
            if quality.get("passed") and discoverability.get("discoverabilitySafe"):
                return suggestion
        return SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL[0]

    def publishability_check(
        self,
        asset: dict[str, Any],
        latest_audit: dict[str, Any] | None = None,
        *,
        distribution_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        caption_text = str(asset.get("caption") or "").strip()
        raw_asset_metadata = asset.get("metadata")
        if not isinstance(raw_asset_metadata, dict):
            try:
                raw_asset_metadata = json.loads(asset.get("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                raw_asset_metadata = {}
        creative_approval_required = asset_requires_creative_approval(asset)
        creative_approval = (
            self._creative_approval_store.status_for_asset(asset)
            if creative_approval_required
            else {"state": "not_required"}
        )
        output_path = str(
            asset.get("campaign_path")
            or asset.get("output_path")
            or asset.get("filePath")
            or ""
        )
        filename = str(asset.get("filename") or Path(output_path).name)
        sidecar = self._caption_lineage_sidecar(output_path)
        caption_context = load_context_json(asset.get("caption_outcome_context_json"))
        if not caption_context and isinstance(asset.get("captionOutcomeContext"), dict):
            caption_context = asset["captionOutcomeContext"]
        variant_lineage = self._variant_lineage_for_asset(asset["id"])
        if variant_lineage and isinstance(caption_context, dict):
            caption_context = {**caption_context, **variant_lineage}
        caption_generation = self.caption_generation_payload(asset)
        generated_lineage = (
            caption_generation.get("generatedAssetLineage")
            if isinstance(caption_generation.get("generatedAssetLineage"), dict)
            else {}
        )
        if isinstance(caption_context, dict) and generated_lineage:
            for key in ("captionPlacementPolicy", "captionPlacementDecision"):
                if (
                    caption_context.get(key) is None
                    and generated_lineage.get(key) is not None
                ):
                    caption_context[key] = generated_lineage[key]
        if (
            isinstance(caption_context, dict)
            and caption_context
            and not caption_context.get("schema")
        ):
            caption_context = {
                "schema": "campaign_factory.caption_outcome_context.v1",
                **caption_context,
            }
        placement_policy = self.normalize_caption_placement_policy(
            (caption_context or {}).get("captionPlacementPolicy")
            or (caption_context or {}).get("caption_placement_policy")
        )
        placement_decision = (caption_context or {}).get("captionPlacementDecision")
        placement_qc_passed = (
            placement_policy == "focal_safe_v1"
            and isinstance(placement_decision, dict)
            and placement_decision.get("status") == "passed"
        )
        render_recipe = (
            (caption_context or {}).get("render_recipe")
            or (sidecar.get("captionOutcomeContext") or {}).get("render_recipe")
            or sidecar.get("renderRecipe")
            or sidecar.get("recipe")
            or asset.get("recipe")
        )
        lower_hints = " ".join(
            str(value or "").lower() for value in (output_path, filename, render_recipe)
        )
        quarantine = self._active_quarantine_for_asset(asset["id"])
        audio_intent, audio_id = self._audio_selection_for_asset(asset)
        audio_segment = self._audio_segment_for_asset(audio_intent)
        cover_frame = self._cover_frame_for_asset(asset, caption_context)
        post_caption = self._instagram_post_caption_for_asset(
            asset, caption_context, distribution_plan=distribution_plan
        )
        ai_disclosure = self.ai_disclosure_status(
            asset=asset,
            post_caption=post_caption,
            creative_approval=creative_approval,
        )
        post_caption_quality = self.instagram_post_caption_quality(post_caption)
        trust_blockers, trust_statuses = self._content_trust_status_blockers(
            asset,
            latest_audit,
            caption_context if isinstance(caption_context, dict) else {},
        )
        asset_content_surface = self._normalize_content_surface(
            (distribution_plan or {}).get("contentSurface")
            or (distribution_plan or {}).get("content_surface")
            or asset.get("content_surface")
        )
        is_reel_surface = asset_content_surface == "reel"
        approved = asset.get("review_state") == "approved"
        caption_hash = asset.get("caption_hash") or (caption_context or {}).get(
            "caption_hash"
        )
        export_caption_hash = (
            (caption_context or {}).get("caption_hash")
            or post_caption.get("burned_caption_hash")
            or caption_hash
        )
        content_fingerprint = asset.get("content_hash") or asset.get("contentHash")
        readiness_blockers = list(
            ((latest_audit or {}).get("readinessSummary") or {}).get("blockingReasons")
            or []
        )
        readiness_blockers.extend(
            ((latest_audit or {}).get("readinessSummary") or {}).get("blockingCodes")
            or []
        )
        audit_warning_codes = set(
            ((latest_audit or {}).get("readinessSummary") or {}).get("warningCodes")
            or []
        )
        audit_warning_codes.update(
            latest_audit.get("warnings") or [] if latest_audit else []
        )
        placement_warning_codes = sorted(
            audit_warning_codes & CAPTION_PLACEMENT_QC_WARNING_CODES
        )
        if placement_warning_codes:
            placement_qc_passed = False
        if (latest_audit or {}).get("overallVerdict") == "fail":
            readiness_blockers.append("contentforge_verdict_fail")
        embedded_audio_required = self._audio_intent_claims_embedded_media(audio_intent)
        embedded_audio_verified = (
            self._embedded_audio_verified(output_path)
            if embedded_audio_required
            else None
        )
        captioned_render_present = (
            (bool(caption_text) and "passthrough" not in lower_hints)
            if is_reel_surface
            else bool(output_path)
        )
        visible_caption_verification = (
            captioned_render_present if is_reel_surface else True
        )
        expected_visual_verification = "passthrough" not in lower_hints
        discoverability_fields = self.publishability_discoverability_fields(
            asset=asset,
            caption_text=caption_text,
            caption_context=caption_context
            if isinstance(caption_context, dict)
            else {},
            post_caption=post_caption,
        )
        discoverability_contract = self.discoverability_safe_content_contract(
            *(value for _, value in discoverability_fields)
        )
        discoverability_evidence = self._discoverability_evidence_for_fields(
            discoverability_fields
        )
        reel_caption_safety_violations = (
            list(discoverability_contract["blockedTerms"]) if is_reel_surface else []
        )
        burned_caption_quality_passed = (
            self._reference_hook_is_schedule_safe(caption_text)
            if is_reel_surface
            else True
        )
        motion_gate = self.motion_qc_gate(asset)
        checks = {
            "creative_approved": approved,
            "captioned_render_present": captioned_render_present,
            "visible_caption_verification": visible_caption_verification,
            "expected_visual_verification": expected_visual_verification,
            "content_fingerprint_present": bool(content_fingerprint),
            "caption_hash_present": bool(caption_hash),
            "captionOutcomeContext_present": bool(caption_context),
            "instagram_post_caption_present": bool(
                post_caption.get("instagram_post_caption")
            ),
            "caption_placement_qc_passed": placement_qc_passed
            if is_reel_surface
            else True,
            "audio_assigned": self._audio_intent_is_attached(audio_intent, audio_id)
            if is_reel_surface
            else True,
            "embedded_audio_verified": embedded_audio_verified is not False,
            "reel_caption_account_safety_passed": not reel_caption_safety_violations,
            "burned_caption_quality_passed": burned_caption_quality_passed,
            "discoverability_safe": discoverability_contract["discoverabilitySafe"]
            if is_reel_surface
            else True,
            "instagram_post_caption_quality_passed": post_caption_quality["passed"]
            if asset_content_surface != "story"
            else True,
            "operator_visual_review_passed": not self._requires_operator_visual_review_for_handoff(
                asset
            )
            if is_reel_surface
            else True,
            "visual_qc_passed": trust_statuses["visualQcStatus"] == "passed",
            "identity_verification_passed": trust_statuses["identityVerificationStatus"]
            == "passed",
            "readiness_checks_pass": bool(latest_audit) and not readiness_blockers,
            "quarantine_clear": not bool(quarantine),
            "creative_approval_valid": creative_approval.get("state")
            in {"approved", "not_required"},
            "ai_disclosure_resolved": ai_disclosure["resolved"] is True,
            **motion_gate["checks"],
        }
        failures: list[str] = []
        warnings: list[str] = []
        if not approved:
            failures.append("not_approved")
        if not captioned_render_present:
            failures.append("missing_burned_captions")
        if (
            asset_content_surface == "feed_single"
            and str(asset.get("media_type") or "").lower() != "image"
        ):
            failures.append("feed_single_requires_image")
        if not expected_visual_verification:
            failures.append("wrong_visual")
        if not content_fingerprint:
            failures.append("missing_content_fingerprint")
        if not caption_hash and asset_content_surface != "story":
            failures.append("missing_caption_hash")
        if not caption_context:
            failures.append("missing_caption_outcome_context")
        if (
            not post_caption.get("instagram_post_caption")
            and asset_content_surface != "story"
        ):
            failures.append("missing_instagram_post_caption")
        if asset_content_surface != "story" and not post_caption_quality["passed"]:
            failures.append("instagram_post_caption_quality_failed")
        if is_reel_surface and not placement_qc_passed:
            failures.append("caption_placement_qc_failed")
        if is_reel_surface and not checks["audio_assigned"]:
            failures.append("missing_audio")
        if embedded_audio_verified is False:
            failures.append("embedded_audio_missing")
        if is_reel_surface and reel_caption_safety_violations:
            failures.append("unsafe_reel_caption_link_or_dm_reference")
        if is_reel_surface and caption_text and not burned_caption_quality_passed:
            failures.append("burned_caption_quality_failed")
        if is_reel_surface and not checks["operator_visual_review_passed"]:
            failures.append("operator_visual_review_required")
        failures.extend(motion_gate["failures"])
        if not checks["creative_approval_valid"]:
            failures.append(
                str(
                    creative_approval.get("blockingReason")
                    or "creative_approval_missing"
                )
            )
        if not checks["ai_disclosure_resolved"]:
            failures.append(AI_DISCLOSURE_BLOCKER)
        failures.extend(trust_blockers)
        if not checks["readiness_checks_pass"]:
            failures.append("missing_audit" if not latest_audit else "readiness_failed")
        if quarantine:
            failures.append("quarantined_asset")
        publishability_findings = readiness_findings_from_codes(
            failures,
            severity="blocker",
            evidence={
                "source": "publishability",
                "renderedAssetId": asset.get("id"),
            },
        )
        warning_findings = readiness_findings_from_codes(
            warnings,
            severity="warning",
            evidence={
                "source": "publishability",
                "renderedAssetId": asset.get("id"),
            },
        )
        failures = readiness_finding_codes(publishability_findings, severity="blocker")
        asset_state = (
            "publishable_candidate" if not failures else "approved_but_not_publishable"
        )
        lifecycle_state = (
            "publishable_candidate"
            if not failures
            else ("creative_approved" if approved else "rendered")
        )
        root_cause = None
        if quarantine:
            root_cause = quarantine.get("root_cause")
        elif "missing_burned_captions" in failures or "wrong_visual" in failures:
            root_cause = "wrong_approved_asset"
        blocking_reason = failures[0] if failures else None
        manifest = None
        deferred_audio_failures = {"missing_audio", "embedded_audio_missing"}
        audio_deferred_to_notify_handoff = bool(
            failures
            and set(failures).issubset(deferred_audio_failures)
            and is_reel_surface
        )
        distribution_content_surface = self._normalize_content_surface(
            (distribution_plan or {}).get("contentSurface")
            or (distribution_plan or {}).get("content_surface")
        )
        distribution_surface = (
            normalize_distribution_surface((distribution_plan or {}).get("surface"))
            if distribution_plan
            else None
        )
        ig_media_type = self._ig_media_type_for_surface(
            distribution_content_surface, str(asset.get("media_type") or "video")
        )
        instagram_trial_reels = bool(
            (distribution_plan or {}).get("instagramTrialReels")
            or (distribution_plan or {}).get("instagram_trial_reels")
        )
        trial_graduation_strategy = (distribution_plan or {}).get(
            "trialGraduationStrategy"
        ) or (distribution_plan or {}).get("trial_graduation_strategy")
        trial_group_id = (distribution_plan or {}).get("trialGroupId") or (
            distribution_plan or {}
        ).get("trial_group_id")
        if (
            not failures or audio_deferred_to_notify_handoff
        ) and distribution_plan is not None:
            manifest = {
                "manifest_version": 2,
                "asset_id": asset["id"],
                "rendered_asset_id": asset["id"],
                "source_asset_id": asset.get("source_asset_id"),
                "render_file_id": self._verification_id(
                    "render_file", asset["id"], filename, content_fingerprint
                ),
                "content_fingerprint": content_fingerprint,
                "content_hash": content_fingerprint,
                "caption_hash": export_caption_hash,
                "captionOutcomeContext": caption_context,
                "instagram_post_caption": post_caption["instagram_post_caption"],
                "instagramPostCaption": post_caption["instagram_post_caption"],
                "instagram_post_caption_hash": post_caption[
                    "instagram_post_caption_hash"
                ],
                "caption_cta": post_caption["caption_cta"],
                "hashtags": post_caption["hashtags"],
                "post_caption_style": post_caption["post_caption_style"],
                "burned_caption_text": post_caption["burned_caption_text"],
                "burned_caption_hash": post_caption["burned_caption_hash"],
                "ai_disclosure": ai_disclosure,
                "visualQcStatus": trust_statuses["visualQcStatus"],
                "identityVerificationStatus": trust_statuses[
                    "identityVerificationStatus"
                ],
                "visualQc": {"status": trust_statuses["visualQcStatus"]},
                "identityVerification": {
                    "status": trust_statuses["identityVerificationStatus"]
                },
                "visual_verification_id": self._verification_id(
                    "visual_verification",
                    asset["id"],
                    content_fingerprint,
                    render_recipe,
                ),
                "caption_verification_id": self._verification_id(
                    "caption_verification",
                    asset["id"],
                    export_caption_hash,
                    render_recipe,
                ),
                "audio_id": audio_id
                or (
                    "deferred_to_notify_handoff"
                    if audio_deferred_to_notify_handoff
                    else "not_required"
                ),
                "distribution_plan_id": distribution_plan["id"],
                "content_surface": distribution_content_surface,
                "contentSurface": distribution_content_surface,
                "distribution_surface": distribution_surface,
                "ig_media_type": ig_media_type,
                "igMediaType": ig_media_type,
                "instagram_trial_reels": instagram_trial_reels,
                "trial_graduation_strategy": trial_graduation_strategy
                if instagram_trial_reels
                else None,
                "trial_group_id": trial_group_id if instagram_trial_reels else None,
                "exported_by_system": "campaign_factory",
                "exported_at": self._utc_now(),
                "audioDeferredToHandoff": audio_deferred_to_notify_handoff,
                "surfaceReadiness": {
                    "canHandoff": True,
                    "scheduleSafe": not audio_deferred_to_notify_handoff,
                    "blockingReasons": failures
                    if audio_deferred_to_notify_handoff
                    else [],
                },
            }
            manifest["mediaItems"] = [
                {
                    "mediaPath": output_path,
                    "mediaHash": content_fingerprint,
                    "mediaType": str(asset.get("media_type") or "video").lower(),
                    "componentIndex": 0,
                }
            ]
            if audio_segment:
                manifest["audio_segment"] = audio_segment
            if cover_frame:
                manifest["cover_frame"] = cover_frame
            if variant_lineage:
                manifest.update(
                    {
                        "concept_id": variant_lineage.get("concept_id"),
                        "parent_reel_id": variant_lineage.get("parent_reel_id"),
                        "parent_asset_id": variant_lineage.get("parent_asset_id"),
                        "variant_family_id": variant_lineage.get("variant_family_id"),
                        "variant_id": variant_lineage.get("variant_id"),
                        "variant_index": variant_lineage.get("variant_index"),
                        "variant_operations": variant_lineage.get("variant_operations"),
                    }
                )
            if isinstance(caption_context, dict):
                caption_family_id = caption_context.get(
                    "caption_family_id"
                ) or caption_context.get("captionFamilyId")
                caption_version_id = caption_context.get(
                    "caption_version_id"
                ) or caption_context.get("captionVersionId")
                if caption_family_id:
                    manifest["caption_family_id"] = caption_family_id
                if caption_version_id:
                    manifest["caption_version_id"] = caption_version_id
        return {
            "schema": "campaign_factory.publishability_check.v1",
            "decision": "pass" if not failures else "blocked",
            "asset_state": asset_state,
            "assetState": asset_state,
            "lifecycle_state": lifecycle_state,
            "publishableCandidate": not failures,
            "exportable": not failures
            and distribution_plan is not None
            and manifest is not None,
            "draftExportable": audio_deferred_to_notify_handoff
            and distribution_plan is not None
            and manifest is not None,
            "approved": approved,
            "captionedRenderPresent": captioned_render_present,
            "captioned_render_present": captioned_render_present,
            "visibleCaptionVerification": "heuristic_pass"
            if visible_caption_verification
            else "not_verified",
            "visible_caption_verification": visible_caption_verification,
            "expectedVisualVerification": "heuristic_pass"
            if expected_visual_verification
            else "failed",
            "expected_visual_verification": expected_visual_verification,
            "readinessChecksPass": checks["readiness_checks_pass"],
            "readiness_checks_pass": checks["readiness_checks_pass"],
            "renderRecipe": render_recipe,
            "mediaPath": output_path,
            "captionLineageSidecarPresent": bool(sidecar),
            "contentFingerprint": content_fingerprint,
            "content_fingerprint": content_fingerprint,
            "captionHash": export_caption_hash,
            "caption_hash": export_caption_hash,
            "captionOutcomeContext": caption_context,
            **post_caption,
            "instagramPostCaptionQuality": post_caption_quality,
            "instagram_post_caption_quality": post_caption_quality,
            "captionPlacementPolicy": placement_policy,
            "captionPlacementDecision": placement_decision,
            "discoverabilitySafe": discoverability_contract["discoverabilitySafe"]
            if is_reel_surface
            else True,
            "discoverabilityContract": discoverability_contract
            if is_reel_surface
            else {
                **discoverability_contract,
                "discoverabilitySafe": True,
                "blockedTerms": [],
                "blockedReason": "",
            },
            "rejectionEvidence": discoverability_evidence
            if is_reel_surface and reel_caption_safety_violations
            else [],
            "reelCaptionAccountSafetyViolations": reel_caption_safety_violations,
            "reel_caption_account_safety_violations": reel_caption_safety_violations,
            "burnedCaptionQualityPassed": burned_caption_quality_passed,
            "burned_caption_quality_passed": burned_caption_quality_passed,
            "visualQcStatus": trust_statuses["visualQcStatus"],
            "identityVerificationStatus": trust_statuses["identityVerificationStatus"],
            **variant_lineage,
            "audioIntent": audio_intent,
            "audio_id": audio_id,
            "audio_segment": audio_segment,
            "cover_frame": cover_frame,
            "motionSpecificQcRequirements": motion_gate["requirements"],
            "motionSpecificQcReceipt": motion_gate["receipt"],
            "creativeApproval": {
                key: value
                for key, value in creative_approval.items()
                if key != "approval"
            },
            "aiDisclosure": ai_disclosure,
            "checks": checks,
            "failureReasons": failures,
            "publishability_failure_reasons": failures,
            "blockingReasons": [f"publishability:{reason}" for reason in failures],
            "blockingReason": blocking_reason,
            "rootCause": root_cause,
            "nextOperatorAction": "replace_with_verified_captioned_asset"
            if root_cause == "wrong_approved_asset"
            else (
                "resolve_publishability_failures"
                if failures
                else "export_to_threadsdashboard"
            ),
            "quarantine": quarantine,
            "metricsEligible": False,
            "metrics_eligible": False,
            "handoff_manifest": manifest,
            "contentSurface": distribution_content_surface
            if distribution_plan is not None
            else self._normalize_content_surface(asset.get("content_surface")),
            "content_surface": distribution_content_surface
            if distribution_plan is not None
            else self._normalize_content_surface(asset.get("content_surface")),
            "distributionSurface": distribution_surface,
            "distribution_surface": distribution_surface,
            "igMediaType": ig_media_type
            if distribution_plan is not None
            else self._ig_media_type_for_surface(
                self._normalize_content_surface(asset.get("content_surface")),
                str(asset.get("media_type") or "video"),
            ),
            "ig_media_type": ig_media_type
            if distribution_plan is not None
            else self._ig_media_type_for_surface(
                self._normalize_content_surface(asset.get("content_surface")),
                str(asset.get("media_type") or "video"),
            ),
            "instagramTrialReels": instagram_trial_reels,
            "instagram_trial_reels": instagram_trial_reels,
            "trialGraduationStrategy": trial_graduation_strategy
            if instagram_trial_reels
            else None,
            "trial_graduation_strategy": trial_graduation_strategy
            if instagram_trial_reels
            else None,
            "trialGroupId": trial_group_id if instagram_trial_reels else None,
            "trial_group_id": trial_group_id if instagram_trial_reels else None,
            "warnings": sorted(set(warnings)),
            "findings": readiness_finding_payloads(
                [*publishability_findings, *warning_findings]
            ),
        }
