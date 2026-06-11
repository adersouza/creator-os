# AudioProviderV1

AudioProviderV1 keeps Reel Factory audio simple. It selects posting audio
metadata; it does not mux, synchronize, classify mood with AI, or publish to
TikTok.

## Modes

- `AUTO_TRENDING`: default. Selects with a 60/30/10 split:
  - 60% TikTok Commercial Music Library primary pool
  - 30% local winners proven in the user's own archive
  - 10% watch-list candidates
- `SAFE_LIBRARY`: selects only from the curated local winner pool.
- `CUSTOM`: records an operator-provided manual track.

## Sources

The provider reads local cache files:

```text
project_data/audio_sources/tiktok_cml_trending.json
project_data/audio_sources/curated_winners.json
project_data/audio_sources/local_winners.json
project_data/audio_sources/watch_list.json
```

The TikTok CML cache should be refreshed by a separate business-safe integration
or manual import. Reel Factory does not automate TikTok logins, private APIs, or
publishing.

Official TikTok guidance points businesses to Commercial Sounds in the mobile
app or the Commercial Music Library in Creative Center. If TikTok provides a
download/export or an officially documented endpoint for the account, use
`audio_refresh.py` to normalize that file into the local cache. Do not scrape
logged-in Creative Center pages or private network APIs.

Example CML cache:

```json
{
  "tracks": [
    {
      "track_id": "123",
      "track_name": "Creator Spark",
      "source": "tiktok_cml",
      "trend_rank": 4,
      "tags": ["upbeat", "fashion", "pop"]
    }
  ]
}
```

Example curated winner cache:

```json
{
  "tracks": [
    {
      "track_id": "winner_001",
      "track_name": "Known Winner",
      "source": "safe_library",
      "tags": ["confidence", "luxury"]
    }
  ]
}
```

`local_winners.json` uses the same shape, but can contain local TikTok audio IDs
when the archive has strong play/like evidence and no readable song title.
`watch_list.json` is for monitored candidates that should get only light
traffic until they prove themselves.

## Output

Selection output includes the fields the posting layer needs:

```json
{
  "track_id": "123",
  "track_name": "Creator Spark",
  "source": "tiktok_cml",
  "trend_rank": 4,
  "selected_reason": "auto_cml_primary_60pct"
}
```

## Tracking What Works

When a selected track is attached to an output, store the selection inside that
output's `<output>.audio_intent.json` sidecar as `audio_selection`. The important
join key is `audio_selection.track_id`.

Later performance imports can group post outcomes by `track_id` to find:

- best average views
- best like/share/save rate
- best retention or manual score
- tracks that disappeared or caused licensing friction

Keep the selection metadata stable even if the actual platform audio is attached
inside TikTok. Reel Factory should track the intent and outcome; it should not
download or redistribute the music.

## Commands

Select one track:

```bash
python3 audio_provider.py --root . --mode AUTO_TRENDING --seed clip_001
```

Select and save the record:

```bash
python3 audio_provider.py --root . --mode AUTO_TRENDING --seed clip_001 --write --stem clip_001
```

Refresh the CML primary pool from an official export or manually saved list:

```bash
python3 audio_refresh.py --root . --cml-export /path/to/tiktok_cml_export.json
```

Weekly automation drop-folder flow:

```bash
mkdir -p project_data/audio_sources/official_cml_inbox
python3 audio_refresh.py --root . --latest-cml-export
```

Put the official TikTok CML export or manually saved official list in
`project_data/audio_sources/official_cml_inbox/`. The refresh command imports
the newest `.json` or `.csv` file, records its SHA-256 in
`project_data/audio_sources/refresh_state.json`, and skips repeated imports of
the same file.

Refresh pools from the reviewed candidate list:

```bash
python3 audio_refresh.py --root . --review-candidates project_data/audio_sources/tiktok_audio_candidates_review_20260603.json
```

Use `SAFE_LIBRARY` when consistency matters more than trend exposure. Use
`CUSTOM` only for manual override tests.

## Non-Goals

Do not build these until audio is proven to be a bottleneck:

- audio matching AI
- mood classification
- music recommendation engines
- beat synchronization
- platform login or posting automation
