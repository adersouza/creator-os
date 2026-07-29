from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from campaign_factory.creation_modes import run_creation_batch
from campaign_factory.derived_still_reporting import derived_still_report
from campaign_factory.derived_stills import (
    edit_still,
    enroll_still,
    harvest_stills,
    validate_static_source_assets,
)
from campaign_factory.source_governance import apply_decision, plan_decision
from campaign_factory.static_mp4_stage import run_static_mp4_stage
from campaign_generation_test_support import (
    fake_static_mp4_render,
    write_fake_static_mp4_outputs,
)
from campaign_test_support import make_factory
from PIL import Image
from reel_factory import derived_stills as reel_derived_stills
from reel_factory.derived_stills import (
    assess_edit_locality,
    evaluate_harvest_frame,
    harvest_animation_frames,
    split_grid_2x3,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _approved_source(cf, tmp_path: Path) -> dict[str, Any]:
    folder = tmp_path / "images"
    folder.mkdir()
    image = folder / "creator.png"
    Image.new("RGB", (720, 1280), (90, 60, 40)).save(image)
    cf.domains.asset_import.import_folder(
        folder,
        campaign_slug="may",
        model_slug="stacey",
        storage_mode="reference",
    )
    source = cf.domains.asset_import.assets_for_campaign(
        cf.domains.campaign_by_slug("may")["id"]
    )[0]
    approval = plan_decision(
        cf.conn,
        creator="stacey",
        source=source["id"],
        decision="approved",
        operator="test",
        reason="fixture approval",
    )
    apply_decision(cf.conn, approval)
    return dict(
        cf.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?", (source["id"],)
        ).fetchone()
    )


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    handle = io.BytesIO()
    Image.new("RGB", (720, 1280), color).save(handle, format="PNG")
    return handle.getvalue()


class FakeEditProvider:
    provider = "openai"
    model = "gpt-image-2"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def preflight(self):
        return {"provider": self.provider, "model": self.model, "authenticated": True}

    def quote(self, *, count: int, output_format: str):
        return {
            "provider": self.provider,
            "model": self.model,
            "amount": 1.25,
            "unit": "USD",
            "count": count,
            "format": output_format,
        }

    def generate(self, *, source, prompt, count, output_format):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider failed")
        return {
            "provider": self.provider,
            "model": self.model,
            "requestId": "request_1",
            "images": [
                _image_bytes((20 * index, 30 + index, 100 + index))
                for index in range(1, count + 1)
            ],
            "usage": {"images": count},
        }


def _identity(_path: Path) -> dict[str, Any]:
    return {"status": "passed", "score": 0.95}


def _image_qc(_path: Path) -> dict[str, Any]:
    return {
        "available": True,
        "anatomy": {"plausible": True, "severity": "none"},
        "exposure": {"safe": True, "severity": "none"},
    }


def _locality(source, output, **kwargs):
    return {
        "schema": "reel_factory.edit_locality_receipt.v1",
        "operation": kwargs["operation"],
        "source": {"path": str(source), "sha256": _sha(source)},
        "output": {"path": str(output), "sha256": _sha(output)},
        "status": "passed",
        "checks": {"fixture": True},
        "narrowComparisonReviewRequired": True,
    }


def test_enrollment_exact_approval_and_static_source_selection(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source = _approved_source(cf, tmp_path)
        result = enroll_still(
            cf,
            campaign_slug="may",
            source_asset_id=source["id"],
            tier="canonical_identity_source",
            apply=True,
        )
        receipt = result["receipt"]
        assert receipt["sourceTier"] == "canonical_identity_source"
        assert receipt["approval"]["exactOutputSha256"] == source["content_hash"]
        validated = validate_static_source_assets(cf, (source["id"],))
        assert validated[0]["sha256"] == source["content_hash"]

        batch = run_creation_batch(
            cf,
            creator="stacey",
            mode="static_reel",
            style="passive_selfie",
            count=1,
            execution="cloud",
            accounts=None,
            audio_preference="embedded_trending_required",
            apply=False,
            reuse_policy="prefer_exact",
            source_asset_ids=(source["id"],),
        )
        assert batch["jobs"][0]["sourceAssetId"] == source["id"]
    finally:
        cf.close()


def test_ai_produced_source_cannot_become_canonical_identity(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source = _approved_source(cf, tmp_path)
        prompt = {
            "generatedAssetLineage": {
                "review": {
                    "generatedImageQc": {
                        "status": "passed",
                        "results": [{"postable": True}],
                    }
                }
            }
        }
        cf.conn.execute(
            "UPDATE source_assets SET source_prompt = ? WHERE id = ?",
            (json.dumps(prompt), source["id"]),
        )
        cf.conn.commit()

        with pytest.raises(PermissionError, match="cannot be canonical"):
            enroll_still(
                cf,
                campaign_slug="may",
                source_asset_id=source["id"],
                tier="canonical_identity_source",
            )
        enrolled = enroll_still(
            cf,
            campaign_slug="may",
            source_asset_id=source["id"],
            tier="approved_generated_still",
        )
        assert enrolled["receipt"]["canonicalIdentityEligible"] is False
        assert enrolled["receipt"]["providerEditDepth"] == 0
    finally:
        cf.close()


def test_approved_tiered_still_propagates_into_static_mp4_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cf = make_factory(tmp_path)
    try:
        source = _approved_source(cf, tmp_path)
        enroll_still(
            cf,
            campaign_slug="may",
            source_asset_id=source["id"],
            tier="canonical_identity_source",
            apply=True,
        )

        def fake_render(_factory, **kwargs):
            write_fake_static_mp4_outputs(kwargs["output_path"])
            return fake_static_mp4_render(
                kwargs["still_path"], kwargs["output_path"], dry_run=False
            )

        monkeypatch.setattr(
            "campaign_factory.static_mp4_stage._invoke_reel_factory_static_mp4",
            fake_render,
        )
        result = run_static_mp4_stage(
            cf,
            campaign_slug="may",
            still_path=Path(source["stored_path"]),
            dry_run=False,
            apply=True,
        )
        metadata = json.loads(result["registeredAsset"]["metadata_json"])
        assert (
            metadata["derivedStillSource"]["sourceTier"] == "canonical_identity_source"
        )
        assert metadata["captionPlacementConstraints"]["avoidGarmentRegion"] is True
        assert (
            metadata["generatedAssetLineage"]["derivedStillSource"]["output"]["sha256"]
            == source["content_hash"]
        )
    finally:
        cf.close()


def test_edit_registers_review_candidates_cache_and_blocks_recursive_edit(
    tmp_path: Path,
):
    cf = make_factory(tmp_path)
    adapter = FakeEditProvider()
    try:
        source = _approved_source(cf, tmp_path)
        enroll_still(
            cf,
            campaign_slug="may",
            source_asset_id=source["id"],
            tier="canonical_identity_source",
            apply=True,
        )
        result = edit_still(
            cf,
            campaign_slug="may",
            image_asset_id=source["id"],
            operation="colorway",
            provider="openai",
            output_format="individual",
            count=6,
            max_usd=2.0,
            apply=True,
            adapter=adapter,
            image_qc_call=_image_qc,
            identity_call=_identity,
            locality_call=_locality,
        )
        assert adapter.calls == 1
        assert len(result["registeredAssets"]) == 6
        assert all(
            asset["review_state"] == "review_ready"
            for asset in result["registeredAssets"]
        )
        first = result["registeredAssets"][0]
        with pytest.raises(PermissionError, match="not an exact approved"):
            validate_static_source_assets(cf, (first["source_asset_id"],))
        cf.domains.finished_video.review_rendered_asset(
            first["id"], decision="approved", require_safe_audit=True
        )
        linked = cf.conn.execute(
            "SELECT * FROM source_assets WHERE id = ?", (first["source_asset_id"],)
        ).fetchone()
        linked_receipt = json.loads(linked["source_prompt"])["derivedStillSource"]
        assert linked["status"] == "approved"
        assert linked_receipt["approval"]["exactOutputSha256"] == first["content_hash"]
        assert linked_receipt["sourceTier"] == "approved_outfit_derivative"
        assert linked_receipt["providerEditDepth"] == 1
        assert (
            validate_static_source_assets(cf, (first["source_asset_id"],))[0]["sha256"]
            == first["content_hash"]
        )

        cached = edit_still(
            cf,
            campaign_slug="may",
            image_asset_id=source["id"],
            operation="colorway",
            provider="openai",
            output_format="individual",
            count=6,
            max_usd=2.0,
            apply=True,
            adapter=adapter,
            image_qc_call=_image_qc,
            identity_call=_identity,
            locality_call=_locality,
        )
        assert cached["cache"]["hit"] is True
        assert adapter.calls == 1
        with pytest.raises(PermissionError, match="does not allow"):
            edit_still(
                cf,
                campaign_slug="may",
                image_asset_id=first["id"],
                operation="colorway",
                provider="openai",
                output_format="individual",
                count=1,
                max_usd=2.0,
                adapter=adapter,
            )
        report = derived_still_report(cf, campaign_slug="may")
        assert report["candidateCount"] >= 6
        assert report["approvedCount"] >= 1
    finally:
        cf.close()


def test_provider_failure_cancels_spend_without_fallback(tmp_path: Path):
    cf = make_factory(tmp_path)
    adapter = FakeEditProvider(fail=True)
    try:
        source = _approved_source(cf, tmp_path)
        enroll_still(
            cf,
            campaign_slug="may",
            source_asset_id=source["id"],
            tier="canonical_identity_source",
            apply=True,
        )
        with pytest.raises(RuntimeError, match="provider failed"):
            edit_still(
                cf,
                campaign_slug="may",
                image_asset_id=source["id"],
                operation="colorway",
                provider="openai",
                output_format="individual",
                count=1,
                max_usd=2.0,
                apply=True,
                adapter=adapter,
                image_qc_call=_image_qc,
                identity_call=_identity,
                locality_call=_locality,
            )
        assert adapter.calls == 1
        status = cf.conn.execute(
            "SELECT status FROM provider_spend_authorizations"
        ).fetchone()[0]
        assert status == "cancelled"
        assert (
            cf.conn.execute("SELECT COUNT(*) FROM rendered_assets").fetchone()[0] == 0
        )
    finally:
        cf.close()


def test_grid_2x3_recovers_six_portrait_panels(tmp_path: Path):
    grid = Image.new("RGB", (3840, 3840))
    for row in range(2):
        for column in range(3):
            grid.paste(
                Image.new(
                    "RGB",
                    (1280, 1920),
                    (50 * column, 50 * row, 30 * (row + column)),
                ),
                (column * 1280, row * 1920),
            )
    handle = io.BytesIO()
    grid.save(handle, format="PNG")
    panels = split_grid_2x3(handle.getvalue(), tmp_path / "panels")
    assert len(panels) == 6
    assert Image.open(panels[0]).size == (1280, 1920)


def test_frame_harvest_is_deterministic_and_enforces_temporal_separation(
    tmp_path: Path,
):
    video = tmp_path / "motion.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=720x1280:rate=12:duration=3",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )

    def accepted(path: Path):
        return {
            "eligible": True,
            "score": int(path.stem.split("_")[1]),
            "rejections": [],
            "measurements": {},
        }

    first = harvest_animation_frames(
        video,
        tmp_path / "first",
        count=3,
        expected_sha256=_sha(video),
        evaluator=accepted,
    )
    second = harvest_animation_frames(
        video,
        tmp_path / "second",
        count=3,
        expected_sha256=_sha(video),
        evaluator=accepted,
    )
    assert [item["timeSec"] for item in first["selectedFrames"]] == [
        item["timeSec"] for item in second["selectedFrames"]
    ]
    times = sorted(item["timeSec"] for item in first["selectedFrames"])
    assert all(right - left >= 0.5 for left, right in zip(times, times[1:]))


def test_harvest_and_locality_fail_closed_when_required_evidence_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    image = tmp_path / "frame.png"
    Image.new("RGB", (720, 1280), (80, 70, 60)).save(image)
    monkeypatch.setattr(reel_derived_stills, "_ocr_text", lambda _path: None)
    monkeypatch.setattr(reel_derived_stills, "_face_count", lambda _path: None)
    monkeypatch.setattr(reel_derived_stills, "_pose_signature", lambda _path: None)
    harvest = evaluate_harvest_frame(image)
    assert harvest["eligible"] is False
    assert "ocr_evidence_unavailable" in harvest["rejections"]
    assert "face_evidence_unavailable" in harvest["rejections"]

    monkeypatch.setattr(
        reel_derived_stills,
        "_locality_measurements",
        lambda _source, _output: {
            "faceBoxIou": 0.91,
            "poseLandmarkDrift": 0.02,
            "personSilhouetteIou": 0.95,
            "backgroundSsim": None,
            "protectedFaceRegionSsim": 0.96,
            "garmentRegionChange": 0.06,
        },
    )
    locality = assess_edit_locality(
        image,
        image,
        operation="colorway",
        source_identity=_identity(image),
        output_identity=_identity(image),
        output_qc=_image_qc(image),
    )
    assert locality["checks"]["backgroundSsim"] is False
    assert locality["status"] == "failed"


def test_campaign_harvest_registers_individual_review_assets(tmp_path: Path):
    cf = make_factory(tmp_path)
    try:
        source = _approved_source(cf, tmp_path)
        campaign = cf.domains.campaign_by_slug("may")
        raw = tmp_path / "raw.mp4"
        raw.write_bytes(b"raw-motion")
        final = tmp_path / "final.mp4"
        final.write_bytes(b"final-motion")
        raw_sha, final_sha = _sha(raw), _sha(final)
        now = "2026-07-29T00:00:00+00:00"
        cf.conn.execute(
            """
            INSERT INTO rendered_assets (
              id, campaign_id, source_asset_id, content_hash, output_path,
              campaign_path, filename, media_type, content_surface, recipe,
              metadata_json, audit_status, review_state, created_at, updated_at
            ) VALUES ('motion_1', ?, ?, ?, ?, ?, 'final.mp4', 'video', 'reel',
                      'higgsfield_kling_3', ?, 'needs_review', 'draft', ?, ?)
            """,
            (
                campaign["id"],
                source["id"],
                final_sha,
                str(final),
                str(final),
                json.dumps(
                    {
                        "visualInput": {"path": str(raw), "sha256": raw_sha},
                        "generationId": "provider_output_1",
                    }
                ),
                now,
                now,
            ),
        )
        cf.conn.execute(
            """
            INSERT INTO generation_output_blobs
            (id, content_sha256, byte_size, media_type, created_at)
            VALUES ('blob_motion_1', ?, ?, 'video', ?)
            """,
            (final_sha, final.stat().st_size, now),
        )
        cf.conn.execute(
            """
            INSERT INTO generation_attempts (
              id, campaign_id, source_asset_id, rendered_asset_id, output_blob_id,
              model_id, motion_task, source_sha256, attempted_output_path,
              duplicate_disposition, created_at
            ) VALUES ('attempt_motion_1', ?, ?, 'motion_1', 'blob_motion_1',
                      'higgsfield/kling-3', 'image_to_video', ?, ?,
                      'canonical_output', ?)
            """,
            (campaign["id"], source["id"], source["content_hash"], str(final), now),
        )
        cf.conn.commit()
        cf.domains.finished_video.review_rendered_asset(
            "motion_1", decision="approved", require_safe_audit=True
        )
        final_only = {
            "visualInput": {"path": str(final), "sha256": final_sha},
            "generationId": "provider_output_1",
        }
        cf.conn.execute(
            "UPDATE rendered_assets SET metadata_json = ? WHERE id = 'motion_1'",
            (json.dumps(final_only),),
        )
        cf.conn.commit()
        with pytest.raises(ValueError, match="only captioned or untraceable"):
            harvest_stills(
                cf,
                campaign_slug="may",
                rendered_asset_id="motion_1",
                count=2,
            )
        cf.conn.execute(
            "UPDATE rendered_assets SET metadata_json = ? WHERE id = 'motion_1'",
            (
                json.dumps(
                    {
                        "visualInput": {"path": str(raw), "sha256": raw_sha},
                        "generationId": "provider_output_1",
                    }
                ),
            ),
        )
        cf.conn.commit()

        def fake_harvest(video, output_dir, **kwargs):
            assert video == raw
            frames = []
            for index in range(2):
                path = output_dir / f"frame_{index}.png"
                Image.new("RGB", (720, 1280), (20 + index, 30, 40)).save(path)
                frames.append(
                    {
                        "path": str(path),
                        "sha256": _sha(path),
                        "timeSec": 0.5 + index,
                        "eligible": True,
                        "score": 0.9,
                        "rejections": [],
                    }
                )
            return {
                "schema": "reel_factory.animation_frame_harvest.v1",
                "source": {"path": str(video), "sha256": _sha(video)},
                "sceneCutsSeconds": [],
                "candidateFrames": frames,
                "selectedFrames": frames,
                "requestedCount": kwargs["count"],
                "acceptedCount": 2,
                "contactSheet": None,
                "exhaustionReasons": [],
            }

        result = harvest_stills(
            cf,
            campaign_slug="may",
            rendered_asset_id="motion_1",
            count=2,
            apply=True,
            harvest_call=fake_harvest,
        )
        assert result["parentRawVisual"]["sha256"] == raw_sha
        assert result["parentRawVisual"]["sourceKind"] == "visualInput"
        assert len(result["registeredAssets"]) == 2
        assert all(
            item["review_state"] == "review_ready"
            for item in result["registeredAssets"]
        )
    finally:
        cf.close()
