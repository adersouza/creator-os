"""Shared prompt-definition governance and compilation receipts.

Prompt text remains owned by the factory that uses it.  This module provides
the small, dependency-free registry contract shared by Campaign, Reference,
and Reel Factory so production prompts cannot change without changing an
approved, fingerprinted definition.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROMPT_DEFINITION_SCHEMA = "creator_os.prompt_definition.v1"
PROMPT_RECEIPT_SCHEMA = "creator_os.prompt_governance_receipt.v1"
PROMPT_REGISTRY_SCHEMA = "creator_os.prompt_registry.v1"
PROMPT_MATERIAL_SCHEMA = "creator_os.prompt_governed_material.v1"
PROMPT_SOURCE_SCHEMA = "creator_os.prompt_source_material.v1"
PROMPT_REGRESSION_FIXTURE_SCHEMA = "creator_os.prompt_regression_fixture.v1"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def python_source_fingerprint(
    path: str | Path,
    *,
    source_id: str,
    symbols: Iterable[str],
) -> str:
    """Fingerprint exact Python definitions without importing their module."""

    source_path = Path(path).expanduser()
    if source_path.is_symlink():
        raise ValueError("prompt_source_file_invalid")
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise ValueError("prompt_source_file_invalid")
    source = source_path.read_text(encoding="utf-8")
    requested = tuple(
        dict.fromkeys(_required(symbol, "source_symbol") for symbol in symbols)
    )
    if not requested:
        raise ValueError("prompt_source_symbols_missing")
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        raise ValueError("prompt_source_parse_invalid") from exc
    located: dict[str, str] = {}
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [target.id for target in targets if isinstance(target, ast.Name)]
        for name in names:
            if name not in requested:
                continue
            if node.end_lineno is None:
                raise ValueError("prompt_source_location_invalid")
            located[name] = "".join(lines[node.lineno - 1 : node.end_lineno])
    missing = sorted(set(requested) - set(located))
    if missing:
        raise ValueError("prompt_source_symbols_missing:" + ",".join(missing))
    return fingerprint(
        {
            "schema": PROMPT_SOURCE_SCHEMA,
            "sourceId": _required(source_id, "source_id"),
            "symbols": [
                {"name": symbol, "source": located[symbol]} for symbol in requested
            ],
        }
    )


def regression_fixture_hash(
    *,
    fixture_id: str,
    inputs: Any,
    compiled_prompt: Any,
) -> str:
    """Hash one real compiler input/output regression fixture."""

    return fingerprint(
        {
            "schema": PROMPT_REGRESSION_FIXTURE_SCHEMA,
            "fixtureId": _required(fixture_id, "fixture_id"),
            "inputs": inputs,
            "compiledPrompt": compiled_prompt,
        }
    )


def governed_material_fingerprint(
    *,
    prompt_id: str,
    version: str,
    owner: str,
    purpose: str,
    provider: str,
    models: Iterable[str],
    template_version: str,
    builder_fingerprint: str,
    compiler_source_fingerprint: str,
    template_source_fingerprint: str,
    input_contract: str,
    output_contract: str,
    compatibility: str,
    cost_behavior: str,
    regression_fixtures: Iterable[str],
) -> str:
    """Fingerprint every approved field that can change prompt behavior."""

    material = {
        "schema": PROMPT_MATERIAL_SCHEMA,
        "promptId": _required(prompt_id, "prompt_id"),
        "version": _required(version, "version"),
        "owner": _required(owner, "owner"),
        "purpose": _required(purpose, "purpose"),
        "provider": _required(provider, "provider"),
        "models": sorted({_required(value, "model") for value in models}),
        "templateVersion": _required(template_version, "template_version"),
        "builderFingerprint": _sha(builder_fingerprint, "builder_fingerprint"),
        "compilerSourceFingerprint": _sha(
            compiler_source_fingerprint, "compiler_source_fingerprint"
        ),
        "templateSourceFingerprint": _sha(
            template_source_fingerprint, "template_source_fingerprint"
        ),
        "inputContract": _required(input_contract, "input_contract"),
        "outputContract": _required(output_contract, "output_contract"),
        "compatibility": _required(compatibility, "compatibility"),
        "costBehavior": _required(cost_behavior, "cost_behavior"),
        "regressionFixtures": sorted(
            {_sha(value, "regression_fixture") for value in regression_fixtures}
        ),
    }
    return fingerprint(material)


def prompt_definition(
    *,
    prompt_id: str,
    version: str,
    owner: str,
    purpose: str,
    provider: str,
    models: Iterable[str],
    template_version: str,
    builder_fingerprint: str,
    compiler_source_fingerprint: str,
    template_source_fingerprint: str,
    input_contract: str,
    output_contract: str,
    approval: Mapping[str, Any],
    effective_at: str,
    retirement_at: str | None = None,
    compatibility: str = "production",
    cost_behavior: str = "provider_call",
    regression_fixtures: Iterable[str] = (),
) -> dict[str, Any]:
    """Build and validate one immutable prompt definition."""

    core = {
        "schema": PROMPT_DEFINITION_SCHEMA,
        "promptId": _required(prompt_id, "prompt_id"),
        "version": _required(version, "version"),
        "owner": _required(owner, "owner"),
        "purpose": _required(purpose, "purpose"),
        "provider": _required(provider, "provider"),
        "models": sorted({_required(value, "model") for value in models}),
        "templateVersion": _required(template_version, "template_version"),
        "builderFingerprint": _sha(builder_fingerprint, "builder_fingerprint"),
        "compilerSourceFingerprint": _sha(
            compiler_source_fingerprint, "compiler_source_fingerprint"
        ),
        "templateSourceFingerprint": _sha(
            template_source_fingerprint, "template_source_fingerprint"
        ),
        "inputContract": _required(input_contract, "input_contract"),
        "outputContract": _required(output_contract, "output_contract"),
        "approval": dict(approval),
        "effectiveAt": _timestamp(effective_at, "effective_at"),
        "retirementAt": (
            _timestamp(retirement_at, "retirement_at") if retirement_at else None
        ),
        "compatibility": _required(compatibility, "compatibility"),
        "costBehavior": _required(cost_behavior, "cost_behavior"),
        "regressionFixtures": sorted(
            {_sha(value, "regression_fixture") for value in regression_fixtures}
        ),
    }
    material_fingerprint = governed_material_fingerprint(
        prompt_id=core["promptId"],
        version=core["version"],
        owner=core["owner"],
        purpose=core["purpose"],
        provider=core["provider"],
        models=core["models"],
        template_version=core["templateVersion"],
        builder_fingerprint=core["builderFingerprint"],
        compiler_source_fingerprint=core["compilerSourceFingerprint"],
        template_source_fingerprint=core["templateSourceFingerprint"],
        input_contract=core["inputContract"],
        output_contract=core["outputContract"],
        compatibility=core["compatibility"],
        cost_behavior=core["costBehavior"],
        regression_fixtures=core["regressionFixtures"],
    )
    if core["approval"].get("materialFingerprint") != material_fingerprint:
        raise PermissionError("prompt_approval_material_mismatch")
    core["governedMaterialFingerprint"] = material_fingerprint
    value = {**core, "definitionFingerprint": fingerprint(core)}
    return validate_prompt_definition(value)


def validate_prompt_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a definition and its explicit production approval."""

    item = dict(value)
    definition_fingerprint = item.pop("definitionFingerprint", None)
    if item.get("schema") != PROMPT_DEFINITION_SCHEMA:
        raise ValueError("prompt_definition_schema_invalid")
    if definition_fingerprint != fingerprint(item):
        raise ValueError("prompt_definition_fingerprint_invalid")
    for key in (
        "promptId",
        "version",
        "owner",
        "purpose",
        "provider",
        "templateVersion",
        "inputContract",
        "outputContract",
        "compatibility",
        "costBehavior",
        "governedMaterialFingerprint",
    ):
        _required(item.get(key), key)
    _sha(item.get("builderFingerprint"), "builderFingerprint")
    _sha(item.get("compilerSourceFingerprint"), "compilerSourceFingerprint")
    _sha(item.get("templateSourceFingerprint"), "templateSourceFingerprint")
    models = item.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("prompt_definition_models_missing")
    for model in models:
        _required(model, "model")
    fixtures = item.get("regressionFixtures")
    if not isinstance(fixtures, list):
        raise ValueError("prompt_definition_regression_fixtures_invalid")
    for fixture in fixtures:
        _sha(fixture, "regressionFixture")
    effective = _parse_timestamp(item.get("effectiveAt"), "effectiveAt")
    retirement = (
        _parse_timestamp(item["retirementAt"], "retirementAt")
        if item.get("retirementAt")
        else None
    )
    if retirement is not None and retirement <= effective:
        raise ValueError("prompt_definition_retirement_invalid")
    approval = item.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("prompt_definition_approval_missing")
    if approval.get("state") != "approved":
        raise PermissionError("production_prompt_not_approved")
    _required(approval.get("approvedBy"), "approvedBy")
    approved_at = _parse_timestamp(approval.get("approvedAt"), "approvedAt")
    if approved_at > effective:
        raise ValueError("prompt_definition_approval_after_effective_date")
    material_fingerprint = governed_material_fingerprint(
        prompt_id=item["promptId"],
        version=item["version"],
        owner=item["owner"],
        purpose=item["purpose"],
        provider=item["provider"],
        models=item["models"],
        template_version=item["templateVersion"],
        builder_fingerprint=item["builderFingerprint"],
        compiler_source_fingerprint=item["compilerSourceFingerprint"],
        template_source_fingerprint=item["templateSourceFingerprint"],
        input_contract=item["inputContract"],
        output_contract=item["outputContract"],
        compatibility=item["compatibility"],
        cost_behavior=item["costBehavior"],
        regression_fixtures=item["regressionFixtures"],
    )
    if (
        item.get("governedMaterialFingerprint") != material_fingerprint
        or approval.get("materialFingerprint") != material_fingerprint
    ):
        raise PermissionError("prompt_approval_material_mismatch")
    return dict(value)


def prompt_registry(definitions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic registry and reject duplicate prompt versions."""

    entries = [validate_prompt_definition(value) for value in definitions]
    entries.sort(key=lambda value: (value["promptId"], value["version"]))
    identities = [(value["promptId"], value["version"]) for value in entries]
    if len(identities) != len(set(identities)):
        raise ValueError("prompt_registry_duplicate_version")
    core = {
        "schema": PROMPT_REGISTRY_SCHEMA,
        "definitions": entries,
    }
    return {**core, "registryFingerprint": fingerprint(core)}


def resolve_prompt(
    registry: Mapping[str, Any],
    *,
    prompt_id: str,
    version: str,
    provider: str,
    model: str,
    at: datetime | None = None,
    allow_compatibility: bool = False,
) -> dict[str, Any]:
    """Resolve one approved prompt version for an exact provider/model."""

    _validate_registry(registry)
    matches = [
        dict(value)
        for value in registry["definitions"]
        if value["promptId"] == prompt_id and value["version"] == version
    ]
    if len(matches) != 1:
        raise LookupError("prompt_definition_not_found")
    item = matches[0]
    current = (at or datetime.now(UTC)).astimezone(UTC)
    if current < _parse_timestamp(item["effectiveAt"], "effectiveAt"):
        raise PermissionError("prompt_definition_not_effective")
    retirement = item.get("retirementAt")
    if retirement and current >= _parse_timestamp(retirement, "retirementAt"):
        raise PermissionError("prompt_definition_retired")
    if item["provider"] not in {"any", provider}:
        raise PermissionError("prompt_definition_provider_mismatch")
    if "*" not in item["models"] and model not in item["models"]:
        raise PermissionError("prompt_definition_model_mismatch")
    if item["compatibility"] != "production" and not allow_compatibility:
        raise PermissionError("compatibility_prompt_requires_explicit_opt_in")
    return item


def bind_prompt_receipt(
    registry: Mapping[str, Any],
    *,
    prompt_id: str,
    version: str,
    provider: str,
    model: str,
    compiled_prompt: Any,
    input_fingerprint: str,
    at: datetime | None = None,
    allow_compatibility: bool = False,
) -> dict[str, Any]:
    """Bind compiled prompt bytes and inputs to the approved registry version."""

    definition = resolve_prompt(
        registry,
        prompt_id=prompt_id,
        version=version,
        provider=provider,
        model=model,
        at=at,
        allow_compatibility=allow_compatibility,
    )
    core = {
        "schema": PROMPT_RECEIPT_SCHEMA,
        "promptId": definition["promptId"],
        "version": definition["version"],
        "definitionFingerprint": definition["definitionFingerprint"],
        "registryFingerprint": registry["registryFingerprint"],
        "owner": definition["owner"],
        "provider": provider,
        "model": model,
        "templateVersion": definition["templateVersion"],
        "compilerSourceFingerprint": definition["compilerSourceFingerprint"],
        "templateSourceFingerprint": definition["templateSourceFingerprint"],
        "governedMaterialFingerprint": definition["governedMaterialFingerprint"],
        "regressionFixtures": definition["regressionFixtures"],
        "inputFingerprint": _sha(input_fingerprint, "input_fingerprint"),
        "compiledPromptFingerprint": fingerprint(compiled_prompt),
        "costBehavior": definition["costBehavior"],
        "compatibility": definition["compatibility"],
    }
    return {**core, "receiptFingerprint": fingerprint(core)}


def verify_prompt_receipt(
    registry: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    provider: str,
    model: str,
    compiled_prompt: Any,
    inputs: Any,
    at: datetime | None = None,
    allow_compatibility: bool = False,
) -> dict[str, Any]:
    """Revalidate a receipt against current registry and exact runtime material."""

    item = dict(receipt)
    receipt_fingerprint = item.pop("receiptFingerprint", None)
    if item.get("schema") != PROMPT_RECEIPT_SCHEMA:
        raise ValueError("prompt_receipt_schema_invalid")
    if receipt_fingerprint != fingerprint(item):
        raise ValueError("prompt_receipt_fingerprint_invalid")
    expected = bind_prompt_receipt(
        registry,
        prompt_id=_required(item.get("promptId"), "promptId"),
        version=_required(item.get("version"), "version"),
        provider=provider,
        model=model,
        compiled_prompt=compiled_prompt,
        input_fingerprint=fingerprint(inputs),
        at=at,
        allow_compatibility=allow_compatibility,
    )
    if dict(receipt) != expected:
        raise PermissionError("prompt_receipt_stale_or_material_mismatch")
    return expected


def _validate_registry(value: Mapping[str, Any]) -> None:
    core = {
        "schema": value.get("schema"),
        "definitions": value.get("definitions"),
    }
    if (
        core["schema"] != PROMPT_REGISTRY_SCHEMA
        or not isinstance(core["definitions"], list)
        or value.get("registryFingerprint") != fingerprint(core)
    ):
        raise ValueError("prompt_registry_invalid")
    for definition in core["definitions"]:
        if not isinstance(definition, dict):
            raise ValueError("prompt_registry_definition_invalid")
        validate_prompt_definition(definition)


def _required(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}_missing")
    return value.strip()


def _sha(value: Any, label: str) -> str:
    text = _required(value, label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{label}_invalid")
    return text


def _timestamp(value: str, label: str) -> str:
    return _parse_timestamp(value, label).isoformat()


def _parse_timestamp(value: Any, label: str) -> datetime:
    text = _required(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label}_timezone_missing")
    return parsed.astimezone(UTC)
