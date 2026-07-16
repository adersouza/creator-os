"""Stable in-process APIs exposed to the Campaign Factory control plane."""

from __future__ import annotations

from .audio_intent import read_audio_intent
from .caption_bank import CaptionBankStore, load_or_build_caption_bank_store
from .reference_video_remix import (
    build_reference_video_remix_plan,
    gemini_motion_analysis_instruction,
)

__all__ = [
    "CaptionBankStore",
    "build_reference_video_remix_plan",
    "gemini_motion_analysis_instruction",
    "load_or_build_caption_bank_store",
    "read_audio_intent",
]
