from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from reel_factory.intent_video_bakeoff import (
    REVIEW_FIELDS,
    build_intent_video_bakeoff_manifest,
)


def _capabilities() -> dict[str, object]:
    return {
        "models": [
            {"job_type": "kling3_0"},
            {"job_type": "seedance_2_0"},
            {"job_type": "kling3_0_motion_control"},
            {"job_type": "veo3_1"},
        ],
        "workflows": [],
    }


def _spec(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "source.jpg"
    driving = tmp_path / "driving.mp4"
    speech = tmp_path / "speech.wav"
    source.write_bytes(b"source-image")
    driving.write_bytes(b"driving-video")
    speech.write_bytes(b"speech-audio")

    def base(index: int) -> dict[str, object]:
        return {
            "creator": f"creator-{index}",
            "soulId": f"soul-{index}",
            "sourceImage": str(source),
            "sourceApproval": f"source-approval-{index}",
        }

    passive = [base(index) for index in range(1, 4)]
    motion = [
        {
            **base(index),
            "drivingVideo": str(driving),
            "drivingApproval": f"driving-approval-{index}",
        }
        for index in range(1, 3)
    ]
    talking = [
        {
            **base(index),
            "speechAudio": str(speech),
            "speechApproval": f"speech-approval-{index}",
            "script": f"Exact script {index}.",
        }
        for index in range(1, 3)
    ]
    talking_motion = [
        {
            **base(1),
            "drivingVideo": str(driving),
            "drivingApproval": "driving-approval-1",
            "speechAudio": str(speech),
            "speechApproval": "speech-approval-1",
            "script": "Exact combined script.",
        }
    ]
    return {
        "passiveSelfie": passive,
        "motionCopy": motion,
        "talkingSelfie": talking,
        "talkingMotionCopy": talking_motion,
    }


def test_manifest_binds_every_candidate_to_same_sample_inputs(
    tmp_path: Path,
) -> None:
    manifest = build_intent_video_bakeoff_manifest(
        _spec(tmp_path),
        review_root=tmp_path / "review",
        higgsfield_capabilities=_capabilities(),
    )

    assert manifest["operatorVisualSelectionRequired"] is True
    assert manifest["productionDefaultsSelected"] is False
    assert manifest["publishingAllowed"] is False
    assert manifest["schedulingAllowed"] is False
    passive = [
        row for row in manifest["outputs"] if row["sampleId"] == "passiveSelfie_1"
    ]
    assert len(passive) == 4
    assert len({row["inputFingerprint"] for row in passive}) == 1
    assert {row["provider"] for row in passive} == {"higgsfield", "wavespeed"}
    assert all(set(row["review"]) == set(REVIEW_FIELDS) for row in passive)


def test_manifest_records_actual_unavailable_higgsfield_features(
    tmp_path: Path,
) -> None:
    manifest = build_intent_video_bakeoff_manifest(
        _spec(tmp_path),
        review_root=tmp_path / "review",
        higgsfield_capabilities=_capabilities(),
    )

    outputs = {row["candidateId"]: row for row in manifest["outputs"]}
    assert outputs["higgsfield_replace"]["status"] == "unavailable"
    assert outputs["higgsfield_speak"]["status"] == "unavailable"
    assert outputs["higgsfield_motion_transfer_plus_lipsync"]["status"] == "unavailable"
    assert outputs["higgsfield_veo31_talking"]["status"] == "planned"
    assert (
        outputs["wavespeed_motion_control_plus_sync3"]["pipeline"][-1]
        == "wavespeed_sync_lipsync3"
    )


def test_manifest_hashes_source_driving_and_speech_files(tmp_path: Path) -> None:
    manifest = build_intent_video_bakeoff_manifest(
        _spec(tmp_path),
        review_root=tmp_path / "review",
        higgsfield_capabilities=_capabilities(),
    )
    sample = manifest["samples"]["talkingMotionCopy"][0]

    assert (
        sample["sourceImage"]["sha256"] == hashlib.sha256(b"source-image").hexdigest()
    )
    assert (
        sample["drivingVideo"]["sha256"] == hashlib.sha256(b"driving-video").hexdigest()
    )
    assert (
        sample["speechAudio"]["sha256"] == hashlib.sha256(b"speech-audio").hexdigest()
    )


def test_manifest_requires_exact_small_cohort_sizes(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    spec["passiveSelfie"] = spec["passiveSelfie"][:2]

    with pytest.raises(ValueError, match="exactly 3"):
        build_intent_video_bakeoff_manifest(
            spec,
            review_root=tmp_path / "review",
            higgsfield_capabilities=_capabilities(),
        )
