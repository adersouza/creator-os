from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from reel_factory.worker_api import (
    contentforge_qc_policy_sha256,
    normalize_profile_id,
    probe_media_identity,
    render_observed_profile,
)

from pipeline_contracts import (
    validate_caption_outcome_context,
    validate_visual_derivative_receipt,
)

from .asset_evidence import invalidate_asset_evidence_after_byte_change
from .persistence import json_load


class ObservedVariantLineageMixin:
    def _eligible_existing_media_parent(self: Any, asset: dict[str, Any]) -> bool:
        digest = str(asset.get("content_hash") or "").lower()
        path = Path(str(asset.get("output_path") or "")).expanduser().resolve()
        if (
            not digest
            or not path.is_file()
            or path.is_symlink()
            or self._sha256_file(path).lower() != digest
        ):
            return False
        row = self.conn.execute(
            """
            SELECT emi.manifest_path, emi.manifest_sha256,
                   emi.audio_receipt_path, emi.audio_receipt_sha256,
                   emi.qc_receipt_path, emi.qc_receipt_sha256
            FROM existing_media_intakes emi
            WHERE emi.rendered_asset_id = ?
              AND emi.final_sha256 = ?
              AND emi.eligibility_state = 'ELIGIBLE'
              AND EXISTS (
                SELECT 1 FROM existing_media_asset_reviews review
                WHERE review.rendered_asset_id = emi.rendered_asset_id
                  AND review.final_sha256 = emi.final_sha256
                  AND review.verdict = 'WOULD_POST'
              )
              AND EXISTS (
                SELECT 1 FROM existing_media_caption_freezes freeze
                WHERE freeze.rendered_asset_id = emi.rendered_asset_id
                  AND freeze.final_sha256 = emi.final_sha256
                  AND freeze.overlay_state = 'NONE_FROZEN'
              )
            ORDER BY emi.updated_at DESC, emi.id DESC
            LIMIT 1
            """,
            (asset["id"], digest),
        ).fetchone()
        if row is None:
            return False
        return all(
            receipt_path.is_file()
            and not receipt_path.is_symlink()
            and self._sha256_file(receipt_path).lower()
            == str(row[sha_column] or "").lower()
            for path_column, sha_column in (
                ("manifest_path", "manifest_sha256"),
                ("audio_receipt_path", "audio_receipt_sha256"),
                ("qc_receipt_path", "qc_receipt_sha256"),
            )
            if (
                receipt_path := Path(str(row[path_column] or "")).expanduser().resolve()
            )
        )

    def _observed_source(
        self: Any, parent: dict[str, Any], *, source_media_path: str | None
    ) -> tuple[Path, str, str]:
        metadata = json_load(parent.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        receipt = metadata.get("audioEmbeddingReceipt")
        original = receipt.get("originalVideo") if isinstance(receipt, dict) else None
        if not isinstance(original, dict) and parent.get("parent_asset_id"):
            ancestor = self.conn.execute(
                "SELECT metadata_json FROM rendered_assets WHERE id = ?",
                (parent["parent_asset_id"],),
            ).fetchone()
            ancestor_metadata = (
                json_load(ancestor["metadata_json"], {}) if ancestor else {}
            )
            ancestor_receipt = (
                ancestor_metadata.get("audioEmbeddingReceipt")
                if isinstance(ancestor_metadata, dict)
                else None
            )
            original = (
                ancestor_receipt.get("originalVideo")
                if isinstance(ancestor_receipt, dict)
                else None
            )
        candidates: list[tuple[Path, str, str]] = []
        if (
            isinstance(original, dict)
            and original.get("path")
            and original.get("sha256")
        ):
            candidates.append(
                (
                    Path(str(original["path"])).expanduser(),
                    str(original["sha256"]).lower(),
                    "audio_receipt_original_visual",
                )
            )
        parent_path = Path(
            str(parent.get("campaign_path") or parent.get("output_path") or "")
        ).expanduser()
        parent_sha = str(parent.get("content_hash") or "").lower()
        if parent_sha:
            candidates.append((parent_path, parent_sha, "parent_final"))
        if source_media_path:
            selected = Path(source_media_path).expanduser().resolve()
            actual = self._sha256_file(selected)
            for _, expected, provenance in candidates:
                if actual == expected:
                    return selected, actual, provenance
            raise ValueError("source_media_path SHA is absent from parent lineage")
        for path, expected, provenance in candidates:
            resolved = path.resolve()
            if (
                resolved.is_file()
                and not resolved.is_symlink()
                and self._sha256_file(resolved) == expected
            ):
                return resolved, expected, provenance
        raise ValueError("verified pre-audio source media is missing")

    def bind_observed_caption(
        self: Any,
        *,
        rendered_asset_id: str,
        output_path: Path,
    ) -> dict[str, Any]:
        """Bind Reel Factory's exact caption render before final audio embedding."""

        asset = self.rendered_asset(rendered_asset_id)
        metadata = json_load(asset.get("metadata_json"), {})
        if (
            asset.get("review_state") != "review_ready"
            or not isinstance(metadata, dict)
            or not isinstance(metadata.get("visualDerivativeReceipt"), dict)
        ):
            raise ValueError("asset is not a review-ready observed derivative")
        current_path = _safe_observed_file(asset.get("output_path"), "current asset")
        current_sha = self._sha256_file(current_path)
        if current_sha != str(asset.get("content_hash") or "").strip().lower():
            raise ValueError("current observed derivative bytes do not match its SHA")
        observed_visual_sha = (
            str(metadata["visualDerivativeReceipt"].get("outputSha256") or "")
            .strip()
            .lower()
        )

        output = _safe_observed_file(output_path, "captioned output")
        caption_path = Path(str(output) + ".caption_lineage.json")
        generated_path = Path(str(output) + ".generated_asset_lineage.json")
        caption_lineage = _load_observed_json(caption_path, "caption lineage")
        generated_lineage = _load_observed_json(
            generated_path, "generated asset lineage"
        )
        source = generated_lineage.get("source")
        render = generated_lineage.get("render")
        caption_source_sha = (
            str(source.get("sourceVideoHash") or "").strip().lower()
            if isinstance(source, dict)
            else ""
        )
        if caption_source_sha != observed_visual_sha:
            raise ValueError("caption render source SHA does not match observed asset")
        if current_sha != observed_visual_sha:
            audio_receipt = metadata.get("audioEmbeddingReceipt")
            final_video = (
                audio_receipt.get("finalVideo")
                if isinstance(audio_receipt, dict)
                else None
            )
            if (
                not isinstance(final_video, dict)
                or str(final_video.get("sha256") or "").strip().lower() != current_sha
            ):
                raise ValueError("current final is not a verified retryable derivative")
        if (
            not isinstance(render, dict)
            or Path(str(render.get("outputPath") or "")).resolve() != output
        ):
            raise ValueError("generated asset lineage is not bound to captioned output")
        output_sha = self._sha256_file(output)
        if generated_lineage.get("contentFingerprint") != output_sha:
            raise ValueError("captioned output SHA does not match generated lineage")

        context = caption_lineage.get("captionOutcomeContext")
        pixel = caption_lineage.get("captionPixelRenderEvidence")
        if (
            caption_lineage.get("captionBurnedIn") is not True
            or not isinstance(pixel, dict)
            or pixel.get("rendered") is not True
            or Path(str(pixel.get("outputPath") or "")).resolve() != output
            or (caption_lineage.get("overlaySemanticQc") or {}).get("passed")
            is not True
            or (caption_lineage.get("captionTimingQc") or {}).get("passed") is not True
            or (caption_lineage.get("captionPlacementDecision") or {}).get("status")
            != "passed"
            or not isinstance(context, dict)
        ):
            raise ValueError(
                "caption lineage does not prove an accepted burned caption"
            )
        validate_caption_outcome_context(context)
        context = {
            **context,
            "render_recipe": "reel_factory_observed_profile_captioned",
        }

        attempt = self.conn.execute(
            """
            SELECT id FROM generation_attempts
            WHERE rendered_asset_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (rendered_asset_id,),
        ).fetchone()
        if not attempt:
            raise ValueError("observed derivative has no generation attempt lineage")

        now = self._utc_now()
        caption_text = str(caption_lineage.get("rawCaptionText") or "").strip()
        caption_hash = str(caption_lineage.get("captionHash") or "").strip()
        selected_banks = caption_lineage.get("selectedBanks") or []
        selected_mix = str(caption_lineage.get("selectedMix") or "").strip() or None
        caption_generation = {
            "generatedAssetLineage": generated_lineage,
            "captionLineage": caption_lineage,
        }
        receipt = {
            "schema": "campaign_factory.observed_caption_binding.v1",
            "inputSha256": caption_source_sha,
            "replacesSha256": current_sha,
            "outputSha256": output_sha,
            "outputPath": str(output),
            "captionLineagePath": str(caption_path),
            "captionLineageSha256": self._sha256_file(caption_path),
            "generatedAssetLineagePath": str(generated_path),
            "generatedAssetLineageSha256": self._sha256_file(generated_path),
            "boundAt": now,
        }
        publishability = metadata.get("publishability")
        if not isinstance(publishability, dict):
            publishability = {}
        blocking = [
            str(value)
            for value in (publishability.get("blockingIssues") or [])
            if str(value) != "parent_audio_rebinding_required"
        ]
        if "parent_audio_rebinding_required" not in blocking:
            blocking.append("parent_audio_rebinding_required")
        metadata.update(
            {
                "asset_state": "review_ready",
                "burnedCaption": True,
                "captionRenderReceipt": receipt,
                "publishability": {
                    **publishability,
                    "status": "blocked",
                    "blockingIssues": blocking,
                },
            }
        )
        blob_id = f"blob_caption_{output_sha[:24]}"
        edge_id = f"edge_caption_{output_sha[:24]}"
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO generation_output_blobs
                (id, content_sha256, byte_size, media_type, created_at)
                VALUES (?, ?, ?, 'video', ?)
                """,
                (blob_id, output_sha, output.stat().st_size, now),
            )
            self.conn.execute(
                """
                INSERT OR IGNORE INTO generation_lineage_edges
                (id, generation_attempt_id, source_asset_id, rendered_asset_id,
                 output_blob_id, relation, lineage_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'caption_render', ?, ?)
                """,
                (
                    edge_id,
                    str(attempt["id"]),
                    str(asset["source_asset_id"]),
                    rendered_asset_id,
                    blob_id,
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            self.conn.execute(
                """
                UPDATE rendered_assets
                SET output_path = ?, campaign_path = ?, filename = ?,
                    caption = ?, caption_hash = ?, caption_banks_json = ?,
                    creator_mix = COALESCE(?, creator_mix),
                    caption_outcome_context_json = ?, caption_generation_json = ?,
                    metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(output),
                    str(output),
                    output.name,
                    caption_text,
                    caption_hash,
                    json.dumps(selected_banks, ensure_ascii=False),
                    selected_mix,
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    json.dumps(caption_generation, ensure_ascii=False, sort_keys=True),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    now,
                    rendered_asset_id,
                ),
            )
            invalidate_asset_evidence_after_byte_change(
                self.conn,
                rendered_asset_id=rendered_asset_id,
                previous_sha=current_sha,
                new_sha=output_sha,
                mutation_type="caption_render",
                mutation_receipt=receipt,
                changed_at=now,
            )
        return {
            **receipt,
            "renderedAssetId": rendered_asset_id,
            "lineageEdgeId": edge_id,
            "reviewState": "review_ready",
        }

    def _generate_observed_variants(
        self: Any,
        *,
        parent_asset_id: str,
        caption_version_id: str | None,
        count: int,
        profile: str,
        attempt_limit: int | None,
        contentforge_base_url: str | None,
        source_media_path: str | None,
    ) -> dict[str, Any]:
        from .adapters.contentforge import audit_variation_batch

        profile_id = normalize_profile_id(profile)
        plan = self.variant_plan(
            parent_asset_id=parent_asset_id,
            caption_version_id=caption_version_id,
            count=count,
            profile=profile,
        )
        if not plan.get("canGenerate"):
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
                "blockingReason": plan.get("blockingReason"),
                "plan": plan,
                "registeredVariants": [],
            }
        parent = self.rendered_asset(parent_asset_id)
        source, source_sha, source_provenance = self._observed_source(
            parent, source_media_path=source_media_path
        )
        media = probe_media_identity(source)
        metadata = json_load(parent.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        ancestor_metadata: dict[str, Any] = {}
        if parent.get("parent_asset_id"):
            ancestor = self.conn.execute(
                "SELECT metadata_json FROM rendered_assets WHERE id = ?",
                (parent["parent_asset_id"],),
            ).fetchone()
            if ancestor:
                loaded = json_load(ancestor["metadata_json"], {})
                if isinstance(loaded, dict):
                    ancestor_metadata = loaded
        explicit_caption_state = metadata.get(
            "burnedCaption", metadata.get("captionBurned")
        )
        captioned = bool(
            explicit_caption_state
            if explicit_caption_state is not None
            else source_provenance == "parent_final"
            and (
                str(parent.get("caption") or "").strip()
                or str(parent.get("caption_hash") or "").strip()
            )
        )
        production_recipe = metadata.get("productionMotionRecipe")
        ancestor_recipe = ancestor_metadata.get("productionMotionRecipe")
        motion_intent = str(
            metadata.get("motionIntent")
            or (
                production_recipe.get("intent")
                if isinstance(production_recipe, dict)
                else ""
            )
            or ancestor_metadata.get("motionIntent")
            or (
                ancestor_recipe.get("intent")
                if isinstance(ancestor_recipe, dict)
                else ""
            )
            or ""
        ).lower()
        synchronized = bool(
            metadata.get("synchronizedContent")
            or metadata.get("referenceTalking")
            or ancestor_metadata.get("synchronizedContent")
            or ancestor_metadata.get("referenceTalking")
            or motion_intent in {"talking", "dance", "motion_copy", "recreate_reel"}
        )
        passive = media["mediaType"] == "image" or bool(
            metadata.get("passiveContent")
            or ancestor_metadata.get("passiveContent")
            or str(
                metadata.get("creationMode")
                or ancestor_metadata.get("creationMode")
                or ""
            ).lower()
            in {"static_reel", "calm_animation"}
            or motion_intent in {"ambient", "calm", "passive", "passive_selfie"}
        )
        audio_state = (
            "final_bound"
            if source_provenance == "parent_final" and metadata.get("audioBurned")
            else "pre_final"
            if media.get("audioPresent")
            else "none"
        )
        model_slug = self._model_slug_for_campaign(parent["campaign_id"])
        campaign_row = self.conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", (parent["campaign_id"],)
        ).fetchone()
        if not campaign_row:
            raise ValueError(f"campaign not found for parent asset: {parent_asset_id}")
        dirs = self.campaign_dirs(model_slug, campaign_row["slug"])
        family_id = str(plan["variantFamilyId"])
        output_dir = dirs["rendered"] / "observed_profiles" / family_id
        audit_dir = dirs["audits"] / "observed_profiles" / family_id
        endpoint = contentforge_base_url or self.settings.contentforge_base_url
        visible_text = False
        if profile_id == "mirror_crop_tone":
            preflight_path = audit_dir / "source_text_preflight.json"
            try:
                preflight = audit_variation_batch(
                    contentforge_root=self.settings.contentforge_root,
                    source_path=source,
                    variant_paths=[source],
                    contentforge_base_url=endpoint,
                    report_path=preflight_path,
                )
                ocr = preflight.get("ocr")
                results = ocr.get("results") if isinstance(ocr, dict) else None
                if not isinstance(ocr, dict) or ocr.get("available") is not True:
                    return {
                        "schema": "campaign_factory.generate_variants.v1",
                        "status": "blocked",
                        "blockingReason": "mirror_ocr_preflight_unavailable",
                        "plan": plan,
                        "registeredVariants": [],
                    }
                visible_text = any(
                    str(item.get("ocrText") or "").strip()
                    for item in (results or [])
                    if isinstance(item, dict)
                )
            except Exception as exc:
                return {
                    "schema": "campaign_factory.generate_variants.v1",
                    "status": "blocked",
                    "blockingReason": "mirror_ocr_preflight_failed",
                    "plan": plan,
                    "registeredVariants": [],
                    "error": str(exc),
                }

        def qc_callback(
            original: Path, candidate: Path, siblings: list[Path]
        ) -> dict[str, Any]:
            report_path = audit_dir / f"{candidate.stem}.contentforge.json"
            report = audit_variation_batch(
                contentforge_root=self.settings.contentforge_root,
                source_path=original,
                variant_paths=[candidate, *siblings],
                contentforge_base_url=endpoint,
                report_path=report_path,
            )
            readiness = report.get("readinessSummary") or {}
            verdicts = report.get("verdicts") or {}
            blocking = [
                str(code)
                for code in (
                    readiness.get("blockingCodes")
                    or readiness.get("blockingReasons")
                    or []
                )
            ]
            if report.get("contractVersion") not in {
                "campaign_factory_audit.v1.7",
                "campaign_factory_audit.v1.8",
                "campaign_factory_audit.v1.9",
                "campaign_factory_audit.v1.10",
            }:
                blocking.append("contentforge_contract_invalid")
            if readiness.get("uploadReady") is not True:
                blocking.append("contentforge_not_upload_ready")
            for layer in ("pdq", "sscd"):
                if verdicts.get(layer) != "pass":
                    blocking.append(f"contentforge_{layer}_failed")
            return {
                "status": "passed" if not blocking else "failed",
                "blockingCodes": list(dict.fromkeys(blocking)),
                "reportPath": str(report_path),
                "contractVersion": report.get("contractVersion"),
                "runId": report.get("runId"),
                "verdicts": {"pdq": verdicts.get("pdq"), "sscd": verdicts.get("sscd")},
                "sourceQc": True,
                "siblingQc": True,
                "ocrReadabilityQc": True,
                "focalSafetyQc": True,
                "watchabilityQc": True,
                "mediaIntegrityQc": True,
            }

        audio_embedder_path = Path(__file__).with_name("audio_radar") / "embedding.py"
        receipt = render_observed_profile(
            source_path=source,
            output_dir=output_dir,
            parent_asset_id=parent_asset_id,
            expected_source_sha256=source_sha,
            profile=f"{profile_id}@1",
            target_accepted_count=count,
            caption_state="captioned" if captioned else "uncaptioned_verified",
            audio_state=audio_state,
            passive_content=passive,
            synchronized_content=synchronized,
            visible_text=visible_text,
            attempt_limit=attempt_limit,
            qc_callback=qc_callback,
            qc_policy_sha256=contentforge_qc_policy_sha256(
                self.settings.contentforge_root
            ),
            audio_embedder_sha256=(
                self._sha256_file(audio_embedder_path)
                if audio_embedder_path.is_file()
                else None
            ),
        )
        validate_visual_derivative_receipt(receipt)
        registered = self._register_observed_derivatives(
            parent=parent,
            plan=plan,
            receipt=receipt,
            source_provenance=source_provenance,
        )
        return {
            "schema": "campaign_factory.generate_variants.v1",
            "status": (
                "completed"
                if len(registered) == count
                else "exhausted"
                if registered
                else "blocked"
            ),
            "blockingReason": (
                None
                if registered
                else ",".join(receipt.get("exhaustionReasons") or [])
                or "no_derivatives_accepted"
            ),
            "plan": plan,
            "derivativeReceipt": receipt,
            "registeredVariants": registered,
        }

    def _register_observed_derivatives(
        self: Any,
        *,
        parent: dict[str, Any],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        source_provenance: str,
    ) -> list[dict[str, Any]]:
        accepted = receipt.get("accepted") or []
        if not accepted:
            return []
        receipt_path = Path(str(accepted[0]["output"]["path"])).parent / (
            f"{parent['id']}_{receipt['profile']['id']}.visual_derivative_receipt.json"
        )
        receipt_sha = self._sha256_file(receipt_path)
        now = self._utc_now()
        registered: list[dict[str, Any]] = []
        savepoint = f"observed_profile_register_{uuid.uuid4().hex[:12]}"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            for item in accepted:
                output = item["output"]
                output_path = Path(str(output["path"]))
                digest = str(output["sha256"])
                asset_id = f"asset_observed_{digest[:16]}"
                accepted_index = int(item["acceptedIndex"])
                operations = [
                    {
                        "type": "reel_factory_observed_profile",
                        "profile": f"{receipt['profile']['id']}@1",
                        "candidateIndex": item["candidateIndex"],
                        "acceptedIndex": accepted_index,
                        "sampledParameters": item["sampledParameters"],
                    },
                    {
                        "type": "preserve_parent_lineage",
                        "parentAssetId": parent["id"],
                        "sourceProvenance": source_provenance,
                        "sourceSha256": receipt["source"]["sha256"],
                    },
                ]
                metadata = {
                    "asset_state": "review_ready",
                    "audioBurned": False,
                    "observedProfile": f"{receipt['profile']['id']}@1",
                    "visualDerivativeReceipt": {
                        "path": str(receipt_path),
                        "sha256": receipt_sha,
                        "toolchainFingerprint": receipt["toolchain"]["fingerprint"],
                        "sourceSha256": receipt["source"]["sha256"],
                        "outputSha256": digest,
                        "acceptedIndex": accepted_index,
                    },
                    "publishability": {
                        "status": "blocked",
                        "blockingIssues": [
                            "exact_final_sha_approval_required",
                            "parent_audio_rebinding_required",
                        ],
                    },
                }
                self.conn.execute(
                    """
                    INSERT INTO rendered_assets
                    (id, campaign_id, source_asset_id, parent_asset_id, content_hash,
                     output_path, campaign_path, filename, media_type, content_surface,
                     caption, caption_hash, caption_banks_json, creator_mix, creator_model,
                     frame_type, length_class, format_class, caption_outcome_context_json,
                     caption_generation_json, recipe, target_ratio, metadata_json,
                     audit_status, review_state, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '[]', ?, ?, ?, ?, ?,
                            '{}', '{}', 'reel_factory_observed_profile', ?, ?, 'passed',
                            'review_ready', ?, ?)
                    ON CONFLICT(campaign_id, content_hash) DO NOTHING
                    """,
                    (
                        asset_id,
                        parent["campaign_id"],
                        parent["source_asset_id"],
                        parent["id"],
                        digest,
                        str(output_path),
                        str(output_path),
                        output_path.name,
                        output["mediaType"],
                        parent.get("content_surface") or "reel",
                        parent.get("creator_mix"),
                        parent.get("creator_model"),
                        parent.get("frame_type"),
                        parent.get("length_class"),
                        parent.get("format_class"),
                        parent.get("target_ratio"),
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                row = self.conn.execute(
                    "SELECT id FROM rendered_assets WHERE campaign_id = ? AND content_hash = ?",
                    (parent["campaign_id"], digest),
                ).fetchone()
                if not row:
                    continue
                asset_id = str(row["id"])
                blob_id = f"blob_observed_{digest[:24]}"
                attempt_id = (
                    f"attempt_observed_{receipt['profile']['id']}_{digest[:16]}"
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO generation_output_blobs
                    (id, content_sha256, byte_size, media_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        blob_id,
                        digest,
                        int(output["byteSize"]),
                        output["mediaType"],
                        now,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO generation_attempts
                    (id, campaign_id, source_asset_id, rendered_asset_id, output_blob_id,
                     request_fingerprint, model_id, motion_task, source_sha256, input_json,
                     worker_result_json, attempted_output_path, duplicate_disposition,
                     created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'reel_factory.observed_profiles@1',
                            'visual_derivative', ?, ?, ?, ?, 'unique_output', ?)
                    """,
                    (
                        attempt_id,
                        parent["campaign_id"],
                        parent["source_asset_id"],
                        asset_id,
                        blob_id,
                        receipt["toolchain"]["fingerprint"],
                        receipt["source"]["sha256"],
                        json.dumps(
                            {
                                "profile": receipt["profile"],
                                "eligibility": receipt["eligibility"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                        str(output_path),
                        now,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO generation_lineage_edges
                    (id, generation_attempt_id, source_asset_id, rendered_asset_id,
                     output_blob_id, relation, lineage_json, created_at)
                    VALUES (?, ?, ?, ?, ?, 'visual_derivative', ?, ?)
                    """,
                    (
                        f"edge_observed_{digest[:24]}",
                        attempt_id,
                        parent["source_asset_id"],
                        asset_id,
                        blob_id,
                        json.dumps(
                            {
                                "parentAssetId": parent["id"],
                                "sourceProvenance": source_provenance,
                                "receiptPath": str(receipt_path),
                                "receiptSha256": receipt_sha,
                                "accepted": item,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
                qc = item["qc"]
                audit_id = f"audit_observed_{digest[:16]}"
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO audit_reports
                    (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path,
                     score, status, layers_json, verdicts_json, overall_verdict,
                     files_analyzed, failed_checks_json, warnings_json, created_at)
                    VALUES (?, ?, ?, ?, ?, 100, 'pass', '{}', ?, 'pass', 1, '[]', '[]', ?)
                    """,
                    (
                        audit_id,
                        parent["campaign_id"],
                        asset_id,
                        qc.get("runId"),
                        qc["reportPath"],
                        json.dumps(qc.get("verdicts") or {}, sort_keys=True),
                        now,
                    ),
                )
                registered.append(
                    self._register_variant_asset(
                        parent_asset_id=parent["id"],
                        variant_asset_id=asset_id,
                        variant_family_id=plan["variantFamilyId"],
                        variant_index=accepted_index,
                        operations=operations,
                        contentforge_run_id=qc.get("runId"),
                        contentforge_preset=f"{receipt['profile']['id']}@1",
                        qc_status="passed",
                        commit=False,
                    )
                )
        except Exception:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        self.conn.commit()
        return registered


def _safe_observed_file(value: object, label: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    return path


def _load_observed_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value
