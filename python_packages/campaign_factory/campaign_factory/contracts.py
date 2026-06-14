from __future__ import annotations

import sys
import os
from pathlib import Path


def _contract_root_candidates() -> list[Path]:
    current = Path(__file__).resolve()
    candidates: list[Path] = []
    env_root = os.environ.get("PIPELINE_CONTRACTS_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    for ancestor in current.parents:
        candidates.append(ancestor / "packages" / "pipeline_contracts")
    for ancestor in current.parents:
        candidates.append(ancestor / "pipeline_contracts")
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


_CONTRACT_ROOT_CANDIDATES = _contract_root_candidates()
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


SCHEMA_DIR = schema_path("audio_intent").parent

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
