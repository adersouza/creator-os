"""Minimal MLX-VLM worker for deterministic, image-aware Wan prompt expansion.

This module is executed by a separate pinned runtime. Keep it dependency-light:
it must not import Creator OS packages or inspect operator environment state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--user-prompt", required=True)
    parser.add_argument("--max-tokens", type=int, default=180)
    return parser


def main() -> int:
    args = _parser().parse_args()
    model, processor = load(str(args.model), lazy=False)
    messages = [
        {"role": "system", "content": args.system_prompt},
        {"role": "user", "content": args.user_prompt},
    ]
    formatted = apply_chat_template(
        processor,
        model.config,
        messages,
        num_images=1,
    )
    result = generate(
        model,
        processor,
        formatted,
        image=[str(args.image)],
        max_tokens=args.max_tokens,
        temperature=0.0,
        skip_special_tokens=True,
        verbose=False,
    )
    print(
        json.dumps(
            {
                "schema": "reel_factory.local_wan_prompt_expansion_worker.v1",
                "text": result.text,
                "promptTokens": result.prompt_tokens,
                "generationTokens": result.generation_tokens,
                "peakMemoryGb": result.peak_memory,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
