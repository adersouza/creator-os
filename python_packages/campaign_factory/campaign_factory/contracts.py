from __future__ import annotations

import sys
from pathlib import Path


_PROJECTS_ROOT = Path(__file__).resolve().parents[2]
_MONOREPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT_ROOT_CANDIDATES = [
    _PROJECTS_ROOT / "pipeline_contracts",
    _MONOREPO_ROOT / "packages" / "pipeline_contracts",
]
_SHARED_CONTRACTS_ROOT = next(
    (candidate for candidate in _CONTRACT_ROOT_CANDIDATES if candidate.exists()),
    _CONTRACT_ROOT_CANDIDATES[0],
)
if _SHARED_CONTRACTS_ROOT.exists() and str(_SHARED_CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_CONTRACTS_ROOT))

from pipeline_contracts import (  # noqa: E402
    ContractValidationError,
    load_schema,
    schema_path,
    validate_audio_catalog_export,
    validate_audio_intent,
    validate_contract,
    validate_performance_sync,
    validate_recommendation_accuracy_report,
    validate_recommendation_next_batch,
    validate_schema_examples,
    validate_threadsdash_draft_payload,
    validate_threadsdash_draft_payload_strict,
)


SCHEMA_DIR = _SHARED_CONTRACTS_ROOT / "schemas"

__all__ = [
    "ContractValidationError",
    "SCHEMA_DIR",
    "load_schema",
    "schema_path",
    "validate_audio_catalog_export",
    "validate_audio_intent",
    "validate_contract",
    "validate_performance_sync",
    "validate_recommendation_accuracy_report",
    "validate_recommendation_next_batch",
    "validate_schema_examples",
    "validate_threadsdash_draft_payload",
    "validate_threadsdash_draft_payload_strict",
]
