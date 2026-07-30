from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from creator_os_core.configuration_registry import (
    validate_operation_configuration,
)

GLOBAL_KILL_SWITCH_ENV = "CREATOR_OS_KILL_SWITCH"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def global_kill_switch_active(
    environ: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether the canonical Creator OS emergency stop is active."""
    values = os.environ if environ is None else environ
    return str(values.get(GLOBAL_KILL_SWITCH_ENV) or "").strip().lower() in _TRUTHY


def require_global_write_allowed(
    operation: str,
    *,
    environ: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed before paid or outbound state-changing operations."""
    values = os.environ if environ is None else environ
    if global_kill_switch_active(values):
        raise PermissionError(
            f"{operation} blocked: {GLOBAL_KILL_SWITCH_ENV} is active"
        )
    try:
        validate_operation_configuration("state_change", values=values)
    except PermissionError as exc:
        raise PermissionError(f"{operation} blocked: {exc}") from exc
