# First Real Stacey Learning Proof Plan

Read-only design only. Do not publish from this document.

## Candidate cohort

The comparable visual inputs are three distinct approved-by-chat Stacey Kling 3
canaries, each 5.041667 seconds, 1080×1920 H.264 with verified AAC and passed
technical QC:

| Candidate | Source asset / SHA | Generation ID | Final candidate SHA |
|---|---|---|---|
| 1 | `src_e3faecf2b473` / `5c4a5d35f7df4b03fd14f7fa28c2721f1cc5594354cd87224bf5f82ee348c749` | `0ff2b4a6-5296-45ad-a0c6-8f795020e7cf` | `c8186c83578061bbb83b451f22d99cdcf3645710c4d56c8a3709f04d647587dd` |
| 2 | `src_4da46d7cc0fa` / `02480d7d305390b7fd6d68eea9d2126fffb43307ab513306b3573ebc9a5daf5f` | `2781fb6e-b3ed-4bf5-a43b-d27399abb7b5` | `8e41c1ce6f0bf9bc000b6b0cab1da4ce8b6ed8b670838bcbb51f4129ec83beda` |
| 3 | `src_44520dccb795` / `1c8fcbac3a338db216f48b4dbb92501210063e2e2e3a2d7b9794e4332a41364d` | `d7fa8027-28a3-4038-b2e3-aa52b02af44f` | `2ceeb1cfb04d3f30975ae9dbaed93c7f229ca928aab0494bd5d3a0e6bc4f4fca` |

There is also a later Audio Radar re-embedding set with SHAs `959b5c8b…`,
`cf20127b…`, and `948e5669…`. Do not mix the two sets. Before publication, the
operator must choose one exact set and persist Campaign approval and canonical
audio selection rows for those exact final hashes.

## Controlled design

- Creator/profile: Stacey and her pinned Soul identity.
- Account: `stacey-main` only, after ThreadsDashboard resolves that alias to one
  healthy exact account.
- Intent: `passive_selfie` for all three.
- Visual recipe: Higgsfield Kling 3 for all three.
- Duration/source class: matched portrait passive motion.
- Surface: use the same surface for all three; regular Reel is preferred unless
  the operator explicitly chooses a Trial Reel cohort for all three.
- Spacing: at least 48 hours between posts to reduce overlap and permit a clean
  24h observation before the next post. Keep the same local posting-window
  family.
- Controlled variables: account, intent, recipe, duration, surface, caption
  family, disclosure policy, and observation buckets.
- Deliberate differences: source image and exact audio track/segment. Because
  two variables differ, results are correlational and cannot isolate source
  from audio causally.

## Preconditions for each post

1. source is explicitly approved and hash-valid;
2. exact final MP4 is chosen from one set above;
3. technical QC and AAC receipt bind that exact SHA;
4. Campaign operator approval binds that exact SHA;
5. canonical audio selection preserves TikTok music ID, track SHA, acoustic
   fingerprint, segment bounds/hash, and final MP4 SHA;
6. export dry-run verifies HMAC payload/account/caption/media;
7. ThreadsDashboard preflight is healthy;
8. no earlier cohort post is publication-ambiguous.

Failure of any precondition invalidates that candidate before publication.

## Observation plan

- Capture 1h for early advisory diagnostics.
- Capture 24h for the first production-eligible equal-age cohort.
- Capture 72h for the preferred mature comparison.
- Preserve views/plays, reach, impressions, likes, comments, shares, saves,
  total and average watch time, and any exposed retention/completion values.
- Missing values stay null. Revised observations append/supersede current
  summaries without deleting history.
- All three must have a real Instagram media ID, valid source/final lineage,
  exact account/creator/intent, and the same observation bucket.

Exclude failed/unconfirmed publications, pre-cutover rows, fallback/fixture
rows, invalid lineage, and mixed-age observations.

## Learning proof

After all three have matching 24h or 72h observations:

1. run `creator-os learning-refresh --dry-run`;
2. verify one same-scope recommendation cites exactly the three measured
   outcome IDs and is `ADVISORY`;
3. run `creator-os learning-refresh --apply`;
4. inspect with `creator-os learning-review list`;
5. explicitly approve one recommendation;
6. run a fourth normal Stacey `creator-os create ...` **dry-run**;
7. verify the decision receipt shows matched pack/recommendation, base ordering,
   learned adjustment, final approved choice, and `learningApplied=true`;
8. require `finalChoiceChanged=true` before calling the software path adaptive.

Do not publish Reel 4 merely to prove consumption. A changed dry-run proves
decision consumption; later publication and equal-age results are needed to
judge whether the decision improved performance.

## Conclusions allowed

Allowed: one approved recommendation changed one later already-approved
source/prompt/audio ordering for the same creator/account/intent.

Not allowed: causal superiority of a source or audio track, global transfer to
another creator/account, provider/model improvement, or autonomous
self-improvement.
