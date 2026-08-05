"""Hostname-free hardware identity for capacity and benchmark evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
from collections.abc import Mapping
from typing import Any, Final

HARDWARE_SCHEMA: Final = "reel_factory.local_hardware_fingerprint.v1"


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def fingerprint(value: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 for a JSON-compatible mapping."""

    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _physical_memory_bytes() -> int | None:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, TypeError, ValueError):
        return None
    total = pages * page_size
    return total if total > 0 else None


def hardware_identity() -> dict[str, Any]:
    """Describe and fingerprint hardware without exposing the hostname."""

    payload: dict[str, Any] = {
        "schema": HARDWARE_SCHEMA,
        "machine": platform.machine() or "unknown",
        "processor": platform.processor() or "unknown",
        "system": platform.system() or "unknown",
        "release": platform.release() or "unknown",
        "physicalMemoryBytes": _physical_memory_bytes(),
        "hostFingerprint": hashlib.sha256(socket.gethostname().encode()).hexdigest(),
    }
    payload["fingerprint"] = fingerprint(payload)
    return payload
