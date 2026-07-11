import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from grid_crop import (
    build_crop_plan,
    crop_image_grid_panels,
    load_crop_plan,
    preset_boxes,
    render_fit_nocrop,
    save_crop_plan,
    validate_boxes,
)
from PIL import Image, ImageDraw


class GridCropTests(unittest.TestCase):
    def _write_grid_image(
        self,
        root: Path,
        name: str,
        columns: int,
        rows: int,
        cell_w: int = 80,
        cell_h: int = 100,
        pad: int = 12,
    ) -> Path:
        image = Image.new(
            "RGB",
            (columns * cell_w + pad * 2, rows * cell_h + pad * 2),
            (245, 245, 245),
        )
        colors = [
            (180, 40, 40),
            (40, 150, 90),
            (60, 90, 190),
            (190, 160, 40),
            (170, 70, 170),
            (40, 170, 180),
            (210, 100, 50),
            (90, 90, 90),
            (35, 120, 40),
        ]
        for row in range(rows):
            for col in range(columns):
                color = colors[(row * columns + col) % len(colors)]
                x1 = pad + col * cell_w
                y1 = pad + row * cell_h
                x2 = x1 + cell_w
                y2 = y1 + cell_h
                for x in range(x1, x2):
                    for y in range(y1, y2):
                        image.putpixel((x, y), color)
        path = root / name
        image.save(path)
        return path

    def test_smart_image_crop_detects_padded_three_by_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = self._write_grid_image(root, "grid_3x2.png", 3, 2)
            manifest = crop_image_grid_panels(image, root / "out", prefix="clip_001")

            self.assertEqual(manifest["gridPreset"], {"columns": 3, "rows": 2})
            self.assertEqual(len(manifest["panelCrops"]), 6)
            self.assertEqual(manifest["contentBox"], [12, 12, 252, 212])
            self.assertTrue(
                all(Path(p["path"]).exists() for p in manifest["panelCrops"])
            )

    def test_smart_image_crop_detects_vertical_square_and_wide_grids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                ("grid_2x3.png", 2, 3, 6),
                ("grid_3x3.png", 3, 3, 9),
                ("grid_4x2.png", 4, 2, 8),
            ]
            for name, columns, rows, count in cases:
                image = self._write_grid_image(root, name, columns, rows)
                manifest = crop_image_grid_panels(
                    image, root / f"out_{columns}x{rows}", prefix=name
                )
                self.assertEqual(
                    manifest["gridPreset"], {"columns": columns, "rows": rows}
                )
                self.assertEqual(len(manifest["panelCrops"]), count)

    def test_ambiguous_weak_boundary_high_panel_guess_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (2048, 1536), (60, 50, 42))
            path = root / "weak_boundary_grid.png"
            image.save(path)

            manifest = crop_image_grid_panels(path, root / "out", prefix="weak")

            self.assertEqual(manifest["gridPreset"], {"columns": 3, "rows": 2})
            self.assertEqual(manifest["confidence"], "review")
            self.assertTrue(manifest["reviewRequired"])
            self.assertEqual(len(manifest["panelCrops"]), 6)

    def test_operator_override_forces_grid_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (2048, 1536), (60, 50, 42))
            path = root / "weak_boundary_grid.png"
            image.save(path)

            manifest = crop_image_grid_panels(
                path, root / "out", columns=3, rows=2, prefix="forced"
            )

            self.assertEqual(manifest["gridPreset"], {"columns": 3, "rows": 2})
            self.assertEqual(manifest["confidence"], "operator_override")
            self.assertEqual(len(manifest["panelCrops"]), 6)

    def test_seam_aware_crop_snaps_shifted_four_by_two_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (2048, 1536), (240, 240, 240))
            draw = ImageDraw.Draw(image)
            x_lines = [0, 544, 1038, 1562, 2048]
            y_lines = [0, 746, 1536]
            colors = [
                (180, 40, 40),
                (40, 150, 90),
                (60, 90, 190),
                (190, 160, 40),
                (170, 70, 170),
                (40, 170, 180),
                (210, 100, 50),
                (90, 90, 90),
            ]
            idx = 0
            for row in range(2):
                for col in range(4):
                    draw.rectangle(
                        (
                            x_lines[col],
                            y_lines[row],
                            x_lines[col + 1] - 1,
                            y_lines[row + 1] - 1,
                        ),
                        fill=colors[idx],
                    )
                    idx += 1
            for x in x_lines[1:-1]:
                draw.rectangle((x - 3, 0, x + 3, 1535), fill=(250, 250, 250))
            draw.rectangle(
                (0, y_lines[1] - 3, 2047, y_lines[1] + 3), fill=(250, 250, 250)
            )
            path = root / "shifted_4x2.png"
            image.save(path)

            manifest = crop_image_grid_panels(
                path, root / "out", columns=4, rows=2, prefix="shifted"
            )

            self.assertEqual(manifest["gridPreset"], {"columns": 4, "rows": 2})
            self.assertEqual(manifest["confidence"], "operator_override")
            self.assertFalse(manifest["reviewRequired"])
            self.assertGreaterEqual(manifest["cropInset"], 10)
            self.assertEqual(manifest["seamDetection"]["confidence"], "high")
            self.assertTrue(manifest["seamDetection"]["snapped"])
            self.assertLess(abs(manifest["seamDetection"]["xLines"][1] - 544), 8)
            self.assertLess(abs(manifest["seamDetection"]["xLines"][2] - 1038), 8)
            self.assertLess(abs(manifest["seamDetection"]["xLines"][3] - 1562), 8)
            self.assertLess(abs(manifest["seamDetection"]["yLines"][1] - 746), 8)
            first_crop = manifest["panelCrops"][0]["cropBox"]
            second_crop = manifest["panelCrops"][1]["cropBox"]
            self.assertGreater(first_crop[2], 500)
            self.assertLess(first_crop[0] + first_crop[2], 544)
            self.assertGreater(second_crop[0], 544)

            auto_manifest = crop_image_grid_panels(
                path, root / "auto_out", prefix="auto_shifted"
            )
            self.assertEqual(auto_manifest["gridPreset"], {"columns": 4, "rows": 2})
            self.assertEqual(len(auto_manifest["panelCrops"]), 8)

    def test_preset_boxes_support_three_by_two_and_four_by_two(self):
        boxes = preset_boxes(1200, 800, columns=3, rows=2)
        self.assertEqual(len(boxes), 6)
        self.assertEqual(boxes[0]["x"], 0)
        self.assertEqual(boxes[0]["w"], 400)
        self.assertEqual(boxes[-1]["x"], 800)
        self.assertEqual(boxes[-1]["h"], 400)

        boxes = preset_boxes(1600, 800, columns=4, rows=2)
        self.assertEqual(len(boxes), 8)
        self.assertEqual(boxes[3]["x"], 1200)
        self.assertEqual(boxes[7]["y"], 400)

    def test_crop_plan_save_load_and_box_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "00_source_videos" / "clip_001.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"mp4")
            with patch(
                "grid_crop.probe_video",
                return_value={"width": 100, "height": 80, "duration": 5.0},
            ):
                plan = build_crop_plan(
                    root,
                    stem="clip_001",
                    source_video=source,
                    columns=3,
                    rows=2,
                    boxes=[
                        {"id": 1, "x": -10, "y": 5, "w": 999, "h": 999, "enabled": True}
                    ],
                )
            self.assertEqual(plan["boxes"][0]["x"], 0)
            self.assertEqual(plan["boxes"][0]["w"], 100)
            out = save_crop_plan(root, plan)
            self.assertTrue(out.exists())
            loaded = load_crop_plan(root, "clip_001")
            self.assertEqual(loaded["schema"], "reel_factory.grid_crop_plan.v1")
            self.assertEqual(loaded["gridPreset"], {"columns": 3, "rows": 2})

    def test_validate_boxes_clamps_to_source_dimensions(self):
        boxes = validate_boxes(
            [{"id": 1, "x": 90, "y": 70, "w": 50, "h": 50, "enabled": False}],
            width=100,
            height=80,
        )
        self.assertEqual(boxes[0]["w"], 10)
        self.assertEqual(boxes[0]["h"], 10)
        self.assertFalse(boxes[0]["enabled"])

    def test_fit_nocrop_render_uses_decrease_for_foreground(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "clip.mp4"
            source.write_bytes(b"mp4")
            out = root / "out.mp4"
            commands = []

            def fake_caption(*args, **kwargs):
                Path(kwargs["out_path"]).write_bytes(b"png")

            def fake_run(cmd, **kwargs):
                commands.append(cmd)
                out.write_bytes(b"mp4")

            with (
                patch("grid_crop.render_caption_png", side_effect=fake_caption),
                patch("grid_crop.subprocess.run", side_effect=fake_run),
            ):
                render_fit_nocrop(
                    root, source_video=source, caption="test", out_path=out
                )

            joined = " ".join(commands[-1])
            self.assertIn("force_original_aspect_ratio=decrease", joined)
            self.assertIn("overlay=(W-w)/2:(H-h)/2", joined)
            self.assertTrue(out.exists())

    def test_gui_grid_crop_suggest_and_save_plan(self):
        import operator_tools as reel_gui

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "00_source_videos"
            raw.mkdir()
            (raw / "clip_001.mp4").write_bytes(b"mp4")
            fake_probe = json.dumps(
                {"streams": [{"width": 1200, "height": 800, "duration": "5.0"}]}
            )

            with (
                patch.dict(
                    os.environ,
                    {
                        "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                        "REEL_FACTORY_ENV": "test",
                    },
                    clear=True,
                ),
                patch.object(reel_gui, "ROOT", root),
                patch.object(reel_gui, "RAW_DIR", raw),
                patch.object(
                    reel_gui.subprocess, "check_output", return_value=fake_probe
                ),
                patch(
                    "grid_crop.probe_video",
                    return_value={"width": 1200, "height": 800, "duration": 5.0},
                ),
            ):
                suggestion = reel_gui.grid_crop_suggest_api(
                    "clip_001", {"columns": 3, "rows": 2}
                )
                saved = reel_gui.grid_crop_save_plan_api(
                    "clip_001",
                    {
                        "columns": 3,
                        "rows": 2,
                        "boxes": suggestion["boxes"],
                    },
                )

            self.assertEqual(len(suggestion["boxes"]), 6)
            self.assertTrue(Path(saved["plan_path"]).exists())
            self.assertEqual(saved["plan"]["renderMode"], "fit_nocrop")

    def test_gui_grid_crop_returns_controlled_error_by_default(self):
        import operator_tools as reel_gui

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Exception) as ctx:
                reel_gui.grid_crop_suggest_api("clip_001", {"columns": 3, "rows": 2})
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertIn("grid_crop is deprecated", str(ctx.exception.detail))

    def test_gui_grid_crop_blocks_prod_even_with_allow_flag(self):
        import operator_tools as reel_gui

        with patch.dict(
            os.environ,
            {
                "REEL_FACTORY_ALLOW_DEPRECATED_GENERATORS": "1",
                "REEL_FACTORY_ENV": "production",
            },
            clear=True,
        ):
            with self.assertRaises(Exception) as ctx:
                reel_gui.grid_crop_suggest_api("clip_001", {"columns": 3, "rows": 2})
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertIn("grid_crop is deprecated", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
