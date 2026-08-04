"""Published outcomes must produce real weights, bounded by the operator's prior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from reference_factory.preference_outcomes import (
    WEIGHT_LIMIT,
    preference_outcome_weights,
    refresh_preference_outcome_weights,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE generated_video_prompts (
          reference_id TEXT,
          outcome_reward_score REAL,
          outcome_sample_count INTEGER
        )
        """
    )
    # Real schema: prompts are keyed by the internal ref_url_<hash> id, while the
    # platform shortcode used by preference itemIds lives in native_media_id.
    conn.execute("CREATE TABLE source_files (reference_id TEXT, native_media_id TEXT)")
    conn.executemany(
        "INSERT INTO source_files VALUES (?, ?)",
        [
            ("ref_url_aaaa1111", "winner"),
            ("ref_url_bbbb2222", "loser"),
        ],
    )
    return conn


def _profile() -> dict:
    return {
        "collectionId": "c1",
        "sourceFingerprint": "a" * 64,
        "items": [
            {"itemId": "reel:winner", "kind": "reel", "score": 4},
            {"itemId": "reel:loser", "kind": "reel", "score": 4},
            {"itemId": "reel:untested", "kind": "reel", "score": 4},
        ],
    }


def test_weights_rank_measured_references_and_ignore_untested_ones():
    conn = _conn()
    conn.executemany(
        "INSERT INTO generated_video_prompts VALUES (?, ?, ?)",
        [("ref_url_aaaa1111", 0.9, 5), ("ref_url_bbbb2222", 0.1, 5)],
    )

    weights = preference_outcome_weights(conn, _profile())

    assert weights["reel:winner"] > weights["reel:loser"]
    assert "reel:untested" not in weights
    assert all(abs(value) <= WEIGHT_LIMIT for value in weights.values())


def test_thin_evidence_earns_no_weight():
    conn = _conn()
    conn.executemany(
        "INSERT INTO generated_video_prompts VALUES (?, ?, ?)",
        [("ref_url_aaaa1111", 0.9, 1), ("ref_url_bbbb2222", 0.1, 1)],
    )

    assert preference_outcome_weights(conn, _profile()) == {}


def test_refresh_persists_weights_without_touching_operator_truth(tmp_path: Path):
    conn = _conn()
    conn.executemany(
        "INSERT INTO generated_video_prompts VALUES (?, ?, ?)",
        [("ref_url_aaaa1111", 0.9, 5), ("ref_url_bbbb2222", 0.1, 5)],
    )
    path = tmp_path / "profile.json"
    original = _profile()
    path.write_text(json.dumps(original), encoding="utf-8")

    result = refresh_preference_outcome_weights(conn, path)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert result["weightedItems"] == 2
    assert written["outcomeWeights"]["reel:winner"] > 0
    # The operator's ratings and the fingerprint binding them are untouched.
    assert written["items"] == original["items"]
    assert written["sourceFingerprint"] == original["sourceFingerprint"]
