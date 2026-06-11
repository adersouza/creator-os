/**
 * Trend Pipeline Types
 *
 * Shared interfaces for the trend filtering, dedup, format rotation,
 * and config-gating modules consumed by the cron orchestrator and generator.
 */

import type { TrendResult } from "../../grokSearch.js";
import type { ExtractedStyle, VoiceProfile } from "../auto-post/types.js";

// Re-export for convenience
export type { ExtractedStyle, TrendResult, VoiceProfile };

/**
 * Matches the `trending_topic_config` table shape.
 */
export interface TrendConfig {
	id: string;
	account_group_id: string; // TEXT FK
	user_id: string; // TEXT FK
	enabled: boolean;
	keywords: string[];
	scan_frequency_hours: number; // default 4
	daily_post_cap: number; // default 3
	blocklist: string[];
	content_preferences: Record<string, unknown>;
	last_scan_at: string | null;
	created_at: string;
	updated_at: string;
}

/**
 * A trend that survived filtering, enriched with a dedup hash.
 */
export interface FilteredTrend extends TrendResult {
	topicHash: string;
}

/**
 * Result summary for a single account group's pipeline run.
 */
export interface TrendPipelineResult {
	groupId: string;
	trendsFound: number;
	postsQueued: number;
	skippedReasons: string[];
}

/**
 * The 4 trend-specific output formats (distinct from auto-post CONTENT_TYPES).
 */
export type TrendFormat = "hot_take" | "analysis" | "question" | "thread_style";
