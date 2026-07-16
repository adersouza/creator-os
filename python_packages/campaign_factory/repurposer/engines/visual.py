from pathlib import Path

from .common import ensure_input_file


class VisualEngine:
    """Layer 3: Generative AI Visual shifts (Higgsfield/Kling)."""

    @staticmethod
    def apply(video_path: Path, output_path: Path, prompt: str = None) -> Path:
        """Invokes generate_assets.py logic to create visual variation."""
        ensure_input_file(video_path, label="video")
        if not prompt:
            return video_path
        print(
            "[VisualEngine] skipped: paid visual generation is disabled for zero-cost variation"
        )
        return video_path
