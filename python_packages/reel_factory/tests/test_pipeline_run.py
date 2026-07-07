import json
import tempfile
import unittest
from pathlib import Path

from campaign_store import create_campaign
from manifest import Manifest
from pipeline_run import (
    PipelineRunConfig,
    _candidate_features,
    discover_candidates,
    pipeline_run_dir,
    run_pipeline,
    write_approved_export,
)
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

    def test_pipeline_run_requires_explicit_paid_generation_opt_in(self):
        with self._root() as tmp:
            root = Path(tmp)
            self._seed_campaign(root)
            reference = root / "reference.jpg"
            reference.write_bytes(b"reference")

            safe = run_pipeline(
                PipelineRunConfig(
                    root=root,
                    campaign="Test Campaign",
                    creator="Stacey",
                    count=1,
                    run_id="safe_asset_plan",
                    reference_image=reference,
                    execute_commands=True,
                ),
                command_runner=lambda command: {"ok": True, "command": command},
            )
            safe_argv = safe["stages"]["assets"]["jobs"][0]["command"]["argv"]
            self.assertIn("dry-run", safe_argv)

            live = run_pipeline(
                PipelineRunConfig(
                    root=root,
                    campaign="Test Campaign",
                    creator="Stacey",
                    count=1,
                    run_id="live_asset_plan",
                    reference_image=reference,
                    execute_commands=True,
                    allow_paid_generation=True,
                    download_assets=True,
                    estimated_cost_per_asset_usd=0.5,
                ),
                command_runner=lambda command: {"ok": True, "command": command},
            )
            live_argv = live["stages"]["assets"]["jobs"][0]["command"]["argv"]
            self.assertIn("create", live_argv)
            self.assertNotIn("dry-run", live_argv)
            self.assertIn("--download", live_argv)
            self.assertIn("--estimated-cost-usd", live_argv)
            self.assertIn("0.5", live_argv)

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
                    "stem": "test_campaign_resume_plan_000",
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
            self.assertEqual(payload["items"][0]["review_state"], "ranked_candidate")
            self.assertEqual(
                Path(payload["items"][0]["output_path"]),
                rendered.resolve(),
            )
            self.assertEqual(second["stages"]["assign"]["status"], "completed")
            self.assertTrue(second["stages"]["assign"]["dry_run"])
            self.assertEqual(second["stages"]["assign"]["result"]["assigned"], 1)

    def test_candidate_features_prefer_aligned_lineage_features(self):
        lineage = {
            "features": {
                "scene": "gym_mirror",
                "camera": "mirror_selfie",
                "pose": "standing",
                "motion": "slow_pan",
                "outfit": "black_set",
                "creator": "stacey",
                "body_style": "athletic_hourglass",
                "caption_style": "short_direct",
                "hook_type": "pov",
                "audio_track_id": "track_1",
            },
            "source": {"soulName": "Unknown"},
            "generation": {"scene": "old_scene"},
        }

        features = _candidate_features(lineage)

        self.assertEqual(features["scene"], "gym_mirror")
        self.assertEqual(features["camera"], "mirror_selfie")
        self.assertEqual(features["creator"], "stacey")
        self.assertEqual(features["audio_track_id"], "track_1")

    def test_discover_candidates_filters_by_run_and_rejects_failed_qc(self):
        with self._root() as tmp:
            root = Path(tmp)
            processed = root / "02_processed"
            processed.mkdir()
            good = processed / "campaign_run_001_ok.mp4"
            rejected = processed / "campaign_run_002_rejected.mp4"
            stale = processed / "campaign_old_001_ok.mp4"
            for path in (good, rejected, stale):
                path.write_bytes(b"video")
            good.with_suffix(good.suffix + ".generated_asset_lineage.json").write_text(
                json.dumps(
                    {
                        "source": {"stem": "campaign_run_001", "soulName": "Stacey"},
                        "generation": {"campaign": "Test Campaign", "status": "ok"},
                        "features": {"creator": "stacey", "scene": "bathroom_mirror"},
                    }
                ),
                encoding="utf-8",
            )
            rejected.with_suffix(
                rejected.suffix + ".generated_asset_lineage.json"
            ).write_text(
                json.dumps(
                    {
                        "source": {"stem": "campaign_run_002", "soulName": "Stacey"},
                        "generation": {
                            "campaign": "Test Campaign",
                            "status": "image_qc_rejected",
                        },
                        "features": {"creator": "stacey", "scene": "bathroom_mirror"},
                    }
                ),
                encoding="utf-8",
            )
            stale.with_suffix(
                stale.suffix + ".generated_asset_lineage.json"
            ).write_text(
                json.dumps(
                    {
                        "source": {"stem": "campaign_old_001", "soulName": "Stacey"},
                        "generation": {"campaign": "Test Campaign", "status": "ok"},
                        "features": {"creator": "stacey", "scene": "bedroom"},
                    }
                ),
                encoding="utf-8",
            )

            candidates = discover_candidates(
                root, campaign="Test Campaign", run_id="run"
            )

            self.assertEqual(
                [Path(row["output_path"]).name for row in candidates], [good.name]
            )

    def test_write_approved_export_marks_ranked_candidates_not_approved(self):
        with self._root() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            output = root / "candidate.mp4"
            output.write_bytes(b"video")

            path = write_approved_export(
                run_dir,
                [
                    {
                        "output_path": str(output),
                        "score": 1.0,
                        "predictedEngagement": {"score": 1.0, "matched": 2},
                    }
                ],
                limit=1,
            )

            assert path is not None
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["items"][0]["review_state"], "ranked_candidate")


if __name__ == "__main__":
    unittest.main()
