from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.threadsdash import (
    SupabaseRestClient,
    evaluate_export_readiness,
    export_threadsdash,
    sync_performance_snapshots,
    verify_threadsdash_export,
)
from .config import get_settings
from .core import CampaignFactory


DEFAULT_STACEY_PROMPT_PATH = Path(
    "/Users/adercialonedesouza/Projects/reel_factory/prompts/stacey_examples_notsasha_pink_4x2_16x9.json"
)

CREATOR_USERNAME_TOKENS = {
    "stacey": ("stacey", "stacy", "bennett", "sbennett"),
    "larissa": ("larissa", "larrisa", "lari", "almas"),
    "lola": ("lola", "nova"),
}

CONTEXT_KEYS = (
    "caption_hash",
    "caption_text",
    "caption_bank",
    "caption_banks",
    "creator_mix",
    "creator_model",
    "frame_type",
    "length_class",
    "format_class",
    "caption_fit_version",
    "render_recipe",
    "source_clip",
    "rendered_output",
    "suitability_decision",
    "suitability_reason",
    "captionSceneTags",
    "reelSceneTags",
    "sceneCompatibilityDecision",
    "sceneCompatibilityReason",
    "captionSceneFitVersion",
)

TRANSPORT_ONLY_CONTEXT_KEYS = {
    "render_recipe",
}

STOP_CONDITIONS = (
    "missing_threadsdash_user_id",
    "missing_supabase_credentials",
    "no_active_stacey_instagram_account",
    "missing_stacey_prompt",
    "no_rendered_output_approved",
    "promotion_preview_blocked",
    "export_readiness_not_ready",
    "threadsdash_export_verification_failed",
    "metrics_reconciliation_failed",
    "caption_outcome_context_fingerprint_mismatch",
    "content_fingerprint_mismatch",
    "caption_hash_mismatch",
)

GATE_REASONS = (
    "ready_for_live_export",
    "awaiting_post_or_metrics",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_caption_context_for_fingerprint(context: dict[str, Any] | None) -> dict[str, Any]:
    source = context if isinstance(context, dict) else {}
    return {
        key: source.get(key)
        for key in CONTEXT_KEYS
        if key not in TRANSPORT_ONLY_CONTEXT_KEYS
    }


def context_fingerprint(context: dict[str, Any] | None) -> str:
    return fingerprint_payload(canonical_caption_context_for_fingerprint(context))


def file_fingerprint(path: str | Path | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_stacey_instagram_account(client: Any, *, user_id: str) -> dict[str, Any] | None:
    discovery = discover_stacey_account_context(client, user_id=user_id)
    return discovery.get("selectedAccount")


def discover_stacey_account_context(client: Any, *, user_id: str) -> dict[str, Any]:
    return discover_creator_account_context(client, user_id=user_id, creator="Stacey")


def discover_creator_account_context(client: Any, *, user_id: str, creator: str) -> dict[str, Any]:
    groups = client.select(
        "account_groups",
        {
            "select": "id,name,account_ids,user_id",
            "user_id": f"eq.{user_id}",
        },
    )
    creator_key = str(creator or "").strip().lower()
    creator_groups = [
        group for group in groups
        if creator_key in str(group.get("name") or "").lower()
    ]
    if not creator_groups:
        return {
            "status": "blocked",
            "blockingReasons": ["no_creator_account_group"],
            "creator": creator,
            "creatorGroups": [],
            "staceyGroups": [],
            "selectedAccount": None,
            "activeInstagramCandidateCount": 0,
            "creatorLikeUngroupedInstagramAccounts": [],
            "staceyLikeActiveInstagramAccounts": [],
            "bridgedInstagramAccounts": [],
            "recommendations": _routing_recommendations(creator, has_bridge=False, has_ungrouped=False),
        }

    creator_group_ids = {str(group.get("id")) for group in creator_groups if group.get("id")}
    creator_account_ids: set[str] = set()
    group_by_id = {str(group.get("id")): group for group in creator_groups if group.get("id")}
    for group in creator_groups:
        account_ids = group.get("account_ids") or group.get("accountIds") or []
        if isinstance(account_ids, str):
            try:
                account_ids = json.loads(account_ids)
            except json.JSONDecodeError:
                account_ids = [account_ids]
        if isinstance(account_ids, list):
            creator_account_ids.update(str(account_id) for account_id in account_ids if account_id)

    thread_accounts = client.select(
        "accounts",
        {
            "select": "id,username,status,is_active,group_id,user_id",
            "user_id": f"eq.{user_id}",
        },
    )
    bridged_account_ids = {
        str(account.get("id"))
        for account in thread_accounts
        if _active_instagram_account(account)
        and (
            str(account.get("id") or "") in creator_account_ids
            or str(account.get("group_id") or "") in creator_group_ids
        )
    }
    thread_account_by_id = {
        str(account.get("id")): account
        for account in thread_accounts
        if str(account.get("id") or "") in bridged_account_ids
    }
    thread_account_by_username = {
        str(account.get("username") or "").strip().lower(): account
        for account in thread_account_by_id.values()
        if account.get("username")
    }

    accounts = client.select(
        "instagram_accounts",
        {
            "select": "*",
            "user_id": f"eq.{user_id}",
        },
    )
    direct_candidates = []
    bridged_candidates = []
    creator_like_active_accounts = []
    ambiguous_bridge_ids: set[str] = set()
    bridge_counts: dict[str, int] = {}
    username_bridge_counts: dict[str, int] = {}
    for account in accounts:
        if not _active_instagram_account(account):
            continue
        username = str(account.get("username") or account.get("handle") or account.get("id") or "")
        if any(token in username.lower() for token in _creator_tokens(creator)):
            creator_like_active_accounts.append({
                "instagramAccountId": account.get("id"),
                "username": username,
                "groupId": account.get("group_id"),
            })
        group_id = str(account.get("group_id") or "")
        account_id = str(account.get("id") or "")
        if group_id in creator_group_ids:
            group = group_by_id.get(group_id) or creator_groups[0]
            direct_candidates.append(_account_resolution_payload(
                account,
                group=group,
                username=username,
                resolution_path="instagram_accounts.group_id",
            ))
            continue
        linked_account_id = _linked_account_id(account)
        if linked_account_id and linked_account_id in bridged_account_ids:
            bridge_counts[linked_account_id] = bridge_counts.get(linked_account_id, 0) + 1
            group = _group_for_linked_account(thread_accounts, linked_account_id, group_by_id) or creator_groups[0]
            bridged_candidates.append(_account_resolution_payload(
                account,
                group=group,
                username=username,
                resolution_path="account_groups.account_ids->accounts->instagram_accounts",
                linked_account_id=linked_account_id,
            ))
            continue
        thread_account = thread_account_by_username.get(username.strip().lower())
        if thread_account:
            thread_account_id = str(thread_account.get("id") or "")
            username_bridge_counts[thread_account_id] = username_bridge_counts.get(thread_account_id, 0) + 1
            group = _group_for_linked_account(thread_accounts, thread_account_id, group_by_id) or creator_groups[0]
            bridged_candidates.append(_account_resolution_payload(
                account,
                group=group,
                username=username,
                resolution_path="account_groups.account_ids->accounts.username->instagram_accounts.username",
                linked_account_id=thread_account_id,
            ))

    ambiguous_bridge_ids = (
        {linked_id for linked_id, count in bridge_counts.items() if count > 1}
        | {linked_id for linked_id, count in username_bridge_counts.items() if count > 1}
    )
    if ambiguous_bridge_ids:
        bridged_candidates = [
            candidate for candidate in bridged_candidates
            if candidate.get("linkedAccountId") not in ambiguous_bridge_ids
        ]
    candidates = direct_candidates + bridged_candidates
    selected = sorted(candidates, key=lambda item: (str(item.get("username") or ""), str(item.get("instagramAccountId") or "")))[0] if candidates else None
    blocking_reasons = []
    if ambiguous_bridge_ids:
        blocking_reasons.append("ambiguous_bridge")
    if not selected and not blocking_reasons:
        blocking_reasons.append("no_active_creator_instagram_account")
    status = "ready" if selected and not blocking_reasons else ("ambiguous" if ambiguous_bridge_ids else "blocked")
    groups_payload = [
        {
            "id": group.get("id"),
            "name": group.get("name"),
            "accountIds": group.get("account_ids") or group.get("accountIds") or [],
        }
        for group in creator_groups
    ]
    ungrouped = [
        account for account in creator_like_active_accounts
        if not account.get("groupId")
    ]
    return {
        "status": status,
        "blockingReasons": blocking_reasons,
        "creator": creator,
        "creatorGroups": groups_payload,
        "staceyGroups": groups_payload if creator_key == "stacey" else [],
        "selectedAccount": selected,
        "directInstagramAccounts": direct_candidates,
        "bridgedInstagramAccounts": sorted(
            bridged_candidates,
            key=lambda item: (str(item.get("username") or ""), str(item.get("instagramAccountId") or "")),
        ),
        "bridgeAccountIds": sorted(bridged_account_ids),
        "ambiguousBridgeAccountIds": sorted(ambiguous_bridge_ids),
        "activeInstagramCandidateCount": len([account for account in accounts if _active_instagram_account(account)]),
        "creatorLikeUngroupedInstagramAccounts": sorted(
            ungrouped,
            key=lambda item: (str(item.get("username") or ""), str(item.get("instagramAccountId") or "")),
        )[:20],
        "staceyLikeActiveInstagramAccounts": sorted(
            ungrouped,
            key=lambda item: (str(item.get("username") or ""), str(item.get("instagramAccountId") or "")),
        )[:20] if creator_key == "stacey" else [],
        "recommendations": _routing_recommendations(
            creator,
            has_bridge=bool(bridged_account_ids),
            has_ungrouped=bool(ungrouped),
            ambiguous=bool(ambiguous_bridge_ids),
        ),
    }


def build_account_routing_audit(client: Any, *, user_id: str, creator: str) -> dict[str, Any]:
    discovery = discover_creator_account_context(client, user_id=user_id, creator=creator)
    return {
        "schema": "campaign_factory.account_routing_audit.v1",
        "mode": "preview",
        "mutatesSupabase": False,
        "creator": creator,
        "userId": user_id,
        "status": discovery.get("status"),
        "blockingReasons": discovery.get("blockingReasons") or [],
        "groups": discovery.get("creatorGroups") or [],
        "selectedAccount": discovery.get("selectedAccount"),
        "directInstagramAccounts": discovery.get("directInstagramAccounts") or [],
        "bridgedInstagramAccounts": discovery.get("bridgedInstagramAccounts") or [],
        "creatorLikeUngroupedInstagramAccounts": discovery.get("creatorLikeUngroupedInstagramAccounts") or [],
        "activeInstagramCandidateCount": discovery.get("activeInstagramCandidateCount") or 0,
        "recommendations": discovery.get("recommendations") or [],
        "rawDiscovery": discovery,
    }


def _creator_tokens(creator: str) -> tuple[str, ...]:
    key = str(creator or "").strip().lower()
    return CREATOR_USERNAME_TOKENS.get(key, (key,)) if key else ()


def _linked_account_id(account: dict[str, Any]) -> str | None:
    for key in ("linked_account_id", "account_id", "threads_account_id", "threads_user_id"):
        value = account.get(key)
        if value:
            return str(value)
    return None


def _group_for_linked_account(accounts: list[dict[str, Any]], linked_account_id: str, group_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for account in accounts:
        if str(account.get("id") or "") == linked_account_id:
            return group_by_id.get(str(account.get("group_id") or ""))
    return None


def _account_resolution_payload(
    account: dict[str, Any],
    *,
    group: dict[str, Any],
    username: str,
    resolution_path: str,
    linked_account_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "instagramAccountId": str(account.get("id") or ""),
        "username": username,
        "groupId": group.get("id"),
        "groupName": group.get("name"),
        "resolutionPath": resolution_path,
        "raw": _safe_account_summary(account),
    }
    if linked_account_id:
        payload["linkedAccountId"] = linked_account_id
    return payload


def _safe_account_summary(account: dict[str, Any]) -> dict[str, Any]:
    safe_keys = (
        "id",
        "username",
        "display_name",
        "status",
        "is_active",
        "group_id",
        "user_id",
        "account_type",
        "login_type",
        "needs_reauth",
        "last_synced_at",
        "created_at",
        "updated_at",
    )
    return {key: account.get(key) for key in safe_keys if key in account}


def _routing_recommendations(
    creator: str,
    *,
    has_bridge: bool,
    has_ungrouped: bool,
    ambiguous: bool = False,
) -> list[str]:
    recommendations = [
        f"attach instagram_accounts to the {creator} group by setting instagram_accounts.group_id to the matching account_groups.id",
    ]
    if has_bridge:
        recommendations.append(
            "or keep the current schema and let closed-loop-proof bridge account_groups.account_ids -> accounts -> instagram_accounts when the bridge is one-to-one"
        )
    else:
        recommendations.append(
            "or add an explicit one-to-one bridge from accounts rows in account_groups.account_ids to their instagram_accounts rows"
        )
    if has_ungrouped:
        recommendations.append(
            f"review active {creator}-like instagram_accounts with group_id null before live scheduling"
        )
    if ambiguous:
        recommendations.append(
            "resolve ambiguous bridge rows before selecting an account; the resolver will not pick among multiple instagram_accounts for one accounts row"
        )
    return recommendations


def _active_instagram_account(account: dict[str, Any]) -> bool:
    if account.get("is_active") is False:
        return False
    status = str(account.get("status") or "active").strip().lower()
    return status not in {"disabled", "inactive", "disconnected", "reauth_required", "error", "blocked"}


class ClosedLoopProofRun:
    def __init__(
        self,
        *,
        campaign_slug: str,
        output_dir: str | Path,
        operator: str | None = None,
        prompt_path: str | Path = DEFAULT_STACEY_PROMPT_PATH,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.record: dict[str, Any] = {
            "schema": "campaign_factory.closed_loop_proof.v1",
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
            "result": "pending",
            "stopReason": None,
            "campaign": {
                "slug": campaign_slug,
                "id": None,
            },
            "targetCreator": "Stacey",
            "primaryKpi": "views",
            "promptPath": str(prompt_path),
            "selectedAccount": None,
            "renderedAssetId": None,
            "distributionPlanId": None,
            "threadsDashboardPostId": None,
            "performanceSnapshotId": None,
            "renderedOutputPath": None,
            "contentFingerprint": None,
            "captionHash": None,
            "captionOutcomeContextFingerprint": None,
            "lineageFingerprintByStage": {},
            "views": None,
            "generationCosts": {
                "higgsfieldImageCost": None,
                "klingCost": None,
                "totalGenerationCost": None,
            },
            "renderCount": None,
            "finalApprovedCount": None,
            "costPerApprovedReel": None,
            "humanReviewReceipt": None,
            "reports": {},
            "stopConditions": list(STOP_CONDITIONS),
            "details": {},
        }

    @property
    def json_path(self) -> Path:
        return self.output_dir / "CLOSED_LOOP_PROOF.json"

    @property
    def markdown_path(self) -> Path:
        return self.output_dir / "CLOSED_LOOP_PROOF.md"

    def update(self, **values: Any) -> None:
        for key, value in values.items():
            if key == "campaign_id":
                self.record["campaign"]["id"] = value
            elif key == "details" and isinstance(value, dict):
                self.record["details"].update(value)
            else:
                self.record[key] = value
        self.record["updatedAt"] = utc_now()

    def stop(self, reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        self.record["result"] = "failed"
        self.record["stopReason"] = reason
        if details:
            self.record["details"].update(details)
        self.record["updatedAt"] = utc_now()
        self.write()
        return self.record

    def gate(self, reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        self.record["result"] = "pending"
        self.record["stopReason"] = reason
        if details:
            self.record["details"].update(details)
        self.record["updatedAt"] = utc_now()
        self.write()
        return self.record

    def complete(self, details: dict[str, Any] | None = None) -> dict[str, Any]:
        self.record["result"] = "passed"
        self.record["stopReason"] = None
        if details:
            self.record["details"].update(details)
        self.record["updatedAt"] = utc_now()
        self.write()
        return self.record

    def write(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(json.dumps(self.record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        self.markdown_path.write_text(self._markdown(), encoding="utf-8")

    def _markdown(self) -> str:
        record = self.record
        account = record.get("selectedAccount") or {}
        costs = record.get("generationCosts") or {}
        lines = [
            "# Stacey Closed-Loop Proof",
            "",
            f"- Result: `{record.get('result')}`",
            f"- Stop reason: `{record.get('stopReason')}`",
            f"- Campaign: `{(record.get('campaign') or {}).get('slug')}`",
            f"- Account: `{account.get('username') or 'pending'}` (`{account.get('instagramAccountId') or 'pending'}`)",
            f"- Rendered asset: `{record.get('renderedAssetId') or 'pending'}`",
            f"- Distribution plan: `{record.get('distributionPlanId') or 'pending'}`",
            f"- ThreadsDashboard post: `{record.get('threadsDashboardPostId') or 'pending'}`",
            f"- Performance snapshot: `{record.get('performanceSnapshotId') or 'pending'}`",
            f"- Views: `{record.get('views')}`",
            "",
            "## Fingerprints",
            "",
            f"- Content fingerprint: `{record.get('contentFingerprint') or 'pending'}`",
            f"- Caption hash: `{record.get('captionHash') or 'pending'}`",
            f"- captionOutcomeContext fingerprint: `{record.get('captionOutcomeContextFingerprint') or 'pending'}`",
            "",
            "## Costs",
            "",
            f"- Higgsfield image cost: `{costs.get('higgsfieldImageCost')}`",
            f"- Kling cost: `{costs.get('klingCost')}`",
            f"- Total generation cost: `{costs.get('totalGenerationCost')}`",
            f"- Render count: `{record.get('renderCount')}`",
            f"- Final approved count: `{record.get('finalApprovedCount')}`",
            f"- Cost per approved reel: `{record.get('costPerApprovedReel')}`",
            "",
            "## Human Review",
            "",
            "```json",
            json.dumps(record.get("humanReviewReceipt"), indent=2, ensure_ascii=False, sort_keys=True),
            "```",
            "",
            "## Lineage By Stage",
            "",
            "```json",
            json.dumps(record.get("lineageFingerprintByStage") or {}, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
            "",
            "## Details",
            "",
            "```json",
            json.dumps(record.get("details") or {}, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
            "",
        ]
        return "\n".join(lines)


def build_stage_fingerprint(
    *,
    rendered_asset_id: str | None,
    content_fingerprint: str | None,
    caption_hash: str | None,
    caption_context_fingerprint: str | None,
    extra: dict[str, Any] | None = None,
) -> str:
    return fingerprint_payload({
        "renderedAssetId": rendered_asset_id,
        "contentFingerprint": content_fingerprint,
        "captionHash": caption_hash,
        "captionOutcomeContextFingerprint": caption_context_fingerprint,
        "extra": extra or {},
    })


def run_stacey_closed_loop_proof(
    *,
    campaign_slug: str,
    user_id: str | None,
    output_dir: str | Path,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_storage_bucket: str = "media",
    operator: str | None = None,
    approval_reason: str | None = None,
    approved_rendered_asset_id: str | None = None,
    prompt_path: str | Path = DEFAULT_STACEY_PROMPT_PATH,
    schedule_mode: str = "live",
    allow_warnings: bool = False,
    allow_live_export: bool = False,
    read_only_verification: bool = False,
    existing_threadsdash_post_id: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    run = ClosedLoopProofRun(
        campaign_slug=campaign_slug,
        output_dir=output_dir,
        operator=operator,
        prompt_path=prompt_path,
    )
    settings = get_settings()
    factory = CampaignFactory(settings)
    try:
        campaign = factory.campaign_by_slug(campaign_slug)
        run.update(campaign_id=campaign["id"])
    except Exception as exc:
        return run.stop("campaign_not_found", {"error": str(exc)})

    if not user_id:
        return run.stop("missing_threadsdash_user_id", {"env": "THREADSDASH_USER_ID"})
    if not supabase_url or not supabase_service_role_key:
        return run.stop("missing_supabase_credentials", {
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
        })

    client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
    account_discovery = discover_stacey_account_context(client, user_id=user_id)
    selected_account = account_discovery.get("selectedAccount")
    if not selected_account:
        return run.stop("no_active_stacey_instagram_account", {"userId": user_id, "accountDiscovery": account_discovery})
    run.update(selectedAccount=selected_account)

    if not Path(prompt_path).exists():
        return run.stop("missing_stacey_prompt", {"promptPath": str(prompt_path)})

    if not approved_rendered_asset_id:
        return run.stop("no_rendered_output_approved", {
            "expectedPromptPath": str(prompt_path),
            "expectedCaptionMix": "Stacey",
            "expectedCaptionFit": "auto",
            "operator": operator or os.environ.get("USER"),
            "note": "Generate the Stacey reel and pass --approved-rendered-asset-id after human review.",
        })

    asset = _export_manifest_asset(factory, campaign_slug, approved_rendered_asset_id)
    if not asset:
        return run.stop("no_rendered_output_approved", {"renderedAssetId": approved_rendered_asset_id})

    caption_context = asset.get("captionOutcomeContext") if isinstance(asset.get("captionOutcomeContext"), dict) else {}
    caption_context_fp = context_fingerprint(caption_context)
    rendered_output_path = asset.get("filePath")
    content_fp = file_fingerprint(rendered_output_path) or asset.get("contentHash")
    caption_hash = asset.get("captionHash") or caption_context.get("caption_hash")
    human_review = {
        "operator": operator or os.environ.get("USER"),
        "timestamp": utc_now(),
        "approvedOutputPath": rendered_output_path,
        "approvalReason": approval_reason or "manual_closed_loop_stage_1_proof",
    }
    run.update(
        renderedAssetId=approved_rendered_asset_id,
        renderedOutputPath=rendered_output_path,
        contentFingerprint=content_fp,
        captionHash=caption_hash,
        captionOutcomeContextFingerprint=caption_context_fp,
        humanReviewReceipt=human_review,
        finalApprovedCount=1,
    )
    run.record["lineageFingerprintByStage"]["rendered output"] = build_stage_fingerprint(
        rendered_asset_id=approved_rendered_asset_id,
        content_fingerprint=content_fp,
        caption_hash=caption_hash,
        caption_context_fingerprint=caption_context_fp,
    )

    plans = [
        plan for plan in factory.distribution_plans_for_asset(approved_rendered_asset_id)
        if plan.get("instagramAccountId") == selected_account["instagramAccountId"]
    ]
    if not plans:
        return run.stop("promotion_preview_blocked", {
            "reason": "selected_stacey_account_missing_from_distribution_plan",
            "selectedInstagramAccountId": selected_account["instagramAccountId"],
            "renderedAssetId": approved_rendered_asset_id,
        })
    plan = sorted(plans, key=lambda item: str(item.get("id") or ""))[0]
    run.update(distributionPlanId=plan.get("id"))
    run.record["lineageFingerprintByStage"]["distribution_plans"] = build_stage_fingerprint(
        rendered_asset_id=approved_rendered_asset_id,
        content_fingerprint=content_fp,
        caption_hash=caption_hash,
        caption_context_fingerprint=caption_context_fp,
        extra={"distributionPlanId": plan.get("id"), "instagramAccountId": plan.get("instagramAccountId")},
    )

    if read_only_verification:
        if not existing_threadsdash_post_id:
            return run.stop("threadsdash_export_verification_failed", {
                "blockingReasons": ["read_only_verification_requires_existing_threadsdash_post_id"],
            })
        existing_rows = client.select("posts", {
            "select": "id,status,scheduled_for,published_at,created_at,updated_at,platform,instagram_account_id,account_id,user_id,metadata",
            "id": f"eq.{existing_threadsdash_post_id}",
        })
        run.record["reports"]["threadsDashboardVerification"] = {
            "ok": bool(existing_rows),
            "mode": "read_only_existing_post",
            "postId": existing_threadsdash_post_id,
            "rowCount": len(existing_rows),
            "status": existing_rows[0].get("status") if existing_rows else None,
        }
        if not existing_rows:
            return run.stop("threadsdash_export_verification_failed", {
                "blockingReasons": ["existing_threadsdash_post_not_found"],
                "postId": existing_threadsdash_post_id,
            })
    else:
        readiness = evaluate_export_readiness(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            limit=limit,
            rendered_asset_ids=[approved_rendered_asset_id],
            schedule_mode=schedule_mode,
        )
        run.record["reports"]["exportReadiness"] = readiness
        if not readiness.get("liveExportAllowed"):
            return run.stop("export_readiness_not_ready", {
                "blockingReasons": readiness.get("blockingReasons") or [],
                "warnings": readiness.get("warnings") or [],
            })
        if not allow_live_export:
            return run.gate("ready_for_live_export", {
                "renderedAssetId": approved_rendered_asset_id,
                "distributionPlanId": plan.get("id"),
                "selectedInstagramAccountId": selected_account["instagramAccountId"],
                "scheduleMode": schedule_mode,
                "liveThreadsDashboardExportRan": False,
                "note": "Export readiness passed. Live ThreadsDashboard export was not run; rerun with --allow-live-export after explicit approval.",
            })

        export_result = export_threadsdash(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            dry_run=False,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_storage_bucket=supabase_storage_bucket,
            allow_warnings=allow_warnings,
            rendered_asset_ids=[approved_rendered_asset_id],
            schedule_mode=schedule_mode,
        )
        run.record["reports"]["threadsDashboardExport"] = export_result
        export_path = export_result.get("exportPath")
        if export_path:
            verify_result = verify_threadsdash_export(
                Path(export_path),
                supabase_url=supabase_url,
                supabase_service_role_key=supabase_service_role_key,
            )
            run.record["reports"]["threadsDashboardVerification"] = verify_result
            if not verify_result.get("ok"):
                return run.stop("threadsdash_export_verification_failed", {
                    "blockingReasons": verify_result.get("blockingReasons") or [],
                })

    sync_result = sync_performance_snapshots(
        factory,
        campaign_slug=campaign_slug,
        user_id=user_id,
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        limit=limit,
    )
    run.record["reports"]["performanceSync"] = sync_result
    snapshot = (
        _performance_snapshot_for_post(factory, approved_rendered_asset_id, existing_threadsdash_post_id)
        if existing_threadsdash_post_id else _latest_performance_snapshot(factory, approved_rendered_asset_id)
    )
    if not snapshot:
        return run.stop("metrics_reconciliation_failed", {
            "renderedAssetId": approved_rendered_asset_id,
            "syncResult": sync_result,
        })
    run.update(
        performanceSnapshotId=snapshot.get("id"),
        threadsDashboardPostId=snapshot.get("post_id"),
        views=snapshot.get("views"),
    )
    snapshot_context_fp = context_fingerprint(_loads(snapshot.get("caption_outcome_context_json"), {}))
    if snapshot_context_fp != caption_context_fp:
        return run.stop("caption_outcome_context_fingerprint_mismatch", {
            "expected": caption_context_fp,
            "actual": snapshot_context_fp,
        })
    if snapshot.get("content_hash") and content_fp and snapshot.get("content_hash") != asset.get("contentHash"):
        return run.stop("content_fingerprint_mismatch", {
            "expected": asset.get("contentHash"),
            "actual": snapshot.get("content_hash"),
        })
    if snapshot.get("caption_hash") and caption_hash and snapshot.get("caption_hash") != caption_hash:
        return run.stop("caption_hash_mismatch", {
            "expected": caption_hash,
            "actual": snapshot.get("caption_hash"),
        })

    run.record["lineageFingerprintByStage"]["performance_snapshots"] = build_stage_fingerprint(
        rendered_asset_id=approved_rendered_asset_id,
        content_fingerprint=content_fp,
        caption_hash=caption_hash,
        caption_context_fingerprint=caption_context_fp,
        extra={"performanceSnapshotId": snapshot.get("id")},
    )
    run.record["reports"]["captionOutcomeReport"] = factory.caption_outcome_report(campaign_slug)
    run.record["reports"]["performanceSummary"] = factory.performance_summary(campaign_slug)
    run.write()
    if read_only_verification and (snapshot.get("status") != "published" or snapshot.get("views") is None):
        return run.gate("awaiting_post_or_metrics", {
            "threadsDashboardPostId": snapshot.get("post_id"),
            "performanceSnapshotId": snapshot.get("id"),
            "postStatus": snapshot.get("status"),
            "views": snapshot.get("views"),
            "note": "Existing ThreadsDashboard row reconciled, but the post is not yet published with imported metrics.",
        })
    return run.complete()


def _export_manifest_asset(factory: CampaignFactory, campaign_slug: str, rendered_asset_id: str) -> dict[str, Any] | None:
    manifest = factory.export_manifest(campaign_slug=campaign_slug)
    for asset in manifest.get("assets") or []:
        if asset.get("renderedAssetId") == rendered_asset_id:
            return asset
    return None


def _latest_performance_snapshot(factory: CampaignFactory, rendered_asset_id: str) -> dict[str, Any] | None:
    row = factory.conn.execute(
        "SELECT * FROM performance_snapshots WHERE rendered_asset_id = ? ORDER BY snapshot_at DESC, created_at DESC LIMIT 1",
        (rendered_asset_id,),
    ).fetchone()
    return dict(row) if row else None


def _performance_snapshot_for_post(factory: CampaignFactory, rendered_asset_id: str, post_id: str | None) -> dict[str, Any] | None:
    if not post_id:
        return _latest_performance_snapshot(factory, rendered_asset_id)
    row = factory.conn.execute(
        """
        SELECT * FROM performance_snapshots
        WHERE rendered_asset_id = ? AND post_id = ?
        ORDER BY snapshot_at DESC
        LIMIT 1
        """,
        (rendered_asset_id, post_id),
    ).fetchone()
    return dict(row) if row else None


def _loads(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(prog="stacey-closed-loop-proof")
    arg_parser.add_argument("--campaign", default="stacey_closed_loop")
    arg_parser.add_argument("--user-id", default=os.environ.get("THREADSDASH_USER_ID"))
    arg_parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[1]))
    arg_parser.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL"))
    arg_parser.add_argument("--supabase-service-role-key", default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))
    arg_parser.add_argument("--supabase-storage-bucket", default=os.environ.get("SUPABASE_STORAGE_BUCKET", "media"))
    arg_parser.add_argument("--operator", default=os.environ.get("USER"))
    arg_parser.add_argument("--approval-reason")
    arg_parser.add_argument("--approved-rendered-asset-id")
    arg_parser.add_argument("--prompt-path", default=str(DEFAULT_STACEY_PROMPT_PATH))
    arg_parser.add_argument("--schedule-mode", choices=["live"], default="live")
    arg_parser.add_argument("--allow-warnings", action="store_true")
    arg_parser.add_argument("--allow-live-export", action="store_true")
    arg_parser.add_argument("--read-only-verification", action="store_true")
    arg_parser.add_argument("--existing-threadsdash-post-id")
    arg_parser.add_argument("--limit", type=int, default=1000)
    return arg_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = run_stacey_closed_loop_proof(
        campaign_slug=args.campaign,
        user_id=args.user_id,
        output_dir=args.output_dir,
        supabase_url=args.supabase_url,
        supabase_service_role_key=args.supabase_service_role_key,
        supabase_storage_bucket=args.supabase_storage_bucket,
        operator=args.operator,
        approval_reason=args.approval_reason,
        approved_rendered_asset_id=args.approved_rendered_asset_id,
        prompt_path=args.prompt_path,
        schedule_mode=args.schedule_mode,
        allow_warnings=args.allow_warnings,
        allow_live_export=args.allow_live_export,
        read_only_verification=args.read_only_verification,
        existing_threadsdash_post_id=args.existing_threadsdash_post_id,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("result") in {"passed", "pending"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
