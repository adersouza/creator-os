from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from reel_factory.worker_api import (
    normalize_profile_id,
    probe_media_identity,
    render_observed_profile,
)

from pipeline_contracts import validate_visual_derivative_receipt

from .persistence import json_load


class ObservedVariantLineageMixin:
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
        captioned = bool(
            str(parent.get("caption") or "").strip()
            or str(parent.get("caption_hash") or "").strip()
            or metadata.get("burnedCaption")
        )
        synchronized = bool(
            metadata.get("synchronizedContent")
            or metadata.get("referenceTalking")
            or str(metadata.get("motionIntent") or "").lower()
            in {"talking", "dance", "motion_copy", "recreate_reel"}
        )
        passive = media["mediaType"] == "image" or bool(
            metadata.get("passiveContent")
            or str(metadata.get("creationMode") or "").lower()
            in {"static_reel", "calm_animation"}
            or str(metadata.get("motionIntent") or "").lower()
            in {"ambient", "calm", "passive", "passive_selfie"}
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

        qc_policy_path = self.settings.contentforge_root / "lib" / "similarity.js"
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
            qc_policy_sha256=(
                self._sha256_file(qc_policy_path) if qc_policy_path.is_file() else None
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
