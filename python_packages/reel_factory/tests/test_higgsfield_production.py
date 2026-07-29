from __future__ import annotations

import hashlib
import json
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
    }
    values.update(overrides)
    if (
        values["recipe_id"] == "higgsfield_recreate_reel"
        and values.get("driving_video_path")
        and not values.get("recreation_anchor_approval")
    ):
        driving = Path(values["driving_video_path"])
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
            reference_video_sha256=hashlib.sha256(driving.read_bytes()).hexdigest(),
            selected_composition_frame_sha256="c" * 64,
            approved_by="operator@test",
        )
        values["source_approval"] = approval["approvalFingerprint"]
        values["source_image_path"] = Path(approval["anchorFilePath"])
        values["recreation_anchor_approval"] = approval
    return subject.HiggsfieldProductionRequest(**values)


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
    assert command[command.index("--mode") + 1] == "fast"
    assert plan["command"][plan["command"].index("--resolution") + 1] == "480p"
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

    receipt = subject.execute_higgsfield_production(
        _request(tmp_path),
        capabilities=_capabilities(),
        adapter=adapter,  # type: ignore[arg-type]
        confirm_paid=True,
    )

    output = Path(receipt["finalOutput"]["path"])
    assert receipt["status"] == "completed"
    assert receipt["generationId"] == "generation-1"
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

    second = FakeAdapter([{"credits": 8.75}, {"credits": 100.0}])
    with pytest.raises(subject.HiggsfieldSubmissionNeedsReconciliation):
        subject.execute_higgsfield_production(
            _request(tmp_path),
            capabilities=_capabilities(),
            adapter=second,  # type: ignore[arg-type]
            confirm_paid=True,
        )
    assert all(command[2] != "create" for command in second.commands)
