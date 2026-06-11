/**
 * Trend Filtering, Dedup, and Config-Gating
 *
 * Pure-logic functions for filtering raw Grok trend results,
 * checking dedup constraints, daily post caps, and scan frequency.
 */

import * as crypto from "node:crypto";
import type { TrendResult } from "../../grokSearch.js";
import type { FilteredTrend, TrendConfig } from "./types.js";

/**
 * Normalize a topic string and return a truncated SHA-256 hash (32 hex chars).
 * Normalization: lowercase, trim, strip non-alphanumeric (except spaces), collapse whitespace.
 */
export function computeTopicHash(topic: string): string {
	const normalized = topic
		.toLowerCase()
		.trim()
		.replace(/[^a-z0-9 ]/g, "")
		.replace(/\s+/g, " ");

	return crypto
		.createHash("sha256")
		.update(normalized)
		.digest("hex")
		.slice(0, 32);
}

/**
 * Filter trends by minimum relevance score and blocklist terms.
 * Returns surviving trends enriched with a topic hash for dedup.
 */
export function filterTrends(
	trends: TrendResult[],
	blocklist: string[],
	minScore: number = 75,
): FilteredTrend[] {
	const lowerBlocklist = blocklist.map((term) => term.toLowerCase());

	return trends
		.filter((trend) => {
			// Score gate
			if (trend.relevanceScore < minScore) return false;

			// Blocklist gate
			const combined = `${trend.topic} ${trend.context}`.toLowerCase();
			for (const term of lowerBlocklist) {
				if (combined.includes(term)) return false;
			}

			return true;
		})
		.map((trend) => ({
			...trend,
			topicHash: computeTopicHash(trend.topic),
		}));
}

/**
 * Check if a trend (by topic hash) has already been discovered for this account group.
 * Uses .maybeSingle() to avoid errors on zero rows.
 */
export async function isAlreadyDiscovered(
	// biome-ignore lint/suspicious/noExplicitAny: Supabase client passed from getSupabaseAny()
	db: any,
	accountGroupId: string,
	topicHash: string,
): Promise<boolean> {
	const { data } = await db
		.from("trend_discoveries")
		.select("id")
		.eq("account_group_id", accountGroupId)
		.eq("topic_hash", topicHash)
		.maybeSingle();

	return data !== null;
}

/**
 * Count how many trends have been posted today (UTC) for this account group.
 */
export async function getTodayPostCount(
	// biome-ignore lint/suspicious/noExplicitAny: Supabase client passed from getSupabaseAny()
	db: any,
	accountGroupId: string,
): Promise<number> {
	const todayMidnight = new Date();
	todayMidnight.setUTCHours(0, 0, 0, 0);

	const { count } = await db
		.from("trend_discoveries")
		.select("id", { count: "exact", head: true })
		.eq("account_group_id", accountGroupId)
		.in("status", ["queued", "posted", "needs_review"])
		.gte("posted_at", todayMidnight.toISOString());

	return count ?? 0;
}

/**
 * Determine if an account group should be scanned based on config state.
 * Returns false if disabled, true if never scanned, or true if enough time has elapsed.
 */
export function shouldScanGroup(config: TrendConfig): boolean {
	if (!config.enabled) return false;
	if (!config.last_scan_at) return true;

	const lastScan = new Date(config.last_scan_at).getTime();
	const now = Date.now();
	const hoursSinceScan = (now - lastScan) / (1000 * 60 * 60);

	return hoursSinceScan >= config.scan_frequency_hours;
}

/**
 * Engagement acceleration scoring (Trend Prediction 2026, Section 3).
 * 2nd derivative of engagement velocity is more predictive than raw velocity.
 * Returns acceleration score: >2 = strong signal, >4 = very strong.
 *
 * Also classifies trend shape for remaining runway estimation:
 * - spike: 24h golden window (most common)
 * - gradual: 3-7 day window (safer to join)
 * - recurring: periodic, always relevant
 */
export function scoreTrendAcceleration(
	relevanceScore: number,
	engagementVelocity?: number,
): {
	accelerationScore: number;
	trendShape: "spike" | "gradual" | "recurring" | "unknown";
	isHighPriority: boolean;
} {
	// Base score from Grok's relevance (0-100)
	const baseScore = relevanceScore / 100;

	// Engagement velocity proxy (from Grok search metadata)
	// High relevance + recency = high acceleration
	const velocity =
		engagementVelocity ??
		(relevanceScore > 90 ? 3 : relevanceScore > 80 ? 2 : 1);

	// Acceleration approximation: score ≥ 90 with high velocity = spike
	const accelerationScore = baseScore * velocity;

	// Shape classification based on score distribution
	let trendShape: "spike" | "gradual" | "recurring" | "unknown" = "unknown";
	if (relevanceScore >= 90) trendShape = "spike";
	else if (relevanceScore >= 80) trendShape = "gradual";
	else if (relevanceScore >= 75) trendShape = "recurring";

	// High priority = acceleration score > 2 (speed queue candidate)
	const isHighPriority = accelerationScore > 2.0;

	return { accelerationScore, trendShape, isHighPriority };
}

/**
 * Check if a trend has decayed past its useful window (Trend Prediction 2026, Section 7).
 * Auto-stop when TrendScore drops below 30% of peak.
 * Uses discovery time as a proxy — spikes decay in 24h, gradual in 3-7 days.
 */
export async function hasTrendDecayed(
	// biome-ignore lint/suspicious/noExplicitAny: Supabase client
	db: any,
	accountGroupId: string,
	topicHash: string,
): Promise<boolean> {
	const { data } = await db
		.from("trend_discoveries")
		.select("posted_at, relevance_score")
		.eq("account_group_id", accountGroupId)
		.eq("topic_hash", topicHash)
		.order("posted_at", { ascending: false })
		.limit(1)
		.maybeSingle();

	if (!data?.posted_at) return false;

	const hoursSinceDiscovery =
		(Date.now() - new Date(data.posted_at as string).getTime()) /
		(1000 * 60 * 60);
	const score = (data.relevance_score as number) || 75;

	// Spikes (score ≥ 90): decay after 24h. Gradual (80-89): 72h. Recurring: 168h (7 days)
	const maxWindow = score >= 90 ? 24 : score >= 80 ? 72 : 168;

	return hoursSinceDiscovery > maxWindow;
}
