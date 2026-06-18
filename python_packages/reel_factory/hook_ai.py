#!/usr/bin/env python3
"""Optional local AI hook rewriting.

Ollama is the first provider. The module keeps a tiny provider seam so a
future llama.cpp or MLX backend can plug in without changing the GUI or tests.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from caption_generation_log import (
    append_generation_log,
    build_generation_record,
    caption_library,
    new_generation_id,
    rank_clip_sidecar,
    score_caption_quality,
)
from embedding_provider import DEFAULT_EMBEDDING_MODEL, HASH_MODEL, cosine_similarity, get_embedding_provider


class HookProvider(Protocol):
    def available(self) -> tuple[bool, str]:
        ...

    def rewrite(self, base: str, *, n: int, min_chars: int,
                max_chars: int, seed: int = 42) -> list[str]:
        ...


@dataclass
class OllamaHookProvider:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout: float = 45.0

    def available(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2.0) as res:
                data = json.loads(res.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            return False, f"Ollama is not reachable: {e}"
        models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
        if not models:
            return False, "Ollama is running but no models are installed."
        if self.model and not any(name == self.model or name.startswith(f"{self.model}:") for name in models):
            return False, f"Ollama model '{self.model}' is not installed. Available: {', '.join(models[:5])}"
        return True, "ok"

    def rewrite(self, base: str, *, n: int, min_chars: int,
                max_chars: int, seed: int = 42) -> list[str]:
        prompt = _rewrite_prompt(base, n=n, min_chars=min_chars, max_chars=max_chars)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2, "seed": seed},
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                data = json.loads(res.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e
        raw = data.get("response", "")
        hooks = parse_hook_response(raw)
        return hooks[:n]


def _rewrite_prompt(base: str, *, n: int, min_chars: int, max_chars: int) -> str:
    return f"""Rewrite this short-form reel hook into {n} variants.

Rules:
- Preserve the meaning exactly.
- Keep the same situation, subject, and emotional direction.
- Do not replace the concrete situation with a vague mood line.
- If the source says someone misses someone, each variant must still clearly say that.
- Keep named entities and numbers unchanged.
- Keep each hook between {min_chars} and {max_chars} characters.
- Keep it punchy, natural, and not corporate.
- Output strict JSON only:
  {{"hooks": ["variant 1", "variant 2"]}}

Source hook:
{base}
"""


def parse_hook_response(raw: str) -> list[str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("Ollama returned malformed JSON") from e
    if isinstance(data, dict) and isinstance(data.get("hooks"), list):
        hooks = data["hooks"]
    elif isinstance(data, dict) and isinstance(data.get("hook"), str):
        hooks = [data["hook"]]
    elif isinstance(data, list):
        hooks = data
    else:
        raise ValueError("Ollama JSON must contain a hooks list")
    out = [str(h).strip() for h in hooks if str(h).strip()]
    if not out:
        raise ValueError("Ollama returned no usable hooks")
    return out


def _required_terms(base: str) -> list[str]:
    terms = re.findall(r"\b\d+(?:\.\d+)?\b", base)
    terms.extend(re.findall(r"\"([^\"]+)\"", base))
    return [term for term in terms if term]


def _keyword_terms(base: str) -> list[str]:
    stop = {
        "the", "and", "but", "for", "with", "when", "what", "that", "this",
        "you", "your", "from", "into", "just", "like", "then", "than", "are",
        "was", "were", "been", "have", "has", "had", "not", "all", "one",
    }
    terms = []
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9']{3,}", base.lower()):
        if token not in stop and token not in terms:
            terms.append(token)
    return terms[:6]


def _missing_concepts(base: str, hook: str) -> str | None:
    base_norm = base.lower()
    hook_norm = hook.lower()
    if re.search(r"\bmiss(?:es|ing|ed)?\b", base_norm) and not re.search(r"\bmiss(?:es|ing|ed)?\b", hook_norm):
        return "miss"
    return None


def validate_hook_variant(base: str, hook: str, *, min_chars: int,
                          max_chars: int, required_terms: list[str] | None = None,
                          reject_identical: bool = False,
                          strict: bool = False,
                          min_similarity: float | None = None,
                          embedding_model: str | None = HASH_MODEL) -> tuple[bool, str]:
    text = hook.strip()
    if len(text) < min_chars:
        return False, "too_short"
    if len(text) > max_chars:
        return False, "too_long"
    if reject_identical and text.lower() == base.strip().lower():
        return False, "identical_to_source"
    if strict:
        missing_concept = _missing_concepts(base, text)
        if missing_concept:
            return False, f"missing_core_concept:{missing_concept}"
    lowered = text.lower()
    terms = list(_required_terms(base))
    if required_terms:
        terms.extend(required_terms)
    for term in terms:
        if term.lower() not in lowered:
            return False, f"missing_required_term:{term}"
    if strict and min_similarity is None:
        min_similarity = 0.50
        if embedding_model == HASH_MODEL:
            embedding_model = DEFAULT_EMBEDDING_MODEL
    if min_similarity is not None:
        provider = get_embedding_provider(embedding_model)
        if provider.name == HASH_MODEL and strict and min_similarity >= 0.50:
            min_similarity = 0.18
        score = cosine_similarity(provider.embed(base), provider.embed(text))
        if score < min_similarity:
            return False, f"low_semantic_similarity:{score:.3f}"
    return True, "ok"


def hook_similarity_mode(embedding_model: str | None) -> str:
    provider = get_embedding_provider(embedding_model)
    return "lexical_fallback_similarity" if provider.name == HASH_MODEL else "semantic_embedding_similarity"


def validate_hook_variants(base: str, hooks: list[str], *, min_chars: int,
                           max_chars: int, required_terms: list[str] | None = None,
                           reject_identical: bool = False, strict: bool = False,
                           min_similarity: float | None = None,
                           embedding_model: str | None = HASH_MODEL) -> tuple[list[str], list[dict[str, str]]]:
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    seen = set()
    for hook in hooks:
        ok, reason = validate_hook_variant(
            base,
            hook,
            min_chars=min_chars,
            max_chars=max_chars,
            required_terms=required_terms,
            reject_identical=reject_identical,
            strict=strict,
            min_similarity=min_similarity,
            embedding_model=embedding_model,
        )
        if ok and hook not in seen:
            accepted.append(hook)
            seen.add(hook)
        else:
            rejected.append({"hook": hook, "reason": "duplicate" if hook in seen else reason})
    return accepted, rejected


def generate_hooks(*, backend: str, model: str, base: str, n: int = 20,
                   min_chars: int = 20, max_chars: int = 120,
                   seed: int = 42, strict: bool = False,
                   required_terms: list[str] | None = None,
                   reject_identical: bool = False,
                   min_similarity: float | None = None,
                   embedding_model: str | None = HASH_MODEL,
                   log_path: str | Path | None = None,
                   recent_hooks: list[str] | None = None) -> dict[str, Any]:
    if backend != "ollama":
        return {"ok": False, "error": f"unsupported backend: {backend}", "hooks": []}
    similarity_mode = hook_similarity_mode(embedding_model)
    warnings: list[str] = []
    if strict and similarity_mode == "lexical_fallback_similarity":
        warnings.append("strict_semantic_validation_using_lexical_fallback")
    provider = OllamaHookProvider(model=model)
    ok, reason = provider.available()
    if not ok:
        return {"ok": False, "error": reason, "hooks": []}
    try:
        prompt = _rewrite_prompt(base, n=n, min_chars=min_chars, max_chars=max_chars)
        raw_hooks = provider.rewrite(base, n=n, min_chars=min_chars, max_chars=max_chars, seed=seed)
        hooks, rejected = validate_hook_variants(
            base,
            raw_hooks,
            min_chars=min_chars,
            max_chars=max_chars,
            required_terms=required_terms,
            reject_identical=reject_identical,
            strict=strict,
            min_similarity=min_similarity,
            embedding_model=embedding_model,
        )
    except (RuntimeError, ValueError, urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": str(e), "hooks": []}
    generation_id = new_generation_id()
    quality = [
        score_caption_quality(hook, recent_hooks=recent_hooks, min_chars=min_chars, max_chars=max_chars)
        for hook in hooks
    ]
    rejected_with_quality = [
        {
            **item,
            "quality": score_caption_quality(str(item.get("hook", "")), recent_hooks=recent_hooks, min_chars=min_chars, max_chars=max_chars),
        }
        for item in rejected
    ]
    if log_path:
        append_generation_log(
            Path(log_path),
            build_generation_record(
                generation_id=generation_id,
                backend=backend,
                model=model,
                prompt=prompt,
                base=base,
                requested_count=n,
                accepted=hooks,
                rejected=rejected_with_quality,
                required_terms=required_terms,
                seed=seed,
                strict=strict,
                min_chars=min_chars,
                max_chars=max_chars,
                embedding_model=embedding_model,
                quality=quality,
            ),
        )
    return {
        "ok": True,
        "backend": backend,
        "model": model,
        "generationId": generation_id,
        "hooks": hooks,
        "quality": quality,
        "rejected": rejected_with_quality,
        "similarityMode": similarity_mode,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default="ollama", choices=["ollama"])
    ap.add_argument("--model")
    ap.add_argument("--base")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--min-chars", type=int, default=20)
    ap.add_argument("--max-chars", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--required-term", action="append", default=[])
    ap.add_argument("--reject-identical", action="store_true")
    ap.add_argument("--min-similarity", type=float, default=None)
    ap.add_argument("--embedding-model", default=HASH_MODEL)
    ap.add_argument("--log-path", default="project_data/caption_generations.jsonl")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--caption-library", action="store_true")
    ap.add_argument("--rank-existing", action="store_true")
    ap.add_argument("--clip")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--captions-dir", default="01_captions")
    ap.add_argument("--performance-json")
    args = ap.parse_args()
    if args.caption_library:
        print(json.dumps(caption_library(Path(args.log_path)), indent=2, ensure_ascii=False))
        return 0
    if args.rank_existing:
        if not args.clip:
            raise SystemExit("--rank-existing requires --clip")
        performance = {}
        if args.performance_json:
            performance = json.loads(Path(args.performance_json).read_text(encoding="utf-8"))
        result = rank_clip_sidecar(
            Path(args.captions_dir),
            args.clip,
            recent_hooks=None,
            top=args.top,
            performance_by_caption_hash=performance.get("captionHashes") if isinstance(performance, dict) else None,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if not args.model or not args.base:
        raise SystemExit("--model and --base are required unless using --caption-library or --rank-existing")
    result = generate_hooks(
        backend=args.backend,
        model=args.model,
        base=args.base,
        n=args.n,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        seed=args.seed,
        strict=args.strict,
        required_terms=args.required_term,
        reject_identical=args.reject_identical,
        min_similarity=args.min_similarity,
        embedding_model=args.embedding_model,
        log_path=None if args.no_log else args.log_path,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
