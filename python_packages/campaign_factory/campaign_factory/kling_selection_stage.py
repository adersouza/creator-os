from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text

from .core import (
    new_id,
    reel_factory_python,
    sanitize_for_storage,
    sha256_file,
    slugify,
)
from .persistence import utc_now


def run_kling_selection_stage(
    factory: Any,
    *,
    campaign_slug: str,
    rendered_asset_ids: list[str],
    batch_id: str | None = None,
    dry_run: bool = True,
    apply: bool = False,
) -> dict[str, Any]:
    """Rank approved static candidates and issue a fail-closed Kling receipt."""
    unique_ids = list(dict.fromkeys(str(value).strip() for value in rendered_asset_ids))
    if len(unique_ids) < 2 or any(not value for value in unique_ids):
        raise ValueError(
            "best-only Kling selection requires at least two unique assets"
        )
    campaign = factory.campaign_by_slug(campaign_slug)
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    resolved_batch_id = slugify(batch_id or new_id("kling_batch"))
    selection_dir = dirs["root"] / "kling_selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = selection_dir / f"{resolved_batch_id}.candidate_manifest.json"
    ranking_path = selection_dir / f"{resolved_batch_id}.ranking.json"
    receipt_path = selection_dir / f"{resolved_batch_id}.selection_receipt.json"

    candidates = [
        _eligible_candidate(factory, campaign_id=campaign["id"], asset_id=asset_id)
        for asset_id in unique_ids
    ]
    manifest = {
        "schema": "campaign_factory.kling_candidate_manifest.v1",
        "batchId": resolved_batch_id,
        "campaign": campaign_slug,
        "humanApprovalRequired": True,
        "candidates": candidates,
    }
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ranking = _invoke_reel_factory_rank(
        factory,
        manifest_path=manifest_path,
        ranking_path=ranking_path,
    )
    _validate_ranking(ranking, candidates=candidates, batch_id=resolved_batch_id)
    if ranking.get("status") != "selected":
        raise ValueError(f"best-only Kling selection blocked: {ranking.get('status')}")
    selected_id = str(ranking["selectedCandidateId"])
    selected = next(row for row in candidates if row["id"] == selected_id)
    selection_id = new_id("kling_selection")
    receipt = {
        "schema": "campaign_factory.kling_selection_receipt.v1",
        "selectionId": selection_id,
        "campaign": campaign_slug,
        "campaignId": campaign["id"],
        "batchId": resolved_batch_id,
        "selectedRenderedAssetId": selected_id,
        "selectedContentHash": selected["contentHash"],
        "selectedOutputPath": selected["outputPath"],
        "acceptedStillHash": selected["acceptedStillHash"],
        "candidateManifestPath": str(manifest_path),
        "candidateManifestHash": sha256_file(manifest_path),
        "rankingPath": str(ranking_path),
        "rankingHash": sha256_file(ranking_path),
        "ranking": ranking,
        "humanApprovalDecisionId": selected["approvalDecisionId"],
        "humanReviewRequired": True,
        "paidGenerationAuthorized": False,
        "publishingAllowed": False,
        "createdAt": utc_now(),
    }
    registered = False
    if apply and not dry_run:
        atomic_write_text(
            receipt_path,
            json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_hash = sha256_file(receipt_path)
        factory.conn.execute(
            """
            INSERT INTO kling_selection_receipts
            (id, campaign_id, batch_id, selected_rendered_asset_id, receipt_path,
             receipt_hash, ranking_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(campaign_id, batch_id) DO UPDATE SET
              id = excluded.id,
              selected_rendered_asset_id = excluded.selected_rendered_asset_id,
              receipt_path = excluded.receipt_path,
              receipt_hash = excluded.receipt_hash,
              ranking_json = excluded.ranking_json,
              status = 'active',
              created_at = excluded.created_at
            """,
            (
                selection_id,
                campaign["id"],
                resolved_batch_id,
                selected_id,
                str(receipt_path),
                receipt_hash,
                json.dumps(sanitize_for_storage(ranking), sort_keys=True),
                receipt["createdAt"],
            ),
        )
        _attach_receipt_to_asset(factory, selected_id, receipt_path, receipt_hash)
        factory.conn.commit()
        registered = True
    return {
        "schema": "campaign_factory.kling_selection_stage_run.v1",
        "campaign": campaign_slug,
        "batchId": resolved_batch_id,
        "dryRun": dry_run or not apply,
        "apply": bool(apply and not dry_run),
        "selectedRenderedAssetId": selected_id,
        "ranking": ranking,
        "receipt": receipt,
        "receiptPath": str(receipt_path) if registered else None,
        "paidGenerationAuthorized": False,
        "publishingAllowed": False,
    }


def validate_kling_selection_receipt(
    factory: Any,
    *,
    receipt_path: Path,
    accepted_still_path: Path,
    selected_static_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(receipt_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != (
        "campaign_factory.kling_selection_receipt.v1"
    ):
        raise ValueError("Kling selection receipt has the wrong schema")
    row = factory.conn.execute(
        "SELECT * FROM kling_selection_receipts WHERE id = ? AND status = 'active'",
        (payload.get("selectionId"),),
    ).fetchone()
    if not row:
        raise ValueError("Kling selection receipt is not registered and active")
    if sha256_file(path) != row["receipt_hash"]:
        raise ValueError("Kling selection receipt hash does not match the registry")
    for path_key, hash_key, label in (
        ("candidateManifestPath", "candidateManifestHash", "candidate manifest"),
        ("rankingPath", "rankingHash", "ranking result"),
    ):
        evidence_path = Path(str(payload.get(path_key) or "")).expanduser().resolve()
        if not evidence_path.is_file() or sha256_file(evidence_path) != payload.get(
            hash_key
        ):
            raise ValueError(f"Kling selection {label} evidence changed")
    if str(payload.get("selectedRenderedAssetId")) != row["selected_rendered_asset_id"]:
        raise ValueError(
            "Kling selection receipt selected asset does not match registry"
        )
    ranking = payload.get("ranking")
    if (
        not isinstance(ranking, dict)
        or ranking.get("status") != "selected"
        or ranking.get("selectedCandidateId") != payload.get("selectedRenderedAssetId")
    ):
        raise ValueError("Kling selection receipt does not contain a valid winner")
    if sha256_file(Path(accepted_still_path)) != payload.get("acceptedStillHash"):
        raise ValueError("accepted still does not match the best-only Kling receipt")
    if selected_static_asset is not None:
        if selected_static_asset.get("id") != payload.get("selectedRenderedAssetId"):
            raise ValueError("static fallback is not the selected Kling candidate")
        if selected_static_asset.get("content_hash") != payload.get(
            "selectedContentHash"
        ):
            raise ValueError("selected static fallback hash changed after ranking")
    _eligible_candidate(
        factory,
        campaign_id=row["campaign_id"],
        asset_id=row["selected_rendered_asset_id"],
    )
    return payload


def _eligible_candidate(
    factory: Any, *, campaign_id: str, asset_id: str
) -> dict[str, Any]:
    row = factory.conn.execute(
        "SELECT * FROM rendered_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    if not row or row["campaign_id"] != campaign_id:
        raise ValueError(f"Kling candidate is not in the campaign: {asset_id}")
    asset = dict(row)
    if asset.get("recipe") != "static_mp4":
        raise ValueError(f"Kling candidate must be a static_mp4 asset: {asset_id}")
    if asset.get("review_state") != "approved":
        raise ValueError(f"Kling candidate lacks human approval: {asset_id}")
    if asset.get("audit_status") != "approved_candidate":
        raise ValueError(f"Kling candidate lacks a safe audit: {asset_id}")
    approval = factory.conn.execute(
        """
        SELECT * FROM approval_decisions WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (asset_id,),
    ).fetchone()
    if not approval or approval["decision"] != "approved":
        raise ValueError(f"Kling candidate approval evidence is missing: {asset_id}")
    audit = factory.conn.execute(
        """
        SELECT * FROM audit_reports WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (asset_id,),
    ).fetchone()
    if (
        not audit
        or audit["status"] != "approved_candidate"
        or audit["overall_verdict"] not in {"pass", "warn"}
        or _json_list(audit["failed_checks_json"])
    ):
        raise ValueError(f"Kling candidate audit evidence is unsafe: {asset_id}")
    output = Path(asset["output_path"])
    if not output.is_file() or sha256_file(output) != asset["content_hash"]:
        raise ValueError(f"Kling candidate content hash is stale: {asset_id}")
    metadata = _json_object(asset.get("metadata_json"))
    lineage = metadata.get("generatedAssetLineage")
    if not isinstance(lineage, dict):
        caption_generation = _json_object(asset.get("caption_generation_json"))
        lineage = caption_generation.get("generatedAssetLineage")
    if not isinstance(lineage, dict):
        raise ValueError(f"Kling candidate is missing generated lineage: {asset_id}")
    source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    accepted_still_hash = str(source.get("parentStillHash") or "")
    if not accepted_still_hash:
        raise ValueError(f"Kling candidate is missing accepted still hash: {asset_id}")
    candidate = {
        "id": asset_id,
        "contentHash": asset["content_hash"],
        "outputPath": asset["output_path"],
        "acceptedStillHash": accepted_still_hash,
        "approvalDecisionId": approval["id"],
        "auditReportId": audit["id"],
        "generatedAssetLineage": lineage,
    }
    prediction = metadata.get("viralityPrediction")
    if isinstance(prediction, dict) and prediction.get("score") is not None:
        candidate["virality"] = float(prediction["score"])
    return candidate


def _invoke_reel_factory_rank(
    factory: Any, *, manifest_path: Path, ranking_path: Path
) -> dict[str, Any]:
    command = [
        reel_factory_python(factory.settings.reel_factory_root),
        "virality_select.py",
        "--rank-kling-candidates",
        str(manifest_path),
        "--root",
        str(factory.settings.reel_factory_root),
        "--out",
        str(ranking_path),
    ]
    proc = subprocess.run(
        command,
        cwd=factory.settings.reel_factory_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr[-2000:] or proc.stdout[-2000:] or "ranking failed"
        )
    payload = json.loads(proc.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("Reel Factory Kling ranking returned non-object JSON")
    return payload


def _validate_ranking(
    ranking: dict[str, Any], *, candidates: list[dict[str, Any]], batch_id: str
) -> None:
    if ranking.get("schema") != "reel_factory.kling_candidate_ranking.v1":
        raise ValueError("Kling ranking has the wrong schema")
    if ranking.get("batchId") != batch_id:
        raise ValueError("Kling ranking batch does not match")
    ranked = ranking.get("candidates")
    if not isinstance(ranked, list) or len(ranked) != len(candidates):
        raise ValueError("Kling ranking candidate set is incomplete")
    expected = {row["id"] for row in candidates}
    actual = {str(row.get("id")) for row in ranked if isinstance(row, dict)}
    if actual != expected:
        raise ValueError("Kling ranking candidate ids do not match")


def _attach_receipt_to_asset(
    factory: Any, asset_id: str, receipt_path: Path, receipt_hash: str
) -> None:
    row = factory.conn.execute(
        "SELECT metadata_json FROM rendered_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    metadata = _json_object(row["metadata_json"] if row else None)
    metadata["klingSelection"] = {
        "receiptPath": str(receipt_path),
        "receiptHash": receipt_hash,
        "selected": True,
        "paidGenerationAuthorized": False,
    }
    factory.conn.execute(
        "UPDATE rendered_assets SET metadata_json = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(
                sanitize_for_storage(metadata), ensure_ascii=False, sort_keys=True
            ),
            utc_now(),
            asset_id,
        ),
    )


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
        return value if isinstance(value, list) else [value]
    return []
