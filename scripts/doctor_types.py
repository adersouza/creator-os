"""Shared result types for Creator OS doctor checks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Result:
    name: str
    category: str
    status: str
    reason: str
    command: str
    evidence: str = ""
    affected: list[str] = field(default_factory=list)
    next_action: str = "None."
    duration_ms: int = 0
