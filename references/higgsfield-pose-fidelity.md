# Higgsfield Soul 2.0 — Pose & Body-Proportion Fidelity

Source of truth for pipeline prompt generation. Verified against live MCP schema 2026-02.

## Live MCP surface (`soul_2`) — verified via models_explore
- Params: `prompt`, `soul_id`, `quality` (`1.5k` | `2k`, default `2k`), `aspect_ratio`, `count` (1–4)
- Media: exactly 1 image input, role `image` (pose/composition reference)
- Aspect ratios: `1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3`
- NOT exposed on MCP: `seed`, `enhance_prompt`, `custom_reference_strength`, `style_id`, `batch_size`
  (those exist only on CLI/Segmind/WaveSpeed surfaces — ignore any advice requiring them here)

## HARD RULE: NO NEGATIVE PROMPTS (owner-confirmed + verified 2026-07-09)
Soul V2 is positive-only. "no X / without X / avoid X" INJECTS X as a concept and renders
MORE of it (proven: "no story bar / no username" produced worse fake UI). Owner confirms
this from their own generations — negatives do more harm than good.
Rule: describe ONLY what you want in frame. To remove something, don't name it — reframe.
(Fix an unwanted app-UI band with "A photograph of ..." framing, NOT "no UI". Fix a bad
limb by describing the desired hand placement, NOT "no extra fingers".)

## Hierarchy of levers (highest impact first)
1. **Training set** — Soul trained on 20–30 recent, consistent photos incl. several full-body/full-height
   shots of target proportions. soul_id locks FACE strongly, body only weakly; training set is the body ceiling.
2. **Reference image every generation** — the only real pose lever. Recreates composition/lighting/vibe,
   NOT skeleton-exact. Identity (soul_id) wins for face; reference wins for pose/framing.
3. **Fixed body-descriptor clause** — repeat the matching BODY AMP BLOCK (see below) front-loaded
   in every spicy gen. Butt axis: `tiny waist, big round bubble butt with full projected glutes,
   thick thighs`. Cleavage axis: `much larger fuller breasts with deep prominent cleavage`.
   NEVER use "wide hips" (widens the whole pelvis).
4. **Self-reference chaining** — feed best output back as image ref to hold proportions across a series.
   Re-anchor to a curated hero image every ~3–5 gens to prevent compounding drift.
5. **Framing** — 9:16 (reels/stories) or 3:4 (feed) + "full body visible head to toe" for silhouette shots.
   1:1 crops hide hip-to-waist ratio.
6. **Escalation** — Nano Banana Pro edit/inpaint pass only when pose must be exact or anatomy errors recur.

## Prompt template
```
[SHOT TYPE], [CAMERA ANGLE], shot on [LENS],
a woman with [BODY AMP BLOCK for the axis — butt or cleavage], long dark hair,
[POSE: weight distribution + limb placement], [ARM/HAND PLACEMENT per hand-safe rules],
[TORSO ROTATION], [GAZE],
wearing [OUTFIT], in [SETTING], [LIGHTING],
[MEDIUM: amateur iPhone photo / digital camera / film grain],
full body visible head to toe
```
- Keep ≤~75 words for identity-critical work; overloading dilutes identity anchor
- Bake style into prompt text ("amateur iPhone photo" tested well) — no style presets on MCP
- Pose language = photographic, not keypoints: "weight shifted onto right hip, left knee bent,
  torso turned three-quarters, looking over shoulder"

## Failure modes
| Failure | Fix |
|---|---|
| Slim-default drift | Body clause every call + curvy full-body training set; prompt alone won't fix face-heavy training |
| Descriptor ignored in long prompt | Shorten; move body clause to front |
| Extreme angle/crop drift | Stay within training-set angles; re-anchor via image ref |
| Anatomy errors (limbs) | Regenerate count=4 and cherry-pick; escalate to Nano Banana edit pass |
| Series drift | Hero-image re-anchoring |

## Per-shot settings
- `count: 4`, cherry-pick best
- `quality: 2k`
- `aspect_ratio`: 9:16 reels / 3:4 feed
- Reference frame attached as the single image media whenever recreating a pose

## WINNING SEXY STYLE (proven — reuse this as the default look)
Reference: hf_20260701_063755 (owner-approved as "really sexy"). The formula that
beats bright daylight full-body gens:

1. **Low-key WARM lighting, no flash.** Single practical light (bedside lamp), dim room,
   crushed shadows, chiaroscuro so chest/face are lit and the rest falls to dark.
   This is the biggest lever — dim warm > bright daylight for spice.
2. **Wardrobe carries the spice, not the pose.** Deep-plunge / zip-front bodysuit,
   corset, plunge neckline. Amp the garment, keep the pose relaxed.
3. **Chest-forward tight framing.** Slight low angle, subject fills 9:16, neckline is the
   focal center. Not full-body-far.
4. **Moody warm grade + low-light grain.** Amber/brown, low-key, phone-in-the-dark
   authenticity. Never studio-clean.
5. **Sultry direct gaze, lips slightly parted.** Intimate, not posed-stiff.
6. **One grounding detail.** Necklace, red nails on the phone, jewelry.

VERIFIED WINNING PROMPT (job a47b8284, soul "Stacey" d63ea9c7, text-only, enhance OFF, seed 284543):
`A grainy amateur low-light phone selfie in a dim bedroom lit by a warm lamp and a
flickering candle. A woman, at least 20 years old, with long dark wavy hair, seductive
half-lidded eyes and parted lips, holds an iPhone at arm's length. She wears a structured
black corset top revealing much larger fuller breasts with deep prominent cleavage. Tight
crop on face and upper torso, subtle film grain, warm amber-and-black palette, intimate mood.`

Technique decoded from the winner:
- text-only + enhance_prompt OFF (hand-authored; enhance would rewrite/soften it)
- moderation-safe age phrase: "a woman, at least 20 years old"
- explicit body amp: "much larger fuller breasts with deep prominent cleavage"
- lighting named as practicals: "dim bedroom lit by a warm lamp and a flickering candle"
- "grainy amateur low-light phone selfie" + "subtle film grain" = authenticity
- "tight crop on face and upper torso" = chest-forward framing
- "warm amber-and-black palette, intimate mood" = the grade

Confirmed across 3 owner-approved winners (job a47b8284 + 2 more, 2026-07): all share
warm lamp/candle bedroom · plunging matte BLACK top · cleavage prominent · tight face+
upper-torso crop · high-angle selfie · warm neutral tan/brown/black palette · shallow DOF
· intimate mood. The two enhanced-format winners share the SAME 13-value hex palette
(#140f0c #36281d #3c2f24 #1b130f #0f0907 #2e1e14 #74513f #452d20 #634331 #4f3829
#855f4b #98715d #605953) — the signature warm-dark grade.

Fail patterns to avoid (my earlier weak gens): bright flat daylight, modest full
lounge sets, full-body-far framing, studio-clean skin. Opposite of the winner.

KNOWN BUG in clean_prompt (2026-07): strips target words but leaves grammar wreckage —
dangling adjectives ("long, tousled." after hair-color strip), mid-phrase cuts
("modern smartphone" -> "modern, exhibits"), broken "appears to be" clauses. Prefer
hand-authoring from the VERIFIED WINNING PROMPT above over sanitizing enhanced captions
until clean_prompt orphan-cleanup is fixed.

## GOLD REFERENCE DATA (source of truth for styles — 225 gold labels)
DB: `/Users/aderdesouza/Developer/reference_reels/reference_factory.sqlite`
- Gold labels: `review_labels` WHERE label='gold' (225 rows). Join `source_files` on
  reference_id for the mp4 path + account.
- **Pre-extracted frames already exist**: `reference_reels/frame_samples/<ref_id>/contact.jpg`
  (+ hook_1s.jpg). Read these to study a style — no ffmpeg needed.
- Query one gold contact sheet per account:
  `SELECT rl.reference_id, sf.account FROM review_labels rl JOIN source_files sf USING(reference_id) WHERE rl.label='gold';`

Gold spread by account: BabyyMimiii_ 89, cakedlucien 67, lunarose.vibes_ 40,
nayabarbiee 27, itsnadorlily 1, evonica.black 1.

## STYLE CATALOG (from gold archetypes — build/test each on soul Stacey d63ea9c7)
- **A Skyline seated** (BabyyMimiii_): floor by floor-to-ceiling window + city towers,
  sports bra, legs wide, cleavage+thighs, bright blue daylight, direct gaze. 9:16.
- **B Airy mirror crouch** (cakedlucien): squat/crouch at closet mirror, neon shorts +
  white tank, wood floor, bright flat, butt from behind, phone visible. 2:3.
- **C Warm bathroom booty** (lunarose.vibes_): standing back-to-cam in warm tiled bathroom,
  arched, look-back smile, black crop+booty shorts, soft window light. 9:16.
- **D Cozy bedroom kneel** (nayabarbiee): kneel on bed, mirror selfie, white bodysuit +
  ruffle shorts, warm lamp + posters, girl's-bedroom cozy. 2:3.
- **E Dark cleavage** (WINNING SEXY STYLE above): dim warm corset selfie. LOCKED.

Spice-axis differs per style: A/E = cleavage; B/C/D = butt. Match the axis to the style.

### BODY AMP BLOCKS (Soul slim-default needs explicit override — verified 2026-07-09)
Weak descriptors ("large round butt") lose to Soul's slim default → butt renders small.
Use the strong amp block for the matching axis, EVERY butt/cleavage gen:
- **BBL butt block** (verified 2026-07-09 — BIG BUTT, NORMAL HIPS): `tiny waist, big
  round bubble butt with full projected glutes, thick thighs` + pose `back arched, big
  butt pushed toward camera, looking back over shoulder`. DO NOT add "wide hips" (widens
  the whole pelvis) OR "slim frame / normal hip width" (unneeded). Just name the butt —
  "projected glutes" gives size from behind without spreading the hips.
- **Cleavage block** (from winner): `much larger fuller breasts with deep prominent cleavage`
Pose note: standing back-to-cam deep-arch look-back and mirror side-arch are the most
RELIABLE (cleanest hands/anatomy) — use as defaults, NOT the only poses. Vary widely:
kneeling, sitting, lying, bent-over-bed, floor, leaning. Squats/crouches are the flakiest —
gen count:4 and cherry-pick when using them. Don't collapse to 2-3 poses; rotate settings,
outfits, and poses to keep a feed looking real.

### FAKE IG/STORY CHROME — the fix is REMOVING trigger words, NOT negative prompts (verified 2026-07-09)
Warm-bedroom shots sometimes render a fake app UI band (story progress bar, username +
avatar, music note, "..." / X, garbled caption text).
- **Soul V2 has NO negative prompts.** Writing "no username, no story bar, no UI" INJECTS
  those tokens as positive concepts and renders MORE chrome. NEVER do this — it backfires.
- **Root cause = framing words.** "amateur phone photo" / "selfie" / "story" / "screenshot"
  make Soul associate with an IG screenshot → it paints the chrome.
- **Fix (verified): drop the trigger words.** Frame as `A photograph of ...` / `A softly
  lit photograph of ...`. Same pink-kneeling-warm-bedroom case rendered 100% clean this way.
- Mirror-selfie styles genuinely need "phone" (the pose holds it) — if a band still leaks
  there, top-crop it (autocrop removes only DARK bars; overlaid chrome on a lit wall needs
  a manual top crop).

### HAND-SAFE POSING (mangled fingers are the #1 defect — verified fix 2026-07-09)
Hands break when fingers are open/splayed/visible. Fix = occlude or occupy BOTH hands:
- Phone-holding hand held up in front of/covering face (fingers hide behind the phone)
- Other hand: flat on hip, flat on butt/thigh, tucked in hair, arm across waist, or OUT of frame
- NEVER: splayed fingers near face, peace sign, both hands fully open, interlaced fingers
- Always gen `count: 4` on hero shots and cherry-pick the clean-hand one (hands are the
  main reason to batch). Salvage an otherwise-perfect shot with a Nano Banana Pro inpaint
  on just the hand region.
Verified: "one hand holding the phone up in front of her face, other hand resting flat on
her hip" produced clean hands + matched the grey-gym-set reference 1:1.

## Ceiling
Higgsfield-only realistic ceiling: "unmistakably same person, same body, closely matching pose" —
not pixel-exact. Consistency is "high, not absolute" — plan to cherry-pick from batches.

Content range: lingerie / bikini / implied is all fair game — no self-imposed "keep it modest"
rule and no age-phrase token. Hard limit is Higgsfield moderation: it rejects explicit/nude at
the API, so the working range tops out at suggestive-but-covered regardless of prompt wording.
