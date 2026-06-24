from post_render import _caption_kind, _short_caption


def test_caption_kind_labels_clean_timed_and_normal():
    timed = '{"segments":[{"text":"first"},{"text":"second"}]}'

    assert _caption_kind("v00_passthrough", timed) == "clean"
    assert _caption_kind("v01_original", timed) == "timed"
    assert _caption_kind("v01_original", "normal caption") == "caption"
    assert _short_caption(timed) == "first / second"
