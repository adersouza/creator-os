from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from creator_os_core.recreation_anchor_approval import (
    write_recreation_anchor_approval,
)
from reel_factory import higgsfield_production as subject


class FakeAdapter:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.commands: list[list[str]] = []

    def run_json(self, command: list[str]) -> dict[str, Any]:
        self.commands.append(command)
        if not self.responses:
            raise AssertionError(f"unexpected command: {command}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response


def _capabilities() -> dict[str, Any]:
    return {
        "schema": subject.CAPABILITY_SCHEMA,
        "authentication": {
            "authenticated": True,
            "plan": "ultimate",
            "credits": 100.0,
        },
        "souls": [
            {
                "id": f"soul_{creator}",
                "name": creator.title(),
                "status": "completed",
                "type": "soul_2",
            }
            for creator in ("stacey", "larissa", "lola")
        ],
        "models": [
            {
                "job_type": "kling3_0_turbo",
                "display_name": "Kling v3.0 Turbo",
            },
            {"job_type": "kling3_0", "display_name": "Kling v3.0"},
            {
                "job_type": "seedance_2_0_mini",
                "display_name": "Seedance 2.0 Mini",
            },
            {"job_type": "seedance_2_0", "display_name": "Seedance 2.0"},
            {
                "job_type": "kling3_0_motion_control",
                "display_name": "Kling 3.0 Motion Control",
            },
            {"job_type": "veo3_1", "display_name": "Google Veo 3.1"},
        ],
        "workflows": [{"job_type": "voice_change", "display_name": "voice_change"}],
        "contracts": {},
    }


def _request(tmp_path: Path, **overrides: Any) -> subject.HiggsfieldProductionRequest:
    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    values: dict[str, Any] = {
        "recipe_id": "higgsfield_passive_selfie",
        "creator": "stacey",
        "soul_id": "soul_stacey",
        "source_approval": "approved-source-1",
        "source_asset_id": "source-asset-1",
        "campaign_source_asset_id": "source-asset-1",
        "source_approval_id": "source-approval-1",
        "source_image_path": source,
        "output_path": tmp_path / "review" / "output.mp4",
        "review_root": tmp_path / "review",
        "prompt": (
            "Subtle eye movement and a small natural head turn with restrained "
            "handheld creator-camera motion."
        ),
        "model": "kling3_0",
        "duration_seconds": 5,
        "max_credits": 20.0,
        "prompt_card_fingerprint": "d" * 64,
        "prompt_builder_fingerprint": "e" * 64,
    }
    values.update(overrides)
    if (
        values["recipe_id"] == "higgsfield_recreate_reel"
        and values.get("driving_video_path")
        and not values.get("recreation_anchor_approval")
    ):
        driving = Path(values["driving_video_path"])
        driving_sha = hashlib.sha256(driving.read_bytes()).hexdigest()
        reference_id = "reference-1"
        approval = write_recreation_anchor_approval(
            output_dir=tmp_path / "anchor-approvals",
            creator=str(values["creator"]),
            soul_id=str(values["soul_id"]),
            anchor_generation_id="anchor-generation-1",
            anchor_file=Path(values["source_image_path"]),
            prompt_pack_id="prompt-pack-1",
            prompt_pack_fingerprint="a" * 64,
            anchor_prompt_fingerprint="b" * 64,
            creator_image_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            reference_video_sha256=driving_sha,
            selected_composition_frame_sha256="c" * 64,
            approved_by="operator@test",
            reference_id=reference_id,
            recreation_plan_fingerprint="8" * 64,
            selected_recreation_mode="structural",
            reference_classification="simple_pose_motion",
            reference_provider_rights={
                "schema": "reference_factory.provider_rights_eligibility.v1",
                "eligible": True,
                "referenceId": reference_id,
                "provider": "higgsfield",
                "operation": "recreation_generation",
                "sourceSha256": driving_sha,
                "rightsEventId": "rights-event-1",
                "rightsEvidenceFingerprint": "9" * 64,
                "rightsExpiresAt": "2026-08-04T00:00:00Z",
            },
        )
        values["source_approval"] = approval["approvalFingerprint"]
        values["source_image_path"] = Path(approval["anchorFilePath"])
        values["recreation_anchor_approval"] = approval
    return subject.HiggsfieldProductionRequest(**values)


def test_balance_delta_attribution_defaults_fail_closed(tmp_path: Path) -> None:
    assert _request(tmp_path).balance_delta_attribution_allowed is False


def test_discovers_exact_authenticated_cli_contracts() -> None:
    adapter = FakeAdapter(
        [
            {"credits": 1183, "subscription_plan_type": "ultimate"},
            {
                "items": [
                    {
                        "id": "soul_stacey",
                        "name": "Stacey",
                        "status": "completed",
                        "type": "soul_2",
                    }
                ]
            },
            {"credits": 91.25},
            {
                "items": [
                    {"job_type": value, "display_name": value}
                    for value in (
                        "kling3_0_turbo",
                        "kling3_0",
                        "seedance_2_0_mini",
                        "seedance_2_0",
                        "kling3_0_motion_control",
                        "veo3_1",
                    )
                ]
            },
            {"items": [{"job_type": "voice_change"}]},
            {"job_type": "kling3_0_turbo", "params": [{"name": "resolution"}]},
            {"job_type": "kling3_0", "params": [{"name": "sound"}]},
            {
                "job_type": "seedance_2_0_mini",
                "params": [{"name": "generate_audio"}],
            },
            {"job_type": "seedance_2_0", "params": [{"name": "generate_audio"}]},
            {
                "job_type": "kling3_0_motion_control",
                "params": [{"name": "video_references"}],
            },
            {"job_type": "veo3_1", "params": [{"name": "quality"}]},
        ]
    )

    result = subject.discover_higgsfield_production_capabilities(
        adapter=adapter  # type: ignore[arg-type]
    )

    assert result["authentication"]["authenticated"] is True
    assert result["authentication"]["credits"] == 1183.0
    assert result["candidates"]["higgsfield_passive_selfie"]["status"] == "supported"
    assert (
        result["candidates"]["higgsfield_motion_copy_animate"]["exposed_job_type"]
        == "kling3_0_motion_control"
    )
    assert (
        result["candidates"]["higgsfield_motion_copy_replace"]["status"] == "unresolved"
    )
    assert result["candidates"]["higgsfield_talking_speak"]["status"] == "unresolved"
    assert (
        result["candidates"]["higgsfield_talking_motion_copy"]["status"] == "unresolved"
    )
    assert (
        result["candidates"]["higgsfield_motion_copy_animate"]["status"]
        == "experimental"
    )
    assert result["candidates"]["higgsfield_talking_veo"]["status"] == "experimental"
    assert set(result["contracts"]) == {
        "kling3_0_turbo",
        "kling3_0",
        "seedance_2_0_mini",
        "seedance_2_0",
        "kling3_0_motion_control",
        "veo3_1",
    }


def test_passive_plan_uses_silent_kling_contract(tmp_path: Path) -> None:
    plan = subject.build_higgsfield_production_plan(
        _request(tmp_path),
        capabilities=_capabilities(),
        adapter=FakeAdapter([]),  # type: ignore[arg-type]
    )

    assert plan["recipe"]["status"] == "supported"
    assert plan["command"][:4] == [
        "higgsfield",
        "generate",
        "create",
        "kling3_0",
    ]
    assert plan["command"][plan["command"].index("--sound") + 1] == "off"
    assert plan["command"][plan["command"].index("--aspect_ratio") + 1] == "9:16"
    assert plan["quoteCommand"][:4] == [
        "higgsfield",
        "generate",
        "cost",
        "kling3_0",
    ]
    assert plan["schedulingAllowed"] is False
    assert plan["publishingAllowed"] is False


def test_passive_plan_uses_kling_turbo_at_720p(tmp_path: Path) -> None:
    plan = subject.build_higgsfield_production_plan(
        _request(tmp_path, model="kling3_0_turbo"),
        capabilities=_capabilities(),
        adapter=FakeAdapter([]),  # type: ignore[arg-type]
    )

    assert plan["command"][3] == "kling3_0_turbo"
    assert plan["command"][plan["command"].index("--resolution") + 1] == "720p"
    assert "--sound" not in plan["command"]
    assert plan["authorizationScope"]["parameters"]["providerSoundArgument"] is None
    assert (
        plan["authorizationScope"]["parameters"]["audioOutputPostcondition"] == "silent"
    )


def test_provider_request_fingerprint_excludes_local_output_destination(
    tmp_path: Path,
) -> None:
    first = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            work_item_id="work-1",
            attempt_id="attempt-1",
            output_path=tmp_path / "first.mp4",
        ),
        capabilities=_capabilities(),
    )
    second = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            work_item_id="work-1",
            attempt_id="attempt-1",
            output_path=tmp_path / "second.mp4",
        ),
        capabilities=_capabilities(),
    )

    assert first["providerRequestFingerprint"] == second["providerRequestFingerprint"]
    assert first["executionFingerprint"] != second["executionFingerprint"]


def test_provider_request_uses_content_identity_not_local_media_path(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first-source.png"
    second_source = tmp_path / "moved-source.png"
    first_source.write_bytes(b"same-approved-source")
    second_source.write_bytes(first_source.read_bytes())

    first = subject.build_higgsfield_production_plan(
        _request(tmp_path, source_image_path=first_source),
        capabilities=_capabilities(),
    )
    second = subject.build_higgsfield_production_plan(
        _request(tmp_path, source_image_path=second_source),
        capabilities=_capabilities(),
    )

    assert first["providerRequestFingerprint"] == second["providerRequestFingerprint"]
    assert first["normalizedCommand"] == second["normalizedCommand"]
    assert first["command"] != second["command"]


def test_provider_request_binds_source_asset_and_attempt_ids(tmp_path: Path) -> None:
    base = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            source_asset_id="source-1",
            campaign_source_asset_id="source-1",
            attempt_id="attempt-1",
        ),
        capabilities=_capabilities(),
    )
    changed_asset = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            source_asset_id="source-2",
            campaign_source_asset_id="source-2",
            attempt_id="attempt-1",
        ),
        capabilities=_capabilities(),
    )
    changed_attempt = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            source_asset_id="source-1",
            campaign_source_asset_id="source-1",
            attempt_id="attempt-2",
        ),
        capabilities=_capabilities(),
    )

    assert (
        base["providerRequestFingerprint"]
        != changed_asset["providerRequestFingerprint"]
    )
    assert (
        base["providerRequestFingerprint"]
        != changed_attempt["providerRequestFingerprint"]
    )


def test_prompt_and_seed_changes_require_a_new_provider_request(
    tmp_path: Path,
) -> None:
    base = subject.build_higgsfield_production_plan(
        _request(tmp_path, seed=1),
        capabilities=_capabilities(),
    )
    changed_prompt = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            seed=1,
            prompt="A different restrained natural head turn in stable framing.",
        ),
        capabilities=_capabilities(),
    )
    changed_seed = subject.build_higgsfield_production_plan(
        _request(tmp_path, seed=2),
        capabilities=_capabilities(),
    )
    changed_approval = subject.build_higgsfield_production_plan(
        _request(tmp_path, seed=1, source_approval="approved-source-2"),
        capabilities=_capabilities(),
    )

    assert (
        base["providerRequestFingerprint"]
        != changed_prompt["providerRequestFingerprint"]
    )
    assert (
        base["providerRequestFingerprint"] != changed_seed["providerRequestFingerprint"]
    )
    assert (
        base["providerRequestFingerprint"]
        != changed_approval["providerRequestFingerprint"]
    )


def test_execution_rejects_a_changed_authorized_provider_request(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        authorized_request_fingerprint="f" * 64,
    )
    plan = subject.build_higgsfield_production_plan(
        request,
        capabilities=_capabilities(),
    )
    adapter = FakeAdapter([])

    with pytest.raises(
        PermissionError,
        match="authorized_provider_request_mismatch",
    ):
        subject.execute_higgsfield_production(
            request,
            adapter=adapter,  # type: ignore[arg-type]
            confirm_paid=True,
            prepared_plan=plan,
        )

    assert adapter.commands == []


def test_execution_rejects_quote_fingerprint_drift(tmp_path: Path) -> None:
    base_request = _request(tmp_path)
    plan = subject.build_higgsfield_production_plan(
        base_request,
        capabilities=_capabilities(),
    )
    authorized_quote = {
        "provider": "higgsfield",
        "amount": 8.0,
        "unit": "higgsfield_credits",
    }
    request = _request(
        tmp_path,
        authorized_request_fingerprint=plan["providerRequestFingerprint"],
        authorized_quote_fingerprint=subject.higgsfield_quote_fingerprint(
            authorized_quote
        ),
    )
    adapter = FakeAdapter([])

    with pytest.raises(PermissionError, match="quote_changed_after_authorization"):
        subject.execute_higgsfield_production(
            request,
            adapter=adapter,  # type: ignore[arg-type]
            confirm_paid=True,
            prepared_plan=plan,
            prepared_quote={**authorized_quote, "amount": 8.5},
        )

    assert adapter.commands == []


def test_motion_control_qualification_plan_uses_exact_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driving = tmp_path / "driving.mp4"
    driving.write_bytes(b"driving-video")
    monkeypatch.setattr(
        subject,
        "_probe_video",
        lambda _path: {"durationSeconds": 7.0},
    )
    plan = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            recipe_id="higgsfield_motion_copy_animate",
            model=None,
            driving_video_path=driving,
        ),
        capabilities=_capabilities(),
        adapter=FakeAdapter([]),  # type: ignore[arg-type]
    )
    assert plan["recipe"]["status"] == "experimental"
    assert plan["command"][3] == "kling3_0_motion_control"
    assert "--image-references" in plan["command"]
    assert "--video-references" in plan["command"]


@pytest.mark.parametrize("creator", ["stacey", "larissa", "lola"])
def test_recreate_qualification_uses_seedance_fast_with_creator_reference(
    tmp_path: Path, creator: str
) -> None:
    driving = tmp_path / "driving.mp4"
    driving.write_bytes(b"driving-video")
    reference_elements = tmp_path / f"{creator}.json"
    reference_elements.write_text(
        json.dumps(
            [
                {
                    "id": f"{creator}-reference",
                    "name": creator,
                    "medias": [],
                    "video_medias": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    plan = subject.build_higgsfield_production_plan(
        _request(
            tmp_path,
            creator=creator,
            soul_id=f"soul_{creator}",
            recipe_id="higgsfield_recreate_reel",
            model="seedance_2_0",
            driving_video_path=driving,
            duration_seconds=7,
            reference_elements_path=reference_elements,
            prompt=(
                "<<<approved_creator_reference_element>>> place her in this "
                "video. same motion but my model instead. Structural breakdown: "
                "[0-3s] Begin a shoulder turn. Camera: fixed."
            ),
        ),
        capabilities=_capabilities(),
        adapter=FakeAdapter([]),  # type: ignore[arg-type]
    )
    command = plan["command"]
    assert command[3] == "seedance_2_0"
    assert command[command.index("--prompt") + 1] == (
        f"<<<{creator}-reference>>> place her in this video. "
        "same motion but my model instead. Structural breakdown: "
        "[0-3s] Begin a shoulder turn. Camera: fixed."
    )
    assert (
        "approved_creator_reference_element"
        not in command[command.index("--prompt") + 1]
    )
    assert (
        command[command.index("--image-references") + 1]
        == plan["recreationAnchorApproval"]["anchorFilePath"]
    )
    # Asserted against the shared constants, not literals: campaign's
    # RECREATE_REEL_STAGE reports these same values in the motion recipe, so this
    # is what stops the operator-facing recipe describing a render the provider
    # call did not make. The literal 480p/fast intent is pinned campaign-side.
    assert command[command.index("--mode") + 1] == subject.RECREATE_REEL_MODE
    assert (
        plan["command"][plan["command"].index("--resolution") + 1]
        == subject.RECREATE_REEL_RESOLUTION
    )
    assert command[command.index("--bitrate_mode") + 1] == "high"
    assert plan["command"][plan["command"].index("--generate_audio") + 1] == "false"
    assert "--start-image" not in command
    assert "--reference_elements" not in command
    assert "--multi_shot_mode" not in command


def test_recreate_qualification_rejects_seedance_mini(
    tmp_path: Path,
) -> None:
    driving = tmp_path / "driving.mp4"
    driving.write_bytes(b"driving-video")
    reference_elements = tmp_path / "stacey.json"
    reference_elements.write_text(
        json.dumps(
            [
                {
                    "id": "stacey-reference",
                    "name": "stacey",
                    "medias": [],
                    "video_medias": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        subject.HiggsfieldFeatureUnavailable,
        match="Mini was rejected",
    ):
        subject.build_higgsfield_production_plan(
            _request(
                tmp_path,
                recipe_id="higgsfield_recreate_reel",
                model="seedance_2_0_mini",
                driving_video_path=driving,
                duration_seconds=7,
                reference_elements_path=reference_elements,
            ),
            capabilities=_capabilities(),
            adapter=FakeAdapter([]),  # type: ignore[arg-type]
        )


def test_recreate_qualification_fails_without_creator_reference(
    tmp_path: Path,
) -> None:
    driving = tmp_path / "driving.mp4"
    driving.write_bytes(b"driving-video")
    with pytest.raises(FileNotFoundError, match="creator reference element"):
        subject.build_higgsfield_production_plan(
            _request(
                tmp_path,
                recipe_id="higgsfield_recreate_reel",
                model=None,
                driving_video_path=driving,
                duration_seconds=7,
                reference_elements_path=tmp_path / "missing-stacey.json",
            ),
            capabilities=_capabilities(),
            adapter=FakeAdapter([]),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "recipe",
    [
        "higgsfield_motion_copy_replace",
        "higgsfield_talking_speak",
        "higgsfield_talking_motion_copy",
    ],
)
def test_unexposed_marketing_features_fail_before_quote(
    tmp_path: Path, recipe: str
) -> None:
    with pytest.raises(subject.HiggsfieldFeatureUnavailable):
        subject.build_higgsfield_production_plan(
            _request(tmp_path, recipe_id=recipe, model=None),
            capabilities=_capabilities(),
            adapter=FakeAdapter([]),  # type: ignore[arg-type]
        )


def test_veo_is_experimental_and_cannot_claim_supplied_voice(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        recipe_id="higgsfield_talking_veo",
        model=None,
        prompt=None,
        script="I almost stayed home, but I am glad I came out.",
        tone="warm",
        pacing="unhurried",
        emotion="slightly amused",
    )
    with pytest.raises(
        subject.HiggsfieldFeatureUnavailable,
        match="no supplied-audio input",
    ):
        subject.build_higgsfield_production_plan(
            request,
            capabilities=_capabilities(),
            adapter=FakeAdapter([]),  # type: ignore[arg-type]
        )

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"voice")
    with pytest.raises(
        subject.HiggsfieldFeatureUnavailable,
        match="no supplied-audio input",
    ):
        subject.build_higgsfield_production_plan(
            _request(
                tmp_path,
                recipe_id="higgsfield_talking_veo",
                model=None,
                prompt=None,
                script="Exact words.",
                speech_audio_path=audio,
            ),
            capabilities=_capabilities(),
            adapter=FakeAdapter([]),  # type: ignore[arg-type]
        )


def test_credit_cap_blocks_before_submission(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [
            {"credits": 22.5},
        ]
    )
    with pytest.raises(PermissionError, match="quote_exceeds_credit_cap"):
        subject.execute_higgsfield_production(
            _request(tmp_path, max_credits=10.0),
            capabilities=_capabilities(),
            adapter=adapter,  # type: ignore[arg-type]
            confirm_paid=True,
        )
    assert adapter.commands[0][1:3] == ["generate", "cost"]
    assert all(command[2] != "create" for command in adapter.commands)


def test_success_hashes_registers_and_preserves_review_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FakeAdapter(
        [
            {"credits": 8.75},
            {"credits": 100.0},
            {"items": ["generation-1"]},
            {
                "items": [
                    {
                        "id": "generation-1",
                        "status": "completed",
                        "result_url": "https://cdn.example/video.mp4?token=secret",
                    }
                ]
            },
            {"credits": 91.25},
        ]
    )

    def fake_download(_url: str, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"review-video-bytes")
        return output

    monkeypatch.setattr(subject, "download_result", fake_download)
    monkeypatch.setattr(
        subject,
        "_probe_video",
        lambda _path: {
            "codec": "h264",
            "width": 720,
            "height": 1280,
            "durationSeconds": 5.0,
            "videoStreams": 1,
            "audioStreams": 0,
            "audio": [],
        },
    )
    monkeypatch.setattr(
        subject,
        "record_asset_generation",
        lambda *_args, **_kwargs: {
            "ok": True,
            "asset_generation_id": "asset-1",
            "identity": {"status": "unknown"},
        },
    )

    request = _request(tmp_path, balance_delta_attribution_allowed=True)
    receipt = subject.execute_higgsfield_production(
        request,
        capabilities=_capabilities(),
        adapter=adapter,  # type: ignore[arg-type]
        confirm_paid=True,
    )

    output = Path(receipt["finalOutput"]["path"])
    assert receipt["status"] == "completed"
    assert receipt["generationId"] == "generation-1"
    assert receipt["externalOperationId"] == "generation-1"
    assert receipt["operationReceipt"] == {
        "schema": "pipeline.operation_receipt.v1",
        "workItemId": receipt["workItemId"],
        "authorizationId": receipt["authorizationId"],
        "attemptId": receipt["attemptId"],
        "externalOperationId": "generation-1",
    }
    assert receipt["model"] == "kling3_0"
    assert receipt["creditsConsumed"] == 8.75
    assert receipt["creditsConsumedSource"] == "account_balance_delta"
    assert receipt["resultUrl"] == "https://cdn.example/video.mp4"
    assert receipt["finalOutput"]["sha256"] == subject._sha256_file(output)
    assert receipt["registration"]["asset_generation_id"] == "asset-1"
    assert set(subject.REVIEW_FIELDS).issubset(receipt["review"])
    assert receipt["review"]["generationTimeSeconds"] >= 0
    assert receipt["review"]["creditsConsumed"] == 8.75
    assert receipt["review"]["dollarCost"] is None
    assert receipt["review"]["identityPreservation"] is None
    assert receipt["review"]["handAnatomyQuality"] is None
    assert receipt["review"]["wouldPost"] is None
    receipts = list((tmp_path / "review" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    assert "secret" not in receipts[0].read_text(encoding="utf-8")
    expected_plan = subject.build_higgsfield_production_plan(
        request,
        capabilities=_capabilities(),
    )
    submitted = next(
        command
        for command in adapter.commands
        if command[:3] == ["higgsfield", "generate", "create"]
    )
    assert submitted == expected_plan["command"]

    recovered = subject.execute_higgsfield_production(
        request,
        adapter=FakeAdapter([]),  # type: ignore[arg-type]
        confirm_paid=True,
    )
    assert recovered["generationId"] == "generation-1"


def test_concurrent_balance_delta_is_not_attributed_to_one_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FakeAdapter(
        [
            {"credits": 8.75},
            {"credits": 100.0},
            {"items": ["generation-concurrent"]},
            {
                "items": [
                    {
                        "id": "generation-concurrent",
                        "status": "completed",
                        "result_url": "https://cdn.example/video.mp4",
                    }
                ]
            },
            {"credits": 70.0},
        ]
    )

    def fake_download(_url: str, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"concurrent-review-video")
        return output

    monkeypatch.setattr(subject, "download_result", fake_download)
    monkeypatch.setattr(
        subject,
        "_probe_video",
        lambda _path: {"audioStreams": 0},
    )
    monkeypatch.setattr(
        subject,
        "record_asset_generation",
        lambda *_args, **_kwargs: {
            "ok": True,
            "asset_generation_id": "asset-concurrent",
        },
    )

    receipt = subject.execute_higgsfield_production(
        _request(tmp_path, balance_delta_attribution_allowed=False),
        capabilities=_capabilities(),
        adapter=adapter,  # type: ignore[arg-type]
        confirm_paid=True,
    )

    assert receipt["creditsConsumed"] is None
    assert receipt["creditsConsumedSource"] == "unknown_concurrent_provider_operations"
    assert receipt["actualCreditsState"] == "unknown"
    assert receipt["actualCreditsReason"] == "concurrent_balance_delta_not_attributable"


def test_silent_recipe_quarantines_returned_provider_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeAdapter(
        [
            {"credits": 8.75},
            {"credits": 100.0},
            {"items": ["generation-with-audio"]},
            {
                "items": [
                    {
                        "id": "generation-with-audio",
                        "status": "completed",
                        "result_url": "https://cdn.example/video.mp4",
                    }
                ]
            },
            {"credits": 91.25},
        ]
    )

    def fake_download(_url: str, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"provider-video-with-audio")
        return output

    monkeypatch.setattr(subject, "download_result", fake_download)
    monkeypatch.setattr(subject, "_probe_video", lambda _path: {"audioStreams": 1})

    result = subject.execute_higgsfield_production(
        _request(tmp_path, balance_delta_attribution_allowed=True),
        capabilities=_capabilities(),
        adapter=adapter,  # type: ignore[arg-type]
        confirm_paid=True,
    )

    assert not (tmp_path / "review" / "output.mp4").exists()
    quarantined = list((tmp_path / "review").glob("output.mp4.quarantine.*"))
    assert len(quarantined) == 1
    receipt_path = next((tmp_path / "review" / "receipts").glob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rejected_unexpected_provider_audio"
    assert result["status"] == "rejected_unexpected_provider_audio"
    assert receipt["technicalRejection"] == "unexpected_provider_audio"
    assert receipt["actualCreditsState"] == "known"
    assert receipt["creditsConsumed"] == 8.75
    assert receipt["quarantinedOutput"]["path"] == str(quarantined[0])


def test_balance_snapshot_does_not_change_authorized_provider_request(
    tmp_path: Path,
) -> None:
    quoted_request = _request(
        tmp_path,
        work_item_id="work-1",
        attempt_id="attempt-1",
        campaign="campaign-1",
        cohort_id="cohort-1",
    )
    quoted_plan = subject.build_higgsfield_production_plan(
        quoted_request,
        capabilities=_capabilities(),
    )
    execution_plan = subject.build_higgsfield_production_plan(
        replace(
            quoted_request,
            batch_balance_snapshot_fingerprint="9" * 64,
        ),
        capabilities=_capabilities(),
    )

    assert (
        execution_plan["providerRequestFingerprint"]
        == quoted_plan["providerRequestFingerprint"]
    )
    assert (
        execution_plan["authorizationScope"]["batchBalanceSnapshotFingerprint"]
        == "9" * 64
    )


@pytest.mark.parametrize("recovery_state", ["temporary", "final", "symlink"])
def test_downloaded_receipt_resumes_without_any_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovery_state: str,
) -> None:
    base_request = _request(
        tmp_path,
        work_item_id="work-1",
        attempt_id="pipeline-1:1",
        authorization_id="authorization-1",
        campaign="campaign-1",
        cohort_id="cohort-1",
    )
    plan = subject.build_higgsfield_production_plan(
        base_request,
        capabilities=_capabilities(),
    )
    quote = {"provider": "higgsfield", "amount": 8.75, "unit": "higgsfield_credits"}
    request = replace(
        base_request,
        authorized_request_fingerprint=plan["providerRequestFingerprint"],
        authorized_quote_fingerprint=subject.higgsfield_quote_fingerprint(quote),
    )
    output = Path(request.output_path)
    temporary = output.with_name(
        f".{output.name}.{plan['executionFingerprint'][:16]}.download"
    )
    recovered_bytes = b"downloaded-before-crash"
    recovered_path = output if recovery_state == "final" else temporary
    recovered_path.parent.mkdir(parents=True)
    if recovery_state == "symlink":
        symlink_target = tmp_path / "symlink-target.mp4"
        symlink_target.write_bytes(recovered_bytes)
        recovered_path.symlink_to(symlink_target)
    else:
        recovered_path.write_bytes(recovered_bytes)
    digest = hashlib.sha256(recovered_bytes).hexdigest()
    receipt_path = Path(request.review_root) / "receipts" / "attempt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema": subject.SCHEMA,
                "status": "downloaded_output",
                "requestFingerprint": plan["requestFingerprint"],
                "providerRequestFingerprint": plan["providerRequestFingerprint"],
                "executionFingerprint": plan["executionFingerprint"],
                "providerCommandFingerprint": plan["authorizationScope"][
                    "providerCommandFingerprint"
                ],
                "workItemId": request.work_item_id,
                "attemptId": request.attempt_id,
                "authorizationId": request.authorization_id,
                "generationId": "generation-1",
                "model": request.model,
                "seed": request.seed,
                "prompt": plan["prompt"],
                "source": plan["source"],
                "creditQuote": quote,
                "balanceBefore": 100.0,
                "downloadedOutput": {
                    "generationId": "generation-1",
                    "temporaryPath": str(temporary),
                    "finalPath": str(output),
                    "sha256": digest,
                },
                "review": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "_probe_video", lambda _path: {"audioStreams": 0})
    monkeypatch.setattr(
        subject.HiggsfieldCliAdapter,
        "run_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local recovery must not call the provider")
        ),
    )
    monkeypatch.setattr(
        subject,
        "record_asset_generation",
        lambda *_args, **_kwargs: {"ok": True, "asset_generation_id": "asset-1"},
    )

    if recovery_state == "symlink":
        with pytest.raises(
            PermissionError, match="higgsfield_local_download_binding_mismatch"
        ):
            subject.resume_higgsfield_local_output(
                request,
                receipt_path=receipt_path,
            )
        assert not output.exists()
        return

    recovered = subject.resume_higgsfield_local_output(
        request, receipt_path=receipt_path
    )

    assert recovered["status"] == "completed"
    assert recovered["actualCreditsState"] == "unknown"
    assert recovered["actualCreditsReason"] == (
        "local_recovery_without_provider_credit_evidence"
    )
    assert output.read_bytes() == recovered_bytes


def test_downloaded_receipt_recovers_by_atomic_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output.mp4"
    temporary = tmp_path / ".output.mp4.temporary.download"
    temporary.write_bytes(b"downloaded-before-crash")
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    receipt_path = tmp_path / "receipt.json"
    receipt = {
        "downloadedOutput": {
            "generationId": "generation-1",
            "temporaryPath": str(temporary),
            "finalPath": str(output),
            "sha256": digest,
        }
    }
    expected_temporary = output.with_name(f".{output.name}.{'e' * 16}.download")
    temporary.replace(expected_temporary)
    monkeypatch.setattr(
        subject,
        "_probe_video",
        lambda _path: {"audioStreams": 0},
    )
    monkeypatch.setattr(
        subject,
        "download_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not download again")
        ),
    )

    retained, retained_sha, _probe = subject._retain_downloaded_output(
        result_url="https://cdn.example/video.mp4",
        output=output,
        generation_id="generation-1",
        execution_fingerprint="e" * 64,
        receipt=receipt,
        receipt_path=receipt_path,
    )

    assert retained == output
    assert retained_sha == digest
    assert output.read_bytes() == b"downloaded-before-crash"


def test_mismatched_final_output_is_quarantined_not_overwritten(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output.mp4"
    output.write_bytes(b"unrelated-existing-output")
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(FileExistsError, match="output_collision_quarantined"):
        subject._retain_downloaded_output(
            result_url="https://cdn.example/video.mp4",
            output=output,
            generation_id="generation-1",
            execution_fingerprint="e" * 64,
            receipt={"downloadedOutput": {"sha256": "f" * 64}},
            receipt_path=receipt_path,
        )

    quarantined = list(tmp_path.glob("output.mp4.quarantine.*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"unrelated-existing-output"


def test_motion_copy_missing_driving_video_never_submits(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([])
    with pytest.raises(ValueError, match="requires a driving video"):
        subject.execute_higgsfield_production(
            _request(
                tmp_path,
                recipe_id="higgsfield_motion_copy_animate",
                model=None,
                max_credits=20.0,
            ),
            capabilities=_capabilities(),
            adapter=adapter,  # type: ignore[arg-type]
            confirm_paid=True,
        )
    assert adapter.commands == []


def test_ambiguous_submission_is_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = FakeAdapter(
        [
            {"credits": 8.75},
            {"credits": 100.0},
            TimeoutError("create timed out"),
        ]
    )
    with pytest.raises(subject.HiggsfieldSubmissionNeedsReconciliation):
        subject.execute_higgsfield_production(
            _request(tmp_path),
            capabilities=_capabilities(),
            adapter=adapter,  # type: ignore[arg-type]
            confirm_paid=True,
        )
    receipt_path = next((tmp_path / "review" / "receipts").glob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "submission_ambiguous"
    assert receipt["requestFingerprint"]
    assert receipt["creditQuote"]["amount"] == 8.75
    assert receipt["balanceBefore"] == 100.0
    assert receipt["providerAccountSnapshot"]["credits"] == 100.0
    assert receipt["submittedAt"]
    assert receipt["model"]
    assert receipt["source"]["sha256"]

    second = FakeAdapter([{"credits": 8.75}, {"credits": 100.0}, {"items": []}])
    with pytest.raises(subject.HiggsfieldSubmissionNeedsReconciliation):
        subject.execute_higgsfield_production(
            _request(tmp_path),
            capabilities=_capabilities(),
            adapter=second,  # type: ignore[arg-type]
            confirm_paid=True,
        )
    assert all(command[2] != "create" for command in second.commands)
    classified = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert classified["submissionHistoryReconciliation"]["classification"] == (
        "ZERO_MATCHES"
    )


def test_ambiguous_submission_reconciles_one_exact_history_match(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        work_item_id="work-1",
        authorization_id="auth-1",
        attempt_id="attempt-1",
        client_request_correlation_id="creator-os:work-1:attempt-1",
    )
    plan = subject.build_higgsfield_production_plan(
        request,
        capabilities=_capabilities(),
        adapter=FakeAdapter([]),  # type: ignore[arg-type]
    )
    adapter = FakeAdapter(
        [
            {
                "items": [
                    {
                        "id": "generation-reconciled",
                        "created_at": "2026-07-29T12:00:10Z",
                        "job_type": "kling3_0",
                        "status": "completed",
                        "params": {
                            "prompt": plan["prompt"],
                            "duration": 5,
                            "aspect_ratio": "9:16",
                        },
                    }
                ]
            }
        ]
    )

    match = subject._reconcile_submission_history(
        request,
        plan=plan,
        receipt={"submittedAt": "2026-07-29T12:00:00Z"},
        adapter=adapter,  # type: ignore[arg-type]
    )

    assert match["classification"] == "EXACT_MATCH"
    assert match["match"]["id"] == "generation-reconciled"
    assert adapter.commands == [
        [
            "higgsfield",
            "generate",
            "list",
            "--video",
            "--size",
            "100",
            "--json",
        ]
    ]


def test_submission_started_after_process_death_reconciles_without_resubmit(
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        work_item_id="work-1",
        authorization_id="auth-1",
        attempt_id="attempt-1",
        client_request_correlation_id="creator-os:work-1:attempt-1",
    )
    plan = subject.build_higgsfield_production_plan(
        request,
        capabilities=_capabilities(),
    )
    adapter = FakeAdapter([{"items": []}])
    receipt_path = tmp_path / "submission-started.json"

    with pytest.raises(subject.HiggsfieldSubmissionNeedsReconciliation):
        subject._recover_higgsfield_generation(
            request,
            plan=plan,
            receipt={
                "status": "submission_started",
                "requestFingerprint": plan["requestFingerprint"],
                "generationId": None,
                "submittedAt": "2026-07-29T12:00:00Z",
            },
            receipt_path=receipt_path,
            adapter=adapter,  # type: ignore[arg-type]
        )

    assert all(
        command[:3] != ["higgsfield", "generate", "create"]
        for command in adapter.commands
    )
