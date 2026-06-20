from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reference_factory.db import connect
from reference_factory.prompt_records import (
    find_prompt_record,
    read_jsonl_records,
    record_reference_id,
    write_jsonl_records,
)
from reference_factory.public_metrics import _prompt_card_from_post
from reference_factory.reference_intake import (
    _build_image_prompt_json_from_analysis,
    _canonical_tool,
    _closeness_controls,
    _compose_higgsfield_from_image_json,
    _compose_higgsfield_main_prompt,
    _compose_kling_main_prompt,
    _find_prompt_record,
    _json_from_model_text,
    _motion_directives,
    _normalize_analysis,
    _normalize_compiled_prompt_set,
    _read_jsonl_records,
    _record_reference_id,
    _validate_compiled_prompt_set,
    _write_jsonl_records,
    export_analysis_queue,
    export_video_prompts,
    generate_video_prompts,
    import_reference_analysis,
    queue_reference_analysis,
)


def make_conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "reference_factory.sqlite")


def write_reference_file(source_root: Path, account: str = "creator_a", name: str = "mirror_clip.mp4") -> Path:
    account_dir = source_root / account
    account_dir.mkdir(parents=True)
    path = account_dir / name
    path.write_bytes(b"fixture bytes")
    return path


def minimal_prompt_analysis(**overrides: object) -> dict[str, object]:
    analysis: dict[str, object] = {
        "schema": "reference_factory.video_recreation_blueprint.v1",
        "summary": "Mirror selfie outfit-check format with quick native motion.",
        "contentFormat": "mirror_selfie",
        "higgsfield_soul_image_prompt": "Use the Soul ID model in a mirror selfie first frame.",
        "higgsfield_negative_prompt": "watermark, platform UI",
        "kling_3_video_prompt": "Animate a subtle hip shift with tiny phone sway.",
        "kling_negative_prompt": "zoom, face reveal",
        "motion_notes": "subtle hip shift, relaxed breathing",
        "camera_notes": "vertical phone mirror angle",
        "style_notes": "soft bedroom light and native Reel pacing",
        "copy_risk_notes": "do not copy face, username, or exact room decor",
        "what_to_change": "new identity, new outfit color, new decor",
        "recreation_blueprint": {
            "format_type": "mirror_selfie",
            "first_frame": {
                "subject_scale": "full body",
                "crop": "vertical 9:16 mirror crop",
                "body_angle": "three-quarter side profile",
                "pose": "phone covering face",
                "phone_or_hand_position": "phone at face height",
                "facial_visibility": "hidden by phone",
                "outfit_silhouette": "fitted mini dress",
                "room_or_location_layout": "bright bedroom with black mirror",
                "lighting": "soft daylight",
                "camera_height": "chest height",
                "camera_distance": "one arm length",
                "lens_feel": "iPhone wide lens",
            },
            "motion_beats": [
                {
                    "time_range": "0-2s",
                    "subject_motion": "small hip shift",
                    "camera_motion": "tiny handheld sway",
                    "pose_change": "micro angle adjustment",
                    "notes": "keep pose continuity",
                }
            ],
            "native_style_constraints": ["phone-native", "imperfect natural framing"],
            "copy_risk_notes": ["no copied identity"],
            "required_changes": ["replace identity", "change outfit color", "remove watermark"],
        },
        "audioVibe": {"energy": "medium", "bpmFeel": "sped-up pop", "moodTags": ["outfit", "mirror"]},
    }
    analysis.update(overrides)
    return analysis


def test_p1_caption_archetype_regression_does_not_require_hidden_key() -> None:
    card = _prompt_card_from_post(
        {
            "id": "post_choice",
            "rank": 1,
            "ownerUsername": "creator",
            "url": "https://example.test/p/post_choice",
            "videoPlayCount": 1200,
            "videoViewCount": 1300,
            "likesCount": 100,
            "commentsCount": 8,
            "matchType": "external_only",
            "referenceId": "ref_choice",
            "caption": "Pick one: left or right?",
        }
    )

    assert card["learnedPattern"]["captionArchetype"] == "choice_bait"
    assert card["learnedPattern"]["structureNotes"]


def test_import_reference_analysis_normalizes_pattern_card_and_exports_prompts(tmp_path: Path) -> None:
    source_root = tmp_path / "downloads"
    write_reference_file(source_root)
    conn = make_conn(tmp_path)
    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=tmp_path / "data",
        platform="Instagram",
        media_kinds=["video", "bogus"],
        limit=1,
    )
    import_path = tmp_path / "analysis.json"
    import_path.write_text(
        json.dumps(
            {
                "items": [
                    "not an object",
                    {"jobId": "missing_reference"},
                    {
                        "analysisJobId": queued["jobs"][0]["id"],
                        "referenceId": queued["jobs"][0]["referenceId"],
                        "analysis": minimal_prompt_analysis(),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    imported = import_reference_analysis(conn, import_path)
    generated = generate_video_prompts(
        conn,
        data_root=tmp_path / "data",
        target_tools=["higgsfield", "kling_3"],
        model_profile="Stacey",
        include_pending=False,
        creative_plan_id="plan_123",
    )
    exported = export_video_prompts(conn, data_root=tmp_path / "data", creative_plan_id="plan_123")

    assert imported["imported"] == 1
    assert [error["error"] for error in imported["errors"]] == [
        "item must be an object",
        "unknown analysis job: missing_reference",
    ]
    assert generated["count"] == 2
    assert generated["targetTools"] == ["higgsfield_soul_image", "kling_3_video"]
    assert generated["prompts"][0]["prompt"]["creativePlanId"] == "plan_123"
    assert Path(exported["dailyHiggsfieldImageJsonlPath"]).read_text(encoding="utf-8").strip()
    assert Path(exported["dailyKlingVideoJsonlPath"]).read_text(encoding="utf-8").strip()
    card = conn.execute("SELECT pattern_json FROM viral_pattern_cards").fetchone()
    assert json.loads(card["pattern_json"])["schema"] == "reference_factory.pattern_card.v1"


def test_import_reference_analysis_rejects_invalid_payload_shape(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"items": {"not": "a list"}}), encoding="utf-8")

    with pytest.raises(ValueError, match="analysis input must be a list"):
        import_reference_analysis(make_conn(tmp_path), path)


def test_normalize_minimal_analysis_builds_safe_image_and_motion_prompts() -> None:
    analysis = _normalize_analysis({"analysis": minimal_prompt_analysis()})
    image_card = _build_image_prompt_json_from_analysis(analysis, model_profile="Stacey")
    image_prompt = _compose_higgsfield_from_image_json(
        {
            "subject": "Adult Stacey Soul ID model mirror pose",
            "composition": {"shot_type": "mirror selfie"},
            "clothing": {"item": "dress"},
            "constraints": {"avoid": ["tattoos", "watermark"]},
            "prompt": "Adult Stacey in a mirror selfie",
        },
        model_profile="Stacey",
        fallback_prompt="fallback",
    )
    prose_image_prompt = _compose_higgsfield_from_image_json(
        {"subject": "Stacey", "prompt": ""},
        model_profile="Stacey",
        fallback_prompt="fallback mirror prompt",
    )
    kling_prompt = _compose_kling_main_prompt(
        analysis_prompt="",
        analysis=analysis,
        model_profile="Stacey",
        fallback_prompt="fallback motion",
    )
    directives = _motion_directives(analysis)

    assert analysis["schema"] == "reference_factory.video_analysis.v1"
    assert analysis["winningFormatCard"]["visualFormat"] == "mirror_selfie"
    assert image_card["constraints"]["must_keep"]
    assert "Adult Stacey" not in image_prompt
    assert "tattoos" not in image_prompt
    assert "fallback mirror prompt" in prose_image_prompt
    assert "phone/hand placement: phone at face height" in directives["must_preserve"]
    assert "fallback motion" in kling_prompt
    assert directives["subject_motion"] == "small hip shift"


def test_json_prompt_compiler_helpers_parse_validate_and_roundtrip(tmp_path: Path) -> None:
    parsed = _json_from_model_text(
        "Here is the JSON:\n```json\n{\"ok\": true, \"items\": [1]}\n```"
    )
    records_path = tmp_path / "prompts" / "records.jsonl"
    records = [{"sourceReferenceId": "ref_a", "prompt": "one"}, {"referenceId": "ref_b", "prompt": "two"}]
    compiled = _normalize_compiled_prompt_set(
        {
            "soul_id_2x3_prompt": "Create one high-quality 2x3 grid featuring six outfit variations.",
            "single_panel_prompt": "Single original panel with preserved pose geometry.",
            "kling_video_prompt": "Animate the generated first frame with subtle phone-native movement.",
            "kling_negative_prompt": "watermark",
            "structured_breakdown": {
                "pose_lock": "mirror selfie pose",
                "body_emphasis": "outfit silhouette",
                "outfit_variations": ["a", "b", "c", "d", "e", "f"],
                "motion_directives": "tiny phone sway",
                    "key_constraints": ["new identity", "clean background", "original decor"],
            },
            "confidence_score": 82,
        }
    )

    _write_jsonl_records(records_path, records)
    loaded = _read_jsonl_records(records_path)
    _validate_compiled_prompt_set(compiled)

    assert parsed == {"ok": True, "items": [1]}
    assert loaded == records
    assert _record_reference_id(loaded[1]) == "ref_b"
    assert _find_prompt_record(loaded, "ref_a") == records[0]
    assert "exactly three columns and two rows" in compiled["soul_id_2x3_prompt"]
    assert _read_jsonl_records(tmp_path / "missing.jsonl") == []


def test_prompt_record_helpers_are_stable_outside_reference_intake(tmp_path: Path) -> None:
    path = tmp_path / "records" / "prompts.jsonl"
    records = [{"sourceReferenceId": "ref_a", "prompt": "one"}, {"referenceId": "ref_b", "prompt": "two"}]

    write_jsonl_records(path, records)
    loaded = read_jsonl_records(path)

    assert loaded == records
    assert read_jsonl_records(tmp_path / "missing.jsonl") == []
    assert record_reference_id(loaded[0]) == "ref_a"
    assert record_reference_id(loaded[1]) == "ref_b"
    assert find_prompt_record(loaded, "ref_b") == records[1]
    assert find_prompt_record(loaded, "missing") is None


def test_compiled_prompt_validation_blocks_unsafe_or_incomplete_output() -> None:
    with pytest.raises(RuntimeError, match="missing required prompt fields"):
        _validate_compiled_prompt_set({})

    with pytest.raises(RuntimeError, match="forbidden Soul prompt terms"):
        _validate_compiled_prompt_set(
            {
                "soul_id_2x3_prompt": "Prompt that mentions a username.",
                "single_panel_prompt": "Single original panel.",
                "kling_video_prompt": "Animate subtly.",
                "kling_negative_prompt": "watermark",
                "structured_breakdown": {
                    "pose_lock": "pose",
                    "body_emphasis": "fit",
                    "outfit_variations": ["a", "b", "c", "d", "e", "f"],
                    "motion_directives": "motion",
                    "key_constraints": ["one", "two", "three"],
                },
                "confidence_score": 80,
            }
        )


def test_queue_export_and_tool_controls_are_stable(tmp_path: Path) -> None:
    source_root = tmp_path / "references"
    write_reference_file(source_root, name="clip.jpg")
    conn = make_conn(tmp_path)
    queued = queue_reference_analysis(
        conn,
        source_root,
        data_root=tmp_path / "data",
        intake_profile="general",
        media_kinds=["nonsense"],
        prompt_style="minimal",
    )
    export = export_analysis_queue(conn, data_root=tmp_path / "data", provider_target="gemini", limit=10)

    assert queued["mediaKinds"] == ["video", "image"]
    assert queued["closenessControls"] == {
        "format_closeness": "medium",
        "identity_copy_risk": "blocked",
        "scene_variation_required": True,
        "spicy_ofm_coded": False,
    }
    assert _closeness_controls("ig_ofm")["format_closeness"] == "high"
    assert _canonical_tool("soul_id") == "higgsfield_soul_image"
    assert _canonical_tool("kling") == "kling_3_video"
    assert Path(export["markdownPath"]).read_text(encoding="utf-8").startswith("# Reference Analysis Queue")
