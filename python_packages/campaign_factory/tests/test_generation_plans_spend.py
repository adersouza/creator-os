from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import campaign_factory.daily_library_production as daily_library_module
import campaign_factory.variant_lineage as variant_lineage_module
import pytest
from campaign_asset_test_support import add_audit_report, add_inventory_parent_fixture
from campaign_factory.adapters import contentforge as contentforge_adapter
from campaign_factory.adapters.contentforge import audit_campaign
from campaign_factory.contracts import (
    validate_front_generation_plan,
    validate_variant_assignment,
)
from campaign_factory.core import CampaignFactory
from campaign_factory.cost_tracker import ensure_cost_table, record_ai_cost
from campaign_factory.daily_library_production import run_daily_library_production
from campaign_factory.front_generation_stage import (
    ACCEPTED_STILL_PLACEHOLDER,
    run_front_generation_stage,
)
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.kling_selection_stage import (
    run_kling_selection_stage,
    validate_kling_selection_receipt,
)
from campaign_factory.learning_cohort import prepare_learning_cohort
from campaign_factory.motion_edit_stage import run_motion_edit_stage
from campaign_factory.pipeline_smoke import _run_mocked_generation_intake_smoke
from campaign_factory.static_mp4_stage import _duration_for_still, run_static_mp4_stage
from campaign_factory.variation_stage import (
    load_variant_assignment_index,
    run_variation_stage,
)
from campaign_generation_test_support import (
    FakeVariationPipeline,
    fake_front_generation_result,
    fake_static_mp4_render,
    write_fake_static_mp4_outputs,
)
from campaign_test_support import (
    add_rendered_asset,
    add_source_asset,
    isolate_account_groups,
    make_factory,
    set_test_source_prompt,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

MONOREPO_ROOT = Path(__file__).resolve().parents[3]

CLI_PYTHONPATH = os.pathsep.join(
    [
        str(PACKAGE_ROOT),
        str(MONOREPO_ROOT / "packages" / "pipeline_contracts"),
    ]
)


def patch_front_static_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_invoke(
        _factory,
        *,
        still_path: Path,
        output_path: Path,
        duration_seconds: float,
        dry_run: bool,
        allow_upscale: bool,
    ) -> dict:
        assert allow_upscale is False
        if not dry_run:
            write_fake_static_mp4_outputs(output_path)
            output_path.write_bytes(f"static:{still_path.name}".encode())
        return fake_static_mp4_render(still_path, output_path, dry_run=dry_run)

    monkeypatch.setattr(
        "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
        fake_invoke,
    )


def patch_front_variant_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "campaign_factory.front_generation_stage._invoke_generate_variant_spec",
        lambda _factory, _result: {
            "soul_id": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
            "cleaned_prompt": "A mirror selfie in a fitted black top.",
            "original": {
                "source": "reference_pass_result",
                "generation_required": False,
                "aspect_ratio": "3:4",
                "reference_media_id": "image_original_1",
            },
            "sexy": {
                "model": "soul_2",
                "soul_id": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
                "prompt": (
                    "A mirror selfie in a fitted black top, 19 years old, dark "
                    "hair, no tattoos, fuller chest with deeper cleavage."
                ),
                "aspect_ratio": "3:4",
                "generation_required": True,
                "reference_media_id": None,
                "text_only": True,
            },
            "provider_generation_count": 1,
        },
    )


def create_approved_static_candidates(
    cf: CampaignFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict], list[Path]]:
    add_source_asset(cf, tmp_path)

    def fake_invoke(
        _factory,
        *,
        still_path,
        output_path,
        duration_seconds,
        dry_run,
        allow_upscale,
    ):
        write_fake_static_mp4_outputs(output_path)
        output_path.write_bytes(f"static:{still_path.name}".encode())
        return fake_static_mp4_render(still_path, output_path, dry_run=dry_run)

    monkeypatch.setattr(
        "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
        fake_invoke,
    )
    stills = [tmp_path / "candidate-a.png", tmp_path / "candidate-b.png"]
    assets: list[dict] = []
    for index, still in enumerate(stills, start=1):
        still.write_bytes(f"accepted-still-{index}".encode())
        result = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=False,
            apply=True,
        )
        asset = result["registeredAsset"]
        add_audit_report(
            cf,
            rendered_asset_id=asset["id"],
            audit_id=f"audit_static_{index}",
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET audit_status = 'approved_candidate' WHERE id = ?",
            (asset["id"],),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset(
            asset["id"], decision="approved", require_safe_audit=True
        )
        assets.append(
            dict(
                cf.conn.execute(
                    "SELECT * FROM rendered_assets WHERE id = ?", (asset["id"],)
                ).fetchone()
            )
        )
    return assets, stills


def test_daily_library_plan_is_deterministic_and_zero_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "one.mp4").write_bytes(b"one")
    (folder / "two.mp4").write_bytes(b"two")
    monkeypatch.setattr(
        daily_library_module,
        "_verify_library_identity",
        lambda _factory, source: {
            "schema": "reel_factory.identity_verification.v1",
            "status": "passed",
            "sourceAssetId": source["id"],
        },
    )
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-07-12")
        cf.domains.asset_import.import_folder(
            folder,
            campaign_slug="stacey_learning_cohort_v1",
            model_slug="stacey",
            storage_mode="reference",
        )
        first = run_daily_library_production(cf, day_index=1, library_root=folder)
        second = run_daily_library_production(cf, day_index=1, library_root=folder)
        assert first["status"] == "planned"
        assert first["selections"] == second["selections"]
        assert len(first["selections"]) == 2
        assert len({item["sourceAssetId"] for item in first["selections"]}) == 2
        assert first["controls"] == {
            "providerCalls": 0,
            "creditsSpent": 0,
            "paidGenerationAllowed": False,
            "approvalActionsTaken": 0,
            "draftActionsTaken": 0,
            "scheduleActionsTaken": 0,
            "publishActionsTaken": 0,
            "humanApprovalRequired": True,
        }
        persisted = cf.conn.execute(
            """SELECT COUNT(*) AS count FROM learning_cohort_assignments
            WHERE source_asset_id IS NOT NULL"""
        ).fetchone()
        assert persisted["count"] == 0
    finally:
        cf.close()


def test_daily_library_apply_stops_at_review_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "one.mp4").write_bytes(b"one")
    (folder / "two.mp4").write_bytes(b"two")
    monkeypatch.setattr(
        daily_library_module,
        "_verify_library_identity",
        lambda _factory, source: {
            "schema": "reel_factory.identity_verification.v1",
            "status": "passed",
            "sourceAssetId": source["id"],
        },
    )

    def fake_run_reel_factory(**kwargs):
        runs = []
        for job_id in kwargs["render_job_ids"]:
            cf.conn.execute(
                "UPDATE render_jobs SET status = 'rendered' WHERE id = ?", (job_id,)
            )
            runs.append({"renderJobId": job_id, "returncode": 0})
        cf.conn.commit()
        assert kwargs.get("caption_mix") is None
        assert kwargs["creator_style_preset"] == "stacey_static_center"
        return {"returncode": 0, "runs": runs}

    def fake_sync_reel_outputs(**kwargs):
        campaign = cf.domains.campaign_by_slug(kwargs["campaign_slug"])
        synced = []
        for index, job_id in enumerate(kwargs["render_job_ids"]):
            job = cf.conn.execute(
                "SELECT * FROM render_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            asset_id = f"daily_asset_{index}"
            output = tmp_path / f"daily_{index}.mp4"
            output.write_bytes(b"rendered")
            cf.conn.execute(
                """INSERT INTO rendered_assets
                (id, campaign_id, source_asset_id, render_job_id, content_hash,
                 output_path, campaign_path, filename, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'now', 'now')""",
                (
                    asset_id,
                    campaign["id"],
                    job["source_asset_id"],
                    job_id,
                    f"daily_hash_{index}",
                    str(output),
                    str(output),
                    output.name,
                ),
            )
            synced.append({"id": asset_id})
        cf.conn.commit()
        return {"synced": synced}

    def fake_audit(_factory, **kwargs):
        return {
            "reports": [
                {
                    "renderedAssetId": asset_id,
                    "status": "approved_candidate",
                    "overallVerdict": "pass",
                    "failedChecks": [],
                    "warnings": [],
                    "error": None,
                    "readinessSummary": {
                        "uploadReady": True,
                        "blockingReasons": [],
                        "blockingCodes": [],
                    },
                }
                for asset_id in kwargs["rendered_asset_ids"]
            ]
        }

    monkeypatch.setattr(
        daily_library_module,
        "_daily_hooks",
        lambda *_args, **_kwargs: [{"text": "pick one"}, {"text": "be honest"}],
    )
    monkeypatch.setattr(
        cf.domains.reel_execution, "run_reel_factory", fake_run_reel_factory
    )
    monkeypatch.setattr(
        cf.domains.reel_execution, "sync_reel_outputs", fake_sync_reel_outputs
    )
    monkeypatch.setattr(daily_library_module, "audit_campaign", fake_audit)
    try:
        prepare_learning_cohort(cf.conn, start_date="2026-07-12")
        cf.domains.asset_import.import_folder(
            folder,
            campaign_slug="stacey_learning_cohort_v1",
            model_slug="stacey",
            storage_mode="reference",
        )
        result = run_daily_library_production(
            cf, day_index=1, library_root=folder, apply=True
        )
        assert result["status"] == "review_ready"
        assert len(result["reviewReady"]) == 2
        assert result["controls"]["approvalActionsTaken"] == 0
        assert result["controls"]["draftActionsTaken"] == 0
        states = cf.conn.execute(
            """SELECT generation_state, approval_state, schedule_state
            FROM learning_cohort_assignments WHERE day_index = 1"""
        ).fetchall()
        assert {row["generation_state"] for row in states} == {"review_ready"}
        assert {row["approval_state"] for row in states} == {"pending"}
        assert {row["schedule_state"] for row in states} == {"blocked_pending_approval"}
        rendered_metadata = [
            json.loads(row["metadata_json"])
            for row in cf.conn.execute(
                "SELECT metadata_json FROM rendered_assets ORDER BY id"
            ).fetchall()
        ]
        assert {item["identityVerificationStatus"] for item in rendered_metadata} == {
            "passed"
        }
        assert {item["visualQcStatus"] for item in rendered_metadata} == {"passed"}
        assert all(
            item["identityVerification"]["sourceAssetId"] for item in rendered_metadata
        )
        assert all(
            item["visualQc"]["source"] == "contentforge" for item in rendered_metadata
        )
    finally:
        cf.close()


def test_daily_library_warning_only_upload_ready_is_review_ready():
    assert daily_library_module._audit_is_review_ready(
        {
            "status": "needs_review",
            "overallVerdict": "warn",
            "failedChecks": [],
            "warnings": ["audio_review"],
            "error": None,
            "readinessSummary": {
                "uploadReady": True,
                "blockingReasons": [],
                "blockingCodes": [],
            },
        }
    )
    assert not daily_library_module._audit_is_review_ready(
        {
            "status": "needs_review",
            "overallVerdict": "fail",
            "failedChecks": ["caption_text_too_small"],
            "error": None,
            "readinessSummary": {"uploadReady": False},
        }
    )


def test_daily_library_identity_does_not_cache_provider_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    source = {
        "id": "src_1",
        "content_hash": "abc123",
        "stored_path": str(tmp_path / "clip.mp4"),
    }
    calls = 0

    def unavailable(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "schema": "reel_factory.identity_verification.v1",
                    "status": "unavailable",
                    "failureReason": "identity_provider_unavailable",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(daily_library_module.subprocess, "run", unavailable)
    try:
        daily_library_module._verify_library_identity(cf, source)
        daily_library_module._verify_library_identity(cf, source)
        assert calls == 2
        assert not list((tmp_path / ".cache" / "library_identity").glob("*.json"))
    finally:
        cf.close()


def test_ai_cost_source_event_key_is_idempotent(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "costs.sqlite")
    try:
        first_id = record_ai_cost(
            conn,
            provider="grok",
            operation="image_prompt",
            campaign_id="campaign_1",
            input_tokens=100,
            output_tokens=25,
            source_event_key="lineage:abc:grok:image_prompt",
        )
        second_id = record_ai_cost(
            conn,
            provider="grok",
            operation="image_prompt",
            campaign_id="campaign_1",
            input_tokens=100,
            output_tokens=25,
            source_event_key="lineage:abc:grok:image_prompt",
        )
        count = conn.execute("SELECT COUNT(*) FROM ai_cost_events").fetchone()[0]
    finally:
        conn.close()

    assert second_id == first_id
    assert count == 1


def test_ai_cost_table_migrates_source_event_key(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "legacy_costs.sqlite")
    try:
        conn.execute(
            """
            CREATE TABLE ai_cost_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                generations INTEGER,
                estimated_cost_usd REAL NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        ensure_cost_table(conn)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ai_cost_events)").fetchall()
        }
        record_ai_cost(
            conn,
            provider="higgsfield",
            operation="soul_grid",
            generations=1,
            source_event_key="lineage:def:higgsfield:soul_grid",
        )
        count = conn.execute("SELECT COUNT(*) FROM ai_cost_events").fetchone()[0]
    finally:
        conn.close()

    assert "source_event_key" in columns
    assert count == 1


def test_finished_video_lineage_cost_recorder_records_generation_costs_once(
    tmp_path: Path,
):
    factory = make_factory(tmp_path)
    lineage = {
        "schema": "reel_factory.lineage.v1",
        "campaign": "camp_1",
        "model": "grok-3-mini",
        "usage": {"input_tokens": 100, "output_tokens": 25},
        "generation": {"tool": "higgsfield_kling_cli", "modelProfile": "soul_grid"},
    }
    lineage_hash = hashlib.sha256(
        json.dumps(lineage, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()[:24]

    try:
        factory.domains.finished_video.record_lineage_costs(lineage)
        factory.domains.finished_video.record_lineage_costs(lineage)

        rows = [
            dict(row)
            for row in factory.conn.execute(
                """
                SELECT provider, operation, input_tokens, output_tokens, generations, source_event_key
                FROM ai_cost_events
                ORDER BY provider, operation
                """
            ).fetchall()
        ]
    finally:
        factory.conn.close()

    assert rows == [
        {
            "provider": "grok",
            "operation": "image_prompt",
            "input_tokens": 100,
            "output_tokens": 25,
            "generations": None,
            "source_event_key": f"lineage:{lineage_hash}:grok:image_prompt",
        },
        {
            "provider": "higgsfield",
            "operation": "soul_grid",
            "input_tokens": None,
            "output_tokens": None,
            "generations": 1,
            "source_event_key": f"lineage:{lineage_hash}:higgsfield:soul_grid",
        },
        {
            "provider": "kling",
            "operation": "video_animate",
            "input_tokens": None,
            "output_tokens": None,
            "generations": 1,
            "source_event_key": f"lineage:{lineage_hash}:kling:video_animate",
        },
    ]


def test_finished_video_lineage_cost_recorder_ensures_table_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    factory = make_factory(tmp_path)
    ensure_calls = []
    record_kwargs = []

    def fake_ensure(conn: sqlite3.Connection) -> None:
        ensure_calls.append(conn)

    def fake_record(conn: sqlite3.Connection, **kwargs: Any) -> str:
        record_kwargs.append(kwargs)
        return str(kwargs["source_event_key"])

    repo = factory.domains.finished_video
    monkeypatch.setattr(repo, "_ensure_cost_table", fake_ensure)
    monkeypatch.setattr(repo, "_record_ai_cost", fake_record)
    try:
        factory.domains.finished_video.record_lineage_costs(
            {
                "campaign": "camp_1",
                "usage": {"input_tokens": 100, "output_tokens": 25},
                "generation": {"tool": "higgsfield_kling_cli"},
            }
        )
    finally:
        factory.conn.close()

    assert len(ensure_calls) == 1
    assert len(record_kwargs) == 3
    assert {item["ensure_schema"] for item in record_kwargs} == {False}


def test_pipeline_full_smoke_mocked_generation_intake_preserves_lineage(tmp_path: Path):
    projects_root = tmp_path / "Projects"
    for repo in [
        "reel_factory",
        "contentforge",
        "reference_factory",
        "ThreadsDashboard",
    ]:
        (projects_root / repo).mkdir(parents=True)

    result = _run_mocked_generation_intake_smoke(
        projects_root=projects_root, workspace=tmp_path / "workspace"
    )

    assert result["ok"] is True
    checks = result["checks"]
    assert checks["lineagePreserved"] is True
    assert checks["promptScorePreserved"] is True
    assert checks["fallbackPreserved"] is True
    assert checks["variationGridPreserved"] is True
    assert result["finishedVideoIntake"]["draftFirst"] is True


def test_run_reel_factory_targets_only_campaign_clips(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may",
            hooks=["hook"],
            recipes=["v01_original"],
            caption_color="auto",
        )
        result = cf.domains.reel_execution.run_reel_factory(
            campaign_slug="may", workers=2
        )
        assert result["returncode"] == 0
        assert len(calls) == 2
        assert all("--only-clip" in call for call in calls)
        assert all("v01_original" in call for call in calls)
        assert all(call[call.index("--band") + 1] == "auto" for call in calls)
        assert all(call[call.index("--color") + 1] == "light" for call in calls)
        assert all(call[call.index("--style") + 1] == "ig" for call in calls)
        assert all(
            call[call.index("--font") + 1] == "Instagram Sans Condensed"
            for call in calls
        )
        assert all("--phone-finalize" in call for call in calls)
        assert calls[0][calls[0].index("--only-clip") + 1] == "clip_001"
        assert calls[1][calls[1].index("--only-clip") + 1] == "clip_002"
    finally:
        cf.close()


def test_run_reel_factory_can_cap_outputs_per_clip(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may", hooks=["h1", "h2"], recipes=None, caption_color="auto"
        )
        result = cf.domains.reel_execution.run_reel_factory(
            campaign_slug="may", workers=1, max_outputs_per_clip=4
        )
        assert result["returncode"] == 0
        assert "--per-clip" in calls[0]
        assert calls[0][calls[0].index("--per-clip") + 1] == "4"
    finally:
        cf.close()


def test_run_reel_factory_can_target_explicit_render_jobs(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        jobs = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may", hooks=["hook"]
        )["prepared"]
        selected = jobs[1]
        result = cf.domains.reel_execution.run_reel_factory(
            campaign_slug="may",
            render_job_ids=[selected["id"]],
            caption_mix="Stacey",
            creator_style_preset="stacey_static_center",
        )
        assert result["returncode"] == 0
        assert [run["renderJobId"] for run in result["runs"]] == [selected["id"]]
        assert len(calls) == 1
        assert calls[0][calls[0].index("--caption-mix") + 1] == "Stacey"
        assert (
            calls[0][calls[0].index("--creator-style-preset") + 1]
            == "stacey_static_center"
        )
        untouched = cf.conn.execute(
            "SELECT status FROM render_jobs WHERE id = ?", (jobs[0]["id"],)
        ).fetchone()
        assert untouched["status"] == "prepared"
        with pytest.raises(ValueError, match="render jobs not found"):
            cf.domains.reel_execution.run_reel_factory(
                campaign_slug="may", render_job_ids=["missing_render_job"]
            )
    finally:
        cf.close()


def test_run_reel_factory_skips_rendered_jobs_by_default(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    (folder / "b.mp4").write_bytes(b"video b")
    cf = make_factory(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may",
            hooks=["hook"],
            recipes=["v01_original"],
            caption_color="auto",
        )
        first = cf.conn.execute(
            "SELECT id FROM render_jobs ORDER BY reel_clip_stem LIMIT 1"
        ).fetchone()["id"]
        cf.conn.execute(
            "UPDATE render_jobs SET status = 'rendered' WHERE id = ?", (first,)
        )
        cf.conn.commit()
        result = cf.domains.reel_execution.run_reel_factory(
            campaign_slug="may", workers=2
        )
        assert result["returncode"] == 0
        assert len(calls) == 1
        assert calls[0][calls[0].index("--only-clip") + 1] == "clip_002"
    finally:
        cf.close()


def test_run_reel_factory_dry_run_keeps_prepared_status(tmp_path: Path, monkeypatch):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video a")
    cf = make_factory(tmp_path)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("campaign_factory.core.subprocess.run", fake_run)
    try:
        cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        job = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may", hooks=["hook"]
        )["prepared"][0]
        result = cf.domains.reel_execution.run_reel_factory(
            campaign_slug="may", dry_run=True
        )
        assert result["returncode"] == 0
        status = cf.conn.execute(
            "SELECT status FROM render_jobs WHERE id = ?", (job["id"],)
        ).fetchone()["status"]
        assert status == "prepared"
    finally:
        cf.close()


def test_front_generation_dry_run_plans_paid_path_without_db_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        calls: list[list[str]] = []

        def fake_invoke(_factory, args):
            calls.append(args)
            return fake_front_generation_result(args)

        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            fake_invoke,
        )

        result = run_front_generation_stage(
            cf,
            campaign_slug="may",
            reference_image_path=reference,
            creator="Stacey",
            execution_plan=build_generation_execution_plan("soul_static"),
            dry_run=True,
        )

        plan = result["plan"]
        validate_front_generation_plan(plan)
        assert result["dryRun"] is True
        assert plan["projectedCostCredits"] is None
        assert plan["budgetStatus"] == "missing_cap"
        assert [stage["name"] for stage in plan["stages"]] == [
            "soul_reference_image",
            "soul_sexy_image",
            "still_accept_gate",
            "static_mp4",
        ]
        assert calls[0][0] == "reference-image-dry-run"
        assert "--execution-plan-file" in calls[0]
        assert len(calls) == 1
        assert plan["stages"][1]["status"] == "blocked"
        assert "captured prompt" in plan["stages"][1]["reason"]
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0] == 0
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_front_generation_global_kill_switch_blocks_before_paid_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        monkeypatch.setenv("CREATOR_OS_KILL_SWITCH", "1")
        jobs_before = cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[
            0
        ]

        with pytest.raises(
            PermissionError, match="paid front generation blocked.*KILL_SWITCH"
        ):
            run_front_generation_stage(
                cf,
                campaign_slug="may",
                reference_image_path=reference,
                creator="Stacey",
                execution_plan=build_generation_execution_plan("soul_static"),
                dry_run=False,
                apply=True,
                enable_paid_generation=True,
                budget_cap_credits=10,
                wait=True,
                download=True,
            )

        assert (
            cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
            == jobs_before
        )
    finally:
        cf.close()


def test_front_generation_apply_fails_closed_without_enable_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")

        def fail_invoke(*_args, **_kwargs):
            raise AssertionError("paid subprocess must not run")

        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            fail_invoke,
        )

        with pytest.raises(PermissionError, match="enable-paid-generation"):
            run_front_generation_stage(
                cf,
                campaign_slug="may",
                reference_image_path=reference,
                creator="Stacey",
                execution_plan=build_generation_execution_plan("soul_static"),
                dry_run=False,
                apply=True,
                budget_cap_credits=10,
            )
        row = cf.conn.execute(
            "SELECT status FROM pipeline_jobs WHERE job_type = 'front_generation'"
        ).fetchone()
        assert row["status"] == "failed"
    finally:
        cf.close()


def test_front_generation_apply_requires_budget_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("paid subprocess must not run")
            ),
        )

        with pytest.raises(ValueError, match="budget-cap-credits"):
            run_front_generation_stage(
                cf,
                campaign_slug="may",
                reference_image_path=reference,
                creator="Stacey",
                execution_plan=build_generation_execution_plan("soul_static"),
                dry_run=False,
                apply=True,
                enable_paid_generation=True,
            )
    finally:
        cf.close()


def test_front_generation_live_paid_path_requires_wait_and_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("paid subprocess must not run")
            ),
        )

        with pytest.raises(ValueError, match="wait --download"):
            run_front_generation_stage(
                cf,
                campaign_slug="may",
                reference_image_path=reference,
                creator="Stacey",
                execution_plan=build_generation_execution_plan("soul_static"),
                dry_run=False,
                apply=True,
                enable_paid_generation=True,
                budget_cap_credits=10,
            )
    finally:
        cf.close()


def test_front_generation_apply_automatically_materializes_static_candidates_before_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        calls: list[list[str]] = []

        def fake_invoke(_factory, args):
            calls.append(args)
            return fake_front_generation_result(args, output_dir=tmp_path)

        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            fake_invoke,
        )
        patch_front_variant_spec(monkeypatch)
        patch_front_static_renderer(monkeypatch)

        result = run_front_generation_stage(
            cf,
            campaign_slug="may",
            reference_image_path=reference,
            creator="Stacey",
            execution_plan=build_generation_execution_plan("soul_static"),
            dry_run=False,
            apply=True,
            enable_paid_generation=True,
            budget_cap_credits=10,
            wait=True,
            download=True,
        )

        plan = result["plan"]
        validate_front_generation_plan(plan)
        assert calls[0][:-2] == [
            "reference-image",
            "--reference",
            str(reference.resolve()),
            "--stem",
            "reference",
            "--campaign",
            "may",
            "--cohort-id",
            "may",
            "--max-credits",
            "10",
            "--creator",
            "Stacey",
            "--wait",
            "--download",
        ]
        assert calls[0][-2] == "--execution-plan-file"
        worker_plan = json.loads(Path(calls[0][-1]).read_text(encoding="utf-8"))
        assert worker_plan == result["executionPlan"]
        assert calls[1][0] == "image"
        assert "--reference" not in calls[1]
        assert "--prompt-json" in calls[1]
        assert "--image-aspect-ratio" in calls[1]
        assert "--execution-plan-file" in calls[1]
        assert len(calls) == 2
        assert ACCEPTED_STILL_PLACEHOLDER not in json.dumps(plan)
        assert plan["budgetStatus"] == "quote_pending"
        assert plan["stages"][0]["status"] == "submitted"
        assert plan["stages"][1]["name"] == "soul_sexy_image"
        assert plan["stages"][1]["status"] == "submitted"
        sexy_pack = json.loads(
            Path(calls[1][calls[1].index("--prompt-json") + 1]).read_text(
                encoding="utf-8"
            )
        )
        assert "19 years old" in sexy_pack["higgsfieldGridPrompt"]
        assert "--image" not in calls[1]
        assert plan["stages"][2]["name"] == "still_accept_gate"
        assert plan["stages"][2]["status"] == "waiting_for_review"
        assert plan["stages"][3]["name"] == "static_mp4"
        assert plan["stages"][3]["status"] == "submitted"
        assert plan["stages"][3]["result"]["candidateCount"] == 2
        assert plan["publishingAllowed"] is False
        assert len(result["registeredStaticAssets"]) == 2
        assert {asset["recipe"] for asset in result["registeredStaticAssets"]} == {
            "static_mp4"
        }
        assert {
            candidate["variant"]
            for candidate in plan["stages"][3]["result"]["candidates"]
        } == {"original", "sexy"}
        generated_sources = cf.conn.execute(
            "SELECT source_prompt, status FROM source_assets "
            "WHERE status = 'generated_qc_passed' ORDER BY created_at, id"
        ).fetchall()
        assert len(generated_sources) == 2
        source_prompts = [json.loads(row["source_prompt"]) for row in generated_sources]
        assert {prompt["variant"] for prompt in source_prompts} == {
            "original",
            "sexy",
        }
        assert all(
            prompt["generatedAssetLineage"]["review"]["qcAcceptanceStatus"]
            == "accepted"
            for prompt in source_prompts
        )
        assert all(
            prompt["generatedAssetLineage"]["review"]["humanReviewStatus"] == "pending"
            for prompt in source_prompts
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'static_mp4'"
            ).fetchone()[0]
            == 2
        )
    finally:
        cf.close()


def test_front_generation_preserves_original_static_when_sexy_candidate_fails_qc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")

        def fake_invoke(_factory, args):
            result = fake_front_generation_result(args, output_dir=tmp_path)
            if args[0] == "image":
                result["ok"] = False
                result["lineage"]["review"]["generatedImageQc"]["status"] = "failed"
                result["error"] = {"reason": "generated_image_qc_failed"}
            return result

        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            fake_invoke,
        )
        patch_front_variant_spec(monkeypatch)
        patch_front_static_renderer(monkeypatch)

        with pytest.raises(
            RuntimeError, match="text-only Soul sexy variant generation blocked"
        ):
            run_front_generation_stage(
                cf,
                campaign_slug="may",
                reference_image_path=reference,
                creator="Stacey",
                execution_plan=build_generation_execution_plan("soul_static"),
                dry_run=False,
                apply=True,
                enable_paid_generation=True,
                budget_cap_credits=10,
                wait=True,
                download=True,
            )

        rows = cf.conn.execute(
            "SELECT recipe, review_state FROM rendered_assets ORDER BY created_at"
        ).fetchall()
        assert [(row["recipe"], row["review_state"]) for row in rows] == [
            ("static_mp4", "review_ready")
        ]
        jobs = cf.conn.execute(
            "SELECT job_type, status FROM pipeline_jobs "
            "WHERE job_type IN ('front_generation', 'static_mp4') ORDER BY created_at"
        ).fetchall()
        assert {(row["job_type"], row["status"]) for row in jobs} == {
            ("front_generation", "failed"),
            ("static_mp4", "succeeded"),
        }
    finally:
        cf.close()


def test_front_generation_rejects_retired_kling_mode_before_factory_access() -> None:
    with pytest.raises(
        ValueError, match="best_only_kling does not use the front-generation worker"
    ):
        run_front_generation_stage(
            object(),
            campaign_slug="may",
            reference_image_path=Path("/definitely/missing.png"),
            creator="Stacey",
            execution_plan=build_generation_execution_plan("best_only_kling"),
            dry_run=True,
        )


def test_front_generation_static_only_apply_needs_no_paid_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        reference = tmp_path / "reference.png"
        reference.write_bytes(b"png")
        accepted = tmp_path / "accepted.png"
        accepted.write_bytes(b"still")
        patch_front_static_renderer(monkeypatch)
        monkeypatch.setattr(
            "campaign_factory.front_generation_stage._invoke_generate_assets",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("static-only flow must not call a paid provider")
            ),
        )

        result = run_front_generation_stage(
            cf,
            campaign_slug="may",
            reference_image_path=reference,
            accepted_still_path=accepted,
            creator="Stacey",
            execution_plan=build_generation_execution_plan("soul_static"),
            dry_run=False,
            apply=True,
        )

        plan = result["plan"]
        validate_front_generation_plan(plan)
        assert plan["projectedCostCredits"] == 0
        assert plan["budgetStatus"] == "not_required"
        assert plan["paidGenerationEnabled"] is False
        assert [stage["name"] for stage in plan["stages"]] == [
            "soul_reference_image",
            "still_accept_gate",
            "static_mp4",
        ]
        assert result["registeredStaticAsset"]["recipe"] == "static_mp4"
        assert result["registeredAsset"] is None
    finally:
        cf.close()


def test_generation_run_library_reuse_outputs_dry_run_report(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
    finally:
        cf.close()

    library = tmp_path / "library"
    library.mkdir()
    (library / "selected.mp4").write_bytes(b"selected-library-mp4")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "campaign_factory.cli",
            "generation",
            "run",
            "--mode",
            "library_reuse",
            "--campaign",
            "may",
            "--folder",
            str(library),
            "--model",
            "model",
            "--dry-run",
        ],
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
    assert payload["schema"] == "campaign_factory.generation_workflow_run.v1"
    assert payload["mode"] == "library_reuse"
    assert payload["dryRun"] is True
    assert payload["result"]["schema"] == "campaign_factory.library_reuse_preflight.v1"
    assert payload["publishingAllowed"] is False


def test_static_mp4_stage_dry_run_is_free_and_does_not_register_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.png"
        still.write_bytes(b"accepted-still")

        def fake_invoke(_factory, **kwargs):
            return fake_static_mp4_render(
                kwargs["still_path"], kwargs["output_path"], dry_run=True
            )

        monkeypatch.setattr(
            "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
            fake_invoke,
        )
        result = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=True,
        )

        assert result["paidGeneration"] is False
        assert result["render"]["animationMode"] == "static_image_mp4"
        assert result["render"]["lockedStatic"] is True
        assert result["registeredAsset"] is None
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0] == 0
        )
    finally:
        cf.close()


def test_static_mp4_default_duration_is_stable_within_operator_range() -> None:
    first = _duration_for_still("a" * 64)
    second = _duration_for_still("a" * 64)
    assert 5.0 <= first <= 7.0
    assert second == first


def test_static_mp4_stage_apply_registers_complete_v2_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.png"
        still.write_bytes(b"accepted-still")

        def fake_invoke(_factory, **kwargs):
            output_path = kwargs["output_path"]
            write_fake_static_mp4_outputs(output_path)
            return fake_static_mp4_render(
                kwargs["still_path"], output_path, dry_run=False
            )

        monkeypatch.setattr(
            "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
            fake_invoke,
        )
        result = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=False,
            apply=True,
        )

        registered = result["registeredAsset"]
        assert registered["source_asset_id"] == source["id"]
        assert registered["recipe"] == "static_mp4"
        assert registered["review_state"] == "review_ready"
        assert registered["audit_status"] == "pending"
        metadata = json.loads(registered["metadata_json"])
        lineage = metadata["generatedAssetLineage"]
        assert lineage["schema"] == "reel_factory.generated_asset_lineage.v2"
        assert lineage["renderedAssetId"] == registered["id"]
        assert lineage["contentFingerprint"] == registered["content_hash"]
        assert lineage["recipeId"] == "static_mp4"
        assert lineage["source"]["promptId"] == "prompt_motion_edit_001"
        assert lineage["source"]["referenceId"] == "reference_test_001"
        assert lineage["generation"]["paidGeneration"] is False
        assert lineage["render"]["lockedStatic"] is True
        assert lineage["asset_state"] == "approved_but_not_publishable"
        assert len(lineage["audioIntentFingerprint"]) == 64
        lineage_path = Path(metadata["generatedAssetLineagePath"])
        assert json.loads(lineage_path.read_text(encoding="utf-8")) == lineage
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM threadsdash_exports").fetchone()[0]
            == 0
        )
    finally:
        cf.close()


def test_static_mp4_stage_apply_is_idempotent_for_same_accepted_still(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.png"
        still.write_bytes(b"accepted-static-still")

        invoke_count = 0

        def fake_invoke(
            _factory,
            *,
            still_path,
            output_path,
            duration_seconds,
            dry_run,
            allow_upscale,
        ):
            nonlocal invoke_count
            invoke_count += 1
            write_fake_static_mp4_outputs(output_path)
            return fake_static_mp4_render(still_path, output_path, dry_run=dry_run)

        monkeypatch.setattr(
            "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
            fake_invoke,
        )
        first = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=False,
            apply=True,
        )
        second = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=still,
            dry_run=False,
            apply=True,
        )

        assert first["registeredAsset"]["id"] == second["registeredAsset"]["id"]
        assert first["reused"] is False
        assert second["reused"] is True
        assert invoke_count == 1
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'static_mp4'"
            ).fetchone()[0]
            == 1
        )
    finally:
        cf.close()


def test_static_mp4_stage_matches_the_accepted_still_to_its_source_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        first = add_source_asset(cf, tmp_path)
        second_folder = tmp_path / "second_source"
        second_folder.mkdir()
        (second_folder / "second.mp4").write_bytes(b"second-source")
        cf.domains.asset_import.import_folder(
            second_folder, campaign_slug="may", model_slug="model"
        )
        sources = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )
        second = next(source for source in sources if source["id"] != first["id"])
        set_test_source_prompt(
            cf,
            second["id"],
            prompt_id="prompt_second",
            reference_id="reference_second",
        )
        accepted = tmp_path / "accepted-second.png"
        accepted.write_bytes(b"accepted-second")
        prompt = json.loads(
            cf.conn.execute(
                "SELECT source_prompt FROM source_assets WHERE id = ?", (second["id"],)
            ).fetchone()[0]
        )
        prompt["generatedAssetLineage"]["review"] = {
            "humanReviewRequired": True,
            "humanReviewStatus": "approved",
            "generatedImageQc": {
                "schema": "reel_factory.generated_image_qc.v1",
                "status": "passed",
                "results": [
                    {
                        "path": str(accepted),
                        "postable": True,
                        "anatomy": {"plausible": True},
                        "exposure": {"safe": True},
                    }
                ],
            },
        }
        cf.conn.execute(
            "UPDATE source_assets SET source_prompt = ? WHERE id = ?",
            (json.dumps(prompt, sort_keys=True), second["id"]),
        )
        cf.conn.commit()

        def fake_invoke(_factory, **kwargs):
            output_path = kwargs["output_path"]
            write_fake_static_mp4_outputs(output_path)
            return fake_static_mp4_render(
                kwargs["still_path"], output_path, dry_run=False
            )

        monkeypatch.setattr(
            "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
            fake_invoke,
        )
        result = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=accepted,
            dry_run=False,
            apply=True,
        )

        assert result["sourceAssetId"] == second["id"]
        assert result["registeredAsset"]["source_asset_id"] == second["id"]
        lineage = json.loads(result["registeredAsset"]["metadata_json"])[
            "generatedAssetLineage"
        ]
        assert lineage["source"]["promptId"] == "prompt_second"
        assert lineage["source"]["referenceId"] == "reference_second"
    finally:
        cf.close()


def test_static_mp4_stage_blocks_ambiguous_multi_source_lineage(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        second_folder = tmp_path / "second_source"
        second_folder.mkdir()
        (second_folder / "second.mp4").write_bytes(b"second-source")
        cf.domains.asset_import.import_folder(
            second_folder, campaign_slug="may", model_slug="model"
        )
        accepted = tmp_path / "unmatched.png"
        accepted.write_bytes(b"unmatched")

        with pytest.raises(ValueError, match="does not match generated-image QC"):
            run_static_mp4_stage(
                cf,
                campaign_slug="may",
                still_path=accepted,
                dry_run=True,
            )
    finally:
        cf.close()


def test_kling_selection_stage_registers_unique_best_approved_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        assets, stills = create_approved_static_candidates(cf, tmp_path, monkeypatch)

        def fake_rank(_factory, *, manifest_path: Path, ranking_path: Path):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidates = manifest["candidates"]
            ranking = {
                "schema": "reel_factory.kling_candidate_ranking.v1",
                "batchId": manifest["batchId"],
                "status": "selected",
                "selectedCandidateId": candidates[1]["id"],
                "candidateCount": 2,
                "signalPresent": True,
                "paidGenerationAuthorized": False,
                "publishingAllowed": False,
                "candidates": [
                    {
                        **candidates[1],
                        "rank": 1,
                        "score": 0.9,
                        "predictedEngagement": {"score": 0.9, "matched": 2},
                    },
                    {
                        **candidates[0],
                        "rank": 2,
                        "score": 0.9,
                        "predictedEngagement": {"score": 0.4, "matched": 1},
                    },
                ],
            }
            ranking_path.write_text(json.dumps(ranking), encoding="utf-8")
            return ranking

        monkeypatch.setattr(
            "campaign_factory.kling_selection_stage._invoke_reel_factory_rank",
            fake_rank,
        )
        result = run_kling_selection_stage(
            cf,
            campaign_slug="may",
            rendered_asset_ids=[assets[0]["id"], assets[1]["id"]],
            batch_id="approved_pair",
            dry_run=False,
            apply=True,
        )

        assert result["selectedRenderedAssetId"] == assets[1]["id"]
        assert result["paidGenerationAuthorized"] is False
        receipt_path = Path(result["receiptPath"])
        assert receipt_path.is_file()
        receipt = validate_kling_selection_receipt(
            cf,
            receipt_path=receipt_path,
            accepted_still_path=stills[1],
            selected_static_asset=assets[1],
        )
        assert receipt["selectedRenderedAssetId"] == assets[1]["id"]
        row = cf.conn.execute(
            "SELECT * FROM kling_selection_receipts WHERE batch_id = 'approved_pair'"
        ).fetchone()
        assert row["status"] == "active"

        receipt_bytes = receipt_path.read_bytes()
        receipt_path.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="wrong schema|hash"):
            validate_kling_selection_receipt(
                cf,
                receipt_path=receipt_path,
                accepted_still_path=stills[1],
                selected_static_asset=assets[1],
            )
        receipt_path.write_bytes(receipt_bytes)
        Path(receipt["rankingPath"]).write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="ranking result evidence changed"):
            validate_kling_selection_receipt(
                cf,
                receipt_path=receipt_path,
                accepted_still_path=stills[1],
                selected_static_asset=assets[1],
            )
    finally:
        cf.close()


def test_kling_selection_stage_blocks_unapproved_or_ambiguous_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        assets, _stills = create_approved_static_candidates(cf, tmp_path, monkeypatch)
        cf.domains.finished_video.review_rendered_asset(
            assets[0]["id"], decision="rejected"
        )
        with pytest.raises(ValueError, match="lacks human approval"):
            run_kling_selection_stage(
                cf,
                campaign_slug="may",
                rendered_asset_ids=[assets[0]["id"], assets[1]["id"]],
                dry_run=True,
            )

        cf.domains.finished_video.review_rendered_asset(
            assets[0]["id"], decision="approved"
        )

        def ambiguous(_factory, *, manifest_path: Path, ranking_path: Path):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            ranking = {
                "schema": "reel_factory.kling_candidate_ranking.v1",
                "batchId": manifest["batchId"],
                "status": "ambiguous_top",
                "selectedCandidateId": None,
                "candidates": manifest["candidates"],
            }
            ranking_path.write_text(json.dumps(ranking), encoding="utf-8")
            return ranking

        monkeypatch.setattr(
            "campaign_factory.kling_selection_stage._invoke_reel_factory_rank",
            ambiguous,
        )
        with pytest.raises(ValueError, match="ambiguous_top"):
            run_kling_selection_stage(
                cf,
                campaign_slug="may",
                rendered_asset_ids=[assets[0]["id"], assets[1]["id"]],
                batch_id="ambiguous",
                dry_run=False,
                apply=True,
            )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM kling_selection_receipts").fetchone()[
                0
            ]
            == 0
        )
    finally:
        cf.close()


def test_kling_selection_stage_rejects_selected_candidate_that_is_not_unique_best(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        assets, _stills = create_approved_static_candidates(cf, tmp_path, monkeypatch)

        def inconsistent(_factory, *, manifest_path: Path, ranking_path: Path):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidates = manifest["candidates"]
            ranking = {
                "schema": "reel_factory.kling_candidate_ranking.v1",
                "batchId": manifest["batchId"],
                "status": "selected",
                "selectedCandidateId": candidates[1]["id"],
                "candidateCount": 2,
                "signalPresent": True,
                "paidGenerationAuthorized": False,
                "publishingAllowed": False,
                "candidates": [
                    {**candidates[0], "rank": 1, "score": 0.9},
                    {**candidates[1], "rank": 2, "score": 0.4},
                ],
            }
            ranking_path.write_text(json.dumps(ranking), encoding="utf-8")
            return ranking

        monkeypatch.setattr(
            "campaign_factory.kling_selection_stage._invoke_reel_factory_rank",
            inconsistent,
        )
        with pytest.raises(ValueError, match="rank-one"):
            run_kling_selection_stage(
                cf,
                campaign_slug="may",
                rendered_asset_ids=[assets[0]["id"], assets[1]["id"]],
                batch_id="inconsistent",
                dry_run=False,
                apply=True,
            )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM kling_selection_receipts").fetchone()[
                0
            ]
            == 0
        )
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("dry_run", "apply"),
    [(True, False), (False, True)],
)
def test_retired_motion_edit_stage_fails_before_any_mutation(
    tmp_path: Path, dry_run: bool, apply: bool
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        still_path = tmp_path / "still.png"
        still_path.write_bytes(b"png")
        before_assets = cf.conn.execute(
            "SELECT COUNT(*) FROM rendered_assets"
        ).fetchone()[0]
        before_jobs = cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[
            0
        ]

        with pytest.raises(PermissionError, match="motion_edit_mode_retired"):
            run_motion_edit_stage(
                cf,
                campaign_slug="may",
                still_path=still_path,
                caption="Retired mode caption",
                dry_run=dry_run,
                apply=apply,
            )

        assert (
            cf.conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0]
            == before_assets
        )
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
            == before_jobs
        )
    finally:
        cf.close()


def test_variation_stage_dry_run_creates_valid_assignment_manifest(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1", "ig_2"])
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_2"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_3"
        )

        result = run_variation_stage(cf, campaign_slug="may", dry_run=True)

        assert result["dryRun"] is True
        assert result["assignments"][0]["assignmentCount"] == 3
        assignment_path = Path(result["assignments"][0]["assignmentPath"])
        payload = json.loads(assignment_path.read_text(encoding="utf-8"))
        validate_variant_assignment(payload)
        assert {item["instagram_account_id"] for item in payload["assignments"]} == {
            "ig_1",
            "ig_2",
            "ig_3",
        }
        assert ".preview." in assignment_path.name
        assert load_variant_assignment_index(cf, campaign_slug="may") == {}
    finally:
        cf.close()


def test_variation_stage_apply_writes_manifest_only_after_perceptual_pass(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1", "ig_2"])
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_2"
        )
        monkeypatch.setattr(
            "campaign_factory.variation_stage.VariantPipeline", FakeVariationPipeline
        )

        def fake_audit(
            *,
            contentforge_root,
            source_path,
            variant_paths,
            contentforge_base_url,
            report_path,
        ):
            assert len(variant_paths) == 2
            assert contentforge_base_url == "http://contentforge.test"
            report_path.write_text("{}", encoding="utf-8")
            return {
                "contractVersion": "campaign_factory_audit.v1.7",
                "overallVerdict": "pass",
                "verdicts": {"pdq": "pass", "sscd": "pass"},
                "readinessSummary": {"uploadReady": True, "blockingCodes": []},
                "reportPath": str(report_path),
            }

        monkeypatch.setattr(
            "campaign_factory.variation_stage.audit_variation_batch", fake_audit
        )

        result = run_variation_stage(
            cf,
            campaign_slug="may",
            dry_run=False,
            contentforge_base_url="http://contentforge.test",
        )

        assignment_path = Path(result["assignments"][0]["assignmentPath"])
        payload = json.loads(assignment_path.read_text(encoding="utf-8"))
        assert assignment_path.exists()
        assert (
            payload["assignments"][0]["lineage"]["perceptual_audit"]["contract_version"]
            == "campaign_factory_audit.v1.7"
        )
        assert payload["assignments"][0]["lineage"]["perceptual_audit"]["verdicts"] == {
            "pdq": "pass",
            "sscd": "pass",
        }
    finally:
        cf.close()


def test_variation_stage_apply_deletes_batch_when_perceptual_gate_blocks(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        isolate_account_groups(cf, ["ig_1", "ig_2"])
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_2"
        )
        monkeypatch.setattr(
            "campaign_factory.variation_stage.VariantPipeline", FakeVariationPipeline
        )
        assignment_dir = (
            cf.domains.campaign_dirs("model", "may")["exports"]
            / "variation_assignments"
        )
        monkeypatch.setattr(
            "campaign_factory.variation_stage.audit_variation_batch",
            lambda **kwargs: {
                "contractVersion": "campaign_factory_audit.v1.7",
                "overallVerdict": "fail",
                "verdicts": {"pdq": "fail", "sscd": "fail"},
                "readinessSummary": {
                    "uploadReady": False,
                    "blockingCodes": ["pdq_sibling_collision", "sscd_unavailable"],
                },
                "reportPath": str(kwargs["report_path"]),
            },
        )

        with pytest.raises(RuntimeError, match="pdq_sibling_collision"):
            run_variation_stage(
                cf,
                campaign_slug="may",
                dry_run=False,
                contentforge_base_url="http://contentforge.test",
            )

        assert not list(assignment_dir.glob("*_variant.mp4"))
        assert not list(assignment_dir.glob("*.variant_assignment.v1.json"))
    finally:
        cf.close()


def test_contentforge_static_mp4_audit_allows_expected_static_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    captured: dict[str, Any] = {}

    def fake_similarity(_base_url, **kwargs):
        captured.update(kwargs)
        return {
            "auditProfile": "campaign_factory_v1",
            "animationMode": "static_image_mp4",
            "allowStaticOpening": True,
            "layers": {"hookVisibility": {"verdict": "warn"}},
            "verdicts": {"hookVisibility": "warn"},
            "overallVerdict": "warn",
            "readinessSummary": {
                "uploadReady": True,
                "blockingCodes": [],
                "warningCodes": ["static_opening"],
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            "UPDATE rendered_assets SET recipe = 'static_mp4' WHERE id = 'asset_1'"
        )
        cf.conn.commit()

        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]

        assert captured["animation_mode"] == "static_image_mp4"
        assert captured["allow_static_opening"] is True
        assert report["allowStaticOpening"] is True
        assert report["status"] == "approved_candidate"
        assert report["failedChecks"] == []
    finally:
        cf.close()


def test_generate_variants_accepts_contentforge_v2_pack(
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
        output_dir = tmp_path / "contentforge_out"
        output_dir.mkdir()
        (output_dir / "variant_001.mp4").write_bytes(b"variant-one")
        (output_dir / "variant_002.mp4").write_bytes(b"variant-two")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_run_v2",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "variantFamilyRecipe": {
                        "familyName": "cover_frame",
                        "profile": "early_hook",
                    },
                    "operationSet": "caption_safe_v2",
                    "operationSignals": {"coverFrameDifferent": True},
                    "qualityScore": 95,
                    "operationDiversityScore": 33,
                },
                {
                    "file": "variant_002.mp4",
                    "uploadReady": True,
                    "recommended": False,
                    "familyName": "generic_variant",
                },
            ],
        }

        monkeypatch.setattr(
            variant_lineage_module,
            "run_contentforge",
            lambda *_args, **_kwargs: report,
        )

        result = cf.domains.variant_lineage.generate_variants(
            parent_asset_id="asset_1",
            count=2,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
        )

        assert result["status"] == "completed"
        assert result["contentforgeReport"]["schema"] == "contentforge.variant_pack.v2"
        assert result["contentforgeReport"]["recommendedCount"] == 1
        assert len(result["registeredVariants"]) == 1
        operations = result["registeredVariants"][0]["variantOperations"]
        assert operations[0]["preset"] == "caption_safe_v2"
        assert operations[1]["result"]["familyName"] == "cover_frame"
        publishability = cf.domains.publishability.explain_publishability(
            result["registeredVariants"][0]["variantAssetId"]
        )
        assert publishability["publishableCandidate"] is True
        assert publishability["checks"]["readiness_checks_pass"] is True
    finally:
        cf.close()


def test_generate_variants_timeout_is_retry_safe_and_commits_no_variants(
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

        def fake_contentforge(*_args, **_kwargs):
            raise RuntimeError("variant pack timed out")

        monkeypatch.setattr(
            variant_lineage_module, "run_contentforge", fake_contentforge
        )

        result = cf.domains.variant_lineage.generate_variants(
            parent_asset_id="asset_1",
            count=2,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            contentforge_timeout_seconds=1,
        )

        assert result["status"] == "blocked"
        assert result["blockingReason"] == "contentforge_variant_pack_cli_error"
        assert result["retryOrResumeSafe"] is True
        assert result["partialCommitPrevented"] is True
        assert result["registeredVariants"] == []
        assert result["contentforgeDiagnostics"]["timeoutSeconds"] == 1
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'"
            ).fetchone()[0]
            == 0
        )
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_generate_variants_polls_job_and_registers_terminal_report(
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
        output_dir = tmp_path / "contentforge_job_out"
        output_dir.mkdir()
        (output_dir / "variant_001.mp4").write_bytes(b"variant-one")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_job_inner_run",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "operationSet": "caption_safe_v2",
                    "qualityScore": 95,
                    "operationDiversityScore": 33,
                }
            ],
        }
        monkeypatch.setattr(
            variant_lineage_module,
            "run_contentforge",
            lambda *_args, **_kwargs: report,
        )

        result = cf.domains.variant_lineage.generate_variants(
            parent_asset_id="asset_1",
            count=1,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            contentforge_timeout_seconds=5,
        )

        assert result["status"] == "completed"
        assert result["contentforgeReport"]["runId"] == "cf_job_inner_run"
        assert len(result["registeredVariants"]) == 1
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'"
            ).fetchone()[0]
            == 1
        )
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 1
    finally:
        cf.close()


def test_generate_variants_rolls_back_partial_registration_on_error(
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
        output_dir = tmp_path / "contentforge_out"
        output_dir.mkdir()
        (output_dir / "variant_001.mp4").write_bytes(b"variant-one")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_run_v2_rollback",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "operationSet": "caption_safe_v2",
                    "qualityScore": 95,
                    "operationDiversityScore": 33,
                }
            ],
        }

        monkeypatch.setattr(
            variant_lineage_module,
            "run_contentforge",
            lambda *_args, **_kwargs: report,
        )

        def fail_register_variant_asset(**_kwargs):
            raise RuntimeError("simulated registration failure")

        monkeypatch.setattr(
            cf.domains.variant_lineage,
            "register_variant_asset",
            fail_register_variant_asset,
        )

        with pytest.raises(RuntimeError, match="simulated registration failure"):
            cf.domains.variant_lineage.generate_variants(
                parent_asset_id="asset_1",
                count=1,
                contentforge_preset="caption_safe_v2",
                contentforge_base_url="http://contentforge.local",
            )

        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM rendered_assets WHERE recipe = 'contentforge_variant_pack'"
            ).fetchone()[0]
            == 0
        )
        assert (
            cf.conn.execute(
                "SELECT COUNT(*) FROM audit_reports WHERE id LIKE 'audit_variant_%'"
            ).fetchone()[0]
            == 0
        )
        assert cf.conn.execute("SELECT COUNT(*) FROM variant_assets").fetchone()[0] == 0
    finally:
        cf.close()


def test_generate_variants_registers_caption_version_lineage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_caption_parent")
        created = cf.domains.caption_family.caption_family_create(
            creator="Stacey",
            parent_asset_id="asset_caption_parent",
            requested_caption_versions=1,
            style="ig_short",
            dry_run=False,
        )
        caption_version = created["plannedVersions"][0]
        output_dir = tmp_path / "contentforge_out"
        output_dir.mkdir()
        (output_dir / "variant_caption_001.mp4").write_bytes(b"variant-caption-version")
        source_override = tmp_path / "caption_version_parent.mp4"
        source_override.write_bytes(b"caption-version-rendered-parent")
        report = {
            "schema": "contentforge.variant_pack.v2",
            "runId": "cf_caption_version_run",
            "manifestPath": str(output_dir / "variant_pack.json"),
            "outputDir": str(output_dir),
            "results": [
                {
                    "file": "variant_caption_001.mp4",
                    "uploadReady": True,
                    "recommended": True,
                    "familyName": "cover_frame",
                    "operationSet": "caption_safe_v2",
                    "qualityScore": 96,
                    "differenceScore": 32,
                    "operationDiversityScore": 34,
                    "captionReadabilityScore": 98,
                    "focalSafetyScore": 98,
                }
            ],
        }

        monkeypatch.setattr(
            variant_lineage_module,
            "run_contentforge",
            lambda *_args, **_kwargs: report,
        )

        result = cf.domains.variant_lineage.generate_variants(
            parent_asset_id="asset_caption_parent",
            caption_version_id=caption_version["captionVersionId"],
            count=1,
            contentforge_preset="caption_safe_v2",
            contentforge_base_url="http://contentforge.local",
            source_media_path=str(source_override),
        )

        assert result["status"] == "completed"
        assert len(result["registeredVariants"]) == 1
        variant = result["registeredVariants"][0]
        assert variant["parentAssetId"] == "asset_caption_parent"
        assert variant["captionFamilyId"] == created["captionFamilyId"]
        assert variant["captionVersionId"] == caption_version["captionVersionId"]
        assert variant["captionHash"] == caption_version["burnedCaptionHash"]
        rendered = cf.domains.rendered_asset(variant["variantAssetId"])
        assert rendered["caption"] == caption_version["burnedCaptionText"]
        assert rendered["caption_hash"] == caption_version["burnedCaptionHash"]
        publishability = cf.domains.publishability.explain_publishability(
            variant["variantAssetId"]
        )
        assert publishability["captionFamilyId"] == created["captionFamilyId"]
        assert publishability["captionVersionId"] == caption_version["captionVersionId"]
        assert (
            publishability["instagram_post_caption"]
            == caption_version["instagramPostCaption"]
        )
    finally:
        cf.close()


def test_reel_factory_parent_throughput_proof_is_read_only_and_pessimistic(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        proof = cf.domains.reel_factory_reports.reel_factory_parent_throughput_proof(
            required_parents_per_day=53
        )

        assert cf.conn.total_changes == before
        assert proof["schema"] == "creator_os.reel_factory_parent_throughput_proof.v1"
        assert proof["canProduce53QualityParentsPerDay"] is False
        assert proof["confidence"] in {"low", "medium", "high"}
        assert proof["limitingStep"]
        assert proof["requiredRawCandidatesPerDay"] >= 53
        assert 0 <= proof["qualityParentPassRate"] <= 1
        assert 0 <= proof["publishabilityPassRate"] <= 1
        assert 0 <= proof["captionFamilyEligibleRate"] <= 1
        assert 0 <= proof["audioValidRate"] <= 1
        assert 0 <= proof["handoffReadyRate"] <= 1
        assert proof["operatorReviewMinutesPerParent"] >= 0
        assert proof["wouldWrite"] is False
    finally:
        cf.close()


def test_reel_factory_yield_failure_and_capacity_reports_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        yield_report = cf.domains.reel_factory_reports.reel_factory_yield_analysis()
        failure = cf.domains.reel_factory_reports.reel_factory_failure_analysis()
        capacity = cf.domains.reel_factory_reports.reel_factory_capacity_model(
            required_parents_per_day=53
        )

        assert cf.conn.total_changes == before
        assert yield_report["schema"] == "creator_os.reel_factory_yield_analysis.v1"
        assert yield_report["funnel"][0]["stage"] == "raw_candidates"
        assert yield_report["funnel"][-1]["stage"] == "schedule_safe"
        assert yield_report["overallYieldPct"] >= 0
        assert yield_report["largestDropoff"]
        assert yield_report["wouldWrite"] is False
        assert failure["schema"] == "creator_os.reel_factory_failure_analysis.v1"
        assert failure["failures"]
        assert failure["whatBreaksFirst"]
        assert all("repairCostMinutes" in item for item in failure["failures"])
        assert failure["wouldWrite"] is False
        assert capacity["schema"] == "creator_os.reel_factory_capacity_model.v1"
        assert capacity["requiredParentsPerDay"] == 53
        assert capacity["passRateScenarios"]["95%"] == 56
        assert capacity["passRateScenarios"]["90%"] == 59
        assert capacity["passRateScenarios"]["80%"] == 67
        assert capacity["passRateScenarios"]["70%"] == 76
        assert capacity["passRateScenarios"]["60%"] == 89
        assert capacity["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_yield_waterfall_and_loss_analysis_explain_current_yield(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        waterfall = cf.domains.parent_factory_reports.parent_factory_yield_waterfall(
            required_parents_per_day=53
        )
        loss = cf.domains.parent_factory_reports.parent_factory_loss_analysis(
            required_parents_per_day=53
        )

        assert cf.conn.total_changes == before
        assert waterfall["schema"] == "creator_os.parent_factory_yield_waterfall.v1"
        assert waterfall["overallYieldPct"] >= 0
        assert waterfall["requiredRawCandidatesPerDay"] >= 53
        assert [row["stage"] for row in waterfall["stages"]] == [
            "raw_candidate",
            "render_success",
            "visual_qc_pass",
            "caption_burn_pass",
            "audio_validation_pass",
            "discoverability_safety_pass",
            "publishability_pass",
            "handoff_ready",
            "schedule_safe",
            "parent_accepted",
        ]
        assert all(
            {"stage", "inputCount", "outputCount", "yieldPct", "lossCount"} <= set(row)
            for row in waterfall["stages"]
        )
        assert waterfall["wouldWrite"] is False
        assert loss["schema"] == "creator_os.parent_factory_loss_analysis.v1"
        assert loss["largestLossStage"]
        assert loss["largestRepairableLossStage"]
        assert loss["highestROIImprovement"]
        assert loss["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_rejection_quality_and_optimization_reports_are_read_only(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        rejections = cf.domains.parent_factory_reports.parent_factory_rejection_report()
        quality = (
            cf.domains.parent_factory_reports.parent_factory_quality_gate_analysis()
        )
        optimization = (
            cf.domains.parent_factory_reports.parent_factory_optimization_plan(
                required_parents_per_day=53
            )
        )

        assert cf.conn.total_changes == before
        assert rejections["schema"] == "creator_os.parent_factory_rejection_report.v1"
        assert rejections["rejectionReasons"]
        assert all(
            {
                "reason",
                "frequency",
                "percentOfFailures",
                "repairable",
                "estimatedFixDifficulty",
            }
            <= set(row)
            for row in rejections["rejectionReasons"]
        )
        assert rejections["wouldWrite"] is False
        assert quality["schema"] == "creator_os.parent_factory_quality_gate_analysis.v1"
        assert quality["qualityGates"]
        assert "publishability_pass" in {row["gate"] for row in quality["qualityGates"]}
        assert quality["wouldWrite"] is False
        assert (
            optimization["schema"] == "creator_os.parent_factory_optimization_plan.v1"
        )
        assert optimization["currentYieldPct"] >= 0
        assert (
            optimization["yieldScenarios"]["20%"]["rawCandidatesNeededFor53Parents"]
            == 265
        )
        assert (
            optimization["yieldScenarios"]["40%"]["rawCandidatesNeededFor53Parents"]
            == 133
        )
        assert (
            optimization["yieldScenarios"]["50%"]["rawCandidatesNeededFor53Parents"]
            == 106
        )
        assert (
            optimization["humanBottleneckAnalysis"]["accountsSupportedPerOperator"] >= 0
        )
        assert optimization["whatThreeFixesIncreaseYieldFastest"]
        assert optimization["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_discoverability_loss_analysis_categorizes_preventable_rejections(
    tmp_path: Path,
):
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
                "DM me, link in bio, add me on Snapchat, OnlyFans",
                json.dumps(
                    {
                        "caption_text": "DM me, link in bio, add me on Snapchat, OnlyFans",
                        "instagram_post_caption": "DM me, link in bio",
                    }
                ),
            ),
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        analysis = (
            cf.domains.discoverability.parent_factory_discoverability_loss_analysis()
        )

        assert cf.conn.total_changes == before
        assert (
            analysis["schema"]
            == "creator_os.parent_factory_discoverability_loss_analysis.v1"
        )
        categories = {
            row["category"]: row["frequency"]
            for row in analysis["discoverabilityRejectionCategories"]
        }
        assert categories["dm_language"] >= 1
        assert categories["bio_reference"] >= 1
        assert categories["snapchat_reference"] >= 1
        assert categories["onlyfans_reference"] >= 1
        assert analysis["percentPreventableAtCaptionCreation"] > 0
        assert analysis["percentPreventableAtGeneration"] >= 0
        assert analysis["percentPreventableAtRegistration"] >= 0
        assert analysis["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_discoverability_loss_analysis_prefers_captured_evidence(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET review_state = 'approved',
                caption = ?,
                caption_outcome_context_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me on Telegram",
                json.dumps(
                    {
                        "caption_text": "DM me on Telegram",
                        "burned_caption_text": "DM me on Telegram",
                        "instagram_post_caption": "DM me on Telegram",
                        "captionPlacementDecision": {"status": "passed"},
                    }
                ),
            ),
        )
        cf.conn.commit()
        cf.domains.publishability.capture_publishability_rejection_evidence("asset_1")
        before = cf.conn.total_changes

        analysis = (
            cf.domains.discoverability.parent_factory_discoverability_loss_analysis()
        )

        assert cf.conn.total_changes == before
        categories = {
            row["category"]: row["frequency"]
            for row in analysis["discoverabilityRejectionCategories"]
        }
        assert categories["dm_language"] >= 1
        assert categories["telegram_reference"] >= 1
        assert analysis["capturedEvidenceCount"] >= 2
        assert analysis["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_master_optimization_report_exposes_discoverability_breakdown(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        report = (
            cf.domains.parent_factory_reports.parent_factory_master_optimization_report(
                required_parents_per_day=53
            )
        )

        assert cf.conn.total_changes == before
        breakdown = report["discoverabilityLossAnalysis"]
        assert (
            breakdown["schema"]
            == "creator_os.parent_factory_discoverability_loss_analysis.v1"
        )
        assert {
            row["category"] for row in breakdown["discoverabilityRejectionCategories"]
        } >= {
            "dm_language",
            "link_language",
            "off_platform_reference",
            "onlyfans_reference",
            "telegram_reference",
            "snapchat_reference",
            "whatsapp_reference",
            "bio_reference",
            "cta_language",
            "other",
        }
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_master_optimization_report_answers_acceptance_questions(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        report = (
            cf.domains.parent_factory_reports.parent_factory_master_optimization_report(
                required_parents_per_day=53
            )
        )

        assert cf.conn.total_changes == before
        assert (
            report["schema"]
            == "creator_os.parent_factory_master_optimization_report.v1"
        )
        acceptance = report["acceptanceCriteria"]
        assert acceptance["whyYieldIs8_2Pct"]
        assert acceptance["whatSingleFixImprovesYieldMost"]
        assert len(acceptance["whatThreeFixesIncreaseYieldFastest"]) == 3
        assert (
            acceptance["expectedYieldAfterFixes"]
            >= report["optimizationPlan"]["currentYieldPct"]
        )
        assert (
            acceptance["newRawCandidatesNeededFor53Parents"]
            <= report["optimizationPlan"]["currentRawCandidatesNeededFor53Parents"]
        )
        assert isinstance(acceptance["canSupport200AccountsAfterFixes"], bool)
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_parent_factory_yield_recovery_math_uses_measured_waterfall(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        origin = cf.domains.discoverability.discoverability_violation_origin_map()
        recovery = cf.domains.parent_factory_reports.parent_factory_recoverable_yield()
        throughput = (
            cf.domains.parent_factory_reports.parent_factory_throughput_recovery_plan()
        )
        feasibility = (
            cf.domains.parent_factory_reports.parent_factory_53_parent_feasibility()
        )

        assert cf.conn.total_changes == before
        assert origin["schema"] == "creator_os.discoverability_violation_origin_map.v1"
        assert origin["whereViolationsFirstAppear"]
        assert origin["earliestPreventableStage"] in {
            "source_content_perception",
            "prompt_generation",
            "caption_generation",
            "burned_caption_generation",
            "caption_family_generation",
            "parent_registration",
            "publishability_validation",
        }
        assert 0 <= origin["percentPreventableBeforeRender"] <= 100
        assert 0 <= origin["percentPreventableBeforeRegistration"] <= 100
        assert recovery["schema"] == "creator_os.parent_factory_recoverable_yield.v1"
        assert recovery["currentYieldPct"] == 8.2
        assert recovery["yieldIfDiscoverabilityFixed"] > recovery["currentYieldPct"]
        assert recovery["yieldIfBothFixed"] >= recovery["yieldIfDiscoverabilityFixed"]
        assert recovery["requiredRawCandidatesFor53Parents"] <= 647
        assert (
            throughput["schema"]
            == "creator_os.parent_factory_throughput_recovery_plan.v1"
        )
        assert throughput["requiredParentsPerDay"] == 53
        assert throughput["currentParentsPerDay"] == 20
        assert throughput["gap"] == 33
        assert throughput["largestLossStage"] == "discoverability_safety_pass"
        assert throughput["expectedGainFromRepair"] > 0
        assert (
            feasibility["schema"]
            == "creator_os.parent_factory_53_parent_feasibility.v1"
        )
        assert feasibility["minimumYieldRequired"] == 21.6
        assert feasibility["minimumCandidatesRequired"] == 245
        assert feasibility["highestROIChange"]
        assert feasibility["recommendedNextImplementation"]
        assert all(
            item["wouldWrite"] is False
            for item in [origin, recovery, throughput, feasibility]
        )
    finally:
        cf.close()


def test_parent_factory_secondary_loss_model_does_not_assume_perfect_recovery(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        secondary = (
            cf.domains.parent_factory_reports.parent_factory_secondary_loss_analysis()
        )
        repaired_waterfall = (
            cf.domains.discoverability.parent_factory_waterfall_after_discoverability()
        )
        true_yield = cf.domains.parent_factory_reports.parent_factory_true_yield_model()
        realistic = (
            cf.domains.parent_factory_reports.parent_factory_realistic_53_parent_plan()
        )

        assert cf.conn.total_changes == before
        assert (
            secondary["schema"]
            == "creator_os.parent_factory_secondary_loss_analysis.v1"
        )
        assert secondary["discoverabilityRemoved"] is True
        assert secondary["newLargestLossStage"] == "none_measured_after_discoverability"
        assert secondary["rankedLossStages"]
        assert secondary["nextBottleneck"] == "downstream_sample_size_uncertainty"
        assert (
            repaired_waterfall["schema"]
            == "creator_os.parent_factory_waterfall_after_discoverability.v1"
        )
        assert repaired_waterfall["discoverabilityRemoved"] is True
        assert repaired_waterfall["stages"][0]["stage"] == "raw_candidate"
        assert all(
            row["stage"] != "discoverability_safety_pass"
            for row in repaired_waterfall["stages"]
        )
        assert true_yield["schema"] == "creator_os.parent_factory_true_yield_model.v1"
        assert true_yield["currentYieldPct"] == 8.2
        assert true_yield["theoreticalUpperBoundYieldPct"] == 100.0
        assert (
            true_yield["realisticYieldAfterDiscoverabilityRepair"]
            < true_yield["theoreticalUpperBoundYieldPct"]
        )
        assert true_yield["acceptedParentsPer245Candidates"] < 245
        assert (
            realistic["schema"]
            == "creator_os.parent_factory_realistic_53_parent_plan.v1"
        )
        assert realistic["discoverabilityRemoved"] is True
        assert (
            realistic["expectedRealYieldPct"]
            == true_yield["realisticYieldAfterDiscoverabilityRepair"]
        )
        assert realistic["requiredCandidatesFor53Parents"] >= 53
        assert realistic["highestROIAfterDiscoverability"]
        assert all(
            item["wouldWrite"] is False
            for item in [secondary, repaired_waterfall, true_yield, realistic]
        )
    finally:
        cf.close()


def test_parent_factory_post_gate_fresh_batch_proof_uses_sandbox_and_real_gates(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        proof = cf.domains.parent_factory_trials.parent_factory_post_gate_fresh_batch_proof()

        assert cf.conn.total_changes == before
        assert (
            proof["schema"]
            == "creator_os.parent_factory_post_gate_fresh_batch_proof.v1"
        )
        assert proof["freshBatch"] is True
        assert proof["fixtureBatch"] is True
        assert proof["targetAcceptedParents"] == 53
        assert proof["rawCandidates"] >= 64
        assert proof["blockedBeforeRender"] > 0
        assert (
            proof["blockedBeforeRender"] + proof["registeredParents"]
            == proof["rawCandidates"]
        )
        assert proof["renderJobsAvoided"] == proof["blockedBeforeRender"]
        assert proof["renderJobsCreated"] == proof["registeredParents"]
        assert proof["registeredParents"] == proof["acceptedParents"]
        assert proof["acceptedParents"] == 53
        assert proof["yieldPct"] >= 50
        assert proof["lateDiscoverabilityFailures"] == 0
        assert proof["publishabilityFailures"] == 0
        assert proof["qualityFailures"] == 0
        assert proof["duplicateFailures"] == 0
        assert proof["otherFailures"] == 0
        assert proof["targetParentsReached"] is True
        assert proof["successCriteria"]["passed"] is True
        assert proof["successCriteria"]["strongPass"] is True
        assert proof["comparison"]["baseline"]["acceptedParents"] == 20
        assert proof["comparison"]["baseline"]["lateDiscoverabilityFailures"] == 225
        assert (
            proof["comparison"]["improvement"]["lateDiscoverabilityFailuresReduced"]
            is True
        )
        assert proof["comparison"]["improvement"]["yieldImproved"] is True
        assert proof["comparison"]["improvement"]["acceptedParentLift"] >= 33
        assert proof["blockedCandidates"]
        assert all(
            item["renderJobCreated"] is False for item in proof["blockedCandidates"]
        )
        assert all(
            item["sourceAssetCreated"] is False for item in proof["blockedCandidates"]
        )
        assert all(
            item["renderedAssetCreated"] is False for item in proof["blockedCandidates"]
        )
        assert {item["blockedAt"] for item in proof["blockedCandidates"]} == {
            "discoverability_pre_render_gate"
        }
        assert proof["wouldWrite"] is False
    finally:
        cf.close()
