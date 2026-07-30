"""Canonical ContentForge analyzer-registry verification."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_analyzer_registry

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
    """Require current v2 production authority from exact implementations."""

    supplied = dict(registry)
    if (
        supplied.get("schema") != "creator_os.analyzer_registry.v2"
        or supplied.get("authorityVersion") != 2
    ):
        raise CanonicalAnalyzerRegistryError(
            "analyzer_registry_production_authority_v2_required"
        )
    return _validate_exact_registry(
        supplied,
        authority_version=2,
        contentforge_root=contentforge_root,
    )


def validate_historical_analyzer_registry(
    registry: Mapping[str, Any],
    *,
    contentforge_root: Path | None = None,
) -> dict[str, Any]:
    """Validate retained structure without claiming current implementation authority."""

    supplied = dict(registry)
    schema = supplied.get("schema")
    if schema not in {
        "creator_os.analyzer_registry.v1",
        "creator_os.analyzer_registry.v2",
    }:
        raise CanonicalAnalyzerRegistryError("analyzer_registry_schema_unsupported")
    del contentforge_root
    try:
        validate_analyzer_registry(supplied)
    except Exception as exc:
        raise CanonicalAnalyzerRegistryError(
            f"historical_analyzer_registry_structure_invalid:{exc}"
        ) from exc
    return {
        "registry": supplied,
        "verificationScope": "historical_structure_only",
        "productionAuthority": False,
        "currentImplementationCompatibility": "not_verified",
    }


def _validate_exact_registry(
    supplied: dict[str, Any],
    *,
    authority_version: int,
    contentforge_root: Path | None,
) -> dict[str, Any]:
    provenance = supplied.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    produced_at = str(provenance.get("producedAt") or "").strip()
    if not produced_at:
        raise CanonicalAnalyzerRegistryError("analyzer_registry_produced_at_missing")
    try:
        canonical = run_contentforge(
            contentforge_root or _default_contentforge_root(),
            "analyzer-registry",
            {
                "producedAt": produced_at,
                "authorityVersion": authority_version,
            },
            timeout=30,
        )
    except RuntimeError as exc:
        raise CanonicalAnalyzerRegistryError(
            f"canonical_analyzer_registry_unavailable:{exc}"
        ) from exc
    if supplied != canonical:
        raise CanonicalAnalyzerRegistryError("analyzer_registry_not_canonical")
    return canonical
