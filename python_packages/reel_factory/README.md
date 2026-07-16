# Reel Factory

Reel Factory owns Creator OS media creation: direct Soul stills, local static
MP4s, optional motion/Kling, safe caption placement/rendering, audio intent, and
asset lineage. Campaign Factory owns campaign decisions and ThreadsDashboard
owns publishing.

Reel Factory does not initialize or maintain a posting ledger. Its pipeline ends
at a ranked approved-export artifact for Campaign Factory intake.

## Active Path

```text
single-person reference image
  -> Higgsfield Soul V2 with explicit Soul ID
  -> reference-conditioned original + captured composition prompt
  -> optional text-only body-emphasis candidate
  -> QC and human acceptance
  -> local zero-provider-cost static MP4
  -> optional deterministic motion edit or approved best-only Kling
  -> placement.py -> caption_render.py when a safe lane exists
  -> audio_intent.v1 and generated_asset_lineage
  -> Campaign Factory
```

Soul identity, prompt evidence, provider receipts, accepted-still hashes, QC,
and downstream asset IDs remain in lineage. Kling is never the only output; the
static fallback survives a motion failure.

## Operator Commands

Use the monorepo command for normal work:

```bash
scripts/creator-os generate --mode soul_static --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png

scripts/creator-os generate --mode soul_static --apply --confirm-paid \
  --target Stacey --workspace "$PWD" --campaign campaign_slug \
  --reference-image /path/to/reference.png --max-credits 2 --wait --download
```

The second command requires confirmation, target identity, exact checkout, and
a finite native-credit cap. It still stops at local review-ready assets.

Package modules remain available for development and focused inspection:

```bash
uv run --package reel-factory python -m reel_factory.generate_assets --help
uv run --package reel-factory python -m reel_factory.reel_pipeline --help
uv run --package reel-factory python -m reel_factory.caption_bank --help
uv run --package reel-factory python -m reel_factory.pipeline_run --help
uv run --package reel-factory python -m reel_factory.review_batch_guard --help
```

`reel_pipeline.py` remains the real command boundary: it owns argument parsing,
run coordination, audio-intent finalization, and watch mode. Its heavy worker
responsibilities are split by stage: `reel_pipeline_render.py` renders one
output, `reel_pipeline_selection.py` discovers and fits captions/recipes, and
`reel_pipeline_support.py` owns shared render policy and lineage helpers. The
entrypoint exposes only the caller-proven compatibility names in `__all__`;
new internal callers import the owning module directly.

`pipeline_run` never calculates campaign strategy. It requires `--plan` with a
validated `campaign_factory.recommendations.next_batch.v1` export and preserves
that Campaign Factory payload in the run state as its decision provenance.

There are no flat top-level Python facade modules and no Reel browser/API
operator surface.

## Caption And Audio Rules

Burned overlay text and the Instagram post caption are different artifacts.
Overlay text must come from `caption_banks/` and pass through `placement.py` and
`caption_render.py`. The canonical font is Instagram Sans Condensed. A missing
safe lane means no burned overlay; the hook can remain the post caption.

Native platform audio is never burned into the MP4. Reel Factory emits
`audio_intent.v1`; ThreadsDashboard resolves and verifies publishable native
audio.

## Legacy Boundary

The normal root command does not expose Grok/grid/cropped-panel/Qwen/Ollama/
Florence/visual-schema generation. The legacy prompt-generation, six-pack, and
manual grid-crop execution paths were removed after repository and runtime
caller proof. The narrow XAI vision transport remains only for fail-closed
anatomy/postability QC. FFmpeg/FFprobe paths remain active rendering and
evidence infrastructure.

## State And Source

Canonical code is under `reel_factory/`. Its manifest retains render attempts,
prompt/asset lineage, operator ratings, output links, metrics evidence, and
derived media intelligence only; it does not create campaigns, creators,
references, or next-batch plans. Generated media, model weights, provider
receipts, render queues, manifests, and local lineage output remain outside Git.
Curated caption banks, font files, schemas/examples, and sanitized fixtures are
committed source.

See [`PIPELINE_BOUNDARIES.md`](PIPELINE_BOUNDARIES.md) for ownership constraints,
[`CANONICAL_DATA_OWNERS.md`](CANONICAL_DATA_OWNERS.md) for data ownership, and
the root [`CREATOR_OS_SYSTEM_MAP.md`](../../CREATOR_OS_SYSTEM_MAP.md) for the
whole pipeline.

## Test

```bash
uv run pytest python_packages/reel_factory/tests
```

The suite protects provider spend/reservation behavior, identity/QC, lineage,
caption placement, rendering, state transitions, failure handling, review
packages, and active Campaign/ContentForge seams.
