"""Re-export of the shared atomic-write / file-lock helpers.

The implementation now lives in ``creator_os_core.fileops`` (deduplicated across
the three factories). This module is kept as a thin re-export so existing
``from .fileops import ...`` sites keep resolving unchanged.
"""

from __future__ import annotations

from creator_os_core.fileops import atomic_write_json, atomic_write_text, file_lock

__all__ = ["atomic_write_json", "atomic_write_text", "file_lock"]
