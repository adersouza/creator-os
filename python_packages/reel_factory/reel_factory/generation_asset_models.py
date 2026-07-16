"""Shared value objects and constants for Reel Factory asset generation."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

from .asset_prompt_contract import AssetPromptSet, parse_asset_prompt_response

IMAGE_MODEL = "text2image_soul_v2"
VIDEO_MODEL = "kling3_0"
DEFAULT_GRID_IMAGE_ASPECT_RATIO = "9:16"
DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO = "3:4"
DIRECT_REFERENCE_SEED_PROMPT = (
    "Use the supplied reference image as the visual guide. Recreate the same pose, clothing, setting, "
    "camera framing, lighting, and social-photo mood for this Soul ID model as one realistic {aspect_ratio} image."
)
IMAGE_MODEL_CANDIDATES = ("soul_2", "soul_v2", IMAGE_MODEL)
VIDEO_MODEL_CANDIDATES = (VIDEO_MODEL,)
CAPABILITY_SCHEMA = "reel_factory.higgsfield_capabilities.v1"
VIDEO_SOUND_MODELS = {"kling2_6", "kling3_0"}
DOWNLOAD_TIMEOUT_SECONDS = 60
MIN_IMAGE_RESULT_BYTES = 10_000
MIN_VIDEO_RESULT_BYTES = 100_000
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
POLICY_BOUND_WORKER_MODES = frozenset(
    {
        "reference-image",
        "reference-image-dry-run",
        "image",
        "image-dry-run",
        "video",
        "video-dry-run",
    }
)


def nonnegative_float_arg(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be a finite, non-negative number"
        ) from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite, non-negative number")
    return parsed


@dataclass(frozen=True)
class AssetGenerationPlan:
    prompt_json: Path
    stem: str
    reference: str | None
    soul_id: str | None
    soul_name: str | None
    start_image: str | None
    out_dir: Path
    source_dir: Path
    end_image: str | None = None
    video_reference: str | None = None
    campaign: str | None = None
    creator: str | None = None
    selected_panel: str | None = None
    image_mode: str = "single"
    image_aspect_ratio: str = DEFAULT_GRID_IMAGE_ASPECT_RATIO
    image_quality: str = "2k"
    video_aspect_ratio: str = "9:16"
    video_duration: int = 5
    video_mode: str | None = "pro"
    video_sound: str = "off"
    image_model: str = IMAGE_MODEL
    video_model: str = VIDEO_MODEL
    cohort_id: str = "creator_os_default"
    max_credits: float | None = None
    # Compatibility-only report field. Paid provider authorization uses native
    # Higgsfield credits and never this estimate.
    estimated_cost_usd: float | None = None
    allow_unbudgeted_local_test: bool = False
    budget_override_ledger_error: bool = False
    spend_authorization_file: Path | None = None


@dataclass(frozen=True)
class DirectReferenceImagePlan:
    reference_image: str
    stem: str
    soul_id: str | None
    soul_name: str | None
    out_dir: Path
    source_dir: Path
    creator: str | None = None
    campaign: str | None = None
    image_aspect_ratio: str = DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO
    image_quality: str = "2k"
    image_model: str = IMAGE_MODEL
    cohort_id: str = "creator_os_default"
    max_credits: float | None = None
    # Compatibility-only report field; see AssetGenerationPlan.
    estimated_cost_usd: float | None = None
    allow_unbudgeted_local_test: bool = False
    budget_override_ledger_error: bool = False
    spend_authorization_file: Path | None = None


def load_prompt(path: Path) -> AssetPromptSet:
    return parse_asset_prompt_response(path.read_text(encoding="utf-8"))


def lineage_path(plan: AssetGenerationPlan) -> Path:
    return plan.source_dir / f"{plan.stem}.generated_asset_lineage.json"


def direct_reference_lineage_path(plan: DirectReferenceImagePlan) -> Path:
    return plan.source_dir / f"{plan.stem}.direct_reference_lineage.json"


def direct_reference_prompt(
    aspect_ratio: str = DEFAULT_DIRECT_REFERENCE_IMAGE_ASPECT_RATIO,
) -> str:
    """Return the only active direct-reference seed prompt."""
    prompt = DIRECT_REFERENCE_SEED_PROMPT.format(aspect_ratio=aspect_ratio)
    return " ".join(prompt.split())
