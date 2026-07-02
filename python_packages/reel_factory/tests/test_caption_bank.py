import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaign_store import ensure_campaign_schema
from caption_bank import (
    ACTIVE_BANKS,
    CaptionBankStore,
    caption_hash,
    caption_static_metadata,
    default_mixes,
    load_or_build_caption_bank_store,
    refresh_caption_weights,
)
from discoverability_safety import (
    audit_caption_sources,
    discoverability_safe_content_contract,
)
from intelligence_store import ensure_intelligence_schema


class CaptionBankTests(unittest.TestCase):
    def _root_with_sources(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        captions = root / "01_captions"
        captions.mkdir()
        (captions / "clip_001.json").write_text(
            json.dumps(
                {
                    "hooks": [
                        "account so small that if you follow me I will message you",
                        "which one would you choose?\n1. kiss\n2. date\n3. me",
                        "I like gym boys but the coach said front or back?",
                        "dark goth girl karma is real",
                    ],
                    "caption_color": "auto",
                }
            ),
            encoding="utf-8",
        )
        (captions / "clip_002.json").write_text(
            json.dumps(
                {
                    "hooks": [
                        {"segments": [{"text": "read this backwards", "end": 2.0}]},
                        "The solutions to my problem isn't dating an older guy",
                    ]
                }
            ),
            encoding="utf-8",
        )
        conn = sqlite3.connect(root / "manifest.sqlite")
        conn.execute(
            "CREATE TABLE variations (caption_text TEXT NOT NULL, caption_hash TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO variations VALUES (?, ?)",
            ("it’s that right?????", caption_hash("it’s that right?????")),
        )
        conn.commit()
        conn.close()
        return root

    def test_build_preserves_sidecar_and_history_captions(self):
        root = self._root_with_sources()

        store = CaptionBankStore.build(root)
        all_texts = {item["text"] for item in store.all_items()}

        self.assertIn(
            "account so small that if you follow me I will message you", all_texts
        )
        self.assertIn("which one would you choose?\n1. kiss\n2. date\n3. me", all_texts)
        self.assertIn("read this backwards", all_texts)
        self.assertIn("it’s that right?????", all_texts)
        self.assertIn(
            "it’s that right?????",
            {item["text"] for item in store.bank_items("weird_generated_history")},
        )
        self.assertEqual(store.bank_items("winner_bank"), [])
        for bank in ACTIVE_BANKS:
            self.assertIn(bank, store.banks)

    def test_store_files_are_manual_learning_ready(self):
        root = self._root_with_sources()
        store = CaptionBankStore.build(root)
        store.write(root)

        self.assertTrue((root / "caption_banks" / "banks.json").exists())
        self.assertTrue((root / "caption_banks" / "mixes.json").exists())
        performance = json.loads(
            (root / "caption_banks" / "performance.json").read_text()
        )
        self.assertEqual(performance["schema"], "reel_factory.caption_performance.v1")
        self.assertEqual(performance["captions"], {})

    def test_creator_mixes_resolve_weighted_caption_pools(self):
        root = self._root_with_sources()
        store = CaptionBankStore.build(root)

        larissa = store.resolve_mix("Larissa", limit=20, seed=7)
        lola = store.resolve_mix("Lola", limit=20, seed=7)

        self.assertTrue(larissa)
        self.assertTrue(lola)
        self.assertGreaterEqual(
            sum("gym_body" in item["banks"] for item in lola),
            sum("gym_body" in item["banks"] for item in larissa),
        )
        excluded = {
            "goth_dark_alt",
            "experimental_edge",
            "weird_generated_history",
            "winner_bank",
        }
        self.assertFalse(
            any(excluded.intersection(item["selected_banks"]) for item in larissa)
        )
        self.assertFalse(
            any(excluded.intersection(item["selected_banks"]) for item in lola)
        )

    def test_explicit_bank_selection_can_pick_goth_bank(self):
        root = self._root_with_sources()
        store = CaptionBankStore.build(root)

        selected = store.resolve_banks(["goth_dark_alt"], limit=10, seed=3)

        self.assertTrue(selected)
        self.assertTrue(
            all("goth_dark_alt" in item["selected_banks"] for item in selected)
        )

    def test_deterministic_seed_repeats_selection(self):
        root = self._root_with_sources()
        store = CaptionBankStore.build(root)

        first = store.resolve_mix("Larissa", limit=3, seed=42)
        second = store.resolve_mix("Larissa", limit=3, seed=42)

        self.assertEqual(
            [item["caption_hash"] for item in first],
            [item["caption_hash"] for item in second],
        )

    def test_refresh_caption_weights_writes_outcome_approved_weights(self):
        root = self._root_with_sources()
        CaptionBankStore.build(root).write(root)
        high = root / "high.mp4"
        low = root / "low.mp4"
        high.write_bytes(b"high")
        low.write_bytes(b"low")
        high_hash = caption_hash("best hook")
        low_hash = caption_hash("flat hook")
        high.with_suffix(high.suffix + ".caption_lineage.json").write_text(
            json.dumps({"captionOutcomeContext": {"captionHash": high_hash}}),
            encoding="utf-8",
        )
        low.with_suffix(low.suffix + ".caption_lineage.json").write_text(
            json.dumps({"captionHash": low_hash}),
            encoding="utf-8",
        )
        conn = sqlite3.connect(root / "manifest.sqlite")
        conn.row_factory = sqlite3.Row
        ensure_campaign_schema(conn)
        ensure_intelligence_schema(conn)
        now = 1
        conn.executemany(
            """
            INSERT INTO campaign_outputs (
                campaign_output_id, output_path, caption_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("co_high", str(high), "best hook", now, now),
                ("co_low", str(low), "flat hook", now, now),
            ],
        )
        conn.executemany(
            """
            INSERT INTO reel_outcomes (
                outcome_id, filename, output_path, platform, account, posted_at,
                views, likes, comments, shares, saves, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "out_high",
                    high.name,
                    str(high),
                    "ig",
                    "stacey",
                    "2026-07-01",
                    100,
                    30,
                    5,
                    5,
                    5,
                    now,
                ),
                (
                    "out_low",
                    low.name,
                    str(low),
                    "ig",
                    "stacey",
                    "2026-07-01",
                    1000,
                    1,
                    0,
                    0,
                    0,
                    now,
                ),
            ],
        )
        conn.commit()
        conn.close()

        result = refresh_caption_weights(root)
        performance = json.loads(
            (root / "caption_banks" / "performance.json").read_text(encoding="utf-8")
        )
        weights = performance["approvedWeights"]["captionHashes"]

        self.assertEqual(result["updated"], 2)
        self.assertEqual(result["unresolved"], 0)
        self.assertGreater(weights[high_hash], weights[low_hash])
        self.assertEqual(performance["captions"][high_hash]["sampleCount"], 1)

    def test_refresh_caption_weights_preserves_existing_weights_without_outcomes(self):
        root = self._root_with_sources()
        banks = root / "caption_banks"
        banks.mkdir(parents=True, exist_ok=True)
        performance_path = banks / "performance.json"
        existing = {
            "schema": "reel_factory.caption_performance.v1",
            "updated_at": 1782874000,
            "notes": "existing real weights",
            "approvedWeights": {"captionHashes": {"known": 123.0}},
            "captions": {},
        }
        performance_path.write_text(json.dumps(existing), encoding="utf-8")
        conn = sqlite3.connect(root / "manifest.sqlite")
        conn.row_factory = sqlite3.Row
        ensure_intelligence_schema(conn)
        conn.close()

        result = refresh_caption_weights(root)
        performance = json.loads(performance_path.read_text(encoding="utf-8"))

        self.assertEqual(result["updated"], 0)
        self.assertEqual(performance, existing)

    def test_caption_static_metadata_classifies_length_and_format(self):
        short = caption_static_metadata("wife or girlfriend")
        numbered = caption_static_metadata(
            "3 things I hate in guys\n1. boring\n2. rude\n3. cheap"
        )
        paragraph = caption_static_metadata(
            "I'm so single I end up texting anyone who follows me because I get excited thinking we might become friends"
        )

        self.assertEqual(short["length_class"], "very_short")
        self.assertEqual(short["format_class"], "single_line")
        self.assertEqual(numbered["format_class"], "numbered_list")
        self.assertEqual(paragraph["length_class"], "long")

    def test_built_bank_items_include_static_fit_metadata(self):
        root = self._root_with_sources()
        store = CaptionBankStore.build(root)

        item = next(
            item
            for item in store.all_items()
            if item["text"].startswith("which one would you choose")
        )

        self.assertIn("length_class", item)
        self.assertIn("format_class", item)
        self.assertEqual(item["format_class"], "numbered_list")

    def test_load_or_build_prefers_existing_files(self):
        root = self._root_with_sources()
        CaptionBankStore.build(root).write(root)

        loaded = load_or_build_caption_bank_store(root)

        self.assertEqual(loaded.mixes, default_mixes())
        self.assertIn("dm_follow_bait", loaded.banks)

    def test_discoverability_contract_blocks_dm_links_and_off_platform_text(self):
        report = discoverability_safe_content_contract(
            "I respond to DMs.\nI just don't respond to basic ones",
            "link in bio",
            "Snap me",
        )

        self.assertFalse(report["discoverabilitySafe"])
        self.assertIn("dm", report["blockedTerms"])
        self.assertIn("link", report["blockedTerms"])
        self.assertIn("snapchat", report["blockedTerms"])
        self.assertEqual(
            report["blockedReason"], "unsafe_dm_link_or_off_platform_language"
        )
        self.assertFalse(report["wouldWrite"])

    def test_discoverability_contract_does_not_block_lowercase_word_of(self):
        report = discoverability_safe_content_contract("photo of the day")

        self.assertTrue(report["discoverabilitySafe"])
        self.assertEqual(report["blockedTerms"], [])

    def test_caption_source_discoverability_audit_flags_active_sources_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captions = root / "01_captions"
            captions.mkdir()
            (captions / "clip_001.json").write_text(
                json.dumps({"hooks": ["I respond to DMs.", "photo of the day"]}),
                encoding="utf-8",
            )
            (captions / "clip_002.json.pre_discoverability_cleanup.bak").write_text(
                json.dumps({"hooks": ["link in bio"]}),
                encoding="utf-8",
            )
            banks = root / "caption_banks"
            banks.mkdir()
            (banks / "banks.json").write_text(
                json.dumps(
                    {
                        "banks": {
                            "shared_girl_next_door": [{"text": "mirror selfie energy"}],
                            "comment_bait": [
                                {"text": "who didn't get a pic in dms yet today?"}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = audit_caption_sources(root)

            self.assertFalse(report["discoverabilitySafe"])
            self.assertEqual(report["captionFilesScanned"], 2)
            self.assertEqual(report["remainingRiskEntries"], 2)
            self.assertEqual(
                {finding["sourceFile"] for finding in report["findings"]},
                {"01_captions/clip_001.json", "caption_banks/banks.json"},
            )
            self.assertFalse(report["wouldWrite"])


if __name__ == "__main__":
    unittest.main()
