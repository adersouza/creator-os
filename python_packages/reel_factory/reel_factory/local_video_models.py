"""Pinned local video model and runtime installation catalog.

Generation is deliberately offline.  This catalog is the only place where
Creator OS maps an operator-facing local model id to download provenance,
runtime arguments, disk expectations, and license obligations.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .video_provider_models import video_model

MLX_VIDEO_REVISION = "87db56a51758fefb748a359b90a5283bb8ba4837"
MLX_VIDEO_REPOSITORY = "https://github.com/Blaizzy/mlx-video.git"
LONGCAT_MLX_REVISION = "e2e1e8701424cef0e601281b62e228e5289ed032"
LONGCAT_MLX_REPOSITORY = "https://github.com/xocialize/longcat-avatar-mlx.git"
MODEL_MANIFEST = ".creator-os-model.json"

LocalFamily = Literal["wan_2", "ltx_2", "longcat_avatar"]


@dataclass(frozen=True, slots=True)
class LocalInstallDependency:
    id: str
    repository: str
    revision: str
    directory_name: str
    includes: tuple[str, ...]
    estimated_bytes: int
    license_id: str
    cache_only: bool = False

    def directory(self, root: Path | None = None) -> Path:
        return (_models_root(root) / self.directory_name).resolve()


@dataclass(frozen=True, slots=True)
class LocalVideoModelSpec:
    model_id: str
    family: LocalFamily
    repository: str
    revision: str
    directory_name: str
    includes: tuple[str, ...]
    required_paths: tuple[str, ...]
    estimated_bytes: int
    quantization: str
    pipeline: str
    width: int
    height: int
    fps: int
    guide_scale: str
    default_steps: int
    license_id: str
    dependency_ids: tuple[str, ...] = ()
    source_repository: str | None = None
    source_revision: str | None = None
    ai_disclosure_required: bool = False
    commercial_revenue_limit_usd: int | None = None

    def directory(self, root: Path | None = None) -> Path:
        return (_models_root(root) / self.directory_name).resolve()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["includes"] = list(self.includes)
        payload["required_paths"] = list(self.required_paths)
        payload["dependency_ids"] = list(self.dependency_ids)
        payload["directory"] = str(self.directory())
        return payload


LTX23_SHARED = LocalInstallDependency(
    id="ltx23_shared_mlx",
    repository="prince-canuma/LTX-2.3-dev",
    revision="5da7eb70a6a8a2691f6810454a31f2790e65d8ee",
    directory_name="LTX-2.3-shared-MLX",
    includes=(
        "audio_vae/**",
        "text_projections/**",
        "vae/**",
        "vocoder/**",
        "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
    ),
    estimated_bytes=9_157_400_000,
    license_id="ltx-2-community-license-agreement",
)

LTX23_TEXT_ENCODER = LocalInstallDependency(
    id="ltx23_gemma_text_encoder",
    repository="Lightricks/gemma-3-12b-it-qat-q4_0-unquantized",
    revision="d62fe4f1995ade703b49a0f3c0d0f161237ef437",
    directory_name="LTX-Gemma3-12B",
    includes=("*",),
    estimated_bytes=24_413_000_000,
    license_id="gemma",
)

WAN_UMT5_TOKENIZER = LocalInstallDependency(
    id="wan_umt5_tokenizer",
    repository="google/umt5-xxl",
    revision="66cb9e7e85526fe440a945569e42c72fb6cbc0ad",
    directory_name=".hf-home/hub",
    includes=(
        "config.json",
        "special_tokens_map.json",
        "spiece.model",
        "tokenizer.json",
        "tokenizer_config.json",
    ),
    estimated_bytes=6_000_000,
    license_id="apache-2.0",
    cache_only=True,
)

_DEPENDENCIES = {
    dependency.id: dependency
    for dependency in (LTX23_SHARED, LTX23_TEXT_ENCODER, WAN_UMT5_TOKENIZER)
}

WAN22_TI2V_5B_Q8 = LocalVideoModelSpec(
    model_id="local_wan22_ti2v_5b_mlx",
    family="wan_2",
    repository="Anes1032/Wan2.2-TI2V-5B-mlx-q8",
    revision="9624723c94ddf509832555c45e223a035baa7d1c",
    directory_name="Wan2.2-TI2V-5B-MLX-Q8",
    includes=(
        "LICENSE",
        "NOTICE",
        "README.md",
        "config.json",
        "model.safetensors",
        "t5_encoder.safetensors",
        "vae.safetensors",
    ),
    required_paths=(
        "config.json",
        "model.safetensors",
        "t5_encoder.safetensors",
        "vae.safetensors",
    ),
    estimated_bytes=19_581_000_000,
    quantization="q8_group64",
    pipeline="wan22_ti2v",
    width=704,
    height=1280,
    fps=24,
    guide_scale="5.0",
    default_steps=40,
    license_id="apache-2.0",
    source_repository="Wan-AI/Wan2.2-TI2V-5B",
    source_revision="921dbaf3f1674a56f47e83fb80a34bac8a8f203e",
    dependency_ids=(WAN_UMT5_TOKENIZER.id,),
)

WAN22_I2V_A14B_Q4 = LocalVideoModelSpec(
    model_id="local_wan22_i2v_a14b_q4_mlx",
    family="wan_2",
    repository="SceneWorks/wan2.2-i2v-a14b-mlx",
    revision="c6c786170031eccc3a1fac0f98f1ad4ff988271e",
    directory_name="Wan2.2-I2V-A14B-MLX-Q4",
    includes=("q4/**", "LICENSE", "README.md"),
    required_paths=(
        "q4/config.json",
        "q4/high_noise_model.safetensors",
        "q4/low_noise_model.safetensors",
        "q4/t5_encoder.safetensors",
        "q4/vae.safetensors",
    ),
    estimated_bytes=28_647_000_000,
    quantization="q4_group64",
    pipeline="wan22_i2v",
    width=704,
    height=1280,
    fps=16,
    guide_scale="3.5,3.5",
    default_steps=20,
    license_id="apache-2.0",
    source_repository="Wan-AI/Wan2.2-I2V-A14B",
    source_revision="206a9ee1b7bfaaf8f7e4d81335650533490646a3",
    dependency_ids=(WAN_UMT5_TOKENIZER.id,),
)

_LTX_REQUIRED = (
    "transformer/config.json",
    "transformer/model.safetensors.index.json",
)

LTX23_DISTILLED = LocalVideoModelSpec(
    model_id="local_ltx23_distilled_mlx",
    family="ltx_2",
    repository="prince-canuma/LTX-2.3-distilled",
    revision="65b104b9387fb173d8e4b92fc5effc47625baf2a",
    directory_name="LTX-2.3-distilled-MLX",
    includes=(
        "transformer/config.json",
        "transformer/model.safetensors.index.json",
        "transformer/model-*-of-00018.safetensors",
    ),
    required_paths=_LTX_REQUIRED,
    estimated_bytes=37_989_000_000,
    quantization="bf16",
    pipeline="distilled",
    width=576,
    height=1024,
    fps=24,
    guide_scale="1.0",
    default_steps=8,
    license_id="ltx-2-community-license-agreement",
    dependency_ids=(LTX23_SHARED.id, LTX23_TEXT_ENCODER.id),
    source_repository="Lightricks/LTX-2.3",
    source_revision="4229404625088d21c4f112eb640fb04a0900ee25",
    ai_disclosure_required=True,
    commercial_revenue_limit_usd=10_000_000,
)

LTX23_DEV_HQ = LocalVideoModelSpec(
    model_id="local_ltx23_dev_hq_mlx",
    family="ltx_2",
    repository="prince-canuma/LTX-2.3-dev",
    revision="5da7eb70a6a8a2691f6810454a31f2790e65d8ee",
    directory_name="LTX-2.3-dev-MLX",
    includes=(
        "transformer/**",
        "ltx-2.3-22b-distilled-lora-384.safetensors",
    ),
    required_paths=(
        *_LTX_REQUIRED,
        "ltx-2.3-22b-distilled-lora-384.safetensors",
    ),
    estimated_bytes=45_585_000_000,
    quantization="bf16",
    pipeline="dev-two-stage-hq",
    width=576,
    height=1024,
    fps=24,
    guide_scale="3.0",
    default_steps=15,
    license_id="ltx-2-community-license-agreement",
    dependency_ids=(LTX23_SHARED.id, LTX23_TEXT_ENCODER.id),
    source_repository="Lightricks/LTX-2.3",
    source_revision="4229404625088d21c4f112eb640fb04a0900ee25",
    ai_disclosure_required=True,
    commercial_revenue_limit_usd=10_000_000,
)

LONGCAT_AVATAR15_Q4 = LocalVideoModelSpec(
    model_id="local_longcat_avatar15_q4_mlx",
    family="longcat_avatar",
    repository="mlx-community/LongCat-Video-Avatar-1.5-q4-dmd-merged",
    revision="5d5b5d61ce6c206930a94c760f6941aff03f9389",
    directory_name="LongCat-Video-Avatar-1.5-q4-dmd-merged",
    includes=("*",),
    required_paths=(
        "pipeline_config.json",
        "audio_encoder/config.json",
        "audio_encoder/model.safetensors",
        "dit/config.json",
        "dit/diffusion_pytorch_model.safetensors.index.json",
        "text_encoder/config.json",
        "text_encoder/model.safetensors.index.json",
        "tokenizer/tokenizer.json",
        "vae/config.json",
        "vae/diffusion_pytorch_model.safetensors",
    ),
    estimated_bytes=25_013_365_609,
    quantization="q4_group64_dmd_merged",
    pipeline="longcat_avatar15_q4_dmd",
    width=480,
    height=832,
    fps=25,
    guide_scale="4.0",
    default_steps=8,
    license_id="mit",
    source_repository="meituan-longcat/LongCat-Video-Avatar-1.5",
    source_revision="92016c71d5d318d0f5d84e4db30015a571484ab6",
    ai_disclosure_required=True,
)

_SPECS = {
    spec.model_id: spec
    for spec in (
        WAN22_TI2V_5B_Q8,
        WAN22_I2V_A14B_Q4,
        LTX23_DISTILLED,
        LTX23_DEV_HQ,
        LONGCAT_AVATAR15_Q4,
    )
}


def local_video_model_spec(model_id: str) -> LocalVideoModelSpec:
    normalized = str(model_id or "").strip().lower().replace("-", "_")
    try:
        spec = _SPECS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported local video model: {model_id}") from exc
    catalog_model = video_model(normalized)
    if catalog_model.backend != "local_mlx":
        raise ValueError(f"{model_id} is not a local MLX model")
    if catalog_model.model_revision != spec.revision:
        raise RuntimeError(f"local model catalog drift for {model_id}")
    return spec


def local_video_model_specs() -> tuple[LocalVideoModelSpec, ...]:
    return tuple(_SPECS.values())


def local_install_dependency(dependency_id: str) -> LocalInstallDependency:
    try:
        return _DEPENDENCIES[dependency_id]
    except KeyError as exc:
        raise ValueError(f"unknown local model dependency: {dependency_id}") from exc


def local_install_dependencies() -> tuple[LocalInstallDependency, ...]:
    return tuple(_DEPENDENCIES.values())


def default_local_model_dir(model_id: str) -> Path:
    return local_video_model_spec(model_id).directory()


def ltx_text_encoder_dir(root: Path | None = None) -> Path:
    return LTX23_TEXT_ENCODER.directory(root)


def ltx_shared_dir(root: Path | None = None) -> Path:
    return LTX23_SHARED.directory(root)


def local_model_catalog() -> dict[str, object]:
    return {
        "schema": "reel_factory.local_model_catalog.v1",
        # Keep the original singleton key for read-only consumers while the
        # explicit map becomes the source of truth for family-aware routing.
        "runtime": {
            "repository": MLX_VIDEO_REPOSITORY,
            "revision": MLX_VIDEO_REVISION,
        },
        "runtimes": {
            "mlx_video": {
                "repository": MLX_VIDEO_REPOSITORY,
                "revision": MLX_VIDEO_REVISION,
            },
            "longcat_avatar": {
                "repository": LONGCAT_MLX_REPOSITORY,
                "revision": LONGCAT_MLX_REVISION,
                "status": "experimental",
            },
        },
        "modelsRoot": str(_models_root()),
        "models": [spec.to_dict() for spec in local_video_model_specs()],
        "dependencies": [asdict(value) for value in local_install_dependencies()],
        "generationDownloadsAllowed": False,
        "providerCalls": 0,
        "paidGeneration": False,
    }


def runtime_identity(family: LocalFamily) -> tuple[str, str, str]:
    if family == "longcat_avatar":
        return ("longcat_avatar", LONGCAT_MLX_REPOSITORY, LONGCAT_MLX_REVISION)
    return ("mlx_video", MLX_VIDEO_REPOSITORY, MLX_VIDEO_REVISION)


def _models_root(value: Path | None = None) -> Path:
    selected = value or os.environ.get("CREATOR_OS_LOCAL_MODELS_ROOT")
    selected = selected or Path.home() / ".creator-os/models"
    return Path(selected).expanduser().resolve()
