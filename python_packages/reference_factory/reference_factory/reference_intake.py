from __future__ import annotations

# ruff: noqa: F401 - compatibility module intentionally re-exports the former surface.
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .prompt_records import find_prompt_record as _find_prompt_record
from .prompt_records import read_jsonl_records as _read_jsonl_records
from .prompt_records import record_reference_id as _record_reference_id
from .prompt_records import write_jsonl_records as _write_jsonl_records
from .reference_analysis import (
    _analysis_from_pattern,
    _analysis_value,
    _as_string_list,
    _blueprint_first_frame,
    _blueprint_first_frame_text,
    _blueprint_list,
    _blueprint_motion_beats,
    _blueprint_motion_text,
    _build_image_prompt_json_from_analysis,
    _classify_reference_format,
    _clean_prompt_text,
    _compose_higgsfield_from_image_json,
    _expand_minimal_prompt_analysis,
    _format_card_from_pattern,
    _image_prompt_json,
    _imageat_prompt_payload,
    _json_from_model_text,
    _kling_scenes,
    _normalize_analysis,
    _pattern_card_from_analysis,
    _recreation_blueprint,
    _sanitize_image_prompt_json,
    _sanitize_prompt_value,
    _store_pattern_and_analysis,
    _stringify_prompt_section,
    _style_tags,
    _winning_format_card,
)
from .reference_analysis_queue import (
    _analysis_queue_markdown,
    _job_payload,
    _job_row_to_export,
    _prompt_scoring_rubric_markdown,
    _wait_for_gemini_file,
    analyze_reference_with_gemini_api,
    export_analysis_queue,
    import_gemini_app_response,
    import_reference_analysis,
    queue_reference_analysis,
)
from .reference_grok import (
    _grok_prompt_builder,
    _grok_prompt_compiler_prompt,
    _grok_prompt_compiler_response_format,
    _grok_reference_image,
    _normalize_compiled_prompt_set,
    _validate_compiled_prompt_set,
)
from .reference_grok import _xai_chat_completion as _xai_chat_completion_impl
from .reference_intake_contracts import (
    ANALYSIS_SCHEMA,
    DEFAULT_INTAKE_PROFILE,
    FORMAT_PRIORITY,
    GEMINI_PROMPT_OUTPUT_SCHEMA,
    GEMINI_PROMPT_SCORING_RUBRIC,
    GROK_PROMPT_MODEL_DEFAULT,
    IG_OFM_CLOSENESS_CONTROLS,
    PATTERN_CARD_SCHEMA,
    PROMPT_READY_STATUS,
    XAI_CHAT_COMPLETIONS_URL,
    _canonical_tool,
    _closeness_controls,
    _norm,
)
from .reference_local_analysis import (
    _analyze_reference_frame_pixels,
    _contains_relationship_terms,
    _detect_scene_cuts,
    _energy_from_probe,
    _extract_reference_frames,
    _float,
    _format_from_local_frame_analysis,
    _local_video_analysis,
    _pattern_card_from_local,
    _probe_media,
    _scene_cut_guesses,
    _shot_sequence_for,
    _sidecar_text,
    analyze_reference_local,
    export_video_analyses,
)
from .reference_prompt_generation import (
    _compose_higgsfield_main_prompt,
    _compose_kling_main_prompt,
    _daily_prompt_review_markdown,
    _heuristic_analysis,
    _higgsfield_prompt,
    _kling_prompt,
    _minimal_gemini_analysis_prompt,
    _motion_directives,
    _prompt_for_tool,
    _validate_prompt_contract,
    _video_prompts_markdown,
    export_video_prompts,
    gemini_analysis_prompt,
    generate_video_prompts,
)


def _xai_chat_completion(**kwargs: Any) -> str:
    return _xai_chat_completion_impl(**kwargs)


def analyze_reference_with_grok_api(
    conn: Connection,
    *,
    source_root: Path,
    data_root: Path,
    platform: str = "instagram",
    account_profile: str | None = None,
    intake_profile: str = DEFAULT_INTAKE_PROFILE,
    media_kinds: list[str] | None = None,
    limit: int = 1,
    model: str = GROK_PROMPT_MODEL_DEFAULT,
    api_key: str | None = None,
    prompt_style: str = "imageat",
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    from .reference_grok import analyze_reference_with_grok_api as implementation

    return implementation(
        conn,
        source_root=source_root,
        data_root=data_root,
        platform=platform,
        account_profile=account_profile,
        intake_profile=intake_profile,
        media_kinds=media_kinds,
        limit=limit,
        model=model,
        api_key=api_key,
        prompt_style=prompt_style,
        ffmpeg=ffmpeg,
        _chat_completion=_xai_chat_completion,
    )


def compile_prompts_with_grok_api(
    *,
    data_root: Path,
    reference_id: str,
    reference_media: Path,
    model: str = GROK_PROMPT_MODEL_DEFAULT,
    api_key: str | None = None,
    ffmpeg: str = "ffmpeg",
    instructions: str | None = None,
) -> dict[str, object]:
    from .reference_grok import compile_prompts_with_grok_api as implementation

    return implementation(
        data_root=data_root,
        reference_id=reference_id,
        reference_media=reference_media,
        model=model,
        api_key=api_key,
        ffmpeg=ffmpeg,
        instructions=instructions,
        _chat_completion=_xai_chat_completion,
    )
