"""Compatibility shim for the pHash/dHash variation audit.

Use perceptual_hash_check.py for the implementation. This name remains so old
commands keep working, but it is not Meta SSCD.
"""

from perceptual_hash_check import (
    HASHES,
    SAMPLE_TIMES,
    audit_clip_dir,
    main,
    mean_hamming,
    probe_duration,
    recipe_from_name,
    sample_hashes,
)

__all__ = [
    "HASHES",
    "SAMPLE_TIMES",
    "audit_clip_dir",
    "main",
    "mean_hamming",
    "probe_duration",
    "recipe_from_name",
    "sample_hashes",
]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "usage: python3 perceptual_hash_check.py /path/to/02_processed/clip_001",
            file=sys.stderr,
        )
        raise SystemExit(2)
    main(sys.argv[1])
