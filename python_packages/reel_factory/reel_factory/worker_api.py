"""Stable in-process APIs exposed to the Campaign Factory control plane."""

from __future__ import annotations

from .anatomy_qc import assess_image_qc as assess_image_qc
from .audio_intent import read_audio_intent
from .caption_bank import (
    CaptionBankStore,
    caption_hook_payload,
    load_or_build_caption_bank_store,
)
from .caption_scene_fit import classify_reel_scene_tags as classify_reel_scene_tags
from .caption_scene_fit import (
    infer_caption_topic_for_reel as infer_caption_topic_for_reel,
)
from .derived_stills import (
    DERIVED_STILL_SCHEMA as DERIVED_STILL_SCHEMA,
)
from .derived_stills import PILOT_COLORWAYS as PILOT_COLORWAYS
from .derived_stills import PROMPT_BUILDER_VERSION as PROMPT_BUILDER_VERSION
from .derived_stills import assess_edit_locality as assess_edit_locality
from .derived_stills import build_edit_prompt as build_edit_prompt
from .derived_stills import evaluate_harvest_frame as evaluate_harvest_frame
from .derived_stills import harvest_animation_frames as harvest_animation_frames
from .derived_stills import (
    materialize_individual_outputs as materialize_individual_outputs,
)
from .derived_stills import provider_adapter as provider_adapter
from .derived_stills import split_grid_2x3 as split_grid_2x3
from .higgsfield_production import (
    RECREATE_REEL_MODE,
    RECREATE_REEL_RESOLUTION,
    HiggsfieldProductionRequest,
    build_higgsfield_production_plan,
    discover_higgsfield_production_capabilities,
    execute_higgsfield_production,
    quote_higgsfield_production_plan,
)
from .higgsfield_production import (
    higgsfield_execution_fingerprint as higgsfield_execution_fingerprint,
)
from .higgsfield_production import (
    higgsfield_quote_fingerprint as higgsfield_quote_fingerprint,
)
from .higgsfield_production import (
    resume_higgsfield_local_output as resume_higgsfield_local_output,
)
from .identity_verification import verify_identity as verify_identity
from .observed_profiles import (
    contentforge_qc_policy_sha256 as contentforge_qc_policy_sha256,
)
from .observed_profiles import normalize_profile_id as normalize_profile_id
from .observed_profiles import probe_media_identity as probe_media_identity
from .observed_profiles import (
    qualify_renderer_equivalence as qualify_renderer_equivalence,
)
from .observed_profiles import render_observed_profile as render_observed_profile
from .observed_profiles import renderer_runtime_receipt as renderer_runtime_receipt
from .observed_profiles import toolchain_receipt as toolchain_receipt
from .perceptual import media_identity as media_identity
from .reddit_gif import render_reddit_gif as render_reddit_gif
from .reel_pipeline_selection import (
    apply_caption_fit_to_caption_set as apply_caption_fit_to_caption_set,
)
from .reel_pipeline_support import CaptionSet as CaptionSet
from .reel_url_import import (
    canonicalize_reel_url as canonicalize_reel_url,
)
from .reel_url_import import download_reel_url as download_reel_url


def gemini_motion_analysis_instruction(reference_id: str) -> str:
    """Return the bounded prompt for the retained motion-analysis contract."""

    resolved = " ".join(str(reference_id or "").split())
    if not resolved:
        raise ValueError("reference_id is required")
    return (
        "Analyze the attached operator-selected reference video as motion structure "
        "only. Return exactly one JSON object matching schema "
        "reel_factory.reference_video_motion_analysis.v1 with referenceId "
        f"{resolved}. The supported input scope is a 4 to 15 second 9:16 video "
        "with one or more shots. Report source.shotCount and source.hasCuts. "
        "Describe the first frame, last frame, subject motion, camera motion, "
        "pacing, and a timestamped structure.timeline across the whole video. "
        "Always return structure.shots with chronological per-shot start/end "
        "times, semanticRole, framing, action, and camera. When cuts exist, also "
        "return structure.cutTimeline with each cut time, adjacent shot numbers, "
        "and transition description. Preserve only reusable pose, framing, camera, "
        "pacing, motion-rhythm, edit-rhythm, or endpoint-composition structure. "
        "Set recreationPolicy.fidelity to broad_structure_only and "
        "recreationPolicy.exactChoreographySupported to false. Exact choreography "
        "transfer is unsupported: do not claim or instruct frame-exact motion "
        "copying. Require changes to identity, surface text, and at least one of "
        "wardrobe, setting, styling, or props. Do not return a transcript, source "
        "wording, creator identity, or instructions to copy the source asset "
        "literally. Set sourceTextPolicy.reuseVerbatim to false."
    )


__all__ = [
    "CaptionBankStore",
    "HiggsfieldProductionRequest",
    "build_higgsfield_production_plan",
    "discover_higgsfield_production_capabilities",
    "execute_higgsfield_production",
    "gemini_motion_analysis_instruction",
    "load_or_build_caption_bank_store",
    "caption_hook_payload",
    "quote_higgsfield_production_plan",
    "read_audio_intent",
    "RECREATE_REEL_MODE",
    "RECREATE_REEL_RESOLUTION",
]
