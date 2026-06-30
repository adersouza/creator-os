import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_intent import read_audio_intent, write_audio_intent
from audio_provider import (
    curated_winners_path,
    eligible_trending_tracks,
    local_winners_path,
    select_audio,
    trending_cml_path,
    watch_list_path,
)


class AudioProviderTests(unittest.TestCase):
    def test_trending_filter_keeps_commercial_safe_style_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = trending_cml_path(root)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "track_id": "a",
                                "track_name": "Runway Pop",
                                "trend_rank": 2,
                                "tags": ["fashion", "pop"],
                            },
                            {
                                "track_id": "b",
                                "track_name": "Sad Ballad",
                                "trend_rank": 1,
                                "tags": ["sad"],
                            },
                            {
                                "track_id": "c",
                                "track_name": "Luxury Chill",
                                "trend_rank": 3,
                                "tags": ["luxury", "chill"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            tracks = eligible_trending_tracks(root)

            self.assertEqual([track.track_id for track in tracks], ["a", "c"])

    def test_auto_trending_outputs_required_selection_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = trending_cml_path(root)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    [
                        {
                            "track_id": "t1",
                            "track_name": "Creator Spark",
                            "trend_rank": 4,
                            "tags": ["upbeat"],
                        },
                    ]
                ),
                encoding="utf-8",
            )

            selection = select_audio(root, mode="AUTO_TRENDING", seed="always-trending")

            self.assertEqual(selection["track_id"], "t1")
            self.assertEqual(selection["track_name"], "Creator Spark")
            self.assertEqual(selection["source"], "tiktok_cml")
            self.assertEqual(selection["trend_rank"], 4)
            self.assertIn("selected_reason", selection)

    def test_auto_mix_can_select_local_winners_and_watch_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_path = local_winners_path(root)
            local_path.parent.mkdir(parents=True)
            local_path.write_text(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "track_id": "local_1",
                                "track_name": "Local Winner",
                                "tags": ["local_winner"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            watch_path = watch_list_path(root)
            watch_path.write_text(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "track_id": "watch_1",
                                "track_name": "Watch Candidate",
                                "tags": ["watch_list"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            selected_ids = {
                select_audio(root, mode="AUTO_TRENDING", seed=f"seed-{idx}")["track_id"]
                for idx in range(20)
            }

            self.assertIn("local_1", selected_ids)
            self.assertIn("watch_1", selected_ids)

    def test_safe_library_uses_curated_winners(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = curated_winners_path(root)
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "tracks": [
                            {
                                "track_id": "w1",
                                "track_name": "Known Winner",
                                "tags": ["confidence"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            selection = select_audio(root, mode="SAFE_LIBRARY", seed="safe")

            self.assertEqual(selection["track_id"], "w1")
            self.assertEqual(
                selection["selected_reason"], "safe_library_curated_winner"
            )

    def test_custom_mode_requires_and_returns_manual_track(self):
        selection = select_audio(
            Path("."),
            mode="CUSTOM",
            seed="manual",
            custom_track={
                "track_id": "manual_1",
                "track_name": "Manual Pick",
                "source": "operator",
            },
        )

        self.assertEqual(selection["track_id"], "manual_1")
        self.assertEqual(selection["selected_reason"], "custom_manual_override")

    def test_audio_intent_can_preserve_provider_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            output.write_bytes(b"fake")
            selection = {
                "track_id": "t1",
                "track_name": "Creator Spark",
                "source": "tiktok_cml",
                "trend_rank": 4,
                "selected_reason": "auto_trending_70pct_tiktok_cml",
            }

            write_audio_intent(
                output,
                mode="native_trending_audio",
                platform="tiktok",
                audio_selection=selection,
            )

            self.assertEqual(
                read_audio_intent(output)["audio_selection"]["track_id"], "t1"
            )


if __name__ == "__main__":
    unittest.main()
