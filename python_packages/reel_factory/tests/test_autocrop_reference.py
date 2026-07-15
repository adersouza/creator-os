from __future__ import annotations

from pathlib import Path

import pytest
from reel_factory.generate_variants import autocrop_reference

Image = pytest.importorskip("PIL.Image")


def test_trims_pillarbox_and_letterbox(tmp_path: Path) -> None:
    # 200x200 black frame with a 120x100 bright photo inset at (40,50).
    im = Image.new("RGB", (200, 200), (0, 0, 0))
    im.paste(Image.new("RGB", (120, 100), (200, 180, 160)), (40, 50))
    src = tmp_path / "framed.png"
    im.save(src)
    res = autocrop_reference(str(src), str(tmp_path / "clean.png"))
    assert res["size"] == [120, 100]  # black bars gone on all sides
    assert res["bbox"] == [40, 50, 160, 150]


def test_bottom_trim_cuts_ui_strip_first(tmp_path: Path) -> None:
    # bright photo full-frame; bottom 10% is where a UI overlay would sit.
    im = Image.new("RGB", (100, 100), (180, 170, 160))
    src = tmp_path / "full.png"
    im.save(src)
    res = autocrop_reference(str(src), str(tmp_path / "c.png"), bottom_trim=0.1)
    assert res["size"][1] <= 90  # bottom strip removed before border scan
