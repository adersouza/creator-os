import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CaptionRenderTests(unittest.TestCase):
    def test_default_condensed_caption_size_clears_qc_floor(self):
        from reel_factory.caption_render import _font_for_lines

        font_path = (
            Path(__file__).resolve().parents[1]
            / "fonts"
            / "InstagramSansCondensed-Regular.woff2"
        )
        self.assertGreaterEqual(_font_for_lines(font_path, 2).size, 96)

    def test_long_caption_renders_inside_canvas(self):
        try:
            from reel_factory.caption_render import render_caption_png
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
            from reel_factory.caption_render import render_caption_png
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

    def test_unrenderable_caption_truncates_instead_of_crashing(self):
        try:
            from reel_factory.caption_render import render_caption_png
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
            out = Path(tmp) / "caption.png"
            render_caption_png(
                text,
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
            self.assertLessEqual(bbox[2], 540)
            self.assertLessEqual(bbox[3], 960)


if __name__ == "__main__":
    unittest.main()


class CaptionOrphanWrapTests(unittest.TestCase):
    """Greedy wrap left a paragraph's last line as one tiny word.

    Measured across the 477 live captions at the real reel width (600px):
    39 orphaned before, 11 after. Every reference creator's caption breaks
    into balanced lines, so this matches the format rather than inventing one.
    """

    @staticmethod
    def _font():
        from PIL import ImageFont

        path = Path(__file__).resolve().parents[1] / "fonts" / "Inter-Black.ttf"
        return ImageFont.truetype(str(path), 64)

    @staticmethod
    def _greedy(text, font, width):
        """Wrap with the un-orphan post-pass disabled."""
        from reel_factory import caption_render as cr

        original = cr._unorphan
        cr._unorphan = lambda lines, *a, **k: lines
        try:
            return cr._wrap_lines(text, font, width)
        finally:
            cr._unorphan = original

    def test_short_trailing_word_is_pulled_up_a_line(self):
        from reel_factory.caption_render import _wrap_lines

        font, width = self._font(), 600
        # A real caption from the live bank, verified to orphan at this width.
        text = "Having a female bestie is like raising a chicken.\nOne day you'll eat it."
        before = self._greedy(text, font, width)
        after = _wrap_lines(text, font, width)

        self.assertEqual(before[-1], "it.", "fixture no longer reproduces the orphan")
        self.assertEqual(after[-1], "eat it.")
        self.assertGreater(len(after[-1].split()), 1)
        # Same words, same order -- only the break position moved.
        self.assertEqual(" ".join(before).split(), " ".join(after).split())

    def test_paragraph_boundaries_are_never_crossed(self):
        from reel_factory.caption_render import _wrap_lines

        font = self._font()
        text = "a short line\n\nx:"
        lines = _wrap_lines(text, font, 600)
        # "x:" is its own paragraph with no donor line; it must be left alone
        # rather than absorbing a word from the paragraph above it.
        self.assertIn("x:", lines)
        self.assertIn("", lines)

    def test_normal_captions_are_untouched(self):
        from reel_factory.caption_render import _wrap_lines

        font, width = self._font(), 600
        text = "come give me a koss"
        self.assertEqual(_wrap_lines(text, font, width), self._greedy(text, font, width))

    def test_donor_line_with_a_single_word_is_left_alone(self):
        from reel_factory.caption_render import _wrap_lines

        font = self._font()
        # Stripping the donor's only word would just move the orphan up.
        lines = _wrap_lines("supercalifragilistic\nto", font, 600)
        self.assertEqual(lines[-1], "to")
