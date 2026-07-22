from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from campaign_asset_test_support import add_audit_report
from campaign_factory.cli_dispatch_operations import dispatch_operations_commands
from campaign_factory.cli_parser import build_cli_parser
from campaign_factory.generation_execution_plan import build_generation_execution_plan
from campaign_factory.motion_generation_stage import (
    _motion_request_fingerprint,
    _register_review_asset,
    _worker_command,
    run_motion_generation_stage,
)
from campaign_test_support import add_source_asset, make_factory

PROMPT = "Natural breathing, a gentle head turn, and a slow cinematic camera push"


def test_motion_request_fingerprint_changes_for_every_material_input(
    tmp_path: Path,
) -> None:
    still = tmp_path / "still.jpg"
    audio = tmp_path / "voice.wav"
    still.write_bytes(b"still")
    audio.write_bytes(b"audio")
    base = dict(
        model_id="local_ltx23_distilled_mlx",
        prompt=PROMPT,
        still=still,
        duration_seconds=6,
        resolution="576x1024",
        seed=42,
        steps=8,
        audio_path=audio,
        generate_audio=False,
        last_image_path=None,
        reference_image_paths=(),
        reference_video_paths=(),
        enable_prompt_expansion=False,
        shot_type="single",
        local_model_dir=None,
        motion_task="audio_image_to_video",
        motion_lora_path=None,
        motion_lora_strength=1.0,
    )
    first = _motion_request_fingerprint(**base)
    assert first == _motion_request_fingerprint(**base)
    for key, value in {
        "prompt": PROMPT + " outdoors",
        "duration_seconds": 10,
        "seed": 43,
        "motion_task": "image_to_video",
        "generate_audio": True,
    }.items():
        changed = {**base, key: value}
        assert _motion_request_fingerprint(**changed) != first


def _register_motion_fixture(
    cf,
    tmp_path: Path,
    *,
    model_id: str = "local_wan22_i2v_a14b_q4_mlx",
    audio_mode: str = "none",
    motion_task: str = "image_to_video",
) -> dict:
    source = add_source_asset(cf, tmp_path)
    still = tmp_path / f"{model_id}-accepted.jpg"
    still.write_bytes(b"accepted-still")
    output = tmp_path / f"{model_id}-motion.mp4"
    output.write_bytes(f"generated-{model_id}-{audio_mode}".encode())
    return _register_review_asset(
        cf,
        campaign=cf.domains.campaign_by_slug("may"),
        source_asset_id=source["id"],
        model_slug="stacey",
        model_id=model_id,
        source_path=still,
        source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
        output_path=output,
        worker_result={
            "result": {
                "audio": {
                    "mode": audio_mode,
                    "nativePlatformAudio": False,
                }
            }
        },
        paid=False,
        motion_task=motion_task,
    )


def _motion_qc_receipt(
    subject_sha256: str,
    *,
    audio_alignment: bool = False,
    lip_sync: bool = False,
) -> dict:
    requirements = {
        "motion": True,
        "temporal": True,
        "freeze": True,
        "anatomy": True,
        "identity": True,
        "loop": False,
        "audioAlignment": audio_alignment,
        "lipSync": lip_sync,
    }
    sources = {
        name: {
            "available": True,
            "analyzer": f"fixture_{name}",
            "analyzerVersion": "1.0.0",
            "subjectSha256": subject_sha256,
        }
        for name, required in requirements.items()
        if required
    }
    return {
        "policy": {
            "id": "contentforge.motion_specific_qc",
            "version": "1.0.0",
        },
        "subjectSha256": subject_sha256,
        "verdict": "pass",
        "passed": True,
        "evidenceOnly": True,
        "modelCalls": 0,
        "providerCalls": 0,
        "requirements": requirements,
        "evidenceSources": sources,
        "reasons": [],
    }


def _write_motion_qc_receipt(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / f"{name}.motion-qc.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def test_text_to_video_worker_omits_image_but_keeps_static_fallback_input(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"still")
        command = _worker_command(
            cf,
            model_id="local_wan22_ti2v_5b_mlx",
            prompt=PROMPT,
            still=still,
            output_path=tmp_path / "out.mp4",
            campaign_slug="may",
            duration_seconds=6,
            resolution="704x1280",
            seed=42,
            steps=40,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="text_to_video",
            motion_lora_path=None,
            motion_lora_strength=1.0,
            dry_run=True,
        )
        assert command[command.index("--task") + 1] == "text_to_video"
        assert "--image" not in command
        assert still.is_file()
    finally:
        cf.close()


def test_local_lora_worker_arguments_are_explicit(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"still")
        lora = tmp_path / "motion.safetensors"
        command = _worker_command(
            cf,
            model_id="local_wan22_i2v_a14b_q4_mlx",
            prompt=PROMPT,
            still=still,
            output_path=tmp_path / "out.mp4",
            campaign_slug="may",
            duration_seconds=6,
            resolution="704x1280",
            seed=42,
            steps=20,
            audio_path=None,
            generate_audio=False,
            last_image_path=None,
            reference_image_paths=(),
            reference_video_paths=(),
            enable_prompt_expansion=False,
            shot_type="single",
            local_model_dir=None,
            motion_task="image_to_video",
            motion_lora_path=lora,
            motion_lora_strength=0.7,
            dry_run=True,
        )
        assert command[command.index("--lora") + 1] == str(lora)
        assert command[command.index("--lora-strength") + 1] == "0.7"
    finally:
        cf.close()


def test_local_wan_apply_preserves_static_fallback_then_registers_review_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        calls: list[str] = []

        def fake_static(*_args, **kwargs):
            calls.append("static")
            assert kwargs["apply"] is True
            return {"registeredAsset": {"source_asset_id": source["id"]}}

        def fake_worker(command, *, factory):
            del factory
            if "--dry-run" in command:
                calls.append("preflight")
                return {
                    "schema": "reel_factory.motion_generation_result.v1",
                    "providerCalls": 0,
                    "result": {"status": "planned"},
                }
            calls.append("local_apply")
            output = Path(command[command.index("--out") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"generated-motion-video")
            return {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "result": {
                    "status": "completed",
                    "outputSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                },
            }

        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage", fake_static
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker", fake_worker
        )
        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("local_wan"),
            campaign_slug="may",
            still_path=still,
            prompt=PROMPT,
            model_id="local_wan22_ti2v_5b_mlx",
            duration_seconds=6,
            resolution=None,
            seed=42,
            steps=40,
            dry_run=False,
            apply=True,
            motion_task="text_to_video",
        )
        assert calls == ["preflight", "static", "local_apply"]
        asset = result["registeredAsset"]
        assert asset["audit_status"] == "pending"
        assert asset["review_state"] == "review_ready"
        assert asset["caption"] == ""
        assert result["providerCalls"] == 0
        metadata = json.loads(asset["metadata_json"])
        assert metadata["source"] is None
        assert metadata["generationInput"] is None
        assert metadata["sourceAssetRole"] == "static_fallback_only"
        assert metadata["identityRole"] == "non_creator_broll"
        assert (
            "text_to_video_identity_assignment_forbidden"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            metadata["staticFallbackSource"]["sha256"]
            == hashlib.sha256(still.read_bytes()).hexdigest()
        )
    finally:
        cf.close()


def test_wavespeed_dry_run_has_zero_provider_calls_and_no_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        scope = {"requestFingerprint": "a" * 64}
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: {
                "schema": "reel_factory.motion_generation_result.v1",
                "providerCalls": 0,
                "spendScope": scope,
            },
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.run_static_mp4_stage",
            lambda *_args, **_kwargs: {"dryRun": True},
        )
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage.issue_wavespeed_spend_authorization",
            lambda *_args, **_kwargs: pytest.fail("dry-run must not authorize spend"),
        )
        result = run_motion_generation_stage(
            cf,
            execution_plan=build_generation_execution_plan("best_motion"),
            campaign_slug="may",
            still_path=still,
            prompt=PROMPT,
            model_id="wavespeed_wan27_i2v_pro",
            duration_seconds=5,
            resolution="1080p",
            seed=42,
            steps=40,
            dry_run=True,
            apply=False,
        )
        assert result["paidGeneration"] is True
        assert result["providerCalls"] == 0
        assert result["registeredAsset"] is None
    finally:
        cf.close()


def test_best_motion_rejects_local_or_unknown_model_before_any_worker_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cf = make_factory(tmp_path)
    try:
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        monkeypatch.setattr(
            "campaign_factory.motion_generation_stage._invoke_worker",
            lambda *_args, **_kwargs: pytest.fail("worker must not run"),
        )
        with pytest.raises(PermissionError, match="does not authorize model"):
            run_motion_generation_stage(
                cf,
                execution_plan=build_generation_execution_plan("best_motion"),
                campaign_slug="may",
                still_path=still,
                prompt=PROMPT,
                model_id="local_wan22_ti2v_5b_mlx",
                duration_seconds=6,
                resolution="720p",
                seed=42,
                steps=40,
                dry_run=True,
                apply=False,
            )
    finally:
        cf.close()


def test_ltx_embedded_audio_is_not_misclassified_as_native_platform_audio(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        output = tmp_path / "ltx.mp4"
        output.write_bytes(b"ltx-video-with-audio")
        campaign = cf.domains.campaign_by_slug("may")
        asset = _register_review_asset(
            cf,
            campaign=campaign,
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_ltx23_distilled_mlx",
            source_path=still,
            source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
            output_path=output,
            worker_result={
                "result": {
                    "audio": {
                        "mode": "generated",
                        "nativePlatformAudio": False,
                        "sidecarSha256": "a" * 64,
                    },
                    "aiDisclosureRequired": True,
                }
            },
            paid=False,
        )
        metadata = json.loads(asset["metadata_json"])
        assert metadata["audioBurned"] is True
        assert metadata["embeddedAudioMode"] == "generated"
        assert metadata["nativeAudioResolved"] is False
        assert (
            "local_audio_policy_review_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "ai_generated_media_disclosure_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "motion_specific_qc_required"
            in metadata["publishability"]["blockingIssues"]
        )
        assert (
            "audio_video_alignment_qc_required"
            in metadata["publishability"]["blockingIssues"]
        )
    finally:
        cf.close()


def test_longcat_talking_asset_requires_lip_sync_qc(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        source = add_source_asset(cf, tmp_path)
        still = tmp_path / "accepted.jpg"
        still.write_bytes(b"accepted-still")
        output = tmp_path / "talking.mp4"
        output.write_bytes(b"talking-video")
        asset = _register_review_asset(
            cf,
            campaign=cf.domains.campaign_by_slug("may"),
            source_asset_id=source["id"],
            model_slug="stacey",
            model_id="local_longcat_avatar15_q4_mlx",
            source_path=still,
            source_hash=hashlib.sha256(still.read_bytes()).hexdigest(),
            output_path=output,
            worker_result={
                "result": {
                    "audio": {"mode": "source", "nativePlatformAudio": False},
                    "aiDisclosureRequired": True,
                }
            },
            paid=False,
        )
        blockers = json.loads(asset["metadata_json"])["publishability"][
            "blockingIssues"
        ]
        assert "motion_specific_qc_required" in blockers
        assert "audio_video_alignment_qc_required" in blockers
        assert "lip_sync_qc_required" in blockers
    finally:
        cf.close()


def test_generated_motion_stays_blocked_after_generic_audit_and_human_approval(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = ?",
            (asset["id"],),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id=asset["id"])

        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert "motion_specific_qc_required" in explanation["failureReasons"]
        assert explanation["checks"]["motion_specific_qc_passed"] is False
        assert explanation["motionSpecificQcReceipt"] is None
        motion_finding = next(
            item
            for item in explanation["findings"]
            if item["code"] == "motion_specific_qc_required"
        )
        assert motion_finding["operatorAction"] == "run_motion_qc_analyzers"
    finally:
        cf.close()


def test_motion_qc_receipt_rejects_mismatched_media_subject(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "mismatch",
            _motion_qc_receipt("a" * 64),
        )

        with pytest.raises(ValueError, match="motion_specific_qc_subject_mismatch"):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )

        count = cf.conn.execute(
            "SELECT COUNT(*) FROM motion_qc_receipts WHERE rendered_asset_id = ?",
            (asset["id"],),
        ).fetchone()[0]
        assert count == 0
    finally:
        cf.close()


def test_embedded_audio_motion_requires_audio_alignment_in_receipt(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path, audio_mode="generated")
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "missing-audio-alignment",
            _motion_qc_receipt(asset["content_hash"]),
        )

        with pytest.raises(
            ValueError,
            match="motion_specific_qc_requirement_missing:audioAlignment",
        ):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )

        explanation = cf.domains.publishability.explain_publishability(asset["id"])
        assert "audio_video_alignment_qc_required" in explanation["failureReasons"]
    finally:
        cf.close()


def test_longcat_motion_requires_lip_sync_in_receipt(tmp_path: Path) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(
            cf,
            tmp_path,
            model_id="local_longcat_avatar15_q4_mlx",
            audio_mode="source",
        )
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "missing-lip-sync",
            _motion_qc_receipt(asset["content_hash"], audio_alignment=True),
        )

        with pytest.raises(
            ValueError,
            match="motion_specific_qc_requirement_missing:lipSync",
        ):
            cf.domains.publishability.register_motion_qc_receipt(
                asset["id"], receipt_path=receipt_path
            )

        explanation = cf.domains.publishability.explain_publishability(asset["id"])
        assert "lip_sync_qc_required" in explanation["failureReasons"]
    finally:
        cf.close()


def test_exact_longcat_motion_qc_receipt_clears_only_bound_motion_gates(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(
            cf,
            tmp_path,
            model_id="local_longcat_avatar15_q4_mlx",
            audio_mode="source",
        )
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "passing-longcat",
            _motion_qc_receipt(
                asset["content_hash"], audio_alignment=True, lip_sync=True
            ),
        )

        registered = cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path, created_by="test"
        )
        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert registered["subjectSha256"] == asset["content_hash"]
        assert registered["policy"] == {
            "id": "contentforge.motion_specific_qc",
            "version": "1.0.0",
        }
        assert "motion_specific_qc_required" not in explanation["failureReasons"]
        assert "audio_video_alignment_qc_required" not in explanation["failureReasons"]
        assert "lip_sync_qc_required" not in explanation["failureReasons"]
        assert explanation["checks"]["motion_specific_qc_passed"] is True
        assert explanation["checks"]["audio_video_alignment_qc_passed"] is True
        assert explanation["checks"]["lip_sync_qc_passed"] is True
        assert explanation["motionSpecificQcReceipt"]["id"] == registered["id"]
        with pytest.raises(
            sqlite3.IntegrityError, match="motion QC receipts are immutable"
        ):
            cf.conn.execute(
                "UPDATE motion_qc_receipts SET created_by = 'tampered' WHERE id = ?",
                (registered["id"],),
            )
    finally:
        cf.close()


def test_registered_motion_qc_receipt_fails_closed_after_media_substitution(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "passing-before-substitution",
            _motion_qc_receipt(asset["content_hash"]),
        )
        cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path
        )
        Path(asset["campaign_path"]).write_bytes(b"substituted-video")

        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert "motion_specific_qc_media_hash_mismatch" in explanation["failureReasons"]
        assert explanation["checks"]["motion_specific_qc_passed"] is False
    finally:
        cf.close()


def test_text_to_video_broll_cannot_be_creator_assigned_by_audit_approval_or_qc(
    tmp_path: Path,
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(
            cf,
            tmp_path,
            motion_task="text_to_video",
        )
        cf.conn.execute(
            "UPDATE rendered_assets SET review_state = 'approved' WHERE id = ?",
            (asset["id"],),
        )
        cf.conn.commit()
        add_audit_report(cf, rendered_asset_id=asset["id"])
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "passing-text-to-video-broll",
            _motion_qc_receipt(asset["content_hash"]),
        )
        cf.domains.publishability.register_motion_qc_receipt(
            asset["id"], receipt_path=receipt_path
        )

        explanation = cf.domains.publishability.explain_publishability(asset["id"])

        assert (
            "text_to_video_identity_assignment_forbidden"
            in explanation["failureReasons"]
        )
        assert explanation["checks"]["motion_specific_qc_passed"] is True
        assert explanation["checks"]["creator_identity_assignment_allowed"] is False
        assert explanation["publishableCandidate"] is False
        identity_finding = next(
            item
            for item in explanation["findings"]
            if item["code"] == "text_to_video_identity_assignment_forbidden"
        )
        assert identity_finding["retryable"] is False
    finally:
        cf.close()


def test_campaign_cli_registers_exact_motion_qc_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cf = make_factory(tmp_path)
    try:
        asset = _register_motion_fixture(cf, tmp_path)
        receipt_path = _write_motion_qc_receipt(
            tmp_path,
            "campaign-cli-passing",
            _motion_qc_receipt(asset["content_hash"]),
        )
        args = build_cli_parser().parse_args(
            [
                "register-motion-qc-receipt",
                "--rendered-asset-id",
                asset["id"],
                "--receipt",
                str(receipt_path),
                "--operator",
                "operator_1",
            ]
        )

        result = dispatch_operations_commands(args, cf, cf.settings)
        payload = json.loads(capsys.readouterr().out)

        assert result == 0
        assert payload["renderedAssetId"] == asset["id"]
        assert payload["subjectSha256"] == asset["content_hash"]
        assert payload["createdBy"] == "operator_1"
    finally:
        cf.close()
