from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import campaign_factory.app as app_module
import campaign_factory.variant_lineage as variant_lineage_module
import pytest
from campaign_asset_test_support import add_audit_report, add_surface_asset_fixture
from campaign_factory.adapters import contentforge as contentforge_adapter
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters.contentforge import audit_campaign
from campaign_factory.audio_smoke import (
    CONTENTFORGE_SMOKE_RESPONSE,
    assert_contentforge_contract_response,
)
from campaign_factory.cli_parser import build_cli_parser
from campaign_factory.config import CREATOR_OS_ROOT, Settings
from campaign_factory.contracts import (
    validate_motion_edit_render,
    validate_schema_examples,
    validate_variant_assignment,
)
from campaign_factory.control import operator_control_check
from campaign_learning_test_support import (
    _approve_asset_for_lifecycle,
    _draft_item,
    _insert_creative_kb_snapshot,
    _manager_report_fixture,
    add_account_requirement_fixture,
    threadsdash_campaign_factory_metadata,
)
from campaign_test_support import add_rendered_asset, add_source_asset, make_factory
from fastapi.testclient import TestClient

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

MONOREPO_ROOT = Path(__file__).resolve().parents[3]

CLI_PYTHONPATH = os.pathsep.join(
    [
        str(PACKAGE_ROOT),
        str(MONOREPO_ROOT / "packages" / "pipeline_contracts"),
    ]
)


def test_export_threadsdash_cli_defaults_to_regular_reel_surface():
    args = build_cli_parser().parse_args(
        ["export-threadsdash", "--campaign", "may", "--user-id", "user_1"]
    )

    assert args.surface == "regular_reel"


def test_operator_control_check_reports_required_entrypoints(tmp_path: Path):
    root = tmp_path / "campaign_factory"
    reel_root = tmp_path / "reel_factory"
    contentforge_root = tmp_path / "contentforge"
    reference_root = tmp_path / "reference_factory"
    threadsdash_root = tmp_path / "ThreadsDashboard"
    for path in [
        root / "campaign_factory",
        reel_root,
        contentforge_root / "lib",
        reference_root / "reference_factory",
        threadsdash_root,
    ]:
        path.mkdir(parents=True, exist_ok=True)
    (root / "campaign_factory" / "cli.py").write_text("", encoding="utf-8")
    (reel_root / "reel_factory").mkdir()
    (reel_root / "reel_factory" / "reel_pipeline.py").write_text("", encoding="utf-8")
    (reel_root / "reel_factory" / "slideshow_factory.py").write_text(
        "", encoding="utf-8"
    )
    (contentforge_root / "package.json").write_text("{}", encoding="utf-8")
    (contentforge_root / "cli.mjs").write_text("", encoding="utf-8")
    (contentforge_root / "lib" / "similarity.js").write_text("", encoding="utf-8")
    (reference_root / "reference_factory" / "cli.py").write_text("", encoding="utf-8")
    settings = Settings(
        root=root,
        db_path=root / "campaign_factory.sqlite",
        reel_factory_root=reel_root,
        contentforge_root=contentforge_root,
        reference_factory_root=reference_root,
        threadsdash_root=threadsdash_root,
        campaigns_dir=root / "campaigns",
    )

    result = operator_control_check(settings)

    assert result["ok"] is True
    assert result["blockingCount"] == 0
    assert any(check["name"] == "reference_bank" for check in result["checks"])
    assert any(check["name"] == "schema.audio_intent" for check in result["checks"])
    assert any(check["name"] == "ffmpeg" for check in result["checks"])
    assert "generate --mode library_reuse" in result["commands"]["makeBatch"]
    assert result["commands"]["checkContentForge"].endswith(" build")
    assert result["commands"]["startCampaignFactory"].startswith(
        "uv run --package campaign-factory campaign-factory serve"
    )
    assert result["commands"]["exportReferencePatterns"].startswith(
        "uv run --package reference-factory python -m reference_factory.cli"
    )
    assert result["commands"]["makeBatch"].startswith(
        f"{CREATOR_OS_ROOT / 'scripts' / 'creator-os'} generate --mode library_reuse --apply"
    )
    assert "cd " not in "\n".join(result["commands"].values())


def test_contract_schema_examples_validate():
    checks = validate_schema_examples()
    assert {check["name"] for check in checks} == {
        "account_eligibility_decision.v1.example.json",
        "audio_intent.v1.example.json",
        "assignment_eligibility.v1.example.json",
        "audio_catalog_export.v1.example.json",
        "campaign_draft_payload.v1.example.json",
        "campaign_draft_payload.v2.example.json",
        "caption_outcome_context.v1.example.json",
        "creative_plan.v1.example.json",
        "front_generation_plan.v1.example.json",
        "generated_asset_lineage.v1.example.json",
        "generated_asset_lineage.v2.example.json",
        "generation_execution_plan.v1.example.json",
        "generation_worker_lineage.v1.example.json",
        "higgsfield_soul_image_prompt.v1.example.json",
        "kling_3_video_prompt.v1.example.json",
        "motion_edit_render.v1.example.json",
        "performance_sync.v1.example.json",
        "post_metric_history.read.v1.example.json",
        "pattern_card.v1.example.json",
        "provider_spend_authorization.v1.example.json",
        "repurposing_plan.v1.example.json",
        "recommendation_accuracy_report.v1.example.json",
        "recommendation_next_batch.v1.example.json",
        "reference_video_motion_analysis.v1.example.json",
        "reference_video_remix_plan.v1.example.json",
        "reference_factory_knowledge_pack.v1.example.json",
        "threadsdash_handshake.v1.example.json",
        "variant_assignment.v1.example.json",
        "video_analysis.v1.example.json",
    }
    assert {check["status"] for check in checks} == {"ok"}


def test_contentforge_smoke_contract_rejects_malformed_response():
    bad = dict(CONTENTFORGE_SMOKE_RESPONSE)
    bad["overallVerdict"] = "maybe"

    try:
        assert_contentforge_contract_response(bad)
    except AssertionError as exc:
        assert "unexpected ContentForge verdict" in str(exc)
    else:
        raise AssertionError("malformed ContentForge response passed smoke validation")


def test_make_batch_returns_compact_operator_summary(tmp_path: Path, monkeypatch):
    bank_path = tmp_path / "campaign_reference_bank.json"
    bank_path.write_text(
        json.dumps(
            {
                "schema": "reference_factory.campaign_reference_bank.v1",
                "clusters": [
                    {
                        "clusterRank": 1,
                        "clusterKey": "caption_led_visual::direct_response::question_hook",
                        "label": "caption led visual / direct response / question hook",
                        "visualFormat": "caption_led_visual",
                        "hookType": "direct_response",
                        "captionArchetype": "question_hook",
                        "captionFormulas": [
                            {
                                "formula": "{direct question}?",
                                "exampleCaptions": ["red or pink ?"],
                            }
                        ],
                        "suggestedVariantRecipes": ["v01_original", "v05_hflip"],
                    }
                ],
            }
        )
    )
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    cf = make_factory(tmp_path)
    try:
        cf.domains.reference.import_reference_bank(bank_path)
        run_kwargs = {}

        def fake_run_reel(**kwargs):
            run_kwargs.update(kwargs)
            return {
                "returncode": 0,
                "runs": [{"renderJobId": "job_1"}],
                "elapsed_seconds": 1.23,
            }

        monkeypatch.setattr(
            cf.domains.reel_execution, "run_reel_factory", fake_run_reel
        )
        monkeypatch.setattr(
            cf.domains.reel_execution,
            "sync_reel_outputs",
            lambda **kwargs: {
                "synced": [{"id": "asset_1"}],
            },
        )
        monkeypatch.setattr(
            contentforge_adapter,
            "audit_campaign",
            lambda *args, **kwargs: {
                "reports": [
                    {
                        "overallVerdict": "warn",
                        "warnings": ["review"],
                        "failedChecks": [],
                    }
                ],
            },
        )

        result = cf.domains.make_batch_repo.make_batch(
            folder=folder,
            campaign_slug="batch",
            model_slug="model",
            variant_count=1,
            user_id=None,
            recipes=None,
        )
        assert result["import"]["importedCount"] == 1
        assert (
            result["referenceSelection"]["clusterKey"]
            == "caption_led_visual::direct_response::question_hook"
        )
        assert result["referenceSelection"]["recipes"] == ["v01_original", "v05_hflip"]
        assert result["prepare"]["preparedCount"] == 1
        assert result["run"]["runCount"] == 1
        assert result["sync"]["syncedCount"] == 1
        assert result["audit"]["reportCount"] == 1
        assert "reports" not in result["audit"]
        assert "runs" not in result["run"]
        assert run_kwargs["max_outputs_per_clip"] == 1
    finally:
        cf.close()


def test_generation_modes_cli_lists_all_operator_paths(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "campaign_factory.cli", "generation", "modes"],
        cwd=PACKAGE_ROOT,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_ROOT": str(tmp_path),
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
            "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
            "REEL_FACTORY_ROOT": str(tmp_path / "reel_factory"),
            "CONTENTFORGE_ROOT": str(tmp_path / "contentforge"),
            "THREADSDASH_ROOT": str(tmp_path / "ThreadsDashboard"),
        },
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [mode["id"] for mode in payload["modes"]] == [
        "library_reuse",
        "soul_static",
        "motion_edit",
        "best_only_kling",
        "reference_video_remix",
    ]


def test_motion_edit_cli_dry_run_returns_valid_render_without_db_mutation(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
    finally:
        cf.close()
    from PIL import Image

    still_path = tmp_path / "still.png"
    Image.new("RGB", (1080, 1920), color=(20, 40, 80)).save(still_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "generation",
            "run",
            "--mode",
            "motion_edit",
            "--campaign",
            "may",
            "--accepted-still",
            str(still_path),
            "--caption",
            "CLI dry run caption",
            "--duration",
            "5",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
            "CAMPAIGN_FACTORY_ROOT": str(tmp_path),
            "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
            "REEL_FACTORY_ROOT": str(
                MONOREPO_ROOT / "python_packages" / "reel_factory"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "motion_edit"
    assert payload["publishingAllowed"] is False
    motion = payload["result"]["motionEdit"]
    static = payload["result"]["staticFallback"]
    validate_motion_edit_render(motion["render"])
    assert motion["registeredAsset"] is None
    assert static["paidGeneration"] is False
    assert static["render"]["audioBurned"] is False
    conn = sqlite3.connect(tmp_path / "campaign_factory.sqlite")
    try:
        assert conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0] == 0
    finally:
        conn.close()


def test_variation_cli_dry_run_creates_assignment_manifest(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "variation",
            "run",
            "--campaign",
            "may",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
            "CAMPAIGN_FACTORY_ROOT": str(tmp_path),
            "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
        },
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assignment_path = Path(payload["assignments"][0]["assignmentPath"])
    validate_variant_assignment(json.loads(assignment_path.read_text(encoding="utf-8")))


def test_contentforge_cli_audit_handles_runner_unavailable(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(
        base_url, *, source, target_file=None, audit_profile=None, layers
    ):
        raise RuntimeError("ContentForge is unavailable")

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["status"] == "needs_review"
        assert "contentforge_cli" in report["failedChecks"]
        assert report["error"] == "ContentForge is unavailable"
        assert "contentforge_cli: ContentForge is unavailable" in report["warnings"]
        assert report["overallVerdict"] == "fail"
    finally:
        cf.close()


def test_dashboard_returns_latest_audit_and_readiness(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        audit = add_audit_report(cf, warnings=["compression"], overall_verdict="warn")
        report_path = Path(audit["path"])
        report_payload = json.loads(report_path.read_text())
        report_payload["creativeQuality"] = {
            "semanticEngine": "heuristic_v1",
            "modelBacked": False,
            "score": 72,
            "hookClarity": {
                "score": 80,
                "level": "strong",
                "text": "just cracked you in my head",
            },
            "visualClarity": {"score": 68, "level": "medium"},
            "openingStrength": {"score": 70, "level": "medium"},
            "subjectVisibility": {"score": 64, "level": "medium"},
            "warnings": [{"code": "creative_hook_generic", "label": "Generic hook"}],
        }
        report_path.write_text(json.dumps(report_payload), encoding="utf-8")
        dashboard = cf.domains.campaign_overview.dashboard("may")
        asset = dashboard["rendered"][0]
        assert asset["latest_audit"]["id"] == "audit_1"
        assert asset["latest_audit"]["overallVerdict"] == "warn"
        assert asset["latest_audit"]["readinessSummary"]["uploadReady"] is True
        assert (
            asset["latest_audit"]["creativeQuality"]["semanticEngine"] == "heuristic_v1"
        )
        assert asset["latest_audit"]["creativeQuality"]["score"] == 72
        assert asset["latest_audit"]["creativeQuality"]["hookClarity"]["score"] == 80
        assert asset["export_readiness"]["state"] == "blocked"
        assert "review_state:draft" in asset["export_readiness"]["blockingReasons"]
    finally:
        cf.close()


def test_dashboard_defaults_to_campaign_with_rendered_assets(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        empty_folder = tmp_path / "empty_inputs"
        empty_folder.mkdir()
        (empty_folder / "empty.mp4").write_bytes(b"empty")
        cf.domains.asset_import.import_folder(
            empty_folder, campaign_slug="new_empty", model_slug="model"
        )
        add_rendered_asset(cf, tmp_path, campaign_slug="with_assets")
        dashboard = cf.domains.campaign_overview.dashboard()
        assert dashboard["campaign"]["slug"] == "with_assets"
        assert len(dashboard["rendered"]) == 1
    finally:
        cf.close()


def test_media_route_refuses_unknown_asset(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    cf.close()
    monkeypatch.setattr(app_module, "settings", cf.settings)
    client = TestClient(app_module.app)
    response = client.get("/api/rendered/missing/media")
    assert response.status_code == 404


def test_publishability_maps_unbounded_trust_statuses_to_contract_blockers(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        audit = add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        audit_path = Path(audit["path"])
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        payload["readinessSummary"]["visualQcStatus"] = "pending"
        payload["readinessSummary"]["identityVerificationStatus"] = "provider_error"
        audit_path.write_text(json.dumps(payload), encoding="utf-8")

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["visualQcStatus"] == "pending"
        assert explanation["identityVerificationStatus"] == "provider_error"
        assert "visual_qc_unavailable" in explanation["publishability_failure_reasons"]
        assert (
            "identity_verification_failed"
            in explanation["publishability_failure_reasons"]
        )
        assert "visual_qc_pending" not in explanation["publishability_failure_reasons"]
        assert (
            "identity_verification_provider_error"
            not in explanation["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_caption_quality_repair_plan_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "DM me for the link",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "caption-quality-repair-plan",
            "--creator",
            "Test",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.caption_quality_repair_plan.v1"
    assert payload["blockedByCaptionQuality"] == 1
    assert payload["replacementCandidates"][0]["wouldWrite"] is False
    assert payload["wouldWrite"] is False


def test_inventory_recovery_report_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "DM me for the link",
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "inventory-recovery-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "3",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.inventory_recovery_report.v1"
    assert payload["successCriteria"]["whyAssetsAreBlocked"] is True
    assert payload["repairClasses"]
    assert payload["wouldWrite"] is False


def test_schedule_safe_production_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "schedule-safe-production-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.schedule_safe_production_report.v1"
    assert payload["requiredFor25Accounts"] == 225
    assert payload["currentInventory"] == 11
    assert payload["wouldWrite"] is False


def test_contentforge_visual_qc_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "contentforge-visual-qc-master-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--current-inventory",
            "11",
            "--required-inventory",
            "225",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.contentforge_visual_qc_master_report.v1"
    assert payload["recoveryProjection"]["currentScheduleSafeAssets"] == 11
    assert payload["recoveryProjection"]["requiredFor25Accounts"] == 225
    assert payload["wouldWrite"] is False


def test_multi_blocker_inventory_unlock_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "inventory-unlock-master-report",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.inventory_unlock_master_report.v1"
    assert payload["currentScheduleSafeAssets"] == 11
    assert payload["requiredFor25Accounts"] == 225
    assert payload["wouldWrite"] is False


def test_operator_inventory_review_batch_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "operator-inventory-review-batch-summary",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
            "--target-unlock",
            "10",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.operator_inventory_review_batch_summary.v1"
    assert payload["targetUnlock"] == 10
    assert payload["safeRepairsOnly"] is True
    assert payload["wouldWrite"] is False


def test_operator_review_simulator_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "operator-review-minimum-certification-path",
            "--creator",
            "Test",
            "--content-surface",
            "reel",
            "--required-inventory",
            "225",
            "--current-inventory",
            "11",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert (
        payload["schema"] == "creator_os.operator_review_minimum_certification_path.v1"
    )
    assert "minimumOperatorMinutesToPass25Gate" in payload
    assert payload["wouldWrite"] is False


def test_fresh_schedule_safe_production_plan_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "fresh-schedule-safe-production-plan",
            "--creator",
            "Stacey",
            "--current-inventory",
            "11",
            "--target-schedule-safe-inventory",
            "270",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.fresh_schedule_safe_production_plan.v1"
    assert payload["freshScheduleSafeAssetsNeeded"] == 259
    assert payload["parentsNeeded"] == 26
    assert payload["wouldWrite"] is False


def test_generate_variants_cli_failure_is_retry_safe_and_commits_no_variants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        cf.domains.variant_lineage.register_parent_reel("asset_1", operator="tester")
        monkeypatch.setattr(
            variant_lineage_module,
            "run_contentforge",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("busy")),
        )

        result = cf.domains.variant_lineage.generate_variants(
            parent_asset_id="asset_1",
            count=1,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            contentforge_timeout_seconds=1,
        )

        assert result["status"] == "blocked"
        assert result["blockingReason"] == "contentforge_variant_pack_cli_error"
        assert result["retryOrResumeSafe"] is True
        assert result["partialCommitPrevented"] is True
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'"
            ).fetchone()[0]
            == 0
        )
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_discoverability_safe_contract_blocks_dm_link_and_off_platform_language(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.discoverability.discoverability_safe_content_contract(
            "DM me",
            "link in bio",
            "Snap me",
            "subscribe here",
            "normal caption of the day",
        )

        assert result["discoverabilitySafe"] is False
        assert (
            result["blockedReason"]
            == "discoverability_risk_link_dm_or_off_platform_reference"
        )
        assert {item["reason"] for item in result["blockedTerms"]} == {
            "dm_reference",
            "link_reference",
            "off_platform_reference",
            "subscription_cta",
        }
        assert result["wouldWrite"] is False
    finally:
        cf.close()


def test_discoverability_safe_contract_does_not_block_common_word_of(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.discoverability.discoverability_safe_content_contract(
            "photo of the day"
        )

        assert result["discoverabilitySafe"] is True
        assert result["blockedTerms"] == []
    finally:
        cf.close()


def test_multi_surface_inventory_audit_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_cli",
            content_surface="feed_single",
            media_type="image",
        )
    finally:
        cf.close()

    env = {
        **os.environ,
        "PYTHONPATH": CLI_PYTHONPATH,
        "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        "REEL_FACTORY_ROOT": str(tmp_path / "reel_factory"),
        "CONTENTFORGE_ROOT": str(tmp_path / "contentforge"),
        "THREADSDASH_ROOT": str(tmp_path / "ThreadsDashboard"),
        "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "multi-surface-inventory-audit",
            "--creator",
            "Stacey",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.multi_surface_inventory_audit.v1"
    assert payload["inventoryBySurface"]["feed_single"]["total"] == 1
    assert payload["wouldWrite"] is False


def test_creator_os_lifecycle_dashboard_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "lifecycle-dashboard",
            "--campaign",
            "may",
            "--include-threadsdash",
            "off",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.lifecycle_dashboard.v1"
    assert payload["counts"]["approved"] == 1
    assert payload["wouldWrite"] is False


def test_lifecycle_report_cli_outputs_json_and_filters_state(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        _approve_asset_for_lifecycle(cf, tmp_path)
    finally:
        cf.close()

    env = {
        **os.environ,
        "PYTHONPATH": CLI_PYTHONPATH,
        "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        "REEL_FACTORY_ROOT": str(tmp_path / "reel_factory"),
        "CONTENTFORGE_ROOT": str(tmp_path / "contentforge"),
        "THREADSDASH_ROOT": str(tmp_path / "ThreadsDashboard"),
        "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "lifecycle-report",
            "--campaign",
            "may",
            "--include-threadsdash",
            "off",
            "--state",
            "creative_approved",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.lifecycle_report.v1"
    assert payload["summary"]["stateCounts"] == {"creative_approved": 1}
    assert payload["rows"][0]["currentState"] == "creative_approved"


def test_dashboard_returns_performance_fields(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        campaign_id = cf.domains.campaign_by_slug("may")["id"]
        cf.conn.execute(
            """
            INSERT INTO performance_snapshots
            (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
             caption_hash, recipe, post_id, platform, status, account_id, instagram_account_id,
             published_at, snapshot_at, views, likes, comments, shares, saves, reach,
             watch_time_seconds, raw_json, created_at, metrics_eligible, history_source,
             lineage_v2_valid)
            VALUES
            ('perf_1', ?, 'asset_1', ?, 'hash_1', 'source_hash_1',
             ?, 'v01_original', 'post_1', 'instagram', 'published', NULL, 'ig_1',
             '2026-01-02T00:00:00+00:00', '2026-01-03T00:00:00+00:00', 500, 40, 3, 7, 9, 450,
             100.0, '{}', '2026-01-03T00:00:00+00:00', 1, 'metric_history', 1)
            """,
            (
                campaign_id,
                cf.domains.rendered_asset("asset_1")["source_asset_id"],
                threadsdash_client_adapter._text_hash("caption"),
            ),
        )
        cf.conn.commit()
        asset = cf.domains.campaign_overview.dashboard("may")["rendered"][0]
        assert asset["latestPerformance"]["metrics"]["views"] == 500
        assert asset["sourcePerformance"]["count"] == 1
        assert asset["captionPerformance"]["count"] == 1
        assert asset["recipePerformance"]["count"] == 1
        assert asset["performanceScore"] is not None
    finally:
        cf.close()


def test_performance_api_endpoints_sync_and_summarize(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    rows = []
    history_rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            if table == "post_metric_history":
                offset = int(params.get("offset", 0))
                limit = int(params.get("limit", len(history_rows)))
                return history_rows[offset : offset + limit]
            assert table == "posts"
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", len(rows)))
            return rows[offset : offset + limit]

    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        rows.append(
            {
                "id": "post_api_1",
                "status": "published",
                "platform": "instagram",
                "instagram_account_id": "ig_1",
                "created_at": "2026-01-02T00:00:00+00:00",
                "published_at": "2026-01-02T01:00:00+00:00",
                "views_count": 111,
                "ig_impressions": 444,
                "ig_reach": 200,
                "metadata": {
                    "campaign_factory": threadsdash_campaign_factory_metadata(source),
                    "insights": {"likes": 5, "shares": 1, "saves": 2},
                },
            }
        )
        history_rows.append(
            {
                "id": "hist_api_1",
                "post_id": "post_api_1",
                "account_id": "acct_1",
                "platform": "instagram",
                "snapshot_at": "2026-01-03T01:00:00+00:00",
                "hours_since_publish": 24,
                "views_count": 333,
                "likes_count": 21,
                "replies_count": 3,
                "reposts_count": 0,
                "quotes_count": 0,
                "shares_count": 4,
                "saves_count": 6,
                "reach": 400,
                "engagement_rate": 0.113,
                "created_at": "2026-01-03T01:00:00+00:00",
            }
        )
    finally:
        cf.close()

    client = TestClient(app_module.app)
    sync = client.post(
        "/api/sync-performance",
        json={
            "campaign": "may",
            "userId": "user_1",
            "supabaseUrl": "https://example.supabase.co",
            "supabaseServiceRoleKey": "service-role",
        },
    )
    assert sync.status_code == 200
    assert sync.json()["inserted"] == 1
    summary = client.get("/api/performance-summary", params={"campaign": "may"})
    assert summary.status_code == 200
    data = summary.json()
    assert data["renderedAssets"]["asset_1"]["totals"]["views"] == 333
    assert data["renderedAssets"]["asset_1"]["totals"]["impressions"] == 444
    assert data["renderedAssets"]["asset_1"]["totals"]["reach"] == 400
    assert data["captionHashes"]["caption_hash_1"]["totals"]["likes"] == 21


def test_activity_and_jobs_api_return_newest_first(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        campaign = cf.domains.models.upsert_campaign("may", "model")
        older = cf.domains.events.create_pipeline_job(
            "import_folder", campaign["id"], {}
        )
        newer = cf.domains.events.create_pipeline_job(
            "prepare_reel", campaign["id"], {}
        )
        cf.domains.events.record_event(
            "source_imported",
            campaign_id=campaign["id"],
            pipeline_job_id=older["id"],
            message="older",
        )
        cf.domains.events.record_event(
            "reel_inputs_prepared",
            campaign_id=campaign["id"],
            pipeline_job_id=newer["id"],
            message="newer",
        )
    finally:
        cf.close()

    monkeypatch.setattr(app_module, "settings", settings)
    client = TestClient(app_module.app)
    activity = client.get("/api/activity-log", params={"campaign": "may", "limit": 10})
    assert activity.status_code == 200
    assert activity.json()["events"][0]["message"] == "newer"
    jobs = client.get("/api/jobs", params={"campaign": "may", "limit": 10})
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["id"] == newer["id"]
    job = client.get(f"/api/jobs/{newer['id']}")
    assert job.status_code == 200
    assert job.json()["jobType"] == "prepare_reel"


def test_account_plan_warns_on_batch_volume_and_api_assigns(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    settings = cf.settings
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        for idx in (2, 3):
            rendered_path = tmp_path / f"asset_{idx}.mp4"
            rendered_path.write_bytes(f"rendered {idx}".encode())
            cf.conn.execute(
                """
                INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'caption', 'v01_original', 'approved_candidate', 'approved', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """,
                (
                    f"asset_{idx}",
                    source["campaign_id"],
                    source["id"],
                    f"hash_{idx}",
                    str(rendered_path),
                    str(rendered_path),
                    rendered_path.name,
                ),
            )
            cf.conn.commit()
            add_audit_report(
                cf, rendered_asset_id=f"asset_{idx}", audit_id=f"audit_{idx}"
            )
            cf.domains.campaign_overview.assign_asset_account(
                f"asset_{idx}", instagram_account_id="ig_shared"
            )
        cf.domains.campaign_overview.assign_asset_account(
            "asset_1", instagram_account_id="ig_shared"
        )
        plan = cf.domains.account_planning.account_plan("may", user_id="user_1")
        assert len(plan["rows"]) == 3
        assert "account_batch_volume_review" in plan["warnings"]
    finally:
        cf.close()

    monkeypatch.setattr(app_module, "settings", settings)
    client = TestClient(app_module.app)
    response = client.post(
        "/api/asset-account-assignment",
        json={
            "renderedAssetId": "asset_1",
            "instagramAccountId": "ig_extra",
        },
    )
    assert response.status_code == 400
    assert "reuse_window" in response.json()["detail"]
    account_plan = client.get(
        "/api/account-plan", params={"campaign": "may", "userId": "user_1"}
    )
    assert account_plan.status_code == 200
    assert not any(
        row["instagramAccountId"] == "ig_extra" for row in account_plan.json()["rows"]
    )


def test_creator_os_daily_plan_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    schedule_path = tmp_path / "schedule_plan.json"
    report_path.write_text(
        json.dumps(
            _manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_cli",
                        "username": "cli",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    },
                ]
            )
        ),
        encoding="utf-8",
    )
    schedule_path.write_text(
        json.dumps(
            {
                "creator": "Stacey",
                "validatedDraftsAvailable": 1,
                "items": [_draft_item("post_cli", "ig_cli")],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "daily-plan",
            "--creator",
            "Stacey",
            "--threadsdash-report-json",
            str(report_path),
            "--schedule-plan-json",
            str(schedule_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.daily_plan.v1"
    assert payload["wouldWrite"] is False
    assert payload["creators"][0]["accountsNeedingPostsToday"] == 1
    assert payload["accounts"][0]["eligibleDrafts"][0]["draftPostId"] == "post_cli"


def test_recommended_inventory_request_plan_cli_outputs_json(tmp_path: Path):
    daily_path = tmp_path / "daily_plan.json"
    inventory_path = tmp_path / "variant_inventory_plan.json"
    daily_path.write_text(
        json.dumps(
            {
                "schema": "creator_os.daily_plan.v1",
                "creators": [
                    {
                        "creator": "Stacey",
                        "inventoryShortfall": 3,
                        "recommendedInventory": [
                            {
                                "sourceSystem": "campaign_factory.creative_performance_analysis",
                                "surface": "reel",
                                "reason": "mirror_selfie is above creator baseline.",
                                "confidence": "low",
                                "conceptId": "mirror_selfie",
                                "captionAngle": "tease",
                                "postingWindow": "6pm",
                                "audioId": "audio_12",
                                "storyIntent": "",
                                "parentAssetId": "asset_parent_cli",
                                "scoreLiftPct": 20,
                                "wouldWrite": False,
                            }
                        ],
                    }
                ],
                "wouldWrite": False,
            }
        ),
        encoding="utf-8",
    )
    inventory_path.write_text(
        json.dumps(
            {
                "schema": "campaign_factory.variant_inventory_plan.v1",
                "executionBatches": [
                    {
                        "parentAssetId": "asset_parent_cli",
                        "requestedVariants": 3,
                        "preset": "caption_safe_v2",
                        "operationFamilies": ["cover_frame"],
                    }
                ],
                "wouldWrite": False,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "recommended-inventory-request-plan",
            "--creator",
            "Stacey",
            "--target-count",
            "3",
            "--daily-plan-json",
            str(daily_path),
            "--variant-inventory-plan-json",
            str(inventory_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.recommended_inventory_request_plan.v1"
    assert payload["requestBatches"][0]["recommendedAction"] == "create_more_reels"
    assert payload["requestBatches"][0]["parentAssetId"] == "asset_parent_cli"
    assert payload["canSatisfyFromExistingInventory"] is True
    assert payload["wouldWrite"] is False


def test_creator_os_account_tiers_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    report_path.write_text(
        json.dumps(
            _manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_cli",
                        "username": "cli",
                        "creator": "Stacey",
                        "safeToSchedule": True,
                        "accountTier": "growth",
                    },
                ]
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "account-tiers",
            "--creator",
            "Stacey",
            "--threadsdash-report-json",
            str(report_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.account_tiers.v1"
    assert payload["tierSummary"]["growth"] == 1
    assert payload["wouldWrite"] is False


def test_creator_os_account_health_report_cli_outputs_json(tmp_path: Path):
    report_path = tmp_path / "threadsdash_report.json"
    report_path.write_text(
        json.dumps(
            _manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_cli",
                        "username": "cli",
                        "creator": "Stacey",
                        "linkSharingRestricted": True,
                    },
                ]
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "account-health-report",
            "--creator",
            "Stacey",
            "--threadsdash-report-json",
            str(report_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.account_health_report.v1"
    assert payload["accounts"][0]["safeToSchedule"] is False
    assert payload["wouldWrite"] is False


def test_creator_os_surface_report_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        model = cf.domains.models.upsert_model("stacey", name="Stacey")
        account = cf.domains.models.upsert_account(
            "stacey_cli",
            platform="instagram",
            external_id="ig_cli",
            model_id=model["id"],
        )
        add_account_requirement_fixture(
            cf, account_id=account["id"], surface="feed_single", max_per_day=1
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "creator-surface-summary",
            "--creator",
            "Stacey",
            "--date",
            "2026-06-06",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.creator_surface_summary.v1"
    assert payload["totalsBySurface"]["feed_single"]["remaining"] == 1
    assert payload["wouldWrite"] is False


def test_creator_os_draft_inventory_gap_cli_outputs_json(tmp_path: Path):
    schedule_path = tmp_path / "schedule_plan.json"
    schedule_path.write_text(
        json.dumps(
            {
                "schema": "threadsdashboard.campaign_schedule_plan.v1",
                "items": [_draft_item("post_cli", "ig_cli", instagram_post_caption="")],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "draft-inventory-gap",
            "--creator",
            "Stacey",
            "--schedule-plan-json",
            str(schedule_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.draft_inventory_gap.v1"
    assert (
        payload["validatedButNotScheduleSafe"][0]["reason"]
        == "missing_instagram_post_caption"
    )
    assert payload["wouldWrite"] is False


def test_creative_knowledge_base_cli_outputs_read_only_report(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        campaign = cf.domains.models.upsert_campaign("stacey_creative_cli", "stacey")
        _insert_creative_kb_snapshot(
            cf,
            snapshot_id="perf_kb_cli",
            campaign_id=campaign["id"],
            post_id="post_cli",
            caption_angle="tease",
            audio_id="audio_12",
            views=500,
            reach=400,
            saves=10,
            shares=5,
            followers=1,
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "creative-knowledge-base",
            "--creator",
            "Stacey",
            "--campaign",
            campaign["slug"],
            "--minimum-sample-size",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
            "CAMPAIGN_FACTORY_CAMPAIGNS": str(tmp_path / "campaigns"),
        },
    )
    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.creative_knowledge_base.v1"
    assert payload["topAudioIds"][0]["key"] == "audio_12"
    assert payload["wouldWrite"] is False


def test_creator_os_execution_readiness_cli_outputs_json(tmp_path: Path):
    threadsdash_root = tmp_path / "ThreadsDashboard"
    (threadsdash_root / "api" / "cron").mkdir(parents=True)
    (threadsdash_root / "api" / "scheduled-post-publish.ts").write_text(
        "export default function handler() {}\n", encoding="utf-8"
    )
    (threadsdash_root / "api" / "cron" / "_campaign-schedule-recovery.ts").write_text(
        "export default function handler() {}\n", encoding="utf-8"
    )
    (threadsdash_root / "api" / "cron" / "[job].ts").write_text(
        'export const jobs = {"campaign-schedule-recovery": () => null};\n',
        encoding="utf-8",
    )
    (threadsdash_root / "vercel.json").write_text(
        '{"crons":[{"path":"/api/cron/campaign-schedule-recovery"}]}\n',
        encoding="utf-8",
    )
    report_path = tmp_path / "threadsdash_report.json"
    schedule_path = tmp_path / "schedule_plan.json"
    time_path = tmp_path / "time_plan.json"
    report_path.write_text(
        json.dumps(
            _manager_report_fixture(
                accounts=[
                    {
                        "accountId": "ig_cli",
                        "username": "cli",
                        "creator": "Stacey",
                        "bucket": "safe_to_schedule_today",
                        "safeToSchedule": True,
                        "needsPostToday": True,
                    },
                ]
            )
        ),
        encoding="utf-8",
    )
    item = _draft_item("post_cli", "ig_cli", scheduled_for="2026-06-06T16:00:00+00:00")
    schedule_path.write_text(
        json.dumps(
            {
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [item],
            }
        ),
        encoding="utf-8",
    )
    time_path.write_text(
        json.dumps(
            {
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "items": [item],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "execution-readiness",
            "--creator",
            "Stacey",
            "--requested-count",
            "1",
            "--threadsdash-report-json",
            str(report_path),
            "--schedule-plan-json",
            str(schedule_path),
            "--time-plan-json",
            str(time_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
            "THREADSDASH_ROOT": str(threadsdash_root),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.execution_readiness.v1"
    assert payload["managerDecision"] == "ready_to_schedule"
    assert payload["wouldWrite"] is False


def test_creator_os_9_5_readiness_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "creator-os-9.5-readiness-report",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.9_5_readiness_report.v1"
    assert payload["wouldWrite"] is False
    assert len(payload["top10RemainingRisks"]) == 10


def test_inventory_factory_master_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "inventory-factory-master-report",
            "--available-inventory",
            "1800",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.inventory_factory_master_report.v1"
    assert payload["wouldWrite"] is False
    assert (
        payload["requirementsFor200Accounts"]["requiredInventoryBuffer"]
        == "1800 schedule-safe drafts"
    )


def test_reel_factory_master_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "reel-factory-master-report",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "creator_os.reel_factory_master_report.v1"
    assert payload["finalVerdict"]["requiredParentsPerDay"] == 53
    assert payload["wouldWrite"] is False


def test_parent_factory_53_parent_trial_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "parent-factory-53-parent-trial",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["schema"] == "creator_os.parent_factory_53_parent_trial.v1"
    assert payload["targetParents"] == 53
    assert payload["trialPassed"] is False
    assert payload["limitingStep"] == "discoverability_safety_pass"
    assert payload["wouldWrite"] is False


def test_parent_factory_post_gate_fresh_batch_proof_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "parent-factory-post-gate-fresh-batch-proof",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": CLI_PYTHONPATH},
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert (
        payload["schema"] == "creator_os.parent_factory_post_gate_fresh_batch_proof.v1"
    )
    assert payload["freshBatch"] is True
    assert payload["lateDiscoverabilityFailures"] == 0
    assert payload["blockedBeforeRender"] > 0
    assert payload["renderJobsAvoided"] > 0
    assert payload["targetParentsReached"] is True
    assert payload["wouldWrite"] is False


def test_parent_factory_master_optimization_report_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "parent-factory-master-optimization-report",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert (
        payload["schema"] == "creator_os.parent_factory_master_optimization_report.v1"
    )
    assert payload["acceptanceCriteria"]["whatSingleFixImprovesYieldMost"]
    assert payload["wouldWrite"] is False


def test_parent_factory_discoverability_loss_analysis_cli_outputs_json(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "parent-factory-discoverability-loss-analysis",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "cli.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert (
        payload["schema"]
        == "creator_os.parent_factory_discoverability_loss_analysis.v1"
    )
    assert payload["discoverabilityRejectionCategories"]
    assert payload["wouldWrite"] is False


def test_capture_publishability_rejection_evidence_cli_outputs_json(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me",
                json.dumps(
                    {
                        "caption_text": "DM me",
                        "burned_caption_text": "DM me",
                        "instagram_post_caption": "DM me",
                        "captionPlacementDecision": {"status": "passed"},
                    }
                ),
            ),
        )
        cf.conn.commit()
    finally:
        cf.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "capture-publishability-rejection-evidence",
            "--asset-id",
            "asset_1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": CLI_PYTHONPATH,
            "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "campaign_factory.rejection_evidence_capture.v1"
    assert payload["capturedCount"] >= 1
    assert payload["wouldWrite"] is True


def test_export_threadsdash_cli_live_missing_credentials_fails_loud(
    tmp_path: Path,
) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": CLI_PYTHONPATH,
        "CAMPAIGN_FACTORY_DB": str(tmp_path / "campaign_factory.sqlite"),
    }
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "export-threadsdash",
            "--campaign",
            "may",
            "--user-id",
            "user_1",
        ],
        cwd=PACKAGE_ROOT,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )

    assert result.returncode != 0
    assert "live ThreadsDashboard export requested" in result.stderr
