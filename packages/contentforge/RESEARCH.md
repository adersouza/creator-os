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

## 5. Platform Forensics (Detection Evidence Only)

This material is retained only to explain signals ContentForge may report. It
must not be used to hide provenance, spoof devices, evade enforcement, or
recommend account/network circumvention. The active product is detect-and-block.

**Four-layer detection:**

### Layer 1: Metadata & Compression Forensics
- Platforms analyze EXIF/container metadata server-side before stripping from public files
- FFmpeg's `Lavf` encoder string and x264 UUID SEI are instant tells
- Double compression creates detectable DCT coefficient periodicity
- Container atoms (ftyp, handler_name, timescale) identify encoding software

### Layer 2: Upload Timing
- Rate limits and publishing policies change and are owned by each platform.
- ContentForge does not schedule, throttle, or advise ways to evade enforcement.
- Production pacing must use current platform documentation and the publishing
  system's account-health guardrails.

### Layer 3: Device Fingerprinting
- TikTok collects 40+ device signals via AppLog SDK
- Meta maintains cross-app device graph (IG, FB, WhatsApp, Messenger)
- Multiple accounts from one device share action budgets

### Layer 4: Network Analysis
- IP classification: mobile (high trust) > residential > VPN (low) > datacenter (blocked)
- ASN analysis identifies hosting/cloud IPs
- Bipartite graph clustering links accounts sharing IPs
- Residential proxy detection via behavioral analysis

ContentForge similarity thresholds are quality and collision signals, not
promises about distribution, moderation, or account survival.

---

## 6. Device Container Forensics

Container and stream metadata can help identify transcoding, missing provenance,
or unexpected changes between an input and output. ContentForge may inspect and
report those signals as evidence. It must preserve honest source/output
lineage; it must not synthesize a phone model, handler, creation time, encoder
identity, or other capture signature, and it must not strip metadata to make an
editorial derivative appear device-native.

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
- Same-parameter re-encoding (QP1 = QP2, GOP1 = GOP2): difficult to classify;
  this is a detector limitation, not a transformation recommendation.

**ContentForge policy:**
- Preserve honest encoder/container provenance.
- Report suspicious or missing provenance as evidence.
- Use editorial transformations only when they improve the actual creative.
- Never randomize encoder parameters, metadata, or device identity to evade
  similarity or provenance systems.

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

### Rejected Historical Approach

Earlier experiments proposed device profiles, invisible noise, encoder-string
sanitization, randomized JPEG quantization tables, and metadata spoofing. Those
features violated Creator OS's provenance and platform-safety boundary and were
removed. They are not an active or acceptable ContentForge mode.

The supported variant path is ordinary editorial work: meaningful trim,
sequencing, pacing, audio, caption, or framing changes with recorded FFmpeg
arguments, source/output SHA-256, quality checks, and honest provenance.

### Remaining Limitations
- **Encoder fingerprints** — Different encoders leave different statistical and
  container signatures. ContentForge records these honestly instead of trying
  to imitate a capture device.
- **C2PA provenance** — cryptographic provenance should be preserved and
  validated when available; ContentForge must never attempt to forge it.
- **Upload timing/rate limiting** — User responsibility (not ContentForge scope)
- **Device and network analysis** — platform-side concerns that are outside
  ContentForge scope and never justify circumvention guidance.
