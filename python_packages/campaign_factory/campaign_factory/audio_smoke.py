from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .adapters.threadsdash import build_draft_payloads, evaluate_export_readiness, export_threadsdash
from .config import Settings
from .contracts import validate_audio_catalog_export, validate_performance_sync, validate_threadsdash_draft_payload
from .core import CampaignFactory, utc_now


SMOKE_CSV = """title,artist,platform,native_audio_id,native_audio_url,mood_tags,best_content_types,account_fit,bpm,energy,trend_status,usage_count,safe_usage_notes,expires_at
Runway Pop,DJ A,instagram,ig_runway_pop,https://instagram.com/audio/runway_pop,glam|fit_check,regular_reel|v01_original,smoke_account,124,8,rising,120000,Attach natively only,2099-01-01T00:00:00+00:00
"""

SMOKE_SNAPSHOT_CSV = """platform,native_audio_id,observed_at,trend_status,usage_count,saturation_score,velocity_score,source,notes
instagram,ig_runway_pop,2026-05-22T11:00:00+00:00,trending,140000,0.33,0.82,manual smoke fixture,Local-only smoke observation
"""

CONTENTFORGE_SMOKE_RESPONSE = {
    "contractVersion": "campaign_factory_audit.v1.9",
    "auditProfile": "campaign_factory_v1",
    "targetFile": "rendered_smoke.mp4",
    "layers": {},
    "verdicts": {},
    "verdictCodes": {"forensics": "forensics_pass", "readability": "caption_readable"},
    "overallVerdict": "pass",
    "readinessSummary": {
        "summaryText": "Upload-ready smoke candidate.",
        "uploadReady": True,
        "blockingReasons": [],
        "warnings": [],
        "recommendedAction": "approve_candidate",
    },
    "filesAnalyzed": 1,
}


def write_smoke_audio_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SMOKE_CSV, encoding="utf-8")
    return path


def write_smoke_audio_snapshot_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SMOKE_SNAPSHOT_CSV, encoding="utf-8")
    return path


def run_pipeline_audio_smoke(
    *,
    projects_root: Path,
    workspace: Path | None = None,
    run_threadsdash_validator: bool = True,
) -> dict[str, Any]:
    projects_root = Path(projects_root).expanduser().resolve()
    reference_root = projects_root / "reference_factory"
    threadsdash_root = projects_root / "ThreadsDashboard"
    reel_root = projects_root / "reel_factory"
    contentforge_root = projects_root / "contentforge"
    for name, path in {
        "reference_factory": reference_root,
        "ThreadsDashboard": threadsdash_root,
        "reel_factory": reel_root,
        "contentforge": contentforge_root,
    }.items():
        if not path.exists():
            raise FileNotFoundError(f"{name} not found under {projects_root}")

    if workspace is None:
        with tempfile.TemporaryDirectory(prefix="campaign-audio-smoke-") as tmp:
            return _run_pipeline_audio_smoke(
                projects_root=projects_root,
                workspace=Path(tmp),
                reference_root=reference_root,
                threadsdash_root=threadsdash_root,
                reel_root=reel_root,
                contentforge_root=contentforge_root,
                run_threadsdash_validator=run_threadsdash_validator,
            )
    return _run_pipeline_audio_smoke(
        projects_root=projects_root,
        workspace=Path(workspace).expanduser().resolve(),
        reference_root=reference_root,
        threadsdash_root=threadsdash_root,
        reel_root=reel_root,
        contentforge_root=contentforge_root,
        run_threadsdash_validator=run_threadsdash_validator,
    )


def _run_pipeline_audio_smoke(
    *,
    projects_root: Path,
    workspace: Path,
    reference_root: Path,
    threadsdash_root: Path,
    reel_root: Path,
    contentforge_root: Path,
    run_threadsdash_validator: bool,
) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    audio_csv = write_smoke_audio_csv(workspace / "audio_catalog_smoke.csv")
    snapshot_csv = write_smoke_audio_snapshot_csv(workspace / "audio_trend_snapshot_smoke.csv")
    reference_export = workspace / "reference_audio_catalog_export.json"
    reference_import = _run_reference_cli(
        reference_root,
        workspace,
        ["import-audio-csv", "--input", str(audio_csv)],
    )
    reference_snapshot_import = _run_reference_cli(
        reference_root,
        workspace,
        ["import-audio-snapshot-csv", "--input", str(snapshot_csv)],
    )
    reference_snapshots = _run_reference_cli(
        reference_root,
        workspace,
        ["list-audio-snapshots", "--platform", "instagram"],
    )
    reference_list = _run_reference_cli(
        reference_root,
        workspace,
        ["list-audio", "--export", str(reference_export)],
    )
    validate_audio_catalog_export(json.loads(reference_export.read_text(encoding="utf-8")))

    settings = Settings(
        root=workspace / "campaign_factory",
        db_path=workspace / "campaign_factory" / "campaign_factory.sqlite",
        reel_factory_root=reel_root,
        contentforge_root=contentforge_root,
        reference_factory_root=reference_root,
        threadsdash_root=threadsdash_root,
        campaigns_dir=workspace / "campaign_factory" / "campaigns",
    )
    factory = CampaignFactory(settings)
    try:
        audio_import = factory.import_audio_catalog(reference_export)
        creative_plan = factory.create_creative_plan(
            name="audio_smoke_daily_plan",
            platform="instagram",
            target_account="smoke_account",
            daily_base_video_target=10,
            style_lanes=["amateur_native", "polished_glam", "slideshow_story"],
            model_profile="smoke_model",
            source_accounts=["smoke_creator"],
            linked_campaign="audio_smoke",
        )
        source, rendered_path = create_smoke_campaign_asset(factory, workspace)
        factory.conn.execute(
            "UPDATE source_assets SET source_prompt = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "creativePlanId": creative_plan["id"],
                        "creativePlanName": creative_plan["name"],
                        "styleLane": "amateur_native",
                        "referenceId": "smoke_reference",
                        "higgsfield_soul_image_prompt": "Smoke model mirror selfie, native IG style.",
                        "kling_3_video_prompt": "Use the generated image as the first frame; subtle handheld selfie motion.",
                    }
                ),
                utc_now(),
                source["id"],
            ),
        )
        factory.conn.commit()
        factory.review_rendered_asset("asset_smoke", decision="approved")
        add_smoke_audit_report(factory)
        draft_payload = build_draft_payloads(factory, campaign_slug="audio_smoke", user_id="smoke_user")
        validate_threadsdash_draft_payload(draft_payload)
        intent = assert_smoke_draft_audio_intent(draft_payload)
        contentforge_response = assert_contentforge_contract_response(CONTENTFORGE_SMOKE_RESPONSE)
        readiness = evaluate_export_readiness(factory, campaign_slug="audio_smoke", user_id="smoke_user")
        blocking_reasons = readiness.get("blockingReasons") or []
        expected_audio_block = "campaign_audio_unresolved: select audio before ThreadsDashboard export"
        if not any(expected_audio_block in str(reason) for reason in blocking_reasons):
            raise AssertionError(f"expected unresolved campaign audio block, got {blocking_reasons}")
        export_result = export_threadsdash(factory, campaign_slug="audio_smoke", user_id="smoke_user", dry_run=True)
        draft_path = Path(export_result["path"])
        validate_threadsdash_draft_payload(json.loads(draft_path.read_text(encoding="utf-8"))["payload"])
        reel_result = _run_reel_approved_export_sidecar(reel_root, workspace, intent)
        performance_sync = sync_smoke_performance(factory, draft_payload=draft_payload, user_id="smoke_user")
    finally:
        factory.close()

    threadsdash_result: dict[str, Any] | None = None
    if run_threadsdash_validator:
        threadsdash_result = _run_threadsdash_validator(threadsdash_root, draft_path)

    summary = {
        "schema": "campaign_factory.pipeline_audio_smoke.v1",
        "ok": True,
        "workspace": str(workspace),
        "projectsRoot": str(projects_root),
        "reference": {
            "csv": str(audio_csv),
            "snapshotCsv": str(snapshot_csv),
            "exportPath": str(reference_export),
            "imported": reference_import.get("imported"),
            "snapshotsImported": reference_snapshot_import.get("imported"),
            "snapshotCount": reference_snapshots.get("count"),
            "exportedCount": reference_list.get("count"),
        },
        "campaign": {
            "audioCatalogImported": audio_import.get("tracksImported"),
            "sourceAssetId": source.get("id"),
            "renderedPath": str(rendered_path),
            "draftExportPath": str(draft_path),
            "audioIntentStatus": intent.get("status"),
            "recommendationCount": len(intent.get("recommendations") or []),
            "performanceInserted": performance_sync.get("inserted"),
            "leaderboardAudioCount": len((((performance_sync.get("summary") or {}).get("leaderboards") or {}).get("audioRecommendations") or [])),
            "liveExportAllowed": readiness.get("liveExportAllowed"),
            "blockingReasons": blocking_reasons,
            "creativePlan": {
                "id": creative_plan.get("id"),
                "name": creative_plan.get("name"),
                "status": creative_plan.get("status"),
            },
        },
        "reelFactory": reel_result,
        "contentforge": {
            "contractVersion": contentforge_response.get("contractVersion"),
            "overallVerdict": contentforge_response.get("overallVerdict"),
            "uploadReady": (contentforge_response.get("readinessSummary") or {}).get("uploadReady"),
        },
        "threadsdash": threadsdash_result,
        "skippedBoundaries": skipped_boundaries(threadsdash_root),
    }
    (workspace / "pipeline_audio_smoke_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def create_smoke_campaign_asset(factory: CampaignFactory, workspace: Path) -> tuple[dict[str, Any], Path]:
    source_dir = workspace / "source_inputs"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "source.mp4").write_bytes(b"smoke source")
    factory.import_folder(
        source_dir,
        campaign_slug="audio_smoke",
        model_slug="smoke_model",
        account_handles=["smoke_account"],
    )
    source = factory.assets_for_campaign(factory.campaign_by_slug("audio_smoke")["id"])[0]
    rendered_path = workspace / "rendered_smoke.mp4"
    rendered_path.write_bytes(b"smoke rendered")
    now = "2026-05-22T00:00:00+00:00"
    factory.conn.execute(
        """
        INSERT INTO rendered_assets
        (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe,
         audit_status, review_state, caption_generation_json, created_at, updated_at)
        VALUES ('asset_smoke', ?, ?, 'smoke_hash', ?, ?, 'rendered_smoke.mp4', 'fit check hook', 'v01_original',
                'pending', 'draft', '{}', ?, ?)
        """,
        (
            source["campaign_id"],
            source["id"],
            str(rendered_path),
            str(rendered_path),
            now,
            now,
        ),
    )
    factory.conn.commit()
    return source, rendered_path


def add_smoke_audit_report(factory: CampaignFactory) -> None:
    asset = factory.conn.execute("SELECT * FROM rendered_assets WHERE id = 'asset_smoke'").fetchone()
    if asset is None:
        raise AssertionError("smoke rendered asset missing")
    report_path = Path(asset["campaign_path"]).with_suffix(".audit_smoke.json")
    report_path.write_text(
        json.dumps({
            "readinessSummary": {"uploadReady": True, "blockingReasons": [], "warnings": []},
            "error": None,
        }),
        encoding="utf-8",
    )
    before = factory.conn.total_changes
    factory.conn.execute(
        """
        INSERT INTO audit_reports
        (id, campaign_id, rendered_asset_id, contentforge_run_id, report_path, score, status,
         layers_json, verdicts_json, overall_verdict, files_analyzed, failed_checks_json, warnings_json, created_at)
        VALUES ('audit_smoke', ?, 'asset_smoke', 'run_smoke', ?, 100, 'approved_candidate',
                '{}', '{}', 'pass', 1, '[]', '[]', '2026-05-22T00:00:00+00:00')
        """,
        (asset["campaign_id"], str(report_path)),
    )
    factory.conn.commit()


def assert_contentforge_contract_response(response: dict[str, Any]) -> dict[str, Any]:
    required = ["contractVersion", "auditProfile", "targetFile", "overallVerdict", "readinessSummary", "filesAnalyzed"]
    missing = [key for key in required if key not in response]
    if missing:
        raise AssertionError(f"ContentForge smoke response missing {missing}")
    if response["auditProfile"] != "campaign_factory_v1":
        raise AssertionError(f"unexpected ContentForge audit profile: {response['auditProfile']}")
    if response["overallVerdict"] not in {"pass", "warn", "fail"}:
        raise AssertionError(f"unexpected ContentForge verdict: {response['overallVerdict']}")
    readiness = response.get("readinessSummary")
    if not isinstance(readiness, dict) or not isinstance(readiness.get("uploadReady"), bool):
        raise AssertionError(f"malformed ContentForge readiness summary: {readiness}")
    return response


def assert_smoke_draft_audio_intent(draft_payload: dict[str, Any]) -> dict[str, Any]:
    drafts = draft_payload.get("drafts") or []
    if len(drafts) != 1:
        raise AssertionError(f"expected one smoke draft, got {len(drafts)}")
    metadata = drafts[0].get("metadata") or {}
    campaign_factory = metadata.get("campaign_factory") or {}
    intent = campaign_factory.get("audio_intent") or {}
    if intent.get("status") != "recommended":
        raise AssertionError(f"expected recommended audio intent, got {intent}")
    recommendations = intent.get("recommendations") or []
    if not recommendations:
        raise AssertionError("expected audio recommendations")
    decision = intent.get("decision") or {}
    primary = decision.get("primaryAudio") or {}
    if not primary:
        raise AssertionError(f"expected audio decision primary, got {decision}")
    if primary.get("audio_title") != "Runway Pop" or primary.get("platform_audio_id") != "ig_runway_pop":
        raise AssertionError(f"unexpected audio decision primary: {primary}")
    first = recommendations[0]
    for key in ("audio_title", "artist_name", "platform_audio_id", "platform_url", "vibe_tags", "confidence", "rationale"):
        if first.get(key) in (None, "", []):
            raise AssertionError(f"recommendation missing {key}: {first}")
    return intent


def sync_smoke_performance(factory: CampaignFactory, *, draft_payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    drafts = draft_payload.get("drafts") or []
    if not drafts:
        raise AssertionError("expected draft payload for performance smoke")
    campaign_slug = str(draft_payload.get("campaign") or "audio_smoke")
    campaign = factory.campaign_by_slug(campaign_slug)
    draft = drafts[0]
    meta = ((draft.get("metadata") or {}).get("campaign_factory") or {})
    now = "2026-05-22T12:30:00+00:00"
    raw = {
        "id": "post_smoke_perf_1",
        "status": "published",
        "platform": "instagram",
        "instagram_account_id": draft.get("instagramAccountId") or "smoke_account",
        "permalink": "https://instagram.test/p/smoke",
        "published_at": "2026-05-22T12:00:00+00:00",
        "metadata": {"campaign_factory": meta, "metrics": {"reach": 1800, "watch_time_seconds": 420.0}},
    }
    before = factory.conn.total_changes
    factory.conn.execute(
        """
        INSERT OR IGNORE INTO performance_snapshots
        (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
         caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
         permalink, published_at, snapshot_at, views, likes, comments, shares, saves, reach,
         watch_time_seconds, metrics_eligible, raw_json, created_at)
        VALUES
        ('perf_smoke_1', ?, ?, ?, ?, ?, ?, ?, 'post_smoke_perf_1', 'instagram', 'published',
         NULL, ?, 'https://instagram.test/p/smoke', '2026-05-22T12:00:00+00:00', ?,
         2400, 190, 22, 31, 44, 1800, 420.0, 1, ?, ?)
        """,
        (
            campaign["id"],
            meta.get("rendered_asset_id"),
            meta.get("source_asset_id"),
            meta.get("content_hash"),
            meta.get("source_content_hash"),
            meta.get("caption_hash"),
            meta.get("recipe"),
            draft.get("instagramAccountId") or "smoke_account",
            now,
            json.dumps(raw, sort_keys=True),
            now,
        ),
    )
    inserted = 1 if factory.conn.total_changes > before else 0
    factory.conn.commit()
    result = {
        "schema": "campaign_factory.performance_sync.v1",
        "campaign": campaign_slug,
        "userId": user_id,
        "checkedAt": now,
        "postsScanned": 1,
        "campaignFactoryPostsScanned": 1,
        "inserted": inserted,
        "skipped": 0,
        "summary": factory.performance_summary(campaign_slug),
        "pipelineJobId": "job_audio_smoke_perf",
        "pipelineTraceId": "trace_audio_smoke_perf",
    }
    validate_performance_sync(result)
    return result


def skipped_boundaries(threadsdash_root: Path) -> list[dict[str, str]]:
    audio_event_handler = threadsdash_root / "api" / "_lib" / "handlers" / "posts" / "campaignFactoryAudioEvents.ts"
    migration = threadsdash_root / "supabase" / "migrations" / "20260522120000_campaign_factory_audio_events.sql"
    validator = threadsdash_root / "tests" / "unit" / "campaignFactoryAudioHandler.test.ts"
    if (
        audio_event_handler.exists()
        and migration.exists()
        and validator.exists()
        and "local DB-backed fixture" in validator.read_text(encoding="utf-8")
    ):
        return []
    if audio_event_handler.exists() and migration.exists():
        return [{
            "boundary": "threadsdash_audio_event_write_read",
            "reason": "ThreadsDashboard exposes the handler and migration, but no local DB-backed validator fixture is present; smoke stays read-only for sibling repos.",
        }]
    return [{
        "boundary": "threadsdash_audio_event_write_read",
        "reason": "No local ThreadsDashboard audio-event validator/helper was found.",
    }]


def _run_reel_approved_export_sidecar(reel_root: Path, workspace: Path, audio_intent: dict[str, Any]) -> dict[str, Any]:
    fixture_root = workspace / "reel_factory_fixture"
    script = f"""
import json
import sys
from pathlib import Path
sys.path.insert(0, {str(reel_root)!r})
from export_approved import export_approved
from manifest import Manifest, sha256_str
from reel_pipeline import Recipe

root = Path({str(fixture_root)!r})
root.mkdir(parents=True, exist_ok=True)
manifest = Manifest(root / "manifest.json")
src = root / "clip_001.mp4"
out = root / "clip_001_h00_v01_original_light_deadbeef.mp4"
src.write_bytes(b"source")
out.write_bytes(b"output")
out.with_suffix(out.suffix + ".audio_intent.json").write_text({json.dumps(json.dumps(audio_intent, sort_keys=True))}, encoding="utf-8")
recipe = Recipe("v01_original")
key = sha256_str("src-hash|fit check hook|v01_original")
manifest.upsert_video("clip_001", src, "src-hash", 2.5)
manifest.add_variation("clip_001", recipe, "fit check hook", out, key, 2.5)
manifest.set_review_state(out.name, "approved")
manifest.save()
print(json.dumps(export_approved(root, account="smoke_account", platform="instagram", date="2026-05-22"), ensure_ascii=False))
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=reel_root, text=True, capture_output=True, check=True)
    payload = json.loads(result.stdout)
    items = payload.get("items") or []
    if len(items) != 1:
        raise AssertionError(f"expected one Reel Factory approved item, got {len(items)}")
    sidecar_intent = items[0].get("audio_intent") or {}
    if sidecar_intent.get("schema") != "pipeline.audio_intent.v1" or sidecar_intent.get("status") != audio_intent.get("status"):
        raise AssertionError(f"Reel Factory audio_intent sidecar was not preserved: {sidecar_intent}")
    return {
        "ok": True,
        "exportPath": payload.get("path"),
        "count": payload.get("count"),
        "audioIntentStatus": sidecar_intent.get("status"),
        "audioIntentPreserved": bool((items[0].get("audio_workflow") or {}).get("audio_intent_preserved")),
    }


def _run_reference_cli(reference_root: Path, workspace: Path, args: list[str]) -> dict[str, Any]:
    python = reference_root / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    cmd = [
        str(python),
        "-m",
        "reference_factory.cli",
        "--db",
        str(workspace / "reference_factory.sqlite"),
        "--data-root",
        str(workspace / "reference_data"),
        *args,
    ]
    result = subprocess.run(cmd, cwd=reference_root, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def _run_threadsdash_validator(threadsdash_root: Path, draft_path: Path) -> dict[str, Any]:
    env = {**os.environ, "PIPELINE_AUDIO_SMOKE_FIXTURE": str(draft_path)}
    cmd = [
        "npm",
        "test",
        "--",
        "--run",
        "tests/pipelineAudioSmokeFixture.test.ts",
        "tests/unit/campaignFactoryAudioHandler.test.ts",
    ]
    result = subprocess.run(cmd, cwd=threadsdash_root, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        raise AssertionError(
            "ThreadsDashboard smoke validator failed\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return {"ok": True, "command": " ".join(cmd), "audioEventWriteReadCovered": True}
