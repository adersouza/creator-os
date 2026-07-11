# ContentForge v5 — Research Documentation

Research compiled April 2026 via Claude Research. Nine deep-dive reports covering the full detection stack that social media platforms use, and how ContentForge's pipeline addresses each layer.

---

## 1. PDQ Hash Fingerprinting (Image)

**What platforms use:** Meta's PDQ (Perceptual Distance Quantization) — a 256-bit DCT hash on a 64x64 grid. Used across Facebook, Instagram, and shared via ThreatExchange.

**How it works:**
- Image downsampled to 64x64 grayscale
- 2D DCT extracts frequency-domain info
- Top-left 16x16 DCT coefficients retained
- 256 coefficients compared to median = 256-bit binary hash
- Match threshold: Hamming distance <= 31 bits (~12% BER)

**Key weaknesses (what ContentForge exploits):**
- 3-5% crop shifts content on DCT grid = Hamming 30-83 bits (crosses threshold)
- Sub-degree rotation defeats crop-invariant neural embeddings
- Color modulation (gamma, saturation, hue) flips DCT threshold bits

**Open-source replication:** `pdqhash` Python package produces identical output to Meta's production system. ContentForge's similarity checker uses this exact package.

**Older algorithms (less relevant):**
- pHash: 64-bit DCT hash, 32x32 downsample — less discriminative at scale
- dHash: 64-bit difference hash — blind to rotation
- aHash: 64-bit average hash — simplest, least robust

---

## 2. Neural Embedding Models (Image/Video)

**What platforms use:** SSCD (Self-Supervised Copy Detection) — Meta's purpose-built model for copy detection.

**Key models:**
| Model | Dim | Copy Detection muAP | Notes |
|-------|-----|---------------------|-------|
| SSCD ResNet-50 | 512 | 0.618 (0.753 normalized) | Best for copy detection |
| CLIP ViT-L/14 | 768 | ~0.30-0.40 | Semantic, not instance |
| DINOv2 ViT-g | 1536 | ~0.35-0.45 | Best dense features |
| ISC21 Winner | 256 | 0.86 | Matching track w/ verification |

**SSCD thresholds (calibrated against DISC2021 benchmark):**
- >= 0.90: near-exact copies (minor augmentation)
- >= 0.75: copy detected (90% precision — Meta's own benchmark threshold)
- 0.50-0.75: similar / modified copy
- < 0.50: distinct content

**ContentForge implementation:** SSCD ResNet-50 (sscd_disc_mixup) loaded via TorchScript, 512-d L2-normalized embeddings, cosine similarity comparison. Model downloaded from Meta's official repo (94 MB). Runs at ~80ms/image on CPU.

**Instagram's 10-repost rule (April 2024):**
Accounts reposting 10+ times in 30 days are removed from all recommendation surfaces (Explore, Reels tab, in-feed suggestions). Content retaining 70%+ of original visual/audio elements gets flagged. The check is binary — pass or fail, no similarity gradient.

**Cross-account target:** SSCD cosine similarity <0.75 between any two posts from same base content across accounts.

**Texture bias exploit (key finding):**
Neural networks rely on texture (not shape) for recognition — opposite of humans. This creates exploitable gaps:

| FFmpeg filter | SSIM impact | Embedding shift | Disproportionate? |
|---|---|---|---|
| `unsharp=3:3:0.8` | > 0.92 | 0.05-0.15 | Yes — looks "crisper" |
| `noise=c0s=8:c0f=t+u` (grain) | > 0.85 | 0.05-0.15 | Yes — barely visible |
| YUV420 chroma round-trip | > 0.95 | measurable | Yes — imperceptible |
| Combined pipeline | > 0.90 | 0.10-0.25 | Yes — crosses threshold |

**ContentForge implementation:** Phase 2 uses increased sharpening (0.5-1.0 vs previous 0.3), temporal+uniform noise (t+u flag), and chroma subsampling.

---

## 3. Video Temporal Fingerprinting

**What platforms use:**
- YouTube Content ID: samples at 1-2 fps (ignores source GOP), extracts ordinal descriptors + temporal gradients, needs 8-10s video match or 3-5s audio match
- Meta TMK+PDQF: projects per-frame PDQ hashes into Fourier temporal basis, cosine similarity >= 0.70
- TikTok: multi-scale temporal extraction, audio-first matching

**Five layers of temporal fingerprinting:**
1. Temporal Ordinal Measurements (TOM) — relative ordering across frame windows
2. Motion vector analysis — extracted from compressed bitstream
3. Scene boundary patterns — shot duration sequences as structural fingerprint
4. Temporal sequence hashing — ordered hash sequences + DTW alignment
5. Audio-visual sync — combined modality matching

**Temporal attacks ranked by effectiveness:**
1. **Non-uniform time remapping** (variable speed curves) — #1 most effective, breaks linear time assumption in DTW/TMK
2. **Scene reordering + per-scene spatial transforms** — attacks temporal AND spatial
3. **Audio replacement/desync** — eliminates strongest single signal
4. **Constant speed changes > +-20%** — exceeds system tolerance
5. **Frame dropping > 20%** — degrades temporal alignment

**Key principle:** Stacking spatial + temporal + audio manipulations has multiplicative (not additive) effect.

**ContentForge implementation:** Non-uniform time warp via sine-wave PTS modulation (amplitude increased to 0.03-0.07), speed shift widened to 0.93-1.07x.

---

## 4. Audio Fingerprinting

**Two foundational approaches:**

**Shazam (constellation maps):** Identifies spectral peaks (15-30/sec) in 300-2000 Hz band, pairs them into 32-bit hashes encoding (f1, f2, delta_t). Match requires 5+ temporally coherent hash hits.

**Philips Robust Hash:** Energy differences across 33 Bark-scale bands = 32-bit sub-fingerprints. Match at BER < 0.35 (Hamming <= 2867/8192).

**Attack effectiveness:**
| Manipulation | Perceptual impact | Fingerprint impact |
|---|---|---|
| Pitch shift +-0.5 semitones | Barely noticeable | 10-30% accuracy loss |
| Pitch shift +-1 semitone | Noticeable | Drops to 30-60% |
| Pitch shift +-2 semitones | Obvious | Effectively broken |
| Time stretch +-5% | Moderate | 50-70% match rate |
| Pitch +-5-8 cents + stretch +-1-2% | Imperceptible (ODG > -0.5) | Substantial disruption |

**Sweet spot:** Combined +-5-50 cent pitch shift + +-1-2% time stretch + psychoacoustically masked noise achieves ODG > -1.0 (transparent quality) while disrupting both frequency and temporal dimensions.

**ContentForge implementation:** Per-variant pitch shifting via `asetrate`+`aresample` (+-50 cents), tempo matching to video speed shift, subtle echo for spectral peak smearing.

---

## 5. Platform Detection Stack (Beyond Content)

**Four-layer detection:**

### Layer 1: Metadata & Compression Forensics
- Platforms analyze EXIF/container metadata server-side before stripping from public files
- FFmpeg's `Lavf` encoder string and x264 UUID SEI are instant tells
- Double compression creates detectable DCT coefficient periodicity
- Container atoms (ftyp, handler_name, timescale) identify encoding software

### Layer 2: Upload Timing
- Burst uploads (5+ in 10 min) trigger shadow-throttling
- Robotic scheduling (same second daily) flags as automation
- No sleep-cycle gap = automated
- Safe rates: TikTok 1-3/day, Instagram Reels 1-2/day, YouTube Shorts 1-3/day
- Minimum 45 min between posts on same account

### Layer 3: Device Fingerprinting
- TikTok collects 40+ device signals via AppLog SDK
- Meta maintains cross-app device graph (IG, FB, WhatsApp, Messenger)
- Multiple accounts from one device share action budgets
- Anti-detect browsers (AdsPower, GoLogin) create isolated profiles

### Layer 4: Network Analysis
- IP classification: mobile (high trust) > residential > VPN (low) > datacenter (blocked)
- ASN analysis identifies hosting/cloud IPs
- Bipartite graph clustering links accounts sharing IPs
- Residential proxy detection via behavioral analysis

### Key operational data (from 293-account network):
- 40-60% account attrition expected
- Zero cross-engagement between own accounts
- Ramp new accounts: 5 posts/day -> 6 -> 7 over first week
- Content similarity score < 0.7 required before publish

---

## 6. Device Container Forensics

**iPhone native recording signature:**
- ftyp: `qt  ` (not `isom`)
- mvhd timescale: 600 (not 1000)
- Video track timescale: 600
- Handler names: `Core Media Video` / `Core Media Audio`
- Bitrate: 20-24 Mbps at 1080p30
- Audio: AAC-LC at 44,100 Hz
- B-frames: 1-2, refs: 2-4
- colr atom: `nclc` type (not `nclx`)
- Apple mdta/keys metadata system

**Android (Samsung/Pixel) recording signature:**
- ftyp: `isom` (same as FFmpeg default)
- mvhd timescale: 1000
- Video track timescale: 90,000
- Handler names: `VideoHandle` / `SoundHandle`
- Samsung bitrate: 17-20 Mbps, Pixel: 12-16 Mbps
- Audio: AAC-LC at 48,000 Hz
- B-frames: 0 (real-time hardware encoders skip these)
- Refs: 1-2

**FFmpeg default (what ContentForge used to output):**
- encoder atom: `Lavf60.x` (instant forensic failure)
- x264 UUID SEI with full parameter string
- Handler: `VideoHandler` / `SoundHandler`
- Bitrate: ~8-12 Mbps at CRF 18-21
- Creation timestamp: epoch 0
- No VUI color metadata

**ContentForge v5 fix:** Per-variant random device profile (iPhone/Samsung/Pixel) with matched bitrate, GOP, B-frames, refs, handler names, audio rate, and color metadata. Uses ABR (like devices) instead of CRF (software tell).

**Still requires post-processing to strip:**
- x264 UUID SEI in bitstream (hardcoded, can't disable via FFmpeg flags)
- Any residual Lavf strings in container

---

## 7. Compression Forensics (Double Encoding Detection)

**Core principle:** Quantization is lossy and non-idempotent — passing through it twice produces statistically detectable artifacts with 93-98% accuracy.

**JPEG double compression detection:**

| Method | What it detects | Accuracy | Tool |
|---|---|---|---|
| JPEG ghost analysis | Per-block error minimization reveals original QF | >90% when delta QF >= 10 | Python (PIL + numpy) |
| DCT histogram periodicity | "Combing pattern" from double quantization grid | DFT peak > 3.0 = suspicious | `jpegio` Python library |
| Benford's law on DCT coefficients | First-digit distribution deviation | Chi-squared divergence | `jpegio` + numpy |
| Quantization table fingerprinting | Software/device identification via QT | Database matching | `exiftool -v3 -QuantizationTable` |

**H.264/H.265 double compression detection:**

| Method | What it detects | Accuracy | Tool |
|---|---|---|---|
| Motion vector Markov statistics | MV transition probabilities differ in re-encoded video | >90% (Su & Li, IEEE SPL 2011) | `ffmpeg -flags2 +export_mvs` |
| GOP periodicity via DFT | Original GOP period persists as frame-size fluctuations | >85% (Bestagini et al. 2013) | `ffprobe -show_frames` |
| Prediction mode distribution | Software encoders explore wider mode space than hardware | >92% for HEVC | `ffmpeg -debug qp` |
| Encoder metadata | Encoded_Library and Encoded_Library_Settings strings | 100% (if not stripped) | `mediainfo --Output=JSON` |

**Key thresholds:**
- delta QP > 6 between passes: readily detectable
- delta QP < 3: challenging (55-65% accuracy)
- Same-parameter re-encoding (QP1 = QP2, GOP1 = GOP2): hardest case — validates ContentForge's approach of randomizing params per variant

**ContentForge mitigation:**
- Randomized CRF/bitrate per variant (avoids same-parameter detection)
- Device-matched GOP structure (30 for Android, 60 for iPhone)
- ABR encoding instead of CRF (matches device behavior)
- Randomized encoding parameters reduce inter-variant correlation

**Available for similarity checker (future):**
- `jpegio` for DCT coefficient analysis on image variants
- GOP periodicity analysis via ffprobe frame data
- Quantization table consistency checking

---

## 8. Instagram/Threads Upload Processing Pipeline

**Key finding: Instagram always re-encodes every upload — no passthrough mode.**

**Image processing:**
- Real optimal upload resolution: **1440px on short edge** (not 1080px)
- JPEG re-compression quality: ~Q70-76 for feed images
- Progressive JPEG with MozJPEG, 4:2:0 chroma subsampling
- Color: forces sRGB — wide-gamut (P3/Adobe RGB) gets desaturated
- All metadata stripped (EXIF, IPTC, XMP, C2PA) — but C2PA read first for AI labeling
- WebP served to compatible clients via content negotiation

**Video processing:**
- Multi-codec ABR: H.264 (basic) → VP9 (advanced) → AV1/SVT-AV1 (premium, 70%+ of Meta video)
- Convex hull optimizer: up to 35 encoding variants per popular video
- Reels: 1080x1920 at 1500-5000 kbps, H.264 High Profile L4.0-4.1
- Audio: AAC-LC 128kbps @ 44.1kHz (Reels/Feed), 64kbps mono (Stories)
- Closed GOP required, 2-second keyframe intervals optimal
- HEVC accepted for upload but never delivered (Meta chose AV1 over HEVC)

**Critical insight:** Pre-compressing to IG's target quality (~Q76) causes WORSE results.
Josh Wright's CIEDE2000 analysis: uploading lossless PNG produced better fidelity than JPEG Q76
because IG's encoder performed only one lossy pass instead of compounding artifacts.

**ContentForge implementation:**
- Image quality raised to Q80-92 (FFmpeg q:v 2-3) — let IG do the only lossy pass
- sRGB colorspace forced via `format=yuvj420p` in image pipeline
- Video bitrates 12-24 Mbps — matches IG's input expectations for convex hull optimizer
- Audio 44.1kHz AAC-LC 128kbps — exact match to IG's output spec
- Closed GOP with 2s keyint (60 frames at 30fps) — matches IG requirement

**Threads:** Shares IG's backend media pipeline but applies less aggressive visible compression.
No aspect ratio cropping. Supports mixed-ratio carousels. Up to 5-minute video.

---

## 9. Threads Platform Policies & Cross-Platform Detection

**Threads API limits (flat rate, no business tier):**
- 250 posts / 24 hours per profile
- 1,000 replies / 24 hours (separate bucket)
- 100 deletes / 24 hours
- No per-hour sub-limit

**No confirmed duplicate detection on Threads:**
- Meta's fingerprinting arsenal (PDQ, SSCD, SimSearchNet++) is vast but not confirmed deployed on Threads for originality
- Duplicate content triggers spam detection, not content fingerprinting
- Instagram's "Original by" / Content Protection tool does NOT cover Threads
- Behavioral signals (posting velocity, cross-account patterns) matter more than content signals

**Shadowbanning signals (ranked by risk):**
1. Rapid-fire posting (10 threads in 6 minutes = warning)
2. Mass following/unfollowing
3. Repetitive replies across threads
4. Engagement bait ("Follow for follow")
5. Unverified automation tools (official API tools are safe)

**API content receives equal or better treatment** than native posts (confirmed by Agorapulse, Hootsuite, Buffer studies).

**Cascade enforcement: Instagram → Threads (one-directional):**
- Instagram ban = Threads disabled automatically
- Threads deletion does NOT affect Instagram
- Summer 2025 ban wave: cascading automation took down whole networks from one shared login

**Cross-posting IG ↔ Threads is safe:**
- Adam Mosseri personally recommends it
- Meta's duplicate detection targets same-platform content theft, not cross-platform self-posting
- No `source_platform` or cross-post metadata in API
- No penalty mechanism exists for identical content on both platforms

**Meta cross-platform content matching:**
- SimSearchNet++ runs on every image uploaded to IG (confirmed)
- Fact-checks propagate across platforms via "near-identical content" detection
- FAISS indexes 1.5 trillion vectors internally
- CIB enforcement formally covers Threads but no takedowns have listed Threads accounts
- ThreatExchange is for external sharing only — Meta's internal matching is proprietary

**Practical limits (community-tested):**
- 20 posts/day practical max per account before spam detection
- New accounts: 1 post every 2 hours until established
- First-hour engagement velocity matters more than posting volume

---

## Implementation Summary

### Similarity Checker v2 (Pre-Publish Audit)
6-layer detection using the same algorithms platforms use:
1. **PDQ hash** — `pdqhash` Python package, Hamming distance thresholds: PASS >60, WARN 30-60, FAIL <30
2. **SSCD neural embedding** — Meta's sscd_disc_mixup model (512-d), cosine similarity thresholds: PASS <0.50, WARN 0.50-0.75, FAIL >=0.75
3. **Audio fingerprint** — Chromaprint/fpcalc spectral landmark comparison
4. **Metadata forensics** — ffprobe + strings scan for encoder tells, bitrate checks
5. **Compression forensics** — DCT histogram periodicity, Benford's law, GOP DFT, x264 SEI UUID detection, encoder ID via MediaInfo
6. **SSIM** — Visual quality indicator only (not a detection predictor)

### Composite Scoring (research-calibrated)
Thresholds calibrated against published benchmarks (DISC2021, Meta's own research):
- **PASS**: SSCD cosine <0.50 AND PDQ Hamming >60
- **WARN**: SSCD 0.50-0.75 OR PDQ 30-60
- **FAIL**: SSCD >=0.75 (90% precision copy threshold) OR PDQ <30
- Cross-account target: SSCD cosine <0.75 between any two posts from same base content

### Pipeline Upgrades v5
- **Device profiles:** Random iPhone/Samsung/Pixel encoding per variant
- **Texture bias exploit:** Increased sharpening (0.5-1.0) + temporal+uniform grain (t+u flag)
- **Audio pitch shift:** +-50 cents via asetrate+aresample (imperceptible, ODG > -0.5)
- **Wider speed range:** 0.93-1.07x (was 0.96-1.04x)
- **Stronger time warp:** Amplitude 0.03-0.07 (was 0.02-0.04), non-uniform sine wave
- **Proper container metadata:** Device-matched handler names, bitrates, color flags, audio sample rates
- **Clean level:** Imperceptible transforms only (crop + micro warp + pitch shift), skips Phase 1
- **Post-processing sanitizer:** Strips x264 UUID SEI from H.264 bitstream + Lavf/Lavc strings from container atoms (zero quality loss binary patching)
- **JPEG QT randomization:** Each image variant gets a unique quantization table fingerprint via jpegio (prevents batch-origin detection)

### Post-Processing Pipeline (lib/sanitize.py)
Applied automatically after every video variant:
1. Scans H.264 bitstream for x264 UUID SEI (dc45e9bd-e6d9-48b7-962c-d820d923eeef) and nullifies it
2. Nullifies (C)too encoder tool atom value
3. Finds and blanks Lavf/Lavc/x264/ffmpeg strings in container atoms
4. Verifies no forensic strings remain post-sanitization
5. Binary patching preserves exact file size (no re-encoding)

### JPEG Post-Processing (lib/jpeg_randomize_qt.py)
Applied automatically after every image variant:
1. Generates randomized quantization tables per variant (+-5% perturbation from standard)
2. Re-saves with unique QT fingerprint (quality range 85-95)
3. Each variant appears to come from different software/device

### Remaining Limitations
- **CABAC probability model patterns** — x264's adaptive arithmetic coding differs from hardware encoders at a statistical level. Cannot be changed without modifying x264 source.
- **Macroblock mode distributions** — x264 explores more prediction modes than hardware encoders. Mitigated by `me=dia:subme=1:trellis=0` in Android profiles but not perfect.
- **C2PA provenance** — Apple is deploying cryptographic content provenance signing. Once active for video, no amount of post-processing can forge a valid signature.
- **Upload timing/rate limiting** — User responsibility (not ContentForge scope)
- **Device fingerprinting** (AppLog SDK, cross-app graphs) — Platform-side, user must use separate devices/anti-detect browsers
- **Network analysis** (IP/ASN/proxy detection) — User must use residential IPs/mobile proxies
