/**
 * Auto-Post Service — shared types.
 */

import type { Platform } from "@/types/platform";

// Media source options for group-specific folders
export type MediaSource = "global" | "group-specific" | "mixed";

// Media mode - how to decide when to attach media
export type MediaMode = "match_competitor" | "random_chance" | "never";

// Auto-post configuration interface
export interface AutoPostConfig {
	enabled: boolean;
	postsPerDay: number; // 6-15 per account
	minIntervalMinutes: number; // 10-60 minutes between posts
	maxIntervalMinutes: number; // For randomization
	mediaAttachmentChance: number; // 0-100% (used when mediaMode is "random_chance")
	mediaSource: MediaSource; // Where to pull media from
	mediaMode: MediaMode; // How to decide when to attach media
	activeHoursStart: number; // 0-23 (e.g., 8 for 8 AM) - in user's timezone
	activeHoursEnd: number; // 0-23 (e.g., 22 for 10 PM) - in user's timezone
	timezone: string; // IANA timezone (e.g., "America/New_York") for active hours
	enableWeekends: boolean;
	roundRobinEnabled: boolean; // Cycle through accounts
	selectedGroups?: string[] | undefined; // Group IDs to auto-post from (empty = all groups)
	lastUpdated?: Date | undefined;
	// Smart Performance Controls
	pauseOnLowPerformance: boolean; // Auto-pause if engagement drops
	performanceThreshold: number; // Minimum engagement rate % (default: 2.0)
	performanceCheckWindow: number; // Number of recent posts to check (default: 10)
	// AI Queue Auto-Fill (generates posts from competitor content when queue is low)
	enableAIQueueFill: boolean; // Auto-generate posts when queue is low
	aiQueueMinThreshold: number; // Min posts in queue before triggering AI (default: 3)
	aiPostsPerFill: number; // Posts to generate per fill (default: 2)
	aiDailyGenerationLimit: number; // Max AI posts per day (default: 10)
	// Custom style guidelines for AI content generation
	aiStyleGuidelines: string; // User-defined rules (e.g., "Always end with a question", "Use bullet points")
	// Smart timing - use AI-analyzed best posting times instead of random intervals
	useSmartTiming: boolean;
	// Auto-unpost duplicate fanout cleanup
	autoUnpostDuplicates?: boolean | undefined;
	autoUnpostWindowHours?: number | undefined;
	autoUnpostKeepTop?: number | undefined;
	// Group Mode - post independently per account group
	groupModeEnabled?: boolean | undefined;
	// Velocity Monitoring
	enableVelocityMonitoring?: boolean | undefined;
	velocityAccelerationThreshold?: number | undefined; // 0.1-20, default 5.0
	velocityDeclineThreshold?: number | undefined; // 0.1-5, default 0.5
	pauseOnDecliningVelocity?: boolean | undefined;
	boostOnViral?: boolean | undefined;
	viralIntervalReductionPct?: number | undefined; // 10-90, step 5, default 50
}

// Queue item for auto-posting
export interface AutoQueueItem {
	postId: string;
	content: string;
	groupId?: string | undefined; // For group-specific media matching
	accountId?: string | undefined; // Real account target when already assigned
	platform?: Platform | undefined; // Target platform (default: threads)
	sourceType?: string | undefined; // ai | competitor_copy | competitor_direct | manual | recycled_direct
	addedAt: Date;
	timesUsed: number;
	lastUsedAt?: Date | undefined;
}

// Auto-post state tracking
export interface AutoPostState {
	currentQueueIndex: number;
	currentAccountIndex: number; // For round-robin
	lastPostTime?: Date | undefined;
	nextPostTime?: Date | undefined; // Random scheduled time for next post
	postsToday: number;
	lastResetDate: string; // YYYY-MM-DD
	accountPostCounts: Record<string, number>; // accountId -> posts today
}

/**
 * Warm-up configuration stored in accounts.ai_config.warmup
 */
export interface AccountWarmupConfig {
	warmup_enabled: boolean;
	warmup_start_posts: number; // Starting posts per day (default: 2)
	warmup_increment: number; // Posts to add each day (default: 2)
	warmup_target: number; // Target daily posts when complete
	warmup_start_date: string | null; // ISO date when warm-up began
	warmup_completed_at: string | null; // ISO date when auto-completed
}

export interface GroupConfig {
	id?: string | undefined;
	workspaceId: string;
	groupId: string;
	postsPerAccountPerDay: number;
	minIntervalMinutes: number;
	activeHoursStart: number;
	activeHoursEnd: number;
	timezone: string;
	postOnWeekends: boolean;
	enabled: boolean;
	autoUnpostOptOut?: boolean | undefined;
}

export interface GroupState {
	id?: string | undefined;
	workspaceId: string;
	groupId: string;
	currentAccountIndex: number;
	currentQueueIndex: number;
	postsToday: number;
	lastPostAt: string | null;
	lastResetDate: string | null;
}
