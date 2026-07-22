"""Canonical model catalog for local and remote motion generation.

The catalog is deliberately small.  A model only enters Creator OS after its
input contract, output limits, cost policy, and retention behavior are known.
Provider marketing names must never be accepted as free-form runtime input.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Backend = Literal["local_mlx", "wavespeed"]
Task = Literal["image_to_video", "reference_to_video", "speech_to_video"]


@dataclass(frozen=True, slots=True)
class VideoModel:
    id: str
    backend: Backend
    provider: str
    provider_model: str
    task: Task
    resolutions: tuple[str, ...]
    durations: tuple[int, ...]
    default_resolution: str
    default_duration: int
    audio_required: bool = False
    first_last_frame: bool = False
    prompt_expansion_supported: bool = False
    paid: bool = False
    quality_tier: str = "production"
    shot_type_supported: bool = False

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["resolutions"] = list(self.resolutions)
        value["durations"] = list(self.durations)
        return value


# Wan 2.2 TI2V-5B is the current Wan 2.2 checkpoint selected for practical
# Apple-silicon execution.  MLX-Video provides the
# native Apple execution layer; model weights remain the official Wan weights.
LOCAL_WAN22_TI2V_5B = VideoModel(
    id="local_wan22_ti2v_5b_mlx",
    backend="local_mlx",
    provider="local",
    provider_model="Wan-AI/Wan2.2-TI2V-5B",
    task="image_to_video",
    resolutions=("720p",),
    durations=(5, 6, 7, 8),
    default_resolution="720p",
    default_duration=6,
    first_last_frame=False,
    paid=False,
    quality_tier="local_best",
)

# The standard Wan 2.7 endpoint remains available as the lower-cost control. It
# has documented 720p/1080p and first/last-frame behavior plus parameter-derived
# pricing, but it is not the quality default.
WAVESPEED_WAN27_I2V = VideoModel(
    id="wavespeed_wan27_i2v",
    backend="wavespeed",
    provider="wavespeed",
    provider_model="alibaba/wan-2.7/image-to-video",
    task="image_to_video",
    resolutions=("720p", "1080p"),
    durations=(5, 10, 15),
    default_resolution="1080p",
    default_duration=5,
    first_last_frame=True,
    prompt_expansion_supported=True,
    paid=True,
    quality_tier="remote_best_bounded",
)

# Pro is the default paid image-motion route.  WaveSpeed publishes an exact
# parameter price for all supported duration/resolution pairs, so Campaign
# Factory can authorize it without trusting a marketing "starting at" price.
WAVESPEED_WAN27_I2V_PRO = VideoModel(
    id="wavespeed_wan27_i2v_pro",
    backend="wavespeed",
    provider="wavespeed",
    provider_model="alibaba/wan-2.7/image-to-video-pro",
    task="image_to_video",
    resolutions=("1080p", "2k", "4k"),
    durations=(5, 10, 15),
    default_resolution="1080p",
    default_duration=5,
    prompt_expansion_supported=True,
    paid=True,
    quality_tier="remote_best",
    shot_type_supported=True,
)

WAVESPEED_WAN27_REFERENCE = VideoModel(
    id="wavespeed_wan27_reference",
    backend="wavespeed",
    provider="wavespeed",
    provider_model="alibaba/wan-2.7/reference-to-video",
    task="reference_to_video",
    resolutions=("720p", "1080p"),
    durations=(5, 10),
    default_resolution="1080p",
    default_duration=5,
    prompt_expansion_supported=True,
    paid=True,
    quality_tier="remote_best_reference",
)

WAVESPEED_WAN22_S2V = VideoModel(
    id="wavespeed_wan22_s2v",
    backend="wavespeed",
    provider="wavespeed",
    provider_model="wavespeed-ai/wan-2.2/speech-to-video",
    task="speech_to_video",
    resolutions=("480p", "720p"),
    durations=(),  # Output length follows the supplied speech audio.
    default_resolution="720p",
    default_duration=0,
    audio_required=True,
    paid=True,
    quality_tier="remote_best_speaking",
)

_MODELS = {
    model.id: model
    for model in (
        LOCAL_WAN22_TI2V_5B,
        WAVESPEED_WAN27_I2V,
        WAVESPEED_WAN27_I2V_PRO,
        WAVESPEED_WAN27_REFERENCE,
        WAVESPEED_WAN22_S2V,
    )
}


def video_model(model_id: str) -> VideoModel:
    normalized = str(model_id or "").strip().lower().replace("-", "_")
    try:
        return _MODELS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported video model: {model_id}") from exc


def video_model_ids(*, task: Task | None = None) -> tuple[str, ...]:
    return tuple(
        model.id for model in _MODELS.values() if task is None or model.task == task
    )


def video_model_catalog() -> dict[str, object]:
    return {
        "schema": "reel_factory.video_model_catalog.v1",
        "models": [model.to_dict() for model in _MODELS.values()],
        "routing": {
            "localImageMotion": LOCAL_WAN22_TI2V_5B.id,
            "paidImageMotion": WAVESPEED_WAN27_I2V_PRO.id,
            "paidImageMotionEconomy": WAVESPEED_WAN27_I2V.id,
            "paidReferenceMotion": WAVESPEED_WAN27_REFERENCE.id,
            "paidSpeakingVideo": WAVESPEED_WAN22_S2V.id,
            "silentProviderFallbackAllowed": False,
        },
    }


def validate_model_request(
    model: VideoModel,
    *,
    resolution: str,
    duration: int | None,
    has_audio: bool,
    has_last_image: bool,
) -> None:
    if resolution not in model.resolutions:
        raise ValueError(
            f"{model.id} resolution must be one of {', '.join(model.resolutions)}"
        )
    if model.durations and duration not in model.durations:
        raise ValueError(
            f"{model.id} duration must be one of "
            + ", ".join(str(value) for value in model.durations)
        )
    if not model.durations and duration not in {None, 0}:
        raise ValueError(f"{model.id} duration is determined by its audio input")
    if model.audio_required and not has_audio:
        raise ValueError(f"{model.id} requires an audio input")
    if model.task != "speech_to_video" and has_audio:
        raise ValueError(
            f"{model.id} does not accept audio in Creator OS; use wavespeed_wan22_s2v"
        )
    if has_last_image and not model.first_last_frame:
        raise ValueError(f"{model.id} does not support a last image")
