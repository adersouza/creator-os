from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from .derived_stills import validate_static_source_assets
from .production_batch_results import (
    finalize_production_batch as _finalize_production_batch,
)
from .production_lane import (
    _SUPPORTED_PASSIVE_INTENTS,
    _audio_policy,
    _require_creator_soul_id,
    _sha256_file,
    fulfill_production_audio,
    plan_production_batch,
    run_production_batch,
)
from .static_mp4_stage import run_static_mp4_stage

CREATE_MODES: Final = ("static_reel", "calm_animation", "recreate_reel")
CALM_STYLES: Final = tuple(sorted(_SUPPORTED_PASSIVE_INTENTS))
REUSE_POLICIES: Final = ("prefer_exact", "require_fresh")


def run_creation_batch(
    factory: Any,
    *,
    creator: str,
    mode: str,
    style: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
    apply: bool,
    max_total_credits: float = 100.0,
    max_concurrency: int = 2,
    reference_video_path: Path | None = None,
    reference_platform: str | None = None,
    reference_authorized: bool = False,
    reference_talking: bool = False,
    prompt_pack_provider: Callable[..., dict[str, Any]] | None = None,
    reuse_policy: str = "prefer_exact",
    source_asset_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run one of the three product modes, reusing qualified media first."""

    if mode not in CREATE_MODES:
        raise ValueError(f"unsupported Creator OS mode: {mode}")
    if style not in CALM_STYLES:
        raise ValueError(f"unsupported calm animation style: {style}")
    if reuse_policy not in REUSE_POLICIES:
        raise ValueError(f"unsupported reuse policy: {reuse_policy}")
    if source_asset_ids and mode != "static_reel":
        raise ValueError("--source-asset-id is only valid for static_reel")
    if source_asset_ids:
        validate_static_source_assets(factory, source_asset_ids)
    intent = "recreate_reel" if mode == "recreate_reel" else style
    reference_sha = (
        _sha256_file(reference_video_path.expanduser().resolve())
        if reference_video_path is not None
        else None
    )
    reusable = (
        _qualified_reusable_assets(
            factory,
            creator=creator,
            mode=mode,
            intent=intent,
            count=count,
            audio_policy=_audio_policy(audio_preference),
            reference_sha256=reference_sha,
        )
        if reuse_policy == "prefer_exact" and not source_asset_ids
        else []
    )
    if len(reusable) == count:
        return _reuse_batch(
            creator=creator,
            mode=mode,
            intent=intent,
            assets=reusable,
            apply=apply,
            reuse_policy=reuse_policy,
        )
    if mode == "static_reel":
        result = _run_static_reel_batch(
            factory,
            creator=creator,
            intent=intent,
            count=count,
            execution=execution,
            accounts=accounts,
            audio_preference=audio_preference,
            apply=apply,
            source_asset_ids=source_asset_ids,
        )
    else:
        result = run_production_batch(
            factory,
            creator=creator,
            intent=intent,
            count=count,
            execution=execution,
            accounts=accounts,
            audio_preference=audio_preference,
            apply=apply,
            max_total_credits=max_total_credits,
            max_concurrency=max_concurrency,
            reference_video_path=reference_video_path,
            reference_platform=reference_platform,
            reference_authorized=reference_authorized,
            reference_talking=reference_talking,
            prompt_pack_provider=prompt_pack_provider,
        )
    result["reusePolicy"] = reuse_policy
    return result


def _qualified_reusable_assets(
    factory: Any,
    *,
    creator: str,
    mode: str,
    intent: str,
    count: int,
    audio_policy: str,
    reference_sha256: str | None,
) -> list[dict[str, Any]]:
    creator_slug, _ = _require_creator_soul_id(creator)
    rows = factory.conn.execute(
        """
        SELECT ra.*, c.slug AS campaign_slug
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        JOIN models m ON m.id = sa.model_id
        JOIN campaigns c ON c.id = ra.campaign_id
        WHERE lower(m.slug) = ? AND ra.media_type = 'video'
          AND ra.content_surface = 'reel'
          AND ra.review_state = 'approved'
          AND ra.audit_status IN ('approved_candidate', 'needs_review')
          AND EXISTS (
            SELECT 1
            FROM approval_decisions ad
            WHERE ad.rendered_asset_id = ra.id AND ad.decision = 'approved'
          )
        ORDER BY ra.updated_at DESC, ra.created_at DESC, ra.id
        """,
        (creator_slug,),
    ).fetchall()
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        asset = dict(row)
        try:
            metadata = json.loads(str(asset.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict):
            continue
        if mode == "static_reel":
            if asset.get("recipe") != "static_mp4":
                continue
        elif metadata.get("contentIntent") != intent:
            continue
        if mode == "recreate_reel":
            reference = metadata.get("referenceVideo")
            if (
                not isinstance(reference, dict)
                or _mapping_sha(reference) != reference_sha256
            ):
                continue
        raw_path = Path(str(asset.get("output_path") or "")).expanduser()
        if raw_path.is_symlink():
            continue
        path = raw_path.resolve()
        digest = str(asset.get("content_hash") or "")
        if not digest or digest in seen or not path.is_file():
            continue
        if _sha256_file(path) != digest:
            continue
        if not _exact_final_binding(
            metadata,
            path=path,
            digest=digest,
            audio_policy=audio_policy,
        ):
            continue
        asset["output_path"] = str(path)
        selected.append(asset)
        seen.add(digest)
        if len(selected) == count:
            break
    return selected


def _mapping_sha(reference: Mapping[str, Any]) -> str | None:
    source = reference.get("originalLocalFile") or reference.get("source")
    return str(source.get("sha256") or "") if isinstance(source, Mapping) else None


def _reuse_batch(
    *,
    creator: str,
    mode: str,
    intent: str,
    assets: list[dict[str, Any]],
    apply: bool,
    reuse_policy: str,
) -> dict[str, Any]:
    results = [
        {
            "jobId": f"reuse_{asset['id']}",
            "index": index,
            "status": "reused",
            "renderedAssetId": asset["id"],
            "campaign": asset["campaign_slug"],
            "outputPath": asset["output_path"],
            "outputSha256": asset["content_hash"],
            "providerCalls": 0,
            "route": "exact_final_reuse",
            "reason": "approved_exact_creator_intent_audio_match",
        }
        for index, asset in enumerate(assets)
    ]
    return {
        "schema": "campaign_factory.production_batch.v1",
        "creator": creator.strip().lower().replace(" ", "_"),
        "mode": mode,
        "intent": intent,
        "execution": "library_reuse",
        "reusePolicy": reuse_policy,
        "route": "exact_final_reuse",
        "requested": len(assets),
        "provider": None,
        "providerQuoteStatus": "not_required",
        "quotedProviderCredits": 0,
        "paidGenerationAuthorized": False,
        "apply": apply,
        "results": results,
        "summary": {
            "requested": len(assets),
            "created": 0,
            "reused": len(assets),
            "submitted": 0,
            "completed": len(assets),
            "blocked": 0,
            "failed": 0,
            "scheduled": 0,
            "published": 0,
            "totalProviderCredits": 0,
        },
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


def _exact_final_binding(
    metadata: Mapping[str, Any],
    *,
    path: Path,
    digest: str,
    audio_policy: str,
) -> bool:
    output = metadata.get("output")
    if not isinstance(output, Mapping) or str(output.get("sha256") or "") != digest:
        return False
    output_path = Path(str(output.get("path") or "")).expanduser()
    if output_path.is_symlink() or output_path.resolve() != path:
        return False
    if audio_policy == "silent_allowed":
        return metadata.get("audioBurned") is not True
    receipt = metadata.get("audioEmbeddingReceipt")
    if not isinstance(receipt, Mapping) or metadata.get("audioBurned") is not True:
        return False
    final_video = receipt.get("finalVideo")
    verification = receipt.get("verification")
    return bool(
        isinstance(final_video, Mapping)
        and str(final_video.get("sha256") or "") == digest
        and isinstance(verification, Mapping)
        and verification.get("status") == "verified"
        and verification.get("audioPresent") is True
        and verification.get("audioCodec") == "aac"
    )


def _run_static_reel_batch(
    factory: Any,
    *,
    creator: str,
    intent: str,
    count: int,
    execution: str,
    accounts: str | None,
    audio_preference: str,
    apply: bool,
    source_asset_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    plan = plan_production_batch(
        factory,
        creator=creator,
        intent=intent,
        count=count,
        execution=execution,
        accounts=accounts,
        audio_preference=audio_preference,
        selected_source_asset_ids=source_asset_ids,
    )
    plan.update(
        {
            "mode": "static_reel",
            "provider": None,
            "providerQuoteStatus": "not_required",
            "quotedProviderCredits": 0,
        }
    )
    results: list[dict[str, Any]] = []
    for job in plan["jobs"]:
        if not apply:
            results.append(
                {"jobId": job["jobId"], "index": job["index"], "status": "created"}
            )
            continue
        try:
            stage = run_static_mp4_stage(
                factory,
                campaign_slug=str(job["campaign"]),
                still_path=Path(str(job["sourcePath"])),
                dry_run=False,
                apply=True,
            )
            stage["audioFulfillment"] = fulfill_production_audio(
                factory,
                job=job,
                generation_result=stage,
            )
            results.append(
                {
                    "jobId": job["jobId"],
                    "index": job["index"],
                    "status": "completed",
                    "providerCalls": 0,
                    "result": stage,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "jobId": job["jobId"],
                    "index": job["index"],
                    "status": "failed",
                    "error": str(exc),
                    "providerCalls": 0,
                }
            )
    finalized = _finalize_production_batch(plan, results, apply=apply)
    finalized["mode"] = "static_reel"
    finalized["summary"]["reused"] = sum(
        bool((item.get("result") or {}).get("reused")) for item in results
    )
    finalized["summary"]["totalProviderCredits"] = 0
    return finalized
