from __future__ import annotations

import sys
from pathlib import Path

_PROJECTS_ROOT = Path(__file__).resolve().parents[2]
_SHARED_CONTRACTS_ROOT = _PROJECTS_ROOT / "pipeline_contracts"
if _SHARED_CONTRACTS_ROOT.exists() and str(_SHARED_CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_CONTRACTS_ROOT))

from pipeline_contracts import (  # noqa: E402
    ContractValidationError,
    load_schema,
    schema_path,
    validate_audio_catalog_export,
    validate_audio_intent,
    validate_contract,
    validate_front_generation_plan,
    validate_generated_asset_lineage,
    validate_motion_edit_render,
    validate_performance_sync,
    validate_post_metric_history_read,
    validate_recommendation_accuracy_report,
    validate_recommendation_next_batch,
    validate_schema_examples,
    validate_threadsdash_draft_payload,
    validate_threadsdash_draft_payload_strict,
    validate_variant_assignment,
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
    "validate_front_generation_plan",
    "validate_generated_asset_lineage",
    "validate_motion_edit_render",
    "validate_post_metric_history_read",
    "validate_performance_sync",
    "validate_recommendation_accuracy_report",
    "validate_recommendation_next_batch",
    "validate_schema_examples",
    "validate_threadsdash_draft_payload",
    "validate_threadsdash_draft_payload_strict",
    "validate_variant_assignment",
]
