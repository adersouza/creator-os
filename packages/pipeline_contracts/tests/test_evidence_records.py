import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pipeline_contracts import (
    AnalyzerRegistryV1,
    AnalyzerRegistryV2,
    BenchmarkRecipeV1,
    ContentIntentV1,
    ContractValidationError,
    CreatorIdentityProfileV1,
    validate_renderer_equivalence_receipt_v2,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "thin_evidence_records.v1.json"


def _fixture(name: str) -> dict:
    records = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return records[name]


@pytest.mark.parametrize(
    ("example_name", "record_type"),
    [
        ("creator_identity_profile", CreatorIdentityProfileV1),
        ("content_intent", ContentIntentV1),
        ("benchmark_recipe", BenchmarkRecipeV1),
        ("analyzer_registry", AnalyzerRegistryV1),
    ],
)
def test_thin_evidence_records_round_trip(example_name: str, record_type: type) -> None:
    payload = _fixture(example_name)

    record = record_type.from_dict(payload)

    assert record.to_dict() == payload


def test_thin_evidence_records_are_frozen() -> None:
    record = CreatorIdentityProfileV1.from_dict(_fixture("creator_identity_profile"))

    with pytest.raises(FrozenInstanceError):
        record.profile_id = "replacement"  # type: ignore[misc]


def test_thin_evidence_record_rejects_unknown_version() -> None:
    payload = _fixture("creator_identity_profile")
    payload["schema"] = "creator_os.creator_identity_profile.v2"

    with pytest.raises(ContractValidationError, match="schema"):
        CreatorIdentityProfileV1.from_dict(payload)


def test_thin_evidence_record_rejects_missing_provenance() -> None:
    payload = _fixture("content_intent")
    del payload["provenance"]

    with pytest.raises(ContractValidationError, match="provenance"):
        ContentIntentV1.from_dict(payload)


def test_production_analyzer_registry_v2_round_trips() -> None:
    path = (
        Path(__file__).parents[1]
        / "pipeline_contracts/schemas/analyzer_registry.v2.example.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert AnalyzerRegistryV2.from_dict(payload).to_dict() == payload


def test_renderer_equivalence_v2_binds_semantics_and_fingerprint() -> None:
    path = (
        Path(__file__).parents[1]
        / "pipeline_contracts/schemas/renderer_equivalence_receipt.v2.example.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_renderer_equivalence_receipt_v2(payload)

    payload["equivalencePolicy"]["minimumSsim"] = 1.0
    unsigned = {
        key: value for key, value in payload.items() if key != "receiptFingerprint"
    }
    payload["receiptFingerprint"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ContractValidationError, match="below declared minimumSsim"):
        validate_renderer_equivalence_receipt_v2(payload)
