# Do Not Change

These are approved architecture decisions and failure-avoidance rules.

## Hard Invariants

- Do not automate Instagram/private APIs/logins/publishing.
- Do not pass reference images into Higgsfield image generation.
- Keep Higgsfield prompt enhancement disabled.
- Soul ID owns identity.
- Grok writes final image prompts.
- Gemini is motion analysis only.
- Kling is off unless the user explicitly requests video generation.
- Crop and inspect Soul grid panels before Kling.
- Keep GridCropperV2 seam detection in the panel crop path.
- Keep Campaign Factory as the control brain for campaign decisions and exports.

## Prompt Rules

Do not make the system conservative by default. The approved prompt target is sexy, body-forward, viral reel-style imagery while preserving reference pose/scene/camera fidelity.

Keep:

- Grok-direct image prompting.
- `reference_factory_sexy_realistic` as reported production mode.
- scene/camera/framing/lighting fidelity.
- exact pose mechanics.
- arched back, S-curve, hip projection, torso twist, waist-to-hip contrast.
- cleavage/body/garment emphasis when supported by the reference.
- garment cling/stretch and outfit color/material variation.
- old Reference Factory-style direct language.

Do not add back:

- identity/spec budget for hair, hairstyle, hair color, tattoos, ethnicity, eye color, freckles.
- face-polish budget such as perfect face language.
- skin texture/sheen cleanup targets in final prompts.
- prompt enhancement.
- broad prompt rewriting after Grok returns.

Cleanup may only:

- remove forbidden identity/face-polish terms or clauses.
- repair punctuation/spacing caused by removals.
- convert hair-contact pose phrases to `hand near head` or `hand behind head`.

Cleanup must not:

- rewrite, soften, summarize, normalize, optimize, compress, or improve Grok's wording.
- remove intense body, garment, or pose language.

## Image Generation Rules

Current defaults:

- Higgsfield image aspect ratio: `4:3`.
- Prompt grid layout: `3x2` unless the user asks for another layout.
- Quality: `2k`.
- Prompt enhancement: off.
- Reference image passed to Higgsfield: no.
- Use Soul ID for identity.

Rejected or risky paths:

- `16:9` and `4x2` can be useful for experiments, but higher panel counts reduce panel quality and make crop/Kling work harder.
- `3:2` was not worth favoring in prior comparisons.
- Passing the reference image into Higgsfield can override prompt intent and defeats Soul ID ownership.
- Paid Kling before crop inspection wastes runs.

## Audio Rules

Keep audio simple.

Allowed:

- Use `AudioProviderV1` metadata selection.
- Use official TikTok Commercial Music Library / Commercial Sounds exports or manually saved official lists.
- Refresh local CML cache from JSON/CSV drop folder.
- Track selected audio by stable `track_id`.
- Let performance imports later learn what worked.

Not allowed:

- Do not scrape TikTok Creative Center pages.
- Do not automate TikTok login.
- Do not call private TikTok APIs.
- Do not build audio matching AI, beat sync, or a recommendation engine until audio is proven to be a bottleneck.

## Campaign And Posting Rules

Campaign Factory may export drafts and readiness packages. It must not become a private-platform publisher.

The Reel Factory posting ledger is an operator scheduling/control layer only:

- It can create planned slots.
- It can assign approved reels.
- It can detect duplicate content by fingerprint.
- It can require resolved audio metadata or manual-audio-needed markers.
- It does not post to Instagram, TikTok, Threads, or private APIs.

