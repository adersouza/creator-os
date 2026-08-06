"""The audio rules must stay single-sourced across the factories.

Campaign Factory and Reference Factory both decide whether audio is licensed and
whether a title is a placeholder. When those rules existed as two copies they had
already drifted textually. This pins them to one implementation: the identity
assertions fail if anyone reintroduces a local copy.
"""

from __future__ import annotations

import pytest
from creator_os_core import audio_rules


def test_both_factories_use_the_shared_rule_objects() -> None:
    campaign_recs = pytest.importorskip("campaign_factory.audio_recommendations")
    reference_audio = pytest.importorskip("reference_factory.audio")

    assert campaign_recs.is_reel_page_url is audio_rules.is_reel_page_url
    assert campaign_recs.audio_preview_evidence is audio_rules.audio_preview_evidence

    repo = campaign_recs.AudioRecommendationRepository
    assert repo.audio_rights_status is audio_rules.audio_rights_status
    assert repo.is_generic_audio_title is audio_rules.is_generic_audio_title
    assert repo.is_native_audio_url is audio_rules.is_native_audio_url

    assert reference_audio.audio_rights_status is audio_rules.audio_rights_status
    assert reference_audio.is_generic_audio_title is audio_rules.is_generic_audio_title
    assert reference_audio._is_native_audio_url is audio_rules.is_native_audio_url
    assert reference_audio._is_reel_page_url is audio_rules.is_reel_page_url


@pytest.mark.parametrize(
    ("title", "platform", "expected"),
    [
        ("", "tiktok", True),
        (None, "tiktok", True),
        ("tiktok audio 12345", "tiktok", True),
        ("instagram audio ab_9 (title unresolved)", "instagram", True),
        ("tiktok audio 12345", "instagram", False),
        ("Real Song Name", "tiktok", False),
        ("TIKTOK AUDIO xyz-1", None, True),
    ],
)
def test_is_generic_audio_title(title: str, platform: str | None, expected: bool) -> None:
    assert audio_rules.is_generic_audio_title(title, platform) is expected


@pytest.mark.parametrize(
    ("url", "platform", "native", "reel"),
    [
        ("https://www.tiktok.com/music/abc-123", "tiktok", True, False),
        ("https://tiktok.com/@u/video/77", "tiktok", False, True),
        ("https://instagram.com/reels/audio/99/", "instagram", True, False),
        ("https://instagram.com/reel/XYZ", "instagram", False, True),
        ("https://evil.com/music/x", "tiktok", False, False),
        ("http://[bad", "tiktok", False, False),
        ("", "tiktok", False, False),
    ],
)
def test_url_classification(url: str, platform: str, native: bool, reel: bool) -> None:
    assert audio_rules.is_native_audio_url(url, platform) is native
    assert audio_rules.is_reel_page_url(url, platform) is reel


def test_rights_status_reads_every_accepted_shape() -> None:
    assert audio_rules.audio_rights_status({}) == ""
    assert audio_rules.audio_rights_status({"rightsStatus": "Licensed-Cleared"}) == (
        "licensed_cleared"
    )
    assert (
        audio_rules.audio_rights_status({"raw": {"rights": {"status": "UNVERIFIED"}}})
        == "unverified"
    )
    assert (
        audio_rules.audio_rights_status({"rights": {"usageRightsStatus": "blocked "}})
        == "blocked"
    )
    # A non-dict in a dict-shaped slot must not raise.
    assert audio_rules.audio_rights_status({"rights": "nope", "raw": None}) == ""


def test_preview_evidence_flags_malformed_sha256() -> None:
    assert audio_rules.audio_preview_evidence({}) == {}
    assert audio_rules.audio_preview_evidence(
        {"localPreviewPath": " /a/b.mp3 ", "previewSha256": "AB" * 32}
    ) == {"path": "/a/b.mp3", "sha256": "ab" * 32, "sha256Format": "valid"}
    assert audio_rules.audio_preview_evidence(
        {"previewEvidence": {"path": "p", "sha256": "zz"}}
    ) == {"path": "p", "sha256": "zz", "sha256Format": "invalid"}
