# Research 01 — Instagram/Threads Duplicate Detection & Throttling (2026)

> Source: owner-supplied deep research, 2026-06-18. Feeds the **anti-shadowban safety track** of `INTELLIGENCE_AUDIT.md`. Full text below; actionable extract first.

## Actionable extract (what Codex should build to)

**Real threshold targets** (variants must clear these to be safe — these are MATCH thresholds, so safe = the other side):
- **PDQ (still-frame, 256-bit):** Hamming **≤30 = likely copy**, **31–40 = gray zone** (still risky with supporting signals), **>40 = unlikely same**. → **Target PDQ Hamming > 40** vs master AND every sibling to be clearly safe (not just >32 as the audit first guessed). Confidence: High.
- **TMK+PDQF (video sequence):** phase-1 cosine **≥0.7** and phase-2 **≥0.7** = candidate match. → **Target < 0.7** on both. Confidence: High (Meta open-source + AFP eval).
- **SSCD (embedding copy detect):** no Meta-published Instagram cutoff; downstream convention **~0.70 cosine = copy**. → **Target SSCD cosine < 0.5** (conservative). Confidence: Medium for use, Low-Med for threshold.
- **Audio fingerprint:** separate layer (DCT-based, Meta patent). Reused/lifted audio matches **independently of visuals**. No public scalar. → per-account audio distinctness is mandatory, not optional.

**Two findings the code audit didn't capture:**
1. **Cosmetic visual edits may not count as a "material edit" at all.** Meta's creator policy: watermark / stitch / trivial trim / superficial overlay = NOT materially edited. Narration / storyline / graphics that re-contextualize = material. → Our editorial deltas (tempo/saturation/crop offsets) are exactly the "superficial" class. Visual nudges that move PDQ are necessary for hash-distance but are **not** what Meta rewards as original. Genuine distinctness must include re-contextualization: real per-account caption/hook/audio/framing differences, not just pixel nudges.
2. **Multi-account same-window posting is the escalation trigger** from content-throttle → account-level suppression. Inference bands (Meta does NOT publish exact numbers; directional confidence Medium, exact counts Low):
   - 1 account, no material edit → Reel-level throttle plausible.
   - 2 accounts, short window, same audio + similar caption → throttle likely + account-linkage review.
   - **3+ linked accounts within hours–1 day → high risk of account-level discovery suppression + anti-spam friction.**
   - Continued after warnings → restriction/disablement.
   → Our cadence is conservative *per account* (good), but **cross-account spread over days** matters more than the 12-min same-day spacing we have. Spread sibling posts across days, add per-account day-of-week jitter.

**Implications for the remediation:**
- Gate on PDQ/SSCD/TMK (the layered stack), not SSIM — and use the real bands above.
- Sibling-vs-sibling perceptual pass before fan-out (cross-account is the actual risk).
- Per-account audio + genuinely distinct captions are first-class, not afterthoughts.
- Cross-account schedule spread (days, not minutes) as an anti-coordination measure.
- Capture-metadata rewrite helps decouple uploads, but **device/account linkage is account-level** — can't be fully spoofed away, reinforcing "legit variation + spread," not "hide it."

**Detection stack (what we're defeating):** PDQ (still frames) + TMK+PDQF/vPDQ (video sequence) + SSCD (embeddings) + audio fingerprint, then candidate-rank → sequence verification → policy classification (recommendation-ineligibility → harder-to-find → restriction/disablement). Text/caption near-dup + hashtag overlap + timing/device metadata are corroborating/coordination signals, not the primary media classifier.

---

## Full research text

# Instagram and Threads Duplicate Content Detection and Throttling as of 2026

## Executive summary

Meta publicly documents the *policy outcome* more clearly than the *scoring internals*. For Instagram, the official posture is now explicit: content that is not original or is only minimally changed is less eligible for recommendation, and repeated violations can make an account and everything it posts harder to find. Meta's creator-facing guidance says simple stitching, watermarking, or light reuse does **not** count as "material edits," while meaningful narration, storyline, or graphics that re-contextualize the source do. In April 2026, Instagram expanded those originality protections from Reels to photos and carousels, which strongly implies that the underlying anti-repost controls for Reels were already operational before that expansion. Threads uses the same Community Standards and broadly similar integrity infrastructure, but its public guidance is oriented more toward conversation quality and less toward media originality; the public record is therefore thinner for Threads-specific duplicate-Reels-style enforcement.

On the media-matching side, the strongest public evidence is that Meta uses a layered stack rather than one hash alone: PDQ for still images, TMK+PDQF and related frame-based/video hashing for videos, SSCD-style embedding retrieval for stronger near-duplicate image copy detection, and separate audio fingerprinting for soundtrack matches. Meta officially open-sourced PDQ and TMK+PDQF in 2019 and described them as part of the suite it uses at Facebook to detect identical and nearly identical photos and videos; the ThreatExchange repository also exposes vPDQ, a frame-sharing video matcher. Meta's SSCD paper, authored by Meta AI, explicitly frames image copy detection as a content-moderation problem at web scale and uses cosine-similarity-based descriptors rather than binary Hamming-distance hashes. Meta patents further show a multi-stage matching design for uploaded videos in a social network: candidate generation from frame and audio fingerprints, ranking by matching segments, and then sequence-level verification.

The best-documented numeric thresholds are **PDQ Hamming distance around 30 to 31** and **TMK+PDQF phase thresholds of 0.7 / 0.7**. Public evaluations of PDQ repeatedly use a 30-ish ceiling as the "working threshold," while Meta's own open work and downstream evaluation of TMK+PDQF use 0.7 as the recommended threshold for both its coarse and fine similarity phases. For SSCD, Meta's public paper does **not** publish a universal Instagram deployment cutoff; it explicitly emphasizes that copy detection needs a threshold but evaluates performance as a thresholded retrieval problem rather than prescribing one global constant. Public downstream SSCD users often binarize copy at cosine similarity around **0.70** for a "copy" decision, but that is an ecosystem convention, not a Meta-published Instagram cutoff, so confidence there is only **low to medium**. Audio thresholds are more opaque still: Meta patents disclose DCT-based audio fingerprinting and segment-based candidate scoring, but not a public scalar cutoff used in production moderation or originality enforcement.

For enforcement, the public record supports a clear distinction between **reach throttling** and **harder sanctions**. Reach throttling is the platform's official "recommendation ineligibility / harder to find" layer: content that is low-originality, unoriginal, or otherwise non-recommendable is filtered out of recommendation surfaces such as Explore and, for repeated offenders, the account itself can become harder to find in search and recommendation surfaces. Harder sanctions are tied to spam, inauthentic behavior, evasion, and accumulated violations: Meta's standards say continued violations despite warnings and restrictions can disable an account, and its spam policy says it can restrict accounts even at lower frequencies when other indicators exist, including repetitive content and signals of coordination. "Hard shadowban" is not a Meta term; the closest official equivalents are **recommendation ineligibility**, **search demotion / harder to find**, **feature restrictions**, and ultimately **account disablement**.

The most defensible operational inference is this: **media similarity alone usually explains distribution loss; media similarity plus behavior/network signals explains account-level suppression**. In other words, a single reposted Reel is most likely to lose recommendation eligibility on content surfaces, but reposting the same or near-same Reel across multiple linked accounts inside a compressed time window, with repetitive captions/hashtags and coordinated posting patterns, moves the problem from "unoriginal content" toward "spam / inauthentic behavior." Public Meta materials do confirm rate limits, repetitive-content restrictions, cross-account coordination enforcement, and use of metadata/behavioral signals in anti-abuse systems, but they do **not** publish the exact account-count, time-window, or device-link thresholds used on Instagram or Threads. Any numeric escalation bands for multi-account reposting therefore remain informed inference rather than documented policy.

## Documented matching stack for Reels

For Reels, the public evidence points to four distinct matching layers. The first is **still-frame perceptual hashing**, where PDQ produces a 256-bit image signature and compares candidates by Hamming distance. The second is **video hashing / sequence similarity**, where TMK+PDQF and vPDQ use frame-level similarity aggregated over time. The third is **embedding-based copy detection**, where SSCD produces dense descriptors compared with cosine similarity or equivalent L2 distance. The fourth is **audio fingerprinting**, which Meta uses in Rights Manager and in patents describing uploaded-content matching inside a social network. This layered design fits both the technical problem and the enforcement problem: Reels are multimodal objects, so robust near-duplicate detection cannot rely only on pixels, only on audio, or only on captions.

For image-like matching inside a Reel, **PDQ** remains the most directly published Meta primitive. Meta describes PDQ as a 256-bit photo hash, and public evaluation shows it is strong against format changes and moderate text overlays but brittle to heavier cropping and rotation unless extra transformed hashes are generated. That makes PDQ a good first-pass frame matcher or prefilter for video systems, but not a sufficient sole detector for adversarial reposting. On standard transformations, public evaluators found that a working PDQ threshold near **30** still catches almost all simple format changes and most moderate text edits, while cropping pushes the distance beyond that threshold very quickly.

For true video-level matching, Meta publicized **TMK+PDQF** as its open-source video-matching system and later exposed **vPDQ** in ThreatExchange as a simpler approach based on shared similar frames. The Australian Federal Police evaluation of Meta's open release reports TMK+PDQF as a two-phase matcher, with cosine similarity in phase one and a refined phase-two score, and uses the authors' recommended threshold of **0.7** in both phases. That is the clearest public numeric cutoff in Meta's video-matching ecosystem. The same evaluation also shows why video-level matching matters for Reels: bitrate changes, format changes, and downscaling stay comfortably above threshold, but title cards, inserted segments, and some watermarks can push scores below it.

For stronger near-duplicate retrieval than binary hashes, Meta AI's **SSCD** is the most relevant public model. The SSCD paper explicitly says image copy detection is important for content moderation and describes a two-stage operational setting where a retrieval threshold decides which candidates move forward. SSCD descriptors are compared with cosine similarity or equivalent L2 distance, and the paper also documents score normalization against a background distribution to stabilize thresholds across queries. What the paper does **not** do is publish a single universal production cutoff for all copy-detection deployments. That omission matters: any claim that "Instagram uses SSCD at exactly X" would overstate the public evidence. The best-supported conclusion is that SSCD-type descriptors are plausible and technically aligned with how a large-scale repost detector would work, but exact deployment and thresholds on Instagram or Threads are **unspecified**.

Audio is handled separately. Meta's Rights Manager help materials say the system protects **audio and video** on Facebook and Instagram and makes matches between reference files and user uploads according to rights holder rules and actions. A Meta/Facebook patent on "systems and methods for identifying matching content in a social network" says an uploaded content item can be processed by an **audio fingerprinting service** and specifically points to a **DCT-based** audio fingerprinting approach for distorted audio. The same patent shows that those audio-matched segments can be used to rank candidates alongside video matches. That is good evidence that soundtrack reuse in Reels can be detected independently of visual reuse, but the public record does not reveal the exact fingerprint family or threshold Meta uses for non-Rights-Manager originality enforcement.

### Algorithm and threshold reference table

| Layer | Method | Score | Cutoff | Reels application | Confidence |
|---|---|---|---|---|---|
| Visual still-frame hash | PDQ (256-bit) | Hamming distance | ≈30–31 working threshold | Keyframe/thumbnail/poster-frame candidateing; lightly edited copies | High |
| Video sequence hash | TMK+PDQF | phase-1 cosine; phase-2 score | 0.7 / 0.7 | Near-dup Reels when re-encoded/rescaled/lightly overlaid | High |
| Video frame-share | vPDQ | shared similar frames | no public Meta cutoff | "Shared frames" evidence two Reels share source | Medium |
| Embedding copy detect | SSCD | cosine / L2 | no official cutoff; ~0.70 downstream | Semantically near-identical frames that defeat simpler hashes | Med use / Low-Med threshold |
| Audio fingerprint | DCT-based (patent) | segment match | unspecified | Reused soundtrack/lifted audio matches independent of visuals | Med existence / Low threshold |

Patent detail: in a 20-second segment sampled at 1 fps, items scoring **≥6 matching frames** become candidates for post-processing, then sequence-level smoothing + frame-by-frame verification. Clearest public segment-level candidate gate, not proof of present Instagram production thresholds.

## Text, hashtags, and metadata signals

Meta's matching technology operates on URLs and text too, identifying exact/near-identical copies with minor modifications — but that's stated in an enforcement context for previously-identified violating content, not the originality/reach context. No public doc says caption similarity alone triggers an "unoriginal content" flag. Best reading: text similarity is available and likely a corroborating signal; media matching remains the primary classifier for Reels. Hashtags: signals in search/discovery + network-analysis features for coordination; unlikely the core duplicate detector, likely a feature in spam/coordination scoring. EXIF/geotags/device IDs/timestamps: metadata + device linkage plausibly used for anti-abuse/account correlation; no public proof EXIF/geotags are a primary duplicate-match feature (EXIF often stripped on share). Upload timing is well-supported: rate limits are public, and spam policy can restrict accounts at lower frequencies when repetitive content + coordination signals are present.

### Non-media signals — known/unknown

| Signal | Reading | Confidence |
|---|---|---|
| Captions/text similarity | Available; corroborating, not the main originality detector for Reels | Medium |
| Hashtag overlap | Useful for coordination/spam linkage; no standalone originality threshold | Low-Medium |
| EXIF/geotags | Possibly visible at ingest; no proof of primary role in dup matching | Low |
| Device IDs/camera linkage | Plausible strong account-linkage when same media across many accounts | Medium |
| Upload timestamps/bursts | Very likely important in escalation content→account action | High |

## Reach throttling versus harder sanctions

Official labels for low-med tier: **recommendation ineligibility / harder to find / reduced distribution** (platform-managed reach throttling). Next tier: **account-level discovery suppression** — repeated non-recommendable/unoriginal posting → account + its content harder to find in Explore/Search/suggested. Final tier: **integrity enforcement** — feature restrictions, disabling, removal for spam/inauthentic behavior/evasion/repeat infringement. Multi-account repost networks are riskier because once behavior looks coordinated/evasive, enforcement basis broadens from originality to integrity.

### Enforcement matrix

| Outcome | Official label | Trigger | Not specified |
|---|---|---|---|
| Lower reach on the Reel | Recommendation ineligibility / reduced distribution | Reused/minimally-changed media; no material edits | Exact similarity score |
| Account + posts harder to find | Harder to find in Explore/Search/suggested | Repeated non-recommendable/unoriginal posting | How many repeats, what window |
| Temp restrictions/friction | Restrictions/rate limits/feature limits | Repetitive posting + spam/coordination indicators; posting too fast | Internal rate-limit numbers |
| Disablement | Disabled / account integrity action | Continued violations after warnings; evasion; fake networks; repeat IP abuse | Account-count/linkage/recidivism rules |

## Actionable thresholds and inference bands

Documented technical: PDQ Hamming ≤30 = likely copy; 31–40 gray; >40 increasingly unlikely same. TMK+PDQF phase-1 ≥0.7 & phase-2 ≥0.7 = candidate match. SSCD ~0.70 cosine downstream "copy-like" (not Meta-blessed). Audio: no public scalar.

Policy threshold (structural, not numeric): watermark/stitch/trivial-trim/superficial-overlay = NOT materially edited; narration/storyline/creative-graphics re-contextualizing the source = material. Clearest line between "same-source Reel, likely throttled" and "derivative but newly authored, more defensible."

Multi-account bands (credible inference, NOT published; Medium directional / Low exact):

| Scenario | Likely result |
|---|---|
| Same/near-same Reel, 1 account, no meaningful edits | Reel-level throttle plausible; account penalty less likely first time |
| Same/near-same, 2 accounts, short window, same audio + similar caption | Throttle much more likely; account-linkage review plausible |
| Same/near-same, 3+ linked accounts within hours–1 day | High risk of account-level discovery suppression + anti-spam friction |
| Repetition continues after warnings/IP complaints | Severe restriction/disablement |

## Instagram vs Threads

Instagram's originality framework is mature/explicit (recommendation guidelines, originality rules, account-status visibility, April 2026 expansion to photos/carousels). Duplicate-Reels enforcement is much more legible on IG. Threads shares Meta's standards but public guidance emphasizes conversation quality, replies (≈half of views), posting frequency, and original-for-Threads content; no public Threads equivalent to IG's originality page. Threads dup-suppression more likely via copypasta/spam/CIB treatment than a distinct "reused Reel" penalty.

## Limitations

Meta does NOT publicly disclose production thresholds or ensemble weights. Weakest parts of the record: exact SSCD cutoffs, audio-match thresholds, EXIF/geotag role in present originality enforcement, exact account-count/time-window rules for cross-account cascades. Multi-account bands are credible inference grounded in policy/patents, not documented constants.
