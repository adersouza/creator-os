# Reference Bank Rebuild — 2026-07-10

This is the portable, non-media subset of learning run
`learning_run_a6e3abe7e4695199`.

## Configuration

- Limit: 300
- Per-account cap: 60
- Caption-driven target share: 0.5
- Strict balance: enabled; scarce visual capacity was not padded with caption-led references
- Pattern provider: deterministic local heuristic
- Embedding clustering: disabled for this reproducible rebuild
- Human labels: Gold-first authoritative ranking
- Measured generated-post outcomes: secondary ranking signal

## Result

- Selected Gold references: 169
- Caption-driven references: 150
- Visual-driven references: 19
- Learning clusters: 9
- Largest source-account contribution: 60 references
- Public posts with follower counts: 500 of 520

Follower-normalized ranking is implemented as `(likes + comments) / followers`
and is preferred whenever follower counts exist. Nested follower counts already
present in stored `author` and `user` source objects were recovered for 500
posts across seven accounts. The remaining 20 posts contain no follower count
and retain the documented engagement-per-view and raw-volume fallback. No
counts were inferred or fabricated.

The visual-driven side remains thin. The current signal classifier treats any
stored OCR caption pattern as caption-driven, and 495 of 520 posts have at least
one such pattern. Because some OCR text is low-confidence noise, increasing the
visual count now requires an evidence-backed signal review; this rebuild does
not auto-relabel references from OCR confidence alone.

## Reproduction

With `REFERENCE_FACTORY_DB` pointing to the operator-owned local database:

```bash
uv run python -m reference_factory.cli \
  --db "$REFERENCE_FACTORY_DB" \
  backfill-follower-metrics --apply

uv run python -m reference_factory.cli \
  --db "$REFERENCE_FACTORY_DB" \
  --data-root /tmp/reference-bank-rebuild \
  analyze-patterns --limit 300 --provider heuristic \
  --account-cap 60 --caption-share 0.5 --strict-balance

uv run python -m reference_factory.cli \
  --db "$REFERENCE_FACTORY_DB" \
  --data-root /tmp/reference-bank-rebuild \
  export-patterns --limit 300 \
  --account-cap 60 --caption-share 0.5 --strict-balance

uv run python -m reference_factory.cli \
  --db "$REFERENCE_FACTORY_DB" \
  --data-root /tmp/reference-bank-rebuild \
  build-learning-system --limit 300 --no-embedding-clusters \
  --account-cap 60 --caption-share 0.5 --strict-balance
```

Machine-local media paths in the committed JSON are represented by
`${REFERENCE_REELS_ROOT}` and `${TIKTOK_ARCHIVE_ROOT}`. Raw media, the SQLite
database, embedding cache, and expanded JSONL runtime bundle are intentionally
excluded.
