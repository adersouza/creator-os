// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Embedding-based On-Brand Gate (Phase 4)
 *
 * Compares generated content against a persona's top-performing posts
 * using cosine similarity of Gemini embeddings. Posts semantically
 * distant from proven winners are likely off-brand garbage.
 *
 * Pipeline position: regex → judge → embedding gate → insert
 *
 * Thresholds (from Grok + Perplexity research):
 *   > 0.80  → on-brand (pass)
 *   0.60-0.80 → borderline (pass if judge score was high)
 *   < 0.60  → off-brand (reject)
 *   > 0.97  → near-duplicate (reject)
 *
 * Cold start: works with as few as 5 reference posts per persona.
 * Embeddings are cached in memory for the duration of the queue fill
 * (not persisted to DB yet — Phase 4.1 optimization).
 *
 * Cost: gemini-embedding-001 at $0.15/1M tokens. Embedding 50 short
 * posts costs < $0.001. Negligible.
 */

import { logger } from "../../logger.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabaseAny } from "../../supabase.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EmbeddingGateResult {
	passed: boolean;
	maxSimilarity: number;
	reason?: string | undefined;
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Below this = off-brand → reject */
const MIN_SIMILARITY = 0.6;

/** Above this = near-duplicate → reject */
const MAX_SIMILARITY = 0.97;

/** Above this vs recent posts = semantic duplicate → reject.
 *  Raised from 0.88 → 0.93: at 0.88 with 4000+ published posts, nearly
 *  every short casual post matches something — 27/29 rejections were
 *  false-positive semantic dedup at 0.882-0.940 similarity. */
const DEDUP_SIMILARITY = 0.93;

/** Above this vs cross-group posts = coordinated account detection risk → reject.
 *  Research: coordinated accounts detected when posting near-IDENTICAL content
 *  (cosine sim 0.46-0.47 in that study referred to identical posts across accounts).
 *  Short casual posts in the same niche (dating/gaming/life) naturally cluster
 *  at 0.6-0.9 similarity due to shared vocabulary — 0.40 rejected everything.
 *  Set to 0.93 (same as DEDUP_SIMILARITY) to only catch actual near-duplicates. */
const CROSS_GROUP_DIVERSITY_THRESHOLD = 0.93;

/** Embedding API timeout */
const EMBED_TIMEOUT_MS = 10_000;

/** Cache embeddings during a single fill cycle (not persisted) */
const embeddingCache = new Map<string, number[]>();

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Check if a candidate post is on-brand for a persona by comparing
 * it against the persona's top-performing posts via cosine similarity.
 *
 * @param candidate  - The post text to evaluate
 * @param topPosts   - Array of the persona's best-performing post texts
 * @param apiKey     - Gemini API key
 * @returns EmbeddingGateResult with pass/fail + similarity score
 */
export async function checkOnBrand(
	candidate: string,
	topPosts: string[],
	apiKey: string,
): Promise<EmbeddingGateResult> {
	// Need at least some reference posts
	if (topPosts.length < 3) {
		return { passed: true, maxSimilarity: -1, reason: "cold-start-bypass" };
	}

	try {
		// Embed candidate
		const candidateVec = await getEmbedding(candidate, apiKey);
		if (!candidateVec) {
			return { passed: true, maxSimilarity: -1, reason: "embed-failed" };
		}

		// Embed reference posts in parallel (cached hits return instantly)
		const refResults = await Promise.all(
			topPosts.map((post) => getEmbedding(post, apiKey)),
		);
		const refVecs = refResults.filter((v): v is number[] => v !== null);

		if (refVecs.length === 0) {
			return { passed: true, maxSimilarity: -1, reason: "no-ref-embeddings" };
		}

		// Compute max cosine similarity
		let maxSim = -1;
		for (const ref of refVecs) {
			const sim = cosineSimilarity(candidateVec, ref);
			if (sim > maxSim) maxSim = sim;
		}

		// Near-duplicate check
		if (maxSim > MAX_SIMILARITY) {
			return {
				passed: false,
				maxSimilarity: maxSim,
				reason: `near-duplicate:${maxSim.toFixed(3)}`,
			};
		}

		// Off-brand check
		if (maxSim < MIN_SIMILARITY) {
			return {
				passed: false,
				maxSimilarity: maxSim,
				reason: `off-brand:${maxSim.toFixed(3)}`,
			};
		}

		return { passed: true, maxSimilarity: maxSim };
	} catch (err) {
		// Fail-open — embedding gate is supplementary
		logger.warn("Embedding gate error, fail-open", {
			error: String(err),
			contentPreview: candidate.substring(0, 40),
		});
		return { passed: true, maxSimilarity: -1, reason: `error:${String(err)}` };
	}
}

/**
 * Semantic dedup — reject posts that express the same idea as recent posts,
 * even if worded differently. Catches what Jaccard/trigram overlap misses.
 *
 * Threshold: > 0.95 similarity to ANY recent post = semantic duplicate.
 * Lower than the on-brand near-duplicate threshold (0.97) because dedup
 * should be stricter — we want variety, not just non-identical posts.
 *
 * Fail-open: if embedding API fails, the post passes through
 * (trigram similarity already provides a baseline check).
 */
export async function checkSemanticDedup(
	candidate: string,
	recentPosts: string[],
	apiKey: string,
): Promise<EmbeddingGateResult> {
	if (recentPosts.length < 5) {
		return { passed: true, maxSimilarity: -1, reason: "too-few-recent" };
	}

	try {
		const candidateVec = await getEmbedding(candidate, apiKey);
		if (!candidateVec) {
			return { passed: true, maxSimilarity: -1, reason: "embed-failed" };
		}

		// Embed recent posts in parallel (cached from same fill cycle)
		const refResults = await Promise.all(
			recentPosts.slice(0, 50).map((post) => getEmbedding(post, apiKey)),
		);
		const refVecs = refResults.filter((v): v is number[] => v !== null);

		if (refVecs.length === 0) {
			return { passed: true, maxSimilarity: -1, reason: "no-ref-embeddings" };
		}

		let maxSim = -1;
		for (const ref of refVecs) {
			const sim = cosineSimilarity(candidateVec, ref);
			if (sim > maxSim) maxSim = sim;
		}

		if (maxSim > DEDUP_SIMILARITY) {
			return {
				passed: false,
				maxSimilarity: maxSim,
				reason: `semantic-duplicate:${maxSim.toFixed(3)}`,
			};
		}

		return { passed: true, maxSimilarity: maxSim };
	} catch (err) {
		logger.warn("Semantic dedup error, fail-open", {
			error: String(err),
			contentPreview: candidate.substring(0, 40),
		});
		return { passed: true, maxSimilarity: -1, reason: `error:${String(err)}` };
	}
}

/**
 * Cross-group content diversity — reject posts too similar to recent posts
 * from OTHER groups in the same workspace. Prevents coordinated account
 * detection where platforms flag accounts posting semantically identical
 * content (research: cosine sim 0.46-0.47 triggers detection).
 *
 * Unlike checkSemanticDedup (which checks within the same group's recent posts),
 * this queries the last 50 published posts across ALL groups in the workspace.
 *
 * Fail-open: if DB query or embedding API fails, the post passes through.
 */
export async function checkCrossGroupDiversity(
	content: string,
	workspaceId: string,
	apiKey: string,
): Promise<EmbeddingGateResult> {
	try {
		// Fetch the last 50 published posts across ALL groups in this workspace
		const db = getSupabaseAny();
		const { data, error } = await db
			.from("auto_post_queue")
			.select("content, group_id")
			.eq("workspace_id", workspaceId)
			.eq("status", "published")
			.order("posted_at", { ascending: false })
			.limit(50);

		if (error) {
			logger.warn("Cross-group diversity DB query failed, fail-open", {
				error: String(error),
				workspaceId,
			});
			return { passed: true, maxSimilarity: -1, reason: "db-error" };
		}

		const crossGroupContents: string[] = (data || [])
			.map((p: { content?: string | undefined }) => p.content || "")
			.filter((c: string) => c.length > 0);

		if (crossGroupContents.length < 5) {
			return { passed: true, maxSimilarity: -1, reason: "too-few-cross-group" };
		}

		// Embed the candidate
		const candidateVec = await getEmbedding(content, apiKey);
		if (!candidateVec) {
			return { passed: true, maxSimilarity: -1, reason: "embed-failed" };
		}

		// Embed cross-group posts (many will be cached from same fill cycle)
		const refResults = await Promise.all(
			crossGroupContents.map((post) => getEmbedding(post, apiKey)),
		);
		const refVecs = refResults.filter((v): v is number[] => v !== null);

		if (refVecs.length === 0) {
			return { passed: true, maxSimilarity: -1, reason: "no-ref-embeddings" };
		}

		let maxSim = -1;
		for (const ref of refVecs) {
			const sim = cosineSimilarity(candidateVec, ref);
			if (sim > maxSim) maxSim = sim;
		}

		logger.info("Cross-group diversity check", {
			workspaceId,
			maxSimilarity: maxSim.toFixed(3),
			threshold: CROSS_GROUP_DIVERSITY_THRESHOLD,
			crossGroupPostCount: refVecs.length,
			contentPreview: content.substring(0, 60),
		});

		if (maxSim > CROSS_GROUP_DIVERSITY_THRESHOLD) {
			return {
				passed: false,
				maxSimilarity: maxSim,
				reason: `cross-group-too-similar:${maxSim.toFixed(3)}`,
			};
		}

		return { passed: true, maxSimilarity: maxSim };
	} catch (err) {
		// Fail-open — diversity check is supplementary
		logger.warn("Cross-group diversity error, fail-open", {
			error: String(err),
			contentPreview: content.substring(0, 40),
		});
		return { passed: true, maxSimilarity: -1, reason: `error:${String(err)}` };
	}
}

/**
 * Clear the embedding cache. Call at the end of each fill cycle
 * to free memory.
 */
export function clearEmbeddingCache(): void {
	embeddingCache.clear();
}

// ---------------------------------------------------------------------------
// Embedding API
// ---------------------------------------------------------------------------

// Import the quota breaker from aiProviders (same module boundary)
let embeddingQuotaBlockedUntil = 0;

async function getEmbedding(
	text: string,
	apiKey: string,
): Promise<number[] | null> {
	// Quota circuit breaker
	if (Date.now() < embeddingQuotaBlockedUntil) {
		return null;
	}

	// Check cache first
	const cacheKey = text.substring(0, 100); // short posts are unique enough
	const cached = embeddingCache.get(cacheKey);
	if (cached) return cached;

	try {
		const response = await withRetry(
			() =>
				fetch(
					`https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=${apiKey}`,
					{
						method: "POST",
						headers: { "Content-Type": "application/json" },
						signal: AbortSignal.timeout(EMBED_TIMEOUT_MS),
						body: JSON.stringify({
							model: "models/gemini-embedding-001",
							content: { parts: [{ text }] },
							taskType: "SEMANTIC_SIMILARITY",
							outputDimensionality: 768, // reduced from 3072 for speed
						}),
					},
				),
			{ label: "auto-post:gemini-embedding" },
		);

		if (!response.ok) {
			logger.warn("Embedding API error", { status: response.status });
			if (
				response.status === 429 ||
				response.status === 402 ||
				response.status === 403
			) {
				embeddingQuotaBlockedUntil = Date.now() + 30 * 60 * 1000;
				logger.error("Embedding quota exhausted — blocking for 30 min");
			}
			return null;
		}

		const data = await response.json();
		const values = data?.embedding?.values;
		if (!Array.isArray(values) || values.length === 0) return null;

		embeddingCache.set(cacheKey, values);
		return values;
	} catch (err) {
		logger.warn("Embedding API call failed", { error: String(err) });
		return null;
	}
}

// ---------------------------------------------------------------------------
// Math
// ---------------------------------------------------------------------------

function cosineSimilarity(a: number[], b: number[]): number {
	if (a.length !== b.length) return 0;
	let dot = 0;
	let normA = 0;
	let normB = 0;
	for (let i = 0; i < a.length; i++) {
		dot += a[i]! * b[i]!;
		normA += a[i]! * a[i]!;
		normB += b[i]! * b[i]!;
	}
	const denom = Math.sqrt(normA) * Math.sqrt(normB);
	return denom === 0 ? 0 : dot / denom;
}
