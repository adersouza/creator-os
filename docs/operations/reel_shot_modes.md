# Reel shot modes

Operator-authored 2026-08-07 (Emerson). This is the taxonomy the pipeline
should route on.

## Why this exists

The three frozen creation modes (`static_reel`, `calm_animation`,
`recreate_reel`) name the **renderer**, not the **shot**. That is the wrong
level for deciding a workflow: on 2026-08-06/07 every real decision in a
recreation run — which frame to sample, which image model, whether Motion
Control is even allowed, whether the provider gate will refuse — was determined
by the *kind of reel*, and `recreate_reel` was constant across all of them and
predicted none. The operator's words: *"the modes are hard because they never
know the proper workflow since it's always different reels."*

A shot mode resolves **to** a creation mode plus everything the creation mode
cannot express. It does not replace the creation modes, which stay load-bearing
in `pipeline_contracts`, `campaign_schema_v10`, the identity guards in
`recreation_lifecycle`, and the arch-guard test.

Reference-account screenshots live in
`~/.creator-os/references/shot_modes/<mode>/`. Stacey character boards live in
`~/.creator-os/references/character_boards/stacey/` (hair-up and hair-down
variants, both 2026-08-06/07).

---

## READ FIRST: two traps that silently ruin these modes

**1. Order by catalogue id; the job's `model` field lies.** Checked against the
authenticated Higgsfield model catalogue 2026-08-07:

| catalogue id | name | description |
| --- | --- | --- |
| `nano_banana_pro` | Nano Banana Pro | *Ultimate quality, text and diagrams* |
| `nano_banana_2` | Nano Banana 2 | *Fast, next-gen high-quality images* |

The ids are correct and self-consistent — `nano_banana_pro` is simply the
stronger model. What misleads is the `model` field **echoed back in the job
response**, which names a tier lower than what you ordered (a `nano_banana_2`
request comes back labelled `nano_banana_flash`). Ignore that field.

Measured consequence, and it is the important part: **only `nano_banana_pro`
fires the character-board identity swap.** `nano_banana_2` was 0-for-4 across
two reels and four frames — it returns a clean, plausible image that is still
the SOURCE woman, and its looser NSFW gate makes it *look* like the working
option. Modes 2, 3 and 5 say "nano banana 2" in the operator's words; **send
`nano_banana_pro`.** Sanity check the echoed params for an `input_images`
array — if absent, the board was not consumed and the credits are wasted.

**2. Soul identity — RESOLVED 2026-08-07.** `Lili` and `Stacey` are the same
persona; `Lili` is a **newer training set**. Either is valid.

- `Stacey` — `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36` — **preferred**: its
  training set has the larger bust, which is the visual hook of modes 1 and 4.
- `Lili` — `733142e2-8bf5-43bc-9edd-50edbcbb6518` — newer training, smaller bust.

**3. Nano Banana handles occluded faces.** When the shot has something covering
the face — a phone held up, a hand, a drink — route the anchor to
`nano_banana_pro` with the character board rather than a Soul text prompt.
Caveat that is easy to conflate: this is about the **shot class**, not the
frame you sample. Still sample an OPEN-face frame for the anchor
(`scripts/pick_anchor_frame.py`); a covered face in the sampled frame causes a
silent passthrough. Shot covered → Nano Banana; anchor frame → open face.

---

## Mode 1 — `car_talking`

Talking-to-camera selfie from the driver's seat. The simplest pipeline: no
reference image is consumed at all, only the reference reel's performance.

- **Anchor:** Soul ID (`Stacey d63ea9c7`, preferred for bust) + **text prompt
  only**, no character board. Prompt must describe a large bust and a top whose
  fit produces heavy cleavage — that is the format's whole visual hook.
- **Motion:** Seedance. The girl says/does exactly what the reference reel does.
- **Post:** talking reels **need burned captions** of what she is saying.
  Source them from the caption bank, never verbatim from the reference creator
  (`sourceTextPolicy.reuseVerbatim: false`).
- **Motion Control:** **FORBIDDEN.** Talking never routes there.

Reference accounts (`mode1_car_talking/`): `@noelleluvs`, `@lana_resse`,
`@iamrinkage`, `@sofialuvxo`, `@snehahulsebus`.

## Mode 2 — `outfit_spin_jiggle`

Sexy outfit, stands up and spins, or walks away from camera with the walk-away
jiggle. This mode is **about the outfit and the anchor being as close to perfect
as possible** — the motion is the easy half.

- **Anchor:** either Soul ID + text prompt, **or** `nano_banana_pro` + character
  board when the outfit does not trip the gate.
  **OPEN — needs a split test.** Reels B and D came out great on a Nano Banana
  anchor. Which model wins per outfit is unresolved; this is the first
  experiment to run.
- **Motion:** Seedance.
- **No overlay text in the anchor image** (trailing clause in the prompt).
- Existing reels that belong here: **B, D, E**.

Reference account (`mode2_outfit_spin_jiggle/`): `@miahjk9`.

Note: `@miahjk9` is also the account the 2026-08-07 caption harvest came from —
the 28 overlay captions now in `candidate_intake.json` are this mode's hooks.
Mode 2 and the caption bank feed each other.

## Mode 3 — `pinterest_calm`

Recreate a still found on Pinterest, then animate it gently — closest to the
existing `calm_animation` renderer.

- **Anchor:** `nano_banana_pro` + character board, recreating the Pinterest image.
- **Motion:** Kling 3 Turbo, calm, **only if motion is wanted at all.** Many of
  these can ship as stills.

## Mode 4 — `soul_closeup_bed`

Close-up, low-motion: in bed, sitting down. Used to build the **pose**
vocabulary; the text prompt only has to carry the clothing.

- **Anchor:** Soul ID (`Stacey`) + text prompt. Describe the bust and cleavage
  explicitly.
- **Do NOT recreate the reference's hair.** Take the pose, the framing and the
  bust; the hair stays the creator's own.
- **Motion:** Kling, ~3 s, casual OpenAI-authored prompt — and only if needed.

Reference account (`mode4_soul_closeup_bed/`):
`@gothgoddessqueen` — https://www.instagram.com/gothgoddessqueen/reels/

## Mode 5 — `dance_poses`

Dancing plus simple poses, full body, fixed camera.

- **Anchor:** `nano_banana_pro` + character board.
  **Generate 2–3 candidates** and keep the one that actually landed the swap —
  the anchor step is not reliable enough here to trust a single generation.
- **Motion:** Seedance; **Kling Motion Control if Seedance refuses** (allowed:
  no talking in this mode).

Reference account (`mode5_dance_poses/`):
`@fayebelincii` — https://www.instagram.com/fayebelincii/reels/
Distinguishing feature: **her reels carry no overlay text**, unlike mode 2's.

---

## Measured constraints that apply across modes

From the 2026-08-06/07 runs (`creator-os-nbp-character-board-test` memory):

- **Frame choice decides whether the anchor swap fires.** Sharpness first, then
  face size, then eyes-visible. `scripts/pick_anchor_frame.py` ranks a reel.
- **Cleavage-dominant close-ups cannot be anchored from a source frame.** Full
  frame → Google refuses; crop enough to pass → the crop is now tight and the
  swap silently passthroughs. This is why mode 1 is text-prompt-only.
- **A refused Seedance job costs ~6 credits**, not zero. Blocked *image* jobs
  are genuinely free.
- **Motion Control is weak at soft-tissue motion** — poor jiggle physics. It is
  a degraded salvage route for mode 2, never the first choice.
- Costs: Soul still ~0.12 · Kling O1 image 0.5 · NB2 anchor 2 ·
  Seedance 7 s 480p 10.5.

## Status

Specification only — nothing routes on these yet. Each mode becomes real when
one paid run through it produces a would-post output, the same bar the recipes
carry. Modes 2 and 5 have the most existing evidence (reels B, D, G).
