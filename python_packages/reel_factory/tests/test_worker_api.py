from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from creator_os_core.task_parameters import (
    benchmark_task_parameter_fingerprint,
    task_parameter_fingerprint,
)
from reel_factory.local_generation_queue import fingerprint
from reel_factory.local_video import (
    LocalVideoRequest,
    local_video_task_parameter_material,
)
from reel_factory.worker_api import admit_local_motion

MODEL_ID = "local_wan22_ti2v_5b_mlx"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
HARDWARE_SHA = "d" * 64


def _parameter_material() -> dict:
    return local_video_task_parameter_material(
        LocalVideoRequest(
            model_id=MODEL_ID,
            image_path=None,
            prompt="A person moves naturally within the original composition",
            output_path=Path("/tmp/not-executed.mp4"),
            duration_seconds=6,
            resolution="720p",
            seed=42,
        )
    )


def _patch_admission_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, dict, dict]:
    identity = {
        "schema": "creator_os.creator_identity_profile.v1",
        "profileId": "profile-stacey",
        "creatorKey": "stacey",
    }
    intent = {
        "schema": "creator_os.content_intent.v1",
        "intentId": "intent-stacey-motion",
        "sourceAssetFingerprints": [SHA_A, SHA_B, SHA_C],
    }
    material = _parameter_material()
    plan = {
        "samples": [
            {
                "sampleId": f"sample-{suffix}",
                "modelId": MODEL_ID,
                "taskKind": "image_to_video",
                "sourcePath": f"/reviewed/{suffix}.png",
                "sourceSha256": source_sha,
                "audioSha256": None,
                "lastImageSha256": None,
                "sourceVideoSha256": None,
                "taskParameterMaterial": material,
                "taskParameterFingerprint": task_parameter_fingerprint(material),
            }
            for suffix, source_sha in (("a", SHA_A), ("b", SHA_B))
        ]
    }
    summary = {
        "planId": "plan-1",
        "summaryId": "summary-1",
        "summaryFingerprint": "e" * 64,
        "planFingerprint": "f" * 64,
        "purpose": "promotion_eligible",
        "samples": [
            {
                "creatorId": "stacey",
                "identityProfileId": identity["profileId"],
                "identityProfileFingerprint": fingerprint(identity),
                "contentIntentId": intent["intentId"],
                "contentIntentFingerprint": fingerprint(intent),
                "taskKind": "image_to_video",
                "capabilityCohort": "silent_i2v",
            }
        ],
    }

    class ArenaStore:
        def __init__(self, _root):
            pass

        def load_plan(self, _plan_id):
            return plan

        def load_review_packet(self, _plan_id):
            return {}

        def load_unblinding_receipt(self, _plan_id, **_kwargs):
            return {}

    monkeypatch.setattr(
        "reel_factory.worker_api.default_local_generation_queue",
        lambda: SimpleNamespace(
            memory_reserve_bytes=1_024,
            resource_limit_bytes=64 * 1024**3,
        ),
    )
    monkeypatch.setattr(
        "reel_factory.worker_api._macos_available_memory_bytes",
        lambda: 48 * 1024**3,
    )
    monkeypatch.setattr(
        "reel_factory.worker_api.default_local_model_benchmark_store",
        lambda: SimpleNamespace(root="/fixture/benchmarks"),
    )
    monkeypatch.setattr("reel_factory.worker_api.LocalModelArenaStore", ArenaStore)
    monkeypatch.setattr(
        "reel_factory.worker_api.HumanMediaReviewStore",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "reel_factory.worker_api.route_local_model",
        lambda *_args, **_kwargs: {
            "selectedModelId": MODEL_ID,
            "winningEvidence": {
                "validArenaSampleIds": ["sample-a", "sample-b"],
                "promotionApproval": {"hardwareFingerprint": HARDWARE_SHA},
            },
        },
    )
    monkeypatch.setattr(
        "reel_factory.worker_api.hardware_identity",
        lambda: {"fingerprint": HARDWARE_SHA},
    )
    return identity, intent, summary


def _records(identity: dict, intent: dict, input_sha: str) -> dict:
    material = _parameter_material()
    return {
        "creatorIdentityProfile": identity,
        "contentIntent": intent,
        "executionPolicy": {"schema": "creator_os.execution_policy.v1"},
        "benchmarkRecipe": {
            "taskKind": "image_to_video",
            "inputFingerprints": [input_sha],
            "parameterFingerprint": benchmark_task_parameter_fingerprint(material),
        },
        "analyzerRegistry": {"schema": "creator_os.analyzer_registry.v1"},
    }


def _admit(
    *,
    summary: dict,
    identity: dict,
    intent: dict,
    input_sha: str,
    role: str,
    **request_overrides,
) -> dict:
    return admit_local_motion(
        arena_summary=summary,
        evidence_records=_records(identity, intent, input_sha),
        input_fingerprints=[input_sha],
        input_bindings=[{"role": role, "sha256": input_sha}],
        creator_id="stacey",
        identity_profile_id=identity["profileId"],
        identity_profile_fingerprint=fingerprint(identity),
        content_intent_id=intent["intentId"],
        content_intent_fingerprint=fingerprint(intent),
        task_kind="image_to_video",
        **request_overrides,
    )


def test_admission_allows_only_exact_typed_inputs_measured_by_winning_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)

    admission = _admit(
        summary=summary,
        identity=identity,
        intent=intent,
        input_sha=SHA_A,
        role="image",
    )

    assert admission["inputBindings"] == [{"role": "image", "sha256": SHA_A}]
    assert {
        tuple((item["role"], item["sha256"]) for item in bindings)
        for bindings in admission["promotionInputCohort"]
    } == {
        (("image", SHA_A),),
        (("image", SHA_B),),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "A different approved prompt changes the motion"),
        ("duration_seconds", 8),
        ("resolution", "1080p"),
        ("seed", 43),
        ("steps", 24),
        ("audio_mode", "generated"),
    ],
)
def test_admission_rejects_unbenchmarked_task_parameter_cell(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)

    with pytest.raises(ValueError, match="task_parameter_mismatch"):
        _admit(
            summary=summary,
            identity=identity,
            intent=intent,
            input_sha=SHA_A,
            role="image",
            **{field: value},
        )


def test_admission_rejects_unbenchmarked_lora_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)
    lora = tmp_path / "unbenchmarked.safetensors"
    lora.write_bytes(b"different lora bytes")

    with pytest.raises(ValueError, match="task_parameter_mismatch"):
        _admit(
            summary=summary,
            identity=identity,
            intent=intent,
            input_sha=SHA_A,
            role="image",
            lora_path=lora,
            lora_strength=0.75,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("duration_seconds", 0, "positive_integer_required"),
        ("resolution", "", "model_shape_missing"),
    ],
)
def test_admission_does_not_default_explicit_invalid_parameters(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object, error: str
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)

    with pytest.raises(ValueError, match=error):
        _admit(
            summary=summary,
            identity=identity,
            intent=intent,
            input_sha=SHA_A,
            role="image",
            **{field: value},
        )


def test_admission_rejects_authorized_but_unbenchmarked_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)

    with pytest.raises(ValueError, match="input_not_in_promoted_cohort"):
        _admit(
            summary=summary,
            identity=identity,
            intent=intent,
            input_sha=SHA_C,
            role="image",
        )


def test_admission_rejects_benchmarked_hash_in_wrong_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)

    with pytest.raises(ValueError, match="required_role_missing"):
        _admit(
            summary=summary,
            identity=identity,
            intent=intent,
            input_sha=SHA_A,
            role="audio",
        )


def test_admission_rejects_winning_sample_from_another_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, intent, summary = _patch_admission_runtime(monkeypatch)

    class ArenaStore:
        def __init__(self, _root):
            pass

        def load_plan(self, _plan_id):
            return {
                "samples": [
                    {
                        "sampleId": "sample-a",
                        "modelId": MODEL_ID,
                        "taskKind": "keyframe_interpolation",
                        "sourcePath": "/reviewed/a.png",
                        "sourceSha256": SHA_A,
                        "audioSha256": None,
                        "lastImageSha256": SHA_B,
                        "sourceVideoSha256": None,
                    }
                ]
            }

        def load_review_packet(self, _plan_id):
            return {}

        def load_unblinding_receipt(self, _plan_id, **_kwargs):
            return {}

    monkeypatch.setattr("reel_factory.worker_api.LocalModelArenaStore", ArenaStore)
    monkeypatch.setattr(
        "reel_factory.worker_api.route_local_model",
        lambda *_args, **_kwargs: {
            "selectedModelId": MODEL_ID,
            "winningEvidence": {
                "validArenaSampleIds": ["sample-a"],
                "promotionApproval": {"hardwareFingerprint": HARDWARE_SHA},
            },
        },
    )

    with pytest.raises(ValueError, match="promoted_sample_binding_invalid"):
        _admit(
            summary=summary,
            identity=identity,
            intent=intent,
            input_sha=SHA_A,
            role="image",
        )
