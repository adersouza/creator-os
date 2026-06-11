from __future__ import annotations

from pathlib import Path


DEFAULT_SOURCE_ROOT = Path.home() / "Downloads" / "examples"
DEFAULT_DATA_ROOT = Path.home() / "Projects" / "reference_reels"
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "reference_factory.sqlite"
CONTENTFORGE_APPLE_VISION_SCRIPT = Path(
    Path.home() / "Projects" / "contentforge" / "scripts" / "apple-vision-ocr.swift"
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def ensure_data_dirs(data_root: Path = DEFAULT_DATA_ROOT) -> None:
    for rel in [
        "manifests",
        "thumbnails",
        "frame_samples",
        "contact_sheets",
        "ocr",
        "curated/gold_captioned",
        "curated/gold_visual",
        "curated/maybe",
        "curated/ignore",
    ]:
        (data_root / rel).mkdir(parents=True, exist_ok=True)
