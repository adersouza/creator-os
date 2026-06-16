import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from generate_assets import (
    DirectReferenceImagePlan,
    create_direct_reference_image_asset,
    direct_reference_prompt,
    dry_run_direct_reference_image,
    extract_higgsfield_generated_prompt,
)
from reel_motion_prompt import SCENE_TYPES, compile_reel_motion_prompt


CAPABILITIES = {
    "schema": "reel_factory.higgsfield_capabilities.v1",
    "createdAt": 1,
    "imageModels": [{
        "job_set_type": "text2image_soul_v2",
        "parameters": [{"name": "custom_reference_id"}],
    }],
    "videoModels": [{"job_set_type": "kling3_0"}],
}


class DirectReferenceWorkflowTests(unittest.TestCase):
    def test_direct_reference_dry_run_builds_higgsfield_reference_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            reference.write_bytes(b"jpg")
            plan = DirectReferenceImagePlan(
                reference_image=str(reference),
                stem="ref_001",
                soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
                soul_name=None,
                creator="Stacey",
                out_dir=root / "output",
                source_dir=root / "00_source_videos",
            )

            result = dry_run_direct_reference_image(plan, wait=True)
            command = result["commands"][0]

            self.assertEqual(result["workflow"], "higgsfield_direct_reference_image")
            self.assertIn("text2image_soul_v2", command)
            self.assertIn("--image", command)
            self.assertIn(str(reference), command)
            self.assertIn("--custom_reference_id", command)
            self.assertIn("d63ea9c7-b2c7-439c-bf0c-edfdf9938a36", command)
            self.assertIn("--aspect_ratio", command)
            self.assertIn("3:4", command)
            self.assertNotIn("9:16 image", " ".join(command))
            self.assertNotIn("grok", " ".join(command).lower())
            self.assertNotIn("qwen", " ".join(command).lower())

    def test_direct_reference_generation_saves_captured_higgsfield_prompt_and_no_campaign_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            reference.write_bytes(b"jpg")
            plan = DirectReferenceImagePlan(
                reference_image=str(reference),
                stem="ref_001",
                soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
                soul_name=None,
                creator="Stacey",
                out_dir=root / "output",
                source_dir=root / "00_source_videos",
            )
            raw_image = {
                "id": "img_1",
                "status": "completed",
                "result_url": "https://example.test/image.png",
                "params": {"prompt": "Higgsfield generated reference prompt"},
            }

            def fake_download(url, out_path):
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(b"png")
                return out_path

            with patch("generate_assets.ensure_required_capabilities", return_value=CAPABILITIES), \
                 patch("generate_assets._cost_preflight_for_plan", return_value={"allowed": True, "blockingReason": "", "blockingReasons": []}), \
                 patch("generate_assets._run_json", return_value=raw_image), \
                 patch("generate_assets.download_result", side_effect=fake_download):
                result = create_direct_reference_image_asset(plan, wait=True, download=True)

            lineage = result["lineage"]
            self.assertTrue(result["ok"])
            self.assertIsNone(result["campaign_record"])
            self.assertEqual(lineage["generation"]["capturedHiggsfieldPrompt"], "Higgsfield generated reference prompt")
            self.assertEqual(lineage["generation"]["promptPolicy"]["grokUsed"], False)
            self.assertEqual(lineage["generation"]["promptPolicy"]["qwenUsed"], False)
            self.assertEqual(lineage["generation"]["promptPolicy"]["visualSchemaUsed"], False)
            self.assertEqual(lineage["generation"]["params"]["imageAspectRatio"], "3:4")
            self.assertEqual(lineage["generation"]["promptPolicy"]["promptAppendUsed"], False)
            self.assertEqual(lineage["generation"]["promptPolicy"]["capturedPromptReused"], False)
            self.assertEqual(lineage["generation"]["promptPolicy"]["policy"], "reference_image_only")
            self.assertTrue(Path(lineage["assets"]["localPaths"]["image"]).exists())
            self.assertTrue(Path(result["path"]).exists())

    def test_direct_reference_prompt_is_reference_only_seed(self):
        prompt = direct_reference_prompt("3:4")

        self.assertIn("Use the supplied reference image", prompt)
        self.assertIn("3:4 image", prompt)
        self.assertNotIn("cleavage", prompt.lower())
        self.assertNotIn("bust", prompt.lower())
        self.assertNotIn("hips", prompt.lower())
        self.assertNotIn("sexier", prompt.lower())

    def test_direct_reference_prompt_uses_requested_aspect_ratio(self):
        prompt = direct_reference_prompt("9:16")

        self.assertIn("9:16 image", prompt)
        self.assertNotIn("3:4 image", prompt)

    def test_extract_higgsfield_generated_prompt_reads_params_prompt(self):
        raw = {
            "id": "img_1",
            "status": "completed",
            "params": {"prompt": "auto described prompt"},
        }

        self.assertEqual(extract_higgsfield_generated_prompt(raw), "auto described prompt")

    def test_motion_prompt_compiler_covers_every_scene_with_stability_constraints(self):
        for scene_type in sorted(SCENE_TYPES):
            compiled = compile_reel_motion_prompt(
                start_image_path="/tmp/start.png",
                scene_type=scene_type,
                captured_higgsfield_prompt="blue dress on couch",
            )
            prompt = compiled.klingMotionPrompt.lower()

            self.assertEqual(compiled.aspectRatio, "9:16")
            self.assertEqual(compiled.durationSeconds, 5)
            self.assertIn("full head and face visible", prompt)
            self.assertIn("outfit", prompt)
            self.assertIn("setting", prompt)
            self.assertIn("no new text", prompt)
            self.assertIn("no", prompt)
            self.assertNotIn("grid", prompt)
            self.assertNotIn("cropped panel", prompt)

    def test_motion_prompt_rejects_unknown_scene_type(self):
        with self.assertRaisesRegex(ValueError, "unsupported scene_type"):
            compile_reel_motion_prompt(start_image_path="/tmp/start.png", scene_type="runway")


if __name__ == "__main__":
    unittest.main()
