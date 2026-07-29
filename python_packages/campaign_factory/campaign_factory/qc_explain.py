from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .asset_evidence import verify_registered_asset_bytes
from .persistence import json_load


def explain_asset_qc(factory: Any, rendered_asset_id: str) -> dict[str, Any]:
    asset = factory.domains.publishability.rendered_asset(rendered_asset_id)
    current_sha = str(asset.get("content_hash") or "")
    latest = factory.domains.publishability.latest_audit_for_asset(rendered_asset_id)
    audits = [
        dict(row)
        for row in factory.conn.execute(
            """
            SELECT id, subject_sha256, status, overall_verdict, report_path, created_at
            FROM audit_reports WHERE rendered_asset_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (rendered_asset_id,),
        ).fetchall()
    ]
    context = json_load(asset.get("caption_outcome_context_json"), {})
    generation = json_load(asset.get("caption_generation_json"), {})
    approval = factory.domains.publishability.creative_approval_for_asset(
        rendered_asset_id
    )
    approval_payload = approval.get("approval")
    operator_review = None
    if isinstance(approval_payload, dict):
        binding = approval_payload.get("operatorReview")
        if isinstance(binding, dict):
            path = Path(str(binding.get("path") or ""))
            if path.is_file() and not path.is_symlink():
                operator_review = json.loads(path.read_text(encoding="utf-8"))
    readiness = factory.domains.publishability.publishability_check(asset, latest)
    blocking_codes = list(readiness.get("failures") or [])
    return {
        "schema": "campaign_factory.qc_explanation.v1",
        "renderedAssetId": rendered_asset_id,
        "currentFileShaVerification": verify_registered_asset_bytes(asset),
        "generatedVisualQc": factory.domains.publishability.motion_qc_gate(asset),
        "captionPlacementDecision": context.get("captionPlacementDecision"),
        "overlayQc": {
            "semantic": context.get("overlaySemanticQc")
            or context.get("overlay_semantic_qc"),
            "timing": context.get("captionTimingQc")
            or context.get("caption_timing_qc"),
            "burnedIn": context.get("captionBurnedIn") is True,
            "fallback": context.get("captionFallback"),
        },
        "audioReceipt": generation.get("audioIntent"),
        "finalArtifactIntegrity": readiness.get("finalArtifactIntegrity"),
        "contentForgeAudit": latest,
        "contentForgeSubjectMatchesCurrentSha": bool(
            latest and latest.get("subjectSha256") == current_sha
        ),
        "campaignReadiness": {
            "state": readiness.get("assetState"),
            "checks": readiness.get("checks"),
            "failures": blocking_codes,
            "warnings": readiness.get("warnings"),
        },
        "operatorReviewVerdict": operator_review,
        "creativeApprovalV2": {
            key: value for key, value in approval.items() if key != "approval"
        },
        "supersededEvidence": [
            audit for audit in audits if audit.get("subject_sha256") != current_sha
        ],
        "currentBlockingCodes": blocking_codes,
    }
