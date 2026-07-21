from pipeline_contracts import evaluate_overlay_semantic_completeness


def test_exact_incomplete_overlay_regression_is_blocked() -> None:
    result = evaluate_overlay_semantic_completeness("men, stop doing this:")

    assert result["passed"] is False
    assert result["failure_reasons"] == ["missing_overlay_payoff_after_setup"]
    assert result["segment_count"] == 1


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


def test_visually_resolved_labels_and_open_loops_are_not_overblocked() -> None:
    for caption in (
        "before gym:",
        "POV:",
        "men, stop sending one-word replies",
        "would you date me or run away?",
        'finish this: "she looks like she..."',
    ):
        result = evaluate_overlay_semantic_completeness(caption)
        assert result["passed"] is True, caption


def test_enumerated_promise_without_payoffs_is_blocked() -> None:
    result = evaluate_overlay_semantic_completeness("3 reasons why you should date me")

    assert result["passed"] is False
    assert result["failure_reasons"] == ["missing_enumerated_overlay_payoffs"]
    assert result["required_payoff_count"] == 3
    assert result["payoff_segment_count"] == 0


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
