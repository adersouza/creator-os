# Creator OS Decisions

This is the decision log for the current approved architecture.

## Prompt Architecture

Decision: Grok writes final image prompts directly.

Evidence:

- `/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py`
- production compatibility mode `grok-direct`
- reported lineage mode `reference_factory_sexy_realistic`

Reason:

- Manual and paid A/B tests showed the old Reference Factory-style prompt language produced the best viral/body-forward image grids.
- Overbuilt compiler-style prompt rewrites caused prompt drift and weaker outputs.
- Grok direct output preserves the useful language while cleanup removes forbidden identity/face-polish budget.

Rejected:

- A heavy schema/compiler between Grok and Higgsfield.
- Conservative prompt language as production default.
- Summarizing or optimizing Grok output after the API response.

## Prompt Cleanup

Decision: cleanup is removal-only.

Allowed:

- Remove forbidden identity/face-polish terms.
- Repair punctuation/spacing after removals.
- Replace hair-contact pose language with `hand near head` or `hand behind head`.

Rejected:

- Rewriting the prompt for taste.
- Softening intense body language.
- Removing pose/body/garment mechanics.
- Applying image cleanup rules to Gemini/Kling motion prompts.

## Image Generation

Decision: Soul ID owns identity and Higgsfield does not receive the reference image.

Evidence:

- `/Users/adercialonedesouza/Projects/reel_factory/generate_assets.py`
- `build_image_cmd()` supports `reference`, but production `create_assets()` and dry-runs pass `reference=None`.

Reason:

- Reference images can override prompt composition and identity.
- Soul ID is the trained identity mechanism.
- The reference is only for Grok/Gemini analysis.

Current defaults:

- image model: `text2image_soul_v2`
- image aspect ratio: `4:3`
- image quality: `2k`
- grid layout: `3x2`
- prompt enhancement: off

Rejected or deprioritized:

- `21:9`: unsupported.
- `3:2`: weaker in prior tests.
- Always using `16:9`/`4x2`: useful for some experiments, but higher panel counts hurt per-panel quality.
- Kling before grid crops are visually acceptable.

## Cropper Architecture

Decision: use GridCropperV2 seam detection before Kling.

Evidence:

- `/Users/adercialonedesouza/Projects/reel_factory/grid_crop.py`
- `/Users/adercialonedesouza/Projects/reel_factory/reel_gui.py`

Reason:

- Native image grids are intermediate artifacts.
- The real start frame for Kling is a cropped panel.
- Seam-aware crop lines reduce panel boundary errors compared with fixed math-only crops.

Behavior:

- content-box detection
- grid inference or forced layout
- projection-profile seam detection
- adaptive inset
- `reviewRequired` when confidence is not high

## Gemini/Kling

Decision: Gemini is motion only; Kling receives one shared motion prompt.

Reason:

- Image quality failures were mostly prompt/grid/crop issues, not motion compiler issues.
- Panel-specific Kling prompts add complexity and inconsistency.

Do not touch Gemini/Kling while tuning image prompts unless explicitly requested.

## Audio Architecture

Decision: keep audio metadata selection simple with `AudioProviderV1`.

Evidence:

- `/Users/adercialonedesouza/Projects/reel_factory/audio_provider.py`
- `/Users/adercialonedesouza/Projects/reel_factory/audio_refresh.py`
- `/Users/adercialonedesouza/Projects/reel_factory/docs/audio_provider_v1.md`

Current split:

- 60% TikTok CML primary pool
- 30% local winners
- 10% watch list

Modes:

- `AUTO_TRENDING`
- `SAFE_LIBRARY`
- `CUSTOM`

Reason:

- Audio is not currently the bottleneck compared with image prompt quality, grid quality, crop quality, and Kling quality.
- Stable metadata lets later performance imports learn which audio worked.

Rejected:

- audio matching AI
- mood classifier
- beat synchronization
- scraping or login automation for TikTok audio discovery

## Campaign Factory Control Brain

Decision: Campaign Factory coordinates the ecosystem; it does not replace specialized repos.

Evidence:

- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/control.py`
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/core.py`
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/db.py`

Responsibilities:

- repo health/control checks
- campaign state
- creative plans
- recommendations
- ContentForge audits
- ThreadsDashboard draft exports
- audio catalog/memory
- performance learning
- readiness gates

Rejected:

- moving prompt generation into Campaign Factory
- posting directly from Campaign Factory
- bypassing ContentForge audit/readiness

## Posting And Platform Safety

Decision: Creator OS does not add Instagram/private API automation.

Allowed:

- draft export
- local posting ledger
- manual/operator scheduling packages
- official app/platform paths already guarded in ThreadsDashboard

Not allowed:

- private APIs
- login automation
- unauthorized posting automation
- scraping logged-in endpoints

## Things Future Codex Sessions Must Not Break

- prompt enhancement off
- no reference image sent to Higgsfield
- Soul ID owns identity
- Grok writes image prompts
- Gemini motion only
- GridCropperV2 seam detection
- Campaign Factory control brain
- no Instagram private API automation

