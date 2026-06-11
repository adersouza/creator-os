/**
 * Auto-Post API Route — Thin Router
 * POST /api/auto-post?action=<action>
 *
 * Handler logic split into focused modules under _lib/handlers/auto-post/route/
 */

import { apiError } from "./_lib/apiResponse.js";
import { logAudit, trackUsage } from "./_lib/auditLog.js";
// --- Config handlers ---
import {
	handleDeleteAccountOverride,
	handleDeleteGroupConfig,
	handleGetAccountOverrides,
	handleGetGroupConfigs,
	handleGetWorkspaceConfig,
	handleToggleGroupMode,
	handleUpsertAccountOverride,
	handleUpsertGroupConfig,
	handleUpsertWorkspaceConfig,
} from "./_lib/handlers/auto-post/route/configHandlers.js";
// --- Content handlers ---
import {
	handleBulkSetContentStrategy,
	handleBulkUpdateGroupConfigs,
	handleCompetitorPostsSample,
	handleGetAccountBios,
	handleGetVariants,
	handlePromoteVariant,
} from "./_lib/handlers/auto-post/route/contentHandlers.js";
import { handleBackfillAccountDna } from "./_lib/handlers/auto-post/route/dnaHandlers.js";
// --- Engagement handlers ---
import {
	handleFetchEngagement,
	handleLogActivity,
	handleSyncEngagement,
} from "./_lib/handlers/auto-post/route/engagementHandlers.js";
// --- Monitoring handlers ---
import {
	handleGetAccountHealth,
	handleGetAutoReplyQueue,
	handleGetPublishLog,
	handleHealthCheck,
	handleToggleAutoReply,
	handleVerifyAutoposterState,
} from "./_lib/handlers/auto-post/route/monitoringHandlers.js";
// --- Queue handlers ---
import {
	handleAddQueueItems,
	handleBulkClearAllQueues,
	handleBulkClearQueue,
	handleDeleteQueueItem,
	handleGetFilterRejections,
	handleGetGroupQueue,
	handleGetQueueCounts,
	handleGetReplyChainStats,
	handleQueueContentAudit,
	handleReorderQueue,
	handleRetryDeadLetter,
	handleTriggerQueueFill,
} from "./_lib/handlers/auto-post/route/queueHandlers.js";
import { withIdempotency } from "./_lib/idempotency.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";

const IDEMPOTENT_HIGH_RISK_ACTIONS = new Set([
	"retry-dead-letter",
	"trigger-queue-fill",
	"bulk-clear-queue",
	"bulk-clear-all-queues",
	"delete-queue-item",
	"add-queue-items",
	"reorder-queue",
	"upsert-workspace-config",
	"upsert-group-config",
	"delete-group-config",
	"toggle-group-mode",
	"override-account-state",
	"backfill-account-dna",
]);

export default withAuth(async (req, res, user) => {
	// Check required environment variables
	const missingEnvVars: string[] = [];
	if (!process.env.SUPABASE_URL) missingEnvVars.push("SUPABASE_URL");
	if (
		!process.env.SUPABASE_SERVICE_ROLE_KEY &&
		!process.env.SUPABASE_SERVICE_KEY
	) {
		missingEnvVars.push("SUPABASE_SERVICE_ROLE_KEY");
	}

	if (missingEnvVars.length > 0) {
		logger.error("Missing environment variables", { missingEnvVars });
		return apiError(
			res,
			500,
			`Server configuration error: missing ${missingEnvVars.join(", ")}`,
		);
	}

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;
	const userId = user.id;

	return withIdempotency(
		req,
		res,
		{
			userId,
			route: "auto-post",
			action,
			enabled: IDEMPOTENT_HIGH_RISK_ACTIONS.has(action),
			requireKey: IDEMPOTENT_HIGH_RISK_ACTIONS.has(action),
			failClosed: IDEMPOTENT_HIGH_RISK_ACTIONS.has(action),
		},
		async () => {
			try {
				switch (action) {
					case "log-activity":
						trackUsage(userId, "auto-post.log-activity");
						return handleLogActivity(req, res, userId);
					case "sync-engagement":
						trackUsage(userId, "auto-post.sync-engagement");
						return handleSyncEngagement(req, res, userId);
					case "fetch-engagement":
						trackUsage(userId, "auto-post.fetch-engagement");
						return handleFetchEngagement(req, res, userId);
					case "get-group-configs":
						return handleGetGroupConfigs(req, res, userId);
					case "get-workspace-config":
						return handleGetWorkspaceConfig(req, res, userId);
					case "upsert-workspace-config":
						logAudit(userId, "auto-post.upsert-workspace-config", { req });
						return handleUpsertWorkspaceConfig(req, res, userId);
					case "upsert-group-config":
						logAudit(userId, "auto-post.upsert-config", { req });
						return handleUpsertGroupConfig(req, res, userId);
					case "delete-group-config":
						logAudit(userId, "auto-post.delete-config", { req });
						return handleDeleteGroupConfig(req, res, userId);
					case "toggle-group-mode":
						logAudit(userId, "auto-post.toggle-mode", { req });
						return handleToggleGroupMode(req, res, userId);
					case "get-group-queue":
						return handleGetGroupQueue(req, res, userId);
					case "health-check":
						return handleHealthCheck(req, res, userId);
					case "get-auto-reply-queue":
						return handleGetAutoReplyQueue(req, res, userId);
					case "toggle-auto-reply":
						logAudit(userId, "auto-post.toggle-auto-reply", { req });
						return handleToggleAutoReply(req, res, userId);
					case "get-account-overrides":
						return handleGetAccountOverrides(req, res, userId);
					case "upsert-account-override":
						logAudit(userId, "auto-post.upsert-account-override", { req });
						return handleUpsertAccountOverride(req, res, userId);
					case "delete-account-override":
						logAudit(userId, "auto-post.delete-account-override", { req });
						return handleDeleteAccountOverride(req, res, userId);
					case "bulk-clear-queue":
						logAudit(userId, "auto-post.bulk-clear-queue", { req });
						return handleBulkClearQueue(req, res, userId);
					case "bulk-clear-all-queues":
						logAudit(userId, "auto-post.bulk-clear-all-queues", { req });
						return handleBulkClearAllQueues(req, res, userId);
					case "get-queue-counts":
						return handleGetQueueCounts(req, res, userId);
					case "delete-queue-item":
						logAudit(userId, "auto-post.delete-queue-item", { req });
						return handleDeleteQueueItem(req, res, userId);
					case "add-queue-items":
						logAudit(userId, "auto-post.add-queue-items", { req });
						return handleAddQueueItems(req, res, userId);
					case "reorder-queue":
						logAudit(userId, "auto-post.reorder-queue", { req });
						return handleReorderQueue(req, res, userId);
					case "stats":
						return (await import("./_lib/handlers/auto-post/stats.js")).default(
							req,
							res,
							userId,
						);
					case "get-reply-chain-stats":
						return handleGetReplyChainStats(req, res, userId);
					case "queue-content-audit":
						return handleQueueContentAudit(req, res, userId);
					case "bulk-update-group-configs":
						logAudit(userId, "auto-post.bulk-update-group-configs", { req });
						return handleBulkUpdateGroupConfigs(req, res, userId);
					case "bulk-set-content-strategy":
						logAudit(userId, "auto-post.bulk-set-content-strategy", { req });
						return handleBulkSetContentStrategy(req, res, userId);
					case "get-account-bios":
						return handleGetAccountBios(req, res, userId);
					case "competitor-posts-sample":
						return handleCompetitorPostsSample(req, res, userId);
					case "ops-dashboard":
						return (
							await import("./_lib/handlers/auto-post/opsDashboard.js")
						).default(req, res, userId);
					case "verify-autoposter-state":
						return handleVerifyAutoposterState(req, res, userId);
					case "get-publish-log":
						return handleGetPublishLog(req, res, userId);
					case "get-account-health":
						return handleGetAccountHealth(req, res, userId);
					case "backfill-account-dna":
						logAudit(userId, "auto-post.backfill-account-dna", { req });
						return handleBackfillAccountDna(req, res, userId);
					case "retry-dead-letter":
						logAudit(userId, "auto-post.retry-dead-letter", { req });
						return handleRetryDeadLetter(req, res, userId);
					case "trigger-queue-fill":
						logAudit(userId, "auto-post.trigger-queue-fill", { req });
						return handleTriggerQueueFill(req, res, userId);
					case "get-filter-rejections":
						return handleGetFilterRejections(req, res, userId);
					case "get-account-states":
						return (
							await import("./_lib/handlers/auto-post/stateHandlers.js")
						).handleGetAccountStates(req, res, userId);
					case "get-queue-fill-explain":
						return (
							await import("./_lib/handlers/auto-post/stateHandlers.js")
						).handleGetQueueFillExplain(req, res, userId);
					case "override-account-state":
						logAudit(userId, "auto-post.override-account-state", { req });
						return (
							await import("./_lib/handlers/auto-post/stateHandlers.js")
						).handleOverrideAccountState(req, res, userId);
					case "get-autoposter-snapshot":
						return (
							await import("./_lib/handlers/auto-post/stateHandlers.js")
						).handleGetAutoposterSnapshot(req, res, userId);
					case "variants":
						return handleGetVariants(req, res, userId);
					case "promote-variant":
						logAudit(userId, "auto-post.promote-variant", { req });
						return handlePromoteVariant(req, res, userId);
					default:
						return apiError(res, 400, `Unknown action: ${action}`);
				}
			} catch (error: unknown) {
				logger.error("Auto-post API error", { error: String(error) });
				return apiError(res, 500, "Internal server error");
			}
		},
	);
});
