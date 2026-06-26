import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caption_bank import CaptionBankStore, caption_hash, load_or_build_caption_bank_store
from caption_intake import import_external, plan_placement, promote, scan_local, swipe_review


class CaptionIntakeTests(unittest.TestCase):
    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "01_captions").mkdir()
        (root / "01_captions" / "clip_001.json").write_text(
            json.dumps({"hooks": ["be honest\nam i your type"]}),
            encoding="utf-8",
        )
        CaptionBankStore.build(root).write(root)
        return root

    def test_scan_local_dedupes_existing_captions(self):
        root = self._root()
        source = root / "tmp" / "lineage.json"
        source.parent.mkdir()
        source.write_text(
            json.dumps(
                {
                    "rawCaptionText": "be honest\nam i your type",
                    "captionOutcomeContext": {"caption_text": "would you date me or run away?"},
                }
            ),
            encoding="utf-8",
        )

        report = scan_local(root, include_seed=False)
        texts = {row["text"] for row in report["candidates"]}

        self.assertIn("would you date me or run away?", texts)
        self.assertNotIn("be honest\nam i your type", texts)

    def test_candidate_intake_does_not_affect_caption_mix(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [{"text": "brand new candidate", "caption_hash": caption_hash("brand new candidate")}],
                }
            ),
            encoding="utf-8",
        )

        store = load_or_build_caption_bank_store(root)
        selected = store.resolve_mix("Stacey", limit=None)

        self.assertNotIn("brand new candidate", {item["text"] for item in selected})

    def test_import_external_adds_review_only_candidates(self):
        root = self._root()
        source = root / "external.json"
        source.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.external_caption_source.v1",
                    "source": "instagram:test_account/reels",
                    "captions": [
                        {
                            "text": "pick one\npizza\nburger\nme",
                            "account": "test_account",
                            "source_url": "https://www.instagram.com/test_account/reels/",
                            "archetype": "choice_poll",
                        },
                        {"text": "be honest\nam i your type"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = import_external(root, source)
        store = load_or_build_caption_bank_store(root)
        texts = {row["text"] for row in report["candidates"]}

        self.assertEqual(report["added_count"], 1)
        self.assertIn("pick one\npizza\nburger\nme", texts)
        self.assertNotIn("be honest\nam i your type", texts)
        self.assertEqual(next(row for row in report["candidates"] if row["text"].startswith("pick one"))["externalSource"]["account"], "test_account")
        self.assertNotIn("pick one\npizza\nburger\nme", {item["text"] for item in store.all_items()})

    def test_import_external_keeps_sourced_edge_candidates_review_only(self):
        root = self._root()
        source = root / "external.json"
        source.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.external_caption_source.v1",
                    "source": "instagram:test_account/reels",
                    "captions": [
                        {
                            "text": "your caring nurse",
                            "account": "test_account",
                            "source_url": "https://www.instagram.com/test_account/reels/",
                            "archetype": "career_bait",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = import_external(root, source)
        store = load_or_build_caption_bank_store(root)
        candidate = next(row for row in report["candidates"] if row["text"] == "your caring nurse")

        self.assertEqual(report["added_count"], 1)
        self.assertEqual(candidate["banks"], ["experimental_edge"])
        self.assertEqual(candidate["reviewOnlyReason"], "sourced_excluded_bank_candidate")
        self.assertEqual(candidate["reviewOnlyExcludedBanks"], ["experimental_edge"])
        self.assertNotIn("your caring nurse", {item["text"] for item in store.all_items()})

    def test_promote_rejects_unsafe_approved_caption(self):
        root = self._root()
        approved = root / "approved.json"
        approved.write_text(json.dumps(["link in bio", "safe little question?"]), encoding="utf-8")

        report = promote(root, approved)
        store = CaptionBankStore.from_root(root)
        texts = {item["text"] for item in store.all_items()}

        self.assertEqual(report["promoted"], 1)
        self.assertIn("safe little question?", texts)
        self.assertNotIn("link in bio", texts)
        self.assertEqual(report["rejected"][0]["blockedTerms"], ["link"])

    def test_promote_rebuilds_banks_with_approved_caption(self):
        root = self._root()
        approved = root / "approved.txt"
        approved.write_text("would you say hi first?", encoding="utf-8")

        report = promote(root, approved)
        store = CaptionBankStore.from_root(root)
        promoted = next(item for item in store.all_items() if item["text"] == "would you say hi first?")

        self.assertEqual(report["promoted"], 1)
        self.assertEqual(Path(report["sidecar"]).name[:16], "approved_intake_")
        self.assertIn("comment_bait", promoted["banks"])

    def test_promote_accepts_reviewed_swipe_decisions(self):
        root = self._root()
        approved = root / "caption_static_swipe_decisions.reviewed.json"
        approved.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_swipe_decisions.v1",
                    "items": [
                        {"text": "approved static hook", "status": "approved", "approvedUse": ["normal"]},
                        {"text": "rejected static hook", "status": "rejected", "approvedUse": []},
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = promote(root, approved)
        store = CaptionBankStore.from_root(root)
        texts = {item["text"] for item in store.all_items()}

        self.assertEqual(report["promoted"], 1)
        self.assertIn("approved static hook", texts)
        self.assertNotIn("rejected static hook", texts)

    def test_plan_placement_adds_timed_hooks_without_explicit_bands(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [
                        {
                            "caption_hash": caption_hash("wife material\nor heartbreak material?"),
                            "text": "wife material\nor heartbreak material?",
                            "banks": ["shared_girl_next_door", "boyfriend_bait"],
                            "status": "candidate",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = plan_placement(root)
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        row = payload["candidates"][0]
        segments = row["hookVariants"]["timed"]["segments"]

        self.assertEqual(report["timedEligible"], 1)
        self.assertEqual(row["placementIntent"]["staticBand"], "lower_center")
        self.assertEqual(row["placementIntent"]["timedPlacementMode"], "segment")
        self.assertFalse(any("band" in segment for segment in segments))
        self.assertTrue(Path(report["reviewFile"]).exists())

    def test_swipe_review_writes_caption_board_without_promoting(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [
                        {
                            "caption_hash": caption_hash("wife material\nor heartbreak material?"),
                            "text": "wife material\nor heartbreak material?",
                            "banks": ["shared_girl_next_door", "boyfriend_bait"],
                            "status": "candidate",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = swipe_review(root)
        decisions = json.loads(Path(report["decisionJsonPath"]).read_text(encoding="utf-8"))
        html = Path(report["boardPath"]).read_text(encoding="utf-8")
        store = load_or_build_caption_bank_store(root)

        self.assertEqual(report["count"], 1)
        self.assertEqual(decisions["schema"], "reel_factory.caption_swipe_decisions.v1")
        self.assertEqual(decisions["reviewMode"], "static")
        self.assertEqual(Path(report["boardPath"]).name, "caption_static_swipe_review.html")
        self.assertIn("wife material", html)
        self.assertIn("Approve static", html)
        self.assertNotIn("Timed beats", html)
        self.assertIn("Download approved JSON", html)
        self.assertNotIn("wife material\nor heartbreak material?", {item["text"] for item in store.all_items()})

    def test_timed_swipe_review_only_includes_timed_candidates(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [
                        {
                            "caption_hash": caption_hash("short hook"),
                            "text": "short hook",
                            "banks": ["comment_bait"],
                            "status": "candidate",
                            "hookVariants": {"static": "short hook", "timed": None},
                        },
                        {
                            "caption_hash": caption_hash("wife material\nor heartbreak material?"),
                            "text": "wife material\nor heartbreak material?",
                            "banks": ["boyfriend_bait"],
                            "status": "candidate",
                            "hookVariants": {
                                "static": "wife material\nor heartbreak material?",
                                "timed": {"segments": [{"text": "wife material"}, {"text": "or heartbreak material?"}]},
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = swipe_review(root, mode="timed")
        decisions = json.loads(Path(report["decisionJsonPath"]).read_text(encoding="utf-8"))
        html = Path(report["boardPath"]).read_text(encoding="utf-8")

        self.assertEqual(report["count"], 1)
        self.assertEqual(decisions["reviewMode"], "timed")
        self.assertEqual(Path(report["boardPath"]).name, "caption_timed_swipe_review.html")
        self.assertIn("Approve timed", html)
        self.assertIn("Timed beats", html)
        self.assertNotIn("short hook", html)

    def test_swipe_review_excludes_generated_seed_by_default(self):
        root = self._root()
        candidate_path = root / "caption_banks" / "candidate_intake.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "schema": "reel_factory.caption_candidate_intake.v1",
                    "candidates": [
                        {
                            "caption_hash": caption_hash("real harvested hook"),
                            "text": "real harvested hook",
                            "banks": ["comment_bait"],
                            "source": "ocr:local.png",
                            "status": "candidate",
                        },
                        {
                            "caption_hash": caption_hash("synthetic filler hook"),
                            "text": "synthetic filler hook",
                            "banks": ["comment_bait"],
                            "source": "generated_seed:0",
                            "status": "candidate",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        report = swipe_review(root)
        html = Path(report["boardPath"]).read_text(encoding="utf-8")

        self.assertEqual(report["count"], 1)
        self.assertIn("real harvested hook", html)
        self.assertNotIn("synthetic filler hook", html)


if __name__ == "__main__":
    unittest.main()
