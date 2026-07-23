"""Canonical ContentForge analyzer-registry verification."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contentforge_cli import run_contentforge


class CanonicalAnalyzerRegistryError(RuntimeError):
    """The supplied registry is unavailable or not ContentForge canonical."""


def _default_contentforge_root() -> Path:
    return Path(__file__).resolve().parents[3] / "packages" / "contentforge"


def validate_canonical_analyzer_registry(
    registry: Mapping[str, Any],
    *,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Require the exact registry emitted from current trusted implementations."""

    supplied = dict(registry)
    provenance = supplied.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    produced_at = str(provenance.get("producedAt") or "").strip()
    if not produced_at:
        raise CanonicalAnalyzerRegistryError("analyzer_registry_produced_at_missing")
    try:
        canonical = run_contentforge(
            contentforge_root or _default_contentforge_root(),
            "analyzer-registry",
            {"producedAt": produced_at},
            timeout=30,
        )
    except RuntimeError as exc:
        raise CanonicalAnalyzerRegistryError(
            f"canonical_analyzer_registry_unavailable:{exc}"
        ) from exc
    if supplied != canonical:
        raise CanonicalAnalyzerRegistryError("analyzer_registry_not_canonical")
    return canonical
