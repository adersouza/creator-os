/**
 * Posts API Route — thin router that delegates to handler modules.
 * POST /api/posts?action=publish|delete|repost|...
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./_lib/apiResponse.js";
import { logAudit, trackUsage } from "./_lib/auditLog.js";
import {
	handleApproval,
	handleBulkScheduleGroups,
	handleCampaignFactoryAudioAction,
	handleCampaignFactoryAudioEvents,
	handleCampaignSchedule,
	handleCampaignSchedulePlan,
	handleCampaignScheduleReport,
	handleCampaignScheduleTimePlan,
	handleDelete,
	handleDeleteBulk,
	handleGhostPosts,
	handleHandoff,
	handleHandoffEvent,
	handleHandoffFollowUp,
	handleImportPosts,
	handleInstagramAccountRestrictions,
	handleLookupPost,
	handlePreflight,
	handlePublish,
	handleRefreshMetrics,
	handleRepost,
	handleReschedule,
	handleSchedule,
	handleSearchLocations,
	handleThreadChain,
	handleUpdateDraft,
} from "./_lib/handlers/posts/index.js";
import { withIdempotency } from "./_lib/idempotency.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import { createPublishJob, wantsAsyncPublish } from "./_lib/publishJobs.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";

type PostsActionHandler = (
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) => Promise<VercelResponse | undefined>;

type PostsActionConfig = {
	handler: PostsActionHandler;
	write?: boolean;
	idempotent?: boolean;
	reflectionRead?: boolean;
};

const REQUIRE_IDEMPOTENCY_KEY_ACTIONS = new Set([
	"publish",
	"delete",
	"repost",
	"delete-bulk",
	"reschedule",
	"schedule",
	"bulk-schedule-groups",
	"campaign-schedule",
]);

const POSTS_ACTIONS: Record<string, PostsActionConfig> = {
	publish: {
		write: true,
		idempotent: true,
		handler: async (req, res, userId) => {
			trackUsage(userId, "posts.publish");
			logAudit(userId, "post.publish", { req });
			if (wantsAsyncPublish(req)) return createPublishJob(req, res, userId);
			return handlePublish(req, res, userId);
		},
	},
	preflight: { handler: (req, res, userId) => handlePreflight(req, res, userId) },
	delete: {
		write: true,
		idempotent: true,
		handler: async (req, res, userId) => {
			logAudit(userId, "post.delete", { req });
			return handleDelete(req, res, userId);
		},
	},
	"thread-chain": { handler: (req, res, userId) => handleThreadChain(req, res, userId) },
	lookup: { handler: (req, res, userId) => handleLookupPost(req, res, userId) },
	"search-locations": { handler: (req, res, userId) => handleSearchLocations(req, res, userId) },
	approve: {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleApproval(req, res, userId, "approved"),
	},
	reject: {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleApproval(req, res, userId, "rejected"),
	},
	repost: {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleRepost(req, res, userId),
	},
	"refresh-metrics": {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleRefreshMetrics(req, res, userId),
	},
	"import-posts": {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleImportPosts(req, res, userId),
	},
	"delete-bulk": {
		write: true,
		idempotent: true,
		handler: async (req, res, userId) => {
			logAudit(userId, "post.delete-bulk", { req });
			return handleDeleteBulk(req, res, userId);
		},
	},
	reschedule: {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleReschedule(req, res, userId),
	},
	"update-draft": {
		write: true,
		handler: (req, res, userId) => handleUpdateDraft(req, res, userId),
	},
	schedule: {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleSchedule(req, res, userId),
	},
	"ghost-posts": { handler: (req, res, userId) => handleGhostPosts(req, res, userId) },
	handoff: { handler: (req, res, userId) => handleHandoff(req, res, userId) },
	"handoff-event": {
		write: true,
		handler: async (req, res, userId) => {
			logAudit(userId, "post.handoff-event", { req });
			return handleHandoffEvent(req, res, userId);
		},
	},
	"handoff-followup": {
		write: true,
		handler: async (req, res, userId) => {
			logAudit(userId, "post.handoff-followup", { req });
			return handleHandoffFollowUp(req, res, userId);
		},
	},
	"bulk-schedule-groups": {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleBulkScheduleGroups(req, res, userId),
	},
	"campaign-schedule": {
		write: true,
		idempotent: true,
		handler: (req, res, userId) => handleCampaignSchedule(req, res, userId),
	},
	"campaign-schedule-report": {
		handler: (req, res, userId) => handleCampaignScheduleReport(req, res, userId),
	},
	"campaign-schedule-plan": {
		handler: (req, res, userId) => handleCampaignSchedulePlan(req, res, userId),
	},
	"campaign-schedule-time-plan": {
		handler: (req, res, userId) => handleCampaignScheduleTimePlan(req, res, userId),
	},
	"instagram-account-restrictions": {
		write: true,
		handler: (req, res, userId) => handleInstagramAccountRestrictions(req, res, userId),
	},
	"campaign-factory-audio": {
		write: true,
		handler: (req, res, userId) => handleCampaignFactoryAudioAction(req, res, userId),
	},
	"campaign-factory-audio-events": {
		handler: (req, res, userId) => handleCampaignFactoryAudioEvents(req, res, userId),
	},
	autopsy: {
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/autopsy.js")).default(req, res),
	},
	"bulk-cancel": {
		write: true,
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/bulk-cancel.js")).default(req, res),
	},
	classify: {
		write: true,
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/classify.js")).default(req, res),
	},
	comments: {
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/comments.js")).default(req, res),
	},
	evergreen: {
		write: true,
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/evergreen.js")).default(req, res),
	},
	reflection: {
		reflectionRead: true,
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/reflection.js")).default(req, res),
	},
	"sentiment-scan": {
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/sentiment-scan.js")).default(req, res),
	},
	"sentiment-summary": {
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/sentiment-summary.js")).default(req, res),
	},
	signal: {
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/signal.js")).default(req, res),
	},
	"draft-folders": {
		write: true,
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/draft-folders.js")).default(req, res),
	},
	templates: {
		write: true,
		handler: async (req, res) =>
			(await import("./_lib/handlers/posts-sub/templates.js")).default(req, res),
	},
};

export default withAuth(async (req, res, user) => {
	const action = req.query.action as string;
	const actionConfig = POSTS_ACTIONS[action];

	// Reflection reads are lightweight DB lookups — use a separate, higher rate limit
	const isReflectionRead = actionConfig?.reflectionRead === true && req.method === "GET";
	const isWrite = actionConfig?.write === true;
	const allowed = await enforceRouteRateLimit(res, {
		key: isReflectionRead
			? `posts-reflection:${user.id}`
			: `posts-${isWrite ? "write" : "read"}:${user.id}`,
		limit: isReflectionRead ? 200 : 60,
		windowSeconds: 60,
		failMode: isWrite ? "closed" : "open",
		message: "Rate limit exceeded",
	});
	if (!allowed) return;

	const userId = user.id;

	if (req.method !== "POST" && req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	return withIdempotency(
		req,
		res,
			{
				userId,
				route: "posts",
				action,
				enabled: req.method === "POST" && actionConfig?.idempotent === true,
				requireKey: REQUIRE_IDEMPOTENCY_KEY_ACTIONS.has(action),
				failClosed: REQUIRE_IDEMPOTENCY_KEY_ACTIONS.has(action),
			},
		async () => {
			try {
				if (!actionConfig) return apiError(res, 400, `Unknown action: ${action}`);
				return actionConfig.handler(req, res, userId);
			} catch (error: unknown) {
				logger.error("Posts API error", { error: String(error) });
				return apiError(res, 500, "Internal server error");
			}
		},
	);
});
