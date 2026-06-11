// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Service — queue operations.
 */

import type { Platform } from "@/types/platform";
import { createServiceLogger, supabase } from "../api/shared";
import { getSupabaseUserId, getWorkspaceId } from "./internal";
import { postAutoPostAction } from "./apiClient";
import { getAutoPostState, updateAutoPostState } from "./state";
import type { AutoQueueItem } from "./types";

const log = createServiceLogger("autoPostService.queue");

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
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return { success: false, error: "Not logged in" };
	}

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) {
			log.error("No workspace found");
			return { success: false, error: "No workspace found" };
		}

		// Check max queue size
		const MAX_QUEUE_SIZE = 500;
		const { count } = await supabase
			.from("auto_post_queue")
			.select("*", { count: "exact", head: true })
			.eq("workspace_id", wsId)
			.in("status", ["queued", "pending"]);

		if ((count ?? 0) >= MAX_QUEUE_SIZE) {
			return {
				success: false,
				error: `Queue is full (maximum ${MAX_QUEUE_SIZE} items)`,
			};
		}

		// Check for duplicate content
		const { data: existing } = await supabase
			.from("auto_post_queue")
			.select("id")
			.eq("workspace_id", wsId)
			.eq("content", content)
			.in("status", ["queued", "pending"])
			.limit(1);

		if (existing && existing.length > 0) {
			return { success: false, error: "This content is already in the queue" };
		}

		const data = await postAutoPostAction<{ inserted?: number | undefined }>(
			"add-queue-items",
			{
				workspaceId: wsId,
				groupId: groupId || null,
				items: [{ content, platform }],
			},
			{
				idempotencyKey: `auto-queue:add:${wsId}:${groupId || "workspace"}:${hashQueueContent(content)}:${platform}`,
			},
		);

		log.debug("Added to queue:", data?.inserted ?? 0);
		return { success: (data?.inserted ?? 0) > 0 };
	} catch (error) {
		log.error("Failed to add to queue:", error);
		return { success: false, error: "Failed to add to queue" };
	}
};

/**
 * Remove an item from the auto-post queue
 */
export const removeFromAutoQueue = async (
	postId: string,
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

		await postAutoPostAction("delete-queue-item", {
			queueItemId: postId,
			dryRun: false,
		}, {
			idempotencyKey: `auto-queue:delete:${wsId}:${postId}`,
		});

		log.debug("Removed from queue:", postId);
		return true;
	} catch (error) {
		log.error("Failed to remove from queue:", error);
		return false;
	}
};

/**
 * Reorder items in the auto-post queue
 */
export const reorderAutoQueue = async (
	orderedPostIds: string[],
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

		// Update each item's created_at to reflect new order.
		// NOTE: There is no dedicated order_index/position column on auto_post_queue,
		// so we repurpose created_at with millisecond offsets as a pragmatic ordering
		// mechanism. The queue is always read with ORDER BY created_at ASC, so this
		// produces the correct visual order. Trade-off: created_at no longer reflects
		// the actual insertion time after a reorder, but the queue is ephemeral and
		// the original add-time is not displayed to users.
		const baseTime = Date.now();
		await postAutoPostAction("reorder-queue", {
			workspaceId: wsId,
			orderedPostIds,
			baseTime,
		}, {
			idempotencyKey: `auto-queue:reorder:${wsId}:${hashQueueContent(orderedPostIds.join(","))}`,
		});

		log.debug("Queue reordered");
		return true;
	} catch (error) {
		log.error("Failed to reorder queue:", error);
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
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const wsId = workspaceId || (await getWorkspaceId());
		if (!wsId) return false;

		await postAutoPostAction("bulk-clear-all-queues", {
			workspaceId: wsId,
			dryRun: false,
		}, {
			idempotencyKey: `auto-queue:clear:${wsId}`,
		});

		// Reset state
		await updateAutoPostState(
			{
				currentQueueIndex: 0,
				postsToday: 0,
				accountPostCounts: {},
			},
			wsId,
		);

		log.debug("Queue cleared");
		return true;
	} catch (error) {
		log.error("Failed to clear queue:", error);
		return false;
	}
};

function hashQueueContent(value: string): string {
	let hash = 2166136261;
	for (let i = 0; i < value.length; i += 1) {
		hash ^= value.charCodeAt(i);
		hash = Math.imul(hash, 16777619);
	}
	return (hash >>> 0).toString(16);
}
