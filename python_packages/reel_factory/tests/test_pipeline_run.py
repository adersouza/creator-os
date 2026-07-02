import json
import tempfile
import unittest
from pathlib import Path

from campaign_store import create_campaign
from manifest import Manifest
from pipeline_run import PipelineRunConfig, pipeline_run_dir, run_pipeline
from posting_ledger import create_posting_plan


class PipelineRunTests(unittest.TestCase):
    def _root(self) -> tempfile.TemporaryDirectory:
        return tempfile.TemporaryDirectory()

    def _seed_campaign(self, root: Path) -> str:
        Manifest(root / "manifest.json")
        result = create_campaign(
            root,
            name="Test Campaign",
            creator="Stacey",
            account="stacey_a",
            platform="ig",
        )
        return result["campaign_id"]

    def test_pipeline_run_plans_dry_end_to_end_commands_without_publish(self):
        with self._root() as tmp:
            root = Path(tmp)
            self._seed_campaign(root)
            reference = root / "reference.jpg"
            reference.write_bytes(b"reference")

            state = run_pipeline(
                PipelineRunConfig(
                    root=root,
                    campaign="Test Campaign",
                    creator="Stacey",
                    count=2,
                    run_id="dry_plan",
                    reference_image=reference,
                    caption_mix="Stacey",
                )
            )

            self.assertEqual(state["schema"], "reel_factory.pipeline_run.v1")
            self.assertEqual(state["publishing"], {"publish": False, "schedule": False})
            self.assertEqual(state["stages"]["next_batch"]["status"], "completed")
            self.assertEqual(state["stages"]["prompt"]["status"], "planned")
            self.assertEqual(len(state["stages"]["prompt"]["jobs"]), 2)
            prompt_argv = state["stages"]["prompt"]["jobs"][0]["command"]["argv"]
            asset_argv = state["stages"]["assets"]["jobs"][0]["command"]["argv"]
            render_argv = state["stages"]["caption_render"]["command"]["argv"]
            self.assertIn("--dry-run", prompt_argv)
            self.assertIn("--dry-run", render_argv)
            self.assertIn("dry-run", asset_argv)
            joined = " ".join(prompt_argv + asset_argv + render_argv)
            self.assertNotIn("--enable-live", joined)
            self.assertNotIn("--enable-paid-generation", joined)
            self.assertNotIn("--schedule-mode", joined)

            state_path = (
                pipeline_run_dir(root, "Test Campaign", "dry_plan")
                / "pipeline_run.json"
            )
            self.assertTrue(state_path.exists())

    def test_pipeline_run_resume_ranks_candidates_and_dry_assigns(self):
        with self._root() as tmp:
            root = Path(tmp)
            campaign_id = self._seed_campaign(root)
            create_posting_plan(
                root,
                creator="Stacey",
                campaign_id=campaign_id,
                accounts=["stacey_a"],
                start_date="2026-07-02",
                days=1,
            )
            reference = root / "reference.jpg"
            reference.write_bytes(b"reference")
            config = PipelineRunConfig(
                root=root,
                campaign="Test Campaign",
                creator="Stacey",
                count=1,
                run_id="resume_plan",
                reference_image=reference,
            )

            first = run_pipeline(config)
            self.assertEqual(first["stages"]["rank"]["status"], "waiting")
            self.assertEqual(first["stages"]["assign"]["status"], "waiting")

            rendered_dir = root / "02_processed"
            rendered_dir.mkdir()
            rendered = rendered_dir / "candidate.mp4"
            rendered.write_bytes(b"rendered reel")
            lineage = {
                "source": {
                    "soulId": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
                    "soulName": "Stacey",
                    "scene": "bedroom",
                    "pose": "mirror pose",
                },
                "generation": {"motion": "subtle", "outfit": "black top"},
            }
            rendered.with_suffix(
                rendered.suffix + ".generated_asset_lineage.json"
            ).write_text(json.dumps(lineage), encoding="utf-8")

            second = run_pipeline(config)
            self.assertEqual(second["stages"]["rank"]["status"], "completed")
            self.assertEqual(second["stages"]["approved_export"]["status"], "completed")
            approved_path = Path(second["stages"]["approved_export"]["path"])
            payload = json.loads(approved_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "reel_factory.approved_export.v1")
            self.assertEqual(payload["count"], 1)
            self.assertEqual(
                Path(payload["items"][0]["output_path"]),
                rendered.resolve(),
            )
            self.assertEqual(second["stages"]["assign"]["status"], "completed")
            self.assertTrue(second["stages"]["assign"]["dry_run"])
            self.assertEqual(second["stages"]["assign"]["result"]["assigned"], 1)


if __name__ == "__main__":
    unittest.main()
