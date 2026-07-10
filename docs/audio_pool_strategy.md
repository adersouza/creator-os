# Audio Pool Strategy

Creator OS now has a reusable seed pool at `docs/examples/audio_catalog_seed_tiktok_20260620.json`.
Import it into Campaign Factory with:

```bash
PYTHONPATH=python_packages/campaign_factory python3 -m campaign_factory.cli import-audio-catalog --path docs/examples/audio_catalog_seed_tiktok_20260620.json
```

Generate a ranked audio intent preview with:

```bash
PYTHONPATH=python_packages/campaign_factory python3 -m campaign_factory.cli recommend-audio --platform tiktok --content-tags shortform,native_audio_pool --limit 5
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

Do not burn platform/trending audio into rendered videos. For automated IG-login
publishing, use explicitly licensed local audio only: download or generate the
track, keep a proof sidecar in `python_packages/reel_factory/03_audio_library`,
mux it into the MP4, and emit `licensed_music` / `embedded_licensed_audio`
evidence.

## Local Licensed Audio

Pixabay Music is a good manual source, but its music downloads are not exposed
through the official Pixabay image/video API. Download selected tracks manually
from the track page, then import the local file or URL.

Use `audio_library_import.py` to validate the audio stream, install it
atomically, and write the SHA-256-addressed license/provenance sidecar. Repeating
the same import is idempotent. Pass either `--url` for a direct HTTP(S) audio
download or `--file` for a local track:

```bash
uv run --package reel-factory python python_packages/reel_factory/audio_library_import.py \
  --root python_packages/reel_factory \
  --url "https://example.com/track.mp3" \
  --title "Track Title" \
  --artist "Artist" \
  --source pixabay \
  --license "Pixabay Content License" \
  --license-url "https://pixabay.com/service/license-summary/" \
  --page-url "https://pixabay.com/music/..." \
  --tag moody --tag reel
```

For a local download, replace `--url ...` with `--file ~/Downloads/track.mp3`.

Other direct-download royalty-free libraries work the same way. The first local
seed uses Incompetech CC BY 4.0 tracks, which require attribution tracking.
