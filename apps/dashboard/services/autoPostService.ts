// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Service
 * Manages the Smart Auto-Poster queue and configuration for Empire tier
 * Features: Round-robin posting, group-specific media, anti-ban safety
 */

import type { Platform } from "@/src/types/platform.js";
import {
	addToAutoQueue as addToAutoQueueViaApi,
	clearAutoQueue as clearAutoQueueViaApi,
	removeFromAutoQueue as removeFromAutoQueueViaApi,
	reorderAutoQueue as reorderAutoQueueViaApi,
} from "@/services/autoPost/queue.js";
import {
	createServiceLogger,
	dbQuery,
	getUserIdAsync,
	supabase,
} from "./api/shared.js";

const log = createServiceLogger("autoPostService");

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	try {
		return await getUserIdAsync();
	} catch {
		return null;
	}
};

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

// Helper to get browser timezone
const getBrowserTimezone = (): string => {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone;
	} catch {
		return "UTC";
	}
};

function isValidTimezone(tz: string): boolean {
	try {
		Intl.DateTimeFormat(undefined, { timeZone: tz });
		return true;
	} catch {
		return false;
	}
}

/**
 * Get current hour in a specific timezone
 */
export const getCurrentHourInTimezone = (timezone: string): number => {
	const tz = isValidTimezone(timezone) ? timezone : "UTC";
	try {
		const formatter = new Intl.DateTimeFormat("en-US", {
			timeZone: tz,
			hour: "numeric",
			hour12: false,
		});
		const hour = parseInt(formatter.format(new Date()), 10);
		return hour === 24 ? 0 : hour;
	} catch {
		return new Date().getHours();
	}
};

/**
 * Get current day of week in a specific timezone (0 = Sunday, 6 = Saturday)
 */
export const getCurrentDayInTimezone = (timezone: string): number => {
	const tz = isValidTimezone(timezone) ? timezone : "UTC";
	try {
		const formatter = new Intl.DateTimeFormat("en-US", {
			timeZone: tz,
			weekday: "short",
		});
		const dayStr = formatter.format(new Date());
		const dayMap: Record<string, number> = {
			Sun: 0,
			Mon: 1,
			Tue: 2,
			Wed: 3,
			Thu: 4,
			Fri: 5,
			Sat: 6,
		};
		return dayMap[dayStr] ?? new Date().getDay();
	} catch {
		return new Date().getDay();
	}
};

/**
 * Calculate a Date object for a specific hour in a timezone
 * Used to schedule posts at the right time regardless of server timezone
 */
const getDateForHourInTimezone = (
	hour: number,
	timezone: string,
	addDays: number = 0,
): Date => {
	const tz = isValidTimezone(timezone) ? timezone : "UTC";
	const now = new Date();

	// Get current date parts in target timezone
	const formatter = new Intl.DateTimeFormat("en-US", {
		timeZone: tz,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	});
	const parts = formatter.formatToParts(now);
	const year = parseInt(
		parts.find((p) => p.type === "year")?.value || "2024",
		10,
	);
	const month =
		parseInt(parts.find((p) => p.type === "month")?.value || "1", 10) - 1;
	const day =
		parseInt(parts.find((p) => p.type === "day")?.value || "1", 10) + addDays;

	// Create date at the target hour in the target timezone
	// We use an iterative approach to handle DST and half-hour offsets
	let guess = new Date(Date.UTC(year, month, day, hour));

	// Get what hour our guess represents in the target timezone
	const getHourInTz = (d: Date): number => {
		return (
			parseInt(
				new Intl.DateTimeFormat("en-US", {
					timeZone: tz,
					hour: "numeric",
					hour12: false,
				}).format(d),
				10,
			) % 24
		);
	};

	// Adjust for timezone offset (iterate to handle DST edge cases)
	for (let i = 0; i < 3; i++) {
		const actualHour = getHourInTz(guess);
		if (actualHour === hour) break;
		const diff = hour - actualHour;
		guess = new Date(guess.getTime() + diff * 60 * 60 * 1000);
	}

	return guess;
};

// Default configuration
export const DEFAULT_AUTO_POST_CONFIG: AutoPostConfig = {
	enabled: false,
	postsPerDay: 8,
	minIntervalMinutes: 20,
	maxIntervalMinutes: 45,
	mediaAttachmentChance: 50,
	mediaSource: "global",
	mediaMode: "random_chance",
	activeHoursStart: 8,
	activeHoursEnd: 22,
	timezone: getBrowserTimezone(), // Use browser timezone as default
	enableWeekends: true,
	roundRobinEnabled: true,
	selectedGroups: [],
	// Smart Performance Controls
	pauseOnLowPerformance: false,
	performanceThreshold: 2.0,
	performanceCheckWindow: 10,
	// AI Queue Auto-Fill
	enableAIQueueFill: false,
	aiQueueMinThreshold: 3,
	aiPostsPerFill: 2,
	aiDailyGenerationLimit: 10,
	aiStyleGuidelines: "", // Empty = use default AI behavior
	useSmartTiming: false,
};

// Default state
const DEFAULT_AUTO_POST_STATE: AutoPostState = {
	currentQueueIndex: 0,
	currentAccountIndex: 0,
	postsToday: 0,
	lastResetDate: new Date().toISOString().split("T")[0]!,
	accountPostCounts: {},
};

/**
 * Get the workspace ID for the current user
 * (In production, this would come from workspace context)
 */
const getWorkspaceId = async (): Promise<string | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	// Get user's default workspace (first one they own)
	const { data, error } = await supabase
		.from("workspaces")
		.select("id")
		.eq("owner_id", userId)
		.limit(1)
		.maybeSingle();

	if (error || !data) return null;
	return data.id;
};

/**
 * Resolve workspaceId, throwing if none can be found.
 * Use in top-level callers that cannot proceed without a workspace.
 */
async function requireWorkspaceId(workspaceId?: string): Promise<string> {
	const id = workspaceId || (await getWorkspaceId());
	if (!id) throw new Error("No workspace found");
	return id;
}

/**
 * Get auto-post configuration for a workspace
 * Creates the config document with defaults if it doesn't exist
 */
export const getAutoPostConfig = async (
	workspaceId?: string,
): Promise<AutoPostConfig> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return DEFAULT_AUTO_POST_CONFIG;
	}

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) {
			log.debug("No workspace found, using defaults");
			return DEFAULT_AUTO_POST_CONFIG;
		}

		const { data, error } = await supabase
			.from("auto_post_config")
			.select("*")
			.eq("workspace_id", wsId)
			.maybeSingle();

		if (error) {
			log.error("Error fetching config:", error);
			throw error;
		}

		if (!data) {
			// No config found, create with defaults
			log.debug("No config found, creating with defaults");
			// Map DEFAULT_AUTO_POST_CONFIG to Supabase column names
			const { error: insertError } = await supabase
				.from("auto_post_config")
				.insert({
					workspace_id: wsId,
					is_enabled: DEFAULT_AUTO_POST_CONFIG.enabled,
					posts_per_day: DEFAULT_AUTO_POST_CONFIG.postsPerDay,
					account_rotation: DEFAULT_AUTO_POST_CONFIG.roundRobinEnabled
						? "round_robin"
						: "sequential",
					posting_times: {
						min_interval: DEFAULT_AUTO_POST_CONFIG.minIntervalMinutes,
						max_interval: DEFAULT_AUTO_POST_CONFIG.maxIntervalMinutes,
						media_chance: DEFAULT_AUTO_POST_CONFIG.mediaAttachmentChance,
						media_source: DEFAULT_AUTO_POST_CONFIG.mediaSource,
						active_hours_start: DEFAULT_AUTO_POST_CONFIG.activeHoursStart,
						active_hours_end: DEFAULT_AUTO_POST_CONFIG.activeHoursEnd,
						timezone: DEFAULT_AUTO_POST_CONFIG.timezone,
						enable_weekends: DEFAULT_AUTO_POST_CONFIG.enableWeekends,
					},
					pause_on_low_performance:
						DEFAULT_AUTO_POST_CONFIG.pauseOnLowPerformance,
					performance_threshold: DEFAULT_AUTO_POST_CONFIG.performanceThreshold,
				});
			if (insertError) {
				// Insert failed — log but still return defaults (don't throw)
				log.error("Failed to insert default config:", insertError);
			}
			return DEFAULT_AUTO_POST_CONFIG;
		}

		// Parse posting_times JSON if it exists
		// biome-ignore lint/suspicious/noExplicitAny: Supabase JSON column lacks TypeScript definition
		const postingTimes = (data?.posting_times || {}) as any;
		// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
		const configData = data as any;

		return {
			enabled: configData?.is_enabled ?? false,
			postsPerDay: configData?.posts_per_day ?? 8,
			minIntervalMinutes: postingTimes.min_interval ?? 20,
			maxIntervalMinutes: postingTimes.max_interval ?? 45,
			mediaAttachmentChance: postingTimes.media_chance ?? 50,
			mediaSource: postingTimes.media_source ?? "global",
			mediaMode: postingTimes.media_mode ?? "random_chance",
			activeHoursStart: postingTimes.active_hours_start ?? 8,
			activeHoursEnd: postingTimes.active_hours_end ?? 22,
			timezone: postingTimes.timezone ?? getBrowserTimezone(),
			enableWeekends: postingTimes.enable_weekends ?? true,
			roundRobinEnabled: configData?.account_rotation === "round_robin",
			selectedGroups: postingTimes.selected_groups ?? [],
			lastUpdated: configData?.updated_at
				? new Date(configData.updated_at)
				: undefined,
			pauseOnLowPerformance: configData?.pause_on_low_performance ?? false,
			performanceThreshold: configData?.performance_threshold ?? 2.0,
			performanceCheckWindow: postingTimes.performance_check_window ?? 10,
			// AI Queue Auto-Fill
			enableAIQueueFill: configData?.enable_ai_queue_fill ?? false,
			aiQueueMinThreshold: configData?.ai_queue_min_threshold ?? 3,
			aiPostsPerFill: configData?.ai_posts_per_fill ?? 2,
			aiDailyGenerationLimit: configData?.ai_daily_generation_limit ?? 10,
			aiStyleGuidelines: configData?.ai_style_guidelines ?? "",
			useSmartTiming: configData?.use_smart_timing ?? false,
		};
	} catch (error) {
		log.error("Failed to get config:", error);
		return DEFAULT_AUTO_POST_CONFIG;
	}
};

/**
 * Save auto-post configuration
 */
export const saveAutoPostConfig = async (
	config: Partial<AutoPostConfig>,
	workspaceId?: string,
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return false;
	}

	try {
		const wsId = await requireWorkspaceId(workspaceId);

		// Validate timezone before saving
		if ("timezone" in config && config.timezone) {
			if (!isValidTimezone(config.timezone)) {
				log.error("Invalid timezone rejected", {
					timezone: config.timezone,
				});
				return false;
			}
		}

		log.debug("Saving config:", JSON.stringify(config), "to workspace:", wsId);

		// Map camelCase to snake_case for Supabase
		const supabaseConfig: Record<string, unknown> = {
			workspace_id: wsId,
			updated_at: new Date().toISOString(),
		};

		if ("enabled" in config) supabaseConfig.is_enabled = config.enabled;
		if ("postsPerDay" in config)
			supabaseConfig.posts_per_day = Math.min(
				Math.max(config.postsPerDay ?? 1, 1),
				20,
			);
		if ("roundRobinEnabled" in config)
			supabaseConfig.account_rotation = config.roundRobinEnabled
				? "round_robin"
				: "sequential";
		if ("pauseOnLowPerformance" in config)
			supabaseConfig.pause_on_low_performance = config.pauseOnLowPerformance;
		if ("performanceThreshold" in config)
			supabaseConfig.performance_threshold = config.performanceThreshold;
		// AI Queue Auto-Fill settings (stored as direct columns)
		if ("enableAIQueueFill" in config)
			supabaseConfig.enable_ai_queue_fill = config.enableAIQueueFill;
		if ("aiQueueMinThreshold" in config)
			supabaseConfig.ai_queue_min_threshold = config.aiQueueMinThreshold;
		if ("aiPostsPerFill" in config)
			supabaseConfig.ai_posts_per_fill = config.aiPostsPerFill;
		if ("aiDailyGenerationLimit" in config)
			supabaseConfig.ai_daily_generation_limit = config.aiDailyGenerationLimit;
		if ("aiStyleGuidelines" in config)
			supabaseConfig.ai_style_guidelines = config.aiStyleGuidelines;
		if ("useSmartTiming" in config)
			supabaseConfig.use_smart_timing = config.useSmartTiming;

		// Store timing/media config in posting_times JSON column
		const postingTimes: Record<string, unknown> = {};
		if ("minIntervalMinutes" in config)
			postingTimes.min_interval = config.minIntervalMinutes;
		if ("maxIntervalMinutes" in config)
			postingTimes.max_interval = config.maxIntervalMinutes;
		if ("mediaAttachmentChance" in config)
			postingTimes.media_chance = config.mediaAttachmentChance;
		if ("mediaSource" in config) postingTimes.media_source = config.mediaSource;
		if ("mediaMode" in config) postingTimes.media_mode = config.mediaMode;
		if ("activeHoursStart" in config)
			postingTimes.active_hours_start = config.activeHoursStart;
		if ("activeHoursEnd" in config)
			postingTimes.active_hours_end = config.activeHoursEnd;
		if ("timezone" in config) postingTimes.timezone = config.timezone;
		if ("enableWeekends" in config)
			postingTimes.enable_weekends = config.enableWeekends;
		if ("performanceCheckWindow" in config)
			postingTimes.performance_check_window = config.performanceCheckWindow;
		if ("selectedGroups" in config)
			postingTimes.selected_groups = config.selectedGroups;

		if (Object.keys(postingTimes).length > 0) {
			supabaseConfig.posting_times = postingTimes;
		}

		const { error } = await supabase
			.from("auto_post_config")
			// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert type narrowing
			.upsert(supabaseConfig as any, { onConflict: "workspace_id" });

		if (error) throw error;

		// Verify the write
		const { data: verifyData, error: verifyError } = await supabase
			.from("auto_post_config")
			.select("is_enabled")
			.eq("workspace_id", wsId)
			.maybeSingle();

		if (verifyError || !verifyData) {
			log.error("Config doc does not exist after save!");
			return false;
		}

		// Check if enabled value matches what we tried to save
		if ("enabled" in config && verifyData.is_enabled !== config.enabled) {
			log.error(
				"MISMATCH! Tried to save enabled:",
				config.enabled,
				"but got:",
				verifyData.is_enabled,
			);
			return false;
		}

		log.debug("Config saved and verified successfully");
		return true;
	} catch (error: unknown) {
		log.error(
			"Failed to save config:",
			error instanceof Error ? error.message : error,
		);
		return false;
	}
};

/**
 * Toggle auto-post enabled/disabled
 * When enabling, also sets a random nextPostTime
 * Returns { success, warning? } — warning is set if enabling with an empty queue
 */
export const toggleAutoPost = async (
	enabled: boolean,
	workspaceId?: string,
): Promise<boolean | { success: boolean; warning?: string | undefined }> => {
	log.debug(
		"toggleAutoPost called - enabled:",
		enabled,
		"workspaceId:",
		workspaceId,
	);

	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const wsId = await requireWorkspaceId(workspaceId);

		// Check if queue is empty when enabling — warn but don't block
		if (enabled) {
			const { count } = await supabase
				.from("auto_post_queue")
				.select("*", { count: "exact", head: true })
				.eq("workspace_id", wsId)
				.in("status", ["queued", "pending"]);

			if ((count ?? 0) === 0) {
				log.warn("Enabling auto-poster with empty queue", {
					wsId,
				});
				// Still save the config but return a warning so callers can inform the user
				const result = await saveAutoPostConfig({ enabled }, wsId);
				if (!result) return false;
				return {
					success: true,
					warning:
						"Auto-poster enabled but queue is empty. Add posts or enable AI Auto-Fill.",
				};
			}
		}

		// Save the config
		const result = await saveAutoPostConfig({ enabled }, wsId);
		log.debug("toggleAutoPost config result:", result);

		// If enabling, set an initial random nextPostTime within active hours.
		//
		// NOTE on atomicity: This check-then-write on auto_post_state is safe because:
		// 1. saveAutoPostConfig() uses upsert with onConflict:"workspace_id", making the
		//    config toggle itself atomic at the DB level.
		// 2. The frontend handleToggle() uses an isToggling guard that prevents double-toggles.
		// 3. The existingState check below only decides whether to seed an initial
		//    next_post_time — a benign race here at worst results in a slightly different
		//    first-post delay, which the cron self-corrects on its next run.
		if (enabled && result) {
			// Check if state already exists - if so, don't overwrite next_post_time
			// This allows: 1) user to clear it for immediate posting, 2) cron to manage it after first post
			const { data: existingState } = await supabase
				.from("auto_post_state")
				.select("next_post_time")
				.eq("workspace_id", wsId)
				.maybeSingle();

			// Only set initial next_post_time if NO state exists (first time enabling)
			// If state exists (even with NULL next_post_time), let the cron handle scheduling
			if (existingState) {
				log.debug("State exists, letting cron manage next_post_time");
				return result;
			}

			const config = await getAutoPostConfig(wsId);
			const timezone = config.timezone || "UTC";
			const range = config.maxIntervalMinutes - config.minIntervalMinutes;
			const randomMinutes = config.minIntervalMinutes + Math.random() * range;
			const totalMinutes = Math.min(randomMinutes, config.maxIntervalMinutes);

			// Calculate initial next post time
			let nextPostTime = new Date(Date.now() + totalMinutes * 60 * 1000);

			// Ensure nextPostTime is within active hours (using user's timezone)
			const is24_7 =
				config.activeHoursEnd === 24 ||
				(config.activeHoursStart === 0 && config.activeHoursEnd === 0);

			if (!is24_7) {
				const effectiveEnd =
					config.activeHoursEnd === 0 ? 24 : config.activeHoursEnd;
				// Get the hour in user's timezone
				const hourInUserTz = getCurrentHourInTimezone(timezone);

				// If outside active hours, jump to next valid time in user's timezone
				if (hourInUserTz >= effectiveEnd) {
					// Jump to next day's start hour in user's timezone
					nextPostTime = getDateForHourInTimezone(
						config.activeHoursStart,
						timezone,
						1,
					);
					// Add some random minutes within the first hour
					nextPostTime = new Date(
						nextPostTime.getTime() + Math.random() * 30 * 60 * 1000,
					);
				} else if (hourInUserTz < config.activeHoursStart) {
					// Jump to today's start hour in user's timezone
					nextPostTime = getDateForHourInTimezone(
						config.activeHoursStart,
						timezone,
						0,
					);
					// Add some random minutes within the first hour
					nextPostTime = new Date(
						nextPostTime.getTime() + Math.random() * 30 * 60 * 1000,
					);
				}
			}

			const roundedMinutes = Math.round(
				(nextPostTime.getTime() - Date.now()) / 60000,
			);

			log.debug(`Setting initial nextPostTime in ${roundedMinutes} minutes`);

			// Update the state with nextPostTime in Supabase
			await supabase.from("auto_post_state").upsert(
				{
					workspace_id: wsId,
					next_post_time: nextPostTime.toISOString(),
					updated_at: new Date().toISOString(),
				},
				{ onConflict: "workspace_id" },
			);

			// Log to Activity Feed via Vercel API
			try {
				const {
					data: { session },
				} = await supabase.auth.getSession();
				if (session) {
					await fetch("/api/auto-post?action=log-activity", {
						method: "POST",
						headers: {
							"Content-Type": "application/json",
							Authorization: `Bearer ${session.access_token}`,
						},
						body: JSON.stringify({
							workspaceId: wsId,
							activityType: "scheduled",
							accountHandle: "Auto-Poster",
							postIndex: 1,
							nextPostIn: roundedMinutes,
							message: `Engine started! First post in ${roundedMinutes}m`,
						}),
					});
				}
			} catch (logError) {
				log.error("Failed to log activity:", logError);
			}
		}

		// If disabling, log that too
		if (!enabled && result) {
			try {
				const {
					data: { session },
				} = await supabase.auth.getSession();
				if (session) {
					await fetch("/api/auto-post?action=log-activity", {
						method: "POST",
						headers: {
							"Content-Type": "application/json",
							Authorization: `Bearer ${session.access_token}`,
						},
						body: JSON.stringify({
							workspaceId: wsId,
							activityType: "skipped",
							accountHandle: "Auto-Poster",
							postIndex: 0,
							message: "Engine stopped",
						}),
					});
				}
			} catch (logError) {
				log.error("Failed to log activity:", logError);
			}
		}

		return result;
	} catch (error) {
		log.error("toggleAutoPost error:", error);
		return false;
	}
};

/**
 * Get the auto-post queue
 */
export const getAutoQueue = async (
	workspaceId?: string,
): Promise<AutoQueueItem[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return [];
	}

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) {
			log.debug("No workspace found");
			return [];
		}

		const { data, error } = await supabase
			.from("auto_post_queue")
			.select("*")
			.eq("workspace_id", wsId)
			.in("status", ["queued", "pending"]) // Only show active queue items
			.order("created_at", { ascending: true });

		if (error) throw error;

		const queue: AutoQueueItem[] = (data || []).map((row) => ({
			postId: row.id,
			content: row.content,
			groupId: row.group_id || undefined,
			accountId:
				row.account_id && row.account_id !== row.group_id
					? row.account_id
					: undefined,
			addedAt: row.created_at ? new Date(row.created_at) : new Date(),
			timesUsed: row.retry_count || 0,
			lastUsedAt: row.posted_at ? new Date(row.posted_at) : undefined,
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row may have extra columns not in generated types
			platform: (row as any).platform || "threads",
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row may have extra columns not in generated types
			sourceType: (row as any).source_type || undefined,
		}));

		log.debug("Loaded queue items:", queue.length);
		return queue;
	} catch (error) {
		log.error("Failed to get queue:", error);
		return [];
	}
};

/**
 * Add an item to the auto-post queue
 */
export const addToAutoQueue = async (
	content: string,
	groupId?: string,
	workspaceId?: string,
	platform: Platform = "threads",
): Promise<{ success: boolean; error?: string | undefined }> => {
	return addToAutoQueueViaApi(content, groupId, workspaceId, platform);
};

/**
 * Remove an item from the auto-post queue
 */
export const removeFromAutoQueue = async (
	postId: string,
	workspaceId?: string,
): Promise<boolean> => {
	return removeFromAutoQueueViaApi(postId, workspaceId);
};

/**
 * Reorder items in the auto-post queue
 */
export const reorderAutoQueue = async (
	orderedPostIds: string[],
	workspaceId?: string,
): Promise<boolean> => {
	return reorderAutoQueueViaApi(orderedPostIds, workspaceId);
};

/**
 * Get auto-post state (current indices, counts, etc.)
 */
export const getAutoPostState = async (
	workspaceId?: string,
): Promise<AutoPostState> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return DEFAULT_AUTO_POST_STATE;
	}

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) {
			return DEFAULT_AUTO_POST_STATE;
		}

		const { data, error } = await supabase
			.from("auto_post_state")
			.select("*")
			.eq("workspace_id", wsId)
			.maybeSingle();

		if (error) {
			log.error("Error fetching state:", error);
			throw error;
		}

		if (!data) return DEFAULT_AUTO_POST_STATE;

		// UTC is intentional here: the cron worker runs server-side where UTC is the
		// canonical clock. Per-user timezone adjustments happen in canAutoPostNow().
		const today = new Date().toISOString().split("T")[0]!;

		// Reset counts if it's a new day
		if (data.last_reset_date !== today) {
			return {
				...DEFAULT_AUTO_POST_STATE,
				currentQueueIndex: data.current_queue_index || 0,
				currentAccountIndex: data.current_account_index || 0,
			};
		}

		// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
		const stateData = data as any;
		return {
			currentQueueIndex: stateData.current_queue_index || 0,
			currentAccountIndex: stateData.current_account_index || 0,
			lastPostTime: stateData.last_post_at
				? new Date(stateData.last_post_at)
				: undefined,
			nextPostTime: stateData.next_post_time
				? new Date(stateData.next_post_time)
				: undefined,
			postsToday: stateData.posts_today || 0,
			lastResetDate: stateData.last_reset_date || today,
			accountPostCounts: (stateData.account_post_counts || {}) as Record<
				string,
				number
			>,
		};
	} catch (error) {
		log.error("Failed to get state:", error);
		return DEFAULT_AUTO_POST_STATE;
	}
};

/**
 * Update auto-post state after a post
 */
export const updateAutoPostState = async (
	updates: Partial<AutoPostState>,
	workspaceId?: string,
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return false;
	}

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) {
			log.error("No workspace found");
			return false;
		}

		// Map camelCase to snake_case
		const supabaseUpdates: Record<string, unknown> = {
			workspace_id: wsId,
			updated_at: new Date().toISOString(),
		};

		if ("currentQueueIndex" in updates)
			supabaseUpdates.current_queue_index = updates.currentQueueIndex;
		if ("currentAccountIndex" in updates)
			supabaseUpdates.current_account_index = updates.currentAccountIndex;
		if ("lastPostTime" in updates)
			supabaseUpdates.last_post_at = updates.lastPostTime?.toISOString();
		if ("nextPostTime" in updates)
			supabaseUpdates.next_post_time = updates.nextPostTime?.toISOString();
		if ("postsToday" in updates)
			supabaseUpdates.posts_today = updates.postsToday;
		if ("lastResetDate" in updates)
			supabaseUpdates.last_reset_date = updates.lastResetDate;
		if ("accountPostCounts" in updates)
			supabaseUpdates.account_post_counts = updates.accountPostCounts;

		const { error } = await supabase
			.from("auto_post_state")
			// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert type narrowing
			.upsert(supabaseUpdates as any, { onConflict: "workspace_id" });

		if (error) throw error;

		return true;
	} catch (error) {
		log.error("Failed to update state:", error);
		return false;
	}
};

/**
 * Get the next post from the queue (with loop-around).
 *
 * IMPORTANT: Callers MUST check for `item === null` before proceeding.
 * A null item means the queue is empty — the caller should log and return early.
 * Example:
 *   const { item } = await getNextQueueItem(wsId);
 *   if (!item) { logger.info("Queue empty, nothing to post"); return; }
 */
export const getNextQueueItem = async (
	workspaceId?: string,
): Promise<{ item: AutoQueueItem | null; index: number }> => {
	const queue = await getAutoQueue(workspaceId);
	const state = await getAutoPostState(workspaceId);

	if (queue.length === 0) {
		return { item: null, index: -1 };
	}

	// Loop around if we've reached the end
	const index = state.currentQueueIndex % queue.length;
	return { item: queue[index]!, index };
};

/**
 * Mark a queue item as used (increment counter, update timestamp)
 */
export const markQueueItemUsed = async (
	postId: string,
	workspaceId?: string,
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) return false;

		// Get current retry count
		const { data: currentItem, error: fetchError } = await supabase
			.from("auto_post_queue")
			.select("retry_count")
			.eq("id", postId)
			.eq("workspace_id", wsId)
			.maybeSingle();

		if (fetchError || !currentItem) return false;

		const currentRetryCount = currentItem.retry_count || 0;

		const { error } = await supabase
			.from("auto_post_queue")
			.update({
				retry_count: currentRetryCount + 1,
				posted_at: new Date().toISOString(),
			})
			.eq("id", postId)
			.eq("workspace_id", wsId);

		if (error) throw error;

		return true;
	} catch (error) {
		log.error("Failed to mark item used:", error);
		return false;
	}
};

/**
 * Add multiple favorites to the auto-queue
 */
export const addFavoritesToAutoQueue = async (
	favorites: Array<{ content: string; groupId?: string | undefined }>,
	workspaceId?: string,
): Promise<number> => {
	let added = 0;

	for (const fav of favorites) {
		const result = await addToAutoQueue(fav.content, fav.groupId, workspaceId);
		if (result.success) added++;
	}

	log.debug(`Added ${added}/${favorites.length} favorites to queue`);
	return added;
};

/**
 * Clear the entire auto-post queue
 */
export const clearAutoQueue = async (
	workspaceId?: string,
): Promise<boolean> => {
	return clearAutoQueueViaApi(workspaceId);
};

/**
 * Check if auto-posting should be allowed right now
 * (based on active hours, weekend settings, rate limits)
 *
 * NOTE: This function is used for UI display only. It does NOT check subscription
 * tier (Empire) or account suspension status. Tier enforcement happens at the API
 * level in api/auto-post.ts (requireEmpireTier). Account suspension is checked by
 * the cron worker (auto-post-worker.ts) before each post attempt.
 */
export const canAutoPostNow = async (
	config: AutoPostConfig,
	state: AutoPostState,
	accountId: string,
): Promise<{ allowed: boolean; reason?: string | undefined }> => {
	const now = new Date();
	const timezone = config.timezone || "UTC";

	// Get current hour and day in user's timezone
	const currentHour = getCurrentHourInTimezone(timezone);
	const currentDay = getCurrentDayInTimezone(timezone);
	const isWeekend = currentDay === 0 || currentDay === 6;

	// Check weekend setting
	if (isWeekend && !config.enableWeekends) {
		return { allowed: false, reason: "Weekend posting disabled" };
	}

	// Check if 24/7 mode (end=24 or start=0 with end=0)
	const is24_7 =
		config.activeHoursEnd === 24 ||
		(config.activeHoursStart === 0 && config.activeHoursEnd === 0);

	// Check active hours (skip check in 24/7 mode)
	if (!is24_7) {
		const effectiveEnd =
			config.activeHoursEnd === 0 ? 24 : config.activeHoursEnd;
		if (currentHour < config.activeHoursStart || currentHour >= effectiveEnd) {
			return {
				allowed: false,
				reason: `Outside active hours (${config.activeHoursStart}:00-${effectiveEnd === 24 ? "00" : effectiveEnd}:00 ${timezone})`,
			};
		}
	}

	// Check per-account daily limit (max 15 per account for safety)
	const accountPostCount = state.accountPostCounts[accountId] || 0;
	if (accountPostCount >= 15) {
		return { allowed: false, reason: "Account daily limit reached (15 posts)" };
	}

	// Check minimum interval since last post
	if (state.lastPostTime) {
		const minutesSinceLastPost =
			(now.getTime() - state.lastPostTime.getTime()) / 60000;
		if (minutesSinceLastPost < config.minIntervalMinutes) {
			return {
				allowed: false,
				reason: `Minimum interval not met (${Math.ceil(config.minIntervalMinutes - minutesSinceLastPost)} min remaining)`,
			};
		}
	}

	return { allowed: true };
};

/**
 * Recalculate nextPostTime based on current config active hours
 * Called when config changes while auto-poster is enabled
 */
export const recalculateNextPostTime = async (
	workspaceId?: string,
): Promise<Date | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) return null;

		const config = await getAutoPostConfig(wsId);
		if (!config.enabled) return null;

		const timezone = config.timezone || "UTC";
		const state = await getAutoPostState(wsId);

		// Calculate base next post time
		const range = config.maxIntervalMinutes - config.minIntervalMinutes;
		const randomMinutes = config.minIntervalMinutes + Math.random() * range;
		const baseTime = state.lastPostTime
			? new Date(state.lastPostTime.getTime() + randomMinutes * 60 * 1000)
			: new Date(Date.now() + randomMinutes * 60 * 1000);

		let nextPostTime = baseTime > new Date() ? baseTime : new Date();

		// Ensure nextPostTime is within active hours (using user's timezone)
		const is24_7 =
			config.activeHoursEnd === 24 ||
			(config.activeHoursStart === 0 && config.activeHoursEnd === 0);

		if (!is24_7) {
			const effectiveEnd =
				config.activeHoursEnd === 0 ? 24 : config.activeHoursEnd;
			// Get current hour in user's timezone
			const hourInUserTz = getCurrentHourInTimezone(timezone);

			if (hourInUserTz >= effectiveEnd) {
				// Jump to next day's start hour in user's timezone
				nextPostTime = getDateForHourInTimezone(
					config.activeHoursStart,
					timezone,
					1,
				);
				nextPostTime = new Date(
					nextPostTime.getTime() + Math.random() * 30 * 60 * 1000,
				);
			} else if (hourInUserTz < config.activeHoursStart) {
				// Jump to today's start hour in user's timezone
				nextPostTime = getDateForHourInTimezone(
					config.activeHoursStart,
					timezone,
					0,
				);
				nextPostTime = new Date(
					nextPostTime.getTime() + Math.random() * 30 * 60 * 1000,
				);
			}
		}

		// Save to database
		await supabase.from("auto_post_state").upsert(
			{
				workspace_id: wsId,
				next_post_time: nextPostTime.toISOString(),
				updated_at: new Date().toISOString(),
			},
			{ onConflict: "workspace_id" },
		);

		log.debug(`Recalculated nextPostTime: ${nextPostTime.toISOString()}`);
		return nextPostTime;
	} catch (error) {
		log.error("Failed to recalculate nextPostTime:", error);
		return null;
	}
};

/**
 * Calculate next random interval for human-like posting
 * Interval is always WITHIN the configured min/max bounds
 */
export const getRandomInterval = (config: AutoPostConfig): number => {
	const range = config.maxIntervalMinutes - config.minIntervalMinutes;
	const randomMinutes = config.minIntervalMinutes + Math.random() * range;
	// Clamp to max to ensure we never exceed user's configured interval
	const clampedMinutes = Math.min(randomMinutes, config.maxIntervalMinutes);
	return Math.round(clampedMinutes * 60 * 1000); // Return milliseconds
};

/**
 * Get media for a post based on config settings and group
 * Uses the mediaSource setting to determine where to pull media from
 * Returns { media, warning } - warning set if fallback used or no media available
 */
export const getMediaForPost = async (
	config: AutoPostConfig,
	groupId?: string,
): Promise<{ mediaUrl: string | null; warning?: string | undefined }> => {
	// Import media service dynamically to avoid circular deps
	const { getRandomMediaForGroup, getRandomMedia } = await import(
		"./mediaService.js"
	);

	// Check if we should even try to attach media
	const shouldAttachMedia = Math.random() * 100 < config.mediaAttachmentChance;
	if (!shouldAttachMedia) {
		return { mediaUrl: null };
	}

	const mediaSource = config.mediaSource || "global";

	try {
		// Global mode: pull from entire library
		if (mediaSource === "global") {
			const media = await getRandomMedia(true);
			return { mediaUrl: media?.url || null };
		}

		// Group-specific mode: only pull from group folder
		if (mediaSource === "group-specific") {
			if (!groupId) {
				return {
					mediaUrl: null,
					warning: "No group specified for group-specific media",
				};
			}

			const media = await getRandomMediaForGroup(groupId, true);
			if (!media) {
				return {
					mediaUrl: null,
					warning: `No media in group folder — posting text only`,
				};
			}
			return { mediaUrl: media.url };
		}

		// Mixed mode: prefer group, fallback to global
		if (mediaSource === "mixed") {
			if (groupId) {
				const groupMedia = await getRandomMediaForGroup(groupId, true);
				if (groupMedia) {
					return { mediaUrl: groupMedia.url };
				}
				// Fallback to global
				const globalMedia = await getRandomMedia(true);
				if (globalMedia) {
					return {
						mediaUrl: globalMedia.url,
						warning: "Using global media (no group media available)",
					};
				}
			} else {
				// No group, use global
				const media = await getRandomMedia(true);
				return { mediaUrl: media?.url || null };
			}
		}

		return { mediaUrl: null };
	} catch (error) {
		log.error("Failed to get media for post:", error);
		return { mediaUrl: null, warning: "Failed to fetch media" };
	}
};

// ============================================================================
// ACCOUNT WARM-UP FEATURE
// Gradual ramp-up for new/inactive accounts to avoid spam detection
// ============================================================================

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

export const DEFAULT_WARMUP_CONFIG: AccountWarmupConfig = {
	warmup_enabled: false,
	warmup_start_posts: 2,
	warmup_increment: 2,
	warmup_target: 15,
	warmup_start_date: null,
	warmup_completed_at: null,
};

/**
 * Get warm-up configuration for an account
 */
export const getAccountWarmupConfig = async (
	accountId: string,
): Promise<AccountWarmupConfig> => {
	try {
		const { data, error } = await supabase
			.from("accounts")
			.select("ai_config")
			.eq("id", accountId)
			.maybeSingle();

		if (error || !data?.ai_config) {
			return { ...DEFAULT_WARMUP_CONFIG };
		}

		const aiConfig = data.ai_config as { warmup?: AccountWarmupConfig | undefined };
		return aiConfig.warmup
			? { ...DEFAULT_WARMUP_CONFIG, ...aiConfig.warmup }
			: { ...DEFAULT_WARMUP_CONFIG };
	} catch (error) {
		log.error("Failed to get warmup config:", error);
		return { ...DEFAULT_WARMUP_CONFIG };
	}
};

/**
 * Save warm-up configuration for an account
 */
export const saveAccountWarmupConfig = async (
	accountId: string,
	warmupConfig: Partial<AccountWarmupConfig>,
): Promise<boolean> => {
	try {
		// Get existing ai_config
		const { data: existingData } = await supabase
			.from("accounts")
			.select("ai_config")
			.eq("id", accountId)
			.maybeSingle();

		const existingAIConfig = (existingData?.ai_config || {}) as Record<
			string,
			unknown
		>;
		const existingWarmup =
			(existingAIConfig.warmup as AccountWarmupConfig) || DEFAULT_WARMUP_CONFIG;

		const updatedWarmup = {
			...existingWarmup,
			...warmupConfig,
		};

		const { error } = await supabase
			.from("accounts")
			.update({
				ai_config: {
					...existingAIConfig,
					warmup: updatedWarmup,
				},
			})
			.eq("id", accountId);

		if (error) throw error;
		return true;
	} catch (error) {
		log.error("Failed to save warmup config:", error);
		return false;
	}
};

/**
 * Enable warm-up for an account (sets start date to today)
 */
export const enableAccountWarmup = async (
	accountId: string,
	config?: Partial<AccountWarmupConfig>,
): Promise<boolean> => {
	return saveAccountWarmupConfig(accountId, {
		...config,
		warmup_enabled: true,
		warmup_start_date: new Date().toISOString().split("T")[0]!,
		warmup_completed_at: null, // Reset completion
	});
};

/**
 * Disable warm-up for an account
 */
export const disableAccountWarmup = async (
	accountId: string,
): Promise<boolean> => {
	return saveAccountWarmupConfig(accountId, {
		warmup_enabled: false,
	});
};

/**
 * Calculate warm-up progress for display
 */
export const getWarmupProgress = (
	config: AccountWarmupConfig,
): {
	currentDay: number;
	totalDays: number;
	todayAllowance: number;
	isComplete: boolean;
	percentComplete: number;
} => {
	if (!config.warmup_enabled || !config.warmup_start_date) {
		return {
			currentDay: 0,
			totalDays: 0,
			todayAllowance: 15,
			isComplete: true,
			percentComplete: 100,
		};
	}

	// If already completed, return completed state
	if (config.warmup_completed_at) {
		const postsToAdd = config.warmup_target - config.warmup_start_posts;
		const totalDays = Math.ceil(postsToAdd / config.warmup_increment) + 1;
		return {
			currentDay: totalDays,
			totalDays,
			todayAllowance: config.warmup_target,
			isComplete: true,
			percentComplete: 100,
		};
	}

	const startDate = new Date(config.warmup_start_date);
	const today = new Date();
	startDate.setHours(0, 0, 0, 0);
	today.setHours(0, 0, 0, 0);

	const daysSinceStart = Math.floor(
		(today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24),
	);

	const currentDay = daysSinceStart + 1;
	const todayAllowance = Math.min(
		config.warmup_start_posts + daysSinceStart * config.warmup_increment,
		config.warmup_target,
	);

	const isComplete = todayAllowance >= config.warmup_target;
	const totalDays =
		config.warmup_increment > 0
			? Math.ceil(
					(config.warmup_target - config.warmup_start_posts) /
						config.warmup_increment,
				) + 1
			: 1;
	const percentComplete = isComplete
		? 100
		: Math.min(99, Math.round((currentDay / totalDays) * 100));

	return {
		currentDay,
		totalDays,
		todayAllowance,
		isComplete,
		percentComplete,
	};
};

/**
 * Calculate warm-up allowance for use in auto-post-worker
 * Returns null if warm-up is disabled or completed (use normal limit)
 */
export const calculateWarmupAllowance = (
	warmup: AccountWarmupConfig | null,
): number | null => {
	if (!warmup?.warmup_enabled || !warmup.warmup_start_date) {
		return null;
	}

	// If already completed, return null (use normal limit)
	if (warmup.warmup_completed_at) {
		return null;
	}

	const startDate = new Date(warmup.warmup_start_date);
	const today = new Date();
	startDate.setHours(0, 0, 0, 0);
	today.setHours(0, 0, 0, 0);

	// DST note: This day-level calculation is DST-safe because both dates are
	// normalized to local midnight (setHours(0,0,0,0)). A DST transition shifts
	// both by the same offset, so the difference in milliseconds still yields the
	// correct whole-day count. The ±1h DST delta is absorbed by Math.floor on a
	// 86,400,000ms divisor and never crosses a day boundary.
	const daysSinceStart = Math.floor(
		(today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24),
	);

	const allowance =
		warmup.warmup_start_posts + daysSinceStart * warmup.warmup_increment;

	// Cap at target
	return Math.min(allowance, warmup.warmup_target);
};

// ============================================================================
// Group Mode Types & Methods
// ============================================================================

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

export const DEFAULT_GROUP_CONFIG: Omit<
	GroupConfig,
	"workspaceId" | "groupId"
> = {
	postsPerAccountPerDay: 4,
	minIntervalMinutes: 90,
	activeHoursStart: 8,
	activeHoursEnd: 22,
	timezone: getBrowserTimezone(),
	postOnWeekends: true,
	enabled: true,
};

/**
 * Check if group mode is enabled for a workspace
 */
export const isGroupModeEnabled = async (
	workspaceId?: string,
): Promise<boolean> => {
	const wsId = workspaceId || (await getWorkspaceId());
	if (!wsId) return false;

	const { data } = await supabase
		.from("auto_post_config")
		.select("group_mode_enabled")
		.eq("workspace_id", wsId)
		.maybeSingle();

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	return (data as any)?.group_mode_enabled ?? false;
};

/**
 * Enable or disable group mode for a workspace
 */
export const setGroupModeEnabled = async (
	enabled: boolean,
	workspaceId?: string,
): Promise<boolean> => {
	const wsId = workspaceId || (await getWorkspaceId());
	if (!wsId) return false;

	const { error } = await supabase
		.from("auto_post_config")
		// biome-ignore lint/suspicious/noExplicitAny: Supabase update type narrowing
		.update({ group_mode_enabled: enabled } as any)
		.eq("workspace_id", wsId);

	if (error) {
		log.error("Error toggling group mode:", error);
		return false;
	}
	return true;
};

// In-memory cache for group configs (2-minute TTL)
const GROUP_CONFIG_CACHE_TTL = 2 * 60 * 1000; // 2 minutes
let groupConfigCache: {
	data: GroupConfig[];
	timestamp: number;
	wsId: string;
} | null = null;

/**
 * Get all group configs for a workspace
 */
export const getGroupConfigs = async (
	workspaceId?: string,
): Promise<GroupConfig[]> => {
	const wsId = workspaceId || (await getWorkspaceId());
	if (!wsId) return [];

	// Return cached data if still fresh and for the same workspace
	if (
		groupConfigCache &&
		groupConfigCache.wsId === wsId &&
		Date.now() - groupConfigCache.timestamp < GROUP_CONFIG_CACHE_TTL
	) {
		return groupConfigCache.data;
	}

	const rows = await dbQuery(
		supabase
			.from("auto_post_group_config")
			.select("*")
			.eq("workspace_id", wsId),
		"[autoPostService] Error fetching group configs",
		// biome-ignore lint/suspicious/noExplicitAny: dbQuery fallback array type
		[] as any[],
	);

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	const configs = (rows || []).map((row: any) => ({
		id: row.id,
		workspaceId: row.workspace_id,
		groupId: row.group_id,
		postsPerAccountPerDay: row.posts_per_account_per_day,
		minIntervalMinutes: row.min_interval_minutes,
		activeHoursStart: row.active_hours_start,
		activeHoursEnd: row.active_hours_end,
		timezone: row.timezone,
		postOnWeekends: row.post_on_weekends,
		enabled: row.enabled,
	}));

	// Update cache
	groupConfigCache = { data: configs, timestamp: Date.now(), wsId };

	return configs;
};

/**
 * Create or update a group config
 */
export const upsertGroupConfig = async (
	config: GroupConfig,
): Promise<boolean> => {
	const { error } = await supabase.from("auto_post_group_config").upsert(
		{
			workspace_id: config.workspaceId,
			group_id: config.groupId,
			posts_per_account_per_day: config.postsPerAccountPerDay,
			min_interval_minutes: config.minIntervalMinutes,
			active_hours_start: config.activeHoursStart,
			active_hours_end: config.activeHoursEnd,
			timezone: config.timezone,
			post_on_weekends: config.postOnWeekends,
			enabled: config.enabled,
			updated_at: new Date().toISOString(),
			// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert type narrowing
		} as any,
		{ onConflict: "workspace_id,group_id" },
	);

	if (error) {
		log.error("Error upserting group config:", error);
		return false;
	}
	// Invalidate group config cache after mutation
	groupConfigCache = null;
	return true;
};

/**
 * Delete a group config
 */
export const deleteGroupConfig = async (
	workspaceId: string,
	groupId: string,
): Promise<boolean> => {
	const { error } = await supabase
		.from("auto_post_group_config")
		.delete()
		.eq("workspace_id", workspaceId)
		.eq("group_id", groupId);

	if (error) {
		log.error("Error deleting group config:", error);
		return false;
	}
	// Invalidate group config cache after mutation
	groupConfigCache = null;
	return true;
};

/**
 * Get all group states for a workspace
 */
export const getGroupStates = async (
	workspaceId?: string,
): Promise<GroupState[]> => {
	const wsId = workspaceId || (await getWorkspaceId());
	if (!wsId) return [];

	const data = await dbQuery(
		supabase.from("auto_post_group_state").select("*").eq("workspace_id", wsId),
		"[autoPostService] Error fetching group states",
		// biome-ignore lint/suspicious/noExplicitAny: dbQuery fallback array type
		[] as any[],
	);

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	return (data || []).map((row: any) => ({
		id: row.id,
		workspaceId: row.workspace_id,
		groupId: row.group_id,
		currentAccountIndex: row.current_account_index,
		currentQueueIndex: row.current_queue_index,
		postsToday: row.posts_today,
		lastPostAt: row.last_post_at,
		lastResetDate: row.last_reset_date,
	}));
};

/**
 * Get queue items for a specific group
 */
export const getGroupQueue = async (
	workspaceId: string,
	groupId: string,
): Promise<AutoQueueItem[]> => {
	const data = await dbQuery(
		supabase
			.from("auto_post_queue")
			.select("*")
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId)
			.in("status", ["queued", "pending"])
			.order("created_at", { ascending: true }),
		"[autoPostService] Error fetching group queue",
		// biome-ignore lint/suspicious/noExplicitAny: dbQuery fallback array type
		[] as any[],
	);

	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	return (data || []).map((row: any) => ({
		postId: row.id,
		content: row.content,
		groupId: row.group_id,
		addedAt: new Date(row.created_at),
		timesUsed: 0,
	}));
};

/**
 * Add items to a group's queue
 */
export const addToGroupQueue = async (
	workspaceId: string,
	groupId: string,
	items: { content: string }[],
): Promise<number> => {
	let insertedCount = 0;
	for (const item of items) {
		const { error } = await supabase.from("auto_post_queue").insert({
			workspace_id: workspaceId,
			group_id: groupId,
			content: item.content,
			status: "pending",
			scheduled_for: new Date().toISOString(),
		});
		if (!error) insertedCount++;
	}
	return insertedCount;
};
