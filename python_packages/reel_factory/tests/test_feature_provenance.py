from __future__ import annotations

import json
from pathlib import Path

from winner_dna import connect, upsert_reel_feature


def test_text_inference_features_are_tagged(tmp_path: Path) -> None:
    # No video_analysis sidecar exists -> features fall back to text inference and
    # must be stamped so the loop never treats keyword guesses as ground truth.
    upsert_reel_feature(tmp_path, tmp_path / "beach_mirror_selfie.mp4")
    conn = connect(tmp_path)
    try:
        row = conn.execute("SELECT features_json FROM reel_features LIMIT 1").fetchone()
    finally:
        conn.close()
    assert json.loads(row["features_json"])["feature_source"] == "text_inference"
