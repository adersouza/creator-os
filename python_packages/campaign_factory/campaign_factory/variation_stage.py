from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Any

from creator_os_core.fileops import atomic_write_text
from repurposer.pipeline import VariantPipeline

from pipeline_contracts import validate_variant_assignment

from .adapters.contentforge import audit_variation_batch

CAMPAIGN_FACTORY_AUDIT_CONTRACTS = {
    "campaign_factory_audit.v1.7",
    "campaign_factory_audit.v1.8",
    "campaign_factory_audit.v1.9",
    "campaign_factory_audit.v1.10",
}


def run_variation_stage(
    factory: Any,
    *,
    campaign_slug: str,
    preset_name: str = "ig_subtle",
    rendered_asset_ids: list[str] | None = None,
    dry_run: bool = True,
    contentforge_base_url: str | None = None,
) -> dict[str, Any]:
    """Create per-account zero-cost variant assignments for approved campaign assets."""
    manifest = factory.export_manifest(campaign_slug=campaign_slug)
    selected_ids = set(rendered_asset_ids or [])
    campaign = factory.campaign_by_slug(campaign_slug)
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    output_dir = (
        factory.campaign_dirs(model_slug, campaign_slug)["exports"]
        / "variation_assignments"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for asset in manifest["assets"]:
        if selected_ids and asset["renderedAssetId"] not in selected_ids:
            continue
        accounts = _account_targets_for_asset(factory, asset)
        if not accounts:
            continue
        if dry_run:
            assignment = _dry_run_assignment(
                campaign_slug=campaign_slug,
                asset=asset,
                accounts=accounts,
                preset_name=preset_name,
                output_dir=output_dir,
            )
            path = (
                output_dir
                / f"{_safe_slug(asset['renderedAssetId'])}.variant_assignment.preview.v1.json"
            )
            atomic_write_text(
                path, json.dumps(assignment, indent=2, sort_keys=True), encoding="utf-8"
            )
        else:
            pipeline = VariantPipeline(
                Path(asset["filePath"]),
                accounts=accounts,
                platform=manifest.get("platform") or "reels",
                output_dir=output_dir,
            )
            path = pipeline.manifest_path(asset["renderedAssetId"])
            path.unlink(missing_ok=True)
            assignment = pipeline.generate_assignment_manifest(
                preset_name=preset_name,
                campaign_slug=campaign_slug,
                master_asset_id=asset["renderedAssetId"],
                write_manifest=False,
            )
            variant_paths = [
                Path(item["variant_path"]) for item in assignment["assignments"]
            ]
            report_path = (
                output_dir
                / f"{_safe_slug(asset['renderedAssetId'])}.perceptual_audit.v1.json"
            )
            try:
                audit = audit_variation_batch(
                    contentforge_root=factory.settings.contentforge_root,
                    source_path=Path(asset["filePath"]),
                    variant_paths=variant_paths,
                    contentforge_base_url=contentforge_base_url
                    or factory.settings.contentforge_base_url,
                    report_path=report_path,
                )
                readiness = audit.get("readinessSummary") or {}
                verdicts = audit.get("verdicts") or {}
                blocking_codes = [
                    str(code) for code in readiness.get("blockingCodes") or []
                ]
                if (
                    audit.get("contractVersion") not in CAMPAIGN_FACTORY_AUDIT_CONTRACTS
                    or readiness.get("uploadReady") is not True
                    or verdicts.get("pdq") != "pass"
                    or verdicts.get("sscd") != "pass"
                ):
                    detail = (
                        ", ".join(blocking_codes) or "perceptual_detector_gate_failed"
                    )
                    raise RuntimeError(f"variation perceptual gate blocked: {detail}")
                audit_lineage = {
                    "contract_version": audit["contractVersion"],
                    "report_path": str(report_path),
                    "verdicts": {
                        "pdq": verdicts["pdq"],
                        "sscd": verdicts["sscd"],
                    },
                }
                for item in assignment["assignments"]:
                    item.setdefault("lineage", {})["perceptual_audit"] = audit_lineage
                validate_variant_assignment(assignment)
                atomic_write_text(
                    path,
                    json.dumps(assignment, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except Exception:
                for variant_path in variant_paths:
                    variant_path.unlink(missing_ok=True)
                path.unlink(missing_ok=True)
                raise
        validate_variant_assignment(assignment)
        results.append(
            {
                "renderedAssetId": asset["renderedAssetId"],
                "assignmentPath": str(path),
                "assignmentCount": len(assignment["assignments"]),
                "dryRun": dry_run,
            }
        )

    return {
        "schema": "campaign_factory.variation_stage_run.v1",
        "campaign": campaign_slug,
        "dryRun": dry_run,
        "presetName": preset_name,
        "outputDir": str(output_dir),
        "assignments": results,
    }


def load_variant_assignment_index(
    factory: Any, *, campaign_slug: str
) -> dict[str, dict[str, Any]]:
    campaign = factory.campaign_by_slug(campaign_slug)
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    assignment_dir = (
        factory.campaign_dirs(model_slug, campaign_slug)["exports"]
        / "variation_assignments"
    )
    index: dict[str, dict[str, Any]] = {}
    for path in sorted(assignment_dir.glob("*.variant_assignment.v1.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_variant_assignment(payload)
        by_account: dict[str, Any] = {}
        for assignment in payload["assignments"]:
            by_account[
                _account_key(
                    assignment.get("account_id"), assignment.get("instagram_account_id")
                )
            ] = assignment
            by_account[_account_key(assignment.get("account_id"), None)] = assignment
            by_account[_account_key(None, assignment.get("instagram_account_id"))] = (
                assignment
            )
        index[payload["master_asset_id"]] = {
            "path": str(path),
            "payload": payload,
            "byAccount": by_account,
        }
    return index


def variant_for_destination(
    assignment_index: dict[str, dict[str, Any]],
    *,
    rendered_asset_id: str,
    account_id: str | None,
    instagram_account_id: str | None,
) -> dict[str, Any] | None:
    asset_entry = assignment_index.get(rendered_asset_id)
    if not asset_entry:
        return None
    by_account = asset_entry["byAccount"]
    return (
        by_account.get(_account_key(account_id, instagram_account_id))
        or by_account.get(_account_key(account_id, None))
        or by_account.get(_account_key(None, instagram_account_id))
    )


def _account_targets_for_asset(
    factory: Any, asset: dict[str, Any]
) -> list[dict[str, Any]]:
    from .adapters.threadsdash import _draft_destinations_for_asset

    destinations = _draft_destinations_for_asset(factory, asset)
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for destination in destinations:
        account_id = destination.get("accountId") or destination.get(
            "instagramAccountId"
        )
        if not account_id:
            continue
        key = _account_key(str(account_id), destination.get("instagramAccountId"))
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "account_id": str(account_id),
                "instagram_account_id": destination.get("instagramAccountId"),
                "preset_name": destination.get("variationPreset") or "ig_subtle",
                "persona": destination.get("reasonCode"),
            }
        )
    return targets


def _dry_run_assignment(
    *,
    campaign_slug: str,
    asset: dict[str, Any],
    accounts: list[dict[str, Any]],
    preset_name: str,
    output_dir: Path,
) -> dict[str, Any]:
    assignments = []
    for account in accounts:
        account_id = account["account_id"]
        variant_asset_id = (
            f"{_safe_slug(asset['renderedAssetId'])}_{_safe_slug(account_id)}"
        )
        assignments.append(
            {
                "account_id": account_id,
                "instagram_account_id": account.get("instagram_account_id"),
                "persona": account.get("persona"),
                "variant_asset_id": variant_asset_id,
                "variant_path": str(output_dir / f"{variant_asset_id}_variant.mp4"),
                "parent_master_asset_id": asset["renderedAssetId"],
                "preset_name": account.get("preset_name") or preset_name,
                "distinctness_scores": {
                    "master_ssim": 0.0,
                    "sibling_max_ssim": 0.0,
                    "threshold": 0.85,
                },
                "lineage": {
                    "mode": "zero_cost_variation_dry_run",
                    "paid_generation": False,
                    "micro_enabled": False,
                },
            }
        )
    return {
        "schema": "campaign_factory.variant_assignment.v1",
        "campaign_slug": campaign_slug,
        "master_asset_id": asset["renderedAssetId"],
        "master_asset_path": str(asset["filePath"]),
        "platform": "reels",
        "generated_at": _utc_now(),
        "variation_enabled": True,
        "assignments": assignments,
    }


def _account_key(account_id: str | None, instagram_account_id: str | None) -> str:
    return f"{account_id or ''}|{instagram_account_id or ''}"


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9._:-]+", "_", str(value).strip())
    return slug.strip("_") or "unassigned"


def _utc_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
