from __future__ import annotations

from feature_extract import extract_features


def test_extract_features_uses_captured_prompt_and_caption_lineage() -> None:
    features = extract_features(
        "Stacey in a bathroom mirror selfie, standing in a black bikini with a slow hip sway and curvy hourglass styling.",
        {
            "rawCaptionText": "Wait until the end",
            "captionOutcomeContext": {
                "length_class": "short",
                "format_class": "direct",
            },
            "audio_selection": {"track_id": "ranked_track_7"},
        },
    )

    non_unknown = [
        value
        for key, value in features.items()
        if key != "grid_source" and value not in (None, "", "unknown")
    ]
    assert len(non_unknown) >= 6
    assert features["creator"] == "stacey"
    assert features["scene"] == "bathroom_mirror"
    assert features["camera"] == "mirror_selfie"
    assert features["pose"] == "standing"
    assert features["motion"] == "hip_sway"
    assert features["outfit"] == "bikini"
    assert features["body_style"] == "thick_hourglass"
    assert features["caption_style"] == "short_direct"
    assert features["hook_type"] == "curiosity"
    assert features["audio_track_id"] == "ranked_track_7"
