from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import campaign_factory.asset_import as asset_import_module
import campaign_factory.core as core_module
import pytest
from campaign_asset_test_support import (
    add_audit_report,
    add_inventory_parent_fixture,
    add_schedule_safe_production_asset,
    add_story_quality_asset,
    add_surface_asset_fixture,
    add_variant_fixture,
    ensure_exportable_distribution_plan,
    table_count,
)
from campaign_factory.adapters import contentforge as contentforge_adapter
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.adapters import (
    threadsdash_draft_delivery as threadsdash_delivery_adapter,
)
from campaign_factory.adapters.contentforge import audit_campaign
from campaign_factory.adapters.threadsdash_draft_delivery import export_threadsdash
from campaign_factory.adapters.threadsdash_draft_payload import build_draft_payloads
from campaign_factory.adapters.threadsdash_draft_readiness import (
    evaluate_export_readiness,
)
from campaign_factory.contracts import (
    validate_audio_intent,
    validate_threadsdash_draft_payload_strict,
)
from campaign_learning_test_support import _draft_item, _manager_report_fixture
from campaign_test_support import (
    add_rendered_asset,
    make_factory,
    set_test_source_prompt,
)


def test_contentforge_staging_is_run_isolated_and_preserves_shared_final(
    tmp_path: Path,
) -> None:
    root = tmp_path / "contentforge"
    shared_final = root / "output" / "final"
    shared_final.mkdir(parents=True)
    baseline = shared_final / "existing.mp4"
    baseline.write_bytes(b"baseline")
    source_a = tmp_path / "source_a.mp4"
    media_a = tmp_path / "media_a.mp4"
    source_b = tmp_path / "source_b.mp4"
    media_b = tmp_path / "media_b.mp4"
    source_a.write_bytes(b"source-a")
    media_a.write_bytes(b"media-a")
    source_b.write_bytes(b"source-b")
    media_b.write_bytes(b"media-b")

    with contentforge_adapter._stage_contentforge_asset(root, source_a, media_a) as (
        _staged_source_a,
        staged_a,
        _references_a,
    ):
        run_a = staged_a.parent.parent
        assert baseline.read_bytes() == b"baseline"
        with contentforge_adapter._stage_contentforge_asset(
            root, source_b, media_b
        ) as (_staged_source_b, staged_b, _references_b):
            run_b = staged_b.parent.parent
            assert run_a != run_b
            assert staged_a.read_bytes() == b"media-a"
            assert staged_b.read_bytes() == b"media-b"
            assert baseline.read_bytes() == b"baseline"
        assert staged_a.exists()
        assert not run_b.exists()

    assert not run_a.exists()
    assert baseline.read_bytes() == b"baseline"


def test_contentforge_staging_exception_cleans_only_its_isolated_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "contentforge"
    source = tmp_path / "source.mp4"
    media = tmp_path / "media.mp4"
    source.write_bytes(b"source")
    media.write_bytes(b"media")
    run_root: Path | None = None

    with pytest.raises(RuntimeError, match="forced interruption"):
        with contentforge_adapter._stage_contentforge_asset(root, source, media) as (
            _staged_source,
            staged,
            _references,
        ):
            run_root = staged.parent.parent
            raise RuntimeError("forced interruption")

    assert run_root is not None
    assert not run_root.exists()
    assert not list((root / "output" / "runs").glob("*/final/*.mp4"))


def test_import_folder_rejects_raw_reel_review_batch_manifest(tmp_path: Path):
    folder = tmp_path / "review_batch"
    folder.mkdir()
    (folder / "clip.mp4").write_bytes(b"video")
    (folder / "review_manifest.json").write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "rows": [
                    {
                        "output": str(folder / "clip.mp4"),
                        "captionHash": "abc",
                        "overlayPng": str(folder / "clip.png"),
                    }
                ],
            }
        )
    )
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(
            ValueError, match="guard-passed Reel Factory review package"
        ):
            cf.domains.asset_import.import_folder(
                folder, campaign_slug="batch", model_slug="model"
            )
    finally:
        cf.close()


def test_import_folder_rejects_review_package_missing_contentforge_audit(
    tmp_path: Path,
):
    folder = tmp_path / "review_batch"
    folder.mkdir()
    clip = folder / "clip.mp4"
    overlay = folder / "clip.png"
    clip.write_bytes(b"video")
    overlay.write_bytes(b"png")
    raw_manifest = folder / "review_manifest.json"
    raw_manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "rows": [
                    {
                        "output": str(clip),
                        "captionHash": "abc",
                        "overlayPng": str(overlay),
                    }
                ],
            }
        )
    )
    (folder / "review_package.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.review_batch_package.v1",
                "manifestPath": str(raw_manifest),
                "count": 1,
                "fileSha256": {
                    str(raw_manifest.resolve()): hashlib.sha256(
                        raw_manifest.read_bytes()
                    ).hexdigest(),
                    str(clip.resolve()): hashlib.sha256(clip.read_bytes()).hexdigest(),
                    str(overlay.resolve()): hashlib.sha256(
                        overlay.read_bytes()
                    ).hexdigest(),
                },
                "rows": [
                    {
                        "output": str(clip),
                        "captionHash": "abc",
                        "overlayPng": str(overlay),
                    }
                ],
            }
        )
    )
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="missing ContentForge audit path"):
            cf.domains.asset_import.import_folder(
                folder, campaign_slug="batch", model_slug="model"
            )
    finally:
        cf.close()


def test_review_batch_contentforge_audit_updates_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.mp4"
    variant = tmp_path / "variant.mp4"
    source.write_bytes(b"source")
    variant.write_bytes(b"variant")
    manifest = tmp_path / "review_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(tmp_path),
                "captionPlacementPolicy": "focal-safe",
                "rows": [
                    {
                        "output": str(variant),
                        "captionHash": "abc",
                        "overlayPng": str(tmp_path / "overlay.png"),
                    }
                ],
            }
        )
    )

    @contextmanager
    def fake_stage(_root, _source, _variants):
        yield source, [variant]

    captured: dict[str, Any] = {}

    def fake_similarity(*args, **kwargs):
        captured.update(kwargs)
        return {
            "auditProfile": "campaign_factory_v1",
            "overallVerdict": "warn",
            "readinessSummary": {
                "uploadReady": True,
                "blockingCodes": [],
                "warningCodes": ["forensics_audio_missing"],
            },
        }

    monkeypatch.setattr(
        contentforge_adapter, "_stage_contentforge_variation_batch", fake_stage
    )
    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)

    report = contentforge_adapter.audit_review_batch_manifest(
        contentforge_root=tmp_path / "contentforge",
        manifest_path=manifest,
        source_path=source,
        contentforge_base_url="cli://local",
    )

    updated_manifest = json.loads(manifest.read_text())
    audit_path = Path(updated_manifest["contentForgeAuditPath"])
    assert audit_path.exists()
    assert report["auditProfile"] == "campaign_factory_v1"
    assert report["variants"] == 1
    assert report["contentForgeMode"] == "cli_local"
    assert report["auditedFileCount"] == 1
    assert report["verdictCounts"]["pass"] == 1
    assert captured["audit_profile"] == "campaign_factory_v1"
    assert captured["target_file"] == variant.name


def test_review_batch_contentforge_audit_writes_per_file_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.mp4"
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    source.write_bytes(b"source")
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    manifest = tmp_path / "review_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(tmp_path),
                "captionPlacementPolicy": "focal-safe",
                "rows": [
                    {
                        "output": str(first),
                        "captionHash": "abc",
                        "overlayPng": str(tmp_path / "first.png"),
                    },
                    {
                        "output": str(second),
                        "captionHash": "def",
                        "overlayPng": str(tmp_path / "second.png"),
                    },
                ],
            }
        )
    )

    @contextmanager
    def fake_stage(_root, _source, _variants):
        yield source, [first, second]

    calls: list[dict[str, Any]] = []

    def fake_similarity(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("comparison_files"):
            return {
                "auditProfile": "campaign_factory_v1",
                "overallVerdict": "warn",
                "readinessSummary": {
                    "uploadReady": True,
                    "blockingCodes": [],
                    "warningCodes": ["aggregate_review"],
                },
            }
        if kwargs["target_file"] == first.name:
            return {
                "auditProfile": "campaign_factory_v1",
                "overallVerdict": "pass",
                "safeZoneScore": 98,
                "readabilityScore": 91,
                "hookVisibilityScore": 88,
                "ocr": {
                    "available": True,
                    "engine": "tesseract",
                    "sampleCount": 3,
                    "avgConfidence": 86,
                    "results": [],
                },
                "timings": {"advisory": {"ocrMs": 12}},
                "readinessSummary": {
                    "uploadReady": True,
                    "recommendedAction": "approve",
                    "blockingCodes": [],
                    "warningCodes": [],
                    "topWarnings": [],
                },
            }
        return {
            "auditProfile": "campaign_factory_v1",
            "overallVerdict": "warn",
            "safeZoneScore": 62,
            "readabilityScore": 44,
            "hookVisibilityScore": 55,
            "ocr": {
                "available": True,
                "engine": "tesseract",
                "sampleCount": 3,
                "avgConfidence": 41,
                "results": [],
            },
            "readinessSummary": {
                "uploadReady": False,
                "recommendedAction": "review",
                "blockingCodes": [],
                "warningCodes": ["caption_low_contrast", "caption_too_small"],
                "topWarnings": [
                    {
                        "code": "caption_low_contrast",
                        "severity": "warn",
                        "message": "Review caption contrast.",
                    }
                ],
            },
        }

    monkeypatch.setattr(
        contentforge_adapter, "_stage_contentforge_variation_batch", fake_stage
    )
    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)

    report = contentforge_adapter.audit_review_batch_manifest(
        contentforge_root=tmp_path / "contentforge",
        manifest_path=manifest,
        source_path=source,
        contentforge_base_url="cli://local",
        animation_mode="static_image_mp4",
        allow_static_opening=True,
        per_file=True,
    )

    assert len(calls) == 3
    assert all(call["animation_mode"] == "static_image_mp4" for call in calls)
    assert all(call["allow_static_opening"] is True for call in calls)
    assert calls[1]["target_file"] == first.name
    assert calls[1]["comparison_files"] == []
    assert calls[2]["target_file"] == second.name
    assert calls[2]["comparison_files"] == []
    assert [row["outputPath"] for row in report["fileResults"]] == [
        str(first.resolve()),
        str(second.resolve()),
    ]
    assert [row["status"] for row in report["fileResults"]] == ["ready", "review"]
    assert report["fileStatusCounts"] == {"ready": 1, "review": 1}
    assert report["fileOverallVerdictCounts"] == {"pass": 1, "warn": 1}
    assert report["warningCodeFrequency"] == {
        "caption_low_contrast": 1,
        "caption_too_small": 1,
    }
    assert report["blockingCodeFrequency"] == {}
    assert report["fileResults"][1]["topWarnings"][0]["code"] == "caption_low_contrast"
    assert report["fileResults"][1]["safeZoneScore"] == 62


def test_review_batch_contentforge_audit_marks_missing_per_file_result_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.mp4"
    first = tmp_path / "first.mp4"
    source.write_bytes(b"source")
    first.write_bytes(b"first")
    manifest = tmp_path / "review_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(tmp_path),
                "rows": [
                    {
                        "output": str(first),
                        "captionHash": "abc",
                        "overlayPng": str(tmp_path / "first.png"),
                    }
                ],
            }
        )
    )

    @contextmanager
    def fake_stage(_root, _source, _variants):
        yield source, [first]

    call_count = {"value": 0}

    def fake_similarity(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "auditProfile": "campaign_factory_v1",
                "overallVerdict": "pass",
                "readinessSummary": {
                    "uploadReady": True,
                    "blockingCodes": [],
                    "warningCodes": [],
                },
            }
        raise RuntimeError("ContentForge timed out")

    monkeypatch.setattr(
        contentforge_adapter, "_stage_contentforge_variation_batch", fake_stage
    )
    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)

    report = contentforge_adapter.audit_review_batch_manifest(
        contentforge_root=tmp_path / "contentforge",
        manifest_path=manifest,
        source_path=source,
        contentforge_base_url="cli://local",
        per_file=True,
    )

    assert report["fileStatusCounts"] == {"blocked": 1}
    assert report["blockingCodeFrequency"] == {"contentforge_cli": 1}
    assert report["fileResults"][0]["error"] == "ContentForge timed out"


def test_import_folder_accepts_guarded_reel_review_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    folder = tmp_path / "review_batch"
    folder.mkdir()
    clip = folder / "clip.mp4"
    overlay = folder / "clip.png"
    audio_intent = folder / "clip.mp4.audio_intent.json"
    lineage = folder / "clip.mp4.generated_asset_lineage.json"
    readiness = folder / "_readiness.json"
    contentforge_audit = folder / "contentforge_audit.json"
    clip.write_bytes(b"video")
    overlay.write_bytes(b"png")
    audio_intent.write_text(
        json.dumps(
            {
                "schema": "audio_intent.v1",
                "mode": "platform_auto_music",
                "humanReviewRequired": True,
            }
        )
    )
    lineage.write_text(
        json.dumps(
            {
                "schema": "reel_factory.generated_asset_lineage.v1",
                "workflow": "reel_factory_review_batch",
                "pipelineTraceId": "trace_review_1",
                "source": {
                    "promptId": "prompt_review_1",
                    "referenceId": "reference_review_1",
                },
                "generation": {"tool": "reel_factory_review_batch"},
                "review": {"humanReviewRequired": True, "status": "approved"},
                "captionPlacementDecision": {
                    "status": "passed",
                    "selectedLane": "top",
                    "scores": {"top": 0.91, "center": 0.42, "bottom": 0.73},
                    "components": {"top": {}, "center": {}, "bottom": {}},
                    "sampleCount": 3,
                },
            }
        )
    )
    readiness.write_text(
        json.dumps({"summary": {"total": 1, "ready": 1, "warn": 0, "notReady": 0}})
    )
    contentforge_audit.write_text(
        json.dumps(
            {
                "auditProfile": "campaign_factory_v1",
                "variants": 1,
                "auditedFileCount": 1,
                "verdictCounts": {"pass": 1, "fail": 0},
                "overallVerdict": "pass",
                "readinessSummary": {"uploadReady": True, "blockingCodes": []},
                "blockingCodes": [],
            }
        )
    )
    raw_manifest = folder / "review_manifest.json"
    raw_manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "contentForgeAuditPath": str(contentforge_audit),
                "font": "Instagram Sans Condensed Bold",
                "renderer": "reel_factory.caption_render",
                "style": "ig",
                "captionSelection": {"source": "caption bank"},
                "backgroundPlate": False,
                "rows": [
                    {
                        "output": str(clip),
                        "captionHash": "abc",
                        "captionText": "caption bank hook",
                        "sourceBanks": ["stacey_hooks"],
                        "selectedBand": "top",
                        "captionPlacementPolicy": "focal-safe",
                        "overlayPng": str(overlay),
                    }
                ],
            }
        )
    )
    hashed_paths = [
        raw_manifest,
        contentforge_audit,
        readiness,
        clip,
        overlay,
        audio_intent,
        lineage,
    ]
    (folder / "review_package.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.review_batch_package.v1",
                "manifestPath": str(raw_manifest),
                "count": 1,
                "guard": {"status": "ready", "blockingReasons": [], "count": 1},
                "fileSha256": {
                    str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in hashed_paths
                },
                "rows": [
                    {
                        "output": str(clip),
                        "captionHash": "abc",
                        "overlayPng": str(overlay),
                    }
                ],
            }
        )
    )

    def fake_guard(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"status": "ready", "count": 1}),
            stderr="",
        )

    monkeypatch.setattr("campaign_factory.asset_import.subprocess.run", fake_guard)
    cf = make_factory(tmp_path)
    try:
        result = cf.domains.asset_import.import_folder(
            folder, campaign_slug="batch", model_slug="model"
        )
        assert any(asset["filename"].endswith(".mp4") for asset in result["imported"])
        assert result["renderedCount"] == 1
        rendered = cf.conn.execute("SELECT * FROM rendered_assets").fetchone()
        assert rendered["caption_hash"] == "abc"
        assert rendered["caption"] == "caption bank hook"
        assert rendered["recipe"] == "reel_factory_review_package"
        assert rendered["audit_status"] == "approved_candidate"
        assert rendered["review_state"] == "review_ready"
        generation = json.loads(rendered["caption_generation_json"])
        assert generation["audioIntent"]["mode"] == "platform_auto_music"
        validate_audio_intent(generation["audioIntent"])
        assert (
            generation["generatedAssetLineage"]["workflow"]
            == "reel_factory_review_batch"
        )
        context = json.loads(rendered["caption_outcome_context_json"])
        assert context["captionPlacementDecision"]["status"] == "passed"
        audit = cf.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = ?", (rendered["id"],)
        ).fetchone()
        assert audit["overall_verdict"] == "pass"
        assert audit["report_path"] == str(contentforge_audit)
        assert (
            cf.domains.export_summary.export_manifest(campaign_slug="batch")["assets"]
            == []
        )
        review_manifest = cf.domains.export_summary.export_manifest(
            campaign_slug="batch", review_only=True
        )
        assert len(review_manifest["assets"]) == 1
        assert review_manifest["assets"][0]["reviewState"] == "review_ready"
        review_payload = build_draft_payloads(
            cf,
            campaign_slug="batch",
            user_id="user_1",
            review_only=True,
        )
        assert review_payload["handoffMode"] == "review_only"
        review_draft = review_payload["drafts"][0]
        assert review_draft["status"] == "draft"
        assert "scheduledFor" not in review_draft
        review_metadata = review_draft["metadata"]["campaign_factory"]
        assert review_metadata["asset_state"] == "review_ready"
        assert review_metadata["approved"] is False
        assert review_metadata["scheduleSafe"] is False
        assert review_metadata["allowPublish"] is False
        assert review_metadata["approvalRequired"] is True
        review_handoff = review_draft["handoffManifest"]
        assert review_handoff["manifest_version"] == 2
        assert review_handoff["asset_id"] == rendered["id"]
        assert review_handoff["content_fingerprint"] == review_draft["contentHash"]
        assert review_handoff["render_file_id"]
        assert review_handoff["visual_verification_id"]
        assert review_handoff["caption_verification_id"]
        assert review_handoff["audio_id"] == "pending_native_audio_review"
        assert review_handoff["distribution_plan_id"] == "review_only_unassigned"
        assert review_handoff["handoffMode"] == "review_only"
        assert review_handoff["approvalRequired"] is True
        assert review_handoff["approved"] is False
        assert review_handoff["scheduleSafe"] is False
        assert review_handoff["allowPublish"] is False
        assert review_metadata["handoff_manifest"] == review_handoff
        validate_threadsdash_draft_payload_strict(review_payload)
        assert (
            threadsdash_delivery_adapter._campaign_factory_manifest_blockers(
                review_payload
            )
            == []
        )
        review_draft["media"][0]["url"] = "https://media.example/review.mp4"
        threadsdash_delivery_adapter._hydrate_surface_media_items_for_uploaded_media(
            review_draft,
            {"publicUrl": "https://media.example/review.mp4"},
        )
        assert (
            threadsdash_delivery_adapter._campaign_factory_manifest_blockers(
                review_payload, require_remote_media_urls=True
            )
            == []
        )
        cf.domains.finished_video.review_rendered_asset(
            rendered["id"], decision="approved", notes="certification smoke"
        )
        exported = cf.domains.export_summary.export_manifest(campaign_slug="batch")
        assert len(exported["assets"]) == 1
        assert exported["assets"][0]["renderedAssetId"] == rendered["id"]
        assert exported["assets"][0]["contentForgeRunId"] == "reel_review_batch"
        assert exported["assets"][0]["auditSummary"]["overallVerdict"] == "pass"
        assert (
            exported["assets"][0]["generatedAssetLineage"]["pipelineTraceId"]
            == "trace_review_1"
        )
    finally:
        cf.close()


def test_import_folder_rejects_self_attested_reel_review_package(tmp_path: Path):
    folder = tmp_path / "review_batch"
    folder.mkdir()
    (folder / "clip.mp4").write_bytes(b"video")
    (folder / "clip.png").write_bytes(b"png")
    contentforge_audit = folder / "contentforge_audit.json"
    contentforge_audit.write_text(
        json.dumps(
            {
                "auditProfile": "campaign_factory_v1",
                "variants": 1,
                "auditedFileCount": 1,
                "verdictCounts": {"pass": 1, "fail": 0},
                "overallVerdict": "pass",
            }
        )
    )
    raw_manifest = folder / "review_manifest.json"
    raw_manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "contentForgeAuditPath": str(contentforge_audit),
                "rows": [
                    {
                        "output": str(folder / "clip.mp4"),
                        "captionHash": "abc",
                        "overlayPng": str(folder / "clip.png"),
                    }
                ],
            }
        )
    )
    (folder / "review_package.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.review_batch_package.v1",
                "manifestPath": str(raw_manifest),
                "count": 1,
                "guard": {"status": "ready", "blockingReasons": [], "count": 1},
                "rows": [
                    {
                        "output": str(folder / "clip.mp4"),
                        "captionHash": "abc",
                        "overlayPng": str(folder / "clip.png"),
                    }
                ],
            }
        )
    )

    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="Reel Factory review guard failed"):
            cf.domains.asset_import.import_folder(
                folder, campaign_slug="batch", model_slug="model"
            )
    finally:
        cf.close()


def test_import_folder_rejects_foreign_reel_review_package(tmp_path: Path):
    folder = tmp_path / "review_batch"
    folder.mkdir()
    (folder / "clip.mp4").write_bytes(b"video")
    (folder / "clip.png").write_bytes(b"png")
    raw_manifest = folder / "review_manifest.json"
    raw_manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "rows": [
                    {
                        "output": str(folder / "clip.mp4"),
                        "captionHash": "abc",
                        "overlayPng": str(folder / "clip.png"),
                    }
                ],
            }
        )
    )
    foreign_manifest = tmp_path / "foreign_manifest.json"
    foreign_manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "rows": [
                    {
                        "output": str(folder / "clip.mp4"),
                        "captionHash": "abc",
                        "overlayPng": str(folder / "clip.png"),
                    }
                ],
            }
        )
    )
    (folder / "review_package.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.review_batch_package.v1",
                "manifestPath": str(foreign_manifest),
                "count": 1,
                "guard": {"status": "ready", "blockingReasons": [], "count": 1},
                "fileSha256": {
                    str(foreign_manifest): hashlib.sha256(
                        foreign_manifest.read_bytes()
                    ).hexdigest()
                },
                "rows": [
                    {
                        "output": str(folder / "clip.mp4"),
                        "captionHash": "abc",
                        "overlayPng": str(folder / "clip.png"),
                    }
                ],
            }
        )
    )

    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="does not match review manifest"):
            cf.domains.asset_import.import_folder(
                folder, campaign_slug="batch", model_slug="model"
            )
    finally:
        cf.close()


def test_import_folder_rejects_stale_reel_review_package_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    folder = tmp_path / "review_batch"
    folder.mkdir()
    clip = folder / "clip.mp4"
    overlay = folder / "clip.png"
    contentforge_audit = folder / "contentforge_audit.json"
    clip.write_bytes(b"video")
    overlay.write_bytes(b"png")
    contentforge_audit.write_text(
        json.dumps(
            {
                "auditProfile": "campaign_factory_v1",
                "variants": 1,
                "auditedFileCount": 1,
                "verdictCounts": {"pass": 1, "fail": 0},
                "overallVerdict": "pass",
            }
        )
    )
    raw_manifest = folder / "review_manifest.json"
    raw_manifest.write_text(
        json.dumps(
            {
                "schema": "creator_os.reel_review_batch.v1",
                "outputDir": str(folder),
                "captionPlacementPolicy": "focal-safe",
                "contentForgeAuditPath": str(contentforge_audit),
                "rows": [
                    {
                        "output": str(clip),
                        "captionHash": "abc",
                        "overlayPng": str(overlay),
                    }
                ],
            }
        )
    )
    stale_hash = hashlib.sha256(b"old video").hexdigest()
    (folder / "review_package.json").write_text(
        json.dumps(
            {
                "schema": "reel_factory.review_batch_package.v1",
                "manifestPath": str(raw_manifest),
                "count": 1,
                "guard": {"status": "ready", "blockingReasons": [], "count": 1},
                "fileSha256": {
                    str(raw_manifest.resolve()): hashlib.sha256(
                        raw_manifest.read_bytes()
                    ).hexdigest(),
                    str(contentforge_audit.resolve()): hashlib.sha256(
                        contentforge_audit.read_bytes()
                    ).hexdigest(),
                    str(clip.resolve()): stale_hash,
                    str(overlay.resolve()): hashlib.sha256(
                        overlay.read_bytes()
                    ).hexdigest(),
                },
                "rows": [
                    {
                        "output": str(clip),
                        "captionHash": "abc",
                        "overlayPng": str(overlay),
                    }
                ],
            }
        )
    )

    def fake_guard(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"status": "ready", "count": 1}),
            stderr="",
        )

    monkeypatch.setattr(
        asset_import_module,
        "subprocess",
        type("SubprocessStub", (), {"run": staticmethod(fake_guard)}),
        raising=False,
    )
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="review package hash mismatch"):
            cf.domains.asset_import.import_folder(
                folder, campaign_slug="batch", model_slug="model"
            )
    finally:
        cf.close()


def test_archive_candidate_quality_report_ranks_clean_candidates_and_excludes_worst_crop(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        for name in ["good_vertical.mp4", "square_crop.mp4", "low_res.mp4"]:
            (archive / name).write_bytes(name.encode("utf-8"))

        def fake_probe(path: Path) -> dict[str, object]:
            if path.name == "square_crop.mp4":
                return {
                    "ok": True,
                    "width": 960,
                    "height": 960,
                    "effectiveWidth": 960,
                    "effectiveHeight": 960,
                    "effectiveAspectRatio": 1.0,
                    "durationSeconds": 5.0,
                    "bitrate": 5_000_000,
                    "videoCodec": "h264",
                    "audioPresent": False,
                }
            if path.name == "low_res.mp4":
                return {
                    "ok": True,
                    "width": 540,
                    "height": 960,
                    "effectiveWidth": 540,
                    "effectiveHeight": 960,
                    "effectiveAspectRatio": 540 / 960,
                    "durationSeconds": 5.0,
                    "bitrate": 2_000_000,
                    "videoCodec": "h264",
                    "audioPresent": False,
                }
            return {
                "ok": True,
                "width": 720,
                "height": 1280,
                "effectiveWidth": 720,
                "effectiveHeight": 1280,
                "effectiveAspectRatio": 720 / 1280,
                "durationSeconds": 5.0,
                "bitrate": 5_000_000,
                "videoCodec": "h264",
                "audioPresent": False,
            }

        monkeypatch.setattr(core_module, "probe_video_metadata", fake_probe)
        inventory = cf.domains.archive_quality.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
        )

        quality = cf.domains.archive_quality.archive_candidate_quality_report(
            inventory_report_path=Path(inventory["reportPath"]),
            requested_count=2,
        )

        assert (
            quality["schema"] == "campaign_factory.archive_candidate_quality_report.v1"
        )
        assert quality["status"] == "ready_for_source_approval"
        selected_names = {
            item["filename"]
            for item in quality["items"]
            if item["recommendation"] == "selected_for_source_approval"
        }
        assert selected_names == {"good_vertical.mp4", "low_res.mp4"}
        square = next(
            item for item in quality["items"] if item["filename"] == "square_crop.mp4"
        )
        assert square["estimatedCropSeverity"] == "severe"
        assert square["recommendation"] == "alternate"
        assert Path(quality["reportPath"]).exists()
    finally:
        cf.close()


def test_archive_candidate_quality_report_blocks_when_ranked_inventory_is_short(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "only.mp4").write_bytes(b"only")
        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {
                "ok": True,
                "width": 720,
                "height": 1280,
                "effectiveWidth": 720,
                "effectiveHeight": 1280,
                "effectiveAspectRatio": 720 / 1280,
                "durationSeconds": 5.0,
                "bitrate": 5_000_000,
                "videoCodec": "h264",
                "audioPresent": False,
            },
        )
        inventory = cf.domains.archive_quality.archive_inventory_report(
            folder=archive,
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=1,
        )

        quality = cf.domains.archive_quality.archive_candidate_quality_report(
            inventory_report_path=Path(inventory["reportPath"]),
            requested_count=2,
        )

        assert quality["status"] == "blocked"
        assert quality["blockingReason"] == "insufficient_ranked_archive_inventory"
        assert quality["wouldProceedToRendering"] is False
    finally:
        cf.close()


def test_publishability_blocks_shouty_live_burned_caption(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        context = {
            "schema": "campaign_factory.caption_outcome_context.v1",
            "caption_hash": "bad_caption_hash",
            "caption_text": "GOING LIVE TONIGHT!!!",
            "caption_bank": "test_bank",
            "caption_banks": ["test_bank"],
            "creator_mix": "Test",
            "render_recipe": "v01_original",
            "captionPlacementPolicy": "focal_safe_v1",
            "captionPlacementDecision": {
                "status": "passed",
                "selectedLane": "center",
                "reason": "test fixture placement passed",
            },
            "instagram_post_caption": "simple today",
            "instagram_post_caption_hash": "post_hash",
            "burned_caption_text": "GOING LIVE TONIGHT!!!",
            "burned_caption_hash": "bad_caption_hash",
        }
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET caption = ?,
                caption_hash = ?,
                caption_outcome_context_json = ?,
                review_state = 'approved',
                audit_status = 'approved_candidate'
            WHERE id = 'asset_1'
            """,
            (
                "GOING LIVE TONIGHT!!!",
                "bad_caption_hash",
                json.dumps(context, ensure_ascii=False, sort_keys=True),
            ),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id="asset_1")

        publishability = cf.domains.publishability.explain_publishability("asset_1")

        assert publishability["burnedCaptionQualityPassed"] is False
        assert (
            "burned_caption_quality_failed"
            in publishability["publishability_failure_reasons"]
        )
        assert (
            "caption_placement_qc_failed"
            not in publishability["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_contentforge_cli_audit_records_pass_result(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(
        contentforge_root,
        *,
        source,
        target_file=None,
        audit_profile=None,
        layers,
        run_id=None,
    ):
        assert contentforge_root == cf.settings.contentforge_root
        assert source.startswith("campaign_factory_source_")
        assert target_file.startswith("campaign_factory_variant_")
        assert audit_profile == "campaign_factory_v1"
        assert "pdq" in layers
        return {
            "auditProfile": audit_profile,
            "targetFile": target_file,
            "layers": {"pdq": {"stats": {"avgDistance": 90}}},
            "verdicts": {"pdq": "pass"},
            "verdictCodes": {"pdq": "pdq_pass"},
            "overallVerdict": "pass",
            "readinessSummary": {
                "summaryText": "Upload-ready candidate with no blocking audit issues.",
                "uploadReady": True,
                "blockingReasons": [],
                "warnings": [],
                "blockingCodes": [],
                "warningCodes": [],
                "topWarnings": [],
                "recommendedAction": "approve_candidate",
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(
            cf, campaign_slug="may", contentforge_base_url="cli://local"
        )
        report = result["reports"][0]
        assert report["status"] == "approved_candidate"
        assert report["contentForgeMode"] == "cli_local"
        assert "contentForgeBaseUrl" not in report
        assert report["overallVerdict"] == "pass"
        assert report["auditProfile"] == "campaign_factory_v1"
        assert report["targetFile"].startswith("campaign_factory_variant_")
        assert report["verdictCodes"] == {"pdq": "pdq_pass"}
        assert report["readinessSummary"]["uploadReady"] is True
        assert report["filesAnalyzed"] == 1
        row = cf.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = 'asset_1'"
        ).fetchone()
        assert row["overall_verdict"] == "pass"
        assert json.loads(row["verdicts_json"]) == {"pdq": "pass"}
    finally:
        cf.close()


def test_contentforge_cli_audit_rejects_obsolete_http_mode(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        with pytest.raises(ValueError, match="runs as cli_local"):
            audit_campaign(
                cf,
                campaign_slug="may",
                contentforge_base_url="http://contentforge.test",
            )
    finally:
        cf.close()


def test_contentforge_audit_can_target_explicit_rendered_assets(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)

    def fake_similarity(*_args, **_kwargs):
        return {
            "layers": {"pdq": {}},
            "verdicts": {"pdq": "pass"},
            "overallVerdict": "pass",
            "readinessSummary": {
                "uploadReady": True,
                "blockingReasons": [],
                "warnings": [],
                "blockingCodes": [],
                "warningCodes": [],
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        original = dict(
            cf.conn.execute(
                "SELECT * FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()
        )
        original.update(
            id="asset_2",
            content_hash="hash_2",
            filename="second.mp4",
        )
        columns = list(original)
        cf.conn.execute(
            f"INSERT INTO rendered_assets ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            [original[column] for column in columns],
        )
        cf.conn.commit()

        result = audit_campaign(
            cf,
            campaign_slug="may",
            contentforge_base_url="cli://local",
            rendered_asset_ids=["asset_2"],
        )
        assert [report["renderedAssetId"] for report in result["reports"]] == [
            "asset_2"
        ]
        untouched = cf.conn.execute(
            "SELECT COUNT(*) AS count FROM audit_reports WHERE rendered_asset_id = 'asset_1'"
        ).fetchone()
        assert untouched["count"] == 0
        with pytest.raises(ValueError, match="rendered assets not found"):
            audit_campaign(
                cf,
                campaign_slug="may",
                rendered_asset_ids=["missing_asset"],
            )
    finally:
        cf.close()


def test_variation_batch_audit_sends_all_siblings_and_writes_report(
    tmp_path: Path, monkeypatch
):
    contentforge_root = tmp_path / "contentforge"
    source = tmp_path / "master.mp4"
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    source.write_bytes(b"master")
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    seen = {}

    def fake_similarity(contentforge_root_arg, **kwargs):
        seen["contentforge_root"] = contentforge_root_arg
        seen.update(kwargs)
        return {
            "contractVersion": "campaign_factory_audit.v1.7",
            "auditProfile": "campaign_factory_v1",
            "overallVerdict": "pass",
            "verdicts": {"pdq": "pass", "sscd": "pass"},
            "readinessSummary": {"uploadReady": True, "blockingCodes": []},
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    report_path = tmp_path / "audit.json"

    report = contentforge_adapter.audit_variation_batch(
        contentforge_root=contentforge_root,
        source_path=source,
        variant_paths=[first, second],
        contentforge_base_url="cli://local",
        report_path=report_path,
    )

    assert seen["contentforge_root"] == contentforge_root
    assert seen["layers"] == ["pdq", "sscd"]
    assert seen["target_file"].startswith("campaign_factory_variant_")
    assert len(seen["comparison_files"]) == 1
    assert report["contentForgeMode"] == "cli_local"
    assert report["reportPath"] == str(report_path)
    assert (
        json.loads(report_path.read_text(encoding="utf-8"))["verdicts"]["pdq"] == "pass"
    )


def test_contentforge_cli_audit_records_warn_and_fail_results(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)

    def fake_similarity(
        base_url,
        *,
        source,
        target_file=None,
        audit_profile=None,
        layers,
        run_id=None,
    ):
        return {
            "layers": {"pdq": {}, "sscd": {}},
            "verdicts": {"pdq": "warn", "sscd": "fail"},
            "overallVerdict": "fail",
            "readinessSummary": {
                "blockingCodes": ["sscd_failed"],
                "warningCodes": ["pdq_review"],
                "blockingReasons": ["sscd: layer failed"],
                "warnings": ["pdq: layer warning"],
                "uploadReady": False,
                "recommendedAction": "reject",
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["status"] == "needs_review"
        assert report["score"] == 0
        assert report["failedChecks"] == ["sscd", "sscd_failed"]
        assert report["warnings"] == ["pdq", "pdq_review"]
    finally:
        cf.close()


def test_contentforge_cli_audit_keeps_review_only_layer_failures_nonblocking(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)

    def fake_similarity(
        base_url,
        *,
        source,
        target_file=None,
        audit_profile=None,
        layers,
        run_id=None,
    ):
        return {
            "layers": {"sscd": {}},
            "verdicts": {"sscd": "fail"},
            "overallVerdict": "warn",
            "readinessSummary": {
                "blockingCodes": [],
                "warningCodes": ["sscd_review"],
                "blockingReasons": [],
                "warnings": ["sscd: layer needs review"],
                "uploadReady": True,
                "recommendedAction": "review",
            },
            "filesAnalyzed": 1,
        }

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["score"] == 84
        assert report["failedChecks"] == []
        assert report["warnings"] == ["sscd_review"]
        readiness = cf.domains.campaign_overview.dashboard("may")["rendered"][0][
            "export_readiness"
        ]
        assert not any(
            reason.startswith("audit_failed:sscd")
            for reason in readiness["blockingReasons"]
        )
    finally:
        cf.close()


def test_contentforge_cli_audit_handles_malformed_response(tmp_path: Path, monkeypatch):
    cf = make_factory(tmp_path)

    def fake_similarity(
        base_url,
        *,
        source,
        target_file=None,
        audit_profile=None,
        layers,
        run_id=None,
    ):
        return {"layers": {}, "verdicts": {}, "filesAnalyzed": 1}

    monkeypatch.setattr(contentforge_adapter, "_post_similarity", fake_similarity)
    try:
        add_rendered_asset(cf, tmp_path)
        result = audit_campaign(cf, campaign_slug="may")
        report = result["reports"][0]
        assert report["status"] == "needs_review"
        assert "contentforge_malformed_response" in report["failedChecks"]
        assert report["overallVerdict"] == "fail"
    finally:
        cf.close()


def test_end_to_end_smoke_import_audit_approve_export(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"source")
    cf = make_factory(tmp_path)
    try:
        imported = cf.domains.asset_import.import_folder(
            folder, campaign_slug="launch", model_slug="model", account_handles=["ig_a"]
        )
        source = imported["imported"][0]
        set_test_source_prompt(cf, source["id"])
        rendered_path = tmp_path / "rendered.mp4"
        rendered_path.write_bytes(b"rendered")
        rendered_hash = hashlib.sha256(rendered_path.read_bytes()).hexdigest()
        now = "2026-01-01T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_smoke', ?, ?, ?, ?, ?, 'rendered.mp4', 'caption', 'v01_original', 'pending', 'draft', ?, ?)
            """,
            (
                source["campaign_id"],
                source["id"],
                rendered_hash,
                str(rendered_path),
                str(rendered_path),
                now,
                now,
            ),
        )
        cf.conn.commit()
        audit = audit_campaign(cf, campaign_slug="launch")
        assert audit["reports"][0]["status"] == "needs_review"
        blocked = export_threadsdash(
            cf, campaign_slug="launch", user_id="user_1", dry_run=True
        )
        assert blocked["draftCount"] == 0
        cf.domains.finished_video.approve_rendered_asset("asset_smoke")
        exported = export_threadsdash(
            cf, campaign_slug="launch", user_id="user_1", dry_run=True
        )
        assert exported["path"] is None
        assert exported["pipelineJobId"] is None
        assert not Path(exported["wouldWritePath"]).exists()
        assert exported["draftCount"] == 1
        draft = exported["payload"]["drafts"][0]
        assert draft["status"] == "draft"
        assert "scheduledFor" not in draft
    finally:
        cf.close()


def test_review_decision_supports_reject_and_approve(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        rejected = cf.domains.finished_video.review_rendered_asset(
            "asset_1", decision="rejected", notes="no"
        )
        assert rejected["review_state"] == "rejected"
        approved = cf.domains.finished_video.review_rendered_asset(
            "asset_1", decision="approved", notes="ok"
        )
        assert approved["review_state"] == "approved"
        decisions = cf.conn.execute(
            "SELECT decision FROM approval_decisions ORDER BY created_at"
        ).fetchall()
        assert [row["decision"] for row in decisions] == ["rejected", "approved"]
    finally:
        cf.close()


def test_operator_approval_requires_safe_audit_when_guard_enabled(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        with pytest.raises(ValueError, match="audit_status:pending"):
            cf.domains.finished_video.review_rendered_asset(
                "asset_1", decision="approved", require_safe_audit=True
            )

        cf.conn.execute(
            "UPDATE rendered_assets SET audit_status = 'approved_candidate' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        approved = cf.domains.finished_video.review_rendered_asset(
            "asset_1", decision="approved", require_safe_audit=True
        )

        assert approved["review_state"] == "approved"

        cf.conn.execute(
            "UPDATE rendered_assets SET audit_status = 'needs_review', review_state = 'review_ready' WHERE id = 'asset_1'"
        )
        cf.conn.commit()
        warning_only = cf.domains.finished_video.review_rendered_asset(
            "asset_1", decision="approved", require_safe_audit=True
        )

        assert warning_only["review_state"] == "approved"
    finally:
        cf.close()


def test_publishability_blocks_passthrough_captioned_media_before_export(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    rows = []

    class FakeClient:
        def __init__(self, url: str, service_role_key: str):
            self.url = url

        def select(self, table, params):
            return rows

    monkeypatch.setattr(threadsdash_client_adapter, "SupabaseRestClient", FakeClient)
    try:
        add_rendered_asset(cf, tmp_path, filename="proof_v00_passthrough.mp4")
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        readiness = evaluate_export_readiness(
            cf,
            campaign_slug="may",
            user_id="user_1",
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
        )

        assert readiness["liveExportAllowed"] is False
        assert readiness["assets"][0]["publishability"]["publishableCandidate"] is False
        assert (
            readiness["assets"][0]["publishability"]["publishability_failure_reasons"]
            == readiness["assets"][0]["publishability"]["failureReasons"]
        )
        assert (
            "missing_burned_captions"
            in readiness["assets"][0]["publishability"][
                "publishability_failure_reasons"
            ]
        )

        with pytest.raises(
            ValueError,
            match="export blocked by (readiness|publishability|handoff manifest)",
        ):
            export_threadsdash(
                cf,
                campaign_slug="may",
                user_id="user_1",
                dry_run=False,
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="service-role",
            )
    finally:
        cf.close()


def test_publishability_uses_review_package_generated_lineage_for_caption_placement(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        caption_generation = {
            "instagram_post_caption": "new post",
            "audioIntent": {
                "schema": "pipeline.audio_intent.v1",
                "mode": "native_platform_audio",
                "required": False,
                "status": "not_required",
            },
            "generatedAssetLineage": {
                "schema": "reel_factory.generated_asset_lineage.v1",
                "captionPlacementPolicy": "focal-safe",
                "captionPlacementDecision": {
                    "status": "passed",
                    "selectedLane": "bottom",
                    "scores": {"top": 10, "center": 20, "bottom": 5},
                    "components": {"top": {}, "center": {}, "bottom": {}},
                    "sampleCount": 3,
                },
            },
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ?, caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(context, sort_keys=True),
                json.dumps(caption_generation, sort_keys=True),
            ),
        )
        cf.conn.commit()

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["captionPlacementPolicy"] == "focal_safe_v1"
        assert explanation["captionPlacementDecision"]["selectedLane"] == "bottom"
        assert explanation["checks"]["caption_placement_qc_passed"] is True
        assert (
            "caption_placement_qc_failed"
            not in explanation["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_operator_publishability_attestation_supplies_caption_visual_and_identity_evidence(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        audit = add_audit_report(cf)
        Path(audit["path"]).write_text(
            json.dumps(
                {
                    "readinessSummary": {
                        "uploadReady": True,
                        "blockingReasons": [],
                        "blockingCodes": [],
                    },
                    "overallVerdict": "pass",
                }
            ),
            encoding="utf-8",
        )
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        context.pop("instagram_post_caption", None)
        context.pop("instagram_post_caption_hash", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ?, caption_generation_json = ?, metadata_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(context, sort_keys=True),
                json.dumps(
                    {
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": False,
                            "status": "not_required",
                        }
                    },
                    sort_keys=True,
                ),
                "{}",
            ),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")

        before = cf.domains.publishability.explain_publishability("asset_1")
        assert (
            "missing_instagram_post_caption" in before["publishability_failure_reasons"]
        )
        assert "visual_qc_unavailable" in before["publishability_failure_reasons"]
        assert (
            "identity_verification_unavailable"
            in before["publishability_failure_reasons"]
        )

        result = cf.domains.finished_video.attest_publishability_evidence(
            "asset_1",
            instagram_post_caption="pick one",
            visual_qc_status="passed",
            identity_verification_status="passed",
            operator="tester",
            notes="operator reviewed rendered reel",
        )
        assert result["attestation"]["visualQcStatus"] == "passed"

        after = cf.domains.publishability.explain_publishability("asset_1")
        assert after["instagram_post_caption"] == "pick one"
        assert after["checks"]["instagram_post_caption_quality_passed"] is True
        assert after["visualQcStatus"] == "passed"
        assert after["identityVerificationStatus"] == "passed"
        assert (
            "missing_instagram_post_caption"
            not in after["publishability_failure_reasons"]
        )
        assert "visual_qc_unavailable" not in after["publishability_failure_reasons"]
        assert (
            "identity_verification_unavailable"
            not in after["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_publishability_blocks_missing_caption_placement_qc(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = 'asset_1'",
            (json.dumps(context, sort_keys=True),),
        )
        cf.conn.commit()

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert (
            "caption_placement_qc_failed"
            in explanation["publishability_failure_reasons"]
        )
        assert explanation["checks"]["caption_placement_qc_passed"] is False
    finally:
        cf.close()


def test_publishability_blocks_failed_caption_placement_qc(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        context["captionPlacementDecision"] = {
            "status": "failed",
            "selectedLane": "center",
            "reason": "center overlaps face",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ? WHERE id = 'asset_1'",
            (json.dumps(context, sort_keys=True),),
        )
        cf.conn.commit()

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert explanation["captionPlacementPolicy"] == "focal_safe_v1"
        assert explanation["captionPlacementDecision"]["status"] == "failed"
        assert (
            "caption_placement_qc_failed"
            in explanation["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_publishability_blocks_caption_safe_zone_audit_warning(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(
            cf,
            warnings=[
                "Caption-like text may overlap bottom or right-side Reels UI controls"
            ],
            warning_codes=["caption_overlaps_ui_safe_zone"],
        )

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert explanation["checks"]["caption_placement_qc_passed"] is False
        assert (
            "caption_placement_qc_failed"
            in explanation["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_publishability_blocks_blank_instagram_post_caption(tmp_path: Path):
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
                        "instagram_post_caption": "",
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

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert (
            "missing_instagram_post_caption"
            in explanation["publishability_failure_reasons"]
        )
    finally:
        cf.close()


def test_publishability_blocks_unavailable_visual_qc_or_identity_verification(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        audit = add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        audit_path = Path(audit["path"])
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        payload["readinessSummary"]["visualQcStatus"] = "unavailable"
        payload["readinessSummary"]["identityVerificationStatus"] = "failed"
        payload["visualQcStatus"] = "unavailable"
        payload["identityVerificationStatus"] = "failed"
        payload["visualQc"] = {"status": "unavailable"}
        payload["identityVerification"] = {"status": "failed"}
        audit_path.write_text(json.dumps(payload), encoding="utf-8")

        explanation = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )

        assert explanation["publishableCandidate"] is False
        assert explanation["checks"]["visual_qc_passed"] is False
        assert explanation["checks"]["identity_verification_passed"] is False
        assert explanation["visualQcStatus"] == "unavailable"
        assert explanation["identityVerificationStatus"] == "failed"
        assert "visual_qc_unavailable" in explanation["publishability_failure_reasons"]
        assert (
            "identity_verification_failed"
            in explanation["publishability_failure_reasons"]
        )
        assert explanation["handoff_manifest"] is None
    finally:
        cf.close()


def test_publishability_blocks_reel_captions_with_text_me_language(tmp_path: Path):
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
                        "instagram_post_caption": "too scared to text me",
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

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert (
            "unsafe_reel_caption_link_or_dm_reference"
            in explanation["publishability_failure_reasons"]
        )
        assert explanation["checks"]["reel_caption_account_safety_passed"] is False
        assert {
            item["reason"] for item in explanation["reelCaptionAccountSafetyViolations"]
        } == {"dm_reference"}
    finally:
        cf.close()


def test_publishability_blocks_low_quality_instagram_post_caption(tmp_path: Path):
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
                        "instagram_post_caption": (
                            "this is a very long caption that should not be used under a Reel because it reads like generated copy "
                            "instead of a simple Instagram caption and it keeps rambling way past the limit"
                        ),
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

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert (
            "instagram_post_caption_quality_failed"
            in explanation["publishability_failure_reasons"]
        )
        assert explanation["checks"]["instagram_post_caption_quality_passed"] is False
        assert explanation["instagramPostCaptionQuality"]["reasons"] == [
            "instagram_post_caption_too_long"
        ]
    finally:
        cf.close()


def test_caption_quality_repair_plan_is_read_only_and_recovers_long_caption(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        burned_before = context["caption_text"]
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": (
                            "this caption is too long and keeps going because it is not the simple native style we want "
                            "under Instagram posts when the asset should be safe for scheduling"
                        ),
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
        before = {
            "rendered_assets": table_count(cf, "rendered_assets"),
            "caption_versions": table_count(cf, "caption_versions"),
            "distribution_plans": table_count(cf, "distribution_plans"),
            "total_changes": cf.conn.total_changes,
        }

        plan = cf.domains.publishability.caption_quality_repair_plan(creator="Test")

        after_context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        assert plan["schema"] == "campaign_factory.caption_quality_repair_plan.v1"
        assert plan["wouldWrite"] is False
        assert plan["blockedByCaptionQuality"] == 1
        assert plan["recoverableByCaptionRewrite"] == 1
        assert plan["recoverableByHashtagTrim"] == 0
        assert plan["recoverableByCTARemoval"] == 0
        assert plan["unrecoverable"] == 0
        candidate = plan["replacementCandidates"][0]
        assert candidate["assetId"] == "asset_1"
        assert candidate["recoveryClass"] == "recoverableByCaptionRewrite"
        assert (
            candidate["suggestedInstagramPostCaption"]
            in core_module.SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL
        )
        assert candidate["wouldPassQualityGate"] is True
        assert candidate["burnedCaptionText"] == burned_before
        assert after_context["caption_text"] == burned_before
        assert {
            "rendered_assets": table_count(cf, "rendered_assets"),
            "caption_versions": table_count(cf, "caption_versions"),
            "distribution_plans": table_count(cf, "distribution_plans"),
            "total_changes": cf.conn.total_changes,
        } == before
    finally:
        cf.close()


def test_caption_quality_repair_plan_classifies_hashtag_and_cta_repairs(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        rendered_path = tmp_path / "asset_2.mp4"
        rendered_path.write_bytes(b"rendered-2")
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename,
             caption, caption_hash, caption_outcome_context_json, recipe, audit_status, review_state,
             caption_generation_json, created_at, updated_at)
            VALUES ('asset_2', ?, ?, 'hash_2', ?, ?, 'asset_2.mp4', 'caption', 'caption_hash_2',
                    ?, 'v01_original', 'passed', 'approved', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
                json.dumps(
                    {**context, "caption_hash": "caption_hash_2"}, sort_keys=True
                ),
            ),
        )
        add_audit_report(cf, rendered_asset_id="asset_2", audit_id="audit_asset_2")
        cf.domains.finished_video.review_rendered_asset("asset_2", decision="approved")
        common_audio = {
            "schema": "pipeline.audio_intent.v1",
            "mode": "native_platform_audio",
            "required": False,
            "status": "not_required",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "pick one\n#one #two #three #four #five #six",
                        "hashtags": [
                            "#one",
                            "#two",
                            "#three",
                            "#four",
                            "#five",
                            "#six",
                        ],
                        "audioIntent": common_audio,
                    }
                ),
            ),
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_2'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "DM me for the link",
                        "audioIntent": common_audio,
                    }
                ),
            ),
        )
        cf.conn.commit()

        plan = cf.domains.publishability.caption_quality_repair_plan(creator="Test")
        by_asset = {item["assetId"]: item for item in plan["replacementCandidates"]}

        assert plan["blockedByCaptionQuality"] == 2
        assert plan["recoverableByHashtagTrim"] == 1
        assert plan["recoverableByCTARemoval"] == 1
        assert by_asset["asset_1"]["recoveryClass"] == "recoverableByHashtagTrim"
        assert by_asset["asset_2"]["recoveryClass"] == "recoverableByCTARemoval"
        assert by_asset["asset_1"]["wouldPassQualityGate"] is True
        assert by_asset["asset_2"]["wouldPassQualityGate"] is True
    finally:
        cf.close()


def test_caption_quality_repair_plan_marks_non_caption_blockers_unrecoverable(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        context = json.loads(
            cf.conn.execute(
                "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = 'asset_1'"
            ).fetchone()[0]
        )
        context.pop("captionPlacementPolicy", None)
        context.pop("captionPlacementDecision", None)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_outcome_context_json = ?, caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(context, sort_keys=True),
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

        plan = cf.domains.publishability.caption_quality_repair_plan(creator="Test")
        candidate = plan["replacementCandidates"][0]

        assert plan["blockedByCaptionQuality"] == 1
        assert plan["unrecoverable"] == 1
        assert candidate["recoveryClass"] == "unrecoverable"
        assert "caption_placement_qc_failed" in candidate["nonCaptionBlockers"]
        assert candidate["wouldPassQualityGate"] is False
    finally:
        cf.close()


def test_contentforge_visual_qc_failure_report_classifies_operator_review_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        add_schedule_safe_production_asset(
            cf, tmp_path, asset_id="parent_fresh", source=source
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_pass",
            source=source,
            parent_asset_id="parent_fresh",
        )
        ensure_exportable_distribution_plan(cf, "variant_pass")
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="variant_operator_review",
            source=source,
            parent_asset_id="parent_fresh",
            filename="variant_audio_preview_review.mp4",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = (
            cf.domains.contentforge_visual_qc.contentforge_visual_qc_failure_report(
                creator="Test",
                content_surface="reel",
                lookback_days=1,
                current_inventory=11,
                required_inventory=225,
            )
        )
        by_category = {
            row["failureCategory"]: row for row in report["failureCategories"]
        }

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.contentforge_visual_qc_failure_report.v1"
        assert report["variantsAnalyzed"] == 2
        assert report["visualQcFailed"] == 1
        assert by_category["operator_visual_review_required"]["count"] == 1
        assert by_category["operator_visual_review_required"]["repairable"] is True
        assert (
            report["largestVisualQCLoss"]["largestFailureCategory"]
            == "operator_visual_review_required"
        )
        assert (
            report["recoveryProjection"]["inventoryRecoveredIfTopVisualIssueFixed"] == 1
        )
        assert report["recoveryProjection"]["remainingGap"] == 213
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_contentforge_visual_qc_reports_zero_failure_window(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        report = cf.domains.contentforge_visual_qc.contentforge_visual_qc_waterfall(
            creator="Test",
            content_surface="reel",
            lookback_days=1,
            current_inventory=11,
            required_inventory=225,
        )

        assert report["schema"] == "creator_os.contentforge_visual_qc_waterfall.v1"
        assert report["waterfall"]["variantsCreated"] == 0
        assert report["waterfall"]["visualQcFailed"] == 0
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_operator_inventory_review_batch_plan_prioritizes_safe_repairs_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="asset_safe_combo",
            source=source,
            filename="asset_safe_combo_audio_preview_test.mp4",
            caption_generation={
                "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                "audioIntent": {
                    "schema": "pipeline.audio_intent.v1",
                    "mode": "native_platform_audio",
                    "required": False,
                    "status": "not_required",
                },
            },
        )
        add_schedule_safe_production_asset(
            cf,
            tmp_path,
            asset_id="asset_wrong_visual",
            source=source,
            filename="asset_wrong_visual_passthrough.mp4",
        )
        cf.conn.commit()
        before = cf.conn.total_changes

        plan = cf.domains.operator_review.operator_inventory_review_batch_plan(
            creator="Test",
            content_surface="reel",
            required_inventory=2,
            current_inventory=0,
            target_unlock=1,
        )

        assert cf.conn.total_changes == before
        assert plan["schema"] == "creator_os.operator_inventory_review_batch_plan.v1"
        assert plan["reviewCandidates"] == 1
        assert plan["recommendedReviewBatchSize"] == 1
        assert plan["reviewBatch"][0]["assetId"] == "asset_safe_combo"
        assert "asset_wrong_visual" not in {
            row["assetId"] for row in plan["reviewBatch"]
        }
        assert plan["estimatedInventoryGain"] == 1
        assert plan["safeRepairsOnly"] is True
        assert plan["wouldWrite"] is False
    finally:
        cf.close()


def test_operator_review_simulator_models_approval_rates_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        source, _ = add_rendered_asset(cf, tmp_path)
        cf.conn.execute("DELETE FROM rendered_assets")
        cf.conn.commit()
        for index in range(4):
            add_schedule_safe_production_asset(
                cf,
                tmp_path,
                asset_id=f"asset_caption_{index}",
                source=source,
                caption_generation={
                    "instagram_post_caption": "this caption is too long and keeps going because it is not the simple native style we want under Instagram posts when the asset should be safe for scheduling and it keeps adding more unnecessary words",
                    "audioIntent": {
                        "schema": "pipeline.audio_intent.v1",
                        "mode": "native_platform_audio",
                        "required": False,
                        "status": "not_required",
                    },
                },
            )
        cf.conn.commit()
        before = cf.conn.total_changes

        report = cf.domains.operator_review.operator_review_simulator(
            creator="Test",
            content_surface="reel",
            required_inventory=4,
            current_inventory=0,
        )
        scenarios = {row["approvalRate"]: row for row in report["scenarios"]}

        assert cf.conn.total_changes == before
        assert report["schema"] == "creator_os.operator_review_simulator.v1"
        assert scenarios[50]["assetsReviewed"] == 4
        assert scenarios[50]["assetsRecovered"] == 2
        assert scenarios[50]["passes25AccountGate"] is False
        assert scenarios[100]["assetsRecovered"] == 4
        assert scenarios[100]["passes25AccountGate"] is True
        assert report["minimumAssetsReviewedToPass25Gate"] == 4
        assert report["minimumOperatorMinutesToPass25Gate"] == 8
        assert report["highestROIBatchType"] == "caption_only"
        assert report["lowestRiskBatchType"] == "caption_only"
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_publishability_blocks_embedded_audio_claim_when_mp4_has_no_audio(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "audioIntent": {
                            "schema": "pipeline.audio_intent.v1",
                            "mode": "native_platform_audio",
                            "required": True,
                            "status": "attached",
                            "operator_selection": {
                                "audio_id": "cml_insomniac_ella_boh",
                                "track_id": "cml_insomniac_ella_boh",
                                "track_name": "iNSOMNiAC",
                                "selected_at": "2026-06-06T04:31:02+00:00",
                                "attached_at": "2026-06-06T04:31:02+00:00",
                                "source": "tiktok_cml",
                                "notes": "Audio is embedded in the registered MP4.",
                            },
                        }
                    }
                ),
            ),
        )
        cf.conn.commit()
        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {"ok": True, "audioPresent": False},
        )

        explanation = cf.domains.publishability.explain_publishability("asset_1")

        assert explanation["publishableCandidate"] is False
        assert explanation["checks"]["embedded_audio_verified"] is False
        assert "embedded_audio_missing" in explanation["publishability_failure_reasons"]
    finally:
        cf.close()


def test_publishability_accepts_licensed_local_audio_embedded_in_mp4(
    tmp_path: Path, monkeypatch
):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)
        cf.conn.execute(
            "UPDATE rendered_assets SET caption_generation_json = ? WHERE id = 'asset_1'",
            (
                json.dumps(
                    {
                        "instagram_post_caption": "new post",
                        "audioIntent": {
                            "schema": "reel_factory.audio_intent.v1",
                            "mode": "licensed_music",
                            "required": True,
                            "status": "planned",
                            "audio_selection": {
                                "source": "local_audio",
                                "path": str(tmp_path / "licensed.m4a"),
                            },
                        },
                    }
                ),
            ),
        )
        cf.conn.commit()
        monkeypatch.setattr(
            core_module,
            "probe_video_metadata",
            lambda path: {"ok": True, "audioPresent": True},
        )

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_1", instagram_account_id="ig_1"
        )
        explanation = cf.domains.publishability.explain_publishability(
            "asset_1", distribution_plan_id=plan["id"]
        )

        assert explanation["publishableCandidate"] is True
        assert explanation["checks"]["audio_assigned"] is True
        assert explanation["checks"]["embedded_audio_verified"] is True
        assert explanation["audioIntent"]["mode"] == "licensed_music"
        assert (
            explanation["audioIntent"]["operator_selection"]["selection_source"]
            == "embedded_licensed_audio"
        )
    finally:
        cf.close()


def test_multi_surface_inventory_audit_counts_schedule_safe_by_surface(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(
            cf,
            tmp_path,
            asset_id="asset_reel_safe",
            campaign_slug="stacey_surface_inventory_20260606",
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET content_surface = 'reel', media_type = 'video' WHERE id = 'asset_reel_safe'"
        )
        cf.domains.distribution.create_distribution_plan(
            "asset_reel_safe", surface="reel", instagram_account_id="ig_stacey_1"
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_safe",
            content_surface="feed_single",
            media_type="image",
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_feed_blocked",
            content_surface="feed_single",
            media_type="image",
            instagram_post_caption="",
        )
        add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_safe",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
        )

        report = cf.domains.surface_inventory.multi_surface_inventory_audit(
            creator="Stacey"
        )

        assert report["inventoryBySurface"]["reel"] == {"total": 1, "scheduleSafe": 1}
        assert report["inventoryBySurface"]["story"] == {"total": 1, "scheduleSafe": 1}
        assert report["inventoryBySurface"]["feed_single"] == {
            "total": 2,
            "scheduleSafe": 1,
        }
        assert report["inventoryBySurface"]["feed_carousel"] == {
            "total": 0,
            "scheduleSafe": 0,
        }
        assert report["wouldWrite"] is False
    finally:
        cf.close()


def test_story_quality_gate_1080x1920_passes(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_1080")

        result = cf.domains.story_management.story_quality_gate_v1("asset_story_1080")

        assert result["story_quality_gate_passed"] is True
        assert result["geometry"]["passed"] is True
        assert result["storyBlackBarCheck"]["blackBarsDetected"] is False
        assert result["wouldWrite"] is False
    finally:
        cf.close()


@pytest.mark.parametrize(
    "asset_id,width,height,reason",
    [
        ("asset_story_square", 1080, 1080, "invalid_story_aspect_ratio"),
        ("asset_story_landscape", 1920, 1080, "invalid_story_aspect_ratio"),
    ],
)
def test_story_quality_gate_blocks_non_story_geometry(
    tmp_path: Path, asset_id: str, width: int, height: int, reason: str
):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(
            cf, tmp_path, asset_id=asset_id, width=width, height=height
        )

        result = cf.domains.story_management.story_quality_gate_v1(asset_id)

        assert result["story_quality_gate_passed"] is False
        assert reason in result["failureReasons"]
    finally:
        cf.close()


def test_story_quality_gate_blocks_black_bars(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(
            cf, tmp_path, asset_id="asset_story_bars", bars={"top", "bottom"}
        )

        result = cf.domains.story_management.story_quality_gate_v1("asset_story_bars")

        assert result["storyBlackBarCheck"]["blackBarsDetected"] is True
        assert "black_bars" in result["failureReasons"]
    finally:
        cf.close()


@pytest.mark.parametrize(
    "asset_id,quality_metadata,reason",
    [
        ("asset_story_safe_zone", {"story_safe_zone_score": 70}, "safe_zone_violation"),
        (
            "asset_story_head_cutoff",
            {"story_focal_safety_score": 65, "focalFailureReason": "head_cutoff"},
            "head_cutoff",
        ),
        (
            "asset_story_text_hidden",
            {"containsRenderedText": True, "story_text_readability_score": 60},
            "text_hidden",
        ),
    ],
)
def test_story_quality_gate_blocks_safe_zone_focal_and_text_failures(
    tmp_path: Path, asset_id: str, quality_metadata: dict, reason: str
):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(
            cf, tmp_path, asset_id=asset_id, quality_metadata=quality_metadata
        )

        result = cf.domains.story_management.story_quality_gate_v1(asset_id)

        assert result["story_quality_gate_passed"] is False
        assert reason in result["failureReasons"]
    finally:
        cf.close()


def test_story_quality_report_and_readiness_use_quality_gate(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_story_quality_asset(cf, tmp_path, asset_id="asset_story_quality_pass")
        add_story_quality_asset(
            cf, tmp_path, asset_id="asset_story_quality_fail", bars={"left"}
        )

        report = cf.domains.story_management.story_quality_report(creator="Stacey")
        readiness = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id="asset_story_quality_fail"
        )
        inventory = cf.domains.story_management.story_inventory_report(creator="Stacey")

        assert report["storyAssetsAnalyzed"] == 2
        assert report["passed"] == 1
        assert report["failed"] == 1
        assert "black_bars" in report["failureReasons"]
        assert readiness["assets"][0]["canHandoff"] is False
        assert "story_quality_gate_failed" in readiness["assets"][0]["blockingReasons"]
        assert inventory["storyAssetsQualityPassed"] == 1
        assert inventory["storyAssetsScheduleSafe"] == 1
        assert inventory["wouldWrite"] is False
    finally:
        cf.close()


def test_story_quality_gate_blocks_existing_story_with_reel_render_lineage(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        asset = add_surface_asset_fixture(
            cf,
            tmp_path,
            asset_id="asset_story_bad_lineage",
            content_surface="story",
            media_type="image",
            instagram_post_caption="",
            target_ratio="9:16",
        )
        reel_rendered = (
            tmp_path
            / "campaign_factory"
            / "campaigns"
            / "stacey"
            / "variant_fanout"
            / "02_rendered"
            / "parent_repair_captioned.mp4"
        )
        reel_rendered.parent.mkdir(parents=True)
        reel_rendered.write_bytes(b"not-used")
        cf.conn.execute(
            "UPDATE rendered_assets SET source_clip = ? WHERE id = ?",
            (str(reel_rendered), asset["id"]),
        )
        cf.conn.commit()

        quality = cf.domains.story_management.story_quality_gate_v1(asset["id"])

        assert quality["story_quality_gate_passed"] is False
        assert (
            "story_source_must_be_raw_not_rendered_reel_asset"
            in quality["failureReasons"]
        )
        assert (
            "story_source_appears_to_have_burned_caption_or_reel_lineage"
            in quality["failureReasons"]
        )
        readiness = cf.domains.surface_handoff.surface_handoff_readiness_report(
            creator="Stacey", rendered_asset_id=asset["id"]
        )
        assert "story_quality_gate_failed" in readiness["assets"][0]["blockingReasons"]
    finally:
        cf.close()


def test_ad_hoc_inventory_fill_variant_requires_operator_visual_review(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_1")
        add_variant_fixture(
            cf,
            tmp_path,
            variant_asset_id="asset_ad_hoc_inventory_variant",
            variant_family_id="vfam_ad_hoc",
            variant_index=1,
        )
        operations = [
            {
                "type": "inventory_fill_ffmpeg_variant",
                "operationFamily": "color_profile",
                "operation": "color_profile_warm_safe",
            },
            {"type": "preserve_parent_lineage", "parentAssetId": "asset_1"},
        ]
        cf.conn.execute(
            "UPDATE rendered_assets SET variant_operations_json = ? WHERE id = ?",
            (
                json.dumps(operations, ensure_ascii=False, sort_keys=True),
                "asset_ad_hoc_inventory_variant",
            ),
        )
        cf.conn.execute(
            "UPDATE variant_assets SET operations_json = ? WHERE variant_asset_id = ?",
            (
                json.dumps(operations, ensure_ascii=False, sort_keys=True),
                "asset_ad_hoc_inventory_variant",
            ),
        )
        cf.conn.commit()

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_ad_hoc_inventory_variant", surface="regular_reel"
        )
        publishability = cf.domains.publishability.explain_publishability(
            "asset_ad_hoc_inventory_variant", distribution_plan_id=plan["id"]
        )
        readiness = cf.domains.surface_handoff.surface_handoff_readiness_for_asset(
            cf.domains.rendered_asset("asset_ad_hoc_inventory_variant")
        )

        assert (
            "operator_visual_review_required"
            in publishability["publishability_failure_reasons"]
        )
        assert "operator_visual_review_required" in readiness["blockingReasons"]
        assert readiness["canHandoff"] is False
    finally:
        cf.close()


def test_audio_preview_reel_requires_operator_visual_review(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_inventory_parent_fixture(cf, tmp_path, asset_id="asset_audio_preview")
        preview_path = (
            tmp_path
            / "stacey_archive_01_src19_caption_bg_light_audio_preview_asset_audio_preview.mp4"
        )
        preview_path.write_bytes(b"preview-render")
        cf.conn.execute(
            """
            UPDATE rendered_assets
            SET filename = ?, output_path = ?, campaign_path = ?
            WHERE id = 'asset_audio_preview'
            """,
            (preview_path.name, str(preview_path), str(preview_path)),
        )
        cf.conn.commit()

        plan = cf.domains.distribution.create_distribution_plan(
            "asset_audio_preview", surface="regular_reel"
        )
        publishability = cf.domains.publishability.explain_publishability(
            "asset_audio_preview", distribution_plan_id=plan["id"]
        )
        readiness = cf.domains.surface_handoff.surface_handoff_readiness_for_asset(
            cf.domains.rendered_asset("asset_audio_preview")
        )

        assert (
            "operator_visual_review_required"
            in publishability["publishability_failure_reasons"]
        )
        assert "operator_visual_review_required" in readiness["blockingReasons"]
        assert readiness["canHandoff"] is False
    finally:
        cf.close()


def test_explain_publishability_and_quarantine_bad_asset(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        add_rendered_asset(cf, tmp_path, filename="proof_v00_passthrough.mp4")
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        add_audit_report(cf)

        explanation = cf.domains.publishability.explain_publishability("asset_1")
        assert explanation["asset_state"] == "approved_but_not_publishable"
        assert explanation["approved"] is True
        assert (
            "missing_burned_captions" in explanation["publishability_failure_reasons"]
        )
        assert explanation["rootCause"] == "wrong_approved_asset"

        quarantine = cf.domains.publishability.quarantine_asset(
            "asset_1",
            reason="threadsdash_draft_media_invalid_missing_burned_captions",
            root_cause="wrong_approved_asset",
            threadsdash_post_id="8ee460e1-4f4e-4298-9597-462223b3f5cb",
            created_by="test",
        )
        assert quarantine["excluded_from_metrics"] == 1

        after = cf.domains.publishability.explain_publishability("asset_1")
        assert "quarantined_asset" in after["publishability_failure_reasons"]
        assert after["blockingReason"] in {
            "missing_burned_captions",
            "quarantined_asset",
        }
    finally:
        cf.close()


def test_import_prepare_and_review_emit_activity_and_jobs(tmp_path: Path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "a.mp4").write_bytes(b"video")
    (folder / "ignore.txt").write_text("ignore")
    cf = make_factory(tmp_path)
    try:
        first = cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        second = cf.domains.asset_import.import_folder(
            folder, campaign_slug="may", model_slug="model"
        )
        assert first["pipelineJobId"]
        assert second["pipelineJobId"]
        assert len(second["duplicates"]) == 1

        prepared = cf.domains.reel_execution.prepare_reel_inputs(
            campaign_slug="may", hooks=["hook"], recipes=["v01_original"]
        )
        assert prepared["pipelineJobId"]

        source = cf.domains.asset_import.assets_for_campaign(
            cf.domains.campaign_by_slug("may")["id"]
        )[0]
        rendered_path = tmp_path / "review.mp4"
        rendered_path.write_bytes(b"rendered")
        cf.conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path, campaign_path, filename, caption, recipe, audit_status, review_state, created_at, updated_at)
            VALUES ('asset_1', ?, ?, 'hash_1', ?, ?, 'review.mp4', 'caption', 'v01_original', 'pending', 'draft', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (
                source["campaign_id"],
                source["id"],
                str(rendered_path),
                str(rendered_path),
            ),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset(
            "asset_1", decision="rejected", notes="bad"
        )

        event_types = [
            event["eventType"]
            for event in cf.domains.events.events_for_campaign("may", limit=50)
        ]
        assert "source_imported" in event_types
        assert "source_duplicate_ignored" in event_types
        assert "reel_inputs_prepared" in event_types
        assert "asset_rejected" in event_types
        job_types = [
            job["jobType"] for job in cf.domains.events.jobs_for_campaign("may")
        ]
        assert "import_folder" in job_types
        assert "prepare_reel" in job_types
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_failed_caption_quality(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]
        item = _draft_item(
            "post_caption_quality", "ig_1", scheduled_for="2026-06-06T16:00:00+00:00"
        )
        item["instagramPostCaptionQuality"] = {
            "passed": False,
            "reasons": ["instagram_post_caption_too_long"],
        }

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [item],
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "items": [item],
            },
        )

        assert result["executionReady"] is False
        assert result["preCommitChecklist"]["captionContractReadiness"] == "fail"
        assert "instagram_post_caption_quality_failed" in result["blockers"]
        details = {item["code"]: item for item in result["blockerDetails"]}
        assert details["instagram_post_caption_quality_failed"]["category"] == "caption"
        assert (
            details["instagram_post_caption_quality_failed"]["nextAction"]
            == "repair_caption_contract"
        )
    finally:
        cf.close()


def test_creator_os_execution_readiness_blocks_publishability_failure_reasons(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]
        item = _draft_item(
            "post_visual_qc", "ig_1", scheduled_for="2026-06-06T16:00:00+00:00"
        )
        item["publishability_failure_reasons"] = ["visual_qc_failed"]

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [item],
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "items": [item],
            },
        )

        assert result["executionReady"] is False
        assert result["preCommitChecklist"]["qualityReadiness"] == "fail"
        assert "visual_qc_failed" in result["blockers"]
        details = {item["code"]: item for item in result["blockerDetails"]}
        assert details["visual_qc_failed"]["category"] == "creative_safety"
        assert details["visual_qc_failed"]["nextAction"] == "repair_or_replace_creative"
    finally:
        cf.close()


@pytest.mark.parametrize(
    ("failure_reason", "expected_blocker", "checklist_key", "category"),
    [
        ("missing_audio", "native_audio_proof_missing", "audioReadiness", "audio"),
        (
            "missing_caption_hash",
            "missing_caption_hash",
            "captionContractReadiness",
            "caption",
        ),
        (
            "missing_caption_outcome_context",
            "missing_caption_outcome_context",
            "captionContractReadiness",
            "caption",
        ),
        (
            "missing_content_fingerprint",
            "missing_content_fingerprint",
            "draftReadiness",
            "draft_contract",
        ),
        ("not_approved", "not_approved", "draftReadiness", "draft_contract"),
        ("readiness_failed", "readiness_failed", "qualityReadiness", "creative_safety"),
        ("wrong_visual", "wrong_visual", "qualityReadiness", "creative_safety"),
    ],
)
def test_creator_os_execution_readiness_covers_all_publishability_failure_reason_categories(
    tmp_path: Path,
    failure_reason: str,
    expected_blocker: str,
    checklist_key: str,
    category: str,
):
    cf = make_factory(tmp_path)
    try:
        accounts = [
            {
                "accountId": "ig_1",
                "username": "stacey_one",
                "creator": "Stacey",
                "bucket": "safe_to_schedule_today",
                "safeToSchedule": True,
                "needsPostToday": True,
            },
        ]
        item = _draft_item(
            "post_publishability_reason",
            "ig_1",
            scheduled_for="2026-06-06T16:00:00+00:00",
        )
        item["publishability_failure_reasons"] = [failure_reason]

        result = cf.domains.execution_readiness.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=1,
            threadsdash_report=_manager_report_fixture(accounts=accounts),
            schedule_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "validatedDraftsAvailable": 1,
                "items": [item],
            },
            time_plan={
                "creator": "Stacey",
                "requestedCount": 1,
                "status": "ready",
                "items": [item],
            },
        )

        assert result["executionReady"] is False
        assert result["preCommitChecklist"][checklist_key] == "fail"
        assert expected_blocker in result["blockers"]
        details = {item["code"]: item for item in result["blockerDetails"]}
        assert details[expected_blocker]["category"] == category
    finally:
        cf.close()


def test_inventory_factory_audit_and_yield_analysis_are_read_only(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes

        audit = cf.domains.inventory_planning.inventory_factory_audit(
            accounts=200, posts_per_account_per_day=3
        )
        yield_report = cf.domains.inventory_planning.inventory_yield_analysis()

        assert cf.conn.total_changes == before
        assert audit["schema"] == "creator_os.inventory_factory_audit.v1"
        assert audit["inventoryPipelineMapped"] is True
        assert audit["dailyCapacityEstimate"] == 0
        assert audit["validatedInventoryCapacity"] == 0
        assert audit["scheduleSafeInventoryCapacity"] == 0
        assert audit["limitingStage"] == "validated_inventory"
        assert audit["wouldWrite"] is False
        assert yield_report["schema"] == "creator_os.inventory_yield_analysis.v1"
        assert yield_report["stageCounts"]["parentAssets"] == 0
        assert yield_report["parentToVariantYield"] == 0
        assert yield_report["variantToValidatedYield"] == 0
        assert yield_report["validatedToScheduleSafeYield"] == 0
        assert yield_report["largestDropoff"]
        assert yield_report["wouldWrite"] is False
    finally:
        cf.close()


def test_capture_publishability_rejection_evidence_stores_exact_discoverability_terms(
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
                caption_outcome_context_json = ?,
                caption_generation_json = ?
            WHERE id = 'asset_1'
            """,
            (
                "DM me",
                json.dumps(
                    {
                        "caption_text": "DM me",
                        "burned_caption_text": "DM me",
                        "instagram_post_caption": "link in bio",
                        "captionPlacementDecision": {"status": "passed"},
                    }
                ),
                json.dumps(
                    {
                        "instagram_post_caption": "link in bio",
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

        result = cf.domains.publishability.capture_publishability_rejection_evidence(
            "asset_1"
        )
        second = cf.domains.publishability.capture_publishability_rejection_evidence(
            "asset_1"
        )
        rows = [
            dict(row)
            for row in cf.conn.execute(
                "SELECT * FROM asset_rejection_evidence WHERE rendered_asset_id = ? ORDER BY failure_category, source_field",
                ("asset_1",),
            ).fetchall()
        ]

        assert result["schema"] == "campaign_factory.rejection_evidence_capture.v1"
        assert result["capturedCount"] >= 2
        assert second["capturedCount"] == result["capturedCount"]
        assert {row["failed_stage"] for row in rows} == {"discoverability_safety_pass"}
        assert {"dm_language", "bio_reference"} <= {
            row["failure_category"] for row in rows
        }
        assert "burned_caption_text" in {row["source_field"] for row in rows}
        assert "instagram_post_caption" in {row["source_field"] for row in rows}
        assert all(row["policy_version"] == "discoverability_safe_v1" for row in rows)
        assert all(row["repairable"] == 1 for row in rows)
    finally:
        cf.close()


def test_discoverability_upstream_gates_block_unsafe_text_without_writing(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    try:
        before = cf.conn.total_changes
        payload = {
            "source_caption": "normal mirror caption",
            "generated_caption": "DM me",
            "burned_caption_text": "link in bio",
            "instagram_post_caption": "casual post caption",
        }

        intake = cf.domains.discoverability.discoverability_intake_gate(payload)
        generation = cf.domains.discoverability.discoverability_generation_gate(payload)
        pre_render = cf.domains.discoverability.discoverability_pre_render_gate(payload)

        assert cf.conn.total_changes == before
        assert intake["schema"] == "campaign_factory.discoverability_intake_gate.v1"
        assert (
            generation["schema"]
            == "campaign_factory.discoverability_generation_gate.v1"
        )
        assert (
            pre_render["schema"]
            == "campaign_factory.discoverability_pre_render_gate.v1"
        )
        assert intake["canProceed"] is True
        assert generation["canProceed"] is False
        assert pre_render["canProceed"] is False
        assert {item["sourceField"] for item in pre_render["violations"]} >= {
            "generated_caption",
            "burned_caption_text",
        }
        assert {item["failureCategory"] for item in pre_render["violations"]} >= {
            "dm_language",
            "bio_reference",
        }
        assert all(
            item["wouldWrite"] is False for item in [intake, generation, pre_render]
        )
    finally:
        cf.close()


def test_campaign_factory_has_no_legacy_supabase_or_preview_write_surface(
    tmp_path: Path, monkeypatch
) -> None:
    cf = make_factory(tmp_path)
    monkeypatch.setenv("CAMPAIGN_FACTORY_ENABLE_LEGACY_SUPABASE_WRITES", "1")
    try:
        add_rendered_asset(cf, tmp_path)
        add_audit_report(cf)
        cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
        ensure_exportable_distribution_plan(cf)

        for mode in ("preview", "live"):
            with pytest.raises(ValueError, match="exports are draft-only"):
                export_threadsdash(
                    cf,
                    campaign_slug="may",
                    user_id="user_1",
                    dry_run=False,
                    schedule_mode=mode,
                    supabase_url="https://example.supabase.co",
                    supabase_service_role_key="service-role",
                )

        assert not hasattr(threadsdash_delivery_adapter, "_write_supabase")
        assert not hasattr(threadsdash_delivery_adapter, "promote_preview_schedule")
        assert not hasattr(threadsdash_delivery_adapter, "clear_preview_schedule")
    finally:
        cf.close()
