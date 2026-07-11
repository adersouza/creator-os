# Reference Bank Rebuild — 2026-07-10

This is the portable, non-media subset of learning run
`learning_run_dafd786d1e0a309b`.

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

- Selected Gold references: 158
- Caption-driven references: 137
- Visual-driven references: 21
- Learning clusters: 8
- Largest source-account contribution: 56 references
- Public posts with follower counts: 0 of 520

Follower-normalized ranking is implemented as `(likes + comments) / followers`
and is preferred whenever follower counts exist. No existing local metric input
contained follower counts, so this run used the documented engagement-per-view
and raw-volume fallback. No counts were inferred or fabricated.

## Reproduction

With `REFERENCE_FACTORY_DB` pointing to the operator-owned local database:

```bash
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
