#!/usr/bin/env python3
"""Compose Reference Factory paid calls with Campaign Factory authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from campaign_factory.all_provider_cost import (
    authorize_reference_paid_action,
    budget_limits_from_env,
    reconcile_reference_paid_action,
)
from campaign_factory.config import get_settings
from campaign_factory.creator_governance import resolve_campaign_operation
from campaign_factory.db import connect as connect_campaign
from campaign_factory.db import init_db
from campaign_factory.production_source_selection import (
    require_creation_enabled_creator,
)
from creator_os_core.provider_spend import build_paid_action_quote
from reference_factory.config import DEFAULT_DATA_ROOT, DEFAULT_DB_PATH
from reference_factory.db import connect as connect_reference
from reference_factory.reference_gemini import analyze_reference_with_gemini_api
from reference_factory.reference_grok import (
    analyze_reference_with_grok_api,
    compile_prompts_with_grok_api,
)

ACTION_CONFIG = {
    "gemini-analyze": ("gemini", "gemini-2.5-flash", "reference_analysis"),
    "grok-analyze": ("xai", "grok-4", "reference_analysis"),
    "grok-compile": ("xai", "grok-4", "reference_prompt_compilation"),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one Campaign-authorized paid Reference Factory action."
    )
    parser.add_argument("action", choices=sorted(ACTION_CONFIG))
    parser.add_argument("--creator", required=True, help="Campaign creator id or slug")
    parser.add_argument("--campaign", required=True, help="Campaign id or slug")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--quote-usd", required=True, type=float)
    parser.add_argument("--max-usd", required=True, type=float)
    parser.add_argument("--pricing-version", required=True)
    parser.add_argument("--campaign-db", type=Path)
    parser.add_argument("--reference-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--reference-id", required=True)
    parser.add_argument("--reference-media", type=Path)
    parser.add_argument("--source-asset-id", required=True)
    parser.add_argument("--platform", default="instagram")
    parser.add_argument(
        "--account-profile",
        help="Optional compatibility value; when set it must match --creator",
    )
    parser.add_argument("--intake-profile", default="ig_ofm")
    parser.add_argument("--media-kinds")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--prompt-style")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--instructions")
    parser.add_argument("--apply", action="store_true")
    return parser


def _resolve_identity(
    conn: sqlite3.Connection, *, table: str, value: str, label: str
) -> str:
    row = conn.execute(
        f"SELECT id FROM {table} WHERE id = ? OR slug = ?",
        (value, value),
    ).fetchone()
    if row is None:
        raise LookupError(f"{label}_not_found:{value}")
    return str(row[0])


def _creation_profile_for_creator(
    conn: sqlite3.Connection, *, creator_id: str, requested_profile: str | None
) -> str:
    row = conn.execute("SELECT slug FROM models WHERE id = ?", (creator_id,)).fetchone()
    if row is None:
        raise LookupError(f"creator_not_found:{creator_id}")
    creator_profile = require_creation_enabled_creator(str(row[0]))
    if requested_profile is not None:
        requested = require_creation_enabled_creator(requested_profile)
        if requested != creator_profile:
            raise PermissionError("reference_paid_account_profile_creator_mismatch")
    return creator_profile


def _paid_callbacks(
    conn: sqlite3.Connection,
    *,
    expected_provider: str,
    expected_model: str,
    expected_action_type: str,
    creator_id: str,
    campaign_id: str,
    run_id: str,
    reference_id: str,
    reference_source_sha256: str,
    governance_context: dict[str, Any],
    quote_usd: float,
    max_usd: float,
    pricing_version: str,
    secret: str,
) -> tuple[Any, Any]:
    def authorize(**kwargs: Any) -> dict[str, Any]:
        if (
            kwargs["provider"] != expected_provider
            or kwargs["model"] != expected_model
            or kwargs["action_type"] != expected_action_type
        ):
            raise PermissionError("reference_paid_action_route_mismatch")
        prompt_inputs = kwargs.get("prompt_inputs")
        source_sha256 = (
            prompt_inputs.get("sourceSha256")
            or prompt_inputs.get("referenceMediaSha256")
            if isinstance(prompt_inputs, dict)
            else None
        )
        if (
            not isinstance(prompt_inputs, dict)
            or prompt_inputs.get("referenceId") != reference_id
            or source_sha256 != reference_source_sha256
            or not prompt_inputs.get("rightsEvidenceFingerprint")
        ):
            raise PermissionError("reference_paid_action_source_binding_mismatch")
        quote = build_paid_action_quote(
            provider=expected_provider,
            model=expected_model,
            amount=quote_usd,
            source="operator_exact_quote",
            pricing_version=pricing_version,
        )
        limits = budget_limits_from_env(
            provider=expected_provider,
            run_cap_usd=max_usd,
        )
        return authorize_reference_paid_action(
            conn,
            provider=expected_provider,
            model=expected_model,
            action_type=expected_action_type,
            request_fingerprint=kwargs["request_fingerprint"],
            creator_id=creator_id,
            campaign_id=campaign_id,
            run_id=run_id,
            reference_id=reference_id,
            reference_source_sha256=reference_source_sha256,
            secret=secret,
            quote=quote,
            limits=limits,
            prompt_governance=kwargs["prompt_governance"],
            current_prompt_registry=kwargs["current_prompt_registry"],
            compiled_prompt=kwargs["compiled_prompt"],
            prompt_inputs=kwargs["prompt_inputs"],
            governance_context=governance_context,
        )

    def reconcile(**kwargs: Any) -> dict[str, Any]:
        return reconcile_reference_paid_action(
            conn,
            paid_action=kwargs["paid_action"],
            actual_usd=kwargs["actual_usd"],
            provider_reference=kwargs["provider_reference"],
            unknown_reason=kwargs["unknown_reason"],
        )

    return authorize, reconcile


def _resolve_reference_binding(
    campaign_conn: sqlite3.Connection,
    reference_conn: sqlite3.Connection,
    *,
    creator_id: str,
    campaign_id: str,
    reference_id: str,
    source_asset_id: str,
    provider: str,
) -> dict[str, Any]:
    reference = reference_conn.execute(
        """
        SELECT reference_id, path, content_hash
        FROM source_files WHERE reference_id = ?
        """,
        (reference_id,),
    ).fetchone()
    if reference is None:
        raise LookupError(f"reference_not_found:{reference_id}")
    reference_path = Path(str(reference["path"])).expanduser().resolve()
    reference_sha256 = str(reference["content_hash"] or "").strip().lower()
    if not reference_path.is_file() or _sha256_file(reference_path) != reference_sha256:
        raise PermissionError("reference_source_bytes_mismatch")
    source = campaign_conn.execute(
        """
        SELECT id, campaign_id, model_id, content_hash, stored_path, status
        FROM source_assets WHERE id = ?
        """,
        (source_asset_id,),
    ).fetchone()
    if (
        source is None
        or source["campaign_id"] != campaign_id
        or source["model_id"] != creator_id
        or source["status"] != "approved"
        or source["content_hash"] != reference_sha256
    ):
        raise PermissionError("reference_campaign_source_binding_mismatch")
    source_path = Path(str(source["stored_path"])).expanduser().resolve()
    if not source_path.is_file() or _sha256_file(source_path) != reference_sha256:
        raise PermissionError("reference_campaign_source_bytes_mismatch")
    governance = resolve_campaign_operation(
        campaign_conn,
        campaign_id=campaign_id,
        operation="reference_analysis",
        provider=provider,
        source_asset_id=source_asset_id,
    )
    if governance.get("creatorId") != creator_id:
        raise PermissionError("reference_campaign_creator_binding_mismatch")
    return {
        "referenceId": reference_id,
        "referencePath": reference_path,
        "referenceSourceSha256": reference_sha256,
        "sourceAssetId": source_asset_id,
        "creatorGovernance": governance,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.apply:
        raise PermissionError("reference_paid_action_requires_apply")
    secret = str(os.environ.get("CREATOR_OS_SPEND_AUTH_SECRET") or "")
    settings = get_settings()
    campaign_db = (args.campaign_db or settings.db_path).expanduser().resolve()
    campaign_conn = connect_campaign(campaign_db)
    reference_conn = connect_reference(args.reference_db.expanduser().resolve())
    try:
        init_db(campaign_conn)
        creator_id = _resolve_identity(
            campaign_conn,
            table="models",
            value=args.creator,
            label="creator",
        )
        creator_profile = _creation_profile_for_creator(
            campaign_conn,
            creator_id=creator_id,
            requested_profile=args.account_profile,
        )
        campaign_id = _resolve_identity(
            campaign_conn,
            table="campaigns",
            value=args.campaign,
            label="campaign",
        )
        provider, model, action_type = ACTION_CONFIG[args.action]
        binding = _resolve_reference_binding(
            campaign_conn,
            reference_conn,
            creator_id=creator_id,
            campaign_id=campaign_id,
            reference_id=args.reference_id,
            source_asset_id=args.source_asset_id,
            provider=provider,
        )
        authorize, reconcile = _paid_callbacks(
            campaign_conn,
            expected_provider=provider,
            expected_model=model,
            expected_action_type=action_type,
            creator_id=creator_id,
            campaign_id=campaign_id,
            run_id=args.run_id,
            reference_id=args.reference_id,
            reference_source_sha256=binding["referenceSourceSha256"],
            governance_context=binding["creatorGovernance"],
            quote_usd=args.quote_usd,
            max_usd=args.max_usd,
            pricing_version=args.pricing_version,
            secret=secret,
        )
        data_root = args.data_root.expanduser().resolve()
        if args.action in {"gemini-analyze", "grok-analyze"}:
            if args.source is not None:
                requested_source = args.source.expanduser().resolve()
                reference_path = binding["referencePath"]
                if requested_source != reference_path and (
                    not requested_source.is_dir()
                    or reference_path.parent != requested_source
                ):
                    raise PermissionError("reference_paid_source_argument_mismatch")
            media_kinds = (
                [
                    value.strip()
                    for value in args.media_kinds.split(",")
                    if value.strip()
                ]
                if args.media_kinds
                else ["video"]
                if args.action == "gemini-analyze"
                else ["video", "image"]
            )
            common = {
                "conn": reference_conn,
                "source_root": binding["referencePath"],
                "data_root": data_root,
                "platform": args.platform,
                "account_profile": creator_profile,
                "intake_profile": args.intake_profile,
                "media_kinds": media_kinds,
                "limit": args.limit,
                "model": model,
                "paid_action_authorizer": authorize,
                "paid_action_reconciler": reconcile,
            }
            result = (
                analyze_reference_with_gemini_api(
                    **common,
                    prompt_style=args.prompt_style or "minimal",
                )
                if args.action == "gemini-analyze"
                else analyze_reference_with_grok_api(
                    **common,
                    prompt_style=args.prompt_style or "imageat",
                    ffmpeg=args.ffmpeg,
                )
            )
        else:
            if args.reference_media is not None and (
                args.reference_media.expanduser().resolve() != binding["referencePath"]
            ):
                raise PermissionError("reference_paid_media_argument_mismatch")
            result = compile_prompts_with_grok_api(
                reference_conn,
                data_root=data_root,
                reference_id=args.reference_id,
                reference_media=binding["referencePath"],
                model=model,
                ffmpeg=args.ffmpeg,
                instructions=args.instructions,
                paid_action_authorizer=authorize,
                paid_action_reconciler=reconcile,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        reference_conn.close()
        campaign_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
