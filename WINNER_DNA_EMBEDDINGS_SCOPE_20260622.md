# Winner-DNA Embeddings Scope — Track B (for Codex)

**Goal:** replace heuristic keyword clustering in Reference Factory with **image-embedding** clustering, so "winner DNA" is discovered from how references actually *look*, not from three categorical tags. Runs local on the Mac Studio (MPS).

**Sequence:** independent of Track A — improves content *taste/coherence* now. Its *money-weighted* ranking (which look made money) waits on Track A's attribution feed. Build the embedding+report slice now; wire reward when A lands. Per Codex: **nearest-neighbor first, no UMAP/HDBSCAN yet.**

---

## 0. Current state (verified, file:line)

- **Clustering seam** `reference_factory/learning.py:163-174` `_cluster_cards()` groups by `_cluster_key(card)` (`:177-184`):
  ```python
  key = "::".join([visual_format, hook_type, caption_archetype])
  ```
  **Exact weakness:** three discrete heuristic tags from `patterns.py:307-397` (`_heuristic_pattern()` — regex/OCR text matching). Zero visual or semantic similarity; no image is ever looked at. Two visually-identical winners with different tag labels land in different clusters; two visually-opposite refs with the same tags merge.
- **Export** `learning.py:634-670` `_campaign_reference_bank()` → `{clusters:[{clusterKey, visualFormat, hookType, captionArchetype, referenceIds, referenceFiles(ranked[:8]), captionFormulas, promptTemplate, audioRecommendations}]}`. Consumed by `campaign_factory/reference.py:37-119` `import_reference_bank()`. **Export shape must stay stable.**
- **Dropped signals** (audit): `accountWinnerSignals` / `personaWinnerSignals` / `performanceSignals` computed (`learning.py:244-254`) but not exported / not consumed.
- **Images on disk** `reference_factory/db.py:14-27` `source_files(path, kind ∈ {video,image}, reference_id PK)`. Videos need first-frame extract; images load direct. Medoid candidate paths already flow as `referenceFiles`/`topLocalPath`.
- **Deps already present:** ContentForge `apps/contentforge/lib/reference_db.py:21-61` = torch + torchvision + **FAISS** + SSCD TorchScript, `EMBEDDING_DIM=512`, **L2-normalized cosine** (`:105`), PDQ hashing. Reel Factory `pyproject.toml` ai-extras = `timm`, `sentence-transformers`, `torchvision`. **DINOv2 loads via `timm`.** So the embedding/index stack is in-repo — reuse it.
- **Higgsfield image gen is prompt-text only** `higgsfield_runner.py:861-871` (`--prompt` + `--custom_reference_id soul_uuid`; **no reference image**). `--start-image` (`:1106-1118`) is the *generated* frame fed to Kling video. So "medoid → reference image for generation" is a **new capability**, not a swap.
- **Outcome loop open** `reference_factory/outcomes.py:12-83` `import_prompt_outcomes()` defined, **never called**; `generated_video_prompts.outcome_reward_score/sample_count/confidence` all NULL. So there is **no measured reward to rank on yet** — see §4.

---

## 1. First slice (the lazy, boring one)

Embed local references → FAISS nearest-neighbor groups → medoid per group → same export shape. **No UMAP, no HDBSCAN, no new infra.**

1. **Embed** each `source_files` row with an image (or video first-frame): **DINOv2 ViT-L/14** via `timm` (style/"vibe"). SigLIP2 (semantic) is a *second* embedding — add only if DINOv2-alone groups look weak. L2-normalize. MPS auto-detect (`torch.backends.mps.is_available()`), CPU fallback. Cache vectors keyed by `reference_id` (skip recompute).
2. **Index + group** reusing ContentForge's FAISS+L2 pattern (`reference_db.py:21-105`): cosine-threshold nearest-neighbor connected components (one tunable threshold). No fixed `k`. Below-threshold singletons = "noise" bucket, not forced into a cluster.
3. **Medoid + rank** per group: medoid = vector closest to group centroid; rank members by **existing** `_quality_score` (`patterns.py:570-611`) + plays/rank (what's available today — see §4 for the reward upgrade). Export `referenceFiles` = top-8 by that rank (slot already exists).
4. **Replace** `_cluster_key`-based grouping in `_cluster_cards()` (`learning.py:163-174`) with the group id. Keep `_cluster_from_items()` output shape; relabel the cluster from the medoid's heuristic tags (so `visualFormat`/`hookType`/`captionArchetype` stay populated for back-compat) + add one field `embeddingClusterId`.

**Out of this slice:** UMAP/HDBSCAN, caption embeddings, the Higgsfield reference-image feature (§3), measured-reward ranking (§4). Each is a separate follow-on, gated on this proving useful.

---

## 2. Schema delta (additive)

- Vector cache: new table `reference_embeddings(reference_id PK, model_tag, dim, vector BLOB, computed_at)` — or a FAISS sidecar `.index` + id map next to the RF DB. Sidecar is lazier (no migration); pick it unless the DB join is needed elsewhere.
- `learning_clusters` (CF side, `reference.py`): add nullable `embedding_cluster_id`. Import logic unchanged otherwise.
- No change to the `campaign_reference_bank.json` contract.

---

## 3. Follow-on: medoid → Higgsfield reference image (NEW capability)

Today Higgsfield image gen is prompt-only. Passing the cluster medoid as a visual anchor (`higgsfield_runner.py:861-871`, add a reference-image arg) is the payoff of embedding clusters — *generate in the proven visual style*, not just from prompt text. **Separate slice**, after §1 medoids look coherent. Note: verify the Higgsfield Soul image API accepts a reference image alongside the soul_uuid before scoping further.

---

## 4. The reward — convergence with Track A

Ranking clusters by **raw** average performance is the trap the research flagged: a one-post cluster fakes a 100% rate. The fix is **empirical-Bayes-shrunk** performance — but that needs a measured reward per reference, and:

- `outcomes.py:import_prompt_outcomes()` is **never called**; `generated_video_prompts.outcome_*` are NULL. The learning loop is open.
- Track A's `autoposter_attribution_facts.v1` is exactly the missing reward signal (per-arm clicks/conversions → back to the reference that generated the post).

**So:** §1 ships ranking on the existing quality/plays signal (taste). The money reward needs **arm-grain** attribution — which Track A delivers only at its **exact-post (V1.5 block-landing-page) grain**, *not* the manual-bio V1 (account/daypart is a scheduling signal, too coarse to rank content by). When Track A's **exact-post** feed exists, wire it through `import_prompt_outcomes()` → `generated_video_prompts.outcome_reward_score`, and switch medoid/cluster ranking to **empirical-Bayes-shrunk reward**. That is the "reference clustering → winner DNA" graduation, and it's the **same shrunk-rate statistic** the bandit uses — one reward definition, two consumers. Don't invent a second reward here.

---

## 5. Acceptance checks

1. Embed + group a sample of `source_files` → groups are **visually** coherent (eyeball the medoid + top-8 per group); two near-duplicate refs land in the same group regardless of heuristic tags.
2. Export `campaign_reference_bank.json` **validates against the existing contract** (`reference.py:import_reference_bank` ingests it unchanged); `embeddingClusterId` present, old tag fields still populated.
3. Re-run is **idempotent + cached** (no re-embedding unchanged `reference_id`s).
4. MPS path used when available; CPU fallback produces identical groups (determinism check on the threshold).
5. Singleton/noise refs are **not** force-merged into a cluster.
6. One runnable self-check: `demo()`/`test_*` that embeds 2 known-similar + 1 known-different fixture image and asserts the two group, the one doesn't.

---

## 6. Open questions for Codex

- **DINOv2 source:** `timm` (already a dep) vs `transformers`? Prefer `timm` to avoid a new dep — confirm the ViT-L/14 weights are reachable offline on the Mac.
- **Vector store:** FAISS sidecar `.index` (no migration) vs a `reference_embeddings` table — which fits the RF DB lifecycle better?
- **Threshold tuning:** what cosine threshold gives sane group sizes on the real reference bank? Needs one calibration pass on actual data (the "leave the knob" point).
- **Video first-frame:** is there an existing frame-extract util in Reel Factory/ContentForge to reuse, or add one?
