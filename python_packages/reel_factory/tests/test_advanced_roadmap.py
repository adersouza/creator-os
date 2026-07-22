import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from reel_factory.ai_visual_qc import record_from_scores, sample_positions
from reel_factory.asset_prompt_contract import (
    AssetPromptSet,
    build_grok_simple_prompt,
    parse_asset_prompt_response,
    write_prompt_template,
)
from reel_factory.audio_intent import write_audio_intent
from reel_factory.audio_mux import audio_id, output_path_for
from reel_factory.caption_generation_log import (
    caption_library,
    rank_clip_sidecar,
    score_caption_quality,
)
from reel_factory.caption_render import render_caption_png
from reel_factory.embedding_index import duplicate_risk, upsert_embedding
from reel_factory.embedding_index import similar as similar_media
from reel_factory.embedding_provider import HashEmbeddingProvider
from reel_factory.evidence_store import (
    connect as campaign_connect,
)
from reel_factory.evidence_store import (
    link_campaign_output,
    record_asset_generation,
    record_prompt_run,
    validate_generation_soul,
)
from reel_factory.generate_assets import (
    AssetGenerationPlan,
    build_image_cmd,
    build_source_lineage,
    extract_url,
    image_identity_flag,
    probe_higgsfield_capabilities,
    resolve_generation_models,
    validate_required_capabilities,
)
from reel_factory.graph_builder import build_ffmpeg_cmd
from reel_factory.hook_ai import (
    generate_hooks,
    parse_hook_response,
    validate_hook_variant,
    validate_hook_variants,
)
from reel_factory.hook_tools import (
    find_semantic_duplicates,
    reindex_hook_library,
    save_hook_to_library,
)
from reel_factory.manifest import Manifest
from reel_factory.media_features import upsert_reel_feature
from reel_factory.placement_scorer import score_lanes
from reel_factory.prompt_guidance import retry_helper_direction
from reel_factory.qc_check import _parse_psnr, _parse_ssim, probe_with_audio_mode
from reel_factory.readiness_check import evaluate_output, run_readiness
from reel_factory.reel_pipeline import Recipe
from reel_factory.reel_url_import import download_reel_url, write_url_sidecar
from reel_factory.render_plan import RenderPlan
from reel_factory.render_queue import RenderQueue, get_queue
from reel_factory.safe_zone import score_safe_zone
from reel_factory.thumbnail_gen import thumbnail_path_for
from reel_factory.xai_vision import build_xai_payload, response_text, strip_json_fence

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

    def test_capability_probe_validates_required_models(self):
        payload = {
            "imageModels": [{"job_type": "text2image_soul_v2"}],
            "videoModels": [{"job_type": "kling3_0"}],
        }
        self.assertTrue(validate_required_capabilities(payload)["ok"])
        payload["videoModels"] = []
        self.assertEqual(
            validate_required_capabilities(payload)["missing"], ["kling3_0"]
        )

    def test_capability_probe_accepts_legacy_model_identifier(self):
        payload = {
            "imageModels": [{"job_set_type": "text2image_soul_v2"}],
            "videoModels": [{"job_set_type": "kling3_0"}],
        }
        self.assertTrue(validate_required_capabilities(payload)["ok"])

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
        image_rows = [{"job_type": "text2image_soul_v2", "type": "image"}]
        video_rows = [{"job_type": "kling3_0", "type": "video"}]

        def fake_run_json(cmd):
            if "--image" in cmd:
                return {"items": image_rows}
            if "--video" in cmd:
                return {"items": video_rows}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch(
                    "reel_factory.generate_assets._run_json", side_effect=fake_run_json
                ),
                patch(
                    "reel_factory.generate_assets._run_text", return_value="help text"
                ),
            ):
                result = probe_higgsfield_capabilities(root, force=True)

            self.assertTrue(result["validation"]["ok"])
            self.assertTrue(
                (root / "project_data" / "higgsfield_capabilities.json").exists()
            )

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

    def test_asset_prompt_contract_writes_empty_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts" / "clip_001_grok.json"

            write_prompt_template(str(path))

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(data),
                ["higgsfieldGridPrompt", "klingMotionPrompt", "notes"],
            )

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

    def test_reel_evidence_schema_excludes_campaign_planner_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = campaign_connect(Path(tmp))
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in {
                "prompt_runs",
                "asset_generations",
                "campaign_outputs",
            }:
                self.assertIn(table, tables)
            self.assertTrue(
                {
                    "creators",
                    "campaigns",
                    "campaign_references",
                    "operator_ratings",
                }.isdisjoint(tables)
            )

    def test_explicit_campaign_keys_flow_through_render_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
                reference_id="reference_factory:gold:mirror-1",
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
            output = link_campaign_output(
                root,
                output_path=out,
                campaign="Test Campaign",
                asset_generation_id=asset_rec["asset_generation_id"],
            )
            self.assertTrue(prompt_rec["prompt_run_id"])
            self.assertEqual(asset_rec["identity"]["status"], "valid")
            self.assertTrue(output["campaign_output_id"])
            conn = campaign_connect(root)
            prompt_row = conn.execute("SELECT * FROM prompt_runs").fetchone()
            asset_row = conn.execute("SELECT * FROM asset_generations").fetchone()
            output_row = conn.execute("SELECT * FROM campaign_outputs").fetchone()
            self.assertEqual(prompt_row["campaign_key"], "Test Campaign")
            self.assertEqual(prompt_row["creator_key"], "Stacey")
            self.assertEqual(
                prompt_row["reference_key"], "reference_factory:gold:mirror-1"
            )
            self.assertEqual(asset_row["campaign_key"], "Test Campaign")
            self.assertEqual(asset_row["creator_key"], "Stacey")
            self.assertEqual(output_row["campaign_key"], "Test Campaign")
            self.assertEqual(output_row["creator_key"], "Stacey")

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

    def test_media_features_derive_creator_and_caption_style_from_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = campaign_connect(root)
            now = int(time.time())
            out = root / "generic_render_name.mp4"
            out.write_bytes(b"video")
            conn.execute(
                """
                INSERT INTO campaign_outputs (
                    campaign_output_id, campaign_key, creator_key, output_path, recipe,
                    caption_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "co_larissa_metadata",
                    "Larissa Metadata",
                    "Larissa",
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

    def test_media_features_prefer_video_analysis_sidecar_over_filename_inference(
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

    def test_duplicate_risk_accepts_legacy_similarity_list_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Manifest(root / "manifest.json")
            out_dir = root / "02_processed" / "clip_001"
            out_dir.mkdir(parents=True)
            candidate = out_dir / "candidate.mp4"
            candidate.write_bytes(b"candidate")
            prior = out_dir / "prior.mp4"
            prior.write_bytes(b"prior")
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

            result = duplicate_risk(
                root, candidate, account="acct", prior_paths=[prior]
            )

            self.assertEqual(result["risk_level"], "high")
            self.assertEqual(result["recommended_action"], "avoid")

    def test_reel_pipeline_accepts_campaign_render_flags(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "reel_factory.reel_pipeline", "--help"],
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

    def test_active_docs_describe_direct_reference_not_grok_grid_production(self):
        docs = [
            REEL_ROOT / "README.md",
            REEL_ROOT / "PIPELINE_BOUNDARIES.md",
            REEL_ROOT / "AGENTS.md",
            REEL_ROOT.parents[1] / "CREATOR_OS_SYSTEM_MAP.md",
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
                info = out.with_suffix(".info.json")
                info.write_text(
                    json.dumps(
                        {
                            "view_count": 1234,
                            "like_count": 88,
                            "upload_date": "20260701",
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with (
                patch(
                    "reel_factory.reel_url_import.shutil.which",
                    return_value="/usr/bin/yt-dlp",
                ),
                patch(
                    "reel_factory.reel_url_import.subprocess.run", side_effect=fake_run
                ),
            ):
                result = download_reel_url(
                    "https://www.instagram.com/reel/example/",
                    out_dir=root,
                    stem="clip_001",
                )

            self.assertTrue((root / "clip_001.mp4").exists())
            self.assertEqual(result["stem"], "clip_001")
            self.assertIn("yt-dlp", result["command"][0])
            self.assertIn("--write-info-json", result["command"])
            self.assertEqual(result["sourceMetrics"]["view_count"], 1234)
            self.assertEqual(
                result["infoJsonPath"], str((root / "clip_001.info.json").resolve())
            )
            self.assertTrue((root / "clip_001.info.json").exists())

    def test_reel_url_downloader_retries_transient_failure(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {"count": 0}

            def fake_run(cmd, capture_output, text, timeout):
                calls["count"] += 1
                if calls["count"] == 1:
                    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="429")
                template = Path(cmd[cmd.index("-o") + 1])
                out = Path(str(template).replace("%(ext)s", "mp4"))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"mp4")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with (
                patch(
                    "reel_factory.reel_url_import.shutil.which",
                    return_value="/usr/bin/yt-dlp",
                ),
                patch(
                    "reel_factory.reel_url_import.subprocess.run", side_effect=fake_run
                ),
                patch("reel_factory.reel_url_import.time.sleep", return_value=None),
            ):
                result = download_reel_url(
                    "https://www.instagram.com/reel/retry/",
                    out_dir=root,
                    stem="clip_retry",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(calls["count"], 2)

    def test_reel_url_downloader_rejects_link_local_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "public http"):
                download_reel_url(
                    "http://169.254.169.254/latest/meta-data/",
                    out_dir=Path(tmp),
                    stem="clip_ssrf",
                )

    def test_reel_url_downloader_rejects_unsafe_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "safe stem"):
                download_reel_url(
                    "https://www.instagram.com/reel/example/",
                    out_dir=Path(tmp),
                    stem="../escape",
                )

    def test_reel_url_downloader_skips_already_imported_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "clip_existing.mp4"
            existing.write_bytes(b"mp4")
            write_url_sidecar(
                root / "clip_existing.reel_url_import.json",
                {
                    "url": "https://www.instagram.com/reel/existing/",
                    "stem": "clip_existing",
                    "sourceVideoPath": str(existing),
                    "sourceMetrics": {"view_count": 10},
                },
            )

            result = download_reel_url(
                "https://www.instagram.com/reel/existing/",
                out_dir=root,
                stem="clip_new",
            )

            self.assertTrue(result["skipped"])
            self.assertEqual(result["reason"], "already_imported_url")
            self.assertEqual(result["path"], str(existing))

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
            with patch("reel_factory.hook_ai.OllamaHookProvider", FakeProvider):
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

        with patch("reel_factory.hook_ai.OllamaHookProvider", FakeProvider):
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
            self.assertIn("strong local quality", ranked["ranked"][0]["reasons"])
            self.assertTrue(
                any(
                    "duplicate_in_batch" in row["quality"]["warnings"]
                    for row in ranked["ranked"]
                )
            )

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
                patch("reel_factory.qc_check._ffprobe_json", return_value=probe_json),
                patch("reel_factory.qc_check._has_faststart", return_value=False),
            ):
                rec = probe_with_audio_mode(path, upload_ready=True)

            reasons = " ".join(rec.reasons)
            self.assertIn("missing_faststart", reasons)
            self.assertIn("missing_creation_time", reasons)
            self.assertIn("generic_handler_name", reasons)
            self.assertIn("suspicious_metadata", " ".join(rec.warnings))

    def test_render_queue_state_transitions_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = get_queue(Path(tmp))
            self.assertIsInstance(queue, RenderQueue)
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
