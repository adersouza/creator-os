from __future__ import annotations

import sqlite3
import subprocess
import json
import base64
import gzip
from pathlib import Path

from reference_factory.audio import analyze_audio_patterns, audio_catalog_health, audio_resolution_shortlist, competitor_audio_leaderboard, export_audio_catalog, extract_audio_signal, import_audio_csv, import_audio_snapshot_csv, import_example_reel_audio, list_audio_catalog, list_audio_trend_snapshots, recommend_audio, resolve_audio_record, review_audio_catalog, scrape_instagram_audio, upsert_audio_record, upsert_audio_trend_snapshot
from reference_factory.audio_refresh import leaderboard_to_catalog_rows
from reference_factory.contact_sheet import generate_contact_sheet
from reference_factory.caption_adaptation import adapt_caption_library, adapt_caption_text
from reference_factory.db import connect
from reference_factory.higgsfield_runner import generate_with_higgsfield, load_prompt_pairs
from reference_factory.identity import text_hash
from reference_factory.learning import build_learning_system, learning_summary
from reference_factory.media import ffprobe_video, parse_fps, probe_videos, sample_frames, thumbnail_batch
from reference_factory.ocr import normalize_text, ocr_cleanup, parse_tesseract_tsv, upsert_caption_pattern
from reference_factory.patterns import analyze_patterns, apply_pattern_labels, export_patterns, pattern_summary
from reference_factory.provider_doctor import provider_doctor
from reference_factory.proof_verifier import verify_proof_bundle
from reference_factory.outcomes import import_prompt_outcomes
from reference_factory.public_metrics import export_learning_set, generate_prompt_cards, import_apify_metrics, top_public_posts
from reference_factory.reference_intake import analyze_reference_local, compile_prompts_with_grok_api, export_video_analyses, generate_video_prompts, gemini_analysis_prompt, import_gemini_app_response, import_reference_analysis, queue_reference_analysis, _grok_prompt_builder, _json_from_model_text
from reference_factory.review import (
    export_gold,
    label_reference,
    reference_query,
    review_batch,
    review_stats,
    set_reference_label,
)
from reference_factory.scan import classify_file, scan_source
from reference_factory.server import create_app
from reference_factory.tiktok_archive import import_tiktok_archive


GOOD_IMAGE_PROMPT_JSON = {
    "promptMode": "structured_json",
    "prompt_schema_version": "imageat_higgsfield.v1",
    "subject": "Stacey posing for a mirror selfie",
    "prompt": "Stacey mirror selfie first frame",
    "composition": {"shot_type": "full-body mirror selfie", "pose": "side profile phone covering face"},
    "clothing": {"item": "fitted mini dress", "fit": "bodycon"},
    "body": {"pose_details": "side profile outfit-check stance"},
    "skin": {"texture": "realistic phone-photo detail"},
    "expression_mood": {"vibe": "confident flirty outfit-check energy"},
    "environment": {"setting": "white bedroom", "details": ["black mirror frame", "bed"]},
    "lighting_and_camera": {"lighting": "soft natural daylight", "camera_feel": "iPhone mirror selfie"},
    "constraints": {
        "must_keep": ["mirror selfie", "phone covering face", "white bedroom"],
        "avoid": ["watermark", "platform UI", "bad anatomy"],
    },
    "negative_prompt": "watermark, platform UI, bad anatomy",
}


def make_conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "reference_factory.sqlite")


def create_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=540x960:d=1.2:r=24",
            "-an",
            str(path),
        ],
        check=True,
    )


def write_higgsfield_prompt_pair(data_root: Path, reference_id: str = "ref_001") -> None:
    prompt_dir = data_root / "reference_intake"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    image = {
        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
        "tool": "higgsfield_soul_image",
        "status": "prompt_ready",
        "sourceReferenceId": reference_id,
        "sourcePatternId": "pattern_001",
        "modelProfile": "Stacey",
        "mainPrompt": json.dumps({key: value for key, value in GOOD_IMAGE_PROMPT_JSON.items() if key != "promptMode"}),
        "negativePrompt": "watermark",
        "closenessControls": {"identity_copy_risk": "blocked"},
        "formatCard": {"visualFormat": "mirror_selfie"},
        "imagePromptJson": GOOD_IMAGE_PROMPT_JSON,
    }
    video = {
        "schema": "reference_factory.kling_3_video_prompt.v1",
        "tool": "kling_3_video",
        "status": "prompt_ready",
        "sourceReferenceId": reference_id,
        "sourcePatternId": "pattern_001",
        "modelProfile": "Stacey",
        "firstFrameInstruction": "Use generated Higgsfield image.",
        "mainPrompt": "Kling 3.0 image-to-video prompt. Use the generated image as first frame.",
        "negativePrompt": "platform UI",
        "motion_directives": {
            "duration_seconds": 5,
            "camera_motion": "tiny handheld sway",
            "subject_motion": "subtle hip shift",
            "must_preserve": ["same crop", "same pose", "same room"],
            "avoid": ["zoom", "face reveal", "outfit change"],
            "fallback_provider": "grok_imagine",
        },
        "closenessControls": {"identity_copy_risk": "blocked"},
        "durationSeconds": 5,
        "formatCard": {"visualFormat": "mirror_selfie"},
    }
    (prompt_dir / "daily_higgsfield_image_prompts.jsonl").write_text(json.dumps(image) + "\n", encoding="utf-8")
    (prompt_dir / "daily_kling_video_prompts.jsonl").write_text(json.dumps(video) + "\n", encoding="utf-8")


def write_higgsfield_prompt_pairs(data_root: Path, reference_ids: list[str]) -> None:
    prompt_dir = data_root / "reference_intake"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    image_rows = []
    video_rows = []
    for reference_id in reference_ids:
        image = {
            "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
            "tool": "higgsfield_soul_image",
            "status": "prompt_ready",
            "sourceReferenceId": reference_id,
            "sourcePatternId": f"pattern_{reference_id}",
            "modelProfile": "Stacey",
            "mainPrompt": json.dumps({key: value for key, value in GOOD_IMAGE_PROMPT_JSON.items() if key != "promptMode"}),
            "negativePrompt": "watermark",
            "imagePromptJson": GOOD_IMAGE_PROMPT_JSON,
        }
        video = {
            "schema": "reference_factory.kling_3_video_prompt.v1",
            "tool": "kling_3_video",
            "status": "prompt_ready",
            "sourceReferenceId": reference_id,
            "sourcePatternId": f"pattern_{reference_id}",
            "modelProfile": "Stacey",
            "mainPrompt": "Kling 3.0 image-to-video prompt. Use the generated image as first frame.",
            "negativePrompt": "platform UI",
            "motion_directives": {
                "duration_seconds": 5,
                "camera_motion": "tiny handheld sway",
                "subject_motion": "subtle hip shift",
                "must_preserve": ["same crop", "same pose", "same room"],
                "avoid": ["zoom", "face reveal", "outfit change"],
                "fallback_provider": "grok_imagine",
            },
        }
        image_rows.append(json.dumps(image))
        video_rows.append(json.dumps(video))
    (prompt_dir / "daily_higgsfield_image_prompts.jsonl").write_text("\n".join(image_rows) + "\n", encoding="utf-8")
    (prompt_dir / "daily_kling_video_prompts.jsonl").write_text("\n".join(video_rows) + "\n", encoding="utf-8")


def create_accepted_proof_bundle(root: Path) -> Path:
    bundle = root / "ACCEPTED_PROOF_BUNDLE"
    assets = bundle / "assets"
    assets.mkdir(parents=True)
    for relative in [
        "assets/01_reference_frames.jpg",
        "assets/02_soul_base_still.png",
        "assets/03_best_2x3_image.png",
        "assets/04_best_2x3_grid_video.mp4",
        "assets/05_best_2x3_vertical_sequence.mp4",
        "assets/06_kling_single_outfit_motion.mp4",
        "assets/07_campaign_passthrough.mp4",
        "assets/08_motion_sequence_frames.jpg",
        "assets/09_campaign_passthrough_frames.jpg",
        "final_visual_audit_sheet.jpg",
        "index.html",
    ]:
        (bundle / relative).write_bytes(b"proof")
    (bundle / "generated_asset_lineage.json").write_text(json.dumps({
        "quality": {"promptScore": {"status": "pass", "warnings": []}},
    }), encoding="utf-8")
    (bundle / "proof_completion_report.json").write_text(json.dumps({
        "acceptedAssets": {"best2x3Image": "assets/03_best_2x3_image.png"},
    }), encoding="utf-8")
    (bundle / "goal_completion_audit.json").write_text(json.dumps({
        "status": "ready_for_user_visual_acceptance_with_final_visual_sheet",
    }), encoding="utf-8")
    return bundle


def test_scan_indexes_account_structure_and_marks_other(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    (account / "a.mp4").write_bytes(b"not a real video")
    (account / "b.jpg").write_bytes(b"jpg")
    (account / "notes.txt").write_text("x")
    conn = make_conn(tmp_path)

    result = scan_source(conn, source)

    assert result["totalFiles"] == 3
    assert result["byKind"]["video"] == 1
    assert result["byKind"]["image"] == 1
    assert result["byKind"]["other"] == 1
    row = conn.execute("SELECT account FROM source_files WHERE file_name = 'a.mp4'").fetchone()
    assert row["account"] == "account_a"
    assert classify_file(account / "notes.txt") == "other"


def test_ffprobe_handles_valid_and_broken_video(tmp_path: Path) -> None:
    good = tmp_path / "good.mp4"
    broken = tmp_path / "broken.mp4"
    create_video(good)
    broken.write_bytes(b"bad")

    good_probe = ffprobe_video(good)
    broken_probe = ffprobe_video(broken)

    assert good_probe["valid"] is True
    assert good_probe["width"] == 540
    assert good_probe["height"] == 960
    assert broken_probe["valid"] is False
    assert parse_fps("30000/1001") == 29.97


def test_probe_and_sample_frames_create_records(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)

    probe_result = probe_videos(conn)
    sample_result = sample_frames(conn, tmp_path / "data")

    assert probe_result["valid"] == 1
    assert sample_result["videos"] == 1
    assert sample_result["frames"] >= 3
    assert conn.execute("SELECT COUNT(*) AS c FROM frame_samples").fetchone()["c"] >= 3


def test_ocr_parser_and_caption_hash_are_stable(tmp_path: Path) -> None:
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t10\t20\t90\t30\t88\tHELLO",
            "5\t1\t1\t1\t1\t2\t110\t20\t80\t30\t91\tTWIN",
        ]
    )
    boxes = parse_tesseract_tsv(tsv, tmp_path / "frame.jpg")

    assert [box["ocrText"] for box in boxes] == ["HELLO", "TWIN"]
    assert normalize_text("  hello\n  twin ") == "hello twin"
    assert text_hash("Hello Twin") == text_hash("hello   twin")


def test_caption_pattern_and_label_export(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)
    ref = conn.execute("SELECT reference_id FROM source_files LIMIT 1").fetchone()["reference_id"]

    upsert_caption_pattern(
        conn,
        ref,
        "ocr_1",
        "just cracked you in my head",
        [{"ocrText": "just cracked", "confidence": 90, "box": {"x": 10, "y": 200, "w": 100, "h": 40}}],
        90,
    )
    conn.commit()
    label = label_reference(conn, ref, "gold", ["caption_style"], "keeper")
    label_reference(conn, ref, "maybe", ["visual_style"], "second thought")
    exported = export_gold(conn, tmp_path / "data")

    assert label["label"] == "gold"
    assert conn.execute("SELECT label FROM review_labels WHERE reference_id = ?", (ref,)).fetchone()["label"] == "maybe"
    assert conn.execute("SELECT COUNT(*) AS c FROM caption_patterns").fetchone()["c"] == 1
    assert exported["count"] == 0
    assert Path(exported["manifestPath"]).exists()


def test_caption_adaptation_rewrites_identity_specific_terms() -> None:
    adapted, rules = adapt_caption_text("Why Indian girls always win?")

    assert adapted == "Why our girls always win?"
    assert rules


def test_caption_adaptation_preserves_hashtags_and_self_phrases() -> None:
    adapted, rules = adapt_caption_text("We're Slavic girls #slavicgirls #redhead")

    assert adapted == "We're our kind of girls #slavicgirls #redhead"
    assert any(rule.startswith("self_plural:") for rule in rules)


def test_caption_adaptation_cleans_described_identity_phrases() -> None:
    plural, plural_rules = adapt_caption_text("not interested in skinny brunette girls")
    singular, singular_rules = adapt_caption_text('would you give a 5"4 brunette girl a chance?')

    assert plural == "not interested in our girls"
    assert singular == "would you give one of our girls a chance?"
    assert any(rule.startswith("descriptor_plural:") for rule in plural_rules)
    assert any(rule.startswith("descriptor_singular:") for rule in singular_rules)


def test_caption_adaptation_exports_profile_outputs(tmp_path: Path) -> None:
    captions = tmp_path / "captions"
    captions.mkdir()
    (captions / "caption_library_unique.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "captionHash": "a",
                        "text": "Why ginger girls?",
                        "sourceType": "public_caption",
                        "reviewLabel": "gold",
                    }
                ),
                json.dumps(
                    {
                        "captionHash": "b",
                        "text": "normal caption",
                        "sourceType": "ocr_overlay",
                        "reviewLabel": "maybe",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = adapt_caption_library(data_root=tmp_path)

    assert result["total"] == 2
    assert result["changed"] == 1
    changed = Path(result["outputs"]["changedTxt"]).read_text(encoding="utf-8")
    assert "Why our girls?" in changed
    assert Path(result["outputs"]["goldTxt"]).exists()


def test_contact_sheet_generates_html(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)
    probe_videos(conn)
    sample_frames(conn, tmp_path / "data")

    result = generate_contact_sheet(conn, "random", count=1, data_root=tmp_path / "data")

    assert result["count"] == 1
    html_path = Path(result["htmlPath"])
    assert html_path.exists()
    assert "Reference Factory Contact Sheet" in html_path.read_text()


def test_reference_intake_queues_gemini_analysis_and_exports_prompts(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    account = source / "creator_a"
    account.mkdir(parents=True)
    create_video(account / "winning.mp4")
    conn = make_conn(tmp_path)

    queued = queue_reference_analysis(
        conn,
        source,
        data_root=tmp_path / "data",
        platform="tiktok",
        provider_target="gemini",
        account_profile="model_a",
    )

    assert queued["queued"] == 1
    assert queued["intakeProfile"] == "ig_ofm"
    assert queued["closenessControls"]["format_closeness"] == "high"
    assert queued["jobs"][0]["status"] == "needs_analysis"
    assert "winningFormatCard" in queued["jobs"][0]["promptText"]
    assert "Output strict JSON only" in queued["jobs"][0]["promptText"]
    assert Path(queued["export"]["jsonPath"]).exists()

    generated = generate_video_prompts(
        conn,
        data_root=tmp_path / "data",
        target_tools=["higgsfield_soul", "kling_3"],
        model_profile="model_a",
        limit=10,
        creative_plan_id="cplan_1",
    )

    assert generated["count"] == 2
    assert {item["targetTool"] for item in generated["prompts"]} == {"higgsfield_soul_image", "kling_3_video"}
    assert {item["status"] for item in generated["prompts"]} == {"prompt_ready"}
    assert "Do not copy" in generated["prompts"][0]["prompt"]["soulIdInstruction"]
    assert Path(generated["export"]["markdownPath"]).exists()
    assert Path(generated["export"]["dailyHiggsfieldImageJsonlPath"]).exists()
    assert Path(generated["export"]["dailyKlingVideoJsonlPath"]).exists()
    assert Path(generated["export"]["dailyPromptReviewPath"]).exists()
    higgsfield_line = Path(generated["export"]["dailyHiggsfieldImageJsonlPath"]).read_text(encoding="utf-8").splitlines()[0]
    kling_line = Path(generated["export"]["dailyKlingVideoJsonlPath"]).read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(higgsfield_line)["schema"] == "reference_factory.higgsfield_soul_image_prompt.v1"
    assert json.loads(kling_line)["schema"] == "reference_factory.kling_3_video_prompt.v1"
    assert json.loads(higgsfield_line)["creativePlanId"] == "cplan_1"
    assert "prompt" not in json.loads(higgsfield_line)


def test_reference_intake_imports_analysis_before_prompt_generation(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    account = source / "creator_b"
    account.mkdir(parents=True)
    create_video(account / "mirror.mp4")
    conn = make_conn(tmp_path)
    queued = queue_reference_analysis(conn, source, data_root=tmp_path / "data", platform="instagram")
    job = queued["jobs"][0]
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "analysisJobId": job["id"],
                        "schema": "reference_factory.video_analysis.v1",
                        "referenceId": job["referenceId"],
                        "summary": "Mirror selfie with confident styling and relationship text overlay.",
                        "platformStyle": "instagram",
                        "contentFormat": "mirror",
                        "hookType": "relationship",
                        "captionStyle": "short white text with dark stroke",
                        "closenessControls": {
                            "format_closeness": "high",
                            "identity_copy_risk": "blocked",
                            "scene_variation_required": True,
                            "spicy_ofm_coded": True,
                        },
                        "winningFormatCard": {
                            "visualFormat": "mirror_selfie",
                            "formatPriorityRank": 1,
                            "poseAction": "close mirror pose",
                            "camera": {"framing": "vertical medium close", "angle": "mirror selfie", "movement": "tiny handheld drift"},
                            "lighting": "warm lamp light",
                            "setting": "bedroom mirror",
                            "styling": "black fitted top",
                            "textOverlay": {"copy": "relationship hook", "placement": "upper third", "fontStyle": "white stroke"},
                            "pacing": {"energy": "medium", "cutRhythm": "single shot", "durationFeel": "short"},
                            "audioVibe": {"energy": "medium", "bpmFeel": "sped up pop", "moodTags": ["glam", "relationship"]},
                            "hookMechanics": ["aspirational mirror framing"],
                            "copyRiskNotes": ["change the person and room"],
                            "transformationInstructions": ["change outfit and room"],
                        },
                        "shotSequence": ["close mirror pose", "small hair movement"],
                        "camera": {"framing": "vertical medium close", "angle": "mirror selfie", "movement": "tiny handheld drift"},
                        "subject": {"action": "poses near mirror", "pose": "one hand on hip", "expression": "confident smirk", "wardrobe": "black fitted top"},
                        "setting": {"location": "bedroom mirror", "lighting": "warm lamp light", "background": "clean bedroom"},
                        "visualPacing": {"energy": "medium", "cutRhythm": "single shot", "motion": "subtle"},
                        "audioVibe": {"energy": "medium", "bpmFeel": "sped up pop", "moodTags": ["glam", "relationship"]},
                        "textOverlay": {"placement": "upper third", "fontStyle": "white stroke", "safeZoneNotes": "avoid eyes"},
                        "viralMechanics": ["aspirational mirror framing"],
                        "reuseRisk": "medium",
                        "transformationNotes": ["change outfit and room"],
                        "qualityWarnings": ["avoid copying face"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    imported = import_reference_analysis(conn, analysis_path)
    generated = generate_video_prompts(
        conn,
        data_root=tmp_path / "data",
        target_tools=["kling_3"],
        model_profile="model_b",
        include_pending=False,
    )

    assert imported["imported"] == 1
    assert generated["count"] == 1
    prompt = generated["prompts"][0]["prompt"]
    assert prompt["schema"] == "reference_factory.kling_3_video_prompt.v1"
    assert prompt["sourcePatternId"]
    assert prompt["formatCard"]["visualFormat"] == "mirror_selfie"
    assert prompt["closenessControls"]["identity_copy_risk"] == "blocked"
    assert prompt["firstFrameInstruction"].startswith("Use the generated Higgsfield")
    assert prompt["camera"]["angle"] == "mirror selfie"
    assert "bedroom mirror" in prompt["mainPrompt"]


def test_reference_intake_minimal_gemini_prompt_and_direct_prompt_import(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    account = source / "creator_minimal"
    account.mkdir(parents=True)
    create_video(account / "selfie.mp4")
    conn = make_conn(tmp_path)

    queued = queue_reference_analysis(
        conn,
        source,
        data_root=tmp_path / "data",
        platform="instagram",
        provider_target="gemini_manual",
        prompt_style="minimal",
    )
    prompt_text = queued["jobs"][0]["promptText"]
    assert queued["promptStyle"] == "minimal"
    assert "recreation blueprint" in prompt_text
    assert "pose geometry" in prompt_text
    assert "Prioritize formats" not in prompt_text
    assert "higgsfield_soul_image_prompt" in prompt_text
    assert "Example `image_prompt_json` style to imitate" in prompt_text
    assert '"promptMode": "structured_json"' in prompt_text
    assert "adult my Soul ID model" not in prompt_text
    assert Path(queued["export"]["outputSchemaPath"]).exists()
    assert Path(queued["export"]["scoringRubricMarkdownPath"]).exists()

    job = queued["jobs"][0]
    analysis_path = tmp_path / "minimal_analysis.json"
    analysis_path.write_text(json.dumps({
        "items": [
            {
                "analysisJobId": job["id"],
                "schema": "reference_factory.video_analysis.v1",
                "referenceId": job["referenceId"],
                "summary": "A casual phone-native selfie clip with subtle handheld movement.",
                "contentFormat": "selfie_video",
                "recreation_blueprint": {
                    "format_type": "selfie_video",
                    "first_frame": {
                        "subject_scale": "upper torso fills most of frame",
                        "crop": "tight crop from chest to top of head",
                        "body_angle": "slight three-quarter angle",
                        "pose": "shoulders angled, relaxed face close to phone",
                        "phone_or_hand_position": "phone held just below eye level",
                        "facial_visibility": "face visible",
                        "outfit_silhouette": "fitted casual top",
                        "room_or_location_layout": "lived-in bedroom behind subject",
                        "lighting": "soft warm bedside lamp",
                        "camera_height": "eye level",
                        "camera_distance": "close arm-length selfie",
                        "lens_feel": "front phone camera",
                    },
                    "motion_beats": [
                        {
                            "time_range": "0.0-1.5s",
                            "subject_motion": "tiny shoulder shift and expression change",
                            "camera_motion": "subtle handheld sway",
                            "pose_change": "leans slightly closer",
                            "notes": "keep amateur phone realism",
                        }
                    ],
                    "native_style_constraints": ["do not make cinematic", "imperfect phone-shot framing"],
                    "copy_risk_notes": ["do not copy the original face"],
                    "required_changes": ["change wardrobe color and room details"],
                },
                "higgsfield_soul_image_prompt": "Use my Soul ID model in a casual bedroom selfie first frame, soft lamp light, relaxed expression.",
                "higgsfield_negative_prompt": "watermark, copied face, username",
                "kling_3_video_prompt": "Use the generated Soul ID image as first frame; subtle handheld selfie sway, tiny expression change, 5 seconds, vertical 9:16.",
                "kling_negative_prompt": "watermark, platform UI, copied person",
                "motion_notes": "subtle handheld sway and facial expression shift",
                "camera_notes": "close vertical phone selfie",
                "style_notes": "casual bedroom lighting",
                "copy_risk_notes": "change face, room, and text",
                "what_to_change": "new wardrobe and room details",
            }
        ]
    }), encoding="utf-8")

    imported = import_reference_analysis(conn, analysis_path)
    generated = generate_video_prompts(conn, data_root=tmp_path / "data", target_tools=["higgsfield_soul", "kling_3"], include_pending=False)

    assert imported["imported"] == 1
    prompts = {item["targetTool"]: item["prompt"] for item in generated["prompts"]}
    image_main = prompts["higgsfield_soul_image"]["mainPrompt"]
    image_json = json.loads(image_main)
    assert image_json["prompt_schema_version"] == "imageat_higgsfield.v1"
    assert image_json["prompt"] == "Use my Soul ID model in a casual bedroom selfie first frame, soft lamp light, relaxed expression."
    assert image_json["composition"]["framing"] == "tight crop from chest to top of head"
    assert image_json["must_keep"][0] == "subject scale: upper torso fills most of frame"
    assert image_json["constraints"]["avoid"] == [
        "visible copied identity",
        "username",
        "watermark",
        "platform UI",
        "explicit nudity",
        "professional studio lighting unless source has it",
        "cluttered background unless source has it",
    ]
    assert "hair identity" not in prompts["higgsfield_soul_image"]["mainPrompt"]
    assert "tattoos" not in prompts["higgsfield_soul_image"]["mainPrompt"].lower()
    assert prompts["higgsfield_soul_image"]["imagePromptJson"]["composition"]["framing"] == "tight crop from chest to top of head"
    assert prompts["higgsfield_soul_image"]["recreationBlueprint"]["first_frame"]["camera_distance"] == "close arm-length selfie"
    assert prompts["higgsfield_soul_image"]["negativePrompt"] == "watermark, copied face, username"
    assert prompts["kling_3_video"]["mainPrompt"].startswith("Kling 3.0 image-to-video prompt")
    assert "Use the generated image as the first/reference frame" in prompts["kling_3_video"]["mainPrompt"]
    assert "Use the generated Soul ID image" in prompts["kling_3_video"]["mainPrompt"]
    assert prompts["kling_3_video"]["motion_directives"]["subject_motion"].startswith("Use the generated Soul ID image")
    assert "0.0-1.5s: tiny shoulder shift" not in prompts["kling_3_video"]["mainPrompt"]
    assert prompts["kling_3_video"]["scenes"][0]["timeRange"] == "0.0-1.5s"
    assert prompts["kling_3_video"]["motion_directives"]["fallback_provider"] == "grok_imagine"
    assert "same first-frame crop" in prompts["kling_3_video"]["motion_directives"]["must_preserve"]
    assert prompts["kling_3_video"]["negativePrompt"] == "watermark, platform UI, copied person"


def test_imageat_prompt_builders_lock_expected_json_shape() -> None:
    source = {"reference_id": "ootd_ref", "path": "/tmp/ootd.mp4", "account": "creator"}
    gemini_prompt = gemini_analysis_prompt(source, platform="instagram", prompt_style="minimal")
    grok_prompt = _grok_prompt_builder({"referenceId": "ootd_ref", "fileName": "ootd.mp4"})

    for prompt in (gemini_prompt, grok_prompt):
        assert '"promptMode": "structured_json"' in prompt
        assert '"composition"' in prompt
        assert '"clothing"' in prompt
        assert '"body"' in prompt
        assert '"lighting_and_camera"' in prompt
        assert "Do not flatten" in prompt or "not a flattened paragraph" in prompt

    assert "adult my Soul ID model" not in gemini_prompt
    assert "tattoos" not in grok_prompt.lower()
    assert "hairstyle changes" not in grok_prompt.lower()


def test_generate_video_prompts_uses_latest_analysis_per_reference(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    conn = make_conn(data_root)
    video = tmp_path / "source.mp4"
    video.write_bytes(b"x" * 120_000)
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, account, file_name, extension, kind, size_bytes,
          mtime, path_hash, content_hash, created_at, updated_at
        ) VALUES ('ref_same', ?, 'creator', 'source.mp4', '.mp4', 'video', 120000,
          '2026-05-26T00:00:00+00:00', 'hash', NULL,
          '2026-05-26T00:00:00+00:00', '2026-05-26T00:00:00+00:00')
        """,
        (str(video),),
    )
    old_analysis = {
        "schema": "reference_factory.video_analysis.v1",
        "referenceId": "ref_same",
        "summary": "old weak summary",
        "contentFormat": "mirror_selfie",
        "higgsfield_soul_image_prompt": "OLD generic modern bedroom prompt",
        "kling_3_video_prompt": "OLD generic video prompt",
    }
    new_analysis = {
        "schema": "reference_factory.video_analysis.v1",
        "referenceId": "ref_same",
        "summary": "new strict mirror selfie blueprint",
        "contentFormat": "mirror_selfie",
        "higgsfield_soul_image_prompt": "NEW exact side-profile phone-covering-face prompt",
        "kling_3_video_prompt": "NEW exact hip shift and free-arm extension prompt",
        "recreation_blueprint": {
            "first_frame": {"subject_scale": "full body side-profile mirror reflection"},
            "motion_beats": [{"time_range": "0.0-1.0s", "subject_motion": "tiny phone sway"}],
        },
    }
    conn.execute(
        """
        INSERT INTO reference_analysis_jobs (
          id, reference_id, source_platform, provider_target, account_profile,
          prompt_text, status, analysis_json, created_at, updated_at
        ) VALUES ('job_old', 'ref_same', 'instagram', 'gemini_manual', 'legacy_profile',
          'prompt', 'pattern_ready', ?, '2026-05-26T00:00:00+00:00', '2026-05-26T00:00:00+00:00')
        """,
        (json.dumps(old_analysis),),
    )
    conn.execute(
        """
        INSERT INTO reference_analysis_jobs (
          id, reference_id, source_platform, provider_target, account_profile,
          prompt_text, status, analysis_json, created_at, updated_at
        ) VALUES ('job_new', 'ref_same', 'instagram', 'gemini_manual', 'ig_ofm',
          'prompt', 'pattern_ready', ?, '2026-05-26T00:00:01+00:00', '2026-05-26T00:00:01+00:00')
        """,
        (json.dumps(new_analysis),),
    )
    conn.commit()

    generated = generate_video_prompts(
        conn,
        data_root=data_root,
        target_tools=["higgsfield_soul", "kling_3"],
        model_profile="Stacey",
        include_pending=False,
    )

    prompts = {item["targetTool"]: item["prompt"] for item in generated["prompts"]}
    assert generated["count"] == 2
    image_json = json.loads(prompts["higgsfield_soul_image"]["mainPrompt"])
    assert image_json["prompt_schema_version"] == "imageat_higgsfield.v1"
    assert image_json["prompt"] == "NEW exact side-profile phone-covering-face prompt"
    assert "OLD generic" not in json.dumps(image_json)
    assert image_json["must_keep"][0] == "subject scale: full body side-profile mirror reflection"
    assert "NEW exact hip shift" in prompts["kling_3_video"]["mainPrompt"]
    assert prompts["kling_3_video"]["motion_directives"]["subject_motion"] == "NEW exact hip shift and free-arm extension prompt"


def test_higgsfield_prompt_pair_matching_and_dry_run(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)

    pairs = load_prompt_pairs(data_root=data_root, limit=10)
    result = generate_with_higgsfield(data_root=data_root, limit=1, dry_run=True, wait=True)

    assert len(pairs) == 1
    assert result["status"] == "dry_run"
    run = result["runs"][0]
    assert run["imageCommand"][4] == "text2image_soul_v2"
    assert "kling3_0" in run["videoCommand"]
    assert "--custom_reference_id" in run["imageCommand"]
    assert "5828d958-91dd-4d6d-8909-934503f47644" in run["imageCommand"]
    assert not run["imageCommand"][6].lstrip().startswith("{")
    assert "Same Soul ID woman" in run["imageCommand"][6]
    assert "confident outfit-check selfie" in run["imageCommand"][6]
    assert "deep plunging cleavage" in run["imageCommand"][6]
    assert "round plump juicy ass" in run["imageCommand"][6]
    assert "watermark" not in run["imageCommand"][6].lower()
    assert "platform ui" not in run["imageCommand"][6].lower()
    assert "negative_prompt" not in run["imageCommand"][6]
    assert "natural breast bounce" in run["videoCommand"][6]
    assert "Negative prompt:" in run["videoCommand"][6]
    assert "--sound" in run["videoCommand"]
    assert "off" in run["videoCommand"]
    assert "--start-image" in run["videoCommand"]
    assert len(run["imageCommands"]) == 1


def test_higgsfield_dry_run_supports_candidates_variation_and_costs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        dry_run=True,
        wait=True,
        image_candidates=3,
        variation_grid=True,
        max_credits=20,
    )

    run = result["runs"][0]
    lineage = json.loads(Path(run["lineagePath"]).read_text(encoding="utf-8"))
    assert result["estimatedCredits"] == 13.86
    assert len(run["imageCommands"]) == 3
    assert len(run["variationCommands"]) == 6
    assert run["variationCommand"][4] == "grok_image"
    assert run["variationCommand"][6].startswith("Make one high-quality variation of this exact pose and background")
    assert "leopard-print fitted mini dress matching the reference outfit" in run["variationCommand"][6]
    assert "No text, username, UI, or watermark" not in run["variationCommand"][6]
    assert "Sharp realistic phone photo" in run["variationCommand"][6]
    assert all("deep V" not in command[6] for command in run["variationCommands"])
    assert all("half unbuttoned" not in command[6] for command in run["variationCommands"])
    assert all("white lace camisole" not in command[6] for command in run["variationCommands"])
    assert lineage["generation"]["variationGrid"]["layout"] == "2x3"
    assert lineage["generation"]["variationGrid"]["strategy"] == "individual"
    assert lineage["generation"]["cost"]["estimatedCredits"] == 13.86
    assert lineage["generation"]["selectedCandidateIndex"] == 1
    assert lineage["source"]["promptSchemaVersion"] == "imageat_higgsfield.v1"


def test_higgsfield_soul_grid_strategy_uses_one_soul_id_grid_prompt(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        dry_run=True,
        wait=True,
        image_candidates=3,
        variation_grid=True,
        variation_strategy="soul_grid",
        max_credits=10,
    )

    run = result["runs"][0]
    lineage = json.loads(Path(run["lineagePath"]).read_text(encoding="utf-8"))
    prompt = run["imageCommand"][6]
    assert result["estimatedCredits"] == 7.62
    assert len(run["imageCommands"]) == 1
    assert run["imageCommand"][4] == "text2image_soul_v2"
    assert run["imageCommand"][8] == "5828d958-91dd-4d6d-8909-934503f47644"
    assert "--aspect_ratio" in run["imageCommand"]
    assert "3:2" in run["imageCommand"]
    assert run["variationCommands"] == []
    assert run["variationCommand"] is None
    assert "Create one high-quality six-panel grid image, exactly three columns and two rows" in prompt
    assert "same Soul ID woman" in prompt
    assert "side-profile mirror selfie" in prompt
    assert "smartphone raised near the face" in prompt
    assert "fitted mini dress" in prompt
    assert "bodycon" in prompt
    assert "bright minimalist bedroom" in prompt
    assert "soft natural daylight" in prompt
    assert "Outfit variations across the panels" in prompt
    assert "deep plunging cleavage" in prompt
    assert "generous pushed-up full breasts" in prompt
    assert "fabric straining against her chest" in prompt
    assert "tiny cinched waist" in prompt
    assert "wide hips" in prompt
    assert "thick thighs" in prompt
    assert "round plump juicy ass prominently displayed in profile" in prompt
    assert "skin-tight fabric clinging to every curve" in prompt
    assert "leopard-print fitted mini dress matching the reference outfit" in prompt
    assert "slightly shorter leopard-print bodycon mini dress" in prompt
    assert "observed short-form format" not in prompt
    assert "spicy_lifestyle" not in prompt
    assert "Long, voluminous" not in prompt
    assert "hair" not in prompt.lower()
    assert "No text" not in prompt
    assert "No clear" not in prompt
    assert "non-nude" not in prompt
    assert "watermark" not in prompt.lower()
    assert "platform ui" not in prompt.lower()
    assert "negative_prompt" not in prompt
    assert "screenshot" not in prompt.lower()
    assert "platform-safe" not in prompt
    assert "social-safe" not in prompt
    assert "non-explicit" not in prompt
    assert "when safe" not in prompt
    assert "branding" not in prompt.lower()
    assert "identifiers" not in prompt.lower()
    assert lineage["generation"]["variationGrid"]["strategy"] == "soul_grid"
    assert lineage["generation"]["variationGrid"]["layout"] == "2x3"
    assert lineage["generation"]["variationGrid"]["provider"] == "text2image_soul_v2"
    assert lineage["generation"]["variationGrid"]["prompt"] == run["variationPrompt"]


def test_higgsfield_runner_prefers_grok_compiled_prompts(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    image_path = data_root / "reference_intake" / "daily_higgsfield_image_prompts.jsonl"
    video_path = data_root / "reference_intake" / "daily_kling_video_prompts.jsonl"
    image_row = json.loads(image_path.read_text(encoding="utf-8"))
    video_row = json.loads(video_path.read_text(encoding="utf-8"))
    compiled = {
        "soul_id_2x3_prompt": "GROK SOUL GRID PROMPT",
        "single_panel_prompt": "GROK SINGLE PANEL PROMPT",
        "kling_video_prompt": "GROK KLING VIDEO PROMPT",
        "kling_negative_prompt": "GROK KLING NEGATIVE",
        "structured_breakdown": {
            "pose_lock": "locked pose",
            "body_emphasis": "deep cleavage, pushed-up breasts, tiny waist, round ass",
            "outfit_variations": ["one", "two", "three", "four", "five", "six"],
            "motion_directives": "hip sway",
            "key_constraints": ["same pose", "same room", "same light"],
        },
        "confidence_score": 92,
    }
    image_row["compiledPrompts"] = compiled
    video_row["compiledPrompts"] = compiled
    image_path.write_text(json.dumps(image_row) + "\n", encoding="utf-8")
    video_path.write_text(json.dumps(video_row) + "\n", encoding="utf-8")

    single = generate_with_higgsfield(data_root=data_root, limit=1, dry_run=True, wait=True)
    grid = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        dry_run=True,
        wait=True,
        variation_grid=True,
        variation_strategy="soul_grid",
        max_credits=10,
    )

    assert single["runs"][0]["imageCommand"][6] == "GROK SINGLE PANEL PROMPT"
    assert single["runs"][0]["videoCommand"][6] == "GROK KLING VIDEO PROMPT Negative prompt: GROK KLING NEGATIVE"
    assert grid["runs"][0]["imageCommand"][6] == "GROK SOUL GRID PROMPT"


def test_compile_prompts_with_grok_api_updates_prompt_jsonl(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root, reference_id="ref_grok")
    reference_image = tmp_path / "reference.jpg"
    reference_image.write_bytes(b"jpg")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-secret")

    def fake_completion(**kwargs):
        assert kwargs["api_key"] == "xai-test-secret"
        assert kwargs["image_path"] == reference_image
        assert kwargs["response_format"]["type"] == "json_schema"
        assert "Example prompt style to imitate" in kwargs["prompt"]
        assert "Use the image as the source of truth" in kwargs["prompt"]
        assert "Extra user instructions: more turquoise, more curve emphasis" in kwargs["prompt"]
        return json.dumps({
            "soul_id_2x3_prompt": "Grok final 2x3 prompt with deep cleavage and round plump ass",
            "single_panel_prompt": "Grok final single panel prompt with tight blue dress",
            "kling_video_prompt": "Grok final Kling prompt with hip sway and natural breast bounce",
            "kling_negative_prompt": "blurry, flat chest, flat ass",
            "structured_breakdown": {
                "pose_lock": "same mirror selfie pose with arched back",
                "body_emphasis": "deep cleavage, pushed-up breasts, tiny waist, wide hips, round plump ass",
                "outfit_variations": [
                    "blue dress",
                    "white dress",
                    "grey dress",
                    "cream dress",
                    "black dress",
                    "sheer white dress",
                ],
                "motion_directives": "hip sway, glute movement, hand near head",
                "key_constraints": ["same pose", "same room", "same lighting"],
            },
            "confidence_score": 88,
            "notes": "ok",
        })

    monkeypatch.setattr("reference_factory.reference_intake._xai_chat_completion", fake_completion)

    result = compile_prompts_with_grok_api(
        data_root=data_root,
        reference_id="ref_grok",
        reference_media=reference_image,
        model="grok-4",
        instructions="more turquoise, more curve emphasis",
    )

    image_row = json.loads((data_root / "reference_intake" / "daily_higgsfield_image_prompts.jsonl").read_text(encoding="utf-8"))
    video_row = json.loads((data_root / "reference_intake" / "daily_kling_video_prompts.jsonl").read_text(encoding="utf-8"))
    assert result["compiledPrompts"]["soul_id_2x3_prompt"].startswith("Create one high-quality six-panel grid image")
    assert image_row["compiledPrompts"]["soul_id_2x3_prompt"].endswith("Grok final 2x3 prompt with deep cleavage and round plump ass")
    assert "no extra panels" in image_row["compiledPrompts"]["soul_id_2x3_prompt"]
    assert image_row["compiledPrompts"]["single_panel_prompt"] == "Grok final single panel prompt with tight blue dress"
    assert video_row["compiledPrompts"]["kling_video_prompt"] == "Grok final Kling prompt with hip sway and natural breast bounce"
    assert video_row["compiledPrompts"]["kling_negative_prompt"] == "blurry, flat chest, flat ass"
    assert image_row["compiledPrompts"]["structured_breakdown"]["outfit_variations"] == [
        "blue dress",
        "white dress",
        "grey dress",
        "cream dress",
        "black dress",
        "sheer white dress",
    ]
    assert result["compiledPrompts"]["confidence_score"] == 88
    assert "xai-test-secret" not in json.dumps(result)


def test_compile_prompts_with_grok_api_rejects_weak_breakdown(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root, reference_id="ref_grok")
    reference_image = tmp_path / "reference.jpg"
    reference_image.write_bytes(b"jpg")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-secret")

    def fake_completion(**_kwargs):
        return json.dumps({
            "soul_id_2x3_prompt": "ok",
            "single_panel_prompt": "ok",
            "kling_video_prompt": "ok",
            "kling_negative_prompt": "ok",
            "structured_breakdown": {
                "pose_lock": "pose",
                "body_emphasis": "body",
                "outfit_variations": ["only one"],
                "motion_directives": "motion",
                "key_constraints": ["same pose", "same room", "same light"],
            },
            "confidence_score": 95,
        })

    monkeypatch.setattr("reference_factory.reference_intake._xai_chat_completion", fake_completion)

    try:
        compile_prompts_with_grok_api(
            data_root=data_root,
            reference_id="ref_grok",
            reference_media=reference_image,
            model="grok-4",
        )
    except RuntimeError as exc:
        assert "outfit_variations" in str(exc)
    else:
        raise AssertionError("expected weak Grok breakdown to be rejected")


def test_higgsfield_variation_moderation_status_is_blocked(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    selected_image = tmp_path / "selected.png"
    selected_image.write_bytes(b"png")

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        assert "grok_image" in cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": "grid_job", "status": "nsfw", "result_url": ""}), "")

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        variation_grid=True,
        variation_strategy="grid",
        selected_image=selected_image,
        no_video=True,
        no_campaign_intake=True,
        runner=fake_runner,
    )

    run = result["runs"][0]
    lineage = json.loads(Path(run["lineagePath"]).read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert run["errors"] == ["variation_grid_blocked"]
    assert lineage["generation"]["variationGrid"]["status"] == "blocked"
    assert lineage["generation"]["variationGrid"]["path"] is None


def test_higgsfield_variation_reruns_blocked_cached_result(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    monkeypatch.setattr("reference_factory.higgsfield_runner._day", lambda: "2026-05-27")
    selected_image = tmp_path / "selected.png"
    grid_image = tmp_path / "grid.png"
    selected_image.write_bytes(b"png")
    grid_image.write_bytes(b"grid")
    out_dir = data_root / "reference_intake" / "generated" / "2026-05-27" / "ref_001"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "variation_grid_2x3_result.json").write_text(
        json.dumps({"id": "old_grid", "status": "nsfw", "result_url": ""}) + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert "grok_image" in cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": "new_grid", "path": str(grid_image)}), "")

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        variation_grid=True,
        variation_strategy="grid",
        selected_image=selected_image,
        no_video=True,
        no_campaign_intake=True,
        runner=fake_runner,
    )

    lineage = json.loads(Path(result["runs"][0]["lineagePath"]).read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert lineage["generation"]["variationGrid"]["status"] == "generated"
    assert lineage["generation"]["variationGrid"]["jobId"] == "new_grid"


def test_higgsfield_individual_variations_assemble_local_grid(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    monkeypatch.setattr("reference_factory.higgsfield_runner._day", lambda: "2026-05-27")
    selected_image = tmp_path / "selected.png"
    selected_image.write_bytes(b"png")
    panel_png = tmp_path / "panel.png"
    panel_png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
        b"\x00\x05\xfe\x02\xfeA\xe2`\x82\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert "grok_image" in cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": f"panel_{len(calls)}", "path": str(panel_png)}), "")

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        variation_grid=True,
        variation_strategy="individual",
        selected_image=selected_image,
        no_video=True,
        no_campaign_intake=True,
        max_credits=20,
        runner=fake_runner,
    )

    lineage = json.loads(Path(result["runs"][0]["lineagePath"]).read_text(encoding="utf-8"))
    assert len(calls) == 6
    assert lineage["generation"]["variationGrid"]["strategy"] == "individual"
    assert lineage["generation"]["variationGrid"]["status"] == "generated"
    assert len(lineage["generation"]["variationGrid"]["panels"]) == 6
    assert Path(lineage["generation"]["variationGrid"]["path"]).exists()
    assert Path(lineage["generation"]["variationGrid"]["gridVideoPath"]).exists()
    assert Path(lineage["generation"]["variationGrid"]["verticalSequenceVideoPath"]).exists()


def test_higgsfield_can_animate_individual_variation_panels(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    monkeypatch.setattr("reference_factory.higgsfield_runner._day", lambda: "2026-05-27")
    selected_image = tmp_path / "selected.png"
    selected_image.write_bytes(b"png")
    panel_png = tmp_path / "panel.png"
    panel_png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
        b"\x00\x05\xfe\x02\xfeA\xe2`\x82\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    panel_video = tmp_path / "panel_video.mp4"
    create_video(panel_video)
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "grok_image" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": f"panel_{len(calls)}", "path": str(panel_png)}), "")
        if "kling3_0" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": f"panel_video_{len(calls)}", "path": str(panel_video)}), "")
        raise AssertionError(cmd)

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        variation_grid=True,
        variation_strategy="individual",
        animate_variation_panels=True,
        selected_image=selected_image,
        no_video=True,
        no_campaign_intake=True,
        max_credits=60,
        runner=fake_runner,
    )

    run = result["runs"][0]
    lineage = json.loads(Path(run["lineagePath"]).read_text(encoding="utf-8"))
    assert result["estimatedCredits"] == 51.0
    assert len([cmd for cmd in calls if "grok_image" in cmd]) == 6
    assert len([cmd for cmd in calls if "kling3_0" in cmd]) == 6
    assert run["errors"] == []
    assert lineage["generation"]["variationGrid"]["panelVideoStatus"] == "generated"
    assert len(lineage["generation"]["variationGrid"]["panelVideos"]) == 6
    assert Path(lineage["generation"]["variationGrid"]["animatedGridVideoPath"]).exists()


def test_higgsfield_reuses_existing_panels_before_kling_animation(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    monkeypatch.setattr("reference_factory.higgsfield_runner._day", lambda: "2026-05-27")
    selected_image = tmp_path / "selected.png"
    selected_image.write_bytes(b"png")
    panel_dir = tmp_path / "panels"
    panel_dir.mkdir()
    panel_png = tmp_path / "panel.png"
    panel_png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
        b"\x00\x05\xfe\x02\xfeA\xe2`\x82\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    for idx in range(6):
        (panel_dir / f"{idx + 1:02d}_panel.png").write_bytes(panel_png.read_bytes())
    panel_video = tmp_path / "panel_video.mp4"
    create_video(panel_video)
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert "grok_image" not in cmd
        assert "kling3_0" in cmd
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": f"panel_video_{len(calls)}", "path": str(panel_video)}), "")

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        variation_grid=True,
        variation_strategy="individual",
        animate_variation_panels=True,
        variation_panel_dir=panel_dir,
        selected_image=selected_image,
        no_video=True,
        no_campaign_intake=True,
        max_credits=50,
        runner=fake_runner,
    )

    run = result["runs"][0]
    lineage = json.loads(Path(run["lineagePath"]).read_text(encoding="utf-8"))
    assert result["estimatedCredits"] == 45.0
    assert len(calls) == 6
    assert run["variationCommands"] == []
    assert run["errors"] == []
    assert lineage["generation"]["variationGrid"]["strategy"] == "existing_panel_folder"
    assert lineage["generation"]["variationGrid"]["panelVideoStatus"] == "generated"
    assert len(lineage["generation"]["variationGrid"]["panelVideos"]) == 6
    assert Path(lineage["generation"]["variationGrid"]["animatedGridVideoPath"]).exists()


def test_verify_proof_bundle_accepts_complete_no_audio_bundle(tmp_path: Path) -> None:
    bundle = create_accepted_proof_bundle(tmp_path)

    def fake_probe(path: Path) -> dict[str, object]:
        if path.name == "04_best_2x3_grid_video.mp4":
            width, height, duration = 1620, 1920, 5.0
        elif path.name == "05_best_2x3_vertical_sequence.mp4":
            width, height, duration = 1080, 1920, 6.0
        elif path.name == "06_kling_single_outfit_motion.mp4":
            width, height, duration = 720, 1280, 5.041667
        elif path.name == "07_campaign_passthrough.mp4":
            width, height, duration = 1080, 1920, 6.0
        else:
            raise AssertionError(path)
        return {
            "valid": True,
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "probe_json": {"streams": [{"codec_type": "video"}]},
        }

    def fake_image_probe(path: Path) -> dict[str, object]:
        if path.name == "03_best_2x3_image.png":
            return {"valid": True, "width": 1620, "height": 1920}
        if path.name == "final_visual_audit_sheet.jpg":
            return {"valid": True, "width": 1620, "height": 7680}
        raise AssertionError(path)

    result = verify_proof_bundle(
        bundle,
        probe_video=fake_probe,
        probe_image=fake_image_probe,
        detect_black=lambda _path: [],
    )

    assert result["status"] == "ok"
    assert result["failed"] == 0


def test_verify_proof_bundle_blocks_audio_or_stale_prompt_warning(tmp_path: Path) -> None:
    bundle = create_accepted_proof_bundle(tmp_path)
    (bundle / "generated_asset_lineage.json").write_text(json.dumps({
        "quality": {"promptScore": {"status": "pass", "warnings": ["stale warning"]}},
    }), encoding="utf-8")

    def fake_probe(path: Path) -> dict[str, object]:
        sizes = {
            "04_best_2x3_grid_video.mp4": (1620, 1920, 5.0),
            "05_best_2x3_vertical_sequence.mp4": (1080, 1920, 6.0),
            "06_kling_single_outfit_motion.mp4": (720, 1280, 5.041667),
            "07_campaign_passthrough.mp4": (1080, 1920, 6.0),
        }
        width, height, duration = sizes[path.name]
        return {
            "valid": True,
            "width": width,
            "height": height,
            "duration_seconds": duration,
            "probe_json": {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]},
        }

    def fake_image_probe(path: Path) -> dict[str, object]:
        if path.name == "03_best_2x3_image.png":
            return {"valid": True, "width": 1620, "height": 1920}
        if path.name == "final_visual_audit_sheet.jpg":
            return {"valid": True, "width": 1620, "height": 7680}
        raise AssertionError(path)

    def fake_black(path: Path) -> list[dict[str, float]]:
        if path.name == "05_best_2x3_vertical_sequence.mp4":
            return [{"start": 1.0, "end": 1.5, "duration": 0.5}]
        return []

    result = verify_proof_bundle(
        bundle,
        probe_video=fake_probe,
        probe_image=fake_image_probe,
        detect_black=fake_black,
    )

    assert result["status"] == "failed"
    names = {check["name"] for check in result["checks"] if check["status"] == "fail"}
    assert "lineage.prompt_score.no_warnings" in names
    assert "video.assets/04_best_2x3_grid_video.mp4.audio" in names
    assert "video.assets/05_best_2x3_vertical_sequence.mp4.no_black_segments" in names


def test_higgsfield_prompt_pairs_skip_temp_and_tiny_sources(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    valid = tmp_path / "valid.mp4"
    valid.write_bytes(b"x" * 120_000)
    temp = Path("/private/var/folders/example/sample.mp4")
    write_higgsfield_prompt_pairs(data_root, ["ref_temp", "ref_tiny", "ref_valid"])
    conn = make_conn(data_root)
    now = "2026-05-26T00:00:00+00:00"
    rows = [
        ("ref_temp", str(temp), "sample.mp4", 3032),
        ("ref_tiny", str(tmp_path / "tiny.mp4"), "tiny.mp4", 3024),
        ("ref_valid", str(valid), "valid.mp4", 120_000),
    ]
    for ref, path, name, size in rows:
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, account, file_name, extension, kind, size_bytes,
              mtime, path_hash, content_hash, created_at, updated_at
            ) VALUES (?, ?, 'creator', ?, '.mp4', 'video', ?, ?, ?, NULL, ?, ?)
            """,
            (ref, path, name, size, now, ref, now, now),
        )
    conn.commit()

    pairs = load_prompt_pairs(data_root=data_root, limit=3)

    assert [pair.reference_id for pair in pairs] == ["ref_valid"]


def test_higgsfield_prompt_pairs_can_filter_reference_id(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pairs(data_root, ["ref_a", "ref_b"])

    pairs = load_prompt_pairs(data_root=data_root, limit=5, reference_id="ref_b")

    assert [pair.reference_id for pair in pairs] == ["ref_b"]


def test_higgsfield_generation_blocks_over_credit_cap(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)

    result = generate_with_higgsfield(data_root=data_root, limit=1, dry_run=True, max_credits=1.0)

    assert result["status"] == "blocked"
    assert result["reason"] == "max_credits_exceeded"


def test_higgsfield_generation_blocks_low_prompt_score(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    prompt_dir = data_root / "reference_intake"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    image = {
        "schema": "reference_factory.higgsfield_soul_image_prompt.v1",
        "tool": "higgsfield_soul_image",
        "status": "prompt_ready",
        "sourceReferenceId": "ref_weak",
        "sourcePatternId": "pattern_weak",
        "modelProfile": "Stacey",
        "mainPrompt": "pretty woman",
        "negativePrompt": "",
    }
    video = {
        "schema": "reference_factory.kling_3_video_prompt.v1",
        "tool": "kling_3_video",
        "status": "prompt_ready",
        "sourceReferenceId": "ref_weak",
        "sourcePatternId": "pattern_weak",
        "modelProfile": "Stacey",
        "mainPrompt": "make a video",
        "negativePrompt": "",
    }
    (prompt_dir / "daily_higgsfield_image_prompts.jsonl").write_text(json.dumps(image) + "\n", encoding="utf-8")
    (prompt_dir / "daily_kling_video_prompts.jsonl").write_text(json.dumps(video) + "\n", encoding="utf-8")

    result = generate_with_higgsfield(data_root=data_root, limit=1, dry_run=True)

    assert result["status"] == "blocked"
    assert result["count"] == 0
    assert result["blockedPrompts"][0]["referenceId"] == "ref_weak"
    assert result["blockedPrompts"][0]["promptScore"]["score"] < 72
    assert result["estimatedCredits"] == 0.0


def test_higgsfield_mocked_success_writes_lineage(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    image_file = tmp_path / "image.png"
    video_file = tmp_path / "video.mp4"
    image_file.write_bytes(b"png")
    video_file.write_bytes(b"mp4")
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "text2image_soul_v2" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": "img_job", "path": str(image_file)}), "")
        if "kling3_0" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": "vid_job", "path": str(video_file)}), "")
        raise AssertionError(cmd)

    result = generate_with_higgsfield(data_root=data_root, limit=1, wait=True, runner=fake_runner)

    run = result["runs"][0]
    lineage = json.loads(Path(run["lineagePath"]).read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert len(calls) == 2
    assert lineage["generation"]["tool"] == "higgsfield_kling_cli"
    assert lineage["generation"]["fallback"]["provider"] == "grok_imagine"
    assert lineage["generation"]["fallback"]["prompt"]
    assert lineage["generation"]["variationGrid"]["provider"] == "grok_image"
    assert lineage["generation"]["variationGrid"]["layout"] == "2x3"
    assert "Make a 2x3 variation of this exact pose and background" in lineage["generation"]["variationGrid"]["prompt"]
    assert "No text, username, UI, or watermark" not in lineage["generation"]["variationGrid"]["prompt"]
    assert "Sharp realistic phone-photo quality" in lineage["generation"]["variationGrid"]["prompt"]
    assert lineage["quality"]["promptScore"]["schema"] == "reference_factory.prompt_quality_score.v1"
    assert lineage["generation"]["imageJobId"] == "img_job"
    assert lineage["generation"]["videoJobId"] == "vid_job"
    assert Path(lineage["generation"]["assetPath"]).exists()


def test_provider_doctor_reports_actionable_provider_state(monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-test-secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("reference_factory.provider_doctor.shutil.which", lambda binary: f"/usr/local/bin/{binary}")

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"data":[{"id":"grok-4"}]}'

    def fake_urlopen(request, timeout):  # noqa: ARG001
        assert "xai-test-secret" in request.headers["Authorization"]
        return FakeResponse()

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["higgsfield", "auth", "whoami"]:
            return subprocess.CompletedProcess(cmd, 0, stdout='{"email":"operator@example.com"}', stderr="")
        if cmd[:3] == ["higgsfield", "soul-id", "list"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Stacey 5828d958-91dd-4d6d-8909-934503f47644", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected")

    result = provider_doctor(
        require_gemini=False,
        check_xai=True,
        check_higgsfield_auth=True,
        runner=fake_runner,
        urlopen=fake_urlopen,
    )

    by_name = {item["name"]: item for item in result["checks"]}
    assert result["status"] in {"ok", "warning"}
    assert by_name["xai.spend"]["status"] == "ok"
    assert by_name["env.gemini"]["status"] == "skipped"
    assert by_name["higgsfield.soul_id.stacey"]["status"] == "ok"
    assert "xai-test-secret" not in json.dumps(result)


def test_higgsfield_campaign_intake_uses_campaign_pythonpath(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    campaign_root = tmp_path / "campaign_factory"
    (campaign_root / ".venv" / "bin").mkdir(parents=True)
    write_higgsfield_prompt_pair(data_root)
    image_file = tmp_path / "image.png"
    video_file = tmp_path / "video.mp4"
    image_file.write_bytes(b"png")
    video_file.write_bytes(b"mp4")
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "text2image_soul_v2" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": "img_job", "path": str(image_file)}), "")
        if "kling3_0" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"id": "vid_job", "path": str(video_file)}), "")
        if "intake-finished-video" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "{\"ok\": true}", "")
        raise AssertionError(cmd)

    result = generate_with_higgsfield(
        data_root=data_root,
        limit=1,
        campaign_factory_root=campaign_root,
        campaign="daily",
        model="stacey",
        runner=fake_runner,
    )

    intake = result["runs"][0]["campaignIntake"]
    assert intake["status"] == "ok"
    assert intake["command"][0] == "/usr/bin/env"
    assert intake["command"][1] == f"PYTHONPATH={campaign_root}"
    assert "-m" in intake["command"]
    assert "campaign_factory.cli" in intake["command"]


def test_higgsfield_result_list_shape_and_resume_image(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root, "ref_resume")
    output_dir = data_root / "reference_intake" / "generated"
    image_file = tmp_path / "image.png"
    video_file = tmp_path / "video.mp4"
    image_file.write_bytes(b"png")
    video_file.write_bytes(b"mp4")
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "text2image_soul_v2" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": [{"id": "img_job", "path": str(image_file)}]}), "")
        if "kling3_0" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": [{"id": "vid_job", "path": str(video_file)}]}), "")
        raise AssertionError(cmd)

    first = generate_with_higgsfield(data_root=data_root, limit=1, runner=fake_runner)
    second = generate_with_higgsfield(data_root=data_root, limit=1, runner=fake_runner)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert sum(1 for cmd in calls if "text2image_soul_v2" in cmd) == 1
    assert sum(1 for cmd in calls if "kling3_0" in cmd) == 1
    assert output_dir.exists()


def test_higgsfield_failed_image_prevents_video_generation(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    write_higgsfield_prompt_pair(data_root)
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "image failed")

    result = generate_with_higgsfield(data_root=data_root, limit=1, runner=fake_runner)

    assert result["status"] == "partial"
    assert result["runs"][0]["status"] == "generation_failed"
    assert len(calls) == 1


def test_reference_intake_imports_gemini_app_response_from_queue(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    account = source / "creator_app"
    account.mkdir(parents=True)
    create_video(account / "mirror.mp4")
    conn = make_conn(tmp_path)

    queued = queue_reference_analysis(
        conn,
        source,
        data_root=tmp_path / "data",
        platform="instagram",
        provider_target="gemini_app",
        prompt_style="minimal",
    )
    queue_path = Path(queued["export"]["jsonPath"])
    response_path = tmp_path / "gemini_response.txt"
    response_path.write_text(json.dumps({
        "schema": "reference_factory.gemini_prompt_analysis.v1",
        "referenceId": "gemini_made_up_file_stem",
        "summary": "A mirror selfie format with casual phone movement.",
        "contentFormat": "mirror_selfie",
        "higgsfield_soul_image_prompt": "My Soul ID model in a casual mirror selfie first frame, soft room light, fitted casual outfit.",
        "higgsfield_negative_prompt": "watermark, username, copied face",
        "kling_3_video_prompt": "Use the generated Higgsfield image as first frame; small handheld mirror movement, subtle pose shift, 5 seconds.",
        "kling_negative_prompt": "watermark, platform UI, copied person",
        "motion_notes": "subtle pose shift",
        "camera_notes": "phone mirror selfie",
        "style_notes": "casual social video",
        "copy_risk_notes": "do not copy identity or exact room",
        "what_to_change": "change outfit, room, and text",
    }), encoding="utf-8")

    imported = import_gemini_app_response(
        conn,
        queue_path=queue_path,
        response_path=response_path,
        data_root=tmp_path / "data",
        model_profile="model_app",
    )

    assert imported["import"]["imported"] == 1
    assert imported["analysisJobId"] == queued["jobs"][0]["id"]
    assert imported["referenceId"] == queued["jobs"][0]["referenceId"]
    assert imported["promptGeneration"]["count"] == 2
    assert Path(imported["promptGeneration"]["export"]["dailyHiggsfieldImageJsonlPath"]).exists()


def test_reference_intake_can_queue_video_only_from_mixed_folder(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    account = source / "creator_c"
    account.mkdir(parents=True)
    create_video(account / "clip.mp4")
    (account / "cover.jpg").write_bytes(b"fake jpg")
    conn = make_conn(tmp_path)

    queued = queue_reference_analysis(
        conn,
        source,
        data_root=tmp_path / "data",
        platform="tiktok",
        media_kinds=["video"],
    )

    assert queued["queued"] == 1
    assert queued["mediaKinds"] == ["video"]
    assert queued["jobs"][0]["fileName"] == "clip.mp4"


def test_reference_local_analysis_creates_pattern_card_and_export(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    account = source / "creator_local"
    account.mkdir(parents=True)
    create_video(account / "mirror_relationship.mp4")
    conn = make_conn(tmp_path)

    result = analyze_reference_local(
        conn,
        source,
        data_root=tmp_path / "data",
        platform="instagram",
        limit=1,
    )
    exported = export_video_analyses(conn, data_root=tmp_path / "data", provider="local")

    assert result["analyzed"] == 1
    assert result["items"][0]["patternCardId"]
    assert Path(result["export"]["jsonPath"]).exists()
    assert Path(exported["jsonPath"]).exists()
    payload = json.loads(Path(exported["jsonPath"]).read_text())
    analysis = payload["items"][0]
    assert analysis["schema"] == "reference_factory.video_analysis.v1"
    assert analysis["patternCard"]["schema"] == "reference_factory.pattern_card.v1"
    assert analysis["patternCard"]["formatType"] in {"mirror_selfie", "selfie_video"}
    assert analysis["signals"]["frameSamples"]


def test_public_prompt_card_handles_shared_choice_caption_archetype() -> None:
    from reference_factory.public_metrics import _prompt_card_from_post

    card = _prompt_card_from_post({
        "id": "post_1",
        "rank": 1,
        "ownerUsername": "creator",
        "url": "https://example.com/p/post_1",
        "videoPlayCount": 1000,
        "videoViewCount": 1100,
        "likesCount": 100,
        "commentsCount": 10,
        "matchType": "external_only",
        "referenceId": "ref_1",
        "caption": "pick one",
    })

    assert card["learnedPattern"]["captionArchetype"] == "choice_bait"
    assert card["learnedPattern"]["structureNotes"]


def test_thumbnail_batch_skips_existing_and_creates_missing(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    create_video(account / "b.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)
    probe_videos(conn)

    first = thumbnail_batch(conn, tmp_path / "data", limit=1)
    second = thumbnail_batch(conn, tmp_path / "data", limit=10)

    assert first["created"] == 1
    assert second["created"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM frame_samples WHERE role='contact'").fetchone()["c"] == 2


def test_review_query_filters_and_clear_label(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)
    probe_videos(conn)
    thumbnail_batch(conn, tmp_path / "data")
    ref = conn.execute("SELECT reference_id FROM source_files LIMIT 1").fetchone()["reference_id"]
    upsert_caption_pattern(conn, ref, "ocr_1", "good hook caption", [], 80)
    conn.commit()

    set_reference_label(conn, ref, "maybe", ["visual_style"])
    maybe = reference_query(conn, label="maybe", captioned=True, min_score=1)
    unreviewed = reference_query(conn, label="unreviewed")
    set_reference_label(conn, ref, None)
    cleared = reference_query(conn, label="unreviewed")

    assert maybe["total"] == 1
    assert maybe["items"][0]["tags"] == ["visual_style"]
    assert unreviewed["total"] == 0
    assert cleared["total"] == 1


def test_review_batch_balances_and_excludes_labeled_items(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    for idx in range(8):
        account = "account_a" if idx < 4 else "account_b"
        ref = f"ref_{idx}"
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, account, file_name, extension, kind,
              size_bytes, mtime, path_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, '.mp4', 'video', 100, 'now', ?, 'now', 'now')
            """,
            (ref, f"/examples/{account}/{idx}.mp4", account, f"{idx}.mp4", f"hash_{idx}"),
        )
        conn.execute(
            """
            INSERT INTO video_probes (
              reference_id, valid, duration_seconds, width, height, fps,
              codec, aspect_ratio, rotation, probe_json, probed_at
            )
            VALUES (?, 1, 8, 1080, 1920, 30, 'h264', 0.5625, 0, '{}', 'now')
            """,
            (ref,),
        )
        if idx % 2 == 0:
            upsert_caption_pattern(conn, ref, f"ocr_{idx}", f"caption {idx}", [], 90)
    set_reference_label(conn, "ref_0", "ignore")

    result = review_batch(conn, target=4, mode="balanced", account_cap=2)

    ids = {item["referenceId"] for item in result["items"]}
    account_counts = {row["account"]: row["count"] for row in result["accountCounts"]}
    assert result["selected"] == 4
    assert result["captionedSelected"] >= 1
    assert result["visualSelected"] >= 1
    assert "ref_0" not in ids
    assert max(account_counts.values()) <= 2


def test_ocr_cleanup_drops_junk_and_keeps_useful_caption(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)
    ref = conn.execute("SELECT reference_id FROM source_files LIMIT 1").fetchone()["reference_id"]
    upsert_caption_pattern(conn, ref, "ocr_short", "B", [], 99)
    upsert_caption_pattern(conn, ref, "ocr_good", "this is a strong hook", [], 82)
    conn.commit()

    result = ocr_cleanup(conn)

    assert result["removed"] == 1
    remaining = conn.execute("SELECT normalized_text FROM caption_patterns").fetchone()[0]
    assert remaining == "this is a strong hook"


def test_gold_export_includes_metadata(tmp_path: Path) -> None:
    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    scan_source(conn, source)
    probe_videos(conn)
    thumbnail_batch(conn, tmp_path / "data")
    ref = conn.execute("SELECT reference_id FROM source_files LIMIT 1").fetchone()["reference_id"]
    upsert_caption_pattern(conn, ref, "ocr_1", "caption text here", [], 91)
    set_reference_label(conn, ref, "gold", ["caption_style"], "keeper")

    exported = export_gold(conn, tmp_path / "data")
    line = Path(exported["manifestPath"]).read_text().strip()

    assert '"label": "gold"' in line
    assert '"bestCaption": "caption text here"' in line
    assert '"thumbnailPath":' in line
    assert Path(exported["summaryPath"]).exists()
    assert exported["summary"]["goldCount"] == 1
    assert exported["summary"]["tagCounts"]["caption_style"] == 1
    assert exported["summary"]["accountDistribution"][0]["account"] == "account_a"


def test_review_api_lists_labels_and_stats(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "a.mp4")
    conn = make_conn(tmp_path)
    db_path = tmp_path / "reference_factory.sqlite"
    scan_source(conn, source)
    probe_videos(conn)
    thumbnail_batch(conn, tmp_path / "data")
    ref = conn.execute("SELECT reference_id FROM source_files LIMIT 1").fetchone()["reference_id"]
    conn.close()
    client = TestClient(create_app(db_path))

    label_response = client.post(
        f"/api/reference/{ref}/label",
        json={"label": "gold", "tags": ["mirror"], "notes": "good"},
    )
    refs_response = client.get("/api/references?label=gold")
    batch_response = client.get("/api/review-batch?mode=balanced&target=10")
    stats_response = client.get("/api/stats")

    assert label_response.status_code == 200
    assert refs_response.json()["total"] == 1
    assert refs_response.json()["items"][0]["label"] == "gold"
    assert batch_response.status_code == 200
    assert batch_response.json()["schema"] == "reference_factory.review_batch.v1"
    assert stats_response.json()["counts"]["gold"] == 1
    assert stats_response.json()["goldProgress"]["target"] == 300
    assert review_stats(connect(db_path))["counts"]["validVideos"] == 1


def test_reference_intake_api_queues_and_generates_prompt_exports(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    source = tmp_path / "examples"
    account = source / "account_a"
    account.mkdir(parents=True)
    create_video(account / "mirror_selfie.mp4")
    db_path = tmp_path / "reference_factory.sqlite"
    client = TestClient(create_app(db_path))

    queued = client.post(
        "/api/reference-analysis/queue",
        json={
            "source": str(source),
            "platform": "instagram",
            "providerTarget": "gemini",
            "intakeProfile": "ig_ofm",
            "mediaKinds": ["video"],
            "limit": 1,
        },
    )
    generated = client.post(
        "/api/video-prompts/generate",
        json={
            "tools": ["higgsfield_soul_image", "kling_3_video"],
            "modelProfile": "model_a",
            "limit": 1,
            "includePending": True,
        },
    )
    prompts = client.get("/api/video-prompts?limit=10")

    assert queued.status_code == 200
    assert queued.json()["intakeProfile"] == "ig_ofm"
    assert generated.status_code == 200
    assert generated.json()["count"] == 2
    assert prompts.status_code == 200
    assert Path(prompts.json()["dailyPromptReviewPath"]).exists()
    assert Path(prompts.json()["dailyHiggsfieldImageJsonlPath"]).exists()
    assert Path(prompts.json()["dailyKlingVideoJsonlPath"]).exists()


def test_gemini_api_response_json_extraction_handles_markdown() -> None:
    parsed = _json_from_model_text(
        """```json
        {"schema":"reference_factory.video_analysis.v1","summary":"mirror selfie"}
        ```"""
    )

    assert parsed["schema"] == "reference_factory.video_analysis.v1"
    assert parsed["summary"] == "mirror selfie"


def test_import_apify_metrics_matches_local_media_and_generates_prompts(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, account, file_name, extension, kind,
          size_bytes, mtime, path_hash, created_at, updated_at
        )
        VALUES (
          'ref_local', '/examples/account_a/account_a_1111111111_2222222222_3333333333.mp4',
          'account_a', 'account_a_1111111111_2222222222_3333333333.mp4',
          '.mp4', 'video', 100, 'now', 'hash', 'now', 'now'
        )
        """
    )
    apify_path = tmp_path / "apify.json"
    apify_path.write_text(
        """
        [
          {
            "id": "2222222222",
            "ownerUsername": "account_a",
            "shortCode": "ABC123",
            "url": "https://www.instagram.com/p/ABC123/",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "type": "Video",
            "productType": "clips",
            "caption": "POV: you found the study buddy",
            "videoViewCount": 1000,
            "videoPlayCount": 2500,
            "likesCount": 120,
            "commentsCount": 9
          },
          {
            "id": "9999999999",
            "ownerUsername": "account_b",
            "shortCode": "XYZ999",
            "url": "https://www.instagram.com/p/XYZ999/",
            "timestamp": "2026-01-02T00:00:00.000Z",
            "type": "Video",
            "productType": "clips",
            "caption": "Well?",
            "videoViewCount": 3000,
            "videoPlayCount": 5000,
            "likesCount": 200,
            "commentsCount": 12
          }
        ]
        """,
        encoding="utf-8",
    )

    imported = import_apify_metrics(conn, [apify_path], top_limit=2, output_dir=tmp_path / "apify")
    top = top_public_posts(conn, limit=2)
    prompts = generate_prompt_cards(conn, limit=2, output_dir=tmp_path / "apify")
    learning = export_learning_set(conn, limit=2, output_dir=tmp_path / "learning")

    assert imported["imported"] == 2
    assert imported["exactLocalMatches"] == 1
    assert top["items"][0]["shortCode"] == "XYZ999"
    assert top["items"][1]["matchType"] == "exact_media_id"
    assert prompts["count"] == 2
    assert prompts["cards"][0]["generationPrompt"]["goal"].startswith("create an original reel")
    assert learning["count"] == 2
    assert learning["exactLocalMatches"] == 1
    assert Path(learning["manifestPath"]).exists()
    assert Path(learning["promptCardsPath"]).exists()


def test_pattern_analyzer_labels_top_posts_and_exports_cards(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, account, file_name, extension, kind,
          size_bytes, mtime, path_hash, created_at, updated_at
        )
        VALUES (
          'ref_local', '/examples/account_a/account_a_1111111111_2222222222_3333333333.mp4',
          'account_a', 'mirror_fitcheck_1111111111_2222222222_3333333333.mp4',
          '.mp4', 'video', 100, 'now', 'hash', 'now', 'now'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO video_probes (
          reference_id, valid, duration_seconds, width, height, fps,
          codec, aspect_ratio, rotation, probe_json, probed_at
        )
        VALUES ('ref_local', 1, 8, 1080, 1920, 30, 'h264', 0.5625, 0, '{}', 'now')
        """
    )
    apify_path = tmp_path / "apify.json"
    apify_path.write_text(
        """
        [
          {
            "id": "2222222222",
            "ownerUsername": "account_a",
            "shortCode": "ABC123",
            "url": "https://www.instagram.com/p/ABC123/",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "type": "Video",
            "productType": "clips",
            "caption": "POV: mirror fit check?",
            "videoViewCount": 100000,
            "videoPlayCount": 250000,
            "likesCount": 12000,
            "commentsCount": 900
          }
        ]
        """,
        encoding="utf-8",
    )
    import_apify_metrics(conn, [apify_path], top_limit=1)

    analyzed = analyze_patterns(conn, limit=1, provider="heuristic", output_dir=tmp_path / "learning")
    summary = pattern_summary(conn, limit=1)
    exported = export_patterns(conn, limit=1, output_dir=tmp_path / "learning")
    applied = apply_pattern_labels(conn, limit=1)

    row = conn.execute("SELECT * FROM reference_patterns").fetchone()
    assert analyzed["analyzed"] == 1
    assert row["suggested_label"] == "gold"
    assert row["visual_format"] == "mirror_selfie"
    assert row["hook_type"] == "viewer_insert"
    assert summary["summary"]["suggestedLabels"]["gold"] == 1
    assert exported["count"] == 1
    assert Path(exported["jsonlPath"]).exists()
    assert applied["applied"] == 1
    assert conn.execute("SELECT label FROM review_labels WHERE reference_id = 'ref_local'").fetchone()["label"] == "gold"


def test_public_post_ranking_prefers_measured_prompt_outcomes(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    for idx, (media_id, account) in enumerate((("2222222222", "small_account"), ("9999999999", "huge_account")), start=1):
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, account, file_name, extension, kind,
              size_bytes, mtime, path_hash, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, '.mp4', 'video', 100, 'now', ?, 'now', 'now')
            """,
            (
                f"ref_{idx}",
                f"/examples/{account}/{account}_1111111111_{media_id}_3333333333.mp4",
                account,
                f"clip_1111111111_{media_id}_3333333333.mp4",
                f"hash_{idx}",
            ),
        )
        conn.execute(
            """
            INSERT INTO generated_video_prompts (
              id, reference_id, target_tool, model_profile, prompt_json, status, created_at, updated_at
            )
            VALUES (?, ?, 'higgsfield', 'default', '{}', 'draft', 'now', 'now')
            """,
            (f"prompt_{idx}", f"ref_{idx}"),
        )
    apify_path = tmp_path / "apify.json"
    apify_path.write_text(
        """
        [
          {"id":"2222222222","ownerUsername":"small_account","shortCode":"LOWRAW","url":"https://instagram.com/p/LOWRAW/","caption":"POV: try this","videoPlayCount":1000,"videoViewCount":900,"likesCount":80,"commentsCount":3,"ownerFollowersCount":200},
          {"id":"9999999999","ownerUsername":"huge_account","shortCode":"HIGHRAW","url":"https://instagram.com/p/HIGHRAW/","caption":"POV: try this","videoPlayCount":1000000,"videoViewCount":900000,"likesCount":8000,"commentsCount":30,"ownerFollowersCount":5000000}
        ]
        """,
        encoding="utf-8",
    )
    import_apify_metrics(conn, [apify_path], top_limit=2)

    imported = import_prompt_outcomes(
        conn,
        [
            {"referenceId": "ref_1", "rewardScore": 1.8, "confidence": 0.82, "sampleCount": 4},
            {"referenceId": "ref_2", "rewardScore": 0.4, "confidence": 0.76, "sampleCount": 8},
        ],
    )
    top = top_public_posts(conn, limit=2)

    assert imported["updated"] == 2
    assert top["items"][0]["shortCode"] == "LOWRAW"
    assert top["items"][0]["measuredOutcome"]["rewardScore"] == 1.8
    assert top["items"][0]["publicRateScore"] > top["items"][1]["publicRateScore"]


def test_pattern_analyzer_embeds_measured_outcome_signals(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    conn.execute(
        """
        INSERT INTO source_files (
          reference_id, path, account, file_name, extension, kind,
          size_bytes, mtime, path_hash, created_at, updated_at
        )
        VALUES (
          'ref_local', '/examples/account_a/account_a_1111111111_2222222222_3333333333.mp4',
          'account_a', 'mirror_fitcheck_1111111111_2222222222_3333333333.mp4',
          '.mp4', 'video', 100, 'now', 'hash', 'now', 'now'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO video_probes (
          reference_id, valid, duration_seconds, width, height, fps,
          codec, aspect_ratio, rotation, probe_json, probed_at
        )
        VALUES ('ref_local', 1, 8, 1080, 1920, 30, 'h264', 0.5625, 0, '{}', 'now')
        """
    )
    conn.execute(
        """
        INSERT INTO generated_video_prompts (
          id, reference_id, target_tool, model_profile, prompt_json, status, created_at, updated_at
        )
        VALUES ('prompt_1', 'ref_local', 'higgsfield', 'default', '{}', 'draft', 'now', 'now')
        """
    )
    apify_path = tmp_path / "apify.json"
    apify_path.write_text(
        """
        [
          {"id":"2222222222","ownerUsername":"account_a","shortCode":"ABC123","url":"https://instagram.com/p/ABC123/","caption":"POV: mirror fit check?","videoPlayCount":10000,"videoViewCount":9000,"likesCount":500,"commentsCount":20}
        ]
        """,
        encoding="utf-8",
    )
    import_apify_metrics(conn, [apify_path], top_limit=1)
    import_prompt_outcomes(conn, [{"referenceId": "ref_local", "rewardScore": 1.35, "confidence": 0.7, "sampleCount": 3}])

    analyzed = analyze_patterns(conn, limit=1, provider="heuristic", output_dir=tmp_path / "learning")
    row = conn.execute("SELECT pattern_json FROM reference_patterns").fetchone()
    pattern = json.loads(row["pattern_json"])

    assert analyzed["analyzed"] == 1
    assert pattern["metrics"]["measuredOutcome"]["rewardScore"] == 1.35
    assert pattern["metrics"]["measuredOutcome"]["sampleCount"] == 3


def test_tiktok_archive_imports_slideshow_references_and_patterns(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    archive = tmp_path / "tiktok"
    appdata = archive / "data" / ".appdata"
    author_dir = archive / "data" / "Following" / "author123"
    videos_dir = author_dir / "videos"
    covers_dir = author_dir / "covers"
    appdata.mkdir(parents=True)
    videos_dir.mkdir(parents=True)
    covers_dir.mkdir(parents=True)
    (videos_dir / "video456.mp4").write_bytes(b"fake video bytes")
    (covers_dir / "video456.jpg").write_bytes(b"fake cover bytes")
    write_archive_db(appdata / "db_authors.js", "dba_base64", {"author123": {"uniqueIds": ["slide_creator"], "nickname": "Slide Creator"}})
    write_archive_db(appdata / "db_videos.js", "dbv_base64", {"video456": {"authorId": "author123", "createTime": 1768000000, "playCount": 123456, "diggCount": 9000}})
    write_archive_db(appdata / "db_texts.js", "dbt_base64", {"video456": "POV: swipe to see the answer"})

    imported = import_tiktok_archive(conn, archive, top_limit=1, output_dir=tmp_path / "tiktok_out")
    top = top_public_posts(conn, limit=1)
    analyzed = analyze_patterns(conn, limit=1, provider="heuristic", output_dir=tmp_path / "learning")
    built = build_learning_system(conn, limit=1, output_dir=tmp_path / "learning")
    summary = learning_summary(conn, limit=1)

    source = conn.execute("SELECT * FROM source_files").fetchone()
    post = conn.execute("SELECT * FROM public_posts").fetchone()
    pattern = conn.execute("SELECT * FROM reference_patterns").fetchone()
    cluster = built["summary"]["visualFormats"]
    assert imported["videosImported"] == 1
    assert source["account"] == "slide_creator"
    assert post["short_code"] == "tiktok_video456"
    assert post["product_type"] == "tiktok_slideshow_reference"
    assert top["items"][0]["rawJson"]["sourceFormat"] == "slideshow"
    assert analyzed["analyzed"] == 1
    assert pattern["visual_format"] == "tiktok_slideshow"
    assert cluster["tiktok_slideshow"] == 1
    assert built["summary"]["topClusterLabels"][0].startswith("tiktok slideshow")
    assert summary["topClusters"][0]["suggestedFormats"][0] == "slideshow"


def test_audio_patterns_extract_native_sound_recommendations(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    conn.execute(
        """
        INSERT INTO public_posts (
          id, owner_username, short_code, url, caption, product_type, post_type,
          video_view_count, video_play_count, likes_count, comments_count,
          match_type, raw_json, imported_at
        )
        VALUES (
          'post_audio', 'account_a', 'AUD1', 'https://instagram.com/p/AUD1/',
          'Do I look different?', 'clips', 'Video', 1000, 2000, 100, 5,
          'external_only',
          '{"musicInfo":{"audio_id":"123","song_name":"Pretty Girl Era (Sped Up)","artist_name":"LU KALA","uses_original_audio":false}}',
          'now'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO reference_patterns (
          id, public_post_id, rank, provider, analyzer_version, suggested_label,
          visual_format, hook_type, caption_archetype, quality_score,
          pattern_json, created_at, updated_at
        )
        VALUES (
          'pattern_audio', 'post_audio', 1, 'heuristic', 'test', 'gold',
          'caption_led_visual', 'direct_response', 'question_hook', 90,
          '{}', 'now', 'now'
        )
        """
    )

    signal = extract_audio_signal(
        {"musicInfo": {"audio_id": "123", "song_name": "Pretty Girl Era (Sped Up)", "artist_name": "LU KALA", "uses_original_audio": False}},
        "clips",
    )
    result = analyze_audio_patterns(conn, limit=10, output_dir=tmp_path / "learning")

    row = conn.execute("SELECT * FROM audio_patterns").fetchone()
    assert signal["audioVibe"] == "sped_up_pop"
    assert result["audioPatternCount"] == 1
    assert row["audio_title"] == "Pretty Girl Era (Sped Up)"
    assert row["usage_type"] == "platform_sound"
    assert json.loads(row["recommendation_json"])["nativeAudioPreferred"] is True


def test_competitor_audio_leaderboard_ranks_similar_creator_sounds(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    rows = [
        (
            "post_a",
            "ai_model_a",
            "A1",
            "https://instagram.com/p/A1/",
            "ai model fit check",
            12000,
            900,
            '{"musicInfo":{"audio_id":"ig_hot","song_name":"Runway Heat","artist_name":"DJ A","uses_original_audio":false}}',
        ),
        (
            "post_b",
            "ai_model_b",
            "B1",
            "https://instagram.com/p/B1/",
            "ofm creator reel",
            9000,
            700,
            '{"musicInfo":{"audio_id":"ig_hot","song_name":"Runway Heat","artist_name":"DJ A","uses_original_audio":false}}',
        ),
        (
            "post_c",
            "food_creator",
            "C1",
            "https://instagram.com/p/C1/",
            "recipe tutorial",
            50000,
            3000,
            '{"musicInfo":{"audio_id":"ig_food","song_name":"Kitchen Song","artist_name":"Chef","uses_original_audio":false}}',
        ),
    ]
    for row in rows:
        conn.execute(
            """
            INSERT INTO public_posts (
              id, owner_username, short_code, url, caption, product_type, post_type,
              video_view_count, video_play_count, likes_count, comments_count,
              match_type, raw_json, imported_at
            )
            VALUES (?, ?, ?, ?, ?, 'clips', 'Video', ?, ?, ?, 0, 'external_only', ?, 'now')
            """,
            (row[0], row[1], row[2], row[3], row[4], row[5], row[5], row[6], row[7]),
        )
    output_path = tmp_path / "competitor_audio.json"
    result = competitor_audio_leaderboard(
        conn,
        platform="instagram",
        accounts=["ai_model_a", "ai_model_b"],
        caption_keywords=["ai", "ofm"],
        min_posts=2,
        output_path=output_path,
    )

    assert result["schema"] == "reference_factory.competitor_audio_leaderboard.v1"
    assert result["count"] == 1
    assert result["items"][0]["audioId"] == "ig_hot"
    assert result["items"][0]["postCount"] == 2
    assert result["items"][0]["accountCount"] == 2
    assert result["items"][0]["totalPlays"] == 21000
    assert output_path.exists()


def test_audio_catalog_csv_import_list_export_and_recommend(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    csv_path = tmp_path / "audio.csv"
    csv_path.write_text(
        "\n".join([
            "title,artist,platform,native_audio_id,native_audio_url,mood_tags,best_content_types,account_fit,bpm,energy,trend_status,usage_count,safe_usage_notes,expires_at",
            "Runway Pop,DJ A,instagram,ig_1,https://instagram.com/audio/1,glam|confident,fit_check|reel,model_a,124,8,rising,120000,attach natively,2099-01-01T00:00:00+00:00",
            "Sleepy Song,DJ B,instagram,ig_2,https://instagram.com/audio/2,chill,tutorial,model_b,80,2,stale,500,old trend,2000-01-01T00:00:00+00:00",
        ]),
        encoding="utf-8",
    )

    imported = import_audio_csv(conn, csv_path)
    listed = list_audio_catalog(conn, platform="instagram", fresh_only=True)
    recommended = recommend_audio(conn, platform="instagram", content_tags=["fit_check", "glam"], account_tags=["model_a"], limit=2)
    export_path = tmp_path / "audio_export.json"
    exported = export_audio_catalog(conn, export_path)

    assert imported["imported"] == 2
    assert listed["count"] == 1
    assert listed["items"][0]["title"] == "Runway Pop"
    assert recommended["recommendations"][0]["audioTitle"] == "Runway Pop"
    assert recommended["recommendations"][0]["confidence"] > recommended["recommendations"][1]["confidence"]
    assert exported["count"] == 2
    assert export_path.exists()


def test_import_example_reel_audio_creates_campaign_factory_ready_feed(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    reels_path = tmp_path / "example_reels.json"
    export_path = tmp_path / "audio_memory.json"
    reels_path.write_text(json.dumps({
        "items": [
            {
                "platform": "instagram",
                "sourceReelUrl": "https://www.instagram.com/reel/CLEAN/",
                "audioTitle": "Mirror Walk Trend",
                "artistName": "Creator Sound",
                "nativeAudioId": "ig_audio_clean",
                "nativeAudioUrl": "https://www.instagram.com/reels/audio/ig_audio_clean/",
                "creatorAccount": "ofm_model_a",
                "views": 450000,
                "likes": 38000,
                "contentTags": "mirror,glam,ofm_reels",
            },
            {
                "platform": "instagram",
                "sourceReelUrl": "https://www.instagram.com/reel/UNRESOLVED/",
                "creatorAccount": "ofm_model_b",
                "views": 90000,
            },
        ],
    }), encoding="utf-8")

    result = import_example_reel_audio(conn, reels_path, export_path=export_path)
    again = import_example_reel_audio(conn, reels_path, export_path=export_path)
    listed = list_audio_catalog(conn, platform="instagram", limit=10)
    exported = json.loads(export_path.read_text(encoding="utf-8"))

    assert result["imported"] == 2
    assert result["unresolved"] == 1
    assert again["imported"] == 2
    assert listed["count"] == 2
    assert exported["schema"] == "reference_factory.audio_catalog_export.v1"
    clean = next(item for item in exported["items"] if item["nativeAudioId"] == "ig_audio_clean")
    unresolved = next(item for item in exported["items"] if item["nativeAudioId"].startswith("example_"))
    assert clean["trendScore"] == 84.0
    assert clean["creatorFitScore"] == 0.9
    assert clean["trendSources"] == ["reference_factory_example_reels"]
    assert clean["performanceSummary"]["views"] == 450000
    assert clean["exampleReels"][0]["url"] == "https://www.instagram.com/reel/CLEAN/"
    assert unresolved["resolved"] is False
    assert "missing_resolved_title" in unresolved["reviewReasons"]


def test_scrape_instagram_audio_extracts_public_page_metadata(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    export_path = tmp_path / "ig_audio_export.json"
    html = """
    <html><script>
    {"musicInfo":{"audio_id":"123456789","song_name":"IG Winner Sound","artist_name":"Trend Artist","uses_original_audio":false},
     "ownerUsername":"creator_a","video_play_count":550000}
    </script></html>
    """

    result = scrape_instagram_audio(
        conn,
        urls=["https://www.instagram.com/reel/ABC/"],
        export_path=export_path,
        fetcher=lambda url: html,
    )
    exported = json.loads(export_path.read_text(encoding="utf-8"))

    assert result["requested"] == 1
    assert result["imported"] == 1
    item = exported["items"][0]
    assert item["title"] == "IG Winner Sound"
    assert item["nativeAudioId"] == "123456789"
    assert item["nativeAudioUrl"] == "https://www.instagram.com/reels/audio/123456789/"
    assert item["exampleReels"][0]["url"] == "https://www.instagram.com/reel/ABC/"


def test_scrape_instagram_audio_prefers_stored_reference_music_info(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    now = "2026-06-01T00:00:00+00:00"
    conn.execute(
        """
        INSERT INTO public_posts (
          id, owner_username, short_code, url, timestamp, product_type, post_type,
          caption, video_view_count, video_play_count, likes_count, comments_count,
          display_url, video_url, match_type, reference_id, local_path, raw_json, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "post_ig_cache",
            "creator_cache",
            "CACHE123",
            "https://www.instagram.com/p/CACHE123/",
            now,
            "clips",
            "Video",
            "cached winner",
            100000,
            250000,
            9000,
            40,
            None,
            None,
            "external_only",
            None,
            None,
            json.dumps({
                "musicInfo": {
                    "audio_id": "cached_audio_1",
                    "song_name": "Cached IG Sound",
                    "artist_name": "Cached Artist",
                    "uses_original_audio": False,
                }
            }),
            now,
        ),
    )
    conn.commit()

    result = scrape_instagram_audio(
        conn,
        urls=["https://www.instagram.com/p/CACHE123/"],
        fetcher=lambda url: (_ for _ in ()).throw(AssertionError("should not fetch public HTML when cache has musicInfo")),
    )
    listed = list_audio_catalog(conn, platform="instagram")

    assert result["imported"] == 1
    assert result["unresolved"] == 0
    assert listed["items"][0]["title"] == "Cached IG Sound"
    assert listed["items"][0]["nativeAudioId"] == "cached_audio_1"
    assert listed["items"][0]["nativeAudioUrl"] == "https://www.instagram.com/reels/audio/cached_audio_1/"


def test_scrape_instagram_audio_keeps_unresolved_rows_when_public_page_blocks_metadata(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)

    result = scrape_instagram_audio(
        conn,
        urls=["https://www.instagram.com/reel/BLOCKED/"],
        fetcher=lambda url: "<html>login wall</html>",
    )
    review = review_audio_catalog(conn, platform="instagram")

    assert result["imported"] == 1
    assert result["unresolved"] == 1
    assert review["items"][0]["nativeAudioId"].startswith("example_")
    assert "missing_resolved_title" in review["items"][0]["reviewReasons"]


def test_audio_catalog_import_reports_missing_required_fields(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    csv_path = tmp_path / "bad_audio.csv"
    csv_path.write_text("title,platform\n,instagram\nNo Platform,\n", encoding="utf-8")

    result = import_audio_csv(conn, csv_path)

    assert result["imported"] == 0
    assert len(result["errors"]) == 2


def test_audio_catalog_review_queue_flags_stale_and_missing_fields(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    csv_path = tmp_path / "audio_review.csv"
    csv_path.write_text(
        "\n".join([
            "title,platform,native_audio_id,native_audio_url,mood_tags,best_content_types,trend_status,expires_at",
            "Fresh Ready,instagram,ig_ready,https://instagram.com/audio/ready,glam,reel,rising,2099-01-01T00:00:00+00:00",
            "Old Trend,instagram,ig_old,https://instagram.com/audio/old,glam,reel,fading,2000-01-01T00:00:00+00:00",
            "Needs Tags,instagram,,,,,rising,2099-01-01T00:00:00+00:00",
        ]),
        encoding="utf-8",
    )
    import_audio_csv(conn, csv_path)

    review = review_audio_catalog(conn, platform="instagram")
    reasons_by_title = {item["title"]: item["reviewReasons"] for item in review["items"]}

    assert "Fresh Ready" not in reasons_by_title
    assert "trend_status:fading" in reasons_by_title["Old Trend"]
    assert "expired" in reasons_by_title["Old Trend"]
    assert "missing_native_locator" in reasons_by_title["Needs Tags"]
    assert "missing_mood_tags" in reasons_by_title["Needs Tags"]
    assert "missing_content_tags" in reasons_by_title["Needs Tags"]


def test_audio_catalog_upsert_record_supports_manual_ui_entry(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    saved = upsert_audio_record(conn, {
        "title": "Manual Trend",
        "artistName": "Creator",
        "platform": "instagram",
        "nativeAudioId": "ig_manual",
        "moodTags": "glam,fit_check",
        "trendStatus": "rising",
    })
    listed = list_audio_catalog(conn, platform="instagram")

    assert saved["item"]["title"] == "Manual Trend"
    assert listed["items"][0]["nativeAudioId"] == "ig_manual"
    assert listed["items"][0]["moodTags"] == ["glam", "fit_check"]


def test_audio_trend_snapshots_are_manual_history_and_update_catalog(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    saved = upsert_audio_record(conn, {
        "title": "Manual Trend",
        "platform": "instagram",
        "nativeAudioId": "ig_manual",
        "moodTags": "glam",
        "bestContentTypes": "reel",
        "trendStatus": "rising",
        "usageCount": 1000,
    })

    snapshot = upsert_audio_trend_snapshot(conn, {
        "audioCatalogId": saved["item"]["id"],
        "observedAt": "2026-05-22T10:00:00+00:00",
        "trendStatus": "fading",
        "usageCount": 2500,
        "saturationScore": 0.91,
        "velocityScore": -0.3,
        "curator": "operator",
        "source": "manual platform review",
        "notes": "Watch for overuse",
    })
    listed = list_audio_trend_snapshots(conn, audio_catalog_id=saved["item"]["id"])
    catalog = list_audio_catalog(conn, platform="instagram")
    review = review_audio_catalog(conn, platform="instagram")

    assert snapshot["item"]["audioTitle"] == "Manual Trend"
    assert listed["count"] == 1
    assert catalog["items"][0]["trendStatus"] == "fading"
    assert catalog["items"][0]["usageCount"] == 2500
    assert catalog["items"][0]["latestTrendSnapshot"]["saturationScore"] == 0.91
    assert "trend_status:fading" in review["items"][0]["reviewReasons"]
    assert "high_saturation" in review["items"][0]["reviewReasons"]


def test_audio_snapshot_csv_import_matches_existing_catalog_record(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    upsert_audio_record(conn, {
        "title": "CSV Trend",
        "platform": "instagram",
        "nativeAudioId": "ig_csv",
        "moodTags": "glam",
        "bestContentTypes": "reel",
    })
    csv_path = tmp_path / "snapshots.csv"
    csv_path.write_text(
        "\n".join([
            "platform,native_audio_id,observed_at,trend_status,usage_count,saturation_score,velocity_score,source",
            "instagram,ig_csv,2026-05-22T11:00:00+00:00,trending,9000,0.4,0.8,manual review",
            "instagram,missing,2026-05-22T11:00:00+00:00,trending,1,0.1,0.1,manual review",
        ]),
        encoding="utf-8",
    )

    imported = import_audio_snapshot_csv(conn, csv_path)
    recommended = recommend_audio(conn, platform="instagram", content_tags=["glam"], limit=1)

    assert imported["imported"] == 1
    assert len(imported["errors"]) == 1
    assert recommended["recommendations"][0]["latestTrendSnapshot"]["velocityScore"] == 0.8


def test_audio_catalog_flags_generic_tiktok_titles_until_resolved(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    upsert_audio_record(conn, {
        "title": "TikTok audio 123",
        "platform": "tiktok",
        "nativeAudioId": "123",
        "nativeAudioUrl": "https://www.tiktok.com/@creator/video/1",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "rising",
    })

    review = review_audio_catalog(conn, platform="tiktok")
    resolved = resolve_audio_record(conn, {
        "platform": "tiktok",
        "nativeAudioId": "123",
        "title": "Real Sound Name",
        "artistName": "Creator",
        "nativeAudioUrl": "https://www.tiktok.com/music/123",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "rising",
        "safeUsageNotes": "Attach natively.",
    })
    review_after = review_audio_catalog(conn, platform="tiktok")

    assert "missing_resolved_title" in review["items"][0]["reviewReasons"]
    assert resolved["item"]["title"] == "Real Sound Name"
    assert review_after["count"] == 0


def test_audio_resolution_shortlist_prioritizes_unresolved_tiktok_sounds(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    upsert_audio_record(conn, {
        "title": "TikTok audio 111",
        "platform": "tiktok",
        "nativeAudioId": "111",
        "nativeAudioUrl": "https://www.tiktok.com/@creator/video/111",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "current",
        "usageCount": 10,
        "exampleReels": "https://www.tiktok.com/@creator/video/111",
    })
    upsert_audio_record(conn, {
        "title": "TikTok audio 222",
        "platform": "tiktok",
        "nativeAudioId": "222",
        "nativeAudioUrl": "https://www.tiktok.com/@creator/video/222",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "rising",
        "usageCount": 1000,
        "exampleReels": "https://www.tiktok.com/@creator/video/222",
    })
    upsert_audio_record(conn, {
        "title": "Resolved Sound",
        "platform": "tiktok",
        "nativeAudioId": "333",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "rising",
        "usageCount": 5000,
    })

    shortlist = audio_resolution_shortlist(conn, platform="tiktok", limit=1)

    assert shortlist["unresolvedTotal"] == 2
    assert shortlist["items"][0]["nativeAudioId"] == "222"
    assert shortlist["items"][0]["exampleUrl"] == "https://www.tiktok.com/@creator/video/222"
    assert "--native-audio-id 222" in shortlist["items"][0]["resolveCommand"]


def test_audio_csv_refresh_preserves_manual_resolution_fields(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    first = tmp_path / "first.csv"
    first.write_text(
        "\n".join([
            "title,artist,platform,native_audio_id,native_audio_url,mood_tags,best_content_types,account_fit,trend_status,usage_count,safe_usage_notes",
            "TikTok audio 123,creator,tiktok,123,https://www.tiktok.com/@creator/video/1,glowup,slideshow,creator,rising,1000,auto",
        ]),
        encoding="utf-8",
    )
    refresh = tmp_path / "refresh.csv"
    refresh.write_text(
        "\n".join([
            "title,artist,platform,native_audio_id,native_audio_url,mood_tags,best_content_types,account_fit,trend_status,usage_count,safe_usage_notes",
            "TikTok audio 123,creator,tiktok,123,https://www.tiktok.com/@creator/video/2,dance,reel,creator,fresh,2000,auto refresh",
        ]),
        encoding="utf-8",
    )
    import_audio_csv(conn, first)
    resolve_audio_record(conn, {
        "platform": "tiktok",
        "nativeAudioId": "123",
        "title": "Manual Title",
        "artistName": "Manual Artist",
        "moodTags": "manual_tag",
        "bestContentTypes": "manual_content",
        "accountFit": "manual_account",
        "trendStatus": "rising",
        "safeUsageNotes": "manual notes",
    })

    import_audio_csv(conn, refresh, preserve_manual_fields=True)
    listed = list_audio_catalog(conn, platform="tiktok")

    item = listed["items"][0]
    assert item["title"] == "Manual Title"
    assert item["artistName"] == "Manual Artist"
    assert item["moodTags"] == ["manual_tag"]
    assert item["bestContentTypes"] == ["manual_content"]
    assert item["safeUsageNotes"] == "manual notes"
    assert item["usageCount"] == 2000
    assert item["trendStatus"] == "fresh"


def test_audio_catalog_health_counts_ready_unresolved_and_stale(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    upsert_audio_record(conn, {
        "title": "TikTok audio 123",
        "platform": "tiktok",
        "nativeAudioId": "123",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "rising",
    })
    upsert_audio_record(conn, {
        "title": "Resolved Sound",
        "platform": "tiktok",
        "nativeAudioId": "456",
        "moodTags": "glowup",
        "bestContentTypes": "slideshow",
        "trendStatus": "fading",
    })

    health = audio_catalog_health(conn, platform="tiktok")

    assert health["total"] == 2
    assert health["unresolvedTitles"] == 1
    assert health["stale"] == 1
    assert health["fresh"] == 1


def test_tiktok_audio_leaderboard_rows_convert_to_catalog_import(tmp_path: Path) -> None:
    payload = {
        "items": [
            {
                "audioId": "aud_1",
                "audioTitle": "TikTok audio aud_1",
                "artistName": "creator",
                "audioVibe": "trending_slideshow_sound",
                "postCount": 1,
                "totalPlays": 150000,
                "medianPlays": 150000,
                "score": 300000,
                "accounts": ["creator"],
                "examples": [
                    {
                        "url": "https://www.tiktok.com/@creator/video/1",
                        "caption": "story of my life #glowup",
                    }
                ],
            }
        ]
    }

    rows = leaderboard_to_catalog_rows(payload)

    assert rows[0]["platform"] == "tiktok"
    assert rows[0]["native_audio_id"] == "aud_1"
    assert rows[0]["trend_status"] == "rising"
    assert "glowup" in rows[0]["mood_tags"]
    assert "attach natively" in rows[0]["safe_usage_notes"].lower()


def write_archive_db(path: Path, var_name: str, value: dict[str, object]) -> None:
    payload = base64.b64encode(gzip.compress(json.dumps(value).encode("utf-8"))).decode("ascii")
    path.write_text(f'window.{var_name}="{payload}";', encoding="utf-8")


def test_learning_system_builds_clusters_playbook_and_campaign_bank(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    for idx in range(3):
        ref = f"ref_{idx}"
        media_id = f"222222222{idx}"
        conn.execute(
            """
            INSERT INTO source_files (
              reference_id, path, account, file_name, extension, kind,
              size_bytes, mtime, path_hash, created_at, updated_at
            )
            VALUES (?, ?, 'account_a', ?, '.mp4', 'video', 100, 'now', ?, 'now', 'now')
            """,
            (
                ref,
                f"/examples/account_a/account_a_1111111111_{media_id}_3333333333.mp4",
                f"mirror_fitcheck_1111111111_{media_id}_3333333333.mp4",
                f"hash_{idx}",
            ),
        )
        conn.execute(
            """
            INSERT INTO video_probes (
              reference_id, valid, duration_seconds, width, height, fps,
              codec, aspect_ratio, rotation, probe_json, probed_at
            )
            VALUES (?, 1, 8, 1080, 1920, 30, 'h264', 0.5625, 0, '{}', 'now')
            """,
            (ref,),
        )
    apify_path = tmp_path / "apify.json"
    apify_path.write_text(
        """
        [
          {"id":"2222222220","ownerUsername":"account_a","shortCode":"A0","url":"https://instagram.com/p/A0/","caption":"POV: mirror fit check?","videoPlayCount":10000,"videoViewCount":9000,"likesCount":500,"commentsCount":20},
          {"id":"2222222221","ownerUsername":"account_a","shortCode":"A1","url":"https://instagram.com/p/A1/","caption":"POV: mirror fit check?","videoPlayCount":9000,"videoViewCount":8000,"likesCount":400,"commentsCount":18},
          {"id":"2222222222","ownerUsername":"account_a","shortCode":"A2","url":"https://instagram.com/p/A2/","caption":"well?","videoPlayCount":8000,"videoViewCount":7000,"likesCount":300,"commentsCount":12}
        ]
        """,
        encoding="utf-8",
    )
    import_apify_metrics(conn, [apify_path], top_limit=3)
    analyze_patterns(conn, limit=3, provider="heuristic", output_dir=tmp_path / "learning")

    built = build_learning_system(conn, limit=3, output_dir=tmp_path / "learning")
    summary = learning_summary(conn, limit=3)

    assert built["references"] == 3
    assert built["clusters"] >= 1
    assert Path(built["playbookMarkdownPath"]).exists()
    assert Path(built["promptPackJsonlPath"]).exists()
    assert Path(built["campaignReferenceBankPath"]).exists()
    bank = json.loads(Path(built["campaignReferenceBankPath"]).read_text(encoding="utf-8"))
    assert "suggestedFormats" in bank["clusters"][0]
    assert conn.execute("SELECT COUNT(*) FROM learning_clusters").fetchone()[0] >= 1
    assert summary["summary"]["referenceCount"] == 3
