# Reel Factory Agent Notes

Before changing generation, Higgsfield/Soul ID settings, Kling motion handling, GUI generation controls, audio selection, or cross-repo Creator OS behavior, read:

```text
SYSTEM_OVERVIEW.md
CURRENT_PRODUCTION_FLOW.md
PIPELINE_BOUNDARIES.md
DO_NOT_CHANGE.md
REPO_MAP.md
DECISIONS.md
docs/next_chat_reel_factory_handoff.md
```

High-priority reminders:

- Active still-image path: `generate_assets.py reference-image` or `reference-image-dry-run`.
- Use Stacey Soul ID for Stacey generations:
  `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`.
- Active stills are direct Higgsfield reference-image generations with `--image <reference>`.
- Active still aspect ratio is `9:16`.
- Do not append prompt text for Stacey reference generations. No body-emphasis flags, no captured-prompt reruns, and no "make it sexier" prompt hacks in the active path.
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
