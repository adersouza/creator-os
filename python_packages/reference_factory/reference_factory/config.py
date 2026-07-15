from __future__ import annotations

import os
from pathlib import Path

from creator_os_core.runtime_paths import resolve_runtime_paths

_PATHS = resolve_runtime_paths()
CREATOR_OS_ROOT = _PATHS.source_root
DEFAULT_SOURCE_ROOT = Path.home() / "Downloads" / "examples"
DEFAULT_TIKTOK_SOURCE_ROOT = Path.home() / "Downloads" / "tiktok"
DEFAULT_DATA_ROOT = Path(
    os.environ.get("REFERENCE_FACTORY_DATA_ROOT", _PATHS.reference_data_root)
)
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "reference_factory.sqlite"
CONTENTFORGE_APPLE_VISION_SCRIPT = Path(
    os.environ.get(
        "CONTENTFORGE_APPLE_VISION_SCRIPT",
        _PATHS.contentforge_root / "scripts" / "apple-vision-ocr.swift",
    )
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
