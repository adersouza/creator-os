from __future__ import annotations

from pathlib import Path

import pytest
from reel_factory.motion_generate import _parser, build_request
from reel_factory.video_provider_models import (
    validate_model_request,
    video_model,
    video_model_catalog,
    video_model_ids,
)


def test_catalog_routes_best_paid_motion_to_wan27_pro_without_fallback() -> None:
    catalog = video_model_catalog()
    assert catalog["routing"] == {
        "localImageMotion": "local_wan22_ti2v_5b_mlx",
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
            "--dry-run",
        ]
    )
    with pytest.raises(ValueError, match="only --resolution 720p"):
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
