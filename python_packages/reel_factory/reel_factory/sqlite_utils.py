"""Re-export of the shared SQLite opener.

The implementation now lives in ``creator_os_core.sqlite`` (deduplicated across
the three factories). This module is kept as a thin re-export so existing
``from reel_factory.sqlite_utils import connect_sqlite`` sites and the top-level
compat shim keep resolving to the same function object.
"""

from __future__ import annotations

from creator_os_core.sqlite import connect_sqlite

__all__ = ["connect_sqlite"]
