from __future__ import annotations

from reel_factory.fetch_models import (
    INSIGHTFACE_REQUIRED,
    INSIGHTFACE_SHA256,
    MODELS,
)


def test_every_downloaded_model_and_archive_has_a_sha256_pin() -> None:
    assert MODELS
    for specification in MODELS.values():
        assert specification["url"].startswith("https://")
        assert len(specification["sha256"]) == 64
        int(specification["sha256"], 16)

    assert len(INSIGHTFACE_SHA256) == 64
    int(INSIGHTFACE_SHA256, 16)
    assert INSIGHTFACE_REQUIRED
    for digest in INSIGHTFACE_REQUIRED.values():
        assert len(digest) == 64
        int(digest, 16)
