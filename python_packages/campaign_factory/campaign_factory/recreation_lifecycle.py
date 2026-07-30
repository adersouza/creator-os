"""Paid anchor generation, recreation review decisions, and lineage explanation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .front_generation_stage import _invoke_generate_assets
from .generation_execution_plan import build_generation_execution_plan
from .production_source_selection import active_production_identity
from .recreation_prompting import validate_prompt_pack


def generate_recreation_anchor(
    factory: Any,
    *,
    creator: str,
    prompt_pack_path: Path,
    attempt_id: str | None,
    max_credits: float,
) -> dict[str, Any]:
    """Run one explicitly authorized text-only Soul call and register its bytes."""

    creator_slug, soul_id = active_production_identity(factory, creator)
    prompt_path = _regular_file(prompt_pack_path, "prompt pack")
    prompt_pack = validate_prompt_pack(
        json.loads(prompt_path.read_text(encoding="utf-8"))
    )
    if prompt_pack.get("creator") != creator_slug:
        raise PermissionError("recreation_anchor_prompt_pack_creator_mismatch")
    creator_image = prompt_pack.get("creatorImage")
    if not isinstance(creator_image, dict):
        raise ValueError("recreation_anchor_creator_image_lineage_missing")
    campaign, source = _campaign_source_for_sha(
        factory, creator_slug, str(creator_image.get("sha256") or "")
    )
    attempt = _attempt_id(
        attempt_id or f"anchor_{prompt_pack['promptPackFingerprint'][:16]}_attempt_1"
    )
    root = factory.settings.reference_reels_root / "anchor_generations" / creator_slug
    root.mkdir(parents=True, exist_ok=True)
    prompt_contract = root / f"{attempt}.prompt.json"
    atomic_write_text(
        prompt_contract,
        json.dumps(
            {
                "higgsfieldGridPrompt": prompt_pack["anchorPrompt"],
                "klingMotionPrompt": "Subtle stable natural motion.",
                "notes": (
                    "Recreation identity anchor; prompt pack "
                    f"{prompt_pack['promptPackFingerprint']}"
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    execution_plan_path = root / f"{attempt}.execution_plan.json"
    atomic_write_text(
        execution_plan_path,
        json.dumps(
            build_generation_execution_plan("soul_static").to_contract(),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    pipeline_job = factory.domains.events.create_pipeline_job(
        "recreation_anchor_generation",
        campaign["id"],
        {
            "attemptId": attempt,
            "creator": creator_slug,
            "sourceAssetId": source["id"],
            "creatorImageSha256": source["content_hash"],
            "referenceVideoSha256": (prompt_pack.get("referenceVideo") or {}).get(
                "sha256"
            ),
            "promptPackPath": str(prompt_path),
            "promptPackFingerprint": prompt_pack["promptPackFingerprint"],
        },
    )
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        result = _invoke_generate_assets(
            factory,
            [
                "image",
                "--prompt-json",
                str(prompt_contract),
                "--stem",
                attempt,
                "--campaign",
                str(campaign["slug"]),
                "--creator",
                creator_slug,
                "--soul-id",
                soul_id,
                "--cohort-id",
                f"recreation_anchor:{attempt}",
                "--image-aspect-ratio",
                "9:16",
                "--image-quality",
                "2k",
                "--max-credits",
                str(max_credits),
                "--download",
                "--wait",
                "--out-dir",
                str(root),
                "--execution-plan-file",
                str(execution_plan_path),
            ],
        )
        if result.get("ok") is not True:
            raise RuntimeError(
                f"recreation_anchor_generation_failed:{result.get('error')}"
            )
        local_paths = ((result.get("lineage") or {}).get("assets") or {}).get(
            "localPaths"
        ) or {}
        anchor = _regular_file(
            Path(str(local_paths.get("image") or "")), "generated anchor"
        )
        digest = _sha256(anchor)
        generation = (result.get("lineage") or {}).get("generation") or {}
        generation_id = str(generation.get("imageJobId") or "")
        if not generation_id:
            raise RuntimeError("recreation_anchor_generation_id_missing")
        registered = _register_anchor_candidate(
            factory,
            campaign=campaign,
            source=source,
            anchor=anchor,
            digest=digest,
            attempt_id=attempt,
            generation_id=generation_id,
            prompt_pack=prompt_pack,
            lineage_path=Path(str(result["path"])).resolve(),
            spend_receipt=result.get("campaignSpendReceipt"),
        )
        completed = {
            "schema": "campaign_factory.recreation_anchor_generation.v1",
            "status": "completed",
            "providerExecutionStatus": "completed",
            "creativeDecision": "pending",
            "publishability": "blocked_pending_anchor_approval",
            "learningEligible": False,
            "pipelineJobId": pipeline_job["id"],
            "attemptId": attempt,
            "generationId": generation_id,
            "anchorPath": str(anchor),
            "anchorSha256": digest,
            "lineagePath": str(Path(str(result["path"])).resolve()),
            "sourceAsset": registered,
            "approvalRequired": True,
            "retryRequiresFreshAuthorization": True,
            "campaignSpendReceipt": result.get("campaignSpendReceipt"),
        }
        factory.domains.events.finish_pipeline_job(pipeline_job["id"], completed)
        return completed
    except Exception as exc:
        factory.domains.events.fail_pipeline_job(
            pipeline_job["id"], str(exc), {"attemptId": attempt}
        )
        raise


def record_recreation_review(
    factory: Any,
    *,
    job_id: str,
    stage: str,
    decision: str,
    reviewed_by: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record an exact-stage decision without rewriting provider success."""

    if stage not in {"anchor", "final_video"}:
        raise ValueError("recreation review stage must be anchor or final_video")
    if decision not in {"approved", "rejected"}:
        raise ValueError("recreation review decision must be approved or rejected")
    if stage == "anchor" and decision == "approved":
        raise ValueError(
            "approve anchors with recreation-anchor-approve to bind exact bytes"
        )
    job = _find_job(factory, job_id)
    if stage == "anchor" and job["jobType"] != "recreation_anchor_generation":
        raise ValueError("anchor review requires a recreation anchor generation job")
    if stage == "final_video" and job["jobType"] != "higgsfield_motion_generation":
        raise ValueError("final video review requires a recreation motion job")
    evidence = _recreation_evidence(factory, job)
    if stage == "anchor":
        subject_sha = evidence["anchor"]["sha256"]
        source_asset_id = evidence["anchor"].get("sourceAssetId")
        rendered_asset_id = None
        retry_branch = "new_soul_anchor" if decision == "rejected" else "seedance"
    else:
        subject_sha = evidence["finalVideo"]["sha256"]
        source_asset_id = None
        rendered_asset_id = evidence["finalVideo"].get("renderedAssetId")
        retry_branch = (
            "retain_anchor_new_seedance" if decision == "rejected" else "none"
        )
    reviewed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    core = {
        "schema": "campaign_factory.recreation_review_decision.v1",
        "pipelineJobId": job["id"],
        "workItemId": evidence["workItemId"],
        "stage": stage,
        "subjectSha256": subject_sha,
        "decision": decision,
        "reviewedBy": _required(reviewed_by, "reviewed by"),
        "reviewedAt": reviewed_at,
        "notes": str(notes or "").strip() or None,
        "providerExecutionStatus": evidence["providerExecutionStatus"],
        "technicalArtifactStatus": evidence["technicalArtifactStatus"],
        "publishability": (
            "eligible_for_normal_approval_flow"
            if stage == "final_video" and decision == "approved"
            else "blocked"
        ),
        "learningEligible": False,
        "retry": {
            "branch": retry_branch,
            "automatic": False,
            "freshSpendAuthorizationRequired": decision == "rejected",
        },
        "identityComparison": evidence["identityComparison"],
    }
    receipt = {**core, "decisionFingerprint": _fingerprint(core)}
    root = factory.settings.reference_reels_root / "recreation_reviews"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{receipt['decisionFingerprint']}.json"
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError:
        if path.is_symlink() or path.read_text(encoding="utf-8") != serialized:
            raise PermissionError("recreation_review_decision_collision") from None
    if rendered_asset_id:
        factory.conn.execute(
            "UPDATE rendered_assets SET review_state = ?, updated_at = ? WHERE id = ?",
            (
                "rejected" if decision == "rejected" else "draft",
                reviewed_at,
                rendered_asset_id,
            ),
        )
    if source_asset_id and decision == "rejected":
        factory.conn.execute(
            "UPDATE source_assets SET status = 'rejected', updated_at = ? WHERE id = ?",
            (reviewed_at, source_asset_id),
        )
    event = factory.domains.events.record_event(
        "recreation_review_decision",
        campaign_id=job.get("campaignId"),
        source_asset_id=source_asset_id,
        rendered_asset_id=rendered_asset_id,
        pipeline_job_id=job["id"],
        status="warning" if decision == "rejected" else "success",
        message=f"Recreation {stage} {decision}",
        metadata={**receipt, "receiptPath": str(path)},
    )
    return {**receipt, "receiptPath": str(path), "activityEventId": event["id"]}


def explain_recreation_job(factory: Any, job_id: str) -> dict[str, Any]:
    job = _find_job(factory, job_id)
    evidence = _recreation_evidence(factory, job)
    decisions = [
        {
            **json.loads(str(row["metadata_json"] or "{}")),
            "activityEventId": row["id"],
        }
        for row in factory.conn.execute(
            """
            SELECT id, metadata_json FROM activity_events
            WHERE pipeline_job_id = ? AND event_type = 'recreation_review_decision'
            ORDER BY created_at, id
            """,
            (job["id"],),
        ).fetchall()
    ]
    return {
        "schema": "campaign_factory.recreation_explain.v1",
        "pipelineJob": {
            "id": job["id"],
            "workItemId": evidence["workItemId"],
            "status": job["status"],
            "attemptCount": job["attemptCount"],
        },
        "reference": evidence["reference"],
        "selectedFrame": evidence["selectedFrame"],
        "promptPack": evidence["promptPack"],
        "soulGeneration": evidence["soulGeneration"],
        "anchorApproval": evidence["anchorApproval"],
        "seedanceRequest": evidence["seedanceRequest"],
        "referenceElement": evidence["referenceElement"],
        "finalVideo": evidence["finalVideo"],
        "audioReceipt": evidence["audioReceipt"],
        "technicalQc": evidence["technicalQc"],
        "identityComparison": evidence["identityComparison"],
        "reviewDecisions": decisions,
        "finalApproval": _final_approval(
            factory, evidence["finalVideo"].get("renderedAssetId")
        ),
        "providerExecutionStatus": evidence["providerExecutionStatus"],
        "technicalArtifactStatus": evidence["technicalArtifactStatus"],
        "publishability": "blocked_pending_explicit_final_approval",
        "learningEligible": False,
    }


def _campaign_source_for_sha(
    factory: Any, creator: str, digest: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    row = factory.conn.execute(
        """
        SELECT s.*, c.slug AS campaign_slug, c.updated_at AS campaign_updated_at
        FROM source_assets s
        JOIN campaigns c ON c.id = s.campaign_id
        JOIN models m ON m.id = s.model_id
        WHERE lower(m.slug) = ? AND s.content_hash = ? AND s.media_type = 'image'
          AND lower(COALESCE(s.status, 'imported')) = 'approved'
        ORDER BY c.updated_at DESC, s.created_at DESC LIMIT 1
        """,
        (creator, digest),
    ).fetchone()
    if row is None:
        raise PermissionError("recreation_creator_image_not_exact_approved_inventory")
    source = dict(row)
    path = _regular_file(Path(str(source["stored_path"])), "creator image")
    if _sha256(path) != digest:
        raise PermissionError("recreation_creator_image_sha_mismatch")
    campaign = factory.domains.campaign_by_slug(str(source["campaign_slug"]))
    return campaign, source


def _register_anchor_candidate(
    factory: Any,
    *,
    campaign: dict[str, Any],
    source: dict[str, Any],
    anchor: Path,
    digest: str,
    attempt_id: str,
    generation_id: str,
    prompt_pack: dict[str, Any],
    lineage_path: Path,
    spend_receipt: Any,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    source_id = (
        "source_recreation_anchor_"
        + hashlib.sha256(f"{campaign['id']}:{digest}".encode()).hexdigest()[:20]
    )
    lineage = {
        "schema": "campaign_factory.recreation_anchor_candidate.v1",
        "derivedFromSourceAssetId": source["id"],
        "creatorImageSha256": source["content_hash"],
        "referenceVideoSha256": (prompt_pack.get("referenceVideo") or {}).get("sha256"),
        "promptPackFingerprint": prompt_pack["promptPackFingerprint"],
        "attemptId": attempt_id,
        "generationId": generation_id,
        "anchorSha256": digest,
        "lineagePath": str(lineage_path),
        "campaignSpendReceipt": spend_receipt,
        "creativeDecision": "pending",
        "learningEligible": False,
    }
    factory.conn.execute(
        """
        INSERT OR IGNORE INTO source_assets
        (id, campaign_id, model_id, content_hash, original_path, stored_path, filename,
         media_type, content_surface, platform, source_prompt, higgsfield_job_id,
         higgsfield_model, notes, account_ids_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'image', 'reel', 'instagram', ?, ?, 'soul_2',
                'recreation identity anchor review candidate', '[]', 'imported', ?, ?)
        """,
        (
            source_id,
            campaign["id"],
            source["model_id"],
            digest,
            str(anchor),
            str(anchor),
            anchor.name,
            json.dumps(lineage, sort_keys=True),
            generation_id,
            now,
            now,
        ),
    )
    factory.conn.commit()
    row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE campaign_id = ? AND content_hash = ?",
        (campaign["id"], digest),
    ).fetchone()
    if row is None:
        raise RuntimeError("recreation_anchor_registration_failed")
    return dict(row)


def _find_job(factory: Any, job_id: str) -> dict[str, Any]:
    try:
        return factory.domains.events.pipeline_job(job_id)
    except ValueError:
        rows = factory.domains.events.jobs_for_campaign(limit=1000)
        matches = [
            row for row in rows if (row.get("input") or {}).get("jobId") == job_id
        ]
        if len(matches) != 1:
            raise ValueError(f"recreation pipeline job not found: {job_id}") from None
        return matches[0]


def _recreation_evidence(factory: Any, job: dict[str, Any]) -> dict[str, Any]:
    input_payload = job.get("input") or {}
    result = job.get("result") or {}
    if job["jobType"] == "recreation_anchor_generation":
        source = result.get("sourceAsset") or {}
        return {
            "workItemId": str(input_payload.get("attemptId") or ""),
            "reference": {
                "id": None,
                "sha256": input_payload.get("referenceVideoSha256"),
                "path": None,
            },
            "selectedFrame": {"sha256": None},
            "promptPack": {
                "fingerprint": input_payload.get("promptPackFingerprint"),
                "path": input_payload.get("promptPackPath"),
            },
            "soulGeneration": {
                "id": result.get("generationId"),
                "model": "soul_2",
                "attemptId": result.get("attemptId"),
                "lineagePath": result.get("lineagePath"),
                "campaignSpendReceipt": result.get("campaignSpendReceipt"),
            },
            "anchorApproval": None,
            "anchor": {
                "path": result.get("anchorPath"),
                "sha256": result.get("anchorSha256"),
                "sourceAssetId": source.get("id"),
            },
            "seedanceRequest": None,
            "referenceElement": None,
            "finalVideo": {
                "renderedAssetId": None,
                "path": None,
                "sha256": None,
            },
            "audioReceipt": None,
            "technicalQc": {
                "status": "completed"
                if result.get("technicalArtifactStatus") == "completed"
                else "pending"
            },
            "identityComparison": {
                "required": True,
                "approvedAnchorSha256": result.get("anchorSha256"),
                "canonicalCreatorReferences": [
                    {
                        "sourceAssetId": input_payload.get("sourceAssetId"),
                        "sha256": input_payload.get("creatorImageSha256"),
                    }
                ],
                "status": "operator_review_required",
            },
            "providerExecutionStatus": result.get("providerExecutionStatus")
            or job["status"],
            "technicalArtifactStatus": (
                "completed" if result.get("anchorSha256") else "missing"
            ),
        }
    reference = input_payload.get("referenceVideo") or {}
    approval = input_payload.get("recreationAnchorApproval") or {}
    registered = result.get("registeredAsset") or {}
    if registered.get("id"):
        current_asset = factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (registered["id"],)
        ).fetchone()
        if current_asset is not None:
            registered = dict(current_asset)
    metadata = json.loads(str(registered.get("metadata_json") or "{}"))
    worker = result.get("worker") or {}
    paid = worker.get("paidGenerationEvidence") or {}
    provider_receipt = paid.get("providerReceipt") or {}
    receipt = {}
    receipt_path = Path(str(provider_receipt.get("path") or "")).expanduser()
    if receipt_path.is_file() and not receipt_path.is_symlink():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    canonical_sha = str(input_payload.get("sourceSha256") or "")
    anchor_row = factory.conn.execute(
        """
        SELECT source_prompt FROM source_assets
        WHERE content_hash = ? AND media_type = 'image'
        ORDER BY created_at DESC LIMIT 1
        """,
        (approval.get("anchorFileSha256"),),
    ).fetchone()
    anchor_lineage = (
        json.loads(str(anchor_row["source_prompt"] or "{}")) if anchor_row else {}
    )
    rendered_asset_id = registered.get("id")
    qc_row = (
        factory.conn.execute(
            """
            SELECT receipt_json, receipt_sha256 FROM motion_qc_receipts
            WHERE rendered_asset_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (rendered_asset_id,),
        ).fetchone()
        if rendered_asset_id
        else None
    )
    qc_receipt = json.loads(str(qc_row["receipt_json"] or "{}")) if qc_row else None
    technical_qc = (
        {
            "status": qc_receipt.get("status"),
            "receiptSha256": qc_row["receipt_sha256"],
            "receipt": qc_receipt,
        }
        if qc_row and isinstance(qc_receipt, dict)
        else {"status": "pending"}
    )
    return {
        "workItemId": str(input_payload.get("jobId") or ""),
        "reference": {
            "id": reference.get("referenceVideoId"),
            "sha256": (reference.get("originalLocalFile") or {}).get("sha256"),
            "path": (reference.get("originalLocalFile") or {}).get("path"),
        },
        "selectedFrame": {
            "sha256": approval.get("selectedCompositionFrameSha256"),
        },
        "promptPack": {
            "fingerprint": approval.get("promptPackFingerprint"),
            "id": approval.get("anchorPromptPackId"),
            "compiledPrompt": metadata.get("compiledPrompt"),
        },
        "soulGeneration": {
            "id": approval.get("anchorGenerationId"),
            "model": approval.get("anchorModel"),
            "attemptId": anchor_lineage.get("attemptId"),
            "lineagePath": anchor_lineage.get("lineagePath"),
            "campaignSpendReceipt": anchor_lineage.get("campaignSpendReceipt"),
        },
        "anchorApproval": approval,
        "anchor": {
            "path": approval.get("anchorFilePath"),
            "sha256": approval.get("anchorFileSha256"),
        },
        "seedanceRequest": {
            "model": paid.get("providerModel"),
            "authorizationId": paid.get("authorizationId"),
            "reservationId": paid.get("reservationId"),
            "providerPlanFingerprint": paid.get("providerPlanFingerprint"),
            "generationId": paid.get("generationId"),
        },
        "referenceElement": paid.get("referenceElement")
        or receipt.get("referenceElement"),
        "finalVideo": {
            "renderedAssetId": registered.get("id"),
            "path": registered.get("output_path"),
            "sha256": registered.get("content_hash"),
        },
        "audioReceipt": metadata.get("audioEmbeddingReceipt"),
        "technicalQc": technical_qc,
        "identityComparison": {
            "required": True,
            "approvedAnchorSha256": approval.get("anchorFileSha256"),
            "canonicalCreatorReferences": [
                {
                    "sourceAssetId": input_payload.get("sourceAssetId"),
                    "sha256": canonical_sha,
                }
            ],
            "status": "operator_review_required",
        },
        "providerExecutionStatus": str(
            (worker.get("result") or {}).get("status")
            or receipt.get("status")
            or job["status"]
        ),
        "technicalArtifactStatus": "completed"
        if registered.get("content_hash")
        else "missing",
    }


def _final_approval(
    factory: Any, rendered_asset_id: str | None
) -> dict[str, Any] | None:
    if not rendered_asset_id:
        return None
    row = factory.conn.execute(
        """
        SELECT decision, notes, created_at FROM approval_decisions
        WHERE rendered_asset_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (rendered_asset_id,),
    ).fetchone()
    return dict(row) if row else None


def _attempt_id(value: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in value
    )
    if not normalized.strip("_-") or len(normalized) > 100:
        raise ValueError("recreation attempt id must be 1 to 100 safe characters")
    return normalized


def _regular_file(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise PermissionError(f"{label} must not be a symlink")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _required(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
