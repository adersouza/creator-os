import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grok_ab_experiment import (
    DEFAULT_AB_IMAGE_ASPECT_RATIO,
    build_example_led_instruction,
    build_explicit_emphasis_instruction,
    clean_grok_prompt,
    create_ab_prompt_experiment,
    prompt_contract_from_cleaned,
    run_ab_images_from_sidecar,
)


EXAMPLES = """Create one high-quality native 2x3 grid featuring six variations of the exact same stunning woman taking a mirror selfie in a bright modern kitchen. Exact reference pose in all panels: close-up vertical frame, facing camera directly, soft flirty expression. Outfit variations (1-6): 1. grey fitted hoodie 2. black fitted hoodie 3. soft pink fitted hoodie 4. burgundy fitted hoodie 5. white fitted hoodie 6. charcoal fitted hoodie. Identical close-up selfie composition, white kitchen cabinets, window blinds, wooden ceiling beams, bright natural window lighting, same camera angle and framing across all six panels."""


class GrokAbExperimentTests(unittest.TestCase):
    def test_explicit_emphasis_instruction_is_simple_few_shot_plain_text(self):
        instruction = build_explicit_emphasis_instruction(EXAMPLES)

        self.assertIn("Look at the reference image.", instruction)
        self.assertIn(EXAMPLES, instruction)
        self.assertIn("native 2x3 grid/contact sheet", instruction)
        self.assertIn("six slight outfit variations", instruction)
        self.assertIn("large cleavage", instruction)
        self.assertIn("nice round ass", instruction)
        self.assertIn("Return only the final Higgsfield prompt.", instruction)
        self.assertNotIn("strict JSON", instruction)
        self.assertNotIn("higgsfieldGridPrompt", instruction)
        self.assertNotIn("scene breakdown", instruction.lower())
        self.assertNotIn("Exact reference pose in all panels:", instruction.split(EXAMPLES)[-1])

    def test_example_led_instruction_uses_examples_as_primary_signal(self):
        instruction = build_example_led_instruction(EXAMPLES)

        self.assertIn("The examples are more important than the instructions.", instruction)
        self.assertIn("exactly three columns and two rows", instruction)
        self.assertIn("six slight outfit variations", instruction)
        self.assertIn("Use this older Reference Factory compiler voice", instruction)
        self.assertIn("Create one high-quality six-panel grid image", instruction)
        self.assertIn("Use the image as the source of truth", instruction)
        self.assertIn("Start with the scene/capture", instruction)
        self.assertIn("mirror/selfie/phone/camera behavior", instruction)
        self.assertIn("six practical outfit/color/fabric variations", instruction)
        self.assertIn("same room, same camera angle, same framing, same lighting", instruction)
        self.assertIn("Do not spend prompt budget describing face quality", instruction)
        self.assertIn("perfect face", instruction)
        self.assertIn("eye color", instruction)
        self.assertIn("exact age", instruction)
        self.assertIn("ethnicity", instruction)
        self.assertIn("skin texture", instruction)
        self.assertIn("high detail", instruction)
        self.assertIn("sharp focus", instruction)
        self.assertIn("Return only the final Higgsfield prompt text.", instruction)
        self.assertIn("Do not return:", instruction)
        self.assertNotIn("large cleavage", instruction.split(EXAMPLES)[-1])
        self.assertNotIn("nice round ass", instruction.split(EXAMPLES)[-1])
        self.assertNotIn("strict JSON", instruction)

    def test_cleanup_removes_only_hair_and_tattoo_clauses(self):
        raw = (
            "Create one native 2x3 grid in a bright kitchen, long blonde hair over one shoulder, "
            "deep cleavage, black fitted dress, small tattoo on hip, phone selfie framing, "
            "wood ceiling beams, six outfit variations."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertTrue(cleanup["changed"])
        self.assertIn("long blonde hair over one shoulder", " ".join(cleanup["removed"]))
        self.assertIn("small tattoo on hip", " ".join(cleanup["removed"]))
        self.assertIn("deep cleavage", cleanup["cleaned"])
        self.assertIn("phone selfie framing", cleanup["cleaned"])
        self.assertIn("wood ceiling beams", cleanup["cleaned"])
        self.assertIn("six outfit variations", cleanup["cleaned"])

    def test_cleanup_preserves_prompt_opening_when_hair_is_in_same_clause(self):
        raw = (
            "A close-up selfie of a stunning woman with long voluminous wavy red hair, "
            "bright blue eyes, seated on a modern living-room couch. "
            "Pose: sitting with one arm raised, hand running through her hair, torso leaned forward."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("A close-up selfie of a stunning woman", cleanup["cleaned"])
        self.assertIn("seated on a modern living-room couch", cleanup["cleaned"])
        self.assertIn("one arm raised", cleanup["cleaned"])
        self.assertIn("torso leaned forward", cleanup["cleaned"])
        self.assertNotIn("blue eyes", cleanup["cleaned"].lower())
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_handles_comma_heavy_hair_descriptors_without_dangling_words(self):
        raw = (
            "A high-resolution vertical smartphone selfie of a stunning woman with long, "
            "voluminous wavy bright red hair, striking blue eyes. "
            "She poses with one hand raised to her head, fingers running through her voluminous hair, "
            "head slightly tilted."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("stunning woman", cleanup["cleaned"])
        self.assertIn("She poses with one hand raised to her head", cleanup["cleaned"])
        self.assertIn("head slightly tilted", cleanup["cleaned"])
        self.assertNotIn("blue eyes", cleanup["cleaned"].lower())
        self.assertNotIn("with long", cleanup["cleaned"])
        self.assertNotIn("through her", cleanup["cleaned"])
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_removes_hand_resting_in_hair_without_dangling_preposition(self):
        raw = (
            "A six-panel 2x3 grid showing the same woman seated on the couch, "
            "right arm raised with hand resting in her long red hair, slight head tilt, "
            "soft direct smile at the camera."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("right arm raised, slight head tilt", cleanup["cleaned"])
        self.assertIn("soft direct smile", cleanup["cleaned"])
        self.assertNotIn("in her,", cleanup["cleaned"])
        self.assertNotIn("with,", cleanup["cleaned"])
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_removes_haired_descriptors_and_hand_in_hair(self):
        raw = (
            "A vertical photograph of the same stunning red-haired woman seated on a grey couch. "
            "Exact pose: right arm lifted with hand in hair, left arm resting out of frame."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("same stunning woman seated on a grey couch", cleanup["cleaned"])
        self.assertIn("right arm lifted, left arm resting out of frame", cleanup["cleaned"])
        self.assertNotIn("red-haired", cleanup["cleaned"].lower())
        self.assertNotIn("with hand", cleanup["cleaned"].lower())
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_removes_redhead_descriptor(self):
        raw = "Create a 2x3 grid of the same stunning redhead woman seated on a couch."

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertEqual(cleanup["cleaned"], "Create a 2x3 grid of the same stunning woman seated on a couch.")
        self.assertIn("redhead", " ".join(cleanup["removed"]).lower())

    def test_cleanup_repairs_dangling_with_and_has_after_hair_removal(self):
        raw = (
            "A room featuring the same woman with long wavy red hair seated on a grey couch. "
            "She has long voluminous wavy red hair, bright blue eyes, and a soft smile."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("same woman seated on a grey couch", cleanup["cleaned"])
        self.assertIn("She has a soft smile", cleanup["cleaned"])
        self.assertNotIn("woman with seated", cleanup["cleaned"])
        self.assertNotIn("has,", cleanup["cleaned"])
        self.assertNotIn("blue eyes", cleanup["cleaned"].lower())
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_removes_eye_color_and_skin_polish_without_losing_scene(self):
        raw = (
            "Create one 2x3 grid on a gray couch in a bright apartment, bright blue eyes, "
            "light freckles, photorealistic skin texture with natural freckles and sheen, "
            "deep cleavage, ribbed crop top, consistent face and body proportions, "
            "consistent body proportions, face, and pose, high detail, sharp focus, "
            "consistent body proportions and face across all panels, blue eyes and pose across all panels, "
            "vertical smartphone aesthetic."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("gray couch", cleanup["cleaned"])
        self.assertIn("bright apartment", cleanup["cleaned"])
        self.assertIn("deep cleavage", cleanup["cleaned"])
        self.assertIn("ribbed crop top", cleanup["cleaned"])
        self.assertIn("consistent body proportions", cleanup["cleaned"])
        self.assertIn("consistent body proportions, and pose", cleanup["cleaned"])
        self.assertIn("and pose across all panels", cleanup["cleaned"])
        self.assertIn("vertical smartphone aesthetic", cleanup["cleaned"])
        self.assertNotIn("blue eyes", cleanup["cleaned"].lower())
        self.assertNotIn("freckle", cleanup["cleaned"].lower())
        self.assertNotIn("skin texture", cleanup["cleaned"].lower())
        self.assertNotIn("sheen", cleanup["cleaned"].lower())
        self.assertNotIn("high detail", cleanup["cleaned"].lower())
        self.assertNotIn("sharp focus", cleanup["cleaned"].lower())
        self.assertNotIn("consistent face", cleanup["cleaned"].lower())
        self.assertNotIn(", face,", cleanup["cleaned"].lower())
        self.assertNotIn("and face across", cleanup["cleaned"].lower())

    def test_cleanup_repairs_with_and_after_identity_removal(self):
        raw = (
            "Six-panel 2x3 grid showcasing the exact same stunning woman with long red hair, "
            "blue eyes, freckles, and an extreme hourglass figure."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("same stunning woman with an extreme hourglass figure", cleanup["cleaned"])
        self.assertNotIn("with and", cleanup["cleaned"].lower())
        self.assertNotIn("blue eyes", cleanup["cleaned"].lower())
        self.assertNotIn("freckle", cleanup["cleaned"].lower())
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_removes_residual_hair_clause(self):
        raw = (
            "Create a 2x3 grid in a bright kitchen, loose hair falling over one shoulder, "
            "deep cleavage, fitted hoodie, same camera angle."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("bright kitchen", cleanup["cleaned"])
        self.assertIn("deep cleavage", cleanup["cleaned"])
        self.assertIn("fitted hoodie", cleanup["cleaned"])
        self.assertIn("same camera angle", cleanup["cleaned"])
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_cleanup_repairs_direction_left_by_hair_action(self):
        raw = (
            "Exact pose: seated three-quarter view, right hand running through her long hair, "
            "left arm resting on the couch, direct eye contact."
        )

        cleanup = clean_grok_prompt(raw)

        self.assertTrue(cleanup["valid"])
        self.assertIn("right arm raised, left arm resting on the couch", cleanup["cleaned"])
        self.assertIn("direct eye contact", cleanup["cleaned"])
        self.assertNotIn("right,", cleanup["cleaned"].lower())
        self.assertNotIn("hair", cleanup["cleaned"].lower())

    def test_prompt_contract_wraps_cleaned_prompt_without_validation_rewrite(self):
        cleaned = (
            "Create one native 2x3 grid with mirror selfie framing, large cleavage, "
            "nice round ass, black fitted dress, and six outfit variations."
        )

        contract = prompt_contract_from_cleaned(cleaned, motion_prompt="shared motion")

        self.assertEqual(contract["higgsfieldGridPrompt"], cleaned)
        self.assertEqual(contract["klingMotionPrompt"], "shared motion")
        self.assertIn("Experimental few-shot Grok A/B prompt", contract["notes"])

    def test_create_ab_prompt_experiment_writes_a_b_audit_bundles_without_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            reference.write_bytes(b"jpg")
            examples = EXAMPLES
            fake_a = {
                "output": [{
                    "content": [{
                        "type": "output_text",
                        "text": "Create one native 2x3 grid with kitchen selfie framing, long brunette hair, large cleavage, black hoodie, six outfit variations."
                    }]
                }]
            }
            fake_b = {
                "output": [{
                    "content": [{
                        "type": "output_text",
                        "text": "Create one native 2x3 grid with kitchen selfie framing, nice round ass, white hoodie, six outfit variations."
                    }]
                }]
            }
            with patch("grok_ab_experiment.load_xai_api_key", return_value="key"), \
                 patch("grok_ab_experiment.call_grok", side_effect=[fake_a, fake_b]) as grok:
                result = create_ab_prompt_experiment(
                    root=root,
                    stem="clip_001",
                    reference_image=reference,
                    examples_text=examples,
                    out_dir=root / "prompts" / "experiments",
                    run_images=False,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(grok.call_count, 2)
            self.assertEqual(result["schema"], "reel_factory.grok_few_shot_ab_experiment.v1")
            self.assertEqual(result["imageAspectRatio"], DEFAULT_AB_IMAGE_ASPECT_RATIO)
            self.assertFalse(result["promptEnhancement"])
            self.assertEqual(result["imageReferencePolicy"], "analysis_only_do_not_send_to_higgsfield")
            self.assertEqual(set(result["conditions"]), {"A", "B"})
            self.assertTrue(Path(result["conditions"]["A"]["instructionPath"]).exists())
            self.assertTrue(Path(result["conditions"]["A"]["rawPromptPath"]).exists())
            self.assertTrue(Path(result["conditions"]["A"]["cleanupDiffPath"]).exists())
            a_contract = json.loads(Path(result["conditions"]["A"]["promptJsonPath"]).read_text(encoding="utf-8"))
            self.assertIn("large cleavage", a_contract["higgsfieldGridPrompt"])
            self.assertNotIn("hair", a_contract["higgsfieldGridPrompt"].lower())
            self.assertEqual(result["conditions"]["A"]["generation"]["status"], "not_run")

    def test_create_ab_prompt_experiment_runs_two_image_jobs_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            reference.write_bytes(b"jpg")
            fake = {
                "output": [{
                    "content": [{
                        "type": "output_text",
                        "text": "Create one native 2x3 grid with kitchen selfie framing, large cleavage, black hoodie, six outfit variations."
                    }]
                }]
            }
            with patch("grok_ab_experiment.load_xai_api_key", return_value="key"), \
                 patch("grok_ab_experiment.call_grok", side_effect=[fake, fake]), \
                 patch("grok_ab_experiment._create_image_grid", side_effect=[
                     {"ok": True, "command": ["higgsfield", "generate", "create"], "localPath": "/tmp/A.png"},
                     {"ok": True, "command": ["higgsfield", "generate", "create"], "localPath": "/tmp/B.png"},
                 ]) as create_grid:
                result = create_ab_prompt_experiment(
                    root=root,
                    stem="clip_001",
                    reference_image=reference,
                    examples_text=EXAMPLES,
                    out_dir=root / "prompts" / "experiments",
                    soul_name="Stacey",
                    run_images=True,
                )

            self.assertEqual(create_grid.call_count, 2)
            self.assertEqual(result["conditions"]["A"]["generation"]["localPath"], "/tmp/A.png")
            self.assertEqual(result["conditions"]["B"]["generation"]["localPath"], "/tmp/B.png")

    def test_run_ab_images_from_sidecar_uses_saved_prompts_without_grok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "prompts" / "experiments"
            out.mkdir(parents=True)
            a_prompt = out / "clip_001_A_prompt.json"
            b_prompt = out / "clip_001_B_prompt.json"
            a_prompt.write_text(json.dumps(prompt_contract_from_cleaned("A prompt")), encoding="utf-8")
            b_prompt.write_text(json.dumps(prompt_contract_from_cleaned("B prompt")), encoding="utf-8")
            sidecar = out / "clip_001_grok_few_shot_ab_experiment.json"
            sidecar.write_text(json.dumps({
                "schema": "reel_factory.grok_few_shot_ab_experiment.v1",
                "stem": "clip_001",
                "imageModel": "text2image_soul_v2",
                "imageAspectRatio": "4:3",
                "imageQuality": "2k",
                "conditions": {
                    "A": {"promptJsonPath": str(a_prompt), "generation": {"status": "not_run"}},
                    "B": {"promptJsonPath": str(b_prompt), "generation": {"status": "not_run"}},
                },
            }), encoding="utf-8")

            with patch("grok_ab_experiment._create_image_grid", side_effect=[
                {"ok": True, "localPath": "/tmp/A.png"},
                {"ok": True, "localPath": "/tmp/B.png"},
            ]) as create_grid:
                result = run_ab_images_from_sidecar(
                    sidecar_path=sidecar,
                    root=root,
                    soul_name="Stacey",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(create_grid.call_count, 2)
            self.assertEqual(result["conditions"]["A"]["generation"]["localPath"], "/tmp/A.png")
            self.assertEqual(result["conditions"]["B"]["generation"]["localPath"], "/tmp/B.png")


if __name__ == "__main__":
    unittest.main()
