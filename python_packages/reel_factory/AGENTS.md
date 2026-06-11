# Reel Factory Agent Notes

Before changing prompt generation, Higgsfield/Soul ID settings, Gemini/Kling
motion handling, GUI generation controls, audio selection, or cross-repo
Creator OS behavior, read the root Creator OS knowledge base first:

```text
SYSTEM_OVERVIEW.md
CURRENT_PRODUCTION_FLOW.md
PIPELINE_BOUNDARIES.md
DO_NOT_CHANGE.md
REPO_MAP.md
DECISIONS.md
```

Then read the Reel Factory handoff:

```text
docs/next_chat_reel_factory_handoff.md
```

That handoff contains the current production rules, recent mistakes to avoid,
Stacey Soul ID settings, aspect-ratio guidance, Grok prompt behavior, and
Gemini/Kling motion cleanup rules.

High-priority reminders:

- Use Stacey Soul ID for Stacey generations:
  `5828d958-91dd-4d6d-8909-934503f47644`.
- Do not pass reference images into Higgsfield image generation.
- Keep Higgsfield prompt enhancement off.
- Current default image grid aspect ratio is `4:3`.
- Prefer `single`, `2x2`, or `3x2`/six-panel grids for quality tests.
- Do not use image-prompt cleanup rules on Gemini/Kling motion text.
- Do not automate Instagram/private APIs/logins/publishing.
