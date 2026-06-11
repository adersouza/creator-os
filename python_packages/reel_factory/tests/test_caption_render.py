import tempfile
import unittest
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CaptionRenderTests(unittest.TestCase):
    def test_long_caption_renders_inside_canvas(self):
        try:
            from caption_render import render_caption_png
        except ModuleNotFoundError as e:
            if e.name == "pilmoji":
                self.skipTest("pilmoji is not installed in this interpreter")
            raise

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "caption.png"
            render_caption_png(
                "supercalifragilisticexpialidocious but make it fit the caption box",
                font_family="Onest",
                fonts_dir=Path("fonts"),
                color_scheme="light",
                band="top",
                style="classic",
                out_path=out,
                canvas_w=540,
                canvas_h=960,
            )

            img = Image.open(out).convert("RGBA")
            bbox = img.getbbox()
            self.assertIsNotNone(bbox)
            self.assertGreater(bbox[2] - bbox[0], 0)
            self.assertLessEqual(bbox[2], 540)
            self.assertLessEqual(bbox[3], 960)


if __name__ == "__main__":
    unittest.main()
