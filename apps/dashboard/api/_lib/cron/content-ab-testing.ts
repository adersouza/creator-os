// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Content A/B Testing Engine
 *
 * Tags AI-generated posts as variant_a (standard) or variant_b (competitor-inspired).
 * After 24 hours, compares engagement. Winner's patterns get weighted higher
 * in the next AI fill cycle.
 *
 * Also computes engagement velocity scoring for all published posts.
 *
 * Runs daily via daily-orchestrator.
 */

import { logger, serializeError } from "../logger.js";
import { getSupabase } from "../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

const LOG_PREFIX = "[content-ab-testing]";

// ============================================================================
// Types
// ============================================================================

interface ABTestResult {
	postsAnalyzed: number;
	variantAAvgViews: number;
	variantBAvgViews: number;
	winner: "a" | "b" | "tie";
	velocityScoresUpdated: number;
}

// ============================================================================
// Engagement Velocity Scoring
// ============================================================================

/**
 * Compute velocity_score for all published posts from last 7 days.
 * velocity_score = engagement / hours_since_posted
 * High velocity = algorithmic push = patterns to copy.
 */
export async function computeVelocityScores(): Promise<number> {
	const now = Date.now();
	const sevenDaysAgo = new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString();

	const { data: posts, error } = await db()
		.from("posts")
		.select("id, views_count, replies_count, likes_count, published_at")
		.eq("platform", "threads")
		.eq("status", "published")
		.not("published_at", "is", null)
		.gte("published_at", sevenDaysAgo);

	if (error || !posts || posts.length === 0) return 0;

	let updated = 0;
	const batchUpdates: { id: string; velocity_score: number }[] = [];

	for (const post of posts) {
		const publishedAt = new Date(post.published_at).getTime();
		const hoursElapsed = Math.max(1, (now - publishedAt) / (1000 * 60 * 60));

		const engagement =
			(post.views_count || 0) +
			(post.replies_count || 0) * 5 +
			(post.likes_count || 0) * 2;
		const velocityScore = Math.round((engagement / hoursElapsed) * 100) / 100;

		batchUpdates.push({ id: post.id, velocity_score: velocityScore });
	}

	// Batch update in chunks of 50
	for (let i = 0; i < batchUpdates.length; i += 50) {
		const batch = batchUpdates.slice(i, i + 50);
		for (const update of batch) {
			const { error: updateErr } = await db()
				.from("posts")
				.update({ predicted_viral_score: update.velocity_score })
				.eq("id", update.id);

			if (!updateErr) updated++;
		}
	}

	logger.info(`${LOG_PREFIX} Velocity scores updated`, {
		total: posts.length,
		updated,
	});

	return updated;
}

// ============================================================================
// A/B Test Analysis
// ============================================================================

/**
 * Analyze A/B test results from posts tagged in auto_post_queue.
 * Posts with source_type "ai" are variant A (standard AI generation).
 * Posts with source_type "competitor_copy" / "competitor_direct" are variant B (competitor-sourced).
 * Compare 24h+ old posts to determine which approach gets more engagement.
 */
export async function analyzeABTests(): Promise<ABTestResult> {
	const result: ABTestResult = {
		postsAnalyzed: 0,
		variantAAvgViews: 0,
		variantBAvgViews: 0,
		winner: "tie",
		velocityScoresUpdated: 0,
	};

	try {
		const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();

		// Get published queue items with engagement data
		const { data: queueItems } = await db()
			.from("auto_post_queue")
			.select(
				"id, source_type, engagement_rate, likes_count, replies_count, reposts_count, group_id",
			)
			.in("status", ["published"])
			.not("source_type", "is", null)
			.gte("created_at", sevenDaysAgo)
			.lte("posted_at", oneDayAgo); // At least 24h old for fair comparison

		if (!queueItems || queueItems.length < 10) {
			logger.info(
				`${LOG_PREFIX} Not enough A/B data (${queueItems?.length || 0} items)`,
			);
			return result;
		}

		// Split by source type
		const variantA = queueItems.filter(
			(i: { source_type: string }) =>
				i.source_type === "ai" || i.source_type === "manual",
		);
		const variantB = queueItems.filter(
			(i: { source_type: string }) =>
				i.source_type === "competitor_copy" ||
				i.source_type === "competitor_direct",
		);

		const avgEngagement = (items: typeof queueItems) => {
			if (items.length === 0) return 0;
			const total = items.reduce((sum: number, i: Record<string, unknown>) => {
				return (
					sum +
					((i.likes_count as number) || 0) +
					((i.replies_count as number) || 0) * 3 +
					((i.reposts_count as number) || 0) * 2
				);
			}, 0);
			return Math.round(total / items.length);
		};

		result.postsAnalyzed = queueItems.length;
		result.variantAAvgViews = avgEngagement(variantA);
		result.variantBAvgViews = avgEngagement(variantB);

		if (variantA.length >= 5 && variantB.length >= 3) {
			const ratio =
				result.variantBAvgViews / Math.max(1, result.variantAAvgViews);
			if (ratio > 1.2) result.winner = "b";
			else if (ratio < 0.8) result.winner = "a";
			else result.winner = "tie";
		}

		// Store results as agent note for MCP visibility
		try {
			const noteContent = JSON.stringify({
				date: new Date().toISOString().split("T")[0]!,
				variantA: {
					count: variantA.length,
					avgEngagement: result.variantAAvgViews,
				},
				variantB: {
					count: variantB.length,
					avgEngagement: result.variantBAvgViews,
				},
				winner: result.winner,
				recommendation:
					result.winner === "b"
						? "Competitor-sourced content is outperforming — lean harder on the competitor lane"
						: result.winner === "a"
							? "Standard AI generation is outperforming — competitor-sourced content may need tuning"
							: "Performance is similar — maintain current mix",
			});

			// Delete existing then insert (cron functions don't have user context)
			await db()
				.from("agent_notes")
				.delete()
				.eq("key", "ab-test-results")
				.is("account_group_id", null);
			await db().from("agent_notes").insert({
				key: "ab-test-results",
				value: noteContent,
				updated_at: new Date().toISOString(),
			});
		} catch {
			// Non-critical
		}

		logger.info(`${LOG_PREFIX} A/B analysis complete`, {
			variantA: variantA.length,
			variantB: variantB.length,
			avgA: result.variantAAvgViews,
			avgB: result.variantBAvgViews,
			winner: result.winner,
		});
	} catch (err) {
		logger.error(`${LOG_PREFIX} A/B analysis failed`, {
			error: serializeError(err),
		});
	}

	return result;
}

// ============================================================================
// Combined Orchestrator
// ============================================================================

export async function processContentABTesting(): Promise<{
	velocityScores: number;
	abTest: ABTestResult;
}> {
	const velocityScores = await computeVelocityScores();
	const abTest = await analyzeABTests();

	return { velocityScores, abTest };
}
