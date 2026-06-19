from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .caption_outcome import load_context_json
from .config import Settings
from .persistence import json_load

CONTENTFORGE_VARIANT_PRESETS = {"caption_safe", "caption_safe_v2", "strong_safe", "subtle", "balanced", "strong"}
CONTENTFORGE_VARIANT_PACK_SCHEMAS = {"contentforge.variant_pack.v1", "contentforge.variant_pack.v2"}
DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS = 14


class VariantLineageRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        utc_now: Callable[[], str],
        sha256_file: Callable[[Any], str],
        sanitize_for_storage: Callable[[Any], Any],
        normalize_content_surface: Callable[[str | None], str],
        urlopen: Callable[..., Any],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        rendered_asset: Callable[[str], dict[str, Any]],
        explain_publishability: Callable[..., dict[str, Any]],
        capture_publishability_rejection_evidence_from_result: Callable[..., dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        audio_selection_for_asset: Callable[[dict[str, Any]], tuple[dict[str, Any], str | None]],
        record_event: Callable[..., dict[str, Any]],
        caption_version_by_id: Callable[[str | None], dict[str, Any] | None],
        model_slug_for_campaign: Callable[[str], str],
        campaign_dirs: Callable[[str, str], dict[str, Any]],
        latest_audit_for_asset: Callable[[str], dict[str, Any] | None],
        content_trust_status_blockers: Callable[..., tuple[list[str], dict[str, str]]],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        aggregate_performance: Callable[..., dict[str, Any]],
        register_variant_asset: Callable[..., dict[str, Any]] | None = None,
        contentforge_variant_presets: set[str] | None = None,
        contentforge_variant_pack_schemas: set[str] | None = None,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._utc_now = utc_now
        self._sha256_file = sha256_file
        self._sanitize_for_storage = sanitize_for_storage
        self._normalize_content_surface = normalize_content_surface
        self._urlopen = urlopen
        self.campaign_by_slug = campaign_by_slug
        self.rendered_asset = rendered_asset
        self.explain_publishability = explain_publishability
        self._capture_publishability_rejection_evidence_from_result = capture_publishability_rejection_evidence_from_result
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._audio_selection_for_asset = audio_selection_for_asset
        self.record_event = record_event
        self._caption_version_by_id = caption_version_by_id
        self._model_slug_for_campaign = model_slug_for_campaign
        self.campaign_dirs = campaign_dirs
        self._latest_audit_for_asset = latest_audit_for_asset
        self._content_trust_status_blockers = content_trust_status_blockers
        self._instagram_post_caption_for_asset = instagram_post_caption_for_asset
        self._performance_snapshot_payload = performance_snapshot_payload
        self._aggregate_performance = aggregate_performance
        self._register_variant_asset = register_variant_asset or self.register_variant_asset
        self._contentforge_variant_presets = contentforge_variant_presets or CONTENTFORGE_VARIANT_PRESETS
        self._contentforge_variant_pack_schemas = contentforge_variant_pack_schemas or CONTENTFORGE_VARIANT_PACK_SCHEMAS

    def register_parent_reel(
        self,
        rendered_asset_id: str,
        *,
        operator: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        asset = self.rendered_asset(rendered_asset_id)
        content_surface = self._normalize_content_surface(asset.get("content_surface"))
        if content_surface == "reel":
            publishability = self.explain_publishability(rendered_asset_id)
            if not publishability.get("publishableCandidate"):
                self._capture_publishability_rejection_evidence_from_result(
                    rendered_asset_id,
                    publishability,
                    commit=True,
                )
                raise ValueError(f"parent reel must be publishable_candidate: {publishability.get('failureReasons') or publishability.get('publishability_failure_reasons')}")
        else:
            readiness = self._surface_handoff_readiness_for_asset(asset)
            if not readiness.get("canHandoff"):
                raise ValueError(f"parent surface asset must be handoff-ready: {readiness.get('blockingReasons')}")
        now = self._utc_now()
        campaign_id = asset["campaign_id"]
        concept_id = f"concept_{hashlib.sha256(f'{campaign_id}:{rendered_asset_id}'.encode('utf-8')).hexdigest()[:12]}"
        parent_reel_id = f"parent_{hashlib.sha256(f'parent:{campaign_id}:{rendered_asset_id}'.encode('utf-8')).hexdigest()[:12]}"
        caption_context = load_context_json(asset.get("caption_outcome_context_json"))
        audio_intent, audio_id = self._audio_selection_for_asset(asset)
        creator = asset.get("creator_model") or asset.get("creator_mix") or caption_context.get("creator_model") or caption_context.get("creator_mix")
        source = self.conn.execute("SELECT * FROM source_assets WHERE id = ?", (asset["source_asset_id"],)).fetchone()
        source_fingerprint = source["content_hash"] if source else None
        payload = {
            "operator": operator,
            "audioIntent": audio_intent,
            **(metadata or {}),
        }
        self.conn.execute(
            """
            INSERT INTO concepts
            (id, campaign_id, creator, parent_reel_id, parent_asset_id, source_asset_id,
             source_fingerprint, content_fingerprint, caption_hash, audio_id, status,
             metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, parent_asset_id) DO UPDATE SET
              creator = excluded.creator,
              source_asset_id = excluded.source_asset_id,
              source_fingerprint = excluded.source_fingerprint,
              content_fingerprint = excluded.content_fingerprint,
              caption_hash = excluded.caption_hash,
              audio_id = excluded.audio_id,
              status = excluded.status,
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                concept_id,
                campaign_id,
                creator,
                parent_reel_id,
                rendered_asset_id,
                asset["source_asset_id"],
                source_fingerprint,
                asset.get("content_hash"),
                asset.get("caption_hash") or caption_context.get("caption_hash"),
                audio_id,
                status,
                json.dumps(self._sanitize_for_storage(payload), ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            UPDATE rendered_assets
            SET concept_id = ?, parent_reel_id = ?, parent_asset_id = COALESCE(parent_asset_id, id), updated_at = ?
            WHERE id = ?
            """,
            (concept_id, parent_reel_id, now, rendered_asset_id),
        )
        self.record_event(
            "parent_reel_registered",
            campaign_id=campaign_id,
            source_asset_id=asset["source_asset_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message=f"Parent reel registered: {rendered_asset_id}",
            metadata={"conceptId": concept_id, "parentReelId": parent_reel_id, "operator": operator},
            commit=False,
        )
        self.conn.commit()
        return self.concept_payload(self.conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone())

    def variant_plan(
        self,
        *,
        parent_asset_id: str,
        caption_version_id: str | None = None,
        count: int = 10,
        contentforge_preset: str = "caption_safe",
        cooldown_days: int = DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS,
    ) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("count must be positive")
        preset = contentforge_preset if contentforge_preset in self._contentforge_variant_presets else "caption_safe"
        asset = self.rendered_asset(parent_asset_id)
        concept = self.concept_for_parent_asset(parent_asset_id)
        caption_version = self._caption_version_by_id(caption_version_id) if caption_version_id else None
        caption_lineage_ok = not caption_version_id or (
            caption_version is not None and caption_version.get("parentAssetId") == parent_asset_id
        )
        can_generate = (
            concept is not None
            and self.explain_publishability(parent_asset_id).get("publishableCandidate")
            and caption_lineage_ok
        )
        family_key = ":".join(str(part or "") for part in (asset["campaign_id"], parent_asset_id, caption_version_id, preset, count))
        variant_family_id = f"vfam_{hashlib.sha256(family_key.encode('utf-8')).hexdigest()[:12]}"
        planned = [
            {
                "variantIndex": idx,
                "operationSet": preset,
                "operations": [
                    {"type": "contentforge_variant_pack", "preset": preset},
                    {
                        "type": "preserve_parent_lineage",
                        "parentAssetId": parent_asset_id,
                        "captionFamilyId": caption_version.get("captionFamilyId") if caption_version else None,
                        "captionVersionId": caption_version_id,
                    },
                ],
                "qualityGate": "contentforge_upload_ready_and_recommended",
            }
            for idx in range(1, count + 1)
        ]
        return {
            "schema": "campaign_factory.variant_plan.v1",
            "parentAssetId": parent_asset_id,
            "parentReelId": concept.get("parentReelId") if concept else None,
            "conceptId": concept.get("conceptId") if concept else None,
            "captionFamilyId": caption_version.get("captionFamilyId") if caption_version else None,
            "captionVersionId": caption_version_id,
            "variantFamilyId": variant_family_id,
            "requestedVariants": count,
            "contentforgePreset": preset,
            "cooldownDays": cooldown_days,
            "canGenerate": bool(can_generate),
            "blockingReason": None if can_generate else ("caption_version_not_found_for_parent" if not caption_lineage_ok else "parent_reel_not_registered_or_not_publishable"),
            "plannedOperations": planned,
            "wouldWrite": False,
        }

    def generate_variants(
        self,
        *,
        parent_asset_id: str,
        caption_version_id: str | None = None,
        count: int = 10,
        contentforge_preset: str = "caption_safe",
        contentforge_base_url: str | None = None,
        source_media_path: str | None = None,
        contentforge_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        plan = self.variant_plan(
            parent_asset_id=parent_asset_id,
            caption_version_id=caption_version_id,
            count=count,
            contentforge_preset=contentforge_preset,
        )
        if not plan.get("canGenerate"):
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
                "blockingReason": plan.get("blockingReason"),
                "plan": plan,
                "registeredVariants": [],
            }
        base_url = (contentforge_base_url or self.settings.contentforge_base_url or "").rstrip("/")
        if not base_url:
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
                "blockingReason": "contentforge_base_url_required",
                "plan": plan,
                "registeredVariants": [],
            }
        parent = self.rendered_asset(parent_asset_id)
        source_path = Path(source_media_path).expanduser() if source_media_path else Path(parent["campaign_path"])
        if not source_path.exists():
            source_path = Path(parent["output_path"]) if not source_media_path else source_path
        if not source_path.exists():
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
                "blockingReason": "parent_media_missing",
                "plan": plan,
                "registeredVariants": [],
            }
        uploads_dir = self.settings.contentforge_root / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        staged_fingerprint = hashlib.sha256(
            f"{parent_asset_id}:{caption_version_id or ''}:{count}:{contentforge_preset}:{parent.get('content_hash') or ''}".encode("utf-8")
        ).hexdigest()[:12]
        staged_name = f"campaign_variant_parent_{parent_asset_id}_{staged_fingerprint}{source_path.suffix.lower()}"
        staged_path = uploads_dir / staged_name
        shutil.copy2(source_path, staged_path)
        idempotency_key = hashlib.sha256(
            f"campaign_factory:{parent_asset_id}:{caption_version_id or ''}:{count}:{contentforge_preset}:{parent.get('content_hash') or ''}".encode("utf-8")
        ).hexdigest()
        body_payload = {
            "source": staged_name,
            "variantCount": count,
            "variationPreset": contentforge_preset,
            "captionMode": "none",
            "preserveBurnedCaptions": True,
            "idempotencyKey": idempotency_key,
        }
        body = json.dumps(body_payload).encode("utf-8")
        endpoint = f"{base_url}/api/variant-pack/jobs"
        request = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout_seconds = int(
            contentforge_timeout_seconds
            or os.environ.get("CONTENTFORGE_VARIANT_PACK_TIMEOUT_SECONDS")
            or 180
        )
        poll_interval_seconds = float(os.environ.get("CONTENTFORGE_VARIANT_PACK_POLL_INTERVAL_SECONDS") or 2)
        request_timeout_seconds = min(30, max(1, timeout_seconds))
        try:
            with self._urlopen(request, timeout=request_timeout_seconds) as response:
                job = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            return self.contentforge_variant_pack_blocked_result(
                plan=plan,
                blocking_reason="contentforge_variant_pack_start_timeout",
                endpoint=endpoint,
                staged_source=staged_name,
                timeout_seconds=request_timeout_seconds,
                error=exc,
            )
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:500]
            except Exception:
                detail = str(exc)
            return self.contentforge_variant_pack_blocked_result(
                plan=plan,
                blocking_reason="contentforge_variant_pack_http_error",
                endpoint=endpoint,
                staged_source=staged_name,
                timeout_seconds=timeout_seconds,
                error=exc,
                extra={"statusCode": exc.code, "responseBody": detail},
            )
        except URLError as exc:
            return self.contentforge_variant_pack_blocked_result(
                plan=plan,
                blocking_reason="contentforge_variant_pack_start_url_error",
                endpoint=endpoint,
                staged_source=staged_name,
                timeout_seconds=request_timeout_seconds,
                error=exc,
            )
        if job.get("schema") in self._contentforge_variant_pack_schemas:
            report = job
        else:
            run_id = job.get("runId")
            poll_url = job.get("pollUrl")
            if not run_id or not poll_url:
                return {
                    "schema": "campaign_factory.generate_variants.v1",
                    "status": "blocked",
                    "blockingReason": "contentforge_variant_pack_job_malformed",
                    "plan": plan,
                    "contentforgeJob": job,
                    "registeredVariants": [],
                    "retryOrResumeSafe": True,
                    "partialCommitPrevented": True,
                }
            deadline = time.monotonic() + max(1, timeout_seconds)
            terminal_job = job
            report = None
            while time.monotonic() < deadline:
                if terminal_job.get("status") == "succeeded" and isinstance(terminal_job.get("report"), dict):
                    report = terminal_job["report"]
                    break
                if terminal_job.get("status") in {"failed", "timed_out", "aborted", "cancelled"}:
                    return {
                        "schema": "campaign_factory.generate_variants.v1",
                        "status": "blocked",
                        "blockingReason": f"contentforge_variant_pack_job_{terminal_job.get('status')}",
                        "plan": plan,
                        "contentforgeJob": terminal_job,
                        "registeredVariants": [],
                        "retryOrResumeSafe": True,
                        "partialCommitPrevented": True,
                    }
                time.sleep(max(0.25, poll_interval_seconds))
                poll_endpoint = f"{base_url}{poll_url}" if str(poll_url).startswith("/") else str(poll_url)
                poll_request = Request(poll_endpoint, headers={"Accept": "application/json"}, method="GET")
                try:
                    with self._urlopen(poll_request, timeout=request_timeout_seconds) as response:
                        terminal_job = json.loads(response.read().decode("utf-8"))
                except (TimeoutError, socket.timeout) as exc:
                    return self.contentforge_variant_pack_blocked_result(
                        plan=plan,
                        blocking_reason="contentforge_variant_pack_poll_timeout",
                        endpoint=poll_endpoint,
                        staged_source=staged_name,
                        timeout_seconds=request_timeout_seconds,
                        error=exc,
                        extra={"runId": run_id, "pollUrl": poll_url},
                    )
                except HTTPError as exc:
                    return self.contentforge_variant_pack_blocked_result(
                        plan=plan,
                        blocking_reason="contentforge_variant_pack_poll_http_error",
                        endpoint=poll_endpoint,
                        staged_source=staged_name,
                        timeout_seconds=request_timeout_seconds,
                        error=exc,
                        extra={"runId": run_id, "pollUrl": poll_url, "statusCode": exc.code},
                    )
                except URLError as exc:
                    return self.contentforge_variant_pack_blocked_result(
                        plan=plan,
                        blocking_reason="contentforge_variant_pack_poll_url_error",
                        endpoint=poll_endpoint,
                        staged_source=staged_name,
                        timeout_seconds=request_timeout_seconds,
                        error=exc,
                        extra={"runId": run_id, "pollUrl": poll_url},
                    )
            if report is None:
                return {
                    "schema": "campaign_factory.generate_variants.v1",
                    "status": "blocked",
                    "blockingReason": "contentforge_variant_pack_job_running",
                    "plan": plan,
                    "contentforgeJob": terminal_job,
                    "registeredVariants": [],
                    "retryOrResumeSafe": True,
                    "partialCommitPrevented": True,
                }
        if report.get("schema") not in self._contentforge_variant_pack_schemas:
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
                "blockingReason": "contentforge_variant_pack_malformed",
                "plan": plan,
                "contentforgeReport": report,
                "registeredVariants": [],
            }
        registered = []
        output_dir = Path(str(report.get("outputDir") or ""))
        campaign_row = self.conn.execute("SELECT * FROM campaigns WHERE id = ?", (parent["campaign_id"],)).fetchone()
        if not campaign_row:
            raise ValueError(f"campaign not found for parent asset: {parent_asset_id}")
        campaign = dict(campaign_row)
        model_slug = self._model_slug_for_campaign(campaign["id"])
        dirs = self.campaign_dirs(model_slug, campaign["slug"])
        caption_version = self._caption_version_by_id(caption_version_id) if caption_version_id else None
        parent_caption_context = load_context_json(parent.get("caption_outcome_context_json"))
        parent_caption_generation = json_load(parent.get("caption_generation_json"), {})
        parent_latest_audit = self._latest_audit_for_asset(parent_asset_id)
        _, parent_trust_statuses = self._content_trust_status_blockers(parent, parent_latest_audit, parent_caption_context)
        variant_burned_caption = caption_version.get("burnedCaptionText") if caption_version else parent.get("caption")
        variant_burned_hash = (
            caption_version.get("burnedCaptionHash")
            if caption_version
            else parent.get("caption_hash") or parent_caption_context.get("caption_hash")
        )
        parent_post_caption = self._instagram_post_caption_for_asset(parent, parent_caption_context)
        variant_instagram_caption = (
            caption_version.get("instagramPostCaption")
            if caption_version
            else parent_post_caption.get("instagram_post_caption")
        )
        variant_instagram_hash = (
            caption_version.get("instagramPostCaptionHash")
            if caption_version
            else parent_post_caption.get("instagram_post_caption_hash")
        )
        savepoint = f"variant_pack_register_{uuid.uuid4().hex[:12]}"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            for result in report.get("results") or []:
                if not isinstance(result, dict):
                    continue
                if result.get("uploadReady") is not True or result.get("recommended") is not True:
                    continue
                filename = result.get("filename") or result.get("file")
                if not filename:
                    continue
                source_variant = Path(str(result.get("filePath") or output_dir / filename))
                if not source_variant.exists():
                    continue
                digest = self._sha256_file(source_variant)
                dest = dirs["rendered"] / f"{Path(filename).stem}_{digest[:10]}{source_variant.suffix.lower()}"
                shutil.copy2(source_variant, dest)
                now = self._utc_now()
                variant_asset_id = f"asset_variant_{digest[:12]}"
                caption_hash = variant_burned_hash
                operations = [
                    {"type": "contentforge_variant_pack", "preset": contentforge_preset},
                    {"type": "contentforge_result", "result": self._sanitize_for_storage(result)},
                    {
                        "type": "preserve_parent_lineage",
                        "parentAssetId": parent_asset_id,
                        "captionFamilyId": caption_version.get("captionFamilyId") if caption_version else None,
                        "captionVersionId": caption_version_id,
                    },
                ]
                result_visual = result.get("visualQcStatus") or result.get("visual_qc_status")
                if isinstance(result.get("visualQc"), dict):
                    result_visual = result_visual or result["visualQc"].get("status")
                result_identity = result.get("identityVerificationStatus") or result.get("identity_verification_status")
                if isinstance(result.get("identityVerification"), dict):
                    result_identity = result_identity or result["identityVerification"].get("status")
                visual_qc_status = str(
                    result_visual
                    or ("passed" if result.get("uploadReady") is True else parent_trust_statuses["visualQcStatus"])
                ).strip().lower()
                identity_verification_status = str(result_identity or parent_trust_statuses["identityVerificationStatus"]).strip().lower()
                caption_context = dict(parent_caption_context)
                caption_context.update({
                    "parent_asset_id": parent_asset_id,
                    "concept_id": plan.get("conceptId"),
                    "parent_reel_id": plan.get("parentReelId"),
                    "variant_family_id": plan.get("variantFamilyId"),
                    "caption_family_id": caption_version.get("captionFamilyId") if caption_version else None,
                    "caption_version_id": caption_version_id,
                    "caption_angle": caption_version.get("captionAngle") if caption_version else None,
                    "caption_text": variant_burned_caption,
                    "caption_hash": caption_hash,
                    "burned_caption_text": variant_burned_caption,
                    "burned_caption_hash": caption_hash,
                    "instagram_post_caption": variant_instagram_caption,
                    "instagram_post_caption_hash": variant_instagram_hash,
                    "caption_cta": caption_version.get("captionCta") if caption_version else None,
                    "hashtags": caption_version.get("hashtags") if caption_version else [],
                    "post_caption_style": caption_version.get("postCaptionStyle") if caption_version else None,
                    "variant_operations": operations,
                    "visualQcStatus": visual_qc_status,
                    "identityVerificationStatus": identity_verification_status,
                    "visualQc": {"status": visual_qc_status},
                    "identityVerification": {"status": identity_verification_status},
                })
                caption_generation = dict(parent_caption_generation)
                caption_generation.update({
                    "caption": variant_burned_caption,
                    "captionHash": caption_hash,
                    "captionFamilyId": caption_version.get("captionFamilyId") if caption_version else None,
                    "captionVersionId": caption_version_id,
                    "captionAngle": caption_version.get("captionAngle") if caption_version else None,
                    "instagram_post_caption": variant_instagram_caption,
                    "instagram_post_caption_hash": variant_instagram_hash,
                    "captionOutcomeContext": caption_context,
                })
                self.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, render_job_id, content_hash, output_path,
                 campaign_path, filename, caption, caption_hash, caption_bank, caption_banks_json,
                 creator_mix, creator_model, frame_type, length_class, format_class,
                 caption_fit_version, suitability_decision, suitability_reason, source_clip,
                 caption_outcome_context_json, caption_generation_json, recipe, target_ratio,
                 audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, 'contentforge_variant_pack', ?, 'passed', 'approved', ?, ?)
                ON CONFLICT(campaign_id, content_hash) DO UPDATE SET
                  output_path = excluded.output_path,
                  campaign_path = excluded.campaign_path,
                  caption_outcome_context_json = excluded.caption_outcome_context_json,
                  caption_generation_json = excluded.caption_generation_json,
                  audit_status = excluded.audit_status,
                  review_state = excluded.review_state,
                  updated_at = excluded.updated_at
                """,
                    (
                        variant_asset_id,
                        parent["campaign_id"],
                        parent["source_asset_id"],
                        None,
                        digest,
                        str(dest),
                        str(dest),
                        dest.name,
                        variant_burned_caption,
                        caption_hash,
                        parent.get("caption_bank"),
                        parent.get("caption_banks_json"),
                        parent.get("creator_mix"),
                        parent.get("creator_model"),
                        parent.get("frame_type"),
                        parent.get("length_class"),
                        parent.get("format_class"),
                        parent.get("caption_fit_version"),
                        parent.get("suitability_decision"),
                        parent.get("suitability_reason"),
                        parent.get("source_clip"),
                        json.dumps(self._sanitize_for_storage(caption_context), ensure_ascii=False, sort_keys=True),
                        json.dumps(self._sanitize_for_storage(caption_generation), ensure_ascii=False, sort_keys=True),
                        parent.get("target_ratio") or "9:16",
                        now,
                        now,
                    ),
                )
                row = self.conn.execute("SELECT id FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?", (parent["campaign_id"], digest)).fetchone()
                if not row:
                    continue
                audit_id = f"audit_variant_{digest[:12]}"
                audit_payload = {
                    "schema": "campaign_factory.contentforge_variant_audit.v1",
                    "targetFile": str(dest),
                    "contentforgeRunId": report.get("runId"),
                    "contentforgeSchema": report.get("schema"),
                    "contentforgePreset": contentforge_preset,
                    "overallVerdict": "pass",
                    "readinessSummary": {
                        "state": "ready",
                        "blockingReasons": [],
                        "blockingCodes": [],
                        "warnings": result.get("mainWarnings") or [],
                        "uploadReady": True,
                        "recommended": True,
                        "visualQcStatus": visual_qc_status,
                        "identityVerificationStatus": identity_verification_status,
                    },
                    "visualQcStatus": visual_qc_status,
                    "identityVerificationStatus": identity_verification_status,
                    "visualQc": {"status": visual_qc_status},
                    "identityVerification": {"status": identity_verification_status},
                    "variant": self._sanitize_for_storage(result),
                }
                audit_dir = dirs["audits"] / "contentforge_variants"
                audit_dir.mkdir(parents=True, exist_ok=True)
                audit_path = audit_dir / f"{audit_id}.json"
                audit_path.write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False), encoding="utf-8")
                self.conn.execute(
                """
                INSERT INTO audit_reports
                (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score,
                 status, layers_json, verdicts_json, overall_verdict, files_analyzed,
                 failed_checks_json, warnings_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pass', '{}', '{}', 'pass', 1, '[]', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  report_path = excluded.report_path,
                  score = excluded.score,
                  status = excluded.status,
                  layers_json = excluded.layers_json,
                  verdicts_json = excluded.verdicts_json,
                  overall_verdict = excluded.overall_verdict,
                  failed_checks_json = excluded.failed_checks_json,
                  warnings_json = excluded.warnings_json,
                  created_at = excluded.created_at
                """,
                    (
                        audit_id,
                        parent["campaign_id"],
                        row["id"],
                        report.get("runId"),
                        str(audit_path),
                        int(result.get("qualityScore") or result.get("creativeQualityScore") or 90),
                        json.dumps(result.get("mainWarnings") or []),
                        now,
                    ),
                )
                variant_payload = self._register_variant_asset(
                    parent_asset_id=parent_asset_id,
                    variant_asset_id=row["id"],
                    variant_family_id=plan["variantFamilyId"],
                    variant_index=len(registered) + 1,
                    operations=operations,
                    caption_family_id=caption_version.get("captionFamilyId") if caption_version else None,
                    caption_version_id=caption_version_id,
                    contentforge_run_id=report.get("runId"),
                    contentforge_preset=contentforge_preset,
                    qc_status="passed",
                    commit=False,
                )
                registered.append(variant_payload)
        except Exception:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return {
            "schema": "campaign_factory.generate_variants.v1",
            "status": "completed",
            "plan": plan,
            "contentforgeReport": {
                "schema": report.get("schema"),
                "runId": report.get("runId"),
                "manifestPath": report.get("manifestPath"),
                "outputDir": report.get("outputDir"),
                "recommendedCount": sum(1 for item in report.get("results") or [] if isinstance(item, dict) and item.get("recommended") is True),
            },
            "registeredVariants": registered,
        }

    def contentforge_variant_pack_blocked_result(
        self,
        *,
        plan: dict[str, Any],
        blocking_reason: str,
        endpoint: str,
        staged_source: str,
        timeout_seconds: int,
        error: BaseException,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnostics = {
            "endpoint": endpoint,
            "stagedSource": staged_source,
            "timeoutSeconds": timeout_seconds,
            "errorType": type(error).__name__,
            "error": str(error),
            "retryOrResumeSafe": True,
            "partialCommitPrevented": True,
        }
        if extra:
            diagnostics.update(extra)
        return {
            "schema": "campaign_factory.generate_variants.v1",
            "status": "blocked",
            "blockingReason": blocking_reason,
            "plan": plan,
            "registeredVariants": [],
            "contentforgeDiagnostics": diagnostics,
            "retryOrResumeSafe": True,
            "partialCommitPrevented": True,
        }

    def register_variant_asset(
        self,
        *,
        parent_asset_id: str,
        variant_asset_id: str,
        variant_family_id: str,
        variant_index: int,
        operations: list[dict[str, Any]],
        caption_family_id: str | None = None,
        caption_version_id: str | None = None,
        contentforge_run_id: str | None = None,
        contentforge_preset: str = "caption_safe",
        qc_status: str = "passed",
        cooldown_days: int = DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS,
        commit: bool = True,
    ) -> dict[str, Any]:
        parent = self.rendered_asset(parent_asset_id)
        variant = self.rendered_asset(variant_asset_id)
        concept = self.concept_for_parent_asset(parent_asset_id)
        if not concept:
            concept = self.register_parent_reel(parent_asset_id)
        now = self._utc_now()
        variant_id = f"var_{hashlib.sha256(f'{variant_family_id}:{variant_index}:{variant_asset_id}'.encode('utf-8')).hexdigest()[:12]}"
        source = self.conn.execute("SELECT * FROM source_assets WHERE id = ?", (variant["source_asset_id"],)).fetchone()
        source_fingerprint = source["content_hash"] if source else None
        caption_context = load_context_json(variant.get("caption_outcome_context_json"))
        _, audio_id = self._audio_selection_for_asset(variant)
        content_surface = self._normalize_content_surface(variant.get("content_surface") or parent.get("content_surface"))
        self.conn.execute(
            """
            INSERT INTO variant_families
            (id, campaign_id, concept_id, parent_reel_id, parent_asset_id, source_asset_id,
             caption_family_id, caption_version_id, requested_count, contentforge_run_id, contentforge_preset, cooldown_days, status,
             manifest_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              requested_count = MAX(requested_count, excluded.requested_count),
              caption_family_id = COALESCE(excluded.caption_family_id, caption_family_id),
              caption_version_id = COALESCE(excluded.caption_version_id, caption_version_id),
              contentforge_run_id = COALESCE(excluded.contentforge_run_id, contentforge_run_id),
              contentforge_preset = excluded.contentforge_preset,
              cooldown_days = excluded.cooldown_days,
              status = 'active',
              updated_at = excluded.updated_at
            """,
            (
                variant_family_id,
                parent["campaign_id"],
                concept["conceptId"],
                concept["parentReelId"],
                parent_asset_id,
                parent["source_asset_id"],
                caption_family_id,
                caption_version_id,
                variant_index,
                contentforge_run_id,
                contentforge_preset,
                cooldown_days,
                json.dumps({"contentforgeRunId": contentforge_run_id}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO variant_assets
            (id, campaign_id, concept_id, parent_reel_id, variant_family_id, variant_index,
             parent_asset_id, caption_family_id, caption_version_id, variant_asset_id, source_asset_id, source_fingerprint,
             content_fingerprint, caption_hash, audio_id, content_surface, operations_json, qc_status,
             contentforge_run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(variant_asset_id) DO UPDATE SET
              variant_family_id = excluded.variant_family_id,
              variant_index = excluded.variant_index,
              caption_family_id = COALESCE(excluded.caption_family_id, caption_family_id),
              caption_version_id = COALESCE(excluded.caption_version_id, caption_version_id),
              content_surface = excluded.content_surface,
              operations_json = excluded.operations_json,
              qc_status = excluded.qc_status,
              contentforge_run_id = excluded.contentforge_run_id,
              updated_at = excluded.updated_at
            """,
            (
                variant_id,
                parent["campaign_id"],
                concept["conceptId"],
                concept["parentReelId"],
                variant_family_id,
                variant_index,
                parent_asset_id,
                caption_family_id,
                caption_version_id,
                variant_asset_id,
                variant["source_asset_id"],
                source_fingerprint,
                variant.get("content_hash"),
                variant.get("caption_hash") or caption_context.get("caption_hash"),
                audio_id,
                content_surface,
                json.dumps(self._sanitize_for_storage(operations), ensure_ascii=False, sort_keys=True),
                qc_status,
                contentforge_run_id,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            UPDATE rendered_assets
            SET parent_asset_id = ?, concept_id = ?, parent_reel_id = ?,
                variant_family_id = ?, variant_id = ?, variant_index = ?,
                variant_operations_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                parent_asset_id,
                concept["conceptId"],
                concept["parentReelId"],
                variant_family_id,
                variant_id,
                variant_index,
                json.dumps(self._sanitize_for_storage(operations), ensure_ascii=False, sort_keys=True),
                now,
                variant_asset_id,
            ),
        )
        if commit:
            self.conn.commit()
        return self.variant_lineage_asset_payload(self.conn.execute("SELECT * FROM variant_assets WHERE variant_asset_id = ?", (variant_asset_id,)).fetchone())

    def parent_variant_inventory(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self.campaign_by_slug(campaign_slug)
        concepts = [self.concept_payload(row) for row in self.conn.execute("SELECT * FROM concepts WHERE campaign_id = ? ORDER BY created_at", (campaign["id"],)).fetchall()]
        families = [self.variant_family_payload(row) for row in self.conn.execute("SELECT * FROM variant_families WHERE campaign_id = ? ORDER BY created_at", (campaign["id"],)).fetchall()]
        variants = [self.variant_lineage_asset_payload(row) for row in self.conn.execute("SELECT * FROM variant_assets WHERE campaign_id = ? ORDER BY variant_family_id, variant_index", (campaign["id"],)).fetchall()]
        usage = [self.variant_usage_payload(row) for row in self.conn.execute("SELECT * FROM variant_account_usage WHERE campaign_id = ? ORDER BY created_at DESC", (campaign["id"],)).fetchall()]
        used_variant_ids = {row["variantId"] for row in usage if row.get("variantId")}
        return {
            "schema": "campaign_factory.parent_variant_inventory.v1",
            "campaign": campaign["slug"],
            "generatedAt": self._utc_now(),
            "summary": {
                "concepts": len(concepts),
                "variantFamilies": len(families),
                "variants": len(variants),
                "unusedVariants": sum(1 for row in variants if row.get("variantId") not in used_variant_ids),
                "usageRows": len(usage),
            },
            "concepts": concepts,
            "variantFamilies": families,
            "variants": variants,
            "unusedVariants": [row for row in variants if row.get("variantId") not in used_variant_ids],
            "accountUsage": usage,
        }

    def variant_metrics_rollup(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self.campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE campaign_id = ? AND metrics_eligible = 1 ORDER BY snapshot_at DESC",
            (campaign["id"],),
        ).fetchall()
        snapshots = [self._performance_snapshot_payload(dict(row)) for row in rows]
        return {
            "schema": "campaign_factory.variant_metrics_rollup.v1",
            "campaign": campaign["slug"],
            "generatedAt": self._utc_now(),
            "summary": {
                "variantsPosted": len({s.get("variantId") for s in snapshots if s.get("variantId")}),
                "accountsReached": len({s.get("instagramAccountId") for s in snapshots if s.get("instagramAccountId")}),
                "totalViews": sum(int((s.get("metrics") or {}).get("views") or 0) for s in snapshots),
                "totalReach": sum(int((s.get("metrics") or {}).get("reach") or 0) for s in snapshots),
                "totalFollowersGained": 0,
            },
            "parents": self.variant_rollup_group(snapshots, "parentReelId", "parentReelId"),
            "families": self.variant_rollup_group(snapshots, "variantFamilyId", "variantFamilyId"),
            "variants": self.variant_rollup_group(snapshots, "variantId", "variantId"),
            "captions": self.variant_rollup_group(snapshots, "captionHash", "captionHash"),
            "captionFamilies": self.variant_rollup_group(snapshots, "captionFamilyId", "captionFamilyId"),
            "captionVersions": self.variant_rollup_group(snapshots, "captionVersionId", "captionVersionId"),
            "audio": self.variant_rollup_group(snapshots, "audioId", "audioId"),
            "surfaces": self.variant_rollup_group(snapshots, "contentSurface", "contentSurface"),
        }

    def concept_for_parent_asset(self, parent_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM concepts WHERE parent_asset_id = ? ORDER BY updated_at DESC LIMIT 1", (parent_asset_id,)).fetchone()
        return self.concept_payload(row) if row else None

    def variant_lineage_for_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM variant_assets WHERE variant_asset_id = ?", (rendered_asset_id,)).fetchone()
        if row:
            payload = self.variant_lineage_asset_payload(row)
            return {
                "conceptId": payload["conceptId"],
                "concept_id": payload["conceptId"],
                "parentReelId": payload["parentReelId"],
                "parent_reel_id": payload["parentReelId"],
                "parentAssetId": payload["parentAssetId"],
                "parent_asset_id": payload["parentAssetId"],
                "captionFamilyId": payload.get("captionFamilyId"),
                "caption_family_id": payload.get("captionFamilyId"),
                "captionVersionId": payload.get("captionVersionId"),
                "caption_version_id": payload.get("captionVersionId"),
                "variantFamilyId": payload["variantFamilyId"],
                "variant_family_id": payload["variantFamilyId"],
                "variantId": payload["variantId"],
                "variant_id": payload["variantId"],
                "variantIndex": payload["variantIndex"],
                "variant_index": payload["variantIndex"],
                "variantOperations": payload["variantOperations"],
                "variant_operations": payload["variantOperations"],
            }
        asset = self.rendered_asset(rendered_asset_id)
        concept_id = asset.get("concept_id")
        if not concept_id:
            return {}
        return {
            "conceptId": concept_id,
            "concept_id": concept_id,
            "parentReelId": asset.get("parent_reel_id"),
            "parent_reel_id": asset.get("parent_reel_id"),
            "parentAssetId": asset.get("parent_asset_id") or rendered_asset_id,
            "parent_asset_id": asset.get("parent_asset_id") or rendered_asset_id,
        }

    def concept_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        data = dict(row)
        return {
            "schema": "campaign_factory.parent_reel.v1",
            "conceptId": data["id"],
            "parentReelId": data["parent_reel_id"],
            "campaignId": data["campaign_id"],
            "creator": data.get("creator"),
            "parentAssetId": data["parent_asset_id"],
            "sourceAssetId": data.get("source_asset_id"),
            "sourceFingerprint": data.get("source_fingerprint"),
            "contentFingerprint": data.get("content_fingerprint"),
            "captionHash": data.get("caption_hash"),
            "audioId": data.get("audio_id"),
            "status": data.get("status"),
            "metadata": json_load(data.get("metadata_json"), {}),
            "createdAt": data.get("created_at"),
            "updatedAt": data.get("updated_at"),
        }

    def variant_family_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "variantFamilyId": data["id"],
            "campaignId": data["campaign_id"],
            "conceptId": data["concept_id"],
            "parentReelId": data["parent_reel_id"],
            "parentAssetId": data["parent_asset_id"],
            "captionFamilyId": data.get("caption_family_id"),
            "captionVersionId": data.get("caption_version_id"),
            "sourceAssetId": data.get("source_asset_id"),
            "requestedCount": data.get("requested_count"),
            "contentforgeRunId": data.get("contentforge_run_id"),
            "contentforgePreset": data.get("contentforge_preset"),
            "cooldownDays": data.get("cooldown_days"),
            "status": data.get("status"),
            "manifest": json_load(data.get("manifest_json"), {}),
        }

    def variant_lineage_asset_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        data = dict(row)
        return {
            "variantId": data["id"],
            "campaignId": data["campaign_id"],
            "conceptId": data["concept_id"],
            "parentReelId": data["parent_reel_id"],
            "variantFamilyId": data["variant_family_id"],
            "variantIndex": data["variant_index"],
            "parentAssetId": data["parent_asset_id"],
            "captionFamilyId": data.get("caption_family_id"),
            "captionVersionId": data.get("caption_version_id"),
            "variantAssetId": data["variant_asset_id"],
            "sourceAssetId": data.get("source_asset_id"),
            "sourceFingerprint": data.get("source_fingerprint"),
            "contentFingerprint": data.get("content_fingerprint"),
            "captionHash": data.get("caption_hash"),
            "audioId": data.get("audio_id"),
            "variantOperations": json_load(data.get("operations_json"), []),
            "qcStatus": data.get("qc_status"),
            "contentforgeRunId": data.get("contentforge_run_id"),
        }

    def variant_usage_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        return {
            "id": data["id"],
            "campaignId": data["campaign_id"],
            "conceptId": data.get("concept_id"),
            "parentReelId": data.get("parent_reel_id"),
            "variantFamilyId": data.get("variant_family_id"),
            "variantId": data.get("variant_id"),
            "renderedAssetId": data.get("rendered_asset_id"),
            "postId": data.get("post_id"),
            "accountId": data.get("account_id"),
            "instagramAccountId": data.get("instagram_account_id"),
            "usageState": data.get("usage_state"),
            "scheduledFor": data.get("scheduled_for"),
            "publishedAt": data.get("published_at"),
            "metricsEligible": bool(data.get("metrics_eligible")),
        }

    def variant_rollup_group(self, snapshots: list[dict[str, Any]], key: str, output_key: str) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            value = snapshot.get(key)
            if value:
                groups.setdefault(str(value), []).append(snapshot)
        rows = []
        for value, group in groups.items():
            rows.append({
                output_key: value,
                "parentReelId": next((item.get("parentReelId") for item in group if item.get("parentReelId")), None),
                "variantFamilyId": next((item.get("variantFamilyId") for item in group if item.get("variantFamilyId")), None),
                "variantId": next((item.get("variantId") for item in group if item.get("variantId")), None),
                "performance": self._aggregate_performance(group),
                "renderedAssetIds": sorted({str(item["renderedAssetId"]) for item in group if item.get("renderedAssetId")}),
                "postIds": sorted({str(item["postId"]) for item in group if item.get("postId")}),
                "accountIds": sorted({str(item["instagramAccountId"]) for item in group if item.get("instagramAccountId")}),
            })
        return sorted(rows, key=lambda item: (-(item["performance"]["totals"].get("views") or 0), str(item.get(output_key) or "")))
