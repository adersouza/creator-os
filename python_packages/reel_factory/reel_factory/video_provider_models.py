"""Canonical model catalog for local and remote motion generation.

The catalog is deliberately small.  A model only enters Creator OS after its
input contract, output limits, cost policy, and retention behavior are known.
Provider marketing names must never be accepted as free-form runtime input.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Backend = Literal["local_mlx", "wavespeed"]
Task = Literal[
    "text_to_video",
    "image_to_video",
    "audio_image_to_video",
    "reference_to_video",
    "speech_to_video",
]


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
    supported_tasks: tuple[Task, ...] = ()
    audio_required: bool = False
    audio_supported: bool = False
    generated_audio_supported: bool = False
    first_last_frame: bool = False
    prompt_expansion_supported: bool = False
    paid: bool = False
    quality_tier: str = "production"
    shot_type_supported: bool = False
    local_runtime_family: str | None = None
    local_profile: str | None = None
    local_model_dir_name: str | None = None
    model_revision: str | None = None
    license_id: str | None = None
    lora_supported: bool = False
    spatial_upscaler: bool = False
    multi_keyframe: bool = False
    capability_status: Literal["production", "experimental"] = "production"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["resolutions"] = list(self.resolutions)
        value["durations"] = list(self.durations)
        value["supported_tasks"] = list(self.supported_tasks or (self.task,))
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
    supported_tasks=("text_to_video", "image_to_video"),
    resolutions=("720p",),
    durations=(5, 6, 7, 8),
    default_resolution="720p",
    default_duration=6,
    first_last_frame=False,
    paid=False,
    quality_tier="local_best",
    local_runtime_family="wan_2",
    local_profile="wan22_ti2v_5b_q8",
    local_model_dir_name="Wan2.2-TI2V-5B-MLX-Q8",
    model_revision="9624723c94ddf509832555c45e223a035baa7d1c",
    license_id="apache-2.0",
    lora_supported=True,
)

LOCAL_WAN22_I2V_A14B_Q4 = VideoModel(
    id="local_wan22_i2v_a14b_q4_mlx",
    backend="local_mlx",
    provider="local",
    provider_model="Wan-AI/Wan2.2-I2V-A14B",
    task="image_to_video",
    resolutions=("720p",),
    durations=(5, 6, 7, 8),
    default_resolution="720p",
    default_duration=6,
    paid=False,
    quality_tier="local_quality",
    local_runtime_family="wan_2",
    local_profile="wan22_i2v_a14b_q4",
    local_model_dir_name="Wan2.2-I2V-A14B-MLX-Q4",
    model_revision="c6c786170031eccc3a1fac0f98f1ad4ff988271e",
    license_id="apache-2.0",
    lora_supported=True,
)

LOCAL_LTX23_DISTILLED = VideoModel(
    id="local_ltx23_distilled_mlx",
    backend="local_mlx",
    provider="local",
    provider_model="Lightricks/LTX-2.3",
    task="image_to_video",
    supported_tasks=("text_to_video", "image_to_video", "audio_image_to_video"),
    resolutions=("576x1024",),
    durations=(5, 6, 7, 8),
    default_resolution="576x1024",
    default_duration=6,
    audio_supported=True,
    generated_audio_supported=True,
    first_last_frame=True,
    paid=False,
    quality_tier="local_audio_fast",
    local_runtime_family="ltx_2",
    local_profile="ltx23_distilled",
    local_model_dir_name="LTX-2.3-distilled-MLX",
    model_revision="65b104b9387fb173d8e4b92fc5effc47625baf2a",
    license_id="ltx-2-community-license-agreement",
    lora_supported=True,
)

LOCAL_LTX23_DEV_HQ = VideoModel(
    id="local_ltx23_dev_hq_mlx",
    backend="local_mlx",
    provider="local",
    provider_model="Lightricks/LTX-2.3",
    task="image_to_video",
    supported_tasks=("text_to_video", "image_to_video", "audio_image_to_video"),
    resolutions=("576x1024",),
    durations=(5, 6, 7, 8),
    default_resolution="576x1024",
    default_duration=6,
    audio_supported=True,
    generated_audio_supported=True,
    first_last_frame=True,
    paid=False,
    quality_tier="local_audio_hq",
    local_runtime_family="ltx_2",
    local_profile="ltx23_dev_two_stage_hq",
    local_model_dir_name="LTX-2.3-dev-MLX",
    model_revision="5da7eb70a6a8a2691f6810454a31f2790e65d8ee",
    license_id="ltx-2-community-license-agreement",
    lora_supported=True,
    spatial_upscaler=True,
)

# LongCat Avatar 1.5 is the strongest credible local talking-avatar route on
# Apple silicon as of 2026.  The MLX port is intentionally marked experimental:
# it is young, single-person, and bounded to short 480p review assets.  Creator
# OS still requires motion/lip-sync QC and human approval before export.
LOCAL_LONGCAT_AVATAR15_Q4 = VideoModel(
    id="local_longcat_avatar15_q4_mlx",
    backend="local_mlx",
    provider="local",
    provider_model="meituan-longcat/LongCat-Video-Avatar-1.5",
    task="audio_image_to_video",
    supported_tasks=("audio_image_to_video",),
    resolutions=("480x832",),
    durations=(3, 4, 5, 6),
    default_resolution="480x832",
    default_duration=4,
    audio_required=True,
    audio_supported=True,
    paid=False,
    quality_tier="local_talking_experimental",
    local_runtime_family="longcat_avatar",
    local_profile="longcat_avatar15_q4_dmd",
    local_model_dir_name="LongCat-Video-Avatar-1.5-q4-dmd-merged",
    model_revision="5d5b5d61ce6c206930a94c760f6941aff03f9389",
    license_id="mit",
    capability_status="experimental",
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
        LOCAL_WAN22_I2V_A14B_Q4,
        LOCAL_LTX23_DISTILLED,
        LOCAL_LTX23_DEV_HQ,
        LOCAL_LONGCAT_AVATAR15_Q4,
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
        model.id
        for model in _MODELS.values()
        if task is None or task in (model.supported_tasks or (model.task,))
    )


def video_model_catalog() -> dict[str, object]:
    return {
        "schema": "reel_factory.video_model_catalog.v1",
        "models": [model.to_dict() for model in _MODELS.values()],
        "routing": {
            "localImageMotion": LOCAL_WAN22_TI2V_5B.id,
            "localImageMotionQuality": LOCAL_WAN22_I2V_A14B_Q4.id,
            "localAudioMotionFast": LOCAL_LTX23_DISTILLED.id,
            "localAudioMotionQuality": LOCAL_LTX23_DEV_HQ.id,
            "localTextToVideo": LOCAL_LTX23_DISTILLED.id,
            "localSpeakingVideo": LOCAL_LONGCAT_AVATAR15_Q4.id,
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
    generate_audio: bool = False,
    task: Task | None = None,
    has_image: bool = True,
    has_lora: bool = False,
) -> None:
    selected_task = task or model.task
    supported_tasks = model.supported_tasks or (model.task,)
    if selected_task not in supported_tasks:
        raise ValueError(
            f"{model.id} does not support task {selected_task}; choose one of "
            + ", ".join(supported_tasks)
        )
    if selected_task in {"image_to_video", "audio_image_to_video"} and not has_image:
        raise ValueError(f"{model.id} task {selected_task} requires an image")
    if selected_task == "text_to_video" and has_image:
        raise ValueError("text_to_video must not silently consume an image")
    if selected_task == "audio_image_to_video" and not (has_audio or generate_audio):
        raise ValueError(
            f"{model.id} audio_image_to_video requires source or generated audio"
        )
    if selected_task != "audio_image_to_video" and (has_audio or generate_audio):
        raise ValueError("audio inputs require the explicit audio_image_to_video task")
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
    if has_audio and not (model.audio_required or model.audio_supported):
        raise ValueError(
            f"{model.id} does not accept audio in Creator OS; use wavespeed_wan22_s2v"
        )
    if generate_audio and not model.generated_audio_supported:
        raise ValueError(f"{model.id} does not support generated audio")
    if generate_audio and has_audio:
        raise ValueError("source audio and generated audio are mutually exclusive")
    if has_last_image and not model.first_last_frame:
        raise ValueError(f"{model.id} does not support a last image")
    if has_lora and not model.lora_supported:
        raise ValueError(f"{model.id} does not support a Creator OS LoRA")
