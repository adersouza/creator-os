"""Small dependency-free vector helpers shared across the factories."""

from __future__ import annotations

import math


def normalize_vector(vec: list[float]) -> list[float]:
    """Return the L2-normalized vector; a zero vector is returned unchanged."""
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot product of two (assumed-normalized) vectors; 0.0 on length mismatch."""
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))
