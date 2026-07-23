from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from reel_factory.motion_generate import _load_bound_json, _parser, build_request
from reel_factory.video_provider_models import (
    validate_model_request,
    video_model,
    video_model_catalog,
    video_model_ids,
)


def _bound_evidence_args(tmp_path: Path) -> list[str]:
    arguments: list[str] = []
    for flag, name in (
        ("--local-motion-admission", "admission"),
        ("--benchmark-recipe", "recipe"),
        ("--analyzer-registry", "registry"),
    ):
        path = tmp_path / f"{name}.json"
        value = {"kind": name}
        if name == "admission":
            value = {
                "schema": "campaign_factory.local_motion_admission.v1",
                "evidenceRecords": {
                    "creatorIdentityProfile": {"profileId": "test-profile"},
                    "contentIntent": {"intentId": "test-intent"},
                },
                "taskParameterMaterial": {
                    "policyContext": {
                        "commercialUse": True,
                        "commercialAnnualRevenueUsd": 1_000,
                        "overlaysExist": False,
                    }
                },
            }
        payload = json.dumps(value, sort_keys=True).encode("utf-8")
        path.write_bytes(payload)
        arguments.extend(
            [flag, str(path), f"{flag}-sha256", hashlib.sha256(payload).hexdigest()]
        )
    return arguments


def test_catalog_routes_best_paid_motion_to_wan27_pro_without_fallback() -> None:
    catalog = video_model_catalog()
    assert catalog["routing"] == {
        "localImageMotion": "local_wan22_ti2v_5b_mlx",
        "localImageMotionQuality": "local_wan22_i2v_a14b_q4_mlx",
        "localAudioMotionFast": "local_ltx23_distilled_mlx",
        "localAudioMotionQuality": "local_ltx23_dev_hq_mlx",
        "localTextToVideo": "local_ltx23_distilled_mlx",
        "localSpeakingVideo": "local_longcat_avatar15_q4_mlx",
        "paidImageMotion": "wavespeed_wan27_i2v_pro",
        "paidImageMotionEconomy": "wavespeed_wan27_i2v",
        "paidReferenceMotion": "wavespeed_wan27_reference",
        "paidSpeakingVideo": "wavespeed_wan22_s2v",
        "silentProviderFallbackAllowed": False,
    }
    assert "wavespeed_wan27_i2v_pro" in video_model_ids(task="image_to_video")


def test_models_enforce_exact_capabilities() -> None:
    pro = video_model("wavespeed_wan27_i2v_pro")
    validate_model_request(
        pro,
        resolution="4k",
        duration=15,
        has_audio=False,
        has_last_image=False,
    )
    with pytest.raises(ValueError, match="does not support a last image"):
        validate_model_request(
            pro,
            resolution="1080p",
            duration=5,
            has_audio=False,
            has_last_image=True,
        )
    reference = video_model("wavespeed_wan27_reference")
    with pytest.raises(ValueError, match="duration must be one of 5, 10"):
        validate_model_request(
            reference,
            resolution="1080p",
            duration=15,
            has_audio=False,
            has_last_image=False,
        )


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported video model"):
        video_model("whatever-is-cheapest-today")


def test_motion_evidence_receiver_rejects_substitution_and_symlink(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "admission.json"
    evidence.write_text("{}", encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    assert _load_bound_json(evidence, digest, label="admission") == {}
    evidence.write_text('{"substituted":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="sha256_mismatch"):
        _load_bound_json(evidence, digest, label="admission")
    symlink = tmp_path / "linked.json"
    symlink.symlink_to(evidence)
    with pytest.raises(ValueError, match="missing_or_unsafe"):
        _load_bound_json(
            symlink,
            hashlib.sha256(evidence.read_bytes()).hexdigest(),
            label="admission",
        )


def test_motion_worker_rejects_backend_specific_options_instead_of_ignoring_them(
    tmp_path: Path,
) -> None:
    image = tmp_path / "still.jpg"
    image.write_bytes(b"still")
    local_args = _parser().parse_args(
        [
            "--model",
            "local_wan22_ti2v_5b_mlx",
            "--prompt",
            "Natural breathing and a slow camera push toward the subject",
            "--image",
            str(image),
            "--out",
            str(tmp_path / "local.mp4"),
            "--campaign",
            "campaign",
            "--resolution",
            "1080p",
            *_bound_evidence_args(tmp_path),
            "--dry-run",
        ]
    )
    with pytest.raises(ValueError, match="resolution must be one of 720p"):
        build_request(local_args)

    remote_args = _parser().parse_args(
        [
            "--model",
            "wavespeed_wan27_i2v_pro",
            "--prompt",
            "Natural breathing and a slow camera push toward the subject",
            "--image",
            str(image),
            "--out",
            str(tmp_path / "remote.mp4"),
            "--campaign",
            "campaign",
            "--steps",
            "30",
            "--dry-run",
        ]
    )
    with pytest.raises(ValueError, match="steps applies only"):
        build_request(remote_args)

    remote_memory_args = _parser().parse_args(
        [
            "--model",
            "wavespeed_wan27_i2v_pro",
            "--prompt",
            "Natural breathing and a slow camera push toward the subject",
            "--image",
            str(image),
            "--out",
            str(tmp_path / "remote-memory.mp4"),
            "--campaign",
            "campaign",
            "--tile-spatial",
            "3",
            "--dry-run",
        ]
    )
    with pytest.raises(ValueError, match="memory controls require a local model"):
        build_request(remote_memory_args)


def test_ltx_audio_capabilities_are_explicit_and_never_inferred(tmp_path: Path) -> None:
    image = tmp_path / "still.jpg"
    image.write_bytes(b"still")
    args = _parser().parse_args(
        [
            "--model",
            "local_ltx23_distilled_mlx",
            "--prompt",
            "Natural portrait motion while matching a short source audio clip",
            "--image",
            str(image),
            "--out",
            str(tmp_path / "local.mp4"),
            "--campaign",
            "campaign",
            "--generate-audio",
            "--task",
            "image_to_video",
            *_bound_evidence_args(tmp_path),
            "--dry-run",
        ]
    )
    request = build_request(args)
    assert request.audio_mode == "generated"
    assert request.task == "image_to_video"
    assert request.audio_path is None

    wan = video_model("local_wan22_ti2v_5b_mlx")
    with pytest.raises(ValueError, match="does not support generated audio"):
        validate_model_request(
            wan,
            resolution="720p",
            duration=6,
            has_audio=False,
            has_last_image=False,
            generate_audio=True,
        )


def test_audio_task_and_inputs_cannot_silently_disagree() -> None:
    ltx = video_model("local_ltx23_dev_hq_mlx")
    with pytest.raises(ValueError, match="requires exact source audio"):
        validate_model_request(
            ltx,
            resolution="576x1024",
            duration=6,
            has_audio=False,
            has_last_image=False,
            task="audio_image_to_video",
        )
    with pytest.raises(ValueError, match="explicit audio_image_to_video task"):
        validate_model_request(
            ltx,
            resolution="576x1024",
            duration=6,
            has_audio=True,
            has_last_image=False,
            task="image_to_video",
        )


def test_model_discovery_includes_every_explicitly_supported_task() -> None:
    from reel_factory.video_provider_models import video_model_ids

    assert "local_wan22_ti2v_5b_mlx" in video_model_ids(task="text_to_video")
    assert "local_ltx23_distilled_mlx" in video_model_ids(task="text_to_video")
    assert "local_ltx23_dev_hq_mlx" in video_model_ids(task="audio_image_to_video")
    assert "local_ltx23_dev_hq_mlx" in video_model_ids(task="keyframe_interpolation")
    assert "local_ltx23_dev_hq_mlx" in video_model_ids(task="video_retake")
    assert "local_ltx23_dev_hq_mlx" in video_model_ids(task="video_extend")
