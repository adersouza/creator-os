from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from campaign_store import campaign_by_name, connect, create_campaign, next_batch_plan

from pipeline_contracts import validate_recommendation_next_batch


class CampaignStoreBanditTests(unittest.TestCase):
    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _campaign_id(self, root: Path) -> str:
        conn = connect(root)
        row = campaign_by_name(conn, "Bandit Test")
        conn.close()
        return str(row["campaign_id"])

    def _create_campaign(self, root: Path) -> str:
        create_campaign(
            root,
            name="Bandit Test",
            creator="Stacey",
            account="acct",
            platform="instagram_reels",
        )
        return self._campaign_id(root)

    def _add_post(
        self,
        root: Path,
        campaign_id: str,
        *,
        recipe: str,
        index: int,
        views: int,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        saves: int = 0,
    ) -> None:
        conn = connect(root)
        now = int(time.time())
        name = f"{recipe}_{index}.mp4"
        out = root / name
        out.write_bytes(name.encode())
        conn.execute(
            """
            INSERT INTO campaign_outputs (
                campaign_output_id, campaign_id, output_path, recipe,
                metrics_filename, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"co_{recipe}_{index}", campaign_id, str(out), recipe, name, now, now),
        )
        conn.execute(
            """
            INSERT INTO publish_metrics (
                filename, platform, account, uploaded_at, views, likes, comments,
                shares, saves, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                "ig",
                "acct",
                "2026-07-01",
                views,
                likes,
                comments,
                shares,
                saves,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def test_next_batch_bandit_seed_is_deterministic(self):
        root = self._root()
        campaign_id = self._create_campaign(root)
        self._add_post(
            root, campaign_id, recipe="v01_original", index=1, views=100, likes=20
        )
        self._add_post(
            root, campaign_id, recipe="v09_caption_bg", index=1, views=100, likes=5
        )

        first = next_batch_plan(root, campaign="Bandit Test", count=8, seed=123)
        second = next_batch_plan(root, campaign="Bandit Test", count=8, seed=123)

        self.assertEqual(
            [idea["recipe_hint"] for idea in first["ideas"]],
            [idea["recipe_hint"] for idea in second["ideas"]],
        )
        self.assertEqual(
            first["schema"], "campaign_factory.recommendations.next_batch.v1"
        )
        validate_recommendation_next_batch(first)
        self.assertEqual(first["items"], first["ideas"])
        self.assertEqual(
            first["items"][0]["suggestedRecipe"], first["ideas"][0]["recipe_hint"]
        )
        self.assertTrue(first["recipe_bandit"]["active"])

    def test_next_batch_bandit_cold_start_preserves_round_robin(self):
        root = self._root()
        self._create_campaign(root)

        plan = next_batch_plan(root, campaign="Bandit Test", count=4, seed=1)

        self.assertFalse(plan["recipe_bandit"]["active"])
        self.assertEqual(
            [idea["recipe_hint"] for idea in plan["ideas"]],
            ["v01_original", "v09_caption_bg", "v01_original", "v09_caption_bg"],
        )
        self.assertEqual(
            plan["ideas"][0]["recipe_bandit"]["mode"], "cold_start_round_robin"
        )

    def test_next_batch_bandit_explores_low_data_arms(self):
        root = self._root()
        campaign_id = self._create_campaign(root)
        for idx in range(5):
            self._add_post(
                root,
                campaign_id,
                recipe="steady",
                index=idx,
                views=100,
                likes=25,
            )
        self._add_post(root, campaign_id, recipe="newish", index=1, views=100, likes=5)

        plan = next_batch_plan(root, campaign="Bandit Test", count=30, seed=27)
        recipes = [idea["recipe_hint"] for idea in plan["ideas"]]

        self.assertIn("steady", recipes)
        self.assertIn("newish", recipes)
        self.assertGreater(len(set(recipes)), 1)

    def test_next_batch_bandit_converges_toward_higher_engagement_rate(self):
        root = self._root()
        campaign_id = self._create_campaign(root)
        for idx in range(40):
            self._add_post(
                root,
                campaign_id,
                recipe="winner",
                index=idx,
                views=100,
                likes=70,
                comments=5,
            )
            self._add_post(
                root,
                campaign_id,
                recipe="loser",
                index=idx,
                views=100,
                likes=1,
            )

        plan = next_batch_plan(root, campaign="Bandit Test", count=200, seed=42)
        recipes = [idea["recipe_hint"] for idea in plan["ideas"]]

        self.assertGreater(recipes.count("winner"), recipes.count("loser"))

    def test_next_batch_bandit_clamps_rates_and_keeps_zero_post_arms_reachable(self):
        root = self._root()
        campaign_id = self._create_campaign(root)
        self._add_post(root, campaign_id, recipe="clamped", index=1, views=1, likes=5)
        self._add_post(root, campaign_id, recipe="zero_view", index=1, views=0)

        plan = next_batch_plan(root, campaign="Bandit Test", count=5, seed=3)
        arms = {arm["recipe"]: arm for arm in plan["recipe_bandit"]["arms"]}

        self.assertEqual(arms["clamped"]["alpha"], 2.0)
        self.assertEqual(arms["clamped"]["beta"], 1.0)
        self.assertEqual(arms["zero_view"]["alpha"], 1.0)
        self.assertEqual(arms["zero_view"]["beta"], 2.0)
        self.assertEqual(arms["v09_caption_bg"]["post_count"], 0)
        self.assertEqual(arms["v09_caption_bg"]["alpha"], 1.0)
        self.assertEqual(arms["v09_caption_bg"]["beta"], 1.0)

    def test_next_batch_bandit_uses_stable_metric_join_key(self):
        root = self._root()
        campaign_id = self._create_campaign(root)
        conn = connect(root)
        now = int(time.time())
        out = root / "local_render_name.mp4"
        out.write_bytes(b"video")
        conn.execute(
            """
            INSERT INTO campaign_outputs (
                campaign_output_id, campaign_id, output_path, job_key, recipe,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "co_stable_renamed",
                campaign_id,
                str(out),
                "job_stable_renamed",
                "stable_recipe",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO publish_metrics (
                filename, platform, account, uploaded_at, views, likes,
                comments, shares, saves, campaign_output_id, job_key, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "posted_renamed_elsewhere.mp4",
                "ig",
                "acct",
                "2026-07-01",
                100,
                40,
                0,
                0,
                0,
                "co_stable_renamed",
                "job_stable_renamed",
                now,
            ),
        )
        conn.commit()
        conn.close()

        plan = next_batch_plan(root, campaign="Bandit Test", count=1, seed=9)
        arms = {arm["recipe"]: arm for arm in plan["recipe_bandit"]["arms"]}

        self.assertEqual(arms["stable_recipe"]["post_count"], 1)
        self.assertEqual(arms["stable_recipe"]["mean_reward"], 0.4)


if __name__ == "__main__":
    unittest.main()
