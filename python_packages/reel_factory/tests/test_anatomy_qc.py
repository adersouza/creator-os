from pathlib import Path

from anatomy_qc import assess_anatomy, filter_plausible, is_postable

HERE = Path(__file__)


def _clean(frames, instruction):
    return '{"plausible": true, "severity": "none", "defects": []}'


def _severe(frames, instruction):
    return '```json\n{"plausible": false, "severity": "severe", "defects": ["6 fingers"]}\n```'


def _minor(frames, instruction):
    return '{"plausible": true, "severity": "minor", "defects": ["slightly odd hand"]}'


def _boom(frames, instruction):
    raise RuntimeError("provider down")


def test_clean_is_postable():
    a = assess_anatomy(HERE, vision_call=_clean)
    assert a["available"] and a["plausible"] and is_postable(a)


def test_severe_defect_rejected():
    a = assess_anatomy(HERE, vision_call=_severe)  # fence-wrapped JSON must parse
    assert a["available"] and not a["plausible"] and not is_postable(a)
    assert a["defects"] == ["6 fingers"]


def test_minor_is_allowed():
    a = assess_anatomy(HERE, vision_call=_minor)
    assert is_postable(a)


def test_provider_down_fails_closed():
    a = assess_anatomy(HERE, vision_call=_boom)
    assert a["available"] is False and not is_postable(a)


def test_missing_file_rejected():
    a = assess_anatomy(HERE.parent / "does_not_exist.png", vision_call=_clean)
    assert not is_postable(a)


def test_filter_splits_kept_rejected():
    kept, rejected = filter_plausible([HERE, HERE], vision_call=_severe)
    assert not kept and len(rejected) == 2
