import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from overnight_grid_worker import (
    CAPTIONS,
    create_kling_for_grid,
    crop_grid_image,
    crop_grid_video,
    detect_visible_content_box,
    grid_assets,
    infer_grid,
    panel_crop_boxes,
    parse_panel_spec,
    prompt_for_grid,
    prompt_for_panel,
    simple_rating,
)
from PIL import Image


class OvernightGridWorkerTests(unittest.TestCase):
    def test_infer_grid_square_as_three_by_three_and_vertical_as_two_by_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            square = root / "square.png"
            vertical = root / "vertical.png"
            Image.new("RGB", (2048, 2048), "white").save(square)
            Image.new("RGB", (1344, 2016), "white").save(vertical)

            self.assertEqual(
                (infer_grid(square).columns, infer_grid(square).rows), (3, 3)
            )
            self.assertEqual(
                (infer_grid(vertical).columns, infer_grid(vertical).rows), (2, 3)
            )

    def test_grid_assets_prefers_known_existing_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "project_data" / "generated_assets"
            assets.mkdir(parents=True)
            wanted = assets / "gwen2wild_v9_video_negative_fix_soul_image.png"
            other = assets / "zzz_soul_image.png"
            Image.new("RGB", (2048, 2048), "white").save(wanted)
            Image.new("RGB", (2048, 2048), "white").save(other)

            names = [spec.path.name for spec in grid_assets(root)]
            self.assertEqual(names[:2], [wanted.name, other.name])

    def test_prompt_for_grid_uses_shared_motion_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "grid_soul_image.png"
            Image.new("RGB", (2048, 2048), "white").save(image)
            prompt_path = prompt_for_grid(root, infer_grid(image))
            payload = json.loads(prompt_path.read_text(encoding="utf-8"))

            self.assertIn(
                "Shared motion pass for every cropped panel",
                payload["klingMotionPrompt"],
            )
            self.assertIn(
                "Apply the same reference-derived movement pattern",
                payload["klingMotionPrompt"],
            )
            self.assertIn(
                "Preserve each supplied start image", payload["klingMotionPrompt"]
            )
            self.assertNotIn("best panel", payload["klingMotionPrompt"])
            self.assertNotIn("negative_prompt", payload)
            self.assertEqual(
                set(payload), {"higgsfieldGridPrompt", "klingMotionPrompt", "notes"}
            )

    def test_prompt_for_panel_reuses_shared_motion_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "grid_soul_image.png"
            Image.new("RGB", (2048, 2048), "white").save(image)
            prompt_path = prompt_for_panel(root, infer_grid(image), 4)
            payload = json.loads(prompt_path.read_text(encoding="utf-8"))

            self.assertIn(
                "Shared motion pass for every cropped panel",
                payload["klingMotionPrompt"],
            )
            self.assertNotIn("panel 4", prompt_path.name)
            self.assertNotIn("negative_prompt", payload)

    def test_simple_rating_rejects_bad_probe_and_keeps_valid_video_shape(self):
        with patch(
            "overnight_grid_worker.probe_video",
            return_value={"width": 512, "height": 512, "duration": 5.0},
        ):
            rating = simple_rating(Path("ok.mp4"))
        self.assertTrue(rating["keep"])
        self.assertEqual(rating["scores"]["motion"], 4)
        self.assertIn("auto_review_pass", rating["labels"])

        with patch(
            "overnight_grid_worker.probe_video",
            return_value={"width": 200, "height": 512, "duration": 1.0},
        ):
            rating = simple_rating(Path("bad.mp4"))
        self.assertFalse(rating["keep"])
        self.assertIn("low_resolution_crop", rating["labels"])
        self.assertIn("too_short", rating["labels"])

    def test_caption_bank_is_short_and_review_friendly(self):
        self.assertGreaterEqual(len(CAPTIONS), 4)
        self.assertTrue(all(len(caption.split()) <= 4 for caption in CAPTIONS))

    def test_square_two_by_three_grid_uses_square_kling_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "grid.png"
            Image.new("RGB", (1344, 1344), "white").save(image)
            result = create_kling_for_grid(
                root, infer_grid(image, columns=3, rows=2), dry_run=True
            )
            self.assertEqual(
                result["would_create"].endswith("_whole_grid_kling.mp4"), True
            )
            self.assertIn("grid.png", result["start_image"])

    def test_crop_grid_video_uses_expected_panel_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "grid.mp4"
            image = root / "grid.png"
            Image.new("RGB", (300, 300), "white").save(image)
            import subprocess

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=300x300:rate=10",
                    "-t",
                    "1",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )

            outputs = crop_grid_video(video, infer_grid(image), root / "panels")
            self.assertEqual(len(outputs), 9)
            self.assertTrue(all(p.exists() for p in outputs))

    def test_smart_crop_helpers_detect_outer_padding_and_split_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "padded_grid.png"
            im = Image.new("RGB", (100, 80), "black")
            for x in range(10, 90):
                for y in range(8, 72):
                    im.putpixel((x, y), (220, 220, 220))
            im.save(image)

            box = detect_visible_content_box(image)
            self.assertEqual(box, (10, 8, 90, 72))

            spec = infer_grid(image, columns=3, rows=2)
            boxes = panel_crop_boxes(100, 80, spec, content_box=box, inset=2)
            self.assertEqual(len(boxes), 6)
            self.assertEqual(boxes[0], (12, 10, 26, 30))
            self.assertEqual(boxes[-1], (62, 40, 26, 30))

    def test_crop_grid_image_creates_high_quality_panel_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "grid.png"
            Image.new("RGB", (900, 600), "white").save(image)
            spec = infer_grid(image, columns=3, rows=2)

            out = crop_grid_image(spec, 5, root / "panels")
            self.assertTrue(out.exists())
            with Image.open(out) as im:
                self.assertEqual(im.size, (300, 300))

    def test_parse_panel_spec_accepts_grid_colon_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "grid.png"
            Image.new("RGB", (900, 900), "white").save(image)

            spec, panel = parse_panel_spec(root, "grid.png:7")
            self.assertEqual(spec.path, image.resolve())
            self.assertEqual(panel, 7)


if __name__ == "__main__":
    unittest.main()
