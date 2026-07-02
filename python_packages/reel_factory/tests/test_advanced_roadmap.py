import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_visual_qc import record_from_scores, sample_positions
from asset_prompt_contract import (
    AssetPromptSet,
    build_grok_simple_prompt,
    parse_asset_prompt_response,
    write_prompt_template,
)
from audio_intent import write_audio_intent
from audio_mux import audio_id, output_path_for
from campaign_store import (
    add_reference,
    campaign_leaderboard,
    create_campaign,
    next_batch_plan,
    record_asset_generation,
    record_prompt_run,
    retry_helper_direction,
    validate_generation_soul,
)
from campaign_store import (
    connect as campaign_connect,
)
from campaign_store import (
    rate_output as store_rate_output,
)
from caption_generation_log import (
    caption_library,
    rank_clip_sidecar,
    score_caption_quality,
)
from caption_render import render_caption_png
from embedding_index import duplicate_risk, upsert_embedding
from embedding_index import similar as similar_media
from embedding_provider import HashEmbeddingProvider
from generate_assets import (
    AssetGenerationPlan,
    HiggsfieldCommandError,
    _six_pack_prompts,
    build_image_cmd,
    build_source_lineage,
    create_image_asset,
    detect_grid_status,
    dry_run,
    extract_url,
    image_identity_flag,
    probe_higgsfield_capabilities,
    resolve_generation_models,
    validate_required_capabilities,
)
from generate_prompts import (
    HIGGSFIELD_REFERENCE_PROMPT_MODE,
    REFERENCE_FACTORY_SEXY_REALISTIC_MODE,
    build_direct_higgsfield_prompt_instruction,
    build_higgsfield_reference_prompt_instruction,
    build_user_instruction,
    build_xai_payload,
    clean_direct_higgsfield_prompt,
    clean_direct_higgsfield_prompt_text,
    compile_prompt_contract,
    extract_first_visible_frame,
    frame_is_visible,
    generate_prompt,
    normalize_grid_layout,
    normalize_motion_analysis,
    parse_direct_higgsfield_prompt_response,
    parse_prompt_text,
    prompt_drift_report,
    response_text,
    scene_json_to_higgsfield_prompt,
    strip_json_fence,
)
from graph_builder import build_ffmpeg_cmd
from hook_ai import (
    generate_hooks,
    parse_hook_response,
    validate_hook_variant,
    validate_hook_variants,
)
from hook_tools import (
    find_semantic_duplicates,
    reindex_hook_library,
    save_hook_to_library,
)
from intelligence_store import (
    confidence_for_sample_size,
    data_quality_score,
    low_data_warning,
    validate_review,
    winner_score,
)
from manifest import Manifest
from metrics_store import import_metrics_csv, import_outcomes_csv, outcomes_summary
from placement_scorer import score_lanes
from qc_check import _parse_psnr, _parse_ssim, probe_with_audio_mode
from readiness_check import evaluate_output, run_readiness
from reel_gui import (
    auto_hooks_api,
    clip_status_from_evidence,
    dashboard_summary_api,
    next_action_for_status,
    queue_threadsdashboard_post,
    save_photo_post_asset,
)
from reel_pipeline import Recipe
from reel_url_import import download_reel_url
from reference_analyzer import (
    analyze_reference,
    build_analysis_instruction,
    normalize_analysis,
)
from render_plan import RenderPlan
from render_queue import RenderQueue
from safe_zone import score_safe_zone
from thumbnail_gen import thumbnail_path_for
from winner_dna import (
    account_fatigue_report,
    assign_experiment,
    baseline_vs_recommended_report,
    cost_analytics,
    decision_log,
    experiment_report,
    persist_recommendation_decision,
    record_cost,
    refresh_winner_dna,
    upsert_reel_feature,
    winner_dna_leaderboard,
)

REEL_ROOT = Path(__file__).resolve().parents[1]


class AdvancedRoadmapTests(unittest.TestCase):
    def test_asset_prompt_contract_accepts_simple_json_only(self):
        parsed = parse_asset_prompt_response(
            json.dumps(
                {
                    "higgsfieldGridPrompt": "2x3 grid, adult glamour outfit variations",
                    "klingMotionPrompt": "subtle confident turn toward camera",
                    "notes": "use best panel",
                }
            )
        )
        self.assertEqual(
            parsed.higgsfieldGridPrompt, "2x3 grid, adult glamour outfit variations"
        )
        self.assertEqual(parsed.notes, "use best panel")

    def test_asset_prompt_contract_rejects_negative_prompt_field(self):
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            parse_asset_prompt_response(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "2x3 grid, adult glamour outfit variations",
                        "klingMotionPrompt": "subtle confident turn toward camera",
                        "negative_prompt": "bad hands",
                    }
                )
            )

    def test_asset_prompt_contract_rejects_negative_higgsfield_language(self):
        rejected = [
            "2x3 grid with no text",
            "2x3 grid, avoid bad hands",
            "2x3 grid without artifacts",
            "2x3 grid, do not include extra limbs",
            "2x3 grid with bad hands fixed",
            "2x3 grid with extra limbs removed",
            "2x3 grid with warped face corrected",
        ]
        for prompt in rejected:
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(ValueError, "rejected v1 language"):
                    parse_asset_prompt_response(
                        json.dumps(
                            {
                                "higgsfieldGridPrompt": prompt,
                                "klingMotionPrompt": "subtle confident turn toward camera",
                            }
                        )
                    )

    def test_asset_prompt_contract_rejects_identity_language_in_final_prompts(self):
        rejected = [
            (
                "2x3 grid using the trained identity",
                "subtle confident turn toward camera",
            ),
            ("2x3 grid with long layered hair", "subtle confident turn toward camera"),
            ("2x3 grid with curly hairstyle", "subtle confident turn toward camera"),
            (
                "2x3 grid, adult glamour outfit variations",
                "keep identity stable during motion",
            ),
        ]
        for image_prompt, motion_prompt in rejected:
            with self.subTest(image_prompt=image_prompt, motion_prompt=motion_prompt):
                with self.assertRaisesRegex(ValueError, "rejected v1 language"):
                    parse_asset_prompt_response(
                        json.dumps(
                            {
                                "higgsfieldGridPrompt": image_prompt,
                                "klingMotionPrompt": motion_prompt,
                            }
                        )
                    )

    def test_asset_prompt_contract_allows_generic_panel_consistency_language(self):
        parsed = parse_asset_prompt_response(
            json.dumps(
                {
                    "higgsfieldGridPrompt": (
                        "Create one high-quality native 2x3 grid featuring six variations of the same adult woman "
                        "with consistent body proportions, deep cleavage, skin-tight fabric cling, bright lighting, and same camera framing"
                    ),
                    "klingMotionPrompt": "subtle confident turn toward camera",
                }
            )
        )
        self.assertIn("consistent body proportions", parsed.higgsfieldGridPrompt)
        self.assertIn("deep cleavage", parsed.higgsfieldGridPrompt)

    def test_asset_prompt_contract_rejects_face_polish_language_in_final_prompts(self):
        rejected_terms = [
            "perfect face",
            "freckles",
            "photorealistic skin texture",
            "natural sheen",
            "skin sheen",
            "high detail",
            "sharp focus",
        ]
        for term in rejected_terms:
            with self.subTest(term=term):
                with self.assertRaisesRegex(ValueError, "rejected v1 language"):
                    parse_asset_prompt_response(
                        json.dumps(
                            {
                                "higgsfieldGridPrompt": f"2x3 grid, adult glamour pose, deep cleavage, {term}",
                                "klingMotionPrompt": "subtle confident turn toward camera",
                            }
                        )
                    )

    def test_asset_prompt_contract_rejects_caption_overlay_and_platform_language(self):
        rejected = [
            (
                "2x3 grid with caption overlay hook",
                "subtle confident turn toward camera",
            ),
            ("2x3 grid with big text at bottom", "subtle confident turn toward camera"),
            (
                "2x3 grid with on-screen text question",
                "subtle confident turn toward camera",
            ),
            ("2x3 grid based on the text hook", "subtle confident turn toward camera"),
            (
                "2x3 grid with Instagram interface crop",
                "subtle confident turn toward camera",
            ),
            (
                "2x3 grid, adult glamour outfit variations",
                "social-media style motion clip",
            ),
            (
                "2x3 grid, adult glamour outfit variations",
                "keep UI buttons outside the frame",
            ),
        ]
        for image_prompt, motion_prompt in rejected:
            with self.subTest(image_prompt=image_prompt, motion_prompt=motion_prompt):
                with self.assertRaisesRegex(ValueError, "rejected v1 language"):
                    parse_asset_prompt_response(
                        json.dumps(
                            {
                                "higgsfieldGridPrompt": image_prompt,
                                "klingMotionPrompt": motion_prompt,
                            }
                        )
                    )

    def test_asset_prompt_set_has_no_legacy_prompt_aliases(self):
        parsed = AssetPromptSet(
            higgsfieldGridPrompt="2x3 grid, adult glamour outfit variations",
            klingMotionPrompt="subtle confident turn toward camera",
        )
        self.assertFalse(hasattr(parsed, "image_prompt"))
        self.assertFalse(hasattr(parsed, "video_prompt"))
        self.assertFalse(hasattr(parsed, "negative_prompt"))

    def test_asset_prompt_contract_rejects_legacy_compiler_shape(self):
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            parse_asset_prompt_response(
                json.dumps(
                    {
                        "soul_id_2x3_prompt": "2x3 grid prompt",
                        "kling_video_prompt": "motion prompt",
                        "kling_negative_prompt": "bad anatomy",
                        "structured_breakdown": {},
                        "confidence_score": 88,
                    }
                )
            )

    def test_grok_simple_prompt_documents_only_clean_fields(self):
        prompt = build_grok_simple_prompt("mirror selfie reference", "red dress")
        self.assertIn('"higgsfieldGridPrompt"', prompt)
        self.assertIn('"klingMotionPrompt"', prompt)
        self.assertNotIn('"negative_prompt"', prompt)
        self.assertIn("mirror selfie reference", prompt)
        self.assertNotIn("confidence_score", prompt)
        self.assertNotIn("Pose fidelity outranks body emphasis", prompt)
        self.assertNotIn("framing, body proportions, and camera feel", prompt)
        self.assertIn("Deterministic compiler only", prompt)
        self.assertIn("Output exactly one standalone Higgsfield Soul ID prompt", prompt)
        self.assertIn("one shared Kling motion prompt", prompt)
        self.assertIn("accepted 9:16 start image", prompt)
        self.assertIn("safety boundaries for no text/logos", prompt)
        self.assertNotIn("Animate the best panel", prompt)
        self.assertNotIn("best frame", prompt)
        self.assertNotIn("JSON-style creative brief", prompt)
        self.assertNotIn("house body style", prompt)
        self.assertNotIn("body-fire glamour", prompt)
        self.assertNotIn("cleavage-forward", prompt)

    def test_retry_helpers_preserve_reference_while_amplifying_body(self):
        self.assertIn(
            "larger pushed-up breasts",
            retry_helper_direction("more_reference_fidelity"),
        )
        self.assertIn(
            "deep cleavage", retry_helper_direction("more_reference_fidelity")
        )
        self.assertIn(
            "larger pushed-up full breasts",
            retry_helper_direction("more_body_emphasis"),
        )
        self.assertIn(
            "deep plunging cleavage as the focal point",
            retry_helper_direction("more_body_emphasis"),
        )
        self.assertIn("curvier frame", retry_helper_direction("more_body_emphasis"))
        self.assertIn("deep plunging cleavage", retry_helper_direction("more_cleavage"))

    def test_higgsfield_rejection_writes_failure_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_path = root / "prompt.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "2x3 grid",
                        "klingMotionPrompt": "motion",
                    }
                ),
                encoding="utf-8",
            )
            plan = AssetGenerationPlan(
                prompt_json=prompt_path,
                stem="clip_001",
                reference=None,
                soul_id="soul_123",
                soul_name="Stacey",
                start_image=None,
                out_dir=root / "project_data" / "generated_assets",
                source_dir=root / "00_source_videos",
            )
            err = HiggsfieldCommandError(
                ["higgsfield", "generate", "create"], 1, "", "rejected by provider"
            )
            with (
                patch(
                    "generate_assets.ensure_required_capabilities",
                    return_value={"schema": "cap", "createdAt": 1},
                ),
                patch(
                    "generate_assets._cost_preflight_for_plan",
                    return_value={
                        "allowed": True,
                        "blockingReason": "",
                        "blockingReasons": [],
                    },
                ),
                patch("generate_assets._run_json", side_effect=err),
            ):
                result = create_image_asset(plan)
            self.assertFalse(result["ok"])
            lineage_path = Path(result["path"])
            self.assertTrue(lineage_path.exists())
            lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
            self.assertEqual(
                lineage["generation"]["status"], "generation_rejected_or_failed"
            )
            self.assertEqual(lineage["generation"]["failure"]["stage"], "image_create")
            self.assertIn(
                "rejected by provider", lineage["generation"]["failure"]["stderrTail"]
            )

    def test_higgsfield_cost_preflight_blocks_paid_image_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_path = root / "prompt.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "reference image still",
                        "klingMotionPrompt": "motion",
                    }
                ),
                encoding="utf-8",
            )
            plan = AssetGenerationPlan(
                prompt_json=prompt_path,
                stem="clip_cost",
                reference=None,
                soul_id="soul_123",
                soul_name="Stacey",
                start_image=None,
                out_dir=root / "project_data" / "generated_assets",
                source_dir=root / "00_source_videos",
            )

            with (
                patch(
                    "generate_assets.ensure_required_capabilities",
                    return_value={"schema": "cap", "createdAt": 1},
                ),
                patch(
                    "generate_assets._cost_preflight_for_plan",
                    return_value={
                        "allowed": False,
                        "blockingReason": "budget_policy_missing",
                        "blockingReasons": ["budget_policy_missing"],
                    },
                ),
                patch("generate_assets._run_json") as run_json,
            ):
                result = create_image_asset(plan)

            self.assertFalse(result["ok"])
            run_json.assert_not_called()
            lineage = result["lineage"]
            self.assertEqual(lineage["generation"]["status"], "cost_preflight_blocked")
            self.assertEqual(
                lineage["generation"]["failure"]["stage"], "cost_preflight"
            )
            self.assertEqual(
                lineage["generation"]["costPreflight"]["blockingReason"],
                "budget_policy_missing",
            )

    def test_active_image_asset_lineage_does_not_call_deprecated_grid_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt_path = root / "prompt.json"
            prompt_path.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "reference image still",
                        "klingMotionPrompt": "motion",
                    }
                ),
                encoding="utf-8",
            )
            plan = AssetGenerationPlan(
                prompt_json=prompt_path,
                stem="clip_single",
                reference=None,
                soul_id="5828d958-91dd-4d6d-8909-934503f47644",
                soul_name="Stacey",
                start_image=None,
                out_dir=root / "project_data" / "generated_assets",
                source_dir=root / "00_source_videos",
            )
            capabilities = {
                "schema": "cap",
                "createdAt": 1,
                "imageModels": [
                    {"job_set_type": "soul_2", "parameters": [{"name": "soul_id"}]}
                ],
                "videoModels": [{"job_set_type": "kling3_0"}],
            }

            with (
                patch(
                    "generate_assets.ensure_required_capabilities",
                    return_value=capabilities,
                ),
                patch(
                    "generate_assets._cost_preflight_for_plan",
                    return_value={
                        "allowed": True,
                        "blockingReason": "",
                        "blockingReasons": [],
                    },
                ),
                patch(
                    "generate_assets._run_json",
                    return_value={"id": "img_1", "url": "https://example.test/img.png"},
                ),
                patch(
                    "generate_assets.validate_generation_soul",
                    return_value={"status": "valid"},
                ),
                patch(
                    "generate_assets.detect_grid_status",
                    side_effect=AssertionError("deprecated grid detection called"),
                ),
            ):
                result = create_image_asset(plan, wait=True, download=False)

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["lineage"]["generation"]["grid"]["status"], "single_image_layout"
            )
            self.assertFalse(result["lineage"]["generation"]["grid"]["isGrid"])

    def test_first_visible_frame_selector_skips_black_frames(self):
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "ref.mp4"
            video.write_bytes(b"fake")
            out_dir = root / "frames"
            calls = {"n": 0}

            def fake_run(cmd, check, stdout, stderr, timeout):
                calls["n"] += 1
                out = Path(cmd[-1])
                out.parent.mkdir(parents=True, exist_ok=True)
                im = Image.new("RGB", (80, 80), "black" if calls["n"] == 1 else "white")
                if calls["n"] > 1:
                    ImageDraw.Draw(im).rectangle([0, 0, 39, 79], fill="gray")
                im.save(out)

            with (
                patch("generate_prompts.video_duration", return_value=1.0),
                patch("generate_prompts.subprocess.run", side_effect=fake_run),
            ):
                result = extract_first_visible_frame(
                    video, out_dir, max_scan_seconds=1.0, step_seconds=0.5
                )

            self.assertEqual(result, out_dir / "reference_00_first_visible.jpg")
            self.assertGreaterEqual(calls["n"], 2)
            self.assertTrue(frame_is_visible(result))

    def test_grid_detection_flags_single_image_and_square_grid(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            single = root / "single.png"
            grid = root / "grid.png"
            Image.new("RGB", (1344, 2016), "white").save(single)
            Image.new("RGB", (1800, 1800), "white").save(grid)

            with patch.dict(
                os.environ,
                {
                    "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                    "REEL_FACTORY_ENV": "test",
                },
                clear=True,
            ):
                self.assertEqual(
                    detect_grid_status(single)["status"], "single_image_or_invalid_grid"
                )
                self.assertEqual(detect_grid_status(grid)["status"], "native_2x3_grid")

    def test_capability_probe_validates_required_models(self):
        payload = {
            "imageModels": [{"job_set_type": "text2image_soul_v2"}],
            "videoModels": [{"job_set_type": "kling3_0"}],
        }
        self.assertTrue(validate_required_capabilities(payload)["ok"])
        payload["videoModels"] = []
        self.assertEqual(
            validate_required_capabilities(payload)["missing"], ["kling3_0"]
        )

    def test_capability_resolver_prefers_current_soul_model_and_identity_flag(self):
        payload = {
            "imageModels": [
                {
                    "job_set_type": "text2image_soul_v2",
                    "parameters": [{"name": "custom_reference_id"}],
                },
                {"job_set_type": "soul_2", "parameters": [{"name": "soul_id"}]},
            ],
            "videoModels": [{"job_set_type": "kling3_0"}],
        }
        resolved = resolve_generation_models(payload)
        self.assertEqual(resolved["imageModel"], "soul_2")
        self.assertEqual(resolved["videoModel"], "kling3_0")
        self.assertEqual(resolved["imageIdentityFlag"], "--soul_id")
        self.assertEqual(image_identity_flag(payload, "soul_2"), "--soul_id")

    def test_capability_resolver_falls_back_to_legacy_soul_param(self):
        payload = {
            "imageModels": [
                {
                    "job_set_type": "text2image_soul_v2",
                    "parameters": [{"name": "custom_reference_id"}],
                }
            ],
            "videoModels": [{"job_set_type": "kling3_0"}],
        }
        resolved = resolve_generation_models(payload)
        self.assertEqual(resolved["imageModel"], "text2image_soul_v2")
        self.assertEqual(resolved["imageIdentityFlag"], "--custom_reference_id")

    def test_capability_probe_writes_cache(self):
        image_rows = [{"job_set_type": "text2image_soul_v2", "type": "image"}]
        video_rows = [{"job_set_type": "kling3_0", "type": "video"}]

        def fake_run_json(cmd):
            if "--image" in cmd:
                return {"items": image_rows}
            if "--video" in cmd:
                return {"items": video_rows}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch("generate_assets._run_json", side_effect=fake_run_json),
                patch("generate_assets._run_text", return_value="help text"),
            ):
                result = probe_higgsfield_capabilities(root, force=True)

            self.assertTrue(result["validation"]["ok"])
            self.assertTrue(
                (root / "project_data" / "higgsfield_capabilities.json").exists()
            )

    def test_grok_api_prompt_instruction_matches_clean_contract(self):
        instruction = build_user_instruction(
            "reference reel frames", "tight blue dress"
        )
        self.assertIn("standalone Higgsfield Soul ID prompt", instruction)
        self.assertIn("one shared Kling motion prompt", instruction)
        self.assertIn("accepted 9:16 start image", instruction)
        self.assertIn("deterministic enhancement profile", instruction)
        self.assertIn("tight blue dress", instruction)
        self.assertIn('"higgsfieldGridPrompt"', instruction)

    def test_grok_api_payload_uses_image_inputs_and_store_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "frame.jpg"
            img.write_bytes(b"fakejpg")

            payload = build_xai_payload(
                model="grok-4.3", frames=[img], instruction="make prompt"
            )

            self.assertFalse(payload["store"])
            parts = payload["input"][0]["content"]
            self.assertEqual(parts[0]["type"], "input_text")
            self.assertEqual(parts[1]["type"], "input_image")
            self.assertTrue(parts[1]["image_url"].startswith("data:image/jpeg;base64,"))

    def test_grok_response_text_and_json_fence_parsing(self):
        payload = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '```json\n{"higgsfieldGridPrompt":"grid","klingMotionPrompt":"motion","notes":"ok"}\n```',
                        }
                    ],
                }
            ],
        }

        parsed = parse_asset_prompt_response(strip_json_fence(response_text(payload)))

        self.assertEqual(parsed.higgsfieldGridPrompt, "grid")
        self.assertEqual(parsed.klingMotionPrompt, "motion")

    def test_grok_prompt_parser_repairs_raw_newlines_in_json_strings(self):
        raw = '{"higgsfieldGridPrompt":"grid line one\nline two","klingMotionPrompt":"motion","notes":"ok"}'

        parsed = parse_prompt_text(raw)

        self.assertIn("line two", parsed.higgsfieldGridPrompt)

    def test_generate_prompt_non_dry_run_still_refuses_to_write_prompt_contract(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "ref.jpg"
            Image.new("RGB", (64, 64), "white").save(ref)

            with patch("generate_prompts.call_grok") as grok:
                with self.assertRaisesRegex(
                    RuntimeError, "dry-run prompt JSON creation only"
                ):
                    generate_prompt(
                        out_path=root / "prompt.json",
                        root=root,
                        reference_images=[ref],
                        dry_run=False,
                    )
                grok.assert_not_called()

            grok.assert_not_called()
            self.assertFalse((root / "prompt.json").exists())

    def test_asset_prompt_contract_writes_empty_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts" / "clip_001_grok.json"

            write_prompt_template(str(path))

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(data),
                ["higgsfieldGridPrompt", "klingMotionPrompt", "notes"],
            )

    def test_generate_assets_dry_run_builds_higgsfield_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "clip_001_grok.json"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "six panel soul id grid",
                        "klingMotionPrompt": "subtle camera motion",
                        "notes": "manual review",
                    }
                ),
                encoding="utf-8",
            )
            reference = root / "ref.png"
            reference.write_bytes(b"png")
            plan = AssetGenerationPlan(
                prompt_json=prompt,
                stem="clip_001",
                reference=str(reference),
                soul_id="5828d958-91dd-4d6d-8909-934503f47644",
                soul_name=None,
                start_image=None,
                out_dir=root / "00_source_videos",
                source_dir=root / "00_source_videos",
            )

            result = dry_run(plan, wait=True)
            commands = [" ".join(cmd) for cmd in result["commands"]]

            self.assertNotIn("higgsfield upload create", "\n".join(commands))
            self.assertIn("text2image_soul_v2", commands[0])
            self.assertIn(
                "--custom_reference_id 5828d958-91dd-4d6d-8909-934503f47644",
                commands[0],
            )
            self.assertIn("--aspect_ratio 9:16", commands[0])
            self.assertNotIn("--image", commands[0])
            self.assertIn("kling3_0", commands[1])
            self.assertIn("--wait", commands[1])

    def test_generate_assets_six_pack_dry_run_builds_six_soul_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "clip_001_grok.json"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "six panel soul id grid",
                        "klingMotionPrompt": "subtle camera motion",
                        "notes": "manual review",
                    }
                ),
                encoding="utf-8",
            )
            plan = AssetGenerationPlan(
                prompt_json=prompt,
                stem="clip_001",
                reference="upload_123",
                soul_id="5828d958-91dd-4d6d-8909-934503f47644",
                soul_name=None,
                start_image=None,
                out_dir=root / "00_source_videos",
                source_dir=root / "00_source_videos",
                image_mode="six-pack",
            )

            with patch.dict(
                os.environ,
                {
                    "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                    "REEL_FACTORY_ENV": "test",
                },
                clear=True,
            ):
                commands = [
                    " ".join(cmd) for cmd in dry_run(plan, wait=True)["commands"]
                ]
            image_commands = [cmd for cmd in commands if "text2image_soul_v2" in cmd]

            self.assertEqual(len(image_commands), 6)
            self.assertTrue(
                all(
                    "--custom_reference_id 5828d958-91dd-4d6d-8909-934503f47644" in cmd
                    for cmd in image_commands
                )
            )
            self.assertIn("Render only outfit variation 6", image_commands[-1])

    def test_deprecated_six_pack_path_raises_by_default(self):
        prompt = AssetPromptSet(
            higgsfieldGridPrompt="six panel soul id grid",
            klingMotionPrompt="subtle camera motion",
            notes="manual review",
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "six_pack is deprecated"):
                _six_pack_prompts(prompt)

    def test_deprecated_six_pack_path_allows_explicit_local_test_override(self):
        prompt = AssetPromptSet(
            higgsfieldGridPrompt="six panel soul id grid",
            klingMotionPrompt="subtle camera motion",
            notes="manual review",
        )
        with patch.dict(
            os.environ,
            {
                "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                "REEL_FACTORY_ENV": "test",
            },
            clear=True,
        ):
            self.assertEqual(len(_six_pack_prompts(prompt)), 6)

    def test_prod_env_blocks_deprecated_generators_even_with_allow_flag(self):
        prompt = AssetPromptSet(
            higgsfieldGridPrompt="six panel soul id grid",
            klingMotionPrompt="subtle camera motion",
            notes="manual review",
        )
        with patch.dict(
            os.environ,
            {
                "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                "REEL_FACTORY_ENV": "production",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "six_pack is deprecated"):
                _six_pack_prompts(prompt)

    def test_deprecated_raise_flag_still_blocks_generators(self):
        prompt = AssetPromptSet(
            higgsfieldGridPrompt="six panel soul id grid",
            klingMotionPrompt="subtle camera motion",
            notes="manual review",
        )
        with patch.dict(
            os.environ,
            {
                "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                "REEL_FACTORY_ENV": "test",
                "REEL_FACTORY_RAISE_ON_DEPRECATED_GENERATORS": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "six_pack is deprecated"):
                _six_pack_prompts(prompt)

    def test_deprecated_grok_reference_analysis_returns_controlled_api_error_by_default(
        self,
    ):
        import reel_gui

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Exception) as ctx:
                reel_gui.analyze_reference_api(
                    {"reference": "ref.png", "model": "grok-4.3"}
                )
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertIn(
            "grok_reference_analysis is deprecated", str(ctx.exception.detail)
        )

    def test_reference_analysis_requires_explicit_model(self):
        import reel_gui

        with self.assertRaises(Exception) as ctx:
            reel_gui.analyze_reference_api({"reference": "ref.png"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "model is required")

    def test_deprecated_grok_reference_analysis_allows_explicit_local_test_override(
        self,
    ):
        import reel_gui

        with (
            patch.dict(
                os.environ,
                {
                    "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                    "REEL_FACTORY_ENV": "test",
                },
                clear=True,
            ),
            patch.object(reel_gui, "_resolve_project_path", return_value="ref.png"),
            patch.object(
                reel_gui, "analyze_reference", return_value={"ok": True}
            ) as analyze,
        ):
            result = reel_gui.analyze_reference_api(
                {"reference": "ref.png", "model": "grok-4.3"}
            )

        self.assertEqual(result, {"ok": True})
        analyze.assert_called_once()

    def test_generate_assets_image_command_requires_soul_identity_param(self):
        prompt = parse_asset_prompt_response(
            json.dumps(
                {
                    "higgsfieldGridPrompt": "grid",
                    "klingMotionPrompt": "motion",
                    "notes": "ok",
                }
            )
        )

        cmd = build_image_cmd(
            prompt,
            reference="pose_upload",
            soul_id="5828d958-91dd-4d6d-8909-934503f47644",
            wait=True,
        )

        self.assertIn("--custom_reference_id", cmd)
        self.assertIn("5828d958-91dd-4d6d-8909-934503f47644", cmd)
        self.assertIn("--image", cmd)

    def test_generate_assets_dry_run_respects_plan_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "clip_001_grok.json"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid",
                        "klingMotionPrompt": "motion",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            plan = AssetGenerationPlan(
                prompt_json=prompt,
                stem="clip_001",
                reference="upload_123",
                soul_id="soul_123",
                soul_name=None,
                start_image=None,
                out_dir=root / "00_source_videos",
                source_dir=root / "00_source_videos",
                image_model="soul_2",
                video_model="seedance_2_0",
            )

            commands = dry_run(plan, wait=True)["commands"]

            self.assertEqual(commands[0][3], "soul_2")
            self.assertEqual(commands[1][3], "seedance_2_0")

    def test_generate_assets_dry_run_passes_video_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "clip_001_grok.json"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "single creator start frame",
                        "klingMotionPrompt": "match source reel pacing",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            ref = root / "reference_reel.mp4"
            ref.write_bytes(b"video")
            plan = AssetGenerationPlan(
                prompt_json=prompt,
                stem="clip_001",
                reference="upload_123",
                soul_id="soul_123",
                soul_name=None,
                start_image="<image_job_id>",
                video_reference=str(ref),
                out_dir=root / "00_source_videos",
                source_dir=root / "00_source_videos",
                video_model="seedance_2_0",
            )

            commands = dry_run(plan, wait=True)["commands"]

            self.assertEqual(commands[1][3], "seedance_2_0")
            self.assertIn("--video", commands[1])
            self.assertIn(str(ref), commands[1])
            self.assertNotIn("--sound", commands[1])

    def test_failed_generation_does_not_extract_nested_media_url(self):
        response = {
            "items": [
                {
                    "id": "vid_1",
                    "status": "failed",
                    "result_url": "",
                    "params": {
                        "medias": [
                            {
                                "data": {
                                    "url": "https://example.test/start-image.png",
                                },
                            }
                        ],
                    },
                }
            ],
        }

        self.assertIsNone(extract_url(response))

    def test_campaign_schema_and_creator_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = campaign_connect(Path(tmp))
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in {
                "creators",
                "campaigns",
                "campaign_references",
                "prompt_runs",
                "asset_generations",
                "operator_ratings",
                "campaign_outputs",
            }:
                self.assertIn(table, tables)
            stacey = conn.execute(
                "SELECT * FROM creators WHERE name='Stacey'"
            ).fetchone()
            self.assertEqual(stacey["soul_id"], "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36")

    def test_campaign_prompt_asset_rating_and_next_batch_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_campaign(
                root,
                name="Test Campaign",
                creator="Stacey",
                account="acct",
                platform="instagram_reels",
            )
            ref = root / "ref.mp4"
            ref.write_bytes(b"video")
            add_reference(
                root, campaign="Test Campaign", source_path=ref, visual_tags=["mirror"]
            )
            prompt_path = root / "prompt.json"
            prompt_fields = {
                "higgsfieldGridPrompt": "grid prompt",
                "klingMotionPrompt": "motion prompt",
                "notes": "ok",
            }
            prompt_path.write_text(json.dumps(prompt_fields), encoding="utf-8")
            prompt_rec = record_prompt_run(
                root,
                campaign="Test Campaign",
                creator="Stacey",
                prompt_json_path=prompt_path,
                model="grok-test",
                prompt_fields=prompt_fields,
            )
            lineage = {
                "source": {"stem": "clip_001"},
                "generation": {
                    "soulId": "5828d958-91dd-4d6d-8909-934503f47644",
                    "uploadId": "upload",
                    "imageJobId": "image",
                    "imageResultUrl": "https://example.test/image.png",
                    "videoJobId": "video",
                    "videoResultUrl": "https://example.test/video.mp4",
                    "params": {},
                    "raw": {
                        "image": {
                            "params": {
                                "custom_reference_id": "5828d958-91dd-4d6d-8909-934503f47644"
                            }
                        }
                    },
                },
                "assets": {"localPaths": {}},
            }
            asset_rec = record_asset_generation(
                root,
                campaign="Test Campaign",
                creator="Stacey",
                prompt_json_path=prompt_path,
                stem="clip_001",
                lineage_path=root / "lineage.json",
                lineage=lineage,
            )
            out = root / "out.mp4"
            out.write_bytes(b"mp4")
            rating = store_rate_output(
                root,
                output_path=out,
                campaign="Test Campaign",
                asset_generation_id=asset_rec["asset_generation_id"],
                scores={
                    "identity": 5,
                    "pose": 2,
                    "taste": 3,
                    "artifacts": 2,
                    "motion": 4,
                },
                labels=["pose_drift", "hand_bad"],
            )
            board = campaign_leaderboard(root, campaign="Test Campaign")
            plan = next_batch_plan(root, campaign="Test Campaign", count=2)
            before_persist = decision_log(root, campaign="Test Campaign")
            persisted_plan = next_batch_plan(
                root, campaign="Test Campaign", count=1, persist=True
            )
            logged = decision_log(root, campaign="Test Campaign")
            self.assertTrue(prompt_rec["prompt_run_id"])
            self.assertEqual(asset_rec["identity"]["status"], "valid")
            self.assertTrue(rating["rating_id"])
            self.assertIn("hand_bad", plan["ideas"][0]["avoid_labels"])
            self.assertIn("data_quality", plan["ideas"][0]["recommendation"])
            self.assertEqual(before_persist["decisions"], [])
            self.assertTrue(persisted_plan["decision_id"])
            self.assertEqual(
                logged["decisions"][0]["decision_id"], persisted_plan["decision_id"]
            )
            self.assertTrue(board["worst_failure_patterns"])

    def test_outcome_import_links_variation_campaign_output_and_legacy_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            src.write_bytes(b"src")
            out = (
                root
                / "02_processed"
                / "clip_001"
                / "clip_001_h00_v01_original_deadbeef.mp4"
            )
            out.parent.mkdir(parents=True)
            out.write_bytes(b"video")
            manifest.upsert_video("clip_001", src, "hash", 2.0)
            manifest.add_variation(
                "clip_001",
                Recipe("v01_original"),
                "wait for it",
                out,
                "job_1",
                2.0,
            )
            manifest.conn.commit()
            csv_path = root / "outcomes.csv"
            csv_path.write_text(
                "filename,platform,account,posted_at,views,likes,comments,shares,saves,watch_time,retention_rate,profile_visits,follows,manual_score,source_url,notes\n"
                f"{out.name},instagram_reels,acct,2026-05-28,100,4,2,3,5,12.5,0.61,7,2,,https://example.test/reel,winner\n",
                encoding="utf-8",
            )

            result = import_outcomes_csv(root, csv_path)
            summary = outcomes_summary(root)
            row = manifest.conn.execute(
                "SELECT * FROM reel_outcomes WHERE filename=?", (out.name,)
            ).fetchone()
            legacy = manifest.conn.execute(
                "SELECT * FROM publish_metrics WHERE filename=?", (out.name,)
            ).fetchone()
            campaign_output = manifest.conn.execute(
                "SELECT * FROM campaign_outputs WHERE metrics_filename=?", (out.name,)
            ).fetchone()

            self.assertEqual(result["imported"], 1)
            self.assertEqual(row["output_path"], str(out))
            self.assertEqual(row["job_key"], "job_1")
            self.assertEqual(row["watch_time"], 12.5)
            self.assertEqual(row["source_url"], "https://example.test/reel")
            self.assertEqual(legacy["views"], 100)
            self.assertIsNotNone(campaign_output)
            self.assertEqual(summary["top"][0]["filename"], out.name)

    def test_old_metrics_import_still_works_after_intelligence_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            src = root / "clip_001.mp4"
            src.write_bytes(b"src")
            out = (
                root
                / "02_processed"
                / "clip_001"
                / "clip_001_h01_v01_original_deadbeef.mp4"
            )
            out.parent.mkdir(parents=True)
            out.write_bytes(b"video")
            manifest.upsert_video("clip_001", src, "hash", 2.0)
            manifest.add_variation(
                "clip_001", Recipe("v01_original"), "hook", out, "job_2", 2.0
            )
            manifest.conn.commit()
            csv_path = root / "metrics.csv"
            csv_path.write_text(
                "filename,platform,account,uploaded_at,views,likes,comments,shares,saves,manual_score,notes\n"
                f"{out.name},ig,acct,2026-05-28,10,1,0,0,0,,ok\n",
                encoding="utf-8",
            )

            result = import_metrics_csv(root, csv_path)

            self.assertEqual(result["imported"], 1)
            self.assertEqual(
                manifest.conn.execute(
                    "SELECT views FROM publish_metrics WHERE filename=?", (out.name,)
                ).fetchone()["views"],
                10,
            )

    def test_review_decision_reason_validation_and_positive_approve(self):
        self.assertEqual(
            validate_review("approve", "identity_good", ["pose_good"])[0], "approve"
        )
        with self.assertRaisesRegex(ValueError, "primary_reason is required"):
            validate_review("reject", None, [])
        with self.assertRaisesRegex(ValueError, "unknown review"):
            validate_review("maybe", "not_a_label", [])

    def test_reference_analysis_writes_schema_and_prompt_dry_run_uses_context(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            ref = root / "bathroom_mirror.png"
            Image.new("RGB", (1080, 1920), "white").save(ref)

            analysis = analyze_reference(root, ref, dry_run=True)
            fake_raw = {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "higgsfieldGridPrompt": (
                                            "Create one high-quality native 2x3 grid featuring six variations of the exact same stunning woman "
                                            "in a tight bathroom mirror selfie pose with strong curves, deep cleavage, skin-tight fabric cling, "
                                            "bright indoor lighting, consistent pose, and sharp photorealistic detail."
                                        )
                                    }
                                ),
                            }
                        ]
                    }
                ]
            }
            with (
                patch("generate_prompts.load_xai_api_key", return_value="key"),
                patch("generate_prompts.call_grok", return_value=fake_raw),
            ):
                prompt = generate_prompt(
                    out_path=root / "prompt.json",
                    root=root,
                    reference_images=[ref],
                    dry_run=True,
                )

            self.assertTrue(Path(analysis["path"]).exists())
            self.assertEqual(analysis["analysis"]["scene_type"], "bathroom_mirror")
            self.assertEqual(analysis["dimensions"]["width"], 1080)
            self.assertEqual(
                prompt["prompt_source"], "live_grok_direct_higgsfield_prompt"
            )
            self.assertIn("Reference analysis", prompt["instruction_preview"])

    def test_reference_analysis_malformed_grok_json_uses_heuristic_fallback(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            ref = root / "bathroom_mirror.png"
            Image.new("RGB", (1080, 1920), "white").save(ref)
            fake_raw = {
                "output": [
                    {"content": [{"type": "output_text", "text": "{not valid json"}]}
                ]
            }

            with (
                patch("reference_analyzer.load_xai_api_key", return_value="key"),
                patch("reference_analyzer.call_grok", return_value=fake_raw),
            ):
                analysis = analyze_reference(root, ref, dry_run=False)

            self.assertEqual(analysis["analysis"]["scene_type"], "bathroom_mirror")
            self.assertTrue(Path(analysis["path"]).exists())

    def test_grok_reference_analysis_instruction_allows_enhanced_visual_direction(self):
        instruction = build_analysis_instruction()

        self.assertIn("sexierVisualDirection", instruction)
        self.assertIn("visualEmphasisSignals", instruction)
        self.assertIn("enhancementSuggestions", instruction)
        self.assertIn("what should be made sexier", instruction)
        self.assertIn("structured JSON only", instruction)
        self.assertNotIn("higgsfieldGridPrompt", instruction)
        self.assertNotIn("klingMotionPrompt", instruction)
        self.assertNotIn("negative_prompt", instruction)
        self.assertNotIn("hook_type", instruction)
        self.assertIn("ignore all non-subject screen artifacts", instruction)
        self.assertNotIn("caption", instruction.lower())
        self.assertNotIn("overlay", instruction.lower())
        self.assertNotIn("ui", instruction.lower())
        self.assertNotIn("interface", instruction.lower())

    def test_reference_analysis_preserves_structured_enhanced_direction(self):
        normalized = normalize_analysis(
            {
                "baseVisualFormula": {
                    "outfit": "black fitted mini dress",
                    "garmentFit": "tight",
                },
                "viralVisualStructure": {
                    "framing": "centered chest-to-thigh vertical frame",
                    "cameraAngle": "slightly low front angle",
                },
                "sexierVisualDirection": {
                    "cleavage": "push deeper cleavage and fuller breasts",
                    "curves": "rounder ass, wider hips, tighter waist",
                },
                "visualEmphasisSignals": {
                    "necklineDepth": "low",
                    "garmentTightness": "very high",
                },
                "enhancementSuggestions": [
                    "stronger hourglass silhouette",
                    "tighter fabric cling",
                ],
                "motion_prompt_hint": "subtle hip sway and slow push-in",
            }
        )

        self.assertEqual(
            normalized["sexierVisualDirection"]["curves"],
            "rounder ass, wider hips, tighter waist",
        )
        self.assertEqual(
            normalized["visualEmphasisSignals"]["garmentTightness"], "very high"
        )
        self.assertIn("tighter fabric cling", normalized["enhancementSuggestions"])

    def test_reference_analysis_scrubs_caption_overlay_and_ui_values(self):
        normalized = normalize_analysis(
            {
                "baseVisualFormula": {
                    "core": "tight upper-body frame",
                    "caption": "source text overlay",
                    "platform": "instagram interface",
                },
                "viralVisualStructure": {
                    "hook": "caption overlay question",
                    "composition": "centered bodycon dress framing",
                },
                "visualEmphasisSignals": [
                    "cleavage",
                    "text overlay hook",
                    "fabric cling",
                ],
                "environment": "minimal room with UI buttons",
                "motion_prompt_hint": "caption stays centered",
            }
        )

        self.assertEqual(
            normalized["baseVisualFormula"], {"core": "tight upper-body frame"}
        )
        self.assertEqual(
            normalized["viralVisualStructure"],
            {"composition": "centered bodycon dress framing"},
        )
        self.assertEqual(
            normalized["visualEmphasisSignals"], ["cleavage", "fabric cling"]
        )
        self.assertEqual(normalized["environment"], "")
        self.assertEqual(normalized["motion_prompt_hint"], "")

    def test_gemini_motion_cleanup_preserves_motion_when_hair_phrase_appears(self):
        normalized = normalize_motion_analysis(
            {
                "camera_motion": "Static medium shot.",
                "subject_motion": (
                    "Subject stands centered, subtly sways hips, slowly raises hands to hips, "
                    "then lowers them. Towards the end, both hands raise to touch hair, then lower. "
                    "Head remains mostly still, facing forward with a slight smile. "
                    "Movement is slow and deliberate."
                ),
                "motion_prompt_hint": (
                    "A static medium shot of a subject standing centered, subtly swaying hips. "
                    "Hands slowly raise to hips, then lower. Towards the end, both hands raise "
                    "to touch hair, then lower. Head remains mostly still, facing forward with "
                    "a slight smile. The movement is slow and deliberate."
                ),
            }
        )

        prompt = compile_prompt_contract(
            reference_analysis=normalized
        ).klingMotionPrompt

        self.assertIn("Static medium shot", prompt)
        self.assertIn("subtly sways hips", prompt)
        self.assertIn("hands to hips", prompt)
        self.assertIn("near head", prompt)
        self.assertIn("slight smile", prompt)
        self.assertIn("slow and deliberate", prompt)
        self.assertNotIn("touch hair", prompt)
        self.assertNotIn("hair", prompt)
        self.assertNotEqual(
            prompt,
            "Animate each cropped panel as its own short vertical motion clip. "
            "Keep the selected panel framing, room, outfit feel, camera angle, lighting, "
            "and supplied start-image composition stable. Apply this motion pattern: Static medium shot.",
        )

    def test_gemini_motion_cleanup_minimally_rewrites_hair_motion_phrases(self):
        normalized = normalize_motion_analysis(
            {
                "camera_motion": "slow handheld push-in",
                "subject_motion": "hands to hair, hair movement, torso leans forward, hips shift right",
                "motion_prompt_hint": "loop-friendly pacing with a small expression change",
            }
        )

        joined = " ".join(normalized.values())

        self.assertIn("slow handheld push-in", joined)
        self.assertIn("hands near head", joined)
        self.assertIn("subtle head-area movement", joined)
        self.assertIn("torso leans forward", joined)
        self.assertIn("hips shift right", joined)
        self.assertIn("small expression change", joined)
        self.assertNotIn("hair", joined.lower())

    def test_gemini_motion_cleanup_rewrites_exact_hair_motion_cases(self):
        cases = [
            ("hands move through hair", "hands move near head"),
            ("hands moving through hair", "hands moving near head"),
            ("hands run through hair", "hands move near head"),
            ("raises both hands to touch her hair", "raises both hands near head"),
            ("raise both hands to touch hair", "raise both hands near head"),
            ("raises hands to touch hair", "raises hands near head"),
            ("hair blows in wind", "subtle wind movement around subject"),
            ("hair blowing in wind", "subtle wind movement around subject"),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                normalized = normalize_motion_analysis(
                    {
                        "camera_motion": "slow push-in camera move",
                        "subject_motion": raw,
                        "motion_prompt_hint": "looks down, smiles, looks back at camera",
                    }
                )
                joined = " ".join(normalized.values())

                self.assertIn("slow push-in camera move", joined)
                self.assertIn(expected, joined)
                self.assertIn("looks down, smiles, looks back at camera", joined)
                self.assertNotIn("hair", joined.lower())
                self.assertNotIn("head area blows in wind", joined.lower())
                self.assertNotIn("raise near head", joined.lower())

    def test_gemini_motion_cleanup_preserves_static_hold_without_generic_fallback(self):
        normalized = normalize_motion_analysis(
            {
                "camera_motion": "Static camera, no movement.",
                "subject_motion": "Subject is completely still, no body movement.",
                "motion_prompt_hint": "No motion.",
            }
        )

        prompt = compile_prompt_contract(
            reference_analysis=normalized
        ).klingMotionPrompt

        self.assertIn("Static camera", prompt)
        self.assertIn("locked framing", prompt)
        self.assertIn("still pose", prompt)
        self.assertIn("static hold", prompt)
        self.assertNotIn("subtle natural phone-camera movement", prompt)
        self.assertNotIn("no movement", prompt.lower())
        self.assertNotIn("no motion", prompt.lower())

    def test_reference_analysis_rejects_final_prompt_and_identity_fields(self):
        forbidden_payloads = [
            {"higgsfieldGridPrompt": "final image prompt"},
            {"klingMotionPrompt": "final motion prompt"},
            {"negative_prompt": "bad hands"},
            {"identityDescription": "blonde blue-eyed reference person"},
            {"hairColor": "blonde"},
            {"eyeColor": "blue"},
            {"ethnicity": "reference ethnicity"},
            {"tattoos": "small wrist tattoo"},
            {"hook_type": "text overlay question"},
            {"caption": "source caption"},
            {"textOverlay": "source overlay"},
            {"ui": "buttons"},
            {"interface": "platform chrome"},
            {"platform": "instagram"},
        ]

        for payload in forbidden_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(
                    ValueError, "unsupported Grok perception fields"
                ):
                    normalize_analysis(payload)

    def test_prompt_compiler_strips_caption_overlay_and_platform_fragments(self):
        prompt = compile_prompt_contract(
            reference_analysis={
                "outfit": "black strapless mini dress",
                "garmentFit": "second-skin fabric cling",
                "viralVisualStructure": {"hook": "caption overlay question"},
                "visualEmphasisSignals": ["cleavage", "text overlay hook", "hips"],
                "environment": "minimal room with interface buttons",
                "camera_motion": "static Instagram UI frame",
                "subject_motion": "slow hip sway",
                "motion_prompt_hint": "caption stays centered",
            }
        )

        joined = f"{prompt.higgsfieldGridPrompt}\n{prompt.klingMotionPrompt}".lower()
        self.assertIn("black strapless mini dress", joined)
        self.assertIn("slow hip sway", joined)
        self.assertNotIn("caption", joined)
        self.assertNotIn("overlay", joined)
        self.assertNotIn("hook", joined)
        self.assertNotIn("instagram", joined)
        self.assertNotIn("interface", joined)
        self.assertNotIn("ui", joined)
        self.assertNotIn("social-media", joined)
        self.assertNotIn("creator-reel", joined)

    def test_prompt_compiler_writes_natural_higgsfield_direction(self):
        prompt = compile_prompt_contract(
            reference_analysis={
                "outfit": {
                    "type": "strapless mini dress",
                    "color": "black",
                    "material": "stretch knit",
                },
                "garmentFit": {"fit": "bodycon tight", "cling": "high"},
                "garmentPlacement": {
                    "placement": "low strapless neckline, hem mid-thigh"
                },
                "pose": {"type": "shoulders angled forward, slight torso lean"},
                "framing": {"type": "tight vertical crop on torso and face"},
                "cameraAngle": {"angle": "slightly low eye-level"},
                "lighting": {"type": "soft frontal natural"},
                "environment": {"setting": "minimal indoor wall"},
                "visualEmphasisSignals": {
                    "cleavage": "deep",
                    "breasts": "prominent",
                    "ass": "partial",
                    "hips": "accentuated",
                    "waist": "cinched",
                    "thighs": "visible",
                    "fabric_cling": "high",
                    "silhouette": "hourglass",
                },
                "sexierVisualDirection": {
                    "enhancements": "deeper cleavage, tighter cling, stronger hourglass"
                },
                "enhancementSuggestions": [
                    "increase cleavage depth",
                    "fuller rounder breasts",
                    "tighter waist cinch",
                ],
            }
        )

        image_prompt = prompt.higgsfieldGridPrompt
        motion_prompt = prompt.klingMotionPrompt
        self.assertIn("Style the subject in", image_prompt)
        self.assertIn("bodycon tight fit with high fabric cling", image_prompt)
        self.assertIn("Pose and frame the image around", image_prompt)
        self.assertIn("full head and face visible", image_prompt)
        self.assertIn("Emphasize deep cleavage, prominent breasts", image_prompt)
        self.assertIn("subtle ass curve", image_prompt)
        self.assertNotIn("2x3", image_prompt)
        self.assertNotIn("grid", image_prompt.lower())
        self.assertNotIn("panel", image_prompt.lower())
        self.assertNotIn("cropped panel", motion_prompt.lower())
        self.assertNotIn("Push the enhanced direction toward", image_prompt)
        self.assertNotIn("Use the reference", image_prompt)
        self.assertNotIn(
            "deep, prominent, accentuated, cinched, visible, high, hourglass",
            image_prompt,
        )
        self.assertNotIn("bodycon tight, high", image_prompt)
        self.assertNotIn("partial ass", image_prompt)
        self.assertLessEqual(image_prompt.count("."), 5)
        self.assertLessEqual(image_prompt.lower().count("cleavage"), 1)
        self.assertLessEqual(image_prompt.lower().count("waist"), 1)
        self.assertLessEqual(image_prompt.lower().count("hip"), 1)
        self.assertLessEqual(image_prompt.lower().count("hourglass"), 1)
        self.assertNotIn("increase cleavage depth", image_prompt)
        self.assertNotIn("tighter waist cinch", image_prompt)
        self.assertNotIn("higher hip emphasis", image_prompt)

    def test_direct_higgsfield_instruction_uses_reference_factory_compiler_voice(self):
        instruction = build_direct_higgsfield_prompt_instruction("make it sexier")

        self.assertIn("Reference image/reel attached.", instruction)
        self.assertIn(
            "Create a high-quality image prompt for Higgsfield Soul V2.", instruction
        )
        self.assertIn("old structured prompts", instruction)
        self.assertIn("Create one high-quality native six-panel grid", instruction)
        self.assertIn("exactly three columns and two rows", instruction)
        self.assertIn("deep plunging cleavage", instruction)
        self.assertIn("extreme hourglass", instruction)
        self.assertIn("massive round plump juicy ass", instruction)
        self.assertIn("tiny cinched waist", instruction)
        self.assertIn("wide hips", instruction)
        self.assertIn("thick thighs", instruction)
        self.assertIn("vary only outfit color and material", instruction)
        self.assertIn("keep the same garment style/cut", instruction)
        self.assertIn(
            "detailed and descriptive like the old structured prompts", instruction
        )
        self.assertIn("strong arched back", instruction)
        self.assertIn("dramatic S-curve posture", instruction)
        self.assertIn('"image_prompt"', instruction)
        self.assertIn('"notes"', instruction)
        self.assertNotIn('"higgsfieldGridPrompt"', instruction)
        self.assertNotIn('"structured_breakdown"', instruction)
        self.assertNotIn('"klingMotionPrompt"', instruction)
        example_block = instruction.split("Example prompt style to imitate:", 1)[
            1
        ].lower()
        self.assertNotIn("perfect face", example_block)
        self.assertNotIn("skin texture", example_block)
        self.assertNotIn("skin sheen", example_block)
        self.assertNotIn("natural sheen", example_block)
        self.assertNotIn("high detail", example_block)
        self.assertNotIn("sharp focus", example_block)
        self.assertNotIn("face realism", example_block)

    def test_direct_higgsfield_instruction_supports_operator_grid_layouts_and_age(self):
        two_by_four = build_direct_higgsfield_prompt_instruction(
            "make it sexier", grid_layout="2x4"
        )

        self.assertIn("exactly two columns and four rows", two_by_four)
        self.assertIn("native eight-panel image", two_by_four)
        self.assertIn("eight variations", two_by_four)
        self.assertNotIn("exact age", two_by_four)

        single = build_direct_higgsfield_prompt_instruction(
            "make it sexier", grid_layout="single"
        )
        self.assertIn("standalone image", single)
        self.assertIn("one standalone image", single)
        self.assertNotIn("Outfit variations: 1.", single)

        parsed = normalize_grid_layout("3x2")
        self.assertEqual(parsed["columns"], 3)
        self.assertEqual(parsed["rows"], 2)
        self.assertEqual(parsed["panel_count"], 6)

    def test_higgsfield_reference_instruction_is_simple_single_image_request(self):
        instruction = build_higgsfield_reference_prompt_instruction(
            "make it more bedroom selfie"
        )

        self.assertIn("Make a prompt similar to this reference image", instruction)
        self.assertIn("Higgsfield with Soul ID", instruction)
        self.assertIn("get the pose down correctly", instruction)
        self.assertIn("Make sure the prompt is sexy", instruction)
        self.assertIn("Do not mention hair", instruction)
        self.assertIn("exactly one standalone image", instruction)
        self.assertIn('"image_prompt"', instruction)
        self.assertIn("make it more bedroom selfie", instruction)
        self.assertNotIn("2x3", instruction)
        self.assertNotIn("3x2", instruction)
        self.assertNotIn("six-panel", instruction.lower())
        self.assertNotIn('"higgsfieldGridPrompt"', instruction)

    def test_direct_higgsfield_parser_accepts_old_reference_factory_key_and_strips_face_polish(
        self,
    ):
        raw = json.dumps(
            {
                "soul_id_2x3_prompt": (
                    "Create one high-quality six-panel grid image, exactly three columns and two rows, featuring six variations "
                    "of the exact same stunning woman with long wavy red hair, blue eyes, freckles, and an extreme hourglass figure. "
                    "She sits on a gray couch in a bright apartment. Exact reference pose in all panels: seated three-quarter view, "
                    "one hand resting in her hair, soft smile. Strong body emphasis in every panel: deep cleavage, tiny waist, "
                    "wide hips, thick thighs, skin-tight fabric cling. Outfit variations: 1. Beige set 2. Black set 3. White set "
                    "4. Rose set 5. Charcoal set 6. Taupe set. Bright daylight, photorealistic skin texture with natural sheen, "
                    "consistent face and body proportions across all panels, high detail, sharp focus, vertical smartphone aesthetic."
                ),
                "structured_breakdown": {
                    "pose_lock": "seated three-quarter view",
                    "body_emphasis": "deep cleavage, tiny waist",
                    "outfit_variations": [
                        "beige",
                        "black",
                        "white",
                        "rose",
                        "charcoal",
                        "taupe",
                    ],
                },
                "confidence_score": 90,
            }
        )

        parsed = parse_direct_higgsfield_prompt_response(
            raw,
            shared_motion_prompt="subtle phone camera sway and soft pose hold",
        )

        prompt = parsed.higgsfieldGridPrompt.lower()
        self.assertIn("gray couch", prompt)
        self.assertIn("deep cleavage", prompt)
        self.assertIn("outfit variations", prompt)
        self.assertNotIn("hair", prompt)
        self.assertNotIn("blue eyes", prompt)
        self.assertNotIn("freckle", prompt)
        self.assertNotIn("skin texture", prompt)
        self.assertNotIn("natural sheen", prompt)
        self.assertNotIn("high detail", prompt)
        self.assertNotIn("sharp focus", prompt)
        self.assertNotIn("consistent face", prompt)

    def test_direct_higgsfield_parser_accepts_manual_grok_image_prompt_key(self):
        raw = json.dumps(
            {
                "image_prompt": (
                    "Create one high-quality native 2x3 grid featuring six variations of the exact same stunning woman. "
                    "Exact reference pose in all panels: seated over-the-shoulder pose, strong arched back, seductive gaze. "
                    "Strong sexual body emphasis in every panel: deep plunging cleavage, massive round plump juicy ass, "
                    "tiny cinched waist, wide hips, thick thighs, dramatic S-curve posture, skin-tight fabric clinging to every curve. "
                    "Outfit variations: 1. Grey set. 2. Black set. 3. White set. 4. Navy set. 5. Deep red set. 6. Soft pink set."
                ),
                "notes": "manual Grok response shape",
            }
        )

        parsed = parse_direct_higgsfield_prompt_response(
            raw,
            shared_motion_prompt="subtle phone camera sway and soft pose hold",
        )

        self.assertIn("native 2x3 grid", parsed.higgsfieldGridPrompt)
        self.assertIn("massive round plump juicy ass", parsed.higgsfieldGridPrompt)
        self.assertFalse(hasattr(parsed, "image_prompt"))

    def test_direct_higgsfield_cleanup_removes_identity_polish_without_scene_loss(self):
        cleaned = clean_direct_higgsfield_prompt_text(
            "A bright living room with a gray couch, blue eyes, freckles, long red hair, "
            "hand resting in her hair, deep cleavage, ribbed crop top, photorealistic skin texture, "
            "high detail, sharp focus, same camera angle."
        )

        low = cleaned.lower()
        self.assertIn("bright living room", low)
        self.assertIn("gray couch", low)
        self.assertIn("deep cleavage", low)
        self.assertIn("ribbed crop top", low)
        self.assertIn("same camera angle", low)
        self.assertNotIn("blue eyes", low)
        self.assertNotIn("freckle", low)
        self.assertNotIn("hair", low)
        self.assertNotIn("skin texture", low)
        self.assertNotIn("high detail", low)
        self.assertNotIn("sharp focus", low)

    def test_direct_higgsfield_cleanup_records_removal_only_diff_and_pose_replacement(
        self,
    ):
        cleanup = clean_direct_higgsfield_prompt(
            "A bright living room with a gray couch, blue eyes, freckles, long red hair, "
            "hand resting in her hair, deep cleavage, pushed-up breasts, dramatic S-curve posture, "
            "ribbed crop top stretching tightly over curves, photorealistic skin texture with natural sheen, "
            "high detail, sharp focus, same camera angle."
        )

        low = cleanup["cleaned"].lower()
        self.assertEqual(
            cleanup["raw"]
            .split(", deep cleavage", 1)[1]
            .count("dramatic S-curve posture"),
            1,
        )
        self.assertIn("deep cleavage", low)
        self.assertIn("pushed-up breasts", low)
        self.assertIn("dramatic s-curve posture", low)
        self.assertIn("ribbed crop top stretching tightly over curves", low)
        self.assertIn("hand near head", low)
        self.assertNotIn("hair", low)
        self.assertNotIn("blue eyes", low)
        self.assertNotIn("freckle", low)
        self.assertNotIn("skin texture", low)
        self.assertNotIn("natural sheen", low)
        self.assertNotIn("high detail", low)
        self.assertNotIn("sharp focus", low)
        self.assertTrue(cleanup["changed"])
        self.assertGreaterEqual(len(cleanup["diff"]), 1)
        self.assertIn(
            "reference_factory_sexy_realistic_removal_only", cleanup["policy"]
        )

    def test_scene_json_to_higgsfield_prompt_preserves_dense_visual_spec_and_strips_forbidden_fields(
        self,
    ):
        prompt = scene_json_to_higgsfield_prompt(
            {
                "subject": {
                    "type": "adult woman",
                    "identity": "same person from reference",
                    "pose": "standing, both hands gripping and slightly pulling down the waistband of unbuttoned light-wash denim shorts, one hand resting in hair",
                    "expression": "neutral sultry gaze with slightly parted lips",
                },
                "face": {"features": "heart-shaped face"},
                "hair": {"style": "long dark waves"},
                "body": {
                    "build": "exaggerated hourglass figure with very large breasts and a big round ass",
                    "breasts": "deep cleavage with pushed-up breasts",
                    "hips_and_ass": "tiny waist, wide hips, thick thighs, big round ass",
                },
                "clothing": {
                    "top": "tight black square-neck spaghetti strap bodysuit stretched tightly over very large breasts",
                    "bottom": "light wash distressed denim shorts unbuttoned and pulled down low on the hips",
                },
                "environment": {
                    "setting": "minimalist indoor room",
                    "background": "plain off-white wall",
                },
                "lighting_and_camera": {
                    "lighting": "soft front-facing flash effect",
                    "camera_angle": "eye-level amateur iPhone shot",
                },
                "outfit_variations": [
                    "1. black bodysuit with light-wash denim shorts",
                    "2. white bodysuit with light-wash denim shorts",
                    "3. burgundy bodysuit with light-wash denim shorts",
                    "4. charcoal bodysuit with light-wash denim shorts",
                    "5. olive bodysuit with light-wash denim shorts",
                    "6. blush bodysuit with light-wash denim shorts",
                ],
                "negative_prompt": "tattoos, bad hands",
                "constraints": {"avoid": ["tattoos"]},
                "ethnicity": "White",
            }
        )

        self.assertIn(
            "Create one high-quality native 2x3 grid featuring six variations", prompt
        )
        self.assertIn(
            "both hands gripping and slightly pulling down the waistband", prompt
        )
        self.assertIn("hand raised near head", prompt)
        self.assertIn("neutral sultry gaze", prompt)
        self.assertIn("very large breasts", prompt)
        self.assertIn("big round ass", prompt)
        self.assertIn("tight black square-neck spaghetti strap bodysuit", prompt)
        self.assertIn("light wash distressed denim shorts unbuttoned", prompt)
        self.assertIn("plain off-white wall", prompt)
        self.assertIn("eye-level amateur iPhone shot", prompt)
        self.assertIn("Outfit Variations (1-6)", prompt)
        self.assertNotIn("identity", prompt.lower())
        self.assertNotIn("heart-shaped", prompt)
        self.assertNotIn("hair", prompt.lower())
        self.assertNotIn("ethnicity", prompt.lower())
        self.assertNotIn("tattoo", prompt.lower())
        self.assertNotIn("bad hands", prompt.lower())

    def test_direct_higgsfield_prompt_parser_accepts_scene_json_and_allows_generic_consistency_language(
        self,
    ):
        parsed = parse_direct_higgsfield_prompt_response(
            json.dumps(
                {
                    "subject": {
                        "type": "adult woman",
                        "pose": "casual iPhone mirror-selfie pose",
                    },
                    "body": {
                        "build": "voluptuous extreme hourglass figure, deep cleavage, tiny waist, wide hips",
                    },
                    "clothing": {
                        "top": "skin-tight ribbed crop top",
                    },
                    "environment": {
                        "setting": "bright indoor room",
                    },
                    "consistency": "exact same stunning woman, consistent body proportions, same pose across panels",
                }
            ),
            shared_motion_prompt="subtle body sway and slow phone-camera push-in",
        )

        self.assertIn("exact same stunning woman", parsed.higgsfieldGridPrompt)
        self.assertIn("casual iPhone mirror-selfie pose", parsed.higgsfieldGridPrompt)
        self.assertEqual(
            parsed.klingMotionPrompt, "subtle body sway and slow phone-camera push-in"
        )

    def test_prompt_drift_report_preserves_valid_grok_prompt(self):
        raw_prompt = (
            "Create one high-quality native 2x3 grid featuring six variations of the exact same stunning woman "
            "taking a bathroom mirror selfie. Exact reference pose in all panels: seated three-quarter back view, "
            "arched back, over-the-shoulder gaze. Strong visual mechanics: deep neckline, tight fabric cling, "
            "tiny waist, wide hips, thick thighs. Outfit variations (1-6): grey set, black set, white set, navy set, "
            "deep red set, soft pink set. Identical bathroom lighting, mirror angle, framing, and room across all panels."
        )
        report = prompt_drift_report(raw_prompt, raw_prompt)

        self.assertEqual(report["removedConcepts"], [])
        self.assertEqual(report["addedConcepts"], [])
        self.assertIn("mirror selfie", report["preservedConcepts"])
        self.assertIn("Outfit variations (1-6)", report["preservedConcepts"])
        self.assertFalse(report["visualMechanicsLoss"])

    def test_generate_prompt_reports_raw_to_final_prompt_drift(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "mirror.png"
            Image.new("RGB", (1080, 1920), "white").save(ref)
            raw_prompt = (
                "Create one high-quality native 2x3 grid featuring six variations of the exact same stunning woman "
                "taking a bathroom mirror selfie. Exact reference pose in all panels: seated three-quarter back view, "
                "arched back, over-the-shoulder gaze. Strong visual mechanics: deep neckline, tight fabric cling, "
                "tiny waist, wide hips, thick thighs. Outfit variations (1-6): grey set, black set, white set, navy set, "
                "deep red set, soft pink set. Identical bathroom lighting, mirror angle, framing, and room across all panels."
            )
            fake_raw = {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "image_prompt": raw_prompt,
                                        "notes": "manual Grok image prompt response shape",
                                    }
                                ),
                            }
                        ]
                    }
                ]
            }
            with (
                patch("generate_prompts.load_xai_api_key", return_value="key"),
                patch("generate_prompts.call_grok", return_value=fake_raw),
            ):
                result = generate_prompt(
                    out_path=root / "prompt.json",
                    root=root,
                    reference_images=[ref],
                    dry_run=True,
                )

        self.assertIn("prompt_drift", result)
        self.assertEqual(result["prompt_mode"], REFERENCE_FACTORY_SEXY_REALISTIC_MODE)
        self.assertEqual(
            result["lineage"]["prompt_mode"], REFERENCE_FACTORY_SEXY_REALISTIC_MODE
        )
        self.assertEqual(result["lineage"]["raw_grok_prompt"], raw_prompt)
        self.assertEqual(result["lineage"]["cleaned_prompt"], raw_prompt)
        self.assertEqual(result["lineage"]["aspect_ratio"], "4:3")
        self.assertEqual(result["lineage"]["grid_layout"]["value"], "3x2")
        self.assertFalse(result["lineage"]["prompt_enhancement"])
        self.assertFalse(result["lineage"]["reference_image_passed_to_higgsfield"])
        self.assertEqual(result["prompt_drift"]["removedConcepts"], [])
        self.assertFalse(result["prompt_drift"]["visualMechanicsLoss"])

    def test_generate_prompt_higgsfield_reference_mode_forces_single_image(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "mirror.png"
            Image.new("RGB", (1080, 1920), "white").save(ref)
            raw_prompt = (
                "Create one standalone image matching the reference bedroom mirror selfie pose, "
                "front mirror angle, phone held at chest height, fitted white tank, pink shorts, "
                "warm bedroom lighting, sexy body-forward posture, deep neckline, tight fabric cling."
            )
            fake_raw = {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "image_prompt": raw_prompt,
                                        "notes": "simple Higgsfield reference prompt",
                                    }
                                ),
                            }
                        ]
                    }
                ]
            }
            with (
                patch("generate_prompts.load_xai_api_key", return_value="key"),
                patch("generate_prompts.call_grok", return_value=fake_raw) as grok,
            ):
                result = generate_prompt(
                    out_path=root / "prompt.json",
                    root=root,
                    reference_images=[ref],
                    dry_run=True,
                    prompt_mode=HIGGSFIELD_REFERENCE_PROMPT_MODE,
                    grid_layout="3x2",
                    creative_direction="make it sexy but keep the exact pose",
                )

        instruction = grok.call_args.args[0]["input"][0]["content"][0]["text"]
        self.assertIn("Make a prompt similar to this reference image", instruction)
        self.assertIn("get the pose down correctly", instruction)
        self.assertIn("exactly one standalone image", instruction)
        self.assertEqual(result["prompt_mode"], HIGGSFIELD_REFERENCE_PROMPT_MODE)
        self.assertEqual(
            result["prompt_source"], "live_grok_higgsfield_reference_prompt"
        )
        self.assertEqual(result["lineage"]["grid_layout"]["value"], "single")
        self.assertIn("bedroom mirror selfie", result["prompt"]["higgsfieldGridPrompt"])
        self.assertNotIn("2x3", result["prompt"]["higgsfieldGridPrompt"].lower())
        self.assertNotIn("3x2", result["prompt"]["higgsfieldGridPrompt"].lower())

    def test_direct_higgsfield_prompt_parser_still_blocks_caption_overlay(self):
        with self.assertRaisesRegex(ValueError, "rejected v1 language"):
            parse_direct_higgsfield_prompt_response(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "Create one native 2x3 grid with caption overlay at bottom"
                    }
                ),
                shared_motion_prompt="subtle body sway",
            )

    def test_direct_higgsfield_prompt_parser_scrubs_identity_traits(self):
        parsed = parse_direct_higgsfield_prompt_response(
            json.dumps(
                {
                    "higgsfieldGridPrompt": (
                        "Create one native 2x3 grid with long brown hair, wrist tattoo, deep cleavage, "
                        "and mirror selfie pose."
                    )
                }
            ),
            shared_motion_prompt="subtle body sway",
        )

        prompt = parsed.higgsfieldGridPrompt.lower()
        self.assertIn("deep cleavage", prompt)
        self.assertIn("mirror selfie pose", prompt)
        self.assertNotIn("hair", prompt)
        self.assertNotIn("tattoo", prompt)

    def test_embedding_search_hash_fallback_finds_similar_neighbor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            a = root / "prompts" / "bathroom_mirror_winner.json"
            b = root / "prompts" / "bathroom_mirror_variant.json"
            c = root / "prompts" / "beach_dance.json"
            a.parent.mkdir()
            a.write_text(
                json.dumps({"higgsfieldGridPrompt": "bathroom mirror selfie crop top"}),
                encoding="utf-8",
            )
            b.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "bathroom mirror selfie crop top alternate"
                    }
                ),
                encoding="utf-8",
            )
            c.write_text(
                json.dumps({"higgsfieldGridPrompt": "beach dance swimsuit ocean"}),
                encoding="utf-8",
            )
            upsert_embedding(root, b)
            upsert_embedding(root, c)

            result = similar_media(root, a, limit=2)

            self.assertEqual(result["results"][0]["path"], str(b.resolve()))

    def test_winner_dna_experiments_and_cost_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            out_a = root / "a_bathroom.mp4"
            out_b = root / "b_beach.mp4"
            out_a.write_bytes(b"a")
            out_b.write_bytes(b"b")
            now = int(time.time())
            manifest.conn.execute(
                "INSERT INTO campaign_outputs (campaign_output_id, output_path, recipe, caption_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("co_a", str(out_a), "grid", "wait?", now, now),
            )
            manifest.conn.execute(
                "INSERT INTO campaign_outputs (campaign_output_id, output_path, recipe, caption_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("co_b", str(out_b), "individual", "look", now, now),
            )
            manifest.conn.execute(
                "INSERT INTO reel_outcomes (outcome_id, filename, output_path, platform, account, posted_at, views, likes, comments, shares, saves, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "oa",
                    out_a.name,
                    str(out_a),
                    "ig",
                    "acct",
                    "2026-05-28",
                    100,
                    100,
                    0,
                    0,
                    0,
                    now,
                ),
            )
            manifest.conn.execute(
                "INSERT INTO reel_outcomes (outcome_id, filename, output_path, platform, account, posted_at, views, likes, comments, shares, saves, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "ob",
                    out_b.name,
                    str(out_b),
                    "ig",
                    "acct",
                    "2026-05-28",
                    100,
                    0,
                    0,
                    1,
                    1,
                    now,
                ),
            )
            manifest.conn.commit()
            upsert_reel_feature(
                root,
                out_a,
                features={
                    "scene": "bathroom_mirror",
                    "camera": "mirror_selfie",
                    "pose": "seated_side",
                    "motion": "hip_sway",
                    "outfit": "crop_top",
                    "creator": "stacey",
                    "grid_source": 1,
                    "caption_style": "short_direct",
                    "hook_type": "curiosity",
                    "body_style": "hourglass",
                },
            )
            upsert_reel_feature(
                root,
                out_b,
                features={
                    "scene": "beach",
                    "camera": "phone",
                    "pose": "standing",
                    "motion": "walk",
                    "outfit": "swimsuit",
                    "creator": "stacey",
                    "grid_source": 0,
                    "caption_style": "short_direct",
                    "hook_type": "direct",
                    "body_style": "hourglass",
                },
            )
            assign_experiment(
                root, name="grid_vs_individual", group="grid", output_path=str(out_a)
            )
            assign_experiment(
                root,
                name="grid_vs_individual",
                group="individual",
                output_path=str(out_b),
            )
            record_cost(
                root,
                entity_type="final_reel",
                output_path=str(out_a),
                estimated_generation_cost=10.0,
            )
            record_cost(
                root,
                entity_type="final_reel",
                output_path=str(out_b),
                estimated_generation_cost=2.0,
            )

            self.assertGreater(
                winner_score(
                    {"views": 0, "likes": 10, "comments": 0, "shares": 0, "saves": 0}
                ),
                0,
            )
            self.assertGreater(
                winner_score(
                    {"views": 0, "likes": 0, "comments": 0, "shares": 1, "saves": 1}
                ),
                winner_score(
                    {"views": 0, "likes": 5, "comments": 0, "shares": 0, "saves": 0}
                ),
            )
            self.assertGreater(
                winner_score(
                    {
                        "views": 100,
                        "likes": 40,
                        "comments": 8,
                        "shares": 3,
                        "saves": 2,
                    }
                ),
                winner_score(
                    {
                        "views": 100000,
                        "likes": 100,
                        "comments": 5,
                        "shares": 1,
                        "saves": 1,
                    }
                ),
            )
            self.assertEqual(
                winner_score(
                    {"manual_score": 7, "views": 100000, "likes": 0, "shares": 0}
                ),
                7,
            )
            refresh_winner_dna(root)
            board = winner_dna_leaderboard(root)
            costs = cost_analytics(root)
            exp = experiment_report(root, "grid_vs_individual")

            self.assertTrue(board["top_scenes"])
            self.assertEqual(
                board["low_data_warning"],
                "Winner DNA is based on fewer than 50 outcome rows (2 available). Treat recommendations as directional.",
            )
            self.assertEqual(board["top_scenes"][0]["confidence"]["level"], "low")
            self.assertEqual(exp["groups"][0]["name"], "individual")
            self.assertGreater(costs["assets"][0]["winner_score_per_cost"], 0)

    def test_winner_dna_refresh_uses_stable_campaign_output_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            now = int(time.time())
            out = root / "local_winner_render.mp4"
            out.write_bytes(b"video")
            manifest.conn.execute(
                """
                INSERT INTO campaign_outputs (
                    campaign_output_id, output_path, job_key, recipe,
                    caption_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "co_winner_stable",
                    str(out.resolve()),
                    "job_winner_stable",
                    "v01_original",
                    "wait?",
                    now,
                    now,
                ),
            )
            manifest.conn.execute(
                """
                INSERT INTO reel_outcomes (
                    outcome_id, filename, campaign_output_id, job_key, platform,
                    account, posted_at, views, likes, comments, shares, saves,
                    imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "outcome_winner_stable",
                    "posted_renamed_winner.mp4",
                    "co_winner_stable",
                    "job_winner_stable",
                    "ig",
                    "acct",
                    "2026-07-01",
                    100,
                    30,
                    5,
                    2,
                    1,
                    now,
                ),
            )
            manifest.conn.commit()
            upsert_reel_feature(
                root,
                out,
                features={"scene": "bedroom", "pose": "standing", "creator": "stacey"},
            )

            refresh_winner_dna(root)
            board = winner_dna_leaderboard(root)

            self.assertEqual(board["top_scenes"][0]["feature_value"], "bedroom")
            self.assertEqual(board["top_scenes"][0]["sample_size"], 1)

    def test_winner_dna_derives_creator_and_caption_style_from_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_campaign(
                root,
                name="Larissa Metadata",
                creator="Larissa",
                account="larissa_acct",
                platform="instagram_reels",
            )
            conn = campaign_connect(root)
            campaign_id = conn.execute(
                "SELECT campaign_id FROM campaigns WHERE name=?",
                ("Larissa Metadata",),
            ).fetchone()["campaign_id"]
            now = int(time.time())
            out = root / "generic_render_name.mp4"
            out.write_bytes(b"video")
            conn.execute(
                """
                INSERT INTO campaign_outputs (
                    campaign_output_id, campaign_id, output_path, recipe,
                    caption_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "co_larissa_metadata",
                    campaign_id,
                    str(out.resolve()),
                    "v09_caption_bg",
                    "1. Smooth\n2. Nervous\n3. Playful\n4. Honest\n5. Bold",
                    now,
                    now,
                ),
            )
            conn.commit()
            conn.close()
            out.with_suffix(out.suffix + ".caption_lineage.json").write_text(
                json.dumps(
                    {
                        "schema": "reel_factory.caption_lineage.v1",
                        "rawCaptionText": "1. Smooth\n2. Nervous\n3. Playful\n4. Honest\n5. Bold",
                        "captionOutcomeContext": {
                            "length_class": "long",
                            "format_class": "numbered_list",
                        },
                    }
                ),
                encoding="utf-8",
            )
            write_audio_intent(
                out,
                mode="native_trending_audio",
                audio_selection={"track_id": "track_rank_1", "track_name": "Top"},
            )

            result = upsert_reel_feature(root, out)

            self.assertEqual(result["features"]["creator"], "larissa")
            self.assertEqual(result["features"]["caption_style"], "long_numbered_list")
            self.assertEqual(result["features"]["audio_track_id"], "track_rank_1")

    def test_winner_dna_features_prefer_video_analysis_sidecar_over_filename_inference(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "unknown_clip.mp4"
            out.write_bytes(b"video")
            out.with_suffix(out.suffix + ".video_analysis.json").write_text(
                json.dumps(
                    {
                        "schema": "reference_factory.video_analysis.v1",
                        "id": "analysis_unknown_clip",
                        "referenceId": "unknown_clip",
                        "provider": "operator_vlm",
                        "model": "video_analysis",
                        "status": "pattern_ready",
                        "winnerDnaFeatures": {
                            "scene": "gym_mirror",
                            "camera": "mirror_selfie",
                            "pose": "standing",
                            "motion": "slow_pan",
                            "outfit": "black_set",
                            "creator": "stacey",
                            "body_style": "athletic_hourglass",
                            "caption_style": "lower_third",
                            "hook_type": "pov",
                        },
                        "media": {
                            "durationSeconds": 7.0,
                            "width": 1080,
                            "height": 1920,
                        },
                        "signals": {},
                        "patternCard": {
                            "schema": "reference_factory.pattern_card.v1",
                            "id": "pattern_gym_mirror",
                            "platform": "instagram",
                            "source": {"referenceId": "unknown_clip"},
                            "formatType": "mirror_selfie",
                            "hookType": "pov",
                            "visualPattern": "Gym mirror clip",
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = upsert_reel_feature(root, out)

            self.assertEqual(result["features"]["scene"], "gym_mirror")
            self.assertEqual(result["features"]["motion"], "slow_pan")
            self.assertEqual(result["features"]["hook_type"], "pov")
            self.assertEqual(result["features"]["feature_source"], "video_analysis")

    def test_confidence_helpers_label_small_samples_as_directional(self):
        self.assertEqual(
            confidence_for_sample_size(8, total_outcomes=20)["level"], "low"
        )
        self.assertIn("fewer than 50", low_data_warning(20))
        self.assertEqual(
            confidence_for_sample_size(30, total_outcomes=80)["level"], "high"
        )

    def test_proof_reports_fatigue_duplicate_and_decision_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            now = int(time.time())
            manual = root / "manual_bathroom.mp4"
            rec = root / "recommended_bathroom.mp4"
            varied = root / "varied_beach.mp4"
            candidate = root / "candidate_bathroom.mp4"
            for path in (manual, rec, varied, candidate):
                path.write_bytes(path.name.encode())
            for co_id, path in (
                ("co_manual", manual),
                ("co_rec", rec),
                ("co_varied", varied),
            ):
                manifest.conn.execute(
                    "INSERT INTO campaign_outputs (campaign_output_id, output_path, recipe, caption_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (co_id, str(path), "v01_original", "wait?", now, now),
                )
            rows = [
                ("om", manual, "acct", 100, 1, 0, 0, 0),
                ("or", rec, "acct", 200, 10, 1, 3, 4),
                ("ov", varied, "acct", 50, 0, 0, 0, 0),
            ]
            for (
                outcome_id,
                path,
                account,
                views,
                likes,
                comments,
                shares,
                saves,
            ) in rows:
                manifest.conn.execute(
                    "INSERT INTO reel_outcomes (outcome_id, filename, output_path, platform, account, posted_at, views, likes, comments, shares, saves, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        outcome_id,
                        path.name,
                        str(path),
                        "ig",
                        account,
                        "2026-05-28",
                        views,
                        likes,
                        comments,
                        shares,
                        saves,
                        now,
                    ),
                )
            manifest.conn.commit()
            for path in (manual, rec):
                upsert_reel_feature(
                    root,
                    path,
                    features={
                        "scene": "bathroom_mirror",
                        "camera": "mirror_selfie",
                        "pose": "seated_side",
                        "motion": "hip_sway",
                        "outfit": "crop_top",
                        "creator": "stacey",
                        "grid_source": 1,
                        "caption_style": "short_direct",
                        "hook_type": "curiosity",
                        "body_style": "hourglass",
                    },
                )
            upsert_reel_feature(
                root,
                varied,
                features={
                    "scene": "beach",
                    "camera": "phone",
                    "pose": "standing",
                    "motion": "walk",
                    "outfit": "dress",
                    "creator": "stacey",
                    "grid_source": 0,
                    "caption_style": "short_direct",
                    "hook_type": "direct",
                    "body_style": "hourglass",
                },
            )
            assign_experiment(
                root,
                name="baseline_vs_recommended",
                group="manual",
                output_path=str(manual),
            )
            assign_experiment(
                root,
                name="baseline_vs_recommended",
                group="recommended",
                output_path=str(rec),
            )
            upsert_embedding(root, rec)
            upsert_embedding(root, varied)

            baseline = baseline_vs_recommended_report(
                root, experiment="baseline_vs_recommended"
            )
            fatigue = account_fatigue_report(root, account="acct", window=30)
            duplicate = duplicate_risk(root, candidate, account="acct")
            plan = {
                "ideas": [
                    {
                        "prompt_focus": "fix_hands",
                        "avoid_labels": ["hands_bad"],
                        "winner_dna_focus": [
                            {
                                "feature_key": "scene",
                                "feature_value": "bathroom_mirror",
                                "sample_size": 2,
                            }
                        ],
                        "recommendation": {
                            "pattern": "bathroom_mirror",
                            "confidence": "low",
                            "confidence_reason": "based on 2 matching outcome rows",
                            "data_quality": {"score": 20},
                        },
                    }
                ]
            }
            decision_id = persist_recommendation_decision(
                root,
                campaign="Test Campaign",
                plan=plan,
                rejection_patterns=[{"label": "hands_bad", "count": 1}],
            )
            decisions = decision_log(root, campaign="Test Campaign")

            self.assertGreater(
                baseline["recommended"]["avg_winner_score"],
                baseline["manual"]["avg_winner_score"],
            )
            self.assertGreater(baseline["lift_percent"], 0)
            self.assertEqual(fatigue["level"], "medium")
            self.assertIn(
                "bathroom_mirror",
                {row["feature_value"] for row in fatigue["overused_patterns"]},
            )
            self.assertNotEqual(
                duplicate["nearest_prior_output"]["path"], str(candidate.resolve())
            )
            self.assertIn(duplicate["recommended_action"], {"safe", "review", "avoid"})
            self.assertEqual(decisions["decisions"][0]["decision_id"], decision_id)
            self.assertEqual(
                decisions["decisions"][0]["recommendation_pattern"], "bathroom_mirror"
            )

    def test_duplicate_risk_accepts_legacy_similarity_list_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            out_dir = root / "02_processed" / "clip_001"
            out_dir.mkdir(parents=True)
            candidate = out_dir / "candidate.mp4"
            candidate.write_bytes(b"candidate")
            prior = out_dir / "prior.mp4"
            prior.write_bytes(b"prior")
            now = int(time.time())
            manifest.conn.execute(
                "INSERT INTO reel_outcomes (outcome_id, filename, output_path, platform, account, posted_at, views, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("op", prior.name, str(prior), "ig", "acct", "2026-05-28", 10, now),
            )
            manifest.conn.commit()
            (out_dir / "_similarity.json").write_text(
                json.dumps(
                    [
                        {
                            "filename": candidate.name,
                            "score": 0.95,
                            "verdict": "near_duplicate",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = duplicate_risk(root, candidate, account="acct")

            self.assertEqual(result["risk_level"], "high")
            self.assertEqual(result["recommended_action"], "avoid")

    def test_duplicate_risk_resolves_prior_outcome_by_filename_when_path_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(root / "manifest.json")
            out_dir = root / "02_processed" / "clip_001"
            out_dir.mkdir(parents=True)
            prior = out_dir / "prior_bathroom.mp4"
            candidate = out_dir / "candidate_bathroom.mp4"
            prior.write_bytes(b"prior")
            candidate.write_bytes(b"candidate")
            now = int(time.time())
            manifest.conn.execute(
                "INSERT INTO reel_outcomes (outcome_id, filename, platform, account, posted_at, views, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("op", prior.name, "ig", "acct", "2026-05-28", 10, now),
            )
            manifest.conn.commit()
            upsert_embedding(root, prior)

            result = duplicate_risk(root, candidate, account="acct")

            self.assertEqual(
                result["nearest_prior_output"]["path"], str(prior.resolve())
            )

    def test_data_quality_score_penalizes_missing_inputs(self):
        weak = data_quality_score(
            total_outcomes=5,
            matched_sample_size=2,
            outcomes_with_metrics=1,
            reviewed_outputs=5,
            reviewed_with_reasons=1,
            distinct_review_labels=1,
            experiment_group_counts=[5, 1],
        )
        strong = data_quality_score(
            total_outcomes=80,
            matched_sample_size=30,
            outcomes_with_metrics=80,
            reviewed_outputs=20,
            reviewed_with_reasons=20,
            distinct_review_labels=5,
            experiment_group_counts=[20, 18],
        )
        self.assertEqual(weak["level"], "weak")
        self.assertEqual(strong["level"], "strong")

    def test_guided_cockpit_status_next_action_and_dashboard_summary(self):
        self.assertEqual(
            clip_status_from_evidence(
                stem="clip_001",
                output_count=0,
                review_states=[],
                outcome_count=0,
                has_prompt=False,
            )["status"],
            "Needs Captions",
        )
        self.assertEqual(
            clip_status_from_evidence(
                stem="clip_001",
                output_count=0,
                review_states=[],
                outcome_count=0,
                has_prompt=False,
                hook_count=3,
            )["status"],
            "Ready to Render",
        )
        self.assertEqual(
            clip_status_from_evidence(
                stem="clip_001",
                output_count=0,
                review_states=[],
                outcome_count=0,
                has_prompt=True,
            )["status"],
            "Needs Soul",
        )
        self.assertEqual(
            clip_status_from_evidence(
                stem="clip_001",
                output_count=3,
                review_states=["draft", "draft"],
                outcome_count=0,
                has_prompt=True,
            )["status"],
            "Needs Review",
        )
        self.assertEqual(
            clip_status_from_evidence(
                stem="clip_001",
                output_count=3,
                review_states=["approved"],
                outcome_count=0,
                has_prompt=True,
            )["status"],
            "Needs Metrics",
        )
        self.assertEqual(
            next_action_for_status("Needs Kling")["label"], "Create Kling video"
        )
        self.assertEqual(
            next_action_for_status("Needs Captions")["label"], "Auto-caption + render"
        )

        summary = dashboard_summary_api()

        self.assertEqual(summary["schema"], "reel_factory.dashboard_summary.v1")
        self.assertIn("command_center", summary)
        self.assertIn("clip_statuses", summary)

    def test_auto_hooks_api_creates_caption_sidecar_without_manual_editing(self):
        with tempfile.TemporaryDirectory() as tmp:
            import reel_gui

            old_root, old_cap = reel_gui.ROOT, reel_gui.CAP_DIR
            try:
                reel_gui.ROOT = Path(tmp)
                reel_gui.CAP_DIR = Path(tmp) / "01_captions"
                result = auto_hooks_api("clip_001", {"count": 5})
                saved = json.loads(
                    (Path(tmp) / "01_captions" / "clip_001.json").read_text()
                )
                repeat = auto_hooks_api("clip_001", {"count": 5})
            finally:
                reel_gui.ROOT, reel_gui.CAP_DIR = old_root, old_cap

            self.assertTrue(result["ok"])
            self.assertTrue(result["generated"])
            self.assertEqual(result["hook_count"], 5)
            self.assertEqual(len(saved["hooks"]), 5)
            self.assertEqual(saved["generation"]["source"], "auto_hooks_v1")
            self.assertFalse(repeat["generated"])

    def test_photo_save_and_threadsdashboard_queue_create_local_handoff_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            import reel_gui

            root = Path(tmp)
            image = root / "project_data" / "generated_assets" / "image.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")
            reel = (
                root
                / "02_processed"
                / "clip_001"
                / "clip_001_h00_v01_original_deadbeef.mp4"
            )
            reel.parent.mkdir(parents=True)
            reel.write_bytes(b"mp4")
            old_root = reel_gui.ROOT
            try:
                reel_gui.ROOT = root
                photo = save_photo_post_asset(
                    root,
                    source_image=str(image),
                    account="acct",
                    caption="photo caption",
                )
                queued = queue_threadsdashboard_post(
                    root,
                    output_path=str(reel),
                    account="acct",
                    caption="reel caption",
                    scheduled_at="2026-05-30T10:00:00",
                )
                queued_again = queue_threadsdashboard_post(
                    root,
                    output_path=str(reel),
                    account="acct",
                    caption="updated reel caption",
                    scheduled_at="2026-05-30T10:00:00",
                )
            finally:
                reel_gui.ROOT = old_root

            self.assertTrue(Path(photo["path"]).exists())
            self.assertTrue(Path(photo["sidecar"]).exists())
            self.assertEqual(photo["photo"]["status"], "saved")
            self.assertTrue(Path(queued["path"]).exists())
            self.assertTrue(Path(queued["queue_path"]).exists())
            self.assertEqual(queued["queued"]["platform"], "threads")
            self.assertEqual(queued["queued"]["status"], "queued")
            self.assertEqual(queued["queued"]["scheduled_at"], "2026-05-30T10:00:00")
            self.assertEqual(
                queued_again["queued"]["post_id"], queued["queued"]["post_id"]
            )
            queue_lines = [
                line
                for line in Path(queued["queue_path"])
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(queue_lines), 1)
            self.assertIn("updated reel caption", queue_lines[0])

    def test_reel_pipeline_accepts_campaign_render_flags(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "reel_pipeline.py", "--help"],
            cwd=REEL_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("--campaign", result.stdout)
        self.assertIn("--asset-generation-id", result.stdout)

    def test_generation_soul_validation_fails_on_missing_or_wrong_id(self):
        expected = "5828d958-91dd-4d6d-8909-934503f47644"
        missing = validate_generation_soul({"params": {}}, expected)
        wrong = validate_generation_soul(
            {"params": {"custom_reference_id": "wrong"}}, expected
        )
        ok = validate_generation_soul(
            {"params": {"custom_reference_id": expected}}, expected
        )
        self.assertEqual(missing["status"], "invalid")
        self.assertEqual(wrong["status"], "invalid")
        self.assertEqual(ok["status"], "valid")

    def test_retry_helper_direction_feeds_prompt_generation(self):
        direction = retry_helper_direction("fix_hands")
        instruction = build_user_instruction("reference", direction)
        self.assertIn("hand placement", instruction.lower())
        self.assertIn("clean support-hand shapes", instruction.lower())
        with self.assertRaises(ValueError):
            retry_helper_direction("not_real")

    def test_generate_assets_source_lineage_captures_job_ids_and_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = parse_asset_prompt_response(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid",
                        "klingMotionPrompt": "motion",
                        "notes": "ok",
                    }
                )
            )
            plan = AssetGenerationPlan(
                prompt_json=root / "prompt.json",
                stem="clip_001",
                reference="upload_123",
                soul_id="soul_123",
                soul_name="Stacey",
                start_image=None,
                out_dir=root,
                source_dir=root,
            )

            lineage = build_source_lineage(
                plan,
                prompt=prompt,
                commands=[["higgsfield", "generate", "create", "kling3_0"]],
                upload_id="upload_123",
                soul_id="soul_123",
                soul_name="Stacey",
                image_job_id="image_job",
                image_result_url="https://example.test/image.png",
                video_job_id="video_job",
                video_result_url="https://example.test/video.mp4",
            )

            self.assertEqual(
                lineage["generation"]["models"]["image"], "text2image_soul_v2"
            )
            self.assertEqual(lineage["generation"]["models"]["video"], "kling3_0")
            self.assertEqual(lineage["generation"]["uploadId"], "upload_123")
            self.assertEqual(lineage["generation"]["soulId"], "soul_123")
            self.assertEqual(lineage["source"]["soulName"], "Stacey")
            self.assertEqual(lineage["generation"]["imageJobId"], "image_job")
            self.assertEqual(
                lineage["generation"]["videoResultUrl"],
                "https://example.test/video.mp4",
            )

    def test_ai_visual_qc_record_flags_deterministic_warnings(self):
        record = record_from_scores(
            "out.mp4",
            "/tmp/out.mp4",
            {
                "opencv_available": 1,
                "blur_min": 10,
                "jump_max": 80,
                "text_edge_score": 0.2,
                "face_count_variance": 1,
            },
        )

        self.assertEqual(record.filename, "out.mp4")
        self.assertIn("possible_blur_or_low_detail", record.warnings)
        self.assertIn("possible_frame_jump_or_flicker", record.warnings)
        self.assertIn("possible_text_or_watermark", record.warnings)
        self.assertIn("face_count_inconsistent", record.warnings)

    def test_ai_visual_qc_sampling_positions_are_deterministic(self):
        self.assertEqual(sample_positions(), [0.0, 0.2, 0.4, 0.6, 0.8, 0.95])

    def test_safe_zone_scorer_flags_bottom_caption_collision(self):
        scored = score_safe_zone(
            width=1080,
            height=1920,
            platform="instagram_reels",
            caption_box={"x": 100, "y": 1600, "w": 700, "h": 220},
        )
        self.assertEqual(scored["safeZoneStatus"], "warn")
        self.assertTrue(scored["captionCollision"])
        self.assertIn("caption_safe_zone_collision", scored["warnings"])

    def test_feed_safe_zone_is_less_reel_ui_constrained(self):
        caption_box = {"x": 100, "y": 1500, "w": 700, "h": 220}
        reels = score_safe_zone(
            width=1080,
            height=1920,
            platform="instagram_reels",
            caption_box=caption_box,
        )
        feed = score_safe_zone(
            width=1080,
            height=1920,
            platform="instagram_feed",
            caption_box=caption_box,
        )

        self.assertIn("caption_safe_zone_collision", reels["warnings"])
        self.assertNotIn("caption_safe_zone_collision", feed["warnings"])

    def test_readiness_warns_for_missing_audio_intent_and_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = (
                root
                / "02_processed"
                / "clip_001"
                / "clip_001_h00_v01_original_light_deadbeef.mp4"
            )
            out.parent.mkdir(parents=True)
            out.write_bytes(b"fake")

            row = evaluate_output(
                root=root,
                clip="clip_001",
                output_path=out,
                platform="instagram_reels",
                dimensions=(1080, 1920),
            )

            self.assertEqual(row["status"], "warn")
            self.assertIn("missing_audio_intent", row["warnings"])
            self.assertIn("missing_generated_asset_lineage", row["warnings"])

    def test_readiness_platform_warnings_for_tiktok_non_9x16_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = (
                root
                / "02_processed"
                / "clip_001"
                / "clip_001_h00_v01_original_light_4x5_deadbeef.mp4"
            )
            out.parent.mkdir(parents=True)
            out.write_bytes(b"fake")

            row = evaluate_output(
                root=root,
                clip="clip_001",
                output_path=out,
                platform="tiktok",
                dimensions=(540, 960),
                ai_qc={"warnings": ["possible_text_or_watermark"]},
            )

            self.assertIn("non_preferred_ratio_4x5", row["warnings"])
            self.assertIn("resolution_below_platform_minimum", row["warnings"])
            self.assertIn("tiktok_text_watermark_review", row["warnings"])

    def test_readiness_accepts_feed_and_square_surface_ratios(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip_dir = root / "02_processed" / "clip_001"
            clip_dir.mkdir(parents=True)
            feed_out = clip_dir / "clip_001_h00_v01_original_light_4x5_deadbeef.mp4"
            square_out = clip_dir / "clip_001_h00_v01_original_light_1x1_deadbeef.mp4"
            feed_out.write_bytes(b"fake")
            square_out.write_bytes(b"fake")

            feed = evaluate_output(
                root=root,
                clip="clip_001",
                output_path=feed_out,
                platform="instagram_feed",
                dimensions=(1080, 1350),
            )
            square = evaluate_output(
                root=root,
                clip="clip_001",
                output_path=square_out,
                platform="instagram_square",
                dimensions=(1080, 1080),
            )

            self.assertEqual(feed["targetRatio"], "4:5")
            self.assertEqual(feed["surface"], "instagram_feed")
            self.assertNotIn("non_preferred_ratio_4x5", feed["warnings"])
            self.assertNotIn("missing_audio_intent", feed["warnings"])
            self.assertEqual(square["targetRatio"], "1:1")
            self.assertEqual(square["surface"], "instagram_square")
            self.assertNotIn("non_preferred_ratio_1x1", square["warnings"])

    def test_readiness_cli_writes_report_for_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = (
                root
                / "02_processed"
                / "clip_001"
                / "clip_001_h00_v01_original_light_deadbeef.mp4"
            )
            out.parent.mkdir(parents=True)
            out.write_bytes(b"fake")

            result = run_readiness(root, clip="clip_001")

            self.assertEqual(result["summary"]["total"], 1)
            self.assertTrue((out.parent / "_readiness.json").exists())

    def test_gui_clip_detail_returns_ai_qc_and_safe_zone_metadata(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            caps = root / "01_captions"
            proc = root / "02_processed"
            clip_proc = proc / "clip_001"
            raw.mkdir()
            caps.mkdir()
            clip_proc.mkdir(parents=True)
            (raw / "clip_001.mp4").write_bytes(b"source")
            (caps / "clip_001.json").write_text('{"hooks":["hook"]}', encoding="utf-8")
            output = clip_proc / "clip_001_h00_v01_original_light_deadbeef.mp4"
            output.write_bytes(b"output")
            (clip_proc / "_ai_qc.json").write_text(
                json.dumps(
                    {
                        "schema": "reel_factory.ai_visual_qc.v1",
                        "clip": "clip_001",
                        "summary": {"total": 1, "warned": 1},
                        "records": [
                            {
                                "filename": output.name,
                                "path": str(output),
                                "warnings": ["possible_text_or_watermark"],
                                "scores": {"text_edge_score": 0.2},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (clip_proc / "_readiness.json").write_text(
                json.dumps(
                    {
                        "schema": "reel_factory.readiness.v1",
                        "clip": "clip_001",
                        "platform": "instagram_reels",
                        "records": [
                            {
                                "filename": output.name,
                                "status": "warn",
                                "score": 80,
                                "warnings": ["missing_audio_intent"],
                                "safeZone": {"safeZoneStatus": "pass"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            write_audio_intent(
                output, mode="native_trending_audio", platform="instagram_reels"
            )

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "CAP_DIR", caps),
                patch.object(reel_gui, "PROC_DIR", proc),
                patch.object(reel_gui, "audio_stream_count", return_value=0),
            ):
                detail = reel_gui.get_clip("clip_001")

            self.assertEqual(
                detail["safe_zones"]["source"], "renderer_default_safe_margins"
            )
            self.assertEqual(
                detail["outputs"][0]["ai_qc"]["warnings"],
                ["possible_text_or_watermark"],
            )
            self.assertEqual(detail["outputs"][0]["readiness"]["status"], "warn")
            self.assertEqual(
                detail["outputs"][0]["audio_intent"]["mode"], "native_trending_audio"
            )

    def test_gui_asset_dry_run_uses_stacey_identity(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            raw.mkdir(parents=True)
            prompt = root / "prompt.json"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
            ):
                result = reel_gui.asset_dry_run_api(
                    {
                        "prompt_json": str(prompt),
                        "stem": "clip_001",
                        "creator": "Stacey",
                    }
                )

            commands = [" ".join(cmd) for cmd in result["commands"]]
            self.assertIn(
                "--custom_reference_id 5828d958-91dd-4d6d-8909-934503f47644",
                commands[0],
            )

    def test_gui_panel_crop_and_full_image_fallback(self):
        import reel_gui
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "project_data"
            image = root / "grid.png"
            Image.new("RGB", (300, 200), "white").save(image)
            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "DATA_DIR", data),
            ):
                panel = reel_gui.asset_select_panel_api(
                    {
                        "source_image": str(image),
                        "stem": "clip_001",
                        "panel": "4",
                    }
                )
                full = reel_gui.asset_select_panel_api(
                    {
                        "source_image": str(image),
                        "stem": "clip_001",
                        "panel": "full_image",
                    }
                )

            self.assertEqual(panel["crop_box"], [0, 100, 100, 200])
            self.assertEqual(full["crop_box"], [0, 0, 300, 200])
            self.assertTrue(Path(panel["path"]).exists())
            self.assertTrue(Path(panel["start_image_path"]).exists())
            self.assertIn("start_image_url", panel)

    def test_gui_create_image_response_exposes_normalized_fields(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "project_data"
            raw = root / "00_source_videos"
            prompt = root / "prompt.json"
            image = data / "generated_assets" / "clip_001_soul_image.png"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            fake = {
                "ok": True,
                "path": str(raw / "clip_001.generated_asset_lineage.json"),
                "campaign_record": {"asset_generation_id": "asset_1"},
                "lineage": {
                    "generation": {
                        "imageJobId": "img_1",
                        "imageResultUrl": "https://example.test/img.png",
                    },
                    "assets": {"localPaths": {"image": str(image)}},
                },
            }
            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "DATA_DIR", data),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "create_image_asset", return_value=fake),
            ):
                result = reel_gui.asset_create_image_api(
                    {"prompt_json": str(prompt), "stem": "clip_001"}
                )

            self.assertEqual(result["image_job_id"], "img_1")
            self.assertEqual(result["image_result_url"], "https://example.test/img.png")
            self.assertEqual(result["local_image_path"], str(image))
            self.assertEqual(result["asset_generation_id"], "asset_1")
            self.assertEqual(
                result["lineage_path"],
                str(raw / "clip_001.generated_asset_lineage.json"),
            )

    def test_gui_create_video_response_exposes_normalized_fields(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            prompt = root / "prompt.json"
            start = root / "start.png"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            start.write_bytes(b"png")
            fake = {
                "ok": True,
                "path": str(raw / "clip_001.generated_asset_lineage.json"),
                "campaign_record": {"asset_generation_id": "asset_2"},
                "lineage": {
                    "generation": {
                        "videoJobId": "vid_1",
                        "videoResultUrl": "https://example.test/video.mp4",
                    },
                    "assets": {"localPaths": {}},
                },
            }
            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "create_video_asset", return_value=fake),
            ):
                result = reel_gui.asset_create_video_api(
                    {
                        "prompt_json": str(prompt),
                        "stem": "clip_001",
                        "start_image": str(start),
                    }
                )

            self.assertEqual(result["video_job_id"], "vid_1")
            self.assertEqual(
                result["video_result_url"], "https://example.test/video.mp4"
            )
            self.assertEqual(result["asset_generation_id"], "asset_2")
            self.assertEqual(
                result["lineage_path"],
                str(raw / "clip_001.generated_asset_lineage.json"),
            )

    def test_gui_create_video_updates_existing_asset_without_new_campaign_record(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            prompt = root / "prompt.json"
            start = root / "start.png"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            start.write_bytes(b"png")
            captured = {}

            def fake_create(plan, *, wait, download):
                captured["campaign"] = plan.campaign
                captured["creator"] = plan.creator
                return {
                    "ok": True,
                    "path": str(raw / "clip_001.generated_asset_lineage.json"),
                    "lineage": {
                        "generation": {
                            "videoJobId": "vid_1",
                            "videoResultUrl": "https://example.test/video.mp4",
                        },
                        "assets": {"localPaths": {}},
                    },
                }

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "create_video_asset", side_effect=fake_create),
                patch.object(
                    reel_gui, "update_asset_generation", return_value={"ok": True}
                ),
            ):
                result = reel_gui.asset_create_video_api(
                    {
                        "prompt_json": str(prompt),
                        "stem": "clip_001",
                        "start_image": str(start),
                        "campaign": "Campaign",
                        "creator": "Stacey",
                        "asset_generation_id": "asset_existing",
                    }
                )

            self.assertIsNone(captured["campaign"])
            self.assertIsNone(captured["creator"])
            self.assertEqual(result["asset_generation_id"], "asset_existing")

    def test_gui_fanout_dry_run_crops_each_detected_panel_and_updates_lineage(self):
        import reel_gui
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            data = root / "project_data"
            raw.mkdir(parents=True)
            source = data / "generated_assets" / "clip_001_soul_image.png"
            source.parent.mkdir(parents=True)
            image = Image.new("RGB", (324, 224), (245, 245, 245))
            colors = [
                (180, 40, 40),
                (40, 150, 90),
                (60, 90, 190),
                (190, 160, 40),
                (170, 70, 170),
                (40, 170, 180),
            ]
            for idx, color in enumerate(colors):
                col = idx % 3
                row = idx // 3
                for x in range(12 + col * 100, 12 + (col + 1) * 100):
                    for y in range(12 + row * 100, 12 + (row + 1) * 100):
                        image.putpixel((x, y), color)
            image.save(source)
            prompt = root / "prompts" / "clip_001_grok.json"
            prompt.parent.mkdir()
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            lineage = raw / "clip_001.generated_asset_lineage.json"
            lineage.write_text(
                json.dumps(
                    {"generation": {}, "assets": {"localPaths": {"image": str(source)}}}
                ),
                encoding="utf-8",
            )

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "DATA_DIR", data),
                patch.object(reel_gui, "RAW_DIR", raw),
            ):
                result = reel_gui.asset_fanout_panels_api(
                    {
                        "stem": "clip_001",
                        "prompt_json": str(prompt),
                        "source_image": str(source),
                        "lineage_path": str(lineage),
                        "dry_run": True,
                    }
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["planned"], 6)
            self.assertEqual(
                result["gridDetection"]["gridPreset"], {"columns": 3, "rows": 2}
            )
            self.assertTrue(
                all(
                    Path(panel["startImagePath"]).exists()
                    for panel in result["cropManifest"]["panelCrops"]
                )
            )
            prompt_paths = {panel["promptJsonPath"] for panel in result["panels"]}
            self.assertEqual(len(prompt_paths), 1)
            self.assertTrue(
                next(iter(prompt_paths)).endswith("_shared_kling_motion_prompt.json")
            )
            self.assertTrue(
                all(panel["sharedMotionPrompt"] for panel in result["panels"])
            )
            updated = json.loads(lineage.read_text(encoding="utf-8"))
            self.assertEqual(len(updated["generation"]["panelCrops"]), 6)
            self.assertIn("panelStartImages", updated["assets"]["localPaths"])

    def test_gui_fanout_honors_grid_layout_override(self):
        import reel_gui
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            data = root / "project_data"
            raw.mkdir(parents=True)
            source = data / "generated_assets" / "clip_001_soul_image.png"
            source.parent.mkdir(parents=True)
            Image.new("RGB", (2048, 1536), (60, 50, 42)).save(source)
            prompt = root / "prompts" / "clip_001_grok.json"
            prompt.parent.mkdir()
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "DATA_DIR", data),
                patch.object(reel_gui, "RAW_DIR", raw),
            ):
                result = reel_gui.asset_fanout_panels_api(
                    {
                        "stem": "clip_001",
                        "prompt_json": str(prompt),
                        "source_image": str(source),
                        "grid_layout": "2x2",
                        "dry_run": True,
                    }
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["planned"], 4)
            self.assertEqual(
                result["gridDetection"]["gridPreset"], {"columns": 2, "rows": 2}
            )
            self.assertEqual(result["gridDetection"]["confidence"], "operator_override")

    def test_gui_fanout_create_records_partial_failures(self):
        import reel_gui
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            data = root / "project_data"
            raw.mkdir(parents=True)
            source = data / "generated_assets" / "clip_001_soul_image.png"
            source.parent.mkdir(parents=True)
            Image.new("RGB", (300, 200), "white").save(source)
            prompt = root / "prompts" / "clip_001_grok.json"
            prompt.parent.mkdir()
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )

            def fake_create(plan, *, wait, download):
                if "_panel_02_" in plan.stem:
                    return {
                        "ok": False,
                        "path": str(raw / f"{plan.stem}.json"),
                        "lineage": {"generation": {}},
                        "error": "quota",
                    }
                return {
                    "ok": True,
                    "path": str(raw / f"{plan.stem}.json"),
                    "lineage": {
                        "generation": {
                            "videoJobId": f"vid_{plan.selected_panel}",
                            "videoResultUrl": f"https://example.test/{plan.selected_panel}.mp4",
                        }
                    },
                }

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "DATA_DIR", data),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "create_video_asset", side_effect=fake_create),
            ):
                result = reel_gui.asset_fanout_panels_api(
                    {
                        "stem": "clip_001",
                        "prompt_json": str(prompt),
                        "source_image": str(source),
                        "dry_run": False,
                        "max_jobs": 3,
                    }
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["created"], 2)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(
                [panel["status"] for panel in result["panels"]],
                ["created", "failed", "created"],
            )

    def test_gui_download_video_uses_stored_asset_generation_url(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            cap = root / "01_captions"
            raw.mkdir()
            cap.mkdir()
            prompt = root / "prompt.json"
            prompt.write_text(
                json.dumps(
                    {
                        "higgsfieldGridPrompt": "grid prompt",
                        "klingMotionPrompt": "motion prompt",
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            create_campaign(
                root,
                name="Download Campaign",
                creator="Stacey",
                account="acct",
                platform="instagram_reels",
            )
            lineage = {
                "source": {
                    "selectedPanel": "full_image",
                    "startImage": str(root / "start.png"),
                },
                "generation": {
                    "soulId": "5828d958-91dd-4d6d-8909-934503f47644",
                    "videoJobId": "vid_1",
                    "videoResultUrl": "https://example.test/video.mp4",
                    "raw": {
                        "image": {
                            "params": {
                                "custom_reference_id": "5828d958-91dd-4d6d-8909-934503f47644"
                            }
                        }
                    },
                },
                "assets": {"localPaths": {}},
            }
            record = record_asset_generation(
                root,
                campaign="Download Campaign",
                creator="Stacey",
                prompt_json_path=prompt,
                stem="clip_001",
                lineage_path=root / "lineage.json",
                lineage=lineage,
            )

            def fake_download(url, out):
                Path(out).write_bytes(b"mp4")
                return str(out), None

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "CAP_DIR", cap),
                patch.object(
                    reel_gui.urllib.request, "urlretrieve", side_effect=fake_download
                ),
            ):
                result = reel_gui.asset_download_video_api(
                    {
                        "stem": "clip_001",
                        "prompt_json": str(prompt),
                        "asset_generation_id": record["asset_generation_id"],
                    }
                )

            self.assertEqual(result["downloaded_stem"], "clip_001")
            self.assertTrue((raw / "clip_001.mp4").exists())
            sidecar = json.loads(
                (raw / "clip_001.generated_asset_lineage.json").read_text()
            )
            self.assertEqual(
                sidecar["generation"]["videoResultUrl"],
                "https://example.test/video.mp4",
            )

    def test_gui_prompt_generate_uses_live_grok_direct_prompt_preview(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "ref.jpg"
            ref.write_bytes(b"jpg")
            create_campaign(
                root,
                name="Prompt Campaign",
                creator="Stacey",
                account="acct",
                platform="instagram_reels",
            )
            fake_raw = {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "image_prompt": (
                                            "Create one high-quality native 2x3 grid featuring six variations of the exact same stunning woman "
                                            "with a perfect face, deep cleavage, round ass emphasis, skin-tight fabric cling, bright lighting, and sharp focus"
                                        ),
                                        "notes": "manual Grok image prompt response shape",
                                    }
                                ),
                            }
                        ]
                    }
                ]
            }
            with (
                patch.object(reel_gui, "ROOT", root),
                patch("generate_prompts.load_xai_api_key", return_value="key"),
                patch("generate_prompts.call_grok", return_value=fake_raw) as grok,
            ):
                result = reel_gui.prompt_generate_api(
                    {
                        "reference_image": str(ref),
                        "out": str(root / "prompt.json"),
                        "campaign": "Prompt Campaign",
                        "creator": "Stacey",
                    }
                )

            self.assertTrue(result["dry_run"])
            self.assertEqual(
                result["prompt_mode"], REFERENCE_FACTORY_SEXY_REALISTIC_MODE
            )
            self.assertEqual(
                result["prompt_source"], "live_grok_direct_higgsfield_prompt"
            )
            self.assertIn("cleaned_prompt", result["lineage"])
            self.assertNotIn(
                "perfect face", result["lineage"]["cleaned_prompt"].lower()
            )
            self.assertNotIn("sharp focus", result["lineage"]["cleaned_prompt"].lower())
            self.assertIn("instruction_preview", result)
            grok.assert_called_once()
            conn = campaign_connect(root)
            count = conn.execute("SELECT COUNT(*) AS n FROM prompt_runs").fetchone()[
                "n"
            ]
            self.assertEqual(count, 0)

    def test_gui_active_action_labels_use_direct_reference_language(self):
        import reel_gui

        payload = json.dumps(reel_gui.next_action_for_status("Needs Soul")).lower()
        self.assertIn("reference still", payload)
        self.assertNotIn("grok", payload)
        self.assertNotIn("2x3", payload)
        self.assertNotIn("six panel", payload)
        self.assertNotIn("cropped panel", payload)

    def test_gui_direct_reference_dry_run_uses_active_single_image_path(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            data = root / "project_data"
            raw.mkdir()
            data.mkdir()
            ref = root / "reference.jpg"
            ref.write_bytes(b"jpg")

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "DATA_DIR", data),
            ):
                result = reel_gui.asset_reference_image_dry_run_api(
                    {
                        "reference": str(ref),
                        "stem": "clip_001",
                        "creator": "Stacey",
                        "body_emphasis": "bust_hips",
                        "wait": True,
                    }
                )

            self.assertEqual(result["workflow"], "higgsfield_direct_reference_image")
            command_text = " ".join(result["commands"][0])
            self.assertIn("--image", result["commands"][0])
            image_arg = result["commands"][0][
                result["commands"][0].index("--image") + 1
            ]
            self.assertEqual(Path(image_arg).resolve(), ref.resolve())
            self.assertIn("--custom_reference_id", result["commands"][0])
            self.assertIn("d63ea9c7-b2c7-439c-bf0c-edfdf9938a36", result["commands"][0])
            self.assertIn("--aspect_ratio 3:4", command_text)
            self.assertNotIn("grid_layout", command_text)
            self.assertNotIn("2x3", command_text.lower())
            self.assertNotIn("six panel", command_text.lower())
            self.assertNotIn("cropped panel", command_text.lower())

    def test_active_docs_describe_direct_reference_not_grok_grid_production(self):
        docs = [
            REEL_ROOT / "CURRENT_PRODUCTION_FLOW.md",
            REEL_ROOT / "PIPELINE_BOUNDARIES.md",
            REEL_ROOT / "AGENTS.md",
            REEL_ROOT / "docs/next_chat_reel_factory_handoff.md",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in docs).lower()
        self.assertIn("direct reference-image", combined)
        self.assertIn("9:16", combined)
        self.assertNotIn("current default image grid aspect ratio is `4:3`", combined)
        self.assertNotIn(
            "reference frames are sent to grok for prompt creation", combined
        )
        self.assertNotIn(
            "do not pass reference images into higgsfield image generation", combined
        )
        self.assertNotIn("grid layout default", combined)

    def test_reel_url_downloader_stages_and_moves_mp4(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_run(cmd, capture_output, text, timeout):
                template = Path(cmd[cmd.index("-o") + 1])
                out = Path(str(template).replace("%(ext)s", "mp4"))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"mp4")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with (
                patch("reel_url_import.shutil.which", return_value="/usr/bin/yt-dlp"),
                patch("reel_url_import.subprocess.run", side_effect=fake_run),
            ):
                result = download_reel_url(
                    "https://www.instagram.com/reel/example/",
                    out_dir=root,
                    stem="clip_001",
                )

            self.assertTrue((root / "clip_001.mp4").exists())
            self.assertEqual(result["stem"], "clip_001")
            self.assertIn("yt-dlp", result["command"][0])

    def test_gui_reel_url_import_downloads_adds_reference_and_prompt(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            cap = root / "01_captions"
            raw.mkdir()
            cap.mkdir()
            create_campaign(
                root,
                name="URL Campaign",
                creator="Stacey",
                account="acct",
                platform="instagram_reels",
            )

            def fake_download(url, *, out_dir, stem):
                out = Path(out_dir) / f"{stem}.mp4"
                out.write_bytes(b"mp4")
                return {
                    "ok": True,
                    "url": url,
                    "stem": stem,
                    "path": str(out.resolve()),
                    "command": ["yt-dlp"],
                }

            fake_prompt = {
                "ok": True,
                "prompt_json_path": str(root / "prompts" / "clip_001_grok.json"),
                "prompt": {
                    "higgsfieldGridPrompt": "grid prompt",
                    "klingMotionPrompt": "motion prompt",
                    "notes": "ok",
                },
            }

            with (
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(reel_gui, "CAP_DIR", cap),
                patch.object(reel_gui, "download_reel_url", side_effect=fake_download),
                patch.object(reel_gui, "generate_prompt", return_value=fake_prompt),
            ):
                result = reel_gui.import_reel_url_api(
                    {
                        "url": "https://www.instagram.com/reel/example/",
                        "campaign": "URL Campaign",
                        "stem": "clip_001",
                        "generate_prompt": True,
                    }
                )

            self.assertEqual(result["stem"], "clip_001")
            self.assertTrue((raw / "clip_001.mp4").exists())
            self.assertTrue((cap / "clip_001.json").exists())
            self.assertTrue(result["reference_record"]["reference_id"])
            self.assertTrue(result["prompt"]["ok"])

    def test_ollama_parser_accepts_valid_json(self):
        self.assertEqual(parse_hook_response('{"hooks":["one","two"]}'), ["one", "two"])
        self.assertEqual(parse_hook_response('{"hook":"one"}'), ["one"])

    def test_ollama_parser_rejects_malformed_json(self):
        with self.assertRaises(ValueError):
            parse_hook_response("not json")

    def test_hook_rewrite_validator_preserves_numbers_and_length(self):
        ok, reason = validate_hook_variant(
            "dating a 30 year old",
            "dating a 30 year old again",
            min_chars=5,
            max_chars=80,
        )
        self.assertTrue(ok, reason)
        ok, reason = validate_hook_variant(
            "dating a 30 year old",
            "dating him again",
            min_chars=5,
            max_chars=80,
        )
        self.assertFalse(ok)
        self.assertIn("30", reason)

    def test_hook_rewrite_validator_rejects_identical_and_low_similarity(self):
        accepted, rejected = validate_hook_variants(
            "when he says he misses you",
            ["when he says he misses you", "completely unrelated topic"],
            min_chars=5,
            max_chars=80,
            reject_identical=True,
            min_similarity=0.7,
            embedding_model="hash-v1",
        )
        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["reason"], "identical_to_source")
        self.assertTrue(rejected[1]["reason"].startswith("low_semantic_similarity"))

    def test_strict_validator_does_not_require_all_keywords_literally(self):
        ok, reason = validate_hook_variant(
            "when he says he misses you",
            "He's missing you",
            min_chars=5,
            max_chars=80,
            strict=True,
            min_similarity=0.18,
            embedding_model="hash-v1",
        )
        self.assertTrue(ok, reason)
        ok, reason = validate_hook_variant(
            "when he says he misses you",
            "Whenever he mentions your name",
            min_chars=5,
            max_chars=80,
            strict=True,
            min_similarity=0.18,
            embedding_model="hash-v1",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_core_concept:miss")

    def test_ollama_unavailable_is_graceful(self):
        result = generate_hooks(
            backend="ollama",
            model="definitely_missing_model",
            base="base hook",
            n=1,
            min_chars=5,
            max_chars=80,
        )
        self.assertIn("ok", result)
        self.assertIn("hooks", result)

    def test_ollama_generation_logs_metadata_and_quality(self):
        class FakeProvider:
            def __init__(self, model):
                self.model = model

            def available(self):
                return True, "ok"

            def rewrite(self, base, *, n, min_chars, max_chars, seed=42):
                return [
                    "when he says he misses you again",
                    "x",
                    "when he says he misses you again",
                ]

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "project_data" / "caption_generations.jsonl"
            with patch("hook_ai.OllamaHookProvider", FakeProvider):
                result = generate_hooks(
                    backend="ollama",
                    model="fake",
                    base="when he says he misses you",
                    n=3,
                    min_chars=5,
                    max_chars=80,
                    reject_identical=True,
                    log_path=log_path,
                    recent_hooks=["when he says he misses you again"],
                )
            self.assertTrue(result["ok"])
            self.assertTrue(result["generationId"].startswith("capgen_"))
            self.assertEqual(len(result["hooks"]), 1)
            self.assertEqual(result["quality"][0]["warnings"], ["recent_duplicate"])
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["generationId"], result["generationId"])
            self.assertEqual(
                record["acceptedHooks"][0]["captionHash"],
                result["quality"][0]["captionHash"],
            )
            self.assertEqual(record["rejectedHooks"][0]["reason"], "too_short")

    def test_ollama_net_new_mode_skips_rewrite_similarity_gate(self):
        class FakeProvider:
            def __init__(self, model):
                self.model = model

            def available(self):
                return True, "ok"

            def rewrite(self, base, *, n, min_chars, max_chars, seed=42):
                raise AssertionError("net_new should not call rewrite")

            def generate_prompt(self, prompt, *, n, seed=42, temperature=0.2):
                self.prompt = prompt
                self.temperature = temperature
                return ["pick the door he would never open"]

        with patch("hook_ai.OllamaHookProvider", FakeProvider):
            result = generate_hooks(
                backend="ollama",
                model="fake",
                base="when he says he misses you",
                mode="net_new",
                n=1,
                min_chars=5,
                max_chars=80,
                required_terms=["misses"],
                min_similarity=0.95,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "net_new")
        self.assertEqual(result["hooks"], ["pick the door he would never open"])

    def test_caption_quality_flags_basic_review_warnings(self):
        quality = score_caption_quality(
            "hi\nthere\nagain\nand\nagain\nand\nagain",
            recent_hooks=["something else"],
            min_chars=5,
            max_chars=20,
        )
        self.assertIn("too_many_lines", quality["warnings"])
        self.assertIn("weak_first_line_hook", quality["warnings"])
        self.assertIn("too_long", quality["warnings"])

    def test_caption_quality_uses_rate_aware_performance_signal(self):
        low = score_caption_quality(
            "which one would you pick?",
            performance={
                "views": 1000,
                "likes": 1,
                "comments": 0,
                "shares": 0,
                "saves": 0,
            },
        )
        high = score_caption_quality(
            "which one would you pick?",
            performance={
                "views": 1000,
                "likes": 180,
                "comments": 20,
                "shares": 10,
                "saves": 15,
            },
        )

        self.assertGreater(high["performanceScore"], low["performanceScore"])
        self.assertGreater(high["qualityScore"], low["qualityScore"])
        self.assertEqual(high["hookFeatures"]["archetype"], "curiosity")

    def test_caption_library_and_rank_existing_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "project_data" / "caption_generations.jsonl"
            log_path.parent.mkdir()
            record = {
                "schema": "reel_factory.caption_generation.v1",
                "generationId": "capgen_1",
                "createdAt": "2026-01-01T00:00:00+00:00",
                "backend": "ollama",
                "model": "fake",
                "promptHash": "prompt_hash",
                "baseHook": "base",
                "acceptedHooks": [
                    {
                        "text": "strong caption hook",
                        "captionHash": "hash_1",
                        "charCount": 19,
                        "lineCount": 1,
                        "qualityScore": 100,
                        "warnings": [],
                    }
                ],
                "rejectedHooks": [
                    {
                        "hook": "x",
                        "reason": "too_short",
                        "quality": {
                            "captionHash": "hash_2",
                            "charCount": 1,
                            "lineCount": 1,
                            "qualityScore": 85,
                            "warnings": ["too_short"],
                        },
                    }
                ],
            }
            log_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            library = caption_library(log_path)
            self.assertEqual(library["count"], 2)
            self.assertEqual(library["captions"][0]["state"], "accepted")
            cap_dir = root / "01_captions"
            cap_dir.mkdir()
            (cap_dir / "clip_010.json").write_text(
                json.dumps(
                    {
                        "hooks": ["strong caption hook", "x", "strong caption hook"],
                        "generation": {"generation_id": "capgen_1", "model": "fake"},
                    }
                ),
                encoding="utf-8",
            )
            ranked = rank_clip_sidecar(
                cap_dir,
                "clip_010",
                top=2,
                performance_by_caption_hash={
                    score_caption_quality("strong caption hook")["captionHash"]: {
                        "totals": {"views": 5000, "shares": 30, "saves": 25}
                    }
                },
            )
            self.assertEqual(ranked["clip"], "clip_010")
            self.assertEqual(ranked["ranked"][0]["text"], "strong caption hook")
            self.assertIn(
                "matching caption has positive history", ranked["ranked"][0]["reasons"]
            )
            self.assertTrue(
                any(
                    "duplicate_in_batch" in row["quality"]["warnings"]
                    for row in ranked["ranked"]
                )
            )

    def test_save_hooks_preserves_generation_metadata(self):
        import reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            cap_dir = Path(tmp)
            generation = {
                "generation_id": "capgen_test",
                "model": "fake",
                "backend": "ollama",
                "caption_hashes": ["hash_1"],
            }
            with patch.object(reel_gui, "CAP_DIR", cap_dir):
                result = reel_gui.save_hooks(
                    "clip_001", {"hooks": ["hook one"], "generation": generation}
                )
            self.assertTrue(result["ok"])
            sidecar = json.loads(
                (cap_dir / "clip_001.json").read_text(encoding="utf-8")
            )
            self.assertEqual(sidecar["generation"]["generation_id"], "capgen_test")
            self.assertEqual(sidecar["hooks"], ["hook one"])

    def test_semantic_duplicate_grouping_and_library_group(self):
        hooks = ["when he says he misses you", "when he says he misses u"]
        dupes = find_semantic_duplicates(hooks, threshold=0.55)
        self.assertTrue(dupes)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook_library.json"
            a = save_hook_to_library(path, hooks[0])
            b = save_hook_to_library(path, hooks[1])
            self.assertEqual(a["semantic_group"], b["semantic_group"])

    def test_hook_library_reindex_preserves_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook_library.json"
            a = save_hook_to_library(path, "when he misses you")
            result = reindex_hook_library(path, embedding_model="hash-v1")
            self.assertEqual(result["count"], 1)
            self.assertEqual(
                save_hook_to_library(path, "when he misses you")["id"], a["id"]
            )

    def test_hash_embedding_provider_is_deterministic(self):
        provider = HashEmbeddingProvider()
        self.assertEqual(provider.embed("you miss me"), provider.embed("you miss me"))

    def test_pose_penalty_changes_lane_score(self):
        plain = score_lanes(stddev_samples=[(1.0, 1.0, 1.0)], center_penalty=0)
        posed = score_lanes(
            stddev_samples=[(1.0, 1.0, 1.0)],
            pose_samples=[(0.0, 100.0, 0.0)],
            center_penalty=0,
        )
        self.assertGreater(posed.scores["center"], plain.scores["center"])

    def test_pango_renderer_flag_falls_back_to_pillow(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cap.png"
            render_caption_png(
                "hello world",
                font_family="Onest",
                fonts_dir=Path("fonts"),
                color_scheme="light",
                band="top",
                style="classic",
                out_path=out,
                renderer="pango",
            )
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)

    def test_encoder_profiles_generate_expected_args(self):
        base = dict(
            src=Path("in.mp4"),
            caption_pngs=[],
            recipe=Recipe("v01_original"),
            out=Path("out.mp4"),
            duration=2.0,
            fonts_dir=Path("fonts"),
            src_hash="abc",
            src_dims=(1080, 1920),
        )
        cpu = build_ffmpeg_cmd(
            RenderPlan(**base, output_profile="cpu_h264_x264"), "ffmpeg"
        )
        self.assertIn("libx264", cpu)
        nvenc = build_ffmpeg_cmd(
            RenderPlan(**base, output_profile="linux_nvenc"), "ffmpeg"
        )
        self.assertIn("h264_nvenc", nvenc)
        with self.assertRaises(ValueError):
            build_ffmpeg_cmd(RenderPlan(**base, output_profile="linux_vaapi"), "ffmpeg")

    def test_thumbnail_naming_is_deterministic(self):
        path = Path("02_processed/clip_001/example.mp4")
        self.assertEqual(thumbnail_path_for(path).name, "example_thumb.png")

    def test_audio_mux_output_naming_is_deterministic(self):
        audio = Path("03_audio_library/trending.mp3")
        video = Path("02_processed/clip_001/example.mp4")
        self.assertIn(audio_id(audio), output_path_for(video, audio).name)
        self.assertTrue(output_path_for(video, audio).name.startswith("example_audio_"))

    def test_qc_regression_parsers(self):
        self.assertEqual(_parse_ssim("n:1 All:0.991234 (20.1)"), 0.991234)
        self.assertEqual(_parse_psnr("average:41.22 min:40.0 max:inf"), 41.22)

    def test_upload_ready_qc_flags_missing_social_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.mp4"
            path.write_bytes(b"not a real mp4, ffprobe is mocked" + b"x" * (600 * 1024))
            probe_json = {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1080,
                        "height": 1920,
                        "avg_frame_rate": "30/1",
                        "tags": {"handler_name": "VideoHandler"},
                    }
                ],
                "format": {
                    "duration": "3.0",
                    "tags": {"encoder": "Lavf60.0.0"},
                },
            }
            with (
                patch("qc_check._ffprobe_json", return_value=probe_json),
                patch("qc_check._has_faststart", return_value=False),
            ):
                rec = probe_with_audio_mode(path, upload_ready=True)

            reasons = " ".join(rec.reasons)
            self.assertIn("missing_faststart", reasons)
            self.assertIn("missing_creation_time", reasons)
            self.assertIn("generic_handler_name", reasons)
            self.assertIn("suspicious_metadata", " ".join(rec.warnings))

    def test_render_queue_state_transitions_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RenderQueue(Path(tmp))
            job_id = queue.enqueue(
                job_key="abc",
                command=["python3", "--version"],
                cwd=Path(tmp),
                max_attempts=1,
            )
            job = queue.claim("worker-1")
            self.assertEqual(job["job_id"], job_id)
            queue.mark_running(job_id, "worker-1")
            queue.conn.execute(
                "UPDATE queue_jobs SET heartbeat_at = 1 WHERE job_id = ?", (job_id,)
            )
            self.assertEqual(queue.recover_stale(stale_after_sec=1), 1)
            self.assertEqual(queue.status()["counts"]["interrupted"], 1)

    def test_render_queue_claim_lost_race_returns_none(self):
        class RaceConnection:
            def __init__(self, real, winner_queue):
                self._real = real
                self._winner_queue = winner_queue
                self._raced = False

            def execute(self, sql, parameters=()):
                if (
                    not self._raced
                    and "SELECT * FROM queue_jobs WHERE status = 'queued'" in sql
                ):
                    row = self._real.execute(sql, parameters).fetchone()
                    self._winner_queue.claim("worker-1")
                    self._raced = True

                    class Result:
                        def fetchone(self):
                            return row

                    return Result()
                return self._real.execute(sql, parameters)

            def commit(self):
                return self._real.commit()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            winner = RenderQueue(root)
            loser = RenderQueue(root)
            job_id = winner.enqueue(
                job_key="abc",
                command=["python3", "--version"],
                cwd=root,
                max_attempts=1,
            )
            loser.conn = RaceConnection(loser.conn, winner)

            self.assertIsNone(loser.claim("worker-2"))
            row = winner.conn.execute(
                "SELECT status, worker_id FROM queue_jobs WHERE job_id=?", (job_id,)
            ).fetchone()

            self.assertEqual(row["status"], "claimed")
            self.assertEqual(row["worker_id"], "worker-1")


if __name__ == "__main__":
    unittest.main()
