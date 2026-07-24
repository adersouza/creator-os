# Mac Local Video Stack — 2026 Decision Record

Creator OS optimizes for one commercial, recoverable Apple-silicon generation
path. A capability is not added merely because a demo launches on MPS. It must
have an exact runtime revision, exact model revisions, bounded inputs, offline
execution, output validation, durable lineage, and a ContentForge review path.

## Adopted

| Capability | Creator OS implementation | Status |
|---|---|---|
| High-volume still motion | Wan 2.2 TI2V-5B Q8 through pinned `mlx-video` | production contract; visual canary required |
| Higher-fidelity still motion | Wan 2.2 I2V-A14B Q4 through pinned `mlx-video` | production contract; visual canary required |
| Fast joint audio/video | LTX-2.3 Q4 through pinned `ltx-2-mlx` | generated audio only |
| HQ joint audio/video | LTX-2.3 Q8 through pinned `ltx-2-mlx` | generated or supplied audio |
| First/last frames | LTX Q8 repeatable keyframe conditioning | exact endpoint hashes retained |
| Keyframe interpolation | LTX Q8 `keyframe` pipeline | explicit task, not a hidden fallback |
| Segment repair | LTX Q8 `retake` pipeline | beta, source fingerprint and bounded latent range required |
| Clip continuation | LTX Q8 `extend` pipeline | beta, 1-24 latent frames, output must become longer |
| Mac memory controls | low-RAM block streaming and spatial/temporal tiling | low-RAM streaming by default; tiling is explicit and only for measured memory pressure |
| Model/style LoRAs | registered `.safetensors` with base revision, source, license, and SHA-256 | generation tasks only |
| Storage review | report-only legacy BF16 inventory | no deletion command exists |

The LTX runtime is direct. Creator OS does not route through a second local HTTP
queue because its existing queue already owns resource admission, interruption
recovery, collision protection, benchmarking, and artifact provenance.

## Deferred Or Rejected

| Candidate | Decision | Reason |
|---|---|---|
| Phosphene API | do not add as a backend | useful product, but its queue would duplicate Creator OS job/recovery state; its underlying `ltx-2-mlx` runtime is integrated directly |
| Phosphene character/voice LoRA trainer | defer | requires a consented dataset, commercial-rights review, identity/voice evaluation, and a training-lineage contract |
| LivePortrait default stack | reject for commercial runtime | its default InsightFace detector weights are restricted to non-commercial research; a replacement detector needs separate proof |
| LTX LipDub | defer | upstream marks it experimental; no production Mac identity/audio canary yet |
| Arbitrary multi-keyframe graph | defer | the supported contract is two endpoints; sequential chains need drift and identity evidence before automation |
| Wan Animate, VACE, S2V, Wan-Dancer | defer | current supported paths are CUDA-oriented or too large for an honest 64 GB Mac contract |
| ComfyUI/MPS as the primary runtime | reject | graph convenience does not replace exact MLX revisioning, offline execution, and one recovery owner |

## Runtime And Model Pins

- `mlx-video`: `87db56a51758fefb748a359b90a5283bb8ba4837`
- `ltx-2-mlx`: `d2ad8e9948157c14a063aca54e510d3d80c2c463`
- LTX Q4: `dgrauet/ltx-2.3-mlx-q4@53a6f5f39d9c074bc73e6a18ba391f40ddffaa68`
- LTX Q8: `dgrauet/ltx-2.3-mlx-q8@03da129baa459c9a70fc5858dee52fa417b3a93d`
- Gemma MLX Q4: `mlx-community/gemma-3-12b-it-4bit@86cc6a8dedbc456dd0e4af01a9d09f396f77e558`

## LTX Reel Recipe

Creator OS uses `576x1024` at 24 fps for ordinary portrait generation. That is
an exact 9:16 frame, both dimensions are divisible by 32, and the generated
frame count remains `8k+1`, matching LTX-2.3's published geometry contract.

- `local_ltx23_distilled_mlx` is the Q4 iteration/qualification tier. It uses
  the fastest distilled pipeline.
- `local_ltx23_dev_hq_mlx` is the Q8 final-quality tier. It uses the
  recommended two-stage HQ pipeline with the pinned distilled LoRA and v1.1
  spatial upscaler.
- `--low-ram` stays enabled on the 64 GB Mac. Spatial and temporal modality
  tiling stay off (`1`) unless a measured 1080p, 8-second-or-longer run exceeds
  the admitted memory envelope. Independent spatial tiles can damage a face
  that crosses tile boundaries and are not a quality preset.
- Image-to-video prompts describe only changes from the supplied first frame:
  literal, chronological subject motion, any requested camera movement, and
  the synchronized soundscape. Prompt enhancement must happen before Arena
  planning so the exact expanded text is fingerprinted; hidden runtime
  expansion is not acceptable evidence.

The installed Q4 and Q8 manifests already bind the required Gemma text encoder,
audio/video components, v1.1 spatial upscaler, and (for Q8) distilled LoRA.
The temporal upscaler and optional control/LipDub LoRAs are not current
requirements for the adopted pipelines and are not downloaded speculatively.

Upstream references: [MLX Video](https://github.com/Blaizzy/mlx-video),
[LTX 2 MLX](https://github.com/dgrauet/ltx-2-mlx),
[LTX-2](https://github.com/Lightricks/LTX-2),
[Phosphene](https://github.com/mrbizarro/phosphene), and
[LivePortrait](https://github.com/KlingAIResearch/LivePortrait).

## Promotion Gate

Installed is not promoted. A model/task becomes recommended only after a real
Mac canary records peak memory and wall time, the output is bound to motion,
identity, anatomy, audio-alignment, and lip-sync evidence as applicable, and a
human approves the matched benchmark. Until then every derivative stays
review-only and the accepted static asset remains the fallback.
