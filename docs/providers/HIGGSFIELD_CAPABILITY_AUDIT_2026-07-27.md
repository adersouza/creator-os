# Authenticated Higgsfield Capability Audit — 2026-07-27

This is a read-only source-capability snapshot. It proves what the authenticated
tool surfaces exposed during implementation; it does not prove merge, runtime
promotion, or a new paid generation.

- CLI: `1.1.19`; account authentication succeeded without credentials being
  printed or stored.
- Souls: the authenticated account returned ready trained identities including
  Stacey, Stacey1, Larissa, and Lola. Production still verifies the selected
  Soul ID live before a paid call.
- CLI commands: account status; Soul list; model/workflow list and get;
  generation cost, create, get, and wait; media upload; result download; credit
  transactions.
- MCP: model discovery and schemas, generic image/video generation, Kling 3
  Motion Control, Soul listing, voice listing, media upload, upscalers, and
  Marketplace search/describe/invoke.
- Marketplace: the authenticated search returned Match Cut and Tracelab; no
  callable talking-avatar, lip-sync, Animate, Recast, Character Swap, UGC, or
  AI Influencer workflow manifest was exposed.

## Classification

| Capability | Classification | Contract finding |
| --- | --- | --- |
| Soul 2.0 | exposed through authenticated CLI | `text2image_soul_v2`; explicit Soul ID and image/text inputs |
| Kling 3.0 | exposed through authenticated CLI | start/end image, prompt, 3-15 seconds, mode, sound on/off |
| Kling 3.0 Turbo | exposed through authenticated CLI | start image, prompt, 3-15 seconds; inspected schema did not expose sound-off |
| Seedance 2.0 / 4K | exposed through authenticated CLI and MCP | image/video/audio references, 4-15 seconds, up to 4K, generated-audio flag |
| Veo 3.1 | exposed through authenticated CLI | start image and dialogue prompt; no supplied-audio input |
| Kling 3 Motion Control | exposed through authenticated CLI and MCP | image plus driving video; the tested settings are a REJECTED RECIPE |
| Gemini Omni Flash | exposed through authenticated CLI/MCP model discovery | image/video editing references; no supplied-audio talking contract |
| image/video upscale | exposed through authenticated MCP | explicit derivative tools; any integration must retain input/output SHA lineage |
| Kling O1 Edit | advertised but not verifiably exposed | CLI exposed an Omni image model, not the claimed video-edit contract |
| Lipsync Studio | browser/UI only | no callable CLI/MCP/Marketplace contract found |
| Higgsfield Speak v2 | official SDK contract; account entitlement unproved | `/v1/speak/higgsfield` structurally accepts `input_image`, WAV `input_audio`, prompt, `mid`/`high` quality, and 5/10/15-second duration; not exposed by CLI/MCP/Marketplace |
| Kling Avatar | advertised but not verifiably exposed | no callable CLI/MCP/Marketplace contract found |
| UGC Factory / AI Influencer | browser/UI only | no manifest proving supplied-voice preservation |
| Higgsfield Animate / Recast / Character Swap | browser/UI only | no distinct callable contract or Soul-ID input contract found |
| relight / inpaint | browser/UI only | no callable contract found in inspected authenticated surfaces |

Seedance accepting an audio reference is not itself proof that it preserves the
voice bytes unchanged. Veo dialogue generation is not exact-voice talking.
Motion Control is not relabeled as Animate. No parameter in this audit is
inferred from a marketing page.

## Speak v2 SDK boundary

The official JavaScript SDK includes `/v1/speak/higgsfield` in its V2 endpoint
type map and documents the same endpoint through the deprecated V1 `generate`
client. The structural input is one image URL, one WAV audio URL, a prompt,
quality `mid` or `high`, duration 5, 10, or 15 seconds, and an optional seed.
The generic V2 response carries a request ID, status URL, cancel URL, and final
video URL and polls `/requests/{request_id}/status`.

That SDK contract does not prove this authenticated account may call Speak.
The inspected CLI authentication does not supply the separate SDK API-key
credentials needed for a non-generating entitlement check. Cost, exact 9:16
dimensions, voice fidelity, re-encoding behavior, and any ambient-audio behavior
remain unproved. Speak accepts an uploaded Soul-generated image structurally,
not a Soul ID directly, and is not an active production recipe.
