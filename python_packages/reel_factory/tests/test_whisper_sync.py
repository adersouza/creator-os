from whisper_sync import spoken_hook_from_segments


def test_spoken_hook_uses_first_three_seconds_only():
    segments = [
        {"text": "first line", "start": 0.0, "end": 1.0},
        {"text": "second beat", "start": 2.4, "end": 3.2},
        {"text": "late payoff", "start": 3.1, "end": 4.0},
    ]

    assert spoken_hook_from_segments(segments) == "first line second beat"
