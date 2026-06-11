/**
 * Prefilter Gate — cheap pre-checks before the expensive embedding gate.
 *
 * Two layers:
 *   1. Banned-phrase match (per-workspace list in `banned_phrases` table).
 *      Supports substring / exact / regex patterns and block / warn severity.
 *      `block` → reject. `warn` → pass with a flag for observability.
 *   2. Trigram similarity (pg_trgm) against recent published / pending /
 *      queued posts in the same workspace. Rejects near-exact duplicates
 *      without paying for a Gemini embedding API round-trip.
 *
 * Designed to run BEFORE checkSemanticDedup / checkOnBrand / checkCrossGroupDiversity
 * so trivial rejections short-circuit the embedding pipeline.
 *
 * Fail-open: any DB or config error passes the candidate through — the
 * embedding gate remains the correctness floor.
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PrefilterResult {
	passed: boolean;
	reason?: string | undefined;
	/** Trigram similarity 0..1 when the reject reason was trigram-dupe. */
	trigramSimilarity?: number | undefined;
	/** IDs of any 'warn' banned phrases that matched (did not block). */
	warnPhrases?: string[] | undefined;
}

export interface PrefilterOptions {
	/** Trigram similarity threshold above which we reject as near-duplicate. 0.7 default. */
	trigramThreshold?: number | undefined;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_TRIGRAM_THRESHOLD = 0.7;
const REGEX_TIMEOUT_MS = 50;

// ---------------------------------------------------------------------------
// Main entry
// ---------------------------------------------------------------------------

export async function runPrefilter(
	candidate: string,
	workspaceId: string,
	options: PrefilterOptions = {},
): Promise<PrefilterResult> {
	const text = (candidate ?? "").trim();
	if (!text) {
		return { passed: false, reason: "empty-content" };
	}

	const threshold = options.trigramThreshold ?? DEFAULT_TRIGRAM_THRESHOLD;
	const warnPhrases: string[] = [];

	// ── Layer 1: banned phrases ───────────────────────────────────────────────
	try {
		const db = getSupabaseAny();
		const { data: rows, error } = await db
			.from("banned_phrases")
			.select("phrase, pattern_type, severity")
			.eq("workspace_id", workspaceId);

		if (error) {
			logger.warn("[prefilter] banned_phrases query failed, fail-open", {
				workspaceId,
				error: error.message,
			});
		} else {
			const lowered = text.toLowerCase();
			for (const row of rows ?? []) {
				const phrase = String(row.phrase ?? "");
				if (!phrase) continue;
				const pattern = String(row.pattern_type ?? "substring");
				const severity = String(row.severity ?? "block");
				const hit = phraseMatches(lowered, text, phrase, pattern);
				if (!hit) continue;

				if (severity === "block") {
					return {
						passed: false,
						reason: `banned-phrase:${pattern}:${truncate(phrase, 40)}`,
						warnPhrases: warnPhrases.length ? warnPhrases : undefined,
					};
				}
				warnPhrases.push(phrase);
			}
		}
	} catch (err) {
		logger.warn("[prefilter] banned-phrase check failed, fail-open", {
			workspaceId,
			error: String(err),
		});
	}

	// ── Layer 2: trigram similarity via check_trigram_dupe RPC ────────────────
	try {
		const db = getSupabaseAny();
		const { data, error } = await db.rpc("check_trigram_dupe", {
			p_workspace_id: workspaceId,
			p_content: text,
			p_threshold: threshold,
		});

		if (error) {
			logger.warn("[prefilter] check_trigram_dupe failed, fail-open", {
				workspaceId,
				error: error.message,
			});
		} else if (Array.isArray(data) && data.length > 0) {
			const match = data[0] as {
				matched_id?: string | undefined;
				matched_similarity?: number | undefined;
			};
			const sim = Number(match.matched_similarity ?? 0);
			return {
				passed: false,
				reason: `trigram-dupe:${sim.toFixed(3)}`,
				trigramSimilarity: sim,
				warnPhrases: warnPhrases.length ? warnPhrases : undefined,
			};
		}
	} catch (err) {
		logger.warn("[prefilter] trigram check threw, fail-open", {
			workspaceId,
			error: String(err),
		});
	}

	return {
		passed: true,
		warnPhrases: warnPhrases.length ? warnPhrases : undefined,
	};
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function phraseMatches(
	lowered: string,
	original: string,
	phrase: string,
	pattern: string,
): boolean {
	const p = phrase.toLowerCase();
	switch (pattern) {
		case "exact":
			return lowered === p;
		case "regex":
			return safeRegexTest(phrase, original);
		default:
			return lowered.includes(p);
	}
}

function safeRegexTest(pattern: string, text: string): boolean {
	// Guard against ReDoS — very crude timeout via Date.now() check after the op.
	// A misbehaving regex will still finish this call; this just prevents future
	// problematic patterns from stalling the pipeline silently.
	try {
		const regex = new RegExp(pattern, "i");
		const started = Date.now();
		const matched = regex.test(text);
		const elapsed = Date.now() - started;
		if (elapsed > REGEX_TIMEOUT_MS) {
			logger.warn("[prefilter] slow regex pattern", {
				pattern: truncate(pattern, 80),
				elapsed,
			});
		}
		return matched;
	} catch (err) {
		logger.debug("[prefilter] invalid regex pattern", {
			pattern: truncate(pattern, 80),
			error: String(err),
		});
		return false;
	}
}

function truncate(s: string, n: number): string {
	return s.length > n ? `${s.slice(0, n)}…` : s;
}
