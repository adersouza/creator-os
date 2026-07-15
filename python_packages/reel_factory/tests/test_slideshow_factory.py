import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from reel_factory.slideshow_factory import (
    build_slideshow,
    discover_media,
    render_grid_preview,
    render_slide,
)


class SlideshowFactoryTests(unittest.TestCase):
    def _write_image(self, path: Path, color: tuple[int, int, int]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (720, 1280), color).save(path)
        return path

    def test_discover_media_ignores_unsupported_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_image(root / "a.jpg", (20, 30, 40))
            (root / "notes.txt").write_text("not media", encoding="utf-8")

            found = discover_media(root)

            self.assertEqual([p.name for p in found], ["a.jpg"])

    def test_render_slide_writes_vertical_jpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._write_image(root / "source.jpg", (120, 80, 40))
            out = root / "slide.jpg"

            render_slide(
                source,
                out,
                hook="What I eat to stop the food noise",
                fonts_dir=Path("fonts"),
                view_count_label="100.8K",
            )

            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (1080, 1920))

    def test_grid_preview_writes_collage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slides = [
                self._write_image(root / f"slide_{idx}.jpg", (idx * 30, 40, 80))
                for idx in range(1, 5)
            ]
            out = root / "grid.jpg"

            render_grid_preview(
                slides, out, title="Claude = 550 videos/day", fonts_dir=Path("fonts")
            )

            self.assertTrue(out.exists())
            with Image.open(out) as img:
                self.assertEqual(img.size, (1080, 1280))

    def test_build_slideshow_writes_manifest_without_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "media"
            for idx in range(4):
                self._write_image(media / f"source_{idx}.jpg", (30 * idx, 60, 90))

            out = root / "out"
            manifest = build_slideshow(
                media,
                out,
                title="Slideshow test",
                hooks=["hook one", "hook two"],
                count=3,
                seed=11,
                reference_pattern_id="pattern_1",
                generation_id="slidegen_1",
                render_video=False,
                render_grid=True,
            )

            manifest_path = out / "slideshow_manifest.json"
            self.assertTrue(manifest_path.exists())
            self.assertEqual(manifest.slide_count, 3)
            self.assertIsNone(manifest.reel_path)
            self.assertTrue(Path(manifest.grid_path).exists())

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], "reel_factory.slideshow.v1")
            self.assertEqual(data["format"], "slideshow_pack")
            self.assertEqual(data["reference_pattern_id"], "pattern_1")
            self.assertEqual(data["generation_id"], "slidegen_1")
            self.assertEqual(data["output_width"], 1080)
            self.assertEqual(data["output_height"], 1920)
            self.assertIsNone(data["duration_seconds"])
            self.assertEqual(len(data["items"]), 3)
            self.assertIn("caption_hash", data["items"][0])
            self.assertTrue(Path(data["items"][0]["slide_path"]).exists())


if __name__ == "__main__":
    unittest.main()
