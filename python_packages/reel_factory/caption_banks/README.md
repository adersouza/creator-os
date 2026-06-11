# Caption Banks

Caption banks organize Reel Factory hooks for weighted rotation. They do not delete, censor, or suppress captions based on style.

- `banks.json` stores reusable caption banks with source metadata and bank membership.
- `mixes.json` stores creator-level weights for Larissa, Stacey, and Lola.
- `performance.json` is intentionally manual-ready scaffolding for future caption performance metadata keyed by `caption_hash`.
- `winner_bank` starts empty and is reserved for future manually promoted captions.

Default mixes target hot adult girl-next-door, mirror selfie, bedroom selfie, and body-forward content. Goth/dark/alt, experimental edge, weird generated history, and winner bank are selectable but off by default.

Each bank item includes static caption fit metadata (`length_class`, `format_class`, word/character/line counts). `reel_pipeline.py --caption-fit auto` uses that metadata with detected frame type so wide or full-body mirror clips prefer short readable hooks, while close-up clips can keep longer hooks. `--caption-fit off` preserves the older bank-selection behavior.
