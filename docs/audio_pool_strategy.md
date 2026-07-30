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
- ThreadsDashboard submits the exact approved MP4 source bytes without replacing
  embedded audio or selecting native audio. Meta may transcode the uploaded file;
  the Instagram media ID, not a matching platform-file SHA, identifies the
  publication.

## Production policy

```text
non-talking intent
  -> embedded_trending_required
  -> verified active Audio Radar track
  -> duration-compatible segment
  -> AAC embedded in the final MP4
  -> receipt binds exact segment bytes and final MP4 SHA-256

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
CREATOR_OS_AUDIO_WINNER_TRACK_COOLDOWN_DAYS=3
CREATOR_OS_AUDIO_PINNED_TRACK_COOLDOWN_DAYS=2
CREATOR_OS_AUDIO_ABSOLUTE_MINIMUM_GAP_HOURS=24
CREATOR_OS_AUDIO_CREATOR_SEGMENT_COOLDOWN_DAYS=14
```

Actual account fatigue is clocked from `performance_snapshots.published_at`.
Active unpublished selections are separately excluded from
`audio_selections.selected_at`, which prevents draft and scheduled inventory
from selecting the same track. A pinned track or measured winner shortens the
account cooldown but cannot bypass the 24-hour floor, and neither bypasses the
creator segment cooldown. Historical metadata remains after cache bytes are
pruned.

## Segment lineage

Every production selection records:

- exact segment start, end, and duration;
- SHA-256 of the canonical decoded `s16le_mono_16000hz` segment bytes;
- decoded-audio fingerprint;
- source track identity and hash;
- final verified MP4 SHA-256 after AAC embedding.

The downstream audio intent carries a SHA-256 of the immutable embedding receipt
core plus the acquired-audio SHA, processed-segment SHA, segment bounds, final
media SHA, and final audio fingerprint. Embedded fulfillment is classified
`EXACT_BYTE_VERIFIED`; native and manual evidence must use their weaker,
explicit evidence classes rather than this byte-level claim.

The processed-segment hash and decoded fingerprint intentionally identify the
same canonical byte slice. Selection fails if the decoded source cannot supply
the complete requested duration. Publication learning accepts the live
snake-case receipt fields while retaining read compatibility for historical
camel-case receipts; it never invents missing historical linkage.

The embedding worker also implements a speaking mix primitive: non-speaking
visuals replace existing audio, while a speaking source preserves speech and
mixes music at `speech_music_volume`. This primitive does not make talking or
lip-sync a supported Creator OS product mode.

Usage-rights provenance is a separate publication gate from byte and trend
evidence. Track metadata must not infer authorization from successful
acquisition; account, territory, commercial-use, expiry, and evidence-receipt
requirements are explicit policy inputs. When a track marks rights as required,
Creator OS and ThreadsDashboard both fail closed until those fields prove a
currently valid authorization.

## Development-only segment challenger

The normal production selector is unchanged. A bounded, read-only librosa
challenger is available only through the optional `audio-eval` dependency group
for local development:

```sh
uv run --group audio-eval python -m \
  campaign_factory.audio_radar.development_evaluator \
  --duration 5 /absolute/path/to/audio.mp3
```

It evaluates at most ten regular local files and at most 90 seconds per file,
prints JSON to stdout, and performs no provider, network, database, cache, or
persistent artifact writes. Its RMS, onset, and beat evidence is comparative
development output, not a production default or automatic promotion signal.

## Weekly refresh

See [`operations/audio_refresh.md`](operations/audio_refresh.md). The supported
command is:

```sh
creator-os audio refresh --region US --max-new 20 --max-active 75 --apply
```
