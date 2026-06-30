import json
import subprocess
from pathlib import Path

MIN_VIDEO_DIMENSION_PX = 720


class QualityGate:
    """Checks the technical quality of generated variants."""

    @staticmethod
    def get_video_info(video_path: Path) -> dict:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return {}
            return json.loads(result.stdout)
        except Exception:
            return {}

    @classmethod
    def is_quality_acceptable(cls, variant: Path) -> bool:
        """Ensure variant meets minimum broadcasting standards."""
        info = cls.get_video_info(variant)
        if not info or "streams" not in info:
            return False

        video_stream = next(
            (s for s in info["streams"] if s["codec_type"] == "video"), None
        )
        if not video_stream:
            return False

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        # Both axes must meet the floor; short wide or narrow tall clips fail.
        if width < MIN_VIDEO_DIMENSION_PX or height < MIN_VIDEO_DIMENSION_PX:
            print(f"Quality Reject: Resolution too low ({width}x{height})")
            return False

        return True
