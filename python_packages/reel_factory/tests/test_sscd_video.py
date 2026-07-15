from pathlib import Path

import numpy as np
import reel_factory.sscd_video as sscd_video


def test_audit_video_dir_reports_pass_warn_fail(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.mp4"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    source.write_bytes(b"source")
    for name in ("a_v01_original.mp4", "b_v05_hflip.mp4", "c_v06_zoom.mp4"):
        (out_dir / name).write_bytes(b"video")

    monkeypatch.setattr(sscd_video, "extract_frames", lambda path, td: [path])
    monkeypatch.setattr(sscd_video, "embed_many", lambda paths: np.ones((1, 1)))
    scores = iter([(0.1, 0.25), (0.4, 0.55), (0.8, 0.9)])
    monkeypatch.setattr(sscd_video, "cross_similarity", lambda _a, _b: next(scores))

    rows = sscd_video.audit_video_dir(source, out_dir)

    assert [row["status"] for row in rows] == ["pass", "warn", "fail"]
    assert rows[2]["max_similarity"] == 0.9
