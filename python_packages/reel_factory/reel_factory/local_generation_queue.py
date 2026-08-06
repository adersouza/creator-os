"""Append-only JSONL journal with fail-closed corruption detection.

Slim remainder of the retired local generation queue: the ContentForge
``structured_human_media_review`` analyzer depends on this journal.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from creator_os_core.fileops import file_lock

JOURNAL_SCHEMA: Final = "reel_factory.local_generation_journal.v1"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def fingerprint(value: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 for a JSON-compatible mapping."""

    return hashlib.sha256(_canonical_json(value)).hexdigest()


class LocalQueueError(RuntimeError):
    """Base class for append-only journal failures."""


class JournalCorruptionError(LocalQueueError):
    """Raised when unacknowledged malformed journal records are present."""


@dataclass(frozen=True)
class JournalIssue:
    line_number: int
    line_sha256: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "lineNumber": self.line_number,
            "lineSha256": self.line_sha256,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class JournalRead:
    events: tuple[dict[str, Any], ...]
    issues: tuple[JournalIssue, ...]


class AppendOnlyJournal:
    """Fsync'd, hash-chained JSONL journal with explicit corruption recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._coordination_path = self.path.with_suffix(
            self.path.suffix + ".coordination"
        )

    def read(self, *, allow_unacknowledged_issues: bool = False) -> JournalRead:
        if not self.path.exists():
            return JournalRead(events=(), issues=())
        events: list[dict[str, Any]] = []
        issues: list[JournalIssue] = []
        acknowledged: set[str] = set()
        previous_hash: str | None = None
        expected_sequence = 1
        with self.path.open("rb") as handle:
            for number, raw_line in enumerate(handle, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                digest = hashlib.sha256(stripped).hexdigest()
                try:
                    event = json.loads(stripped)
                    if not isinstance(event, dict):
                        raise ValueError("event is not a JSON object")
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                    issues.append(
                        JournalIssue(
                            line_number=number,
                            line_sha256=digest,
                            reason=type(exc).__name__,
                        )
                    )
                    continue
                claimed_hash = event.get("eventHash")
                hash_payload = dict(event)
                hash_payload.pop("eventHash", None)
                integrity_error: str | None = None
                if event.get("schema") != JOURNAL_SCHEMA:
                    integrity_error = "unexpected_schema"
                elif event.get("sequence") != expected_sequence:
                    integrity_error = "non_contiguous_sequence"
                elif event.get("previousEventHash") != previous_hash:
                    integrity_error = "previous_event_hash_mismatch"
                elif claimed_hash != fingerprint(hash_payload):
                    integrity_error = "event_hash_mismatch"
                if integrity_error is not None:
                    issues.append(
                        JournalIssue(
                            line_number=number,
                            line_sha256=digest,
                            reason=integrity_error,
                        )
                    )
                    continue
                events.append(event)
                previous_hash = str(claimed_hash)
                expected_sequence += 1
                if event.get("eventType") == "journal_recovery_recorded":
                    recovered = event.get("payload", {}).get(
                        "recoveredIssueDigests", []
                    )
                    if isinstance(recovered, list):
                        acknowledged.update(str(item) for item in recovered)
        unresolved = tuple(
            issue for issue in issues if issue.line_sha256 not in acknowledged
        )
        if unresolved and not allow_unacknowledged_issues:
            raise JournalCorruptionError(
                f"local_generation_journal_corrupt:{len(unresolved)}_unacknowledged_record(s)"
            )
        return JournalRead(events=tuple(events), issues=unresolved)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        allow_unacknowledged_issues: bool = False,
    ) -> dict[str, Any]:
        if not event_type.strip():
            raise ValueError("event_type must be non-empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._coordination_path):
            read = self.read(allow_unacknowledged_issues=allow_unacknowledged_issues)
            previous_hash = (
                str(read.events[-1].get("eventHash")) if read.events else None
            )
            event: dict[str, Any] = {
                "schema": JOURNAL_SCHEMA,
                "sequence": len(read.events) + 1,
                "eventId": str(uuid.uuid4()),
                "eventType": event_type,
                "occurredAt": _utc_now(),
                "previousEventHash": previous_hash,
                "payload": dict(payload),
            }
            event["eventHash"] = fingerprint(event)
            encoded = _canonical_json(event) + b"\n"
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            descriptor = os.open(self.path, flags, 0o600)
            try:
                if os.path.getsize(self.path) > 0:
                    with self.path.open("rb") as check:
                        check.seek(-1, os.SEEK_END)
                        if check.read(1) != b"\n":
                            os.write(descriptor, b"\n")
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise OSError("short append to local generation journal")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def acknowledge_corruption(self) -> dict[str, Any] | None:
        """Preserve malformed records and append an explicit recovery marker."""

        read = self.read(allow_unacknowledged_issues=True)
        if not read.issues:
            return None
        return self.append(
            "journal_recovery_recorded",
            {
                "recoveredIssueDigests": [issue.line_sha256 for issue in read.issues],
                "issues": [issue.as_dict() for issue in read.issues],
                "recoveryPolicy": "preserve_malformed_record_and_skip_during_replay",
            },
            allow_unacknowledged_issues=True,
        )
