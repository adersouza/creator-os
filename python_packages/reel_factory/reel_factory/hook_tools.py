"""Hook normalization, fuzzy duplicate detection, and local hook library."""

from __future__ import annotations

import hashlib
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from embedding_provider import (
    HASH_MODEL,
    cosine_similarity,
    get_embedding_provider,
)
from .fileops import atomic_write_text

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover - fallback for minimal envs
    fuzz = None

FUZZY_DUPLICATE_THRESHOLD = 92
SEMANTIC_DUPLICATE_THRESHOLD = 0.82


def hook_text(hook: str | dict[str, Any]) -> str:
    if isinstance(hook, dict):
        segments = hook.get("segments")
        if isinstance(segments, list):
            return " ".join(
                str(seg.get("text", "")) for seg in segments if isinstance(seg, dict)
            )
        return json.dumps(hook, sort_keys=True, ensure_ascii=False)
    return str(hook)


def normalize_hook_text(hook: str | dict[str, Any]) -> str:
    text = hook_text(hook).lower()
    text = re.sub(r"[^a-z0-9\s']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str | dict[str, Any], b: str | dict[str, Any]) -> float:
    left = normalize_hook_text(a)
    right = normalize_hook_text(b)
    if not left or not right:
        return 0.0
    if fuzz is not None:
        return float(fuzz.token_set_ratio(left, right))
    return SequenceMatcher(None, left, right).ratio() * 100.0


def find_near_duplicates(
    hooks: list[str | dict[str, Any]],
    threshold: int = FUZZY_DUPLICATE_THRESHOLD,
) -> list[dict[str, int | float]]:
    out: list[dict[str, int | float]] = []
    for i in range(len(hooks)):
        for j in range(i + 1, len(hooks)):
            score = similarity(hooks[i], hooks[j])
            if score >= threshold:
                out.append({"first": i, "duplicate": j, "score": round(score, 1)})
    return out


def semantic_vector(
    text: str | dict[str, Any], embedding_model: str | None = HASH_MODEL
) -> list[float]:
    provider = get_embedding_provider(embedding_model)
    return provider.embed(normalize_hook_text(text))


def find_semantic_duplicates(
    hooks: list[str | dict[str, Any]],
    threshold: float = SEMANTIC_DUPLICATE_THRESHOLD,
    embedding_model: str | None = HASH_MODEL,
) -> list[dict[str, int | float]]:
    provider = get_embedding_provider(embedding_model)
    vectors = [provider.embed(normalize_hook_text(hook)) for hook in hooks]
    out: list[dict[str, int | float]] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = cosine_similarity(vectors[i], vectors[j])
            if score >= threshold:
                out.append({"first": i, "duplicate": j, "score": round(score, 3)})
    return out


def semantic_group_for(
    library: list[dict[str, Any]],
    hook: str | dict[str, Any],
    threshold: float = SEMANTIC_DUPLICATE_THRESHOLD,
    embedding_model: str | None = HASH_MODEL,
) -> str:
    provider = get_embedding_provider(embedding_model)
    vector = provider.embed(normalize_hook_text(hook))
    for item in library:
        group = item.get("semantic_group")
        if not group:
            continue
        score = cosine_similarity(
            vector,
            provider.embed(normalize_hook_text(item.get("hook", item.get("text", "")))),
        )
        if score >= threshold:
            return str(group)
    normalized = normalize_hook_text(hook)
    return "sem_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]


def embedding_status(embedding_model: str | None = None) -> dict[str, str | bool]:
    provider = get_embedding_provider(embedding_model)
    return {
        "model": provider.name,
        "real_embeddings": provider.name != HASH_MODEL,
    }


def read_hook_library(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_hook_to_library(
    path: Path,
    hook: str | dict[str, Any],
    tags: list[str] | None = None,
    embedding_model: str | None = HASH_MODEL,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    library = read_hook_library(path)
    normalized = normalize_hook_text(hook)
    now = int(time.time())
    for item in library:
        if item.get("normalized_text") == normalized:
            item["last_used_at"] = now
            item["use_count"] = int(item.get("use_count", 0)) + 1
            item.setdefault(
                "semantic_group",
                semantic_group_for(library, hook, embedding_model=embedding_model),
            )
            item["embedding_model"] = get_embedding_provider(embedding_model).name
            item["embedding_dims"] = len(semantic_vector(hook, embedding_model))
            atomic_write_text(path, 
                json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return item
    provider = get_embedding_provider(embedding_model)
    semantic_group = semantic_group_for(library, hook, embedding_model=embedding_model)
    item = {
        "id": f"hook_{now}_{len(library) + 1}",
        "hook": hook,
        "text": hook_text(hook),
        "normalized_text": normalized,
        "semantic_group": semantic_group,
        "embedding_model": provider.name,
        "embedding_dims": len(provider.embed(normalized)),
        "tags": tags or [],
        "created_at": now,
        "last_used_at": now,
        "use_count": 1,
    }
    library.append(item)
    atomic_write_text(path, json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8")
    return item


def reindex_hook_library(
    path: Path,
    *,
    embedding_model: str | None = None,
    threshold: float = SEMANTIC_DUPLICATE_THRESHOLD,
) -> dict[str, Any]:
    library = read_hook_library(path)
    provider = get_embedding_provider(embedding_model)
    groups: list[tuple[str, list[float]]] = []
    for idx, item in enumerate(library):
        text = item.get("hook", item.get("text", ""))
        vec = provider.embed(normalize_hook_text(text))
        group = None
        for group_id, group_vec in groups:
            if cosine_similarity(vec, group_vec) >= threshold:
                group = group_id
                break
        if group is None:
            normalized = item.get("normalized_text") or normalize_hook_text(text)
            group = (
                "sem_"
                + hashlib.sha256(str(normalized).encode("utf-8")).hexdigest()[:10]
            )
            groups.append((group, vec))
        item["semantic_group"] = group
        item["embedding_model"] = provider.name
        item["embedding_dims"] = len(vec)
        item["reindexed_at"] = int(time.time())
        library[idx] = item
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "count": len(library),
        "groups": len({item.get("semantic_group") for item in library}),
        "embedding_model": provider.name,
        "real_embeddings": provider.name != HASH_MODEL,
    }
