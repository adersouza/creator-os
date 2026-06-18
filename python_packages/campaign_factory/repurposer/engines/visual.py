from pathlib import Path

from .common import ensure_input_file

# We dynamically import this to avoid circular dependencies if reel_factory relies on campaign_factory later
try:
    from reel_factory.generate_assets import AssetGenerationPlan, create_video_asset
except ImportError:
    AssetGenerationPlan = None
    create_video_asset = None


class VisualEngine:
    """Layer 3: Generative AI Visual shifts (Higgsfield/Kling)."""

    @staticmethod
    def apply(video_path: Path, output_path: Path, prompt: str = None) -> Path:
        """Invokes generate_assets.py logic to create visual variation."""
        ensure_input_file(video_path, label="video")
        if not prompt:
            return video_path
        if AssetGenerationPlan is None or create_video_asset is None:
            print("[VisualEngine] skipped: reel_factory.generate_assets is unavailable")
            return video_path

        print("[VisualEngine] skipped: paid visual generation is disabled for zero-cost variation")
        return video_path
