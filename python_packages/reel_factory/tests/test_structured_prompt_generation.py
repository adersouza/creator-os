import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from generate_prompts import (
    JSON_STRUCTURED_RECREATION_MODE,
    build_json_structured_recreation_instruction,
    clean_direct_higgsfield_prompt,
    generate_prompt,
    normalize_structured_recreation_spec,
    structured_recreation_spec_to_prompt,
)


class StructuredPromptGenerationTests(unittest.TestCase):
    def test_instruction_requests_auditable_json_contract(self):
        instruction = build_json_structured_recreation_instruction(
            "preserve the outfit check pose",
            grid_layout="3x2",
            image_aspect_ratio="4:3",
        )

        self.assertIn('"schema": "reel_factory.reference_recreation_prompt.v1"', instruction)
        self.assertIn("strict JSON object", instruction)
        self.assertIn("wardrobe", instruction)
        self.assertIn("qualityConstraints", instruction)
        self.assertIn("one native 6-panel grid", instruction)
        self.assertIn("adult woman, age 20+", instruction)
        self.assertIn("Do not describe identity-locked details", instruction)
        self.assertIn("preserve the outfit check pose", instruction)

    def test_normalizer_removes_identity_and_ui_fields(self):
        raw = {
            "schema": "reel_factory.reference_recreation_prompt.v1",
            "adultSubject": True,
            "scene": {
                "environment": "bedroom mirror selfie",
                "username": "bad ui label",
                "background": "white dresser and warm lamp",
            },
            "subject": {
                "bodyPose": "standing hip popped toward mirror",
                "hair": "long brunette hair",
                "silhouetteEmphasis": ["tiny waist", "wide hips"],
            },
            "wardrobe": {
                "garmentFamily": "fitted mini dress",
                "fit": "bodycon",
                "colorPalette": ["blue"],
            },
            "qualityConstraints": {
                "noText": True,
                "watermark": "bad watermark instruction",
            },
            "extra": "ignored",
        }

        spec = normalize_structured_recreation_spec(json.dumps(raw))

        self.assertEqual(spec["schema"], "reel_factory.reference_recreation_prompt.v1")
        self.assertTrue(spec["adultSubject"])
        self.assertNotIn("extra", spec)
        self.assertNotIn("username", spec["scene"])
        self.assertNotIn("hair", spec["subject"])
        self.assertNotIn("watermark", spec["qualityConstraints"])

    def test_structured_spec_compiles_to_higgsfield_prompt(self):
        spec = normalize_structured_recreation_spec(json.dumps({
            "schema": "reel_factory.reference_recreation_prompt.v1",
            "adultSubject": True,
            "scene": {
                "captureStyle": "mirror selfie",
                "environment": "simple bedroom",
                "background": "dresser and plain wall",
            },
            "subject": {
                "bodyPose": "standing with one hip shifted",
                "cameraFacing": "front-facing mirror angle",
                "crop": "head to upper thigh visible",
                "silhouetteEmphasis": ["defined waist", "curvy hip line"],
            },
            "wardrobe": {
                "garmentFamily": "fitted lounge set",
                "upperGarment": "white fitted tank",
                "lowerGarment": "pink fitted shorts",
                "fabric": ["soft ribbed cotton"],
                "fit": "snug",
                "variationPlan": ["white tank with pink shorts", "black tank with gray shorts"],
            },
            "lighting": {"quality": "warm indoor light"},
            "camera": {"shotType": "vertical phone photo"},
            "glamourDirection": {
                "bodyForwardCues": ["confident posture"],
                "garmentCues": ["fabric follows silhouette"],
            },
        }))

        prompt = structured_recreation_spec_to_prompt(spec, grid_layout="3x2")
        cleanup = clean_direct_higgsfield_prompt(prompt)

        self.assertIn("Create one high-quality six-panel grid image", prompt)
        self.assertIn("mirror selfie", prompt)
        self.assertIn("fitted lounge set", prompt)
        self.assertIn("white tank with pink shorts", prompt)
        self.assertIn("clean image-only composition", prompt.lower())
        self.assertIn("complete head visible", prompt.lower())
        self.assertTrue(cleanup["valid"])
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_mode_constant_is_cli_safe(self):
        self.assertEqual(JSON_STRUCTURED_RECREATION_MODE, "json-structured")

    def test_generate_prompt_json_structured_writes_lineage(self):
        grok_payload = {
            "id": "resp_test",
            "model": "grok-test",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({
                                "schema": "reel_factory.reference_recreation_prompt.v1",
                                "adultSubject": True,
                                "scene": {
                                    "captureStyle": "mirror selfie",
                                    "environment": "bedroom",
                                    "background": "plain wall and dresser",
                                },
                                "subject": {
                                    "bodyPose": "standing with hip shifted",
                                    "cameraFacing": "front mirror angle",
                                    "crop": "head to upper thigh visible",
                                    "silhouetteEmphasis": ["defined waist", "curvy hip line"],
                                },
                                "wardrobe": {
                                    "garmentFamily": "fitted lounge set",
                                    "upperGarment": "white fitted tank",
                                    "lowerGarment": "pink fitted shorts",
                                    "fit": "snug",
                                    "variationPlan": ["white tank pink shorts", "black tank gray shorts"],
                                },
                                "lighting": {"quality": "warm room light"},
                                "camera": {"shotType": "vertical phone photo"},
                                "glamourDirection": {
                                    "bodyForwardCues": ["confident posture"],
                                    "garmentCues": ["fabric follows silhouette"],
                                },
                                "qualityConstraints": {"noText": True, "noUi": True},
                            }),
                        }
                    ]
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "reference.jpg"
            Image.new("RGB", (120, 160), (220, 200, 190)).save(ref)
            out = root / "prompt.json"

            with patch("generate_prompts.load_xai_api_key", return_value="test-key"), patch(
                "generate_prompts.call_grok", return_value=grok_payload
            ):
                result = generate_prompt(
                    out_path=out,
                    root=root,
                    reference_images=[ref],
                    prompt_mode=JSON_STRUCTURED_RECREATION_MODE,
                    dry_run=True,
                    grid_layout="3x2",
                    image_aspect_ratio="4:3",
                )

            prompt_data = json.loads(out.read_text())
            lineage = json.loads(Path(result["lineage_path"]).read_text())
            self.assertEqual(result["prompt_mode"], JSON_STRUCTURED_RECREATION_MODE)
            self.assertEqual(result["prompt_source"], "live_grok_structured_reference_schema")
            self.assertIn("higgsfieldGridPrompt", prompt_data)
            self.assertIn("mirror selfie", prompt_data["higgsfieldGridPrompt"])
            self.assertEqual(
                lineage["structured_prompt_spec"]["schema"],
                "reel_factory.reference_recreation_prompt.v1",
            )
            self.assertEqual(
                result["structured_prompt_spec"]["schema"],
                "reel_factory.reference_recreation_prompt.v1",
            )


if __name__ == "__main__":
    unittest.main()
    generate_prompt,
