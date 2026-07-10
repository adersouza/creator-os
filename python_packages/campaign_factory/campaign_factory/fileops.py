"""Locking and atomic-write helpers for campaign_factory.

Writers across the package (report/audit/summary emitters, scripts) previously
used bare ``Path.write_text``. A crash mid-write leaves a truncated file, and
concurrent writers (cron + interactive runs) can interleave. These helpers
provide:

- ``atomic_write_text`` / ``atomic_write_json``: write to a temp file in the
  same directory, fsync, then ``os.replace`` so readers only ever observe the
  old or the new complete contents.
- ``file_lock``: advisory inter-process lock (``fcntl.flock``) keyed on a
  sidecar ``.lock`` file, for serializing multi-file write sequences.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

__all__ = ["atomic_write_json", "atomic_write_text", "file_lock"]


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically replace ``path`` with ``text`` (temp file + ``os.replace``)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    encoding: str = "utf-8",
) -> None:
    """Atomically write ``payload`` as JSON (trailing newline included)."""
    text = json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=sort_keys)
    atomic_write_text(path, text + "\n", encoding=encoding)


@contextmanager
def file_lock(path: Path | str, *, blocking: bool = True) -> Iterator[Path]:
    """Advisory exclusive lock on ``<path>.lock``; yields the locked path.

    Raises ``BlockingIOError`` when ``blocking=False`` and the lock is held.
    """
    target = Path(path)
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    with open(lock_path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), flags)
        try:
            yield target
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
