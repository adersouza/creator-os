# Audio Radar production strategy

Audio Radar is the automatic music path for normal non-talking Reels. The
operator does not manually choose a song during ordinary production.

## Ownership

- SocialCrawl TikTok trending videos are the primary discovery feed.
- TikTok Creative Center is optional chart enrichment.
- SocialCrawl Instagram is optional and non-blocking.
- TikLive resolves selected TikTok music IDs to downloadable audio.
- Campaign Factory owns the canonical catalog, verified cache, lifecycle,
  matching, segment selection, AAC embedding, and final-media receipt.
- ThreadsDashboard publishes the exact completed MP4 unchanged. It does not
  replace embedded TikTok audio with native Instagram audio.

## Production policy

```text
non-talking intent
  -> embedded_trending_required
  -> verified active Audio Radar track
  -> duration-compatible segment
  -> AAC embedded in the final MP4
  -> receipt bound to the final MP4 SHA-256

talking or supplied-voice intent
  -> creator_voice
  -> preserve dialogue
  -> no automatic music replacement
```

No valid active cached track means production fails with
`NEEDS_EMBEDDED_AUDIO`. Production does not fall back to fixtures, random local
music, native Instagram audio, or silence. A local fixture is available only
through the explicit test-only `CREATOR_OS_EMBEDDED_AUDIO_FIXTURE` override.

## Rotation and reuse

The active library contains only hash-verified playable cache objects.
Selection considers lifecycle/freshness, content tags, duration, recent use,
measured performance, and batch uniqueness. Exact acoustic duplicates are
removed before batch partitioning.

Machine-local cooldown defaults are configurable:

```sh
CREATOR_OS_AUDIO_ACCOUNT_TRACK_COOLDOWN_DAYS=7
CREATOR_OS_AUDIO_CREATOR_SEGMENT_COOLDOWN_DAYS=14
```

A pinned track or measured winner may explicitly override cooldown. Historical
metadata remains after cache bytes are pruned.

## Weekly refresh

See [`operations/audio_refresh.md`](operations/audio_refresh.md). The supported
command is:

```sh
creator-os audio refresh --region US --max-new 20 --max-active 75 --apply
```
