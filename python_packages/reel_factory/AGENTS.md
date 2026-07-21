# Reel Factory Agent Notes

Before changing generation, Higgsfield/Soul ID settings, Kling motion handling,
audio selection, or cross-repo Creator OS behavior, read:

```text
README.md
PIPELINE_BOUNDARIES.md
DO_NOT_CHANGE.md
CANONICAL_DATA_OWNERS.md
../../CREATOR_OS_SYSTEM_MAP.md
```

High-priority reminders:

- Active still-image path: `python -m reel_factory.generate_assets reference-image`
  or `reference-image-dry-run`.
- Use Stacey Soul ID for Stacey generations:
  `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`.
- Active stills are direct Higgsfield reference-image generations with `--image <reference>`.
- Active still aspect ratio is `9:16`.
- A normal reference-conditioned still is one pass. When the operator explicitly
  requests the settled Original + Sexy comparison, follow the repository-root
  two-pass recipe exactly: preserve Pass 1 as Original, clean its captured
  prompt, and make the append-only body-emphasis Sexy variant text-only. Never
  attempt to inject the edit into the reference-conditioned pass.
- Do not make Grok, Qwen, Ollama, Florence, visual-schema extraction, grids, or panel crops the default operator path.
- Use `reel_motion_prompt.py` for accepted-still Kling prompts.
- Do not automate Instagram/private APIs/logins/publishing.
- Burned overlay text is not the Instagram post caption. Burned overlay text is
  rendered by Reel Factory; post captions are owned by Campaign Factory /
  ThreadsDashboard.
- Use `Instagram Sans Condensed` for default IG-style overlay text. Font files
  live in `fonts/`, and the allowed font set is in `recipe_loader.py`.
- Overlay text comes from `caption_banks/` through `caption_bank.py`; never
  freehand it and never burn Higgsfield prompt text into the video.
- Native platform audio is not burned into MP4s. Emit/consume `audio_intent.v1`
  and let ThreadsDashboard select and verify native audio before publish.

Legacy Grok/grid experiment files may remain for old tests, but they are not current production guidance.
