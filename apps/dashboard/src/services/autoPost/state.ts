// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Service — state read/write.
 */

import { createServiceLogger, supabase } from "../api/shared";
import { getSupabaseUserId, getWorkspaceId } from "./internal";
import type { AutoPostState } from "./types";

const log = createServiceLogger("autoPostService.state");

// Default state
const DEFAULT_AUTO_POST_STATE: AutoPostState = {
	currentQueueIndex: 0,
	currentAccountIndex: 0,
	postsToday: 0,
	lastResetDate: new Date().toISOString().split("T")[0]!,
	accountPostCounts: {},
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
