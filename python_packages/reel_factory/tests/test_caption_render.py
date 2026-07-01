import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_wrapped_caption_pixels_stay_out_of_reels_safe_zones(self):
        try:
            from caption_render import render_caption_png
        except ModuleNotFoundError as e:
            if e.name == "pilmoji":
                self.skipTest("pilmoji is not installed in this interpreter")
            raise

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "caption.png"
            render_caption_png(
                "launch day checklist has one verylongunbrokenwordthatmustwrap cleanly",
                font_family="Onest",
                fonts_dir=Path("fonts"),
                color_scheme="light",
                band="bottom",
                style="classic",
                out_path=out,
                canvas_w=540,
                canvas_h=960,
            )

            img = Image.open(out).convert("RGBA")
            bbox = img.getbbox()
            self.assertIsNotNone(bbox)
            assert bbox is not None
            safe_bottom = round(480 * 960 / 1920)
            self.assertLessEqual(bbox[2] - bbox[0], 360)
            self.assertLessEqual(bbox[3], 960 - safe_bottom)

    def test_unrenderable_caption_does_not_shrink_below_legible_floor(self):
        try:
            from caption_render import render_caption_png
        except ModuleNotFoundError as e:
            if e.name == "pilmoji":
                self.skipTest("pilmoji is not installed in this interpreter")
            raise

        text = "\n".join(
            [
                "3 different ways a guy would ask me out",
                "Smooth: " + "very specific romantic setup " * 6,
                "Nervous: " + "awkward cute overthinking line " * 6,
                "Playful: " + "teasing challenge with extra words " * 6,
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                ValueError, "caption_unrenderable_at_legible_size"
            ):
                render_caption_png(
                    text,
                    font_family="Onest",
                    fonts_dir=Path("fonts"),
                    color_scheme="light",
                    band="bottom",
                    style="classic",
                    out_path=Path(tmp) / "caption.png",
                    canvas_w=540,
                    canvas_h=960,
                )


if __name__ == "__main__":
    unittest.main()
