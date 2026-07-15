from pathlib import Path

from reel_factory.anatomy_qc import (
    assess_anatomy,
    assess_image_qc,
    filter_plausible,
    filter_postable,
    is_image_postable,
    is_postable,
)

HERE = Path(__file__)


def _clean(frames, instruction):
    return '{"plausible": true, "severity": "none", "defects": []}'


def _severe(frames, instruction):
    return '```json\n{"plausible": false, "severity": "severe", "defects": ["6 fingers"]}\n```'


def _minor(frames, instruction):
    return '{"plausible": true, "severity": "minor", "defects": ["slightly odd hand"]}'


def _boom(frames, instruction):
    raise RuntimeError("provider down")


def _image_clean(frames, instruction):
    return '{"anatomy": {"plausible": true, "severity": "none", "defects": []}, "exposure": {"safe": true, "severity": "none", "issues": []}}'


def _image_exposed(frames, instruction):
    return '{"anatomy": {"plausible": true, "severity": "none", "defects": []}, "exposure": {"safe": false, "severity": "severe", "issues": ["visible nipple"]}}'


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


def test_exposure_gate_rejects_explicit_image():
    a = assess_image_qc(HERE, vision_call=_image_exposed)
    assert a["exposure"]["issues"] == ["visible nipple"]
    assert not is_image_postable(a)


def test_filter_postable_uses_anatomy_and_exposure():
    kept, rejected = filter_postable([HERE, HERE], vision_call=_image_clean)
    assert len(kept) == 2 and not rejected
