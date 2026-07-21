"""Normalize provider model identifiers across response schema versions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODEL_IDENTIFIER_KEYS = ("job_type", "job_set_type", "id", "model_id")


def model_identifiers(row: Mapping[str, Any]) -> frozenset[str]:
    """Return normalized model IDs from current and legacy provider rows."""
    identifiers: set[str] = set()
    for key in MODEL_IDENTIFIER_KEYS:
        value = row.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if normalized:
            identifiers.add(normalized)
    return frozenset(identifiers)
