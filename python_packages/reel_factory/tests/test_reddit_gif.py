from pathlib import Path

from PIL import Image
from reel_factory.reddit_gif import render_reddit_gif


def test_reddit_gif_dry_run_is_small_identity_safe_motion(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (720, 1280), color=(50, 60, 70)).save(source)

    receipt = render_reddit_gif(source, tmp_path / "output.gif", dry_run=True)

    assert receipt["outputSize"] == [720, 1280]
    assert receipt["frameCount"] == 36
    assert receipt["motion"] == "identity_safe_center_zoom_1.2_percent"
    assert receipt["ffmpegCommand"][-1].endswith("output.gif")
