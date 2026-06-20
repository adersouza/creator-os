# Audio Pool Strategy

Creator OS now has a reusable seed pool at `docs/examples/audio_catalog_seed_tiktok_20260620.json`.
Import it into Campaign Factory with:

```bash
PYTHONPATH=python_packages/campaign_factory python3 -m campaign_factory.cli import-audio-catalog --path docs/examples/audio_catalog_seed_tiktok_20260620.json
```

## Current Split

- Reference Factory owns audio intake, review, trend metadata, and `audio_catalog_export.v1`.
- Campaign Factory owns recommendation, account fit, fatigue/performance rollups, and `audio_intent.v1`.
- ThreadsDashboard owns user selection, Meta audio search/metadata, native-audio proof, and publish preflight.

## Product Pattern

Do the smallest useful version:

1. Show Campaign Factory recommendations first.
2. Let the user search platform-native audio when the connected account supports it.
3. Store the selected platform audio id/title/artist/proof on `audio_intent.operator_selection`.
4. Block live publishing until native audio is verified by ThreadsDashboard preflight.
5. Fall back to notification/manual publishing when a platform audio cannot be attached through API.

Do not burn platform/trending audio into rendered videos unless the operator explicitly provides licensed local audio.
