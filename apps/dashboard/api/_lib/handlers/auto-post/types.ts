/**
 * Auto-Post Worker Type Definitions
 *
 * Shared interfaces used across all auto-post modules.
 */

// ============================================================================
// Configuration
// ============================================================================

// Rate limits per Threads API documentation (250/day official)
export const RATE_LIMITS = {
	POSTS_PER_HOUR: 25,
	POSTS_PER_DAY: 250,
};

// ============================================================================
// Core Interfaces
// ============================================================================

export interface AutoPostConfig {
	workspace_id: string;
	is_enabled: boolean;
	platform?: "threads" | "instagram" | "both" | undefined;
	posting_times: {
		media_chance: number;
		media_mode?: "match_competitor" | "random_chance" | "never" | undefined;
		selected_groups?: string[] | undefined;
		timezone?: string | undefined;
	};
	pause_on_low_performance: boolean;
	performance_threshold: number;
	// AI Queue Auto-Fill settings
	enable_ai_queue_fill?: boolean | undefined;
	ai_queue_min_threshold?: number | undefined;
	ai_posts_per_fill?: number | undefined;
	ai_daily_generation_limit?: number | undefined;
	ai_generations_today?: number | undefined;
	ai_last_generation_date?: string | undefined;
	ai_style_guidelines?: string | undefined;
	use_smart_timing?: boolean | undefined;
	// Group mode
	group_mode_enabled?: boolean | undefined;
	// Deprecated legacy knobs — preserved for backward compatibility only.
	// Queue-fill source mix now follows sourcePolicy.ts instead.
	competitor_copy_ratio?: number | undefined;
	competitor_copy_max_words?: number | undefined;
	// Engagement velocity controls (Empire tier)
	enable_velocity_monitoring?: boolean | undefined;
	velocity_acceleration_threshold?: number | undefined;
	velocity_decline_threshold?: number | undefined;
	pause_on_declining_velocity?: boolean | undefined;
	boost_on_viral?: boolean | undefined;
	viral_interval_reduction_pct?: number | undefined;
}

export interface AutoPostState {
	workspace_id: string;
	current_queue_index: number;
	current_account_index: number;
	last_post_at: string | null;
	next_post_time: string | null;
	posts_today: number;
	posts_this_hour: number;
	last_reset_date: string;
	account_post_counts: Record<string, number>;
	consecutive_failures: number;
	last_cron_run_at?: string | null | undefined;
}

export interface QueueItem {
	id: string;
	workspace_id: string;
	account_id: string | null;
	content: string;
	status: string;
	scheduled_for: string;
	created_at: string;
	media_urls?: string[] | null | undefined;
	source_content?: string | null | undefined;
	retry_count?: number | undefined;
	next_retry_at?: string | null | undefined;
	last_error?: string | null | undefined;
	/** Origin: 'manual', 'ai', 'competitor_copy', 'competitor_direct', 'recycled_direct' */
	source_type?: string | null | undefined;
	/** Spoiler trick metadata: { word, charOffset, charLength } */
	text_spoilers?: string | Record<string, unknown> | null | undefined;
	/** Notification-style topic tag shown as bold header above post */
	topic_tag?: string | null | undefined;
}

export interface Account {
	id: string;
	user_id: string;
	username: string;
	threads_user_id: string;
	threads_access_token_encrypted: string;
	status: string;
	ai_config?:
		| {
				warmup?:
					| {
							warmup_enabled: boolean;
							warmup_start_posts: number;
							warmup_increment: number;
							warmup_target: number;
							warmup_start_date: string | null;
							warmup_completed_at: string | null;
					  }
					| undefined;
				extracted_style?: ExtractedStyle | undefined;
		  }
		| undefined;
}

export interface PostingResult {
	success: boolean;
	threadId?: string | undefined;
	error?: string | undefined;
	retryable?: boolean | undefined;
}

export interface IGPostingResultInternal {
	success: boolean;
	mediaId?: string | undefined;
	containerId?: string | undefined;
	error?: string | undefined;
	retryable?: boolean | undefined;
	permalink?: string | undefined;
}

export interface CompetitorPost {
	id: string;
	content: string;
	competitor_username: string;
	engagement_score: number;
	like_count: number;
	reply_count: number;
	media_type?: string | undefined;
	metric_quality?: string | undefined;
	hook_type?: string | undefined;
	topic_label?: string | undefined;
}

export interface ExtractedStyle {
	hooks?: { patterns?: string[] | undefined } | undefined;
	vocabulary?: { signature_words?: string[] | undefined } | undefined;
	emoji_usage?:
		| {
				frequency?: string | undefined;
				placement?: string | undefined;
				favorites?: string[] | undefined;
		  }
		| undefined;
	length?:
		| { typical_chars?: string | undefined; preference?: string | undefined }
		| undefined;
	tone?: { vibe?: string | undefined; energy?: string | undefined } | undefined;
	punctuation?: { quirks?: string[] | undefined } | undefined;
}

export interface VoiceProfile {
	voice_profile?: string | undefined;
	focus_topics?: string[] | undefined;
	avoid_topics?: string[] | undefined;
	avoid_words?: string[] | undefined;
	emoji_usage?: "none" | "minimal" | "moderate" | "heavy" | undefined;
	cta_style?: "none" | "link_in_bio" | "dm_me" | "subscribe" | undefined;
	// Voice Profile Engineering 2026: per-group calibration
	vulnerability_ratio?: number | undefined; // 0-1, default 0.25
	sentence_length_target?:
		| {
				avg: number;
				variance: "low" | "moderate" | "high" | "very_high";
				min: number;
				max: number;
		  }
		| undefined;
	time_of_day_modifiers?:
		| {
				morning?: string | undefined;
				afternoon?: string | undefined;
				evening?: string | undefined;
				latenight?: string | undefined;
		  }
		| undefined;
}

// ============================================================================
// Group Mode Interfaces
// ============================================================================

export interface GroupConfig {
	id: string;
	workspace_id: string;
	group_id: string;
	posts_per_account_per_day: number;
	min_interval_minutes: number;
	max_interval_minutes?: number | undefined;
	active_hours_start: number;
	active_hours_end: number;
	timezone: string;
	post_on_weekends: boolean;
	enabled: boolean;
	// Auto-reply settings
	enable_auto_reply?: boolean | undefined;
	auto_reply_trigger_count?: number | undefined;
	auto_reply_window_hours?: number | undefined;
	auto_reply_daily_limit?: number | undefined;
	auto_reply_ratio?: number | undefined;
}

export interface AccountOverride {
	account_id: string;
	group_id: string;
	overrides: Partial<Omit<GroupConfig, "id" | "workspace_id" | "group_id">>;
}

export interface AccountOverride {
	account_id: string;
	group_id: string;
	overrides: Partial<Omit<GroupConfig, "id" | "workspace_id" | "group_id">>;
}

export interface GroupState {
	id?: string | undefined;
	workspace_id: string;
	group_id: string;
	current_account_index: number;
	current_queue_index: number;
	posts_today: number;
	last_post_at: string | null;
	last_reset_date: string | null;
	last_cron_run_at?: string | null | undefined;
	ig_current_account_index?: number | undefined;
	ig_current_queue_index?: number | undefined;
	ig_posts_today?: number | undefined;
	ig_last_post_at?: string | null | undefined;
}

export interface GroupInfo {
	id: string;
	name: string;
	account_ids: string[];
	voice_profile?: string | undefined;
}

// ============================================================================
// AI Content Generation Interfaces
// ============================================================================

export interface UserAIConfig {
	provider: string;
	apiKey: string;
	baseUrl?: string | undefined;
	model?: string | undefined;
}

export interface TopPost {
	content: string;
	likes: number;
	replies: number;
	reposts: number;
}

export interface GeneratedPostIdea {
	content: string;
	viralScore: number;
	promptVersion?: string | undefined;
	templateId?: string | undefined;
	modelProvider?: string | undefined;
	sourceMediaType?: string | undefined;
	sourceContent?: string | undefined;
	sourcePatternId?: string | undefined;
	strategyRecommendationId?: string | undefined;
	strategyRecommendationPatternType?: string | undefined;
	strategyRecommendationConfidence?: number | undefined;
	cloneFamily?: string | undefined;
	winnerClone?: boolean | undefined;
	contentType?: string | undefined;
	sourceCompetitorId?: string | undefined;
	sourceCompetitorUsername?: string | undefined;
	targetAccountId?: string | undefined;
	targetRoundRobinIndex?: number | undefined;
	targetIsProbe?: boolean | undefined;
	/** Spoiler trick metadata — word + which chars to hide */
	spoilerMeta?:
		| { word: string; charOffset: number; charLength: number }
		| null
		| undefined;
}

// ============================================================================
// Timing Insights (Smart Scheduling)
// ============================================================================

export interface TimingInsights {
	bestPostingHours?: number[] | undefined; // UTC hours from data_driven_insights
	peakWindows?: Array<{ day: string; hour: number }> | undefined; // manual peak windows
	timezone?: string | undefined; // e.g., "America/New_York"
	activeHoursStart?: number | undefined; // 0-23
	activeHoursEnd?: number | undefined; // 0-23
}

// ============================================================================
// Insights Interfaces
// ============================================================================

export interface AutoPostInsights {
	lastComputedAt: string;
	postCount: number;
	avgEngagementRate: number;
	bestPostingHours: number[];
	bestPostingDays: number[];
	optimalIntervalMinutes: number;
	contentTypePerformance: {
		withMedia: { avgEngagement: number; count: number };
		textOnly: { avgEngagement: number; count: number };
	};
	topPerformingQueue: string[];
	recommendations: string[];
}

// ============================================================================
// Worker Stats
// ============================================================================

export interface WorkerStats {
	workspacesChecked: number;
	postsPublished: number;
	skipped: number;
	failed: number;
	errors: string[];
}
