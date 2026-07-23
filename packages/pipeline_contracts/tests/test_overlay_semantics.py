import pytest

from pipeline_contracts import (
    evaluate_overlay_semantic_completeness,
    evaluate_overlay_timing,
)


def test_exact_incomplete_overlay_regression_is_blocked() -> None:
    result = evaluate_overlay_semantic_completeness("men, stop doing this:")

    assert result["passed"] is False
    assert result["failure_reasons"] == ["missing_overlay_payoff_after_setup"]
    assert result["segment_count"] == 1


def test_contentforge_clip004_pixel_pass_still_requires_semantic_payoff() -> None:
    """Keep pixel delivery evidence separate from semantic completeness.

    This is the exact one-line sequence observed by the provider-free
    ContentForge canary over all 14 sampled frames of preserved clip_004
    (media SHA-256 de97f2be4753c8b68ce594f93d872e18e39ef6929516b6f92a89579e64bb1fe1).
    OCR/readability/safe-zone passing cannot turn an unfinished setup into a
    complete caption.
    """

    contentforge_overlay_observation = {
        "available": True,
        "passed": True,
        "sampling": {
            "requestedFrames": 14,
            "analyzedFrames": 14,
            "detectedTextFrames": 14,
            "coverageRatio": 1,
            "detectionCoverageRatio": 1,
        },
        "readability": {"passed": True, "averageScore": 100},
        "safeZone": {"passed": True, "failedBoxCount": 0},
        "timedSequence": [
            {
                "text": "men, stop doing this:",
                "firstObservedAtSeconds": 0.4,
                "lastObservedAtSeconds": 13.466,
                "sampledFrameCount": 14,
            }
        ],
    }

    assert contentforge_overlay_observation["passed"] is True
    assert contentforge_overlay_observation["readability"]["passed"] is True
    assert contentforge_overlay_observation["safeZone"]["passed"] is True
    result = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": item["text"]}
                for item in contentforge_overlay_observation["timedSequence"]
            ]
        },
        require_overlay=True,
    )

    assert result["passed"] is False
    assert result["decision"] == "blocked"
    assert result["failure_reasons"] == ["missing_overlay_payoff_after_setup"]
    assert result["distinct_segment_count"] == 1


def test_repeated_timed_setup_does_not_fake_a_payoff() -> None:
    result = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": "men, stop doing this:", "end": 3.0},
                {"text": "men, stop doing this:", "start": 3.0},
            ]
        }
    )

    assert result["passed"] is False
    assert result["segment_count"] == 2
    assert result["distinct_segment_count"] == 1


def test_real_timed_payoff_passes() -> None:
    result = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": "men, stop doing this:", "end": 3.0},
                {"text": "sending one-word replies", "start": 3.0},
            ]
        }
    )

    assert result["passed"] is True
    assert result["decision"] == "timed_payoff_present"
    assert result["distinct_segment_count"] == 2


def test_distinct_timed_segments_still_block_when_final_payoff_is_missing() -> None:
    result = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": "men, stop doing this:", "end": 3.0},
                {"text": "wait for it:", "start": 3.0},
            ]
        }
    )

    assert result["passed"] is False
    assert result["failure_reasons"] == ["missing_overlay_payoff_after_setup"]


def test_serialized_timed_caption_manifest_is_understood() -> None:
    result = evaluate_overlay_semantic_completeness(
        '{"segments":[{"text":"wait for it:","end":2},{"text":"the reveal","start":2}]}'
    )

    assert result["passed"] is True
    assert result["decision"] == "timed_payoff_present"


def test_self_contained_labels_and_open_loops_are_not_overblocked() -> None:
    for caption in (
        "POV:",
        "men, stop sending one-word replies",
        "would you date me or run away?",
        'finish this: "she looks like she..."',
    ):
        result = evaluate_overlay_semantic_completeness(caption)
        assert result["passed"] is True, caption


def test_before_state_requires_after_state_or_human_semantic_approval() -> None:
    blocked = evaluate_overlay_semantic_completeness("before gym:")
    approved = evaluate_overlay_semantic_completeness(
        "before gym:", human_semantic_approval=True
    )
    timed = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": "before gym:", "start": 0.0, "end": 2.0},
                {"text": "after gym: still smiling", "start": 2.0},
            ]
        },
        duration_seconds=5.0,
    )

    assert blocked["passed"] is False
    assert blocked["failure_reasons"] == ["missing_overlay_payoff_after_before_state"]
    assert approved["passed"] is True
    assert approved["decision"] == "human_semantic_approval"
    assert timed["passed"] is True
    assert timed["timing_verified"] is True


def test_enumerated_promise_without_payoffs_is_blocked() -> None:
    result = evaluate_overlay_semantic_completeness("3 reasons why you should date me")

    assert result["passed"] is False
    assert result["failure_reasons"] == ["missing_enumerated_overlay_payoffs"]
    assert result["required_payoff_count"] == 3
    assert result["payoff_segment_count"] == 0


@pytest.mark.parametrize("count", [1, 10, 12, 100])
def test_numbered_promise_detection_is_not_limited_to_two_through_nine(
    count: int,
) -> None:
    result = evaluate_overlay_semantic_completeness(
        f"{count} reasons why you should date me"
    )

    assert result["passed"] is False
    assert result["required_payoff_count"] == count


def test_enumerated_timed_caption_requires_every_promised_payoff() -> None:
    result = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": "3 reasons why you should date me", "end": 2.0},
                {"text": "I remember the little things", "start": 2.0},
                {"text": "I make boring days fun", "start": 4.0},
            ]
        }
    )

    assert result["passed"] is False
    assert result["required_payoff_count"] == 3
    assert result["payoff_segment_count"] == 2


def test_enumerated_timed_caption_passes_with_every_promised_payoff() -> None:
    result = evaluate_overlay_semantic_completeness(
        {
            "segments": [
                {"text": "3 reasons why you should date me", "end": 2.0},
                {"text": "I remember the little things", "start": 2.0},
                {"text": "I make boring days fun", "start": 4.0},
                {"text": "I actually communicate", "start": 6.0},
            ]
        }
    )

    assert result["passed"] is True
    assert result["decision"] == "timed_payoff_present"
    assert result["required_payoff_count"] == 3
    assert result["payoff_segment_count"] == 3


def test_dangling_clause_is_blocked() -> None:
    result = evaluate_overlay_semantic_completeness("I was going to tell you but…")

    assert result["passed"] is False
    assert result["failure_reasons"] == ["dangling_overlay_clause"]


def test_clean_media_without_overlay_passes() -> None:
    result = evaluate_overlay_semantic_completeness(None)

    assert result["passed"] is True
    assert result["decision"] == "no_burned_overlay"


def test_burned_overlay_requires_nonempty_text() -> None:
    result = evaluate_overlay_semantic_completeness(
        {"segments": []}, require_overlay=True
    )

    assert result["passed"] is False
    assert result["failure_reasons"] == ["missing_burned_overlay_text"]
    assert result["timed_sequence"] is True


def test_resolved_timing_rejects_payoff_after_media_ends() -> None:
    result = evaluate_overlay_timing(
        [
            {"text": "men, stop doing this:", "start": 0.0, "end": 2.0},
            {"text": "sending one-word replies", "start": 99.0, "end": None},
        ],
        duration_seconds=5.0,
    )

    assert result["passed"] is False
    assert "overlay_segment_outside_media_duration" in result["failure_reasons"]


def test_resolved_timing_rejects_empty_invalid_and_unordered_segments() -> None:
    result = evaluate_overlay_timing(
        [
            {"text": "payoff", "start": 2.0, "end": 2.0},
            {"text": "", "start": 1.0, "end": 3.0},
        ],
        duration_seconds=5.0,
    )

    assert result["passed"] is False
    assert set(result["failure_reasons"]) == {
        "missing_burned_overlay_text",
        "non_monotonic_overlay_start",
        "non_positive_overlay_interval",
    }


def test_resolved_timing_accepts_visible_ordered_sequence() -> None:
    result = evaluate_overlay_timing(
        [
            {"text": "wait for it:", "start": 0.0, "end": 2.0},
            {"text": "the reveal", "start": 2.0, "end": None},
        ],
        duration_seconds=5.0,
    )

    assert result["passed"] is True
    assert result["segments"][1]["end"] == 5.0
    assert result["resolved_render_plan"]["segments"] == [
        {
            "index": 0,
            "text": "wait for it:",
            "start": 0.0,
            "end": 2.0,
        },
        {
            "index": 1,
            "text": "the reveal",
            "start": 2.0,
            "end": 5.0,
        },
    ]


def test_fully_implicit_timed_sequence_resolves_evenly() -> None:
    result = evaluate_overlay_timing(
        [{"text": "setup"}, {"text": "payoff"}],
        duration_seconds=6.0,
    )

    assert result["passed"] is True
    assert [(row["start"], row["end"]) for row in result["segments"]] == [
        (0.0, 3.0),
        (3.0, 6.0),
    ]
