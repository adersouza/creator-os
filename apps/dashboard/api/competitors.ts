/**
 * Consolidated Competitors API Route (thin router)
 *
 * POST /api/competitors?action=search|add|sync|queue-sync-all|oembed|fetch-top-posts|lookup-post|ig-search|ig-add|ig-sync|ig-business-discovery|ig-detect-alerts
 * GET  /api/competitors?action=top-posts|aggregated-top-posts|ig-benchmarks|ig-content-breakdown|ig-comparison-history
 *
 * All handler logic lives in api/_lib/handlers/competitors/.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import type { DbContext } from "./_lib/dbContext.js";
import { handleBulkAdd } from "./_lib/handlers/competitors/bulkAdd.js";
import { handleIgAdd } from "./_lib/handlers/competitors/instagram/add.js";
import {
	handleIgBenchmarks,
	handleIgContentBreakdown,
} from "./_lib/handlers/competitors/instagram/benchmarks.js";
import {
	handleIgComparisonHistory,
	handleIgDetectAlerts,
} from "./_lib/handlers/competitors/instagram/history.js";
// --- Instagram handlers ---
import {
	handleIgBusinessDiscovery,
	handleIgSearch,
} from "./_lib/handlers/competitors/instagram/search.js";
import { handleIgSync } from "./_lib/handlers/competitors/instagram/sync.js";
import { handleAdd } from "./_lib/handlers/competitors/threads/add.js";
import { handleLookupPost } from "./_lib/handlers/competitors/threads/lookupPost.js";
import { handleOembed } from "./_lib/handlers/competitors/threads/oembed.js";
import {
	handleAggregatedTopPosts,
	handleFetchTopPosts,
	handleGetTopPosts,
} from "./_lib/handlers/competitors/threads/posts.js";
import {
	handleBulkRemove,
	handleRemove,
} from "./_lib/handlers/competitors/threads/remove.js";
// --- Threads handlers ---
import { handleSearch } from "./_lib/handlers/competitors/threads/search.js";
import {
	handleQueueSyncAll,
	handleSync,
} from "./_lib/handlers/competitors/threads/sync.js";
import { logger } from "./_lib/logger.js";
import { withAuthDb } from "./_lib/middleware.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";
import { requireMinTier } from "./_lib/tierGate.js";
import { parseQueryOrError } from "./_lib/validation.js";
import { z } from "./_lib/zodCompat.js";

const ListQuerySchema = z.object({
	accountId: z.string().optional(),
	action: z.string().optional(),
});

type ApiUser = DbContext["user"];
type UserDb = DbContext["userDb"];

// Inline list handler — returns all tracked competitors for the authenticated user
async function handleList(
	req: VercelRequest,
	res: VercelResponse,
	user: ApiUser,
	userDb: UserDb,
) {
	const parsed = parseQueryOrError(res, ListQuerySchema, req.query);
	if (!parsed) return;

	const tQuery = userDb
		.from("competitors")
		.select(
			"id, user_id, username, threads_user_id, display_name, bio, avatar_url, follower_count, is_verified, added_at, last_synced_at, platform, human_verified",
		)
		.eq("user_id", user.id);
	const { data: threads, error: threadsError } = await tQuery.limit(500);
	if (threadsError) {
		logger.error("[competitors] Failed to fetch Threads competitors", {
			error: threadsError.message,
			userId: user.id,
		});
		return apiError(res, 500, "Failed to load competitors");
	}

	const igQuery = userDb
		.from("instagram_competitors")
		.select(
			"id, user_id, username, ig_user_id, display_name, bio, profile_pic_url, followers_count, media_count, is_verified, created_at, updated_at",
		)
		.eq("user_id", user.id);
	const { data: instagram, error: igError } = await igQuery.limit(500);
	if (igError) {
		logger.error("[competitors] Failed to fetch IG competitors", {
			error: igError.message,
			userId: user.id,
		});
		return apiError(res, 500, "Failed to load competitors");
	}

	return apiSuccess(res, {
		competitors: [...(threads || []), ...(instagram || [])],
	});
}

// Action -> handler map
const actionHandlers: Record<
	string,
	(
		req: VercelRequest,
		res: VercelResponse,
		user?: { id: string; email?: string | undefined },
	) => Promise<VercelResponse | undefined>
> = {
	"bulk-add": handleBulkAdd,
	// Threads
	search: handleSearch,
	add: handleAdd,
	remove: handleRemove,
	"bulk-remove": handleBulkRemove,
	sync: handleSync,
	"queue-sync-all": handleQueueSyncAll,
	oembed: handleOembed,
	"fetch-top-posts": handleFetchTopPosts,
	"top-posts": handleGetTopPosts,
	"aggregated-top-posts": handleAggregatedTopPosts,
	"lookup-post": handleLookupPost,
	// Instagram
	"ig-search": handleIgSearch,
	"ig-add": handleIgAdd,
	"ig-sync": handleIgSync,
	"ig-business-discovery": handleIgBusinessDiscovery,
	"ig-benchmarks": handleIgBenchmarks,
	"ig-content-breakdown": handleIgContentBreakdown,
	"ig-comparison-history": handleIgComparisonHistory,
	"ig-detect-alerts": handleIgDetectAlerts,
	// Lazy-loaded consolidated handlers
	analyze: async (req, res) =>
		(await import("./_lib/handlers/competitors-sub/analyze.js")).default(
			req,
			res,
		),
	avatar: async (req, res) =>
		(await import("./_lib/handlers/competitors-sub/avatar.js")).default(
			req,
			res,
		),
	media: async (req, res) =>
		(await import("./_lib/handlers/competitors-sub/media.js")).default(
			req,
			res,
		),
};

// Actions that require POST method (write operations)
const postActions = new Set([
	"search",
	"add",
	"remove",
	"bulk-remove",
	"bulk-add",
	"sync",
	"queue-sync-all",
	"oembed",
	"fetch-top-posts",
	"lookup-post",
	"ig-search",
	"ig-add",
	"ig-sync",
	"ig-business-discovery",
	"ig-detect-alerts",
]);

// Actions that require GET method (read operations)
const getActions = new Set([
	"list",
	"top-posts",
	"aggregated-top-posts",
	"ig-benchmarks",
	"ig-content-breakdown",
	"ig-comparison-history",
]);

export const config = { maxDuration: 120 };

export default withAuthDb(
	async (req, res, { user, userDb }): Promise<VercelResponse> => {
		// Rate limit: 60 req/min per user
		const action = req.query.action as string;
		const isWrite = postActions.has(action);
		const allowed = await enforceRouteRateLimit(res, {
			key: `competitors-${isWrite ? "write" : "read"}:${user.id}`,
			limit: 60,
			windowSeconds: 60,
			failMode: isWrite ? "closed" : "open",
			message: "Rate limit exceeded",
		});
		if (!allowed) return res;

		// Competitor tracking requires Pro tier
		if (!(await requireMinTier(user.id, "pro", res))) return res;

		// Enforce HTTP method per action
		if (postActions.has(action) && req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}
		if (getActions.has(action) && req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		try {
			if (action === "list") {
				return (await handleList(req, res, user, userDb)) as VercelResponse;
			}
			const handle = actionHandlers[action];
			if (!handle) {
				return apiError(res, 400, `Unknown action: ${action}`);
			}
			return (await handle(req, res, user)) as VercelResponse;
		} catch (error: unknown) {
			logger.error("Competitors API error", { error: String(error) });
			return apiError(res, 500, "Internal server error");
		}
	},
);
