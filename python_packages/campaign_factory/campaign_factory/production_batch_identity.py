"""Deterministic identity helpers for independent production jobs."""

from __future__ import annotations

import hashlib


def deterministic_seed(
    *, creator: str, intent: str, index: int, source_sha256: str, used: set[int]
) -> int:
    nonce = 0
    while True:
        material = f"{creator}:{intent}:{index}:{source_sha256}:{nonce}".encode()
        seed = int(hashlib.sha256(material).hexdigest()[:8], 16) % 2_147_483_648
        if seed not in used:
            return seed
        nonce += 1
