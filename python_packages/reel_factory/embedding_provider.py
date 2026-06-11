"""Local embedding providers for hook similarity.

The sentence-transformers backend is optional. If it is not installed or the
model cannot be loaded, callers can fall back to the deterministic hash model.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol


DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
HASH_MODEL = "hash-v1"


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> list[float]:
        ...


ALIASES = {
    "u": "you",
    "ur": "your",
    "ya": "you",
    "bc": "because",
    "cuz": "because",
    "ppl": "people",
    "gonna": "going",
    "wanna": "want",
    "tho": "though",
}


def normalize_for_embedding(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s']+", " ", text)
    tokens = [ALIASES.get(tok, tok) for tok in re.findall(r"[a-z0-9']+", text)]
    return " ".join(tokens)


@dataclass
class HashEmbeddingProvider:
    name: str = HASH_MODEL
    dims: int = 64

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in normalize_for_embedding(text).split():
            h = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(h[:2], "big") % self.dims
            sign = 1.0 if h[2] % 2 == 0 else -1.0
            vec[idx] += sign
        return normalize_vector(vec)


class SentenceTransformersProvider:
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model_name = model_name
        self.name = f"sentence-transformers/{model_name}"
        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return [float(v) for v in vec]


@lru_cache(maxsize=4)
def _cached_sentence_provider(model_name: str) -> SentenceTransformersProvider:
    return SentenceTransformersProvider(model_name)


def normalize_vector(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def get_embedding_provider(model: str | None = None,
                           *, allow_fallback: bool = True) -> EmbeddingProvider:
    if not model or model == HASH_MODEL:
        return HashEmbeddingProvider()
    if model in {DEFAULT_EMBEDDING_MODEL, f"sentence-transformers/{DEFAULT_EMBEDDING_MODEL}"}:
        try:
            return _cached_sentence_provider(DEFAULT_EMBEDDING_MODEL)
        except Exception:
            if allow_fallback:
                return HashEmbeddingProvider()
            raise
    if model.startswith("sentence-transformers/"):
        try:
            return _cached_sentence_provider(model.split("/", 1)[1])
        except Exception:
            if allow_fallback:
                return HashEmbeddingProvider()
            raise
    return HashEmbeddingProvider()
