from __future__ import annotations

from generate_variants import build_spec, clean_prompt, pick_aspect, sexy_variant

_ENHANCED = (
    "A slightly high-angle, close-up selfie of a young Caucasian woman with long "
    "dark hair, posing outdoors on a beach. She is wearing a black lace bikini top "
    "with thin straps. She has a small hoop nose ring. The image is framed as a "
    "digital screenshot of a social media post, with an oversized blue plus sign "
    "at the bottom.\n"
    'HEX VALUES: ["#000000", "#7f534a"]'
)


def test_clean_strips_identity_and_ui_keeps_scene_and_outfit() -> None:
    cleaned = clean_prompt(_ENHANCED).lower()
    for banned in (
        "caucasian",
        "dark hair",
        "woman",
        "nose ring",
        "screenshot",
        "plus sign",
        "hex values",
    ):
        assert banned not in cleaned, f"{banned!r} survived: {cleaned}"
    assert "bikini" in cleaned  # outfit kept
    assert "beach" in cleaned  # scene kept
    assert "of a," not in cleaned


def test_clean_keeps_object_colors_and_leaves_no_debris() -> None:
    # regression: "white" is an object color, not just ethnicity; "shot on a
    # smartphone" and "she appears to be in her 20s" must not leave dangling stubs.
    src = (
        "A close-up selfie of a young Caucasian woman with long dark brown hair, "
        "she appears to be in her early 20s, wearing a bikini, stacked white lounge "
        "chairs and a blue and white sky behind, shot on a smartphone."
    )
    cleaned = clean_prompt(src)
    low = cleaned.lower()
    assert "white lounge chairs" in low  # object color survives
    assert "blue and white sky" in low
    assert "caucasian" not in low and "dark brown hair" not in low
    assert "appears to be" not in low
    assert "shot on a," not in low and "on a smartphone" not in low
    assert "  " not in cleaned  # no double spaces
    assert ", ," not in cleaned and ". ," not in cleaned  # no punctuation debris


def test_sexy_variant_is_append_only_cleavage() -> None:
    sexy = sexy_variant("on a beach in a bikini", include_butt=False)
    assert sexy.startswith("on a beach in a bikini")
    assert "cleavage" in sexy.lower()
    assert "butt" not in sexy.lower()  # cleavage-only for a selfie


def test_pick_aspect_selfie_vs_fullbody_vs_reel() -> None:
    assert pick_aspect("a close-up selfie in a bikini") == "3:4"
    assert pick_aspect("a wide shot seated on a boat, legs forward") == "2:3"
    assert pick_aspect("a vertical video reel of a beach") == "9:16"


def test_spec_reuses_original_and_plans_exactly_one_text_only_sexy_call() -> None:
    spec = build_spec(_ENHANCED, soul_id="soul-1", reference_media_id="ref-9")
    # sexy MUST be text-only or the ref re-enhances and wipes the body edit
    assert spec["sexy"]["text_only"] is True
    assert spec["sexy"]["reference_media_id"] is None
    assert "cleavage" in spec["sexy"]["prompt"].lower()
    assert spec["sexy"]["generation_required"] is True
    # The reference-pass result is already the original; never pay to rerun it.
    assert spec["original"]["source"] == "reference_pass_result"
    assert spec["original"]["generation_required"] is False
    assert spec["original"]["reference_media_id"] == "ref-9"
    assert spec["original"]["aspect_ratio"] == spec["sexy"]["aspect_ratio"]
    assert spec["provider_generation_count"] == 1
    assert "run only the sexy" in spec["next"]


def test_stacey_sexy_prompt_uses_exact_operator_identity_phrase() -> None:
    spec = build_spec(
        _ENHANCED,
        soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
        reference_media_id="ref-9",
    )
    prompt = spec["sexy"]["prompt"].lower()
    assert "19 years old" in prompt
    assert "dark hair" in prompt
    assert "no tattoos" in prompt
    for banned in ("adult", "woman", "girl", "teen", "young"):
        assert banned not in prompt


def test_stacey_prompt_removes_standalone_adult_word() -> None:
    spec = build_spec(
        "A mirror selfie with an adult subject in a social media story interface.",
        soul_id="d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
    )
    prompt = spec["sexy"]["prompt"].lower()
    assert "19 years old" in prompt
    for banned in ("adult", "woman", "girl", "teen", "young"):
        assert banned not in prompt
    assert "in an" not in prompt
    assert " ," not in prompt
