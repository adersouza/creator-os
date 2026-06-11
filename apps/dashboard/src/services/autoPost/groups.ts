/**
 * Auto-Post Service — Group Mode operations.
 */

import { createServiceLogger, dbQuery, supabase } from "../api/shared";
import { getBrowserTimezone, getWorkspaceId } from "./internal";
import { postAutoPostAction } from "./apiClient";
import type { AutoQueueItem, GroupConfig, GroupState } from "./types";

const log = createServiceLogger("autoPostService.groups");

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
	autoUnpostOptOut: false,
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
		autoUnpostOptOut: Boolean(row.content_sources?.auto_unpost_opt_out ?? false),
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
	let contentSources: Record<string, unknown> | undefined;
	if (config.autoUnpostOptOut !== undefined) {
		const { data: existing } = await supabase
			.from("auto_post_group_config")
			.select("content_sources")
			.eq("workspace_id", config.workspaceId)
			.eq("group_id", config.groupId)
			.maybeSingle();
		contentSources = {
			...((existing?.content_sources as Record<string, unknown> | null) ?? {}),
			auto_unpost_opt_out: Boolean(config.autoUnpostOptOut),
		};
	}
	const payload: Record<string, unknown> = {
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
		};
	if (contentSources) payload.content_sources = contentSources;

	const { error } = await supabase.from("auto_post_group_config").upsert(
		// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert type narrowing
		payload as any,
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
	try {
		const result = await postAutoPostAction<{ inserted?: number | undefined }>(
			"add-queue-items",
			{
				workspaceId,
				groupId,
				items: items.map((item) => ({
					content: item.content,
					platform: "threads",
				})),
			},
			{
				idempotencyKey: `group-queue:add:${workspaceId}:${groupId}:${items.length}:${hashGroupQueueItems(items)}`,
			},
		);
		return result.inserted ?? 0;
	} catch (error) {
		log.error("Failed to add group queue items:", error);
		return 0;
	}
};

function hashGroupQueueItems(items: { content: string }[]): string {
	let hash = 2166136261;
	const text = items.map((item) => item.content).join("\n---\n");
	for (let i = 0; i < text.length; i += 1) {
		hash ^= text.charCodeAt(i);
		hash = Math.imul(hash, 16777619);
	}
	return (hash >>> 0).toString(16);
}
