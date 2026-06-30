import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_DIR = ROOT / "fixtures" / "manifest_v2"
VISUAL_QC_DIR = ROOT / "fixtures" / "visual_qc"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_v2_fixture_set_covers_all_surfaces():
    expected = {
        "reel_manifest_v2_valid.json": ("reel", "REELS"),
        "story_manifest_v2_valid.json": ("story", "STORIES"),
        "feed_single_manifest_v2_valid.json": ("feed_single", "IMAGE"),
        "feed_carousel_manifest_v2_valid.json": ("feed_carousel", "CAROUSEL"),
        "trial_reel_manifest_v2_valid.json": ("reel", "REELS"),
    }

    assert {path.name for path in MANIFEST_DIR.glob("*.json")} == set(expected)

    for filename, (surface, ig_media_type) in expected.items():
        payload = _load_json(MANIFEST_DIR / filename)
        assert payload["manifest_version"] == 2
        assert payload["content_surface"] == surface
        assert payload["contentSurface"] == surface
        assert payload["ig_media_type"] == ig_media_type
        assert payload["igMediaType"] == ig_media_type
        assert payload["content_hash"]
        assert payload["content_fingerprint"] == payload["content_hash"]
        assert isinstance(payload["mediaItems"], list) and payload["mediaItems"]
        assert payload["surfaceReadiness"]["canHandoff"] is True
        assert payload["surfaceReadiness"]["blockingReasons"] == []
        assert payload["wouldWrite"] is False


def test_manifest_v2_caption_contracts_are_surface_native():
    reel = _load_json(MANIFEST_DIR / "reel_manifest_v2_valid.json")
    trial = _load_json(MANIFEST_DIR / "trial_reel_manifest_v2_valid.json")
    story = _load_json(MANIFEST_DIR / "story_manifest_v2_valid.json")
    feed = _load_json(MANIFEST_DIR / "feed_single_manifest_v2_valid.json")
    carousel = _load_json(MANIFEST_DIR / "feed_carousel_manifest_v2_valid.json")

    for payload in [reel, trial]:
        assert payload["caption_hash"]
        assert payload["instagram_post_caption"]
        assert payload["caption_family_id"]
        assert payload["caption_version_id"]

    assert story["content_surface"] == "story"
    assert story["instagram_post_caption"] == ""
    assert story["story_intent"] == "snapchat_promo"

    for payload in [feed, carousel]:
        assert payload["caption_hash"] == ""
        assert payload["instagram_post_caption"]
        assert payload["caption_family_id"]
        assert payload["caption_version_id"]


def test_trial_reel_manifest_requires_explicit_trial_contract():
    payload = _load_json(MANIFEST_DIR / "trial_reel_manifest_v2_valid.json")

    assert payload["content_surface"] == "reel"
    assert payload["ig_media_type"] == "REELS"
    assert payload["distribution_surface"] == "trial_reel"
    assert payload["instagram_trial_reels"] is True
    assert payload["trial_graduation_strategy"] in {"MANUAL", "SS_PERFORMANCE"}


def test_carousel_manifest_v2_preserves_slide_order_and_hashes():
    payload = _load_json(MANIFEST_DIR / "feed_carousel_manifest_v2_valid.json")
    media_items = payload["mediaItems"]

    assert 2 <= len(media_items) <= 10
    assert [item["componentIndex"] for item in media_items] == list(
        range(len(media_items))
    )
    assert [item["mediaHash"] for item in media_items] == [
        "hash_carousel_slide_0",
        "hash_carousel_slide_1",
        "hash_carousel_slide_2",
    ]


def test_visual_qc_fixture_set_covers_pass_and_fail_cases():
    fixtures = {path.stem: _load_json(path) for path in VISUAL_QC_DIR.glob("*.json")}

    assert set(fixtures) == {
        "story_valid_1080x1920",
        "story_black_bars",
        "story_bad_aspect_ratio",
        "story_safe_zone_violation",
        "feed_image_valid",
        "carousel_valid_ordered_slides",
        "carousel_bad_slide_order",
    }
    assert fixtures["story_valid_1080x1920"]["expectedPass"] is True
    assert fixtures["story_black_bars"]["expectedFailureReasons"] == ["black_bars"]
    assert fixtures["story_bad_aspect_ratio"]["expectedFailureReasons"] == [
        "story_aspect_ratio_not_safe"
    ]
    assert fixtures["story_safe_zone_violation"]["expectedFailureReasons"] == [
        "safe_zone_violation"
    ]
    assert fixtures["feed_image_valid"]["expectedPass"] is True
    assert fixtures["carousel_valid_ordered_slides"]["componentIndexes"] == [0, 1, 2]
    assert fixtures["carousel_bad_slide_order"]["expectedFailureReasons"] == [
        "carousel_components_not_ordered"
    ]
