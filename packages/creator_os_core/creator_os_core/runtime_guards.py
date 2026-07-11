from __future__ import annotations

import os

GLOBAL_KILL_SWITCH_ENV = "CREATOR_OS_KILL_SWITCH"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def global_kill_switch_active() -> bool:
    """Return whether the canonical Creator OS emergency stop is active."""
    return os.environ.get(GLOBAL_KILL_SWITCH_ENV, "").strip().lower() in _TRUTHY


def require_global_write_allowed(operation: str) -> None:
    """Fail closed before paid or outbound state-changing operations."""
    if global_kill_switch_active():
        raise PermissionError(
            f"{operation} blocked: {GLOBAL_KILL_SWITCH_ENV} is active"
        )
