/**
 * Auto-Post Service — configuration + toggle.
 */

import { apiUrl } from "@/lib/apiUrl";
import { createServiceLogger, supabase } from "../api/shared";
import { postAutoPostAction } from "./apiClient";
import {
	getBrowserTimezone,
	getCurrentHourInTimezone,
	getDateForHourInTimezone,
	getSupabaseUserId,
	getWorkspaceId,
	isValidTimezone,
	requireWorkspaceId,
} from "./internal";
import type { AutoPostConfig } from "./types";

const log = createServiceLogger("autoPostService.config");

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
	autoUnpostDuplicates: false,
	autoUnpostWindowHours: 6,
	autoUnpostKeepTop: 1,
};

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
				.upsert(
					{
						workspace_id: wsId,
						is_enabled: DEFAULT_AUTO_POST_CONFIG.enabled,
						posting_times: {
							posts_per_day: DEFAULT_AUTO_POST_CONFIG.postsPerDay,
							min_interval: DEFAULT_AUTO_POST_CONFIG.minIntervalMinutes,
							max_interval: DEFAULT_AUTO_POST_CONFIG.maxIntervalMinutes,
							media_chance: DEFAULT_AUTO_POST_CONFIG.mediaAttachmentChance,
							media_source: DEFAULT_AUTO_POST_CONFIG.mediaSource,
							active_hours_start: DEFAULT_AUTO_POST_CONFIG.activeHoursStart,
							active_hours_end: DEFAULT_AUTO_POST_CONFIG.activeHoursEnd,
							timezone: DEFAULT_AUTO_POST_CONFIG.timezone,
							enable_weekends: DEFAULT_AUTO_POST_CONFIG.enableWeekends,
							round_robin_enabled: DEFAULT_AUTO_POST_CONFIG.roundRobinEnabled,
						},
						pause_on_low_performance:
							DEFAULT_AUTO_POST_CONFIG.pauseOnLowPerformance,
						performance_threshold:
							DEFAULT_AUTO_POST_CONFIG.performanceThreshold,
					},
					{ onConflict: "workspace_id", ignoreDuplicates: true },
				);
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
			postsPerDay: postingTimes.posts_per_day ?? 8,
			minIntervalMinutes: postingTimes.min_interval ?? 20,
			maxIntervalMinutes: postingTimes.max_interval ?? 45,
			mediaAttachmentChance: postingTimes.media_chance ?? 50,
			mediaSource: postingTimes.media_source ?? "global",
			mediaMode: postingTimes.media_mode ?? "random_chance",
			activeHoursStart: postingTimes.active_hours_start ?? 8,
			activeHoursEnd: postingTimes.active_hours_end ?? 22,
			timezone: postingTimes.timezone ?? getBrowserTimezone(),
			enableWeekends: postingTimes.enable_weekends ?? true,
			roundRobinEnabled:
				postingTimes.round_robin_enabled ??
				DEFAULT_AUTO_POST_CONFIG.roundRobinEnabled,
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
			autoUnpostDuplicates: Boolean(
				postingTimes.auto_unpost_duplicates ?? false,
			),
			autoUnpostWindowHours: Number(postingTimes.auto_unpost_window_hours ?? 6),
			autoUnpostKeepTop: Number(postingTimes.auto_unpost_keep_top ?? 1),
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
		if ("postsPerDay" in config)
			postingTimes.posts_per_day = Math.min(
				Math.max(config.postsPerDay ?? 1, 1),
				20,
			);
		if ("roundRobinEnabled" in config)
			postingTimes.round_robin_enabled = Boolean(config.roundRobinEnabled);
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
		if ("autoUnpostDuplicates" in config)
			postingTimes.auto_unpost_duplicates = Boolean(
				config.autoUnpostDuplicates,
			);
		if ("autoUnpostWindowHours" in config)
			postingTimes.auto_unpost_window_hours = Math.min(
				Math.max(Math.round(config.autoUnpostWindowHours ?? 6), 1),
				168,
			);
		if ("autoUnpostKeepTop" in config)
			postingTimes.auto_unpost_keep_top = Math.min(
				Math.max(Math.round(config.autoUnpostKeepTop ?? 1), 1),
				10,
			);

		if (Object.keys(postingTimes).length > 0) {
			const { data: existingConfig } = await supabase
				.from("auto_post_config")
				.select("posting_times")
				.eq("workspace_id", wsId)
				.maybeSingle();
			supabaseConfig.posting_times = {
				...((existingConfig?.posting_times as Record<string, unknown> | null) ??
					{}),
				...postingTimes,
			};
		}

		const result = await postAutoPostAction<{ config?: { is_enabled?: boolean | undefined } | undefined }>(
			"upsert-workspace-config",
			supabaseConfig,
			{
				idempotencyKey: `auto-config:save:${wsId}:${Object.keys(config).sort().join("-")}`,
			},
		);

		if ("enabled" in config && result.config?.is_enabled !== config.enabled) {
			log.error(
				"MISMATCH! Tried to save enabled:",
				config.enabled,
				"but got:",
				result.config?.is_enabled,
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
					await fetch(apiUrl("/api/auto-post?action=log-activity"), {
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
					await fetch(apiUrl("/api/auto-post?action=log-activity"), {
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
