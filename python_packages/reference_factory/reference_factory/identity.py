from __future__ import annotations

import hashlib
from pathlib import Path


def stable_reference_id(path: Path, size_bytes: int) -> str:
    digest = hashlib.sha1(f"{path.resolve()}|{size_bytes}".encode("utf-8")).hexdigest()
    return "ref_" + digest[:16]


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def content_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def text_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

