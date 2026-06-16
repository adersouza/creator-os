"""Runtime guard for deprecated local generation paths."""
from __future__ import annotations

import os


DEPRECATED_GENERATOR_FLAG = "REEL_FACTORY_RAISE_ON_DEPRECATED_GENERATORS"
TRUTHY = {"1", "true", "yes", "on"}


def guard_deprecated_generator(feature: str) -> None:
    """Raise when operators intentionally enable the deprecation kill switch."""
    if os.environ.get(DEPRECATED_GENERATOR_FLAG, "").strip().lower() in TRUTHY:
        raise RuntimeError(
            f"{feature} is deprecated; unset {DEPRECATED_GENERATOR_FLAG} only for local migration review"
        )
