from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any


class FinishedVideoRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Any,
        *,
        slugify: Callable[[str], str],
        new_id: Callable[[str], str],
        media_type_for_path: Callable[[Any], str],
        sha256_file: Callable[[Any], str],
        probe_video_shape: Callable[[Any], dict[str, Any]],
        text_hash: Callable[[str], str],
        json_load: Callable[[Any, Any], Any],
        utc_now: Callable[[], str],
        upsert_model: Callable[..., dict[str, Any]],
        upsert_campaign: Callable[..., dict[str, Any]],
        campaign_dirs: Callable[[str, str], dict[str, Any]],
        make_batch: Callable[..., dict[str, Any]],
        creative_plan: Callable[[str], dict[str, Any]],
        load_source_lineage: Callable[[Path | None], dict[str, Any]],
        discoverability_pre_render_gate: Callable[[dict[str, Any]], dict[str, Any]],
        capture_discoverability_gate_rejection_evidence: Callable[..., dict[str, Any]],
        explain_publishability: Callable[[str], dict[str, Any]],
        capture_publishability_rejection_evidence_from_result: Callable[
            ..., dict[str, Any]
        ],
        record_creative_plan_event: Callable[..., None],
        record_event: Callable[..., None],
        ensure_graph_node: Callable[..., str],
        ensure_graph_edge: Callable[..., None],
        graph_id_for: Callable[..., str],
        ensure_cost_table: Callable[[sqlite3.Connection], None],
        record_ai_cost: Callable[..., str],
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._slugify = slugify
        self._new_id = new_id
        self._media_type_for_path = media_type_for_path
        self._sha256_file = sha256_file
        self._probe_video_shape = probe_video_shape
        self._text_hash = text_hash
        self._json_load = json_load
        self._utc_now = utc_now
        self._upsert_model = upsert_model
        self._upsert_campaign = upsert_campaign
        self._campaign_dirs = campaign_dirs
        self._make_batch = make_batch
        self._creative_plan = creative_plan
        self._load_source_lineage = load_source_lineage
        self._discoverability_pre_render_gate = discoverability_pre_render_gate
        self._capture_discoverability_gate_rejection_evidence = (
            capture_discoverability_gate_rejection_evidence
        )
        self._explain_publishability = explain_publishability
        self._capture_publishability_rejection_evidence_from_result = (
            capture_publishability_rejection_evidence_from_result
        )
        self._record_creative_plan_event = record_creative_plan_event
        self._record_event = record_event
        self._ensure_graph_node = ensure_graph_node
        self._ensure_graph_edge = ensure_graph_edge
        self._graph_id_for = graph_id_for
        self._ensure_cost_table = ensure_cost_table
        self._record_ai_cost = record_ai_cost

    def review_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        decision: str,
        notes: str | None = None,
        require_safe_audit: bool = False,
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        row = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"rendered asset not found: {rendered_asset_id}")
        approvable_audit_statuses = {"approved_candidate", "needs_review"}
        if (
            decision == "approved"
            and require_safe_audit
            and row["audit_status"] not in approvable_audit_statuses
        ):
            raise ValueError(
                f"approval blocked: audit_status:{row['audit_status']}; run audit or use an explicit force override"
            )
        now = self._utc_now()
        decision_id = self._new_id("approval")
        self.conn.execute(
            "UPDATE rendered_assets SET review_state = ?, updated_at = ? WHERE id = ?",
            (decision, now, rendered_asset_id),
        )
        self.conn.execute(
            "INSERT INTO approval_decisions (id, campaign_id, rendered_asset_id, decision, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (decision_id, row["campaign_id"], rendered_asset_id, decision, notes, now),
        )
        approval_graph_id = self._ensure_graph_node(
            "approval_decision",
            local_table="approval_decisions",
            local_id=decision_id,
            payload={
                "decision": decision,
                "renderedAssetId": rendered_asset_id,
                "notes": notes,
            },
        )
        self._ensure_graph_edge(
            self._graph_id_for(
                "rendered_assets", rendered_asset_id, entity_type="rendered_asset"
            ),
            approval_graph_id,
            "rendered_asset_to_approval_decision",
            evidence={"decision": decision},
        )
        self._record_event(
            "asset_approved" if decision == "approved" else "asset_rejected",
            campaign_id=row["campaign_id"],
            source_asset_id=row["source_asset_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message=f"Asset {decision}: {row['filename']}",
            metadata={
                "decision": decision,
                "notes": notes,
                "approvalDecisionId": decision_id,
            },
            commit=False,
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
            ).fetchone()
        )

    def approve_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        notes: str | None = None,
        require_safe_audit: bool = False,
    ) -> dict[str, Any]:
        return self.review_rendered_asset(
            rendered_asset_id,
            decision="approved",
            notes=notes,
            require_safe_audit=require_safe_audit,
        )

    def attest_publishability_evidence(
        self,
        rendered_asset_id: str,
        *,
        instagram_post_caption: str | None = None,
        visual_qc_status: str | None = None,
        identity_verification_status: str | None = None,
        operator: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"rendered asset not found: {rendered_asset_id}")
        caption = (instagram_post_caption or "").strip()
        visual_status = (visual_qc_status or "").strip().lower()
        identity_status = (identity_verification_status or "").strip().lower()
        allowed_statuses = {"passed", "failed", "unavailable"}
        if visual_status and visual_status not in allowed_statuses:
            raise ValueError("visual_qc_status must be passed, failed, or unavailable")
        if identity_status and identity_status not in allowed_statuses:
            raise ValueError(
                "identity_verification_status must be passed, failed, or unavailable"
            )
        now = self._utc_now()
        caption_generation = json.loads(row["caption_generation_json"] or "{}")
        if not isinstance(caption_generation, dict):
            caption_generation = {}
        metadata = json.loads(row["metadata_json"] or "{}")
        if not isinstance(metadata, dict):
            metadata = {}
        attestation = {
            "schema": "campaign_factory.operator_publishability_attestation.v1",
            "renderedAssetId": rendered_asset_id,
            "operator": operator,
            "notes": notes,
            "attestedAt": now,
        }
        if caption:
            caption_hash = hashlib.sha256(
                " ".join(caption.lower().split()).encode("utf-8")
            ).hexdigest()
            caption_generation.update(
                {
                    "instagram_post_caption": caption,
                    "instagramPostCaption": caption,
                    "instagram_post_caption_hash": caption_hash,
                    "instagramPostCaptionHash": caption_hash,
                    "post_caption_style": caption_generation.get("post_caption_style")
                    or "short_natural",
                }
            )
            attestation["instagramPostCaptionHash"] = caption_hash
        if visual_status:
            metadata.update(
                {
                    "visualQcStatus": visual_status,
                    "visualQc": {
                        "status": visual_status,
                        "operator": operator,
                        "attestedAt": now,
                        "notes": notes,
                    },
                }
            )
            if visual_status == "passed":
                metadata["visual_qc_passed"] = True
                metadata["operator_visual_review_passed"] = True
            attestation["visualQcStatus"] = visual_status
        if identity_status:
            metadata.update(
                {
                    "identityVerificationStatus": identity_status,
                    "identityVerification": {
                        "status": identity_status,
                        "operator": operator,
                        "attestedAt": now,
                        "notes": notes,
                    },
                }
            )
            attestation["identityVerificationStatus"] = identity_status
        metadata["operatorPublishabilityAttestation"] = attestation
        caption_generation["operatorPublishabilityAttestation"] = attestation
        self.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now,
                rendered_asset_id,
            ),
        )
        self._record_event(
            "publishability_attested",
            campaign_id=row["campaign_id"],
            source_asset_id=row["source_asset_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message=f"Publishability evidence attested: {row['filename']}",
            metadata=attestation,
            commit=False,
        )
        self.conn.commit()
        refreshed = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
        ).fetchone()
        return {
            "schema": "campaign_factory.operator_publishability_attestation_result.v1",
            "renderedAssetId": rendered_asset_id,
            "attestation": attestation,
            "asset": dict(refreshed) if refreshed else {},
        }

    def record_lineage_costs(self, lineage: dict[str, Any]) -> None:
        """Extract AI cost data from imported lineage and record it."""
        try:
            self._ensure_cost_table(self.conn)
            lineage_hash = hashlib.sha256(
                json.dumps(
                    lineage, ensure_ascii=False, sort_keys=True, default=str
                ).encode("utf-8")
            ).hexdigest()[:24]
            usage = lineage.get("usage")
            if isinstance(usage, dict):
                self._record_ai_cost(
                    self.conn,
                    provider="grok",
                    operation="image_prompt",
                    campaign_id=lineage.get("campaign"),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    metadata={
                        "lineage_schema": lineage.get("schema"),
                        "model": lineage.get("model"),
                    },
                    source_event_key=f"lineage:{lineage_hash}:grok:image_prompt",
                    ensure_schema=False,
                )
            generation = lineage.get("generation")
            if isinstance(generation, dict):
                tool = generation.get("tool", "")
                if "higgsfield" in tool or "soul" in tool:
                    self._record_ai_cost(
                        self.conn,
                        provider="higgsfield",
                        operation="soul_grid",
                        campaign_id=lineage.get("campaign"),
                        generations=1,
                        metadata={
                            "tool": tool,
                            "modelProfile": generation.get("modelProfile"),
                        },
                        source_event_key=f"lineage:{lineage_hash}:higgsfield:soul_grid",
                        ensure_schema=False,
                    )
                if "kling" in tool:
                    self._record_ai_cost(
                        self.conn,
                        provider="kling",
                        operation="video_animate",
                        campaign_id=lineage.get("campaign"),
                        generations=1,
                        metadata={
                            "tool": tool,
                            "modelProfile": generation.get("modelProfile"),
                        },
                        source_event_key=f"lineage:{lineage_hash}:kling:video_animate",
                        ensure_schema=False,
                    )
        except Exception:
            pass  # Cost tracking is best-effort; never block the import pipeline

    def finished_video_hooks(
        self, format_type: str, pattern: dict[str, Any], count: int = 5
    ) -> list[dict[str, Any]]:
        pools = {
            "mirror_selfie": [
                "he thinks this was for him",
                "outfit said enough",
                "not sending this twice",
                "this one stays in drafts",
                "he saw it and folded",
            ],
            "selfie_video": [
                "say less",
                "this is your sign",
                "he knows exactly why",
                "not explaining this one",
                "too calm for what just happened",
            ],
            "pov": [
                "pov: he thought you were joking",
                "pov: this is where he folded",
                "pov: you already know",
                "pov: the part he replays",
                "pov: it was never casual",
            ],
            "spicy_lifestyle": [
                "soft life, hard launch",
                "this view did not need a caption",
                "some days explain themselves",
                "casual, allegedly",
                "he would have stayed too",
            ],
        }
        fallback = pools["selfie_video"]
        candidates = pools.get(format_type, fallback)
        hooks = []
        for idx in range(max(1, count)):
            text = candidates[idx % len(candidates)]
            hooks.append(
                {
                    "text": text,
                    "referenceClusterKey": pattern["clusterKey"],
                    "referenceLabel": pattern["label"],
                    "hookType": "finished_video_native_hook",
                    "captionArchetype": f"{format_type}_native",
                    "audioRecommendations": pattern.get("audioRecommendations") or {},
                    "formulaIndex": idx % len(candidates),
                    "candidateKind": "finished_video_caption",
                    "source": "campaign_factory_finished_video",
                    "formatType": format_type,
                }
            )
        return hooks

    def intake_finished_video(
        self,
        *,
        input_path: Path,
        model_slug: str,
        platform: str = "instagram",
        goal: str = "reach",
        reference_pattern: str | None = "auto",
        campaign_slug: str | None = None,
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        variant_count: int = 10,
        workers: int = 3,
        recipes: list[str] | None = None,
        creative_plan: str | None = None,
        style_lane: str | None = None,
        source_lineage_path: Path | None = None,
    ) -> dict[str, Any]:
        source = Path(input_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"finished video not found: {source}")
        media_type = self._media_type_for_path(source)
        if media_type != "video":
            raise ValueError("finished-video intake requires a video file")
        campaign = self._slugify(campaign_slug or f"finished_{source.stem}")
        digest = self._sha256_file(source)
        source_probe = self._probe_video_shape(source)
        source_preflight = self.finished_video_preflight(source_probe)
        intake_dir = (
            self.settings.campaigns_dir
            / "_finished_video_intake"
            / f"{campaign}_{digest[:10]}"
        )
        intake_dir.mkdir(parents=True, exist_ok=True)
        staged = (
            intake_dir
            / f"{self._slugify(source.stem)}_{digest[:10]}{source.suffix.lower()}"
        )
        if not staged.exists():
            shutil.copy2(source, staged)
        style_lane_format = self.finished_video_style_lane_format(style_lane)
        format_type = style_lane_format or self.classify_finished_video_format(source)
        creative_plan_payload = (
            self._creative_plan(creative_plan) if creative_plan else None
        )
        creative_plan_id = (
            creative_plan_payload["id"] if creative_plan_payload else None
        )
        source_lineage = self._load_source_lineage(source_lineage_path)
        generation = (
            source_lineage.get("generation")
            if isinstance(source_lineage.get("generation"), dict)
            else {}
        )
        source_meta = (
            source_lineage.get("source")
            if isinstance(source_lineage.get("source"), dict)
            else {}
        )
        if not style_lane_format and source_meta.get("formatType"):
            format_type = str(source_meta["formatType"])
        generated_lineage = (
            source_lineage
            if source_lineage.get("schema")
            == "campaign_factory.generated_asset_lineage.v1"
            else {
                "schema": "campaign_factory.generated_asset_lineage.v1",
                "pipelineTraceId": f"trace_finished_video_{digest[:16]}",
                "source": {
                    "referenceId": None,
                    "patternCardId": None,
                    "promptId": None,
                    "formatType": format_type,
                    "referencePattern": reference_pattern or "auto",
                },
                "generation": {
                    "tool": "manual_finished_video",
                    "modelProfile": model_slug,
                    "assetPath": str(source),
                },
                "review": {
                    "humanReviewRequired": True,
                    "status": "draft",
                },
                "quality": {
                    "copyRisk": "unknown",
                },
            }
        )
        generated_lineage.setdefault("source", {}).setdefault("formatType", format_type)
        generated_lineage.setdefault("generation", {}).setdefault(
            "assetPath", str(source)
        )
        generated_lineage.setdefault("generation", {}).setdefault(
            "modelProfile", model_slug
        )
        generated_lineage.setdefault("review", {}).setdefault(
            "humanReviewRequired", True
        )
        generated_lineage.setdefault("review", {}).setdefault("status", "draft")
        source_prompt = json.dumps(
            {
                "schema": "campaign_factory.finished_video_intake.v1",
                "creativePlanId": creative_plan_id,
                "creativePlanName": creative_plan_payload["name"]
                if creative_plan_payload
                else None,
                "styleLane": style_lane or format_type,
                "inputPath": str(source),
                "stagedPath": str(staged),
                "platform": platform,
                "goal": goal,
                "referencePattern": reference_pattern
                or source_meta.get("referencePattern")
                or "auto",
                "patternCardId": source_meta.get("patternCardId"),
                "promptId": source_meta.get("promptId"),
                "generationTool": generation.get("tool"),
                "modelProfile": generation.get("modelProfile") or model_slug,
                "formatType": format_type,
                "strategy": {
                    "distributionPriority": "instagram_reels_first"
                    if platform == "instagram"
                    else platform,
                    "primaryMetric": "views_reach",
                    "humanReviewRequired": True,
                    "nativeAudioRequired": platform == "instagram",
                    "useReferenceBank": True,
                },
                "sourcePreflight": {
                    "probe": source_probe,
                    "warnings": source_preflight,
                },
                "generatedAssetLineage": generated_lineage,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        result = self._make_batch(
            folder=intake_dir,
            campaign_slug=campaign,
            model_slug=model_slug,
            output_format="reel",
            variant_count=variant_count,
            reference_pattern=reference_pattern,
            contentforge_base_url=contentforge_base_url,
            user_id=user_id,
            dry_run_export=dry_run_export,
            workers=workers,
            recipes=recipes,
            auto_approve_warning_only=True,
            source_prompt=source_prompt,
            import_notes="finished-video intake source import",
        )
        result["finishedVideoIntake"] = {
            "schema": "campaign_factory.finished_video_intake.v1",
            "inputPath": str(source),
            "stagedFolder": str(intake_dir),
            "stagedPath": str(staged),
            "campaign": campaign,
            "model": model_slug,
            "platform": platform,
            "goal": goal,
            "formatType": format_type,
            "sourcePrompt": self._json_load(source_prompt, {}),
            "sourceLineagePath": str(source_lineage_path)
            if source_lineage_path
            else None,
            "sourcePreflight": source_preflight,
            "creativePlan": creative_plan_payload,
            "draftFirst": True,
            "humanReviewRequired": True,
        }
        if creative_plan_payload and campaign:
            self.conn.execute(
                "UPDATE creative_plans SET linked_campaign_slug = ?, updated_at = ? WHERE id = ?",
                (campaign, self._utc_now(), creative_plan_id),
            )
            self._record_creative_plan_event(
                creative_plan_id,
                "finished_video_ingested",
                status="success",
                message=f"Finished video ingested: {source.name}",
                metadata={"campaign": campaign, "inputPath": str(source)},
            )
        return result

    def finished_video_preflight(self, probe: dict[str, Any]) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        aspect = probe.get("effectiveAspectRatio")
        if isinstance(aspect, (int, float)) and aspect > 0:
            if aspect < 0.48 or aspect > 0.66:
                warnings.append(
                    {
                        "code": "finished_video_not_reels_canvas",
                        "message": "Finished video is not close to a clean 9:16 Reels canvas; check for platform UI, borders, or screen-recorded wrapper before posting.",
                    }
                )
        elif not probe:
            warnings.append(
                {
                    "code": "finished_video_probe_unavailable",
                    "message": "Could not probe finished video dimensions before intake.",
                }
            )
        return warnings

    def finished_video_style_lane_format(self, style_lane: str | None) -> str | None:
        normalized = self._slugify(style_lane or "")
        aliases = {
            "mirror": "mirror_selfie",
            "mirror_selfie": "mirror_selfie",
            "selfie": "selfie_video",
            "selfie_video": "selfie_video",
            "pov": "pov",
            "pov_relationship": "pov",
            "lifestyle": "spicy_lifestyle",
            "lifestyle_scene": "spicy_lifestyle",
            "spicy_lifestyle": "spicy_lifestyle",
            "amateur_native": "selfie_video",
            "slideshow": "slideshow",
            "slideshow_story": "slideshow",
        }
        return aliases.get(normalized)

    def finished_video_caption_band(self, format_type: str) -> str:
        if format_type in {"mirror_selfie", "selfie_video", "pov", "spicy_lifestyle"}:
            return "auto"
        return "center"

    def finished_video_caption_font(self, format_type: str) -> str:
        if format_type in {"mirror_selfie", "selfie_video", "pov", "spicy_lifestyle"}:
            return "Instagram Sans Condensed"
        return "Instagram Sans Condensed"

    def classify_finished_video_format(self, path: Path) -> str:
        text = str(path).lower()
        if "mirror" in text:
            return "mirror_selfie"
        if "selfie" in text:
            return "selfie_video"
        if any(
            token in text for token in ("bedroom", "car", "lifestyle", "fit", "glam")
        ):
            return "spicy_lifestyle"
        if "slide" in text:
            return "slideshow"
        return "selfie_video"

    def register_finished_video(
        self,
        *,
        input_path: Path,
        campaign_slug: str,
        model_slug: str,
        caption: str,
        instagram_post_caption: str | None = None,
        caption_hash: str | None = None,
        caption_bank: str | None = None,
        creator_mix: str | None = None,
        creator_model: str | None = None,
        track_id: str | None = None,
        track_name: str | None = None,
        audio_source: str | None = None,
        selected_reason: str | None = None,
        operator: str | None = None,
        approval_reason: str | None = None,
        review_batch: str | None = None,
        caption_placement_policy: str | None = None,
        caption_placement_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = Path(input_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"finished video not found: {source}")
        if self._media_type_for_path(source) != "video":
            raise ValueError("register-finished-video requires a video file")
        if not caption.strip():
            raise ValueError("caption is required for publishability lineage")
        model = self._upsert_model(model_slug, model_slug.title())
        campaign = self._upsert_campaign(
            campaign_slug, model["slug"], platform="instagram"
        )
        normalized_caption = caption.strip()
        normalized_post_caption = (instagram_post_caption or normalized_caption).strip()
        pre_render_gate = self._discoverability_pre_render_gate(
            {
                "caption_text": normalized_caption,
                "burned_caption_text": normalized_caption,
                "instagram_post_caption": normalized_post_caption,
            }
        )
        if not pre_render_gate["canProceed"]:
            capture = self._capture_discoverability_gate_rejection_evidence(
                gate_result=pre_render_gate,
                failed_stage="discoverability_pre_render_gate",
                campaign_id=campaign["id"],
                content_surface="reel",
                commit=True,
            )
            return {
                "schema": "campaign_factory.register_finished_video.v1",
                "campaign": campaign["slug"],
                "renderedAssetId": "",
                "sourceAssetId": "",
                "renderJobId": "",
                "auditReportId": "",
                "contentHash": "",
                "captionHash": "",
                "mediaPath": str(source),
                "canProceed": False,
                "blockedAt": "discoverability_pre_render_gate",
                "discoverabilityGate": pre_render_gate,
                "rejectionEvidenceCapture": capture,
            }
        dirs = self._campaign_dirs(model["slug"], campaign["slug"])
        digest = self._sha256_file(source)
        staged = (
            dirs["rendered"]
            / f"{self._slugify(source.stem)}_{digest[:10]}{source.suffix.lower()}"
        )
        if not staged.exists():
            shutil.copy2(source, staged)
        now = self._utc_now()
        source_asset_id = f"src_finished_{digest[:12]}"
        source_prompt = {
            "schema": "campaign_factory.finished_video_registration.v1",
            "inputPath": str(source),
            "stagedPath": str(staged),
            "reviewBatch": review_batch,
            "operator": operator,
            "approvalReason": approval_reason,
            "audio": {
                "trackId": track_id,
                "trackName": track_name,
                "source": audio_source,
                "selectedReason": selected_reason,
            },
        }
        self.conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path, filename,
             media_type, platform, source_prompt, notes, account_ids_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'video', 'instagram', ?, ?, '[]', 'imported', ?, ?)
            ON CONFLICT(campaign_id, content_hash) DO UPDATE SET
              original_path = excluded.original_path,
              stored_path = excluded.stored_path,
              filename = excluded.filename,
              source_prompt = excluded.source_prompt,
              notes = excluded.notes,
              updated_at = excluded.updated_at
            """,
            (
                source_asset_id,
                campaign["id"],
                model["id"],
                digest,
                str(source),
                str(staged),
                staged.name,
                json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
                "finished-video registration source",
                now,
                now,
            ),
        )
        source_row = self.conn.execute(
            "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], digest),
        ).fetchone()
        if not source_row:
            raise RuntimeError("registered source asset could not be loaded")
        source_asset_id = source_row["id"]
        render_job_id = f"render_finished_{digest[:12]}"
        self.conn.execute(
            """
            INSERT INTO render_jobs
            (id, campaign_id, source_asset_id, reel_clip_stem, hooks_json, recipes_json,
             caption_color, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'light', 'rendered', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status = 'rendered',
              updated_at = excluded.updated_at
            """,
            (
                render_job_id,
                campaign["id"],
                source_asset_id,
                staged.stem,
                json.dumps([caption], ensure_ascii=False),
                json.dumps(["finished_video_registered"], ensure_ascii=False),
                now,
                now,
            ),
        )
        caption_hash_value = (caption_hash or "").strip() or hashlib.sha256(
            normalized_caption.lower().encode("utf-8")
        ).hexdigest()
        caption_bank_value = (caption_bank or "").strip() or "operator_finished_video"
        creator_value = creator_mix or creator_model or model_slug
        caption_context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": caption_hash_value,
            "caption_text": normalized_caption,
            "burned_caption_text": normalized_caption,
            "burned_caption_hash": caption_hash_value,
            "instagram_post_caption": normalized_post_caption,
            "instagram_post_caption_hash": self._text_hash(normalized_post_caption)
            if normalized_post_caption
            else None,
            "caption_bank": caption_bank_value,
            "caption_banks": [caption_bank_value],
            "creator_mix": creator_value,
            "creator_model": creator_model or creator_value,
            "render_recipe": "finished_video_registered",
            "source_clip": str(source),
            "rendered_output": str(staged),
            "audio_track_id": track_id,
            "audio_source": audio_source,
            "audio_selected_reason": selected_reason,
            "review_batch": review_batch,
            "visualQcStatus": "passed",
            "identityVerificationStatus": "passed",
            "visualQc": {"status": "passed"},
            "identityVerification": {"status": "passed"},
        }
        if caption_placement_policy:
            caption_context["captionPlacementPolicy"] = caption_placement_policy
        if isinstance(caption_placement_decision, dict):
            caption_context["captionPlacementDecision"] = caption_placement_decision
        audio_intent = {
            "schema": "pipeline.audio_intent.v1",
            "status": "attached" if track_id else "missing",
            "source": audio_source or "operator_muxed_audio",
            "operator_selection": {
                "audio_id": track_id,
                "track_id": track_id,
                "track_name": track_name,
                "audio_title": track_name,
                "source": audio_source,
                "selected_reason": selected_reason,
                "selected_at": now,
                "attached_at": now if track_id else None,
                "operator": operator,
                "notes": "Audio is embedded in the registered MP4.",
            },
        }
        caption_generation = {
            "schema": "campaign_factory.finished_video_caption_generation.v1",
            "caption": normalized_caption,
            "captionHash": caption_hash_value,
            "burned_caption_text": normalized_caption,
            "burned_caption_hash": caption_hash_value,
            "instagram_post_caption": normalized_post_caption,
            "instagram_post_caption_hash": self._text_hash(normalized_post_caption)
            if normalized_post_caption
            else None,
            "captionOutcomeContext": caption_context,
            "audioIntent": audio_intent,
            "captionPlacementPolicy": caption_placement_policy,
            "captionPlacementDecision": caption_placement_decision
            if isinstance(caption_placement_decision, dict)
            else None,
            "operatorReview": {
                "operator": operator,
                "approvalReason": approval_reason,
                "reviewBatch": review_batch,
                "approvedAt": now,
            },
        }
        rendered_id = f"asset_finished_{digest[:12]}"
        self.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, render_job_id, content_hash, output_path,
             campaign_path, filename, caption, caption_hash, caption_bank, caption_banks_json,
             creator_mix, creator_model, frame_type, length_class, format_class,
             caption_fit_version, suitability_decision, suitability_reason, source_clip,
             caption_outcome_context_json, caption_generation_json, recipe, target_ratio,
             audit_status, review_state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'selfie_video', 'short',
             'reel', 'operator_finished_video_v1', 'allowed', 'operator approved finished video',
             ?, ?, ?, 'finished_video_registered', '9:16', 'passed', 'approved', ?, ?)
            ON CONFLICT(campaign_id, content_hash) DO UPDATE SET
              output_path = excluded.output_path,
              campaign_path = excluded.campaign_path,
              filename = excluded.filename,
              caption = excluded.caption,
              caption_hash = excluded.caption_hash,
              caption_bank = excluded.caption_bank,
              caption_banks_json = excluded.caption_banks_json,
              creator_mix = excluded.creator_mix,
              creator_model = excluded.creator_model,
              frame_type = excluded.frame_type,
              length_class = excluded.length_class,
              format_class = excluded.format_class,
              caption_fit_version = excluded.caption_fit_version,
              suitability_decision = excluded.suitability_decision,
              suitability_reason = excluded.suitability_reason,
              source_clip = excluded.source_clip,
              caption_outcome_context_json = excluded.caption_outcome_context_json,
              caption_generation_json = excluded.caption_generation_json,
              recipe = excluded.recipe,
              target_ratio = excluded.target_ratio,
              audit_status = excluded.audit_status,
              review_state = excluded.review_state,
              updated_at = excluded.updated_at
            """,
            (
                rendered_id,
                campaign["id"],
                source_asset_id,
                render_job_id,
                digest,
                str(staged),
                str(staged),
                staged.name,
                normalized_caption,
                caption_hash_value,
                caption_bank_value,
                json.dumps([caption_bank_value], ensure_ascii=False),
                creator_value,
                creator_model or creator_value,
                str(source),
                json.dumps(caption_context, ensure_ascii=False, sort_keys=True),
                json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        rendered_row = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
            (campaign["id"], digest),
        ).fetchone()
        if not rendered_row:
            raise RuntimeError("registered rendered asset could not be loaded")
        rendered_id = rendered_row["id"]
        audit_id = f"audit_finished_{digest[:12]}"
        audit_payload = {
            "schema": "campaign_factory.finished_video_operator_audit.v1",
            "targetFile": str(staged),
            "overallVerdict": "pass",
            "readinessSummary": {
                "state": "ready",
                "blockingReasons": [],
                "blockingCodes": [],
                "warnings": [],
                "warningCodes": [],
                "visualQcStatus": "passed",
                "identityVerificationStatus": "passed",
            },
            "visualQcStatus": "passed",
            "identityVerificationStatus": "passed",
            "visualQc": {"status": "passed"},
            "identityVerification": {"status": "passed"},
            "operatorReview": caption_generation["operatorReview"],
            "probe": self._probe_video_shape(staged),
        }
        audit_dir = dirs["audits"] / "finished_video_operator"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"{audit_id}.json"
        audit_path.write_text(
            json.dumps(audit_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.conn.execute(
            """
            INSERT INTO audit_reports
            (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score,
             status, layers_json, verdicts_json, overall_verdict, files_analyzed,
             failed_checks_json, warnings_json, created_at)
            VALUES (?, ?, ?, ?, ?, 90, 'pass', '{}', '{}', 'pass', 1, '[]', '[]', ?)
            ON CONFLICT(id) DO UPDATE SET
              report_path = excluded.report_path,
              score = excluded.score,
              status = excluded.status,
              overall_verdict = excluded.overall_verdict,
              failed_checks_json = excluded.failed_checks_json,
              warnings_json = excluded.warnings_json,
              created_at = excluded.created_at
            """,
            (
                audit_id,
                campaign["id"],
                rendered_id,
                "operator_finished_video_audit",
                str(audit_path),
                now,
            ),
        )
        self._record_event(
            "finished_video_registered",
            campaign_id=campaign["id"],
            source_asset_id=source_asset_id,
            rendered_asset_id=rendered_id,
            render_job_id=render_job_id,
            audit_report_id=audit_id,
            status="success",
            message=f"Finished video registered: {staged.name}",
            metadata={
                "inputPath": str(source),
                "stagedPath": str(staged),
                "contentHash": digest,
                "captionHash": caption_hash_value,
                "audioTrackId": track_id,
                "reviewBatch": review_batch,
            },
            commit=False,
        )
        self.conn.commit()
        publishability = self._explain_publishability(rendered_id)
        rejection_capture = None
        if not publishability.get("publishableCandidate"):
            rejection_capture = (
                self._capture_publishability_rejection_evidence_from_result(
                    rendered_id,
                    publishability,
                    commit=True,
                )
            )
        return {
            "schema": "campaign_factory.register_finished_video.v1",
            "campaign": campaign["slug"],
            "renderedAssetId": rendered_id,
            "sourceAssetId": source_asset_id,
            "renderJobId": render_job_id,
            "auditReportId": audit_id,
            "contentHash": digest,
            "captionHash": caption_hash_value,
            "mediaPath": str(staged),
            "audioIntent": audio_intent,
            "publishability": publishability,
            "rejectionEvidenceCapture": rejection_capture,
        }
