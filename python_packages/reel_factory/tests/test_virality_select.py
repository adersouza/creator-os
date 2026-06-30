from __future__ import annotations

from pathlib import Path

from virality_select import predict_engagement, rank_candidates, select_best
from winner_dna import connect


def _seed(root: Path) -> None:
    conn = connect(root)
    # 40 outcome rows so confidence can reach "high"; values irrelevant to ranking.
    for i in range(40):
        conn.execute(
            "INSERT INTO reel_outcomes (output_path, filename, views, imported_at) "
            "VALUES (?, ?, ?, ?)",
            (f"out_{i}.mp4", f"out_{i}.mp4", 1, 0),
        )
    now = 0
    rows = [
        ("dna_scene_beach", "scene", "beach", 30, 1000.0, "out_0.mp4", now),
        ("dna_scene_office", "scene", "office", 30, 50.0, "out_1.mp4", now),
        ("dna_hook_type_curiosity", "hook_type", "curiosity", 30, 800.0, "out_2.mp4", now),
    ]
    conn.executemany(
        "INSERT INTO winner_dna (dna_id, feature_key, feature_value, sample_size, "
        "avg_winner_score, top_output_path, updated_at) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_higher_engagement_candidate_wins(tmp_path: Path) -> None:
    _seed(tmp_path)
    candidates = [
        {"id": "office_one", "features": {"scene": "office"}},
        {"id": "beach_one", "features": {"scene": "beach", "hook_type": "curiosity"}},
    ]
    best = select_best(candidates, tmp_path)
    assert best is not None and best["id"] == "beach_one"
    # ranking is fully ordered, best-first
    ranked = rank_candidates(candidates, tmp_path)
    assert [c["id"] for c in ranked] == ["beach_one", "office_one"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_scorer_hook_blends_external_signal(tmp_path: Path) -> None:
    _seed(tmp_path)
    candidates = [
        {"id": "beach_one", "features": {"scene": "beach"}},
        {"id": "office_one", "features": {"scene": "office"}},
    ]
    # External scorer that flips preference: office should now win.
    ranked = rank_candidates(
        candidates, tmp_path, scorer=lambda c, _data: 1.0 if c["id"] == "office_one" else 0.0
    )
    assert ranked[0]["id"] == "office_one"


def test_cold_start_candidate_scores_zero_not_crash(tmp_path: Path) -> None:
    _seed(tmp_path)
    conn = connect(tmp_path)
    try:
        pred = predict_engagement({"scene": "unseen_scene", "outfit": "unknown"}, conn)
    finally:
        conn.close()
    assert pred == {"score": 0.0, "matched": 0, "weight": 0.0}
