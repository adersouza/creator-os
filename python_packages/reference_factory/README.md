# Reference Factory

Reference Factory teaches Creator OS. It indexes operator-owned reference
media, extracts local evidence, supports human gold/maybe/ignore labels, builds
winner patterns and prompt packs, recommends audio, and imports measured prompt
outcomes.

It does not decide campaigns, generate platform posts, schedule, or publish.

## Supported Operator Path

The root command provides the canonical local reference/audio refresh:

```bash
scripts/creator-os reference-refresh --dry-run
scripts/creator-os reference-refresh --apply --source ~/Downloads/tiktok
```

Dry run prints the exact commands and paths. Apply updates only local Reference
and Campaign data and exports the audio catalog; it never touches
ThreadsDashboard or a provider.

## Package CLI

Inspect all package-owned commands without side effects:

```bash
uv run --package reference-factory python -m reference_factory.cli --help
```

Common local stages include:

```bash
uv run --package reference-factory python -m reference_factory.cli scan \
  --source ~/Downloads/examples
uv run --package reference-factory python -m reference_factory.cli probe
uv run --package reference-factory python -m reference_factory.cli sample-frames
uv run --package reference-factory python -m reference_factory.cli ocr
uv run --package reference-factory python -m reference_factory.cli review-batch
uv run --package reference-factory python -m reference_factory.cli export-gold
uv run --package reference-factory python -m reference_factory.cli analyze-patterns
uv run --package reference-factory python -m reference_factory.cli build-learning-system
```

These commands can write the configured local database and derived-data root.
Provider-backed generation and analysis commands are advanced paths and require
their own explicit provider/credit gates.

## Human Review Surface

`review-server` is intentionally retained. It is the active local browser
surface for human reference labels, not a product dashboard or publishing UI.

```bash
uv run --package reference-factory python -m reference_factory.cli review-server
```

Labels remain operator decisions. Never synthesize gold coverage from uncertain
or missing evidence.

## Outputs

The configured `REFERENCE_FACTORY_DATA_ROOT` owns derived artifacts such as:

- manifests, thumbnails, frame samples, contact sheets, and OCR;
- curated gold/maybe/ignore outputs;
- learning sets, pattern cards, clusters, and playbooks;
- Higgsfield/Kling prompt packs;
- Campaign reference banks and caption formulas;
- audio catalogs, snapshots, and recommendations.

The configured `REFERENCE_FACTORY_DB` owns indexed reference, label, pattern,
audio, and outcome state. Both are operator/runtime data and stay outside Git.

`creator_os_core.runtime_paths` resolves default monorepo, data, and ContentForge
paths without a personal hardcoded checkout.

## Learning Boundary

Campaign performance outcomes may be imported for ranking, but missing follower
or platform metrics remain missing. Fallback ranking must be documented; it must
not fabricate counts. Ambiguous or conflicting lineage remains ineligible.

## Test

```bash
uv run python -m pytest python_packages/reference_factory/tests
```

Coverage protects ingestion, labels, ranking, outcome imports, provider
failures, prompt/audio exports, proof bundles, and the Campaign/Reel seams.
