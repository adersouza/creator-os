from __future__ import annotations

from copy import deepcopy

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis_jsonschema import from_schema

from pipeline_contracts import (
    ContractValidationError,
    load_example,
    load_schema,
    validate_audio_intent,
    validate_higgsfield_soul_image_prompt,
    validate_reference_video_motion_analysis,
)

FUZZ_SETTINGS = settings(
    max_examples=20,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)


@FUZZ_SETTINGS
@given(from_schema(load_schema("reference_video_motion_analysis")))
def test_strict_motion_analysis_accepts_schema_generated_payloads(
    payload: object,
) -> None:
    validate_reference_video_motion_analysis(payload)


@FUZZ_SETTINGS
@given(from_schema(load_schema("higgsfield_soul_image_prompt")))
def test_soul_prompt_accepts_schema_generated_payloads(payload: object) -> None:
    validate_higgsfield_soul_image_prompt(payload)


@FUZZ_SETTINGS
@given(from_schema(load_schema("audio_intent")))
def test_permissive_audio_intent_accepts_schema_generated_payloads(
    payload: object,
) -> None:
    validate_audio_intent(payload)


@FUZZ_SETTINGS
@given(from_schema(load_schema("reference_video_motion_analysis")))
def test_required_field_mutations_fail_closed(payload: object) -> None:
    assert isinstance(payload, dict)
    malformed = deepcopy(payload)
    malformed.pop("referenceId")

    with pytest.raises(ContractValidationError, match="referenceId"):
        validate_reference_video_motion_analysis(malformed)


@FUZZ_SETTINGS
@given(from_schema(load_schema("audio_intent")))
def test_wrong_type_mutations_fail_closed(payload: object) -> None:
    assert isinstance(payload, dict)
    malformed = deepcopy(payload)
    malformed["required"] = "yes"

    with pytest.raises(ContractValidationError, match="required"):
        validate_audio_intent(malformed)


@given(st.sampled_from([5, 12]))
def test_motion_duration_contract_accepts_both_inclusive_boundaries(
    duration_seconds: int,
) -> None:
    payload = load_example("reference_video_motion_analysis")
    payload["source"]["durationSeconds"] = duration_seconds

    validate_reference_video_motion_analysis(payload)


@FUZZ_SETTINGS
@given(from_schema(load_schema("reference_video_motion_analysis")))
def test_strict_contract_rejects_unknown_fields(payload: object) -> None:
    assert isinstance(payload, dict)
    malformed = deepcopy(payload)
    malformed["unexpectedContractField"] = True

    with pytest.raises(ContractValidationError, match="unexpectedContractField"):
        validate_reference_video_motion_analysis(malformed)


@FUZZ_SETTINGS
@given(from_schema(load_schema("audio_intent")))
def test_explicitly_permissive_contract_keeps_unknown_fields_compatible(
    payload: object,
) -> None:
    assert isinstance(payload, dict)
    compatible = deepcopy(payload)
    compatible["futureConsumerField"] = {"version": 2}

    validate_audio_intent(compatible)
