# Research 02 — Detection Thresholds & Account Clustering (2026)

> Owner-supplied research. Distilled to load-bearing specs. Pairs with `01`. Feeds INTELLIGENCE_AUDIT Track S.

## Hard numbers (from Meta's open-source T&S code — best public proxy, NOT production spec)

| Algorithm | Match criterion | Status |
|-----------|-----------------|--------|
| **PDQ** (image, 256-bit DCT) | Hamming **≤31** / 256 = match; discard quality **≤49**; random pairs ~128 | Documented reference threshold |
| **SSCD / SimSearchNet++** (deployed on FB/IG) | cosine **≥0.75** → copy @ ~90% precision (`sscd_disc_mixup`; ≡ Euclidean <0.7); 512-dim L2-norm descriptor | Documented reference model; **production family** |
| **TMK+PDQF** (video, 15fps, ~256KB sig) | cosine **≥0.7** both phases (1KB level-1 + 256KB level-2) | Documented threshold |
| **vPDQ** (clip-in-video) | per-frame ≤31, quality ≥50, **≥80%** frame overlap (example params); matches subsequences | Documented example |
| **Audio** | Rights Manager + **Audible Magic** (3rd-party); flags + blocks on match | Documented existence; no public scalar |

Meta states TMK "is not — nor has it ever been — Meta's primary video matcher"; production matchers are proprietary and likely tighter + human-reviewed. SSCD lead author: "SimSearchNet++ is deployed on Facebook and Instagram." So the deployed copy-detector is **descriptor-based (handles crop/color/text-overlay/screenshot)**, not just hashing.

## The binding constraint: account clustering

Meta links accounts at the *user* level (which is why an IG strike suppresses the same person's Threads reach). Documented/reported clustering signals: **IP, device/browser fingerprint (canvas/WebGL/fonts/resolution/timezone), cookies/pixels, shared phone/email, shared payment method, behavioral/temporal patterns** (identical posting times, session rhythm). Mobile apps fingerprint device sensors browsers can't mask. Meta actioned ~687M–1.1B fake accounts/quarter in 2025, mostly via fingerprint + behavioral clustering.

**Multi-account post-farming stacks 3 independent layers:** (1) content matcher (PDQ/SSCD/vPDQ/audio) recognizes same source across accounts; (2) account clustering links accounts to one operator; (3) unoriginal/spam policy demotes/removes. Same-audio + same-caption accelerate the flag. Coordinated-inauthentic-behavior takedown can remove the **whole network at once** — a ban, not a throttle.

## Policy thresholds & timeline

- **10+ unoriginal posts in 30 days → non-recommendable** (IG Reels, Apr 2024; expanded platform-wide to photos/carousels **Apr 30 2026**). Duplicate replaced by original in recs; reach reduced account-wide; repeat offenders demonetized. Recovery ~30 days of original posting.
- Trivial edits Meta names as **insufficient**: "adding borders, inserting captions, and changing the reel's speed." Material = voiceover, storyline, graphics that re-contextualize.
- Other signals: caption/text near-dup hashing (Meta patent, MD5 + near-dup), recycled caption/hashtag blocks = spam trigger. C2PA/IPTC = labeling not clustering, and IG recompresses/strips C2PA on upload (not a reliable cross-account key).
- Threads: runs on IG's moderation backend; inherits guidelines; weights unoriginal/duplicate **more aggressively** (reposts/screenshots suppressed harder); reduced-distribution episodes ~7–14 days.

## Enforcement tiers
1. **Reduced distribution / recommendation-ineligible** (soft, common): unoriginal/trivial-edit/watermarked/recycled-caption/near-dup → out of Explore/Reels-feed-for-non-followers/Suggested; still visible to followers. Surfaced in Account Status → Recommendation eligibility. Diagnostic: non-follower reach collapses 30–60% → <10%.
2. **Account-level**: repeated unoriginal → account-wide reach cut, demonetization, fully non-recommendable.
3. **Integrity**: coordinated-inauthentic-behavior / IP / evasion → removal/disablement of the cluster.

## Honest takeaway for a multi-account operator
The only durable, policy-compliant version is **genuinely distinct content per account** (different footage, edits, audio, captions, cadence) with legitimately separated identities — which is most of the cost of just making original content. Hash-uniquification alone fails because clustering + policy operate independently of the hash.
